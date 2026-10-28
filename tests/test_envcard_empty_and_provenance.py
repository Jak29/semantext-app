"""envcard on an environment with no rules, and on a rule whose environment records no provenance: each says so on
the card, and an arm with rules (or with provenance) shows no such line."""
from __future__ import annotations

import pytest

from semantext import envcard
from test_envcard import write

RATIFIED = {"id": "empty", "version": "1.0.0", "status": "ratified", "ratified_by": "owner"}


@pytest.mark.parametrize("entries", [[], None], ids=["empty list", "no entries"])
def test_an_environment_with_no_rules_says_so_and_is_never_a_bare_header(tmp_path, entries):
    env = write(tmp_path, "empty", RATIFIED, entries)
    lines = envcard.card(env).splitlines()
    assert lines == ["## empty 1.0.0 (ratified, ratified by owner)", envcard.NO_RULES]
    assert "no rules: this environment holds no entries" in envcard.reference(env)


def test_an_empty_child_still_shows_its_parents_rules(tmp_path):
    write(tmp_path, "core", {"id": "core", "version": "1.0.0", "status": "ratified", "ratified_by": "owner"},
          [{"id": "c.one", "statement": "A parent rule.", "ratified_by": "owner", "provenance": {"type": "EXPLICIT"}}])
    seat = write(tmp_path, "seat", {**RATIFIED, "id": "seat", "inherits": ["core@1.0.0"]}, [])
    text = envcard.card(seat)
    assert "- c.one: A parent rule." in text and text.endswith("## seat 1.0.0 (ratified, ratified by owner)\n"
                                                                 + envcard.NO_RULES)
    # must-refuse: an environment with a rule carries no such line
    full = write(tmp_path, "full", {**RATIFIED, "id": "full"},
                 [{"id": "f.one", "statement": "A rule.", "ratified_by": "owner", "provenance": {"type": "EXPLICIT"}}])
    assert envcard.NO_RULES not in envcard.card(full)


def test_a_rule_with_no_provenance_is_marked_and_one_with_provenance_is_not(tmp_path):
    env = write(tmp_path, "mixed", {**RATIFIED, "id": "mixed"},
                [{"id": "m.hand", "statement": "Typed in by hand.", "ratified_by": "owner"},
                 {"id": "m.blank", "statement": "An empty section.", "ratified_by": "owner", "provenance": {}},
                 {"id": "m.told", "statement": "From the owner's words.", "ratified_by": "owner",
                  "provenance": {"type": "EXPLICIT", "quote": "say it once"}}])
    lines = envcard.card(env).splitlines()
    assert lines[1] == "  (2 rules here record no provenance; the reference marks each)"     # one line, counted
    assert "- m.hand: Typed in by hand." in lines and "- m.told: From the owner's words." in lines   # no mark per rule
    ref = envcard.reference(env)
    assert ref.count("**Provenance:** none recorded in the environment") == 2                   # each, in the reference


def test_forty_rules_with_no_provenance_add_at_most_one_line_to_the_card(tmp_path):
    rules = [{"id": f"f.r{i:02d}", "statement": f"Rule {i}.", "ratified_by": "owner"} for i in range(40)]
    told = [{**r, "provenance": {"type": "EXPLICIT"}} for r in rules]
    bare = envcard.card(write(tmp_path, "bare", {**RATIFIED, "id": "f"}, rules)).splitlines()
    kept = envcard.card(write(tmp_path, "told", {**RATIFIED, "id": "f"}, told)).splitlines()
    assert len(bare) - len(kept) == 1
    assert [x for x in bare if x not in kept] == ["  (40 rules here record no provenance; the reference marks each)"]
    assert len("\n".join(bare)) - len("\n".join(kept)) < 80                   # one line's bytes, not 40 marks
