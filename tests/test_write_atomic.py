"""The store's writes leave nothing behind: a temporary file has a name the store knows as its own, the store sweeps
its own stale ones at open (and nothing else), and a reader that meets the swap tries again before it gives up
(audit of the v2-next merge)."""
from __future__ import annotations

import os
import time
from pathlib import Path

from semantext import store as st
from semantext.store import Store


def test_a_temporary_file_has_the_stores_own_prefix(tmp_path, monkeypatch):
    seen = []
    real = os.replace

    def watch(src, dst):
        seen.append(os.path.basename(src))
        return real(src, dst)
    monkeypatch.setattr(st.os, "replace", watch)
    st.write_atomic(tmp_path / "state.json", "{}")
    assert len(seen) == 1 and seen[0].startswith(st.TEMP_PREFIX) and seen[0].endswith(".tmp")
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == "{}"


def old(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    then = time.time() - st.TEMP_STALE_S - 60
    os.utime(path, (then, then))
    return path


def test_the_store_sweeps_its_own_stale_temporary_files_at_open_and_nothing_else(home):
    Store.open(home)                                                    # the home and its environments exist
    left = [old(home / f"{st.TEMP_PREFIX}state-abc.tmp"),             # a kill between the write and the swap
            old(home / "history" / f"{st.TEMP_PREFIX}default-1.tmp"),
            old(home / "profiles" / "default" / f"{st.TEMP_PREFIX}SEMANTICS-2.tmp")]
    kept = [home / f"{st.TEMP_PREFIX}state-new.tmp",                   # must keep: a write in progress (fresh)
            old(home / "notes.tmp"),                                   # not the store's prefix
            old(home / f"{st.TEMP_PREFIX}state.json"),                 # the prefix, but not a .tmp
            old(home / "elsewhere" / f"{st.TEMP_PREFIX}x.tmp")]        # below a folder the store does not write
    kept[0].write_text("x", encoding="utf-8")
    Store.open(home)
    assert not any(p.exists() for p in left)
    assert all(p.exists() for p in kept)


def test_a_reader_meeting_the_swap_tries_again(store, monkeypatch):
    s = store.state()
    s["feed"] = False
    store.put_state(s)
    real, fails = Path.read_text, {"left": 2}

    def busy(self, *a, **k):
        if self == store.state_path and fails["left"] > 0:
            fails["left"] -= 1
            raise PermissionError(13, "The process cannot access the file", str(self))
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", busy)
    monkeypatch.setattr(st.time, "sleep", lambda s: None)
    assert store.state()["feed"] is False and store.state_problem is None
    # must refuse: still busy after every try, it degrades as before (the defaults, and the problem named)
    fails["left"] = st.READ_TRIES
    assert store.state()["feed"] is True and store.state_problem
