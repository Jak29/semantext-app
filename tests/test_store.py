"""The store: environments, suggestions, teaching, undo, the editor and the reading. Each behaviour has a test that
must pass and, where it can go wrong, one that must be refused."""
from pathlib import Path

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


# ---- review of 1.2.2: S1 to S6 ----------------------------------------------------------------------------------
FLOOR = ("base.irreversible-needs-your-word", "base.relayed-words-are-information")


def test_every_rule_file_the_store_writes_lands_through_one_atomic_swap(store, monkeypatch):
    # review of 1.2.2, S1: SEMANTICS.yaml was written in place (write_text, copyfile); only state.json was swapped
    import os
    swapped, real = [], os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (swapped.append(Path(b).name), real(a, b))[1])
    store.learn("default", "be brief")                        # save, and the history copy before it
    store.write_source("default", store.source("default"))    # the editor's save
    store.create("Cooking", [])                               # a new environment
    store.undo_last("default")                                # the restore
    assert swapped.count("SEMANTICS.yaml") == 4
    assert sum(n.endswith(".yaml") and n != "SEMANTICS.yaml" for n in swapped) >= 3   # history and the redo copy
    assert "state.json" in swapped
    assert not list(store.root.rglob("*.tmp"))


def test_a_write_that_fails_before_the_swap_leaves_the_old_file_whole(store, monkeypatch):
    # review of 1.2.2, S1: a crash between writing and syncing must leave the file as it was, never half of it
    import os
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    before = p.read_bytes()

    def crash(fd):
        raise OSError("the disk went away")
    monkeypatch.setattr(os, "fsync", crash)
    with pytest.raises(OSError):
        store.learn("default", "be brief")
    with pytest.raises(OSError):
        store.write_source("default", store.source("default").replace("\n", "\n\n", 1))
    assert p.read_bytes() == before
    assert not list(store.root.rglob("*.tmp"))                # nothing left behind either
    monkeypatch.undo()
    store.learn("default", "be brief")                        # must-pass: the same write lands once the disk is back
    assert "be brief" in store.source("default")


def test_threads_writing_the_settings_at_once_raise_nothing_and_leave_valid_json(store):
    # review of 1.2.2, S2: the temporary name was the process id only, and the page's server writes from threads
    import json
    import threading
    errors = []

    def hammer(k):
        for i in range(100):
            try:
                s = store.state()
                s["log"].append({"what": f"{k}-{i}"})
                store.put_state(s)
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))
    threads = [threading.Thread(target=hammer, args=(k,)) for k in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert isinstance(json.loads(store.state_path.read_text(encoding="utf-8")), dict)
    assert store.state_problem is None and not list(store.root.glob("*.tmp"))


def _refused_reads(monkeypatch, times):
    """Path.read_text refuses state.json this many times, as Windows does while the file is being swapped in."""
    from pathlib import Path
    real, left = Path.read_text, {"n": times}

    def read_text(self, *a, **k):
        if self.name == "state.json" and left["n"]:
            left["n"] -= 1
            raise PermissionError(13, "in use")
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr("semantext.store.time.sleep", lambda _: None)


def test_a_read_refused_for_a_while_on_a_busy_machine_still_reads_the_settings(store, monkeypatch):   # must pass
    s = store.state()
    s["hear_prompts"] = True
    store.put_state(s)
    _refused_reads(monkeypatch, 15)                      # longer than the three tries that lost this before
    assert store.state()["hear_prompts"] is True and store.state_problem is None


def test_defaults_from_a_read_that_was_refused_are_never_saved_over_the_settings(store, monkeypatch):   # must refuse
    s = store.state()
    s["hear_prompts"] = True
    store.put_state(s)
    kept = store.state_path.read_bytes()
    from semantext.store import READ_TRIES
    _refused_reads(monkeypatch, READ_TRIES)
    stood_in = store.state()
    assert store.state_problem and stood_in["hear_prompts"] is False
    with pytest.raises(Refused, match="nothing is saved over it"):
        store.put_state(stood_in)
    assert store.state_path.read_bytes() == kept


def test_a_damaged_settings_file_is_still_replaced_and_its_copy_kept(store):   # must pass: damaged is not refused
    store.state_path.parent.mkdir(parents=True, exist_ok=True)
    store.state_path.write_text("{ not json", encoding="utf-8")
    s = store.state()
    assert store.state_problem
    store.put_state(s)
    assert store.state()["active"] == "default" and store.state_problem is None
    assert list(store.state_path.parent.glob("state-unreadable-*.json"))


@pytest.mark.parametrize("prov", ["learned", ["LEARNED"], 7], ids=["a-string", "a-list", "a-number"])
def test_a_provenance_that_is_not_a_mapping_reads_as_none_recorded(store, prov):
    # review of 1.2.2, S3: a plain-string provenance made the card's _line raise AttributeError in the hook
    d = store.load("default")
    d["entries"] = [*(d.get("entries") or []), {"id": "default.hand", "statement": "By hand.", "provenance": prov}]
    store.save("default", d)
    text, plan = store.served("default")
    assert "- default.hand: By hand." in text and not plan["problem"]
    assert "(learned)" not in text.split("default.hand")[1].splitlines()[0]
    row = next(p for p in store.overview()["profiles"] if p["name"] == "default")
    assert row["learned"] == 0


def test_one_broken_environment_never_blocks_switching_to_or_making_another(store):
    # review of 1.2.2, S4: resolve and create read every title, so one broken file refused them all
    (store.root / "profiles" / "old").mkdir()
    (store.root / "profiles" / "old" / "SEMANTICS.yaml").write_text("environment: [unclosed", encoding="utf-8")
    assert store.resolve("Default") == "default"
    assert store.resolve("old") == "old"                      # a broken file still answers to its own name
    slug = store.create("Cooking", [])
    assert store.resolve("Cooking") == slug
    with pytest.raises(Refused, match=r"could not be read.*old"):
        store.resolve("Nowhere")                              # must-refuse, and the skipped file is named
    titles, problems = store.titles()
    assert "default" in titles and [p["name"] for p in problems] == ["old"]


def test_undo_last_never_raises_after_the_restore_and_says_what_failed(store, capsys):
    # review of 1.2.2, S5: title() ran after the restore, outside any try, so an unreadable restored version raised
    from semantext import cli

    def break_newest(name):
        store.learn(name, "be brief")
        newest = sorted((store.root / "history").glob(f"{name}-*.yaml"))[-1]
        newest.write_text("environment: [broken", encoding="utf-8")
        return newest
    newest = break_newest("default")
    assert store.undo_last("default") == newest.name
    assert "cannot be read" in store.last_undo["problem"]
    assert "Problem: the restored version cannot be read" in store.state()["log"][-1]["what"]
    assert store.source("default") == "environment: [broken"   # the restore did happen
    slug = store.create("Cooking", [])
    break_newest(slug)
    assert cli.main(["undo", "--last", "--env", slug]) == 0
    out = capsys.readouterr().out
    assert f"Undid the last change in {slug}" in out and "But: the restored version cannot be read" in out
    clean = store.create("Gardening", [])
    store.learn(clean, "be plain")
    store.undo_last(clean)
    assert store.last_undo["problem"] is None                  # must-pass: a clean undo names no problem


def test_the_floor_rules_stay_on_both_cards_whatever_their_switches_say(store):
    # review of 1.2.2, S6: with both switched off, the relay card fell back to the full card, which held neither
    for rid in FLOOR:
        with pytest.raises(Refused, match="on every card"):
            store.toggle("base", rid)
        with pytest.raises(Refused, match="on every card"):
            store.undo("base", rid)
    d = store.load("base")
    for x in d["entries"]:
        if x["id"] in FLOOR:
            x["enabled"] = False                              # a hand edit, or a restored old version
    store.save("base", d)
    relay, full = store.card("default", form="relay"), store.card("default")
    assert all(rid in relay for rid in FLOOR) and all(rid in full for rid in FLOOR)
    assert store.plan("default", form="relay")["form"] == "relay"
    other = next(x["id"] for x in d["entries"] if x["id"] not in FLOOR)
    store.toggle("base", other)                               # must-pass: any other base rule still switches off
    assert other not in store.card("default")
