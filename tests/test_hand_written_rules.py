"""A rule written into its file by hand is marked as such: Semantext's own card counts them in one line ("N rules are
hand-written", since every rule Semantext writes carries a provenance type) and the page marks each; the ratified
environments' Rules drawer marks "no provenance", since those files cannot tell a hand-typed rule from one ratified
without a record. Each mark has an arm that must stay unmarked."""
from __future__ import annotations

from pathlib import Path

import yaml

from semantext.sources import rules
from semantext.store import Store


def by_hand(st: Store, name: str, entry: dict) -> None:
    """A rule added to the environment's file directly, as an editor or another program would."""
    p = st.path(name)
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    d["entries"] = (d.get("entries") or []) + [entry]
    p.write_text(yaml.safe_dump(d, sort_keys=False), encoding="utf-8")


def line_of(card: str, rid: str) -> str:
    return next(x for x in card.splitlines() if x.startswith(f"- {rid}:"))


def test_a_rule_typed_into_the_file_is_marked_hand_written_on_the_card(store):
    name = store.state()["active"]
    by_hand(store, name, {"id": f"{name}.typed", "kind": "rule", "statement": "Typed in by hand."})
    by_hand(store, name, {"id": f"{name}.odd", "kind": "rule", "statement": "An unknown origin.",
                          "provenance": {"type": "SOMETHING-ELSE"}})
    rid = store.learn(name, "Answer in one line")
    card = store.card(name)
    assert card.splitlines()[2] == "2 rules are hand-written (no provenance)."      # one line, under the header
    assert line_of(card, f"{name}.typed").endswith("Typed in by hand.")             # never a mark on each rule
    # must-refuse: what Semantext wrote is never counted as hand-written, the rules it ships included
    assert line_of(card, rid).endswith("(learned)")
    assert Store.hand_written({"provenance": {"type": "DEFAULT"}}) is False
    assert Store.hand_written({}) is True and Store.hand_written({"provenance": "a text"}) is True


def test_forty_hand_written_rules_add_at_most_one_line_to_the_card(store):
    name = store.state()["active"]
    before = store.card(name).splitlines()
    for i in range(40):
        by_hand(store, name, {"id": f"{name}.h{i:02d}", "kind": "rule", "statement": f"Rule {i}."})
    after = store.card(name).splitlines()
    added = [x for x in after if x not in before]
    assert len(added) == 41 and "40 rules are hand-written (no provenance)." in added   # 40 rules and one line
    assert sum(len(x) + 1 for x in added) - sum(len(f"- {name}.h{i:02d}: Rule {i}.") + 1 for i in range(40)) == len(
        "40 rules are hand-written (no provenance).") + 1                                  # no byte per rule beyond it


def test_the_page_says_hand_written_where_it_used_to_say_it_came_with_semantext():
    page = (Path(__file__).parents[1] / "semantext" / "static" / "index.html").read_text(encoding="utf-8")
    assert '"DEFAULT" ? "Came with Semantext"' in page
    assert ': "Came with Semantext";' not in page                     # no longer the answer for every unknown rule
    assert "Hand-written: its file records no provenance" in page and "(hand-written)" in page


def card_file(tmp_path: Path, entries: list) -> dict:
    env = tmp_path / "cards" / "core"
    env.mkdir(parents=True)
    (env / "SEMANTICS.yaml").write_text(yaml.safe_dump({
        "environment": {"id": "core", "version": "1.0.0", "status": "ratified", "ratified_by": "pat"},
        "entries": entries, "agents": {"Alder": {"entries": [{"id": "core.alder", "statement": "Alder's own."}]}}}),
        encoding="utf-8")
    return rules.load({"cards": str(tmp_path / "cards")})


def test_a_ratified_rule_with_no_provenance_is_marked_and_only_that(tmp_path):
    out = card_file(tmp_path, [
        {"id": "core.typed", "statement": "No provenance.", "ratified_by": "pat"},
        {"id": "core.blank", "statement": "An empty section.", "ratified_by": "pat", "provenance": {}},
        {"id": "core.told", "statement": "From the owner's words.", "ratified_by": "pat",
         "provenance": {"type": "EXPLICIT", "quote": "say it once"}}])
    got = {r["id"]: r["no_provenance"] for r in out["environments"][0]["rules"]}
    # must-refuse arms: a rule with provenance, and an agent's own layer (the agent is its source), stay unmarked
    assert got == {"core.typed": True, "core.blank": True, "core.told": False, "core.alder": False}
    page = (Path(__file__).parents[1] / "semantext" / "static" / "v2" / "drawers.js").read_text(encoding="utf-8")
    assert 'r.no_provenance ? h("span"' in page and "(no provenance)" in page
