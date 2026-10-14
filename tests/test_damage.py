"""Damage from outside Semantext: a hand edit that went wrong, a folder copied in a file manager, a settings file left
empty by a crash. Each is named in one line, the rest goes on working, and none of them takes the card away from the
AI: the base rules always go out."""
import json
import shutil

import pytest
import yaml

from semantext import cli, hook
from semantext.store import Refused

FLOOR_RULE = "base.irreversible-needs-your-word"


def break_rule(store, bad):
    """Append one malformed rule to the default environment's file, as a hand edit would."""
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    d = store.load("default")
    d["entries"] = [*(d.get("entries") or []), bad]
    p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return p


BAD = [{"id": "default.typo"}, "just a line of text", {"statement": "a rule with no id"}, {"id": "default.n", "statement": 7}]
BAD_IDS = ["no-statement", "a-plain-line", "no-id", "statement-not-text"]


@pytest.mark.parametrize("bad", BAD, ids=BAD_IDS)
def test_a_malformed_rule_is_refused_in_one_line_naming_the_file(store, capsys, bad):
    p = break_rule(store, bad)
    assert cli.main(["card"]) == 1
    err = capsys.readouterr().err
    assert str(p) in err and "Traceback" not in err and err.count("\n") == 1
    if isinstance(bad, dict) and bad.get("id"):
        assert bad["id"] in err                                     # the rule is named, not only the file


@pytest.mark.parametrize("bad", BAD, ids=BAD_IDS)
def test_a_broken_rule_file_still_leaves_the_ai_the_base_rules(store, bad):
    p = break_rule(store, bad)
    out = hook.run(json.dumps({"prompt": "hi"}), store)
    assert FLOOR_RULE in out                                        # the base rules still go out, every prompt
    assert str(p) in out and "only the base rules are shown" in out
    assert "unavailable" not in out


def test_doctor_names_a_broken_file_and_carries_on(store, capsys):
    p = break_rule(store, {"id": "default.typo"})
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "PROBLEM" in out and str(p) in out and "hear-prompts" in out     # the checks after it still ran


def test_the_page_state_survives_one_broken_environment(store):
    break_rule(store, {"id": "default.typo"})
    view = store.overview()
    assert [x["name"] for x in view["problems"]] == ["default"] and "default.typo" in view["problems"][0]["problem"]


def test_an_environment_with_no_version_or_scope_still_makes_a_card(store):
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    d = store.load("default")
    d["environment"].pop("version", None)
    d["environment"].pop("scope", None)
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")
    assert FLOOR_RULE in store.card("default")


def test_the_editor_refuses_what_the_card_could_not_read(store):
    d = store.load("default")
    d["entries"] = [*(d.get("entries") or []), {"id": "default.typo"}]
    before = store.source("default")
    with pytest.raises(Refused, match="default.typo"):
        store.write_source("default", yaml.safe_dump(d, sort_keys=False))
    assert store.source("default") == before                         # refused before anything was written
    with pytest.raises(Refused, match=r"at line \d+, column \d+"):
        store.write_source("default", "environment:\n  - broken: [\n")


def test_yaml_damage_is_named_by_line_and_column(store, capsys):
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    p.write_text(p.read_text(encoding="utf-8") + "  - broken: [\n", encoding="utf-8")
    assert cli.main(["card"]) == 1
    err = capsys.readouterr().err
    assert "line " in err and "column " in err and str(p) in err


# ---- the settings file ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", ["", "[1, 2]", "{not json"], ids=["empty", "a-list", "not-json"])
def test_an_unreadable_settings_file_falls_back_and_is_kept_before_it_is_replaced(store, capsys, text):
    store.state_path.write_text(text, encoding="utf-8")
    assert cli.main(["card"]) == 0                                  # the card, from the defaults
    out = hook.run(json.dumps({"prompt": "hi"}), store)
    assert str(store.state_path) in out and FLOOR_RULE in out
    capsys.readouterr()
    assert cli.main(["doctor"]) == 1 and str(store.state_path) in capsys.readouterr().out
    store.log("a change")                                           # the next write keeps the unreadable file first
    kept = list(store.root.glob("state-unreadable-*.json"))
    assert len(kept) == 1 and kept[0].read_text(encoding="utf-8") == text
    assert isinstance(json.loads(store.state_path.read_text(encoding="utf-8")), dict)
    assert not list(store.root.glob("state-*.tmp"))                 # written whole, through a temporary file


# ---- a stray folder ---------------------------------------------------------------------------------------------------
def test_a_copied_folder_in_profiles_is_skipped_and_reported(store, capsys):
    shutil.copytree(store.root / "profiles" / "default", store.root / "profiles" / "default - Copy")
    assert cli.main(["env", "list"]) == 0
    assert "default - Copy" not in capsys.readouterr().out
    assert "default - Copy" in store.strays() and "default - Copy" not in store.names()
    assert cli.main(["doctor"]) == 1 and "default - Copy" in capsys.readouterr().out


# ---- undo after a hand edit -------------------------------------------------------------------------------------------
def test_undo_after_a_broken_hand_edit_says_where_that_file_is_kept(store, capsys):
    store.learn("default", "Use the staging database for every experiment.")
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    p.write_text(p.read_text(encoding="utf-8") + "  - broken: [\n", encoding="utf-8")
    assert cli.main(["undo", "--last"]) == 0
    out = capsys.readouterr().out
    assert "could not be read" in out and "-redo.yaml" in out


def test_undo_after_a_valid_hand_edit_names_the_rules_it_takes_off(store, capsys):
    rid = store.learn("default", "Use the staging database for every experiment.")
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    d = store.load("default")
    d["entries"].append({"id": "default.by-hand", "kind": "rule", "statement": "Added by hand."})
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")   # not a tracked change
    assert cli.main(["undo", "--last"]) == 0
    out = capsys.readouterr().out
    assert "took off 2 rules" in out and rid in out and "default.by-hand" in out and "-redo.yaml" in out


# ---- the last resort ------------------------------------------------------------------------------------------------
def test_an_unexpected_error_is_one_line_never_a_traceback(store, capsys, monkeypatch):
    def boom(store, args):
        raise KeyError("statement")
    monkeypatch.setattr(cli, "cmd_card", boom)
    assert cli.main(["card"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("semantext: an unexpected KeyError") and "Traceback" not in err and err.count("\n") == 1
