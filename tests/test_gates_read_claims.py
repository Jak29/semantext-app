"""What the gates reader says against what it measured: a static read of git's files, never a run of a hook.

The all-clear names what was read and that nothing was tested; a hook file git would not run (on POSIX, one without
the executable bit) is not counted as a hook; and every record carries the time it was read. Each check has a
must-pass arm and a must-refuse arm. This machine is Windows: the POSIX arm is measured by setting the reader's
platform flag and its executable check by hand, not on a POSIX file system.
"""
from __future__ import annotations

import re

import pytest

from semantext.sources import gates, view
from test_sources_gates import ALL_FOUR, one, touch
from test_v2_view import World
from semantext.sources.gates import World as GitWorld

STAMP = "2026-10-23T12:34:56Z"


@pytest.fixture
def estate(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    return w


def mend_every_gate(w: World) -> None:
    touch(w.base / "birch" / ".identity", "Birch <birch@crew.test>\n")
    for n in ALL_FOUR:
        touch(w.base / "cedar" / "chain" / n, "#!/bin/sh\n")


def hooks_not_executable(real):
    """os.access as it would answer for a hook file without the executable bit; every other path as it is."""
    return lambda p, mode: False if str(p).replace('\\', '/').rsplit('/', 1)[-1] in ALL_FOUR else real(p, mode)


# ---------------------------------------------------------------- E21 G2: the all-clear says what was read
def test_the_all_clear_says_what_was_read_and_that_no_hook_was_tested(estate):
    text = view.answer("waiting")["holds"]["text"]
    assert "checks nothing" in text and "a hook for each act" not in text      # must-refuse: no all-clear yet
    mend_every_gate(estate)
    text = view.answer("waiting")["holds"]["text"]
    assert "every worktree is gated" not in text and "identity declared" not in text
    assert "every worktree has a hook for each act and an .identity that names someone (read; not tested)" in text


def test_the_armed_words_name_a_hook_file_and_an_identity_line_never_a_working_gate(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    assert w["set"] == ["ARMED"] and w["words"] == ["a hook for each act, identity named"]
    assert w["tested"] is False and all(v["tested"] is False for v in w["verdicts"])
    assert not any("gated" in x for x in w["words"])                             # must-refuse: the old over-claim


def test_the_reader_says_it_differs_from_the_checker_on_vacuous(tmp_path):
    doc = " ".join(gates.__doc__.split())
    assert "deliberately differs from the hook checker on VACUOUS" in doc
    assert "VACUOUS only when at least one act is gated" in doc
    assert "the same four the hook checker prints" not in doc
    # the behaviour the words describe: nothing gated and nobody named is open, never "checks nothing"
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ["README"]})
    assert w["set"] == ["UNCOVERED"]
    w = one(tmp_path / "b", config="\thooksPath = chain\n", hooks={"chain": ["pre-commit"]})
    assert w["set"] == ["UNCOVERED", "VACUOUS"]                                 # must-pass: one act gated, nobody named


# ---------------------------------------------------------------- E21 G1: a hook git would not run is not a hook
def test_on_posix_a_hook_without_the_executable_bit_is_not_counted(tmp_path, monkeypatch):
    real = gates.os.access
    monkeypatch.setattr(gates, "WINDOWS", False)
    monkeypatch.setattr(gates.os, "access", lambda p, mode: False if str(p).endswith("pre-push") else real(p, mode))
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    assert w["set"] == ["UNCOVERED"] and w["verdicts"][0]["open"] == ["git push"]
    assert w["not_executable"] == ["pre-push"] and w["executable"] == gates.EXEC_POSIX
    # must-refuse: with the bit on every file, the same repository has a hook for each act
    monkeypatch.setattr(gates.os, "access", lambda p, mode: True)
    w = one(tmp_path / "b", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    assert w["set"] == ["ARMED"] and w["not_executable"] == []


def test_on_windows_the_bit_is_not_read_and_the_record_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "WINDOWS", True)
    monkeypatch.setattr(gates.os, "access", hooks_not_executable(gates.os.access))   # it is not asked
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    assert w["set"] == ["ARMED"] and w["not_executable"] == []
    assert w["executable"] == "executable bit not checked on Windows"


def test_only_non_executable_files_in_gits_own_folder_leave_the_gates_off(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "WINDOWS", False)
    monkeypatch.setattr(gates.os, "access", hooks_not_executable(gates.os.access))
    w = one(tmp_path, hooks={".git/hooks": ALL_FOUR}, identity="A <a@x.y>\n")
    assert w["set"] == ["INERT"] and w["not_executable"] == sorted(ALL_FOUR)


# ---------------------------------------------------------------- E21 G4: the time of the read
def test_each_record_and_the_status_line_carry_the_time_of_the_read(estate, monkeypatch):
    got = gates.load(estate.cfg())
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", got["read_at"])
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", w["read_at"])
               for r in got["repos"] for w in r["worktrees"])
    monkeypatch.setattr(gates, "read_at", lambda: STAMP)
    got = gates.load(estate.cfg())
    assert got["read_at"] == STAMP and {w["read_at"] for r in got["repos"] for w in r["worktrees"]} == {STAMP}
    assert f"Gates (read at {STAMP}):" in view.answer("waiting")["holds"]["text"]
    p = view.answer("projects")
    assert p["read_at"] == STAMP
    assert {t["read_at"] for r in p["projects"] for t in r["gates"]["worktrees"]} == {STAMP}
    # must-refuse: another read is another time, never the first one kept
    monkeypatch.setattr(gates, "read_at", lambda: "2026-10-24T00:00:00Z")
    assert "Gates (read at 2026-10-24T00:00:00Z):" in view.answer("waiting")["holds"]["text"]
