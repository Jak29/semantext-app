"""The Gates reader against the confirmed findings of the round 3 review (d205b4a), for the verdict and its words: each test
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


# ---------------------------------------------------------------- gates_verdict_wording/F1: no dead code
def test_verdict_f1_no_statement_follows_a_return_in_its_block():
    tree = ast.parse(inspect.getsource(verdict))
    dead = []
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list):
                for a, b in zip(block, block[1:]):
                    if isinstance(a, (ast.Return, ast.Raise)):
                        dead.append(b.lineno)
    assert dead == []


# ---------------------------------------------------------------- gates_verdict_wording/F2: the note says what was measured
def test_wording_f2_the_empty_hooks_path_note_says_only_what_was_measured():
    text = wording.EMPTY_HOOKS_PATH
    assert "from any hooks folder" not in text
    assert '"/pre-commit"' in text and "2.39.1" in text and "not read" in text
