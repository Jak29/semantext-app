// Work: the board (a swimlane per project, a column per state, done and parked folded), the backlog (ranked per
// project, epics folded) and the estate view (what no longer holds first, then the counts). PM-DESIGN r5, the layout.
import { h } from "./dom.js";
import { plural } from "./words.js";
import { disclosure } from "./parts.js";
import { workBadges } from "./workitem.js";

export const WORK_STATES = ["backlog", "next", "doing", "review", "done", "parked"];
const FOLDED = new Set(["done", "parked"]);
const OPEN = new Set(["backlog", "next", "doing", "review"]);
const STATE_TITLE = { backlog: "Backlog", next: "Next", doing: "Doing", review: "Review", done: "Done", parked: "Parked" };

// One item, as a button that opens it in the side panel.
export function itemButton(i, sel, select, extra) {
  return h("button", { class: "witem" + (sel === i.id ? " selected" : ""), type: "button", "data-k": "wi:" + i.id,
    "aria-pressed": String(sel === i.id), on: { click: () => select(i.id) } },
  h("span", { class: "witem-head" }, h("span", { class: "mono" }, i.id), h("span", { class: "chip kind" }, i.kind),
    i.priority !== null && i.priority !== undefined ? h("span", { class: "chip" }, "priority " + i.priority) : null),
  h("span", { class: "witem-title" }, i.title),
  // the owner's chip only when there is one: "no owner" is a badge already, and one fact has one badge
  h("span", { class: "chips" }, i.owner ? h("span", { class: "chip seat" }, i.owner) : null, workBadges(i)),
  extra ? h("span", { class: "meta" }, extra) : null);
}

const live = (data) => (data.items || []).filter((i) => !i.voided);
const ofProject = (data, p) => live(data).filter((i) => i.project === p);
const rank = (a, b) => ((a.priority ?? 1e9) - (b.priority ?? 1e9)) || (a.n - b.n);

function lane(data, p, sel, select) {
  const items = ofProject(data, p.name);
  const cols = WORK_STATES.map((s) => {
    const here = items.filter((i) => i.shown === s).sort(rank);
    const cards = here.map((i) => itemButton(i, sel, select, s === "review" ? i.waits : null));
    if (FOLDED.has(s)) {
      const box = disclosure("work:" + s + ":" + p.name, STATE_TITLE[s] + " " + here.length, "wcol-fold");
      box.append(...cards);   // folded until opened; the fold remembers being opened
      return h("div", { class: "wcol", role: "group", "aria-label": STATE_TITLE[s] + ", " + p.name }, box);
    }
    return h("div", { class: "wcol", role: "group", "aria-label": STATE_TITLE[s] + ", " + p.name },
      h("p", { class: "label" }, STATE_TITLE[s] + " " + here.length), ...cards);
  });
  return h("section", { class: "lane", "aria-label": "Project " + p.name },
    h("h2", { class: "lane-head" }, p.name, p.known ? null : h("span", { class: "meta" }, " (not a project in your seats file)"),
      h("span", { class: "meta" }, " · " + plural(items.length, "item"))),
    h("div", { class: "wcols" }, cols));
}

export function workBoard(data, sel, select) {
  if (!(data.projects || []).length) return h("p", { class: "empty" }, "No work items yet.");
  return h("div", { class: "board" }, data.projects.map((p) => lane(data, p, sel, select)));
}

// The backlog: every open item of a project, ranked (your priority first, then the order filed), each epic folded with
// its own items inside it. The rank is read here; only your typed line changes it.
export function workBacklog(data, sel, select) {
  if (!(data.projects || []).length) return h("p", { class: "empty" }, "No work items yet.");
  return h("div", { class: "backlog" }, data.projects.map((p) => {
    const items = ofProject(data, p.name);
    // An epic may sit under an epic (rules.py checks only that the parent is an epic of the project), so the backlog
    // is a tree: every open item and every epic goes inside its parent epic, at any depth. An epic is drawn when it is
    // open or holds open work below it, and counts the open items below it at every depth.
    const epics = new Map(items.filter((i) => i.kind === "epic").map((e) => [e.id, { epic: e, kids: [], open: 0 }]));
    const parentOf = (i) => (i.epic && i.epic !== i.id && epics.has(i.epic) ? epics.get(i.epic) : null);
    const units = [];
    for (const i of items.filter((x) => x.kind !== "epic" && OPEN.has(x.shown))) {
      const up = parentOf(i);
      (up ? up.kids : units).push(i);
      for (let e = up, seen = new Set(); e && !seen.has(e.epic.id); e = parentOf(e.epic)) { seen.add(e.epic.id); e.open += 1; }
    }
    for (const { epic: e, open } of epics.values()) {
      if (!OPEN.has(e.shown) && !open) continue;
      const up = parentOf(e);
      (up ? up.kids : units).push(e);
    }
    const row = (i) => h("li", null, h("span", { class: "rank meta" }, i.priority === null || i.priority === undefined ? "not ranked" : "#" + i.priority),
      itemButton(i, sel, select, i.shown));
    const unit = (u) => {
      if (u.kind !== "epic") return row(u);
      const { kids, open } = epics.get(u.id);
      const box = disclosure("work:epic:" + u.id, "Epic " + u.id + ": " + u.title + " · " + plural(open, "open item"), "epic");
      box.append(h("div", { class: "epic-own" }, itemButton(u, sel, select, u.shown)), h("ol", { class: "ranked" }, kids.sort(rank).map(unit)));
      return h("li", null, box);
    };
    const list = h("ol", { class: "ranked" }, units.sort(rank).map(unit));
    return h("section", { class: "part", "aria-label": "Backlog of " + p.name }, h("h2", { class: "lane-head" }, p.name),
      units.length ? list : h("p", { class: "empty" }, "Nothing open."));
  }));
}

function shortlist(title, items, sel, select, none) {
  return h("section", { class: "part" }, h("h2", { class: "label" }, title + " · " + items.length),
    items.length ? h("div", { class: "wlist-items" }, items.map((i) => itemButton(i, sel, select, i.waits))) : h("p", { class: "empty" }, none));
}

export function workEstate(data, sel, select) {
  const items = live(data);
  const gone = items.filter((i) => i.status === "proof-gone");
  const claimed = items.filter((i) => i.status === "done-claimed");
  // done (claimed) is its own column, never counted as done; so is each other done word, and proof no longer holds
  const cols = ["backlog", "next", "doing", "review", "proof no longer holds", "done (checked)", "done (claimed)",
    "done (your word)", "parked", "void"];
  const table = h("table", { class: "events wcounts" },
    h("thead", null, h("tr", null, h("th", null, "Project"), cols.map((c) => h("th", null, c)))),
    h("tbody", null, (data.projects || []).map((p) => h("tr", null, h("td", null, p.name),
      cols.map((c) => h("td", { class: "mono" }, String((data.counts[p.name] || {})[c] || 0)))))));
  const st = data.store || {};
  return h("div", { class: "estate" },
    shortlist("Proof no longer holds", gone, sel, select, "Every proof that once held still holds."),
    shortlist("Done (claimed)", claimed, sel, select, "No item is done on proof that no reader can see."),
    h("section", { class: "part" }, h("h2", { class: "label" }, "Counts per project and state"),
      (data.projects || []).length ? table : h("p", { class: "empty" }, "No work items yet."),
      h("p", { class: "meta" }, plural(st.events || 0, "event") + " in the store, " + (data.not_applied || 0) + " of them not applied. "
        + (st.intact ? "The chain from its head is whole." : "The chain is broken: no event is trusted."))));
}
