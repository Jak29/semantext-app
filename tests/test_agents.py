"""Which agent is asking: worked out without names, with how it was known, and never taken over by a claim."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import semantext
from semantext import hook
from semantext.agents import MAX_SESSIONS, Agents, clean, project_of, tool_of
from semantext.cli import main
from semantext.inbox import Inbox
from semantext.store import Refused


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


@pytest.fixture
def repo(tmp_path):
    """A project folder with a git marker, and a subfolder inside it."""
    r = tmp_path / "My Project"
    (r / ".git").mkdir(parents=True)
    (r / "src" / "deep").mkdir(parents=True)
    return r


def test_the_tool_is_read_from_the_hook_event_or_the_shell():
    assert tool_of({"hook_event_name": "UserPromptSubmit"}, {}) == "claude-code"
    assert tool_of({}, {"CLAUDECODE": "1"}) == "claude-code"
    assert tool_of({}, {"CODEX_SANDBOX": "seatbelt"}) == "codex"
    assert tool_of({}, {}) is None
    assert tool_of(None, {"PATH": "x"}) is None


def test_the_project_is_the_git_root_wherever_the_agent_stands(repo):
    assert project_of(repo) == project_of(repo / "src" / "deep") == "my-project"
    assert project_of(None) is None


def test_an_unnamed_agent_is_identified_by_tool_and_project(store, repo):
    agents = Agents(store.root)
    hook_side = agents.identify(env={}, event={"hook_event_name": "UserPromptSubmit", "cwd": str(repo / "src"),
                                               "session_id": "s1"})
    shell_side = agents.identify(env={"CLAUDECODE": "1"}, cwd=repo / "src" / "deep")
    assert hook_side.name == shell_side.name == "claude-code@my-project"
    assert hook_side.how == shell_side.how == "observed" and hook_side.session == "s1"
    assert agents.identify(env={}, cwd=repo).name == "ai"            # no tool seen, nothing stated: the old name


def test_two_projects_and_two_tools_never_merge(store, tmp_path):
    a, b = tmp_path / "a" / "app", tmp_path / "b" / "app"       # the same folder name, different places
    for p in (a, b):
        (p / ".git").mkdir(parents=True)
    agents = Agents(store.root)
    first, second = (agents.identify(env={"CLAUDECODE": "1"}, cwd=p).name for p in (a, b))
    assert (first, second) == ("claude-code@app", "claude-code@app-2")     # one name per project PATH
    assert agents.identify(env={"CLAUDECODE": "1"}, cwd=b / ".git").name == "claude-code@app-2"   # and it stays
    assert Agents(store.root).identify(env={"CLAUDECODE": "1"}, cwd=a).name == "claude-code@app"   # across restarts
    assert agents.identify(env={"CODEX_SANDBOX": "1"}, cwd=b).name == "codex@app-2"
    agents.bind("app-one", a)
    assert agents.identify(env={"CLAUDECODE": "1"}, cwd=a).name == "app-one"


def test_a_binding_wins_and_a_claim_inside_it_is_only_a_label(store, repo):
    agents = Agents(store.root)
    agents.bind("reviewer", repo)
    who = agents.identify(env={"CLAUDECODE": "1", "SEMANTEXT_AGENT": "Boss"}, cwd=repo / "src")
    assert (who.name, who.how, who.claimed) == ("reviewer", "bound", "boss")
    assert agents.identify(env={"SEMANTEXT_AGENT": "reviewer"}, cwd=repo).claimed is None


def test_a_claimed_name_never_takes_a_bound_agents_own_rules(store, repo, tmp_path):
    agents = Agents(store.root)
    agents.bind("reviewer", repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    claim = agents.identify(env={"SEMANTEXT_AGENT": "reviewer"}, cwd=elsewhere)
    assert (claim.name, claim.how) == ("reviewer", "claimed")
    assert not agents.serves_own_rules(claim)                      # reviewer is bound: a claim gets none of it
    loner = agents.identify(env={"SEMANTEXT_AGENT": "scribe"}, cwd=elsewhere)
    assert not agents.serves_own_rules(loner)                      # a claim gets the shared rules only, until bound
    assert agents.serves_own_rules(agents.identify(env={}, cwd=repo))


def test_the_deepest_binding_wins(store, repo):
    agents = Agents(store.root)
    agents.bind("outer", repo)
    agents.bind("inner", repo / "src")
    assert agents.identify(env={}, cwd=repo / "src" / "deep").name == "inner"
    assert agents.identify(env={}, cwd=repo).name == "outer"
    assert agents.unbind(repo / "src") and agents.identify(env={}, cwd=repo / "src").name == "outer"


def test_sessions_are_recorded_without_the_prompt_and_stay_bounded(store, repo):
    agents = Agents(store.root)
    for i in range(MAX_SESSIONS + 5):
        agents.seen(agents.identify(env={}, event={"hook_event_name": "UserPromptSubmit", "cwd": str(repo),
                                                   "session_id": f"s{i}", "prompt": "SECRET-PROMPT-TEXT"}))
    text = agents.sessions_path.read_text(encoding="utf-8")
    assert "SECRET-PROMPT-TEXT" not in text and len(json.loads(text)) == MAX_SESSIONS
    rows = agents.overview()
    assert rows[0]["name"] == "claude-code@my-project" and len(rows[0]["sessions"]) == MAX_SESSIONS


def test_the_hook_files_and_shows_answers_under_the_same_name_as_the_shell(store, repo, monkeypatch):
    # The agent asks from its shell (CLAUDECODE set by the tool); the hook's next prompt carries the answer.
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.chdir(repo)
    who = Agents(store.root).identify()
    Inbox(store.root).ask("Pick", "why", "Which?", ["a", "b"], source=who.name, how=who.how)
    Inbox(store.root).answer(1, "2", via="page")
    monkeypatch.delenv("CLAUDECODE")
    out = hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(repo), "session_id": "x"}), store)
    assert "#1 Pick: b" in out
    other = hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(repo.parent), "session_id": "y"}),
                     store)
    assert "#1 Pick" not in other                                  # another project's agent never sees it


def test_a_request_records_how_its_asker_was_known(capsys, home, monkeypatch, repo):
    monkeypatch.chdir(repo)
    monkeypatch.setenv("SEMANTEXT_AGENT", "Scribe")
    run(capsys, "ask", "--title", "T", "--why", "W", "--question", "Q?", "--option", "a")
    assert Inbox(home).get(1)["from_how"] == "claimed"
    assert "from scribe (claimed)" in run(capsys, "inbox")[1]
    monkeypatch.delenv("SEMANTEXT_AGENT")
    run(capsys, "ask", "--title", "T2", "--why", "W", "--question", "Q?", "--option", "a")
    assert "from ai (unnamed)" in run(capsys, "inbox")[1]


def test_binding_is_the_users_act_not_an_agents(capsys, home, monkeypatch, repo):
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run(capsys, "agent", "bind", "reviewer")
    assert code == 1 and "cannot change agents here" in err
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: True)
    code, out, _ = run(capsys, "agent", "bind", "reviewer")
    assert code == 0 and "is now reviewer" in out
    assert "reviewer" in run(capsys, "agent", "whoami")[1]
    assert "bound to" in run(capsys, "agents")[1]


def test_names_are_cleaned_and_bad_ones_refused(store, repo):
    assert clean("  Claude Code @ Repo! ") == "claude-code-@-repo"
    with pytest.raises(Exception):
        Agents(store.root).bind("", repo)


def test_a_plain_shell_writes_nothing(store, repo):
    agents = Agents(store.root)
    who = agents.identify(env={}, cwd=repo)
    assert (who.name, who.project) == ("ai", None) and not agents.path.exists()


STARTER = ("import sys, time\n"
           "from pathlib import Path\n"
           "from semantext.agents import Agents\n"
           "root, cwd, session, gate = sys.argv[1:5]\n"
           "(Path(gate) / session).touch()\n"                  # ready; then all start together, at the gate
           "while not (Path(gate) / 'go').exists():\n"
           "    time.sleep(0.002)\n"
           "a = Agents(root)\n"
           "who = a.identify(event={'hook_event_name': 'UserPromptSubmit', 'cwd': cwd, 'session_id': session})\n"
           "a.seen(who)\n"
           "print(who.name)\n")


def test_eight_agents_starting_at_once_share_one_name_and_lose_no_session(store, repo, tmp_path):
    src = str(Path(semantext.__file__).resolve().parent.parent)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": src + os.pathsep + os.environ.get("PYTHONPATH", "")}
    gate = tmp_path / "gate"
    gate.mkdir()
    procs = [subprocess.Popen([sys.executable, "-c", STARTER, str(store.root), str(repo), f"s{i}", str(gate)],
                              env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
    deadline = time.monotonic() + 60
    while len(list(gate.iterdir())) < 8 and time.monotonic() < deadline:
        time.sleep(0.01)
    (gate / "go").touch()
    outs = [p.communicate(timeout=120) for p in procs]
    assert [p.returncode for p in procs] == [0] * 8, [err[-300:] for _, err in outs]
    assert {out.strip() for out, _ in outs} == {"claude-code@my-project"}
    agents = Agents(store.root)
    assert list(agents.config()["projects"].values()) == ["my-project"]
    assert sorted(json.loads(agents.sessions_path.read_text(encoding="utf-8"))) == sorted(f"s{i}" for i in range(8))
    assert not list(store.root.glob("*.tmp"))


def test_a_change_is_never_written_over_an_unreadable_agents_file(store, repo):
    agents = Agents(store.root)
    agents.path.write_text("{ half a file", encoding="utf-8")
    with pytest.raises(Refused):
        agents.bind("reviewer", repo)
    assert agents.identify(env={"CLAUDECODE": "1"}, cwd=repo).name == "claude-code@my-project"   # still named
    assert agents.path.read_text(encoding="utf-8") == "{ half a file"                             # and untouched


def test_bookkeeping_that_cannot_be_written_never_stops_an_agent(store, repo, monkeypatch):
    def held_open(*_):
        raise PermissionError("held open by another program")
    monkeypatch.setattr(Agents, "_write", held_open)
    agents = Agents(store.root)
    who = agents.identify(event={"hook_event_name": "UserPromptSubmit", "cwd": str(repo), "session_id": "s1"})
    assert who.name == "claude-code@my-project"
    agents.seen(who)                                                  # no error: the prompt goes ahead
    assert not agents.path.exists() and not agents.sessions_path.exists()


def test_a_write_that_cannot_land_leaves_no_temporary_file(store, monkeypatch):
    def held_open(self, target):
        raise PermissionError("held open by another program")
    monkeypatch.setattr(Path, "replace", held_open)
    monkeypatch.setattr("semantext.agents.time.sleep", lambda _: None)
    with pytest.raises(Refused):
        Agents(store.root).rename("scribe", "The Scribe")
    assert not list(store.root.glob("*.tmp"))
