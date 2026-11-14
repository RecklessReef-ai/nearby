"""Ask the sealed brain about the house.

The same rules as the letter, because it is the same brain:
- It is shown counters only: which gadgets are home, what kind each is, how many names each asked for,
  what the detectors noticed, which fixes are on. Never an address, never a clock time.
- The owner's own words go the same way: sealed, end to end, to the attested model. A question that
  carries an address is turned back before it leaves the house.
- It can't change anything. It may suggest from the fixed menu, for gadgets on the list; the page turns
  a suggestion into a tap, and plain code on the Pi does the work. Off-menu suggestions are dropped here.
- If the brain isn't sealed today, is over its cap or can't be reached, Nearby says so and answers
  from what it can see by itself. It never asks a less private model instead.

Nothing about the talk is kept on the Pi. The page holds the last few turns and sends them along.
"""
from __future__ import annotations

import json
import os

from . import brain, counters, detectors, find, fixes

MAX_QUESTION = 500
KEEP_TURNS = 6
ACTIONS = ("quiet", "block", "fence")
WHERE = {
    "beside": "Where Nearby sits: beside the router, as the house's phone book. It knows who is home and which names each gadget asks for. It does not see what a gadget actually sends, and a gadget that carries its own phone book goes around it.",
    "door": "Where Nearby sits: at the door, between the modem and the router. Everything the house sends passes through it.",
    "router": "Where Nearby sits: it is the router. Everything the house sends passes through it.",
}

SYSTEM = """You are Nearby, the keeper of one home's network, talking with the person who lives there.
You are shown counters only: which gadgets are home, what kind each is, how many names each asked for and which, what the detectors noticed, and which fixes are on. That is all you know about this house. Never claim to know more, and never invent a fact.
Speak in plain words and short sentences. No jargon without a one-clause explanation. Never alarm. At most 110 words.
You cannot change anything yourself. You may suggest actions ONLY from this menu, only for gadgets on the list, using the label exactly as given:
quiet (turn on the maker's own list of ad and tracking names; only where the list says the gadget can be quieted), block (refuse every name that gadget asks for; only where the list says it can be blocked), fence (move it to the guest Wi-Fi so it can't reach other devices; the owner does this by hand in the router), none.
Suggest at most two actions, and only when they answer what was asked. The owner taps to make one happen, and every tap has an undo.
If asked how to change a setting on a router or a gadget, give at most four short numbered steps in general terms and say the owner does them by hand.
If the counters don't answer the question, say what Nearby can't see from where it sits.
Reply as JSON only: {"reply": "...", "suggestions": [{"device": "<label exactly as given>", "action": "<menu word>", "why": "<one plain sentence>"}]}"""


class Refused(Exception):
    """The question can't be sent, with a reason fit to show the owner."""


def house() -> tuple[str, dict, dict]:
    """What the brain is shown about the house, the day's counters, and the gadgets by label."""
    summary = counters.summarize(update_baseline=False)
    summary["odd"] = [{"label": f["label"], "type": f["type"], "text": f["text"]} for f in detectors.latest()["findings"]]
    active = fixes.load()["active"]
    by_label: dict[str, list[dict]] = {}
    lines = [counters.as_text(summary), "", "Gadgets home now, and what Nearby can do to each:"]
    for d in find.load().get("devices", {}).values():
        if not d.get("online") or d["kind"] == "this_computer":
            continue
        label = d["label"] or "something"
        by_label.setdefault(label, []).append(d)
        can = fixes.can(d)
        on = sorted(a for a in active.get(d["mac"], {}) if a in ACTIONS)
        lines.append(f"- {label} ({d['kind'].replace('_', ' ')}): " + (f"can be {' or '.join('quieted' if a == 'quiet' else 'blocked' for a in can)}" if can else "can only be watched")
                     + (f"; on now: {', '.join(on)}" if on else ""))
    lines += ["", WHERE.get(os.environ.get("NEARBY_SEAT", "beside"), WHERE["beside"])]
    text = "\n".join(lines)
    if counters.has_address(text):
        raise ValueError("the house summary contains an address or a timestamp; refusing to send")
    return text, summary, by_label


def parse(text: str, by_label: dict) -> dict:
    """The reply and the menu-checked suggestions. Anything off the menu, or about a gadget not on the list, is dropped."""
    start, end = text.find("{"), text.rfind("}")
    try:
        obj = json.loads(text[start:end + 1]) if start >= 0 else {}
    except ValueError:
        obj = {}
    if not isinstance(obj, dict):
        obj = {}
    active = fixes.load()["active"]
    suggestions = []
    for s in obj.get("suggestions") or []:
        if not (isinstance(s, dict) and s.get("action") in ACTIONS and s.get("device") in by_label):
            continue
        same = by_label[s["device"]]
        dev = same[0] if len(same) == 1 else None  # two gadgets with one name: Nearby won't guess which
        suggestions.append({
            "device": s["device"], "action": s["action"], "why": str(s.get("why", ""))[:200],
            "mac": dev["mac"] if dev else None,
            "can": bool(dev) and s["action"] in fixes.can(dev),
            "on": bool(dev) and s["action"] in active.get(dev["mac"], {}),
        })
    return {"reply": str(obj.get("reply") or text).strip()[:1500], "suggestions": suggestions[:2]}


def _local(why: str, summary: dict | None) -> dict:
    seen = (" What I can see by myself: " + brain.local_letter(summary)["letter"]) if summary else ""
    return {"reply": f"I can't reach the sealed brain right now ({why}), and I won't ask anywhere less private.{seen}",
            "suggestions": [], "source": "local", "detail": why, "tokens": 0}


def answer(question: str, history: list | None = None) -> dict:
    """One turn. Returns {reply, suggestions, source, detail, tokens}. Raises Refused for a question that can't be sent."""
    q = " ".join(str(question or "").split())[:MAX_QUESTION]
    if not q:
        raise Refused("Type a question first.")
    turns = []
    for t in (history or [])[-KEEP_TURNS:]:
        if isinstance(t, dict) and t.get("who") in ("you", "nearby") and t.get("text"):
            turns.append(("Owner" if t["who"] == "you" else "Nearby") + ": " + " ".join(str(t["text"]).split())[:600])
    said = "\n".join(turns)
    if counters.has_address(q + "\n" + said):
        raise Refused('Leave out addresses and exact times. Call the gadget by its name, like "the Office TV".')
    try:
        text, summary, by_label = house()
    except Exception as e:
        return _local(str(e), None)
    proof = brain.morning_check()
    if not proof.get("ok"):
        return _local(proof.get("error") or "not sealed today", summary)
    prompt = text + ("\n\nEarlier in this talk:\n" + said if said else "") + "\n\nThe owner asks: " + q
    try:
        got = brain.ask(prompt, proof, system=SYSTEM)
    except Exception as e:
        return _local(str(e), summary)
    out = parse(got["text"], by_label)
    out.update(source="sealed", detail=got["verified"], tokens=got["tokens"])
    return out
