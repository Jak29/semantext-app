"""Whose words a prompt carries, read ONE way for every engine: the app's hook (sender.whose) and the estate's reading
card (envhook.from_owner). Two copies of these rules drifted apart (audit of e36d0c0, findings F-A to F-G), so both
engines now call this module and keep only their own vocabulary.

The default is the user's, and only evidence takes a prompt away. Two kinds count:
  - the prompt's TEXT, when it opens the way the tools deliver another agent's message or a notice (past any mix of
    whitespace and byte-order marks); a message that mentions those words later stays the user's;
  - the tool's own RECORD of the prompt: the NEWEST record with the same words (line endings, no-break spaces, a
    byte-order mark and outer whitespace aside) that names an origin decides, and only when it says the prompt was
    not the user's. A record that names no origin is no evidence, so it never hides an older one that does.
A record can only take a prompt away, never give one back. Nothing here raises: a transcript, a record or a prompt
of any shape that cannot be read is no evidence, which leaves the user's own (the full card holds every rule).
"""
from __future__ import annotations

import json
import re

from . import jsonread

USER, RELAY, NOTICE = "user", "relay", "notice"
# The opening forms, ONE test (_opens_as) for a bare prompt and for the words inside a wrapper alike, compared without
# case. Another agent's message: one session's to another (with or without words between "message" and its colon:
# "... sent a message while you were working:"), or a subagent's to the session that started it.
RELAY_STARTS = ("another claude session sent a message", "<cross-session-message", "<agent-message")
# The first form needs its colon, within a few words on the same line: a prompt that only begins with those words is
# the user's own (round 3 review, F4).
RELAY_PHRASE = re.compile(r"another claude session sent a message[^:\n]{0,60}:")
# A tool's own report or notice.
NOTICE_STARTS = ("<task-notification>",)
# A bracketed notice the tool adds, recognised by the words it carries rather than one exact spelling.
NOTICE_TAG = re.compile(r"\[[^\]\n]{0,120}?(?:cross-session|not user input|non-user source|system notification)"
                        r"[^\]\n]{0,120}\]", re.IGNORECASE)
# Inside a wrapper the tool's own notice also opens "[system notification" with a bracket that is long or runs onto the
# next line, as the wrapped reader before b220b2c accepted it (round 3 review, F3). Bare, such a bracket stays the
# user's: a user's own "[Cross-session notes\n]" is theirs.
WRAPPED_NOTICE = "[system notification"
# The tool can wrap another session's message, or a notice, in a system-reminder tag (F-B: one engine lacked it). The
# opening tag is read whole by one pattern, and the words after it get the same test as a bare prompt (audit of the
# v2-next merge: a wrapped bracketed notice, a wrapped raw tag and a ">" in a quoted attribute all read as the user's).
# The name ends at a blank, "/" or ">" (F5). A quoted value is one only after "=" (so it may hold ">"); any other quote
# is an ordinary character (F2). No possessive repeat (Python 3.10 has none, F1): the four alternatives start
# differently ("=" before a quote, "=" before anything else, anything but "=" and ">"), so the pattern is still linear.
WRAPPER = re.compile(r"<system-reminder(?=[\s/>])(?:[^=>]|=(?![ \t\r\n]*[\"'])|=[ \t\r\n]*\"[^\"]*\"|"
                     r"=[ \t\r\n]*'[^']*')*>", re.IGNORECASE)
WRAPS = 3                         # a wrapper inside a wrapper is read this deep, and no deeper

TAIL_BYTES = 4_000_000           # how much of the transcript's end is read: a prompt's record is among the newest
# Claude Code marks each turn with where it came from (turnOrigin). A value not named here says nothing, so the
# record's other marks, or the default, decide. A "scheduled" turn (a /loop wake-up) was started by the tool, not typed
# by the user: the owner's decision of 2026-10-23 is that it is never the user's words.
TURN_ORIGIN = {"human": USER, "peer": RELAY, "task_notification": NOTICE, "system": NOTICE, "scheduled": NOTICE}
# The older form of the same record, still written on many records with no turnOrigin: {"origin": {"kind": ...}}.
ORIGIN_KIND = {"human": USER, "peer": RELAY, "task-notification": NOTICE, "task_notification": NOTICE, "system": NOTICE}
BOM = "﻿"
# Every whitespace character and the byte-order mark, so one str.strip pass removes any mix of them, in either order
# (F-C). A loop of lstrip() then lstrip(BOM) copied the string once per pair: quadratic on alternating runs.
EDGE = "".join(chr(c) for c in range(0x3001) if chr(c).isspace()) + BOM
# How much of an opening the prefix test examines (a wrapper's tag is read whole, then its words get the same bound):
# the longest form is the bracketed notice, at most 1 + 120 + 19 + 120 + 1 = 261 characters.
OPENING = 300


def _str(value) -> str | None:
    """A record's field as a lookup key: only a string is one (F-G: a list in its place raised TypeError)."""
    return value if isinstance(value, str) else None


def head(prompt: str) -> str:
    """The prompt's opening, past any mix of whitespace and byte-order marks, in either order (F-C), in one pass.
    str.lstrip() alone does not remove U+FEFF."""
    return prompt.lstrip(EDGE)


def same(text: str) -> str:
    """A prompt's text in the form it is compared with its record in: CRLF and CR as LF, a no-break space as a space,
    no byte-order mark or whitespace at either end. The hook's prompt and the record's text can differ in exactly
    these (F-E; earlier, two prompts with CRLF got the owner's card in production)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").strip(EDGE)


def by_text(prompt) -> str:
    """USER, RELAY or NOTICE, from how the prompt opens. Anything that is not text is the user's (the default)."""
    if not isinstance(prompt, str):
        return USER
    return _opens_as(head(prompt)) or USER


def _opens_as(h: str, depth: int = 0) -> str | None:
    """RELAY or NOTICE when text (already past its leading whitespace) opens as another agent's message or a notice,
    bare or inside a system-reminder wrapper however long its attributes or the whitespace after it; None otherwise."""
    opening = h[:OPENING].lower()
    if opening.startswith(RELAY_STARTS[1:]) or RELAY_PHRASE.match(opening):
        return RELAY
    if opening.startswith(NOTICE_STARTS) or NOTICE_TAG.match(opening) or (depth and opening.startswith(WRAPPED_NOTICE)):
        return NOTICE
    if depth < WRAPS:
        m = WRAPPER.match(h)
        if m:
            return _opens_as(h[m.end():].lstrip(EDGE), depth + 1)
    return None


# ---- the tool's own record of where a prompt came from ---------------------------------------------------------------
def _kind(origin) -> str | None:
    return ORIGIN_KIND.get(_str(origin.get("kind"))) if isinstance(origin, dict) else None


def record_text(r: dict) -> str | None:
    """The text of a user record that is a prompt: a string, or text blocks (perhaps beside an image). None for a
    tool's result, or anything else."""
    m = r.get("message") if isinstance(r.get("message"), dict) else {}
    c = m.get("content")
    if isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None
        c = "".join(b["text"] for b in c
                    if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)) or None
    return c if isinstance(c, str) else None


def record_origin(r) -> tuple[str | None, str | None]:
    """(the prompt text a transcript record carries, where it came from: USER, RELAY, NOTICE or None when the record
    says nothing of itself), or (None, None) for a record that carries no prompt."""
    if not isinstance(r, dict):
        return None, None
    a = r.get("attachment") if isinstance(r.get("attachment"), dict) else {}
    if a.get("type") == "queued_command":
        text = _str(a.get("prompt"))
        if a.get("humanTurn"):
            return text, USER
        if a.get("commandMode") == "task-notification":
            return text, NOTICE
        if a.get("isMeta"):
            return text, RELAY if a.get("reminderId") else NOTICE
        return text, _kind(a.get("origin")) or _kind(r.get("origin"))
    if r.get("type") == "user":
        text = record_text(r)
        if r.get("isCompactSummary") or r.get("isVisibleInTranscriptOnly"):
            return text, NOTICE          # F-D: a compaction summary is the tool's text, whatever its turnOrigin says
        kind = TURN_ORIGIN.get(_str(r.get("turnOrigin"))) or _kind(r.get("origin"))
        if kind is None and r.get("isMeta"):
            kind = NOTICE                # F-D: added by the tool, never typed
        return text, kind
    return None, None


def _parse(line: bytes):
    """One transcript line as a record, or None. Nesting is bounded by the interpreter's own limit: a line nested
    deeper is no record (F-G: it raised RecursionError)."""
    try:
        return jsonread.loads(line)
    except (ValueError, RecursionError):
        return None


def records(transcript, needles, tail: int = TAIL_BYTES):
    """The transcript's records (dicts) whose line holds one of `needles` (bytes), newest first, from its last `tail`
    bytes. Nothing at all for a path of any shape that cannot be read."""
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            lines = f.read().splitlines()
    except (OSError, ValueError, TypeError):
        return
    for line in reversed(lines):
        if not any(n in line for n in needles):
            continue                     # cheap: most lines are not this prompt's record
        r = _parse(line)
        if isinstance(r, dict):
            yield r


def span_of(transcript, prompt, tail: int = TAIL_BYTES) -> dict | None:
    """Where the prompt's own record lies in the transcript: {"offset", "length", "turn"} for the newest line, in the
    last `tail` bytes, whose record carries these words (as same() compares them), or None. Offset and length are of
    the line's bytes, its newline and any carriage return left out; "turn" is the record's uuid when it has one. Never
    raises (the work kernel's turn record, PM-DESIGN follow-ups to A1, (a))."""
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    want = same(prompt)
    try:
        with open(transcript, "rb") as f:
            f.seek(0, 2)
            base = max(0, f.tell() - tail)
            f.seek(base)
            data = f.read()
    except (OSError, ValueError, TypeError):
        return None
    marks = needles(prompt)
    end = len(data)
    while end > 0:
        start = data.rfind(b"\n", 0, end - 1) + 1 if end > 1 else 0
        line = data[start:end].rstrip(b"\n").rstrip(b"\r")
        end = start
        if (start == 0 and base > 0) or not any(n in line for n in marks):
            continue                     # a line cut by the tail, or not this prompt's
        r = _parse(line)
        text, _ = record_origin(r)
        if isinstance(text, str) and same(text) == want:
            turn = r.get("uuid") if isinstance(r.get("uuid"), str) else None
            return {"offset": base + start, "length": len(line), "turn": turn}
    return None


def needles(words: str) -> set[bytes]:
    """`words` as they appear inside a JSON line (quotes, backslashes and line breaks escaped). A record may store
    non-ASCII as itself or as \\u escapes: both are looked for."""
    return {json.dumps(words, ensure_ascii=a)[1:-1].encode("utf-8", "surrogatepass") for a in (False, True)}


def _recorded(transcript, prompt, tail: int) -> str | None:
    want = same(prompt)
    if not want:
        return None
    # the needle is the first word only (up to 40 characters), so line ends and no-break spaces cannot hide a record;
    # the comparison below decides
    first = re.split(r"\s", want, maxsplit=1)[0][:40] or want[:40]
    for r in records(transcript, needles(first), tail):
        text, kind = record_origin(r)
        if kind is not None and text is not None and same(text) == want:
            return kind                  # the newest record with these words that NAMES an origin decides
    return None                          # one that names none is no evidence, and never hides an older one's


def recorded(transcript, prompt, tail: int = TAIL_BYTES) -> str | None:
    """Where the tool's own transcript says this prompt came from (USER, RELAY or NOTICE): its newest record whose
    text is the prompt's and that names an origin. None when there is no transcript or no such record yet."""
    if not transcript or not isinstance(prompt, str) or not prompt.strip():
        return None
    try:
        return _recorded(transcript, prompt, tail)
    except Exception:  # noqa: BLE001  the record is a second opinion: an unreadable one is no evidence (F-G)
        return None


def classify(prompt, transcript=None, record_check: bool = True) -> tuple[str, str]:
    """Whose words a prompt carries (USER, RELAY or NOTICE), and what told: "text" when the prompt opens as a relay
    or a notice, "transcript" when the tool's own record decided, "none" when nothing said (the user's, the default).
    The text decides first; the record can only take a prompt away from the user, never give one to them."""
    kind = by_text(prompt)
    if kind != USER:
        return kind, "text"
    if not record_check:
        return USER, "none"
    origin = recorded(transcript, prompt)
    if origin in (RELAY, NOTICE):
        return origin, "transcript"
    return USER, "transcript" if origin == USER else "none"
