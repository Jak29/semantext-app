"""The proxy end to end: the Anthropic SDK (R1) -> the proxy -> a loopback stub upstream that logs what reaches it.

The upstream invariant (D6): in a refuse arm the stub receives nothing; in a pass arm it receives the client's request
with the card added at the end of `system`, and no credential (a loopback model block).
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

anthropic = pytest.importorskip("anthropic")

from semantext import proxy  # noqa: E402
from tests.test_blocks import GOOD  # noqa: E402

CARD = "- r1: ask before deleting anything"
READ = "id: read\nkind: tool\nname: Read\nruns_as: client\ntests: []\n"
CODER = GOOD["coder.yaml"].replace("tools: [bash]", "tools: [bash, read]")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Stub:
    """A loopback upstream that answers each request with the next scripted reply and logs what it received."""

    def __init__(self):
        self.replies, self.log = [], []
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                stub.log.append({"path": self.path, "headers": dict(self.headers),
                                 "body": json.loads(self.rfile.read(n))})
                kind, payload = stub.replies.pop(0)
                status, more = 200, {}
                if kind == "status":                       # ("status", (code, headers, json payload))
                    status, more, payload = payload
                    kind = "json"
                if kind == "sse":
                    data = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in payload).encode()
                    ctype = "text/event-stream"
                else:
                    data, ctype = json.dumps(payload).encode(), "application/json"
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                for k, v in more.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def sse_turn(*blocks_, stop="tool_use"):
    ev = [("message_start", {"type": "message_start", "message": {
        "id": "msg_up", "type": "message", "role": "assistant", "content": [], "model": "claude-opus-5-5",
        "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 5, "output_tokens": 0}}})]
    for i, b in enumerate(blocks_):
        if b["type"] == "text":
            ev += [("content_block_start", {"type": "content_block_start", "index": i,
                                            "content_block": {"type": "text", "text": ""}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": i,
                                            "delta": {"type": "text_delta", "text": b["text"]}})]
        else:
            ev += [("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                "type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}}),
                   ("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                       "type": "input_json_delta", "partial_json": json.dumps(b["input"])}})]
        ev.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    ev += [("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                              "usage": {"output_tokens": 7}}), ("message_stop", {"type": "message_stop"})]
    return ("sse", ev)


def json_turn(*blocks_, stop="tool_use"):
    return ("json", {"id": "msg_up", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                     "content": list(blocks_), "stop_reason": stop, "stop_sequence": None,
                     "usage": {"input_tokens": 5, "output_tokens": 7}})


def T(t):
    return {"type": "text", "text": t}


def C(name, inp, tid="toolu_1"):
    return {"type": "tool_use", "id": tid, "name": name, "input": inp}


@pytest.fixture
def env(tmp_path):
    stub = Stub()
    space = tmp_path / "space"
    space.mkdir()
    model = (f"id: claude\nkind: model\nprovider: anthropic\nmodel: claude-opus-5-5\n"
             f"endpoint: http://127.0.0.1:{stub.port}\ncredential_host: 127.0.0.1\ntests: []\n")
    for name, text in {**GOOD, "claude.yaml": model, "read.yaml": READ, "coder.yaml": CODER}.items():
        (space / name).write_text(text, encoding="utf-8")
    port = free_port()
    ready = threading.Event()
    threading.Thread(target=proxy.serve, args=(space, tmp_path / "home", CARD, port), kwargs={"ready": ready},
                     daemon=True).start()
    assert ready.wait(5)
    client = anthropic.Anthropic(base_url=f"http://127.0.0.1:{port}", api_key="sk-test-canary-0000000000000000",
                                 default_headers={"x-semantext-agent": "coder"}, max_retries=0)
    yield stub, client, port, tmp_path / "home", ready.server
    ready.server.shutdown()
    stub.server.shutdown()


def ask(client, stream, messages=None):
    kw = dict(model="claude-opus-5-5", max_tokens=100, system="attribution block",
              messages=messages or [{"role": "user", "content": "go"}],
              tools=[{"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
                     {"name": "Read", "description": "read", "input_schema": {"type": "object"}}])
    if stream:
        with client.messages.stream(**kw) as s:
            return s.get_final_message()
    return client.messages.create(**kw)


@pytest.mark.parametrize("stream", [True, False])
def test_an_ungated_call_passes_and_the_upstream_sees_the_card_at_the_end(env, stream):   # the control
    stub, client, *_ = env
    stub.replies.append((sse_turn if stream else json_turn)(T("reading"), C("Read", {"path": "a.txt"})))
    msg = ask(client, stream)
    assert [b.type for b in msg.content] == ["text", "tool_use"] and msg.content[1].input == {"path": "a.txt"}
    sent = stub.log[0]
    assert sent["body"]["system"][0]["text"] == "attribution block"                      # still first
    assert sent["body"]["system"][-1]["text"] == CARD                                      # the card at the end
    assert not {k.lower() for k in sent["headers"]} & {"x-api-key", "authorization", "x-semantext-agent"}


@pytest.mark.parametrize("stream", [True, False])
def test_a_gated_call_is_held_and_never_reaches_the_client(env, stream):                  # must-refuse (held)
    stub, client, *_ = env
    stub.replies.append((sse_turn if stream else json_turn)(
        T("I will delete the logs."), C("Bash", {"command": "rm -rf logs"}), T("Done, the logs are gone.")))
    msg = ask(client, stream)
    assert [b.type for b in msg.content] == ["text", "text"] and msg.stop_reason == "end_turn"
    assert "Waiting for the person's word" in msg.content[1].text
    raw = json.dumps(msg.model_dump())
    assert "rm -rf" not in raw and "logs are gone" not in raw


def test_an_unknown_field_never_reaches_the_upstream(env):                               # must-refuse (upstream side)
    stub, client, *_ = env
    with pytest.raises(anthropic.APIStatusError) as e:
        client.messages.create(model="claude-opus-5-5", max_tokens=10, messages=[{"role": "user", "content": "x"}],
                               extra_body={"web_search_options": {}})
    assert e.value.status_code == 400 and "web_search_options" in str(e.value)
    assert stub.log == []


def raw_post(port, headers, body=b"{}"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest("POST", "/v1/messages", skip_host=True, skip_accept_encoding=True)
    for k, v in headers.items():
        c.putheader(k, v)
    c.putheader("Content-Length", str(len(body)))
    c.endheaders(body)
    r = c.getresponse()
    return r.status, r.read()


GOOD_BODY = json.dumps({"model": "claude-opus-5-5", "max_tokens": 5,
                        "messages": [{"role": "user", "content": "x"}]}).encode()


@pytest.mark.parametrize("headers,word", [
    ({"Host": "localhost:{p}"}, b"Host"),
    ({"Host": "evil.example"}, b"Host"),
    ({"Origin": "https://evil.example"}, b"Origin"),
    ({"Content-Type": "text/plain"}, b"JSON"),
    ({"Content-Encoding": "gzip"}, b"compressed"),
])
def test_the_listener_refuses_the_web(env, headers, word):                                # must-refuse (D8)
    stub, client, port, *_ = env
    base = {"Host": "127.0.0.1:{p}", "Content-Type": "application/json", "x-semantext-agent": "coder"}
    status, body = raw_post(port, {k: v.format(p=port) for k, v in {**base, **headers}.items()}, GOOD_BODY)
    assert status == 403 and b"X-ROUTE" in body and word in body and stub.log == []    # its own rule, not X-ID


def test_the_listener_control_passes(env):                                                # control for the above
    stub, client, port, *_ = env
    stub.replies.append(json_turn(T("hi"), stop="end_turn"))
    status, _ = raw_post(port, {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json",
                                "x-semantext-agent": "coder"}, GOOD_BODY)
    assert status == 200 and len(stub.log) == 1


@pytest.mark.parametrize("agent", [None, "nobody", "claude"])                            # absent, unknown, not an agent
def test_no_agent_named_is_refused(env, agent):                                          # must-refuse (X-ID)
    stub, client, port, *_ = env
    headers = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json"}
    if agent:
        headers["x-semantext-agent"] = agent
    status, body = raw_post(port, headers, GOOD_BODY)
    assert status == 403 and b"x-semantext-agent" in body and stub.log == []


def test_a_yes_replays_the_held_call_once_with_no_upstream_request(env):                 # T1, U1, U4
    stub, client, port, home, server = env
    stub.replies.append(sse_turn(T("deleting"), C("Bash", {"command": "rm -rf logs"})))
    held = ask(client, True)
    note = held.content[-1].text
    p = server.RequestHandlerClass.proxy
    aid = p.asks._read()[0]["id"]
    assert p.asks.answer(aid, "yes", __import__("time").monotonic())
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    replayed = ask(client, True, history)
    assert [b.type for b in replayed.content] == ["tool_use"] and replayed.content[0].input == {"command": "rm -rf logs"}
    assert len(stub.log) == 1                                                             # no upstream request
    assert p.asks.status(aid, __import__("time").monotonic()) == "spent"                 # the answer is spent
    assert p.stash.peek(next(iter(p.stash._turns), "")) is None and not p.stash._turns    # and the stash is empty
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    again = ask(client, True, history)                                                    # once only
    assert [b.type for b in again.content] == ["text"] and len(stub.log) == 2


def test_a_replay_spends_the_answer_even_when_the_gate_was_removed(env):                # U4: the turn is the unit
    stub, client, port, home, server = env
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    note = ask(client, True).content[-1].text
    p = server.RequestHandlerClass.proxy
    now = __import__("time").monotonic
    aid = p.asks._read()[0]["id"]
    p.asks.answer(aid, "yes", now())
    (p.space_dir / "shell-held.yaml").unlink()                                            # the person removed the gate
    from semantext import blocks
    p.expected = blocks.load(p.space_dir).digest              # and set the space again (P8: their own act, a restart)
    history = [{"role": "user", "content": "go"}, {"role": "assistant", "content": [{"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    replayed = ask(client, True, history)
    assert [b.type for b in replayed.content] == ["tool_use"]
    assert p.asks.status(aid, now()) == "spent"                                           # not left to be used again


def test_the_record_holds_no_input_text_and_no_key(env):                                  # D7, canary
    stub, client, port, home, _ = env
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf secret-dir-xyz"}),
                                 C("tool-named-secret-qrs", {"a": 1}, "toolu_2")))      # an undeclared name too
    ask(client, True)
    everything = "".join(p.read_text(encoding="utf-8", errors="replace") for p in home.iterdir() if p.is_file()
                         and p.name != "node.key")
    assert "secret-dir-xyz" not in everything and "sk-test-canary" not in everything
    assert "tool-named-secret-qrs" not in everything                                     # D7: undeclared, never named
