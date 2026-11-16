// The page's one way to ask the reader. The reader is semantext/reading.py, the same one `semantext read` prints from
// (reading.report): this file only sends the words to it and checks what comes back, and never reads a message itself,
// so the page and the command line cannot disagree. Prism's message box and Rules' Try a message both use it.
//
// It is a POST because the person's words must never travel in an address (browsers, proxies and logs keep those). The
// route changes nothing and writes nothing: it only answers. The words go to Semantext on this machine and no further.

// An answer, checked in this order: the status first, then the body. A body that is not JSON (a proxy's page, an
// empty reply, a cut connection) is said plainly, never passed on as a reading.
// Named readerAnswer, not answer: the page tests are handed every module's exports as names (tests/v2_dom.js), and a test
// that declares its own `answer` (test_v2_plugins_page) failed on the shared one.
export async function readerAnswer(r) {
  let j = null, bad = false;
  try { j = await r.json(); } catch (e) { bad = true; }
  if (!r.ok) {
    const said = !bad && j && typeof j.error === "string" ? j.error : "";
    throw new Error(said || r.statusText || "the server answered " + (r.status || "with an error"));
  }
  if (bad || j === null || typeof j !== "object" || Array.isArray(j)) throw new Error("the server's answer was not readable");
  return j;
}

// The message (and, where there is one, the agent's last offer) read clause by clause, with the advice for each act the
// words name. Rejects with a plain reason; an answer in the wrong shape is a failure, never an empty reading.
export async function readMessage(message, offer) {
  const body = { message: String(message == null ? "" : message) };
  if (offer) body.offer = String(offer);
  const r = await fetch("/api/read", { method: "POST", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Semantext": "1" }, body: JSON.stringify(body) });
  const j = await readerAnswer(r);
  if (!shaped(j)) throw new Error("the answer was not in the shape the page expects");
  return j;
}

// Whether an answer is the shape the page draws from, to its last element (R6): lists of the right things, strings where
// the page prints a string. A well-shaped wrong element ({readings:[null]}, a reading with no acts list, an advice of
// null) would throw inside the page's drawing and leave the last figure standing, so it is refused here, whole. This
// checks shape only; what the reader means by its words is the reader's (semantext/reading.py) and is never judged here.
const text = (x) => typeof x === "string";
const maybe = (x) => x === undefined || x === null || text(x);
const flag = (x) => x === undefined || typeof x === "boolean";
const record = (x) => x !== null && typeof x === "object" && !Array.isArray(x);
export function shaped(j) {
  if (!record(j) || !Array.isArray(j.readings) || !Array.isArray(j.advice)) return false;
  if (!flag(j.clipped) || !flag(j.unreadable) || (j.max_chars !== undefined && typeof j.max_chars !== "number")) return false;
  if (j.clipped === true && typeof j.max_chars !== "number") return false;   // "Read up to undefined characters" is no sentence
  return j.readings.every((r) => record(r) && text(r.clause) && text(r.kind) && text(r.label) && Array.isArray(r.acts)
      && r.acts.every(text) && maybe(r.time))
    && j.advice.every((a) => record(a) && text(a.act) && text(a.word) && text(a.rule) && text(a.why)
      && (a.quote === undefined || text(a.quote)) && maybe(a.bound) && flag(a.covers));
}

// What one act's advice says, in the page's words. An ASK whose words appear to cover the act is never shown as a go:
// the reader fills the ask in, and the person confirms it.
export function adviceLine(a) {
  if (a.covers) return "your words appear to say go: confirm" + (a.bound ? " (within “" + a.bound + "”)" : "");
  return String(a.why || "");
}
