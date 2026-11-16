"""The proxy page and command, after the pageasks attack (items P1 to P7).

P1 a stopped proxy's asks do not come back (serve.lock is the evidence, not run.json); P2 an interrupted append rolls
forward exactly one line; P3 honest refusals; P4 an expiry too large for a float; P5 the chain is read once per list;
P6 the page tells the truth (node); P7 the command can revoke. Each has its must-pass and its must-refuse.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from semantext import cli, decide, proxycmd
from semantext.proxy_record import Record, RecordFailed
from semantext.store import Refused, file_lock
from semantext.work import chain
from tests.test_proxy_page import (World, _proxies_end_with_the_test, answer, drive, home, hold_proxy, listed,  # noqa: F401
                                   needs_node, server, stop_proxy)

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- P1: a stopped proxy's asks do not come back
def test_a_stopped_proxy_lists_nothing_and_answers_nothing(server, home):   # must refuse
    w = World(home, running=False)                       # run.json and live-looking asks; nothing holds serve.lock
    aid = w.hold()
    rows = w.asks._read()
    rows[0]["expires"] = time.monotonic() + 5 * 86400    # days left, as after a reboot
    (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
    assert listed(server) == (200, {"state": "stopped", "asks": []})
    code, got = answer(server, aid, "yes")
    assert code == 400 and "has stopped" in got["error"] and "nothing was answered" in got["error"]
    assert w.status(aid) == "open" and w.chain() == []
    with pytest.raises(proxycmd.Stopped) as e:
        proxycmd.open_asks(w.home)
    assert "no proxy is running" in str(e.value) and "went with it" in str(e.value)
    with pytest.raises(proxycmd.Stopped):
        proxycmd.held_asks(w.home)
    with pytest.raises(proxycmd.Stopped):
        proxycmd.answer(w.home, aid, "yes")
    assert w.chain() == []


def test_a_proxy_that_ends_takes_its_asks_with_it(server, home):
    w = World(home)                                      # running: holds the lock
    aid = w.hold()
    assert [a["id"] for a in listed(server)[1]["asks"]] == [aid]
    stop_proxy(w.home)                                   # the process ends: the system lets the lock go
    assert listed(server) == (200, {"state": "stopped", "asks": []})
    assert answer(server, aid, "no")[0] == 400 and w.chain() == []


def test_the_command_says_a_stopped_proxy_is_stopped(home, capsys):
    w = World(home, running=False)
    w.hold()
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "asks"]) == 0
    out = capsys.readouterr().out
    assert "No proxy is running from this home" in out and "went with it" in out and "ask_" not in out


def test_no_proxy_ever_is_still_none_and_a_probe_makes_nothing(server, home, tmp_path):
    assert listed(server) == (200, {"state": "none", "asks": []})
    nowhere = tmp_path / "nowhere"
    assert proxycmd.proxy_running(nowhere) is False and not nowhere.exists()


HOLDER = ("import sys\nfrom pathlib import Path\nfrom semantext.store import file_lock\n"
          "with file_lock(Path(sys.argv[1])):\n    print('held', flush=True)\n    sys.stdin.readline()\n")


def test_a_lock_held_by_another_process_is_a_running_proxy(server, home):
    w = World(home, running=False)
    aid = w.hold()
    assert proxycmd.proxy_running(w.home) is False
    p = subprocess.Popen([sys.executable, "-X", "utf8", "-c", HOLDER, str(w.home / "serve.lock")], cwd=ROOT,
                         env={**os.environ, "PYTHONPATH": str(ROOT)}, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held"
        assert proxycmd.proxy_running(w.home) is True
        assert [a["id"] for a in listed(server)[1]["asks"]] == [aid]
        assert [a["id"] for a in proxycmd.open_asks(w.home)] == [aid]
        assert answer(server, aid, "yes")[0] == 200 and w.chain() == [(aid, "yes")]
    finally:
        p.stdin.write("\n"); p.stdin.flush(); p.wait(timeout=20)
    assert proxycmd.proxy_running(w.home) is False        # it ended, however it ended: the lock is free
    assert listed(server)[1]["state"] == "stopped"


def test_the_probe_lets_go_at_once_and_never_fails_a_starting_proxy(tmp_path):
    h = tmp_path / "h"
    h.mkdir()
    stop = threading.Event()
    probes = []

    def probe():
        while not stop.is_set():
            probes.append(proxycmd.proxy_running(h))
    t = threading.Thread(target=probe, daemon=True)
    t.start()
    try:
        for _ in range(40):                               # a proxy starting (serve waits 0.5 s) while probes run
            with file_lock(h / "serve.lock", timeout=0.5):
                pass
    finally:
        stop.set(); t.join(5)
    assert probes
    with file_lock(h / "serve.lock", timeout=0):          # and nothing is left held by the probe
        pass


def test_the_probe_does_not_take_a_lock_that_is_not_a_plain_file(tmp_path):   # must refuse to take it
    h = tmp_path / "h"
    (h / "serve.lock").mkdir(parents=True)
    assert proxycmd.proxy_running(h) is True              # K6: a lock that cannot be taken is never "stopped"
    assert (h / "serve.lock").is_dir()                    # and the probe made nothing of it


# ---------------------------------------------------------------- P2: an interrupted append rolls forward one line
def whole(path, n):
    r = Record(path)
    for i in range(n):
        r.append("note", {"i": i})
    return r


def ahead(path, n=1, seq=None, prev=None):
    """n sealed lines written after the file's end without moving the head: the process that died between the two."""
    rows = Record(path).lines()
    s, p = (rows[-1]["seq"], rows[-1]["hash"]) if rows else (0, chain.GENESIS)
    out = []
    for i in range(n):
        sealed = chain.seal({"v": 1, "id": f"pr_{s:026d}", "kind": "note", "provider": "semantext", "source": "proxy",
                             "at": "2026-11-07T00:00:00.000000Z", "body": {"x": i}}, (seq or s + 1), (prev or p))
        out.append(chain.line_of(sealed))
        s, p = sealed["seq"], sealed["hash"]
        seq = prev = None
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("".join(l + "\n" for l in out))


def test_one_line_ahead_of_the_head_is_rolled_forward(tmp_path):
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path)
    r = Record(path)
    assert r.verify() and r.seq == 4
    assert Record(path).verify()                          # any reader says the same
    r.append("note", {"i": "after"})                      # the next append writes the head over it
    fresh = Record(path)
    assert fresh.verify() and fresh.seq == 5 and len(fresh.lines()) == 5
    assert json.loads(fresh.head_path.read_text(encoding="utf-8"))["seq"] == 5


def test_one_line_ahead_of_an_empty_head_is_rolled_forward(tmp_path):
    path = tmp_path / "proxy.jsonl"
    ahead(path)                                           # the very first append: line written, head never was
    r = Record(path)
    assert r.verify() and r.seq == 1


def test_a_failed_head_write_is_healed_by_the_next_reader_but_not_by_its_own_process(tmp_path, monkeypatch):
    path = tmp_path / "proxy.jsonl"
    r = whole(path, 2)
    monkeypatch.setattr("semantext.proxy_record.os.replace", lambda *a: (_ for _ in ()).throw(OSError("disk")))
    with pytest.raises(RecordFailed):
        r.append("note", {"i": "x"})
    monkeypatch.undo()
    with pytest.raises(RecordFailed):                     # T8 unchanged: its own write failed, it stays broken
        r.append("note", {"i": "y"})
    assert not r.verify()
    other = Record(path)                                  # a new process looks and finds one line ahead
    assert other.verify() and other.seq == 3
    other.append("note", {"i": "z"})
    assert Record(path).verify()


@pytest.mark.parametrize("n", [2, 3])
def test_two_or_more_lines_ahead_stay_broken(tmp_path, n):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path, n)
    r = Record(path)
    assert not r.verify()
    with pytest.raises(RecordFailed):
        r.append("note", {})


def test_a_line_that_does_not_follow_the_head_stays_broken(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path, prev="0" * 64)
    assert not Record(path).verify()
    path2 = tmp_path / "b" / "proxy.jsonl"
    path2.parent.mkdir()
    whole(path2, 3)
    ahead(path2, seq=9)
    assert not Record(path2).verify()


def test_a_head_that_names_another_line_stays_broken_even_with_one_line_ahead(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    r = whole(path, 3)
    ahead(path)
    r.head_path.write_text(json.dumps({"seq": 3, "hash": "f" * 64}), encoding="utf-8")   # right count, wrong line
    assert not Record(path).verify()
    r.head_path.write_text(json.dumps({"seq": 2, "hash": Record(path).lines()[1]["hash"]}), encoding="utf-8")
    assert not Record(path).verify()                      # two ahead of a head that is honest about line 2


def test_a_line_that_names_the_old_head_but_skips_one_stays_broken(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    rows = Record(path).lines()
    ahead(path)                                           # one honest line ahead, then replace it with one sealed on line 2
    lines = path.read_text(encoding="utf-8").splitlines()
    sealed = chain.seal({"v": 1, "id": "pr_" + "0" * 26, "kind": "note", "provider": "semantext", "source": "proxy",
                         "at": "2026-11-07T00:00:00.000000Z", "body": {}}, 3, rows[1]["hash"])
    lines[-1] = chain.line_of(sealed)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    assert not Record(path).verify()


def test_an_earlier_line_changed_stays_broken_even_with_one_line_ahead(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[1] = lines[1].replace('"i":1', '"i":7')
    assert lines[1] != path.read_text(encoding="utf-8").splitlines()[1]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    assert not Record(path).verify()


def test_a_head_ahead_of_the_file_stays_broken(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 4)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8", newline="\n")     # a line dropped; the head names 4
    assert not Record(path).verify()


def test_a_torn_last_line_is_not_rolled_forward(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 2)
    ahead(path)
    data = path.read_bytes()
    path.write_bytes(data[:-20])                          # the extra line cut mid-way, no newline
    assert not Record(path).verify()


# ---------------------------------------------------------------- P3: honest refusals
def test_a_record_that_cannot_be_written_says_so_and_answers_nothing(server, home, monkeypatch):
    w = World(home)
    aid = w.hold()

    def fail(self, kind, body):
        raise RecordFailed("the record could not be written (OSError)")
    monkeypatch.setattr(Record, "append", fail)
    code, got = answer(server, aid, "yes")
    assert code == 400
    assert "could not write the proxy's record" in got["error"] and "nothing was answered" in got["error"]
    assert "needs looking at" in got["error"] and "could not be made" not in got["error"]
    assert w.status(aid) == "open"
    with pytest.raises(Refused) as e:
        proxycmd.answer(w.home, aid, "yes")
    assert "nothing was answered" in str(e.value)


def test_a_line_on_the_chain_and_no_asks_file_says_to_answer_again(server, home, monkeypatch):
    w = World(home)
    aid = w.hold()
    real = decide.Asks._write
    monkeypatch.setattr(decide.Asks, "_write", lambda self, asks: (_ for _ in ()).throw(
        decide.Refused("X-EXC", "the ask store cannot be written")))
    code, got = answer(server, aid, "yes")
    assert code == 400
    msg = got["error"]
    assert "on the proxy's record" in msg and "asks file could not be written" in msg
    assert "does not act on it" in msg and "answer again" in msg and "semantext proxy answer" in msg and "buttons" in msg
    assert w.chain() == [(aid, "yes")] and w.status(aid) == "open"
    monkeypatch.setattr(decide.Asks, "_write", real)
    assert answer(server, aid, "yes")[0] == 200            # answering again works, and the chain's last word is yes
    assert w.status(aid) == "yes"


def test_an_asks_file_that_fails_before_the_chain_is_not_called_answered(server, home, monkeypatch):   # must refuse
    w = World(home)
    aid = w.hold()
    monkeypatch.setattr(decide.Asks, "answer", lambda self, *a: (_ for _ in ()).throw(
        decide.Refused("X-EXC", "the ask store cannot be read")))
    code, got = answer(server, aid, "yes")
    assert code == 400 and "on the proxy's record" not in got["error"] and w.chain() == []


# ---------------------------------------------------------------- P4: an expiry too large for a float
BIG = "1" + "0" * 400


@pytest.mark.parametrize("expires", [BIG, "Infinity", "-Infinity", "NaN", "1e400"])
def test_an_expiry_too_large_for_a_float_is_unreadable_and_gets_a_response(server, home, expires, capsys):   # must refuse
    w = World(home)
    row = ('[{"id":"ask_X","run":"run-1","agent":"a","tool":"T","status":"open","expires":%s}]' % expires)
    (w.home / "asks.json").write_text(row, encoding="utf-8")
    too_big = expires in (BIG, "Infinity", "1e400")      # the minutes left cannot be worked out; the others never are live
    code, got = listed(server)
    assert (code, got) == (200, {"state": "unreadable" if too_big else "ok", "asks": []})
    for fn in (proxycmd.open_asks, proxycmd.held_asks):
        if too_big:
            with pytest.raises(Refused) as e:
                fn(w.home)
            assert "asks file holds something it should not" in str(e.value)
        else:
            assert fn(w.home) == []
    capsys.readouterr()
    assert (cli.main(["--home", str(home), "proxy", "asks"]) != 0) is too_big
    err = capsys.readouterr().err
    assert "Traceback" not in err and "please report" not in err.lower()


def test_a_huge_expiry_is_one_readable_refusal_at_the_command(home, capsys):
    w = World(home)
    (w.home / "asks.json").write_text('[{"id":"ask_X","run":"run-1","agent":"a","tool":"T","status":"open","expires":%s}]'
                                      % BIG, encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "asks"]) != 0
    err = capsys.readouterr().err
    assert "asks file holds something it should not" in err and "Traceback" not in err


def test_a_row_of_an_earlier_run_with_a_huge_expiry_does_not_hide_the_rest(server, home):
    w = World(home)
    aid = w.hold()
    rows = w.asks._read()
    rows.append({"id": "ask_old", "run": "run-0", "agent": "a", "tool": "T", "status": "open", "expires": 10 ** 400})
    (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
    assert [a["id"] for a in listed(server)[1]["asks"]] == [aid]        # never live, so never read as a number


# ---------------------------------------------------------------- P5: the chain is read once per list
def yes_world(home, n_yes, chain_lines):
    w = World(home)
    ids = []
    for i in range(n_yes):
        aid = w.hold(tool=f"T{i}", n=i)
        assert w.asks.answer(aid, "yes", time.monotonic())
        ids.append(aid)
    path = w.home / "proxy.jsonl"
    rec = Record(path)
    rec.verify()
    seq, prev = rec.seq, rec.prev
    out = []
    for i in range(max(0, chain_lines - seq)):
        sealed = chain.seal({"v": 1, "id": f"pr_{i:026d}", "kind": "note", "provider": "semantext", "source": "proxy",
                             "at": "2026-11-07T00:00:00.000000Z", "body": {"i": i}}, seq + 1, prev)
        out.append(chain.line_of(sealed))
        seq, prev = sealed["seq"], sealed["hash"]
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write("".join(l + "\n" for l in out))
    Path(str(path) + ".head.json").write_text(json.dumps({"seq": seq, "hash": prev}), encoding="utf-8")
    assert Record(path).verify()
    return w, ids


def test_the_list_reads_the_chain_once_however_many_yeses(home, monkeypatch):
    w, ids = yes_world(home, 20, 100)
    calls = []
    real = Record.lines
    monkeypatch.setattr(Record, "lines", lambda self: calls.append(1) or real(self))
    got = proxycmd.page_asks(w.home)
    assert [a["id"] for a in got["asks"]] == ids and len(calls) == 1
    assert w.asks.record is not None


def test_the_lists_time_does_not_grow_with_the_yeses(tmp_path):
    def cost(n_yes, sub):
        h = tmp_path / sub
        h.mkdir()
        w, ids = yes_world(h, n_yes, 5000)
        best = 9.0
        for _ in range(3):
            t0 = time.perf_counter()
            assert len(proxycmd.page_asks(w.home)["asks"]) == n_yes
            best = min(best, time.perf_counter() - t0)
        return best
    one, many = cost(1, "one"), cost(20, "many")
    assert many < 3 * one + 0.05, (one, many)


def test_the_chains_last_word_decides_and_a_spent_yes_is_not_listed(server, home):   # must refuse to show what releases nothing
    w = World(home)
    a, b, c, d = (w.hold(tool=f"T{i}", n=i) for i in range(4))
    for x in (a, b, c):
        assert w.asks.answer(x, "yes", time.monotonic())
    assert w.asks.answer(b, "revoke", time.monotonic())
    assert w.asks.spend([c], time.monotonic())
    rows = w.asks._read()
    for r in rows:
        if r["id"] in (b, c):
            r["status"] = "yes"                           # the file says yes again; the chain's last word / spent says not
    (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
    assert [(x["id"], x["status"]) for x in listed(server)[1]["asks"]] == [(a, "yes"), (d, "open")]


def test_a_broken_chain_lists_no_yes(server, home):   # must refuse
    w = World(home)
    aid = w.hold()
    w.asks.answer(aid, "yes", time.monotonic())
    (w.home / "proxy.jsonl").write_text("not a sealed line\n", encoding="utf-8")
    assert listed(server)[1]["asks"] == []


# ---------------------------------------------------------------- P7: the command can revoke
def test_a_yes_not_yet_used_is_listed_at_the_terminal_with_its_revoke_line(home, capsys, monkeypatch):
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    w = World(home)
    a, b = w.hold(), w.hold(tool="Write", n=2)
    assert w.asks.answer(a, "yes", time.monotonic())
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "asks"]) == 0
    lines = {l.split()[0]: l for l in capsys.readouterr().out.splitlines() if l.strip()}
    # the line carries the --home that chose the proxy's folder (attack 24, L3: it was dropped, and the pasted revoke
    # was refused in the default home while the yes stayed live)
    assert "a yes not yet used" in lines[a] and f"semantext --home {home} proxy answer {a} revoke" in lines[a]
    assert "yes not yet used" not in lines[b] and "revoke" not in lines[b]          # an open ask is not a yes
    assert [x["id"] for x in proxycmd.open_asks(w.home)] == [b]                     # open_asks lists only the open
    assert cli.main(["--home", str(home), "proxy", "answer", a, "revoke"]) == 0     # the printed line works
    capsys.readouterr()
    cli.main(["--home", str(home), "proxy", "asks"])
    out = capsys.readouterr().out
    assert a not in out and b in out and w.chain() == [(a, "yes"), (a, "revoke")]


def test_a_used_revoked_or_unproved_yes_is_not_listed_at_the_terminal(home, capsys):   # must refuse
    w = World(home)
    used, taken, unproved = w.hold(), w.hold(tool="B", n=2), w.hold(tool="C", n=3)
    for x in (used, taken):
        w.asks.answer(x, "yes", time.monotonic())
    w.asks.spend([used], time.monotonic())
    w.asks.answer(taken, "revoke", time.monotonic())
    rows = w.asks._read()
    rows[2]["status"] = "yes"                              # the file says yes; the chain says nothing
    (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "asks"]) == 0
    out = capsys.readouterr().out
    assert used not in out and taken not in out and unproved not in out and "Nothing waits for your word." in out


def test_the_revoke_line_names_a_given_proxy_home(tmp_path, capsys):
    ph = tmp_path / "elsewhere"
    w = World(tmp_path / "x")
    w2 = World.__new__(World)                              # a proxy home given with --proxy-home
    w2.home = ph
    proxycmd.write_run(ph, "run-1", 8790)
    hold_proxy(ph)
    w2.record = Record(ph / "proxy.jsonl")
    w2.asks = decide.Asks(ph / "asks.json", run="run-1", record=w2.record)
    aid = w2.hold()
    w2.asks.answer(aid, "yes", time.monotonic())
    capsys.readouterr()
    assert cli.main(["--home", str(tmp_path / "st"), "proxy", "asks", "--proxy-home", str(ph)]) == 0
    assert f"semantext --home {tmp_path / 'st'} proxy answer {aid} revoke --proxy-home {ph}" in capsys.readouterr().out


# ---------------------------------------------------------------- P6: the page tells the truth (node)
@needs_node
@pytest.mark.parametrize("then", [
    'state = "none"; asks = [];',
    'state = "stopped"; asks = [];',
    'state = "unreadable"; asks = [];',
    'down = true;',
    'asks = [];',                                         # the ask is no longer listed (used, run out, taken back)
    'asks[0].status = "open";',                           # listed, but no longer a yes
])
def test_the_release_note_is_cleared_when_it_is_no_longer_true(then):   # must refuse to keep a stale promise
    got = drive("""
asks = [ask("ask-1")];
fill(); await holdsRead(); await settle();
press("Yes once"); await settle();
const before = section().textContent;
""" + then + """
await holdsRead(); await settle();
report([before, section().textContent]);
""")
    assert "the proxy releases that call once" in got[0]
    assert "releases that call once" not in got[1] and "Said yes" not in got[1]


@needs_node
def test_the_release_note_stays_while_the_ask_is_still_a_yes():
    got = drive("""
asks = [ask("ask-1")];
fill(); await holdsRead(); await settle();
press("Yes once"); await settle();
asks[0].minutes_left = 3;
await holdsRead(); await settle();
report(section().textContent);
""")
    assert "the proxy releases that call once" in got


@needs_node
def test_a_stopped_proxy_is_said_in_plain_words():
    got = drive("""
state = "stopped";
fill(); await holdsRead(); await settle();
report([section().textContent, buttons()]);
""")
    assert "No proxy is running from this Semantext home" in got[0] and "what it held went with it" in got[0]
    assert "Nothing waits" not in got[0] and got[1] == []


@needs_node
def test_with_waiting_off_the_proxys_holds_are_still_shown():
    got = drive("""
S.data.waiting = { off: true, missing: ["inbox"], cards: [], seats: [], holds: { text: "" }, machine_inbox: [], change_records: [], changes: {}, frame: {} };
asks = [ask("ask-1"), ask("ask-2", { tool: "Write" })];
fill(); await holdsRead(); await settle();
report([section().textContent, buttons()]);
""")
    assert "The proxy holds 2 calls for you." in got[0] and "coder wants to call Bash" in got[0]
    assert got[1] == ["Yes once", "No", "Yes once", "No"]


@needs_node
def test_with_waiting_off_and_nothing_held_the_section_says_so():
    got = drive("""
S.data.waiting = { off: true, missing: ["inbox"], cards: [], seats: [], holds: { text: "" }, machine_inbox: [], change_records: [], changes: {}, frame: {} };
fill(); await holdsRead(); await settle();
report(section().textContent);
""")
    assert "Nothing waits for your word at the proxy." in got and "calls for you" not in got
