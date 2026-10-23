"""The proposed-change card (sources/change.py and its kind in the cards reader), on synthetic sources in tmp_path.

Every check has a must-pass arm and a must-refuse arm: what changes is counted and an unchanged tree counts nothing; the
evidence is current until a byte of it changes, and a file outside the person's own folders, a link or a folder is
never read; a card missing its component is refused; an outcome lands on its change card and on nothing else; a score
over no stated chance is None, never 0. Nothing here runs a command or calls git.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from semantext.sources import cards, change, gates, view
from semantext.sources.gates import World as GitWorld
from test_sources_cards import writers
from test_v2_view import World, append, touch


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "git-user"
    user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    w.rule = touch(w.base / "lab" / "rules" / "short.md", "Keep answers short.\n")
    return w


def proposal(id_="A-20261005-100000", **kw) -> dict:
    return {"id": id_, "at": "2026-10-05T10:00:00+01:00", "kind": "change", "title": "Shorter answers",
            "why": "The answers ran long in three sessions.", "component": "rule", "hypothesis": "A shorter card is read.",
            "trigger": "three long answers on 1 October", "regression_risk": "a needed detail is cut",
            "why_not_smaller": "a word in chat was tried and lost", "retroactive_check": "C-1 would have passed",
            "predicted": [{"measure": "answer length", "direction": "down", "p": 0.8},
                          {"measure": "corrections", "direction": "down", "p": 0.6}, "reading time"],
            "undo": {"commit": "abc1234"},
            "tree": {"before": {"CLAUDE.md": "long rule text"}, "after": {"CLAUDE.md": "short", "NEW.md": "x"},
                     "always_on": ["CLAUDE.md"]}, **kw}


def changes_file(world, seat: str) -> Path:
    """Where an agent keeps its proposed changes: changes.jsonl beside its requests file, in its own home."""
    return world.file(seat).with_name("changes.jsonl")


def by_change(key: str) -> dict:
    return {c["key"]: c for c in view.answer("waiting")["change_records"]}[key]


def by_card(key: str) -> dict:
    return {c["key"]: c for c in view.answer("waiting")["cards"]}[key]


def ask_about(id_, change_id, **kw) -> dict:
    return {"id": id_, "at": "2026-10-05T11:00:00+01:00", "kind": "decision", "title": "Adopt it?", "why": "see it",
            "question": "Adopt the change?", "options": ["yes", "no"], "change": change_id, **kw}


# ---------------------------------------------------------------- what changes
def test_what_changes_is_counted_from_the_two_trees():
    got = change.diff_summary({"a": "1", "b": "2", "c": "3"}, {"b": "2", "c": "three", "d": "4"}, ["c", "x"])
    assert got == {"added": ["d"], "removed": ["a"], "changed": ["c"], "always_on_char_delta": 4}
    # must-refuse: the same tree twice changes nothing
    assert change.diff_summary({"a": "1"}, {"a": "1"}, ["a"]) == {"added": [], "removed": [], "changed": [],
                                                                  "always_on_char_delta": 0}


# ---------------------------------------------------------------- is the evidence current
def test_the_fingerprint_follows_the_bytes_and_reads_only_plain_files_inside(tmp_path):
    a, b = touch(tmp_path / "a.txt", "one"), touch(tmp_path / "b.txt", "two")
    roots = [os.path.normcase(str(tmp_path))]
    first = change.fingerprint([str(a), str(b)], roots)["digest"]
    assert first and change.fingerprint([str(b), str(a)], roots)["digest"] == first     # the order named is not read
    b.write_text("TWO", encoding="utf-8")
    assert change.fingerprint([str(a), str(b)], roots)["digest"] != first               # must pass: a byte moves it
    gone = change.fingerprint([str(a), str(tmp_path / "gone.txt")], roots)
    assert gone["digest"] is None and "not there" in gone["why"]          # an absent file is unknown, never current
    # must-refuse: a path that is not full, one outside the roots, a folder, too many files, nothing named
    assert change.fingerprint(["a.txt"], roots)["digest"] is None
    assert change.fingerprint([str(a)], [os.path.normcase(str(tmp_path / "elsewhere"))])["digest"] is None
    assert "outside" in change.fingerprint([str(a)], [os.path.normcase(str(tmp_path / "x"))])["why"]
    (tmp_path / "dir").mkdir()
    assert change.fingerprint([str(tmp_path / "dir")], roots)["digest"] is None
    assert change.fingerprint([str(a)] * (change.MAX_FILES + 1), roots)["digest"] is None
    assert change.fingerprint([], roots)["digest"] is None
    try:
        os.symlink(a, tmp_path / "link.txt")
    except (OSError, NotImplementedError):
        return
    assert "link" in change.fingerprint([str(tmp_path / "link.txt")], roots)["why"]


def test_a_card_is_stale_once_its_evidence_moves(world):
    rule = str(world.rule)
    digest = change.fingerprint([rule], [str(world.base / "lab")])["digest"]   # lab is a project Alder works in
    assert digest
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal(evidence={"files": [rule], "digest": digest}))
    c = by_change("Alder/A-20261005-100000")
    assert c["kind"] == "change" and c["asked_in"] == [] and c["decided"] is False
    assert c["change"]["freshness"]["state"] == "current"
    world.rule.write_text("Keep answers very short.\n", encoding="utf-8")
    assert by_change("Alder/A-20261005-100000")["change"]["freshness"]["state"] == "stale"   # must refuse: not current
    # must-refuse: evidence outside the person's projects and homes is not read, so it is unknown, never current
    outside = touch(world.root / "elsewhere" / "x.txt", "x")
    append(changes_file(world, "Alder"), proposal("A-20261005-110000", evidence={
        "files": [str(outside)], "digest": change.fingerprint([str(outside)], [str(world.root)])["digest"]}))
    far = by_change("Alder/A-20261005-110000")["change"]["freshness"]
    assert far["state"] == "unknown" and "outside" in far["why"]


# ---------------------------------------------------------------- the card
def test_a_change_card_carries_its_fields_and_is_refused_without_them(world):
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal(), proposal("A-20261005-120000", component=None),
           proposal("A-20261005-130000", undo={"command": "git reset --hard"}, predicted="shorter"))
    out = cards.load(world.cfg())
    got = {c["id"]: c for c in out["changes"]}
    assert all(c["kind"] != "change" for c in out["cards"])                   # a record, never a card that waits
    ch = got["A-20261005-100000"]["change"]
    assert ch["component"] == "rule" and ch["undo"] == {"commit": "abc1234"} and ch["prune"] is False
    assert ch["predicted"][0] == {"measure": "answer length", "direction": "down", "p": 0.8}
    assert ch["predicted"][2] == {"measure": "reading time", "direction": None, "p": None}
    assert ch["what_changes"] == {"added": ["NEW.md"], "removed": [], "changed": ["CLAUDE.md"],
                                  "always_on_char_delta": -9}
    # must-refuse: no component, no card; an undo that is a command is no undo, and is said, never run
    assert "A-20261005-120000" not in got
    assert any(p["kind"] == "missing field" and "component" in p["text"] for p in out["problems"])
    bad = got["A-20261005-130000"]
    assert bad["change"]["undo"] is None and bad["change"]["predicted"] == []
    said = [p["text"] for p in out["problems"] if p.get("shown")]
    assert any("undo is neither" in t for t in said) and any("predicted measures are not a list" in t for t in said)


def test_outcomes_are_new_entries_on_their_change_card_and_nothing_else(world):
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal(),
           {"outcome": "A-20261005-100000", "at": "2026-10-06T10:00:00Z",
            "moved": {"answer length": "down", "corrections": "up"}, "regressions": ["a needed detail was cut"]},
           {"outcome": "A-20261005-100000", "at": "2026-10-07T10:00:00Z", "moved": {"answer length": "down",
            "corrections": "up"}, "regressions": ["a needed detail was cut"], "undone": True},
           {"outcome": "A-20261001-100000", "at": "x"},                  # a decision card's id, not a change's
           {"outcome": "A-20261005-100000", "moved": {"answer length": "sideways"}})
    out = cards.load(world.cfg())
    c = next(x for x in out["changes"] if x["id"] == "A-20261005-100000")
    assert [o["undone"] for o in c["outcomes"]] == [False, True]                       # the undo is one more entry
    j = c["judged"]
    assert [(m["measure"], m["hit"]) for m in j["measures"]] == [("answer length", True), ("corrections", False),
                                                                   ("reading time", None)]
    assert j["terms"] == pytest.approx([(0.8 - 1) ** 2, (0.6 - 0) ** 2])
    assert j["unpredicted_regressions"] == ["a needed detail was cut"] and j["undone"] is True
    # must-refuse: an outcome on a decision card, and one with a move that is not up, down or none
    kinds = [p["kind"] for p in out["problems"]]
    assert kinds.count("outcome with no change") == 1 and kinds.count("bad outcome") == 1
    tally = next(s for s in out["seats"] if s["seat"] == "Alder")["changes"]
    assert tally["lines"] == tally["records"] + tally["outcomes"] + tally["refused"] == 5


def test_the_score_per_agent_is_a_brier_score_with_its_count(world):
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal(),
           {"outcome": "A-20261005-100000", "moved": {"answer length": "down", "corrections": "up"}},
           proposal("A-20261005-140000", predicted=["no chance stated"]),
           {"outcome": "A-20261005-140000", "moved": {"no chance stated": "up"}})
    touch(changes_file(world, "Birch"))
    append(changes_file(world, "Birch"), proposal("B-20261005-100000"))
    append(world.file("Birch"), ask_about("B-20261005-110000", "B-20261005-100000"),
           {"close": "B-20261005-110000", "at": "2026-10-05T12:00:00Z", "how": "declined"})
    w = view.answer("waiting")
    assert w["changes"]["Alder"] == {"filed": 2, "decided": 2, "brier": round(((0.8 - 1) ** 2 + 0.6 ** 2) / 2, 4),
                                     "scored": 2}
    # must-refuse: a card with no stated chance, or no outcome, is never scored as 0
    assert w["changes"]["Birch"] == {"filed": 1, "decided": 1, "brier": None, "scored": 0}
    assert change.score([{"kind": "decision", "seat": "X"}]) == {}


# ---------------------------------------------------------------- where a change lives, and who asks about it
def test_a_change_or_an_outcome_in_the_requests_file_is_a_problem_that_says_where_it_belongs(world):
    append(world.file("Alder"), proposal(), {"outcome": "A-20261005-100000", "moved": {}})
    out = cards.load(world.cfg())
    assert out["changes"] == [] and "A-20261005-100000" not in [c["id"] for c in out["cards"]]
    said = [p for p in out["problems"] if p["kind"] == cards.ELSEWHERE]
    assert len(said) == 2 and all(Path(p["source"]) == world.file("Alder") for p in said)
    # must pass: the same lines in changes.jsonl are a record and its outcome
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal(), {"outcome": "A-20261005-100000", "moved": {}})
    again = cards.load(world.cfg())
    assert [c["id"] for c in again["changes"]] == ["A-20261005-100000"] and len(again["changes"][0]["outcomes"]) == 1
    # must-refuse: a decision or a command in changes.jsonl is not a change
    append(changes_file(world, "Alder"), ask_about("A-20261005-120000", "A-20261005-100000"))
    assert [p["kind"] for p in cards.load(world.cfg())["problems"]].count("not a change") == 1


def test_the_folder_is_the_seat_and_a_seat_field_never_is(world):
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal(seat="Birch"), proposal("A-20261005-110000", seat="Alder"))
    out = cards.load(world.cfg())
    assert [(c["seat"], c["id"]) for c in out["changes"]] == [("Alder", "A-20261005-100000"),
                                                              ("Alder", "A-20261005-110000")]
    said = [p["text"] for p in out["problems"] if p["kind"] == "seat field"]
    assert len(said) == 1 and "the folder stands" in said[0]                   # must-refuse: the field is ignored


def test_a_decision_naming_a_change_links_both_ways_and_an_unknown_id_is_a_problem(world):
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal())
    append(world.file("Alder"), ask_about("A-20261005-110000", "A-20261005-100000"),
           ask_about("A-20261005-120000", "A-20991231-000000"))
    asked = by_card("Alder/A-20261005-110000")
    assert asked["change_id"] == "A-20261005-100000" and asked["state"] == "waiting"
    assert by_change("Alder/A-20261005-100000")["asked_in"] == ["Alder/A-20261005-110000"]
    # must-refuse: an id that names no change is a problem on the card, and nothing is linked
    lost = by_card("Alder/A-20261005-120000")
    assert lost["change_id"] is None and lost["change_unknown"] == "A-20991231-000000"
    assert any("names the change A-20991231-000000" in n for n in lost["notes"])
    # must-refuse: another agent's change of the same id is not this agent's, and is not linked
    append(world.file("Birch"), ask_about("B-20261005-110000", "A-20261005-100000"))
    assert by_card("Birch/B-20261005-110000")["change_id"] is None
    assert by_change("Alder/A-20261005-100000")["asked_in"] == ["Alder/A-20261005-110000"]


def test_one_build_digests_at_most_the_cap_of_records_per_agent(world, monkeypatch):
    monkeypatch.setattr(view, "RECORD_CAP", 2)
    rule = str(world.rule)
    digest = change.fingerprint([rule], [str(world.base / "lab")])["digest"]
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), *(proposal(f"A-20261005-10000{i}", evidence={"files": [rule], "digest": digest})
                                           for i in range(3)), proposal("A-20261005-200000"))
    got = {c["id"]: c["change"]["freshness"] for c in view.answer("waiting")["change_records"]}
    assert got["A-20261005-100000"]["state"] == got["A-20261005-100001"]["state"] == "current"   # must pass
    assert got["A-20261005-100002"] == {"state": "unknown", "why": "not checked: over the cap of 2 change records "
                                        "whose evidence one page build digests for one agent"}
    assert got["A-20261005-200000"] is None                                  # a record with no evidence uses none


def test_one_build_reads_at_most_its_byte_budget_of_evidence(world, monkeypatch):
    a = touch(world.base / "lab" / "notes" / "a.md", "a" * 20)
    b = touch(world.base / "lab" / "notes" / "b.md", "b" * 20)
    lab = [str(world.base / "lab")]
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"),
           proposal("A-20261005-100000", evidence={"files": [str(a)], "digest": change.fingerprint([str(a)], lab)["digest"]}),
           proposal("A-20261005-100001", evidence={"files": [str(b)], "digest": change.fingerprint([str(b)], lab)["digest"]}))

    def states(budget: int) -> dict:
        monkeypatch.setattr(view, "READ_BUDGET", budget)
        change._CACHE.clear()                                    # a cached file costs nothing; measure the reads
        return {c["id"]: c["change"]["freshness"] for c in view.answer("waiting")["change_records"]}

    got = states(30)
    assert got["A-20261005-100000"]["state"] == "current"
    assert got["A-20261005-100001"] == {"state": "unknown", "why": "not checked: over the read budget",
                                        "files": [str(b)]}                    # must refuse: past the budget
    both = states(40)
    assert both["A-20261005-100000"]["state"] == both["A-20261005-100001"]["state"] == "current"   # must pass


def test_a_changes_file_that_is_a_hard_link_is_not_read(world):
    touch(changes_file(world, "Alder"))
    append(changes_file(world, "Alder"), proposal())
    try:
        os.link(changes_file(world, "Alder"), changes_file(world, "Birch"))
    except OSError as e:
        pytest.skip(f"no hard link here: {e}")
    out = cards.load(world.cfg())
    assert out["changes"] == []                                              # neither name is read: either could lie
    assert sorted(Path(p["source"]).parent.name for p in out["problems"] if p["kind"] == "link") == ["alder", "birch"]
    os.unlink(changes_file(world, "Birch"))                                  # must pass: one name again, read again
    assert [c["seat"] for c in cards.load(world.cfg())["changes"]] == ["Alder"]


def test_the_change_module_runs_nothing_and_writes_nothing():
    source = Path(change.__file__).read_text(encoding="utf-8")
    imported = {n.names[0].name.split(".")[0] for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Import)}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"subprocess", "shutil", "pty", "multiprocessing"}
    assert writers(source) == [] and "Licensed under the Apache License, Version 2.0" in source and "CHANGED" in source
    # must-refuse: the same checks find a planted import and a planted write
    planted = source + "\nimport subprocess\nPath('x').write_text('y')\n"
    assert "subprocess" in {n.names[0].name for n in ast.walk(ast.parse(planted)) if isinstance(n, ast.Import)}
    assert writers(planted) == ["write_text"]
