"""Counters, not logs. Reads AdGuard Home's query log and boils a day down to a
few numbers and a few names per device. This is the only thing the brain is
ever shown. Capped in code: eight names per device, no addresses, no times.
"""
from __future__ import annotations

import json
import os
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime
from urllib.parse import urlencode
from urllib.request import urlopen

from . import find

ADGUARD = os.environ.get("ADGUARD_URL") or f"http://{find.load().get('me') or '127.0.0.1'}:3000"
BASELINE = find.DATA_DIR / "baseline.json"
TOP_N = 8
_TWO_LEVEL = {"co", "com", "net", "org", "gov", "ac", "edu"}
_ADDRESS = re.compile(r"\b(\d{1,3}\.){3}\d{1,3}\b|\b([0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b|\b[0-9a-f]{1,4}(::?[0-9a-f]{1,4}){2,7}\b|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}|\b\d{1,2}:\d{2}\b", re.I)
_SITE = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")


def is_site(name: str) -> bool:
    """True for a plain site name like example.co.uk, and nothing else. Anything that is not one never reaches a rule, a page or a model."""
    return bool(_SITE.fullmatch(name or ""))


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
            t = when(e)
            if t < since:
                return entries
            entries.append(e)
        older_than = page.get("oldest") or data[-1]["time"]
    return entries


_TIME = re.compile(r"^(.*?)(\.\d+)?(Z|[+-]\d\d:\d\d)?$")
_lock = threading.Lock()


def when(e: dict) -> datetime:
    """The moment of one phone-book entry, with its time zone. AdGuard writes nine decimals; Python reads six."""
    base, frac, zone = _TIME.match(e["time"]).groups()
    return datetime.fromisoformat(base + (frac or "")[:7] + ("+00:00" if zone in (None, "Z") else zone))


def device_key(ip: str, by_ip: dict) -> str:
    dev = by_ip.get(ip)
    return dev["mac"] if dev else f"ip:{ip}"


def label_for(e: dict, dev: dict | None) -> str:
    return (dev or {}).get("label") or (e.get("client_info") or {}).get("name") or "an unnamed device"


def _load_baseline() -> dict:
    """{device: {name: the day it was first asked for}}. Older files held plain lists; those count as 'before'."""
    try:
        raw = json.loads(BASELINE.read_text())
    except (OSError, ValueError):
        return {}
    return {k: (v if isinstance(v, dict) else {n: "" for n in v}) for k, v in raw.items()}


def known_before(names_by_device: dict[str, list[str]], day: str, learn: bool = True) -> dict[str, set[str]]:
    """For each device, the names it had asked for before `day`. With learn, today's names are remembered, dated today.
    Asking twice on the same day gives the same answer, so a second letter still knows what was new."""
    with _lock:
        baseline = _load_baseline()
        known = {k: {n for n, d in baseline.get(k, {}).items() if d < day} for k in names_by_device}
        if learn:
            for k, names in names_by_device.items():
                seen = baseline.setdefault(k, {})
                for n in names:
                    if len(seen) >= 2000:
                        break
                    seen.setdefault(n, day)
            find.DATA_DIR.mkdir(parents=True, exist_ok=True)
            BASELINE.write_text(json.dumps(baseline))
    return known


def summarize(day: date | None = None, update_baseline: bool = True) -> dict:
    """One day of the house as counters. Safe to show a model."""
    now = datetime.now().astimezone()  # the house's own clock: a day is midnight to midnight where the house is
    day = day or now.date()
    start = datetime(day.year, day.month, day.day).astimezone()
    state = find.load()
    by_ip = find.by_ip(state)
    log = fetch_log(start) if day == now.date() else []

    per: dict[str, dict] = defaultdict(lambda: {"lookups": 0, "blocked": 0, "names": Counter()})
    for e in log:
        ip = e.get("client", "")
        dev = by_ip.get(ip)
        p = per[device_key(ip, by_ip)]
        p["lookups"] += 1
        if str(e.get("reason", "")).startswith("Filtered"):
            p["blocked"] += 1
        p["names"][registrable(e.get("question", {}).get("name", ""))] += 1
        p.setdefault("label", label_for(e, dev))
        p.setdefault("kind", (dev or {}).get("kind", "unknown"))

    ranked = {key: [n for n, _ in p["names"].most_common()] for key, p in per.items()}
    before = known_before(ranked, day.isoformat(), learn=update_baseline)
    devices = []
    for key, p in per.items():
        known, names = before[key], ranked[key]
        new = [n for n in names if n not in known][:TOP_N]
        devices.append({
            "label": p["label"], "kind": p["kind"], "lookups": p["lookups"], "blocked": p["blocked"],
            "distinct_names": len(names), "top": names[:TOP_N], "new": new,
            "first_day": not known,
        })

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
        "note": "Only devices that use Nearby's phone book appear under 'watched'. Others are counted but not heard." if len(devices) < len(online) - 1 else "",
    }
    return summary


def ever_asked(key: str) -> list[str]:
    """Every site this device has asked for since Nearby began listening to it."""
    with _lock:
        return sorted(n for n in _load_baseline().get(key, {}) if "." in n)


def has_address(text: str) -> bool:
    """True if the text carries a network address, a hardware address or a timestamp. Nothing like that leaves the house."""
    return bool(_ADDRESS.search(text))


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
    if summary.get("odd"):
        lines.append("Noticed by the detectors:")
        lines += [f"- {f['label']}: {f['text']}" for f in summary["odd"][:6]]
    if summary["note"]:
        lines.append(summary["note"])
    text = "\n".join(lines)
    if _ADDRESS.search(text):
        raise ValueError("summary contains an address or a timestamp; refusing to send")
    return text
