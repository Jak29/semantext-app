"""The typed-secret cut, round 5 (attack 25: L7 to L10). Each test failed on 3e5e2ac for the stated reason unless it is
marked must-pass.

L7  key=VALUE with a 4- or 5-character value and no tail (or a 1-character tail) was not collected at all, because the
    shared key check's arm needs 6 characters after "=". The cut collects it from 4, as the prose form does.
L8  the take-it-back line printed a key-shaped --home verbatim on the stdout of a command that worked, which is released
    uncut. It is printed as a placeholder, with a note in words.
L9  R10 made the JWT's match start at its run, so the backstop held lead+JWT only; a line printing the JWT without its
    glued lead was no longer cut. The JWT from its own "eyJ" is collected too.
L10 the module docstring's start window, and two stated limits of the printed line.
"""
from __future__ import annotations

import random
import re
import string
import time

import pytest

from semantext import cli, proxycmd
from semantext.inbox import SECRET

from test_owed_cut import AGENT, run, start
from tests.test_proxy_page import World, _proxies_end_with_the_test  # noqa: F401  (the autouse fixture that lets the locks go)

AID = "ask_0123456789ABCDEFGHJKMNPQRS"


# ---------------------------------------------------------------- L7: key=VALUE from 4 characters, with or without a tail
VALUES = ["abcd", "abcde", "abcdef", "Zq9x5", "12345", "Hunter22"]
TAILS = ["", "/", "/x", "/h/sub"]
KEYS = ["password=", "api_key=", "token=", "secret=", "passwd=", "passphrase=", "api-key="]


@pytest.mark.parametrize("tail", TAILS, ids=["none", "slash", "path", "deep"])
@pytest.mark.parametrize("value", VALUES)
def test_a_key_value_of_four_or_more_characters_is_collected_alone_whatever_follows(value, tail):   # must-refuse
    got = cli.secret_values(["--home", f"C:/T/password={value}{tail}", "rules"])
    assert value in got, got
    cut = cli._cut(f"[WinError 183] Cannot create a file: 'C:\\T\\password={value}'", got)
    assert value.lower() not in cut.lower() and cli._NOT_REPEATED in cut


@pytest.mark.parametrize("key", KEYS)
def test_every_key_word_collects_a_short_value(key):                                  # must-refuse
    assert cli.secret_values(["x", f"{key}abcde"]) == {"abcde"}


@pytest.mark.parametrize("argv", [["x", "password: abcde"], ["x", "password = abcde"], ["x", "Password:\tabcde"],
                                  ["--home", "C:/T/token=abcd/", "rules"]])
def test_the_spaced_and_colon_forms_are_collected_too(argv):                           # must-refuse
    assert {"abcde", "abcd"} & cli.secret_values(argv)


@pytest.mark.parametrize("argv", [["x", "token=ab"], ["x", "password=abc"], ["x", "token=/abc"], ["x", "token="],
                                  ["x", 'password="",x'], ["x", "my password is ab"], ["x", "no key here: abcd"],
                                  ["x", "tokens are great"], ["x", "abcde"]])
def test_a_value_too_short_or_a_line_with_no_key_word_collects_nothing(argv):          # must-pass (the stated limit)
    assert cli.secret_values(argv) == set()


def test_three_characters_before_a_tail_stay_inside_the_stated_limit():                 # must-pass
    got = cli.secret_values(["--home", "C:/T/password=abc/xyz", "rules"])
    assert "abc" not in got and "abc/xyz" in got


@pytest.mark.parametrize("typed, infile, value", [("password=abcde", "password=abcde", "abcde"),
                                                  ("password=abcd", "password=abcd", "abcd"),
                                                  ("api_key=12345", "api_key=12345", "12345"),
                                                  ("token=abcd/", "token=abcd", "abcd"),
                                                  ("secret=Zq9x5/", "secret=Zq9x5", "Zq9x5")])
def test_the_folder_message_does_not_print_a_value_with_no_tail_end_to_end(typed, infile, value, tmp_path, monkeypatch,
                                                                           capsys):   # must-refuse
    work = start(tmp_path, monkeypatch, AGENT)
    (work / infile).write_text("", encoding="utf-8")
    code, out, err = run(["--home", str(work / typed), "rules"], capsys)
    assert code not in (0, None), (code, out, err)
    assert cli._NOT_REPEATED in err, "the case does not reach a message that echoes the typed folder"
    assert value.lower() not in (out + err).lower(), err


def test_an_ordinary_folder_message_is_still_said(tmp_path, monkeypatch, capsys):          # must-pass
    work = start(tmp_path, monkeypatch, AGENT)
    (work / "plainfile").write_text("", encoding="utf-8")
    code, out, err = run(["--home", str(work / "plainfile"), "rules"], capsys)
    assert code not in (0, None) and "plainfile" in err and cli._NOT_REPEATED not in err


# ---------------------------------------------------------------- L8: a key-shaped home is not printed
KEYED_HOMES = ["C:/x/token=Zq9x5Wv8Ut7Sr6/h", "C:/x/password=abcde", "C:/x/api_key=12345/sub",
               "C:/x/sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2", "C:/x/ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3/h"]


@pytest.mark.parametrize("secret_home", KEYED_HOMES)
def test_the_line_does_not_repeat_a_key_shaped_home(secret_home):                         # must-refuse
    line = proxycmd.revoke_line(AID, None, secret_home)
    assert line == f'semantext --home "<your --home folder>" proxy answer {AID} revoke'
    assert not cli.secret_values([line])
    assert "looks like a key" in proxycmd.revoke_note(None, secret_home)


@pytest.mark.parametrize("secret_home", KEYED_HOMES)
def test_a_key_shaped_proxy_home_is_hidden_the_same_way(secret_home):                     # must-refuse
    line = proxycmd.revoke_line(AID, secret_home, "C:/ok")
    ok = proxycmd.shell_quote(str(__import__("pathlib").Path("C:/ok")))   # the machine's own spelling (attack 26, K2: not a Windows path)
    assert line == f'semantext --home {ok} proxy answer {AID} revoke --proxy-home "<your --proxy-home folder>"'
    assert "--proxy-home" in proxycmd.revoke_note(secret_home, "C:/ok") and "--home" not in proxycmd.revoke_note(secret_home, "C:/ok")[:22]


def test_both_hidden_are_both_named():                                                     # must-refuse
    note = proxycmd.revoke_note(KEYED_HOMES[1], KEYED_HOMES[0])
    assert "--home and --proxy-home" in note and "abcde" not in note and "Zq9x5" not in note


@pytest.mark.parametrize("folder", ["C:/x/my home", "C:/Users/you/.semantext", "/home/you/semantext", "C:/x/it's",
                                    "C:/x/test_the_printed_line_names_the_same_proxy_home_as_the_listing0",   # a long run with a digit
                                    "C:/x/tokens/h", "C:/x/password-manager/h", "C:/x/secrets/h"])
def test_an_ordinary_folder_is_printed_whole_and_has_no_note(folder):                      # must-pass
    line = proxycmd.revoke_line(AID, None, folder)
    assert line == f"semantext --home {proxycmd.shell_quote(str(__import__('pathlib').Path(folder)))} proxy answer {AID} revoke"
    assert "<" not in line and proxycmd.revoke_note(None, folder) == ""


def test_no_folder_given_prints_no_folder_and_no_note():                                    # must-pass
    assert proxycmd.revoke_line(AID, None, None) == f"semantext proxy answer {AID} revoke"
    assert proxycmd.revoke_note(None, None) == ""


def test_a_control_character_still_gives_no_line_even_in_a_key_shaped_folder():            # must-pass
    assert proxycmd.revoke_line(AID, None, "C:/x/token=Zq9x5Wv8Ut7Sr6\n/h") is None


def test_proxy_asks_in_a_key_shaped_home_does_not_say_it_on_stdout(tmp_path, monkeypatch, capsys):   # must-refuse
    import time as _t
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    h = tmp_path / "x" / "token=Zq9x5Wv8Ut7Sr6" / "h"
    assert cli.main(["--home", str(h), "init"]) == 0
    w = World(h)
    a = w.hold()
    assert w.asks.answer(a, "yes", _t.monotonic())
    capsys.readouterr()
    assert cli.main(["--home", str(h), "proxy", "asks"]) == 0                  # exit 0: stdout is released uncut
    out = capsys.readouterr().out
    assert "a yes not yet used" in out and "<your --home folder>" in out and "looks like a key" in out
    assert "Zq9x5Wv8Ut7Sr6" not in out and "zq9x5wv8ut7sr6" not in out.lower()


def test_proxy_asks_in_an_ordinary_home_still_prints_a_line_that_works(tmp_path, monkeypatch, capsys):   # must-pass
    import time as _t
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    h = tmp_path / "plain home"
    assert cli.main(["--home", str(h), "init"]) == 0
    w = World(h)
    a = w.hold()
    assert w.asks.answer(a, "yes", _t.monotonic())
    capsys.readouterr()
    assert cli.main(["--home", str(h), "proxy", "asks"]) == 0
    out = capsys.readouterr().out
    assert f"semantext --home '{h}' proxy answer {a} revoke" in out and "<" not in out and "looks like a key" not in out
    assert cli.main(["--home", str(h), "proxy", "answer", a, "revoke"]) == 0


# ---------------------------------------------------------------- L9: the JWT itself stays among the values cut
SHORT = "eyJhbGciOiJI.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4"            # the repo's own short test JWT
STD = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
       "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
LEADS = ["", "x", "x_", "Q9", "20", "Bearer_", "AKIAABCDEFGHIJKLMNOP", "eyJabc", "_-_"]
JWT_BASE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", re.I)   # the arm as 99f9116 had it


PLAIN_LEADS = ["", "x", "x_", "Q9", "20", "Bearer_", "_-_"]   # token characters with no "eyJ" of their own, and no key of their own


@pytest.mark.parametrize("lead", LEADS)
@pytest.mark.parametrize("jwt", [SHORT, STD], ids=["short", "standard"])
def test_a_jwt_printed_without_its_glued_lead_is_cut(jwt, lead):                           # must-refuse
    argv = ["read", "--env", lead + jwt]
    got = cli.secret_values(argv)
    if lead == "eyJabc":      # the lead's own "eyJ" is the leftmost, so the token is lead+token, as at 99f9116 (not narrower)
        assert lead + jwt in got
        return
    assert jwt in got, got
    out = cli._unkeyed(f"no such environment: {jwt}", argv)
    assert jwt.rsplit(".", 1)[1] not in out and cli._NOT_REPEATED in out


@pytest.mark.parametrize("lead", PLAIN_LEADS)
@pytest.mark.parametrize("jwt", [SHORT, STD], ids=["short", "standard"])
def test_the_lead_and_the_token_are_both_still_collected(jwt, lead):                       # must-pass (R10's wider cut stays)
    got = cli.secret_values(["read", "--env", lead + jwt])
    assert jwt in got and (lead + jwt in got)
    assert cli._NOT_REPEATED in cli._unkeyed(f"bad {lead}{jwt}", ["read", "--env", lead + jwt])
    assert jwt.rsplit(".", 1)[1] not in cli._unkeyed(f"bad {lead}{jwt}", ["read", "--env", lead + jwt])


def test_a_jwt_in_a_longer_word_is_cut_with_and_without_the_lead():                        # must-refuse
    word = "Authorization:Bearer_" + SHORT
    got = cli.secret_values(["x", word])
    assert SHORT in got
    assert SHORT.rsplit(".", 1)[1] not in cli._unkeyed("bad " + SHORT, ["x", word])


def test_every_jwt_the_base_arm_found_in_a_typed_word_is_still_collected():                # must-refuse (the attacker's differential)
    rnd = random.Random(2510)
    b64 = string.ascii_letters + string.digits + "_-"

    def seg(n):
        return "".join(rnd.choice(b64) for _ in range(n))
    seps = [" ", ".", "=", ":", "/", "\n", "é", "%", "\\", "'", '"', ",", ""]
    worse = checked = 0
    for _ in range(1500):
        parts = []
        for _ in range(rnd.randint(1, 5)):
            if rnd.random() < 0.6:
                parts.append(rnd.choice(LEADS) + "eyJ" + seg(rnd.randint(5, 40)) + "." + seg(rnd.randint(8, 40)) + "." + seg(rnd.randint(8, 43)))
            else:
                parts.append(seg(rnd.randint(1, 50)))
            parts.append(rnd.choice(seps))
        word = "".join(parts)
        got = cli.secret_values(["read", "--env", word])
        for m in JWT_BASE.finditer(word):
            checked += 1
            worse += m.group(0) not in got
    assert checked > 500
    assert worse == 0, f"{worse} of {checked} JWTs found by the base arm are no longer collected"


def test_a_jwt_glued_after_a_key_the_shared_check_has_already_taken_is_collected():          # must-refuse
    # AKIA + 16 characters are one SECRET match; the token behind them is not found by it (its arm needs a run boundary)
    word = "AKIAABCDEFGHIJKLMNOP" + SHORT
    assert not [m for m in SECRET.finditer(word) if SHORT in m.group(0)]
    assert SHORT in cli.secret_values(["x", word])


@pytest.mark.parametrize("word", ["eyJa" * 5000, "eyJé" * 5000, ("eyJaaaaaaaaaa." * 2000), ("eyJ" + "a" * 20000),
                                  " ".join(["eyJaaaaaaaaaaaa.bbbbbbbbbbb"] * 1200)],
                         ids=["eyJa-x5000", "eyJe-acute-x5000", "eyJ-dot-x2000", "eyJ-a-x20000", "spaced-pairs-x1200"])
def test_collecting_a_hostile_line_of_eyj_is_linear(word):                                  # must-refuse (the R10 shape)
    t0 = time.perf_counter()
    cli.secret_values(["read", "--env", word])
    took = time.perf_counter() - t0
    assert took < 0.5, took


@pytest.mark.parametrize("word", ["eyJhbGciOiJI.eyJzdWIiOiIxMjM0", "eyJhbGciOiJI eyJzdWIiOiIxMjM0 SflKxwRJSMeKKF2QT4",
                                  "eyJshort.eyJshort.eyJshort", "plain words eyJ"])
def test_a_word_that_is_not_a_jwt_collects_nothing(word):                                  # must-pass
    assert cli.secret_values(["x", word]) == set()


def test_the_jwt_arm_is_still_the_shared_one():                                            # must-pass: the test above follows SECRET
    assert SECRET.search("Bearer_" + SHORT) and SECRET.search(SHORT)


# ---------------------------------------------------------------- L10: the stated limits
def test_the_module_docstring_states_the_start_window():                                   # must-refuse
    doc = proxycmd.__doc__
    assert "residual window" in doc and "serve.lock" in doc and "atomic write" in doc and "68.8" in doc
    assert "nothing\nof the run before it is listed or answered in between," in doc


def test_revoke_line_states_its_shell_limits():                                            # must-refuse
    doc = proxycmd.revoke_line.__doc__
    assert "cmd.exe" in doc and "UNC" in doc and "looks like a key" in doc


# ---------------------------------------------------------------- cost: per call, per answer
def test_the_cost_of_collecting_and_of_the_line_is_small():                                # budget: under 5 ms per call
    argv = ["--home", "C:/Users/you/some/long/path/with/many/parts/token=abcd/x", "rules", "read", "--env", STD, "hello " * 50]
    t0 = time.perf_counter()
    for _ in range(100):
        cli.secret_values(argv)
    per_values = (time.perf_counter() - t0) / 100
    t0 = time.perf_counter()
    for _ in range(100):
        proxycmd.revoke_line(AID, "C:/p", "C:/x/token=Zq9x5Wv8Ut7Sr6/h")
    per_line = (time.perf_counter() - t0) / 100
    assert per_values < 0.005 and per_line < 0.005, (per_values, per_line)
