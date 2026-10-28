// The map of the whole, under your own word for it.
import { h } from "./dom.js";
import { day, listWords, plural } from "./words.js";
import { crumbs, disclosure, header } from "./parts.js";
import { S } from "./app.js";
import { mapKey } from "./frame.js";
import { openDrawer } from "./drawers.js";

// ---------------------------------------------------------------- the map of the whole
const TILE_LIMIT = 14;   // at most 14 named children on a level

export function brokenWords(words) {
  const say = { "off": ["off", "off"], "checks nothing": ["checks nothing", "check nothing"], "open": ["open", "open"], "stranded": ["stranded", "stranded"] };
  return Object.entries(words || {}).sort((a, b) => b[1] - a[1]).map(([w, n]) => n + " " + (say[w] ? say[w][n === 1 ? 0 : 1] : w)).join(", ");
}

export function marks(n, below) {
  const out = [];
  if (n.waiting) out.push(h("span", { class: "marks" }, h("span", { class: "dot", "aria-hidden": "true" }), plural(n.waiting, "card") + " waiting"));
  if (n.broken) out.push(h("span", { class: "marks bad" }, h("span", { class: "mark", "aria-hidden": "true" }),
    plural(n.broken, "worktree") + (below ? " below" : "") + ": " + brokenWords(n.broken_words) + " (read)"));
  if (!n.waiting && !n.broken) out.push(h("span", { class: "marks quiet" }, "nothing waiting; no gate found broken (read)"));
  return out;
}

export function tilesOf(items, make) {
  const shown = items.slice(0, TILE_LIMIT).map(make);
  const out = [h("div", { class: "tiles" }, shown)];
  if (items.length > TILE_LIMIT) {
    const d = disclosure("more:" + S.sub, plural(items.length - TILE_LIMIT, "more"));
    d.append(h("div", { class: "tiles", "data-space": "mt-12" }, items.slice(TILE_LIMIT).map(make)));
    out.push(d);
  }
  return out;
}

export function nodeTile(data, n) {
  const kind = n.kind === "group" ? "group · " + plural(n.children.length, "environment")
    : n.kind === "environment" ? "home of " + listWords(n.members.map((m) => m.name)) + " · " + plural(n.projects.length, "project")
    : n.kind;
  return h("a", { class: "tile", href: "#" + mapKey() + "/" + encodeURIComponent(n.id), "data-k": "node:" + n.id },
    h("span", { class: "name" }, n.name || "(no name)"), h("span", { class: "kind" }, kind), marks(n, true));
}

export function projectTile(t, home) {
  return h("a", { class: "tile", href: "#projects/" + encodeURIComponent(t.id), "data-k": "pt:" + t.id },
    h("span", { class: "name" }, t.name), h("span", { class: "kind" }, (home ? "its home · " : "project · ") + plural(t.worktrees, "worktree")),
    marks(t, false));
}

export function agentTile(data, m) {
  const a = data.agents[m.agent_id] || { name: m.name, waiting: [], works: [] };
  const n = { waiting: a.waiting.length, broken: 0 };
  return h("button", { class: "tile", type: "button", "data-k": "at:" + m.agent_id, on: { click: (ev) => openDrawer("agent", { id: m.agent_id }, ev.currentTarget) } },
    h("span", { class: "name" }, a.name), h("span", { class: "kind" }, "agent · works in " + plural(a.works.length, "project")),
    n.waiting ? h("span", { class: "marks" }, h("span", { class: "dot", "aria-hidden": "true" }), plural(n.waiting, "card") + " waiting") : h("span", { class: "marks quiet" }, "nothing waiting"));
}

export function render(data, el) {
  const place = el;
  const word = (S.frame && S.frame.name) || "Map";
  if (!data) { place.replaceChildren(header(word, "Reading your files…")); return; }
  if (data.off || !data.root) {
    place.replaceChildren(header(word, "The map is off: your sources file names no seats file and no map.", S.frame ? "Your sources file: " + S.frame.config : null));
    return;
  }
  const node = data.nodes[S.sub] || data.nodes[data.root];
  const chain = [];
  for (let n = node; n; n = n.parent ? data.nodes[n.parent] : null) chain.unshift(n);
  const trail = chain.length > 1 ? crumbs(...chain.slice(0, -1).map((n) => h("a", { href: "#" + mapKey() + "/" + encodeURIComponent(n.id) },
    n.kind === "whole" ? word : n.name)), node.name) : null;
  const legend = h("p", { class: "meta legend" }, h("span", { class: "dot", "aria-hidden": "true" }), "a card waits for your word below",
    h("span", { class: "mark", "data-space": "ml-18", "aria-hidden": "true" }), "a gate below is off, open, stranded or checks nothing, from a static read");
  const parts = [];
  if (node.kind === "whole") {
    const m = data.map || {};
    let line = "No map file is named in your sources file.";
    if (m.off === false) {
      line = m.places == null ? "The map file could not be summed up (see the problems above)."
        : "The map: " + plural(m.places, "place") + " and " + plural(m.edges || 0, "edge") + (m.measured ? ", measured " + day(m.measured) : ", with no date of measuring") + ".";
    }
    parts.push(header(word, line, null, trail));
    if (m.sectors && m.sectors.length) {
      const d = disclosure("map:sectors", plural(m.sectors.length, "sector") + " in the map file");
      d.append(h("ul", { class: "sectors" }, m.sectors.map((s) => h("li", null, h("span", null, s.name), h("span", { class: "meta" }, " · " + plural(s.places || 0, "place") + (s.title ? " · " + s.title : ""))))));
      parts[0].append(h("div", { "data-space": "mt-8" }, d));
    }
    const kids = node.children.map((id) => data.nodes[id]).filter(Boolean);
    // A level shows only when it has two: one group alone is opened in place, under its name.
    if (kids.length === 1 && kids[0].kind === "group") {
      const g = kids[0];
      const gk = g.children.map((id) => data.nodes[id]).filter(Boolean);
      parts.push(h("section", { class: "part" },
        h("h2", { class: "label" }, h("a", { href: "#" + mapKey() + "/" + encodeURIComponent(g.id), "data-space": "inherit-color" }, g.name), " · " + plural(gk.length, "environment")),
        tilesOf(gk, (n) => nodeTile(data, n))));
    } else {
      parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "In it"), tilesOf(kids, (n) => nodeTile(data, n))));
    }
  } else if (node.kind === "group") {
    parts.push(header(node.name, "A group of " + plural(node.members.length, "agent") + ", in " + plural(node.children.length, "environment") + ".", null, trail));
    const kids = node.children.map((id) => data.nodes[id]).filter(Boolean);
    parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "Environments"), tilesOf(kids, (n) => nodeTile(data, n))));
    const homeless = node.members.filter((m) => !kids.some((k) => k.members.some((x) => x.agent_id === m.agent_id)));
    if (homeless.length) parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "Agents with no home folder"), tilesOf(homeless, (m) => agentTile(data, m))));
  } else {
    parts.push(header(node.name, "An environment: " + listWords(node.members.map((m) => m.name + "'s home")) + ".", node.path, trail));
    parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "Members"), tilesOf(node.members, (m) => agentTile(data, m))));
    const tiles = node.projects.map((id) => data.projects[id]).filter(Boolean);
    parts.push(h("section", { class: "part" }, h("h2", { class: "label" }, "Works in"),
      tiles.length ? tilesOf(tiles, (t) => projectTile(t, t.id === node.project_id)) : h("p", { class: "empty" }, "No project lists its members.")));
  }
  parts.push(legend);
  place.replaceChildren(...parts);
}
