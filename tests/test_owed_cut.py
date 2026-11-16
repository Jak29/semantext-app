"""A secret typed on the command line is never said back, whatever the message does to it (attack 22, O4).

The first backstop cut a key-shaped argument out of an error line only where the line repeated the typed word character
for character. A message changes a word: a URL lowercased, a path normalised (./ and the trailing / dropped, / made \\),
a backslash doubled by repr, a non-ASCII letter escaped, a tab written \\t before the parser's own scrub runs. The
backstop now collects the secret VALUES from the typed line and cuts every spelling of each, in any case, from every
line written to stderr and from stdout when the command fails.

Must-refuse: the attacker's path, repr, URL-credential, ASCII-escape, tab and newline cases (ported from the scripts of
attack 22) show no secret in stderr or stdout. Must-pass: an ordinary wrong word is still named; nothing else in an error
line is cut; a command that worked prints what it prints.
"""
from __future__ import annotations

import io
import json

import pytest

from semantext import cli

K = {
    "openai": "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2",
    "stripe": "sk_live_" + "A1b2C3d4E5f6G7h8I9j0K1",
    "gh": "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3",
    "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
    "jwt": "eyJhbGciOiJI.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
    "slack": "xoxb-" + "1234567890-abcdefghij",
    "hf": "hf_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6",
    "pat": "github_pat_" + "A1b2C3d4E5f6G7h8I9j0K1",
    "long": "Xk9" + "a8Zq7Lm2Pw4Rt6Yu1Io3Ee5Dc0Vb9Nn8Mm7Qq6Ww5Ee4Rr3Tt2Yy1",
    "hex": "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "b64": "dGhpcyBpcyBhIHNlY3JldCB0b2tlbiB2YWx1ZSBmb3IgdGVzdGluZw==",
}
AGENT, USER = {"CLAUDECODE": "1"}, {}

# (name, who, args with {K}, files made first). {T} is a working folder, {H} the Semantext home.
PATHS = [
    ("cases-export-fwd", AGENT, ["cases", "--export", "{T}/nope/{K}/out.jsonl"], []),
    ("cases-export-back", AGENT, ["cases", "--export", "{T}\\nope\\{K}\\out.jsonl"], []),
    ("proxy-asks-dot-slash", AGENT, ["proxy", "asks", "--proxy-home", "./{K}/"], []),
    ("proxy-asks-fwd", AGENT, ["proxy", "asks", "--proxy-home", "{T}/{K}"], []),
    ("proxy-asks-plain", AGENT, ["proxy", "asks", "--proxy-home", "{K}"], []),
    ("home-under-a-file", AGENT, ["--home", "{T}/{K}/h", "rules"], ["{K}"]),
    ("agent-bind-fwd", USER, ["agent", "bind", "bob", "--folder", "{T}/nope/{K}"], []),
    ("agent-bind-dot", USER, ["agent", "bind", "bob", "--folder", "./{K}/"], []),
    ("install-agents-md", AGENT, ["install", "agents-md", "--file", "{T}/nope/{K}/AGENTS.md", "--apply"], []),
    ("install-claude", AGENT, ["install", "claude-code", "--settings", "{T}/nope/{K}/s.json", "--apply"], []),
    ("uninstall-claude", USER, ["uninstall", "claude-code", "--settings", "{T}/nope/{K}/s.json", "--apply"], []),
    ("mine-not-a-file", AGENT, ["mine", "{T}/nope/{K}.jsonl", "--dry-run"], []),
    ("backtest-not-a-file", AGENT, ["backtest", "{T}/nope/{K}.jsonl"], []),
    ("doctor-settings", AGENT, ["doctor", "--settings", "{T}/nope/{K}/settings.json"], []),
    ("agent-unbind", USER, ["agent", "unbind", "--folder", "{T}/{K}"], []),
]
REPRS = [
    ("toggle-bs", USER, ["toggle", "x\\{K}"], []),
    ("pin-bs", USER, ["pin", "x\\{K}"], []),
    ("undo-bs", USER, ["undo", "x\\{K}"], []),
    ("plugins-show-bs", AGENT, ["plugins", "show", "x\\{K}"], []),
    ("plugins-disable-bs", AGENT, ["plugins", "disable", "x\\{K}"], []),
    ("env-add-bs", USER, ["env", "add", "x\\{K}"], []),
    ("toggle-agent", AGENT, ["toggle", "x\\{K}"], []),
    ("toggle-plain", USER, ["toggle", "{K}"], []),
    ("read-env-bs", AGENT, ["read", "--env", "x\\{K}", "hello"], []),
    ("hours-bs", AGENT, ["compute", "hold", "--hours", "x\\{K}"], []),
    ("pick-bs", USER, ["env", "new", "Office", "--pick", "x\\{K}"], []),
    ("model-name-bs", USER, ["model", "set", "--address", "http://127.0.0.1:1", "--model", "x\\{K}"], []),
]
ASCII = [
    ("plugins-show-eacute-before", AGENT, ["plugins", "show", "é{K}"], []),
    ("plugins-show-eacute-after", AGENT, ["plugins", "show", "{K}é"], []),
    ("toggle-eacute", USER, ["toggle", "é{K}"], []),
    ("plugins-show-astral", AGENT, ["plugins", "show", "\U0001f600{K}"], []),
]
URLS = [
    ("backtest-reader", AGENT, ["backtest", "--reader", "endpoint:https://bob:{K}@api.example.com/v1#m", "{T}/t.jsonl"],
     ["t.jsonl"]),
    ("record-reader", USER, ["record", "topics", "--reader", "endpoint:https://bob:{K}@api.example.com#m"], []),
    ("model-address", USER, ["model", "set", "--address", "http://bob:{K}@127.0.0.1:1", "--model", "m"], []),
]
URL_PASSWORDS = {"plain": "Hunter22Secret", "symbols": "Pa55-w0rd_Zz9", "longer": "correct-horse-battery-staple-9"}


def start(tmp_path, monkeypatch, who, console_after: bool = False):
    """A home made by the user at their console, then the shell of whoever runs the case."""
    work = tmp_path / "t"
    work.mkdir(exist_ok=True)
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: True)
    cli.main(["init"])
    for name, value in who.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: not who)
    monkeypatch.chdir(work)
    return work


def run(args, capsys):
    capsys.readouterr()
    try:
        code = cli.main(args)
    except SystemExit as e:
        code = e.code
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def shown_in(text: str, secret: str) -> bool:
    """Whether the secret shows in the text: as written, lowered, or as most of it (the first 12 characters)."""
    low = text.lower()
    return secret in text or secret.lower() in low or (len(secret) > 12 and secret[:12].lower() in low)


def case_args(args, work, home, key):
    return [a.replace("{K}", key).replace("{T}", str(work)).replace("{H}", str(home)) for a in args]


def make_files(work, files, key):
    for f in files:
        p = work / f.replace("{K}", key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("", encoding="utf-8")


def run_family(template, keys, tmp_path, monkeypatch, capsys, home):
    name, who, args, files = template
    leaks = []
    for kn, key in keys.items():
        sub = tmp_path / kn   # one home per key
        sub.mkdir()
        monkeypatch.setenv("SEMANTEXT_HOME", str(sub / "semantext"))
        work = start(sub, monkeypatch, who)
        make_files(work, files, key)
        code, out, err = run(case_args(args, work, sub / "semantext", key), capsys)
        # stderr always; stdout when the command failed (a command that worked prints the user's own result)
        for stream, text in (("stderr", err), ("stdout", out if code not in (0, None) else "")):
            if shown_in(text, key):
                leaks.append((kn, stream, text.strip()[:200]))
        for name_ in who:
            monkeypatch.delenv(name_, raising=False)
    return leaks


@pytest.mark.parametrize("template", PATHS + REPRS + ASCII, ids=lambda t: t[0])
def test_a_key_in_a_changed_word_is_not_said_back(template, tmp_path, monkeypatch, capsys, home):   # must-refuse
    assert run_family(template, K, tmp_path, monkeypatch, capsys, home) == []


@pytest.mark.parametrize("template", URLS, ids=lambda t: t[0])
def test_a_key_in_a_url_credential_is_not_said_back(template, tmp_path, monkeypatch, capsys, home):  # must-refuse
    assert run_family(template, K, tmp_path, monkeypatch, capsys, home) == []


@pytest.mark.parametrize("template", URLS, ids=lambda t: t[0])
@pytest.mark.parametrize("pw", URL_PASSWORDS.values(), ids=URL_PASSWORDS.keys())
def test_a_url_password_a_message_lowercases_is_not_said_back(template, pw, tmp_path, monkeypatch, capsys, home):  # must-refuse
    assert run_family(template, {"pw": pw}, tmp_path, monkeypatch, capsys, home) == []


PROSE = {"tab": ("my password\tis hunter22", "hunter22"), "newline": ("my password\nis hunter22", "hunter22"),
         "space": ("my password is hunter22", "hunter22"), "tab-was": ("passphrase\twas Zebra-77-Orbit", "Zebra-77-Orbit"),
         "token-tab": ("token:\tabcdef123456", "abcdef123456")}
PARSER = {"config": ["config", "{v}"], "feature": ["feature", "{v}", "on"], "answer-id": ["answer", "{v}", "1"],
          "port": ["serve", "--port", "{v}"], "forget-ids": ["forget", "{v}"], "env-action": ["env", "{v}"],
          "proxy-port": ["proxy", "asks", "--port", "{v}"], "recall-n": ["recall", "-n", "{v}"]}


@pytest.mark.parametrize("where", PARSER)
@pytest.mark.parametrize("kind", PROSE)
def test_a_prose_secret_with_a_tab_or_newline_is_not_said_back_by_the_parser(where, kind, tmp_path, monkeypatch, capsys):   # must-refuse
    said, secret = PROSE[kind]
    work = start(tmp_path, monkeypatch, AGENT)
    code, out, err = run([a.replace("{v}", said) for a in PARSER[where]], capsys)
    assert code == 2
    assert not shown_in(err, secret) and not shown_in(out, secret)
    assert err.strip(), "an error still says that something was wrong"


# ---- the cut itself, and what it must leave alone ------------------------------------------------------------------
def test_the_cut_takes_every_spelling_of_a_value_in_any_case():                                   # must-refuse
    v = "Hunter22Secret"
    for spelled in (v, v.lower(), v.upper(), "x" + v + "y"):
        assert v.lower() not in cli._cut(f"bad {spelled} here", {v}).lower()
    p = "dir\\" + "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    k = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    for line in (f"no such folder: {p!r}", f"no such folder: {p}", f"bad {p.replace(chr(92), chr(92) * 2)}",
                 "bad \\u00e9" + k, ascii("é" + k), json.dumps("é" + k), repr("a\tb" + k)):
        assert k.lower() not in cli._cut(line, {k}).lower(), line


def test_a_non_ascii_value_is_cut_in_the_escaped_spellings_a_message_may_use():                    # must-refuse
    got = cli.secret_values(["config", "my password is pässwörd\U0001f600"])
    assert got == {"pässwörd\U0001f600"}
    v = next(iter(got))
    for line in (f"bad {v}", "bad " + ascii(v), "bad " + json.dumps(v), "bad " + repr(v), "bad " + v.upper(),
                 "bad " + json.dumps(v).replace("\\", "\\\\")):
        assert cli._cut(line, got) == "bad " + cli._NOT_REPEATED or cli._NOT_REPEATED in cli._cut(line, got), line
        assert "ssw" not in cli._cut(line, got).lower().replace("(a key-shaped value, not repeated)", ""), line


def test_the_values_are_the_secrets_not_the_words_around_them():                                 # must-pass
    got = cli.secret_values(["backtest", "--reader", "endpoint:https://bob:Hunter22Secret@api.example.com/v1#m"])
    assert "Hunter22Secret" in got and not any("api.example.com" in v or v == "bob" for v in got)
    assert cli.secret_values(["config", "my password\tis hunter22"]) == {"hunter22"}
    assert cli.secret_values(["read", "--env", "x/" + "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2" + "/"]) == {
        "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"}


@pytest.mark.parametrize("argv", [["toggle", "rule1"], ["read", "--env", "work", "hello world"],
                                  ["cases", "--export", "/tmp/pytest-of-someone/pytest-0/test_a_path0/out.jsonl"],
                                  ["recall", "password", "is", "a", "word"], ["teach", "token", "limits"]])
def test_an_ordinary_command_line_has_no_secret_in_it(argv):                                       # must-pass
    assert cli.secret_values(argv) == set()


def test_an_ordinary_wrong_word_is_still_named_beside_a_key(tmp_path, monkeypatch, capsys):          # must-pass
    work = start(tmp_path, monkeypatch, USER)
    k = K["openai"]
    code, out, err = run(["toggle", "nosuchrule"], capsys)
    assert code != 0 and "nosuchrule" in err
    code, out, err = run(["read", "--env", k, "hello"], capsys)
    assert code != 0 and k not in err and "no environment by that name" in err and "semantext env list" in err
    code, out, err = run(["backtest", "--reader", "endpoint:https://bob:Hunter22Secret@api.example.com/v1#m",
                          "nosuchfile.jsonl"], capsys)
    assert "hunter22secret" not in err.lower() and "nosuchfile" in err        # the rest of the line is still there


def test_a_value_is_cut_only_where_it_is_not_elsewhere_in_the_line():                              # must-pass
    k = K["gh"]
    line = f"no such folder 'projects' (typed {k}); try: semantext agents"
    cut = cli._cut(line, {k})
    assert "projects" in cut and "try: semantext agents" in cut and cli._NOT_REPEATED in cut and k not in cut


def test_stdout_is_cut_only_when_the_command_failed():                                              # must-pass and must-refuse
    k = K["gh"]
    for failed, want_key in ((True, False), (False, True)):
        sink = io.StringIO()
        held = cli._Cutting(sink, {k}, hold=True)
        held.write(f"saw {k}\n")
        held.write("more")
        assert sink.getvalue() == ""           # held until the command ends
        held.finish(failed)
        assert (k in sink.getvalue()) is want_key and "more" in sink.getvalue()


def test_stderr_is_cut_line_by_line_across_writes():                                                # must-refuse
    k = K["gh"]
    sink = io.StringIO()
    err = cli._Cutting(sink, {k})
    err.write("bad ")
    err.write(k[:10])
    err.write(k[10:] + "\nnext line ")
    assert k not in sink.getvalue() and "bad " in sink.getvalue()
    err.write(k)
    err.finish(True)                           # a last line without a newline is cut too
    assert k not in sink.getvalue() and sink.getvalue().endswith(cli._NOT_REPEATED)


def test_no_secret_typed_leaves_the_streams_alone(tmp_path, monkeypatch, capsys):                    # must-pass
    start(tmp_path, monkeypatch, USER)
    seen = []
    real = cli._main
    monkeypatch.setattr(cli, "_main", lambda argv, typed: (seen.append((__import__("sys").stdout, __import__("sys").stderr)),
                                                           real(argv, typed))[1])
    run(["rules"], capsys)
    import sys
    assert seen and not isinstance(seen[0][0], cli._Cutting) and not isinstance(seen[0][1], cli._Cutting)
    assert not isinstance(sys.stdout, cli._Cutting) and not isinstance(sys.stderr, cli._Cutting)


def test_the_streams_are_put_back_after_a_failing_command(tmp_path, monkeypatch, capsys):             # must-pass
    import sys
    start(tmp_path, monkeypatch, AGENT)
    before = sys.stdout, sys.stderr
    run(["toggle", K["gh"]], capsys)
    assert (sys.stdout, sys.stderr) == before


@pytest.mark.parametrize("word", ["hook", "mcp", "serve"])
def test_a_command_a_reader_waits_on_is_never_held(word):                                           # must-pass
    assert word in cli._STREAMING
