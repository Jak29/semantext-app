"""Waiting and the Record with no setup: the requests in your own Semantext inbox (inbox.py), as the page draws them.

Someone with no seats file and no inbox folder still has an inbox: agents file requests in it with `semantext ask`, and
you answer them. This reads that file and writes nothing. Each request is one card, named by its number (#12, as you
answer it in chat), from the agent that filed it. A request that is answered or withdrawn is closed; one you parked waits
apart until you bring it back. Each request you answered is one decision in the Record: withdrawn ones are not, since no
words of yours are in them.

A long inbox stays bounded. The page draws the newest CARD_CAP cards of each kind (waiting, parked, done), and the Record
the newest RECORD_CAP answers; what is not drawn is COUNTED and said ("more"), never dropped: the counts are of the whole
inbox, and as you answer or park the newer cards the older ones are drawn. A field longer than FIELD_CAP characters is
cut where it is drawn, with the number of characters not drawn, and the card says which fields were cut ("cut"): a cut
command is never offered to copy. Nothing in the inbox file is changed.
"""
from __future__ import annotations

from pathlib import Path

from ..inbox import MODEL_LABEL, flags as _flags, Inbox
from . import problem

CHANGE_WORDS = "It proposes a rule for the environment "
VIA = {"page": "you, on the page", "terminal": "you, at a terminal", "chat": "you, in chat"}
CARD_CAP = 100      # cards drawn of each kind: waiting, parked, done
RECORD_CAP = 500    # answers drawn in the Record
FIELD_CAP = 2000    # characters of one field a card draws
OPTION_CAP = 50     # options a card draws (the rest are in the file)
TEXT_FIELDS = ("title", "why", "question", "command", "does", "undo", "cwd", "statement")
STATES = ("waiting", "parked", "closed")


def _cut(value: str, limit: int = FIELD_CAP) -> str:
    """Text as a card draws it: whole, or its first `limit` characters and how many were not drawn."""
    if len(value) <= limit:
        return value
    return value[:limit] + f" … ({len(value) - limit} more characters are in your inbox file, not drawn here)"


def _text(value) -> str | None:
    """A field as the page shows it: text (cut if it is very long), or nothing. A hand-edited line may hold a number
    JSON cannot carry (NaN)."""
    return _cut(value) if isinstance(value, str) else None


def _options(r: dict) -> list[str]:
    """The options a card draws: all of them when they are texts, up to OPTION_CAP, each cut like any field."""
    options = r.get("options")
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        return []
    return [_cut(o, 300) for o in options[:OPTION_CAP]]


def _cut_fields(r: dict) -> list[str]:
    """The names of the fields this card draws cut, so the page can say so and withhold what a cut would make unsafe."""
    out = [k for k in TEXT_FIELDS if isinstance(r.get(k), str) and len(r[k]) > FIELD_CAP]
    options = r.get("options")
    if isinstance(options, list) and (len(options) > OPTION_CAP or any(isinstance(o, str) and len(o) > 300 for o in options)):
        out.append("options")
    answer, closed = r.get("answer"), r.get("closed")
    for name, part in (("answer", answer), ("closing", closed)):
        if isinstance(part, dict) and any(isinstance(part.get(k), str) and len(part[k]) > FIELD_CAP for k in ("words", "how", "picked", "choice")):
            out.append(name)
    return out


def _state(r: dict) -> str:
    """waiting, parked or closed: from the request alone, so every request can be counted without drawing it."""
    if r.get("answer") is not None or r.get("closed") is not None:   # a line with no fields is still an answer
        return "closed"
    return "parked" if r.get("parked") is True else "waiting"


def _who(r: dict) -> str:
    who = str(r.get("from") or "an agent")
    return who + " (claimed)" if r.get("from_how") == "claimed" else who   # as Inbox.ask promises: shown as claimed


def _choices(r: dict) -> list[dict]:
    """What the page may offer as buttons, each the choice inbox.answer takes. A question with no options is answered in
    your own words, on the card."""
    if r.get("status") != "open" or r.get("parked") is True:   # a parked request is brought back first
        return []
    if r.get("kind") == "command":
        return [{"label": "Done", "choice": "done"}, {"label": "Won't do", "choice": "won't"}]
    if r.get("kind") == "rule":
        return [{"label": "Add it", "choice": "add"}, {"label": "Don't add", "choice": "no"}]
    return [{"label": o, "choice": str(i)} for i, o in enumerate(_options(r), 1)]


def _model(r: dict) -> dict:
    m = r.get("model") if isinstance(r.get("model"), dict) else {}
    return {"label": MODEL_LABEL, "name": _text(m.get("name")), "version": _text(m.get("version")),
            "digest": _text(m.get("digest")),
            "problems": [_cut(p, 400) for p in (m.get("problems") or [])[:20] if isinstance(p, str)] if isinstance(m.get("problems"), list) else []}


def _card(r: dict) -> dict:
    kind = r.get("kind")
    words = ""
    if kind == "rule":   # a proposed rule is decided as a decision is; adding it is what the answer does (server: st.adopt)
        words = CHANGE_WORDS + f"{r.get('env')}: {_text(r.get('statement'))}"
    answer, closed = r.get("answer"), r.get("closed")
    done = answer if answer is not None else closed   # a line with no fields is still an answer: never waiting again
    how = None
    if answer is not None:
        how = ("You answered: " if answer.get("via") in VIA else "Answered, and the line does not say it came from you: ") + _cut(str(answer.get("picked") or answer.get("choice") or "")) + (": " + _cut(answer["words"]) if isinstance(answer.get("words"), str) and answer["words"] else "")
    elif closed:
        how = "Withdrawn" + (": " + _cut(closed["how"]) if isinstance(closed.get("how"), str) and closed["how"] else "")
    who = _who(r)
    claimed = r.get("from_how") == "claimed"
    options = _options(r)
    return {"seat": who, "id": f"#{r['id']}", "number": r["id"], "kind": "command" if kind == "command" else "decision",
            "title": _text(r.get("title")), "why": _text(r.get("why")), "question": _text(r.get("question")) or words,
            "options": options, "recommend": r.get("recommend") if type(r.get("recommend")) is int else None,
            "command": _text(r.get("command")), "does": _text(r.get("does")), "undo": _text(r.get("undo")),
            "cwd": _text(r.get("cwd")), "at": _text(r.get("at")), "cut": _cut_fields(r),
            "state": "closed" if done is not None else "parked" if r.get("parked") is True else "waiting", "closing": {"at": _text(done.get("at")), "how": how} if done is not None else None,
            "run": None, "output": None, "parked_at": _text(r.get("parked_at")), "asks": who, "acts": who,
            "asks_basis": "it says it filed this request; the name is its own claim" if claimed else "it filed this request", "acts_basis": "it acts on your answer", "line": None,
            "choices": _choices(r), "own_inbox": True, "rule": kind == "rule",
            # a model's proposal: the label is the kernel's word, its fields the person's settings (model.py)
            "label": MODEL_LABEL if kind == "model" else None, "model": _model(r) if kind == "model" else None,
            # worked out from the command itself, so a line edited by hand cannot drop the warning
            "flags": _flags(r["command"]) if kind == "command" and isinstance(r.get("command"), str) else []}


def _decision(r: dict, path) -> dict:
    a = r["answer"]
    picked, words = _text(a.get("picked")), _text(a.get("words"))
    at = _text(a.get("at")) or ""
    options = r.get("options") if isinstance(r.get("options"), list) else []
    offered = [_text(r.get("question")) or "", *(f"{i}. {_cut(o, 300)}" for i, o in enumerate(options[:OPTION_CAP], 1) if isinstance(o, str))]
    who = str(r.get("from") or "an agent")
    return {"id": f"#{r['id']}", "line": None, "date": at[:10] or None, "time": at[11:19] or None, "to": who,
            "subject": _text(r.get("title")), "words": words or picked or _text(a.get("choice")),
            "offer": "\n".join(x for x in offered if x) or None, "reading": f"You picked: {picked}" if picked and words else None,
            "source": f"{path}, request #{r['id']}", "pin": None, "stored_status": "answered", "computed_status": "answered",
            "supersedes": [], "superseded_by": [], "notes": [], "mentions": {}, "added_by": VIA.get(a.get("via"), "the line does not say it came from you"),
            "added": at or None,
            # your answer to a model's proposal: the Record keeps that it was a MODEL proposal you answered
            "label": MODEL_LABEL if r.get("kind") == "model" else None, "model": _model(r) if r.get("kind") == "model" else None}


def decisions(home, cap: int = RECORD_CAP, counted: dict | None = None) -> tuple[list[dict], str, list[dict]]:
    """(each request you answered as the Record's entry, oldest first; the file; what could not be shown). Only the
    newest `cap` are drawn; the rest are said as one line among what could not be shown, with their number, and the
    whole number answered goes into `counted["answered"]` when a dict is given."""
    inbox = Inbox(Path(home))
    answered = [r for r in inbox.requests().values() if r.get("status") == "answered"]
    total = len(answered)
    if counted is not None:
        counted["answered"] = total
    out, problems = [], []
    if total > cap:
        answered = sorted(answered, key=lambda r: r["id"])[-cap:]
        problems.append(problem(inbox.path, None, "more answers",
                                f"{total} answers are in your inbox; the newest {cap} are drawn here, and the other "
                                f"{total - cap} are in this file"))
    for r in answered:
        try:
            out.append(_decision(r, inbox.path))
        except Exception as e:  # noqa: BLE001  a line edited by hand costs that decision, said, and never the others
            problems.append(problem(inbox.path, None, "bad field", f"request #{r.get('id')} cannot be shown ({type(e).__name__})"))
    return out, str(inbox.path), problems


def load(home, cap: int = CARD_CAP) -> dict:
    """{"off": False, "own_inbox": True, "cards": [...], ...}, in the shape of cards.load.

    The cards are the newest `cap` of each kind (waiting, parked, done). "counts" are of the whole inbox, "more" says how
    many of each kind are not among the cards (zero when all are), and "cap" is the cap used; "seats" are the agents of
    the cards drawn, and "asked_by" every agent that filed a request."""
    inbox = Inbox(Path(home))
    requests = inbox.requests()
    kinds: dict[str, list] = {s: [] for s in STATES}
    asked_by = set()
    for r in requests.values():
        kinds[_state(r)].append(r)
        asked_by.add(_who(r))
    chosen, more = [], {}
    for s in STATES:
        newest = sorted(kinds[s], key=lambda r: r["id"], reverse=True)[:cap]
        chosen += newest
        more[s] = len(kinds[s]) - len(newest)
    chosen.sort(key=lambda r: r["id"])
    cards, problems = [], []
    for r in chosen:
        try:
            card = _card(r)
            if card["state"] == "waiting":   # the same question, answered before: shown beside it, never used for it
                e = inbox.earlier(r, requests)
                a = e["answer"] if e else None
                card["answered_before"] = {"choice": _text(a.get("choice")) or "", "words": _text(a.get("words")) or "", "picked": _text(a.get("picked")) or ""} if a else None
            cards.append(card)
        except Exception as e:  # noqa: BLE001  a line edited by hand costs that request, said, and never the others
            problems.append(problem(Inbox(Path(home)).path, None, "bad field",
                                    f"request #{r.get('id')} cannot be shown ({type(e).__name__})"))
    seats = sorted({c["seat"] for c in cards})
    states = ("waiting", "parked", "closed", "run")
    return {"off": False, "own_inbox": True, "seats": [{"seat": s} for s in seats], "asked_by": sorted(asked_by),
            "cards": cards, "changes": [], "more": more, "cap": cap,
            "counts": {"cards": len(requests), "by_state": {s: len(kinds.get(s, ())) for s in states},
                       "by_seat": {}},
            "runs": {"lines": 0, "cards": 0, "unmatched": 0},
            "parking": {"events": 0, "parked": 0, "on_done_cards": 0, "decisions_back": {}}, "problems": problems}
