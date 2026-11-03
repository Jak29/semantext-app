"""The model point's kit: a fake runtime, a scripted provider, planted-bad providers, and observers that look from
OUTSIDE the provider (Orithises K1: observed, never reported). Nothing here runs a model or reaches past 127.0.0.1.

- FakeRuntime: Ollama's two calls (/api/tags, /api/generate, streamed), in this process, on a port of its own. It
  counts for itself: tokens generated, tokens generated after it saw the client close, connections in flight at once,
  how long each generation stayed open, and every request body. Its worker threads are started with it, before any
  model call, so the watch never mistakes them for the provider's.
  keep_generating=True plants the bad runtime of PB12 / M-BUDGET: it sees the close and generates on anyway.
- Scripted: the good provider, which returns a fixed proposal (Koinos, section 3).
- NeverCloses (PB13) and NoCap (PB15): the built-in provider with one guard taken out each.
- (watched_import, a provider module's import under the same watch as a call (PB05a, PB16), lives in the tests: it
  runs a file's text as code, which nothing in the package may do; tests/test_adversarial_instructions.py.)
- state_digest, after_close, open_past, cap_sent: the observers.

What these cannot observe is said where it applies: a real runtime's tokens and CPU after a close are not seen here
(they need the runtime itself, a later run on Jak's word), and a watch inside the process does not see native code that
makes its own system calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import select
import socket
import threading
import time
from pathlib import Path

from . import model


class FakeRuntime:
    def __init__(self, pieces=("ok",), model_name: str = "fake:latest", blob: bytes | None = None, port: int = 0,
                 host: str = "127.0.0.1", delay: float = 0.0, workers: int = 4):
        self.pieces, self.model, self.delay = list(pieces), model_name, delay
        self.blob = blob if blob is not None else b"a fake model file for " + model_name.encode()
        # Two digests, as Ollama has them, so a mixup fails a test: the weights blob's sha256, named inside the
        # manifest, and the manifest's own sha256, which /api/tags reports and `ollama list` shows as the model's ID.
        self.blob_digest = "sha256:" + hashlib.sha256(self.blob).hexdigest()
        self.manifest = json.dumps({"schemaVersion": 2, "layers": [
            {"mediaType": model.WEIGHTS, "digest": self.blob_digest, "size": len(self.blob)}]}).encode()
        self.digest = "sha256:" + hashlib.sha256(self.manifest).hexdigest()
        self.host, self._port, self.workers = host, port, workers
        self.keep_generating = False   # PB12: the planted-bad runtime
        self.redirect = None           # PB03f: answer /api/generate with a 302 to this
        self.whole = True              # PB10c: False ends the stream with no "done"
        self.tags_digests = None       # PB11a/b: what /api/tags reports, one per call (default: the file's hash)
        self.eval_count = None         # what its last line says it generated (default: the truth)
        self.tags_hang = False         # F7: /api/tags is read and never answered
        self.requests: list = []       # (path, body), every HTTP request it read
        self.raw_connections = 0       # every connection accepted, HTTP or not
        self.generated = self.after_close = self.active = self.max_active = 0
        self.closed_seen = False
        self.generations: list = []    # {"opened": t, "ended": t or None}
        self._lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()

    # ---- life ------------------------------------------------------------------------------------------------------
    def start(self) -> "FakeRuntime":
        fam = socket.AF_INET6 if ":" in self.host else socket.AF_INET
        self._sock = socket.socket(fam, socket.SOCK_STREAM)
        if self._port:   # the same port again (KA4): what any local program could do once the runtime stops
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self._port))
        self._sock.listen(16)
        self._sock.settimeout(0.2)
        self.port = self._sock.getsockname()[1]
        self.url = f"http://{'[::1]' if fam == socket.AF_INET6 else self.host}:{self.port}"
        self._threads = [threading.Thread(target=self._accept, daemon=True, name="fake-runtime")]
        self._threads += [threading.Thread(target=self._work, daemon=True, name="fake-runtime")
                          for _ in range(self.workers)]
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        for _ in range(self.workers):
            self._jobs.put(None)
        for t in self._threads:
            t.join(2)
        self._sock.close()

    def _accept(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            with self._lock:
                self.raw_connections += 1
            self._jobs.put(conn)

    def _work(self):
        while True:
            conn = self._jobs.get()
            if conn is None:
                return
            try:
                self._handle(conn)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    # ---- one request -----------------------------------------------------------------------------------------------
    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(5)
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(65536)
            if not chunk:
                return
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        method, path = lines[0].split(" ")[:2]
        length = 0
        for h in lines[1:]:
            k, _, v = h.partition(":")
            if k.strip().lower() == "content-length":
                length = int(v.strip())
        while len(rest) < length:
            chunk = conn.recv(65536)
            if not chunk:
                break
            rest += chunk
        body = json.loads(rest) if rest else None
        with self._lock:
            self.requests.append((path, body))
        if path == "/api/generate" and self.redirect:
            conn.sendall(f"HTTP/1.1 302 Found\r\nLocation: {self.redirect}\r\nContent-Length: 0\r\n"
                         f"Connection: close\r\n\r\n".encode())
            return
        if path == "/api/tags" and self.tags_hang:
            while not self._stop.is_set() and not self._peer_closed(conn):
                time.sleep(0.05)
            return
        if path == "/api/tags":
            d = self.tags_digests.pop(0) if self.tags_digests else self.digest
            out = json.dumps({"models": [{"name": self.model, "model": self.model,
                                          "digest": d.removeprefix("sha256:"), "details": {"family": "fake"}}]}).encode()
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                         + str(len(out)).encode() + b"\r\nConnection: close\r\n\r\n" + out)
            return
        if path == "/api/generate":
            self._generate(conn)
            return
        conn.sendall(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")

    @staticmethod
    def _peer_closed(conn: socket.socket) -> bool:
        try:
            ready, _, _ = select.select([conn], [], [], 0)
            if not ready:
                return False
            return conn.recv(1, socket.MSG_PEEK) == b""
        except OSError:
            return True

    def _generate(self, conn: socket.socket) -> None:
        rec = {"opened": time.monotonic(), "ended": None}
        with self._lock:
            self.generations.append(rec)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\nConnection: close\r\n\r\n")
            closed = False
            for piece in self.pieces:
                if self.delay:
                    time.sleep(self.delay)
                if not closed and self._peer_closed(conn):
                    closed = self.closed_seen = True
                if closed:
                    if not self.keep_generating:
                        break
                    with self._lock:   # the planted-bad runtime: it generates on with nobody listening
                        self.generated += 1
                        self.after_close += 1
                    continue
                try:
                    conn.sendall((json.dumps({"model": self.model, "response": piece, "done": False}) + "\n").encode())
                except OSError:
                    closed = self.closed_seen = True
                    continue
                with self._lock:
                    self.generated += 1
            if not closed and self.whole:
                conn.sendall((json.dumps({"model": self.model, "response": "", "done": True,
                                          "eval_count": len(self.pieces) if self.eval_count is None
                                          else self.eval_count}) + "\n").encode())
        finally:
            rec["ended"] = time.monotonic()
            with self._lock:
                self.active -= 1


# ---- providers ------------------------------------------------------------------------------------------------------
class Scripted:
    """The good provider: returns a fixed proposal, reads nothing, touches nothing, and reports who it is on every call.
    `identity`, if given, is what it reports; otherwise the class's `default_identity` (a test sets it to the model the
    fake runtime serves). A report with no digest in it is refused, or flagged, never taken as a match (Koinos F5)."""

    default_identity: dict | None = None

    def __init__(self, out, identity: dict | None = None):
        self.out, self.identity = out, identity

    def reported(self):
        return self.identity if self.identity is not None else type(self).default_identity

    def propose(self, card: str, prompt: str):
        return self.out if isinstance(self.out, list) else [self.out]


class NeverCloses(model.OllamaProvider):
    """Planted bad (PB13): reads the stream to its end, with no budget and no shut connection."""

    def propose(self, card, prompt):
        import http.client
        host, port = self.addr
        conn = http.client.HTTPConnection(host, port, timeout=60)
        conn.request("POST", "/api/generate", body=json.dumps(self._body(card, prompt)).encode(),
                     headers={"Content-Type": "application/json"})
        r = conn.getresponse()
        out = []
        for line in r:
            out.append(json.loads(line).get("response", ""))
        return ["".join(out)]


class ClosesLate(model.OllamaProvider):
    """Planted bad M-BUDGET (c): stops reading at its budget, but shuts the connection only `late` seconds after."""
    late = 1.0

    def propose(self, card, prompt):
        self._generating = True
        try:
            return super().propose(card, prompt)
        finally:
            self._generating = False

    def _shut(self, conn, sock):
        # Late on the generate call only: the model-list calls before it shut on time, so the case dies of its own
        # rule (M-BUDGET) and not of the call's overall time (M-SIZE).
        if getattr(self, "_generating", False):
            time.sleep(ClosesLate.late)
        model.OllamaProvider._shut(conn, sock)


class ReturnsOpen(model.OllamaProvider):
    """Planted bad M-BUDGET (d): answers with the first piece and returns, leaving the connection open while the
    runtime generates on. The kernel files the answer; only the runtime's counters show what went on."""

    def propose(self, card, prompt):
        import http.client
        host, port = self.addr
        self._left = http.client.HTTPConnection(host, port, timeout=5)
        self._left.request("POST", "/api/generate", body=json.dumps(self._body(card, prompt)).encode(),
                           headers={"Content-Type": "application/json"})
        self._resp = self._left.getresponse()
        return [json.loads(self._resp.readline()).get("response", "")]

    def close_now(self):
        """The test's own cleanup, after the kit has looked."""
        for x in (getattr(self, "_resp", None), getattr(self, "_left", None)):
            if x is not None:
                x.close()


class NoCap(model.OllamaProvider):
    """Planted bad (PB15): asks the runtime with no token cap."""

    def _body(self, card, prompt):
        b = super()._body(card, prompt)
        b["options"].pop("num_predict", None)
        return b


# ---- observers ---------------------------------------------------------------------------------------------------------
def state_digest(root) -> str:
    """Names, sizes, modified times and hashes of every file under the state directory (Demo 2's P-5)."""
    rows = []
    for dirpath, _dirs, files in os.walk(root):
        for f in sorted(files):
            p = Path(dirpath) / f
            try:
                st = p.stat()
                rows.append([str(p.relative_to(root)), st.st_size, st.st_mtime_ns,
                             hashlib.sha256(p.read_bytes()).hexdigest()])
            except OSError as e:
                rows.append([str(p), "unreadable", type(e).__name__])
    return hashlib.sha256(json.dumps(sorted(rows)).encode()).hexdigest()


def after_close(rt: FakeRuntime, settle: float = 1.0) -> int:
    """Tokens the runtime generated after it saw the client close, counted by the runtime, after a settle time."""
    time.sleep(settle)
    return rt.after_close


def open_past(rt: FakeRuntime, budget: float, margin: float = 0.3) -> bool:
    """Whether any generation stayed open longer than the budget (and a margin), as the runtime measured it."""
    now = time.monotonic()
    return any(((g["ended"] or now) - g["opened"]) > budget + margin for g in rt.generations)


def budget_verdict(rt: FakeRuntime, budget: float) -> str | None:
    """M-BUDGET, judged at the runtime (Orithises r5): the provider returned, or was abandoned, while generation went
    on: tokens generated after the runtime saw the close, or a generation open past the budget. None otherwise. The
    kernel cannot judge this; only the runtime's own counters can."""
    return "M-BUDGET" if rt.after_close > 0 or open_past(rt, budget) else None


def cap_sent(rt: FakeRuntime) -> list:
    """The token cap each generate request carried, as the runtime received it (None: no cap)."""
    return [((b or {}).get("options") or {}).get("num_predict") for p, b in rt.requests if p == "/api/generate"]
