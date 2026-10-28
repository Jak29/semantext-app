"""The parts of the Gates reader on their own: the verdict as a total, pure function over its whole input space, the
wording as the only place the gate words are written and free of claims a static read cannot make, and the shim that
keeps the old single module's names working. Each check has a must-pass arm and a must-refuse arm.
"""
from __future__ import annotations

import ast
import builtins
import itertools
import json
import os
import re
import types
from pathlib import Path

import pytest

from semantext.sources import gates
from semantext.sources.gates import config, discover, hooks, values, verdict, wording
from semantext.sources.gates.verdict import ARMED, INERT, ORDER, UNCOVERED, VACUOUS, Facts, states

PARTS = Path(gates.__file__).parent


# ---------------------------------------------------------------- the verdict, over every input
def oracle(hooks_path_set, own_folder, covered, entries):
    """The states as the docstring states them, written apart from the code: a set, then put in the checker's order."""
    if not covered or (not hooks_path_set and own_folder is None):    # VD1 (round 2): no acts is no verdict
        return None
    if not hooks_path_set and own_folder is False:
        return (INERT,)
    found = set()
    if False in covered:
        found.add(UNCOVERED)
    if entries == 0 and True in covered:
        found.add(VACUOUS)
    if False not in covered and VACUOUS not in found:
        found.add(ARMED)
    return tuple(s for s in ORDER if s in found)


EVERY_COVER = [c for n in range(0, 6) for c in itertools.product((False, True), repeat=n)]
EVERY_FACT = list(itertools.product((False, True), (False, True, None), EVERY_COVER, (0, 1, 2, 7)))


def test_the_verdict_agrees_with_its_rules_on_every_fact():
    assert len(EVERY_FACT) == 2 * 3 * 63 * 4
    for fact in EVERY_FACT:
        assert states(Facts(*fact)) == oracle(*fact), fact


def test_the_states_keep_their_shape_on_every_fact():
    for fact in EVERY_FACT:
        got = states(Facts(*fact))
        if got is None:
            continue
        assert got and len(set(got)) == len(got) and list(got) == [s for s in ORDER if s in got]
        assert (INERT not in got and ARMED not in got) or len(got) == 1          # INERT and ARMED are always alone
        if VACUOUS in got:
            assert True in fact[2]                    # never VACUOUS with nothing covered: nothing runs to check nothing


def test_the_four_acts_as_the_reader_asks_them():
    """Must-pass and must-refuse on the cases the reader meets: four acts, a count of entries."""
    four = (True,) * 4
    assert states(Facts(True, None, four, 1)) == (ARMED,)
    assert states(Facts(True, None, four, 0)) == (VACUOUS,)
    assert states(Facts(True, None, (True, False, True, True), 0)) == (UNCOVERED, VACUOUS)
    assert states(Facts(True, None, (False,) * 4, 0)) == (UNCOVERED,)          # not VACUOUS: nothing is covered
    assert states(Facts(False, False, (False,) * 4, 3)) == (INERT,)
    assert states(Facts(False, True, (False,) * 4, 3)) == (UNCOVERED,)         # git's own folder holds a file: not off
    assert states(Facts(False, True, four, 1)) != (INERT,)


MALFORMED = [
    None, (), "ARMED", {"hooks_path_set": True}, [True, None, (True,), 1], (True, None, (True,)),
    (True, None, (True,), 1, 0), (1, None, (True,), 1), ("yes", None, (True,), 1), (True, 0, (True,), 1),
    (True, None, [True], 1), (True, None, (1,), 1), (True, None, (True, "no"), 1), (True, None, None, 1),
    (True, None, (True,), -1), (True, None, (True,), True), (True, None, (True,), 1.0), (True, None, (True,), "1"),
    (False, None, (True,), 1),                         # git's own folder decides the answer and was not looked at
]


@pytest.mark.parametrize("facts", MALFORMED, ids=[repr(m) for m in MALFORMED])
def test_facts_outside_the_domain_give_no_states_and_never_a_guess(facts):
    assert states(facts) is None


def test_a_plain_tuple_of_good_facts_is_read_as_facts():
    assert states((True, None, (True,) * 4, 1)) == (ARMED,)


def test_the_verdict_opens_nothing(monkeypatch):
    def forbidden(*a, **k):
        raise AssertionError("the verdict touched the file system")
    for owner, name in ((builtins, "open"), (os, "scandir"), (os, "stat"), (os, "access"), (os, "listdir")):
        monkeypatch.setattr(owner, name, forbidden)
    first = [states(Facts(*f)) for f in EVERY_FACT]
    assert first == [states(Facts(*f)) for f in EVERY_FACT]                  # the same facts, the same states


# ---------------------------------------------------------------- the wording
FORBIDDEN = re.compile(r"\b(gated|protected|protects|enforced|enforces|working|works|secure|secured|guarded|safe)\b", re.I)


def over_claims(text: str) -> list:
    """What a static read must never say: a word claiming a gate works, or "armed" without "(read)"."""
    found = FORBIDDEN.findall(text)
    if re.search(r"\barmed\b", text, re.I) and "(read)" not in text:
        found.append("armed")
    return found


def test_the_scanner_finds_an_over_claim():
    """Must-refuse: the scanner is not a check that always passes."""
    assert over_claims("every worktree is gated") == ["gated"]
    assert over_claims("the gate is enforced") == ["enforced"]
    assert over_claims("armed") == ["armed"] and over_claims("armed (read)") == []
    assert over_claims("a hook for each act, identity named") == []


def every_static_string() -> list:
    out = [wording.words(v, wording.STATIC) for v in ORDER]
    out += [wording.READ, wording.READ_NOTE, wording.ARMED_WORDS, wording.NOT_TESTED, wording.STRANDED,
            wording.EXEC_POSIX, wording.EXEC_WINDOWS, wording.BARE_NOTE, wording.bare_note(), wording.bare_note("x"),
            wording.main_note("C/x"), wording.executable(True), wording.executable(False),
            wording.via_note("pre-applypatch", "applypatch-msg")]
    out += [wording.missing_note(g, locked) for g in (None, "folder", "gitfile", "blank", "empty") for locked in (0, 1)]
    out += list(wording.WORDS.values())
    return out


def test_no_gate_string_the_reader_can_write_over_claims():
    for text in every_static_string():
        assert over_claims(text) == [], text


def test_the_words_on_the_pinned_answer_do_not_over_claim():
    """The record's words, notes and stranded words over the whole pinned corpus. The per-act "state" value is a token
    in the record ("gated" or "open"), not words for the page, and is left out here."""
    pinned = json.loads(Path(__file__).with_name("gates_pin_expected.json").read_text(encoding="utf-8"))
    said = []
    for side in pinned.values():
        said.append(side["read_note"])
        for w in (w for r in side["repos"] for w in r["worktrees"]):
            said += [*w["words"], w["executable"], w["note"] or "", *(e["note"] or "" for e in w["events"])]
            for v in w["verdicts"]:
                said += [v["words"], *(s["words"] for s in v.get("stranded", []))]
    assert len(said) > 50
    for text in said:
        assert over_claims(text) == [], text


def test_every_state_the_verdict_can_give_has_words_and_other_evidence_has_none():
    given = {s for f in EVERY_FACT for s in (states(Facts(*f)) or ())}
    assert given == set(ORDER) == set(wording.WORDS)
    with pytest.raises(ValueError):
        wording.words(ARMED, "record")        # a record that a hook refused something has no words yet
    with pytest.raises(ValueError):
        wording.words("GUARDED", wording.STATIC)


def string_constants(path: Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_the_gate_words_are_written_only_in_wording():
    # the phrases only: a one-word state ("off", "open") is also a key or a token elsewhere, and says nothing on its own
    words = {w for w in (wording.ARMED_WORDS, wording.NOT_TESTED, wording.READ_NOTE, wording.EXEC_POSIX,
                         wording.EXEC_WINDOWS, wording.BARE_NOTE, *wording.WORDS.values()) if " " in w}
    assert len(words) == 7
    assert words <= string_constants(PARTS / "wording.py")                # must-pass: they are there
    for part in ("__init__.py", "values.py", "config.py", "discover.py", "hooks.py", "verdict.py"):
        assert not words & string_constants(PARTS / part), part


# ---------------------------------------------------------------- the shim
SHIMMED = ("this_machine", "Reader", "git_number", "RULES", "user_home", "value_problem", "include_condition",
           "parse_bool", "git_absolute", "find_worktrees", "global_files", "PROTECTED", "WINDOWS_ONLY", "parse_config",
           "normalised", "World", "load", "read_at", "WINDOWS", "MAX_FILE", "MAX_VISITS", "MAX_WORKTREES", "MAX_GITFILE",
           "MAX_NAMES", "EXEC_POSIX", "ARMED_WORDS", "NOT_TESTED", "gone_note")


@pytest.mark.parametrize("name", SHIMMED)
def test_the_old_names_are_still_there(name):
    assert hasattr(gates, name)


def test_a_patch_on_the_package_reaches_every_part_that_holds_the_name(monkeypatch):
    before = values.WINDOWS
    monkeypatch.setattr(gates, "WINDOWS", not before)
    assert values.WINDOWS is config.WINDOWS is hooks.WINDOWS is gates.WINDOWS is (not before)
    monkeypatch.undo()
    assert values.WINDOWS is config.WINDOWS is hooks.WINDOWS is before


def test_without_the_shim_a_patch_on_the_package_would_not_reach_the_parts():
    """Must-refuse: an ordinary module's setattr leaves the parts as they were, which is why the shim is there."""
    before = values.WINDOWS
    types.ModuleType.__setattr__(gates, "MAX_NAMES", 1)
    try:
        assert hooks.MAX_NAMES == 5_000
    finally:
        types.ModuleType.__setattr__(gates, "MAX_NAMES", 5_000)
    assert values.WINDOWS is before and discover.MAX_WORKTREES == 500
