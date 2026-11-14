"""The detectors, on a replayed log. Run: cd app && python3 -m unittest discover tests"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

os.environ["NEARBY_DATA"] = tempfile.mkdtemp()
from nearby import counters, detectors  # noqa: E402

TZ = timezone(timedelta(hours=-6))
NOW = datetime(2026, 11, 14, 18, 0, tzinfo=TZ)
TV, PLUG, PHONE = "192.168.0.70", "192.168.0.46", "192.168.0.14"
BY_IP = {
    TV: {"ip": TV, "mac": "aa:aa:aa:aa:aa:70", "kind": "samsung_tv", "label": "Living room TV"},
    PLUG: {"ip": PLUG, "mac": "aa:aa:aa:aa:aa:46", "kind": "cloud_gadget", "label": "Sound machine"},
    PHONE: {"ip": PHONE, "mac": "aa:aa:aa:aa:aa:14", "kind": "phone_or_laptop", "label": "a phone or laptop"},
}


def entry(ip, name, t):
    return {"client": ip, "question": {"name": name}, "time": t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")}


def ordinary_day():
    """A normal day: the TV and the phone ask for things at uneven moments, the plug checks its clock on the hour."""
    log, uneven = [], [0, 7, 19, 26, 61, 64, 113, 200, 207, 311, 342, 480, 495, 610, 700]
    for m in uneven:
        log.append(entry(TV, "api.netflix.com", NOW - timedelta(minutes=m)))
        log.append(entry(PHONE, f"site{m}.example.com", NOW - timedelta(minutes=m + 3)))
    for h in range(16):
        log.append(entry(PLUG, "time.hatch.co", NOW - timedelta(hours=h)))
        log.append(entry(PLUG, "api.hatch.co", NOW - timedelta(hours=h, minutes=h * 3 % 17)))
    return log


KNOWN = {"aa:aa:aa:aa:aa:70": {"netflix.com", "samsungacr.com"}, "aa:aa:aa:aa:aa:46": {"hatch.co"}, "aa:aa:aa:aa:aa:14": {"example.com"}}


class Detectors(unittest.TestCase):
    def test_an_ordinary_day_trips_nothing(self):
        findings, _ = detectors.detect(ordinary_day(), BY_IP, KNOWN, {}, NOW)
        self.assertEqual(findings, [])

    def test_one_planted_beacon_trips_exactly_one_detector(self):
        log = ordinary_day() + [entry(TV, "log-ingestion.samsungacr.com", NOW - timedelta(seconds=60 * i + (i % 3))) for i in range(40)]
        findings, _ = detectors.detect(log, BY_IP, KNOWN, {}, NOW)
        self.assertEqual([(f["label"], f["type"]) for f in findings], [("Living room TV", "steady_beat")])
        self.assertIn("samsungacr.com", findings[0]["text"])
        self.assertIn("every 60 seconds", findings[0]["text"])

    def test_a_name_asked_twice_at_once_is_one_beat(self):
        times = [NOW - timedelta(seconds=300 * i) for i in range(12)]
        doubled = times + [t + timedelta(milliseconds=40) for t in times]
        self.assertAlmostEqual(detectors.beat(doubled), 300, delta=1)

    def test_uneven_lookups_are_not_a_beat(self):
        times = [NOW - timedelta(seconds=s) for s in (0, 40, 300, 310, 900, 1500, 1520, 4000, 4100, 9000, 9500)]
        self.assertIsNone(detectors.beat(times))

    def test_a_new_name_from_a_gadget_is_flagged_but_not_from_a_phone(self):
        log = ordinary_day() + [entry(PLUG, "cdn.unheard-of.cn", NOW - timedelta(minutes=5)), entry(PHONE, "brand-new.example.org", NOW - timedelta(minutes=5))]
        findings, _ = detectors.detect(log, BY_IP, KNOWN, {}, NOW)
        self.assertEqual([(f["label"], f["type"], f["names"]) for f in findings], [("Sound machine", "new_names", ["unheard-of.cn"])])

    def test_first_day_being_heard_has_nothing_to_call_new(self):
        findings, _ = detectors.detect(ordinary_day(), BY_IP, {}, {}, NOW)
        self.assertEqual(findings, [])

    def test_a_busy_night_is_flagged_against_the_usual_night(self):
        night = [entry(PLUG, f"a{i % 9}.hatch.co", NOW.replace(hour=2, minute=0) + timedelta(seconds=(i * 7919) % 10000)) for i in range(120)]  # a burst, at uneven moments
        usual = {"aa:aa:aa:aa:aa:46": {"2026-11-12": 4, "2026-11-13": 6}}
        findings, tonight = detectors.detect(ordinary_day() + night, BY_IP, KNOWN, usual, NOW)
        self.assertEqual([(f["label"], f["type"]) for f in findings], [("Sound machine", "odd_hours")])
        self.assertGreaterEqual(tonight["aa:aa:aa:aa:aa:46"], 120)
        # the same night with no earlier nights to compare against says nothing
        self.assertEqual(detectors.detect(ordinary_day() + night, BY_IP, KNOWN, {}, NOW)[0], [])

    def test_what_the_brain_is_shown_has_no_address_and_no_time(self):
        log = ordinary_day() + [entry(TV, "log-ingestion.samsungacr.com", NOW - timedelta(seconds=60 * i)) for i in range(40)]
        findings, _ = detectors.detect(log, BY_IP, KNOWN, {}, NOW)
        summary = {"day": "2026-11-14", "devices_online": 3, "joined_today": [], "watched": [], "note": "", "odd": findings}
        text = counters.as_text(summary)  # raises if an address or a timestamp slipped in
        self.assertIn("Living room TV: asks for samsungacr.com on a steady beat", text)

    def test_names_learned_today_stay_new_all_day(self):
        self.assertEqual(counters.known_before({"dev": ["old.com"]}, "2026-11-13")["dev"], set())
        self.assertEqual(counters.known_before({"dev": ["old.com", "fresh.com"]}, "2026-11-14")["dev"], {"old.com"})
        self.assertEqual(counters.known_before({"dev": ["fresh.com"]}, "2026-11-14")["dev"], {"old.com"})
        self.assertEqual(counters.known_before({"dev": []}, "2026-11-15")["dev"], {"old.com", "fresh.com"})


if __name__ == "__main__":
    unittest.main()
