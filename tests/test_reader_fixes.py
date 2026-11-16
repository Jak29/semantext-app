"""The reader on the page, after its attack (R1, R4, R5, R6): no literal "null", no stale reading, two headed readings,
and an answer checked to its last element.

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules, as test_prism_page.py draws.
Each behaviour has a must-pass and a must-refuse beside it.
"""
from __future__ import annotations

import json

import pytest

from semantext import reading
from test_one_page import WORLD
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Every text node of a drawn page that is the word the DOM writes for a missing value.
WALK = """
const nulls = (root) => {
  const out = [];
  const walk = (n) => { for (const c of n.childNodes || []) { if (c.nodeType === 3) { if (c.data === "null" || c.data === "undefined") out.push(c.data + " in " + (n.className || n.tagName)); } else walk(c); } };
  walk(root);
  return out;
};
const TICKS = () => { let t = Promise.resolve(); for (let i = 0; i < 40; i++) t = t.then(() => null); return t; };
"""


def answers(*messages):
    return json.dumps({m: {"ok": True, **reading.report(m)} for m in messages}, ensure_ascii=False)


def prism(by, body):
    """Prism opened on a fetch that answers /api/read from `by` (a JSON object by message) at once; every other request waits."""
    return WALK + """
const BY = %s;
const sent = [];
globalThis.fetch = (path, opts) => {
  sent.push(String(path));
  if (path === "/api/read") {
    const got = BY[JSON.parse(opts.body).message];
    return got && got.fail ? Promise.resolve({ ok: false, status: 500, statusText: "x", json: () => Promise.resolve({ error: got.fail }) })
      : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(got) });
  }
  return new Promise(() => {});
};
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
const place = () => document.getElementById("place");
const ask = (words) => { const i = place().querySelector("input.prism-input"); i.value = words; place().querySelector("form.prism-form").dispatch("submit"); return TICKS(); };
""" % by + body


# ---------------------------------------------------------------- R1: the stand-in writes the DOM's "null"
@needs_node
def test_the_stand_in_writes_null_and_undefined_as_text_as_the_dom_does():   # must-refuse: a null is never skipped
    got = run("""
const p = document.createElement("div"), a = document.createElement("span");
p.append(a);
a.before(null); a.after(undefined); p.prepend(null); p.append(undefined);
const order = p.childNodes.map((n) => n.nodeType === 3 ? n.data : n.tagName);
const q = document.createElement("div"); q.replaceChildren(null, undefined, "x");
let threw = null;
try { p.insertBefore(null, a); } catch (e) { threw = e.name === "TypeError"; }
const kept = document.createElement("div"); kept.append(document.createElement("b"), "t");
a.before("s", document.createElement("i"));
report({ order, replaced: q.childNodes.map((n) => n.data), threw, kept: kept.textContent, after: p.childNodes.map((n) => n.nodeType === 3 ? n.data : n.tagName) });
""")
    assert got["order"] == ["null", "null", "SPAN", "undefined", "undefined"]
    assert got["replaced"] == ["null", "undefined", "x"]
    assert got["threw"] is True                      # insertBefore(null) is a TypeError in a browser
    assert got["kept"] == "t"                        # must-pass: real nodes and strings are drawn as they are
    assert got["after"] == ["null", "null", "s", "I", "SPAN", "undefined", "undefined"]


@needs_node
def test_insert_before_puts_a_node_before_the_other_and_moves_it_from_where_it_was():   # must-pass
    got = run("""
const p = document.createElement("div"), a = document.createElement("a"), b = document.createElement("b"), c = document.createElement("i");
p.append(a, b, c);
p.insertBefore(c, a);
const one = p.childNodes.map((n) => n.tagName).join();
p.insertBefore(a, null);
report([one, p.childNodes.map((n) => n.tagName).join(), c.parentNode === p]);
""")
    assert got == ["I,A,B", "I,B,A", True]


# ---------------------------------------------------------------- R1: Prism draws no "null"
@needs_node
@pytest.mark.parametrize("words", ["Hello there", "Thanks, that looks great."])
def test_a_message_naming_no_act_draws_no_null_beside_the_figure(words):   # fails on the base: "null" after the figure
    got = run(prism(answers(words), """
return ask(%s).then(() => report({ bad: nulls(place()), advice: place().all((e) => e.classList.contains("prism-advice")).length,
  text: place().textContent }));
""" % json.dumps(words)))
    assert got["bad"] == []
    assert got["advice"] == 0                                    # must-pass: the list is not drawn when there is nothing in it


@needs_node
def test_the_empty_box_and_a_failed_read_draw_no_null():
    got = run(prism(json.dumps({"Publish it.": {"fail": "nope"}}), """
return ask("").then(() => { const empty = nulls(place()), say = place().textContent.includes("Type a message.");
  return ask("Publish it.").then(() => report({ empty, say, failed: nulls(place()), text: place().textContent })); });
"""))
    assert got["empty"] == [] and got["say"] is True
    assert got["failed"] == [] and "NOT READ" in got["text"]


@needs_node
def test_a_message_that_names_an_act_still_draws_its_advice_list():   # must-pass beside the null fix
    msg = "Publish the release tonight."
    got = run(prism(answers(msg), """
return ask(%s).then(() => report({ bad: nulls(place()), rows: place().all((e) => e.classList.contains("prism-advice-row")).length }));
""" % json.dumps(msg)))
    assert got["bad"] == [] and got["rows"] >= 1


PLACES = ["#prism", "#waiting", "#work", "#record", "#rules", "#rules/test", "#today", "#projects", "#documents", "#diffmap",
          "#map", "#map/~agents", "#plugins", "#settings"]


@needs_node
def test_no_drawn_page_holds_a_text_node_null_or_undefined():
    # Every place, as drawn while its read has not come (fetch waits) and from the Rules world of test_one_page: the walk
    # looks at the page and the bar. It is the whole-page version of the null fix above: a conditional that hands null or
    # undefined to replaceChildren, append, prepend, before or after shows here as the word.
    got = run(WALK + """
globalThis.fetch = () => new Promise(() => {});
applyFrame({ name: null, word: null, waiting: 2, problems: [], outside: [] });
const seen = {};
const next = (list, i) => i >= list.length ? Promise.resolve() : (() => {
  location.hash = list[i]; route();
  return settled().then(() => TICKS()).then(() => {
    seen[list[i]] = [...nulls(document.getElementById("place")), ...nulls(document.getElementById("bar-place"))];
    return next(list, i + 1);
  });
})();
return next(%s, 0).then(() => report(seen));
""" % json.dumps(PLACES))
    assert {k: v for k, v in got.items() if v} == {}, got
    assert set(got) == set(PLACES)                               # must-refuse: a place the walk skipped is not "clean"


@needs_node
def test_the_try_a_message_view_draws_no_null_for_a_message_naming_no_act():
    msg = "Hello there"
    got = run(WORLD + WALK + """
const BY = %s;
globalThis.fetch = (path, opts) => path === "/api/read"
  ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BY[JSON.parse(opts.body).message]) })
  : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ agent: "helper", words: "own", basis: "text", environment: "default",
      form: "full", layers: [], bytes: 1, left_out: 0, answers: [], waiting: [], reading: { readings: [], decisions: [] }, text: "card" }) });
return moved.tryMessage(%s, "", "helper", "").then(() => report(nulls(document.getElementById("testFlow"))));
""" % (answers(msg), json.dumps(msg)))
    assert got == []


# ---------------------------------------------------------------- R4: a stale reading is cleared at once
def pending_second(js_after):
    """Prism: the first message answers at once; the second never does (its resolver is kept in `late`)."""
    first, second = "Publish the release tonight.", "Publish the release tonight. Do not publish it."
    return prism(json.dumps({first: {"ok": True, **reading.report(first)}}), """
const late = {};
const base = globalThis.fetch;
globalThis.fetch = (path, opts) => path === "/api/read" && JSON.parse(opts.body).message === %s
  ? new Promise((go) => { late.go = go; }) : base(path, opts);
return settled().then(() => ask(%s)).then(() => {
  const before = place().textContent;
  const hadConfirm = before.includes("your words appear to say go: confirm");
  return ask(%s).then(() => { %s });
});
""" % (json.dumps(second), json.dumps(first), json.dumps(second), js_after))


@needs_node
def test_while_new_words_are_read_the_old_advice_and_rays_are_gone():   # fails on the base: the old go-confirm stays drawn
    got = run(pending_second("""
  const after = place().textContent;
  report({ hadConfirm, after, advice: place().all((e) => e.classList.contains("prism-advice")).length,
    rays: place().all((e) => e.getAttribute("class") === "ray-kind").map((e) => e.textContent),
    status: place().querySelector("p.prism-status").textContent });
"""))
    assert got["hadConfirm"] is True                             # must-pass: the control reading did draw the confirm
    assert "appear to say go" not in got["after"] and got["advice"] == 0
    assert got["rays"] == ["READING…"]                           # the figure says reading and shows no old ray
    assert got["status"] == "Reading…"


@needs_node
def test_the_new_reading_replaces_the_pending_one_when_it_lands():   # must-pass: clearing does not stop the answer being drawn
    second = "Why is the build failing?"
    got = run(prism(answers(second), """
return ask("Publish it.").then(() => ask(%s)).then(() => report({ rays: place().all((e) => e.getAttribute("class") === "ray-kind").map((e) => e.textContent),
  status: place().querySelector("p.prism-status").textContent }));
""" % json.dumps(second)))
    assert got["rays"] == ["QUESTION · edit"] and got["status"] == ""


@needs_node
def test_try_a_message_clears_the_old_readings_while_new_words_are_read():   # fails on the base: the old quick reading stays
    first, second = "Publish the release tonight.", "Hello there"
    got = run(WORLD + """
const BY = %s;
const hold = {};
globalThis.fetch = (path, opts) => {
  const b = opts && opts.body ? JSON.parse(opts.body) : null;
  if (path === "/api/read") return b.message === %s ? new Promise((go) => { hold.go = go; })
    : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BY[b.message]) });
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ agent: "helper", words: "own", basis: "text", environment: "default",
    form: "full", layers: [], bytes: 1, left_out: 0, answers: [], waiting: [], reading: { readings: [{ label: "AN INSTRUCTION", says: "says", rule: "r" }], decisions: [] }, text: "card" }) });
};
const flow = () => document.getElementById("testFlow").textContent;
return moved.tryMessage(%s, "", "helper", "").then(() => {
  const old = flow();
  moved.tryMessage(%s, "", "helper", "");
  report({ old, now: flow() });
});
""" % (answers(first), json.dumps(second), json.dumps(first), json.dumps(second)))
    assert "your words appear to say go: confirm" in got["old"] and "AN INSTRUCTION" in got["old"]      # the control drew both
    assert "appear to say go" not in got["now"] and "AN INSTRUCTION" not in got["now"] and "INSTRUCTION" not in got["now"]
    assert "Reading…" in got["now"]


# ---------------------------------------------------------------- R5: two readings, each headed with what it reads
@needs_node
def test_each_reading_is_headed_with_what_it_reads_and_neither_sentence_speaks_for_both():
    msg = "Publish the release tonight."
    got = run(WORLD + """
const BY = %s;
globalThis.fetch = (path, opts) => path === "/api/read"
  ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BY[JSON.parse(opts.body).message]) })
  : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ agent: "helper", words: "own", basis: "text", environment: "default",
      form: "full", layers: [], bytes: 1, left_out: 0, answers: [], waiting: [], reading: { readings: [{ label: "AN INSTRUCTION", says: "says", rule: "r" }], decisions: [] }, text: "card" }) });
return moved.tryMessage(%s, "", "helper", "").then(() => {
  const heads = document.getElementById("testFlow").all((e) => e.tagName === "H2").map((e) => e.textContent);
  report({ heads, text: document.getElementById("testFlow").textContent });
});
""" % (answers(msg), json.dumps(msg)))
    assert got["heads"][0] == "Clause by clause: what it asks for, act by act"
    assert got["heads"][1] == "The quick reading: what kind of message this is"
    assert got["text"].count("Semantext's quick reading") == 1   # the quick reading's note is its own, said once
    assert got["text"].count("The same reader as semantext read") == 1


@needs_node
def test_a_failed_reading_keeps_its_heading_and_the_other_is_headed_beside_it():   # must-pass for the failure states
    got = run(WORLD + """
globalThis.fetch = (path) => path === "/api/read" ? Promise.resolve({ ok: false, status: 500, statusText: "x", json: () => Promise.resolve({ error: "no" }) })
  : new Promise(() => {});
moved.S.reader = { busy: true, message: "m" };
const busy = moved.clauseFlow().textContent;
moved.S.reader = { err: "no", message: "m" };
report([busy, moved.clauseFlow().textContent]);
""")
    assert all(t.startswith("Clause by clause: what it asks for, act by act") for t in got)


# ---------------------------------------------------------------- R6: the answer is checked to its last element
GOOD = reading.report("Publish the release tonight.")
SHAPE = "the answer was not in the shape the page expects"
BAD_ANSWERS = {
    "a null reading": {**GOOD, "readings": [None]},
    "a reading with no acts": {**GOOD, "readings": [{k: v for k, v in GOOD["readings"][0].items() if k != "acts"}]},
    "acts not strings": {**GOOD, "readings": [{**GOOD["readings"][0], "acts": [1]}]},
    "acts a string": {**GOOD, "readings": [{**GOOD["readings"][0], "acts": "publish"}]},
    "a clause that is a number": {**GOOD, "readings": [{**GOOD["readings"][0], "clause": 5}]},
    "a label that is missing": {**GOOD, "readings": [{k: v for k, v in GOOD["readings"][0].items() if k != "label"}]},
    "a time that is a number": {**GOOD, "readings": [{**GOOD["readings"][0], "time": 5}]},
    "an advice of null": {**GOOD, "advice": [None]},
    "an advice with no act": {**GOOD, "advice": [{k: v for k, v in GOOD["advice"][0].items() if k != "act"}]},
    "an advice with no rule": {**GOOD, "advice": [{k: v for k, v in GOOD["advice"][0].items() if k != "rule"}]},
    "a word that is a number": {**GOOD, "advice": [{**GOOD["advice"][0], "word": 3}]},
    "a bound that is a number": {**GOOD, "advice": [{**GOOD["advice"][0], "bound": 3}]},
    "covers that is a string": {**GOOD, "advice": [{**GOOD["advice"][0], "covers": "yes"}]},
    "readings not a list": {**GOOD, "readings": {}},
    "a clipped that is a string": {**GOOD, "clipped": "yes"},
    "clipped with no max": {**{k: v for k, v in GOOD.items() if k != "max_chars"}, "clipped": True},
}


@needs_node
@pytest.mark.parametrize("name", list(BAD_ANSWERS))
def test_a_well_shaped_wrong_answer_is_a_failure_and_clears_the_figure(name):   # must-refuse: fails on the base (it throws in show)
    msg_ok, msg_bad = "Delete the old branch.", "Publish the release tonight."
    by = json.dumps({msg_ok: {"ok": True, **reading.report(msg_ok)}, msg_bad: BAD_ANSWERS[name]})
    got = run(prism(by, """
return ask(%s).then(() => { const good = place().textContent; return ask(%s).then(() => report({ good,
  status: place().querySelector("p.prism-status").textContent, cls: place().querySelector("p.prism-status").className,
  rays: place().all((e) => e.getAttribute("class") === "ray-kind").map((e) => e.textContent), text: place().textContent })); });
""" % (json.dumps(msg_ok), json.dumps(msg_bad))))
    assert "INSTRUCTION · delete" in got["good"]                  # the control: a good answer drew
    assert got["status"] == f"Could not read it: {SHAPE}. No reading is shown." and "warn" in got["cls"]
    assert got["rays"] == ["NOT READ"] and "INSTRUCTION · delete" not in got["text"]    # the figure is cleared, not left stale


@needs_node
def test_every_reader_answer_of_the_real_reader_is_in_the_shape_the_page_expects():   # must-pass: no good answer is refused
    from test_reading import CASES
    msgs = [c[0] if isinstance(c, (tuple, list)) else c for c in CASES][:80] + ["", "x" * 25_000, "Привет, publish it", "Yes"]
    by = json.dumps({m: {"ok": True, **reading.report(m)} for m in msgs}, ensure_ascii=False)
    got = run("""
const BY = %s;
globalThis.fetch = (path, opts) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BY[JSON.parse(opts.body).message]) });
const out = [];
return Promise.all(Object.keys(BY).map((m) => readMessage(m).then(() => null, (e) => m.slice(0, 40) + ": " + e.message))).then((r) => report(r.filter(Boolean)));
""" % by)
    assert got == []


@needs_node
def test_try_a_message_says_the_wrong_shape_and_shows_no_reading():
    msg = "Publish the release tonight."
    got = run(WORLD + """
globalThis.fetch = (path) => path === "/api/read"
  ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ ok: true, readings: [null], advice: [] }) })
  : Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ agent: "helper", words: "own", basis: "text", environment: "default",
      form: "full", layers: [], bytes: 1, left_out: 0, answers: [], waiting: [], reading: { readings: [], decisions: [] }, text: "card" }) });
return moved.tryMessage(%s, "", "helper", "").then(() => report(document.getElementById("testFlow").textContent));
""" % json.dumps(msg))
    assert "Could not read it clause by clause: " + SHAPE + ". No reading is shown." in got
    assert "INSTRUCTION" not in got and "undefined" not in got


@needs_node
def test_a_page_test_may_declare_its_own_answer():   # fails on the base: reader.js exported `answer`, handed to every test as a name
    assert run("let answer = 1; let reply = 2; report([answer, reply, typeof readerAnswer, typeof readMessage]);") == [1, 2, "function", "function"]