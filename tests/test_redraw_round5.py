"""The fifth attack of the re-draw (D21 to D26): who changed the selection while a draw waited, the page or the person.

D21  a keyed field in a plug-in module's output lost its range and caret at every draw of the place: the draw's synchronous
     part detached the field before the mark, and the late finish took the new field's default caret for the person's.
     A field the draw replaced is not one the person moved; an unkeyed one is found again by where it stood.
D22  a cross-edge selection was left on OTHER words when the page's own refresh redrew the banner (S.err cleared, "Checked
     HH:MM" on a new minute, a second read during a first import) between the draw's mark and its late finish. The late
     finish tells the page's own states (a chain) from the person's change.
D23  a selection wholly inside a plug-in place with an end ON #place itself was let go at every draw.
D24  a plug-in place named like a property of Object ("constructor") drew its module from Object before any data was read.
     Own properties only; the names are refused; registry.PAGE_NAMES is every name the page answers at.
D25  keep() did not wait for an async render().
D26  frame.rail alone is not a change of the place.
Noise: N9 (ySync), N13 (decimals in a reason), N17 (the title rewritten), N4 (the release of a selection inside the place).

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules. Each must-pass has its must-refuse
beside it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from semantext import pagemodule, registry
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

# Object.prototype's own properties (D24), as the items name them: the test's own list, so a name dropped from the code's list
# is a failing test and not a quietly shorter one.
OBJECT_PROPS = ("constructor", "toString", "valueOf", "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable",
                "toLocaleString", "__proto__", "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__")

FRAME = """
const place = (name, over) => Object.assign({ name, title: name[0].toUpperCase() + name.slice(1), origin: "semantext-" + name, version: "0.3", module: true }, over || {});
const frameOf = (...places) => ({ name: null, word: null, waiting: 0, problems: [], outside: places });
const tick = async () => { await settled(); for (let i = 0; i < 12; i++) await Promise.resolve(); };
"""

TIX = """
export function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("p", { class: "tix-row" }, "Ticket one: the printer on floor two is broken"), h("p", { class: "tix-row" }, "Ticket two: " + data.n + " items listed"));
}
"""

FORM = """
export function render(data, el, helpers) {
  const h = helpers.h;
  el.replaceChildren(h("p", { class: "form-row" }, "Search the tickets"),
    h("input", { "data-k": "tix-q", value: data.q || "hello world" }),
    h("textarea", { "data-k": "tix-note", value: data.note || "first line of the note\\nsecond line" }),
    h("input", { class: "unkeyed", value: data.u || "an unkeyed field" }),
    h("button", { type: "button", class: "mod-btn" }, "Refresh tickets"));
}
"""

# A module whose render() is async: it draws after several awaits.
ASYNC = """
export async function render(data, el, helpers) {
  const h = helpers.h;
  for (let i = 0; i < 6; i++) await Promise.resolve();
  if (globalThis.__hold) await globalThis.__hold;
  if (data.boom) throw new Error("it broke after an await");
  el.replaceChildren(h("p", { class: "tix-row" }, "Ticket one: the printer on floor two is broken"), h("p", { class: "tix-row" }, "Ticket two: " + data.n + " items listed"));
}
"""


def modules(tmp_path, **files) -> Path:
    folder = tmp_path / "plugins"
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / f"{name}.js").write_text(text, encoding="utf-8")
    return folder


# ---------------------------------------------------------------- D21: a keyed field the draw replaced
FORMPAGE = FRAME + """
return (async () => {
  applyFrame(frameOf(place("form")));
  S.data.form = { place: "form", frame: S.frame };
  location.hash = "#form";
  route();
  await tick();
  const el = document.getElementById("place");
  const field = (k) => el.all((e) => e.getAttribute("data-k") === k)[0];
  const unkeyed = () => el.all((e) => e.className === "unkeyed")[0];
  const out = {};
  const runCase = async (name, get, s, e, d, real, change) => {
    const f = get();
    f.focus();
    f.setSelectionRange(s, e, d);
    const before = [f.selectionStart, f.selectionEnd, f.selectionDirection];
    if (real) S.rev++;
    if (change) Object.assign(S.data.form, change);
    fill();
    await tick();
    const g = get();
    out[name] = { before, sameNode: g === f, focused: document.activeElement === g, active: document.activeElement === document.body || !document.activeElement ? "none" : "other",
      after: g ? [g.selectionStart, g.selectionEnd, g.selectionDirection] : null };
  };
  //BODY
  report(out);
})();
"""


def form(tmp_path, body: str):
    return run(FORMPAGE.replace("//BODY", body), plugins=modules(tmp_path, form=FORM))


@needs_node
def test_a_keyed_field_a_plugin_draws_keeps_its_range_and_caret_through_a_draw(tmp_path):
    got = form(tmp_path, """
  for (const real of [false, true]) {
    const k = real ? "_real" : "_quiet";
    await runCase("input" + k, () => field("tix-q"), 2, 7, "forward", real);
    await runCase("inputBackward" + k, () => field("tix-q"), 1, 9, "backward", real);
    await runCase("textarea" + k, () => field("tix-note"), 6, 10, "forward", real);
    await runCase("caretOnly" + k, () => field("tix-q"), 3, 3, "none", real);
    await runCase("caretAtStart" + k, () => field("tix-note"), 0, 0, "none", real);
  }""")
    assert len(got) == 10
    for name, c in got.items():
        assert c["focused"] is True and c["after"] == c["before"], (name, c)   # the very range, on the field shown


@needs_node
def test_a_fuzz_of_ranges_in_a_plugins_keyed_fields_loses_none(tmp_path):                              # h8_fuzz, 60 of 60
    got = form(tmp_path, """
  let seed = 7;
  const rnd = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % k; };
  let lost = 0;
  for (let i = 0; i < 60; i++) {
    const key = rnd(2) ? "tix-q" : "tix-note";
    const real = rnd(2) === 1;
    const len = field(key).value.length;
    let s = rnd(len + 1), e = rnd(len + 1);
    if (s > e) [s, e] = [e, s];
    await runCase("c" + i, () => field(key), s, e, s === e ? "none" : rnd(2) ? "forward" : "backward", real);
    const c = out["c" + i];
    if (!c.focused || c.after.join() !== c.before.join()) lost++;
  }
  out.lost = lost;""")
    assert got["lost"] == 0


@needs_node
def test_an_unkeyed_field_a_plugin_draws_keeps_its_focus_and_range_when_the_draw_reads_the_same(tmp_path):
    got = form(tmp_path, """
  for (const real of [false, true]) {
    const k = real ? "_real" : "_quiet";
    await runCase("unkeyed" + k, unkeyed, 3, 10, "forward", real);
    await runCase("unkeyedCaret" + k, unkeyed, 5, 5, "none", real);
  }""")
    for name, c in got.items():
        assert c["focused"] is True and c["after"] == c["before"], (name, c)


@needs_node
def test_an_unkeyed_field_that_now_reads_other_words_is_not_given_the_focus_or_the_old_range(tmp_path):   # must refuse
    got = form(tmp_path, """
  await runCase("changed", unkeyed, 3, 10, "forward", true, { u: "words the module drew instead" });""")
    c = got["changed"]
    assert c["focused"] is False and c["active"] == "none"                    # not moved onto a field that reads differently
    assert c["after"] != c["before"]                                          # and the old range was not put on other words


@needs_node
def test_a_caret_the_person_moved_in_a_field_outside_the_place_while_a_draw_waited_is_kept(tmp_path):    # must refuse the other way
    got = run(FRAME + """
return (async () => {
  applyFrame(frameOf(place("form")));
  S.data.form = { place: "form", frame: S.frame };
  location.hash = "#form"; route(); await tick();
  const input = document.createElement("input"); input.setAttribute("data-k", "outside-q"); input.value = "typed by the person";
  document.body.append(input);
  input.focus(); input.setSelectionRange(2, 8, "forward");
  S.rev++; fill();                                        // the draw empties the place: the field is not in it
  input.setSelectionRange(11, 11, "none");                // the person clicks elsewhere in it while the draw waits
  await tick();
  report({ range: [input.selectionStart, input.selectionEnd], focused: document.activeElement === input });
})();
""", plugins=modules(tmp_path, form=FORM))
    assert got["range"] == [11, 11] and got["focused"] is True


# ---------------------------------------------------------------- D22: the page's own draws while a draw waits
PLACE_WITH_BANNER = FRAME + """
const probs = [{ reader: "rules", source: "a.md", line: 3, text: "an unknown key in the rules file" },
  { reader: "rules", source: "b.md", line: 7, text: "a second problem here" }];
const frame = (...places) => ({ name: null, word: null, waiting: 0, problems: probs, outside: places });
let n = 3, fail = false;
globalThis.fetch = async (url) => {
  if (fail) throw new Error("the server went away");
  if (String(url).includes("/api/v2/tix")) return { ok: true, json: async () => ({ n, frame: frame(place("tix")) }) };
  return { ok: false, status: 404, json: async () => ({ error: "none" }) };
};
const refresh = __ticks[0];
"""

REFRESH = PLACE_WITH_BANNER + """
return (async () => {
  S.open.add("problems:show");
  applyFrame(frame(place("tix")));
  location.hash = "#tix";
  await route();
  await tick();
  const el = document.getElementById("place"), box = document.getElementById("problems"), checked = document.getElementById("checked");
  const sel = window.getSelection();
  const rows = () => el.all((e) => e.className === "tix-row");
  const row0 = () => rows()[0].childNodes[0];
  const probText = (i) => box.all((e) => e.tagName === "LI")[i].childNodes[0].childNodes[0];
  const last = () => box.all((e) => e.tagName === "LI").length - 1;
  const out = {};
  const runCase = async (name, before, set) => {
    await before();
    await tick();
    set();
    const was = String(sel);
    n++;                                                   // the plug-in's data changed: this read draws
    await refresh();
    await tick();
    out[name] = { was, after: String(sel), collapsed: sel.isCollapsed, err: S.err };
    sel.removeAllRanges();
  };
  const failed = async () => { fail = true; await refresh(); fail = false; };   // S.err set: the banner lists "could not read" first
  const none = async () => {};
  //BODY
  report(out);
})();
"""


def refresh(tmp_path, body: str):
    return run(REFRESH.replace("//BODY", body), plugins=modules(tmp_path, tix=TIX))


@needs_node
def test_a_draw_left_for_another_place_while_it_waited_holds_nothing_for_the_next_one():
    got = run(KEEP.replace("//BODY", """
  const p = document.createElement("p"); p.append("some words to hold"); region.append(p);
  const t = p.childNodes[0];
  sel.setBaseAndExtent(t, 2, t, 9);
  const w = later();
  keep(() => w.p, region);                                // a draw that waits and leaves the page as it was
  S.mounted = "elsewhere/";                               // the person went to another place: this draw is stale
  w.go(); await flush();                                  // it is dropped, never finished
  const r = holdSelection(null, region);
  const took = r.mark({});                                // a draw that begins on the same state must not take a dead one over
  report({ leaked: took !== undefined && took !== r });"""))
    assert got["leaked"] is False


@needs_node
def test_a_selection_across_the_places_edge_is_let_go_when_the_banner_is_redrawn_in_the_same_wait(tmp_path):   # h1a
    got = refresh(tmp_path, """
  await runCase("forward", failed, () => sel.setBaseAndExtent(probText(last()), 2, row0(), 23));
  await runCase("backward", failed, () => sel.setBaseAndExtent(row0(), 23, probText(last()), 2));
  await runCase("noBannerRedraw", none, () => sel.setBaseAndExtent(probText(last()), 2, row0(), 23));""")
    for name, c in got.items():
        assert c["was"] != "" and c["after"] == "" and c["collapsed"] is True, (name, c)    # let go: never the words left over


@needs_node
def test_a_selection_inside_the_place_is_kept_when_the_banner_is_redrawn_in_the_same_wait(tmp_path):         # must pass beside it
    got = refresh(tmp_path, """
  await runCase("inside", failed, () => sel.setBaseAndExtent(row0(), 12, row0(), 23));
  await runCase("insideNoErr", none, () => sel.setBaseAndExtent(row0(), 12, row0(), 23));
  await runCase("bannerOnly", failed, () => sel.setBaseAndExtent(probText(1), 2, probText(1), 9));""")
    for name, c in got.items():
        assert c["was"] != "" and c["after"] == c["was"], (name, c)


@needs_node
def test_a_fuzz_of_cross_edge_selections_through_the_pages_own_refresh_never_ends_on_other_words(tmp_path):    # h1_fuzz
    got = refresh(tmp_path, """
  let seed = 20261108;
  const rnd = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % k; };
  const outsideZones = [
    () => { const lis = box.all((e) => e.tagName === "LI"); return lis[1 + rnd(lis.length - 1)].childNodes[0].childNodes[0]; },
    () => { const lis = box.all((e) => e.tagName === "LI"); return lis[1 + rnd(lis.length - 1)].childNodes[1].childNodes[0]; },
  ];
  const insideZones = [
    () => el.childNodes[0].childNodes[0],
    () => rows()[0].childNodes[0],
    () => rows()[1].childNodes[0],
  ];
  const tally = {};
  for (let i = 0; i < 40; i++) {
    for (const withErr of [true, false]) {
      if (withErr) { await failed(); await tick(); }
      const o = outsideZones[rnd(2)](), inn = insideZones[rnd(3)]();
      const oo = rnd(o.data.length + 1), io = rnd(inn.data.length + 1);
      if (rnd(2)) sel.setBaseAndExtent(inn, io, o, oo); else sel.setBaseAndExtent(o, oo, inn, io);
      const was = String(sel);
      if (!was) { sel.removeAllRanges(); continue; }
      n++;
      await refresh();
      await tick();
      const after = String(sel);
      const cls = after === was ? "kept" : !after ? "letGo" : "OTHER_WORDS";
      tally[cls] = (tally[cls] || 0) + 1;
      sel.removeAllRanges();
    }
  }
  out.tally = tally;""")
    assert "OTHER_WORDS" not in got["tally"]
    assert got["tally"].get("letGo", 0) >= 40       # the fuzz really drew cross-edge selections


@needs_node
def test_a_selection_across_the_places_edge_is_let_go_when_checked_is_rewritten_in_the_same_wait(tmp_path):   # h1c
    got = run(FRAME + """
const frame = () => frameOf(place("tix"));
let n = 3;
globalThis.fetch = async (url) => (String(url).includes("/api/v2/tix")
  ? { ok: true, json: async () => ({ n, frame: frame() }) }
  : { ok: false, status: 404, json: async () => ({ error: "none" }) });
const refresh = __ticks[0];
return (async () => {
  applyFrame(frame());
  location.hash = "#tix";
  await route();
  await tick();
  const el = document.getElementById("place"), checked = document.getElementById("checked");
  const sel = window.getSelection();
  const row0 = () => el.all((e) => e.className === "tix-row")[0].childNodes[0];
  const out = {};
  const runCase = async (name, minuteRolled, set) => {
    if (minuteRolled) checked.textContent = "Checked 00:00";   // the words the bar showed a minute ago: this read writes them again
    await tick();
    set();
    const was = String(sel);
    n++;
    await refresh();
    await tick();
    out[name] = { was, after: String(sel), checkedNow: checked.textContent };
    sel.removeAllRanges();
  };
  const endOfChecked = () => [checked.childNodes[0], checked.childNodes[0].data.length];
  await runCase("fromEndOfChecked", true, () => { const [t, o] = endOfChecked(); sel.setBaseAndExtent(t, o, row0(), 23); });
  await runCase("backward", true, () => { const [t, o] = endOfChecked(); sel.setBaseAndExtent(row0(), 23, t, o); });
  await runCase("fromCheckedWords", true, () => { const [t] = endOfChecked(); sel.setBaseAndExtent(t, 2, row0(), 23); });
  await runCase("inside_control", true, () => sel.setBaseAndExtent(row0(), 12, row0(), 23));
  report(out);
})();
""", plugins=modules(tmp_path, tix=TIX))
    for name in ("fromEndOfChecked", "backward", "fromCheckedWords"):
        assert got[name]["was"] != "" and got[name]["after"] == "", name
    assert got["inside_control"]["after"] == got["inside_control"]["was"] == "the printer"     # must pass beside them
    assert got["fromEndOfChecked"]["checkedNow"].startswith("Checked ") and got["fromEndOfChecked"]["checkedNow"] != "Checked 00:00"


SLOWREADS = FRAME + """
const probs = [{ reader: "rules", source: "a.md", line: 3, text: "an unknown key in the rules file" },
  { reader: "rules", source: "b.md", line: 7, text: "a second problem here" }];
const frame = () => ({ name: null, word: null, waiting: 0, problems: probs, outside: [place("slow", { title: "Slowly" })] });
let n = 3;
globalThis.fetch = async (url) => (String(url).includes("/api/v2/slow")
  ? { ok: true, json: async () => ({ n, frame: frame() }) }
  : { ok: false, status: 404, json: async () => ({ error: "none" }) });
const refresh = __ticks[0];
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  let release;
  const mod = { render(data, el, h) { el.replaceChildren(h.h("p", { class: "slow-row" }, "Slow words here: " + data.n)); } };
  importer.load = () => new Promise((r) => { release = () => r(mod); });
  S.open.add("problems:show");
  applyFrame(frame());
  location.hash = "#slow";
  await route();                                   // the first draw waits for the module
  await flush();
  const el = document.getElementById("place"), box = document.getElementById("problems");
  const sel = window.getSelection();
  const lis = box.all((e) => e.tagName === "LI");
  const b = lis[lis.length - 1].childNodes[0].childNodes[0];
  const meta = el.childNodes[0].childNodes[0];
  sel.setBaseAndExtent(b, 2, meta, 7);             // a problem's words into "Slowly ·" (the meta line, drawn at once)
  const out = { was: String(sel) };
  //BODY
})();
"""


@needs_node
@pytest.mark.parametrize("reads", [1, 2, 3])
def test_a_selection_across_the_edge_is_let_go_after_any_number_of_reads_while_the_module_loads(reads):      # h1b, h1b_control
    got = run(SLOWREADS.replace("//BODY", f"""
  for (let i = 0; i < {reads}; i++) {{ n++; await refresh(); await flush(); }}
  release();
  await settled();
  await flush();
  report({{ was: out.was, after: String(sel), drew: el.textContent.includes("Slow words here") }});"""))
    assert got["was"] != "" and got["after"] == "" and got["drew"] is True


@needs_node
def test_other_words_selected_while_the_module_loads_and_the_page_reads_again_are_kept():          # must refuse the other way
    got = run(SLOWREADS.replace("//BODY", """
  n++; await refresh(); await flush();
  sel.setBaseAndExtent(b, 1, b, 6);                  // the person selects other words, wholly in the banner
  const theirs = String(sel);
  n++; await refresh(); await flush();               // the page reads again and draws the place again
  release();
  await settled();
  await flush();
  report({ theirs, after: String(sel), drew: el.textContent.includes("Slow words here") });"""))
    assert got["theirs"] != "" and got["after"] == got["theirs"] and got["drew"] is True


@needs_node
def test_a_selection_released_while_the_module_loads_and_the_page_reads_again_stays_released():       # must refuse
    got = run(SLOWREADS.replace("//BODY", """
  n++; await refresh(); await flush();
  sel.removeAllRanges();                             // the person lets go
  n++; await refresh(); await flush();
  release();
  await settled();
  await flush();
  report({ after: String(sel), collapsed: sel.isCollapsed, drew: el.textContent.includes("Slow words here") });"""))
    assert got["after"] == "" and got["collapsed"] is True and got["drew"] is True


@needs_node
def test_a_waiting_draw_is_dropped_when_it_never_finishes_and_one_that_is_alive_is_taken_over():
    got = run(FRAME + """
return (async () => {
  const region = document.getElementById("place");
  const sel = window.getSelection();
  const text = document.createElement("p"); text.append("some words to hold"); region.append(text);
  const t = text.childNodes[0];
  const hold = () => { sel.setBaseAndExtent(t, 2, t, 9); return holdSelection(null, region); };
  const a = hold(); a.mark("one");
  const b = hold(); const took = b.mark("two");            // begins on a state a waiting draw holds: takes its selection over
  const out = { tookOver: took === a };
  a.drop("one");                                            // not the owner any more: the draw that took it over still has it
  const d = hold(); const still = d.mark("four");
  out.stillHeld = still !== undefined && still !== d;
  a.drop("four");                                           // the owner lets it go (never finished)
  sel.setBaseAndExtent(t, 2, t, 9);
  const e = holdSelection(null, region); const gone = e.mark("five");
  out.afterDrop = gone === undefined || gone === e;
  report(out);
})();
""")
    assert got["tookOver"] is True and got["stillHeld"] is True
    assert got["afterDrop"] is True


# ---------------------------------------------------------------- D23: an end on #place itself, within its children
END_ON_PLACE = FRAME + """
return (async () => {
  applyFrame(frameOf(place("tix")));
  S.data.tix = { place: "tix", frame: S.frame, n: 3 };
  location.hash = "#tix";
  route();
  await tick();
  const el = document.getElementById("place");
  const frameEl = () => el.childNodes[1];
  const row = (i) => el.all((e) => e.className === "tix-row")[i].childNodes[0];
  const meta = () => el.childNodes[0].childNodes[0];
  const sel = window.getSelection();
  const out = {};
  const runCase = async (name, set, real, change) => {
    set();
    const before = String(sel);
    if (real) S.rev++;
    if (change) S.data.tix.n = change;
    fill();
    await tick();
    out[name] = { before, after: String(sel) };
    sel.removeAllRanges();
  };
  //BODY
  report(out);
})();
"""


@needs_node
def test_a_selection_wholly_in_the_place_with_an_end_on_the_place_itself_is_kept(tmp_path):
    got = run(END_ON_PLACE.replace("//BODY", """
  for (const real of [false, true]) {
    const k = real ? "_real" : "_quiet";
    await runCase("rowToPlaceEnd" + k, () => sel.setBaseAndExtent(row(0), 5, el, 2), real);
    await runCase("wholePlace" + k, () => sel.setBaseAndExtent(el, 0, el, 2), real);
    await runCase("metaToPlaceEnd" + k, () => sel.setBaseAndExtent(meta(), 3, el, 2), real);
    await runCase("placeStartToRow" + k, () => sel.setBaseAndExtent(el, 0, row(1), 10), real);
    await runCase("frameStartToRow" + k, () => sel.setBaseAndExtent(frameEl(), 0, row(1), 10), real);   // kept before this change too
    await runCase("textOnly" + k, () => sel.setBaseAndExtent(row(0), 5, row(1), 10), real);
  }"""), plugins=modules(tmp_path, tix=TIX))
    assert len(got) == 12
    for name, c in got.items():
        assert c["before"] != "" and c["after"] == c["before"], (name, c)


@needs_node
def test_a_selection_with_an_end_on_the_place_whose_words_changed_is_let_go_not_put_on_other_words(tmp_path):   # must refuse
    got = run(END_ON_PLACE.replace("//BODY", """
  await runCase("rowToPlaceEnd", () => sel.setBaseAndExtent(row(0), 5, el, 2), true, 4);     // "3 items" is now "4 items"
  await runCase("metaToPlaceEnd", () => sel.setBaseAndExtent(meta(), 3, el, 2), true, 5);"""), plugins=modules(tmp_path, tix=TIX))
    for name, c in got.items():
        assert c["before"] != "" and c["after"] == "", (name, c)


# ---------------------------------------------------------------- D24: own properties only; the names are refused
@needs_node
def test_a_place_named_like_a_property_of_object_draws_nothing_before_its_data_is_read(tmp_path):         # h13
    got = run(FRAME + """
let mode = "never";
const P = place("constructor", { title: "Tickets" }), Q = place("tixother", { title: "Other" });
globalThis.fetch = (url) => {
  if (mode === "never") return new Promise(() => {});
  if (mode === "fail") return Promise.resolve({ ok: false, status: 500, json: async () => ({ error: "the plug-in's read failed" }) });
  return Promise.resolve({ ok: true, json: async () => ({ n: 5, frame: frameOf(P, Q) }) });
};
return (async () => {
  const out = {};
  applyFrame(frameOf(P, Q));
  const el = document.getElementById("place");
  const rows = () => el.all((e) => e.className === "tix-row").map((e) => e.textContent);
  const at = async (name, how) => { mode = how; location.hash = "#" + name; const r = route(); if (how !== "never") await r; await tick(); return { place: S.place, err: S.err, own: Object.hasOwn(S.data, name), rows: rows(), text: el.textContent }; };
  out.constructorBefore = await at("constructor", "never");
  out.otherBefore = await at("tixother", "never");
  out.constructorFailed = await at("constructor", "fail");
  out.otherFailed = await at("tixother", "fail");
  out.constructorRead = await at("constructor", "ok");
  out.otherRead = await at("tixother", "ok");
  report(out);
})();
""", plugins=modules(tmp_path, constructor=TIX, tixother=TIX))
    for k in ("constructorBefore", "otherBefore", "constructorFailed", "otherFailed"):
        assert got[k]["rows"] == [] and got[k]["own"] is False, k                    # not drawn from anything read
    assert got["constructorFailed"]["err"] and got["otherFailed"]["err"]
    for k in ("constructorRead", "otherRead"):                                      # must pass beside them: real data is drawn
        assert got[k]["rows"] == ["Ticket one: the printer on floor two is broken", "Ticket two: 5 items listed"], k


@needs_node
def test_the_refused_names_are_all_of_objects_own_properties():
    got = run("report(Object.getOwnPropertyNames(Object.prototype).sort())")
    assert sorted(OBJECT_PROPS) == got                       # the list is the whole of them, in this node
    assert sorted(registry.OBJECT_PROPS) == sorted(OBJECT_PROPS)


@pytest.mark.parametrize("name", OBJECT_PROPS)
def test_a_plugin_place_named_like_a_property_of_object_is_refused(name):                       # must refuse
    class Place:
        kind, title, build = "place", "A place", lambda self, sources: {}

    Place.name = name
    for spelled in (name, name.upper(), name.lower()):
        with pytest.raises(ValueError, match="property every object has"):
            registry.Registry().add("place", spelled, Place(), origin="someone")
    assert not pagemodule.NAME.fullmatch(name) and not pagemodule.NAME.fullmatch(name.lower())


def test_a_name_that_only_starts_like_one_is_a_name_and_other_kinds_may_use_it():                  # must pass beside them
    class Thing:
        kind, title, name = "place", "A place", "constructors"

        def build(self, sources):
            return {}

    assert registry.Registry().add("place", "constructors", Thing(), origin="someone").name == "constructors"
    assert pagemodule.NAME.fullmatch("constructors") and pagemodule.NAME.fullmatch("constructor-x") and pagemodule.NAME.fullmatch("tix")
    assert not pagemodule.NAME.fullmatch("constructor.js")
    from semantext import server
    assert not server.PLUGIN_FILE.fullmatch("constructor.js") and server.PLUGIN_FILE.fullmatch("constructors.js")


@needs_node
def test_registry_page_names_are_every_name_the_page_answers_at():                              # drift: one list, the page's own
    got = run("report({ route: Object.keys(ROUTE), old: Object.keys(OLD) })")
    page = set(got["route"]) | set(got["old"]) | {"overview"}                                      # overview: the first release's place
    assert set(registry.PAGE_NAMES) == page
    assert len(registry.PAGE_NAMES) == len(page)                                                   # none twice


@pytest.mark.parametrize("name", registry.PAGE_NAMES)
def test_an_outside_place_cannot_take_any_name_the_page_answers_at(name):                          # must refuse
    class Place:
        kind, title, build = "place", "A place", lambda self, sources: {}

    Place.name = name
    with pytest.raises(ValueError, match="could never be reached"):
        registry.Registry().add("place", name, Place(), origin="someone")
    with pytest.raises(ValueError, match="could never be reached"):
        registry.Registry().add("place", name.upper(), Place(), origin="someone")


def test_a_place_under_a_name_the_page_does_not_answer_at_is_still_added():                       # must pass beside them
    class Place:
        kind, title, name, build = "place", "A place", "prisms", lambda self, sources: {}

    assert registry.Registry().add("place", "prisms", Place(), origin="someone").name == "prisms"


# ---------------------------------------------------------------- D25: an async render is waited for
@needs_node
def test_a_selection_in_a_module_whose_render_is_async_is_kept_through_a_draw(tmp_path):
    got = run(END_ON_PLACE.replace("//BODY", """
  for (const real of [false, true]) {
    const k = real ? "_real" : "_quiet";
    await runCase("inside" + k, () => sel.setBaseAndExtent(row(0), 12, row(0), 23), real);
    await runCase("acrossRows" + k, () => sel.setBaseAndExtent(row(0), 0, row(1), 10), real);
  }
  out.rows = el.all((e) => e.className === "tix-row").map((e) => e.textContent);"""), plugins=modules(tmp_path, tix=ASYNC))
    assert got["rows"] == ["Ticket one: the printer on floor two is broken", "Ticket two: 3 items listed"]
    for name in ("inside_quiet", "inside_real", "acrossRows_quiet", "acrossRows_real"):
        assert got[name]["before"] != "" and got[name]["after"] == got[name]["before"], name


@needs_node
def test_settled_waits_for_an_async_render_and_a_selection_the_person_released_meanwhile_stays_released(tmp_path):
    got = run(END_ON_PLACE.replace("//BODY", """
  let go; globalThis.__hold = new Promise((r) => { go = r; });
  sel.setBaseAndExtent(row(0), 12, row(0), 23);
  fill();                                                 // the async render waits for the test's promise
  const early = el.all((e) => e.className === "tix-row").length;
  sel.removeAllRanges();                                  // the person lets go while it waits
  go();
  await tick();
  out.asyncRelease = { early, rows: el.all((e) => e.className === "tix-row").length, after: String(sel), collapsed: sel.isCollapsed };
  globalThis.__hold = null;"""), plugins=modules(tmp_path, tix=ASYNC))
    assert got["asyncRelease"] == {"early": 0, "rows": 2, "after": "", "collapsed": True}


@needs_node
def test_a_module_whose_async_render_throws_leaves_a_problem_line_and_no_selection_on_other_words(tmp_path):   # must refuse
    got = run(END_ON_PLACE.replace("//BODY", """
  sel.setBaseAndExtent(row(0), 12, row(0), 23);
  S.data.tix.boom = true; S.rev++;
  fill();
  await tick();
  out.boom = { problem: el.textContent.includes("could not draw it: it broke after an await"), after: String(sel) };"""), plugins=modules(tmp_path, tix=ASYNC))
    assert got["boom"]["problem"] is True and got["boom"]["after"] in ("", "the printer")


@needs_node
def test_a_module_whose_render_is_not_async_still_draws_and_keeps_the_selection(tmp_path):         # must pass beside them
    got = run(END_ON_PLACE.replace("//BODY", """
  await runCase("inside", () => sel.setBaseAndExtent(row(0), 12, row(0), 23), true);"""), plugins=modules(tmp_path, tix=TIX))
    assert got["inside"]["after"] == got["inside"]["before"] == "the printer"


# ---------------------------------------------------------------- D26: frame.rail is not a change of the place
@needs_node
def test_a_read_that_differs_in_frame_rail_alone_is_not_a_change_of_the_place(tmp_path):
    got = run(FRAME + """
let rail = { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 }, n = 3, other = 0;
globalThis.fetch = async (url) => ({ ok: true, json: async () => ({ n, frame: Object.assign(frameOf(place("tix")), { rail, other }) }) });
return (async () => {
  applyFrame(frameOf(place("tix")));
  location.hash = "#tix";
  await route();
  await tick();
  const el = document.getElementById("place");
  const sel = window.getSelection();
  const rows = () => el.all((e) => e.className === "tix-row");
  const row0 = () => rows()[0].childNodes[0];
  sel.setBaseAndExtent(row0(), 12, row0(), 23);
  const was = String(sel), nodes = rows(), rev = S.rev;
  rail = { a: 9, b: 8, c: 7, d: 6, e: 5, f: 4 };                     // the rail alone
  const changed = await load("tix");
  await tick();
  const out = { was, changed, rev: S.rev - rev, sameNodes: rows().every((r, i) => r === nodes[i]) && rows().length === 2, after: String(sel), railNow: S.frame.rail.a };
  other = 1;                                                          // control: a change outside the rail
  const controlChanged = await load("tix");
  await tick();
  out.control = { changed: controlChanged, rev: S.rev - rev, sameNodes: rows().every((r, i) => r === nodes[i]) };
  n = 4;                                                              // control: the place's own data
  out.controlData = { changed: await load("tix") };
  await tick();
  out.controlData.text = el.textContent.includes("4 items listed");
  report(out);
})();
""", plugins=modules(tmp_path, tix=TIX))
    assert got["changed"] is False and got["rev"] == 0 and got["sameNodes"] is True
    assert got["was"] == "the printer" and got["after"] == "the printer"
    assert got["railNow"] == 9                                          # the bar still gets the newest rail
    assert got["control"]["changed"] is True and got["control"]["rev"] == 1                       # must pass beside it
    assert got["controlData"] == {"changed": True, "text": True}


# ---------------------------------------------------------------- noise: surviving mutants pinned
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
def test_a_page_that_shrank_while_the_draw_waited_is_scrolled_back_when_it_grows_again():             # N9
    got = run(KEEP.replace("//BODY", """
  const calls = [];
  window.scrollTo = (x, y) => { calls.push(y); };         // the page is too short to scroll: scrollY does not follow
  window.scrollY = 900;
  const w = later();
  keep(() => { window.scrollY = 300; return w.p; });      // the draw empties the place: the browser clamps the scroll
  w.go(); await flush();
  report({ calls });"""))
    assert got["calls"] == [900, 900]                      # once while it waited, once when it finished


@needs_node
def test_a_scroll_the_person_made_after_the_page_shrank_is_not_undone():                           # must refuse the other way
    got = run(KEEP.replace("//BODY", """
  const calls = [];
  window.scrollTo = (x, y) => { calls.push(y); };
  window.scrollY = 900;
  const w = later();
  keep(() => { window.scrollY = 300; return w.p; });
  window.scrollY = 120;                                   // the person scrolls up while it waits
  w.go(); await flush();
  report({ calls, now: window.scrollY });"""))
    assert got["calls"] == [900] and got["now"] == 120


COMPUTE = FRAME + """
let reasons = [];
globalThis.fetch = async () => ({ ok: true, json: async () => ({ frame: Object.assign(frameOf(), { compute: { verdict: "hold", reasons, cpu_busy: 90, memory_free: 5000, not_read: [] } }) }) });
return (async () => {
  const out = {};
  const step = async (name, r) => { reasons = r; const c = await load("sources"); out[name] = { changed: c, rev: S.rev }; };
  //BODY
  report(out);
})();
"""


@needs_node
def test_a_reading_with_decimals_written_into_a_reason_is_not_a_change():                          # N13
    got = run(COMPUTE.replace("//BODY", """
  await step("first", ["the processor is 93.5% busy"]);
  await step("decimalStep", ["the processor is 94.5% busy"]);
  await step("wholeStep", ["the processor is 95% busy"]);
  await step("memoryDecimals", ["the processor is 95% busy", "only 7.25% of memory is free"]);
  await step("memoryStep", ["the processor is 95% busy", "only 7.5% of memory is free"]);
  await step("words", ["the processor is 95% busy", "only 7.5% of memory is idle"]);"""))
    assert got["first"]["changed"] is True
    assert got["decimalStep"]["changed"] is False and got["wholeStep"]["changed"] is False       # numbers only
    assert got["memoryDecimals"]["changed"] is True                                               # a reason that appeared
    assert got["memoryStep"]["changed"] is False
    assert got["words"]["changed"] is True                                                         # must refuse: words changed


@needs_node
def test_the_gaming_tooltip_is_written_only_when_it_differs():                                      # N17
    got = run(FRAME + """
const node = document.getElementById("gaming");
let writes = 0, held = "";
Object.defineProperty(node, "title", { get: () => held, set: (v) => { writes++; held = v; } });
const on = (why) => ({ name: null, word: null, waiting: 0, problems: [], outside: [], gaming: { state: "unknown", why } });
applyFrame(on("the flag could not be read"));
const first = writes;
applyFrame(on("the flag could not be read"));
applyFrame(on("the flag could not be read"));
const unchanged = writes;
applyFrame(on("another reason"));
report({ first, unchanged, changed: writes, title: node.title });
""")
    assert got["first"] == 1 and got["unchanged"] == 1                 # three reads of one title: one write
    assert got["changed"] == 2 and got["title"] == "another reason"   # must pass beside it: a new title is written


@needs_node
def test_a_selection_inside_the_place_that_the_person_released_while_the_module_loaded_is_not_brought_back():   # N4
    got = run(FRAME + """
return (async () => {
  let release;
  const mod = { render(data, el, helpers) { el.replaceChildren(helpers.h("p", null, "Slow words here")); } };
  importer.load = () => new Promise((r) => { release = () => r(mod); });
  applyFrame(frameOf(place("slow", { title: "Slowly" })));
  const sel = window.getSelection();
  S.data.slow = { place: "slow", frame: S.frame };
  location.hash = "#slow";
  route();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  const el = document.getElementById("place");
  const flush = async () => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
  const out = {};
  const meta = el.childNodes[0].childNodes[0];
  sel.setBaseAndExtent(meta, 0, meta, 3);             // "Slo": wholly inside the place, and drawn again with the same words
  fill();                                              // a draw that waits for the module
  sel.collapse(el.childNodes[0].childNodes[0], 2);     // the person's click, in the meta line drawn again
  release();
  await settled(); await flush();
  out.caret = [String(sel), sel.isCollapsed];
  sel.setBaseAndExtent(el.childNodes[0].childNodes[0], 0, el.childNodes[0].childNodes[0], 3);
  fill();
  sel.removeAllRanges();                               // the person lets go
  await settled(); await flush();
  out.released = [String(sel), sel.isCollapsed];
  report(out);
})();
""")
    assert got["caret"] == ["", True]
    assert got["released"] == ["", True]


@needs_node
def test_a_selection_inside_the_place_that_nobody_touched_is_put_back_when_the_module_lands():     # N4's must pass
    got = run(FRAME + """
return (async () => {
  const mod = { render(data, el, helpers) { el.replaceChildren(helpers.h("p", null, "Slow words here")); } };
  let release;
  importer.load = () => new Promise((r) => { release = () => r(mod); });
  applyFrame(frameOf(place("slow", { title: "Slowly" })));
  const sel = window.getSelection();
  S.data.slow = { place: "slow", frame: S.frame };
  location.hash = "#slow";
  route();
  for (let i = 0; i < 4; i++) await Promise.resolve();
  const el = document.getElementById("place");
  const meta = el.childNodes[0].childNodes[0];
  sel.setBaseAndExtent(meta, 0, meta, 3);
  fill();
  release();
  await settled();
  for (let i = 0; i < 8; i++) await Promise.resolve();
  report({ text: String(sel) });
})();
""")
    assert got["text"] == "Slo"
