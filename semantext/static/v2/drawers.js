// The drawers: an agent, its rules, a project's gates, a project's documents.
import { $, h } from "./dom.js";
import { newestFirst, plural, when } from "./words.js";
import { docHref } from "./parts.js";
import { DRAWER_ROUTE, load, S } from "./app.js";
import { renderProblems } from "./frame.js";
import { goCard } from "./waiting.js";
import { basisWords, docNode, stateWords, worktreeDetail, wtName } from "./projects.js";

// ---------------------------------------------------------------- drawers
export function openDrawer(kind, arg, opener) {
  S.drawer = { kind, arg: arg || {} };
  S.opener = opener || document.activeElement;
  $("drawer").hidden = false;
  $("scrim").hidden = false;
  renderDrawer(true);
  $("drawer-close").focus();
  const route = DRAWER_ROUTE[kind];
  if (!S.data[route]) load(route).then(() => renderDrawer(false)).catch((e) => { S.err = String(e.message || e); renderProblems(); });
}

export function closeDrawer(quiet) {
  if (!S.drawer) return;
  S.drawer = null;
  $("drawer").hidden = true;
  $("scrim").hidden = true;
  const back = S.opener;
  S.opener = null;
  if (quiet) return;
  if (back && document.contains(back)) back.focus();
  else if (back && back.dataset && back.dataset.k) {
    const again = document.querySelector('[data-k="' + CSS.escape(back.dataset.k) + '"]');
    (again || $("main")).focus();
  } else $("main").focus();
}

export function drawerPart(label, ...kids) { return h("section", { class: "part" }, h("h3", { class: "label" }, label), ...kids); }

export function renderDrawer(fresh) {
  if (!S.drawer) return;
  const body = $("drawer-body");
  const y = body.scrollTop;
  const { kind, arg } = S.drawer;
  const data = S.data[DRAWER_ROUTE[kind]];
  $("drawer-kind").textContent = { agent: "Agent", rules: "Rules", gates: "Gates", docs: "Documents" }[kind];
  if (!data) { $("drawer-title").textContent = "Reading…"; body.replaceChildren(); return; }
  const parts = (DRAW[kind] || (() => ["", []]))(data, arg);
  $("drawer-title").textContent = parts[0];
  body.replaceChildren(...parts[1]);
  if (!fresh) body.scrollTop = y;
}

export const DRAW = {
  agent(data, arg) {
    const id = arg.id || (data.names || {})[arg.name];
    const a = data.agents[id];
    if (!a) return [arg.name || "No such agent", [h("p", { class: "empty" }, "This agent is not in your seats file now.")]];
    const facts = h("dl", { class: "facts" });
    const add = (k, v) => { if (v) facts.append(h("dt", null, k), h("dd", null, v)); };
    add("Also called", (a.other_names || []).join(", "));
    add("Groups", (a.groups || []).join(", "));
    add("Emails", (a.emails || []).join(", "));
    if (a.home) facts.append(h("dt", null, "Home"), h("dd", { class: "mono" }, a.home));
    const go = (href) => (ev) => { closeDrawer(true); if (location.hash === href) ev.preventDefault(); };
    const works = a.works.length ? h("div", { class: "alist" }, a.works.map((w) => h("div", { class: "arow" },
      h("a", { href: "#projects/" + encodeURIComponent(w.project_id), on: { click: go("#projects/" + w.project_id) } }, w.name),
      h("span", { class: "soft" }, basisWords(w))))) : h("p", { class: "empty" }, "No project lists this agent.");
    const waiting = a.waiting.map((k) => data.cards[k]).filter(Boolean);
    const cardsList = waiting.length ? h("div", { class: "alist" }, newestFirst(waiting).map((c) => h("div", { class: "arow" },
      h("button", { class: "link mono", type: "button", on: { click: () => goCard(c.key) } }, c.id),
      h("span", null, c.title), h("span", { class: "meta" }, when(c.at)))))
      : h("p", { class: "empty" }, "Nothing from " + a.name + " waits for your word" + (a.cards ? "; " + plural(a.cards, "card") + " in all." : "."));
    const docs = (data.documents || []).filter((d) => a.documents.includes(d.id));
    const docList = docs.length ? h("div", { class: "alist" }, docs.map((d) => h("div", { class: "arow" },
      h("a", { href: docHref(d.id), on: { click: () => closeDrawer(true) } }, d.title || d.slug),
      h("span", { class: "meta" }, "cv/" + d.slug + " · " + when(d.updated)))))
      : h("p", { class: "empty" }, "No documents in " + a.name + "'s cv folder.");
    const r = a.rules || { environments: [] };
    const rules = h("div", { class: "alist" },
      h("p", { class: "soft" }, r.environments.length ? "Its own: " + r.environments.join(", ") + ". Every other environment is shared." : "No environment of its own; it reads the shared ones."),
      h("button", { class: "link", type: "button", on: { click: (ev) => openDrawer("rules", { agent: a.name }, ev.currentTarget) } }, "Open " + a.name + "'s rules"));
    return [a.name, [h("section", { class: "part" }, facts), drawerPart("Works in", works), drawerPart("Waiting", cardsList),
      drawerPart("Documents", docList), drawerPart("Rules", rules)]];
  },

  rules(data, arg) {
    if (data.off) return ["Rules", [h("p", { class: "empty" }, "Rules are off: your sources file names no folder of rule cards.")]];
    const envs = data.environments || [];
    const agent = arg.agent;
    const owned = new Set(Object.values(data.agents || {}).flatMap((x) => x.environments || []));
    let chosen = envs;
    let lead = "";
    if (agent && data.agents && data.agents[agent]) {
      const mine = data.agents[agent].environments || [];
      chosen = [...envs.filter((e) => mine.includes(e.name)), ...envs.filter((e) => !owned.has(e.name))];
      lead = (mine.length ? "Its own environment" + (mine.length > 1 ? "s" : "") + " first (" + Object.values(data.agents[agent].basis || {}).join("; ") + "), then the shared ones." : "It has no environment of its own; these are the shared ones.");
    }
    const c = data.counts || {};
    const share = (n) => c.rules ? " (" + Math.round(100 * (n || 0) / c.rules) + "%)" : "";
    const parts = [h("section", { class: "part" },
      h("p", { class: "soft" }, plural(c.rules || 0, "rule") + " in " + plural(c.environments || 0, "environment") + ": " + (c.written || 0) + " written" + share(c.written)
        + ", " + (c.checked || 0) + " checked" + share(c.checked) + (c.guarded_once ? ", " + c.guarded_once + " guarded once" + share(c.guarded_once) : "")
        + ", " + (c.guarded || 0) + " guarded" + share(c.guarded) + "."),
      lead ? h("p", { class: "meta", "data-space": "mt-4" }, lead) : null,
      h("p", { class: "meta", "data-space": "mt-4" }, "How firmly each is held: written, its words alone; checked, a correction kept as a regression case names it; guarded, a checker that runs outside this page recorded both its must-pass and its must-refuse arm passing, on these words and the files as they are now; guarded once, such a record that has gone stale since."),
      data.run_records ? null : h("p", { class: "meta", "data-space": "mt-4" }, "Your sources file names no run-record folder, so no rule is guarded. A checker your guards file names, or a guard a card mentions, is shown as a claim and counts for nothing."))];
    for (const e of chosen) {
      const env = h("div", { class: "env" },
        h("p", { class: "env-head" }, e.title || e.name),
        h("p", { class: "meta" }, [e.name, e.version ? "version " + e.version : null, e.status, e.ratified_by ? "ratified by " + e.ratified_by : null,
          owned.has(e.name) ? null : "shared"].filter(Boolean).join(" · ")));
      if (e.scope) env.append(h("p", { class: "soft", "data-space": "mt-4" }, e.scope));
      const rules = e.rules || [];
      if (!rules.length) env.append(h("p", { class: "empty" }, "No rules in this environment yet."));
      const kinds = new Map();
      for (const r of rules) { const k = r.kind || "other"; if (!kinds.has(k)) kinds.set(k, []); kinds.get(k).push(r); }
      for (const [k, list] of kinds) {
        env.append(h("p", { class: "label kind-head" }, k + " · " + list.length));
        for (const r of list) env.append(ruleNode(r));
      }
      parts.push(env);
    }
    return [agent ? agent + "'s rules" : "Your rules", parts];
  },

  gates(data, arg) {
    const p = (data.projects || []).find((x) => x.id === arg.project);
    if (!p) return ["No such project", [h("p", { class: "empty" }, "No project in your seats file has this id now.")]];
    const trees = p.gates.worktrees;
    if (!trees.length) return [p.name, [h("p", { class: "empty" }, "No worktree was read here.")]];
    const rank = (t) => Math.min(...t.words.map((w) => ["off", "checks nothing", "open", "stranded", "unknown", "folder gone"].indexOf(w)).map((i) => i < 0 ? 9 : i));
    const t = trees.find((x) => x.path === arg.path) || trees.slice().sort((a, b) => rank(a) - rank(b))[0];
    const parts = [];
    if (trees.length > 1) {
      parts.push(h("div", { class: "switcher", role: "group", "aria-label": "Worktrees" }, trees.map((x) => h("button", { type: "button", "aria-pressed": String(x === t),
        on: { click: () => { S.drawer.arg = { project: p.id, path: x.path }; renderDrawer(false); } } }, h("span", { class: "mono" }, wtName(x)), stateWords(x)))));
    }
    parts.push(h("section", { class: "part" }, h("p", null, h("span", { class: "mono" }, t.path)), h("p", { "data-space": "mt-4" }, stateWords(t)),
      data.read_note ? h("p", { class: "meta", "data-space": "mt-4" }, "From " + data.read_note + ".") : null));
    parts.push(h("section", { class: "part" }, h("div", { class: "wt-body", "data-space": "pad-0" }, worktreeDetail(t))));
    parts.push(h("section", { class: "part" }, h("a", { href: "#projects/" + encodeURIComponent(p.id), on: { click: () => closeDrawer(true) } }, "Open " + p.name)));
    return [p.name, parts];
  },

  docs(data, arg) {
    const p = (data.projects || []).find((x) => x.id === arg.project);
    if (!p) return ["No such project", [h("p", { class: "empty" }, "No project in your seats file has this id now.")]];
    const docs = (data.documents || []).filter((d) => d.project === p.id);
    const parts = [h("section", { class: "part" }, h("p", { class: "soft" }, docs.length ? plural(docs.length, "document") + " in " + p.name + ", each a cv folder holding a MASTER.md. Open one to read it here." : "No documents here."))];
    if (docs.length) parts.push(h("section", { class: "part" }, docs.map(docNode)));
    return [p.name, parts];
  },
};

// A rule, with how firmly it is held and the source of that level: the run records of checkers that run outside the
// page (docs/run-record-schema.md), the regression cases that name it, and, said as claims, the checkers the guards file
// names and the guards the card mentions.
export function recordedBy(v) { return "(recorded by " + v.checker + " " + v.version + " at " + v.at + "; not re-run by this page)"; }
export function armsWords(v) {
  const p = v.arms.must_pass, f = v.arms.must_refuse;
  return "must-pass " + p.passed + " of " + p.ran + " passed, must-refuse " + f.refused + " of " + f.ran + " refused";
}
// A record's findings never change its level, and are never hidden behind a passing count (docs/run-record-schema.md).
export const withFindings = (n) => (n ? ", with " + plural(n, "finding") : "");
// A record's own outcome is said as it wrote it; "failed" or "not proved" earns nothing, whatever the counts say.
export const outcomeWords = (v) => (v.outcome ? " Its outcome: " + v.outcome + "." : "");
export function runLine(v) {
  if (v.state === "guarded") return "Guarded" + withFindings((v.findings || []).length) + ": " + armsWords(v) + " " + recordedBy(v) + "." + outcomeWords(v);
  if (v.state === "stale") return "Guarded once, now stale: " + v.stale.join("; ") + ". " + armsWords(v) + " " + recordedBy(v) + "." + outcomeWords(v);
  if (v.outcome === "failed" || v.outcome === "not proved") return "The newest run of " + v.checker + " says its outcome is " + v.outcome + " (" + armsWords(v) + "), so it earns nothing " + recordedBy(v) + ".";
  return "The newest run of " + v.checker + " did not pass (" + armsWords(v) + "), so it earns nothing " + recordedBy(v) + ".";
}
export function ruleNode(r) {
  const held = r.held || "written";
  const node = h("div", { class: "rule", "data-rule": r.id }, h("p", null, r.words),
    h("p", { class: "meta" }, h("span", { class: "mono" }, r.id), " · ", h("span", { class: held === "guarded" || held === "checked" ? "goldtext" : "soft" },
      held + (held === "guarded" ? withFindings((r.runs || []).filter((v) => v.state === "guarded").reduce((n, v) => n + (v.findings || []).length, 0)) : "")),
      r.agent ? " · " + r.agent + " only" : "", r.live === false ? " · switched off" : "", r.candidate ? " · not ratified" : "",
      r.no_provenance ? h("span", { title: "Its environment records no provenance for it: most often typed into the file by hand. Who ratified it is not where it came from." }, " · (no provenance)") : null));
  const why = h("ul", { class: "meta held-why" });
  for (const v of r.runs || []) {
    why.append(h("li", { class: "run" }, runLine(v), v.note ? h("span", { class: "soft" }, " Its note: " + v.note) : null,
      (v.findings || []).length ? h("ul", { class: "findings" }, v.findings.map((f) => h("li", null, "Finding: " + f))) : null));
  }
  for (const k of r.checkers || []) {
    why.append(h("li", null, "Your guards file names " + k.name + (k.where ? " (" + k.where + (k.where_note ? ", " + k.where_note : k.where_exists === true ? ", which is there now" : k.where_exists === false ? ", which is not there now" : "") + ")" : "") + ": it must let pass " + k.must_pass.join("; ")
      + ", and it must refuse " + k.must_refuse.join("; ") + ". A name in that file is not a run, so it earns nothing by itself."));
  }
  const kept = (r.cases || []).filter((x) => x && x.kept_in && x.kept_in.length);
  if (kept.length) why.append(h("li", null, "Checked by " + kept.map((x) => x.id + " (kept in " + x.kept_in.join(", ") + ")").join(", ") + "."));
  const loose = (r.cases || []).filter((x) => x && (!x.kept_in || !x.kept_in.length));
  if (loose.length) why.append(h("li", null, "Names " + loose.map((x) => x.id).join(", ") + ", which no card keeps, so it checks nothing."));
  if (held === "written") why.append(h("li", null, "Its words alone: no regression case names it and no run record guards it."));
  if (r.guards && r.guards.length) why.append(h("li", null, "The card says: " + r.guards.join("; ") + ". No checker is named for it, so that counts for nothing."));
  node.append(why);
  return node;
}
