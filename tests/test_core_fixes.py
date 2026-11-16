"""The ask store and its chain, fixes of the attacks on the replay and release work (C1, C2, C5).

  C1  a reader and the file swap collide on Windows (WinError 5): the store's own tools (read_settled, write_atomic)
      retry the refusal, so a yes, a revoke or an open never fails because someone was reading.
  C2  the chain's LAST word decides: a yes counts only while the last answered word for that ask on the chain is yes
      and no `spent` line lists it. A crash between a chain line and the asks file leaves the file behind the chain.
  C5  the cap is checked for the whole turn before any ask is opened.
"""
from __future__ import annotations

import json
import secrets
import threading
import time

import pytest

from semantext import canon, decide
from semantext.assemble import Refused
from tests.test_decide import RM, call, msg, run, space_of  # noqa: F401
from tests.test_decide import env  # noqa: F401  (a fixture)

NOW = 100.0


def _open(asks, d="d1", conv="c", now=NOW, tool="bash"):
    return asks.open("coder", "space", tool, "call", d, conv, now)


def _yes_for(asks, d="d1", conv="c", now=NOW, tool="bash"):
    return asks.yes_for("coder", "space", tool, d, conv, now)


# ================= C1: a reader never makes a write fail =================
def test_spinning_readers_never_make_an_open_or_an_answer_fail(tmp_path):          # must-pass (fails on the base)
    asks = decide.Asks(tmp_path / "asks.json", run="r1", key=secrets.token_bytes(32))
    stop, errs = threading.Event(), []

    def reader():
        while not stop.is_set():
            try:                                   # what every yes_for and status does: unlocked reads
                _yes_for(asks)
                asks.status("nothing", NOW)
            except Refused as e:
                errs.append(("read", str(e)))
            time.sleep(0.001)      # a reader that never lets go of the file is a limit (see Asks), not this test

    readers = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
    for t in readers:
        t.start()
    fails, t0 = [], time.monotonic()
    try:
        for i in range(40):
            try:
                aid = _open(asks, d=f"d{i}")
                assert asks.answer(aid, "yes", NOW)
                assert _yes_for(asks, d=f"d{i}") == aid
            except Refused as e:
                fails.append(str(e))
    finally:
        stop.set()
        for t in readers:
            t.join(5)
    assert fails == [] and errs == [], (fails[:2], errs[:2])
    assert time.monotonic() - t0 < 10


def test_an_unreadable_store_is_still_refused_not_read_as_empty(tmp_path):         # must-refuse (the control)
    p = tmp_path / "asks.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(Refused) as e:
        decide.Asks(p, run="r1")._read()
    assert e.value.rule == "X-EXC"
    assert decide.Asks(tmp_path / "none.json", run="r1")._read() == []              # a missing file is no asks


# ================= C2: the chain's last word decides =================
@pytest.fixture
def chained(tmp_path):
    """Asks with a record that is a plain list of lines (what Asks needs of a record: lines() and append())."""
    class Rec:
        def __init__(self):
            self.rows = []

        def lines(self):
            return list(self.rows)

        def append(self, kind, body):
            self.rows.append({"kind": kind, "body": body})
    rec = Rec()
    return decide.Asks(tmp_path / "asks.json", run="r1", key=secrets.token_bytes(32), record=rec), rec


def _file_status(asks, aid, word):
    """Put the asks file back to a status, as it was before a crash that lost its write."""
    rows = asks._read()
    for a in rows:
        if a["id"] == aid:
            a["status"] = word
    asks._write(rows)


def test_a_plain_yes_releases_once(chained):                                         # control
    asks, rec = chained
    aid = _open(asks)
    assert asks.answer(aid, "yes", NOW)
    assert _yes_for(asks) == aid and asks.status(aid, NOW) == "yes"
    assert asks.spend([aid], NOW)
    assert _yes_for(asks) is None and not asks.spend([aid], NOW) and asks.status(aid, NOW) == "spent"


def test_a_yes_then_a_revoke_written_whole_is_held(chained):                         # control
    asks, rec = chained
    aid = _open(asks)
    asks.answer(aid, "yes", NOW)
    assert asks.answer(aid, "revoke", NOW)
    assert _yes_for(asks) is None and not asks.spend([aid], NOW)
    assert asks.status(aid, NOW) == "revoked"


def test_a_crash_after_the_revoke_line_does_not_release(chained):                    # must-refuse (fails on the base)
    asks, rec = chained
    aid = _open(asks)
    asks.answer(aid, "yes", NOW)
    rec.append("answered", {"ask": aid, "word": "revoke"})       # the chain line was written; the file write was lost
    assert [a["status"] for a in asks._read()] == ["yes"]
    assert _yes_for(asks) is None, "the chain's last word is revoke: a yes read from the file released"
    assert not asks.spend([aid], NOW)
    assert asks.status(aid, NOW) == "unproved"                    # the file and the chain differ
    again = _open(asks)                                           # the model re-issues the call: a new ask, held
    assert again != aid


def test_a_crash_after_the_spent_line_does_not_release_twice(chained):               # must-refuse (fails on the base)
    asks, rec = chained
    aid = _open(asks)
    asks.answer(aid, "yes", NOW)
    assert asks.spend([aid], NOW)
    _file_status(asks, aid, "yes")                               # the file write after the spent line was lost
    assert _yes_for(asks) is None, "a spent yes released a second time"
    assert not asks.spend([aid], NOW)
    assert asks.status(aid, NOW) == "spent"                       # the chain says so, and a sweep may drop the turn


def test_a_yes_after_a_revoke_on_the_chain_counts_again(chained):                    # must-pass: the LAST word, not any
    asks, rec = chained
    aid = _open(asks)
    asks.answer(aid, "yes", NOW)
    rec.append("answered", {"ask": aid, "word": "revoke"})
    rec.append("answered", {"ask": aid, "word": "yes"})
    assert _yes_for(asks) == aid and asks.status(aid, NOW) == "yes"


def test_a_spent_line_for_another_ask_does_not_hold_this_one(chained):               # must-pass (the spent set is per ask)
    asks, rec = chained
    a, b = _open(asks, d="d1"), _open(asks, d="d2")
    asks.answer(a, "yes", NOW)
    asks.answer(b, "yes", NOW)
    assert asks.spend([a], NOW)
    assert _yes_for(asks, d="d2") == b and asks.spend([b], NOW)


def test_the_chain_is_read_once_per_call_not_once_per_ask(chained):
    asks, rec = chained
    ids = [_open(asks, d=f"d{i}") for i in range(6)]
    for i in ids:
        asks.answer(i, "yes", NOW)
    reads = []
    real = rec.lines
    rec.lines = lambda: (reads.append(1), real())[1]
    assert _yes_for(asks, d="d5") == ids[5]
    assert len(reads) == 1
    reads.clear()
    snap = asks.snapshot()
    assert [asks.status(i, NOW, snap) for i in ids] == ["yes"] * 6 and len(reads) == 1
    reads.clear()
    assert asks.spend(ids, NOW) and len(reads) == 1


def test_a_sweep_and_a_replay_check_read_the_chain_once_per_pass(chained):
    asks, rec = chained
    stash = decide.Stash()
    ids = [_open(asks, d=f"d{i}") for i in range(4)]
    for k, i in enumerate(ids):
        asks.answer(i, "yes", NOW)
        stash.put(f"k{k}", decide.Stashed("c", "m", [i], [], "t", False, f"k{k}"))
    reads = []
    real = rec.lines
    rec.lines = lambda: (reads.append(1), real())[1]
    assert stash.sweep(asks, NOW) == 0 and len(reads) == 1


# ================= C5: the cap is checked for the whole turn =================
def _many(n, prefix="echo"):
    return [call("Bash", canon.loads(f'{{"command": "{prefix} {i}"}}'), f"t{i}") for i in range(n)]


def _open_count(asks):
    return sum(1 for a in asks._read() if a["status"] == "open")


def test_a_turn_that_would_pass_the_cap_opens_no_ask(env):                           # must-refuse (fails on the base)
    space, asks = env
    with pytest.raises(Refused) as e:
        run(env, msg(*_many(decide.MAX_OPEN_ASKS + 1)))
    assert e.value.rule == "X-ASK"
    assert _open_count(asks) == 0, "a refused turn left asks behind"
    out = run(env, msg(call("Bash", canon.loads('{"command": "one"}'))))          # the agent is not shut out
    assert out.held and _open_count(asks) == 1


def test_a_turn_of_exactly_the_cap_opens_all_of_them(env):                           # control
    space, asks = env
    out = run(env, msg(*_many(decide.MAX_OPEN_ASKS)))
    assert out.held and len(out.asks) == decide.MAX_OPEN_ASKS and _open_count(asks) == decide.MAX_OPEN_ASKS


def test_a_reused_ask_is_not_counted_twice(env):                                     # control
    space, asks = env
    run(env, msg(*_many(10)))                                                         # ten open
    again = run(env, msg(*_many(10), call("Bash", canon.loads('{"command": "new"}'), "tn")))
    assert again.held and _open_count(asks) == 11                                    # ten reused, one new
    twins = run(env, msg(*[call("Bash", canon.loads('{"command": "same"}'), f"s{i}") for i in range(30)]))
    assert twins.held and len(twins.asks) == 1 and _open_count(asks) == 12           # thirty twins are one ask


def test_a_turn_over_what_room_is_left_is_refused_whole(env):
    space, asks = env
    run(env, msg(*_many(15)))
    with pytest.raises(Refused):
        run(env, msg(*_many(5, "fresh"), call("Bash", canon.loads('{"command": "fresh 5"}'), "t5")))   # 6 new, 5 room
    assert _open_count(asks) == 15
    assert run(env, msg(*_many(5, "fresh"))).held and _open_count(asks) == 20


def test_the_undeclared_pool_keeps_its_own_cap_for_a_turn(env):
    space, asks = env
    with pytest.raises(Refused, match="may not call"):
        run(env, msg(*[call(f"Nope{i}", canon.loads(f'{{"n": {i}}}'), f"u{i}") for i in range(decide.MAX_UNDECLARED + 1)]))
    assert _open_count(asks) == 0
    ok = run(env, msg(*[call(f"Nope{i}", canon.loads(f'{{"n": {i}}}'), f"u{i}") for i in range(decide.MAX_UNDECLARED)],
                      *_many(decide.MAX_OPEN_ASKS)))                                 # both pools full at once is fine
    assert ok.held and _open_count(asks) == decide.MAX_UNDECLARED + decide.MAX_OPEN_ASKS
