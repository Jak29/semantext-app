"""What was heard, the proposals made from it, and the hook that hands the card to an AI."""
import io
import json

import pytest

from semantext import hook
from semantext.heard import Heard
from semantext.store import Refused


def test_hear_recall_and_forget(store, home):
    h = Heard(home)
    h.hear("default", "Please keep answers short")
    h.hear("default", "What is the capital of Peru?")
    assert [i["text"] for i in h.recall("default")] == ["What is the capital of Peru?", "Please keep answers short"]
    assert [i["id"] for i in h.recall("default", "short answers")] == [1]
    assert h.forget("default", [1]) == 1
    assert [i["id"] for i in h.items("default")] == [2]
    assert h.forget("default") == 1 and h.items("default") == []


def test_hearing_nothing_is_refused(store, home):
    with pytest.raises(Refused):
        Heard(home).hear("default", "   ")


def test_a_damaged_line_is_skipped_not_fatal(store, home):
    h = Heard(home)
    h.hear("default", "First")
    with h.path("default").open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    h.hear("default", "Second")
    assert [i["text"] for i in h.items("default")] == ["First", "Second"]


def test_proposals_come_from_rule_shaped_sentences_only(store, home):
    h = Heard(home)
    h.hear("default", "Never use bullet points for short answers. What time is it?")
    h.hear("default", "Thanks, that helps")
    props = Heard(home).propose("default", store)
    assert [p["statement"] for p in props] == ["Never use bullet points for short answers."]


def test_an_accepted_proposal_is_not_proposed_again(store, home):
    h = Heard(home)
    h.hear("default", "Always cite your sources")
    statement = h.propose("default", store)[0]["statement"]
    store.learn("default", statement)
    assert h.propose("default", store) == []


def test_the_hook_prints_the_active_card(store):
    out = hook.run(json.dumps({"prompt": "hello"}), store)
    assert out == store.card("default")


def test_the_hook_keeps_prompts_only_when_switched_on(store, home, tmp_path):
    t = tmp_path / "t.jsonl"     # only words the tool's own record calls the user's are kept
    t.write_text(json.dumps({"type": "user", "turnOrigin": "human", "message": {"content": "Never apologise"}}) + "\n",
                 encoding="utf-8")
    event = json.dumps({"prompt": "Never apologise", "transcript_path": str(t)})
    hook.run(event, store)
    assert Heard(home).items("default") == []
    store.set_option("hear_prompts", True)
    hook.run(event, store)
    assert [i["text"] for i in Heard(home).items("default")] == ["Never apologise"]


def test_the_hook_survives_an_event_that_is_not_json(store):
    assert hook.run("not json", store).startswith("# Semantext")


def test_the_hook_never_blocks_a_prompt(home, monkeypatch, capsys):
    (home / "profiles" / "default").mkdir(parents=True)
    (home / "profiles" / "default" / "SEMANTICS.yaml").write_text("environment: [broken", encoding="utf-8")
    (home / "profiles" / "base").mkdir(parents=True)
    (home / "profiles" / "base" / "SEMANTICS.yaml").write_text("environment: [broken", encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    assert hook.main() == 0
    out = capsys.readouterr().out                  # both files broken: the problem is named, and the prompt goes on
    assert "not valid YAML" in out and "could not be read either" in out


def test_a_card_that_fits_is_unchanged():
    card = "# head\n- a: one\n- b: two"
    assert hook.fit(card) == card


def test_a_large_card_keeps_whole_rules_under_the_limit():
    card = "# head\n" + "\n".join(f"- rule.{i}: " + "word " * 30 for i in range(200))
    out = hook.fit(card)
    assert len(out.encode("utf-8")) <= hook.LIMIT_BYTES
    rules = [line for line in out.splitlines() if line.startswith("- ")]
    assert all(line.endswith("word ") or line.endswith("word") for line in rules)   # no rule cut in the middle
    assert out.splitlines()[-1].startswith(f"({200 - len(rules)} more rules not shown")
