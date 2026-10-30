"""The Plug-ins tab's module (static/v2/plugins.js), run in node on the page's own modules: what each control sends,
that only what you changed is sent, and how the server's answer is shown. The server is a stand-in that records what
it was sent. Each rule has both arms: what must pass and what must be refused. Skipped where node is not installed."""
from __future__ import annotations

import json
import re

import pytest

from semantext import paths
from v2_node import NODE, run

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DATA = {"place": "plugins", "closures_known": True, "sources_readable": True, "list_command": "semantext plugins",
        "problems": [], "changes": [
            {"n": 2, "at": "2026-10-20T12:00:00Z", "who": "page", "what": "proposed", "field": "settings",
             "plugin": "source.tickets", "before": {"values": {}, "absent": ["extra"]},
             "after": {"values": {"extra": ["/x"]}, "absent": []}, "confirmed": False,
             "command": "semantext plugins confirm 2"},
            {"n": 1, "at": "2026-10-20T11:00:00Z", "who": "terminal", "what": "on", "field": "on",
             "plugin": "source.tickets", "before": None, "after": {"origin": "semantext-jira", "version": "0.3"},
             "confirmed": None, "command": None}],
        "plugins": [
            {"key": "source.tickets", "kind": "source", "name": "tickets", "title": "Tickets", "builtin": False,
             "package": "semantext-jira", "version": "0.3", "trust": "on", "on": True, "loaded": True,
             "health": {"words": "not called yet"}, "reads": ["the tickets file"], "undeclared": [], "shared": [],
             "declared": True, "declaration_problem": None, "can": {"off": True, "change": True}, "on_command": None,
             "settings": [
                 {"key": "tickets", "type": "path", "title": "Tickets file", "widens": False, "required": True,
                  "set": True, "value": "/t"},
                 {"key": "project", "type": "text", "title": "Project", "widens": False, "required": False,
                  "set": True, "value": "alpha"},
                 {"key": "extra", "type": "paths", "title": "More", "widens": False, "required": False, "set": False,
                  "value": None}]},
            {"key": "place.board", "kind": "place", "name": "board", "title": "board", "builtin": False,
             "package": "semantext-board", "version": "0.2", "trust": "installed, not on", "on": False, "loaded": False,
             "health": {"words": "not on, so never called"}, "reads": [], "undeclared": [], "shared": [],
             "declared": False, "declaration_problem": None, "can": {"off": False, "change": False}, "settings": [],
             "on_command": "semantext plugins enable place.board"}]}

SETUP = "const DATA = " + json.dumps(DATA) + r""";
const sent = [];
let answer = { ok: true, status: 200, body: { change: { n: 3, what: "off", plugin: "source.tickets" } } };
sender.post = (act, body) => { sent.push([act, body]); return Promise.resolve({ ok: answer.ok, status: answer.status, json: () => Promise.resolve(answer.body) }); };
S.data.plugins = DATA; S.place = "plugins"; S.sub = null; mount(); fill();
const place = $("place");
const byKey = (k) => place.all((e) => e.getAttribute("data-k") === k)[0];
const text = () => place.textContent;
"""


@pytest.mark.parametrize("state, why, fix, said, unsaid", [
    ("incomplete", "the list is not complete", "set closed_paths_complete to true",
     ["is incomplete", "Why: the list is not complete.", "To fix it, set closed_paths_complete to true."],
     ["not named"]),
    ("unknown", "a path is not full", "correct your closures",
     ["cannot be read", "Why: a path is not full."], ["not named"]),
    ("none named", None, "name them", ["are not named", "Name them under \"closed\""], ["Why:"]),
])
def test_the_tab_says_the_true_state_of_the_closures(state, why, fix, said, unsaid):   # must say, must not say
    data = {**DATA, "closures_known": False, "closures_state": state, "closures_why": why, "closures_fix": fix}
    got = run("const DATA = " + json.dumps(data) + r""";
sender.post = () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
S.data.plugins = DATA; S.place = "plugins"; S.sub = null; mount(); fill();
report({ text: $("place").textContent });
""")
    assert all(s in got["text"] for s in said), got["text"]
    assert not any(s in got["text"] for s in unsaid), got["text"]


def test_the_controls_send_exactly_what_each_change_is():   # must pass
    got = run(SETUP + r"""
return (async () => {
await PG_send_wait(() => byKey("poff:source.tickets").click());
const a = JSON.parse(JSON.stringify(sent));
sent.length = 0;
const f = byKey("pf-source.tickets-project"); f.value = "beta"; f.dispatch("input");
const e = byKey("pf-source.tickets-extra"); e.value = "/a\n\n /b \n"; e.dispatch("input");
await PG_send_wait(() => byKey("pchange:source.tickets").click());
const b = JSON.parse(JSON.stringify(sent));
sent.length = 0;
await PG_send_wait(() => byKey("pback:1").click());
report({ a, b, c: JSON.parse(JSON.stringify(sent)), said: text().includes("Done: change 3, turned off (source.tickets).") });
async function PG_send_wait(fn) { fn(); for (let i = 0; i < 20; i++) await Promise.resolve(); }
})();
""")
    assert got["a"] == [["off", {"plugin": "source.tickets"}]]
    assert got["b"] == [["settings", {"plugin": "source.tickets", "settings": {"project": "beta", "extra": ["/a", "/b"]}}]]
    assert got["c"] == [["rollback", {"change": 1}]] and got["said"] is True


def test_nothing_is_sent_when_nothing_changed_and_an_emptied_field_takes_a_setting_out():
    got = run(SETUP + r"""
byKey("pchange:source.tickets").click();
const none = sent.length;
const f = byKey("pf-source.tickets-project"); f.value = "  "; f.dispatch("input");
report({ none, said: text().includes("Nothing changed"), out: changedSettings(DATA.plugins[0]) });
""")
    assert got["none"] == 0 and got["said"] is True       # must refuse to send an empty change
    assert got["out"] == {"project": None}                # must pass: emptied means taken out


def test_a_refusal_shows_the_servers_words_and_the_line_to_type():   # must refuse quietly, and say why
    got = run(SETUP + r"""
answer = { ok: false, status: 403, body: { error: "not changed on the page: it would widen what the plug-in reads (tickets)", command: "semantext plugins confirm 4", proposal: 4 } };
const f = byKey("pf-source.tickets-tickets"); f.value = "/elsewhere"; f.dispatch("input");
byKey("pchange:source.tickets").click();
return (async () => {
for (let i = 0; i < 20; i++) await Promise.resolve();
const card = place.all((e) => e.getAttribute("data-plugin") === "source.tickets")[0];
const box = card.all((e) => e.getAttribute("role") === "status")[0];
report({ text: text(), kept: byKey("pf-source.tickets-tickets").value, inCard: Boolean(box && box.textContent.includes("confirm 4")),
  acts: Boolean(box && box.className.includes("acts")) });
})();
""")
    assert "it would widen what the plug-in reads (tickets)" in got["text"] and "semantext plugins confirm 4" in got["text"]
    assert got["kept"] == "/elsewhere"   # what you typed stays, so a refusal costs you nothing
    assert got["inCard"] is True and got["acts"] is True   # beside the button that sent it, marked as yours to act on


@pytest.mark.parametrize("status, words", [("expired", "expired"), ("superseded", "later proposal"),
                                           ("confirmed", "Confirmed at the terminal")])
def test_a_proposal_that_cannot_be_confirmed_says_why_and_offers_no_line(status, words):   # must refuse the line
    got = run(SETUP + r"""
const c = Object.assign({}, DATA.changes[0], { status: """ + json.dumps(status) + r""", command: null, confirmed: """
              + json.dumps(status == "confirmed") + r""" });
const li = changeRow(c);
report({ text: li.textContent, buttons: li.all((e) => e.tagName === "BUTTON").length });
""")
    assert words in got["text"] and "plugins confirm" not in got["text"] and got["buttons"] == 0


def test_a_proposal_answered_202_is_shown_as_recorded_never_as_refused():   # must pass, and must refuse "refused"
    got = run(SETUP + r"""
answer = { ok: true, status: 202, body: { proposed: 5, line: "semantext plugins confirm 5", said: "proposed, not changed: proposal 5 is applied at your own console" } };
const f = byKey("pf-source.tickets-project"); f.value = "beta"; f.dispatch("input");
byKey("pchange:source.tickets").click();
return (async () => {
for (let i = 0; i < 20; i++) await Promise.resolve();
const card = place.all((e) => e.getAttribute("data-plugin") === "source.tickets")[0];
const box = card.all((e) => e.getAttribute("role") === "status")[0];
report({ text: box ? box.textContent : "", cls: box ? box.className : "", drafts: Object.keys(PG.drafts) });
})();
""")
    assert "proposal 5" in got["text"] and "semantext plugins confirm 5" in got["text"]
    assert "acts" in got["cls"] and "bad" not in got["cls"] and "Done" not in got["text"]
    assert got["drafts"] == []   # what you typed was taken: it is the proposal now


def test_no_empty_part_is_drawn_as_the_word_null():   # must refuse: replaceChildren writes null as "null"
    got = run(SETUP + r"""report({ words: place.textContent.match(/\bnull\b/g), loose: place.childNodes.filter((n) => !n.tagName).length });""")
    assert got == {"words": None, "loose": 0}


def test_a_plug_in_that_is_not_on_has_no_button_to_turn_it_on():   # must refuse: the page never turns one on
    got = run(SETUP + r"""
const card = place.all((e) => e.getAttribute("data-plugin") === "place.board")[0];
report({ buttons: card.all((e) => e.tagName === "BUTTON").map((b) => b.textContent), text: card.textContent,
  proposal: text().includes("semantext plugins confirm 2") });
""")
    assert got["buttons"] == [] and "semantext plugins enable place.board" in got["text"]
    assert got["proposal"] is True   # an unconfirmed proposal shows the line that makes it, and no roll back


def test_the_module_writes_only_to_its_own_routes():   # must refuse any other write
    text = (paths.static_dir() / "v2" / "plugins.js").read_text(encoding="utf-8")
    assert re.findall(r'fetch\("([^"]+)"', text) == ["/api/v2/plugins/"]
    assert '"X-Semantext": "1"' in text and "innerHTML" not in text
    others = [p.name for p in (paths.static_dir() / "v2").glob("*.js") if p.name != "plugins.js"]
    assert [n for n in others if re.search(r'method:\s*"POST"', (paths.static_dir() / "v2" / n).read_text("utf-8"))] == []
