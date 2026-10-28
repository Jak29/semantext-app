"""A change card's Brier score never says more than was measured: n scored of m made (m holds what an outcome left
out, what awaits an outcome and what cannot be scored), a coin beside it, and an interval only from ten CHANGES, with
a width that is never zero. Built on plain records, as the cards reader hands them to score()."""
from __future__ import annotations

import math

import pytest

from semantext.sources import change


def record(seat, predicted, moved=None, undone=False, raw=None):
    """A change record with its predictions (read as the cards reader reads a line), and, when `moved` is given, one
    outcome judged against them."""
    line = raw if raw is not None else [{"measure": m, "direction": d, "p": p} for m, d, p in predicted]
    ch, _ = change.fields({"predicted": line})
    out = {"kind": "change", "seat": seat, "change": ch, "outcomes": [], "judged": None}
    if moved is not None:
        out["outcomes"] = [{"at": "x", "moved": moved, "regressions": [], "undone": undone}]
        out["judged"] = change.judged(ch, out["outcomes"])
    return out


def parts(s: dict) -> tuple:
    return s["scored"], s["left_out"], s["awaiting"], s["unusable"], s["predicted"]


def test_a_prediction_left_out_of_the_outcome_still_counts_in_m():
    """An agent that measures only the predictions it got right scores well on n, and m shows what it left out."""
    honest = record("A", [("x", "up", 0.9), ("y", "up", 0.9)], {"x": "up", "y": "down"})
    picky = record("B", [("x", "up", 0.9), ("y", "up", 0.9)], {"x": "up"})        # y left out of its outcome
    got = change.score([honest, picky])
    assert parts(got["A"]) == (2, 0, 0, 0, 2)
    assert parts(got["B"]) == (1, 1, 0, 0, 2)
    assert got["B"]["brier"] == pytest.approx(0.01) and got["B"]["brier"] < got["A"]["brier"]
    later = change.score([picky, record("B", [("z", "down", 0.7)])])["B"]          # no outcome yet: awaiting
    assert parts(later) == (1, 1, 1, 0, 3)


def test_an_invalid_prediction_counts_in_m_as_unusable():
    """A chance outside 0 to 1, a missing chance, no direction, a direction that is neither, or no name: each was made
    and cannot be scored, so it is in m as unusable, never dropped."""
    raw = [{"measure": "ok", "direction": "up", "p": 0.8},
           {"measure": "too sure", "direction": "up", "p": 1.5},
           {"measure": "negative", "direction": "down", "p": -0.1},
           {"measure": "no chance", "direction": "up"},
           {"measure": "no direction", "p": 0.7},
           {"measure": "sideways", "direction": "sideways", "p": 0.7},
           "a bare text",
           {"direction": "up", "p": 0.9}]                                          # no name
    s = change.score([record("A", None, {"ok": "up", "too sure": "up", "negative": "down", "no chance": "up",
                                         "no direction": "up", "sideways": "up"}, raw=raw)])["A"]
    assert parts(s) == (1, 0, 0, 7, 8)
    assert s["scored"] + s["left_out"] + s["awaiting"] + s["unusable"] == s["predicted"]
    # a predicted field that is not a list at all is one unusable prediction, not none
    assert parts(change.score([record("A", None, raw="shorter")])["A"]) == (0, 0, 0, 1, 1)
    # must-refuse: only usable predictions are scored, so the unusable ones move n by nothing
    assert s["brier"] == pytest.approx((0.8 - 1) ** 2)


def test_the_interval_counts_changes_not_predictions_and_is_never_a_point():
    one_change = change.score([record("A", [(f"m{i}", "up", 0.9) for i in range(10)],
                                      {f"m{i}": "up" for i in range(10)})])["A"]
    assert one_change["scored"] == 10 and one_change["changes_scored"] == 1
    assert one_change["interval"] is None                                       # ten predictions are one change
    assert one_change["interval_note"] == "too few to state an interval (fewer than 10 changes scored)"
    alike = [record("A", [("m", "up", 0.9)], {"m": "up"}) for _ in range(10)]   # ten changes, all hit alike
    s = change.score(alike)["A"]
    half = math.sqrt(math.log(2 / 0.05) / 20)
    assert s["changes_scored"] == 10 and s["brier_by_change"] == pytest.approx(0.01)
    assert s["interval"] == [0.0, round(0.01 + half, 4)] and s["interval"][1] > s["interval"][0]
    nine = change.score(alike[:9])["A"]
    assert nine["interval"] is None and nine["changes_scored"] == 9


def test_the_coin_stands_beside_the_score():
    s = change.score([record("A", [("m", "up", 0.8)], {"m": "up"})])["A"]
    assert s["coin"] == 0.25 and s["brier"] == pytest.approx(0.04)
    assert change.score([record("A", [("m", "up", 0.8)])])["A"]["coin"] is None   # nothing scored, no coin either


def test_repeating_a_sure_prediction_never_pads_a_score():
    """Audit of the v2-next merge: one wrong p=0.9 beside 100 copies of one sure prediction scored 0.008. A measure
    predicted again on the same change (in any case) counts as unusable, never scored."""
    padded = record("A", [("wrong", "up", 0.9)] + [("sure", "up", 1.0)] * 100 + [("SURE", "up", 1.0)],
                    {"wrong": "down", "sure": "up"})
    s = change.score([padded])["A"]
    assert parts(s) == (2, 0, 0, 100, 102)           # 99 more "sure" and one "SURE": 100 unusable
    assert s["brier"] == pytest.approx((0.81 + 0.0) / 2)
    # must-pass: distinct measures still score, one term each
    plain = change.score([record("A", [("a", "up", 1.0), ("b", "up", 0.9)], {"a": "up", "b": "down"})])["A"]
    assert parts(plain) == (2, 0, 0, 0, 2)


def test_a_change_counts_at_most_its_cap_of_predictions():
    many = [(f"m{i}", "up", 1.0) for i in range(change.MAX_PREDICTIONS + 5)]
    s = change.score([record("A", many, {m: "up" for m, _, _ in many})])["A"]
    assert change.MAX_PREDICTIONS == 20
    assert parts(s) == (20, 0, 0, 5, 25)
    ch, notes = change.fields({"predicted": [{"measure": m, "direction": d, "p": p} for m, d, p in many]})
    assert len(ch["predicted"]) == 20 and ch["unnamed_predictions"] == 5
    assert any("more than 20" in why for _, why in notes)