"""The Gates reader against the confirmed findings of the round 2 review (c607024): each test names its finding, fails
on c607024, and has a must-pass arm beside its must-refuse arm. Where git is installed, the findings measured with real
git are measured again here (every repository is made under the test's temporary folder, and no network is used).
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from semantext.sources import gates
from semantext.sources.gates import config, discover, hooks, values, verdict, wording
from test_sources_gates import ALL_FOUR, kinds, link, load, one, repo, seats, touch, world

WHO = "A <a@x.y>\n"
HAS_GIT = shutil.which("git") is not None


def git(*args, cwd: Path, env: dict) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=env, text=True).stdout


@pytest.fixture
def genv(tmp_path):
    return {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid"}


# ---------------------------------------------------------------- H1: a stray folder that cannot be listed
def test_h1_a_folder_looked_in_only_for_strays_never_costs_the_verdict(tmp_path, monkeypatch):
    """Reproduced as the review did: MAX_NAMES 4, the hook folder holds 3 of the 4 hooks and top/hooks 6 files (with all
    four there, nothing is open, and no stray folder is looked at since round 3, F5)."""
    monkeypatch.setattr(gates, "MAX_NAMES", 4)
    w = one(tmp_path, config="\thooksPath = .githooks\n", hooks={".githooks": ALL_FOUR[:3], "hooks": list("abcdef")},
            identity=WHO)
    assert (w["status"], w["set"]) == ("read", ["UNCOVERED"])
    assert any("stranded hooks in" in u and "/hooks" in u and "more than 4 entries" in u for u in w["uncertain"])
    # must refuse: the folder git runs hooks from is still held to the limit, since the verdict rests on it
    over = one(tmp_path / "over", config="\thooksPath = .githooks\n", hooks={".githooks": [*ALL_FOUR, "x"]}, identity=WHO)
    assert (over["status"], over["set"]) == ("unknown", [])


def test_h1_a_stray_folder_that_cannot_be_listed_is_a_note(tmp_path, monkeypatch):
    real = os.scandir

    def scandir(path):
        if str(path).replace("\\", "/").endswith("/r/chain"):
            raise PermissionError("no listing")
        return real(path)

    monkeypatch.setattr(hooks.os, "scandir", scandir)
    w = one(tmp_path, config="\thooksPath = .githooks\n", hooks={".githooks": ALL_FOUR[1:], "chain": ["pre-commit"]},
            identity=WHO)
    assert w["set"] == ["UNCOVERED"] and any("stranded hooks in" in u and "could not be listed" in u
                                             for u in w["uncertain"])


# ---------------------------------------------------------------- D5: a commondir inside a .git folder
def test_d5_a_commondir_in_a_git_folder_is_honoured_for_the_settings(tmp_path):
    main = repo(tmp_path / "base", "m5", "\thooksPath = from-main\n")
    w5 = tmp_path / "base" / "w5"
    touch(w5 / ".git" / "HEAD", "ref: refs/heads/main\n")
    touch(w5 / ".git" / "commondir", "../../m5/.git\n")
    seed = discover.find_worktrees(w5, [])[0]
    assert config.same_place(seed.common, main / ".git") and config.same_place(seed.git_dir, w5 / ".git")
    out = load({"seats": str(seats(tmp_path, [{"name": "w5", "path": "w5", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["hooks_path"]["value"] == "from-main"
    # must pass: a .git folder with no commondir is its own common folder
    plain = repo(tmp_path / "base", "plain")
    assert discover.find_worktrees(plain, [])[0].common == plain / ".git"


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed here")
def test_d5_real_git_reads_the_settings_of_the_folder_commondir_names(tmp_path, genv):
    m5, w5 = tmp_path / "base" / "m5", tmp_path / "base" / "w5"
    m5.mkdir(parents=True)
    git("init", "-q", cwd=m5, env=genv)
    git("config", "core.hooksPath", "from-main", cwd=m5, env=genv)
    touch(w5 / ".git" / "HEAD", "ref: refs/heads/master\n")
    touch(w5 / ".git" / "commondir", "../../m5/.git\n")
    assert git("config", "--get", "core.hooksPath", cwd=w5, env=genv).strip() == "from-main"     # git's answer
    out = load({"seats": str(seats(tmp_path, [{"name": "w5", "path": "w5", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["hooks_path"]["value"] == "from-main"                    # the reader's


# ---------------------------------------------------------------- D2: a bare repository reached from its worktree
def bare_with_worktree(tmp_path: Path) -> tuple:
    bare = tmp_path / "base" / "repo.git"
    touch(bare / "config", "[core]\n\trepositoryformatversion = 0\n\tbare = true\n")
    touch(bare / "HEAD", "ref: refs/heads/main\n")
    (bare / "objects").mkdir(parents=True)
    (bare / "refs").mkdir(parents=True)
    wt = tmp_path / "base" / "wt"
    link(bare, "wt", wt, common=bare)
    return bare, wt


def test_d2_a_bare_repository_reached_from_its_worktree_has_its_bare_main(tmp_path):
    bare, wt = bare_with_worktree(tmp_path)
    problems: list = []
    from_wt = [(s.name, s.bare) for s in discover.find_worktrees(wt, problems)]
    from_bare = [(s.name, s.bare) for s in discover.find_worktrees(bare, [])]
    assert from_wt == from_bare == [(None, True), ("wt", False)]
    assert "no-main-worktree" not in [p["kind"] for p in problems]
    # must refuse: a common folder git does not take for a git folder (no HEAD of its own) is a problem, never a bare main
    (bare / "HEAD").unlink()
    problems = []
    seeds = discover.find_worktrees(wt, problems)
    assert [(s.name, s.bare) for s in seeds] == [("wt", False)] and "no-main-worktree" in [p["kind"] for p in problems]


@pytest.mark.skipif(not HAS_GIT, reason="git is not installed here")
def test_d2_real_git_lists_the_bare_repository_from_its_linked_worktree(tmp_path, genv):
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-q", cwd=src, env=genv)
    touch(src / "a.txt", "a\n")
    git("add", "a.txt", cwd=src, env=genv)
    git("commit", "-q", "-m", "c", cwd=src, env=genv)
    base = tmp_path / "base"
    base.mkdir()
    git("clone", "-q", "--bare", str(src), str(base / "repo.git"), cwd=tmp_path, env=genv)
    git("worktree", "add", "-q", str(base / "wt"), cwd=base / "repo.git", env=genv)
    assert "(bare)" in git("worktree", "list", cwd=base / "wt", env=genv).splitlines()[0]
    problems: list = []
    seeds = discover.find_worktrees(base / "wt", problems)
    assert [(s.name, s.bare) for s in seeds] == [(None, True), ("wt", False)] and problems == []


# ---------------------------------------------------------------- I2: a group that is not a word
@pytest.mark.parametrize("group", [["crew"], 0, "", 3, {"a": 1}])
def test_i2_a_group_that_is_not_a_word_is_a_problem(tmp_path, group):
    repo(tmp_path / "base" / "homes", "ann")
    path = seats(tmp_path, [{"name": "home", "path": "{home}", "kind": "repo"}],
                 {"Ann": {"home": "homes/ann", "groups": ["crew"]}, "Bob": {"home": "homes/bob"}})
    out = load({"seats": str(path), "group": group}, world(tmp_path))
    assert "shape" in kinds(out) and "'group'" in next(p["text"] for p in out["problems"] if p["kind"] == "shape")
    assert [r["seat"] for r in out["repos"]] == ["Ann", "Bob"] and out["group"] is None
    # must pass: a word, and no group at all, raise no such problem
    for cfg in ({"seats": str(path), "group": "crew"}, {"seats": str(path)}, {"seats": str(path), "group": None}):
        assert "shape" not in kinds(load(cfg, world(tmp_path))), cfg


# ---------------------------------------------------------------- the values
def test_v3_a_unit_is_folded_in_ascii_only():
    kelvin = "1\u212a"                                      # KELVIN SIGN, which str.lower() makes "k"
    assert values.git_number(kelvin) is None
    assert values.value_problem("core.bigfilethreshold", kelvin) is not None
    assert values.git_number("1k") == values.git_number("1K") == 1024        # must pass


def test_v2_a_backslash_or_a_drive_is_absolute_only_on_windows(monkeypatch):
    monkeypatch.setattr(gates, "NT_PATHS", False)
    assert [values.git_absolute(p) for p in ("\\x", "C:/x", "c:x", "/x", "x")] == [False, False, False, True, False]
    monkeypatch.setattr(gates, "NT_PATHS", True)
    assert [values.git_absolute(p) for p in ("\\x", "C:/x", "c:x", "/x", "x")] == [True, True, True, True, False]


def test_v4_unsigned_long_is_as_wide_as_this_build_makes_it():
    assert values.c_ulong_bits(4) == 32 and values.c_ulong_bits(8) == 64      # a 32-bit POSIX build is 32
    assert values.ULONG_BITS == 8 * struct.calcsize("L")


# ---------------------------------------------------------------- the settings files
def test_c7_one_included_file_met_by_two_spellings_is_reported_once(tmp_path):
    home = tmp_path / "user"
    touch(home / "inc.cfg", "[core]\n\tbare = maybe\n")
    touch(home / ".config" / "git" / "config", "[include]\n\tpath = ../../inc.cfg\n")
    touch(home / ".gitconfig", "[include]\n\tpath = inc.cfg\n")
    problems: list = []
    reader = config.SettingsReader(world(tmp_path), problems)
    for f in config.global_files(reader.world):
        reader.expand("global", f)
    assert [p["kind"] for p in problems] == ["bad-value"]
    # must refuse: a second file with the same line is a second problem
    touch(home / "other.cfg", "[core]\n\tbare = maybe\n")
    touch(home / ".gitconfig", "[include]\n\tpath = inc.cfg\n[include]\n\tpath = other.cfg\n")
    problems2: list = []
    reader2 = config.SettingsReader(world(tmp_path), problems2)
    for f in config.global_files(reader2.world):
        reader2.expand("global", f)
    assert [p["kind"] for p in problems2] == ["bad-value", "bad-value"]


def test_c8_a_bin_folder_on_the_path_leads_to_mingw64(tmp_path):
    install = tmp_path / "Git"
    for f in ("bin/git.exe", "cmd/git.exe", "mingw64/bin/git.exe"):
        touch(install / f)
    for sub in ("bin", "cmd", "mingw64/bin"):
        assert config.install_prefix({"PATH": str(install / sub)}) == install / "mingw64", sub
    plain = tmp_path / "usr"                                # must pass: a bin with no mingw64 beside it
    touch(plain / "bin" / "git")
    assert config.install_prefix({"PATH": str(plain / "bin")}) == plain


@pytest.mark.parametrize("scope, may", [("local", False), ("worktree", False), ("global", True), ("system", True)])
def test_c9_a_conditional_include_is_looked_through_at_its_own_scope(tmp_path, scope, may):
    """trace2.maxfiles with no value stops git only where git reads it: in the system's and your own settings."""
    touch(tmp_path / "inc.cfg", "[trace2]\n\tmaxfiles\n")
    touch(tmp_path / "top.cfg", '[includeIf "gitdir:/work/"]\n\tpath = inc.cfg\n')
    got = config.SettingsReader(world(tmp_path), []).expand(scope, tmp_path / "top.cfg")
    assert len(got.notes) == 1
    assert ("may set core.hooksPath" in got.notes[0]) is may and ("does not depend on it" in got.notes[0]) is not may


def test_c10_a_hooks_path_that_is_not_utf8_gives_no_answer(tmp_path):
    top = repo(tmp_path / "base", "r", hooks={"h\u00e9ks": ALL_FOUR}, identity=WHO)
    (top / ".git" / "config").write_bytes(b"[core]\n\trepositoryformatversion = 0\n\thooksPath = h\xe9ks\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    w = out["repos"][0]["worktrees"][0]
    assert w["status"] == "unknown" and any("not UTF-8" in u for u in w["uncertain"]) and "not-utf8" in kinds(out)
    # must pass: the same folder named in UTF-8
    (top / ".git" / "config").write_bytes("[core]\n\trepositoryformatversion = 0\n\thooksPath = h\u00e9ks\n".encode())
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["set"] == ["ARMED"]


# ---------------------------------------------------------------- discover
def test_d1_a_path_git_wrote_in_bytes_that_are_not_utf8(monkeypatch):
    monkeypatch.setattr(gates, "NT_PATHS", False)
    assert discover.path_text(b"/w/caf\xe9") == "/w/caf\udce9"            # POSIX: the same bytes, kept
    assert config.show(Path("/w/caf\udce9")).endswith("caf\ufffd")        # and written as text in the record
    monkeypatch.setattr(gates, "NT_PATHS", True)
    assert discover.path_text(b"/w/caf\xe9") == "/w/caf\ufffd"            # Windows: git writes UTF-8 there
    assert discover.path_text("/w/caf\u00e9".encode()) == "/w/caf\u00e9"  # must pass: UTF-8 either way


def test_d8_a_root_of_another_kind_needs_no_path(tmp_path):
    out = load({"seats": str(seats(tmp_path, [{"kind": "notes", "name": "n"}]))}, world(tmp_path))
    assert out["problems"] == [] and out["repos"] == []
    # must refuse: a root with no kind and no path, or a repo with no path, is still a bad root
    out = load({"seats": str(seats(tmp_path, [{"name": "x"}, {"kind": "repo", "name": "y"}]))}, world(tmp_path))
    assert kinds(out) == ["bad-root", "bad-root"]


# ---------------------------------------------------------------- verdict and wording
def test_vd1_no_acts_make_no_verdict():
    assert verdict.states(verdict.Facts(True, None, (), 0)) is None
    assert verdict.states(verdict.Facts(False, False, (), 0)) is None
    assert verdict.states(verdict.Facts(True, None, (True,), 1)) == (verdict.ARMED,)      # must pass


def test_w1_a_gone_with_no_words_is_an_error():
    with pytest.raises(ValueError, match="no words"):
        wording.missing_note("vanished", False)
    assert [wording.missing_note(g, False).split(";")[0] for g in (None, "folder")] == ["the worktree's folder is gone"] * 2


# ---------------------------------------------------------------- the package and its shim
def test_i1_the_shim_keeps_each_part_s_own_dunders():
    names = {p: (p.__name__, p.__file__) for p in (values, hooks)}
    gates.__name__ = gates.__name__                         # what importlib.reload does, through the package's setattr
    gates.__file__ = gates.__file__
    assert {p: (p.__name__, p.__file__) for p in (values, hooks)} == names
    assert values.__name__.endswith(".values") and hooks.__file__.endswith("hooks.py")


def test_i6_a_name_patched_in_with_create_is_given_back_to_the_part():
    real = hooks.datetime
    with mock.patch.object(gates, "datetime", "FAKE", create=True):
        assert hooks.datetime == "FAKE"                     # carried to the part that reads it
    assert hooks.datetime is real and not hasattr(gates, "datetime")
    with mock.patch.object(gates, "MAX_NAMES", 7):          # must pass: a name the package holds, as before
        assert hooks.MAX_NAMES == 7
    assert hooks.MAX_NAMES == gates.MAX_NAMES == 5_000


def test_i4_the_off_answer_has_the_keys_of_a_read_one(tmp_path):
    off = gates.load({})
    read = load({"seats": str(seats(tmp_path, []))}, world(tmp_path))
    assert set(read) == set(off) and off["off"] is True and off["outside_group"] == []   # round 3, F1: both ways
    assert {"read_note", "read_at", "system_config", "home", "group", "outside_group"} <= set(off)
