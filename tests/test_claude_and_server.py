"""Connecting to Claude Code, and the local page's server."""
import http.client
import json
import threading
import urllib.request

import pytest

from semantext import claude
from semantext.server import make_server
from semantext.store import Refused


def test_install_creates_the_settings_file(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    changed, backup = claude.install(path, "semantext hook")
    assert changed and backup is None
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0] == {"type": "command", "command": "semantext hook"}


def test_install_keeps_everything_else_and_backs_up_first(tmp_path):
    path = tmp_path / "settings.json"
    other = {"theme": "dark", "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "other"}]}]}}
    path.write_text(json.dumps(other), encoding="utf-8")
    changed, backup = claude.install(path, "semantext hook")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert changed and json.loads(backup.read_text(encoding="utf-8")) == other
    assert data["theme"] == "dark"
    assert [g["hooks"][0]["command"] for g in data["hooks"]["UserPromptSubmit"]] == ["other", "semantext hook"]


def test_install_twice_adds_nothing(tmp_path):
    path = tmp_path / "settings.json"
    claude.install(path, "semantext hook")
    assert claude.install(path, "semantext hook") == (False, None)
    assert len(json.loads(path.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]) == 1


def test_a_settings_file_that_is_not_json_is_never_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(Refused):
        claude.install(path, "semantext hook")
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_uninstall_removes_only_semantext(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "other"}]}]}}),
                    encoding="utf-8")
    claude.install(path, "semantext hook")
    changed, _ = claude.uninstall(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert changed and not claude.is_installed(data)
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "other"


def test_a_settings_file_with_a_byte_order_mark_is_read(tmp_path):
    """Windows PowerShell 5.1 saves JSON with a byte-order mark: it is still JSON."""
    path = tmp_path / "settings.json"
    path.write_text("\ufeff" + json.dumps({"theme": "dark"}), encoding="utf-8")
    changed, _ = claude.install(path, "semantext hook")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    assert changed and data["theme"] == "dark" and claude.is_installed(data)


@pytest.mark.parametrize("command", ["semantext hook", "semantext.exe hook", '"C:\\Py\\Scripts\\semantext.exe" hook',
                                     '"C:\\Py\\python.exe" -m semantext hook', 'semantext --home "D:\\rules" hook',
                                     "/usr/bin/semantext --home /srv/rules hook"])
def test_our_hook_is_known_however_it_is_spelled(tmp_path, command):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}}),
                    encoding="utf-8")
    assert claude.install(path, "semantext hook") == (False, None)      # never a second entry
    assert claude.uninstall(path)[0] and not claude.is_installed(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("command", ["semantext-hooks run", "echo semantext", "mysemantext hookup"])
def test_another_command_is_never_taken_for_ours(command):
    assert not claude.is_installed({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": command}]}]}})


def test_a_hook_installed_from_another_home_names_that_home(tmp_path):
    other = tmp_path / "rules"
    assert f'--home "{other.resolve()}" hook' in claude.hook_command(other)
    assert "--home" not in claude.hook_command(None)


def test_two_backups_in_one_second_never_overwrite_each_other(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    assert len({claude._backup(path) for _ in range(5)}) == 5


@pytest.fixture
def server(store):
    srv = make_server(store, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _url(srv, path):
    return f"http://127.0.0.1:{srv.server_address[1]}{path}"


def _post(srv, path, body, headers=None):
    # As the page sends it: its own header and its own origin (a browser names the page with every POST).
    h = {"Content-Type": "application/json", "X-Semantext": "1", "Origin": f"http://127.0.0.1:{srv.server_address[1]}"}
    h.update(headers or {})
    req = urllib.request.Request(_url(srv, path), data=json.dumps(body).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_page_and_its_state_are_served(server):
    with urllib.request.urlopen(_url(server, "/")) as r:
        assert r.status == 200 and b"<title>Semantext</title>" in r.read()
    with urllib.request.urlopen(_url(server, "/api/state")) as r:
        assert json.loads(r.read())["active"] == "default"


def test_a_change_from_the_page_is_saved(server, store):
    status, body = _post(server, "/api/learn", {"name": "default", "words": "Answer in one line"})
    assert status == 200 and body["id"] == "default.learned-1"
    assert "Answer in one line" in store.card("default")


def test_a_change_without_the_page_header_is_refused(server, store):
    status, _ = _post(server, "/api/learn", {"name": "default", "words": "Injected"}, {"X-Semantext": ""})
    assert status == 403 and "Injected" not in store.card("default")


def test_the_page_lists_ideas_and_adds_the_ticked_ones(server, store):
    def ideas():
        with urllib.request.urlopen(_url(server, "/api/ideas?name=default")) as r:
            return json.loads(r.read())["packs"]
    rule = ideas()[0]["rules"][0]
    assert rule["held"] is False
    status, body = _post(server, "/api/add-suggestions", {"name": "default", "ids": [rule["id"]]})
    assert status == 200 and body["added"] == ["default." + rule["id"].split(".", 1)[-1]]
    assert ideas()[0]["rules"][0]["held"] is True
    status, _ = _post(server, "/api/add-suggestions", {"name": "default", "ids": rule["id"]})      # not a list
    assert status == 400
    status, _ = _post(server, "/api/add-suggestions", {"name": "default", "ids": ["work.outcome-first"]},
                      {"X-Semantext": ""})
    assert status == 403 and "default.outcome-first" not in store.card("default")


def test_a_change_from_another_site_is_refused(server, store):
    status, _ = _post(server, "/api/learn", {"name": "default", "words": "Injected"}, {"Origin": "https://evil.example"})
    assert status == 403 and "Injected" not in store.card("default")
    own = f"http://127.0.0.1:{server.server_address[1]}"
    status, _ = _post(server, "/api/learn", {"name": "default", "words": "From the page"}, {"Origin": own})
    assert status == 200 and "From the page" in store.card("default")


def test_only_the_page_itself_is_served_as_a_file(server):
    for path in ("/../pyproject.toml", "/%2e%2e%2fpyproject.toml", "/static/index.html", "/api/../store.py"):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("GET", path)
        assert conn.getresponse().status == 404, path
        conn.close()


def test_a_request_for_another_host_is_refused(server):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    conn.request("GET", "/api/state", headers={"Host": "attacker.example:80"})
    assert conn.getresponse().status == 403
    conn.close()


def test_a_refusal_comes_back_as_a_message(server):
    status, body = _post(server, "/api/active", {"name": "base"})
    assert status == 400 and "base" in body["error"]


def test_a_second_server_cannot_share_a_port_in_use(server, store):
    # Real sockets, not a mock: on Windows a reused address would let this second bind succeed silently.
    with pytest.raises(OSError):
        second = make_server(store, "127.0.0.1", server.server_address[1])
        second.server_close()


@pytest.mark.parametrize("headers", [{"X-Semantext": ""}, {"X-Semantext": "1", "Origin": "https://evil.example"},
                                     {"X-Semantext": "1", "Host": "evil.example"}], ids=["no-header", "origin", "host"])
def test_a_refused_change_is_read_cleanly_even_with_a_large_body(server, store, headers):
    # A refused change with a large body still gets its 403, and changes nothing. The server drains the body before it
    # answers, because closing with unread data resets the connection and the client can lose the 403 (seen on
    # Windows CI). That race is rare: a probe measured 4 resets in 1,200 refused POSTs before the drain and 0 in 1,200
    # after, so these few rounds check the refusal end to end but cannot prove the drain alone.
    port = server.server_address[1]
    h = {"Content-Type": "application/json", "Host": f"127.0.0.1:{port}", **headers}
    body = json.dumps({"name": "default", "words": "Injected " + "x" * 150_000}).encode()
    for _ in range(5):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.request("POST", "/api/learn", body=body, headers=h)
        r = c.getresponse()
        assert r.status == 403
        r.read()
        c.close()
    assert "Injected" not in store.card("default")


def test_a_refused_client_that_stalls_gets_the_refusal_without_a_traceback(store, capsys, monkeypatch):
    # It declares a body and never sends it: the drain waits for the timeout, then answers anyway.
    from semantext import server as server_module
    srv = make_server(store, "127.0.0.1", 0)
    srv.RequestHandlerClass.timeout = 0.5
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        port = srv.server_address[1]
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.putrequest("POST", "/api/learn", skip_host=True)
        c.putheader("Host", f"127.0.0.1:{port}")
        c.putheader("Content-Length", "1000")
        c.endheaders()                                       # headers only; the declared body never comes
        r = c.getresponse()
        assert r.status == 403
        c.close()
    finally:
        srv.shutdown()
        srv.server_close()
    assert "Traceback" not in capsys.readouterr().err
    assert server_module.MAX_BODY >= 1000


def test_a_client_that_hangs_up_leaves_no_traceback(store, capsys):
    srv = make_server(store, "127.0.0.1", 0)
    try:
        for gone in (ConnectionAbortedError(), BrokenPipeError(), ConnectionResetError()):
            try:
                raise gone
            except OSError:
                srv.handle_error(None, ("127.0.0.1", 1))
        assert capsys.readouterr().err == ""
        try:
            raise ValueError("a real fault")
        except ValueError:
            srv.handle_error(None, ("127.0.0.1", 1))
        assert "ValueError" in capsys.readouterr().err     # a real fault is still reported
    finally:
        srv.server_close()


def test_the_server_serves_this_machine_only(store):
    with pytest.raises(Refused):
        make_server(store, "0.0.0.0", 0)
