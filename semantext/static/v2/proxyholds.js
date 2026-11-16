// The proxy holds: the calls the proxy is keeping for your word, listed in Waiting, and your answer to each (yes once, no,
// or revoke for a yes not yet used). Your answer is the same one `semantext proxy answer` makes, sent from your own page
// to the one route below; nothing here runs anything. The list is the tool and the agent and why it is held, never what
// the call was given and never your words.
import { h } from "./dom.js";
import { plural } from "./words.js";
import { S, fill } from "./app.js";

export const ASKS_ROUTE = "/api/proxy/asks";
export const PROXY_ROUTE = "/api/proxy/answer";
const SAYS = { yes: "Said yes", no: "Said no", revoke: "Took the yes back" };

// state: null before the first read (nothing is drawn), then "none" (no proxy has run), "stopped" (one ran and none runs
// now), "ok", "unreadable" (a damaged file at the proxy), or "unread" (this page could not ask Semantext for it).
export const HOLDS = { state: null, asks: [], sig: "", reading: false, again: false, busy: new Set(), note: "", noteAsk: "", noteWord: "", problem: "" };

// Read what the proxy holds. Called whenever Waiting reads again; a read that changed nothing changes nothing, and one
// that fails is said on the page, never raised into Waiting's own read.
export async function holdsRead() {
  if (HOLDS.reading) { HOLDS.again = true; return; }
  HOLDS.reading = true;
  let next = { state: "unread", asks: [] };
  try {
    const r = await fetch(ASKS_ROUTE, { headers: { "X-Semantext": "1" }, cache: "no-store" });
    const d = r.ok ? await r.json() : null;
    if (d && ["none", "stopped", "ok", "unreadable"].includes(d.state) && Array.isArray(d.asks)) next = { state: d.state, asks: d.asks };
  } catch (e) { /* said below as unread */ }
  HOLDS.reading = false;
  const sig = JSON.stringify(next);
  if (sig !== HOLDS.sig) {
    HOLDS.sig = sig;
    HOLDS.state = next.state;
    HOLDS.asks = next.asks;
    // A note is a fact about the list it was made against. "The proxy releases that call once" is true only while the
    // list still shows that ask as a yes; once the state is anything but ok (none, stopped, unreadable, a failed read),
    // or the ask is gone or no longer a yes (used, run out, taken back elsewhere), the note would promise what is not so.
    if (HOLDS.note) {
      const listed = next.state === "ok" ? next.asks.find((a) => a.id === HOLDS.noteAsk) : null;
      if (next.state !== "ok" || (HOLDS.noteWord === "yes" && !(listed && listed.status === "yes"))) HOLDS.note = "";
    }
    if (S.place === "waiting") fill();
  }
  if (HOLDS.again) { HOLDS.again = false; await holdsRead(); }
}

export const proxyPost = { post: (body) => fetch(PROXY_ROUTE, { method: "POST", cache: "no-store",
  headers: { "X-Semantext": "1", "Content-Type": "application/json" }, body: JSON.stringify(body) }) };

// One press, one answer. The server refuses a second (an ask answered is no longer open), and says why on the page.
export async function answerAsk(a, word) {
  if (HOLDS.busy.has(a.id)) return;
  HOLDS.busy.add(a.id);
  HOLDS.note = ""; HOLDS.problem = "";
  fill();
  let r = null, got = {};
  try {
    r = await proxyPost.post({ ask: a.id, word });
    try { got = await r.json(); } catch (e) { /* the status says enough */ }
  } catch (e) { got = { error: "the page could not reach Semantext" }; }
  HOLDS.busy.delete(a.id);
  if (r && r.ok) {
    HOLDS.note = SAYS[word] + " to " + a.agent + "'s call of " + a.tool + (word === "yes" ? ": the proxy releases that call once, in that chat: with its held turn at the chat's next message if every call of the turn has your yes, or when the agent makes the call again; not while your newest message in that chat names one of its acts other than as a plain go." : ".");
    HOLDS.noteAsk = a.id; HOLDS.noteWord = word;
  }
  else HOLDS.problem = "Not taken: " + (got.error || "that answer was not accepted.");
  await holdsRead();
  fill();
}

export function openHolds() { return HOLDS.state === "ok" ? HOLDS.asks.filter((a) => a.status === "open").length : 0; }

function left(m) { return m < 1 ? "less than a minute left" : plural(m, "minute") + " left"; }

function askNode(a) {
  const busy = HOLDS.busy.has(a.id);
  const press = (word, label) => h("button", { type: "button", class: "answer", disabled: busy, "data-k": "proxy:" + a.id + ":" + word,
    on: { click: () => answerAsk(a, word) } }, label);
  const yes = a.status === "yes";
  return h("article", { class: "card is-waiting", "data-proxy-ask": a.id },
    h("p", { class: "card-title" }, a.agent + " wants to call " + a.tool),
    h("p", { class: "meta" }, "Held because: " + a.why + " · " + left(a.minutes_left) + " · " + a.id),
    yes ? h("p", { class: "meta" }, "You said yes. It releases that call once, in that chat: with its held turn at the chat's next message if every call of the turn has your yes, or when the agent makes the call again, but not while your newest message in that chat names one of its acts other than as a plain go; revoke it if you have changed your mind.") : null,
    h("div", { class: "answers" }, yes ? press("revoke", "Revoke") : [press("yes", "Yes once"), press("no", "No")]));
}

// The section's children, or none before the first read.
export function holdsNodes() {
  if (HOLDS.state === null) return [];
  const asks = HOLDS.state === "ok" ? HOLDS.asks : [];
  const open = openHolds();
  const head = h("h2", { class: "label group-head" }, "The proxy holds" + (asks.length ? " · " + open + " waiting" + (asks.length > open ? ", " + (asks.length - open) + " said yes" : "") : ""));
  const said = HOLDS.state === "none" ? "No proxy has run from this Semantext home, so none holds a call for you. Start one at your terminal with `semantext proxy serve`."
    : HOLDS.state === "stopped" ? "No proxy is running from this Semantext home, and what it held went with it. Start one at your terminal with `semantext proxy serve`."
    : HOLDS.state === "unreadable" ? "The proxy's files could not be read, so nothing is listed. `semantext proxy asks` at your terminal says why."
    : HOLDS.state === "unread" ? "Could not read what the proxy holds."
    : asks.length ? "" : "Nothing waits for your word at the proxy.";
  return [head, said ? h("p", { class: "shelf-note" }, said) : null,
    asks.length ? h("div", { class: "cards" }, asks.map(askNode)) : null,
    HOLDS.note ? h("p", { class: "shelf-note", role: "status" }, HOLDS.note) : null,
    HOLDS.problem ? h("p", { class: "refused", role: "alert" }, HOLDS.problem) : null].filter(Boolean);
}
