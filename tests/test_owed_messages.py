"""`_users_act` keeps one guard for every act of the user's, but what it says after the refusal fits the act: starting
or answering the proxy no longer says "Only the user changes their rules".

Must-pass: the person's own terminal still passes every act. Must-refuse: an agent's shell is still refused for every
act, with the words of that act.
"""
from __future__ import annotations

import pytest

from semantext import cli
from semantext.store import Refused

AGENT = "this is an agent's shell"


def key() -> str:
    """A key-shaped word, made here so no key sits in the source."""
    return "sk-" + "a1b2c3d4" * 4


@pytest.mark.parametrize("what", sorted(cli._ACT_SAID))
def test_every_act_is_still_refused_in_an_agents_shell(what, monkeypatch):      # must-refuse
    monkeypatch.setattr(cli, "human_terminal", lambda: AGENT)
    with pytest.raises(Refused) as e:
        cli._users_act(what)
    said = str(e.value)
    assert said.startswith(f"cannot {what} here: {AGENT}. ")
    assert said.endswith(cli._ACT_SAID[what])


@pytest.mark.parametrize("what", sorted(cli._ACT_SAID) + ["switch environments", "add rules", "pin a rule"])
def test_every_act_passes_at_the_persons_own_terminal(what, monkeypatch):       # must-pass
    monkeypatch.setattr(cli, "human_terminal", lambda: None)
    assert cli._users_act(what) is None


def test_the_proxy_acts_do_not_talk_about_rules(monkeypatch):
    monkeypatch.setattr(cli, "human_terminal", lambda: AGENT)
    for what, word in (("start the proxy", "starts the proxy"), ("answer the proxy", "answers what the proxy holds")):
        with pytest.raises(Refused) as e:
            cli._users_act(what)
        assert word in str(e.value) and "changes their rules" not in str(e.value)


def test_a_rule_act_keeps_its_old_words(monkeypatch):
    """The acts that change rules say what they always said."""
    monkeypatch.setattr(cli, "human_terminal", lambda: AGENT)
    for what in ("switch environments", "make an environment", "add rules", "switch a rule", "pin a rule", "undo a rule"):
        with pytest.raises(Refused) as e:
            cli._users_act(what)
        assert str(e.value).endswith(cli._RULES_SAID) and "Only the user changes their rules" in str(e.value)


def test_the_proxy_commands_say_it_through_the_command_line(home, monkeypatch, capsys):   # must-refuse
    monkeypatch.setattr(cli, "human_terminal", lambda: AGENT)
    cli.main(["--home", str(home), "init"])
    capsys.readouterr()
    assert cli.main(["--home", str(home), "proxy", "answer", "abc", "yes"]) == 1
    err = capsys.readouterr().err
    assert "cannot answer the proxy here" in err and "changes their rules" not in err
    assert cli.main(["--home", str(home), "proxy", "serve", "--space", str(home)]) == 1
    err = capsys.readouterr().err
    assert "cannot start the proxy here" in err and "changes their rules" not in err
