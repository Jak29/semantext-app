"""The proxy's record: an append-only, hash-chained log in the doors-spec envelope (ARCHITECTURE.md v1.3, section 2).

Each line is sealed by work/chain.py (the same canonical form and hash as the Work store): {v, id, kind, provider, at,
source, body, seq, prev, hash}. The head ({seq, hash} of the last line) is kept beside the log.

What a body may hold is the caller's to keep narrow (PROXY-DESIGN r4, section 6): no message text, no tool-input text,
no key; a name only if it is declared, otherwise "undeclared" with its length and a keyed digest (D7). `undeclared()`
gives that form.

No record, no pass (T8): append() raises RecordFailed when the line cannot be written and made durable; the caller
then refuses the request. Once a write has failed, every later append fails too, until a person looks.
"""
from __future__ import annotations

import datetime
import json
import os
import secrets
import threading
from pathlib import Path

from . import canon
from .store import file_lock
from .work import chain

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
MAX_TEXT = 200          # any text recorded is at most this many characters, from a restricted set


class RecordFailed(Exception):
    """The record could not be written: nothing passes until it can (T8)."""


def mint(prefix: str) -> str:
    """An opaque id minted by the kernel: <prefix>_<26 Crockford base32> (doors spec v0.6, rule 3)."""
    n = secrets.randbits(130)
    return prefix + "_" + "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in range(26))


def safe(text: str) -> str:
    """Text for the record: capped and restricted to letters, digits and a few marks (D7)."""
    return "".join(c for c in str(text)[:MAX_TEXT] if c.isalnum() or c in " _-.:/")


def undeclared(node_key: bytes, name: str) -> dict:
    """A name the blocks do not declare: never its text (D7)."""
    return {"class": "undeclared", "length": len(name), "digest": canon.d_rec(node_key, canon.d_act(name))}


class Record:
    """Appended by the proxy and by the person's answering command alike, so the head is re-read under a lock held
    across processes (store.file_lock) at every append, never trusted from memory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.head_path = self.path.with_name(self.path.name + ".head.json")
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._lock = threading.Lock()
        self.broken = False
        self.seq, self.prev = 0, chain.GENESIS

    def _head(self) -> None:
        if not self.head_path.exists():
            self.seq, self.prev = 0, chain.GENESIS
            return
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
            self.seq, self.prev = int(head["seq"]), str(head["hash"])
        except (OSError, ValueError, KeyError, TypeError):
            self.broken = True

    def lines(self) -> list[dict]:
        """Every line of the chain in its sealed form, followed back from the head; a broken chain gives none."""
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        out, prev = [], chain.GENESIS
        for n, line in enumerate(l for l in text.splitlines() if l.strip()):
            rec, why, own = chain.parse_line(line)
            if rec is None or not own or rec.get("prev") != prev or rec.get("seq") != n + 1:
                return []                                 # not whole: nothing on it is trusted
            out.append(rec)
            prev = rec["hash"]
        return out

    def verify(self) -> bool:
        """Whether the chain on disk is whole and ends at the head (R4): a line edited, dropped or swapped, or a head
        that names another line, is noticed here, at start and before the first append, not left to a later reader."""
        self._head()
        if self.broken:
            return False
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self.seq == 0
        except (OSError, ValueError):                 # unreadable (a folder at the name, not UTF-8): broken, said
            self.broken = True
            return False
        lines = self.lines()
        n = sum(1 for l in text.splitlines() if l.strip())
        ok = len(lines) == n == self.seq and (not lines or lines[-1]["hash"] == self.prev)
        self.broken = self.broken or not ok
        return ok

    def append(self, kind: str, body: dict) -> dict:
        with self._lock, file_lock(self.lock_path):
            # Before every append, not only the first: a line broken while the proxy runs is caught at the next one.
            # Limit, stated: this reads the whole chain each time, so its cost grows with the record (v0).
            self.verify()
            self._head()
            if self.broken:
                raise RecordFailed("the record failed before and has not been looked at")
            rec = {"v": 1, "id": mint("pr"), "kind": kind, "provider": "semantext", "source": "proxy",
                   "at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                   "body": body}
            sealed = chain.seal(rec, self.seq + 1, self.prev)
            try:
                with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(chain.line_of(sealed) + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                tmp = self.head_path.with_name(self.head_path.name + ".tmp")
                tmp.write_text(json.dumps({"seq": sealed["seq"], "hash": sealed["hash"]}), encoding="utf-8")
                os.replace(tmp, self.head_path)
            except (OSError, ValueError, TypeError) as e:
                self.broken = True
                raise RecordFailed(f"the record could not be written ({type(e).__name__})") from None
            self.seq, self.prev = sealed["seq"], sealed["hash"]
            return sealed
