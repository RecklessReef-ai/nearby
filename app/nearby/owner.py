"""The owner's lock on Nearby's page.

Before this, anyone on the home Wi-Fi could open the page and press its buttons: a guest, or a gadget that had
been taken over. Now the page asks for a password. The first person to open a fresh box chooses it.

- The password is never stored. A salted scrypt hash of it is, in data/owner.json.
- A sign-in hands the browser a random token in a cookie the page's scripts cannot read. Only a hash of the
  token is kept on the box, so a copy of the data folder is not a way in.
- Ten wrong tries from one address lock that address out for ten minutes.
- The MCP door has its own password and is not opened by this one.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from . import find

OWNER = find.DATA_DIR / "owner.json"
COOKIE = "nearby_owner"
MIN_LENGTH = 10
SESSION_SECONDS = 30 * 24 * 3600
MAX_TRIES, LOCK_SECONDS = 10, 600
_lock = threading.Lock()
_strikes: dict[str, list[float]] = {}
_tries = threading.Lock()


class Refused(Exception):
    """A reason fit to show on the sign-in page."""


def _load() -> dict:
    try:
        d = json.loads(OWNER.read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    find.save(OWNER, d)
    try:
        os.chmod(OWNER, 0o600)
    except OSError:
        pass


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32).hex()


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_set() -> bool:
    return bool(_load().get("hash"))


def choose(password: str) -> None:
    """Set the password on a fresh box. Refused once one exists: changing it means signing in first."""
    with _lock:
        if _load().get("hash"):
            raise Refused("A password is already set on this box.")
        _store(password)


def change(password: str) -> None:
    """A new password, from someone already signed in. Every other sign-in is ended."""
    with _lock:
        _store(password)


def _store(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_LENGTH:
        raise Refused(f"Use {MIN_LENGTH} characters or more.")
    salt = secrets.token_bytes(16)
    _save({"salt": salt.hex(), "hash": _hash(password, salt), "sessions": {}})


def check(password: str) -> bool:
    d = _load()
    if not d.get("hash") or not isinstance(password, str):
        return False
    return hmac.compare_digest(_hash(password, bytes.fromhex(d["salt"])), d["hash"])


def locked(who: str) -> bool:
    now = time.time()
    _strikes[who] = [t for t in _strikes.get(who, []) if now - t < LOCK_SECONDS]
    return len(_strikes[who]) >= MAX_TRIES


def strike(who: str) -> None:
    _strikes.setdefault(who, []).append(time.time())


def attempt(who: str) -> bool:
    """Count one try for this address before the password is looked at. False when it has used them all."""
    with _tries:
        if locked(who):
            return False
        strike(who)
        return True


def forgive(who: str) -> None:
    """The password was right: that try does not count against the address."""
    with _tries:
        if _strikes.get(who):
            _strikes[who].pop()


def sign_in() -> str:
    """A new token for a browser that just gave the right password."""
    token = secrets.token_urlsafe(32)
    with _lock:
        d = _load()
        now = time.time()
        live = {k: v for k, v in (d.get("sessions") or {}).items() if v > now}
        live[_digest(token)] = now + SESSION_SECONDS
        d["sessions"] = live
        _save(d)
    return token


def signed_in(token: str | None) -> bool:
    if not token:
        return False
    return (_load().get("sessions") or {}).get(_digest(token), 0) > time.time()


def sign_out(token: str | None) -> None:
    if not token:
        return
    with _lock:
        d = _load()
        if (d.get("sessions") or {}).pop(_digest(token), None) is not None:
            _save(d)
