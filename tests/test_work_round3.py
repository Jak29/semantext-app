"""Review round 3 of the Work system (G6), its low findings on the kernel's own modules: the chain's form, the door
checks, the person's act lines, the fold's clock note, the writer's reads and its rate limit, and the command line.
Each is a must-refuse with its must-pass partner."""
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from semantext.work.chain import GENESIS, line_of, parse_line, seal, walk
from semantext.work.turns import turn_names
from work_kit import P, bound, item, lines, make, new, plant, refused, row, stamp

TOKEN = "ghp_" + "a1" * 15


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def sealed(seq=1, prev=GENESIS, **over):
    rec = {"v": 1, "event": "comment", "id": f"W-{P}-1", "text": "x", "who": "alpha", "assurance": "bound",
           "channel": "mcp", "at": "2026-10-24T14:00:00Z", **over}
    return seal(rec, seq, prev)


# ---- 13: the version is the integer 1, never true or 1.0 -----------------------------------------------------------
@pytest.mark.parametrize("v", ["true", "1.0"])
def test_a_version_that_is_not_the_integer_one_is_not_a_record(v):
    text = line_of(sealed())
    assert parse_line(text)[0] is not None                                   # must pass: v is 1
    forged = text.replace('"v":1', '"v":' + v, 1)
    assert forged != text
    rec, why, _ = parse_line(forged)
    assert rec is None and "version" in why


# ---- 14: a named record whose prev is not text is a broken chain, never a TypeError ----------------------------------
@pytest.mark.parametrize("prev", [["x"], {"a": 1}])
def test_a_named_record_whose_prev_is_not_text_is_a_broken_chain(prev):
    first = sealed()
    rec = sealed(seq=2, prev=prev)                   # the head names it, so the walk steps back through its prev
    got = walk([line_of(first), line_of(rec)], None, {"seq": 2, "hash": rec["hash"]})
    assert got["intact"] is False and any(p["kind"] == "broken" for p in got["problems"])
    good = sealed(seq=2, prev=first["hash"])
    assert walk([line_of(first), line_of(good)], None, {"seq": 2, "hash": good["hash"]})["intact"] is True   # pass


# ---- 15: a claimed extra field and the person's value get the secret-shape scan ---------------------------------------
def test_a_token_in_a_claimed_extra_field_is_refused_and_nothing_is_kept(w):
    ident = new(w, "alpha")
    refused("MALFORMED", w.write, bound("alpha"), "comment", {"id": ident, "text": "ok", "token": TOKEN})
    refused("MALFORMED", w.write, bound("alpha"), "comment", {"id": ident, "text": "ok", "aside": {"k": [TOKEN]}})
    assert len(lines(w)) == 1
    assert w.write(bound("alpha"), "comment", {"id": ident, "text": "ok", "note": "plain"})["applied"]   # must pass


def test_the_fold_still_reads_a_claimed_field_without_the_costly_scan(w):
    ident = new(w, "alpha")
    seq = plant(w, {"event": "comment", "id": ident, "text": "ok", "claimed_note": TOKEN, "who": "alpha",
                    "assurance": "bound"})
    assert row(w, seq)["applied"] is True        # the scan is the writer's, before anything is kept; the fold reads


# ---- 16: an edit that changes nothing is refused, never "recorded" ----------------------------------------------------
@pytest.mark.parametrize("req", [{}, {"titel": "x"}], ids=["nothing", "misspelt"])
def test_an_edit_with_no_editable_field_is_refused(w, req):
    ident = new(w, "alpha")
    refused("MALFORMED", w.write, bound("alpha"), "edit", {"id": ident, **req})
    assert len(lines(w)) == 1
    assert w.write(bound("alpha"), "edit", {"id": ident, "title": "x"})["item"]["title"] == "x"   # must pass


# ---- 9: the seat in "assign <seat>" is matched exactly, case included --------------------------------------------------
def test_the_seat_in_an_assign_line_is_matched_in_its_own_case():
    ident = f"W-{P}-1"
    assert turn_names(f"{ident} assign Rowan", ident, "assign", "Rowan") == f"{ident} assign Rowan"
    assert turn_names(f"{ident} ASSIGN Rowan", ident, "assign", "Rowan") == f"{ident} assign Rowan"
    assert turn_names(f"{ident} assign rowan", ident, "assign", "Rowan") is None
    assert turn_names(f"{ident} assign ROWAN", ident, "assign", "Rowan") is None
    assert turn_names(f"{ident} DONE", ident, "done") == f"{ident} done"     # must pass: the choice word in any case


# ---- 17: a stamp far ahead does not make every later record "a clock set back" -----------------------------------------
def test_a_stamp_far_ahead_does_not_turn_the_clock_note_into_noise(w):
    ident = new(w, "alpha")
    ahead = plant(w, {"event": "comment", "id": ident, "text": "x", "who": "alpha", "assurance": "bound",
                      "at": "2099-01-01T00:00:00Z"})
    later = w.write(bound("alpha"), "comment", {"id": ident, "text": "an ordinary record"})["seq"]
    assert "ahead" in row(w, ahead)["clock"]
    assert row(w, later).get("clock") is None
    back = plant(w, {"event": "comment", "id": ident, "text": "y", "who": "alpha", "assurance": "bound",
                     "at": stamp(w.clock_.now - timedelta(days=1))})
    assert "set back" in row(w, back)["clock"]                                # must refuse: a real set-back is said


# ---- 11: the rate limit counts the last minute, however many other actors write ----------------------------------------
def test_the_rate_limit_counts_the_last_minute_not_the_last_few_events(tmp_path):
    w = make(tmp_path / "home", rate=2)
    ident = new(w, "alpha")
    w.write(bound("alpha"), "comment", {"id": ident, "text": "two"})
    for k in range(14):                              # more than (rate + 1) * 4 events by others, in the same minute
        w.write(bound(f"seat{k}"), "comment", {"id": ident, "text": "busy"})
    refused("RATE_LIMIT", w.write, bound("alpha"), "comment", {"id": ident, "text": "three"})
    w.clock_.now += timedelta(seconds=61)
    assert w.write(bound("alpha"), "comment", {"id": ident, "text": "a minute on"})["applied"]   # must pass


# ---- 12: a read never sees the head of a write the log it read does not hold ------------------------------------------
def test_a_write_landing_between_the_reads_never_shows_a_sound_store_as_broken(w):
    ident = new(w, "alpha")
    real = w.path
    fired = []

    class Racing(type(real)):
        def read_bytes(self):
            data = super().read_bytes()
            if not fired:                           # one write lands just after the log is read, before the head
                fired.append(1)
                w.path = real
                w.write(bound("alpha"), "comment", {"id": ident, "text": "landed between"})
                w.path = racing
            return data

    racing = Racing(real)
    w.path = racing
    st = w.state()
    w.path = real
    assert fired and st["intact"] is True and not any(p["kind"] == "broken" for p in st["problems"])
    assert w.state()["intact"] is True                                         # must pass: read again, whole

# ---- the attack on the Work page, A3: the record's actor is checked as the writer checks it ---------------------------
@pytest.mark.parametrize("who", ["alpha\u202e", "al\npha", "a" * 41, "../alpha", 7], ids=["bidi", "newline", "long",
                                                                                         "path", "not-text"])
def test_a_record_whose_actor_is_not_a_seat_name_is_malformed_never_applied(w, who):
    ident = new(w, "alpha")
    seq = plant(w, {"event": "comment", "id": ident, "text": "hi", "who": who, "assurance": "claimed"})
    assert row(w, seq)["code"] == "MALFORMED" and item(w, ident)["comments"] == []
    good = plant(w, {"event": "comment", "id": ident, "text": "hi", "who": "beta", "assurance": "claimed"})
    assert row(w, good)["applied"] is True                                        # must pass

# ---- 10: a line left past the head when the head write fails is adopted by the next append, and only that line --------
def _failing_head_once(monkeypatch, w):
    from semantext import store
    real, failed = store.write_atomic, []

    def write(target, data):
        if str(target) == str(w.head_path) and not failed:
            failed.append(1)
            raise PermissionError("the head is held by a reader")       # Windows refusing the swap for over a second
        return real(target, data)
    monkeypatch.setattr(store, "write_atomic", write)
    return failed


def test_a_line_whose_head_write_failed_is_adopted_by_the_next_append(w, monkeypatch):
    ident = new(w, "alpha")
    failed = _failing_head_once(monkeypatch, w)
    with pytest.raises(PermissionError):
        w.write(bound("alpha"), "comment", {"id": ident, "text": "the head failed after me"})
    assert failed and len(lines(w)) == 2
    assert w.state()["events"][-1]["on_chain"] is False                     # until the next append adopts it
    nxt = w.write(bound("alpha"), "comment", {"id": ident, "text": "next"})
    st = w.state()
    assert nxt["seq"] == 3 and st["intact"] and all(e["on_chain"] for e in st["events"])
    assert [c["text"] for c in st["items"][ident]["comments"]] == ["the head failed after me", "next"]
    pending = json.loads(w.pending_path.read_text(encoding="utf-8"))           # now the newest line's own, done with
    assert pending["hash"] == json.loads(w.head_path.read_text(encoding="utf-8"))["hash"]


def test_a_create_whose_head_write_failed_keeps_its_owner_and_is_never_minted_twice(w, monkeypatch):
    _failing_head_once(monkeypatch, w)
    with pytest.raises(PermissionError):
        new(w, "alpha", title="First")
    again = new(w, "alpha", title="Second")
    st = w.state()
    assert again == f"W-{P}-2" and st["items"][f"W-{P}-1"]["owner"] == "alpha"


def test_any_other_line_past_the_head_is_never_adopted(w):
    ident = new(w, "alpha")
    seq = plant(w, {"event": "comment", "id": ident, "text": "planted", "who": "alpha", "assurance": "bound"},
                move_head=False)
    head = w.head_path.read_text(encoding="utf-8")
    import json as _json
    w.pending_path.write_text(_json.dumps({"hash": "f" * 64, "head": _json.loads(head)}), encoding="utf-8")
    nxt = w.write(bound("alpha"), "comment", {"id": ident, "text": "the writer's own"})
    st = w.state()
    planted = next(e for e in st["events"] if e["line"] == 2)
    assert nxt["seq"] == seq and st["intact"] and planted["on_chain"] is False and planted["effective"] == "claimed"
    assert next(e for e in st["events"] if e["line"] == 3)["on_chain"] is True             # the writer's own line
    assert w.pending_path.read_text(encoding="utf-8") != "{}"                 # the forged record was dropped, then
                                                                               # the writer's own pending one written