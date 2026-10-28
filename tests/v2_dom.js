// Runs the v2 page's own modules in node, on a small stand-in for the browser's document, so their functions can be
// tested as written. Usage: node --experimental-vm-modules v2_dom.js <index.html> < test.js ; the test runs after the
// page has started, with the modules' exports in scope, and whatever it passes to report() is printed as JSON. Nothing
// here reads or writes any file but the page's own, and nothing is fetched: fetch answers never, so the page waits as it
// would on a slow server.
"use strict";
const fs = require("fs");
const path = require("path");
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
const context = {
  document, Node, console,
  window: { scrollY: 0, scrollTo() {}, addEventListener() {}, getSelection: () => ({ removeAllRanges() {}, addRange() {} }) },
  location: { hash: "", search: "" },
  navigator: { clipboard: { writeText: () => Promise.resolve() } },
  fetch: () => new Promise(() => {}),
  setInterval: () => 0, setTimeout: () => 0, clearTimeout() {},
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
  for (const [file, mod] of [[entries[0], entry], ...[...modules].filter(([f]) => f !== entries[0])]) {
    for (const [k, v] of Object.entries(mod.namespace)) {
      if (!(k in names)) names[k] = v;
      else if (file !== entries[0]) shared.add(k);
    }
  }
  for (const k of shared) if (!(k in entry.namespace)) delete names[k];
  const keys = Object.keys(names);
  const test = fs.readFileSync(0, "utf8");
  const run = vm.runInContext("(function (report, " + keys.join(", ") + ") {\n" + test + "\n})", context, { filename: "test.js" });
  await run((x) => { reported = x; }, ...keys.map((k) => names[k]));   // a test may return a promise; it is awaited
  process.stdout.write(JSON.stringify(reported === undefined ? null : reported));
})().catch((e) => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
