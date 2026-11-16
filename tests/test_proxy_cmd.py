"""The proxy from the command line (semantext/proxycmd.py, `semantext proxy serve|asks|answer`): the person starts it,
sees what it holds, and answers it from their own terminal; the running proxy then releases exactly that call, once.
Each arm has its must-refuse: an agent's shell, an ask of an earlier run, a broken record, a word that is not an answer.
"""
from __future__ import annotations

import json
import threading
import time

import pytest

anthropic = pytest.importorskip("anthropic")

from semantext import cli, proxycmd  # noqa: E402
from tests.test_proxy import CARD, CODER, READ, C, Stub, T, free_port, sse_turn  # noqa: E402
from tests.test_blocks import GOOD  # noqa: E402


_READY: list = []      # each served proxy's ready event (it carries the server), so a test can end one


@pytest.fixture
def served(tmp_path, monkeypatch):
    stub = Stub()
    space = tmp_path / "space"
    space.mkdir()
    model = (f"id: claude\nkind: model\nprovider: anthropic\nmodel: claude-opus-5-5\n"
             f"endpoint: http://127.0.0.1:{stub.port}\ncredential_host: 127.0.0.1\ntests: []\n")
    for name, text in {**GOOD, "claude.yaml": model, "read.yaml": READ, "coder.yaml": CODER}.items():
        (space / name).write_text(text, encoding="utf-8")
    home = tmp_path / "proxyhome"
    port = free_port()
    ready = threading.Event()
    threading.Thread(target=proxycmd.serve, args=(space, home, CARD, port), kwargs={"ready": ready},
                     daemon=True).start()
    assert ready.wait(5)
    _READY.append(ready)
    client = anthropic.Anthropic(base_url=f"http://127.0.0.1:{port}", api_key="sk-test-canary-0000000000000000",
                                 default_headers={"x-semantext-agent": "coder"}, max_retries=0)
    monkeypatch.setattr(cli, "human_terminal", lambda: None)                 # the person's own terminal
    yield stub, client, home, tmp_path
    ready.server.shutdown()
    stub.server.shutdown()


def ask(client, messages=None):
    kw = dict(model="claude-opus-5-5", max_tokens=100, system="s",
              messages=messages or [{"role": "user", "content": "go"}],
              tools=[{"name": "Bash", "description": "run", "input_schema": {"type": "object"}},
                     {"name": "Read", "description": "read", "input_schema": {"type": "object"}}])
    with client.messages.stream(**kw) as s:
        return s.get_final_message()


def cli_run(tmp_path, home, *args):
    return cli.main(["--home", str(tmp_path / "st"), "proxy", *args, "--proxy-home", str(home)])


def test_a_proxy_that_ends_leaves_nothing_to_list_or_answer(served, capsys):          # must-refuse
    """A real serve holds serve.lock for its life; when it ends the system lets the lock go, and what it held with it."""
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    aid = proxycmd.open_asks(home)[0]["id"]
    assert proxycmd.proxy_running(home)
    _READY[-1].server.shutdown()                       # serve returns, and its lock goes with it
    for _ in range(100):
        if not proxycmd.proxy_running(home):
            break
        time.sleep(0.05)
    assert not proxycmd.proxy_running(home)
    capsys.readouterr()
    assert cli_run(tmp, home, "asks") == 0 and "No proxy is running" in capsys.readouterr().out
    assert cli_run(tmp, home, "answer", aid, "yes") != 0
    assert "has stopped" in capsys.readouterr().err


def test_serve_names_its_run(served):
    stub, client, home, tmp = served
    run = json.loads((home / "run.json").read_text(encoding="utf-8"))
    assert run["run"] and run["port"] and run["pid"]


def test_held_call_listed_answered_yes_and_released_once(served, capsys):
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(T("deleting"), C("Bash", {"command": "rm -rf logs"})))
    held = ask(client)
    note = held.content[-1].text
    assert "Waiting for the person's word" in note
    capsys.readouterr()
    assert cli_run(tmp, home, "asks") == 0
    listed = capsys.readouterr().out
    aid = proxycmd.open_asks(home)[0]["id"]
    assert aid in listed and "coder -> bash" in listed and "rm -rf" not in listed      # no input text, ever
    assert cli_run(tmp, home, "answer", aid, "yes") == 0
    assert f"Ask {aid} is now yes" in capsys.readouterr().out
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    replayed = ask(client, history)
    assert [b.type for b in replayed.content] == ["tool_use"] and replayed.content[0].input == {"command": "rm -rf logs"}
    assert len(stub.log) == 1                                                       # the replay made no upstream call
    stub.replies.append(sse_turn(T("ok"), stop="end_turn"))
    assert [b.type for b in ask(client, history).content] == ["text"]               # once only
    capsys.readouterr()
    cli_run(tmp, home, "asks")
    assert "Nothing waits for your word." in capsys.readouterr().out


def test_a_revoke_whose_asks_write_fails_leaves_the_call_held(served, monkeypatch):    # must-refuse (K1)
    """The revoke is on the chain and the asks file still says yes. The page and the command list nothing for it, and the
    real proxy, which reads the chain's last word, releases nothing: not by the agent making the call again, not by the
    client replaying the held turn. Answering again then finishes the revoke."""
    from semantext import decide
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(T("deleting"), C("Bash", {"command": "rm -rf logs"})))
    note = ask(client).content[-1].text
    aid = proxycmd.open_asks(home)[0]["id"]
    assert proxycmd.answer(home, aid, "yes") == "yes"
    assert [x["id"] for x in proxycmd.held_asks(home)] == [aid]
    real, mine = decide.Asks._write, threading.current_thread()

    def failing(self, asks):                     # the answering command's write only; the proxy's own are not touched
        if threading.current_thread() is mine:
            raise decide.Refused("X-EXC", "the ask store cannot be written")
        return real(self, asks)
    monkeypatch.setattr(decide.Asks, "_write", failing)
    with pytest.raises(proxycmd.Refused) as e:
        proxycmd.answer(home, aid, "revoke")
    assert "on the proxy's record" in str(e.value) and "answer again" in str(e.value)
    monkeypatch.setattr(decide.Asks, "_write", real)
    rows = json.loads((home / "asks.json").read_text(encoding="utf-8"))
    assert next(a["status"] for a in rows if a["id"] == aid) == "yes"                  # the file still says yes
    from semantext.proxy_record import Record
    words = [r["body"]["word"] for r in Record(home / "proxy.jsonl").lines()
             if r.get("kind") == "answered" and r["body"]["ask"] == aid]
    assert words == ["yes", "revoke"]                                                  # and the chain's last word is revoke
    assert aid not in [x["id"] for x in proxycmd.held_asks(home)]                      # the command lists nothing for it
    assert aid not in [x["id"] for x in proxycmd.open_asks(home)]
    assert aid not in [x["id"] for x in proxycmd.page_asks(home)["asks"]]              # nor does the page
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    upstream = len(stub.log)
    stub.replies.append(sse_turn(T("held again"), C("Bash", {"command": "rm -rf logs"})))
    replayed = ask(client, history)                                                    # the client replays the held turn
    assert {b.type for b in replayed.content} == {"text"} and len(stub.log) == upstream + 1   # asked upstream: not replayed
    assert "Waiting for the person's word" in replayed.content[-1].text
    stub.replies.append(sse_turn(T("held again"), C("Bash", {"command": "rm -rf logs"})))
    reissued = ask(client)                                                             # the agent makes the call again
    assert {b.type for b in reissued.content} == {"text"}
    assert "Waiting for the person's word" in reissued.content[-1].text                # held again, not released
    assert proxycmd.answer(home, aid, "revoke") == "revoked"                           # answering again finishes it
    rows = json.loads((home / "asks.json").read_text(encoding="utf-8"))
    assert next(a["status"] for a in rows if a["id"] == aid) == "revoked"


def test_a_yes_the_chain_still_holds_stays_listed_and_is_released(served):          # must-pass beside K1
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(T("deleting"), C("Bash", {"command": "rm -rf logs"})))
    note = ask(client).content[-1].text
    aid = proxycmd.open_asks(home)[0]["id"]
    assert proxycmd.answer(home, aid, "yes") == "yes"
    assert aid in [x["id"] for x in proxycmd.page_asks(home)["asks"]]
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    assert [b.type for b in ask(client, history).content] == ["tool_use"]


def test_a_no_drops_the_held_call(served, capsys):
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    note = ask(client).content[-1].text
    aid = proxycmd.open_asks(home)[0]["id"]
    assert cli_run(tmp, home, "answer", aid, "no") == 0
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    history = [{"role": "user", "content": "go"}, {"role": "assistant", "content": [{"type": "text", "text": note}]},
               {"role": "user", "content": "carry on"}]
    again = ask(client, history)
    assert [b.type for b in again.content] == ["text"]                             # held again, not released
    assert "Waiting for the person's word" in again.content[-1].text


def test_answering_and_starting_are_refused_in_an_agents_shell(served, monkeypatch, capsys):   # must-refuse
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    aid = proxycmd.open_asks(home)[0]["id"]
    monkeypatch.setattr(cli, "human_terminal", lambda: "this is an agent's shell")
    assert cli_run(tmp, home, "answer", aid, "yes") != 0
    assert proxycmd.open_asks(home)[0]["id"] == aid                                 # still open: nothing answered
    assert cli_run(tmp, home, "serve", "--space", str(tmp / "space")) != 0
    assert cli_run(tmp, home, "asks") == 0                                          # listing is not refused


def test_an_ask_of_an_earlier_run_cannot_be_answered(served, capsys):              # must-refuse
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    aid = proxycmd.open_asks(home)[0]["id"]
    run = json.loads((home / "run.json").read_text(encoding="utf-8"))
    (home / "run.json").write_text(json.dumps({**run, "run": "a-later-run"}), encoding="utf-8")   # the proxy restarted
    capsys.readouterr()
    assert cli_run(tmp, home, "answer", aid, "yes") != 0
    assert "earlier run" in capsys.readouterr().err


def test_a_broken_record_answers_nothing(served, capsys):                          # must-refuse
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    aid = proxycmd.open_asks(home)[0]["id"]
    rec = home / "proxy.jsonl"
    lines = rec.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"kind":', '"kind" :', 1) if '"kind":' in lines[0] else lines[0] + " "
    rec.write_text("\n".join(lines) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert cli_run(tmp, home, "answer", aid, "yes") != 0
    assert "record is broken" in capsys.readouterr().err
    assert proxycmd.open_asks(home)[0]["id"] == aid


@pytest.mark.parametrize("word", ["YES!", "ok", "", "maybe"])
def test_only_yes_no_or_revoke_is_an_answer(served, word, capsys):                  # must-refuse
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    aid = proxycmd.open_asks(home)[0]["id"]
    assert cli_run(tmp, home, "answer", aid, word) != 0
    assert proxycmd.open_asks(home)[0]["id"] == aid


def test_no_proxy_yet_is_said_plainly(tmp_path, capsys):
    cli.main(["--home", str(tmp_path / "st"), "init"])
    capsys.readouterr()
    assert cli.main(["--home", str(tmp_path / "st"), "proxy", "asks", "--proxy-home", str(tmp_path / "none")]) != 0
    assert "semantext proxy serve" in capsys.readouterr().err


# ---- Koinos's attack on the serve command ----
def test_a_second_serve_on_the_same_folder_is_refused_and_renames_nothing(served, tmp_path):    # must-refuse
    stub, client, home, tmp = served
    before = (home / "run.json").read_text(encoding="utf-8")
    with pytest.raises(proxycmd.Refused) as e:
        proxycmd.serve(tmp / "space", home, CARD, free_port())
    assert "already runs" in str(e.value)
    assert (home / "run.json").read_text(encoding="utf-8") == before


def test_a_second_serve_on_a_taken_port_is_refused_and_renames_nothing(served):                  # must-refuse
    stub, client, home, tmp = served
    port = json.loads((home / "run.json").read_text(encoding="utf-8"))["port"]
    other = tmp / "otherhome"
    with pytest.raises(proxycmd.Refused) as e:
        proxycmd.serve(tmp / "space", other, CARD, port)
    assert "cannot be used" in str(e.value)
    # The failed start names no run: run.json says "starting" with none (K4), and nothing holds the folder now.
    doc = json.loads((other / "run.json").read_text(encoding="utf-8"))
    assert not doc.get("run") and doc.get("starting") is True
    assert proxycmd.page_asks(other) == {"state": "stopped", "asks": []}
    assert not (other / "asks.json").exists()


@pytest.mark.parametrize("content", ["5", "null", "[1, 2]", '[{"id": 5}]', '[{"id": "a", "expires": "x"}]',
                                     '[{"id": "a", "status": "open", "expires": 1e300, "reading": [1]}]',
                                     "[" * 100000 + "]" * 100000, "", "\ufeff[]", '{"a": 1}'],
                         ids=["int", "null", "list-of-ints", "id-int", "expires-str", "reading-list", "deep",
                              "empty", "bom", "object"])
def test_a_damaged_asks_file_gives_one_readable_refusal(served, content, capsys):
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    (home / "asks.json").write_text(content, encoding="utf-8")
    capsys.readouterr()
    for args in (["asks"], ["answer", "a", "yes"]):
        code = cli_run(tmp, home, *args)
        err = capsys.readouterr().err
        assert "Traceback" not in err and "please report" not in err.lower(), (content[:30], args, err)
    assert not any(a.get("status") == "yes" for a in _asks_raw(home))


def _asks_raw(home):
    try:
        d = json.loads((home / "asks.json").read_text(encoding="utf-8"))
    except (ValueError, RecursionError):
        return []
    return [a for a in d if isinstance(a, dict)] if isinstance(d, list) else []


def test_control_characters_in_the_asks_file_never_reach_the_terminal(served, capsys):
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    asks = json.loads((home / "asks.json").read_text(encoding="utf-8"))
    asks[0]["agent"] = "coder\x1b[2J\x1b]0;owned\x07" + "x" * 5_000_000
    (home / "asks.json").write_text(json.dumps(asks), encoding="utf-8")
    capsys.readouterr()
    assert cli_run(tmp, home, "asks") == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out and len(out) < 1000


def test_answer_stays_quick_on_a_long_record(served, capsys):
    import time as _t
    stub, client, home, tmp = served
    cli.main(["--home", str(tmp / "st"), "init"])
    _long_record(home / "proxy.jsonl", 5000)
    stub.replies.append(sse_turn(C("Bash", {"command": "rm -rf logs"})))
    ask(client)
    aid = proxycmd.open_asks(home)[0]["id"]
    t0 = _t.perf_counter()
    assert cli_run(tmp, home, "answer", aid, "yes") == 0
    assert _t.perf_counter() - t0 < 1.0


def _long_record(path, n):
    """A whole chain of n lines written at once (sealed as Record.append seals them), so a test can start from a long
    record without n durable appends."""
    import json as _json
    from semantext.proxy_record import Record
    from semantext.work import chain
    rec = Record(path)
    rec.verify()
    seq, prev = rec.seq, rec.prev
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    out = []
    for i in range(n):
        sealed = chain.seal({"v": 1, "id": f"pr_{i:026d}", "kind": "note", "provider": "semantext", "source": "proxy",
                             "at": "2026-11-07T00:00:00.000000Z", "body": {"i": i}}, seq + 1, prev)
        out.append(chain.line_of(sealed))
        seq, prev = sealed["seq"], sealed["hash"]
    path.write_text(existing + "".join(l + "\n" for l in out), encoding="utf-8", newline="\n")
    (path.parent / (path.name + ".head.json")).write_text(_json.dumps({"seq": seq, "hash": prev}), encoding="utf-8")
    assert Record(path).verify()


def test_an_append_does_not_grow_with_the_record(tmp_path):
    """Before, every append re-parsed the whole chain (45 ms a call at 5,000 lines, growing). Now the part already
    found whole is re-hashed, so an append at 50,000 lines costs about what it costs at 1,000."""
    import time as _t
    from semantext.proxy_record import Record
    small, big = tmp_path / "small" / "proxy.jsonl", tmp_path / "big" / "proxy.jsonl"
    small.parent.mkdir(); big.parent.mkdir()
    _long_record(small, 1000)
    _long_record(big, 50000)
    def per_append(path):
        r = Record(path)
        r.verify()                                   # the first read is a full one, as at start
        t0 = _t.perf_counter()
        for i in range(20):
            r.append("note", {"i": i})
        return (_t.perf_counter() - t0) / 20
    a, b = per_append(small), per_append(big)
    assert b < max(5 * a, 0.05), (a, b)


def test_an_edit_to_an_early_line_is_still_caught_at_the_next_append(tmp_path):     # must-refuse
    from semantext.proxy_record import Record, RecordFailed
    path = tmp_path / "proxy.jsonl"
    _long_record(path, 300)
    r = Record(path)
    assert r.verify()
    r.append("note", {"i": "x"})                      # the whole file is now known
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[10] = lines[10].replace('"i":10', '"i":11')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    with pytest.raises(RecordFailed):
        r.append("note", {"i": "y"})
    assert not Record(path).verify()


def test_lines_appended_by_another_process_are_read_and_checked(tmp_path):
    from semantext.proxy_record import Record
    path = tmp_path / "proxy.jsonl"
    a, b = Record(path), Record(path)
    a.append("note", {"i": 1})
    assert len(a.lines()) == 1
    b.append("note", {"i": 2})                        # the answering command, say
    assert [x["body"]["i"] for x in a.lines()] == [1, 2] and a.verify()
