"""Prism, the home of the page (1.6.2): the illustrated reading and the five bands of your spectrum.

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules, as test_one_page.py draws.
"""
from __future__ import annotations

import re

import pytest

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


@needs_node
def test_prism_reads_the_example_message_and_says_it_is_an_illustration():
    got = run(DRAW % 0)
    for kind in ("QUESTION", "SUGGESTION", "TIME", "YOUR WORD"):                       # "Could we maybe ship ... later?"
        assert kind in got["text"], kind
    assert "INSTRUCTION" not in got["text"]                                             # must-refuse: no false fallback
    assert "An illustration of how Semantext reads" in got["text"]
    assert "Semantext sends nothing you type here" in got["text"]                      # P4's wording


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
    band = [a for a in got["asked"] if not a[0].startswith("/api/v2/")]          # the app's own frame read aside
    assert [a[0] for a in band] == ["/api/state", "/api/profile?name=me", "/api/profile?name=base", "/api/agents"]
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
def test_typing_reading_and_the_presets_send_and_keep_nothing():   # must-refuse (Koinos P3)
    got = run("""
const sent = [];
globalThis.fetch = (path, opts) => { sent.push(String(path)); return new Promise(() => {}); };
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
  report({ before, after: [sent.length, location.hash, document.title], sent,
           input: [input.getAttribute("spellcheck"), input.getAttribute("autocomplete")] });
});
""")
    assert got["after"] == got["before"]                                                 # no request, address or title
    assert not [p for p in got["sent"] if "MARKER" in p]
    assert got["input"] == ["false", "off"]                                             # P4


@needs_node
def test_the_prism_page_sends_nothing():   # must-refuse: the reading is drawn here, never asked of a server
    got = run("""
const sent = [];
globalThis.fetch = (path, opts) => { sent.push([path, (opts && opts.method) || "GET"]); return new Promise(() => {}); };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => report(sent));
""")
    assert all(method == "GET" for _, method in got)                                   # reads only, as every place
    assert not [p for p, _ in got if re.search(r"read|card|model|ask", p)]             # nothing about the message
