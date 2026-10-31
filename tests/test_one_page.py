"""The one page: Today, Rules, Agents and Settings moved from the home page into the v2 page's parts.

The v2 page used to change only answers, parks and plug-ins. These parts change rules and settings too, so the guard was
narrowed for exactly them, and what it refused before is written here first as must-refuse.
"""
from __future__ import annotations

import re

import pytest

from semantext import paths
from semantext.server import V2_FILES
from v2_node import NODE, run

V2 = paths.static_dir() / "v2"
OWN = ["ownbase.js", "ownevents.js", "ownplace.js", "owntoday.js", "ownrules.js", "ownsky.js", "ownagents.js", "ownspace.js", "ownsettings.js"]
OWN_ROUTES = {"/api/active", "/api/toggle", "/api/learn", "/api/agent-bind", "/api/agent-unbind", "/api/agent-name", "/api/undo",
              "/api/undo-last", "/api/feature", "/api/source", "/api/explain", "/api/setting", "/api/create", "/api/add-suggestions"}
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def text(name):
    return (V2 / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------- what the guard refused, still refused
def test_the_other_places_still_change_nothing_of_your_rules():   # must refuse
    others = [p.name for p in V2.glob("*.js") if p.name not in OWN]
    for name in others:
        t = text(name)
        assert not any(route in t for route in OWN_ROUTES), name
        if name not in ("app.js",):
            assert "ownbase.js" not in t or name in OWN, name         # no other place reaches the one way to change them


def test_only_the_three_known_modules_ever_post():   # must refuse any new writer
    posting = sorted(p.name for p in V2.glob("*.js") if re.search(r'method:\s*"POST"', p.read_text("utf-8")))
    assert posting == ["cards.js", "ownbase.js", "plugins.js"]


def test_the_moved_parts_name_only_their_own_routes():   # must refuse answers, parks and plug-ins from them
    named = set()
    for name in OWN:
        named |= set(re.findall(r'(?:act|api)\("(/api/[a-z-]+)", \{', text(name)))
    assert named == OWN_ROUTES
    for name in OWN:
        t = text(name)
        assert "/api/answer" not in t and "/api/park" not in t and "/api/v2/plugins" not in t, name


def test_the_moved_parts_set_text_never_markup():   # must refuse
    for name in OWN:
        assert "innerHTML" not in text(name) and "insertAdjacentHTML" not in text(name), name


def test_every_moved_part_is_served_and_nothing_else_was_added():
    for name in OWN + ["own.css"]:
        assert f"/v2/{name}" in V2_FILES, name


@needs_node
@pytest.mark.parametrize("route", ["/api/answer", "/api/park", "/api/v2/plugins/enable", "/api/nope", "http://elsewhere/api/learn"])
def test_a_change_to_any_other_route_is_refused_before_it_is_sent(route):   # must refuse
    got = run("""
return moved.api(%r, { x: 1 }).then(() => report("sent"), (e) => report(String(e.message)));
""" % route)
    assert "not a change this part of the page makes" in got


@needs_node
def test_a_change_to_its_own_route_is_sent():   # must pass
    got = run("""
let sent = null;
globalThis.fetch = (path) => { sent = path; return new Promise(() => {}); };
moved.api("/api/learn", { words: "x" });
report(sent);
""")
    assert got == "/api/learn"


# ---------------------------------------------------------------- the places, and where a bare address opens
@needs_node
@pytest.mark.parametrize("waiting,place", [(2, "waiting"), (0, "today")])
def test_a_bare_address_opens_on_waiting_only_when_something_waits(waiting, place):
    got = run("""
applyFrame({ name: null, word: null, waiting: %d, problems: [], outside: [] });
location.hash = "";
route();
return settled().then(() => report(S.place));
""" % waiting)
    assert got == place


@needs_node
@pytest.mark.parametrize("address,place,sub", [("#today", "today", None), ("#today/history", "today", "history"), ("#rules", "rules", None),
                                               ("#rules/test", "rules", "test"), ("#settings", "settings", None), ("#map/~agents", "map", "~agents"),
                                               ("#map/~gets", "map", "~gets")])
def test_each_address_reaches_its_place(address, place, sub):
    got = run("""
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = %r;
route();
return settled().then(() => report([S.place, S.sub, document.getElementById("place").textContent]));
""" % address)
    assert got[:2] == [place, sub]
    assert "Reading" in got[2]                                           # fetch never answers here: it waits, and says so


@needs_node
def test_today_counts_what_waiting_shows():   # the two pages' disagreement: one answer on the whole page
    got = run("""
applyFrame({ name: null, word: null, waiting: 2, problems: [], outside: [] });
const one = moved.needsYou();
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
report([one.textContent, moved.needsYou()]);
""")
    assert got == ["2 decisions are waiting for you", None]


def test_the_bar_lists_ten_places_in_the_agreed_order():
    html = text("index.html")
    assert re.findall(r'data-place="([a-z]+)"', html) == ["today", "waiting", "work", "projects", "documents", "map", "record",
                                                          "rules", "plugins", "settings"]
    assert html.index('id="tab-record"') < html.index('id="tabs-outside"') < html.index('id="tab-rules"')


# ---------------------------------------------------------------- every moved view draws
WORLD = """
const O = moved.S;
const rule = (id, type) => ({ id, statement: "<b>" + id + "</b>", enabled: true, provenance: { type, words: "mine" } });
const rec = { at: "2026-10-31T10:00:00", agent: "helper", how: "bound", tool: "t", words: "agent", from: "you", basis: "text", environment: "default", form: "relay",
  layers: [{ layer: "base", ids: ["a"] }], bytes: 10, left_out: 1, answers: [3], waiting: [], noticed: ["question"], problem: null };
O.state = { active: "default", you: ["you"], feed: true, hear_prompts: false, version: "x", log: [{ when: "2026-10-31T10:00:00", what: "changed" }], problems: [],
  profiles: [{ name: "default", title: "Default", rules: 1 }, { name: "base", title: "Base", rules: 1 }], connections: { claude_code: true, settings: "s", files: [{ file: "f", ok: false }] } };
O.profile = { environment: { id: "default", title: "Default" }, entries: [rule("mine", "LEARNED"), rule("hand", undefined)], tests: [{ message: "m", rules: ["mine"] }] };
O.base = { environment: { id: "base", title: "Base" }, entries: [rule("base.a", "DEFAULT")] };
O.agents = [{ name: "helper", label: "", folders: ["C:/x"], sessions: [{ how: "observed" }], rules: [rule("h", "PROPOSED")], carried: [{ from: "old", rules: [rule("c", "LEARNED")] }], envs: {}, seen: "now", now: null }];
O.feed = { on: true, limit: 9500, records: [rec] };
O.metrics = { window: { records: 1, since: "2026-10-30T10:00:00" }, noticed: { question: { n: 2, covered: 1 } }, cards: { cut: 1, base_only: 1 }, messages: { own: 1 },
  others: { n: 1, claims_you: 1 }, decisions: { asked: 1, answered: 1, median_minutes: 3, via: { chat: 1 } }, rules: { cases: 1, covered: 0, yours: 1, proposed: 0 } };
O.layers = { agent: "helper", form: "full", card: { layers: [{ layer: "base", ids: ["base.a"] }], bytes: 1, limit: 2, left_out: 1, card: "text" } };
O.test = moved.fromTest({ agent: "helper", words: "own", basis: "text", environment: "default", form: "full", layers: [], bytes: 1, left_out: 0, answers: [], waiting: [], reading: { readings: [{ label: "L", says: "S", rule: "base.a" }], decisions: [{ ask: "A" }] }, text: "card" }, "hello", false);
O.expanded = rec.at; O.agentOpen = "helper"; O.ruleOpen = "mine";
"""


@needs_node
@pytest.mark.parametrize("view,says", [("today", "What it did"), ("history", "Every message"), ("rules", "<b>mine</b>"), ("test", "How it is read"),
                                       ("agents", "Name an agent"), ("layers", "Exactly what it receives"), ("settings", "Recent changes")])
def test_every_moved_view_draws_from_a_full_world(view, says):   # a name left behind by the move would throw here
    got = run(WORLD + """
const el = document.createElement("div");
moved.VIEWS[%r]().constructor;
el.append(moved.VIEWS[%r]());
report(el.textContent);
""" % (view, view))
    assert says in got and "undefined" not in got and "[object" not in got

# ---------------------------------------------------------------- no name left behind by the move
TOP = re.compile(r"^(?:export )?(?:async )?(?:function|const|let) ([A-Za-z_$][\w$]*)", re.M)


def _code(t):
    t = re.sub(r"//[^\n]*", "", t)
    return re.sub(r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'', '""', t)


def left_behind(texts):
    """Each module's uses of a name another moved module defines at its top level, which it neither defines nor imports."""
    defined = {n: set(TOP.findall(t)) for n, t in texts.items()}
    every = set().union(*defined.values())
    out = {}
    for n, t in texts.items():
        imported = {x.split(" as ")[-1].strip() for m in re.findall(r"import \{([^}]*)\}", t) for x in m.split(",")}
        code = _code(re.sub(r"^import .*$", "", t, flags=re.M))
        local = set(re.findall(r"(?:const|let|function)\s+([A-Za-z_$][\w$]*)", code)) | {p for m in re.findall(r"\(([^()]*)\)\s*=>", code) for p in re.findall(r"[A-Za-z_$][\w$]*", m)} | set(re.findall(r"\b([A-Za-z_$][\w$]*)\s*=>", code)) | set(re.findall(r"[,\s]([A-Za-z_$][\w$]*)\s*=[^=>]", code)) | set(re.findall(r"\b([A-Za-z_$][\w$]*)\([^()]*\)\s*\{", code))
        used = set(re.findall(r"(?<![\w$.])([A-Za-z_$][\w$]*)\b(?!\s*:)", code))
        missing = (used & every) - defined[n] - imported - local
        if missing:
            out[n] = sorted(missing)
    return out


def test_no_moved_part_uses_a_name_it_did_not_import():   # must pass
    assert left_behind({n: text(n) for n in OWN}) == {}


def test_the_name_check_can_fail():   # must refuse: the two the attack found, as they were
    assert left_behind({"a.js": "export function allAgents() {}\n", "b.js": "const x = () => allAgents();\n"}) == {"b.js": ["allAgents"]}
    assert left_behind({"a.js": "const SOURCE = 1;\n", "b.js": "function f() { return SOURCE; }\n"}) == {"b.js": ["SOURCE"]}