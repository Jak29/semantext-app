"""The hook: `semantext hook` hands your card to your AI with every prompt.

Claude Code runs it as a UserPromptSubmit command hook: the event arrives as JSON on stdin, and what this prints on
stdout is added to the prompt's context. Three limits, each learned the hard way:

- It never blocks a prompt. Any failure prints one line saying the card is unavailable, and exits 0 (an exit code
  of 2 would block the prompt).
- It stays under LIMIT_BYTES. Larger hook output may be saved to a file with only a short preview shown, so most of
  the card would never reach the AI, silently.
- A rule is never cut in the middle: half a rule can lose the very limit it states. Whole rules are kept, and one
  line says how many were left out.
"""
from __future__ import annotations

import json
import re
import sys

from . import jsonread
from .agents import Agents, clean, key_shaped
from .feed import Feed, stamp
from .heard import Heard
from .inbox import (Inbox, card_notes, chat_notes, describe_answer, mentioned, mine, not_taken_note,
                    typed_answer)
from .sender import NOTICE, RELAY, USER, relay_from, whose
from .store import Refused, Store

LIMIT_BYTES = 9_500


def fit(card: str, limit: int = LIMIT_BYTES) -> str:
    """The card whole if it fits; otherwise whole lines up to the limit, then a line saying how many rules were
    left out."""
    if len(card.encode("utf-8")) <= limit:
        return card
    lines = card.splitlines()
    total = sum(1 for line in lines if line.startswith("- "))
    kept, size, reserve = [], 0, 200
    for line in lines:
        n = len(line.encode("utf-8")) + 1
        if size + n > limit - reserve:
            break
        kept.append(line)
        size += n
    shown = sum(1 for line in kept if line.startswith("- "))
    kept.append(f"({total - shown} more rules not shown: the card's size limit. "
                f"Run `semantext card` to see them all.)")
    return "\n".join(kept)


WORDS = {USER: "own", RELAY: "agent", NOTICE: "tool"}


def compose(store: Store, name: str, form: str, layer, notes: str = "") -> tuple[str, dict]:
    """The text for one prompt, and what went into it: the inbox's notes first (their room is reserved, so the size
    rule can never drop an answer), then the card, fitted. The report is the card's plan cut to the rules that were
    actually sent, with how many the size limit left out."""
    card, plan = store.served(name, form, agent=layer)   # a broken rule file still leaves the base rules
    budget = LIMIT_BYTES - 1   # one byte for the final newline
    body = fit(card, budget - len(notes.encode("utf-8")) - 2) if notes else fit(card, budget)
    text = notes + "\n\n" + body if notes else body
    return text, {"environment": name, "form": plan["form"], "problem": bool(plan.get("problem")),
                  "layers": sent_layers(plan["layers"], body), "bytes": len(text.encode("utf-8")),
                  "left_out": rule_lines(card) - rule_lines(body)}


def rule_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("- "))


def sent_layers(layers: list, body: str) -> list[dict]:
    """Each layer of a card's plan, with the ids of its rules that are in the text as sent: the size limit can leave
    some out."""
    sent = {line[2:].split(": ", 1)[0] for line in body.splitlines() if line.startswith("- ")}
    return [{"layer": x["layer"], "name": str(x["name"]),
             "ids": [str(e.get("id", "?")) for e in x["rules"] if str(e.get("id", "?")) in sent]} for x in layers]


def record(who, words: str, basis: str, served: dict, answers: list, waiting: list, sender: str = "",
           noticed: list | None = None) -> dict:
    """The feed's line for one delivery (see feed.py): what Semantext decided, never what was said. `sender` is the
    name another agent's message gives itself in its opening tag, if any; `noticed`, what its quick reading noticed."""
    return {"at": stamp(), "agent": who.name, "how": who.how, "tool": who.tool or "", "words": words, "from": sender,
            "basis": basis, **served, "answers": answers, "waiting": waiting, "noticed": noticed or []}


def noticed(store: Store, name: str, prompt, answer: bool = False) -> list[str]:
    """What Semantext's own quick reading (store.read, saving nothing) notices in the user's own words, by kind only:
    a question, a maybe, an act that needs their word... A message whose one answer was RECORDED is an answer, and only
    that; one shaped like an answer but not recorded (no such request, no record of who typed it) is read as words."""
    if answer:
        return ["answer"]
    if not isinstance(prompt, str) or not prompt.strip():
        return []
    try:
        r = store.read(name, prompt, dry=True, entries=[])   # the kinds only: no rule file read a second time
    except Exception:  # noqa: BLE001  a record of the work, never a reason for a prompt to fail
        return []
    return [x["kind"] for x in r["readings"]] + (["needs-word"] if r["decisions"] else [])


def _form_fits(r: dict, choice: str) -> str:
    """Why a typed answer's form does not fit its request, or "" when it does: words alone ("#12: ...") answer only a
    question with no options; a command takes done or won't, and a proposed rule add or no."""
    if choice:
        return ""
    if r.get("kind") == "decision" and r.get("options"):
        return f"#{r['id']} has options: answer with its number, such as #{r['id']} 1, and any words after a comma"
    if r.get("kind") == "command":
        return f"#{r['id']} is a command: answer #{r['id']} done or #{r['id']} won't"
    if r.get("kind") == "rule":
        return f"#{r['id']} is a proposed rule: answer #{r['id']} add or #{r['id']} no"
    return ""


def _kept_or_not(inbox: Inbox, rid: int, choice: str, words: str, e: Exception) -> dict:
    """After an error, the inbox itself says whether this answer was kept: one already written is never reported as not
    recorded."""
    try:
        r = inbox.get(rid)
        a = r.get("answer") or {}
        if (r["status"] == "answered" and a.get("via") == "chat" and a.get("choice") == str(choice).strip()
                and a.get("words") == str(words).strip()):
            return {"id": rid, "ok": True, "said": describe_answer(r)}
    except Exception:  # noqa: BLE001  the inbox cannot be read either: it was not recorded, as far as can be told
        pass
    return {"id": rid, "ok": False, "why": f"it could not be recorded just now ({type(e).__name__})"}


def take_answers(store: Store, inbox: Inbox, typed: list) -> list[dict]:
    """Record the answer the user typed in chat (inbox.typed_answer), as the page and the terminal record theirs:
    checked, answered, and a proposed rule they said add to is added. Called only for a message that both its text and
    the tool's own record call the user's. One result per answer: {"id", "ok", and "said" or "why"}."""
    out = []
    for rid, choice, words in typed:
        try:
            r = inbox.get(rid)
            misfit = _form_fits(r, choice)
            if misfit:
                raise Refused(misfit)
            store.check_adoptable(r, choice)
            r = inbox.answer(rid, choice, words, via="chat")
        except Refused as e:        # refused before anything was written
            out.append({"id": rid, "ok": False, "why": str(e)})
            continue
        except Exception as e:  # noqa: BLE001  perhaps after the answer was written: the inbox says which
            out.append(_kept_or_not(inbox, rid, choice, words, e))
            continue
        try:
            added = store.adopt(r)
        except Exception as e:  # noqa: BLE001  the answer stands; only the rule did not go in
            out.append({"id": rid, "ok": True, "said": describe_answer(r) + f" (recorded; the rule could not be added: {e})"})
            continue
        out.append({"id": rid, "ok": True, "said": describe_answer(r) + (f" (the rule is added as {added})" if added else "")})
    return out


def sender_name(prompt) -> str:
    """Who relayed this prompt, as its opening tag names them: cleaned like any agent's name, and nothing at all when
    the name looks like it holds a key."""
    raw = relay_from(prompt)
    return "" if key_shaped(raw) else clean(raw)


SESSION_RE = re.compile(r"[A-Za-z0-9_-]{1,64}", re.ASCII)   # the session names the work kernel's reader accepts


def keep_turn(root, event: dict, prompt, transcript, own: bool, basis: str) -> str | None:
    """The session's newest turn, for the work kernel (PM-DESIGN, follow-ups to A1, (a)): paths.turns_dir/<session>.json
    holds whose words they were, on what basis, when, and where the turn's own record lies in the transcript (path,
    byte offset, length). The words themselves are not copied: they stay in the transcript, and the kernel reads them
    from the span. One small file per session, replaced each turn. Never raises, never blocks the prompt.

    Returns None, or the fault in one line when the record could not be kept, for the hook to say: without it the
    person's acts in this session read "unverified". On Windows a Semantext home whose path is long can pass the
    260-character limit for the record's file (and the temporary file it is written through), and the write fails."""
    try:
        session = event.get("session_id")
        if not isinstance(session, str) or not SESSION_RE.fullmatch(session) or not isinstance(transcript, str):
            return
        from . import provenance
        from .paths import turns_dir
        from .store import write_atomic
        span = provenance.span_of(transcript, prompt)
        rec = {"origin": "own" if own else "relayed", "basis": basis if span and basis == "transcript" else "none",
               "turn": (span or {}).get("turn") or f"{session}@{(span or {}).get('offset')}",
               "at": stamp_utc()}
        if span:
            rec.update(transcript=transcript, offset=span["offset"], length=span["length"])
        folder = turns_dir(root)
        folder.mkdir(parents=True, exist_ok=True)
        write_atomic(folder / f"{session}.json", json.dumps(rec))
    except Exception as e:  # noqa: BLE001  the turn record is for the work kernel; the card goes out whatever happens
        why = getattr(e, "strerror", None) or type(e).__name__
        return (f"this turn's record was not kept ({why}), so an act typed in this session reads unverified; on "
                f"Windows a long Semantext home path can pass the 260-character limit")
    return None


def stamp_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(event_text: str, store: Store | None = None) -> str:
    """The text to add to the prompt: the inbox's answers and waiting requests first, then the card. If hearing
    prompts is switched on, the prompt is also kept, on this machine; if the feed is on (the default), one line says
    what was sent, never what was said."""
    try:
        text = (event_text or "").lstrip("﻿")   # a PowerShell pipe adds a byte-order mark
        event = jsonread.loads(text) if text.strip() else {}
    except (ValueError, RecursionError):
        event = {}          # not an event we understand: the card still goes out
    store = store or Store.open()
    state = store.state()
    name = state["active"]
    event = event if isinstance(event, dict) else {}
    prompt = event.get("prompt")
    agents = Agents(store.root)
    who = agents.identify(event=event)         # the same name `semantext ask` works out in this agent's shell
    transcript = event.get("transcript_path") if isinstance(event.get("transcript_path"), str) else None
    agents.seen(who, transcript)                # the session and where its transcript is, never the prompt
    try:
        kind, basis = whose(prompt, transcript)     # the user's own words, or another agent's or a tool's
    except Exception:  # noqa: BLE001  the evidence could not be read: the short card for this one prompt, and the
        kind, basis = NOTICE, "error"            # feed says why (audit of f342d88, protection finding 2)
    own = kind == USER
    turn_fault = keep_turn(store.root, event, prompt, transcript, own, basis)   # said after the card, if any
    # Kept as heard only when the tool's own record says the user typed it, the bar a typed answer has: the text
    # alone can be fooled (a relay behind a zero-width space, or in lower case), and nothing marked is not a yes.
    if own and basis == "transcript" and state.get("hear_prompts") and isinstance(prompt, str) and prompt.strip():
        try:
            Heard(store.root).hear(name, prompt, source="hook")   # only the user's own words become "heard"
        except Refused:
            pass                                 # a prompt holding a key is not kept, and still gets its card
    inbox = Inbox(store.root)
    # An answer typed in chat ("#12 2"): only from the user's own words, only when the tool's own record agrees that
    # the user typed them, and only from a message that is one answer and nothing else. Another agent's message, a
    # tool's notice, a message with no record, or pasted text that mentions requests answers nothing.
    one = typed_answer(prompt) if own else None
    took = None
    if one and basis == "transcript":
        try:
            took = take_answers(store, inbox, [one])
        except Exception as e:  # noqa: BLE001  the card still goes out; the inbox says whether the answer was kept
            took = [_kept_or_not(inbox, *one, e)]
    recorded = bool(took) and any(x["ok"] for x in took)   # what the feed calls an answer: one that was kept
    if one:
        said = chat_notes(took) if basis == "transcript" else chat_notes([], confirmed=False)
    else:   # a waiting request's number where an answer would put it: say plainly that nothing was taken
        try:
            waiting = {r["id"] for r in inbox.open_requests()} if own else set()
        except Exception:  # noqa: BLE001
            waiting = set()
        named = [i for i in mentioned(prompt) if i in waiting]
        said = not_taken_note(named) if named else ""
    notes = "\n\n".join(x for x in (said, card_notes(inbox, who)) if x)   # this agent's own requests and answers
    form = "full" if own else "relay"           # the short card for words that are not the user's
    layer = agents.own_names(who) if agents.serves_own_rules(who) else None   # its own rules, never a claim's
    out, served = compose(store, name, form, layer, notes)
    if state.get("feed", True):
        try:
            asked = [r for r in inbox.requests().values() if mine(r, who)]
            feed = Feed(store.root)
            feed.add(record(who, WORDS[kind], basis, served,
                            [r["id"] for r in asked if r["status"] == "answered" and not r["read"]],
                            [r["id"] for r in asked if r["status"] == "open"], sender_name(prompt),
                            noticed(store, name, prompt, recorded) if own else []))
            if feed.problem:   # a fault, not a busy moment: said once, as one line after the card
                out = f"{out}\n\nSemantext: {feed.problem}" if out else f"Semantext: {feed.problem}"
        except Exception:  # noqa: BLE001  the feed is a record of the work, never a reason for a prompt to fail
            pass
    if turn_fault:   # this turn's record was not kept: said each time, since each such turn's act reads unverified
        out = f"{out}\n\nSemantext: {turn_fault}" if out else f"Semantext: {turn_fault}"
    return out


def _read_event() -> str:
    """The event as Claude Code sends it: UTF-8 bytes, whatever this machine's own code page is."""
    buf = getattr(sys.stdin, "buffer", None)
    return buf.read().decode("utf-8", "replace") if buf is not None else sys.stdin.read()


def _write(text: str) -> None:
    """Exact bytes: UTF-8 and plain newlines, so the size limit holds on Windows too (no CR added per line)."""
    buf = getattr(sys.stdout, "buffer", None)
    if buf is not None:
        sys.stdout.flush()
        buf.write(text.encode("utf-8", "replace"))
        buf.flush()
    else:
        sys.stdout.write(text)


def main(event_text: str | None = None) -> int:
    try:
        _write(run(_read_event() if event_text is None else event_text) + "\n")
    except Exception as e:  # noqa: BLE001  never block the prompt, whatever went wrong
        _write(f"Semantext: the card is unavailable this time ({type(e).__name__}).\n")
    return 0
