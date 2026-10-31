// The frame every place carries: the bar's counts and the gaming indicator, and the problems banner.
import { $, h } from "./dom.js";
import { cap, plural, when } from "./words.js";
import { disclosure } from "./parts.js";
import { S } from "./app.js";
import { renderOutsideTabs } from "./outside.js";

export const READER = { waiting: "Waiting", record: "Record", rules: "Rules", gates: "Gates", places: "Places", sources: "Sources", page: "This page" };

// ---------------------------------------------------------------- the frame: the bar, and the problems banner
export const mapKey = () => (S.frame && S.frame.word) || "map";

export function applyFrame(f) {
  S.frame = f;
  const tab = $("tab-map");
  tab.textContent = f.name || "Map";
  tab.href = "#" + mapKey();
  const n = f.waiting || 0;
  $("count-waiting").textContent = n ? String(n) : "";
  $("tab-waiting").setAttribute("aria-label", n ? "Waiting, " + plural(n, "card") : "Waiting, nothing");
  renderOutsideTabs(f, S.place);
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
  node.textContent = w ? w.text : "";
  node.title = w ? w.title : "";
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
  count.textContent = plural(list.length, "file problem");
  count.setAttribute("aria-expanded", String(Boolean(S.problemsOpen && list.length)));
  box.hidden = list.length === 0 || (onWaiting && !S.problemsOpen);
  if (!list.length) { box.replaceChildren(); return; }
  const item = (p) => h("li", null, h("span", null, cap(p.text || p.kind || "a problem")),
    h("span", { class: "pwhere" }, [p.source || "", p.line ? "line " + p.line : ""].filter(Boolean).join(", ")
      + (READER[p.reader] ? (p.source ? " · " : "") + READER[p.reader] : "")));
  const full = (into) => {
    into.append(h("ul", null, list.slice(0, 5).map(item)));
    if (list.length > 5) {
      const more = disclosure("problems:more", plural(list.length - 5, "more problem"));
      more.append(h("ul", null, list.slice(5).map(item)));
      into.append(more);
    }
  };
  if (onWaiting) {
    const title = h("p", { class: "problems-title" }, "Something in your files needs fixing:");
    box.replaceChildren(title);
    full(box);
  } else {
    const fold = disclosure("problems:show", h("span", null, h("span", { class: "problems-title" }, "Something in your files needs fixing: "),
      plural(list.length, "problem")), "problems-fold");
    full(fold);
    box.replaceChildren(fold);
  }
}
