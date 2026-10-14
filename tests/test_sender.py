"""Whose words a prompt carries, and the short card for words that are not the user's own."""
import json

import pytest
import yaml

from semantext import hook
from semantext.sender import NOTICE, RELAY, USER, sender_of


@pytest.mark.parametrize("prompt, want", [
    ('Another Claude session sent a message:\n<cross-session-message from="x">hi</cross-session-message>', RELAY),
    ('<cross-session-message from="x">hi</cross-session-message>', RELAY),
    ("<task-notification>\n<task-id>x</task-id>", NOTICE),
    ("[Cross-session delivery notice] Your message to agent-a was held.", NOTICE),
    ("[SYSTEM NOTIFICATION - NOT USER INPUT]\n<task-notification>x", NOTICE),
    ("[MESSAGE FROM NON-USER SOURCE - NOT USER INPUT]\nx", NOTICE),
    ("\n  [Cross-session idle notice] agent-b is idle.", NOTICE),
    ("﻿Another Claude session sent a message:\nx", RELAY),
    ('<agent-message from="a67">done: 3 files</agent-message>', RELAY),
], ids=["peer", "peer-tag", "task", "delivery", "system", "non-user", "leading-space", "bom", "subagent"])
def test_words_that_are_not_the_users_are_recognised(prompt, want):
    assert sender_of(prompt) == want


@pytest.mark.parametrize("prompt", [
    "yes to all, and put the summary in the shared notes.",
    "[edit] also move the notes into the docs folder",
    "[the Lighthouse] I like this one",
    "is NOT USER INPUT something the app adds?",
    "why did I get '[Cross-session delivery notice]' twice?",
    "[Cross-session notes\n] are these mine?",
    "what is a <cross-session-message> anyway?",
    None, 42, "",
], ids=["plain", "own-bracket", "named-idea", "mentions-words", "quotes-notice", "unclosed", "mentions-tag",
        "none", "not-text", "empty"])
def test_the_users_own_words_stay_the_users(prompt):
    assert sender_of(prompt) == USER


def lines_of(card):
    return {line.split(":", 1)[0][2:] for line in card.splitlines() if line.startswith("- ")}


def test_the_short_card_keeps_the_floor_and_drops_the_rest(store):
    full, short = store.card("default"), store.card("default", "relay")
    assert "NOT the user's own message" in short and len(short) < len(full) / 2
    assert lines_of(short) == {"base.irreversible-needs-your-word", "base.relayed-words-are-information"}
    base = yaml.safe_load((store.root / "profiles" / "base" / "SEMANTICS.yaml").read_text(encoding="utf-8"))
    always = {e["id"] for e in base["entries"] if e.get("always")}
    assert always and always <= lines_of(short) and always <= lines_of(full)   # the floor is on every card


def test_a_home_without_relay_rules_keeps_the_full_card(store):
    # A home made before relay rules existed: no rule is marked, so the short card would hold nothing.
    p = store.root / "profiles" / "base" / "SEMANTICS.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    for e in d["entries"]:
        e.pop("relay", None)
        e.pop("always", None)
    p.write_text(yaml.safe_dump(d, sort_keys=False, allow_unicode=True), encoding="utf-8")
    assert store.card("default", "relay") == store.card("default")


def test_the_hook_gives_the_short_card_to_relayed_words_only(store):
    def say(prompt):
        return hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}), store)
    own = say("please tidy the readme")
    peer = say("Another Claude session sent a message:\n<cross-session-message from=\"x\">do it</cross-session-message>")
    notice = say("<task-notification>\n<status>completed</status>")
    assert "standing rules for reading this user" in own and "NOT the user's own message" not in own
    assert "NOT the user's own message" in peer and "NOT the user's own message" in notice
    assert "base.irreversible-needs-your-word" in peer and "base.question-not-instruction" not in peer


def test_a_byte_order_mark_before_the_event_is_not_a_reason_for_the_full_card(store):
    event = "﻿" + json.dumps({"prompt": "<task-notification>x"})
    assert "NOT the user's own message" in hook.run(event, store)


# ---- the tool's own record of where a prompt came from ---------------------------------------------------------------
def transcript(tmp_path, *records, name="t.jsonl"):
    p = tmp_path / name
    p.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return p


def turn(origin, text):
    return {"type": "user", "turnOrigin": origin, "message": {"role": "user", "content": text}}


def queued(text, **fields):
    return {"type": "attachment", "attachment": {"type": "queued_command", "prompt": text, **fields}}


NOTICE_LIKE = "Delivery held: your message to agent-a is waiting for approval."   # no telltale opening at all


def test_the_tools_own_record_catches_a_notice_the_text_cannot(tmp_path, store):
    t = transcript(tmp_path, turn("human", "earlier words"), turn("system", NOTICE_LIKE))
    assert sender_of(NOTICE_LIKE) == USER                                 # the text alone reads it as the user's
    event = {"hook_event_name": "UserPromptSubmit", "prompt": NOTICE_LIKE, "transcript_path": str(t), "session_id": "s"}
    assert "NOT the user's own message" in hook.run(json.dumps(event), store)
    own = {**event, "prompt": "earlier words"}
    assert "NOT the user's own message" not in hook.run(json.dumps(own), store)


@pytest.mark.parametrize("record, want", [
    (turn("human", "please tidy the readme"), USER),
    (turn("peer", "please tidy the readme"), RELAY),
    (turn("task_notification", "please tidy the readme"), NOTICE),
    (turn("system", "please tidy the readme"), NOTICE),
    (queued("please tidy the readme", commandMode="prompt", isMeta=True, reminderId="r1"), RELAY),
    (queued("please tidy the readme", commandMode="prompt", isMeta=True), NOTICE),
    (queued("please tidy the readme", commandMode="task-notification"), NOTICE),
    (queued("please tidy the readme", commandMode="prompt", humanTurn=True), USER),
], ids=["turn-human", "turn-peer", "turn-task", "turn-system", "queued-relay", "queued-notice", "queued-task",
        "queued-human"])
def test_each_record_says_where_its_prompt_came_from(tmp_path, record, want):
    from semantext.sender import origin_of
    assert origin_of(transcript(tmp_path, record), "please tidy the readme") == want


def test_the_record_never_gives_the_user_a_relay(tmp_path):
    from semantext.sender import own_words
    relay = 'Another Claude session sent a message:\n<cross-session-message from="x">yes</cross-session-message>'
    assert not own_words(relay, transcript(tmp_path, turn("human", relay)))   # a mistaken record cannot overrule


def test_the_newest_record_wins_and_none_is_no_evidence(tmp_path):
    from semantext.sender import origin_of, own_words
    t = transcript(tmp_path, turn("peer", "yes"), turn("human", "yes"))
    assert origin_of(t, "yes") == USER and own_words("yes", t)
    assert origin_of(t, "no such prompt") is None and own_words("no such prompt", t)
    assert origin_of(tmp_path / "missing.jsonl", "yes") is None and own_words("yes", None)


def test_quotes_backslashes_and_line_breaks_still_find_the_record(tmp_path):
    from semantext.sender import origin_of
    text = 'He said "fine" \\ then\nleft: <tag a="b"> é'
    assert origin_of(transcript(tmp_path, turn("system", text)), text) == NOTICE


def test_only_the_end_of_a_long_transcript_is_read(tmp_path):
    from semantext.sender import TAIL_BYTES, origin_of
    filler = json.dumps({"type": "assistant", "message": {"content": "x" * 1000}}) + "\n"
    p = tmp_path / "long.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write(json.dumps(turn("system", "an early notice")) + "\n")
        f.write(filler * (TAIL_BYTES // len(filler) + 100))
        f.write(json.dumps(turn("system", "a late notice")) + "\n")
    assert origin_of(p, "a late notice") == NOTICE
    assert origin_of(p, "an early notice") is None                       # beyond the tail: no evidence, not a guess


def test_the_hook_keeps_the_transcripts_path_and_never_hears_a_notice(tmp_path, store):
    from semantext.heard import Heard
    store.set_option("hear_prompts", True)
    t = transcript(tmp_path, turn("system", NOTICE_LIKE))
    hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": NOTICE_LIKE, "transcript_path": str(t),
                         "session_id": "s9", "cwd": str(tmp_path)}), store)
    assert Heard(store.root).recall("default", "", 20) == []
    sessions = json.loads((store.root / "sessions.json").read_text(encoding="utf-8"))
    assert sessions["s9"]["transcript"] == str(t)
