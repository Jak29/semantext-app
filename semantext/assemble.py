"""One assembler for an Anthropic Messages reply, streamed or not (PROXY-DESIGN r4: section 4, T10, D3, D4, T6).

Whatever arrives is built into ONE message object by this assembler, and the proxy decides on that object; a stream
and a JSON body differ only in framing. While a stream arrives, blocks before the first `tool_use` may be forwarded
live (Assembler.live); from the first `tool_use` on, every block is held back until the turn's end (D3).

Refused (Refused, with a rule id and a reason; no ask is ever made from one, T6):

  - an event, block or delta type not in the known tables, unless the space lists it as text-like (D4);
  - `server_tool_use`, a `*_tool_result` or `mcp_tool_use` block: the request gate should have stopped the work that
    makes one, so one arriving is a breach (X-REQ);
  - an ambiguous shape (T10): a `tool_use` inside `message_start`, a `content_block_start` whose `tool_use` already
    carries a non-empty input, a delta or stop for a block not open, a block index that is not the next one, a delta
    of the wrong type for its block, an event before `message_start` or after `message_stop`, a second
    `message_start`;
  - a `tool_use` input that is not one strict JSON value (canon.loads), or over the caps;
  - a stream that ends before `message_stop` (cut), or an `error` event (the client gets the vendor's error as sent).

Caps (D14): at most BLOCK_CAP characters of input in one block and TURN_CAP in the whole turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import canon

BLOCK_CAP = 4 * 1024 * 1024
TURN_CAP = 16 * 1024 * 1024

EVENTS = {"message_start", "content_block_start", "content_block_delta", "content_block_stop", "message_delta",
          "message_stop", "ping", "error"}
# Block types the proxy reads, and the delta types each may receive. Sources: PROXY-DESIGN r4 section 1 (streaming
# page; vision page and U7; claude-api skill for redacted_thinking, fallback and compaction).
BLOCKS = {
    "text": {"text_delta"},
    "thinking": {"thinking_delta", "signature_delta"},
    "redacted_thinking": set(),
    "fallback": set(),
    "compaction": set(),
    "tool_use": {"input_json_delta"},
}
SERVER_BLOCKS = ("server_tool_use", "mcp_tool_use", "mcp_tool_result")   # and every type ending "_tool_result"


class Refused(Exception):
    """The turn is refused: no ask, an error to the client (T6). `rule` is the kit's rule id."""

    def __init__(self, rule: str, reason: str):
        super().__init__(f"{rule}: {reason}")
        self.rule, self.reason = rule, reason


class VendorError(Exception):
    """The upstream sent an `error` event: it goes to the client as sent."""

    def __init__(self, data: dict):
        super().__init__("the upstream sent an error")
        self.data = data


def _call_id(cb: dict) -> None:
    """A call's id: present and text, in both framings (Koinos K1): the client pairs its result to the call by it."""
    i = cb.get("id")
    if not isinstance(i, str) or isinstance(i, canon.Number) or not i or len(i) > 256:
        raise Refused("X-ASM", "a tool call without an id that is text")


def _name(t) -> str:
    """A type name as it may appear in an error: capped and restricted (D7)."""
    s = "".join(c for c in str(t)[:40] if c.isalnum() or c in "_-.")
    return s or "?"


@dataclass
class Block:
    index: int
    kind: str
    start: dict
    deltas: list = field(default_factory=list)
    stopped: bool = False
    text: str = ""          # a tool_use's accumulated partial_json
    input: object = None    # a tool_use's input, read strictly once the block stops

    def value(self) -> dict:
        """The block as a whole, as a non-streamed reply would give it."""
        b = dict(self.start)
        if self.kind == "tool_use":
            b["input"] = self.input
        elif self.kind == "text":
            b["text"] = b.get("text", "") + "".join(d.get("text", "") for d in self.deltas)
        elif self.kind == "thinking":
            b["thinking"] = b.get("thinking", "") + "".join(d.get("thinking", "") for d in self.deltas
                                                            if d.get("type") == "thinking_delta")
            sigs = [d["signature"] for d in self.deltas if d.get("type") == "signature_delta"]
            if sigs:
                b["signature"] = sigs[-1]
        return b


class Assembler:
    def __init__(self, text_like=()):
        self.text_like = set(text_like)
        self.started = self.stopped = False
        self.message: dict = {}
        self.blocks: list[Block] = []
        self.delta: dict = {}
        self.first_tool: int | None = None
        self.size = 0

    # ---- streamed ----
    def event(self, name: str, data_text: str) -> list[tuple[str, dict]]:
        """Read one SSE event. Returns the events that may go to the client NOW (blocks before the first tool_use and
        pings), re-serialised by the caller; everything else waits for finish()."""
        try:
            data = canon.loads(data_text)
        except canon.NotCanonical as e:
            raise Refused("X-ASM", f"an event that is not strict JSON ({e})") from None
        if not isinstance(data, dict) or data.get("type") != name:
            raise Refused("X-ASM", "an event whose data type does not match its name")
        if name not in EVENTS:
            raise Refused("X-ASM", f"an event of a type the proxy does not know: {_name(name)}")
        if self.stopped:
            raise Refused("X-ASM", "an event after message_stop")
        if name == "error":
            raise VendorError(data)
        if name == "ping":
            return [(name, data)]
        if name == "message_start":
            if self.started:
                raise Refused("X-ASM", "a second message_start")
            msg = data.get("message")
            if not isinstance(msg, dict) or msg.get("content") not in ([], None):
                raise Refused("X-ASM", "message_start carrying content (a tool_use may hide there)")
            self.started, self.message = True, msg
            return []                                     # held until the first block is decided (D3d)
        if not self.started:
            raise Refused("X-ASM", f"{_name(name)} before message_start")
        if name == "content_block_start":
            return self._start(data)
        if name == "content_block_delta":
            return self._delta(data)
        if name == "content_block_stop":
            return self._stop(data)
        if name == "message_delta":
            d = data.get("delta")
            if not isinstance(d, dict):
                raise Refused("X-ASM", "a message_delta without a delta")
            # Only the stop fields: a delta carrying `content`, `role` or anything else would become the decided
            # message, a call the client never saw (Orithises P6). Anything else is an ambiguous shape.
            if set(d) - {"stop_reason", "stop_sequence"}:
                raise Refused("X-ASM", "a message_delta changing more than how the message stopped")
            self.delta.update(d)
            if "usage" in data:
                self.delta["usage"] = data["usage"]
            return []
        self.stopped = True                               # message_stop
        return []

    def _block(self, data) -> Block:
        i = data.get("index")
        if not isinstance(i, canon.Number) or not str(i).isdigit() or int(i) >= len(self.blocks):
            raise Refused("X-ASM", "an event for a block that is not open")
        b = self.blocks[int(i)]
        if b.stopped:
            raise Refused("X-ASM", "an event for a block already stopped")
        return b

    def _start(self, data) -> list:
        i, cb = data.get("index"), data.get("content_block")
        if not isinstance(i, canon.Number) or str(i) != str(len(self.blocks)):
            raise Refused("X-ASM", "a block index that is not the next one")
        if self.blocks and not self.blocks[-1].stopped:
            raise Refused("X-ASM", "a block started before the last one stopped")
        if not isinstance(cb, dict):
            raise Refused("X-ASM", "a content_block_start without a block")
        kind = cb.get("type")
        self._known(kind)
        if kind == "tool_use":
            if cb.get("input") not in ({}, None):
                raise Refused("X-ASM", "a tool_use that starts with an input already in it")
            _call_id(cb)                                                                 # Koinos K1
            if any(b.kind == "tool_use" and b.start.get("id") == cb.get("id") for b in self.blocks):
                raise Refused("X-ASM", "two tool calls with one id")                      # Orithises P10
            if self.first_tool is None:
                self.first_tool = len(self.blocks)
        self.blocks.append(Block(len(self.blocks), kind, cb))
        return self._live("content_block_start", data)

    def _known(self, kind):
        if isinstance(kind, str) and (kind in SERVER_BLOCKS or kind.endswith("_tool_result")):
            raise Refused("X-REQ", f"a {_name(kind)} block: vendor-side work the request gate should have stopped")
        if kind not in BLOCKS and kind not in self.text_like:
            raise Refused("X-ASM", f"a block of a type the proxy does not know: {_name(kind)}")

    def _delta(self, data) -> list:
        b = self._block(data)
        d = data.get("delta")
        if not isinstance(d, dict):
            raise Refused("X-ASM", "a content_block_delta without a delta")
        allowed = BLOCKS.get(b.kind, {"text_delta"} if b.kind in self.text_like else set())
        if d.get("type") not in allowed:
            raise Refused("X-ASM", f"a {_name(d.get('type'))} delta on a {_name(b.kind)} block")
        if b.kind == "tool_use":
            part = d.get("partial_json")
            if not isinstance(part, str):
                raise Refused("X-ASM", "an input_json_delta without partial_json")
            b.text += part
            self.size += len(part)
            if len(b.text) > BLOCK_CAP:
                raise Refused("X-CAP", f"a tool input over {BLOCK_CAP} characters")
            if self.size > TURN_CAP:
                raise Refused("X-CAP", f"a turn over {TURN_CAP} characters of input")
        b.deltas.append(d)
        return self._live("content_block_delta", data)

    def _stop(self, data) -> list:
        b = self._block(data)
        b.stopped = True
        if b.kind == "tool_use":
            try:
                b.input = canon.loads(b.text) if b.text else {}
            except canon.NotCanonical as e:
                raise Refused("X-ASM", f"a tool input that is not one strict JSON value ({e})") from None
            if not isinstance(b.input, dict):
                raise Refused("X-ASM", "a tool input that is not an object")
        return self._live("content_block_stop", data)

    def _live(self, name, data) -> list:
        i = int(data["index"])
        if self.first_tool is None or i < self.first_tool:
            return [(name, data)]
        return []

    def finish(self, ended_cleanly: bool = True) -> dict:
        """The whole message, once message_stop has arrived. A stream that ended without it is refused (cut)."""
        if not ended_cleanly or not self.stopped:
            raise Refused("X-ASM", "the stream ended before message_stop")
        if any(not b.stopped for b in self.blocks):
            raise Refused("X-ASM", "a block never stopped")
        msg = dict(self.message)
        msg["content"] = [b.value() for b in self.blocks]
        for k, v in self.delta.items():
            msg[k] = v
        return msg

    # ---- not streamed ----
    def body(self, text: str) -> dict:
        """A whole JSON reply, read and checked as a stream's blocks would be (D2)."""
        try:
            msg = canon.loads(text)
        except canon.NotCanonical as e:
            raise Refused("X-ASM", f"a reply that is not strict JSON ({e})") from None
        if not isinstance(msg, dict):
            raise Refused("X-ASM", "a reply that is not an object")
        if msg.get("type") == "error":
            raise VendorError(msg)
        content = msg.get("content")
        if msg.get("type") != "message" or not isinstance(content, list):
            raise Refused("X-ASM", "a reply that is not a message")
        size, ids = 0, set()
        for n, cb in enumerate(content):
            if not isinstance(cb, dict):
                raise Refused("X-ASM", "a content item that is not a block")
            self._known(cb.get("type"))
            if cb.get("type") == "tool_use":
                _call_id(cb)                                                              # K1: as when streamed
                if cb.get("id") in ids:
                    raise Refused("X-ASM", "two tool calls with one id")
                ids.add(cb.get("id"))
                if not isinstance(cb.get("input"), dict):
                    raise Refused("X-ASM", "a tool input that is not an object")
                one = len(canon.dumps(cb["input"]))
                if one > BLOCK_CAP:                                                       # K2: as when streamed
                    raise Refused("X-CAP", f"a tool input over {BLOCK_CAP} characters")
                size += one
                if size > TURN_CAP:
                    raise Refused("X-CAP", f"a turn over {TURN_CAP} characters of input")
                if self.first_tool is None:
                    self.first_tool = n
        return msg
