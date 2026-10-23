// Runs the v2 page's own script in node, on a small stand-in for the browser's document, so its functions can be
// tested as written. Usage: node v2_dom.js <page.html> < test.js ; the test is run in the page's own scope after the
// page's script, and whatever it passes to report() is printed as JSON. Nothing here reads or writes any file but the
// page, and nothing is fetched: fetch answers never, so the page waits as it would on a slow server.
"use strict";
const fs = require("fs");
const vm = require("vm");

class Node {
  constructor() { this.parentNode = null; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  replaceWith(...xs) {
    const p = this.parentNode;
    if (!p) return;
    const at = p.childNodes.indexOf(this);
    const made = xs.map((x) => (x instanceof Node ? x : new Text(String(x))));
    for (const m of made) { if (m.parentNode) m.parentNode.removeChild(m); m.parentNode = p; }
    p.childNodes.splice(at, 1, ...made);
    this.parentNode = null;
  }
}
class Text extends Node {
  constructor(text) { super(); this.data = String(text); this.nodeName = "#text"; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); }
}
class Element extends Node {
  constructor(tag) {
    super();
    this.tagName = String(tag).toUpperCase();
    this.nodeName = this.tagName;
    this.childNodes = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this.open = false;
    this.disabled = false;
    this.value = "";
    this.className = "";
    const self = this;
    this.classList = {
      add: (...c) => { const s = new Set(self.className.split(/\s+/).filter(Boolean)); c.forEach((x) => s.add(x)); self.className = [...s].join(" "); },
      remove: (...c) => { self.className = self.className.split(/\s+/).filter((x) => x && !c.includes(x)).join(" "); },
      contains: (c) => self.className.split(/\s+/).includes(c),
    };
  }
  get children() { return this.childNodes.filter((n) => n instanceof Element); }
  _adopt(kids) {
    const out = [];
    for (const k of kids) {
      if (k instanceof Fragment) { out.push(...k.childNodes.splice(0)); continue; }
      const n = k instanceof Node ? k : new Text(String(k));
      if (n.parentNode) n.parentNode.removeChild(n);
      out.push(n);
    }
    out.forEach((n) => { n.parentNode = this; });
    return out;
  }
  append(...kids) { this.childNodes.push(...this._adopt(kids)); }
  prepend(...kids) { this.childNodes.unshift(...this._adopt(kids)); }
  replaceChildren(...kids) { this.childNodes.forEach((n) => { n.parentNode = null; }); this.childNodes = []; this.append(...kids); }
  removeChild(n) { const i = this.childNodes.indexOf(n); if (i >= 0) this.childNodes.splice(i, 1); n.parentNode = null; return n; }
  setAttribute(k, v) {
    this.attributes[k] = String(v);
    if (k.startsWith("data-")) this.dataset[k.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(v);
    if (k === "id") this.id = String(v);
  }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type) { for (const fn of this.listeners[type] || []) fn({ type, currentTarget: this, target: this, preventDefault() {} }); }
  click() { this.dispatch("click"); }
  focus() {}
  select() {}
  scrollIntoView() {}
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(v) { this.replaceChildren(String(v)); }
  // every descendant element, depth first; the tests select with plain functions, not CSS
  all(pred) {
    const out = [];
    const walk = (n) => { for (const c of n.childNodes) if (c instanceof Element) { if (!pred || pred(c)) out.push(c); walk(c); } };
    walk(this);
    return out;
  }
  querySelector(sel) {
    const m = String(sel).match(/^([a-z]+)?(?:\.([\w-]+))?$/i);
    if (!m) return null;
    return this.all((e) => (!m[1] || e.tagName === m[1].toUpperCase()) && (!m[2] || e.classList.contains(m[2])))[0] || null;
  }
}
class Fragment extends Element { constructor() { super("#fragment"); } }

const byId = new Map();
const body = new Element("body");
const document = {
  createElement: (tag) => new Element(tag),
  createTextNode: (t) => new Text(t),
  createDocumentFragment: () => new Fragment(),
  createRange: () => ({ selectNodeContents() {} }),
  getElementById: (id) => {
    if (!byId.has(id)) { const e = new Element("div"); e.setAttribute("id", id); body.append(e); byId.set(id, e); }
    return byId.get(id);
  },
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
  contains: (n) => body.contains(n),
  get activeElement() { return null; },
  body,
};

const page = fs.readFileSync(process.argv[2], "utf8");
const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (scripts.length !== 1) throw new Error("the page should hold one script, and it holds " + scripts.length);
let reported;
const context = {
  document, Node, console,
  window: { scrollY: 0, scrollTo() {}, addEventListener() {}, getSelection: () => ({ removeAllRanges() {}, addRange() {} }) },
  location: { hash: "", search: "" },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  fetch: () => new Promise(() => {}),
  setInterval: () => 0, setTimeout: () => 0, clearTimeout() {},
  CSS: { escape: (s) => String(s) },
  URL, URLSearchParams, Blob: class {}, TextEncoder, TextDecoder,
  report: (x) => { reported = x; },
};
vm.createContext(context);
vm.runInContext(scripts[0], context, { filename: "v2.html" });
const test = fs.readFileSync(0, "utf8");
vm.runInContext(test, context, { filename: "test.js" });
process.stdout.write(JSON.stringify(reported === undefined ? null : reported));
