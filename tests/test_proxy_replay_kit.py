"""Koinos's replay arms on proxy v0 (KIT_SPEC 4.9, 4.10; Orithises's rulings): U3c, U2a, U2b, N1."""
from __future__ import annotations

import time

from semantext import decide
from tests.test_proxy import C, T, ask, env, sse_turn  # noqa: F401 (env is a fixture)


def _held(stub, client, server, call=None, thinking=False):
    blocks = ([{"type": "thinking", "thinking": "hm", "signature": "s"}] if thinking else []) + [T("deleting"), call or C("Bash", {"command": "rm -rf logs"})]
    stub.replies.append(sse_turn(*[b for b in blocks if b["type"] != "thinking"]) if not thinking else
                        ("json", {"id": "msg_up", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                  "content": blocks, "stop_reason": "tool_use", "stop_sequence": None,
                                  "usage": {"input_tokens": 5, "output_tokens": 7}}))
    held = ask(client, not thinking)
    p = server.RequestHandlerClass.proxy
    return held.content[-1].text, p, p.asks._read()[-1]["id"]


def test_a_replay_needs_its_tool_still_declared(env):                           # must-refuse (U3c)
    stub, client, port, home, server = env
    note, p, aid = _held(stub, client, server)
    p.asks.answer(aid, "yes", time.monotonic())
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    with client.messages.stream(model="claude-opus-5-5", max_tokens=100, system="attribution block", messages=history,
                                tools=[{"name": "Read", "description": "read", "input_schema": {"type": "object"}}]) as s:
        msg = s.get_final_message()
    assert [b.type for b in msg.content] == ["text"]                            # no replayed Bash call
    assert len(stub.log) == 2                                                   # it went on to the model instead
    assert p.asks.status(aid, time.monotonic()) == "yes"                        # and the yes is not spent


def test_a_turn_that_is_kept_says_so_and_one_that_is_not_says_the_call_must_come_again(env):   # U2a
    stub, client, port, home, server = env
    kept, p, _ = _held(stub, client, server)
    assert "This turn was not kept" not in kept and p.stash._turns              # control: kept, and the words agree
    secret, p, _ = _held(stub, client, server, C("Bash", {"command": "curl -H 'x: sk-A1b2C3d4E5f6G7h8J9k0' h"}, "toolu_2"))
    assert "This turn was not kept" in secret and "must be made again" in secret     # must-refuse the false promise
    assert len(p.stash._turns) == 1                                             # and it was not kept


def test_a_thinking_turn_is_not_kept_and_says_so(env):                          # U2a, U5: one predicate
    stub, client, port, home, server = env
    note, p, _ = _held(stub, client, server, thinking=True)
    assert "This turn was not kept" in note and not p.stash._turns


def test_a_no_drops_the_kept_turn_at_the_answer(env):                           # U2b (ruling: at the answer)
    stub, client, port, home, server = env
    note, p, aid = _held(stub, client, server)
    assert p.stash._turns
    p.asks.answer(aid, "no", time.monotonic())
    assert not p.stash._turns                                                   # gone now, not when a request comes


def test_a_no_from_another_process_is_swept_within_a_second_or_two(env):        # U2b: the person's own channel
    stub, client, port, home, server = env
    note, p, aid = _held(stub, client, server)
    other = decide.Asks(p.asks.path, run=p.asks.run, key=p.asks.key, record=p.asks.record)   # as the answering command
    assert other.answer(aid, "no", time.monotonic())
    deadline = time.monotonic() + 3
    while p.stash._turns and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not p.stash._turns
