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

// A fold remembers being opened (S.open). `then`, where given, runs when the PERSON opens or shuts it (a shelf that
// draws its cards only while open draws again).
//
// Law (D8): only a person's own toggle counts. Setting d.open on a details this very draw made fires "toggle" in Chrome
// (measured), even when the details is already out of the page; a handler that drew again on that made a new details,
// which fired again, without end (about 2,700 mutation records a second, and a mouse could neither select nor fold). So
// a toggle is acted on only when the details is in the page and says something other than what is remembered: the
// event the draw itself caused always says what is remembered, and is let go.
export function disclosure(key, summary, cls, then) {
  const d = h("details", { class: cls || null });
  d.open = S.open.has(key);
  d.append(summary instanceof Node ? h("summary", { "data-k": key }, summary) : h("summary", { "data-k": key }, summary));
  d.addEventListener("toggle", () => {
    if (!document.contains(d)) return;               // a draw's own details, already taken out again
    if (d.open === S.open.has(key)) return;          // the draw's own event: it says what is remembered
    if (d.open) S.open.add(key); else S.open.delete(key);
    if (then) then();
  });
  return d;
}

export function header(title, sub, meta, crumbs) {
  return h("header", { class: "head" }, crumbs || null, h("h1", null, title), sub ? h("p", { class: "sub" }, sub) : null,
    meta ? h("p", { class: "meta" }, meta) : null);
}

// A document's address in the page: its folder (which opens its MASTER.md), or one file in it.
export function docHref(id, file) { return "#documents/" + encodeURIComponent(id) + (file ? "/" + encodeURIComponent(file) : ""); }
