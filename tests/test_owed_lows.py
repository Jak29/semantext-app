"""The typed-secret cut, round 4 (attack 24, after the third fix round): L4, L5 and L6.

L4  O11 was narrowed, not closed. The plug-in console prints a typed name as ascii_only(repr(name)), and _spellings never
    built that spelling: a secret holding a letter beyond ASCII AND a backslash or an invisible or control character was
    printed whole by `plugins show` (repr doubles the backslash and escapes the invisible character, ascii_only then
    doubles the backslash again and writes the letter as \\u00e4 with one). _spellings now applies the console's rule to
    every base form (raw, repr, ascii, JSON) and to the lowered value too.
L5  The value alone of key=VALUE was collected only from 6 characters, so a 4- or 5-character value followed by a path tail
    was printed by the folder message. It is collected from 4, as the prose value is.
L6  The cut of a message that echoes the typed line was quadratic in the number of typed secrets (0.44 s at 1000, 1.7 s
    at 2000): one alternation of every spelling was tried at every position. It is one pass now.

Each test failed at 99f9116 for the stated reason unless it is marked must-pass.
"""
from __future__ import annotations

import json
import random
import re
import string
import time

import pytest

from semantext import cli, pluginpage

from test_owed_cut import AGENT, USER, run, start

ZWSP, SHY, BEL, GRIN = "\u200b", "\u00ad", "\x07", "\U0001f600"
# (typed argument, what it is a secret from). The attacker's five cases, then the soft hyphen and the BEL.
L4_CASES = {
    "token-latin1-bs": "token=ä\\bcdefgh1.x",
    "prose-latin1-bs-astral": f"my password is pä\\ss{GRIN}",
    "prose-latin1-zwsp": f"my password is päss{ZWSP}word",
    "prose-latin1-bs-late": "my password is ä\\Grüße2026.x",
    "prose-ascii-bs-astral": f"my password is pa\\ss{GRIN}word",
    "prose-upper-latin1-bs": "my password is Ä\\Grüße2026.x",     # a message that lowers the name escapes ä, not Ä
    "prose-latin1-soft-hyphen": f"my password is pässw{SHY}ord",
    "prose-latin1-bel": f"my password is pä{BEL}ssword",
}
L4_CONTROLS = {"ascii-bs": "my password is pa\\ssword", "original-o11": f"my password is pässwörd{GRIN}"}


def leak_forms(argv):
    """Every way the secret may have been printed, worked out here from the console's own renderer and nothing of cli's."""
    out = set()
    for v in cli.secret_values(argv):
        for s in (v, v.lower()):
            out |= {s, repr(s)[1:-1], json.dumps(s)[1:-1], pluginpage.ascii_only(s), pluginpage.ascii_only(repr(s))[1:-1],
                    pluginpage.ascii_only(repr(s)[1:-1])}
    return {f for f in out if len(f) >= 4}


def console_message(typed: str) -> str:
    """The message plugincmd._find raises for an unknown name, as the console writes it (ascii_only of the whole text)."""
    return pluginpage.ascii_only(f"no installed package offers a plug-in named {typed!r}; `semantext plugins` lists them "
                                 f"as <kind>.<name>")


@pytest.mark.parametrize("name", list(L4_CASES) + list(L4_CONTROLS))
def test_the_console_spelling_of_a_repr_of_the_name_is_cut(name):                              # must-refuse
    typed = {**L4_CASES, **L4_CONTROLS}[name]
    argv = ["plugins", "show", typed]
    values = cli.secret_values(argv)
    assert values, "the typed secret was not collected at all"
    forms = leak_forms(argv)
    message = console_message(typed)
    assert any(f in message for f in forms), "the test does not reproduce a message that holds the secret"
    cut = cli._cut(message, values).lower()
    assert [f for f in forms if f.lower() in cut] == [], cut
    assert cli._NOT_REPEATED in cut and "no installed package offers a plug-in named" in cut   # the rest is still said


@pytest.mark.parametrize("name", list(L4_CASES) + list(L4_CONTROLS))
def test_a_lowered_message_is_cut_too(name):                                                    # must-refuse
    typed = {**L4_CASES, **L4_CONTROLS}[name]
    argv = ["plugins", "show", typed]
    cut = cli._cut(console_message(typed.lower()), cli.secret_values(argv)).lower()
    assert [f for f in leak_forms(argv) if f.lower() in cut] == [], cut


@pytest.mark.parametrize("who", [AGENT, USER], ids=["agent", "console"])
@pytest.mark.parametrize("name", list(L4_CASES) + list(L4_CONTROLS))
@pytest.mark.parametrize("extra", [[], ["--full"]], ids=["plain", "full"])
def test_plugins_show_does_not_print_the_secret_it_was_typed(name, extra, who, tmp_path, monkeypatch, capsys):   # must-refuse
    typed = {**L4_CASES, **L4_CONTROLS}[name]
    start(tmp_path, monkeypatch, who)
    code, out, err = run(["plugins", "show", typed, *extra], capsys)
    assert code != 0 and "named" in err, (code, err)
    seen = (err + out).lower()
    assert [f for f in leak_forms(["plugins", "show", typed]) if f.lower() in seen] == [], err


def test_a_plain_unknown_name_is_still_named_and_a_plain_value_has_one_spelling(tmp_path, monkeypatch, capsys):   # must-pass
    start(tmp_path, monkeypatch, AGENT)
    code, out, err = run(["plugins", "show", "no-such.thing"], capsys)
    assert code != 0 and "no-such.thing" in err
    assert cli._spellings("abcdef123456") == {"abcdef123456"}, "an ordinary value grew spellings it does not need"


def test_the_console_rule_in_cli_is_the_consoles(): # must-pass: the copy stays in step (the limit _spellings states)
    rnd = random.Random(24)
    pool = string.printable.replace(" ", "")[:80] + "äöüßé\\'\"" + ZWSP + SHY + BEL + GRIN + "ñ€\u0301\u00a0"
    for _ in range(3000):
        s = "".join(rnd.choice(pool) for _ in range(rnd.randint(1, 14)))
        assert cli._console_escaped(s) == pluginpage.ascii_only(s), repr(s)


# ---------------------------------------------------------------- L5: the value alone from 4 characters
@pytest.mark.parametrize("value", ["abcd", "abcde", "abcdef", "Zq9x5", "Hunter22"])
@pytest.mark.parametrize("shape", ["--home|/tmp/password={V}/h|rules", "install|agents-md|--file|/tmp/token={V}/AGENTS.md",
                                   "x|C:/w/api_key={V}/sub/dir"])
def test_a_value_of_four_or_five_characters_with_a_path_tail_is_collected_alone(value, shape):   # must-refuse
    argv = shape.replace("{V}", value).split("|")
    got = cli.secret_values(argv)
    assert value in got, got
    assert cli._NOT_REPEATED in cli._cut(f"[WinError 183] Cannot create a file: '/tmp/password={value}'", got)
    assert value.lower() not in cli._cut(f"[WinError 183] Cannot create a file: '/tmp/password={value}'", got).lower()


@pytest.mark.parametrize("value", ["abc", "ab", "xyz"])
def test_a_value_of_three_characters_is_still_not_collected_alone(value):                       # must-pass (the stated limit)
    got = cli.secret_values(["--home", f"/tmp/password={value}/hhhhh", "rules"])
    assert value not in got and f"{value}/hhhhh" in got


@pytest.mark.parametrize("value", ["abcd", "abcde", "abcdef"])
def test_the_folder_message_does_not_print_a_short_value_end_to_end(value, tmp_path, monkeypatch, capsys):   # must-refuse
    work = start(tmp_path, monkeypatch, AGENT)
    (work / f"password={value}").write_text("", encoding="utf-8")
    code, out, err = run(["--home", str(work / f"password={value}" / "h"), "rules"], capsys)
    assert code != 0 and value not in (err + out).lower(), err
    (work / f"token={value}").write_text("", encoding="utf-8")
    code, out, err = run(["install", "agents-md", "--file", str(work / f"token={value}" / "AGENTS.md"), "--apply"], capsys)
    assert code != 0 and value not in (err + out).lower(), err


@pytest.mark.parametrize("argv", [["x", "token=ab"], ["x", "password=abc"], ["x", "my password is ab"], ["x", "token=/abc"]])   # "=abcde": L7
def test_a_line_that_is_not_key_shaped_collects_nothing_still(argv):                             # must-pass
    assert cli.secret_values(argv) == set()


# ---------------------------------------------------------------- L6: one pass, linear in the number of secrets
def _argv_with(n, seed=24):
    rnd = random.Random(seed)

    def word(k):
        return "".join(rnd.choice(string.ascii_letters + string.digits) for _ in range(k))
    out = []
    for i in range(n):
        k = i % 4
        out.append([f"https://ghp_{word(24)}:x@h{i}.example.com/v1", f"C:/w/token={word(10)}/t{i}",
                    f"password is {word(8)}/x", f"sk-{word(22)}"][k])
    return out


def _best(f, *a, times=3):
    best = None
    for _ in range(times):
        t0 = time.perf_counter()
        r = f(*a)
        best = min(best, time.perf_counter() - t0) if best is not None else time.perf_counter() - t0
    return r, best


def test_cutting_an_echoed_line_is_linear_in_the_number_of_secrets():                          # must-refuse (0.44 s and 1.7 s)
    took = {}
    for n in (1000, 2000):
        argv = _argv_with(n)
        values = cli.secret_values(argv)
        assert len(values) >= n
        echo = "semantext: " + " ".join(argv)
        cut, took[n] = _best(cli._cut, echo, values)
        assert [a for a in argv if a.split("/")[-1].split(":")[0].lower() in cut.lower() and len(a.split("/")[-1]) > 12] == []
    assert took[2000] < 0.3, f"{took[2000]:.3f} s for 2000 secrets (99f9116: 1.7 s)"
    assert took[2000] < 3.0 * max(took[1000], 0.02), f"x{took[2000] / took[1000]:.1f} on doubling: not linear"


def test_a_long_echo_with_few_secrets_is_cut_in_time():                                         # must-pass
    secret = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    text = ("an ordinary line of words and paths C:\\Users\\x\\y " * 20 + secret + " ") * 2000     # about 2 MB
    out, t = _best(cli._cut, text, {secret}, times=1)
    assert secret not in out and out.count(cli._NOT_REPEATED) == 2000
    assert t < 5.0, f"{t:.2f} s"


# ---- the one pass says what the alternation said
def _old_cut(text, values):
    """The cut before round 4: one alternation of every spelling, longest first, case-insensitive."""
    forms = sorted({f for v in values for f in cli._spellings(v)}, key=len, reverse=True)
    if not forms or not text:
        return text
    return re.sub("|".join(re.escape(f) for f in forms), cli._NOT_REPEATED, text, flags=re.I)


def test_the_one_pass_cut_equals_the_alternation_on_random_texts():                            # must-pass (and must-refuse)
    rnd = random.Random(2024)
    values = {"Hunter22Secret", "sk-A1b2C3d4E5f6G7h8I9j0K1l2", "pässwörd" + GRIN, "ä\\Grüße2026", "abcd", "abcde/h",
              "dir\\token9999", "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3", "Straße-Key99"}
    forms = sorted({f for v in values for f in cli._spellings(v)})
    noise = list("abcdefghij kl/\\ ,.:;'\"äöüßÄÖÜ12345") + [GRIN, ZWSP]
    for _ in range(400):
        parts = []
        for _ in range(rnd.randint(1, 12)):
            if rnd.random() < 0.5:
                f = rnd.choice(forms)
                f = "".join(c.upper() if rnd.random() < 0.3 else c for c in f)
                parts.append(f)
            else:
                parts.append("".join(rnd.choice(noise) for _ in range(rnd.randint(0, 8))))
        text = "".join(parts)
        assert cli._cut(text, values) == _old_cut(text, values), repr(text)


def test_the_longest_spelling_wins_and_prefixes_of_every_length_are_cut():                      # must-refuse
    short, mid, long_ = "abcd", "abcdefgh", "abcdefghijklmnopqrst"
    assert cli._cut(f"x {long_} y", {short, mid, long_}) == f"x {cli._NOT_REPEATED} y"
    assert cli._cut(f"x {mid} y", {short, mid, long_}) == f"x {cli._NOT_REPEATED} y"
    assert cli._cut(f"x {short} y", {short, mid, long_}) == f"x {cli._NOT_REPEATED} y"
    assert cli._cut(f"x {mid}ijk y", {short, mid}) == f"x {cli._NOT_REPEATED}ijk y"               # the longer form first
    longer = long_ + "uvwxyz"                                                                     # one bucket: the same first 16
    assert cli._cut(f"x {longer} y", {long_, longer}) == f"x {cli._NOT_REPEATED} y"
    assert cli._cut(f"x {long_}uvwxy y", {long_, longer}) == f"x {cli._NOT_REPEATED}uvwxy y"
    assert cli._cut("x abc y abcxefg z", {short, mid, long_}) == "x abc y abcxefg z"             # not a whole form: stays
    assert cli._cut("", {short}) == "" and cli._cut("abc abcd", set()) == "abc abcd"


def test_secrets_that_share_a_long_prefix_are_each_cut_whole():                                 # must-refuse
    base = "sk-ant-api03-" + "Q" * 6
    values = {base + f"{i:04d}tail" for i in range(300)}
    text = " ".join(sorted(values)) + " and " + base + "0007"                                    # the last one is only a prefix
    out = cli._cut(text, values)
    assert out == " ".join([cli._NOT_REPEATED] * 300) + " and " + base + "0007"


@pytest.mark.parametrize("typed,printed", [("Ärger-Pass-99", "ärger-pass-99"), ("Straße-Key99", "STRASSE-KEY99".replace("SS", "ß")),
                                           ("ΣΙΓΜΑ-Key-99", "σιγμα-key-99"), ("Kelvin-Key99", "Kelvin-Key99".replace("K", "\u212a"))])
def test_case_is_folded_character_by_character(typed, printed):                                 # must-refuse
    assert cli._cut(f"bad {printed} here", {typed}) == f"bad {cli._NOT_REPEATED} here"


def test_the_fold_agrees_with_the_re_module_on_every_cased_character():                         # must-pass
    """The cut folds one character at a time; the alternation it replaced asked the re module. Where a character has a
    case, the two must say the same about the character and each of its other cases."""
    import sys
    seen = 0
    for cp in range(0x20000):                                    # every cased character is in the first two planes
        c = chr(cp)
        if c.lower() == c and c.upper() == c and c.casefold() == c:
            continue
        for d in {c.lower(), c.upper(), c.title(), c.casefold()}:
            if len(d) != 1 or d == c:
                continue
            seen += 1
            same = re.fullmatch(re.escape(c), d, re.I) is not None
            assert (cli._fold(c) == cli._fold(d)) == same, (hex(cp), hex(ord(d)))
    assert seen > 2000
    extra = getattr(getattr(re, "_casefix", None), "_EXTRA_CASES", None)   # the characters the re module joins by hand
    assert extra is None or len(extra) > 10
    for low, others in (extra or {}).items():
        assert {cli._fold(chr(x)) for x in (low, *others)} == {cli._fold(chr(low))}, (hex(low), [hex(x) for x in others])
