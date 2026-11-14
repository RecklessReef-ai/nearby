"""A door for an AI the owner chooses: Nearby as an MCP connector, behind a password.

Off unless NEARBY_MCP_TOKEN is set in .env. Every request must carry it as
`Authorization: Bearer <token>`. Ten wrong tries from one address lock that address out for ten minutes.

What comes through the door is what the sealed brain is shown, and nothing more: gadgets by name and kind,
counts, the names they asked for, what the detectors noticed, which fixes are on. Never a network address,
never a hardware address, never a clock time. A gadget is always called by its name.

An assistant cannot change anything through it. The `fix` tool is an ask: it waits on Nearby's page until the
owner says yes or no, and lapses after fifteen minutes. A yes then does exactly what the owner's own tap would.
The same guard rails hold at the ask and again at the yes: never the router, never Nearby itself, nothing off the menu.

Said plainly: an AI connected here is not the sealed brain. Whatever it reads leaves the house under that
AI's own rules. That is the owner's choice to make, which is why the door is shut until they set a password.

The wire format is MCP's streamable HTTP, kept to the plain request-and-answer part: no sessions, no streams.
"""
from __future__ import annotations

import hmac
import os
import time

from . import __version__, chat, find, fixes, letters

PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TRIES, LOCK_SECONDS = 10, 600
_strikes: dict[str, list[float]] = {}

TOOLS = [
    {"name": "house",
     "description": "What is in the home right now, as Nearby sees it: each gadget by name and kind, how many names it asked the house phone book for today and which, what the detectors noticed, which fixes are on, what can be done to each gadget, and where Nearby sits on the network. Counts and names only: no addresses, no times.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "fixes",
     "description": "Which fixes are on right now (quieted or blocked gadgets, and since which day), which asks are still waiting for the owner's yes, and the last few changes with who made them.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "fix",
     "description": "Ask the owner to do one fix on one gadget, or to take one back. This changes nothing by itself: the ask shows on Nearby's page and the owner says yes or no there. It lapses after 15 minutes. quiet: turn on the maker's own list of ad and tracking names (only for gadgets the house tool says can be quieted). block: refuse every name that gadget asks for, which stops most gadgets reaching the internet. undo=true asks to take a fix back. The router and Nearby itself can never be blocked. Tell the person what you asked for, and to open Nearby to answer. Call `fixes` afterwards to see what they decided.",
     "inputSchema": {"type": "object", "additionalProperties": False, "required": ["device", "action"], "properties": {
         "device": {"type": "string", "description": "The gadget's name, exactly as the house tool gives it."},
         "action": {"type": "string", "enum": ["quiet", "block"]},
         "undo": {"type": "boolean", "description": "true to take the fix back. Default false."}}}},
    {"name": "letter",
     "description": "The latest letter Nearby wrote about the house, in plain words, and whether it was written by the sealed brain on NEAR AI Cloud or locally.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
INSTRUCTIONS = ("Nearby keeps one home's network. Call `house` first. Gadgets are known by name only; you are never given addresses. "
                "You cannot change anything yourself. `fix` asks the owner, who answers on Nearby's page; every fix has an undo. Nearby sits beside the router as the "
                "house phone book: it knows who is home and which names each gadget asks for, not what a gadget actually sends.")


def token() -> str:
    t = os.environ.get("NEARBY_MCP_TOKEN", "").strip()
    return t if len(t) >= 24 else ""  # a short password is treated as no password: the door stays shut


def allowed(header: str) -> bool:
    t = token()
    return bool(t) and hmac.compare_digest((header or "").encode(), f"Bearer {t}".encode())


def locked(who: str) -> bool:
    now = time.time()
    _strikes[who] = [t for t in _strikes.get(who, []) if now - t < LOCK_SECONDS]
    return len(_strikes[who]) >= MAX_TRIES


def strike(who: str) -> None:
    _strikes.setdefault(who, []).append(time.time())


def _house() -> str:
    return chat.house()[0]


def _fixes() -> str:
    s = fixes.load()
    devices = find.load().get("devices", {})
    words = {"quiet": "quieted", "block": "blocked"}
    who = lambda mac: (devices.get(mac) or {}).get("label") or "a gadget no longer seen"
    on = [f"- {who(mac)}: {words[a]} since {v.get('at', '')[:10]}" for mac, acts in s["active"].items() for a, v in acts.items() if a in words]
    on += [f"- {who(mac)}: name-fenced since {acts['only'].get('at', '')[:10]}, may only ask for {', '.join(acts['only'].get('sites', []))}" for mac, acts in s["active"].items() if "only" in acts]
    on += [f"- {who(mac)}: may no longer ask for {site}" for mac, acts in s["active"].items() for site in sorted(acts.get("names") or {})]
    log = [f"- {e['at'][:10]}: {'undid ' if e.get('undo') else ''}{'stop ' + e['name'] if e.get('name') else e['action']} on {e.get('label') or 'a gadget'}, by {'the owner' if e.get('by', 'owner') == 'owner' else e['by'] + ' with the owner\'s yes'}" for e in s["log"][-10:]]
    waiting = [f"- {a['text']}" for a in fixes.asks()]
    return ("On now:\n" + ("\n".join(on) or "- nothing") + "\n\nWaiting for the owner's yes:\n" + ("\n".join(waiting) or "- nothing")
            + "\n\nLast changes:\n" + ("\n".join(log) or "- none yet"))


def _fix(device: str, action: str, undo: bool = False) -> str:
    same = [d for d in find.load().get("devices", {}).values() if d.get("online") and (d.get("label") or "something") == device]
    if not same:
        raise fixes.Refused(f'No gadget called "{device}" is home right now. Call house for the names.')
    if len(same) > 1:
        raise fixes.Refused(f'{len(same)} gadgets share the name "{device}", so Nearby won\'t guess which. The owner can tap the right one on the house page.')
    a = fixes.ask(same[0]["mac"], action, bool(undo), who="an assistant")
    return f'Asked: "{a["text"]}". Nothing has changed. The owner has to say yes on Nearby\'s page within {fixes.ASK_MINUTES} minutes. Call fixes to see what they decided.'


def _letter() -> str:
    r = letters.latest()
    if not r:
        return "No letter has been written yet."
    where = "written in the sealed room on NEAR AI Cloud" if r.get("source") == "sealed" else "written locally, from a template"
    return f"{r['date']} ({where}):\n\n{r['letter']}"


def call(name: str, args: dict) -> tuple[str, bool]:
    """Run one tool. Returns (text, is_error). Never raises: the reason goes back to the AI in plain words."""
    try:
        if name == "house":
            return _house(), False
        if name == "fixes":
            return _fixes(), False
        if name == "letter":
            return _letter(), False
        if name == "fix":
            if args.get("action") not in ("quiet", "block") or not isinstance(args.get("device"), str):
                return "fix needs a device name and an action of quiet or block.", True
            return _fix(args["device"], args["action"], args.get("undo") is True), False
        return f"Nearby has no tool called {name}.", True
    except fixes.Refused as e:
        return str(e), True
    except Exception as e:
        return f"Nearby could not do that: {e}", True


def handle(msg) -> dict | None:
    """One JSON-RPC message in, its answer out. None for a notification, which gets no answer."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "not a JSON-RPC 2.0 message"}}
    if "id" not in msg:
        return None
    mid, method, params = msg["id"], msg.get("method"), msg.get("params")
    params = params if isinstance(params, dict) else {}

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        want = params.get("protocolVersion")
        return ok({"protocolVersion": want if want in PROTOCOLS else PROTOCOLS[0], "capabilities": {"tools": {}},
                   "serverInfo": {"name": "nearby", "title": "Nearby", "version": __version__}, "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        args = params.get("arguments")
        text, is_error = call(str(params.get("name")), args if isinstance(args, dict) else {})
        return ok({"content": [{"type": "text", "text": text}], "isError": is_error})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Nearby does not know the method {method}"}}
