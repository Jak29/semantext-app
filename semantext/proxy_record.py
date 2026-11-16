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
import hashlib
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
        self._torn = False
        self.seq, self.prev = 0, chain.GENESIS
        # The part of the file already read and found whole: its length in bytes, the SHA-256 of those bytes, and its
        # sealed lines. A later read re-hashes that part (cheap) and parses only what follows it; if any byte of it
        # changed, the hash differs and the whole file is read again. So an edit anywhere is still caught at the next
        # read, as before, but a long record no longer costs a full parse at every append.
        self._known = (0, hashlib.sha256(b"").hexdigest(), [])

    def _scan(self) -> list | None:
        """Every sealed line of the file, in order, or None when the file is not one whole chain from the start (a line
        edited, dropped, swapped, not UTF-8, or not this record's). FileNotFoundError when there is no file."""
        data = self.path.read_bytes()
        # A last line without its newline is a torn tail (a write cut at the newline, or the newline taken off): the
        # next append would write straight after it and make one unreadable line of two (the pageasks attack, K3).
        # verify() reads this; lines() still reads what is whole.
        self._torn = bool(data) and not data.endswith(b"\n")
        size, digest, known = self._known
        if len(data) >= size and hashlib.sha256(memoryview(data)[:size]).hexdigest() == digest:
            start, out = size, list(known)             # the part read before is byte for byte as it was
        else:
            start, out = 0, []
        try:
            tail = bytes(memoryview(data)[start:]).decode("utf-8")
        except UnicodeDecodeError:
            return None
        prev = out[-1]["hash"] if out else chain.GENESIS
        for line in tail.splitlines():
            if not line.strip():
                continue
            rec, why, own = chain.parse_line(line)
            if rec is None or not own or rec.get("prev") != prev or rec.get("seq") != len(out) + 1:
                return None                               # not whole: nothing on it is trusted
            out.append(rec)
            prev = rec["hash"]
        if data.endswith(b"\n") or not data:              # remember only up to a whole last line
            self._known = (len(data), hashlib.sha256(data).hexdigest(), out)
        return out

    def _head(self) -> None:
        if not self.head_path.exists():
            self.seq, self.prev = 0, chain.GENESIS
            return
        try:
            head = json.loads(self.head_path.read_text(encoding="utf-8"))
            seq = head["seq"]
            # A count is a whole number: written as one (the writer's own form) or as digits. Not a bool, not a float
            # (-1.5 and 1e400 are not counts, and int() would make one of them), not below zero: a head of -1 over an
            # empty chain reached got[-1] on [] (the pageasks attack, K2).
            if isinstance(seq, str) and not (seq.isascii() and seq.isdigit()):
                raise ValueError("not a count")
            if isinstance(seq, bool) or not isinstance(seq, (int, str)) or int(seq) < 0:
                raise ValueError("not a count")
            self.seq, self.prev = int(seq), str(head["hash"])
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            self.broken = True

    def lines(self) -> list[dict]:
        """Every line of the chain in its sealed form, followed back from the head; a broken chain gives none."""
        try:
            got = self._scan()
        except FileNotFoundError:
            return []
        except OSError:
            return []
        return list(got) if got is not None else []

    def verify(self) -> bool:
        """Whether the chain on disk is whole and ends at the head (R4): a line edited, dropped or swapped, or a head
        that names another line, is noticed here, at start and before the first append, not left to a later reader."""
        self._head()
        if self.broken:
            return False
        try:
            got = self._scan()
        except FileNotFoundError:
            return self.seq == 0
        except OSError:                                # unreadable (a folder at the name): broken, said
            self.broken = True
            return False
        if got is not None and self._torn:
            self.broken = True                         # a torn last line: broken as it always was, never rolled forward
            return False
        ok = got is not None and len(got) == self.seq and (not got or got[-1]["hash"] == self.prev)
        if not ok and got is not None and not self.broken and self._interrupted(got):
            # append() writes the line, then the head. A process that died between the two, or whose head write failed,
            # leaves the file exactly one sealed line ahead of the head, and that line follows the head. That one line is
            # rolled forward: it is taken as the head here, and the next append writes the head file over it. Nothing
            # else is: two lines ahead, a line that does not follow the head (_scan already refuses a chain that
            # breaks), an earlier line changed, a head ahead of the file, or a last line that lacks its newline (K3)
            # stay broken. A whole file ends in a newline, so no append ever writes after a torn line.
            self.seq, self.prev = got[-1]["seq"], got[-1]["hash"]
            ok = True
        self.broken = self.broken or not ok
        return ok

    def _interrupted(self, got: list) -> bool:
        """Whether the chain `got` is the head's chain and one line more, that line sealed on the head (seq = head seq +
        1, prev = head hash). *Limit:* the line is accepted because it is sealed on the head, as every line is; the chain
        has no key, so someone who can write this file could add one and have it taken. That is the anchor's catch
        (ARCHITECTURE section 2), not this file's."""
        if not got or len(got) != self.seq + 1:        # not got: a count below zero cannot name an empty chain's next line
            return False
        last = got[-1]
        return last.get("seq") == self.seq + 1 and last.get("prev") == self.prev

    def append(self, kind: str, body: dict) -> dict:
        with self._lock, file_lock(self.lock_path):
            # Before every append, not only the first: a line broken while the proxy runs is caught at the next one.
            # The part already found whole is re-hashed, not re-parsed (see _known): an edit there is still caught.
            self.verify()          # reads the head too, and may roll one interrupted line forward (seq and prev then
            if self.broken:        # name that line: a second _head() here would undo it)
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
