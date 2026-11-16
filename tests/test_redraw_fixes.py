"""The attack of the re-draw keeps the selection (D1 to D6): what a selection does when the page draws again.

D1  a triple-click (an end at offset 0 of the next block) was lost even by a draw that changed nothing: the stand-in now
    reads a selection as Chrome does (a line break where a block ends), a draw that reads the same replaces nothing, and
    a draw that changed the part puts each end back by its path.
D2  a selection is searched for only in the element that held it, and let go if the words are not there once.
D3  the banner, "Checked" and the bar are written only when they differ, and through keep() when they do.
D4  the copy box shown when the clipboard is refused stays through the page's draws until you copy it or hide it.
D5  two elements that share a data-k (a card in the place and in a drawer): the selection and the focus go back to
    the copy they were in.
D6  the New item, Edit and Priority fields carry a key, so a draw gives the focus and the caret back.

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules. Each must-pass has its must-refuse
beside it. A read that finds a change is S.rev++ (accept() does it), and the tests that draw "again" say which they mean.
"""
from __future__ import annotations

import pytest

from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

WAITING = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  const card = (over) => Object.assign({ key: "Alder/A-1", seat: "Alder", id: "A-1", kind: "decision", title: "Pick one",
    why: "because the first is safer", question: "Which?", options: ["first", "second"], state: "waiting", asks: "Alder",
    acts: "Alder", at: "2026-10-01T10:00:00Z", notes: [], own_inbox: true }, over || {});
  const three = (w3) => [card(), card({ key: "Alder/A-2", id: "A-2", title: "Other", why: "so that it holds", question: "Is it so?" }),
    card({ key: "Alder/A-3", id: "A-3", title: "Third", why: w3 })];
  // bump: a read that found a change (accept() moves S.rev); without it, a draw from the same data
  const draw3 = (w3, bump) => { if (bump !== false) S.rev++; S.data.waiting = { cards: three(w3), seats: ["Alder"] }; fill(); };
  const PICKS = [{ choice: "1", label: "first" }, { choice: "2", label: "second" }];
  const place = document.getElementById("place");
  const sel = window.getSelection();
  const blocks = () => place.all((e) => e.tagName === "P" && (e.className === "why" || e.className === "question")).slice(0, 4);
  const why = (n) => place.all((e) => e.className === "why")[n || 0];
  //BODY
});
"""


def waiting(body: str):
    return run(WAITING.replace("//BODY", body))


# ---------------------------------------------------------------- D1: the stand-in reads a selection as Chrome does
@needs_node
def test_the_stand_in_reads_a_line_break_where_a_block_ends():
    got = waiting("""
  draw3("x");
  const w = why(0).childNodes[0], q = blocks()[1];
  sel.setBaseAndExtent(w, 0, q, 0);                      // a triple-click: the end is at the start of the next block
  const triple = String(sel);
  sel.setBaseAndExtent(w, 3, w, 7);
  const inside = String(sel);
  sel.setBaseAndExtent(w, w.data.length, q, 0);          // from the end of one block to the start of the next
  const between = String(sel);
  sel.setBaseAndExtent(why(0), 0, why(0), 1);            // the block's own contents, no further
  report({ triple, inside, between, whole: String(sel), words: w.data });""")
    assert got["triple"] == got["words"] + "\n\n"        # a paragraph ends in a pair of breaks
    assert got["inside"] == got["words"][3:7]           # words inside one block carry none
    assert got["between"] == "\n\n"
    assert got["whole"] == got["words"]                  # an end inside the block takes none of its break


# ---------------------------------------------------------------- D1 (a): a draw that changes nothing replaces nothing
@needs_node
def test_a_triple_click_survives_a_redraw_that_changes_nothing_and_the_nodes_stay():
    got = waiting("""
  draw3("x");
  const w = why(0).childNodes[0], q = blocks()[1];
  const wasPlace = place.childNodes.slice();
  sel.setBaseAndExtent(w, 0, q, 0);
  const saved = String(sel);
  draw3("x", false);                                     // the ten-second read found nothing new
  report({ saved, now: String(sel), collapsed: sel.isCollapsed, same: why(0).childNodes[0] === w && sel.anchorNode === w && sel.focusNode === q,
    attached: document.contains(w), place: place.childNodes.length === wasPlace.length });""")
    assert got["saved"].endswith("\n\n") and got["collapsed"] is False
    assert got["now"] == got["saved"]
    assert got["same"] is True and got["attached"] is True       # the very nodes, not a copy of their words


@needs_node
def test_a_redraw_after_a_change_in_the_data_draws_new_nodes_and_still_keeps_a_triple_click():       # must-refuse: no reuse
    got = waiting("""
  draw3("x");
  const w = why(0).childNodes[0], q = blocks()[1];
  sel.setBaseAndExtent(w, 0, q, 0);
  const saved = String(sel);
  draw3("x");                                            // S.rev moved: the same words, but the data changed
  report({ saved, now: String(sel), collapsed: sel.isCollapsed, replaced: why(0).childNodes[0] !== w && !document.contains(w),
    inNew: sel.anchorNode === why(0).childNodes[0] && sel.focusNode === blocks()[1] });""")
    assert got["replaced"] is True                         # a handler on a node holds the data it was drawn from
    assert got["now"] == got["saved"] and got["collapsed"] is False
    assert got["inNew"] is True


@needs_node
def test_a_part_that_changed_is_drawn_new_and_the_parts_beside_it_that_did_not_stay():
    got = waiting("""
  draw3("x");
  const w = why(0).childNodes[0], t3 = why(2).childNodes[0];
  sel.setBaseAndExtent(w, 3, w, 9);
  const saved = String(sel);
  draw3("y", false);                                     // card 3's words changed; the data did not move
  report({ saved, now: String(sel), card1: why(0).childNodes[0] === w, card3: why(2).childNodes[0] !== t3, third: why(2).textContent });""")
    assert got["card1"] is True and got["card3"] is True and got["third"] == "y"
    assert got["now"] == got["saved"] == "ause t"


# ---------------------------------------------------------------- D1 (b): each end by its path
FUZZ = """
  const kinds = ["t0", "tm", "tl", "e0", "el"];
  const pt = (i, kind) => {
    const b = blocks()[i], t = b.childNodes[0];
    return kind === "t0" ? [t, 0] : kind === "tm" ? [t, Math.floor(t.data.length / 2)] : kind === "tl" ? [t, t.data.length]
      : kind === "e0" ? [b, 0] : [b, b.childNodes.length];
  };
  let n = 0, trials = 0, replaced = 0;
  const bad = [];
  for (let i = 0; i < 4; i++) for (const ki of kinds) for (let j = 0; j < 4; j++) for (const kj of kinds) {
    draw3("x" + n++);
    const [a, ao] = pt(i, ki), [f, fo] = pt(j, kj);
    sel.setBaseAndExtent(a, ao, f, fo);
    const saved = String(sel);
    if (!saved || sel.isCollapsed) continue;
    trials++;
    draw3("x" + n++);                                    // another card changed: the data moved, every node is new
    if (!document.contains(a)) replaced++;
    if (sel.isCollapsed || String(sel) !== saved) bad.push([i, ki, j, kj, saved, String(sel)]);
  }
  report({ trials, replaced, bad: bad.slice(0, 5), nbad: bad.length });"""


@needs_node
def test_an_end_at_offset_zero_or_a_text_edge_is_put_back_across_blocks_after_a_changed_draw():
    got = waiting(FUZZ)
    assert got["trials"] > 150                             # most of the end positions make a selection
    assert got["replaced"] == got["trials"]                # in every one the draw really replaced the nodes
    assert got["nbad"] == 0, got["bad"]


# ---------------------------------------------------------------- D2: the search is inside the element that held the words
@needs_node
def test_words_are_not_followed_onto_an_option_button_when_the_why_changed():                  # must-refuse
    got = waiting("""
  S.rev++;
  S.data.waiting = { cards: [card({ why: "because the first is safer", choices: PICKS })], seats: ["Alder"] };
  fill();
  const w = why(0).childNodes[0];
  sel.setBaseAndExtent(w, 12, w, 17);                    // "first"
  const said = String(sel);
  S.rev++;
  S.data.waiting = { cards: [card({ why: "nothing alike here", choices: PICKS })], seats: ["Alder"] };
  fill();
  const buttons = place.all((e) => e.tagName === "BUTTON" && e.textContent === "first").length;
  report({ said, text: String(sel), collapsed: sel.isCollapsed, buttons });""")
    assert got["said"] == "first" and got["buttons"] == 1   # "first" stands once in the card, on an option button
    assert got["text"] == "" and got["collapsed"] is True    # and the selection is not moved onto it


@needs_node
def test_words_are_not_followed_into_another_heading():                                   # must-refuse
    got = waiting("""
  S.rev++;
  S.data.waiting = { cards: [card({ why: "SEE OUR RULES", title: "YOUR RULES" })], seats: ["Alder"] };
  fill();
  const w = why(0).childNodes[0];
  sel.setBaseAndExtent(w, 4, w, 8);                      // "OUR "
  const said = String(sel);
  S.rev++;
  S.data.waiting = { cards: [card({ why: "nothing alike here", title: "YOUR RULES" })], seats: ["Alder"] };
  fill();
  report({ said, text: String(sel), collapsed: sel.isCollapsed });""")
    assert got["said"] == "OUR " and got["text"] == "" and got["collapsed"] is True


@needs_node
def test_words_that_moved_inside_their_own_element_are_still_found():                       # must-pass beside the two above
    got = waiting("""
  S.rev++;
  S.data.waiting = { cards: [card({ why: "because the first is safer", title: "the first" })], seats: ["Alder"] };
  fill();
  const w = why(0).childNodes[0];
  sel.setBaseAndExtent(w, 12, w, 17);
  S.rev++;
  S.data.waiting = { cards: [card({ why: "!! because the first is safer", title: "the first" })], seats: ["Alder"] };
  fill();
  report({ text: String(sel), inWhy: sel.anchorNode === why(0).childNodes[0] && sel.focusNode === why(0).childNodes[0] });""")
    assert got["text"] == "first" and got["inWhy"] is True       # not the title, which holds "first" as well


# ---------------------------------------------------------------- D3: the banner, "Checked" and the bar
PROBLEMS = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  S.problemsOpen = true;
  const sel = window.getSelection();
  const prob = (text) => ({ reader: "rules", source: "a.md", line: 3, text });
  const frame = (problems, over) => Object.assign({ name: null, word: null, waiting: 1, problems, outside: [] }, over || {});
  const box = document.getElementById("problems");
  const first = () => box.all((e) => e.tagName === "SPAN")[0].childNodes[0];
  //BODY
});
"""


def problems(body: str):
    return run(PROBLEMS.replace("//BODY", body))


@needs_node
def test_a_selection_in_the_banner_survives_a_refresh_that_changed_nothing():
    got = problems("""
  applyFrame(frame([prob("bad thing")]));
  const t = first();
  sel.setBaseAndExtent(t, 0, t, 3);
  const said = String(sel);
  applyFrame(frame([prob("bad thing")]));                // what every ten-second read does
  applyFrame(frame([prob("bad thing")]));
  report({ said, text: String(sel), same: first() === t && sel.anchorNode === t, shown: box.textContent });""")
    assert got["said"] == "Bad" and got["text"] == "Bad"
    assert got["same"] is True and "Bad thing" in got["shown"]


@needs_node
def test_a_selection_in_the_banner_survives_a_refresh_that_changed_another_problem_and_not_the_one_changed():
    got = problems("""
  applyFrame(frame([prob("bad thing"), prob("worse thing")]));
  const title = box.all((e) => e.className === "problems-title")[0].childNodes[0];
  sel.setBaseAndExtent(title, 0, title, 9);
  const said = String(sel);
  applyFrame(frame([prob("bad thing"), prob("a different thing")]));
  const kept = [String(sel), box.textContent.includes("A different thing")];
  const items = box.all((e) => e.tagName === "LI");
  const second = items[1].all((e) => e.tagName === "SPAN")[0].childNodes[0];
  sel.setBaseAndExtent(second, 0, second, 4);            // words in the problem that is about to change
  applyFrame(frame([prob("bad thing"), prob("another thing")]));
  report({ said, kept, gone: String(sel), collapsed: sel.isCollapsed });""")
    assert got["said"] == "Something" and got["kept"] == ["Something", True]
    assert got["gone"] == "" and got["collapsed"] is True    # must-refuse: words that changed are not followed


@needs_node
def test_checked_is_written_only_when_it_differs():
    got = problems("""
  const checked = document.getElementById("checked");
  setText(checked, "Checked 10:00");
  const t = checked.childNodes[0];
  sel.setBaseAndExtent(t, 8, t, 13);                     // "10:00"
  setText(checked, "Checked 10:00");                      // the next ten-second read, in the same minute
  const same = [String(sel), checked.childNodes[0] === t];
  setText(checked, "Checked 10:01");                      // a minute later: the words change
  report({ same, text: checked.textContent, now: String(sel), collapsed: sel.isCollapsed });""")
    assert got["same"] == ["10:00", True]
    assert got["text"] == "Checked 10:01"                   # a change is still written
    assert got["now"] == "" and got["collapsed"] is True    # and a selection in the words that changed is not moved


@needs_node
def test_the_bar_and_the_gaming_word_are_not_rewritten_by_a_refresh_that_changed_nothing():
    got = problems("""
  const f = frame([], { name: "Alder", waiting: 3, gaming: { state: "unknown", why: "no flag" } });
  applyFrame(f);
  const tab = document.getElementById("tab-map"), count = document.getElementById("count-waiting"), game = document.getElementById("gaming");
  const nodes = [tab.childNodes[0], count.childNodes[0], game.childNodes[0]];
  sel.setBaseAndExtent(nodes[2], 0, nodes[2], 6);
  applyFrame(f);
  renderGaming();
  const kept = [tab.childNodes[0] === nodes[0], count.childNodes[0] === nodes[1], game.childNodes[0] === nodes[2], String(sel)];
  applyFrame(frame([], { name: "Alder", waiting: 4, gaming: { state: "unknown", why: "no flag" } }));
  report({ kept, count: count.textContent, game: String(sel) });""")
    assert got["kept"] == [True, True, True, "Gaming"]
    assert got["count"] == "4"                              # a count that moved is written
    assert got["game"] == "Gaming"                          # and the selection beside it is held through it


# ---------------------------------------------------------------- D4: the copy box
DOCS = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#documents/d1";
route();
return settled().then(async () => {
  const sel = window.getSelection();
  const place = document.getElementById("place");
  const doc = { id: "d1", agent: "Alder", project_name: "P", slug: "p", title: "Doc", master: "MASTER.md",
    updated: "2026-10-01T10:00:00Z", docs: [], diagrams: [] };
  S.data.documents = { documents: [doc] };
  D.text.set("d1/MASTER.md@2026-10-01T10:00:00Z", { text: "hello world" });
  fill();
  const copy = () => place.all((e) => e.tagName === "BUTTON" && e.getAttribute("data-k") === "copy:d1")[0];
  const box = () => place.all((e) => e.tagName === "TEXTAREA" && e.className === "copy-box")[0];
  const refuse = () => { navigator.clipboard.writeText = () => Promise.reject(new Error("refused")); };
  //BODY
});
"""


def docs(body: str):
    return run(DOCS.replace("//BODY", body))


@needs_node
def test_the_copy_box_stays_through_the_pages_draws_with_its_focus_and_selection():
    got = docs("""
  refuse();
  await copyText(copy(), "hello world", copy().parentNode, "d1");
  const first = box();
  const shown = [document.activeElement === first, first.selectionStart, first.selectionEnd, first.value];
  fill();                                                // the ten-second draw
  S.rev++;
  fill();                                                // and one after a read that found a change
  const after = box();
  report({ shown, there: !!after, value: after && after.value, active: document.activeElement === after,
    range: after && [after.selectionStart, after.selectionEnd], boxes: place.all((e) => e.className === "copy-box").length });""")
    assert got["shown"] == [True, 0, 11, "hello world"]
    assert got["there"] is True and got["value"] == "hello world"
    assert got["active"] is True and got["range"] == [0, 11]
    assert got["boxes"] == 1


@needs_node
def test_the_copy_box_goes_when_you_hide_it_copy_it_or_leave():                                # must-refuse: not kept forever
    got = docs("""
  refuse();
  await copyText(copy(), "hello world", copy().parentNode, "d1");
  place.all((e) => e.getAttribute("data-k") === "copybox-hide")[0].click();
  const hidden = [!box(), D.box];
  await copyText(copy(), "hello world", copy().parentNode, "d1");
  navigator.clipboard.writeText = () => Promise.resolve();   // the clipboard works now
  await copyText(copy(), "hello world", copy().parentNode, "d1");
  const copied = [!box(), D.box, copy().textContent];
  fill();
  const copiedAfter = !box();
  refuse();
  await copyText(copy(), "hello world", copy().parentNode, "d1");
  location.hash = "#documents";                          // the list of documents
  route();
  S.data.documents = { documents: [doc] };
  fill();
  const left = [D.box, !box()];
  report({ hidden, copied, copiedAfter, left });""")
    assert got["hidden"] == [True, None]
    assert got["copied"] == [True, None, "Copied"] and got["copiedAfter"] is True
    assert got["left"] == [None, True]


@needs_node
def test_the_copy_box_is_not_kept_for_words_that_have_since_changed():                        # must-refuse
    got = docs("""
  refuse();
  await copyText(copy(), "hello world", copy().parentNode, "d1");
  D.text.set("d1/MASTER.md@2026-10-02T10:00:00Z", { text: "new words" });
  doc.updated = "2026-10-02T10:00:00Z";
  S.rev++;
  fill();
  report({ box: !!box(), state: D.box });""")
    assert got["box"] is False and got["state"] is None


# ---------------------------------------------------------------- D5: two elements that share a key
DUPES = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  const sel = window.getSelection();
  const place = document.getElementById("place");
  const side = document.getElementById("drawer-body");
  const copyOf = (words) => h("div", { "data-k": "card:Alder/A-1" }, h("p", null, words), h("input", { type: "text", "data-k": "words:Alder/A-1", value: "typed" }));
  const draw = () => { place.replaceChildren(copyOf("same words here")); side.replaceChildren(copyOf("same words here")); };
  draw();
  //BODY
});
"""


def dupes(body: str):
    return run(DUPES.replace("//BODY", body))


@needs_node
def test_a_selection_in_the_second_copy_of_a_card_goes_back_to_the_second_copy():
    got = dupes("""
  const t = side.childNodes[0].childNodes[0].childNodes[0];
  sel.setBaseAndExtent(t, 0, t, 5);
  keep(draw);
  const now = side.childNodes[0].childNodes[0].childNodes[0];
  report({ text: String(sel), inSecond: sel.anchorNode === now && sel.focusNode === now, inFirst: place.contains(sel.anchorNode) });""")
    assert got["text"] == "same " and got["inSecond"] is True and got["inFirst"] is False


@needs_node
def test_a_selection_in_the_second_copy_is_let_go_when_that_copy_is_gone_and_not_moved_to_the_first():       # must-refuse
    got = dupes("""
  const t = side.childNodes[0].childNodes[0].childNodes[0];
  sel.setBaseAndExtent(t, 0, t, 5);
  keep(() => { place.replaceChildren(copyOf("same words here")); side.replaceChildren(); });   // the drawer closed
  report({ text: String(sel), collapsed: sel.isCollapsed, count: sel.rangeCount });""")
    assert got["text"] == "" and got["collapsed"] is True


@needs_node
def test_the_focus_in_the_second_copy_goes_back_to_the_second_copy():
    got = dupes("""
  const field = side.childNodes[0].childNodes[1];
  field.focus();
  field.setSelectionRange(1, 4, "forward");
  keep(draw);
  const now = side.childNodes[0].childNodes[1];
  report({ second: document.activeElement === now, first: document.activeElement === place.childNodes[0].childNodes[1],
    range: [now.selectionStart, now.selectionEnd] });""")
    assert got["second"] is True and got["first"] is False
    assert got["range"] == [1, 4]


# ---------------------------------------------------------------- D6: the work fields carry a key
WORK = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#work";
route();
return settled().then(async () => {
  const sel = window.getSelection();
  const place = document.getElementById("place");
  const holder = document.createElement("div");
  place.append(holder);
  const item = { id: "W-1", state: "next", title: "A title", kind: "task", text: "some body", version: 3, priority: null, voided: false };
  const fields = () => holder.all((e) => e.tagName === "INPUT" || e.tagName === "SELECT" || e.tagName === "TEXTAREA");
  //BODY
});
"""


def work(body: str):
    return run(WORK.replace("//BODY", body))


@needs_node
def test_every_work_field_carries_a_key():
    got = work("""
  WA.adding = "demo";
  holder.append(newItemNode("demo"));
  const adding = fields().map((e) => e.getAttribute("data-k"));
  holder.replaceChildren();
  WA.adding = null;
  WA.editing = item.id;
  holder.append(...panelControls(item));
  const editing = fields().map((e) => e.getAttribute("data-k"));
  report({ adding, editing });""")
    assert got["adding"] == ["wnew-title:demo", "wnew-kind:demo"]
    assert got["editing"] == ["wedit-title:W-1", "wedit-kind:W-1", "wedit-text:W-1", "wprio:W-1"]
    assert len(set(got["adding"] + got["editing"])) == 6


@needs_node
@pytest.mark.parametrize("which,select", [(0, [2, 7]), (2, [1, 4]), (3, [0, 1])], ids=["title", "text", "priority"])
def test_a_work_field_keeps_its_focus_and_caret_through_a_draw(which, select):
    got = work("""
  WA.editing = item.id;
  const draw = () => holder.replaceChildren(...panelControls(item));
  draw();
  const f = fields()[%d];
  f.focus();
  f.value = "hello world";
  f.dispatch("input");
  f.setSelectionRange(%d, %d, "forward");
  keep(draw);
  const now = fields()[%d];
  report({ replaced: now !== f, active: document.activeElement === now, range: [now.selectionStart, now.selectionEnd] });""" % (which, select[0], select[1], which))
    assert got["replaced"] is True and got["active"] is True
    # the priority field is a number box: its value is whatever its draft holds, so only the focus is asked of it
    if which != 3:
        assert got["range"] == select


@needs_node
def test_a_work_field_you_are_not_in_is_not_given_the_focus():                                 # must-refuse
    got = work("""
  WA.editing = item.id;
  const draw = () => holder.replaceChildren(...panelControls(item));
  draw();
  const other = holder.all((e) => e.tagName === "BUTTON")[0];
  other.focus();
  keep(draw);
  report({ field: fields().some((f) => document.activeElement === f) });""")
    assert got["field"] is False
