"""The evening letter. Counters in, plain words out.

The letter is written on the box, by plain code, from a template. No model, and nothing leaves the house.
A brain that wants to say more reads the letter through the door, like everything else.
Each letter is saved with the counters it was written from.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import counters, detectors
from .find import DATA_DIR

LETTERS = DATA_DIR / "letters"


def write(force: bool = False, weekly: bool = False) -> dict | None:
    """Write tonight's letter. Returns None when the day was quiet and nothing forced it."""
    summary = counters.summarize()
    try:
        summary["odd"] = [{"label": f["label"], "type": f["type"], "text": f["text"]} for f in detectors.run()]
    except Exception:
        summary["odd"] = []
    summary["quiet"] = summary["quiet"] and not summary["odd"]
    if summary["quiet"] and not force and not weekly:
        return None
    result = local(summary)
    now = datetime.now().astimezone()  # the house's own clock, so an evening letter carries that evening's date
    record = {
        "date": now.date().isoformat(), "written_at": now.isoformat(timespec="seconds"), "weekly": weekly,
        "letter": result["letter"], "suggestions": result["suggestions"], "source": "local", "detail": "written on the box, from a template",
        "counters": summary,
    }
    LETTERS.mkdir(parents=True, exist_ok=True)
    stem = LETTERS / (record["date"] + ("-weekly" if weekly else ""))
    stem.with_suffix(".json").write_text(json.dumps(record, indent=2))
    stem.with_suffix(".md").write_text(as_markdown(record))
    return record


def as_markdown(r: dict) -> str:
    where = "written earlier by an outside model, before the box stopped calling out" if r["source"] == "sealed" else "written on the box, in plain words from a template"
    lines = [f"# Your house, {r['date']}", "", r["letter"], ""]
    if r["suggestions"]:
        lines += ["## Nearby suggests", ""] + [f"- **{s['action']}** the {s['device']}: {s['why']}" for s in r["suggestions"]] + [""]
    lines += ["---", f"{where}."]
    return "\n".join(lines)


def latest() -> dict | None:
    try:
        files = sorted(LETTERS.glob("*.json"))
        return json.loads(files[-1].read_text()) if files else None
    except (OSError, ValueError):
        return None


def all_letters() -> list[dict]:
    out = []
    for f in sorted(LETTERS.glob("*.json"), reverse=True):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            pass
    return out


def local(summary: dict) -> dict:
    """Plain words from a template. No model."""
    n = summary["devices_online"]
    parts = [f"Tonight {n} thing{'s' if n != 1 else ''} in your house {'are' if n != 1 else 'is'} online."]
    joined = summary["joined_today"]
    if joined and len(joined) >= max(2, n - 1):
        parts.append(f"This was Nearby's first day, so it met all {len(joined)} of them.")
    elif joined:
        parts.append("New today: " + ", ".join(joined) + ".")
    loud = sorted((d for d in summary["watched"] if d["kind"] != "this_computer"), key=lambda d: -d["lookups"])
    if loud:
        d = loud[0]
        names = "name" if d["lookups"] == 1 else "names"
        parts.append(f"The {d['label']} asked for {d['lookups']} {names}, mostly {', '.join(d['top'][:3])}." if d["top"] else f"The {d['label']} asked for {d['lookups']} {names}.")
        if d["new"] and not d["first_day"]:
            parts.append("New names it never asked for before: " + ", ".join(d["new"][:3]) + ".")
    else:
        parts.append("Nothing was pointed at the phone book today, so there is nothing to report on what was asked.")
    odd = summary.get("odd") or []
    if odd:
        f = odd[0]
        parts.append(f"One thing worth a look: the {f['label']} {f['text']}")
        if len(odd) > 1:
            parts.append(f"{len(odd) - 1} more on the house page.")
    else:
        parts.append("Nothing here needs you tonight.")
    return {"letter": " ".join(parts), "suggestions": []}
