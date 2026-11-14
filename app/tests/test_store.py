"""The home's tables: what goes in, what a brain may read out."""
import json
import os
import tempfile
import unittest

os.environ.setdefault("NEARBY_DATA", tempfile.mkdtemp())
try:
    from nearby import connector, detectors, find, fixes, store
except ModuleNotFoundError as e:
    raise unittest.SkipTest(f"needs the app image: {e}")

TV, PLUG = "aa:aa:aa:aa:aa:70", "aa:aa:aa:aa:aa:46"
DEVICES = {
    TV: {"ip": "192.168.0.70", "mac": TV, "kind": "samsung_tv", "label": "Living room TV", "online": True},
    PLUG: {"ip": "192.168.0.46", "mac": PLUG, "kind": "cloud_gadget", "label": "Sound machine", "online": False},
}
ODD = {"at": "2026-11-14T09:00:00-06:00", "heard": 2, "learning": [], "lookups": {TV: 774, PLUG: 12},
       "names": {TV: [["hulu.com", 191], ["imrworldwide.com", 76]], PLUG: [["hatchbaby.com", 12]]},
       "findings": [{"key": TV, "label": "Living room TV", "type": "new_names", "text": "asked for 3 names it never asked for before.", "names": []}]}
LOG = {"active": {}, "lists": [], "log": [{"at": "2026-11-14T09:58:50-06:00", "mac": TV, "label": "Living room TV", "action": "name", "undo": False, "name": "imrworldwide.com"}]}


class Tables(unittest.TestCase):
    def setUp(self):
        find.DATA_DIR.mkdir(parents=True, exist_ok=True)
        store.DB.unlink(missing_ok=True)
        find.DEVICES_FILE.write_text(json.dumps({"devices": DEVICES, "last_scan": "x"}))
        detectors.ODD.write_text(json.dumps(ODD))
        fixes.FIXES.write_text(json.dumps(LOG))

    def test_a_look_at_the_house_becomes_rows(self):
        n = store.sync()
        self.assertEqual((n["areas"], n["devices"], n["device_days"], n["lookups"], n["findings"], n["changes"]), (5, 2, 2, 3, 1, 1))
        self.assertEqual((n["readings"], n["automations"]), (0, 0))

    def test_running_it_again_counts_nothing_twice(self):
        store.sync()
        again = dict(ODD, lookups={TV: 800, PLUG: 12})
        detectors.ODD.write_text(json.dumps(again))
        n = store.sync()
        self.assertEqual((n["devices"], n["device_days"], n["lookups"], n["findings"], n["changes"]), (2, 2, 3, 1, 1))
        self.assertIn("| 800", store.rows("device_days", "Living room TV"))

    def test_a_brain_reads_names_and_days_and_never_an_address_or_a_time(self):
        store.sync()
        for t in store.VIEWS:
            text = store.rows(t, limit=50) + store.describe()
            for leak in (TV, PLUG, "192.168.0.70", "192.168.0.46", "09:58", "T09"):
                self.assertNotIn(leak, text, t)
        self.assertNotIn("mac", store.describe())
        self.assertIn("Living room TV | name | imrworldwide.com", store.rows("changes"))

    def test_only_the_listed_tables_can_be_read_and_no_query_gets_through(self):
        store.sync()
        for bad in ("sqlite_master", "devices; DROP TABLE devices", "devices WHERE 1=1", ""):
            with self.assertRaises(ValueError):
                store.rows(bad)
        self.assertIn("No rows", store.rows("lookups", "x' OR '1'='1"))
        self.assertEqual(store.counts()["devices"], 2)
        self.assertEqual(len(store.rows("lookups", limit=10 ** 9).splitlines()) - 1, 3)

    def test_the_door_has_the_tables(self):
        store.sync()
        text, err = connector.call("tables", {})
        self.assertFalse(err)
        self.assertIn("automations (0 rows)", text)
        text, err = connector.call("rows", {"table": "lookups", "device": "Living room TV", "limit": 1})
        self.assertFalse(err)
        self.assertIn("hulu.com | 191", text)
        self.assertNotIn("imrworldwide", text)
        text, err = connector.call("rows", {"table": "sqlite_master"})
        self.assertTrue(err)

    def test_the_tables_are_ready_for_the_rest_of_the_home(self):
        db = store.connect()
        db.execute("INSERT INTO readings (at, area, measure, value, unit) VALUES ('2026-11-14T10:00:00', 'power', 'house draw', 1.2, 'kW')")
        db.execute("INSERT INTO automations (name, area, when_text, do_text, asked_by, asked_on) VALUES ('Lights out', 'power', 'nobody is home', 'turn the lights off', 'an assistant', '2026-11-14')")
        with self.assertRaises(Exception):
            db.execute("INSERT INTO readings (at, area, measure, value, unit) VALUES ('x', 'garage', 'm', 1, 'u')")
        db.commit(); db.close()
        self.assertIn("power | house draw | 1.2 | kW", store.rows("readings"))
        self.assertIn("Lights out | power | nobody is home | turn the lights off | 0", store.rows("automations"))


class ReviewFixes(unittest.TestCase):
    setUp = Tables.setUp

    def test_a_finding_whose_count_keeps_rising_stays_one_row(self):
        for n in (100, 101, 102):
            odd = dict(ODD, findings=[{"key": TV, "label": "Living room TV", "type": "steady_beat", "text": f"asks for x.example on a steady beat, {n} times in the last day.", "names": ["x.example"]}])
            detectors.ODD.write_text(json.dumps(odd))
            got = store.sync()
        self.assertEqual(got["findings"], 1)
        self.assertIn("102 times", store.rows("findings"))

    def test_a_change_to_a_device_no_longer_known_is_not_repeated(self):
        log = dict(LOG, log=LOG["log"] + [{"at": "2026-11-13T08:00:00-06:00", "mac": "aa:aa:aa:aa:aa:99", "label": "gone", "action": "block", "undo": False}])
        fixes.FIXES.write_text(json.dumps(log))
        for _ in range(3):
            got = store.sync()
        self.assertEqual(got["changes"], 2)
        self.assertIn("a device no longer seen | block", store.rows("changes"))
        self.assertNotIn("aa:aa:aa:aa:aa:99", store.rows("changes"))

    def test_first_and_last_seen_come_from_the_house_not_from_the_moment_of_writing(self):
        devices = {TV: dict(DEVICES[TV], online=False, first_seen="2026-09-01T10:00:00", last_seen="2026-10-01T10:00:00")}
        find.DEVICES_FILE.write_text(json.dumps({"devices": devices, "last_scan": "x"}))
        store.sync()
        self.assertIn("Living room TV | samsung_tv | network | 0 | 2026-09-01 | 2026-10-01", store.rows("devices"))

    def test_counts_are_filed_under_the_day_they_are_from(self):
        detectors.ODD.write_text(json.dumps(dict(ODD, at="2026-11-13T23:50:00-06:00")))
        store.sync()
        self.assertIn("2026-11-13 | Living room TV | 774", store.rows("device_days"))
        detectors.ODD.unlink()
        store.DB.unlink()
        self.assertEqual(store.sync()["device_days"], 0)

    def test_many_first_openers_at_once_build_the_tables_once(self):
        import threading
        errors = []

        def go():
            try:
                store.rows("devices")
            except Exception as e:
                errors.append(repr(e))
        for _ in range(5):
            store.DB.unlink(missing_ok=True)
            threads = [threading.Thread(target=go) for _ in range(16)]
            [t.start() for t in threads]
            [t.join() for t in threads]
        self.assertEqual(errors, [])

    def test_an_upgrade_from_the_first_layout_keeps_working(self):
        import sqlite3
        db = sqlite3.connect(store.DB)
        db.executescript(store.SCHEMA[0] + "PRAGMA user_version = 1;")
        db.close()
        self.assertEqual(store.sync()["changes"], 1)

    def test_an_address_hidden_in_a_device_name_is_struck_out_at_the_door(self):
        from nearby import rules
        devices = {TV: dict(DEVICES[TV], label="shelly1-AABBCC000002"), PLUG: dict(DEVICES[PLUG], label="ip-192-168-0-7", online=True)}
        find.DEVICES_FILE.write_text(json.dumps({"devices": devices, "last_scan": "x"}))
        store.sync()
        from nearby import counters
        counters.fetch_log = lambda *a, **k: []
        for tool, args in (("rows", {"table": "devices"}), ("house", {}), ("fixes", {})):
            text, err = connector.call(tool, args)
            self.assertFalse(err, text)
            self.assertNotIn("AABBCC000002", text, tool)
            self.assertNotIn("192-168-0-7", text, tool)
        self.assertIn(rules.STRUCK, connector.call("rows", {"table": "devices"})[0])
