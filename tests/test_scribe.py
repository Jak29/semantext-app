"""An agent may be the scribe of the user's words, never their author. From its shell, a rule it teaches is live only
when it is a whole sentence the user wrote in that same session, as the tool records it, shaped as a preference or said
while correcting. Anything else is a proposal."""
import json

import pytest

from semantext import hook
from semantext.cli import main
from semantext.inbox import Inbox
from semantext.store import Store


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def turn(origin, text):
    return {"type": "user", "turnOrigin": origin, "timestamp": "2026-10-13T16:00:00Z",
            "message": {"role": "user", "content": text}}


@pytest.fixture
def session(home, tmp_path, monkeypatch):
    """A Claude Code session in a project: its transcript, seen by the hook, and the agent's own shell inside it."""
    proj = tmp_path / "proj"
    (proj / ".git").mkdir(parents=True)
    t = tmp_path / "transcript.jsonl"

    def say(*records):
        t.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "s1", "cwd": str(proj),
                             "transcript_path": str(t), "prompt": records[-1]["message"]["content"]}),
                 Store.open(home))
    monkeypatch.chdir(proj)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    return say


def learned(home):
    return {x["id"]: x for x in Store.open(home).load("default").get("entries") or [] if "learned" in x["id"]}


CORRECTION = "No, that's not what I meant. Never push to main without asking me first."


def test_the_users_own_correction_taught_word_for_word_is_their_rule(capsys, home, session):
    session(turn("human", CORRECTION))
    code, out, _ = run(capsys, "teach", "Never push to main without asking me first.")
    assert code == 0 and "the user's own sentence" in out
    rule = learned(home)["default.learned-1"]
    p = rule["provenance"]
    assert rule["statement"] == "Never push to main without asking me first."
    assert p["type"] == "LEARNED" and p["session"] == "s1" and p["scribe"] == "claude-code@proj"
    assert p["prompt"]["offset"] == CORRECTION.find("Never") and len(p["prompt"]["sha256"]) == 16
    assert not Inbox(home).requests()


@pytest.mark.parametrize("prompt, taught", [
    ("Should we always push to main?", "always push to main"),                    # a span of a question
    ("Should we always push to main?", "Should we always push to main?"),         # the question itself
    (CORRECTION, "Never push to main without asking."),                           # a paraphrase
    (CORRECTION, "push to main without asking me first."),                        # part of a sentence
    ("The weather is nice today. Lunch at one.", "The weather is nice today."),   # no rule in it, no correction
    ("should we always push to main", "should we always push to main"),           # a question with no question mark
    ("We always push to main?", "We always push to main?"),                       # a question by its mark alone
    ("Don't worry about that. Delete the old branch.", "Delete the old branch."),  # a one-off order beside a "don't"
    ("don't we always push to main", "don't we always push to main"),             # a negative question
    ("we always push to main, right", "we always push to main, right"),           # a tag question
    ("have we always pushed to main", "have we always pushed to main"),           # another opener
    ("I'm not sure we should always push to main", "I'm not sure we should always push to main"),   # a hedge
    ("maybe we should always push to main", "maybe we should always push to main"),  # a suggestion, not an order
    ("Always push to main, right", "Always push to main, right"),                 # a rule's opening, then a tag
    ("Never push to main, I think.", "Never push to main, I think."),             # a rule's opening, then a hedge
    ("Never mind, push it.", "Never mind, push it."),                             # "never mind" is no rule
    ("When I say done, do I mean pushed?", "When I say done, do I mean pushed?"),  # a reading rule that asks
    ("Don't push yet.", "Don't push yet."),                                       # a choice for now, not for good
    ("Don't merge for now.", "Don't merge for now."),
    ("Never deploy today.", "Never deploy today."),
], ids=["span-of-question", "question", "paraphrase", "part-of-sentence", "not-a-rule", "unmarked-question",
        "question-by-its-mark", "one-off-order", "negative-question", "tag-question", "other-opener", "hedge",
        "suggestion", "rule-then-tag", "rule-then-hedge", "never-mind", "reading-rule-that-asks", "yet", "for-now",
        "today"])
def test_anything_else_from_the_user_is_only_a_proposal(capsys, home, session, prompt, taught):
    session(turn("human", prompt))
    code, out, _ = run(capsys, "teach", taught)
    assert code == 0 and "Proposed, not learned" in out and not learned(home)


@pytest.mark.parametrize("sentence", [
    "No, when I say done I mean pushed.",
    "When I ask whether something could be done, I am asking, not telling you to do it.",
    "When I say maybe, I mean no.",
    "From now on, explain an error before you fix it.",
], ids=["say-mean", "ask-asking", "quotes-a-hedge", "from-now-on"])
def test_a_reading_rule_in_its_own_words_is_written_down(capsys, home, session, sentence):
    session(turn("human", sentence))
    assert "the user's own sentence" in run(capsys, "teach", sentence)[1]


@pytest.mark.parametrize("sentence", ["When I get home, I'll call you.", "When I ask you later, remind me."],
                         ids=["when-i-get-home", "when-i-ask-later"])
def test_a_when_i_sentence_that_is_no_reading_rule_stays_a_proposal(capsys, home, session, sentence):
    session(turn("human", sentence))
    assert "Proposed, not learned" in run(capsys, "teach", sentence)[1]


def test_read_hears_a_correction_that_opens_with_no(store):
    for message in ("No, I meant the other file.", "no, when I say done I mean pushed"):
        assert any(x["rule"] == "base.corrections-become-rules" for x in store.read("default", message, dry=True)["readings"])


def test_a_rule_that_opens_with_do_not_is_still_a_rule(capsys, home, session):
    session(turn("human", "Do not push to main without asking me first."))
    assert "the user's own sentence" in run(capsys, "teach", "Do not push to main without asking me first.")[1]


def test_a_relayed_sentence_is_never_the_users(capsys, home, session):
    session(turn("peer", CORRECTION))                                             # another session sent it
    assert "Proposed, not learned" in run(capsys, "teach", "Never push to main without asking me first.")[1]
    assert not learned(home)


def test_a_borrowed_session_id_lends_no_one_s_words(capsys, home, session, tmp_path, monkeypatch):
    session(turn("human", CORRECTION))
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ".git").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)                                                  # s1's id, inherited in another project
    assert "Proposed, not learned" in run(capsys, "teach", "Never push to main without asking me first.")[1]
    assert not learned(home)
