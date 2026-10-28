"""Every place of the v2 page, drawn for the fixture world, pinned to a checked-in file (tests/v2_page_pin.json).

The page is drawn in node (tests/v2_dom.js, through tests/v2_node.py) from the places' own answers for the world in
tests/test_v2_view.py: each place at every level the world reaches, each drawer, and the bar. For each, the pin holds
the text of every element in order (with its tag, its class, and whether it is hidden or folded) and the set of
interactive elements (tag, address, key, type, state, and the events it listens to). A change to how the page is laid
out must leave this file as it is; a change to what the page shows must change it, on purpose.

The world's folders are written as /fixture and every backslash as a slash, the ids are hashed from those, the times
that are now (the files' own, and when the gates were read) are one fixed time, and dates are read in en-US and UTC,
so the pin does not depend on where or when the tests run. To write the file again: SEMANTEXT_WRITE_PIN=1 pytest tests/test_v2_page_pin.py.
Skipped where node is not installed.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from semantext.sources import gates, places, view
from semantext.sources.gates import World as GitWorld
from test_v2_view import World
from v2_node import NODE, run

PIN = Path(__file__).with_name("v2_page_pin.json")
ROUTES = ("waiting", "projects", "documents", "map", "record", "rules", "sources")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")
NOW_KEYS = ("checked", "read_at", "updated", "file_updated")
NOW = "2026-10-20T12:00:00Z"


def plain(x, roots, now):
    """The answer with the world's folders as /fixture, every backslash as a slash, and each time of now as one."""
    if isinstance(x, dict):
        return {k: plain(v, roots, now) for k, v in x.items()}
    if isinstance(x, list):
        return [plain(v, roots, now) for v in x]
    if isinstance(x, str):
        for t in now:
            x = x.replace(t, NOW)
        return roots.sub("/fixture", x).replace("\\", "/")
    return x


DRAW = r"""
for (const name of ["toLocaleString", "toLocaleDateString", "toLocaleTimeString"]) {
  const was = Date.prototype[name];
  Date.prototype[name] = function (locales, opts) { return was.call(this, "en-US", Object.assign({}, opts, { timeZone: "UTC" })); };
}
const OPEN_TAGS = ["A", "BUTTON", "INPUT", "TEXTAREA", "SELECT", "SUMMARY", "DETAILS"];
function texts(root) {
  const out = [];
  const walk = (n, folded) => {
    for (const c of n.childNodes) {
      if (!c.tagName) continue;
      const own = c.childNodes.filter((x) => !x.tagName).map((x) => x.textContent).join("").trim();
      const fold = folded || (c.tagName === "DETAILS" && !c.open);
      const mark = (c.hidden ? " (hidden)" : "") + (folded && c.tagName !== "SUMMARY" ? " (folded)" : "");
      if (own) out.push(c.tagName.toLowerCase() + (c.className ? "." + c.className.trim().split(/\s+/).join(".") : "") + mark + ": " + own);
      walk(c, c.tagName === "SUMMARY" ? folded : fold);
    }
  };
  walk(root, false);
  return out;
}
function controls(root) {
  return root.all((e) => OPEN_TAGS.includes(e.tagName)).map((e) => [e.tagName.toLowerCase(), e.getAttribute("href"),
    e.getAttribute("data-k"), e.type || null, e.getAttribute("aria-pressed"), e.tagName === "DETAILS" ? e.open : e.disabled || null,
    Object.keys(e.listeners).sort().join(" ")]);
}
const shot = () => ({ bar: texts($("bar-place")), barControls: controls($("bar-place")), place: texts($("place")),
  controls: controls($("place")), problems: texts($("problems")), problemsHidden: $("problems").hidden });
const pins = {};
for (const [r, d] of Object.entries(DATA)) S.data[r] = d;
applyFrame(DATA.waiting.frame);
pins.frame = { tabs: ["tab-waiting", "tab-projects", "tab-documents", "tab-map", "tab-record"].map((id) => [$(id).textContent, $(id).getAttribute("href"), $(id).getAttribute("aria-label")]),
  count: [$("problems-count").hidden, $("problems-count").textContent], gaming: [$("gaming").hidden, $("gaming").textContent] };
const at = (place, sub) => { S.place = place; S.sub = sub || null; mount(); fill(); pins[place + "/" + (sub || "")] = shot(); };
at("waiting");
S.problemsOpen = true; renderProblems(); pins["waiting/ problems open"] = shot(); S.problemsOpen = false;
for (const k of ["shelf:parked", "shelf:done", "shelf:changes"]) S.open.add(k);
S.byProject = true; at("waiting"); pins["waiting/ shelves open, by project"] = pins["waiting/"]; S.byProject = false;
S.q.waiting = "Title A-"; at("waiting"); pins["waiting/ searched"] = pins["waiting/"]; S.q.waiting = "";
S.open.clear(); at("waiting");
at("projects");
for (const p of DATA.projects.projects) at("projects", p.id);
at("projects", "no-such-project");
at("documents");
for (const d of DATA.documents.documents) {
  at("documents", d.id);
  for (const f of [...d.docs.map((x) => x.file), ...d.diagrams, "not-listed.md"]) at("documents", d.id + "/" + f);
}
at("documents", "no-such-document");
at("map");
for (const id of Object.keys(DATA.map.nodes || {})) at("map", id);
at("record");
for (const t of DATA.record.threads) at("record", "t/" + t.key);
for (const e of DATA.record.entries) at("record", e.id);
at("record", "J-404");
S.q.record = "first"; at("record"); pins["record/ searched"] = pins["record/"]; S.q.record = "";
S.facet = "parked"; at("record"); pins["record/ parked"] = pins["record/"]; S.facet = "all";
at("record");
const drawer = (kind, arg) => { S.drawer = { kind, arg }; renderDrawer(true);
  pins["drawer " + kind + " " + JSON.stringify(arg)] = { kind: $("drawer-kind").textContent, title: $("drawer-title").textContent,
    body: texts($("drawer-body")), controls: controls($("drawer-body")) }; };
for (const id of Object.keys(DATA.map.agents || {})) drawer("agent", { id });
drawer("agent", { name: "Nobody" });
drawer("rules", {});
for (const name of Object.keys(DATA.rules.agents || {})) drawer("rules", { agent: name });
for (const p of DATA.projects.projects) { drawer("gates", { project: p.id }); drawer("docs", { project: p.id }); }
report(pins);
"""


def drawn(tmp_path, monkeypatch) -> dict:
    w = World(tmp_path)
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    roots = re.compile("|".join(re.escape(r) for r in sorted(
        {str(tmp_path), tmp_path.as_posix(), str(tmp_path.resolve()), tmp_path.resolve().as_posix()}, key=len, reverse=True)),
        re.IGNORECASE)
    # ids are hashes of where a place lies: hashed here from the world's paths as /fixture, so they (and every order
    # that follows them) are the same wherever the world was made
    real = places._node_id
    monkeypatch.setattr(places, "_node_id", lambda kind, *parts: real(kind, *(roots.sub("/fixture", p).replace("\\", "/")
                                                                              for p in parts)))
    data = {r: view.answer(r) for r in ROUTES}
    # the times the world's files were made, and the time the gates were read, are now: each is written as one time
    now = {v for v in walk(data) if isinstance(v, tuple)}
    return run("const DATA = " + json.dumps(plain(data, roots, {v for _, v in now})) + ";\n" + DRAW)


def walk(x, key=None):
    """Every value in an answer, with the (key, value) pairs of the keys that hold a time of now."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k in NOW_KEYS and isinstance(v, str):
                yield (k, v)
            yield from walk(v, k)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v, key)


def test_every_place_draws_as_pinned(tmp_path, monkeypatch):
    got = drawn(tmp_path, monkeypatch)
    if os.environ.get("SEMANTEXT_WRITE_PIN") == "1":
        PIN.write_text(json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        pytest.skip("the pin was written")
    pinned = PIN.read_text(encoding="utf-8")
    if not gates.WINDOWS:   # the pin was drawn on Windows; elsewhere the record says the executable bit was checked
        assert gates.EXEC_WINDOWS in pinned
        pinned = pinned.replace(gates.EXEC_WINDOWS, gates.EXEC_POSIX)
    want = json.loads(pinned)
    assert sorted(got) == sorted(want)
    for key in sorted(want):
        assert got[key] == want[key], key
    # must-refuse: the pin tells a drawing apart from one with a word changed, and covers every place and every drawer
    changed = json.loads(json.dumps(got).replace("waits for your word", "waits for you", 1))
    assert changed != want
    assert {k.split("/")[0] for k in want if "/" in k} >= {"waiting", "projects", "documents", "map", "record"}
    assert {k.split(" ")[1] for k in want if k.startswith("drawer ")} == {"agent", "rules", "gates", "docs"}
    assert all(want[k]["place"] for k in want if "/" in k)                  # no level drew nothing
