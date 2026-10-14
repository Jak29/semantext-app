"""Semantext over MCP: the card and the inbox for any AI tool that speaks the Model Context Protocol. A client's own name
is a claim; there is no way to answer, and a rule is only ever a proposal."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import semantext
from semantext.agents import Agents
from semantext.inbox import Inbox
from semantext.mcp import TOOLS, Server
from semantext.store import Store


def rpc(server, method, params=None, rid=1):
    return server.handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def call(server, tool, **args):
    result = rpc(server, "tools/call", {"name": tool, "arguments": args})["result"]
    return result["isError"], result["content"][0]["text"]


def connect(store, cwd, client="Claude Desktop", version="2025-06-18"):
    s = Server(store, env={}, cwd=str(cwd))
    reply = rpc(s, "initialize", {"protocolVersion": version, "capabilities": {}, "clientInfo": {"name": client}})
    return s, reply["result"]


def test_the_handshake_hands_over_the_card(store, tmp_path):
    _, result = connect(store, tmp_path)
    assert result["protocolVersion"] == "2025-06-18" and result["serverInfo"]["name"] == "semantext"
    assert result["capabilities"] == {"tools": {}}
    assert "standing rules for reading this user" in result["instructions"]
    assert "base.irreversible-needs-your-word" in result["instructions"]
    assert connect(store, tmp_path, version="1999-01-01")[1]["protocolVersion"] == "2025-06-18"   # its newest


def test_no_tool_answers_or_changes_a_rule():
    names = {t["name"] for t in TOOLS}
    assert names == {"card", "ask", "answers", "close", "propose_rule", "decisions"}   # decisions only reads
    assert not names & {"answer", "teach", "toggle", "pin", "undo", "feature", "config", "hear", "forget"}


def test_a_client_is_a_claim_by_its_own_name(store, tmp_path):
    s, _ = connect(store, tmp_path)
    error, text = call(s, "ask", title="Merge?", why="It ships", question="Now or later?", options=["Now", "Later"])
    assert not error and text.startswith("[#1]")
    r = Inbox(store.root).get(1)
    assert (r["from"], r["from_how"], r["from_key"]) == ("claude-desktop", "claimed", "claim:claude-desktop")


def test_an_answer_reaches_the_asking_client_and_no_other(store, tmp_path):
    mine, _ = connect(store, tmp_path)
    other, _ = connect(store, tmp_path, client="Cursor")
    call(mine, "ask", title="Merge?", why="It ships", question="Now or later?", options=["Now", "Later"])
    Inbox(store.root).answer(1, "2", "after the review", via="page")
    assert "#1 Merge?: Later" in call(mine, "card")[1]                  # in its card's notes, like the hook's
    assert "Merge?" not in call(other, "answers")[1]
    error, text = call(other, "close", id=1)
    assert error and "not one of your requests" in text
    assert "#1 Merge?: Later" in call(mine, "answers")[1]
    assert "No new answers" in call(mine, "answers")[1]                 # read once, then marked


def test_a_rule_over_mcp_is_only_ever_a_proposal(store, tmp_path):
    s, _ = connect(store, tmp_path)
    before = store.card("default")
    error, text = call(s, "propose_rule", rule="Never push to main without asking me first.", why="You corrected me")
    assert not error and "Proposed, not learned" in text
    assert store.card("default") == before and Inbox(store.root).get(1)["kind"] == "rule"
    error, text = call(s, "propose_rule", rule="Cite every line.", for_me_only=True)
    assert error and "stated, not one the user bound" in text           # a claim gets no layer of its own


def test_a_folder_the_user_bound_names_the_client(store, tmp_path):
    Agents(store.root).bind("reviewer", tmp_path)
    s, _ = connect(store, tmp_path)
    error, _ = call(s, "propose_rule", rule="Cite every line.", for_me_only=True)
    assert not error and Inbox(store.root).get(1)["agent"] == "reviewer"
    assert Inbox(store.root).get(1)["from_how"] == "bound"


def test_an_agents_own_rules_follow_it_into_a_binding_over_mcp_too(store, tmp_path):
    app = tmp_path / "app"
    (app / ".git").mkdir(parents=True)
    store.learn("default", "Cite every line.", agent="claude-code@app")       # taught while it was seen as itself
    seen = Server(store, env={"CLAUDECODE": "1"}, cwd=str(app))
    assert "Cite every line." in call(seen, "card")[1]
    Agents(store.root).bind("reviewer", app)                                  # the user names it by its folder
    assert "Cite every line." in call(seen, "card")[1]                        # worked out afresh: the rule goes along
    other, _ = connect(store, tmp_path)                                        # a client's own name, elsewhere
    assert "Cite every line." not in call(other, "card")[1]


def test_the_protocol_s_edges(store, tmp_path):
    s, _ = connect(store, tmp_path)
    assert s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert s.handle({"jsonrpc": "2.0", "id": 9, "result": {}}) is None   # a client's own response: nothing to say
    assert rpc(s, "ping")["result"] == {}
    assert rpc(s, "resources/list")["error"]["code"] == -32601
    assert rpc(s, "tools/call", {"name": "answer", "arguments": {}})["error"]["code"] == -32602
    assert s.handle_line("{not json")["error"]["code"] == -32700
    assert s.handle({"id": 3, "method": "ping"})["error"]["code"] == -32600
    batch = s.handle_line(json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                      {"jsonrpc": "2.0", "method": "notifications/initialized"}]))
    assert batch == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    error, text = call(s, "ask", title="T", why="W", question="Q", options="ab")
    assert error and "list" in text


def test_a_broken_rule_file_leaves_the_base_rules_and_the_server_goes_on(store, tmp_path):
    s, _ = connect(store, tmp_path)
    (store.root / "profiles" / "default" / "SEMANTICS.yaml").write_text("- not a rule file\n", encoding="utf-8")
    error, text = call(s, "card")
    assert not error and "not a Semantext rule file" in text and "base.irreversible-needs-your-word" in text
    assert rpc(s, "ping")["result"] == {}


def test_it_speaks_over_standard_input_and_output(home, tmp_path):
    Store.open(home)
    src = str(Path(semantext.__file__).resolve().parent.parent)
    env = {**{k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID")},
           "SEMANTEXT_HOME": str(home), "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "Zed"}}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "card", "arguments": {}}}]
    r = subprocess.run([sys.executable, "-m", "semantext", "mcp"], input="".join(json.dumps(m) + "\n" for m in lines)
                       .encode("utf-8"), capture_output=True, env=env, cwd=tmp_path, timeout=60)
    replies = [json.loads(x) for x in r.stdout.decode("utf-8").splitlines() if x.strip()]
    assert r.returncode == 0 and [x["id"] for x in replies] == [1, 2, 3]
    assert "standing rules for reading this user" in replies[2]["result"]["content"][0]["text"]
    assert b"\r\n" not in r.stdout                                       # one message per line, plain newlines
