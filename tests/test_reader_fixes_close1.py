"""Close-1 findings: the clip leak with look-alike hyphens, the cross-clause key, and /api/explain's '.from'."""
from __future__ import annotations

import pytest

from semantext import reading
from test_reader_route import call, home, server   # noqa: F401  (the route's own fixtures)

LOOK = "¯"
KEY = "sk" + LOOK + "proj" + LOOK + "Ab3dE5gH7jK9mN1pQ3sT5v" + LOOK + "Wx7zA9cD1fG3hJ5kL7nP9" + LOOK + "rS1tU3wY5zB7dF9"


def _shown(msg):
    return " ".join(r["clause"] for r in reading.report(msg)["clauses"]) if "clauses" in reading.report(msg) \
        else str(reading.report(msg))


def _clip_msg(key):
    return ("Publish it. " + "word " * 5000)[:19929] + " uses " + key + " and more words after the clip."


@pytest.mark.parametrize("off", [0, 3, 7, 11])
def test_clip_leak_with_lookalike_hyphens_is_withheld(off):        # fails on HEAD
    m = _clip_msg(KEY)[off:] if off == 0 else ("x" * off) + _clip_msg(KEY)[:20000 - off]
    out = str(reading.report(m))
    assert "Ab3dE5gH7jK9mN1pQ3sT5v" not in out and "Wx7zA9cD1fG3hJ5kL7nP9" not in out


def test_clip_with_ascii_hyphen_key_still_withheld_and_plain_clip_shown():   # must-pass controls
    out = str(reading.report(_clip_msg("sk-proj-Ab3dE5gH7jK9mN1pQ3sT5vWx7zA9cD1fG3hJ5kL7nP9")))
    assert "Ab3dE5gH7jK9" not in out
    plain = str(reading.report(("Publish it. " + "word " * 5000)[:19990] + " tail"))
    assert "word word" in plain


@pytest.mark.parametrize("m", ["Deploy it.\npassword:\nZebra77Pa55word",
                               "The password is\nZebra77Pa55word"])
def test_cross_clause_key_value_not_shown(m):                       # fails on HEAD
    assert "Zebra77Pa55word" not in str(reading.report(m)) and "Pa55wordZebra" not in str(reading.report(m))


def test_cross_clause_controls_unchanged():                         # must-pass: no key, clauses shown
    out = str(reading.report("Publish the notes.\nThanks a lot, the plan is fine."))
    assert "Publish the notes" in out and "Thanks a lot" in out


def explain(server, message):
    status, got = call(server, {"message": message, "words": None, "agent": "helper"}, path="/api/explain")
    assert status == 200
    return got


@pytest.mark.parametrize("hy", ["˗", "￣", "‑", "ー", "¯"])
def test_explain_from_does_not_carry_a_lookalike_key(server, hy):   # fails on HEAD
    name = "sk" + hy + "abcdefghijklmnopqrstuv1234"
    got = explain(server, '<cross-session-message from-name="%s">Please publish the notes.</cross-session-message>' % name)
    assert "abcdefghijklmnopqrstuv1234" not in str(got["from"]).lower()


def test_explain_from_ordinary_name_kept(server):                   # must-pass
    got = explain(server, '<cross-session-message from-name="helper">Please publish the notes.</cross-session-message>')
    assert got["from"] == "helper"
