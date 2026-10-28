"""The Gates reader against the confirmed findings of the round 3 review (d205b4a), for the loader: each test
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


# ---------------------------------------------------------------- gates_init/F1: both answers have both keys
def test_init_f1_the_off_and_read_answers_have_the_same_keys(tmp_path):
    off = load({})
    path = seats(tmp_path, [])
    read = load({"seats": str(path)}, world(tmp_path))
    assert set(off) == set(read)
    assert off["seats"] is None and read["key"] == "seats"


# ---------------------------------------------------------------- gates_init/F2: one worktree fails alone
def test_init_f2_one_failing_worktree_costs_only_itself(tmp_path, monkeypatch):
    top = repo(tmp_path / "base", "r")
    for k in range(3):
        link(top, f"w{k}", tmp_path / "base" / f"w{k}")
    real = gates.Reader.record

    def record(self, seed):
        if seed.name == "w1":
            raise OSError("no reading this one")
        return real(self, seed)
    monkeypatch.setattr(gates.Reader, "record", record)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [w["name"] for w in out["repos"][0]["worktrees"]] == [None, "w0", "w2"]
    bad = [p for p in out["problems"] if p["kind"] == "unreadable"]
    assert len(bad) == 1 and bad[0]["source"].replace("\\", "/").endswith("/w1")


# ---------------------------------------------------------------- gates_init/F3: a group is one word
@pytest.mark.parametrize("group", ["   ", "a b", "\t"])
def test_init_f3_a_group_that_is_not_a_word_is_no_filter(tmp_path, group):
    out = load({"seats": str(seats(tmp_path, [])), "group": group}, world(tmp_path))
    assert out["group"] is None and [p["kind"] for p in out["problems"]] == ["shape"]


def test_init_f3_a_word_is_still_a_filter(tmp_path):
    out = load({"seats": str(seats(tmp_path, [])), "group": "crew"}, world(tmp_path))
    assert out["group"] == "crew" and out["problems"] == []


# ---------------------------------------------------------------- gates_init/F6: a reload keeps the restore records
def test_init_f6_a_reload_keeps_what_a_create_patch_must_give_back():
    assert "NAME_ONLY_IN_HOOKS" not in vars(gates)
    hooks.NAME_ONLY_IN_HOOKS = "own"
    try:
        with mock.patch.object(gates, "NAME_ONLY_IN_HOOKS", "patched", create=True):
            assert hooks.NAME_ONLY_IN_HOOKS == "patched"
            importlib.reload(gates)
        assert hooks.NAME_ONLY_IN_HOOKS == "own"
    finally:
        del hooks.NAME_ONLY_IN_HOOKS


