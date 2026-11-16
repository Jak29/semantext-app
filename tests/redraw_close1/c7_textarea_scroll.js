// D25 x holdScroll (mine). A plug-in's keyed text box that the person has scrolled is held through a draw (D13) and put
// back at the finish. With an async render that draws the box at once and then waits (D25 makes keep() wait for it), the
// person can scroll the NEW box while the module waits; the finish then puts the OLD scroll back over theirs.
const P = { name: "notes", title: "Notes", origin: "semantext-notes", version: "1.0", module: true };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [P] });
S.data.notes = { n: 1 };
location.hash = "#notes";
route();
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  await tick(); await settled(); await tick();
  const place = document.getElementById("place");
  const box = () => place.all((e) => e.getAttribute("data-k") === "long-note")[0];
  const out = {};
  for (const [name, personScrollsTo] of [["scrolledOnWhileItWaited", 900], ["scrolledBackToTheTop", 0], ["control_untouched", null]]) {
    globalThis.__hold = null; S.rev++; fill(); await tick(); await settled(); await tick();
    box().scrollTop = 500;                                    // the person read down to here
    let go; globalThis.__hold = new Promise((r) => { go = r; });
    S.data.notes = { n: S.data.notes.n + 1 }; S.rev++; fill(); await tick();
    const duringWait = box().scrollTop;                       // the new box, as the browser shows it: at the top
    if (personScrollsTo !== null) box().scrollTop = personScrollsTo;
    const theirs = box().scrollTop;
    go(); globalThis.__hold = null; await settled(); await tick();
    out[name] = { heldAt: 500, newBoxDuringWait: duringWait, personLeftItAt: theirs, afterTheFinish: box().scrollTop,
      verdict: personScrollsTo === null ? (box().scrollTop === 500 ? "kept" : "lost") : box().scrollTop === theirs ? "PERSON_KEPT" : "PERSON_UNDONE" };
  }
  report(out);
})();
