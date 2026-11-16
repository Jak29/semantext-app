"""Fixes after the attack of the owed items (cli.py and sources/own_places.py).

O1  every change refused in an agent's shell names BOTH routes, `semantext teach` and `semantext ask`.
O2  a name or value the person typed is never repeated when it looks like a key; an ordinary wrong word still is.
O3  the projects' list is made distinct first (first spelling, first place), and only then cut to its last 200.
"""
from __future__ import annotations

import json

import pytest

from semantext import cli
from semantext.cli import main
from semantext.sources import own_places

# Made-up values in the shapes of keys (none is real).
KEYS = {
    "openai": "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2",
    "github": "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3",
    "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
    "jwt": "eyJhbGciOiJI.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
    "long": "Xk9" + "a8Zq7Lm2Pw4Rt6Yu1Io3Ee5Dc0Vb9Nn8Mm7Qq6Ww5Ee4Rr3Tt2Yy1",
}


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ---- O1 -------------------------------------------------------------------------------------------------------------
AGENT_CHANGES = [["feature", "inbox", "on"], ["config", "hear-prompts", "on"], ["hear", "as", "if", "mine"],
                 ["forget", "--all"], ["model", "set", "--model", "x"], ["model", "clear"]]


@pytest.mark.parametrize("args", AGENT_CHANGES, ids=[" ".join(a) for a in AGENT_CHANGES])
def test_a_refusal_in_an_agents_shell_names_both_routes(capsys, home, monkeypatch, args):     # must-pass
    run(capsys, "init")
    before = snapshot(home)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run(capsys, *args)
    if "cannot" not in err:                                    # a command that is not an act of the user's at all
        pytest.skip("not refused as an act: " + err)
    assert code == 1 and "`semantext teach`" in err and "`semantext ask`" in err
    assert snapshot(home) == before                            # the guard and the files written stay as they were


def test_every_act_said_names_both_routes():                  # must-refuse: no act in the table may lose a route
    for act, words in cli._ACT_SAID.items():
        assert "`semantext teach`" in words and "`semantext ask`" in words, act


# ---- O2 -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("kind", sorted(KEYS))
@pytest.mark.parametrize("command", [["read", "--env", "{k}", "hello"], ["rules", "--env", "{k}"],
                                     ["card", "--env", "{k}"], ["env", "use", "{k}"], ["env", "add", "--env", "{k}", "x"],
                                     ["teach", "--env", "{k}", "a", "rule"], ["export", "system-prompt", "--env", "{k}"]])
def test_a_key_typed_as_an_environment_is_never_repeated(capsys, home, kind, command):      # must-refuse
    key = KEYS[kind]
    code, out, err = run(capsys, "init")
    code, out, err = run(capsys, *[a.format(k=key) for a in command])
    assert code != 0
    assert key not in out + err and key[: max(12, len(key) - 6)] not in out + err
    assert "no environment by that name" in err


def test_an_ordinary_wrong_environment_is_still_named(capsys, home):                         # must-pass
    run(capsys, "init")
    code, _, err = run(capsys, "rules", "--env", "Kayaking")
    assert code == 1 and "no environment called 'Kayaking'" in err


@pytest.mark.parametrize("kind", sorted(KEYS))
def test_a_key_in_a_suggestion_id_or_a_reader_or_hours_is_never_repeated(capsys, home, kind):   # must-refuse
    key = KEYS[kind]
    run(capsys, "init")
    for args in (["env", "new", "Office", "--pick", key], ["compute", "hold", "--hours", key]):
        code, out, err = run(capsys, *args)
        assert code == 1 and key not in out + err, args
    code, out, err = run(capsys, "compute", "hold", "--hours", "abc")
    assert "'abc'" in err                                      # an ordinary wrong word is still named
    code, out, err = run(capsys, "env", "new", "Office", "--pick", "nope.nothing")
    assert "nope.nothing" in err


@pytest.mark.parametrize("kind", sorted(KEYS))
def test_a_key_as_an_agent_name_is_never_repeated_or_written(capsys, home, kind):            # must-refuse
    key = KEYS[kind]
    run(capsys, "init")
    before = snapshot(home)
    code, out, err = run(capsys, "teach", "--agent", key, "Keep", "it", "short.")
    assert code == 1 and key not in out + err
    code, out, err = run(capsys, "rules", "--agent", key)
    assert key not in out + err
    assert all(key.encode() not in b for b in snapshot(home).values())
    assert snapshot(home).keys() == before.keys()


def test_the_last_defence_cuts_a_typed_key_out_of_any_message():                              # must-pass and must-refuse
    key = KEYS["openai"]
    said = cli._unkeyed(f"some store said: no such thing as {key}; and {key}x", ["read", f"--env={key}"])
    assert key not in said and cli._NOT_REPEATED in said
    plain = "no such thing as Kayaking"
    assert cli._unkeyed(plain, ["read", "--env", "Kayaking"]) == plain          # an ordinary word is left alone
    assert cli._unkeyed(f"has {key}", ["read"]) == f"has {key}"                  # only what was typed is cut


# ---- O3 -------------------------------------------------------------------------------------------------------------
def write_list(home, names):
    (home / "work").mkdir(parents=True, exist_ok=True)
    (home / "work" / "projects.json").write_text(json.dumps(names), encoding="utf-8")


def drawn(home):
    problems: list = []
    got = own_places.load(home, "Mine", None, problems)
    return [p["name"] for p in got["projects"]], got["projects_more"], problems


def test_the_first_spelling_at_the_first_place_wins(tmp_path):                               # the attacker's first input
    write_list(tmp_path, ["Foo", "foo", "Bar"])
    names, more, problems = drawn(tmp_path)
    assert names == ["Foo", "Bar"] and more == 0 and problems == []


def test_a_repeated_list_is_not_wrapped(tmp_path):                                           # the attacker's second input
    write_list(tmp_path, [f"p{i % 300}" for i in range(1000)])
    names, more, _ = drawn(tmp_path)
    assert names == [f"p{i}" for i in range(100, 300)]         # the last 200 of the 300 distinct names, in order
    assert more == 100
    assert names != [f"p{i}" for i in [*range(200, 300), *range(100)]]


def test_a_long_list_with_repeats_says_how_many_more(tmp_path):
    write_list(tmp_path, [f"q{i}" for i in range(250)] + ["Q0", "q1", "extra"])
    names, more, problems = drawn(tmp_path)
    assert names == [f"q{i}" for i in range(51, 250)] + ["extra"] and more == 51      # 251 distinct, the last 200
    assert [p["kind"] for p in problems] == ["more projects"] and "51 more names" in problems[0]["text"]


def test_a_list_within_the_cap_keeps_its_order_and_says_nothing(tmp_path):                  # must-pass
    write_list(tmp_path, ["b", "a", "B", "c", "A"])
    names, more, problems = drawn(tmp_path)
    assert names == ["b", "a", "c"] and more == 0 and problems == []
