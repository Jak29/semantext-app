"""The kernel's one writer of work events (PM-DESIGN r2 to r5).

One store, owned by Semantext, in its own home: <home>/work/events.jsonl, with its head in events.head.json beside it
(r4: no seat writes into another seat's home). Every write goes through store.append_checked, and under its one lock
the writer reads the log, walks the chain to the head, folds it, and only then decides: it mints the id
(W-<project>-<n>, one more than any n ever used in that project), answers a repeated request_key with the first result
(the same body) or CONFLICT (another body), refuses a `from` that is not the folded state (STALE_VERSION), asks the
same rules the fold applies (rules.apply, on a copy), stamps who, at and the assurance, and chains the line to the head.
The caller never sets who, at or the assurance: they come from the Actor, which only kernel code makes. A claimed
actor's authority-bearing event that the table would allow from a bound seat is written as a proposal and shown so; any
other refusal writes nothing.

The containment set (doors spec v0.6, rule 11), on every write: no link or junction at the log, the head, the store
folder, or any folder between it and the Semantext home; no second hard link; a size cap. Above the home, where the home
lies is the person's own choice and is not judged (a temporary folder is under a link on some systems).
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import jsonread, paths, store
from . import span
from ..sources import MAX_LINE
from .chain import GENESIS, line_of, parse_line, read_head, seal
from .events import PERSON, SEAT_RE, VERSION, WorkRefused, request, valid_project
from .chain import extend, walk
from .fold import Folder
from .rules import Refuse, apply, clauses_hash
from .turns import check_turn

RATE_PER_MINUTE = 120              # events per actor per minute (the attack, F9)
STORE_BYTES = 256 * 1024 * 1024    # the log's size cap


@dataclass(frozen=True)
class Actor:
    """Who is acting, as the kernel knows it. `assurance` is "bound" only for the kernel's own channels (the MCP tool,
    the person's found turn); the command line makes "claimed" actors, which hold no rights."""
    who: str
    assurance: str
    channel: str
    session: str | None = None


def cli_actor(name: str) -> Actor:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-")[:40] or "cli"
    if not clean[0].isalpha():
        clean = "cli-" + clean
    return Actor(clean[:40] if clean != PERSON else "cli-person", "claimed", "cli")


def slug(name) -> str | None:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:64].strip("-")
    return s if valid_project(s) else None


class Writer:
    def __init__(self, home=None, *, projects=None, seats=None, clock=None, turns=None, parked=(),
                 rate=RATE_PER_MINUTE, cap=STORE_BYTES, transcript_roots=None):
        self.home = Path(home) if home else paths.home()
        # the folders a person's turn may lie in: a span outside them is never read, at write or when read again
        given = transcript_roots if transcript_roots is not None else getattr(turns, "transcripts", None)
        self.transcript_roots = list(given) if given is not None else span.transcript_roots()
        self.dir = self.home / "work"
        self.path, self.head_path = self.dir / "events.jsonl", self.dir / "events.head.json"
        # the line being written, before it is written: {"hash", "head"} (PM-DESIGN, decided 24 October, low 10)
        self.pending_path = self.dir / "events.pending.json"
        self._projects, self._seats = projects, seats
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.turns, self.parked, self.rate, self.cap = turns, frozenset(parked), rate, cap
        self._cache, self._cache_lock = None, threading.RLock()

    # ---- what is known -------------------------------------------------------------------------------------------
    def projects(self) -> set[str]:
        """The project slugs an item may belong to: those given, else the seats file's seat names and named roots, and
        any names in <home>/work/projects.json (a list of names, the person's own)."""
        if self._projects is not None:
            return set(self._projects)
        from ..sources import kernel
        names = [r["seat"] for r in kernel.seat_rows(self.home)] + [r["name"] for r in kernel.named_roots(self.home)]
        extra = self.dir / "projects.json"
        try:
            listed = jsonread.loads(extra.read_text(encoding="utf-8")) if extra.is_file() else []
        except (OSError, ValueError):
            listed = []
        names += [x for x in listed if isinstance(x, str)] if isinstance(listed, list) else []
        return {s for s in map(slug, names) if s}

    def seats(self) -> set[str] | None:
        if self._seats is not None:
            return set(self._seats)
        from ..sources import kernel
        rows = kernel.seat_rows(self.home)
        return {r["seat"] for r in rows} if rows else None

    def state(self) -> dict:
        """The folded store, read without the file lock (a reader never blocks the writer), through the same cache."""
        raw, head = self.read()
        with self._cache_lock:   # a copy: the cached fold goes on growing, and a caller must not see it move
            return copy.deepcopy(self._folded(raw, head, self.clock()))

    def read(self, tries: int = 3) -> tuple[bytes, dict | None]:
        """The log's bytes and its head, read without the lock as one view (G6, finding 12). The head is read FIRST:
        the writer syncs a line before it moves the head, so the log read after it always holds the record that head
        names, and a write landing between the two reads can only leave its own new line past the head for a moment,
        never make a sound store read as broken. The head is read again after the log, and the pair read again while
        it moved."""
        for _ in range(max(1, tries)):
            head = self._head()
            raw = self.path.read_bytes() if self.path.exists() else b""
            if self._head() == head:
                break
        return raw, head

    def _folded(self, raw: bytes, head, now=None) -> dict:
        """The fold of these bytes against this head. The verified prefix is cached: the bytes up to the end of the
        last line folded, their SHA-256, the head they were verified to, and the Folder. When the file still begins
        with exactly those bytes, only the lines after them are walked (back from the head to the cached head) and fed;
        any other change (an edit, a cut, a head that moved back, a chain that runs through an older line) verifies the
        whole store again. Only an intact store is cached. The prefix is re-hashed on every read, so an edit inside it
        is always seen; that is a pass of SHA-256 over the file, not a fold."""
        cut = raw.rfind(b"\n") + 1
        torn = raw[cut:].decode("utf-8", errors="replace") if cut < len(raw) else None
        with self._cache_lock:
            c = self._cache
            if c is not None and not self._watch_holds(c):
                c = self._cache = None          # a transcript changed under a cached verdict: fold again, checked anew
            if c is not None and cut >= c["offset"] and hashlib.sha256(raw[:c["offset"]]).hexdigest() == c["sha"]:
                if head != c["head"] or cut > c["offset"]:
                    more = _lines(raw[c["offset"]:cut])
                    ext = extend(more, c["lines"], c["head"], head)
                    if ext is not None:
                        got = self._checks(ext["records"])
                        c["folder"].feed(ext["records"], ext["problems"], got)
                        self._watch(c, ext["records"], got)
                        c.update(offset=cut, sha=hashlib.sha256(raw[:cut]).hexdigest(), head=dict(head),
                                 lines=c["lines"] + len(more))
                    else:
                        c = None
                if c is not None:
                    return _with_torn(c["folder"].snapshot(now, dict(head), True), torn, c["lines"])
            lines = _lines(raw[:cut])
            w = walk(lines, None, head)
            folder = Folder(self.parked)
            got = self._checks(w["records"])
            folder.feed(w["records"], w["problems"], got, w["intact"])
            self._cache = {"offset": cut, "sha": hashlib.sha256(raw[:cut]).hexdigest(), "head": dict(head),
                           "lines": len(lines), "folder": folder, "watch": {}} if w["intact"] and head else None
            if self._cache is not None:
                self._watch(self._cache, w["records"], got)
            return _with_torn(folder.snapshot(now, w["end"], w["intact"]), torn, len(lines))

    def _checks(self, records) -> dict:
        """Each person_act's transcript span read again (span.checks), before the fold: the fold reads nothing."""
        return span.checks(records, self.transcript_roots)

    @staticmethod
    def _watch(cache, records, checks) -> None:
        """Remember, beside the cached fold, each transcript a verdict was read from: its size and mtime then, and the
        acts read from it with their verdicts. A verdict reached while the span could not be read (a locked file, a
        transcript not there yet) is marked to be read again on every read: it is never kept (round 4, finding 4)."""
        for n, rec, on_chain in records:
            path = span.span_path(rec) if n in checks else None
            if path is not None:
                w = cache["watch"].setdefault(path, {"stamp": span.stamp(path), "acts": {}})
                verdict, why = checks[n]
                w["acts"][n] = (rec, on_chain, verdict, verdict == span.UNVERIFIED and why == span.UNREADABLE)

    def _watch_holds(self, cache) -> bool:
        """False when a transcript behind a cached verdict changed (its size or mtime moved: an edit, a cut, or only
        growth), or a verdict was reached while its span could not be read, and reading the act again gives another
        verdict; then the cache is dropped. Growth alone keeps every verdict, so a growing transcript costs one
        bounded read per act in it, never a fold from scratch."""
        for path, w in cache.get("watch", {}).items():
            now = span.stamp(path)
            moved = now != w["stamp"]
            for rec, on_chain, verdict, retry in w["acts"].values():
                # (size, mtime) can be put back after an equal-length edit, so the span's own sha256 is compared too
                # (round 4, decision 7): one bounded read per act; the full check only when something moved
                if (moved or retry or not _span_same(rec, self.transcript_roots)) and \
                        span.check(rec, self.transcript_roots, on_chain)[0] != verdict:
                    return False
            w["stamp"] = now
        return True

    def _head(self):
        """The head, or None when it is missing or not one: a head file that is not UTF-8 is not a head (the store then
        reads as broken, a problem shown), never a raise (round 4, low)."""
        try:
            return self._head_strict()
        except (OSError, UnicodeDecodeError):
            return None

    def _head_strict(self):
        """The head as _head reads it, but an OSError (a head that could not be read now) is raised."""
        try:
            return read_head(self.head_path.read_text(encoding="utf-8")) if self.head_path.exists() else None
        except UnicodeDecodeError:
            return None

    # ---- writing -------------------------------------------------------------------------------------------------
    def write(self, actor: Actor, event: str, req: dict, *, source=None) -> dict:
        """One event from an agent (or the command line), or a WorkRefused. Returns {"id", "seq", "applied",
        "proposal", "item"}."""
        if event == "person_act":
            raise WorkRefused("NOT_AUTHORIZED", "the person's acts come only from their own turn (person_act)")
        if actor.who == PERSON or actor.channel == "person":
            raise WorkRefused("NOT_AUTHORIZED", "an agent's channel never acts as the person")
        fields, claimed = request(event, req)
        return self._append(actor, event, fields, claimed, source=source)

    def import_item(self, actor: Actor, req: dict) -> dict:
        """An item brought in from elsewhere (slice 6's seed): a create marked source "import", which can never be the
        person's act and carries no state (the attack, finding 10 and F13)."""
        return self.write(actor, "create", req, source="import")

    def person_act(self, session: str, req: dict) -> dict:
        """The person's act, found in their own turn: the session is the kernel channel's, never the caller's, and the
        turn is read by self.turns (TranscriptTurns), never sent."""
        fields, claimed = request("person_act", req)
        value = fields.get("value")
        if fields["act"] == "clauses":
            value = clauses_hash(fields.get("clauses") or [])
        turn = self.turns.turn(session) if self.turns is not None else None
        evidence = check_turn(turn, fields["id"], fields["act"], value, self.clock(), self.transcript_roots)
        return self._append(Actor(PERSON, "bound", "person", session), "person_act", fields, claimed,
                            evidence=evidence)

    def _append(self, actor, event, fields, claimed, *, source=None, evidence=None) -> dict:
        self._contained()
        if actor.assurance not in ("bound", "claimed", "observed", "fallback") or not SEAT_RE.fullmatch(actor.who):
            raise WorkRefused("MALFORMED", "the actor is not one the kernel knows how to stamp")
        if event == "create" and fields["project"] not in self.projects():
            raise WorkRefused("UNKNOWN_ID", f"{fields['project']!r} is not a project in the seats or projects file")
        seats = self.seats()
        for k in ("reviewer", "to_seat"):
            if k in fields and seats is not None and fields[k] not in seats:
                raise WorkRefused("UNKNOWN_ID", f"{fields[k]!r} is not a seat")
        if event == "person_act" and fields["act"] == "assign" and seats is not None and fields.get("value") not in seats:
            raise WorkRefused("UNKNOWN_ID", "the person assigns to a seat")
        out: dict = {}

        def check(tail):
            self._adopt(tail)
            st = self._folded(tail.raw, self._head())
            if not st["intact"]:
                raise WorkRefused("CONFLICT", "the store does not match its head (cut, edited or reordered), so "
                                              "nothing more is written until it has been looked at")
            now = self.clock()
            rec = {"v": VERSION, "event": event, "who": actor.who, "assurance": actor.assurance,
                   "channel": actor.channel, "at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), **fields, **claimed}
            if evidence is not None:
                rec["evidence"] = evidence
            if source is not None:
                rec["source"] = source
            if event == "create":
                n = st["minted"].get(fields["project"], 0) + 1
                if n > 999999:
                    raise WorkRefused("STORE_FULL", "the project has used every item number")
                rec["id"] = f"W-{fields['project']}-{n}"
            self._repeat(st, actor, rec, out)
            self._limits(st, tail, actor, now)
            out.update(self._dry_run(st, event, fields, rec))
            sealed = seal(rec, st["end"]["seq"] + 1, st["end"]["hash"])
            line = line_of(sealed)
            if len(line.encode("utf-8")) > MAX_LINE:
                raise WorkRefused("MALFORMED", f"the event is over {MAX_LINE // 1024} KB")
            out.update(rec=sealed, line=line)
            # before the line: what it is and the head it extends, so a head write that fails after the line is synced
            # leaves a line the next append can adopt, and only that one
            store.write_atomic(self.pending_path, json.dumps({"hash": sealed["hash"], "head": dict(st["end"])}))

        def head(tail, text):
            store.write_atomic(self.head_path, json.dumps({"seq": out["rec"]["seq"], "hash": out["rec"]["hash"]}))
            # the pending record is left as it is: it names the head's own line now, which _adopt passes over

        try:
            store.append_checked(self.path, check, lambda tail: out["line"], after=head)
        except _Same as same:
            return same.result
        rec = out["rec"]
        return {"id": rec.get("id") or fields.get("id"), "seq": rec["seq"], "applied": not out["proposal"],
                "proposal": out["proposal"], "item": out["item"], "assurance": actor.assurance}

    def _adopt(self, tail) -> None:
        """Under the lock, before anything is decided: when the pending record names a line that is in the log, whose
        own hash is the pending hash, and that chains to the head the pending record names (that head being the head
        now), the head is moved to it; the line the writer wrote and could not put its head on is on the chain. Any
        other line past the head is never adopted (the attack, A11). A pending record that can no longer be adopted
        (its line is not there, or the head is elsewhere) is cleared. Whoever can write the pending record can write
        the head itself, so this opens nothing that was closed."""
        try:
            got = jsonread.loads(self.pending_path.read_text(encoding="utf-8")) if self.pending_path.is_file() else None
        except (OSError, ValueError):
            got = None
        if not isinstance(got, dict) or not got:
            return
        try:
            head = self._head_strict()
        except OSError:   # the head could not be read now: the pending record is kept, and nothing is decided on it
            raise WorkRefused("CONFLICT", "the store's head could not be read just now; try again") from None
        want, base = got.get("hash"), got.get("head")
        if head is not None and head.get("hash") == want:
            return                 # the usual case: the head was written, and names the pending line itself
        if head is None and not self.head_path.exists():
            head = {"seq": 0, "hash": GENESIS}   # the first line's head write failed: it extends the chain's start
        if isinstance(want, str) and isinstance(base, dict) and head is not None and \
                (head.get("seq"), head.get("hash")) == (base.get("seq"), base.get("hash")):
            for text in reversed(tail.lines):
                rec, _, own = parse_line(text)
                if rec is not None and own and rec.get("hash") == want and rec.get("seq") == head["seq"] + 1 and \
                        rec.get("prev") == head["hash"]:
                    store.write_atomic(self.head_path, json.dumps({"seq": rec["seq"], "hash": rec["hash"]}))
                    break
        store.write_atomic(self.pending_path, "{}")   # adopted, or never adoptable: either way it is done with

    def _repeat(self, st, actor, rec, out):
        key = rec.get("request_key")
        if key is None:
            return
        prior = st["keys"].get((actor.who, key))
        if prior is None:
            return
        from .fold import _req_hash
        if prior[1] != _req_hash(rec):
            raise WorkRefused("CONFLICT", "this request_key was used for another request")
        row = next(r for r in st["events"] if r["seq"] == prior[0])
        raise _Same({"id": row["id"], "seq": prior[0], "applied": row["applied"], "proposal": row["code"] ==
                     "PROPOSAL", "item": copy.deepcopy(st["items"].get(row["id"])), "assurance": actor.assurance, "repeat": True})

    def _limits(self, st, tail, actor, now):
        if tail.size > self.cap:
            raise WorkRefused("STORE_FULL", f"the work store is over {self.cap} bytes")
        # the kernel's stamps are fixed-width UTC text, so text order is time order: no parsing per event. Every
        # event of the last minute is counted, however many other actors wrote in it (G6, finding 11): back from the
        # newest of the writer's own lines (on the chain) to the first one older than the minute
        since = (now - timedelta(seconds=59)).strftime("%Y-%m-%dT%H:%M:%SZ")
        until = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        recent = 0
        for row in reversed(st["events"]):
            at = row["at"]
            if not row["on_chain"] or not isinstance(at, str):
                continue
            if at < since:
                break
            recent += row["who"] == actor.who and at <= until
        if recent >= self.rate:
            raise WorkRefused("RATE_LIMIT", f"{actor.who} wrote {recent} events in the last minute")

    def _dry_run(self, st, event, fields, rec) -> dict:
        """The rules on a copy of what the event touches: the same table the fold will apply."""
        def attempt(assurance):
            items = dict(st["items"]) if event == "create" else \
                {fields["id"]: copy.deepcopy(st["items"][fields["id"]])} if fields["id"] in st["items"] else {}
            apply(items, event, fields, {**rec, "seq": st["end"]["seq"] + 1}, assurance, self.parked,
                  set(st["acts"]))
            return items.get(rec.get("id") or fields.get("id"))
        try:
            return {"item": attempt(rec["assurance"]), "proposal": False}
        except Refuse as e:
            if e.code != "NOT_BOUND":
                raise WorkRefused(e.code, e.reason) from None
        try:
            attempt("bound")      # would a bound seat be allowed this? then it is written as a proposal
        except Refuse as e:
            raise WorkRefused(e.code, e.reason) from None
        return {"item": copy.deepcopy(st["items"].get(fields.get("id"))), "proposal": True}

    def _contained(self):
        """The containment set before a write: no link or junction from the store folder up to the home, at the log or
        the head; no second hard link."""
        home = self.home
        for p in [self.path, self.head_path, self.pending_path, self.dir, *self.dir.parents]:
            if p.exists() or p.is_symlink():
                if _linked(p) or (p.is_file() and os.stat(p).st_nlink > 1):
                    raise WorkRefused("CONFLICT", f"{p} is a link, a junction or a second hard link; the work store "
                                                  f"is never written through one")
            if p == home:
                break
        for name in (self.path.name, self.head_path.name, self.pending_path.name):
            if ":" in name:
                raise WorkRefused("CONFLICT", "an alternate stream is never the work store")


def _linked(p: Path) -> bool:
    """A symbolic link, or a Windows junction or other link (a reparse point whose tag names another place), read
    from lstat so it holds on every Python: Path.is_junction is 3.12's. One that cannot be examined counts as a link."""
    try:
        st = os.lstat(p)
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                and getattr(st, "st_reparse_tag", 0) & 0x20000000)   # the name-surrogate bit: names another place


def _span_same(rec, roots) -> bool:
    """The act's span still reads, and its bytes are still the ones recorded (their sha256)."""
    sp = rec.get("evidence", {}).get("span") if isinstance(rec.get("evidence"), dict) else None
    if not isinstance(sp, dict) or set(sp) != set(span.SPAN_KEYS):
        return False
    data = span.read_span(sp["path"], sp["offset"], sp["length"], roots)
    return data is not None and hashlib.sha256(data).hexdigest() == sp["sha256"]


def _lines(data: bytes) -> list[str]:
    return [p.decode("utf-8", errors="replace") for p in data.split(b"\n")[:-1]]


def _with_torn(st: dict, torn, n_lines: int) -> dict:
    if torn is not None:
        st["problems"].append({"line": n_lines + 1, "kind": "torn", "text": "a torn last line (no newline), dropped"})
    return st


class _Same(Exception):
    def __init__(self, result):
        super().__init__("a repeated request")
        self.result = result
