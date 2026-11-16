"""`semantext read --act VALUE`, and any other argument argparse quotes in an error, never prints a key-shaped value.

Must-pass: a real act still reads, repeatably; an ordinary wrong word is still named by argparse where it is not a key.
Must-refuse: a key-shaped word is refused and not repeated, in `--act` and in every other place argparse quotes.
"""
from __future__ import annotations

import pytest

from semantext import cli, reading


def key() -> str:
    """A key-shaped word, made here so no key sits in the source."""
    return "sk-" + "a1b2c3d4" * 4


# ---- a key typed where argparse would quote it --------------------------------------------------------------------
def test_read_act_never_prints_a_key(home, capsys):                              # must-refuse
    k = key()
    with pytest.raises(SystemExit) as e:
        cli.main(["--home", str(home), "read", "--act", k, "publish it"])
    assert e.value.code == 2
    seen = capsys.readouterr()
    assert k not in seen.err and k not in seen.out and "sk-" not in seen.err


def test_read_act_refuses_a_plain_wrong_word_without_repeating_it(home, capsys):  # must-refuse
    with pytest.raises(SystemExit) as e:
        cli.main(["--home", str(home), "read", "--act", "frobnicate", "publish it"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "frobnicate" not in err and "not an act the reader knows" in err
    assert all(a in err for a in reading.ACTS)          # it says which acts there are


def test_read_act_still_takes_every_real_act(home, capsys):                      # must-pass
    cli.main(["--home", str(home), "init"])
    for act in reading.ACTS:
        capsys.readouterr()
        assert cli.main(["--home", str(home), "read", "--act", act, "publish it"]) == 0
        assert capsys.readouterr().out.count(f"{act}: ") == 1


def test_read_act_is_repeatable(home, capsys):                                   # must-pass
    cli.main(["--home", str(home), "init"])
    first, second = list(reading.ACTS)[:2]
    capsys.readouterr()
    assert cli.main(["--home", str(home), "read", "--act", first, "--act", second, "publish it"]) == 0
    out = capsys.readouterr().out
    assert f"{first}: " in out and f"{second}: " in out


@pytest.mark.parametrize("argv", [
    ["proxy", "{k}"],                  # an invalid choice in a positional
    ["{k}"],                           # an invalid command
    ["read", "x", "--bogus={k}"],      # an unrecognised argument
    ["model", "{k}"],
])
def test_no_argparse_error_repeats_a_key(argv, home, capsys):                    # must-refuse
    k = key()
    with pytest.raises(SystemExit) as e:
        cli.main(["--home", str(home), *[a.replace("{k}", k) for a in argv]])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert k not in err and "sk-a1b2" not in err
    assert "looks like it holds a key" in err


def test_an_ordinary_argparse_error_still_names_the_word(home, capsys):          # must-pass: only keys are scrubbed
    with pytest.raises(SystemExit):
        cli.main(["--home", str(home), "proxy", "frobnicate"])
    assert "frobnicate" in capsys.readouterr().err
