"""Koinos's second kit run on proxy v0 (3 November 2026): X1, R1 and R3.

X1: a held call's input and every header value go through the key-shape check, which was quadratic on a long run of
letters (80,000 in about 32 s through the proxy, the GIL held). R1: a header block over 32 KiB was accepted. R3: a NUL
in a forwarded header value reached the upstream. Each arm has a must-refuse and a control that passes.
"""
from __future__ import annotations

import time

import pytest

from tests.test_orithises_probes import GOOD_BODY, post
from tests.test_proxy import C, T, ask, env, json_turn  # noqa: F401 (env is a fixture)


def test_a_held_call_with_a_long_plain_input_is_decided_in_time(env):        # must-refuse the stall (X1)
    stub, client, *_ = env
    stub.replies.append(json_turn(T("running"), C("Bash", {"command": "echo " + "a" * 100_000})))
    start = time.perf_counter()
    msg = ask(client, False)
    assert time.perf_counter() - start < 2.0
    assert "Waiting for the person's word" in msg.content[-1].text       # held, as before


def test_a_header_block_over_32_kib_is_refused_before_anything_reads_it(env):   # must-refuse (R1)
    stub, client, port, *_ = env
    start = time.perf_counter()
    status, body = post(port, GOOD_BODY, headers={"anthropic-beta": "a" * 40_000})
    assert status == 403 and b"over 32768 bytes" in body
    assert time.perf_counter() - start < 2.0 and stub.log == []


@pytest.mark.parametrize("value", ["a\x00b", "a\x1bb", "a\x7fb"], ids=["NUL", "escape", "DEL"])
def test_a_control_character_in_a_header_value_is_refused(env, value):         # must-refuse (R3)
    stub, client, port, *_ = env
    status, body = post(port, GOOD_BODY, headers={"anthropic-beta": value})
    assert status == 403 and b"control character" in body
    assert stub.log == []                                                      # nothing reached the upstream


RATE = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}


def _rate_limited(port, retry_after):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("POST", "/v1/messages", skip_host=True, skip_accept_encoding=True)
    data = __import__("json").dumps(GOOD_BODY).encode()
    for k, v in {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", "x-semantext-agent": "coder",
                 "Content-Length": str(len(data))}.items():
        c.putheader(k, v)
    c.endheaders(data)
    r = c.getresponse()
    out = (r.status, r.getheader("retry-after"), r.read())
    c.close()
    return out


def test_a_429_passes_its_retry_after_to_the_client(env):                      # R8: Claude Code backs off on it
    stub, client, port, *_ = env
    stub.replies.append(("status", (429, {"retry-after": "17"}, RATE)))
    status, wait, body = _rate_limited(port, "17")
    assert status == 429 and wait == "17" and b"rate_limit_error" in body


def test_a_retry_after_that_is_not_seconds_is_not_passed(env):                # must-refuse: only a plain number
    stub, client, port, *_ = env
    stub.replies.append(("status", (429, {"retry-after": "17; evil=1"}, RATE)))
    status, wait, _ = _rate_limited(port, None)
    assert status == 429 and wait is None


def test_plain_headers_under_the_bound_still_pass(env):                       # control
    stub, client, port, *_ = env
    stub.replies.append(json_turn(T("ok"), stop="end_turn"))
    status, _ = post(port, GOOD_BODY, headers={"anthropic-beta": "x" * 20_000, "anthropic-version": "2023-06-01\tz"})
    assert status == 200
    assert stub.log[0]["headers"]["anthropic-beta"] == "x" * 20_000           # forwarded unchanged
