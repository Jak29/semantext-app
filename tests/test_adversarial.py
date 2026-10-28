"""Adversarial tests: what Semantext must do, and what it must refuse or survive.

Each test names one promise and tries to break it. They use only the public API, a temporary home (no test touches
the real ~/.semantext or ~/.claude), and real subprocesses where the promise is about the command line or the hook.
"""
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

from semantext import claude, hook, paths
from semantext.heard import Heard
from semantext.server import make_server
from semantext.store import Refused, Store


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def adv_home(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("SEMANTEXT_HOME", str(tmp_path / "semantext"))
    return tmp_path / "semantext"


@pytest.fixture
def adv_store(adv_home):
    return Store.open(adv_home)


def child_env(home: Path, user: Path) -> dict:
    """The environment a tool such as Claude Code would give the hook: no forced UTF-8 mode."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env.update(SEMANTEXT_HOME=str(home), HOME=str(user), USERPROFILE=str(user), PYTHONDONTWRITEBYTECODE="1")
    # The package under test, also when it runs from a source checkout rather than installed.
    src = str(Path(paths.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def run_cli(home: Path, *args, stdin: bytes = b"", timeout=60):
    user = home.parent / "user"
    user.mkdir(exist_ok=True)
    return subprocess.run([sys.executable, "-m", "semantext", *args], input=stdin, capture_output=True,
                          env=child_env(home, user), timeout=timeout)


@pytest.fixture
def server(adv_store):
    srv = make_server(adv_store, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def request(port, method, path, headers=None, body=None, host=None):
    """Return (status, headers, body), or (None, None, reason) when the server closed without answering."""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        c.putheader("Host", host if host is not None else f"127.0.0.1:{port}")
        data = json.dumps(body).encode() if isinstance(body, (dict, list)) else (body or b"")
        for k, v in (headers or {}).items():
            c.putheader(k, v)
        if method == "POST":
            c.putheader("Content-Type", "application/json")
            c.putheader("Content-Length", str(len(data)))
        c.endheaders(data if method == "POST" else None)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    except (http.client.RemoteDisconnected, ConnectionError, socket.timeout) as e:
        return None, None, repr(e)
    finally:
        c.close()


PAGE = {"X-Semantext": "1"}


def page(port):
    """What the page itself sends with a change: its header and its own origin."""
    return {**PAGE, "Origin": f"http://127.0.0.1:{port}"}


# ---------------------------------------------------------------- the store
@pytest.mark.parametrize("title, slug", [("Work A", "work-a"), ("Work", "work-2")])
def test_undo_last_never_restores_another_environment(adv_store, title, slug):
    """'work' shares a prefix with 'work-a', and with 'work-2' (what a second 'Work' becomes). Undoing 'work' must
    never pull in a version of the other one."""
    s = adv_store
    assert s.create("Work", []) == "work"
    assert s.create(title, []) == slug
    s.learn(slug, "always answer in one line")
    with pytest.raises(Refused):
        s.undo_last("work")                      # 'work' has no earlier version of its own
    assert s.load("work")["environment"]["id"] == "work"


def test_undo_last_takes_its_own_newest_version(adv_store):
    s = adv_store
    s.create("Work", [])
    s.create("Work A", [])
    s.learn("work", "keep every answer short")    # 'work' now has one earlier version: the empty one
    s.learn("work-a", "a rule in the other environment")
    s.undo_last("work")
    d = s.load("work")
    assert d["environment"]["id"] == "work"
    assert not [e for e in d.get("entries") or [] if "learned" in str(e.get("id"))]


def test_learned_ids_stay_unique_after_a_hand_edit(adv_store):
    s = adv_store
    first = s.learn("default", "always reply in English")
    s.learn("default", "never use emoji at all")
    d = yaml.safe_load(s.source("default"))
    d["entries"] = [e for e in d["entries"] if e["id"] != first]
    s.write_source("default", yaml.safe_dump(d, sort_keys=False, allow_unicode=True))
    s.learn("default", "keep answers short please")
    ids = [e["id"] for e in s.load("default")["entries"]]
    assert len(ids) == len(set(ids)), f"two rules share an id: {ids}"


def test_a_name_with_a_trailing_newline_is_not_a_name(adv_home):
    with pytest.raises(Refused):
        Heard(adv_home).path("default\n")


@pytest.mark.parametrize("title", ["Con", "Nul", "Aux", "Prn", "Com1", "Lpt1"])
def test_names_reserved_by_windows_are_refused_on_every_platform(adv_store, title):
    """A portability rule, so a home made on one machine opens on another: Windows reserves these names as
    devices ('nul' reads as existing there), so a folder of that name made elsewhere is unreliable on Windows."""
    with pytest.raises(Refused):
        adv_store.create(title, [])


@pytest.mark.parametrize("name", ["../default", "..", "default/../base", "C:default", "default.yaml", "Default",
                                  "a" * 40, "", None, 7])
def test_a_bad_name_reaches_no_file(adv_store, name):
    with pytest.raises(Refused):
        adv_store.load(name)
    with pytest.raises(Refused):
        adv_store.set_active(name)


def test_a_rule_file_cannot_run_code(adv_store, tmp_path):
    marker = tmp_path / "ran"
    evil = ("environment: {id: default, version: 0.1.0, scope: x}\n"
            f"entries: !!python/object/apply:os.system ['echo x > \"{marker}\"']\n")
    before = adv_store.source("default")
    with pytest.raises(Refused):
        adv_store.write_source("default", evil)
    assert not marker.exists()
    assert adv_store.source("default") == before


def test_exact_words_survive_yaml(adv_store):
    words = "Don't say 'basically': ever. #1 rule - &a *b !!str {x: [y]} éŁ☃ --- ..."
    rid = adv_store.learn("default", words)
    entry = [e for e in adv_store.load("default")["entries"] if e["id"] == rid][0]
    assert entry["statement"] == words
    assert entry["provenance"]["words"] == words


# ---------------------------------------------------------------- the hook
def test_the_card_arrives_with_hearing_on_whatever_the_prompt(adv_store, adv_home):
    """Claude Code sends UTF-8. A prompt in any language must not cost the user the card."""
    adv_store.set_option("hear_prompts", True)
    prompt = "Łódź"          # its UTF-8 bytes include 0x81, which the Windows code page 1252 lacks
    r = run_cli(adv_home, "hook", stdin=json.dumps({"prompt": prompt}, ensure_ascii=False).encode("utf-8"))
    assert r.returncode == 0
    assert b"# Semantext" in r.stdout, r.stdout[:200]


def test_the_hook_keeps_the_prompt_exactly(adv_store, adv_home):
    """What is heard is what was sent, whatever the machine's own code page."""
    adv_store.set_option("hear_prompts", True)
    prompt = "café naïve ☃"
    t = adv_home / "t.jsonl"     # only words the tool's own record calls the user's are kept
    t.write_text(json.dumps({"type": "user", "turnOrigin": "human", "message": {"content": prompt}},
                            ensure_ascii=False) + "\n", encoding="utf-8")
    r = run_cli(adv_home, "hook", stdin=json.dumps({"prompt": prompt, "transcript_path": str(t)},
                                                   ensure_ascii=False).encode("utf-8"))
    assert r.returncode == 0
    heard = Heard(adv_home).items(adv_store.state()["active"])
    assert heard and heard[-1]["text"] == prompt, f"heard {heard[-1]['text'] if heard else None!r}"


def test_the_hook_output_stays_under_its_limit_in_bytes(adv_store, adv_home):
    """The limit is on the bytes the hook writes, line endings included."""
    d = yaml.safe_load(adv_store.source("default"))
    d["entries"] = []
    adv_store.write_source("default", yaml.safe_dump(d, sort_keys=False))
    target = hook.LIMIT_BYTES - 21                 # a card that fits, with 20 bytes to spare
    empty = len(adv_store.card("default").encode("utf-8"))
    per_rule = len("\n- default.r000: " + "x" * 18)
    n = (target - empty) // per_rule - 1
    d["entries"] = [{"id": f"default.r{i:03d}", "statement": "x" * 18} for i in range(n)]
    adv_store.write_source("default", yaml.safe_dump(d, sort_keys=False))
    pad = target - len(adv_store.card("default").encode("utf-8"))
    d["entries"][-1]["statement"] = "x" * (18 + pad)
    adv_store.write_source("default", yaml.safe_dump(d, sort_keys=False))
    assert len(adv_store.card("default").encode("utf-8")) == target   # the card itself fits
    r = run_cli(adv_home, "hook", stdin=b'{"prompt": "hi"}')
    assert r.returncode == 0
    assert len(r.stdout) <= hook.LIMIT_BYTES, f"{len(r.stdout)} bytes written"


@pytest.mark.parametrize("stdin", [b"", b"not json", b"[1, 2]", b'{"prompt": 7}', b"\xff\xfe\x00garbage",
                                   b"[" * 100_000, json.dumps({"prompt": "y" * 1_000_000}).encode()],
                         ids=["empty", "not-json", "a-list", "a-number", "binary", "deep-nesting", "1-MB-prompt"])
def test_the_hook_never_blocks_whatever_arrives(adv_store, adv_home, stdin):
    r = run_cli(adv_home, "hook", stdin=stdin)
    assert r.returncode == 0
    assert b"Traceback" not in r.stdout and b"Traceback" not in r.stderr
    assert len(r.stdout) <= hook.LIMIT_BYTES


def test_the_hook_keeps_nothing_unless_hearing_is_on(adv_store, adv_home):
    assert not adv_store.state()["hear_prompts"]
    r = run_cli(adv_home, "hook", stdin=b'{"prompt": "a private sentence"}')
    assert r.returncode == 0
    assert not (adv_home / "heard").exists() or not any((adv_home / "heard").iterdir())


# ---------------------------------------------------------------- the page server
@pytest.mark.parametrize("host", ["0.0.0.0", "", "::", "127.0.0.2", "LOCALHOST", "192.168.1.10"])
def test_the_server_refuses_to_listen_off_this_machine(adv_store, host):
    with pytest.raises(Refused):
        make_server(adv_store, host=host, port=0)


def test_every_allowed_host_can_actually_be_served(adv_store):
    """The guard allows 127.0.0.1, localhost and ::1; each must give a working server or a clear refusal."""
    for host in ("127.0.0.1", "localhost", "::1"):
        try:
            srv = make_server(adv_store, host=host, port=0)
        except Refused:
            continue
        except OSError as e:
            pytest.fail(f"{host}: allowed by the guard, but serving it raised {type(e).__name__}: {e}")
        srv.server_close()


def test_no_response_invites_another_site(server):
    _, port = server
    for method, path, headers, body in (("GET", "/", {}, None), ("GET", "/api/state", {}, None),
                                        ("GET", "/nope", {}, None), ("POST", "/api/active", {}, {"name": "x"}),
                                        ("POST", "/api/active", page(port), {"name": "../x"})):
        status, h, _ = request(port, method, path, headers, body)
        assert status is not None
        assert "Access-Control-Allow-Origin" not in h
        assert h.get("X-Content-Type-Options") == "nosniff"


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_request_for_another_host_is_refused(server, method):
    _, port = server
    status, _, _ = request(port, method, "/api/state" if method == "GET" else "/api/active",
                           PAGE, {"name": "default"} if method == "POST" else None, host="evil.example")
    assert status == 403


@pytest.mark.parametrize("origin", ["null", "http://evil.example", "http://127.0.0.1:1", "https://127.0.0.1"])
def test_a_change_from_another_page_is_refused(server, origin):
    _, port = server
    status, _, _ = request(port, "POST", "/api/active", {**PAGE, "Origin": origin}, {"name": "default"})
    assert status == 403


def test_a_damaged_rule_file_gets_an_answer_not_a_dropped_connection(server, adv_store):
    _, port = server
    adv_store.path("default").write_text("environment: [unclosed\n", encoding="utf-8")
    for method, path, body in (("GET", "/api/profile?name=default", None), ("GET", "/api/card?name=default", None),
                               ("POST", "/api/toggle", {"name": "default", "id": "x"})):
        status, _, text = request(port, method, path, page(port), body)
        assert status is not None and status >= 400 and status != 403, f"{method} {path}: {text}"


def test_a_damaged_settings_file_gets_an_answer(server, adv_store):
    _, port = server
    adv_store.state_path.write_text("{not json", encoding="utf-8")
    status, _, text = request(port, "GET", "/api/state")
    assert status == 200, text                       # the page still opens, on the defaults, and names the file
    assert any(p["name"] == "state.json" for p in json.loads(text)["problems"])


def test_a_negative_length_is_refused_at_once(server):
    _, port = server
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    try:
        s.sendall((f"POST /api/active HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nX-Semantext: 1\r\n"
                   f"Origin: http://127.0.0.1:{port}\r\n"
                   "Content-Type: application/json\r\nContent-Length: -1\r\n\r\n").encode())
        try:
            head = s.recv(64)
        except socket.timeout:
            head = b""
    finally:
        s.close()
    assert head.startswith(b"HTTP/1.") and head.split()[1].startswith(b"4"), head


def test_the_page_never_parses_rule_text_as_html():
    page = (paths.static_dir() / "index.html").read_text(encoding="utf-8")
    sinks = re.findall(r"\.innerHTML\b|\.outerHTML\b|insertAdjacentHTML|document\.write|\beval\s*\(|new Function\b",
                       page)
    assert not sinks, sinks


# ---------------------------------------------------------------- the command line
def test_a_home_that_is_a_file_gives_a_message_not_a_traceback(tmp_path):
    f = tmp_path / "semantext"
    f.write_text("I am a file", encoding="utf-8")
    r = run_cli(f, "card")
    assert r.returncode != 0
    assert b"Traceback" not in r.stderr, r.stderr.decode("utf-8", "replace")[-400:]


def test_a_damaged_settings_file_gives_a_message_not_a_traceback(adv_store, adv_home):
    adv_store.state_path.write_text("{not json", encoding="utf-8")
    r = run_cli(adv_home, "card")
    assert b"Traceback" not in r.stderr, r.stderr.decode("utf-8", "replace")[-400:]


def test_an_unknown_command_gives_usage_not_a_traceback(adv_home):
    r = run_cli(adv_home, "frobnicate")
    assert r.returncode == 2
    assert b"usage:" in r.stderr and b"Traceback" not in r.stderr


# ---------------------------------------------------------------- connecting Claude Code
@pytest.mark.parametrize("settings", [{"hooks": ["x"]}, {"hooks": {"UserPromptSubmit": "x"}},
                                      {"hooks": {"UserPromptSubmit": [7]}}])
def test_an_odd_settings_file_is_refused_and_left_untouched(tmp_path, settings):
    p = tmp_path / "settings.json"
    text = json.dumps(settings)
    p.write_text(text, encoding="utf-8")
    for act in (lambda: claude.install(p, "semantext hook"), lambda: claude.uninstall(p)):
        try:
            act()
        except Refused:
            pass
        assert p.read_text(encoding="utf-8") == text


def test_install_then_uninstall_leaves_the_rest_of_the_settings_as_they_were(tmp_path):
    p = tmp_path / "settings.json"
    before = {"model": "x", "statusLine": {"type": "command", "command": "echo →"},
              "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "other-tool"}]}],
                        "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]},
              "permissions": {"deny": ["Bash(rm:*)"]}}
    p.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")
    assert claude.install(p, "semantext hook")[0]
    assert not claude.install(p, "semantext hook")[0]          # never twice
    assert claude.uninstall(p)[0]
    assert json.loads(p.read_text(encoding="utf-8")) == before


def test_install_without_apply_changes_nothing(adv_home, tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{}", encoding="utf-8")
    r = run_cli(adv_home, "install", "claude-code", "--settings", str(p))
    assert r.returncode == 0
    assert p.read_text(encoding="utf-8") == "{}"
    assert [x.name for x in tmp_path.iterdir() if x.name.startswith("settings.json.")] == []


# ---------------------------------------------------------------- the package
def test_importing_writes_nothing_and_opens_no_connection(tmp_path):
    home, user = tmp_path / "semantext", tmp_path / "user"
    user.mkdir()
    code = ("import socket\n"
            "def no(*a, **k):\n    raise SystemExit('a connection was opened at import')\n"
            "socket.socket.connect = no\nsocket.create_connection = no\n"
            "import semantext, semantext.cli, semantext.server, semantext.hook, semantext.store, semantext.heard, "
            "semantext.claude\n")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, env=child_env(home, user), cwd=tmp_path,
                       timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert not home.exists()
    assert list(user.iterdir()) == []
