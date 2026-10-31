"""Waiting with no setup: the requests in your own Semantext inbox (inbox.py), as the cards the page draws.

Someone with no seats file and no inbox folder still has an inbox: agents file requests in it with `semantext ask`, and
you answer them. This reads that file and writes nothing. Each request is one card, named by its number (#12, as you
answer it in chat), from the agent that filed it. A request that is answered or withdrawn is closed.
"""
from __future__ import annotations

from pathlib import Path

from ..inbox import Inbox
from . import problem

CHANGE_WORDS = "It proposes a rule for the environment "


def _text(value) -> str | None:
    """A field as the page shows it: text, or nothing. A hand-edited line may hold a number JSON cannot carry (NaN)."""
    return value if isinstance(value, str) else None


def _choices(r: dict) -> list[dict]:
    """What the page may offer as buttons, each the choice inbox.answer takes. A question with no options is answered in
    your own words, on the home page."""
    if r.get("status") != "open":
        return []
    if r.get("kind") == "command":
        return [{"label": "Done", "choice": "done"}, {"label": "Won't do", "choice": "won't"}]
    if r.get("kind") == "rule":
        return [{"label": "Add it", "choice": "add"}, {"label": "Don't add", "choice": "no"}]
    options = r.get("options")
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        return []
    return [{"label": o, "choice": str(i)} for i, o in enumerate(options, 1)]


def _card(r: dict) -> dict:
    kind = r.get("kind")
    words = ""
    if kind == "rule":   # a proposed rule is decided as a decision is; adding it is the home page's
        words = CHANGE_WORDS + f"{r.get('env')}: {r.get('statement')}"
    answer, closed = r.get("answer"), r.get("closed")
    done = answer or closed
    how = None
    if answer:
        how = "You answered: " + str(answer.get("picked") or answer.get("choice") or "") + (": " + answer["words"] if isinstance(answer.get("words"), str) and answer["words"] else "")
    elif closed:
        how = "Withdrawn" + (": " + closed["how"] if isinstance(closed.get("how"), str) and closed["how"] else "")
    who = str(r.get("from") or "an agent")
    claimed = r.get("from_how") == "claimed"
    if claimed:   # as Inbox.ask promises: a name the agent gave itself is shown as claimed wherever it appears
        who += " (claimed)"
    options = r.get("options")
    options = options if isinstance(options, list) and all(isinstance(o, str) for o in options) else []
    return {"seat": who, "id": f"#{r['id']}", "number": r["id"], "kind": "command" if kind == "command" else "decision",
            "title": _text(r.get("title")), "why": _text(r.get("why")), "question": _text(r.get("question")) or words,
            "options": options, "recommend": r.get("recommend") if type(r.get("recommend")) is int else None,
            "command": _text(r.get("command")), "does": _text(r.get("does")), "undo": _text(r.get("undo")),
            "cwd": _text(r.get("cwd")), "at": _text(r.get("at")),
            "state": "closed" if done else "waiting", "closing": {"at": _text(done.get("at")), "how": how} if done else None,
            "run": None, "output": None, "parked_at": None, "asks": who, "acts": who,
            "asks_basis": "it says it filed this request; the name is its own claim" if claimed else "it filed this request", "acts_basis": "it acts on your answer", "line": None,
            "choices": _choices(r), "own_inbox": True}


def load(home) -> dict:
    """{"off": False, "own_inbox": True, "cards": [...], ...}, in the shape of cards.load."""
    requests = Inbox(Path(home)).requests()
    cards, problems = [], []
    for r in requests.values():
        try:
            cards.append(_card(r))
        except Exception as e:  # noqa: BLE001  a line edited by hand costs that request, said, and never the others
            problems.append(problem(Inbox(Path(home)).path, None, "bad field",
                                    f"request #{r.get('id')} cannot be shown ({type(e).__name__})"))
    seats = sorted({c["seat"] for c in cards})
    states = ("waiting", "parked", "closed", "run")
    return {"off": False, "own_inbox": True, "seats": [{"seat": s} for s in seats], "cards": cards, "changes": [],
            "counts": {"cards": len(cards), "by_state": {s: sum(c["state"] == s for c in cards) for s in states},
                       "by_seat": {}},
            "runs": {"lines": 0, "cards": 0, "unmatched": 0},
            "parking": {"events": 0, "parked": 0, "on_done_cards": 0, "decisions_back": {}}, "problems": problems}
