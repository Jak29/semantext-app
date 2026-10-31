// Today: is it working, and what it did.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR, VIEWS } from "./ownbase.js";
import { S as PAGE } from "./app.js";

// What waits is what Waiting shows, whichever inbox it comes from: one answer on the whole page.
const waitingNow = () => (PAGE.frame && PAGE.frame.waiting) || 0;
function connected() {
  const c = (S.state && S.state.connections) || {};
  return !!(c.claude_code || (c.files || []).some(f => f.ok) || S.feed.records.length);
}
export function heroNodes() {
  const rs = S.feed.records;
  const today = rs.filter(r => { const d = when(r.at); return d && d.toDateString() === new Date().toDateString(); });
  const mine = today.filter(r => r.words === "own").length, agents = new Set(today.filter(r => r.words === "own").map(r => r.agent)).size;
  const wait = waitingNow(), liveNow = rs.length && Date.now() - when(rs[0].at) < 120000;
  let title, sub;
  if (!S.feed.on) { title = "Your rules go with every message"; sub = "The feed is off, so nothing shows here. It can be switched on in Settings."; }
  else if (!connected()) { title = "Connect your AI"; sub = "Then every message you send it carries your rules."; }
  else {
    title = wait ? (wait === 1 ? "One decision needs you" : `${wait} decisions need you`) : "Working";
    sub = mine ? `Your rules went with ${plural(mine, "message")} of yours today${agents > 1 ? `, to ${agents} agents` : ""}.`
      : rs.length ? `Quiet today. The last message was ${ago(rs[0].at)}.` : "Your next message to your AI shows here.";
  }
  return [h("h1", {}, title), h("p", { class: "sub" }, liveNow ? h("span", { class: "live", title: "A card went out in the last two minutes" }) : null, sub)];
}
const minutes = (m) => m < 1 ? "a minute" : m < 90 ? `${Math.round(m)} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} days`;
function allCounts(m) {
  const N = m.noticed || {}, out = [];
  // What was sent with them, never what an agent then did: that is the agent's, reading the whole card.
  const missed = (x) => x.covered < x.n ? `${x.n - x.covered} went without it` : "";
  const cut = [m.cards.cut ? `${m.cards.cut} cut by the size limit` : "", m.cards.base_only ? `${m.cards.base_only} with the base rules only` : ""].filter(Boolean).join(", ");
  if (m.messages.own) out.push({ n: m.messages.own, t: m.messages.own === 1 ? "message of yours carried your rules" : "messages of yours carried your rules", warn: cut });
  if (N["needs-word"]) out.push({ n: N["needs-word"].n, t: N["needs-word"].n === 1 ? "risky ask, sent with the rule to wait for you" : "risky asks, each sent with the rule to wait for you", warn: missed(N["needs-word"]) });
  if (m.others.n) out.push({ n: m.others.n, t: m.others.n === 1 ? "message from another agent, marked not yours" : "messages from other agents, marked not yours",
    warn: m.others.claims_you ? `${m.others.claims_you} claimed to be you` : "" });
  if (N.question) out.push({ n: N.question.n, t: N.question.n === 1 ? "question, sent with the rule for questions" : "questions, each sent with the rule for questions", warn: missed(N.question) });
  if (N.suggestion) out.push({ n: N.suggestion.n, t: N.suggestion.n === 1 ? "maybe, sent with the rule for maybes" : "maybes, each sent with the rule for maybes", warn: missed(N.suggestion) });
  if (m.decisions.answered) out.push({ n: m.decisions.answered, t: m.decisions.answered === 1 ? "decision you answered" : "decisions you answered",
    note: [m.decisions.median_minutes !== null ? `half within ${minutes(m.decisions.median_minutes)}` : "", m.decisions.via.chat ? `${m.decisions.via.chat} typed in chat` : ""].filter(Boolean).join(", ") });
  if (m.rules.cases) out.push({ n: m.rules.cases, t: m.rules.cases === 1 ? "correction kept as a test" : "corrections kept as tests",
    warn: m.rules.covered < m.rules.cases ? `${m.rules.cases - m.rules.covered} no longer covered` : "" });
  const added = m.rules.yours + m.rules.proposed;
  if (added) out.push({ n: added, t: `${added === 1 ? "rule" : "rules"} you added to ${envTitle(S.state.active)}` });
  return out;
}
export function countsView() {
  const m = S.metrics;
  if (!m || (!m.window.records && !m.decisions.asked)) return null;
  const all = allCounts(m);
  if (!all.length) return null;
  // How far back the feed reaches, as a span rather than a date, so the line reads the same whenever it is read.
  const since = when(m.window.since), days = since ? Math.max(1, Math.ceil((Date.now() - since) / 86400000)) : 0;
  const top = all.slice(0, 3), rest = all.slice(3);
  return h("section", { class: "gap" },
    h("div", { class: "sechead" }, h("h2", { class: "label" }, "What it did"), days ? h("span", { class: "meta" }, days === 1 ? "last day" : `last ${days} days`) : null),
    h("div", { class: "stats" }, top.map(x => h("div", { class: "stat" }, h("div", { class: "n" }, fmt(x.n)), h("div", { class: "meta" }, x.t),
      x.warn ? h("div", { class: "meta warn" }, x.warn) : null))),
    h("details", { class: "allcounts" }, h("summary", { class: "meta" }, rest.length ? "All counts, and how they are counted" : "How these are counted"),
      rest.length ? h("div", { class: "tally" }, rest.map(x => [h("span", { class: "n" }, fmt(x.n)),
        h("span", {}, x.t, x.note ? h("span", { class: "meta" }, "  ·  " + x.note) : null, x.warn ? h("span", { class: "meta warn" }, "  ·  " + x.warn) : null)])) : null,
      h("p", { class: "meta", "data-sp": "mt12 ch66" }, `From Semantext's own records, never from what was said: the last ${plural(m.window.records, "message")} it handed a card to, and every decision. A count says what went with a message, not what the agent then did.`)));
}
// What just happened, one line each: the agent, what kind of message, how many rules went with it.
const KIND_WORDS = [["needs-word", "an ask that needs your word"], ["answer", "your answer"], ["correction", "your correction"],
  ["question", "your question"], ["suggestion", "your maybe"], ["pause", "your pause"], ["yes", "your yes"]];
function whatOf(r) {
  const n = r.layers.reduce((k, x) => k + x.ids.length, 0);
  const got = r.form === "full" ? `all ${n} rules` : `${n} safety rules`;
  const kind = (KIND_WORDS.find(([k]) => (r.noticed || []).includes(k)) || [null, "your message"])[1];
  if (r.words === "own") return `${kind}  ·  ${got}`;
  if (r.words === "tool") return `a tool's notice  ·  ${got}`;
  return claimsYou(r.from) ? `claims to be you, so treated as passed on  ·  ${got}` : `passed on${r.from ? " by " + label(r.from) : ""}  ·  ${got}`;
}
export function recentRows() {
  const rs = S.feed.records.slice(0, 5);
  if (!rs.length) return h("li", { class: "empty" }, S.feed.on ? "Nothing yet. Each message to your agents shows here." : "The feed is off.");
  return rs.map(r => {
    const open = S.expanded === r.at;
    return h("li", {},
      h("button", { class: "line", type: "button", "data-explain": r.at, "aria-expanded": String(open) },
        h("span", { class: "who" }, label(r.agent)),
        h("span", { class: "what" + (claimsYou(r.from) && r.words === "agent" ? " warn" : "") }, whatOf(r)),
        h("span", { class: "when meta" }, ago(r.at)),
        h("span", { class: "chev", "aria-hidden": "true" }, open ? "–" : "+")),
      open ? h("div", { class: "opened" }, stepsView(fromRecord(r))) : null);
  });
}
// The first time: three steps, in order, and nothing else.
function startHere() {
  const c = (S.state && S.state.connections) || {};
  return h("section", {}, h("ol", { class: "start" },
    h("li", {}, h("b", {}, "Connect your AI"), h("span", { class: "meta" }, c.claude_code ? "Claude Code is connected." : "For Claude Code, run this once in a terminal."),
      c.claude_code ? h("span", { class: "meta" }, "Done") : copyBtn("semantext install claude-code --apply")),
    h("li", {}, h("b", {}, "Check your rules"), h("span", { class: "meta" }, `${plural(live(S.base.entries).length, "starter rule")} are on.`),
      h("button", { class: "btn small", type: "button", "data-view": "rules" }, "See them")),
    h("li", {}, h("b", {}, "Talk to your AI"), h("span", { class: "meta" }, "Your next message shows here."))));
}
export function historyRows() {
  const rs = S.feed.records.slice(0, 100);
  if (!rs.length) return h("tr", {}, h("td", { colspan: "6", class: "empty" }, S.feed.on ? "No messages yet." : "The feed is off."));
  return rs.map(r => {
    const sel = S.expanded === r.at;
    return [h("tr", { class: "pick", "data-at": r.at, "aria-selected": String(sel), tabindex: "0" },
      h("td", { class: "num soft" }, clock(r.at)),
      h("td", {}, label(r.agent)),
      h("td", { class: claimsYou(r.from) && r.words === "agent" ? "warn" : "soft" }, claimsYou(r.from) && r.words === "agent" ? "Claims to be you" : WORDS[r.words]),
      h("td", { class: "soft" }, (r.form === "full" ? "Full" : "Short") + " · " + envTitle(r.environment), r.problem ? h("span", { class: "warn" }, " · a file is broken") : null),
      h("td", { class: "num soft" }, `${count(r, "base")} · ${count(r, "environment")} · ${count(r, "agent")}`),
      h("td", { class: "num soft" }, fmt(r.bytes), r.left_out ? h("span", { class: "warn" }, ` · ${r.left_out} left out`) : null)),
      sel ? h("tr", {}, h("td", { colspan: "6", "data-sp": "opened-cell" }, stepsView(fromRecord(r)))) : null];
  });
}
export function needsYou() {
  const n = waitingNow();
  if (!n) return null;
  return h("p", { class: "gap" }, h("a", { href: "#waiting" }, n === 1 ? "One decision is waiting for you" : `${n} decisions are waiting for you`));
}
  VIEWS.today = () => h("section", { class: "view", "data-part": "today" },
    h("header", { id: "hero" }, heroNodes()),
    S.feed.on && !connected() ? startHere() : [
      h("div", { id: "needs" }, needsYou()),
      h("div", { id: "counts" }, countsView()),
      h("section", { class: "gap" },
        h("div", { class: "sechead" }, h("h2", { class: "label" }, "Recent"),
          S.feed.records.length > 5 ? h("button", { class: "link meta", type: "button", "data-view": "history" }, "Every message") : null),
        h("ul", { class: "list", id: "recent" }, recentRows()))]);

  VIEWS.history = () => h("section", { class: "view", "data-part": "history" },
    back("today", "Today"),
    h("header", {}, h("h1", {}, "Every message"), h("p", { class: "sub" }, "One row per message, newest first. What was said is never kept. Select a row for its five steps.")),
    h("section", {}, h("div", { class: "tablewrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Time", "Who asked", "Whose words", "Card", "Rules: everywhere · environment · agent", "Bytes"].map(t => h("th", { scope: "col" }, t)))),
      h("tbody", { id: "historyRows" }, historyRows())))));
