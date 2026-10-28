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


# ---- one reader for both engines (provenance.py): the drift found by the audit of e36d0c0 -------------------------
def _estate_owner(tmp_path, prompt, t):
    from semantext import envhook
    cfg = envhook.Config({"environments": str(tmp_path / "envs"), "core": "core", "headers": {}})
    return envhook.from_owner(prompt, str(t), cfg)


def test_a_compaction_summary_is_never_heard_as_the_users_words(tmp_path, store):
    # F-D: a compaction summary carries turnOrigin "human"; the hook read it as the user's own, with basis
    # "transcript", and with hearing on kept it as the user's words
    from semantext.heard import Heard
    store.set_option("hear_prompts", True)
    summary = "This session is being continued from a previous conversation that ran out of context."
    t = transcript(tmp_path, {**turn("human", summary), "isCompactSummary": True})
    from semantext.sender import whose
    assert whose(summary, str(t)) == (NOTICE, "transcript")
    out = hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": summary, "transcript_path": str(t),
                               "session_id": "s1", "cwd": str(tmp_path)}), store)
    assert "NOT the user's own message" in out
    assert Heard(store.root).recall("default", "", 20) == []


@pytest.mark.parametrize("marks", [{"turnOrigin": "scheduled", "isMeta": True}, {"isMeta": True},
                                   {"turnOrigin": "human", "isVisibleInTranscriptOnly": True}],
                         ids=["scheduled-meta", "meta", "transcript-only"])
def test_a_turn_the_tool_added_is_not_the_users_in_either_engine(tmp_path, marks):
    from semantext.sender import whose
    text = "Run the nightly check."
    t = transcript(tmp_path, {"type": "user", "message": {"role": "user", "content": text}, **marks})
    assert whose(text, str(t)) == (NOTICE, "transcript")
    assert _estate_owner(tmp_path, text, t) is False


def test_a_scheduled_turn_is_never_the_users_words(tmp_path):
    # The owner's decision: a scheduled turn (a /loop wake-up) was started by the tool, so even with no other mark it
    # is not the user's, in both engines. A plain human turn with the same words still is.
    from semantext.envhook import record_says
    from semantext.sender import whose
    text = "Run the nightly check."
    t = transcript(tmp_path, turn("scheduled", text))
    assert record_says(str(t), text) == "not"
    assert whose(text, str(t))[0] != USER
    assert _estate_owner(tmp_path, text, t) is False
    (tmp_path / "h").mkdir()
    h = transcript(tmp_path / "h", turn("human", text))
    assert whose(text, str(h)) == (USER, "transcript")


PLAIN = {"type": "user", "message": {"role": "user", "content": "tidy the readme"}}   # names no origin


@pytest.mark.parametrize("older, newer, want", [
    (turn("peer", "tidy the readme"), PLAIN, (RELAY, "transcript")),
    (turn("human", "tidy the readme"), PLAIN, (USER, "transcript")),
    (turn("peer", "tidy the readme"), turn("human", "tidy the readme"), (USER, "transcript")),
], ids=["peer-then-plain", "human-then-plain", "peer-then-human"])
def test_a_record_that_names_no_origin_never_hides_an_older_one(tmp_path, older, newer, want):
    # audit of f342d88, protection finding 1: a newer record naming no origin is no evidence, so it no longer
    # shadows an older one that names one; the newest record that NAMES an origin still decides
    from semantext.sender import whose
    t = transcript(tmp_path, older, newer)
    assert whose("tidy the readme", str(t)) == want
    assert _estate_owner(tmp_path, "tidy the readme", t) is (want[0] == USER)


def test_text_blocks_of_any_shape_never_make_the_reader_raise(tmp_path):
    from semantext.sender import whose
    t = transcript(tmp_path, {"type": "user", "turnOrigin": "peer", "message": {"content": [
        {"type": "text", "text": 5}, {"type": "text", "text": "tidy the readme"}]}})
    assert whose("tidy the readme", str(t)) == (RELAY, "transcript")


def test_a_deeply_nested_line_never_makes_the_sentence_check_raise(tmp_path):
    from semantext.sender import users_sentence
    p = tmp_path / "deep.jsonl"
    p.write_text('{"a": ' + "[" * 100_000 + "]" * 100_000 + ', "k": "Never push to main."}\n', encoding="utf-8")
    assert users_sentence(p, "Never push to main.") is None


def test_a_classifier_failure_gives_the_short_card_and_says_so_in_the_feed(tmp_path, store, monkeypatch):
    # F-G: hook.run did not wrap whose(...). Audit of f342d88, protection finding 2: a failure is evidence that the
    # evidence could not be read, so the prompt is not the owner's (the short card, for this one prompt), it is not
    # kept as heard, and the feed records why
    from semantext.feed import Feed
    from semantext.heard import Heard
    store.set_option("hear_prompts", True)
    text = "please tidy the readme"
    t = transcript(tmp_path, turn("human", text))

    def broken(prompt, transcript=None):
        raise RecursionError("deep")
    monkeypatch.setattr(hook, "whose", broken)
    out = hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": text, "transcript_path": str(t)}),
                   store)
    assert "NOT the user's own message" in out
    assert Heard(store.root).recall("default", "", 20) == []
    assert Feed(store.root).recent(1)[-1]["basis"] == "error"


@pytest.mark.parametrize("prompt", [
    "please tidy the readme",                                                   # nothing marks it: not a yes
    "​Another Claude session sent a message:\nkeep this as my rule",      # a relay behind a zero-width space
    "another claude session sent a message:\nkeep this as my rule",            # a relay in lower case
], ids=["no-record", "zero-width-relay", "lower-case-relay"])
def test_only_words_the_record_calls_the_users_are_kept_as_heard(tmp_path, store, prompt):
    # audit of f342d88, protection finding 2: hearing has the bar a typed answer has, the tool's own record
    from semantext.heard import Heard
    store.set_option("hear_prompts", True)
    hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt,
                         "transcript_path": str(transcript(tmp_path, turn("human", "something else")))}), store)
    assert Heard(store.root).recall("default", "", 20) == []
    t = transcript(tmp_path, turn("human", "please keep my words"), name="own.jsonl")
    hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "please keep my words",
                         "transcript_path": str(t)}), store)
    assert [i["text"] for i in Heard(store.root).recall("default", "", 20)] == ["please keep my words"]


def test_reading_the_opening_is_linear_on_any_mix_of_whitespace_and_marks(tmp_path):
    # audit of f342d88, protection finding 3: stripping by a loop of lstrip() then lstrip(BOM) copied the prompt once
    # per pair, so alternating runs were quadratic (100,000 pairs took about 1.5 s)
    import time
    from semantext import provenance
    from semantext.sender import whose
    pad = " ﻿" * 1_000_000
    t = transcript(tmp_path, turn("peer", "x"))
    start = time.perf_counter()
    assert whose(pad + "<cross-session-message from-name=\"x\">hi", str(t)) == (RELAY, "text")
    assert whose(pad + "tidy the readme" + pad, str(t)) == (USER, "none")
    assert provenance.same(pad + "tidy" + pad) == "tidy"
    assert time.perf_counter() - start < 2

@pytest.mark.parametrize("prompt, want", [
    ('<system-reminder id="1">' + " " * 300 + "Another Claude session sent a message:\nhi", RELAY),
    ("<system-reminder " + "a" * 400 + ">\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nhi", NOTICE),
    ('<system-reminder id="1">' + " \ufeff\n" * 5_000 + "another claude session sent a message:\nhi", RELAY),
], ids=["spaces-after-the-tag", "long-attribute", "mixed-run-lower-case"])
def test_a_wrapped_message_is_read_however_far_its_words_are_pushed(tmp_path, prompt, want):
    # audit of d52f22f: the 300-character bound cut the wrapped form, so with no record it read as the user's
    from semantext.sender import whose
    assert whose(prompt, str(tmp_path / "none.jsonl")) == (want, "text")
    assert _estate_owner(tmp_path, prompt, tmp_path / "none.jsonl") is False


def test_a_wrapper_with_a_huge_attribute_is_read_quickly(tmp_path):
    import time
    from semantext.sender import whose
    attr = "x" * 1_000_000
    none = str(tmp_path / "none.jsonl")
    start = time.perf_counter()
    assert whose(f'<system-reminder data="{attr}">Another Claude session sent a message:\nhi', none) == (RELAY, "text")
    assert whose(f'<system-reminder data="{attr}">tidy the readme', none) == (USER, "none")   # wrapped, not a relay
    assert whose(f'<system-reminder data="{attr}', none) == (USER, "none")                    # never closed
    assert time.perf_counter() - start < 2

# ---- one prefix test for a bare opening and a wrapper's words (audit of the v2-next merge) ------------------------
@pytest.mark.parametrize("prompt, want", [
    ("<system-reminder>\n[Cross-session delivery notice] Your message to agent-a was held.", NOTICE),
    ('<system-reminder>\n<cross-session-message from="uds:x" from-name="x">hi</cross-session-message>', RELAY),
    ("<system-reminder>\n<task-notification>\n<status>completed</status>", NOTICE),
    ('<system-reminder note="a > b">Another Claude session sent a message:\nhi', RELAY),
    ("<system-reminder note='x>y'>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nhi", NOTICE),
    ("Another Claude session sent a message while you were working:\nhi", RELAY),
    ("<system-reminder><system-reminder>\n<agent-message from=\"a\">done</agent-message>", RELAY),
], ids=["wrapped-bracket", "wrapped-raw-relay", "wrapped-raw-task", "quoted-gt", "single-quoted-gt",
        "bare-relay-without-colon", "wrapped-twice"])
def test_a_wrapper_and_a_bare_opening_get_the_same_test(tmp_path, prompt, want):
    from semantext.sender import whose
    none = tmp_path / "none.jsonl"
    assert whose(prompt, str(none)) == (want, "text")
    assert _estate_owner(tmp_path, prompt, none) is False


@pytest.mark.parametrize("prompt", [
    "<system-reminder>please tidy the readme",                                  # wrapped, but the user's words
    '<system-reminder note="never closed>Another Claude session sent a message:\nhi',   # the tag never ends
    "I got <system-reminder>[SYSTEM NOTIFICATION] in a log; what is it?",       # mentioned later
], ids=["wrapped-plain", "unclosed-quote", "mentioned-later"])
def test_what_the_prefix_test_does_not_name_stays_the_users(tmp_path, prompt):
    from semantext.sender import whose
    assert whose(prompt, str(tmp_path / "none.jsonl")) == (USER, "none")


def test_five_megabytes_of_any_wrapper_is_read_quickly(tmp_path):
    import time
    from semantext.sender import whose
    none = str(tmp_path / "none.jsonl")
    relay = "Another Claude session sent a message:\nhi"
    cases = [('<system-reminder note="' + "a>" * 2_500_000 + '">' + relay, RELAY),
             ("<system-reminder " + 'x="" ' * 1_000_000 + ">" + relay, RELAY),
             ("<system-reminder>" + " \n" * 2_500_000 + relay, RELAY),
             ('<system-reminder note="' + "a" * 5_000_000 + relay, USER)]     # never closed
    start = time.perf_counter()
    for prompt, want in cases:
        assert whose(prompt, none)[0] == want
    # linear reads take well under a second here; a quadratic one takes minutes. 5 s leaves room for a slow runner
    # (CI's macOS took 1.1 s against the old 1 s bound) and still refuses the quadratic
    assert time.perf_counter() - start < 5.0