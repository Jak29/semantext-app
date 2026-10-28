"""The Gates reader: each worktree's gate state, read from git's own files without running git.

Every repository here is made by hand in a temporary folder, laid out as git lays it out, so these tests need no git.
Each check has a must-pass arm and a must-refuse arm: a planted defect the reader has to report, or a wrong value it has
to tell apart from the right one.
"""
from __future__ import annotations

import io
import json
import os
import pathlib
import shutil
import subprocess
from pathlib import Path

import pytest

from semantext.sources import gates
from semantext.sources.gates import World, load, parse_config

ALL_FOUR = ("pre-commit", "commit-msg", "applypatch-msg", "pre-push")


# ---------------------------------------------------------------- building repositories without git
def touch(path: Path, text: str = "") -> Path:
    """A file, made executable: on POSIX git (and the reader) ignore a hook without the bit. On Windows the mode is
    not read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    path.chmod(0o755)
    return path


def repo(base: Path, name: str, config: str = "", hooks: dict | None = None, identity: str | None = None) -> Path:
    """A repository as git lays it out: .git/config, HEAD, the objects and refs folders, and folders of hook files named
    by `hooks`."""
    top = base / name
    touch(top / ".git" / "config", "[core]\n\trepositoryformatversion = 0\n" + config)
    touch(top / ".git" / "HEAD", "ref: refs/heads/main\n")
    (top / ".git" / "objects").mkdir(parents=True, exist_ok=True)
    (top / ".git" / "refs").mkdir(parents=True, exist_ok=True)
    for folder, names in (hooks or {}).items():
        (top / folder).mkdir(parents=True, exist_ok=True)
        for n in names:
            touch(top / folder / n, "#!/bin/sh\n")
    if identity is not None:
        touch(top / ".identity", identity)
    return top


def link(top: Path, wid: str, where: Path, config_worktree: str | None = None, make: bool = True,
         common: Path | None = None) -> Path:
    """A linked worktree of the repository at top, checked out at `where`; returns its folder under .git/worktrees (under
    `common` instead for a repository with no .git, such as a bare one)."""
    git = (common or top / ".git") / "worktrees" / wid
    touch(git / "gitdir", f"{where.as_posix()}/.git\n")
    touch(git / "commondir", "../..\n")
    touch(git / "HEAD", "ref: refs/heads/other\n")
    if make:
        touch(where / ".git", f"gitdir: {git.as_posix()}\n")
    if config_worktree is not None:
        touch(git / "config.worktree", config_worktree)
    return git


def world(tmp_path: Path, system: tuple = (), env: dict | None = None, notes: tuple = (), prefix: Path | None = None) -> World:
    home = tmp_path / "user"
    home.mkdir(parents=True, exist_ok=True)
    return World(dict(env or {}), home, tuple(system), (), tuple(notes), prefix)


def seats(tmp_path: Path, roots: list, people: dict | None = None, name: str = "roots.json") -> Path:
    data = {"base": (tmp_path / "base").as_posix(), "seats": people or {}, "roots": roots}
    return touch(tmp_path / name, json.dumps(data))


def whole(tmp_path: Path, w: World | None = None, **kw) -> dict:
    """The whole answer for a repository made with repo(**kw)."""
    repo(tmp_path / "base", "r", **kw)
    return load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, w or world(tmp_path))


def one(tmp_path: Path, w: World | None = None, **kw) -> dict:
    """The main worktree of a repository made with repo(**kw), as the reader reports it."""
    return whole(tmp_path, w, **kw)["repos"][0]["worktrees"][0]


def kinds(out: dict) -> list:
    return [p["kind"] for p in out["problems"]]


# ---------------------------------------------------------------- the four states
STATES = {
    "off: nothing set, nothing in git's own folder": ("", {}, None, ["INERT"], ["off"]),
    "off: only .sample files are not hooks": ("", {".git/hooks": ["pre-commit.sample", "pre-push.sample"]}, None,
                                             ["INERT"], ["off"]),
    "git's own folder gates when nothing is set": ("", {".git/hooks": ALL_FOUR}, "A <a@x.y>\n", ["ARMED"],
                                                  [gates.ARMED_WORDS]),
    "open, not off: git's own folder holds a hook that is no gate": ("", {".git/hooks": ["post-commit"]}, None,
                                                                    ["UNCOVERED"], ["open"]),
    "open: a hook folder with no hook in it": ("\thooksPath = chain\n", {"chain": ["README"]}, "A <a@x.y>\n",
                                              ["UNCOVERED"], ["open"]),
    "open and checks nothing": ("\thooksPath = chain\n", {"chain": ["pre-commit"]}, None, ["UNCOVERED", "VACUOUS"],
                                ["open", "checks nothing"]),
    "open with an identity": ("\thooksPath = chain\n", {"chain": ALL_FOUR[:3]}, "A <a@x.y>\n", ["UNCOVERED"], ["open"]),
    "checks nothing: all four, no identity": ("\thooksPath = chain\n", {"chain": ALL_FOUR}, None, ["VACUOUS"],
                                              ["checks nothing"]),
    "a hook for each act, identity named": ("\thooksPath = chain\n", {"chain": ALL_FOUR}, "A <a@x.y>\n", ["ARMED"],
                                            [gates.ARMED_WORDS]),
}


@pytest.mark.parametrize("config, hooks, identity, states, words", STATES.values(), ids=STATES.keys())
def test_the_four_states(tmp_path, config, hooks, identity, states, words):
    w = one(tmp_path, config=config, hooks=hooks, identity=identity)
    assert (w["status"], w["set"], w["words"]) == ("read", states, words)
    assert [v["verdict"] for v in w["verdicts"]] == states
    assert all(v["read"] == "static" for v in w["verdicts"])   # every verdict says it is a static read


def test_a_wrong_state_is_told_apart(tmp_path):
    """A gate with no identity is not armed, and a folder with no hooks is not off: the pairs the checker keeps apart."""
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    assert w["set"] == ["VACUOUS"] and "ARMED" not in w["set"]
    w = one(tmp_path / "b", config="\thooksPath = chain\n", hooks={"chain": ["x"]}, identity="A <a@x.y>\n")
    assert w["set"] == ["UNCOVERED"] and "INERT" not in w["set"]


def test_no_event_gated_is_said_and_is_not_checks_nothing(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ["README"]})
    open_ = w["verdicts"][0]
    assert open_["verdict"] == "UNCOVERED" and open_["none_gated"] is True
    assert open_["open"] == ["ordinary commit", "git merge --no-ff", "git am", "git push"]
    assert "VACUOUS" not in w["set"]            # nothing runs, so there is nothing to call vacuous


def test_the_event_table(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ["pre-commit", "pre-applypatch"]})
    rows = {r["event"]: r for r in w["events"]}
    assert rows["ordinary commit"]["state"] == "gated" and rows["ordinary commit"]["by"] == "pre-commit"
    assert rows["git push"]["state"] == "open" and rows["git push"]["needs"] == ["pre-push"]
    assert rows["git am"]["by"] == "pre-applypatch"
    assert rows["git am"]["note"] == "via pre-applypatch; applypatch-msg is the preferred point"
    assert w["reachable"] == ["pre-applypatch", "pre-commit"]
    best = one(tmp_path / "b", config="\thooksPath = chain\n", hooks={"chain": ["applypatch-msg", "pre-applypatch"]})
    assert {r["event"]: r for r in best["events"]}["git am"]["by"] == "applypatch-msg"
    assert {r["event"]: r for r in best["events"]}["git am"]["note"] is None


def test_either_hook_covers_git_am_and_neither_leaves_it_open(tmp_path):
    for name in ("applypatch-msg", "pre-applypatch"):
        w = one(tmp_path / name, config="\thooksPath = chain\n", hooks={"chain": [name]})
        assert {r["event"]: r for r in w["events"]}["git am"]["state"] == "gated"
    w = one(tmp_path / "neither", config="\thooksPath = chain\n", hooks={"chain": ["pre-commit"]})
    row = {r["event"]: r for r in w["events"]}["git am"]
    assert row["state"] == "open" and row["needs"] == ["applypatch-msg", "pre-applypatch"]


def test_a_folder_named_like_a_hook_is_not_a_hook(tmp_path):
    top = tmp_path / "base" / "r"
    repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ["commit-msg"]})
    (top / "chain" / "pre-commit").mkdir()                    # a folder, not a file
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    rows = {r["event"]: r for r in out["repos"][0]["worktrees"][0]["events"]}
    assert rows["ordinary commit"]["state"] == "open" and rows["git merge --no-ff"]["state"] == "gated"


# ---------------------------------------------------------------- .identity
@pytest.mark.parametrize("text, entries", [
    ("", 0), ("\n\n", 0), ("# only a comment\n", 0), ("   # indented comment\n", 0), ("  \t \n", 0),
    ("A <a@x.y>\n", 1), ("# who\nA <a@x.y>\n\nB <b@x.y>\n", 2), ("A <a@x.y>", 1),
    ("Ana " + chr(0xD3) + " <ana@x.y>\r\nBo <b@x.y>\r\n", 2),
])
def test_identity_counts_entries_and_not_comments(tmp_path, text, entries):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity=text)
    assert w["identity"]["entries"] == entries and w["identity"]["present"] is True
    assert w["set"] == (["ARMED"] if entries else ["VACUOUS"])


def test_identity_that_is_absent_or_a_folder_counts_nothing(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    assert w["identity"] == {"file": (tmp_path / "base" / "r" / ".identity").as_posix(), "present": False, "entries": 0}
    (tmp_path / "base" / "r" / ".identity").mkdir()
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["identity"]["present"] is False


def test_an_identity_that_is_not_text_gives_no_answer_and_says_why(tmp_path):
    repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    (tmp_path / "base" / "r" / ".identity").write_bytes(b"A <a@x.y>\n\xff\xfe\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    w = out["repos"][0]["worktrees"][0]
    assert w["status"] == "unknown" and w["set"] == [] and w["verdicts"] == []
    assert any("could not be read" in u for u in w["uncertain"])
    assert [p["kind"] for p in out["problems"]] == ["not-utf8"]
    # the same file as text is read: the planted defect is the bytes, nothing else
    (tmp_path / "base" / "r" / ".identity").write_bytes("A <a@x.y>\n".encode())
    ok = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert ok["repos"][0]["worktrees"][0]["set"] == ["ARMED"] and ok["problems"] == []


def test_a_byte_order_mark_in_identity_is_noted(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="\ufeff# who\n")
    assert w["identity"]["entries"] == 1          # the checker counts the first line when a mark hides its #
    assert any("byte-order mark" in u for u in w["uncertain"])
    plain = one(tmp_path / "p", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="# who\n")
    assert plain["identity"]["entries"] == 0 and plain["uncertain"] == []


# ---------------------------------------------------------------- stranded hooks
def stranded(w: dict) -> dict:
    return {s["name"]: s["where"] for v in w["verdicts"] for s in v.get("stranded", [])}


def test_a_hook_that_exists_elsewhere_is_stranded(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", identity="A <a@x.y>\n",
            hooks={"chain": ["pre-commit", "commit-msg", "applypatch-msg"], "hooks": ["pre-push"],
                   ".git/hooks": ["pre-push", "pre-commit"]})
    top = (tmp_path / "base" / "r").as_posix()
    assert stranded(w) == {"pre-push": [f"{top}/hooks", f"{top}/.git/hooks"]}   # pre-commit is gated: not stranded
    assert w["verdicts"][0]["stranded"][0]["words"] == "stranded"
    assert w["set"] == ["UNCOVERED"]


def test_a_hook_is_not_stranded_when_something_better_covers_the_act(tmp_path):
    """git am has two hooks. pre-applypatch in the folder git uses covers it, so applypatch-msg elsewhere is not lost."""
    w = one(tmp_path, config="\thooksPath = chain\n", identity="A <a@x.y>\n",
            hooks={"chain": ["pre-commit", "commit-msg", "pre-applypatch", "pre-push"],
                   ".git/hooks": ["applypatch-msg"]})
    assert w["set"] == ["ARMED"] and stranded(w) == {}
    gone = one(tmp_path / "b", config="\thooksPath = chain\n", identity="A <a@x.y>\n",
               hooks={"chain": ["pre-commit", "commit-msg", "pre-push"], ".git/hooks": ["applypatch-msg"]})
    assert stranded(gone) == {"applypatch-msg": [(tmp_path / "b" / "base" / "r" / ".git" / "hooks").as_posix()]}


def test_a_missing_hooks_path_strands_everything_that_exists_elsewhere(tmp_path):
    w = one(tmp_path, config="\thooksPath = nowhere\n", hooks={".git/hooks": ["pre-commit", "pre-push", "post-commit"]})
    assert w["set"] == ["UNCOVERED"] and set(stranded(w)) == {"pre-commit", "pre-push"}   # post-commit is no gate
    assert w["verdicts"][0]["none_gated"] is True and w["reachable"] == []


def test_a_sample_or_a_name_that_is_no_gate_is_not_stranded(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ["README"],
                                                              ".git/hooks": ["pre-push.sample", "update", "post-commit"]})
    assert stranded(w) == {}


def test_the_folder_git_runs_is_never_its_own_stranded_source(tmp_path):
    for place in ("hooks", ".git/hooks", "chain"):
        w = one(tmp_path / place.replace("/", "_"), config=f"\thooksPath = {place}\n", hooks={place: ["pre-commit"]})
        assert stranded(w) == {} and w["hooks_dir"].endswith("/" + place)       # the folder git runs is not "elsewhere"
        assert w["reachable"] == ["pre-commit"]
    # and the same hook is stranded the moment git is pointed at another folder
    off = one(tmp_path / "off", config="\thooksPath = other\n", hooks={"chain": ["pre-commit"], "other": ["README"]})
    assert set(stranded(off)) == {"pre-commit"} and off["reachable"] == []


# ---------------------------------------------------------------- git's settings: scopes, relative paths, the worktree file
def test_a_relative_hooks_path_is_the_worktrees_own(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    other = tmp_path / "wt"
    link(main, "feat", other)
    (other / "chain").mkdir()
    touch(other / "chain" / "pre-commit")        # this checkout carries only one hook
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    mine, theirs = out["repos"][0]["worktrees"]
    assert mine["hooks_dir"] == (main / "chain").as_posix() and mine["set"] == ["ARMED"]
    assert theirs["hooks_dir"] == (other / "chain").as_posix()          # its own checkout's, not the main one's
    assert theirs["name"] == "feat" and theirs["main"] is False
    assert theirs["set"] == ["UNCOVERED", "VACUOUS"]                      # one hook, and no .identity in this checkout


def test_an_absolute_hooks_path_with_escaped_backslashes(tmp_path):
    chain = tmp_path / "shared" / "chain"
    for n in ALL_FOUR:
        touch(chain / n)
    escaped = str(chain).replace("\\", "\\\\")        # how git writes a Windows path into a settings file
    w = one(tmp_path, config=f'\thooksPath = "{escaped}"\n', identity="A <a@x.y>\n")
    assert w["hooks_dir"] == chain.as_posix() and w["set"] == ["ARMED"]


def test_scopes_apply_lowest_first_and_the_last_one_wins(tmp_path):
    base = tmp_path / "base"
    system = touch(tmp_path / "sys" / "gitconfig", "[core]\n\thooksPath = from-system\n")
    home = tmp_path / "user"
    wld = world(tmp_path, system=(system,))
    xdg = home / ".config" / "git" / "config"
    glob = home / ".gitconfig"
    top = repo(base, "r")
    path = [{"name": "r", "path": "r", "kind": "repo"}]

    def where() -> tuple:
        out = load({"seats": str(seats(tmp_path, path))}, wld)
        hp = out["repos"][0]["worktrees"][0]["hooks_path"]
        return hp["scope"], hp["value"]

    assert where() == ("system", "from-system")
    touch(xdg, "[core]\n\thooksPath = from-xdg\n")
    assert where() == ("global", "from-xdg")
    touch(glob, "[core]\n\thooksPath = from-gitconfig\n")
    assert where() == ("global", "from-gitconfig")              # ~/.gitconfig is read after the XDG file
    touch(top / ".git" / "config", "[core]\n\thooksPath = from-local\n")
    assert where() == ("local", "from-local")
    touch(top / ".git" / "config", "[core]\n\trepositoryformatversion = 0\n\thooksPath = from-local\n"
                                   "[extensions]\n\tworktreeConfig = true\n")
    touch(top / ".git" / "config.worktree", "[core]\n\thooksPath = from-worktree\n")
    assert where() == ("worktree", "from-worktree")


def test_a_lower_scope_never_beats_a_higher_one(tmp_path):
    system = touch(tmp_path / "sys" / "gitconfig", "[core]\n\thooksPath = from-system\n")
    w = one(tmp_path, w=world(tmp_path, system=(system,)), config="")
    assert w["hooks_path"]["scope"] == "system"
    touch(tmp_path / "user" / ".gitconfig", "[core]\n\thooksPath = from-you\n")
    top = tmp_path / "base" / "r"
    touch(top / ".git" / "config", "[core]\n\trepositoryformatversion = 0\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path, system=(system,)))
    assert out["repos"][0]["worktrees"][0]["hooks_path"]["value"] == "from-you"   # the system one is the lowest


def test_the_worktree_file_is_read_only_when_the_repository_allows_it(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    other = tmp_path / "wt"
    link(main, "feat", other, config_worktree="[core]\n\thooksPath = elsewhere\n")
    path = [{"name": "r", "path": "r", "kind": "repo"}]

    def feat() -> dict:
        out = load({"seats": str(seats(tmp_path, path))}, world(tmp_path))
        return out["repos"][0]["worktrees"][1]

    head = "[core]\n\trepositoryformatversion = 0\n\thooksPath = chain\n"
    assert feat()["hooks_path"]["scope"] == "local"             # no extension: config.worktree is ignored
    for text in ("[extensions]\n\tworktreeConfig = false\n", "[extensions]\n\tworktreeConfig = off\n"):
        touch(main / ".git" / "config", head + text)
        assert feat()["hooks_path"]["scope"] == "local"
    for text in ("[extensions]\n\tworktreeConfig = true\n", "[extensions]\n\tworktreeconfig\n",
                 "[extensions]\n\tworktreeConfig = 1\n"):
        touch(main / ".git" / "config", head + text)
        got = feat()["hooks_path"]
        assert (got["scope"], got["value"]) == ("worktree", "elsewhere")


def test_the_worktree_file_belongs_to_its_own_worktree(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n[extensions]\n\tworktreeConfig = true\n",
                hooks={"chain": ALL_FOUR})
    link(main, "a", tmp_path / "wt-a", config_worktree="[core]\n\thooksPath = only-a\n")
    link(main, "b", tmp_path / "wt-b")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    got = {w["name"]: w["hooks_path"]["value"] for w in out["repos"][0]["worktrees"]}
    assert got == {None: "chain", "a": "only-a", "b": "chain"}


def test_an_empty_value_is_set_and_runs_no_hook_as_git_reads_it(tmp_path):
    """H3 (round 2): an empty core.hooksPath was read as "not set", so git's own hooks folder was judged reachable. Git
    2.39.1 runs no hook there then (measured below, with real git): every act is open, the hooks there are stranded."""
    touch(tmp_path / "user" / ".gitconfig", "[core]\n\thooksPath = chain\n")
    w = one(tmp_path, w=world(tmp_path), config="\thooksPath =\n", hooks={"chain": ALL_FOUR, ".git/hooks": ALL_FOUR},
            identity=WHO)
    assert w["hooks_path"]["set"] is True and w["hooks_path"]["value"] == "" and w["hooks_path"]["scope"] == "local"
    assert (w["status"], w["set"], w["hooks_dir"], w["reachable"]) == ("read", ["UNCOVERED"], None, [])
    assert [e["state"] for e in w["events"]] == ["open"] * 4 and gates.EMPTY_HOOKS_PATH in w["note"]
    stranded = {s["name"]: s["where"] for s in w["verdicts"][0]["stranded"]}
    assert set(stranded) == set(ALL_FOUR) and all(any(p.endswith(".git/hooks") for p in v) for v in stranded.values())
    blank = one(tmp_path / "b", config='\thooksPath = "  "\n', hooks={".git/hooks": ALL_FOUR}, identity=WHO)
    assert blank["hooks_path"]["set"] is True and blank["set"] == ["UNCOVERED"]
    # must pass: with no line at all, git's own folder is where git looks, and it gates
    unset = one(tmp_path / "c", hooks={".git/hooks": ALL_FOUR}, identity=WHO)
    assert unset["hooks_path"]["set"] is False and unset["set"] == ["ARMED"] and unset["reachable"] == sorted(ALL_FOUR)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
def test_real_git_runs_no_hook_from_its_own_folder_when_hooks_path_is_empty(tmp_path):
    """H3, measured: a pre-commit in .git/hooks that writes a marker runs with no core.hooksPath and does not run with an
    empty one; the reader says the same."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path),
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    marks = {}
    for label, empty in (("unset", False), ("empty", True)):
        top = tmp_path / "base" / label
        top.mkdir(parents=True)
        subprocess.run(["git", "-C", str(top), "init", "-q"], check=True, env=env, capture_output=True)
        if empty:
            subprocess.run(["git", "-C", str(top), "config", "core.hooksPath", ""], check=True, env=env, capture_output=True)
        mark = tmp_path / f"ran-{label}"
        touch(top / ".git" / "hooks" / "pre-commit", f"#!/bin/sh\necho ran > '{mark.as_posix()}'\n")
        touch(top / "a.txt", "a\n")
        touch(top / ".identity", WHO)
        subprocess.run(["git", "-C", str(top), "add", "a.txt"], check=True, env=env, capture_output=True)
        subprocess.run(["git", "-C", str(top), "commit", "-q", "-m", "c"], check=True, env=env, capture_output=True)
        marks[label] = mark.exists()
    assert marks == {"unset": True, "empty": False}
    out = load({"seats": str(seats(tmp_path, [{"name": n, "path": n, "kind": "repo"} for n in ("unset", "empty")]))},
               world(tmp_path))
    unset, empty = (r["worktrees"][0] for r in out["repos"])
    assert "pre-commit" in unset["reachable"] and unset["hooks_path"]["set"] is False
    assert empty["reachable"] == [] and empty["hooks_path"]["set"] is True and "UNCOVERED" in empty["set"]
    assert empty["verdicts"][0]["stranded"][0]["name"] == "pre-commit"


def test_a_hooks_path_with_no_value_is_refused_by_git_so_there_is_no_answer(tmp_path):
    """git stops at once on a core.hooksPath with no value, wherever it is written and whatever is written after it, so
    the hook checker gets no verdict at all. Calling that INERT would be a verdict git never gave."""
    out = whole(tmp_path, config="\thooksPath\n", hooks={"chain": ALL_FOUR})
    w = out["repos"][0]["worktrees"][0]
    assert (w["status"], w["set"], w["verdicts"], w["events"]) == ("unknown", [], [], [])
    assert any("git would refuse to run here" in u and "core.hooksPath has no value" in u for u in w["uncertain"])
    assert kinds(out) == ["bad-value"] and out["summary"]["unknown"] == 1
    later = one(tmp_path / "b", config="\thooksPath\n\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    assert later["status"] == "unknown"                          # a value written after it does not undo it
    touch(tmp_path / "c" / "user" / ".gitconfig", "[core]\n\thooksPath\n")
    shared = whole(tmp_path / "c", w=world(tmp_path / "c"), config="\thooksPath = chain\n")
    assert shared["repos"][0]["worktrees"][0]["status"] == "unknown"      # nor does a value in the repository's own file
    assert kinds(shared) == ["bad-value"] and shared["problems"][0]["source"].endswith(".gitconfig")
    fine = one(tmp_path / "d", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})   # the planted defect removed
    assert fine["status"] == "read" and fine["set"] == ["VACUOUS"]


def test_a_value_less_hooks_path_in_a_file_every_worktree_reads_is_one_problem(tmp_path):
    touch(tmp_path / "user" / ".gitconfig", "[core]\n\thooksPath\n")
    main = repo(tmp_path / "base", "r")
    link(main, "a", tmp_path / "wt-a")
    link(main, "b", tmp_path / "wt-b")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [w["status"] for w in out["repos"][0]["worktrees"]] == ["unknown"] * 3 and kinds(out) == ["bad-value"]


def test_a_tilde_path_is_read_as_the_checker_reads_it_and_noted(tmp_path):
    out = whole(tmp_path, config="\thooksPath = ~/hooks\n")
    w = out["repos"][0]["worktrees"][0]
    assert w["hooks_dir"] == (tmp_path / "base" / "r" / "~" / "hooks").as_posix()
    assert any("starts with ~" in u for u in w["uncertain"])
    assert out["summary"]["uncertain"] == 1 and out["repos"][0]["counts"]["uncertain"] == 1     # a doubt is counted
    clean = whole(tmp_path / "b", config="\thooksPath = chain\n")
    assert clean["repos"][0]["worktrees"][0]["uncertain"] == [] and clean["summary"]["uncertain"] == 0


# ---------------------------------------------------------------- how a settings file is read
PARSES = [
    ("[core]\n\thooksPath = chain\n", [("core.hookspath", "chain", 2)]),
    ("[Core]\nHooksPath=chain", [("core.hookspath", "chain", 2)]),
    ("[core] hooksPath = chain\n", [("core.hookspath", "chain", 1)]),
    ('[core]\n\thooksPath = "a  b" # note\n', [("core.hookspath", "a  b", 2)]),
    ("[core]\n\thooksPath = a  b ; note\n", [("core.hookspath", "a  b", 2)]),
    ("[core]\n\thooksPath = a#b\n", [("core.hookspath", "a", 2)]),
    ('[core]\n\thooksPath = "a#b"\n', [("core.hookspath", "a#b", 2)]),
    ("[core]\n\thooksPath = C:\\\\x\\\\y\n", [("core.hookspath", "C:\\x\\y", 2)]),
    ('[core]\n\thooksPath = say \\"hi\\"\n', [("core.hookspath", 'say "hi"', 2)]),
    ("[core]\n\thooksPath = ch\\\nain\n", [("core.hookspath", "chain", 2)]),
    ("[core]\n\ta = x \\\n  y\n\tb = 1\n", [("core.a", "x   y", 2), ("core.b", "1", 4)]),
    ("[core]\r\n\thooksPath = chain\r\n", [("core.hookspath", "chain", 2)]),
    ("\ufeff[core]\n\thooksPath = chain\n", [("core.hookspath", "chain", 2)]),
    ('[remote "Origin"]\n\turl = u\n', [("remote.Origin.url", "u", 2)]),
    ('[remote "a\\"b\\\\c"]\n\turl = u\n', [('remote.a"b\\c.url', "u", 2)]),
    ("[core]\n\tbare\n\tx = 1\n", [("core.bare", None, 2), ("core.x", "1", 3)]),
    ("# top comment\n; another\n\n[core]\n\t# inside\n\ta = 1\n", [("core.a", "1", 6)]),
    ("[core]\n\ta =\n\tb = \"\"\n", [("core.a", "", 2), ("core.b", "", 3)]),
    ("[core]\n\tx-y = 1\n", [("core.x-y", "1", 2)]),
    # measured against git 2.39: a name and a value end at a NUL, as C strings do
    ("[core]\n\thooksPath = ch\x00ain\n", [("core.hookspath", "ch", 2)]),
    ('[remote "a\x00b"]\n\turl = u\n', [("remote.a", "u", 2)]),
    # a header with no section name before its quoted part is one git reads
    ('[ "x"]\n\tk = 1\n', [(".x.k", "1", 2)]),
    # the end of the file is a line break, so a backslash that ends the file joins nothing and the value stands
    ("[core]\n\thooksPath = chain\\", [("core.hookspath", "chain", 2)]),
    ("[core]\n\thooksPath = chain\\\n", [("core.hookspath", "chain", 2)]),
    ("[core]\n\thooksPath = chain", [("core.hookspath", "chain", 2)]),
    ("[core]\n\tbare", [("core.bare", None, 2)]),
    ("[core]\n\ta = x\x0cy\n\tb = \x0bz\n", [("core.a", "x\x0cy", 2), ("core.b", "\x0bz", 3)]),   # not blanks to git
]


@pytest.mark.parametrize("text, expect", PARSES)
def test_a_settings_file_is_read_like_git_reads_it(text, expect):
    got, error = parse_config(text)
    assert error is None and got == expect


@pytest.mark.parametrize("text, line", [
    ("[core\n\ta = 1\n", 1), ("[]\n", 1), ('[core "x]\n', 1), ("[core\n\"x\"]\n", 1),
    ("[core]\n\ta\\q = 1\n", 2), ("[core]\n\ta = b\\q\n", 2), ("[core]\n\ta = \"open\n\tb = 1\n", 2),
    ("[core]\n\ta b\n", 2), ("=x\n", 1), ("[core]\n\t1a = x\n", 2),
    # git numbers a header by the line break or the end of the file it stopped at: measured, not guessed
    ("[core \"x\"\n", 2), ("[core \"x\"", 2), ("[core", 2), ("[core\n", 1), ("[", 2), ("[\n", 1),
    ("a = 1\n[core\n b = 2\n", 2), ("\n\n[core\n", 3), ("[core]\n[]\n", 2), ('[x "y"z]\n', 1),
    # a value that goes on over several lines is numbered by the line it went wrong on
    ("a = x \\\n  \\q\n", 2), ("a = x \\\n  \"open\n", 2), ("[core]\n\thooksPath = \"chain\\", 3),
    ("[core]\n\ta = 1\n\t\x00 = 2\n", 3),
])
def test_what_git_would_refuse_is_refused_with_its_line(text, line):
    got, error = parse_config(text)
    assert error is not None and error[0] == line


def test_a_refused_line_keeps_what_came_before_it():
    got, error = parse_config("[core]\n\ta = 1\n\tb b\n\tc = 2\n")
    assert got == [("core.a", "1", 2)] and error[0] == 3


def test_a_file_git_would_refuse_gives_no_answer(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n\tbroken line here\n", hooks={"chain": ALL_FOUR})
    assert (w["status"], w["set"], w["verdicts"]) == ("unknown", [], [])
    assert any("git would refuse to run here" in u and "bad config line" in u for u in w["uncertain"])
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [p["kind"] for p in out["problems"]] == ["bad-config"] and out["problems"][0]["line"] == 4
    fine = one(tmp_path / "b", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    assert fine["status"] == "read"


def test_a_refused_file_you_share_is_reported_once_and_marks_every_worktree(tmp_path):
    touch(tmp_path / "user" / ".gitconfig", "[user\nname = x\n")
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    link(main, "a", tmp_path / "wt-a")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [w["status"] for w in out["repos"][0]["worktrees"]] == ["unknown", "unknown"]
    assert len([p for p in out["problems"] if p["kind"] == "bad-config"]) == 1


def test_a_settings_file_over_the_limit_is_a_problem_and_gives_no_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_FILE", 1000)
    w = one(tmp_path, config="\thooksPath = chain\n" + "# padding\n" * 200)
    assert w["status"] == "unknown"
    # git would read a big file; the reader cannot, so it says it cannot tell and does not say git would refuse
    assert any(u.startswith("cannot tell:") and "could not be read" in u for u in w["uncertain"])
    assert not any("git would refuse" in u for u in w["uncertain"])
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [p["kind"] for p in out["problems"]] == ["too-big"]
    small = one(tmp_path / "s", config="\thooksPath = chain\n")
    assert small["status"] == "read"


# ---------------------------------------------------------------- includes
def test_include_path_is_followed_relative_to_the_file_that_names_it(tmp_path):
    touch(tmp_path / "user" / "extra" / "hooks.cfg", "[core]\n\thooksPath = from-include\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = extra/hooks.cfg\n")
    w = one(tmp_path, w=world(tmp_path))
    assert w["hooks_path"]["value"] == "from-include" and w["hooks_path"]["scope"] == "global"
    assert w["hooks_path"]["via"] == [(tmp_path / "user" / ".gitconfig").as_posix()]
    assert w["hooks_path"]["file"] == (tmp_path / "user" / "extra" / "hooks.cfg").as_posix()


def test_an_include_lands_where_it_is_written(tmp_path):
    inc = touch(tmp_path / "inc.cfg", "[core]\n\thooksPath = from-include\n")
    here = inc.as_posix()
    touch(tmp_path / "user" / ".gitconfig", f"[core]\n\thooksPath = before\n[include]\n\tpath = {here}\n")
    assert one(tmp_path, w=world(tmp_path))["hooks_path"]["value"] == "from-include"
    touch(tmp_path / "user" / ".gitconfig", f"[include]\n\tpath = {here}\n[core]\n\thooksPath = after\n")
    assert one(tmp_path / "b", w=world(tmp_path))["hooks_path"]["value"] == "after"


def test_a_relative_include_is_taken_from_the_folder_of_the_file_that_names_it(tmp_path):
    touch(tmp_path / "user" / "inc" / "sibling.cfg", "[core]\n\thooksPath = from-sibling\n")
    touch(tmp_path / "user" / "inc" / "outer.cfg", "[include]\n\tpath = sibling.cfg\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = inc/outer.cfg\n")
    touch(tmp_path / "user" / "sibling.cfg", "[core]\n\thooksPath = a-decoy-in-the-home-folder\n")
    w = one(tmp_path, w=world(tmp_path))
    assert w["hooks_path"]["value"] == "from-sibling" and len(w["hooks_path"]["via"]) == 2
    touch(tmp_path / "b" / "user" / ".gitconfig", "[include]\n\tpath = inc/outer.cfg\n")   # the sibling is nowhere
    touch(tmp_path / "b" / "user" / "inc" / "outer.cfg", "[include]\n\tpath = sibling.cfg\n")
    assert one(tmp_path / "b", w=world(tmp_path / "b"))["hooks_path"]["value"] is None       # skipped, not found elsewhere


def test_a_file_included_from_two_places_is_reported_once(tmp_path):
    shared = touch(tmp_path / "shared.cfg", "[core]\n\thooksPath\n")
    system = touch(tmp_path / "sys" / "gitconfig", f"[include]\n\tpath = {shared.as_posix()}\n")
    touch(tmp_path / "user" / ".gitconfig", f"[include]\n\tpath = {shared.as_posix()}\n")
    out = whole(tmp_path, w=world(tmp_path, system=(system,)))
    w = out["repos"][0]["worktrees"][0]
    assert kinds(out) == ["bad-value"] and len([u for u in w["uncertain"] if "no value" in u]) == 1


def test_includes_inside_includes_and_a_tilde_path(tmp_path):
    touch(tmp_path / "user" / "deep.cfg", "[core]\n\thooksPath = deep\n")
    touch(tmp_path / "user" / "mid.cfg", "[include]\n\tpath = ~/deep.cfg\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = mid.cfg\n")
    w = one(tmp_path, w=world(tmp_path))
    assert w["hooks_path"]["value"] == "deep" and len(w["hooks_path"]["via"]) == 2


def test_an_include_that_is_not_there_is_skipped_as_git_skips_it(tmp_path):
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = gone.cfg\n[core]\n\thooksPath = chain\n")
    w = one(tmp_path, w=world(tmp_path), hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    assert w["status"] == "read" and w["set"] == ["ARMED"]


def test_an_include_that_is_a_folder_or_has_no_path_stops_git_and_gives_no_answer(tmp_path):
    """Measured with git 2.39: an include of a folder stops git, and so does an empty path (the including file's own
    folder). An include of something that is not there does not."""
    for k, text in enumerate(("[include]\n\tpath = inc-dir\n", "[include]\n\tpath =\n")):
        (tmp_path / str(k) / "user" / "inc-dir").mkdir(parents=True)
        touch(tmp_path / str(k) / "user" / ".gitconfig", text)
        out = whole(tmp_path / str(k), w=world(tmp_path / str(k)))
        w = out["repos"][0]["worktrees"][0]
        assert w["status"] == "unknown" and any("is not a file" in u for u in w["uncertain"]), text
        assert kinds(out) == ["bad-include"], text
    touch(tmp_path / "z" / "user" / ".gitconfig", "[include]\n\tpath = inc-gone\n")
    assert one(tmp_path / "z", w=world(tmp_path / "z"))["status"] == "read"          # nothing there: git skips it


def test_include_loops_and_a_value_less_include_give_no_answer(tmp_path):
    touch(tmp_path / "user" / "a.cfg", "[include]\n\tpath = b.cfg\n")
    touch(tmp_path / "user" / "b.cfg", "[include]\n\tpath = a.cfg\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = a.cfg\n")
    loop = one(tmp_path, w=world(tmp_path))
    assert loop["status"] == "unknown" and any("includes it back" in u for u in loop["uncertain"])
    touch(tmp_path / "b" / "user" / ".gitconfig", "[include]\n\tpath\n")
    bare = one(tmp_path / "b", w=world(tmp_path / "b"))
    assert bare["status"] == "unknown" and any("no value" in u for u in bare["uncertain"])


def nested(user: Path, depth: int) -> None:
    """~/.gitconfig includes c1, which includes c2, and so on down to c<depth>, which sets core.hooksPath."""
    for k in range(1, depth):
        touch(user / f"c{k}.cfg", f"[include]\n\tpath = c{k + 1}.cfg\n")
    touch(user / f"c{depth}.cfg", "[core]\n\thooksPath = deepest\n")
    touch(user / ".gitconfig", "[include]\n\tpath = c1.cfg\n")


def test_includes_nest_as_deep_as_git_allows_and_no_deeper(tmp_path):
    """Measured with git 2.39: a file included ten deep is read, one included eleven deep stops git."""
    nested(tmp_path / "ok" / "user", 10)
    ok = one(tmp_path / "ok", w=world(tmp_path / "ok"))
    assert ok["status"] == "read" and ok["hooks_path"]["value"] == "deepest" and len(ok["hooks_path"]["via"]) == 10
    nested(tmp_path / "deep" / "user", 11)
    out = whole(tmp_path / "deep", w=world(tmp_path / "deep"))
    deep = out["repos"][0]["worktrees"][0]
    assert deep["status"] == "unknown" and any("deeper than git allows" in u for u in deep["uncertain"])
    assert kinds(out) == ["bad-include"]


def test_more_includes_than_the_reader_follows_are_no_answer_and_not_a_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_VISITS", 3)
    for name, times in (("few", 3), ("many", 5)):
        touch(tmp_path / name / "user" / "x.cfg", "[user]\n\tname = x\n")
        touch(tmp_path / name / "user" / ".gitconfig", "[include]\n\tpath = x.cfg\n" * times)
    assert one(tmp_path / "few", w=world(tmp_path / "few"))["status"] == "read"          # at the limit: followed
    many = one(tmp_path / "many", w=world(tmp_path / "many"))
    assert many["status"] == "unknown"
    assert any(u.startswith("cannot tell:") and "more than 3 includes" in u for u in many["uncertain"])
    assert not any("git would refuse" in u for u in many["uncertain"])


def test_a_conditional_include_is_always_a_doubt_and_says_whether_it_could_matter(tmp_path):
    def run(sub: str, target: str | None, name: str) -> list:
        root = tmp_path / name
        if target is not None:
            touch(root / "user" / "cond.cfg", target)
        touch(root / "user" / ".gitconfig", f'[includeIf "{sub}"]\n\tpath = cond.cfg\n')
        return one(root, w=world(root), config="\thooksPath = chain\n")["uncertain"]

    sets = run("gitdir:/work/", "[core]\n\thooksPath = other\n", "sets")
    assert len(sets) == 1 and 'includeIf "gitdir:/work/" is not evaluated' in sets[0] and "may set core.hooksPath" in sets[0]
    quiet = run("gitdir:/work/", "[user]\n\tname = x\n", "quiet")       # recorded all the same: the answer does not hinge on it
    assert len(quiet) == 1 and "is not evaluated" in quiet[0] and "does not depend on it" in quiet[0] and "may set" not in quiet[0]
    assert run("gitdir:/work/", None, "absent") == []                                       # git skips a missing file
    assert run("somenewkind:/work/", "[core]\n\thooksPath = other\n", "unknown") == []      # git never applies it
    for sub in ("onbranch:main", "hasconfig:remote.*.url:*", "gitdir/i:/Work/"):
        assert len(run(sub, "[core]\n\thooksPath = other\n", "kind-" + sub[:6])) == 1, sub
    assert "may set" in run("gitdir:/work/", "[user\n", "damaged")[0]                       # a file git might refuse
    (tmp_path / "folder" / "user" / "cond.cfg").mkdir(parents=True)                          # a folder where a file should be
    touch(tmp_path / "folder" / "user" / ".gitconfig", '[includeIf "gitdir:/work/"]\n\tpath = cond.cfg\n')
    assert "may set" in one(tmp_path / "folder", w=world(tmp_path / "folder"))["uncertain"][0]    # git stops on it


def test_a_conditional_include_looks_through_the_includes_inside_it(tmp_path):
    touch(tmp_path / "user" / "inner.cfg", "[core]\n\thooksPath = other\n")
    touch(tmp_path / "user" / "cond.cfg", "[include]\n\tpath = inner.cfg\n")
    touch(tmp_path / "user" / ".gitconfig", '[includeIf "gitdir:/work/"]\n\tpath = cond.cfg\n')
    only = one(tmp_path, w=world(tmp_path))["uncertain"]
    assert len(only) == 1 and "may set core.hooksPath" in only[0]


def test_a_branching_conditional_include_is_looked_through_once_per_file(tmp_path, monkeypatch):
    """Ten includes of the next file, six files deep: a hundred thousand paths if each were followed afresh."""
    for k in range(5):
        touch(tmp_path / "user" / f"f{k}.cfg", f"[include]\n\tpath = f{k + 1}.cfg\n" * 10)
    touch(tmp_path / "user" / "f5.cfg", "[user]\n\tname = x\n")
    touch(tmp_path / "user" / ".gitconfig", '[includeIf "gitdir:/work/"]\n\tpath = f0.cfg\n')
    looked, real = [], gates.Reader._could_set_hooks

    def counting(self, path, scope, seen):
        looked.append(path)
        return real(self, path, scope, seen)

    monkeypatch.setattr(gates.Reader, "_could_set_hooks", counting)
    w = one(tmp_path, w=world(tmp_path))
    assert len(looked) == 6 and len(w["uncertain"]) == 1 and "does not depend on it" in w["uncertain"][0]


# ---------------------------------------------------------------- where git looks on this machine
def test_the_machines_own_settings_files_are_found_and_named(tmp_path):
    install = tmp_path / "git"
    touch(install / "cmd" / "git.exe")
    touch(install / "etc" / "gitconfig", "[core]\n\thooksPath = from-system\n")
    env = {"PATH": str(install / "cmd"), "USERPROFILE": str(tmp_path / "user")}
    m = gates.this_machine(env)
    assert m.system == (install / "etc" / "gitconfig",) and m.notes == ()
    assert m.home == tmp_path / "user"
    w = one(tmp_path, w=m)
    assert w["hooks_path"]["scope"] == "system"
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, m)
    assert out["system_config"]["file"] == (install / "etc" / "gitconfig").as_posix()


def test_a_missing_system_file_is_said(tmp_path, monkeypatch):
    """The packaged places (/etc/gitconfig and the like) are moved into tmp_path: a runner that has its own system file
    must not decide this test."""
    monkeypatch.setattr(gates, "SYSTEM_FILES", (str(tmp_path / "etc" / "gitconfig"),))
    m = gates.this_machine({"PATH": str(tmp_path / "nowhere"), "USERPROFILE": str(tmp_path)})
    assert m.system == () and any("no system settings file was found" in n for n in m.notes)
    assert any("no system settings file" in u for u in one(tmp_path, w=m)["uncertain"])
    # must pass: a file at a packaged place is the one read
    touch(tmp_path / "etc" / "gitconfig", "")
    assert gates.this_machine({"PATH": str(tmp_path / "nowhere")}).system == (tmp_path / "etc" / "gitconfig",)


def test_mingw_layouts_are_found(tmp_path):
    install = tmp_path / "git"
    touch(install / "mingw64" / "bin" / "git.exe")
    touch(install / "etc" / "gitconfig", "")
    assert gates.this_machine({"PATH": str(install / "mingw64" / "bin")}).system == (install / "etc" / "gitconfig",)


def test_the_environment_can_move_the_files_and_the_reader_follows(tmp_path):
    sysfile = touch(tmp_path / "s.cfg", "[core]\n\thooksPath = from-system\n")
    mine = touch(tmp_path / "g.cfg", "[core]\n\thooksPath = from-global\n")
    touch(tmp_path / "user" / ".gitconfig", "[core]\n\thooksPath = from-home\n")
    env = {"HOME": str(tmp_path / "user"), "PATH": ""}
    assert one(tmp_path / "a", w=gates.this_machine({**env, "GIT_CONFIG_SYSTEM": str(sysfile)}))["hooks_path"]["value"] \
        == "from-home"
    only_system = {"HOME": str(tmp_path / "empty"), "PATH": "", "GIT_CONFIG_SYSTEM": str(sysfile)}
    assert one(tmp_path / "b", w=gates.this_machine(only_system))["hooks_path"]["value"] == "from-system"
    moved = gates.this_machine({**env, "GIT_CONFIG_GLOBAL": str(mine)})
    assert one(tmp_path / "c", w=moved)["hooks_path"]["value"] == "from-global"       # ~/.gitconfig is no longer read
    none = gates.this_machine({**env, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": str(sysfile)})
    assert none.system == () and none.notes == ()
    kept = gates.this_machine({**env, "GIT_CONFIG_NOSYSTEM": "0", "GIT_CONFIG_SYSTEM": str(sysfile)})
    assert kept.system == (sysfile,)


def test_a_variable_that_moves_where_git_looks_is_named_not_evaluated(tmp_path):
    m = gates.this_machine({"PATH": "", "GIT_CONFIG_SYSTEM": str(tmp_path / "none"), "GIT_CONFIG_COUNT": "1"})
    assert len(m.notes) == 1 and "GIT_CONFIG_COUNT is set" in m.notes[0]
    assert any("GIT_CONFIG_COUNT" in u for u in one(tmp_path, w=m)["uncertain"])
    assert gates.this_machine({"PATH": "", "GIT_CONFIG_SYSTEM": str(tmp_path / "none"), "GIT_EDITOR": "true"}).notes == ()


def test_the_home_git_uses(tmp_path):
    (tmp_path / "hp").mkdir()
    assert gates.user_home({"HOME": "/h", "USERPROFILE": "/u", "HOMEDRIVE": "Q:", "HOMEPATH": "\\x"}) == Path("/h")
    assert gates.user_home({"USERPROFILE": "/u"}) == Path("/u")
    assert gates.user_home({"HOMEDRIVE": "Q:", "HOMEPATH": "\\nowhere", "USERPROFILE": "/u"}) == Path("/u")  # not there
    drive, tail = os.path.splitdrive(str(tmp_path / "hp"))
    if drive:                                    # Windows: the home drive and path win over the profile when they exist
        assert gates.user_home({"HOMEDRIVE": drive, "HOMEPATH": tail, "USERPROFILE": "/u"}) == Path(drive + tail)


def test_yes_and_no_as_git_reads_them():
    for text in (None, "true", "Yes", "ON", "1", "2", "1k", "+3"):
        assert gates.parse_bool(text) is True, text
    for text in ("", "false", "No", "OFF", "0", "0g", "-0"):
        assert gates.parse_bool(text) is False, text
    for text in ("maybe", "1.5", "one", "tru"):
        assert gates.parse_bool(text) is None, text


def test_which_settings_are_includes():
    assert gates.include_condition("include.path") == ""
    assert gates.include_condition("includeif.gitdir:/a/.path") == "gitdir:/a/"
    assert gates.include_condition("includeif.hasconfig:remote.*.url:*.example/.path") == "hasconfig:remote.*.url:*.example/"
    for key in ("include.pathx", "includeif.path", "includeif..path", "core.path", "includeif.x.other", "core.hookspath"):
        assert gates.include_condition(key) is None, key


def test_what_git_counts_as_an_absolute_path():
    windows_only = ("\\a", "C:/a", "c:\\a", "C:a")   # absolute on Windows; ordinary names elsewhere (V2)
    for text in ("/a",) + (windows_only if gates.NT_PATHS else ()):
        assert gates.git_absolute(text), text
    for text in ("a", "./a", "../a", "~a", "a/C:/b", "") + (() if gates.NT_PATHS else windows_only):
        assert not gates.git_absolute(text), text


# ---------------------------------------------------------------- worktrees
def test_every_worktree_is_found(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    for wid in ("zeta", "alpha", "mid"):
        link(main, wid, tmp_path / "wts" / wid)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    ws = out["repos"][0]["worktrees"]
    assert [w["name"] for w in ws] == [None, "alpha", "mid", "zeta"]            # the main one first, then by name
    assert [w["path"] for w in ws] == [main.as_posix()] + [(tmp_path / "wts" / n).as_posix() for n in ("alpha", "mid", "zeta")]
    assert all(w["exists"] and w["status"] == "read" for w in ws)
    assert out["repos"][0]["counts"]["worktrees"] == 4 and out["summary"]["worktrees"] == 4
    assert ws[1]["git_dir"] == (main / ".git" / "worktrees" / "alpha").as_posix() and ws[1]["common_dir"] == (main / ".git").as_posix()
    assert ws[0]["git_dir"] == ws[0]["common_dir"]


def test_a_worktree_whose_folder_was_removed_is_listed_as_missing(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    link(main, "gone", tmp_path / "wts" / "gone", make=False)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    gone = out["repos"][0]["worktrees"][1]
    assert (gone["name"], gone["exists"], gone["status"], gone["set"]) == ("gone", False, "missing", [])
    assert "prunable" in gone["note"] and gone["uncertain"] == []     # missing is a state, not a doubt about a reading
    assert out["repos"][0]["counts"]["missing"] == 1 and out["repos"][0]["worktrees"][0]["status"] == "read"
    assert out["repos"][0]["worktrees"][0]["note"] is None


def test_a_locked_worktree_is_marked(tmp_path):
    main = repo(tmp_path / "base", "r")
    git = link(main, "held", tmp_path / "wts" / "held")
    touch(git / "locked", "on a drive that is not always there\n")
    link(main, "free", tmp_path / "wts" / "free")
    ws = {w["name"]: w for w in load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))},
                                     world(tmp_path))["repos"][0]["worktrees"]}
    assert ws["held"]["locked"] is True and ws["free"]["locked"] is False


def test_a_locked_worktree_whose_folder_is_gone_is_not_called_prunable(tmp_path):
    """Measured with git 2.39: a worktree whose folder is gone is listed prunable, unless it is locked."""
    main = repo(tmp_path / "base", "r")
    git = link(main, "held", tmp_path / "wts" / "held", make=False)
    touch(git / "locked", "on a drive that is not always there\n")
    link(main, "free", tmp_path / "wts" / "free", make=False)
    ws = {w["name"]: w for w in load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))},
                                     world(tmp_path))["repos"][0]["worktrees"]}
    assert (ws["held"]["status"], ws["held"]["locked"]) == ("missing", True)
    assert "locked" in ws["held"]["note"] and "does not call it prunable" in ws["held"]["note"]
    assert (ws["free"]["status"], ws["free"]["locked"]) == ("missing", False)
    assert "lists it as prunable" in ws["free"]["note"] and "locked" not in ws["free"]["note"]


def test_more_linked_worktrees_than_the_limit_are_said(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_WORKTREES", 2)
    main = repo(tmp_path / "base", "r")
    for wid in "abcd":
        link(main, wid, tmp_path / "wts" / wid)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [w["name"] for w in out["repos"][0]["worktrees"]] == [None, "a", "b"] and kinds(out) == ["too-many"]
    monkeypatch.setattr(gates, "MAX_WORKTREES", 4)
    assert len(load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))},
                    world(tmp_path))["repos"][0]["worktrees"]) == 5


def test_an_empty_or_missing_gitdir_file_is_skipped_and_reported(tmp_path):
    """Measured with git 2.39: a worktree folder with no gitdir file, or an empty one, is not listed at all."""
    main = repo(tmp_path / "base", "r")
    touch(main / ".git" / "worktrees" / "empty" / "gitdir", "")
    (main / ".git" / "worktrees" / "bare").mkdir(parents=True)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [w["name"] for w in out["repos"][0]["worktrees"]] == [None]
    assert [p["kind"] for p in out["problems"]] == ["worktree-skipped", "worktree-skipped"]


def test_a_gitdir_file_may_hold_a_relative_path(tmp_path):
    """git 2.48 and later can write a worktree's gitdir as a path relative to the folder that holds the file
    (worktree.useRelativePaths). The git this was measured with, 2.39, writes only absolute ones and prints a relative
    one as it stands, so this follows the newer reading and is not measured."""
    main = repo(tmp_path / "base", "r")
    git = main / ".git" / "worktrees" / "rel"
    touch(git / "gitdir", "../../../../../wts/rel/.git\n")   # relative to the folder that holds it
    touch(tmp_path / "wts" / "rel" / ".git", "gitdir: x\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    rel = out["repos"][0]["worktrees"][1]
    assert rel["path"] == (tmp_path / "wts" / "rel").as_posix() and rel["exists"] is True


def test_a_root_that_is_itself_a_linked_worktree_lists_the_whole_repository(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    link(main, "one", tmp_path / "base" / "wt-one")
    link(main, "two", tmp_path / "base" / "wt-two")
    out = load({"seats": str(seats(tmp_path, [{"name": "w", "path": "wt-one", "kind": "repo"}]))}, world(tmp_path))
    assert [w["name"] for w in out["repos"][0]["worktrees"]] == [None, "one", "two"]
    assert out["problems"] == []


GIT = "<git>"      # where a test's .git file text names the git folder


def separate(tmp_path: Path, name: str = "r", config: str = "[core]\n\thooksPath = chain\n", text: str | None = None) -> Path:
    """A repository whose git folder lives apart from its work tree: the work tree holds a .git file naming the folder.
    `text` is that file's text, with <git> standing for the folder (its default is what git writes)."""
    elsewhere = tmp_path / "gitdirs" / f"{name}.git"
    touch(elsewhere / "config", "[core]\n\trepositoryformatversion = 0\n" + config)
    touch(elsewhere / "HEAD", "ref: refs/heads/main\n")
    (elsewhere / "objects").mkdir(parents=True, exist_ok=True)
    (elsewhere / "refs").mkdir(parents=True, exist_ok=True)
    top = tmp_path / "base" / name
    touch(top / ".git", (f"gitdir: {GIT}\n" if text is None else text).replace(GIT, elsewhere.as_posix()))
    for n in ALL_FOUR:
        touch(top / "chain" / n)
    return top


def only_root(base: Path, name: str = "r") -> dict:
    """The whole answer for the one root `name` under base."""
    return load({"seats": str(seats(base, [{"name": "r", "path": name, "kind": "repo"}]))}, world(base))


def test_a_repository_whose_git_folder_lives_elsewhere(tmp_path):
    top = separate(tmp_path)
    w = only_root(tmp_path)["repos"][0]["worktrees"][0]
    assert w["path"] == top.as_posix() and w["common_dir"] == (tmp_path / "gitdirs" / "r.git").as_posix()
    assert w["status"] == "read" and w["set"] == ["VACUOUS"]
    # git's own list names the git folder as the main worktree here (measured, git 2.39); this names the checkout and says so
    assert "git worktree list" in w["note"] and "r.git" in w["note"]


GOOD_GITFILES = {      # measured with git 2.39: it takes each of these
    "line breaks of both kinds": f"gitdir: {GIT}\r\n", "blank lines at the end": f"gitdir: {GIT}\n\n\n",
    "no final line break": f"gitdir: {GIT}", "nothing counted after a NUL": f"gitdir: {GIT}\x00junk\n",
    "a path from the .git file's own folder": "gitdir: ../../gitdirs/r.git\n",
}
BAD_GITFILES = {       # measured with git 2.39: it stops on each of these, with 'invalid gitfile format' or 'not a git repository'
    "no blank after the colon": f"gitdir:{GIT}\n", "capital letters": f"GITDIR: {GIT}\n",
    "a byte-order mark first": chr(0xFEFF) + f"gitdir: {GIT}\n", "no path": "gitdir: \n", "nothing after the colon": "gitdir:\n",
    "a second blank before the path": f"gitdir:  {GIT}\n", "blanks after the path": f"gitdir: {GIT}  \n",
    "a second line": f"gitdir: {GIT}\nmore\n", "not a gitfile at all": "this is not a gitfile\n",
    "a folder that is not there": f"gitdir: {GIT}-nowhere\n",
}


@pytest.mark.parametrize("label", GOOD_GITFILES)
def test_a_gitfile_git_accepts_is_followed(tmp_path, label):
    separate(tmp_path, text=GOOD_GITFILES[label])
    out = only_root(tmp_path)
    w = out["repos"][0]["worktrees"][0]
    assert (w["status"], w["set"], out["problems"]) == ("read", ["VACUOUS"], []), label


@pytest.mark.parametrize("label", BAD_GITFILES)
def test_a_gitfile_git_refuses_gives_no_answer(tmp_path, label):
    separate(tmp_path, text=BAD_GITFILES[label])
    out = only_root(tmp_path)
    (w,) = out["repos"][0]["worktrees"]
    assert (w["status"], w["set"], w["verdicts"], w["events"]) == ("unknown", [], [], []), label
    assert any("git would not run here" in u for u in w["uncertain"]) and kinds(out) == ["bad-gitfile"], label


@pytest.mark.parametrize("label, damage", [
    ("no HEAD", lambda g: (g / "HEAD").unlink()), ("a HEAD that names nothing", lambda g: touch(g / "HEAD", "oops\n")),
    ("a HEAD with a blank first", lambda g: touch(g / "HEAD", " ref: refs/heads/x\n")),
    ("a HEAD naming a branch outside refs/", lambda g: touch(g / "HEAD", "ref: heads/x\n")),
    ("a HEAD with thirty-nine hex digits", lambda g: touch(g / "HEAD", "0123456789abcdef0123456789abcdef0123456\n")),
    ("no objects folder", lambda g: (g / "objects").rmdir()), ("no refs folder", lambda g: (g / "refs").rmdir())])
def test_a_gitfile_whose_target_is_not_a_git_folder_gives_no_answer(tmp_path, label, damage):
    """Measured with git 2.39: it wants a HEAD that names a branch under refs/ or a commit, and the objects and refs folders."""
    separate(tmp_path)
    damage(tmp_path / "gitdirs" / "r.git")
    out = only_root(tmp_path)
    assert out["repos"][0]["worktrees"][0]["status"] == "unknown" and kinds(out) == ["bad-gitfile"], label


@pytest.mark.parametrize("head", ["ref: refs/heads/x\n", "ref: refs/heads/x", "ref:refs/heads/x\n", "ref:   refs/heads/x\r\n",
                                  "ref: refs/\n", "0123456789abcdef0123456789abcdef01234567\n", "0123456789ABCDEF0123456789ABCDEF01234567",
                                  "0123456789abcdef0123456789abcdef01234567 and more\n"])
def test_a_head_git_accepts_is_accepted(tmp_path, head):
    separate(tmp_path)
    touch(tmp_path / "gitdirs" / "r.git" / "HEAD", head)
    assert only_root(tmp_path)["repos"][0]["worktrees"][0]["status"] == "read"


def test_a_gitfile_within_the_size_git_allows_is_read(tmp_path, monkeypatch):
    """Must-pass arm."""
    separate(tmp_path)
    monkeypatch.setattr(gates, "MAX_GITFILE", 1 << 20)
    assert only_root(tmp_path)["repos"][0]["worktrees"][0]["status"] == "read"


def test_a_gitfile_over_the_size_git_allows_gives_no_answer(tmp_path, monkeypatch):
    """Must-refuse arm. Measured with git 2.39: 'too large to be a .git file' (over a megabyte)."""
    separate(tmp_path)
    monkeypatch.setattr(gates, "MAX_GITFILE", 10)
    big = only_root(tmp_path)
    assert big["repos"][0]["worktrees"][0]["status"] == "unknown" and "too large" in big["problems"][0]["text"]


def test_a_damaged_gitfile_is_a_problem_and_the_worktree_has_no_answer(tmp_path):
    top = tmp_path / "base" / "r"
    touch(top / ".git", "this is not a gitfile\n")
    out = only_root(tmp_path)
    (w,) = out["repos"][0]["worktrees"]
    assert (w["status"], w["set"]) == ("unknown", []) and [p["kind"] for p in out["problems"]] == ["bad-gitfile"]
    assert out["summary"]["unknown"] == 1


# ---------------------------------------------------------------- the seats file
def test_roots_of_kind_repo_and_one_home_root_per_seat(tmp_path):
    base = tmp_path / "base"
    for name in ("alpha", "beta", "homes/ann", "homes/bob"):
        repo(base, name)
    people = {"Ann": {"home": "homes/ann"}, "Bob": {"home": "homes/bob"}, "Cy": {"names": ["Cy"]}}
    path = seats(tmp_path, [
        {"name": "alpha", "path": "alpha", "kind": "repo", "boards": []},
        {"name": "notes", "path": "notes", "kind": "folder"},
        {"name": "home", "path": "{home}", "kind": "repo"},
        {"name": "beta", "path": "beta", "kind": "repo"}], people)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["external"] = [{"name": "ext", "path": str(tmp_path / "ext")}]
    path.write_text(json.dumps(data), encoding="utf-8")
    out = load({"seats": str(path)}, world(tmp_path))
    assert [(r["name"], r["seat"]) for r in out["repos"]] == [("alpha", None), ("home", "Ann"), ("home", "Bob"), ("beta", None)]
    assert [p["kind"] for p in out["problems"]] == ["no-home"] and "Cy" in out["problems"][0]["text"]
    assert out["repos"][1]["root"] == (base / "homes" / "ann").as_posix()


def test_a_root_that_is_not_there_or_not_a_repository_is_a_problem(tmp_path):
    (tmp_path / "base" / "plain").mkdir(parents=True)
    path = seats(tmp_path, [{"name": "gone", "path": "gone", "kind": "repo"},
                            {"name": "plain", "path": "plain", "kind": "repo"}])
    out = load({"seats": str(path)}, world(tmp_path))
    assert [(r["name"], r["present"], r["worktrees"]) for r in out["repos"]] == [("gone", False, []), ("plain", True, [])]
    assert sorted(p["kind"] for p in out["problems"]) == ["missing-root", "not-a-repository"]


def test_a_damaged_seats_file_is_a_problem_not_a_crash(tmp_path):
    cases = {"not json": "{ nope", "an array": "[1, 2]", "no roots": json.dumps({"base": "x"}),
             "roots that is not a list": json.dumps({"roots": {"a": 1}})}
    for label, text in cases.items():
        path = touch(tmp_path / "bad.json", text)
        out = load({"seats": str(path)}, world(tmp_path))
        assert out["off"] is False and out["repos"] == [], label
        assert [p["kind"] for p in out["problems"]] in (["bad-json"], ["no-roots"]), label
    out = load({"seats": str(tmp_path / "absent.json")}, world(tmp_path))
    assert out["repos"] == [] and [p["kind"] for p in out["problems"]] == ["unreadable"]
    path = seats(tmp_path, [{"name": "x"}, "text", {"name": "ok", "path": "ok", "kind": "repo"}])
    repo(tmp_path / "base", "ok")
    out = load({"seats": str(path)}, world(tmp_path))
    assert [r["name"] for r in out["repos"]] == ["ok"] and [p["kind"] for p in out["problems"]] == ["bad-root", "bad-root"]


def test_a_seats_file_with_a_byte_order_mark_is_read(tmp_path):
    repo(tmp_path / "base", "r")
    path = seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert [r["name"] for r in load({"seats": str(path)}, world(tmp_path))["repos"]] == ["r"]


def test_the_source_is_off_without_its_key(tmp_path):
    for cfg in ({}, {"inbox": "x"}, {"seats": ""}, None):
        out = load(cfg, world(tmp_path))
        assert out["off"] is True and out["key"] == "seats" and out["repos"] == [] and out["problems"] == []
        json.dumps(out)
    assert load({"seats": str(seats(tmp_path, []))}, world(tmp_path))["off"] is False


def test_the_whole_answer_is_plain_data(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ["pre-commit"]})
    link(main, "a", tmp_path / "wts" / "a")
    link(main, "gone", tmp_path / "wts" / "gone", make=False)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert json.loads(json.dumps(out)) == out
    assert out["read"] == "static" and "never that it still refuses" in out["read_note"]
    # main: one hook and no identity (open, checks nothing); a: its checkout has no chain folder (open); gone: missing
    assert out["summary"] == {"worktrees": 3, "INERT": 0, "UNCOVERED": 2, "VACUOUS": 1, "ARMED": 0, "unknown": 0,
                              "missing": 1, "bare": 0, "uncertain": 0}


# ---------------------------------------------------------------- bare, and a work tree somewhere else
CHAIN = {"chain": ALL_FOUR}
WHO = "A <a@x.y>\n"


def worktrees_of(tmp_path: Path, w: World | None = None) -> list:
    return only_root(tmp_path)["repos"][0]["worktrees"] if w is None else load(
        {"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, w)["repos"][0]["worktrees"]


@pytest.mark.parametrize("text", ["\tbare = false\n", "\tbare = no\n", "\tbare = 0\n", "\tworktree = ..\n", "\tworktree = ../\n"])
def test_a_repository_that_is_not_bare_and_has_this_folder_as_its_work_tree_is_read(tmp_path, text):
    w = one(tmp_path, config="\thooksPath = chain\n" + text, hooks=CHAIN, identity=WHO)
    assert (w["status"], w["set"]) == ("read", ["ARMED"])


def test_a_work_tree_named_by_its_full_path_is_read(tmp_path):
    here = tmp_path / "base" / "r"
    for text in (f"\tworktree = {here.as_posix()}\n", f"\tworktree = {here.as_posix()}/\n", f'\tworktree = "{str(here)}"\n'.replace("\\", "\\\\")):
        w = one(tmp_path, config="\thooksPath = chain\n" + text, hooks=CHAIN, identity=WHO)
        assert (w["status"], w["set"]) == ("read", ["ARMED"]), text


@pytest.mark.parametrize("text", ["\tbare = true\n", "\tbare\n", "\tbare = yes\n", "\tbare = 1\n", "\tbare = false\n\tbare = true\n"])
def test_a_repository_that_says_it_is_bare_has_no_work_tree_and_no_verdict(tmp_path, text):
    """Measured with git 2.39: with core.bare on, `git rev-parse --show-toplevel` stops ('must be run in a work tree'), so the
    hook checker has no verdict, and `git worktree list` calls the main worktree bare."""
    out = whole(tmp_path, config="\thooksPath = chain\n" + text, hooks=CHAIN, identity=WHO)
    w = out["repos"][0]["worktrees"][0]
    assert (w["status"], w["set"], w["verdicts"], w["events"], w["hooks_path"]) == ("bare", [], [], [], None)
    assert w["note"].startswith("a bare repository") and "core.bare is on" in w["note"]
    assert out["summary"]["bare"] == 1 and out["summary"]["unknown"] == 0 and out["repos"][0]["counts"]["bare"] == 1


def test_the_last_core_bare_wins(tmp_path):
    w = one(tmp_path, config="\thooksPath = chain\n\tbare = true\n\tbare = false\n", hooks=CHAIN, identity=WHO)
    assert w["status"] == "read" and w["set"] == ["ARMED"]


def test_without_a_repository_format_version_git_ignores_bare_and_worktree(tmp_path):
    """Must-pass arm. Measured with git 2.39: with no version (or a negative one) git throws away what it read first from
    the file, so these lines change nothing and the worktree is read as it stands."""
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    nowhere = (tmp_path / "nowhere").as_posix()
    for version in ("", "\trepositoryformatversion = -1\n"):
        touch(main / ".git" / "config", f"[core]\n{version}\thooksPath = chain\n\tbare = true\n\tworktree = {nowhere}\n")
        w = worktrees_of(tmp_path)[0]
        assert (w["status"], w["set"]) == ("read", ["ARMED"]), version


def test_bare_counts_once_the_repository_has_a_format_version(tmp_path):
    """Must-refuse arm. The same lines, with a version, make the repository bare: no verdict."""
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    touch(main / ".git" / "config", "[core]\n\trepositoryformatversion = 0\n\thooksPath = chain\n\tbare = true\n")
    assert worktrees_of(tmp_path)[0]["status"] == "bare"
    nowhere = (tmp_path / "nowhere").as_posix()
    touch(main / ".git" / "config", f"[core]\n\trepositoryformatversion = 1\n\thooksPath = chain\n\tworktree = {nowhere}\n")
    assert worktrees_of(tmp_path)[0]["status"] == "unknown"                   # and so does a work tree somewhere else


def test_a_work_tree_somewhere_else_gives_no_verdict_and_names_both_places(tmp_path):
    """Measured with git 2.39: git rev-parse --show-toplevel prints core.worktree, so the checker measures that folder
    (here a different one) and the verdict would be about it, not about the worktree asked for."""
    other = tmp_path / "other-place"
    other.mkdir()
    (tmp_path / "base" / "r" / "inner").mkdir(parents=True)
    for label, text in (("absolute", f"\tworktree = {other.as_posix()}\n"), ("relative to the git folder", "\tworktree = ../inner\n"),
                        ("the git folder itself", "\tworktree = .\n")):
        out = whole(tmp_path, config="\thooksPath = chain\n" + text, hooks=CHAIN, identity=WHO)
        w = out["repos"][0]["worktrees"][0]
        assert (w["status"], w["set"], w["verdicts"]) == ("unknown", [], []), label
        reason = next(u for u in w["uncertain"] if "another work tree" in u)
        assert "core.worktree" in reason and (tmp_path / "base" / "r").as_posix() in reason, label


@pytest.mark.parametrize("label, text", [
    ("no value", "\tworktree\n"), ("an empty value", "\tworktree =\n"), ("a relative folder that is not there", "\tworktree = ../nope\n"),
    ("an absolute folder that is not there", "\tworktree = /no/such/place-here\n"),
    ("a bare that is not a yes or no", "\tbare = maybe\n")])
def test_a_work_tree_git_cannot_go_to_gives_no_answer(tmp_path, label, text):
    """D4 (round 2): an absolute core.worktree naming a missing folder is where git stops, as a relative one is; it was
    called "another work tree" before."""
    out = whole(tmp_path, config="\thooksPath = chain\n" + text, hooks=CHAIN, identity=WHO)
    w = out["repos"][0]["worktrees"][0]
    assert (w["status"], w["set"], w["verdicts"]) == ("unknown", [], []), label
    assert any("git would refuse to run here" in u for u in w["uncertain"]), label
    assert not any("another work tree" in u for u in w["uncertain"]), label
    if "not there" in label:
        assert any("which is not a folder" in u for u in w["uncertain"]), label


def linked_bare(tmp_path: Path, extension: bool) -> tuple:
    """A repository whose shared file says core.bare, with a linked worktree that has its own hooks and identity."""
    config = "\thooksPath = chain\n\tbare = true\n" + ("[extensions]\n\tworktreeConfig = true\n" if extension else "")
    main = repo(tmp_path / "base", "r", config=config, hooks=CHAIN, identity=WHO)
    own = link(main, "feat", tmp_path / "wts" / "feat")
    for n in ALL_FOUR:
        touch(tmp_path / "wts" / "feat" / "chain" / n)
    touch(tmp_path / "wts" / "feat" / ".identity", WHO)
    return main, own


def test_core_bare_in_the_shared_file_binds_only_the_main_worktree_without_the_worktree_extension(tmp_path):
    """Must-pass arm. Measured with git 2.39: the linked worktree works (its checker verdict is ARMED); the main one is bare."""
    linked_bare(tmp_path, False)
    main_w, feat = worktrees_of(tmp_path)
    assert (main_w["status"], feat["status"], feat["set"]) == ("bare", "read", ["ARMED"])


def test_core_bare_in_the_shared_file_binds_a_linked_worktree_when_the_worktree_extension_is_on(tmp_path):
    """Must-refuse arm. Measured with git 2.39: with extensions.worktreeConfig on the shared file's core.bare reaches the
    linked worktrees too, and git stops there ('must be run in a work tree')."""
    linked_bare(tmp_path, True)
    main_w, feat = worktrees_of(tmp_path)
    assert (main_w["status"], feat["status"], feat["set"], feat["verdicts"]) == ("bare", "unknown", [], [])
    assert any("git would refuse to run here" in u and "core.bare is on" in u for u in feat["uncertain"])


def test_a_linked_worktrees_own_file_can_take_core_bare_back(tmp_path):
    """Must-pass arm."""
    main, own = linked_bare(tmp_path, True)
    touch(own / "config.worktree", "[core]\n\tbare = false\n")
    assert [w["status"] for w in worktrees_of(tmp_path)] == ["bare", "read"]


def linked_elsewhere(tmp_path: Path, extension: bool) -> Path:
    """A linked worktree whose own settings file names another folder as the work tree."""
    config = "\thooksPath = chain\n" + ("[extensions]\n\tworktreeConfig = true\n" if extension else "")
    main = repo(tmp_path / "base", "r", config=config, hooks=CHAIN, identity=WHO)
    other = tmp_path / "elsewhere"
    other.mkdir()
    return link(main, "feat", tmp_path / "wts" / "feat", config_worktree=f"[core]\n\tworktree = {other.as_posix()}\n")


def test_a_linked_worktrees_own_core_worktree_is_not_read_without_the_worktree_extension(tmp_path):
    """Must-pass arm."""
    linked_elsewhere(tmp_path, False)
    assert [w["status"] for w in worktrees_of(tmp_path)] == ["read", "read"]


def test_a_linked_worktrees_own_core_worktree_counts_with_the_worktree_extension(tmp_path):
    """Must-refuse arm. Measured with git 2.39: git then measures the other folder, and the main worktree is not bound by it."""
    linked_elsewhere(tmp_path, True)
    main_w, feat = worktrees_of(tmp_path)
    assert main_w["status"] == "read"
    assert feat["status"] == "unknown" and any("another work tree" in u and "config.worktree" in u for u in feat["uncertain"])


def main_with_worktree_file(tmp_path: Path, text: str) -> None:
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n[extensions]\n\tworktreeConfig = true\n", hooks=CHAIN, identity=WHO)
    touch(main / ".git" / "config.worktree", text)


def test_the_worktree_file_of_the_main_worktree_can_say_it_is_not_bare(tmp_path):
    """Must-pass arm."""
    main_with_worktree_file(tmp_path, "[core]\n\tbare = false\n")
    assert worktrees_of(tmp_path)[0]["status"] == "read"


def test_the_worktree_file_of_the_main_worktree_can_say_it_is_bare(tmp_path):
    """Must-refuse arm. Measured with git 2.39: core.bare in config.worktree makes the main worktree bare (no verdict)."""
    main_with_worktree_file(tmp_path, "[core]\n\tbare = true\n")
    assert worktrees_of(tmp_path)[0]["status"] == "bare"


def test_bare_and_worktree_in_your_own_settings_are_not_read_by_git(tmp_path):
    """Measured with git 2.39: core.bare and core.worktree count only from the repository's own file (and a worktree's); a
    line in ~/.gitconfig, or in a file the repository's file includes, changes nothing."""
    touch(tmp_path / "user" / ".gitconfig", "[core]\n\tbare = true\n\tworktree = /elsewhere/entirely\n")
    assert one(tmp_path, w=world(tmp_path), config="\thooksPath = chain\n", hooks=CHAIN, identity=WHO)["set"] == ["ARMED"]
    touch(tmp_path / "inc.cfg", "[core]\n\tbare = true\n")
    w = one(tmp_path / "b", config=f"\thooksPath = chain\n[include]\n\tpath = {(tmp_path / 'inc.cfg').as_posix()}\n", hooks=CHAIN,
            identity=WHO)
    assert w["set"] == ["ARMED"]


# ---------------------------------------------------------------- a bare repository named as a root
def bare_repo(tmp_path: Path, name: str = "b.git") -> Path:
    """A repository with no work tree: its own folder holds HEAD, config, objects and refs, and no .git."""
    top = tmp_path / "base" / name
    touch(top / "config", "[core]\n\trepositoryformatversion = 0\n\tbare = true\n\thooksPath = chain\n")
    touch(top / "HEAD", "ref: refs/heads/main\n")
    (top / "objects").mkdir(parents=True, exist_ok=True)
    (top / "refs").mkdir(parents=True, exist_ok=True)
    return top


def test_a_bare_repository_root_lists_its_linked_worktrees_and_reports_the_bare_main_as_bare(tmp_path):
    """Measured with git 2.39: `git worktree list` names the bare repository's own folder first, marked bare, then the
    linked worktrees; the checker has no verdict for the bare one and a normal one for each linked."""
    top = bare_repo(tmp_path)
    for wid in ("one", "two"):
        link(top, wid, tmp_path / "wts" / wid, common=top)
        for n in ALL_FOUR:
            touch(tmp_path / "wts" / wid / "chain" / n)
        touch(tmp_path / "wts" / wid / ".identity", WHO)
    out = load({"seats": str(seats(tmp_path, [{"name": "b", "path": "b.git", "kind": "repo"}]))}, world(tmp_path))
    bare, one_, two = out["repos"][0]["worktrees"]
    assert (bare["name"], bare["main"], bare["status"], bare["set"], bare["path"]) == (None, True, "bare", [], top.as_posix())
    assert [(w["name"], w["status"], w["set"]) for w in (one_, two)] == [("one", "read", ["ARMED"]), ("two", "read", ["ARMED"])]
    assert out["problems"] == [] and out["summary"]["worktrees"] == 3 and out["summary"]["bare"] == 1
    assert out["summary"]["ARMED"] == 2 and out["summary"]["unknown"] == 0


def test_a_bare_repository_root_with_no_linked_worktree_is_one_bare_record(tmp_path):
    top = bare_repo(tmp_path)
    (w,) = load({"seats": str(seats(tmp_path, [{"name": "b", "path": "b.git", "kind": "repo"}]))}, world(tmp_path))["repos"][0]["worktrees"]
    assert (w["status"], w["exists"], w["path"]) == ("bare", True, top.as_posix())


def test_a_folder_that_is_not_a_git_folder_is_still_no_repository(tmp_path):
    top = bare_repo(tmp_path)
    (top / "HEAD").write_text("not a head\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "b", "path": "b.git", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"] == [] and kinds(out) == ["not-a-repository"]


# ---------------------------------------------------------------- include.path, expanded as git expands it
def test_a_prefix_include_is_followed_and_never_taken_for_a_relative_path(tmp_path):
    """Measured with git 2.39: %(prefix)/ in an include path stands for git's install prefix (and the rest is taken from
    there); a folder that happens to be named %(prefix) beside the settings file is not it."""
    prefix = tmp_path / "git-install"
    touch(prefix / "etc" / "team.cfg", "[core]\n\thooksPath = from-prefix\n")
    touch(tmp_path / "user" / "%(prefix)" / "etc" / "team.cfg", "[core]\n\thooksPath = from-a-decoy\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = %(prefix)/etc/team.cfg\n")
    w = one(tmp_path, w=world(tmp_path, prefix=prefix))
    assert w["hooks_path"]["value"] == "from-prefix" and w["hooks_path"]["scope"] == "global"
    assert w["hooks_path"]["file"] == (prefix / "etc" / "team.cfg").as_posix()


def test_a_prefix_include_that_climbs_out_of_the_prefix_and_one_with_an_absolute_rest(tmp_path):
    """The prefix folder is made: outside Windows ".." is taken on the disk, not on the text, so a path that climbs
    through a folder that is not there names no file (git, which opens the path as it stands, skips it too)."""
    prefix = tmp_path / "git-install" / "mingw"
    prefix.mkdir(parents=True)
    touch(tmp_path / "sibling.cfg", "[core]\n\thooksPath = from-sibling\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = %(prefix)/../../sibling.cfg\n")
    assert one(tmp_path, w=world(tmp_path, prefix=prefix))["hooks_path"]["value"] == "from-sibling"
    touch(tmp_path / "b" / "user" / ".gitconfig", f"[include]\n\tpath = %(prefix)/{(tmp_path / 'sibling.cfg').as_posix()}\n")
    assert one(tmp_path / "b", w=world(tmp_path / "b", prefix=prefix))["hooks_path"]["value"] == "from-sibling"   # used as it stands


def test_a_prefix_include_that_names_no_file_is_skipped(tmp_path):
    """Must-pass arm. Git skips an include of a file that is not there."""
    prefix = tmp_path / "git-install"
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = %(prefix)/not-there.cfg\n[core]\n\thooksPath = chain\n")
    w = one(tmp_path, w=world(tmp_path, prefix=prefix), hooks=CHAIN, identity=WHO)
    assert (w["status"], w["set"], w["uncertain"]) == ("read", ["ARMED"], [])


def test_a_prefix_include_with_no_known_prefix_gives_no_answer(tmp_path):
    """Must-refuse arm. Where git's install prefix was not found the file cannot be named, so there is no verdict."""
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = %(prefix)/x.cfg\n")
    out = whole(tmp_path, w=world(tmp_path))
    w = out["repos"][0]["worktrees"][0]
    assert w["status"] == "unknown" and any(u.startswith("cannot tell:") and "install prefix" in u for u in w["uncertain"])
    assert kinds(out) == ["unknown-include"]


@pytest.mark.parametrize("path", ["~nosuchuser/x.cfg", "~\\\\x.cfg", "~x", "~root/x.cfg"])
def test_an_include_from_another_users_home_gives_no_answer(tmp_path, path):
    """Measured with git 2.39 for Windows: ~name/ (and ~\\) cannot be expanded, git stops; elsewhere it needs the user
    database, which this does not read. Either way there is no verdict."""
    touch(tmp_path / "user" / "x.cfg", "[user]\n\tname = x\n")
    touch(tmp_path / "user" / ".gitconfig", f"[include]\n\tpath = {path}\n[core]\n\thooksPath = chain\n")
    out = whole(tmp_path, w=world(tmp_path), hooks=CHAIN, identity=WHO)
    w = out["repos"][0]["worktrees"][0]
    assert (w["status"], w["set"], w["verdicts"]) == ("unknown", [], [])
    assert any(u.startswith("cannot tell:") and "another user's home" in u for u in w["uncertain"]) and kinds(out) == ["unknown-include"]


def test_an_include_from_your_own_home_is_followed(tmp_path):
    touch(tmp_path / "user" / "x.cfg", "[core]\n\thooksPath = chain\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = ~/x.cfg\n")
    w = one(tmp_path, w=world(tmp_path), hooks=CHAIN, identity=WHO)
    assert (w["status"], w["set"]) == ("read", ["ARMED"]) and w["hooks_path"]["file"] == (tmp_path / "user" / "x.cfg").as_posix()


def test_on_windows_a_path_that_starts_with_a_single_slash_is_taken_from_the_install_prefix(tmp_path, monkeypatch):
    """Must-refuse arm. Measured with Git for Windows 2.39: include.path = /x is read as %(prefix)/x (git warns 'old-style'),
    so the file on the current drive is not the one it reads."""
    monkeypatch.setattr(gates, "WINDOWS", True)
    prefix = tmp_path / "git-install"
    touch(prefix / "inc.cfg", "[core]\n\thooksPath = from-prefix\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = /inc.cfg\n")
    assert one(tmp_path, w=world(tmp_path, prefix=prefix))["hooks_path"]["value"] == "from-prefix"


def test_elsewhere_a_rooted_include_path_is_an_ordinary_path(tmp_path, monkeypatch):
    """Must-pass arm. On Windows the rooted path is taken on the current drive, so the test runs from tmp_path's drive
    (a runner whose checkout is on another drive than its temp folder would otherwise look on the wrong one)."""
    monkeypatch.setattr(gates, "WINDOWS", False)
    monkeypatch.chdir(tmp_path)
    prefix = tmp_path / "git-install"
    rooted = (tmp_path / "inc.cfg").as_posix()
    rooted = rooted.split(":", 1)[1] if ":" in rooted[:3] else rooted
    touch(tmp_path / "inc.cfg", "[core]\n\thooksPath = on-the-drive\n")
    touch(tmp_path / "user" / ".gitconfig", f"[include]\n\tpath = {rooted}\n")
    assert one(tmp_path, w=world(tmp_path, prefix=prefix))["hooks_path"]["value"] == "on-the-drive"


def test_the_install_prefix_is_found_from_the_git_on_the_path(tmp_path):
    cmd_install = tmp_path / "gitwin"
    touch(cmd_install / "cmd" / "git.exe")
    touch(cmd_install / "mingw64" / "bin" / "git.exe")
    assert gates.this_machine({"PATH": str(cmd_install / "cmd")}).prefix == cmd_install / "mingw64"      # cmd/ hands over to mingw64/bin
    assert gates.this_machine({"PATH": str(cmd_install / "mingw64" / "bin")}).prefix == cmd_install / "mingw64"
    unix = tmp_path / "usr"
    touch(unix / "bin" / "git")
    assert gates.this_machine({"PATH": str(unix / "bin")}).prefix == unix
    assert gates.this_machine({"PATH": str(tmp_path / "nowhere")}).prefix is None


# ---------------------------------------------------------------- what git stops on in a value
def settings_file(tmp_path: Path, text: str, where: str = "local", version: str | None = "0", **kw) -> dict:
    """The one worktree of a repository whose settings are `text`, written in its own file or in your own (global)."""
    if where == "global":
        touch(tmp_path / "user" / ".gitconfig", text)
        return one(tmp_path, w=world(tmp_path), config="\thooksPath = chain\n", hooks=CHAIN, identity=WHO, **kw)
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    head = "" if version is None else f"\trepositoryformatversion = {version}\n"
    touch(main / ".git" / "config", f"[core]\n{head}\thooksPath = chain\n" + text)
    return worktrees_of(tmp_path)[0]


REFUSED = {       # each stops git 2.39 at start-up (the hook checker's first step gives nothing), by the value written
    "a yes or no that is neither": "[core]\n\tfilemode = maybe\n",
    "a name that needs a value, with none": "[user]\n\tname\n",
    "an address that needs a value, with none": "[user]\n\temail\n",
    "a number that is none": "[index]\n\tversion = two\n",
    "a number too big for an int": "[index]\n\tversion = 2147483648\n",
    "a compression level out of range": "[core]\n\tcompression = 10\n",
    "a size that is negative": "[core]\n\tbigfilethreshold = -1\n",
    "a word the setting does not know": "[push]\n\tdefault = Simple\n",
    "a word in the wrong case": "[branch]\n\tautosetuprebase = NEVER\n",
    "an advice switch that is not a yes or no": "[advice]\n\tstatusHints = perhaps\n",
    "an abbreviation length out of range": "[core]\n\tabbrev = 3\n",
    "an abbreviation that is a yes": "[core]\n\tabbrev = true\n",
    "a comment character of two characters": "[core]\n\tcommentchar = ab\n",
    "a fetch algorithm git does not know": "[fetch]\n\tnegotiationAlgorithm = fast\n",
    "an end-of-line setting that is not a yes or no": "[core]\n\tautocrlf = sometimes\n",
    "a compression level written as a size": "[pack]\n\tcompression = 1k\n",
}
ACCEPTED = {      # the neighbours git takes
    "a yes or no that is a number": "[core]\n\tfilemode = 1\n", "a yes written as the bare name": "[core]\n\tfilemode\n",
    "a name with a value": "[user]\n\tname = Ann\n", "an empty name": "[user]\n\tname =\n",
    "an address": "[user]\n\temail = a@x.y\n", "a number": "[index]\n\tversion = 4\n", "a number with a unit": "[index]\n\tversion = 1k\n",
    "a hexadecimal number": "[index]\n\tversion = 0x4\n", "a compression level": "[core]\n\tcompression = -1\n",
    "the top compression level": "[core]\n\tcompression = 9\n", "a size with a unit": "[core]\n\tbigfilethreshold = 512m\n",
    "a word the setting knows": "[push]\n\tdefault = simple\n", "a word in any case": "[core]\n\tautocrlf = INPUT\n",
    "an advice switch": "[advice]\n\tstatusHints = false\n", "an abbreviation length": "[core]\n\tabbrev = 12\n",
    "an abbreviation of auto": "[core]\n\tabbrev = AUTO\n", "an abbreviation that is a no": "[core]\n\tabbrev = no\n",
    "a comment character": "[core]\n\tcommentchar = \";\"\n", "the automatic comment character": "[core]\n\tcommentchar = auto\n",
    "a fetch algorithm": "[fetch]\n\tnegotiationAlgorithm = SKIPPING\n", "an end-of-line setting": "[core]\n\tautocrlf = true\n",
    "a name git does not read": "[nothing]\n\tat-all\n", "a hook folder name": "[core]\n\thooksPath = chain\n",
}


@pytest.mark.parametrize("label", ACCEPTED)
def test_a_value_git_accepts_is_read(tmp_path, label):
    w = settings_file(tmp_path, ACCEPTED[label])
    assert (w["status"], w["set"], w["uncertain"]) == ("read", ["ARMED"], []), label


@pytest.mark.parametrize("label", REFUSED)
def test_a_value_git_refuses_gives_no_answer(tmp_path, label):
    w = settings_file(tmp_path, REFUSED[label])
    assert (w["status"], w["set"], w["verdicts"], w["events"]) == ("unknown", [], [], []), label
    assert any(u.startswith("git would refuse to run here:") for u in w["uncertain"]), label
    key = REFUSED[label].split("]")[0][1:] + "."
    assert any(key in u.lower() for u in w["uncertain"]), label                  # and the reason names the setting


def test_a_value_git_refuses_is_a_problem_once_and_binds_every_worktree_that_reads_the_file(tmp_path):
    touch(tmp_path / "user" / ".gitconfig", "[core]\n\tfilemode = maybe\n")
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    link(main, "feat", tmp_path / "wts" / "feat")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert [w["status"] for w in out["repos"][0]["worktrees"]] == ["unknown", "unknown"]
    assert kinds(out) == ["bad-value"] and out["problems"][0]["source"].endswith(".gitconfig")
    assert "core.filemode" in out["problems"][0]["text"]


def test_a_bad_value_binds_wherever_it_is_written_and_a_protected_name_binds_from_your_settings(tmp_path):
    """Must-refuse arm. Measured with git 2.39: a bad core.filemode stops git wherever it is written; trace2.* (and
    core.longpaths on Windows) are read from the system's and your own settings only, and stop git from there."""
    for where in ("global", "local"):
        assert settings_file(tmp_path / where, "[core]\n\tfilemode = maybe\n", where)["status"] == "unknown", where
    assert settings_file(tmp_path / "g", "[trace2]\n\tenvVars\n", "global")["status"] == "unknown"


def test_a_protected_name_in_the_repositorys_own_file_is_not_read(tmp_path):
    """Must-pass arm. The same line in the repository's own file is never searched for by git, so it cannot stop it."""
    assert settings_file(tmp_path / "l", "[trace2]\n\tenvVars\n", "local")["status"] == "read"
    assert settings_file(tmp_path / "ok", "[trace2]\n\tenvVars = HOME\n", "global")["status"] == "read"


def test_a_name_that_exists_only_on_windows_is_a_refusal_there(tmp_path, monkeypatch):
    """Must-refuse arm."""
    monkeypatch.setattr(gates, "WINDOWS", True)
    assert settings_file(tmp_path / "w", "[core]\n\tfscache = maybe\n")["status"] == "unknown"
    assert settings_file(tmp_path / "wl", "[core]\n\tlongpaths = maybe\n", "global")["status"] == "unknown"


def test_a_name_that_exists_only_on_windows_is_no_refusal_elsewhere(tmp_path, monkeypatch):
    """Must-pass arm."""
    monkeypatch.setattr(gates, "WINDOWS", False)
    assert settings_file(tmp_path / "x", "[core]\n\tfscache = maybe\n")["status"] == "read"
    assert settings_file(tmp_path / "xl", "[core]\n\tlongpaths = maybe\n", "global")["status"] == "read"


def test_another_users_home_in_a_path_setting_stops_git_on_windows(tmp_path, monkeypatch):
    """Must-refuse arm. Measured with Git for Windows 2.39: 'failed to expand user dir' for ~name/ and ~\\ in a path setting."""
    monkeypatch.setattr(gates, "WINDOWS", True)
    for k, value in enumerate(("~nosuchuser/x", "~\\\\x", "~x")):
        w = settings_file(tmp_path / str(k), f"[core]\n\texcludesfile = {value}\n")
        assert w["status"] == "unknown" and any("another user's home" in u for u in w["uncertain"]), value


def test_a_path_setting_git_can_expand_is_read(tmp_path, monkeypatch):
    """Must-pass arm. ~ and ~/ are the home, %(prefix)/ the install prefix, and /x is an ordinary rooted path."""
    monkeypatch.setattr(gates, "WINDOWS", True)
    for k, value in enumerate(("~/x", "~", "/x", "plain", "%(prefix)/x")):
        assert settings_file(tmp_path / f"ok{k}", f"[core]\n\texcludesfile = {value}\n")["status"] == "read", value
    monkeypatch.setattr(gates, "WINDOWS", False)
    assert settings_file(tmp_path / "nt", "[core]\n\texcludesfile = ~nosuchuser/x\n")["status"] == "read"   # needs the user database


def test_git_numbers_are_read_as_git_reads_them():
    good = {"0": 0, "7": 7, "-1": -1, "+3": 3, "0x10": 16, "0X1f": 31, "010": 8, "1k": 1024, "2K": 2048, "1m": 1 << 20, "1g": 1 << 30,
            "  5": 5, "2147483647": 2147483647, "-2147483647": -2147483647}
    for text, number in good.items():
        assert gates.git_number(text) == number, text
    for text in ("", None, "x", "1.5", "08", "1kb", "1 k", "0x", "2147483648", "-2147483648", "2g", "4g", "99999999999999999999", "1e3"):
        assert gates.git_number(text) is None, text
    assert gates.git_number("4294967295", 32, signed=False) == 4294967295 and gates.git_number("4294967296", 32, signed=False) is None
    assert gates.git_number("-1", 32, signed=False) is None and gates.git_number("4294967296", 64, signed=False) == 4294967296


def test_every_rule_in_the_table_is_well_formed():
    kinds_ = {"text", "path", "bool", "words+bool", "words", "int", "ulong", "abbrev", "commentchar"}
    assert all(rule[0] in kinds_ for rule in gates.RULES.values())
    assert gates.PROTECTED <= set(gates.RULES) and gates.WINDOWS_ONLY <= set(gates.RULES)
    assert all(key == key.lower() and key.count(".") == 1 for key in gates.RULES)
    for key, rule in gates.RULES.items():
        if rule[0] in ("words", "words+bool"):
            assert rule[1] and all(w == w.lower() for w in rule[1]) and isinstance(rule[2], bool), key
    assert gates.value_problem("core.filemode", "maybe") and gates.value_problem("core.filemode", "yes") is None
    assert gates.value_problem("not.a.rule", "anything") is None and gates.value_problem("user.name", None) == "user.name has no value"


# ---------------------------------------------------------------- the repository format, and its extensions
def formatted(tmp_path: Path, version: str | None, extra: str = "", where: str = "local") -> dict:
    return settings_file(tmp_path, extra, where, version)


FORMAT_REFUSED = {      # measured with git 2.39
    "a format this git does not know": ("2", ""), "a format 3": ("3", ""), "a format that is no number": ("two", ""),
    "a format written with a unit": ("1k", ""), "an octal format above 1": ("010", ""),
    "an extension this git does not know, at format 1": ("1", "[extensions]\n\trefStorage = reftable\n"),
    "an extension in capitals it does not know": ("1", "[extensions]\n\tFoo = x\n"),
    "an extension under a sub-name": ("1", '[extensions "x"]\n\tfoo = 1\n'),
    "an extension that needs format 1, at format 0": ("0", "[extensions]\n\tobjectFormat = sha1\n"),
    "the other extension that needs format 1, at format 0": ("0", "[extensions]\n\tnoop-v1 = x\n"),
    "an object format git does not know": ("1", "[extensions]\n\tobjectFormat = banana\n"),
    "an object format git does not know, with no version": (None, "[extensions]\n\tobjectFormat = banana\n"),
    "a worktree extension that is no yes or no, with a negative version": ("-1", "[extensions]\n\tworktreeConfig = perhaps\n"),
    "an object format in capitals": ("1", "[extensions]\n\tobjectFormat = SHA1\n"),
    "an object format with no value": ("1", "[extensions]\n\tobjectFormat\n"),
    "a worktree extension that is not a yes or no": ("0", "[extensions]\n\tworktreeConfig = perhaps\n"),
    "a precious-objects extension that is not a yes or no": ("1", "[extensions]\n\tpreciousObjects = perhaps\n"),
    "a partial clone with no value": ("0", "[extensions]\n\tpartialClone\n"),
}
FORMAT_READ = {
    "format 1 with the extensions it knows": ("1", "[extensions]\n\tobjectFormat = sha256\n\tnoop = x\n\tnoop-v1\n\tpreciousObjects = true\n"),
    "format 1 with a worktree extension": ("1", "[extensions]\n\tworktreeConfig = true\n"),
    "an extension it does not know, at format 0": ("0", "[extensions]\n\trefStorage = reftable\n"),
    "no version at all, whatever the extensions": (None, "[extensions]\n\tobjectFormat = sha1\n\tfoo = x\n"),
    "a negative version, whatever the extensions": ("-1", "[extensions]\n\tobjectFormat = sha1\n\tfoo = x\n"),
    "a version written in hexadecimal": ("0x1", ""), "a version with a plus": ("+1", "[extensions]\n\tobjectFormat = sha1\n"),
    "the extensions it knows at format 0": ("0", "[extensions]\n\tnoop = x\n\tpreciousObjects = false\n\tpartialClone = origin\n"),
    "a partial clone that names something": ("1", "[extensions]\n\tpartialClone = banana\n"),
}


@pytest.mark.parametrize("label", FORMAT_READ)
def test_a_repository_format_git_accepts_is_read(tmp_path, label):
    version, extra = FORMAT_READ[label]
    w = formatted(tmp_path, version, extra)
    assert (w["status"], w["set"]) == ("read", ["ARMED"]), label


@pytest.mark.parametrize("label", FORMAT_REFUSED)
def test_a_repository_format_git_refuses_gives_no_answer(tmp_path, label):
    version, extra = FORMAT_REFUSED[label]
    w = formatted(tmp_path, version, extra)
    assert (w["status"], w["set"], w["verdicts"]) == ("unknown", [], []), label
    assert any(u.startswith("git would refuse to run here:") for u in w["uncertain"]), label


def test_a_repository_format_version_with_no_value_gives_no_answer(tmp_path):
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    touch(main / ".git" / "config", "[core]\n\trepositoryformatversion\n\thooksPath = chain\n")
    w = worktrees_of(tmp_path)[0]
    assert w["status"] == "unknown" and any("repositoryformatversion has no value" in u for u in w["uncertain"])


def test_the_format_and_extensions_count_only_in_the_repositorys_own_file(tmp_path):
    """Measured with git 2.39: git reads them from the repository's file alone; the same lines in ~/.gitconfig, or in a file
    the repository's file includes, are ignored (so cannot stop it)."""
    for k, where in enumerate(("global", "included")):
        text = "[core]\n\trepositoryformatversion = 2\n[extensions]\n\trefStorage = x\n\tobjectFormat = banana\n"
        if where == "global":
            w = settings_file(tmp_path / str(k), text, "global")
        else:
            touch(tmp_path / "inc.cfg", text)
            w = settings_file(tmp_path / str(k), f"[include]\n\tpath = {(tmp_path / 'inc.cfg').as_posix()}\n")
        assert w["status"] == "read", where


def test_a_worktree_extension_with_no_version_does_not_turn_the_worktree_file_on(tmp_path):
    """Must-refuse arm (the old reading turned it on). Measured with git 2.39: no version, so the extension is thrown away."""
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    touch(main / ".git" / "config.worktree", "[core]\n\thooksPath = elsewhere\n")
    touch(main / ".git" / "config", "[core]\n\thooksPath = chain\n[extensions]\n\tworktreeConfig = true\n")
    w = worktrees_of(tmp_path)[0]
    assert w["hooks_path"]["scope"] == "local" and w["set"] == ["ARMED"]


def test_a_worktree_extension_turns_the_worktree_file_on_once_there_is_a_version(tmp_path):
    """Must-pass arm."""
    main = repo(tmp_path / "base", "r", hooks=CHAIN, identity=WHO)
    touch(main / ".git" / "config.worktree", "[core]\n\thooksPath = elsewhere\n")
    touch(main / ".git" / "config", "[core]\n\trepositoryformatversion = 1\n\thooksPath = chain\n[extensions]\n\tworktreeConfig = true\n")
    assert worktrees_of(tmp_path)[0]["hooks_path"]["scope"] == "worktree"


def test_a_conditional_include_that_holds_a_value_git_stops_on_is_a_doubt(tmp_path):
    touch(tmp_path / "user" / "cond.cfg", "[core]\n\tfilemode = maybe\n")
    touch(tmp_path / "user" / ".gitconfig", '[includeIf "gitdir:/work/"]\n\tpath = cond.cfg\n')
    (doubt,) = one(tmp_path, w=world(tmp_path))["uncertain"]
    assert "is not evaluated" in doubt and "make git refuse" in doubt


# ---------------------------------------------------------------- a linked worktree's own .git file
def linked_checkout(tmp_path: Path) -> tuple:
    """(the main worktree's folder, the admin folder of a linked worktree `feat`, the linked worktree's folder)."""
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks=CHAIN, identity=WHO)
    where = tmp_path / "wts" / "feat"
    admin = link(main, "feat", where)
    for n in ALL_FOUR:
        touch(where / "chain" / n)
    touch(where / ".identity", WHO)
    return main, admin, where


def feat_of(tmp_path: Path) -> dict:
    return worktrees_of(tmp_path)[1]


def test_a_linked_worktree_whose_gitfile_names_its_admin_folder_is_read(tmp_path):
    main, admin, where = linked_checkout(tmp_path)
    assert (feat_of(tmp_path)["status"], feat_of(tmp_path)["set"]) == ("read", ["ARMED"])
    for text in (f"gitdir: {admin.as_posix()}\r\n", f"gitdir: {admin.as_posix()}", f"gitdir: {admin.as_posix()}\n\n",
                 f"gitdir: {os.path.relpath(admin, where).replace(os.sep, '/')}\n"):
        touch(where / ".git", text)
        assert feat_of(tmp_path)["status"] == "read", text


@pytest.mark.parametrize("label, text", [
    ("no blank after the colon", "gitdir:ADMIN\n"), ("capital letters", "GITDIR: ADMIN\n"), ("blanks after the path", "gitdir: ADMIN  \n"),
    ("no path", "gitdir: \n"), ("a folder that is not there", "gitdir: ADMIN-nowhere\n"), ("a second line", "gitdir: ADMIN\nmore\n"),
    ("the shared git folder, with no admin folder", "gitdir: COMMON\n")])
def test_a_linked_worktree_whose_gitfile_git_would_not_use_gives_no_answer(tmp_path, label, text):
    """The shared folder is a git folder, and git uses it: but it is not the folder that lists this worktree, and the settings it
    would read (a worktree's own file, say) could be other ones, so the reader says it cannot tell. The rest git refuses."""
    main, admin, where = linked_checkout(tmp_path)
    touch(where / ".git", text.replace("ADMIN", admin.as_posix()).replace("COMMON", (main / ".git").as_posix()))
    feat = feat_of(tmp_path)
    assert (feat["status"], feat["set"], feat["verdicts"]) == ("unknown", [], []), label
    if label.startswith("the shared"):
        assert feat["uncertain"][0].startswith("cannot tell:") and "names" in feat["uncertain"][0]
    else:
        assert feat["uncertain"][0].startswith("git would not run here as this worktree:"), label


def test_a_linked_worktree_whose_gitfile_names_another_worktrees_admin_folder_gives_no_answer(tmp_path):
    main, admin, where = linked_checkout(tmp_path)
    other = link(main, "other", tmp_path / "wts" / "other")
    touch(where / ".git", f"gitdir: {other.as_posix()}\n")
    feat = next(w for w in worktrees_of(tmp_path) if w["name"] == "feat")
    assert feat["status"] == "unknown" and feat["uncertain"][0].startswith("cannot tell:")


def test_a_linked_worktree_whose_dot_git_is_a_folder_or_is_missing_gives_no_answer(tmp_path):
    main, admin, where = linked_checkout(tmp_path)
    (where / ".git").unlink()
    (where / ".git").mkdir()
    folder = feat_of(tmp_path)
    assert folder["status"] == "unknown" and "is a folder" in folder["uncertain"][0]
    # the repository lists the folder (its gitdir names no .git suffix), and the folder has no .git: git looks above it
    (where / ".git").rmdir()
    touch(admin / "gitdir", f"{where.as_posix()}\n")
    bare_folder = feat_of(tmp_path)
    assert bare_folder["status"] == "unknown" and "has no .git" in bare_folder["uncertain"][0]


def test_a_linked_worktree_with_a_damaged_admin_folder_gives_no_answer(tmp_path):
    """Must-refuse arm."""
    main, admin, where = linked_checkout(tmp_path)
    (admin / "commondir").unlink()               # the admin folder is then no git folder: it has no objects of its own
    assert feat_of(tmp_path)["status"] == "unknown"
    touch(admin / "commondir", "../..\n")
    (admin / "HEAD").unlink()
    assert feat_of(tmp_path)["status"] == "unknown"
    touch(admin / "HEAD", "ref: refs/heads/feat\n")
    touch(admin / "commondir", " ../..\n")        # a blank first: the path is no longer the shared folder
    assert feat_of(tmp_path)["status"] == "unknown"


def test_a_linked_worktree_whose_admin_folder_is_whole_is_read(tmp_path):
    """Must-pass arm. The shared folder may be named without a final line break, with CRLF, or with a trailing slash."""
    main, admin, where = linked_checkout(tmp_path)
    for text in ("../..", "../..\r\n", "../../\n"):
        touch(admin / "commondir", text)
        assert feat_of(tmp_path)["status"] == "read", repr(text)


# ---------------------------------------------------------------- the repository's record of a worktree
def test_a_gitdir_file_of_only_a_line_break_lists_a_worktree_with_no_path(tmp_path):
    """Measured with git 2.39: it lists a worktree with an empty path and calls it prunable ('invalid gitdir file')."""
    main = repo(tmp_path / "base", "r")
    touch(main / ".git" / "worktrees" / "x" / "gitdir", "\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    (m, x) = out["repos"][0]["worktrees"]
    assert (x["name"], x["path"], x["exists"], x["status"], x["set"]) == ("x", "", False, "missing", [])
    assert "names no folder" in x["note"] and "prunable" in x["note"]
    assert kinds(out) == ["worktree-damaged"] and out["summary"]["missing"] == 1


def test_a_gitdir_file_with_a_blank_first_lists_the_path_with_the_blank_and_it_is_not_there(tmp_path):
    """Measured with git 2.39: git trims the end of the file, never its start, so ' <path>/.git' names no folder."""
    main = repo(tmp_path / "base", "r")
    here = tmp_path / "wts" / "x"
    touch(here / ".git", "gitdir: nowhere\n")
    touch(main / ".git" / "worktrees" / "x" / "gitdir", f" {here.as_posix()}/.git\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    x = out["repos"][0]["worktrees"][1]
    assert (x["path"], x["exists"], x["status"]) == (" " + here.as_posix(), False, "missing")
    assert "starts with a blank" in x["note"] and "prunable" in x["note"] and kinds(out) == ["worktree-damaged"]


def test_blanks_at_the_end_of_a_gitdir_file_are_trimmed_as_git_trims_them(tmp_path):
    main, admin, where = linked_checkout(tmp_path)
    for tail in ("\n", "\r\n", "  \n", "\t\n\n", ""):
        touch(admin / "gitdir", f"{where.as_posix()}/.git{tail}")
        feat = feat_of(tmp_path)
        assert (feat["path"], feat["exists"], feat["status"]) == (where.as_posix(), True, "read"), repr(tail)


def test_the_note_on_a_missing_worktree_says_only_what_is_true(tmp_path):
    """Its folder gone, its .git file gone with the folder still there, and no folder named at all are three things."""
    main = repo(tmp_path / "base", "r")
    link(main, "nofolder", tmp_path / "wts" / "nofolder", make=False)
    there = tmp_path / "wts" / "nogitfile"
    link(main, "nogitfile", there, make=False)
    touch(there / "README", "the folder is still here\n")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    notes = {w["name"]: w["note"] for w in out["repos"][0]["worktrees"]}
    assert notes["nofolder"] == "the worktree's folder is gone; git lists it as prunable"
    assert "folder is gone" not in notes["nogitfile"] and ".git file is gone" in notes["nogitfile"]
    assert "though its folder is still there" in notes["nogitfile"] and notes["nogitfile"].endswith("prunable")
    assert all(w["status"] == "missing" for w in out["repos"][0]["worktrees"][1:])


# ---------------------------------------------------------------- the group
def homes_file(tmp_path: Path) -> Path:
    for name in ("homes/ann", "homes/bob", "homes/cy"):
        repo(tmp_path / "base", name)
    people = {"Ann": {"home": "homes/ann", "groups": ["crew", "all"]}, "Bob": {"home": "homes/bob", "groups": ["others"]},
              "Cy": {"home": "homes/cy"}, "Di": {"groups": ["crew"]}}
    return seats(tmp_path, [{"name": "home", "path": "{home}", "kind": "repo"}], people)


def test_only_the_seats_in_the_group_are_read(tmp_path):
    out = load({"seats": str(homes_file(tmp_path)), "group": "crew"}, world(tmp_path))
    assert [(r["name"], r["seat"]) for r in out["repos"]] == [("home", "Ann")]
    assert out["group"] == "crew" and out["outside_group"] == ["Bob", "Cy"]
    assert [p["kind"] for p in out["problems"]] == ["no-home"] and "Di" in out["problems"][0]["text"]    # a member with no home
    assert out["summary"]["worktrees"] == 1


def test_every_seat_is_read_without_a_group(tmp_path):
    path = homes_file(tmp_path)
    for cfg in ({"seats": str(path)}, {"seats": str(path), "group": ""}, {"seats": str(path), "group": 3}):
        out = load(cfg, world(tmp_path))
        assert [r["seat"] for r in out["repos"]] == ["Ann", "Bob", "Cy"] and out["outside_group"] == [] and out["group"] is None, cfg
        assert ("shape" in kinds(out)) is ("group" in cfg), cfg     # I2 (round 2): a group that is no word is said


def test_a_group_is_matched_whole_and_in_the_same_case(tmp_path):
    path = homes_file(tmp_path)
    for name in ("Crew", "cre", "crew ", "all,crew"):
        out = load({"seats": str(path), "group": name}, world(tmp_path))
        assert out["repos"] == [] and out["outside_group"] == ["Ann", "Bob", "Cy", "Di"], name
    assert [r["seat"] for r in load({"seats": str(path), "group": "all"}, world(tmp_path))["repos"]] == ["Ann"]


def test_a_group_does_not_touch_the_roots_that_are_named_outright(tmp_path):
    repo(tmp_path / "base", "plain")
    path = seats(tmp_path, [{"name": "plain", "path": "plain", "kind": "repo"}, {"name": "home", "path": "{home}", "kind": "repo"}],
                 {"Ann": {"home": "plain", "groups": ["crew"]}})
    out = load({"seats": str(path), "group": "nobody"}, world(tmp_path))
    assert [(r["name"], r["seat"]) for r in out["repos"]] == [("plain", None)] and out["outside_group"] == ["Ann"]


def test_the_source_is_still_off_without_its_key_whatever_the_group(tmp_path):
    out = load({"group": "crew"}, world(tmp_path))
    assert out["off"] is True and out["repos"] == []


# ---------------------------------------------------------------- limits, and what it never does
def test_a_hook_folder_within_the_listing_limit_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(gates, "MAX_NAMES", 3)
    small = one(tmp_path / "s", config="\thooksPath = chain\n", hooks={"chain": ["a", "b"]})
    assert (small["status"], small["uncertain"]) == ("read", [])
    at = one(tmp_path / "at", config="\thooksPath = chain\n", hooks={"chain": ["a", "b", "c"]})       # exactly the limit
    assert (at["status"], at["uncertain"]) == ("read", [])
    # the hooks are named last in the folder, but inside the limit they are all seen
    last = one(tmp_path / "last", config="\thooksPath = chain\n", hooks={"chain": ["a", "pre-commit"]})
    assert last["reachable"] == ["pre-commit"]


def test_a_hook_folder_over_the_listing_limit_gives_no_answer(tmp_path, monkeypatch):
    """A listing cut short could hide the very hooks that decide the verdict (the first entries are not the hooks), so
    a verdict from it would be a guess: the worktree says it cannot tell and keeps nothing it worked out."""
    monkeypatch.setattr(gates, "MAX_NAMES", 3)
    over = one(tmp_path / "over", config="\thooksPath = chain\n", hooks={"chain": ["a", "b", "c", "d"]})   # one more
    assert (over["status"], over["set"], over["verdicts"], over["events"], over["reachable"]) == ("unknown", [], [], [], [])
    assert over["uncertain"][0].startswith("cannot tell:") and "holds more than 3 entries" in over["uncertain"][0]
    ten = one(tmp_path / "ten", config="\thooksPath = chain\n", hooks={"chain": [f"f{k}" for k in range(10)]})
    assert ten["status"] == "unknown" and ten["hooks_dir"] is None
    # a folder looked in only for hooks stranded there is held to the same limit, but it holds no fact the verdict rests
    # on, so the verdict stands and the doubt is noted (H1, round 2: it cost the verdict before)
    elsewhere = one(tmp_path / "wrong", config="\thooksPath = missing\n", hooks={"hooks": list("abcd")})
    assert elsewhere["status"] == "read" and elsewhere["set"] == ["UNCOVERED"]
    assert any("stranded hooks in" in u and "holds more than 3 entries" in u for u in elsewhere["uncertain"])


def test_a_hook_folder_that_cannot_be_listed_gives_no_answer(tmp_path, monkeypatch):
    real = os.scandir

    def refuse(p):
        if str(p).endswith("chain"):
            raise PermissionError(13, "denied", str(p))
        return real(p)

    assert one(tmp_path / "fine", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})["status"] == "read"
    monkeypatch.setattr(gates.os, "scandir", refuse)
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    assert w["status"] == "unknown" and any("could not be listed" in u for u in w["uncertain"])


def snapshot(root: Path) -> dict:
    """Every file and folder under root with its size and last change: a write, a new folder or a removal shows."""
    return {str(p): (p.is_dir(), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(root.rglob("*"))}


def test_nothing_is_written_and_nothing_is_run(tmp_path, monkeypatch):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n[extensions]\n\tworktreeConfig = true\n",
                hooks={"chain": ALL_FOUR, ".git/hooks": ["pre-push"]}, identity="A <a@x.y>\n")
    link(main, "a", tmp_path / "wts" / "a", config_worktree="[core]\n\tlongpaths = true\n")
    link(main, "gone", tmp_path / "wts" / "gone", make=False)
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = more.cfg\n")
    touch(tmp_path / "user" / "more.cfg", "[user]\n\tname = x\n")
    path = seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}])
    before = snapshot(tmp_path)

    def forbidden(*a, **k):
        raise AssertionError("the reader started a process")

    for owner, name in ((subprocess, "run"), (subprocess, "Popen"), (subprocess, "check_output"), (os, "system"),
                        (os, "popen")):
        monkeypatch.setattr(owner, name, forbidden)
    opened = []
    real_open = io.open

    def watching(file, mode="r", *a, **k):
        opened.append((str(file), mode))
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(io, "open", watching)        # pathlib opens every file through io.open
    if hasattr(pathlib, "_NormalAccessor"):          # Python 3.10: pathlib kept its own reference to io.open
        monkeypatch.setattr(pathlib._NormalAccessor, "open", staticmethod(watching))
    out = load({"seats": str(path)}, world(tmp_path))
    monkeypatch.undo()
    assert [w["status"] for w in out["repos"][0]["worktrees"]] == ["read", "read", "missing"]
    assert snapshot(tmp_path) == before
    assert len(opened) >= 6 and all(mode in ("r", "rb") for _, mode in opened)   # it did read, and only read
    # the guards fire: a changed file is seen, a write would be seen as one, and a process start is refused
    touch(main / ".identity", "A <a@x.y>\nB <b@x.y>\n")
    assert snapshot(tmp_path) != before
    (tmp_path / "new-folder").mkdir()
    assert "new-folder" in "".join(snapshot(tmp_path))
    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(AssertionError):
        subprocess.run(["git", "--version"])


def test_a_surprise_while_judging_one_worktree_is_unknown_and_the_rest_are_read(tmp_path, monkeypatch):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    link(main, "odd", tmp_path / "wts" / "odd")
    real = gates.Reader.judge

    def judge(self, seed, settings, rec, notes):
        if seed.name == "odd":
            raise ValueError("embedded null byte")
        return real(self, seed, settings, rec, notes)

    monkeypatch.setattr(gates.Reader, "judge", judge)
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    main_w, odd = out["repos"][0]["worktrees"]
    assert main_w["status"] == "read" and main_w["set"] == ["ARMED"]
    assert odd["status"] == "unknown" and odd["set"] == [] and odd["events"] == []
    assert any("ValueError" in u and "embedded null byte" in u for u in odd["uncertain"])
    assert kinds(out) == ["unexpected"] and out["summary"]["unknown"] == 1      # never silence: a problem as well


HALF_WORKED = ("hooks_path", "hooks_dir", "reachable", "identity", "set", "words", "verdicts", "events")   # a reading's fields


def test_a_surprise_half_way_through_judging_keeps_no_reading_but_keeps_its_notes(tmp_path, monkeypatch):
    """H6 (round 2): the notes judge makes are about files it read (the byte-order mark here), not half a verdict, so
    they stay when it then fails; the fields of a reading do not."""
    real = gates.Reader.identity_entries

    def late(self, top, notes):
        real(self, top, notes)                       # which notes the byte-order mark, as it would
        raise OSError("the disk went away")          # after the folder, the hooks and the event table are already worked out

    # the reading that is not interrupted fills every one of those fields, and notes the mark
    fine = one(tmp_path / "b", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="﻿A <a@x.y>\n")
    assert fine["status"] == "read" and all(fine[f] for f in HALF_WORKED)
    assert any("byte-order mark" in u for u in fine["uncertain"])
    monkeypatch.setattr(gates.Reader, "identity_entries", late)
    w = one(tmp_path, config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="﻿A <a@x.y>\n")
    assert w["status"] == "unknown"
    assert (w["hooks_path"], w["hooks_dir"], w["reachable"], w["identity"]) == (None, None, [], None)    # never half a record
    assert (w["set"], w["words"], w["verdicts"], w["events"]) == ([], [], [], [])
    assert any("OSError" in u and "the disk went away" in u for u in w["uncertain"])
    assert any("byte-order mark" in u for u in w["uncertain"])                # a note about a file that was read
    monkeypatch.setattr(gates.Reader, "identity_entries", real)
    assert one(tmp_path / "c", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")["set"] == ["ARMED"]


def test_a_worktree_with_no_answer_keeps_no_reading_whatever_stopped_it(tmp_path):
    """Whatever the reason (a refusal, an unreadable file, a folder too big to list), the fields of a reading are empty."""
    refused = one(tmp_path / "r", config="\thooksPath = chain\n\tbroken line\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    unread = one(tmp_path / "u", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    (tmp_path / "u" / "base" / "r" / ".identity").write_bytes(b"\xff\xfe")
    unread = load({"seats": str(seats(tmp_path / "u", [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path / "u")
                  )["repos"][0]["worktrees"][0]
    for w in (refused, unread):
        assert w["status"] == "unknown"
        assert (w["hooks_path"], w["hooks_dir"], w["reachable"], w["identity"]) == (None, None, [], None)
        assert (w["set"], w["words"], w["verdicts"], w["events"]) == ([], [], [], [])
        assert w["uncertain"]                       # and it says why


def test_a_root_that_cannot_be_walked_is_a_problem_and_the_others_are_still_read(tmp_path, monkeypatch):
    repo(tmp_path / "base", "a", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    repo(tmp_path / "base", "b", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR}, identity="A <a@x.y>\n")
    real = gates.find_worktrees

    def find(root, problems):
        if root.name == "a":
            raise ValueError("embedded null byte")
        return real(root, problems)

    roots = [{"name": "a", "path": "a", "kind": "repo"}, {"name": "b", "path": "b", "kind": "repo"}]
    monkeypatch.setattr(gates, "find_worktrees", find)
    out = load({"seats": str(seats(tmp_path, roots))}, world(tmp_path))
    a, b = out["repos"]
    assert a["worktrees"] == [] and [w["set"] for w in b["worktrees"]] == [["ARMED"]]
    assert kinds(out) == ["unreadable"] and "embedded null byte" in out["problems"][0]["text"]
    monkeypatch.setattr(gates, "find_worktrees", real)
    both = load({"seats": str(seats(tmp_path, roots))}, world(tmp_path))
    assert both["problems"] == [] and [r["worktrees"][0]["set"] for r in both["repos"]] == [["ARMED"], ["ARMED"]]


def test_the_files_a_worktree_read_are_listed_with_their_scope_and_who_included_them(tmp_path):
    touch(tmp_path / "user" / "more.cfg", "[user]\n\tname = x\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = more.cfg\n")
    system = touch(tmp_path / "sys" / "gitconfig", "")
    w = one(tmp_path, w=world(tmp_path, system=(system,)))
    assert [(f["scope"], f["file"].rsplit("/", 1)[-1], f["included_by"] is not None) for f in w["files"]] == [
        ("system", "gitconfig", False), ("global", ".gitconfig", False), ("global", "more.cfg", True),
        ("local", "config", False)]
    assert w["files"][2]["included_by"] == (tmp_path / "user" / ".gitconfig").as_posix()
    bare = one(tmp_path / "b")                       # no system file, no global file: only the repository's own
    assert [f["scope"] for f in bare["files"]] == ["local"]


def test_what_one_worktree_reports_of_the_files_it_read_is_its_own(tmp_path):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n")
    link(main, "a", tmp_path / "wts" / "a")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    first, second = out["repos"][0]["worktrees"]
    assert first["files"] == second["files"] and first["files"][-1]["scope"] == "local"
    first["files"][-1]["file"] = "changed by whoever holds the first answer"
    assert second["files"][-1]["file"].endswith("/.git/config")


def test_a_refused_include_is_a_problem_as_well_as_a_doubt(tmp_path):
    touch(tmp_path / "user" / "a.cfg", "[include]\n\tpath = a.cfg\n")
    touch(tmp_path / "user" / ".gitconfig", "[include]\n\tpath = a.cfg\n")
    repo(tmp_path / "base", "r")
    out = load({"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}, world(tmp_path))
    assert out["repos"][0]["worktrees"][0]["status"] == "unknown"
    assert [p["kind"] for p in out["problems"]] == ["bad-include"] and "includes it back" in out["problems"][0]["text"]


def test_program_files_is_a_place_the_system_file_may_be(tmp_path):
    installed = touch(tmp_path / "pf" / "Git" / "etc" / "gitconfig", "[core]\n\thooksPath = from-system\n")
    got = gates.this_machine({"PATH": "", "PROGRAMFILES": str(tmp_path / "pf"), "HOME": str(tmp_path / "user")})
    assert got.system == (installed,) and str(installed) in got.tried
    # the same machine without the file: the place is still tried, and nothing from it is read (a real /etc/gitconfig
    # on a machine running the tests may be, so the test does not insist the list is empty)
    bare = gates.this_machine({"PATH": "", "PROGRAMFILES": str(tmp_path / "nopf"), "HOME": str(tmp_path / "user")})
    assert installed not in bare.system and str(tmp_path / "nopf" / "Git" / "etc" / "gitconfig") in bare.tried


@pytest.mark.skipif(os.name != "nt", reason="environment names are not case-sensitive on Windows")
def test_environment_names_are_matched_without_regard_to_case_on_windows(tmp_path):
    touch(tmp_path / "xdg" / "git" / "config", "[core]\n\thooksPath = from-xdg\n")
    got = gates.this_machine({"Path": "", "Home": str(tmp_path / "user"), "Xdg_Config_Home": str(tmp_path / "xdg")})
    assert got.home == tmp_path / "user" and gates.global_files(got)[0] == tmp_path / "xdg" / "git" / "config"
    touch(tmp_path / "pf" / "Git" / "etc" / "gitconfig", "")
    assert gates.this_machine({"Path": "", "ProgramFiles": str(tmp_path / "pf")}).system == (
        tmp_path / "pf" / "Git" / "etc" / "gitconfig",)


def test_names_are_upper_cased_only_where_the_system_ignores_case():
    got = gates.normalised({"Path": "p", "HOME": "h"})
    assert got == ({"PATH": "p", "HOME": "h"} if os.name == "nt" else {"Path": "p", "HOME": "h"})


@pytest.mark.skipif(os.name != "nt", reason="the ProgramData file is Git for Windows'")
def test_the_programdata_file_is_read_first_among_the_system_files_and_said(tmp_path):
    shared = touch(tmp_path / "pd" / "Git" / "config", "[core]\n\thooksPath = from-programdata\n")
    installed = touch(tmp_path / "pf" / "Git" / "etc" / "gitconfig", "[user]\n\tname = x\n")
    m = gates.this_machine({"PATH": "", "ProgramData": str(tmp_path / "pd"), "ProgramFiles": str(tmp_path / "pf"),
                            "HOME": str(tmp_path / "user")})
    assert m.system == (shared, installed) and any("an order taken on trust" in n for n in m.notes)
    assert one(tmp_path, w=m)["hooks_path"]["value"] == "from-programdata"      # nothing read after it sets the path
    quiet = gates.this_machine({"PATH": "", "ProgramFiles": str(tmp_path / "pf"), "HOME": str(tmp_path / "user")})
    assert quiet.system == (installed,) and quiet.notes == ()


def _timeless(x):
    """An answer with every read_at taken out: the one part of it that is the time of reading, not what was read."""
    if isinstance(x, dict):
        return {k: _timeless(v) for k, v in x.items() if k != "read_at"}
    if isinstance(x, list):
        return [_timeless(v) for v in x]
    return x


def test_a_second_reading_gives_the_same_answer(tmp_path, monkeypatch):
    main = repo(tmp_path / "base", "r", config="\thooksPath = chain\n", hooks={"chain": ALL_FOUR})
    link(main, "a", tmp_path / "wts" / "a")
    cfg = {"seats": str(seats(tmp_path, [{"name": "r", "path": "r", "kind": "repo"}]))}
    # Every reading a new second, as when the two straddle a second boundary: before, the stamps alone made the two
    # answers differ, and the suite failed once on it (19:38:47Z against 19:38:48Z; the recheck of 17021c2).
    ticks = iter(range(10 ** 6))
    monkeypatch.setattr(gates, "read_at", lambda: f"2026-10-24T19:38:{next(ticks) % 60:02d}Z")
    first, second = load(cfg, world(tmp_path)), load(cfg, world(tmp_path))
    assert first["read_at"] != second["read_at"]   # the clock moved between them, every time
    assert _timeless(first) == _timeless(second)
    touch(main / ".identity", "A <a@x.y>\n")
    assert load(cfg, world(tmp_path))["repos"][0]["worktrees"][0]["set"] == ["ARMED"]   # nothing is remembered between loads
