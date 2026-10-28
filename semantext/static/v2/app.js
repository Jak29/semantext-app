// The page: its shared state, its reads, moving between places, and the start. Each place is its own module.
import { $ } from "./dom.js";
import { clock } from "./words.js";
import { applyFrame, renderProblems } from "./frame.js";
import { closeDrawer, openDrawer, renderDrawer } from "./drawers.js";
import * as waiting from "./waiting.js";
import * as projects from "./projects.js";
import * as documents from "./documents.js";
import * as map from "./map.js";
import * as record from "./record.js";
import * as work from "./work.js";
import { drawOutside, outsidePlace, renderOutsideTabs } from "./outside.js";

// ---------------------------------------------------------------- the state of the page
export const S = {
  place: null, sub: null, mounted: null,
  data: {}, sig: {}, frame: null, err: null, busy: false,
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
export const ROUTE = { waiting: "waiting", projects: "projects", documents: "documents", map: "map", record: "record", work: "work" };
export const DRAWER_ROUTE = { agent: "map", rules: "rules", gates: "projects", docs: "projects" };
// A built-in place's route, or a place a plug-in adds (the frame lists those): its route is its own name.
export const routeOf = (place) => ROUTE[place] || (outsidePlace(S.frame, place) ? place : null);

async function get(route) {
  const r = await fetch("/api/v2/" + route, { headers: { "X-Semantext": "1" }, cache: "no-store" });
  if (!r.ok) {
    let why = "the server answered " + r.status;
    try { why = (await r.json()).error || why; } catch (e) { /* the status says enough */ }
    throw new Error(why);
  }
  return r.json();
}

// A refresh that changed nothing changes nothing on the page: open sections, search text and scroll stay as they are.
function accept(route, data) {
  if (data && data.frame) applyFrame(data.frame);
  const copy = Object.assign({}, data, { frame: Object.assign({}, data.frame, { checked: null }) });
  const sig = JSON.stringify(copy);
  if (S.sig[route] === sig) return false;
  S.sig[route] = sig;
  S.data[route] = data;
  return true;
}

export async function load(route) {
  const changed = accept(route, await get(route));
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
    $("checked").textContent = "Checked " + clock();
  } catch (e) {
    S.err = String(e && e.message || e);
    $("checked").textContent = "Could not check at " + clock();
  } finally {
    S.busy = false;
    renderProblems();
  }
}

// ---------------------------------------------------------------- moving between places
function parseHash() {
  let raw = location.hash.replace(/^#/, "");
  try { raw = decodeURIComponent(raw); } catch (e) { /* a hash that is not encoding is read as it is */ }
  const cut = raw.indexOf("/");
  const head = cut < 0 ? raw : raw.slice(0, cut);
  const sub = cut < 0 ? null : raw.slice(cut + 1) || null;
  if (!head) return { place: "waiting", sub: null };
  if (head === "waiting" || head === "projects" || head === "documents" || head === "record" || head === "work") return { place: head, sub };
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
  if (!r.place) r = { place: "waiting", sub: null };
  const key = r.place + "/" + (r.sub || "");
  const moved = key !== S.mounted;
  S.place = r.place;
  S.sub = r.sub;
  if (moved && S.target && (S.target.place !== r.place || r.place === "record")) S.target = null;
  for (const a of document.querySelectorAll(".places a")) {
    if (a.dataset.place === r.place) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  if (S.frame) renderOutsideTabs(S.frame, r.place);
  $("main").className = r.place === "projects" || r.place === "map" || r.place === "work" ? "wide" : "";
  if (moved) {
    S.mounted = key;
    mount();
    window.scrollTo(0, 0);
  }
  if (S.data[routeOf(S.place)]) fill();
  try {
    await load(routeOf(S.place));
    S.err = null;
    $("checked").textContent = "Checked " + clock();
  } catch (e) {
    S.err = String(e.message || e);
    if (!S.data[routeOf(S.place)]) fill();
  }
  renderProblems();
}

// Each place is a module: render(data, el) draws it from its route's answer, and mount(el), where a place has one,
// makes the parts it keeps between drawings. A place a plug-in adds is drawn by its own page module (outside.js).
const PLACES = { waiting, projects, documents, map, record, work };
export function mount() { $("place").replaceChildren(); $("bar-place").replaceChildren(); if (PLACES[S.place] && PLACES[S.place].mount) PLACES[S.place].mount($("place")); }
export function fill() {
  const own = PLACES[S.place];
  if (own) keep(() => own.render(S.data[ROUTE[S.place]], $("place")));
  else if (outsidePlace(S.frame, S.place) && S.data[S.place]) keep(() => drawOutside(outsidePlace(S.frame, S.place), S.data[S.place], $("place")));
}

// Re-drawing keeps the scroll and, where it can, the focused control; only a link's target moves the page.
export function keep(fn) {
  const y = window.scrollY;
  const a = document.activeElement;
  const k = a && a.dataset ? a.dataset.k : null;
  S.moved = false;
  fn();
  if (k && !document.contains(a)) {
    const again = document.querySelector('[data-k="' + CSS.escape(k) + '"]');
    if (again) again.focus({ preventScroll: true });
  }
  if (!S.moved && Math.abs(window.scrollY - y) > 1) window.scrollTo(0, y);
  S.moved = false;
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
