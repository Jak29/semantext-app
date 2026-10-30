// Plug-ins: every plug-in, built in or installed, with where it came from, whether it is on, its health, what it
// declares it reads, and its settings (semantext/pluginpage.py). Installed is not on. The page turns a plug-in off,
// and proposes: a settings change, or a rollback of one, is kept as a proposal you apply at your own console, which
// shows its before and after. Turning a plug-in on is never done here either. Each is one POST the server guards and
// records; the page shows the one line you type at your console.
import { h } from "./dom.js";
import { plural, when } from "./words.js";
import { disclosure, header } from "./parts.js";
import { fill, load } from "./app.js";

// What you typed and have not sent (kept across the redrawing every refresh makes), and the answer to the last change.
export const PG = { drafts: {}, said: null, where: null, sending: false };
export const sender = {
  post: (act, body) => fetch("/api/v2/plugins/" + act, { method: "POST", cache: "no-store",
    headers: { "X-Semantext": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) }),
};

const WHAT = { on: "turned on", off: "turned off", settings: "settings changed", rollback: "rolled back",
  proposed: "proposed" };
const LABEL = { widens: "it widens what a plug-in reads", narrows: "no plug-in that declares these keys reads more",
  unknown: "no plug-in declares a type for a key it changes",
  "order changed": "the order of a list's entries changed, and what an order means is not known" };

// The answer to a change, in words; a refusal keeps the server's words and the line to type, when there is one.
export async function send(act, body) {
  if (PG.sending) return;
  PG.sending = true;
  PG.where = body.plugin || "changes";   // the answer is shown beside the control that sent it
  PG.said = { text: "Sending…" };
  fill();
  try {
    const r = await sender.post(act, body);
    let got = {};
    try { got = await r.json(); } catch (e) { /* the status says enough */ }
    if (r.status === 202 && got.proposed) {
      // a proposal was recorded: accepted, not made, and not refused; the line applies it at your console
      PG.said = { acts: true, text: got.said || "Proposed: proposal " + got.proposed + ".", command: got.line || null, note: got.note || null };
      if (act === "settings") delete PG.drafts[body.plugin];
    } else if (r.ok) {
      const c = got.change || {};
      PG.said = { text: "Done: change " + c.n + ", " + (WHAT[c.what] || c.what) + " (" + c.plugin + ")." };
      if (act === "settings") delete PG.drafts[body.plugin];
    } else {
      // a change that is yours to make at the console is where you act (gold); anything else did not work (red)
      PG.said = { bad: !got.command, acts: Boolean(got.command), text: got.error || "the server answered " + r.status,
        command: got.command || null, note: got.note || null };
    }
  } catch (e) {
    PG.said = { bad: true, text: "The change could not be sent: " + String((e && e.message) || e) };
  } finally {
    PG.sending = false;
  }
  fill();   // the answer is shown at once; the place is read again behind it
  try { if (!(await load("plugins"))) fill(); } catch (e) { /* the problems line says so at the next refresh */ }
}

// ---------------------------------------------------------------- one plug-in
const shownValue = (v) => (Array.isArray(v) ? v.join("\n") : v === null || v === undefined ? "" : String(v));
const draftOf = (p, s) => {
  const d = PG.drafts[p.key];
  return d && Object.prototype.hasOwnProperty.call(d, s.key) ? d[s.key] : shownValue(s.value);
};
const isList = (s) => s.type === "paths" || s.type === "list";

// What you typed, as the server is sent it: only what changed; an empty field takes the setting out (null).
export function changedSettings(p) {
  const out = {};
  for (const s of p.settings) {
    const typed = draftOf(p, s);
    if (typed === shownValue(s.value) && (s.set || typed === "")) continue;
    if (!typed.trim()) { if (s.set) out[s.key] = null; continue; }
    out[s.key] = isList(s) ? typed.split("\n").map((x) => x.trim()).filter(Boolean) : typed.trim();
  }
  return out;
}

function field(p, s, can) {
  const id = "pf-" + p.key + "-" + s.key;
  const keep = (ev) => { (PG.drafts[p.key] = PG.drafts[p.key] || {})[s.key] = ev.currentTarget.value; };
  const attrs = { id, "data-k": id, value: draftOf(p, s), disabled: !can, on: { input: keep } };
  const input = isList(s) ? h("textarea", Object.assign({ class: "input", rows: 3 }, attrs))
    : h("input", Object.assign({ class: "input", type: "text" }, attrs));
  const notes = [s.type ? s.type + (isList(s) ? ", one a line" : "") : null, s.required ? "needed" : null,
    s.widens ? "any change widens what it reads" : null, s.set ? null : "not set"].filter(Boolean);
  return h("div", { class: "pfield" }, h("label", { for: id }, s.title, " ", h("span", { class: "mono soft" }, s.key)),
    input, h("p", { class: "meta" }, notes.join(" · ")));
}

function command(line, intro) {
  return h("div", { class: "pcmd" }, h("p", { class: "meta" }, intro), h("code", { class: "mono" }, line));
}

// The answer to the last change, where it was made: in its plug-in's card, or under the change log.
export function saidBox(where) {
  if (!PG.said || PG.where !== where) return null;
  return h("div", { class: "psaid" + (PG.said.bad ? " bad" : PG.said.acts ? " acts" : ""), role: "status" },
    h("p", null, PG.said.text), PG.said.command ? command(PG.said.command, "Type at your own console:") : null,
    PG.said.note ? h("p", { class: "meta" }, PG.said.note) : null);
}

export function pluginCard(p) {
  const kids = [h("div", { class: "plugin-head" },
    h("h3", null, p.title !== p.name ? p.title + " " : "", h("span", { class: "mono" }, p.key)),
    h("span", { class: "trust" + (p.on ? " is-on" : "") }, p.trust)),
  h("p", { class: "meta" }, "From " + p.package + (p.version ? " " + p.version : "") + (p.builtin ? " (built in)" : " (an installed package, not part of Semantext)")),
  h("p", { class: "meta" }, "Health: " + p.health.words)];
  if (p.declaration_problem) kids.push(h("p", { class: "refused" }, "Its declaration cannot be used: " + p.declaration_problem));
  kids.push(h("p", { class: "label" }, "What it may read"), h("ul", { class: "preads" }, p.reads.map((r) => h("li", null, r))),
    h("p", { class: "meta" }, "Declared by its package, not enforced: a plug-in is code with your whole reach."));
  if (p.settings.length) {
    kids.push(h("p", { class: "label" }, "Settings"), ...p.settings.map((s) => field(p, s, p.can.change && !PG.sending)));
    if (p.shared && p.shared.length) kids.push(h("p", { class: "meta" }, "Read by another plug-in too, so a change is judged for each: " + p.shared.join(", ")));
    if (p.can.change) {
      kids.push(h("button", { type: "button", class: "toggle", "data-k": "pchange:" + p.key, disabled: PG.sending, on: { click: () => {
        const settings = changedSettings(p);
        if (!Object.keys(settings).length) { PG.where = p.key; PG.said = { text: "Nothing changed in " + p.key + "'s settings." }; fill(); return; }
        send("settings", { plugin: p.key, settings });
      } } }, "Propose this change"));
      kids.push(h("p", { class: "meta" }, "The page never writes these: it proposes, and you apply the change at your own console, which shows its before and after."));
    } else if (p.change_note) {
      kids.push(h("p", { class: "meta" }, p.change_note));
    }
  }
  if (p.undeclared && p.undeclared.length) {
    kids.push(h("p", { class: "label" }, "Keys it reads that it declares no type for"),
      h("ul", { class: "preads" }, p.undeclared.map((u) => h("li", null, h("span", { class: "mono" }, u.key), ": " + (u.set ? shownValue(u.value) : "not set")))),
      h("p", { class: "meta" }, "Changed in your sources file, not here."));
  }
  if (p.can.off) {
    kids.push(h("button", { type: "button", class: "toggle", "data-k": "poff:" + p.key, disabled: PG.sending,
      on: { click: () => send("off", { plugin: p.key }) } }, "Turn off"));
  }
  if (p.on_command) kids.push(command(p.on_command, "Turning it on is yours, at your own console. Type:"));
  if (p.off_command) kids.push(command(p.off_command, "The page cannot turn it off. At your own console, type:"));
  if (p.off_note) kids.push(h("p", { class: "meta" }, p.off_note));
  kids.push(saidBox(p.key));
  return h("article", { class: "plugin", "data-plugin": p.key }, kids);
}

function builtinRow(p) {
  const keys = p.settings.map((s) => s.key + (s.set ? " = " + shownValue(s.value).replace(/\n/g, ", ") : " (not set)"));
  return h("li", null, h("span", { class: "mono" }, p.key), " · " + p.title + " · " + p.reads.join("; "),
    keys.length ? h("span", { class: "meta" }, " · keys: " + keys.join("; ")) : null);
}

// ---------------------------------------------------------------- the change log
const PROPOSAL = { confirmed: "Confirmed at the terminal.", expired: "Not made, and expired: it was not confirmed in time.",
  superseded: "Not made: a later proposal for the same setting took its place." };
function stateWords(field, v) {
  if (field === "on") return v ? "on (" + v.origin + " " + (v.version || "") + ")" : "off";
  if (!v) return "(nothing)";
  const said = Object.entries(v.values || {}).map(([k, x]) => k + " = " + (Array.isArray(x) ? x.join(", ") : String(x)));
  return said.concat((v.absent || []).map((k) => k + " not set")).join("; ") || "(nothing)";
}

export function changeRow(c) {
  const kids = [h("p", null, h("span", { class: "mono" }, "#" + c.n), " " + (WHAT[c.what] || c.what) + " · ",
    h("span", { class: "mono" }, c.plugin), " · by " + (c.who === "page" ? "this page" : "the terminal") + " · " + when(c.at)),
  h("p", { class: "meta" }, "Before: " + stateWords(c.field, c.before)),
  h("p", { class: "meta" }, "After: " + stateWords(c.field, c.after))];
  if (c.rolls_back) kids.push(h("p", { class: "meta" }, "Rolls back change " + c.rolls_back + "."));
  if (c.confirms) kids.push(h("p", { class: "meta" }, "Confirms proposal " + c.confirms + "."));
  if (c.what === "proposed") {
    if (c.label) kids.push(h("p", { class: "meta" }, "Labelled when proposed: " + c.label + " (" + (LABEL[c.label] || c.label) + "). The label decides nothing; you do, at your console."));
    if (c.command) kids.push(command(c.command, "Not made. To apply it, type at your own console:"));
    else kids.push(h("p", { class: "meta" }, PROPOSAL[c.status] || (c.confirmed ? PROPOSAL.confirmed : "Not made.")));
  } else if (c.status === "not applied") {
    kids.push(h("p", { class: "refused" }, "Not applied: the file this record names does not now hold its \"after\", and no later record explains it (the change stopped before it was made, or the file was edited by hand since). It is not rolled back."));
  } else {
    kids.push(h("button", { type: "button", class: "toggle small", "data-k": "pback:" + c.n, disabled: PG.sending,
      on: { click: () => send("rollback", { change: c.n }) } }, "Roll back"));
  }
  return h("li", { class: "pchange" }, kids);
}

// What the person is told of their closed places while a plug-in cannot be turned on: the true state, its reason, and
// what fixes it (closed.closures_state), never "not named" when they are named.
export function closuresSaid(data) {
  const state = data.closures_state || "none named";
  if (state !== "incomplete" && state !== "unknown")
    return "Your closed places are not named, so every path is closed to a plug-in and none can be turned on. Name them under \"closed\" in your sources file.";
  const lead = state === "incomplete"
    ? "Your closed places are named, and the list of closed paths is incomplete, so every path is closed to a plug-in and none can be turned on."
    : "Your closed places are named and cannot be read, so every path is closed to a plug-in and none can be turned on.";
  const why = data.closures_why ? " Why: " + data.closures_why + "." : "";
  const fix = data.closures_fix ? " To fix it, " + data.closures_fix + "." : "";
  return lead + why + fix;
}

// ---------------------------------------------------------------- the place
export function render(data, el) {
  if (!data) { el.replaceChildren(header("Plug-ins", "Reading what is installed…")); return; }
  const outside = data.plugins.filter((p) => !p.builtin);
  const built = data.plugins.filter((p) => p.builtin);
  const out = [h("h1", { class: "sr-only" }, "Plug-ins"),
    header("Plug-ins", "Installed is not on: a plug-in reads nothing until you turn it on at your own console.",
      plural(outside.length, "installed plug-in") + " · " + outside.filter((p) => p.on).length + " on · " + plural(built.length, "built-in part"))];
  if (!data.closures_known) out.push(h("p", { class: "refused" }, closuresSaid(data)));
  if (data.command_note) out.push(h("p", { class: "meta" }, data.command_note));
  if (!data.sources_readable) out.push(h("p", { class: "refused" }, "Your sources file cannot be read, so no setting is shown or changed."));
  out.push(outside.length ? h("div", { class: "plugins" }, outside.map(pluginCard))
    : h("p", { class: "empty" }, "No installed package offers a plug-in. `" + data.list_command + "` lists them too."));
  const box = disclosure("plugins:builtin", plural(built.length, "built-in part") + ", always on");
  box.append(h("ul", { class: "preads" }, built.map(builtinRow)));
  out.push(box, h("h2", { class: "label" }, "Changes"), saidBox("changes"));
  out.push(data.changes.length ? h("ol", { class: "plog" }, data.changes.map(changeRow))
    : h("p", { class: "empty" }, "No change recorded yet. Every change made here or with `semantext plugins` is recorded, and can be rolled back."));
  if (data.problems.length) out.push(h("ul", { class: "preads" }, data.problems.map((p) => h("li", { class: "bad" }, p.text))));
  el.replaceChildren(...out.filter(Boolean));   // replaceChildren sets a null as the text "null"; h() skips one
}
