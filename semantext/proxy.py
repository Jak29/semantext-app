"""The Semantext proxy, v0: Anthropic Messages, on loopback (PROXY-DESIGN r4).

    serve(space_dir, home, card, port)       (1.7.0: a library call; no `semantext proxy serve` command yet)

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


def conversation_key(key: bytes, body: dict, session: str | None) -> str:
    """A keyed hash of the system prefix, the first user message and the client's session header (J6, T11)."""
    first = next((m for m in body.get("messages", []) if isinstance(m, dict) and m.get("role") == "user"), None)
    sysp = body.get("system")
    sys0 = sysp[0] if isinstance(sysp, list) and sysp else sysp
    data = canon.dumps([sys0 if sys0 is not None else "", first or "", session or ""]).encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()


REMINDER_TAG = re.compile(r"<\s*(/?)\s*system-reminder\b[^<>]{0,200}>", re.I)
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
                return words, (_texts(prev) or None) if prev else None
    return None, None

SCAN_WINDOW, SCAN_OVERLAP = 96 * 1024, 20 * 1024


def _bounded(pattern: str) -> re.Pattern:
    """inbox.SECRET with its open middles bounded, for the windowed scan only (Orithises F1, Koinos): a match must be
    shorter than the overlap, or a key crossing a window's edge lies in no window. Each part that must be reached whole
    is capped (a URL's user and password at 4 KiB each, a JWT's first two segments at 8 KiB each, a PEM label at 128,
    the spaces around "password =" or "password is" at 256), so the longest match is about 16.5 KiB, under the 20 KiB
    overlap. Every replacement must apply, or the proxy does not start."""
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


def _secret(text: str) -> bool:
    """The key-shape check over the whole text (Koinos's margin after X1: one search holds the GIL, and a 4 MiB held
    input once stopped every thread for about 2 s). Up to one window it is inbox.SECRET itself. Longer, it runs
    SECRET_BOUNDED in overlapping windows, giving the other threads the GIL between them: every match of the bounded
    pattern is shorter than the overlap, so a key is found at any offset, across any edge. Stated limit (PROXY-DESIGN
    5d): in an input longer than one window, a part longer than its bound (a URL user or password over 4 KiB, a JWT
    segment over 8 KiB, more than 256 spaces around "password =") is not found; none is a usable credential."""
    if len(text) <= SCAN_WINDOW:
        return bool(SECRET.search(text))
    for start in range(0, len(text), SCAN_WINDOW - SCAN_OVERLAP):
        if SECRET_BOUNDED.search(text, start, start + SCAN_WINDOW):
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
            conv = conversation_key(self.proxy.key, body, self.headers.get("x-claude-code-session-id"))
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
                              body.get("messages", []), now)
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
        self.proxy.stash.drop(conv)
        words, offer = person_words(body)
        out = decide.decide(space, "space", agent, model_id, msg, conv, self.proxy.asks, now, words=words, offer=offer)
        if out.held:
            raise Refused("X-REL", "the answered call would be held now; the space or its gates changed")
        left = [a for a in s.asks if self.proxy.asks.status(a, now) == "yes"]
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
        out = decide.decide(space, "space", agent, model_id, msg, conv, self.proxy.asks, now, kept=kept, words=words,
                            offer=offer)
        for c in out.calls:                                   # T8: recorded before anything is emitted
            name = space.blocks[c.tool]["name"] if c.tool else undeclared(self.proxy.key, c.name)
            self.proxy.record.append("call", {"tool": name, "decision": "held" if out.held else "pass",
                                              "d_rec": canon.d_rec(self.proxy.key, c.d_act)})
        if out.held:
            self.proxy.record.append("held", {"asks": out.asks})
            if kept:                                          # one predicate for the words and the stash (U2a)
                decide.stash_turn(self.proxy.stash, conv, body.get("model"), out, msg, thinking, _secret)
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


def serve(space_dir, home, card: str, port: int, expected_digest=None, ready=None):
    """Run the proxy on 127.0.0.1:port until stopped. `ready` (a threading.Event) is set once it listens."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    proxy = Proxy(space_dir, home, card, expected_digest)
    handler = type("H", (Handler,), {"proxy": proxy, "port": port})
    server = Server(("127.0.0.1", port), handler)
    server.daemon_threads = True
    if ready is not None:
        ready.server = server
        ready.set()
    server.serve_forever()
