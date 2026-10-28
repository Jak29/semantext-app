// Projects: each project from your seats file, its agents, gates, cards and documents.
import { h } from "./dom.js";
import { listWords, newestFirst, plural, tail, when } from "./words.js";
import { crumbs, disclosure, docHref, header } from "./parts.js";
import { S } from "./app.js";
import { agentChip, cardNode } from "./cards.js";
import { closeDrawer, openDrawer } from "./drawers.js";

// ---------------------------------------------------------------- Projects
export const BROKEN = new Set(["off", "checks nothing", "open", "stranded"]);

export function basisWords(m) {
  const basis = m.basis || [];
  const parts = [];
  if (basis.includes("home")) parts.push("its home");
  if (basis.includes("identity")) parts.push("listed in .identity" + (m.emails && m.emails.length ? " as " + m.emails.join(", ") : ""));
  return parts.join("; ") || "listed";
}

export function gateCell(p, k) {
  const g = p.gates;
  if (!g.found) return h("span", { class: "none" }, "no gate read");
  if (!g.worktrees.length) return h("span", { class: "none" }, "no worktree found");
  const broken = BROKEN.has(g.worst);
  return h("button", { class: "cellbtn", type: "button", "data-k": k, title: "Open the gates",
    on: { click: (ev) => openDrawer("gates", { project: p.id }, ev.currentTarget) } },
    h("span", { class: "w" + (broken ? " bad" : "") }, g.worst + readMark(g.worst)),
    h("span", { class: "meta" }, g.broken ? g.broken + " of " + plural(g.worktrees.length, "worktree") : plural(g.worktrees.length, "worktree")));
}

export function render(data, el) {
  const place = el;
  if (!data) { place.replaceChildren(header("Projects", "Reading your files…")); return; }
  if (S.sub) return fillProject(data, S.sub, el);
  if (data.off) {
    place.replaceChildren(header("Projects", "Projects are off: your sources file names no seats file.", S.frame ? "Your sources file: " + S.frame.config : null));
    return;
  }
  const rows = data.projects;
  const sub = plural(rows.length, "project") + " from your seats file, with " + plural(data.worktrees, "worktree")
    + ". " + data.assigned + " of " + plural(data.total, "card") + " belong to one.";
  const head = header("Projects", sub, data.read_note ? "Gate states come from " + data.read_note.replace(/^a /, "a ") + ". Each is marked (read)." : null);
  if (!rows.length) {
    place.replaceChildren(head, h("p", { class: "empty" }, "No projects yet. Name a root of kind “repo” in your seats file, and it shows here."));
    return;
  }
  const table = h("div", { class: "rows", role: "table", "aria-label": "Projects" },
    h("div", { class: "prow head-row", role: "row" }, ["Project", "Agents", "Gates, at their worst", "Waiting", "Documents"].map((t) => h("span", { class: "label", role: "columnheader" }, t))));
  for (const p of rows) {
    table.append(h("div", { class: "prow", role: "row" },
      h("div", { class: "pname", role: "cell" }, h("a", { href: "#projects/" + encodeURIComponent(p.id), "data-k": "p:" + p.id }, p.name),
        h("div", { class: "ppath", title: p.path }, tail(p.path))),
      h("div", { class: "chips", role: "cell" }, p.agents.length ? p.agents.map((a) => agentChip(a.name, a.agent_id, "pa:" + p.id + ":" + a.agent_id)) : h("span", { class: "none" }, "nobody listed")),
      h("div", { role: "cell" }, gateCell(p, "pg:" + p.id)),
      h("div", { role: "cell", class: "cellbtn" }, p.waiting.length ? h("span", { class: "goldtext" }, h("span", { class: "dot", "aria-hidden": "true" }), p.waiting.length + " waiting")
        : h("span", { class: "none", title: "Nothing waits here" }, "–"), p.cards.length ? h("span", { class: "meta" }, plural(p.cards.length, "card") + " in all") : null),
      h("div", { role: "cell" }, p.documents.length ? h("button", { class: "link", type: "button", "data-k": "pd:" + p.id,
        on: { click: (ev) => openDrawer("docs", { project: p.id }, ev.currentTarget) } }, plural(p.documents.length, "document"))
        : h("span", { class: "none", title: "No documents" }, "–"))));
  }
  place.replaceChildren(head, table);
}

export function worktreeDetail(t) {
  const out = [];
  if (t.status === "missing") out.push(h("p", null, t.note || "The worktree's folder is gone."));
  if (t.status === "unknown") out.push(h("p", null, "No verdict: the reader could not be sure of git's settings here (see below)."));
  if (t.events.length) {
    out.push(h("table", { class: "events" },
      h("thead", null, h("tr", null, ["Act", "State", "Hook", "Note"].map((x) => h("th", null, x)))),
      h("tbody", null, t.events.map((e) => h("tr", null,
        h("td", null, e.event),
        h("td", { class: e.state === "open" ? "bad" : null }, e.state === "gated" ? "has a hook (" + NOT_TESTED + ")" : e.state + " (read)"),
        h("td", { class: "mono" }, e.by || (e.needs ? "needs " + e.needs.join(" or ") : "")),
        h("td", { class: "soft" }, e.note || ""))))));
  }
  const hp = t.hooks_path;
  if (hp && hp.set) {
    out.push(h("p", null, "core.hooksPath is ", h("span", { class: "mono" }, hp.value), ", set in the " + (hp.scope || "unknown") + " settings: ",
      h("span", { class: "mono" }, (hp.file || "") + (hp.line ? " line " + hp.line : "")),
      hp.via && hp.via.length ? " (included by " + hp.via.join(", ") + ")" : "", "."));
  } else if (t.status === "read") {
    out.push(h("p", null, "core.hooksPath is not set, so git runs hooks from ", h("span", { class: "mono" }, t.hooks_dir || "its own hooks folder"), "."));
  }
  if (hp && hp.set && t.hooks_dir) out.push(h("p", { class: "soft" }, "Hooks run from ", h("span", { class: "mono" }, t.hooks_dir), "."));
  if (t.identity) {
    out.push(h("p", { class: t.identity.present && t.identity.entries ? "soft" : "bad" }, t.identity.present
      ? ".identity names " + plural(t.identity.entries, "committer") + (t.identity.entries ? "." : ", so a hook that checks it lets every commit through.")
      : "No .identity file here, so a hook that checks it lets every commit through.",
      " ", h("span", { class: "mono" }, t.identity.file || "")));
  }
  if (t.not_executable && t.not_executable.length) {
    out.push(h("p", { class: "bad" }, "Not executable, so git ignores it (read): " + t.not_executable.join(", ") + "."));
  }
  if (t.status === "read" && t.executable) out.push(h("p", { class: "soft" }, "Hook files: " + t.executable + "."));
  if (t.read_at) out.push(h("p", { class: "meta" }, "Read at " + t.read_at + "; a later edit is not in it."));
  for (const s of t.stranded || []) {
    out.push(h("p", { class: "bad" }, "Stranded (read): " + s.name + " exists in " + (s.where || []).join(", ") + ", where git does not look."));
  }
  if (t.uncertain && t.uncertain.length) {
    out.push(h("div", null, h("p", { class: "label" }, "Not certain"), h("ul", { class: "soft" }, t.uncertain.map((u) => h("li", null, u)))));
  }
  if (t.files && t.files.length) {
    const d = disclosure("files:" + t.path, plural(t.files.length, "settings file") + " read");
    d.append(h("ul", { class: "mono" }, t.files.map((f) => h("li", null, f.scope + ": " + f.file + (f.included_by ? " (included by " + f.included_by + ")" : "")))));
    out.push(d);
  }
  return out;
}

export function stateWords(t) {
  return h("span", { class: "words-row" }, t.words.map((w) => h("span", { class: BROKEN.has(w) ? "bad" : "soft" }, w + readMark(w))));
}

// A gate word as read: the all-clear says what was read and that no hook was run, never that a gate refuses.
const ARMED_WORDS = "a hook for each act, identity named", NOT_TESTED = "read; not tested";
export function readMark(w) { return w === ARMED_WORDS ? " (" + NOT_TESTED + ")" : " (read)"; }


export function docNode(d) {
  const go = () => closeDrawer(true);
  return h("div", { class: "doc" },
    h("p", { class: "subject" }, h("a", { href: docHref(d.id), on: { click: go } }, d.title || d.slug)),
    h("p", { class: "meta" }, (d.agent ? d.agent + " · " : "") + "cv/" + d.slug + " · updated " + when(d.updated)),
    d.docs.length ? h("ul", null, d.docs.map((x) => h("li", null, h("a", { href: docHref(d.id, x.file), on: { click: go } }, x.title || x.file),
      h("span", { class: "meta" }, " · " + x.file + " · " + when(x.updated))))) : null,
    d.diagrams.length ? h("p", { class: "meta" }, plural(d.diagrams.length, "diagram") + ": ",
      d.diagrams.map((f, i) => [i ? ", " : "", h("a", { href: docHref(d.id, f), on: { click: go } }, f)])) : null);
}

function fillProject(data, id, el) {
  const place = el;
  const p = data.projects.find((x) => x.id === id);
  const trail = crumbs(h("a", { href: "#projects" }, "Projects"), p ? p.name : id);
  if (!p) {
    place.replaceChildren(header("No such project", "No project in your seats file has this id now.", null, trail));
    return;
  }
  const agents = h("section", { class: "part" }, h("h2", { class: "label" }, "Agents"));
  if (p.agents.length) {
    agents.append(h("div", { class: "alist" }, p.agents.map((a) => h("div", { class: "arow" }, agentChip(a.name, a.agent_id, "pp:" + a.agent_id), h("span", { class: "soft" }, basisWords(a))))));
  } else agents.append(h("p", { class: "empty" }, "Nobody is listed. Add “Name <email>” lines to this project's .identity file."));
  if (p.others && p.others.length) agents.append(h("p", { class: "meta", "data-space": "mt-10" }, "Also listed in .identity, and no agent of yours: " + listWords(p.others.map((o) => o.name)) + "."));

  const gates = h("section", { class: "part" }, h("h2", { class: "label" }, "Gates"));
  if (!p.gates.found) gates.append(h("p", { class: "empty" }, "No gate was read: the folder is not a repository the reader could find."));
  else {
    if (data.read_note) gates.append(h("p", { class: "meta", "data-space": "mb-10" }, "From " + data.read_note + "."));
    const list = h("div", { class: "wts" });
    for (const t of p.gates.worktrees) {
      const d = disclosure("wt:" + t.path, h("span", { "data-space": "contents" }, h("span", { class: "mono", title: t.path }, wtName(t)), stateWords(t)), "wt");
      d.append(h("div", { class: "wt-body" }, worktreeDetail(t)));
      list.append(d);
    }
    gates.append(p.gates.worktrees.length ? list : h("p", { class: "empty" }, "No worktree found."));
  }

  const cardsPart = h("section", { class: "part" }, h("h2", { class: "label" }, "Cards"));
  const mine = p.cards.map((k) => data.cards[k]).filter(Boolean);
  const order = { waiting: 0, parked: 1, closed: 2, run: 2 };
  const sorted = newestFirst(mine).sort((a, b) => (order[a.state] ?? 3) - (order[b.state] ?? 3));
  cardsPart.append(sorted.length ? h("div", { class: "cards" }, sorted.map(cardNode))
    : h("p", { class: "empty" }, "No card is placed in this project. A card belongs here when it runs in this folder or names it."));

  const docsPart = h("section", { class: "part" }, h("h2", { class: "label" }, "Documents"));
  const docs = data.documents.filter((d) => d.project === p.id);
  docsPart.append(docs.length ? h("div", null, docs.map(docNode))
    : h("p", { class: "empty" }, "No documents. A folder cv/<project>/ holding a MASTER.md in an agent's home shows here."));

  const sub = p.home_of && p.home_of.length ? "The home of " + listWords(p.home_of) + "." : plural(p.agents.length, "agent") + " work here.";
  place.replaceChildren(header(p.name, sub, p.path, trail), agents, gates, cardsPart, docsPart);
}

// A worktree by the name a person knows it by: the main one, or its folder within the project.
export function wtName(t) { return t.main ? "main worktree" : t.short; }
