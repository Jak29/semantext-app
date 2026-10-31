// Agents, one step in from the Map: who they are, what each gets, and naming one by its folder.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR, VIEWS } from "./ownbase.js";
import { ruleRow } from "./ownrules.js";
import { spaceLegend } from "./ownspace.js";

// What your agents say to each other, and who is working on what: to read. Nothing on it is your word.
const BOARD = { posts: [], claims: [], attacks: [], damaged: 0 };
const named = (e) => String(e.said_by || e.from || "an agent");
export async function loadBoard() {
  try { Object.assign(BOARD, await api("/api/board"), { failed: false }); } catch (e) { BOARD.failed = true; }
  fill("boardBox", boardView());
}
export function boardView() {
  return [h("div", { class: "sechead" }, h("h2", { class: "label" }, "Between your agents"), h("span", { class: "meta" }, "information, never your word")),
    BOARD.failed ? h("p", { class: "meta warn" }, "The board could not be read.") : null,
    (BOARD.unread || []).length ? h("p", { class: "meta warn" }, "Could not be read: " + BOARD.unread.join(", ") + ".") : null,
    BOARD.damaged ? h("p", { class: "meta warn" }, plural(BOARD.damaged, "damaged line") + " in the board file could not be read.") : null,
    BOARD.claims.length ? h("ul", { class: "list" }, BOARD.claims.map(c => h("li", { class: "line" }, h("span", { class: "who" }, c.path), h("span", { class: "what" }, named(c) + (c.note ? "  ·  " + c.note : "")), h("span", { class: "when meta" }, ago(c.at))))) : null,
    BOARD.posts.length ? h("ul", { class: "list", "data-sp": "mt12" }, BOARD.posts.map(p => h("li", {}, h("div", { class: "line" }, h("span", { class: "who" }, named(p)), h("span", { class: "what" }, (p.to && p.to.length ? "to " + p.to.join(", ") + "  ·  " : "") + p.title), h("span", { class: "when meta" }, ago(p.at))), p.body ? h("pre", { class: "card" }, p.body) : null)))
      : h("p", { class: "meta" }, "Nothing yet. Agents post with semantext board post, and see what is for them with semantext start."),
    h("div", { class: "sechead", "data-sp": "mt16" }, h("h2", { class: "label" }, "Claims under attack"), h("span", { class: "meta" }, "survived means it stood up to this attack, not that it is true")),
    BOARD.attacks.length ? h("ul", { class: "list" }, [...BOARD.attacks].reverse().map(c => h("li", {}, h("div", { class: "line" }, h("span", { class: "who" }, c.state), h("span", { class: "what" }, c.claim), h("span", { class: "when meta" }, named(c))),
      c.verdicts.map(v => h("p", { class: "meta" }, v.verdict + ", by " + named(v) + ": " + v.method + (v.not_tried ? "  ·  not tried: " + v.not_tried : ""))))))
      : h("p", { class: "meta" }, "None yet. An agent puts one up with semantext attack ask.")];
}
function sizeBar(pct) { const i = h("i", {}); i.style.width = pct + "%"; return h("div", { class: "sizebar" }, i); }
function deliveries(agent, env) { return S.feed.records.filter(r => r.agent === agent && (!env || r.environment === env)); }
export function allAgents() {
  const names = new Map(S.agents.map(a => [a.name, a]));
  for (const r of S.feed.records) if (!names.has(r.agent)) names.set(r.agent, { name: r.agent, label: "", folders: [], sessions: [], rules: [], carried: [], envs: {} });
  return [...names.values()];
}
export function agentRows(list) {
  if (!list.length) return h("li", { class: "empty" }, "No agents yet. One appears here once it uses Semantext, or when you name one by its folder.");
  return list.map(a => {
    const open = S.agentOpen === a.name, cards = deliveries(a.name).length, own = (a.rules || []).length;
    const how = a.folders.length ? "bound by you" : a.sessions.length ? (a.sessions.every(s => s.how === "claimed") ? "claimed" : "seen in its folder") : a.name === "ai" ? "unnamed" : "rules only";
    return h("li", {},
      h("button", { class: "line", type: "button", "data-agent": a.name, "aria-expanded": String(open) },
        h("span", { class: "who" }, label(a.name)),
        h("span", { class: "what meta", "data-sp": "t3" }, how),
        h("span", { class: "when meta" }, [plural(cards, "card"), own ? plural(own, "own rule") : ""].filter(Boolean).join("  ·  ")),
        h("span", { class: "chev", "aria-hidden": "true" }, open ? "–" : "+")),
      open ? agentDetail(a) : null);
  });
}
function agentDetail(a) {
  const name = S.state.active, open = S.inbox.open.filter(q => q.from === a.name).length;
  return h("div", { class: "opened", id: "agentDetail" },
    h("p", { class: "meta" }, (a.folders.length ? "Bound by you to " + a.folders.join(", ") : a.sessions.length ? "Seen by its tool and project" : "Known by the rules you gave it")
      + (a.seen ? `, last seen ${a.seen}` : "") + (a.sessions.length ? ` (${plural(a.sessions.length, "session")})` : "") + "."
      + (open ? ` ${plural(open, "request")} waiting for you.` : "")),
    a.folders.length ? h("div", { class: "links", "data-sp": "mt6" }, a.folders.map(f => h("button", { class: "link meta", type: "button", "data-unbind": f }, `Unbind ${f}`))) : null,
    a.now ? h("p", { class: "meta" }, `You bound its folder to ${a.now}: its rules go with ${a.now} now.`) : null,
    (a.rules || []).length ? h("ul", { class: "list", "data-sp": "mt12" }, a.rules.map(e => ruleRow(e, name))) : h("p", { class: "meta", "data-sp": "mt8" }, `No rules of its own in ${S.profile.environment.title}.`),
    (a.carried || []).map(c => [h("p", { class: "meta", "data-sp": "mt10" }, `Taught to it as ${c.from}, before you named it:`), h("ul", { class: "list" }, c.rules.map(e => ruleRow(e, name)))]),
    h("form", { class: "addrule", "data-agent-rule": a.name, "data-sp": "mt14" },
      h("input", { class: "input", placeholder: `A rule for ${label(a.name)} only`, autocomplete: "off", "aria-label": `A rule for ${a.name}` }),
      h("button", { class: "btn", type: "submit" }, "Add")),
    h("form", { class: "addrule", "data-agent-label": a.name, "data-sp": "mt8" },
      h("input", { class: "input", placeholder: "A display name, if you like", value: a.label || "", autocomplete: "off", "aria-label": `A display name for ${a.name}` }),
      h("button", { class: "btn", type: "submit" }, "Name it")),
    h("div", { class: "links", "data-sp": "mt12" },
      h("button", { class: "link meta", type: "button", "data-do": "test-agent", "data-name": a.name }, "Try a message to it"),
      h("button", { class: "link meta", type: "button", "data-do": "layers-agent", "data-name": a.name }, "What it gets")));
}
export async function refreshLayers() {
  try { S.layers.card = await api(`/api/card?name=${enc(S.state.active)}&agent=${enc(S.layers.agent)}&form=${S.layers.form}`); }
  catch (e) { S.layers.card = { error: e.message }; }
  fill("layStack", layerStack()); fill("layCard", layerCard());
}
function layerStack() {
  const card = S.layers.card;
  const on = new Set(card && card.layers ? card.layers.flatMap(x => x.ids) : []);
  const a = S.agents.find(x => x.name === S.layers.agent);
  const agentRules = a ? [...(a.rules || []), ...(a.carried || []).flatMap(c => c.rules)] : [];
  const block = (title, rules, empty) => h("div", { class: "layer" },
    h("div", { class: "sechead" }, h("h2", { class: "label" }, title), h("span", { class: "meta" }, `${rules.filter(e => on.has(e.id)).length} of ${rules.length} on this card`)),
    rules.length ? h("ul", { class: "list" }, rules.map(e => h("li", { class: "line", "data-sp": on.has(e.id) ? null : "t3" },
      h("span", { class: "grow" }, e.statement, !on.has(e.id) ? h("span", { class: "meta" }, e.enabled === false ? "  ·  switched off" : S.layers.form === "relay" ? "  ·  not on the short card" : "  ·  left out by the size limit") : null))))
      : h("p", { class: "meta" }, empty));
  return [
    S.layers.agent ? block(`${label(S.layers.agent)} only`, agentRules, "No rules of its own here.") : null,
    block(`In ${S.profile.environment.title}`, live(S.profile.entries), "No rules of its own yet."),
    block("Everywhere", live(S.base.entries), "No shared rules.")];
}
function layerCard() {
  const c = S.layers.card;
  if (!c) return h("p", { class: "meta" }, "Building the card...");
  if (c.error) return h("p", { class: "meta warn" }, "The card could not be built: " + c.error);
  return [h("div", { class: "sechead" }, h("h2", { class: "label" }, "Exactly what it receives"), h("span", { class: "meta num" }, `${fmt(c.bytes)} of ${fmt(c.limit)} bytes`)),
    sizeBar(Math.min(100, Math.round(100 * c.bytes / c.limit))),
    c.left_out ? h("p", { class: "meta warn" }, `${plural(c.left_out, "rule")} would not fit the size limit, and would be left out with a line saying so.`) : null,
    h("pre", { class: "card" }, c.card)];
}
  VIEWS.agents = () => {
    const envs = S.state.profiles.filter(p => p.name !== "base"), list = allAgents(), many = list.length > 1 || envs.length > 1;
    return h("section", { class: "view", "data-part": "agents" },
      h("header", {}, h("h1", {}, "Agents"),
        h("p", { class: "sub" }, `${plural(list.length, "agent")} · ${plural(envs.length, "environment")}`)),
      many ? h("section", {}, h("div", { class: "sky map", id: "skyHost" }), spaceLegend()) : null,
      h("section", { class: "gap" }, h("ul", { class: "list" }, agentRows(list))),
      h("section", { class: "gap", id: "boardBox" }, boardView()),
      h("section", { class: "gap" },
        h("div", { class: "links" }, h("button", { class: "link", type: "button", "data-view": "layers" }, "What an agent gets")),
        h("details", { class: "gap" }, h("summary", {}, "Name an agent by its folder"),
          h("form", { class: "addrule", id: "bindForm" },
            h("input", { class: "input", name: "agent", placeholder: "A name, such as reviewer", autocomplete: "off", "aria-label": "The agent's name", "data-sp": "f220" }),
            h("input", { class: "input", name: "folder", placeholder: "Its folder, such as C:\\code\\app", autocomplete: "off", "aria-label": "The folder", "data-sp": "f260" }),
            h("button", { class: "btn primary", type: "submit" }, "Bind")),
          h("p", { class: "meta", "data-sp": "mt10 ch66" }, "Every agent working in that folder then has that name, and gets the rules you give it. A name an agent gives itself is only a claim."))));
  };

  VIEWS.layers = () => {
    const named = S.agents.filter(a => a.name !== "ai");
    return h("section", { class: "view", "data-part": "layers" },
      back("agents", "Agents"),
      h("header", {}, h("h1", {}, "What an agent gets"),
        h("p", { class: "sub" }, "Every card is built from layers: the rules shared everywhere, the environment's, and the agent's own, which never override the ones beneath.")),
      h("section", {}, h("div", { class: "row", "data-sp": "wrap" },
        h("select", { class: "input", id: "layAgent", "aria-label": "For" }, h("option", { value: "" }, "Any agent without rules of its own"),
          named.map(a => h("option", { value: a.name, selected: S.layers.agent === a.name ? "" : null }, label(a.name)))),
        h("div", { class: "seg", role: "group", "aria-label": "Whose words" },
          h("button", { type: "button", "data-form": "full", "aria-pressed": String(S.layers.form === "full") }, "Your words: the full card"),
          h("button", { type: "button", "data-form": "relay", "aria-pressed": String(S.layers.form === "relay") }, "Not yours: the short card")))),
      h("section", { class: "gap two" }, h("div", { id: "layStack" }, layerStack()), h("div", { id: "layCard" }, layerCard())));
  };
