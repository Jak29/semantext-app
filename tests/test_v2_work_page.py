"""The Work place drawn by the page's own modules in node (tests/v2_dom.js), for the fixture world in work_world.py.

The visible text of each view (the strip, the board, the backlog, the estate and one item's panel) is pinned to a
checked-in file (tests/v2_work_pin.json); a change to what the page shows must change it, on purpose. To write it
again: SEMANTEXT_WRITE_PIN=1 pytest tests/test_v2_work_page.py. The inbox link's form is checked again in the page, and
its must-refuse arms are here. Skipped where node is not installed.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from v2_node import NODE, PAGE, run
from work_world import build, place

PIN = Path(__file__).with_name("v2_work_pin.json")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

TEXTS = r"""
S.frame = Object.assign(S.frame || {}, { inbox_app: true });
for (const name of ["toLocaleString", "toLocaleDateString", "toLocaleTimeString"]) {
  const was = Date.prototype[name];
  Date.prototype[name] = function (locales, opts) { return was.call(this, "en-US", Object.assign({}, opts, { timeZone: "UTC" })); };
}
function texts(root) {
  const out = [];
  const walk = (n, folded) => {
    for (const c of n.childNodes) {
      if (!c.tagName) continue;
      const own = c.childNodes.filter((x) => !x.tagName).map((x) => x.textContent).join("").trim();
      const fold = folded || (c.tagName === "DETAILS" && !c.open);
      const mark = (c.hidden ? " (hidden)" : "") + (folded && c.tagName !== "SUMMARY" ? " (folded)" : "");
      if (own) out.push(c.tagName.toLowerCase() + (c.className ? "." + c.className.trim().split(/\s+/).join(".") : "") + mark + ": " + own);
      walk(c, c.tagName === "SUMMARY" ? folded : fold);
    }
  };
  walk(root, false);
  return out;
}
const byClass = (root, cls) => root.all((e) => e.classList.contains(cls));
"""


def world(tmp_path):
    w = build(tmp_path)
    data = json.loads(json.dumps(place(tmp_path)).replace(json.dumps(str(tmp_path))[1:-1], "/fixture"))
    return w, data


def draw(data, sel):
    return run(TEXTS + "const DATA = " + json.dumps(data) + ";\nconst SEL = " + json.dumps(sel) + ";\n" + """
S.place = "work"; S.sub = null; mount(); S.data.work = DATA; fill();
const out = { bar: texts($("bar-place")), strip: texts(WK.strip), board: texts(WK.body) };
S.sub = "backlog"; fill(); out.backlog = texts(WK.body);
S.sub = "estate"; fill(); out.estate = texts(WK.body);
S.sub = null; fill(); workSelect(SEL);
out.address = S.sub;
const panel = byClass($("place"), "work-panel")[0];
out.panel = texts(panel);
out.inbox = panel.all((e) => e.tagName === "A").map((a) => [a.textContent, a.getAttribute("href")]);
out.struck = panel.all((e) => e.tagName === "TR" && e.classList.contains("not-applied")).map((r) => [r.all((e) => e.tagName === "S").length, r.textContent]);
out.selected = byClass(WK.body, "selected").map((b) => b.getAttribute("data-k"));
report(out);
""")


def test_each_view_of_the_work_place_is_pinned(tmp_path):
    w, data = world(tmp_path)
    got = draw(data, w.ids["checked"])
    if os.environ.get("SEMANTEXT_WRITE_PIN"):
        PIN.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    assert got == json.loads(PIN.read_text(encoding="utf-8"))


def test_the_views_say_their_words(tmp_path):
    w, data = world(tmp_path)
    got = draw(data, w.ids["checked"])
    strip, board, estate, panel = (" | ".join(got[k]) for k in ("strip", "board", "estate", "panel"))
    # the strip: the proposal and the request for your word, each with the line to type, and the ranking count
    assert "Waiting on you" in strip and "Birch (bound) proposes parking it" in strip
    assert "W-lab-6 park" in strip and "as a message of its own; a message that adds anything else authorises nothing." in strip
    assert "3 items wait for your ranking (backlog to next)" in strip
    # the board: a lane per project, done and parked folded with their counts, badges in words
    assert "h2.lane-head: lab" in board and "h2.lane-head: orchard" in board
    assert "summary: Done 1" in board and "summary: Parked 0" in board
    assert "(folded): done (your word)" in board and "proof no longer holds" in board
    assert "waits on Alder's review" in board
    # the estate view leads with what no longer holds and what is only claimed
    assert got["estate"][0] == "h2.label: Proof no longer holds · 1" and "h2.label: Done (claimed) · 1" in estate
    # the panel: the forged park struck through, with its reason in words
    assert ["Open in your inbox", "jak-inbox://work/lab/2"] in got["inbox"]
    assert len(got["struck"]) == 1 and got["struck"][0][0] == 6 and "not applied: NOT_AUTHORIZED" in got["struck"][0][1]
    assert "your decision J-20261020-1" in panel and "chip.wbadge.c-met: met" in panel
    assert got["selected"] == ["wi:" + w.ids["checked"]]
    # must refuse: an empty store says so, and shows no strip
    empty = run(TEXTS + """S.place = "work"; S.sub = null; mount(); S.data.work = { store: { exists: false }, items: [], projects: [] }; fill();
report({ head: texts(WK.head), strip: WK.strip.hidden, body: texts(WK.body) });""")
    assert empty["strip"] is True and empty["body"] == ["p.empty: No work items yet."]


def test_with_no_inbox_app_in_the_settings_there_is_no_link(tmp_path):
    w, data = world(tmp_path)
    got = run("S.frame = null;\n" + TEXTS.replace("{ inbox_app: true }", "{ inbox_app: false }") + "const DATA = " + json.dumps(data)
              + ";\nS.place = \"work\"; S.sub = null; mount(); S.data.work = DATA; fill();\n"
              + "report({ links: WK.strip.all((e) => e.tagName === \"A\" && (e.getAttribute(\"href\") || \"\").startsWith(\"jak-inbox:\")).length });")
    assert got["links"] == 0


def test_a_forged_inbox_link_is_never_drawn(tmp_path):
    w, data = world(tmp_path)
    item = next(i for i in data["items"] if i["id"] == w.ids["checked"])
    for bad in ("jak-inbox://work/lab/02", "jak-inbox://work/lab/3", "jak-inbox://work/lab/2?act=done",
                "https://example.com/", "jak-inbox://card/A-20261020-101"):
        item["inbox"] = bad
        got = draw(data, w.ids["checked"])
        assert got["inbox"] == [], bad
        assert "span.meta: No inbox link for this item." in got["panel"] or any("no inbox link" in t for t in got["panel"])


LINKS = [
    ("jak-inbox://work/lab/2", "W-lab-2"),
    ("jak-inbox://work/lab/999999", "W-lab-999999"),
    ("jak-inbox://work/lab/02", None),                       # a leading zero
    ("jak-inbox://work/lab/0", None),
    ("jak-inbox://work/lab/1234567", None),                  # 7 digits
    ("jak-inbox://work/elsewhere/2", None),                  # a project not in the seats file
    ("jak-inbox://work/lab/2?act=done", None),               # a query
    ("jak-inbox://work/lab/2#done", None),                   # a fragment
    ("jak-inbox://work/lab/2/done", None),                   # an extra segment
    ("jak-inbox://work/lab/%32", None),                      # an escape
    ("jak-inbox://work/lab/A-20260101-120000", None),        # a card id in a work link
    ("jak-inbox://card/A-20260101-120000", None),
    ("jak-inbox://work/Lab/2", None),
    ("jak-inbox://work/lab/2\n", None),
    (None, None),
]


def test_the_inbox_link_form_is_checked_in_the_page():
    got = run("report(" + json.dumps([u for u, _ in LINKS]) + ".map((u) => parseInboxLink(u, ['lab', 'orchard'])));")
    assert got == [want for _, want in LINKS]
    made = run("report([inboxLink('W-lab-2', ['lab']), inboxLink('W-lab-02', ['lab']), inboxLink('W-lab-1234567', ['lab']),"
               " inboxLink('W-lab-2', ['orchard']), inboxLink('A-20261020-101', ['lab'])]);")
    assert made == ["jak-inbox://work/lab/2", None, None, None, None]


ADDRESSES = [
    ("item/lab/2", "W-lab-2"),
    ("item/lab/02", None),            # a leading zero
    ("item/lab/1234567", None),       # 7 digits
    ("item/elsewhere/2", None),       # a project not in the seats file
    ("item/lab/2/done", None),        # an extra segment
    ("item/lab/2?x=1", None),         # a query
    ("item/lab/A-20261020-101", None),   # a card id
    ("lab/2", None),
    ("backlog", None),
]


def test_the_item_open_in_the_panel_is_in_the_address_and_checked(tmp_path):
    w, data = world(tmp_path)
    got = run(TEXTS + "const DATA = " + json.dumps(data) + ";\nconst SUBS = " + json.dumps([s for s, _ in ADDRESSES]) + ";\n" + """
S.place = "work"; S.sub = null; mount(); S.data.work = DATA; fill();
const opened = (sub) => { S.sub = sub; fill(); const p = byClass($("place"), "work-panel")[0]; return p ? texts(p)[0] : null; };
const shown = SUBS.map(opened);
S.sub = "backlog"; fill();
workSelect("W-lab-3");
const clicked = [S.sub, opened(S.sub)];
workSelect("W-lab-3");
const closed = [S.sub, byClass($("place"), "work-panel").length];
report({ shown, parsed: SUBS.map((s) => parseItemAddress(s, DATA.known_projects)), clicked, closed,
  made: [itemAddress("W-lab-3", ["lab"]), itemAddress("W-lab-03", ["lab"]), itemAddress("W-lab-3", ["orchard"])] });
""")
    assert got["parsed"] == [want for _, want in ADDRESSES]
    assert got["shown"] == ["p.label: W-lab-2"] + [None] * (len(ADDRESSES) - 1)   # must refuse: nothing else opens
    assert got["clicked"] == ["item/lab/3", "p.label: W-lab-3"]                   # a click puts the item in the address
    assert got["closed"] == ["backlog", 0]                                         # and closing gives the view back
    assert got["made"] == ["item/lab/3", None, None]


EVERY_VIEW = """
const shots = [];
const shot = (what) => shots.push([what, $("bar-place").textContent + "\\n" + $("place").textContent]);
S.place = "work"; S.sub = null; mount(); S.data.work = DATA; fill(); shot("board");
for (const d of $("place").all((e) => e.tagName === "DETAILS")) d.open = true;
shot("board, every fold open");
S.sub = "backlog"; fill(); shot("backlog");
S.sub = "estate"; fill(); shot("estate");
S.sub = null; fill();
for (const i of DATA.items || []) { S.sub = null; fill(); workSelect(i.id); shot("panel " + i.id); }
report(shots);
"""
WORD_NULL = re.compile(r"\b(?:null|undefined|NaN)\b")


def test_no_work_view_shows_null_or_undefined_as_text(tmp_path):
    empty = json.loads(json.dumps(place(tmp_path / "empty")))
    _, data = world(tmp_path / "world")
    for d in (empty, data):
        shots = run(TEXTS + "const DATA = " + json.dumps(d) + ";\n" + EVERY_VIEW)
        assert len(shots) == 4 + len(d["items"])
        assert [(what, WORD_NULL.findall(text)) for what, text in shots if WORD_NULL.search(text)] == []
    # must refuse: the same scan sees a null set as text beside the board
    planted = run(TEXTS + "const DATA = " + json.dumps(empty) + ";\n"
                  "S.place = 'work'; S.sub = null; mount(); S.data.work = DATA; fill(); WK.body.append(String(null));"
                  "report($('place').textContent);")
    assert WORD_NULL.search(planted)


def test_one_fact_has_one_badge_on_every_card(tmp_path):
    w, data = world(tmp_path)
    got = run(TEXTS + "const DATA = " + json.dumps(data) + ";\n" + """
S.place = "work"; S.sub = null; mount(); S.data.work = DATA; fill();
for (const d of $("place").all((e) => e.tagName === "DETAILS")) d.open = true;
report($("place").all((e) => e.classList.contains("witem")).map((b) => [b.getAttribute("data-k"),
  b.all((e) => e.classList.contains("chip")).map((c) => c.textContent)]));
""")
    assert got
    repeated = [(k, chips) for k, chips in got if len(chips) != len(set(chips))]
    assert repeated == []
    unowned = [chips for k, chips in got if k == "wi:" + w.ids["claimed"]]
    assert unowned and all(chips.count("no owner") == 1 for chips in unowned)


WORK_FILES = ("work.js", "workboard.js", "workitem.js")


def test_the_work_modules_set_no_style_and_parse_no_markup():
    folder = PAGE.parent
    style = re.compile(r"""\bstyle\s*:|\.style\b|setAttribute\(\s*["']style|cssText""")
    sinks = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|DOMParser|eval\(|new Function")
    for name in WORK_FILES:
        text = (folder / name).read_text(encoding="utf-8")
        assert not style.search(text) and not sinks.search(text), name
        assert text.count("\n") <= 350, name
        assert not re.search(r"\bfetch\(|XMLHttpRequest|method:\s*\"POST", text), name   # the place only reads
    # must refuse: the same checks see a style attribute and a sink planted in a copy
    planted = (folder / "work.js").read_text(encoding="utf-8").replace('h("div", { class: "ask" }', 'h("div", { style: "x" }', 1)
    assert style.search(planted)
    assert sinks.search("el.innerHTML = x")


def test_an_epic_under_an_epic_is_drawn_inside_it_and_counted(tmp_path):   # review round 3 (G6), finding 26
    from work_kit import bound, person
    from work_world import writer
    w = writer(tmp_path)
    mk = lambda **kw: w.write(bound("Alder"), "create", {"project": "lab", **kw})["id"]
    outer = mk(title="Outer", kind="epic")
    inner = mk(title="Inner", kind="epic", epic=outer)
    leaf = mk(title="Leaf", epic=inner)
    lone = mk(title="Lone epic", kind="epic")
    person(w, outer, "park")                         # an epic that is not open is still drawn when it holds open work
    data = json.loads(json.dumps(place(tmp_path)))
    got = run(TEXTS + "const DATA = " + json.dumps(data) + ";\n" + """
S.place = "work"; S.sub = "backlog"; mount(); S.data.work = DATA; fill();
const boxes = WK.body.all((e) => e.tagName === "DETAILS");
report(boxes.map((b) => [b.all((e) => e.tagName === "SUMMARY")[0].textContent,
  b.all((e) => e.tagName === "DETAILS").map((d) => d.all((e) => e.tagName === "SUMMARY")[0].textContent),
  b.all((e) => e.classList.contains("witem")).map((x) => x.getAttribute("data-k"))]));
""")
    by = {s.split(":")[0]: (s, inside, items) for s, inside, items in got}
    assert set(by) == {f"Epic {outer}", f"Epic {inner}", f"Epic {lone}"}
    s, inside, items = by[f"Epic {outer}"]
    assert "1 open item" in s and [x.split(":")[0] for x in inside] == [f"Epic {inner}"]
    assert "wi:" + leaf in items                                           # the leaf is inside the outer epic's box
    assert "1 open item" in by[f"Epic {inner}"][0] and "0 open items" in by[f"Epic {lone}"][0]   # must pass