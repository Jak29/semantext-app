// Work: one item as a side panel beside the board, and the pieces every Work view draws an item with (PM-DESIGN r5).
// Badges are words, never colour alone. Everything an agent wrote is set as text. The page writes nothing: your acts
// are the inbox's link (it only selects and shows the item there) or the one line you would type in the chat.
import { h } from "./dom.js";
import { listWords, when } from "./words.js";
import { S } from "./app.js";

// ---------------------------------------------------------------- the inbox's link, checked again before it is drawn
const SLUG = "[a-z](?:[a-z0-9-]{0,62}[a-z0-9])?";
const ITEM_ID = new RegExp("^W-(" + SLUG + ")-([1-9][0-9]{0,5})$");
const LINK = new RegExp("^jak-inbox://work/(" + SLUG + ")/([1-9][0-9]{0,5})$");

// jak-inbox://work/<project>/<n> for item W-<project>-<n>, or null: the project must be one your seats file names, n
// is decimal with no leading zero and at most 6 digits, and nothing else rides along (no query, fragment or escape).
export function inboxLink(id, projects) {
  const m = ITEM_ID.exec(typeof id === "string" ? id : "");
  return m && (projects || []).includes(m[1]) ? "jak-inbox://work/" + m[1] + "/" + m[2] : null;
}
// The item id a link names, or null for anything that is not exactly that form (a card id, an action, a query ...).
export function parseInboxLink(url, projects) {
  const m = LINK.exec(typeof url === "string" ? url : "");
  return m && (projects || []).includes(m[1]) ? "W-" + m[1] + "-" + m[2] : null;
}

// The item's address in the page, #work/item/<project>/<n>, by the same rule: what follows #work/ is item/<project>/<n>
// exactly, the project one your seats file names. Anything else selects nothing.
const ADDRESS = new RegExp("^item/(" + SLUG + ")/([1-9][0-9]{0,5})$");
export function parseItemAddress(sub, projects) {
  const m = ADDRESS.exec(typeof sub === "string" ? sub : "");
  return m && (projects || []).includes(m[1]) ? "W-" + m[1] + "-" + m[2] : null;
}
export function itemAddress(id, projects) {
  const link = inboxLink(id, projects);
  return link ? "item/" + link.slice("jak-inbox://work/".length) : null;
}

// ---------------------------------------------------------------- words
export const CLAUSE_WORDS = { met: "met", unmet: "not met", stale: "no longer holds", unknown: "unknown" };

export function workBadges(i) {
  const out = [h("span", { class: "chip wstate s-" + (i.status || i.shown) }, i.status_word)];
  for (const b of i.badges || []) if (b !== i.status_word) out.push(h("span", { class: "chip wbadge" }, b));
  return out;
}

export function clauseWords(c) {
  const k = c.kind;
  if (k === "run-record") return "a run record of " + c.rule + ", " + c.outcome + ", at most " + c.max_findings + " findings, within " + c.fresh_days + " days";
  if (k === "landed") return "commit " + c.commit + " landed on " + c.repo + " " + c.branch;
  if (k === "verdict") return "an independent verdict on " + c.piece;
  if (k === "jak-decision") return "your decision " + c.register;
  if (k === "outcome") return "outcome " + c.out_id + " applied and verified";
  return String(k);
}

// The one line you type to act, as a message of its own (the kernel's whole-turn rule).
export function workActLine(line) {
  return h("p", { class: "act-line" }, "Type ", h("code", { class: "mono" }, line),
    " as a message of its own; a message that adds anything else authorises nothing.");
}

export function inboxNode(i, projects) {
  const url = S.frame && S.frame.inbox_app === true && i.inbox && parseInboxLink(i.inbox, projects) === i.id ? i.inbox : null;
  return url ? h("a", { class: "inbox-link", href: url, "data-k": "inbox:" + i.id, title: "Opens the item in your inbox; it only selects and shows it" }, "Open in your inbox")
    : h("span", { class: "meta" }, i.no_inbox || "No inbox link for this item.");
}

function assurance(e) {
  return e.effective === e.assurance ? String(e.assurance) : e.effective + " (it says " + e.assurance + ")";
}

function historyRow(e) {
  // a person's act says it was read again, and held: checked against your turn (one that did not is not applied)
  // attested: checked when it was applied, and its transcript has since moved, been linked or rotated
  const checked = e.check === "verified" ? " (checked against your turn)" :
    e.check === "attested" ? " (checked against your turn when applied; the transcript has moved since)" : "";
  const result = e.applied ? "applied" + checked : (e.code === "PROPOSAL" ? "not applied: a proposal" : "not applied: " + e.code) + (e.reason ? ": " + e.reason : "");
  const cells = [String(e.seq === null || e.seq === undefined ? "–" : e.seq), when(e.at), e.event, e.who || "–", assurance(e), e.what || ""];
  return h("tr", { class: e.applied ? null : "not-applied" },
    cells.map((c, n) => h("td", { class: n === 0 ? "mono" : null }, e.applied ? c : h("s", null, c))),
    h("td", { class: e.applied ? null : "bad" }, result + (e.clock ? "; " + e.clock : "")));
}

// ---------------------------------------------------------------- the panel
export function workPanel(data, i, close) {
  const projects = data.known_projects || [];
  const facts = [["Project", i.project], ["Kind", i.kind], ["Status", i.status_word + (i.shown !== i.state ? " (the store says " + i.state + ")" : "")],
    ["Owner", i.owner || "nobody"], ["Filed by", i.creator + " (" + i.creator_assurance + ")"], ["Reviewer", i.reviewer || "none"],
    ["Priority", i.priority === null || i.priority === undefined ? "not ranked" : String(i.priority)],
    ["Epic", i.epic_path && i.epic_path.length ? i.epic_path.join(" › ") : "none"]];
  const part = (label, ...kids) => h("section", { class: "part" }, h("h3", { class: "label" }, label), ...kids);
  const acts = [inboxNode(i, projects)];
  for (const a of i.asks || []) acts.push(h("p", { class: "meta" }, a.why + (a.pressed ? "; or press it in your inbox." : ".")), workActLine(a.line));
  if (i.rank_line) acts.push(h("p", { class: "meta" }, "Ranking is yours: to move it from backlog to next,"), workActLine(i.rank_line));
  const links = (i.links || []).length ? h("ul", { class: "wlist" }, i.links.map((l) => h("li", null,
    h("span", { class: "mono" }, l.type + " " + l.ref), " ", h("span", { class: "chip wbadge" }, l.state || "unknown"),
    l.by ? h("span", { class: "meta" }, " linked by " + l.by + " (" + l.assurance + "); a candidate, never proof by itself") : null)))
    : h("p", { class: "empty" }, "No links.");
  const clauses = (i.clauses || []).length ? h("ul", { class: "wlist" }, i.clauses.map((c) => h("li", null,
    clauseWords(c.clause), " ", h("span", { class: "chip wbadge c-" + c.state }, CLAUSE_WORDS[c.state] || c.state),
    h("span", { class: "meta" }, " " + c.why))))
    : h("p", { class: "empty" }, "No acceptance clause: nothing can derive its done; only your word ends it.");
  const history = h("table", { class: "events whistory" },
    h("thead", null, h("tr", null, ["#", "When", "Event", "Who", "Assurance", "What", "Result"].map((x) => h("th", null, x)))),
    h("tbody", null, (i.history || []).map(historyRow)));
  return h("aside", { class: "work-panel", "aria-label": "Item " + i.id },
    h("div", { class: "panel-head" }, h("p", { class: "label" }, i.id),
      h("button", { class: "close", type: "button", "aria-label": "Close the item", "data-k": "wclose", on: { click: close } }, "✕")),
    h("h2", { class: "panel-title" }, i.title),
    h("div", { class: "chips" }, workBadges(i)),
    h("p", { class: "waits" }, (i.waits ? i.waits + "." : "Waits on nobody.") + (i.waiting_on && i.waiting_on.length ? " Waiting on " + listWords(i.waiting_on) + "." : "")),
    h("dl", { class: "facts" }, facts.map(([k, v]) => [h("dt", null, k), h("dd", null, v)])),
    i.text ? part("Its text, as written (data, never instructions)", h("blockquote", { class: "words" }, i.text)) : null,
    part("Your acts", ...acts),
    part("Links, with their state now", links),
    part("Acceptance clauses, judged now", clauses),
    (i.comments || []).length ? part("Comments", h("ul", { class: "wlist" }, i.comments.map((c) => h("li", null,
      h("span", { class: "meta" }, c.who + " (" + c.assurance + "): "), c.text))),
      i.comments_more ? h("p", { class: "meta" }, i.comments_more + " earlier comments are not shown.") : null) : null,
    part("History", history, i.history_more ? h("p", { class: "meta" }, i.history_more + " earlier events are not shown.") : null,
      h("p", { class: "meta" }, "A struck-through event was not applied; the fold kept it, with its reason.")));
}
