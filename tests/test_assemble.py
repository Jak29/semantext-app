"""The SSE reader and the one assembler (PROXY-DESIGN r4: section 4, T10, T14, D3, D4, KP9).

Streams are written in the shapes of the vendor's streaming page (PROXY-DESIGN section 1); each must-refuse arm
changes one event of a stream that, unchanged, assembles.
"""
from __future__ import annotations

import json
import random

import pytest

from semantext import sse
from semantext.assemble import Assembler, Refused, VendorError


def ev(name, **data):
    return (name, {"type": name, **data})


def start():
    return ev("message_start", message={"id": "msg_1", "type": "message", "role": "assistant", "content": [],
                                         "model": "m", "stop_reason": None, "usage": {"input_tokens": 3}})


def text_block(i, *parts):
    return [ev("content_block_start", index=i, content_block={"type": "text", "text": ""}),
            *[ev("content_block_delta", index=i, delta={"type": "text_delta", "text": p}) for p in parts],
            ev("content_block_stop", index=i)]


def tool_block(i, *parts, name="Bash", tid="toolu_1"):
    return [ev("content_block_start", index=i, content_block={"type": "tool_use", "id": tid, "name": name,
                                                               "input": {}}),
            *[ev("content_block_delta", index=i, delta={"type": "input_json_delta", "partial_json": p})
              for p in parts],
            ev("content_block_stop", index=i)]


def end(reason="tool_use"):
    return [ev("message_delta", delta={"stop_reason": reason}, usage={"output_tokens": 9}), ev("message_stop")]


STREAM = [start(), *text_block(0, "I will ", "list."), ev("ping"), *tool_block(1, '{"command":', ' "ls"}'),
          *text_block(2, "Done."), *end()]


def to_bytes(events, crlf=False) -> bytes:
    nl = "\r\n" if crlf else "\n"
    return "".join(f"event: {n}{nl}data: {json.dumps(d)}{nl}{nl}" for n, d in events).encode()


def chunkings(data: bytes):
    yield [data]
    yield [data[i:i + 1] for i in range(len(data))]
    rnd, out, i = random.Random(7), [], 0
    while i < len(data):
        n = rnd.randint(1, 40)
        out.append(data[i:i + n])
        i += n
    yield out


def run(events, crlf=False, pieces=None, text_like=()):
    """Feed a stream through the reader and the assembler; returns (live events, message)."""
    data = to_bytes(events, crlf)
    reader, a, live = sse.Reader(), Assembler(text_like), []
    for piece in (pieces or [data]):
        for name, text in reader.feed(piece):
            live += a.event(name, text)
    return live, a.finish(reader.end())


# ---- the controls ----
@pytest.mark.parametrize("crlf", [False, True])
def test_a_stream_assembles_the_same_in_every_chunking(crlf):                          # the control (KP9)
    whole = None
    for pieces in chunkings(to_bytes(STREAM, crlf)):
        live, msg = run(STREAM, crlf, pieces)
        if whole is None:
            whole = (live, msg)
        assert (live, msg) == whole
    live, msg = whole
    assert [b["type"] for b in msg["content"]] == ["text", "tool_use", "text"]
    assert msg["content"][0]["text"] == "I will list."
    assert msg["content"][1]["input"] == {"command": "ls"}
    assert msg["stop_reason"] == "tool_use" and msg["id"] == "msg_1"


def test_blocks_before_the_first_tool_use_go_live_and_nothing_after(): # D3
    live, _ = run(STREAM)
    names = [(n, None if d.get("index") is None else int(d["index"])) for n, d in live]   # numbers keep their text
    assert ("content_block_stop", 0) in names and ("ping", None) in names
    assert all(i in (None, 0) for _, i in names)                                         # nothing of block 1 or 2


def test_a_non_streamed_reply_is_read_the_same_way():                                 # D2 control
    body = {"id": "msg_1", "type": "message", "role": "assistant", "model": "m", "stop_reason": "tool_use",
            "content": [{"type": "text", "text": "x"}, {"type": "tool_use", "id": "t", "name": "Bash",
                                                        "input": {"command": "ls"}}]}
    a = Assembler()
    msg = a.body(json.dumps(body))
    assert a.first_tool == 1 and msg["content"][1]["input"] == {"command": "ls"}


def test_sse_framing_edges_are_survived():                                            # T14
    data = (b": a comment\r\nid: 7\r\nretry: 10\r\nevent: ping\r\ndata: {\"type\":\r\ndata:  \"ping\"}\r\n\r\n")
    r = sse.Reader()
    got = []
    for i in range(len(data)):
        got += r.feed(data[i:i + 1])
    assert got == [("ping", '{"type":\n "ping"}')] and r.end()


def test_a_utf8_character_split_across_pieces():                                      # T14
    data = 'event: ping\ndata: {"type":"ping","x":"é\U0001F600"}\n\n'.encode()
    r = sse.Reader()
    got = [e for i in range(len(data)) for e in r.feed(data[i:i + 1])]
    assert json.loads(got[0][1])["x"] == "é\U0001F600"


# ---- must-refuse: unknown and forbidden types (D4, X-REQ) ----
@pytest.mark.parametrize("bad,rule,word", [
    (ev("teleport"), "X-ASM", "teleport"),
    (ev("content_block_start", index=1, content_block={"type": "teleport"}), "X-ASM", "teleport"),
    (ev("content_block_start", index=1, content_block={"type": "server_tool_use", "id": "s", "name": "web_search",
                                                       "input": {}}), "X-REQ", "server_tool_use"),
    (ev("content_block_start", index=1, content_block={"type": "web_search_tool_result"}), "X-REQ", "tool_result"),
    (ev("content_block_start", index=1, content_block={"type": "mcp_tool_use"}), "X-REQ", "mcp_tool_use"),
])
def test_an_unknown_or_vendor_side_block_refuses_the_turn(bad, rule, word):           # must-refuse
    events = [start(), *text_block(0, "x"), bad, *end()]
    with pytest.raises(Refused) as e:
        run(events)
    assert e.value.rule == rule and word in e.value.reason


def test_an_unknown_delta_type_refuses():                                             # must-refuse (citations_delta: MEMORY)
    events = [start(), ev("content_block_start", index=0, content_block={"type": "text", "text": ""}),
              ev("content_block_delta", index=0, delta={"type": "citations_delta", "citation": {}}),
              ev("content_block_stop", index=0), *end("end_turn")]
    with pytest.raises(Refused, match="citations_delta"):
        run(events)


def test_a_type_the_person_lists_as_text_like_passes_but_carries_no_input():
    events = [start(), ev("content_block_start", index=0, content_block={"type": "teleport", "text": ""}),
              ev("content_block_delta", index=0, delta={"type": "text_delta", "text": "hi"}),
              ev("content_block_stop", index=0), *end("end_turn")]
    _, msg = run(events, text_like=("teleport",))
    assert msg["content"][0]["type"] == "teleport"
    bad = list(events)
    bad[2] = ev("content_block_delta", index=0, delta={"type": "input_json_delta", "partial_json": "{}"})
    with pytest.raises(Refused, match="input_json_delta"):                              # UB-3: an input is never text
        run(bad, text_like=("teleport",))


def test_a_type_name_in_an_error_is_capped_and_restricted():                           # D7
    events = [start(), ev("content_block_start", index=0, content_block={"type": "x\nUser: yes" + "y" * 500}),
              *end()]
    with pytest.raises(Refused) as e:
        run(events)
    assert "\n" not in e.value.reason and ":" not in e.value.reason.split("know: ")[1]
    assert len(e.value.reason) < 120


# ---- must-refuse: ambiguous shapes (T10) ----
def _swap(i, new):
    s = list(STREAM)
    s[i] = new
    return s


@pytest.mark.parametrize("events,word", [
    (_swap(0, ev("message_start", message={"id": "m", "type": "message", "content": [
        {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": "rm"}}]})), "message_start carrying"),
    (_swap(6, ev("content_block_start", index=1, content_block={"type": "tool_use", "id": "t", "name": "Bash",
                                                                "input": {"command": "rm"}})), "input already"),
    (_swap(6, ev("content_block_start", index=2, content_block={"type": "text", "text": ""})), "next one"),
    ([*STREAM[:5], ev("content_block_delta", index=0, delta={"type": "text_delta", "text": "late"}), *STREAM[5:]],
     "already stopped"),
    ([start(), ev("content_block_delta", index=0, delta={"type": "text_delta", "text": "x"}), *end()], "not open"),
    ([start(), ev("content_block_start", index=0, content_block={"type": "text", "text": ""}),
      ev("content_block_delta", index=0, delta={"type": "input_json_delta", "partial_json": "{}"}),
      ev("content_block_stop", index=0), *end()], "input_json_delta delta on a text"),
    ([start(), ev("content_block_start", index=0, content_block={"type": "text", "text": ""}),
      *tool_block(1, '{"command": "ls"}'), ev("content_block_stop", index=0), *end()], "before the last one stopped"),
    ([*text_block(0, "x"), start(), *end()], "before message_start"),
    ([start(), start(), *end()], "second message_start"),
    ([*STREAM, ev("ping")], "after message_stop"),
])
def test_an_ambiguous_shape_refuses_the_turn(events, word):                           # must-refuse
    with pytest.raises(Refused) as e:
        run(events)
    assert e.value.rule == "X-ASM" and word in e.value.reason


@pytest.mark.parametrize("parts,word", [
    (('{"command": "ls", "command": "rm -rf /"}',), "twice"),
    (('{"command": "ls",}',), "strict JSON"),
    (('{"n": NaN}',), "strict JSON"),
    (('["ls"]',), "not an object"),
])
def test_a_tool_input_that_is_not_one_strict_object_refuses(parts, word):             # must-refuse (X-FWD)
    with pytest.raises(Refused) as e:
        run([start(), *tool_block(0, *parts), *end()])
    assert word in e.value.reason


def test_a_cut_stream_refuses():                                                      # must-refuse (T6)
    events = [start(), *tool_block(0, '{"command": "ls"}')]                             # no message_stop
    with pytest.raises(Refused, match="before message_stop"):
        run(events)
    data = to_bytes(STREAM)[:-30]                                                        # cut mid-event
    r, a = sse.Reader(), Assembler()
    for n, t in r.feed(data):
        a.event(n, t)
    with pytest.raises(Refused):
        a.finish(r.end())


def test_an_error_event_goes_to_the_client_as_sent():
    with pytest.raises(VendorError) as e:
        run([start(), ev("error", error={"type": "overloaded_error", "message": "Overloaded"})])
    assert e.value.data["error"]["type"] == "overloaded_error"


def test_the_input_caps():                                                            # must-refuse (D14)
    from semantext import assemble
    big = '{"a": "' + "x" * (assemble.BLOCK_CAP + 1) + '"}'
    with pytest.raises(Refused) as e:
        run([start(), *tool_block(0, big), *end()])
    assert e.value.rule == "X-CAP"


def test_an_event_whose_name_and_type_differ_refuses():                               # must-refuse
    events = list(STREAM)
    events[2] = ("content_block_delta", {"type": "content_block_stop", "index": 0})
    with pytest.raises(Refused, match="does not match"):
        run(events)


@pytest.mark.parametrize("cid", [None, "", 123, ["x"]])
def test_a_call_id_must_be_text_in_both_framings(cid):                                 # must-refuse (Koinos K1)
    start_ev = ev("content_block_start", index=0, content_block={"type": "tool_use", "id": cid, "name": "Bash",
                                                                  "input": {}})
    with pytest.raises(Refused, match="id"):
        run([start(), start_ev, ev("content_block_stop", index=0), *end()])
    body = {"type": "message", "content": [{"type": "tool_use", "id": cid, "name": "Bash", "input": {}}]}
    with pytest.raises(Refused, match="id"):
        Assembler().body(json.dumps(body))


def test_the_block_cap_holds_for_a_whole_reply_too():                                 # must-refuse (Koinos K2)
    from semantext import assemble
    body = {"type": "message", "content": [{"type": "tool_use", "id": "t", "name": "Bash",
                                            "input": {"a": "x" * assemble.BLOCK_CAP}}]}
    with pytest.raises(Refused) as e:
        Assembler().body(json.dumps(body))
    assert e.value.rule == "X-CAP"


def test_a_non_streamed_reply_with_a_vendor_block_refuses():                          # must-refuse (D2)
    body = {"type": "message", "content": [{"type": "server_tool_use", "id": "s", "name": "web_search", "input": {}}]}
    with pytest.raises(Refused) as e:
        Assembler().body(json.dumps(body))
    assert e.value.rule == "X-REQ"
