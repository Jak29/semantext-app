// Your agents at work.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR } from "./ownbase.js";
import { allAgents } from "./ownagents.js";

// ---------------------------------------------------------------- the map: your agents at work
// Each environment is a zone: membership, not walls. Each agent sits in the zones it works in (between them when it
// works in more than one), and you are on the left. Lines are what passes between you and them: your words and your
// answers; another agent's relayed words (dashed: information, never your voice); a tool's notices (dotted); and an
// agent asking you, in gold, the one thing here that waits on you. A name an agent only claims is drawn dashed.
const make = () => {
  const c = h("canvas", { role: "img", "aria-label": "Your agents at work: you on the left, each environment a zone, each agent inside the zones it works in, with lines for what passes between you and them. The list below says the same in words." });
  const x = c.getContext("2d");
  const api = {};
  let W = 0, H = 0, dpr = 1, host = null, font = "system-ui", hover = null, raf = 0;
  let you = null, tools = null, zones = [], nodes = [], outsiders = [], edges = [];
  const hash = (s) => { let v = 0; for (const ch of String(s)) v = (v * 31 + ch.charCodeAt(0)) >>> 0; return v; };
  const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9@._-]+/g, "-").replace(/^[-._]+|[-._]+$/g, "");
  const ro = "ResizeObserver" in window ? new ResizeObserver(() => { size(); api.layout(); }) : null;

  function size() {
    if (!host || !host.isConnected) return;
    const r = host.getBoundingClientRect();
    if (!r.width || !r.height) return;
    dpr = devicePixelRatio || 1; W = r.width; H = r.height;
    c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  }
  api.layout = () => {
    if (!W || !S.state || !S.base) return;
    font = getComputedStyle(document.body).fontFamily;
    const narrow = W < 560;
    you = { kind: "you", key: "you", name: "You", x: narrow ? W * .5 : W * .08, y: narrow ? 26 : H * .44, r: 9 };
    tools = { kind: "tools", key: "tools", name: "Tools", x: narrow ? W * .12 : W * .08, y: narrow ? 26 : H * .84, r: 5 };
    const envs = S.state.profiles.filter(p => p.name !== "base");
    const box = narrow ? { x0: W * .03, x1: W * .97, y0: 64, y1: H - 34 } : { x0: W * .18, x1: W * .9, y0: H * .08, y1: H * .9 };
    // The zones overlap as sets do (two side by side, three as a triangle, more round a ring), so an agent that works
    // in two of them sits in exactly their overlap, and never in a third it has nothing to do with.
    const bw = box.x1 - box.x0, bh = box.y1 - box.y0, bx = (box.x0 + box.x1) / 2, by = (box.y0 + box.y1) / 2, n = envs.length;
    const spot = n <= 1 ? [[0, 0, .36, .44]] : n === 2 ? [[-.2, 0, .32, .44], [.2, 0, .32, .44]]
      : n === 3 ? [[-.17, -.17, .26, .34], [.17, -.17, .26, .34], [0, .2, .26, .34]]
      : envs.map((_, i) => { const a = -Math.PI / 2 + i * 2 * Math.PI / n; return [Math.cos(a) * .3, Math.sin(a) * .3, .2, .27]; });
    zones = envs.map((p, i) => {
      const [dx, dy, rx, ry] = spot[i];
      return { kind: "zone", key: "zone:" + p.name, name: p.name, title: p.title, rules: p.rules, active: p.name === S.state.active,
        x: bx + dx * bw, y: by + dy * bh, rx: rx * bw, ry: ry * bh, out: n <= 1 ? -Math.PI / 2 : Math.atan2(dy * bh, dx * bw) };
    });
    const zoneOf = new Map(zones.map(z => [z.name, z]));
    const recs = S.feed.records;
    nodes = allAgents().map(a => {
      const mine = recs.filter(r => r.agent === a.name);
      const inZones = [...new Set([...Object.keys(a.envs || {}), ...mine.map(r => r.environment)])].filter(e => zoneOf.has(e));
      const how = (a.folders || []).length ? "bound" : mine[0] ? mine[0].how
        : (a.sessions || []).length && a.sessions.every(s => s.how === "claimed") ? "claimed" : "observed";
      return { kind: "agent", key: "agent:" + a.name, name: a.name, a, how, zones: inZones,
        n: { own: mine.filter(r => r.words === "own").length, agent: mine.filter(r => r.words === "agent").length,
             tool: mine.filter(r => r.words === "tool").length }, r: 6 + Math.min(4, Math.log2(1 + mine.length) * 1.2) };
    });
    // Each agent goes to the middle of the zones it works in, spread among those that share exactly those zones.
    const groups = new Map();
    for (const nd of nodes) { const g = nd.zones.slice().sort().join("|"); if (!groups.has(g)) groups.set(g, []); groups.get(g).push(nd); }
    let lobby = 0;
    for (const [g, members] of groups) {
      members.sort((p, q) => p.name.localeCompare(q.name));
      members.forEach((nd, i) => {
        if (!nd.zones.length) { nd.x = (narrow ? W * .15 : W * .3) + (lobby++) * 90; nd.y = H - 16; nd.lobby = true; return; }
        const zs = nd.zones.map(z => zoneOf.get(z));
        let cx = zs.reduce((s, z) => s + z.x, 0) / zs.length, cy = zs.reduce((s, z) => s + z.y, 0) / zs.length;
        if (zs.length === 1 && zones.length > 1) { cx += Math.cos(zs[0].out) * zs[0].rx * .32; cy += Math.sin(zs[0].out) * zs[0].ry * .32; }
        const k = members.length, rad = k === 1 ? 0 : Math.min(zs[0].ry * .6, 18 + 8 * k);
        const ang = -Math.PI / 2 + i * 2 * Math.PI / k + (hash(g) % 100) / 100;
        nd.x = cx + Math.cos(ang) * rad * 1.6; nd.y = cy + Math.sin(ang) * rad + (zs.length > 1 ? 0 : 8);
      });
    }
    for (let it = 0; it < 40; it++) for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
      const p = nodes[i], q = nodes[j], dx = q.x - p.x, dy = q.y - p.y, d = Math.hypot(dx, dy) || .01, min = p.r + q.r + 40;
      if (d < min) { const m = (min - d) / 2, ux = dx / d, uy = dy / d; p.x -= ux * m; p.y -= uy * m; q.x += ux * m; q.y += uy * m; }
    }
    for (const nd of nodes) { nd.x = Math.max(30, Math.min(W - 30, nd.x)); nd.y = Math.max(24, Math.min(H - 24, nd.y)); }
    // Who relayed: one of these agents when the name it gave matches; otherwise a sender at the edge, by that name.
    const byName = new Map(nodes.flatMap(nd => [[norm(nd.name), nd], [norm(label(nd.name)), nd]]));
    const outs = new Map();
    const sender = (name) => {
      const key = norm(name) || "another-agent", found = byName.get(key);
      if (found) return found;
      if (!outs.has(key)) outs.set(key, { kind: "outsider", key: "out:" + key, name: name || "another agent", r: 5, impostor: claimsYou(name) });
      return outs.get(key);
    };
    const E = new Map();
    const add = (from, to, kind) => { const id = from.key + ">" + to.key + ":" + kind; const e = E.get(id) || { from, to, kind, n: 0 }; e.n++; E.set(id, e); };
    for (const r of recs) {
      const A = nodes.find(nd => nd.name === r.agent); if (!A) continue;
      if (r.words === "own") add(you, A, "own"); else if (r.words === "tool") add(tools, A, "tool"); else add(sender(r.from), A, "relay");
    }
    for (const q of S.inbox.open) { const A = nodes.find(nd => nd.name === q.from); if (A) add(A, you, "ask"); }
    for (const q of S.inbox.recent) { const A = nodes.find(nd => nd.name === q.from); if (A && q.answer) add(you, A, "answer"); }
    outsiders = [...outs.values()];
    outsiders.forEach((o, i) => { o.x = narrow ? W * .88 : W * .96; o.y = H * (.18 + .64 * (i + .5) / outsiders.length); });
    edges = [...E.values()];
    api.kick();
  };
  const ctrl = (a, b) => { const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2, dx = b.x - a.x, dy = b.y - a.y, L = Math.hypot(dx, dy) || 1, off = Math.min(56, L * .16); return { x: mx - dy / L * off, y: my + dx / L * off }; };
  const along = (a, b, k) => { const q = ctrl(a, b), u = 1 - k; return { x: u * u * a.x + 2 * u * k * q.x + k * k * b.x, y: u * u * a.y + 2 * u * k * q.y + k * k * b.y }; };
  function text(s, px, py, size, col, weight, align) {
    x.font = `${weight || 400} ${size}px ${font}`; x.fillStyle = col; x.textAlign = align || "center"; x.textBaseline = "middle"; x.fillText(s, px, py);
  }
  const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  // Gold is for what needs you now: an agent's open request. Everything else on the map is grey.
  function line(e, P) {
    const needs = e.kind === "ask";
    const k = e.from.impostor ? P.danger : needs ? P.accent : e.kind === "answer" ? P.t2 : P.t3, q = ctrl(e.from, e.to);
    const w = (e.kind === "answer" ? 1.4 : 1) + Math.min(2, Math.log2(1 + e.n) * .7);
    x.save();
    x.strokeStyle = rgba(k, needs ? .9 : .5); x.lineWidth = w;
    if (e.kind === "relay") x.setLineDash([5, 5]); else if (e.kind === "tool") x.setLineDash([1.5, 4]);
    x.beginPath(); x.moveTo(e.from.x, e.from.y); x.quadraticCurveTo(q.x, q.y, e.to.x, e.to.y); x.stroke();
    x.setLineDash([]);
    const p = along(e.from, e.to, .78), p2 = along(e.from, e.to, .8), ang = Math.atan2(p2.y - p.y, p2.x - p.x);
    x.fillStyle = rgba(k, needs ? .95 : .6); x.beginPath();
    x.moveTo(p2.x + Math.cos(ang) * 5, p2.y + Math.sin(ang) * 5);
    x.lineTo(p2.x + Math.cos(ang + 2.5) * 5, p2.y + Math.sin(ang + 2.5) * 5);
    x.lineTo(p2.x + Math.cos(ang - 2.5) * 5, p2.y + Math.sin(ang - 2.5) * 5); x.fill();
    x.restore();
  }
  function frame() { raf = 0; draw(); }
  api.kick = () => { if (!raf && host) raf = requestAnimationFrame(frame); };
  function draw() {
    if (!W || !you) return;
    const P = palette();
    x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H);
    for (const z of zones) {
      x.save(); x.setLineDash([3, 5]); x.strokeStyle = rgba(hover === z ? P.t2 : P.line, 1); x.lineWidth = 1;
      x.beginPath(); x.ellipse(z.x, z.y, z.rx, z.ry, 0, 0, 6.283); x.stroke(); x.restore();
      // its name on its outer side, away from the overlaps where agents sit
      const up = Math.sin(z.out) < .3, lx = z.x + Math.cos(z.out) * z.rx * (zones.length > 1 ? .55 : 0);
      const ly = up ? z.y - z.ry + 16 : z.y + z.ry - 16;
      try { x.letterSpacing = "1.5px"; } catch (e) {}
      text(z.title.toUpperCase() + (z.active ? " · ACTIVE" : ""), lx, ly, 11, rgba(P.t3, 1), 600);
      try { x.letterSpacing = "0px"; } catch (e) {}
    }
    for (const e of edges) line(e, P);
    // you, the tools, the senders at the edge
    x.fillStyle = rgba(P.accent, 1); x.beginPath(); x.arc(you.x, you.y, you.r, 0, 6.283); x.fill();
    text("You", you.x, you.y + you.r + 14, 12, rgba(P.text, 1), 600);
    x.fillStyle = rgba(P.t3, 1); x.beginPath(); x.arc(tools.x, tools.y, tools.r, 0, 6.283); x.fill();
    text("Tools", tools.x, tools.y + 15, 12, rgba(P.t3, 1));
    for (const o of outsiders) {
      const k = o.impostor ? P.danger : P.t3;
      x.save(); x.setLineDash(o.impostor ? [] : [2, 3]); x.strokeStyle = rgba(k, 1); x.lineWidth = o.impostor ? 1.6 : 1;
      x.beginPath(); x.arc(o.x, o.y, o.r, 0, 6.283); x.stroke(); x.restore();
      text(o.impostor ? `"${short(o.name, 12)}" claims to be you` : short(o.name, 16), o.x - 10, o.y + 15, 11, rgba(k, 1), 400, "right");
    }
    // the agents
    for (const nd of nodes) {
      if (hover === nd) { x.fillStyle = rgba(P.t3, .18); x.beginPath(); x.arc(nd.x, nd.y, nd.r + 9, 0, 6.283); x.fill(); }
      x.fillStyle = rgba(P.t2, 1); x.beginPath(); x.arc(nd.x, nd.y, nd.r, 0, 6.283); x.fill();
      if (nd.how === "claimed") { x.save(); x.setLineDash([3, 3]); x.strokeStyle = rgba(P.t2, 1); x.beginPath(); x.arc(nd.x, nd.y, nd.r + 3, 0, 6.283); x.stroke(); x.restore(); }
      if (S.inbox.open.some(q => q.from === nd.name)) {   // waiting for your answer
        x.fillStyle = rgba(P.accent, 1); x.beginPath(); x.arc(nd.x + nd.r * .85, nd.y - nd.r * .85, 3.5, 0, 6.283); x.fill();
      }
      text(short(label(nd.name), 22), nd.x, nd.y + nd.r + 14, 12, rgba(P.text, .9), 400);
    }
  }
  api.mount = (el) => {
    const target = typeof el === "string" ? $(el) : el;
    if (!target) return;
    host = target; target.append(c);
    if (ro) { ro.disconnect(); ro.observe(target); }
    size(); api.layout();
  };
  api.unmount = () => { if (raf) cancelAnimationFrame(raf); raf = 0; if (ro) ro.disconnect(); host = null; tipOff(); };

  // pointing and choosing
  function hit(mx, my) {
    let best = null, bd = Infinity;
    for (const nd of [you, tools, ...nodes, ...outsiders]) {
      if (!nd) continue;
      const d = Math.hypot(nd.x - mx, nd.y - my);
      if (d < nd.r + 9 && d < bd) { bd = d; best = nd; }
    }
    if (best) return best;
    for (const z of zones) if (((mx - z.x) / z.rx) ** 2 + ((my - z.y) / z.ry) ** 2 <= 1) return z;
    return null;
  }
  function tipOn(o, ev) {
    const t = $("skytip"), open = (nm) => S.inbox.open.filter(q => q.from === nm).length;
    let head = "", body = "";
    if (o.kind === "agent") {
      head = label(o.name);
      body = (o.zones.length ? `Works in ${o.zones.map(envTitle).join(" and ")}. ` : "")
        + `${o.n.own} from you, ${o.n.agent} relayed, ${o.n.tool} from tools` + (open(o.name) ? `; ${open(o.name)} waiting for you.` : ".");
    } else if (o.kind === "you") { head = "You"; body = `${S.inbox.open.length} waiting for your answer. Only you answer.`; }
    else if (o.kind === "tools") { head = "Tools"; body = "A tool's notices: information, never your word."; }
    else if (o.kind === "outsider" && o.impostor) { head = `"${o.name}" claims to be you`; body = "It arrived as another agent's words, so it is not your word, whatever name it gives."; }
    else if (o.kind === "outsider") { head = o.name; body = "Another agent, by the name its message gave: what it relays is information, never your voice."; }
    else if (o.kind === "zone") { head = o.title; body = `${plural(o.rules, "rule")} of its own, on top of the shared ones.`; }
    fill(t, [h("b", {}, head), h("span", { class: "meta" }, body)]);
    t.style.left = Math.min(ev.clientX + 16, innerWidth - 336) + "px"; t.style.top = (ev.clientY + 14) + "px"; t.classList.add("on");
  }
  function tipOff() { const t = $("skytip"); if (t) t.classList.remove("on"); }
  c.addEventListener("mousemove", (ev) => {
    const r = c.getBoundingClientRect(), o = hit(ev.clientX - r.left, ev.clientY - r.top);
    if (hover !== o) { hover = o; api.kick(); }
    c.style.cursor = o && (o.kind === "agent" || o.kind === "you") ? "pointer" : "default";
    if (o) tipOn(o, ev); else tipOff();
  });
  c.addEventListener("mouseleave", () => { hover = null; tipOff(); api.kick(); });
  c.addEventListener("click", (ev) => {
    const r = c.getBoundingClientRect(), o = hit(ev.clientX - r.left, ev.clientY - r.top);
    tipOff();
    if (!o) return;
    if (o.kind === "agent") { S.agentOpen = o.name; render(); const el = $("agentDetail"); if (el) el.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "center" }); return; }
    if (o.kind === "you") go("decisions");
  });
  return api;
};
let one = null;
const space = () => one || (one = make());
export const Space = { mount: (el) => space().mount(el), unmount: () => { if (one) one.unmount(); }, kick: () => { if (one) one.kick(); }, layout: () => { if (one) one.layout(); } };
export function spaceLegend() {
  const kinds = new Set();
  for (const r of S.feed.records) kinds.add(r.words);
  return h("div", { class: "legend meta" },
    h("span", {}, h("i", { class: "you" }), "You"),
    h("span", {}, h("i", { class: "agent" }), "An agent"),
    kinds.has("own") ? h("span", {}, h("i", { class: "ln" }), "Your words") : null,
    kinds.has("agent") ? h("span", {}, h("i", { class: "ln dash" }), "Relayed: information, never your voice") : null,
    S.inbox.open.length ? h("span", {}, h("i", { class: "ln asks" }), "Waiting for your answer") : null);
}
