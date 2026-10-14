"""The v2 page, its routes and the status line, on synthetic sources in tmp_path.

The server runs in this process, as the other page tests run it; the status line runs as the command Claude Code runs.
Every check has a must-pass arm and a must-refuse arm: a read the page makes is answered and the same read from anywhere
else is refused; nothing is written, and a planted write is seen by the same listing; the page sets text and never
markup, and a copy that parses markup is caught.
"""
from __future__ import annotations

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

from semantext import paths
from semantext.server import make_server
from semantext.sources import gates, view
from semantext.sources.gates import World as GitWorld
from test_v2_view import World, append, ask

ROUTES = ("sources", "waiting", "projects", "map", "record", "rules", "hollow")   # the last is the person's word
PAGE = paths.static_dir() / "v2.html"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    git_user = tmp_path / "git-user"
    git_user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, git_user, (), (), ()))
    return w


@pytest.fixture
def server(store, world):
    srv = make_server(store, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path: str, headers: dict | None = None) -> tuple[int, bytes, str]:
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


PAGE_HEADER = {"X-Semantext": "1"}


# ---------------------------------------------------------------- a read only the page makes
def test_every_route_answers_the_page_and_refuses_anyone_else(server):
    own = f"http://127.0.0.1:{server.server_address[1]}"
    for route in ROUTES:
        status, body, ctype = get(server, "/api/v2/" + route, PAGE_HEADER)
        assert status == 200 and "json" in ctype, route
        got = json.loads(body)
        assert got["frame"]["waiting"] == 2 and got["place"] == ("map" if route == "hollow" else route)
        assert get(server, "/api/v2/" + route, {**PAGE_HEADER, "Origin": own})[0] == 200
        # must-refuse: without the page's header, from another site, or as a cross-site fetch
        assert get(server, "/api/v2/" + route)[0] == 403, route
        assert get(server, "/api/v2/" + route, {**PAGE_HEADER, "Origin": "http://evil.example"})[0] == 403
        assert get(server, "/api/v2/" + route, {**PAGE_HEADER, "Sec-Fetch-Site": "cross-site"})[0] == 403
        assert get(server, "/api/v2/" + route, {"X-Semantext": "0"})[0] == 403
    assert get(server, "/api/v2/nowhere", PAGE_HEADER)[0] == 404
    assert get(server, "/api/v2/", PAGE_HEADER)[0] == 404


def test_the_routes_give_the_views_own_numbers(server, world):
    for route in ROUTES:
        over_http = json.loads(get(server, "/api/v2/" + route, PAGE_HEADER)[1])
        direct = view.answer(route)
        over_http["frame"].pop("checked")
        direct["frame"].pop("checked")
        assert over_http == json.loads(json.dumps(direct)), route
    # must-refuse: a card filed now is in the next answer
    append(world.file("Cedar"), ask("C-20261005-090000", "2026-10-05T09:00:00+01:00"))
    assert json.loads(get(server, "/api/v2/waiting", PAGE_HEADER)[1])["frame"]["waiting"] == 3


def test_v2_serves_the_page_and_nothing_beside_it(server):
    status, body, ctype = get(server, "/v2")
    assert status == 200 and ctype.startswith("text/html") and b"<title>Semantext</title>" in body
    assert body == PAGE.read_bytes()
    for path in ("/v2.html", "/static/v2.html", "/v2/", "/v2/x", "/v2/../index.html"):
        assert get(server, path)[0] == 404, path
    # the page that was there before stays as it was
    status, body, _ = get(server, "/")
    assert status == 200 and body == (paths.static_dir() / "index.html").read_bytes()
    assert get(server, "/api/feed")[0] == 403


# ---------------------------------------------------------------- nothing written
def listing(root: Path) -> dict:
    """Every file and folder under root: (kind, size, modification time). A folder's size is not compared."""
    out = {}
    for here, dirs, files in os.walk(root):
        for name in dirs + files:
            p = Path(here) / name
            st = p.lstat()
            kind = "d" if p.is_dir() else "f"
            out[str(p.relative_to(root))] = (kind, 0 if kind == "d" else st.st_size, st.st_mtime_ns)
    return out


def test_nothing_is_written_by_any_route(server, store, tmp_path, world):
    before = listing(tmp_path)
    assert store.root.is_dir() and (store.root / "profiles").is_dir()   # the home is watched as it is
    for _ in range(2):
        for route in ROUTES:
            assert get(server, "/api/v2/" + route, PAGE_HEADER)[0] == 200
        assert get(server, "/v2")[0] == 200
        get(server, "/api/v2/waiting")                                   # a refused read writes nothing either
    assert listing(tmp_path) == before
    # must-refuse: the same listing sees a write, in the home or among the sources
    append(world.file("Alder"), "{}")
    assert listing(tmp_path) != before
    after_append = listing(tmp_path)
    (store.root / "note.txt").write_text("x", encoding="utf-8")
    assert listing(tmp_path) != after_append


# ---------------------------------------------------------------- the page sets text, never markup
def page_faults(text: str) -> list[str]:
    """What is wrong with the page: a way to parse text as markup, a place missing from the bar, a read without the
    page's header, anything loaded from the network, or the wrong title."""
    faults = [api for api in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "DOMParser")
              if api in text]
    faults += [f"no place {p}" for p in ("waiting", "projects", "map", "record") if f'data-place="{p}"' not in text]
    if '"X-Semantext": "1"' not in text:
        faults.append("reads without the page's header")
    if re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", text) or "@import" in text:
        faults.append("loads from the network")
    if "<title>Semantext</title>" not in text:
        faults.append("wrong title")
    return faults


def test_the_page_sets_text_never_markup_and_has_the_four_places():
    text = PAGE.read_text(encoding="utf-8")
    assert page_faults(text) == []
    for tab in ("Waiting", "Projects", "Record"):
        assert re.search(rf'data-place="[a-z]+"[^>]*>{tab}\b', text), tab
    assert "prefers-reduced-motion" in text and "prefers-color-scheme: dark" in text and '[data-theme="dark"]' in text
    # must-refuse: each fault, planted in a copy, is found
    assert "innerHTML" in page_faults(text.replace("node.append(", "node.innerHTML = (", 1))
    assert "no place record" in page_faults(text.replace('data-place="record"', ""))
    assert "reads without the page's header" in page_faults(text.replace('"X-Semantext": "1"', ""))
    assert "loads from the network" in page_faults(text.replace("</head>", '<script src="https://cdn.example/x.js"></script></head>'))


# ---------------------------------------------------------------- the status line
def statusline(tmp_path: Path, config: Path, stdin: bytes = b"", *args: str):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    src = str(Path(paths.__file__).resolve().parent.parent)
    env.update(SEMANTEXT_SOURCES=str(config), SEMANTEXT_HOME=str(tmp_path / "never-made"),
               HOME=str(tmp_path / "git-user"), USERPROFILE=str(tmp_path / "git-user"), PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    r = subprocess.run([sys.executable, "-m", "semantext", "statusline", *args], input=stdin, capture_output=True,
                       env=env, timeout=60)
    return r.returncode, r.stdout.decode("utf-8").strip(), r.stderr.decode("utf-8", "replace")


def test_the_status_line_on_fixtures_and_on_a_broken_config(tmp_path, world):
    before = listing(tmp_path)
    code, out, err = statusline(tmp_path, world.config, b'{"session_id": "abc", "model": {"id": "x"}}')
    assert (code, out, err) == (0, "2 waiting · newest: Birch B-20261002-090000 Title B-20261002-090000", "")
    code, out, _ = statusline(tmp_path, world.config, b"", "--width", "50")
    assert code == 0 and len(out) <= 50 and out.endswith("…")
    assert listing(tmp_path) == before and not (tmp_path / "never-made").exists()   # nothing written, no home made
    # must-refuse: a card filed now changes the line; a broken config, or a bad width, never fails
    append(world.file("Cedar"), ask("C-20261005-090000", "2026-10-05T09:00:00+01:00"))
    assert statusline(tmp_path, world.config)[1].startswith("3 waiting · newest: Cedar C-20261005-090000")
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert statusline(tmp_path, broken, b"{}") == (0, view.UNAVAILABLE, "")
    assert statusline(tmp_path, tmp_path / "no-such-file.json")[:2] == (0, view.UNAVAILABLE)
    assert statusline(tmp_path, world.config, b"", "--width", "wide")[0:2] == (
        0, "3 waiting · newest: Cedar C-20261005-090000 Title C-20261005-090000")
    assert not (tmp_path / "never-made").exists()
