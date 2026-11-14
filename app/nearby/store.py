"""The home's tables. One small database on the box: data/nearby.db.

The JSON files are still what Nearby works from minute to minute. After every look at the house the same facts are
written here as rows, so they build up over days and can be asked about: by the owner, and by a brain through the door.

The tables are laid out for a whole home, not only its network. Every device and every reading belongs to an area:
network, power, air, water, food. Only network has rows today. `readings` and `automations` are empty and waiting.

A brain never sees a hardware address or a network address. `devices.mac` and `changes.mac` are the only columns that
hold one, they are never in what `describe` or `rows` give out, and no table holds a network address at all.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime

from . import detectors, find, fixes

DB = find.DATA_DIR / "nearby.db"
AREAS = ("network", "power", "air", "water", "food")
_lock = threading.Lock()
_opening = threading.Lock()

SCHEMA = [
    """
    CREATE TABLE areas (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
    CREATE TABLE devices (
        id INTEGER PRIMARY KEY, mac TEXT UNIQUE NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL,
        area TEXT NOT NULL DEFAULT 'network' REFERENCES areas(name),
        online INTEGER NOT NULL DEFAULT 0, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
    CREATE TABLE device_days (
        day TEXT NOT NULL, device_id INTEGER NOT NULL REFERENCES devices(id), lookups INTEGER NOT NULL,
        PRIMARY KEY (day, device_id));
    CREATE TABLE lookups (
        day TEXT NOT NULL, device_id INTEGER NOT NULL REFERENCES devices(id), name TEXT NOT NULL, count INTEGER NOT NULL,
        PRIMARY KEY (day, device_id, name));
    CREATE TABLE findings (
        day TEXT NOT NULL, device_id INTEGER NOT NULL REFERENCES devices(id), kind TEXT NOT NULL, text TEXT NOT NULL,
        PRIMARY KEY (day, device_id, kind, text));
    CREATE TABLE changes (
        at TEXT NOT NULL, device_id INTEGER REFERENCES devices(id), action TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
        undo INTEGER NOT NULL DEFAULT 0, by TEXT NOT NULL DEFAULT 'owner',
        PRIMARY KEY (at, device_id, action, name, undo));
    CREATE TABLE readings (
        id INTEGER PRIMARY KEY, at TEXT NOT NULL, device_id INTEGER REFERENCES devices(id),
        area TEXT NOT NULL REFERENCES areas(name), measure TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL);
    CREATE INDEX readings_by_time ON readings (area, measure, at);
    CREATE TABLE automations (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, area TEXT NOT NULL REFERENCES areas(name),
        when_text TEXT NOT NULL, do_text TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
        asked_by TEXT NOT NULL, asked_on TEXT NOT NULL, approved_on TEXT);
    """,
    """
    DROP TABLE findings;
    CREATE TABLE findings (
        day TEXT NOT NULL, device_id INTEGER NOT NULL REFERENCES devices(id), kind TEXT NOT NULL, about TEXT NOT NULL DEFAULT '',
        text TEXT NOT NULL, PRIMARY KEY (day, device_id, kind, about));
    DROP TABLE changes;
    CREATE TABLE changes (
        at TEXT NOT NULL, mac TEXT NOT NULL DEFAULT '', device_id INTEGER REFERENCES devices(id), action TEXT NOT NULL,
        name TEXT NOT NULL DEFAULT '', undo INTEGER NOT NULL DEFAULT 0, by TEXT NOT NULL DEFAULT 'owner',
        PRIMARY KEY (at, mac, action, name, undo));
    """,
]

# What each table is for, in the words a brain is given. The order here is the order they are shown in.
ABOUT = {
    "areas": "The parts of a home Nearby can hold data for. Only network has rows today.",
    "devices": "Every device Nearby has seen, by name and kind, the area it belongs to, and the first and last day it was seen.",
    "device_days": "One row per device per day: how many names it asked the house phone book for in the day up to the last look.",
    "lookups": "Per device per day, the names it asked for most, with a count each.",
    "findings": "What the detectors noticed, per device per day: a new name, a steady beat, an odd hour.",
    "changes": "Every fix switched on or taken back, by day, and who asked for it.",
    "readings": "Measurements from sensors: power, air, water, soil. Empty until a sensor is connected.",
    "automations": "Rules for the house: when something happens, do something. Empty until the first one is approved.",
}
# What `rows` hands out. Never devices.mac, and days only, never clock times.
VIEWS = {
    "areas": "SELECT name FROM areas ORDER BY id",
    "devices": "SELECT label AS device, kind, area, online, substr(first_seen,1,10) AS first_seen, substr(last_seen,1,10) AS last_seen FROM devices ORDER BY label",
    "device_days": "SELECT t.day, d.label AS device, t.lookups FROM device_days t JOIN devices d ON d.id = t.device_id ORDER BY t.day DESC, t.lookups DESC",
    "lookups": "SELECT t.day, d.label AS device, t.name, t.count FROM lookups t JOIN devices d ON d.id = t.device_id ORDER BY t.day DESC, t.count DESC",
    "findings": "SELECT t.day, d.label AS device, t.kind, t.text FROM findings t JOIN devices d ON d.id = t.device_id ORDER BY t.day DESC",
    "changes": "SELECT substr(t.at,1,10) AS day, COALESCE(d.label, 'a device no longer seen') AS device, t.action, t.name, t.undo, t.by FROM changes t LEFT JOIN devices d ON d.id = t.device_id ORDER BY t.at DESC",
    "readings": "SELECT substr(t.at,1,10) AS day, COALESCE(d.label, '') AS device, t.area, t.measure, t.value, t.unit FROM readings t LEFT JOIN devices d ON d.id = t.device_id ORDER BY t.at DESC",
    "automations": "SELECT name, area, when_text, do_text, enabled, asked_by, asked_on, approved_on FROM automations ORDER BY id",
}
MAX_ROWS = 50


def connect() -> sqlite3.Connection:
    """Open the database, making or upgrading it first. Each step in SCHEMA runs once, in order."""
    find.DATA_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    with _opening:  # two openers must not both build the tables
        have = db.execute("PRAGMA user_version").fetchone()[0]
        for step in range(have, len(SCHEMA)):
            # the step and its number land together or not at all, so a crash half way can't leave tables without a number
            db.executescript(f"BEGIN IMMEDIATE;\n{SCHEMA[step]}\nPRAGMA user_version = {step + 1};\nCOMMIT;")
        db.executemany("INSERT OR IGNORE INTO areas (name) VALUES (?)", [(a,) for a in AREAS])
        db.commit()
    return db


def sync() -> dict:
    """Write what Nearby knows right now into the tables. Safe to run as often as you like: nothing is counted twice."""
    now = datetime.now().astimezone()
    stamp = now.isoformat(timespec="seconds")
    devices = find.load().get("devices", {})
    odd = detectors.latest()
    day = str(odd.get("at") or "")[:10]  # the day the counts are from, not the day they happen to be written
    if not day:
        odd = {}  # no look has been taken yet: nothing to file under a day
    with _lock:
        db = connect()
        try:
            for mac, d in devices.items():
                db.execute(
                    """INSERT INTO devices (mac, label, kind, online, first_seen, last_seen) VALUES (?,?,?,?,?,?)
                       ON CONFLICT(mac) DO UPDATE SET label = excluded.label, kind = excluded.kind, online = excluded.online,
                       first_seen = min(devices.first_seen, excluded.first_seen), last_seen = excluded.last_seen""",
                    (mac, d.get("label") or "something", d.get("kind") or "unknown", 1 if d.get("online") else 0,
                     _day(d.get("first_seen"), stamp), _day(d.get("last_seen"), stamp)))
            ids = {r["mac"]: r["id"] for r in db.execute("SELECT id, mac FROM devices")}
            for mac, n in (odd.get("lookups") or {}).items():
                if mac in ids:
                    db.execute("INSERT INTO device_days (day, device_id, lookups) VALUES (?,?,?) ON CONFLICT(day, device_id) DO UPDATE SET lookups = excluded.lookups", (day, ids[mac], int(n)))
            for mac, names in (odd.get("names") or {}).items():
                if mac in ids:
                    db.executemany("INSERT INTO lookups (day, device_id, name, count) VALUES (?,?,?,?) ON CONFLICT(day, device_id, name) DO UPDATE SET count = excluded.count",
                                   [(day, ids[mac], str(name), int(count)) for name, count in names])
            for f in odd.get("findings") or []:
                if f.get("key") in ids:
                    # one finding per device, kind and subject a day; its words carry a running count, so they are replaced, not added
                    about = str((f.get("names") or [""])[0]) if f.get("type") == "steady_beat" else ""
                    db.execute("INSERT INTO findings (day, device_id, kind, about, text) VALUES (?,?,?,?,?) ON CONFLICT(day, device_id, kind, about) DO UPDATE SET text = excluded.text",
                               (day, ids[f["key"]], str(f.get("type", "")), about, str(f.get("text", ""))))
            for e in fixes.load().get("log") or []:
                db.execute("INSERT INTO changes (at, mac, device_id, action, name, undo, by) VALUES (?,?,?,?,?,?,?) ON CONFLICT(at, mac, action, name, undo) DO UPDATE SET device_id = excluded.device_id",
                           (e.get("at", ""), e.get("mac") or "", ids.get(e.get("mac")), e.get("action", ""), e.get("name") or "", 1 if e.get("undo") else 0, e.get("by") or "owner"))
            db.commit()
            return counts(db)
        finally:
            db.close()


def _day(value, fallback: str) -> str:
    """A stamp from devices.json as given, or the fallback when it is missing or not a string."""
    return value if isinstance(value, str) and len(value) >= 10 else fallback


def counts(db: sqlite3.Connection | None = None) -> dict:
    own = db is None
    db = db or connect()
    try:
        return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ABOUT}
    finally:
        if own:
            db.close()


def describe() -> str:
    """The tables in plain words, for a brain: what each holds, its columns, how many rows."""
    db = connect()
    try:
        out = ["The home's tables. Ask for rows from one with the `rows` tool."]
        for t, about in ABOUT.items():
            cols = [c[0] for c in db.execute(VIEWS[t] + " LIMIT 0").description]
            n = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            out.append(f"- {t} ({n} row{'s' if n != 1 else ''}): {about}\n  columns: {', '.join(cols)}")
        return "\n".join(out)
    finally:
        db.close()


def rows(table: str, device: str | None = None, limit: int = 20) -> str:
    """Rows from one table as plain lines. Only the tables and columns in VIEWS; there is no free-form query."""
    if table not in VIEWS:
        raise ValueError(f"There is no table called {table}. The tables are: {', '.join(VIEWS)}.")
    limit = max(1, min(int(limit or 20), MAX_ROWS))
    db = connect()
    try:
        sql, args = VIEWS[table], []
        if device:
            cols = [c[0] for c in db.execute(sql + " LIMIT 0").description]
            if "device" not in cols:
                raise ValueError(f"The {table} table is not kept per device.")
            sql, args = f"SELECT * FROM ({sql}) WHERE device = ?", [device]
        got = db.execute(sql + " LIMIT ?", args + [limit]).fetchall()
        if not got:
            return f"No rows in {table}" + (f" for {device}." if device else ".")
        cols = got[0].keys()
        return f"{table}, {len(got)} row{'s' if len(got) != 1 else ''} ({', '.join(cols)}):\n" + "\n".join("- " + " | ".join(str(r[c]) for c in cols) for r in got)
    finally:
        db.close()
