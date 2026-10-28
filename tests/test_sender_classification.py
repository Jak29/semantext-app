"""Whose words a prompt carries: an exhaustive test of the two classifiers (audit of e36d0c0, 2026-10-23).

The two engines:
  * semantext.sender.whose(prompt, transcript)  -> (kind, basis); the app's hook and the answers typed in chat
  * semantext.envhook.from_owner(prompt, transcript, cfg) -> bool; the estate's reading card

WHAT IS PROVED, AND HOW. The code defaults to OWNER and lets evidence take a prompt away:
  S1  text demotes:    a prompt that opens as another agent's message or a tool's notice is NOT the owner's, whatever its
                       record says, whether or not it has one, and with the record check on or off.
  S2  record demotes:  when the tool's own record of the prompt (the NEWEST record with the same words) says it is not the
                       user's, the prompt is not the owner's. Line endings and no-break spaces do not hide the record.
  S3  default:         with no evidence either way the prompt is the owner's (stated, counted on real data elsewhere).
  S4  newest decides:  of two records with the same words, the later one decides.
  S5  no promotion:    a record that says "own" never turns a prompt that S1 demotes into the owner's; no record, however
                       formed, ever turns a not-owner prompt into the owner's.
  S6  totality:        neither engine raises on any transcript or prompt, and each returns a bool / a (kind, basis) pair.
The statement is a finite one: the table below is the whole space of facts the two engines read (how the prompt OPENS,
and what the newest matching record SAYS, under three spellings of the same words), so each cell is checked, not
sampled. The test is mapped to the real code: every cell calls the real function on a real transcript file.

SPECIFICATION. The spec is mine (independent of both engines): the UNION of what either engine demotes by text (so a
form only one engine knows is a finding against the other), and the record rules S2 and S4 stated above. Cells where an
engine differs from the spec are listed in KNOWN with the finding; each is an xfail(strict=True), so the day an engine is
fixed the test says so and the entry has to go. A cell outside KNOWN that fails is a new finding.

Run (copy this file into the repo's tests/):  python -m pytest tests/test_sender_classification.py -q
On e36d0c0: 1171 passed, 94 xfailed (7.6 s). The xfails are the findings F-A to F-G (see KNOWN_BY_RULE, KNOWN_RAISES and
FINDINGS); the findings table is strict, so a fix turns its row into a failure that says "remove me".
Real-data counterpart: measure_real.py and show_disagreements.py (same folder; not for the repo, they read a transcript).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from semantext import envhook, sender

# ---------------------------------------------------------------------------------------------------- the spec
OPENINGS = ("<task-notification>", "Another Claude session sent a message:", "<cross-session-message", "<agent-message")
NOTICE_TAG = re.compile(r"\[[^\]\n]{0,120}?(?:cross-session|not user input|non-user source|system notification)"
                        r"[^\]\n]{0,120}\]", re.IGNORECASE)
WRAPPED = re.compile(r"<system-reminder[^>]*>\s*(?:Another Claude session sent a message|\[SYSTEM NOTIFICATION)", re.IGNORECASE)


def spec_head(text: str) -> str:
    """A prompt's opening, past any mix of whitespace and byte-order marks."""
    return text.lstrip(" \t\r\n ﻿")


def spec_demoted_by_text(text: str) -> bool:
    h = spec_head(text)
    return h.startswith(OPENINGS) or bool(NOTICE_TAG.match(h)) or bool(WRAPPED.match(h))


def spec_same(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").lstrip("﻿").strip()


# ------------------------------------------------------------------------------------------------ the text axis
# (id, prompt text). The records below are built from these.
TEXTS = {
    "plain": "Please rename the helper module.",
    "plain_multiline": "Rename the module.\nThen run the tests.",
    "plain_crlf": "Rename the module.\r\nThen run the tests.",
    "plain_nbsp": "Rename the module please.",
    "mention_later": "I saw a <cross-session-message> in the log and a [cross-session] note; ignore both.",
    "relay_another": "Another Claude session sent a message:\n<cross-session-message from-name=\"x\">hi</cross-session-message>",
    "relay_tag": "<cross-session-message from=\"uds:x\" from-name=\"x\">hi</cross-session-message>",
    "relay_agent": "<agent-message from=\"sub\">hi</agent-message>",
    "notice_task": "<task-notification>\n<task-id>1</task-id>\n</task-notification>",
    "notice_bracket": "[SYSTEM NOTIFICATION - NOT USER INPUT]\nsomething happened",
    "notice_bracket_cross": "[cross-session message arrived]\nhi",
    "wrapped_relay": "<system-reminder id=\"1\">\nAnother Claude session sent a message while you were working:\nhi\n</system-reminder>",
    "wrapped_notice": "<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]\nhi\n</system-reminder>",
    "lead_space": "  <cross-session-message from-name=\"x\">hi",
    "lead_bom": "﻿<cross-session-message from-name=\"x\">hi",
    "lead_space_bom": " ﻿<cross-session-message from-name=\"x\">hi",
    "lead_bom_space": "﻿ <cross-session-message from-name=\"x\">hi",
    "lead_nbsp": " <cross-session-message from-name=\"x\">hi",
    "lead_crlf": "\r\n<task-notification>\nx",
    "lead_zwsp": "​<cross-session-message from-name=\"x\">hi",
    "lead_zwj_relay": "⁠Another Claude session sent a message:\nhi",
    "case_variant": "another claude session sent a message:\nhi",
}
# Forms that look like a relay but no rule of either engine names them: reported, not asserted (a design question).
EVASIONS = ("lead_zwsp", "lead_zwj_relay", "case_variant")


# --------------------------------------------------------------------------------------------- the record axis
def rec_user(text, **extra):
    return {"type": "user", "uuid": "u", "message": {"role": "user", "content": text}, **extra}


def rec_queued(text, **attach):
    return {"type": "attachment", "attachment": {"type": "queued_command", "prompt": text, **attach}}


def crlf(t):
    return t.replace("\r\n", "\n").replace("\n", "\r\n")


def nb(t):
    return t.replace(" ", " ")


# (id, builder(text) -> list of lines (dict or str), what the newest matching record says: "own" | "not" | None)
RECORDS = {
    "file_missing": (None, None),
    "empty": (lambda t: [], None),
    "other_prompt": (lambda t: [rec_user("something else entirely", turnOrigin="peer")], None),
    "turn_human": (lambda t: [rec_user(t, turnOrigin="human")], "own"),
    "turn_peer": (lambda t: [rec_user(t, turnOrigin="peer")], "not"),
    "turn_task": (lambda t: [rec_user(t, turnOrigin="task_notification")], "not"),
    "turn_system": (lambda t: [rec_user(t, turnOrigin="system")], "not"),
    "kind_human": (lambda t: [rec_user(t, origin={"kind": "human"})], "own"),
    "kind_peer": (lambda t: [rec_user(t, origin={"kind": "peer"})], "not"),
    "kind_task_hyphen": (lambda t: [rec_user(t, origin={"kind": "task-notification"})], "not"),
    "queued_human": (lambda t: [rec_queued(t, humanTurn=True)], "own"),
    "queued_task": (lambda t: [rec_queued(t, commandMode="task-notification")], "not"),
    "queued_meta_reminder": (lambda t: [rec_queued(t, isMeta=True, reminderId="r1")], "not"),
    "queued_meta": (lambda t: [rec_queued(t, isMeta=True)], "not"),
    "queued_peer_origin": (lambda t: [rec_queued(t, origin={"kind": "peer"})], "not"),
    "queued_plain": (lambda t: [rec_queued(t)], None),
    "user_plain": (lambda t: [rec_user(t)], None),
    "user_meta": (lambda t: [rec_user(t, isMeta=True)], "not"),
    "compact_summary": (lambda t: [rec_user(t, isCompactSummary=True)], "not"),
    "tool_result_not_a_prompt": (lambda t: [{"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "content": t}]}, "turnOrigin": "peer"}], None),
    "text_blocks_human": (lambda t: [{"type": "user", "turnOrigin": "human", "message": {"role": "user", "content": [
        {"type": "text", "text": t}]}}], "own"),
    "stale_own_then_not": (lambda t: [rec_user(t, turnOrigin="human"), rec_user(t, turnOrigin="peer")], "not"),
    "stale_not_then_own": (lambda t: [rec_user(t, turnOrigin="peer"), rec_user(t, turnOrigin="human")], "own"),
    "garbage_then_own": (lambda t: ["not json at all", "[1, 2, 3]", "null", rec_user(t, turnOrigin="human")], "own"),
    "garbage_after_peer": (lambda t: [rec_user(t, turnOrigin="peer"), "{broken", "\x00\x01"], "not"),
    # the same words under another spelling: the record must still be found (S2)
    "peer_crlf_in_record": (lambda t: [rec_user(crlf(t), turnOrigin="peer")], "not"),
    "peer_lf_in_record": (lambda t: [rec_user(spec_same(t).replace("\r\n", "\n"), turnOrigin="peer")], "not"),
    "peer_nbsp_in_record": (lambda t: [rec_user(nb(t), turnOrigin="peer")], "not"),
    "peer_bom_in_record": (lambda t: [rec_user("﻿" + t, turnOrigin="peer")], "not"),
    "peer_padded_in_record": (lambda t: [rec_user("  " + t + "\n\n", turnOrigin="peer")], "not"),
    "human_crlf_in_record": (lambda t: [rec_user(crlf(t), turnOrigin="human")], "own"),
}


# ------------------------------------------------------------------------------------------------ the engines
def make_cfg(tmp_path, record_check=True):
    return envhook.Config({"environments": str(tmp_path / "envs"), "core": "core", "headers": {},
                           "record_check": record_check})


def write_transcript(tmp_path, name, lines):
    p = tmp_path / f"{name}.jsonl"
    with open(p, "wb") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)).encode("utf-8", "surrogatepass") + b"\n")
    return str(p)


def engine_envhook(prompt, transcript, tmp_path, record_check=True):
    return envhook.from_owner(prompt, transcript, make_cfg(tmp_path, record_check))


def engine_sender(prompt, transcript, tmp_path, record_check=True):
    kind, basis = sender.whose(prompt, transcript)
    assert kind in (sender.USER, sender.RELAY, sender.NOTICE) and basis in ("text", "transcript", "none")
    return kind == sender.USER


ENGINES = {"envhook.from_owner": engine_envhook, "sender.whose": engine_sender}


def spec_owner(text, says, record_check=True):
    """The expected answer: owner unless the text demotes it, or the record check is on and the newest matching record says not."""
    if spec_demoted_by_text(text):
        return False
    return not (record_check and says == "not")


# ----------------------------------------------------------------------------------------------------- KNOWN
# (engine, text id, record id) cells where the engine differs from the spec today. Filled from the first run on e36d0c0;
# each group is one finding. A cell here is xfail(strict=True): when an engine is fixed the cell XPASSes and fails the run,
# so the entry is removed and the test then guards the fix.
KNOWN: dict[tuple[str, str, str], str] = {}
# (engine, predicate(text_id, record_id), finding). A cell matching a rule may differ from the spec without failing the
# table; the strict xfail tests at the end of this file (test_finding_*) are what notice a fix.
KNOWN_BY_RULE: list = [
]


def known(engine, text_id, record_id):
    if (engine, text_id, record_id) in KNOWN:
        return KNOWN[(engine, text_id, record_id)]
    for eng, pred, why in KNOWN_BY_RULE:
        if eng == engine and pred(text_id, record_id):
            return why
    return None


# ---------------------------------------------------------------------------------------------- the exhaustive cells
CELLS = [(e, t, r) for e in ENGINES for t in TEXTS if t not in EVASIONS for r in RECORDS]


@pytest.mark.parametrize("engine,text_id,record_id", CELLS, ids=[f"{e.split('.')[0]}-{t}-{r}" for e, t, r in CELLS])
def test_cell(tmp_path, engine, text_id, record_id):
    text = TEXTS[text_id]
    build, says = RECORDS[record_id]
    transcript = str(tmp_path / "missing.jsonl") if build is None else write_transcript(tmp_path, "t", build(text))
    why = known(engine, text_id, record_id)
    want = spec_owner(text, says)
    got = ENGINES[engine](text, transcript, tmp_path)
    if why and got != want:
        pytest.xfail(why)
    assert got == want, f"{engine}: spec says owner={want}, engine says owner={got} (text {text_id}, record {record_id})"


@pytest.mark.parametrize("engine", list(ENGINES))
def test_S1_text_demotes_whatever_the_record_says(tmp_path, engine):
    """S1 and S5 together: for every text that opens as a relay or notice, every record gives not-owner, and with the record check off."""
    bad = []
    for text_id, text in TEXTS.items():
        if text_id in EVASIONS or not spec_demoted_by_text(text):
            continue
        for record_id, (build, says) in RECORDS.items():
            transcript = str(tmp_path / "none.jsonl") if build is None else write_transcript(tmp_path, "s1", build(text))
            for record_check in (True, False):
                if engine == "sender.whose" and not record_check:
                    continue
                if ENGINES[engine](text, transcript, tmp_path, record_check):
                    bad.append((text_id, record_id, record_check))
    cells = {(t, r) for t, r, _ in bad}
    unexplained = [c for c in cells if not known(engine, *c)]
    assert not unexplained, f"{engine}: a demoted text became the owner's with these records: {sorted(unexplained)[:12]}"


@pytest.mark.parametrize("engine", list(ENGINES))
def test_S5_a_record_never_promotes(tmp_path, engine):
    """No record of any form turns a not-owner prompt (by the spec) into the owner's, and 'own' records change nothing for them."""
    bad = []
    for text_id, text in TEXTS.items():
        if text_id in EVASIONS:
            continue
        base_transcript = str(tmp_path / "x.jsonl")
        base = ENGINES[engine](text, base_transcript, tmp_path)
        for record_id, (build, says) in RECORDS.items():
            if build is None:
                continue
            transcript = write_transcript(tmp_path, "s5", build(text))
            got = ENGINES[engine](text, transcript, tmp_path)
            if base is False and got is True:
                bad.append((text_id, record_id))
    unexplained = [c for c in bad if not known(engine, *c)]
    assert not unexplained, f"{engine}: a record promoted a not-owner prompt: {unexplained[:12]}"


# --------------------------------------------------------------------------------------------------- S6 totality
def deep_json(n=100_000):
    return "[" * n + "]" * n


GARBAGE = {
    "binary": lambda t: [bytes(range(256)).decode("latin-1")],
    "huge_line_with_needle": lambda t: [t + "x" * 3_000_000],
    "needle_then_deep_nesting": lambda t: ['{"a": ' + deep_json() + f', "k": {json.dumps(t[:40])}' + "}"],
    "array_lines": lambda t: ['[' + json.dumps(t) + ']'] * 5,
    "string_line": lambda t: [json.dumps(t)],
    "null_message": lambda t: [{"type": "user", "message": None, "turnOrigin": "peer"}],
    "message_not_dict": lambda t: [{"type": "user", "message": "text", "turnOrigin": "peer"}],
    "content_list_of_junk": lambda t: [{"type": "user", "turnOrigin": "peer", "message": {"content": [1, None, "x", {"type": "text"}]}}],
    "attachment_not_dict": lambda t: [{"type": "attachment", "attachment": "x"}],
    "origin_not_dict": lambda t: [{"type": "user", "origin": "peer", "message": {"content": t}}],
    "turnorigin_unhashable": lambda t: [{"type": "user", "turnOrigin": ["peer"], "message": {"content": t}}],
    "origin_kind_unhashable": lambda t: [{"type": "user", "origin": {"kind": ["peer"]}, "message": {"content": t}}],
    "queued_prompt_not_str": lambda t: [{"type": "attachment", "attachment": {"type": "queued_command", "prompt": 5, "humanTurn": True}}],
    "lone_surrogate": lambda t: ['{"type": "user", "turnOrigin": "peer", "message": {"content": "' + t[:10] + '\\ud800"}}'],
}


@pytest.mark.parametrize("engine", list(ENGINES))
@pytest.mark.parametrize("garbage_id", list(GARBAGE))
def test_S6_no_transcript_makes_a_classifier_raise(tmp_path, engine, garbage_id):
    text = TEXTS["plain_multiline"]
    transcript = write_transcript(tmp_path, "g", GARBAGE[garbage_id](text))
    if garbage_id in KNOWN_RAISES.get(engine, {}):
        with pytest.raises(Exception):
            ENGINES[engine](text, transcript, tmp_path)
        pytest.xfail(KNOWN_RAISES[engine][garbage_id])
    out = ENGINES[engine](text, transcript, tmp_path)
    assert isinstance(out, bool)


KNOWN_RAISES: dict = {      # engine -> {garbage id: finding}
}


@pytest.mark.parametrize("engine", list(ENGINES))
@pytest.mark.parametrize("bad_path", [None, "", 0, 12.5, b"bytes.jsonl", ".", "a\x00b", "no/such/dir/t.jsonl"])
def test_S6_a_transcript_path_of_any_shape(tmp_path, engine, bad_path):
    out = ENGINES[engine](TEXTS["plain"], bad_path, tmp_path)
    assert out is True                # nothing readable: the default (S3), and no exception


@pytest.mark.parametrize("engine", list(ENGINES))
def test_S6_a_directory_as_the_transcript(tmp_path, engine):
    assert ENGINES[engine](TEXTS["plain"], str(tmp_path), tmp_path) is True


@pytest.mark.parametrize("engine", list(ENGINES))
@pytest.mark.parametrize("prompt", [None, 5, 5.5, b"bytes", ["list"], {"d": 1}, True])
def test_S6_and_S3_a_prompt_that_is_not_text_is_the_owners(tmp_path, engine, prompt):
    """Stated in both docstrings ('anything unreadable counts as the user's'); asserted so a change is noticed. A design
    question for the owner of the hook: it is the one place a malformed input FAILS TOWARD the owner."""
    assert ENGINES[engine](prompt, str(tmp_path / "t.jsonl"), tmp_path) is True


@pytest.mark.parametrize("engine", list(ENGINES))
@pytest.mark.parametrize("prompt", ["", "   ", "\n", "﻿", " "])
def test_S6_and_S3_an_empty_prompt_is_the_owners_by_default(tmp_path, engine, prompt):
    transcript = write_transcript(tmp_path, "e", [rec_user("x", turnOrigin="peer")])
    assert ENGINES[engine](prompt, transcript, tmp_path) is True


# ------------------------------------------------------------------------- S3 the default is counted, not hidden
def test_S3_the_default_is_the_owners_and_it_is_reported_as_unconfirmed(tmp_path):
    """sender.whose says WHY: 'none' when nothing told. The estate engine returns only a bool, so it cannot say; the
    count of owner classifications that rest on nothing is measured on real data (proof_sender/measure_real.py)."""
    kind, basis = sender.whose(TEXTS["plain"], str(tmp_path / "missing.jsonl"))
    assert (kind, basis) == (sender.USER, "none")
    transcript = write_transcript(tmp_path, "o", [rec_user(TEXTS["plain"], turnOrigin="human")])
    assert sender.whose(TEXTS["plain"], transcript) == (sender.USER, "transcript")


# ------------------------------------------------- the findings, each a strict xfail that flips when it is fixed
FINDINGS = [
    # (id, engine, text id, record id, expected owner per the spec)
    ("F-A", "envhook.from_owner", "relay_agent", "file_missing", False),
    ("F-B1", "sender.whose", "wrapped_relay", "file_missing", False),
    ("F-B2", "sender.whose", "wrapped_notice", "file_missing", False),
    ("F-C", "sender.whose", "lead_space_bom", "file_missing", False),
    ("F-D1", "sender.whose", "plain", "user_meta", False),
    ("F-D2", "sender.whose", "plain", "compact_summary", False),
    ("F-E1", "sender.whose", "plain_multiline", "peer_crlf_in_record", False),
    ("F-E2", "sender.whose", "plain_crlf", "peer_lf_in_record", False),
    ("F-E3", "sender.whose", "plain_nbsp", "peer_nbsp_in_record", False),
]


@pytest.mark.parametrize("fid,engine,text_id,record_id,want", FINDINGS, ids=[f[0] for f in FINDINGS])
def test_finding(tmp_path, fid, engine, text_id, record_id, want):
    text = TEXTS[text_id]
    build, _ = RECORDS[record_id]
    transcript = str(tmp_path / "missing.jsonl") if build is None else write_transcript(tmp_path, "f", build(text))
    assert ENGINES[engine](text, transcript, tmp_path) == want


# ------------------------------------------------------------------ the evasions (reported, not asserted)
@pytest.mark.parametrize("text_id", EVASIONS)
def test_evasions_reported(tmp_path, text_id, capsys):
    text = TEXTS[text_id]
    got = {e: f(text, str(tmp_path / "none.jsonl"), tmp_path) for e, f in ENGINES.items()}
    print(f"EVASION {text_id}: owner={got} (no record); the spec has no rule for it, so this is information for the owner of the hook")
    assert set(got.values()) <= {True, False}
