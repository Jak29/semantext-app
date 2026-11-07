// Prism: the home of the page (the Prism identity, chosen on I-20261103-133724). One message goes in; what it means
// comes out as labelled rays; and below it your five parts, the spectrum, each opening the place that holds it.
// The reading at the top is an illustration of HOW Semantext reads, drawn here from a few word patterns, and it says
// so: the reader itself works from your rules and, where you set one, a model. Nothing typed here is sent anywhere.
import { h } from "./dom.js";
import { newestFirst, plural } from "./words.js";
import { S, keep, load } from "./app.js";
import { cardNode } from "./cards.js";

// The Rules band only reads, so it does not import the Rules parts: they hold the one way to change rules, and no other
// place may reach it (test_one_page). Its reads are GETs, made here; the words for where a rule came from are the Rules
// place's own (its SOURCE), said again.
async function read(path) {
  const r = await fetch(path, { headers: { "X-Semantext": "1" }, cache: "no-store" });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const live = (es) => (es || []).filter((e) => !e.archived);
function source(e) {
  const p = e.provenance || {};
  return p.type === "LEARNED" ? "Your words" : p.type === "PROPOSED" ? "Proposed by " + (p.by || "an agent") + ", added by you"
    : p.type === "SUGGESTED" ? "Suggested" + (p.pack ? ": " + p.pack : "") : p.type === "SETTING" ? "A switch"
    : p.type === "DEFAULT" ? "Came with Semantext" : "Hand-written: its file records no provenance, so who wrote it is not known";
}

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

// open: the band opened in place (APP-DESIGN depth 2), or null. Waiting and Rules open in place (build step 2); the
// other bands still go to their place. rules: the Rules band's own read, and the rule picked to show beside the list.
const P = { draft: "Could we maybe ship the dark mode later?", open: null, reading: false, readErr: null,
  rules: { data: null, err: null, reading: false, at: 0, pick: null } };
const IN_PLACE = new Set(["rules", "waiting"]);
export { P as PRISM };   // the tests set a band's read as a read would; fetch answers never in node

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
  // Koinos C5: Escape closes the open band and gives focus back to its button (a drawer, when one is open, goes first).
  // On the document, once: a redraw replaces the button, so focus is not always inside the bands when Escape comes.
  if (!P.escape) {
    P.escape = true;
    document.addEventListener("keydown", onKey);
    // An open band reads again every ten seconds, whether or not the frame's count changed (Koinos: a swapped card
    // stayed unseen while the count stood still).
    setInterval(() => { if (P.open && S.place === "prism") { P.rules.at = 0; readOpen(); } }, 10000);
  }
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
  if (P.open && !IN_PLACE.has(P.open)) P.open = null;
  readOpen();
  P.bands.replaceChildren(...BANDS.map((b) => {
    const count = b.key === "waiting" ? w.text : null;
    const cls = "band band-" + b.key + (b.key === "waiting" && w.n ? " hot" : "");
    const label = b.name + (count !== null ? ", " + w.label : "");
    const parts = [h("span", { class: "band-name" }, h("span", { class: "swatch", "aria-hidden": "true" }), b.name),
      h("span", { class: "band-count mono" }, count === null ? "" : count),
      h("span", { class: "band-line" }, b.line)];
    if (!IN_PLACE.has(b.key)) {
      return h("a", { class: cls, href: b.href, "data-k": "band:" + b.key, "aria-label": label },
        ...parts, h("span", { class: "band-go", "aria-hidden": "true" }, "→"));
    }
    // A band that opens in place: a button under a heading (Koinos C3), its panel straight after it.
    const open = P.open === b.key, panel = "band-panel-" + b.key;
    const button = h("button", { type: "button", class: cls + (open ? " open" : ""), "data-k": "band:" + b.key,
      "aria-expanded": String(open), "aria-controls": panel, "aria-label": label,
      on: { click: () => toggle(b.key) } },
    ...parts, h("span", { class: "band-go", "aria-hidden": "true" }, open ? "−" : "+"));
    const body = h("div", { id: panel, class: "band-panel", role: "region", hidden: !open, "aria-label": b.name }, open ? panelFor(b) : null);
    if (open) P.panel = body;   // the open band's panel, redrawn in place when its read lands or a rule is picked
    return h("section", { class: "band-wrap" }, h("h2", { class: "band-head" }, button), body);
  }));
}

// Escape closes the open band. Koinos E1: the drawer's own Escape runs first and clears S.drawer, so a key it has
// already used (defaultPrevented) must not close the band as well.
export function onKey(ev) {
  if (ev.defaultPrevented || ev.key !== "Escape" || !P.open || S.drawer || S.place !== "prism") return;
  ev.preventDefault();
  toggle(P.open);
}
function readOpen() {
  if (P.open === "waiting") readWaiting();
  if (P.open === "rules") readRules();
}

// Open or close a band in place; the redraw makes a new button, and focus stays on it (Koinos A5).
function toggle(key) {
  P.open = P.open === key ? null : key;
  bands();
  const b = P.bands.querySelector('[data-k="band:' + key + '"]');
  if (b) b.focus();
}

// The Waiting band's own read: the place's route, fetched while the band is open, so its cards are now and not the
// frame's count. One read at a time; a failure is said in the band, never shown as an empty list (Koinos D1).
function readWaiting() {
  if (P.reading) return;
  P.reading = true;
  load("waiting").then(() => { P.readErr = null; }, (e) => { P.readErr = String(e && e.message || e); })
    .finally(() => { P.reading = false; if (P.bands && document.contains(P.bands)) redrawPanel(); });
}
function redrawPanel() {
  const key = P.open;
  // Koinos F1: in keep(), so the focused control (a rule row, a card's words box) and its caret survive the redraw.
  if (key && P.panel && P.bands.contains(P.panel)) keep(() => P.panel.replaceChildren(panelFor(BANDS.find((b) => b.key === key))));
}

// The Rules band's own read: the same reads the Rules place makes (the active setup, its rules, the shared ones and each
// agent's own), at most every ten seconds while the band is open. It only reads; every change is made in Rules.
function readRules() {
  const R = P.rules;
  if (R.reading || (R.data && Date.now() - R.at < 10000)) return;
  R.reading = true;
  (async () => {
    const state = await read("/api/state");
    const [profile, base, agents] = await Promise.all([read("/api/profile?name=" + encodeURIComponent(state.active)),
      read("/api/profile?name=base"), read("/api/agents")]);
    R.data = { env: (profile.environment && profile.environment.title) || state.active, own: live(profile.entries),
      agents: (agents.agents || []).filter((a) => (a.rules || []).length).map((a) => ({ name: a.name, rules: live(a.rules) })),
      base: live(base.entries), tests: profile.tests || [] };
    R.err = null;
  })().catch((e) => { R.err = String(e && e.message || e); })
    .finally(() => { R.reading = false; R.at = Date.now(); if (P.bands && document.contains(P.bands)) redrawPanel(); });
}

function panelFor(b) {
  return b.key === "rules" ? rulesPanel(b) : waitingPanel(b);
}

function rulesPanel(b) {
  const R = P.rules, all = h("a", { class: "band-all", href: b.href }, "Switch, edit or add rules in Rules →");
  if (!R.data) return h("div", { class: "band-body" }, h("p", { class: "band-state", role: "status" }, R.err ? "Could not read your rules: " + R.err + "." : "Reading your rules…"), all);
  const stale = R.err ? h("p", { class: "band-state warn", role: "status" }, "Could not check just now (" + R.err + "); these are the rules last read.") : null;
  const groups = [["In " + R.data.env, R.data.own], ...R.data.agents.map((a) => [a.name + " only", a.rules]), ["Everywhere", R.data.base]]
    .filter(([, rules]) => rules.length);
  const every = groups.flatMap(([, rules]) => rules);
  const picked = every.find((e) => e.id === R.pick) || null;
  const pick = (id) => { R.pick = R.pick === id ? null : id; redrawPanel(); };
  const list = h("div", { class: "rule-list" }, groups.length ? groups.map(([title, rules]) => h("div", { class: "rule-group" },
    h("h3", { class: "label" }, title + " · " + plural(rules.length, "rule")),
    h("ul", { class: "rule-rows" }, rules.map((e) => h("li", null, h("button", { type: "button", class: "rule-row" + (e.enabled === false ? " off" : ""),
      "data-k": "rule:" + e.id, "aria-current": picked === e ? "true" : null, "aria-controls": picked ? "rule-detail" : null,
      on: { click: () => pick(e.id) } },
    h("span", { class: "rule-st" }, e.statement), e.enabled === false ? h("span", { class: "chip" }, "off") : null))))))
    : h("p", { class: "band-state" }, "No rules yet."));
  const detail = picked ? ruleBeside(picked, R.data.tests) : null;
  return h("div", { class: "band-body" }, stale, h("div", { class: "band-split" }, list, detail), all);
}

// Depth 3: one rule beside the list, in its words, with where it came from and the tests behind it. No switch here:
// the band shows; Rules changes (the switch, edit and remove are there, one link away).
function ruleBeside(e, tests) {
  const p = e.provenance || {}, kept = tests.filter((t) => (t.rules || []).includes(e.id));
  const fact = (k, v) => v ? h("div", { class: "fact" }, h("span", { class: "k" }, k), h("span", { class: "v" }, v)) : null;
  return h("aside", { id: "rule-detail", class: "rule-beside", "aria-label": "The rule: " + String(e.statement).slice(0, 80) },
    h("p", { class: "rule-big" }, e.statement),
    fact("State", e.enabled === false ? "Off: on no card" : "On"),
    fact("When", e.always ? "always, on every card" : e.applies_when || "whenever it fits"),
    fact("From", source(e)),
    p.type === "LEARNED" && p.words && p.words.trim() !== String(e.statement).trim() ? fact("Your words", "“" + p.words + "”") : null,
    fact("Tests", kept.length ? plural(kept.length, "test") + ", from your corrections" : "none yet"));
}

function waitingPanel(b) {
  const all = h("a", { class: "band-all", href: b.href }, "All of " + b.name + ", with what is parked and done →");
  const data = S.data.waiting;
  if (!data) {
    return h("div", { class: "band-body" }, h("p", { class: "band-state", role: "status" }, P.readErr ? "Could not read your cards: " + P.readErr + "." : "Reading your cards…"), all);
  }
  // Koinos W1: the band's count is the frame's, which adds this machine's own inbox; so the panel draws those cards
  // too, apart and under their own heading, as the Waiting place does.
  const machine = newestFirst(data.machine_inbox || []).filter((c) => c.state === "waiting");
  const own = machine.length ? h("section", { "aria-label": "This machine's own inbox" },
    h("h3", { class: "label" }, "This machine's own inbox · " + machine.length + " waiting"),
    h("div", { class: "cards" }, machine.map(cardNode))) : null;
  const stale = P.readErr ? h("p", { class: "band-state warn", role: "status" }, "Could not check just now (" + P.readErr + "); these are the cards last read.") : null;
  if (data.off) return h("div", { class: "band-body" }, stale, h("p", { class: "band-state" }, "Waiting is off: your sources file names no place for cards."), own, all);
  const waiting = newestFirst(data.cards || []).filter((c) => c.state === "waiting");
  const list = waiting.length ? h("div", { class: "cards" }, waiting.map(cardNode))
    : h("p", { class: "band-state" }, machine.length ? "Nothing else is waiting for you." : "Nothing is waiting for you.");
  return h("div", { class: "band-body" }, stale, list, own, all);
}
