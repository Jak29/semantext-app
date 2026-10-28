"""Evidence, way 2 (git index), against the audit's name lists (audit_names): a file the project's index does not
track is refused whatever its name, with the name belt off, and every honest name the index tracks is evidence.

At e36d0c0 the same lists, placed in a project bound to the agent, measured 34 of 89 secret-shaped names digested and
22 of 60 honest names refused (password_policy.md, keys.py, key.md among them); the refusing arm here and the tracked
honest arm both fail there. The index is written in pure Python (gitindex_writer) and, where git is installed,
cross-checked against the indexes git itself writes. Every test has a must-pass and a must-refuse arm.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

import audit_names as K
from gitindex_writer import index_bytes, write_index
from semantext.sources import change, evidence, evidence_gitindex as gi, gates, view
from semantext.sources.gates import World as GitWorld
from test_v2_view import World, append, touch

WINDOWS = sys.platform == "win32"
UNTRACKED = "git does not track it"


@pytest.fixture(autouse=True)
def fresh_cache():
    gi._CACHE.clear()
    change._CACHE.clear()
    yield
    gi._CACHE.clear()


@pytest.fixture
def lab(tmp_path):
    top = tmp_path / "lab"
    (top / ".git").mkdir(parents=True)
    return top


def pol(*roots):
    return gi.for_seat("Alder", {}, [str(r) for r in roots])


def put(folder, rel, text=None):
    return touch(folder.joinpath(*rel.split("/")), text or f"x {rel}")


def fp(path, policy) -> dict:
    return change.fingerprint([str(path)], policy)


def test_the_page_uses_this_way_and_the_name_belt_is_off():
    assert view.evidence_way is gi and gi.NAME_BELT is False
    assert evidence.way() is gi and evidence.way(evidence.DEFAULT_WAY) is view.evidence_way   # one default, not two


def test_a_list_of_roots_is_read_through_the_pages_way(lab):
    """The public interface (semantext.api.fingerprint) takes the filer's roots as a list: it gets the page's digest
    for a tracked file, and an untracked one is refused as the page refuses it, never read with no policy."""
    from semantext import api
    write_index(lab, ["notes.md"])
    kept, loose = put(lab, "notes.md"), put(lab, "loose.md")
    said = fp(kept, pol(lab))["digest"]
    assert said and api.fingerprint([str(kept)], [str(lab)])["digest"] == said         # must pass: the page's digest
    assert change.fingerprint([str(kept)], (str(lab),))["digest"] == said
    got = api.fingerprint([str(loose)], [str(lab)])                                    # must refuse: untracked
    assert got["digest"] is None and UNTRACKED in got["why"]
    assert change.fingerprint([str(kept)], [])["digest"] is None                       # no roots: nothing is read
    assert change.freshness({"files": [str(kept)], "digest": said}, [str(lab)])["state"] == "current"


# ---------------------------------------------------------------- acceptance
def test_every_audit_name_the_index_does_not_track_is_refused(lab):
    """Every name placed in the project and left out of its index: unknown, whatever it is called."""
    write_index(lab, [f"h/{n}" for n in K.HONEST])
    p = pol(lab)
    for name in K.EVERY:
        got = fp(put(lab, f"s/{name}"), p)
        assert got["digest"] is None and UNTRACKED in got["why"], (name, got)


BELTED_HONEST: set = set()   # the short belt's cost among the audit's honest names: none since f8dfae1's audit
                             # (credentials_policy.md was refused by credentials* until then)


def test_every_honest_audit_name_the_index_tracks_is_evidence_but_the_few_the_short_belt_names(lab):
    write_index(lab, [f"h/{n}" for n in K.HONEST])
    p = pol(lab)
    assert {n for n in K.HONEST if gi.tracked_belt([n])} == BELTED_HONEST    # the short belt's stated cost
    for name in K.HONEST:   # hidden names and every kind included: e36d0c0 refused 22 of these
        got = fp(put(lab, f"h/{name}"), p)
        if name in BELTED_HONEST:
            assert got["digest"] is None and "named like a secret" in got["why"], name
        else:
            assert got["digest"], name
    # must refuse: the same honest names, untracked, are unknown (the cost of this way: a new note waits for git add)
    for name in ("password_policy.md", "keys.py", "LICENSE"):
        got = fp(put(lab, f"new/{name}"), p)
        assert got["digest"] is None and UNTRACKED in got["why"], name


@pytest.mark.parametrize("name", [".env", "id_rsa", ".env.json", "wallet.json", "wallet_main.txt", "server.pem",
                                  "tls.key", "github_token.json", "api-token.txt", "token.json", "bot.token",
                                  "credentials.json", "conf/.env.local"])
def test_the_short_belt_refuses_a_tracked_secret_name_with_its_reason(lab, name):
    """Audit of fb1720d, protection finding 2: `git add -f .env` lists .env, so a few names are refused when listed."""
    honest = ["keys.py", "password_policy.md", "key.md", "tokenizer.py", "tokens.md", "token_budget.md", "wallets.md",
              "walleted.md"]
    write_index(lab, [name, *honest])
    p = pol(lab)
    got = fp(put(lab, name), p)
    assert got["digest"] is None and "named like a secret" in got["why"] and "git tracks it" in got["why"]
    for h in honest:                                                     # must pass: tracked honest names
        assert fp(put(lab, h), p)["digest"], h


def test_every_audit_secret_name_the_index_tracks_is_refused_by_the_short_belt(lab):
    """Audit of f8dfae1, protection finding 1: of its 89 secret-shaped names tracked, 16 were refused and 73 digested.
    Now every one is refused, by name, and every honest one tracked beside them is evidence."""
    write_index(lab, [*(f"s/{n}" for n in K.SECRET), *(f"h/{n}" for n in K.HONEST)])
    p = pol(lab)
    digested = [n for n in K.SECRET if fp(put(lab, f"s/{n}"), p)["digest"]]
    assert digested == [] and len(K.SECRET) == 89
    refused = [n for n in K.HONEST if not fp(put(lab, f"h/{n}"), p)["digest"]]   # must pass: the honest names
    assert refused == [] and len(K.HONEST) == 60


@pytest.mark.parametrize("name", ["id_ed25519", "id_ed25519.pub", "id_ecdsa", "id_dsa", ".npmrc", ".netrc", ".pgpass",
                                  ".git-credentials", ".ssh/config", ".ssh/id_ed25519", ".aws/config", ".gnupg/x.gpg",
                                  "oauth.json", "secret.json", "secrets.yaml", "token", "tokens.json",
                                  "token_backup.json", "wallet", "mywallet.json", "service-account.json",
                                  "client_secret.json", "api_key.txt", "store.p12", "cert.pfx", "db.kdbx",
                                  "password.txt", "auth.json", "env.json", "deploy/credentials_prod.json"])
def test_the_names_the_audit_found_digesting_are_refused(lab, name):
    """Audit of f8dfae1: these named cases digested at f8dfae1, tracked with `git add -f`."""
    honest = ["tokenizer.py", "tokens.md", "wallets.md", "keys.py", "key.md", "password_policy.md", "auth.md",
              "env.md", "id_mapping.py", "credentials_policy.md", "token_budget.md", "keymap.json"]
    write_index(lab, [name, *honest])
    p = pol(lab)
    got = fp(put(lab, name), p)
    assert got["digest"] is None and "named like a secret" in got["why"], got
    for h in honest:                                                     # must pass: tracked honest names
        assert fp(put(lab, h), p)["digest"], h


def test_a_tracked_secret_under_another_name_is_evidence_as_the_docstring_states(lab):
    """The trade-off, stated in evidence_gitindex: a listed secret under a name the short belt does not name is
    evidence, like any listed file; this policy chooses relevant files, it is not a defence."""
    write_index(lab, ["deploy_config.json"])
    p = pol(lab)
    assert fp(put(lab, "deploy_config.json"), p)["digest"]
    got = fp(put(lab, "deploy_notes.json"), p)                 # must refuse: one beside it that is not tracked
    assert got["digest"] is None and UNTRACKED in got["why"]


SHA1, SHA256 = "1" * 40, "f" * 64


@pytest.mark.parametrize("head, refs, admitted", [
    (None, {}, False), ("hello\n", {}, False), ("ref: \n", {}, False), ("a" * 39 + "\n", {}, False),
    ("a" * 41 + "\n", {}, False), ("A" * 40 + "\n", {}, False),
    (SHA1 + "\n", {}, True), (SHA256, {}, True),                                     # detached: an id is enough
    ("ref: refs/heads/main\n", {"refs/heads/main": SHA1 + "\n"}, True),              # a loose ref
    ("ref: refs/heads/main\n", {"refs/heads/main": SHA256}, True),
    ("ref: refs/heads/main\n", {"packed-refs": f"# pack-refs with: peeled fully-peeled sorted\n"
                                               f"{SHA1} refs/heads/dev\n{SHA1} refs/heads/main\n^{SHA1}\n"}, True),
    ("ref: refs/heads/main\r\n", {"packed-refs": f"{SHA1} refs/heads/main\r\n"}, True),
    ("ref: refs/heads/main\n", {}, False),                                           # the ref does not exist
    ("ref: refs/heads/nope-nothing\n", {"refs/heads/main": SHA1 + "\n"}, False),
    ("ref: refs/heads/main\n", {"packed-refs": ""}, False),                          # an empty packed-refs
    ("ref: refs/heads/main\n", {"packed-refs": f"{SHA1} refs/heads/main-old\n"}, False),
    ("ref: refs/heads/main\n", {"packed-refs": f"^{SHA1} refs/heads/main\n"}, False),
    ("ref: refs/heads/main\n", {"refs/heads/main": "not an id\n"}, False),
    ("ref: refs/heads/main\n", {"refs/heads/main": "ref: refs/heads/dev\n", "refs/heads/dev": SHA1}, False),
    ("ref: refs/../../x\n", {"x": SHA1}, False),                                     # `..` in the name
    ("ref: refs/heads/../main\n", {"refs/main": SHA1}, False),
    ("ref: refs/heads/.hidden\n", {"refs/heads/.hidden": SHA1}, False),
    ("ref: refs/heads/x.lock\n", {"refs/heads/x.lock": SHA1}, False),
    ("ref: refs/heads/a\\b\n", {}, False),
], ids=["no-head", "not-a-ref", "empty-ref", "short-id", "long-id", "upper-id", "sha1-id", "sha256-id",
        "loose-sha1", "loose-sha256", "packed", "packed-crlf", "missing-ref", "other-ref-only", "empty-packed",
        "packed-other", "packed-peeled-only", "loose-not-an-id", "loose-symref", "dotdot", "dotdot-inner",
        "dot-part", "lock", "backslash"])
def test_only_a_real_repository_is_read(tmp_path, head, refs, admitted):
    """Audit of fb1720d: a hand-built .git/index in a plain folder admitted anything beside it. Audit of f8dfae1,
    protection finding 2: a HEAD naming a ref that does not exist was admitted. HEAD must hold a commit id, or name a
    ref that a loose ref file or a packed-refs line holds."""
    top = tmp_path / "plain"
    write_index(top, ["a.md"], head=None)
    if head is not None:
        (top / ".git" / "HEAD").write_bytes(head.encode("ascii"))
    for rel, text in refs.items():
        touch(top / ".git" / rel, text)
    got = fp(put(top, "a.md"), pol(top))
    if admitted:
        assert got["digest"], got
    else:
        assert got["digest"] is None and "HEAD" in got["why"] and "not a repository" in got["why"], got


def test_a_ref_that_is_a_folder_or_a_link_is_not_read(tmp_path):
    top = tmp_path / "plain"
    write_index(top, ["a.md"], ref=None)
    (top / ".git" / "refs" / "heads" / "main").mkdir(parents=True)                # a folder where the ref should be
    got = fp(put(top, "a.md"), pol(top))
    assert got["digest"] is None and "ref is not a plain file" in got["why"], got
    (top / ".git" / "refs" / "heads" / "main").rmdir()
    touch(top / ".git" / "refs" / "heads" / "main", SHA1 + "\n")                  # must pass: the ref as git writes it
    gi._CACHE.clear()
    change._CACHE.clear()
    assert fp(top / "a.md", pol(top))["digest"]


def test_a_packed_refs_read_counts_against_the_budget(tmp_path):
    top = tmp_path / "plain"
    write_index(top, ["a.md"], ref=None)
    packed = f"{SHA1} refs/heads/main\n"
    touch(top / ".git" / "packed-refs", packed)
    f, p = put(top, "a.md"), pol(top)
    both = os.path.getsize(top / ".git" / "index") + os.path.getsize(top / ".git" / "packed-refs")
    assert p.refuse(str(f), os.path.realpath(f), str(top), {"left": both - 1}) == evidence.OVER_BUDGET
    budget = {"left": both}
    assert p.refuse(str(f), os.path.realpath(f), str(top), budget) is None                # must pass: just enough
    assert budget["left"] == 0


def test_a_home_below_its_repository_top_is_read_when_the_top_is_a_named_root(tmp_path):
    """Audit of fb1720d, protection finding 3: seat folders inside one shared repository."""
    top = tmp_path / "shared"
    write_index(top, ["seat-a/notes.md", "seat-b/notes.md"])
    home = top / "seat-a"
    mine, loose = put(home, "notes.md"), put(home, "loose.md")
    p = pol(home, top)
    assert p.refuse(str(mine), os.path.realpath(mine), str(home)) is None          # read from the home's own root
    assert UNTRACKED in p.refuse(str(loose), os.path.realpath(loose), str(home))   # only what the index lists
    assert fp(mine, p)["digest"]
    # must refuse: the top is above every root, so it is never read
    alone = pol(home)
    got = fp(mine, alone)
    assert got["digest"] is None and "no git repository whose top is inside its roots" in got["why"]
    assert "no git repository" in alone.refuse(str(mine), os.path.realpath(mine), str(home))


def test_on_the_page_a_tracked_file_is_current_and_an_untracked_one_unknown(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "git-user"
    user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    lab_top = w.base / "lab"
    write_index(lab_top, ["rules/short.md"])
    rule = put(lab_top, "rules/short.md", "Keep answers short.")
    loose = put(lab_top, "rules/oauth.json", "{}")                     # evidence at e36d0c0 (a bound project)
    said = change.fingerprint([str(rule)], pol(w.base / "alder", lab_top))["digest"]
    touch(w.base / "alder" / "changes.jsonl")
    line = {"at": "2026-10-05T10:00:00Z", "kind": "change", "title": "t", "why": "w", "component": "rule",
            "hypothesis": "h", "undo": {"commit": "abc1234"}}
    append(w.base / "alder" / "changes.jsonl", {**line, "id": "A-20261005-100000", "evidence": {"files": [str(rule)],
                                                                                              "digest": said}},
           {**line, "id": "A-20261005-100001", "evidence": {"files": [str(loose)], "digest": "0" * 64}})
    got = {c["id"]: c["change"]["freshness"] for c in view.answer("waiting")["change_records"]}
    assert got["A-20261005-100000"]["state"] == "current"
    assert got["A-20261005-100001"]["state"] == "unknown" and UNTRACKED in got["A-20261005-100001"]["why"]


# ---------------------------------------------------------------- the index, read without git
@pytest.mark.parametrize("version", [2, 3, 4])
@pytest.mark.parametrize("hash_", [20, 32])
def test_each_version_and_hash_is_read(lab, version, hash_):
    paths = ["a.md", "deep/er/notes.md", "deep/er/notes2.md", "deep/x.py", "z" * 300 + ".md"]
    names = gi.tracked(index_bytes(paths, version=version, hash=hash_))
    assert sorted(n.decode() for n in names) == sorted(paths)
    assert gi.tracked(index_bytes(paths, version=version, hash=hash_, trailer="zero"))   # index.skipHash
    with pytest.raises(gi._Bad, match="checksum"):                                         # must refuse
        gi.tracked(index_bytes(paths, version=version, hash=hash_, trailer="bad"))


def test_a_name_longer_than_the_flags_can_say_is_read_to_its_nul():
    long = "d/" + "n" * 5000 + ".md"
    assert [n.decode() for n in gi.tracked(index_bytes([long]))] == [long]
    with pytest.raises(gi._Bad, match="not as long"):                                      # must refuse: a lie
        gi.tracked(index_bytes([("a.md", {"name_len": 7})]))


def test_only_ordinary_files_at_stage_0_count():
    entries = ["plain.md", ("exec.sh", {"mode": 0o100755}), ("link.md", {"mode": 0o120000}),
               ("sub", {"mode": 0o160000}), ("theirs.md", {"stage": 2}), ("ita.md", {"ext": 0x2000}),
               ("sparse.md", {"ext": 0x4000})]
    got = sorted(n.decode() for n in gi.tracked(index_bytes(entries, version=3)))
    assert got == ["exec.sh", "plain.md"]
    with pytest.raises(gi._Bad, match="version 2"):                                       # extended flags need v3
        gi.tracked(index_bytes([("ita.md", {"ext": 0x2000})], version=2))


@pytest.mark.parametrize("data, why", [
    (b"", "no DIRC"), (b"XXXX" + bytes(40), "no DIRC"),
    (index_bytes(["a.md"], version=5), "version 5"),
    (index_bytes(["a.md", "b.md"], count=3), "ends inside"),
    (index_bytes(["a.md", ("dir", {"mode": 0o040000})]), "sparse"),
    (index_bytes(["a.md"], extensions=[(b"sdir", b"")]), "sparse"),
    (index_bytes(["a.md"], extensions=[(b"link", bytes(20))]), "split index"),
])
def test_an_index_that_cannot_be_read_whole_is_refused(data, why):
    with pytest.raises(gi._Bad, match=why):
        gi.tracked(data)
    assert gi.tracked(index_bytes(["a.md"], extensions=[(b"TREE", b"0 1 x"), (b"UNTR", b"")]))   # must pass


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
@pytest.mark.parametrize("version", ["2", "3", "4"])
def test_the_reader_agrees_with_the_index_git_writes(tmp_path, version):
    """Git writes the index; the reader must find exactly what `git ls-files -s` lists at stage 0 as a file."""
    top = tmp_path / "repo"
    for rel in ("a.md", "deep/b.py", "deep/deeper/c.txt", "LICENSE", ".gitignore", "x y.md"):
        put(top, rel)
    put(top, "untracked.md")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}

    def git(*args):
        return subprocess.run(["git", "-C", str(top), *args], check=True, capture_output=True, env=env).stdout

    git("init", "-q")
    git("add", "a.md", "deep", "LICENSE", ".gitignore", "x y.md")
    p = pol(top)
    got = fp(top / "a.md", p)                              # must refuse: a branch with no commit yet names no ref
    assert got["digest"] is None and "no ref file or packed-refs line" in got["why"], got
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c")
    git("add", "-N", "untracked.md")                       # intent to add: listed by git, not tracked content
    git("update-index", "--index-version", version)
    listed = {line.split("\t", 1)[1] for line in git("ls-files", "-s").decode().splitlines() if line.startswith("100")}
    assert "untracked.md" in listed                       # git lists an intent-to-add entry (with the empty blob's id)
    got = {n.decode() for n in gi.tracked((top / ".git" / "index").read_bytes())}
    assert got == listed - {"untracked.md"} and "deep/deeper/c.txt" in got and "x y.md" in got
    change._CACHE.clear()
    assert fp(top / "deep" / "deeper" / "c.txt", p)["digest"]
    assert UNTRACKED in fp(top / "untracked.md", p)["why"]
    git("pack-refs", "--all")                              # the branch now lives only in packed-refs
    branch = (top / ".git" / "HEAD").read_text().split("ref: ", 1)[1].strip()
    assert not (top / ".git").joinpath(*branch.split("/")).exists()
    assert f" {branch}" in (top / ".git" / "packed-refs").read_text()
    change._CACHE.clear()
    assert fp(top / "a.md", p)["digest"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed here")
def test_in_a_real_repository_every_audit_secret_name_added_with_force_is_refused(tmp_path):
    """The audit's own measure (f8dfae1: a real repository, `git add -f`): 16 of 89 secret names refused and 73
    digested, 1 of 60 honest names refused. Now 89 of 89 and 0 of 60."""
    top = tmp_path / "repo"
    for n in K.SECRET:
        put(top, f"s/{n}")
    for n in K.HONEST:
        put(top, f"h/{n}")
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}

    def git(*args):
        return subprocess.run(["git", "-C", str(top), *args], check=True, capture_output=True, env=env).stdout

    git("init", "-q")
    git("add", "-f", "s", "h")
    git("-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c")
    p = pol(top)
    digested = [n for n in K.SECRET if fp(top.joinpath("s", *n.split("/")), p)["digest"]]
    refused = [n for n in K.HONEST if not fp(top.joinpath("h", *n.split("/")), p)["digest"]]
    assert (len(K.SECRET) - len(digested), digested) == (89, [])
    assert (len(refused), refused) == (0, [])


# ---------------------------------------------------------------- the repository, found without following anything
def test_the_nearest_repository_holds_its_files(lab):
    write_index(lab, ["inner/x.md", "y.md"])
    inner = lab / "inner"
    write_index(inner, ["z.md"])
    p = pol(lab)
    got = fp(put(inner, "x.md"), p)                                   # the outer index lists it, but inner/ is its own
    assert got["digest"] is None and UNTRACKED in got["why"]
    assert fp(put(inner, "z.md"), p)["digest"] and fp(put(lab, "y.md"), p)["digest"]    # must pass


def test_no_repository_at_or_below_the_root_is_unknown(tmp_path):
    root = tmp_path / "plain"
    f = put(root, "notes/a.md")
    got = fp(f, pol(root))
    assert got["digest"] is None and "no git repository" in got["why"]
    # must refuse: a repository whose top is ABOVE the root is not searched for (the root is a home inside it)
    write_index(tmp_path, ["plain/notes/a.md"])
    got = fp(f, pol(root))
    assert got["digest"] is None and "no git repository" in got["why"]
    assert fp(f, pol(tmp_path))["digest"]                                                  # must pass: from its top


def test_a_git_file_a_missing_index_and_a_linked_index_are_unknown(tmp_path):
    wt = tmp_path / "worktree"
    touch(wt / ".git", "gitdir: C:/elsewhere/.git/worktrees/wt\n")       # a linked worktree's .git is a file
    got = fp(put(wt, "a.md"), pol(wt))
    assert got["digest"] is None and ".git is a file" in got["why"]
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    touch(empty / ".git" / "HEAD", "ref: refs/heads/main\n")             # a real repository, with no index yet
    touch(empty / ".git" / "refs" / "heads" / "main", SHA1 + "\n")
    got = fp(put(empty, "a.md"), pol(empty))
    assert got["digest"] is None and "no index" in got["why"]
    hard = tmp_path / "hard"
    real = write_index(tmp_path / "other", ["a.md"])
    (hard / ".git").mkdir(parents=True)
    touch(hard / ".git" / "HEAD", "ref: refs/heads/main\n")
    touch(hard / ".git" / "refs" / "heads" / "main", SHA1 + "\n")
    try:
        os.link(real, hard / ".git" / "index")
    except OSError as e:
        pytest.skip(f"no hard link here: {e}")
    got = fp(put(hard, "a.md"), pol(hard))
    assert got["digest"] is None and "hard link" in got["why"]


@pytest.mark.skipif(not WINDOWS, reason="junctions are a Windows thing")
def test_a_git_folder_that_is_a_junction_is_not_followed(tmp_path):
    import _winapi
    elsewhere = tmp_path / "elsewhere"
    write_index(elsewhere, ["a.md"])
    top = tmp_path / "top"
    top.mkdir()
    _winapi.CreateJunction(str(elsewhere / ".git"), str(top / ".git"))
    got = fp(put(top, "a.md"), pol(top))
    assert got["digest"] is None and ".git is a link" in got["why"]


@pytest.mark.skipif(not WINDOWS, reason="case-blind paths are the Windows default")
def test_on_windows_a_path_matches_its_entry_without_case(lab):
    write_index(lab, ["Notes/Plan.md"])
    put(lab, "Notes/Plan.md")
    assert fp(lab / "notes" / "plan.md", pol(lab))["digest"]


# ---------------------------------------------------------------- cost: the cache and the read budget
def test_the_index_is_read_once_within_its_lifetime_and_counts_against_the_budget(lab, monkeypatch):
    index = write_index(lab, ["a.md", "b.md"])
    a, b = put(lab, "a.md", "aa"), put(lab, "b.md", "bb")
    size = index.stat().st_size
    budget = {"left": size - 1}
    got = change.fingerprint([str(a)], pol(lab), budget)                  # must refuse: the index alone is over it
    assert got == {"digest": None, "why": evidence.OVER_BUDGET}
    budget = {"left": size + 4}
    assert change.fingerprint([str(a)], pol(lab), budget)["digest"] and budget["left"] == 2
    assert change.fingerprint([str(b)], pol(lab), budget)["digest"] and budget["left"] == 0   # the index is cached
    clock = [time_now() + gi.CACHE_S + 1]
    monkeypatch.setattr(gi.time, "monotonic", lambda: clock[0])
    change._CACHE.clear()
    got = change.fingerprint([str(b)], pol(lab), {"left": 2})              # its lifetime is over: read again
    assert got == {"digest": None, "why": evidence.OVER_BUDGET}


def time_now() -> float:
    return gi.time.monotonic()


def test_an_index_that_changes_is_read_again(lab):
    write_index(lab, ["a.md"])
    a, b = put(lab, "a.md"), put(lab, "b.md")
    p = pol(lab)
    assert fp(a, p)["digest"] and UNTRACKED in fp(b, p)["why"]
    write_index(lab, ["a.md", "b.md"])                                     # git add b.md: a new index, a new key
    assert fp(b, p)["digest"]


# ---------------------------------------------------------------- the belt, when switched on
def test_the_name_belt_when_switched_on_refuses_tracked_secret_names_and_honest_ones_too(lab, monkeypatch):
    write_index(lab, ["vault.json", "password_policy.md", "monkey.md"])
    monkeypatch.setattr(gi, "NAME_BELT", True)
    p = pol(lab)
    got = fp(put(lab, "vault.json"), p)                                     # the full belt names it; the short one not
    assert got["digest"] is None and "named like a secret" in got["why"]
    assert fp(put(lab, "password_policy.md"), p)["digest"] is None          # its cost, and why it is off
    assert fp(put(lab, "monkey.md"), p)["digest"]                           # must pass
