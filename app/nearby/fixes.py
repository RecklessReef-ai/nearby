"""Fix taps, with undo. Every fix goes through the house's phone book (AdGuard Home),
because that is the one door Nearby holds today. Nothing here logs into the router.

  quiet  turn on the maker-specific list of ad and tracking names for this kind of device
  block  refuse every name this one device asks for
  only   a name fence: the device may look up the sites it already uses and nothing new. For a simple gadget
         that only talks to its maker. Offered when a gadget uses a dozen sites or fewer; the list is fixed at the tap.
  name   refuse one site for this one device, and nothing else (the TV keeps playing, the tracker goes quiet).
         Only a site the device has really asked for can be stopped, so nothing can be blocked on a guess.
  fence  keep a device away from the others: needs the router, so it is a step list, not a tap

What is on is kept in data/fixes.json and rebuilt into the phone book from there,
so undo is exact: remove the entry, rebuild. Nearby only ever touches its own
marked block of rules and the lists it switched on itself.

Said plainly: a block here stops a gadget finding anything by name. A gadget that
carries its own phone book (a Google TV) or dials a number it already knows can
still get out. Only a box at the door stops that.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from urllib.request import Request, urlopen

import re

from . import counters, detectors, find

FIXES = find.DATA_DIR / "fixes.json"
BEGIN = "! Nearby fixes: begin. Managed by Nearby; changes between these lines are overwritten."
END = "! Nearby fixes: end."

# kind of device -> (list address, name shown in AdGuard). Maintained lists of each maker's own tracking names.
QUIET_LISTS = {
    "samsung_tv": ("https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/native.samsung.txt", "Quiet the Samsung TV (hagezi native list)"),
    "roku": ("https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/native.roku.txt", "Quiet a Roku (hagezi native list)"),
}
_SITE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
NEVER = {"this_computer", "router"}
PEOPLE = {"phone", "phone_or_laptop"}  # people browse; a name fence would break their day
FENCE_MAX = 12  # blocking these takes the whole house down
_lock = threading.Lock()


class Refused(Exception):
    """The tap can't be done, with a reason fit to show the owner."""


def _api(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = Request(f"{counters.ADGUARD}/control/{path}", data=data, headers={"Content-Type": "application/json"} if data else {})
    with urlopen(req, timeout=15) as r:
        raw = r.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def load() -> dict:
    try:
        s = json.loads(FIXES.read_text())
    except (OSError, ValueError):
        s = {}
    s.setdefault("active", {})   # {hardware address: {"block": {...}, "quiet": {...}}}
    s.setdefault("lists", [])    # list addresses Nearby switched on itself, so undo never turns off one the owner chose
    s.setdefault("log", [])
    return s


def _save(s: dict) -> None:
    find.DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIXES.write_text(json.dumps(s, indent=2))


def can(dev: dict) -> list[str]:
    """Which taps make sense for this device."""
    if dev.get("kind") in NEVER:
        return []
    return (["quiet"] if dev.get("kind") in QUIET_LISTS else []) + ["block"]


def fence_names(dev: dict) -> list[str]:
    """The sites a name fence would allow for this gadget, or [] when a fence doesn't fit it."""
    if dev.get("kind") in NEVER | PEOPLE:
        return []
    sites = [s for s in counters.ever_asked(dev["mac"]) if _SITE.match(s)]
    return sites if 0 < len(sites) <= FENCE_MAX else []


def block_rules(active: dict, devices: dict) -> list[str]:
    """One phone-book rule per blocked device, by its address today. Pure."""
    rules = []
    for mac in sorted(active):
        ip = (devices.get(mac) or {}).get("ip")
        if not ip or devices[mac].get("kind") in NEVER:
            continue
        if "block" in active[mac]:
            rules.append(f"||*^$client={ip}")
        elif "only" in active[mac]:
            rules.append(f"||*^$client={ip}")
            rules += [f"@@||{site}^$client={ip}" for site in active[mac]["only"].get("sites", []) if _SITE.match(site)]
        rules += [f"||{site}^$client={ip}" for site in sorted(active[mac].get("names") or {}) if _SITE.match(site)]
    return rules


def merge_rules(existing: list[str], ours: list[str]) -> list[str]:
    """The owner's own rules, untouched, then Nearby's marked block. Pure."""
    kept, inside = [], False
    for line in existing:
        if line.strip() == BEGIN:
            inside = True
        elif line.strip() == END:
            inside = False
        elif not inside:
            kept.append(line)
    return kept + ([BEGIN] + ours + [END] if ours else [])


def wanted_lists(active: dict, devices: dict) -> set[str]:
    return {QUIET_LISTS[devices[mac]["kind"]][0] for mac, on in active.items()
            if "quiet" in on and mac in devices and devices[mac].get("kind") in QUIET_LISTS}


def sync(s: dict | None = None) -> dict:
    """Make the phone book match data/fixes.json. Safe to call any time; follows a device whose address changed."""
    s = s or load()
    devices = find.load().get("devices", {})
    status = _api("filtering/status")

    rules = merge_rules(status.get("user_rules") or [], block_rules(s["active"], devices))
    if rules != (status.get("user_rules") or []):
        _api("filtering/set_rules", {"rules": rules})

    want = wanted_lists(s["active"], devices)
    have = {f["url"]: f for f in status.get("filters") or []}
    names = {url: name for url, name in QUIET_LISTS.values()}
    fresh = False
    for url in want:
        if url not in have:
            _api("filtering/add_url", {"name": names[url], "url": url, "whitelist": False})
            s["lists"].append(url)
            fresh = True
        elif not have[url].get("enabled"):
            _api("filtering/set_url", {"url": url, "whitelist": False, "data": {"name": have[url].get("name") or names[url], "url": url, "enabled": True}})
            s["lists"].append(url)
            fresh = True
    for url in [u for u in s["lists"] if u not in want]:
        if url in have and have[url].get("enabled"):
            _api("filtering/set_url", {"url": url, "whitelist": False, "data": {"name": have[url].get("name") or names.get(url, url), "url": url, "enabled": False}})
        s["lists"].remove(url)
    s["lists"] = sorted(set(s["lists"]))
    if fresh:
        try:
            _api("filtering/refresh", {"whitelist": False})  # fetch the list now rather than at the next daily update
        except Exception:
            pass
    return s


def tap(mac: str, action: str, undo: bool = False, name: str | None = None) -> dict:
    """Do one fix, or take it back. Raises Refused with plain words when it can't."""
    with _lock:
        devices = find.load().get("devices", {})
        dev = devices.get(mac)
        if not dev:
            raise Refused("Nearby doesn't know that device any more. Look again, then try.")
        if action == "fence":
            raise Refused("Fencing needs the router. Follow the steps on the card.")
        s = load()
        before = json.dumps(s)
        on = s["active"].setdefault(mac, {})
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        entry = {"at": now, "mac": mac, "label": dev.get("label", ""), "action": action, "undo": undo}
        if action == "name":
            site = (name or "").strip().lower().rstrip(".")
            stopped = on.setdefault("names", {})
            if dev.get("kind") in NEVER or not _SITE.match(site):
                raise Refused(f"Nearby can't stop that name for the {dev.get('label') or 'device'}.")
            asked = {n for n, _ in detectors.latest()["names"].get(mac, [])}
            if not undo and site not in asked:
                raise Refused(f"The {dev.get('label') or 'device'} hasn't asked for {site}, so there is nothing to stop.")
            if undo:
                stopped.pop(site, None)
            else:
                stopped[site] = {"at": now}
            if not stopped:
                del on["names"]
            entry["name"] = site
        elif action == "only":
            if undo:
                on.pop("only", None)
            else:
                sites = fence_names(dev)
                if not sites:
                    raise Refused(f"A name fence doesn't fit the {dev.get('label') or 'device'}: it uses too many sites, or Nearby hasn't heard it yet.")
                on["only"] = {"at": now, "label": dev.get("label", ""), "sites": sites}
        elif action not in can(dev):
            raise Refused(f"Nearby can't {action} the {dev.get('label') or 'device'}.")
        elif undo:
            on.pop(action, None)
        else:
            on[action] = {"at": now, "label": dev.get("label", "")}
        if not on:
            del s["active"][mac]
        s["log"] = (s["log"] + [entry])[-200:]
        try:
            s = sync(s)
        except Exception as e:
            try:
                sync(json.loads(before))  # put the phone book back the way it was
            except Exception:
                pass
            raise Refused(f"The phone book didn't answer, so nothing was changed. ({e})")
        _save(s)
        return {"ok": True, "mac": mac, "active": s["active"].get(mac, {})}


def fence_steps(router_maker: str = "") -> list[str]:
    """No router login yet, so fencing is done by hand. Plain steps, with the ASUS wording when that is the router."""
    asus = "asus" in router_maker.lower()
    return [
        ("Open the ASUS Router app or the router's page. Go to Guest Network and turn one on. Set 'Access Intranet' to Disable."
         if asus else "Open your router's app or page. Turn on the Guest network (some call it IoT). Make sure guests can't reach your other devices."),
        "On the gadget, or in its app, forget the house Wi-Fi and join the guest one.",
        "Come back here and tap Look again. The gadget can still reach the internet, but not your laptop or your phone.",
    ]
