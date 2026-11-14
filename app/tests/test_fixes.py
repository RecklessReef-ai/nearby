"""The taps, against a pretend phone book. Run: cd app && python3 -m unittest discover tests"""
import json
import os
import tempfile
import unittest

os.environ.setdefault("NEARBY_DATA", tempfile.mkdtemp())
from nearby import find, fixes  # noqa: E402

TV, PLUG, ROUTER = "aa:aa:aa:aa:aa:70", "aa:aa:aa:aa:aa:46", "aa:aa:aa:aa:aa:01"
DEVICES = {
    TV: {"ip": "192.168.0.70", "mac": TV, "kind": "samsung_tv", "label": "Living room TV"},
    PLUG: {"ip": "192.168.0.46", "mac": PLUG, "kind": "cloud_gadget", "label": "Sound machine"},
    ROUTER: {"ip": "192.168.0.1", "mac": ROUTER, "kind": "router", "label": "ASUS router"},
}
SAMSUNG = fixes.QUIET_LISTS["samsung_tv"][0]


class PhoneBook:
    """Stands in for AdGuard Home: remembers rules and which lists are on."""
    def __init__(self):
        self.rules, self.down = ["||my-own-rule.example^"], False
        self.filters = [{"url": SAMSUNG, "name": "Quiet the Samsung TV", "enabled": False}]

    def __call__(self, path, body=None):
        if self.down:
            raise OSError("connection refused")
        if path == "filtering/status":
            return {"user_rules": list(self.rules), "filters": [dict(f) for f in self.filters]}
        if path == "filtering/set_rules":
            self.rules = list(body["rules"])
        if path == "filtering/set_url":
            next(f for f in self.filters if f["url"] == body["url"])["enabled"] = body["data"]["enabled"]
        if path == "filtering/add_url":
            self.filters.append({"url": body["url"], "name": body["name"], "enabled": True})
        return {}


class Fixes(unittest.TestCase):
    def setUp(self):
        find.DATA_DIR.mkdir(parents=True, exist_ok=True)
        find.DEVICES_FILE.write_text(json.dumps({"devices": DEVICES}))
        fixes.FIXES.unlink(missing_ok=True)
        self.book = fixes._api = PhoneBook()

    def test_block_then_undo_leaves_the_phone_book_as_it_was(self):
        fixes.tap(PLUG, "block")
        self.assertEqual(self.book.rules, ["||my-own-rule.example^", fixes.BEGIN, "||*^$client=192.168.0.46", fixes.END])
        fixes.tap(PLUG, "block", undo=True)
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])
        self.assertEqual(fixes.load()["active"], {})
        self.assertEqual([(e["action"], e["undo"]) for e in fixes.load()["log"]], [("block", False), ("block", True)])

    def test_a_blocked_gadget_that_changes_address_stays_blocked(self):
        fixes.tap(PLUG, "block")
        moved = json.loads(json.dumps(DEVICES)); moved[PLUG]["ip"] = "192.168.0.99"
        find.DEVICES_FILE.write_text(json.dumps({"devices": moved}))
        fixes.sync()
        self.assertIn("||*^$client=192.168.0.99", self.book.rules)
        self.assertNotIn("||*^$client=192.168.0.46", self.book.rules)

    def test_quiet_turns_the_makers_list_on_and_undo_turns_it_off(self):
        fixes.tap(TV, "quiet")
        self.assertTrue(self.book.filters[0]["enabled"])
        fixes.tap(TV, "quiet", undo=True)
        self.assertFalse(self.book.filters[0]["enabled"])

    def test_undo_never_turns_off_a_list_the_owner_turned_on(self):
        self.book.filters[0]["enabled"] = True
        fixes.tap(TV, "quiet")
        fixes.tap(TV, "quiet", undo=True)
        self.assertTrue(self.book.filters[0]["enabled"])

    def test_the_router_and_this_computer_can_never_be_blocked(self):
        with self.assertRaises(fixes.Refused):
            fixes.tap(ROUTER, "block")
        self.assertEqual(fixes.block_rules({ROUTER: {"block": {}}}, DEVICES), [])
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])

    def test_quiet_is_only_offered_where_there_is_a_list(self):
        self.assertEqual(fixes.can(DEVICES[TV]), ["quiet", "block"])
        self.assertEqual(fixes.can(DEVICES[PLUG]), ["block"])
        with self.assertRaises(fixes.Refused):
            fixes.tap(PLUG, "quiet")

    def test_one_name_for_one_gadget_then_undo(self):
        fixes.detectors.ODD.write_text(json.dumps({"names": {TV: [["imrworldwide.com", 76], ["hulu.com", 131]]}}))
        fixes.tap(TV, "name", name="imrworldwide.com")
        self.assertEqual(self.book.rules, ["||my-own-rule.example^", fixes.BEGIN, "||imrworldwide.com^$client=192.168.0.70", fixes.END])
        fixes.tap(TV, "block")
        self.assertEqual(self.book.rules[2:4], ["||*^$client=192.168.0.70", "||imrworldwide.com^$client=192.168.0.70"])
        fixes.tap(TV, "block", undo=True)
        fixes.tap(TV, "name", undo=True, name="imrworldwide.com")
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])
        self.assertEqual(fixes.load()["active"], {})

    def test_only_a_name_the_gadget_really_asked_for_can_be_stopped(self):
        fixes.detectors.ODD.write_text(json.dumps({"names": {TV: [["hulu.com", 131]], ROUTER: [["asus.com", 3]]}}))
        for mac, name in ((TV, "bank.example.com"), (TV, "hulu.com^$important"), (TV, ""), (ROUTER, "asus.com"), (PLUG, "hulu.com")):
            with self.assertRaises(fixes.Refused, msg=(mac, name)):
                fixes.tap(mac, "name", name=name)
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])
        self.assertEqual(fixes.load()["active"], {})

    def test_a_name_fence_allows_what_the_gadget_uses_and_nothing_new(self):
        fixes.counters.BASELINE.write_text(json.dumps({PLUG: {"hatchbaby.com": "2026-11-14", "aws.com": "2026-11-14", "amazonaws.com": "2026-11-14"},
                                                        TV: {f"site{i}.com": "2026-11-14" for i in range(40)}}))
        self.assertEqual(fixes.fence_names(DEVICES[PLUG]), ["amazonaws.com", "aws.com", "hatchbaby.com"])
        fixes.tap(PLUG, "only")
        self.assertEqual(self.book.rules[2:-1], ["||*^$client=192.168.0.46", "@@||amazonaws.com^$client=192.168.0.46", "@@||aws.com^$client=192.168.0.46", "@@||hatchbaby.com^$client=192.168.0.46"])
        # the list is fixed at the tap: a name learned later does not slip in
        fixes.counters.BASELINE.write_text(json.dumps({PLUG: {"hatchbaby.com": "x", "aws.com": "x", "amazonaws.com": "x", "evil.example": "2026-11-15"}}))
        fixes.sync()
        self.assertNotIn("@@||evil.example^$client=192.168.0.46", self.book.rules)
        fixes.tap(PLUG, "only", undo=True)
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])

    def test_a_name_fence_is_refused_where_it_would_break_things(self):
        fixes.counters.BASELINE.write_text(json.dumps({TV: {f"site{i}.com": "x" for i in range(40)}, ROUTER: {"asus.com": "x"}}))
        for mac in (TV, ROUTER, PLUG):  # too many sites, the router, never heard
            with self.assertRaises(fixes.Refused, msg=mac):
                fixes.tap(mac, "only")
        self.assertEqual(fixes.fence_names({"mac": "p", "kind": "phone"}), [])
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])

    def test_a_gadget_that_left_takes_its_rule_with_it(self):
        fixes.tap(PLUG, "block")
        gone = json.loads(json.dumps(DEVICES)); gone[PLUG]["online"] = False
        gone["aa:aa:aa:aa:aa:99"] = {"ip": "192.168.0.46", "mac": "aa:aa:aa:aa:aa:99", "kind": "phone", "label": "iPhone", "online": True}  # a phone got its old address
        find.DEVICES_FILE.write_text(json.dumps({"devices": gone}))
        fixes.resync()
        self.assertEqual(self.book.rules, ["||my-own-rule.example^"])          # the phone is not blocked by mistake
        self.assertEqual(find.by_ip({"devices": gone})["192.168.0.46"]["label"], "iPhone")
        gone[PLUG]["online"] = True; gone[PLUG]["ip"] = "192.168.0.47"
        find.DEVICES_FILE.write_text(json.dumps({"devices": gone}))
        fixes.resync()
        self.assertIn("||*^$client=192.168.0.47", self.book.rules)             # it comes home, the block comes back

    def test_a_stopped_name_stays_stopped_inside_a_name_fence(self):
        fixes.counters.BASELINE.write_text(json.dumps({PLUG: {"hatchbaby.com": "x", "aws.com": "x"}}))
        fixes.detectors.ODD.write_text(json.dumps({"names": {PLUG: [["aws.com", 162]]}}))
        fixes.tap(PLUG, "only")
        fixes.tap(PLUG, "name", name="aws.com")
        self.assertNotIn("@@||aws.com^$client=192.168.0.46", self.book.rules)
        self.assertIn("@@||hatchbaby.com^$client=192.168.0.46", self.book.rules)
        self.assertIn("||aws.com^$client=192.168.0.46", self.book.rules)

    def test_only_a_plain_site_name_counts_as_one(self):
        for bad in ("evil.com\n", "x.'+alert`1`+'.com", "a b.com", "", "com", "-a.com", "a..com", "ex ample.com$important"):
            self.assertFalse(fixes.counters.is_site(bad), bad)
        for good in ("example.com", "a-b.co.uk", "1.example.org"):
            self.assertTrue(fixes.counters.is_site(good), good)

    def test_the_scrubber_knows_every_shape_of_address_and_time(self):
        for leak in ("fe80::1c2d:3e4f", "AA-BB-CC-DD-EE-FF", "at 03:14 it woke", "2026-11-14T03:14", "10.0.0.7"):
            self.assertTrue(fixes.counters.has_address(leak), leak)
        self.assertFalse(fixes.counters.has_address("Office TV: 774 lookups, 45 different names, asks for hulu.com about every 5 minutes"))

    def test_no_picture_of_the_house_means_hands_off_the_phone_book(self):
        fixes.tap(PLUG, "block")
        find.DEVICES_FILE.write_text("{")                                      # a half-written file
        fixes.resync()
        self.assertIn("||*^$client=192.168.0.46", self.book.rules)

    def test_a_sleeping_tv_is_still_the_tv(self):
        awake = {"kind": "samsung_tv", "label": "Samsung AU8000 43 TV", "facts": {"modelName": "UN43AU8000FXZA"}}
        asleep = find.remember(awake, {"kind": "unknown", "label": "Samsung device", "facts": {}, "ip": "192.168.0.70"})
        self.assertEqual((asleep["kind"], asleep["label"], asleep["facts"]["modelName"]), ("samsung_tv", "Samsung AU8000 43 TV", "UN43AU8000FXZA"))
        self.assertEqual(fixes.can(asleep), ["quiet", "block"])
        # a gadget never recognised stays unknown, and a fresh recognition always wins
        self.assertEqual(find.remember({}, {"kind": "unknown", "label": "something new"})["kind"], "unknown")
        self.assertEqual(find.remember(awake, {"kind": "google_tv", "label": "Office TV"})["kind"], "google_tv")

    def test_if_the_phone_book_is_down_nothing_is_recorded(self):
        self.book.down = True
        with self.assertRaises(fixes.Refused):
            fixes.tap(PLUG, "block")
        self.assertEqual(fixes.load()["active"], {})


if __name__ == "__main__":
    unittest.main()
