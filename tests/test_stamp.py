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


def test_two_saves_on_a_frozen_clock_keep_two_versions(frozen_clock, store):
    name = "default"
    data = store.load(name)
    store.save(name, data)
    store.save(name, data)
    kept = sorted(store.history_dir.glob(f"{name}-*.yaml"))
    assert len(kept) >= 2 and len({p.name for p in kept}) == len(kept)
