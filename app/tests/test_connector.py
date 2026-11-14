"""The MCP door's rules. Needs the app's own packages, so run it in the app image:
docker run --rm -e NEARBY_DATA=/tmp/t -v "$PWD/app:/app" -w /app nearby-app python -m unittest tests.test_connector"""
import json
import os
import tempfile
import unittest

os.environ.setdefault("NEARBY_DATA", tempfile.mkdtemp())
try:
    from nearby import connector, counters, find, fixes
except ModuleNotFoundError as e:
    raise unittest.SkipTest(f"needs the app image: {e}")

TV, PLUG, ROUTER, P1, P2 = "aa:aa:aa:aa:aa:70", "aa:aa:aa:aa:aa:46", "aa:aa:aa:aa:aa:01", "aa:aa:aa:aa:aa:11", "aa:aa:aa:aa:aa:12"
DEVICES = {
    TV: {"ip": "192.168.0.70", "mac": TV, "kind": "samsung_tv", "label": "Living room TV", "online": True},
    PLUG: {"ip": "192.168.0.46", "mac": PLUG, "kind": "cloud_gadget", "label": "Sound machine", "online": True},
    ROUTER: {"ip": "192.168.0.1", "mac": ROUTER, "kind": "router", "label": "ASUS router", "online": True},
    P1: {"ip": "192.168.0.11", "mac": P1, "kind": "phone", "label": "iPhone", "online": True},
    P2: {"ip": "192.168.0.12", "mac": P2, "kind": "phone", "label": "iPhone", "online": True},
}


def rpc(method, params=None, mid=1):
    return connector.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def tool(name, **args):
    r = rpc("tools/call", {"name": name, "arguments": args})["result"]
    return r["content"][0]["text"], r["isError"]


class Door(unittest.TestCase):
    def setUp(self):
        find.DATA_DIR.mkdir(parents=True, exist_ok=True)
        find.DEVICES_FILE.write_text(json.dumps({"devices": DEVICES, "last_scan": "x"}))
        fixes.FIXES.unlink(missing_ok=True)
        counters.fetch_log = lambda *a, **k: []
        self.rules = []
        fixes._api = lambda path, body=None: (self.rules.__setitem__(slice(None), body["rules"]) if path == "filtering/set_rules" else None) or {"user_rules": list(self.rules), "filters": []}
        connector._strikes.clear()

    def test_the_door_is_shut_without_a_long_password(self):
        os.environ["NEARBY_MCP_TOKEN"] = ""
        self.assertFalse(connector.allowed("Bearer "))
        os.environ["NEARBY_MCP_TOKEN"] = "short"
        self.assertFalse(connector.allowed("Bearer short"))
        os.environ["NEARBY_MCP_TOKEN"] = "x" * 32
        self.assertTrue(connector.allowed("Bearer " + "x" * 32))
        self.assertFalse(connector.allowed("Bearer " + "x" * 31 + "y"))
        self.assertFalse(connector.allowed("x" * 32))

    def test_ten_wrong_tries_lock_that_address_out(self):
        for _ in range(9):
            connector.strike("192.0.2.9")
        self.assertFalse(connector.locked("192.0.2.9"))
        connector.strike("192.0.2.9")
        self.assertTrue(connector.locked("192.0.2.9"))
        self.assertFalse(connector.locked("192.0.2.10"))

    def test_handshake_and_tool_list(self):
        r = rpc("initialize", {"protocolVersion": "2025-03-26"})["result"]
        self.assertEqual((r["protocolVersion"], r["serverInfo"]["name"]), ("2025-03-26", "nearby"))
        self.assertEqual(rpc("initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"], connector.PROTOCOLS[0])
        self.assertIsNone(connector.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual([t["name"] for t in rpc("tools/list")["result"]["tools"]], ["house", "fixes", "fix", "letter"])
        self.assertEqual(rpc("resources/list")["error"]["code"], -32601)

    def test_what_comes_through_has_names_and_no_addresses(self):
        text, err = tool("house")
        self.assertFalse(err)
        self.assertIn("- Living room TV (samsung tv): can be quieted or blocked", text)
        self.assertFalse(counters.has_address(text))
        for d in DEVICES.values():
            self.assertNotIn(d["ip"], text)
            self.assertNotIn(d["mac"], text)

    def test_a_fix_by_name_then_its_undo(self):
        text, err = tool("fix", device="Sound machine", action="block")
        self.assertEqual((err, self.rules[1]), (False, "||*^$client=192.168.0.46"))
        on, _ = tool("fixes")
        self.assertIn("- Sound machine: blocked since", on)
        self.assertFalse(counters.has_address(on))
        text, err = tool("fix", device="Sound machine", action="block", undo=True)
        self.assertEqual((err, self.rules), (False, []))

    def test_the_guard_rails_hold_through_the_door(self):
        for args in (dict(device="ASUS router", action="block"), dict(device="iPhone", action="block"), dict(device="The fridge", action="block"),
                     dict(device="Sound machine", action="quiet"), dict(device="Sound machine", action="reboot")):
            text, err = tool("fix", **args)
            self.assertTrue(err, args)
        self.assertEqual(self.rules, [])
        self.assertEqual(fixes.load()["active"], {})


if __name__ == "__main__":
    unittest.main()
