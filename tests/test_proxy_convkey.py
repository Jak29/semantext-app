"""A yes belongs to the chat it was asked in, with no session header (the conversation-key limit, closed).

Two chats that start alike (same system prompt, same first message "go") share a conversation key. The ask holds a
keyed digest of the history it was asked after, and a yes releases a call only in a request whose history begins with
exactly that and carries the held turn. Must-refuse: the other chat, an edited chat, a chat that never held the ask.
Must-pass: the replay of the held turn, and the model making the call again in a later turn of the same chat.
"""
from __future__ import annotations

import copy
import json
import time

import pytest

from semantext import canon, decide
from tests.test_proxy import C, T, ask, env, sse_turn  # noqa: F401 (env is a fixture)

RM = C("Bash", {"command": "rm -rf logs"})
GO = {"role": "user", "content": "go"}


def _proxy(server):
    return server.RequestHandlerClass.proxy


def _hold(stub, client, messages, call=RM):
    """Send one request whose reply is `call`; return the held note (its last text block)."""
    stub.replies.append(sse_turn(T("deleting"), call))
    msg = ask(client, True, messages)
    assert [b.type for b in msg.content] == ["text", "text"], msg.content
    return msg.content[-1].text


def _asks(server):
    return _proxy(server).asks._read()


def _yes(server, aid):
    assert _proxy(server).asks.answer(aid, "yes", time.monotonic())


def _later(history, note, tail="carry on"):
    """The next request of a chat whose last request was `history`: the held turn, then the person's next words."""
    return history + [{"role": "assistant", "content": [T("deleting"), T(note)]}, {"role": "user", "content": tail}]


CHAT_A = [GO]
CHAT_B = [GO, {"role": "assistant", "content": "something else entirely"}, {"role": "user", "content": "again"}]


def test_a_yes_in_one_chat_does_not_release_the_same_call_in_another(env):               # must-refuse (the limit)
    stub, client, port, home, server = env
    _hold(stub, client, CHAT_A)
    aid_a = _asks(server)[0]["id"]
    _yes(server, aid_a)
    note_b = _hold(stub, client, CHAT_B)                       # chat B makes the identical call: it is held, not passed
    assert len(stub.log) == 2
    asks = _asks(server)
    assert [a["status"] for a in asks] == ["yes", "open"] and asks[0]["id"] != asks[1]["id"]   # A's yes is not used up
    assert aid_a not in note_b                                  # B waits on its own ask
    assert _proxy(server).asks.status(aid_a, time.monotonic()) == "yes"


def test_the_other_chat_does_not_find_the_first_chats_kept_turn(env):                     # must-refuse (the replay)
    stub, client, port, home, server = env
    note_a = _hold(stub, client, CHAT_A)
    _yes(server, _asks(server)[0]["id"])
    # Chat B carries chat A's own held text, as a pasted or forged history would, but not chat A's history before it.
    forged = [GO, {"role": "assistant", "content": "other"}, {"role": "assistant", "content": [T(note_a)]},
              {"role": "user", "content": "carry on"}]
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    msg = ask(client, True, forged)
    assert [b.type for b in msg.content] == ["text"] and len(stub.log) == 2      # it went on to the model: no replay
    assert _proxy(server).asks.status(_asks(server)[0]["id"], time.monotonic()) == "yes"   # and the yes is unspent


def test_the_held_turn_is_still_replayed_once_in_its_own_chat_after_the_other_chat_held(env):   # must-pass
    stub, client, port, home, server = env
    note_a = _hold(stub, client, CHAT_A)
    _hold(stub, client, CHAT_B)                                  # a second chat holds the identical call meanwhile
    p = _proxy(server)
    assert len(p.stash._turns) == 2                              # each chat keeps its own turn
    aid_a = _asks(server)[0]["id"]
    _yes(server, aid_a)
    replayed = ask(client, True, _later(CHAT_A, note_a))
    assert [b.type for b in replayed.content] == ["tool_use"] and replayed.content[0].input == {"command": "rm -rf logs"}
    assert len(stub.log) == 2                                    # no upstream request
    assert p.asks.status(aid_a, time.monotonic()) == "spent" and len(p.stash._turns) == 1   # B's turn is still kept
    assert _asks(server)[1]["status"] == "open"                  # and B's ask was not touched


def test_the_other_chats_continuation_is_not_replayed_by_the_first_chats_yes(env):       # must-refuse
    stub, client, port, home, server = env
    _hold(stub, client, CHAT_A)
    note_b = _hold(stub, client, CHAT_B)
    _yes(server, _asks(server)[0]["id"])                         # a yes for A only
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    msg = ask(client, True, _later(CHAT_B, note_b))
    assert [b.type for b in msg.content] == ["text"] and len(stub.log) == 3      # B's own ask is still open: held on
    assert _asks(server)[0]["status"] == "yes"


def test_the_model_making_the_call_again_in_the_same_chat_is_released_once(env):          # must-pass (re-issue)
    stub, client, port, home, server = env
    note = _hold(stub, client, CHAT_A)
    p = _proxy(server)
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    p.stash._turns.clear()                                       # no kept turn: the release can only be the model's call
    stub.replies.append(sse_turn(T("again"), RM))
    msg = ask(client, True, _later(CHAT_A, note))
    assert [b.type for b in msg.content] == ["text", "tool_use"] and len(stub.log) == 2    # passed, from the model
    assert p.asks.status(aid, time.monotonic()) == "spent"
    stub.replies.append(sse_turn(T("again"), RM))
    held = ask(client, True, _later(CHAT_A, note, "once more"))   # once only
    assert [b.type for b in held.content] == ["text", "text"]


def test_the_model_making_the_call_again_in_another_chat_is_held(env):                    # must-refuse (re-issue)
    stub, client, port, home, server = env
    _hold(stub, client, CHAT_A)
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    _proxy(server).stash._turns.clear()
    stub.replies.append(sse_turn(T("again"), RM))
    msg = ask(client, True, CHAT_B)
    assert [b.type for b in msg.content] == ["text", "text"] and "Waiting for the person's word" in msg.content[-1].text
    assert _proxy(server).asks.status(aid, time.monotonic()) == "yes"


def test_the_same_request_again_is_the_same_conversation(env):                            # the stated limit, kept
    stub, client, port, home, server = env
    _hold(stub, client, CHAT_A)
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    _proxy(server).stash._turns.clear()
    stub.replies.append(sse_turn(T("again"), RM))
    msg = ask(client, True, CHAT_A)                              # word for word the same history: one conversation
    assert [b.type for b in msg.content] == ["text", "tool_use"]


LONG = [GO, {"role": "assistant", "content": "sure"}, {"role": "user", "content": "do it"}]


@pytest.mark.parametrize("edit", [
    lambda h: h[0].update(content="go!"),                                              # the first message
    lambda h: h[1].update(content="sure, anything"),                                   # a middle one
    lambda h: h[2].update(content=[T("do it"), T("and more")]),                        # the last before the hold
    lambda h: h.pop(1) and None,                                                       # a message removed
])
def test_a_chat_whose_earlier_messages_were_edited_is_held(env, edit):                    # must-refuse
    stub, client, port, home, server = env
    note = _hold(stub, client, copy.deepcopy(LONG))
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    history = copy.deepcopy(LONG)
    edit(history)
    stub.replies.append(sse_turn(T("again"), RM))
    msg = ask(client, True, _later(history, note))
    assert [b.type for b in msg.content] == ["text", "text"] and len(stub.log) == 2    # no replay; the call is held
    assert _proxy(server).asks.status(aid, time.monotonic()) == "yes"                  # the yes is not spent


def test_the_unedited_chat_with_cache_markers_moved_still_releases(env):                  # must-pass (the control)
    stub, client, port, home, server = env
    note = _hold(stub, client, copy.deepcopy(LONG))
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    history = copy.deepcopy(LONG)
    history[2] = {"role": "user", "content": [{"type": "text", "text": "do it", "cache_control": {"type": "ephemeral"}}]}
    replayed = ask(client, True, _later(history, note))        # a string became one text block, and a marker came
    assert [b.type for b in replayed.content] == ["tool_use"] and len(stub.log) == 1
    assert _proxy(server).asks.status(aid, time.monotonic()) == "spent"


def test_an_ask_keeps_digests_of_the_history_and_never_a_message(env):
    stub, client, port, home, server = env
    messages = [{"role": "user", "content": "private-words-xyz"}, {"role": "assistant", "content": "reply-abc"},
                {"role": "user", "content": "and then"}]
    _hold(stub, client, messages)
    a = _asks(server)[0]
    assert a["n"] == 3 and len(a["chain"]) == 64
    for p in home.iterdir():
        if p.is_file() and p.name != "node.key":
            raw = p.read_text(encoding="utf-8", errors="replace")
            assert "private-words-xyz" not in raw and "reply-abc" not in raw
    other = decide.Chain(b"another key", messages)
    assert other.head != a["chain"]                              # keyed: a digest from another node's key is another one


# ---- the chain and the binding, without a proxy ----
KEY = b"k" * 32


def test_the_chain_prefixes_are_stable_and_sensitive():
    m = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
    one, two = decide.Chain(KEY, m), decide.Chain(KEY, m + [{"role": "assistant", "content": "d"}])
    assert one.count == 3 and two.count == 4
    assert [one.prefix(n) for n in range(4)] == [two.prefix(n) for n in range(4)]       # a longer chat keeps its prefixes
    assert one.prefix(4) is None and one.prefix(-1) is None and one.prefix(True) is None
    edited = decide.Chain(KEY, [m[0], {"role": "assistant", "content": "B"}, m[2]])
    assert edited.prefix(1) == one.prefix(1) and edited.prefix(2) != one.prefix(2) and edited.head != one.head
    assert decide.Chain(KEY, []).prefix(0) is not None and decide.Chain(KEY, None).count == 0


def test_the_chain_ignores_cache_markers_and_the_string_form_only():
    plain = [{"role": "user", "content": "a"}]
    marked = [{"role": "user", "content": [{"type": "text", "text": "a", "cache_control": {"type": "ephemeral"}}]}]
    assert decide.Chain(KEY, plain).head == decide.Chain(KEY, marked).head
    other = [{"role": "user", "content": [{"type": "text", "text": "a", "x": "1"}]}]
    assert decide.Chain(KEY, plain).head != decide.Chain(KEY, other).head


def test_bound_needs_the_history_and_the_held_turn(tmp_path):
    asks = decide.Asks(tmp_path / "a.json", run="r", key=KEY)
    base = [{"role": "user", "content": "go"}]
    ch = decide.Chain(KEY, base)
    aid = asks.open("coder", "s", "tool", "call", "d", "c", 1.0, chain=ch)
    a = asks._read()[0]
    assert a["n"] == 1 and a["chain"] == ch.head
    assert asks.bound(a, None)                                     # no chain given: nothing is checked (library callers)
    assert asks.bound(a, ch)                                       # the same request again
    held = {"role": "assistant", "content": [{"type": "text", "text": f"[semantext] ask {aid}. wait"}]}
    assert asks.bound(a, decide.Chain(KEY, base + [held, {"role": "user", "content": "x"}]))
    assert asks.bound(a, decide.Chain(KEY, base + [{**held, "content": f"ask {aid}"}]))          # as a bare string
    assert not asks.bound(a, decide.Chain(KEY, base + [{"role": "assistant", "content": "x"}, held]))   # not next in line
    assert not asks.bound(a, decide.Chain(KEY, base + [{**held, "role": "user"}]))                 # not an assistant turn
    assert not asks.bound(a, decide.Chain(KEY, [{"role": "user", "content": "go!"}, held]))        # another history
    assert not asks.bound(a, decide.Chain(KEY, []))                                                # a shorter one
    for bad in ({}, {"n": 1}, {"chain": ch.head}, {"n": True, "chain": ch.head}, {"n": "1", "chain": ch.head}):
        assert not asks.bound({"id": aid, **bad}, ch)                                              # a damaged ask binds nothing


def test_one_open_ask_per_chat_and_one_per_retry(tmp_path):
    asks = decide.Asks(tmp_path / "a.json", run="r", key=KEY)
    a1 = decide.Chain(KEY, [GO])
    b1 = decide.Chain(KEY, [GO, {"role": "assistant", "content": "x"}, {"role": "user", "content": "y"}])
    first = asks.open("coder", "s", "t", "call", "d", "c", 1.0, chain=a1)
    assert asks.open("coder", "s", "t", "call", "d", "c", 2.0, chain=a1) == first       # a retry of the same request
    assert asks.open("coder", "s", "t", "call", "d", "c", 2.0, chain=b1) != first       # another chat, same key
    held = {"role": "assistant", "content": [{"type": "text", "text": f"ask {first}"}]}
    later = decide.Chain(KEY, [GO, held, {"role": "user", "content": "ok"}])
    assert asks.open("coder", "s", "t", "call", "d", "c", 3.0, chain=later) == first     # the same chat, a later turn


def test_a_stash_is_kept_under_the_chat_and_found_only_there():
    stash = decide.Stash()
    ch_a, ch_b = decide.Chain(KEY, [GO]), decide.Chain(KEY, [GO, GO, GO])
    out = decide.Outcome(True, [], "end_turn", asks=["ask_1"], held_text="held")
    msg = {"content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": canon.loads('{"command": "ls"}')}]}
    assert decide.stash_turn(stash, "c", "m", out, msg, False, lambda s: False, chain=ch_a)
    assert decide.stash_turn(stash, "c", "m", out, msg, False, lambda s: False, chain=ch_b)
    assert len(stash._turns) == 2 and decide.stash_key("c", ch_a.head) in stash._turns
    assert decide.stash_key("c", None) == "c"
