# Nearby

Nearby finds every gadget in a home, names it, explains in plain words what it sends home, and hands you the fix. It runs on the laptop you already own. Built at NEAR HACKATHON, November 2026, by one person.

## The problem

People who are scared of the gadgets in their house ask four things: *what is this thing, is someone watching, is it listening, will I be stuck with it.* Every answer today is "log into the router, find the setting, read the log, decide." Nobody does that. So the TV fingerprints the screen once a minute, the streaming stick reports usage by default, and the sound machine keeps a line open to a cloud all day, and the owner has no idea.

## What Nearby does

1. **Find.** Sweeps the home network from the laptop and reads who answered. No root needed.
2. **Name.** Works out what each thing is from the network alone: the hardware maker, the name it gave the router, and the questions it answers on its own (a Samsung TV says its model on port 8001, a Cast device says its name on 8008). No device name is ever searched online.
3. **Explain.** A card per kind of device, written by a person: what it is, what it sends home, which switch turns that off, and how it should feel.
4. **Fix.** Nearby becomes the house's phone book (AdGuard Home on the laptop). Point a device at it and every name it asks for shows up, with lists you can turn on to quiet a TV. Router fixes behind one tap, with undo, are the next step (day 7).
5. **The note.** Each evening something changed, and each week no matter what, a short letter about your house. Written from counters, never raw logs, by a brain in a sealed enclave on NEAR AI Cloud. Falls back to local words when the enclave can't be reached, is over its cap, or fails its morning check.

### The wall, said plainly

A laptop only hears its own traffic. Nearby can see *who* is in the house, not *what they say* to the internet, unless a device is pointed at it for names. Some devices (Google TV) skip the router's phone book and ask Google directly, so even that misses them. Only something at the door, where the internet comes in, sees everything. Nearby says this on the page instead of pretending.

## How NEAR fits

**The sealed brain** (`app/nearby/brain.py`, `attest.py`). The evening letter is written by a model NEAR AI Cloud serves inside its own Trusted Execution Environment (Intel TDX plus NVIDIA confidential computing). Only models on a short sealed list are allowed. Before the first call each day Nearby fetches a fresh attestation with its own nonce and runs NEAR's published checks: the Intel quote is verified with `dcap-qvl`, debug mode must be off, the quote must bind our nonce and the model's signing key, the measured config and the event log must match, and GPU evidence is checked with NVIDIA's attestation service. Any failure means the letter is written locally from a template. The proof of each day's check is saved in `data/proofs/`.

**End-to-end encrypted to the enclave.** The counters are encrypted on the laptop to the attested model's key (X25519 + HKDF + XChaCha20-Poly1305, NEAR AI's published scheme), so not even the gateway sees them. The reply comes back encrypted to a one-time key. After each call Nearby fetches the TEE's signature over the exact request and response bytes and checks it against the attested signer.

**Code watches, the model explains.** The model is shown counters only: how many names a device asked for, which, what was new. Never an address, never a time, never a log line; a scrubber refuses to send anything that looks like one. The model may only suggest from a fixed menu (quiet, fence, block, ask, none) and only about devices it was told about; anything else is dropped in code. Caps on tokens and dollars live outside the model.

**The house's own key** (`app/nearby/housekey.py`). On first run Nearby makes an Ed25519 key pair. That is a NEAR key, so the house has a NEAR implicit account from day one with no sign-up. The key signs every letter and every proof. Nothing is written on-chain.

Tracks: `security`, `agents`, `privacy`.

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
- Open `/letter` and tap **Write tonight's letter now**. **See:** a short letter about the house in plain words. With no NEAR AI Cloud key it says it was written locally, and why. Every letter is signed by the house key.
- Put a NEAR AI Cloud key in `.env` as `NEAR_AI_API_KEY`, restart (`docker compose up -d`), open `/letter`, tap **Check the seal**. **See:** `data/proofs/<today>.json` with the checks that passed, and the next letter says "written in a sealed room on NEAR AI Cloud".
- `curl localhost:8765/api/brain` **See:** the model, whether a key is present, today's proof, the caps, and the house's NEAR account id.
- Without Docker, for the page only: `./dev.sh`.

To stop: `docker compose down`. To undo a TV: set its DNS back to automatic. Nothing else was changed.

## What's inside

```
install.sh                one command: .env, AdGuard config, docker compose up
docker-compose.yml        adguard (host network, :53 and :3000) + app (host network, :8765)
app/nearby/find.py        the finder: sweep, neighbour table, identity ports, DHCP names, maker table
app/nearby/cards.py       the plain-word cards, one per kind of device
app/nearby/web.py         the pages (/, /letter) and a small API (/api/devices, /api/scan, /api/brain, /api/letter, /health)
app/nearby/counters.py    AdGuard query log -> per-device counters, eight names each, scrubbed
app/nearby/brain.py       sealed model list, morning attestation, E2EE call, signature check, caps, fixed menu, local fallback
app/nearby/attest.py      NEAR AI Cloud's published attestation checks (dcap-qvl, nonce, signer, config, event log, NVIDIA)
app/nearby/housekey.py    the house's Ed25519 / NEAR key, signs letters and proofs
app/nearby/letters.py     writes the evening and weekly letters with counters, proof and signature
adguard/AdGuardHome.template.yaml   logging on, every list off until tapped
data/                     devices.json, house.key, proofs/, letters/, usage.json (gitignored)
```

## Privacy

- Nothing leaves the laptop on day one. Hardware-maker lookups use a built-in table; the online fallback is off by default and, if turned on, sends only the three-byte maker prefix.
- No model touches raw logs. Summaries are capped in code and checked for addresses before they leave.
- The brain runs only in NEAR AI's attested TEEs, encrypted end to end, verified each morning. "Sealed, checked every morning" is the claim; not "nobody could ever see it". TEEs rest on trust in the chip maker and have been broken before.
- No account. No login on the trusted Wi-Fi. Secrets live in `.env`, never in the repo.

## The 14 days

Day 1 find, name, AdGuard. Day 2-3 finder and cards. Day 4 counters. Day 5 sealed brain. Day 6 the letter. Day 7 router fixes with undo. Day 8 dev router test. Day 9 detectors. Day 10 the screen. Day 11 freeze. Day 12 this README. Day 13 demo. Day 14 submit.

## Licence

MIT.
