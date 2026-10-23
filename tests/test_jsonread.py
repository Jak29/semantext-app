"""A text nested past json's parser gets the same answer on every machine, at every reader.

Whether 30,000 levels overflow the parser is the interpreter's stack: they do on Windows (a RecursionError) and parse
under 3.14 on Linux and macOS. Each test runs three ways on any machine: with this machine's own parser, with one that
overflows, and with one that copes; the answer must be the same in all three."""
import http.client
import json
import threading
import time

import pytest

from semantext import envhook, jsonread
from semantext.server import DEEP_BODY, make_server
from semantext.sources import cards, gates, load_config, rules

N = 30000
DEEP = "[" * N + "]" * N            # valid JSON, 60,000 bytes: under every size limit it meets here
MARK = '"__deep__"'


def nested(n: int):
    value = []
    for _ in range(n - 1):
        value = [value]
    return value


def _swap(value):
    """The parse with the mark in place of DEEP, with the deep list put back where the mark is."""
    if value == MARK[1:-1]:
        return nested(N)
    if isinstance(value, dict):
        return {k: _swap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_swap(v) for v in value]
    return value


@pytest.fixture(params=["this-machine", "overflows", "copes"])
def parser(request, monkeypatch):
    real = json.loads

    def loads(text, *a, **k):
        s = text.decode("utf-8") if isinstance(text, (bytes, bytearray)) else text
        if DEEP not in s or request.param == "this-machine":
            return real(text, *a, **k)
        if request.param == "overflows":
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")
        return _swap(real(s.replace(DEEP, MARK), *a, **k))
    monkeypatch.setattr(json, "loads", loads)
    return request.param


# ---- the loader itself
def test_the_loader_refuses_a_deep_text_however_the_parser_would_fare(parser):
    for text in (DEEP, DEEP.encode("utf-8"), '{"a": ' + DEEP + "}"):
        with pytest.raises(jsonread.NotJSON) as got:
            jsonread.loads(text)
        assert got.value.deep and "nested more than" in str(got.value) and isinstance(got.value, ValueError)


def test_the_loader_reads_what_is_not_too_deep_and_keeps_jsons_words_for_what_is_not_json():
    """Must-pass arm: MAX_DEPTH levels are read; brackets inside a string are not nesting."""
    at_limit = "[" * jsonread.MAX_DEPTH + "]" * jsonread.MAX_DEPTH
    assert jsonread.loads(at_limit) == nested(jsonread.MAX_DEPTH)
    assert jsonread.loads(json.dumps({"x": "[" * N})) == {"x": "[" * N}
    with pytest.raises(jsonread.NotJSON) as got:
        jsonread.loads("{nope")
    assert not got.value.deep and isinstance(got.value, json.JSONDecodeError)
    with pytest.raises(json.JSONDecodeError) as real:
        json.loads("{nope")
    assert str(got.value) == str(real.value)
    with pytest.raises(jsonread.NotJSON) as over:
        jsonread.loads("[" * (jsonread.MAX_DEPTH + 1) + "]" * (jsonread.MAX_DEPTH + 1))
    assert over.value.deep


# ---- an unclosed string costs a pass, not a pass per quote
LINE = 64 * 1024   # the record reader's longest line


def hostile(tail: str = "") -> str:
    """300 openers, one quote that never closes, then \\" to fill a line: each \\" holds a quote the scan could restart at."""
    head = "[" * 300 + '"'
    return head + '\\"' * ((LINE - len(head) - len(tail)) // 2) + tail


@pytest.mark.parametrize("tail", ["", "\\"], ids=["unclosed", "unclosed-ending-in-a-lone-backslash"])
def test_an_unclosed_string_is_scanned_in_one_pass(tail):
    """Must refuse: on 0909675 this line took about 16 s in depth(), a hook frozen by one line an agent can write. The
    lone backslash at the very end is the case a closing of `"` or end of text alone would still leave quadratic."""
    text = hostile(tail)
    t = time.perf_counter()
    assert jsonread.depth(text) == 300
    assert time.perf_counter() - t < 1
    t = time.perf_counter()
    with pytest.raises(jsonread.NotJSON) as got:
        jsonread.loads(text)
    assert got.value.deep and time.perf_counter() - t < 1        # still refused, and as too deep


def test_a_valid_line_of_escaped_quotes_still_parses_and_counts_right():
    """Must pass: a closed string of the same \\" is read whole, and brackets after it still count."""
    body = '\\"' * ((LINE - 64) // 2)
    text = '{"a": "' + body + '", "b": [[[1]]]}'
    t = time.perf_counter()
    assert jsonread.loads(text) == {"a": '"' * ((LINE - 64) // 2), "b": [[[1]]]}
    assert time.perf_counter() - t < 1
    deep_after = '["' + body + '", ' + "[" * 300 + "]" * 300 + "]"
    assert jsonread.depth(deep_after) == 301


def test_the_cards_reader_scans_the_same_way():
    t = time.perf_counter()
    assert cards._nesting(hostile()) == 300 and time.perf_counter() - t < 1


# ---- each reader
def test_a_deep_seats_file_is_bad_json_to_the_gates_reader(tmp_path, parser):
    f = tmp_path / "seats.json"
    f.write_text(DEEP, encoding="utf-8")
    problems = []
    assert gates.read_roots(str(f), problems) == ([], [])
    assert [p["kind"] for p in problems] == ["bad-json"]


def test_a_deep_sources_file_is_refused_as_not_json(tmp_path, parser):
    f = tmp_path / "sources.json"
    f.write_text('{"name": ' + DEEP + "}", encoding="utf-8")
    with pytest.raises(jsonread.NotJSON):
        load_config(f)


def test_a_deep_hook_payload_reads_as_no_payload(parser):
    assert envhook.parse_payload(DEEP) == {}
    assert envhook.parse_payload('{"prompt": ' + DEEP + "}") == {}


def test_a_deep_guards_file_is_bad_guards(tmp_path, parser):
    f = tmp_path / "guards.json"
    f.write_text('{"checkers": ' + DEEP + "}", encoding="utf-8")
    problems = []
    assert rules.checkers(str(f), problems) == {}
    assert [p["kind"] for p in problems] == ["bad-guards"]


def test_a_deep_request_body_is_answered_400_with_a_fixed_message(store, parser):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    body = ('{"name": ' + DEEP + "}").encode("utf-8")
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        c.putrequest("POST", "/api/active", skip_host=True)
        for k, v in (("Host", f"127.0.0.1:{port}"), ("X-Semantext", "1"), ("Origin", f"http://127.0.0.1:{port}"),
                     ("Content-Type", "application/json"), ("Content-Length", str(len(body)))):
            c.putheader(k, v)
        c.endheaders()
        c.send(body)
        r = c.getresponse()
        assert (r.status, json.loads(r.read())) == (400, {"error": DEEP_BODY})
    finally:
        srv.shutdown()
        srv.server_close()
    assert store.state()["active"] == "default"
