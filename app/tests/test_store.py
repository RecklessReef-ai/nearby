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
