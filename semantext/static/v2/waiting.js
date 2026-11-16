// Waiting, the home: every card that waits for your word, then the shelves.
import { $, h } from "./dom.js";
import { listWords, newestFirst, plural, stamp } from "./words.js";
import { disclosure, header } from "./parts.js";
import { applyTarget, fill, S } from "./app.js";
import { brierWords, cardNode } from "./cards.js";
import { closeDrawer } from "./drawers.js";
import { holdsNodes, openHolds } from "./proxyholds.js";

// ---------------------------------------------------------------- Waiting
export const W = {};

// On Waiting the cards lead: the place's heading, its sentence, the search and By project sit in the bar, so the first
// card is the first thing under it.
export function mount(el) {
  W.head = h("div");
  W.say = h("span", { class: "say" });
  W.search = h("input", { class: "input search", type: "search", placeholder: "Search the cards", "aria-label": "Search the cards",
    value: S.q.waiting, "data-k": "search:waiting" });
  W.search.addEventListener("input", () => { S.q.waiting = W.search.value; fill(); });
  W.group = h("button", { class: "toggle small", type: "button", "aria-pressed": String(S.byProject), "data-k": "byproject" }, "By project");
  W.group.addEventListener("click", () => { S.byProject = !S.byProject; W.group.setAttribute("aria-pressed", String(S.byProject)); fill(); });
  W.tools = h("div", { class: "bar-tools", role: "group", "aria-label": "Waiting" }, W.say, W.search, W.group);
  $("bar-place").replaceChildren(W.tools);
  W.list = h("section", { class: "cards", "aria-label": "Waiting for you" });
  W.empty = h("div", { hidden: true });
  W.proxy = h("section", { "aria-label": "The proxy holds" });
  W.parked = h("div");
  W.done = h("div");
  W.machine = h("section", { "aria-label": "This machine's own inbox" });
  el.replaceChildren(W.head, W.machine, W.list, W.empty, W.proxy, W.parked, W.done);
}

function cardText(c) {
  const ch = c.change || {};
  return [c.id, c.seat, c.title, c.why, c.question, ...(c.options || []), c.command, c.does, c.undo, c.cwd,
    c.project && c.project.name, ch.component, ch.hypothesis, ch.trigger, ch.regression_risk,
    ...(ch.predicted || []).map((p) => p.measure)].filter(Boolean).join("\n").toLowerCase();
}

// A long own inbox draws its newest cards of each kind; the rest are counted here and never dropped. As the newer ones are
// answered or parked, the older ones are drawn.
export function moreLine(n, kind) {
  return n ? h("p", { class: "shelf-note", "data-more": kind },
    plural(n, "more " + kind + " request") + " not drawn here: the newest are shown, and the older ones appear as you answer or park these. All of them are in your inbox file.") : null;
}

// What agents filed in this machine's own inbox while a setup is named: apart, under its own heading, and only when there is any.
function drawMachine(data, match) {
  const all = data.machine_inbox || [], cards = all.filter(match), more = data.machine_more || {};
  const n = all.filter((c) => c.state === "waiting").length + (more.waiting || 0), m = all.filter((c) => c.state === "parked").length + (more.parked || 0);
  W.machine.replaceChildren();
  if (all.length) W.machine.append(...[h("h2", { class: "label group-head" }, "This machine's own inbox · " + n + " waiting" + (m ? ", " + m + " parked" : "")), h("div", { class: "cards" }, cards.map(cardNode)),
    moreLine(more.waiting, "waiting"), moreLine(more.parked, "parked")].filter(Boolean));
}

export function render(data, el) {
  if (!data) { W.head.replaceChildren(h("h1", { class: "sr-only" }, "Waiting")); W.say.textContent = "Reading your files…"; return; }
  const q = S.q.waiting.trim().toLowerCase();
  const match = (c) => !q || cardText(c).includes(q);
  drawMachine(data, match);
  if (data.off) {
    W.head.replaceChildren(header("Waiting", "Waiting is off: your sources file names no " + listWords(data.missing.map((k) => '"' + k + '"')) + ".",
      S.frame ? "Your sources file: " + S.frame.config : null));
    W.tools.hidden = true;
    for (const x of [W.list, W.empty, W.parked, W.done]) x.replaceChildren();
    // The proxy's holds are not Waiting's cards: with Waiting off an agent may still be held at the proxy, waiting for
    // your word, so they are still shown, and said, never emptied without a word (the line under the title is hidden
    // with Waiting's tools, so the sentence goes in the section itself).
    const held = openHolds();
    W.proxy.replaceChildren(...(held ? [h("p", { class: "shelf-note" }, "The proxy holds " + plural(held, "call") + " for you.")] : []), ...holdsNodes());
    return;
  }
  W.proxy.replaceChildren(...holdsNodes());
  const held = openHolds();
  W.tools.hidden = false;
  const all = newestFirst(data.cards);
  const waiting = all.filter((c) => c.state === "waiting");
  const parked = data.cards.filter((c) => c.state === "parked").sort((a, b) => stamp(b.parked_at) - stamp(a.parked_at));
  const done = all.filter((c) => c.state === "closed" || c.state === "run");
  const w = waiting.filter(match), p = parked.filter(match), d = done.filter(match);
  const more = data.more || {};   // your own inbox, when it is the cards: what the cap left undrawn, by kind
  const nWaiting = waiting.length + (more.waiting || 0), nParked = parked.length + (more.parked || 0), nDone = done.length + (more.closed || 0);
  const sub = nWaiting === 0 ? (held ? "No card is waiting for you." : "Nothing is waiting for you.")
    : (nWaiting === 1 ? "1 card waits for your word." : nWaiting + " cards wait for your word, newest first.")
      + (q ? " " + w.length + " of them " + (w.length === 1 ? "matches" : "match") + "." : "");
  W.head.replaceChildren(h("h1", { class: "sr-only" }, "Waiting"));
  const elsewhere = (data.machine_inbox || []).filter((c) => c.state === "waiting").length + ((data.machine_more || {}).waiting || 0);
  W.say.textContent = sub + (elsewhere ? " Plus " + elsewhere + " in this machine's own inbox." : "")
    + (held ? " The proxy holds " + plural(held, "call") + " for you." : "");
  W.say.title = data.seats.length ? "From the requests of " + listWords(data.seats) + "." : "No agent's requests are read.";

  if (S.byProject && w.length) {
    const groups = new Map();
    for (const c of w) {
      const k = c.project ? (c.project.name || c.project.id) : "";
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(c);
    }
    const names = [...groups.keys()].filter(Boolean).sort((a, b) => a.localeCompare(b));
    if (groups.has("")) names.push("");
    W.list.replaceChildren(...names.map((k) => h("div", null,
      h("h2", { class: "label group-head" }, (k || "Not in a project") + " · " + groups.get(k).length),
      h("div", { class: "cards" }, groups.get(k).map(cardNode)))));
  } else {
    W.list.replaceChildren(...w.map(cardNode));
  }
  const waitingMore = moreLine(more.waiting, "waiting");
  if (waitingMore) W.list.append(waitingMore);
  W.empty.hidden = w.length !== 0;
  if (!waiting.length) {
    W.empty.replaceChildren(h("p", { class: "empty" }, held ? "No card is waiting for you." : "Nothing is waiting for you."), h("p", { class: "holds" }, data.holds ? data.holds.text : ""));
  } else if (!w.length) {
    W.empty.replaceChildren(h("p", { class: "empty" }, "No waiting card matches “" + S.q.waiting.trim() + "”."));
  }

  const parkedDecisions = data.record && !data.record.off ? data.record.parked : 0;
  W.parked.replaceChildren();
  if (parked.length || parkedDecisions) {
    const box = disclosure("shelf:parked", "Parked " + (q ? p.length + " of " + nParked : nParked), "shelf", fill);
    if (box.open) {
      if (p.length) box.append(h("div", { class: "cards" }, p.map(cardNode)));
      const parkedMore = moreLine(more.parked, "parked");
      if (parkedMore) box.append(parkedMore);
      if (parkedDecisions) box.append(h("p", { class: "shelf-note" }, plural(parkedDecisions, "decision is", "decisions are") + " parked in your register: ",
        h("a", { href: "#record", on: { click: () => { S.facet = "parked"; S.q.record = ""; } } }, "see them in the Record"), "."));
    }
    W.parked.append(box);
  }
  W.done.replaceChildren();
  if (done.length) {
    const box = disclosure("shelf:done", "Done " + (q ? d.length + " of " + nDone : nDone), "shelf", fill);
    if (box.open) {
      box.append(h("div", { class: "cards" }, d.map(cardNode)));
      const doneMore = moreLine(more.closed, "done");
      if (doneMore) box.append(doneMore);
    }
    W.done.append(box);
  }
  // Proposed changes: records, not asks, each linked to the decision cards that ask about it.
  const records = newestFirst(data.change_records || []);
  if (records.length) {
    const r = records.filter(match);
    const box = disclosure("shelf:changes", "Proposed changes " + (q ? r.length + " of " + records.length : records.length), "shelf", fill);
    if (box.open) box.append(h("div", { class: "cards" }, r.map(cardNode)));
    W.done.append(box);
  }
  // Proposed changes, per agent: filed, decided, and how their stated chances fared against what was measured.
  const scores = Object.entries(data.changes || {});
  if (scores.length) {
    W.done.append(h("p", { class: "shelf-note", "data-space": "mt-20" }, "Proposed changes: " + scores.map(([seat, s]) => seat + " " + s.filed + " filed, "
      + s.decided + " decided, " + brierWords(s)).join("; ") + "."));
  }
  applyTarget("waiting", "data-card");
}

export function goCard(key) {
  S.target = { place: "waiting", key, focused: false };
  closeDrawer(true);
  if (S.q.waiting) { S.q.waiting = ""; if (W.search) W.search.value = ""; }
  if (location.hash === "#waiting") fill(); else location.hash = "#waiting";
}
