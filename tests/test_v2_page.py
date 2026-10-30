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
from semantext.server import V2_CSP, V2_FILES, make_server
from semantext.sources import gates, view
from semantext.sources.gates import World as GitWorld
from test_v2_view import World, append, ask

ROUTES = ("sources", "waiting", "projects", "documents", "map", "record", "rules", "plugins", "hollow")   # the last is the word
PAGE = paths.static_dir() / "v2" / "index.html"


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


def _timeless(x):
    """An answer with the times of now taken out: the frame's checked, and each gates record's read_at (whole seconds,
    so two answers built a moment apart differed when a second turned between them)."""
    if isinstance(x, dict):
        return {k: _timeless(v) for k, v in x.items() if k not in ("checked", "read_at")}
    if isinstance(x, list):
        return [_timeless(v) for v in x]
    if isinstance(x, str):   # the holds line says it too: "Gates (read at 2026-10-24T15:00:01Z)"
        return re.sub(r"read at \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "read at <now>", x)
    return x


def test_the_routes_give_the_views_own_numbers(server, world):
    for route in ROUTES:
        over_http = json.loads(get(server, "/api/v2/" + route, PAGE_HEADER)[1])
        direct = view.answer(route)
        assert "checked" in over_http["frame"] and "checked" in direct["frame"]
        assert _timeless(over_http) == _timeless(json.loads(json.dumps(direct))), route
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


def test_the_pages_files_are_served_from_a_fixed_list_and_nothing_else(server):
    # the list is exactly the files beside index.html: none left unserved, none listed that is not there
    beside = {p.name for p in PAGE.parent.iterdir() if p.is_file() and p.name != "index.html"}
    assert {name for name, _ in V2_FILES.values()} == beside and set(V2_FILES) == {f"/v2/{n}" for n in beside}
    page = PAGE.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/v2/style.css">' in page and '<script type="module" src="/v2/app.js">' in page
    for path, (name, _) in V2_FILES.items():
        status, body, ctype = get(server, path)
        assert status == 200 and body == (PAGE.parent / name).read_bytes(), path
        assert ctype == ("text/css; charset=utf-8" if name.endswith(".css") else "text/javascript; charset=utf-8"), path
    # the page and every file beside it carry the page's policy; the old page at / is left as it was
    for path in ("/v2", *V2_FILES):
        req = urllib.request.Request(f"http://127.0.0.1:{server.server_address[1]}{path}")
        with urllib.request.urlopen(req, timeout=30) as r:
            assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Content-Type-Options"] == "nosniff"
            assert r.headers.get_all("Content-Security-Policy") == [V2_CSP], path
    assert "script-src 'self';" in V2_CSP and "style-src 'self';" in V2_CSP and "'unsafe-inline'" not in V2_CSP
    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/", timeout=30) as r:
        assert "Content-Security-Policy" not in r.headers
    # must-refuse: anything not on the list, however it is spelled, and no file is reached by a path
    for path in ("/v2/index.html", "/v2/APP.JS", "/v2/app.js/", "/v2//app.js", "/v2/nope.js", "/v2/../v2.html",
                 "/v2/%2e%2e/server.py", "/v2/..%2fserver.py", "/v2/v2/app.js", "/static/v2/app.js", "/app.js",
                 "/v2/style.css.map", "/v2/app.js%00.css"):
        assert get(server, path)[0] == 404, path


def inline_script(html: str) -> list[str]:
    """What in the page the policy would block: a <script> with no src (inline code), or an on* handler attribute."""
    found = [m[0] for m in re.finditer(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", html, re.I)]
    found += [m[0] for m in re.finditer(r"<[a-z][^>]*?\son[a-z]+\s*=", html, re.I)]
    return found


def test_the_page_holds_no_inline_script_the_policy_would_block():
    html = PAGE.read_text(encoding="utf-8")
    assert inline_script(html) == [] and '<script type="module" src="/v2/app.js">' in html
    # must-refuse: an inline script, or a handler attribute, planted in a copy, is caught
    assert inline_script(html.replace("</body>", "<script>alert(1)</script></body>"))
    assert inline_script(html.replace("</body>", '<script type="module">import "./x.js";</script></body>'))
    assert inline_script(html.replace('<button class="close"', '<button onclick="go()" class="close"'))
    assert inline_script(html.replace("<body>", '<body onload="start()">'))


INLINE_STYLE = re.compile(r"""\bstyle\s*:|\bstyle\s*=|setAttribute\(\s*["']style["']|<style\b""", re.I)


def inline_styles(files: dict[str, str]) -> list[str]:
    """Where a module or the page sets a style the policy (style-src 'self') would block: a style attribute, by h()'s
    style: key or by hand, or a <style> element. The CSSOM (el.style.x = ...) is allowed and not matched."""
    return [f"{n}: {m.group(0)}" for n, t in files.items() if n.endswith((".js", ".html")) for m in INLINE_STYLE.finditer(t)]


def test_no_module_or_page_sets_an_inline_style():   # the audit of c607024: style-src 'self', no 'unsafe-inline'
    files = page_files()
    assert inline_styles(files) == []
    # must-refuse: each spelling planted in a copy is caught
    for planted in ('h("p", { style: "margin-top:4px" })', 'el.setAttribute("style", "x")', '<p style="x">',
                    "<style>p{}</style>"):
        assert inline_styles({"app.js" if "(" in planted else "index.html": planted}), planted
    assert inline_styles({"app.js": "el.style.marginTop = '4px';"}) == []   # the CSSOM is allowed


def page_files() -> dict[str, str]:
    """The page and every file served beside it, by name."""
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(PAGE.parent.iterdir()) if p.is_file()}


SINKS = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser")


def test_no_module_parses_text_as_markup_and_each_is_small():
    files = page_files()
    modules = {n: t for n, t in files.items() if n.endswith(".js")}
    assert len(modules) >= 8 and "app.js" in modules and "dom.js" in modules
    assert {n: SINKS.findall(t) for n, t in modules.items() if SINKS.search(t)} == {}
    assert {n: t.count("\n") for n, t in modules.items() if t.count("\n") > 350} == {}
    # must-refuse: a sink planted in any one module is found in that module, by name
    for name in modules:
        planted = {**modules, name: modules[name] + "\nel.insertAdjacentHTML('beforeend', x);\n"}
        assert [n for n, t in planted.items() if SINKS.search(t)] == [name]


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
    faults += [f"no place {p}" for p in ("waiting", "projects", "documents", "map", "record")
               if f'data-place="{p}"' not in text]
    if '"X-Semantext": "1"' not in text:
        faults.append("reads without the page's header")
    if re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", text) or "@import" in text:
        faults.append("loads from the network")
    if "<title>Semantext</title>" not in text:
        faults.append("wrong title")
    return faults


def test_the_page_sets_text_never_markup_and_has_the_four_places():
    text = "\n".join(page_files().values())
    assert page_faults(text) == []
    for tab in ("Waiting", "Projects", "Documents", "Record"):
        assert re.search(rf'data-place="[a-z]+"[^>]*>{tab}\b', text), tab
    assert "prefers-reduced-motion" in text and "prefers-color-scheme: dark" in text and '[data-theme="dark"]' in text
    # must-refuse: each fault, planted in a copy, is found
    assert "innerHTML" in page_faults(text.replace("node.append(", "node.innerHTML = (", 1))
    assert "no place record" in page_faults(text.replace('data-place="record"', ""))
    assert "no place documents" in page_faults(text.replace('data-place="documents"', ""))
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
