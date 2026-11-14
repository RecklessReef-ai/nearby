"""The one page. Minute one: how many things are in the house, named. Tap one, read its card."""
from __future__ import annotations

import html
import ipaddress
import os
import threading
import time
from collections import defaultdict
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response

from datetime import datetime

from . import __version__, brain, chat, connector, counters, detectors, find, fixes, housekey, letters
from .cards import card

SCAN_EVERY = int(os.environ.get("SCAN_EVERY", "10")) * 60
LETTER_HOUR = int(os.environ.get("LETTER_HOUR", "20"))  # local time
_lock = threading.Lock()
_letter_lock = threading.Lock()
_chat_lock = threading.Lock()


def _loop() -> None:
    while True:
        try:
            with _lock:
                find.scan()
        except Exception as e:  # keep sweeping no matter what
            print("scan failed:", e)
        try:
            fixes.resync()  # a blocked gadget that changed address stays blocked; one that left loses its rule
        except Exception as e:
            print("fix sync failed:", e)
        try:
            detectors.run()
        except Exception as e:
            print("detectors failed:", e)
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


def _own_address(host: str) -> bool:
    """Nearby is reached by its number on the home network, by localhost, or by a .local name. Never by a website's name."""
    name = host.rsplit(":", 1)[0].strip("[]") if host.count(":") == 1 or host.startswith("[") else host
    if name in ("localhost",) or name.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


@app.middleware("http")
async def home_only(request: Request, call_next):
    """A website open in the house must not be able to read Nearby or press its buttons.
    It can't use Nearby's number (the browser stops it), so it would have to arrive under its own name: refused.
    And a post must come from Nearby's own page, or from a program in the house that sends no origin at all."""
    host = request.headers.get("host", "")
    if not _own_address(host):
        return JSONResponse({"error": "Nearby only answers at its own address on the home network."}, status_code=403)
    origin = request.headers.get("origin")
    if request.method != "GET" and origin and urlparse(origin).netloc != host:
        return JSONResponse({"error": "That only works from Nearby's own page."}, status_code=403)
    return await call_next(request)

STYLE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nearby</title>
<style>
/* No web fonts and no outside files: this page never asks the internet for anything. */
:root{--bg:#f3f5f1;--panel:#fff;--fg:#151a17;--muted:#667069;--line:#dde2db;--accent:#17694f;--accent-soft:#e1f0e9;--warn:#855600;--warn-soft:#fbedc8;--stop:#a3261d;--stop-soft:#fbe3e0}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#101311;--panel:#181c19;--fg:#ecefea;--muted:#98a29b;--line:#2a302c;--accent:#6fd0b0;--accent-soft:#15322a;--warn:#f0b64a;--warn-soft:#3a2c0d;--stop:#ff9086;--stop-soft:#3d1a17;color-scheme:dark}}
:root[data-theme=dark]{--bg:#101311;--panel:#181c19;--fg:#ecefea;--muted:#98a29b;--line:#2a302c;--accent:#6fd0b0;--accent-soft:#15322a;--warn:#f0b64a;--warn-soft:#3a2c0d;--stop:#ff9086;--stop-soft:#3d1a17;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
main{max-width:620px;margin:0 auto;padding:20px 16px 72px;display:flex;flex-direction:column;gap:20px}
a{color:var(--accent)}
.top{display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;letter-spacing:-.01em}
.brand i{width:10px;height:10px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
nav{display:flex;gap:4px;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px}
nav a{padding:5px 12px;border-radius:999px;text-decoration:none;color:var(--muted);font-size:14px;font-weight:600}
nav a.here{background:var(--accent-soft);color:var(--accent)}
.hero{display:flex;flex-direction:column;gap:6px;padding:8px 0 0}
h1{font-size:clamp(27px,7.4vw,38px);line-height:1.12;letter-spacing:-.025em;margin:0;font-weight:750;text-wrap:balance}
h1 b{color:var(--accent);font-weight:inherit}
.sub{color:var(--muted);margin:0}
.eyebrow{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0}

.list{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.dev+.dev{border-top:1px solid var(--line)}
.dev>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;padding:13px 14px}
.dev>summary::-webkit-details-marker{display:none}
.dev>summary:focus-visible,button:focus-visible,nav a:focus-visible,.more>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ico{flex:none;width:40px;height:40px;border-radius:11px;display:grid;place-items:center;background:var(--bg);color:var(--muted)}
.ico svg{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.dev.look .ico{background:var(--warn-soft);color:var(--warn)}.dev.stopped .ico{background:var(--stop-soft);color:var(--stop)}
.who{min-width:0;flex:1;display:flex;flex-direction:column}
.name{font-weight:650;font-size:17px;line-height:1.25;overflow-wrap:anywhere}
.gist{color:var(--muted);font-size:14px;line-height:1.3}
.tags{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:4px;max-width:44%}
.tag{font-size:12px;font-weight:650;padding:2px 8px;border-radius:999px;white-space:nowrap;background:var(--bg);color:var(--muted)}
.tag.look{background:var(--warn-soft);color:var(--warn)}.tag.stop{background:var(--stop-soft);color:var(--stop)}.tag.on{background:var(--accent-soft);color:var(--accent)}
.chev{flex:none;width:8px;height:8px;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(45deg);margin:0 4px 4px 2px;opacity:.6}
.dev[open]>summary .chev{transform:rotate(-135deg);margin-bottom:-4px}

.card{padding:2px 14px 16px 66px;display:flex;flex-direction:column;gap:14px}
@media (max-width:480px){.card{padding-left:14px}}
.card p{margin:0}.what{font-size:16px}
.fact{color:var(--accent);font-weight:650}
.notice{background:var(--warn-soft);color:var(--fg);border-radius:10px;padding:10px 12px;font-size:15px}
.notice strong{display:block;color:var(--warn);font-size:12px;letter-spacing:.06em;text-transform:uppercase;margin-bottom:2px}
.notice ul{margin:0;padding-left:18px}
.taps{display:flex;flex-direction:column;gap:12px}
.tap{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px}
.tap .why{flex-basis:100%;font-size:13.5px;line-height:1.4;color:var(--muted)}
button{font:inherit;font-weight:650;font-size:15px;cursor:pointer;border-radius:10px;padding:8px 16px;border:1px solid var(--line);background:var(--panel);color:var(--fg)}
button.do{background:var(--fg);color:var(--bg);border-color:var(--fg)}
button:disabled{opacity:.5;cursor:default}
.err{color:var(--stop);font-size:14px}.err:empty{display:none}
.more{border-top:1px solid var(--line);padding-top:12px}
.more>summary{cursor:pointer;color:var(--accent);font-weight:650;font-size:15px;list-style:none}
.more>summary::-webkit-details-marker{display:none}.more>summary::after{content:" +"}.more[open]>summary::after{content:" \\2212"}
.more h4{margin:14px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.more ul,.more ol{margin:0;padding-left:20px;font-size:15px}.more li{margin:4px 0}.more p{font-size:15px}
.steps{border-top:0;padding-top:0}
.names{list-style:none;padding:0!important;margin:8px 0!important;display:flex;flex-direction:column}
.names li{display:flex;align-items:center;gap:10px;margin:0!important;padding:5px 0;border-bottom:1px solid var(--line)}
.names .site{flex:1;min-width:0;overflow-wrap:anywhere;font:14px ui-monospace,SFMono-Regular,Menlo,monospace}
.names .n{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}.names button{padding:4px 12px;font-size:13.5px}.more .why{font-size:13.5px;color:var(--muted)}
.feel{font-style:italic;color:var(--muted);margin-top:10px!important}
.tech{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--muted);overflow-wrap:anywhere}
.row{display:flex;flex-wrap:wrap;gap:10px}
.ask{background:var(--warn-soft);border:1px solid var(--warn);border-radius:14px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.ask p{margin:0}.ask .q{font-size:17px;font-weight:650}.ask .row button{flex:1;min-height:44px}
.wall{padding:14px 16px;border:1px dashed var(--line);border-radius:14px;color:var(--muted);font-size:15px}
.wall strong{color:var(--fg)}
.paper{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px 20px;font-size:18px;line-height:1.6}
.paper p{margin:0;max-width:60ch}
.seal{display:flex;gap:10px;align-items:flex-start;font-size:15px}
.seal i{flex:none;width:22px;height:22px;border-radius:50%;background:var(--accent-soft);color:var(--accent);display:grid;place-items:center;font-style:normal;font-weight:800;font-size:13px}
.seal.local i{background:var(--bg);color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.panel ul{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px}
.h2{font-size:20px;line-height:1.25;margin:0;letter-spacing:-.01em}.panel>.tag{align-self:flex-start}
.facts li{display:grid;grid-template-columns:150px minmax(0,1fr);gap:2px 14px;font-size:15.5px;padding-top:10px;border-top:1px solid var(--line)}
.facts .k{color:var(--muted);font-size:13.5px;font-weight:600}
.facts code{overflow-wrap:anywhere}.facts button{padding:3px 10px;font-size:13px;margin-left:4px}
@media (max-width:480px){.facts li{grid-template-columns:1fr}}
code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace}
footer{font-size:12.5px;line-height:1.5;color:var(--muted)}
/* The map is one fixed look in both themes: a dark chart table. */
.mapbox{background:#0b130f;border-radius:16px;overflow:hidden;border:1px solid #1d2c25}
.map{display:block;width:100%;height:auto;font-family:inherit}
.m-dot{fill:#1a2a22}.m-ring{fill:none;stroke:#182720;stroke-width:1}
.m-line{stroke:#2b4237;stroke-width:1.4}.m-line.heard{stroke:#2f6b56}.m-line.silent{stroke-dasharray:2 5}
.m-line.cut{stroke:#ff7a6e;stroke-dasharray:5 5;opacity:.8}.m-line.trunk{stroke:#3d7f69;stroke-width:2.5}.m-line.book{stroke:#5fe0b5;stroke-width:2}
.m-flow{stroke:#5fe0b5;stroke-width:2;stroke-linecap:round;stroke-dasharray:1 16;fill:none}
.m-x{stroke:#ff7a6e;stroke-width:2;stroke-linecap:round}
.m-node{fill:#13201a;stroke:#35584a;stroke-width:1.5}.m-ico{fill:none;stroke:#a9c7ba;stroke-width:2.2;stroke-linecap:round;stroke-linejoin:round}
.m-name,.m-sub,.m-note{paint-order:stroke;stroke:#0b130f;stroke-width:4px;stroke-linejoin:round}
.m-name{fill:#e3efe8;font-size:10.5px;font-weight:650}.m-sub{fill:#7f998c;font-size:9px}.m-note{fill:#9db5a9;font-size:8px;letter-spacing:.06em;text-transform:uppercase;stroke:none}
.m-door{fill:#0b130f;stroke:#7f998c;stroke-width:1;stroke-dasharray:3 3}
.m-a{cursor:pointer}.m-a:focus-visible .m-node{stroke:#fff;stroke-width:2.5}
.m-a.look .m-node{stroke:#ffc04d;fill:#2c230c}.m-a.look .m-ico{stroke:#ffc04d}.m-a.look .m-sub{fill:#ffc04d}
.m-a.stopped .m-node{stroke:#ff7a6e;fill:#2e1512}.m-a.stopped .m-ico{stroke:#ff7a6e}.m-a.stopped .m-sub{fill:#ff7a6e}
.m-a.quieted .m-node{stroke:#5fe0b5}
.m-home .m-node{fill:#123528;stroke:#5fe0b5;stroke-width:2}.m-home .m-ico{stroke:#5fe0b5}
.m-halo{fill:none;stroke:#ffc04d;stroke-width:1.5;opacity:0}
.key{display:flex;flex-wrap:wrap;gap:6px 16px;padding:10px 14px 12px;font-size:12.5px;color:#9db5a9;border-top:1px solid #1d2c25}
.key span{display:inline-flex;align-items:center;gap:6px}.key i{width:18px;height:0;border-top:2px solid #2f6b56}
.key .k-silent i{border-top:2px dotted #4a6a5c}.key .k-look i,.key .k-stop i{width:9px;height:9px;border-radius:50%;border:2px solid #ffc04d}.key .k-stop i{border-color:#ff7a6e}
.talk{display:flex;flex-direction:column;gap:12px;min-height:120px}
.msg{max-width:88%;padding:10px 14px;border-radius:16px;font-size:16px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}
.msg.you{align-self:flex-end;background:var(--fg);color:var(--bg);border-bottom-right-radius:4px}
.msg.nearby{align-self:flex-start;background:var(--panel);border:1px solid var(--line);border-bottom-left-radius:4px}
.msg.wait{color:var(--muted);font-style:italic}
.from{display:block;margin-top:6px;font-size:12px;color:var(--muted);white-space:normal}.from.sealed{color:var(--accent)}
.sugg{display:flex;flex-direction:column;gap:6px;margin-top:10px;padding-top:10px;border-top:1px solid var(--line);white-space:normal;font-size:15px}
.sugg .tap{gap:6px 10px}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chips button{font-weight:500;font-size:14.5px;border-radius:999px;padding:8px 14px}
.askbar{display:flex;gap:8px;position:sticky;bottom:12px}
.askbar input{flex:1;min-width:0;font:inherit;padding:11px 14px;border-radius:12px;border:1px solid var(--line);background:var(--panel);color:var(--fg)}
.askbar input:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
@media (prefers-reduced-motion:no-preference){.chev{transition:transform .15s}
 .m-flow{animation:flow 1.6s linear infinite}@keyframes flow{to{stroke-dashoffset:-17}}
 .m-halo{animation:halo 2s ease-out infinite}@keyframes halo{0%{opacity:.9;transform:scale(.8)}100%{opacity:0;transform:scale(1.5)}}}
</style></head><body>"""

ICONS = {
    "samsung_tv": '<rect x="3" y="5" width="18" height="12" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "google_tv": '<path d="M4 8V7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2h-5"/><path d="M4 12a7 7 0 0 1 7 7M4 16a3 3 0 0 1 3 3M4 19.5h.01"/>',
    "cloud_gadget": '<path d="M9 3v5M15 3v5M7 8h10v3a5 5 0 0 1-10 0zM12 16v5"/>',
    "router": '<rect x="3" y="13" width="18" height="6" rx="2"/><path d="M7 16h.01M11 16h.01M8 13L6 6M16 13l2-7"/>',
    "game_console": '<rect x="2" y="8" width="20" height="9" rx="4.5"/><path d="M7 11v3M5.5 12.5h3M16 12.5h.01M18.5 12.5h.01"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    "phone_or_laptop": '<rect x="5" y="5" width="14" height="10" rx="1.5"/><path d="M2.5 19h19"/>',
    "this_computer": '<path d="M4 11l8-7 8 7M6 10v9h12v-9M10 19v-5h4v5"/>',
    "unknown": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01"/>',
}
ICONS["roku"] = ICONS["google_tv"]


ICONS["internet"] = '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>'


ON_BATTERY = any(Path("/sys/class/power_supply").glob("BAT*"))  # a laptop: Nearby only watches while it is awake


def map_svg(devs: list[dict], active: dict, noticed_by: dict, lookups: dict) -> str:
    """The house as a map, top to bottom the way the wires run: the internet, the router with Nearby beside it, then every gadget.
    A line with moving dots means Nearby hears that gadget; a dotted line means it doesn't. Tap a gadget for its card."""
    W, cx, top_y, door_y, hub_y = 360, 180, 44, 107, 172
    router = next((d for d in devs if d["kind"] == "router"), None)
    me = next((d for d in devs if d["kind"] == "this_computer"), None)
    fan = [d for d in devs if d["kind"] not in ("router", "this_computer")]

    def short(text: str, n: int = 13) -> str:
        return html.escape(text if len(text) <= n else text[:n - 1].rstrip() + "…")

    def node(x: float, y: float, kind: str, name: str, note: str, cls: str = "", mac: str = "", r: int = 19, label: str = "below") -> str:
        tx, ty, anchor = {"below": (x, y + r + 13, "middle"), "right": (x + r + 8, y - 1, "start"), "left": (x - r - 8, y - 1, "end")}[label]
        halo = f'<circle class="m-halo" cx="{x:.1f}" cy="{y:.1f}" r="{r + 5}" style="transform-origin:{x:.1f}px {y:.1f}px"/>' if "look" in cls else ""
        body = (f'{halo}<circle class="m-node" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>'
                f'<g class="m-ico" transform="translate({x - 9:.1f},{y - 9:.1f}) scale(.75)">{ICONS.get(kind, ICONS["unknown"])}</g>'
                f'<text class="m-name" x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}">{short(name)}</text>'
                f'<text class="m-sub" x="{tx:.1f}" y="{ty + 11:.1f}" text-anchor="{anchor}">{html.escape(note)}</text>')
        if not mac:
            return f'<g class="{cls}">{body}</g>'
        return f'<a class="m-a {cls}" href="#d{html.escape(mac.replace(":", ""))}" aria-label="{html.escape(name)}: {html.escape(note)}">{body}</a>'

    # gadgets stand in rows below the router, four then three, so every name has room at phone width
    rows, i = [], 0
    while i < len(fan):
        k = 4 if len(rows) % 2 == 0 else 3
        rows.append(fan[i:i + k])
        i += k
    spots = []
    for r, row in enumerate(rows):
        for j, d in enumerate(row):
            x = W * (j + 0.5) / len(row)
            spots.append((d, x, hub_y + 94 + 90 * r - 16 * ((x - cx) / 160) ** 2))  # the ends lift a little, like a fan
    H = round(max([y for _, _, y in spots] + [hub_y + 60]) + 58)

    lines, nodes = [], []
    for d, x, y in spots:
        on, noticed, n = active.get(d["mac"], {}), noticed_by.get(d["mac"]), lookups.get(d["mac"], 0)
        if "block" in on:
            mx, my = (x + cx) / 2, (y + hub_y) / 2
            lines.append(f'<line class="m-line cut" x1="{x:.1f}" y1="{y:.1f}" x2="{cx}" y2="{hub_y}"/>'
                         f'<path class="m-x" d="M{mx - 4:.1f} {my - 4:.1f}l8 8M{mx + 4:.1f} {my - 4:.1f}l-8 8"/>')
            cls, note = "stopped", "blocked"
        else:
            heard = n
            lines.append(f'<line class="m-line {"heard" if heard else "silent"}" x1="{x:.1f}" y1="{y:.1f}" x2="{cx}" y2="{hub_y}"/>')
            if heard:
                lines.append(f'<line class="m-flow" x1="{x:.1f}" y1="{y:.1f}" x2="{cx}" y2="{hub_y}"/>')
            cls = "look" if noticed else "quieted" if "quiet" in on else ""
            note = "worth a look" if noticed else f"{n} lookup{'s' if n != 1 else ''}" if n else "not heard"
        nodes.append(node(x, y, d["kind"], d["label"] or "something", note, cls, d["mac"]))

    lines.append(f'<line class="m-line trunk" x1="{cx}" y1="{top_y}" x2="{cx}" y2="{hub_y}"/><line class="m-flow" x1="{cx}" y1="{hub_y}" x2="{cx}" y2="{top_y}"/>')
    nodes.append(node(cx, top_y, "internet", "Internet", "outside the house", label="right"))
    my_mac, words = (me or {}).get("mac", ""), "the phone book" + (", while awake" if ON_BATTERY else "")
    router_name, router_note, router_mac = (router["label"], router["ip"], router["mac"]) if router else ("the router", "", "")
    lines.append(f'<rect class="m-door" x="{cx - 30}" y="{door_y - 8}" width="60" height="16" rx="8"/><text class="m-note" x="{cx}" y="{door_y + 3.5}" text-anchor="middle">the door</text>')
    lines.append(f'<line class="m-line book" x1="{cx}" y1="{hub_y}" x2="{cx + 78}" y2="{hub_y}"/><line class="m-flow" x1="{cx}" y1="{hub_y}" x2="{cx + 78}" y2="{hub_y}"/>')
    nodes.append(node(cx + 78, hub_y, "this_computer", "Nearby", words, "m-home", my_mac, r=20, label="right"))
    nodes.append(node(cx, hub_y, "router", router_name, router_note, "", router_mac, r=22, label="left"))

    return (f'<div class="mapbox"><svg class="map" viewBox="0 0 {W} {H}" role="img" aria-label="Map of the house network: the internet at the top, the router below it, {len(fan)} gadgets fanned out underneath, and Nearby {html.escape(words)}">'
            f'<defs><pattern id="dots" width="18" height="18" patternUnits="userSpaceOnUse"><circle class="m-dot" cx="1" cy="1" r="1"/></pattern></defs>'
            f'<rect width="{W}" height="{H}" fill="url(#dots)"/>'
            + "".join(lines) + "".join(nodes) + '</svg>'
            '<div class="key"><span><i></i>heard by the phone book</span><span class="k-silent"><i></i>not heard</span>'
            '<span class="k-look"><i></i>worth a look</span><span class="k-stop"><i></i>blocked</span></div></div>')


def top(here: str) -> str:
    return (f'<div class="top"><div class="brand"><i></i>Nearby</div><nav>'
            f'<a href="/"{" class=here" if here == "house" else ""}>House</a>'
            f'<a href="/ask"{" class=here" if here == "ask" else ""}>Ask</a>'
            f'<a href="/letter"{" class=here" if here == "letter" else ""}>Letter</a></nav></div>')


SCRIPT = """<script>
function tap(b,mac,action,undo,name){b.disabled=true;
 fetch('/api/fix',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mac:mac,action:action,undo:undo,name:name||null})})
 .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
 .then(function(x){if(x.ok){location.hash=mac.replace(/:/g,'');location.reload()}else{b.disabled=false;(b.closest('.card')||document).querySelector('.err').textContent=x.j.error||'That did not work. Nothing was changed.'}})
 .catch(function(){b.disabled=false})}
function answer(b,id,yes){b.disabled=true;
 fetch('/api/asks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:id,yes:yes})})
 .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
 .then(function(x){if(x.ok){location.reload()}else{b.disabled=false;b.closest('.ask').querySelector('.err').textContent=x.j.error||'That did not work. Nothing was changed.'}})
 .catch(function(){b.disabled=false})}
(function(){var box=document.getElementById('asks');if(!box)return;var seen=box.getAttribute('data-n');
 setInterval(function(){fetch('/api/asks').then(function(r){return r.json()}).then(function(a){if(String(a.length)!==seen)location.reload()}).catch(function(){})},8000)})();
function openCard(){var h=location.hash.slice(1),d=h&&(document.getElementById(h)||document.getElementById('d'+h));if(d&&d.tagName==='DETAILS'){d.open=true;d.scrollIntoView({block:'start'})}}
window.addEventListener('hashchange',openCard);openCard();
</script>"""
FENCEABLE = {"samsung_tv", "google_tv", "roku", "cloud_gadget", "unknown"}
TAP_WORDS = {
    "quiet": ("Quiet it", "Quieted", "Turns on the list of this maker's own ad and tracking names in the phone book. Shows, apps and updates keep working."),
    "block": ("Block it", "Blocked", "Refuses every name it asks for. A gadget that carries its own phone book can still get out; only a box at the door stops that."),
}


class Tap(BaseModel):
    mac: str
    action: str
    undo: bool = False
    name: str | None = None


def names_html(d: dict, on: dict, asked: list) -> str:
    """The sites this gadget asked for in the last day, each with its own stop. One name, one gadget, nothing else touched."""
    if d["kind"] in fixes.NEVER:
        return ""
    stopped = {site: v for site, v in (on.get("names") or {}).items() if counters.is_site(site)}
    counts = {site: n for site, n in asked if counters.is_site(site)}
    rows = []
    for site in list(stopped) + [s for s in counts if s not in stopped]:
        mac, safe = html.escape(d["mac"]), html.escape(site)
        if site in stopped:
            rows.append(f"""<li><span class="site">{safe}</span><span class="tag stop">stopped</span><button onclick="tap(this,'{mac}','name',true,'{safe}')">Undo</button></li>""")
        else:
            rows.append(f"""<li><span class="site">{safe}</span><span class="n">{counts[site]}</span><button onclick="tap(this,'{mac}','name',false,'{safe}')">Stop</button></li>""")
    if not rows:
        return ""
    return (f'<details class="more"{" open" if stopped else ""}><summary>Names it asked for today</summary><ul class="names">{"".join(rows)}</ul>'
            '<p class="why">Stop one name and this gadget can no longer reach it. Everything else keeps working. If something breaks, tap Undo.</p></details>')


def taps_html(d: dict, on: dict, router_maker: str) -> str:
    """The buttons for one device: what is on with its undo, what can be turned on, and the fence steps."""
    rows = []
    mac = html.escape(d["mac"])
    for action in fixes.can(d):
        do, done, why = TAP_WORDS[action]
        if action in on:
            rows.append(f"""<div class="tap"><span class="tag {'stop' if action == 'block' else 'on'}">{done} since {html.escape(on[action]['at'][:10])}</span><button onclick="tap(this,'{mac}','{action}',true)">Undo</button></div>""")
        else:
            rows.append(f"""<div class="tap"><button class="do" onclick="tap(this,'{mac}','{action}',false)">{do}</button><p class="why">{why}</p></div>""")
    if "only" in on:
        allowed = ", ".join(html.escape(x) for x in on["only"].get("sites", []))
        rows.append(f"""<div class="tap"><span class="tag on">Name-fenced since {html.escape(on['only']['at'][:10])}</span><button onclick="tap(this,'{mac}','only',true)">Undo</button><p class="why">It may only look up: {allowed}. Anything new is refused.</p></div>""")
    elif "block" not in on and (sites := fixes.fence_names(d)):
        rows.append(f"""<div class="tap"><button class="do" onclick="tap(this,'{mac}','only',false)">Fence its names</button><p class="why">Lets it look up only the {len(sites)} site{'s' if len(sites) != 1 else ''} it already uses ({html.escape(', '.join(sites))}) and nothing new. If it is ever taken over, it can't call anywhere else.</p></div>""")
    if d["kind"] in FENCEABLE:
        steps = "".join(f"<li>{html.escape(x)}</li>" for x in fixes.fence_steps(router_maker))
        rows.append(f"""<div class="tap"><details class="more steps"><summary>Fence it off from your other devices: three steps, by hand</summary><ol>{steps}</ol></details><p class="why">Keeps it away from your other devices. Needs the router, so Nearby can't tap it for you yet.</p></div>""")
    return ('<div class="taps">' + "".join(rows) + '</div><p class="err"></p>') if rows else ""


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


@app.post("/api/fix")
def fix(t: Tap, request: Request):
    """One tap, or its undo. Only from Nearby's own page: another website open in the house can't press these."""
    origin = request.headers.get("origin")
    if "application/json" not in request.headers.get("content-type", "") or (origin and urlparse(origin).netloc != request.headers.get("host")):
        return JSONResponse({"error": "Taps only work from Nearby's own page."}, status_code=403)
    try:
        return fixes.tap(t.mac, t.action, t.undo, t.name)
    except fixes.Refused as e:
        return JSONResponse({"error": str(e)}, status_code=400)


class Answer(BaseModel):
    id: str
    yes: bool


@app.get("/api/asks")
def asks_waiting():
    return [{"id": a["id"], "text": a["text"], "who": a.get("who", "an assistant")} for a in fixes.asks()]


@app.post("/api/asks")
def answer_ask(a: Answer):
    """The owner's yes or no to something an assistant asked for."""
    try:
        return fixes.decide(a.id, a.yes)
    except fixes.Refused as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/fixes")
def fixes_now():
    return fixes.load()


@app.get("/api/odd")
def odd():
    return detectors.latest()


@app.post("/api/odd")
def odd_now():
    with _lock:
        detectors.run()
    return detectors.latest()


@app.post("/mcp")
async def mcp_door(request: Request):
    """The MCP connector. Shut unless a password is set; every request must carry it."""
    if not connector.token():
        return JSONResponse({"error": "The connector is off. Set NEARBY_MCP_TOKEN (24 characters or more) in .env to turn it on."}, status_code=404)
    who = request.client.host if request.client else "unknown"
    if connector.locked(who):
        return JSONResponse({"error": "Too many wrong passwords. Try again in ten minutes."}, status_code=429)
    if not connector.allowed(request.headers.get("authorization", "")):
        connector.strike(who)
        return JSONResponse({"error": "Wrong or missing password."}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "that was not JSON"}}, status_code=400)
    if isinstance(body, list):
        answers = [a for a in [await run_in_threadpool(connector.handle, m) for m in body[:20]] if a is not None]
        return JSONResponse(answers) if answers else Response(status_code=202)
    answer = await run_in_threadpool(connector.handle, body)
    return JSONResponse(answer) if answer is not None else Response(status_code=202)


@app.get("/mcp")
@app.delete("/mcp")
def mcp_no_stream():
    return Response(status_code=405, headers={"Allow": "POST"})


class Question(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/chat")
def ask_brain(q: Question, request: Request):
    """One question to the sealed brain. Only from Nearby's own page, one at a time."""
    origin = request.headers.get("origin")
    if "application/json" not in request.headers.get("content-type", "") or (origin and urlparse(origin).netloc != request.headers.get("host")):
        return JSONResponse({"error": "Questions only work from Nearby's own page."}, status_code=403)
    try:
        with _chat_lock:
            return chat.answer(q.message, q.history)
    except chat.Refused as e:
        return JSONResponse({"error": str(e)}, status_code=400)


ASK_SCRIPT = """<script>
var talk=document.getElementById('talk'),box=document.getElementById('q'),send=document.getElementById('send'),turns=[];
try{turns=JSON.parse(sessionStorage.getItem('nearby-talk')||'[]')}catch(e){}
function el(tag,cls,text){var n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
function fixButton(s,undo){var b=el('button',undo?'':'do',undo?'Undo':(s.action==='quiet'?'Quiet it':'Block it'));
 b.onclick=function(){b.disabled=true;fetch('/api/fix',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mac:s.mac,action:s.action,undo:undo})})
  .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})}).then(function(x){var row=b.parentNode;
   if(x.ok){row.removeChild(b);var old=row.querySelector('.tag');if(old)row.removeChild(old);if(!undo)row.appendChild(el('span','tag '+(s.action==='block'?'stop':'on'),'done'));row.appendChild(fixButton(s,!undo))}
   else{b.disabled=false;row.appendChild(el('span','err',x.j.error||'That did not work. Nothing was changed.'))}}).catch(function(){b.disabled=false})};return b}
function show(t){var m=el('div','msg '+t.who,t.text);
 if(t.who==='nearby'&&t.source){m.appendChild(el('span','from '+t.source,t.source==='sealed'?'Answered in the sealed room on NEAR AI Cloud. '+(t.detail||''):'Answered here, without the brain.'))}
 if(t.suggestions&&t.suggestions.length){var box=el('div','sugg');t.suggestions.forEach(function(s){var row=el('div','tap');
   row.appendChild(el('span',null,s.action.charAt(0).toUpperCase()+s.action.slice(1)+' the '+s.device+'. '+s.why));
   if(s.action==='fence'||!s.can||!s.mac){row.appendChild(el('span','why',s.action==='fence'?'Fencing is three steps by hand. Open its card on the House page.':'Open its card on the House page.'))}
   else{if(s.on)row.appendChild(el('span','tag '+(s.action==='block'?'stop':'on'),'done'));row.appendChild(fixButton(s,!!s.on))}
   box.appendChild(row)});m.appendChild(box)}
 talk.appendChild(m);m.scrollIntoView({block:'end'});return m}
function keep(){try{sessionStorage.setItem('nearby-talk',JSON.stringify(turns.slice(-12)))}catch(e){}}
function ask(text){text=(text||box.value).trim();if(!text||send.disabled)return;box.value='';send.disabled=true;
 var history=turns.map(function(t){return {who:t.who,text:t.text}}).slice(-6);
 var mine={who:'you',text:text};turns.push(mine);show(mine);var wait=show({who:'nearby wait',text:'Asking the sealed brain…'});
 fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,history:history})})
 .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j}})})
 .then(function(x){talk.removeChild(wait);var t=x.ok?{who:'nearby',text:x.j.reply,source:x.j.source,detail:x.j.detail,suggestions:x.j.suggestions}:{who:'nearby',text:x.j.error||'That did not work.'};
  if(x.ok){turns.push(t);keep()}else{turns.pop()}show(t)})
 .catch(function(){talk.removeChild(wait);turns.pop();show({who:'nearby',text:'Nearby did not answer. Check that it is still running.'})})
 .then(function(){send.disabled=false;box.focus()})}
document.getElementById('askform').addEventListener('submit',function(e){e.preventDefault();ask()});
Array.prototype.forEach.call(document.querySelectorAll('.chips button'),function(b){b.onclick=function(){ask(b.textContent)}});
document.getElementById('fresh').onclick=function(){turns=[];keep();talk.textContent=''};
turns.forEach(show);
</script>"""


COPY_SCRIPT = """<script>
function copy(b,id){var t=document.getElementById(id).textContent;
 function done(){b.textContent='Copied';setTimeout(function(){b.textContent='Copy'},1500)}
 function pick(){var r=document.createRange();r.selectNodeContents(document.getElementById(id));var s=getSelection();s.removeAllRanges();s.addRange(r)}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(done,pick)}else{pick()}}
</script>"""


@app.get("/brains", response_class=HTMLResponse)
def brains_page(request: Request):
    """Plain words on the difference between the brains Nearby can work with, and which are switched on in this house."""
    status = brain.proof_today() or {}
    if not brain.key():
        sealed_now = '<span class="tag">off: no NEAR AI Cloud key set</span>'
    elif status.get("ok"):
        sealed_now = '<span class="tag on">on: seal checked today</span>'
    else:
        sealed_now = '<span class="tag on">on: seal is checked before the next question</span>'
    door_now = '<span class="tag on">on: password set</span>' if connector.token() else '<span class="tag">off: no password set</span>'

    def row(label: str, text: str) -> str:
        return f'<li><span class="k">{label}</span><span>{text}</span></li>'

    address = f"http://{html.escape(request.headers.get('host') or 'this-address:8765')}/mcp"
    command = f'claude mcp add --transport http nearby {address} --header "Authorization: Bearer YOUR-PASSWORD"'
    if connector.token():
        connect = f"""<details class="more" open><summary>Connect your assistant</summary>
<ul class="facts">
{row("Address", f'<code id="addr">{address}</code> <button type="button" onclick="copy(this,&quot;addr&quot;)">Copy</button>')}
{row("Password", "Kept on the Nearby box, in its settings file, on the line <code>NEARBY_MCP_TOKEN</code>. It is not shown here, because anyone on your Wi-Fi can open this page.")}
{row("How it is sent", "As a header on every request: <code>Authorization: Bearer</code> then the password.")}
{row("What it can do", "See who is home and what each gadget asked for. See which fixes are on. Quiet or block a gadget, or undo it. Read the latest letter.")}
{row("In Claude Code", f'<code id="cmd">{html.escape(command)}</code> <button type="button" onclick="copy(this,&quot;cmd&quot;)">Copy</button><br>Swap YOUR-PASSWORD for the real one.')}
</ul></details>"""
    else:
        connect = """<details class="more" open><summary>Turn the door on</summary>
<p>On the Nearby box, open its settings file and put a long password (24 characters or more) on the line <code>NEARBY_MCP_TOKEN=</code>. Restart Nearby. Then come back here for the address.</p></details>"""

    return STYLE + f"""<main>{top('ask')}
<div class="hero"><h1>Choose your brain</h1>
<p class="sub">Nearby gathers the facts about your home and does the work. A brain helps you decide what to do. You can use one, both, or none.</p></div>

<div class="panel"><p class="eyebrow">The private brain</p>
<h2 class="h2">NEAR AI, in a sealed room</h2>{sealed_now}
<ul class="facts">
{row("Who can read your home's facts", "Only the model. Not NEAR, not the company that made the model, not us. Nearby checks the seal every morning before it sends anything.")}
{row("What it is shown", "Counts and names only. Never an address, never a time.")}
{row("Speed", "Slow today. An answer can take a couple of minutes.")}
{row("Cost", "Your own NEAR AI Cloud account. A letter costs a fraction of a cent.")}
{row("Good for", "The nightly letter, and questions you don't mind waiting on.")}
</ul>
<p class="gist">The seal rests on trust in the chip maker, and sealed rooms have been broken before. So we say "sealed, and checked every morning", not "nobody could ever see it".</p></div>

<div class="panel"><p class="eyebrow">Your own assistant</p>
<h2 class="h2">Any AI you already use, through Nearby's password door</h2>{door_now}
<ul class="facts">
{row("Who can read your home's facts", "The company behind that assistant, under its own rules. It is not sealed.")}
{row("What it is shown", "The same counts and names as the private brain. Never an address.")}
{row("Speed", "Fast. It answers like any chat.")}
{row("Cost", "Whatever you already pay for it.")}
{row("Good for", "Back-and-forth, and bigger jobs that need a stronger model.")}
</ul>
<p class="gist">The door is shut until you set a password, and it only opens inside your home network.</p>
{connect}</div>

<div class="panel"><p class="eyebrow">No brain</p>
<h2 class="h2">Nearby by itself</h2>
<ul class="facts">
{row("What still works", "It watches the house, flags what is odd, and does what you tap. Letters come from a plain template.")}
{row("What you lose", "Explanations in plain words, and suggestions.")}
</ul></div>

<div class="wall"><strong>What never changes, whichever brain you pick.</strong> A brain can suggest. It cannot act. Only your tap changes anything in the house, and every tap has an undo.</div>
<p><a href="/ask">Back to Ask</a></p>
</main>""" + COPY_SCRIPT + "</body></html>"


@app.get("/ask", response_class=HTMLResponse)
def ask_page():
    status = brain.proof_today() or {}
    ok, why = brain.within_caps()
    if not brain.key():
        seal = "No NEAR AI Cloud key is set, so answers come from Nearby alone."
    elif not ok:
        seal = "The brain is resting: " + html.escape(why) + ". Answers come from Nearby alone until then."
    elif status.get("ok"):
        seal = "Sealed brain checked today at " + html.escape(str(status.get("checked_at", ""))[11:16]) + " UTC."
    else:
        seal = "The seal is checked before your first question today. That one takes a little longer."
    return STYLE + f"""<main>{top('ask')}
<div class="hero"><h1>Ask about your house</h1>
<p class="sub">The brain sees counts only: who is home and how many names each gadget asked for. It can suggest; only your tap changes anything. <a href="/brains">Which brain is this, and what are my choices?</a></p></div>
<div class="chips"><button type="button">Is anything in my house worth worrying about?</button><button type="button">What is the loudest gadget, and is that normal?</button><button type="button">What should I do first to protect my home?</button></div>
<div class="talk" id="talk" aria-live="polite"></div>
<form class="askbar" id="askform"><label for="q" hidden>Your question</label>
<input id="q" type="text" maxlength="{chat.MAX_QUESTION}" autocomplete="off" placeholder="Ask about your house">
<button class="do" id="send" type="submit">Ask</button></form>
<div class="row"><button type="button" id="fresh">Start over</button></div>
<footer>{seal} Model: {html.escape(brain.MODEL)}. Your words go sealed, end to end, to the attested model; nothing about this talk is kept on Nearby. Leave out addresses; call a gadget by its name.</footer>
</main>""" + ASK_SCRIPT + "</body></html>"


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
        devs = [d for d in find.load().get("devices", {}).values() if d.get("online")]
        active = fixes.load()["active"]

        def button(sg: dict) -> str:
            same = [d for d in devs if d["label"] == sg["device"]]
            if len(same) != 1 or sg["action"] not in fixes.can(same[0]):
                return '<p class="why">Open its card on the house page for the steps.</p>' if sg["action"] == "fence" else ""
            mac = html.escape(same[0]["mac"])
            if sg["action"] in active.get(same[0]["mac"], {}):
                return f"""<span class="tag on">done</span><button onclick="tap(this,'{mac}','{sg['action']}',true)">Undo</button>"""
            return f"""<button class="do" onclick="tap(this,'{mac}','{sg['action']}',false)">{TAP_WORDS[sg['action']][0]}</button>"""

        sugg = "".join(f"<li class='tap'><span><b>{html.escape(s['action'].capitalize())}</b> the {html.escape(s['device'])}. {html.escape(s['why'])}</span>{button(s)}</li>" for s in r["suggestions"])
        sealed = r["source"] == "sealed"
        where = "Written in a sealed room on NEAR AI Cloud." if sealed else "Written here, from a template."
        body = f"""<div class="hero"><p class="eyebrow">{'Weekly letter' if r.get('weekly') else 'Evening letter'} · {html.escape(r['date'])}</p><h1>Your house</h1></div>
<div class="paper"><p>{html.escape(r['letter'])}</p></div>
{('<div class="panel card"><p class="eyebrow">Nearby suggests</p><ul>' + sugg + '</ul><p class="gist">Nothing happens until you tap. Every tap has an undo.</p><p class="err"></p></div>') if sugg else ''}
<div class="panel">
  <div class="seal{'' if sealed else ' local'}"><i>{'✓' if sealed else '·'}</i><span><strong>{where}</strong> {html.escape(str(r.get('detail', '')))}.</span></div>
  <details class="more"><summary>What left the house</summary>
    <p>Counters only: {len((r.get('sent_to_brain') or '').split())} words. No addresses, no times.</p>
    <p>Signed by this house's key <code>{html.escape(r['house'][:16])}…</code></p>
  </details>
</div>"""
    else:
        body = """<div class="hero"><h1>No letter yet.</h1><p class="sub">The first one is written at 8 pm, or now with the button.</p></div>"""
    seal = ("Sealed brain checked today at " + html.escape(str(status.get("checked_at", ""))[11:16]) + " UTC." if status.get("ok")
            else "Sealed brain: " + html.escape(str(status.get("error") or "not checked yet today")) + ".")
    return STYLE + f"""<main>{top('letter')}{body}
<div class="row">
<button onclick="this.disabled=true;this.textContent='Writing…';fetch('/api/letter',{{method:'POST'}}).then(()=>location.reload())">Write tonight's letter now</button>
<button onclick="this.disabled=true;this.textContent='Checking…';fetch('/api/brain/check',{{method:'POST'}}).then(()=>location.reload())">Check the seal</button>
</div>
<footer>{seal} Model: {html.escape(brain.MODEL)}.</footer>
</main>""" + SCRIPT + "</body></html>"


@app.get("/", response_class=HTMLResponse)
def page():
    s = find.load()
    devs = [d for d in s.get("devices", {}).values() if d.get("online")]
    devs.sort(key=lambda d: (ORDER.index(d["kind"]) if d["kind"] in ORDER else 99, ipaddress.ip_address(d["ip"])))
    others = [d for d in devs if d["kind"] != "this_computer"]
    n = len(others)
    lan_ip = s.get("me", "this computer")
    active = fixes.load()["active"]
    noticed_all = detectors.latest()
    noticed_by = defaultdict(list)
    for f in noticed_all["findings"]:
        noticed_by[f["key"]].append(f)
    router_maker = next((d["maker"] for d in devs if d["kind"] == "router"), "")
    if not s.get("last_scan"):
        headline, sub = "Looking around the house.", "The first look takes about ten seconds. Refresh in a moment."
    else:
        headline = f"<b>{n}</b> thing{'s' if n != 1 else ''} in your house {'are' if n != 1 else 'is'} talking to the internet right now."
        sub = "Tap one to see what it is and what you can do."
    waiting = fixes.asks()
    asks_html = "".join(f"""<div class="ask"><p class="eyebrow">{html.escape(a.get('who', 'an assistant')).capitalize()} is asking</p><p class="q">{html.escape(a['text'])}?</p>
<p class="sub">Nothing has changed. It only happens if you say yes, and you can undo it afterwards.</p>
<div class="row"><button class="do" onclick="answer(this,'{html.escape(a['id'])}',true)">Yes, do it</button><button onclick="answer(this,'{html.escape(a['id'])}',false)">No</button></div><p class="err"></p></div>""" for a in waiting)
    n_learning = len(noticed_all["learning"])
    learning = (f"the detectors heard {noticed_all['heard']} devices; {n_learning} are on their first day, so 'new' and 'usual' start tomorrow for them"
                if n_learning else f"the detectors heard {noticed_all['heard']} devices")
    items = []
    for d in devs:
        c = card(d["kind"], lan_ip)
        noticed = noticed_by.get(d["mac"], [])
        on = active.get(d["mac"], {})
        tags = ('<span class="tag look">worth a look</span>' if noticed else "")
        tags += "".join(f'<span class="tag {"stop" if a == "block" else "on"}">{TAP_WORDS[a][1].lower()}</span>' for a in on if a in TAP_WORDS)
        n_stopped = len(on.get("names") or {})
        tags += '<span class="tag on">name-fenced</span>' if "only" in on else ""
        tags += f'<span class="tag stop">{n_stopped} name{"s" if n_stopped != 1 else ""} stopped</span>' if n_stopped else ""
        tags += '<span class="tag">new</span>' if d.get("is_new") else ""
        state = " stopped" if "block" in on else " look" if noticed else ""
        facts = d.get("facts") or {}
        fact_line = ""
        if d["kind"] == "google_tv" and facts.get("usage_stats_on"):
            fact_line = "Usage reports to Google: on."
        if d["kind"] == "samsung_tv" and str(facts.get("smartHubAgreement")).lower() == "true":
            fact_line = "Smart Hub agreement: on. Voice: " + ("on." if str(facts.get("VoiceSupport")).lower() == "true" else "off.")
        maker = "" if d["maker"] in ("unknown maker", "private address") else f"{d['maker']} · "
        items.append(f"""
<details class="dev{state}" id="d{html.escape(d['mac'].replace(':', ''))}">
  <summary><span class="ico"><svg viewBox="0 0 24 24" aria-hidden="true">{ICONS.get(d['kind'], ICONS['unknown'])}</svg></span>
    <span class="who"><span class="name">{html.escape(d['label'] or 'something')}</span><span class="gist">{html.escape(c.get('gist', ''))}</span></span>
    <span class="tags">{tags}</span><span class="chev"></span></summary>
  <div class="card">
    <p class="what">{html.escape(c['what'])}</p>
    {f'<p class="fact">{html.escape(fact_line)}</p>' if fact_line else ''}
    {('<div class="notice"><strong>Nearby noticed</strong><ul>' + ''.join(f"<li>It {html.escape(f['text'])}</li>" for f in noticed) + '</ul></div>') if noticed else ''}
    {taps_html(d, on, router_maker)}
    {names_html(d, on, noticed_all["names"].get(d["mac"], []))}
    <details class="more"><summary>What it sends home, and the switch</summary>
      <h4>What it sends home</h4><ul>{''.join(f'<li>{html.escape(x)}</li>' for x in c['sends_home'])}</ul>
      {('<h4>The switch</h4><ul>' + ''.join(f'<li>{html.escape(x)}</li>' for x in c['switches']) + '</ul>') if c['switches'] else ''}
      <h4>What Nearby can do</h4><p>{html.escape(c['nearby_can'])}</p>
      <p class="feel">{html.escape(c['feeling'])}</p>
    </details>
    <p class="tech">{html.escape(maker)}{html.escape(d['ip'])} · {html.escape(d['mac'])} · first seen {html.escape((d.get('first_seen') or '')[:10])}</p>
  </div>
</details>""")
    return STYLE + f"""<main>{top('house')}
<div id="asks" data-n="{len(waiting)}">{asks_html}</div>
<div class="hero"><h1>{headline}</h1><p class="sub">{html.escape(sub)}</p></div>
{map_svg(devs, active, noticed_by, noticed_all["lookups"]) if s.get("last_scan") else ""}
<div class="list">{''.join(items)}</div>
<div class="row"><button onclick="this.disabled=true;this.textContent='Looking…';fetch('/api/scan',{{method:'POST'}}).then(()=>location.reload())">Look again</button></div>
<div class="wall"><strong>What Nearby can't see from here.</strong> It hears the names each gadget asks for, not what the gadget then says. A gadget that carries its own phone book goes around it. Only something in the path of the traffic sees everything.</div>
<p><a href="/brains">Choose your brain, or connect your own assistant</a></p>
<footer>Nearby {__version__} · last look {html.escape(s.get('last_scan') or 'none yet')} UTC · {html.escape(learning)} · everything here was learned from the network alone. No name was searched online.</footer>
</main>""" + SCRIPT + "</body></html>"
