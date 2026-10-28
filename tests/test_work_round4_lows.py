"""Review round 4, the low findings (decision 5), each a must-refuse with its must-pass partner."""
from pathlib import Path

import pytest

from semantext import store
from semantext.work import clauses
from semantext.work.chain import GENESIS, line_of, parse_line, walk
from semantext.work.cli import _show
from work_kit import P, bound, make, new, person, plant, refused, to_doing

J = "J-20261020-1"


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def held(tmp_path):
    return make(tmp_path / "home", parked={J})


# ---- the parked hold: every way into doing ------------------------------------------------------------------------------
def test_review_to_doing_respects_the_hold(tmp_path):
    w = held(tmp_path)
    ident = to_doing(w)
    w.write(bound("alpha"), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": "beta"})
    w.write(bound("beta"), "link", {"id": ident, "link": {"type": "decision", "ref": J}})
    refused("HELD", w.write, bound("beta"), "move", {"id": ident, "from": "review", "to": "doing"})
    w.write(bound("beta"), "unlink", {"id": ident, "link": {"type": "decision", "ref": J}})   # must pass: unheld
    w.write(bound("beta"), "move", {"id": ident, "from": "review", "to": "doing"})
    assert w.state()["items"][ident]["state"] == "doing"


def test_unpark_into_doing_respects_the_hold(tmp_path):
    w = held(tmp_path)
    ident = to_doing(w)
    person(w, ident, "park")
    w.write(bound("beta"), "link", {"id": ident, "link": {"type": "decision", "ref": J}})
    refused("HELD", person, w, ident, "unpark")
    other = new(w, "alpha")                                                 # must pass: parked from backlog
    person(w, other, "park")
    w.write(bound("beta"), "link", {"id": other, "link": {"type": "decision", "ref": J}})
    person(w, other, "unpark")
    assert w.state()["items"][other]["state"] == "backlog"


# ---- the writer's head --------------------------------------------------------------------------------------------------
def test_adopt_keeps_the_pending_line_when_the_head_cannot_be_read(w, monkeypatch):
    new(w, "alpha")
    real = store.write_atomic

    def no_head(p, data):
        if Path(p) == w.head_path:
            raise OSError("the disk said no")
        return real(p, data)
    monkeypatch.setattr(store, "write_atomic", no_head)
    with pytest.raises(OSError):
        new(w, "alpha")                                                     # the line is synced, the head is not
    monkeypatch.setattr(store, "write_atomic", real)
    real_read, fails = Path.read_text, [1]

    def flaky(self, *a, **k):
        if self == w.head_path and fails:
            fails.pop()
            raise OSError("locked, once")
        return real_read(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", flaky)
    refused("CONFLICT", new, w, "alpha")                                    # nothing decided on an unread head
    monkeypatch.setattr(Path, "read_text", real_read)
    new(w, "alpha")                                                         # must pass: the orphan is adopted
    st = w.state()
    assert [e["seq"] for e in st["events"]] == [1, 2, 3] and all(e["on_chain"] for e in st["events"])


def test_a_head_that_is_not_utf8_is_a_problem_not_a_raise(w):
    new(w, "alpha")
    w.head_path.write_bytes(b"\xff\xfe{\x00")
    st = w.state()
    assert not st["intact"] and st["problems"]
    refused("CONFLICT", new, w, "alpha")


# ---- the chain ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("lines,torn", [(["not a record"], None), ([], '{"v":1,"ev'), (["{}"], "x")])
def test_no_head_and_nothing_parsable_is_not_intact(lines, torn):
    assert walk(lines, torn, None)["intact"] is False


def test_partner_an_empty_store_with_no_head_is_intact():
    assert walk([], None, None)["intact"] is True


def test_a_lone_surrogate_in_a_line_is_a_problem_never_a_raise():
    rec = {"v": 1, "event": "comment", "id": f"W-{P}-1", "text": "x\udc80", "who": "alpha", "assurance": "bound",
           "channel": "mcp", "at": "2026-10-24T14:00:00Z", "seq": 1, "prev": GENESIS}
    text = line_of({**rec, "hash": "0" * 64})                               # in the writer's form, but for its hash
    got, why, own = parse_line(text)
    assert got is None and not own and why
    assert walk([text], None, None)["intact"] is False                      # walked, never raised


# ---- two questions settled by reading the code (decision 6), held here so they stay settled --------------------------
def test_a_write_after_a_torn_tail_starts_a_fresh_line_and_the_chain_holds(w):
    new(w, "alpha")
    plant(w, None, raw='{"v":1,"event":"comm')                              # a writer died mid-line
    second = new(w, "alpha")
    st = w.state()
    assert st["intact"] and second in st["items"] and all(e["on_chain"] for e in st["events"])
    assert w.path.read_bytes().count(b'{"v":1,"event":"comm\n') == 1        # the fragment kept on a line of its own


def test_a_span_holding_a_bare_number_is_no_turn_never_a_raise():
    from semantext.work.span import named_line
    assert named_line(b"123", f"W-{P}-1", "park", None)[0] is None


# ---- verdict names, text, show ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("attacker", ["alice ", "ALICE", " Alice\t", "", "   "])
def test_a_verdict_by_the_originator_in_any_case_or_spacing_is_unmet(attacker):
    c = {"piece": "p1"}
    f = {"verdict": {"piece": "p1", "attacker": attacker, "verdict": "survived"},
         "piece": {"id": "p1", "originator": "alice"}}
    assert clauses._verdict(c, f, None)[0] == "unmet"


def test_partner_an_independent_verdict_is_met():
    f = {"verdict": {"piece": "p1", "attacker": "bob", "verdict": "survived"},
         "piece": {"id": "p1", "originator": "alice"}}
    assert clauses._verdict({"piece": "p1"}, f, None)[0] == "met"


def test_crlf_in_text_is_kept_as_a_newline(w):
    ident = new(w, "alpha")
    w.write(bound("alpha"), "comment", {"id": ident, "text": "a\r\nb"})
    assert w.state()["items"][ident]["comments"][0]["text"] == "a\nb"
    refused("MALFORMED", w.write, bound("alpha"), "comment", {"id": ident, "text": "a\rb"})   # a lone CR, still not


def test_show_prints_no_control_character_from_an_off_chain_line(w):
    ident = new(w, "alpha")
    plant(w, {"event": "comment\x1b[31m", "id": ident, "text": "x", "who": "x\x1b[2J", "assurance": "bound\x1b[0m"},
          move_head=False)
    said = []
    _show(w.state(), ident, said.append)
    assert said and not any("\x1b" in s for s in said)
    assert any("comment" in s for s in said)                                # must pass: the row is still shown
