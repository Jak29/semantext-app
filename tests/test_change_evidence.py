"""The change card's evidence digest, attacked (the audit of 8807d40: an intermediate junction, a hard link, an
alternate stream, secret names, short names, missing roots), and the scoring of an undo. Every attack here was digested, or scored, by 8807d40; each now has a refusing arm beside a
passing one. Junctions are made with _winapi.CreateJunction (Windows, no privilege needed); a test that cannot make its
link or its short name on this machine is skipped, never passed.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

from semantext.sources import change

WINDOWS = sys.platform == "win32"


def junction(link: Path, target: Path) -> None:
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


@pytest.fixture
def area(tmp_path):
    root, outside = tmp_path / "project", tmp_path / "outside"
    for p in (root, outside, root / "sub"):
        p.mkdir()
    (outside / "report.txt").write_text("TOP-SECRET", encoding="utf-8")
    (root / "plain.txt").write_text("hello", encoding="utf-8")
    (root / "sub" / "notes.txt").write_text("notes", encoding="utf-8")
    return root, outside


def fp(path, root) -> dict:
    # the root as compared (case-folded), the way 8807d40's view passed it, so an attack is measured on its own
    return change.fingerprint([str(path)], [os.path.normcase(str(root))])


def test_a_plain_file_inside_is_digested_and_one_outside_is_not(area):
    root, outside = area
    assert fp(root / "plain.txt", root)["digest"] and fp(root / "sub" / "notes.txt", root)["digest"]   # must pass
    assert fp(outside / "report.txt", root)["digest"] is None
    assert fp(root / ".." / "outside" / "report.txt", root)["digest"] is None
    with pytest.raises(TypeError):
        change.fingerprint([str(root / "plain.txt")])          # roots are required: there is no default to fall back on
    assert change.fingerprint([str(outside / "report.txt")], [])["digest"] is None


@pytest.mark.skipif(not WINDOWS, reason="junctions are a Windows thing")
def test_a_junction_in_the_middle_of_a_path_is_never_followed(area):
    root, outside = area
    junction(root / "bridge", outside)
    got = fp(root / "bridge" / "report.txt", root)              # 8807d40: digested, an oracle on the outside file
    assert got["digest"] is None and "link or junction" in got["why"]
    assert fp(root / "bridge", root)["digest"] is None
    # must pass: a root that is itself reached through a junction (as a synced folder can be) still reads inside
    via = root.parent / "via"
    junction(via, root)
    assert fp(via / "sub" / "notes.txt", via)["digest"] == fp(via / "sub" / "notes.txt", via)["digest"] is not None


def test_a_hard_link_is_never_read(area):
    root, outside = area
    try:
        os.link(outside / "report.txt", root / "hardlink.txt")
    except OSError as e:
        pytest.skip(f"no hard link here: {e}")
    got = fp(root / "hardlink.txt", root)                        # 8807d40: digested the outside file's bytes
    assert got["digest"] is None and "hard link" in got["why"]


@pytest.mark.skipif(not WINDOWS, reason="alternate data streams are NTFS")
def test_an_alternate_stream_is_never_read(area):
    root, _ = area
    try:
        with open(str(root / "plain.txt") + ":hidden", "w", encoding="utf-8") as f:   # the test makes its own stream
            f.write("stream bytes")
    except OSError as e:
        pytest.skip(f"no alternate stream here: {e}")
    got = fp(str(root / "plain.txt") + ":hidden", root)          # 8807d40: digested the stream
    assert got["digest"] is None and "colon" in got["why"]
    assert change.fingerprint(["C:plain.txt"], [str(root)])["digest"] is None          # drive-relative


SECRETS = [(".ssh", "notes.md"), ("sub", ".env.local.txt"), (".kaggle", "notes.txt"), (".aws", "config.json"),
           (".Docker", "config.json"), (".kube", "x.yaml"), (".gnupg", "a.txt"), ("credentials", "x.txt"),
           ("credentials.json",), ("sub", ".env.json")]
NOT_EVIDENCE = [(".npmrc",), (".netrc",), (".pgpass",), (".git-credentials",), ("id_ed25519",), ("id_rsa.pub",),
                ("server.PEM",), ("x.pfx",), ("x.p12",), ("db.kdbx",), ("api.key",), ("photo.png",), ("prod.env",),
                ("wallet.dat",), ("a.pdf",), ("nb.ipynb",), ("paper.tex",), ("README.rst",), ("a.tsv",)]
# Names that held or suggested secrets and were digested at 91625c1, from the audit's probe of the kinds: every one is
# refused now.
DIGESTED_AT_91625C1 = [
    "wallet.json", "wallet.txt", "wallet.md", "vault.json", "vault.yaml", "vault.txt", "token.json", "tokens.json",
    "my_token.txt", "secret.json", "secrets.json", "secrets.yaml", "client_secret.json", "kaggle.json", "gh/hosts.yml",
    ".config/gh/hosts.yml", ".ssh_old/config.txt", ".ssh.bak/id.txt", ".sshd/x.txt", "service-account.json",
    "api_key.txt", "apikey.json", "password.txt", "passwords.csv", "seed.txt", "mnemonic.txt", "recovery_codes.txt",
    "access_token.txt", "auth.json", "env.json", "settings.local.json", ".claude/settings.local.json", "keys.json",
    "key.json", "private_key.json", "x.key.md", "cred.json"]
INNOCENT = [("tokenizer.py",), ("secretary.md",), ("sub", "token_budget.md"), ("tokenizer", "a.py"), ("keyboard.md",),
            ("monkey.md",), ("key_results.md",), ("notes.MD",), ("hosts.yml",), ("other", "hosts.yml")]
# The new kinds: scripts, markup, build files and logs, which changes are most often about.
SCRIPTS = ["LICENSE", "Makefile", "Dockerfile", "README", ".gitignore", ".gitattributes", ".editorconfig", "index.html",
           "style.css", "run.sh", "run.ps1", "run.bat", "run.cmd", "pom.xml", "setup.cfg", "pytest.ini", "main.go",
           "App.java", "lib.c", "lib.h", "x.hpp", "x.cpp", "a.log"]
# The trade-off of whole-part matching, stated: these honest names are refused.
REFUSED_HONEST = ["vault_notes.md", "wallets.md", "tokens.md", ".sshd_notes.md", "passwords_policy.md"]


def make(root: Path, parts) -> Path:
    f = root.joinpath(*parts)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("x", encoding="utf-8")
    return f


@pytest.mark.parametrize("parts", SECRETS)
def test_a_part_named_like_a_secret_is_refused_even_for_a_kind_that_is_evidence(area, parts):
    root, _ = area
    got = fp(make(root, parts), root)
    assert got["digest"] is None and "holds secrets" in got["why"]


@pytest.mark.parametrize("parts", NOT_EVIDENCE)
def test_a_file_that_is_not_a_kind_of_evidence_is_refused(area, parts):
    root, _ = area
    got = fp(make(root, parts), root)
    assert got["digest"] is None and ("not a kind of file read as evidence" in got["why"] or "holds secrets" in got["why"])


@pytest.mark.parametrize("parts", INNOCENT)
def test_an_innocent_name_is_read_as_evidence(area, parts):
    root, _ = area
    assert fp(make(root, parts), root)["digest"]                 # c5eecb6 refused several of these by substring


@pytest.mark.parametrize("rel", DIGESTED_AT_91625C1)
def test_every_secret_name_digested_at_91625c1_is_refused(area, rel):
    root, _ = area
    got = fp(make(root, ("s", *rel.split("/"))), root)
    assert got["digest"] is None and "holds secrets" in got["why"]


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_and_build_files_are_evidence(area, name):
    root, _ = area
    assert fp(make(root, ("h", name)), root)["digest"]          # 91625c1 refused every one of these as not evidence


@pytest.mark.parametrize("name", REFUSED_HONEST)
def test_the_trade_off_of_whole_part_matching_refuses_these_honest_names(area, name):
    root, _ = area
    assert fp(make(root, ("h", name)), root)["digest"] is None


def test_a_secret_named_file_is_refused_by_both_layers():
    for name in (".npmrc", ".netrc", ".git-credentials", "id_ed25519", "server.pem", "db.kdbx"):
        assert change._kind(name) is not None and change._bad_name(name) is not None, name
    # must pass: each layer lets an ordinary evidence name through
    assert change._kind("tokenizer.py") is None and change._bad_name("tokenizer.py") is None


@pytest.mark.skipif(not WINDOWS, reason="short (8.3) names are a Windows thing")
def test_a_short_name_is_refused_and_realpath_expands_it_here(area):
    root, _ = area
    long = root / ".environment-secrets" / "credentials-file.txt"
    long.parent.mkdir()
    long.write_text("x", encoding="utf-8")
    buf = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(long), buf, 1024):
        pytest.skip("no short name on this volume")
    tail = Path(buf.value).parts[-2:]
    if "~" not in tail[0]:
        pytest.skip("this volume makes no 8.3 names")
    short = root.joinpath(*tail)                                 # the root as given, the folder by its short name
    assert os.path.normcase(os.path.realpath(short)) == os.path.normcase(os.path.realpath(long))   # expanded here
    got = fp(short, root)                                        # 8807d40: digested
    assert got["digest"] is None and "is a short (8.3) name" in got["why"]
    assert change.fingerprint([str(short)], [str(root)])["digest"] is None     # the root as written, too


def test_an_absent_file_is_unknown_and_too_many_files_are_said(area):
    root, _ = area
    gone = change.freshness({"files": [str(root / "nope.txt")], "digest": "x" * 64}, [str(root)])
    assert gone["state"] == "unknown" and "not there" in gone["why"]
    many = change.fingerprint([str(root / "plain.txt")] * (change.MAX_FILES + 1), [str(root)])
    assert many["digest"] is None and "at most 50" in many["why"]
    assert change.fingerprint([str(root / "plain.txt")] * change.MAX_FILES, [str(root)])["digest"]   # must pass


def test_the_cache_is_in_memory_and_lapses(area, monkeypatch):
    root, _ = area
    f = root / "big.txt"
    body = b"A" * 5000 + b"middle" + b"B" * 5000
    f.write_bytes(body)
    clock = [1000.0]
    monkeypatch.setattr(change.time, "monotonic", lambda: clock[0])
    change._CACHE.clear()
    first = fp(f, root)["digest"]
    st = f.stat()
    f.write_bytes(body.replace(b"middle", b"MIDDLE"))           # same size, same ends, same time: the stated limit
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert fp(f, root)["digest"] == first                        # within 60 s it can read as current (SECURITY.md)
    clock[0] += change.CACHE_S
    assert fp(f, root)["digest"] != first                        # must refuse: after its lifetime it is read again
    edge = f.read_bytes()
    f.write_bytes(b"C" + edge[1:])
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert fp(f, root)["digest"] != first                        # an edit at an end is never covered by the cache


# ---------------------------------------------------------------- an undo never rescores
def test_an_undo_records_the_undo_and_never_rescores_the_measurement():
    card = {"predicted": change._predicted([{"measure": "m1", "direction": "up", "p": 0.9},
                                            {"measure": "m2", "direction": "down", "p": 0.8}], [])}
    measured, _ = change.outcome({"moved": {"m1": "up", "m2": "down"}, "undone": False})
    empty, _ = change.outcome({"moved": {}, "undone": True})
    back, _ = change.outcome({"moved": {"m1": "none", "m2": "none"}, "undone": True})
    alone = change.judged(card, [measured])
    for later in (empty, back):                                  # 8807d40: the undo replaced the measurement
        j = change.judged(card, [measured, later])
        assert j["terms"] == pytest.approx(alone["terms"]) and alone["terms"] == pytest.approx([0.01, 0.04])
        assert j["undone"] is True
    # must-refuse: an undo with no measurement before it scores nothing
    assert change.judged(card, [empty])["terms"] == []
