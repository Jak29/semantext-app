"""C8 (C6 refined): with a session header the session and the history are the chat; without one the system and the tools
are part of it too.

Claude Code sends x-claude-code-session-id, and its tools list and a system block can change inside one session (tools
loaded on demand, MCP servers connecting, a date). C6 made the system and the tools part of every chat's identity, so
there a yes stopped finding its call and the person was asked again. Now the chain's start covers the system and the
tools only when the request has no session header. A system given as one string is one text block, as messages are.

Each test names the mutant it fails on (changed temporarily, the test seen to fail, the code put back).
"""
from __future__ import annotations

import copy
import time

import pytest

anthropic = pytest.importorskip("anthropic")

from semantext import decide, proxy  # noqa: E402
from tests.test_core_fixes_proxy import SYS_A, SYS_B, TOOLS, go  # noqa: E402
from tests.test_proxy import T, env, sse_turn  # noqa: E402,F401  (env is a fixture)
from tests.test_proxy_convkey import GO, RM as RM_CALL, _asks, _later, _proxy, _yes  # noqa: E402

KEY = b"k" * 32
TOOLS_MORE = TOOLS + [{"name": "Grep", "description": "loaded on demand", "input_schema": {"type": "object"}}]
SYS_A_STR = "attribution block"
SYS_A_BLOCK = [{"type": "text", "text": "attribution block"}]


def client_for(port, session=None):
    headers = {"x-semantext-agent": "coder"}
    if session:
        headers["x-claude-code-session-id"] = session
    return anthropic.Anthropic(base_url=f"http://127.0.0.1:{port}", api_key="sk-test-canary-0000000000000000",
                               default_headers=headers, max_retries=0)


def hold_and_yes(env, client, system, tools):
    stub, _c, port, home, server = env
    stub.replies.append(sse_turn(T("deleting"), RM_CALL))
    note = go(client, [GO], system, tools).content[-1].text
    aid = _asks(server)[0]["id"]
    _yes(server, aid)
    return note, aid


def kinds(msg):
    return [b.type for b in msg.content]


def status(server, aid):
    return _proxy(server).asks.status(aid, time.monotonic())


CHANGES = {"a tool added": (SYS_A, TOOLS_MORE), "a system block changed": (SYS_B, TOOLS),
           "both": (SYS_B, TOOLS_MORE)}


# ---- with a session header: the system and the tools may change inside the chat ----
@pytest.mark.parametrize("change", list(CHANGES))
def test_session_header_replay_survives_a_changed_system_or_tools(env, change):        # mutant: the start digest covers system and tools whatever the header
    stub, _c, port, home, server = env
    cl = client_for(port, "S1")
    note, aid = hold_and_yes(env, cl, SYS_A, TOOLS)
    system, tools = CHANGES[change]
    got = go(cl, _later([GO], note), system, tools)
    assert kinds(got) == ["tool_use"], "the session's yes was lost when the client changed its system or tools"
    assert status(server, aid) == "spent"


@pytest.mark.parametrize("change", list(CHANGES))
def test_session_header_re_issued_call_survives_a_changed_system_or_tools_and_releases_once(env, change):  # same mutant
    stub, _c, port, home, server = env
    cl = client_for(port, "S1")
    note, aid = hold_and_yes(env, cl, SYS_A, TOOLS)
    system, tools = CHANGES[change]
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert kinds(go(cl, [GO], system, tools)) == ["text", "tool_use"]
    assert status(server, aid) == "spent"
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert "tool_use" not in kinds(go(cl, [GO], system, tools)), "one yes released twice"


def test_session_header_a_different_session_with_identical_messages_is_another_chat(env):   # mutant: the session left out of the start digest and the conversation key
    stub, _c, port, home, server = env
    a, b = client_for(port, "S1"), client_for(port, "S2")
    note, aid = hold_and_yes(env, a, SYS_A, TOOLS)
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert "tool_use" not in kinds(go(b, [GO], SYS_A, TOOLS)), "a yes in S1 released the call in S2"
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    assert kinds(go(b, _later([GO], note), SYS_A, TOOLS)) == ["text"]
    assert status(server, aid) == "yes"
    assert kinds(go(a, _later([GO], note), SYS_A, TOOLS)) == ["tool_use"]                # control: S1 itself


def test_session_header_edited_history_is_still_another_chat(env):                     # names NO mutant: the edit is a different first/next message the conversation key and Chain.holds already catch; the history-out-of-chain mutant is killed by test_core_fixes_left.py::test_an_earlier_message_edited_is_another_chat_though_the_first_is_the_same
    stub, _c, port, home, server = env
    cl = client_for(port, "S1")
    note, aid = hold_and_yes(env, cl, SYS_A, TOOLS)
    edited = [{"role": "user", "content": "go"}, {"role": "assistant", "content": "something else"},
              {"role": "user", "content": "again"}]
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert "tool_use" not in kinds(go(cl, edited, SYS_A, TOOLS))
    assert status(server, aid) == "yes"


# ---- without a session header: they are part of the chat (C6 stays) ----
@pytest.mark.parametrize("change", list(CHANGES))
def test_no_session_header_a_changed_system_or_tools_is_another_chat_held_again(env, change):   # mutant: the start digest never covers them
    stub, client, port, home, server = env
    note, aid = hold_and_yes(env, client, SYS_A, TOOLS)
    system, tools = CHANGES[change]
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert "tool_use" not in kinds(go(client, [GO], system, tools)), "no session header: another chat was released"
    assert status(server, aid) == "yes" and len(_asks(server)) == 2                      # asked again, the old yes unspent
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    assert kinds(go(client, _later([GO], note), system, tools)) == ["text"]
    assert kinds(go(client, _later([GO], note), SYS_A, TOOLS)) == ["tool_use"]           # control: its own chat


# ---- one string is one block ----
def test_a_string_system_and_the_same_text_as_one_block_are_one_chat(env):               # mutant: plain_system leaves a string a string
    stub, client, port, home, server = env
    note, aid = hold_and_yes(env, client, SYS_A_STR, TOOLS)
    got = go(client, _later([GO], note), SYS_A_BLOCK, TOOLS)
    assert kinds(got) == ["tool_use"], "the string and the block spelling were two chats"
    assert status(server, aid) == "spent"


def test_a_string_system_and_one_block_re_issue_releases_once(env):                       # same mutant
    stub, client, port, home, server = env
    note, aid = hold_and_yes(env, client, SYS_A_BLOCK, TOOLS)
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert kinds(go(client, [GO], SYS_A_STR, TOOLS)) == ["text", "tool_use"]
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert "tool_use" not in kinds(go(client, [GO], SYS_A_STR, TOOLS))


def test_a_string_system_with_other_text_is_another_chat(env):                           # control that can fail
    stub, client, port, home, server = env
    note, aid = hold_and_yes(env, client, SYS_A_STR, TOOLS)
    stub.replies.append(sse_turn(T("again"), RM_CALL))
    assert "tool_use" not in kinds(go(client, [GO], "attribution block!", TOOLS))
    assert status(server, aid) == "yes"


# ---- the chain, alone ----
def head(session=None, system=None, tools=None, messages=None):
    return decide.Chain(KEY, messages or [GO], system, tools, session).head


def test_chain_with_a_session_ignores_system_and_tools_but_not_the_session():          # mutant: start covers system/tools whatever the session
    assert head("S1", SYS_A, TOOLS) == head("S1", SYS_B, TOOLS_MORE) == head("S1")
    assert head("S1", SYS_A, TOOLS) != head("S2", SYS_A, TOOLS)
    assert head("S1", messages=[GO]) != head("S1", messages=[GO, GO])


def test_chain_without_a_session_covers_system_and_tools():                              # mutant: start never covers them
    assert head(None, SYS_A, TOOLS) != head(None, SYS_B, TOOLS)
    assert head(None, SYS_A, TOOLS) != head(None, SYS_A, TOOLS_MORE)
    assert head(None, SYS_A, TOOLS) == head("", SYS_A, TOOLS) == head(None, copy.deepcopy(SYS_A), copy.deepcopy(TOOLS))
    assert head(None, SYS_A, TOOLS) != head("S1", SYS_A, TOOLS)                           # a session is not "no session"


def test_chain_string_system_is_one_text_block():                                         # mutant: plain_system leaves a string a string
    assert head(None, SYS_A_STR, TOOLS) == head(None, SYS_A_BLOCK, TOOLS)
    assert head(None, SYS_A_STR, TOOLS) != head(None, "attribution block!", TOOLS)
    assert head(None, SYS_A_STR, TOOLS) != head(None, None, TOOLS)


def test_conversation_key_reads_a_string_system_as_one_block():                          # mutant: conversation_key reads the raw system
    k = proxy.conversation_key
    assert k(KEY, {"system": SYS_A_STR, "messages": [GO]}, None, "coder") == \
        k(KEY, {"system": SYS_A_BLOCK, "messages": [GO]}, None, "coder")
    assert k(KEY, {"system": SYS_A_STR, "messages": [GO]}, None, "coder") != \
        k(KEY, {"system": "other", "messages": [GO]}, None, "coder")
