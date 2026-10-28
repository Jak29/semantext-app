"""The change card's evidence digest, attacked (the audit of 8807d40: an intermediate junction, a hard link, an
alternate stream, secret names, short names, missing roots), and the scoring of an undo. Every attack here was digested, or scored, by 8807d40; each now has a refusing arm beside a
passing one. Junctions are made with _winapi.CreateJunction (Windows, no privilege needed); a test that cannot make its
link or its short name on this machine is skipped, never passed.

These test HOW change.py reads (the checks every evidence policy sits behind), so they use a policy defined here that
admits every file inside its roots. Which files are evidence is each way's own test (test_evidence_*.py).
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

from semantext.sources import change, evidence

WINDOWS = sys.platform == "win32"


class Inside(evidence.Policy):
    """Every file inside the roots, for testing the reading alone."""
    name = "inside (tests only)"

    def __init__(self, *roots):
        self._roots = [str(r) for r in roots]

    def roots(self):
        return self._roots

    def refuse(self, path, real, root, budget=None):
        return None


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
    return change.fingerprint([str(path)], Inside(os.path.normcase(str(root))))


def test_a_plain_file_inside_is_digested_and_one_outside_is_not(area):
    root, outside = area
    assert fp(root / "plain.txt", root)["digest"] and fp(root / "sub" / "notes.txt", root)["digest"]   # must pass
    assert fp(outside / "report.txt", root)["digest"] is None
    assert fp(root / ".." / "outside" / "report.txt", root)["digest"] is None
    with pytest.raises(TypeError):
        change.fingerprint([str(root / "plain.txt")])          # a policy is required: there is no default to fall back on
    assert change.fingerprint([str(outside / "report.txt")], Inside())["digest"] is None     # a policy with no roots
    # must refuse: a bare list of roots (the public call) is read through the page's way (git-index), never with no
    # policy, so a file no repository lists is not digested; something that is neither a list nor a policy reads nothing
    got = change.fingerprint([str(root / "plain.txt")], [str(root)])
    assert got["digest"] is None and "git repository" in got["why"]
    for nothing in (str(root), {"roots": [str(root)]}, None, object()):
        got = change.fingerprint([str(root / "plain.txt")], nothing)
        assert got["digest"] is None and "no evidence policy" in got["why"]
    # the base policy admits nothing
    class Bare(evidence.Policy):
        def roots(self):
            return [str(root)]
    got = change.fingerprint([str(root / "plain.txt")], Bare())
    assert got["digest"] is None and "no evidence policy admits it" in got["why"]


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


@pytest.mark.skipif(not WINDOWS, reason="junctions are a Windows thing")
def test_a_file_directly_under_a_linked_root_is_read_like_one_a_folder_deeper(area):
    # review of 1.2.2, C1: its parent is the root, and the root's own link was taken for "changed while it was read"
    root, outside = area
    via = root.parent / "via"
    junction(via, root)
    got = fp(via / "plain.txt", via)
    assert got["digest"] is not None, got
    assert got["digest"] == fp(via / "plain.txt", via)["digest"]             # and steady from one read to the next
    junction(root / "bridge", outside)
    assert fp(via / "bridge" / "report.txt", via)["digest"] is None          # must-refuse: a link below the root


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
    assert change.fingerprint(["C:plain.txt"], Inside(root))["digest"] is None          # drive-relative


def test_the_names_the_file_system_reads_differently_are_refused_and_names_alone_decide_nothing_else():
    for part in ("a.txt:hidden", "trailing.", "trailing ", "CON", "nul.txt", "PROGRA~1"):
        assert change._bad_name(part) is not None, part
    # must pass: change.py no longer judges what a name may hold; that is the evidence policy's question
    for part in (".npmrc", "id_ed25519", "server.pem", "wallet.json", "password_policy.md", "tokenizer.py"):
        assert change._bad_name(part) is None, part
    assert not hasattr(change, "SECRET_NAMES") and not hasattr(change, "EVIDENCE_KINDS")


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
    assert change.fingerprint([str(short)], Inside(root))["digest"] is None     # the root as written, too


def test_an_absent_file_is_unknown_and_too_many_files_are_said(area):
    root, _ = area
    gone = change.freshness({"files": [str(root / "nope.txt")], "digest": "x" * 64}, Inside(root))
    assert gone["state"] == "unknown" and "not there" in gone["why"]
    many = change.fingerprint([str(root / "plain.txt")] * (change.MAX_FILES + 1), Inside(root))
    assert many["digest"] is None and "at most 50" in many["why"]
    assert change.fingerprint([str(root / "plain.txt")] * change.MAX_FILES, Inside(root))["digest"]   # must pass


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
