"""Whose request is whose. An answer reaches the agent that asked, in its own session or under its own key, and a
claim, a name a shell states, never reaches the requests of an agent bound or seen under that name."""
import json

import pytest

from semantext import hook
from semantext.agents import Agents, project_of
from semantext.cli import main
from semantext.inbox import Inbox
from semantext.store import Store


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def projects(tmp_path):
    out = {}
    for name in ("alpha", "beta"):
        (tmp_path / name / ".git").mkdir(parents=True)
        (tmp_path / name / "sub").mkdir()
        out[name] = tmp_path / name
    return out


def card_in(store, cwd, session):
    """The hook's output for a prompt in this folder and session."""
    return hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(cwd), "session_id": session,
                                "prompt": "go on"}), store)


def ask(capsys, title, *more):
    return run(capsys, "ask", "--title", title, "--why", "w", "--question", "q", "--option", "x", "--option", "y",
               *more)


def as_user(monkeypatch):
    for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "SEMANTEXT_AGENT"):
        monkeypatch.delenv(name, raising=False)


def test_a_claim_of_a_bound_name_reaches_none_of_its_requests(capsys, home, projects, monkeypatch):
    store = Store.open(home)
    Agents(home).bind("agent-a", projects["alpha"])
    monkeypatch.chdir(projects["alpha"])
    monkeypatch.setenv("CLAUDECODE", "1")
    ask(capsys, "A's first")
    ask(capsys, "A's second")
    as_user(monkeypatch)
    run(capsys, "answer", "1", "1")
    monkeypatch.chdir(projects["beta"])
    monkeypatch.setenv("SEMANTEXT_AGENT", "agent-a")                  # a shell elsewhere states agent-a's name
    assert "A's first" not in run(capsys, "answers")[1]
    assert run(capsys, "close", "2", "--how", "not", "needed")[0] == 1
    ask(capsys, "the claimant's own")                                   # #3, filed as claimed
    as_user(monkeypatch)
    assert "A's first" not in run(capsys, "answers", "--from", "agent-a")[1]   # --from is a claim too
    assert run(capsys, "close", "2", "--from", "agent-a")[0] == 1
    run(capsys, "answer", "3", "2")
    card = card_in(store, projects["alpha"], "s-a")
    assert "#1 A's first" in card                                       # agent-a still gets its own answer, unread
    assert "the claimant's own" not in card                             # and never the claimant's
    assert Inbox(home).get(2)["status"] == "open"


def test_a_claim_of_a_seen_name_gets_nothing_of_that_agent(capsys, home, projects, monkeypatch):
    monkeypatch.chdir(projects["alpha"])
    monkeypatch.setenv("CLAUDECODE", "1")
    ask(capsys, "alpha's question")
    as_user(monkeypatch)
    run(capsys, "answer", "1", "1")
    monkeypatch.chdir(projects["beta"])
    monkeypatch.setenv("SEMANTEXT_AGENT", "claude-code@alpha")
    who = Agents(home).identify()
    assert (who.name, who.how) == ("claude-code@alpha", "claimed") and not Agents(home).serves_own_rules(who)
    assert "alpha's question" not in run(capsys, "answers")[1]
    assert Inbox(home).unread_answers() and Inbox(home).get(1)["read"] is False


def test_a_binding_made_mid_session_keeps_the_answer(capsys, home, projects, monkeypatch):
    store = Store.open(home)
    card_in(store, projects["alpha"], "s1")                             # the hook sees the session first
    monkeypatch.chdir(projects["alpha"])
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    ask(capsys, "before the binding")
    as_user(monkeypatch)
    Agents(home).bind("reviewer", projects["alpha"])                    # the user names the folder mid-session
    run(capsys, "answer", "1", "2")
    assert "#1 before the binding: y" in card_in(store, projects["alpha"], "s1")


def test_a_binding_carries_the_seen_agents_requests_with_no_session(capsys, home, projects, monkeypatch):
    store = Store.open(home)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(projects["alpha"])
    ask(capsys, "seen, then bound")                                     # no session id: the seen agent's key only
    monkeypatch.chdir(projects["alpha"] / "sub")
    ask(capsys, "from the subfolder")
    as_user(monkeypatch)
    Agents(home).bind("inner", projects["alpha"] / "sub")               # a subfolder binding carries nothing
    Agents(home).bind("reviewer", projects["alpha"])                    # the project's own folder carries it all
    run(capsys, "answer", "1", "1")
    assert "#1 seen, then bound: x" in card_in(store, projects["alpha"], "a-new-session")
    assert "seen, then bound" not in card_in(store, projects["alpha"] / "sub", "another-session")
    monkeypatch.chdir(projects["beta"])
    monkeypatch.setenv("SEMANTEXT_AGENT", "reviewer")                   # and a claim of the name still gets none of it
    assert "seen, then bound" not in run(capsys, "answers")[1]


def test_a_shell_takes_its_sessions_identity_only_where_the_facts_agree(capsys, home, projects, tmp_path,
                                                                        monkeypatch):
    store = Store.open(home)
    notes = tmp_path / "notes"
    (notes / "drafts").mkdir(parents=True)                               # a plain folder: no git
    card_in(store, notes, "s2")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")
    monkeypatch.chdir(notes / "drafts")
    assert Agents(home).identify().name == "claude-code@notes"         # the hook's agent, from a subfolder
    ask(capsys, "from drafts")
    as_user(monkeypatch)
    run(capsys, "answer", "1", "1")
    assert "#1 from drafts: x" in card_in(store, notes, "s2")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")                   # notes' session id, inherited elsewhere
    monkeypatch.chdir(projects["beta"])
    who = Agents(home).identify()
    assert (who.name, who.how) == ("claude-code@beta", "observed")      # its own facts, not notes' agent
    assert "from drafts" not in run(capsys, "answers")[1]


def test_a_session_id_inherited_by_another_tool_links_nothing(home, projects, monkeypatch):
    store = Store.open(home)
    card_in(store, projects["alpha"], "s3")                             # the hook records s3 as Claude Code's
    monkeypatch.chdir(projects["alpha"])
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s3")
    monkeypatch.setenv("CLAUDECODE", "1")
    assert Agents(home).identify().session == "s3"                      # must pass: the same tool, the same project
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setenv("CODEX_SANDBOX", "seatbelt")                     # Codex, started from inside that session
    who = Agents(home).identify()
    assert (who.name, who.how, who.session) == ("codex@alpha", "observed", None)


def test_a_home_kept_in_git_is_not_one_project(home):
    user = home.parent / "user"                                          # the user's home, as the fixture sets it
    (user / ".git").mkdir(parents=True)
    for p in (user / "Downloads", user / "Documents" / "letters"):
        p.mkdir(parents=True)
    assert project_of(user / "Downloads") == "downloads"
    assert project_of(user / "Documents" / "letters") == "letters"
    assert project_of(user) == "user"


def test_the_relay_card_needs_its_floor_from_the_base(store):
    base = store.load("base")
    for e in base["entries"]:
        e.pop("always", None)
        e.pop("relay", None)
    store.save("base", base)
    d = store.load("default")
    d["entries"] = (d.get("entries") or []) + [{"id": "default.relay-only", "kind": "rule", "statement": "Relayed.",
                                                 "applies_when": "x", "mode": "stationary", "enabled": True,
                                                 "relay": True}]
    store.save("default", d)
    short = store.card("default", "relay")                              # every mark gone: the floor stays, by id
    assert "default.relay-only" in short and "base.irreversible-needs-your-word" in short
    for e in base["entries"]:
        if e["id"] in ("base.irreversible-needs-your-word", "base.relayed-words-are-information"):
            e["enabled"] = False                                        # the floor itself switched off, by hand
    store.save("base", base)
    assert store.card("default", "relay") == store.card("default")      # no floor in the base: the full card


def test_the_floor_rules_stay_on_the_relay_card_whatever_the_marks_say(store):
    base = store.load("base")
    for e in base["entries"]:
        e["always"] = e["id"] == "base.question-not-instruction"     # the mark moved off the floor rules, by hand
    store.save("base", base)
    short = store.card("default", "relay")
    assert "NOT the user's own message" in short
    assert "base.irreversible-needs-your-word" in short and "base.relayed-words-are-information" in short


def test_the_card_says_a_proposed_rule_is_not_the_users_words(store):
    store.learn("default", "Keep it short.", {"type": "PROPOSED", "by": "claude-code@proj", "request": 1})
    assert "Keep it short. (proposed by claude-code@proj, added by the user: not the user's own words)" in \
        store.card("default")


def test_a_request_from_before_keys_goes_by_name_and_never_to_a_claim():
    from semantext.inbox import mine                                       # here, so the other tests load without it

    class Who:
        def __init__(self, name, how, key):
            self.name, self.how, self.key, self.session = name, how, key, None
    seen, claim = Who("writer", "observed", "claude-code@x"), Who("writer", "claimed", "claim:writer")
    old = {"from": "writer"}                                              # filed before anyone said how
    assert mine(old, seen) and mine(old, claim)
    assert mine({"from": "writer", "from_how": "observed"}, seen)
    assert not mine({"from": "writer", "from_how": "bound"}, claim)      # a claim never reaches a bound agent's
    assert not mine({"from": "writer", "from_how": "claimed"}, seen)     # nor an agent a claimant's
    assert mine({"from": "writer", "from_key": "claim:writer"}, claim)
    assert not mine({"from": "writer", "from_key": "bound:x"}, claim)
