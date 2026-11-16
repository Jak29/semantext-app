"""The replay and release gaps of the proxy, end to end (A08, U2c, U3a, U3b, U4e) and the whitespace scan bound.

Everything here goes through the real proxy: the Anthropic SDK -> the proxy -> a loopback stub upstream. The person's
answers are given on the proxy's own asks (as the app or the CLI would, from their channel).

  A08  a yes for one held call releases or replays only that call: not one made by another agent, in another space,
       to another tool, or with an input that differs by one byte. What counts as the same act is canon's: key order,
       whitespace and string escapes do not change it; the written form of a number does (1 and 1.0 are two acts).
  U2c  a restart between the ask and the replay: the kept turn is gone and the old yes is void.
  U3a  a gate added between the yes and the replay: the call that the person answered still goes (their yes is for the
       act); a call of the turn that was not asked about and is now gated is HELD, and the replay is refused.
  U3b  any other change to the blocks: refused (X-DIGEST) until the person sets the space again; after they do, a
       call the space no longer allows is held and the replay is refused (X-REL). Never released silently.
  U4e  a turn of 20 held calls replays whole or not at all.
  The scan bound: the spaces around "password =" and "password is" are bounded at 256 in a long input, on both sides.
"""
from __future__ import annotations

import shutil
import threading
import time

import pytest

anthropic = pytest.importorskip("anthropic")

from semantext import blocks, canon, proxy  # noqa: E402
from tests.test_blocks import GOOD  # noqa: E402
from tests.test_proxy import CARD, CODER, READ, C, Stub, T, ask, free_port, sse_turn  # noqa: E402
from tests.test_proxy_scan_windows import EDGES, O, W  # noqa: E402

RM = {"command": "rm -rf logs"}
now = time.monotonic

OTHER_AGENT = CODER.replace("id: coder", "id: other")
READ_GATE = ("id: read-held\nkind: gate\nmatch: {tools: [read]}\nanswer: [person]\non_timeout: refuse\n"
             "tests:\n  - name: a read waits\n    given: {tool: Read}\n    expect: hold\n")
BASH_GATE_2 = READ_GATE.replace("read-held", "bash-held-too").replace("[read]", "[bash]").replace("Read", "Bash")


class Rig:
    """One proxy with its own stub upstream, space folder and home."""

    def __init__(self, stub, space, home, extra):
        self.stub, self.space, self.home, self.extra = stub, space, home, extra
        self.port = free_port()
        ready = threading.Event()
        threading.Thread(target=proxy.serve, args=(space, home, CARD, self.port), kwargs={"ready": ready},
                         daemon=True).start()
        assert ready.wait(5)
        self.server, self.stopped = ready.server, False

    @property
    def proxy(self):
        return self.server.RequestHandlerClass.proxy

    def client(self, agent="coder"):
        return anthropic.Anthropic(base_url=f"http://127.0.0.1:{self.port}", api_key="sk-test-canary-0000000000000000",
                                   default_headers={"x-semantext-agent": agent}, max_retries=0)

    def stop(self):
        if not self.stopped:
            self.stopped = True
            self.server.shutdown()
            self.server.server_close()

    def restart(self):
        """A new proxy run over the same space and home (the person stopped it and started it again)."""
        self.stop()
        return Rig(self.stub, self.space, self.home, self.extra)

    def repin(self):
        """The person sets the space again (P8: their own act, a restart): the blocks as they are now are the pin."""
        self.proxy.expected = blocks.load(self.space).digest


@pytest.fixture
def rigs(tmp_path):
    made, stubs = [], []

    def make(extra=None):
        stub = Stub()
        stubs.append(stub)
        root = tmp_path / f"r{len(made)}"
        space = root / "space"
        space.mkdir(parents=True)
        model = (f"id: claude\nkind: model\nprovider: anthropic\nmodel: claude-opus-5-5\n"
                 f"endpoint: http://127.0.0.1:{stub.port}\ncredential_host: 127.0.0.1\ntests: []\n")
        for name, text in {**GOOD, "claude.yaml": model, "read.yaml": READ, "coder.yaml": CODER,
                           **(extra or {})}.items():
            (space / name).write_text(text, encoding="utf-8")
        rig = Rig(stub, space, root / "home", extra)
        made.append(rig)
        return rig

    yield make
    for r in made:
        r.stop()
    for s in stubs:
        s.server.shutdown()


# ---- helpers ----
def types(msg):
    return [b.type for b in msg.content]


def history(note, first="go"):
    return [{"role": "user", "content": first},
            {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": note}]},
            {"role": "user", "content": "carry on"}]


def hold(rig, client, *calls):
    """The model makes these calls and the proxy holds the turn. Returns the held text."""
    rig.stub.replies.append(sse_turn(T("deleting"), *calls))
    held = ask(client, True)
    assert "tool_use" not in types(held), "a held turn emits no call"
    return held.content[-1].text


def yes(p, aid):
    assert p.asks.answer(aid, "yes", now())


def status(p, aid):
    return p.asks.status(aid, now())


def upstream_text(rig, client, messages=None):
    """A request that must go on to the model: the stub answers with text, and nothing is replayed."""
    rig.stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    got = ask(client, True, messages)
    assert types(got) == ["text"]
    return got


def refused(client, messages, rule):
    with pytest.raises(anthropic.APIStatusError) as e:
        ask(client, True, messages)
    assert e.value.status_code == 400 and rule in str(e.value)


def raw_turn(name, raw, tid="toolu_1"):
    """One call whose input is written exactly as `raw` (key order, spaces and number spelling kept)."""
    kind, ev = sse_turn(C(name, {}, tid))
    for _, d in ev:
        if d.get("delta", {}).get("type") == "input_json_delta":
            d["delta"]["partial_json"] = raw
    return kind, ev


def records(p, kind):
    return [r for r in p.record.lines() if r.get("kind") == kind]


# ================= A08: a yes releases exactly the call it was given for =================
def test_a_yes_for_one_agents_call_releases_no_other_agents_call(rigs):         # A08a (call by another agent)
    rig = rigs({"other.yaml": OTHER_AGENT})
    a, b, p = rig.client("coder"), rig.client("other"), rig.proxy
    hold(rig, a, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))             # the other agent makes the same call
    got = ask(b, True)
    assert "tool_use" not in types(got) and got.content[-1].text.startswith("[semantext] ")
    asks = p.asks._read()
    assert {x["agent"] for x in asks} == {"coder", "other"} and status(p, aid) == "yes"   # its own ask, theirs unspent
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))             # control: the agent that was answered
    assert "tool_use" in types(ask(a, True)) and status(p, aid) == "spent"


def test_another_agents_request_neither_replays_nor_spoils_a_held_turn(rigs):   # A08a (replay to another agent)
    rig = rigs({"other.yaml": OTHER_AGENT})
    a, b, p = rig.client("coder"), rig.client("other"), rig.proxy
    note = hold(rig, a, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    upstream_text(rig, b, history(note))                                        # same chat, sent by the other agent
    assert len(rig.stub.log) == 2 and status(p, aid) == "yes"                   # it went to the model; nothing spent
    got = ask(a, True, history(note))                                           # control: the turn is still the first
    assert types(got) == ["tool_use"] and len(rig.stub.log) == 2 and status(p, aid) == "spent"


def test_a_yes_in_one_space_releases_nothing_in_another(rigs):                  # A08b
    r1, r2 = rigs(), rigs()
    p1, p2 = r1.proxy, r2.proxy
    note = hold(r1, r1.client(), C("Bash", RM))
    aid = p1.asks._read()[0]["id"]
    yes(p1, aid)
    shutil.copy(r1.home / "asks.json", r2.home / "asks.json")                   # even the answered ask itself, copied in
    r2.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))
    got = ask(r2.client(), True)
    assert "tool_use" not in types(got)                                         # the same call is held in the other space
    upstream_text(r2, r2.client(), history(note))                               # and its held text replays nothing there
    assert len(r2.stub.log) == 2 and not [a for a in p2.asks._read() if a["status"] == "spent"]
    assert status(p1, aid) == "yes"
    assert types(ask(r1.client(), True, history(note))) == ["tool_use"]         # control: in its own space it replays


@pytest.mark.parametrize("other", ["Read", "Foo"], ids=["a declared tool", "a tool the agent may not call"])
def test_a_yes_for_one_tool_releases_no_other_tool(rigs, other):                # A08c
    rig = rigs({"read-held.yaml": READ_GATE})
    cl, p = rig.client(), rig.proxy
    hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("x"), C(other, RM)))                     # the same input, another tool
    got = ask(cl, True)
    assert "tool_use" not in types(got) and status(p, aid) == "yes"
    assert len([a for a in p.asks._read() if a["status"] == "open"]) == 1
    rig.stub.replies.append(sse_turn(T("x"), C("Bash", RM)))                    # control: the tool it was given for
    assert "tool_use" in types(ask(cl, True)) and status(p, aid) == "spent"


@pytest.mark.parametrize("changed", [{"command": "rm -rf log"}, {"command": "rm -rf logs "},
                                     {"command": "rm -rf Logs"}, {"command": "rm -rf l0gs"},
                                     {"command": "rm -rf logs\n"}, {"cmd": "rm -rf logs"},
                                     {"command": "rm -rf logs", "x": ""}],
                         ids=["a byte less", "a trailing space", "one capital", "one digit", "a newline", "a key",
                              "a field more"])
def test_a_yes_does_not_release_an_input_that_differs_by_one_byte(rigs, changed):   # A08d
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    rig.stub.replies.append(sse_turn(T("x"), C("Bash", changed)))               # the model re-issues a near copy
    assert "tool_use" not in types(ask(cl, True)) and status(p, aid) == "yes"
    rig.stub.replies.append(sse_turn(T("x"), C("Bash", RM)))                    # control: the exact call is released
    assert "tool_use" in types(ask(cl, True)) and status(p, aid) == "spent"


def test_a_replay_sends_the_kept_call_whatever_the_client_says_it_was(rigs):     # A08d (the replay side)
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    yes(p, p.asks._read()[0]["id"])
    said = [{"role": "user", "content": "go"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash",
                                               "input": {"command": "rm -rf /"}}, {"type": "text", "text": note}]},
            {"role": "user", "content": "carry on"}]
    got = ask(cl, True, said)
    assert types(got) == ["tool_use"] and got.content[0].input == RM            # the kept bytes, not the client's


def test_a_revoke_from_another_process_is_swept_from_memory(rigs):             # U2b (found by U4e: it read 'unproved')
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    other = type(p.asks)(p.asks.path, run=p.asks.run, key=p.key, record=p.record)   # the person's own process
    assert other.answer(aid, "revoke", now())
    assert status(p, aid) == "revoked" and p.stash._turns
    assert p.stash.sweep(p.asks, now()) == 1 and not p.stash._turns


@pytest.mark.parametrize("spelled", [
    '{"cwd":"/a","command":"rm -rf logs"}',
    '{ "command" : "rm -rf logs" ,\n\t"cwd" :\r\n "/a" }',
    '{"command":"\\u0072m -rf logs","cwd":"\\u002fa"}'], ids=["key order", "whitespace", "string escapes"])
def test_the_same_act_in_another_spelling_is_released(rigs, spelled):           # canon: these are one act
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    rig.stub.replies.append(raw_turn("Bash", '{"command":"rm -rf logs","cwd":"/a"}'))
    assert "tool_use" not in types(ask(cl, True))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    assert canon.d_act(canon.loads(spelled)) == canon.d_act(canon.loads('{"command":"rm -rf logs","cwd":"/a"}'))
    rig.stub.replies.append(raw_turn("Bash", spelled))
    assert "tool_use" in types(ask(cl, True)) and status(p, aid) == "spent"


@pytest.mark.parametrize("written,others", [
    ("1", ["1.0", "1e0", "1.00", "10E-1", "0.1e1", "1E+0"]),
    ("9007199254740993", ["9007199254740992", "9007199254740993.0"]),
    ("0", ["-0", "0.0", "0e0"])], ids=["one", "above 2^53", "zero"])
def test_a_number_written_another_way_is_another_act(rigs, written, others):    # canon: numbers keep their own text
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    rig.stub.replies.append(raw_turn("Bash", '{"n":' + written + '}'))
    ask(cl, True)
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    for other in others:
        rig.stub.replies.append(raw_turn("Bash", '{"n":' + other + '}'))
        assert "tool_use" not in types(ask(cl, True)), other
        assert status(p, aid) == "yes", other
    rig.stub.replies.append(raw_turn("Bash", '{"n":' + written + '}'))          # control: the number as it was written
    assert "tool_use" in types(ask(cl, True)) and status(p, aid) == "spent"


# ================= U2c: a restart =================
@pytest.mark.parametrize("restart", [False, True], ids=["same run (control)", "after a restart"])
def test_a_restart_between_the_ask_and_the_replay(rigs, restart):               # U2c
    rig = rigs()
    p = rig.proxy
    note = hold(rig, rig.client(), C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    cur = rig.restart() if restart else rig
    cl, p2 = cur.client(), cur.proxy
    if not restart:
        assert types(ask(cl, True, history(note))) == ["tool_use"] and len(rig.stub.log) == 1   # replayed, no upstream
        return
    assert p2.asks.run != p.asks.run and not p2.stash._turns                    # a new run; the kept turn died with the old
    assert status(p2, aid) == "expired"                                         # and its yes is void
    upstream_text(cur, cl, history(note))                                       # the held text replays nothing
    assert len(rig.stub.log) == 2
    rig.stub.replies.append(sse_turn(T("deleting"), C("Bash", RM)))             # the model makes the call again
    assert "tool_use" not in types(ask(cl, True))                               # the old yes does not release it
    fresh = [a for a in p2.asks._read() if a["status"] == "open"]
    assert len(fresh) == 1 and fresh[0]["id"] != aid and fresh[0]["run"] == p2.asks.run
    assert p2.asks.yes_for("coder", "space", fresh[0]["tool"], fresh[0]["d_act"], fresh[0]["conv"], now()) is None
    assert not [a for a in p2.asks._read() if a["status"] == "spent"]


# ================= U3: the space changes between the yes and the replay =================
def _two_call_turn(rig, cl):
    return hold(rig, cl, C("Bash", RM, "toolu_b"), C("Read", {"path": "notes.txt"}, "toolu_r"))


@pytest.mark.parametrize("added", [False, True], ids=["no new gate (control)", "a gate on the other call"])
def test_a_gate_added_on_a_call_that_was_not_asked_about_refuses_the_replay(rigs, added):   # U3a
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = _two_call_turn(rig, cl)                                              # Bash is held; Read passed on its own
    asks = p.asks._read()
    assert len(asks) == 1
    aid = asks[0]["id"]
    yes(p, aid)
    if added:
        (rig.space / "read-held.yaml").write_text(READ_GATE, encoding="utf-8")
        rig.repin()
        refused(cl, history(note), "X-REL")
        assert len(rig.stub.log) == 1 and status(p, aid) == "yes"               # nothing left, nothing spent
        assert not p.stash._turns                                               # and the kept turn is gone
        assert [a["tool"] for a in p.asks._read() if a["status"] == "open"] == ["read"]   # Read asks in its own right
    else:
        got = ask(cl, True, history(note))
        assert types(got) == ["tool_use", "tool_use"] and [b.id for b in got.content] == ["toolu_b", "toolu_r"]
        assert status(p, aid) == "spent"


def test_a_gate_added_on_the_answered_call_still_releases_it_once(rigs):        # U3a: the yes is for the act
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    (rig.space / "bash-held-too.yaml").write_text(BASH_GATE_2, encoding="utf-8")
    rig.repin()
    assert types(ask(cl, True, history(note))) == ["tool_use"] and status(p, aid) == "spent"
    upstream_text(rig, cl, history(note))                                       # and once only
    assert len(rig.stub.log) == 2


def _add_gate(space):
    (space / "bash-held-too.yaml").write_text(BASH_GATE_2, encoding="utf-8")
    return lambda: (space / "bash-held-too.yaml").unlink()


def _edit_block(space):
    old = (space / "bash.yaml").read_text(encoding="utf-8")
    (space / "bash.yaml").write_text(old.replace("runs_programs: true\n", ""), encoding="utf-8")
    return lambda: (space / "bash.yaml").write_text(old, encoding="utf-8")


def _remove_gate(space):
    old = (space / "shell-held.yaml").read_text(encoding="utf-8")
    (space / "shell-held.yaml").unlink()
    return lambda: (space / "shell-held.yaml").write_text(old, encoding="utf-8")


def _default_pass(space):
    old = (space / "space.yaml").read_text(encoding="utf-8")
    (space / "space.yaml").write_text(old.replace("default: hold", "default: pass"), encoding="utf-8")
    return lambda: (space / "space.yaml").write_text(old, encoding="utf-8")


@pytest.mark.parametrize("change", [_add_gate, _edit_block, _remove_gate, _default_pass],
                         ids=["a gate added", "a block edited", "a gate removed", "the default changed"])
def test_a_changed_space_is_refused_until_the_person_sets_it_again(rigs, change):   # U3b (not set again)
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    undo = change(rig.space)
    refused(cl, history(note), "X-DIGEST")                                      # not replayed, not forwarded
    refused(cl, [{"role": "user", "content": "go"}], "X-DIGEST")
    assert len(rig.stub.log) == 1 and status(p, aid) == "yes" and p.stash._turns   # nothing spent, nothing lost
    undo()
    assert types(ask(cl, True, history(note))) == ["tool_use"] and status(p, aid) == "spent"   # control: put back


def _tool_dropped(space):
    (space / "coder.yaml").write_text(CODER.replace("tools: [bash, read]", "tools: [read]"), encoding="utf-8")


def _tool_renamed(space):
    old = (space / "bash.yaml").read_text(encoding="utf-8")
    (space / "bash.yaml").write_text(old.replace("name: Bash", "name: Shell"), encoding="utf-8")


@pytest.mark.parametrize("change", [_tool_dropped, _tool_renamed], ids=["the agent drops the tool", "the tool renamed"])
def test_a_call_the_changed_space_no_longer_allows_is_not_released_when_set_again(rigs, change):   # U3b (set again)
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note = hold(rig, cl, C("Bash", RM))
    aid = p.asks._read()[0]["id"]
    yes(p, aid)
    change(rig.space)
    rig.repin()
    with pytest.raises(anthropic.APIStatusError) as e:
        ask(cl, True, history(note))
    assert e.value.status_code in (400, 403)                                    # refused, whichever rule says so
    assert len(rig.stub.log) == 1 and status(p, aid) == "yes" and not p.stash._turns
    assert not records(p, "call")[-1]["body"].get("decision") == "replayed"


# ================= U4e: a turn of 20 held calls =================
N = 20


def _hold_n(rig, cl):
    calls = [C("Bash", {"command": f"rm -rf logs{i}"}, f"toolu_{i:02d}") for i in range(N)]
    note = hold(rig, cl, *calls)
    ids = [a["id"] for a in rig.proxy.asks._read()]
    assert len(ids) == N and all(a["status"] == "open" for a in rig.proxy.asks._read())
    return note, ids


@pytest.mark.parametrize("open_at", [0, 9, 19])
def test_nineteen_yes_and_one_open_replays_nothing_and_spends_nothing(rigs, open_at):   # U4e
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note, ids = _hold_n(rig, cl)
    for i, aid in enumerate(ids):
        if i != open_at:
            yes(p, aid)
    upstream_text(rig, cl, history(note))                                       # the request goes on to the model
    assert len(rig.stub.log) == 2
    assert [status(p, a) for a in ids].count("yes") == N - 1 and status(p, ids[open_at]) == "open"
    assert records(p, "call") and not [r for r in records(p, "call") if r["body"].get("decision") == "replayed"]
    assert len(p.stash._turns) == 1                                             # the turn is still kept
    yes(p, ids[open_at])                                                        # the last answer: now it is whole
    got = ask(cl, True, history(note))
    assert [b.id for b in got.content] == [f"toolu_{i:02d}" for i in range(N)]
    assert [b.input for b in got.content] == [{"command": f"rm -rf logs{i}"} for i in range(N)]
    assert len(rig.stub.log) == 2                                               # no upstream request for it
    assert [status(p, a) for a in ids] == ["spent"] * N                         # all spent
    assert len([r for r in records(p, "call") if r["body"].get("decision") == "replayed"]) == N
    upstream_text(rig, cl, history(note))                                       # once
    assert len(rig.stub.log) == 3


@pytest.mark.parametrize("word", ["no", "revoke"])
@pytest.mark.parametrize("at", [0, 10, 19])
def test_a_no_on_any_one_call_replays_none(rigs, word, at):                     # U4e
    rig = rigs()
    cl, p = rig.client(), rig.proxy
    note, ids = _hold_n(rig, cl)
    for aid in ids:
        if word == "no" and aid == ids[at]:
            assert p.asks.answer(aid, "no", now())
        else:
            yes(p, aid)
    if word == "revoke":
        assert p.asks.answer(ids[at], "revoke", now())
    upstream_text(rig, cl, history(note))
    assert len(rig.stub.log) == 2 and not p.stash._turns
    assert [status(p, a) for a in ids].count("yes") == N - 1                    # the others are not spent
    assert status(p, ids[at]) == ("no" if word == "no" else "revoked")
    assert not [r for r in records(p, "call") if r["body"].get("decision") == "replayed"]
    upstream_text(rig, cl, history(note))                                       # and it does not come back
    assert len(rig.stub.log) == 3


# ================= the whitespace scan bound =================
SPACES = {"before =": lambda n: "password" + " " * n + "= hunter22x",
          "after =": lambda n: "password =" + " " * n + "hunter22x",
          "before is": lambda n: "password" + " " * n + "is hunter22x",
          "after is": lambda n: "password is" + " " * n + "hunter22x"}


def _across(key, cut):
    key = " " + key                                                             # a word boundary before "password"
    at = cut - len(key) // 2
    return "a " * (at // 2) + ("a" if at % 2 else "") + key + " a" * ((4 * W - at - len(key)) // 2)


@pytest.mark.parametrize("edge", list(EDGES))
@pytest.mark.parametrize("where", list(SPACES))
@pytest.mark.parametrize("n,found", [(255, True), (256, True), (257, False), (258, False)])
def test_the_whitespace_bound_is_pinned_from_both_sides(where, n, found, edge):   # the stated limit: 256 spaces
    key = SPACES[where](n)
    text = _across(key, EDGES[edge])
    assert proxy.SECRET.search(text)                                            # control: the whole pattern finds it
    assert proxy._secret(text) is found


def test_a_short_input_is_checked_by_the_whole_pattern_with_no_bound():         # the bound is for long inputs only
    assert proxy._secret("password" + " " * 1000 + "= hunter22x")
    assert not proxy._secret("pass word = hunter22x") and O < W
