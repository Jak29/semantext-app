"""The price of 1.2.2's two-day bound on history names, measured, and stated in SECURITY.md.

A clock more than two days ahead, then corrected, leaves future names that sort as the newest, so undo_last restores
one of them; a name up to two days ahead holds every later name just past it, with the order kept."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from semantext import store as store_mod
from test_stamp import Clock, _kept_in_order


def test_a_clock_three_days_ahead_then_corrected_leaves_undo_last_an_older_version(monkeypatch, store):
    monkeypatch.setattr(store_mod, "datetime", Clock)
    monkeypatch.setattr(store_mod, "_last_stamp", [None])
    fast = _kept_in_order(store, "default", [(datetime(2026, 10, 28, 12, 0), True)])           # three days fast
    later = _kept_in_order(store, "default", [(datetime(2026, 10, 25, 12, 0), True)])          # corrected, a restart
    assert later[0] < fast[0]                     # the future name is no floor, so the later version sorts before it
    assert store.undo_last("default") == fast[0]  # the price: the future-named, older version is restored


def test_a_name_a_day_ahead_holds_later_names_past_it_with_the_order_kept(monkeypatch, store):
    monkeypatch.setattr(store_mod, "datetime", Clock)
    monkeypatch.setattr(store_mod, "_last_stamp", [None])
    ahead = _kept_in_order(store, "default", [(datetime(2026, 10, 26, 12, 0), True)])          # a day fast
    later = _kept_in_order(store, "default", [(datetime(2026, 10, 25, 12, 0), True),
                                              (datetime(2026, 10, 25, 13, 0), True)])
    assert ahead[0] < later[0] < later[1]                                    # the order is kept
    assert all(x.startswith("default-20261026-120000") for x in later)        # held at a time that has not come


def test_security_states_the_price_of_the_bound():
    text = " ".join((Path(__file__).parents[1] / "SECURITY.md").read_text(encoding="utf-8").split())
    assert "clock that ran more than two days ahead and was then corrected" in text
    assert "`undo_last` restores one of them" in text
    assert "A name up to two days ahead" in text and "The order is kept" in text
