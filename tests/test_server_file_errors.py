"""A file error reaches the page as a fixed message and an error id, never as the error's own text (which carries a
path and the system's words). Real sockets, with the store's file calls made to fail."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from test_claude_and_server import _post, _url, server  # noqa: F401  (server is a fixture)

SECRET = r"C:\Users\someone\private\rules\SEMANTICS.yaml"


def test_a_failed_write_answers_a_fixed_message_and_an_id(server, store, monkeypatch):  # noqa: F811
    def denied(*a, **k):
        raise PermissionError(13, "Access is denied", SECRET)
    monkeypatch.setattr(store, "set_active", denied)
    status, body = _post(server, "/api/active", {"name": "default"})
    assert status == 500
    assert body == {"error": "could not write your files", "error_id": "PermissionError/EACCES"}
    assert "private" not in json.dumps(body) and "denied" not in json.dumps(body)


def test_a_failed_read_answers_a_fixed_message_and_an_id(server, store, monkeypatch):  # noqa: F811
    def gone(*a, **k):
        raise FileNotFoundError(2, "No such file or directory", SECRET)
    real = store.state
    monkeypatch.setattr(store, "state", gone)
    try:
        with urllib.request.urlopen(_url(server, "/api/state")) as r:
            status, body = r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        status, body = e.code, json.loads(e.read())
    assert status == 500
    assert body == {"error": "could not read your files", "error_id": "FileNotFoundError/ENOENT"}
    assert "private" not in json.dumps(body)
    # must-refuse: a request that is the caller's fault is still told why, in words, as a 400
    monkeypatch.setattr(store, "state", real)
    status, body = _post(server, "/api/active", {"name": "base"})
    assert status == 400 and "base" in body["error"]
