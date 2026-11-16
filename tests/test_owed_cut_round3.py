"""The typed-secret cut, third round (attack 22b: O7 to O11). Each test here failed on 4756135 for the stated reason.

O7  a key typed as the USER part of user:password@ was never collected, so a message printing the address printed it.
O8  key=VALUE and "password is VALUE" were collected only together with everything after them up to the next space, so
    a message printing the value without that tail printed it whole.
O9  the stdout exemption for commands a reader waits on was triggered by any typed WORD (hook, mcp, serve), not by the
    command: `start --since KEY --from serve` printed KEY on stdout.
O10 with no console streams (pythonw) a command whose line held a secret raised AttributeError out of main.
O11 the ascii_only spelling (\\u00e4 for a Latin-1 letter, \\U0001f600 beside it) was not built.

Must-pass: an ordinary user name, a bare word and a short value are still not collected; a command a reader waits on is
still never held. Must-refuse: every spelling of the key, in every message the attacker used.
"""
from __future__ import annotations

import contextlib
import sys

import pytest

from semantext import cli, pluginpage

from test_owed_cut import AGENT, K, USER, case_args, make_files, run, shown_in, start


ONE_MESSAGE = '{"type": "user", "message": {"role": "user", "content": "always answer in French"}}\n'


# ---- O7: the key in the USER part of a URL ---------------------------------------------------------------------------
USER_PART_SHAPES = ["{K}:x", "{K}:x-oauth-basic", "{K}:pw", "{K}:Hunter22Secret"]


@pytest.mark.parametrize("shape", USER_PART_SHAPES)
@pytest.mark.parametrize("name", list(K))
def test_a_key_in_the_user_part_of_a_url_is_collected(name, shape):                 # must-refuse
    key = K[name]
    got = cli.secret_values(["backtest", "--reader", "endpoint:https://" + shape.replace("{K}", key) + "@api.example.com/v1#m"])
    assert key in got


def test_the_user_part_is_cut_in_every_spelling_a_message_uses():                  # must-refuse
    key = K["gh"]
    got = cli.secret_values(["model", "set", "--address", f"http://{key}:x-oauth-basic@127.0.0.1:1"])
    for line in (f"carries {key}:x@host", f"carries {key.lower()}:x@host", f"carries {key!r}", "carries " + repr(key + "\\"),
                 f"carries {key.upper()}"):
        assert key.lower() not in cli._cut(line, got).lower(), line


def test_an_ordinary_user_part_and_a_bare_address_collect_no_user():              # must-pass
    got = cli.secret_values(["backtest", "--reader", "endpoint:https://bob:Hunter22Secret@api.example.com/v1#m"])
    assert got == {"Hunter22Secret"}
    assert cli.secret_values(["model", "set", "--address", "http://alice@127.0.0.1:1", "--model", "m"]) == set()
    assert cli.secret_values(["model", "set", "--address", "http://alice:pw@127.0.0.1:1", "--model", "m"]) == set()


USER_PART = [
    ("backtest-user", AGENT, ["backtest", "--reader", "endpoint:https://{K}:x@api.example.com/v1#m", "{T}/t.jsonl"], ["t.jsonl"]),
    ("backtest-user-gh", AGENT, ["backtest", "--reader", "endpoint:https://{K}:x-oauth-basic@api.example.com/v1#m", "{T}/t.jsonl"],
     ["t.jsonl"]),
    ("record-user", USER, ["record", "topics", "--reader", "endpoint:https://{K}:x-oauth-basic@api.example.com#m"], []),
    ("model-user", USER, ["model", "set", "--address", "http://{K}:x-oauth-basic@127.0.0.1:1", "--model", "m"], []),
    ("backtest-http", USER, ["backtest", "--reader", "endpoint:http://{K}:x-oauth-basic@api.example.com/v1#m@SOMEVAR", "{T}/t.jsonl"],
     ["t.jsonl"]),
]


@pytest.mark.parametrize("template", USER_PART, ids=lambda t: t[0])
def test_a_key_in_the_user_part_is_not_said_back(template, tmp_path, monkeypatch, capsys):       # must-refuse
    leaks = []
    for kn, key in K.items():
        sub = tmp_path / kn
        sub.mkdir()
        monkeypatch.setenv("SEMANTEXT_HOME", str(sub / "semantext"))
        work = start(sub, monkeypatch, template[1])
        make_files(work, template[3], key)
        for f in template[3]:   # a trace with one message in it: an EMPTY one exits 0 before the refusal this test guards
            (work / f).write_text(ONE_MESSAGE, encoding="utf-8")
        code, out, err = run(case_args(template[2], work, sub / "semantext", key), capsys)
        # attack 25, L10: backtest-http read an empty trace, exited 0 after 0 calls, and never reached its refusal, so it
        # passed on a build that cut nothing. Each case must END in a refusal (a failed command is the one whose stdout
        # is cut), whatever the build.
        assert code not in (0, None), (template[0], kn, code, out, err)
        for stream, text in (("stderr", err), ("stdout", out if code not in (0, None) else "")):
            if shown_in(text, key):
                leaks.append((kn, stream, text.strip()[:200]))
        for name_ in template[1]:
            monkeypatch.delenv(name_, raising=False)
    assert leaks == []


# ---- O8: the value alone, as well as with its tail -------------------------------------------------------------------
ALONE = [
    ("path-tail", ["--home", "/tmp/password=Hunter22Secret/h", "rules"], "Hunter22Secret", "Hunter22Secret/h"),
    ("path-token", ["install", "agents-md", "--file", "/tmp/token=abcdef123456/AGENTS.md"], "abcdef123456", "abcdef123456/AGENTS.md"),
    ("reader-query", ["backtest", "--reader", "endpoint:http://api.example.com/v1?token=abcdef123456#m@SOMEVAR", "t.jsonl"],
     "abcdef123456", "abcdef123456#m@SOMEVAR"),
    ("amp", ["x", "https://h/p?a=1&api_key=abcdef123456&b=2"], "abcdef123456", "abcdef123456&b=2"),
    ("quoted", ["x", 'password="abcdef123456",next'], "abcdef123456", None),
    ("semicolon", ["x", "secret=abcdef123456;rest"], "abcdef123456", "abcdef123456;rest"),
    ("bracket", ["x", "passphrase=abcdef123456]more"], "abcdef123456", "abcdef123456]more"),
    ("prose", ["x", "my password is hunter22/tail"], "hunter22", "hunter22/tail"),
    ("prose-comma", ["x", "my passcode was hunter22,then"], "hunter22", "hunter22,then"),
]


@pytest.mark.parametrize("case", ALONE, ids=lambda c: c[0])
def test_the_value_alone_is_collected_as_well_as_with_its_tail(case):                # must-refuse
    _, argv, alone, with_tail = case
    got = cli.secret_values(argv)
    assert alone in got
    if with_tail:
        assert with_tail in got


def test_a_message_that_prints_the_value_without_its_tail_is_cut():                # must-refuse
    got = cli.secret_values(["--home", "/tmp/password=Hunter22Secret/h", "rules"])
    assert "hunter22secret" not in cli._cut("[WinError 183] 'c0\\password=Hunter22Secret'", got).lower()
    assert "abcdef123456" not in cli._cut("use https for http://api.example.com/v1?token=abcdef123456",
                                          cli.secret_values(["a", "http://api.example.com/v1?token=abcdef123456#m@V"]))


@pytest.mark.parametrize("argv", [["x", "token=ab"], ["x", "password=abc"], ["x", "my password is ab"],   # "=abcde": L7 collects it
                                  ["x", "token=/abc"], ["x", 'password="",x'], ["x", "token="]])
def test_a_value_too_short_to_be_one_is_not_collected(argv):                         # must-pass
    assert cli.secret_values(argv) == set()


def test_the_path_tail_is_cut_end_to_end(tmp_path, monkeypatch, capsys):             # must-refuse
    work = start(tmp_path, monkeypatch, AGENT)
    (work / "password=Hunter22Secret").write_text("", encoding="utf-8")
    code, out, err = run(["--home", str(work / "password=Hunter22Secret" / "h"), "rules"], capsys)
    assert code != 0 and "hunter22secret" not in (err + out).lower()
    (work / "token=abcdef123456").write_text("", encoding="utf-8")
    code, out, err = run(["install", "agents-md", "--file", str(work / "token=abcdef123456" / "AGENTS.md"), "--apply"], capsys)
    assert "abcdef123456" not in (err + out).lower()


def test_the_reader_query_is_cut_end_to_end(tmp_path, monkeypatch, capsys):          # must-refuse
    work = start(tmp_path, monkeypatch, USER)
    (work / "t.jsonl").write_text('{"type": "user", "message": {"role": "user", "content": "always answer in French"}}\n',
                                  encoding="utf-8")
    for query in ("token=abcdef123456", "password=Hunter22Secret", "a=1&api_key=abcdef123456", "secret=Zq9xW8vU7tS6"):
        code, out, err = run(["backtest", "--reader", f"endpoint:http://api.example.com/v1?{query}#m@SOMEVAR",
                              str(work / "t.jsonl")], capsys)
        value = query.split("=")[-1]
        assert code != 0 and value.lower() not in (err + out).lower(), query


# ---- O9: the exemption follows the command, not a typed word ----------------------------------------------------------
@pytest.mark.parametrize("word", ["hook", "mcp", "serve", "--hook"])
def test_a_failing_command_with_a_streaming_word_typed_is_still_cut(word, tmp_path, monkeypatch, capsys):    # must-refuse
    work = start(tmp_path, monkeypatch, AGENT)
    key = K["gh"]
    # attack 25, L10: "--from --hook" is an argparse error ("expected one argument", exit 2) before any message is made, so
    # the case passed on a build that cut nothing. "--from=--hook" gives the option its value and runs the command.
    code, out, err = run(["start", "--since", key, f"--from={word}"], capsys)
    assert "expected one argument" not in err and code != 2, (word, code, err)
    assert not shown_in(out, key) and not shown_in(err, key), (code, out, err)
    code, out, err = run(["--home", str(work / word), "work", "show", key], capsys)
    assert code != 0 and not shown_in(out, key) and not shown_in(err, key), (code, out, err)


def test_a_streaming_word_typed_as_a_value_does_not_decide(tmp_path, monkeypatch, capsys):        # must-refuse
    start(tmp_path, monkeypatch, AGENT)
    held = []
    real = cli._main

    def spy(argv, typed):
        held.append(isinstance(sys.stdout, cli._Cutting))
        return real(argv, typed)
    monkeypatch.setattr(cli, "_main", spy)
    run(["start", "--since", K["gh"], "--from", "serve"], capsys)
    assert held == [True]


def _parsed(*argv):
    return cli.build_parser().parse_args(list(argv))


@pytest.mark.parametrize("argv", [["serve"], ["mcp"], ["hook"], ["start", "--hook"], ["proxy", "serve", "--space", "s"]])
def test_the_commands_a_reader_waits_on_are_streaming(argv):                           # must-pass
    assert cli._streams(_parsed(*argv))


@pytest.mark.parametrize("argv", [["start", "--since", "serve"], ["work", "show", "hook"], ["proxy", "asks"], ["rules"],
                                  ["start"], ["toggle", "mcp"], ["feed", "on"]])
def test_other_commands_are_not_streaming_whatever_words_they_hold(argv):             # must-refuse
    assert not cli._streams(_parsed(*argv))


@pytest.mark.parametrize("word", ["serve", "mcp", "hook"])
def test_a_command_a_reader_waits_on_gets_the_real_stdout(word, tmp_path, monkeypatch, capsys):    # must-pass
    work = start(tmp_path, monkeypatch, USER)
    seen = []

    def fake(*a, **kw):
        seen.append(sys.stdout)
        print("a line a reader waits on")
        return 0
    monkeypatch.setattr(cli, {"serve": "cmd_serve", "mcp": "cmd_mcp", "hook": "hook_main"}[word], fake)
    code, out, err = run(["--home", str(work / K["gh"]), word], capsys)
    assert code == 0 and "a line a reader waits on" in out
    assert seen and not isinstance(seen[0], cli._Cutting)


# ---- O10: no console streams -------------------------------------------------------------------------------------------
NONE_CASES = [(["card", "--env", "default", "--agent", "x/" + K["gh"]], AGENT), (["toggle", K["gh"]], USER),
              (["read", "--env", K["gh"], "hello"], AGENT), (["config", "my password\tis hunter22"], AGENT)]


@pytest.mark.parametrize("argv, who", NONE_CASES, ids=["card", "toggle", "read", "config"])
def test_no_console_stream_and_a_secret_typed_raises_nothing(argv, who, tmp_path, monkeypatch, capsys):    # must-refuse
    start(tmp_path, monkeypatch, who)

    def call():
        try:
            return cli.main(argv)
        except SystemExit as e:
            return e.code
    with contextlib.redirect_stdout(None), contextlib.redirect_stderr(None):
        code = call()
    assert code in (0, 1, 2)


def test_no_console_stream_gives_the_same_exit_as_with_one(tmp_path, monkeypatch, capsys):   # must-pass
    start(tmp_path, monkeypatch, AGENT)
    argv = ["toggle", K["gh"]]
    with_streams = run(argv, capsys)[0]
    with contextlib.redirect_stdout(None), contextlib.redirect_stderr(None):
        assert cli.main(argv) == with_streams


def test_a_cutting_stream_over_nothing_writes_nothing():                                # must-refuse
    for hold in (False, True):
        c = cli._Cutting(None, {"abcdef123456"}, hold=hold)
        assert c.write("abcdef123456\n") == 13
        c.finish(True)


# ---- O11: the ascii_only spelling of a mixed value --------------------------------------------------------------------
MIXED = ["pässwörd\U0001f600", "café\U0001f511zz", "xсä\U0001f600yy", "ééé\U0001f600\U0001f600"]


@pytest.mark.parametrize("value", MIXED)
def test_the_ascii_only_spelling_of_a_mixed_value_is_cut(value):                      # must-refuse
    got = cli.secret_values(["config", "my password is " + value])
    assert got == {value}
    spelled = pluginpage.ascii_only(value)
    assert cli._cut("bad " + spelled, got) == "bad " + cli._NOT_REPEATED
    assert cli._cut("bad " + repr(spelled), got) == "bad '" + cli._NOT_REPEATED + "'"
    assert cli._cut("bad " + spelled.upper(), got) == "bad " + cli._NOT_REPEATED


def test_the_mixed_value_is_cut_end_to_end(tmp_path, monkeypatch, capsys):             # must-refuse
    start(tmp_path, monkeypatch, AGENT)
    code, out, err = run(["plugins", "show", "my password is pässwörd\U0001f600"], capsys)
    assert code != 0
    for bad in ("p\\u00e4ss", "\\u00f6rd", "\\U0001f600", "\U0001f600", "päss"):
        assert bad not in (err + out), (bad, err)


def test_a_plain_word_is_not_cut_by_the_extra_spellings():                            # must-pass
    got = cli.secret_values(["config", "my password is pässwörd\U0001f600"])
    assert cli._cut("the word password is here, and päss is short", got) == "the word password is here, and päss is short"
