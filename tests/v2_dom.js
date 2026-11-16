// Runs the v2 page's own modules in node, on a small stand-in for the browser's document, so their functions can be
// tested as written. Usage: node --experimental-vm-modules v2_dom.js <index.html> < test.js ; the test runs after the
// page has started, with the modules' exports in scope, and whatever it passes to report() is printed as JSON. Nothing
// here reads or writes any file but the page's own, and nothing is fetched: fetch answers never, so the page waits as it
// would on a slow server.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

// What is focused and what is selected, as the browser keeps them: a node taken out of the page loses the focus, and a
// selection end inside it moves to the place it was taken from (the DOM's rule), so a test sees what a person would.
let active = null;
function detached(n, parent, index) {
  if (active && n.contains(active)) active = null;
  SEL.moved(n, parent, index);
  // an element out of the page forgets how far it was scrolled (a browser keeps no scroll for a detached box)
  const reset = (x) => { if (x.nodeType === 1) { x.scrollTop = 0; x.scrollLeft = 0; x.childNodes.forEach(reset); } };
  reset(n);
}
class Node {
  constructor() { this.parentNode = null; }
  contains(n) { for (let x = n; x; x = x.parentNode) if (x === this) return true; return false; }
  // 4: the other node comes later in the page, 2: earlier; plus 16 when this holds it, 8 when it holds this
  compareDocumentPosition(o) {
    const order = [];
    const walk = (x) => { order.push(x); (x.childNodes || []).forEach(walk); };
    walk(body);
    const i = order.indexOf(this), j = order.indexOf(o);
    if (i < 0 || j < 0 || i === j) return i === j && i >= 0 ? 0 : 1;
    return (j > i ? 4 : 2) | (this.contains(o) ? 16 : 0) | (o.contains(this) ? 8 : 0);
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  // before and after take nodes and strings; as in a browser, a string, null or undefined becomes a Text node ("null",
  // "undefined"), never nothing. A page that hands one of them a conditional's null draws that word, and a test sees it.
  before(...xs) { this._beside(xs, 0); }
  after(...xs) { this._beside(xs, 1); }
  _beside(xs, d) {
    const p = this.parentNode;
    if (!p) return;
    const kids = p._adopt(xs);   // taken out of where they were first, so the place is found after
    p.childNodes.splice(p.childNodes.indexOf(this) + d, 0, ...kids);
  }
  replaceWith(...xs) {
    const p = this.parentNode;
    if (!p) return;
    const at = p.childNodes.indexOf(this);
    const made = xs.map((x) => (x instanceof Node ? x : new Text(String(x))));
    for (const m of made) { if (m.parentNode) m.parentNode.removeChild(m); m.parentNode = p; }
    p.childNodes.splice(at, 1, ...made);
    this.parentNode = null;
    detached(this, p, at);
  }
}
class Text extends Node {
  constructor(text) { super(); this.data = String(text); this.nodeName = "#text"; this.nodeType = 3; }
  get textContent() { return this.data; }
  set textContent(v) { this.data = String(v); SEL.replaced(this); }
}
class Element extends Node {
  constructor(tag) {
    super();
    this.tagName = String(tag).toUpperCase();
    this.nodeName = this.tagName;
    this.nodeType = 1;
    this.childNodes = [];
    this.attributes = {};
    this.listeners = {};
    this.dataset = {};
    this.style = {};
    this.hidden = false;
    this.open = false;
    this.disabled = false;
    this._ss = 0; this._se = 0; this._sd = "none";
    this.scrollTop = 0; this.scrollLeft = 0;
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
  // _adopt writes every non-node as text (String(null) is "null"), as the DOM does for append, prepend, replaceChildren,
  // before and after: a null is never skipped here, so a page that passes one shows it.
  append(...kids) { this.childNodes.push(...this._adopt(kids)); }
  prepend(...kids) { this.childNodes.unshift(...this._adopt(kids)); }
  // insertBefore takes a node (null or undefined is a TypeError, as in a browser) and a node of this one, or null for the end
  insertBefore(n, ref) {
    if (!(n instanceof Node)) throw new TypeError("insertBefore: the first argument is not a Node");
    if (ref !== null && ref !== undefined && ref.parentNode !== this) throw new Error("NotFoundError: the reference is not a child");
    const kids = this._adopt([n]);
    this.childNodes.splice(ref ? this.childNodes.indexOf(ref) : this.childNodes.length, 0, ...kids);
    return n;
  }
  replaceChildren(...kids) {
    const gone = this.childNodes;
    this.childNodes = [];
    gone.forEach((n) => { n.parentNode = null; detached(n, this, 0); });
    this.append(...kids);
  }
  removeChild(n) {
    const i = this.childNodes.indexOf(n);
    if (i >= 0) this.childNodes.splice(i, 1);
    n.parentNode = null;
    if (i >= 0) detached(n, this, i);
    return n;
  }
  // A field holds a selection (start, end, direction); setting its value puts the caret at the end, as a browser does.
  _field() { return this.tagName === "INPUT" || this.tagName === "TEXTAREA"; }
  get value() { return this._value; }
  set value(v) { this._value = String(v); this._ss = this._se = this._value.length; this._sd = "none"; }
  get selectionStart() { return this._field() ? this._ss : undefined; }
  get selectionEnd() { return this._field() ? this._se : undefined; }
  get selectionDirection() { return this._field() ? this._sd : undefined; }
  setSelectionRange(s, e, d) {
    const n = this._value.length;
    this._ss = Math.max(0, Math.min(s, n)); this._se = Math.max(this._ss, Math.min(e, n)); this._sd = d || "none";
  }
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
  focus() { if (body.contains(this)) active = this; }
  blur() { if (active === this) active = null; }
  select() { this.setSelectionRange(0, this._value.length, "none"); }
  scrollIntoView() {}
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
    const attr = String(sel).match(/^\[([\w-]+)="(.*)"\]$/), id = String(sel).match(/^#([\w-]+)$/);
    if (attr) return this.all((e) => e.getAttribute(attr[1]) === attr[2])[0] || null;
    if (id) return this.all((e) => e.getAttribute("id") === id[1])[0] || null;
    const m = String(sel).match(/^([a-z]+)?(?:\.([\w-]+))?$/i);
    if (!m) return null;
    return this.all((e) => (!m[1] || e.tagName === m[1].toUpperCase()) && (!m[2] || e.classList.contains(m[2])))[0] || null;
  }
}
class Fragment extends Element { constructor() { super("#fragment"); } }

const byId = new Map();
const body = new Element("body");

// The one selection of the page. Its text is the page's text between its two ends, in document order, as Chrome reads
// a selection: a line break where a block ends (two where a paragraph does, one break for any run of them), so a
// triple-click, which ends at the start of the next block, reads with a break pair at its end. The page's text is a run
// of units, a character or a break; a point (node, offset) is the number of units before it, and a break that ends a
// block lies before every point that comes after the block's end (so a range ending there takes it) and after those
// inside it. A break with no text after it is not read.
const BLOCKS = new Set(["DIV", "P", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "DL", "DT", "DD", "SECTION", "ARTICLE",
  "HEADER", "FOOTER", "MAIN", "NAV", "ASIDE", "FORM", "FIELDSET", "TABLE", "TR", "PRE", "BLOCKQUOTE", "FIGURE", "FIGCAPTION", "DETAILS", "SUMMARY"]);
function flow(targets) {
  const units = [], at = targets.map(() => null);
  let pending = 0;
  const mark = (node, offset) => targets.forEach(([n, o], i) => { if (at[i] === null && n === node && o === offset) at[i] = units.length + (pending ? 1 : 0); });
  const walk = (x) => {
    if (x instanceof Text) {
      for (let c = 0; c <= x.data.length; c++) {
        mark(x, c);
        if (c < x.data.length) { if (pending) { units.push({ n: pending }); pending = 0; } units.push(x.data[c]); }
      }
      return;
    }
    x.childNodes.forEach((k, i) => { mark(x, i); walk(k); });
    mark(x, x.childNodes.length);
    if (BLOCKS.has(x.tagName)) pending = Math.max(pending, x.tagName === "P" ? 2 : 1);
  };
  walk(body);
  return { units, at };
}
const SEL = {
  a: null, ao: 0, f: null, fo: 0,
  get rangeCount() { return this.a ? 1 : 0; },
  get anchorNode() { return this.a; }, get anchorOffset() { return this.ao; },
  get focusNode() { return this.f; }, get focusOffset() { return this.fo; },
  get isCollapsed() { return !this.a || (this.a === this.f && this.ao === this.fo); },
  removeAllRanges() { this.a = this.f = null; this.ao = this.fo = 0; },
  collapse(n, o) { this.setBaseAndExtent(n, o, n, o); },   // a click's caret
  addRange(r) { this.a = r.startContainer; this.ao = r.startOffset; this.f = r.endContainer; this.fo = r.endOffset; },
  setBaseAndExtent(an, ao, fn, fo) {
    if (!body.contains(an) || !body.contains(fn)) throw new Error("a selection end outside the page");
    this.a = an; this.ao = ao; this.f = fn; this.fo = fo;
  },
  toString() {
    if (!this.a) return "";
    const { units, at } = flow([[this.a, this.ao], [this.f, this.fo]]);
    if (at[0] === null || at[1] === null) return "";
    return units.slice(Math.min(...at), Math.max(...at)).map((u) => (typeof u === "string" ? u : "\n".repeat(u.n))).join("");
  },
  // a node taken out: an end inside it goes to where it was taken from; a text node given new text: its ends go to 0
  // (and an end that sat in the parent, after the place the node left, counts one child fewer)
  moved(n, parent, index) {
    if (this.a && n.contains(this.a)) { this.a = parent; this.ao = index; }
    else if (this.a === parent && this.ao > index) this.ao--;
    if (this.f && n.contains(this.f)) { this.f = parent; this.fo = index; }
    else if (this.f === parent && this.fo > index) this.fo--;
  },
  replaced(t) {
    if (this.a === t) this.ao = 0;
    if (this.f === t) this.fo = 0;
  },
};
const document = {
  createElement: (tag) => new Element(tag),
  createElementNS: (ns, tag) => new Element(tag),   // the Prism mark and figure are SVG: drawn as elements here
  createTextNode: (t) => new Text(t),
  createDocumentFragment: () => new Fragment(),
  createRange: () => ({
    startContainer: body, startOffset: 0, endContainer: body, endOffset: 0,
    setStart(n, o) { this.startContainer = n; this.startOffset = o; },
    setEnd(n, o) { this.endContainer = n; this.endOffset = o; },
    selectNodeContents(n) { this.startContainer = this.endContainer = n; this.startOffset = 0; this.endOffset = n instanceof Text ? n.data.length : n.childNodes.length; },
  }),
  getElementById: (id) => {
    if (!byId.has(id)) { const e = new Element("div"); e.setAttribute("id", id); body.append(e); byId.set(id, e); }
    return byId.get(id);
  },
  querySelector: (sel) => body.querySelector(sel),
  // only the one selector the page asks for (the keyed text boxes whose scroll it holds); any other finds nothing
  querySelectorAll: (sel) => (sel === "textarea[data-k]" ? body.all((e) => e.tagName === "TEXTAREA" && e.hasAttribute("data-k")) : []),
  addEventListener() {},
  contains: (n) => body.contains(n),
  get activeElement() { return active; },
  body,
};

// The page is index.html and its ES modules beside it: the one module script it names is loaded with node's module
// loader (node runs this with --experimental-vm-modules), and each import is read from the page's own folder by its
// file name. The test is given every module's exports as names; nothing of the page is made global, so a module that
// uses a name it does not import fails here as it would in the browser. Where two modules export one name, app.js's
// is given, and a name only places share (render, mount) is not.
const page = fs.readFileSync(process.argv[2], "utf8");
const folder = path.dirname(process.argv[2]);
if (/<script>/.test(page)) throw new Error("the page should hold no inline script");
const entries = [...page.matchAll(/<script type="module" src="\/v2\/([\w-]+\.js)"><\/script>/g)].map((m) => m[1]);
if (entries.length !== 1) throw new Error("the page should load one module, and it loads " + entries.length);
let reported;
// The page's own refresh() is not exported: app.js hands it to setInterval and to a window focus listener, so the harness
// keeps both, as __ticks and __win (type -> [fn]), and a test may run the page's own refresh through them.
const __win = {}, __ticks = [];
const context = {
  document, Node, console,
  window: { scrollY: 0, scrollTo() {}, addEventListener(t, fn) { (__win[t] = __win[t] || []).push(fn); }, getSelection: () => SEL },
  location: { hash: "", search: "" },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  fetch: () => new Promise(() => {}),
  setInterval: (fn) => { __ticks.push(fn); return 0; }, setTimeout: () => 0, clearTimeout() {}, __win, __ticks,
  CSS: { escape: (s) => String(s) },
  URL, URLSearchParams, Blob: class {}, TextEncoder, TextDecoder,
};
vm.createContext(context);

// A plug-in's page module is imported by the page at /v2/plugin/<name>.js, as the server serves it; here it is read
// from the folder given as the third argument (the test's), and nothing else may be imported that way.
const plugins = process.argv[3] || null;
async function dynamic(spec) {
  const m = /^\/v2\/plugin\/([a-z0-9][a-z0-9_-]*)\.js$/.exec(spec);
  if (!m || !plugins) throw new Error("not found: " + spec);
  const file = path.join(plugins, m[1] + ".js");
  if (!fs.existsSync(file)) throw new Error("the server answered 404 for " + spec);
  const mod = new vm.SourceTextModule(fs.readFileSync(file, "utf8"), { context, identifier: spec });
  await mod.link((s) => { throw new Error("a page module imports nothing of the page: " + s); });
  await mod.evaluate();
  return mod;
}

const modules = new Map();
function load(name) {
  if (!/^[\w-]+\.js$/.test(name)) throw new Error("a module outside the page's folder: " + name);
  if (!modules.has(name)) {
    modules.set(name, new vm.SourceTextModule(fs.readFileSync(path.join(folder, name), "utf8"),
      { context, identifier: name, importModuleDynamically: dynamic }));
  }
  return modules.get(name);
}

(async () => {
  const entry = load(entries[0]);
  await entry.link((spec) => load(spec.replace(/^\.\//, "")));
  await entry.evaluate();
  const names = {};
  const shared = new Set();
  // The parts moved from the home page (own*.js) reuse the page's short names, so theirs are given apart, as moved.<name>.
  const moved = {};
  for (const [file, mod] of [[entries[0], entry], ...[...modules].filter(([f]) => f !== entries[0])]) {
    for (const [k, v] of Object.entries(mod.namespace)) {
      if (file.startsWith("own")) { if (!(k in moved)) moved[k] = v; continue; }
      if (!(k in names)) names[k] = v;
      else if (file !== entries[0]) shared.add(k);
    }
  }
  names.moved = moved;
  for (const k of shared) if (!(k in entry.namespace)) delete names[k];
  const keys = Object.keys(names);
  const test = fs.readFileSync(0, "utf8");
  const run = vm.runInContext("(function (report, " + keys.join(", ") + ") {\n" + test + "\n})", context, { filename: "test.js" });
  await run((x) => { reported = x; }, ...keys.map((k) => names[k]));   // a test may return a promise; it is awaited
  process.stdout.write(JSON.stringify(reported === undefined ? null : reported));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
