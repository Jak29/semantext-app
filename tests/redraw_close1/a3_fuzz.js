// Fuzz of a3: the person holds S1 in the place; a read draws (an async module that waits on its own read); while it waits
// the person acts (caret click, other words, release, nothing) and 1 to 3 more draws of the place come. Classified at the
// end: OLD_BACK (S1's words again although the person changed them), PERSONS (the person's own selection), letGo, kept
// (S1 untouched and kept), OTHER.
const P = { name: "atix", title: "Tickets", origin: "semantext-atix", version: "1.0", module: true };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [P] });
S.data.atix = { n: 3 };
location.hash = "#atix";
route();
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  await tick(); await settled(); await tick();
  const place = document.getElementById("place");
  const sel = window.getSelection();
  const texts = () => [place.childNodes[0].childNodes[0], ...place.all((e) => e.className === "tix-row").map((e) => e.childNodes[0])];
  let seed = 777;
  const rnd = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return Math.floor(seed / 65536) % k; };
  const pickRange = () => {
    const t = texts(); const a = t[rnd(t.length)], b = t[rnd(t.length)];
    const ao = rnd(a.data.length + 1), bo = rnd(b.data.length + 1);
    sel.setBaseAndExtent(a, ao, b, bo);
    return String(sel);
  };
  const tally = {}, examples = {};
  let cases = 0;
  while (cases < 100) {
    sel.removeAllRanges();
    const s1 = pickRange();
    if (!s1) continue;
    cases++;
    let go; globalThis.__hold = new Promise((r) => { go = r; });
    S.rev++; S.data.atix = { n: S.data.atix.n }; fill();
    await tick();
    const act = ["caret", "other", "release", "nothing"][rnd(4)];
    let mine = null;
    if (act === "caret") { const t = texts(); const x = t[rnd(t.length)]; sel.collapse(x, rnd(x.data.length + 1)); mine = ""; }
    if (act === "other") { mine = pickRange(); }
    if (act === "release") { sel.removeAllRanges(); mine = ""; }
    const more = 1 + rnd(3);
    for (let i = 0; i < more; i++) { if (rnd(2)) S.rev++; fill(); await tick(); }
    go(); globalThis.__hold = null;
    await settled(); await tick();
    const after = String(sel);
    let v;
    if (act === "nothing") v = after === s1 ? "kept" : after === "" ? "letGo" : "OTHER";
    else if (after === s1 && mine !== s1) v = "OLD_BACK";
    else if (after === mine && mine !== "") v = "PERSONS";
    else if (after === "") v = "letGo";
    else v = "OTHER";
    const tag = act + "/" + (more) + "more/" + v;
    tally[tag] = (tally[tag] || 0) + 1;
    if ((v === "OLD_BACK" || v === "OTHER") && !examples[act + v]) examples[act + v] = { s1, mine, after, more };
  }
  const sum = {};
  for (const [k, n] of Object.entries(tally)) { const v = k.split("/")[2]; sum[v] = (sum[v] || 0) + n; }
  report({ cases, sum, tally, examples });
})();
