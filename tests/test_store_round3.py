"""The store's writes against the confirmed findings of the whole-file review of store.py at 994f103 (store_whole) and
of the excerpt (store_store): each test names its finding and fails on 994f103."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from semantext import store as st
from semantext.store import Refused, Store
from test_write_atomic import old


def busy_reads(monkeypatch, path: Path, times: int) -> dict:
    """Path.read_bytes refuses `path` for the next `times` reads, as Windows does while the file is swapped in."""
    real, left = Path.read_bytes, {"n": times}

    def read(self):
        if os.path.normcase(str(self)) == os.path.normcase(str(path)) and left["n"] > 0:
            left["n"] -= 1
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", read)
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    return left


# ---------------------------------------------------------------- store_whole/F1 (store_store/F1): every read retries
def test_f1_undo_last_reads_the_environment_as_every_reader_does(store, monkeypatch):
    store.learn("default", "say less")
    path = store.path("default")
    left = busy_reads(monkeypatch, path, 2)
    store.undo_last("default")
    assert left["n"] == 0 and "say less" not in path.read_text(encoding="utf-8")


def test_f1_put_state_copies_an_unreadable_state_file_with_retries(store, monkeypatch):
    store.state_path.write_text("{ not json", encoding="utf-8")
    left = busy_reads(monkeypatch, store.state_path, 2)
    store.put_state(store.state())
    assert left["n"] == 0 and list(store.root.glob("state-unreadable-*.json"))


# ---------------------------------------------------------------- store_whole/F3: a stray folder is left alone
def test_f3_open_sweeps_no_stray_folder_under_profiles(home):
    Store.open(home)
    stray = old(home / "profiles" / "work backup" / f"{st.TEMP_PREFIX}SEMANTICS-ab12.tmp")
    env = old(home / "profiles" / "default" / f"{st.TEMP_PREFIX}SEMANTICS-cd34.tmp")
    store = Store.open(home)
    assert "work backup" in store.strays()
    assert stray.exists() and not env.exists()


# ---------------------------------------------------------------- store_whole/F5: a state.json that is a folder
def test_f5_a_state_file_that_is_a_folder_is_refused_plainly_and_fast(store):
    store.state_path.mkdir()
    start = time.perf_counter()
    s = store.state()
    assert store.state_problem and "not a file" in store.state_problem
    assert time.perf_counter() - start < 0.05
    with pytest.raises(Refused, match="not a file"):
        store.put_state(s)
    with pytest.raises(Refused, match="not a file"):
        store.set_option("feed", False)


# ---------------------------------------------------------------- store_whole/F7: CRLF text keeps its lines
def test_f7_crlf_text_through_the_editor_keeps_its_lines(store):
    text = store.source("default").replace("\r\n", "\n")
    store.write_source("default", text.replace("\n", "\r\n"))
    raw = store.path("default").read_bytes()
    assert b"\r\r\n" not in raw
    assert store.source("default").replace("\r\n", "\n").splitlines() == text.splitlines()


# ---------------------------------------------------------------- store_store/F7: no wait under the store-wide lock
def test_store_f7_the_swap_retry_waits_outside_the_lock(tmp_path, monkeypatch):
    real, fails, held = os.replace, {"n": 3}, []

    def replace(src, dst):
        if fails["n"] > 0:
            fails["n"] -= 1
            raise PermissionError(13, "in use", str(dst))
        return real(src, dst)

    def sleep(s):
        held.append(st._WRITE_LOCK.locked())
    monkeypatch.setattr(st.os, "replace", replace)
    monkeypatch.setattr(st.time, "sleep", sleep)
    st.write_atomic(tmp_path / "a.txt", "a")
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "a"
    assert held == [False, False, False]
    # must refuse: a swap that never lands still raises, and leaves no temporary file
    fails["n"] = 99
    with pytest.raises(PermissionError):
        st.write_atomic(tmp_path / "b.txt", "b")
    assert not list(tmp_path.glob(f"{st.TEMP_PREFIX}*"))
