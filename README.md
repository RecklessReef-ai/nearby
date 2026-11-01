# Nearby

Nearby finds every gadget in a home, names it, explains in plain words what it sends home, and hands you the fix. It runs on the laptop you already own. Built at NEAR HACKATHON, November 2026, by one person.

## The problem

People who are scared of the gadgets in their house ask four things: *what is this thing, is someone watching, is it listening, will I be stuck with it.* Every answer today is "log into the router, find the setting, read the log, decide." Nobody does that. So the TV fingerprints the screen once a minute, the streaming stick reports usage by default, and the sound machine keeps a line open to a cloud all day, and the owner has no idea.

## What Nearby does

1. **Find.** Sweeps the home network from the laptop and reads who answered. No root needed.
2. **Name.** Works out what each thing is from the network alone: the hardware maker, the name it gave the router, and the questions it answers on its own (a Samsung TV says its model on port 8001, a Cast device says its name on 8008). No device name is ever searched online.
3. **Explain.** A card per kind of device, written by a person: what it is, what it sends home, which switch turns that off, and how it should feel.
4. **Fix.** Nearby becomes the house's phone book (AdGuard Home on the laptop). Point a device at it and every name it asks for shows up, with lists you can turn on to quiet a TV. Router fixes behind one tap, with undo, are the next step (day 7).
5. **The note.** Each evening something changed, and each week no matter what, a short letter about your house. Written from counters, never raw logs, by a brain in a sealed enclave on NEAR AI Cloud (day 5). Falls back to local words when the enclave can't be reached.

### The wall, said plainly

A laptop only hears its own traffic. Nearby can see *who* is in the house, not *what they say* to the internet, unless a device is pointed at it for names. Some devices (Google TV) skip the router's phone book and ask Google directly, so even that misses them. Only something at the door, where the internet comes in, sees everything. Nearby says this on the page instead of pretending.

## How NEAR fits

- **NEAR AI Cloud, Private TEE tier** writes the notes (day 5). The laptop talks straight to the attested enclave; the model maker and the cloud host can't read house data; attestation is checked before the first call each day; fail closed to local words.
- **Code watches, the model explains.** Every detector runs in plain code on counters. The model receives a capped summary, never a log line, and only suggests from a fixed menu.
- Tracks: `security`, `agents`, `privacy`.

## Try it: do X, see Y

Needs Docker with Compose on a Linux computer that is on the home Wi-Fi. (macOS: Docker Desktop 4.34 or later for host networking.)

```
git clone https://github.com/RecklessReef-ai/nearby
cd nearby
./install.sh
```

- Open `http://<this computer's address>:8765`. **See:** "N things in your house are talking to the internet right now." and the list, named.
- Tap a device. **See:** its card: what it is, what it sends home, the switch, what Nearby can do.
- Open `http://<this computer's address>:3000`. **See:** AdGuard Home's query log, empty until a device is pointed at it.
- On a Samsung TV: Settings > General > Network > Network Status > IP Settings > DNS Setting > Enter manually > this computer's address. **See:** within a minute, every name the TV asks for, in the query log, with the client named.
- Health check: `curl localhost:8765/health` **See:** `{"ok": true, ...}` with the device count.
- Without Docker, for the page only: `./dev.sh`.

To stop: `docker compose down`. To undo a TV: set its DNS back to automatic. Nothing else was changed.

## What's inside

```
install.sh                one command: .env, AdGuard config, docker compose up
docker-compose.yml        adguard (host network, :53 and :3000) + app (host network, :8765)
app/nearby/find.py        the finder: sweep, neighbour table, identity ports, DHCP names, maker table
app/nearby/cards.py       the plain-word cards, one per kind of device
app/nearby/web.py         the one page and a small API (/api/devices, /api/scan, /health)
adguard/AdGuardHome.template.yaml   logging on, every list off until tapped
data/devices.json         what was found (gitignored)
```

## Privacy

- Nothing leaves the laptop on day one. Hardware-maker lookups use a built-in table; the online fallback is off by default and, if turned on, sends only the three-byte maker prefix.
- No model touches raw logs. Summaries are capped in code.
- No account. No login on the trusted Wi-Fi. Secrets live in `.env`, never in the repo.

## The 14 days

Day 1 find, name, AdGuard. Day 2-3 finder and cards. Day 4 counters. Day 5 sealed brain. Day 6 the letter. Day 7 router fixes with undo. Day 8 dev router test. Day 9 detectors. Day 10 the screen. Day 11 freeze. Day 12 this README. Day 13 demo. Day 14 submit.

## Licence

MIT.
