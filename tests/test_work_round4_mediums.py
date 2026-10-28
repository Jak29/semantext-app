"""Review round 4, the medium findings (decision 4): a verified act stays applied; a verdict made while the transcript
could not be read is never kept; only a bound link holds an item, and a link can be undone; a request key names its
item. Each is a must-refuse with its must-pass partner."""
import hashlib
import json
import os
from datetime import timedelta

import pytest

from semantext.sources import work
from semantext.work import span
from work_kit import (NOW, P, bound, claimed, make, new, person, plant, refused, stamp, to_doing, transcript_record,
                      transcripts)

J = "J-20261020-1"


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def page(w):
    return work.load({"_home": str(w.home), "transcripts": [str(transcripts(w.home))]}, now=NOW, projects={P, "atlas"})


def shown(w, ident):
    return next(i for i in page(w)["items"] if i["id"] == ident)


def act_row(st, seq):
    return next(e for e in st["events"] if e["seq"] == seq)


def put(w, record, name="s1"):
    path = transcripts(w.home) / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(record).encode("utf-8")
    offset = path.stat().st_size if path.exists() else 0
    with open(path, "ab") as f:
        f.write(data + b"\n")
    return {"path": str(path), "offset": offset, "length": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def planted_act(w, ident, what="park"):
    """A person_act chained by something other than the writer, whose span is a real, fresh turn of his: it holds
    while its transcript reads, and carries no attestation of the writer's."""
    sp = put(w, transcript_record(f"{ident} {what}", session="s1", turn="t9", at=NOW - timedelta(seconds=60)))
    return plant(w, {"event": "person_act", "id": ident, "act": what, "who": "person", "assurance": "bound",
                     "evidence": {"session": "s1", "turn": "t9", "turn_at": stamp(NOW - timedelta(seconds=60)),
                                  "line": f"{ident} {what}", "span": sp}}), sp


# ---- 2b: a verified act stays applied when its transcript is linked, moved or rotated --------------------------------
@pytest.mark.parametrize("how", ["hard-link", "moved", "cut"])
def test_an_act_the_writer_applied_stays_applied_when_its_transcript_moves(w, tmp_path, how):
    ident = new(w, "alpha")
    seq = person(w, ident, "park")["seq"]
    t = transcripts(w.home) / "s1.jsonl"
    if how == "hard-link":
        os.link(t, tmp_path / "backup.jsonl")
    elif how == "moved":
        os.replace(t, tmp_path / "rotated.jsonl")
    else:
        t.write_bytes(b"")
    fresh = make(w.home)
    st = fresh.state()
    assert st["items"][ident]["state"] == "parked" and act_row(st, seq)["applied"]
    assert act_row(st, seq)["check"] == "attested"
    assert shown(w, ident)["state"] == "parked"
    assert w.state()["items"][ident]["state"] == "parked"                  # the writer that wrote it, too


def test_partner_an_act_the_writer_never_attested_falls_when_its_transcript_cannot_be_read(w, tmp_path):
    ident = new(w, "alpha")
    seq, sp = planted_act(w, ident)
    assert make(w.home).state()["items"][ident]["state"] == "parked"       # it holds while the transcript reads
    os.link(sp["path"], tmp_path / "backup.jsonl")
    st = make(w.home).state()
    assert st["items"][ident]["state"] == "backlog" and act_row(st, seq)["code"] == "UNVERIFIED"


def test_partner_an_attested_act_whose_bytes_changed_still_falls(w):
    ident = new(w, "alpha")
    seq = person(w, ident, "park")["seq"]
    t = transcripts(w.home) / "s1.jsonl"
    data = bytearray(t.read_bytes())
    data[data.index(b"park")] = ord("b")
    t.write_bytes(bytes(data))
    st = make(w.home).state()
    assert st["items"][ident]["state"] == "backlog" and act_row(st, seq)["code"] == "UNVERIFIED"


def test_partner_an_attestation_off_the_chain_counts_for_nothing(w, tmp_path):
    ident = new(w, "alpha")
    sp = {"path": str(tmp_path / "gone.jsonl"), "offset": 0, "length": 10, "sha256": "a" * 64}
    seq = plant(w, {"event": "person_act", "id": ident, "act": "park", "who": "person", "assurance": "bound",
                    "evidence": {"session": "s1", "turn": "t9", "turn_at": stamp(NOW - timedelta(seconds=60)),
                                 "line": f"{ident} park", "span": sp, "attested": "a" * 64}}, move_head=False)
    st = w.state()
    assert st["items"][ident]["state"] == "backlog" and not act_row(st, seq)["applied"]


# ---- 4: a verdict made while the transcript could not be read is never kept -------------------------------------------
def test_a_failed_read_is_not_kept_as_the_verdict(w, monkeypatch):
    ident = new(w, "alpha")
    seq, _ = planted_act(w, ident)
    real, fails = span.read_span, [1]

    def flaky(*a, **k):
        if fails:
            fails.pop()
            return None                                                     # the transcript locked, once
        return real(*a, **k)
    monkeypatch.setattr(span, "read_span", flaky)
    first = w.state()
    assert act_row(first, seq)["code"] == "UNVERIFIED"
    again = w.state()                                                       # the same writer, its cache warm
    assert again["items"][ident]["state"] == "parked" and act_row(again, seq)["check"] == "verified"


# ---- 4a: only a bound link holds; a claimed or off-chain one is a proposal, and a link can be undone -------------------
def test_a_claimed_link_to_a_parked_decision_holds_nothing_and_shows_as_a_proposal(tmp_path):
    w = make(tmp_path / "home", parked={J})
    ident = new(w, "alpha", links=[{"type": "commit", "ref": "abc1234"}])
    person(w, ident, "next", frm="backlog")
    w.write(claimed("someone"), "link", {"id": ident, "link": {"type": "decision", "ref": J}})
    got = w.state()["items"][ident]
    assert got["held_by"] == [] and got["hold_proposed"] == [J]
    w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    assert w.state()["items"][ident]["state"] == "doing"


def test_an_off_chain_link_holds_nothing(tmp_path):
    w = make(tmp_path / "home", parked={J})
    ident = new(w, "alpha", links=[{"type": "commit", "ref": "abc1234"}])
    person(w, ident, "next", frm="backlog")
    plant(w, {"event": "link", "id": ident, "link": {"type": "decision", "ref": J}, "who": "alpha",
              "assurance": "bound"}, move_head=False)
    w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    assert w.state()["items"][ident]["state"] == "doing"


def test_partner_a_bound_link_holds_and_its_unlink_releases_it(tmp_path):
    w = make(tmp_path / "home", parked={J})
    ident = new(w, "alpha", links=[{"type": "commit", "ref": "abc1234"}])
    person(w, ident, "next", frm="backlog")
    w.write(bound("beta"), "link", {"id": ident, "link": {"type": "decision", "ref": J}})
    assert w.state()["items"][ident]["held_by"] == [J]
    refused("HELD", w.write, bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    # a claimed unlink never undoes a bound link: it is a proposal, shown and not applied
    got = w.write(claimed("someone"), "unlink", {"id": ident, "link": {"type": "decision", "ref": J}})
    assert got["proposal"] and not got["applied"] and w.state()["items"][ident]["held_by"] == [J]
    w.write(bound("beta"), "unlink", {"id": ident, "link": {"type": "decision", "ref": J}})
    assert w.state()["items"][ident]["held_by"] == []
    w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    assert w.state()["items"][ident]["state"] == "doing"


def test_a_claimed_unlink_undoes_a_claimed_link(w):
    ident = new(w, "alpha")
    w.write(claimed("someone"), "link", {"id": ident, "link": {"type": "post", "ref": "P100"}})
    w.write(claimed("other"), "unlink", {"id": ident, "link": {"type": "post", "ref": "P100"}})
    assert w.state()["items"][ident]["links"] == []
    refused("UNKNOWN_ID", w.write, bound("alpha"), "unlink", {"id": ident, "link": {"type": "post", "ref": "P100"}})


# ---- 2c: a request key names its item -----------------------------------------------------------------------------------
def test_a_repeated_key_on_another_item_is_a_conflict_never_the_first_answer(w):
    a, b = new(w, "alpha"), new(w, "alpha")
    w.write(bound("alpha"), "comment", {"id": a, "text": "same", "request_key": "k1"})
    refused("CONFLICT", w.write, bound("alpha"), "comment", {"id": b, "text": "same", "request_key": "k1"})
    again = w.write(bound("alpha"), "comment", {"id": a, "text": "same", "request_key": "k1"})   # must pass: a repeat
    assert again["repeat"] and again["id"] == a


def test_partner_a_repeated_create_is_still_the_first_answer(w):
    one = w.write(bound("alpha"), "create", {"project": P, "title": "T", "request_key": "c1"})
    two = w.write(bound("alpha"), "create", {"project": P, "title": "T", "request_key": "c1"})
    assert two["repeat"] and two["id"] == one["id"]
