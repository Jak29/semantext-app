// A card, as your inbox shows it: shared by Waiting, Projects and the drawers.
import { $, h } from "./dom.js";
import { day, plural, when } from "./words.js";
import { disclosure } from "./parts.js";
import { S, fill, load } from "./app.js";
import { goCard } from "./waiting.js";
import { openDrawer } from "./drawers.js";

// ---------------------------------------------------------------- the card, as your inbox shows it
export function toast(text) {
  const t = $("toast");
  t.textContent = text;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
}

export async function copyId(button) {
  const id = button.dataset.id;
  try {
    await navigator.clipboard.writeText(id);
    button.textContent = "Copied";
  } catch (e) {
    // If the clipboard is refused, the ID is selected so Ctrl+C copies it.
    const range = document.createRange();
    range.selectNodeContents(button);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
    toast("Press Ctrl+C to copy " + id);
  }
  setTimeout(() => { button.textContent = id; }, 1500);
}

export function chip(text, cls) { return h("span", { class: "chip " + cls }, text); }

export function agentChip(name, id, k) {
  return h("button", { class: "chip seat", type: "button", "data-k": k || null, title: "Open " + name,
    on: { click: (ev) => openDrawer("agent", id ? { id } : { name }, ev.currentTarget) } }, name);
}

export function runLine(run) {
  if (!run.finished) return h("p", { class: "status" }, "Started " + when(run.started) + ", and no result was recorded.");
  if (run.timed_out) return h("p", { class: "status bad" }, "Stopped after 30 minutes, " + when(run.finished) + ".");
  if (run.exit === 0) return h("p", { class: "status" }, "Ran " + when(run.finished) + ", and finished cleanly.");
  return h("p", { class: "status bad" }, "Ran " + when(run.finished) + ", and failed (exit " + (run.exit ?? "unknown") + ").");
}

// Park and Bring back: a link that opens the card in your inbox, where your own press is the only thing that writes.
// It carries a seat and a card's id and nothing else, held here to the inbox's own form (its link.rs), or it is not drawn.
const LINK_SEAT = /^[A-Za-z][A-Za-z0-9_-]{0,31}$/, LINK_ID = /^[A-Za-z]-[0-9]{8}-[0-9]{6}(-[0-9]{1,3})?$/;
export function cardLink(seat, id) {
  return typeof seat === "string" && typeof id === "string" && LINK_SEAT.test(seat) && LINK_ID.test(id)
    ? "jak-inbox://card/" + seat + "/" + id : null;
}
export function parkNode(c, parked) {
  if (!(S.frame && S.frame.inbox_app === true)) return null;   // no inbox app named in your settings: no dead link
  const url = cardLink(c.seat, c.id);
  const word = parked ? "Bring back" : "Park";
  if (!url) return h("span", { class: "meta" }, word + " from your inbox.");
  return h("a", { class: "inbox-link", href: url, "data-k": "park:" + c.key,
    title: "Opens this card in your inbox, and does nothing else: your press there is what " + (parked ? "brings it back" : "parks it") }, word + " in your inbox");
}

// A request in your own inbox is answered here, through the same guarded route as the home page. One press, one answer;
// the server keeps it, and refuses a second. A question with no options is answered in your own words on the home page.
export const answers = { post: (body) => fetch("/api/answer", { method: "POST", cache: "no-store",
  headers: { "X-Semantext": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) }), said: {} };
export async function answerRequest(c, choice) {
  let r = null, got = {};
  try {
    r = await answers.post({ id: c.number, choice });
    try { got = await r.json(); } catch (e) { /* the status says enough */ }
  } catch (e) { got = { error: "the page could not reach Semantext" }; }
  answers.said[c.key] = r && r.ok ? null : (got.error || "That answer was not taken.");
  if (r && r.ok) await load("waiting");
  fill();
}
export function answerNode(c) {
  const box = h("div", { class: "answers", "data-k": "answer:" + c.key });
  if ((c.choices || []).length) {
    box.append(...c.choices.map((x) => h("button", { type: "button", class: "answer", "data-k": "answer:" + c.key + ":" + x.choice,
      on: { click: () => answerRequest(c, x.choice) } }, x.label)));
  } else box.append(h("a", { href: "/" }, "Answer in your own words on the home page"));
  if (answers.said[c.key]) box.append(h("p", { class: "refused", role: "alert" }, answers.said[c.key]));
  return box;
}

export function cardNode(c) {
  const waiting = c.state === "waiting", parked = c.state === "parked", done = c.state === "closed" || c.state === "run";
  const node = h("article", { class: "card " + (waiting ? "is-waiting" : parked ? "is-parked" : "is-done"), "data-card": c.key,
    "data-k": "card:" + c.key, tabindex: "-1" });
  const id = h("button", { class: "id", type: "button", title: "Copy this ID", "data-id": c.id, "data-k": "id:" + c.key,
    on: { click: (ev) => copyId(ev.currentTarget) } }, c.id);
  const at = h("time", { class: "at", datetime: c.at || null }, when(c.at));
  const kindWord = c.kind === "command" ? "Command" : c.kind === "change" ? (c.change && c.change.prune ? "Prune" : "Change") : "Decision";
  node.append(h("div", { class: "card-head" }, agentChip(c.seat, null, "seat:" + c.key), chip(kindWord, "kind"), id, at));
  node.append(h("h2", { class: "card-title" }, c.title), h("p", { class: "why" }, c.why));
  if (c.kind === "change" && c.change) {
    changeBody(c, node);
    // A change is a record, not an ask: the decision cards that ask about it are linked, and nothing runs from here.
    node.append(h("p", { class: "where" }, (c.asked_in || []).length
      ? ["Asked in ", c.asked_in.map((k, i) => [i ? ", " : "", h("button", { class: "link mono", type: "button", "data-k": "asked:" + c.key + ":" + k,
        on: { click: () => { S.open.add("shelf:done"); S.open.add("shelf:parked"); goCard(k); } } }, k.split("/").slice(1).join("/"))]), c.decided ? "; that card is closed, or an outcome is recorded (both are lines in the agent's own files)." : ". Nothing proposed runs before your word."]
      : "No decision card asks about it yet, so it waits for nothing."));
    for (const note of c.notes || []) node.append(h("p", { class: "refused" }, note));
    return node;
  } else if (c.kind === "command") {
    const facts = h("dl", { class: "facts" });
    if (c.does) facts.append(h("dt", null, "What it does"), h("dd", null, c.does));
    if (c.undo) facts.append(h("dt", null, "Undo"), h("dd", null, c.undo));
    if (c.cwd) facts.append(h("dt", null, "Runs in"), h("dd", { class: "mono" }, c.cwd));
    if (facts.childNodes.length) node.append(facts);
    node.append(h("pre", { class: "command" }, c.command || ""));
    if (c.run) node.append(runLine(c.run));
    const out = outputBox(c);
    if (out) node.append(out);
    if (!c.run && waiting) node.append(h("p", { class: "where", title: "This page never runs anything." }, c.own_inbox ? "Run it yourself, then say how it went:" : "Run it from your inbox app if you use one, or a terminal. ", parkNode(c, false)));
    if (c.own_inbox && waiting) node.append(answerNode(c));
  } else {
    if (c.question) node.append(h("p", { class: "question" }, c.question));
    if (c.options && c.options.length && !(c.own_inbox && waiting)) node.append(h("ol", { class: "options" }, c.options.map((o) => h("li", null, o))));
    if (c.change_id) {
      const target = c.seat + "/" + c.change_id;
      node.append(h("p", { class: "where" }, "It asks about the proposed change ", h("button", { class: "link mono", type: "button", "data-k": "about:" + c.key,
        on: { click: () => { S.open.add("shelf:changes"); goCard(target); } } }, c.change_id), "."));
    }
    if (waiting && c.own_inbox) node.append(answerNode(c));
    else if (waiting) node.append(h("p", { class: "where" }, "Answer in " + c.seat + "'s chat: paste the ID, then your decision. ", parkNode(c, false)));
  }
  for (const note of c.notes || []) node.append(h("p", { class: "refused" }, note));
  if (c.closing) node.append(h("p", { class: "closed" }, "Closed " + when(c.closing.at) + (c.closing.how ? ": " + c.closing.how : ".")));
  if (parked) node.append(h("p", { class: "park" }, "Parked " + when(c.parked_at) + ". " + c.seat + " holds it until you bring it back. ", parkNode(c, true)));
  node.append(cardMore(c));
  return node;
}

// A proposed change, as one card you can judge: what it changes and why, what it should move, what it risks, whether
// its evidence is still today's, and how to undo it. The undo is shown as data; this page never performs it.
const DIR = { up: "up", down: "down" };
export function changeBody(c, node) {
  const ch = c.change;
  node.append(h("p", { class: "question" }, ch.hypothesis || ""));
  const facts = h("dl", { class: "facts" });
  const add = (k, v) => { if (v !== null && v !== undefined && v !== "") facts.append(h("dt", null, k), h("dd", null, v)); };
  add("Changes", ch.component);
  if (ch.predicted && ch.predicted.length) {
    add("Should move", h("ul", { class: "options" }, ch.predicted.map((p) => h("li", null, p.measure
      + (p.direction ? " " + DIR[p.direction] : "") + (p.p !== null && p.p !== undefined ? " (chance stated " + Math.round(p.p * 100) + "%)" : "")))));
  } else add("Should move", h("span", { class: "bad" }, "no measure named, so its effect cannot be checked"));
  add("Risk", ch.regression_risk);
  const w = ch.what_changes;
  if (w) {
    const parts = [w.added.length ? plural(w.added.length, "file") + " added" : null, w.removed.length ? plural(w.removed.length, "file") + " removed" : null,
      w.changed.length ? plural(w.changed.length, "file") + " changed" : null].filter(Boolean);
    add("What changes", (parts.join(", ") || "no file") + "; always-on text " + (w.always_on_char_delta > 0 ? "+" : w.always_on_char_delta < 0 ? "−" : "±")
      + Math.abs(w.always_on_char_delta) + " characters");
  }
  const f = ch.freshness;
  if (f) {
    add("Evidence", h("span", { class: f.state === "current" ? "soft" : "bad", title: f.why || (f.state === "stale" ? "Today's digest " + f.today + " is not the card's " + f.digest : "") },
      f.state === "current" ? "current: the files it was measured on are unchanged"
        : f.state === "stale" ? "stale: the files it was measured on have changed since"
          : "unknown: " + (f.why || "it cannot be checked")));
  }
  if (ch.undo) add("Undo", h("span", { class: "mono" }, ch.undo.commit ? "back to commit " + ch.undo.commit : "restore " + ch.undo.restore + (ch.undo.from ? " from " + ch.undo.from : "")));
  else add("Undo", h("span", { class: "bad" }, "none given"));
  node.append(facts);
  const more = disclosure("proposal:" + c.key, "How it was reasoned", "more");
  const dl = h("dl", { class: "facts" });
  for (const [k, v] of [["Trigger", ch.trigger], ["Why not smaller", ch.why_not_smaller], ["Retroactive check", ch.retroactive_check]]) if (v) dl.append(h("dt", null, k), h("dd", null, v));
  if (w) for (const [k, list] of [["Added", w.added], ["Removed", w.removed], ["Changed", w.changed]]) if (list.length) dl.append(h("dt", null, k), h("dd", { class: "mono" }, list.join(", ")));
  if (ch.evidence && ch.evidence.files.length) dl.append(h("dt", null, "Measured on"), h("dd", { class: "mono" }, ch.evidence.files.join(", ")));
  more.append(dl.childNodes.length ? dl : h("p", { class: "meta" }, "The card gives no more."));
  node.append(more);
  for (const o of c.outcomes || []) {
    node.append(h("p", { class: o.undone ? "status bad" : "status" }, (o.undone ? "Undone " : "Outcome recorded ") + when(o.at)
      + (Object.keys(o.moved || {}).length ? ": " + Object.entries(o.moved).map(([m, d]) => m + " " + d).join(", ") : "")
      + (o.regressions && o.regressions.length ? "; regressions: " + o.regressions.join("; ") : "") + "."));
  }
  const j = c.judged;
  if (j) {
    const hits = j.measures.filter((m) => m.hit === true).length, judged = j.measures.filter((m) => m.hit !== null).length;
    node.append(h("p", { class: "status" }, "Against its prediction: " + hits + " of " + plural(judged, "measured prediction") + " held, of " + j.measures.length + " made"
      + (j.unpredicted_regressions.length ? "; " + plural(j.unpredicted_regressions.length, "regression") + " nobody predicted" : "") + "."));
  }
}

// An agent's Brier score, never without both counts: n scored of m predicted, the coin's 0.25 beside it, and an
// interval only from ten scored.
export function brierWords(s) {
  const m = s.predicted === undefined ? s.scored : s.predicted;
  const rest = [["left out of its outcome", s.left_out], ["awaiting an outcome", s.awaiting], ["unusable", s.unusable]]
    .filter(([, n]) => n).map(([w, n]) => n + " " + w);
  const counts = s.scored + " scored of " + plural(m, "prediction") + " made" + (rest.length ? " (" + rest.join(", ") + ")" : "");
  if (s.brier === null) return "no prediction scored yet (" + counts + ")";
  const changes = plural(s.changes_scored || 0, "change");
  return "Brier " + s.brier.toFixed(2) + " (0 is perfect; a coin scores " + (s.coin === null || s.coin === undefined ? "0.25" : s.coin.toFixed(2)) + "), " + counts
    + (s.interval ? "; per change " + s.brier_by_change.toFixed(2) + ", 95% bound " + s.interval[0].toFixed(2) + " to " + s.interval[1].toFixed(2) + " over " + changes
      : "; " + changes + ", " + (s.interval_note || "too few to state an interval"));
}

// A run's output, as your inbox shows it under Done: stdout and stderr as text, behind one click.
export function outputBox(c) {
  const o = c.output;
  if (!o) return null;
  const out = String(o.stdout || "").trim(), err = String(o.stderr || "").trim();
  if (!out && !err) return null;
  const d = disclosure("output:" + c.key, "Output", "output");
  if (out) d.append(h("pre", { class: "command out" }, out));
  if (o.stdout_cut) d.append(h("p", { class: "meta" }, "and " + o.stdout_cut + " more characters of stdout, not shown here"));
  if (err) d.append(h("pre", { class: "command err" }, err));
  if (o.stderr_cut) d.append(h("p", { class: "meta" }, "and " + o.stderr_cut + " more characters of stderr, not shown here"));
  return d;
}

// What this page adds under a card, behind one click so the card stays as short as your inbox's: who asks and who
// acts, its project, and your earlier words. The line says how many earlier words there are, so they are never hidden
// without a sign.
export function cardMore(c) {
  const n = (c.earlier || []).length;
  const d = disclosure("more:" + c.key, (n ? "Your earlier words (" + n + ") · " : "") + "Asks, acts" + (c.project ? ", project" : ""), "more");
  const who = h("p", { class: "who" },
    h("span", { class: "tip", title: "How the page knows: " + (c.asks_basis || "not said") }, "Asks: " + c.asks),
    "·", h("span", { class: "tip", title: "How the page knows: " + (c.acts_basis || "not said") }, "Acts: " + c.acts));
  if (c.project) {
    const why = c.project.via === "cwd" ? "it runs in this project's folder" : "its " + (c.project.field || "words") + " name this project's folder";
    who.append("·", h("a", { class: "chip", href: "#projects/" + encodeURIComponent(c.project.id), title: "In this project because " + why,
      "data-k": "proj:" + c.key }, c.project.name || "a project"));
  }
  const body = h("div", { class: "more-body" }, who);
  for (const e of c.earlier || []) {
    body.append(h("div", { class: "said" },
      h("p", { class: "meta" }, h("a", { href: "#record/" + encodeURIComponent(e.id), class: "mono" }, e.id),
        " · " + day(e.date) + " · " + (e.status || "no status") + " · " + e.link),
      h("blockquote", { class: "words" }, e.words || "(no words recorded)")));
  }
  d.append(body);
  return d;
}
