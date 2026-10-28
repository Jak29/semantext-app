"""Page modules for outside places (semantext/pagemodule.py, static/v2/outside.js): an enabled outside Place may ship
one ES module, served at /v2/plugin/<name>.js from its registry entry alone, and drawn by the page with the text-only
helpers. Each rule has an arm that must pass and one that must refuse.

The plug-in's package is a stand-in made here: a folder holding its files, and a distribution that lists them, offered
through a stand-in for importlib.metadata.entry_points. Nothing is installed. The page parts run in node
(tests/v2_dom.js), where the module is read from a folder as the server would serve it.
"""
from __future__ import annotations

import importlib.metadata
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from semantext import api, pagemodule, registry, server
from semantext.server import V2_CSP, make_server
from semantext.sources import view
from v2_node import NODE, run

GOOD = """export function render(data, el, helpers) {
  el.append(helpers.h("p", { class: "tickets" }, "Tickets: " + data.tickets), helpers.text(" <b>not markup</b>"));
}
"""


class Dist:
    """A distribution as importlib.metadata gives one: its name, version, listed files and where they are."""

    def __init__(self, root: Path, files=("semantext_board/__init__.py", "semantext_board/board.js"),
                 name="semantext-board", version="0.3"):
        self.root, self.name, self.version = root, name, version
        self.files = None if files is None else [importlib.metadata.PackagePath(f) for f in files]

    def locate_file(self, path):
        return self.root / str(path)


class Point:
    def __init__(self, name, make, dist):
        self.name, self.group, self.dist, self._make, self.loads = name, registry.GROUP, dist, make, 0

    def load(self):
        self.loads += 1
        return self._make()


def board_place(name="board", module="semantext_board/board.js"):
    class Board:
        kind, title = "place", "Board"
        page_module = module

        def build(self, sources):
            return {"tickets": 2}
    Board.name = name
    return Board


@pytest.fixture
def plugin(tmp_path, monkeypatch, home):
    """An installed plug-in package with a place and its module; `turn_on()` enables it."""
    root = tmp_path / "site"
    (root / "semantext_board").mkdir(parents=True)
    (root / "semantext_board" / "board.js").write_bytes(GOOD.encode("utf-8"))
    (root / "semantext_board" / "__init__.py").write_text("", encoding="utf-8")
    dist = Dist(root)
    points = [Point("place.board", board_place(), dist)]
    calls = []

    def entry_points(**kw):
        calls.append(kw)
        return [p for p in points if kw.get("group") == registry.GROUP]

    monkeypatch.setattr(importlib.metadata, "entry_points", entry_points)

    def turn_on(*keys, d=dist):
        registry.write_enabled({k: {"origin": d.name, "version": d.version, "at": "2026-10-23T00:00:00Z"}
                                for k in keys or ("place.board",)}, home)
    return type("P", (), {"root": root, "dist": dist, "points": points, "calls": calls, "turn_on": staticmethod(turn_on),
                          "home": home})


def entry(home, name="board"):
    return registry.load_enabled(view.BUILT_IN, home).get("place", name)


# ---------------------------------------------------------------- served from the registry entry, enabled only
def test_an_enabled_place_with_a_module_is_served_with_the_pages_policy(plugin):   # must pass
    plugin.turn_on()
    code, body = server.plugin_module("board.js", plugin.home)
    assert code == 200 and body == GOOD.encode("utf-8")
    frame = view.answer("board", home=plugin.home)["frame"]
    assert frame["outside"] == [{"name": "board", "title": "Board", "origin": "semantext-board", "version": "0.3",
                                 "module": True}]


def test_a_place_not_enabled_has_no_module_and_its_code_never_runs(plugin):   # must refuse
    code, body = server.plugin_module("board.js", plugin.home)
    assert code == 404 and plugin.points[0].loads == 0
    assert view.answer("waiting", home=plugin.home)["frame"]["outside"] == []


@pytest.mark.parametrize("tail", ["../app.js", "..%2fapp.js", "%2e%2e/app.js", "board/../board.js", "a/board.js",
                                  "Board.js", "board.JS", "board", "board.mjs", "board.js/", ".board.js",
                                  "-board.js", "board.js.map", "bo ard.js", "..\\app.js", "board%00.js", ""])
def test_a_path_shaped_request_is_refused_before_any_plug_in_is_looked_at(plugin, tail):
    plugin.turn_on()
    plugin.calls.clear()
    assert server.plugin_module(tail, plugin.home) == (404, {"error": "not found"})
    assert plugin.calls == [] and plugin.points[0].loads == 0


@pytest.mark.parametrize("name", ["a.b", "Board", "x/y", "..", "b" * 65])
def test_a_place_whose_name_is_not_a_plain_word_gets_no_module(plugin, name):
    plugin.points[:] = [Point(f"place.{name}", board_place(name), plugin.dist)]
    plugin.turn_on(f"place.{name}")
    e = entry(plugin.home, name)
    assert e is not None                                                 # the place itself is on
    with pytest.raises(pagemodule.NoModule, match="not a plain word"):
        pagemodule.locate(e)
    assert view.answer(name, home=plugin.home)["frame"]["outside"][0]["module"] is False


@pytest.mark.parametrize("module,why", [
    ("/semantext_board/board.js", "relative path"),
    ("semantext_board\\board.js", "relative path"),
    ("C:semantext_board/board.js", "relative path"),
    ("semantext_board/../semantext_board/board.js", ". or .."),
    ("./semantext_board/board.js", ". or .."),
    ("semantext_board/__init__.py", "relative path"),                   # not a .js file
    ("semantext_board/other.js", "not among the files"),                 # on disk is not enough: it must be listed
    (None, "ships no page module"),
    (7, "relative path"),
])
def test_the_declared_module_must_be_one_of_its_own_listed_js_files(plugin, module, why):
    (plugin.root / "semantext_board" / "other.js").write_text(GOOD, encoding="utf-8")
    plugin.points[:] = [Point("place.board", board_place(module=module), plugin.dist)]
    plugin.turn_on()
    code, body = server.plugin_module("board.js", plugin.home)
    assert code == 404 and why in body["error"]


def test_a_distribution_that_lists_no_files_serves_nothing(plugin):
    plugin.points[0].dist = Dist(plugin.root, files=None)
    plugin.turn_on()
    code, body = server.plugin_module("board.js", plugin.home)
    assert code == 404 and "lists no installed files" in body["error"]


def test_a_listed_file_that_resolves_outside_the_install_folder_is_refused(plugin, tmp_path):
    class Elsewhere(Dist):
        def locate_file(self, path):   # a RECORD entry whose bytes lie elsewhere, as a link would make them
            return tmp_path / "elsewhere" / str(path) if str(path) else self.root
    (tmp_path / "elsewhere" / "semantext_board").mkdir(parents=True)
    (tmp_path / "elsewhere" / "semantext_board" / "board.js").write_text(GOOD, encoding="utf-8")
    plugin.points[0].dist = Elsewhere(plugin.root)
    plugin.turn_on()
    code, body = server.plugin_module("board.js", plugin.home)
    assert code == 404 and "resolves outside" in body["error"]


def test_a_module_over_the_size_bound_is_not_served(plugin):
    (plugin.root / "semantext_board" / "board.js").write_bytes(b"//" + b"x" * pagemodule.MAX_MODULE)
    plugin.turn_on()
    code, body = server.plugin_module("board.js", plugin.home)
    assert code == 404 and "over 1 MiB" in body["error"]


def test_a_built_in_places_name_serves_no_plug_in_module(plugin):
    plugin.turn_on()
    assert server.plugin_module("waiting.js", plugin.home)[0] == 404
    assert server.plugin_module("app.js", plugin.home)[0] == 404


@pytest.fixture
def served(store):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _get(srv, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}{path}") as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_over_http_the_module_carries_the_csp_and_a_script_type(plugin, served):
    code, headers, _ = _get(served, "/v2/plugin/board.js")
    assert code == 404 and headers["Content-Security-Policy"] == V2_CSP    # must refuse: not on yet
    plugin.turn_on()
    code, headers, body = _get(served, "/v2/plugin/board.js")
    assert code == 200 and body == GOOD.encode("utf-8")
    assert headers["Content-Type"].startswith("text/javascript") and headers["Content-Security-Policy"] == V2_CSP
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert _get(served, "/v2/plugin/..%2fapp.js")[0] == 404
    assert _get(served, "/v2/outside.js")[0] == 200                      # the page's own module for these places


def test_the_api_states_the_page_module_contract():
    assert "page_module" in api.Place.__doc__ and "render(data, el, helpers)" in api.Place.__doc__


# ---------------------------------------------------------------- drawn by the page
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

FRAME = """
const place = (name, over) => Object.assign({ name, title: name[0].toUpperCase() + name.slice(1), origin: "semantext-" + name, version: "0.3", module: true }, over || {});
const frameOf = (...places) => ({ name: null, word: null, waiting: 0, problems: [], outside: places });
const go = async (name, data) => {
  S.data[name] = Object.assign({ place: name, frame: S.frame }, data);
  location.hash = "#" + name;
  route();                 // its read never answers here: the place is drawn from the data already held
  await settled();
  return document.getElementById("place");
};
"""


def modules(tmp_path, **files) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / f"{name}.js").write_text(text, encoding="utf-8")
    return folder


@needs_node
def test_an_enabled_place_with_a_module_renders_through_the_page(plugin, tmp_path):   # must pass, end to end
    plugin.turn_on()
    code, body = server.plugin_module("board.js", plugin.home)        # the bytes the server serves
    assert code == 200
    folder = modules(tmp_path)
    (folder / "board.js").write_bytes(body)
    outside = view.answer("board", home=plugin.home)["frame"]["outside"]
    got = run(FRAME + """
return (async () => {
  applyFrame(Object.assign(frameOf(), { outside: %s }));
  const el = await go("board", { tickets: 2 });
  const tabs = document.getElementById("tabs-outside");
  const link = tabs.children[0];
  const frame = el.all((e) => e.classList.contains("plugin-frame"))[0];
  report({ text: el.textContent, inFrame: frame.textContent, tag: frame.children[0].tagName,
    tab: link.textContent, href: link.getAttribute("href"), place: link.getAttribute("data-place"), current: link.getAttribute("aria-current"),
    title: link.getAttribute("title"), placeNow: S.place });
})();
""" % json.dumps(outside), plugins=folder)
    assert got["inFrame"] == "Tickets: 2 <b>not markup</b>" and got["tag"] == "P"   # text set as text
    assert "Board · added by semantext-board 0.3" in got["text"] and got["placeNow"] == "board"
    assert (got["tab"], got["href"], got["place"]) == ("Boardsemantext-board", "#board", "board")
    assert got["current"] == "page" and "semantext-board" in got["title"]


@needs_node
def test_the_bar_lists_outside_places_after_the_built_ins_with_their_origin(tmp_path):
    got = run(FRAME + """
applyFrame(frameOf(place("board"), place("diagrams", { origin: "semantext-pele", version: null })));
const tabs = document.getElementById("tabs-outside").children;
report({ names: tabs.map((a) => a.getAttribute("data-place")), origins: tabs.map((a) => a.children[0].textContent), empty: (() => { applyFrame(frameOf()); return document.getElementById("tabs-outside").children.length; })() });
""")
    assert got == {"names": ["board", "diagrams"], "origins": ["semantext-board", "semantext-pele"], "empty": 0}
    page = Path(view.__file__).parents[1] / "static" / "v2" / "index.html"
    html = page.read_text(encoding="utf-8")
    assert html.index('id="tab-record"') < html.index('id="tabs-outside"') < html.index("</nav>")


@needs_node
def test_a_place_not_enabled_is_not_routed_to_and_its_module_never_imported(tmp_path):   # must refuse
    folder = modules(tmp_path, board=GOOD.replace("export function render", "globalThis.imported = true;\nexport function render"))
    got = run(FRAME + """
return (async () => {
  applyFrame(frameOf());                 // the frame lists no outside place: none is turned on
  S.data.board = { tickets: 2 };
  location.hash = "#board";
  route();
  await settled();
  report({ place: S.place, tabs: document.getElementById("tabs-outside").children.length, imported: typeof imported });
})();
""", plugins=folder)
    assert got == {"place": "waiting", "tabs": 0, "imported": "undefined"}


@needs_node
@pytest.mark.parametrize("name,source,why", [
    ("throws", "export function render() { throw new Error('boom'); }", "boom"),
    ("atload", "throw new Error('at load');\nexport function render() {}", "at load"),
    ("norender", "export const x = 1;", "offers no render"),
    ("gone", None, "404"),
])
def test_a_module_that_throws_leaves_a_problem_line_and_the_page_working(tmp_path, name, source, why):
    folder = modules(tmp_path, good=GOOD, **({name: source} if source else {}))
    got = run(FRAME + """
return (async () => {
  applyFrame(frameOf(place("%s"), place("good")));
  const bad = await go("%s", { tickets: 1 });
  const line = bad.all((e) => e.classList.contains("plugin-problem")).map((e) => e.textContent);
  const ok = await go("good", { tickets: 5 });        // the rest of the page goes on: another place still draws
  renderProblems();
  report({ line, ok: ok.textContent, tabs: document.getElementById("tabs-outside").children.length, place: S.place });
})();
""" % (name, name), plugins=folder)
    assert len(got["line"]) == 1 and got["line"][0].startswith("This place's page module could not draw it: ")
    assert why in got["line"][0]
    assert "Tickets: 5" in got["ok"] and got["tabs"] == 2 and got["place"] == "good"


@needs_node
def test_a_place_without_a_module_or_that_stopped_is_shown_as_text(tmp_path):
    got = run(FRAME + """
return (async () => {
  applyFrame(frameOf(place("plain", { module: false }), place("stopped")));
  const plain = (await go("plain", { tickets: "<i>3</i>" })).textContent;
  const stopped = (await go("stopped", { off: true, failed: "TypeError: x" })).textContent;
  report({ plain, stopped });
})();
""")
    assert "ships no page module" in got["plain"] and '"tickets": "<i>3</i>"' in got["plain"]
    assert '"frame"' not in got["plain"]                                 # render gets the place's JSON, no frame
    assert "could not draw it: the place stopped (TypeError: x)" in got["stopped"]
