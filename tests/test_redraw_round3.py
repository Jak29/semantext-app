"""The third attack of the re-draw (D7 to D13, and the loop D8): what a draw that changes nothing does, and what a selection,
a focus and a scroll do through the page's own periodic read.

D8   an open Waiting shelf drew itself without end: Chrome fires "toggle" on a details a draw made, even when it is
     already out of the page, and the shelf's handler drew again. A toggle is acted on only when it is a person's own.
D7   the machine's readings (cpu_busy, memory_free) differ at every read; counting them as a change made every node new at
     every periodic draw. Tested through load(), the path the page reads by.
D9   a selection in a plug-in module's output was dropped at every draw: the module draws after its import resolves.
D10  the bar's plug-in tabs were new nodes at every read, outside keep().
D11  the problems banner: an unkeyed list let a selection land on the same characters in another problem.
D12  Diffmap's copy box was destroyed by the next draw, and D.box kept its command.
D13  the copy box's own scroll went back to the top at every draw.

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules. Each must-pass has its must-refuse
beside it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# ---------------------------------------------------------------- Waiting, with a Done shelf and a counted draw
SHELF = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  const closed = { key: "Alder/A-1", seat: "Alder", id: "A-1", kind: "decision", title: "Pick one", why: "because the first is safer",
    question: "Which?", options: ["first", "second"], state: "closed", asks: "Alder", acts: "Alder", at: "2026-10-01T10:00:00Z", notes: [], own_inbox: true };
  S.data.waiting = { cards: [closed], seats: ["Alder"] };
  const place = document.getElementById("place");
  let draws = 0;                                         // how many times Waiting drew its cards
  const first = W.list.replaceChildren.bind(W.list);
  W.list.replaceChildren = (...a) => { draws++; return first(...a); };
  const shelfNode = () => W.done.childNodes[0];
  //BODY
});
"""


def shelf(body: str):
    return run(SHELF.replace("//BODY", body))


@needs_node
def test_an_open_shelf_draws_once_however_many_toggles_chrome_fires_on_the_details_the_draw_made():
    got = shelf("""
  S.open.add("shelf:done");
  fill();
  const base = draws;
  for (let i = 0; i < 20; i++) shelfNode().dispatch("toggle");   // Chrome fires one on every details a draw makes, once open is set
  report({ more: draws - base, open: S.open.has("shelf:done"), shown: shelfNode().open, cards: W.done.textContent.includes("Pick one") });""")
    assert got["more"] == 0                                # the loop: not one more draw
    assert got["open"] is True and got["shown"] is True and got["cards"] is True   # and the shelf stays open, with its cards


@needs_node
def test_a_toggle_on_a_details_that_is_no_longer_in_the_page_calls_no_fill():
    got = shelf("""
  S.open.add("shelf:done");
  fill();
  const old = shelfNode();
  S.rev++;                                               // a read that found a change: the draw makes new nodes
  fill();                                                // the old details is out of the page now
  const gone = !document.contains(old);
  const base = draws;
  old.open = false;                                      // even a toggle that says something other than what is remembered
  old.dispatch("toggle");
  report({ gone, more: draws - base, open: S.open.has("shelf:done") });""")
    assert got["gone"] is True
    assert got["more"] == 0 and got["open"] is True         # not drawn, and the memory is not changed by it


@needs_node
def test_a_persons_own_toggle_still_draws_and_is_remembered():                                   # must-refuse the other way
    got = shelf("""
  fill();
  const closedShelf = shelfNode();
  const hadCards = W.done.textContent.includes("Pick one");
  closedShelf.open = true;                               // a click on the summary: the browser sets open, then fires toggle
  const base = draws;
  closedShelf.dispatch("toggle");
  const opened = [draws - base, S.open.has("shelf:done"), shelfNode().open, W.done.textContent.includes("Pick one")];
  shelfNode().open = false;
  const base2 = draws;
  shelfNode().dispatch("toggle");
  report({ hadCards, opened, shut: [draws - base2, S.open.has("shelf:done"), shelfNode().open, W.done.textContent.includes("Pick one")] });""")
    assert got["hadCards"] is False
    assert got["opened"] == [1, True, True, True]
    assert got["shut"] == [1, False, False, False]


@needs_node
def test_every_fold_made_by_disclosure_acts_only_on_a_persons_toggle():
    got = shelf("""
  let calls = 0;
  const d = disclosure("k:test", "A fold", null, () => calls++);
  d.open = true;                                         // not in the page: the draw's own event
  d.dispatch("toggle");
  const detachedCase = [calls, S.open.has("k:test")];
  place.append(d);
  d.open = false; d.dispatch("toggle");                  // in the page, and it says what is remembered: shut
  const same = [calls, S.open.has("k:test")];
  d.open = true; d.dispatch("toggle");                   // a person opens it
  const opened = [calls, S.open.has("k:test")];
  d.dispatch("toggle");                                  // the same word again
  const again = [calls, S.open.has("k:test")];
  d.open = false; d.dispatch("toggle");
  report({ detachedCase, same, opened, again, shut: [calls, S.open.has("k:test")] });""")
    assert got["detachedCase"] == [0, False]
    assert got["same"] == [0, False]
    assert got["opened"] == [1, True]
    assert got["again"] == [1, True]
    assert got["shut"] == [2, False]


# ---------------------------------------------------------------- D7: the live read
LIVE = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  const waitingCard = { key: "Alder/A-1", seat: "Alder", id: "A-1", kind: "decision", title: "Pick one", why: "because the first is safer",
    question: "Which?", options: ["first", "second"], state: "waiting", asks: "Alder", acts: "Alder", at: "2026-10-01T10:00:00Z", notes: [], own_inbox: true };
  const compute = (cpu, over) => Object.assign({ verdict: "free", reasons: [], not_read: [], could_not_tell: [], games: [], cpu_busy: cpu, memory_free: 60.0 }, over || {});
  const reply = (cpu, over, cards) => ({ cards: cards || [waitingCard], seats: ["Alder"],
    frame: { name: null, word: null, waiting: 1, problems: [], outside: [], compute: compute(cpu, over) } });
  let served = reply(10);
  globalThis.fetch = async (url) => (String(url).includes("/api/v2/waiting")
    ? { ok: true, json: async () => JSON.parse(JSON.stringify(served)) }
    : { ok: false, status: 404, json: async () => ({ error: "none" }) });
  const place = document.getElementById("place");
  const whyNode = () => place.all((e) => e.className === "why")[0].childNodes[0];
  //BODY
});
"""


def live(body: str):
    return run(LIVE.replace("//BODY", body))


@needs_node
def test_a_read_that_differs_only_in_the_machines_readings_changes_nothing_on_the_page():
    got = live("""
  const first = await load("waiting");
  const rev = S.rev, w = whyNode();
  const sel = window.getSelection();
  sel.setBaseAndExtent(w, 0, w, 7);
  served = reply(37.5);
  served.frame.compute.memory_free = 41.2;               // what every ten-second read does: both readings move
  const second = await load("waiting");
  served = reply(64.0);
  const third = await load("waiting");
  report({ first, second, third, rev: S.rev - rev, same: whyNode() === w, kept: String(sel), seen: S.frame.compute.cpu_busy });""")
    assert got["first"] is True
    assert got["second"] is False and got["third"] is False
    assert got["rev"] == 0                                  # S.rev did not move: the nodes are the ones drawn
    assert got["same"] is True and got["kept"] == "because"
    assert got["seen"] == 64.0                              # and the page still holds the newest reading


@needs_node
def test_a_read_that_changes_the_verdict_or_a_card_is_still_a_change():                          # must-refuse
    got = live("""
  await load("waiting");
  const rev = S.rev, w = whyNode();
  served = reply(95, { verdict: "light", reasons: ["the processor is 95% busy"] });
  const verdict = await load("waiting");
  const afterVerdict = [S.rev - rev, whyNode() !== w, document.getElementById("gaming").textContent];
  const rev2 = S.rev;
  served = reply(95, { verdict: "light", reasons: ["the processor is 96% busy"] });
  const reason = await load("waiting");
  const changed = Object.assign({}, waitingCard, { why: "because the second is safer" });
  served = reply(95, { verdict: "light", reasons: ["the processor is 96% busy"] }, [changed]);
  const card = await load("waiting");
  report({ verdict, afterVerdict, reason, reasonRev: S.rev - rev2, card, text: place.textContent.includes("second is safer") });""")
    assert got["verdict"] is True and got["afterVerdict"][0] == 1 and got["afterVerdict"][1] is True
    assert got["afterVerdict"][2] == "Light work only"
    assert got["reason"] is False                           # D20: the same reason with a number that moved is not a change (a new reason is: round 4)
    assert got["card"] is True and got["text"] is True


# ---------------------------------------------------------------- D9, D10: plug-in places and the bar's tabs
FRAME = """
const place = (name, over) => Object.assign({ name, title: name[0].toUpperCase() + name.slice(1), origin: "semantext-" + name, version: "0.3", module: true }, over || {});
const frameOf = (...places) => ({ name: null, word: null, waiting: 0, problems: [], outside: places });
"""

TIX = """
export function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("p", null, "Ticket one: the printer on floor two is broken"), h("p", null, "Ticket two: " + data.n + " items listed"));
}
"""


def modules(tmp_path, **files) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / f"{name}.js").write_text(text, encoding="utf-8")
    return folder


TIXPAGE = FRAME + """
return (async () => {
  applyFrame(frameOf(place("tix")));
  const sel = window.getSelection();
  const el = document.getElementById("place");
  const give = (n) => { S.data.tix = { place: "tix", frame: S.frame, n }; };
  give(3);
  location.hash = "#tix";
  route();
  await settled();
  const row = (i) => el.all((e) => e.tagName === "P" && e.textContent.startsWith("Ticket"))[i].childNodes[0];
  //BODY
})();
"""


def tix(tmp_path, body: str):
    return run(TIXPAGE.replace("//BODY", body), plugins=modules(tmp_path, tix=TIX))


@needs_node
def test_a_selection_in_a_plugins_output_survives_a_draw_that_changes_nothing_and_the_nodes_stay(tmp_path):
    got = tix(tmp_path, """
  const t = row(0), u = row(1);
  sel.setBaseAndExtent(t, 12, t, 23);
  const said = String(sel);
  fill();                                                // the ten-second draw: same data
  await settled();
  const quiet = [String(sel), row(0) === t, sel.anchorNode === row(0)];   // D16: a module's output is never settled; the page shows its latest draw, and the selection is in it
  const t2 = row(0), u2 = row(1);                        // the nodes the page shows now (a module's output is never settled, D16)
  sel.setBaseAndExtent(t2, 0, u2, 10);                   // across both rows
  const across = String(sel);
  fill();
  await settled();
  report({ said, quiet, across, acrossNow: String(sel), still: row(0) !== t2 && row(1) !== u2 && sel.anchorNode === row(0) && sel.focusNode === row(1) });""")
    assert got["said"] == "the printer"
    assert got["quiet"] == ["the printer", False, True]     # new nodes (D16), the same words, the selection in the nodes the page shows
    assert got["acrossNow"] == got["across"] and got["across"] != "" and got["still"] is True


@needs_node
def test_a_selection_in_a_plugins_output_goes_back_when_the_data_moved_and_the_words_are_the_same(tmp_path):
    got = tix(tmp_path, """
  const t = row(0);
  sel.setBaseAndExtent(t, 12, t, 23);
  S.rev++;                                               // a read that found a change elsewhere in the answer
  fill();
  await settled();
  report({ text: String(sel), collapsed: sel.isCollapsed, replaced: row(0) !== t, inNew: sel.anchorNode === row(0) });""")
    assert got["text"] == "the printer" and got["collapsed"] is False
    assert got["replaced"] is True and got["inNew"] is True  # the module drew new nodes, and the selection is in them


@needs_node
def test_a_selection_in_a_plugins_output_is_let_go_when_its_words_changed_or_when_you_released_it(tmp_path):   # must-refuse
    got = tix(tmp_path, """
  const u = row(1);
  sel.setBaseAndExtent(u, 12, u, 19);                    // "3 items"
  const said = String(sel);
  give(4); S.rev++;
  fill();
  await settled();
  const changed = [String(sel), sel.isCollapsed];
  const t = row(0);
  sel.setBaseAndExtent(t, 12, t, 23);
  sel.removeAllRanges();                                 // released
  fill();
  await settled();
  report({ said, changed, released: String(sel), releasedCollapsed: sel.isCollapsed });""")
    assert got["said"] == "3 items"
    assert got["changed"] == ["", True]                     # not moved onto other words
    assert got["released"] == "" and got["releasedCollapsed"] is True


SLOW = FRAME + """
return (async () => {
  let release;
  const mod = { render(data, el, helpers) { el.replaceChildren(helpers.h("p", null, "Slow words here")); } };
  importer.load = () => new Promise((r) => { release = () => r(mod); });   // the page module is still being fetched
  applyFrame(frameOf(place("slow", { title: "Slowly" })));
  const sel = window.getSelection();
  const tabs = document.getElementById("tabs-outside");
  S.data.slow = { place: "slow", frame: S.frame };
  location.hash = "#slow";
  route();                                               // its draw waits for the module
  for (let i = 0; i < 4; i++) await Promise.resolve();   // the import has been asked for
  const name = tabs.children[0].childNodes[0];           // the tab, drawn again by the move
  //BODY
})();
"""


@needs_node
def test_a_selection_you_made_while_a_plugins_module_was_loading_is_not_taken_back():             # must-refuse
    got = run(SLOW.replace("//BODY", """
  sel.setBaseAndExtent(name, 0, name, 3);                // "Slo"
  fill();                                                // a draw that waits: it holds "Slo"
  sel.setBaseAndExtent(name, 1, name, 4);                // and you select other words while it waits
  release();
  await settled();
  report({ text: String(sel), words: document.getElementById("place").textContent.includes("Slow words here") });"""))
    assert got["words"] is True                             # the module drew
    assert got["text"] == "low"                             # and your new selection is still yours


@needs_node
def test_a_plugins_draw_that_finishes_after_you_left_puts_nothing_back():                           # must-refuse
    got = run(SLOW.replace("//BODY", """
  sel.setBaseAndExtent(name, 0, name, 3);
  fill();
  sel.removeAllRanges();                                 // you click elsewhere, then go to another place
  location.hash = "#waiting";
  route();
  release();
  await settled();
  report({ text: String(sel), collapsed: sel.isCollapsed, place: S.place });"""))
    assert got["place"] == "waiting"
    assert got["text"] == "" and got["collapsed"] is True    # the selection you let go is not brought back


@needs_node
def test_the_bars_plugin_tabs_are_not_drawn_again_by_a_read_that_changed_nothing(tmp_path):
    got = run(FRAME + """
const sel = window.getSelection();
const tabs = document.getElementById("tabs-outside");
applyFrame(frameOf(place("tix", { title: "Tickets" })));
const link = tabs.children[0], name = link.childNodes[0];
link.focus();
sel.setBaseAndExtent(name, 0, name, 7);
applyFrame(frameOf(place("tix", { title: "Tickets" })));   // what every ten-second read does
applyFrame(frameOf(place("tix", { title: "Tickets" })));
report({ same: tabs.children[0] === link, focus: document.activeElement === link, text: String(sel), key: link.getAttribute("data-k") });""")
    assert got["same"] is True and got["focus"] is True and got["text"] == "Tickets"
    assert got["key"] == "outtab:tix"


@needs_node
def test_the_bars_plugin_tabs_are_drawn_when_they_change_and_the_focus_goes_back_to_the_same_tab():   # must-refuse + must-pass
    got = run(FRAME + """
const sel = window.getSelection();
const tabs = document.getElementById("tabs-outside");
applyFrame(frameOf(place("tix"), place("board")));
const link = tabs.children[0];
link.focus();
applyFrame(frameOf(place("tix", { title: "Support" }), place("board")));   // a title changed
const now = tabs.children[0];
const refocus = [now !== link, document.activeElement === now, now.textContent.startsWith("Support")];
const name = now.childNodes[0];
sel.setBaseAndExtent(name, 0, name, 3);
applyFrame(frameOf(place("tix", { title: "Tickets again" }), place("board")));   // the words under the selection changed
const shifted = [String(sel), sel.isCollapsed];
applyFrame(frameOf(place("board")));                     // a place went away
report({ refocus, shifted, names: tabs.children.map((a) => a.getAttribute("data-place")), active: document.activeElement === now });""")
    assert got["refocus"] == [True, True, True]
    assert got["shifted"] == ["", True]
    assert got["names"] == ["board"] and got["active"] is False      # the focus is not given to a tab that is not the one it was on


# ---------------------------------------------------------------- D11: the banner's problems each have their own key
PROBLEMS = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  S.problemsOpen = true;
  const sel = window.getSelection();
  const prob = (text, line) => ({ reader: "rules", source: "a.md", line: line || 3, text });
  const frame = (problems) => ({ name: null, word: null, waiting: 1, problems, outside: [] });
  const box = document.getElementById("problems");
  const items = () => box.all((e) => e.tagName === "LI");
  const textOf = (i) => items()[i].all((e) => e.tagName === "SPAN")[0].childNodes[0];
  //BODY
});
"""


def problems(body: str):
    return run(PROBLEMS.replace("//BODY", body))


@needs_node
def test_a_selection_stays_in_its_problem_when_the_list_shifts_under_it():
    got = problems("""
  applyFrame(frame([prob("zeta thing"), prob("alpha thing"), prob("beta thing")]));
  const t = textOf(2);
  sel.setBaseAndExtent(t, 5, t, 10);                     // "thing" in "Beta thing"
  const said = String(sel);
  applyFrame(frame([prob("omega thing"), prob("zeta thing"), prob("alpha thing"), prob("beta thing")]));
  const owner = sel.anchorNode.parentNode.parentNode.textContent;
  report({ said, text: String(sel), owner, inBeta: sel.anchorNode === textOf(3) });""")
    assert got["said"] == "thing" and got["text"] == "thing"
    assert got["owner"].startswith("Beta thing") and got["inBeta"] is True


@needs_node
def test_a_selection_is_let_go_and_not_moved_when_its_problem_is_gone_or_changed():            # must-refuse
    got = problems("""
  applyFrame(frame([prob("zeta thing"), prob("alpha thing"), prob("beta thing")]));
  let t = textOf(2);
  sel.setBaseAndExtent(t, 5, t, 10);
  applyFrame(frame([prob("zeta thing"), prob("alpha thing")]));              // beta is gone; "thing" stands in the others
  const gone = [String(sel), sel.isCollapsed];
  applyFrame(frame([prob("zeta thing"), prob("alpha thing"), prob("beta thing")]));
  t = textOf(2);
  sel.setBaseAndExtent(t, 5, t, 10);
  applyFrame(frame([prob("zeta thing"), prob("alpha thing"), prob("beta things")]));   // its words changed
  const changed = [String(sel), sel.isCollapsed];
  applyFrame(frame([prob("same thing"), prob("same thing")]));               // two problems alike
  t = textOf(1);
  sel.setBaseAndExtent(t, 5, t, 10);
  applyFrame(frame([prob("same thing")]));                                    // one of them is gone
  report({ gone, changed, alike: [String(sel), sel.isCollapsed], keys: items().map((e) => e.getAttribute("data-k")) });""")
    assert got["gone"] == ["", True]
    assert got["changed"] == ["", True]
    assert got["alike"] == ["", True]                       # the second of two alike is not the first
    assert len(got["keys"]) == 1 and got["keys"][0].startswith("problem:")


@needs_node
def test_two_problems_alike_have_two_keys_and_the_list_keeps_drawing_when_it_changes():
    got = problems("""
  applyFrame(frame([prob("same thing"), prob("same thing"), prob("other")]));
  const keys = items().map((e) => e.getAttribute("data-k"));
  const t = textOf(1);
  sel.setBaseAndExtent(t, 5, t, 10);
  applyFrame(frame([prob("same thing"), prob("same thing"), prob("other"), prob("more")]));
  report({ keys, text: String(sel), second: sel.anchorNode === textOf(1), shown: box.textContent.includes("More") });""")
    assert len(set(got["keys"])) == 3
    assert got["text"] == "thing" and got["second"] is True and got["shown"] is True


# ---------------------------------------------------------------- D12 and D13: the copy boxes
SPEC = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#diffmap/f1/spec.md";
route();
return settled().then(async () => {
  const sel = window.getSelection();
  const place = document.getElementById("place");
  const COMMAND = "diffmap open f1/spec.md";
  const spec = (over) => Object.assign({ folder: "f1", file: "spec.md", title: "T", stem: "spec", agent: "Alder", project_name: "P", slug: "p",
    updated: "2026-10-01T10:00:00Z", command: COMMAND }, over || {});
  S.data.diffmap = { specs: [spec(), spec({ file: "other.md" })], note: null };
  fill();
  const copy = () => place.all((e) => e.tagName === "BUTTON" && e.getAttribute("data-k") === "copy:f1:spec.md")[0];
  const box = () => place.all((e) => e.tagName === "TEXTAREA" && e.className === "copy-box")[0];
  const refuse = () => { navigator.clipboard.writeText = () => Promise.reject(new Error("refused")); };
  const settleAll = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
  //BODY
});
"""


def spec(body: str):
    return run(SPEC.replace("//BODY", body))


@needs_node
def test_diffmaps_copy_box_stays_through_the_pages_draws_with_its_focus_and_selection():
    got = spec("""
  refuse();
  copy().click();                                        // the page's own button
  await settleAll();
  const first = box();
  const shown = [!!first, document.activeElement === first, first.selectionStart, first.selectionEnd, D.box && D.box.id];
  fill();                                                // the ten-second draw
  S.rev++;
  fill();                                                // and one after a read that found a change
  const after = box();
  report({ shown, there: !!after, value: after && after.value, active: document.activeElement === after,
    range: after && [after.selectionStart, after.selectionEnd], boxes: place.all((e) => e.className === "copy-box").length, id: D.box && D.box.id });""")
    assert got["shown"] == [True, True, 0, 23, "diffmap:f1/spec.md"]
    assert got["there"] is True and got["value"] == "diffmap open f1/spec.md"
    assert got["active"] is True and got["range"] == [0, 23]
    assert got["boxes"] == 1 and got["id"] == "diffmap:f1/spec.md"


@needs_node
def test_diffmaps_copy_box_goes_when_you_hide_it_copy_it_leave_or_the_command_changes():       # must-refuse: not kept forever
    got = spec("""
  refuse();
  copy().click(); await settleAll();
  place.all((e) => e.getAttribute("data-k") === "copybox-hide")[0].click();
  const hidden = [!box(), D.box];
  copy().click(); await settleAll();
  navigator.clipboard.writeText = () => Promise.resolve();
  copy().click(); await settleAll();
  const copied = [!box(), D.box, copy().textContent];
  refuse();
  copy().click(); await settleAll();
  S.data.diffmap = { specs: [spec({ command: "diffmap open f1/spec.md --other" }), spec({ file: "other.md" })], note: null };
  S.rev++; fill();
  const stale = [!box(), D.box];
  refuse();
  copy().click(); await settleAll();
  location.hash = "#diffmap";                            // the list of specs
  route();
  const toList = [D.box, !box()];
  location.hash = "#diffmap/f1/spec.md";
  route();
  S.data.diffmap = { specs: [spec(), spec({ file: "other.md" })], note: null };
  fill();
  const back = [!box(), D.box];
  refuse();
  copy().click(); await settleAll();
  location.hash = "#waiting";
  route();
  report({ hidden, copied, stale, toList, back, leftForWaiting: D.box });""")
    assert got["hidden"] == [True, None]
    assert got["copied"] == [True, None, "Copied"]
    assert got["stale"] == [True, None]
    assert got["toList"] == [None, True]
    assert got["back"] == [True, None]                      # coming back does not bring the box back
    assert got["leftForWaiting"] is None                    # and D.box does not hold the command after you left


@needs_node
def test_a_box_for_another_spec_or_a_document_is_not_shown_on_this_spec():                    # must-refuse
    got = spec("""
  D.box = { id: "diffmap:f1/other.md", text: COMMAND };
  fill();
  const other = [!box(), D.box];
  D.box = { id: "d1", text: COMMAND };                   // a document's box
  fill();
  report({ other, doc: [!box(), D.box] });""")
    assert got["other"] == [True, None] and got["doc"] == [True, None]


DOCS = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#documents/d1";
route();
return settled().then(async () => {
  const place = document.getElementById("place");
  const doc = { id: "d1", agent: "Alder", project_name: "P", slug: "p", title: "Doc", master: "MASTER.md",
    updated: "2026-10-01T10:00:00Z", docs: [], diagrams: [] };
  S.data.documents = { documents: [doc] };
  D.text.set("d1/MASTER.md@2026-10-01T10:00:00Z", { text: "hello world ".repeat(500) });
  fill();
  const copy = () => place.all((e) => e.tagName === "BUTTON" && e.getAttribute("data-k") === "copy:d1")[0];
  const box = () => place.all((e) => e.tagName === "TEXTAREA" && e.className === "copy-box")[0];
  navigator.clipboard.writeText = () => Promise.reject(new Error("refused"));
  await copyText(copy(), "hello world ".repeat(500), copy().parentNode, "d1");
  //BODY
});
"""


def docs(body: str):
    return run(DOCS.replace("//BODY", body))


@needs_node
def test_the_copy_boxes_own_scroll_is_kept_through_a_settle_draw_and_a_draw_of_new_nodes():
    got = docs("""
  const first = box();
  first.scrollTop = 1500; first.scrollLeft = 7;
  fill();                                                // a draw that changed nothing: the very node is put back
  const quiet = [box() === first, box().scrollTop, box().scrollLeft];
  S.rev++;
  fill();                                                // after a read that found a change: a new node
  const changed = [box() !== first, box().scrollTop, box().scrollLeft];
  report({ quiet, changed, value: box().value.length });""")
    assert got["quiet"] == [True, 1500, 7]
    assert got["changed"] == [True, 1500, 7]
    assert got["value"] == 6000


@needs_node
def test_a_box_that_was_not_scrolled_is_left_at_the_top_and_a_hidden_box_does_not_come_back():     # must-refuse
    got = docs("""
  fill();
  S.rev++;
  fill();
  const top = box().scrollTop;
  box().scrollTop = 900;
  place.all((e) => e.getAttribute("data-k") === "copybox-hide")[0].click();
  const hidden = !box();
  fill();
  S.rev++;
  fill();
  const text = document.createElement("textarea");       // a text box with no key is not the page's to hold
  place.append(text);
  text.scrollTop = 40;
  fill();
  report({ top, hidden, after: !box(), unkeyed: text.scrollTop });""")
    assert got["top"] == 0
    assert got["hidden"] is True and got["after"] is True
