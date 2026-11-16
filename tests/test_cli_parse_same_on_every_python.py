"""A command line is read the same way on every Python the package supports.

argparse before Python 3.12.7 gives a word to nobody when it follows an option and an earlier word of the command was
already taken: `semantext env add --env work an-id` left `an-id` unread on 3.10 and 3.11 ("unrecognized arguments"),
while newer Pythons read it. The suite only ever ran on a newer Python, so nobody saw it until the whole suite was run
under 3.11 on 15 November 2026 (six tests failed there, all this). cli._Parser now has a sub-command read its part of
the line a second way when the first leaves words unread, and keeps the second reading only if it reads every word.

What is held here:
1. where an option sits among a sub-command's words does not change what is read (every sub-command that has words and
   a plain option, on whichever Python runs this: on 3.10 and 3.11 that is the second reading at work);
2. the second way reads a line exactly as the first does wherever the first reads it whole (so falling back to it
   changes nothing but the lines the old argparse could not read);
3. a line with more words than its command takes is refused as before, in the same words, and a key-shaped word in it
   is not repeated.
What changed on every Python, and is meant: the words of one many-word argument split by an option
(`backtest a.jsonl --env work b.jsonl`) were refused by every Python and are now read (law 1 fails on the old code
under 3.14 for that reason, and under 3.11 for the 3.11 reason as well).
Limit: options that take several values (--pick, --accept, --how, --to) or an optional value are left out of 1, since
they take the words that follow them on every Python.
"""
from __future__ import annotations

import argparse

import pytest

from semantext import cli

KEY = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"          # made up, in the shape of a key


def subparsers() -> dict:
    """Each sub-command's parser, once, by its first name."""
    top = cli.build_parser()
    sub = next(a for a in top._actions if isinstance(a, argparse._SubParsersAction))
    seen, out = set(), {}
    for name, sp in sub.choices.items():
        if id(sp) not in seen:
            seen.add(id(sp))
            out[name] = sp
    return out


def _sample(action) -> str:
    if action.choices:
        return sorted(str(c) for c in action.choices)[0]
    return "1" if action.type is int else "word"


def _words(sp) -> list:
    words = []
    for a in sp._get_positional_actions():
        n = {None: 1, "?": 1, "*": 2, "+": 2}.get(a.nargs, a.nargs if isinstance(a.nargs, int) else 1)
        words += [_sample(a)] * n if not a.choices else [_sample(a)]
    return words


def _plain_options(sp) -> list:
    """Up to two of the sub-command's options that take no value or exactly one, as they would be typed."""
    typed = []
    for a in sp._get_optional_actions():
        if not a.option_strings or isinstance(a, (argparse._HelpAction, argparse._VersionAction)):
            continue
        flag = max(a.option_strings, key=len)
        if a.nargs == 0:
            typed.append([flag])
        elif a.nargs is None:
            typed.append([flag, _sample(a)])
        if len(typed) == 2:
            break
    return [x for pair in typed for x in pair]


def _read(sp, line, how=None):
    """(what was read, the words left unread), or None when the line is refused."""
    try:
        ns, left = (how or sp.parse_known_args)(list(line))
    except SystemExit:
        return None
    return vars(ns), left


def cases():
    for name, sp in sorted(subparsers().items()):
        words, opts = _words(sp), _plain_options(sp)
        if words and opts:
            yield name, sp, words, opts


def test_where_an_option_sits_among_the_words_changes_nothing(capsys):
    between, checked = 0, 0
    for name, sp, words, opts in cases():
        last = _read(sp, words + opts)                     # the documented order: the words, then the options
        capsys.readouterr()
        if last is None or last[1]:
            continue                                       # the made-up words are not a line this command takes
        checked += 1
        first = _read(sp, opts + words)
        assert first == last, f"{name}: options first reads otherwise: {opts + words}"
        if len(words) >= 2:
            middle = words[:1] + opts + words[1:]          # the shape the old argparse could not read
            assert _read(sp, middle) == last, f"{name}: an option after the first word reads otherwise: {middle}"
            between += 1
    assert checked >= 12 and between >= 6, (checked, between)   # the law is tried on real sub-commands, not on none


def test_the_second_way_reads_what_the_first_way_reads(capsys):
    plain = argparse.ArgumentParser.parse_known_args           # argparse's own reading, without _Parser's second way
    tried = 0
    for name, sp, words, opts in cases():
        for line in (words + opts, opts + words, words):
            first = _read(sp, line, lambda a: plain(sp, a))
            capsys.readouterr()
            if first is None or first[1]:
                continue
            sp._again = True                                   # as _Parser sets it while it reads the second way
            try:
                second = _read(sp, line, sp.parse_known_intermixed_args)
            finally:
                sp._again = False
            assert second == first, f"{name}: the second way reads {line} otherwise"
            tried += 1
    assert tried >= 30, tried


@pytest.mark.parametrize("line, read", [
    (["env", "add", "--env", "work", "an-id"], {"action": "add", "env": "work", "name_or_title": ["an-id"]}),
    (["env", "add", "an-id", "--env", "work"], {"action": "add", "env": "work", "name_or_title": ["an-id"]}),
    (["env", "new", "--none", "Research", "notes"], {"action": "new", "none": True, "name_or_title": ["Research", "notes"]}),
    (["env", "new", "Research", "notes", "--none"], {"action": "new", "none": True, "name_or_title": ["Research", "notes"]}),
])
def test_the_lines_the_old_argparse_could_not_read(line, read):            # must-pass on every Python
    args = cli.build_parser().parse_args(line)
    assert {k: getattr(args, k) for k in read} == read


@pytest.mark.parametrize("line", [["card", "extra"], ["env", "list", "--none", "--bogus"], ["compute", "ask", "extra"],
                                  ["rules", "--env", "work", "extra", "words"]])
def test_a_line_no_python_reads_is_refused_as_before(line, capsys):       # must-refuse
    with pytest.raises(SystemExit) as stop:
        cli.build_parser().parse_args(line)
    err = capsys.readouterr().err
    assert stop.value.code == 2 and "unrecognized arguments: " + " ".join(x for x in line if x in ("extra", "words", "--bogus")) in err


@pytest.mark.parametrize("line", [["card", KEY], ["rules", "--env", "work", KEY], ["compute", KEY]])
def test_a_key_in_a_refused_line_is_not_repeated(line, capsys):           # must-refuse
    with pytest.raises(SystemExit) as stop:
        cli.build_parser().parse_args(line)
    seen = capsys.readouterr()
    assert stop.value.code == 2
    assert KEY not in seen.err + seen.out and KEY[:12] not in seen.err + seen.out
