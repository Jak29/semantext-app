"""The Gates reader against the confirmed findings of the round 3 review (d205b4a), for the hook folders: each test
names its finding, fails on d205b4a, and has a must-pass arm beside its must-refuse arm where one can be
written.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
from pathlib import Path
from unittest import mock

import pytest

from semantext.sources import gates
from semantext.sources.gates import config, discover, hooks, values, verdict, wording
from semantext.sources.gates.config import World
from test_sources_gates import ALL_FOUR, link, load, one, repo, seats, touch, world

WHO = "A <a@x.y>\n"


def chain(base: Path, n: int, last: str) -> str:
    """n files, each including the next, the last holding `last`: the include line that starts the chain."""
    for k in range(n):
        touch(base / f"c{k}.cfg", f"[include]\n\tpath = c{k + 1}.cfg\n" if k + 1 < n else last)
    return "[include]\n\tpath = c0.cfg\n"


# ---------------------------------------------------------------- gates_hooks/F1: unknown keeps no empty-path note
def test_hooks_f1_an_unknown_record_carries_no_empty_hooks_path_note(tmp_path):
    top = repo(tmp_path / "base", "r", "\thooksPath =\n")
    (top / ".identity").write_bytes(b"\xff\xfe not utf-8\n")
    w = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    rec = w["repos"][0]["worktrees"][0]
    assert rec["status"] == "unknown" and rec["note"] is None
    # must pass: a record that is read still says it
    assert wording.EMPTY_HOOKS_PATH in one(tmp_path / "ok", config="\thooksPath =\n")["note"]


# ---------------------------------------------------------------- gates_hooks/F3: a real U+FFFD is a name
def test_hooks_f3_a_replacement_character_written_in_the_file_is_a_folder_name(tmp_path):
    w = one(tmp_path, config="\thooksPath = hooks-\ufffd\n", hooks={"hooks-\ufffd": ALL_FOUR}, identity=WHO)
    assert w["status"] == "read" and w["set"] == ["ARMED"] and w["hooks_dir"].endswith("/hooks-\ufffd")
    # must refuse: a byte that is not UTF-8 still leaves the folder unknown
    top = repo(tmp_path / "bad" / "base", "r")
    with open(top / ".git" / "config", "ab") as f:
        f.write(b"\thooksPath = hooks-\xff\n")
    out = load({"seats": str(seats(tmp_path / "bad", [{"name": "r", "path": "r", "kind": "repo"}]))},
               world(tmp_path / "bad"))
    bad = out["repos"][0]["worktrees"][0]
    assert bad["status"] == "unknown" and any("not UTF-8" in u for u in bad["uncertain"])


# ---------------------------------------------------------------- gates_hooks/F4: a stray note says what it is
def test_hooks_f4_a_stray_folder_note_is_worded_as_a_note(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_NAMES", 4)
    w = one(tmp_path, config="\thooksPath = .githooks\n", hooks={".githooks": ["pre-commit"], "hooks": list("abcdef")},
            identity=WHO)
    notes = [u for u in w["uncertain"] if u.startswith("stranded hooks in")]
    assert len(notes) == 1 and "more than 4 entries" in notes[0]
    assert "cannot tell:" not in notes[0] and "the checker has no answer here" not in notes[0]


# ---------------------------------------------------------------- gates_hooks/F5: no stray note when nothing is open
def test_hooks_f5_a_fully_gated_record_lists_no_strays(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_NAMES", 4)
    w = one(tmp_path, config="\thooksPath = .githooks\n", hooks={".githooks": ALL_FOUR, "chain": list("abcdef")},
            identity=WHO)
    assert w["set"] == ["ARMED"] and not any("stranded" in u for u in w["uncertain"])
    # must refuse: with an act open, the stray folder is still looked at, and its note given
    w = one(tmp_path / "open", config="\thooksPath = .githooks\n", hooks={".githooks": ["pre-commit"],
                                                                          "chain": list("abcdef")}, identity=WHO)
    assert any("stranded hooks in" in u for u in w["uncertain"])


# ---------------------------------------------------------------- gates_hooks/F6: a quoted blank is kept
def test_hooks_f6_a_quoted_blank_hooks_path_is_a_folder_name(tmp_path):
    w = one(tmp_path, config='\thooksPath = " h"\n', hooks={" h": ALL_FOUR}, identity=WHO)
    assert w["hooks_path"]["value"] == " h" and w["hooks_dir"].endswith("/ h") and w["set"] == ["ARMED"]
    # a value of blanks only is a folder of that name, never the empty case (on Windows such a folder cannot be
    # listed, so there the record is unknown, and says why)
    blank = one(tmp_path / "blank", config='\thooksPath = " "\n', hooks={".git/hooks": ALL_FOUR})
    assert wording.EMPTY_HOOKS_PATH not in (blank["note"] or "")
    assert (blank["hooks_dir"] or "").endswith("/ ") or blank["status"] == "unknown"
    # must pass: an empty value is still the empty case
    assert one(tmp_path / "empty", config="\thooksPath =\n")["hooks_dir"] is None


