// Prism: the home of the page (the Prism identity, chosen on I-20261103-133724). One message goes in; what it means
// comes out as labelled rays; and below it your five parts, the spectrum, each opening the place that holds it.
// The reading at the top is an illustration of HOW Semantext reads, drawn here from a few word patterns, and it says
// so: the reader itself works from your rules and, where you set one, a model. Nothing typed here is sent anywhere.
import { h } from "./dom.js";
import { plural } from "./words.js";
import { S } from "./app.js";

const SVG = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...kids) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined) node.append(kid instanceof Node ? kid : String(kid));
  return node;
}

// The mark: a beam in, the prism, three rays out (sky, amber, rose). Shared with the bar (index.html draws its own).
export function mark(size = 36) {
  return svg("svg", { width: size, height: Math.round(size * 0.7), viewBox: "0 0 40 28", "aria-hidden": "true", class: "prism-mark" },
    svg("path", { d: "M2 14H15", class: "ink" }), svg("path", { d: "M15 4L25 14L15 24Z", class: "ink glass" }),
    svg("path", { d: "M25 14L38 5", class: "ray-agents" }), svg("path", { d: "M25 14L38 14", class: "ray-record" }),
    svg("path", { d: "M25 14L38 23", class: "ray-waiting" }));
}

// The readings the illustration can show, each with its colour's part of the spectrum.
const KINDS = [
  { kind: "QUESTION", text: "It answers. Nothing changes.", ray: "agents", test: (t) => t.includes("?") },
  { kind: "SUGGESTION", text: "An option, never an order.", ray: "rules", test: (t) => /\b(maybe|could|we should|perhaps|i was thinking)\b/.test(t) },
  { kind: "TIME", text: "Kept word for word.", ray: "record", test: (t) => /\b(later|today|tonight|tomorrow|next week|for now|soon)\b/.test(t) },
  // Koinos P7: Semantext holds acts a gate catches, not words; a word here only says the act would need you.
  { kind: "YOUR WORD", text: "Would need your word: the act waits, not the words.", ray: "waiting",
    test: (t) => /\b(delete|publish|push|ship|send|buy|pay|deploy)\b/.test(t) },
];
export function readings(text) {
  const t = String(text || "").toLowerCase();
  const out = KINDS.filter((k) => k.test(t));
  return out.length ? out : [{ kind: "INSTRUCTION", text: "Done as asked, inside your rules.", ray: "plain" }];
}

const BANDS = [
  { key: "rules", name: "Rules", line: "What your agents are told, in your words", href: "#rules" },
  { key: "agents", name: "Agents", line: "Who is working, and the model on this machine", href: "#map/~agents" },
  { key: "work", name: "Work", line: "What is being done, project by project", href: "#work" },
  { key: "record", name: "Record", line: "What happened, and whether it helped", href: "#record" },
  { key: "waiting", name: "Waiting on you", line: "Only you decide these", href: "#waiting" },
];

const P = { draft: "Could we maybe ship the dark mode later?" };

function prism(rs) {
  const n = rs.length, gap = n > 1 ? Math.min(62, 220 / (n - 1)) : 0;
  const rays = rs.map((r, i) => {
    const y = Math.round(150 + (i - (n - 1) / 2) * gap);
    return svg("g", { class: "ray ray-" + r.ray + " i" + i },   // a class: the page allows nothing inline
      svg("path", { d: "M320 150 C 400 150, 430 " + y + ", 494 " + y, class: "ray-line" }),
      svg("circle", { cx: 500, cy: y, r: 5 }),
      svg("text", { x: 518, y: y - 7, class: "ray-kind" }, r.kind),
      svg("text", { x: 518, y: y + 14, class: "ray-text" }, r.text));
  });
  return svg("svg", { viewBox: "0 0 720 300", class: "prism-figure", role: "img",
    "aria-label": "Read as: " + rs.map((r) => r.kind.toLowerCase()).join(", ") },
  svg("path", { d: "M0 150 H250", class: "beam" }), svg("path", { d: "M250 80 L320 150 L250 220 Z", class: "glass" }), rays);
}

export function mount(el) {
  P.figure = h("div", { class: "prism-art" });
  // P4: no spell-check or autocomplete, so the browser's own helpers are not handed what is typed here either.
  const input = h("input", { id: "prism-msg", class: "prism-input", value: P.draft, "data-k": "prism:msg",
    "aria-label": "A message to your agents", spellcheck: "false", autocomplete: "off" });
  const draw = () => { P.draft = input.value; P.figure.replaceChildren(prism(readings(P.draft))); };
  const form = h("form", { class: "prism-form", on: { submit: (ev) => { ev.preventDefault(); draw(); } } },
    input, h("button", { type: "submit", class: "btn primary" }, "Read"));
  const presets = h("div", { class: "prism-presets" }, ["Could we maybe ship the dark mode later?", "Delete the old branch.",
    "Why is the build failing?"].map((t) => h("button", { type: "button", class: "chip", on: { click: () => { input.value = t; draw(); } } }, t)));
  P.bands = h("div", { class: "spectrum" });
  el.replaceChildren(
    h("section", { class: "prism-hero", "aria-label": "Read a message" },
      h("div", { class: "prism-words" },
        h("h1", { class: "prism-title" }, "One message.", h("br"), h("strong", null, "Everything it means.")),
        form, presets,
        h("p", { class: "prism-note" }, "An illustration of how Semantext reads. The reader itself works from your rules and, " +
          "where you set one, a model on your machine. Semantext sends nothing you type here.")),
      P.figure),
    h("section", { class: "prism-spectrum", "aria-label": "Your spectrum" },
      h("div", { class: "spectrum-head" }, h("h2", { class: "label" }, "Your spectrum"),
        h("span", { class: "meta" }, "every message passes through all five")),
      P.bands));
  draw();
  bands();   // drawn at once from the frame: the place's own read may be slow, and the bands do not wait for it
}

export function render(_data, el) {
  if (!P.bands || !el.contains(P.bands)) mount(el);
  else bands();
}

// Koinos P1: a count is shown only when a frame has said it. With none read yet the band says so ("…"), and when the
// last read failed the count it shows is marked as the last one known, never passed off as now.
function waitingCount() {
  if (!S.frame || typeof S.frame.waiting !== "number") return { text: "…", label: "not read yet", n: 0 };
  const n = S.frame.waiting;
  const stale = S.err ? " (last known)" : "";
  return { text: String(n) + (S.err ? "?" : ""), label: (n ? plural(n, "card") : "nothing") + stale, n };
}

function bands() {
  const w = waitingCount();
  P.bands.replaceChildren(...BANDS.map((b) => {
    const count = b.key === "waiting" ? w.text : null;
    return h("a", { class: "band band-" + b.key + (b.key === "waiting" && w.n ? " hot" : ""), href: b.href, "data-k": "band:" + b.key,
      "aria-label": b.name + (count !== null ? ", " + w.label : "") },
    h("span", { class: "band-name" }, h("span", { class: "swatch", "aria-hidden": "true" }), b.name),
    h("span", { class: "band-count mono" }, count === null ? "" : count),
    h("span", { class: "band-line" }, b.line),
    h("span", { class: "band-go", "aria-hidden": "true" }, "→"));
  }));
}
