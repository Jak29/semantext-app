// Work: every piece of work across your projects, read from the work store through the kernel's fold (PM-DESIGN r5).
// At the top, what waits on you; then the board, the backlog or the estate view, with the item you pick in a side
// panel beside it. The page only reads: your acts are a link into your inbox, or the one line you type in the chat.
import { $, h } from "./dom.js";
import { plural } from "./words.js";
import { disclosure, header } from "./parts.js";
import { fill, S } from "./app.js";
import { itemButton, workBacklog, workBoard, workEstate } from "./workboard.js";
import { inboxNode, itemAddress, parseItemAddress, workActLine, workPanel } from "./workitem.js";

// The view is in the address (#work, #work/backlog, #work/estate), and so is the item open in the panel
// (#work/item/<project>/<n>, checked as the inbox link is). An item of a project your seats file does not name has no
// address: it opens in the panel, and the address stays as it was.
export const WK = { sel: null, view: "board", loose: null };
const VIEWS = [["board", "Board"], ["backlog", "Backlog"], ["estate", "Estate"]];
function viewOf() {
  if (VIEWS.some(([k]) => k === S.sub)) WK.view = S.sub;
  else if (!String(S.sub || "").startsWith("item/")) WK.view = "board";
  return WK.view;
}
export const workSelected = (data) => parseItemAddress(S.sub, data.known_projects) || WK.loose;

export function mount(el) {
  WK.say = h("span", { class: "say" });
  WK.views = h("nav", { class: "seg", "aria-label": "Work views" }, VIEWS.map(([k, t]) =>
    h("a", { class: "toggle small", href: "#work" + (k === "board" ? "" : "/" + k), "data-k": "wv:" + k }, t)));
  $("bar-place").replaceChildren(h("div", { class: "bar-tools", role: "group", "aria-label": "Work" }, WK.say, WK.views));
  WK.head = h("div");
  WK.strip = h("section", { class: "wstrip", "aria-label": "Waiting on you" });
  WK.body = h("div", { class: "wbody" });
  el.replaceChildren(WK.head, WK.strip, WK.body);
}

export function workSelect(id) {
  const data = S.data.work || {};
  const open = id && id !== workSelected(data) ? id : null;
  const addr = open ? itemAddress(open, data.known_projects) : null;
  WK.loose = open && !addr ? open : null;
  S.sub = addr || (WK.view === "board" ? null : WK.view);
  S.mounted = "work/" + (S.sub || "");   // the address is changed here, so the place is not mounted again
  if (typeof history !== "undefined" && history.replaceState) history.replaceState(null, "", "#work" + (S.sub ? "/" + S.sub : ""));
  fill();
}

// "Waiting on you": the same set the inbox lists under "Work waiting on you" (r5): proposals and requests for your word,
// each with the inbox's link where the inbox carries the act and the line you would type, and the count waiting on
// your ranking.
export function workStrip(data, select) {
  const byId = new Map((data.items || []).map((i) => [i.id, i]));
  const rows = (data.asks || []).map((a) => {
    const i = byId.get(a.item);
    return h("div", { class: "ask" }, itemButton(i, WK.sel, select, a.why),
      a.pressed ? inboxNode(i, data.known_projects || []) : h("span", { class: "meta" }, "Typed in the chat, never pressed (it carries a value)."),
      workActLine(a.line));
  });
  const ranking = data.ranking || [];
  const out = [h("h2", { class: "label" }, "Waiting on you")];
  if (!rows.length && !ranking.length) out.push(h("p", { class: "empty" }, "Nothing here waits on you."));
  out.push(...rows);
  if (ranking.length) {
    const box = disclosure("work:ranking", plural(ranking.length, "item waits", "items wait") + " for your ranking (backlog to next)", "wrank");
    box.append(...ranking.map((id) => byId.get(id)).filter(Boolean).map((i) => h("div", { class: "ask" },
      itemButton(i, WK.sel, select, null), workActLine(i.rank_line))));
    out.push(box);
  }
  return out;
}

export function render(data, el) {
  if (!data) { WK.head.replaceChildren(header("Work", "Reading the work store…")); return; }
  const view = viewOf();
  WK.sel = workSelected(data);
  for (const a of WK.views.children) {
    if (a.getAttribute("data-k") === "wv:" + view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  const st = data.store || {};
  const items = (data.items || []).filter((i) => !i.voided);
  WK.say.textContent = st.exists ? plural(items.length, "item") + " in " + plural((data.projects || []).length, "project") : "No work store yet.";
  const notes = [];
  if (!st.exists) notes.push(h("p", { class: "empty" }, "No work items yet. Agents file them with the work tool; `semantext work new` files one from a shell."));
  if (st.exists && !st.intact) notes.push(h("p", { class: "refused" }, "The store's chain is broken (cut, edited or reordered): no event in it is trusted, so every one counts as claimed and holds no rights. The problems list says where."));
  WK.head.replaceChildren(h("h1", { class: "sr-only" }, "Work"), ...notes);
  WK.strip.replaceChildren(...workStrip(data, workSelect));
  WK.strip.hidden = !st.exists;
  const main = view === "backlog" ? workBacklog(data, WK.sel, workSelect) : view === "estate" ? workEstate(data, WK.sel, workSelect)
    : workBoard(data, WK.sel, workSelect);
  const picked = WK.sel && (data.items || []).find((i) => i.id === WK.sel);
  WK.body.className = "wbody" + (picked ? " with-panel" : "");
  // replaceChildren sets a null as the text "null", so only what is there is passed (h() skips a null; this does not)
  const kids = [h("div", { class: "wmain" }, main)];
  if (picked) kids.push(workPanel(data, picked, () => workSelect(null)));
  WK.body.replaceChildren(...kids);
}
