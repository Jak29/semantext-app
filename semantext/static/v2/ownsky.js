// Your rules as a constellation.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR } from "./ownbase.js";
import { SOURCE, ruleDetail } from "./ownrules.js";

// ---------------------------------------------------------------- the constellation: your rules, as structure
// Rings are where a rule applies: the centre, everywhere (the shared base); the next ring, the active environment; the
// outer ring, one agent's own, an arc of it per agent. Your own words are gold, joined in the order you added them, so
// the shape grows as you correct your AIs; everything Semantext wrote is grey. A rule switched off is a hollow star.
// Only the structure you have is drawn: a ring with no rules on it is not there. It is still until something real
// happens: a message lights the rules that went with it, for a moment.
const make = () => {
  const c = h("canvas", { role: "img", "aria-label": "Your rules as a constellation: the centre applies everywhere, and each ring out applies more narrowly. Gold stars are rules in your own words. The list below says the same in words." });
  const x = c.getContext("2d");
  const api = {};
  let W = 0, H = 0, dpr = 1, host = null, raf = 0, font = "system-ui", hover = null;
  let stars = [], rings = [], arcs = [], mid = null, lit = new Map();
  const ro = "ResizeObserver" in window ? new ResizeObserver(() => { size(); api.layout(); }) : null;
  const originOf = (e) => { const t = (e.provenance || {}).type; return t === "LEARNED" ? "you" : t === "PROPOSED" ? "agent" : "app"; };
  const addedAt = (e) => { const p = e.provenance || {}; return String(p.when || p.added || p.proposed || ""); };
  const ORDER = { app: 0, agent: 1, you: 2 };
  const kept = (es) => (es || []).filter(e => e && !e.archived);
  const testedIds = () => new Set(((S.profile && S.profile.tests) || []).flatMap(t => t.rules || []));

  function size() {
    if (!host || !host.isConnected) return;
    const r = host.getBoundingClientRect();
    if (!r.width || !r.height) return;
    dpr = devicePixelRatio || 1; W = r.width; H = r.height;
    c.width = Math.round(W * dpr); c.height = Math.round(H * dpr);
  }
  function star(e, layer, sx, sy, agent, tested) {
    const o = originOf(e);
    return { e, id: e.id, layer, origin: o, x: sx, y: sy, agent, off: e.enabled === false, tested: tested.has(e.id),
      r: o === "you" ? 4.4 : o === "agent" ? 3.8 : 3.1 };
  }
  // Stars evenly round a ring, from the top; a crowded ring alternates between two radii so none overlap.
  function round(list, r, a0, step, layer, agent, tested) {
    const crowded = 2 * Math.PI * r / Math.max(1, list.length) < 11;
    list.forEach((e, i) => { const a = a0 + i * step, rr = crowded && i % 2 ? r * .9 : r; stars.push(star(e, layer, mid.x + Math.cos(a) * rr, mid.y + Math.sin(a) * rr, agent, tested)); });
  }
  api.layout = () => {
    if (!W || !S.base || !S.profile) return;
    font = getComputedStyle(document.body).fontFamily;
    const R = Math.min(W * .44, H * .42);
    mid = { x: W / 2, y: H / 2 + 6, R };
    const tested = testedIds();
    const base = kept(S.base.entries), env = kept(S.profile.entries);
    const agents = S.agents.map(a => ({ name: a.name, rules: kept([...(a.rules || []), ...(a.carried || []).flatMap(k => k.rules)]) })).filter(a => a.rules.length);
    stars = []; rings = []; arcs = [];
    const rb = R * (env.length || agents.length ? .24 : .5);
    rings.push({ key: "base", r: rb, n: base.length });
    round(base, rb, -Math.PI / 2, 2 * Math.PI / Math.max(1, base.length), "base", null, tested);
    if (env.length) {
      // this environment's rules, grouped by who wrote them, each group in the order its rules were added
      const re = R * (agents.length ? .6 : .86);
      rings.push({ key: "environment", r: re, n: env.length });
      const sorted = env.slice().sort((p, q) => ORDER[originOf(p)] - ORDER[originOf(q)] || addedAt(p).localeCompare(addedAt(q)));
      const groups = new Set(sorted.map(originOf)).size, step = 2 * Math.PI / (sorted.length + (groups > 1 ? groups : 0));
      let a = -Math.PI / 2, prev = null;
      for (const e of sorted) {
        if (prev !== null && originOf(e) !== prev) a += step;
        round([e], re, a, 0, "environment", null, tested); prev = originOf(e); a += step;
      }
    }
    if (agents.length) {
      const ra = R * .93, total = agents.reduce((n, g) => n + g.rules.length, 0) + agents.length, step = 2 * Math.PI / total;
      rings.push({ key: "agent", r: ra, n: total - agents.length });
      let a = -Math.PI / 2 + step / 2;
      for (const g of agents) {
        const a0 = a, list = g.rules.slice().sort((p, q) => addedAt(p).localeCompare(addedAt(q)));
        round(list, ra, a, step, "agent", g.name, tested);
        a += step * list.length;
        arcs.push({ name: g.name, a0: a0 - step * .35, a1: a - step * .65, r: ra });
        a += step;
      }
    }
    api.kick();
  };

  function frame(now) { raf = 0; draw(now); if (!still && host && busy(now)) raf = requestAnimationFrame(frame); }
  const busy = (now) => [...lit.values()].some(t => t > now);
  api.kick = () => { if (!raf && host) raf = requestAnimationFrame(frame); };
  function text(s, px, py, sz, col, weight, align) {
    x.font = `${weight || 400} ${sz}px ${font}`; x.fillStyle = col; x.textAlign = align || "center"; x.textBaseline = "middle"; x.fillText(s, px, py);
  }
  function caps(s, px, py, col, align) {
    try { x.letterSpacing = "1.5px"; } catch (e) { /* older canvases draw it without the spacing */ }
    text(s.toUpperCase(), px, py, 11, col, 600, align);
    try { x.letterSpacing = "0px"; } catch (e) { /* as above */ }
  }
  const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
  // How bright a star is now: lit by the last message (fading over 1.4 s; with reduced motion, until the next one).
  const glowOf = (s, now) => { const t = lit.get(s.id); return t === undefined ? 0 : still ? .8 : t > now ? Math.min(1, (t - now) / 1400) : 0; };

  function draw(now) {
    if (!W || !mid) return;
    const P = palette();
    x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, W, H);
    const { x: cx, y: cy } = mid;
    // the rings: where a rule applies, each named
    for (const g of rings) {
      x.save(); x.setLineDash([2, 5]); x.strokeStyle = rgba(P.line, 1); x.lineWidth = 1;
      x.beginPath(); x.arc(cx, cy, g.r, 0, 6.283); x.stroke(); x.restore();
    }
    const top = (g) => cy - g.r - 14;
    for (const g of rings) {
      if (g.key === "base") caps(rings.length > 1 ? `Everywhere · ${g.n}` : `Everywhere · ${plural(g.n, "rule")}`, cx, rings.length > 1 ? cy + g.r + 17 : top(g), rgba(P.t3, 1));
      if (g.key === "environment") caps(`In ${S.profile.environment.title} · ${g.n}`, cx, top(g), rgba(P.t3, 1));
    }
    for (const a of arcs) {
      const am = (a.a0 + a.a1) / 2, lx = cx + Math.cos(am) * (a.r + 18), ly = cy + Math.sin(am) * (a.r + 18);
      x.save(); x.strokeStyle = rgba(P.t3, .7); x.lineWidth = 1.5; x.beginPath(); x.arc(cx, cy, a.r + 8, a.a0, a.a1); x.stroke(); x.restore();
      text(short(label(a.name), 20) + " only", lx, ly, 12, rgba(P.t2, 1), 400, Math.cos(am) > .25 ? "left" : Math.cos(am) < -.25 ? "right" : "center");
    }
    // the shared rules, joined in a closed ring: every full card carries all of them together
    const shared = stars.filter(s => s.layer === "base" && !s.off);
    if (shared.length > 2) {
      x.strokeStyle = rgba(P.t3, .3); x.lineWidth = 1; x.beginPath();
      shared.forEach((s, i) => (i ? x.lineTo(s.x, s.y) : x.moveTo(s.x, s.y))); x.closePath(); x.stroke();
    }
    // your own rules, joined in the order you added them
    const yours = new Map();
    for (const s of stars) if (s.origin === "you" && s.layer !== "base") { const k = s.layer + ":" + (s.agent || ""); if (!yours.has(k)) yours.set(k, []); yours.get(k).push(s); }
    for (const g of yours.values()) {
      if (g.length < 2) continue;
      x.strokeStyle = rgba(P.accent, .55); x.lineWidth = 1.2; x.beginPath();
      g.forEach((s, i) => (i ? x.lineTo(s.x, s.y) : x.moveTo(s.x, s.y))); x.stroke();
    }
    // the stars
    for (const s of stars) {
      const k = s.origin === "you" ? P.accent : s.origin === "agent" ? P.t2 : P.t3, g = glowOf(s, now), hov = hover === s;
      if (g || hov) {
        const rad = s.r * (3.5 + 3 * g) + (hov ? 4 : 0), gr = x.createRadialGradient(s.x, s.y, 0, s.x, s.y, rad);
        gr.addColorStop(0, rgba(g ? P.text : k, .22 + .4 * g)); gr.addColorStop(1, rgba(g ? P.text : k, 0));
        x.fillStyle = gr; x.beginPath(); x.arc(s.x, s.y, rad, 0, 6.283); x.fill();
      }
      if (s.off) { x.strokeStyle = rgba(k, .9); x.lineWidth = 1.3; x.beginPath(); x.arc(s.x, s.y, s.r, 0, 6.283); x.stroke(); }
      else { x.fillStyle = rgba(g ? P.text : k, 1); x.beginPath(); x.arc(s.x, s.y, s.r + 1.2 * g, 0, 6.283); x.fill(); }
      if (s.tested) { x.strokeStyle = rgba(k, .9); x.lineWidth = 1; x.beginPath(); x.arc(s.x, s.y, s.r + 3.4, 0, 6.283); x.stroke(); }
    }
  }

  // A delivery: the rules that went with it light up for a moment. Which rules light is read from the feed line alone:
  // the ones sent, and for your own words, the shared rules that speak to what the quick reading noticed.
  api.pulse = (r) => {
    if (!host || !r) return;
    api.layout();
    const now = performance.now(), sent = new Set(r.layers.flatMap(L => L.ids)), on = new Set();
    if (r.words === "own") {
      for (const k of r.noticed || []) if (RULE_FOR[k] && sent.has(RULE_FOR[k])) on.add(RULE_FOR[k]);
      for (const s of stars) if (s.layer !== "base" && sent.has(s.id)) on.add(s.id);
    } else for (const s of stars) if (sent.has(s.id)) on.add(s.id);   // the short card: the safety rules alone
    lit = new Map([...on].map(id => [id, now + 1400]));
    api.kick();
  };
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
    let best = null, bd = 13;
    for (const s of stars) { const d = Math.hypot(s.x - mx, s.y - my); if (d < bd) { bd = d; best = s; } }
    return best;
  }
  const where = (s) => s.layer === "base" ? "Everywhere" : s.layer === "environment" ? `In ${S.profile.environment.title}` : `${label(s.agent)} only`;
  function tipOn(s, ev) {
    const t = $("skytip");
    fill(t, [h("b", {}, short(String(s.e.statement || ""), 140)), h("span", { class: "meta" }, `${where(s)} · ${SOURCE(s.e)}${s.off ? " · off" : ""}`)]);
    t.style.left = Math.min(ev.clientX + 16, innerWidth - 336) + "px"; t.style.top = (ev.clientY + 14) + "px"; t.classList.add("on");
  }
  function tipOff() { const t = $("skytip"); if (t) t.classList.remove("on"); }
  c.addEventListener("mousemove", (ev) => {
    const r = c.getBoundingClientRect(), s = hit(ev.clientX - r.left, ev.clientY - r.top);
    if (hover !== s) { hover = s; api.kick(); }
    c.style.cursor = s ? "pointer" : "default";
    if (s) tipOn(s, ev); else tipOff();
  });
  c.addEventListener("mouseleave", () => { hover = null; tipOff(); api.kick(); });
  c.addEventListener("click", (ev) => {
    const r = c.getBoundingClientRect(), s = hit(ev.clientX - r.left, ev.clientY - r.top);
    tipOff();
    if (!s) return closePop();
    rulePop(s, ev.clientX, ev.clientY, where(s));
  });
  return api;
};
let one = null;
const sky = () => one || (one = make());
export const Sky = { mount: (el) => sky().mount(el), unmount: () => { if (one) one.unmount(); }, pulse: (r) => { if (one) one.pulse(r); }, kick: () => { if (one) one.kick(); }, layout: () => { if (one) one.layout(); } };
// Only what the picture holds goes in its legend.
export function skyLegend() {
  const all = [...live(S.base.entries), ...live(S.profile.entries), ...S.agents.flatMap(a => [...(a.rules || []), ...(a.carried || []).flatMap(k => k.rules)])];
  const has = (t) => all.some(e => ((e.provenance || {}).type) === t);
  const tested = ((S.profile && S.profile.tests) || []).length > 0;
  return h("div", { class: "legend meta" },
    has("LEARNED") ? h("span", {}, h("i", { class: "you" }), "Your own words, joined in the order you added them") : null,
    h("span", {}, h("i", { class: "app" }), "Came with Semantext"),
    has("PROPOSED") ? h("span", {}, h("i", { class: "agent" }), "An agent's proposal you added") : null,
    all.some(e => e.enabled === false) ? h("span", {}, h("i", { class: "off" }), "Switched off") : null,
    tested ? h("span", {}, h("i", { class: "tested" }), "Kept with the message it was taught from") : null);
}
// One rule, from the constellation: what it says, when, where it applies, who wrote it, and its switch.
function rulePop(s, px, py, whereText) {
  const e = s.e, prof = s.layer === "base" ? "base" : S.state.active;
  fill("rulecard", [
    h("div", { class: "row" }, h("span", { class: "label grow" }, whereText),
      h("button", { class: "link meta", type: "button", "data-do": "close-pop", "aria-label": "Close" }, "Close")),
    h("p", { class: "st" }, e.statement),
    ruleDetail(e, prof, true)]);
  place(px, py);
}
function place(px, py) {
  const el = $("rulecard");
  el.hidden = false;
  el.style.left = Math.max(16, Math.min(px + 16, innerWidth - 376)) + "px";
  el.style.top = Math.max(16, Math.min(py - 20, innerHeight - el.offsetHeight - 16)) + "px";
}
export function closePop() { const el = $("rulecard"); if (el) el.hidden = true; }
