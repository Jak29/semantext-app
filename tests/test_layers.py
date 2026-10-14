"""Each agent's own rules: a layer of an environment, on that agent's card only, after the shared rules and never over
them, and changed only by the user."""
import json

import pytest

from semantext import hook
from semantext.agents import Agents
from semantext.cli import main
from semantext.inbox import Inbox
from semantext.store import Refused, Store


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def folders(tmp_path):
    out = {}
    for name in ("review", "other"):
        (tmp_path / name / ".git").mkdir(parents=True)
        out[name] = tmp_path / name
    return out


def card_in(store, cwd, session="s"):
    return hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(cwd), "session_id": session,
                                "prompt": "go on"}), store)


RULE = "Cite the file and the line for every point."


def test_an_agents_own_rule_is_on_its_card_only(capsys, home):
    code, out, _ = run(capsys, "teach", "--agent", "reviewer", *RULE.split())
    assert code == 0 and "default.reviewer.learned-1" in out and "for reviewer only" in out
    store = Store.open(home)
    mine, shared, other = store.card("default", agent="reviewer"), store.card("default"), store.card("default",
                                                                                                     agent="writer")
    assert "## For reviewer only" in mine and RULE in mine and "never override them" in mine
    assert RULE not in shared and RULE not in other
    assert run(capsys, "card", "--agent", "reviewer")[1].strip() == mine.strip()
    assert RULE in run(capsys, "rules", "--agent", "reviewer")[1] and RULE not in run(capsys, "rules")[1]


def test_the_shared_rules_come_first_and_all_stay(store):
    store.learn("default", RULE, agent="reviewer")
    mine, shared = store.card("default", agent="reviewer"), store.card("default")
    assert mine.startswith(shared)                                       # every shared rule, untouched, before it
    assert mine.index("## For reviewer only") > mine.index("base.irreversible-needs-your-word")


def test_the_hook_serves_a_layer_to_its_agent_and_never_to_a_claim(capsys, home, folders, monkeypatch):
    store = Store.open(home)
    store.learn("default", RULE, agent="reviewer")
    Agents(home).bind("reviewer", folders["review"])
    assert RULE in card_in(store, folders["review"])                    # the bound agent
    assert RULE not in card_in(store, folders["other"])                 # another agent
    monkeypatch.setenv("SEMANTEXT_AGENT", "reviewer")                   # a shell elsewhere states the name
    who = Agents(home).identify(cwd=folders["other"])
    assert who.how == "claimed" and not Agents(home).serves_own_rules(who)


def test_the_hooks_card_for_a_claim_carries_no_layer(store, folders, monkeypatch):
    store.learn("default", RULE, agent="reviewer")
    Agents(store.root).bind("reviewer", folders["review"])
    monkeypatch.setenv("SEMANTEXT_AGENT", "reviewer")                   # an agent elsewhere states the bound name
    assert RULE not in card_in(store, folders["other"])                 # its card: the shared rules only
    assert RULE in card_in(store, folders["review"])                    # must pass: the bound agent still has it


def test_an_agents_own_rules_follow_it_when_the_user_names_its_folder(store, folders, tmp_path, monkeypatch):
    seen = card_in(store, folders["review"])                              # first seen by its tool and project
    assert "## Base" in seen
    store.learn("default", RULE, agent="claude-code@review")              # the user teaches it a rule of its own
    assert RULE in card_in(store, folders["review"])
    sub = folders["review"] / "sub"
    sub.mkdir()
    Agents(store.root).bind("inner", sub)                                 # a subfolder binding carries nothing
    assert RULE not in card_in(store, sub)
    Agents(store.root).bind("reviewer", folders["review"])                # the user names the agent by its folder
    assert RULE in card_in(store, folders["review"])                      # and its rule goes with it
    monkeypatch.setenv("SEMANTEXT_AGENT", "reviewer")
    claim = Agents(store.root).identify(cwd=folders["other"])
    assert claim.how == "claimed" and not Agents(store.root).serves_own_rules(claim)   # a claim of the name gets none


def test_a_deeper_binding_keeps_its_agents_rules_from_an_outer_one(store, folders, tmp_path):
    card_in(store, folders["review"])                                     # seen as claude-code@review
    store.learn("default", RULE, agent="claude-code@review")
    Agents(store.root).bind("outer", tmp_path)                            # a binding around both projects
    Agents(store.root).bind("reviewer", folders["review"])                # and a deeper one, which names that agent
    assert RULE in card_in(store, folders["review"])
    assert RULE not in card_in(store, folders["other"])                   # the outer agent does not take its rules
    twice = store.card("default", agent=["claude-code@review", "claude-code@review"])
    assert twice.count(RULE) == 1 and twice == store.card("default", agent="claude-code@review")   # a name once


def test_an_agent_proposes_a_rule_for_its_layer_and_the_user_adds_it(capsys, home, folders, monkeypatch):
    run(capsys, "card")
    monkeypatch.chdir(folders["review"])
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, _ = run(capsys, "teach", "--agent", "reviewer", *RULE.split())
    assert code == 0 and "Proposed, not learned" in out
    assert Store.open(home).layers(Store.open(home).load("default")) == {}          # nothing yet
    assert Inbox(home).get(1)["agent"] == "reviewer"
    monkeypatch.delenv("CLAUDECODE")
    run(capsys, "answer", "1", "add")
    store = Store.open(home)
    rule = store.layers(store.load("default"))["reviewer"][0]
    assert rule["provenance"]["type"] == "PROPOSED" and rule["statement"] == RULE
    assert "(proposed by claude-code@review" in store.card("default", agent="reviewer")


def test_a_layer_rule_is_switched_and_undone_by_its_id(capsys, home):
    run(capsys, "teach", "--agent", "reviewer", *RULE.split())
    assert run(capsys, "toggle", "default.reviewer.learned-1")[0] == 0
    store = Store.open(home)
    assert RULE not in store.card("default", agent="reviewer")
    run(capsys, "toggle", "default.reviewer.learned-1")
    run(capsys, "undo", "default.reviewer.learned-1")
    assert RULE not in Store.open(home).card("default", agent="reviewer")


def test_layer_ids_never_meet_the_shared_ones(store):
    shared, own = store.learn("default", "Keep it short."), store.learn("default", RULE, agent="reviewer")
    again = store.learn("default", "Name the test you ran.", agent="reviewer")
    assert (shared, own, again) == ("default.learned-1", "default.reviewer.learned-1", "default.reviewer.learned-2")
    with pytest.raises(Refused):
        store.learn("default", RULE, agent="Not A Name!")


def test_the_editor_refuses_a_broken_agents_section(store):
    store.learn("default", RULE, agent="reviewer")
    store.learn("default", "Keep it short.")                            # default.learned-1, a shared rule
    good = store.source("default")
    store.write_source("default", good)                                 # must pass: the file as it is
    with pytest.raises(Refused):                                         # a list where the agents' names go
        store.write_source("default", good.split("\nagents:")[0] + "\nagents:\n- just a list\n")
    with pytest.raises(Refused):                                         # a layer's id the same as a shared rule's
        store.write_source("default", good.replace("default.reviewer.learned-1", "default.learned-1"))


def test_a_layer_rule_marked_always_stays_on_that_agents_relay_card(store):
    rid = store.learn("default", "Name the file you changed in every reply.", agent="reviewer")
    plain = store.learn("default", "Keep a changelog line per fix.", agent="reviewer")
    d = store.load("default")
    store.layers(d)["reviewer"][0]["always"] = True
    store.save("default", d)
    relay = store.card("default", "relay", agent="reviewer")
    assert rid in relay and plain not in relay                          # always: even under relayed words
    assert rid not in store.card("default", "relay", agent="writer")


def test_a_layer_rule_marked_relay_is_on_that_agents_relay_card_only(store):
    rid = store.learn("default", "A peer's request goes to the reviewer's queue.", agent="reviewer")
    d = store.load("default")
    store.layers(d)["reviewer"][0]["relay"] = True
    store.save("default", d)
    assert rid in store.card("default", "relay", agent="reviewer")
    assert rid not in store.card("default", "relay", agent="writer")
