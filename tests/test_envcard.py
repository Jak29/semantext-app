"""envcard: a parent comes first, every rule is whole unless a ratified line stands for it, the statement stays whole
in the reference, and a stale pin or a candidate is marked. Each check has an arm that must refuse."""
import yaml

from semantext import envcard


def write(base, name, environment, entries, tests=None):
    (base / name).mkdir()
    data = {"environment": environment, "entries": entries}
    if tests:
        data["tests"] = tests
    (base / name / "SEMANTICS.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return base / name / "SEMANTICS.yaml"


def test_the_parent_comes_first_and_each_rule_is_whole(tmp_path):
    write(tmp_path, "core", {"id": "core", "version": "1.1.0", "status": "ratified", "ratified_by": "owner"},
          [{"id": "c.one", "statement": "A grant lets the agent decide.  It does not waive reading first.",
            "ratified_by": "owner"}])
    seat = write(tmp_path, "seat", {"id": "seat", "version": "1.0.0", "status": "candidate",
                                    "inherits": ["core@1.0.0"]},
                 [{"id": "s.one", "statement": "Keep going means keep working.", "ratified_by": None}], [{"case": "x"}])
    text = envcard.card(seat)
    assert text.index("## core 1.1.0") < text.index("## seat 1.0.0")
    assert "- c.one: A grant lets the agent decide. It does not waive reading first." in text   # its limit is kept
    assert "- s.one: Keep going means keep working. (candidate)" in text                    # must-refuse: unratified
    assert "WARNING: seat pins core@1.0.0, but core is at 1.1.0" in text                    # must-refuse: stale pin
    assert "(1 regression cases" in text


def test_a_ratified_line_replaces_its_statement_on_the_card_only(tmp_path):
    env = write(tmp_path, "lined", {"id": "lined", "version": "2.0.0", "status": "ratified", "ratified_by": "owner",
                                    "card_sections": {"whole": "Guardrails:", "lines": "Rules:"},
                                    "reference": "REF.md", "reference_line": "All rules in full: {reference}."},
                [{"id": "l.short", "statement": "Keep going means keep working. A report trigger is not a stop.",
                  "line": "Keep working; a report trigger is not a stop.", "ratified_by": "owner"},
                 {"id": "l.guard", "statement": "Never open the closed folder.", "ratified_by": "owner"},
                 {"id": "l.cand", "statement": "A long candidate rule.", "line": "Short candidate.",
                  "ratified_by": None}])
    text = envcard.card(env)
    assert text.index("Guardrails:") < text.index("- l.guard: Never open") < text.index("Rules:")
    assert "- l.short: Keep working; a report trigger is not a stop." in text
    assert "Keep going means keep working" not in text                    # must-refuse: the statement is not shown
    assert "- l.cand: Short candidate. (candidate)" in text
    assert text.endswith("All rules in full: REF.md.")
    ref = envcard.reference(env)
    assert "Keep going means keep working. A report trigger is not a stop." in ref    # the statement, whole
    assert "**On the card:** Keep working; a report trigger is not a stop." in ref


def test_the_reference_holds_the_environment_itself_not_its_parent(tmp_path):
    write(tmp_path, "core", {"id": "core", "version": "1.0.0", "status": "ratified", "ratified_by": "owner"},
          [{"id": "c.one", "statement": "A parent rule.", "ratified_by": "owner"}])
    seat = write(tmp_path, "seat", {"id": "seat", "version": "1.0.0", "status": "ratified", "ratified_by": "owner",
                                    "inherits": ["core@1.0.0"]},
                 [{"id": "s.one", "statement": "A seat rule.", "ratified_by": "owner"}])
    ref = envcard.reference(seat)
    assert "s.one" in ref and "c.one" not in ref
