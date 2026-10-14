"""The feed: what Semantext did with each prompt, so you can watch it work.

Each time the hook hands out a card it keeps one line in <home>/feed.jsonl: when; which agent asked, and how Semantext
knew it; whose words the prompt carried, and what told; for another agent's message, the name its opening tag gives
the sender (a claim); the environment; the card's form; the rules on it, layer by layer; its size, and how many rules
the size limit left out; the inbox answers and requests that went with it; whether a broken file cut the card back
to the base rules; and what Semantext's own quick reading noticed in the message, by kind only (a question, a maybe,
an act that needs the person's word ...).

What it never keeps: the prompt's text, or anything else that was said. Every value is checked for the shape of a key,
a token or a password, and one that has it is kept as "(withheld)". Only the newest lines are kept: past TRIM_AT bytes
the file is cut back to the newest KEEP bytes of whole lines. Switched off (`semantext feed off`, or Settings on the
page), nothing at all is written. The page reads it only through its own server (server.py), and nothing reads it for
anything else: it is a record of what happened, never a source of rules.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from .inbox import SECRET, file_lock, token_like
from .store import Refused

FIELDS = ("at", "agent", "how", "tool", "words", "from", "basis", "environment", "form", "layers", "bytes", "left_out",
          "answers", "waiting", "problem", "noticed")
# What Semantext's own quick reading noticed in the user's own message, by kind only, never the words: a question, a
# maybe, a yes, a pause, a time limit, a correction, an instruction, an act that needs their word (send, delete,
# publish...), and an answer to a request, typed in chat. Another agent's message or a tool's notice: nothing.
NOTICED = ("question", "suggestion", "yes", "pause", "time", "correction", "instruction", "needs-word", "answer")
OLDER = frozenset(FIELDS) - {"noticed"}  # a line written before 1.1 kept no `noticed`: read back as noticing nothing
HOW = ("bound", "claimed", "observed", "fallback")
WORDS = ("own", "agent", "tool")        # the user's own words, another agent's, or a tool's notice
BASIS = ("text", "transcript", "none")  # what told: how the prompt opens, the tool's own record, or nothing (the user's)
FORMS = ("full", "relay")
LAYERS = ("base", "environment", "agent")
TRIM_AT, KEEP = 512_000, 256_000        # bytes
WITHHELD = "(withheld)"
BUSY_TRIES = 8                          # 25 ms each: a busy feed is skipped, never waited on, so no prompt waits


def stamp() -> str:
    """Now, to the microsecond: a record's time is also its place in the feed."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def scrub(value):
    """The value, with every string shaped like a key, a token or a password replaced by WITHHELD."""
    if isinstance(value, str):
        return WITHHELD if SECRET.search(value) or token_like(value) else value
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()}
    return value


def _count(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def valid(r) -> bool:
    """Whether r is a feed record: exactly FIELDS, each of its declared kind. Nothing else is written, or read back."""
    if not isinstance(r, dict) or set(r) != set(FIELDS):
        return False
    texts = all(isinstance(r[k], str) for k in ("at", "agent", "tool", "from", "environment"))
    layers = isinstance(r["layers"], list) and all(
        isinstance(x, dict) and set(x) == {"layer", "name", "ids"} and x["layer"] in LAYERS
        and isinstance(x["name"], str) and isinstance(x["ids"], list) and all(isinstance(i, str) for i in x["ids"])
        for x in r["layers"])
    return (texts and layers and r["how"] in HOW and r["words"] in WORDS and r["basis"] in BASIS
            and r["form"] in FORMS and _count(r["bytes"]) and _count(r["left_out"])
            and all(isinstance(v, list) and all(_count(i) for i in v) for v in (r["answers"], r["waiting"]))
            and isinstance(r["problem"], bool)
            and isinstance(r["noticed"], list) and all(k in NOTICED for k in r["noticed"]))


class Feed:
    def __init__(self, root: Path):
        self.path = Path(root) / "feed.jsonl"
        self.lock_path = Path(root) / "feed.lock"

    def add(self, record: dict) -> bool:
        """Keep one record, scrubbed. Refused unless it is a feed record (see valid). Best effort otherwise: when the
        file is busy this record is skipped (False), so a prompt never waits on the feed."""
        record = scrub(record)
        if not valid(record):
            raise Refused("not a feed record: the feed keeps exactly its declared fields")
        line = json.dumps({k: record[k] for k in FIELDS}, ensure_ascii=False) + "\n"
        try:
            with file_lock(self.lock_path, "the feed is busy", tries=BUSY_TRIES):
                with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(line)
                if self.path.stat().st_size > TRIM_AT:
                    self._trim()
        except Refused:
            return False
        return True

    def _trim(self) -> None:
        """Cut back to the newest whole lines within KEEP bytes, through a temporary file put in place."""
        kept, size = [], 0
        for line in reversed(self.path.read_bytes().splitlines(keepends=True)):
            if size + len(line) > KEEP:
                break
            kept.append(line)
            size += len(line)
        tmp = self.path.with_name(f"feed.{os.getpid()}.tmp")
        try:
            tmp.write_bytes(b"".join(reversed(kept)))
            for attempt in range(20):   # Windows refuses the swap while the page is reading the file
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    time.sleep(0.025)
        finally:
            if tmp.exists():
                tmp.unlink()            # the swap never happened: the old file stands, and is cut next time

    def recent(self, n: int = 100) -> list[dict]:
        """The newest n records, newest first. A damaged line, or one that is not a feed record, is skipped; a line in
        the form written before `noticed` was kept is read as noticing nothing."""
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except (FileNotFoundError, NotADirectoryError):
            return []
        out = []
        for line in reversed(lines):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and set(r) == OLDER:
                r["noticed"] = []
            if valid(r):
                out.append(r)
                if len(out) >= n:
                    break
        return out
