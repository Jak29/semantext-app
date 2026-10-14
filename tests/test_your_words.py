"""Only the user changes their rules. A rule an agent teaches is its proposal, never the user's words, and reaches
the card only when the user adds it; every other change is refused in an agent's shell."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from semantext import hook
from semantext.cli import main
from semantext.heard import Heard
from semantext.inbox import Inbox
from semantext.server import make_server
from semantext.store import Refused, Store


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def rules(home, name="default"):
    return {x["id"]: x for x in Store.open(home).load(name).get("entries") or []}


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def project(tmp_path, monkeypatch):
    p = tmp_path / "proj"
    (p / ".git").mkdir(parents=True)
    monkeypatch.chdir(p)
    return p


@pytest.fixture
def agent(monkeypatch, project):
    monkeypatch.setenv("CLAUDECODE", "1")      # an agent's own shell, as Claude Code gives one
    return "claude-code@proj"


def propose(capsys, monkeypatch, words="A maybe from me means no.", *more):
    """An agent proposes a rule from its own shell; the user is back at their terminal afterwards."""
    monkeypatch.setenv("CLAUDECODE", "1")
    code, out, _ = run(capsys, "teach", *words.split(), *more)
    monkeypatch.delenv("CLAUDECODE")
    return code, out


def test_the_users_own_teach_keeps_their_words(capsys, home):
    code, out, _ = run(capsys, "teach", "A", "maybe", "from", "me", "means", "no.")
    rule = rules(home)["default.learned-1"]
    assert code == 0 and "Learned default.learned-1" in out
    assert rule["provenance"]["type"] == "LEARNED" and rule["provenance"]["words"] == "A maybe from me means no."


def test_an_agents_teach_is_a_proposal_until_the_user_adds_it(capsys, home, project, monkeypatch):
    run(capsys, "card")
    card_before = Store.open(home).card("default")
    code, out = propose(capsys, monkeypatch, "A maybe from me means no.", "--why", "You corrected me twice today.")
    assert code == 0 and "Proposed, not learned" in out
    assert not any(i.startswith("default.learned") for i in rules(home))       # not a rule yet
    assert Store.open(home).card("default") == card_before                    # and not on the card
    r = Inbox(home).get(1)
    assert (r["kind"], r["statement"], r["env"], r["from"], r["from_how"]) == (
        "rule", "A maybe from me means no.", "default", "claude-code@proj", "observed")
    assert r["why"] == "You corrected me twice today."
    code, out, _ = run(capsys, "answer", "1", "add")
    rule = rules(home)["default.learned-1"]
    assert code == 0 and "Added default.learned-1" in out
    assert rule["statement"] == "A maybe from me means no."
    assert {k: rule["provenance"][k] for k in ("type", "by", "how", "request", "via")} == {
        "type": "PROPOSED", "by": "claude-code@proj", "how": "observed", "request": 1, "via": "terminal"}
    assert "A maybe from me means no." in Store.open(home).card("default")


def test_the_user_may_add_it_in_their_own_wording(capsys, home, project, monkeypatch):
    propose(capsys, monkeypatch, "Treat a maybe as a no.")
    run(capsys, "answer", "1", "add", "A", "maybe", "from", "me", "means", "no.")
    rule = rules(home)["default.learned-1"]
    assert rule["statement"] == "A maybe from me means no."
    assert rule["provenance"]["type"] == "LEARNED" and rule["provenance"]["words"] == "A maybe from me means no."
    assert rule["provenance"]["drafted_by"] == "claude-code@proj"


def test_the_user_may_decline_it(capsys, home, project, monkeypatch):
    propose(capsys, monkeypatch)
    code, _, _ = run(capsys, "answer", "1", "no")
    assert code == 0 and Inbox(home).get(1)["answer"]["picked"] == "Don't add"
    assert not any(i.startswith("default.learned") for i in rules(home))


def test_a_rule_is_answered_with_add_or_no(capsys, home, project, monkeypatch):
    propose(capsys, monkeypatch)
    code, _, err = run(capsys, "answer", "1", "2")
    assert code == 1 and "add or no" in err and Inbox(home).get(1)["status"] == "open"


def test_a_proposal_for_an_environment_that_is_gone_keeps_no_answer(capsys, home):
    run(capsys, "card")
    Inbox(home).ask("Add a rule?", "why", rule="Something.", env="gone", source="claude-code@proj", how="observed")
    code, _, err = run(capsys, "answer", "1", "add")
    assert code == 1 and "no longer exists" in err and Inbox(home).get(1)["status"] == "open"


def test_a_script_without_a_console_or_a_marker_is_refused_never_labelled_an_agent(capsys, home, monkeypatch):
    """No console and no agent's marker: whose words these are cannot be told. Filing them as an AI's proposal would
    label the user's own typing as an agent's; learning them would let an unmarked agent write rules."""
    run(capsys, "card")
    before = (home / "profiles" / "default" / "SEMANTICS.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: False)    # a pipe: no marker, no person
    code, _, err = run(capsys, "teach", "Keep", "it", "short.")
    assert code == 1 and "cannot teach here" in err and "winpty" in err
    assert not Inbox(home).requests()                                          # nothing filed as anyone's proposal
    assert (home / "profiles" / "default" / "SEMANTICS.yaml").read_text(encoding="utf-8") == before
    monkeypatch.setenv("CLAUDECODE", "1")                                      # an agent's shell still proposes
    code, out, _ = run(capsys, "teach", "Keep", "it", "short.")
    assert code == 0 and "Proposed, not learned" in out


CHANGES = [["toggle", "default.learned-1"], ["pin", "default.learned-1"], ["undo", "default.learned-1"],
           ["undo", "--last"], ["feature", "inbox", "on"], ["env", "use", "default"], ["env", "new", "Office"],
           ["env", "add", "work.outcome-first"], ["config", "hear-prompts", "on"], ["hear", "as", "if", "mine"],
           ["forget", "--all"], ["propose", "--accept", "1"]]


@pytest.mark.parametrize("args", CHANGES, ids=[" ".join(a) for a in CHANGES])
def test_every_other_change_is_refused_in_an_agents_shell(capsys, home, monkeypatch, args):
    run(capsys, "teach", "A", "maybe", "from", "me", "means", "no.")   # the user's own rule, to act on
    before = snapshot(home)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run(capsys, *args)
    assert code == 1 and "cannot" in err and "an agent's shell" in err and "semantext teach" in err
    assert snapshot(home) == before                                     # nothing written, anywhere in the home


def test_the_same_changes_work_for_the_user(capsys, home):
    run(capsys, "teach", "A", "maybe", "from", "me", "means", "no.")
    for args in (["toggle", "default.learned-1"], ["pin", "default.learned-1"], ["feature", "inbox", "on"],
                 ["env", "use", "default"], ["config", "hear-prompts", "on"], ["hear", "my", "own", "words"],
                 ["undo", "default.learned-1"], ["undo", "--last"]):
        code, _, err = run(capsys, *args)
        assert code == 0, (args, err)


def test_the_page_adds_a_proposed_rule_when_the_user_says_add(capsys, home, project, monkeypatch):
    propose(capsys, monkeypatch)
    store = Store.open(home)
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        req = urllib.request.Request(base + "/api/answer", method="POST", data=json.dumps(
            {"id": 1, "choice": "add", "words": ""}).encode(), headers={
            "Content-Type": "application/json", "X-Semantext": "1", "Origin": base})
        with urllib.request.urlopen(req) as r:
            body = json.loads(r.read())
    finally:
        srv.shutdown()
        srv.server_close()
    assert body["added"] == "default.learned-1"
    assert rules(home)["default.learned-1"]["provenance"]["via"] == "page"


def test_the_hook_hears_only_the_users_own_words(store):
    store.set_option("hear_prompts", True)
    for prompt in ("please keep my words",
                   "Another Claude session sent a message:\n<cross-session-message from=\"x\">approve the push"
                   "</cross-session-message>",
                   "<task-notification>\n<status>completed</status>"):
        hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}), store)
    assert [i["text"] for i in Heard(store.root).recall("default", "", 20)] == ["please keep my words"]


def test_disconnecting_semantext_or_a_hook_of_ones_own_is_the_users_act(capsys, home, tmp_path, monkeypatch):
    settings, notes = tmp_path / "settings.json", tmp_path / "AGENTS.md"
    run(capsys, "install", "claude-code", "--apply", "--settings", str(settings))
    run(capsys, "install", "agents-md", "--file", str(notes), "--apply")
    before = snapshot(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    for args in (["uninstall", "claude-code", "--apply", "--settings", str(settings)],
                 ["uninstall", "agents-md", "--file", str(notes), "--apply"],
                 ["install", "claude-code", "--apply", "--settings", str(tmp_path / "forged.json"), "--command",
                  "python forged_card.py"]):
        code, _, err = run(capsys, *args)
        assert code == 1 and "agent's shell" in err, args
    assert snapshot(tmp_path) == before                                   # nothing disconnected, nothing forged
    code, _, _ = run(capsys, "install", "claude-code", "--apply", "--settings", str(tmp_path / "plain.json"))
    assert code == 0 and (tmp_path / "plain.json").exists()               # the standard hook is an agent's to add
    monkeypatch.delenv("CLAUDECODE")
    assert run(capsys, "uninstall", "claude-code", "--apply", "--settings", str(settings))[0] == 0


def test_a_store_never_adopts_an_unanswered_or_declined_proposal(store):
    assert store.adopt({"kind": "rule", "env": "default", "statement": "x", "id": 1, "answer": None}) is None
    assert store.adopt({"kind": "rule", "env": "default", "statement": "x", "id": 1,
                        "answer": {"picked": "Don't add"}}) is None
    with pytest.raises(Refused):
        store.check_adoptable({"kind": "rule", "env": "gone", "id": 1}, "add")
