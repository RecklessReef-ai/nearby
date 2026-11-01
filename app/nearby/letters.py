"""The evening letter. Counters in, plain words out, signed by the house key.

Each letter is saved with the exact counters that were sent, the day's proof,
where the words came from (sealed brain or local template), and a signature.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import brain, counters, housekey
from .find import DATA_DIR

LETTERS = DATA_DIR / "letters"


def write(force: bool = False, weekly: bool = False) -> dict | None:
    """Write tonight's letter. Returns None when the day was quiet and nothing forced it."""
    summary = counters.summarize()
    if summary["quiet"] and not force and not weekly:
        return None
    sent = counters.as_text(summary)
    labels = {d["label"] for d in summary["watched"]} | set(summary["joined_today"])
    proof = brain.morning_check()
    source, detail = "local", ""
    result = None
    if proof.get("ok"):
        try:
            reply = brain.ask(sent, proof)
            result = brain.parse_reply(reply["text"], labels)
            source, detail = "sealed", reply["verified"]
            result["tokens"] = reply["tokens"]
        except Exception as e:
            detail = f"sealed brain unavailable: {e}"
    else:
        detail = proof.get("error", "not sealed today")
    if result is None:
        result = brain.local_letter(summary)
    now = datetime.now(timezone.utc)
    record = {
        "date": now.date().isoformat(), "written_at": now.isoformat(timespec="seconds"), "weekly": weekly,
        "letter": result["letter"], "suggestions": result["suggestions"], "source": source, "detail": detail,
        "model": brain.MODEL if source == "sealed" else None, "tokens": result.get("tokens", 0),
        "sent_to_brain": sent if source == "sealed" else None, "counters": summary,
        "proof": {k: proof.get(k) for k in ("ok", "model", "checked_at", "signing_address", "checks", "error")},
        "house": housekey.account_id(),
    }
    record["signature"] = housekey.sign(record["letter"].encode("utf-8"))
    LETTERS.mkdir(parents=True, exist_ok=True)
    stem = LETTERS / (record["date"] + ("-weekly" if weekly else ""))
    stem.with_suffix(".json").write_text(json.dumps(record, indent=2))
    stem.with_suffix(".md").write_text(as_markdown(record))
    return record


def as_markdown(r: dict) -> str:
    where = "written in a sealed room on NEAR AI Cloud" if r["source"] == "sealed" else "written here, in plain words from a template"
    lines = [f"# Your house, {r['date']}", "", r["letter"], ""]
    if r["suggestions"]:
        lines += ["## Nearby suggests", ""] + [f"- **{s['action']}** the {s['device']}: {s['why']}" for s in r["suggestions"]] + [""]
    lines += ["---", f"{where}. " + (f"Sealed brain checked {r['proof']['checked_at'][:16]} UTC; {r['detail']}." if r["source"] == "sealed" else f"({r['detail']})"),
              f"Signed by this house's key `{r['house'][:12]}…`: `{r['signature'][:24]}…`"]
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
