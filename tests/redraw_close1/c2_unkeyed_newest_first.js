// D21's unkeyed refind (mine). A plain module (it keys nothing) lists tickets newest first, each with an empty reply box
// and an "assign to" field. The person clicks into ONE ticket's reply box to answer it; a read brings a new ticket in on
// top (or takes one away, or re-sorts). The page then "finds the field again" by its old path in the place and checks
// only that what stands there READS the same; every empty reply box reads the same. Then the person types.
const P = { name: "inbox", title: "Inbox", origin: "semantext-inbox", version: "1.0", module: true };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [P] });
S.data.inbox = { tickets: ["B: the scanner jams", "A: the printer is broken"] };
location.hash = "#inbox";
route();
const tick = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
return (async () => {
  await tick(); await settled(); await tick();
  const place = document.getElementById("place");
  const ticketOf = (el) => { for (let x = el; x; x = x.parentNode) if (x.className === "ticket") return x.childNodes[0].textContent; return null; };
  const boxIn = (subject, cls) => place.all((e) => e.className === cls && ticketOf(e) === subject)[0];
  const typeWord = (f, w) => { f.value = f.value.slice(0, f.selectionStart) + w + f.value.slice(f.selectionEnd); };
  const out = {};
  const one = async (name, start, subject, cls, next, real, typedFirst) => {
    S.data.inbox = { tickets: start }; S.rev++; fill(); await tick(); await settled(); await tick();
    const f = boxIn(subject, cls); f.focus();
    if (typedFirst) { f.value = typedFirst; }
    f.setSelectionRange(f.value.length, f.value.length, "none");
    S.data.inbox = { tickets: next }; if (real) S.rev++;
    fill(); await tick(); await settled(); await tick();
    const a = document.activeElement;
    const now = a && a !== document.body ? ticketOf(a) : null;
    const rec = { personWasIn: subject + " / " + cls, next, focusNowIn: now, verdict: now === null ? "letGo" : now === subject ? "SAME_TICKET" : "OTHER_TICKET" };
    if (now !== null) { typeWord(a, "On it, fixing today"); rec.replyLandedIn = ticketOf(a); rec.repliesNow = place.all((e) => e.className === cls).map((e) => ticketOf(e) + " => " + JSON.stringify(e.value)); }
    out[name] = rec;
  };
  const AB = ["B: the scanner jams", "A: the printer is broken"];
  await one("reply_newTicketOnTop", AB, "A: the printer is broken", "reply", ["C: the door is stuck", ...AB], true);
  await one("reply_topTicket_newTicketOnTop", AB, "B: the scanner jams", "reply", ["C: the door is stuck", ...AB], true);
  await one("assignee_newTicketOnTop", AB, "A: the printer is broken", "assignee", ["C: the door is stuck", ...AB], true);
  await one("reply_ticketAboveClosed", ["C: the door is stuck", ...AB], "B: the scanner jams", "reply", AB, true);
  await one("reply_ownTicketClosed", ["C: the door is stuck", ...AB], "C: the door is stuck", "reply", AB, true);
  await one("reply_resorted", AB, "A: the printer is broken", "reply", AB.slice().reverse(), true);
  await one("control_sameTickets_real", AB, "A: the printer is broken", "reply", AB, true);
  await one("control_sameTickets_quiet", AB, "A: the printer is broken", "reply", AB, false);
  await one("control_typedBeforeTheRead_newTicketOnTop", AB, "A: the printer is broken", "reply", ["C: the door is stuck", ...AB], true, "half a rep");
  const v = Object.values(out);
  report({ summary: { OTHER_TICKET: v.filter((c) => c.verdict === "OTHER_TICKET").length, SAME_TICKET: v.filter((c) => c.verdict === "SAME_TICKET").length, letGo: v.filter((c) => c.verdict === "letGo").length }, out });
})();
