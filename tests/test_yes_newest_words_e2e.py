"""The person's newest words and an earlier yes, through the real proxy and a client (needs the Anthropic SDK; the same
law is pinned without it in test_yes_newest_words.py)."""
from __future__ import annotations

import pytest

anthropic = pytest.importorskip("anthropic")

from tests.test_proxy import C, T, ask, sse_turn  # noqa: E402
from tests.test_replay_gaps import RM, hold, rigs, status, types, yes  # noqa: E402,F401

STOP = "wait, do not delete anything. I changed my mind."
SECRET_RM = {"command": "rm -rf logs  # password = hunter22xyz"}


def _after(held, last):
    return [{"role": "user", "content": "go"},
            {"role": "assistant", "content": [T("deleting"), T(held)]},
            {"role": "user", "content": last}]


def test_a_later_stop_holds_the_kept_turn_and_leaves_the_yes(rigs):
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    held = hold(rig, cl, C("Bash", RM))
    aid = p.asks.snapshot().asks[-1]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("ok, I will not"), stop="end_turn"))
    got = ask(cl, True, _after(held, STOP))
    assert types(got) == ["text"] and status(p, aid) == "yes"


def test_a_later_stop_holds_the_call_made_again(rigs):
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    held = hold(rig, cl, C("Bash", SECRET_RM))
    aid = p.asks.snapshot().asks[-1]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", SECRET_RM, "toolu_2")))
    got = ask(cl, True, _after(held, STOP))
    assert "tool_use" not in types(got) and status(p, aid) == "yes"
    assert [a["id"] for a in p.asks.snapshot().asks] == [aid]


def test_a_go_for_one_act_and_a_stop_for_another_holds_the_kept_turn(rigs):
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    held = hold(rig, cl, C("Bash", {"command": "git push origin main && rm -rf logs"}))
    aid = p.asks.snapshot().asks[-1]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("ok, pushing only"), stop="end_turn"))
    got = ask(cl, True, _after(held, "go ahead and push. do not delete anything."))
    assert types(got) == ["text"] and status(p, aid) == "yes"


def test_a_go_after_the_yes_still_sends_the_kept_turn(rigs):
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    held = hold(rig, cl, C("Bash", RM))
    aid = p.asks.snapshot().asks[-1]["id"]
    yes(p, aid)
    got = ask(cl, True, _after(held, "ok, go ahead now"))
    assert types(got) == ["tool_use"] and status(p, aid) == "spent"
