"""The readers behind work clauses (PM-DESIGN r4, slice 2b): run-record clauses through runs.py, verdict clauses from
the verdicts file, landed and outcome unknown. For each reader: met; not met; stale; the builder's own evidence
refused; a missing or unreadable file shown as unknown. The run-record world is test_sources_runs.py's own."""
from __future__ import annotations

import json

import pytest

from semantext.sources import closed, work
from semantext.work.clauses import evaluate
from test_sources_runs import NOW, good, world, write   # noqa: F401  (world is a fixture)

RUN = {"kind": "run-record", "rule": "core.a", "outcome": "clean", "max_findings": 0, "fresh_days": 30}
VERDICT = {"kind": "verdict", "piece": "p1"}


NAMED = closed.ReadContext("", ())   # closures named, none closed: api 0.2 closes every path while they are unknown


def holds(got):
    """A run record that passes every other test of its clause is "unknown" while no reader names who built its
    checker (PM-DESIGN, decided 24 October, A2: checker_by reads unknown until it is wired), never "met"."""
    return got[0] == "unknown" and "who built the checker" in got[1]


def judged(clause, cfg, owner="Alder", ctx=NAMED):
    item = {"id": "W-lab-1", "state": "review", "owner": owner, "creator": owner, "clauses": [clause]}
    ev = work.Evidence([], cfg, NOW, ctx)
    got = evaluate(item, ev, NOW, ctx)["clauses"][0]
    return got["state"], got["why"], ev


def run_cfg(w, **over):
    return {"cards": str(w.cards), "run_records": [str(w.repo)], **over}


# ---- run records, through runs.py --------------------------------------------------------------------------------
def test_a_run_record_clause_is_met_by_a_fresh_passing_record(world):
    write(world, good(world))
    state, why, _ = judged(RUN, run_cfg(world))
    assert holds((state, why))


def test_a_run_record_clause_is_not_met_by_a_failed_run_or_too_many_findings(world):
    write(world, good(world, outcome="failed"))
    assert judged(RUN, run_cfg(world))[0] == "unmet"
    write(world, good(world, findings=["one"], at="2026-10-23T20:30:00Z"))   # newer, passing, with a finding
    state, why, _ = judged(RUN, run_cfg(world))
    assert state == "unmet" and "clean" in why
    assert holds(judged({**RUN, "outcome": "with findings", "max_findings": 1}, run_cfg(world)))
    assert judged({**RUN, "rule": "core.b"}, run_cfg(world))[:2] == ("unmet", "no evidence found")   # no record


def test_a_run_record_clause_no_longer_holds_when_the_bytes_change_or_it_ages(world):
    write(world, good(world))
    assert holds(judged(RUN, run_cfg(world)))
    assert holds(judged({**RUN, "fresh_days": 1}, run_cfg(world)))
    world.file.write_bytes(b"print('changed')\n")
    state, why, _ = judged(RUN, run_cfg(world))
    assert state == "stale" and "changed since it was checked" in why


def test_a_run_record_by_the_items_builder_never_meets_its_clause(world):
    write(world, good(world, by="Alder"))
    state, why, _ = judged(RUN, run_cfg(world))
    assert state == "unmet" and "own builder" in why
    assert holds(judged(RUN, run_cfg(world), owner="Birch"))           # must pass: anyone else's run counts


def test_a_run_record_clause_with_no_folder_or_no_card_is_unknown(world):
    write(world, good(world))
    assert judged(RUN, {"cards": str(world.cards)})[:1] == ("unknown",)
    state, why, _ = judged(RUN, run_cfg(world, cards=str(world.root / "no-cards")))
    assert state == "unknown" and "no rule card holds" in why
    state, why, _ = judged({**RUN, "rule": "core.zz"}, run_cfg(world))
    assert state == "unknown" and "core.zz" in why


# ---- verdicts ------------------------------------------------------------------------------------------------------
def files(root, verdicts, pieces=({"id": "p1", "originator": "Cedar"},)):
    v, p = root / "verdicts.jsonl", root / "pieces.jsonl"
    v.write_text("".join((x if isinstance(x, str) else json.dumps(x)) + "\n" for x in verdicts), encoding="utf-8")
    p.write_text("".join(json.dumps(x) + "\n" for x in pieces), encoding="utf-8")
    return {"verdicts": str(v), "pieces": str(p)}


def row(verdict="survived", by="Birch", at="2026-10-22T10:00:00Z", piece="p1"):
    return {"piece": piece, "verdict": verdict, "by": by, "at": at}


def test_a_verdict_clause_is_met_by_an_independent_survived_verdict(tmp_path):
    state, why, _ = judged(VERDICT, files(tmp_path, [row()]))
    assert (state, why) == ("met", "an independent verdict: survived")


def test_a_verdict_clause_is_not_met_by_a_kill_or_by_the_pieces_originator(tmp_path):
    assert judged(VERDICT, files(tmp_path, [row("killed")]))[0] == "unmet"
    assert judged(VERDICT, files(tmp_path, [row(by="Cedar")]))[:2] == ("unmet", "the verdict's attacker is the piece's originator")
    assert judged(VERDICT, files(tmp_path, [row(piece="p2")]))[:2] == ("unmet", "no evidence found")


def test_a_verdict_clause_no_longer_holds_after_a_later_kill(tmp_path):
    cfg = files(tmp_path, [row(), row("killed", at="2026-10-23T10:00:00Z")])
    assert judged(VERDICT, cfg)[:2] == ("stale", "a later verdict killed it")
    cfg = files(tmp_path, [row("killed", at="2026-10-23T10:00:00Z"), row()])   # file order is not time order
    assert judged(VERDICT, cfg)[0] == "stale"


def test_a_verdict_by_the_items_owner_or_creator_never_counts(tmp_path):
    state, why, _ = judged(VERDICT, files(tmp_path, [row(by="Alder")]))
    assert state == "unmet" and "own builder" in why
    assert judged(VERDICT, files(tmp_path, [row(by="Alder")]), owner="Birch")[0] == "met"


def test_a_missing_unreadable_or_closed_verdicts_file_is_unknown(tmp_path, monkeypatch):
    assert judged(VERDICT, {})[0] == "unknown"
    state, why, _ = judged(VERDICT, {"verdicts": str(tmp_path / "nope.jsonl"), "pieces": str(tmp_path / "p.jsonl")})
    assert state == "unknown" and "not there" in why
    cfg = files(tmp_path, [row()])
    (tmp_path / "pieces.jsonl").write_text("", encoding="utf-8")
    assert judged(VERDICT, cfg)[:2] == ("unknown", "the pieces file holds no piece p1")
    # an unusable line is a problem, never read; the rest still are
    cfg = files(tmp_path, ["{not json", {"piece": "p1"}, row()])
    state, _, ev = judged(VERDICT, cfg)
    assert state == "met" and [p["kind"] for p in ev.problems] == ["bad-row", "bad-row"]
    # a file in a place the person closed is not read
    shut = tmp_path / "shut"
    shut.mkdir()
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"closed": [str(shut)]}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    inside = files(shut, [row()])
    state, why, _ = judged(VERDICT, inside, ctx=closed.context(tmp_path))
    assert state == "unknown" and "closed" in why
    assert judged(VERDICT, cfg, ctx=closed.context(tmp_path))[0] == "met"   # must pass: outside it, read


def test_while_the_closures_are_not_known_no_verdicts_file_is_read_and_it_says_why(tmp_path, monkeypatch):
    cfg = files(tmp_path, [row()])
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(tmp_path / "no-sources.json"))     # no closures named anywhere
    for ctx in (None, closed.context(tmp_path), closed.ReadContext("", None)):
        state, why, _ = judged(VERDICT, cfg, ctx=ctx)                                # must refuse: unknown means closed
        assert state == "unknown" and "closed places are not named" in why, (ctx, why)
    assert judged(VERDICT, cfg, ctx=closed.ReadContext("", ()))[0] == "met"           # must pass: named, none closed


# ---- whose evidence: a maker or an originator the evidence does not name is unknown, never independent ----------
@pytest.mark.parametrize("by", [None, ""], ids=["no-by", "empty-by"])
def test_a_run_record_that_names_no_maker_is_unknown_never_independent(world, by):
    rec = good(world)
    if by is None:
        del rec["by"]
    else:
        rec["by"] = by
    write(world, rec)
    state, why, _ = judged(RUN, run_cfg(world))
    assert state == "unknown" and "names no maker" in why, why


def test_a_run_record_that_names_its_maker_still_counts(world):
    write(world, good(world, by="pat"))                                          # must pass
    assert holds(judged(RUN, run_cfg(world)))


@pytest.mark.parametrize("added_by", [None, "", "  "], ids=["none", "empty", "blank"])
def test_a_register_entry_that_names_no_maker_is_unknown(added_by):
    clause = {"kind": "jak-decision", "register": "J-20261020-1"}
    entry = {"id": "J-20261020-1", "words": "Yes, W-lab-1.", "computed_status": "in force", "added_by": added_by}
    item = {"id": "W-lab-1", "state": "review", "owner": "Alder", "creator": "Alder", "clauses": [clause]}
    got = evaluate(item, work.Evidence([entry]), NOW, NAMED)["clauses"][0]
    assert got["state"] == "unknown" and "names no maker" in got["why"]
    entry["added_by"] = "Rowan"                                                  # must pass: a named maker
    assert evaluate(item, work.Evidence([entry]), NOW, NAMED)["clauses"][0]["state"] == "met"


def test_a_piece_that_names_no_originator_is_unknown_never_independent(tmp_path):
    cfg = files(tmp_path, [row(by="Cedar")], pieces=({"id": "p1"},))
    state, why, _ = judged(VERDICT, cfg)
    assert state == "unknown" and "names no originator" in why, why
    cfg = files(tmp_path, [row(by="Cedar")], pieces=({"id": "p1", "originator": "  "},))
    assert judged(VERDICT, cfg)[0] == "unknown"
    cfg = files(tmp_path, [row(by="Cedar")], pieces=({"id": "p1", "originator": "Dogwood"},))
    assert judged(VERDICT, cfg)[:2] == ("met", "an independent verdict: survived")   # must pass


# ---- the estate counts ----------------------------------------------------------------------------------------------
def test_done_claimed_has_its_own_column_and_is_never_counted_as_done(tmp_path):
    from work_world import answer, build
    build(tmp_path)
    counts = answer(tmp_path)["counts"]
    assert counts["orchard"] == {"done (claimed)": 1, "proof no longer holds": 1, "done (your word)": 1}
    assert counts["lab"] == {"backlog": 3, "done (checked)": 1, "review": 2}
    assert not any("done" in c for c in counts.values())


# ---- review round 3 (G6), the readers' lows -------------------------------------------------------------------------
def test_a_rule_id_with_other_words_in_another_environment_is_unknown(world):
    import yaml
    write(world, good(world))
    assert holds(judged(RUN, run_cfg(world)))                                        # must pass: one environment
    other = {"environment": {"id": "other", "version": "1", "ratified_by": "pat"},
             "entries": [{"id": "core.a", "statement": "Other words entirely.", "ratified_by": "pat"}]}
    (world.cards / "other").mkdir()
    (world.cards / "other" / "SEMANTICS.yaml").write_text(yaml.safe_dump(other), encoding="utf-8")
    state, why, _ = judged(RUN, run_cfg(world))
    assert state == "unknown" and "more than one" in why, why


def test_a_clause_naming_a_piece_no_pieces_line_holds_is_unknown_with_or_without_a_verdict(tmp_path):
    cfg = files(tmp_path, [row()])                                          # verdicts on p1 only; pieces hold p1
    assert judged({"kind": "verdict", "piece": "p2"}, cfg)[:2] == ("unknown", "the pieces file holds no piece p2")
    assert judged(VERDICT, files(tmp_path, [row(piece="p3")]))[:2] == ("unmet", "no evidence found")   # must pass


def test_a_verdict_whose_time_is_not_a_time_is_a_problem_and_never_outranks_a_later_kill(tmp_path):
    cfg = files(tmp_path, [row("killed", at="2024-05-10T10:00:00Z"), row("survived", at="2024-5-9T10:00:00Z")])
    state, why, ev = judged(VERDICT, cfg)
    assert state == "unmet" and "killed" in why and [p["kind"] for p in ev.problems] == ["bad-row"]
    cfg = files(tmp_path, [row("survived", at="2024-05-09T10:00:00Z"), row("killed", at="2024-05-10T10:00:00+00:00")])
    assert judged(VERDICT, cfg)[0] == "stale"                                # must pass: both are times, kill newer


def test_a_blank_attacker_is_a_problem_never_an_independent_verdict(tmp_path):
    state, _, ev = judged(VERDICT, files(tmp_path, [row(by="  ")]))
    assert state != "met" and [p["kind"] for p in ev.problems] == ["bad-row"]

# ---- PM-DESIGN, follow-ups to A1, (c): a run record may name who built its checker (built_by) -------------------------
def test_a_run_record_naming_another_seat_as_its_checkers_builder_meets_its_clause(world):
    write(world, good(world, built_by="Cedar"))
    assert judged(RUN, run_cfg(world))[0] == "met"                                    # must pass: named, not the builder


def test_a_run_record_whose_checker_the_items_builder_built_never_meets_its_clause(world):
    write(world, good(world, built_by="Alder"))
    state, why, _ = judged(RUN, run_cfg(world))
    assert state == "unmet" and "checker was built by the item's builder" in why


def test_a_run_record_with_no_built_by_stays_unknown(world):
    write(world, good(world))
    assert holds(judged(RUN, run_cfg(world)))


def test_a_built_by_that_is_not_text_is_a_problem_and_earns_nothing(world):
    from test_sources_runs import load, rule_of
    write(world, good(world, built_by=["Cedar"]))
    out = load(world)
    assert rule_of(out)["runs"] == [] and [p["kind"] for p in out["problems"]] == ["bad-field"]