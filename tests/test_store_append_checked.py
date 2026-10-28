"""store.append_checked: lock, check, append one whole line, sync (doors spec v0.6, rule 10). Each behaviour has a test
that must pass and, where it can go wrong, one that must be refused."""
import subprocess
import sys
import threading
from pathlib import Path

import pytest

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
import sys
from semantext.store import append_checked
path, tag = sys.argv[1], sys.argv[2]
for i in range(1000):
    append_checked(path, None, lambda tail: f"{tag} {i} {len(tail.lines)}")
"""


def test_two_processes_appending_1000_lines_each_lose_and_interleave_nothing(tmp_path):
    p = tmp_path / "log.jsonl"
    root = str(Path(__file__).resolve().parents[1])
    procs = [subprocess.Popen([sys.executable, "-c", CHILD, str(p), tag], cwd=root) for tag in ("a", "b")]
    assert all(proc.wait(timeout=300) == 0 for proc in procs)
    lines = p.read_text().splitlines()
    assert len(lines) == 2000
    assert [int(x.split()[2]) for x in lines] == list(range(2000))   # each saw every line before its own
    for tag in ("a", "b"):
        assert [int(x.split()[1]) for x in lines if x.startswith(tag + " ")] == list(range(1000))


def test_after_runs_under_the_lock_after_the_write(tmp_path):
    p = tmp_path / "log.jsonl"
    got = []
    append_checked(p, None, "z", after=lambda tail, text: got.append((p.read_bytes(), text)))
    assert got == [(b"z\n", "z")]
