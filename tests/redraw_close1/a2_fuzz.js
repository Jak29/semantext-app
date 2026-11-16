// Fuzz of a2: a list of rows (each an unkeyed empty note and an unkeyed quantity "1"); the person is in one row's field;
// a read inserts, removes, reorders or keeps the rows (real draws). Classified: SAME_ROW (focus kept in the person's row),
// letGo (no focus), OTHER_ROW (the focus and the old range went to another row's field).
const P = { name: "rows", title: "Rows", origin: "semantext-rows", version: "1.0", module: true };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [P] });
S.data.rows = { rows: ["Ticket 1", "Ticket 2", "Ticket 3"] };
location.hash = "#rows";
route();
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  await tick(); await settled(); await tick();
  const place = document.getElementById("place");
  const rowOf = (el) => { for (let x = el; x; x = x.parentNode) if (x.className === "row") return x.childNodes[0].textContent; return null; };
  let seed = 4242;
  const rnd = (k) => { seed = (seed * 1103515245 + 12345) % 2147483648; return Math.floor(seed / 65536) % k; };
  let next = 4;
  const tally = {}, examples = {};
  for (let i = 0; i < 80; i++) {
    const start = Array.from({ length: 2 + rnd(4) }, () => "Ticket " + (next++));
    S.data.rows = { rows: start }; S.rev++; fill(); await tick(); await settled(); await tick();
    const pick = rnd(start.length), cls = rnd(2) ? "note" : "qty";
    const f = place.all((e) => e.className === cls && rowOf(e) === start[pick])[0];
    f.focus(); if (cls === "qty") f.setSelectionRange(0, 1, "forward"); else f.setSelectionRange(0, 0, "none");
    const op = ["insertAbove", "remove", "reorder", "same"][rnd(4)];
    let rows = start.slice();
    if (op === "insertAbove") rows.splice(rnd(pick + 1), 0, "Ticket " + (next++));
    if (op === "remove") rows.splice(rnd(rows.length), 1);
    if (op === "reorder") rows = rows.slice().reverse();
    S.data.rows = { rows }; S.rev++; fill(); await tick(); await settled(); await tick();
    const a = document.activeElement;
    const r = a && a !== document.body ? rowOf(a) : null;
    const v = r === null ? "letGo" : r === start[pick] ? "SAME_ROW" : "OTHER_ROW";
    const tag = op + "/" + v;
    tally[tag] = (tally[tag] || 0) + 1;
    if (v === "OTHER_ROW" && !examples[op]) examples[op] = { held: start[pick] + " " + cls, rows, focusedRow: r, range: [a.selectionStart, a.selectionEnd] };
  }
  report({ tally, examples });
})();
