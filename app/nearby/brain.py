"""The sealed brain. NEAR AI Cloud, Confidential TEE models only.

Order of operations, every time:
1. Is the model on the short list of models NEAR serves inside its own TEEs? If not, refuse.
2. Has today's attestation passed? If not, run it. If it fails, use local words.
3. Encrypt the counters to the attested model key (E2EE), send, decrypt the answer.
4. Fetch the response signature and check it against the attested signer.
5. Count tokens and dollars against the caps. Over a cap: local words until tomorrow.

The model only ever sees counters. It may only suggest from a fixed menu.
Plain code decides what, if anything, happens next.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from nacl.bindings import (
    crypto_aead_xchacha20poly1305_ietf_decrypt,
    crypto_aead_xchacha20poly1305_ietf_encrypt,
    crypto_sign_ed25519_pk_to_curve25519,
    crypto_sign_ed25519_sk_to_curve25519,
)
from nacl.signing import SigningKey, VerifyKey

from . import attest
from .find import DATA_DIR

BASE = "https://cloud-api.near.ai/v1"
# Models NEAR AI serves inside its own attested TEEs. Anything else is refused, even if it is cheaper or smarter.
SEALED_MODELS = {
    "Qwen/Qwen3.8-27B": "Qwen 3.8 27B",
    "deepseek-ai/DeepSeek-V4.1-Flash-1017": "DeepSeek V4.1 Flash",
    "Qwen/Qwen3.6-35B-A3B-FP8": "Qwen 3.6 35B",
}
MODEL = os.environ.get("NEAR_AI_MODEL", "Qwen/Qwen3.8-27B")
MENU = ("quiet", "fence", "block", "ask", "none")
CAP_TOKENS_DAY = int(os.environ.get("CAP_TOKENS_DAY", "50000"))
CAP_USD_MONTH = float(os.environ.get("CAP_USD_MONTH", "1.00"))
PROOFS = DATA_DIR / "proofs"
USAGE = DATA_DIR / "usage.json"

SYSTEM = """You write a short evening note for the person who lives in a house, about the gadgets in it.
You are given counters only: how many names each device asked for, which names, what was new.
Rules: plain words, no jargon, no technical terms without a one-clause explanation, never alarm, at most 120 words.
Say what is normal. Point out at most one thing worth a look. Never invent facts beyond the counters.
Then suggest actions ONLY from this menu: quiet (stop a device's ad or tracking names), fence (keep a device away from the others),
block (stop one device entirely), ask (you want the owner's view), none.
Reply as JSON only: {"letter": "...", "suggestions": [{"device": "<label exactly as given>", "action": "<menu word>", "why": "<one plain sentence>"}]}"""


def key() -> str:
    return os.environ.get("NEAR_AI_API_KEY", "").strip()


def _headers(extra: dict | None = None) -> dict:
    h = {"Authorization": f"Bearer {key()}", "Content-Type": "application/json", "Accept": "application/json",
         "Accept-Encoding": "identity", "x-no-aliasing": "true"}
    h.update(extra or {})
    return h


# ---------- the morning check ----------

def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _proof_file(date: str, model: str):
    """One proof a day per model. The letter's model keeps the plain name; any other model gets its own file beside it."""
    return PROOFS / (f"{date}.json" if model == MODEL else f"{date}.{re.sub(r'[^A-Za-z0-9]+', '-', model)}.json")


def proof_today(model: str = MODEL) -> dict | None:
    try:
        p = json.loads(_proof_file(today(), model).read_text())
        return p if p.get("model") == model else None
    except (OSError, ValueError):
        return None


def morning_check(model: str = MODEL, force: bool = False) -> dict:
    """Fetch a fresh attestation with our nonce and check every candidate. Cached per day."""
    if not force and (p := proof_today(model)):
        return p
    proof = {"date": today(), "model": model, "ok": False, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "candidates": []}
    if model not in SEALED_MODELS:
        proof["error"] = f"{model} is not on the sealed list"
        return _save_proof(proof)
    if not key():
        proof["error"] = "no NEAR AI Cloud key in .env"
        return _save_proof(proof)
    nonce = secrets.token_hex(32)
    q = urlencode({"model": model, "provider": "near", "signing_algo": "ed25519", "include_tls_fingerprint": "false", "nonce": nonce})
    try:
        with urlopen(Request(f"{BASE}/attestation/report?{q}", headers=_headers()), timeout=60) as r:
            report = json.loads(r.read())
    except HTTPError as e:
        proof["error"] = f"attestation request failed: {e.code} {e.read()[:200].decode(errors='replace')}"
        return _save_proof(proof)
    except Exception as e:
        proof["error"] = f"attestation request failed: {e}"
        return _save_proof(proof)
    candidates = report.get("model_attestations") or []
    if not candidates:
        proof["error"] = "no model attestation returned: this model is not served from a NEAR TEE right now"
        return _save_proof(proof)
    good = []
    for c in candidates:
        try:
            checks = attest.check_report(c, nonce)
            good.append({"signing_public_key": c.get("signing_public_key"), "signing_address": c.get("signing_address"), "checks": checks})
        except Exception as e:
            proof["candidates"].append({"signing_address": c.get("signing_address"), "failed": str(e)})
    proof["candidates"] += [{"signing_address": g["signing_address"], "passed": g["checks"]} for g in good]
    if good:
        proof.update(ok=True, nonce=nonce, signing_public_key=good[0]["signing_public_key"], signing_address=good[0]["signing_address"],
                     signers=[g["signing_address"] for g in good], checks=good[0]["checks"])
    else:
        proof["error"] = "every attestation candidate failed a check"
    return _save_proof(proof)


def _save_proof(proof: dict) -> dict:
    PROOFS.mkdir(parents=True, exist_ok=True)
    _proof_file(proof["date"], proof["model"]).write_text(json.dumps(proof, indent=2))
    return proof


# ---------- caps ----------

def _usage() -> dict:
    try:
        return json.loads(USAGE.read_text())
    except (OSError, ValueError):
        return {}


def within_caps() -> tuple[bool, str]:
    u = _usage()
    day_tokens = u.get(today(), {}).get("tokens", 0)
    month_usd = sum(v.get("usd", 0) for k, v in u.items() if k[:7] == today()[:7])
    if day_tokens >= CAP_TOKENS_DAY:
        return False, f"daily token cap reached ({day_tokens} of {CAP_TOKENS_DAY})"
    if month_usd >= CAP_USD_MONTH:
        return False, f"monthly dollar cap reached (${month_usd:.2f} of ${CAP_USD_MONTH:.2f})"
    return True, ""


def _record(tokens_in: int, tokens_out: int, model: str) -> None:
    price = _pricing(model)
    usd = tokens_in * price.get("input", 0) / 1e6 + tokens_out * price.get("output", 0) / 1e6
    u = _usage()
    d = u.setdefault(today(), {"tokens": 0, "usd": 0.0, "calls": 0})
    d["tokens"] += tokens_in + tokens_out
    d["usd"] = round(d["usd"] + usd, 6)
    d["calls"] += 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USAGE.write_text(json.dumps(u, indent=2))


_PRICES: dict = {}


def _pricing(model: str) -> dict:
    if not _PRICES:
        try:
            with urlopen(f"{BASE}/models", timeout=15) as r:
                for m in json.loads(r.read()).get("data", []):
                    _PRICES[m["id"]] = m.get("pricing") or {}
        except Exception:
            pass
    return _PRICES.get(model, {"input": 0.04, "output": 1.35})


# ---------- E2EE ----------

def _kdf(shared: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"ed25519_encryption").derive(shared)


def encrypt_for(plaintext: str, model_ed25519_pub_hex: str) -> str:
    model_x = crypto_sign_ed25519_pk_to_curve25519(bytes.fromhex(model_ed25519_pub_hex))
    eph = X25519PrivateKey.generate()
    sym = _kdf(eph.exchange(X25519PublicKey.from_public_bytes(model_x)))
    nonce = secrets.token_bytes(24)
    ct = crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext.encode(), None, nonce, sym)
    return (eph.public_key().public_bytes_raw() + nonce + ct).hex()


def decrypt_with(encrypted_hex: str, client_x25519_secret: bytes) -> str:
    data = bytes.fromhex(encrypted_hex)
    eph_pub = X25519PublicKey.from_public_bytes(data[:32])
    sym = _kdf(X25519PrivateKey.from_private_bytes(client_x25519_secret).exchange(eph_pub))
    return crypto_aead_xchacha20poly1305_ietf_decrypt(data[56:], None, data[32:56], sym).decode()


# ---------- the call ----------

def ask(user_text: str, proof: dict, model: str = MODEL, max_tokens: int = 2500, system: str = SYSTEM) -> dict:
    """One sealed, end-to-end encrypted call. Returns {text, verified, chat_id, tokens}. Raises on failure."""
    ok, why = within_caps()
    if not ok:
        raise RuntimeError(why)
    client = SigningKey.generate()
    client_pub_hex = bytes(client.verify_key).hex()
    client_x_secret = crypto_sign_ed25519_sk_to_curve25519(bytes(client) + bytes(client.verify_key))
    model_pub = proof["signing_public_key"]
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": encrypt_for(system, model_pub)},
                     {"role": "user", "content": encrypt_for(user_text, model_pub)}],
        "max_tokens": max_tokens, "temperature": 0.3,
    }, separators=(",", ":")).encode()
    req = Request(f"{BASE}/chat/completions", data=body, method="POST", headers=_headers({
        "X-Signing-Algo": "ed25519", "X-Client-Pub-Key": client_pub_hex, "X-Model-Pub-Key": model_pub, "X-Encryption-Version": "2"}))
    with urlopen(req, timeout=120) as r:
        raw = r.read()
    data = json.loads(raw)
    msg = data["choices"][0]["message"]
    text = decrypt_with(msg["content"], client_x_secret) if msg.get("content") else ""
    usage = data.get("usage") or {}
    _record(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0), model)
    if not text.strip():
        # The model thinks before it writes; if the thinking used the whole budget there is no letter.
        raise RuntimeError("the sealed brain ran out of room before it wrote anything")
    verified = _verify_signature(data.get("id", ""), body, raw, model, proof)
    return {"text": text, "verified": verified, "chat_id": data.get("id"), "tokens": usage.get("total_tokens", 0)}


def _verify_signature(chat_id: str, req_body: bytes, resp_body: bytes, model: str, proof: dict) -> str:
    """Ask the gateway for the TEE's signature over this exchange and check it against the attested signer."""
    if not chat_id:
        return "no chat id"
    try:
        with urlopen(Request(f"{BASE}/signature/{chat_id}?signing_algo=ed25519", headers=_headers()), timeout=30) as r:
            sig = json.loads(r.read())
    except Exception as e:
        return f"signature not available ({e})"
    if "signature" not in sig:
        return f"signature not available ({sig.get('message') or sig.get('error_code')})"
    expected_tee = f"{model}:{hashlib.sha256(req_body).hexdigest()}:{hashlib.sha256(resp_body).hexdigest()}"
    text = sig.get("text", "")
    if sig.get("signature_kind") == "provider_tee" and text != expected_tee:
        return "signed text does not match this request and response"
    signer = (sig.get("signing_address") or "").removeprefix("0x").lower()
    if signer not in [s.lower() for s in proof.get("signers", [])]:
        return "signer is not one of today's attested models"
    for decode in (bytes.fromhex, lambda s: __import__("base64").b64decode(s)):
        try:
            VerifyKey(bytes.fromhex(signer)).verify(text.encode(), decode(sig["signature"]))
            return f"verified ({sig.get('signature_kind')})"
        except Exception:
            continue
    return "signature did not verify"


# ---------- the letter ----------

def parse_reply(text: str, labels: set[str]) -> dict:
    """Pull the letter and the menu-checked suggestions out of the model's reply. Anything off-menu is dropped."""
    start, end = text.find("{"), text.rfind("}")
    try:
        obj = json.loads(text[start:end + 1]) if start >= 0 else {}
    except ValueError:
        obj = {}
    letter = (obj.get("letter") or text).strip()
    suggestions = []
    for s in obj.get("suggestions") or []:
        if isinstance(s, dict) and s.get("action") in MENU and s.get("device") in labels and s["action"] != "none":
            suggestions.append({"device": s["device"], "action": s["action"], "why": str(s.get("why", ""))[:200]})
    return {"letter": letter[:1200], "suggestions": suggestions[:3]}


def local_letter(summary: dict) -> dict:
    """Plain words from a template. No model. Used when the brain is not sealed, over cap, or unreachable."""
    n = summary["devices_online"]
    parts = [f"Tonight {n} thing{'s' if n != 1 else ''} in your house {'are' if n != 1 else 'is'} online."]
    joined = summary["joined_today"]
    if joined and len(joined) >= max(2, n - 1):
        parts.append(f"This was Nearby's first day, so it met all {len(joined)} of them.")
    elif joined:
        parts.append("New today: " + ", ".join(joined) + ".")
    loud = sorted((d for d in summary["watched"] if d["kind"] != "this_computer"), key=lambda d: -d["lookups"])
    if loud:
        d = loud[0]
        names = "name" if d["lookups"] == 1 else "names"
        parts.append(f"The {d['label']} asked for {d['lookups']} {names}, mostly {', '.join(d['top'][:3])}." if d["top"] else f"The {d['label']} asked for {d['lookups']} {names}.")
        if d["new"] and not d["first_day"]:
            parts.append("New names it never asked for before: " + ", ".join(d["new"][:3]) + ".")
    else:
        parts.append("Nothing was pointed at the phone book today, so there is nothing to report on what was asked.")
    odd = summary.get("odd") or []
    if odd:
        f = odd[0]
        parts.append(f"One thing worth a look: the {f['label']} {f['text']}")
        if len(odd) > 1:
            parts.append(f"{len(odd) - 1} more on the house page.")
    else:
        parts.append("Nothing here needs you tonight.")
    return {"letter": " ".join(parts), "suggestions": []}
