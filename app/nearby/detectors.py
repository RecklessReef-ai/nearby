"""Detectors. Plain code that reads the phone book's counts and flags the odd.

Three checks, per device:
  new names   a gadget asks for somewhere it never asked for before
  steady beat a gadget asks for the same name on a fixed beat, the pattern of something reporting in
  odd hours   a gadget is far busier in the small hours than it usually is

Times are used here, inside the house, to measure beats and nights. What comes
out is words and counts only: no address, no clock time. That is all the brain
is ever shown, and counters.as_text checks it again before anything leaves.

The baseline is short on purpose so this works in a hackathon week: one earlier
day of being heard is enough to judge "new" and "usual". A real house wants two weeks.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

from . import counters, find

ODD = find.DATA_DIR / "odd.json"
NIGHTS = find.DATA_DIR / "nights.json"

NIGHT = (1, 5)            # the small hours, house time: from 1 up to 5
MIN_BEATS = 8             # a beat needs at least this many even gaps in a row
BEAT_RANGE = (20, 3600)   # seconds; faster is a retry storm, slower is not a beat we can call in a day
BEAT_SLACK = 0.15         # a gap counts as "on the beat" within 15% of the usual gap
BEAT_SHARE = 0.8          # and four in five gaps must be on it
NIGHT_FLOOR = 30          # fewer lookups than this in a night is never odd
NIGHT_TIMES = 3           # odd means this many times the usual night
KEEP_NIGHTS = 14

# People browse, so a new name from a phone or laptop means nothing.
PEOPLE = {"phone", "phone_or_laptop", "this_computer"}
# Clocks and "am I online" checks beat all day on every gadget. Not worth a flag.
ROUTINE = ("time.", "time-", "ntp.", "pool.", "connectivitycheck.", "connectivity-check.", "captive.", "msftconnecttest.", "detectportal.")


def beat(times: list[datetime]) -> float | None:
    """The usual gap in seconds if these lookups arrive on a steady beat, else None."""
    ts = sorted(times)
    events = [ts[0]] if ts else []
    for t in ts[1:]:
        if (t - events[-1]).total_seconds() > 2:  # a name is often asked for twice at once (two address kinds)
            events.append(t)
    gaps = [(b - a).total_seconds() for a, b in zip(events, events[1:])]
    if len(gaps) < MIN_BEATS:
        return None
    usual = median(gaps)
    if not BEAT_RANGE[0] <= usual <= BEAT_RANGE[1]:
        return None
    on_beat = sum(1 for g in gaps if abs(g - usual) <= BEAT_SLACK * usual)
    return usual if on_beat / len(gaps) >= BEAT_SHARE else None


def every(seconds: float) -> str:
    if seconds < 90:
        return f"{max(5, round(seconds / 5) * 5)} seconds"
    minutes = round(seconds / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def detect(entries: list[dict], by_ip: dict, known: dict[str, set[str]], nights: dict, now: datetime) -> tuple[list[dict], dict[str, int]]:
    """Pure: a day of phone-book entries in, findings out. Returns (findings, tonight's lookups per device).

    known:  for each device, the names it asked for before today (empty or missing = first day being heard).
    nights: for each device, {day: lookups in the small hours} for earlier days.
    """
    today = now.date()
    per: dict[str, dict] = defaultdict(lambda: {"by_name": defaultdict(list), "today": Counter(), "night": 0})
    for e in entries:
        ip = e.get("client", "")
        dev = by_ip.get(ip)
        name = (e.get("question") or {}).get("name", "").lower().rstrip(".")
        if not name:
            continue
        t = counters.when(e).astimezone(now.tzinfo)
        p = per[counters.device_key(ip, by_ip)]
        p.setdefault("label", counters.label_for(e, dev))
        p.setdefault("kind", (dev or {}).get("kind", "unknown"))
        p["by_name"][name].append(t)
        if t.date() == today:
            p["today"][counters.registrable(name)] += 1
            if NIGHT[0] <= t.hour < NIGHT[1]:
                p["night"] += 1

    findings: list[dict] = []
    tonight: dict[str, int] = {}
    for key, p in per.items():
        if p["kind"] == "this_computer":
            continue
        tonight[key] = p["night"]

        def found(kind: str, text: str, names: list[str]) -> None:
            findings.append({"key": key, "label": p["label"], "device_kind": p["kind"], "type": kind, "text": text, "names": names})

        # new names
        before = known.get(key) or set()
        if before and p["kind"] not in PEOPLE:
            new = [n for n, _ in p["today"].most_common() if n not in before]
            if new:
                more = f" and {len(new) - 3} more" if len(new) > 3 else ""
                found("new_names", f"asked for {len(new)} name{'s' if len(new) != 1 else ''} it never asked for before: {', '.join(new[:3])}{more}.", new[:8])

        # steady beat: one finding per site, the busiest name wins
        beats: dict[str, tuple[int, float]] = {}
        for name, times in p["by_name"].items():
            if name.startswith(ROUTINE):
                continue
            gap = beat(times)
            if gap:
                site = counters.registrable(name)
                if site not in beats or len(times) > beats[site][0]:
                    beats[site] = (len(times), gap)
        for site, (n, gap) in sorted(beats.items(), key=lambda kv: -kv[1][0])[:3]:
            found("steady_beat", f"asks for {site} on a steady beat, about every {every(gap)}, {n} times in the last day. That is the pattern of something reporting in.", [site])

        # odd hours
        earlier = [v for d, v in (nights.get(key) or {}).items() if d < today.isoformat()]
        if earlier and now.hour >= NIGHT[0]:
            usual = sum(earlier) / len(earlier)
            if p["night"] >= max(NIGHT_FLOOR, NIGHT_TIMES * usual):
                found("odd_hours", f"was busy in the middle of the night: {p['night']} lookups while the house slept. Its usual night is about {round(usual)}.", [])
    return findings, tonight


def _read(path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def run(now: datetime | None = None) -> list[dict]:
    """Read the last day from the phone book, run the three checks, remember what was learned. Saves data/odd.json."""
    now = now or datetime.now().astimezone()
    today = now.date().isoformat()
    state = find.load()
    by_ip = find.by_ip(state)
    entries = counters.fetch_log(now - timedelta(hours=24))

    names_today: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if counters.when(e).astimezone(now.tzinfo).date().isoformat() == today:
            names_today[counters.device_key(e.get("client", ""), by_ip)].append(counters.registrable((e.get("question") or {}).get("name", "")))
    known = counters.known_before({k: sorted(set(v)) for k, v in names_today.items()}, today)

    nights = _read(NIGHTS)
    findings, tonight = detect(entries, by_ip, known, nights, now)
    if now.hour >= NIGHT[1]:  # the night is over; it becomes part of "usual"
        for key, n in tonight.items():
            days = nights.setdefault(key, {})
            days[today] = n
            for old in sorted(days)[:-KEEP_NIGHTS]:
                del days[old]
    lookups = Counter(counters.device_key(e.get("client", ""), by_ip) for e in entries)
    asked: dict[str, Counter] = defaultdict(Counter)  # the sites each device asked for in the last day, for the card and the single-name block
    for e in entries:
        site = counters.registrable((e.get("question") or {}).get("name", "").lower().rstrip("."))
        if counters.is_site(site):
            asked[counters.device_key(e.get("client", ""), by_ip)][site] += 1
    names = {k: c.most_common(15) for k, c in asked.items()}
    learning = sorted(k for k in tonight if not known.get(k))  # first day being heard: nothing to compare with yet
    find.DATA_DIR.mkdir(parents=True, exist_ok=True)
    NIGHTS.write_text(json.dumps(nights))
    ODD.write_text(json.dumps({"at": now.isoformat(timespec="seconds"), "heard": len(tonight), "learning": learning, "lookups": dict(lookups), "names": names, "findings": findings}, indent=2))
    return findings


def latest() -> dict:
    return {"at": None, "heard": 0, "learning": [], "lookups": {}, "names": {}, "findings": [], **_read(ODD)}
