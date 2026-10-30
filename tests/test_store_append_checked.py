"""store.append_checked: lock, check, append one whole line, sync (doors spec v0.6, rule 10). Each behaviour has a test
that must pass and, where it can go wrong, one that must be refused."""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from semantext import store
from semantext.store import Refused, Tail, append_checked, file_lock


def test_a_line_is_appended_whole_with_its_newline(tmp_path):
    p = tmp_path / "log.jsonl"
    assert append_checked(p, None, '{"a":1}') == '{"a":1}'
    append_checked(p, None, lambda tail: f'{{"n":{len(tail.lines)}}}')
    assert p.read_bytes() == b'{"a":1}\n{"n":1}\n'


def test_a_check_that_refuses_writes_nothing(tmp_path):
    p = tmp_path / "log.jsonl"
    append_checked(p, None, "one")

    def no(tail):
        raise Refused("not this one")
    with pytest.raises(Refused, match="not this one"):
        append_checked(p, no, "two")
    assert p.read_bytes() == b"one\n"


def test_a_line_with_a_line_break_inside_is_refused(tmp_path):
    p = tmp_path / "log.jsonl"
    for bad in ("a\nb", "a\rb", 7):
        with pytest.raises(Refused, match="one line"):
            append_checked(p, None, bad)
    assert not p.exists() or p.read_bytes() == b""


def test_a_torn_tail_is_never_glued_to_the_new_line_starts_fresh(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_bytes(b'{"a":1}\n{"b":')
    seen = {}

    def look(tail):
        seen["torn"], seen["lines"] = tail.torn, tail.lines
    append_checked(p, look, '{"c":3}')
    assert seen == {"torn": '{"b":', "lines": ['{"a":1}']}
    assert p.read_bytes() == b'{"a":1}\n{"b":\n{"c":3}\n'   # the fragment is a line of its own; the new line is whole


def test_the_tail_of_a_whole_file_has_no_torn_part():
    assert Tail(b"a\nb\n").torn is None and Tail(b"a\nb\n").lines == ["a", "b"]
    assert Tail(b"").torn is None and Tail(b"").lines == []
    assert Tail(b"a\r\nb").lines == ["a\r"] and Tail(b"a\r\nb").torn == "b"


def test_a_held_lock_refuses_after_its_timeout_and_frees_when_released(tmp_path):
    p = tmp_path / "log.jsonl"
    with file_lock(p.with_name(p.name + ".lock")):
        with pytest.raises(Refused, match="held by another writer"):
            append_checked(p, None, "x", timeout=0.2)
    append_checked(p, None, "y", timeout=0.2)   # released: the partner goes through
    assert p.read_bytes() == b"y\n"


@pytest.mark.parametrize("name", [".lock", ".lock.gate"])
def test_a_folder_at_the_lock_or_its_gate_is_refused_and_nothing_is_written(tmp_path, name):   # must refuse
    p = tmp_path / "log.jsonl"
    (tmp_path / ("log.jsonl" + name)).mkdir()
    with pytest.raises(Refused, match="not a lock file"):
        append_checked(p, None, "x")
    assert not p.exists()


def test_a_link_at_the_lock_is_refused_and_nothing_is_made_where_it_leads(tmp_path):   # must refuse
    p, elsewhere = tmp_path / "log.jsonl", tmp_path / "elsewhere"
    elsewhere.mkdir()
    lock = tmp_path / "log.jsonl.lock"
    if os.name == "nt":   # a junction needs no privilege, so this arm runs on Windows too
        import _winapi
        _winapi.CreateJunction(str(elsewhere), str(lock))
    else:
        os.symlink(elsewhere / "planted.lock", lock)
    with pytest.raises(Refused, match="not a lock file") as e:
        append_checked(p, None, "x")
    # the refusal claims no more than it knows: in the race on Windows the open may already have made a file
    assert "it is not taken as a lock" in str(e.value) and "nothing is written" not in str(e.value)
    assert not p.exists() and list(elsewhere.iterdir()) == []


@pytest.mark.parametrize("name", [".lock", ".lock.gate"])
def test_a_hard_link_at_the_lock_or_its_gate_is_refused_and_the_other_file_is_untouched(tmp_path, name):   # refuse
    p, other = tmp_path / "log.jsonl", tmp_path / "someone-elses.txt"
    other.write_bytes(b"not a lock")
    os.link(other, tmp_path / ("log.jsonl" + name))   # a second name for another file: its bytes would be locked
    with pytest.raises(Refused, match="hard link"):
        append_checked(p, None, "x")
    assert not p.exists() and other.read_bytes() == b"not a lock"


def test_a_file_swapped_in_between_the_look_and_the_open_is_refused(tmp_path, monkeypatch):   # must refuse
    # Windows has no O_NOFOLLOW, so the name can change between lstat and open: here, just before the open, the plain
    # lock is replaced by another file. The open then holds a file that is not the one looked at, and it is refused.
    p = tmp_path / "log.jsonl"
    lock = tmp_path / "log.jsonl.lock"
    lock.write_bytes(b"")
    real_open = os.open

    def swapping(path, *args, **kw):
        if os.fspath(path) == os.fspath(lock):
            stand_in = tmp_path / "stand-in"
            stand_in.write_bytes(b"put here between the look and the open")
            os.replace(stand_in, lock)
        return real_open(path, *args, **kw)
    monkeypatch.setattr(store.os, "open", swapping)
    with pytest.raises(Refused, match="changed while it was opened"):
        append_checked(p, None, "x")
    monkeypatch.setattr(store.os, "open", real_open)
    append_checked(p, None, "y")   # must pass: nothing swapped, the same lock file is taken
    assert p.read_bytes() == b"y\n"


class _Stat:   # what lstat says of a name on Windows: its mode, its attributes, its reparse tag
    def __init__(self, mode, attributes=0, tag=0):
        self.st_mode, self.st_file_attributes, self.st_reparse_tag = mode, attributes, tag


@pytest.mark.parametrize("tag, said", [(0x9000001A, None),                  # a cloud placeholder of a file: plain
                                       (0xA000000C, "a link or a junction"),  # a symbolic link: names another place
                                       (0xA0000003, "a link or a junction")])  # a junction: names another place
def test_a_reparse_point_is_a_link_only_when_its_tag_names_another_place(tmp_path, monkeypatch, tag, said):
    import stat as st
    monkeypatch.setattr(store.os, "lstat", lambda p: _Stat(st.S_IFREG | 0o644, st.FILE_ATTRIBUTE_REPARSE_POINT
                                                            if hasattr(st, "FILE_ATTRIBUTE_REPARSE_POINT") else 0x400,
                                                            tag))
    assert store._standing(tmp_path / "log.jsonl.lock") == said   # a placeholder passes; a link is said as one


def test_what_stands_at_a_lock_is_said_as_what_it_is(tmp_path):
    (tmp_path / "f").mkdir()
    assert store._standing(tmp_path / "f") == "a folder"           # must refuse, and say what it is
    (tmp_path / "plain").write_bytes(b"")
    assert store._standing(tmp_path / "plain") is None             # must pass
    assert store._standing(tmp_path / "missing") is None


def test_a_plain_lock_and_gate_left_behind_are_taken_as_before(tmp_path):   # must pass
    p = tmp_path / "log.jsonl"
    (tmp_path / "log.jsonl.lock").write_bytes(b"left by a writer that died")
    (tmp_path / "log.jsonl.lock.gate").write_bytes(b"")
    append_checked(p, None, "x")
    assert p.read_bytes() == b"x\n"


def test_threads_never_interleave_and_every_check_sees_the_lines_before_it(tmp_path):
    p = tmp_path / "log.jsonl"

    def worker(k):
        for _ in range(100):
            append_checked(p, None, lambda tail: str(len(tail.lines)))
    threads = [threading.Thread(target=worker, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = p.read_text().splitlines()
    assert lines == [str(i) for i in range(400)]   # a number minted under the lock is never minted twice


CHILD = r"""
import sys, time
from semantext.store import append_checked
path, tag = sys.argv[1], sys.argv[2]
longest = 0.0
for i in range(1000):
    t = time.monotonic()
    append_checked(path, None, lambda tail: f"{tag} {i} {len(tail.lines)}")   # a tight loop: the gate lets the other in
    longest = max(longest, time.monotonic() - t)
print(longest)
"""


def test_two_processes_appending_1000_lines_each_lose_and_interleave_nothing(tmp_path):
    p = tmp_path / "log.jsonl"
    root = str(Path(__file__).resolve().parents[1])
    procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(p), tag], cwd=root, stdout=subprocess.PIPE, text=True)
             for tag in ("a", "b")]
    outs = [proc.communicate(timeout=300)[0] for proc in procs]
    assert [proc.returncode for proc in procs] == [0, 0]
    lines = p.read_text().splitlines()
    assert len(lines) == 2000
    assert [int(x.split()[2]) for x in lines] == list(range(2000))   # each saw every line before its own
    for tag in ("a", "b"):
        assert [int(x.split()[1]) for x in lines if x.startswith(tag + " ")] == list(range(1000))
    # Neither tight loop starved the other: the longest single append in each stayed far inside the 10 s timeout.
    # The bound is loose on purpose (a slow runner's fsync can take a while); a starved writer waits whole seconds.
    assert all(float(out) < store.LOCK_TIMEOUT / 2 for out in outs), outs


def _someone_stands_at_the_gate(lock) -> bool:
    """True while another writer holds <lock>.gate, that is, waits in the turnstile for the lock itself."""
    fd = store._open_lock(lock.with_name(lock.name + ".gate"))
    try:
        try:
            store._lock_byte(fd, True)
        except OSError:
            return True
        store._lock_byte(fd, False)
        return False
    finally:
        os.close(fd)


def _holder_lets_go_and_asks_again(lock, gated: bool) -> list:
    """The holder lets the lock go and at once asks for it again, while a second writer is waiting for it. Returns
    who got it next, in order: with the gate the waiter goes first, every time."""
    order = []
    with file_lock(lock):
        waiter = threading.Thread(target=lambda: _take_and_note(lock, order, "waiter"))
        waiter.start()
        deadline = time.monotonic() + 10
        if gated:
            while not _someone_stands_at_the_gate(lock):
                assert time.monotonic() < deadline, "the waiter never reached the gate"
                time.sleep(0.001)
        else:
            time.sleep(0.05)   # the waiter is asking again every few milliseconds by now
    _take_and_note(lock, order, "holder")
    waiter.join(10)
    return order


def _take_and_note(lock, order, who):
    with file_lock(lock):
        order.append(who)


def test_a_waiting_writer_goes_before_the_holder_asks_again(tmp_path):
    lock = tmp_path / "log.jsonl.lock"
    for _ in range(5):
        assert _holder_lets_go_and_asks_again(lock, gated=True) == ["waiter", "holder"]


def test_without_the_gate_the_holder_asking_again_wins_the_bare_lock(tmp_path, monkeypatch):
    # The control: the same race with the turnstile off. The waiter asks every 5 ms and the holder asks again within
    # a fraction of one, so the holder wins nearly every round; five rounds in which the waiter always won would mean
    # the check above could not have failed.
    monkeypatch.setattr(store, "_GATED", False)
    lock = tmp_path / "log.jsonl.lock"
    rounds = [_holder_lets_go_and_asks_again(lock, gated=False) for _ in range(5)]
    assert ["holder", "waiter"] in rounds, rounds


def test_after_runs_under_the_lock_after_the_write(tmp_path):
    p = tmp_path / "log.jsonl"
    got = []
    append_checked(p, None, "z", after=lambda tail, text: got.append((p.read_bytes(), text)))
    assert got == [(b"z\n", "z")]
