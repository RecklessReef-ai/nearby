"""The chat's rules, without calling the brain. Needs the app's own packages, so run it in the app image:
docker run --rm -e NEARBY_DATA=/tmp/t -v "$PWD/app:/app" -w /app nearby-app python -m unittest tests.test_chat"""
import json
import os
import tempfile
import unittest

os.environ.setdefault("NEARBY_DATA", tempfile.mkdtemp())
try:
    from nearby import brain, chat, counters, find, fixes
except ModuleNotFoundError as e:  # the laptop's own python has no nacl
    raise unittest.SkipTest(f"needs the app image: {e}")

TV, PLUG, P1, P2 = "aa:aa:aa:aa:aa:70", "aa:aa:aa:aa:aa:46", "aa:aa:aa:aa:aa:11", "aa:aa:aa:aa:aa:12"
DEVICES = {
    TV: {"ip": "192.168.0.70", "mac": TV, "kind": "samsung_tv", "label": "Living room TV", "online": True},
    PLUG: {"ip": "192.168.0.46", "mac": PLUG, "kind": "cloud_gadget", "label": "Sound machine", "online": True},
    P1: {"ip": "192.168.0.11", "mac": P1, "kind": "phone", "label": "iPhone", "online": True},
    P2: {"ip": "192.168.0.12", "mac": P2, "kind": "phone", "label": "iPhone", "online": True},
}


class Chat(unittest.TestCase):
    def setUp(self):
        find.DATA_DIR.mkdir(parents=True, exist_ok=True)
        find.DEVICES_FILE.write_text(json.dumps({"devices": DEVICES, "last_scan": "x"}))
        fixes.FIXES.unlink(missing_ok=True)
        counters.fetch_log = lambda *a, **k: []
        self.sent = []
        brain.morning_check = lambda *a, **k: {"ok": True, "signing_public_key": "00"}

        def fake_ask(text, proof, **kw):
            self.sent.append((text, kw.get("system")))
            return {"text": json.dumps({"reply": "The TV is the loud one.", "suggestions": [
                {"device": "Living room TV", "action": "quiet", "why": "It tracks the screen."},
                {"device": "Living room TV", "action": "reboot the router", "why": "off menu"},
                {"device": "The fridge", "action": "block", "why": "not a gadget on the list"},
                {"device": "iPhone", "action": "block", "why": "two share this name"}]}), "verified": "verified", "tokens": 321}
        brain.ask = fake_ask

    def test_the_brain_is_shown_counts_and_labels_and_no_address(self):
        out = chat.answer("Which gadget is the loudest?")
        text, system = self.sent[0]
        self.assertEqual(system, chat.SYSTEM)
        self.assertIn("- Living room TV (samsung tv): can be quieted or blocked", text)
        self.assertIn("The owner asks: Which gadget is the loudest?", text)
        self.assertFalse(counters.has_address(text))
        self.assertNotIn("192.168", text)
        self.assertEqual(out["source"], "sealed")

    def test_off_menu_and_unknown_gadgets_are_dropped_and_shared_names_get_no_tap(self):
        out = chat.answer("What should I do?")
        self.assertEqual([(s["device"], s["action"], s["can"]) for s in out["suggestions"]], [("Living room TV", "quiet", True), ("iPhone", "block", False)])
        self.assertEqual(out["suggestions"][0]["mac"], TV)
        self.assertIsNone(out["suggestions"][1]["mac"])

    def test_a_question_with_an_address_never_leaves_the_house(self):
        with self.assertRaises(chat.Refused):
            chat.answer("what is 192.168.0.70 doing")
        with self.assertRaises(chat.Refused):
            chat.answer("and now?", [{"who": "you", "text": "the one at aa:bb:cc:dd:ee:ff"}])
        self.assertEqual(self.sent, [])

    def test_earlier_turns_ride_along(self):
        chat.answer("Is that normal?", [{"who": "you", "text": "Which is loudest?"}, {"who": "nearby", "text": "The TV."}])
        self.assertIn("Earlier in this talk:\nOwner: Which is loudest?\nNearby: The TV.", self.sent[0][0])

    def test_not_sealed_means_a_local_answer_and_nothing_sent(self):
        brain.morning_check = lambda *a, **k: {"ok": False, "error": "no NEAR AI Cloud key in .env"}
        out = chat.answer("Is anything wrong?")
        self.assertEqual((out["source"], out["suggestions"], self.sent), ("local", [], []))
        self.assertIn("won't ask anywhere less private", out["reply"])

    def test_a_brain_that_fails_falls_back_to_local(self):
        def boom(*a, **k):
            raise RuntimeError("daily token cap reached (50000 of 50000)")
        brain.ask = boom
        out = chat.answer("Is anything wrong?")
        self.assertEqual(out["source"], "local")
        self.assertIn("daily token cap reached", out["reply"])


if __name__ == "__main__":
    unittest.main()
