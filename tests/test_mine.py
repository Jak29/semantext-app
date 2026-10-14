"""Mining: the user's own past words from a transcript, kept as heard, never a rule, never a secret, never twice. Every
transcript here is made up."""
import json
import socket

import pytest

from semantext import hook
from semantext.cli import main
from semantext.heard import Heard
from semantext.mine import encode_project, is_correction, mine, units
from semantext.sender import own_words
from semantext.store import Refused, Store

KEY = "sk-" + "a1b2c3d4" * 3          # built at run time: no key-shaped literal in the source


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


def user(text, origin="human", uid=None, older=False, meta=False, summary=False, at="2026-10-01T10:00:00Z"):
    r = {"type": "user", "uuid": uid or f"u-{abs(hash((text, origin, older))) % 10**8}", "timestamp": at,
         "message": {"role": "user", "content": text}}
    if origin and older:
        r["origin"] = {"kind": origin}                                      # the older form of the record
    elif origin:
        r["turnOrigin"] = origin.replace("-", "_")
    if meta:
        r["isMeta"] = True
    if summary:
        r["isCompactSummary"] = True
    return r


def reply(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def tool_result():
    return {"type": "user", "uuid": "t-1", "message": {"content": [{"type": "tool_result", "content": "done"}]}}


def queued(text, human=True):
    return {"type": "attachment", "uuid": f"q-{len(text)}",
            "attachment": {"type": "queued_command", "prompt": text, "humanTurn": human}}


def transcript(path, *records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


MIXED = [
    user("Please keep the summary short from now on."),                               # mine, by the record
    reply("Understood."),
    user("Always name the file you changed.", origin="human", older=True),            # mine, by the older record
    user("Report from agent-a: the build passed.", origin="peer"),                    # another agent's message
    user("<task-notification>\n<task-id>x</task-id>", origin="task-notification"),    # a tool's notice
    user("Another Claude session sent a message:\nhi", origin="human"),               # the text says relay
    user("Hook says hello.", origin=None, meta=True),                                 # added by the tool
    user("The conversation so far, summarised.", origin=None, summary=True),          # a compaction summary
    tool_result(),
    {**user("Fix the parser.", uid="side-1"), "isSidechain": True},                   # a subagent's own conversation
    queued("Never push without asking me first."),                                    # mine, typed while it worked
]


def test_mining_keeps_only_the_users_own_words(store, tmp_path):
    t = transcript(tmp_path / "s1.jsonl", *MIXED)
    r = mine(store, "default", [t])
    kept = [i["text"] for i in Heard(store.root).items("default")]
    assert kept == ["Please keep the summary short from now on.", "Always name the file you changed.",
                    "Never push without asking me first."]
    assert (r["kept"], r["by_record"], r["summaries"], r["not_users"]) == (3, 3, 1, 4)
    assert all(i["source"] == "transcript" and i["from"]["file"] == "s1.jsonl" for i in Heard(store.root).items("default"))


def test_a_record_that_says_nothing_leaves_it_to_the_words(store, tmp_path):
    t = transcript(tmp_path / "s2.jsonl", user("Keep answers brief.", origin=None))
    r = mine(store, "default", [t])
    assert (r["kept"], r["by_text_only"]) == (1, 1)


def test_mining_never_keeps_a_secret(store, tmp_path, capsys):
    t = transcript(tmp_path / "s3.jsonl", user(f"use this key {KEY} for the deploy"), user("Keep it short."))
    r = mine(store, "default", [t])
    assert (r["kept"], r["secrets"]) == (1, 1)
    assert KEY not in (store.root / "heard" / "default.jsonl").read_text(encoding="utf-8")
    with pytest.raises(Refused):
        Heard(store.root).hear("default", f"my token is {KEY}")             # the same line for every way in
    store.set_option("hear_prompts", True)
    out = hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "cwd": str(tmp_path), "session_id": "s",
                               "prompt": f"deploy with {KEY}"}), store)
    assert "Semantext: standing rules" in out and KEY not in json.dumps(Heard(store.root).items("default"))


def test_the_heard_store_refuses_a_secret_however_it_arrives(store):
    kept = Heard(store.root).keep("default", [{"text": f"key {KEY}"}, {"text": "Keep it short."}], source="transcript")
    assert kept == 1 and KEY not in json.dumps(Heard(store.root).items("default"))


def test_mining_keeps_nothing_twice(store, tmp_path):
    t = transcript(tmp_path / "s4.jsonl", *MIXED, queued("Never push without asking me first."))
    first = mine(store, "default", [t])
    second = mine(store, "default", [t])
    assert first["kept"] == 3 and first["duplicates"] == 1                  # the same words, queued and delivered
    assert (second["kept"], second["duplicates"]) == (0, 4)
    assert len(Heard(store.root).items("default")) == 3


def test_mining_is_the_users_act_and_makes_no_rule(capsys, home, tmp_path, monkeypatch):
    t = transcript(tmp_path / "s5.jsonl", *MIXED)
    run(capsys, "init")
    before = Store.open(home).card("default")
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run(capsys, "mine", str(t))
    assert code == 1 and not Heard(home).items("default")                  # an agent's shell keeps nothing
    code, out, _ = run(capsys, "mine", str(t), "--dry-run", "--json")
    assert code == 0 and json.loads(out)["kept"] == 3 and not Heard(home).items("default")
    monkeypatch.delenv("CLAUDECODE")
    code, out, _ = run(capsys, "mine", str(t))
    assert code == 0 and "Kept 3 of your own messages" in out and "Nothing became a rule" in out
    assert Store.open(home).card("default") == before                       # no rule from mining
    assert "Always name the file you changed." in run(capsys, "propose")[1]  # a proposal, for the user to accept


def test_mining_opens_no_connection(store, tmp_path, monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("mining opened a connection")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert mine(store, "default", [transcript(tmp_path / "s6.jsonl", *MIXED)])["kept"] == 3


def test_a_correction_is_paired_with_the_prompt_it_corrected(tmp_path):
    t = transcript(tmp_path / "s7.jsonl",
                   user("Clean up the old notes."), reply("I deleted the notes folder."),
                   user("No, I meant archive them, not delete them."), reply("Restored and archived."),
                   user("No problem, thanks for that."),
                   user("Report from agent-a: done.", origin="peer"),                # between two of the user's
                   user("Why did you change the colours?"))                           # no reply since: no pair
    u = units(t)
    assert [x["misread"] for x in u] == [True, False, False, False]
    assert u[0]["correction"] == "No, I meant archive them, not delete them." and "deleted" in u[0]["reply_tail"]


@pytest.mark.parametrize("text, want", [
    ("No, I meant the other file.", True), ("no - the second one", True), ("That's not what I asked for", True),
    ("I said tomorrow, not today.", True), ("Why did you remove the tests?", True), ("Stop changing the config.", True),
    ("Again I said the blue one.", True), ("As I said, the second file.", True),
    ("I don't think you're following the plan.", True), ("You're not reading the brief.", True),
    ("keep it short is what I meant", True), ("Read it first, then change it.", True),
    ("This was my original question, look again.", True),
    ("No problem at all", False), ("No rush on this", False), ("Notes for later", False), ("Nothing else", False),
    ("Wait, one more idea", False), ("Actually that looks great", False), ("Please carry on", False),
    ("You're right, thanks.", False), ("I'm not sure yet.", False),
    ("I said hello to the team.", True),     # a pin, not a law: the known price of "I said", one false row at most
])
def test_the_correction_openings(text, want):
    assert is_correction(text) is want


def test_the_projects_transcripts_are_found_by_its_folder(capsys, home, tmp_path):
    project = tmp_path / "work" / "app"
    (project / ".git").mkdir(parents=True)
    folder = home.parent / "user" / ".claude" / "projects" / encode_project(project.resolve())
    folder.mkdir(parents=True)
    transcript(folder / "session.jsonl", *MIXED)
    run(capsys, "init")
    code, out, _ = run(capsys, "mine", "--project", str(project), "--dry-run", "--json")
    assert code == 0 and json.loads(out)["files"] == 1
    assert encode_project(r"D:\work\my app") == "D--work-my-app"


def test_the_older_record_can_take_a_prompt_away_from_the_user(tmp_path):
    t = transcript(tmp_path / "s8.jsonl", user("Build it now.", origin="peer", older=True),
                   user("Ship the fix.", origin="human", older=True))
    assert own_words("Build it now.", t) is False                           # an older record of another agent's
    assert own_words("Ship the fix.", t) is True
