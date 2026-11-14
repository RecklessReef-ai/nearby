"""Find every device on the home network without root and without a model.

Plain code only. Steps: work out the LAN, ping every address so the kernel
learns who answered, read the neighbour table, then ask each device the
questions it answers on its own (Samsung TVs on 8001, Cast devices on 8008,
routers on 80), and read its DHCP name from the router.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

DATA_DIR = Path(os.environ.get("NEARBY_DATA", Path(__file__).resolve().parents[2] / "data"))
DEVICES_FILE = DATA_DIR / "devices.json"

# Makers we know by the first three bytes of the hardware address. Small on
# purpose: common home gadgets. Unknown prefixes stay "unknown maker" unless
# OUI_LOOKUP=on, which sends only the prefix to macvendors.com.
OUI = {
    "fc:34:97": "ASUS", "04:d4:c4": "ASUS", "2c:fd:a1": "ASUS", "7c:10:c9": "ASUS",
    "38:86:f7": "Google", "f4:f5:d8": "Google", "54:60:09": "Google", "1c:f2:9a": "Google", "48:d6:d5": "Google",
    "a0:d0:5b": "Samsung", "8c:79:f5": "Samsung", "c4:73:1e": "Samsung", "f8:04:2e": "Samsung", "bc:14:85": "Samsung",
    "c0:cd:d6": "Espressif", "24:6f:28": "Espressif", "a4:cf:12": "Espressif", "3c:71:bf": "Espressif", "84:cc:a8": "Espressif",
    "b8:27:eb": "Raspberry Pi", "dc:a6:32": "Raspberry Pi", "e4:5f:01": "Raspberry Pi",
    "f0:27:2d": "Amazon", "44:65:0d": "Amazon", "fc:65:de": "Amazon", "74:c2:46": "Amazon", "a0:02:dc": "Amazon",
    "d8:31:34": "Roku", "b0:a7:37": "Roku", "cc:6d:a0": "Roku", "08:05:81": "Roku",
    "b8:e9:37": "Sonos", "5c:aa:fd": "Sonos", "94:9f:3e": "Sonos",
    "50:c7:bf": "TP-Link", "60:32:b1": "TP-Link", "98:da:c4": "TP-Link", "b0:be:76": "TP-Link",
    "a0:40:a0": "Netgear", "9c:3d:cf": "Netgear", "c0:ff:d4": "Netgear",
    "18:b4:30": "Nest", "64:16:66": "Nest",
    "00:17:88": "Philips Hue", "ec:b5:fa": "Philips Hue",
    "e0:9f:2a": "Wyze", "2c:aa:8e": "Wyze", "d0:3f:27": "Wyze",
    "34:3e:a4": "Ring", "68:1f:d8": "Ring",
    "48:a6:b8": "Sonos", "70:ee:50": "Netatmo", "d0:73:d5": "LIFX",
    "58:b0:3e": "Nintendo", "98:b6:e9": "Nintendo", "7c:bb:8a": "Nintendo", "04:03:d6": "Nintendo",
    "00:04:4b": "NVIDIA", "48:b0:2d": "NVIDIA", "28:3f:69": "Sony", "fc:0f:e6": "Sony", "0c:fe:45": "Sony",
}
APPLE_PREFIXES = {"3c:22:fb", "a4:83:e7", "f0:18:98", "dc:a9:04", "28:6a:ba", "ac:bc:32", "b8:53:ac", "14:7d:da", "f8:ff:c2", "d0:81:7a"}

PORTS = [22, 53, 80, 443, 554, 1900, 5000, 7676, 8001, 8008, 8009, 8060, 8080, 8443, 9100, 9197, 32400, 62078]


def sh(cmd: list[str], timeout: float = 5) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def lan() -> tuple[str, str, str, str]:
    """Return (interface, my ip, network cidr, gateway ip)."""
    route = sh(["ip", "-4", "route", "show", "default"]).split()
    if "dev" not in route:
        raise RuntimeError("no default route; is this machine on a network?")
    dev = route[route.index("dev") + 1]
    gw = route[route.index("via") + 1] if "via" in route else ""
    addr = sh(["ip", "-4", "-o", "addr", "show", "dev", dev])
    m = re.search(r"inet (\d+\.\d+\.\d+\.\d+/\d+)", addr)
    if not m:
        raise RuntimeError(f"no IPv4 address on {dev}")
    me = m.group(1).split("/")[0]
    net = str(ipaddress.ip_interface(m.group(1)).network)
    return dev, me, net, gw


def ping(ip: str) -> bool:
    return subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True).returncode == 0


def sweep(net: str) -> None:
    hosts = list(ipaddress.ip_network(net).hosts())[:1024]
    with ThreadPoolExecutor(max_workers=96) as ex:
        list(ex.map(lambda h: ping(str(h)), hosts))


def neighbours(dev: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in sh(["ip", "-4", "neigh", "show", "dev", dev]).splitlines():
        parts = line.split()
        if "lladdr" in parts and not any(s in parts for s in ("FAILED", "INCOMPLETE")):
            out[parts[0]] = parts[parts.index("lladdr") + 1].lower()
    return out


def open_ports(ip: str) -> list[int]:
    def probe(p: int) -> int | None:
        try:
            with socket.create_connection((ip, p), timeout=0.6):
                return p
        except OSError:
            return None
    with ThreadPoolExecutor(max_workers=len(PORTS)) as ex:
        return sorted(p for p in ex.map(probe, PORTS) if p)


def http_json(url: str, timeout: float = 1.5) -> dict | None:
    try:
        with urlopen(Request(url, headers={"User-Agent": "nearby"}), timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def http_server_header(ip: str) -> str:
    try:
        with urlopen(Request(f"http://{ip}/", headers={"User-Agent": "nearby"}), timeout=1.5) as r:
            return r.headers.get("Server", "")
    except Exception as e:  # HTTPError still carries headers
        return getattr(getattr(e, "headers", None), "get", lambda *_: "")("Server", "")


def dhcp_name(ip: str) -> str:
    try:
        return socket.gethostbyaddr(ip)[0].split(".")[0]
    except OSError:
        return ""


def maker(mac: str) -> str:
    prefix = mac[:8]
    if prefix in OUI:
        return OUI[prefix]
    if prefix in APPLE_PREFIXES:
        return "Apple"
    # Randomised private addresses (phones) have bit 1 of the first byte set.
    if int(mac[:2], 16) & 0x02:
        return "private address"
    if os.environ.get("OUI_LOOKUP", "off") == "on":
        try:
            with urlopen(f"https://api.macvendors.com/{prefix}", timeout=3) as r:
                return r.read().decode().strip()
        except Exception:
            pass
    return "unknown maker"


# DHCP names some gadgets give themselves, turned into the name on the box.
NAME_HINTS = {"restore2": "Hatch Restore 2", "restore": "Hatch Restore", "wyze": "Wyze camera", "ring": "Ring", "shelly": "Shelly plug",
              "tasmota": "a smart plug", "sonos": "Sonos speaker", "hue": "Philips Hue bridge", "roomba": "Roomba", "nest": "Nest"}


def nice_name(dhcp: str) -> str:
    low = dhcp.lower()
    for key, name in NAME_HINTS.items():
        if low.startswith(key):
            return name
    return dhcp


def identify(ip: str, mac: str, me: str, gw: str) -> dict:
    d = {"ip": ip, "mac": mac, "maker": maker(mac), "kind": "unknown", "label": "", "facts": {}}
    if ip == me:
        d.update(kind="this_computer", label=socket.gethostname())
        return d
    d["ports"] = ports = open_ports(ip)
    d["dhcp_name"] = dhcp_name(ip)
    if 8001 in ports and (j := http_json(f"http://{ip}:8001/api/v2/")):
        dev = j.get("device", {})
        d.update(kind="samsung_tv", label=dev.get("name") or "Samsung TV")
        d["facts"] = {k: dev.get(k) for k in ("modelName", "OS", "VoiceSupport", "smartHubAgreement") if k in dev}
    elif 8008 in ports and (j := http_json(f"http://{ip}:8008/setup/eureka_info?params=name,build_version,uptime,opt_in,device_info")):
        d.update(kind="google_tv", label=j.get("name") or "Google TV")
        d["facts"] = {"cast_build": j.get("build_version"), "uptime_days": round((j.get("uptime") or 0) / 86400, 1),
                      "usage_stats_on": (j.get("opt_in") or {}).get("stats"), "crash_reports_on": (j.get("opt_in") or {}).get("crash")}
    elif 8060 in ports:
        d.update(kind="roku", label="Roku")
    elif 62078 in ports:
        d.update(kind="phone", label=d["dhcp_name"] or "iPhone")
    elif ip == gw:
        d.update(kind="router", label=f"{d['maker']} router" if d["maker"] != "unknown maker" else "the router")
        d["facts"] = {"web_server": http_server_header(ip)}
    elif d["maker"] == "Espressif" and not ports:
        d.update(kind="cloud_gadget", label=nice_name(d["dhcp_name"]) or "a small gadget")
    elif d["maker"] in ("Nintendo", "Sony") or (d["maker"] == "NVIDIA" and d["dhcp_name"].lower().startswith("shield")):
        d.update(kind="game_console", label=d["dhcp_name"] or f"{d['maker']} console")
    elif d["maker"] == "Apple" or d["maker"] == "private address":
        d.update(kind="phone_or_laptop", label=d["dhcp_name"] or "a phone or laptop")
    elif d["dhcp_name"]:
        d["label"] = d["dhcp_name"]
    else:
        d["label"] = f"{d['maker']} device" if d["maker"] != "unknown maker" else "something new"
    return d


def clean(text: str, limit: int = 40) -> str:
    """A name as a device gave it, made safe to show and to hand to a model: letters, digits and a little punctuation, cut short.
    A gadget chooses its own name, so a name must never be able to carry markup or a paragraph of instructions."""
    return " ".join(re.sub(r"[^\w .'()+-]", " ", str(text or "")).split())[:limit].strip()


def by_ip(state: dict) -> dict:
    """Which device holds each address right now. A device that is home wins over one that left and had the address before."""
    out: dict = {}
    for d in sorted(state.get("devices", {}).values(), key=lambda d: bool(d.get("online"))):
        out[d["ip"]] = d
    return out


def save(path, obj) -> None:
    """Write a file whole or not at all, so a reader never sees half of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2))
    os.replace(tmp, path)


def remember(old: dict, new: dict) -> dict:
    """A gadget Nearby has recognised stays recognised. A sleeping TV closes the port it was named by;
    the same hardware address is still the same TV, so its kind, name and facts are kept."""
    if new.get("kind") == "unknown" and old.get("kind") not in (None, "unknown", "this_computer", "router"):
        new.update(kind=old["kind"], label=old.get("label") or new.get("label", ""), facts=old.get("facts") or new.get("facts") or {})
    return new


def load() -> dict:
    try:
        return json.loads(DEVICES_FILE.read_text())
    except (OSError, ValueError):
        return {"devices": {}, "last_scan": None}


def scan() -> dict:
    """One sweep of the house. Merges into data/devices.json keyed by hardware address."""
    dev, me, net, gw = lan()
    sweep(net)
    found = neighbours(dev)
    my_mac = (re.search(r"link/ether (\S+)", sh(["ip", "link", "show", "dev", dev])) or [None, "00:00:00:00:00:00"])[1]
    found[me] = my_mac
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(lambda kv: identify(kv[0], kv[1], me, gw), found.items()))
    state = load()
    for r in results:
        old = state["devices"].get(r["mac"], {})
        remember(old, r)
        r["label"] = clean(r.get("label")) or "something new"
        r["dhcp_name"] = clean(r.get("dhcp_name"))
        r["first_seen"] = old.get("first_seen", now)
        r["last_seen"] = now
        r["is_new"] = not old
        state["devices"][r["mac"]] = r
    for mac, d in state["devices"].items():
        d["online"] = d["last_seen"] == now
    state.update(last_scan=now, lan=net, me=me, gateway=gw)
    save(DEVICES_FILE, state)
    return state


if __name__ == "__main__":
    t = time.time()
    s = scan()
    for d in sorted(s["devices"].values(), key=lambda x: ipaddress.ip_address(x["ip"])):
        print(f"{d['ip']:<16}{d['mac']:<19}{d['maker']:<14}{d['kind']:<16}{d['label']}  {d.get('facts') or ''}")
    print(f"\n{len(s['devices'])} devices, {time.time() - t:.0f}s")
