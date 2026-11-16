"""An environment is never named like a key; one that already is stays reachable (attack 22, O5).

Since the first backstop no command could name an environment whose title looked like a key ("no environment by that
name" while `env list` showed it). `env new` now refuses such a title, saying why and not repeating it, and an existing
environment whose slug is key-shaped is found by its slug, without the typed word being said back.

Must-pass: an ordinary title, one that holds the word "password" or "token", is made. Must-refuse: a key-shaped title,
in any of the shapes, makes no environment and is not repeated; a key-shaped word that names nothing is not repeated and
gets no near-miss hint.
"""
from __future__ import annotations

import pytest

from semantext import cli
from semantext.store import Refused, Store

KEY_TITLE = "sk-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
KEY_SLUG = KEY_TITLE.lower()


def _folders(store):
    return sorted(p.name for p in store.profiles_dir.iterdir())


@pytest.mark.parametrize("title", [KEY_TITLE, "AKIA" + "ABCDEFGHIJKLMNOP", "password is hunter22", "passphrase was Zebra77",
                                   "Xk9a8Zq7Lm2Pw4Rt6Yu1Io3Ee5Dc0Vb9Nn8Mm7Q"])
def test_a_key_shaped_title_makes_no_environment_and_is_not_repeated(title, store):          # must-refuse
    before = _folders(store)
    with pytest.raises(Refused) as e:
        store.create(title, [])
    said = str(e.value)
    assert "looks like it holds a key" in said and title not in said and title.lower() not in said.lower()
    assert _folders(store) == before


@pytest.mark.parametrize("title", ["Gardening", "Password manager", "Token economy", "Secret santa", "Key lime pie"])
def test_an_ordinary_title_is_still_made(title, store):                                       # must-pass
    name = store.create(title, [])
    assert store.resolve(name) == name and store.resolve(title) == name


def test_env_new_refuses_a_key_title_at_the_console_without_saying_it(home, capsys):         # must-refuse
    cli.main(["init"])
    capsys.readouterr()
    assert cli.main(["env", "new", "--none", KEY_TITLE]) == 1
    seen = capsys.readouterr()
    assert "looks like it holds a key" in seen.err
    assert KEY_TITLE not in seen.err + seen.out and KEY_TITLE.lower() not in (seen.err + seen.out).lower()
    assert cli.main(["env", "list"]) == 0
    assert "sk-" not in capsys.readouterr().out                                               # nothing was made


@pytest.fixture
def old_key_env(store, monkeypatch):
    """An environment made before the rule, titled like a key: made with the check off."""
    with monkeypatch.context() as m:
        m.setattr("semantext.agents.key_shaped", lambda name: False)
        return store.create(KEY_TITLE, [])


def test_the_test_fixture_made_a_key_shaped_slug(old_key_env):                                  # guards the fixture itself
    assert old_key_env == KEY_SLUG


def test_an_existing_key_named_environment_is_found_by_its_slug(old_key_env, store, home, capsys):   # must-pass
    assert store.resolve(old_key_env) == old_key_env
    capsys.readouterr()
    assert cli.main(["rules", "--env", old_key_env]) == 0
    assert cli.main(["where", "--env", old_key_env]) == 0
    assert cli.main(["env", "use", old_key_env]) == 0
    assert store.state()["active"] == old_key_env


def test_a_key_that_names_nothing_is_not_repeated_and_gets_no_hint(old_key_env, store, home, capsys):   # must-refuse
    near = old_key_env + "x"
    with pytest.raises(Refused) as e:
        store.resolve(near)
    assert near not in str(e.value) and "did you mean" not in str(e.value) and "no environment by that name" in str(e.value)
    capsys.readouterr()
    assert cli.main(["rules", "--env", near]) == 1
    seen = capsys.readouterr()
    assert near not in seen.err + seen.out and old_key_env not in seen.err + seen.out


def test_an_ordinary_unknown_name_is_still_named_with_its_hint(store):                         # must-pass
    store.create("Gardening", [])
    with pytest.raises(Refused) as e:
        store.resolve("gardenin")
    assert "'gardenin'" in str(e.value) and "did you mean gardening" in str(e.value)
