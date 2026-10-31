// Today, Rules, Settings and Agents as places on the page. They draw from the home page's reads (ownbase.js), not from a
// place's answer: the route they read is only the frame, so the bar and the waiting count stay current.
import { $, AFTER, S, fill, h, hooks, host, load, loadInbox, loadMetrics, pollFeed, render } from "./ownbase.js";
import { Sky, closePop } from "./ownsky.js";
import { Space } from "./ownspace.js";
import { countsView, heroNodes, historyRows, needsYou, recentRows } from "./owntoday.js";
import { loadIdeas } from "./ownrules.js";
import { refreshLayers } from "./ownagents.js";
import { closeMenu, loadModels } from "./ownsettings.js";
import "./ownevents.js";

AFTER.today = () => loadMetrics();
AFTER.layers = () => refreshLayers();
AFTER.rules = () => { Sky.mount("ruleSky"); if (S.ideasOpen) loadIdeas(); };
AFTER.agents = () => { if ($("skyHost")) Space.mount("skyHost"); };
AFTER.settings = () => loadModels();

const onToday = (fn) => { if (host.el && S.view === "today") fn(); };
hooks.inbox = () => {};
hooks.metrics = () => onToday(() => fill("counts", countsView()));
hooks.layout = () => Space.layout();
hooks.fresh = (fresh) => {
  loadMetrics();
  onToday(() => { fill("hero", heroNodes()); fill("recent", recentRows()); });
  if (host.el && S.view === "history") fill("historyRows", historyRows());
  if (host.el && S.view === "rules") Sky.pulse(fresh);
};

export function leave() {
  if (!host.el) return;
  Space.unmount(); Sky.unmount(); closePop(); closeMenu();
  host.el = null;
}

let polling = false;
async function enter(view, el) {
  const own = h("div", { class: "own" }, h("div", { class: "problem", id: "problem", role: "alert", hidden: true }));
  const main = h("div", { class: "own-view" }, h("p", { class: "meta" }, "Reading your rules…"));
  own.append(main);
  el.replaceChildren(own);
  host.el = main;
  S.view = view;
  try {
    await load();
    await Promise.all([loadInbox(), pollFeed(), loadMetrics()]);
  } catch (e) {
    if (host.el === main) fill(main, [h("p", {}, "This could not start: " + String(e.message || e)), h("p", { class: "meta" }, "Is `semantext serve` still running? Reload the page once it is.")]);
    return;
  }
  if (host.el !== main) return;   // you moved on while it was reading
  render();
  if (!polling) {
    polling = true;
    setInterval(() => { if (host.el) pollFeed(); }, 3000);
    setInterval(() => { if (host.el) loadInbox(); }, 15000);
  }
}

// A place: mount(el) when you arrive; render(), each time the frame changes, moves only what the frame decides.
const place = (view) => ({
  mount: (el) => { enter(view(), el); },
  render: () => { onToday(() => { fill("hero", heroNodes()); fill("needs", needsYou()); }); },
});
export const todayPlace = place(() => (location.hash.includes("/history") ? "history" : "today"));
export const rulesPlace = place(() => (location.hash.includes("/test") ? "test" : "rules"));
export const settingsPlace = place(() => "settings");
export const agentsPlace = place(() => (location.hash.includes("~gets") ? "layers" : "agents"));
