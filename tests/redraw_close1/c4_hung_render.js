// D22 x D25 (mine). "drop() clears a draw that never finishes." A draw whose async render never settles (the module's own
// read never answers) never reaches keep()'s later(), so it is never dropped, superseded or not.
//  A. same place, later: the person released the words long ago; a click's caret in the place and two reads bring them back.
//  B. another place of the same plug-in: words selected on place A are selected on place B, where the person selected nothing.
//  C. control: the same steps with a render that does settle.
const A = { name: "atix", title: "Tickets", origin: "semantext-x", version: "1.0", module: true };
const B = { name: "tix", title: "Reports", origin: "semantext-x", version: "1.0", module: true };
const frame = () => ({ name: null, word: null, waiting: 0, problems: [], outside: [A, B] });
globalThis.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/v2/atix")) return { ok: true, json: async () => ({ n: 3, frame: frame() }) };
  if (u.includes("/api/v2/tix")) return { ok: true, json: async () => ({ items: [1, 2], frame: frame() }) };
  return { ok: false, status: 404, json: async () => ({ error: "none" }) };
};
const tick = async () => { for (let i = 0; i < 40; i++) await Promise.resolve(); };
return (async () => {
  const out = {};
  const place = document.getElementById("place");
  const sel = window.getSelection();
  const row = (i) => place.all((e) => e.className === "tix-row")[i].childNodes[0];
  const meta = () => place.childNodes[0].childNodes[0];
  const draw = async () => { S.rev++; fill(); await tick(); await tick(); };
  const start = async () => { applyFrame(frame()); location.hash = "#atix"; await route(); await tick(); await tick(); sel.removeAllRanges(); };

  for (const hung of [true, false]) {
    const tag = hung ? "hung" : "control_settles";
    // A. same place, later
    await start();
    sel.setBaseAndExtent(row(0), 12, row(0), 23);                       // "the printer"
    const s1 = String(sel);
    let go; globalThis.__hold = hung ? new Promise(() => {}) : new Promise((r) => { go = r; });
    S.rev++; fill(); await tick();                                      // the read whose render waits on its own read
    if (!hung) { go(); await tick(); }
    globalThis.__hold = null;
    const afterThatRead = String(sel);
    sel.setBaseAndExtent(row(1), 0, row(1), 6); const other = String(sel);   // the person selects other words ...
    await draw(); const otherKept = String(sel) === other;
    sel.removeAllRanges(); await draw();                                 // ... and lets go; two reads that finish
    sel.collapse(row(1), 4);                                             // a click in the place: a caret, no words
    await draw(); const afterOneRead = String(sel);
    await draw(); const afterTwoReads = String(sel);
    out[tag + "_A_samePlaceLater"] = { s1, afterThatRead, otherKept, afterOneRead, afterTwoReads,
      verdict: afterTwoReads === s1 ? "OLD_WORDS_BACK" : afterTwoReads === "" ? "nothing_selected" : "OTHER" };

    // B. another place of the same plug-in
    sel.removeAllRanges();
    await start();
    sel.setBaseAndExtent(meta(), 8, meta(), meta().data.length);         // ". added by semantext-x 1.0" in Tickets' meta line
    const m1 = String(sel);
    let go2; globalThis.__hold = hung ? new Promise(() => {}) : new Promise((r) => { go2 = r; });
    S.rev++; fill(); await tick();
    if (!hung) { go2(); await tick(); }
    globalThis.__hold = null;
    if (!hung) sel.removeAllRanges();                                    // (where it settled the words were put back: the person lets go before leaving)
    location.hash = "#tix"; await route(); await tick(); await tick();   // the person goes to Reports
    out[tag + "_B_otherPlace"] = { selectedOnTickets: m1, nowOn: S.place, metaNow: meta().data, selectedOnReports: String(sel),
      verdict: String(sel) === "" ? "nothing_selected" : String(sel) === m1 ? "WORDS_OF_THE_OTHER_PLACE_SELECTED" : "OTHER" };
    sel.removeAllRanges();
  }
  report(out);
})();
