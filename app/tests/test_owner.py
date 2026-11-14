"""The owner's lock on the page, and the locks on every answer."""
import json
import os
import tempfile
import unittest

os.environ.setdefault("NEARBY_DATA", tempfile.mkdtemp())
try:
    from nearby import find, owner, web
except ModuleNotFoundError as e:
    raise unittest.SkipTest(f"needs the app image: {e}")


class Lock(unittest.TestCase):
    def setUp(self):
        find.DATA_DIR.mkdir(parents=True, exist_ok=True)
        owner.OWNER.unlink(missing_ok=True)
        owner._strikes.clear()

    def test_a_fresh_box_is_claimed_once(self):
        self.assertFalse(owner.is_set())
        with self.assertRaises(owner.Refused):
            owner.choose("short")
        owner.choose("a long enough password")
        self.assertTrue(owner.is_set())
        with self.assertRaises(owner.Refused):
            owner.choose("someone else's password")
        self.assertTrue(owner.check("a long enough password"))
        self.assertFalse(owner.check("someone else's password"))

    def test_the_password_and_the_token_are_never_stored(self):
        owner.choose("a long enough password")
        token = owner.sign_in()
        kept = owner.OWNER.read_text()
        self.assertNotIn("a long enough password", kept)
        self.assertNotIn(token, kept)
        self.assertEqual(oct(owner.OWNER.stat().st_mode & 0o777), "0o600")

    def test_a_sign_in_lasts_until_sign_out_and_a_made_up_token_never_works(self):
        owner.choose("a long enough password")
        token = owner.sign_in()
        self.assertTrue(owner.signed_in(token))
        self.assertFalse(owner.signed_in(token + "x"))
        self.assertFalse(owner.signed_in(None))
        self.assertFalse(owner.signed_in(""))
        owner.sign_out(token)
        self.assertFalse(owner.signed_in(token))

    def test_an_old_sign_in_stops_working(self):
        owner.choose("a long enough password")
        token = owner.sign_in()
        d = json.loads(owner.OWNER.read_text())
        d["sessions"] = {k: 1 for k in d["sessions"]}
        owner.OWNER.write_text(json.dumps(d))
        self.assertFalse(owner.signed_in(token))

    def test_changing_the_password_ends_every_sign_in(self):
        owner.choose("a long enough password")
        token = owner.sign_in()
        owner.change("another long password")
        self.assertFalse(owner.signed_in(token))
        self.assertTrue(owner.check("another long password"))

    def test_ten_wrong_tries_lock_that_address_out(self):
        for _ in range(9):
            owner.strike("192.0.2.9")
        self.assertFalse(owner.locked("192.0.2.9"))
        owner.strike("192.0.2.9")
        self.assertTrue(owner.locked("192.0.2.9"))
        self.assertFalse(owner.locked("192.0.2.10"))

    def test_only_sign_in_health_and_the_door_are_open_without_the_owner(self):
        for path in ("/health", "/mcp", "/login", "/api/login"):
            self.assertTrue(web.open_to_all(path), path)
        for path in ("/", "/brains", "/letter", "/api/fix", "/api/asks", "/api/devices", "/api/fixes", "/api/scan", "/api/letter", "/api/tables", "/api/odd", "/logout", "/login/x", "/mcp/x"):
            self.assertFalse(web.open_to_all(path), path)

    def test_every_route_is_either_open_on_purpose_or_locked(self):
        paths = {r.path for r in web.app.routes if hasattr(r, "methods")}
        self.assertTrue({"/", "/api/fix", "/api/asks", "/mcp", "/login"} <= paths)
        self.assertEqual({p for p in paths if web.open_to_all(p)} - {"/health", "/mcp", "/login", "/api/login"}, set())

    def test_a_try_is_counted_before_the_password_is_looked_at(self):
        from nearby import connector
        for lock in (owner, connector):
            lock._strikes.clear()
            self.assertEqual([lock.attempt("192.0.2.9") for _ in range(12)], [True] * 10 + [False] * 2)
            self.assertTrue(lock.attempt("192.0.2.10"))
            lock.forgive("192.0.2.10")
            self.assertEqual(lock._strikes["192.0.2.10"], [])

    def test_a_burst_of_guesses_gets_ten_tries_and_no_more(self):
        import threading
        owner._strikes.clear()
        got = []
        threads = [threading.Thread(target=lambda: got.append(owner.attempt("192.0.2.9"))) for _ in range(120)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(got.count(True), 10)

    def test_the_open_health_page_says_nothing_about_the_house(self):
        self.assertEqual(sorted(web.health()), ["ok", "version"])
