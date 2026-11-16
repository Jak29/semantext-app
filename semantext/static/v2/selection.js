// What you have selected survives a re-draw. The page draws again every ten seconds, on a window focus, and when a band
// or a drawer reads again; a draw replaces elements, and the browser drops a selection that lived in a replaced one (in
// a field it collapses to the caret; in the page's words it is gone). Reading a card's words to copy them, with a
// quiet page re-drawing under you, is the case this is for.
//
// The choice, and why: the selection is put back after the draw, and the draw is not held. Holding a part back while words
// are selected would show a card that has since been answered, or a count that has since moved, for as long as you keep
// them selected, and would hold back a draw you asked for yourself. Putting it back never delays what the page shows.
//
// Two layers, because a selection put back by guessing is the weaker one (a triple-click ends at the start of the next
// block: measured in Chrome, about three in ten cross-block selections do not survive a count of characters):
//  1. A draw whose output is the same as what is drawn does not replace it (settle): the nodes that were drawn are put
//     back, so the selection ends are the very nodes they were. Only where the data they were drawn from has not changed
//     since (see keep() in app.js), because a node keeps the handlers of the draw that made it.
//  2. A draw that did change the part puts the selection back by where it stood.
//
// Laws:
//  - Only a selection you hold at the moment of the draw is put back. Nothing is remembered between draws, so words you
//    have released (a click elsewhere, Escape) are never brought back.
//  - Words are put back only when they are the same words: a rebuilt selection is kept only if its text equals the saved
//    text exactly. Tried in order: the same nodes, if they are in the page again; each end by its path (the nearest keyed
//    element around it, its data-k else its id, which of those sharing the key it is, the child indexes down, the offset);
//    each end by its count of characters into its keyed element; the same words looked for inside the one element that
//    held them, used only if they occur once there. Else the selection is let go: a selection on other words than yours,
//    or in another copy of the same card, would be worse than none.
//  - A field keeps its start, end and direction, clamped to what the field now holds, and only a field you are in.
//    A field is found again by its key and which of the elements sharing the key it was.
// Limits: a selection whose ends sit in no keyed element is put back only if its own nodes come back; words that changed or
// moved are not followed; a selection across a changed block is put back only if its text still reads the same; words that
// cross a block edge are not searched for (the search reads the element's text, which has no line breaks); a node put back
// by settle keeps the handlers of the draw that made it, so a draw whose data has changed never reuses a node.
// Rounds three to five (the attacks of the unchanged read, the late finish and the interleave): a plug-in place draws after its
// module is imported, so keep() holds the selection through the wait and restores it when the draw finishes. That finish may
// take back only what the DRAW took, never what the person did while it waited:
//  - A text selection is put back only if it lay wholly inside the region the draw filled (an end ON the region, within its
//    children, is inside: D23), only if its text then reads exactly the same, and only if it is a state the PAGE left. The
//    restore keeps a CHAIN of those states (D22): the mark taken when the draw returns, and each state a draw of the page's
//    own, begun on a state in the chain, ended in (the problems banner, "Checked HH:MM"). A selection off the chain is the
//    person's (a click's caret, a release, other words) and is never touched; one with an end outside the region that did
//    not survive is let go (D14). A second draw of the same region that begins on a state in the chain takes over the first
//    one's held selection, because what it would hold is the damage the first did.
//  - A field the draw replaced has its range put back (D21) unless the person moved the focus or the page's selection since
//    (close1); an unkeyed one is found again by where it stood, only if the whole region reads as it did. A waiting draw
//    that saw the person act is let go for good; a newer draw of its region, or leaving the place, drops it (app.js).
//  - A plug-in's output is never settled, so a module's later updates reach the nodes the page shows (D16).
// Also held: the plug-in tabs, the problems and a copy box's own scroll (holdScroll). Limits: a module's own timer draws are
// not held; a person's change that lands exactly on a chain state reads as the page's; an unkeyed field in a region that
// changed anywhere, or that the person typed into, is let go; a toggle after a draw replaced the fold is let go.

const noop = () => {};
const TEXT = 3, ELEMENT = 1;
const kids = (n) => Array.from(n.childNodes);
const size = (n) => (n.nodeType === TEXT ? n.data.length : n.childNodes.length);

function fieldSelection(el) {
  if (!el || typeof el.setSelectionRange !== "function") return null;
  try {
    const s = el.selectionStart, e = el.selectionEnd;
    return typeof s === "number" && typeof e === "number" ? { s, e, d: el.selectionDirection || "none" } : null;
  } catch (x) { return null; }   // a field of a kind that holds no selection (a checkbox) says nothing
}

// ---------------------------------------------------------------- keys: which element is meant, after a draw
// An element the page can find again: its data-k, else its id. Several elements can share one key (the same card in the
// place and in a drawer), so an element is its key and which of those it is, in page order.
function keyOf(el) {
  const k = el.getAttribute("data-k");
  if (k) return { t: "k", v: k };
  const id = el.getAttribute("id");
  return id ? { t: "i", v: id } : null;
}
const hasKey = (n, key) => n.nodeType === ELEMENT && n.getAttribute(key.t === "k" ? "data-k" : "id") === key.v;
function keyed(key) {
  const out = [];
  const walk = (n) => { if (n.nodeType !== ELEMENT) return; if (hasKey(n, key)) out.push(n); for (const c of n.childNodes) walk(c); };
  walk(document.body);
  return out;
}
const rootOf = (d) => keyed(d.key)[d.occ] || null;

// A field or control, as findAgain() finds it after a draw.
export function placeOf(el) {
  const k = el && el.dataset ? el.dataset.k : null;
  if (!k) return null;
  const key = { t: "k", v: k };
  return { key, occ: Math.max(0, keyed(key).indexOf(el)) };
}
export const findAgain = (where) => (where ? rootOf(where) : null);

// Where a node stands: the nearest keyed element around it (or it), which of its key it is, and the child indexes down.
function describe(node) {
  const path = [];
  for (let el = node; el; el = el.parentNode) {
    if (el.nodeType === ELEMENT) {
      const key = keyOf(el);
      if (key) { const occ = keyed(key).indexOf(el); return occ < 0 ? null : { key, occ, path }; }
    }
    if (!el.parentNode) return null;
    path.unshift(kids(el.parentNode).indexOf(el));
  }
  return null;
}
function resolve(d) {
  let n = rootOf(d);
  for (let i = 0; n && i < d.path.length; i++) n = n.childNodes[d.path[i]];
  return n || null;
}

// (childNodes is a NodeList in a browser: Array.from, not its own methods.)
const length = (n) => (n.nodeType === TEXT ? n.data.length : kids(n).reduce((sum, c) => sum + length(c), 0));
const textOf = (n) => (n.nodeType === TEXT ? n.data : kids(n).map(textOf).join(""));

// How many characters of text lie inside `root` before the point (node, offset).
function before(root, node, offset) {
  let n = 0, found = false;
  const walk = (x) => {
    if (x === node) {
      if (x.nodeType === TEXT) n += offset;
      else for (let i = 0; i < offset; i++) n += length(x.childNodes[i]);
      found = true;
      return;
    }
    if (x.nodeType === TEXT) { n += x.data.length; return; }
    for (const c of x.childNodes) { walk(c); if (found) return; }
  };
  walk(root);
  return found ? n : null;
}
// The point inside `root` that lies after n characters of its text. Between two text nodes both are the same place:
// the start of a selection takes the later node and its end the earlier, so the words are inside their own node.
function at(root, n, start) {
  let left = n, last = null;
  const walk = (x) => {
    if (x.nodeType === TEXT) {
      last = x;
      if (start ? left < x.data.length : left <= x.data.length) return { node: x, offset: left };
      left -= x.data.length;
      return null;
    }
    for (const c of x.childNodes) { const p = walk(c); if (p) return p; }
    return null;
  };
  return walk(root) || (last ? { node: last, offset: last.data.length } : { node: root, offset: 0 });
}

// A restore is a function(late) with mark(token), drop(token) and again(); keep() marks a late draw once its synchronous part is
// done, and calls restore(true) at its finish. What the person changed between the two is theirs (D15); what the PAGE did is
// not (D22): a selection is the page's if it is a state the page left (the chain below); a replaced field's, see holdField.
const getSel = () => (typeof window.getSelection === "function" ? window.getSelection() : null);
const nothing = Object.assign(() => {}, { mark() {}, drop() {}, again: () => null });
const ends = (sel) => (sel ? [sel.rangeCount, sel.anchorNode, sel.anchorOffset, sel.focusNode, sel.focusOffset] : []);
const sameEnds = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);
const theirs = (take, marked) => !sameEnds(take(), marked);

// The text selections whose draw is still waiting, each with its chain: the states the page left while it waited, the mark
// first. A draw of the page's own (the problems banner, "Checked") that BEGINS on a state in a chain adds the state it ends
// on; one that begins off the chain began on the person's change, and what it leaves is not added. Cost: one size check per
// keep when no draw waits; with one waiting, a comparison of five values per chain state (at most CHAIN) per keep.
const watchers = new Set(), CHAIN = 16;
const known = (w, e) => w.chain.some((c) => sameEnds(c, e));
const note = (w, e) => { if (!known(w, e)) { w.chain.push(e); if (w.chain.length > CHAIN) w.chain.shift(); } };

// Where an element stood under `root` (the child index at each level), and what stands there now if it reads exactly as the
// field did (shell: tag, attributes, class, state and value) and is not `old` itself.
const pathIn = (root, el) => { const p = []; for (let n = el; n && n !== root; n = n.parentNode) p.unshift(kids(n.parentNode).indexOf(n)); return p; };
function sameAt(root, via, old) {
  let n = root;
  for (const i of via.path) n = n && n.childNodes[i];
  return n && n !== old && n.nodeType === ELEMENT && shell(n) === via.read ? n : null;
}

function holdField(a, region) {
  const was = fieldSelection(a);
  if (!was) return null;
  const where = placeOf(a);
  // An unkeyed field is found again by where it stood in the region after a late draw (D21), only if the whole region reads
  // as it did (close1 #2: the empty boxes of a list read alike; a row moved put the focus on ANOTHER row's box).
  const via = !where && region && region !== a && region.contains(a) ? { path: pathIn(region, a), read: shell(a), all: serial(region) } : null;
  const again = (late) => (document.contains(a) ? a : where ? findAgain(where) : late && via && serial(region) === via.all ? sameAt(region, via, a) : null);
  const field = (late) => { const el = again(late); return el && document.activeElement === el ? el : null; };
  const caret = () => { const f = field(true), c = f && fieldSelection(f); return c ? [c.s, c.e, c.d] : []; };
  // close1 #1: an async render (D25) shows the new field DURING the wait, so a replaced field can be acted on. The person
  // acted if the focus or the page's selection moved since the mark (keep() asks acted() before it gives a focus back).
  const person = () => [document.activeElement, ...ends(getSel())];
  let marked = [], replaced = false, seen = null, did = null;
  const acted = () => (did === null ? (did = seen !== null && !sameEnds(person(), seen)) : did);
  const restore = (late) => {
    const el = field(late);   // only the field you are in: another's caret is not moved
    if (!el) return;
    // A caret you moved while the draw waited is yours; a field the draw replaced is put back (D21) unless you acted.
    if (late && (replaced ? acted() : theirs(caret, marked))) return;
    const now = fieldSelection(el);
    if (!now || (now.s === was.s && now.e === was.e && now.d === was.d)) return;
    const n = String(el.value || "").length;
    try { el.setSelectionRange(Math.min(was.s, n), Math.min(was.e, n), was.d); } catch (x) { /* a field that takes no selection */ }
  };
  return Object.assign(restore, { field: true, again, acted, drop: noop, mark: () => { replaced = !document.contains(a); marked = caret(); seen = person(); did = null; } });
}

const classOf = (el) => (typeof el.className === "string" ? el.className : el.getAttribute("class") || "");
// The deepest element that holds both nodes.
function around(a, b) {
  const up = new Set();
  for (let x = a; x; x = x.parentNode) up.add(x);
  for (let y = b; y; y = y.parentNode) if (up.has(y)) return y.nodeType === ELEMENT ? y : y.parentNode;
  return null;
}

// `region`, where a draw is to finish later (a plug-in place): the element the draw fills. A late restore puts back only a
// selection wholly inside it whose text reads exactly the same (D14); one end inside and one outside was damaged by the draw
// (the end inside went to the region's start), and what is left is not what was selected, so it is let go.
function holdText(region) {
  const sel = getSel();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return null;
  const saved = String(sel);
  if (!saved) return null;
  // D23: a point ON the region itself, within its children (a row to (#place, 2)), is inside it as a point in a child is.
  const inside = (n) => region.contains(n);
  const whole = !region || (inside(sel.anchorNode) && inside(sel.focusNode));
  const end = (node, offset) => {
    const d = describe(node), root = d && rootOf(d);
    return { node, offset, d, n: root ? before(root, node, offset) : null };
  };
  const A = end(sel.anchorNode, sel.anchorOffset), F = end(sel.focusNode, sel.focusOffset);
  const forward = sel.anchorNode === sel.focusNode ? sel.anchorOffset <= sel.focusOffset
    : !!(sel.anchorNode.compareDocumentPosition(sel.focusNode) & 4);   // 4: the focus comes later in the page
  const top = around(sel.anchorNode, sel.focusNode);
  const scope = top && top.nodeType === ELEMENT ? { d: describe(top), tag: top.tagName, cls: classOf(top) } : null;
  const w = { region, chain: [], owner: null, restore: null, gone: false };
  const apply = (late) => {
    const now = window.getSelection();
    if (!now) return;
    if (late && (w.gone || !known(w, ends(now)))) return;   // released, made again or moved by the person while the draw waited (D15); not one the page left (D22)
    if (!now.isCollapsed && String(now) === saved && document.contains(now.anchorNode) && document.contains(now.focusNode)) return;   // it survived
    if (late && !whole) { now.removeAllRanges(); return; }   // D14: not wholly in what the draw made, so it cannot be known to be the same words
    // The anchor is where the selection began and the focus where it ends, so a selection made backwards stays backwards.
    const put = (a, f) => {
      try { now.setBaseAndExtent(a.node, a.offset, f.node, f.offset); } catch (x) { return false; }
      return String(now) === saved;
    };
    const point = (e) => {
      const node = e.d && resolve(e.d);
      return node && e.offset <= size(node) ? { node, offset: e.offset } : null;
    };
    if (document.contains(A.node) && document.contains(F.node) && put(A, F)) return;   // the very nodes are back in the page
    const pa = point(A), pf = point(F);
    if (pa && pf && put(pa, pf)) return;   // each end where it stood
    const ra = A.d && rootOf(A.d), rf = F.d && rootOf(F.d);
    if (ra && rf && A.n !== null && F.n !== null) {   // each end by its count of characters
      const lo = at(forward ? ra : rf, forward ? A.n : F.n, true), hi = at(forward ? rf : ra, forward ? F.n : A.n, false);
      if (forward ? put(lo, hi) : put(hi, lo)) return;
    }
    const c = scope && scope.d && resolve(scope.d);   // the same words, if they stand once in the element that held them
    if (c && c.nodeType === ELEMENT && c.tagName === scope.tag && classOf(c) === scope.cls) {
      const text = textOf(c), i = text.indexOf(saved);
      if (i >= 0 && text.indexOf(saved, i + 1) < 0) {
        const lo = at(c, i, true), hi = at(c, i + saved.length, false);
        if (forward ? put(lo, hi) : put(hi, lo)) return;
      }
    }
    now.removeAllRanges();   // not the same words: no selection, rather than one on other words
  };
  const restore = (late) => { try { apply(late); } finally { watchers.delete(w); } };
  w.restore = restore;
  return Object.assign(restore, { again: () => null, drop: (token) => { if (w.owner === token) watchers.delete(w); },   // superseded, or left
    mark: (token) => { w.owner = token; note(w, ends(getSel())); watchers.add(w); } });
}

// Call before a draw, and what it returns after (restore(late) if it finished later; mark(token) once its synchronous part is
// done; drop(token) if it never finishes). mark() may return another draw's restore: a draw of the region that begins on a
// state in a waiting draw's chain takes over its held selection, as what it would hold is the damage that draw did (D22).
export function holdSelection(active, region) {
  const inner = holdField(active, region) || holdText(region || null) || nothing;
  if (!watchers.size) return inner;
  const begin = ends(getSel());
  // A waiting draw whose chain lacks this draw's start has seen the person act: it is let go for good (close1 #3: a later
  // draw moved the person's caret onto (#place, 0), a state in its chain, and the OLD words came back).
  for (const x of watchers) if (!known(x, begin)) { x.gone = true; watchers.delete(x); }
  if (!watchers.size) return inner; const flagged = [...watchers];   // the waiting draws this one begins on a state of theirs
  const out = Object.assign((late) => { inner(late); const e = ends(getSel()); for (const x of flagged) note(x, e); }, { again: inner.again, drop: inner.drop, acted: inner.acted });
  out.mark = (token) => {
    const old = !inner.field && region ? flagged.find((x) => x.region === region && watchers.has(x)) : null;
    if (!old) { inner.mark(token); return out; }
    old.owner = token;
    note(old, ends(getSel()));
    return old.restore;
  };
  return out;
}

// ---------------------------------------------------------------- a draw that changes nothing replaces nothing
// How a node reads, for comparing what is drawn with what a draw made: its tag, its attributes, the state a person
// changes (a field's value, an opened fold), and its children. Handlers are not part of it.
const STATE = ["hidden", "open", "disabled", "checked"];
const names = (el) => (typeof el.getAttributeNames === "function" ? el.getAttributeNames() : Object.keys(el.attributes || {}));
function shell(el) {
  let s = "<" + el.tagName;
  for (const k of names(el).sort()) { const v = String(el.getAttribute(k)); s += " " + k.length + ":" + k + "=" + v.length + ":" + v; }
  if (typeof el.className === "string") s += " c" + el.className.length + ":" + el.className;
  for (const p of STATE) if (el[p]) s += " +" + p;
  if (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT") s += " v" + String(el.value).length + ":" + el.value;
  return s + ">";
}
export function serial(n) {
  if (n.nodeType === TEXT) return "T" + n.data.length + ":" + n.data;
  if (n.nodeType !== ELEMENT) return "";   // a comment says nothing
  return shell(n) + kids(n).map(serial).join("") + "</>";
}
// True when `nodes`, put under `parent`, would read as what `parent` holds now.
export function same(parent, nodes) {
  const cur = kids(parent);
  return cur.length === nodes.length && cur.every((c, i) => serial(c) === serial(nodes[i]));
}

// What a region held before a draw: each element's children, and every node.
export function snapshot(region) {
  const children = new Map(), all = new Set();
  const walk = (n) => { all.add(n); if (n.nodeType === ELEMENT) { const k = kids(n); children.set(n, k); k.forEach(walk); } };
  walk(region);
  return { children, all };
}

// After a draw: wherever it put new nodes that read the same as the old ones it took out, the old ones go back, so a
// selection (or a focus, or a scroll) inside them was never disturbed. Only where the draw took nodes out and left them
// out of the page: a node that is in the page, or a new place for an old node, is not touched; and children are paired
// by position, so a part whose number of children changed is left as drawn.
export function settle(region, snap) {
  const { children, all } = snap;
  const twin = (o, n) => {
    if (o === n || document.contains(o)) return n;
    if (serial(o) === serial(n)) return o;
    if (o.nodeType === ELEMENT && n.nodeType === ELEMENT && shell(o) === shell(n) && o.childNodes.length === n.childNodes.length) {
      const a = kids(o), b = kids(n), mix = b.map((c, i) => twin(a[i], c));
      if (mix.some((c, i) => c !== b[i])) n.replaceChildren(...mix);
    }
    return n;
  };
  const walk = (el) => {
    const old = children.get(el);
    if (!old) return;   // made by this draw: nothing of it was there before
    const cur = kids(el);
    if (old.length === cur.length && old.every((n, i) => n === cur[i])) { cur.forEach((c) => { if (c.nodeType === ELEMENT) walk(c); }); return; }
    if (old.length !== cur.length) return;
    if (old.some((o) => !cur.includes(o) && document.contains(o))) return;   // an old node moved elsewhere in the page
    if (cur.some((n) => !old.includes(n) && all.has(n))) return;             // an old node moved in from elsewhere
    const mix = cur.map((n, i) => twin(old[i], n));
    if (mix.some((n, i) => n !== cur[i])) el.replaceChildren(...mix);
  };
  walk(region);
}
