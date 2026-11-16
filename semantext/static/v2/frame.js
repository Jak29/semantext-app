// The frame every place carries: the bar's counts and the gaming indicator, and the problems banner.
import { $, h } from "./dom.js";
import { cap, plural, when } from "./words.js";
import { disclosure } from "./parts.js";
import { keep, S } from "./app.js";
import { same } from "./selection.js";
import { outsidePlaces, renderOutsideTabs } from "./outside.js";

export const READER = { waiting: "Waiting", record: "Record", rules: "Rules", gates: "Gates", places: "Places", sources: "Sources", page: "This page" };

// Words are written only when they differ. Writing the same words again replaces the node that holds them, and the
// browser drops a selection that lived in a replaced node (the banner, "Checked", the bar's counts). A change goes
// through keep(), so a selection elsewhere is held through it.
export function setText(node, text) {
  if (node.textContent !== text) keep(() => { node.textContent = text; });
}

// ---------------------------------------------------------------- the frame: the bar, and the problems banner
export const mapKey = () => (S.frame && S.frame.word) || "map";

// The bar's plug-in tabs (D10): drawn again only when what they would show differs from what they show, and then through
// keep() with each tab carrying a key, so a focus or a selection on one goes back to it. Drawn on every read they were
// new nodes every ten seconds: the keyboard focus fell to the page and a selected tab name collapsed. The menus a
// person opens are left as they are while the list is the same (outside.js remembers the ones left open for a draw).
const tabsDrawn = new WeakMap();   // the tabs' element -> what it was last drawn from
const tag = (n, out) => {
  if (n.nodeType !== 1) return;
  if (n.getAttribute("data-place")) n.setAttribute("data-k", "outtab:" + n.getAttribute("data-place"));
  else if (n.tagName === "SUMMARY") n.setAttribute("data-k", "outmenu:" + (n.getAttribute("title") || ""));
  for (const c of n.childNodes) tag(c);
};
export function drawTabs(f, current) {
  const el = $("tabs-outside");
  const from = JSON.stringify([outsidePlaces(f), current]);
  if (tabsDrawn.get(el) === from) return;
  tabsDrawn.set(el, from);
  keep(() => { renderOutsideTabs(f, current); tag(el); });
}

export function applyFrame(f) {
  S.frame = f;
  const tab = $("tab-map");
  setText(tab, f.name || "Map");
  tab.href = "#" + mapKey();
  const n = f.waiting || 0;
  setText($("count-waiting"), n ? String(n) : "");
  $("tab-waiting").setAttribute("aria-label", n ? "Waiting, " + plural(n, "card") : "Waiting, nothing");
  drawTabs(f, S.place);
  renderGaming();
  renderProblems();
}

// The gaming indicator: what your inbox's "I'm gaming" button says, read from its flag as its gaming.py reads it. The
// page never writes the flag and never runs gaming.py. The hold lapses at its end time, between two reads too.
export function hhmm(ms) {
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? "?" : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}
export function gamingWords(g, nowMs) {
  if (!g) return null;
  if (g.state === "on") {
    if (typeof g.until_epoch !== "number" || !(nowMs < g.until_epoch * 1000)) return null;
    return { text: "Gaming hold until " + hhmm(g.until_epoch * 1000), cls: "gaming",
      title: "Your inbox's I'm gaming button is on" + (g.since ? " since " + when(g.since) : "") + ". This page only reads it." };
  }
  if (g.state === "unknown") return { text: "Gaming state unknown", cls: "gaming unknown", title: g.why || "The gaming flag could not be read." };
  return null;
}
// The compute monitor (sources/compute.py): what the machine shows beyond the button. It says something only when work
// should wait or a sign could not be read; a first reading with nothing wrong yet is not worth a word.
export function computeWords(c) {
  if (!c) return null;
  const why = (c.reasons || []).join("; ");
  const also = (c.not_read || []).length ? " Not read: " + c.not_read.join(", ") + "." : "";
  if (c.verdict === "hold") return { text: "Hold heavy work", cls: "gaming", title: why + "." + also + " This page only reads it." };
  if (c.verdict === "light") return { text: "Light work only", cls: "gaming", title: why + "." + also + " This page only reads it." };
  if (c.verdict === "unknown" && (c.could_not_tell || []).length) {
    return { text: "Compute state unknown", cls: "gaming unknown", title: c.could_not_tell.join("; ") + "." + also };
  }
  return null;
}
export function renderGaming() {
  const node = $("gaming");
  // A server started before the page learned to read the flag sends no gaming state: then nothing is said.
  const f = S.frame;
  const w = f ? (gamingWords(f.gaming, Date.now()) || computeWords(f.compute)) : null;
  node.hidden = !w;
  node.className = w ? w.cls : "gaming";
  setText(node, w ? w.text : "");
  const title = w ? w.title : "";
  if (node.title !== title) node.title = title;   // the readings in a reason reach the page here, and only here (D20)
}

// The problems: on Waiting the cards lead, so the bar shows a quiet count that opens the list on a click; in the other
// places the list stays folded to its first line above the place, always in sight and never in the way.
export function problemList() {
  const list = ((S.frame && S.frame.problems) || []).slice();
  if (S.err) list.unshift({ reader: "page", source: "", line: null, text: "The page could not read your files just now: " + S.err });
  return list;
}
export function renderProblems() {
  const box = $("problems");
  const list = problemList();
  const onWaiting = S.place === "waiting" || !S.place;
  const count = $("problems-count");
  count.hidden = !(onWaiting && list.length);
  setText(count, plural(list.length, "file problem"));
  count.setAttribute("aria-expanded", String(Boolean(S.problemsOpen && list.length)));
  box.hidden = list.length === 0 || (onWaiting && !S.problemsOpen);
  // The box is drawn again only when what it would hold differs from what it holds (a selection in it is then kept).
  const draw = (nodes) => { if (!same(box, nodes)) keep(() => box.replaceChildren(...nodes)); };
  if (!list.length) { draw([]); return; }
  // Each problem has its own key (D11): the path step of selection.js puts a selection back by the nearest keyed element,
  // and an unkeyed list let it land on the same characters in ANOTHER problem when the list shifted. A problem is its
  // reader, source, line and words; two alike are told apart by which of them it is, and a selection in a problem that
  // is gone, or whose words changed, has no key to go back to and is let go.
  // D19: the key is the JSON of [reader, source, line, words, which of the alike], so no two problems can share one: a
  // suffix joined to the words ("#2") collided with words that end in it, and a line of null and a line of 0 were one key.
  const seen = new Map();
  const item = (p) => {
    const id = JSON.stringify([p.reader ?? null, p.source ?? null, p.line ?? null, p.text || p.kind || null]);
    const n = (seen.get(id) || 0) + 1;
    seen.set(id, n);
    return h("li", { "data-k": "problem:" + JSON.stringify([id, n]) }, h("span", null, cap(p.text || p.kind || "a problem")),
      h("span", { class: "pwhere" }, [p.source || "", p.line ? "line " + p.line : ""].filter(Boolean).join(", ")
        + (READER[p.reader] ? (p.source ? " · " : "") + READER[p.reader] : "")));
  };
  const full = (into) => {
    into.push(h("ul", null, list.slice(0, 5).map(item)));
    if (list.length > 5) {
      const more = disclosure("problems:more", plural(list.length - 5, "more problem"));
      more.append(h("ul", null, list.slice(5).map(item)));
      into.push(more);
    }
  };
  if (onWaiting) {
    const nodes = [h("p", { class: "problems-title" }, "Something in your files needs fixing:")];
    full(nodes);
    draw(nodes);
  } else {
    const fold = disclosure("problems:show", h("span", null, h("span", { class: "problems-title" }, "Something in your files needs fixing: "),
      plural(list.length, "problem")), "problems-fold");
    const inside = [];
    full(inside);
    fold.append(...inside);
    draw([fold]);
  }
}
