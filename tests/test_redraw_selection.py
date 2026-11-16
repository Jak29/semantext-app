"""A re-draw keeps what you have selected (unreleased): the page draws again every ten seconds, on a window focus, and when a
band or a drawer reads again, and a draw used to drop the selection (in a field it collapsed to the caret; in a card's
words it was gone).

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules. The stand-in keeps a selection and
a focus as the browser does (a node taken out moves the selection's ends and drops the focus), so a draw that does not
keep the selection loses it here, as it does there: test_the_stand_in_loses_a_selection_a_bare_draw_replaces proves it.
Each must-pass has its must-refuse beside it: words you released are not brought back, words that changed are not
followed, and a field you are not in gets no selection.
"""
from __future__ import annotations

import pytest

from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# The Waiting place, with one card that has a words box (a card in this machine's own inbox), drawn the way a read lands:
# the data set, then fill(), which is what load() ends in when the ten-second read finds a change.
WAITING = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  const KEY = "Alder/A-1";
  const card = (over) => Object.assign({ key: KEY, seat: "Alder", id: "A-1", kind: "decision", title: "Pick one",
    why: "because the first is safer", question: "Which?", options: ["first", "second"], state: "waiting", asks: "Alder",
    acts: "Alder", at: "2026-10-01T10:00:00Z", notes: [], own_inbox: true }, over || {});
  const draw = (c) => { S.rev++; S.data.waiting = { cards: [c], seats: ["Alder"] }; fill(); };   // S.rev++: a read that found a change (accept)
  const place = document.getElementById("place");
  const find = (pred) => place.all(pred)[0];
  const why = () => find((e) => e.className === "why");
  const words = () => find((e) => e.tagName === "INPUT" && e.getAttribute("data-k") === "words:" + KEY);
  const sel = window.getSelection();
  //BODY
});
"""


def waiting(body: str):
    return run(WAITING.replace("//BODY", body))


# ---------------------------------------------------------------- a field keeps its start, end and direction
@needs_node
def test_a_words_box_keeps_its_selection_through_a_redraw():
    got = waiting("""
  answers.words[KEY] = "hello brave world";
  draw(card());
  const before = words();
  before.focus();
  before.setSelectionRange(6, 11, "backward");
  draw(card());
  const after = words();
  report({ replaced: after !== before, attached: place.contains(after), active: document.activeElement === after,
    range: [after.selectionStart, after.selectionEnd, after.selectionDirection], value: after.value });""")
    assert got["replaced"] is True and got["attached"] is True       # the box really was drawn again
    assert got["active"] is True                                       # focus stayed
    assert got["range"] == [6, 11, "backward"]                         # start, end and direction, not only the caret
    assert got["value"] == "hello brave world"


@needs_node
def test_a_field_you_are_not_in_gets_no_selection_and_a_short_value_clamps_it():       # must-refuse + clamp
    got = waiting("""
  answers.words[KEY] = "hello brave world";
  draw(card());
  const before = words();
  before.setSelectionRange(2, 4, "forward");                          // a selection in it, but focus is elsewhere
  find((e) => e.tagName === "BUTTON" && e.getAttribute("data-k") === "send:" + KEY).focus();
  draw(card());
  const idle = words();
  const idleRange = [idle.selectionStart, idle.selectionEnd];
  idle.focus();
  idle.setSelectionRange(6, 11, "forward");
  answers.words[KEY] = "hi";                                          // the value is shorter after the draw
  draw(card());
  const short = words();
  report({ idle: idleRange, length: idle.value.length, short: [short.selectionStart, short.selectionEnd] });""")
    assert got["idle"] == [got["length"], got["length"]]              # the caret a new value gets, not the old 2..4
    assert got["short"] == [2, 2]                                       # clamped to what the field now holds


# ---------------------------------------------------------------- words on the page
@needs_node
@pytest.mark.parametrize("anchor,focus,left,right", [(0, 7, 0, 7), (7, 0, 7, 0)], ids=["forward", "backward"])
def test_words_selected_in_a_card_survive_a_redraw_with_their_direction(anchor, focus, left, right):
    got = waiting("""
  draw(card());
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, %d, old, %d);
  const said = String(sel);
  draw(card());
  const now = why().childNodes[0];
  report({ said, text: String(sel), collapsed: sel.isCollapsed, replaced: now !== old, gone: !document.contains(old),
    inNew: sel.anchorNode === now && sel.focusNode === now, offsets: [sel.anchorOffset, sel.focusOffset] });""" % (anchor, focus))
    assert got["said"] == "because"
    assert got["replaced"] is True and got["gone"] is True            # the selected text really was drawn again
    assert got["text"] == "because" and got["collapsed"] is False
    assert got["inNew"] is True                                         # on the new words, not the dropped ones
    assert got["offsets"] == [left, right]


@needs_node
def test_words_are_found_again_when_the_text_before_them_changed():
    got = waiting("""
  draw(card());
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 7);
  draw(card({ why: "!! because the first is safer" }));          // a longer line before: the same offsets are other words
  report({ text: String(sel), collapsed: sel.isCollapsed, inNew: sel.anchorNode === why().childNodes[0] });""")
    assert got["text"] == "because" and got["collapsed"] is False and got["inNew"] is True


@needs_node
def test_words_that_changed_are_not_followed_and_nothing_stands_in_their_place():       # must-refuse
    got = waiting("""
  draw(card());
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 7);
  draw(card({ why: "nothing alike here at all" }));
  report({ text: String(sel), collapsed: sel.isCollapsed });""")
    assert got["text"] == "" and got["collapsed"] is True            # no selection, not one on other words


@needs_node
def test_words_that_now_stand_twice_are_not_guessed_at():                                   # must-refuse
    got = waiting("""
  draw(card({ why: "first the safer" }));
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, 6, old, 9);                              // "the"
  draw(card({ why: "xx the one the" }));                             // the same offsets are "one"; "the" is there twice
  report({ text: String(sel), collapsed: sel.isCollapsed });""")
    assert got["text"] == "" and got["collapsed"] is True


@needs_node
def test_a_selection_you_released_is_not_brought_back():                                  # must-refuse
    got = waiting("""
  draw(card());
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 7);
  draw(card());
  const kept = String(sel);
  sel.removeAllRanges();                                              // released: a click elsewhere, Escape
  draw(card());
  draw(card({ why: "because the first is safer" }));
  const released = [String(sel), sel.rangeCount];
  const now = why().childNodes[0];
  sel.setBaseAndExtent(now, 3, now, 3);                               // a caret only, no words selected
  draw(card());
  report({ kept, released, caret: [String(sel), sel.isCollapsed] });""")
    assert got["kept"] == "because"                                     # it was kept while held
    assert got["released"] == ["", 0]                                   # and not remembered once released
    assert got["caret"] == ["", True]                                   # a caret is not made into a selection


@needs_node
def test_a_selection_across_two_cards_is_kept():
    got = waiting("""
  S.data.waiting = { cards: [card(), card({ key: "Alder/A-2", id: "A-2", title: "Other", why: "so that it holds" })], seats: ["Alder"] };
  fill();
  const whys = () => place.all((e) => e.className === "why");
  const from = whys()[0].childNodes[0], to = whys()[1].childNodes[0];
  sel.setBaseAndExtent(from, 8, to, 2);
  const said = String(sel);
  fill();
  report({ said, text: String(sel), inNew: sel.anchorNode === whys()[0].childNodes[0] && sel.focusNode === whys()[1].childNodes[0] });""")
    assert got["text"] == got["said"] and "so" in got["text"]
    assert got["inNew"] is True


@needs_node
def test_the_stand_in_loses_a_selection_a_bare_draw_replaces():           # the control that lets the must-passes fail
    got = waiting("""
  draw(card());
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 7);
  const field = (() => { answers.words[KEY] = "hello"; draw(card()); const w = words(); w.focus(); w.setSelectionRange(1, 3, "forward"); return w; })();
  const plain = why().childNodes[0];
  sel.setBaseAndExtent(plain, 0, plain, 7);
  why().parentNode.replaceChildren();                                  // a draw that does not go through keep()
  report({ text: String(sel), collapsed: sel.isCollapsed, active: document.activeElement === null || document.activeElement !== field });""")
    assert got["text"] == "" and got["collapsed"] is True
    assert got["active"] is True


# ---------------------------------------------------------------- the other re-draws: the bands, a drawer, Today
BAND = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(async () => {
  const place = document.getElementById("place");
  const sel = window.getSelection();
  const band = (name) => place.all((e) => e.tagName === "BUTTON" && e.className.includes("band-" + name))[0];
  //BODY
});
"""


@needs_node
def test_the_waiting_band_keeps_a_selection_through_its_ten_second_redraw():
    got = run(BAND.replace("//BODY", """
  S.data.waiting = { cards: [{ key: "Alder/A-1", seat: "Alder", id: "A-1", kind: "decision", title: "Pick one",
    why: "because the first is safer", question: "Which?", options: ["first", "second"], state: "waiting", asks: "Alder",
    acts: "Alder", at: "2026-10-01T10:00:00Z", notes: [] }], seats: ["Alder"] };
  band("waiting").click();
  const why = () => place.all((e) => e.className === "why")[0];
  const old = why().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 7);
  redrawPanel();                                                       // where the band's read ends, every ten seconds
  report({ text: String(sel), gone: !document.contains(old), inNew: sel.anchorNode === why().childNodes[0] });"""))
    assert got["gone"] is True and got["text"] == "because" and got["inNew"] is True


@needs_node
def test_the_rules_band_keeps_a_selection_and_drops_it_when_you_released_it():
    rule = ('{ id: "r1", statement: "A question asks for an answer, not a change", enabled: true, applies_when: "when you ask", '
            'provenance: { type: "LEARNED", words: "when I ask, just answer" } }')
    got = run(BAND.replace("//BODY", """
  PRISM.rules.data = { env: "Me", own: [%s], agents: [], base: [], tests: [] };
  PRISM.rules.at = Date.now();
  band("rules").click();
  const st = () => place.all((e) => e.className === "rule-st")[0];
  const old = st().childNodes[0];
  sel.setBaseAndExtent(old, 2, old, 10);                               // "question"
  redrawPanel();
  const kept = [String(sel), !document.contains(old)];
  sel.removeAllRanges();
  redrawPanel();
  report({ kept, released: String(sel) });""" % rule))
    assert got["kept"] == ["question", True]
    assert got["released"] == ""                                        # must-refuse: released, so not brought back


@needs_node
def test_a_drawer_keeps_a_selection_through_a_read_that_lands_while_it_is_open():
    got = run(BAND.replace("//BODY", """
  S.data.map = { agents: { a1: { name: "Alder", works: [], waiting: [], documents: [], groups: [], emails: [], other_names: [],
    rules: null, cards: 0 } }, cards: {}, documents: [], names: {} };
  openDrawer("agent", { id: "a1" });
  const body = document.getElementById("drawer-body");
  const line = () => body.all((e) => e.className === "empty" && e.textContent.startsWith("Nothing from"))[0];
  const old = line().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 7);
  S.rev++;                                                             // the read found a change (accept)
  renderDrawer(false);                                                 // what load() does when the drawer's route changed
  report({ text: String(sel), gone: !document.contains(old), inNew: sel.anchorNode === line().childNodes[0] });"""))
    assert got["gone"] is True and got["text"] == "Nothing" and got["inNew"] is True


@needs_node
def test_the_feed_poll_redraws_history_and_keeps_a_selection():
    got = run(BAND.replace("//BODY", """
  const { hooks, host, S: own } = moved;
  const rows = document.getElementById("historyRows");
  host.el = document.createElement("div");
  own.view = "history";
  own.feed = { on: true, limit: 9500, records: [{ at: "2026-10-01T10:00:00Z", agent: "ai", words: "own", form: "full",
    environment: "home", layers: [], bytes: 100, answers: [], waiting: [] }] };
  hooks.fresh({ at: "2026-10-01T10:00:00Z" });                         // what pollFeed calls when something new arrived
  const cell = () => rows.all((e) => e.tagName === "TD" && e.textContent === "Your words")[0];
  const old = cell().childNodes[0];
  sel.setBaseAndExtent(old, 0, old, 4);
  hooks.fresh({ at: "2026-10-01T10:00:00Z" });
  report({ text: String(sel), gone: !document.contains(old), inNew: sel.anchorNode === cell().childNodes[0] });"""))
    assert got["gone"] is True and got["text"] == "Your" and got["inNew"] is True


# ---------------------------------------------------------------- a timer that wrote the same words again
@needs_node
def test_copy_id_selected_for_ctrl_c_is_not_dropped_by_its_own_timer():
    got = run(BAND.replace("//BODY", """
  const timers = [];
  globalThis.setTimeout = (fn) => { timers.push(fn); return 0; };
  navigator.clipboard.writeText = () => Promise.reject(new Error("refused"));   // the clipboard is refused
  const button = document.createElement("button");
  button.dataset.id = "A-1";
  button.textContent = "A-1";
  place.append(button);
  await copyId(button);
  const text = button.childNodes[0];
  const selected = [String(sel), sel.anchorNode === button && sel.focusNode === button];   // selectNodeContents(button)
  timers.forEach((fn) => fn());                                         // the 1.5 s timer, and the toast's
  report({ selected, after: String(sel), same: button.childNodes[0] === text, collapsed: sel.isCollapsed });"""))
    assert got["selected"] == ["A-1", True]
    assert got["after"] == "A-1" and got["same"] is True and got["collapsed"] is False


@needs_node
def test_copy_id_still_puts_the_id_back_after_copied():                   # must-refuse: the fix does not stop the reset
    got = run(BAND.replace("//BODY", """
  const timers = [];
  globalThis.setTimeout = (fn) => { timers.push(fn); return 0; };
  const button = document.createElement("button");
  button.dataset.id = "A-1";
  button.textContent = "A-1";
  place.append(button);
  await copyId(button);
  const said = button.textContent;
  timers.forEach((fn) => fn());
  report({ said, after: button.textContent });"""))
    assert got["said"] == "Copied" and got["after"] == "A-1"
