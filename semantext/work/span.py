"""The transcript span behind a person's act (PM-DESIGN, decided 24 October, A1).

At write time the kernel records, in the act's evidence, where the person's own turn lies in the session's transcript:
its path, the byte offset and length of the turn's record, and the sha256 of those bytes. When the store is read, the
Work source re-reads that span and checks it again, so a person_act planted in the file with made-up evidence is
"not applied (unverified)", never state. The transcript itself is the log; no turn log of our own is kept.

A span is read only when it is in a transcript root the kernel trusts (transcript_roots), through no link and no second
hard link, and never more than MAX_SPAN bytes. The record it holds must be the person's own turn (provenance's reading
of the record and of its words), and its words must name exactly the act (turns.turn_names). Nothing here raises for
a span of any shape: a span that cannot be read or does not hold is unverified, with the reason.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

from .. import jsonread, provenance

MAX_SPAN = 256 * 1024          # bytes of one turn's record; a longer span is never read
VERIFIED, UNVERIFIED, ATTESTED = "verified", "unverified", "attested"
UNREADABLE = "its span cannot be read inside the transcript roots"   # a verdict of this kind is never kept (writer)
SPAN_KEYS = ("path", "offset", "length", "sha256")


def transcript_roots(cfg=None) -> list[Path]:
    """The folders a transcript span may lie in: the sources file's "transcripts" (a list of folders), else the tool's
    own transcript folder (~/.claude/projects)."""
    said = (cfg or {}).get("transcripts")
    if isinstance(said, list) and said:
        return [Path(x).expanduser() for x in said if isinstance(x, str) and x]
    return [Path.home() / ".claude" / "projects"]


def _inside(path, roots):
    """The transcript's resolved path when it is a plain file inside one of `roots` (no link, one hard link), else
    None."""
    try:
        p = Path(path)
        if not p.is_absolute() or p.is_symlink() or not p.is_file():
            return None
        real = p.resolve()
        if os.stat(real).st_nlink > 1:
            return None
        for root in roots:
            r = Path(root).resolve()
            if real != r and r in real.parents:
                return real
    except (OSError, ValueError, TypeError):
        return None
    return None


def read_span(path, offset, length, roots) -> bytes | None:
    """Exactly `length` bytes at `offset` of a transcript inside the trusted roots, or None. Bounded: never more than
    MAX_SPAN bytes, and nothing is read for a span of the wrong shape."""
    if not isinstance(path, str) or not all(isinstance(x, int) and not isinstance(x, bool) for x in (offset, length)):
        return None
    if offset < 0 or not 0 < length <= MAX_SPAN:
        return None
    real = _inside(path, roots)
    if real is None:
        return None
    try:
        with open(real, "rb") as f:
            if offset + length > os.fstat(f.fileno()).st_size:   # past the end: never sought (an offset of 2**63
                return None                                       # does not fit a file position, and raised)
            f.seek(offset)
            data = f.read(length)
    except (OSError, ValueError, OverflowError):
        return None
    return data if len(data) == length else None


FACTS = ("session", "turn", "turn_at")   # what the evidence says of the turn, each read from the turn's own record


def utc_stamp(text) -> str | None:
    """A transcript record's own time ("2026-10-24T13:59:00.123Z") as the kernel's stamp, to the second, else None."""
    try:
        t = datetime.fromisoformat(text) if isinstance(text, str) and len(text) <= 40 else None
    except ValueError:
        return None
    if t is None or t.tzinfo is None:
        return None
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def facts(rec) -> dict | None:
    """The turn's own marks, read from its transcript record and never from the evidence (round 4, decision 1b): its
    session (sessionId), its turn (uuid) and its time (timestamp, to the second); None when it lacks one."""
    if not isinstance(rec, dict):
        return None
    session, turn, at = rec.get("sessionId"), rec.get("uuid"), utc_stamp(rec.get("timestamp"))
    if not (isinstance(session, str) and 0 < len(session) <= 128 and isinstance(turn, str) and 0 < len(turn) <= 128
            and at is not None):
        return None
    return {"session": session, "turn": turn, "turn_at": at}


def named_line(data: bytes, ident: str, act: str, value) -> tuple[str | None, str, dict | None]:
    """(the act line the span's record names, or None; why not; the record's own facts): the record must be the
    person's own turn, by its own marks and by its words, it must carry its own session, turn and time, and its words
    must name exactly this act."""
    from .turns import turn_names
    try:
        rec = jsonread.loads(data.decode("utf-8").rstrip("\r\n"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, "the span is not one transcript record", None
    text, kind = provenance.record_origin(rec)
    if kind != provenance.USER or not isinstance(text, str) or provenance.by_text(text) != provenance.USER:
        return None, "the span's record is not the person's own turn", None
    own = facts(rec)
    if own is None:
        return None, "the span's record names no session, turn or time of its own", None
    line = turn_names(text, ident, act, value)
    return (line, "", own) if line else (None, "the span's words do not name this act", None)


def make(turn, ident: str, act: str, value, roots) -> tuple[dict | None, str, dict | None]:
    """At write time: the span of the turn's record, {path, offset, length, sha256}, once its bytes are read and found
    to name this act, with the record's own facts (session, turn, turn_at); or None, why, None."""
    path, offset, length = getattr(turn, "transcript", None), getattr(turn, "offset", None), getattr(turn, "length", None)
    if path is None:
        return None, "the turn's record names no span of the transcript", None
    data = read_span(path, offset, length, roots)
    if data is None:
        return None, "the turn's span of the transcript cannot be read inside the transcript roots", None
    line, why, own = named_line(data, ident, act, value)
    if line is None:
        return None, why, None
    return {"path": path, "offset": offset, "length": length, "sha256": hashlib.sha256(data).hexdigest()}, "", own


def check(rec: dict, roots, on_chain: bool = False) -> tuple[str, str]:
    """A stored person_act read back: (VERIFIED | ATTESTED | UNVERIFIED, why). An act with no span is UNVERIFIED: the
    kernel never writes one. The evidence's session, turn and time must be the span's record's own: the window and the
    used-once key (rules._person) then rest on the transcript, never on what the planter wrote.

    ATTESTED (round 4, decision 4): an act ON THE CHAIN that carries the writer's attestation (evidence "attested", the
    sha256 of the span it read and found to hold when it applied the act) stays applied when its transcript can no
    longer be read where it was: a backup's hard link, a move, a rotation, a cut. Bytes that read and differ are an
    edit, and the act falls, attested or not. The limit, as chain.py states it for every record: a program that writes
    both the log and its head can write an attestation too."""
    from .rules import clauses_hash
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    if not ev:
        return UNVERIFIED, "it carries no evidence of the person's turn"
    span = ev.get("span")
    if span is None:   # every act the kernel writes carries one; Work was never live without (follow-ups to A1, (b))
        return UNVERIFIED, "its evidence names no span of the transcript, so it cannot be checked"
    if not isinstance(span, dict) or set(span) != set(SPAN_KEYS):
        return UNVERIFIED, "its span is not {path, offset, length, sha256}"
    data = read_span(span["path"], span["offset"], span["length"], roots)
    if data is None:
        if on_chain and isinstance(span["sha256"], str) and ev.get("attested") == span["sha256"] and \
                all(isinstance(ev.get(k), str) for k in FACTS):
            return ATTESTED, ("checked against the person's turn when it was applied; its transcript can no longer "
                              "be read where it was (moved, linked or rotated)")
        return UNVERIFIED, UNREADABLE
    if hashlib.sha256(data).hexdigest() != span["sha256"]:
        return UNVERIFIED, "its span's bytes are not the ones recorded"
    act, value = rec.get("act"), rec.get("value")
    if act == "clauses":
        value = clauses_hash(rec.get("clauses") or [])
    if not isinstance(rec.get("id"), str) or not isinstance(act, str):
        return UNVERIFIED, "it names no item or act"
    line, why, own = named_line(data, rec["id"], act, value)
    if line is None or line != ev.get("line"):
        return UNVERIFIED, why or "its span names another act than its evidence"
    if any(ev.get(k) != own[k] for k in FACTS):
        return UNVERIFIED, "its evidence's session, turn or time is not its transcript record's own"
    return VERIFIED, "its span of the transcript holds the person's own turn naming this act"


def stamp(path):
    """(size, mtime in ns) of a transcript, or None when it cannot be read: what the writer's cache of verdicts
    compares to notice a transcript that changed."""
    try:
        st = os.stat(path)
    except (OSError, ValueError, TypeError):
        return None
    return st.st_size, st.st_mtime_ns


def span_path(rec: dict):
    """The transcript a stored person_act's span names, or None."""
    ev = rec.get("evidence") if isinstance(rec.get("evidence"), dict) else {}
    sp = ev.get("span") if isinstance(ev.get("span"), dict) else {}
    return sp.get("path") if isinstance(sp.get("path"), str) else None


def checks(records, roots) -> dict:
    """{line number: (verdict, why)} for every person_act among the walked records [(line, record, on_chain)] that
    claims to be the person's and carries evidence; the table refuses the others with its own codes, as before."""
    from .events import PERSON
    return {n: check(rec, roots, on_chain) for n, rec, on_chain in records
            if rec.get("event") == "person_act" and rec.get("who") == PERSON and isinstance(rec.get("evidence"), dict)}
