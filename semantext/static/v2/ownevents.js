// What the page's Today, Rules, Agents and Settings do when you press something. Only inside their own parts: every other
// place keeps its own handlers.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR, load, loadInbox, pollFeed } from "./ownbase.js";
import { Sky, closePop } from "./ownsky.js";
import { Space } from "./ownspace.js";
import { historyRows, recentRows } from "./owntoday.js";
import { loadIdeas, ruleLists, testFlow } from "./ownrules.js";
import { refreshLayers } from "./ownagents.js";
import { closeMenu, openEditor, openMenu, openNew, suggest } from "./ownsettings.js";

const inOwn = (el) => !!(el && el.closest && el.closest(".own"));
let suggestTimer = null;
$("newName").addEventListener("input", () => { clearTimeout(suggestTimer); suggestTimer = setTimeout(suggest, 220); });
$("newCancel").addEventListener("click", () => { $("newEnv").hidden = true; });
$("newCreate").addEventListener("click", async () => {
  const picks = [...document.querySelectorAll("#picks input:checked")].map(i => ({ pack: i.dataset.pack, id: i.dataset.id }));
  const r = await act("/api/create", { title: $("newName").value.trim(), picks }, picks.length ? "Made, and active" : "Made, and empty: add rules under Rules");
  if (r) $("newEnv").hidden = true;
});
document.addEventListener("click", async (ev) => {
  if (!inOwn(ev.target)) { closeMenu(); return; }
  const row = ev.target.closest("tr[data-at]");
  if (row) { S.expanded = S.expanded === row.dataset.at ? null : row.dataset.at; fill("historyRows", historyRows()); return; }
  const t = ev.target.closest("button");
  if (!t) {
    if (!ev.target.closest("#envMenu")) closeMenu();
    if (!ev.target.closest("#rulecard") && ev.target.tagName !== "CANVAS") closePop();
    if (ev.target.id === "newEnv") $("newEnv").hidden = true;
    return;
  }
  if (!t.closest("#envMenu") && t.id !== "envPill" && t.dataset.do !== "env-menu") closeMenu();
  const name = S.state && S.state.active;
  if (t.id === "envPill") return $("envMenu").hidden ? openMenu(t) : closeMenu();
  if (t.dataset.view) return go(t.dataset.view);
  if (t.dataset.env) { closeMenu(); S.layers.card = null; return act("/api/active", { name: t.dataset.env }, "Switched: every agent now reads " + envTitle(t.dataset.env)); }
  if (t.dataset.explain) { S.expanded = S.expanded === t.dataset.explain ? null : t.dataset.explain; fill("recent", recentRows()); return; }
  if (t.dataset.rule) {
    S.ruleOpen = S.ruleOpen === t.dataset.rule ? null : t.dataset.rule;
    if (S.view === "rules") fill("ruleLists", ruleLists(live(S.profile.entries)));
    else render();
    return;
  }
  if (t.dataset.agent) { S.agentOpen = S.agentOpen === t.dataset.agent ? null : t.dataset.agent; return render(); }
  if (t.dataset.copy !== undefined) { try { await navigator.clipboard.writeText(t.dataset.copy); toast("Copied: " + t.dataset.copy); } catch (e) { toast(t.dataset.copy); } return; }
  if (t.dataset.form) { S.layers.form = t.dataset.form; document.querySelectorAll("[data-form]").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.form === S.layers.form))); return refreshLayers(); }
  if (t.dataset.toggle || t.dataset.remove) {
    const r = t.dataset.toggle ? await act("/api/toggle", { name: t.dataset.prof, id: t.dataset.toggle })
      : await act("/api/undo", { name, id: t.dataset.remove }, "Removed: kept in the file, off the card");
    closePop();
    const lost = (r && r.uncovered) || [];   // the kept corrections this leaves uncovered: said plainly, never blocked
    if (lost.length) toast(`Off the card, so ${lost.length === 1 ? "one of your corrections is" : lost.length + " of your corrections are"} no longer covered: that misreading can come back`);
    if (r) loadMetrics();                    // switched back on, or off: the counts follow either way
    return;
  }
  if (t.dataset.unbind) return act("/api/agent-unbind", { folder: t.dataset.unbind }, "Unbound: the agents there are known by their tool again");
  if (t.dataset.feature) { const on = t.getAttribute("aria-checked") !== "true"; return act("/api/feature", { name, feature: t.dataset.feature, on }, on ? "On: one rule added to this environment" : "Off: that rule is off the card"); }
  if (t.dataset.setting) { const on = t.getAttribute("aria-checked") !== "true"; const r = await act("/api/setting", { key: t.dataset.setting, on }, on ? "On" : "Off"); if (r) pollFeed(); return; }
  const d = t.dataset.do;
  if (d === "close-pop") return closePop();
  if (d === "test-agent") { S.testAgent = t.dataset.name; return go("test"); }
  if (d === "layers-agent") { S.layers.agent = t.dataset.name; S.layers.card = null; return go("layers"); }
  if (d === "editor") return openEditor();
  if (d === "env-menu") return openMenu(t);
  if (d === "new-env") return openNew();
  if (d === "undo-last") return act("/api/undo-last", { name }, "Undone: the last saved version is back, and the one it replaced is kept");
  if (d === "add-ideas") {
    const ids = [...document.querySelectorAll("#ideasList input[data-idea]:checked:not(:disabled)")].map(i => i.dataset.idea);
    if (!ids.length) return toast("Tick the suggestions you want first");
    return act("/api/add-suggestions", { name, ids }, `Added ${plural(ids.length, "rule")}`);
  }
  if (t.id === "save") {
    try { await api("/api/source", { name, text: $("editor").value }); $("editStatus").className = "status-line meta"; $("editStatus").textContent = "Saved. The old version is kept."; await load(); render(); }
    catch (e) { $("editStatus").className = "status-line meta bad"; $("editStatus").textContent = "Not saved: " + e.message; }
    return;
  }
  if (t.id === "revert") return openEditor();
  if (t.id === "edClose") { $("editorDlg").hidden = true; return; }
});
document.addEventListener("keydown", (e) => {
  if (!inOwn(e.target) && e.key !== "Escape") return;
  if (e.key === "Enter" && e.target.matches("tr[data-at]")) { e.target.click(); return; }
  if (e.key !== "Escape") return;
  if (!$("rulecard").hidden) { closePop(); return; }
  if (!$("editorDlg").hidden) { $("editorDlg").hidden = true; return; }
  if (!$("newEnv").hidden) { $("newEnv").hidden = true; return; }
  closeMenu();
});
document.addEventListener("change", (ev) => {
  if (ev.target.id === "layAgent") { S.layers.agent = ev.target.value; refreshLayers(); }
});
document.addEventListener("toggle", (ev) => {   // toggle does not bubble, so it is caught on the way down
  if (ev.target.id !== "ideasBox") return;
  S.ideasOpen = ev.target.open;
  if (ev.target.open) loadIdeas();
}, true);
document.addEventListener("submit", async (ev) => {
  const f = ev.target;
  if (!inOwn(f)) return;
  ev.preventDefault();
  if (f.id === "teachFromTest") {
    const words = f.elements.words.value.trim();
    if (!words) return toast("Write it first, in your own words");
    // the very message just tried is kept beside the rule, as its test
    const misread = S.test ? S.test.message : "";
    if (await act("/api/learn", { name: S.state.active, words, agent: null, misread: misread || null },
      misread ? "Added, with the message kept as its test" : "Added: every agent gets it with your next message")) loadMetrics();
    return;
  }
  if (f.id === "bindForm") {
    const agent = f.elements.agent.value.trim(), folder = f.elements.folder.value.trim();
    if (agent && folder) await act("/api/agent-bind", { agent, folder }, `Every agent in that folder is now ${agent}`);
    return;
  }
  if (f.id === "addRule") {
    const words = f.elements.words.value.trim(), agent = f.elements.scope ? f.elements.scope.value : "";
    if (!words) return toast("Write the rule first, in your own words");
    await act("/api/learn", { name: S.state.active, words, agent: agent || null }, agent ? `Added, for ${label(agent)} only` : "Added, with your words kept beside it");
    return;
  }
  if (f.dataset.agentRule) {
    const input = f.querySelector("input");
    const r = await act("/api/learn", { name: S.state.active, words: input.value, agent: f.dataset.agentRule }, `Added, for ${label(f.dataset.agentRule)} only`);
    if (r) input.value = "";
    return;
  }
  if (f.dataset.agentLabel) { await act("/api/agent-name", { agent: f.dataset.agentLabel, label: f.querySelector("input").value.trim() }, "Named"); return; }
  if (f.id === "testForm") {
    const message = f.elements.message.value.trim();
    if (!message) return toast("Type a message to try");
    try {
      const r = await api("/api/explain", { message, words: f.elements.words.value || null, agent: f.elements.agent.value });
      S.test = fromTest(r, message, false);
      fill("testFlow", testFlow());
    } catch (e) { toast(e.message); }
  }
});
if (typeof matchMedia === "function") matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { Sky.kick(); Space.kick(); });
