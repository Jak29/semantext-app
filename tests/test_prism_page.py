"""Prism, the home of the page (1.6.2): the illustrated reading and the five bands of your spectrum.

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules, as test_one_page.py draws.
"""
from __future__ import annotations

import json
import re

import pytest

from semantext import reading
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRAW = """
applyFrame({ name: null, word: null, waiting: %d, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  const links = place.all((e) => e.tagName === "A").map((a) => [a.getAttribute("href"), a.textContent]);
  report({ text: place.textContent, links });
});
"""


EXAMPLE = "Could we maybe ship the dark mode later?"


def answers(*messages, offer=None):
    """The real reader's answers (reading.report, the one `semantext read` prints from), by message, as JSON for a stub."""
    return json.dumps({m: {"ok": True, **reading.report(m, offer=offer)} for m in messages}, ensure_ascii=False)


def stub(by_message):
    """A fetch for the page: POST /api/read answers from the real reader (by message) at once; every other request
    waits, as it does in node. What was sent is kept in `sent` as [path, method, body]."""
    return """
const sent = [];
const BY = %s;
globalThis.fetch = (path, opts) => {
  sent.push([String(path), (opts && opts.method) || "GET", (opts && opts.body) || null]);
  if (path === "/api/read") {
    const got = BY[JSON.parse(opts.body).message];
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(got) });
  }
  return new Promise(() => {});
};
const ticks = (n = 40) => { let t = Promise.resolve(); for (let i = 0; i < n; i++) t = t.then(() => null); return t; };
""" % by_message


@needs_node
def test_prism_draws_what_the_real_reader_answers():
    got = run(stub(answers(EXAMPLE)) + """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => ticks()).then(() => {
  const place = document.getElementById("place");
  report({ text: place.textContent, sent, status: place.querySelector("p.prism-status").textContent });
});
""")
    t = got["text"]
    assert "QUESTION · publish" in t and "“later”, kept word for word" in t           # the reader's kind, act and time word
    assert "You mentioned it as question, which is not a go." in t                       # the advice is the reader's why
    assert "INSTRUCTION" not in t and "SUGGESTION" not in t and "YOUR WORD" not in t     # must-refuse: no page-made readings
    assert "appear to say go" not in t                                                   # must-refuse: a question is no go
    assert got["status"] == ""
    posts = [s for s in got["sent"] if s[1] == "POST"]
    assert posts == [["/api/read", "POST", json.dumps({"message": EXAMPLE}, separators=(",", ":"))]]   # in the body only
    assert "Read by the same reader as semantext read" in t
    assert "nothing is saved and nothing leaves it" in t


@needs_node
def test_prism_says_reading_and_draws_nothing_the_reader_did_not_say():   # must-refuse: no reading made up while waiting
    got = run(DRAW % 0)
    assert "Reading…" in got["text"] and "READING…" in got["text"]
    for kind in ("QUESTION", "SUGGESTION", "TIME", "YOUR WORD", "INSTRUCTION"):
        assert kind not in got["text"], kind


@needs_node
def test_a_go_the_reader_hedges_is_drawn_as_confirm_never_as_a_go():
    msg = "Publish the release tonight."
    got = run(stub(answers(msg)) + """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const input = document.getElementById("place").querySelector("input.prism-input");
  input.value = %s;
  document.getElementById("place").querySelector("form.prism-form").dispatch("submit");
  return ticks();
}).then(() => report(document.getElementById("place").querySelector("ul.prism-advice").textContent));
""" % json.dumps(msg))
    assert "publish" in got and "your words appear to say go: confirm (within “tonight”)" in got
    assert "ALLOWED" not in got and "BLOCKED" not in got


def failing(reply):
    """A page whose reader route answers `reply` (a JS expression for the response), then shows the message box."""
    return """
globalThis.fetch = (path, opts) => path === "/api/read" ? Promise.resolve(%s) : new Promise(() => {});
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => { let t = Promise.resolve(); for (let i = 0; i < 40; i++) t = t.then(() => null); return t; }).then(() => {
  const place = document.getElementById("place");
  report({ status: place.querySelector("p.prism-status").textContent, cls: place.querySelector("p.prism-status").className,
           text: place.textContent });
});
""" % reply


@needs_node
@pytest.mark.parametrize("reply,says", [
    ("{ ok: false, status: 400, statusText: 'Bad', json: () => Promise.resolve({ error: 'request too large' }) }", "request too large"),
    ("{ ok: false, status: 502, statusText: 'Bad Gateway', json: () => Promise.reject(new SyntaxError('<html>')) }", "Bad Gateway"),
    ("{ ok: false, status: 502, statusText: '', json: () => Promise.reject(new SyntaxError('<html>')) }", "the server answered 502"),
    ("{ ok: true, status: 200, json: () => Promise.reject(new SyntaxError('not json')) }", "the server's answer was not readable"),
    ("{ ok: true, status: 200, json: () => Promise.resolve(null) }", "the server's answer was not readable"),
    ("{ ok: true, status: 200, json: () => Promise.resolve({ ok: true }) }", "the answer was not in the shape the page expects"),
], ids=["json error", "html error body", "no status text", "ok but not json", "ok but null", "ok but wrong shape"])
def test_a_failed_read_is_said_plainly_and_no_reading_is_drawn(reply, says):   # must-refuse: no false reading
    got = run(failing(reply))
    assert got["status"] == f"Could not read it: {says}. No reading is shown." and "warn" in got["cls"]
    assert "NOT READ" in got["text"] and "QUESTION" not in got["text"]


@needs_node
def test_a_good_answer_with_ok_first_still_draws():   # must-pass beside the failures above
    ok = json.dumps({"ok": True, **reading.report("Delete the old branch.")})
    got = run(failing("{ ok: true, status: 200, json: () => Promise.resolve(%s) }" % ok))
    assert got["status"] == "" and "INSTRUCTION · delete" in got["text"]


@needs_node
def test_the_status_is_checked_before_the_body_is_trusted():   # item 4: r.ok first, then a body that may not be JSON
    got = run("""
const outcome = (r) => readerAnswer(r).then((j) => ["ok", j], (e) => ["error", e.message]);
return Promise.all([
  outcome({ ok: false, status: 500, statusText: "Server Error", json: () => Promise.resolve({ error: "no" }) }),
  outcome({ ok: false, status: 500, statusText: "Server Error", json: () => Promise.reject(new Error("x")) }),
  outcome({ ok: false, status: 500, statusText: "Server Error", json: () => Promise.resolve({ error: 5 }) }),
  outcome({ ok: false, status: 500, statusText: "", json: () => Promise.resolve(null) }),
  outcome({ ok: true, status: 200, json: () => Promise.reject(new Error("x")) }),
  outcome({ ok: true, status: 200, json: () => Promise.resolve([1]) }),
  outcome({ ok: true, status: 200, json: () => Promise.resolve({ a: 1 }) }),
]).then(report);
""")
    assert got == [["error", "no"], ["error", "Server Error"], ["error", "Server Error"], ["error", "the server answered 500"],
                   ["error", "the server's answer was not readable"], ["error", "the server's answer was not readable"],
                   ["ok", {"a": 1}]]


@needs_node
def test_typing_waits_for_a_pause_and_a_slow_answer_to_an_older_message_is_dropped():
    got = run(stub("{}") + """
const timers = [], cleared = [];
globalThis.setTimeout = (fn, ms) => { timers.push([fn, ms]); return timers.length; };
globalThis.clearTimeout = (id) => { cleared.push(id); };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  const input = place.querySelector("input.prism-input");
  const before = sent.filter((s) => s[0] === "/api/read").length;       // the page's own first ask, for the example
  for (const v of ["P", "Pu", "Pub"]) { input.value = v; input.dispatch("input"); }
  const typing = sent.filter((s) => s[0] === "/api/read").length;       // typing alone sends nothing
  report({ before, typing, waits: timers.map((t) => t[1]), cleared: cleared.length,
           status: place.querySelector("p.prism-status").textContent });
});
""")
    assert got["before"] == 1 and got["typing"] == 1             # three keystrokes, no request; only the pause sends
    assert got["waits"] == [400, 400, 400] and got["cleared"] >= 3
    assert got["status"] == "Reading…"
    late = run("""
const resolvers = {};
const reply = (msg) => ({ ok: true, status: 200, json: () => Promise.resolve(%s[msg]) });
globalThis.fetch = (path, opts) => path === "/api/read"
  ? new Promise((resolve) => { resolvers[JSON.parse(opts.body).message] = () => resolve(reply(JSON.parse(opts.body).message)); })
  : new Promise(() => {});
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  const input = place.querySelector("input.prism-input"), form = place.querySelector("form.prism-form");
  input.value = "Delete the old branch."; form.dispatch("submit");
  input.value = "Why is the build failing?"; form.dispatch("submit");
  resolvers["Why is the build failing?"]();                       // the newer answer lands first
  let t = Promise.resolve(); for (let i = 0; i < 40; i++) t = t.then(() => null);
  return t.then(() => { resolvers["Delete the old branch."](); for (let i = 0; i < 40; i++) t = t.then(() => null); return t; })
    .then(() => report(place.textContent));
});
""" % answers("Delete the old branch.", "Why is the build failing?"))
    assert "QUESTION" in late and "INSTRUCTION · delete" not in late    # must-refuse: the older answer does not replace it


@needs_node
def test_an_empty_message_is_not_sent_and_says_so():   # must-refuse
    got = run(stub("{}") + """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  const input = place.querySelector("input.prism-input");
  const before = sent.length;
  input.value = "   "; place.querySelector("form.prism-form").dispatch("submit");
  report({ extra: sent.length - before, text: place.textContent });
});
""")
    assert got["extra"] == 0 and "NOTHING TO READ" in got["text"] and "Type a message." in got["text"]


@needs_node
@pytest.mark.parametrize("waiting", [0, 3])
def test_four_bands_open_their_places_and_waiting_opens_in_place_with_the_count(waiting):
    got = run(DRAW.replace("report({ text: place.textContent, links });", """
  const b = place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-waiting"))[0];
  report({ text: place.textContent, links, waiting: [b.textContent, b.getAttribute("aria-expanded"),
    b.parentNode.tagName, b.getAttribute("aria-controls")] });""") % waiting)
    hrefs = [h for h, _ in got["links"]]
    assert hrefs == ["#map/~agents", "#work", "#record"]          # must-refuse: Rules and Waiting are no longer links out
    text, expanded, parent, controls = got["waiting"]
    assert text.startswith("Waiting on you" + str(waiting))
    assert expanded == "false" and parent == "H2" and controls == "band-panel-waiting"   # Koinos C3


# The Waiting band opened in place (APP-DESIGN depth 2, build step 2). The test sets the place's data as a read would,
# since fetch answers never here.
OPEN = """
applyFrame({ name: null, word: null, waiting: %d, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  %s
  const place = document.getElementById("place");
  const b = place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-waiting"))[0];
  b.click();
  const again = place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-waiting"))[0];
  const panel = place.all((e) => e.getAttribute("id") === "band-panel-waiting")[0];
  report({ expanded: again.getAttribute("aria-expanded"), hidden: panel.hidden, text: panel.textContent,
    links: panel.all((e) => e.tagName === "A").map((a) => a.getAttribute("href")) });
});
"""
CARD = ('{ key: "Alder/A-1", seat: "Alder", id: "A-1", kind: "decision", title: "Pick one", why: "because", '
        'question: "Which?", options: ["first", "second"], state: "%s", asks: "Alder", acts: "Alder", '
        'at: "2026-10-01T10:00:00Z", notes: [] }')


@needs_node
def test_waiting_opens_in_place_and_shows_the_waiting_cards():
    data = 'S.data.waiting = { cards: [%s, %s], seats: ["Alder"] };' % (CARD % "waiting", (CARD % "closed").replace("A-1", "A-2"))
    got = run(OPEN % (1, data))
    assert got["expanded"] == "true" and got["hidden"] is False
    assert "Pick one" in got["text"] and "Which?" in got["text"]
    assert got["text"].count("Pick one") == 1                       # must-refuse: a closed card is not shown here
    assert "#waiting" in got["links"]                               # the whole place, parked and done, one link away


@needs_node
def test_waiting_opened_before_its_read_says_so_never_nothing():   # must-refuse (Koinos D1): no false empty list
    got = run(OPEN % (2, "S.data.waiting = undefined;"))
    assert "Reading your cards" in got["text"]
    assert "Nothing is waiting" not in got["text"]


RULES = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  %s
  const place = document.getElementById("place");
  const open = () => place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-rules"))[0];
  open().click();
  const panel = () => place.all((e) => e.getAttribute("id") === "band-panel-rules")[0];
  const first = { text: panel().textContent, expanded: open().getAttribute("aria-expanded"),
    rows: panel().all((e) => e.tagName === "BUTTON" && e.className.startsWith("rule-row")).map((b) => b.textContent),
    switches: panel().all((e) => e.getAttribute("role") === "switch").length,
    links: panel().all((e) => e.tagName === "A").map((a) => a.getAttribute("href")) };
  const row = panel().all((e) => e.tagName === "BUTTON" && e.className.startsWith("rule-row"))[0];
  if (row) row.click();
  const aside = panel().all((e) => e.tagName === "ASIDE")[0];
  report({ first, aside: aside ? aside.textContent : null, current: panel().all((e) => e.getAttribute("aria-current") === "true").length });
});
"""
RULE = ('{ id: "%s", statement: "%s", enabled: %s, applies_when: "when you ask", '
        'provenance: { type: "LEARNED", words: "when I ask, just answer" } }')


@needs_node
def test_rules_open_in_place_grouped_with_one_rule_beside_and_no_switch():
    own = RULE % ("r1", "A question asks for an answer, not a change", "true")
    off = RULE % ("r2", "Name the version on every change", "false")
    data = ('PRISM.rules.data = { env: "Me", own: [%s, %s], agents: [], base: [], '
            'tests: [{ message: "m", rules: ["r1"] }] }; PRISM.rules.at = Date.now();' % (own, off))
    got = run(RULES % data)
    first = got["first"]
    assert first["expanded"] == "true" and "In Me · 2 rules" in first["text"]
    assert first["rows"][0] == "A question asks for an answer, not a change"
    assert first["rows"][1].endswith("off")                          # an off rule says so
    assert first["switches"] == 0                                     # must-refuse: the band shows, Rules changes
    assert first["links"] == ["#rules"]
    assert got["current"] == 1
    for part in ("Your words", "when I ask, just answer", "1 test, from your corrections", "when you ask"):
        assert part in got["aside"], part


@needs_node
def test_rules_opened_before_their_read_say_so_never_none():        # must-refuse (Koinos D1)
    got = run(RULES % "PRISM.rules.data = null;")
    assert "Reading your rules" in got["first"]["text"]
    assert "No rules yet" not in got["first"]["text"] and got["aside"] is None


@needs_node
def test_waiting_draws_this_machines_own_inbox_which_its_count_includes():      # Koinos W1
    machine = (CARD % "waiting").replace("Pick one", "From the machine").replace("A-1", "M-1")
    got = run(OPEN % (1, 'S.data.waiting = { cards: [], machine_inbox: [%s], seats: [] };' % machine))
    assert "This machine's own inbox · 1 waiting" in got["text"] and "From the machine" in got["text"]
    assert "Nothing is waiting for you." not in got["text"]                      # must-refuse: the count said 1


@needs_node
@pytest.mark.parametrize("state,words", [
    ("PRISM.readErr = 'the server answered 500'; S.data.waiting = undefined;", "Could not read your cards: the server answered 500."),
    ("PRISM.readErr = 'timed out'; S.data.waiting = { cards: [%s], seats: [] };" % (CARD % "waiting"),
     "these are the cards last read"),
], ids=["failed first read", "stale read"])
def test_a_failed_read_is_said_in_the_band(state, words):                       # Koinos D1, T1
    # The click's own read never answers in node, so the state set before it is what the panel draws.
    got = run(OPEN % (1, state))
    assert words in got["text"]


@needs_node
def test_escape_used_by_the_drawer_does_not_close_the_band_too():              # must-refuse (Koinos E1)
    got = run("""
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  S.data.waiting = { cards: [], seats: [] };
  const place = document.getElementById("place");
  const band = () => place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-waiting"))[0];
  band().click();
  onKey({ key: "Escape", defaultPrevented: true, preventDefault() {} });
  const after_drawer = band().getAttribute("aria-expanded");
  onKey({ key: "Escape", defaultPrevented: false, preventDefault() {} });
  report([after_drawer, band().getAttribute("aria-expanded")]);
});
""")
    assert got == ["true", "false"]       # the drawer's Escape leaves the band open; a plain Escape closes it


@needs_node
def test_rules_are_read_through_the_pages_own_get_and_drawn():                 # T1: the read itself runs
    got = run("""
const asked = [];
globalThis.fetch = (path, opts) => {
  asked.push([path, opts.headers["X-Semantext"], opts.method || "GET"]);
  const answers = { "/api/state": { active: "me" }, "/api/profile?name=me": { environment: { title: "Me" },
      entries: [{ id: "r1", statement: "Read before you write", enabled: true }] },
    "/api/profile?name=base": { entries: [{ id: "b1", statement: "Shared one", archived: true }] }, "/api/agents": { agents: [] } };
  return Promise.resolve({ ok: true, json: () => Promise.resolve(answers[path]) });
};
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-rules"))[0].click();
  let ticks = Promise.resolve();
  for (let i = 0; i < 20; i++) ticks = ticks.then(() => null);   // the read's promise chain, several hops long
  return ticks.then(() => {
    const panel = place.all((e) => e.getAttribute("id") === "band-panel-rules")[0];
    report({ asked, text: panel.textContent });
  });
});
""")
    band = [a for a in got["asked"] if not a[0].startswith("/api/v2/") and a[0] != "/api/read"]   # the frame read and the
    assert [a[0] for a in band] == ["/api/state", "/api/profile?name=me", "/api/profile?name=base", "/api/agents"]   # reader aside
    assert all(a[1] == "1" and a[2] == "GET" for a in band)                      # reads only, with the header
    assert "In Me · 1 rule" in got["text"] and "Read before you write" in got["text"]
    assert "Shared one" not in got["text"]                                       # an archived rule is not drawn


@needs_node
def test_waiting_opened_with_none_waiting_says_nothing_waits():
    got = run(OPEN % (0, 'S.data.waiting = { cards: [%s], seats: [] };' % (CARD % "parked")))
    assert "Nothing is waiting for you." in got["text"]
    assert "Pick one" not in got["text"]


@needs_node
def test_with_nothing_read_the_waiting_band_says_so():   # must-refuse (Koinos P1): never a false "0, nothing"
    got = run("""
location.hash = "#prism";
route();
return settled().then(() => {
  const band = document.getElementById("place").querySelector(".band-waiting");
  report([band.querySelector(".band-count").textContent, band.getAttribute("aria-label")]);
});
""")
    assert got == ["…", "Waiting on you, not read yet"]


@needs_node
@pytest.mark.parametrize("reply,says", [
    ("{ ok: false, status: 502, statusText: 'Bad Gateway', json: () => Promise.reject(new SyntaxError('<html>')) }", "Bad Gateway"),
    ("{ ok: true, status: 200, json: () => Promise.reject(new SyntaxError('<html>')) }", "the server's answer was not readable"),
], ids=["error page", "ok but not json"])
def test_the_rules_band_read_checks_the_status_and_survives_a_body_that_is_not_json(reply, says):   # item 4
    got = run("""
globalThis.fetch = (path, opts) => path.startsWith("/api/v2/") || path === "/api/read" ? new Promise(() => {}) : Promise.resolve(%s);
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-rules"))[0].click();
  let ticks = Promise.resolve();
  for (let i = 0; i < 30; i++) ticks = ticks.then(() => null);
  return ticks.then(() => report(place.all((e) => e.getAttribute("id") === "band-panel-rules")[0].textContent));
});
""" % reply)
    assert f"Could not read your rules: {says}." in got and "No rules yet" not in got      # said, never an empty list


@needs_node
def test_typing_reading_and_the_presets_send_the_words_in_one_body_and_never_in_an_address():   # must-refuse (Koinos P3)
    got = run("""
const sent = [], bodies = [];
globalThis.fetch = (path, opts) => { sent.push(String(path)); bodies.push((opts && opts.body) || ""); return new Promise(() => {}); };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const before = [sent.length, location.hash, document.title];
  const place = document.getElementById("place");
  const input = place.querySelector("input.prism-input");
  input.value = "MARKER-7f3a delete everything";
  place.querySelector("form.prism-form").dispatch("submit");
  for (const b of place.all((e) => e.tagName === "BUTTON" && e.classList.contains("chip"))) b.click();
  report({ before, after: [sent.length, location.hash, document.title], sent, bodies,
           input: [input.getAttribute("spellcheck"), input.getAttribute("autocomplete")] });
});
""")
    assert got["after"][1:] == got["before"][1:]                                        # no new address or title
    assert got["after"][0] > got["before"][0]                                           # a read is a request, now
    assert not [p for p in got["sent"] if "MARKER" in p]                                # the words are in no address
    assert any("MARKER-7f3a delete everything" in b for b in got["bodies"])             # they travel in a body
    assert all(p == "/api/read" for p, b in zip(got["sent"], got["bodies"]) if b)       # and only to the reader
    assert got["input"] == ["false", "off"]                                             # P4


@needs_node
def test_the_prism_page_posts_only_to_the_reader():   # must-refuse: no other change, and nothing in an address
    got = run("""
const sent = [];
globalThis.fetch = (path, opts) => { sent.push([path, (opts && opts.method) || "GET"]); return new Promise(() => {}); };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => report(sent));
""")
    assert [p for p, m in got if m == "POST"] == ["/api/read"]                         # the one POST: the reader, once
    assert not [p for p, m in got if m == "GET" and re.search(r"read|card|model|ask|\?.*=", p)]   # no GET names the message
