// Settings: environments, switches, connections.
import { $, S, back, h, fill, act, api, ago, clock, copyBtn, enc, envTitle, fmt, label, live, plural, render, go, still, stepsView, fromRecord, fromTest, claimsYou, count, palette, rgba, toast, when, WORDS, HOW, loadMetrics, RULE_FOR, VIEWS } from "./ownbase.js";

export async function loadModels() {
  try {
    const m = await api("/api/models");
    fill("models", m.local.length ? ["On this computer: ", m.local.join(", "), ". ", h("button", { class: "link", type: "button", "data-copy": `semantext export modelfile --base ${m.local[0]}` }, "Copy the command"), " for an Ollama Modelfile with your card."]
      : "None found. A model you pull with Ollama appears here.");
  } catch (e) { fill("models", "Could not look: " + e.message); }
}
export function openMenu(anchor) {
  const st = S.state;
  fill("envMenu", [
    st.profiles.filter(p => p.name !== "base").map(p => h("button", { type: "button", role: "menuitem", "data-env": p.name },
      h("span", { class: "tick" }, p.name === st.active ? "✓" : ""), p.title, h("span", { class: "meta", "data-sp": "ml-auto" }, plural(p.rules, "rule")))),
    h("hr"), h("button", { type: "button", role: "menuitem", "data-do": "new-env" }, h("span", { class: "tick" }, "+"), "New environment")]);
  const m = $("envMenu"), r = (anchor || $("envPill")).getBoundingClientRect();
  m.hidden = false;
  m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
  m.style.top = Math.min(r.bottom + 6, innerHeight - m.offsetHeight - 8) + "px";
  const pill = $("envPill"); if (pill) pill.setAttribute("aria-expanded", "true");
}
export function closeMenu() { const m = $("envMenu"); if (m) m.hidden = true; const pill = $("envPill"); if (pill) pill.setAttribute("aria-expanded", "false"); }
export function openNew() { closeMenu(); $("newEnv").hidden = false; $("newName").value = ""; fill("picks", []); $("newFor").textContent = ""; $("newName").focus(); }
export async function suggest() {
  const title = $("newName").value.trim();
  if (!title) { fill("picks", []); $("newFor").textContent = ""; return; }
  const s = await api("/api/suggest?title=" + enc(title));
  $("newFor").textContent = s.matched ? `Suggested for ${title}` : "No close match, so some ideas to start from";
  fill("picks", s.rules.map(r => h("li", {}, h("label", {},
    h("input", { type: "checkbox", "data-pack": r.pack, "data-id": r.id, checked: r.ticked ? "" : null }),
    h("span", {}, r.statement, h("span", { class: "meta" }, "  ·  " + r.pack_title))))));
}
export async function openEditor() {
  $("edLead").textContent = `The file behind ${S.profile.environment.title}.`;
  $("editStatus").textContent = ""; $("editorDlg").hidden = false;
  try { $("editor").value = (await api("/api/source?name=" + enc(S.state.active))).text; } catch (e) { $("editStatus").className = "status-line meta bad"; $("editStatus").textContent = e.message; }
}
  VIEWS.settings = () => {
    const st = S.state, c = st.connections || {};
    const feat = (k) => live(S.profile.entries).some(e => e.id === "feature." + k && e.enabled !== false);
    const sw = (attrs, on, name) => h("button", { class: "switch", role: "switch", "aria-checked": String(on), "aria-label": name, type: "button", ...attrs });
    const setrow = (title, help, control) => h("div", { class: "setrow" }, h("div", {}, title, help ? h("div", { class: "meta" }, help) : null), control);
    return h("section", { class: "view", "data-part": "settings" },
      h("header", {}, h("h1", {}, "Settings"), h("p", { class: "sub" }, "Everything Semantext keeps is a plain file on this machine.")),
      h("section", {}, h("div", { class: "sechead" }, h("h2", { class: "label" }, "Environment")),
        setrow(S.profile.environment.title, `${plural(live(S.profile.entries).length, "rule")} of its own, on top of ${plural(live(S.base.entries).length, "shared rule")}.`,
          h("div", { class: "row" }, h("button", { class: "btn small", type: "button", "data-do": "env-menu" }, "Switch"),
            h("button", { class: "btn small", type: "button", "data-do": "new-env" }, "New"),
            h("button", { class: "btn small", type: "button", "data-do": "editor" }, "Edit the file")))),
      h("section", { class: "gap" }, h("div", { class: "sechead" }, h("h2", { class: "label" }, "Switches")),
        setrow("Match my tone", "One rule: familiar phrasing, never copying you.", sw({ "data-feature": "tone" }, feat("tone"), "Match my tone")),
        setrow("Jokes", "One rule: humour is welcome, never at your expense.", sw({ "data-feature": "jokes" }, feat("jokes"), "Jokes")),
        setrow("Ask me in the inbox", "One rule: agents file what needs your word, and wait.", sw({ "data-feature": "inbox" }, feat("inbox"), "Ask me in the inbox")),
        setrow("The feed", "One line per prompt: who asked, whose words, which card. Never what was said.", sw({ "data-setting": "feed" }, !!st.feed, "The feed")),
        setrow("Hear my prompts", "Keeps your own prompts on this machine, so rules can be proposed from them.", sw({ "data-setting": "hear_prompts" }, !!st.hear_prompts, "Hear my prompts"))),
      h("section", { class: "gap" }, h("div", { class: "sechead" }, h("h2", { class: "label" }, "Connections")),
        setrow("Claude Code", c.claude_code ? `Every prompt gets your card (${c.settings}).` : c.claude_code === null ? `Its settings file could not be read (${c.settings}).` : "Not connected yet.",
          c.claude_code ? h("span", { class: "meta" }, "Connected") : copyBtn("semantext install claude-code --apply")),
        (c.files || []).map(f => setrow("Instructions file", f.file, h("span", { class: f.ok ? "meta" : "meta warn" }, f.ok ? "Up to date" : "Block missing"))),
        setrow("Any MCP tool", "Add semantext mcp as a server: the card and the inbox.", copyBtn("semantext mcp")),
        setrow("Local models", h("span", { id: "models" }, "Looking..."), null),
        h("p", { class: "meta", "data-sp": "mt12" }, "Codex, freebuff and any agent with an instructions file: semantext install codex | freebuff | agents-md --apply.")),
      h("details", { class: "gap" }, h("summary", {}, "Recent changes"),
        st.log.length ? h("ul", { class: "list" }, st.log.map(l => h("li", { class: "line" }, h("span", { class: "when meta mono" }, String(l.when).slice(5, 16).replace("T", " ")), h("span", { class: "what" }, l.what))))
          : h("p", { class: "meta" }, "Nothing yet.")),
      h("p", { class: "meta gap" }, `Semantext ${st.version || ""}`));
  };
