"""The person's acts on work items: the turn that names one, and the inbox's deep link (PM-DESIGN r2, r3, r5; doors spec
v0.6, rule 5).

An act counts only when the kernel itself finds the person's own turn and that turn names it:
  - the turn is found by the session of the kernel's own channel, in a configured root (TranscriptTurns), never from
    a path, a transcript or a session the caller sends; a record outside the root, through a link or with a second
    hard link is not evidence;
  - the record says the words are the person's own, on a transcript ("own", "transcript"); relayed is refused;
  - the WHOLE turn is act lines and nothing else, each exactly "<id> <choice>" (a space, tab or colon between, at
    most one full stop or exclamation mark after). Lines split only on \\n and \\r\\n, only spaces and tabs are
    trimmed, matching is ASCII: a quote, a question, a sentence, a zero-width or look-alike character, or an id that
    is a prefix of another (W-semantext-12 in W-semantext-120) is not the act;
  - it is used once, and only within ACT_SECONDS of the kernel's now.
The choices for a work item: backlog, next, doing, review, done, park, unpark (the doors spec's list), and, where the
design was silent, reopen and void, a whole number (the priority), "assign <seat>" (reassign) and "clauses <8 hex>"
(new acceptance clauses, named by the first 8 hex digits of their hash, so the line binds the clauses it accepts).
The id is matched exactly, case included (ids are lower case), and so is the seat in "assign <seat>"; the choice word
in any ASCII case.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .. import jsonread
from .events import ID_RE, SEAT_RE, PERSON, WorkRefused, parse_id

ACT_SECONDS = 600
WORDS = ("backlog", "next", "doing", "review", "done", "park", "unpark", "reopen", "void")
OTHER_WORDS = ("yes", "no", "grant", "revoke", "switch")   # the doors' families: still act lines, never this act
SEP = r"(?:[ \t]+|:[ \t]*)"
END = r"[ \t]*[.!]?"
ANY_ACT = re.compile(r"[A-Za-z]+[_-][A-Za-z0-9_-]*[A-Za-z0-9]" + SEP +
                     r"(?:(?:%s)|[0-9]{1,6}|assign[ \t]+[A-Za-z][A-Za-z0-9._-]{0,39}|clauses[ \t]+[0-9a-f]{8})" %
                     "|".join(WORDS + OTHER_WORDS) + END, re.ASCII | re.IGNORECASE)


def when(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def act_line(ident: str, act: str, value=None) -> str | None:
    """The line, as the kernel writes it in the evidence, that names this act; None for an act that has none."""
    if parse_id(ident) is None:
        return None
    if act in WORDS and value is None:
        return f"{ident} {act}"
    if act == "priority" and isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 999999:
        return f"{ident} {value}"
    if act == "assign" and isinstance(value, str) and SEAT_RE.fullmatch(value) and value != PERSON:
        return f"{ident} assign {value}"
    if act == "clauses" and isinstance(value, str) and re.fullmatch(r"[0-9a-f]{8}", value):
        return f"{ident} clauses {value}"
    return None


def turn_names(text, ident: str, act: str, value=None) -> str | None:
    """The line of the turn that names this act, or None. Every non-blank line must be an act line (of any family);
    a turn that mixes an act with anything else names nothing."""
    expect = act_line(ident, act, value)
    if expect is None or not isinstance(text, str):
        return None
    lines = [x.strip(" \t") for x in re.split(r"\r?\n", text) if x.strip(" \t")]
    if not lines or not all(ANY_ACT.fullmatch(x) for x in lines):
        return None
    word = expect[len(ident) + 1:]
    choice, _, rest = word.partition(" ")
    # the choice word in any case; what follows it (the seat of "assign <seat>", the clauses' hex) exactly, as the id
    tail = re.escape(choice) + (r"[ \t]+(?-i:" + re.escape(rest) + ")" if rest else "")
    shape = re.compile(re.escape(ident) + SEP + tail + END, re.ASCII | re.IGNORECASE)
    for x in lines:
        m = shape.fullmatch(x)
        if m and x.startswith(ident):          # the id exactly, case included
            return expect
    return None


@dataclass(frozen=True)
class Turn:
    """The tool's own record of the person's newest turn in a session, as the kernel read it."""
    session: str
    turn: str
    at: str           # UTC, %Y-%m-%dT%H:%M:%SZ
    text: str
    origin: str       # "own" | "relayed"
    basis: str        # "transcript" | "none"
    # where the turn's own record lies in the session's transcript: its path, and the byte offset and length of the
    # record's line (PM-DESIGN, decided 24 October, A1). A turn without them is never acted on.
    transcript: str | None = None
    offset: int | None = None
    length: int | None = None


def turns_root(home=None) -> Path:
    """The folder the hook keeps each session's newest turn in (paths.turns_dir), which TranscriptTurns reads."""
    from ..paths import turns_dir
    return turns_dir(home)


class TranscriptTurns:
    """Reads <root>/<session>.json, a record the hook keeps of the session's newest turn (semantext hook,
    turns_root): {origin, basis, turn, at, transcript, offset, length}, and "text" when a record carries the words
    itself; the hook's does not, so they are read from the span. The session comes from the kernel's channel. A name with a separator, a
    link, a second hard link, or a file whose real folder is not the root is not evidence (doors spec v0.6, rule 5).
    `transcripts` are the folders a transcript span may lie in (span.transcript_roots)."""

    def __init__(self, root, transcripts=None):
        from .span import transcript_roots
        self.root = Path(root).resolve()
        self.transcripts = list(transcripts) if transcripts is not None else transcript_roots()

    def turn(self, session):
        if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session, re.ASCII):
            return None
        path = self.root / f"{session}.json"
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != self.root:
                return None
            if os.stat(path).st_nlink > 1:
                return None
            rec = jsonread.loads(path.read_text(encoding="utf-8"))   # a NotJSON is a ValueError: no evidence
        except (OSError, ValueError):
            return None
        if not isinstance(rec, dict) or not all(isinstance(rec.get(k), str) for k in ("origin", "basis", "turn", "at")):
            return None
        whole = lambda k: rec.get(k) if isinstance(rec.get(k), int) and not isinstance(rec.get(k), bool) else None
        where = (rec.get("transcript") if isinstance(rec.get("transcript"), str) else None, whole("offset"),
                 whole("length"))
        text = rec.get("text") if isinstance(rec.get("text"), str) else self._words(*where)
        if not isinstance(text, str):
            return None
        return Turn(session, rec["turn"], rec["at"], text, rec["origin"], rec["basis"], *where)

    def _words(self, path, offset, length):
        """The turn's words, read from its own record in the transcript: the hook copies no words (paths.turns_dir)."""
        from .. import jsonread as jr, provenance
        from .span import read_span
        data = read_span(path, offset, length, self.transcripts) if path is not None else None
        if data is None:
            return None
        try:
            text, _ = provenance.record_origin(jr.loads(data.decode("utf-8")))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return None
        return text


def check_turn(turn, ident: str, act: str, value, now: datetime, roots=None) -> dict:
    """The evidence for a person's act from the turn the kernel found, or a refusal: NOT_AUTHORIZED for words known to
    be relayed, UNDECIDABLE (the act stays waiting) for anything that is not his own turn naming exactly this act. The
    evidence carries the span of the turn's record in its transcript, read here inside `roots` and found to be his
    own turn naming the act, so the act can be checked again whenever it is read (span.py)."""
    if turn is None:
        raise WorkRefused("UNDECIDABLE", "no record of the person's own turn in this session; it stays waiting")
    if turn.basis != "transcript":
        raise WorkRefused("UNDECIDABLE", "the record does not say, on a transcript, whose words these are")
    if turn.origin != "own":
        raise WorkRefused("NOT_AUTHORIZED", "these words are relayed, not the person's own")
    line = turn_names(turn.text, ident, act, value)
    if line is None:
        raise WorkRefused("UNDECIDABLE", "no turn of the person's own, made only of act lines, names exactly this "
                                         "act; it stays waiting")
    from .span import make, transcript_roots
    span, why, own = make(turn, ident, act, value, transcript_roots() if roots is None else roots)
    if span is None:
        raise WorkRefused("UNDECIDABLE", f"{why}, so the act could never be checked again; it stays waiting")
    # the session, the turn and its time are the transcript record's own, never the hook's or the caller's (round 4)
    if own["session"] != turn.session:
        raise WorkRefused("UNDECIDABLE", "the turn's record in the transcript is of another session; it stays waiting")
    at = when(own["turn_at"])
    if at is None or not 0 <= (now - at).total_seconds() <= ACT_SECONDS:
        raise WorkRefused("UNDECIDABLE", "the turn naming this act is too old (or has no time); they say it again")
    # "attested": the writer's verdict at apply time, the sha256 of the span it read and found to hold, so the act
    # stays applied when the transcript is later linked, moved or rotated (round 4, decision 4; span.check)
    return {"session": own["session"], "turn": own["turn"], "turn_at": own["turn_at"], "line": line, "span": span,
            "attested": span["sha256"]}


# ---- the inbox's deep link (r5): jak-inbox://work/<project>/<n>, an id and nothing else -----------------------------
SCHEME = "jak-inbox://work/"
LINK_RE = re.compile(r"jak-inbox://work/([a-z](?:[a-z0-9-]{0,62}[a-z0-9])?)/([1-9][0-9]{0,5})", re.ASCII)


def deep_link(ident: str, projects) -> str:
    got = parse_id(ident)
    if got is None or got[0] not in set(projects or ()):
        raise WorkRefused("MALFORMED", f"{ident!r} is not an item of a known project")
    return f"{SCHEME}{got[0]}/{got[1]}"


def parse_deep_link(url, projects) -> str:
    """The item id a deep link names. It carries only the id: no action word, query, fragment, extra path, percent
    sign or any character outside the id's own (r3, r5; the attack, A10)."""
    m = LINK_RE.fullmatch(url) if isinstance(url, str) else None
    if not m or m.group(1) not in set(projects or ()):
        raise WorkRefused("MALFORMED", "a work link is jak-inbox://work/<known project>/<n> and nothing else")
    ident = f"W-{m.group(1)}-{m.group(2)}"
    if not ID_RE.fullmatch(ident):
        raise WorkRefused("MALFORMED", "not an item id")
    return ident
