// The parts of the page that came from the home page (Today, Rules, Agents, Settings): the helpers and the state they
// share, and the one module of the page's own that changes your rules and settings (see OWN_ROUTES in the tests).
import { toast } from "./cards.js";
export { toast };

// Every element is built with createElement and textContent: rule text is user-editable, so nothing is parsed as HTML.
export const $ = (id) => document.getElementById(id);
export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v; else el.setAttribute(k, String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
// flat(Infinity): a list of lists must never reach replaceChildren as an array (it would become "[object ...]" text).
// A part of another view is simply not there: filling it is a no-op, never an error.
export const fill = (el, nodes) => { const t = typeof el === "string" ? $(el) : el; if (t) t.replaceChildren(...[nodes].flat(Infinity).filter(Boolean)); };
// The only changes these parts make: your rules, agents and settings. Answers, parks and plug-ins have their own modules.
const OWN_ROUTES = new Set(["/api/active", "/api/toggle", "/api/learn", "/api/agent-bind", "/api/agent-unbind", "/api/agent-name", "/api/undo",
  "/api/undo-last", "/api/feature", "/api/source", "/api/explain", "/api/setting", "/api/create", "/api/add-suggestions"]);
// Every call names this page with its own header: the server answers changes, and the feed, only to the page itself.
export async function api(path, body) {
  if (body && !OWN_ROUTES.has(path)) throw new Error(path + " is not a change this part of the page makes");
  const r = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json", "X-Semantext": "1" }, body: JSON.stringify(body) }
                                   : { headers: { "X-Semantext": "1" } });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
export const enc = encodeURIComponent;
export async function act(path, body, done) { try { const r = await api(path, body); if (done) toast(done); await load(); render(); return r; } catch (e) { toast(e.message); return null; } }
export const still = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
export const live = (es) => (es || []).filter(e => !e.archived);
export const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + "s")}`;
export const fmt = (n) => Number(n || 0).toLocaleString("en");
export const when = (at) => { const d = new Date(String(at || "").replace(/(\.\d{3})\d+/, "$1")); return isNaN(d) ? null : d; };
export function ago(at) {
  const d = when(at); if (!d) return "";
  const s = Math.max(0, (Date.now() - d) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) { const n = Math.round(s / 86400); return n === 1 ? "a day ago" : `${n} days ago`; }
  return d.toLocaleDateString([], { day: "numeric", month: "short" });
}
export const clock = (at) => { const d = when(at); return d ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""; };
// The canvases take their colours from the page's own tokens, so they follow the theme like everything else.
const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function rgbOf(name) {
  const v = token(name), m = v.match(/^#([0-9a-f]{6})$/i);
  if (m) { const n = parseInt(m[1], 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; }
  const p = v.match(/\d+(\.\d+)?/g);
  return p ? p.slice(0, 3).map(Number) : [128, 128, 128];
}
export const rgba = (k, a) => `rgba(${k[0]},${k[1]},${k[2]},${Math.max(0, Math.min(1, a))})`;
export const palette = () => ({ text: rgbOf("--text"), t2: rgbOf("--text-2"), t3: rgbOf("--text-3"), line: rgbOf("--line-2"),
  accent: rgbOf("--accent"), danger: rgbOf("--danger"), surface: rgbOf("--surface") });

export const S = { view: "today", state: null, base: null, profile: null, agents: [], inbox: { open: [], recent: [] },
  feed: { on: true, limit: 9500, records: [] }, layers: { agent: "", form: "full", card: null }, test: null,
  agentOpen: null, ideasOpen: false, metrics: null, register: { q: "", items: null }, expanded: null, ruleOpen: null,
  testAgent: "" };

export const WORDS = { own: "Your words", agent: "Passed on by another agent", tool: "A tool's notice" };
export const HOW = { bound: "bound by you", observed: "seen by its tool and folder", claimed: "claimed by its shell", fallback: "unnamed" };
const BASIS = { text: "told by how it opens", transcript: "told by the tool's own record", none: "nothing marked it otherwise", error: "it could not be read, so the short card went", page: "chosen in the test" };

export const envTitle = (name) => ((S.state && S.state.profiles.find(p => p.name === name)) || {}).title || name || "";
const normName = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9@._-]+/g, "-").replace(/^[-._]+|[-._]+$/g, "");
// A relayed message can name any sender, you included: such a claim is flagged, and never decides whose words they are.
export const claimsYou = (name) => !!name && ((S.state && S.state.you) || []).includes(normName(name));
export const label = (name) => { const a = S.agents.find(x => x.name === name); return name === "ai" ? "An unnamed agent" : (a && a.label) || name; };

function showProblems(lines) {
  const el = $("problem");
  if (!el) return;
  el.hidden = !lines.length;
  fill(el, lines.length ? [...lines.map(t => h("p", {}, t)),
    h("p", { class: "meta" }, "Fix the line it names, or run `semantext undo --last` to restore the last saved version. Your AI still gets the base rules meanwhile.")] : []);
}
export async function load() {
  S.state = await api("/api/state");
  showProblems((S.state.problems || []).map(p => p.problem));
  const name = S.state.active;
  const [profile, base, agents] = await Promise.all([
    api("/api/profile?name=" + enc(name)).catch(() => ({ environment: { id: name, title: name }, entries: [] })),
    api("/api/profile?name=base").catch(() => ({ environment: { id: "base", title: "Base" }, entries: [] })),
    api("/api/agents").catch(() => ({ agents: [] }))]);
  S.profile = profile; S.base = base; S.agents = agents.agents || [];
  layoutSpace();
}
export async function loadInbox() {
  try { S.inbox = await api("/api/inbox"); } catch (e) { S.inbox = { open: [], recent: [] }; }
  layoutSpace();
  hooks.inbox();
}
export async function loadMetrics() {
  try { S.metrics = await api("/api/metrics"); } catch (e) { /* the page works without the counts */ }
  hooks.metrics();
}
export async function pollFeed() {
  let fresh = null;
  try {
    const f = await api("/api/feed?n=200");
    const had = S.feed.records[0], newest = f.records[0], first = !S.feedLoaded;
    S.feed = f; S.feedLoaded = true;
    if (!had || !newest || newest.at !== had.at) layoutSpace();
    if (!first && newest && (!had || newest.at !== had.at)) fresh = newest;
  } catch (e) { /* the page works without the feed */ }
  if (!fresh) return;
  // Something real happened: the counts, the lines and the picture move, and only then.
  loadMetrics();
  hooks.fresh(fresh);
}

// ---------------------------------------------------------------- one delivery, and the five steps it passed through
export function fromRecord(r) { return { ...r, example: false }; }
export function fromTest(r, message, example) {
  const a = S.agents.find(x => x.name === r.agent);
  const how = !r.agent ? "fallback" : a && a.folders.length ? "bound" : a && a.sessions.length && a.sessions.every(s => s.how === "claimed") ? "claimed" : "observed";
  return { at: new Date().toISOString(), agent: r.agent || "ai", how, tool: "", words: r.words, from: r.from || "", basis: r.basis, environment: r.environment,
    form: r.form, layers: r.layers, bytes: r.bytes, left_out: r.left_out, answers: r.answers, waiting: r.waiting, problem: r.problem,
    reading: r.reading, text: r.text, message, example };
}
export const count = (d, l) => d.layers.filter(x => x.layer === l).reduce((n, x) => n + x.ids.length, 0);
function stages(d) {
  const counts = { base: count(d, "base"), environment: count(d, "environment"), agent: count(d, "agent") };
  const total = counts.base + counts.environment + counts.agent;
  const pct = Math.min(100, Math.round(100 * d.bytes / (S.feed.limit || 9500)));
  const agent = label(d.agent);
  return [
    { caps: "Who asked", v: agent, s: HOW[d.how] || d.how,
      why: d.how === "bound" ? `You bound its folder to ${agent}, so every agent working there is ${agent}.`
        : d.how === "observed" ? `Semantext saw ${d.tool || "its tool"} working in this project, so it needed no name.`
        : d.how === "claimed" ? `Its shell says it is ${agent}. A claim gets the shared rules only, until you bind it.`
        : "Nothing named it, so it is read as an unnamed agent and gets the shared rules." },
    { caps: "Whose words", v: WORDS[d.words], s: BASIS[d.basis] || "",
      why: d.words === "own" ? (d.basis === "transcript" ? "The tool's own record says you typed it." : "Nothing marks it as relayed, so it counts as yours: the safe side, since your full card holds every rule.")
        : d.words === "agent" ? "Another agent's message is information, never your word."
          + (claimsYou(d.from) ? ` It names its sender as "${d.from}", as if it were you; the name decides nothing.` : d.from ? ` It names its sender as ${label(d.from)}: a claim.` : "")
        : "A tool's notice is information, never your word." },
    { caps: "Which rules", v: d.form === "full" ? "All your rules" : "Only the safety rules", s: envTitle(d.environment),
      why: d.form === "full" ? "Your own words get all your rules: the shared ones, this environment's, and the agent's own."
        : "Words that are not yours get only the safety rules, so no one else can speak with your authority." },
    { caps: "Layers", v: plural(total, "rule"), s: `${counts.base} everywhere · ${counts.environment} environment · ${counts.agent} agent`,
      why: d.left_out ? `${plural(d.left_out, "rule")} did not fit the size limit; your AI is told how many.`
        : counts.agent ? `${agent} also gets ${plural(counts.agent, "rule")} of its own, after the shared ones, which they never override.`
        : "Every layer it is entitled to, whole." },
    { caps: "Sent", v: `${fmt(d.bytes)} bytes`, s: `${pct}% of the limit`,
      why: d.answers.length ? `With your answer${d.answers.length > 1 ? "s" : ""} to #${d.answers.join(", #")}, for ${agent} alone.`
        : d.waiting.length ? `${plural(d.waiting.length, "request")} from ${agent} ${d.waiting.length === 1 ? "waits" : "wait"} for your answer; it is told not to act on ${d.waiting.length === 1 ? "it" : "them"} yet.`
        : "Added to the prompt before your AI reads a word of it." },
  ];
}
// The steps open only when asked for: a line of what happened, then why, in the small size.
export function stepsView(d) {
  return h("dl", { class: "steps" }, stages(d).map(s => [h("dt", { class: "label" }, s.caps),
    h("dd", {}, h("div", {}, s.v, s.s ? h("span", { class: "meta" }, "  ·  " + s.s) : null), h("div", { class: "meta" }, s.why))]));
}

export const RULE_FOR = { question: "base.question-not-instruction", suggestion: "base.suggest-not-require", yes: "base.yes-binds-to-offer",
  pause: "base.parked-stays-parked", time: "base.time-kept-verbatim", correction: "base.corrections-become-rules",
  instruction: "base.show-your-work", "needs-word": "base.irreversible-needs-your-word" };
export const back = (view, name) => h("button", { class: "link back meta", type: "button", "data-view": view }, "‹ " + name);
export function copyBtn(cmd) { return h("button", { class: "btn small", type: "button", "data-copy": cmd, title: cmd }, "Copy the command"); }

// Filled in by ownplace.js: the views, and what each does when new data arrives. Kept here so the parts need no cycle.
export const VIEWS = {}, AFTER = {};
export const hooks = { inbox() {}, metrics() {}, fresh() {}, leave() {}, layout() {} };
const layoutSpace = () => hooks.layout();
export const host = { el: null };

export function render() {
  if (!host.el || !VIEWS[S.view]) return;
  fill(host.el, VIEWS[S.view]());
  if (AFTER[S.view]) AFTER[S.view]();
}
// Where each view lives on the page. A view that came from Decisions is now in Waiting and Record.
export const ADDRESS = { today: "today", history: "today/history", rules: "rules", test: "rules/test", agents: "map/~agents",
  layers: "map/~gets", settings: "settings", decisions: "waiting" };
export function go(view) { location.hash = "#" + (ADDRESS[view] || "today"); }

