// The page: its shared state, its reads, moving between places, and the start. Each place is its own module.
import { $, h } from "./dom.js";
import { clock } from "./words.js";
import { applyFrame, drawTabs, renderProblems, setText } from "./frame.js";
import { closeDrawer, openDrawer, renderDrawer } from "./drawers.js";
import { findAgain, holdSelection, placeOf, settle, snapshot } from "./selection.js";
import * as waiting from "./waiting.js";
import { holdsRead } from "./proxyholds.js";
import * as projects from "./projects.js";
import * as documents from "./documents.js";
import * as diffmap from "./diffmap.js";
import * as map from "./map.js";
import * as record from "./record.js";
import * as work from "./work.js";
import * as plugins from "./plugins.js";
import * as prism from "./prism.js";
import { drawOutside, outsidePlace } from "./outside.js";
import { agentsPlace, leave, rulesPlace, settingsPlace, todayPlace } from "./ownplace.js";

// ---------------------------------------------------------------- the state of the page
export const S = {
  place: null, sub: null, mounted: null,
  data: {}, sig: {}, rev: 0, frame: null, err: null, busy: false,
  open: new Set(), q: { waiting: "", record: "" }, facet: "all", byProject: false, problemsOpen: false,
  drawer: null, opener: null,
  target: null,   // { place, key, focused }: the card or decision a link pointed at, marked until you go elsewhere
};

// Mark the element a link pointed at: on every drawing while you stay, and brought into view and focused once.
export function applyTarget(place, attr) {
  const t = S.target;
  if (!t || t.place !== place) return;
  const el = document.querySelector("[" + attr + '="' + CSS.escape(t.key) + '"]');
  if (!el) return;
  el.classList.add("target");
  if (!t.focused) { t.focused = true; S.moved = true; el.scrollIntoView({ block: "center" }); el.focus({ preventScroll: true }); }
}
// Today, Rules and Settings read their own data (ownplace.js); their route is only the frame.
export const ROUTE = { prism: "sources", today: "sources", rules: "sources", settings: "sources", waiting: "waiting", projects: "projects", documents: "documents", diffmap: "diffmap", map: "map", record: "record", work: "work", plugins: "plugins" };
export const DRAWER_ROUTE = { agent: "map", rules: "rules", gates: "projects", docs: "projects" };
// A built-in place's route, or a place a plug-in adds (the frame lists those): its route is its own name.
export const routeOf = (place) => (Object.hasOwn(ROUTE, place) ? ROUTE[place] : outsidePlace(S.frame, place) ? place : null);
// Whether a route has been read: an OWN property of S.data, never one a place inherits from Object by being named like it
// (a plug-in place named "constructor" was drawn from Object's own function before any data was read, and "0 items listed"
// stayed on the page when the read failed: D24). pagemodule and registry refuse such a name now; this is the page's own belt.
const read = (route) => route !== null && route !== undefined && Object.hasOwn(S.data, route) && Boolean(S.data[route]);

async function get(route) {
  const r = await fetch("/api/v2/" + route, { headers: { "X-Semantext": "1" }, cache: "no-store" });
  if (!r.ok) {
    let why = "the server answered " + r.status;
    try { why = (await r.json()).error || why; } catch (e) { /* the status says enough */ }
    throw new Error(why);
  }
  return r.json();
}

// The machine's own readings change at every look (compute.verdict() gives cpu_busy and memory_free on every call, held or
// not), and the page draws neither: what it shows of the machine is the verdict and its reasons, drawn by renderGaming()
// through setText, which writes only what differs. They are not the page's data, so a read that differs in them alone
// is not a change (D7): counting them made S.rev move at every read, and every node of every place was new at every
// periodic draw. A reading that crosses a line shows in the verdict and its reasons, which ARE counted. (Should a place
// ever show a reading itself, it must draw it through setText, and not count it here.)
// compute.py also writes the reading INTO a reason when it crosses a line ("the processor is 93% busy" at 90% or more, "only
// 7% of memory is free" under 10%), so above the line every 1% step changed a reason and counted as a change (D20). The
// numbers in a reason are compared as a bare "#%": that the reason is there still counts (a line crossed shows in the verdict
// and in the reasons), its number moving does not. The newest numbers are still drawn: applyFrame() runs first, and the
// bar's indicator writes its tooltip from S.frame.
// frame.rail (the six counts every answer carries, from the first release on) is the bar's own and is not a place's data
// either (D26, law L23): a read that differs in the rail alone is not a change of the place, so no S.rev bump, no draw, and no
// selection lost to one. The rail is still read: applyFrame() runs first on every answer, and the bar draws it from S.frame.
const VOLATILE = ["cpu_busy", "memory_free"];
const NUMBER = /\d+(?:\.\d+)?\s*%/g;
function steady(frame) {
  const f = Object.assign({}, frame, { checked: null });
  delete f.rail;
  if (f.compute && typeof f.compute === "object") {
    f.compute = Object.assign({}, f.compute);
    for (const k of VOLATILE) delete f.compute[k];
    if (Array.isArray(f.compute.reasons)) f.compute.reasons = f.compute.reasons.map((r) => String(r).replace(NUMBER, "#%"));
  }
  return f;
}

// A refresh that changed nothing changes nothing on the page: open sections, search text and scroll stay as they are.
function accept(route, data) {
  if (data && data.frame) applyFrame(data.frame);
  const copy = Object.assign({}, data, { frame: steady(data.frame) });
  const sig = JSON.stringify(copy);
  if (Object.hasOwn(S.sig, route) && S.sig[route] === sig) return false;   // own properties only: a place may be named like one of Object's (D24)
  S.sig[route] = sig;
  S.data[route] = data;
  S.rev++;   // the data the page is drawn from has changed: nodes drawn before it hold handlers made from the old (see keep)
  return true;
}

export async function load(route) {
  const changed = accept(route, await get(route));
  if (route === "waiting") holdsRead();   // what the proxy holds is read with Waiting, and never holds it up
  if (changed && S.place && routeOf(S.place) === route) fill();
  if (changed && S.drawer && DRAWER_ROUTE[S.drawer.kind] === route) renderDrawer(false);
  return changed;
}

async function refresh() {
  if (S.busy || !S.place) return;
  S.busy = true;
  try {
    await load(routeOf(S.place));
    if (S.drawer && DRAWER_ROUTE[S.drawer.kind] !== routeOf(S.place)) await load(DRAWER_ROUTE[S.drawer.kind]);
    S.err = null;
    setText($("checked"), "Checked " + clock());
  } catch (e) {
    S.err = String(e && e.message || e);
    setText($("checked"), "Could not check at " + clock());
  } finally {
    S.busy = false;
    renderProblems();
  }
}

// ---------------------------------------------------------------- moving between places
// The addresses the home page had still work.
// (Exported with ROUTE: registry.PAGE_NAMES must name every address the page answers at, and a test compares the two, D24.)
export const OLD = { live: "today", inbox: "waiting", decisions: "waiting", agents: "map/~agents", layers: "map/~gets", test: "rules/test", history: "today/history" };
function parseHash() {
  let raw = location.hash.replace(/^#/, "");
  try { raw = decodeURIComponent(raw); } catch (e) { /* a hash that is not encoding is read as it is */ }
  // A place a plug-in adds and the frame lists is reachable by its own name even when the home page used the name before
  // (live, inbox, decisions, agents, layers, test, history): the old address is a courtesy, the listed place is the tab's
  // own link. Limit: a plug-in named like a built-in place (prism, today, rules, settings, waiting, projects, documents,
  // diffmap, record, work, plugins, map) is still the built-in place; refusing such a name is for where plug-ins are listed.
  if (Object.hasOwn(OLD, raw) && !outsidePlace(S.frame, raw)) raw = OLD[raw];
  const cut = raw.indexOf("/");
  const head = cut < 0 ? raw : raw.slice(0, cut);
  const sub = cut < 0 ? null : raw.slice(cut + 1) || null;
  if (!head) return { place: null, bare: true, sub: null };
  if (head !== "map" && Object.hasOwn(ROUTE, head)) return { place: head, sub };   // every built-in place but the map (below), by ROUTE's own list
  if (head === "map" || (S.frame && S.frame.word && head === S.frame.word)) return { place: "map", sub };
  if (outsidePlace(S.frame, head)) return { place: head, sub };
  return { place: null, head, sub };
}

export async function route() {
  let r = parseHash();
  if (!r.place && !S.frame) {
    try { accept("sources", await get("sources")); } catch (e) { S.err = String(e.message || e); }
    r = parseHash();
  }
  // A bare address opens on Prism, the home (its Waiting band carries the count); a name it does not know, on Waiting.
  if (!r.place) r = { place: r.bare ? "prism" : "waiting", sub: null };
  const key = r.place + "/" + (r.sub || "");
  const moved = key !== S.mounted;
  S.place = r.place;
  S.sub = r.sub;
  if (moved && S.target && (S.target.place !== r.place || r.place === "record")) S.target = null;
  for (const a of document.querySelectorAll(".places a")) {
    if (a.dataset.place === r.place) {
      a.setAttribute("aria-current", "page");
      const row = a.parentNode;   // on a phone the places are one row that scrolls: the current one stays in sight
      if (row && row.scrollWidth > row.clientWidth) row.scrollLeft = a.offsetLeft - row.offsetLeft - 16;
    } else a.removeAttribute("aria-current");
  }
  if (S.frame) drawTabs(S.frame, r.place);
  $("main").className = r.place === "prism" || r.place === "projects" || r.place === "map" || r.place === "work" || r.place === "rules" || (r.place === "today" && r.sub) ? "wide" : "";
  const more = document.getElementById("places-more");   // a place picked from More closes it
  if (more) {
    more.open = false;
    // Koinos P6: on a place under More, More itself shows as where you are.
    const inBar = ["prism", "waiting", "work", "record", "rules"].includes(r.place);
    const summary = more.firstChild && more.firstChild.tagName === "SUMMARY" ? more.firstChild : more.querySelector("summary");
    if (summary) summary.className = inBar ? "" : "current";
  }
  if (moved) {
    // Leaving a place drops every draw still waiting there with the selection it held (close1 finding 4: a render that never
    // settled took the next place's draw over, and its words were selected on a place where the person selected nothing).
    for (const p of pending.values()) p.drop(p.token);
    pending.clear();
    S.mounted = key;
    mount();
    window.scrollTo(0, 0);
  }
  if (read(routeOf(S.place))) fill();
  try {
    await load(routeOf(S.place));
    S.err = null;
    setText($("checked"), "Checked " + clock());
  } catch (e) {
    S.err = String(e.message || e);
    if (!read(routeOf(S.place))) fill();
  }
  renderProblems();
}

// Each place is a module: render(data, el) draws it from its route's answer, and mount(el), where a place has one,
// makes the parts it keeps between drawings. A place a plug-in adds is drawn by its own page module (outside.js).
const PLACES = { prism, today: todayPlace, waiting, projects, documents, diffmap, map, record, work, rules: rulesPlace, plugins, settings: settingsPlace };
const placeNow = () => (S.place === "map" && S.sub && S.sub[0] === "~" ? agentsPlace : Object.hasOwn(PLACES, S.place) ? PLACES[S.place] : undefined);
export function mount() {
  leave();
  documents.leaveBox();   // a copy box shown for one document or spec is dropped when you go to another place (D12)
  $("place").replaceChildren();
  $("bar-place").replaceChildren();
  if (S.place === "map") $("bar-place").append(S.sub && S.sub[0] === "~" ? h("a", { href: "#map" }, "The map") : h("a", { href: "#map/~agents" }, "Agents"));
  if (placeNow() && placeNow().mount) placeNow().mount($("place"));
}
// Prism's bands and Today, Rules, Settings and Agents draw from reads of their own, which S.rev does not count; a draw of
// them is always the new nodes (keep, below).
const OWN_DATA = new Set([prism, todayPlace, rulesPlace, settingsPlace, agentsPlace]);
export function fill() {
  const own = placeNow();
  if (own) keep(() => own.render(S.data[ROUTE[S.place]], $("place")), OWN_DATA.has(own) ? null : $("place"));
  else if (outsidePlace(S.frame, S.place) && read(S.place)) keep(() => drawOutside(outsidePlace(S.frame, S.place), S.data[S.place], $("place")), $("place"), false);   // never settled (D16)
}

// Re-drawing keeps the scroll and, where it can, the focused control and what you have selected (a field's caret or
// range, or words on the page); only a link's target moves the page. Every re-draw that is not your own click goes
// through here: the refresh, a band's or a drawer's read, Today's counts and feed.
//
// Given a `region` (the element the draw fills), a draw that changes nothing replaces nothing (selection.js, settle):
// where the draw made new nodes that read the same as the old ones it took out, the old ones go back, so a selection or
// a focus in them was never disturbed. Only while S.rev has not moved since the region was last drawn here: a node keeps
// the handlers of the draw that made it, and a handler holds the data it was drawn from (an item's version, a card), so
// once the data has changed the nodes are the new ones. A region drawn from data S.rev does not count is not given.
const drawn = new WeakMap();   // region -> S.rev when it was last drawn through keep()
//
// A draw that finishes later (fn returns a promise: a plug-in's place, whose module draws after it is imported) is put
// back when it finishes, not before (D9): the selection and the focus are held through the wait and restored then, once
// the words are in the page; restoring at the start found an empty frame and let the selection go. A draw that is
// followed by a newer one on the same region, or by moving to another place, is not put back (the newer one holds its own).
const latest = new Map();   // region (or null) -> the newest draw that finishes later
const pending = new Map();  // region (or null) -> how to drop that draw's held selection, when a newer draw of the region starts
//
// What a late finish may take back is only what the DRAW took from the person, never what the person did while it waited:
//  - a selection: put back only if the person has not touched it since the draw's synchronous part (a click's caret, a
//    release, other words: D15), only if it lay wholly inside the region, and only if the words read the same (D14);
//  - a focus: only if it is on the page (the draw dropped it);
//  - the scroll: only if the person has not scrolled since the draw began waiting (D17).
// `settleIt` false for a plug-in place (D16): a module keeps the element it was given (`current = el`) and updates it later,
// so settle putting the OLD nodes back after the module drew sent its later updates to nodes that are out of the page.
// A plug-in's output is never settled: the page shows what the module drew last.
// keep() waits for the promise `fn` returns. drawOutside (outside.js) returns the one for the module's import AND for what
// the module's render() returns, so a module whose render() is async (draws after an await) is waited for too (D25).
// What the PAGE did while it waited is not the person's (D22): a selection the page itself left (the problems banner and
// "Checked HH:MM" are drawn in the same wait) is put back exactly or let go, and only a selection off the page's own chain
// is the person's (selection.js, holdText). A field the draw replaced is put back (D21). Limit: a draw that damages the
// selection only after it returns, and not through keep(), is read as the person's.
export function keep(fn, region, settleIt = true) {
  const y = window.scrollY;
  const a = document.activeElement;
  const where = placeOf(a);   // the focused control's key, and which of the elements sharing it it is
  let restore = holdSelection(a, region);   // a field's caret or range, or words selected on the page (selection.js)
  const scrolled = documents.holdScroll();   // a copy box's own scroll (a node put back, or made again, starts at the top)
  const snap = settleIt && region && drawn.get(region) === S.rev ? snapshot(region) : null;
  S.moved = false;
  const out = fn();
  if (region) drawn.set(region, S.rev);
  let ySync = y;   // where the page stood once the draw began waiting
  const finish = (late) => {
    if (snap) settle(region, snap);
    // After a wait the person may have moved on: a selection they made meanwhile, or a control they went to, is theirs and is
    // not taken back; only a selection the draw dropped (none left) or a focus it dropped (on the page) is put back.
    // A focus is given back only if the person has not acted since the draw took it (close1 finding 1: a click on the page's
    // words focuses nothing, and the focus was put back into the field they had left).
    const free = !late || ((!document.activeElement || document.activeElement === document.body) && !(restore.acted && restore.acted()));
    if (free && !document.contains(a)) {
      const again = (where && findAgain(where)) || restore.again(late);   // by its key, else (an unkeyed field, after a late draw) by where it stood
      if (again) again.focus({ preventScroll: true });
    } else if (free && snap && a && a !== document.body && document.contains(a) && document.activeElement !== a) a.focus({ preventScroll: true });
    restore(late);
    scrolled();
    const theirs = late && Math.abs(window.scrollY - ySync) > 1;
    if (!theirs && !S.moved && Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);
    S.moved = false;
  };
  if (out && typeof out.then === "function") {
    const token = {}, mounted = S.mounted, older = pending.get(region || null);
    latest.set(region || null, token);
    // The selection as the draw's synchronous part left it, taken before anything else of the page can touch it (D15, D22): a
    // later draw of the same region may take this one's held selection over, and then finishes with that one.
    restore = restore.mark(token) || restore;
    if (scrolled.mark) scrolled.mark();   // a box's scroll as the draw left it: a scroll after this is the person's (close1 finding 5)
    // The older draw of this region is dropped now, not when its promise settles (close1 finding 4: a render that never settles
    // kept its held words for the life of the page). After mark(), so a takeover (D22) has already made them this draw's.
    if (older) older.drop(older.token);
    pending.set(region || null, { token, drop: restore.drop });
    if (!S.moved && Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);   // the page does not jump while it waits
    ySync = window.scrollY;
    const later = () => { if (latest.get(region || null) === token && S.mounted === mounted) finish(true); else restore.drop(token); };
    return out.then(later, later);
  }
  finish();
  return out;
}

// ---------------------------------------------------------------- start
$("problems-count").addEventListener("click", () => {
  S.problemsOpen = !S.problemsOpen;
  renderProblems();
  if (S.problemsOpen) { window.scrollTo(0, 0); $("problems").focus({ preventScroll: true }); }
});
$("drawer-close").addEventListener("click", () => closeDrawer());
$("scrim").addEventListener("click", () => closeDrawer());
document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && S.drawer) { ev.preventDefault(); closeDrawer(); } });
$("skip").addEventListener("click", (ev) => { ev.preventDefault(); $("main").focus(); });
window.addEventListener("hashchange", () => { closeDrawer(true); route(); });
window.addEventListener("focus", () => refresh());
setInterval(refresh, 10000);

(async function start() {
  await route();
  // A drawer can be opened from the address: ?open=agent:<id or name>, rules, rules:<agent>, gates:<project id>, docs:<project id>.
  const open = new URLSearchParams(location.search).get("open");
  if (open) {
    const cut = open.indexOf(":");
    const kind = cut < 0 ? open : open.slice(0, cut);
    const arg = cut < 0 ? "" : open.slice(cut + 1);
    if (kind === "agent") openDrawer("agent", /^[0-9a-f]{10}$/.test(arg) ? { id: arg } : { name: arg });
    else if (kind === "rules") openDrawer("rules", arg ? { agent: arg } : {});
    else if (kind === "gates" || kind === "docs") openDrawer(kind, { project: arg });
  }
})();
