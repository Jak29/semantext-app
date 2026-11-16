// Documents: each cv/<project> folder with a MASTER.md, read in the page.
import { h } from "./dom.js";
import { plural, when } from "./words.js";
import { crumbs, docHref, header } from "./parts.js";
import { fill, S } from "./app.js";
import { chip } from "./cards.js";
import { renderMarkdown } from "./markdown.js";
import { findAgain, placeOf } from "./selection.js";

// The scroll inside a keyed text box (the copy box's own scroll, D13; moved here from selection.js, whose size is capped). A
// node that is taken out of the page and put back (settle) or made again starts at the top, so a person who scrolled through
// a long text to read it was sent back to the start at every read. Called before a draw; call what it returns after. Only a
// box that has been scrolled is held, and only a keyed one (found again by its key and which of its key it is). Limit: a
// scroller that is not a keyed text box (a code block with its own scroll) is not held.
export function holdScroll() {
  const held = [];
  for (const el of document.querySelectorAll("textarea[data-k]")) {
    if (el.scrollTop || el.scrollLeft) held.push({ el, top: el.scrollTop, left: el.scrollLeft, where: placeOf(el) });
  }
  if (!held.length) return () => {};
  // mark(), for a draw that finishes later (keep()): each box as the draw's synchronous part left it. At the finish a box the
  // person scrolled since is theirs and is not put back (close1 finding 5: an async render (D25) puts the new box in the page
  // during the wait, and the old scroll was written over the person's). A box made after the mark starts at the top, so one
  // found away from the top was scrolled by the person. Limit: a person who scrolls a new box and back to the very top leaves
  // nothing to tell from a box nobody touched, and the old scroll is put back.
  const find = (x) => (document.contains(x.el) ? x.el : findAgain(x.where));
  let marked = false;
  const restore = () => {
    for (const x of held) {
      const el = find(x);
      if (!el) continue;
      const theirs = x.mark && x.mark.el === el ? el.scrollTop !== x.mark.top || el.scrollLeft !== x.mark.left : el !== x.el && (el.scrollTop || el.scrollLeft);
      if (marked && theirs) continue;
      if (el.scrollTop !== x.top) el.scrollTop = x.top;
      if (el.scrollLeft !== x.left) el.scrollLeft = x.left;
    }
  };
  return Object.assign(restore, { mark: () => { marked = true; for (const x of held) { const el = find(x); x.mark = el ? { el, top: el.scrollTop, left: el.scrollLeft } : null; } } });
}

// ---------------------------------------------------------------- Documents
// Every project folder an agent keeps in its cv/ with a MASTER.md, as your inbox's Documents lists them, read here:
// MASTER.md (with its Copy button), the detailed documents beside it, and its diagrams. The server reads only a file its
// documents reader lists in a listed folder; this page sets every word of it as text.
export const D = { text: new Map(), images: new Map(), pending: new Set(), box: null };

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

// The text shown selected when the clipboard was refused stays through the page's draws (every ten seconds it draws
// again, and a box made only by the click would be destroyed with its focus and selection) until you copy it, hide it,
// or leave this document: D.box is {id, text}, and the document's draw puts the box back. `id` is the document's, or
// null for a box that belongs to no one document.
export function hideBox() {
  D.box = null;
  fill();
}
// Whose box may be shown at this address: a document's own id (its address's first piece), or "diffmap:<folder>/<file>" for
// a spec (D12: Diffmap's command box was destroyed by the next draw, and D.box kept its command after you left). A box with
// id null belongs to no one place and is kept. Called by each place's draw and when the page moves to another place.
export function boxOwner(place, sub) {
  if (place === "documents") return sub ? sub.split("/")[0] : undefined;
  if (place === "diffmap") return sub ? "diffmap:" + sub : undefined;
  return undefined;
}
export function leaveBox() {
  if (D.box && D.box.id !== null && D.box.id !== boxOwner(S.place, S.sub)) D.box = null;
}
// `label` names what the box holds, for a screen reader: MASTER.md's text, or (Diffmap) a shell command.
export function boxNodes(label = "MASTER.md, selected to copy") {
  const box = h("textarea", { class: "copy-box", readonly: true, "aria-label": label, "data-k": "copybox" });
  box.value = D.box.text;
  box.addEventListener("copy", () => setTimeout(hideBox, 0));   // after the browser has taken the copy
  return [box, h("button", { type: "button", class: "toggle small", "data-k": "copybox-hide", on: { click: hideBox } }, "Hide")];
}

// Copy MASTER.md's text, as your inbox's Copy does; when the clipboard is refused, the text is shown selected.
export async function copyText(button, text, into, id, boxLabel) {
  const label = button.textContent;
  try {
    await navigator.clipboard.writeText(text);
    D.box = null;
    Array.from(into.children).filter((c) => (c.dataset.k || "").startsWith("copybox")).forEach((c) => c.remove());   // copied: the box is done
    button.textContent = "Copied";
  } catch (e) {
    D.box = { id: id === undefined ? null : id, text };
    let box = into.querySelector("textarea.copy-box");
    if (!box) { into.append(...boxNodes(boxLabel)); box = into.querySelector("textarea.copy-box"); }
    box.focus();
    box.select();
    button.textContent = "Press Ctrl+C";
  }
  setTimeout(() => { button.textContent = label; }, 1800);
}

export function render(data, el) {
  const place = el;
  leaveBox();   // you left the document the box was for
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
      if (got && !got.error) {
        copy.addEventListener("click", () => copyText(copy, got.text, tools, d.id));
        if (D.box && D.box.text === got.text) tools.append(...boxNodes());   // a box shown when the clipboard was refused stays
        else D.box = null;                                                   // the document's words moved on: the box is stale
      }
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
