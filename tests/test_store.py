"""The store: environments, suggestions, teaching, undo, the editor and the reading. Each behaviour has a test that
must pass and, where it can go wrong, one that must be refused."""
import pytest
import yaml

from semantext import paths
from semantext.store import Refused, Store


def nulls(obj, path=""):
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in nulls(v, f"{path}.{k}")]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in nulls(v, f"{path}[{i}]")]
    return [path] if obj is None else []


def test_shipped_files_hold_no_null_values():
    # A comma inside an unquoted flow mapping ({note: a, b}) silently splits it into a second key with a null value.
    files = list((paths.package_data() / "profiles").glob("*/SEMANTICS.yaml"))
    files += list(paths.suggestions_dir().glob("*.yaml"))
    assert len(files) >= 6
    found = [f"{f.name}{p}" for f in files for p in nulls(yaml.safe_load(f.read_text(encoding="utf-8")))]
    assert found == []


def test_the_null_check_sees_a_planted_null():
    assert nulls({"provenance": {"note": "a", "b": None}}) == [".provenance.b"]


def test_a_new_home_starts_on_default_with_the_base_rules(store):
    assert store.state()["active"] == "default"
    assert store.names()[0] == "default" and "base" in store.names()
    card = store.card("default")
    assert card.startswith("# Semantext: standing rules for reading this user (Default environment)")
    assert "- base.question-not-instruction:" in card


def test_opening_a_home_twice_overwrites_nothing(home):
    s = Store.open(home)
    s.learn("default", "Answer in British English")
    again = Store.open(home)
    assert "Answer in British English" in again.card("default")


def test_a_name_that_fits_a_pack_gets_its_rules_ticked(store):
    sg = store.suggest("Studying for exams")
    assert sg["matched"] and len(sg["rules"]) >= 3
    assert all(r["pack"] == "research" and r["ticked"] for r in sg["rules"])


def test_a_name_that_fits_no_pack_ticks_nothing_and_offers_one_idea_per_pack(store):
    sg = store.suggest("Zzyzx")
    assert not sg["matched"]
    assert not any(r["ticked"] for r in sg["rules"])
    assert len(sg["rules"]) == len(store.packs())


def test_a_new_environment_holds_the_rules_picked_and_becomes_active(store):
    picks = [{"pack": r["pack"], "id": r["id"]} for r in store.suggest("Office")["rules"]]
    name = store.create("Office", picks)
    assert name == "office" and store.state()["active"] == "office"
    assert "- office.outcome-first:" in store.card("office")


def test_the_same_name_never_overwrites(store):
    store.create("Office", [])
    assert store.create("Office", []) == "office-2"


def test_teaching_keeps_your_exact_words(store):
    rid = store.learn("default", "Never use bullet points for short answers")
    rule = [e for e in store.load("default")["entries"] if e["id"] == rid][0]
    assert rule["provenance"]["words"] == "Never use bullet points for short answers"
    assert rule["mode"] == "adaptive"
    assert f"- {rid}: Never use bullet points for short answers (learned)" in store.card("default")


def test_undo_keeps_the_rule_in_the_file_but_off_the_card(store):
    rid = store.learn("default", "Cite the page number")
    store.undo("default", rid)
    assert any(e["id"] == rid and e.get("archived") for e in store.load("default")["entries"])
    assert rid not in store.card("default")


def test_a_rule_switched_off_is_off_the_card(store):
    store.create("Office", [{"pack": "work", "id": "work.outcome-first"}])
    assert store.toggle("office", "office.outcome-first") is False
    assert "office.outcome-first" not in store.card("office")
    assert store.toggle("office", "office.outcome-first") is True
    assert "office.outcome-first" in store.card("office")


def test_pin_switches_between_stationary_and_adaptive(store):
    store.create("Office", [{"pack": "work", "id": "work.outcome-first"}])
    assert store.pin("office", "office.outcome-first") == "adaptive"
    assert store.pin("office", "office.outcome-first") == "stationary"


def test_the_news_switch_adds_a_rule_for_the_chosen_country(store):
    store.feature("default", "news", True, "Ireland")
    assert "focused on Ireland" in store.card("default")
    store.feature("default", "news", False)
    assert "focused on Ireland" not in store.card("default")


def test_every_write_keeps_the_old_version(store, home):
    store.learn("default", "One")
    store.learn("default", "Two")
    store.feature("default", "jokes", True)
    assert len(list((home / "history").glob("default-*.yaml"))) >= 3


def test_the_editor_saves_a_valid_environment(store):
    good = store.source("default").replace("grows from what you teach it.", "grows from what you teach it, always.")
    store.write_source("default", good)
    assert "always" in store.source("default")


def test_reading_a_question_and_a_material_act(store):
    r = store.read("default", "Can you delete the old files?")
    assert any(x["label"] == "A question" for x in r["readings"])
    assert any('"delete"' in d["ask"] for d in r["decisions"])
    assert len(store.state()["pending"]) == 1


def test_an_ordinary_request_asks_for_no_decision(store):
    r = store.read("default", "Tell me about the weather")
    assert r["decisions"] == [] and r["touched"] == []
    assert r["readings"][0]["label"] == "An instruction"


def test_words_that_share_meaning_with_a_rule_touch_it_unless_it_is_off(store):
    store.create("Office", [{"pack": "work", "id": "work.three-options"}, {"pack": "work", "id": "work.outcome-first"}])
    store.toggle("office", "office.outcome-first")
    r = store.read("office", "Give me three options for the outcome")
    assert "office.three-options" in r["touched"]
    assert "office.outcome-first" not in r["touched"]


def test_a_dry_read_saves_no_pending_decision(store):
    store.read("default", "Please delete everything", dry=True)
    assert store.state()["pending"] == []


def test_a_pending_decision_can_be_answered_once(store):
    d = store.read("default", "Send the report")["decisions"][0]
    store.decide(d["id"], "yes")
    assert store.state()["pending"] == []
    with pytest.raises(Refused):
        store.decide(d["id"], "yes")


def test_undo_last_goes_back_one_change_at_a_time_and_deletes_nothing(store, home):
    store.create("Lab", [])
    store.feature("lab", "jokes", True)
    store.learn("lab", "Cite the page number")
    store.undo_last("lab")
    assert "Cite the page number" not in store.card("lab") and "feature.jokes" in store.card("lab")
    store.undo_last("lab")
    assert "feature.jokes" not in store.card("lab")
    assert len(list((home / "history").glob("lab-*.yaml"))) >= 4


def test_undo_with_no_history_is_refused(store):
    store.create("Fresh", [])
    with pytest.raises(Refused):
        store.undo_last("fresh")


def test_a_missing_active_environment_falls_back_to_default(store):
    store.put_state(dict(store.state(), active="gone"))
    assert store.state()["active"] == "default"


@pytest.mark.parametrize("label, call", [
    ("a path as an environment name", lambda s: s.load("../x")),
    ("broken YAML in the editor", lambda s: s.write_source("default", "environment: [")),
    ("a changed environment id", lambda s: s.write_source("default", s.source("default").replace("id: default", "id: x", 1))),
    ("a rule without a statement", lambda s: s.write_source(
        "default", "environment: {id: default, version: 0.1.0, scope: x}\nentries:\n- id: a\n")),
    ("two rules sharing an id", lambda s: s.write_source(
        "default", "environment: {id: default, version: 0.1.0, scope: x}\nentries:\n"
                   "- {id: a, statement: one}\n- {id: a, statement: two}\n")),
    ("an empty correction", lambda s: s.learn("default", "   ")),
    ("a correction over 400 characters", lambda s: s.learn("default", "x" * 401)),
    ("a model not on this machine", lambda s: s.set_model("no-such-model:latest")),
    ("base as the active environment", lambda s: s.set_active("base")),
    ("a title with a path in it", lambda s: s.create("../evil", [])),
    ("a suggestion that does not exist", lambda s: s.create("Lab", [{"pack": "work", "id": "work.nope"}])),
    ("an unknown rule", lambda s: s.toggle("default", "default.nope")),
    ("an unknown feature", lambda s: s.feature("default", "lasers", True)),
    ("an unknown setting", lambda s: s.set_option("telemetry", True)),
])
def test_refused(store, label, call):
    with pytest.raises(Refused):
        call(store)


def test_a_refused_edit_leaves_the_file_unchanged(store):
    before = store.source("default")
    with pytest.raises(Refused):
        store.write_source("default", "environment: [")
    assert store.source("default") == before
