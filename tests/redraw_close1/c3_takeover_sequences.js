// D22's takeover (mine), through the page's OWN refresh(). A plug-in place whose module is still being imported (a slow
// first import: nothing async in the module). The place's meta line ("Slowly . added by ...") is drawn at once at every
// draw, so words in it are wholly inside the place. The person holds S1 there; a read draws (and waits for the import);
// the person then changes the selection (a click's caret, other words, a longer or shorter selection, words in the banner,
// a release) or leaves it; 1, 2 or 3 more reads come; the import lands.
// The law: what the person changed is theirs. Never S1 again once they changed it.
let n = 3;
const refresh = __ticks[0];
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
const probs = [{ reader: "rules", source: "a.md", line: 3, text: "an unknown key in the rules file" }];
return (async () => {
  const out = {}, tally = {};
  let c = 0;
  S.open.add("problems:show");
  for (const act of ["caret", "other", "extend", "shrink", "banner", "release", "nothing"]) {
    for (const more of [1, 2, 3]) {
      const name = "slowc" + (c++);
      const Pn = { name, title: "Slowly", origin: "semantext-slow", version: "1.0", module: true };
      const fr = () => ({ name: null, word: null, waiting: 0, problems: probs, outside: [Pn] });
      globalThis.fetch = async (url) => (String(url).includes("/api/v2/" + name)
        ? { ok: true, json: async () => ({ items: n, frame: fr() }) }
        : { ok: false, status: 404, json: async () => ({ error: "none" }) });
      let release;
      const mod = { render(data, el, h) { el.replaceChildren(h.h("p", { class: "slow-row" }, "Slow words here: " + data.items)); } };
      importer.load = () => new Promise((r) => { release = () => r(mod); });
      applyFrame(fr());
      location.hash = "#" + name;
      await route(); await flush();
      const el = document.getElementById("place"), box = document.getElementById("problems");
      const sel = window.getSelection();
      const meta = () => el.childNodes[0].childNodes[0];
      const bannerText = () => box.all((e) => e.tagName === "LI")[0].childNodes[0].childNodes[0];
      sel.removeAllRanges();
      if (act === "shrink") sel.setBaseAndExtent(meta(), 0, meta(), 14); else sel.setBaseAndExtent(meta(), 0, meta(), 7);
      const s1 = String(sel);
      n++; await refresh(); await flush();                       // read 1: a draw that waits for the import
      let mine = null;
      if (act === "caret") { sel.collapse(meta(), 12); mine = ""; }
      if (act === "other") { sel.setBaseAndExtent(meta(), 9, meta(), 14); mine = String(sel); }
      if (act === "extend") { sel.setBaseAndExtent(meta(), 0, meta(), 14); mine = String(sel); }
      if (act === "shrink") { sel.setBaseAndExtent(meta(), 0, meta(), 7); mine = String(sel); }
      if (act === "banner") { sel.setBaseAndExtent(bannerText(), 3, bannerText(), 14); mine = String(sel); }
      if (act === "release") { sel.removeAllRanges(); mine = ""; }
      for (let i = 0; i < more; i++) { n++; await refresh(); await flush(); }
      release();
      await settled(); await flush();
      const after = String(sel);
      let v;
      if (act === "nothing") v = after === s1 ? "kept" : after === "" ? "letGo" : "OTHER";
      else if (after === s1 && mine !== s1) v = "OLD_BACK";
      else if (after === mine && mine !== "") v = "PERSONS";
      else if (after === "") v = mine === "" ? "stays_released" : "letGo";
      else v = "OTHER";
      out[act + "_" + more + "more"] = { s1, mine, after, verdict: v };
      tally[v] = (tally[v] || 0) + 1;
      sel.removeAllRanges();
    }
  }
  report({ tally, out });
})();
