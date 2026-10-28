// Markdown, drawn as text: no document's words are ever parsed as markup.
import { h } from "./dom.js";
import { docHref } from "./parts.js";
import { diagramNode } from "./documents.js";

// ---- markdown, read safely: headings, paragraphs, lists, quotes, code, tables, bold, italics, inline code, links and
// diagrams. Every node is built from text, so HTML written in a document shows as the text it is.
const MD_ITEM = /^\s*([-*]|\d+[.)])\s+/;
const MD_INLINE = /(`[^`]+`)|(!\[[^\]]*\]\([^)\s]+\))|(\[[^\]]+\]\([^)\s]+\))|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)/g;

export function renderMarkdown(text, ctx) {
  const out = document.createDocumentFragment();
  const lines = String(text || "").replace(/\r\n?/g, "\n").split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    let m;
    if (/^\s*$/.test(line)) { i++; continue; }
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.append(h("pre", null, h("code", null, buf.join("\n"))));
      continue;
    }
    if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      const head = document.createElement("h" + Math.min(m[1].length + 1, 6));
      mdInline(head, m[2], ctx);
      out.append(head);
      i++;
      continue;
    }
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) { out.append(document.createElement("hr")); i++; continue; }
    if (/^>/.test(line)) {
      const buf = [];
      while (i < lines.length && /^>/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ""));
      const quote = document.createElement("blockquote");
      quote.append(renderMarkdown(buf.join("\n"), ctx));
      out.append(quote);
      continue;
    }
    if (/^\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\|?\s*:?-{3,}/.test(lines[i + 1])) {
      const rows = [];
      while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) rows.push(lines[i++]);
      out.append(mdTable(rows, ctx));
      continue;
    }
    if (MD_ITEM.test(line)) {
      const list = document.createElement(/^\s*\d+[.)]\s+/.test(line) ? "ol" : "ul");
      while (i < lines.length && MD_ITEM.test(lines[i])) {
        let item = lines[i++].replace(MD_ITEM, "");
        while (i < lines.length && /^\s{2,}\S/.test(lines[i]) && !MD_ITEM.test(lines[i])) item += " " + lines[i++].trim();
        const li = document.createElement("li");
        mdInline(li, item, ctx);
        list.append(li);
      }
      out.append(list);
      continue;
    }
    const buf = [];
    while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,6}\s|```|>|\|)/.test(lines[i]) && !MD_ITEM.test(lines[i])) buf.push(lines[i++].trim());
    if (!buf.length) buf.push(lines[i++].trim());
    const para = document.createElement("p");
    mdInline(para, buf.join(" "), ctx);
    out.append(para);
  }
  return out;
}

export function mdInline(parent, text, ctx) {
  let last = 0;
  for (const m of text.matchAll(MD_INLINE)) {
    if (m.index > last) parent.append(document.createTextNode(text.slice(last, m.index)));
    const token = m[0];
    if (m[1]) parent.append(h("code", null, token.slice(1, -1)));
    else if (m[2]) {
      const parts = token.match(/^!\[([^\]]*)\]\(([^)\s]+)\)$/);
      parent.append(mdDiagram(parts[1], parts[2], ctx));
    } else if (m[3]) {
      const parts = token.match(/^\[([^\]]+)\]\(([^)\s]+)\)$/);
      parent.append(mdLink(parts[1], parts[2], ctx));
    } else if (m[4]) {
      const strong = document.createElement("strong");
      mdInline(strong, token.slice(2, -2), ctx);
      parent.append(strong);
    } else if (m[5]) {
      const em = document.createElement("em");
      mdInline(em, token.slice(1, -1), ctx);
      parent.append(em);
    }
    last = m.index + token.length;
  }
  if (last < text.length) parent.append(document.createTextNode(text.slice(last)));
}

// A link to https opens in a new tab, with no way back to this page; a relative .md link that names a document of the
// same folder opens it here; anything else is plain text, its address beside it.
export function mdLink(text, href, ctx) {
  if (/^https:\/\/[^\s]+$/i.test(href)) return h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
  const d = ctx && ctx.doc;
  if (d && /^[^\/\\:?#]+\.md$/i.test(href)) {
    if (d.master && href.toLowerCase() === d.master.toLowerCase()) return h("a", { href: docHref(d.id) }, text);
    if ((d.docs || []).some((x) => x.file === href)) return h("a", { href: docHref(d.id, href) }, text);
  }
  return document.createTextNode(text + " (" + href + ")");
}

export function mdDiagram(alt, src, ctx) {
  const d = ctx && ctx.doc;
  if (d && /^[^\/\\:?#]+\.svg$/i.test(src) && (d.diagrams || []).includes(src)) return diagramNode(d, src, alt);
  return h("figure", { class: "md-figure" }, h("figcaption", { class: "meta" }, "[diagram: " + (alt || src) + "]"));
}

export function mdTable(rows, ctx) {
  const cells = (row) => row.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  const cell = (tag, c) => { const n = document.createElement(tag); mdInline(n, c, ctx); return n; };
  return h("div", { class: "md-table-wrap" }, h("table", null,
    h("thead", null, h("tr", null, cells(rows[0]).map((c) => cell("th", c)))),
    h("tbody", null, rows.slice(2).map((row) => h("tr", null, cells(row).map((c) => cell("td", c)))))));
}
