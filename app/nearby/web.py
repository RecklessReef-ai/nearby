"""The one page. Minute one: how many things are in the house, named. Tap one, read its card."""
from __future__ import annotations

import html
import ipaddress
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from datetime import datetime

from . import __version__, brain, find, housekey, letters
from .cards import card

SCAN_EVERY = int(os.environ.get("SCAN_EVERY", "10")) * 60
LETTER_HOUR = int(os.environ.get("LETTER_HOUR", "20"))  # local time
_lock = threading.Lock()
_letter_lock = threading.Lock()


def _loop() -> None:
    while True:
        try:
            with _lock:
                find.scan()
        except Exception as e:  # keep sweeping no matter what
            print("scan failed:", e)
        time.sleep(SCAN_EVERY)


def _evening_loop() -> None:
    """Once a day at LETTER_HOUR local: a letter if anything changed; on Sundays, the weekly letter no matter what."""
    done_for = None
    while True:
        now = datetime.now()
        if now.hour == LETTER_HOUR and done_for != now.date():
            done_for = now.date()
            try:
                with _letter_lock:
                    letters.write(weekly=(now.weekday() == 6))
            except Exception as e:
                print("letter failed:", e)
        time.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    housekey.load_or_make()
    threading.Thread(target=_loop, daemon=True).start()
    threading.Thread(target=_evening_loop, daemon=True).start()
    yield


app = FastAPI(title="Nearby", version=__version__, lifespan=lifespan)

STYLE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nearby</title>
<style>
:root{--bg:#f7f6f2;--fg:#1b1b1b;--muted:#6b6b6b;--line:#e3e1da;--card:#fff;--accent:#1f6f5f;--tag:#fff3c4}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#141413;--fg:#efede6;--muted:#9a978f;--line:#2a2a28;--card:#1d1d1b;--accent:#6fcbb6;--tag:#4a3d12}}
:root[data-theme=dark]{--bg:#141413;--fg:#efede6;--muted:#9a978f;--line:#2a2a28;--card:#1d1d1b;--accent:#6fcbb6;--tag:#4a3d12}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:640px;margin:0 auto;padding:40px 16px 80px}
h1{font-size:clamp(26px,6vw,36px);line-height:1.15;margin:0 0 8px;font-weight:650}
.sub{color:var(--muted);margin:0 0 28px}
details{border-top:1px solid var(--line)}details:last-of-type{border-bottom:1px solid var(--line)}
summary{list-style:none;cursor:pointer;display:flex;align-items:baseline;gap:10px;padding:16px 0}summary::-webkit-details-marker{display:none}
.name{font-weight:600;font-size:19px}.maker{margin-left:auto;color:var(--muted);font-size:14px;white-space:nowrap}
.tag{background:var(--tag);font-size:12px;padding:2px 7px;border-radius:999px}
.card{background:var(--card);border-radius:12px;padding:16px 18px;margin:0 0 18px}
.card h4{margin:16px 0 6px;font-size:14px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
.card ul{margin:0;padding-left:20px}.card li{margin:4px 0}.fact{color:var(--accent);font-weight:600}
.feel{font-style:italic;color:var(--muted)}.tech{font-size:12px;color:var(--muted);margin:14px 0 0}
.wall{margin-top:40px;padding:18px;border:1px dashed var(--line);border-radius:12px;color:var(--muted)}
button{margin-top:24px;background:none;border:1px solid var(--line);color:var(--fg);padding:10px 16px;border-radius:999px;font:inherit;cursor:pointer}
footer{margin-top:40px;font-size:13px;color:var(--muted)}
</style></head><body>"""

ORDER = ["samsung_tv", "google_tv", "roku", "cloud_gadget", "unknown", "game_console", "router", "phone", "phone_or_laptop", "this_computer"]


@app.get("/health")
def health():
    s = find.load()
    return {"ok": True, "version": __version__, "last_scan": s.get("last_scan"), "devices": len(s.get("devices", {}))}


@app.get("/api/devices")
def devices():
    return find.load()


@app.post("/api/scan")
def rescan():
    with _lock:
        return JSONResponse(find.scan())


@app.get("/api/brain")
def brain_status():
    proof = brain.proof_today() or {}
    ok, why = brain.within_caps()
    return {"model": brain.MODEL, "sealed_list": list(brain.SEALED_MODELS), "key_present": bool(brain.key()),
            "today": {k: proof.get(k) for k in ("ok", "checked_at", "signing_address", "checks", "error")},
            "caps_ok": ok, "caps_note": why, "house": housekey.account_id(), "house_key": housekey.public_key_near()}


@app.post("/api/brain/check")
def brain_check():
    return brain.morning_check(force=True)


@app.post("/api/letter")
def write_letter(force: bool = True, weekly: bool = False):
    with _letter_lock:
        r = letters.write(force=force, weekly=weekly)
    return r or {"quiet": True, "letter": None}


@app.get("/api/letters")
def list_letters():
    return letters.all_letters()


@app.get("/letter", response_class=HTMLResponse)
def letter_page():
    r = letters.latest()
    status = brain.proof_today() or {}
    if r:
        where = ("Written in a sealed room on NEAR AI Cloud. " + html.escape(str(r.get("detail", ""))) + "."
                 if r["source"] == "sealed" else "Written here, from a template. " + html.escape(str(r.get("detail", ""))) + ".")
        sugg = "".join(f"<li><b>{html.escape(s['action'])}</b> the {html.escape(s['device'])}. {html.escape(s['why'])}</li>" for s in r["suggestions"])
        body = f"""<h1>Your house, {html.escape(r['date'])}</h1>
<p class="letter">{html.escape(r['letter'])}</p>
{('<h4>Nearby suggests</h4><ul>' + sugg + '</ul><p class="sub">Taps for these land on day 7. Nothing happens until you tap.</p>') if sugg else ''}
<div class="wall"><strong>Where these words came from.</strong> {where}<br>
Sent to the brain: counters only, {len((r.get('sent_to_brain') or '').split())} words, no addresses, no times.<br>
Signed by this house's key <code>{html.escape(r['house'][:16])}…</code></div>"""
    else:
        body = """<h1>No letter yet.</h1><p class="sub">The first one is written at 8 pm, or now with the button.</p>"""
    seal = ("Sealed brain checked today at " + html.escape(str(status.get("checked_at", ""))[11:16]) + " UTC." if status.get("ok")
            else "Sealed brain: " + html.escape(str(status.get("error") or "not checked yet today")) + ".")
    return STYLE + f"""<main>{body}
<p class="sub">{seal} Model: {html.escape(brain.MODEL)}.</p>
<button onclick="this.disabled=true;this.textContent='Writing…';fetch('/api/letter',{{method:'POST'}}).then(()=>location.reload())">Write tonight's letter now</button>
<button onclick="this.disabled=true;fetch('/api/brain/check',{{method:'POST'}}).then(()=>location.reload())">Check the seal</button>
<p><a href="/">Back to the house</a></p>
</main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def page():
    s = find.load()
    devs = [d for d in s.get("devices", {}).values() if d.get("online")]
    devs.sort(key=lambda d: (ORDER.index(d["kind"]) if d["kind"] in ORDER else 99, ipaddress.ip_address(d["ip"])))
    others = [d for d in devs if d["kind"] != "this_computer"]
    n = len(others)
    lan_ip = s.get("me", "this computer")
    if not s.get("last_scan"):
        headline, sub = "Looking around the house.", "The first look takes about ten seconds. Refresh in a moment."
    else:
        headline = f"{n} thing{'s' if n != 1 else ''} in your house {'are' if n != 1 else 'is'} talking to the internet right now."
        sub = "Tap one to read what it is and what it sends home."
    items = []
    for d in devs:
        c = card(d["kind"], lan_ip)
        new = ' <span class="tag">new</span>' if d.get("is_new") else ""
        facts = d.get("facts") or {}
        fact_line = ""
        if d["kind"] == "google_tv" and facts.get("usage_stats_on"):
            fact_line = "Usage reports to Google: on."
        if d["kind"] == "samsung_tv" and str(facts.get("smartHubAgreement")).lower() == "true":
            fact_line = "Smart Hub agreement: on. Voice: " + ("on." if str(facts.get("VoiceSupport")).lower() == "true" else "off.")
        items.append(f"""
<details>
  <summary><span class="name">{html.escape(d['label'] or 'something')}</span>{new}<span class="maker">{html.escape(d['maker'])}</span></summary>
  <div class="card">
    <p>{html.escape(c['what'])}</p>
    {f'<p class="fact">{html.escape(fact_line)}</p>' if fact_line else ''}
    <h4>What it sends home</h4><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in c['sends_home'])}</ul>
    {('<h4>The switch</h4><ul>' + ''.join(f'<li>{html.escape(x)}</li>' for x in c['switches']) + '</ul>') if c['switches'] else ''}
    <h4>What Nearby can do</h4><p>{html.escape(c['nearby_can'])}</p>
    <p class="feel">{html.escape(c['feeling'])}</p>
    <p class="tech">{html.escape(d['ip'])} · {html.escape(d['mac'])} · first seen {html.escape((d.get('first_seen') or '')[:10])}</p>
  </div>
</details>""")
    return STYLE + f"""<main>
<h1>{html.escape(headline)}</h1>
<p class="sub">{html.escape(sub)}</p>
{''.join(items)}
<button onclick="fetch('/api/scan',{{method:'POST'}}).then(()=>location.reload())">Look again</button>
<div class="wall"><strong>What this computer can't see.</strong> It knows who is in the house, not what they say. A laptop only hears its own traffic. To see what the TV sends, something has to sit at the door, where the internet comes in.</div>
<p><a href="/letter">Tonight's letter</a></p>
<footer>Nearby {__version__} · last look {html.escape(s.get('last_scan') or 'none yet')} UTC · everything here was learned from the network alone. No name was searched online.</footer>
</main></body></html>"""
