"""Counters, not logs. Reads AdGuard Home's query log and boils a day down to a
few numbers and a few names per device. This is the only thing the brain is
ever shown. Capped in code: eight names per device, no addresses, no times.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from . import find

ADGUARD = os.environ.get("ADGUARD_URL") or f"http://{find.load().get('me') or '127.0.0.1'}:3000"
BASELINE = find.DATA_DIR / "baseline.json"
TOP_N = 8
_TWO_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu"}
_ADDRESS = re.compile(r"\b(\d{1,3}\.){3}\d{1,3}\b|\b([0-9a-f]{2}:){5}[0-9a-f]{2}\b|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", re.I)


def registrable(name: str) -> str:
    """samsungacr.com from xyz.samsungacr.com; bbc.co.uk from news.bbc.co.uk."""
    parts = name.lower().rstrip(".").split(".")
    if len(parts) >= 3 and parts[-2] in _TWO_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else name


def fetch_log(since: datetime, limit: int = 500) -> list[dict]:
    entries, older_than = [], ""
    for _ in range(200):  # at most 100k entries
        q = {"limit": limit}
        if older_than:
            q["older_than"] = older_than
        try:
            with urlopen(f"{ADGUARD}/control/querylog?{urlencode(q)}", timeout=10) as r:
                page = json.loads(r.read())
        except Exception:
            break
        data = page.get("data") or []
        if not data:
            break
        for e in data:
            t = datetime.fromisoformat(e["time"].replace("Z", "+00:00")[:26] + "+00:00") if "." in e["time"] else datetime.fromisoformat(e["time"].replace("Z", "+00:00"))
            if t < since:
                return entries
            entries.append(e)
        older_than = page.get("oldest") or data[-1]["time"]
    return entries


def _load_baseline() -> dict:
    try:
        return json.loads(BASELINE.read_text())
    except (OSError, ValueError):
        return {}


def summarize(day: date | None = None, update_baseline: bool = True) -> dict:
    """One day of the house as counters. Safe to show a model."""
    day = day or datetime.now(timezone.utc).date()
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    state = find.load()
    by_ip = {d["ip"]: d for d in state.get("devices", {}).values()}
    log = fetch_log(start) if day == datetime.now(timezone.utc).date() else []
    baseline = _load_baseline()

    per: dict[str, dict] = defaultdict(lambda: {"lookups": 0, "blocked": 0, "names": Counter()})
    for e in log:
        ip = e.get("client", "")
        dev = by_ip.get(ip)
        key = dev["mac"] if dev else f"ip:{ip}"
        p = per[key]
        p["lookups"] += 1
        if str(e.get("reason", "")).startswith("Filtered"):
            p["blocked"] += 1
        p["names"][registrable(e.get("question", {}).get("name", ""))] += 1
        p.setdefault("label", (dev or {}).get("label") or (e.get("client_info") or {}).get("name") or "an unnamed device")
        p.setdefault("kind", (dev or {}).get("kind", "unknown"))

    devices = []
    for key, p in per.items():
        known = set(baseline.get(key, []))
        names = [n for n, _ in p["names"].most_common()]
        new = [n for n in names if n not in known][:TOP_N]
        devices.append({
            "label": p["label"], "kind": p["kind"], "lookups": p["lookups"], "blocked": p["blocked"],
            "distinct_names": len(names), "top": names[:TOP_N], "new": new,
            "first_day": not known,
        })
        if update_baseline:
            baseline[key] = sorted(known | set(names))[:2000]
    if update_baseline:
        find.DATA_DIR.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(baseline))

    online = [d for d in state.get("devices", {}).values() if d.get("online")]
    joined_today = [d["label"] for d in online if (d.get("first_seen") or "")[:10] == day.isoformat() and d["kind"] != "this_computer"]
    quiet = not devices and not joined_today
    summary = {
        "day": day.isoformat(),
        "devices_online": len([d for d in online if d["kind"] != "this_computer"]),
        "joined_today": joined_today,
        "watched": devices,
        "total_lookups": sum(d["lookups"] for d in devices),
        "quiet": quiet,
        "note": "Only devices pointed at this computer's phone book appear under 'watched'. Others are counted but not heard." if len(devices) < len(online) - 1 else "",
    }
    return summary


def as_text(summary: dict) -> str:
    """The exact words the brain sees. No addresses, no times, by construction and then checked."""
    lines = [f"Day: {summary['day']}. Devices online: {summary['devices_online']}."]
    if summary["joined_today"]:
        lines.append("Joined today: " + ", ".join(summary["joined_today"]) + ".")
    for d in summary["watched"]:
        head = f"- {d['label']} ({d['kind'].replace('_', ' ')}): {d['lookups']} lookups, {d['distinct_names']} different names, {d['blocked']} quieted."
        if d["first_day"]:
            head += " First day being heard."
        lines.append(head)
        if d["top"]:
            lines.append("  asked most for: " + ", ".join(d["top"]))
        if d["new"] and not d["first_day"]:
            lines.append("  new today: " + ", ".join(d["new"]))
    if summary["note"]:
        lines.append(summary["note"])
    text = "\n".join(lines)
    if _ADDRESS.search(text):
        raise ValueError("summary contains an address or a timestamp; refusing to send")
    return text
