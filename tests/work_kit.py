"""Shared helpers for the work tests: a writer on a fresh home with a fixed clock, a stand-in for the transcript
source, and a way to plant lines the writer never wrote (the attacks write the file directly)."""
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from semantext.work.chain import line_of, read_head, seal
from semantext.work.events import WorkRefused
from semantext.work.turns import Turn
from semantext.work.writer import Actor, Writer

NOW = datetime(2026, 10, 24, 14, 0, 0, tzinfo=timezone.utc)
P = "semantext"


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class Turns:
    """session -> Turn: what the hook's record of the person's newest turn says (TranscriptTurns in real use)."""

    def __init__(self):
        self.by = {}

    def turn(self, session):
        return self.by.get(session)


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def transcripts(home):
    """The kit's transcript root: each session's transcript is <home>/transcripts/<session>.jsonl."""
    return Path(home) / "transcripts"


def make(home, **kw):
    clock, turns = kw.pop("clock", Clock()), kw.pop("turns", Turns())
    if "transcript_roots" in inspect.signature(Writer).parameters:
        kw.setdefault("transcript_roots", [transcripts(home)])
    w = Writer(home, projects=kw.pop("projects", {P, "atlas"}), seats=kw.pop("seats", {"alpha", "beta", "gamma"}),
               clock=clock, turns=turns, **kw)
    w.clock_, w.turns_ = clock, turns
    return w


def bound(who):
    return Actor(who, "bound", "mcp")


def claimed(who):
    return Actor(who, "claimed", "cli")


def transcript_record(text, origin="own", session=None, turn=None, at=None):
    """The tool's own record of a turn, as a transcript line holds it: with its session, its uuid and its own time
    when given (the kernel reads them from here, never from the evidence)."""
    rec = {"type": "user", "turnOrigin": "human" if origin == "own" else "peer",
           "message": {"role": "user", "content": text}}
    if session is not None:
        rec["sessionId"] = session
    if turn is not None:
        rec["uuid"] = turn
    if at is not None:
        rec["timestamp"] = at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return rec


def say(w, text, session="s1", turn="t1", ago=60, origin="own", basis="transcript", record=None):
    """The person's newest turn in `session`, `ago` seconds before the writer's now: its record appended to the
    session's transcript, and the turn naming that record's span (path, offset, length)."""
    path = transcripts(w.home) / f"{session}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = record if record is not None else transcript_record(
        text, origin, session=session, turn=turn, at=w.clock_.now - timedelta(seconds=ago))
    line = json.dumps(record).encode("utf-8")
    offset = path.stat().st_size if path.exists() else 0
    with open(path, "ab") as fh:
        fh.write(line + b"\n")
    got = {"session": session, "turn": turn, "at": stamp(w.clock_.now - timedelta(seconds=ago)), "text": text,
           "origin": origin, "basis": basis, "transcript": str(path), "offset": offset, "length": len(line)}
    w.turns_.by[session] = Turn(**{k: v for k, v in got.items() if k in Turn.__dataclass_fields__})


def person(w, ident, act, frm=None, value=None, text=None, session="s1", turn=None, **extra):
    """The person types the act's own line (or `text`) and the kernel acts on it."""
    from semantext.work.turns import act_line
    if text is None:
        text = act_line(ident, act, value)
    say(w, text, session=session, turn=turn or f"t-{ident}-{act}-{frm}-{value}")
    req = {"id": ident, "act": act, **extra}
    if frm is not None:
        req["from"] = frm
    if value is not None:
        req["value"] = value
    return w.person_act(session, req)


def checks_of(w, lines, head):
    """The person_acts' span checks for these lines, as the writer and the Work source give them to the fold."""
    from semantext.work import span
    from semantext.work.chain import walk
    return span.checks(walk(lines, None, head)["records"], w.transcript_roots)


def refused(code, fn, *a, **k):
    with pytest.raises(WorkRefused) as e:
        fn(*a, **k)
    assert e.value.code == code, e.value
    return e.value


def item(w, ident):
    return w.state()["items"].get(ident)


def row(w, seq):
    return next(e for e in w.state()["events"] if e["seq"] == seq)


def new(w, who="alpha", title="A task", actor=None, **kw):
    return w.write(actor or bound(who), "create", {"project": P, "title": title, **kw})["id"]


def to_doing(w, who="alpha", **kw):
    """An item of `who`'s, ranked by the person and moved to doing by its owner."""
    ident = new(w, who, links=[{"type": "commit", "ref": "abc1234"}], **kw)
    person(w, ident, "next", frm="backlog")
    w.write(bound(who), "move", {"id": ident, "from": "next", "to": "doing"})
    return ident


def lines(w):
    return w.path.read_text(encoding="utf-8").splitlines() if w.path.exists() else []


def plant(w, rec, move_head=True, raw=None):
    """Append a line the kernel's writer never wrote: a sealed record chained to the head (and, with move_head, the
    head moved too, as a program that can write both would), or `raw` text as it is."""
    head = read_head(w.head_path.read_text(encoding="utf-8")) if w.head_path.exists() else {"seq": 0, "hash": "0" * 64}
    w.dir.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        with open(w.path, "ab") as fh:
            fh.write(raw.encode("utf-8") if isinstance(raw, str) else raw)
        return None
    full = {"v": 1, "channel": "mcp", "at": stamp(w.clock_.now), **rec}
    sealed = seal(full, head["seq"] + 1, head["hash"])
    with open(w.path, "ab") as fh:
        fh.write((line_of(sealed) + "\n").encode("utf-8"))
    if move_head:
        w.head_path.write_text('{"seq": %d, "hash": "%s"}' % (sealed["seq"], sealed["hash"]), encoding="utf-8")
    return sealed["seq"]
