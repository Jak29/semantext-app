"""Files named by the time never overwrite each other, even on a clock that repeats a microsecond.

On Windows with Python 3.10, datetime.now() can read the same microsecond twice in a row, so two backups made at once
were given one name and the second overwrote the first. These tests freeze the clock to make that happen every time.
"""
from datetime import datetime

import pytest

from semantext import claude
from semantext import store as store_mod

FROZEN = datetime(2026, 10, 14, 12, 0, 0, 0)


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(store_mod, "datetime", Frozen)
    monkeypatch.setattr(store_mod, "_last_stamp", [None])


def test_stamps_never_repeat_and_keep_their_order_on_a_frozen_clock(frozen_clock):
    marks = [store_mod.stamp() for _ in range(5)]
    assert len(set(marks)) == 5
    assert marks == sorted(marks)
    assert marks[0] == "20261014-120000-000000"


def test_five_backups_on_a_frozen_clock_are_five_files(frozen_clock, tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    assert len({claude._backup(path) for _ in range(5)}) == 5


class Clock(datetime):
    """A clock the test sets, read through store's own datetime (the module that reads the clock)."""
    t = datetime(2026, 10, 25, 0, 30)

    @classmethod
    def now(cls, tz=None):
        return cls.t


def _kept_in_order(store, name, steps):
    """Save once per step (setting the clock, and 'restart' to forget the last stamp); return the new history names
    in the order they were made."""
    made = []
    for when, restart in steps:
        if restart:
            store_mod._last_stamp[0] = None
        Clock.t = when
        before = {p.name for p in store.history_dir.glob(f"{name}-*.yaml")} if store.history_dir.exists() else set()
        store.save(name, store.load(name))
        made += sorted({p.name for p in store.history_dir.glob(f"{name}-*.yaml")} - before)
    return made


def test_a_clock_set_back_after_a_restart_never_puts_a_new_version_before_an_old_one(monkeypatch, store):
    # audit of 44d2dfa: names in naive local time, a restart, then the clock an hour earlier (as on 25 October),
    # gave the latest save the EARLIEST name, so undo_last restored the wrong version. Fails by assertion on 44d2dfa.
    monkeypatch.setattr(store_mod, "datetime", Clock)
    monkeypatch.setattr(store_mod, "_last_stamp", [None])
    made = _kept_in_order(store, "default", [(datetime(2026, 10, 25, 0, 30), False),
                                             (datetime(2026, 10, 25, 0, 45), False),
                                             (datetime(2026, 10, 25, 0, 10), True)])
    assert len(made) == 3 and made == sorted(made)                            # must-refuse: no reordering
    newest = sorted(p.name for p in store.history_dir.glob("default-*.yaml"))[-1]
    assert newest == made[-1]                                                 # undo_last would take the last one kept


def test_names_written_in_local_time_before_the_change_still_sort_first(monkeypatch, store):
    # a history folder from before the change holds local-time names an hour AHEAD of UTC (summer time); a new UTC
    # name must still sort after them, or the first undo after upgrading picks an old version
    monkeypatch.setattr(store_mod, "datetime", Clock)
    monkeypatch.setattr(store_mod, "_last_stamp", [None])
    store.history_dir.mkdir(parents=True, exist_ok=True)
    old = store.history_dir / "default-20261023-180000-000000.yaml"
    old.write_text(store.path("default").read_text(encoding="utf-8"), encoding="utf-8")
    made = _kept_in_order(store, "default", [(datetime(2026, 10, 23, 17, 0), True)])
    assert made and made[0] > old.name                                        # must-pass


def test_a_far_future_name_in_the_folder_neither_blocks_a_save_nor_pins_the_next_name(monkeypatch, store):
    # audit of 4599bda: a name dated 9999 made the next name overflow, so every save failed before writing; a name
    # dated 2099 pinned every later name to 2099. Marks more than two days ahead of now are ignored.
    monkeypatch.setattr(store_mod, "datetime", Clock)
    monkeypatch.setattr(store_mod, "_last_stamp", [None])
    store.history_dir.mkdir(parents=True, exist_ok=True)
    text = store.path("default").read_text(encoding="utf-8")
    for planted in ("default-99991231-235959-999999.yaml", "default-20991231-120000-000000.yaml"):
        (store.history_dir / planted).write_text(text, encoding="utf-8")
    made = _kept_in_order(store, "default", [(datetime(2026, 10, 25, 0, 30), True)])   # must-pass: it saves
    assert made and made[0].startswith("default-20261025-003000")            # must-refuse: not pinned to 2099
    # a name a day ahead (a local clock east of UTC) still counts as a floor
    (store.history_dir / "default-20261026-003000-000000.yaml").write_text(text, encoding="utf-8")
    made = _kept_in_order(store, "default", [(datetime(2026, 10, 25, 0, 31), True)])
    assert made and made[0] > "default-20261026-003000-000000.yaml"


def test_two_saves_on_a_frozen_clock_keep_two_versions(frozen_clock, store):
    name = "default"
    data = store.load(name)
    store.save(name, data)
    store.save(name, data)
    kept = sorted(store.history_dir.glob(f"{name}-*.yaml"))
    assert len(kept) >= 2 and len({p.name for p in kept}) == len(kept)
