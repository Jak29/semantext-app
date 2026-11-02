// Diffmap: the change specs agents keep for you in cv/<project>/diffmap/, read in the page, each with the command that
// opens it in the diffmap viewer. The page runs nothing: you copy the command and start the viewer yourself.
import { h } from "./dom.js";
import { plural, when } from "./words.js";
import { crumbs, header } from "./parts.js";
import { fill, S } from "./app.js";
import { chip } from "./cards.js";
import { readDocument, copyText } from "./documents.js";
import { renderMarkdown } from "./markdown.js";

export const M = { text: new Map(), pending: new Set() };

export function specHref(folder, file) { return "#diffmap/" + encodeURIComponent(folder) + "/" + encodeURIComponent(file); }

function specText(s) {
  const key = s.folder + "/" + s.file + "@" + s.updated;
  if (M.text.has(key)) return M.text.get(key);
  if (!M.pending.has(key)) {
    M.pending.add(key);
    readDocument(s.folder, s.file).then((r) => r.json()).then((j) => ({ text: String(j.text || "") }), (e) => ({ error: String(e.message || e) }))
      .then((v) => { M.text.set(key, v); M.pending.delete(key); if (S.place === "diffmap") fill(); });
  }
  return null;
}

// A spec, split at its fences. A "mermaid diff" fence is a before-and-after diagram: each line is marked by its first
// character (a space for both, - for before, + for after) and shown as text in that colour, never drawn. A "changes"
// fence is a commit range on its first line, then the files in review order. Any other fence is code; the rest is prose.
export function specParts(text) {
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  const parts = [];
  let prose = [];
  const flush = () => { if (prose.some((l) => l.trim())) parts.push({ kind: "prose", text: prose.join("\n") }); prose = []; };
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(/^```\s*(.*)$/);
    if (!m) { prose.push(lines[i]); continue; }
    flush();
    const info = m[1].trim();
    const body = [];
    i++;
    while (i < lines.length && !/^```/.test(lines[i])) body.push(lines[i++]);
    const diff = info.match(/^mermaid\s+diff(?:\s+\[(.*)\])?\s*$/i);
    if (diff) parts.push({ kind: "diagram", label: diff[1] || "", lines: body });
    else if (/^changes\s*$/i.test(info)) parts.push({ kind: "changes", range: (body[0] || "").trim(), files: body.slice(1).map((x) => x.trim()).filter(Boolean) });
    else parts.push({ kind: "code", info, text: body.join("\n") });
  }
  flush();
  return parts;
}

function partNode(p) {
  if (p.kind === "prose") return renderMarkdown(p.text, null);
  if (p.kind === "code") return h("pre", null, h("code", null, p.text));
  if (p.kind === "diagram") {
    return h("figure", { class: "spec-diff" }, p.label ? h("figcaption", { class: "label" }, "Diagram, before and after: " + p.label) : h("figcaption", { class: "label" }, "Diagram, before and after"),
      h("pre", null, p.lines.map((l) => h("span", { class: l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "same" }, l + "\n"))),
      h("p", { class: "meta" }, "Shown as text. Lines with - are before the change, lines with + after it; the viewer draws them."));
  }
  return h("section", { class: "part spec-changes" }, h("h3", { class: "label" }, "The change"),
    h("p", null, "Commits ", h("code", null, p.range || "(no range given)")),
    p.files.length ? h("ol", null, p.files.map((f) => h("li", null, h("code", null, f)))) : h("p", { class: "meta" }, "No files listed."));
}

function commandNode(s, note) {
  if (!s.command) return h("p", { class: "meta" }, "No command to open it: " + s.no_command + ".");
  const copy = h("button", { type: "button", "data-k": "copy:" + s.folder + ":" + s.file }, "Copy the command");
  const tools = h("div", { class: "doc-tools" }, h("code", { class: "command" }, s.command), copy);
  copy.addEventListener("click", () => copyText(copy, s.command, tools));
  return h("div", null, tools, note ? h("p", { class: "meta" }, note) : null,
    h("p", { class: "meta" }, "Run it yourself to open this change in the viewer. This page runs nothing. The command is built from diffmap_command in your sources file, which an agent can edit: read it before you run it."));
}

export function render(data, el) {
  if (!data) { el.replaceChildren(header("Diffmap", S.err ? "The page could not read your specs: " + S.err : "Reading your files…")); return; }
  if (data.off) { el.replaceChildren(header("Diffmap", "Diffmap is off: your sources file names no seats file.", S.frame ? "Your sources file: " + S.frame.config : null)); return; }
  const specs = data.specs || [];
  if (S.sub) {
    const cut = S.sub.indexOf("/");
    const folder = cut < 0 ? S.sub : S.sub.slice(0, cut);
    const file = cut < 0 ? "" : S.sub.slice(cut + 1);
    return fillSpec(specs.find((s) => s.folder === folder && s.file === file), data.note, el);
  }
  const lines = [];
  if (data.template_problem) lines.push(h("p", { class: "refused" }, "Your diffmap command is not used: " + data.template_problem + "."));
  el.replaceChildren(header("Diffmap", specs.length ? plural(specs.length, "change spec") + ", newest first. An agent writes one when a change is big enough for you to review in the viewer."
    : "No change specs yet. An agent writes one as cv/<project>/diffmap/<name>.md in its home when a change is big enough for you to review."),
  ...lines,
  h("div", { class: "docrows" }, specs.map((s) => h("a", { class: "docrow", href: specHref(s.folder, s.file), "data-k": "spec:" + s.folder + ":" + s.file },
    h("span", { class: "card-head" }, chip(s.agent, "seat"), s.project_name ? chip(s.project_name, "kind") : null, h("span", { class: "at" }, "Updated " + when(s.updated))),
    h("span", { class: "subject" }, s.title || s.stem),
    h("span", { class: "meta" }, "cv/" + s.slug + "/diffmap/" + s.file + (s.command ? "" : " · no command"))))));
}

function fillSpec(s, note, el) {
  const all = h("a", { href: "#diffmap" }, "Diffmap");
  if (!s) { el.replaceChildren(header("No such spec", "No change spec of yours is at this address now.", null, crumbs(all, "a spec"))); return; }
  const parts = [header(s.title || s.stem, null, s.agent + "'s project" + (s.project_name ? " · " + s.project_name : "") + " · cv/" + s.slug + "/diffmap/" + s.file + " · updated " + when(s.updated), crumbs(all, s.title || s.stem)),
    commandNode(s, note)];
  const art = h("article", { class: "md" });
  const got = specText(s);
  if (!got) art.append(h("p", { class: "meta" }, "Reading " + s.file + "…"));
  else if (got.error) art.append(h("p", { class: "refused" }, "Could not read " + s.file + ": " + got.error));
  else for (const p of specParts(got.text)) art.append(partNode(p));
  parts.push(art);
  el.replaceChildren(...parts);
}
