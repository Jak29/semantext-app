"""The inbox (an AI asks, only the user answers) and connecting agents through their instructions files."""
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from semantext import agentfiles, hook
from semantext.cli import main
from semantext.inbox import AGENT_MARKERS, Inbox, card_notes, flags
from semantext.server import make_server
from semantext.store import Refused


def run(capsys, *args):
    code = main(list(args))
    out = capsys.readouterr()
    return code, out.out, out.err


# ---------------------------------------------------------------- the inbox
def test_a_decision_is_filed_and_answered_with_the_users_words(store):
    box = Inbox(store.root)
    r = box.ask("Pick a name", "It goes on the release", "Which name?", ["Alpha", "Beta"], recommend=2, source="writer")
    assert (r["id"], r["status"], r["recommend"], r["from"]) == (1, "open", 2, "writer")
    a = box.answer(1, "2", "Beta, but with a capital B everywhere", via="page")
    assert a["status"] == "answered" and a["answer"]["picked"] == "Beta"
    assert a["answer"]["words"] == "Beta, but with a capital B everywhere" and a["answer"]["via"] == "page"


@pytest.mark.parametrize("label, call", [
    ("no title", lambda b: b.ask("", "why", "q?", ["a"])),
    ("no why", lambda b: b.ask("t", "", "q?", ["a"])),
    ("no question", lambda b: b.ask("t", "why", "", ["a"])),
    ("too many options", lambda b: b.ask("t", "why", "q?", [str(i) for i in range(10)])),
    ("the same option twice", lambda b: b.ask("t", "why", "q?", ["yes", "Yes"])),
    ("a recommendation that is not an option", lambda b: b.ask("t", "why", "q?", ["a", "b"], recommend=3)),
    ("a command without what it does", lambda b: b.ask("t", "why", command="make", undo="none")),
    ("a command without its undo", lambda b: b.ask("t", "why", command="make", does="builds")),
    ("a command carrying a token", lambda b: b.ask("t", "why", command="curl -H 'x: ghp_" + "a" * 30 + "'",
                                                   does="d", undo="u")),
    ("a decision and a command at once", lambda b: b.ask("t", "why", "q?", ["a"], command="ls", does="d", undo="u")),
    ("a decision whose question carries a token", lambda b: b.ask("t", "why", "Use ghp_" + "a" * 30 + "?", ["a"])),
    ("an option carrying a password", lambda b: b.ask("t", "why", "q?", ["password=hunter2hunter2", "b"])),
    ("a title carrying a key", lambda b: b.ask("key sk-" + "a" * 20, "why", "q?", ["a"])),
    ("an undo carrying a token", lambda b: b.ask("t", "why", command="make", does="d", undo="token: abcdef123456")),
])
def test_a_bad_request_is_refused(store, label, call):
    with pytest.raises(Refused):
        call(Inbox(store.root))
    assert Inbox(store.root).requests() == {}


def test_a_command_is_never_run_and_carries_its_flags(store, tmp_path):
    marker = tmp_path / "ran"
    box = Inbox(store.root)
    r = box.ask("Clean up", "Old builds", command=f'echo x > "{marker}"', does="writes a file", undo="delete it")
    assert "may delete or overwrite" in r["flags"]
    assert box.answer(r["id"], "done", via="page")["answer"]["picked"] == "Done"
    assert not marker.exists()
    assert flags("curl https://example.com") == ["uses the network"]
    assert flags("sudo make install") == ["asks for admin"]
    assert flags("echo hello") == []


@pytest.mark.parametrize("label, call", [
    ("an unknown request", lambda b: b.answer(99, "1", via="page")),
    ("an option out of range", lambda b: b.answer(1, "3", via="page")),
    ("an empty answer", lambda b: b.answer(1, "", "", via="page")),
    ("an answer from anywhere but the terminal or the page", lambda b: b.answer(1, "1", via="agent")),
])
def test_a_bad_answer_is_refused(store, label, call):
    box = Inbox(store.root)
    box.ask("t", "why", "q?", ["a", "b"])
    with pytest.raises(Refused):
        call(box)
    assert box.get(1)["status"] == "open"


def test_an_answer_is_given_once_and_a_withdrawn_request_takes_none(store):
    box = Inbox(store.root)
    box.ask("one", "why", "q?", ["a", "b"])
    box.ask("two", "why", "q?", ["a", "b"])
    box.answer(1, "1", via="page")
    with pytest.raises(Refused):
        box.answer(1, "2", via="page")
    box.close(2, "superseded by #3")
    with pytest.raises(Refused):
        box.answer(2, "1", via="page")
    assert box.get(1)["answer"]["picked"] == "a" and box.get(2)["status"] == "closed"


def test_answers_stay_on_the_card_until_the_asker_reads_them(store):
    box = Inbox(store.root)
    box.ask("one", "why", "q?", ["a", "b"], source="writer")
    box.ask("two", "why", "q?", ["a", "b"], source="editor")
    box.answer(1, "2", "go", via="page")
    notes = card_notes(box, None)                            # None: every asker's
    assert "#1 one: b \"go\"" in notes and "#2 two" in notes and notes.index("#1 one") < notes.index("#2 two")
    assert "#1 one" in card_notes(box, None)                 # shown again: nothing is marked by showing it
    assert "#2 two" not in card_notes(box, "writer")         # an agent sees only its own requests
    assert card_notes(box) == ""                             # an unnamed agent is "ai", and asked nothing here
    box.mark_read([1], by="writer")
    assert "#1 one" not in card_notes(box, None)


def test_the_card_notes_are_capped(store):
    box = Inbox(store.root)
    for i in range(8):
        box.ask(f"request {i}", "why", "q?", ["a"])
    notes = card_notes(box)
    assert notes.count("\n- #") == 5 and "- 3 more: run `semantext inbox`" in notes


def test_the_hook_puts_answers_first_and_stays_under_its_limit(store, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_AGENT", raising=False)
    box = Inbox(store.root)
    for i in range(5):
        box.ask(f"request {i}", "why", "q?", ["a"])
        box.answer(i + 1, "1", "w" * 990, via="page")
    out = hook.run("{}", store)
    assert out.startswith("## The user's answers") and "# Semantext: standing rules" in out
    assert len((out + "\n").encode("utf-8")) <= hook.LIMIT_BYTES
    shown = out.count("w" * 990)
    assert 1 <= shown < 5 and f"- {5 - shown} more: run `semantext answers`" in out
    assert "w" * 991 not in out and all(len(seq) == 990 for seq in re.findall(r"w{2,}", out))   # none is cut


def test_the_hook_holds_its_limit_with_long_non_ascii_answers(store, monkeypatch):
    # Seven answers of 999 snowmen, with the longest titles and options: about 4 KB a line in UTF-8.
    monkeypatch.delenv("SEMANTEXT_AGENT", raising=False)
    box = Inbox(store.root)
    for i in range(7):
        box.ask(f"{i}" + "t" * 117, "why", "q?", [f"{i}" + "o" * 299])
        box.answer(i + 1, "1", "☃" * 999, via="page")
    for i in range(7):
        box.ask(f"waiting {i}" + "☃" * 100, "why", "q?", ["a"])
    out = hook.run("{}", store)
    assert len((out + "\n").encode("utf-8")) <= hook.LIMIT_BYTES
    assert "- 7 more: run `semantext answers`" in out and "more: run `semantext inbox`" in out
    assert "base." in out                                  # the card keeps its rules


def test_ids_stay_unique_when_agents_ask_at_once(store):
    box = Inbox(store.root)
    threads = [threading.Thread(target=box.ask, args=(f"r{i}", "why", "q?", ["a"])) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(box.requests()) == list(range(1, 9))


@pytest.fixture
def at_a_console(monkeypatch):
    """A person's own console: no agent's variable set, and standard input a real terminal."""
    for marker in AGENT_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: True)


def test_the_library_refuses_a_terminal_answer_from_an_agents_process(store, at_a_console, monkeypatch):
    box = Inbox(store.root)
    box.ask("t", "why", "q?", ["a", "b"])
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(Refused, match="an agent's shell"):
        box.answer(1, "1", via="terminal")
    with pytest.raises(TypeError):
        box.answer(1, "1")                                   # where an answer came from must always be said
    monkeypatch.delenv("CLAUDECODE")
    assert box.answer(1, "1", via="terminal")["answer"]["via"] == "terminal"


def test_a_command_is_kept_exactly(store):
    box = Inbox(store.root)
    cmd = 'echo "a  b"\nWrite-Host \'two\'\n\tindented'
    assert box.ask("t", "why", command="  " + cmd + "\n", does="d", undo="u")["command"] == cmd
    with pytest.raises(Refused, match="control characters"):
        box.ask("t", "why", command="echo a\x1b[2Khidden", does="d", undo="u")


@pytest.mark.parametrize("secret", ["gho_" + "a" * 30, "ghs_" + "a" * 30, "ghu_" + "a" * 30, "ghr_" + "a" * 30,
                                    "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"])   # built at run time: no key-shaped literal in the source
def test_more_kinds_of_key_are_refused(store, secret):
    with pytest.raises(Refused):
        Inbox(store.root).ask("t", "why " + secret, "q?", ["a"])
    assert Inbox(store.root).requests() == {}


def test_an_id_is_never_reused_after_a_hand_edit(store):
    box = Inbox(store.root)
    box.ask("one", "why", "q?", ["a"])
    box.ask("two", "why", "q?", ["a"])
    lines = box.path.read_text(encoding="utf-8").splitlines(keepends=True)
    box.path.write_text("".join(lines[:-1]), encoding="utf-8")        # the newest request, deleted by hand
    assert box.ask("three", "why", "q?", ["a"])["id"] == 3


def test_an_answer_not_from_the_user_is_labelled_everywhere(capsys, home, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_AGENT", raising=False)
    box = Inbox(home)
    box.ask("Pick one", "why", "q?", ["option 1", "option 2"])
    with box.path.open("a", encoding="utf-8") as f:                   # an agent writes the file itself
        f.write(json.dumps({"type": "answer", "id": 1, "choice": "1", "picked": "option 1", "via": "agent"}) + "\n")
    assert "(not from the user: via agent)" in card_notes(box)
    assert "(not from the user: via agent)" in run(capsys, "inbox", "--all")[1]
    assert "(not from the user: via agent)" in run(capsys, "answers")[1]


def test_answers_marks_only_its_own_askers_answers_read(capsys, home, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_AGENT", raising=False)
    box = Inbox(home)
    box.ask("for codex", "why", "q?", ["a"], source="codex")
    box.ask("for an unnamed agent", "why", "q?", ["a"])
    box.answer(1, "1", via="page")
    box.answer(2, "1", via="page")
    out = run(capsys, "answers")[1]                          # unnamed: the "ai" asker
    assert "for an unnamed agent" in out and "for codex" not in out
    assert "#1 for codex" in card_notes(box, "codex")        # codex's answer still reaches codex


def test_only_the_asker_or_the_user_can_withdraw(capsys, home, monkeypatch):
    for marker in AGENT_MARKERS:
        monkeypatch.delenv(marker, raising=False)
    Inbox(home).ask("mine", "why", "q?", ["a"], source="codex")
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: False)
    code, _, err = run(capsys, "close", "1", "--from", "claude")
    assert code == 1 and "asked by codex" in err
    code, _, err = run(capsys, "close", "1")                  # nobody named, and not a console
    assert code == 1 and "cannot withdraw it here" in err
    assert Inbox(home).get(1)["status"] == "open"
    code, out, _ = run(capsys, "close", "1", "--from", "codex", "--how", "done", "already")
    assert code == 0 and "Withdrew #1" in out and Inbox(home).get(1)["closed"]["by"] == "codex"


def test_a_damaged_inbox_line_is_skipped(store):
    box = Inbox(store.root)
    box.ask("one", "why", "q?", ["a"])
    with box.path.open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    box.ask("two", "why", "q?", ["a"])
    assert sorted(box.requests()) == [1, 2]


def test_a_null_stdin_is_not_a_terminal_so_an_unmarked_agent_cannot_answer(store):
    """An agent's shell attaches the null device to stdin, and on Windows os.isatty() is true for it. An agent that sets
    no marker must still be refused, on every platform."""
    Inbox(store.root).ask("Ship it?", "Release day", "Ship now?", ["Yes", "Wait"])
    env = {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    probe = subprocess.run([sys.executable, "-c", "from semantext.inbox import stdin_is_console as c; print(c())"],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, env=env)
    assert probe.stdout.strip() == "False", probe.stderr
    r = subprocess.run([sys.executable, "-m", "semantext", "answer", "1", "1"], stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "not an interactive terminal" in r.stderr, (r.stdout, r.stderr)
    assert Inbox(store.root).get(1)["status"] == "open"


def test_the_cli_files_a_request_and_an_agent_cannot_answer_it(capsys, home, monkeypatch):
    for marker in AGENT_MARKERS:                 # the suite itself may run inside an agent's shell
        monkeypatch.delenv(marker, raising=False)
    code, out, _ = run(capsys, "ask", "--title", "Ship it?", "--why", "Release day", "--question", "Ship now?",
                       "--option", "Yes", "--option", "Wait", "--recommend", "1", "--from", "builder")
    assert code == 0 and out.startswith("[#1] Ship it?")
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: False)
    code, _, err = run(capsys, "answer", "1", "1")
    assert code == 1 and "not an interactive terminal" in err
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: True)
    monkeypatch.setenv("CLAUDECODE", "1")
    code, _, err = run(capsys, "answer", "1", "1")
    assert code == 1 and "an agent's shell" in err
    monkeypatch.delenv("CLAUDECODE")
    code, out, _ = run(capsys, "answer", "1", "1", "ship", "it")
    assert code == 0 and 'Ship it?: Yes "ship it"' in out
    assert "No new answers" in run(capsys, "answers")[1]   # an unnamed reader is "ai": builder's answer is not its
    code, out, _ = run(capsys, "answers", "--from", "builder")
    assert code == 0 and 'Ship it?: Yes "ship it"' in out and "not from the user" not in out and "Marked as read" in out
    assert "No new answers" in run(capsys, "answers", "--from", "builder")[1]


def test_the_inbox_lists_what_waits(capsys, home):
    run(capsys, "ask", "--title", "Clean up", "--why", "Old builds", "--command", "rm -r build", "--does",
        "removes the build folder", "--undo", "rebuild it")
    out = run(capsys, "inbox")[1]
    assert "#1  Clean up" in out and "from ai (unnamed)" in out and "second look: may delete or overwrite" in out
    assert "Semantext never runs it" in out


def test_the_page_answers_and_says_so(store):
    store.feature("default", "inbox", True)
    Inbox(store.root).ask("Pick", "why", "Which?", ["a", "b"])
    srv = make_server(store, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with urllib.request.urlopen(base + "/api/inbox") as r:
            assert [x["id"] for x in json.loads(r.read())["open"]] == [1]
        def answer(headers):
            req = urllib.request.Request(base + "/api/answer", method="POST", headers={
                "Content-Type": "application/json", "X-Semantext": "1", **headers},
                data=json.dumps({"id": 1, "choice": "2", "words": "b!"}).encode())
            try:
                with urllib.request.urlopen(req) as r:
                    return r.status, json.loads(r.read())
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read())
        assert answer({})[0] == 403                          # a local script, with no page behind it
        assert answer({"Origin": "https://evil.example"})[0] == 403
        assert Inbox(store.root).get(1)["status"] == "open"
        status, body = answer({"Origin": base})               # the page itself
        assert status == 200 and body["request"]["answer"]["via"] == "page"
    finally:
        srv.shutdown()
        srv.server_close()
    assert "never answer your own request" in store.card("default").lower()


# ---------------------------------------------------------------- instructions files
@pytest.mark.parametrize("original", [b"", b"# My notes\n\nKeep it short.\n", b"# My notes\r\nKeep it short.\r\n",
                                      b"\xef\xbb\xbf# BOM file\nline\n", b"no final newline", b"blank end\n\n"],
                         ids=["empty", "lf", "crlf", "bom", "no-final-newline", "blank-end"])
def test_install_then_uninstall_gives_back_the_same_bytes(tmp_path, original):
    p = tmp_path / "AGENTS.md"
    p.write_bytes(original)
    assert agentfiles.install(p, "# card\n- a: one")[0]
    text = p.read_bytes()
    assert text.startswith(original) and b"<!-- semantext:start" in text
    if b"\r\n" in original:
        assert b"\n" not in text.replace(b"\r\n", b"")          # the block keeps the file's CRLF style
    assert agentfiles.install(p, "# card\n- a: one") == (False, None)   # twice adds nothing
    assert agentfiles.uninstall(p)[0]
    assert p.read_bytes() == original


def test_sync_reports_a_broken_file_and_leaves_it_alone(tmp_path, store, capsys, home):
    p = tmp_path / "AGENTS.md"
    assert run(capsys, "install", "agents-md", "--file", str(p), "--apply")[0] == 0
    broken = p.read_bytes() + p.read_bytes()                   # two blocks, as a careless paste would leave it
    p.write_bytes(broken)
    code, out, _ = run(capsys, "sync")
    assert code == 1 and "PROBLEM" in out and "no block there" not in out
    assert out.count(str(p)) == 1                               # the file is named once
    assert p.read_bytes() == broken


def test_sync_refreshes_the_copy_and_install_refreshes_in_place(tmp_path, store):
    p = tmp_path / "knowledge.md"
    p.write_text("# project\n", encoding="utf-8")
    agentfiles.install(p, store.card("default"))
    agentfiles.remember(store, p)
    store.learn("default", "Answer in one line")
    assert agentfiles.sync(store) == [(str(p), "refreshed")]
    assert p.read_text(encoding="utf-8").count("<!-- semantext:start") == 1
    assert "Answer in one line" in p.read_text(encoding="utf-8")


@pytest.mark.parametrize("content", [
    "<!-- semantext:start -->\nA\n<!-- semantext:start -->\nB\n<!-- semantext:end -->\n",
    "text\n<!-- semantext:end -->\n",
    "<!-- semantext:end -->\nx\n<!-- semantext:start -->\n",
    "<!-- semantext:start -->\nno end\n",
], ids=["two-starts", "end-without-start", "reversed", "start-without-end"])
def test_broken_markers_are_refused_and_the_file_left_alone(tmp_path, content):
    p = tmp_path / "AGENTS.md"
    p.write_text(content, encoding="utf-8")
    for act in (lambda: agentfiles.install(p, "card"), lambda: agentfiles.uninstall(p)):
        with pytest.raises(Refused):
            act()
        assert p.read_text(encoding="utf-8") == content


def test_a_folder_or_a_non_utf8_file_is_refused(tmp_path):
    with pytest.raises(Refused):
        agentfiles.install(tmp_path, "card")
    p = tmp_path / "latin.md"
    p.write_bytes(b"caf\xe9\n")
    with pytest.raises(Refused):
        agentfiles.install(p, "card")
    assert p.read_bytes() == b"caf\xe9\n"


def test_the_block_names_no_local_path(home, store):
    text = agentfiles.block(store.card("default"))
    assert str(home) not in text and str(home.parent) not in text and "semantext card" in text


def test_freebuff_uses_the_projects_root(tmp_path, monkeypatch):
    (tmp_path / "proj" / ".git").mkdir(parents=True)
    (tmp_path / "proj" / "src").mkdir()
    monkeypatch.chdir(tmp_path / "proj" / "src")
    assert agentfiles.default_file("freebuff") == (tmp_path / "proj" / "knowledge.md").resolve()


def test_cli_installs_codex_and_doctor_reports_it(capsys, home):
    code, out, _ = run(capsys, "install", "codex")
    assert code == 0 and "would be added" in out
    codex = home.parent / "user" / ".codex" / "AGENTS.md"
    assert not codex.exists()
    assert run(capsys, "install", "codex", "--apply")[0] == 0 and agentfiles.has_block(codex)
    code, out, _ = run(capsys, "doctor")
    assert code == 0 and f"connected ({codex})" in out
    codex.write_text("hand edited, block gone\n", encoding="utf-8")
    code, out, _ = run(capsys, "doctor")
    assert code == 1 and "PROBLEM" in out
    code, _, err = run(capsys, "install", "agents-md")
    assert code == 1 and "--file" in err


def test_export_for_local_models(capsys, home):
    code, out, _ = run(capsys, "export", "system-prompt")
    assert code == 0 and out.startswith("# Semantext")
    code, out, _ = run(capsys, "export", "modelfile", "--base", "llama3.2")
    assert code == 0 and out.startswith("FROM llama3.2\nSYSTEM \"\"\"\n# Semantext")
    assert run(capsys, "export", "modelfile")[0] == 1
    run(capsys, "teach", 'Say """hi""" like that')
    code, _, err = run(capsys, "export", "modelfile", "--base", "llama3.2")
    assert code == 1 and "three double quotes" in err


def test_the_package_never_starts_a_process():
    import pathlib
    import semantext
    src = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path(semantext.__file__).parent.glob("*.py"))
    for needle in ("import subprocess", "os.system(", "os.popen(", "os.exec", "os.spawn", "Popen("):
        assert needle not in src, needle
