// D21 x D25 (mine). A plug-in form whose render is async and draws its fields AT ONCE, then waits on a read of its own.
// D21 says "a replaced field was never in the page for the person to move"; D25 makes keep() wait for the whole render,
// so the NEW field is in the page, for the person to click and type in, for as long as the module's own read takes.
// Each case: a range or caret held in a keyed field; a read draws; while the module waits the person goes back into the
// field the page shows and acts; the module's read lands. Then one more key is "typed" (what a key does in a field: it
// replaces the field's selection), to show where the person's next key goes.
const P = { name: "mform", title: "Form", origin: "semantext-mform", version: "1.0", module: true };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [P] });
S.data.mform = { q: "hello world", n: 1, mode: "first" };
location.hash = "#mform";
route();
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  await tick(); await settled(); await tick();
  const place = document.getElementById("place");
  const field = (k) => place.all((e) => e.getAttribute("data-k") === k)[0];
  const typeKey = (f, ch) => { const s = f.selectionStart, e = f.selectionEnd, v = f.value; f.value = v.slice(0, s) + ch + v.slice(e); f.setSelectionRange(s + ch.length, s + ch.length, "none"); };
  const typeWord = (f, w) => { for (const ch of w) typeKey(f, ch); };
  const out = {};
  const one = async (name, key, held, mode, real, person) => {
    globalThis.__hold = null;
    S.data.mform = { q: "hello world", n: S.data.mform.n + 1, mode }; S.rev++;
    fill(); await tick(); await settled(); await tick();                  // a clean start: the fields as the module draws them
    const f = field(key); f.focus(); f.setSelectionRange(...held);
    let go; globalThis.__hold = new Promise((r) => { go = r; });
    if (real) { S.data.mform = Object.assign({}, S.data.mform, { n: S.data.mform.n + 1 }); S.rev++; }
    fill(); await tick();                                                 // the page reads; the module draws and waits
    const g = field(key);
    const inPageDuringWait = !!g && g !== f && document.contains(g);
    let theirs = null, typed = null;
    if (inPageDuringWait && person) { person(g); theirs = [g.selectionStart, g.selectionEnd, g.selectionDirection]; typed = g.value; }
    go(); globalThis.__hold = null;
    await settled(); await tick();
    const k = field(key);
    const after = [k.selectionStart, k.selectionEnd, k.selectionDirection];
    const rec = { held, mode, real, inPageDuringWait, theirs, after, value: k.value, focused: document.activeElement === k };
    if (theirs) {
      rec.verdict = String(after) === String(theirs) ? "PERSON_KEPT" : String(after) === String(held) ? "PERSON_UNDONE" : "OTHER";
      typeKey(k, "!");
      rec.afterNextKey = k.value;
      rec.wanted = typed.slice(0, theirs[0]) + "!" + typed.slice(theirs[1]);
      rec.nextKeyWhereThePersonWas = rec.afterNextKey === rec.wanted;
    } else rec.verdict = String(after) === String(held) ? "kept" : "lost";
    out[name] = rec;
  };
  const typeAtEnd = (g) => { g.focus(); g.setSelectionRange(g.value.length, g.value.length, "none"); typeWord(g, " again"); };
  const clickAt = (n) => (g) => { g.focus(); g.setSelectionRange(n, n, "none"); };
  const selectWord = (g) => { g.focus(); g.setSelectionRange(0, 5, "forward"); };
  const backspaceAtEnd = (g) => { g.focus(); const v = g.value; g.value = v.slice(0, -1); g.setSelectionRange(v.length - 1, v.length - 1, "none"); };
  for (const real of [true, false]) {
    const s = real ? "_real" : "_quiet";
    await one("range_thenTypedAtEnd" + s, "tix-q", [2, 7, "forward"], "first", real, typeAtEnd);
    await one("caret_thenTypedAtEnd" + s, "tix-q", [5, 5, "none"], "first", real, typeAtEnd);
    await one("range_thenClickElsewhereInIt" + s, "tix-q", [0, 11, "forward"], "first", real, clickAt(3));
    await one("note_range_thenSelectedAWord" + s, "tix-note", [6, 10, "backward"], "first", real, selectWord);
    await one("caret_thenBackspace" + s, "tix-q", [2, 2, "none"], "first", real, backspaceAtEnd);
    await one("control_untouched_drawsFirst" + s, "tix-q", [2, 7, "forward"], "first", real, null);
    await one("control_untouched_drawsLast" + s, "tix-q", [2, 7, "forward"], "last", real, null);
  }
  // control: the person went to the OTHER field while the module waited; neither field is touched
  {
    globalThis.__hold = null;
    S.data.mform = { q: "hello world", n: S.data.mform.n + 1, mode: "first" }; S.rev++; fill(); await tick(); await settled(); await tick();
    const f = field("tix-q"); f.focus(); f.setSelectionRange(2, 7, "forward");
    let go; globalThis.__hold = new Promise((r) => { go = r; });
    S.rev++; fill(); await tick();
    const note = field("tix-note"); note.focus(); note.setSelectionRange(4, 4, "none");
    go(); globalThis.__hold = null; await settled(); await tick();
    const q = field("tix-q"), n2 = field("tix-note");
    out.control_wentToTheOtherField = { q: [q.selectionStart, q.selectionEnd], note: [n2.selectionStart, n2.selectionEnd], focusOnNote: document.activeElement === n2 };
  }
  const undone = Object.values(out).filter((c) => c.verdict === "PERSON_UNDONE").length;
  const persons = Object.values(out).filter((c) => c.theirs).length;
  report({ summary: { personCases: persons, PERSON_UNDONE: undone, nextKeyElsewhere: Object.values(out).filter((c) => c.theirs && !c.nextKeyWhereThePersonWas).length }, out });
})();
