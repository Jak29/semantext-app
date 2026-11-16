"""The Semantext proxy, v0: Anthropic Messages, on loopback (PROXY-DESIGN r4).

    semantext proxy serve --space FOLDER [--port N]      (the person's own act at their console; see proxycmd.py)

A client points its base URL at http://127.0.0.1:N and names its agent in the header `x-semantext-agent`. Each request:

  1. the listener's rules (section 2, D8): Host is 127.0.0.1:N exactly, no Origin, JSON only, one Content-Length and
     no Transfer-Encoding, no Expect, a body under 32 MiB read within 30 s, the exact paths, at most 16 connections;
  2. the body read strictly (canon.loads), the agent named (an absent or unknown claim is refused: X-ID), the space
     loaded whole with its digest checked against the last one the person set (A1);
  3. the request gate (gate_request);
  4. a replay, when a held turn of this conversation has every ask answered yes (decide.replay_due), decided again
     (U3), recorded, and answered by the proxy with no upstream request;
  5. otherwise the card appended at the end of `system`, the headers out by family, the credential only to the model
     block's host (and never to a loopback block), the upstream reached at an address checked after resolution;
  6. the reply assembled (assemble), decided (decide), recorded before anything after the first tool_use is emitted
     (T8), and emitted: the blocks before the first tool_use stream live; the rest at the turn's end, renumbered.

Nothing here writes a block, answers an ask, or reads the person's words as an answer (U6).
"""
from __future__ import annotations

import hashlib
import hmac
import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import blocks, canon, decide, gate_request, sse
from .assemble import Assembler, Refused, VendorError
from .inbox import SECRET
from .proxy_record import Record, RecordFailed, safe, undeclared

MAX_BODY = 32 * 1024 * 1024
BODY_DEADLINE_S = 30
MAX_CONNECTIONS = 16           # connections at once, counted at accept (Orithises P7)
HEADER_DEADLINE_S = 10         # the request line and headers must arrive within this (P7)
MAX_HEADER_BLOCK = 32 * 1024   # the whole header block, names and values (PROXY-DESIGN section 2; Koinos R1)
RETRY_AFTER = re.compile(r"\d{1,6}(\.\d{1,3})?")   # seconds, as the vendor sends them; anything else is not passed
CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")   # any control character but the tab (Koinos R3; KIT_SPEC: F)
IDLE_S, TURN_S = 120, 30 * 60
ROUTES = {"/v1/messages": "messages", "/v1/messages/count_tokens": "count"}
PASS_FAMILIES = ("anthropic-", "x-claude-code-")
PASS_NAMES = ("content-type", "accept")
CREDENTIAL_NAMES = ("x-api-key", "authorization")


def _error(kind: str, message: str) -> bytes:
    return json.dumps({"type": "error", "error": {"type": kind, "message": message}}).encode()


def is_global(addr: str) -> bool:
    """A vetted public-address test, after unmapping (T15): every embedded or special form is not public."""
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif (ip in ipaddress.ip_network("64:ff9b::/96") or ip.sixtofour or ip.teredo
              or int(ip) < 2 ** 32):                    # ::a.b.c.d, the old IPv4-compatible form (P14)
            return False
    return ip.is_global and not ip.is_multicast


class Upstream(http.client.HTTPSConnection):
    """An HTTPS connection to a model block's host, made to an address checked after resolution (D9, J5, T15):
    a public host must resolve to a public address, an in-house host into its declared CIDR; each address tried is
    checked, a fallback included. TLS verification is always on; no environment proxy is read."""

    def __init__(self, host, port, cidrs=()):
        super().__init__(host, port, timeout=IDLE_S, context=ssl.create_default_context())
        self.cidrs = [ipaddress.ip_network(c) for c in cidrs]

    def connect(self):
        last = None
        for fam, kind, proto, _, addr in socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM):
            ip = addr[0]
            ok = (any(ipaddress.ip_address(ip.split("%")[0]) in n for n in self.cidrs) if self.cidrs
                  else is_global(ip))
            if not ok:
                last = Refused("X-UP", "the model's host resolved to an address it may not use")
                continue
            try:
                sock = socket.create_connection((ip, self.port), timeout=IDLE_S)
            except OSError as e:
                last = e
                continue
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
            return
        raise last or Refused("X-UP", "the model's host has no address")


class Loopback(http.client.HTTPConnection):
    """A loopback model block: a literal 127.0.0.1 or ::1 only, never a name (T13)."""


def node_key(home: Path) -> bytes:
    p = home / "node.key"
    if not p.exists():
        p.write_bytes(secrets.token_bytes(32))
    return p.read_bytes()


def conversation_key(key: bytes, body: dict, session: str | None, agent: str | None = None) -> str:
    """A keyed hash of the system prefix, the first user message, the client's session header and the agent that
    named itself (J6, T11). The agent is part of it: two agents that send the same chat are two conversations, so one
    agent's kept turn is neither replayed to the other nor dropped by the other's request (found by A08). It only
    groups: two chats of one agent that start alike share it. What ties a yes to ONE chat is the history chain
    (decide.Chain), which covers the whole system, the tools and every message. The two parts it reads are taken
    without their cache markers (decide.plain_block), as the chain takes them: a client moves a marker onto the newest
    message, and a first message that carries one in one request and not in the next is still the same chat; without
    this the key changed with the marker and a yes was never found again (C6)."""
    first = next((m for m in body.get("messages", []) if isinstance(m, dict) and m.get("role") == "user"), None)
    sysp = decide.plain_system(body.get("system"))      # a string is one text block (C8), markers dropped (C7)
    sys0 = sysp[0] if isinstance(sysp, list) and sysp else sysp
    first = decide._plain(first) if first is not None else None
    data = canon.dumps([sys0 if sys0 is not None else "", first or "", session or ""]
                       + ([agent] if agent else [])).encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


# The white space before and after the slash is written so that the two runs never share one: `<\s*(/?)\s*` tried
# every split of the spaces after a "<" that opens no tag (the square of the run: 8 s for "<" and 32 KiB of spaces,
# measured, on every request that carried the message; the same in 1.7.0). The tags it finds are the same.
REMINDER_TAG = re.compile(r"<(?:\s*(/))?\s*system-reminder\b[^<>]{0,200}>", re.I)
MAX_WORDS = 64 * 1024            # the person's words kept: the first and last halves, after reminders are cut
MAX_RAW = 4 * 1024 * 1024        # text read from one message before cutting (the newest blocks first)
MAX_TURNS = 10_000               # messages looked back through for the person's words
MAX_BLOCKS = 10_000              # blocks read in one message; a message with more is not read as the person's words


def _cut_reminders(t: str) -> str:
    """t with every <system-reminder> section cut, nested ones whole, an unclosed one to the end, any case or spacing
    of the tag (Orithises, re-attack on the wiring's fixes). Linear: one pass over the tags, bounded tag length."""
    out, i, depth = [], 0, 0
    for m in REMINDER_TAG.finditer(t):
        if depth == 0:
            out.append(t[i:m.start()])
        depth = depth - 1 if m.group(1) else depth + 1
        if depth < 0:
            depth = 0                 # a stray closing tag: skip the tag itself
        i = m.end()
    if depth == 0:
        out.append(t[i:])
    return " ".join(out)


def _cut_closed_reminders(t: str) -> str:
    """_cut_reminders, but the text after a reminder tag that is never closed is KEPT (a tag the person pasted in front
    of their words must not swallow them). Only for words read to ADD holds (hold_only_words)."""
    out, i, depth, opened = [], 0, 0, 0
    for m in REMINDER_TAG.finditer(t):
        if depth == 0:
            out.append(t[i:m.start()])
            opened = m.end()
        depth = depth - 1 if m.group(1) else depth + 1
        if depth < 0:
            depth = 0
        i = m.end()
    out.append(t[i:] if depth == 0 else t[opened:])
    return " ".join(out)


# What the client itself writes around words that reach it while a tool runs. Measured on Claude Code's own requests
# (November 2026, 33 of 33 in one long session): the line "The user sent a new message while you were working:", then
# the person's words, then one paragraph on how the client surfaces them; another session's message arrives behind the
# same kind of lead. These sentences are not the person's, and they name an act ("sent", "messages the user sends"):
# read with the words, every such message held `send`, and held it again over a yes.
CLIENT_LEADS = ("The user sent a new message while you were working:",
                "Another Claude session sent a message while you were working:")
CLIENT_TAIL = ("This is how Claude Code surfaces messages the user sends mid-turn",
               "Address the message above as you continue this turn.")
MAX_CLIENT_TAIL = 400
CLIENT_TAG = re.compile(r"<(?:\s*/)?\s*cross-session-message\b[^<>]{0,300}>")   # around another session's message
_EDGE = " \t\r\n\ufeff\u200b\u200c\u200d\u2060"    # what may stand around a client's line: white space, a BOM, zero-width marks
_LEADS_N = tuple(s.casefold() for s in CLIENT_LEADS)
_TAIL_N = tuple(s.casefold() for s in CLIENT_TAIL)
# The client's own record renders words typed while a tool ran INSIDE a reminder tag (the 33 requests measured carry
# them bare). Sent that way the section would be cut whole and the words never read. So an opening tag that stands
# directly before the lead is dropped first: the section then reads as typed words, and its closing tag is a stray
# closer, which the cut skips. One run of white space after the "<", a bounded tag, a bounded gap: one pass.
TYPED_WRAP = re.compile(r"<\s*system-reminder\b[^<>]{0,200}>\s{0,8}"
                        r"(?=the user sent a new message while you were working:)", re.I)


def _unwrap_typed(t: str) -> str:
    return TYPED_WRAP.sub("\n", t) if "<" in t else t


def _cut_client_notes(t: str) -> str:
    """t without the client's own lines around words typed while a tool ran: a lead only as a whole line, the closing
    paragraph only as one line of at most MAX_CLIENT_TAIL characters that begins and ends as the client writes it (both
    in any case, with white space, a byte-order mark or zero-width marks around them), and the tag around another
    session's message (its name holds the word "message", which the reader takes for a send). The words between them
    stay as they are. Only for text read to ADD holds (hold_only_words). Limit: another client's wording, or a later
    wording of this one, is not known here and is read with the words (it can cost an ask)."""
    low = t.casefold()
    if _TAIL_N[0] not in low and "cross-session-message" not in t and not any(lead in low for lead in _LEADS_N):
        return t
    keep = []
    for line in t.split("\n"):
        s = line.strip(_EDGE).casefold()
        tail = len(s) <= MAX_CLIENT_TAIL and s.startswith(_TAIL_N[0]) and s.endswith(_TAIL_N[1])
        if not (tail or s in _LEADS_N):
            keep.append(line)
    return CLIENT_TAG.sub(" ", "\n".join(keep))


MAX_HOLD_ONLY = 16               # texts read for holds only, of each of the two kinds (hold_only_words)
MAX_HOLD_SCAN = 2000             # user messages looked back through for them
MAX_TYPED_TAIL = 256             # of a message with more than MAX_BLOCKS blocks: the last blocks looked at, for typed words


def _is_typed(t: str) -> bool:
    """Whether a text block is what the person typed while a tool ran: it BEGINS with the client's lead for that
    (measured: 33 of 33 such blocks), in any case, after white space, a byte-order mark or zero-width marks, and after
    any closed reminder section the client put at the block's head."""
    head = t[:400].lstrip(_EDGE)
    if head.startswith("<"):                          # a tag first: cut the closed reminders, then look
        head = _cut_closed_reminders(t if len(t) <= MAX_RAW else t[:MAX_RAW]).lstrip(_EDGE)[:400]
    return head.casefold().startswith(_LEADS_N[0])


def _beside_a_result(m) -> tuple:
    """(typed, other): the text of a user message that carries a tool result, for the hold-only reading. Each text
    block is taken on its own. A block that begins with the client's lead is what the person typed: every such block is
    read (the newest MAX_HOLD_ONLY of the message, each kept to MAX_WORDS), whatever stands before or after it in the
    message: a note in an earlier block made the whole message other text, and megabytes in a later block hid it. The
    remaining blocks are the other text, read as _raw reads a message: the newest first, up to MAX_RAW. A message with
    more than MAX_BLOCKS blocks is looked at only in its last MAX_TYPED_TAIL blocks, and only for typed words."""
    c = m.get("content") if isinstance(m, dict) else None
    if not isinstance(c, list):
        return "", ""
    many = len(c) > MAX_BLOCKS
    typed, rest = [], []
    for b in (c[-MAX_TYPED_TAIL:] if many else c):
        if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
            t = _unwrap_typed(b["text"])
            (typed if _is_typed(t) else rest).append(t)
    half = MAX_RAW // 2
    mine = "\n".join(
        _keep(_cut_client_notes(_cut_closed_reminders(t if len(t) <= MAX_RAW else t[:half] + "\n" + t[-half:])))
        for t in reversed(typed[-MAX_HOLD_ONLY:]))    # the newest block first, as the messages are
    if many:
        return mine, ""
    parts, size = [], 0
    for t in reversed(rest):                          # the other blocks: the newest first, up to MAX_RAW
        parts.append(t)
        size += len(t)
        if size >= MAX_RAW:
            break
    return mine, _keep(_cut_client_notes(_cut_closed_reminders("\n".join(reversed(parts)))))


def hold_only_words(body: dict) -> list:
    """Text read ONLY to add holds, never as a go, a yes or an answer: [(text, index of its message)].
    The person's words (person_words) skip a user message that carries a tool result, and cut a reminder tag that is
    never closed to the end; but a client sends words typed while a tool runs beside its result, and a person may paste
    such a tag before "do not delete anything". So: the text blocks of each user message that carries a tool result,
    after the person's own words, and the person's own message read with an unclosed tag kept. Text there may be the
    client's own or another session's (a tool's output is never read): it can cost a hold, the cheap direction; nothing
    here releases. The client's own lines around typed words are cut first (_cut_client_notes).

    ORDER AND CAPS. What the person typed comes FIRST: each text block that begins with the client's lead for words
    typed while a tool ran (_is_typed; measured: 33 of 33 blocks), taken block by block (_beside_a_result), and the
    person's own message read with an unclosed tag kept; newest first, up to MAX_HOLD_ONLY messages. Then the other
    texts (the client's notes, another session's message), newest first, each distinct text once, up to MAX_HOLD_ONLY.
    The decision reads them joined in this order and the reader reads the first 20,000 characters or 400 clauses, so a
    note or another session's message, however long or however many, does not push the typed words out of the reading
    (sixteen notes after a "don't push yet" did; so did a note in the same message, and 4 MiB in a later block of it).
    Limits: only that one client's lead is known, and only at the start of a block, so from another client, or where
    something stands before the lead in its block, the words are of the second kind, where a newer long text can crowd
    an older one out; of the person's own typing, the newest MAX_HOLD_ONLY typed messages are read, up to the reader's
    clip, and of one block over MAX_WORDS its two ends; a message with more than MAX_BLOCKS blocks is looked at only in
    its last MAX_TYPED_TAIL blocks and only for typed words; words inside a closed reminder pair are cut with it."""
    raw = body.get("messages") if isinstance(body, dict) else None
    msgs = raw if isinstance(raw, list) else []
    lo = max(0, len(msgs) - MAX_TURNS)
    typed, other, seen, scanned = [], [], set(), 0
    for i in range(len(msgs) - 1, lo - 1, -1):
        m = msgs[i]
        if not (isinstance(m, dict) and m.get("role") == "user"):
            continue
        scanned += 1
        if scanned > MAX_HOLD_SCAN or (len(typed) >= MAX_HOLD_ONLY and len(other) >= MAX_HOLD_ONLY):
            break
        if _carries_tool_result(m):
            mine, rest = _beside_a_result(m)
            if mine.strip() and len(typed) < MAX_HOLD_ONLY:
                typed.append((mine, i))               # what the person typed while a tool ran
            if rest.strip() and rest not in seen and len(other) < MAX_HOLD_ONLY:
                seen.add(rest)
                other.append((rest, i))
            continue
        r = _raw(m)                                   # the person's own message: only what the cuts below add
        own = _keep(_cut_reminders(r))                # (an unclosed tag kept; typed words the client wrapped in one)
        text = _keep(_cut_client_notes(_cut_closed_reminders(_unwrap_typed(r))))
        if text.strip() and text != own and len(typed) < MAX_HOLD_ONLY:
            typed.append((text, i))
        if own.strip():
            break                                     # older messages are not newer than the person's own words
    return typed + other


def _keep(t: str) -> str:
    """The person's words, cut to MAX_WORDS AFTER reminders are cut, keeping both ends (a hold can be first or last)."""
    if len(t) <= MAX_WORDS:
        return t
    h = MAX_WORDS // 2
    return t[:h] + "\n" + t[-h:]


def _raw(m) -> str:
    c = m.get("content") if isinstance(m, dict) else None
    if isinstance(c, str):
        return c[-MAX_RAW:] if len(c) > MAX_RAW else c
    if isinstance(c, list):
        if len(c) > MAX_BLOCKS:
            return ""
        parts, size = [], 0
        for b in reversed(c):                         # newest blocks first, up to MAX_RAW
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
                size += len(b["text"])
                if size >= MAX_RAW:
                    break
        return "\n".join(reversed(parts))
    return ""


def _texts(m) -> str:
    """The text blocks of one message, joined, with the harness's own <system-reminder> sections cut out, then kept
    to MAX_WORDS; tool results and every other block left out."""
    return _keep(_cut_reminders(_raw(m)))


def _carries_tool_result(m) -> bool:
    c = m.get("content")
    if isinstance(c, list) and len(c) > MAX_BLOCKS:
        return True                  # too many blocks to read: not taken as the person's words
    return isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def person_words(body: dict) -> tuple:
    """The person's latest words in a request (the newest user message with text of its own, never a tool result) and
    the agent's text just before them (the offer a bare yes answers). (None, None) when there are none within the last
    MAX_TURNS messages. The decision reads them only to ADD holds (reading.held_by_words), so text that is not really
    the person's can cost an ask, never release a call."""
    return person_words_at(body)[:2]


def person_words_at(body: dict) -> tuple:
    """person_words and the index of the message the words are in (None with no words): the decision holds a call
    against an earlier yes only for words written after the ask was made (decide.decide, `words_at`)."""
    raw = body.get("messages") if isinstance(body, dict) else None
    msgs = raw if isinstance(raw, list) else []
    lo = max(0, len(msgs) - MAX_TURNS)
    for i in range(len(msgs) - 1, lo - 1, -1):
        m = msgs[i]
        # A user turn that carries a tool result is the harness's, not the person's: text beside a result (a hook's
        # note, a reminder) is not their words (Koinos, attack on the reader's wiring).
        if isinstance(m, dict) and m.get("role") == "user" and not _carries_tool_result(m):
            words = _texts(m)
            if words.strip():
                prev = next((msgs[j] for j in range(i - 1, lo - 1, -1)
                             if isinstance(msgs[j], dict) and msgs[j].get("role") == "assistant"), None)
                return words, (_texts(prev) or None) if prev else None, i
    return None, None, None

SCAN_WINDOW, SCAN_OVERLAP = 96 * 1024, 20 * 1024


def _bounded(pattern: str) -> re.Pattern:
    """inbox.SECRET with its open middles bounded, for the windowed scan only (Orithises F1, Koinos): a match must be
    shorter than the overlap, or a key crossing a window's edge lies in no window. Each part that must be reached whole
    is capped (a URL's user and password at 4 KiB each, a JWT's first two segments at 8 KiB each, a PEM label at 128,
    the spaces around "password =" or "password is" at 256), so the longest match is about 16.5 KiB, under the 20 KiB
    overlap. Every replacement must apply, or the proxy does not start. Limit, stated (R14): the JWT arm of this pattern
    begins at the start of its run of token characters (inbox.SECRET, R10), so a JWT glued after a run that opens with
    "eyJ" and has its first dot more than 8 KiB on is not matched by it; _secret finds that JWT with _glued_jwt."""
    swaps = [(r"://[^\s/:@]+:[^\s/@]+@", r"://[^\s/:@]{1,4096}:[^\s/@]{1,4096}@"),
             (r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.", r"eyJ[A-Za-z0-9_-]{8,8192}\.[A-Za-z0-9_-]{8,8192}\."),
             (r"-----BEGIN [A-Z0-9 ]+-----", r"-----BEGIN [A-Z0-9 ]{1,128}-----"),
             (r"\s*[=:]\s*", r"\s{0,256}[=:]\s{0,256}"),
             (r"\s+(is|was)\s+", r"\s{1,256}(is|was)\s{1,256}")]
    for old, new in swaps:
        if pattern.count(old) != 1:
            raise RuntimeError(f"the key-shape pattern changed; bound it again for the windowed scan: {old}")
        pattern = pattern.replace(old, new)
    return re.compile(pattern, re.I)


SECRET_BOUNDED = _bounded(SECRET.pattern)


# A JSON web token for the windowed scan, found from its DOT (R14). inbox.SECRET's JWT arm begins at the start of its run
# of token characters (R10, to be linear), so inside SECRET_BOUNDED a run that begins with "eyJ" and has its dot more
# than 8 KiB on set the first segment's length from that first "eyJ", and a JWT glued after the run was missed at every
# offset (99f9116 found it from its own "eyJ"). Here each run of 11 or more token characters that ends in a dot is taken
# once (a run begins after a character that is not one, so the pass is linear), the 8,195 characters before the dot are
# searched for an "eyJ" that leaves a first segment of 8 to 8,192 characters (the longest 99f9116 allowed), and the two
# segments after the dot are tried once. That is the bound of 99f9116 exactly, for every "eyJ" at once.
_TOKEN = r"[A-Za-z0-9_-]"
_JWT_RUN = re.compile(r"(?<!" + _TOKEN + r")" + _TOKEN + r"{11,}\.", re.I)
_JWT_EYJ = re.compile(r"eyJ", re.I)
_JWT_REST = re.compile(_TOKEN + r"{8,8192}\." + _TOKEN + r"{8,}", re.I)


def _glued_jwt(window: str) -> bool:
    for m in _JWT_RUN.finditer(window):
        dot = m.end() - 1
        if _JWT_EYJ.search(window, max(m.start(), dot - 8195), dot - 8) and _JWT_REST.match(window, m.end()):
            return True
    return False


def _secret(text: str) -> bool:
    """The key-shape check over the whole text (Koinos's margin after X1: one search holds the GIL, and a 4 MiB held
    input once stopped every thread for about 2 s). Up to one window it is inbox.SECRET itself. Longer, it runs
    SECRET_BOUNDED, and the JWT pass _glued_jwt, in overlapping windows, giving the other threads the GIL between them:
    every match of the bounded pattern is shorter than the overlap, so a key is found at any offset, across any edge.
    Stated limit (PROXY-DESIGN 5d): in an input longer than one window, a part longer than its bound (a URL user or
    password over 4 KiB, a JWT segment over 8 KiB, more than 256 spaces around "password =") is not found; none is a
    usable credential. The JWT's bound is exactly 99f9116's: its first segment, which is the token characters between
    its own "eyJ" and its first dot, is at most 8,192 long, and so is the second. Characters glued before the "eyJ" do
    not count (R14), however many: a JWT after 100,000 token characters is found. No wider bound remains for the JWT;
    SECRET_BOUNDED's own JWT arm is kept for the single search's sake and is subsumed here."""
    if len(text) <= SCAN_WINDOW:
        return bool(SECRET.search(text))
    for start in range(0, len(text), SCAN_WINDOW - SCAN_OVERLAP):
        if SECRET_BOUNDED.search(text, start, start + SCAN_WINDOW) or _glued_jwt(text[start:start + SCAN_WINDOW]):
            return True
        time.sleep(0)                      # give the other threads the GIL between windows
    return False


def _numbers(value):
    """A value the proxy built (an index it numbered, a count) made canonical: its own whole numbers as Number text.
    Values read from upstream are Number already and pass through unchanged."""
    if isinstance(value, bool) or value is None or isinstance(value, canon.Number):
        return value
    if isinstance(value, int):
        return canon.Number(str(value))
    if isinstance(value, list):
        return [_numbers(v) for v in value]
    if isinstance(value, dict):
        return {k: _numbers(v) for k, v in value.items()}
    return value


class Proxy:
    def __init__(self, space_dir: Path, home: Path, card: str, expected_digest: str | None = None):
        self.space_dir, self.home, self.card = Path(space_dir), Path(home), card
        # P8: with no digest given, the space as it is at start is pinned; a change then refuses until the person
        # starts the proxy again (their own act), never passes unseen.
        self.expected = expected_digest or blocks.load(self.space_dir).digest
        self.key = node_key(self.home)
        self.record = Record(self.home / "proxy.jsonl")
        self.record.verify()                  # R4: a broken chain is found at start; every request is then refused
        self.asks = decide.Asks(self.home / "asks.json", run=secrets.token_hex(8), key=self.key, record=self.record)
        self.stash = decide.Stash()
        self.asks.on_closed = self.stash.drop_ask        # U2b: a no or a revoke drops its kept turn at the answer
        self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def space(self):
        s = blocks.load(self.space_dir)
        if self.expected and s.digest != self.expected:
            raise Refused("X-DIGEST", "the space's blocks changed since the person last set them")
        return s


class Handler(BaseHTTPRequestHandler):
    proxy: Proxy = None
    port: int = 0
    protocol_version = "HTTP/1.1"
    timeout = HEADER_DEADLINE_S        # a connection that sends nothing is closed (P7); the body has its own deadline

    def log_message(self, *a):          # nothing about a request is printed: the record is the one account
        return

    # R1 (Orithises's recheck of the proxy server): `timeout` bounds each read, so a byte every few seconds would keep a slot for
    # ever. A total deadline from the connection's start closes it unless the request line and headers are in by then;
    # and each connection carries one request only, so the deadline never has to be re-armed.
    # One watchdog for the whole server (Server._watchdog), not a thread per connection: each connection is entered
    # with its deadline and left once its headers are in.
    def setup(self):
        super().setup()
        self.server.waiting_headers[self] = time.monotonic() + HEADER_DEADLINE_S

    def parse_request(self):
        ok = super().parse_request()
        self.server.waiting_headers.pop(self, None)
        self.close_connection = True
        return ok

    def finish(self):
        self.server.waiting_headers.pop(self, None)
        super().finish()

    # ---- replies ----
    def _send(self, status: int, body: bytes, ctype="application/json", extra=None):
        if getattr(self, "_streaming", False):        # headers already sent: an error goes out as an SSE event
            try:
                message = json.loads(body).get("error", {}).get("message", "semantext refused the turn")
            except ValueError:
                message = "semantext refused the turn"
            self._event("error", {"type": "error", "error": {"type": "api_error", "message": message}})
            return
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # Each connection carries one request (see the deadline above): say so, or a client that keeps the connection
        # for its next request meets a closed socket (Koinos, 1.7.0 release attack: 21 of 600 SDK requests failed).
        self.send_header("Connection", "close")
        self.close_connection = True
        for name, value in (extra or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _refuse(self, e: Refused, status=400):
        # P5: a request refused before its body is read must not leave that body to be read as the next request.
        self.close_connection = True
        try:
            self.proxy.record.append("refused", {"rule": e.rule})    # the rule only: a reason may carry a client's name (P4)
        except RecordFailed:
            pass
        self._send(status, _error("invalid_request_error", f"semantext refused ({e.rule}): {e.reason}"))

    # ---- the listener (section 2, D8, T13) ----
    def _listener(self, method: str) -> str:
        # Koinos R1 and R3: the header block is bounded before any value is read, and no value carries a control
        # character (a NUL or a bare CR reached the upstream in a forwarded header). The bound also bounds what the
        # key-shape check is given (X1).
        size = 0
        for name, value in self.headers.items():
            size += len(name) + len(value) + 4
            if CONTROL.search(value):
                raise Refused("X-ROUTE", "a header value carries a control character")
        if size > MAX_HEADER_BLOCK:
            raise Refused("X-ROUTE", f"the headers are over {MAX_HEADER_BLOCK} bytes")
        hosts = self.headers.get_all("Host") or []
        if hosts != [f"127.0.0.1:{self.port}"]:
            raise Refused("X-ROUTE", "the Host must be 127.0.0.1 and this port")
        if self.headers.get("Origin") is not None:
            raise Refused("X-ROUTE", "a request from a web page (it carries an Origin)")
        if self.headers.get("Transfer-Encoding") is not None or self.headers.get("Expect") is not None:
            raise Refused("X-ROUTE", "only a plain body with one Content-Length")
        if self.headers.get("Content-Encoding") is not None:
            raise Refused("X-ROUTE", "a compressed request body cannot be judged")
        # The path as sent: http.server folds a leading // into / before we see self.path (P13).
        sent = self.requestline.split(" ")
        if len(sent) != 3 or sent[1] != self.path:
            raise Refused("X-ROUTE", "no such route")
        path, _, query = self.path.partition("?")
        if method == "GET":
            if path != "/v1/models" or (query and not (query.startswith("limit=") and query[6:].isdigit())):
                raise Refused("X-ROUTE", "no such route")
            return "models"
        if path not in ROUTES or query not in ("", "beta=true"):
            raise Refused("X-ROUTE", "no such route")
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise Refused("X-ROUTE", "the body must be JSON")
        return ROUTES[path]

    def _body(self) -> dict:
        lengths = self.headers.get_all("Content-Length") or []
        if len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > MAX_BODY:
            raise Refused("X-BODY", f"one Content-Length, at most {MAX_BODY} bytes")
        n, data = int(lengths[0]), b""
        self.connection.settimeout(BODY_DEADLINE_S)
        deadline = time.monotonic() + BODY_DEADLINE_S
        while len(data) < n:
            if time.monotonic() > deadline:
                raise Refused("X-BODY", "the body did not arrive in time")
            piece = self.rfile.read(min(65536, n - len(data)))
            if not piece:
                raise Refused("X-BODY", "the body ended early")
            data += piece
        try:
            body = canon.loads(data)
        except canon.NotCanonical as e:
            raise Refused("X-BODY", f"the body is not one strict JSON value ({e})") from None
        if not isinstance(body, dict):
            raise Refused("X-BODY", "the body is not an object")
        return body

    # ---- methods ----
    def do_GET(self):
        self._serve("GET")

    def do_POST(self):
        self._serve("POST")

    def do_HEAD(self):
        self._refuse(Refused("X-ROUTE", "no such method"), 405)

    do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_HEAD

    def _serve(self, method):
        if not self.proxy.slots.acquire(blocking=False):
            return self._refuse(Refused("X-CAP", f"more than {MAX_CONNECTIONS} requests at once"), 429)
        try:
            route = self._listener(method)
            space = self.proxy.space()
            claims = self.headers.get_all("x-semantext-agent") or []
            if len(claims) > 1:
                raise Refused("X-ID", "two x-semantext-agent headers: name one agent")   # T12, P13
            agent = claims[0] if claims else None
            if not agent or agent not in space.blocks or space.blocks[agent]["kind"] != "agent":
                raise Refused("X-ID", "name a configured agent in the x-semantext-agent header")
            if route == "models":
                ids = sorted(space.blocks[m]["model"] for m in space.blocks[agent].get("models", []))
                return self._send(200, json.dumps({"data": [{"type": "model", "id": i} for i in ids],
                                                   "has_more": False}).encode())
            body = self._body()
            check = gate_request.check(body, space, agent)
            model_id = next(m for m in space.blocks[agent].get("models", [])
                            if space.blocks[m]["model"] == body.get("model"))
            conv = conversation_key(self.proxy.key, body, self.headers.get("x-claude-code-session-id"), agent)
            # The history as digests: an ask is tied to the messages it was asked after, so a chat that shares the key
            # (no session header, an alike start) is still another conversation (decide.Chain, Asks.bound).
            # With no session header the chain covers the whole system and the tools too (C6): another project's system
            # block or another tools list is another chat, whatever the conversation key (system[0] and the first
            # message) says. With one (C8) the session and the history are the chat: Claude Code's tools list and
            # system change inside one session, and a yes must still find its call.
            self.chain = (decide.Chain(self.proxy.key, body.get("messages"), body.get("system"), body.get("tools"),
                                       self.headers.get("x-claude-code-session-id"))
                          if route == "messages" else None)
            self.proxy.record.append("request", {"agent": agent, "model": model_id, "route": route,
                                                 "space": space.digest, "unknown": len(check.unknown),
                                                 "vendor_recorded": len(check.recorded)})   # R2: how many, never the client's names
            if route == "messages" and self._replay(space, agent, model_id, body, conv):
                return
            self._forward(space, agent, model_id, body, conv, route)
        except Refused as e:
            self._refuse(e, 403 if e.rule in ("X-ROUTE", "X-ID") else 400)
        except RecordFailed as e:
            self._send(503, _error("api_error", f"semantext cannot write its record, so nothing passes: {e}"))
        except Exception as e:                            # T8: an exception in the decision path refuses the turn
            try:
                self.proxy.record.append("refused", {"rule": "X-EXC", "class": type(e).__name__})
            except RecordFailed:
                pass
            self._send(500, _error("api_error", f"semantext refused the turn ({type(e).__name__})"))
        finally:
            self.proxy.slots.release()

    # ---- replay (T1, U1 to U5) ----
    def _replay(self, space, agent, model_id, body, conv) -> bool:
        now = time.monotonic()
        s = decide.replay_due(self.proxy.stash, self.proxy.asks, conv, body.get("model"), self.path.partition("?")[0],
                              body.get("messages", []), now, chain=self.chain)
        if s is None:
            return False
        # Koinos U3c: a kept call whose tool this request no longer declares cannot run; no replay, and the yes stays
        # unspent (the request goes on to the model as any other).
        declared = {t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)}
        if any(c.get("name") not in declared for c in s.calls):
            return False
        msg = {"id": "msg_" + secrets.token_hex(12), "type": "message", "role": "assistant", "model": body["model"],
               "content": s.calls, "stop_reason": "tool_use", "stop_sequence": None,
               "usage": {"input_tokens": 0, "output_tokens": 0}}
        # U3: the whole decision runs again on the stashed calls, with the person's answers live: a gated call is
        # released (and its answer spent) by its yes; anything held now (a tool no longer declared, a new gate, a
        # changed space) refuses the replay. Answers the decision did not need are spent too: the turn is the unit.
        self.proxy.stash.drop(s.key)
        # The same call twice in one kept turn shares one ask, and one yes releases one call: the turn cannot be sent
        # whole. Said as it is, before the decision runs (it would open a fresh ask for the second call). The yes is
        # not spent: the call made again goes through once on it.
        acts = [(c.get("name"), canon.d_act(c.get("input"))) for c in s.calls]
        if len(set(acts)) != len(acts):
            raise Refused("X-REL", "the kept turn makes the same call twice and one yes releases one call; "
                                   "nothing was sent, and the call made again goes through once")
        words, offer = person_words(body)
        at = person_words_at(body)[2] if words else None
        out = decide.decide(space, "space", agent, model_id, msg, conv, self.proxy.asks, now, words=words, offer=offer,
                            chain=self.chain, words_at=at, hold_only=hold_only_words(body))
        if out.held and out.over_yes:
            # The person's newest message, written after the held turn, holds a call they had said yes to: their
            # newest words win. Nothing is sent on and nothing is spent; the kept turn is let go (it cannot be the
            # turn before a later message once the chat goes on), and the request goes on to the model as any other.
            # The yes stands: the same call made again goes through once when the newest words no longer hold it.
            return False
        if out.held:
            raise Refused("X-REL", "the answered call would be held now; the space or its gates changed")
        # C9 (Orithises, the left-spend window): EVERY ask of the kept turn the re-decision did not spend is spent here,
        # through Asks.spend, which takes each only while it is a live yes whose chain's last word is yes, under the lock,
        # all or none. It was spent only for the asks a fresh reading still showed as "yes": an ask revoked, spent or
        # unproved between replay_due and that reading dropped out of `left`, and the whole kept turn went out.
        left = [a for a in dict.fromkeys(s.asks) if a not in out.released]
        if left and not self.proxy.asks.spend(left, now):
            raise Refused("X-REL", "the answer was spent, revoked or expired")
        for c in s.calls:
            self.proxy.record.append("call", {"decision": "replayed", "d_rec": canon.d_rec(
                self.proxy.key, canon.d_act(c["input"]))})
        self._emit_whole(msg, body.get("stream") is True)
        return True

    # ---- forwarding ----
    def _upstream(self, block):
        u = urlsplit(block["endpoint"])
        host = (u.hostname or "").lower()
        if host in ("127.0.0.1", "::1"):
            if u.scheme != "http":
                raise Refused("X-UP", "a loopback model is reached over http")
            return Loopback(host, u.port or 80, timeout=IDLE_S), True
        if u.scheme != "https" or u.username or u.password or host != block["credential_host"].lower():
            raise Refused("X-KEY", "the model block's endpoint is not its credential host over https")
        return Upstream(host, u.port or 443, block.get("cidr", ())), False

    def _headers_out(self, loopback: bool, space) -> dict:
        extra = {n.lower() for n in space.settings.get("extra_header_names", [])}
        out = {}
        for name, value in self.headers.items():
            low = name.lower()
            credential = low in CREDENTIAL_NAMES or _secret(value)            # T2: by value as well as name
            if credential:
                if not loopback:
                    out[name] = value
                continue
            if (low.startswith(PASS_FAMILIES) or low in PASS_NAMES or low in extra) and low != "x-semantext-agent":
                out[name] = value
        out["Accept-Encoding"] = "identity"                                   # J1
        return out

    def _forward(self, space, agent, model_id, body, conv, route):
        block = space.blocks[model_id]
        out_body = dict(body)
        sysp = out_body.get("system")
        sys_list = [{"type": "text", "text": sysp}] if isinstance(sysp, str) else list(sysp or [])
        out_body["system"] = sys_list + [{"type": "text", "text": self.proxy.card}]  # at the end, never first
        conn, loopback = self._upstream(block)
        path = self.path
        conn.request("POST", path, body=canon.dumps(out_body).encode(), headers=self._headers_out(loopback, space))
        resp = conn.getresponse()
        if resp.status >= 300 and resp.status < 400:
            raise Refused("X-UP", "the model's host redirected; nothing follows a redirect")
        enc = (resp.getheader("Content-Encoding") or "identity").lower()
        if enc != "identity":
            raise Refused("X-UP", "the model's host sent a compressed reply the proxy did not ask for")
        if resp.status >= 400 or route == "count":
            data = resp.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise Refused("X-CAP", "the reply is too large")
            if resp.status >= 400:
                try:
                    shaped = json.loads(data).get("type") == "error"
                except ValueError:
                    shaped = False
                # Koinos R8: the client backs off on retry-after; it is passed when it is a plain number of seconds.
                wait = (resp.getheader("retry-after") or "").strip()
                extra = {"retry-after": wait} if RETRY_AFTER.fullmatch(wait) else None
                return self._send(resp.status, data if shaped else _error("api_error", "the model's host failed"),
                                  extra=extra)
            try:                                         # P11: the count only, never the reply as sent
                n = canon.loads(data).get("input_tokens")
            except (canon.NotCanonical, AttributeError):
                n = None
            if not isinstance(n, canon.Number) or not str(n).isdigit():
                raise Refused("X-UP", "the token count reply was not a count")
            return self._send(200, canon.dumps({"input_tokens": n}).encode())
        ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        stream = body.get("stream") is True and ctype == "text/event-stream"
        if stream:
            self._stream(space, agent, model_id, body, conv, resp)
        else:
            a = Assembler(space.settings.get("text_like_types", []))
            data = resp.read(MAX_BODY + 1)
            if len(data) > MAX_BODY:
                raise Refused("X-CAP", "the reply is too large")
            msg = a.body(data.decode("utf-8"))
            self._decide_and_emit(space, agent, model_id, body, conv, msg, stream=False, live=False)

    def _stream(self, space, agent, model_id, body, conv, resp):
        reader, a = sse.Reader(), Assembler(space.settings.get("text_like_types", []))
        started = False
        start_at = last = time.monotonic()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self._streaming = self.close_connection = True
        try:
            while True:
                if time.monotonic() - start_at > TURN_S:
                    raise Refused("X-CAP", "the turn ran past its time")
                piece = resp.read1(65536) if hasattr(resp, "read1") else resp.read(65536)
                now = time.monotonic()
                if not piece:
                    break
                if now - last > IDLE_S:
                    raise Refused("X-CAP", "the model's host went quiet")
                last = now
                for name, text in reader.feed(piece):
                    for ev_name, data in a.event(name, text):
                        if not started:
                            self._event("message_start", {"type": "message_start", "message": a.message})
                            started = True
                        self._event(ev_name, data)
            msg = a.finish(reader.end())
        except VendorError as e:
            self._event("error", e.data)
            return
        except (Refused, sse.TooBig, UnicodeDecodeError, OSError) as e:      # OSError: a socket timeout, a cut
            rule = getattr(e, "rule", "X-ASM")
            try:
                self.proxy.record.append("refused", {"rule": rule})
            except RecordFailed:
                pass
            # K5: the client is told why, the type named (assemble._name: capped, restricted); the record holds the rule
            reason = getattr(e, "reason", None) or type(e).__name__
            self._event("error", {"type": "error", "error": {"type": "invalid_request_error",
                                                            "message": f"semantext refused the turn ({rule}): {reason}"}})
            return
        if not started:
            self._event("message_start", {"type": "message_start", "message": a.message})
        self._decide_and_emit(space, agent, model_id, body, conv, msg, stream=True, live=True,
                              emitted=a.first_tool if a.first_tool is not None else len(msg["content"]))

    def _decide_and_emit(self, space, agent, model_id, body, conv, msg, stream, live, emitted=0):
        now = time.monotonic()
        thinking = any(b.get("type") in ("thinking", "redacted_thinking") for b in msg.get("content", []))
        kept = not thinking and decide.keepable(msg, _secret)       # known before the held text is written (U2a)
        words, offer = person_words(body)
        at = person_words_at(body)[2] if words else None
        out = decide.decide(space, "space", agent, model_id, msg, conv, self.proxy.asks, now, kept=kept, words=words,
                            offer=offer, chain=self.chain, words_at=at, hold_only=hold_only_words(body))
        for c in out.calls:                                   # T8: recorded before anything is emitted
            name = space.blocks[c.tool]["name"] if c.tool else undeclared(self.proxy.key, c.name)
            self.proxy.record.append("call", {"tool": name, "decision": "held" if out.held else "pass",
                                              "d_rec": canon.d_rec(self.proxy.key, c.d_act)})
        if out.held:
            self.proxy.record.append("held", {"asks": out.asks})
            if kept:                                          # one predicate for the words and the stash (U2a)
                decide.stash_turn(self.proxy.stash, conv, body.get("model"), out, msg, thinking, _secret,
                                chain=self.chain)
        self.proxy.record.append("turn", {"stop_reason": safe(out.stop_reason or ""), "held": out.held})
        if not stream:
            whole = dict(msg)
            whole["content"], whole["stop_reason"] = out.content, out.stop_reason
            return self._send(200, canon.dumps(_numbers(whole)).encode())
        # The blocks before the first tool_use went out live (indices 0 .. emitted-1); in both outcomes they are the
        # head of out.content, so the rest is everything after them, numbered on from there (D3a).
        for n, b in enumerate(out.content[emitted:], start=emitted):
            self._block_events(n, b)
        delta = {"type": "message_delta", "delta": {"stop_reason": out.stop_reason, "stop_sequence": None},
                 "usage": msg.get("usage", {})}
        self._event("message_delta", delta)
        self._event("message_stop", {"type": "message_stop"})

    def _emit_whole(self, msg, stream):
        if not stream:
            return self._send(200, canon.dumps(_numbers(msg)).encode())
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self._streaming = self.close_connection = True
        start = dict(msg)
        start["content"], start["stop_reason"] = [], None
        self._event("message_start", {"type": "message_start", "message": start})
        for n, b in enumerate(msg["content"]):
            self._block_events(n, b)
        self._event("message_delta", {"type": "message_delta", "delta": {"stop_reason": msg["stop_reason"],
                                                                          "stop_sequence": None},
                                      "usage": {"output_tokens": 0}})
        self._event("message_stop", {"type": "message_stop"})

    def _block_events(self, index: int, b: dict):
        t = b.get("type")
        if t == "tool_use":
            self._event("content_block_start", {"type": "content_block_start", "index": index, "content_block": {
                "type": "tool_use", "id": b["id"], "name": b["name"], "input": {}}})
            self._event("content_block_delta", {"type": "content_block_delta", "index": index, "delta": {
                "type": "input_json_delta", "partial_json": canon.dumps(b["input"])}})
        elif t == "text":
            self._event("content_block_start", {"type": "content_block_start", "index": index,
                                                "content_block": {"type": "text", "text": ""}})
            self._event("content_block_delta", {"type": "content_block_delta", "index": index,
                                                "delta": {"type": "text_delta", "text": b.get("text", "")}})
        else:                                                 # thinking and the rest: as one start, whole
            self._event("content_block_start", {"type": "content_block_start", "index": index, "content_block": b})
        self._event("content_block_stop", {"type": "content_block_stop", "index": index})

    def _event(self, name: str, data: dict):
        self.wfile.write(f"event: {name}\ndata: {canon.dumps(_numbers(data))}\n\n".encode("utf-8"))
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    """At most MAX_CONNECTIONS connections at once, counted at accept: one past it is closed unread (P7)."""
    daemon_threads = True
    # One listener per port (Koinos, attack on the serve command): with address reuse on, Windows let a second proxy
    # bind the same port and serve beside the first. Off, and exclusive where the platform offers it.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._open = threading.BoundedSemaphore(MAX_CONNECTIONS)
        self.waiting_headers = {}                    # handler -> the time its request line and headers must be in by
        self._closing = threading.Event()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def shutdown(self):
        self._closing.set()                          # the watchdog ends with its server, never outlives it
        super().shutdown()

    def _watchdog(self):
        """R1: a connection whose request line and headers are not in by its deadline is closed, however slowly they
        drip: the deadline is total, from the connection's start, where the socket timeout bounds only each read."""
        tick = 0
        while not self._closing.wait(0.25):
            now = time.monotonic()
            for handler, deadline in list(self.waiting_headers.items()):
                if now > deadline:
                    self.waiting_headers.pop(handler, None)
                    try:
                        handler.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
            tick += 1
            proxy_ = getattr(self.RequestHandlerClass, "proxy", None)
            if tick % 4 == 0 and proxy_ is not None:          # Koinos U2b: once a second, a refused turn is dropped
                try:
                    proxy_.stash.sweep(proxy_.asks, now)
                except Exception:                              # the sweep never takes the watchdog down with it
                    pass

    def process_request(self, request, client_address):
        if not self._open.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._open.release()


def serve(space_dir, home, card: str, port: int, expected_digest=None, ready=None, on_run=None):
    """Run the proxy on 127.0.0.1:port until stopped. `ready` (a threading.Event) is set once it listens; `on_run`
    is called with the run id once the proxy exists and before it listens (the command names the run with it, so the
    person's answering command answers this run's asks)."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    proxy = Proxy(space_dir, home, card, expected_digest)
    handler = type("H", (Handler,), {"proxy": proxy, "port": port})
    server = Server(("127.0.0.1", port), handler)    # raises if the port is taken: nothing is named before this
    if on_run is not None:
        on_run(proxy.asks.run)                          # only a proxy that holds its port names the run
    server.daemon_threads = True
    if ready is not None:
        ready.server = server
        ready.set()
    server.serve_forever()
