// Documents: each cv/<project> folder with a MASTER.md, read in the page.
import { h } from "./dom.js";
import { plural, when } from "./words.js";
import { crumbs, docHref, header } from "./parts.js";
import { fill, S } from "./app.js";
import { chip } from "./cards.js";
import { renderMarkdown } from "./markdown.js";

// ---------------------------------------------------------------- Documents
// Every project folder an agent keeps in its cv/ with a MASTER.md, as your inbox's Documents lists them, read here:
// MASTER.md (with its Copy button), the detailed documents beside it, and its diagrams. The server reads only a file its
// documents reader lists in a listed folder; this page sets every word of it as text.
export const D = { text: new Map(), images: new Map(), pending: new Set() };

export async function readDocument(id, file) {
  const r = await fetch("/api/v2/document?doc=" + encodeURIComponent(id) + "&file=" + encodeURIComponent(file),
    { headers: { "X-Semantext": "1" }, cache: "no-store" });
  if (!r.ok) {
    let why = "the server answered " + r.status;
    try { why = (await r.json()).error || why; } catch (e) { /* the status says enough */ }
    throw new Error(why);
  }
  return r;
}

// A file's text, read once for each time its folder was updated: {text} or {error}, or null while it is read (the place
// is drawn again when it arrives).
export function docText(d, file) {
  const key = d.id + "/" + file + "@" + d.updated;
  if (D.text.has(key)) return D.text.get(key);
  if (!D.pending.has(key)) {
    D.pending.add(key);
    readDocument(d.id, file).then((r) => r.json()).then((j) => ({ text: String(j.text || "") }), (e) => ({ error: String(e.message || e) }))
      .then((v) => { D.text.set(key, v); D.pending.delete(key); if (S.place === "documents") fill(); });
  }
  return null;
}

// A diagram, shown through an <img>, which never runs a diagram's script. Its bytes come from the read route (with the
// page's header, which an <img> cannot send), so the <img> is given them as a local object URL.
export function diagramNode(d, file, alt) {
  const fig = h("figure", { class: "md-figure" });
  const key = d.id + "/" + file + "@" + d.updated;
  const got = D.images.get(key);
  if (got && got.url) fig.append(h("img", { src: got.url, alt: alt || file }));
  else if (got) fig.append(h("p", { class: "refused" }, "Could not read " + file + ": " + got.error));
  else {
    fig.append(h("p", { class: "meta" }, "Reading " + file + "…"));
    if (!D.pending.has(key)) {
      D.pending.add(key);
      readDocument(d.id, file).then((r) => r.arrayBuffer())
        .then((buf) => ({ url: URL.createObjectURL(new Blob([buf], { type: "image/svg+xml" })) }), (e) => ({ error: String(e.message || e) }))
        .then((v) => { D.images.set(key, v); D.pending.delete(key); if (S.place === "documents") fill(); });
    }
  }
  if (alt) fig.append(h("figcaption", { class: "meta" }, alt));
  return fig;
}

// Copy MASTER.md's text, as your inbox's Copy does; when the clipboard is refused, the text is shown selected.
export async function copyText(button, text, into) {
  const label = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
  } catch (e) {
    let box = into.querySelector("textarea.copy-box");
    if (!box) { box = h("textarea", { class: "copy-box", readonly: true, "aria-label": "MASTER.md, selected to copy" }); box.value = text; into.append(box); }
    box.focus();
    box.select();
    button.textContent = "Press Ctrl+C";
  }
  setTimeout(() => { button.textContent = label; }, 1800);
}

export function render(data, el) {
  const place = el;
  if (!data) {
    place.replaceChildren(header("Documents", S.err ? "The page could not read your documents: " + S.err + ". A server started before the page changed reads them once it is started again."
      : "Reading your files…"));
    return;
  }
  if (data.off) {
    place.replaceChildren(header("Documents", "Documents are off: your sources file names no seats file.", S.frame ? "Your sources file: " + S.frame.config : null));
    return;
  }
  const docs = data.documents || [];
  if (S.sub) {
    const cut = S.sub.indexOf("/");
    const id = cut < 0 ? S.sub : S.sub.slice(0, cut);
    return fillDocument(docs.find((d) => d.id === id), id, cut < 0 ? null : S.sub.slice(cut + 1) || null, el);
  }
  const head = header("Documents", docs.length ? plural(docs.length, "project") + " with a MASTER.md, newest first. Each agent keeps its projects' documents in its own cv folder."
    : "No project documents yet. A folder cv/<project>/ holding a MASTER.md in an agent's home shows here.");
  place.replaceChildren(head, h("div", { class: "docrows" }, docs.map((d) => h("a", { class: "docrow", href: docHref(d.id), "data-k": "doc:" + d.id },
    h("span", { class: "card-head" }, chip(d.agent, "seat"), d.project_name ? chip(d.project_name, "kind") : null, h("span", { class: "at" }, "Updated " + when(d.updated))),
    h("span", { class: "subject" }, d.title || d.slug),
    h("span", { class: "meta" }, plural(d.docs.length, "detailed document") + " · " + plural(d.diagrams.length, "diagram") + " · cv/" + d.slug)))));
}

function fillDocument(d, id, file, el) {
  const place = el;
  const all = h("a", { href: "#documents" }, "Documents");
  if (!d) { place.replaceChildren(header("No such document", "No document of yours has this id now.", null, crumbs(all, id))); return; }
  const isMaster = !file || file === d.master;
  const name = isMaster ? d.master : file;
  const sub = isMaster ? null : (d.docs || []).find((x) => x.file === file);
  const diagram = !isMaster && (d.diagrams || []).includes(file);
  const title = isMaster ? (d.title || d.slug) : sub ? (sub.title || file) : file;
  const trail = isMaster ? crumbs(all, d.title || d.slug) : crumbs(all, h("a", { href: docHref(d.id) }, d.title || d.slug), title);
  const meta = d.agent + "'s project" + (d.project_name ? " · " + d.project_name : "") + " · cv/" + d.slug + "/" + name + " · updated " + when(isMaster ? d.updated : sub ? sub.updated : d.updated);
  const parts = [header(title, null, meta, trail)];
  if (!isMaster && !sub && !diagram) {
    parts.push(h("p", { class: "empty" }, "This file is not one listed in " + (d.title || d.slug) + "'s folder."));
    place.replaceChildren(...parts);
    return;
  }
  const art = h("article", { class: "md" });
  if (diagram) art.append(diagramNode(d, file, null));
  else {
    const got = docText(d, name);
    if (!got) art.append(h("p", { class: "meta" }, "Reading " + name + "…"));
    else if (got.error) art.append(h("p", { class: "refused" }, "Could not read " + name + ": " + got.error));
    else art.append(renderMarkdown(got.text, { doc: d }));
    if (isMaster) {
      const copy = h("button", { type: "button", "data-k": "copy:" + d.id, disabled: !(got && !got.error) }, "Copy MASTER.md");
      const tools = h("div", { class: "doc-tools" }, copy);
      if (got && !got.error) copy.addEventListener("click", () => copyText(copy, got.text, tools));
      parts.push(tools);
    }
  }
  parts.push(art);
  if (isMaster && (d.docs.length || d.diagrams.length)) {
    const more = h("section", { class: "part" });
    if (d.docs.length) more.append(h("h2", { class: "label" }, "Detailed documents"), h("div", { class: "alist" }, d.docs.map((x) => h("div", { class: "arow" },
      h("a", { href: docHref(d.id, x.file), "data-k": "docf:" + d.id + ":" + x.file }, x.title || x.file), h("span", { class: "meta" }, x.file + " · " + when(x.updated))))));
    if (d.diagrams.length) more.append(h("h2", { class: "label", "data-space": d.docs.length ? "mt-20" : null }, "Diagrams"), h("div", { class: "alist" }, d.diagrams.map((f) => h("div", { class: "arow" },
      h("a", { href: docHref(d.id, f), "data-k": "docf:" + d.id + ":" + f }, f)))));
    parts.push(more);
  }
  place.replaceChildren(...parts);
}
