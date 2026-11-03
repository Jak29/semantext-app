// Work: your own changes to work items, made here on your page (PAGE-ACTS r1). The one module that posts to /api/work,
// and to nothing else. Each change says the state the item was drawn in, so a board drawn before another change is
// refused (stale) rather than applied to the wrong state; each click carries a key of its own, so a retry records once.
// What you wrote is kept when a change is refused, and the refusal's words are shown.
import { h } from "./dom.js";
import { fill, load } from "./app.js";

export const WORK_ROUTE = "/api/work";
export const WA = { said: null, ok: null, drafts: {}, adding: null, editing: null, dragging: null };
export const STATES = ["backlog", "next", "doing", "review"];
export const STATE_WORD = { backlog: "Backlog", next: "Next", doing: "Doing", review: "Review" };
const KINDS = ["task", "story", "bug", "research", "epic"];

function key() {
  const c = globalThis.crypto;
  if (c && c.randomUUID) return "page-" + c.randomUUID();
  return "page-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
}

export const workPost = { post: (body) => fetch(WORK_ROUTE, { method: "POST", cache: "no-store",
  headers: { "X-Semantext": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) }) };

// One change: {action: create | edit | act, request}. True when it was taken.
export async function workChange(action, request, done, version, confirmed) {
  let r = null, got = {};
  const body = { action, request: { ...request, request_key: key() } };
  if (version !== undefined) body.version = version;   // the item as the page drew it: a change since is refused
  if (confirmed) body.confirm = request.id;            // done and void, asked first
  try {
    r = await workPost.post(body);
    try { got = await r.json(); } catch (e) { /* the status says enough */ }
  } catch (e) { got = { error: "the page could not reach Semantext" }; }
  const ok = !!(r && r.ok);
  WA.said = ok ? null : (got.error || "That change was not taken.");
  WA.ok = ok ? (done || "Done.") : null;
  if (ok) await load("work");
  fill();
  return ok;
}

export const act = (i, what, extra, done) => workChange("act", { id: i.id, act: what, ...(extra || {}) }, done, i.version,
  what === "done" || what === "void");
export const moveTo = (i, to) => i.state === to ? Promise.resolve(false)
  : act(i, to, { from: i.state }, i.id + " moved to " + STATE_WORD[to] + ".");

// The line under the board that says what happened, or why it did not.
export function workSaid() {
  if (WA.said) return h("p", { class: "refused", role: "alert" }, WA.said);
  if (WA.ok) return h("p", { class: "meta", role: "status" }, WA.ok);
  return null;
}

// ---------------------------------------------------------------- new item, per project
export function newItemNode(project) {
  if (WA.adding !== project) {
    return h("button", { type: "button", class: "toggle small", "data-k": "wnew:" + project,
      on: { click: () => { WA.adding = project; WA.said = null; fill(); } } }, "New item");
  }
  const d = WA.drafts["new:" + project] || (WA.drafts["new:" + project] = { title: "", kind: "task" });
  const title = h("input", { type: "text", class: "wfield", value: d.title, placeholder: "What is the work?",
    "aria-label": "Title of the new item", on: { input: (e) => { d.title = e.target.value; } } });
  const kind = h("select", { class: "wfield", "aria-label": "Kind", on: { change: (e) => { d.kind = e.target.value; } } },
    KINDS.map((k) => h("option", { value: k, selected: k === d.kind ? "" : null }, k)));
  const send = async () => {
    if (!d.title.trim()) { WA.said = "Write a title first."; fill(); return; }
    if (await workChange("create", { project, title: d.title.trim(), kind: d.kind }, "Filed in " + project + ", in Backlog.")) {
      delete WA.drafts["new:" + project]; WA.adding = null; fill();
    }
  };
  return h("form", { class: "wnew", "aria-label": "New item in " + project, on: { submit: (e) => { e.preventDefault(); send(); } } },
    title, kind, h("button", { type: "submit", class: "answer" }, "File it"),
    h("button", { type: "button", class: "toggle small", on: { click: () => { WA.adding = null; fill(); } } }, "Cancel"));
}

// ---------------------------------------------------------------- the panel's controls
function editNode(i) {
  if (WA.editing !== i.id) {
    return h("button", { type: "button", class: "toggle small", "data-k": "wedit:" + i.id, disabled: i.state === "done",
      title: i.state === "done" ? "A done item is not edited; a later defect is a new item" : null,
      on: { click: () => { WA.editing = i.id; WA.said = null; fill(); } } }, "Edit");
  }
  const d = WA.drafts["edit:" + i.id] || (WA.drafts["edit:" + i.id] = { title: i.title, kind: i.kind, text: i.text || "" });
  const title = h("input", { type: "text", class: "wfield", value: d.title, "aria-label": "Title", on: { input: (e) => { d.title = e.target.value; } } });
  const kind = h("select", { class: "wfield", "aria-label": "Kind", on: { change: (e) => { d.kind = e.target.value; } } },
    KINDS.map((k) => h("option", { value: k, selected: k === d.kind ? "" : null }, k)));
  const text = h("textarea", { class: "wfield", rows: "5", "aria-label": "Text", on: { input: (e) => { d.text = e.target.value; } } });
  text.value = d.text;
  const send = async () => {
    const req = { id: i.id };
    if (d.title.trim() && d.title.trim() !== i.title) req.title = d.title.trim();
    if (d.kind !== i.kind) req.kind = d.kind;
    if (d.text !== (i.text || "")) req.text = d.text;
    if (Object.keys(req).length === 1) { WA.editing = null; fill(); return; }
    if (await workChange("edit", req, i.id + " saved.", i.version)) { delete WA.drafts["edit:" + i.id]; WA.editing = null; fill(); }
  };
  return h("form", { class: "wedit", "aria-label": "Edit " + i.id, on: { submit: (e) => { e.preventDefault(); send(); } } },
    title, kind, text, h("div", { class: "row" }, h("button", { type: "submit", class: "answer" }, "Save"),
      h("button", { type: "button", class: "toggle small", on: { click: () => { delete WA.drafts["edit:" + i.id]; WA.editing = null; fill(); } } }, "Cancel")));
}

// A change that one more click cannot take back asks first, in words.
function sure(words) {
  return typeof confirm !== "function" || confirm(words);
}

export function panelControls(i) {
  const out = [];
  const st = i.state;
  if (i.voided) return [h("p", { class: "meta" }, "This item is void; nothing more is done to it.")];
  if (STATES.includes(st)) {
    out.push(h("div", { class: "row", role: "group", "aria-label": "Move " + i.id },
      h("span", { class: "meta" }, "Move to "),
      STATES.filter((s) => s !== st).map((s) => h("button", { type: "button", class: "toggle small", "data-k": "wmove:" + s,
        on: { click: () => moveTo(i, s) } }, STATE_WORD[s]))));
  }
  const row = [];
  if (st === "doing" || st === "review") row.push(h("button", { type: "button", class: "answer", "data-k": "wdone",
    on: { click: () => sure("Mark " + i.id + " done on your word? Only reopening undoes it.") && act(i, "done", { from: st }, i.id + " is done, on your word.") } }, "Done"));
  if (STATES.includes(st)) row.push(h("button", { type: "button", class: "toggle small", "data-k": "wpark",
    on: { click: () => act(i, "park", null, i.id + " parked: nobody moves it until you bring it back.") } }, "Park"));
  if (st === "parked") row.push(h("button", { type: "button", class: "answer", "data-k": "wunpark",
    on: { click: () => act(i, "unpark", null, i.id + " brought back.") } }, "Bring back"));
  if (st === "done") row.push(h("button", { type: "button", class: "toggle small", "data-k": "wreopen",
    on: { click: () => act(i, "reopen", null, i.id + " reopened, in Doing.") } }, "Reopen"));
  row.push(editNode(i));
  if (st !== "done") row.push(h("button", { type: "button", class: "toggle small bad", "data-k": "wvoid",
    on: { click: () => sure("Void " + i.id + "? It stays in the history, struck out, and cannot be brought back.") && act(i, "void", null, i.id + " is void.") } }, "Void"));
  out.push(h("div", { class: "row" }, row));
  const d = WA.drafts["prio:" + i.id] || (WA.drafts["prio:" + i.id] = { v: i.priority === null || i.priority === undefined ? "" : String(i.priority) });
  const prio = h("input", { type: "number", min: "1", max: "999", step: "1", class: "wfield narrow", value: d.v, "aria-label": "Priority (1 is first)",
    on: { input: (e) => { d.v = e.target.value; } } });
  out.push(h("form", { class: "row", "aria-label": "Rank " + i.id, on: { submit: (e) => {
    e.preventDefault();
    const n = Number(d.v);
    if (!Number.isInteger(n) || n < 1 || n > 999) { WA.said = "A priority is a whole number from 1 (first) to 999."; fill(); return; }
    act(i, "priority", { value: n }, i.id + " ranked " + n + ".");
  } } }, h("span", { class: "meta" }, "Priority "), prio, h("button", { type: "submit", class: "toggle small" }, "Rank")));
  return out;
}

// ---------------------------------------------------------------- dragging a card between columns
// A card carries its id; a column takes it when it is one of the four you move between. The keyboard way is the
// panel's "Move to" buttons, which do the same.
export function draggable(i) {
  if (!STATES.includes(i.state) || i.voided) return {};
  return { draggable: "true", on: {
    dragstart: (e) => { WA.dragging = i.id; e.dataTransfer.setData("text/x-semantext-item", i.id); e.dataTransfer.effectAllowed = "move"; },
    dragend: () => { WA.dragging = null; } } };
}

export function dropTarget(state, items) {
  if (!STATES.includes(state)) return {};
  const over = (e) => { if (Array.from(e.dataTransfer.types || []).includes("text/x-semantext-item")) { e.preventDefault(); e.currentTarget.classList.add("drop"); } };
  return { "data-drop": state, on: {
    dragover: over, dragenter: over,
    dragleave: (e) => e.currentTarget.classList.remove("drop"),
    drop: (e) => {
      e.preventDefault(); e.currentTarget.classList.remove("drop");
      // only a drag that began on this page's own card: a drag from another window may carry the same type (Koinos's F8)
      const id = e.dataTransfer.getData("text/x-semantext-item");
      const mine = WA.dragging !== null && WA.dragging === id;
      WA.dragging = null;
      const i = mine ? (items || []).find((x) => x.id === id) : null;
      if (i) moveTo(i, state);
    } } };
}
