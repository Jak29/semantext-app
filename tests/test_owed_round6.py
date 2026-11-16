"""The typed-secret cut, round 6 (attack 26: K1 to K5 and the placeholder). Each test failed on 6d26c20 for the stated
reason unless it is marked must-pass.

K1  _jwts was quadratic on a run of "eyJ" glued by a character the re module reads as a letter under re.I.
K3  a key that holds e-y-j, or a key glued before a token, left the token (or the key) printed alone.
K4  key=VALUE of 4 or 5 characters with a "#", "(", "&" ... among its first four was not collected.
K5  a short value that ends where a key begins took the cut and the rest of the key was printed.
K6  the hidden-folder placeholder was a redirection when pasted unedited into cmd.exe or a POSIX shell.
"""
from __future__ import annotations

import pytest

from semantext import cli, proxycmd

AID = "ask_0123456789ABCDEFGHJKMNPQRS"
SHORT = "eyJhbGciOiJI.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4"
KEY = "sk-A1b2C3d4E5f6G7h8I9j0K1l2"


# ---------------------------------------------------------------- K1: linear, counted (not timed)
class _Counting:
    def __init__(self, real):
        self.real, self.calls = real, 0

    def match(self, *a, **kw):
        self.calls += 1
        return self.real.match(*a, **kw)


@pytest.mark.parametrize("glue", [chr(0x212A), chr(0x17F), chr(0x131), chr(0x130), "a"], ids=["kelvin", "longs", "dotless", "dotted", "ascii"])
def test_a_hostile_run_of_eyj_is_tried_a_few_times_not_once_per_eyj(glue, monkeypatch):   # must-refuse
    counter = _Counting(cli._JWT_OWN)
    monkeypatch.setattr(cli, "_JWT_OWN", counter)
    cli.secret_values(["read", "--env", ("eyJ" + glue) * 5000])
    assert counter.calls <= 4 * cli._EYJ_TRIES, counter.calls


def test_a_plain_token_is_still_found_by_the_collector():                                 # must-pass
    assert cli._jwts("x " + SHORT + " y") == [SHORT]
    assert cli._jwts("eyJabc") == []


# ---------------------------------------------------------------- K3: the token and the key, each alone
LEADS = ["AKIAEYJABCDEFGHIJKLM", "akiaxxeyjxxxxxxxxxxx", "AIza" + "A" * 10 + "eYj" + "A" * 22, "ghp_AbAbAbAbAbEyJCdCdCdCdCdCd_",
         "sk_live_ZzZzZzZzeyjZzZzZzZzZz-", "hf_" + "Q" * 10 + "EYJ" + "Q" * 20 + "_", "xoxb-11111eyj11111_"]


@pytest.mark.parametrize("lead", LEADS)
def test_a_token_glued_after_a_key_that_holds_eyj_is_cut_alone(lead):                      # must-refuse
    values = cli.secret_values(["read", "--env", lead + SHORT])
    cut = cli._cut(f"no such environment: {SHORT} .", values)
    assert "SflKxwRJSMeKKF2QT4" not in cut and cli._NOT_REPEATED in cut


@pytest.mark.parametrize("prefix", ["id_", "x-", ""])
@pytest.mark.parametrize("sep", ["_", "-", "."])
def test_a_key_glued_before_a_token_is_cut_alone(prefix, sep):                              # must-refuse
    values = cli.secret_values(["read", "--env", f"{prefix}{KEY}{sep}{SHORT}"])
    cut = cli._cut(f"said: {KEY} .", values)
    assert "A1b2C3d4E5f6G7h8I9j0K1l2" not in cut


def test_the_standard_token_and_a_plain_word_are_unchanged():                               # must-pass
    std = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
           "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
    assert std in cli.secret_values(["read", "--env", std])
    assert cli.secret_values(["read", "--env", "honeyjar_and_other_words"]) == set()


# ---------------------------------------------------------------- K4: short values with a delimiter among the first four
@pytest.mark.parametrize("value", ["a#bcd", "#abcd", "ab&cd", "(abc)", "[key]", "{a1b}", "<pw1>", "a,bcd", "ab;cd", "ab'cd",
                                   "1,234", "a/bcd", "#abc"])
@pytest.mark.parametrize("key", ["password=", "token=", "api_key=", "secret: "])
def test_a_short_value_with_a_delimiter_early_is_collected(key, value):                     # must-refuse
    got = cli.secret_values(["x", key + value])
    cut = cli._cut(f"cannot use '{value}' here", got)
    assert value.lower() not in cut.lower() and cli._NOT_REPEATED in cut, got


@pytest.mark.parametrize("argv", [["x", "token=/abc"], ["x", 'password="",x'], ["x", "token=ab"], ["x", "password=#ab"],
                                  ["x", "token=;abc"], ["x", "no key here: #abcd"]])
def test_a_path_an_empty_value_or_too_short_collects_nothing(argv):                         # must-pass (the stated limit)
    assert cli.secret_values(argv) == set()


def test_end_to_end_the_folder_message_does_not_print_it(tmp_path, monkeypatch, capsys):    # must-refuse
    from test_owed_cut import AGENT, run, start
    work = start(tmp_path, monkeypatch, AGENT)
    (work / "password=#abcd").write_text("", encoding="utf-8")
    code, out, err = run(["--home", str(work / "password=#abcd"), "rules"], capsys)
    assert code not in (0, None) and cli._NOT_REPEATED in err and "#abcd" not in out + err, err


# ---------------------------------------------------------------- K5: overlapping forms are cut as their union
@pytest.mark.parametrize("n", [1, 2, 3])
def test_a_short_value_running_into_a_key_does_not_leave_the_rest_of_the_key(n):            # must-refuse
    short = "zzz" + KEY[:n]
    cut = cli._cut(f"cannot use zzz{KEY} here", cli.secret_values(["x", f"token={short}", "--env", KEY]))
    assert KEY[n:n + 8] not in cut and "cannot use" in cut and "here" in cut


def test_forms_that_do_not_overlap_are_cut_apart(): # must-pass
    cut = cli._cut("a abcd b wxyz c", {"abcd", "wxyz"})
    assert cut == f"a {cli._NOT_REPEATED} b {cli._NOT_REPEATED} c"


def test_a_form_inside_a_longer_one_is_one_cut():                                             # must-pass
    cut = cli._cut("see abcdefgh now", {"abcd", "abcdefgh"})
    assert cut == f"see {cli._NOT_REPEATED} now"


# ---------------------------------------------------------------- K6: the placeholder is not a redirection
def test_the_placeholder_is_quoted_so_a_pasted_line_redirects_nothing():                      # must-refuse
    line = proxycmd.revoke_line(AID, "C:/x/token=Zq9x5Wv8Ut7Sr6/h", "C:/x/password=abcde")
    assert '"<your --home folder>"' in line and '"<your --proxy-home folder>"' in line
    assert " <your" not in line and " >" not in line


def test_an_ordinary_line_has_no_angle_bracket():                                              # must-pass
    assert "<" not in proxycmd.revoke_line(AID, "C:/x/ok", "C:/x/home")
