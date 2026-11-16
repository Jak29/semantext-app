// Rules: see, add, switch and try them.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR, VIEWS } from "./ownbase.js";
import { skyLegend } from "./ownsky.js";
import { readMessage, adviceLine } from "./reader.js";
import { keep } from "./app.js";

const WRITTEN_BY = ["DEFAULT", "LEARNED", "PROPOSED", "SUGGESTED", "SETTING"];
const handWritten = (e) => !WRITTEN_BY.includes((e.provenance || {}).type);
export const SOURCE = (e) => {
  const p = e.provenance || {};
  return p.type === "LEARNED" ? "Your words" : p.type === "PROPOSED" ? `Proposed by ${p.by || "an agent"}, added by you`
    : p.type === "SUGGESTED" ? `Suggested${p.pack ? ": " + p.pack : ""}` : p.type === "SETTING" ? "A switch"
    : p.type === "DEFAULT" ? "Came with Semantext" : "Hand-written: its file records no provenance, so who wrote it is not known";
};
export function ruleDetail(e, prof, inPop) {
  const p = e.provenance || {};
  const added = when(p.when || p.added || p.proposed);
  const kind = Object.keys(RULE_FOR).find(k => RULE_FOR[k] === e.id), n = kind && S.metrics && S.metrics.noticed[kind];
  const kept = ((S.profile && S.profile.tests) || []).filter(t => (t.rules || []).includes(e.id));
  const short = (text, k) => { const v = String(text || "").split(/\s+/).join(" "); return v.length > k ? v.slice(0, k - 1) + "…" : v; };
  return h("div", { class: "detail" },
    h("p", { class: "meta" }, "When: ", e.always ? "always, on every card, even the short one" : e.applies_when || "whenever it fits"),
    h("p", { class: "meta" }, SOURCE(e), added ? `  ·  added ${added.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" })}` : "",
      e.relay && !e.always ? "  ·  also on the short card" : ""),
    p.type === "LEARNED" && p.words && p.words.trim() !== String(e.statement).trim() ? h("p", { class: "meta quote" }, `Your words: “${p.words}”`) : null,
    n ? h("p", { class: "meta" }, `${n.n} of your recent messages read this way, and this rule went with ${n.covered === n.n ? "every one" : n.covered + " of them"}.`) : null,
    kept.length ? h("p", { class: "meta" }, kept.length === 1 ? "Its test, the message your AI got wrong: " : `Its ${kept.length} tests: `,
      kept.slice(0, 2).map((t, i) => [i ? "; " : "", `“${short(t.message, 90)}”`]), kept.length > 2 ? `, and ${kept.length - 2} more` : "",
      ". Switching it off would let that misreading come back.") : null,
    h("div", { class: "row", "data-sp": "mt4" },
      inPop ? [h("button", { class: "switch", role: "switch", "aria-checked": String(e.enabled !== false), "aria-label": "On or off", "data-toggle": e.id, "data-prof": prof, type: "button" }),
        h("span", { class: "meta" }, e.enabled === false ? "Off: on no card" : "On")] : null,
      h("span", { class: "grow" }),
      p.type === "LEARNED" || p.type === "PROPOSED" ? h("button", { class: "link meta", type: "button", "data-remove": e.id, "data-prof": prof }, "Remove") : null));
}
export function ruleRow(e, prof) {
  const open = S.ruleOpen === e.id, mine = (e.provenance || {}).type === "LEARNED";
  return h("li", { class: "rule" + (e.enabled === false ? " off" : "") },
    h("div", { class: "line" },
      h("button", { class: "link st", type: "button", "data-rule": e.id, "aria-expanded": String(open), "data-sp": "plain" },
        mine ? h("span", { class: "mine", title: "Your own words" }) : null, e.statement,
        handWritten(e) ? h("span", { class: "meta", title: "Its file records no provenance" }, " (hand-written)") : null),
      h("button", { class: "switch", role: "switch", "aria-checked": String(e.enabled !== false), "aria-label": "On or off: " + String(e.statement).slice(0, 80), "data-toggle": e.id, "data-prof": prof, type: "button" })),
    open ? ruleDetail(e, prof, false) : null);
}
function ruleGroup(title, rules, prof, empty) {
  return h("div", { class: "gap" },
    h("div", { class: "sechead" }, h("h2", { class: "label" }, title), h("span", { class: "meta" }, plural(rules.length, "rule"))),
    rules.length ? h("ul", { class: "list" }, rules.map(e => ruleRow(e, prof))) : h("p", { class: "meta" }, empty));
}
export function ruleLists(env) {
  return [ruleGroup(`In ${S.profile.environment.title}`, env, S.state.active, "None of its own yet: it reads the shared rules. Add one above."),
    S.agents.filter(a => (a.rules || []).length).map(a => ruleGroup(`${label(a.name)} only`, a.rules, S.state.active, "")),
    ruleGroup("Everywhere", live(S.base.entries), "base", "None.")];
}
export async function loadIdeas() {
  try {
    const r = await api("/api/ideas?name=" + enc(S.state.active));
    fill("ideasList", [
      r.packs.map(p => [h("p", { class: "label", "data-sp": "mt16" }, p.title), h("ul", { class: "picks" }, p.rules.map(x => h("li", {}, h("label", {},
        h("input", { type: "checkbox", "data-idea": x.id, checked: x.held ? "" : null, disabled: x.held ? "" : null }),
        h("span", {}, x.statement, x.held ? h("span", { class: "meta" }, "  ·  already here") : null)))))]),
      h("div", { class: "actions", "data-sp": "start" }, h("button", { class: "btn", type: "button", "data-do": "add-ideas" }, "Add the ticked ones"))]);
  } catch (e) { fill("ideasList", h("p", { class: "meta" }, "The suggestions could not be loaded: " + e.message)); }
}

// ---------------------------------------------------------------- try a message
const ruleIndex = () => {
  const m = new Map();
  for (const e of live(S.base.entries)) m.set(e.id, e.statement);
  for (const e of live(S.profile.entries)) m.set(e.id, e.statement);
  for (const a of S.agents) for (const e of [...(a.rules || []), ...(a.carried || []).flatMap(c => c.rules)]) m.set(e.id, e.statement);
  return m;
};
// Try a message: the quick reading of /api/explain, and the reader's clause-by-clause reading with its advice for each
// act (reader.js, the same reader `semantext read` prints from). The two are asked together and fail apart: each says
// its own failure, and neither stands in for the other.
export async function tryMessage(message, words, agent, offer) {
  const mine = S.tryNo = (S.tryNo || 0) + 1;   // a slower, older try never replaces a newer one
  S.reader = { message, offer: offer || "", busy: true };
  S.offerBox = offer || "";   // R9: the box holds what was sent; the view and its input listener keep this as the box changes
  S.test = null;   // R4: the last quick reading is of other words; none is shown beside a new ask (a failed one leaves none, too)
  fill("testFlow", testFlow());
  const asked = readMessage(message, offer).then((data) => ({ message, offer: offer || "", data }),
    (e) => ({ message, offer: offer || "", err: String(e && e.message || e) }));
  let got = null, failed = null;
  try { got = fromTest(await api("/api/explain", { message, words: words || null, agent }), message, false); } catch (e) { failed = e; }
  const reader = await asked;
  if (mine !== S.tryNo) return;
  S.test = got;
  S.reader = reader;
  if (failed) toast(failed.message);
  fill("testFlow", testFlow());
}
const chip = (t, more) => h("span", { class: "chip" + (more ? " " + more : "") }, t);
// Each clause as a chip with the acts it names and any time word kept as written, then the advice for each act the
// words name. An ASK whose words appear to cover the act reads "your words appear to say go: confirm", never as a go.
export function clauseFlow() {
  const Q = S.reader;
  if (!Q) return null;
  const head = h("div", { class: "sechead" }, h("h2", { class: "label" }, "Clause by clause: what it asks for, act by act"));
  if (Q.busy) return h("section", { class: "gap" }, head, h("p", { class: "soft", role: "status" }, "Reading…"));
  if (Q.err) return h("section", { class: "gap" }, head, h("p", { class: "soft", role: "status" }, "Could not read it clause by clause: " + Q.err + ". No reading is shown."));
  const d = Q.data;
  const cut = d.clipped ? h("p", { class: "meta" }, `Read up to ${d.max_chars} characters; the rest was not read.`) : null;
  const odd = d.unreadable ? h("p", { class: "meta" }, "Some letters are outside the Latin script, which the reader cannot vouch for: no go is read from this message.") : null;
  const clauses = d.readings.length ? h("ul", { class: "clauses" }, d.readings.map(x => h("li", { class: "clause" },
    chip(x.label, "kind"), " ", x.acts.map(a => [chip(a), " "]), x.time ? [chip("“" + x.time + "”", "time"), " "] : null,
    h("span", { class: "soft" }, x.clause)))) : h("p", { class: "soft" }, "Nothing to read: the message is empty.");
  // R9: a bare yes answers the offer in the second box, so the advice made with an offer (the go-hint among it) is drawn only
  // while that offer is in the box. After the box is emptied or changed, or the view is drawn again (its box starts empty),
  // the advice is withdrawn and says why; the clauses, made from the message alone, stay.
  // R12: the advice sits in a slot of its own, so a keystroke in the offer box redraws only the slot (offerKeystroke), never the
  // view: the teach box's words and its open fold are not in it.
  return h("section", { class: "gap" }, head, cut, odd, clauses, adviceSlot(),
    h("p", { class: "meta", "data-sp": "mt12" }, "Advice only: it can make a gate stricter, never looser, and words alone never pass an act that leaves this machine, spends or deletes. The same reader as semantext read."));
}
// The offer this reading was made with is no longer the one in the box (R9).
const offerGone = (Q) => !!Q && !!Q.offer && String(S.offerBox || "") !== Q.offer;
function adviceNode(Q, gone) {
  const d = Q.data;
  return gone ? h("p", { class: "soft", role: "status" }, "The offer this was read with is no longer in the box, so the advice made from it is withdrawn. Put the offer back, or press Try it to read these words alone.")
    : d.advice.length ? h("div", { class: "advice" }, d.advice.map(a => h("div", { class: "advice-row" },
    h("div", {}, h("b", {}, a.act), "  ", chip(a.word, a.covers ? "covers" : ""), "  ", h("span", { class: "soft" }, adviceLine(a))),
    h("div", { class: "meta" }, `The rule: ${a.rule}` + (a.quote ? `  ·  “${a.quote}”` : ""))))) : h("p", { class: "soft" }, "The words name no act, so there is nothing to advise on.");
}
function adviceSlot() {
  const gone = offerGone(S.reader);
  return h("div", { class: "adviceslot", "data-slot": "advice", "data-gone": gone ? "1" : "0" }, adviceNode(S.reader, gone));
}
// R12: the offer box changed. Only the advice node is withdrawn or restored, and only when its state changes, through
// keep() (the focus, the caret, the scroll); the rest of the view, and what was typed in it, is not drawn again. A
// reading that is not drawn (busy, failed) has no slot, and nothing is done.
function offerKeystroke(flow, value) {
  S.offerBox = value;
  const slot = flow.querySelector('[data-slot="advice"]'), Q = S.reader;
  if (!slot || !Q || !Q.data) return;
  const gone = offerGone(Q);
  if (slot.getAttribute("data-gone") === (gone ? "1" : "0")) return;
  keep(() => { slot.setAttribute("data-gone", gone ? "1" : "0"); fill(slot, adviceNode(Q, gone)); });
}
export function testFlow() {
  const d = S.test;
  if (!d) return clauseFlow();
  const R = d.reading || { readings: [], decisions: [], touched: [] };
  const idx = ruleIndex();
  return [clauseFlow(),
    // R5: each reading says what it reads. This one is the whole message by cue words, as a kind; the other, above it, is
    // each clause by the act it names. Their sentences differ on purpose (a kind of message is not a go), and neither
    // speaks for both.
    h("section", { class: "gap" }, h("div", { class: "sechead" }, h("h2", { class: "label" }, "The quick reading: what kind of message this is")),
      h("p", { class: "meta" }, "How it is read, as a whole message, from cue words."),
      R.readings.length || R.decisions.length ? h("div", { class: "readings" },
        R.readings.map(x => h("div", {}, h("div", {}, h("b", {}, x.label), "  ", h("span", { class: "soft" }, x.says)), h("div", { class: "meta" }, "The rule: " + (idx.get(x.rule) || x.rule)))),
        R.decisions.map(x => h("div", { "data-sp": "ink" }, x.ask))) : h("p", { class: "soft" }, "No cue words: it is read as a plain message, with your whole card."),
      h("p", { class: "meta", "data-sp": "mt12" }, "This is Semantext's quick reading, from cue words. Your AI reads the message with the whole card.")),
    h("section", { class: "gap" }, h("div", { class: "sechead" }, h("h2", { class: "label" }, "What happens to it")), stepsView(d)),
    h("section", { class: "gap" }, h("details", {}, h("summary", {}, "Not read the way you meant?"),
      h("form", { class: "addrule", id: "teachFromTest" },
        h("input", { class: "input", name: "words", placeholder: "How it should have been read, as a rule", autocomplete: "off", "aria-label": "How this message should have been read, as a rule" }),
        h("button", { class: "btn primary", type: "submit" }, "Keep the rule")),
      h("p", { class: "meta", "data-sp": "mt10" }, "This message is kept beside the rule, as its test."))),
    h("section", { class: "gap" }, h("details", {}, h("summary", {}, "The card it would get"), h("pre", { class: "card" }, d.text)))];
}
  VIEWS.rules = () => {
    const env = live(S.profile.entries);
    const named = S.agents.filter(a => a.name !== "ai");
    return h("section", { class: "view", "data-part": "rules" },
      h("header", {}, h("h1", {}, "Rules"),
        h("p", { class: "sub" }, `What your agents follow in ${S.profile.environment.title}. The centre applies everywhere, and each ring out applies more narrowly.`)),
      h("section", {}, h("div", { class: "sky", id: "ruleSky" }), skyLegend()),
      h("section", { class: "gap" },
        h("form", { class: "addrule", id: "addRule" },
          h("input", { class: "input", name: "words", placeholder: "A rule in your own words, such as: Always answer in one line.", autocomplete: "off", "aria-label": "A new rule, in your own words" }),
          named.length ? h("select", { class: "input", name: "scope", "aria-label": "Who it is for" }, h("option", { value: "" }, "Every agent"),
            named.map(a => h("option", { value: a.name }, `${label(a.name)} only`))) : null,
          h("button", { class: "btn primary", type: "submit" }, "Add")),
        h("div", { id: "ruleLists" }, ruleLists(env))),
      h("section", { class: "gap" },
        h("div", { class: "links" },
          h("button", { class: "link", type: "button", "data-view": "test" }, "Try a message"),
          h("button", { class: "link", type: "button", "data-do": "editor" }, "Edit the file"),
          S.state.log.length ? h("button", { class: "link", type: "button", "data-do": "undo-last" }, "Undo the last change") : null),
        h("details", { id: "ideasBox", class: "gap", open: S.ideasOpen ? "" : null },
          h("summary", {}, "Add suggested rules"), h("div", { id: "ideasList" }, h("p", { class: "meta" }, "Looking...")))));
  };

  VIEWS.test = () => {
    S.offerBox = "";   // R9: this view draws its offer box empty
    const offerBox = h("input", { class: "input", name: "offer", "data-sp": "mt12", autocomplete: "off", spellcheck: "false",
      placeholder: "The agent's last offer, if this answers one, such as: Shall I publish the release?", "aria-label": "The agent's last offer, if this message answers one" });
    const flow = h("div", { id: "testFlow" }, testFlow());
    // The advice is withdrawn at once when the box changes, so a hint made from an offer is never beside other words. Only
    // the advice node is touched (R12); a whole redraw of the flow wiped the teach box and closed its fold.
    offerBox.addEventListener("input", () => offerKeystroke(flow, offerBox.value.trim()));
    return h("section", { class: "view", "data-part": "test" },
    back("rules", "Rules"),
    h("header", {}, h("h1", {}, "Try a message"), h("p", { class: "sub" }, "See how one message would be read, and which rules would go with it. Nothing is saved.")),
    h("section", {}, h("form", { id: "testForm" },
      h("textarea", { class: "input", name: "message", rows: "3", placeholder: "Could we maybe publish it tomorrow?", "aria-label": "The message to try" }, S.test ? S.test.message : S.reader ? S.reader.message : ""),
      h("div", { class: "row", "data-sp": "mt12 wrap" },
        h("select", { class: "input", name: "words", "aria-label": "Whose words" },
          [["", "Whose words: tell from the text"], ["own", "Mine"], ["agent", "Another agent's"], ["tool", "A tool's notice"]].map(([v, t]) => h("option", { value: v }, t))),
        h("select", { class: "input", name: "agent", "aria-label": "Sent to" }, h("option", { value: "" }, "Sent to: an unnamed agent"),
          S.agents.filter(a => a.name !== "ai").map(a => h("option", { value: a.name, selected: S.testAgent === a.name ? "" : null }, label(a.name)))),
        h("span", { class: "grow" }),
        h("button", { class: "btn primary", type: "submit" }, "Try it")),
      offerBox)),
    flow);
  };
