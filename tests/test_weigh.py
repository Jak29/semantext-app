"""`semantext backtest --weighed`: the weighed touch, on synthetic histories with known cue rates.

The history: 40 blocks, each one message the user then corrects and ten clean ones, one minute apart. The card holds
one rule, "Never deploy on a friday.", so "deploy" and "never" are its word cues. "deploy" is in 30% of the misread
messages and 4% of the clean ones; "never" is in 30% of both, so it carries nothing.
"""
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from semantext import cli
from semantext import weigh as wt
from semantext.mine import units
from semantext.store import Refused

START = datetime(2030, 1, 1, tzinfo=timezone.utc)
SENTINEL = "zebraquartz"
BOOT = 400


@pytest.fixture
def card(store):
    store.learn("default", "Never deploy on a friday.")
    return store


class Transcript:
    def __init__(self, path):
        self.path, self.t, self.n, self.records = path, START, 0, []

    def _add(self, record):
        self.n += 1
        self.t += timedelta(minutes=1)
        self.records.append({"uuid": f"r{self.n}", "timestamp": self.t.isoformat(), "isSidechain": False, **record})
        return self

    def user(self, text):
        return self._add({"type": "user", "turnOrigin": "human", "message": {"role": "user", "content": text}})

    def reply(self, text="Done."):
        return self._add({"type": "assistant", "message": {"role": "assistant",
                                                           "content": [{"type": "text", "text": text}]}})

    def write(self):
        self.path.write_text("".join(json.dumps(r) + "\n" for r in self.records), encoding="utf-8")
        return self.path


def message(i, deploy, never):
    return (f"Prepare the staging build number {i} {SENTINEL}" + (" and deploy it" if deploy else "")
            + (" but never in a hurry" if never else "") + ".")


def history(path, deploy_mis=(0, 1, 2), clean_deploy=lambda j: j % 25 == 0, never=(3, 4, 5)):
    t = Transcript(path)
    for b in range(40):
        t.user(message(b, b % 10 in deploy_mis, b % 10 in never)).reply()
        t.user("No, I meant the other environment.").reply()
        for j in range(10 * b, 10 * b + 10):
            t.user(message(1000 + j, clean_deploy(j), j % 10 in never)).reply()
    return t.write()


def measure(store, path, **kw):
    return wt.measure(store, "default", [path], boot=BOOT, **kw)


# ---- the parts ------------------------------------------------------------------------------------------------------
def test_the_parts_are_cut_by_time(card, tmp_path):
    parts = wt.split(units(history(tmp_path / "h.jsonl")))
    assert (len(parts["fit_misread"]), len(parts["fit_clean"]), len(parts["calib_clean"])) == (20, 100, 100)
    assert sum(1 for u in parts["test"] if u["misread"]) == 20 and len(parts["test"]) == 220
    ids = [u["record"] for k in ("fit_misread", "fit_clean", "calib_clean", "test") for u in parts[k]]
    assert len(ids) == len(set(ids))
    assert max(wt._when(u) for u in parts["calib_clean"]) < min(wt._when(u) for u in parts["test"])


def test_a_rule_learned_in_the_test_part_is_left_off_the_card(card, tmp_path):
    card.learn("default", "Always tag the release.", {"type": "LEARNED", "words": "Always tag the release.",
                                                      "when": (START + timedelta(hours=12)).isoformat()})
    rep = measure(card, history(tmp_path / "late.jsonl"))
    assert rep["card_rules"] == {"on_card": 1, "left_off": 1, "undated_kept": 0}
    assert rep["card"]["rules"] == 1 and rep["card_all_in_sample"]["rules"] == 2


def test_too_few_misread_messages_are_refused(card, tmp_path):
    t = Transcript(tmp_path / "few.jsonl")
    for b in range(3):
        t.user(message(b, True, False)).reply().user("No, I meant the other environment.").reply()
    with pytest.raises(Refused):
        wt.split(units(t.write()))


# ---- must pass ------------------------------------------------------------------------------------------------------
def test_an_informative_cue_is_weighed_and_the_touch_holds_its_ceiling(card, tmp_path):
    rep = measure(card, history(tmp_path / "h.jsonl"), ledger=True)
    assert rep["card_rules"] == {"on_card": 1, "left_off": 0, "undated_kept": 0}
    c = rep["card"]
    w = c["ledger"]
    # The fit part: deploy in 6 of 20 misread and 4 of 100 clean; never in 6 and 30.
    assert w["word:deploy"]["weight"] == pytest.approx(math.log((6.5 / 21) / (4.5 / 101)), abs=1e-4)
    assert abs(w["word:never"]["weight"]) < 0.1
    assert all(v["weight"] <= v["ceiling"] for v in w.values())
    assert c["consistency"]["disagreements"] == 0
    assert c["weighed"]["touched"] == {"misread": 6, "clean": 8}
    assert c["unweighed"]["touched"] == {"misread": 12, "clean": 64}
    assert c["weighed"]["ceiling"]["holds"] and c["weighed"]["skill_shown"]
    assert c["precision_gain"]["lo"] > 0 and c["verdict"] == "GO"


# ---- must refuse ----------------------------------------------------------------------------------------------------
def test_a_weight_above_its_ceiling_is_refused():
    with pytest.raises(Refused):
        wt.check_ceilings({"word:x": {"weight": 1.2, "ceiling": math.log(1 / 0.43)}})


def test_a_cue_seen_fewer_than_three_times_weighs_nothing():
    w = wt.fit_weights([{"word:rare"}, set(), set()], [set()] * 10)        # once, in one misread message
    assert w["word:rare"]["k_misread"] + w["word:rare"]["k_clean"] < wt.SUPPORT and w["word:rare"]["weight"] == 0.0


def test_a_cue_that_carries_nothing_gives_no_skill(card, tmp_path):
    rep = measure(card, history(tmp_path / "n.jsonl", deploy_mis=(), clean_deploy=lambda j: False))
    assert rep["card"]["weighed"]["touched"]["misread"] == 0 and rep["card"]["verdict"] == "KILL"


def test_a_ceiling_that_fails_on_later_messages_is_never_called_holding(card, tmp_path):
    drift = lambda j: j % 10 in (6, 7, 8) if j >= 200 else j % 25 == 0      # noqa: E731
    rep = measure(card, history(tmp_path / "d.jsonl", clean_deploy=drift))
    assert rep["card"]["weighed"]["ceiling"]["holds"] is False and rep["card"]["verdict"] == "KILL"


def test_a_non_strict_threshold_on_tied_scores_breaks_the_ceiling(card, tmp_path, monkeypatch):
    assert wt.over(0.0, 0.0) is False and wt.threshold([0.0] * 50, 0.10) == 0.0
    monkeypatch.setattr(wt, "over", lambda s, t: s >= t)
    rep = measure(card, history(tmp_path / "s.jsonl"))
    assert rep["card"]["weighed"]["ceiling"]["holds"] is False


def test_cues_that_drift_from_the_back_tests_own_touch_are_counted(card, tmp_path, monkeypatch):
    real = wt.rule_words
    monkeypatch.setattr(wt, "rule_words", lambda entries: real(entries) | {"staging"})
    rep = measure(card, history(tmp_path / "c.jsonl"))
    assert rep["card"]["consistency"]["disagreements"] > 0


# ---- what it may not do --------------------------------------------------------------------------------------------
def test_the_report_holds_no_message_text(card, tmp_path):
    out = json.dumps(measure(card, history(tmp_path / "p.jsonl")))
    assert SENTINEL not in out and "Prepare the staging" not in out


def test_measuring_writes_nothing(card, tmp_path):
    path = history(tmp_path / "w.jsonl")
    before = {p: p.read_bytes() for p in card.root.rglob("*") if p.is_file()}
    measure(card, path)
    assert {p: p.read_bytes() for p in card.root.rglob("*") if p.is_file()} == before


# ---- the command line ----------------------------------------------------------------------------------------------
def test_the_command_reports_the_verdict(card, tmp_path, capsys):
    path = history(tmp_path / "cli.jsonl")
    assert cli.main(["backtest", "--weighed", "--json", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["card"]["verdict"] == "GO"
    assert cli.main(["backtest", "--weighed", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Verdict: GO" in out and "ceiling 10%: holds" in out and SENTINEL not in out


@pytest.mark.parametrize("extra", [["--split", "2030-01-01"], ["--reader", "ollama:some-model"], ["--alpha", "1.5"],
                                   ["--show"], ["--clean-sample", "5"]])
def test_the_command_refuses_what_does_not_go_with_weighing(card, tmp_path, capsys, extra):
    path = history(tmp_path / "x.jsonl")
    assert cli.main(["backtest", "--weighed", *extra, str(path)]) == 1
    assert capsys.readouterr().err.startswith("semantext: ")
