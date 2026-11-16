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


# ---------------------------------------------------------------- R10: the JSON web token arm (round 4)
# Its first segment ran to the end of its run of token characters and then needed a dot, so each "eyJ" of one long run
# scanned the rest of it again: quadratic. 20,000 characters of "eyJa" took 9.9 s at 1.8.0's base, with the GIL held, and
# the folded text of feed.scrub (every non-ASCII character read as a hyphen, a token character) sent "eyJé" into it too.
JWT_RUNS = [("eyJa", "eyJa"), ("eyJ-e-acute", "eyJ\u00e9"), ("eyJ-U+3316", "eyJ\u3316"), ("eyJ-U+3389", "eyJ\u3389")]
SIZES = [5_000, 10_000, 20_000, 80_000]
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"


def _clock(fn, text):
    start = time.perf_counter()
    fn(text)
    return time.perf_counter() - start


def _nfkc(text):
    import unicodedata
    return unicodedata.normalize("NFKC", text)


@pytest.mark.parametrize("name,unit", JWT_RUNS, ids=[n for n, _ in JWT_RUNS])
def test_a_long_run_of_eyj_is_checked_in_linear_time(name, unit):   # fails on the base: 20,000 took 0.5 s, 80,000 took ~9 s
    from semantext.feed import scrub
    times = {}
    for size in SIZES:
        text = (unit * size)[:size]
        times[size] = max(_clock(SECRET.search, text), _clock(scrub, text), _clock(lambda t: SECRET.search(_nfkc(t)), text))
    assert times[80_000] < 0.2, times                                     # the stated bound at 80,000 characters
    # linear growth: x16 the input is about x16 the time; quadratic is x256. A floor keeps timer noise out of the ratio.
    assert times[80_000] < 48 * max(times[5_000], 0.001), times


def test_the_attackers_message_is_read_in_proportion_to_its_length():     # the message of the finding, 19,998 characters
    from semantext import reading
    acts = "publish push delete send pay download fix "
    for unit in ("eyJa", "eyJ\u00e9", "eyJ\u3316", "eyJ\u3389"):
        text = acts + unit * ((20_000 - len(acts)) // 4)
        assert len(text) <= 20_000
        start = time.perf_counter()
        reading.report(text)
        assert time.perf_counter() - start < 1.0, unit.encode("ascii", "backslashreplace")


@pytest.mark.parametrize("text", [
    JWT,
    "Authorization: Bearer " + JWT,
    '{"token": "' + JWT + '"}',
    "x=" + JWT + "&y=1",
    "cookie;" + JWT + ";",
    "EYJHBGCIOIJIUZI1NIJ9.EYJZDWIIOIIXMJM0NTY3ODKWIN0.DBJFTJEZ4CVPMB92K27UHBUJU1P1R_WW1GFWFOEJXK",   # pins re.I
    "xyz" + JWT,                                                       # glued to a token character before it
    "a" * 5_000 + JWT,                                                 # after a long run of token characters
    "eyJeyJeyJ" + JWT[3:],                                             # eyJ inside its own first segment
    "eyJ12345678eyJ.abcdefgh.abcdefgh",                                # an eyJ whose own tail is too short: the first one counts
    "eyJa" * 30_000 + "." + "b" * 8 + "." + "c" * 8,                    # a long run of them, then the dots: found, in time
    "pad " * 100 + "eyJabcdefgh.abcdefgh.abcdefgh",
    "eyJabcdefgh.abcdefgh.abcdefgh" + "tail",
], ids=["bare", "bearer", "json", "after =", "between ;", "upper case", "glued before", "after 5,000 letters",
        "eyJ in its first segment", "short tail of a later eyJ", "long run then dots", "after padding", "with a tail"])
def test_every_form_of_a_json_web_token_is_still_found(text):        # must-pass: nothing the arm caught before is lost
    start = time.perf_counter()
    assert SECRET.search(text)
    assert time.perf_counter() - start < 0.5


def test_the_match_holds_the_whole_token_even_when_glued():          # what secret_values cuts out of a typed word
    assert SECRET.search("xyz" + JWT).group(0).endswith(JWT)
    assert SECRET.search("A B " + JWT + " C").group(0) == JWT


@pytest.mark.parametrize("text", [
    "eyJ" + "a" * 100,                                                # no dots
    "eyJabcdefgh.abcdefgh",                                           # two segments
    "eyJabc.defghijk.lmnopqrs",                                       # first segment too short
    "eyJabcdefgh.abc.abcdefgh",                                       # second too short
    "eyJabcdefgh.abcdefgh.abc",                                       # third too short
    "eyJabcdefgh abcdefgh.abcdefgh",                                  # a space ends the run before a dot
    "eyJ" * 30_000,                                                   # a long run of eyJ with no dot: no key, and quick
    ("eyJ\u00e9" * 20_000),
], ids=["no dots", "two segments", "short first", "short second", "short third", "space in it", "long eyJ run", "long non-ASCII run"])
def test_text_that_only_looks_like_a_json_web_token_is_not_one(text):   # must-refuse
    start = time.perf_counter()
    assert not SECRET.search(text)
    assert time.perf_counter() - start < 0.5


def test_the_proxys_bounded_pattern_still_builds_and_finds_it_in_time():   # proxy._bounded needs the arm's literal text whole
    from semantext import proxy
    assert proxy.SECRET_BOUNDED.search("padding " + JWT)
    assert not proxy.SECRET_BOUNDED.search("eyJa" * 20_000)
    start = time.perf_counter()
    assert proxy._secret(("eyJa" * 60_000) + " " + JWT)               # longer than one window: found across windows
    assert proxy._secret("q" * 200_000 + " " + JWT)
    assert not proxy._secret("eyJa" * 60_000)
    assert time.perf_counter() - start < 3.0
