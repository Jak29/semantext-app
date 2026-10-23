"""The Rules reader: rule cards read where they lie, every defect reported, nothing written.

Every fixture is made here, in a temporary folder. Each check has an arm that must pass (a good card is read as it
says) and an arm that must refuse (a planted defect is reported, or a wrong value is told apart from the right one)."""
import copy
import json
import os
import stat
import sys
import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from semantext.sources import rules


# ---------------------------------------------------------------- fixtures
def rule(rid, words="Ask before you act on a guess.", **more):
    return {"id": rid, "kind": "ruling", "statement": words, "applies_when": "Always.", "ratified_by": "pat", **more}


def case(cid, message="Tidy it up?", **more):
    return {"case": cid, "message": message, "expected": "Only tidy.", "forbidden": "Rewrite it.", **more}


def doc(name, entries=(), tests=(), **env):
    head = {"id": name, "version": "1.0.0", "status": "ratified", "ratified_by": "pat", "inherits": [], **env}
    return {"environment": head, "entries": list(entries), "tests": list(tests)}


def put(root: Path, name: str, card) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    text = card if isinstance(card, str) else yaml.safe_dump(card, sort_keys=False)
    (folder / "SEMANTICS.yaml").write_text(text, encoding="utf-8")
    return folder / "SEMANTICS.yaml"


def read(root: Path) -> dict:
    return rules.load({"cards": str(root)})


def read_within(root: Path, seconds: float = 20) -> dict:
    """read(), but a reader that never finishes is a failed test and not a stuck one (a card whose aliases are not
    bounded would take that long)."""
    box: dict = {}
    worker = threading.Thread(target=lambda: box.update(out=read(root)), daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), f"the reader was still working after {seconds} seconds"
    return box["out"]


def envs(out: dict) -> dict:
    return {e["name"]: e for e in out["environments"]}


def kinds(out: dict) -> list[str]:
    return [p["kind"] for p in out["problems"]]


FOLDED = """\
environment:
  id: core
  version: 1.0.0
  status: ratified
  ratified_by: pat
entries:
  - id: core.diligence
    kind: ruling
    statement: >-
      A grant of judgement lets the agent decide.  It does not waive
      reading before acting.
    ratified_by: pat
"""


# ---------------------------------------------------------------- the source itself
def test_a_missing_cards_key_turns_the_source_off(tmp_path):
    off = rules.load({})
    assert off["off"] is True and off["environments"] == [] and off["problems"] == []
    on = read(tmp_path)                       # must refuse to call a key that is there "off"
    assert on["off"] is False and on["environments"] == [] and on["problems"] == []


@pytest.mark.parametrize("where", ["nowhere", "a-file.txt"])
def test_a_cards_folder_that_is_not_a_folder_is_one_problem_not_a_crash(tmp_path, where):
    (tmp_path / "a-file.txt").write_text("not a folder", encoding="utf-8")
    out = read(tmp_path / where)
    assert out["environments"] == [] and kinds(out) == ["no-folder"]
    assert out["problems"][0]["source"] == str(tmp_path / where)


def test_the_result_is_plain_data_even_when_a_card_holds_dates_and_times(tmp_path):
    put(tmp_path, "core", """\
environment:
  id: core
  version: 1.0.0
  status: ratified
  ratified_by: pat
  ratification: {date: 2026-09-29, words: "yes to all", mode: one yes, record: r.md}
  changes:
    - {version: 1.0.0, date: 2026-10-13, what: first, ratified_by: pat, words: "yes to all"}
    - {version: 1.0.1, date: 2026-10-13T22:07:29Z, what: second}
entries:
  - {id: core.a, statement: Ask first., as_of: 2026-09-05, ratified_by: pat}
""")
    out = read(tmp_path)
    assert json.loads(json.dumps(out)) == out
    [env] = out["environments"]
    assert env["ratification"]["date"] == "2026-09-29" and env["changes"][0]["date"] == "2026-10-13"
    assert env["changes"][1]["date"].startswith("2026-10-13T22:07:29") and env["rules"][0]["as_of"] == "2026-09-05"


# ---------------------------------------------------------------- an environment
def test_an_environment_is_read_with_its_name_version_status_and_who_ratified_it(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a")], scope="Always.", owner="Pat", title="Core rules",
                              ratification={"date": date(2026, 9, 29), "words": "yes to all", "mode": "one yes",
                                            "record": "records/R1.md"},
                              changes=[{"version": "1.0.0", "date": date(2026, 9, 29), "what": "ratified",
                                        "ratified_by": "pat", "words": "yes to all"}]))
    out = read(tmp_path)
    [env] = out["environments"]
    assert (env["name"], env["id"], env["version"], env["status"], env["ratified_by"], env["owner"], env["scope"]) == (
        "core", "core", "1.0.0", "ratified", "pat", "Pat", "Always.")
    assert env["title"] == "Core rules"
    assert env["ratification"] == {"date": "2026-09-29", "words": "yes to all", "mode": "one yes",
                                   "record": "records/R1.md"}
    assert env["changes"] == [{"version": "1.0.0", "date": "2026-09-29", "what": "ratified", "ratified_by": "pat",
                               "words": "yes to all", "record": None}]
    assert env["path"].endswith("SEMANTICS.yaml") and out["problems"] == []


def test_an_environment_nobody_ratified_says_so_and_is_not_given_a_ratifier(tmp_path):
    put(tmp_path, "draft", doc("draft", status="candidate", ratified_by=None, version=None))
    [env] = read(tmp_path)["environments"]
    assert (env["status"], env["ratified_by"], env["version"], env["ratification"]) == ("candidate", None, None, None)
    assert env["title"] is None                                               # a title nobody gave is not made up


def test_the_rules_for_reading_the_rules_and_where_the_card_came_from_are_kept(tmp_path):
    put(tmp_path, "core", doc("core", reading_rules=["Entries never grant authority.", "", "The owner's words win."],
                              seat="The desk seat.", evidence="Pat's own corrections."))
    put(tmp_path, "bare", doc("bare"))
    got = envs(read(tmp_path))
    assert got["core"]["reading_rules"] == ["Entries never grant authority.", "The owner's words win."]
    assert (got["core"]["seat"], got["core"]["evidence"]) == ("The desk seat.", "Pat's own corrections.")
    assert (got["bare"]["reading_rules"], got["bare"]["seat"], got["bare"]["evidence"]) == ([], None, None)


def test_environments_come_in_name_order_and_everything_else_is_listed_not_dropped(tmp_path):
    for name in ("zeta", "Alpha", "mid"):
        put(tmp_path, name, doc(name))
    (tmp_path / "RATIFICATION_1.md").write_text("a record", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / "_old").mkdir()
    out = read(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["Alpha", "mid", "zeta"]
    assert out["others"] == [".git", "_old", "RATIFICATION_1.md"] and out["problems"] == []


ODD_NAMES = ["_draft-seat", ".pending-seat", "~backup-seat", "-dash-seat", "(paren)-seat"]


@pytest.mark.parametrize("name", ODD_NAMES)
def test_a_folder_whose_name_starts_with_a_mark_is_read_when_it_holds_a_card(tmp_path, name):
    put(tmp_path, "core", doc("core", [rule("core.a")]))
    put(tmp_path, name, doc(name, [rule("odd.a", words="Odd, but a card.")], inherits=["core@1.0.0"]))
    (tmp_path / ".git").mkdir()                                              # beside one that is not an environment
    out = read(tmp_path)
    got = envs(out)
    assert sorted(got) == sorted(["core", name]) and out["problems"] == []
    assert got[name]["rules"][0]["words"] == "Odd, but a card." and got[name]["parents"][0]["state"] == "current"
    assert out["others"] == [".git"]                                          # it is not listed aside with them


@pytest.mark.parametrize("name", ODD_NAMES)
def test_a_card_in_such_a_folder_that_cannot_be_read_is_a_problem_and_never_listed_aside(tmp_path, name):
    bad = put(tmp_path, name, "environment: [unclosed\n")
    out = read(tmp_path)
    assert out["environments"] == [] and kinds(out) == ["bad-yaml"] and out["problems"][0]["source"] == str(bad)
    assert out["others"] == []


def test_a_folder_with_a_mark_in_its_name_and_a_folder_where_its_card_should_be_is_no_card(tmp_path):
    (tmp_path / "_odd" / "SEMANTICS.yaml").mkdir(parents=True)
    out = read(tmp_path)
    assert out["environments"] == [] and kinds(out) == ["no-card"] and out["others"] == []


def test_a_folder_with_a_mark_whose_card_cannot_be_told_about_is_read_not_listed_aside(tmp_path, monkeypatch):
    (tmp_path / "_odd").mkdir()
    (tmp_path / ".git").mkdir()
    assert read(tmp_path)["others"] == [".git", "_odd"]                       # must pass: told there is no card
    monkeypatch.setattr(rules, "_holds_card", lambda folder: None if folder.name == "_odd" else False)
    out = read(tmp_path)                                                       # must refuse: not told, so it is said
    assert out["others"] == [".git"] and kinds(out) == ["no-card"]


@pytest.mark.parametrize("marks", [1, 2])
def test_a_card_saved_with_a_byte_order_mark_is_read_even_if_a_tool_added_it_twice(tmp_path, marks):
    folder = tmp_path / "core"
    folder.mkdir()
    (folder / "SEMANTICS.yaml").write_bytes(b"\xef\xbb\xbf" * marks + FOLDED.encode("utf-8"))
    out = read(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["core"] and out["problems"] == []


def test_an_invisible_character_that_is_not_a_byte_order_mark_is_not_quietly_dropped(tmp_path):
    put(tmp_path, "core", "\u200b" + FOLDED)                    # a zero-width space before the first key
    out = read(tmp_path)
    assert out["environments"] == [] and kinds(out) == ["not-a-card"]


# ---------------------------------------------------------------- a rule's words
def test_a_rules_words_are_whole_with_only_spaces_and_line_breaks_joined(tmp_path):
    put(tmp_path, "core", FOLDED)
    [r] = read(tmp_path)["environments"][0]["rules"]
    assert r["words"] == "A grant of judgement lets the agent decide. It does not waive reading before acting."
    assert (r["id"], r["kind"], r["ratified_by"], r["candidate"]) == ("core.diligence", "ruling", "pat", False)


def test_one_changed_character_in_a_rule_shows_in_its_words(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    put(a, "core", FOLDED)
    put(b, "core", FOLDED.replace("judgement", "judgemend"))
    wa = read(a)["environments"][0]["rules"][0]["words"]
    wb = read(b)["environments"][0]["rules"][0]["words"]
    assert wa != wb and [i for i, (x, y) in enumerate(zip(wa, wb)) if x != y] == [wa.index("judgement") + 8]


def test_the_spaces_that_are_joined_are_exactly_the_ones_the_top_of_the_file_lists():
    folded = {c for c in map(chr, range(0x110000)) if ("a" + c + "b").split() == ["a", "b"]}
    assert set(rules.SPACES) == folded                                      # the list is what this Python folds
    assert len(rules.SPACES) == len(set(rules.SPACES)) == 29 and "the 29" in rules.__doc__
    for token in ("U+0009", "U+000D", "U+001C", "U+001F", "U+0020", "U+0085", "U+00A0", "U+1680", "U+2000", "U+200A",
                  "U+2028", "U+2029", "U+202F", "U+205F", "U+3000"):
        assert token in rules.__doc__                                       # and the top of the file names them


def test_every_listed_space_is_joined_into_one_plain_space_and_no_other_character_is_touched(tmp_path):
    unlisted = ["\u200b", "\ufeff", "\u00ad", "\u180e", "\u2060", "\u0430"]    # zero-width, soft hyphen, a Cyrillic "a"
    spaces = rules.SPACES
    put(tmp_path, "core", doc("core", [rule(f"core.s{i}", words=f"{c}one{c}{c}two{c}") for i, c in enumerate(spaces)]
                                      + [rule(f"core.k{i}", words=f"one{c}two") for i, c in enumerate(unlisted)]))
    out = read(tmp_path)
    got = {r["id"]: r["words"] for r in out["environments"][0]["rules"]}
    assert out["problems"] == [] and len(got) == len(spaces) + len(unlisted)
    assert [f"U+{ord(c):04X}" for i, c in enumerate(spaces) if got[f"core.s{i}"] != "one two"] == []
    assert [f"U+{ord(c):04X}" for i, c in enumerate(unlisted) if got[f"core.k{i}"] != f"one{c}two"] == []


def test_a_rule_nobody_ratified_is_a_candidate_and_one_that_was_is_not(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a"), rule("core.b", ratified_by=None),
                                      rule("core.c", ratified_by="")]))
    got = {r["id"]: (r["candidate"], r["ratified_by"]) for r in read(tmp_path)["environments"][0]["rules"]}
    assert got == {"core.a": (False, "pat"), "core.b": (True, None), "core.c": (True, None)}


@pytest.mark.parametrize("said", [False, 0, [], " ", "   ", ["", " "], "no"])
def test_a_ratifier_that_names_nobody_ratifies_nothing_but_a_name_does(tmp_path, said):
    """A `false` names nobody, the way an empty field or one of only spaces does (the top of rules.py says so). The
    word no is a name like any other: the card said it."""
    put(tmp_path, "core", doc("core", [rule("core.a", ratified_by=copy.copy(said))],
                              ratified_by=copy.copy(said)))                   # one object each: no alias is written
    [env] = read(tmp_path)["environments"]
    [r] = env["rules"]
    named = said == "no"
    assert (r["candidate"], r["ratified_by"]) == (not named, "no" if named else None)
    assert env["ratified_by"] == ("no" if named else None)


def test_a_rule_switched_off_or_undone_is_listed_as_not_live_not_dropped(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.on"), rule("core.off", enabled=False),
                                      rule("core.undone", enabled=False, archived=True)]))
    got = {r["id"]: r["live"] for r in read(tmp_path)["environments"][0]["rules"]}
    assert got == {"core.on": True, "core.off": False, "core.undone": False}


def test_a_rule_carries_when_it_applies_where_it_came_from_and_when_it_may_have_lapsed(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a", applies_when="A first-person future statement.",
                                            as_of=date(2026, 9, 5),
                                            provenance={"type": "EXPLICIT", "quote": "I'll start next week."}),
                                      rule("core.b", provenance={"type": "INFERRED", "quote": None})]))
    a, b = read(tmp_path)["environments"][0]["rules"]
    assert (a["applies_when"], a["as_of"], a["basis"], a["quote"]) == (
        "A first-person future statement.", "2026-09-05", "EXPLICIT", "I'll start next week.")
    assert (b["as_of"], b["basis"], b["quote"]) == (None, "INFERRED", None)


def test_the_rules_of_an_agents_own_layer_are_read_and_marked(tmp_path):
    card = doc("core", [rule("core.a")])
    card["agents"] = {"reviewer": {"entries": [{"id": "core.reviewer.learned-1", "kind": "rule",
                                                "statement": "Cite the file and the line."}]}}
    put(tmp_path, "core", card)
    own, layered = read(tmp_path)["environments"][0]["rules"]
    assert (own["agent"], layered["agent"], layered["id"], layered["candidate"]) == (
        None, "reviewer", "core.reviewer.learned-1", True)


@pytest.mark.parametrize("relation,kept", [
    ({"specializes": "core.a"}, {"specializes": ["core.a"]}),
    ({"specializes": ["core.a", "core.b"], "replaces": ["core.old"]},
     {"specializes": ["core.a", "core.b"], "replaces": ["core.old"]}),
    ({"specializes": [], "replaces": None}, {}),                  # nothing named is nothing kept
    (None, {}),
])
def test_how_a_rule_stands_to_other_rules_is_kept_as_the_card_says_it(tmp_path, relation, kept):
    put(tmp_path, "core", doc("core", [rule("core.x", relation=relation)]))
    out = read(tmp_path)
    assert out["environments"][0]["rules"][0]["relation"] == kept and out["problems"] == []


# ---------------------------------------------------------------- ids
def test_a_number_written_without_quotes_is_an_id_shown_as_its_digits(tmp_path):
    put(tmp_path, "2026", """\
environment:
  id: 2026
  version: 1.0.0
entries:
  - id: 7
    statement: Seven.
    ratified_by: pat
  - id: core.b
    statement: Cites the case that names seven.
    ratified_by: pat
    provenance: {cases: [8]}
tests:
  - case: 8
    message: A message.
    rules: [7]
""")
    out = read(tmp_path)
    [env] = out["environments"]
    assert out["problems"] == [] and (env["name"], env["id"]) == ("2026", "2026")
    assert [(r["id"], r["held"]) for r in env["rules"]] == [("7", "checked"), ("core.b", "checked")]


NOT_IDS = [("7.5", "a decimal number", "7.5"), ("yes", "a yes/no", "True"), ("2026-09-05", "a date", "2026-09-05"),
           ("[a, b]", "a list", "a, b"), ("{a: b}", "a section", "a: b")]


@pytest.mark.parametrize("value,reads,shown", NOT_IDS)
def test_a_rule_id_that_is_not_text_is_a_problem_that_names_it_and_a_missing_one_says_so(tmp_path, value, reads, shown):
    put(tmp_path, "core", f"environment:\n  id: core\nentries:\n  - id: {value}\n    statement: Ask first.\n"
                          "  - id: core.ok\n    statement: Fine.\n  - statement: Nobody named me.\n")
    out = read(tmp_path)
    first, second = out["problems"]
    assert [p["kind"] for p in out["problems"]] == ["bad-rule", "bad-rule"]
    assert first["text"].startswith("rule 1 has an id that reads as " + reads) and shown in first["text"]
    assert first["text"].endswith("not text; put it in quotes")
    assert second["text"] == "rule 3 has no id"                         # an id that is missing says so, and no more
    assert [r["id"] for r in out["environments"][0]["rules"]] == ["core.ok"]


@pytest.mark.parametrize("value,reads,shown", NOT_IDS)
def test_an_environment_id_that_is_not_text_is_a_problem_that_names_it(tmp_path, value, reads, shown):
    put(tmp_path, "bad", f"environment:\n  id: {value}\n")
    [p] = read(tmp_path)["problems"]
    assert p["kind"] == "not-a-card"
    assert p["text"].startswith("the 'environment' section has an id that reads as " + reads) and shown in p["text"]


def test_a_card_without_an_environment_section_or_without_an_id_says_which(tmp_path):
    put(tmp_path, "no-id", "environment:\n  version: 1\n")
    put(tmp_path, "no-section", "- a\n- b\n")
    said = {Path(p["source"]).parent.name: p["text"] for p in read(tmp_path)["problems"]}
    assert said == {"no-id": "the 'environment' section has no id",
                    "no-section": "it is not a rule card: it needs an 'environment' section with an id"}


def test_an_id_has_its_spaces_joined_like_any_text_and_a_reference_finds_it_however_it_is_spaced(tmp_path):
    put(tmp_path, "core", doc("core", [
        rule("\u00a0core.a ", provenance={"cases": [" C-1\u3000"]}),
        rule("core.b  c", provenance={"cases": ["C-2"]}),                      # two spaces inside become one
    ], [case("C-1", rules=["core.a"]), case("C-2", rules=["core.b \u2003c"])]))
    out = read(tmp_path)
    assert out["problems"] == []
    assert [(r["id"], r["held"]) for r in out["environments"][0]["rules"]] == [("core.a", "checked"),
                                                                              ("core.b c", "checked")]


# ---------------------------------------------------------------- the corrections kept as tests
def test_a_correction_is_listed_with_its_message_and_the_readings(tmp_path):
    put(tmp_path, "core", doc("core", [], [
        {"case": "C-1", "message": "Is it\n\nsafe?", "expected": {"act": "Question", "authority": [],
                                                                  "operation": "discuss"}, "forbidden": "Run it."},
        {"case": "C-2", "message_excerpt": "part of a longer message", "expected": "Only tidy."},
        {"case": "C-3", "message": "Tidy it?", "correction": "Format only.", "expected": "Format.", "forbidden": None},
    ]))
    c1, c2, c3 = read(tmp_path)["environments"][0]["cases"]
    assert (c1["message"], c1["excerpt"], c1["expected"], c1["forbidden"]) == (
        "Is it safe?", False, "act: Question; operation: discuss", "Run it.")
    assert (c2["message"], c2["excerpt"], c2["forbidden"]) == ("part of a longer message", True, "")
    assert (c3["correction"], c3["forbidden"], c3["rules"]) == ("Format only.", "", [])


def test_the_owners_own_words_on_a_correction_and_where_they_came_from_are_kept(tmp_path):
    put(tmp_path, "core", doc("core", [], [
        case("C-1", his_correction="Not that, this.", his_refinement="And slower.", source="A chat, 2026-09-29."),
        case("C-2", correction="Plain.", his_correction="The plain field says it first."),
        case("C-3"),
    ]))
    c1, c2, c3 = read(tmp_path)["environments"][0]["cases"]
    assert (c1["correction"], c1["refinement"], c1["source"]) == (
        "Not that, this.", "And slower.", "A chat, 2026-09-29.")
    assert (c2["correction"], c2["refinement"]) == ("Plain.", "")             # the first field that says anything
    assert (c3["correction"], c3["refinement"], c3["source"]) == ("", "", None)   # words nobody wrote are not made up


# ---------------------------------------------------------------- how firmly a rule is held
def test_a_rule_is_checked_when_a_correction_kept_as_a_test_is_tied_to_it(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a", provenance={"cases": ["C-1", "C-2"]})], [case("C-1")]))
    [env] = read(tmp_path)["environments"]
    [r] = env["rules"]
    assert r["held"] == "checked"
    assert r["cases"] == [{"id": "C-1", "kept_in": ["core"]}, {"id": "C-2", "kept_in": []}]
    assert env["cases"][0]["rules"] == ["core.a"]


def test_a_case_that_no_card_keeps_does_not_make_a_rule_checked(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a", provenance={"cases": ["C-9"]})], [case("C-1")]))
    [env] = read(tmp_path)["environments"]
    [r] = env["rules"]
    assert r["held"] == "written" and r["cases"] == [{"id": "C-9", "kept_in": []}]
    assert env["cases"][0]["rules"] == [] and env["counts"]["checked"] == 0


def test_a_rule_with_no_cases_is_written(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a"), rule("core.b", provenance={"type": "EXPLICIT"})]))
    got = [(r["held"], r["cases"]) for r in read(tmp_path)["environments"][0]["rules"]]
    assert got == [("written", []), ("written", [])]


def test_a_case_kept_in_another_card_backs_a_rule_and_says_where(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a", provenance={"cases": ["C-1"]})]))
    put(tmp_path, "desk-seat", doc("desk-seat", [], [case("C-1")], inherits=["core@1.0.0"]))
    got = envs(read(tmp_path))
    assert got["core"]["rules"][0]["held"] == "checked"
    assert got["core"]["rules"][0]["cases"] == [{"id": "C-1", "kept_in": ["desk-seat"]}]
    assert got["desk-seat"]["cases"][0]["rules"] == ["core.a"]


def test_a_rule_id_held_by_two_cards_is_listed_once_against_the_case_it_cites(tmp_path):
    for name in ("core", "copy"):
        put(tmp_path, name, doc(name, [rule("shared.a", provenance={"cases": ["C-1"]})], [case("C-1")]))
    got = envs(read(tmp_path))
    assert got["core"]["cases"][0]["rules"] == ["shared.a"] == got["copy"]["cases"][0]["rules"]
    assert got["core"]["rules"][0]["cases"] == [{"id": "C-1", "kept_in": ["copy", "core"]}]


def test_a_correction_that_names_a_rule_backs_it_and_no_other(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a"), rule("core.b")], [case("C-1", rules=["core.a"])]))
    [env] = read(tmp_path)["environments"]
    by_id = {r["id"]: r for r in env["rules"]}
    assert (by_id["core.a"]["held"], by_id["core.b"]["held"]) == ("checked", "written")
    assert by_id["core.a"]["cases"] == [{"id": "C-1", "kept_in": ["core"]}] and env["cases"][0]["rules"] == ["core.a"]


def test_a_correction_that_names_no_rule_backs_none_even_if_its_words_match_one(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.parked-holds", words="Parked stays parked.")],
                              [case("core-parked", message="Parked stays parked.")]))
    [env] = read(tmp_path)["environments"]
    assert env["rules"][0]["held"] == "written" and env["rules"][0]["cases"] == []
    assert env["cases"][0]["rules"] == [] and env["counts"]["cases"] == 1


@pytest.mark.parametrize("guard,texts", [
    ("a hook refuses the write", ["a hook refuses the write"]),
    ("nonexistent-hook", ["nonexistent-hook"]),                   # only the word none is none, not one starting with it
    (["none", "check A"], ["check A"]),                           # a guard beside a "none" still counts
    (["check A", "check B"], ["check A", "check B"]),
    ({"hook": "pre-write", "ref": "tools/x"}, ["hook: pre-write; ref: tools/x"]),
])
def test_a_guard_the_card_only_claims_is_shown_and_earns_the_rule_nothing(tmp_path, guard, texts):
    put(tmp_path, "core", doc("core", [rule("core.a", guard=guard)]))
    [r] = read(tmp_path)["environments"][0]["rules"]
    assert (r["held"], r["guards"], r["checkers"]) == ("written", texts, [])   # a claim, never "guarded"


@pytest.mark.parametrize("guard", [False, True, "", None, [], [""], "   ", "none", "None", "N/A", ["no", "-"]])
def test_a_card_that_records_no_guard_never_makes_a_rule_guarded(tmp_path, guard):
    put(tmp_path, "core", doc("core", [rule("core.a", guard=guard)]))
    [r] = read(tmp_path)["environments"][0]["rules"]
    assert (r["held"], r["guards"]) == ("written", [])


def guards_file(tmp_path, *checkers) -> str:
    f = tmp_path.parent / (tmp_path.name + "-guards.json")
    f.write_text(json.dumps({"checkers": list(checkers)}), encoding="utf-8")
    return str(f)


HOOK = {"name": "pre-write hook", "rules": ["core.a"], "must_pass": "a short answer is written",
        "must_refuse": ["a long answer is refused"], "where": "hooks/pre-write"}


def test_the_word_guards_is_read_too_and_only_a_named_checker_guards(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a", guards=["a hook"], provenance={"cases": ["C-1"]})],
                              [case("C-1")]))
    [r] = read(tmp_path)["environments"][0]["rules"]
    assert r["held"] == "checked" and r["guards"] == ["a hook"]          # the card's claim alone: checked, no more
    out = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, HOOK)})
    [r] = out["environments"][0]["rules"]
    assert r["held"] == "guarded" and r["cases"] == [{"id": "C-1", "kept_in": ["core"]}]   # guarded outranks checked
    assert r["checkers"] == [{"name": "pre-write hook", "must_pass": ["a short answer is written"],
                              "must_refuse": ["a long answer is refused"], "where": "hooks/pre-write",
                              "where_exists": False, "where_note": None}]   # must-refuse: not there is never "there"
    hook = tmp_path.parent / "hooks" / "pre-write"         # where is read beside the guards file
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\n", encoding="utf-8")
    again = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, HOOK)})
    assert again["environments"][0]["rules"][0]["checkers"][0]["where_exists"] is True


WINDOWS_SHAPED = ["\\\\no-such-host\\share\\x", "//no-such-host/share/x", "\\\\?\\UNC\\host\\share",
                  "\\\\.\\PhysicalDrive0", "\\\\localhost\\c$\\Windows", "C:\\hooks\\x:stream", "hooks:x", "/\\host\\share"]


@pytest.mark.parametrize("where", WINDOWS_SHAPED)
def test_a_network_or_device_where_is_never_looked_up(tmp_path, monkeypatch, where):
    """A checker's where on a share would make the page build open a network connection (16 to 42 s a checker, and
    the host sees the attempt). It is refused on its text alone: the file system is never asked. Run under Windows'
    rule, where these name shares, devices and streams, on any machine."""
    monkeypatch.setattr(sys, "platform", "win32")
    put(tmp_path, "core", doc("core", [rule("core.a")]))
    calls = []
    monkeypatch.setattr(os.path, "lexists", lambda p: calls.append(str(p)) or False)   # records; never touches a disk
    out = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, {**HOOK, "where": where})})
    [k] = out["environments"][0]["rules"][0]["checkers"]
    assert calls == [] and k["where_exists"] is None and k["where_note"] == "not checked: a network or device path"
    assert k["where"] == where                                   # shown as the file's text
    # must pass: a local where is still looked up, once; a drive letter's colon is no stream
    here = str(tmp_path / "hooks" / "x")
    local = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, {**HOOK, "where": here})})
    assert len(calls) == 1 and local["environments"][0]["rules"][0]["checkers"][0]["where_note"] is None
    assert rules.not_local("C:\\hooks\\x") is None


@pytest.mark.parametrize("where", [w for w in WINDOWS_SHAPED if not w.startswith("//")])
def test_elsewhere_a_backslash_or_a_colon_is_part_of_a_name(tmp_path, monkeypatch, where):
    """Outside Windows these are odd names of local files, not shares or devices: they are looked up, once, and a name
    that is not there is said to be not there. The lookup is recorded, never made."""
    monkeypatch.setattr(sys, "platform", "linux")
    put(tmp_path, "core", doc("core", [rule("core.a")]))
    calls = []
    monkeypatch.setattr(os.path, "lexists", lambda p: calls.append(str(p)) or False)
    out = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, {**HOOK, "where": where})})
    [k] = out["environments"][0]["rules"][0]["checkers"]
    assert len(calls) == 1 and (k["where_exists"], k["where_note"], k["where"]) == (False, None, where)


def test_elsewhere_a_path_that_starts_with_two_slashes_is_still_never_looked_up(monkeypatch):
    """Must-refuse arm. POSIX leaves a leading // to the system, and some take it as a share; three or more slashes
    are one."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert rules.not_local("//no-such-host/share/x") == rules.NOT_LOCAL and rules.not_local(" //host") == rules.NOT_LOCAL
    assert rules.not_local("///etc/x") is None and rules.not_local("/etc/x") is None


@pytest.mark.parametrize("platform", ["cygwin", "msys"])
def test_python_for_cygwin_or_msys_keeps_the_windows_rule(monkeypatch, platform):
    """Must-refuse arm. There os.name is "posix", yet the paths reach Windows' shares, devices and streams."""
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(os, "name", "posix")
    assert [w for w in WINDOWS_SHAPED if rules.not_local(w) != rules.NOT_LOCAL] == []
    assert rules.not_local("C:\\hooks\\x") is None


@pytest.mark.parametrize("bad", [
    {**HOOK, "must_refuse": []}, {**HOOK, "must_pass": "  "}, {**HOOK, "name": ""}, {**HOOK, "rules": []},
    {k: v for k, v in HOOK.items() if k != "must_refuse"}, "a hook"])
def test_a_checker_without_both_arms_guards_nothing(tmp_path, bad):
    put(tmp_path, "core", doc("core", [rule("core.a")]))
    out = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, bad, {**HOOK, "rules": ["core.zz"]})})
    [r] = out["environments"][0]["rules"]
    assert r["held"] == "written" and r["checkers"] == []
    kinds = [p["kind"] for p in out["problems"]]
    assert "unknown-rule" in kinds and (kinds.count("bad-checker") == 1 or bad == "a hook")


def test_an_unreadable_or_missing_guards_file_guards_nothing_and_says_so(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a")]))
    for content, kind in (("{ not json", "bad-guards"), ('{"checkers": {}}', "bad-guards"), (None, "no-guards-file")):
        f = tmp_path.parent / "guards-x.json"
        if content is None:
            f.unlink(missing_ok=True)
        else:
            f.write_text(content, encoding="utf-8")
        out = rules.load({"cards": str(tmp_path), "guards": str(f)})
        assert out["environments"][0]["rules"][0]["held"] == "written"
        assert [p["kind"] for p in out["problems"]] == [kind]


def test_counts_add_up_per_environment_and_in_total(tmp_path):
    put(tmp_path, "core", doc("core", [rule("core.a", provenance={"cases": ["C-1"]}), rule("core.b"),
                                      rule("core.c", guard="a hook"), rule("core.d", ratified_by=None)],
                              [case("C-1"), case("C-2")]))
    put(tmp_path, "desk-seat", doc("desk-seat", [rule("desk-seat.x")]))
    out = read(tmp_path)
    assert envs(out)["core"]["counts"] == {"rules": 4, "candidates": 1, "written": 3, "checked": 1, "guarded": 0,
                                           "cases": 2}
    assert out["counts"] == {"environments": 2, "rules": 5, "candidates": 1, "written": 4, "checked": 1, "guarded": 0,
                             "cases": 2}
    guarded = rules.load({"cards": str(tmp_path), "guards": guards_file(tmp_path, {**HOOK, "rules": ["core.c"]})})
    assert envs(guarded)["core"]["counts"]["guarded"] == 1 and guarded["counts"]["written"] == 3


# ---------------------------------------------------------------- what an environment inherits
@pytest.mark.parametrize("pin,state,kind", [
    ("core@1.0.0", "current", None),
    ("core", "current", None),
    ("core@0.9.0", "changed", "stale-pin"),
    ("ghost@1.0.0", "missing", "missing-parent"),
])
def test_a_parent_is_current_changed_or_missing(tmp_path, pin, state, kind):
    put(tmp_path, "core", doc("core"))
    put(tmp_path, "desk-seat", doc("desk-seat", inherits=[pin]))
    out = read(tmp_path)
    [parent] = envs(out)["desk-seat"]["parents"]
    name, _, wanted = pin.partition("@")
    assert (parent["name"], parent["pin"], parent["state"]) == (name, wanted or None, state)
    assert kinds(out) == ([kind] if kind else [])
    assert parent["version"] == (None if state == "missing" else "1.0.0")


def test_a_parent_with_no_version_has_changed_from_any_pin_and_the_problem_says_so(tmp_path):
    put(tmp_path, "core", doc("core", version=None))
    put(tmp_path, "desk-seat", doc("desk-seat", inherits=["core@1.0.0"]))
    put(tmp_path, "desk-two", doc("desk-two", inherits=["core"]))             # no pin, so nothing to differ from
    out = read(tmp_path)
    got = envs(out)
    assert (got["desk-seat"]["parents"][0]["state"], got["desk-two"]["parents"][0]["state"]) == ("changed", "current")
    [p] = out["problems"]
    assert p["kind"] == "stale-pin" and "no version" in p["text"] and "None" not in p["text"]


def test_an_environment_with_no_parent_has_none_whether_it_says_null_or_nothing(tmp_path):
    put(tmp_path, "a", "environment:\n  id: a\n  inherits: null\n")
    put(tmp_path, "b", "environment:\n  id: b\n")
    put(tmp_path, "c", "environment:\n  id: c\n  inherits: []\n")
    out = read(tmp_path)
    assert [e["parents"] for e in out["environments"]] == [[], [], []] and out["problems"] == []


@pytest.mark.parametrize("pin,state,why", [
    ("core@1.0.0", "unread", "bad-yaml"),
    ("core", "unread", "bad-yaml"),
    ("ghost@1.0.0", "missing", None),
])
def test_a_child_of_a_card_not_read_is_told_its_folder_is_there_not_that_it_is_missing(tmp_path, pin, state, why):
    put(tmp_path, "core", "environment: [unclosed\n")
    put(tmp_path, "desk-seat", doc("desk-seat", inherits=[pin]))
    out = read(tmp_path)
    [parent] = envs(out)["desk-seat"]["parents"]
    assert (parent["state"], parent["version"]) == (state, None)                 # a parent not read has no version
    [mine] = [p for p in out["problems"] if p["source"].endswith(os.path.join("desk-seat", "SEMANTICS.yaml"))]
    if why:                                                       # the folder is there: say so, and why it was not read
        assert mine["kind"] == "unread-parent" and "whose folder is there" in mine["text"] and why in mine["text"]
        assert "not among the cards" not in mine["text"]
    else:                                                         # no folder of that name: still missing
        assert mine["kind"] == "missing-parent" and "not among the cards" in mine["text"]


@pytest.mark.parametrize("make,why", [
    (lambda root: (root / "core").mkdir(), "no-card"),
    (lambda root: put(root, "core", "- a\n- b\n"), "not-a-card"),
    (lambda root: (root / "core" / "SEMANTICS.yaml").mkdir(parents=True), "no-card"),
])
def test_whatever_kept_a_parent_from_being_read_is_named_in_what_the_child_is_told(tmp_path, make, why):
    make(tmp_path)
    put(tmp_path, "desk-seat", doc("desk-seat", inherits=["core@1.0.0"]))
    out = read(tmp_path)
    [mine] = [p for p in out["problems"] if p["kind"] == "unread-parent"]
    assert why in mine["text"] and envs(out)["desk-seat"]["parents"][0]["state"] == "unread"


def test_a_folder_that_holds_no_card_and_is_listed_aside_is_still_there_for_a_child_that_inherits_it(tmp_path):
    (tmp_path / "_old").mkdir()
    put(tmp_path, "desk-seat", doc("desk-seat", inherits=["_old"]))
    out = read(tmp_path)
    assert out["others"] == ["_old"] and envs(out)["desk-seat"]["parents"][0]["state"] == "unread"
    [mine] = out["problems"]
    assert mine["kind"] == "unread-parent" and "holds no SEMANTICS.yaml" in mine["text"]


# ---------------------------------------------------------------- every defect is reported
def laughs(levels: int = 10, fan: int = 10, walked: bool = False) -> str:
    """A small card whose aliases, written out in full, come to about fan ** levels values. With `walked` the last list
    is the environment's scope, a field the reader turns into text, so a reader that wrote the aliases out would never
    finish."""
    lines = ["l0: &l0 [" + ", ".join(["x"] * fan) + "]"]
    lines += [f"l{n}: &l{n} [" + ", ".join([f"*l{n - 1}"] * fan) + "]" for n in range(1, levels)]
    scope = f", scope: *l{levels - 1}" if walked else ""
    return "\n".join(lines) + f"\nenvironment: {{id: bad{scope}}}\n"


UNUSABLE = {
    "unclosed list": ("environment:\n  id: [unclosed\n", "bad-yaml"),
    "impossible date": ("environment:\n  id: bad\n  version: 2026-13-45\n", "bad-yaml"),
    "an alias nobody defined": ("environment: {id: bad}\nagain: *nowhere\n", "bad-yaml"),
    "an alias that points inside itself": ("environment: {id: bad}\nloop: &l [*l]\n", "too-large"),
    "aliases that grow past the bound": (laughs(), "too-large"),
    "nested too deep": ("[" * 3000, "bad-yaml"),
    "a list, not a card": ("- a\n- b\n", "not-a-card"),
    "an empty file": ("", "not-a-card"),
    "no environment section": ("entries: []\n", "not-a-card"),
    "an environment without an id": ("environment:\n  version: 1\n", "not-a-card"),
    "an id that is a decimal": ("environment:\n  id: 7.5\n", "not-a-card"),
    "an id that is a yes/no": ("environment:\n  id: yes\n", "not-a-card"),
}


@pytest.mark.parametrize("text,kind", UNUSABLE.values(), ids=UNUSABLE.keys())
def test_a_card_that_cannot_be_read_is_one_problem_and_the_good_cards_are_unharmed(tmp_path, text, kind):
    put(tmp_path, "good", doc("good", [rule("good.a")]))
    bad = put(tmp_path, "bad", text)
    out = read(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["good"] and out["environments"][0]["rules"][0]["id"] == "good.a"
    assert kinds(out) == [kind] and out["problems"][0]["source"] == str(bad)


def test_a_yaml_error_names_its_line(tmp_path):
    put(tmp_path, "bad", "environment:\n  id: bad\nentries: [\n  - x\n  : y\n")
    [p] = read(tmp_path)["problems"]
    assert p["kind"] == "bad-yaml" and isinstance(p["line"], int) and p["line"] >= 1


def test_an_alias_nobody_defined_names_its_line_and_an_anchor_with_no_alias_is_harmless(tmp_path):
    put(tmp_path, "bad", "environment:\n  id: bad\nentries: &e []\nagain: *nowhere\n")
    put(tmp_path, "fine", "environment: &e\n  id: fine\n")
    out = read(tmp_path)
    [p] = out["problems"]
    assert (p["kind"], p["line"]) == ("bad-yaml", 4) and "alias" in p["text"]
    assert [e["name"] for e in out["environments"]] == ["fine"]


ALIASED = """\
environment:
  id: core
  version: 1.0.0
  status: ratified
  ratified_by: &owner pat
  scope: &scope {where: here, when: always}
defaults: &defaults
  kind: ruling
  ratified_by: *owner
  provenance: &prov {type: EXPLICIT, quote: yes to all, cases: [C-1]}
entries:
  - id: core.a
    <<: *defaults
    statement: &words Ask before you act on a guess.
    applies_when: *scope
  - id: core.b
    kind: ruling
    statement: *words
    ratified_by: *owner
tests:
  - case: C-1
    message: &msg Tidy it up?
    expected: &exp {act: Question}
    forbidden: *words
  - case: C-2
    message: *msg
    expected: *exp
"""


class NoAliases(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def test_a_card_with_aliases_is_read_as_safe_load_reads_it_the_same_as_the_card_written_out(tmp_path):
    written_out = yaml.dump(yaml.safe_load(ALIASED), Dumper=NoAliases, sort_keys=False)
    assert "*" in ALIASED and "&" in ALIASED and "*" not in written_out and "&" not in written_out   # the premise
    put(tmp_path / "aliased", "core", ALIASED)
    put(tmp_path / "plain", "core", written_out)
    aliased, plain = read(tmp_path / "aliased"), read(tmp_path / "plain")
    assert aliased["problems"] == plain["problems"] == []
    where = lambda out: [{**e, "path": None} for e in out["environments"]]      # all but where each one lives
    assert where(aliased) == where(plain)
    [env] = aliased["environments"]                                          # and what it says is what safe_load says
    a, b = env["rules"]
    assert env["ratified_by"] == "pat" and env["scope"] == "where: here; when: always"
    assert (a["kind"], a["ratified_by"], a["basis"], a["quote"]) == ("ruling", "pat", "EXPLICIT", "yes to all")
    assert a["held"] == "checked"
    assert a["words"] == b["words"] == "Ask before you act on a guess." and a["applies_when"] == env["scope"]
    assert (b["ratified_by"], b["held"]) == ("pat", "written")
    c1, c2 = env["cases"]
    assert (c1["message"], c1["expected"], c1["forbidden"]) == ("Tidy it up?", "act: Question", a["words"])
    assert (c2["message"], c2["expected"]) == ("Tidy it up?", "act: Question")


def written_out(value) -> int:
    """The size the top of rules.py describes, counted the plain way: walking the data, so a value met again is counted
    again. For text-only data."""
    if isinstance(value, dict):
        return 1 + sum(written_out(k) + written_out(v) for k, v in value.items())
    if isinstance(value, list):
        return 1 + sum(map(written_out, value))
    return 1 + len(value)


def test_aliases_are_measured_in_values_and_characters_and_a_card_exactly_at_the_bound_is_read(tmp_path, monkeypatch):
    text = "environment: {id: core, scope: &s [ab, cd]}\nagain: *s\n"
    size = rules._expanded(yaml.compose(text, Loader=yaml.SafeLoader))
    assert size == written_out(yaml.safe_load(text)) == 48                 # every value one, every character one
    diamond = "{a: &d [x], b: [*d], c: [*d]}"                              # shared twice, but not a loop
    assert rules._expanded(yaml.compose(diamond, Loader=yaml.SafeLoader)) == written_out(yaml.safe_load(diamond))
    put(tmp_path, "core", text)
    monkeypatch.setattr(rules, "MAX_EXPANDED", size)                         # at the bound: read
    assert [e["name"] for e in read(tmp_path)["environments"]] == ["core"]
    monkeypatch.setattr(rules, "MAX_EXPANDED", size - 1)                     # one over: refused, and the bound is said
    out = read(tmp_path)
    assert out["environments"] == [] and kinds(out) == ["too-large"] and f"{size - 1:,}" in out["problems"][0]["text"]


def test_aliases_that_would_never_finish_are_a_problem_that_gives_the_bound_and_the_reader_does_not_hang(tmp_path):
    put(tmp_path, "good", doc("good"))
    bad = put(tmp_path, "bad", laughs(walked=True))                         # its scope would be 10 ** 10 values long
    out = read_within(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["good"]
    [p] = out["problems"]
    assert (p["kind"], p["source"]) == ("too-large", str(bad)) and f"{rules.MAX_EXPANDED:,}" in p["text"]


def test_an_alias_that_points_back_inside_what_it_names_is_a_problem_and_the_reader_does_not_hang(tmp_path):
    put(tmp_path, "good", doc("good"))
    put(tmp_path, "bad", "l: &l [*l]\nenvironment: {id: bad, scope: *l}\n")
    out = read_within(tmp_path)
    [p] = out["problems"]
    assert [e["name"] for e in out["environments"]] == ["good"]
    assert p["kind"] == "too-large" and "points back inside what it names" in p["text"]


def test_a_folder_without_a_card_is_a_problem_and_so_is_one_that_is_not_text(tmp_path):
    put(tmp_path, "good", doc("good"))
    (tmp_path / "empty").mkdir()
    (tmp_path / "binary").mkdir()
    (tmp_path / "binary" / "SEMANTICS.yaml").write_bytes(b"environment:\n  id: binary\n  scope: \xff\xfe\n")
    out = read(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["good"]
    assert sorted((Path(p["source"]).name, p["kind"]) for p in out["problems"]) == [
        ("SEMANTICS.yaml", "not-utf8"), ("empty", "no-card")]


def test_a_card_over_the_size_limit_is_a_problem_that_gives_the_limit_and_is_not_parsed(tmp_path, monkeypatch):
    size = put(tmp_path, "core", FOLDED).stat().st_size
    monkeypatch.setattr(rules, "MAX_CARD", size)                               # at the limit: read
    assert [e["name"] for e in read(tmp_path)["environments"]] == ["core"]
    monkeypatch.setattr(rules, "MAX_CARD", size - 1)                           # one byte over: refused
    out = read(tmp_path)
    assert out["environments"] == [] and kinds(out) == ["too-large"] and f"{size - 1:,}" in out["problems"][0]["text"]


PAD = "# " + "x" * 78 + "\n"                                                    # a comment line, 80 bytes


def test_the_stated_bound_is_four_mib_and_a_card_a_little_over_a_million_bytes_is_read(tmp_path):
    assert rules.MAX_CARD == 4 * 1024 * 1024 and "4 MiB" in rules.__doc__
    text = FOLDED + PAD * (1_100_000 // len(PAD))
    assert 1_000_000 < len(text.encode()) < rules.MAX_CARD
    put(tmp_path, "core", text)
    out = read(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["core"] and out["problems"] == []


def test_a_card_over_the_stated_bound_is_refused_and_the_problem_gives_the_bound(tmp_path):
    put(tmp_path, "core", FOLDED + PAD * (rules.MAX_CARD // len(PAD) + 1))
    out = read(tmp_path)
    [p] = out["problems"]
    assert out["environments"] == [] and p["kind"] == "too-large"
    assert f"{rules.MAX_CARD:,}" in p["text"] and "4 MiB" in p["text"]


def test_a_card_cannot_run_anything_a_python_tag_is_only_a_problem(tmp_path):
    sentinel = tmp_path / "ran.txt"
    put(tmp_path, "bad", "environment: {id: bad}\nentries:\n  - id: bad.x\n    statement: "
                         f"!!python/object/apply:builtins.open [{json.dumps(str(sentinel))}, w]\n")
    out = read(tmp_path)
    assert kinds(out) == ["bad-yaml"] and out["environments"] == [] and not sentinel.exists()


PARTIAL = {
    "entries not a list": (lambda d: d.update(entries="nope"), "bad-field"),
    "a rule that is just text": (lambda d: d["entries"].append("just text"), "bad-rule"),
    "a rule with no id": (lambda d: d["entries"].append({"statement": "no id"}), "bad-rule"),
    "a rule with no statement": (lambda d: d["entries"].append({"id": "bad.x"}), "bad-rule"),
    "a statement that is not text": (lambda d: d["entries"].append({"id": "bad.x", "statement": 42}), "bad-rule"),
    "a rule id used twice": (lambda d: d["entries"].append(rule("bad.ok")), "duplicate-id"),
    "provenance that is not a section": (lambda d: d["entries"][0].update(provenance="oops"), "bad-field"),
    "cases that are not ids": (lambda d: d["entries"][0].update(provenance={"cases": [["nested"]]}), "bad-field"),
    "tests not a list": (lambda d: d.update(tests="nope"), "bad-field"),
    "a case that is just text": (lambda d: d["tests"].append("just text"), "bad-case"),
    "a case with no id": (lambda d: d["tests"].append({"message": "no id"}), "bad-case"),
    "a case id used twice": (lambda d: d["tests"].append(case("C-1")), "duplicate-id"),
    "a case naming a rule nobody holds": (lambda d: d["tests"].append(case("C-2", rules=["bad.nowhere"])),
                                          "unknown-rule"),
    "a case whose rules are not ids": (lambda d: d["tests"].append(case("C-2", rules=[["nested"]])), "bad-field"),
    "an id that differs from the folder": (lambda d: d["environment"].update(id="other"), "name-mismatch"),
    "ratification that is not a section": (lambda d: d["environment"].update(ratification="oops"), "bad-field"),
    "reading rules not a list": (lambda d: d["environment"].update(reading_rules="oops"), "bad-field"),
    "changes not a list": (lambda d: d["environment"].update(changes="oops"), "bad-field"),
    "a change that is just text": (lambda d: d["environment"].update(changes=["oops"]), "bad-field"),
    "agents not a section": (lambda d: d.update(agents="oops"), "bad-field"),
    "an agent that is not a section": (lambda d: d.update(agents={"reviewer": "oops"}), "bad-field"),
    "inherits that holds a list": (lambda d: d["environment"].update(inherits=[["nested"]]), "bad-field"),
    "a relation that is not a section": (lambda d: d["entries"][0].update(relation="oops"), "bad-field"),
    "a relation that names no ids": (lambda d: d["entries"][0].update(relation={"specializes": [["nested"]]}),
                                     "bad-field"),
}


@pytest.mark.parametrize("break_it,kind", PARTIAL.values(), ids=PARTIAL.keys())
def test_a_flaw_inside_a_card_is_one_problem_and_the_rest_of_the_card_is_still_read(tmp_path, break_it, kind):
    d = doc("bad", [rule("bad.ok")], [case("C-1")])
    break_it(d)
    bad = put(tmp_path, "bad", d)
    out = read(tmp_path)
    [env] = out["environments"]
    assert kinds(out) == [kind] and out["problems"][0]["source"] == str(bad)
    assert "bad.ok" in [r["id"] for r in env["rules"]] or d["entries"] == "nope"


def test_a_bug_met_on_one_card_is_said_as_a_problem_and_the_other_cards_are_still_read(tmp_path, monkeypatch):
    put(tmp_path, "good", doc("good", [rule("good.a")]))
    put(tmp_path, "odd", doc("odd"))
    real = rules._environment

    def environment(folder, problems):
        if folder.name == "odd":
            raise ValueError("boom")
        return real(folder, problems)

    clean = read(tmp_path)
    monkeypatch.setattr(rules, "_environment", environment)
    out = read(tmp_path)
    assert [e["name"] for e in clean["environments"]] == ["good", "odd"] and clean["problems"] == []   # must pass
    assert [e["name"] for e in out["environments"]] == ["good"]                                       # must refuse
    assert [(p["kind"], p["source"], p["text"]) for p in out["problems"]] == [
        ("unreadable", str(tmp_path / "odd"), "ValueError: boom")]


def test_a_name_that_vanishes_while_the_folder_is_read_is_a_problem_not_a_listed_file(tmp_path, monkeypatch):
    put(tmp_path, "good", doc("good"))
    (tmp_path / "RECORD.md").write_text("a record", encoding="utf-8")
    assert read(tmp_path)["others"] == ["RECORD.md"]                                                  # must pass
    real = rules._stat
    monkeypatch.setattr(rules, "_stat", lambda p: None if p.name == "RECORD.md" else real(p))
    out = read(tmp_path)
    assert out["others"] == [] and kinds(out) == ["unreadable"]                                       # must refuse
    assert [e["name"] for e in out["environments"]] == ["good"]


def test_a_planted_defect_changes_what_is_reported_a_clean_copy_reports_nothing(tmp_path):
    good, planted = tmp_path / "good", tmp_path / "planted"
    d = doc("core", [rule("core.a")], [case("C-1")])
    put(good, "core", d)
    d["entries"].append({"id": "core.b"})
    put(planted, "core", d)
    assert read(good)["problems"] == [] and kinds(read(planted)) == ["bad-rule"]


def test_every_folder_is_read_or_a_problem_whatever_is_wrong_with_it_or_called(tmp_path):
    put(tmp_path, "good-1", doc("good-1", [rule("good-1.a")]))
    put(tmp_path, "good-2", doc("good-2", inherits=["good-1@1.0.0"]))
    put(tmp_path, "_good-3", doc("_good-3"))                                  # a mark first, a card inside: read
    put(tmp_path, "~bad-3", "environment: [unclosed\n")                       # a mark first, a card that is no good
    for i, (text, _) in enumerate(UNUSABLE.values()):
        put(tmp_path, f"bad-{i:02d}", text)
    (tmp_path / "bare").mkdir()                                               # a name that is a name, but no card
    (tmp_path / ".git").mkdir()                                               # a mark first and no card: not one
    out = read(tmp_path)
    folders = {p.name for p in tmp_path.iterdir() if p.is_dir()}

    def folder_of(p):
        path = Path(p["source"])
        return path.parent.name if path.name == "SEMANTICS.yaml" else path.name

    listed_aside = set(out["others"]) & folders                               # folders only: not the files beside them
    assert listed_aside == {".git"}
    assert folders == {e["name"] for e in out["environments"]} | {folder_of(p) for p in out["problems"]} | listed_aside
    assert len(out["environments"]) == 3 and len(out["problems"]) == len(UNUSABLE) + 2
    assert all(set(p) == {"source", "line", "kind", "text"} for p in out["problems"])


def test_dropping_an_environment_from_the_result_breaks_the_every_folder_check(tmp_path):
    put(tmp_path, "good-1", doc("good-1"))
    put(tmp_path, "good-2", doc("good-2"))
    out = read(tmp_path)
    folders = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert folders == {e["name"] for e in out["environments"]}
    assert folders != {e["name"] for e in out["environments"][1:]}


# ---------------------------------------------------------------- links are never followed
def make_dir_link(target: Path, link: Path) -> bool:
    """A link to a folder: a junction on Windows (it needs no privilege), a symlink elsewhere. False if this machine
    cannot make one."""
    try:
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, ImportError, AttributeError):
        return False


def test_a_folder_that_is_a_link_is_a_problem_and_its_card_is_never_read(tmp_path):
    cards = tmp_path / "cards"
    put(cards, "real", doc("real", [rule("real.a")]))
    put(tmp_path / "elsewhere", "secret", doc("secret", [rule("secret.private")]))
    if not make_dir_link(tmp_path / "elsewhere" / "secret", cards / "secret"):
        pytest.skip("this machine cannot make a link")
    out = read(cards)
    assert [e["name"] for e in out["environments"]] == ["real"]                       # the arm that must pass
    assert [(p["kind"], p["source"]) for p in out["problems"]] == [("link", str(cards / "secret"))]   # must refuse
    assert "secret.private" not in json.dumps(out) and out["others"] == []


def test_a_card_that_is_a_symbolic_link_is_a_problem_and_is_never_read(tmp_path):
    cards = tmp_path / "cards"
    real = put(tmp_path / "elsewhere", "secret", doc("secret", [rule("secret.private")]))
    (cards / "linked").mkdir(parents=True)
    try:
        os.symlink(real, cards / "linked" / "SEMANTICS.yaml")
    except OSError:
        pytest.skip("this machine cannot make a symbolic link")
    out = read(cards)
    assert out["environments"] == [] and "secret.private" not in json.dumps(out)
    assert [(p["kind"], p["source"]) for p in out["problems"]] == [("link", str(cards / "linked" / "SEMANTICS.yaml"))]


def test_a_card_whose_own_stat_says_link_is_not_read_even_where_no_link_can_be_made(tmp_path, monkeypatch):
    put(tmp_path, "linked", doc("linked", [rule("linked.a")]))
    put(tmp_path, "plain", doc("plain", [rule("plain.a")]))
    real = rules._stat

    def stat_of(p):
        linked = p.name == "SEMANTICS.yaml" and p.parent.name == "linked"
        return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777) if linked else real(p)

    monkeypatch.setattr(rules, "_stat", stat_of)
    out = read(tmp_path)
    assert [e["name"] for e in out["environments"]] == ["plain"] and kinds(out) == ["link"]


def fake_stat(mode: int, attributes: int | None = None, tag: int = 0):
    out = SimpleNamespace(st_mode=mode)
    if attributes is not None:
        out.st_file_attributes, out.st_reparse_tag = attributes, tag
    return out


@pytest.mark.parametrize("st,linked", [
    (fake_stat(stat.S_IFLNK | 0o777), True),                    # a symbolic link
    (fake_stat(stat.S_IFDIR, 0x410, 0xA0000003), True),         # a Windows junction
    (fake_stat(stat.S_IFREG, 0x400, 0xA000000C), True),         # a Windows symbolic link
    (fake_stat(stat.S_IFREG, 0x420, 0x9000001A), False),        # a cloud placeholder holds its own bytes: read it
    (fake_stat(stat.S_IFDIR, 0x10, 0), False),
    (fake_stat(stat.S_IFREG), False),                           # a POSIX stat has no Windows attributes at all
])
def test_a_link_is_a_symlink_or_a_reparse_point_that_names_another_place(st, linked):
    assert rules._linked(st) is linked


def test_a_folder_where_the_card_should_be_is_no_card(tmp_path):
    (tmp_path / "odd" / "SEMANTICS.yaml").mkdir(parents=True)
    out = read(tmp_path)
    assert out["environments"] == [] and kinds(out) == ["no-card"]


# ---------------------------------------------------------------- read only
def snapshot(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def test_reading_writes_nothing_not_even_beside_the_cards(tmp_path):
    put(tmp_path, "good", doc("good", [rule("good.a", provenance={"cases": ["C-1"]})], [case("C-1")]))
    put(tmp_path, "bad", "environment: [unclosed\n")
    (tmp_path / "bare").mkdir()
    (tmp_path / "RECORD.md").write_text("a record", encoding="utf-8")
    before = snapshot(tmp_path)
    read(tmp_path)
    assert snapshot(tmp_path) == before
