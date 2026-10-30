"""The authority arms of the attack on the work design (A1 to A11), each a must-refuse with its must-pass partner. A
refusal is checked by its code; where the writer refuses, the same event planted in the file (on the chain, the head
moved too, as a program that can write both would) is checked "not applied" by the fold, which re-applies the table."""
import os
from datetime import timedelta

import pytest

from semantext import jsonread
from semantext.work.turns import TranscriptTurns, deep_link, parse_deep_link
from work_kit import P, bound, claimed, item, lines, make, new, person, plant, refused, row, say, to_doing


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


# ---- A1: an agent moves another seat's item ----------------------------------------------------------------------
def test_a1_an_agent_cannot_move_another_seats_item(w):
    ident = new(w, "alpha")
    person(w, ident, "next", frm="backlog")
    refused("NOT_AUTHORIZED", w.write, bound("beta"), "move", {"id": ident, "from": "next", "to": "doing"})
    seq = plant(w, {"event": "move", "id": ident, "from": "next", "to": "doing", "who": "beta", "assurance": "bound"})
    assert row(w, seq)["code"] == "NOT_AUTHORIZED" and item(w, ident)["state"] == "next"


def test_a1_partner_the_owner_moves_its_item(w):
    ident = new(w, "alpha")
    person(w, ident, "next", frm="backlog")
    assert w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})["item"]["state"] == "doing"


# ---- A2: assigning oneself another seat's item, or assigning a third seat -----------------------------------------
def test_a2_an_agent_cannot_take_an_owned_item_or_assign_a_third_seat(w):
    ident = new(w, "alpha")
    refused("NOT_AUTHORIZED", w.write, bound("beta"), "assign_self", {"id": ident})
    refused("NOT_AUTHORIZED", w.write, bound("beta"), "assign_self", {"id": ident, "owner": "gamma"})
    r = w.write(bound("beta"), "propose_reassign", {"id": ident, "to_seat": "gamma"})
    assert item(w, ident)["owner"] == "alpha" and item(w, ident)["proposals"][0]["what"] == "reassign" and r["applied"]
    seq = plant(w, {"event": "assign_self", "id": ident, "who": "beta", "assurance": "bound"})
    assert row(w, seq)["code"] == "NOT_AUTHORIZED" and item(w, ident)["owner"] == "alpha"


def test_a2_partner_a_seat_takes_an_unassigned_item(w):
    ident = new(w, actor=claimed("someone"))          # a claimed create names no owner
    assert item(w, ident)["owner"] is None
    assert w.write(bound("beta"), "assign_self", {"id": ident})["item"]["owner"] == "beta"


# ---- A3: parked by anyone but the person ---------------------------------------------------------------------------
def test_a3_no_agent_act_sets_or_leaves_parked(w):
    ident = new(w, "alpha")
    refused("PARKED", w.write, bound("alpha"), "move", {"id": ident, "from": "backlog", "to": "parked"})
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "edit", {"id": ident, "parked": True})
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "create", {"project": P, "title": "x", "state": "parked"})
    refused("NOT_AUTHORIZED", w.import_item, bound("alpha"), {"project": P, "title": "x", "state": "parked"})
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "person_act", {"id": ident, "act": "park"})
    # a direct line: the person's act with no evidence of a turn, and a create carrying a state
    seq = plant(w, {"event": "person_act", "id": ident, "act": "park", "who": "person", "assurance": "bound"})
    seq2 = plant(w, {"event": "create", "id": f"W-{P}-9", "project": P, "title": "y", "state": "parked",
                     "who": "alpha", "assurance": "bound"})
    assert row(w, seq)["code"] == "NOT_AUTHORIZED" and row(w, seq2)["code"] == "MALFORMED"
    assert item(w, ident)["state"] == "backlog" and item(w, f"W-{P}-9") is None
    person(w, ident, "park")
    refused("PARKED", w.write, bound("alpha"), "move", {"id": ident, "from": "parked", "to": "backlog"})


def test_a3_partner_the_persons_own_act_parks_and_back_returns_where_it_left(w):
    ident = to_doing(w)
    assert person(w, ident, "park")["item"]["state"] == "parked"
    assert person(w, ident, "unpark")["item"]["state"] == "doing"


# ---- A4: priority ----------------------------------------------------------------------------------------------
def test_a4_an_agent_never_sets_or_changes_priority(w):
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "create", {"project": P, "title": "x", "priority": 1})
    ident = new(w, "alpha")
    assert item(w, ident)["priority"] is None
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "edit", {"id": ident, "priority": 1})
    seq = plant(w, {"event": "person_act", "id": ident, "act": "priority", "value": 1, "who": "alpha",
                    "assurance": "bound"})
    assert row(w, seq)["code"] == "NOT_AUTHORIZED" and item(w, ident)["priority"] is None


def test_a4_partner_the_person_reprioritises(w):
    ident = new(w, "alpha")
    assert person(w, ident, "priority", value=3)["item"]["priority"] == 3


# ---- A5: edit ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("field,value", [("state", "done"), ("owner", "beta"), ("priority", 1),
                                         ("epic", f"W-{P}-1"), ("parked", True),
                                         ("links", [{"type": "commit", "ref": "abc1234"}]), ("proof", "x"),
                                         ("clauses", [])])
def test_a5_edit_carries_only_title_text_and_kind(w, field, value):
    ident = new(w, "alpha")
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "edit", {"id": ident, field: value})
    assert len(lines(w)) == 1


def test_a5_edit_of_another_seats_item_is_refused(w):
    ident = new(w, "alpha")
    refused("NOT_AUTHORIZED", w.write, bound("beta"), "edit", {"id": ident, "title": "mine now"})


def test_a5_partner_the_owner_edits_title_text_and_kind(w):
    ident = new(w, "alpha")
    got = w.write(bound("alpha"), "edit", {"id": ident, "title": "Better", "text": "why", "kind": "bug"})["item"]
    assert (got["title"], got["text"], got["kind"]) == ("Better", "why", "bug")


# ---- A6: done needs proof (the clause arms are in test_work_review.py) -----------------------------------------------
def test_a6_no_agent_moves_an_item_to_done(w):
    ident = to_doing(w)
    refused("BAD_EDGE", w.write, bound("alpha"), "move", {"id": ident, "from": "doing", "to": "done"})
    w.write(bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": "beta"})
    for who in ("alpha", "beta", "gamma"):
        refused("BAD_EDGE", w.write, bound(who), "move", {"id": ident, "from": "review", "to": "done"})


# ---- A7: review names its reviewer; the author never approves --------------------------------------------------------
def test_a7_review_needs_a_reviewer_who_is_not_the_author(w):
    ident = to_doing(w)
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review"})
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "move",
            {"id": ident, "from": "doing", "to": "review", "reviewer": "alpha"})
    w.write(bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": "beta"})
    refused("NOT_AUTHORIZED", w.write, bound("gamma"), "move", {"id": ident, "from": "review", "to": "doing"})
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "move", {"id": ident, "from": "review", "to": "doing"})


def test_a7_partner_the_reviewer_sends_it_back_and_the_persons_word_makes_it_done(w):
    ident = to_doing(w)
    w.write(bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": "beta"})
    assert w.write(bound("beta"), "move", {"id": ident, "from": "review", "to": "doing"})["item"]["state"] == "doing"
    got = person(w, ident, "done", frm="doing")["item"]
    assert got["state"] == "done" and got["done_by"] == "word"


# ---- A8: caller-set actor and time fields are refused, never ignored -------------------------------------------------
@pytest.mark.parametrize("field", ["who", "at", "seq", "evidence", "as", "by", "time", "assurance", "seat", "session",
                                   "transcript", "turn"])
def test_a8_a_caller_set_actor_or_time_field_is_refused(w, field):
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "create", {"project": P, "title": "x", field: "person"})
    assert lines(w) == []


def test_a8_a_caller_set_id_on_create_is_refused(w):
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "create", {"project": P, "title": "x", "id": f"W-{P}-77"})



def test_a8_partner_the_same_call_without_them_and_an_extra_is_kept_as_claimed(w):
    r = w.write(bound("alpha"), "create", {"project": P, "title": "x", "note": "hello"})
    assert r["applied"] and '"claimed_note":"hello"' in lines(w)[0]
    assert "note" not in item(w, r["id"]) and item(w, r["id"])["creator"] == "alpha"


# ---- A9: the person's act by chat ------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Is W-semantext-1 next?",                              # a question
    "W-semantext-1 next\nthanks",                          # an act and something else: the whole turn names nothing
    "> W-semantext-1 next",                                # a quote
    "W-semantext-1 next please",
    "W-semantext-12 next",                                 # another id that the act's id is a prefix of
    "W-semantext-1 nextt",
    "w-semantext-1 next",                                  # the case of the id
    "W-Semantext-1 next",
    "W-semantext-1\u200b next",                            # a zero-width character
    "W-semantext-1\u00a0next",                             # a no-break space
    "W-semantext-1 next\u2028",                            # a line separator
    "W-semantext-1 n\u0435xt",                           # a look-alike letter (Cyrillic e)
])
def test_a9_a_turn_that_is_not_exactly_the_act_is_undecidable_and_nothing_is_written(w, text):
    ident = new(w, "alpha")
    say(w, text)
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "next", "from": "backlog"})
    assert len(lines(w)) == 1


@pytest.mark.parametrize("origin,basis,code", [("relayed", "transcript", "NOT_AUTHORIZED"),
                                               ("own", "none", "UNDECIDABLE")])
def test_a9_a_relayed_turn_or_one_with_no_transcript_basis_is_refused(w, origin, basis, code):
    ident = new(w, "alpha")
    say(w, f"{ident} next", origin=origin, basis=basis)       # a notice, a scheduled turn, a summary: relayed
    refused(code, w.person_act, "s1", {"id": ident, "act": "next", "from": "backlog"})


def test_a9_the_transcript_and_session_never_come_from_the_caller(w):
    ident = new(w, "alpha")
    say(w, f"{ident} next", session="other")
    for extra in ({"session": "other"}, {"transcript": "C:/x.json"}, {"turn": "t1"}):
        refused("NOT_AUTHORIZED", w.person_act, "s1", {"id": ident, "act": "next", "from": "backlog", **extra})
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "next", "from": "backlog"})   # not this chat


def test_a9_the_same_turn_used_twice_is_refused(w):
    ident = new(w, "alpha")
    say(w, f"{ident} park", turn="once")
    w.person_act("s1", {"id": ident, "act": "park"})
    refused("CONFLICT", w.person_act, "s1", {"id": ident, "act": "park"})


def test_a9_a_turn_older_than_the_window_is_refused_and_the_limit_itself_is_inside(w):
    ident = new(w, "alpha")
    say(w, f"{ident} next", ago=601)
    refused("UNDECIDABLE", w.person_act, "s1", {"id": ident, "act": "next", "from": "backlog"})
    say(w, f"{ident} next", ago=600)
    assert w.person_act("s1", {"id": ident, "act": "next", "from": "backlog"})["item"]["state"] == "next"


def test_a9_a_transcript_record_through_a_link_a_hard_link_or_a_bad_session_is_no_evidence(tmp_path):
    root = tmp_path / "turns"
    root.mkdir()
    good = root / "s1.json"
    good.write_text('{"origin": "own", "basis": "transcript", "text": "x", "turn": "t", "at": "2026-10-24T14:00:00Z"}',
                    encoding="utf-8")
    src = TranscriptTurns(root)
    assert src.turn("s1").origin == "own"                                   # the partner: the hook's own record
    assert src.turn("../s1") is None and src.turn("s1.json") is None and src.turn("") is None
    os.link(good, tmp_path / "elsewhere.json")                              # a second hard link to the record
    assert src.turn("s1") is None
    outside = tmp_path / "agent.json"
    outside.write_text(good.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        os.symlink(outside, root / "s2.json")
    except OSError:
        pytest.skip("this account cannot make a symbolic link")
    assert src.turn("s2") is None


def test_a9_a_transcript_record_nested_too_deeply_is_no_evidence(tmp_path):   # the shared bounded reader
    root = tmp_path / "turns"
    root.mkdir()
    rec = '{"origin": "own", "basis": "transcript", "text": "x", "turn": "t", "at": "2026-10-24T14:00:00Z"'
    deep = "[" * (jsonread.MAX_DEPTH + 1) + "]" * (jsonread.MAX_DEPTH + 1)
    (root / "s1.json").write_text(rec + "}", encoding="utf-8")
    (root / "s2.json").write_text(rec + ', "aside": ' + deep + "}", encoding="utf-8")
    (root / "s3.json").write_text(rec + ', "aside": ' + "[" * 30000 + "]" * 30000 + "}", encoding="utf-8")
    src = TranscriptTurns(root)
    assert src.turn("s1").origin == "own"                                   # the partner: within the bound
    assert src.turn("s2") is None and src.turn("s3") is None


def test_a9_partner_his_own_exact_turn_acts_once(w):
    ident = new(w, "alpha")
    texts = (f"{ident} next", f"{ident}: next.", f"{ident}\tNEXT!", f"W-semantext-99 doing\n{ident} next")
    for k, text in enumerate(texts):
        assert person(w, ident, "next", frm="backlog", text=text, turn=f"go{k}")["item"]["state"] == "next"
        person(w, ident, "backlog", frm="next", turn=f"back{k}")


# ---- A10: the deep link carries an id and nothing else ---------------------------------------------------------------
@pytest.mark.parametrize("url", ["jak-inbox://work/semantext/12/done", "jak-inbox://work/semantext/12?act=park",
                                 "jak-inbox://work/semantext/012", "jak-inbox://work/nowhere/12",
                                 "jak-inbox://work/semantext/12#done", "jak-inbox://work/sem%61ntext/12",
                                 "jak-inbox://work/semantext/12 ", "jak-inbox://work/Semantext/12",
                                 "jak-inbox://work/semantext/1234567", "https://work/semantext/12"])
def test_a10_a_deep_link_with_an_action_or_an_unvalidated_part_is_refused(url):
    refused("MALFORMED", parse_deep_link, url, {P})


def test_a10_partner_a_valid_id_round_trips():
    assert deep_link("W-semantext-12", {P}) == "jak-inbox://work/semantext/12"
    assert parse_deep_link("jak-inbox://work/semantext/12", {P}) == "W-semantext-12"
    refused("MALFORMED", deep_link, "W-semantext-12?done", {P})


# ---- A11: lines the writer did not write; links at the store -------------------------------------------------------
def test_a11_a_line_appended_after_the_head_is_off_the_chain_and_holds_no_rights(w):
    ident = new(w, "alpha")
    seq = plant(w, {"event": "person_act", "id": ident, "act": "park", "who": "person", "assurance": "bound",
                    "evidence": {"session": "s", "turn": "t", "turn_at": "2026-10-24T13:59:00Z",
                                 "line": f"{ident} park"}}, move_head=False)
    r = row(w, seq)
    assert r["on_chain"] is False and r["effective"] == "claimed" and not r["applied"]
    assert item(w, ident)["state"] == "backlog"
    nxt = w.write(bound("alpha"), "comment", {"id": ident, "text": "still mine"})   # the writer chains from its head
    assert nxt["seq"] == seq and w.state()["intact"]


def test_a11_a_planted_bound_line_on_the_chain_is_still_judged_by_the_table(w):
    ident = new(w, "alpha")
    seq = plant(w, {"event": "move", "id": ident, "from": "backlog", "to": "next", "who": "alpha",
                    "assurance": "bound"})
    assert row(w, seq)["code"] == "BAD_EDGE"                                # ranking is the person's, whoever writes


def test_a11_a_junction_or_link_at_the_store_or_a_hard_link_at_the_log_refuses_every_write(tmp_path):
    w = make(tmp_path / "home")
    new(w, "alpha")
    os.link(w.path, tmp_path / "copy.jsonl")
    refused("CONFLICT", new, w, "alpha")
    other = make(tmp_path / "home2")
    real = tmp_path / "real-work"
    real.mkdir()
    other.home.mkdir()
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(real), str(other.dir))
        else:
            os.symlink(real, other.dir)
    except OSError:
        pytest.skip("cannot make a junction or link here")
    refused("CONFLICT", new, other, "alpha")
    assert list(real.iterdir()) == []


def test_a11_partner_a_plain_store_is_written(tmp_path):
    w = make(tmp_path / "home")
    assert new(w, "alpha") == f"W-{P}-1" and w.state()["intact"]


@pytest.mark.parametrize("name", [".lock", ".lock.gate"])
def test_a11_a_hard_link_or_a_folder_at_the_logs_lock_or_its_gate_refuses_every_write(tmp_path, name):   # refuse
    w = make(tmp_path / "home")
    first = new(w, "alpha")
    at = w.path.with_name(w.path.name + name)
    elsewhere = tmp_path / "someone-elses.txt"
    elsewhere.write_bytes(b"not a lock")
    at.unlink(missing_ok=True)   # the plain one the first write left
    os.link(elsewhere, at)   # a second name for a file outside the store: the lock would be taken on it
    refused("CONFLICT", new, w, "alpha")
    at.unlink()
    at.mkdir()               # a folder squatting at the name: refused, never a PermissionError
    refused("CONFLICT", new, w, "alpha")
    assert [i["id"] for i in w.state()["items"].values()] == [first] and elsewhere.read_bytes() == b"not a lock"
    at.rmdir()               # must pass: the name free again, the next write goes through
    assert new(w, "alpha") == f"W-{P}-2"


# ---- void belongs to the owner, and every way into review counts as reaching doing (review round 3, G6 4 and 5) ----
def test_void_is_the_owners_after_the_person_reassigns_the_item(w):
    ident = new(w, "alpha")
    person(w, ident, "assign", value="beta")
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "void", {"id": ident, "reason": "not mine now"})
    seq = plant(w, {"event": "void", "id": ident, "reason": "not mine now", "who": "alpha", "assurance": "bound"})
    assert row(w, seq)["code"] == "NOT_AUTHORIZED" and not item(w, ident)["voided"]
    got = w.write(bound("beta"), "void", {"id": ident, "reason": "a duplicate"})["item"]   # must pass: the owner
    assert got["voided"]["by"] == "beta"


def test_void_of_an_item_taken_from_a_claimed_create_is_the_takers(w):
    ident = new(w, actor=claimed("someone"))
    w.write(bound("beta"), "assign_self", {"id": ident})
    refused("NOT_AUTHORIZED", w.write, bound("gamma"), "void", {"id": ident, "reason": "x"})
    assert w.write(bound("beta"), "void", {"id": ident, "reason": "a duplicate"})["item"]["voided"]


@pytest.mark.parametrize("frm", ["backlog", "next"])
def test_an_item_the_person_moves_straight_to_review_has_reached_doing(w, frm):
    ident = new(w, "alpha")
    if frm == "next":
        person(w, ident, "next", frm="backlog")
    got = person(w, ident, "review", frm=frm)["item"]
    assert got["state"] == "review" and got["reached_doing"] is True
    refused("NOT_AUTHORIZED", w.write, bound("alpha"), "void", {"id": ident, "reason": "too late"})


def test_partner_an_item_never_past_next_is_still_voidable_by_its_owner(w):
    ident = new(w, "alpha")
    person(w, ident, "next", frm="backlog")
    assert item(w, ident)["reached_doing"] is False
    assert w.write(bound("alpha"), "void", {"id": ident, "reason": "not needed"})["item"]["voided"]

# ---- review round 3, G6 lows on the table: reopen is held, an epic is live, review needs a deliverable, parked is
# the person's --------------------------------------------------------------------------------------------------------
def test_reopen_into_doing_is_held_while_a_linked_decision_is_parked(tmp_path):
    w = make(tmp_path / "home", parked={"J-20260101-3"})
    ident = new(w, "alpha", links=[{"type": "commit", "ref": "abc1234"}])
    person(w, ident, "next", frm="backlog")
    w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    person(w, ident, "done", frm="doing")
    w.write(bound("alpha"), "link", {"id": ident, "link": {"type": "decision", "ref": "J-20260101-3"}})
    refused("HELD", person, w, ident, "reopen")
    assert item(w, ident)["state"] == "done"


def test_partner_reopen_with_no_parked_decision_goes_to_doing(w):
    ident = to_doing(w)
    person(w, ident, "done", frm="doing")
    assert person(w, ident, "reopen")["item"]["state"] == "doing"


def test_no_item_is_filed_under_a_void_epic(w):
    epic = new(w, "alpha", kind="epic")
    w.write(bound("alpha"), "void", {"id": epic, "reason": "a duplicate"})
    refused("MALFORMED", new, w, "alpha", epic=epic)
    live = new(w, "alpha", kind="epic")
    assert item(w, new(w, "alpha", epic=live))["epic"] == live                   # must pass


@pytest.mark.parametrize("link", [{"type": "decision", "ref": "J-20260101-3"}, {"type": "post", "ref": "P100"},
                                  {"type": "card", "ref": "A-20260101-120000"}], ids=["decision", "post", "card"])
def test_review_needs_a_deliverable_not_any_link(w, link):
    ident = new(w, "alpha", links=[link])
    person(w, ident, "next", frm="backlog")
    w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    refused("MALFORMED", w.write, bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review",
                                                          "reviewer": "beta"})


def test_review_needs_a_deliverable_a_bound_seat_linked(w):
    ident = new(w, "alpha")
    person(w, ident, "next", frm="backlog")
    w.write(bound("alpha"), "move", {"id": ident, "from": "next", "to": "doing"})
    w.write(claimed("gamma"), "link", {"id": ident, "link": {"type": "commit", "ref": "abc1234"}})
    refused("MALFORMED", w.write, bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review",
                                                          "reviewer": "beta"})
    w.write(bound("alpha"), "link", {"id": ident, "link": {"type": "run", "ref": "semantext-prove#4"}})
    assert w.write(bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review",
                                            "reviewer": "beta"})["applied"]          # must pass


def test_the_owner_does_not_edit_an_item_the_person_parked(w):
    ident = new(w, "alpha")
    person(w, ident, "park")
    refused("PARKED", w.write, bound("alpha"), "edit", {"id": ident, "title": "Mine again"})
    person(w, ident, "unpark")
    assert w.write(bound("alpha"), "edit", {"id": ident, "title": "Mine again"})["item"]["title"] == "Mine again"

# ---- the attack on the Work page, A1: the A11 arm with the head moved too ------------------------------------------
def test_a11_a_planted_person_act_on_the_chain_with_made_up_evidence_is_never_state(w):
    # the head moved too, as a program that can write both files would; the evidence names a span of a real
    # transcript, inside the trusted root, whose bytes are not the ones it claims (PM-DESIGN, decided 24 October, A1)
    from work_kit import transcripts
    ident = new(w, "alpha")
    say(w, "an ordinary message")
    span = {"path": str(transcripts(w.home) / "s1.jsonl"), "offset": 0, "length": 30, "sha256": "0" * 64}
    seq = plant(w, {"event": "person_act", "id": ident, "act": "park", "who": "person", "assurance": "bound",
                    "evidence": {"session": "s", "turn": "t", "turn_at": "2026-10-24T13:59:00Z",
                                 "line": f"{ident} park", "span": span}}, move_head=True)
    r = row(w, seq)
    assert r["on_chain"] and not r["applied"] and r["code"] == "UNVERIFIED" and item(w, ident)["state"] == "backlog"
    person(w, ident, "park")                                             # must pass: his own act, from his own turn
    assert item(w, ident)["state"] == "parked"