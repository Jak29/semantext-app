import { h } from "./dom.js";
import { S } from "./app.js";

// The pieces every place is drawn with: breadcrumbs, a fold that remembers being opened, a place's head, and a
// document's address.
// Breadcrumbs: each piece in its own box, so the separators keep their space.
export function crumbs(...pieces) {
  const nav = h("nav", { class: "crumbs", "aria-label": "Where you are" });
  pieces.forEach((p, i) => { if (i) nav.append(h("span", { "aria-hidden": "true" }, "›")); nav.append(p instanceof Node ? p : h("span", null, p)); });
  return nav;
}

export function disclosure(key, summary, cls) {
  const d = h("details", { class: cls || null });
  d.open = S.open.has(key);
  d.append(summary instanceof Node ? h("summary", { "data-k": key }, summary) : h("summary", { "data-k": key }, summary));
  d.addEventListener("toggle", () => { if (d.open) S.open.add(key); else S.open.delete(key); });
  return d;
}

export function header(title, sub, meta, crumbs) {
  return h("header", { class: "head" }, crumbs || null, h("h1", null, title), sub ? h("p", { class: "sub" }, sub) : null,
    meta ? h("p", { class: "meta" }, meta) : null);
}

// A document's address in the page: its folder (which opens its MASTER.md), or one file in it.
export function docHref(id, file) { return "#documents/" + encodeURIComponent(id) + (file ? "/" + encodeURIComponent(file) : ""); }
