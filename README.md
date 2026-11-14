# Nearby

Nearby is software for making your own home MCP: one small box beside your router that watches the home network, can act on it, and gives the AI you choose a safe door in. Built at NEAR HACKATHON, November 2026, by one person.

Nearby is not the brain. It is where a home keeps its data, its scripts and its rules, so that whichever AI you pick can be useful there. We believe local is where this has to end up: a home's brain should live in the home. Until local models are good enough, any model you choose comes in through one door. The full argument is in [Local comes first](docs/local-first.md).

## Nearby in three parts

1. **A small box beside your router.** A Raspberry Pi in our house. It becomes the house's phone book, so it knows who is home and what each gadget asks for, and it can quiet, stop or block a gadget with one tap and an undo. Bring your own, or get one set up and ready. The code is the same and it is open.
2. **A home MCP.** The box offers a short list of actions behind a password: see the house, see what is on, change one gadget, undo it. That is the door any AI uses. It gets names and counts, never addresses.
3. **A brain you bring.** No model runs on the box and the box calls no model. An assistant you already use connects to the door, with whichever model you like behind it: Claude, OpenAI's, and later a local one. Every one of them is handed the same house rules, and can only ask.

All of it is there to make protecting and running a home easier: see what is in the house, understand it, and act with one tap and an undo.

## The problem

People who are scared of the gadgets in their house ask four things: *what is this thing, is someone watching, is it listening, will I be stuck with it.* Every answer today is "log into the router, find the setting, read the log, decide." Nobody does that. So the TV fingerprints the screen once a minute, the streaming stick reports usage by default, and the sound machine keeps a line open to a cloud all day, and the owner has no idea.

## What Nearby does

1. **Find.** Sweeps the home network from the box and reads who answered. No root needed.
2. **Name.** Works out what each thing is from the network alone: the hardware maker, the name it gave the router, and the questions it answers on its own (a Samsung TV says its model on port 8001, a Cast device says its name on 8008). No device name is ever searched online.
3. **Explain.** A card per kind of device, written by a person: what it is, what it sends home, which switch turns that off, and how it should feel.
4. **Fix.** Nearby becomes the house's phone book (AdGuard Home). Point a device at it, or the whole house from the router, and every name it asks for shows up. Each gadget's card has taps with undo: **Quiet it** turns on the maker's own list of ad and tracking names, **Block it** refuses every name that one gadget asks for. **Fence it** (keep a gadget away from the others) needs the router, so it is three steps by hand.
5. **Notice.** Three detectors run on the phone book's counts after every look: a gadget asks for a name it never asked for before, asks for the same name on a steady beat, or is far busier at night than usual. What they find shows on the gadget's card and goes into the letter as words and counts.
6. **The note.** Each evening something changed, and each week no matter what, a short letter about your house. Written on the box from counters, by plain code and a template, with no model. A brain you connect can read it through the door.

### The wall, said plainly

Beside the router, Nearby hears the names a gadget asks for. It does not see what the gadget then says to the place it reached. A gadget that carries its own phone book, or dials an address it already knows, goes around Nearby altogether. Only something in the path of the traffic sees everything. Nearby says this on the page instead of pretending.

## How a brain fits

**One door for any model.** Nearby is a home MCP server. It does not pick a model for you and it holds no model key. Any model comes in the same way: through an assistant app on a computer in your home that speaks MCP. An earlier version of this code called a cloud model straight from the box. We took that out on the last day so the box does one job: hold the home's data, scripts and rules. That work is in the git history.

**Code watches, the model explains.** A model is shown counters only: how many names a device asked for, which, what was new. Never an address, never a time, never a log line. Everything going out through the door passes a last check that strikes out anything shaped like one. A model can only ask for a fix from a fixed menu, for a gadget Nearby names, and nothing changes until the owner says yes.

Tracks: `security`, `agents`, `privacy`.

## Try it: do X, see Y

Needs Docker with Compose on a Linux computer that is on the home Wi-Fi. (macOS: Docker Desktop 4.34 or later for host networking.)

```
git clone https://github.com/RecklessReef-ai/nearby
cd nearby
./install.sh
```

- Open `http://<this computer's address>:8765`. **See:** "N things in your house are talking to the internet right now." and the list, named.
- Look at the map at the top. **See:** the internet, the router with Nearby beside it, and every device hanging below. Tap one and its card opens.
- Tap a device. **See:** its card: what it is, the buttons, and under "What it sends home" the longer explanation.
- Open the page the first time. **See:** it asks you to choose a password. Open it in a private window. **See:** it asks for that password before it shows anything.
- On a Samsung TV: Settings > General > Network > Network Status > IP Settings > DNS Setting > Enter manually > this computer's address. **See:** within a minute, every name the TV asks for, in the query log, with the client named.
- Tap a gadget, then **Block it**. **See:** the tag "blocked", and in AdGuard's query log every name from that gadget refused. Tap **Undo**. **See:** it is back, and AdGuard's custom rules are as they were.
- Open a device's card, then **Names it asked for today**, and tap **Stop** on one. **See:** that one name refused for that one device, everything else untouched, and an Undo.
- Open `/brains`. **See:** how to connect an assistant, and the house rules every brain is given, each with how code holds it.
- `curl localhost:8765/api/odd` **See:** what the detectors found on the last look, and which devices are on their first day being heard.
- Tests: `docker compose run --rm -e NEARBY_DATA=/tmp/t -v "$PWD/app:/app" app python -m unittest discover tests` **See:** 56 pass. One replays a log where one planted beacon trips exactly one detector. Others prove a block and its undo leave the phone book as it was, that the router and Nearby itself can never be blocked, that an assistant's ask changes nothing until the owner says yes, that an address planted in a letter is struck out at the door, and that no code on the box calls a model.
- Health check: `curl localhost:8765/health` **See:** `{"ok": true, ...}` with the device count.
- Open `/letter` and tap **Write tonight's letter now**. **See:** a short letter about the house in plain words, written on the box by plain code.
- Without Docker, for the page only: `./dev.sh`.

To stop: `docker compose down`. To undo a TV: set its DNS back to automatic. Nothing else was changed.

### What the taps and detectors can't do yet

- A block is a phone-book block. A gadget that carries its own phone book (a Google TV) or dials an address it already knows still gets out. Only a box at the door stops that.
- Nearby does not log into the router. Fencing is by hand.
- The detectors' baseline is one earlier day, short on purpose for the hackathon. On a device's first day nothing is called new or unusual.
- A laptop Nearby can't recognise as a laptop gets flagged for new names, because people browse. Phones and tablets are skipped.

## What's inside

```
install.sh                one command: .env, AdGuard config, docker compose up
docker-compose.yml        adguard (host network, :53; its controls on the box only) + app (host network, :8765, no extra rights, read-only)
app/nearby/find.py        the finder: sweep, neighbour table, identity ports, DHCP names, maker table
app/nearby/cards.py       the plain-word cards, one per kind of device
app/nearby/web.py         the pages (/, /brains, /letter), the MCP door (/mcp) and a small API (/api/devices, /api/scan, /api/fix, /api/fixes, /api/asks, /api/odd, /api/letter, /health)
app/nearby/connector.py   the one door every brain reads through: password, five tools, counts only, a last check that strikes out any address; `fix` asks, it never acts
app/nearby/owner.py       the owner's password on the page: salted hash, sign-in cookie, lockout
app/nearby/store.py       the home's tables in SQLite: network today, ready for power, air, water, food and automations
app/nearby/rules.py       the house rules: the job and six rules handed to every brain, and how code holds each
app/nearby/fixes.py       the fixes: quiet, block, stop one name, fence names, undo; an assistant's ask and the owner's yes
app/nearby/detectors.py   new names, steady beat, odd hours; counts in, plain words out
app/tests/                the detectors on a replayed log, the taps against a pretend phone book
app/nearby/counters.py    AdGuard query log -> per-device counters, eight names each, scrubbed
app/nearby/letters.py     writes the evening and weekly letters on the box from a template, with the counters it was written from
adguard/AdGuardHome.template.yaml   logging on, every list off until tapped
data/                     devices.json, letters/, fixes.json, asks.json, odd.json, nights.json (gitignored)
```

## Privacy

- Nothing leaves the box until you set a password and connect a brain yourself. Hardware-maker lookups use a built-in table; the online fallback is off by default and, if turned on, sends only the three-byte maker prefix.
- No model touches raw logs. What a brain is shown is capped in code and checked for addresses on the way out.
- No model runs on the box, and the box never calls one. What a connected assistant reads leaves the house under that assistant's own rules. That is your call, which is why the door starts shut.
- The page asks for a password. The first person to open a fresh box chooses it. Only a salted hash is kept, the sign-in cookie can't be read by scripts, and ten wrong tries lock that address out for ten minutes.
- The phone book's own controls (AdGuard Home) answer on the box only. Nothing else in the house can reach them.
- The app's container has no extra rights, cannot gain any, and can write only to its data folder.
- Secrets live in `.env`, never in the repo.

## Built in the hackathon window, and with what

Every commit in this repository was made between November 1 and November 14, 2026. There is no earlier code.

- Written with an AI coding agent (Claude Code), directed and tested by one person in one house.
- Runs on: Python 3.12, FastAPI, Uvicorn, Docker Compose.
- Uses, unmodified: AdGuard Home as the phone book, and hagezi's per-maker tracker lists.

## The home's tables

Nearby keeps one small database on the box, `data/nearby.db` (SQLite, nothing to install). After every look at the house, what it knows is written there as rows, so it builds up over days.

- `devices`, `device_days`, `lookups`, `findings`, `changes`: the network, filled today.
- `areas`: network, power, air, water, food. Every device and reading belongs to one.
- `readings`: measurements from sensors. Empty until one is connected.
- `automations`: when this happens, do that. Empty until the first one is approved.

A brain reads them through the door with two tools: `tables` (what each holds) and `rows` (rows from one table). There is no free-form query. Devices are named, never addressed, and days are given, never clock times.

## Let an AI you choose in (MCP)

Nearby can be an MCP server, so an assistant you already use can look at the house and ask for changes. It is off until you set a password: put one of 24 characters or more in `.env` as `NEARBY_MCP_TOKEN` and restart. The address is `http://<nearby's address>:8765/mcp`, and every request must send `Authorization: Bearer <password>`.

- Tools: `house` (who is home, counts, what the detectors noticed), `fixes` (what is on, what is waiting, who changed what), `fix` (ask for one gadget to be quieted or blocked, or for that to be undone), `tables` and `rows` (the home's data tables), `rules` (the house rules every brain is given, and how code holds each), `letter` (the latest letter).
- **An assistant can ask. It cannot act.** `fix` puts an ask at the top of Nearby's page: "Block the Hatch?" with Yes and No. Nothing changes until the owner taps Yes. An ask lapses after 15 minutes.
- The assistant gets names and counts. No addresses, no times. A name a gadget gave itself is cut down to 40 plain characters first, and every answer passes a last check that strikes out anything shaped like an address.
- The router and Nearby itself can never be blocked, at the ask or at the yes.
- It reaches Nearby over the home network only. Nearby does not open a door to the internet.
- What an assistant reads leaves the house under that assistant's own rules. That is your call, which is why the door starts shut.

Do X, see Y, with the password in `$T`:

```
curl -s -X POST http://localhost:8765/mcp -H "Authorization: Bearer $T" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"house","arguments":{}}}'
```

**See:** the house in plain words, with no address in it. Call `fix` the same way, then open the page. **See:** the ask, waiting for you.

Not done yet for the door: one password is shared by every assistant, it travels unscrambled on the home network, and there is no limit on how often an assistant may ask beyond five asks waiting at once.

## Where this is going

Today Nearby sits beside the router and works through the house's phone book. The router is the stronger machine and stays in charge of the traffic.

The intention is to make the router you already have better at protecting the home. Nearby becomes the base layer beside it: it watches, holds the data and the scripts, lets the brain you connect say what it is looking at, and then tells the router what to do. Cut a gadget off. Put the gadgets on their own safe network, away from the laptops and phones. Always with one tap and an undo, and always with the scripts living on the box in your house, not in a cloud.

Two ways to get it, same code either way:

- **Bring your own hardware.** The code is open. Put it on a Raspberry Pi or any small Linux computer at install.
- **Buy it ready.** The same small computer, set up before it arrives.

Not built yet: Nearby signing in to the router, the safe network, and anything that controls a gadget directly.

## Licence

MIT.
