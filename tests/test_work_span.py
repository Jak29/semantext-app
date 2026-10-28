"""The person's act, checked again when read (PM-DESIGN, decided 24 October, A1). At write time the kernel records the
transcript span of the person's turn (path, offset, length, sha256); the Work source and the writer's own fold read
that span again, so a person_act planted with made-up evidence, or with none, is "not applied (unverified)", never
state (follow-ups to A1, (b): there are no old-style acts). Each check has a must-pass arm."""
import hashlib
from datetime import timedelta

import pytest

from semantext.sources import work
from semantext.work.turns import Turn
from work_kit import NOW, P, make, new, person, plant, refused, say, stamp, to_doing, transcript_record, transcripts


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def page(w):
    return work.load({"_home": str(w.home), "transcripts": [str(transcripts(w.home))]}, now=NOW, projects={P, "atlas"})


def shown(w, ident):
    return next(i for i in page(w)["items"] if i["id"] == ident)


def history_row(w, ident, seq):
    return next(e for e in shown(w, ident)["history"] if e["seq"] == seq)


def act(ident, what, span, line=None, frm=None):
    rec = {"event": "person_act", "id": ident, "act": what, "who": "person", "assurance": "bound",
           "evidence": {"session": "s1", "turn": "t9", "turn_at": stamp(NOW - timedelta(seconds=60)),
                        "line": line or f"{ident} {what}", **({"span": span} if span is not None else {})}}
    if frm:
        rec["from"] = frm
    return rec


def a_span(path, data=None, offset=0, length=None, sha=None):
    data = data if data is not None else path.read_bytes()[offset:offset + (length or 0)]
    return {"path": str(path), "offset": offset, "length": length if length is not None else len(data),
            "sha256": sha or hashlib.sha256(data).hexdigest()}


# ---- an act the kernel wrote is checked and holds --------------------------------------------------------------------
def test_an_act_the_kernel_wrote_is_verified_from_its_span_and_applied(w):
    ident = new(w, "alpha")
    seq = person(w, ident, "park")["seq"]
    row = history_row(w, ident, seq)
    assert row["applied"] and row["check"] == "verified" and shown(w, ident)["state"] == "parked"


# ---- planted acts: made-up evidence never becomes state --------------------------------------------------------------
def test_a_planted_act_whose_span_bytes_are_not_the_recorded_ones_is_not_applied(w):
    ident = new(w, "alpha")
    say(w, "hello")                                                       # a real transcript, a real record in it
    path = transcripts(w.home) / "s1.jsonl"
    seq = plant(w, act(ident, "park", a_span(path, length=20, sha="0" * 64)))
    row = history_row(w, ident, seq)
    assert not row["applied"] and row["code"] == "UNVERIFIED" and "not applied (unverified)" in row["reason"]
    assert shown(w, ident)["state"] == "backlog" and w.state()["items"][ident]["state"] == "backlog"


def test_a_planted_act_whose_span_holds_another_act_is_not_applied(w):
    ident = new(w, "alpha")
    say(w, f"{ident} next")                                               # his real turn: next, never park
    t = w.turns_.by["s1"]
    data = (transcripts(w.home) / "s1.jsonl").read_bytes()[t.offset:t.offset + t.length]
    seq = plant(w, act(ident, "park", a_span(transcripts(w.home) / "s1.jsonl", data, t.offset, t.length)))
    row = history_row(w, ident, seq)
    assert row["code"] == "UNVERIFIED" and ("another act" in row["reason"] or "do not name" in row["reason"])
    assert shown(w, ident)["state"] == "backlog"


def test_a_planted_act_whose_span_is_outside_the_transcript_roots_is_not_applied(w, tmp_path):
    ident = new(w, "alpha")
    outside = tmp_path / "elsewhere.jsonl"
    import json
    data = json.dumps(transcript_record(f"{ident} park", session="s1", turn="t9",
                                        at=NOW - timedelta(seconds=60))).encode("utf-8")
    outside.write_bytes(data + b"\n")
    seq = plant(w, act(ident, "park", a_span(outside, data, 0, len(data))))
    row = history_row(w, ident, seq)
    assert row["code"] == "UNVERIFIED" and "transcript roots" in row["reason"]
    inside = transcripts(w.home) / "s9.jsonl"                               # must pass: the same bytes inside a root
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_bytes(data + b"\n")
    seq2 = plant(w, act(ident, "park", a_span(inside, data, 0, len(data))))
    assert history_row(w, ident, seq2)["check"] == "verified" and shown(w, ident)["state"] == "parked"


@pytest.mark.parametrize("bad", [{"offset": -1}, {"length": 0}, {"length": 256 * 1024 + 1}, {"offset": "0"},
                                 {"path": "relative.jsonl"}], ids=["negative", "empty", "too-long", "text", "relative"])
def test_a_span_of_the_wrong_shape_is_never_read_and_is_unverified(w, bad):
    ident = new(w, "alpha")
    say(w, f"{ident} park")
    t = w.turns_.by["s1"]
    good = a_span(transcripts(w.home) / "s1.jsonl", None, t.offset, t.length)
    seq = plant(w, act(ident, "park", {**good, **bad}))
    assert history_row(w, ident, seq)["code"] == "UNVERIFIED"


# ---- no old-style acts (PM-DESIGN, follow-ups to A1, (b)): an act with no span is unverified, never state ----------
def test_an_act_with_no_span_is_not_applied_unverified(w):
    ident = to_doing(w)
    seq = plant(w, act(ident, "done", None, frm="doing"))
    row = history_row(w, ident, seq)
    assert not row["applied"] and row["code"] == "UNVERIFIED" and "not applied (unverified)" in row["reason"]
    got = shown(w, ident)
    assert got["state"] == "doing" and w.state()["items"][ident]["state"] == "doing"
    assert "re-checkable" not in str(page(w))
    word = to_doing(w)                                                      # must pass: a checked word says so
    person(w, word, "done", frm="doing")
    assert shown(w, word)["status_word"] == "done (your word)"


def test_the_page_never_says_not_re_checkable():
    from pathlib import Path
    import semantext
    root = Path(semantext.__file__).parent
    said = [p.name for p in list(root.rglob("*.py")) + list((root / "static" / "v2").glob("*.js"))
            if "re-checkable" in p.read_text(encoding="utf-8")]
    assert said == []


# ---- the writer: a new act carries its span, or is not written ---------------------------------------------------------
def test_the_writer_refuses_a_turn_that_names_no_transcript_span(w):
    ident = new(w, "alpha")
    w.turns_.by["s1"] = Turn("s1", "t1", stamp(NOW - timedelta(seconds=60)), f"{ident} park", "own", "transcript")
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "park"})
    assert w.state()["items"][ident]["state"] == "backlog"


def test_the_writer_refuses_a_span_whose_record_is_not_the_persons_own_turn(w):
    ident = new(w, "alpha")
    say(w, f"{ident} park", record=transcript_record(f"{ident} park", origin="relayed"))
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "park"})
    say(w, f"{ident} park", turn="t2")                                      # must pass: his own record
    got = w.person_act("s1", {"id": ident, "act": "park"})
    assert got["item"]["state"] == "parked"
    ev = w.state()["items"][ident]
    assert ev["state"] == "parked"


# ---- the writer's cached verdicts notice a transcript that changes (size or mtime) ------------------------------------
def _cached_act(w):
    ident = new(w, "alpha")
    seq = person(w, ident, "park")["seq"]
    st = w.state()                                                       # the verdict is now in the writer's cache
    assert next(e for e in st["events"] if e["seq"] == seq)["check"] == "verified"
    return ident, seq, transcripts(w.home) / "s1.jsonl"


def _row(w, seq):
    return next(e for e in w.state()["events"] if e["seq"] == seq)


def test_a_transcript_edited_in_place_is_checked_again_and_the_act_falls(w):
    import os
    ident, seq, t = _cached_act(w)
    data = bytearray(t.read_bytes())
    data[data.index(b"park")] = ord("b")                                   # same size, other bytes: "bark"
    st = os.stat(t)
    t.write_bytes(bytes(data))
    os.utime(t, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))              # its mtime moves, as an edit's does
    r = _row(w, seq)
    assert r["code"] == "UNVERIFIED" and w.state()["items"][ident]["state"] == "backlog"


def test_an_equal_length_edit_with_its_mtime_put_back_is_still_seen(w):
    # round 4, decision 7: the cache compares the span's sha256 too, not only (size, mtime)
    import os
    ident, seq, t = _cached_act(w)
    st = os.stat(t)
    data = bytearray(t.read_bytes())
    data[data.index(b"park")] = ord("b")
    t.write_bytes(bytes(data))
    os.utime(t, ns=(st.st_atime_ns, st.st_mtime_ns))                       # the mtime restored: (size, mtime) agree
    r = _row(w, seq)
    assert r["code"] == "UNVERIFIED" and w.state()["items"][ident]["state"] == "backlog"


def test_a_transcript_cut_short_is_checked_again_and_the_act_stays_on_the_writers_attestation(w):
    # round 4, decision 4: a span that can no longer be read (cut, moved, linked) leaves an act the writer applied
    # applied, as "attested"; bytes that read and differ (the edit above) still make it fall
    ident, seq, t = _cached_act(w)
    t.write_bytes(t.read_bytes()[:10])
    r = _row(w, seq)
    assert r["applied"] and r["check"] == "attested" and w.state()["items"][ident]["state"] == "parked"


def test_partner_a_transcript_that_only_grows_keeps_its_acts(w):
    ident, seq, t = _cached_act(w)
    with open(t, "ab") as f:
        f.write(b'{"type": "assistant", "message": {"content": "later"}}\n')
    r = _row(w, seq)
    assert r["applied"] and r["check"] == "verified" and w.state()["items"][ident]["state"] == "parked"