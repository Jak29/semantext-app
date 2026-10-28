// The page's DOM helpers, the only way any module makes an element.
// Every piece of the person's text is set as text: elements are made with createElement, and words go in as text
// nodes, never parsed as markup. The page only reads: it sends the X-Semantext header with every read, runs nothing,
// and writes nothing anywhere.

export const $ = (id) => document.getElementById(id);
const PROPS = new Set(["open", "hidden", "type", "value", "disabled", "checked", "tabIndex", "placeholder"]);

export function h(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "on") for (const [type, fn] of Object.entries(v)) node.addEventListener(type, fn);
    else if (PROPS.has(k)) node[k] = v;
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    node.append(kid instanceof Node ? kid : String(kid));
  }
  return node;
}
