// D25 x the focus (mine). keep() puts back "a focus the draw dropped (on the page)": at a late finish, if nothing is
// focused, the control that was focused before the draw is focused again (by its key), and D21 then puts its range back.
// With an async render that draws at once and then waits (D25), the wait is real time. The person, whose field the draw
// took, does NOT go back into it: they click on the page's words instead (a click on text focuses nothing). When the
// module's read lands the focus is put into the field, with the old range selected; the next key goes there.
const P = { name: "mform", title: "Form", origin: "semantext-mform", version: "1.0", module: true };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [P] });
S.data.mform = { q: "hello world", n: 1, mode: "first" };
location.hash = "#mform";
route();
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  await tick(); await settled(); await tick();
  const place = document.getElementById("place");
  const sel = window.getSelection();
  const field = (k) => place.all((e) => e.getAttribute("data-k") === k)[0];
  const words = () => place.all((e) => e.className === "form-row")[0].childNodes[0];
  const other = document.createElement("button"); other.setAttribute("data-k", "elsewhere"); other.append("A button elsewhere"); document.body.append(other);
  const out = {};
  const one = async (name, real, person) => {
    globalThis.__hold = null; S.data.mform = { q: "hello world", n: S.data.mform.n + 1, mode: "first" }; S.rev++;
    fill(); await tick(); await settled(); await tick();
    sel.removeAllRanges();
    const f = field("tix-q"); f.focus(); f.setSelectionRange(2, 7, "forward");
    let go; globalThis.__hold = new Promise((r) => { go = r; });
    if (real) { S.data.mform = Object.assign({}, S.data.mform, { n: S.data.mform.n + 1 }); S.rev++; }
    fill(); await tick();
    person();                                              // while the module waits on its own read
    const during = document.activeElement === field("tix-q") ? "the field" : document.activeElement === other ? "the button" : "nothing";
    go(); globalThis.__hold = null; await settled(); await tick();
    const g = field("tix-q");
    const now = document.activeElement === g ? "the field" : document.activeElement === other ? "the button" : "nothing";
    const rec = { focusWhileItWaited: during, focusAfterTheFinish: now, fieldRange: [g.selectionStart, g.selectionEnd, g.selectionDirection], value: g.value };
    if (now === "the field") { const s = g.selectionStart, e = g.selectionEnd; g.value = g.value.slice(0, s) + " " + g.value.slice(e); rec.afterTheSpaceBar = g.value; }
    out[name] = rec;
  };
  // a click on the page's words: whatever was focused loses the focus, and a caret is left in the words
  const clickOnWords = () => { if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur(); sel.collapse(words(), 6); };
  const goToButton = () => { other.focus(); };
  for (const real of [true, false]) {
    const s = real ? "_real" : "_quiet";
    await one("personClickedOnThePagesWords" + s, real, clickOnWords);
    await one("control_personWentToAnotherControl" + s, real, goToButton);
    await one("control_untouched" + s, real, () => {});
  }
  report(out);
})();
