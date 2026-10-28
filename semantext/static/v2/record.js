// The Record: your register's decisions, by thread, then by decision, then at the source.
import { h } from "./dom.js";
import { cap, day, plural } from "./words.js";
import { crumbs, header } from "./parts.js";
import { fill, S } from "./app.js";

// ---------------------------------------------------------------- the Record
export const R = {};

export function mount(el) {
  R.head = h("div");
  R.search = h("input", { class: "input search", type: "search", placeholder: "Search your words", "aria-label": "Search your words",
    value: S.q.record, "data-k": "search:record" });
  R.search.addEventListener("input", () => { S.q.record = R.search.value; fill(); });
  R.facets = h("div", { class: "seg", role: "group", "aria-label": "Status" });
  R.tools = h("div", { class: "tools" }, R.search, R.facets);
  R.list = h("div");
  R.empty = h("p", { class: "empty", hidden: true });
  el.replaceChildren(R.head, R.tools, R.list, R.empty);
}

// The Record zooms: threads by subject, then a thread's decisions, then one decision at its source (your words whole,
// the offer you accepted, and where they were first written down, as the register pins them). The register stays the
// authority; nothing here is a summary. Search reads your own words (and the offers and quotes you were given), not the
// scribe's readings.
export function entryText(e) {
  return [e.id, e.subject, e.words, e.offer, ...(e.notes || []).map((n) => n.quote)].filter((x) => typeof x === "string").join("\n").toLowerCase();
}

export function statusWord(s) { return h("span", { class: "state-word" + (s === "superseded" || s === "parked" ? " quiet" : "") }, s || "no status"); }

const utf8 = (s) => new TextEncoder().encode(String(s || ""));
// Words that fit in 512 bytes are shown whole. Longer words are shown up to that, cut at a character, with how much
// is left and where it is whole: never summarised.
export function wordsNode(text, limit, whole) {
  const s = typeof text === "string" ? text : text === null || text === undefined ? "" : JSON.stringify(text);
  if (!s) return h("blockquote", { class: "words" }, "(no words recorded)");
  const bytes = utf8(s);
  if (bytes.length <= limit) return h("blockquote", { class: "words" }, s);
  let cut = new TextDecoder("utf-8", { fatal: false }).decode(bytes.slice(0, limit)).replace(/�+$/, "");
  return h("div", null, h("blockquote", { class: "words" }, cut + "…"),
    h("p", { class: "meta" }, (bytes.length - utf8(cut).length) + " more bytes, not shown here. ", whole ? h("a", { href: whole }, "Read them whole at the source") : null));
}

export const recordHref = (id) => "#record/" + encodeURIComponent(id);
export const recordLinks = (ids) => ids.map((id, i) => [i ? ", " : "", h("a", { href: recordHref(id) }, id)]);

// A decision in its thread: its id, date and status, your words (whole up to 512 bytes), and what superseded it.
export function entryNode(e, limit, withSubject) {
  const node = h("div", { class: "entry", "data-entry": e.id, "data-k": "entry:" + e.id, tabindex: "-1" });
  if (withSubject) node.append(h("p", { class: "subject" }, e.subject || "(no subject)"));
  const stored = e.stored_status && e.stored_status !== e.computed_status ? " (stored as " + e.stored_status + ")" : "";
  node.append(h("p", { class: "meta" }, h("a", { class: "mono", href: recordHref(e.id), title: "Open it at its source" }, e.id), " · " + day(e.date) + " · ",
    statusWord(e.computed_status), stored + (e.to ? " · to " + e.to : "")));
  node.append(wordsNode(e.words, limit, e.id ? recordHref(e.id) : null));
  const rel = h("p", { class: "rel" });
  if (e.superseded_by && e.superseded_by.length) rel.append(h("span", { class: "bad" }, "Superseded by ", recordLinks(e.superseded_by)));
  if (e.supersedes && e.supersedes.length) rel.append(h("span", null, "Supersedes ", recordLinks(e.supersedes)));
  if (rel.childNodes.length) node.append(rel);
  return node;
}

// One decision at its source: everything the register holds for it, each labelled with whose words it is.
export function sourceNode(e, byId) {
  const parts = [];
  const facts = h("dl", { class: "facts" });
  const add = (k, v, cls) => { if (v !== null && v !== undefined && v !== "") facts.append(h("dt", null, k), h("dd", { class: cls || null }, v)); };
  add("Status", [statusWord(e.computed_status), e.stored_status && e.stored_status !== e.computed_status ? " (stored as " + e.stored_status + ")" : ""]);
  add("Date", e.date ? day(e.date) + (e.time ? " · " + e.time + " UTC" : "") : null);
  add("To", e.to);
  if (e.pin) {
    add("Written down", h("span", { class: "mono" }, e.pin.repo + " at commit " + e.pin.commit + ", " + e.pin.file + ", "
      + (e.pin.last_line !== e.pin.line ? "lines " + e.pin.line + " to " + e.pin.last_line : "line " + e.pin.line)));
  } else add("Written down", e.source ? h("span", null, h("span", { class: "mono" }, String(e.source)), " (not in repo@commit:file:line form, so no line is given)") : "no source recorded");
  add("Recorded by", [e.added_by, e.added ? day(e.added) : null].filter(Boolean).join(" · "));
  parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "Your words, whole"), wordsNode(e.words, Infinity, null)));
  if (e.offer) parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "The offer you accepted"), wordsNode(e.offer, Infinity, null)));
  parts.push(h("section", { class: "part" }, facts));
  if (e.computed_status === "parked") {
    parts.push(h("p", { class: "meta", "data-space": "mt-12" }, "A hold: its words are above, whole, and its time anchor is the date. The register keeps no separate field for what it stops or who lifts it; your words say it."));
  }
  const rel = h("p", { class: "rel" });
  if (e.superseded_by && e.superseded_by.length) rel.append(h("span", { class: "bad" }, "Superseded by ", recordLinks(e.superseded_by)));
  if (e.supersedes && e.supersedes.length) rel.append(h("span", null, "Supersedes ", recordLinks(e.supersedes)));
  if (rel.childNodes.length) parts.push(h("section", { class: "part" }, rel));
  for (const later of e.superseded_by || []) {
    const s = byId.get(later);
    if (s) parts.push(h("div", { class: "note" }, h("p", { class: "label" }, "Superseded by " + later + ", " + day(s.date)), wordsNode(s.words, Infinity, null)));
  }
  if (e.reading) {
    parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "The scribe's reading"),
      h("p", { class: "meta" }, "An agent's one-line reading of your words, not your words."), h("p", { class: "soft" }, e.reading)));
  }
  for (const n of e.notes || []) {
    parts.push(h("div", { class: "note" }, h("p", { class: "label" }, "Note (the scribe's, not a decision of yours)"), h("p", { class: "soft" }, n.text || ""),
      n.quote ? wordsNode(n.quote, Infinity, null) : null,
      h("p", { class: "pin" }, n.pin ? n.pin.repo + " at commit " + n.pin.commit + ", " + n.pin.file + ", line " + n.pin.line + (n.pin.last_line !== n.pin.line ? " to " + n.pin.last_line : "") : (n.source || ""))));
  }
  return parts;
}

export function render(data, el) {
  if (!data) { R.head.replaceChildren(header("Record", "Reading your files…")); return; }
  if (data.off) {
    R.head.replaceChildren(header("Record", "The record is off: your sources file names no register.", S.frame ? "Your sources file: " + S.frame.config : null));
    R.tools.hidden = true;
    R.list.replaceChildren();
    return;
  }
  R.tools.hidden = false;
  const counts = data.counts || {};
  const by = counts.by_status || {};
  R.head.replaceChildren(header("Record", plural(counts.entries || 0, "decision") + " in " + plural(counts.threads || 0, "thread") + ", newest first. Your words are kept as you gave them.",
    data.files && data.files.register ? "From " + data.files.register + (data.notes_off ? "" : ", with its notes") + "." : null));
  const facets = [["all", "All", counts.entries || 0], ...Object.entries(by).filter(([, n]) => n > 0).map(([s, n]) => [s, cap(s), n])];
  if (!facets.some(([k]) => k === S.facet)) S.facet = "all";
  R.facets.replaceChildren(...facets.map(([k, label, n]) => h("button", { type: "button", "aria-pressed": String(S.facet === k), "data-k": "facet:" + k,
    on: { click: () => { S.facet = k; fill(); } } }, label, h("span", { class: "n" }, String(n)))));
  const q = S.q.record.trim().toLowerCase();
  const byId = new Map((data.entries || []).filter((e) => typeof e.id === "string").map((e) => [e.id, e]));
  const limit = data.whole_bytes || 512;
  const all = h("a", { href: "#record" }, "Record");
  const sub = S.sub || "";
  // Level 3: one decision at its source.
  if (sub && !sub.startsWith("t/")) {
    R.tools.hidden = true;
    R.empty.hidden = true;
    const e = byId.get(sub);
    const t = e && (data.threads || []).find((x) => (x.entries || []).includes(e.id));
    if (!e) { R.head.replaceChildren(header("No such decision", "No decision in your register has the id " + sub + " now.", null, crumbs(all, sub))); R.list.replaceChildren(); return; }
    R.head.replaceChildren(header(e.id, null, null, crumbs(all, t ? h("a", { href: "#record/t/" + t.key }, t.subject || "(no subject)") : e.subject || "(no subject)", e.id)));
    R.list.replaceChildren(h("p", { class: "subject" }, e.subject || "(no subject)"), ...sourceNode(e, byId));
    return;
  }
  // Level 2: one thread's decisions, newest first.
  if (sub.startsWith("t/")) {
    R.tools.hidden = true;
    R.empty.hidden = true;
    const t = (data.threads || []).find((x) => x.key === sub.slice(2));
    if (!t) { R.head.replaceChildren(header("No such thread", "No subject in your register has this address now.", null, crumbs(all, "a thread"))); R.list.replaceChildren(); return; }
    const ents = (t.entries || []).map((id) => byId.get(id)).filter(Boolean).reverse();
    R.head.replaceChildren(header(t.subject || "(no subject)", plural((t.entries || []).length, "decision") + " · now " + (t.current || "no status")
      + ((t.to || []).length ? " · to " + t.to.join(", ") : "") + " · " + (t.first === t.last ? day(t.last) : day(t.first) + " to " + day(t.last)), null, crumbs(all, t.subject || "(no subject)")));
    R.list.replaceChildren(h("div", { class: "thread" }, ents.map((e) => entryNode(e, limit, false))));
    return;
  }
  // Level 1: the threads, one line each; with a search, the decisions whose words match, each one click from its source.
  const fits = (e) => (S.facet === "all" || e.computed_status === S.facet) && (!q || entryText(e).includes(q));
  const out = [];
  let shown = 0;
  if (q) {
    for (const t of data.threads || []) {
      for (const e of (t.entries || []).map((id) => byId.get(id)).filter((x) => x && fits(x)).reverse()) { shown++; out.push(h("div", { class: "thread" }, entryNode(e, limit, true))); }
    }
  } else {
    for (const t of data.threads || []) {
      const ents = (t.entries || []).map((id) => byId.get(id)).filter((e) => e && fits(e));
      if (!ents.length) continue;
      shown += ents.length;
      out.push(h("a", { class: "thread threadrow", href: "#record/t/" + t.key, "data-k": "thread:" + t.key },
        h("span", { class: "subject" }, t.subject || "(no subject)"),
        h("span", { class: "meta" }, plural((t.entries || []).length, "decision") + " · now " + (t.current || "no status") + ((t.to || []).length ? " · to " + t.to.join(", ") : "")
          + " · " + (t.first === t.last ? day(t.last) : day(t.first) + " to " + day(t.last)))));
    }
  }
  R.list.replaceChildren(...out);
  R.empty.hidden = shown !== 0;
  R.empty.textContent = q ? "No decision's words match “" + S.q.record.trim() + "”" + (S.facet !== "all" ? " among those " + S.facet : "") + "." : "No decision has this status.";
}
