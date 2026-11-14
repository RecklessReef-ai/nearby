"""The house's own key. Made on first run, never leaves this machine.

It is an Ed25519 key pair, which is what a NEAR account uses, so the house has
a NEAR address from day one (the implicit account: the public key in hex).
Nothing is written on-chain. The key signs every letter.
"""
from __future__ import annotations

import hashlib
import os

from nacl.signing import SigningKey, VerifyKey

from .find import DATA_DIR

KEY_FILE = DATA_DIR / "house.key"
_ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = bytearray()
    while n:
        n, r = divmod(n, 58)
        out.append(_ALPHABET[r])
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return (_ALPHABET[0:1] * pad + out[::-1]).decode()


def load_or_make() -> SigningKey:
    if KEY_FILE.exists():
        return SigningKey(bytes.fromhex(KEY_FILE.read_text().strip()))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sk = SigningKey.generate()
    fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(bytes(sk).hex())
    return sk


def account_id() -> str:
    """The NEAR implicit account id for this house: the public key as 64 hex chars."""
    return bytes(load_or_make().verify_key).hex()


def public_key_near() -> str:
    return "ed25519:" + _b58(bytes(load_or_make().verify_key))


def sign(data: bytes) -> str:
    return load_or_make().sign(data).signature.hex()


def verify(data: bytes, signature_hex: str, account: str | None = None) -> bool:
    try:
        VerifyKey(bytes.fromhex(account or account_id())).verify(data, bytes.fromhex(signature_hex))
        return True
    except Exception:
        return False


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
