"""Orithises's recheck of the proxy server: residuals R1 to R4 and the test gaps N2, N19, N26, N27."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time

import pytest

from semantext import blocks, decide, gate_request, proxy, proxy_record
from semantext.assemble import Refused
from tests.test_blocks import GOOD
from tests.test_proxy import env, json_turn, T  # noqa: F401 (env is a fixture)
from tests.test_orithises_probes import GOOD_BODY, post


# ---- R1: a slow drip of header bytes does not keep a slot ----
def test_a_header_drip_is_closed_at_the_total_deadline(env, monkeypatch):            # must-refuse (R1)
    stub, client, port, home, server = env
    monkeypatch.setattr(proxy, "HEADER_DEADLINE_S", 1)
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"POST /v1/messages HTTP/1.1\r\n")
    t0, closed = time.monotonic(), False
    while time.monotonic() - t0 < 6:
        try:
            s.sendall(b"X-Drip: a\r\n")                                                    # never ends the headers
            time.sleep(0.3)
        except OSError:
            closed = True
            break
        try:
            s.settimeout(0.01)
            if s.recv(1) == b"":
                closed = True
                break
        except (socket.timeout, BlockingIOError):
            pass
        except OSError:
            closed = True
            break
    s.close()
    assert closed and time.monotonic() - t0 < 5


# ---- R2: vendor work recorded by count, never by the client's names ----
def test_recorded_vendor_work_writes_no_name(env):                                    # must-refuse (R2)
    stub, client, port, home, server = env
    p = server.RequestHandlerClass.proxy
    (p.space_dir / "space.yaml").write_text("default: hold\nvendor_side: record\n", encoding="utf-8")
    p.expected = blocks.load(p.space_dir).digest
    stub.replies.append(json_turn(T("hi"), stop="end_turn"))
    post(port, dict(GOOD_BODY, tools=[{"type": "web_search_20260209", "name": "web_search"}]))
    raw = (home / "proxy.jsonl").read_text(encoding="utf-8")
    assert "web_search" not in raw and '"vendor_recorded":1' in raw


# ---- R3: a source type on no list is refused ----
@pytest.mark.parametrize("block", [
    {"type": "document", "source": {"type": "s3_bucket", "bucket": "b"}},
    {"type": "image", "source": {"type": "text", "data": "x"}},
    {"type": "image", "source": "https://x"},
])
def test_a_source_type_on_no_list_is_refused(tmp_path, block):                        # must-refuse (R3)
    for name, text in {**GOOD, "space.yaml": "default: hold\n"}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    body = {"model": "claude-opus-5-5", "max_tokens": 5, "messages": [{"role": "user", "content": [block]}]}
    with pytest.raises(Refused) as e:
        gate_request.check(body, blocks.load(tmp_path), "coder")
    assert e.value.rule == "X-REQ"


# ---- R4 and N27: a broken chain is noticed at once ----
def _chain(tmp_path, n=3):
    r = proxy_record.Record(tmp_path / "proxy.jsonl")
    for i in range(n):
        r.append("turn", {"n": i})
    return r


@pytest.mark.parametrize("damage", ["edit", "drop", "swap"])
def test_a_damaged_chain_refuses_the_next_append(tmp_path, damage):                   # must-refuse (R4, N27)
    _chain(tmp_path)
    p = tmp_path / "proxy.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    if damage == "edit":
        lines[1] = lines[1].replace('"n":1', '"n":9')
    elif damage == "drop":
        del lines[1]
    else:
        lines[0], lines[1] = lines[1], lines[0]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    r = proxy_record.Record(p)
    assert not r.verify()
    with pytest.raises(proxy_record.RecordFailed):
        r.append("turn", {})


def test_a_chain_damaged_while_running_refuses_the_next_append(tmp_path):            # must-refuse (R4: mid-run)
    r = _chain(tmp_path)                                                                 # appending, all well
    p = tmp_path / "proxy.jsonl"
    p.write_text(p.read_text(encoding="utf-8").replace('"n":1', '"n":7'), encoding="utf-8")
    with pytest.raises(proxy_record.RecordFailed):                                        # the same object, next append
        r.append("turn", {"n": 3})


def test_a_whole_chain_verifies_and_appends(tmp_path):                                # control
    r = _chain(tmp_path)
    assert r.verify()
    r.append("turn", {"n": 3})
    assert proxy_record.Record(tmp_path / "proxy.jsonl").verify()


# ---- N26: two processes append to one chain ----
APPEND = """
import sys
sys.path.insert(0, {tree!r})
from semantext import proxy_record
r = proxy_record.Record({path!r})
for i in range(25):
    r.append("turn", {{"who": {who!r}, "n": i}})
"""


def test_two_processes_append_to_one_whole_chain(tmp_path):                           # N26
    import semantext
    from pathlib import Path
    tree = str(Path(semantext.__file__).parent.parent)
    path = str(tmp_path / "proxy.jsonl")
    procs = [subprocess.Popen([sys.executable, "-c", APPEND.format(tree=tree, path=path, who=w)]) for w in "ab"]
    for p in procs:
        assert p.wait(60) == 0
    r = proxy_record.Record(path)
    assert r.verify() and len(r.lines()) == 50


# ---- N2: a spend whose chain line is missing spends nothing ----
def test_a_yes_without_its_chain_line_cannot_be_spent(tmp_path):                      # must-refuse (N2)
    rec = proxy_record.Record(tmp_path / "proxy.jsonl")
    asks = decide.Asks(tmp_path / "asks.json", "run", key=b"k", record=rec)
    aid = asks.open("coder", "s", "bash", "call", "d" * 64, "c", 1.0)
    data = json.loads((tmp_path / "asks.json").read_text(encoding="utf-8"))
    data[0]["status"] = "yes"                                                             # the file says yes; no line
    (tmp_path / "asks.json").write_text(json.dumps(data), encoding="utf-8")
    assert not asks.spend([aid], 2.0)
    assert asks.status(aid, 2.0) == "unproved"


# ---- N19: a count reply that is not a count ----
def test_a_count_reply_that_is_not_a_count_is_refused(env):                           # must-refuse (N19)
    stub, client, port, home, server = env
    stub.replies.append(("json", {"input_tokens": "lots"}))
    status, body = post(port, GOOD_BODY, path="/v1/messages/count_tokens")
    assert status == 400 and b"not a count" in body
