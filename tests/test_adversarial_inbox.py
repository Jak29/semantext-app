"""Adversarial tests for the inbox: an AI asks, only the user answers, and the hook shows answers without writing.

The human-only gate stops ACCIDENTS (an agent's own shell: a marker set, or no console on standard input). On one
user account nothing local can stop an agent that deliberately clears its markers and attaches a console, so the
last arms test that every answer is VISIBLE for what it is, not that self-answering is impossible.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from semantext import hook, paths
from semantext.inbox import AGENT_MARKERS, Inbox
from semantext.store import Refused, Store


@pytest.fixture
def inbox_home(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("SEMANTEXT_HOME", str(tmp_path / "semantext"))
    for m in AGENT_MARKERS:
        monkeypatch.delenv(m, raising=False)
    Store.open(tmp_path / "semantext")
    return tmp_path / "semantext"


def decision(ib: Inbox, source="agent-a", title="Pick one", n=2):
    return ib.ask(title, "it needs you", question="Which?", options=[f"option {i}" for i in range(1, n + 1)],
                  source=source)["id"]


def env_without_markers(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS and k not in ("PYTHONUTF8",)}
    src = str(Path(paths.__file__).resolve().parent.parent)
    env.update(SEMANTEXT_HOME=str(home), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return env


def answer_events(home: Path) -> int:
    p = home / "inbox.jsonl"
    return sum(1 for line in p.read_text(encoding="utf-8").splitlines() if '"type": "answer"' in line) if p.exists() else 0


# ---------------------------------------------------------------- the gate: every non-console stdin is refused
def _shapes(tmp: Path):
    f = tmp / "stdin.txt"
    f.write_bytes(b"y\n")
    shapes = {"devnull": {"stdin": subprocess.DEVNULL}, "empty-pipe": {"input": b""}, "pipe-with-y": {"input": b"y\n"},
              "file": {"stdin_path": f}}
    if sys.platform == "win32":
        shapes["detached"] = {"creationflags": subprocess.DETACHED_PROCESS, "stdin": subprocess.DEVNULL}
    return shapes


@pytest.mark.parametrize("shape", ["devnull", "empty-pipe", "pipe-with-y", "file", "detached"])
def test_answer_is_refused_for_every_non_console_stdin(inbox_home, tmp_path, shape):
    shapes = _shapes(tmp_path)
    if shape not in shapes:
        pytest.skip("Windows only")
    rid = decision(Inbox(inbox_home))
    kw = dict(shapes[shape])
    path = kw.pop("stdin_path", None)
    args = [sys.executable, "-m", "semantext", "answer", str(rid), "1"]
    env = env_without_markers(inbox_home)
    if path:
        with open(path, "rb") as fh:
            r = subprocess.run(args, stdin=fh, capture_output=True, env=env, timeout=60, **kw)
    else:
        r = subprocess.run(args, capture_output=True, env=env, timeout=60, **kw)
    assert r.returncode != 0, r.stdout[-300:]
    assert answer_events(inbox_home) == 0
    assert b"Traceback" not in r.stderr


WRAP = (
    "import os, sys\n"
    "fd = os.open('CONIN$', os.O_RDWR); os.dup2(fd, 0)\n"     # a real console on stdin (Windows)
    "from semantext import cli\n"
    "sys.exit(cli.main(sys.argv[1:]))\n"
)


def run_with_real_console(home: Path, args, extra_env=None):
    """Windows: a hidden new console, with CONIN$ reopened as stdin (measured: GetConsoleMode then succeeds)."""
    if sys.platform != "win32":
        pytest.skip("the real-console arm is written for Windows; POSIX would use a pty")
    env = env_without_markers(home)
    env.update(extra_env or {})
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return subprocess.run([sys.executable, "-c", WRAP, *args], capture_output=True, env=env, timeout=60,
                          creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)


def test_a_real_console_with_no_marker_may_answer(inbox_home):
    rid = decision(Inbox(inbox_home))
    r = run_with_real_console(inbox_home, ["answer", str(rid), "1", "my", "exact", "words"])
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    got = Inbox(inbox_home).get(rid)
    assert got["status"] == "answered" and got["answer"]["via"] == "terminal"
    assert got["answer"]["words"] == "my exact words"


@pytest.mark.parametrize("marker", list(AGENT_MARKERS))
def test_a_marker_refuses_even_with_a_real_console(inbox_home, marker):
    rid = decision(Inbox(inbox_home))
    r = run_with_real_console(inbox_home, ["answer", str(rid), "1"], {marker: "1"})
    assert r.returncode != 0
    assert answer_events(inbox_home) == 0


# ---------------------------------------------------------------- ids, damage, unknown ids
def test_eight_concurrent_asks_get_eight_consecutive_ids(inbox_home):
    env = env_without_markers(inbox_home)
    procs = [subprocess.Popen([sys.executable, "-m", "semantext", "ask", "--title", f"t{i}", "--why", "w",
                               "--question", "q", "--option", "a", "--option", "b"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(8)]
    codes = [p.wait(timeout=120) for p in procs]
    assert codes == [0] * 8, [p.stderr.read()[-200:] for p in procs]
    lines = (inbox_home / "inbox.jsonl").read_text(encoding="utf-8").splitlines()
    ids = sorted(json.loads(x)["id"] for x in lines)
    assert ids == list(range(1, 9))


def test_an_id_is_never_reused_after_a_hand_edit(inbox_home):
    """Delete the newest request line by hand (its answer line stays): the next id must still be new."""
    ib = Inbox(inbox_home)
    decision(ib)
    last = decision(ib)
    ib.answer(last, "1", via="page")
    p = inbox_home / "inbox.jsonl"
    p.write_text("".join(x + "\n" for x in p.read_text(encoding="utf-8").splitlines()
                         if not (f'"id": {last},' in x and '"type": "request"' in x)), encoding="utf-8")
    assert decision(ib) > last


def test_events_for_unknown_ids_and_damaged_lines_are_harmless(inbox_home):
    ib = Inbox(inbox_home)
    rid = decision(ib)
    with open(inbox_home / "inbox.jsonl", "a", encoding="utf-8") as f:
        f.write('{"type": "answer", "id": 999, "choice": "1", "via": "page"}\n{"type": "close", "id": 998}\n')
        f.write('{"type": "read", "id": 997}\n{not json\n"a string"\n')
    reqs = ib.requests()
    assert set(reqs) == {rid}
    assert reqs[rid]["status"] == "open"


# ---------------------------------------------------------------- who reads, who closes
def test_an_unscoped_reader_does_not_swallow_other_askers_answers(inbox_home):
    """`semantext answers` with no asker named marks answers read. An answer to agent B must still reach B."""
    ib = Inbox(inbox_home)
    a, b = decision(ib, "agent-a"), decision(ib, "agent-b")
    ib.answer(a, "1", via="page")
    ib.answer(b, "2", via="page")
    r = subprocess.run([sys.executable, "-m", "semantext", "answers"], capture_output=True,
                       env=env_without_markers(inbox_home), timeout=60)
    assert r.returncode == 0
    assert [x["id"] for x in Inbox(inbox_home).unread_answers("agent-b")] == [b], "B's answer was marked read"


def test_a_reader_marks_only_its_own(inbox_home):
    ib = Inbox(inbox_home)
    a, b = decision(ib, "agent-a"), decision(ib, "agent-b")
    ib.answer(a, "1", via="page")
    ib.answer(b, "1", via="page")
    env = {**env_without_markers(inbox_home), "SEMANTEXT_AGENT": "agent-a"}
    subprocess.run([sys.executable, "-m", "semantext", "answers"], capture_output=True, env=env, timeout=60)
    assert [x["id"] for x in Inbox(inbox_home).unread_answers("agent-b")] == [b]
    assert Inbox(inbox_home).unread_answers("agent-a") == []


def test_only_the_asker_may_close(inbox_home):
    rid = decision(Inbox(inbox_home), "agent-a")
    env = {**env_without_markers(inbox_home), "SEMANTEXT_AGENT": "agent-b"}
    r = subprocess.run([sys.executable, "-m", "semantext", "close", str(rid), "--how", "not", "mine"],
                       capture_output=True, env=env, timeout=60)
    assert Inbox(inbox_home).get(rid)["status"] == "open", "another agent closed agent-a's request"
    assert r.returncode != 0


def test_close_never_answers(inbox_home):
    ib = Inbox(inbox_home)
    rid = decision(ib)
    ib.close(rid, "superseded")
    assert ib.get(rid)["answer"] is None
    with pytest.raises(Refused):
        ib.answer(rid, "1", via="page")


# ---------------------------------------------------------------- what may never be filed
GH = "gh{}_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


@pytest.mark.parametrize("token", [GH.format("p"), GH.format("o"), GH.format("s"), GH.format("u"),
                                   "sk-" + "a" * 24, "AK" + "IA" + "ABCDEFGHIJKLMNOP", "xox" + "b-" + "1234567890ab",
                                   "AI" + "za" + "x" * 35, "-----BEGIN " + "RSA PRIVATE KEY-----"],
                         ids=["ghp", "gho", "ghs", "ghu", "sk", "akia", "xoxb", "aiza", "pem"])
def test_a_secret_shaped_command_is_refused(inbox_home, token):
    with pytest.raises(Refused):
        Inbox(inbox_home).ask("t", "w", command=f"deploy --key {token}", does="deploys", undo="cannot be undone")


@pytest.mark.parametrize("field", ["title", "why", "question", "option"])
def test_a_secret_in_a_decision_is_refused_too(inbox_home, field):
    """The hook shows titles to the AI, and the file keeps everything: a key belongs in no field."""
    token = GH.format("p")
    kw = {"title": "t", "why": "w", "question": "q", "options": ["a", "b"]}
    if field == "option":
        kw["options"] = ["a", token]
    else:
        kw[field] = f"use {token}"
    with pytest.raises(Refused):
        Inbox(inbox_home).ask(kw["title"], kw["why"], question=kw["question"], options=kw["options"])


@pytest.mark.parametrize("missing", ["does", "undo"])
def test_a_command_needs_does_and_undo(inbox_home, missing):
    kw = {"does": "prints", "undo": "nothing to undo"}
    kw[missing] = ""
    with pytest.raises(Refused):
        Inbox(inbox_home).ask("t", "w", command="echo hi", **kw)


def test_a_command_card_never_runs(inbox_home, tmp_path):
    marker = tmp_path / "ran.txt"
    ib = Inbox(inbox_home)
    rid = ib.ask("t", "w", command=f'echo x > "{marker}"', does="writes a file", undo="delete the file")["id"]
    ib.answer(rid, "done", via="page")
    subprocess.run([sys.executable, "-m", "semantext", "answers"], capture_output=True,
                   env=env_without_markers(inbox_home), timeout=60)
    hook.run('{"prompt": "hi"}', Store.open(inbox_home))
    assert not marker.exists()


# ---------------------------------------------------------------- below the command line
def test_an_answer_from_a_marked_process_is_never_labelled_terminal(inbox_home, monkeypatch):
    """The store layer, called from an agent's own process: refused, or at least never recorded as the user's
    terminal."""
    rid = decision(Inbox(inbox_home))
    monkeypatch.setenv("CLAUDECODE", "1")
    try:
        got = Inbox(inbox_home).answer(rid, "1", via="terminal")
    except Refused:
        return
    assert got["answer"]["via"] != "terminal", "an agent's process recorded via=terminal"


def test_a_page_answer_needs_the_pages_own_origin(inbox_home):
    """A browser on the page always sends its Origin with a POST. One without it is a local process, not the page."""
    import http.client
    import threading
    from semantext.server import make_server
    rid = decision(Inbox(inbox_home))
    srv = make_server(Store.open(inbox_home), port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        def post(origin):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            body = json.dumps({"id": rid, "choice": "1"}).encode()
            headers = {"Host": f"127.0.0.1:{port}", "X-Semantext": "1", "Content-Type": "application/json",
                       "Content-Length": str(len(body))}
            if origin:
                headers["Origin"] = origin
            c.request("POST", "/api/answer", body=body, headers=headers)
            s = c.getresponse().status
            c.close()
            return s
        assert post(None) == 403, "an answer with no Origin was accepted as the page's"
        assert Inbox(inbox_home).get(rid)["status"] == "open"
        assert post(f"http://127.0.0.1:{port}") == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_a_command_is_kept_exactly(inbox_home):
    """The user copies the command to run it: what is stored must be what was asked, apart from its ends."""
    cmd = 'echo "a  b"\nWrite-Host \'two\''
    got = Inbox(inbox_home).ask("t", "w", command=cmd, does="prints two lines", undo="nothing to undo")
    assert got["command"] == cmd.strip(), repr(got["command"])


# ---------------------------------------------------------------- the hook: bytes, read-only, visibility
def test_the_hook_stays_under_its_limit_with_long_non_ascii_answers(inbox_home):
    ib = Inbox(inbox_home)
    for i in range(7):
        rid = ib.ask("ł" * 118 + str(i), "w", question="q",
                     options=["é" * 300, "b" + str(i)])["id"]
        ib.answer(rid, "1", "☃" * 999, via="page")
    for i in range(7):
        ib.ask("ł" * 119, "w", question="q", options=["a", "b"])
    out = hook.run('{"prompt": "hi"}', Store.open(inbox_home))
    assert len(out.encode("utf-8")) + 1 <= hook.LIMIT_BYTES, f"{len(out.encode('utf-8')) + 1} bytes"
    assert "# Semantext" in out, "the card was crowded out"


def test_the_hook_never_writes_the_inbox(inbox_home):
    ib = Inbox(inbox_home)
    rid = decision(ib)
    ib.answer(rid, "1", via="page")
    before = (inbox_home / "inbox.jsonl").read_bytes()
    for _ in range(3):
        hook.run('{"prompt": "hi"}', Store.open(inbox_home))
    assert (inbox_home / "inbox.jsonl").read_bytes() == before


def test_an_answer_not_from_a_person_shows_as_such(inbox_home):
    """Appended by hand, as any agent on the account could: it must not pass for the user's answer. (Asked as
    "ai", the default reader, so the unscoped hook shows it.)"""
    ib = Inbox(inbox_home)
    rid = decision(ib, "ai")
    with open(inbox_home / "inbox.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "answer", "id": rid, "at": "2026-10-13T13:00:00+01:00", "choice": "1",
                            "picked": "option 1", "words": "", "via": "agent"}) + "\n")
    out = hook.run('{"prompt": "hi"}', Store.open(inbox_home))
    line = next(x for x in out.splitlines() if f"#{rid}" in x)
    assert "agent" in line.lower() or "not from" in line.lower(), line
