"""The house rules. One copy, kept on the box, handed to every brain.

The job never changes with the brain: protect the home by surfacing what is in it, so the owner can make the choices.

No brain lives on the box. The same words go to any AI that comes through the MCP door, and onto the
Connect page, so the owner reads exactly what the AI was told.

A rule here is a request. A model can ignore a request, so each one is also held in plain code, named beside it.
The words tell a good model how to behave. The code stops a bad one.
"""
from __future__ import annotations

from . import counters

JOB = "Protect this home by surfacing what is in it, so the owner can make the choices."
# (the rule a brain is given, how plain code holds it)
RULES = (
    ("Show what is there. Never guess, never invent a fact, never alarm.",
     "A brain is handed counts and names only, so it has nothing else to repeat."),
    ("Suggest, never act. The owner decides.",
     "A suggestion becomes a button or an ask. Nothing changes without the owner's yes."),
    ("Suggest only from the menu Nearby gives, for gadgets Nearby names.",
     "Anything off the menu, or for a gadget not on the list, is dropped before the owner sees it."),
    ("Addresses and clock times stay at home. Call a gadget by its name.",
     "Everything that goes out through the door is checked, and an address or a time is struck out."),
    ("Never the router, never Nearby itself.",
     "Both are refused in code, at the ask and again at the yes."),
    ("Every change has an undo.",
     "Each fix is recorded with the way to take it back."),
)
MENU = ("quiet", "block", "fence")  # the only actions a brain may suggest
STRUCK = "[kept at home]"


def for_model() -> str:
    """The rules as a brain reads them."""
    return "Your job: " + JOB + "\nThe house rules, which hold whichever AI you are:\n" + "\n".join(f"{i}. {rule}" for i, (rule, _) in enumerate(RULES, 1))


def for_owner() -> str:
    """The rules with how each is held, for the `rules` tool and anyone checking."""
    return "The job: " + JOB + "\n\n" + "\n".join(f"{i}. {rule}\n   Held by code: {held}" for i, (rule, held) in enumerate(RULES, 1))


def keep_home(text: str) -> str:
    """Strike out anything shaped like a network address, a hardware address or a clock time. The last check before words leave the box."""
    return counters._ADDRESS.sub(STRUCK, text)
