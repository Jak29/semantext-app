"""The change card's score against the confirmed findings of the whole-file review of sources/change.py at 994f103
(change_whole): each test names its finding and fails on 994f103."""
from __future__ import annotations

import pytest

from semantext.sources import change
from test_change_score_counts import parts, record

P = lambda m, d="down", p=0.8: {"measure": m, "direction": d, "p": p}   # noqa: E731


# ---------------------------------------------------------------- F1: folded by case on both sides
def test_f1_a_duplicate_in_another_case_is_judged_by_the_name_the_outcome_uses():
    s = change.score([record("A", None, {"latency": "down"}, raw=[P("Latency"), P("latency")])])["A"]
    assert parts(s) == (1, 0, 0, 1, 2) and s["brier"] == pytest.approx(0.04)
    # must pass: an exact name still wins over a folded one when the outcome holds both
    ch, _ = change.fields({"predicted": [P("Latency", "up")]})
    j = change.judged(ch, [{"at": "x", "moved": {"latency": "down", "Latency": "up"}, "regressions": [],
                            "undone": False}])
    assert j["measures"][0]["hit"] is True
    # and a regression named in another case was predicted
    j = change.judged(ch, [{"at": "x", "moved": {}, "regressions": ["LATENCY", "memory"], "undone": False}])
    assert j["unpredicted_regressions"] == ["memory"]


# ---------------------------------------------------------------- F2: the first scorable copy counts
def test_f2_a_bare_name_before_a_full_prediction_gives_way_to_it():
    s = change.score([record("A", None, {"latency": "down"}, raw=["latency", P("latency")])])["A"]
    assert parts(s) == (1, 0, 0, 1, 2) and s["brier"] == pytest.approx(0.04)
    # must refuse: two scorable copies still count once, the first (so a repeat cannot pad)
    s = change.score([record("A", None, {"latency": "down"}, raw=[P("latency", p=0.6), P("latency", p=1.0)])])["A"]
    assert parts(s) == (1, 0, 0, 1, 2) and s["brier"] == pytest.approx(0.16)


# ---------------------------------------------------------------- F3: one note for every repeat
def test_f3_repeats_are_one_bounded_note():
    _, notes = change.fields({"predicted": [P("wrong", "up", 0.9)] + [P("sure", "up", 1.0)] * 100})
    repeats = [t for _, t in notes if "more than once" in t or "repeat" in t]
    assert len(repeats) == 1 and "99" in repeats[0]
    _, notes = change.fields({"predicted": [P("n" * 10_000)] * 50})
    about = [t for _, t in notes if "predicted" in t]
    assert len(about) == 1 and len(about[0]) < 400 and about[0].startswith("49 ")


# ---------------------------------------------------------------- F4: the docstring says what the code holds
def test_f4_the_score_docstring_claims_no_more_than_the_cap():
    doc = " ".join(change.score.__doc__.split())
    assert "neither repeating a sure prediction" not in doc
    assert "repeating a measure" in doc and "MAX_PREDICTIONS" in doc


# ---------------------------------------------------------------- F6: the cap note counts measures
def test_f6_repeats_past_the_cap_are_repeats_not_more_measures():
    raw = [P(f"m{i}") for i in range(change.MAX_PREDICTIONS)] + [P("x"), P("x"), P("x")]
    ch, notes = change.fields({"predicted": raw})
    assert len(ch["predicted"]) == change.MAX_PREDICTIONS and ch["unnamed_predictions"] == 3
    texts = [t for _, t in notes]
    assert any("1 past that do not count" in t for t in texts)
    assert any("2 predicted" in t and "more than once" in t for t in texts)
