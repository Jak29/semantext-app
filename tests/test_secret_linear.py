"""The key-shape check takes time in proportion to its input (Koinos X1, 3 November 2026).

Its URL arm (user:password@ in a URL) had an unbounded scheme, so a long run of letters, digits, "+", "." or "-" was
tried from every start: quadratic, 80,000 letters in about 32 s, with the GIL held. A model's output reaches it (a
held call's input, a header value), so it could stall the proxy. Each arm has a must-pass and a must-refuse.
"""
from __future__ import annotations

import time

import pytest

from semantext.inbox import SECRET

RUNS = [("letters", "a"), ("letters and digits", "a1"), ("letters and dots", "a.")]


@pytest.mark.parametrize("name,unit", RUNS)
def test_a_long_run_is_checked_in_linear_time(name, unit):   # must-refuse the stall: 80,000 took ~32 s before
    text = (unit * 80_000)[:80_000]
    start = time.perf_counter()
    assert SECRET.search(text) is None
    assert time.perf_counter() - start < 1.0, name


@pytest.mark.parametrize("text", [
    "see https://jak:hunter22@host/x",
    "ftp+ssh://a:bcdef@c",
    "x" * 40 + "https://u:pass1@h",   # a scheme after a long run: the bound must not hide it (the silent direction)
    "a" * 80_000 + " https://u:pass1@h",
], ids=["plain", "scheme with +", "after a run of 40", "after 80,000 letters"])
def test_a_password_in_a_url_is_still_found(text):           # must-pass
    assert SECRET.search(text)


@pytest.mark.parametrize("text", ["https://host/path", "mailto:someone@example.com", "user@host:22"])
def test_a_url_without_a_password_is_not_a_key(text):        # must-refuse a false key
    assert not SECRET.search(text)


# Orithises's mutants of the URL arm (CHECK_bounded_secret.md): each pins one part of it.
def test_the_bound_is_32_characters_of_scheme():                # pins {0,31}: a mutant of 3, or an off-by-one, fails
    assert SECRET.search("a" + "1" * 31 + "://u:pass1@h")
    assert not SECRET.search("a" + "1" * 32 + "://u:pass1@h")    # the stated limit: no letter in the last 32


@pytest.mark.parametrize("text", ["https://user:@host", "http://host:8080/a/b@c"], ids=["empty password", "slash in path"])
def test_a_url_that_only_looks_like_one_is_not_a_key(text):     # must-refuse: a slash in the password would catch prose
    assert not SECRET.search(text)


@pytest.mark.parametrize("text", ["SEE HTTPS://JAK:HUNTER22@HOST", "PASSWORD IS hunter22"], ids=["upper URL", "upper prose"])
def test_upper_case_is_still_found(text):                       # pins re.I
    assert SECRET.search(text)


def test_the_model_point_checks_as_written_as_well_as_folded():  # Orithises M2: folding alone would miss this
    from semantext.model import _plain, _secret
    value = "password is ab\u200b\u200b"
    assert not SECRET.search(_plain(value))                        # folded, it is too short to be a key
    assert _secret(value)                                          # as written, it is one


# Orithises (re-check of 07a2aa4): the model point runs the check twice, as written and folded, on the card and the
# prompt before any call, so a pasted long line once stalled `ask` (20,000 letters, 4.4 s). The size row for F3.
@pytest.mark.parametrize("name,unit", RUNS)
def test_the_model_points_check_is_linear_too(name, unit):
    from semantext.model import _secret
    text = (unit * 100_000)[:100_000]
    start = time.perf_counter()
    assert _secret(text) is False
    assert time.perf_counter() - start < 1.5, name