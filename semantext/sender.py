"""Whose words a prompt carries: the user's own, another agent's, or a tool's notice.

An AI tool hands its agent more than the user's messages: another session's message, a background task's report, a
system notice. Read with the user's full card, such words get treated as the user's own. So the hook tells them
apart, and gives anything that is not the user's own message the short relay card.

The test looks only at how a prompt OPENS, in the forms the tools use for those deliveries. A user's own message that
mentions those words later, or opens with a bracket of its own, stays the user's. Anything unreadable counts as the
user's: the safe direction, since the full card holds every rule.

The rules themselves, and the reading of the tool's own record, live in provenance.py, shared with the estate's
reading card (envhook.from_owner), so the two can never drift apart again.
"""
from __future__ import annotations

import hashlib
import re

from . import provenance
from .provenance import (NOTICE, NOTICE_STARTS, NOTICE_TAG, RELAY, RELAY_STARTS, TAIL_BYTES, USER,  # noqa: F401
                         record_text)

FROM_NAME = re.compile(r'\bfrom-name="([^"\n]{1,80})"')


def relay_from(prompt) -> str:
    """The name a relayed message gives its sender, when its opening tag states one (Claude Code's message from another
    session carries from-name="..."): the sender's own claim, taken from the tag alone, never from the message. "" when
    the prompt is not a relay, or its opening states no name."""
    if not isinstance(prompt, str) or sender_of(prompt) != RELAY:
        return ""
    head = provenance.head(prompt)[:600]
    end = head.find(">")
    m = FROM_NAME.search(head[:end] if end > 0 else "")
    return m.group(1) if m else ""


def sender_of(prompt) -> str:
    """USER, RELAY or NOTICE, from how the prompt opens."""
    return provenance.by_text(prompt)


# ---- the tool's own record of where a prompt came from ---------------------------------------------------------------
# Claude Code keeps a transcript, and marks each turn with where it came from (turnOrigin), and each prompt queued while
# the agent worked with what kind it was. Measured on 1,503 prompts of one real transcript: every prompt's
# record was made before its hook started, and was already in the file for all turns and all but 11 queued prompts.
def origin_of(transcript, prompt, tail: int = TAIL_BYTES) -> str | None:
    """Where the tool's own transcript says this prompt came from (USER, RELAY or NOTICE): its newest record whose text
    is the prompt's. None when there is no transcript, no such record yet, or the record says nothing."""
    return provenance.recorded(transcript, prompt, tail)


SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
# What the scribe may write down as the user's own rule. A list of question wordings always misses one ("don't we ...",
# "..., right", "maybe we should ..."), so the test runs the other way: the sentence must OPEN with a standing-preference
# form, and carry no hedge or question anywhere. Anything else is a proposal, and the user decides what they meant.
RULE_OPENING = re.compile(r"^(?:always|never(?!\s+mind\b)|from now on|don'?t(?!\s+(?:we|you|i|they|he|she|it)\b)"
                          r"|do not|please don'?t|make sure|i want you to|i prefer|i'?d rather)\b", re.I)
# ... or a reading rule in its tight form, which may quote the very hedge it defines ("When I say maybe, I mean no").
READING_RULE = re.compile(r"^when i (?:say|ask|write|use)\b.{1,200}?\bi(?:'m| am)?\s+(?:mean|meant|asking|want)\b", re.I)
HEDGE = re.compile(r"\b(?:maybe|perhaps|might|could|should we|we could|what if|how about|i think|i was thinking"
                   r"|i wonder"
                   # ... and time words: "Don't push yet" is a choice for now, and made permanent it would misread
                   # the very time words the user chose (and could quietly block an act they later want)
                   r"|yet|for now|today|tonight|this time|right now|at the moment|until)\b|,\s*right\b|\bisn'?t it\b|\?",
                   re.I)


def users_sentence(transcript, words) -> dict | None:
    """The user's own sentence, if `words` is one, word for word, in this transcript: a whole sentence of a prompt the
    tool records as the user's own turn and whose text reads as theirs, opening as a standing preference (always, never,
    don't, from now on, I prefer ...) with no hedge or question in it, or a reading rule in its tight form. A span
    proves who wrote it, not that it was meant as a rule: a question, a maybe, part of a sentence or a one-off order
    stays a proposal. Returns where it came from (the prompt's hash, time and the sentence's place), or None."""
    want = str(words or "").strip()
    body = re.sub(r"^no[,.]\s*", "", want, flags=re.I)   # "No, when I say ..." or "No, never ..."
    if not transcript or not body:
        return None
    if READING_RULE.match(body):
        if want.endswith("?"):
            return None                  # it may quote a hedge, but it may not ask
    elif not RULE_OPENING.match(body) or HEDGE.search(want):
        return None
    for r in provenance.records(transcript, provenance.needles(want)):
        text, origin = provenance.record_origin(r)
        if origin != USER or text is None or sender_of(text) != USER:
            continue                     # only a prompt that both the record and the text call the user's own
        if want not in (s.strip() for s in SENTENCES.split(text)):
            continue                     # a whole sentence, never a span of one
        return {"sentence": want, "offset": text.find(want), "at": r.get("timestamp"),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]}
    return None


def whose(prompt, transcript=None) -> tuple[str, str]:
    """Whose words a prompt carries (USER, RELAY or NOTICE), and what told: "text" when the prompt opens as a relay
    or a notice, "transcript" when the tool's own record decided, "none" when nothing said (the user's, the safe
    side). The text decides first; the tool's own record can only take a prompt away from the user, never give one to
    them: a relay read as the user's words is the costly mistake, so a record that is stale, or matches an older prompt
    with the same words, cannot turn a relay into the user's own."""
    return provenance.classify(prompt, transcript)


def own_words(prompt, transcript=None) -> bool:
    """Whether a prompt is the user's own words (see whose)."""
    return whose(prompt, transcript)[0] == USER
