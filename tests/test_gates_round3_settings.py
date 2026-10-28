"""The Gates reader against the confirmed findings of the round 3 review (d205b4a), for the settings files, their values and the worktrees found: each test
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


# ---------------------------------------------------------------- gates_config/F2: a file is known by its path
@pytest.mark.skipif(os.name != "nt", reason="names holding a lone surrogate exist only on Windows file systems")
def test_config_f2_two_files_that_show_alike_are_not_a_cycle(tmp_path):
    a, b = tmp_path / "\ud800", tmp_path / "\ud801"          # distinct names, both shown as U+FFFD
    touch(a / "config", "[include]\n\tpath = ~/config\n")
    touch(b / "config", "[core]\n\thooksPath = h\n")
    assert config.show(a / "config") == config.show(b / "config")
    out = config.SettingsReader(World({}, b, ()), []).expand("global", a / "config")
    assert out.refused == [] and [s.key for s in out.settings][-1] == "core.hookspath"
    # must refuse: a file that really includes itself is still a cycle
    touch(tmp_path / "self" / "config", "[include]\n\tpath = config\n")
    loop = config.SettingsReader(World({}, tmp_path, ()), []).expand("global", tmp_path / "self" / "config")
    assert any("includes it back" in r for r in loop.refused)


# ---------------------------------------------------------------- gates_config/F3: a conditional include's depth
@pytest.mark.parametrize("plain, says", [(9, "may set core.hooksPath"), (2, "does not depend on it")])
def test_config_f3_a_conditional_include_is_counted_from_where_git_is(tmp_path, plain, says):
    user = tmp_path / "user"
    touch(user / "a.cfg", "[include]\n\tpath = b.cfg\n")
    touch(user / "b.cfg", "[include]\n\tpath = c.cfg\n")
    touch(user / "c.cfg", "[user]\n\tname = x\n")
    top = chain(user, plain, '[includeIf "gitdir:/work/"]\n\tpath = a.cfg\n')
    touch(user / ".gitconfig", top)
    doubts = [u for u in one(tmp_path, w=world(tmp_path))["uncertain"] if "is not evaluated" in u]
    assert len(doubts) == 1 and says in doubts[0]


# ---------------------------------------------------------------- gates_config/F4: an unknown includeIf kind
def test_config_f4_a_kind_git_never_applies_is_not_looked_through(tmp_path):
    user = tmp_path / "user"
    touch(user / "hooks.cfg", "[core]\n\thooksPath = other\n")
    touch(user / "extra.cfg", '[includeIf "nonsense:x"]\n\tpath = hooks.cfg\n')
    touch(user / ".gitconfig", '[includeIf "gitdir:/w/"]\n\tpath = extra.cfg\n')
    doubts = one(tmp_path, w=world(tmp_path))["uncertain"]
    assert len(doubts) == 1 and "does not depend on it" in doubts[0]
    # must refuse: a kind git applies is looked through
    touch(user / "extra.cfg", '[includeIf "onbranch:main"]\n\tpath = hooks.cfg\n')
    assert "may set" in one(tmp_path / "again", w=World({}, user, ()))["uncertain"][0]


# ---------------------------------------------------------------- gates_config/F6: one line past MAX_VISITS
def test_config_f6_includes_past_the_limit_are_one_line(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_VISITS", 3)
    touch(tmp_path / "user" / "x.cfg", "[user]\n\tname = x\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = x.cfg\n" * 8)
    w = one(tmp_path, w=world(tmp_path))
    assert w["status"] == "unknown" and sum("more than 3 includes" in u for u in w["uncertain"]) == 1


# ---------------------------------------------------------------- gates_config/F7: a 32-bit Git for Windows
def test_config_f7_the_mingw32_system_file_is_a_candidate(tmp_path):
    install = tmp_path / "git"
    touch(install / "cmd" / "git.exe")
    found = config.system_candidates({"PATH": str(install / "cmd")})
    assert install / "mingw32" / "etc" / "gitconfig" in found and install / "mingw64" / "etc" / "gitconfig" in found


# ---------------------------------------------------------------- gates_discover/F1: a commondir in a .git folder
def test_discover_f1_a_git_folder_with_a_commondir_ignores_the_common_core_bare(tmp_path):
    repo(tmp_path / "base", "m5", "\tbare = true\n")
    w5 = tmp_path / "base" / "w5"
    touch(w5 / ".git" / "HEAD", "ref: refs/heads/main\n")
    touch(w5 / ".git" / "commondir", "../../m5/.git\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "w5", "path": "w5", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["status"] == "read"
    # must refuse: in the repository's own folder core.bare = true is still bare
    out = load({"seats": str(seats(tmp_path, [{"name": "m5", "path": "m5", "kind": "repo"}], name="m.json"))},
               world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["status"] == "bare"


# ---------------------------------------------------------------- gates_discover/F2: the gitdir file is a path
def test_discover_f2_a_worktrees_gitdir_is_read_as_a_path(tmp_path, monkeypatch):
    top = repo(tmp_path / "base", "r")
    where = tmp_path / "base" / "caf\u00e9"
    admin = link(top, "w", where)
    (admin / "gitdir").write_bytes((tmp_path / "base").as_posix().encode("utf-8") + b"/caf\xe9/.git\n")
    monkeypatch.setattr(discover, "path_text", lambda raw: raw.decode("latin-1"))   # a file system in Latin-1
    seeds = discover.find_worktrees(top, problems := [])
    assert seeds[1].exists and not [p for p in problems if p["kind"] == "not-utf8"]


# ---------------------------------------------------------------- gates_discover/F4: commondir as git reads it
def test_discover_f4_a_commondir_is_trimmed_of_line_ends_only(tmp_path):
    repo(tmp_path / "base", "m")
    for name, text, ok in (("tab", "../../m/.git\t", False), ("empty", "", False), ("crlf", "../../m/.git\r\n", True)):
        w = tmp_path / "base" / name
        touch(w / ".git" / "HEAD", "ref: refs/heads/main\n")
        touch(w / ".git" / "commondir", text)
        assert (discover.git_dir_problem(w / ".git") is None) is ok, name
    # an absolute commondir is normalised as a relative one is
    touch(tmp_path / "base" / "abs" / ".git" / "commondir", (tmp_path / "base" / "m" / "x" / ".." / ".git").as_posix())
    assert discover.common_dir_of(tmp_path / "base" / "abs" / ".git") == tmp_path / "base" / "m" / ".git"


# ---------------------------------------------------------------- gates_discover/F5: a git folder not named .git
def test_discover_f5_a_git_folder_with_a_work_tree_is_no_bare_repository(tmp_path):
    proj = tmp_path / "base" / "proj"
    data = proj / "gitdata"
    touch(data / "config", f"[core]\n\trepositoryformatversion = 0\n\tbare = false\n\tworktree = {proj.as_posix()}\n")
    touch(data / "HEAD", "ref: refs/heads/main\n")
    (data / "objects").mkdir()
    (data / "refs").mkdir()
    wt = tmp_path / "base" / "wt"
    link(proj, "wt", wt, common=data)
    seeds = discover.find_worktrees(wt, [])
    main = [s for s in seeds if s.name is None]
    assert main and not main[0].bare and config.same_place(main[0].top, proj)
    # must refuse: with no work tree named, it is still the bare repository's own folder
    touch(data / "config", "[core]\n\trepositoryformatversion = 0\n")
    assert [s.bare for s in discover.find_worktrees(wt, []) if s.name is None] == [True]


# ---------------------------------------------------------------- gates_discover/F6: git's own blanks after ref:
def test_discover_f6_a_vertical_tab_after_ref_is_no_head():
    assert not discover.head_is_valid(b"ref:\vrefs/heads/main")
    assert not discover.head_is_valid(b"ref:\frefs/heads/main")
    assert discover.head_is_valid(b"ref: \t\r\nrefs/heads/main") and discover.head_is_valid(b"a" * 64)


# ---------------------------------------------------------------- gates_values/a/F3: core.abbrev and SHA-256
def test_values_a_f3_an_abbrev_over_40_is_refused_only_for_sha1(tmp_path):
    long = "\tabbrev = 48\n"
    top = repo(tmp_path / "v1" / "base", "r", long, hooks={".git/hooks": ALL_FOUR}, identity=WHO)
    cfg = top / ".git" / "config"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("repositoryformatversion = 0", "repositoryformatversion = 1")
                   + "[extensions]\n\tobjectformat = sha256\n", encoding="utf-8")
    out = load({"seats": str(seats(tmp_path / "v1", [{"name": "r", "path": "r", "kind": "repo"}]))},
               world(tmp_path / "v1"))
    assert out["repos"][0]["worktrees"][0]["status"] == "read"
    # must refuse: in a SHA-1 repository git stops on it (measured with Git for Windows 2.39.1)
    sha1 = one(tmp_path / "s1", config=long, hooks={".git/hooks": ALL_FOUR}, identity=WHO)
    assert sha1["status"] == "unknown" and any("core.abbrev" in u for u in sha1["uncertain"])
    assert values.value_problem("core.abbrev", "65") and not values.value_problem("core.abbrev", "40")


# ---------------------------------------------------------------- gates_values/a/F4: a byte the text cannot show
def test_values_a_f4_a_comment_char_read_with_a_replacement_is_not_called_a_refusal(tmp_path):
    top = repo(tmp_path / "base", "r", hooks={".git/hooks": ALL_FOUR}, identity=WHO)
    with open(top / ".git" / "config", "ab") as f:
        f.write(b"\tcommentChar = \xe9\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    w = out["repos"][0]["worktrees"][0]
    assert not any("git would refuse" in u for u in w["uncertain"])
    assert w["status"] == "unknown" and any(u.startswith("cannot tell:") and "commentchar" in u.lower()
                                            for u in w["uncertain"])
    # must refuse: two characters written as UTF-8 are still a refusal (git takes one byte)
    two = one(tmp_path / "two", config="\tcommentChar = ab\n")
    assert any("git would refuse" in u for u in two["uncertain"])


