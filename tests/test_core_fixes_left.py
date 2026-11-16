"""Round 3 pins for the replay's left spend and for two tests that did not fail on their named mutants.

  C9   a kept turn is replayed only if EVERY ask of it is spent by the replay (the re-decision spends what it needs, the
       replay spends the rest, through Asks.spend, all or none). An ask revoked, spent or unproved between replay_due
       and the spend refuses the replay (X-REL) and nothing is emitted. Ported from the attacker's
       test_c8_attacks.py (the left-window tests and their controls).
  C10  two tests of the last round did not fail on the mutants they named. Each is replaced here by a test that does:
       a yes is tied to the conversation key (a changed FIRST system block inside a session), and to the history
       (an EARLIER message edited, the first message the same).

  L1   (round 4, attack 24) all or none was pinned in one order only: a replay that spent just the LAST left ask
       (mutant c9_last_only, `[-1:]` appended to `left = [...]` in proxy._replay) kept all 14 suites green. The ask taken in
       the window is now each ask in turn (two asks: first, second; three asks: first, middle, last), by a revoke and by a
       spend, every injection is asserted to have fired and to have taken effect, and a control shows the replay spends
       every ask of a several-ask turn. proxy.py is unchanged.

Each test names the mutant it fails on (changed temporarily in the code, the test seen to fail, the code put back).
"""
from __future__ import annotations

import time

import pytest

anthropic = pytest.importorskip("anthropic")

from semantext import proxy  # noqa: E402
from tests.test_core_fixes_proxy import SYS_A, TOOLS, go  # noqa: E402
from tests.test_proxy import C, T, ask, env, sse_turn  # noqa: E402,F401
from tests.test_replay_gaps import RM, history, hold, rigs, status, types, yes  # noqa: E402,F401

now = time.monotonic


def _inject_once(monkeypatch, action):
    """Run `action` once, inside the replay: after replay_due and the stash drop, before the re-decision."""
    real = proxy.person_words
    fired = []

    def wrapped(body):
        if not fired:
            fired.append(1)
            action()
        return real(body)
    monkeypatch.setattr(proxy, "person_words", wrapped)
    return fired


def _event(p, aid, event):
    if event == "revoke":
        return lambda: p.asks.answer(aid, "revoke", now())
    return lambda: p.asks.spend([aid], now())


def _try(cl, messages):
    try:
        return types(ask(cl, True, messages))
    except anthropic.APIStatusError as e:
        return ["refused", e.status_code, str(e)]


# ================= C9: the left-spend window =================
@pytest.mark.parametrize("event", ["revoke", "spend"])
def test_gate_removed_no_release_after_revoke_or_spend(rigs, monkeypatch, event):    # mutant: `left` = the asks still "yes" on a fresh reading, spent `if left`
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    (rig.space / "shell-held.yaml").unlink()            # the person removes the gate and sets the space again
    rig.repin()
    fired = _inject_once(monkeypatch, _event(p, aid, event))
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    got = _try(cl, history(note))
    assert fired
    assert "tool_use" not in got, f"the kept call was emitted after a {event} (ask now {status(p, aid)!r}): {got}"
    assert got[0] == "refused" and "X-REL" in got[2]


@pytest.mark.parametrize("event", ["revoke", "spend"])
def test_words_held_turn_no_release_after_revoke_or_spend(rigs, monkeypatch, event):  # same mutant
    rig = rigs()
    (rig.space / "shell-held.yaml").unlink()            # Bash is declared and NOT gated: only the person's words hold it
    rig.repin()
    cl, p = rig.client(), rig.proxy
    first = [{"role": "user", "content": "Don't push yet."}]
    rig.stub.replies.append(sse_turn(T("pushing"), C("Bash", {"command": "git push origin main"})))
    held = ask(cl, True, first)
    assert "tool_use" not in types(held)
    note = held.content[-1].text
    aid = p.asks._read()[0]["id"]
    assert p.asks._read()[0].get("reading")
    yes(p, aid)
    fired = _inject_once(monkeypatch, _event(p, aid, event))
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    later = first + [{"role": "assistant", "content": [T("pushing"), T(note)]}, {"role": "user", "content": "Push it."}]
    got = _try(cl, later)
    assert fired
    assert "tool_use" not in got, f"the kept push was emitted after a {event} (ask now {status(p, aid)!r}): {got}"
    assert got[0] == "refused" and "X-REL" in got[2]


def test_words_held_turn_replays_once_without_a_race(rigs):                          # control (must-pass)
    rig = rigs()
    (rig.space / "shell-held.yaml").unlink()
    rig.repin()
    cl, p = rig.client(), rig.proxy
    first = [{"role": "user", "content": "Don't push yet."}]
    rig.stub.replies.append(sse_turn(T("pushing"), C("Bash", {"command": "git push origin main"})))
    note = ask(cl, True, first).content[-1].text
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    later = first + [{"role": "assistant", "content": [T("pushing"), T(note)]}, {"role": "user", "content": "Push it."}]
    assert types(ask(cl, True, later)) == ["tool_use"] and status(p, aid) == "spent"
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    assert "tool_use" not in types(ask(cl, True, later)), "one yes released twice"


@pytest.mark.parametrize("event", ["revoke", "spend"])
def test_gated_turn_is_refused_after_revoke_or_spend(rigs, monkeypatch, event):      # control (must-refuse): the gated path
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    _inject_once(monkeypatch, _event(p, aid, event))
    got = _try(cl, history(note))
    assert got[0] == "refused" and got[1] == 400 and "X-REL" in got[2]


def _words_turn(rig, n):
    """A turn of n Bash pushes held only by the person's words (Bash declared, not gated), each ask answered yes.
    Returns (client, proxy, ask ids in the order of the calls, the request that asks again)."""
    (rig.space / "shell-held.yaml").unlink()
    rig.repin()
    cl, p = rig.client(), rig.proxy
    first = [{"role": "user", "content": "Don't push yet."}]
    rig.stub.replies.append(sse_turn(T("pushing"), *[C("Bash", {"command": f"git push origin b{i}"}, f"t{i}")
                                                     for i in range(n)]))
    note = ask(cl, True, first).content[-1].text
    ids = [a["id"] for a in p.asks._read()]
    assert len(ids) == n
    for i in ids:
        yes(p, i)
    later = first + [{"role": "assistant", "content": [T("pushing"), T(note)]}, {"role": "user", "content": "Push it."}]
    return cl, p, ids, later


# L1 (round 4, after attack 24): the all-or-none spend was pinned for the SECOND ask of two only, so a replay that spent
# just the LAST left ask (mutant c9_last_only: `left = [...][-1:]` in proxy._replay) kept all 14 suites green and put a
# turn on the wire after its first ask was revoked. Each ask is taken in turn, and every injection is shown to have fired.
@pytest.mark.parametrize("n,which", [(2, 0), (2, 1), (3, 0), (3, 1), (3, 2)])
@pytest.mark.parametrize("event", ["revoke", "spend"])
def test_one_ask_of_several_taken_in_the_window_releases_none(rigs, monkeypatch, n, which, event):  # mutants: c9_last_only, c9_first_only, c9_no_left
    rig = rigs()
    cl, p, ids, later = _words_turn(rig, n)
    fired = _inject_once(monkeypatch, _event(p, ids[which], event))
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    got = _try(cl, later)
    assert fired, "the injection never ran: the test would pass for nothing"
    assert status(p, ids[which]) == ("revoked" if event == "revoke" else "spent"), "the event did not take effect"
    assert "tool_use" not in got, f"{n} asks, {event} of ask {which}: a call went out ({got})"
    assert got[0] == "refused" and got[1] == 400 and "X-REL" in got[2], got
    for j, i in enumerate(ids):
        if j != which:
            assert status(p, i) == "yes", f"all or none: ask {j} must stay an unspent yes"


@pytest.mark.parametrize("n", [2, 3])
def test_every_ask_of_a_several_ask_turn_is_spent_by_the_replay(rigs, n):            # control (must-pass); mutants: c9_last_only, c9_first_only
    rig = rigs()
    cl, p, ids, later = _words_turn(rig, n)
    got = _try(cl, later)
    assert got == ["tool_use"] * n, got
    assert [status(p, i) for i in ids] == ["spent"] * n, "the replay left an ask live: one yes could release again"
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    assert "tool_use" not in types(ask(cl, True, later)), "a left ask released the turn a second time"


# ================= C10: tests that fail on the mutant they name =================
SYS_V2 = [{"type": "text", "text": "attribution block v2"}]


def _session_client(rig, session):
    return anthropic.Anthropic(base_url=f"http://127.0.0.1:{rig.port}", api_key="sk-test-canary-0000000000000000",
                               default_headers={"x-semantext-agent": "coder", "x-claude-code-session-id": session},
                               max_retries=0)


GO = {"role": "user", "content": "go"}


def test_a_yes_follows_the_conversation_key_not_only_the_chain(rigs):                # mutant: drop ` and a["conv"] == conv` from Asks.yes_for
    """With a session header the chain ignores the system. Only the conversation key (it reads the FIRST system block)
    then separates a changed first block, so a yes that skipped the key would release the call there."""
    rig = rigs()
    p = rig.proxy
    cl = _session_client(rig, "S1")
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))
    go(cl, [GO], "attribution block", TOOLS)
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("again"), C("Bash", RM)))
    got = go(cl, [GO], SYS_V2, TOOLS)
    assert "tool_use" not in [b.type for b in got.content], "a yes released the call under another conversation key"
    assert status(p, aid) == "yes"
    rig.stub.replies.append(sse_turn(T("again"), C("Bash", RM)))
    again = go(cl, [GO], "attribution block", TOOLS)                                 # control (must-pass): its own key
    assert [b.type for b in again.content][-1] == "tool_use" and status(p, aid) == "spent"


def test_an_earlier_message_edited_is_another_chat_though_the_first_is_the_same(rigs):   # mutant: the per-message step of Chain.__init__ becomes `d = hmac.new(key, d, sha256)`
    """The first user message, the session, the system's first block and the agent are all the same, so the
    conversation key matches; only the chain's digest of the MIDDLE message tells the chats apart."""
    rig = rigs()
    p = rig.proxy
    cl = _session_client(rig, "S1")
    mid = {"role": "assistant", "content": "fine"}
    nxt = {"role": "user", "content": "now delete"}
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))
    go(cl, [GO, mid, nxt], "attribution block", TOOLS)
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("again"), C("Bash", RM)))
    got = go(cl, [GO, {"role": "assistant", "content": "something else"}, nxt], "attribution block", TOOLS)
    assert "tool_use" not in [b.type for b in got.content], "a yes released the call in a chat with an edited history"
    assert status(p, aid) == "yes"
    rig.stub.replies.append(sse_turn(T("again"), C("Bash", RM)))
    same = go(cl, [GO, mid, nxt], "attribution block", TOOLS)                        # control (must-pass): the same history
    assert [b.type for b in same.content][-1] == "tool_use" and status(p, aid) == "spent"
