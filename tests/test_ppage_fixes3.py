"""The proxy page and command, round 4 (attack 24, after the third fix round): L2 and L3.

L2  K4's residual was wider than its stated limit. During a new proxy's start the dead run's asks were listed in 150 of
    150 starts and a dead run's yes was taken in 114, mostly by listings and answers that read run.json BEFORE serve took
    serve.lock and probed AFTER it (the probe can wait on probe.lock behind other probes). _run_of now probes first and
    reads run.json after it; the asks file's reads look at run.json again (after the read for a listing, and under the
    asks file's own lock for an answer), and refuse when run.json is starting or names another run than the asks were
    made under. The remaining window is the one atomic write of the starting run.json (stated in _run_of).
L3  The printed "take it back" line dropped a global --home: pasted as printed it answered in the default home, was
    refused, and the yes stayed live. It now carries every option that chose the proxy's folder, quoted for the shell.

Each test names what it fails on at 99f9116.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
from pathlib import Path

import pytest

from semantext import cli, decide, proxycmd
from semantext.store import Refused, Store
from tests.test_ppage_fixes2 import AID, days_left, run_in_shell
from tests.test_proxy_page import World, _proxies_end_with_the_test, home, hold_proxy  # noqa: F401


# ---------------------------------------------------------------- L2: the order of the probe and the run file
class NewProxy:
    """A second proxy starting on the folder: the real proxycmd.serve (real serve.lock, real starting run.json), with a
    stand-in for proxy.serve that waits until the test lets it name its run."""

    def __init__(self, monkeypatch, tmp_path):
        from semantext import blocks, proxy
        monkeypatch.setattr(blocks, "load", lambda d: None)
        self.entered, self.release = threading.Event(), threading.Event()
        self.thread = None
        self.tmp = tmp_path

        def stand_in(space_dir, home, card, port, ready=None, on_run=None):
            self.entered.set()
            assert self.release.wait(30)
            on_run("run-new")
        monkeypatch.setattr(proxy, "serve", stand_in)

    def start(self, home):
        """Take the folder and write the starting run.json, then return (the proxy is mid-start)."""
        if self.thread is None:
            self.thread = threading.Thread(target=proxycmd.serve, args=(self.tmp / "space", home, "card", 8790), daemon=True)
            self.thread.start()
            assert self.entered.wait(30)

    def finish(self):
        self.release.set()
        if self.thread is not None:
            self.thread.join(30)


@pytest.fixture
def new_proxy(monkeypatch, tmp_path):
    p = NewProxy(monkeypatch, tmp_path)
    yield p
    p.finish()


def dead_world(home):
    w = World(home, run_id="dead-run", running=False)      # nothing holds serve.lock; its asks have days left (a reboot)
    aid = w.hold()
    days_left(w)
    return w, aid


def probe_then_start(monkeypatch, new_proxy, home):
    """Make the new proxy take serve.lock and write its starting run.json in the gap between a reader's first look at
    run.json and its probe (what a probe waiting at probe.lock gives): the probe itself is the real one."""
    real = proxycmd.proxy_running

    def probe(h):
        new_proxy.start(home)
        return real(h)
    monkeypatch.setattr(proxycmd, "proxy_running", probe)


def test_a_listing_whose_probe_meets_the_new_proxy_does_not_list_the_dead_runs_asks(home, new_proxy, monkeypatch):   # must-refuse
    w, aid = dead_world(home)
    probe_then_start(monkeypatch, new_proxy, w.home)
    assert proxycmd.page_asks(w.home) == {"state": "stopped", "asks": []}, "run.json was read before the probe"
    assert new_proxy.thread is not None, "the new proxy never started: the test would pass for nothing"


@pytest.mark.parametrize("answering", [False, True])
def test_the_run_is_read_after_the_probe_not_before_it(home, new_proxy, monkeypatch, answering):   # must-refuse (the order itself)
    """Alone, without the second look at run.json that follows: the name _run_of returns is the one read after the probe."""
    w, aid = dead_world(home)
    probe_then_start(monkeypatch, new_proxy, w.home)
    with pytest.raises(proxycmd.Starting) as e:
        proxycmd._run_of(w.home, answering=answering)
    assert ("nothing was answered" in str(e.value)) == answering and new_proxy.thread is not None


@pytest.mark.parametrize("lister", ["open_asks", "held_asks"])
def test_the_commands_listing_whose_probe_meets_the_new_proxy_lists_nothing(home, new_proxy, monkeypatch, lister):   # must-refuse
    w, aid = dead_world(home)
    probe_then_start(monkeypatch, new_proxy, w.home)
    with pytest.raises(proxycmd.Starting):
        getattr(proxycmd, lister)(w.home)
    assert new_proxy.thread is not None


def test_an_answer_whose_probe_meets_the_new_proxy_takes_nothing(home, new_proxy, monkeypatch):   # must-refuse
    w, aid = dead_world(home)
    probe_then_start(monkeypatch, new_proxy, w.home)
    with pytest.raises(proxycmd.Starting) as e:
        proxycmd.answer(w.home, aid, "yes")
    assert "nothing was answered" in str(e.value) and new_proxy.thread is not None
    assert w.status(aid) == "open" and w.chain() == [], "the dead run's ask was answered"


# The look at run.json that follows the asks file's read (the move from "the probe said running" to "this is the file").
def test_a_start_that_begins_after_the_asks_file_was_read_stops_the_listing(home, monkeypatch):      # must-refuse
    w = World(home)                                        # a proxy of run-1 that runs (it holds serve.lock)
    aid = w.hold()
    real = decide.Asks._read

    def read_then_restart(self):
        rows = real(self)
        proxycmd.write_starting(w.home, 8790)              # the next start lands between the read and the listing
        return rows
    monkeypatch.setattr(decide.Asks, "_read", read_then_restart)
    assert proxycmd.page_asks(w.home) == {"state": "stopped", "asks": []}
    with pytest.raises(proxycmd.Starting):
        proxycmd.open_asks(w.home)


@pytest.mark.parametrize("what", ["starting", "named"])
def test_a_start_that_lands_before_the_write_stops_the_answer_under_the_asks_lock(home, monkeypatch, what):   # must-refuse
    w = World(home)                                        # run-1 runs; run.json is read as run-1 ...
    aid = w.hold()
    real = proxycmd._asks

    def asks_then_restart(h, run, with_record=True):
        asks = real(h, run, with_record)                   # ... and the record was verified (the long part) ...
        if what == "starting":
            proxycmd.write_starting(h, 8790)               # ... then the start lands: run.json names no run
        else:
            proxycmd.write_run(h, "run-2", 8790)           # ... or names the new run
        return asks
    monkeypatch.setattr(proxycmd, "_asks", asks_then_restart)
    with pytest.raises(proxycmd.Stopped) as e:             # Starting is a Stopped
        proxycmd.answer(w.home, aid, "yes")
    assert isinstance(e.value, proxycmd.Starting) == (what == "starting")
    assert "nothing was answered" in str(e.value)
    assert w.status(aid) == "open" and w.chain() == [], "the answer was written after the start landed"


def test_a_proxy_that_runs_is_listed_and_answered_as_before(home):                                    # must-pass
    w = World(home)
    a, b = w.hold(), w.hold(tool="Write", n=2)
    got = proxycmd.page_asks(w.home)
    assert got["state"] == "ok" and [x["id"] for x in got["asks"]] == [a, b]
    assert proxycmd.answer(w.home, a, "yes") == "yes"
    assert proxycmd.answer(w.home, a, "revoke") == "revoked"
    assert proxycmd.answer(w.home, b, "no") == "no"
    assert w.chain() == [(a, "yes"), (a, "revoke"), (b, "no")]


def test_a_home_with_no_run_file_is_still_none_and_makes_no_lock_file(tmp_path):                      # must-pass
    ph = tmp_path / "empty"
    ph.mkdir()
    assert proxycmd.page_asks(ph) == {"state": "none", "asks": []}
    with pytest.raises(proxycmd.NoProxy):
        proxycmd.answer(ph, "ask_0123456789ABCDEFGHJKMNPQRS", "yes")
    assert list(ph.iterdir()) == [], "a look at a folder that never held a proxy made files in it"


def test_a_stopped_proxy_still_reads_stopped_and_answers_nothing(home):                              # must-pass
    w, aid = dead_world(home)
    assert proxycmd.page_asks(w.home) == {"state": "stopped", "asks": []}
    with pytest.raises(proxycmd.Stopped) as e:
        proxycmd.answer(w.home, aid, "yes")
    assert "has stopped" in str(e.value) and w.status(aid) == "open" and w.chain() == []


# ---- the attacker's k4_window.py and k4_start.py part 2, ported: many real starts under tight pollers
def test_no_dead_runs_ask_is_listed_or_taken_outside_the_one_file_write(home, tmp_path, monkeypatch):   # must-refuse
    """Real proxycmd.serve starts (real serve.lock, real write_starting) with a stand-in for the proxy's own start, and
    tight pollers listing and answering. For each dead-run listing and each dead-run yes taken, the last time the poll
    LOOKED at run.json (the look that decided it) must fall after serve began to take serve.lock (L) and before the
    starting run.json was in place (W): that is the one atomic write the docstring of _run_of states. A look before L is
    the read-before-the-probe the attacker found (100 of 102 listings, at 99f9116); a look after W is a start that was
    read past. Where the attacker saw the dead run's asks listed in 150 of 150 starts and a yes taken in 114 of 150,
    the looks that decide here are all inside the stated window."""
    from semantext import blocks, proxy
    monkeypatch.setattr(blocks, "load", lambda d: None)
    marks, counter = {}, [0]
    real_lock, real_ws, real_read = proxycmd.file_lock, proxycmd.write_starting, proxycmd.read_run
    local = threading.local()

    @contextlib.contextmanager
    def spy_lock(path, timeout=10.0):
        if str(path).endswith("serve.lock") and timeout == 0.5:
            marks["L"] = time.perf_counter()               # before the lock is taken: never later than the taking
        with real_lock(path, timeout=timeout):
            yield

    def spy_write_starting(h, port):
        real_ws(h, port)
        marks["W"] = time.perf_counter()

    def spy_read(h):
        local.looked = time.perf_counter()                 # before the read: never later than what the read saw
        return real_read(h)

    def stand_in(space_dir, h, card, port, ready=None, on_run=None):
        time.sleep(0.03)
        counter[0] += 1
        on_run(f"run-new-{counter[0]}")
    monkeypatch.setattr(proxycmd, "file_lock", spy_lock)
    monkeypatch.setattr(proxycmd, "write_starting", spy_write_starting)
    monkeypatch.setattr(proxycmd, "read_run", spy_read)
    monkeypatch.setattr(proxy, "serve", stand_in)

    w = World(home, run_id="dead-run", running=False)
    old = [w.hold(agent=f"ag{i}") for i in range(4)]

    def poller(stop, events, answers):
        while not stop.is_set():
            got = proxycmd.page_asks(w.home)
            dead = [x for x in got["asks"] if x["id"] in old] if got["state"] == "ok" else []
            if dead:
                events.append(("list", local.looked))
                if answers:
                    try:
                        said = proxycmd.answer(w.home, dead[0]["id"], "yes")
                    except Refused:
                        said = None
                    if said == "yes":
                        events.append(("take", local.looked))

    outside, seen = [], 0
    for _ in range(12):
        proxycmd.write_run(w.home, "dead-run", 8790)
        rows = w.asks._read()
        for r in rows:
            if r["id"] in old:
                r["status"], r["expires"] = "open", time.monotonic() + 5 * 86400
        (w.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
        events, stop = [], threading.Event()
        pollers = [threading.Thread(target=poller, args=(stop, events, True), daemon=True)]
        pollers += [threading.Thread(target=poller, args=(stop, events, False), daemon=True) for _ in range(2)]
        for t in pollers:
            t.start()
        time.sleep(0.03)
        marks.clear()
        proxycmd.serve(tmp_path / "nospace", w.home, "card", 8790)
        time.sleep(0.03)
        stop.set()
        for t in pollers:
            t.join(30)
        for kind, looked in events:
            seen += 1
            if not (marks["L"] <= looked < marks["W"]):
                outside.append((kind, round((looked - marks["L"]) * 1000, 1), round((looked - marks["W"]) * 1000, 1)))
    assert outside == [], f"{len(outside)} of {seen} dead-run listings/takes decided outside the lock-to-write window (ms from L, from W)"


# ---------------------------------------------------------------- L3: the printed line carries the home
def a_live_yes(home):
    w = World(home)
    aid = w.hold()
    assert w.asks.answer(aid, "yes", time.monotonic())
    return w, aid


def printed_line(capsys, argv):
    capsys.readouterr()
    assert cli.main(argv) == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if "proxy answer" in l]
    assert len(lines) == 1
    return lines[0][lines[0].index("semantext "):]


def the_proxy_home_of(argv):
    """The folder `semantext <argv>` would use, computed the way cmd_proxy does."""
    args = cli.build_parser().parse_args(argv)
    return proxycmd.proxy_home(Store.open(args.home).root, args.proxy_home).resolve()


def test_the_printed_line_names_the_same_proxy_home_as_the_listing(home, capsys, monkeypatch):   # must-refuse (99f9116: no --home)
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    w, aid = a_live_yes(home)
    line = printed_line(capsys, ["--home", str(home), "proxy", "asks"])
    argv = run_in_shell(line)
    assert argv[:2] == ["--home", str(home)], line
    assert the_proxy_home_of(argv) == w.home.resolve(), "pasted as printed, it would answer in another folder"
    assert cli.main(argv) == 0                             # and as printed it takes the yes back
    assert w.chain() == [(aid, "yes"), (aid, "revoke")]
    assert w.status(aid) == "revoked"


@pytest.mark.parametrize("name", ["my home", "it's a 'home'", "dollar $x and `tick` ; semi"])
def test_the_printed_line_quotes_a_home_for_the_shell_and_still_names_the_folder(tmp_path, capsys, monkeypatch, name):   # must-refuse
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    h = tmp_path / name
    assert cli.main(["--home", str(h), "init"]) == 0
    w, aid = a_live_yes(h)
    line = printed_line(capsys, ["--home", str(h), "proxy", "asks"])
    argv = run_in_shell(line)
    assert argv[:2] == ["--home", str(h)]
    assert the_proxy_home_of(argv) == w.home.resolve()
    assert cli.main(argv) == 0 and w.status(aid) == "revoked"


def test_the_printed_line_carries_both_options_when_both_chose_the_folder(home, tmp_path, capsys, monkeypatch):   # must-refuse
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    ph = tmp_path / "elsewhere"
    w = World.__new__(World)
    w.home = ph
    proxycmd.write_run(ph, "run-1", 8790)
    hold_proxy(ph)
    from semantext.proxy_record import Record
    w.record = Record(ph / "proxy.jsonl")
    w.asks = decide.Asks(ph / "asks.json", run="run-1", record=w.record)
    aid = w.hold()
    assert w.asks.answer(aid, "yes", time.monotonic())
    line = printed_line(capsys, ["--home", str(home), "proxy", "asks", "--proxy-home", str(ph)])
    argv = run_in_shell(line)
    assert argv == ["--home", str(home), "proxy", "answer", aid, "revoke", "--proxy-home", str(ph)]
    assert the_proxy_home_of(argv) == ph.resolve()
    assert cli.main(argv) == 0 and w.status(aid) == "revoked"


def test_with_neither_option_the_line_names_neither(home, capsys, monkeypatch):                    # must-pass
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    monkeypatch.setenv("SEMANTEXT_HOME", str(home))        # the variable chose the home; the pasted line has it set too
    w, aid = a_live_yes(home)
    line = printed_line(capsys, ["proxy", "asks"])
    assert line == f"semantext proxy answer {aid} revoke"


@pytest.mark.parametrize("given", [("C:\\a\nb", None), (None, "C:\\a\nb"), ("/a\x1b[2Jb", "/ok"), ("/ok", "/a\x00b")])
def test_no_line_is_printed_when_either_folder_cannot_be_quoted(given):                            # must-refuse
    h, ph = given
    assert proxycmd.revoke_line(AID, ph, h) is None
    assert proxycmd.revoke_line(AID, None, None) == f"semantext proxy answer {AID} revoke"


def test_the_line_puts_home_before_the_command_and_proxy_home_after_it():                         # must-pass
    h, p = str(Path("/h")), str(Path("/p"))                # the separator of the machine the line is printed on
    line = proxycmd.revoke_line(AID, "/p", "/h")
    assert line == f"semantext --home {h} proxy answer {AID} revoke --proxy-home {p}"
    assert proxycmd.revoke_line(AID, None, "/h") == f"semantext --home {h} proxy answer {AID} revoke"
    assert proxycmd.revoke_line(AID, "/p", None) == f"semantext proxy answer {AID} revoke --proxy-home {p}"
