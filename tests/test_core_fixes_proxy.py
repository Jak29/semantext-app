"""The release path through the real proxy: pins for what the attacks on the replay work and the conversation key found.

  C3  the spend of answers the re-decision did not need ("left") is pinned: one yes never releases two calls.
  C4  a yes is scoped to its session; two identical calls in a held turn and one yes never emit two calls; an
      undeclared tool's ask is keyed by the tool, not by the word "undeclared"; a replay whose tools the request no
      longer declares goes to the model and leaves the yes unspent.
  C6  a chat is its system and its tools too, not only its messages.
  C7  `cache_control` is dropped only where it is a cache marker, never inside a tool_use input.

Each test names the mutant it fails on (changed temporarily in the code, the test seen to fail, the code put back).
"""
from __future__ import annotations

import copy
import time

import pytest

anthropic = pytest.importorskip("anthropic")

from semantext import decide  # noqa: E402
from tests.test_proxy import C, T, ask, env, json_turn, sse_turn  # noqa: E402,F401  (env is a fixture)
from tests.test_proxy_convkey import GO, RM as RM_CALL, _asks, _later, _proxy, _yes  # noqa: E402
from tests.test_replay_gaps import RM, history, hold, rigs, status, types, upstream_text, yes  # noqa: E402,F401


def tool_uses(msg):
    return [b for b in msg.content if b.type == "tool_use"]


# ================= C3: the left spend =================
def test_a_yes_the_redecision_did_not_need_is_spent_with_the_replay(rigs):              # mutant: `if False:` for `if left and not ...spend(left, now)`
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    gate = rig.space / "shell-held.yaml"
    old = gate.read_text(encoding="utf-8")
    gate.unlink()                                   # the person removes the gate and sets the space again
    rig.repin()
    got = ask(cl, True, history(note))              # the replay: the call needs no yes now
    assert types(got) == ["tool_use"]
    assert status(p, aid) == "spent", "the turn is the unit: its yes is spent with the replay"
    gate.write_text(old, encoding="utf-8")          # the gate comes back
    rig.repin()
    rig.stub.replies.append(sse_turn(T("again"), C("Bash", RM)))
    again = ask(cl, True)                           # the model makes the call again
    assert "tool_use" not in types(again), "the old yes released a second call"
    assert status(p, aid) == "spent"


def test_without_a_regate_the_yes_is_used_once_and_only_once(rigs):                      # control (must-pass)
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    assert types(ask(cl, True, history(note))) == ["tool_use"] and status(p, aid) == "spent"
    rig.stub.replies.append(sse_turn(T("again"), C("Bash", RM)))
    assert "tool_use" not in types(ask(cl, True))


# ================= C4: scoping and duplicates =================
def test_session_header_separates(rigs):                                                  # end to end; names NO mutant: since C8 the chain carries the session, so dropping the conv test from yes_for no longer fails it (that mutant is killed by test_core_fixes_left.py::test_a_yes_follows_the_conversation_key_not_only_the_chain)
    rig = rigs()
    p = rig.proxy

    def client(session):
        return anthropic.Anthropic(base_url=f"http://127.0.0.1:{rig.port}", api_key="sk-test-canary-0000000000000000",
                                   default_headers={"x-semantext-agent": "coder", "x-claude-code-session-id": session},
                                   max_retries=0)
    a, b = client("S1"), client("S2")
    note = hold(rig, a, C("Bash", RM))
    yes(p, p.asks._read()[0]["id"])
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))
    assert "tool_use" not in types(ask(b, True)), "a yes on S1 released the same call on S2"
    upstream_text(rig, b, history(note))                                                  # nor does S2 replay S1's turn
    assert types(ask(a, True, history(note))) == ["tool_use"]                              # control: S1 itself


@pytest.mark.parametrize("stream", [True, False])
def test_dup_calls_one_yes_never_two_calls(rigs, stream):                                 # mutant dup_both: `yes not in released` and the spend's length test removed
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM, "t1"), C("Bash", RM, "t2"))
    for a in p.asks._read():
        yes(p, a["id"])
    try:
        n = len(tool_uses(ask(cl, stream, history(note))))
    except anthropic.APIStatusError:
        n = 0
    assert n != 2, "one yes released two calls"
    assert len([a for a in p.asks._read() if a["status"] == "spent"]) <= 1


def test_two_identical_calls_re_issued_in_one_turn_release_one(rigs):                     # mutant: `if yes and yes not in released` -> `if yes`, with the spend length test removed
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    hold(rig, cl, C("Bash", RM, "t1"))
    yes(p, p.asks._read()[0]["id"])
    rig.stub.replies.append(sse_turn(T("x"), C("Bash", RM, "t1"), C("Bash", RM, "t2")))
    got = ask(cl, True)
    assert len(tool_uses(got)) != 2 and "tool_use" not in types(got)       # the second is held, so the turn is
    assert status(p, p.asks._read()[0]["id"]) == "yes"                      # and nothing was spent


def test_a_yes_on_one_undeclared_tool_releases_no_other(rigs):                             # mutant: the key "undeclared:<digest>" -> "undeclared"
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    inp = {"x": "1"}
    hold(rig, cl, C("SendEmail", inp))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("again"), C("DeleteFile", inp)))
    assert "tool_use" not in types(ask(cl, True)), "a yes on SendEmail released DeleteFile with the same input"
    assert status(p, aid) == "yes"
    assert len(p.asks._read()) == 2                                          # the other tool has its own ask
    assert p.asks._read()[0]["tool"] != p.asks._read()[1]["tool"]
    assert p.asks._read()[0]["tool"].startswith("undeclared:")


def test_a_kept_call_to_a_tool_the_request_never_declared_is_not_replayed(rigs):           # mutant: `if any(c.get("name") not in declared ...)` -> `if False:`
    """U3c. The model made a gated call to a tool this request does not offer (here Bash, with only Read declared):
    the turn is held and kept, the person says yes, and the same request comes again. Replaying it would hand the
    client a call to a tool it does not have; it goes to the model instead, and the yes stays unspent. (Since C6 the
    tools list is part of the chat, so a request that DROPS a tool later is another chat and finds no kept turn at
    all: the check is for a call the request never offered.)"""
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    only_read = [{"name": "Read", "description": "r", "input_schema": {"type": "object"}}]
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))
    note = go(cl, [GO], "attribution block", only_read).content[-1].text
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    got = go(cl, [GO, {"role": "assistant", "content": [T("deleting"), T(note)]}, {"role": "user", "content": "carry on"}],
             "attribution block", only_read)
    assert [b.type for b in got.content] == ["text"] and status(p, aid) == "yes"
    assert len(rig.stub.log) == 2                                                          # it went to the model


def test_a_request_that_drops_the_tool_later_finds_no_kept_turn(rigs):                     # the attacker's case, now met by the chain (C6)
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(json_turn(T("ok"), stop="end_turn"))
    got = cl.messages.create(model="claude-opus-5-5", max_tokens=10, system="attribution block", messages=history(note),
                             tools=[{"name": "Read", "description": "r", "input_schema": {"type": "object"}}])
    assert types(got) == ["text"] and status(p, aid) == "yes"                # to the model, and the yes unspent
    assert types(ask(cl, True, history(note))) == ["tool_use"]               # control: with the tool declared, it replays


# ================= C6: a chat is its system and its tools too =================
def go(client, messages, system, tools):
    with client.messages.stream(model="claude-opus-5-5", max_tokens=100, system=system, messages=messages,
                                tools=tools) as s:
        return s.get_final_message()


MARK = {"type": "ephemeral"}
SYS_A = [{"type": "text", "text": "attribution block"}, {"type": "text", "text": "cwd=/projA"}]
SYS_B = [{"type": "text", "text": "attribution block"}, {"type": "text", "text": "cwd=/projB"}]
TOOLS = [{"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
         {"name": "Read", "description": "read", "input_schema": {"type": "object"}}]
TOOLS_OTHER = [{"name": "Bash", "description": "DIFFERENT", "input_schema": {"type": "object", "properties": {"x": {}}}},
               {"name": "Read", "description": "read", "input_schema": {"type": "object"}}]


def held_in(env, system=SYS_A, tools=TOOLS, messages=None):
    stub, client, port, home, server = env
    stub.replies.append(sse_turn(T("deleting"), RM_CALL))
    note = go(client, messages or [GO], system, tools).content[-1].text
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    return note, aid


@pytest.mark.parametrize("which", ["system", "tools"])
def test_the_same_messages_under_another_system_or_tools_are_another_chat(env, which):    # mutant: Chain ignores system / tools (the start digest as before)
    stub, client, port, home, server = env
    note, aid = held_in(env)
    other = {"system": SYS_B, "tools": TOOLS} if which == "system" else {"system": SYS_A, "tools": TOOLS_OTHER}
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    got = go(client, [GO], **other)                                           # the model re-issues the call there
    assert "tool_use" not in [b.type for b in got.content], "a yes in one chat released the call in another"
    assert _proxy(server).asks.status(aid, time.monotonic()) == "yes" and len(_asks(server)) == 2
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))                    # nor does the other chat replay the turn
    got = go(client, _later([GO], note), **other)
    assert [b.type for b in got.content] == ["text"] and _proxy(server).asks.status(aid, time.monotonic()) == "yes"


def test_the_same_chat_replays_once(env):                                          # control (must-pass)
    stub, client, port, home, server = env
    note, aid = held_in(env)
    got = go(client, _later([GO], note), SYS_A, TOOLS)
    assert [b.type for b in got.content] == ["tool_use"]
    assert _proxy(server).asks.status(aid, time.monotonic()) == "spent"


def _marked(system, tools):
    system, tools = copy.deepcopy(system), copy.deepcopy(tools)
    for b in system:                       # the first system block too: the conversation key reads it
        b["cache_control"] = MARK
    tools[-1]["cache_control"] = MARK
    return system, tools


def test_cache_markers_moved_on_system_tools_and_messages_still_replay_once(env):        # mutant: markers kept in the start digest
    stub, client, port, home, server = env
    note, aid = held_in(env)
    sysm, toolsm = _marked(SYS_A, TOOLS)
    marked_first = [{"role": "user", "content": [{"type": "text", "text": "go", "cache_control": MARK}]}]
    later = marked_first + [{"role": "assistant", "content": [T("deleting"), T(note)]},
                            {"role": "user", "content": [{"type": "text", "text": "carry on", "cache_control": MARK}]}]
    got = go(client, later, sysm, toolsm)
    assert [b.type for b in got.content] == ["tool_use"], "markers moved and the held turn was no longer found"
    assert _proxy(server).asks.status(aid, time.monotonic()) == "spent"


def test_cache_markers_moved_still_release_a_re_issued_call_once(env):                     # mutant: markers kept in the start digest
    stub, client, port, home, server = env
    note, aid = held_in(env)
    sysm, toolsm = _marked(SYS_A, TOOLS)
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    got = go(client, [{"role": "user", "content": [{"type": "text", "text": "go", "cache_control": MARK}]}], sysm, toolsm)
    assert [b.type for b in got.content] == ["text", "tool_use"]
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    got = go(client, [GO], sysm, toolsm)
    assert "tool_use" not in [b.type for b in got.content], "one yes released twice"


# ================= C7: cache_control only as a marker =================
KEY = b"k" * 32


def head(messages, system=None, tools=None):
    return decide.Chain(KEY, messages, system, tools).head


def hist(inp):
    return [GO, {"role": "assistant", "content": [C("Read", inp, "toolu_9")]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_9", "content": "x"}]}]


def test_a_cache_control_field_in_a_tool_input_is_data_not_a_marker():                    # mutant: _no_cache at every depth
    assert head(hist({"path": "a", "cache_control": "z"})) != head(hist({"path": "a"}))
    assert head(hist({"path": "a", "o": {"cache_control": MARK}})) != head(hist({"path": "a", "o": {}}))


def test_a_cache_control_field_in_a_tool_schema_is_data_too():
    one = [{"name": "T", "input_schema": {"type": "object", "properties": {"cache_control": {"type": "string"}}}}]
    two = [{"name": "T", "input_schema": {"type": "object", "properties": {}}}]
    assert head([GO], tools=one) != head([GO], tools=two)


def test_markers_on_text_tool_use_tool_result_and_nested_blocks_make_no_difference():       # control (must-pass)
    plain = [GO, {"role": "assistant", "content": [T("a"), C("Read", {"path": "a"}, "toolu_9")]},
             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_9",
                                           "content": [T("out"), {"type": "tool_result", "content": [T("deep")]}]}]},
             {"role": "assistant", "content": "ok"}, {"role": "user", "content": "more"}]
    marked = copy.deepcopy(plain)
    marked[0] = {"role": "user", "content": [{"type": "text", "text": "go", "cache_control": MARK}]}
    marked[1]["content"][0]["cache_control"] = MARK                          # a text block
    marked[1]["content"][1]["cache_control"] = MARK                          # a tool_use block (its input untouched)
    res = marked[2]["content"][0]
    res["cache_control"] = MARK                                              # the tool_result
    res["content"][0]["cache_control"] = MARK                                # a block in its content list
    res["content"][1]["cache_control"] = MARK                                # a nested tool_result
    res["content"][1]["content"][0]["cache_control"] = MARK                  # and a block inside that
    marked[4] = {"role": "user", "content": [{"type": "text", "text": "more", "cache_control": MARK}]}
    sysm, toolsm = _marked(SYS_A, TOOLS)
    assert head(marked, sysm, toolsm) == head(plain, SYS_A, TOOLS)
    assert head(marked, sysm, toolsm) != head(plain, SYS_B, TOOLS)                # the control that can fail


def test_the_attackers_case_through_the_proxy_is_held(env):                                # mutant: _no_cache at every depth
    stub, client, port, home, server = env
    ha = [GO, {"role": "assistant", "content": [C("Read", {"path": "a", "cache_control": "z"}, "toolu_9")]},
          {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_9", "content": "x"}]}]
    hb = copy.deepcopy(ha)
    del hb[1]["content"][0]["input"]["cache_control"]
    note, aid = held_in(env, messages=ha)
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    got = go(client, hb, SYS_A, TOOLS)
    assert "tool_use" not in [b.type for b in got.content], "a chat that differs only in a tool input was the same chat"
    assert _proxy(server).asks.status(aid, time.monotonic()) == "yes"
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert [b.type for b in go(client, ha, SYS_A, TOOLS).content] == ["text", "tool_use"]   # control: its own chat
