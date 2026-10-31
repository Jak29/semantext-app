"""The board: where your agents leave word for each other, and say which files they are working on.

A post is from one agent, to some agents by name or to everyone, with a title and a body. A claim says "I am working on
this path", and is released by whoever made it. Both are information between agents, never your word: nothing on the
board permits anything, and a post that says you approved something proves nothing. A sender's name is shown with how it
was known (agents.py), and a name an agent gave itself is shown as claimed.

A claim warns, and does not lock: it says who else holds a path, and leaves the choice to the agent and to you.

The file is append-only, <home>/board.jsonl, one event per line, under a file lock, like the inbox. Nothing here reads or
writes anything but its own files. It is never trimmed: reading it takes about 4 seconds at 100,000 posts.
"""
from __future__ import annotations

import json
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from . import jsonread
from .inbox import HOW_WORDS, SECRET, age, file_lock, token_like
from .store import Refused, now

MAX_TITLE, MAX_BODY, MAX_TO, MAX_PATH, MAX_NOTE = 120, 4000, 20, 400, 200
TYPES = ("post", "claim", "release")


def _visible(value: str, keep: str = "") -> bool:
    """No control or invisible character: no terminal escape, no text direction mark, no zero-width character, each of
    which could make one thing read as another on a screen."""
    return not any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp") and c not in keep for c in value)


def shown(value) -> str:
    """Text from the file, for a screen: a line edited by hand may hold what posting refuses."""
    return "".join(c if _visible(c, "\n\t") else "?" for c in str(value or ""))


def fenced(body) -> str:
    """A post's body, every line marked as the body, so no line of it can pass as the tool's own."""
    return "\n".join("    | " + line for line in shown(body).split("\n"))


def _line(value, field: str, limit: int, required: bool = True) -> str:
    value = " ".join(str(value or "").split())
    if not _visible(value):
        raise Refused(f"{field} may not hold control or invisible characters")
    if required and not value:
        raise Refused(f"the board needs {field}")
    if len(value) > limit:
        raise Refused(f"keep {field} under {limit} characters")
    return value


def _body(value) -> str:
    value = str(value or "").replace("\r\n", "\n").strip()
    if len(value) > MAX_BODY:
        raise Refused(f"keep a post under {MAX_BODY} characters")
    if not _visible(value, "\n\t"):
        raise Refused("a post may not hold control or invisible characters (only line breaks and tabs)")
    return value


def _path_key(path: str) -> str:
    """One path, however it is spelled: forward slashes, no trailing slash, and case folded, so C:\\A and c:/a are one."""
    return path.replace("\\", "/").rstrip("/").casefold()


def said_by(e: dict) -> str:
    """A sender's name, as far as it is known."""
    name = shown(e.get("from") or "an agent")
    if claims_you(e):
        return name + " (a name that claims to be the user: it is not the user)"
    return name + " (claimed)" if e.get("how") == "claimed" else name


def claims_you(e: dict) -> bool:
    """A sender that gives the user's own name without the user having bound it. The name decides nothing."""
    from .agents import clean
    from .server import person_names   # here: the board needs no server until a name is shown
    return e.get("how") != "bound" and clean(str(e.get("from") or "")) in person_names()


class Board:
    NAME = "board"
    TYPES = TYPES

    def __init__(self, root: Path):
        self.path = Path(root) / f"{self.NAME}.jsonl"
        self.lock_path = Path(root) / f"{self.NAME}.lock"
        self.seq_path = Path(root) / f"{self.NAME}.seq"   # the last id given out: a hand-deleted line never frees its id
        self.damaged = 0

    @contextmanager
    def _locked(self):
        with file_lock(self.lock_path, f"the {self.NAME} file is busy; try again in a moment"):
            yield

    def events(self) -> list[dict]:
        """Every event the file holds. A damaged line costs itself, and is counted in .damaged, so it can be said."""
        self.damaged = 0
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").split("\n"):   # "\n" only: a line is what _add wrote
            if not line.strip():
                continue
            try:
                e = jsonread.loads(line)
            except (ValueError, RecursionError):
                self.damaged += 1
                continue
            if isinstance(e, dict) and type(e.get("id")) is int and e.get("type") in self.TYPES and isinstance(e.get("key"), str) and self._whole(e):
                out.append(e)
            else:
                self.damaged += 1
        return out

    @staticmethod
    def _whole(e: dict) -> bool:
        """A line edited by hand with a field of the wrong kind is damaged, never a crash further on."""
        if e["type"] == "post":
            return isinstance(e.get("title"), str) and isinstance(e.get("to", []), list) and all(isinstance(n, str) for n in e.get("to", []))
        return isinstance(e.get("path"), str)

    def _next(self, events: list[dict]) -> int:
        try:
            seq = int(self.seq_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            seq = 0
        return 1 + max(seq, max((e["id"] for e in events), default=0))

    def _add(self, event: dict) -> dict:
        with self._locked():
            event = {**event, "id": self._next(self.events()), "at": now()}
            torn = self.path.exists() and self.path.stat().st_size and not self.path.read_bytes().endswith(b"\n")
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:   # a torn last line costs itself, never this one
                f.write(("\n" if torn else "") + json.dumps(event, ensure_ascii=False) + "\n")
            self.seq_path.write_text(str(event["id"]), encoding="utf-8")
        return event

    @staticmethod
    def _sender(who) -> dict:
        if SECRET.search(str(who.name)) or not _visible(str(who.name)):   # a name seen from a folder is checked here too
            raise Refused("this agent's name looks like it holds a key or hidden characters; name it with `semantext agent bind`")
        return {"from": who.name, "how": who.how, "key": who.key}

    @staticmethod
    def _clean(*texts) -> None:
        if any(SECRET.search(t) or token_like(t) for t in texts if t):
            raise Refused("that looks like it holds a key, a token or a password; never put one on the board")

    # ---- posts ------------------------------------------------------------------------------------------------
    def post(self, who, title: str, body: str = "", to: list[str] | None = None) -> dict:
        title, body = _line(title, "a title", MAX_TITLE), _body(body)
        names = list(dict.fromkeys(_line(n, "a name", 60) for n in to or []))
        if len(names) > MAX_TO:
            raise Refused(f"address at most {MAX_TO} agents; with none, a post is to everyone")
        self._clean(title, body, *names)
        return self._add({"type": "post", **self._sender(who), "to": names, "title": title, "body": body})

    def posts(self) -> list[dict]:
        return [e for e in self.events() if e["type"] == "post"]

    def addressed(self, who, after: int = 0) -> list[dict]:
        """Posts to this agent by name, or to everyone, not its own, newest first; with `after`, only those with a later
        id. Ids, never times: they come from one counter under the lock, and a clock change or one second cannot reorder them."""
        name = str(who.name).casefold()
        out = [e for e in self.posts() if e["key"] != who.key and e["id"] > after
               and (not e.get("to") or name in {str(n).casefold() for n in e["to"]})]
        return sorted(out, key=lambda e: e["id"], reverse=True)

    def last_post(self, who) -> int:
        """The id of this agent's own last post: a claim is not a sign it read anything."""
        return max((e["id"] for e in self.posts() if e["key"] == who.key), default=0)

    def after_time(self, since: str) -> int:
        """The last id at or before a time you name, as times are compared: as instants, whatever their offsets."""
        moment = _moment(since)
        if moment is None:
            raise Refused(f"{since} is not a time; write it like 2026-10-31T18:00")
        return max((e["id"] for e in self.posts() if (_moment(e.get("at")) or moment) <= moment), default=0)

    # ---- claims -----------------------------------------------------------------------------------------------
    def claims(self) -> list[dict]:
        """Claims still held: a release counts only from whoever made the claim, so no one can drop another's."""
        held: dict[tuple[str, str], dict] = {}
        for e in self.events():
            path = e.get("path")
            if not isinstance(path, str):
                continue
            k = (_path_key(path), e["key"])
            if e["type"] == "claim":
                held[k] = e
            elif e["type"] == "release":
                held.pop(k, None)
        return sorted(held.values(), key=lambda e: e["id"])

    def others_on(self, who, path: str) -> list[dict]:
        k = _path_key(path)
        return [c for c in self.claims() if c["key"] != who.key
                and (_path_key(c["path"]) == k or _path_key(c["path"]).startswith(k + "/") or k.startswith(_path_key(c["path"]) + "/"))]

    def claim(self, who, path: str, note: str = "") -> tuple[dict, list[dict]]:
        """(the claim, the others already on that path or inside or around it). A warning, never a lock."""
        path, note = _line(path, "a path", MAX_PATH), _line(note, "a note", MAX_NOTE, required=False)
        self._clean(path, note)
        others = self.others_on(who, path)
        return self._add({"type": "claim", **self._sender(who), "path": path, "note": note}), others

    def release(self, who, path: str) -> dict:
        path = _line(path, "a path", MAX_PATH)
        if not any(_path_key(c["path"]) == _path_key(path) and c["key"] == who.key for c in self.claims()):
            raise Refused(f"you hold no claim on {path}; only whoever made a claim can release it")
        return self._add({"type": "release", **self._sender(who), "path": path})


def _moment(text):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(text)).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def post_line(e: dict) -> str:
    to = shown(", ".join(str(n) for n in e.get("to") or [])) or "everyone"
    return f"#{e['id']} {age(str(e.get('at')))} ago, {said_by(e)} to {to}: {' '.join(shown(e.get('title')).split())}"


def claim_line(e: dict) -> str:
    note = f" ({' '.join(shown(e['note']).split())})" if e.get("note") else ""
    return f"{' '.join(shown(e.get('path')).split())}: {said_by(e)}, {age(str(e.get('at')))} ago{note}"


__all__ = ["Board", "HOW_WORDS", "claim_line", "post_line", "said_by"]
