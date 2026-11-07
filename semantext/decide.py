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

Stash and replay (T1, U1 to U5): a held turn's calls are kept in memory only, bound to the conversation key. When
every ask of that turn is answered yes, the next model request with the same key, whose history holds the held text as
the assistant turn before its last user turn, is answered by the proxy with that turn's calls, once, after the whole
decision runs again on them (U3). A call whose input has a secret shape is held but never stashed (U2), and a turn with
thinking on is not replayed (U5).
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import actclass, canon, reading
from .assemble import Refused
from .proxy_record import mint
from .store import file_lock

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


class Asks:
    """The asks of this proxy run, in a file the person's channel also writes answers to.

    The file is not the authority for a yes (Orithises P1). With a record, an answer is also written to the chain as an
    `answered` line, and a yes counts only when the whole chain holds that line for that ask; a spend writes `spent`.
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

    def _on_chain(self, aid: str, word: str) -> bool:
        if self.record is None:
            return True
        return any(r.get("kind") == "answered" and r.get("body", {}).get("ask") == aid
                   and r.get("body", {}).get("word") == word for r in self.record.lines())

    def _read(self) -> list:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            raise Refused("X-EXC", "the ask store cannot be read") from None
        return [a for a in data if isinstance(a, dict)]

    def _write(self, asks: list) -> None:
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps(asks), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            raise Refused("X-EXC", "the ask store cannot be written") from None

    def live(self, a: dict, now: float) -> bool:
        return a.get("run") == self.run and now < a.get("expires", 0)

    def open(self, agent: str, space: str, tool: str, act: str, d_act: str, conv: str, now: float,
             reading: dict | None = None) -> str:
        """The id of the open ask for this act (one canonical act, one ask), or a new one; refused at the cap.
        `reading`, when the person's words held the call: {"act", "word", "rule"} only, never their words."""
        d_act = self._digest(d_act)
        with file_lock(self.lock):
            asks = self._read()
            for a in asks:
                if (self.live(a, now) and a["status"] == "open" and a["agent"] == agent and a["space"] == space
                        and a["tool"] == tool and a["d_act"] == d_act and a["conv"] == conv):
                    return a["id"]
            pool = tool.startswith("undeclared")
            cap = MAX_UNDECLARED if pool else MAX_OPEN_ASKS
            if sum(1 for a in asks if self.live(a, now) and a["status"] == "open" and a["agent"] == agent
                   and str(a["tool"]).startswith("undeclared") == pool) >= cap:
                raise Refused("X-ASK", f"this agent has {cap} asks waiting already"
                                       + (" for tools it may not call" if pool else ""))
            aid = mint("ask")
            ask = {"id": aid, "run": self.run, "agent": agent, "space": space, "tool": tool, "act": act,
                   "d_act": d_act, "conv": conv, "status": "open", "expires": now + ASK_TTL_S}
            if reading:
                ask["reading"] = {k: str(reading[k]) for k in ("act", "word", "rule") if k in reading}
            asks.append(ask)
            self._write(asks)
            return aid

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

    def yes_for(self, agent: str, space: str, tool: str, d_act: str, conv: str, now: float) -> str | None:
        """A live yes for exactly this act in this conversation, if there is one (the model re-issued the call)."""
        d_act = self._digest(d_act)
        for a in self._read():
            if (self.live(a, now) and a["status"] == "yes" and a["agent"] == agent and a["space"] == space
                    and a["tool"] == tool and a["d_act"] == d_act and a["conv"] == conv
                    and self._on_chain(a["id"], "yes")):
                return a["id"]
        return None

    def status(self, aid: str, now: float) -> str:
        for a in self._read():
            if a["id"] == aid:
                if not self.live(a, now):
                    return "expired"
                if a["status"] in ("yes", "revoked", "no") and not self._on_chain(aid, a["status"]):
                    return "unproved"                     # the file says so; the chain does not (P1)
                return a["status"]
        return "unknown"

    def spend(self, aids: list, now: float) -> bool:
        """Spend the releases of a turn, all or none, atomically (T11): True only if every one was a live yes."""
        with file_lock(self.lock):
            asks = self._read()
            mine = [a for a in asks if a["id"] in aids]
            if len(mine) != len(aids) or not all(self.live(a, now) and a["status"] == "yes"
                                                 and self._on_chain(a["id"], "yes") for a in mine):
                return False
            for a in mine:
                a["status"] = "spent"
            if self.record is not None:
                self.record.append("spent", {"asks": list(aids)})
            self._write(asks)
            return True


@dataclass
class Stashed:
    conv: str
    model: str
    asks: list
    calls: list               # the tool_use blocks, as judged
    held_text: str
    thinking: bool


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
        dead = []
        for k in keys:
            s = self.peek(k)
            if s and any(asks.status(a, now) in ("no", "expired", "unknown", "revoked", "spent") for a in s.asks):
                dead.append(k)
        for k in dead:
            self.drop(k)
        return len(dead)


def held_text(asks: list, first_tool_label: str, kept: bool = True) -> str:
    """Kernel-known words only (T9): a declared tool's name or a fixed phrase, the ask ids, fixed words."""
    ids = ", ".join(asks)
    # Nothing promised that the proxy does not control (P3). Koinos U2a: the words differ when the turn is not kept (a
    # secret-shaped input, a thinking turn): then a yes can only release the very same call made again.
    if not kept:
        return (f"{HELD_PREFIX}Waiting for the person's word on {first_tool_label} (ask {ids}). This turn was not kept: "
                f"if they answer yes, the same call must be made again, and it can then go through once.")
    return (f"{HELD_PREFIX}Waiting for the person's word on {first_tool_label} (ask {ids}). If they answer yes, "
            f"the same call can go through once.")


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
           offer: str | None = None) -> Outcome:
    """`words` is the person's latest message and `offer` the agent's text before it, when the caller has them: the
    reader (reading.held_by_words) may then HOLD a call whose act the words hold, as a gate would, released the same
    way by the person's yes on its ask. The words only ever add holds."""
    calls = calls_of(space, agent_id, msg)
    stop = msg.get("stop_reason")
    if not calls:
        if stop == "tool_use":                     # Koinos K4: a client may wait for a result that cannot come
            raise Refused("X-ASM", "a turn that stopped for a tool call and holds none")
        return Outcome(False, list(msg.get("content", [])), stop, calls=[])
    default_hold = space.settings.get("default") == "hold"
    held_idx, released, readings, memo = [], [], {}, {}
    for c in calls:
        gates = _gates_for(space, c, model_id)
        by_words = (reading.held_by_words(words, actclass.acts_of_call(c.name, c.input), offer=offer, memo=memo)
                    if words else None)
        if by_words:
            readings[c.index] = by_words
        if stop != "tool_use":
            held_idx.append(c)
        elif (c.tool is None and default_hold) or gates or by_words:  # P2: an undeclared call's yes releases it too
            yes = asks.yes_for(agent_id, space_id, _ask_tool(c), c.d_act, conv, now)
            # Koinos (attack on the reader's wiring): one yes releases ONE call; a second identical call in the turn is held
            if yes and yes not in released:
                released.append(yes)
            else:
                held_idx.append(c)
    if not held_idx:
        if released and not asks.spend(released, now):
            raise Refused("X-REL", "a release was spent by another request at the same moment")
        return Outcome(False, list(msg.get("content", [])), stop, calls=calls)
    first = held_idx[0]
    aids = [asks.open(agent_id, space_id, _ask_tool(c), "call", c.d_act, conv, now,
                      reading=readings.get(c.index))
            for c in held_idx]                          # the unit is the turn (U4): every held call has its ask
    label = first.tool and space.blocks[first.tool]["name"] or "a tool the agent may not call"
    text = held_text(sorted(set(aids), key=aids.index), label, kept)
    # Before the first held call, the non-call blocks stay; no call of a held turn is emitted, even one that would
    # have passed on its own (found by test_one_held_call_holds_the_turn).
    # Koinos K3: cut at the first CALL, not the first held one: text after any call presupposes it ran, and in a held
    # turn no call runs.
    content = list(msg["content"][:calls[0].index]) + [{"type": "text", "text": text}]
    return Outcome(True, content, "end_turn", asks=sorted(set(aids), key=aids.index), calls=calls, held_text=text)


def keepable(msg: dict, secret_shape) -> bool:
    """Whether a held turn would be kept for replay: no input of a secret shape (U2). Asked BEFORE the held text is
    written, so the text says the truth (Koinos U2a)."""
    blocks = [b for b in msg.get("content", []) if b.get("type") == "tool_use"]
    return not any(secret_shape(canon.dumps(b.get("input"))) for b in blocks)


def stash_turn(stash: Stash, conv: str, model: str, out: Outcome, msg: dict, thinking: bool, secret_shape) -> bool:
    """Keep a held turn's calls for replay (T1). Not when any input has a secret shape (U2). True when stashed."""
    blocks = [b for b in msg.get("content", []) if b.get("type") == "tool_use"]
    if not keepable(msg, secret_shape):
        return False
    stash.put(conv, Stashed(conv, model, out.asks, blocks, out.held_text, thinking))
    return True


def replay_due(stash: Stash, asks: Asks, conv: str, model: str, route: str, history: list, now: float):
    """The stashed turn to replay for this request, or None (U1, U4, U5). Spends nothing; the caller re-decides (U3)
    and then spends."""
    if route != "/v1/messages":
        return None
    s = stash.peek(conv)
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
    states = [asks.status(a, now) for a in s.asks]
    if any(st in ("no", "expired", "unknown", "revoked", "spent") for st in states):
        stash.drop(conv)                                  # zeroised on no, expiry and spend (U2)
        return None
    if not all(st == "yes" for st in states):
        return None
    return s
