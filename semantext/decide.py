"""The decision on a turn, the asks it makes, and their release (PROXY-DESIGN r4: sections 4 and 5, 5b; J2, T1, T6,
T8, T9, T11, U1 to U6).

A turn's calls are decided together, at the turn's end, on the one assembled message:

  - a call to a tool no `tool` block of the agent declares is UNMATCHED: held when the space's default is hold;
  - a call that any gate matches is held, unless a live release for exactly this act exists, which it then spends;
    a gate matches a call when it names the call's tool or model, or when it names a field the proxy cannot read in
    v0 (acts, classes, spend): an act that cannot be classified matches (ARCHITECTURE section 3);
  - a call with any stop reason other than tool_use is held (D3b);
  - if any call is held, the whole turn is held (Koinos 3): the blocks before the first held call stay, nothing from
    it on is emitted (J2), and one held-text block, built from kernel-known words only (T9), says which asks wait.

Asks live in a file beside the record (the person answers from another process: the app or the CLI). They are tied
to the proxy's own run: an ask from an earlier run is void, so a release never outlives the stash it would replay
(U2) and expiry needs no clock shared between runs. Within a run, expiry is on the monotonic clock (T11).

Which chat a yes belongs to: the conversation key groups chats that start alike (and a client may send no session
header), so each ask also holds a keyed digest of the history it was asked after (Chain). A yes releases a call only
in a request whose history begins with exactly that, and then is that same history again or goes on with the assistant
turn that carries the ask's held text. Another chat, or the same chat with an earlier message edited, is held anew.
What a chat is depends on the header (C6, refined by C8). With a session header (x-claude-code-session-id) the session
and the messages are the chat: the system and the tools list may change inside it (Claude Code loads tools on demand,
MCP servers connect), and a yes still finds its call. With no session header a chat is its system and its tools as
well as its messages: the chain starts from a digest of the whole system (every block) and the tools list, so the same
messages under another project's system block, or another tools list, are another chat. A system given as one string
is one text block, as a message's content is. Cache markers are ignored where they are markers and nowhere else (C7,
Chain).
*Limits, stated:* with no session header, a chat whose whole system, tools and history so far are identical to the
held request's is the same conversation to the proxy (it is the same request), and a client that changes its system or
its tools between two requests of one chat (a new date in a system block, a tool added) is held again and the person is
asked again. With a session header two chats of one session with the same messages are one chat to the proxy, and a
client that moves to other tools or another system inside its session keeps its yes; the session header is the
client's word, and a client that sends another's session id is not stopped (it is the agent's own harness). In both
cases a client that rewrites its earlier messages (compaction, trimming) is held again, and one that forges its history
is not stopped. The conversation key still reads the first system block, so a client whose FIRST system block changes
inside a session is another conversation to the proxy, though the chain would allow it (measured by the attack on
a1ff89a): its kept turn is not found, and a call the model makes again is held with a second ask, so the person is
asked again; the old yes stays unspent.
C9: the replay spends EVERY ask of a kept turn that the re-decision did not (Outcome.released lists what it did), all
or none, so an ask revoked or spent between replay_due and the spend refuses the replay instead of being skipped.

Stash and replay (T1, U1 to U5): a held turn's calls are kept in memory only, bound to the conversation key and the
history it was held after. When
every ask of that turn is answered yes, the next model request with the same key, whose history holds the held text as
the assistant turn before its last user turn, is answered by the proxy with that turn's calls, once, after the whole
decision runs again on them (U3). A call whose input has a secret shape is held but never stashed (U2), and a turn with
thinking on is not replayed (U5).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import actclass, canon, reading
from .assemble import Refused
from .proxy_record import mint
from .store import file_lock, read_settled, write_atomic

class Chain:
    """A keyed hash chain over a request's start and messages: the conversation's history, in digests (no session
    header needed).

    digest[0] is a keyed start. With no session header it covers the request's WHOLE system (every block) and its
    tools list (C6: a chat is its system and its tools too; two chats with the same messages but another project's
    system block or another tools list are two chats, where the conversation key reads only system[0] and the first
    message). With a session header it covers the session only (C8): the session and the messages are the chat, and
    the system and the tools may change inside it. digest[k] = HMAC(node
    key, digest[k-1] + sha256 of message k, canonical). A message is made canonical before it is hashed: a bare string
    becomes one text block, and a `cache_control` marker is dropped where it is a marker (C7: see `plain_block`): a
    client moves those markers from request to request without changing what was said. The chain lives for one
    request; only digests are ever stored (in an ask, a kept turn's key), never a message.

    `prefix(n)` is the digest of the first n messages, or None past the end. `holds(n, aid)` says whether message n
    (counting from 0, the one right after those n) is an assistant turn that carries the held text of ask `aid`: the
    proxy wrote that text, with the ask's random id in it, so another chat does not have it."""

    def __init__(self, key: bytes, messages, system=None, tools=None, session: str | None = None):
        self.messages = messages if isinstance(messages, list) else []
        # C8: with a session header the session is the chat's start, and the system and the tools may change inside
        # it (Claude Code loads tools on demand, MCP servers connect); without one they are all the start there is.
        # The marker "session" cannot be a system list, so the two forms never collide.
        what = ["session", session] if session else [plain_system(system), plain_tools(tools)]
        start = hashlib.sha256(canon.dumps(what).encode()).digest()
        d = hmac.new(key, b"semantext chain 0" + start, hashlib.sha256).digest()
        self._d = [d]
        for m in self.messages:
            d = hmac.new(key, d + hashlib.sha256(canon.dumps(_plain(m)).encode()).digest(), hashlib.sha256).digest()
            self._d.append(d)
    @property
    def count(self) -> int:
        return len(self.messages)

    @property
    def head(self) -> str:
        return self._d[-1].hex()

    def prefix(self, n) -> str | None:
        if isinstance(n, bool) or not isinstance(n, int) or not 0 <= n <= self.count:
            return None
        return self._d[n].hex()

    def holds(self, n: int, aid: str) -> bool:
        if not 0 <= n < self.count:
            return False
        m = self.messages[n]
        if not isinstance(m, dict) or m.get("role") != "assistant":
            return False
        c = m.get("content")
        texts = [c] if isinstance(c, str) else [b.get("text") for b in c if isinstance(b, dict)] if isinstance(c, list) else []
        return any(isinstance(t, str) and aid in t for t in texts)


def _plain(m):
    """A message in the one shape the chain hashes (see Chain)."""
    if isinstance(m, dict) and isinstance(m.get("content"), str):
        m = {**m, "content": [{"type": "text", "text": m["content"]}]}
    if isinstance(m, dict) and isinstance(m.get("content"), list):
        m = {**m, "content": [plain_block(b) for b in m["content"]]}
    return m


def plain_block(b):
    """A content block without its cache marker (C7). `cache_control` is dropped only where it is a marker: on the
    block itself (a text, tool_use, tool_result or any other block of a message, a system block, a tool definition)
    and on the blocks inside a tool_result's content list, down as far as tool_results nest. It is never dropped inside
    a tool_use `input` or any other data: a field of that name there is what the model sent, and two chats that differ
    only there are two chats (found by the attack on the conversation key)."""
    if not isinstance(b, dict):
        return b
    b = {k: v for k, v in b.items() if k != "cache_control"}
    if b.get("type") == "tool_result" and isinstance(b.get("content"), list):
        b["content"] = [plain_block(x) for x in b["content"]]
    return b


def plain_system(system):
    """The request's system as the chain hashes it: its blocks without cache markers, and a system given as one string
    as one text block (C8: the two spellings are one chat, as a message's are). The conversation key reads it the
    same way."""
    if isinstance(system, str):
        return [{"type": "text", "text": system}]
    return [plain_block(b) for b in system] if isinstance(system, list) else system


def plain_tools(tools):
    """The request's tools list as the chain hashes it: each definition without its cache marker, and nothing inside
    it touched (a schema property named cache_control is data)."""
    return [plain_block(t) for t in tools] if isinstance(tools, list) else tools

ASK_TTL_S = 3600
MAX_OPEN_ASKS = 20
MAX_UNDECLARED = 5          # open asks for tools the agent may not call: their own pool (P2)
HELD_PREFIX = "[semantext] "


@dataclass
class Call:
    index: int
    id: str
    name: str
    input: object
    d_act: str
    tool: str | None          # the declaring tool block's id, or None (unmatched)


@dataclass
class Outcome:
    held: bool
    content: list             # the blocks to emit, in order, indices to be renumbered by the emitter
    stop_reason: str
    asks: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    held_text: str = ""
    released: list = field(default_factory=list)   # the asks this decision itself spent (C9: the replay spends the rest)
    over_yes: list = field(default_factory=list)   # asks with a yes whose call the person's newer words hold again


_UNREAD = object()


class Reading:
    """One reading of the ask store: the asks file as read, and the chain read at most once, on first use."""

    def __init__(self, asks: "Asks", rows: list):
        self._asks, self.asks, self._chain = asks, rows, _UNREAD

    def chain(self):
        if self._chain is _UNREAD:
            self._chain = self._asks._chain_state()
        return self._chain


class Asks:
    """The asks of this proxy run, in a file the person's channel also writes answers to.

    The file is not the authority for a yes (Orithises P1). With a record, an answer is also written to the chain as an
    `answered` line, and a yes counts only while the chain's LAST answered word for that ask is yes and no `spent` line
    lists it (C2); a spend writes `spent`. So a crash between a chain line and the file write (a revoke, a spend)
    cannot leave a yes that releases: the chain wins, and `status` says "unproved" (the words differ) or "spent".
    *Limit, stated (A1):* a process with the person's file rights can write the asks file AND seal a chain line and
    move the head; that is harder than editing one file, and it is not prevented. The anchor (ARCHITECTURE section 2)
    is what would catch it.

    With a node key, an ask holds the keyed digest of its input, never the unkeyed one (Orithises P12).
    Asks for an undeclared tool have their own small pool (MAX_UNDECLARED), so they cannot shut the agent's real asks
    out (P2); a yes releases one as it does any other."""

    def __init__(self, path: str | Path, run: str, key: bytes | None = None, record=None):
        self.path = Path(path)
        self.lock = self.path.with_name(self.path.name + ".lock")
        self.run, self.key, self.record = run, key, record
        self.on_closed = None        # called with an ask id when a no or a revoke closes it here (the proxy's stash)

    def _digest(self, d_act: str) -> str:
        return canon.d_rec(self.key, d_act) if self.key else d_act

    def _chain_state(self):
        """The chain read once, in one pass: ({ask: its LAST answered word}, {asks a `spent` line lists}), or None
        with no record. The chain's last word decides (found by the critic, C2): `answered` lines for an ask are
        read in order and the last one stands, so a yes that a later revoke overtook is not a yes, and a spent ask is
        spent whatever the asks file says. A crash between a chain line and the file write leaves the file behind the
        chain; the chain wins."""
        if self.record is None:
            return None
        last, spent = {}, set()
        for r in self.record.lines():
            body = r.get("body")
            if not isinstance(body, dict):
                continue
            if r.get("kind") == "answered" and isinstance(body.get("ask"), str):
                last[body["ask"]] = body.get("word")
            elif r.get("kind") == "spent" and isinstance(body.get("asks"), list):
                spent.update(x for x in body["asks"] if isinstance(x, str))
        return last, spent

    def _on_chain(self, aid: str, word: str, state=_UNREAD) -> bool:
        """Whether the chain holds `word` for this ask as its last answer (a yes also needs: not spent). With no
        record, true. `state` is a reading already made (`Reading.chain()`); without one the chain is read here."""
        state = self._chain_state() if state is _UNREAD else state
        if state is None:
            return True
        last, spent = state
        return last.get(aid) == word and not (word == "yes" and aid in spent)

    def snapshot(self) -> "Reading":
        """The asks file read now and, when first needed, the chain read once: one reading for a pass over many asks
        (a sweep, a replay check), so the chain is not read again for each ask."""
        return Reading(self, self._read())

    def _read(self) -> list:
        # The store's own tools (found by the attack on the replay work, C1): on Windows a reader and the swap of a
        # write collide (WinError 5), 400 of 400 writes failed against three spinning readers. read_settled and
        # write_atomic retry that refusal for about a second, and write_atomic's temporary name is its own.
        try:
            data = json.loads(read_settled(self.path))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            raise Refused("X-EXC", "the ask store cannot be read") from None
        return [a for a in data if isinstance(a, dict)]

    def _write(self, asks: list) -> None:
        try:
            write_atomic(self.path, json.dumps(asks))
        except OSError:
            raise Refused("X-EXC", "the ask store cannot be written") from None

    def live(self, a: dict, now: float) -> bool:
        return a.get("run") == self.run and now < a.get("expires", 0)

    @staticmethod
    def bound(a: dict, chain: "Chain | None") -> bool:
        """Whether this request is the conversation the ask was made in (the conversation binding). With no chain
        (a caller that has no messages) nothing is checked. Otherwise the ask must carry the digest of the history it
        was asked after, and this request's history must begin with exactly that, and then either be that same history
        (the very same request again) or go on with the assistant turn that carries this ask's held text. So a chat
        whose earlier messages differ, or that never held this ask, is another conversation, whatever its key says."""
        if chain is None:
            return True
        n, d = a.get("n"), a.get("chain")
        if isinstance(n, bool) or not isinstance(n, int) or not isinstance(d, str):
            return False
        mine = chain.prefix(n)
        if mine is None or not hmac.compare_digest(mine, d):
            return False
        return n == chain.count or chain.holds(n, str(a.get("id")))

    def open(self, agent: str, space: str, tool: str, act: str, d_act: str, conv: str, now: float,
             reading: dict | None = None, chain: "Chain | None" = None) -> str:
        """The id of the open ask for this act (one canonical act, one ask) in this conversation, or a new one; refused
        at the cap. `reading`, when the person's words held the call: {"act", "word", "rule"} only, never their words.
        `chain` binds the ask to the history it is asked after (digests only; see Chain and bound)."""
        return self.open_all([(agent, space, tool, act, d_act, conv, reading)], now, chain)[0]

    def open_all(self, specs: list, now: float, chain: "Chain | None" = None) -> list:
        """The asks of a whole turn, opened together, one id per spec (agent, space, tool, act, d_act, conv, reading)
        in order. The cap is checked for the whole turn before any ask is written (found by the critic, C5): opened
        call by call, a 21-call turn left 20 open asks behind and then refused the 21st, and the agent was shut out
        for an hour. Now a turn whose NEW asks would pass a cap is refused and opens none. An ask that is reused (one
        canonical act is one ask, also among the turn's own calls) is not counted; the undeclared pool counts apart."""
        with file_lock(self.lock):
            asks = self._read()
            fresh, ids = [], []
            for agent, space, tool, act, d_act, conv, reading in specs:
                d_act = self._digest(d_act)
                found = next((a for a in asks + fresh
                              if self.live(a, now) and a["status"] == "open" and a["agent"] == agent
                              and a["space"] == space and a["tool"] == tool and a["d_act"] == d_act
                              and a["conv"] == conv and self.bound(a, chain)), None)
                if found:
                    ids.append(found["id"])
                    continue
                ask = {"id": mint("ask"), "run": self.run, "agent": agent, "space": space, "tool": tool, "act": act,
                       "d_act": d_act, "conv": conv, "status": "open", "expires": now + ASK_TTL_S}
                if chain is not None:
                    ask["n"], ask["chain"] = chain.count, chain.head
                if reading:
                    ask["reading"] = {k: str(reading[k]) for k in ("act", "word", "rule") if k in reading}
                fresh.append(ask)
                ids.append(ask["id"])
            for agent, pool in {(a["agent"], self._pooled(a)) for a in fresh}:
                cap = MAX_UNDECLARED if pool else MAX_OPEN_ASKS
                held = sum(1 for a in asks if self.live(a, now) and a["status"] == "open" and a["agent"] == agent
                           and self._pooled(a) == pool)
                if held + sum(1 for a in fresh if a["agent"] == agent and self._pooled(a) == pool) > cap:
                    raise Refused("X-ASK", f"this agent has {cap} asks waiting already"
                                           + (" for tools it may not call" if pool else ""))
            if fresh:
                self._write(asks + fresh)
            return ids

    @staticmethod
    def _pooled(a: dict) -> bool:
        return str(a["tool"]).startswith("undeclared")
    def answer(self, aid: str, word: str, now: float) -> bool:
        """The person's answer (yes, no or revoke), from their own channel. False when the ask is not live."""
        if word not in ("yes", "no", "revoke"):
            raise ValueError("an answer is yes, no or revoke")
        with file_lock(self.lock):
            asks = self._read()
            for a in asks:
                if a["id"] == aid and self.live(a, now):
                    if word == "revoke":
                        if a["status"] != "yes":
                            return False
                        a["status"] = "revoked"
                    elif a["status"] != "open":
                        return False
                    else:
                        a["status"] = word
                    if self.record is not None:                       # the chain, before the file says so
                        self.record.append("answered", {"ask": aid, "word": word})
                    self._write(asks)
                    if word in ("no", "revoke") and self.on_closed is not None:
                        self.on_closed(aid)   # U2b: in this process, its kept turn goes now; others, by the sweep
                    return True
            return False

    def yes_for(self, agent: str, space: str, tool: str, d_act: str, conv: str, now: float,
                chain: "Chain | None" = None) -> str | None:
        """A live yes for exactly this act in this conversation, if there is one (the model re-issued the call). With
        a `chain`, only a yes whose ask was made in this very history (bound). The record is read once, and only when
        an ask passes every other test."""
        d_act = self._digest(d_act)
        seen = self.snapshot()
        for a in seen.asks:
            if (self.live(a, now) and a["status"] == "yes" and a["agent"] == agent and a["space"] == space
                    and a["tool"] == tool and a["d_act"] == d_act and a["conv"] == conv
                    and self.bound(a, chain) and self._on_chain(a["id"], "yes", seen.chain())):
                return a["id"]
        return None

    def asked_after(self, aid: str):
        """How many messages the history held when this ask was made (its `n`), or None (no chain was given)."""
        for a in self._read():
            if a.get("id") == aid:
                n = a.get("n")
                return n if isinstance(n, int) and not isinstance(n, bool) else None
        return None

    def status(self, aid: str, now: float, seen: "Reading | None" = None) -> str:
        """The ask's state, from the file and the chain together. A caller that asks about many asks passes one
        `seen` (snapshot()), so the file and the chain are read once for the pass."""
        seen = seen or self.snapshot()
        for a in seen.asks:
            if a["id"] == aid:
                if not self.live(a, now):
                    return "expired"
                if a["status"] not in ("yes", "revoked", "no"):
                    return a["status"]
                chain = seen.chain()
                if chain is not None and a["status"] == "yes" and aid in chain[1]:
                    return "spent"                        # a spent line is on the chain; the file write after it was lost
                # The chain's word for a revoked ask is "revoke" (found by U4e: it read "unproved", so a revoke made
                # from another process was never swept from memory as the law says).
                word = "revoke" if a["status"] == "revoked" else a["status"]
                if not self._on_chain(aid, word, chain):
                    return "unproved"                     # the file says so; the chain's last word does not (P1, C2)
                return a["status"]
        return "unknown"

    def spend(self, aids: list, now: float) -> bool:
        """Spend the releases of a turn, all or none, atomically (T11): True only if every one was a live yes."""
        with file_lock(self.lock):
            seen = self.snapshot()
            asks = seen.asks
            mine = [a for a in asks if a["id"] in aids]
            if len(mine) != len(aids) or not all(self.live(a, now) and a["status"] == "yes"
                                                 and self._on_chain(a["id"], "yes", seen.chain()) for a in mine):
                return False
            for a in mine:
                a["status"] = "spent"
            if self.record is not None:
                self.record.append("spent", {"asks": list(aids)})
            self._write(asks)
            return True

def stash_key(conv: str, digest: str | None) -> str:
    """Where a kept turn lives: its conversation key and the digest of the history it was held after, so two chats
    that share a key keep their own turns instead of one overwriting the other."""
    return conv if digest is None else f"{conv}|{digest}"


@dataclass
class Stashed:
    conv: str
    model: str
    asks: list
    calls: list               # the tool_use blocks, as judged
    held_text: str
    thinking: bool
    key: str = ""             # where it is kept (stash_key)


class Stash:
    """Held turns' calls, in memory only (U2): lost with the process."""

    def __init__(self):
        self._turns: dict[str, Stashed] = {}
        self._lock = threading.Lock()

    def put(self, key: str, s: Stashed) -> None:
        with self._lock:
            self._turns[key] = s

    def take(self, key: str) -> Stashed | None:
        with self._lock:
            return self._turns.pop(key, None)

    def peek(self, key: str) -> Stashed | None:
        with self._lock:
            return self._turns.get(key)

    def drop(self, key: str) -> None:
        with self._lock:
            self._turns.pop(key, None)

    def drop_ask(self, aid: str) -> None:
        """Drop every kept turn that waits on this ask (a no or a revoke closed it)."""
        with self._lock:
            for k in [k for k, s in self._turns.items() if aid in s.asks]:
                self._turns.pop(k, None)

    def sweep(self, asks: "Asks", now: float) -> int:
        """Koinos U2b: a kept turn whose answer is no, revoked, expired, spent or unknown is dropped now, not when a
        request next finds it, so a refused call's input does not stay in memory. Returns how many were dropped."""
        with self._lock:
            keys = list(self._turns)
        if not keys:
            return 0
        seen = asks.snapshot()                            # one reading for the pass, not one per ask (C2)
        dead = []
        for k in keys:
            s = self.peek(k)
            if s and any(asks.status(a, now, seen) in ("no", "expired", "unknown", "revoked", "spent") for a in s.asks):
                dead.append(k)
        for k in dead:
            self.drop(k)
        return len(dead)


def held_text(asks: list, first_tool_label: str, kept: bool = True, over_yes: list = ()) -> str:
    """Kernel-known words only (T9): a declared tool's name or a fixed phrase, the ask ids, fixed words."""
    ids = ", ".join(asks)
    # An ask that already has the person's yes, held again by their newer words (the newest words win): said so.
    tail = (f" Ask {', '.join(over_yes)} has the person's yes, but their newest message holds the call again: it can "
            f"go through once after a later message of theirs that does not hold it." if over_yes else "")
    # Nothing promised that the proxy does not control (P3). Koinos U2a: the words differ when the turn is not kept (a
    # secret-shaped input, a thinking turn): then a yes can only release the very same call made again.
    if not kept:
        return (f"{HELD_PREFIX}Waiting for the person's word on {first_tool_label} (ask {ids}). This turn was not kept: "
                f"if they answer yes, the same call must be made again, and it can then go through once.{tail}")
    return (f"{HELD_PREFIX}Waiting for the person's word on {first_tool_label} (ask {ids}). If they answer yes, "
            f"the same call can go through once.{tail}")


def names_and_holds(words: str, acts, memo: dict):
    """Whether the person's words hold a call over a yes they already gave: the first act of `acts` that some clause of
    the words NAMES and whose advice is not a plain go (the reading where the words appear to say go), or None. Each act
    is looked at on its own (reading.held_by_words stops at the first act it holds, so a go that is not plain for one
    act hid a stop for the next). Words that name none of the acts ("ok, go ahead now", "thanks", a bare "stop") hold
    nothing here. The words alone are read, never the offer: a bare yes binds to an offer, and here it answers nothing.
    Limits: a word for the act the reader does not know names nothing; a sentence about the past that names the act
    ("I already deleted the logs") holds (the cheap direction)."""
    if not acts or not isinstance(words, str) or not words.strip():
        return None
    if "read" not in memo:
        memo["read"] = reading.read(words)
    for a in acts:
        if a not in reading.ACTS:
            continue
        key = "named:" + a
        if key not in memo:
            memo[key] = None
            if any(a in r.acts for r in memo["read"].readings):
                adv = reading.advise(memo["read"], a)
                if adv.word != "ALLOWED" and not adv.covers:
                    memo[key] = {"act": a, "word": adv.word, "rule": adv.rule}
        if memo[key]:
            return memo[key]
    return None


def _ask_tool(c: Call) -> str:
    """The tool an ask is for: the declaring block's id, or for an undeclared tool "undeclared:" and a digest of its
    name. Koinos (attack on the reader's wiring): keyed by "undeclared" alone, a yes on one undeclared tool released ANOTHER with
    the same input (send_email {"x":"1"} released delete_file {"x":"1"})."""
    return c.tool or "undeclared:" + canon.d_act(c.name)[:24]


def _gates_for(space, call: Call, model_id: str) -> list:
    out = []
    for gid, g in space.of("gate").items():
        m = g["match"]
        if (call.tool and call.tool in m.get("tools", [])) or model_id in m.get("models", []) \
                or any(k in m for k in ("acts", "classes", "spend_over")):
            out.append(gid)
    return out


def calls_of(space, agent_id: str, msg: dict) -> list:
    agent = space.blocks[agent_id]
    declared = {space.blocks[t]["name"]: t for t in agent.get("tools", [])}
    out = []
    for i, b in enumerate(msg.get("content", [])):
        if b.get("type") == "tool_use":
            name = b.get("name")
            name = name if isinstance(name, str) else ""
            out.append(Call(i, str(b.get("id", "")), name, b.get("input"), canon.d_act(b.get("input")),
                            declared.get(name)))
    return out


def decide(space, space_id: str, agent_id: str, model_id: str, msg: dict, conv: str, asks: Asks, now: float,
           secret_shape=lambda value: False, kept: bool = True, words: str | None = None,
           offer: str | None = None, chain: Chain | None = None, words_at: int | None = None,
           hold_only=None) -> Outcome:
    """`chain` is this request's history (Chain): a yes releases a call only in the history its ask was made in, and an
    ask is opened in it. The proxy always gives one; None (a library caller with no messages) checks no history.
    `words` is the person's latest message and `offer` the agent's text before it, when the caller has them: the
    reader (reading.held_by_words) may then HOLD a call whose act the words hold, as a gate would, released the same
    way by the person's yes on its ask. The words only ever add holds.

    The newest words win over an earlier yes, in the holding direction only: `words_at` is the index of the message the
    words are in. When those words were written after the ask was made (a later message than the held turn) and they
    name one of the call's acts other than as a plain go (names_and_holds, each act on its own), the call is held as it
    would be with no yes, on that same ask (no new ask is opened), and the yes is not spent. The words the ask was made
    after do not undo its yes (the yes answered them), and without `words_at` or a chain the order cannot be known and
    the yes stands, as before.

    `hold_only` is [(text, message index)] read ONLY to add holds, on both paths (proxy.hold_only_words: words typed
    beside a tool's result, a message read with an unclosed reminder tag kept). It is read with no offer and never
    takes the place of `words`: it cannot release, answer an ask or bind a yes."""
    calls = calls_of(space, agent_id, msg)
    stop = msg.get("stop_reason")
    if not calls:
        if stop == "tool_use":                     # Koinos K4: a client may wait for a result that cannot come
            raise Refused("X-ASM", "a turn that stopped for a tool call and holds none")
        return Outcome(False, list(msg.get("content", [])), stop, calls=[])
    default_hold = space.settings.get("default") == "hold"
    held_idx, released, readings, memo, over = [], [], {}, {}, {}
    hold_only = [(t, i) for t, i in (hold_only or ()) if isinstance(t, str) and t.strip() and isinstance(i, int)]
    # Hold-only text (beside a tool's result, after an unclosed reminder tag), in the order given (what the person
    # typed first: proxy.hold_only_words), joined: one reading per
    # decision whatever the number of messages (the reader reads its first 20,000 characters). Read with no offer, so
    # a bare yes there binds to nothing; it can add a hold and nothing else.
    extra = "\n".join(t for t, _ in hold_only)
    extra_memo, after = {}, {}                             # after: {n: (the text of messages after n, its memo)}
    for c in calls:
        gates = _gates_for(space, c, model_id)
        acts = actclass.acts_of_call(c.name, c.input) if (words or extra) else ()
        by_words = reading.held_by_words(words, acts, offer=offer, memo=memo) if words else None
        if not by_words and extra:
            by_words = reading.held_by_words(extra, acts, memo=extra_memo)
        if by_words:
            readings[c.index] = by_words
        if stop != "tool_use":
            held_idx.append(c)
        elif (c.tool is None and default_hold) or gates or by_words:  # P2: an undeclared call's yes releases it too
            yes = asks.yes_for(agent_id, space_id, _ask_tool(c), c.d_act, conv, now, chain)
            if yes and ((words and words_at is not None) or extra):
                n = asks.asked_after(yes)
                if n is not None and n not in after:
                    t = "\n".join(t for t, i in hold_only if i > n)
                    after[n] = (t, {})
                newer = n is not None and (
                    (words_at is not None and words_at > n and names_and_holds(words, acts, memo))
                    or names_and_holds(after[n][0], acts, after[n][1]))
                if newer:                                  # newer words than the held turn: they win
                    over[c.index] = yes
                    held_idx.append(c)
                    continue
            # Koinos (attack on the reader's wiring): one yes releases ONE call; a second identical call in the turn is held
            if yes and yes not in released:
                released.append(yes)
            else:
                held_idx.append(c)
    if not held_idx:
        if released and not asks.spend(released, now):
            raise Refused("X-REL", "a release was spent by another request at the same moment")
        return Outcome(False, list(msg.get("content", [])), stop, calls=calls, released=list(released))
    first = held_idx[0]
    # The unit is the turn (U4): every held call has its ask, all opened at once, so the cap is checked for the whole
    # turn before any ask is written (C5). A call held again over its yes keeps that ask: none is opened for it.
    fresh = iter(asks.open_all([(agent_id, space_id, _ask_tool(c), "call", c.d_act, conv, readings.get(c.index))
                                for c in held_idx if c.index not in over], now, chain))
    aids = [over[c.index] if c.index in over else next(fresh) for c in held_idx]
    label = first.tool and space.blocks[first.tool]["name"] or "a tool the agent may not call"
    over_ids = sorted(set(over.values()), key=aids.index)
    text = held_text(sorted(set(aids), key=aids.index), label, kept, over_ids)
    # Before the first held call, the non-call blocks stay; no call of a held turn is emitted, even one that would
    # have passed on its own (found by test_one_held_call_holds_the_turn).
    # Koinos K3: cut at the first CALL, not the first held one: text after any call presupposes it ran, and in a held
    # turn no call runs.
    content = list(msg["content"][:calls[0].index]) + [{"type": "text", "text": text}]
    return Outcome(True, content, "end_turn", asks=sorted(set(aids), key=aids.index), calls=calls, held_text=text,
                   over_yes=over_ids)


def keepable(msg: dict, secret_shape) -> bool:
    """Whether a held turn would be kept for replay: no input of a secret shape (U2). Asked BEFORE the held text is
    written, so the text says the truth (Koinos U2a)."""
    blocks = [b for b in msg.get("content", []) if b.get("type") == "tool_use"]
    return not any(secret_shape(canon.dumps(b.get("input"))) for b in blocks)


def stash_turn(stash: Stash, conv: str, model: str, out: Outcome, msg: dict, thinking: bool, secret_shape,
               chain: Chain | None = None) -> bool:
    """Keep a held turn's calls for replay (T1). Not when any input has a secret shape (U2). True when stashed. With a
    `chain` (the history of the request that was held) it is kept under that history too."""
    blocks = [b for b in msg.get("content", []) if b.get("type") == "tool_use"]
    if not keepable(msg, secret_shape):
        return False
    key = stash_key(conv, chain.head if chain is not None else None)
    stash.put(key, Stashed(conv, model, out.asks, blocks, out.held_text, thinking, key))
    return True


def replay_due(stash: Stash, asks: Asks, conv: str, model: str, route: str, history: list, now: float,
               chain: Chain | None = None):
    """The stashed turn to replay for this request, or None (U1, U4, U5). Spends nothing; the caller re-decides (U3)
    and then spends. With a `chain`, the turn is looked for under the history before the last two messages (the held
    turn and the user turn after it): a chat whose history is not the one the turn was held in finds nothing."""
    if route != "/v1/messages":
        return None
    if chain is None:
        key = conv
    else:
        before = chain.prefix(len(history) - 2)
        if before is None:
            return None
        key = stash_key(conv, before)
    s = stash.peek(key)
    if s is None or s.model != model or s.thinking:
        return None
    if not history or history[-1].get("role") != "user" or len(history) < 2:
        return None
    prior = history[-2]
    content = prior.get("content")
    if prior.get("role") != "assistant" or not isinstance(content, list):
        return None
    if not any(isinstance(b, dict) and b.get("type") == "text" and b.get("text") == s.held_text for b in content):
        return None
    seen = asks.snapshot()                                # one reading for the whole turn's asks
    states = [asks.status(a, now, seen) for a in s.asks]
    if any(st in ("no", "expired", "unknown", "revoked", "spent") for st in states):
        stash.drop(key)                                   # zeroised on no, expiry and spend (U2)
        return None
    if not all(st == "yes" for st in states):
        return None
    return s
