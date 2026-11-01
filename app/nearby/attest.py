"""Check that the brain is sealed before trusting it.

Follows NEAR AI Cloud's published check (docs.near.ai, "quote, nonce and signer"):
verify the Intel TDX quote with dcap-qvl, refuse debug mode, confirm the quote
binds our fresh nonce and the model's signing key, confirm the measured config
and the event log, and (when GPU evidence is present) ask NVIDIA's attestation
service about the GPU. Any failure means: not sealed today, use local words.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import struct
from urllib.request import Request, urlopen

import dcap_qvl

ACCEPTED_TCB = {"UpToDate", "SWHardeningNeeded"}
NRAS = "https://nras.attestation.nvidia.com/v3/attest/gpu"


def _json(value):
    return json.loads(value) if isinstance(value, str) else value


def _signing_identity(report: dict) -> bytes:
    identity = bytes.fromhex(report["signing_address"].removeprefix("0x"))
    if {"ecdsa": 20, "ed25519": 32}.get(report["signing_algo"]) != len(identity):
        raise ValueError("unsupported signing identity")
    return identity


def replay_rtmr3(event_log) -> bytes:
    rtmr3 = bytes(48)
    for event in _json(event_log):
        if event.get("imr") != 3:
            continue
        digest = hashlib.sha384(
            struct.pack("<I", event["event_type"]) + b":" + event["event"].encode("utf-8") + b":"
            + bytes.fromhex(event.get("event_payload") or "")
        ).digest()
        if event.get("digest") and bytes.fromhex(event["digest"]) != digest:
            raise ValueError(f"digest mismatch for event {event['event']}")
        rtmr3 = hashlib.sha384(rtmr3 + digest).digest()
    return rtmr3


def _verify_quote(raw: bytes):
    result = dcap_qvl.get_collateral_and_verify(raw)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result


def check_report(report: dict, nonce_hex: str, verify_quote=_verify_quote) -> dict:
    """Return the checks dict. Raises ValueError on the first failed check."""
    checks: dict[str, object] = {}
    verified = verify_quote(bytes.fromhex(report["intel_quote"]))
    status = getattr(verified, "status", None) or json.loads(verified.to_json()).get("status")
    if status not in ACCEPTED_TCB:
        raise ValueError(f"TCB status {status} not accepted: {getattr(verified, 'advisory_ids', '')}")
    checks["tcb_status"] = status
    quote = json.loads(verified.to_json())["report"]["TD10"]

    if bytes.fromhex(quote["td_attributes"])[0] & 1:
        raise ValueError("TDX debug mode is enabled")
    checks["debug_off"] = True

    identity = _signing_identity(report)
    fingerprint = report.get("tls_cert_fingerprint")
    bound = hashlib.sha256(identity + bytes.fromhex(fingerprint)).digest() if fingerprint else identity.ljust(32, b"\0")
    if bytes.fromhex(quote["report_data"]) != bound + bytes.fromhex(nonce_hex):
        raise ValueError("report data does not bind the signer and nonce")
    if report["request_nonce"].lower() != nonce_hex.lower():
        raise ValueError("echoed nonce does not match")
    checks["nonce_and_signer_bound"] = True

    app_compose = _json(report["info"]["tcb_info"])["app_compose"]
    if bytes.fromhex(quote["mr_config_id"]) != b"\x01" + hashlib.sha256(app_compose.encode("utf-8")).digest() + bytes(15):
        raise ValueError("MRCONFIGID does not match app_compose")
    checks["config_measured"] = True

    if replay_rtmr3(report["event_log"]) != bytes.fromhex(quote["rt_mr3"]):
        raise ValueError("event log does not match RTMR3")
    checks["event_log_matches"] = True

    payload = report.get("nvidia_payload")
    if payload:
        checks["gpu"] = check_gpu(_json(payload), nonce_hex)
    else:
        checks["gpu"] = "no GPU evidence in report"
    checks["quote_sha256"] = hashlib.sha256(bytes.fromhex(report["intel_quote"])).hexdigest()
    return checks


def check_gpu(payload: dict, nonce_hex: str) -> str:
    if str(payload.get("nonce", "")).lower() != nonce_hex.lower():
        raise ValueError("GPU evidence nonce does not match")
    req = Request(NRAS, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urlopen(req, timeout=30) as r:
        answer = json.loads(r.read())
    token = answer[0][1] if isinstance(answer, list) and answer and isinstance(answer[0], list) else None
    if not token:
        raise ValueError("NVIDIA attestation service gave no token")
    body = token.split(".")[1]
    body += "=" * (-len(body) % 4)
    claims = json.loads(__import__("base64").urlsafe_b64decode(body))
    if claims.get("x-nvidia-overall-att-result") is not True:
        raise ValueError("NVIDIA attestation result is not true")
    return "verified by NVIDIA NRAS"
