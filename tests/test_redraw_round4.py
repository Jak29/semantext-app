"""The fourth attack of the re-draw (D14 to D20): what a draw that finishes LATER may take back, and what it may not.

D14  a selection crossing the edge of a plug-in's place was left on OTHER words by the late restore. A late restore puts back
     only a selection wholly inside what the module drew, and only when the words read exactly the same; else it lets go.
D15  a selection released while a module was loading (a click's caret, removeAllRanges) came back when the module drew.
D16  settle put the OLD nodes back after a plug-in module drew, so the module's later updates went to detached nodes.
D17  the late finish scrolled back to where the draw began, undoing a scroll the person made during the wait.
D18  keep() waits for the promise the draw returns (the stated limit: a module whose render is async, until outside.js
     returns render's own promise).
D19  a problem's key could collide with another's ("#2" suffix; a line of null and of 0).
D20  compute.py writes a reading into a reason above 90 % busy / under 10 % free; each 1 % step counted as a change.
Noise: M7 (a focus the person moved to during the wait is not taken back), the Diffmap box's label, and a plug-in place named
like an old address (live) or like a prototype property (constructor).

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules. Each must-pass has its must-refuse
beside it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

FRAME = """
const place = (name, over) => Object.assign({ name, title: name[0].toUpperCase() + name.slice(1), origin: "semantext-" + name, version: "0.3", module: true }, over || {});
const frameOf = (...places) => ({ name: null, word: null, waiting: 0, problems: [], outside: places });
"""

TIX = """
export function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("p", { class: "tix-row" }, "Ticket one: the printer on floor two is broken"), h("p", { class: "tix-row" }, "Ticket two: " + data.n + " items listed"));
}
"""

# A module that keeps hold of what it drew, to update it later (a status that changes between reads).
STATUS = """
let current = null;
export function render(data, el, helpers) {
  current = el;
  el.replaceChildren(helpers.h("p", { class: "live-row" }, "Status: " + (data.status || "idle")));
  globalThis.__liveUpdate = (words) => { current.childNodes[0].replaceChildren("Status: " + words); };
}
"""

# The module draws the place's words and nothing else: for a place named like an old address or a built-in one.
PLAIN = """
export function render(data, el, helpers) { el.replaceChildren(helpers.h("p", null, "Drawn by the plug-in")); }
"""


def modules(tmp_path, **files) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / f"{name}.js").write_text(text, encoding="utf-8")
    return folder


# ---------------------------------------------------------------- D14: a selection across the edge of the place
CROSS = FRAME + """
return (async () => {
  applyFrame(frameOf(place("tix")));
  const sel = window.getSelection();
  const el = document.getElementById("place");
  S.data.tix = { place: "tix", frame: S.frame, n: 3 };
  location.hash = "#tix";
  route();
  await settled();
  // head and tail are keyed, as the banner and the drawer are: a restore could find their ends again
  const head = document.createElement("p"); head.setAttribute("data-k", "head"); head.append("Head words before the place"); document.body.insertBefore(head, el);
  const tail = document.createElement("p"); tail.setAttribute("data-k", "tail"); tail.append("Tail words after the place"); document.body.append(tail);
  const row = (i) => el.all((e) => e.className === "tix-row")[i].childNodes[0];
  const ht = () => head.childNodes[0], tt = () => tail.childNodes[0];
  const out = {};
  const tick = async () => { await settled(); for (let i = 0; i < 8; i++) await Promise.resolve(); };
  const runCase = async (name, set, real) => {
    set();
    const before = String(sel);
    if (real) S.rev++;
    fill();
    await tick();
    out[name] = { before, after: String(sel), collapsed: sel.isCollapsed };
    sel.removeAllRanges();
  };
  //BODY
  report(out);
})();
"""


def cross(tmp_path, body: str):
    return run(CROSS.replace("//BODY", body), plugins=modules(tmp_path, tix=TIX))


@needs_node
def test_a_selection_across_the_edge_of_a_plugins_place_is_let_go_never_left_on_other_words(tmp_path):
    got = cross(tmp_path, """
  for (const real of [false, true]) {
    const k = real ? "_real" : "_quiet";
    await runCase("headToRow" + k, () => sel.setBaseAndExtent(ht(), 5, row(0), 23), real);
    await runCase("rowToTail" + k, () => sel.setBaseAndExtent(row(0), 12, tt(), 4), real);
    await runCase("rowToHeadBackward" + k, () => sel.setBaseAndExtent(row(0), 23, ht(), 5), real);
    await runCase("tailToRowBackward" + k, () => sel.setBaseAndExtent(tt(), 4, row(0), 12), real);
  }""")
    for name, c in got.items():
        assert c["before"] != ""
        assert c["after"] == "" and c["collapsed"] is True, name   # let go: not truncated, not widened, not moved


@needs_node
def test_a_selection_wholly_inside_or_wholly_outside_a_plugins_place_is_still_kept(tmp_path):         # must-pass beside it
    got = cross(tmp_path, """
  for (const real of [false, true]) {
    const k = real ? "_real" : "_quiet";
    await runCase("inside" + k, () => sel.setBaseAndExtent(row(0), 12, row(0), 23), real);
    await runCase("across_rows" + k, () => sel.setBaseAndExtent(row(0), 0, row(1), 10), real);
    await runCase("outside" + k, () => sel.setBaseAndExtent(ht(), 5, ht(), 15), real);
    await runCase("outside_both" + k, () => sel.setBaseAndExtent(ht(), 5, tt(), 4), real);
  }""")
    for name, c in got.items():
        assert c["before"] != "" and c["after"] == c["before"], name


# ---------------------------------------------------------------- D15: a selection released while the module loaded
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
  sel.setBaseAndExtent(name, 0, name, 3);                // "Slo" held in the bar's tab when a draw starts
  fill();                                                // a draw that waits for the module
  const meta = document.getElementById("place").childNodes[0].childNodes[0];   // the place's meta line, drawn at once
  //BODY
})();
"""


def slow(body: str):
    return run(SLOW.replace("//BODY", body))


@needs_node
def test_a_selection_released_while_a_module_loaded_is_not_brought_back_when_it_lands():
    got = slow("""
  const out = {};
  sel.collapse(meta, 2);                                 // a click's caret
  release();
  await settled();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  out.caret = [String(sel), sel.isCollapsed];
  report(out);""")
    assert got["caret"] == ["", True]


@needs_node
def test_a_selection_emptied_while_a_module_loaded_is_not_brought_back_when_it_lands():
    got = slow("""
  sel.removeAllRanges();                                 // removeAllRanges: no range at all
  release();
  await settled();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  report({ text: String(sel), collapsed: sel.isCollapsed, drew: document.getElementById("place").textContent.includes("Slow words here") });""")
    assert got["text"] == "" and got["collapsed"] is True and got["drew"] is True


@needs_node
def test_a_selection_you_did_not_touch_while_a_module_loaded_is_still_there_when_it_lands():          # must-pass
    got = slow("""
  release();
  await settled();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  report({ text: String(sel), drew: document.getElementById("place").textContent.includes("Slow words here") });""")
    assert got["text"] == "Slo" and got["drew"] is True


@needs_node
def test_other_words_selected_while_a_module_loaded_are_kept():                                       # must-refuse the other way
    got = slow("""
  sel.setBaseAndExtent(name, 1, name, 4);
  release();
  await settled();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  report({ text: String(sel) });""")
    assert got["text"] == "low"


# A direct keep(): the draw returns a promise the test holds, in a region of its own.
KEEP = """
const region = document.getElementById("place");
const sel = window.getSelection();
const later = () => { let go; const p = new Promise((r) => { go = r; }); return { p, go }; };
const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
S.mounted = S.mounted || "x/";
return (async () => {
//BODY
})();
"""


@needs_node
def test_a_field_caret_you_moved_while_a_draw_waited_is_not_put_back():
    got = run(KEEP.replace("//BODY", """
  const input = document.createElement("input"); input.setAttribute("data-k", "f1"); input.value = "hello world";
  document.body.append(input);
  input.focus(); input.setSelectionRange(2, 5);
  const w = later();
  keep(() => { region.replaceChildren(document.createElement("p")); return w.p; }, region);
  input.setSelectionRange(8, 8);                          // the person clicks elsewhere in the field while it waits
  w.go(); await flush();
  const moved = [input.selectionStart, input.selectionEnd];
  input.setSelectionRange(2, 5);
  const w2 = later();
  keep(() => { input.setSelectionRange(0, 0); return w2.p; }, region);   // the draw itself moved the caret
  w2.go(); await flush();
  report({ moved, put: [input.selectionStart, input.selectionEnd] });"""))
    assert got["moved"] == [8, 8]                           # the person's caret
    assert got["put"] == [2, 5]                             # a caret the draw moved is put back


# ---------------------------------------------------------------- D16: a plug-in's later updates reach the page
STATUSPAGE = FRAME + """
return (async () => {
  applyFrame(frameOf(place("status")));
  S.data.status = { place: "status", frame: S.frame, status: "idle" };
  location.hash = "#status";
  route();
  await settled();
  const el = document.getElementById("place");
  const tick = async () => { await settled(); for (let i = 0; i < 8; i++) await Promise.resolve(); };
  const shown = () => el.all((e) => e.className === "live-row").map((e) => e.textContent);
  //BODY
})();
"""


@needs_node
def test_a_plugins_later_updates_show_after_a_draw_at_an_unchanged_read(tmp_path):
    got = run(STATUSPAGE.replace("//BODY", """
  const first = shown();
  const rev = S.rev;
  location.hash = "#status/"; route(); await tick();      // the same place key: a draw at an unchanged S.rev
  location.hash = "#status"; route(); await tick();
  fill(); await tick();
  __liveUpdate("2 jobs running");
  const one = shown();
  __liveUpdate("5 jobs running");
  report({ first, one, two: shown(), rev: S.rev - rev, rows: el.all((e) => e.className === "live-row").length });"""),
        plugins=modules(tmp_path, status=STATUS))
    assert got["first"] == ["Status: idle"]
    assert got["one"] == ["Status: 2 jobs running"] and got["two"] == ["Status: 5 jobs running"]
    assert got["rev"] == 0 and got["rows"] == 1


@needs_node
def test_a_plugins_draw_after_a_real_read_still_shows_its_latest_state(tmp_path):                     # must-pass beside it
    got = run(STATUSPAGE.replace("//BODY", """
  S.rev++; S.data.status = { place: "status", frame: S.frame, status: "busy" };
  fill(); await tick();
  __liveUpdate("6 jobs running");
  report({ shown: shown() });"""), plugins=modules(tmp_path, status=STATUS))
    assert got["shown"] == ["Status: 6 jobs running"]


# ---------------------------------------------------------------- D17: a scroll the person made during the wait
@needs_node
def test_a_scroll_the_person_made_while_a_draw_waited_is_not_undone():
    got = run(KEEP.replace("//BODY", """
  const calls = [];
  window.scrollTo = (x, y) => { calls.push(y); window.scrollY = y; };
  window.scrollY = 120;
  const w = later();
  keep(() => { region.replaceChildren(document.createElement("p")); return w.p; }, region);
  window.scrollY = 900;                                   // the person scrolls down while it waits
  w.go(); await flush();
  report({ calls, now: window.scrollY });"""))
    assert got["calls"] == [] and got["now"] == 900


@needs_node
def test_a_scroll_the_draw_itself_moved_is_still_put_back_when_it_finishes():                          # must-pass beside it
    got = run(KEEP.replace("//BODY", """
  const calls = [];
  window.scrollTo = (x, y) => { calls.push(y); window.scrollY = y; };
  window.scrollY = 120;
  const w = later();
  keep(() => { region.replaceChildren(document.createElement("p")); window.scrollY = 0; return w.p; }, region);   // the draw moves it
  const waiting = [calls.slice(), window.scrollY];        // put back at once: the page does not jump while it waits
  w.go(); await flush();                                  // nobody scrolled meanwhile: nothing more to do, and nothing undone
  report({ waiting, calls, now: window.scrollY });"""))
    assert got["waiting"] == [[120], 120]
    assert got["calls"] == [120] and got["now"] == 120


# ---------------------------------------------------------------- D18: keep() waits for the promise the draw returns
@needs_node
def test_keep_waits_for_a_draw_that_finishes_after_several_awaits_and_puts_the_selection_back():
    got = run(KEEP.replace("//BODY", """
  // as drawOutside draws: a frame at once (the old nodes go), and the words into it after several awaits
  const draw = (text) => { const f = document.createElement("div"); region.replaceChildren(f); return (async () => { for (let i = 0; i < 6; i++) await null; const p = document.createElement("p"); p.append(text); f.replaceChildren(p); })(); };
  const first = document.createElement("p"); first.append("Ticket one: the printer on floor two"); region.replaceChildren(first);
  let t = first.childNodes[0];
  sel.setBaseAndExtent(t, 12, t, 23);
  const said = String(sel);
  keep(() => draw("Ticket one: the printer on floor two"), region);
  await flush();
  const same = [String(sel), sel.anchorNode && region.contains(sel.anchorNode)];
  t = region.all((e) => e.tagName === "P")[0].childNodes[0];
  sel.setBaseAndExtent(t, 12, t, 23);
  keep(() => draw("Ticket one: the scanner on floor two"), region);   // other words
  await flush();
  report({ said, same, changed: [String(sel), sel.isCollapsed] });"""))
    assert got["said"] == "the printer"
    assert got["same"] == ["the printer", True]
    assert got["changed"] == ["", True]                     # never put on other words


@needs_node
def test_a_module_whose_render_is_async_loses_the_selection_but_never_gets_other_words(tmp_path):      # the stated limit
    got = run(FRAME + """
return (async () => {
  applyFrame(frameOf(place("slowtix")));
  S.data.slowtix = { place: "slowtix", frame: S.frame };
  location.hash = "#slowtix";
  route();
  await settled();
  for (let i = 0; i < 20; i++) await Promise.resolve();
  const el = document.getElementById("place"), sel = window.getSelection();
  const t = el.all((e) => e.className === "tix-row")[0].childNodes[0];
  sel.setBaseAndExtent(t, 12, t, 23);
  fill();
  await settled();
  for (let i = 0; i < 20; i++) await Promise.resolve();
  report({ text: String(sel), drew: el.all((e) => e.className === "tix-row").map((e) => e.textContent) });
})();""", plugins=modules(tmp_path, slowtix="""
export async function render(data, el, helpers) {
  for (let i = 0; i < 6; i++) await null;
  el.replaceChildren(helpers.h("p", { class: "tix-row" }, "Ticket one: the printer on floor two is broken"));
}
"""))
    assert got["text"] in ("", "the printer")                # kept once outside.js returns render's promise; else let go
    assert got["drew"] == ["Ticket one: the printer on floor two is broken"]


# ---------------------------------------------------------------- M7: a focus the person went to during the wait
@needs_node
def test_a_control_you_went_to_while_a_draw_waited_keeps_the_focus():
    got = run(KEEP.replace("//BODY", """
  const button = () => { const b = document.createElement("button"); b.setAttribute("data-k", "mod-btn"); b.append("Mod"); return b; };
  region.replaceChildren(button());
  region.childNodes[0].focus();
  const other = document.createElement("button"); other.setAttribute("data-k", "x-other"); other.append("Other"); document.body.append(other);
  const w = later();
  keep(() => { region.replaceChildren(button()); return w.p; }, region);   // the draw takes the focused button out
  const dropped = document.activeElement === document.body || document.activeElement === null;
  other.focus();                                          // the person goes to another control while it waits
  w.go(); await flush();
  report({ dropped, kept: document.activeElement === other, stolen: document.activeElement === region.childNodes[0] });"""))
    assert got["kept"] is True and got["stolen"] is False


@needs_node
def test_a_focus_the_draw_dropped_is_put_back_on_the_same_control_when_it_finishes():                  # must-pass beside it
    got = run(KEEP.replace("//BODY", """
  const button = () => { const b = document.createElement("button"); b.setAttribute("data-k", "mod-btn"); b.append("Mod"); return b; };
  region.replaceChildren(button());
  region.childNodes[0].focus();
  const w = later();
  keep(() => { region.replaceChildren(button()); return w.p; }, region);
  const dropped = document.activeElement !== region.childNodes[0];
  w.go(); await flush();
  report({ dropped, back: document.activeElement === region.childNodes[0] });"""))
    assert got["dropped"] is True and got["back"] is True


# ---------------------------------------------------------------- D19: no two problems share a key
PROBLEMS = """
applyFrame({ name: null, word: null, waiting: 1, problems: [], outside: [] });
location.hash = "#waiting";
route();
return settled().then(async () => {
  S.problemsOpen = true;
  const sel = window.getSelection();
  const prob = (text, line) => ({ reader: "rules", source: "a.md", line: line === undefined ? 3 : line, text });
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
def test_a_selection_never_moves_to_another_problem_when_words_end_like_a_suffix():
    got = problems("""
  applyFrame(frame([prob("same thing"), prob("same thing"), prob("same thing#2")]));
  const keys = items().map((e) => e.getAttribute("data-k"));
  const t = textOf(2);
  sel.setBaseAndExtent(t, 0, t, 4);                      // "Same" in "Same thing#2"
  const said = String(sel);
  applyFrame(frame([prob("same thing#2"), prob("same thing"), prob("same thing")]));   // a reorder
  const owner = sel.anchorNode ? sel.anchorNode.parentNode.parentNode.textContent : null;
  report({ keys, said, text: String(sel), owner, inFirst: sel.anchorNode === textOf(0) });""")
    assert len(set(got["keys"])) == 3                       # three keys, however the words end
    assert got["said"] == "Same"
    assert got["text"] in ("", "Same")
    if got["text"]:
        assert got["owner"].startswith("Same thing#2") and got["inFirst"] is True   # kept only in its own problem


@needs_node
def test_a_line_of_null_and_a_line_of_zero_are_two_problems_and_a_selection_stays_in_its_own():
    got = problems("""
  applyFrame(frame([prob("same thing", null), prob("same thing", 0)]));
  const keys = items().map((e) => e.getAttribute("data-k"));
  const t = textOf(1);                                   // the problem with line 0
  sel.setBaseAndExtent(t, 5, t, 10);
  applyFrame(frame([prob("same thing", 0), prob("same thing", null)]));   // they swap places
  const owner = sel.anchorNode ? sel.anchorNode.parentNode.parentNode.getAttribute("data-k") : null;
  const swapped = items().map((e) => e.getAttribute("data-k"));
  report({ keys, swapped, text: String(sel), owner });""")
    assert len(set(got["keys"])) == 2
    assert got["swapped"] == [got["keys"][1], got["keys"][0]]   # a problem keeps its key when the list moves
    assert got["text"] in ("", "thing")
    if got["text"]:
        assert got["owner"] == got["keys"][1]               # still the problem with line 0, never the one with null

@needs_node
def test_problems_alike_in_everything_still_get_their_own_keys_and_a_selection_stays_in_its_own():     # must-pass
    got = problems("""
  applyFrame(frame([prob("same thing"), prob("same thing"), prob("other")]));
  const keys = items().map((e) => e.getAttribute("data-k"));
  const t = textOf(1);
  sel.setBaseAndExtent(t, 5, t, 10);
  applyFrame(frame([prob("same thing"), prob("same thing"), prob("other"), prob("more")]));
  report({ keys, text: String(sel), second: sel.anchorNode === textOf(1) });""")
    assert len(set(got["keys"])) == 3
    assert got["text"] == "thing" and got["second"] is True


# ---------------------------------------------------------------- D20: a reading written into a reason is not a change
BUSY = """
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#documents/d1";
route();
return settled().then(async () => {
  const doc = { id: "d1", agent: "Alder", project_name: "P", slug: "p", title: "Doc", master: "MASTER.md", updated: "2026-10-01T10:00:00Z", docs: [], diagrams: [] };
  D.text.set("d1/MASTER.md@2026-10-01T10:00:00Z", { text: "Hello world, a short master.\\n" });
  const compute = (cpu, mem, over) => Object.assign({ verdict: "free", reasons: [], not_read: ["the GPU"], could_not_tell: [], games: [], cpu_busy: cpu, memory_free: mem }, over || {});
  const busyCpu = (cpu) => compute(cpu, 40, { verdict: "light", reasons: ["the processor is " + cpu.toFixed(0) + "% busy"] });
  const lowMem = (mem) => compute(20, mem, { verdict: "light", reasons: ["only " + mem.toFixed(0) + "% of memory is free"] });
  const gameBusy = (cpu) => compute(cpu, 40, { verdict: "hold", games: ["Game.exe"],
    reasons: ["a game is running: Game.exe", "a Direct3D full-screen program is in front", "the processor is " + cpu.toFixed(0) + "% busy"] });
  let served;
  const reply = (c) => ({ documents: [doc], frame: { name: null, word: null, waiting: 0, problems: [], outside: [], compute: c } });
  globalThis.fetch = async (url) => (String(url).includes("/api/v2/documents")
    ? { ok: true, json: async () => JSON.parse(JSON.stringify(served)) }
    : { ok: false, status: 404, json: async () => ({ error: "none" }) });
  const place = document.getElementById("place");
  const crumb = () => place.all((e) => e.tagName === "A" && e.textContent === "Documents")[0];
  const series = async (first, list) => {
    served = reply(first); await load("documents");
    const c0 = crumb(); c0.focus();
    const rev0 = S.rev, changed = [];
    for (const c of list) { served = reply(c); changed.push(await load("documents")); }
    return { changed, rev: S.rev - rev0, same: crumb() === c0, focus: document.activeElement === c0, tooltip: document.getElementById("gaming").title };
  };
  //BODY
});
"""


@needs_node
def test_a_busy_machine_whose_reading_moves_inside_a_reason_changes_nothing_on_the_page():
    got = run(BUSY.replace("//BODY", """
  const cpu = await series(busyCpu(91), [busyCpu(92), busyCpu(93.4), busyCpu(95), busyCpu(97)]);
  const mem = await series(lowMem(9), [lowMem(8), lowMem(7.2), lowMem(9.6), lowMem(5)]);
  const game = await series(gameBusy(90.4), [gameBusy(91), gameBusy(92.2), gameBusy(96), gameBusy(99)]);
  report({ cpu, mem, game });"""))
    for name in ("cpu", "mem", "game"):
        s = got[name]
        assert s["changed"] == [False] * 4, name
        assert s["rev"] == 0 and s["same"] is True and s["focus"] is True, name
    assert "97% busy" in got["cpu"]["tooltip"]              # and the newest reading is the one the tooltip shows
    assert "5% of memory" in got["mem"]["tooltip"]
    assert "99% busy" in got["game"]["tooltip"]


@needs_node
def test_a_reason_that_appears_goes_away_or_changes_its_words_is_still_a_change():                      # must-refuse
    got = run(BUSY.replace("//BODY", """
  served = reply(compute(12, 60)); await load("documents");
  const rev = S.rev;
  served = reply(busyCpu(91)); const appears = await load("documents");
  served = reply(lowMem(8)); const otherReason = await load("documents");
  served = reply(gameBusy(95)); const game = await load("documents");
  served = reply(compute(12, 60)); const gone = await load("documents");
  report({ appears, otherReason, game, gone, rev: S.rev - rev });"""))
    assert got["appears"] is True and got["otherReason"] is True and got["game"] is True and got["gone"] is True
    assert got["rev"] == 4


# ---------------------------------------------------------------- Diffmap's box names its command
@needs_node
def test_diffmaps_copy_box_is_labelled_for_the_command_and_documents_for_master():
    got = run("""
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#diffmap/f1/spec.md";
route();
return settled().then(async () => {
  const place = document.getElementById("place");
  const spec = { folder: "f1", file: "spec.md", title: "T", stem: "spec", agent: "Alder", project_name: "P", slug: "p", updated: "2026-10-01T10:00:00Z", command: "diffmap open f1/spec.md" };
  S.data.diffmap = { specs: [spec], note: null };
  fill();
  navigator.clipboard.writeText = () => Promise.reject(new Error("refused"));
  const copy = place.all((e) => e.tagName === "BUTTON" && e.getAttribute("data-k") === "copy:f1:spec.md")[0];
  copy.click();
  for (let i = 0; i < 6; i++) await Promise.resolve();
  const label = () => place.all((e) => e.className === "copy-box")[0].getAttribute("aria-label");
  const first = label();
  fill();                                                 // drawn again from D.box: the same label
  report({ first, again: label(), master: boxNodes()[0].getAttribute("aria-label") });
});""")
    assert "diffmap command" in got["first"] and "MASTER" not in got["first"]
    assert got["again"] == got["first"]
    assert got["master"] == "MASTER.md, selected to copy"


# ---------------------------------------------------------------- a plug-in place named like an old address
NAMED = FRAME + """
return (async () => {
  applyFrame(frameOf(//PLACES));
  S.data[NAME] = { place: NAME, frame: S.frame };
  location.hash = "#" + NAME;
  route();
  await settled();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  report({ place: S.place, drew: document.getElementById("place").textContent.includes("Drawn by the plug-in") });
})();
"""


def named(tmp_path, name: str, listed: bool):
    js = NAMED.replace("//PLACES", f'place("{name}")' if listed else "").replace("NAME", f'"{name}"')
    return run(js, plugins=modules(tmp_path, **{name: PLAIN}))


@needs_node
@pytest.mark.parametrize("name", ["live", "inbox", "decisions", "agents", "layers", "test", "history"])
def test_a_plugin_place_named_like_an_old_address_is_reached_by_its_own_name(tmp_path, name):
    got = named(tmp_path, name, True)
    assert got["place"] == name and got["drew"] is True


@needs_node
@pytest.mark.parametrize("name,goes", [("live", "today"), ("inbox", "waiting"), ("test", "rules"), ("history", "today")])
def test_the_old_address_still_goes_where_it_went_when_no_plugin_has_the_name(tmp_path, name, goes):   # must-refuse
    got = named(tmp_path, name, False)
    assert got["place"] == goes and got["drew"] is False


@needs_node
def test_a_plugin_named_like_a_builtin_place_stays_the_builtin_place_and_a_prototype_name_is_no_place(tmp_path):
    today = named(tmp_path, "today", True)
    assert today["place"] == "today" and today["drew"] is False        # the stated limit: the built-in wins
    proto = named(tmp_path, "constructor", True)
    assert proto["place"] == "constructor" and proto["drew"] is True   # a name on Object.prototype is a place like any other
    unlisted = named(tmp_path, "constructor", False)
    assert unlisted["place"] == "waiting"                              # and unlisted it is not a place at all
