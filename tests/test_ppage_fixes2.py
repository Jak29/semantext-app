"""The proxy page and command, after the second pageasks attack (items K2 to K7; K1 is in test_proxy_cmd.py, through a
real proxy).

K4 a starting proxy names no run until it has one; K5 probes never meet at serve.lock; K6 a lock that cannot be taken
never reads as stopped; K3 a last line without its newline is never rolled forward nor written after; K2 a head that
cannot be a count is a broken record, not a traceback; K7 the printed "take it back" line is quoted for the shell it is
printed in. Each has its must-pass and its must-refuse.
"""
from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

from semantext import cli, decide, proxycmd
from semantext.proxy_record import Record, RecordFailed
from semantext.store import Refused, file_lock
from tests.test_ppage_fixes import ahead, whole
from tests.test_proxy_page import (World, _proxies_end_with_the_test, answer, home, hold_proxy, listed,  # noqa: F401
                                   server)


def days_left(w):
    rows = w.asks._read()
    for r in rows:
        r["expires"] = time.monotonic() + 5 * 86400        # as after a reboot: the monotonic clock starts again
    (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")


# ---------------------------------------------------------------- K4: a starting proxy names no run yet
@pytest.fixture
def starting(tmp_path, monkeypatch):
    """proxycmd.serve with the real lock and the real run file, and a stand-in for the long part (the proxy's own start:
    blocks, node key, record verify, bind). The stand-in is called while serve holds serve.lock and on_run has not run."""
    from semantext import blocks, proxy
    monkeypatch.setattr(blocks, "load", lambda d: None)
    seen = {}

    def install(fn):
        monkeypatch.setattr(proxy, "serve", fn)
    seen["install"] = install
    return seen


def probe_all(ph, aid):
    """What every way of looking at the proxy says right now: the page's list, the command's two lists, and an answer."""
    out = {"page": proxycmd.page_asks(ph)}
    for name in ("open_asks", "held_asks"):
        try:
            out[name] = getattr(proxycmd, name)(ph)
        except Refused as e:
            out[name] = type(e).__name__
    try:
        out["answer"] = proxycmd.answer(ph, aid, "yes")
    except Refused as e:
        out["answer"] = f"{type(e).__name__}: {e}"
    return out


def test_while_a_proxy_starts_the_dead_runs_asks_are_neither_listed_nor_answered(home, tmp_path, starting):   # must refuse
    w = World(home, running=False)                        # run-1 is dead: its asks have days left, nothing holds the lock
    aid = w.hold()
    days_left(w)
    window = []

    def slow_start(space_dir, ph, card, port, ready=None, on_run=None):
        window.append(probe_all(ph, aid))                 # serve holds serve.lock; run.json has not been rewritten
        on_run("run-2")
        window.append(probe_all(ph, aid))                 # the new run is named: the dead run's ask is another run's
    starting["install"](slow_start)
    proxycmd.serve(tmp_path / "space", w.home, "card", 8790)
    inside, after = window
    assert inside["page"] == {"state": "stopped", "asks": []}
    assert inside["open_asks"] == "Starting" and inside["held_asks"] == "Starting"
    assert inside["answer"].startswith("Starting:") and "nothing was answered" in inside["answer"]
    assert w.chain() == [] and w.status(aid) == "open"    # nothing was written for the dead run's ask
    assert after["page"] == {"state": "ok", "asks": []} and after["open_asks"] == [] and after["held_asks"] == []
    assert after["answer"].startswith("Refused: ") and "earlier run" in after["answer"]
    assert w.chain() == [] and w.status(aid) == "open"
    assert json.loads((w.home / "run.json").read_text(encoding="utf-8"))["run"] == "run-2"


def test_run_json_names_no_run_from_the_moment_serve_holds_the_lock(home, tmp_path, starting):
    w = World(home, running=False)
    seen = []
    starting["install"](lambda sp, ph, card, port, ready=None, on_run=None: seen.append(
        (json.loads((ph / "run.json").read_text(encoding="utf-8")), proxycmd.proxy_running(ph))))
    proxycmd.serve(tmp_path / "space", w.home, "card", 8790)
    doc, running = seen[0]
    assert not doc.get("run") and doc.get("starting") is True and running is True
    with pytest.raises(proxycmd.Stopped):
        proxycmd.open_asks(w.home)                        # the start ended without a run: nothing holds the lock now


def test_a_start_that_ends_without_a_run_reads_as_stopped_not_starting(home, tmp_path, starting, capsys, monkeypatch):
    w = World(home, running=False)
    aid = w.hold()
    days_left(w)

    def port_taken(sp, ph, card, port, ready=None, on_run=None):
        raise OSError(10048, "address in use")
    starting["install"](port_taken)
    with pytest.raises(Refused) as e:
        proxycmd.serve(tmp_path / "space", w.home, "card", 8790)
    assert "cannot be used" in str(e.value)
    assert proxycmd.page_asks(w.home) == {"state": "stopped", "asks": []}
    with pytest.raises(proxycmd.Stopped) as e2:
        proxycmd.answer(w.home, aid, "yes")
    assert not isinstance(e2.value, proxycmd.Starting) and "has stopped" in str(e2.value)
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "asks", "--proxy-home", str(w.home)]) == 0
    assert "No proxy is running" in capsys.readouterr().out


def test_the_command_says_a_proxy_is_starting(home, tmp_path, starting, capsys):
    w = World(home, running=False)
    out = []

    def slow_start(sp, ph, card, port, ready=None, on_run=None):
        capsys.readouterr()
        cli.main(["--home", str(home), "proxy", "asks", "--proxy-home", str(ph)])
        out.append(capsys.readouterr().out)
    starting["install"](slow_start)
    proxycmd.serve(tmp_path / "space", w.home, "card", 8790)
    assert "starting" in out[0] and "Nothing waits for your word" in out[0] and "No proxy is running" not in out[0]


def test_a_run_file_that_cannot_be_written_is_said_not_blamed_on_the_port(home, tmp_path, starting, monkeypatch):   # must refuse
    w = World(home, running=False)
    called = []
    starting["install"](lambda *a, **k: called.append(1))
    monkeypatch.setattr(proxycmd, "write_atomic", lambda *a: (_ for _ in ()).throw(PermissionError(13, "denied")))
    with pytest.raises(Refused) as e:
        proxycmd.serve(tmp_path / "space", w.home, "card", 8790)
    assert "run.json" in str(e.value) and "port" not in str(e.value) and not called   # the proxy never started


# ---------------------------------------------------------------- K5: a probe never meets a probe at serve.lock
def race(h, threads=4, each=150):
    results = []

    def probe():
        got = [proxycmd.proxy_running(h) for _ in range(each)]
        results.extend(got)
    ts = [threading.Thread(target=probe, daemon=True) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join(120) for t in ts]
    return results


def test_probes_racing_on_a_home_with_no_proxy_all_say_stopped(tmp_path):   # must refuse "running" for a dead proxy
    h = tmp_path / "h"
    h.mkdir()
    got = race(h)
    assert len(got) == 600 and not any(got), sum(got)


def test_a_dead_proxys_ask_is_never_answered_while_probes_race(home):   # must refuse
    w = World(home, running=False)
    stop = threading.Event()

    def hammering():
        while not stop.is_set():
            proxycmd.proxy_running(w.home)
    hammer = [threading.Thread(target=hammering, daemon=True) for _ in range(3)]
    [t.start() for t in hammer]
    taken = 0
    try:
        for i in range(120):
            aid = w.hold(agent=f"ag{i}")
            days_left(w)
            try:
                proxycmd.answer(w.home, aid, "yes")
                taken += 1
            except proxycmd.Stopped:
                pass
    finally:
        stop.set()
        [t.join(10) for t in hammer]
    assert taken == 0 and w.chain() == []


def test_probes_racing_on_a_home_with_a_proxy_all_say_running(tmp_path):
    h = tmp_path / "h"
    h.mkdir()
    hold_proxy(h)
    got = race(h, threads=3, each=60)
    assert len(got) == 180 and all(got)


def test_probes_wait_for_each_other_on_their_own_lock_not_on_serve_lock(tmp_path, monkeypatch):
    h = tmp_path / "h"
    h.mkdir()
    taken = []
    real = proxycmd.file_lock

    def spy(path, timeout=10.0):
        taken.append((Path(path).name, timeout))
        return real(path, timeout=timeout)
    monkeypatch.setattr(proxycmd, "file_lock", spy)
    assert proxycmd.proxy_running(h) is False
    assert [n for n, t in taken] == ["probe.lock", "serve.lock"]
    assert taken[0][1] > 0 and taken[1][1] == 0           # a short wait for other probes; none for the proxy's lock


def test_a_probe_does_not_make_a_folder(tmp_path):
    nowhere = tmp_path / "nowhere"
    assert proxycmd.proxy_running(nowhere) is False and not nowhere.exists()


# ---------------------------------------------------------------- K6: a lock that cannot be taken is never "stopped"
@pytest.mark.parametrize("fails,exc", [
    ("serve.lock", Refused("serve.lock is a folder, not a lock file; it is not taken as a lock")),
    ("serve.lock", Refused("serve.lock.gate has another name on disk (a hard link), so it is not taken as a lock")),
    ("serve.lock", Refused("serve.lock changed while it was opened, so it is not taken as a lock")),
    ("serve.lock", Refused("serve.lock is held by another writer for over 0 s; try again")),
    ("serve.lock", PermissionError(13, "denied")),
    ("serve.lock", OSError(5, "io")),
    ("serve.lock", ValueError("embedded null byte")),
    ("probe.lock", Refused("probe.lock is held by another writer for over 2 s; try again")),
    ("probe.lock", Refused("probe.lock is a folder, not a lock file; it is not taken as a lock")),
    ("probe.lock", PermissionError(13, "denied")),
])
def test_any_failure_to_take_a_lock_reads_as_running_never_stopped(tmp_path, monkeypatch, fails, exc):   # must refuse
    h = tmp_path / "h"
    h.mkdir()
    real = proxycmd.file_lock

    def selective(path, timeout=10.0):
        if Path(path).name == fails:
            raise exc
        return real(path, timeout=timeout)
    assert proxycmd.proxy_running(h) is False             # control: nothing in the way, a successful take, stopped
    monkeypatch.setattr(proxycmd, "file_lock", selective)
    assert proxycmd.proxy_running(h) is True


def shaped(w, shape):
    """Put a shape on the lock files of w's proxy home; the lock the proxy holds is already taken (World runs it)."""
    lock, gate = w.home / "serve.lock", w.home / "serve.lock.gate"
    try:
        if shape == "gate is a folder":
            os.rename(gate, w.home / "gate.moved")
            gate.mkdir()
        elif shape == "gate has another name":
            os.link(gate, w.home / "gate.link")
        elif shape == "lock has another name":
            os.link(lock, w.home / "lock.link")
        elif shape == "gate is read-only":
            os.chmod(gate, stat.S_IREAD)
        elif shape == "lock is read-only":
            os.chmod(lock, stat.S_IREAD)
        elif shape == "probe.lock is a folder":
            (w.home / "probe.lock").mkdir()
    except OSError as e:
        pytest.skip(f"the shape cannot be made here: {e}")


SHAPES = ["gate is a folder", "gate has another name", "lock has another name", "gate is read-only", "lock is read-only",
          "probe.lock is a folder"]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_running_proxy_with_a_lock_shape_in_the_way_is_not_said_to_have_stopped(server, home, shape):   # must refuse
    w = World(home)                                       # running: it holds serve.lock
    aid = w.hold()
    shaped(w, shape)
    try:
        assert proxycmd.proxy_running(w.home) is True
        assert listed(server)[1]["state"] == "ok" and [a["id"] for a in listed(server)[1]["asks"]] == [aid]
        code, got = answer(server, aid, "no")
        assert code == 200 and w.status(aid) == "no"       # answered; never told "has stopped" while it holds the call
    finally:
        for p in (w.home / "serve.lock", w.home / "serve.lock.gate"):
            try:
                os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass


def test_a_lock_that_is_a_folder_reads_as_running_not_stopped(tmp_path):   # was: "not running, the safe side"
    h = tmp_path / "h"
    (h / "serve.lock").mkdir(parents=True)
    assert proxycmd.proxy_running(h) is True


# ---------------------------------------------------------------- K3: a last line missing its newline
def test_a_last_line_missing_only_its_newline_is_not_rolled_forward_nor_written_after(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path)                                           # sealed on the head; the head file was never moved
    data = path.read_bytes()
    assert data.endswith(b"\n")
    path.write_bytes(data[:-1])                           # a torn write cut exactly at the newline
    r = Record(path)
    assert not r.verify()
    with pytest.raises(RecordFailed):
        r.append("note", {"i": "after"})
    assert path.read_bytes() == data[:-1]                 # no append wrote after the torn line
    assert not Record(path).verify()


def test_a_head_naming_a_last_line_that_lost_its_newline_takes_no_append(tmp_path):   # must refuse
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    data = path.read_bytes()
    path.write_bytes(data[:-1])                           # nothing ahead: the head names this line, newline gone
    r = Record(path)
    assert not r.verify()
    with pytest.raises(RecordFailed):
        r.append("note", {})
    assert path.read_bytes() == data[:-1]
    fresh = Record(path)
    fresh.verify()
    with pytest.raises(RecordFailed):
        fresh.append("note", {})
    assert path.read_bytes() == data[:-1]


def test_a_line_that_ends_with_its_newline_is_still_rolled_forward(tmp_path):
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path)
    r = Record(path)
    assert r.verify() and r.seq == 4
    r.append("note", {"i": "after"})
    fresh = Record(path)
    assert fresh.verify() and fresh.seq == 5
    assert path.read_bytes().count(b"\n") == 5 and path.read_bytes().endswith(b"\n")


def test_a_crlf_line_end_is_still_whole(tmp_path):
    path = tmp_path / "proxy.jsonl"
    whole(path, 3)
    ahead(path)
    data = path.read_bytes()
    path.write_bytes(data[:-1] + b"\r\n")
    r = Record(path)
    assert r.verify() and r.seq == 4


def test_the_command_answers_nothing_on_a_record_whose_last_line_lost_its_newline(home):   # must refuse
    w = World(home)
    aid = w.hold()
    w.record.append("note", {"i": 1})
    p = w.home / "proxy.jsonl"
    data = p.read_bytes()
    p.write_bytes(data[:-1])
    with pytest.raises(Refused) as e:
        proxycmd.answer(w.home, aid, "yes")
    assert "record is broken" in str(e.value)
    assert p.read_bytes() == data[:-1] and w.status(aid) == "open"


# ---------------------------------------------------------------- K2: a head that cannot be a count
HEADS = ['{"seq": -1, "hash": "x"}', '{"seq": "-1", "hash": "x"}', '{"seq": -1.5, "hash": "x"}',
         '{"seq": true, "hash": "x"}', '{"seq": null, "hash": "x"}', '{"seq": [], "hash": "x"}',
         '{"seq": "x", "hash": "x"}', '{"seq": 1.5, "hash": "x"}', '{"seq": Infinity, "hash": "x"}',
         '{"seq": 1e400, "hash": "x"}', '{"seq": " 1 ", "hash": "x"}', '[]', '"x"', '5']
CHAINS = {"empty": b"", "blank": b"\n  \n\n", "one": None}


@pytest.mark.parametrize("head", HEADS)
@pytest.mark.parametrize("chain_kind", list(CHAINS))
def test_a_head_that_cannot_be_a_count_is_a_broken_record_not_a_traceback(tmp_path, head, chain_kind):   # must refuse
    path = tmp_path / "proxy.jsonl"
    if chain_kind == "one":
        whole(path, 1)
    else:
        path.write_bytes(CHAINS[chain_kind])
    Path(str(path) + ".head.json").write_text(head, encoding="utf-8")
    before = path.read_bytes()
    r = Record(path)
    assert r.verify() is False
    with pytest.raises(RecordFailed):
        r.append("note", {})
    assert Record(path).verify() is False
    assert path.read_bytes() == before


def test_a_negative_head_over_an_empty_chain_is_a_refusal_at_the_command_and_the_page(server, home):   # must refuse
    w = World(home)
    aid = w.hold()
    (w.home / "proxy.jsonl").write_bytes(b"")
    (w.home / "proxy.jsonl.head.json").write_text('{"seq": -1, "hash": "x"}', encoding="utf-8")
    with pytest.raises(Refused) as e:
        proxycmd.answer(w.home, aid, "yes")
    assert "record is broken" in str(e.value)
    code, got = answer(server, aid, "yes")
    assert code == 400 and "record is broken" in got["error"] and "error_id" not in got
    assert w.status(aid) == "open"


def test_an_index_error_from_a_damaged_file_is_still_one_readable_refusal(home, monkeypatch):   # must refuse
    w = World(home)
    aid = w.hold()
    monkeypatch.setattr(decide.Asks, "answer", lambda self, *a: [][0])
    with pytest.raises(Refused) as e:
        proxycmd.answer(w.home, aid, "yes")
    assert "nothing was answered" in str(e.value)


def test_a_head_that_is_a_whole_count_still_works(tmp_path):
    path = tmp_path / "proxy.jsonl"
    r = whole(path, 3)
    head = json.loads(r.head_path.read_text(encoding="utf-8"))
    for form in (head["seq"], str(head["seq"])):
        r.head_path.write_text(json.dumps({"seq": form, "hash": head["hash"]}), encoding="utf-8")
        assert Record(path).verify()
    r.head_path.unlink()
    assert not Record(path).verify()                      # no head, three lines: still broken (unchanged)


# ---------------------------------------------------------------- K7: the printed line is quoted for its shell
AID = "ask_0123456789ABCDEFGHJKMNPQRS"


@pytest.mark.parametrize("windows,text,want", [
    (True, r"C:\Users\you\proxy", r"C:\Users\you\proxy"),
    (True, r"C:\my proxy home", r"'C:\my proxy home'"),
    (True, r"C:\it's here", r"'C:\it''s here'"),
    (True, "C:\\a\u2019b c", "'C:\\a\u2019\u2019b c'"),           # PowerShell reads a curly quote as a quote
    (True, "C:\\x;y $z `w", "'C:\\x;y $z `w'"),
    (True, "-flag", "'-flag'"),
    (False, "/home/you/proxy", "/home/you/proxy"),
    (False, "/home/my proxy", "'/home/my proxy'"),
    (False, "/home/it's", "'/home/it'\"'\"'s'"),
])
def test_quoting_for_each_shell(windows, text, want):
    assert proxycmd.shell_quote(text, windows=windows) == want


@pytest.mark.parametrize("bad", ["ask_A; Start-Process notepad; #", "ask_B$(Start-Process notepad)", "ask_E | Out-File x",
                                 "ask_" + "G" * 90, "-x", "", "ask_0123456789ABCDEFGHJKMNPQR", "ask_0123456789abcdefghjkmnpqrs",
                                 AID + "\n", AID + " revoke", "x" + AID])
def test_no_line_is_printed_for_an_id_that_is_not_the_proxys_own_shape(bad):   # must refuse
    assert proxycmd.revoke_line(bad, None) is None
    assert proxycmd.revoke_line(AID, None) == f"semantext proxy answer {AID} revoke"


def test_no_line_is_printed_for_a_home_with_a_control_character():   # must refuse
    assert proxycmd.revoke_line(AID, "C:\\a\nb") is None and proxycmd.revoke_line(AID, "/a\x1b[2Jb") is None


def run_in_shell(line: str) -> list:
    """The printed line, run as is in the shell of this machine, with `semantext` standing for a program that prints the
    arguments it was given."""
    dump = "import sys, json; sys.stdout.write(json.dumps(sys.argv[1:]))"
    if os.name == "nt":
        script = f"function semantext {{ & '{sys.executable}' -X utf8 -c '{dump}' @args }}; {line}"
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    else:
        script = f"semantext() {{ '{sys.executable}' -c '{dump}' \"$@\"; }}; {line}"
        cmd = ["sh", "-c", script]
    done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


@pytest.mark.parametrize("name", ["my proxy home", "it's a 'proxy' home", "dollar $x and `tick` ; semi", "plain"])
def test_the_printed_line_runs_as_printed_with_a_home_holding_spaces_and_quotes(tmp_path, name, capsys, monkeypatch):
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    ph = tmp_path / name
    w = World.__new__(World)
    w.home = ph
    proxycmd.write_run(ph, "run-1", 8790)
    hold_proxy(ph)
    w.record = Record(ph / "proxy.jsonl")
    w.asks = decide.Asks(ph / "asks.json", run="run-1", record=w.record)
    aid = w.asks.open("coder", "space", "Bash", "delete", "d1", "conv-1", time.monotonic(),
                      reading={"act": "delete", "word": "W", "rule": "Confirm"})
    assert w.asks.answer(aid, "yes", time.monotonic())
    capsys.readouterr()
    assert cli.main(["--home", str(tmp_path / "st"), "proxy", "asks", "--proxy-home", str(ph)]) == 0
    printed = [l for l in capsys.readouterr().out.splitlines() if "proxy answer" in l]
    assert len(printed) == 1
    line = printed[0][printed[0].index("semantext "):]
    argv = run_in_shell(line)
    assert argv == ["--home", str(tmp_path / "st"), "proxy", "answer", aid, "revoke", "--proxy-home", str(ph)]
    args = cli.build_parser().parse_args(argv)            # and the command's own parser reads it as that command
    assert args.rest == [aid, "revoke"] and args.proxy_home == str(ph) and args.home == str(tmp_path / "st")
    assert cli.main(argv) == 0                            # as printed: no --home added by the test (attack 24, L3)
    assert [(a, wd) for a, wd in [(r["body"]["ask"], r["body"]["word"]) for r in w.record.lines()
                                  if r.get("kind") == "answered"]] == [(aid, "yes"), (aid, "revoke")]


def test_a_yes_with_an_odd_id_is_listed_with_no_command_line(home, capsys):   # must refuse to print a line that is not the proxy's
    w = World(home)
    w.hold()
    rows = w.asks._read()
    rows[0]["id"] = "ask_A; Start-Process notepad; #"     # a writer with file rights: the stated A1 limit
    rows[0]["status"] = "yes"
    (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
    w.record.append("answered", {"ask": rows[0]["id"], "word": "yes"})
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "asks"]) == 0
    out = capsys.readouterr().out
    assert "a yes not yet used" in out and "proxy answer" not in out
