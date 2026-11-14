"""Plain-word cards for each kind of device. Written by a person, not a model.

Facts come from Nearby's own research notes (R7) and the maker's own pages.
No model ever searches a device name. The card says what the thing is, what
it sends home, which switch turns that off, and what Nearby can do.
"""

CARDS: dict[str, dict] = {
    "samsung_tv": {
        "gist": "Fingerprints the screen about once a minute.",
        "what": "A Samsung smart TV. It runs its own apps and its own software, Tizen.",
        "sends_home": [
            "A fingerprint of what is on the screen, about once a minute, to Samsung. This is on even when the TV is only used as a monitor for a game console or a laptop.",
            "What you watch and which apps you open, for ads and recommendations.",
            "Your voice, when the voice feature is on and you press the microphone button.",
        ],
        "switches": [
            "Settings > General > Terms & Privacy > Viewing Information Services: off. This stops the screen fingerprint.",
            "Settings > General > Terms & Privacy > Interest-Based Advertising: off.",
            "Settings > General > Terms & Privacy > Voice Recognition Services: off, if you never talk to the TV.",
        ],
        "nearby_can": "Answer the TV's name lookups, so you can see every name it asks for and quiet the ones you don't want. On the TV: Settings > General > Network > Network Status > IP Settings > DNS Setting > Enter manually > {lan_ip}.",
        "feeling": "This is the loudest thing in most houses. It is not a hack. It is how the TV was sold.",
    },
    "google_tv": {
        "gist": "Reports usage to Google by default.",
        "what": "A Google TV streaming device. It plays apps and lets phones cast to it.",
        "sends_home": [
            "Usage statistics and crash reports to Google: when casting starts, which apps, errors. On by default, and on for this one.",
            "What you watch inside each app goes to that app's maker (Netflix, YouTube, and so on).",
        ],
        "switches": [
            "Google Home app > this device > Settings > 'Send device usage data and crash reports': off.",
            "On the TV: Settings > Privacy > Usage & diagnostics: off.",
        ],
        "nearby_can": "Answer its name lookups, so you can see what it asks for and stop single names. Some of these devices also ask Google's own phone book directly, so Nearby may not hear everything it does.",
        "feeling": "Normal for a Google device. The two switches above cut most of it.",
    },
    "cloud_gadget": {
        "gist": "Keeps a line open to its maker all day.",
        "what": "A small gadget with a Wi-Fi chip inside (a sound machine, a plug, a light, a sensor). Its app talks to it through the maker's cloud, not directly.",
        "sends_home": [
            "A connection to the maker's cloud that stays open all day, so the app can reach it from anywhere.",
            "Its state and your commands, through that cloud.",
        ],
        "switches": [
            "Nothing to switch off on the gadget itself. It has no screen and no settings page.",
        ],
        "nearby_can": "Fence it: put it in a group that can reach the internet but none of your other devices. If it is ever taken over, it can't reach your laptop or your phone. This needs the router, so for now it is three steps by hand, below.",
        "feeling": "Harmless on a good day. Fencing is what you do for the bad day.",
    },
    "router": {
        "gist": "The front door of the house.",
        "what": "The front door of the house. Every device's traffic goes through it.",
        "sends_home": [
            "ASUS routers: if AiProtection, Traffic Analyzer, Adaptive QoS or Web History are on, traffic data goes to Trend Micro. Their notice says this can include web addresses and files.",
            "Firmware update checks and the time, daily.",
        ],
        "switches": [
            "ASUS: AiProtection > turn off what you don't use. Adaptive QoS > Web History: off.",
        ],
        "nearby_can": "Nearby's taps (quiet, block) go through the phone book, not the router, so nothing here logs into it. Fencing a gadget onto the guest network is still done by hand; the steps are on each gadget's card.",
        "feeling": "Keep its software up to date. That matters more than any setting.",
    },
    "game_console": {
        "gist": "Updates and online play. Normal.",
        "what": "A game console.",
        "sends_home": ["Game updates, online play, friends and the store, to its maker. Normal."],
        "switches": ["Parental controls live in the maker's phone app, if there are kids."],
        "nearby_can": "Keep it on the people side of the house, with phones and laptops.",
        "feeling": "Nothing to worry about here.",
    },
    "phone": {
        "gist": "A phone. Fine.",
        "what": "A phone. Probably yours.",
        "sends_home": ["Whatever its apps send. That is a different fight, and not one for this screen."],
        "switches": [],
        "nearby_can": "Nothing needed. It uses a private hardware address, which is good.",
        "feeling": "Fine.",
    },
    "phone_or_laptop": {
        "gist": "A phone, tablet or laptop. Fine.",
        "what": "A phone, tablet or laptop. It hides its real hardware address, which is what phones do now.",
        "sends_home": ["Whatever its apps send."],
        "switches": [],
        "nearby_can": "Nothing needed.",
        "feeling": "Fine.",
    },
    "this_computer": {
        "gist": "This is where Nearby lives.",
        "what": "The Nearby box. This page is running on it.",
        "sends_home": ["Nearby sends nothing about your house anywhere unless you connect an assistant of your own."],
        "switches": [],
        "nearby_can": "Hear the names each gadget asks for, and refuse the ones you stop. It does not see what a gadget then says.",
        "feeling": "Fine.",
    },
    "roku": {
        "gist": "Sends viewing data to Roku for ads.",
        "what": "A Roku streaming device.",
        "sends_home": ["Viewing data and a screen fingerprint on Roku TVs, to Roku, for ads."],
        "switches": ["Settings > Privacy > Smart TV experience > Use info from TV inputs: off. Settings > Privacy > Advertising > Limit ad tracking: on."],
        "nearby_can": "Answer its name lookups so you can see and quiet them.",
        "feeling": "Like the Samsung TV: loud by design, quieter with two switches.",
    },
    "unknown": {
        "gist": "Not recognised yet.",
        "what": "Something new. Nearby could not tell what it is from the network alone yet.",
        "sends_home": ["Unknown until it answers its name lookups here."],
        "switches": [],
        "nearby_can": "Watch it. If you know what it is, tell Nearby and it will remember.",
        "feeling": "A new thing you don't recognise is the one worth a look. Most turn out to be a phone or a plug.",
    },
}


def card(kind: str, lan_ip: str = "this computer's address") -> dict:
    c = dict(CARDS.get(kind, CARDS["unknown"]))
    c["nearby_can"] = c["nearby_can"].replace("{lan_ip}", lan_ip)
    return c
