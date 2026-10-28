"""The Gates reader's whole answer over a fixed corpus, pinned byte for byte to a file kept beside the tests.

The corpus is made by hand as the other gates tests make it, with no git: worktrees that are armed, inert, vacuous (no
.identity, and one that names nobody), open with a stranded hook, one whose hook git would not run as not executable,
settings read through an include and a conditional include, settings git refuses, a repository with several linked
worktrees (present, gone, locked, with its own settings file), a bare repository, a seat's home and a missing root.

The answer is read twice, once as on Windows and once as on POSIX, so the file is the same on every machine: the
platform flag is set by hand, and the executable check answers "no" for one hook only. The time of each read and the
temporary folder are replaced by fixed placeholders, and a path under that folder is written with forward slashes
(a problem names its file as the platform spells it); nothing else is touched.

To write the file again after a change that is meant to change the answer: SEMANTEXT_WRITE_GATES_PIN=1 pytest this file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from semantext.sources import gates
from test_sources_gates import ALL_FOUR, link, repo, seats, touch, world

PIN = Path(__file__).with_name("gates_pin_expected.json")
NAMED = "A <a@x.y>\n"


def corpus(tmp_path: Path) -> Path:
    """The fixed corpus, under tmp_path/base; returns the seats file that names it."""
    base = tmp_path / "base"
    chain = "\thooksPath = chain\n"
    repo(base, "armed", chain, {"chain": ALL_FOUR}, NAMED)
    repo(base, "inert")
    repo(base, "vacuous", chain, {"chain": ALL_FOUR})                         # no .identity at all
    repo(base, "nobody", chain, {"chain": ALL_FOUR}, "# a comment, and no one\n\n")
    repo(base, "stranded", chain, {"chain": ["pre-commit"], ".git/hooks": ["pre-push", "commit-msg"]}, NAMED)
    repo(base, "noexec", chain, {"chain": ALL_FOUR}, NAMED)                   # pre-push here is not executable
    inc = repo(base, "includes", "[include]\n\tpath = extra.cfg\n[includeIf \"gitdir:elsewhere/\"]\n\tpath = cond.cfg\n",
               {"chain": ALL_FOUR}, NAMED)
    touch(inc / ".git" / "extra.cfg", "[core]\n\thooksPath = chain\n")
    touch(inc / ".git" / "cond.cfg", "[user]\n\tname = Someone\n")
    repo(base, "refused", "\tbare = maybe\n", {"chain": ALL_FOUR}, NAMED)
    repo(base, "badline", "this is not a setting\n")
    multi = repo(base, "multi", "[extensions]\n\tworktreeConfig = true\n", {".git/hooks": ALL_FOUR}, NAMED)
    touch(base / "multi-a" / ".identity", NAMED)
    link(multi, "a", base / "multi-a")
    link(multi, "b", base / "multi-b", config_worktree=f"[core]\n{chain}")
    touch(base / "multi-b" / ".identity", NAMED)
    for n in ALL_FOUR:
        touch(base / "multi-b" / "chain" / n, "#!/bin/sh\n")
    link(multi, "gone", base / "multi-gone", make=False)
    touch(link(multi, "locked", base / "multi-locked", make=False) / "locked", "")
    (base / "multi-nogitfile").mkdir(parents=True)
    link(multi, "nogitfile", base / "multi-nogitfile", make=False)
    bare = base / "bare.git"
    touch(bare / "config", "[core]\n\trepositoryformatversion = 0\n\tbare = true\n")
    touch(bare / "HEAD", "ref: refs/heads/main\n")
    (bare / "objects").mkdir(parents=True)
    (bare / "refs").mkdir(parents=True)
    repo(base / "homes", "s1", chain, {"chain": ALL_FOUR[:2]}, NAMED)
    names = ["armed", "inert", "vacuous", "nobody", "stranded", "noexec", "includes", "refused", "badline", "multi",
             "bare.git", "absent"]
    roots = [{"name": n, "path": n, "kind": "repo"} for n in names]
    roots += [{"name": "home", "path": "{home}", "kind": "repo"}, {"name": "notes", "path": "notes", "kind": "folder"}]
    return seats(tmp_path, roots, {"s1": {"home": "homes/s1"}, "s2": {}})


def placeheld(value, spellings: list):
    """The answer with every spelling of the temporary folder made <TMP> and every read_at made <READ_AT>."""
    if isinstance(value, dict):
        return {k: "<READ_AT>" if k == "read_at" else placeheld(v, spellings) for k, v in value.items()}
    if isinstance(value, list):
        return [placeheld(v, spellings) for v in value]
    if isinstance(value, str):
        for s in spellings:
            value = value.replace(s, "<TMP>")
        if "<TMP>" in value:          # a problem's source is the path as the platform spells it: one spelling here
            value = value.replace("\\", "/")
    return value


def answer(tmp_path: Path, monkeypatch) -> str:
    path = corpus(tmp_path)
    real = os.access
    monkeypatch.setattr(gates.os, "access",
                        lambda p, mode: False if str(p).replace("\\", "/").endswith("noexec/chain/pre-push") else real(p, mode))
    out = {}
    for name, flag in (("windows", True), ("posix", False)):
        monkeypatch.setattr(gates, "WINDOWS", flag)
        out[name] = gates.load({"seats": str(path)}, world(tmp_path))
    monkeypatch.undo()
    spellings = {str(tmp_path), tmp_path.as_posix(), str(tmp_path.resolve()), tmp_path.resolve().as_posix()}
    held = placeheld(out, sorted(spellings, key=len, reverse=True))
    return json.dumps(held, sort_keys=True, indent=1, ensure_ascii=True) + "\n"


def test_the_whole_answer_over_the_corpus_is_unchanged(tmp_path, monkeypatch):
    got = answer(tmp_path, monkeypatch)
    if os.environ.get("SEMANTEXT_WRITE_GATES_PIN"):
        PIN.write_bytes(got.encode("ascii"))
    expected = PIN.read_bytes().replace(b"\r\n", b"\n")      # a checkout may turn the file's line breaks into CRLF
    assert got.encode("ascii") == expected


def test_the_pin_can_fail(tmp_path, monkeypatch):
    """Must-refuse: one hook taken away from the corpus changes the answer, so the pin is not a check that always passes."""
    got = json.loads(answer(tmp_path / "a", monkeypatch))
    corpus(tmp_path / "b")
    (tmp_path / "b" / "base" / "armed" / "chain" / "pre-push").unlink()
    monkeypatch.setattr(gates, "WINDOWS", True)
    changed = gates.load({"seats": str(tmp_path / "b" / "roots.json")}, world(tmp_path / "b"))
    assert got["windows"]["repos"][0]["worktrees"][0]["set"] == ["ARMED"]
    assert changed["repos"][0]["worktrees"][0]["set"] == ["UNCOVERED"]


def test_the_corpus_covers_what_it_says(tmp_path, monkeypatch):
    """Each case the corpus names is in the answer, so a fixture that silently stopped making its case is caught."""
    got = json.loads(answer(tmp_path, monkeypatch))
    for side in ("windows", "posix"):
        trees = {r["name"] + ":" + str(w["name"]): w for r in got[side]["repos"] for w in r["worktrees"]}
        assert trees["armed:None"]["set"] == ["ARMED"] and trees["inert:None"]["set"] == ["INERT"]
        assert trees["vacuous:None"]["set"] == ["VACUOUS"] and trees["vacuous:None"]["identity"]["present"] is False
        assert trees["nobody:None"]["set"] == ["VACUOUS"] and trees["nobody:None"]["identity"]["present"] is True
        assert trees["stranded:None"]["verdicts"][0]["stranded"]
        assert trees["includes:None"]["hooks_path"]["via"] and trees["includes:None"]["set"] == ["ARMED"]
        assert trees["refused:None"]["status"] == "unknown" and trees["badline:None"]["status"] == "unknown"
        assert {trees[f"multi:{n}"]["status"] for n in ("gone", "locked", "nogitfile")} == {"missing"}
        assert trees["multi:b"]["hooks_path"]["scope"] == "worktree" and trees["bare.git:None"]["status"] == "bare"
        assert "missing-root" in [p["kind"] for p in got[side]["problems"]]
    assert got["posix"]["repos"][5]["worktrees"][0]["not_executable"] == ["pre-push"]
    assert got["windows"]["repos"][5]["worktrees"][0]["not_executable"] == []
