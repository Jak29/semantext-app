"""Review round 4, the forged person_act (decision 1): (a) an act with no span is unverified everywhere and the fold
refuses it; (b) a genuine old turn cannot be replayed. The session, the turn and its time are read from the
transcript record at the span, never from the evidence; the act lies within ACT_SECONDS of that record's own stamp;
and one transcript record (keyed by the sha256 of its span) authorizes at most one act."""
import hashlib
import json
from datetime import timedelta

import pytest

from semantext.sources import work
from semantext.work.chain import walk
from semantext.work.fold import fold
from work_kit import (NOW, P, make, new, person, plant, refused, say, stamp, transcript_record, transcripts)


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def page(w):
    return work.load({"_home": str(w.home), "transcripts": [str(transcripts(w.home))]}, now=NOW, projects={P, "atlas"})


def shown(w, ident):
    return next(i for i in page(w)["items"] if i["id"] == ident)


def history_row(w, ident, seq):
    return next(e for e in shown(w, ident)["history"] if e["seq"] == seq)


def put(w, record, name="s1"):
    """One transcript record appended to <roots>/<name>.jsonl: its span."""
    path = transcripts(w.home) / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(record).encode("utf-8")
    offset = path.stat().st_size if path.exists() else 0
    with open(path, "ab") as f:
        f.write(data + b"\n")
    return {"path": str(path), "offset": offset, "length": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def forged(ident, what, span, session="s1", turn="t9", turn_at=None, frm=None):
    rec = {"event": "person_act", "id": ident, "act": what, "who": "person", "assurance": "bound",
           "evidence": {"session": session, "turn": turn, "turn_at": turn_at or stamp(NOW - timedelta(seconds=60)),
                        "line": f"{ident} {what}", "span": span}}
    if frm:
        rec["from"] = frm
    return rec


# ---- (a) no span: unverified on the page, in the writer, and in a fold given no checks -------------------------------
def test_a_spanless_act_is_refused_by_every_reader(w):
    ident = new(w, "alpha")
    rec = forged(ident, "park", None)
    del rec["evidence"]["span"]
    seq = plant(w, rec)
    assert history_row(w, ident, seq)["code"] == "UNVERIFIED"
    assert w.state()["items"][ident]["state"] == "backlog"
    lines = w.path.read_text(encoding="utf-8").splitlines()
    head = json.loads(w.head_path.read_text(encoding="utf-8"))
    walked = walk(lines, None, head)
    st = fold(walked["records"], checks=None)                               # no checks given: still never state
    assert st["items"][ident]["state"] == "backlog"
    assert next(e for e in st["events"] if e["seq"] == seq)["code"] == "UNVERIFIED"


# ---- (b) replay of a genuine old turn ----------------------------------------------------------------------------------
def test_an_old_turn_is_not_an_act_now_whatever_the_evidence_says(w):
    ident = new(w, "alpha")
    old = NOW - timedelta(days=7)
    sp = put(w, transcript_record(f"{ident} park", session="s1", turn="t9", at=old))
    seq = plant(w, forged(ident, "park", sp, turn_at=stamp(NOW - timedelta(seconds=60))))   # a fresh time, made up
    row = history_row(w, ident, seq)
    assert not row["applied"] and shown(w, ident)["state"] == "backlog"
    seq2 = plant(w, forged(ident, "park", sp, turn_at=stamp(old)))         # the record's own time: too old
    assert not history_row(w, ident, seq2)["applied"] and shown(w, ident)["state"] == "backlog"


def test_partner_a_fresh_record_whose_evidence_is_its_own_is_applied(w):
    ident = new(w, "alpha")
    sp = put(w, transcript_record(f"{ident} park", session="s1", turn="t9", at=NOW - timedelta(seconds=60)))
    seq = plant(w, forged(ident, "park", sp))
    assert history_row(w, ident, seq)["check"] == "verified" and shown(w, ident)["state"] == "parked"


@pytest.mark.parametrize("field,value", [("session", "s2"), ("turn", "t-other"),
                                         ("turn_at", stamp(NOW - timedelta(seconds=30)))])
def test_evidence_that_is_not_its_records_own_is_unverified(w, field, value):
    ident = new(w, "alpha")
    sp = put(w, transcript_record(f"{ident} park", session="s1", turn="t9", at=NOW - timedelta(seconds=60)))
    seq = plant(w, forged(ident, "park", sp, **{field: value}))
    row = history_row(w, ident, seq)
    assert row["code"] == "UNVERIFIED" and shown(w, ident)["state"] == "backlog"


def test_a_record_with_no_session_turn_or_time_is_unverified(w):
    ident = new(w, "alpha")
    sp = put(w, {"type": "user", "turnOrigin": "human", "message": {"role": "user", "content": f"{ident} park"}})
    seq = plant(w, forged(ident, "park", sp))
    assert history_row(w, ident, seq)["code"] == "UNVERIFIED"


def test_one_record_authorizes_one_act_whatever_turn_id_the_evidence_gives(w):
    ident = new(w, "alpha")
    sp = put(w, transcript_record(f"{ident} park\n{ident} 5", session="s1", turn="t9",
                                  at=NOW - timedelta(seconds=60)))
    a = plant(w, forged(ident, "park", sp))
    assert history_row(w, ident, a)["applied"]
    rec = forged(ident, "priority", sp)
    rec["value"], rec["evidence"]["line"] = 5, f"{ident} 5"
    b = plant(w, rec)                                                       # the same record, another act
    row = history_row(w, ident, b)
    assert not row["applied"] and row["code"] == "CONFLICT" and shown(w, ident)["priority"] is None


def test_the_writer_takes_session_turn_and_time_from_the_record(w):
    ident = new(w, "alpha")
    got = person(w, ident, "park")
    rec = json.loads(w.path.read_text(encoding="utf-8").splitlines()[-1])
    data = open(rec["evidence"]["span"]["path"], "rb").read()
    o, n = rec["evidence"]["span"]["offset"], rec["evidence"]["span"]["length"]
    record = json.loads(data[o:o + n])
    assert got["applied"] and rec["evidence"]["turn"] == record["uuid"] and rec["evidence"]["session"] == "s1"
    assert rec["evidence"]["turn_at"] == record["timestamp"][:19] + "Z"


def test_the_writer_refuses_an_old_record_even_when_the_hook_says_the_turn_is_fresh(w):
    ident = new(w, "alpha")
    say(w, f"{ident} park", record=transcript_record(f"{ident} park", session="s1", turn="t1",
                                                     at=NOW - timedelta(days=7)))
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "park"})
    assert w.state()["items"][ident]["state"] == "backlog"


def test_the_writer_refuses_a_record_of_another_session(w):
    ident = new(w, "alpha")
    say(w, f"{ident} park", record=transcript_record(f"{ident} park", session="s-other", turn="t1",
                                                     at=NOW - timedelta(seconds=60)))
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "park"})
