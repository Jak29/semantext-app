"""The Waiting place: what your agents have asked of you, read the way your own inbox reads it.

An agent that needs your word files a request: one JSON object a line, appended to its requests file in the agent's own
home folder (requests.jsonl, unless the config's "requests" key names another file). A request is a decision (a question and its options) or a command (what to run, what it does, how to undo it).
A proposed change (change.py) is a record, not an ask, and lives in its own file beside the requests file
(changes.jsonl, unless the config's "changes" key names another), with its outcomes; a change line or an outcome in
the requests file is a problem that says so. A decision card may name a change by its id ("change": id), and is then
the ask for it; an id that names no change read here is a problem, never a silent link.
A line with a "close" field closes the request it names. A command you ran is noted in runs.jsonl and a card you parked
in parked.jsonl, both in the shared inbox folder.

This reader folds those files into cards, each waiting, parked, closed or run, and only ever opens files for reading.
It takes every file as your own inbox does, so that what it shows is what the inbox shows: a request file that is not
all UTF-8 is not read at all, a number too large for a float is not JSON, a line of runs.jsonl that is not a whole run
record is not a run, and a line of parked.jsonl is parsed as it stands. Every line it cannot use is a problem in the
result, never silence: a line that is not JSON, a field that is missing, an id used twice (the first stands), a closing
that names no request, a parking it does not know. A card that is still shown but has something wrong in it (no "does",
a hidden character in its command) carries a problem too, marked "shown". Which agent a card is from comes from the home
folder in the seats file, never from a field in the line. A card that has run is never waiting, whether or not anyone
has closed it.
"""
from __future__ import annotations

import json
import os
import re
import stat
import unicodedata
from pathlib import Path

from .. import jsonread
from ..pathrule import SeatsUnread, read_seats
from . import MAX_LINE, change, home_base, problem, under
from .places import _linked

FILE = "requests.jsonl"      # each agent's requests file in its home; the config's "requests" key can name another
FILE_CAP = 5 * 1024 * 1024   # the inbox leaves a bigger file unread until it is trimmed
MAX_DEPTH = jsonread.INBOX_DEPTH   # the deepest nesting the inbox reads in a request, a parking or the seats file
STATES = ("waiting", "parked", "closed", "run")
KINDS = ("decision", "command")
REQUIRED = {"decision": ("id", "at", "title", "why", "question"), "command": ("id", "at", "title", "why", "command")}
CHANGES = "changes.jsonl"    # each agent's proposed changes in its home (change.py); the config's "changes" key renames it
ELSEWHERE = "belongs in changes.jsonl"
ASKS = "the agent whose home folder holds the line, from the seats file; a field in the line is never read"
ACTS = ("by a rule in the decision register, a card whose act another agent performs is filed by that agent, so the "
        "agent whose home holds the line is the one that acts; the line itself does not say who acts")
BOM = chr(0xFEFF)
# What the inbox trims from a line and from a text field: Unicode white space. str.strip() trims four more characters
# (U+001C to U+001F), and a line of only those is not blank to the inbox: it is not JSON.
SPACE = "".join(map(chr, (*range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B),
                          0x2028, 0x2029, 0x202F, 0x205F, 0x3000)))
# Characters that can make a command's text differ from what runs: direction marks and overrides, zero-width and
# soft-hyphen characters, a byte-order mark inside the text. The inbox will not run such a command; this reader shows
# it with a note. Control characters other than tab and line breaks count too (see _hidden).
HIDDEN = {*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), *range(0x2066, 0x206A),
          0xFEFF, 0xAD, 0x61C, 0x180E}


class _Refused(Exception):
    """A line that cannot be used, and which kind of problem it is."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind, self.text = kind, text


def _text(v: dict, key: str) -> str | None:
    """A text field as the inbox reads it: a string, trimmed, and not empty. Anything else counts as missing."""
    x = v.get(key)
    return (x.strip(SPACE) or None) if isinstance(x, str) else None


def _hidden(*texts: str | None) -> str | None:
    """The first character in these texts that could make the text shown differ from the text that runs, as "U+202E", or
    None."""
    for text in texts:
        for ch in text or "":
            if ord(ch) in HIDDEN or (unicodedata.category(ch) == "Cc" and ch not in "\t\n\r"):
                return f"U+{ord(ch):04X}"
    return None


# ---------------------------------------------------------------------------------------------------- lines
def _lines(text: str) -> list[tuple[int, str]]:
    """(number, line) for every line of a file's text, blank ones too, split as the inbox splits: at a line feed, with
    one carriage return before it going with it. A carriage return on its own is part of the line."""
    parts = text.split("\n")
    last = parts.pop()   # what follows the final line feed: the last line when it has no line feed, else nothing
    lines = [p[:-1] if p.endswith("\r") else p for p in parts]
    if last:
        lines.append(last)
    return list(enumerate(lines, 1))


def _blank(line: str) -> bool:
    return not line.strip(SPACE)


# ---------------------------------------------------------------------------------------------------- JSON
# The inbox's strict reading lives in jsonread (inbox_loads), so the seats file is read by it everywhere, the
# card hook included; the names this module has always used for it stay here.
_parse = jsonread.inbox_loads
_STRING, _WS, _nesting = jsonread._STRING, jsonread._WS, jsonread._nesting


# ---------------------------------------------------------------------------------------------------- seats
def _seats(path: str, problems: list, group: str | None = None) -> list[dict]:
    """The agents in the seats file, each with the folder its requests are in. With a group, only the agents in that
    group, as the inbox reads only its own group's: the others are left out and not mentioned. A home that is empty, that
    holds a NUL character, or that pathrule.under refuses is a problem and is not followed. The base is judged by
    pathrule.home_base and each home joined to it by pathrule.under, as the places and gates readers and the card hook
    judge and join them, so one spelling is one folder to all of them, or refused by all of them.

    A seats file that cannot be read, or holds no table of seats, gives no seats. A base that is missing, refused or
    not an existing folder drops the HOMES, never the seats: every seat is still listed, with no home, and the base's
    problem is said once (as the places reader does), so a check of who is a seat never finds the list empty because
    the base was wrong."""
    where = Path(path)
    try:
        data = read_seats(where)   # read one way by every reader and the card hook: a key twice, no seats
    except SeatsUnread as e:
        problems.append(problem(where, None, "seats file", f"cannot be read ({e})"))
        return []
    table = data.get("seats") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        problems.append(problem(where, None, "seats file", "it needs a table of seats"))
        return []
    base, why = home_base(data.get("base"))   # given, read exactly as written, an existing folder; else no home
    if base is None:
        problems.append(problem(where, None, "seats file", why))
    out = []
    for name in sorted(table):
        entry = table[name] if isinstance(table[name], dict) else {}
        groups, home = entry.get("groups"), entry.get("home")
        names = [g for g in groups if isinstance(g, str)] if isinstance(groups, list) else []
        if group is not None and group not in names:
            continue
        row = {"seat": name, "groups": names, "home": None}
        out.append(row)
        if base is None:   # no home is read without a base; said once, above
            continue
        if not (isinstance(home, str) and home.strip()):
            problems.append(problem(where, None, "seats file",
                                    f"{name} has no home folder, so its requests are not read"))
            continue
        if "\x00" in home:
            problems.append(problem(where, None, "seats file",
                                    f"{name}'s home holds a NUL character, so its requests are not read"))
            continue
        full, why = under(base, home)   # the one join the places and gates readers make too, so all three agree
        if full is None:
            problems.append(problem(where, None, "seats file", f"{name}'s home: {why}, so its requests are not read"))
        else:
            row["home"] = full
            if not Path(row["home"]).is_dir():
                problems.append(problem(where, None, "seats file",
                                        f"{name}'s home folder {row['home']} does not exist"))
    return out


# ---------------------------------------------------------------------------------------------------- requests
def _options(v: dict) -> tuple[list[str], tuple[str, str] | None]:
    """A decision's options, and the problem with them if there is one. Only text is kept, as the inbox does."""
    if "options" not in v:
        return [], ("missing field", "it has no options")
    if not isinstance(v["options"], list):
        return [], ("bad field", "its options are not a list")
    kept = [o for o in v["options"] if isinstance(o, str)]
    left_out = len(v["options"]) - len(kept)
    return kept, ("bad field", f"{left_out} of its options are not text, and are left out") if left_out else None


def _card(v: dict) -> tuple[dict, list[tuple[str, str]]]:
    """A request as the inbox reads it, and the problems that leave it still shown. A line that cannot be a card is
    refused. A missing does, undo or options is a problem too, and so is a command or folder with a hidden character in
    it, but the card stays: something is waiting on you."""
    kind = _text(v, "kind")
    if kind is None:
        raise _Refused("missing field", "it has no kind")
    if kind == "change":
        raise _Refused(ELSEWHERE, "it is a change record, which " + ELSEWHERE + " in the same folder; a change that "
                                  "needs your word is asked by a decision card naming its id")
    if kind not in KINDS:
        raise _Refused("unknown kind", f"its kind {kind[:40]!r} is neither decision nor command")
    missing = [k for k in REQUIRED[kind] if _text(v, k) is None]
    if missing:
        raise _Refused("missing field", "it has no " + ", ".join(missing))
    decision = kind == "decision"
    card = {"id": _text(v, "id"), "kind": kind, "title": _text(v, "title"), "why": _text(v, "why"),
            "question": _text(v, "question") if decision else None, "options": [],
            "command": None if decision else _text(v, "command"), "does": None if decision else _text(v, "does"),
            "undo": None if decision else _text(v, "undo"), "cwd": None if decision else _text(v, "cwd"),
            "at": _text(v, "at")}
    if decision:
        card["options"], bad = _options(v)
        card["change_id"] = _text(v, "change")   # the id of a change record this decision asks about, if it names one
        return card, [bad] if bad else []
    absent = [k for k in ("does", "undo") if card[k] is None]
    noted = [("missing field", "it has no " + ", ".join(absent))] if absent else []
    hidden = _hidden(card["command"], card["cwd"])
    if hidden:
        noted.append(("hidden character", f"its command or folder holds an invisible or direction-changing character "
                                          f"({hidden}), so the text shown may not be what runs"))
    return card, noted


def _closing(v: dict, n: int, text: str, before: dict | None) -> dict:
    """A closing as the card shows it. A card closed twice shows the later closing, and keeps the earlier ones."""
    kept = [*before["earlier"], {k: before[k] for k in ("at", "how", "line")}] if before else []
    return {"at": _text(v, "at") or "", "how": _text(v, "how") or "", "line": n, "raw": text, "earlier": kept}


class _Requests:
    """One agent's request file, read. Every non-blank line becomes a card, a closing that took effect or a refused line
    with a problem, so tally lines = cards + closings + refused."""

    def __init__(self, seat: str, file: Path | None, problems: list, closures=()):
        self.seat, self.file, self.problems = seat, file, problems
        self.closures = closures   # the person's closed places, as the built-in readers read them (closed.closures)
        self.tally = {"file": str(file) if file else None, "present": False, "lines": 0, "cards": 0, "closings": 0,
                      "refused": 0}

    def refuse(self, n: int, kind: str, text: str) -> None:
        self.tally["refused"] += 1
        self.problems.append(problem(self.file, n, kind, f"{self.seat}: {text}"))

    def note(self, n: int, kind: str, text: str) -> None:
        self.problems.append({**problem(self.file, n, kind, f"{self.seat}: {text} (the card is still shown)"),
                              "shown": True})

    def lines(self) -> list:
        """The file's lines. Nothing when it is not there (an agent that has asked nothing has no file yet), and nothing
        with a problem when it is there but cannot be read. The inbox reads a file whole or not at all: one byte that
        is not UTF-8 and none of it is read.

        A file in a place the person closed is not read, nor one that is a link of any kind: a symbolic link, a
        junction, or a hard link (a file with more than one name), any of which could show another file's lines as this
        agent's cards. The changes file was held to this alone; the requests file was not, so a requests.jsonl hard-linked
        to any readable file was read and shown as that seat's (the Fable review of 70f2d3c, finding 3)."""
        if self.file is None:
            return []
        from .closed import _judge   # here: only a file about to be read needs the closures judged
        if _judge(str(self.file), self.closures):
            return self.unusable(f"{self.file.name} is in a place you closed, so it is not read", "closed-place")
        try:
            st = os.lstat(self.file)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            return self.unusable(f"cannot be examined ({e})")
        if _linked(st):
            self.tally["present"] = True
            return self.unusable(f"{self.file.name} is a link, so it is not read", "link")
        if stat.S_ISREG(st.st_mode) and st.st_nlink > 1:
            self.tally["present"] = True
            return self.unusable(f"{self.file.name} is a hard link (it has {st.st_nlink} names), so it is not read",
                                 "link")
        try:
            size = self.file.stat().st_size
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            return self.unusable(f"cannot be read ({e})")
        self.tally["present"] = True
        if not self.file.is_file():
            return self.unusable(f"{self.file.name} is not a file")
        if size > FILE_CAP:
            return self.unusable(f"{self.file.name} is over 5 MB, so it is not read until it is trimmed")
        try:
            raw = self.file.read_bytes()
        except (OSError, ValueError) as e:
            return self.unusable(f"cannot be read ({e})")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return self.unusable(f"it holds bytes that are not UTF-8 text ({e.reason}, at byte {e.start}), so none of "
                                 f"the file is read", "bad encoding")
        return _lines(text.lstrip(BOM))

    def unusable(self, why: str, kind: str = "file") -> list:
        self.problems.append(problem(self.file, None, kind, f"{self.seat}: {why}"))
        return []

    def cards(self) -> list[dict]:
        cards, seen, closings = [], set(), []
        for n, line in self.lines():
            trimmed = line.strip(SPACE)
            if not trimmed:
                continue
            self.tally["lines"] += 1
            if len(trimmed.encode("utf-8")) > MAX_LINE:   # measured after trimming, in bytes, as the inbox does
                self.refuse(n, "line too long", f"longer than {MAX_LINE // 1024} KB, so skipped")
                continue
            try:
                v = _parse(trimmed)
            except ValueError as e:
                self.refuse(n, "bad json", f"not JSON ({e})")
                continue
            if not isinstance(v, dict):
                self.refuse(n, "not an object", "it is JSON, but not an object")
                continue
            if _text(v, "close"):
                closings.append((n, line, _text(v, "close"), v))
                continue
            if _text(v, "outcome"):
                self.refuse(n, ELSEWHERE, "it is the outcome of a change, which " + ELSEWHERE + " in the same folder")
                continue
            try:
                card, notes = _card(v)
            except _Refused as e:
                self.refuse(n, e.kind, e.text)
                continue
            if card["id"] in seen:
                self.refuse(n, "duplicate id", f"the id {card['id']} is used twice, and the first stands")
                continue
            seen.add(card["id"])
            self.tally["cards"] += 1
            cards.append({"seat": self.seat, **card, "state": "waiting", "closing": None, "run": None,
                          "parked_at": None, "asks": self.seat, "asks_basis": ASKS, "acts": self.seat,
                          "acts_basis": ACTS, "line": n, "raw": line})
            for kind, why in notes:
                self.note(n, kind, why)
        self.close(cards, closings)
        return cards

    def close(self, cards: list[dict], closings: list) -> None:
        """Apply the closings once every request is read, so a closing may come before its card."""
        by_id = {c["id"]: c for c in cards}
        for n, line, wanted, v in closings:
            card = by_id.get(wanted)
            if card is None:
                self.refuse(n, "closing with no card", f"a closing names {wanted}, which is not one of its requests")
                continue
            self.tally["closings"] += 1
            card["closing"] = _closing(v, n, line, card["closing"])


class _Changes(_Requests):
    """One agent's changes file (change.py), read: each change line a record, each outcome line one more entry on the
    record it names, in file order, never an edit. The agent is the folder that holds the file; a seat field in a line
    is never read for it (one that disagrees is said, and the folder stands). Read whole or not at all, as a requests
    file is; tally lines = records + outcomes + refused."""

    def __init__(self, seat: str, file: Path | None, problems: list, closures=()):
        super().__init__(seat, file, problems, closures)
        self.tally = {"file": str(file) if file else None, "present": False, "lines": 0, "records": 0, "outcomes": 0,
                      "refused": 0}

    # lines() is a requests file's: a link of any kind, or a file in a closed place, is not read

    def records(self) -> list[dict]:
        records, seen, outcomes = [], set(), []
        for n, line in self.lines():
            trimmed = line.strip(SPACE)
            if not trimmed:
                continue
            self.tally["lines"] += 1
            if len(trimmed.encode("utf-8")) > MAX_LINE:
                self.refuse(n, "line too long", f"longer than {MAX_LINE // 1024} KB, so skipped")
                continue
            try:
                v = _parse(trimmed)
            except ValueError as e:
                self.refuse(n, "bad json", f"not JSON ({e})")
                continue
            if not isinstance(v, dict):
                self.refuse(n, "not an object", "it is JSON, but not an object")
                continue
            if _text(v, "outcome"):
                outcomes.append((n, _text(v, "outcome"), v))
                continue
            if _text(v, "kind") != "change":
                self.refuse(n, "not a change", "a changes file holds change records and their outcomes only")
                continue
            missing = [k for k in change.REQUIRED if _text(v, k) is None]
            if missing:
                self.refuse(n, "missing field", "it has no " + ", ".join(missing))
                continue
            rid = _text(v, "id")
            if rid in seen:
                self.refuse(n, "duplicate id", f"the id {rid} is used twice, and the first stands")
                continue
            seen.add(rid)
            own, notes = change.fields(v)
            said = _text(v, "seat")
            if said is not None and said != self.seat:
                notes.append(("seat field", f"its seat field says {said[:40]!r}; the folder says {self.seat}, and the "
                                            f"folder stands"))
            self.tally["records"] += 1
            records.append({"seat": self.seat, "id": rid, "kind": "change", "title": _text(v, "title"),
                            "why": _text(v, "why"), "at": _text(v, "at"), "change": own, "outcomes": [],
                            "asked_in": [], "line": n, "raw": line})
            for kind, why in notes:
                self.note(n, kind, why)
        self.attach(records, outcomes)
        return records

    def attach(self, records: list[dict], outcomes: list) -> None:
        """Each outcome onto its record, as one more entry: never an edit, and an undo is a later outcome."""
        by_id = {r["id"]: r for r in records}
        for n, wanted, v in outcomes:
            record = by_id.get(wanted)
            if record is None:
                self.refuse(n, "outcome with no change", f"an outcome names {wanted}, which is not one of its changes")
                continue
            got, why = change.outcome(v)
            if got is None:
                self.refuse(n, "bad outcome", f"the outcome of {wanted}: {why}")
                continue
            self.tally["outcomes"] += 1
            record["outcomes"].append({**got, "line": n})
        for record in records:
            record["judged"] = change.judged(record["change"], record["outcomes"])


# ---------------------------------------------------------------------------------------------------- runs
# A run record is read as the inbox reads it: a JSON object (or an array of its nine fields in order) whose seat, id and
# started are text, whose finished is text or null, whose exit is a 32-bit whole number or null, whose timed_out is true
# or false, and whose stdout, stderr and command are text; a field twice is an error. A field it does not know is
# skipped as JSON and nothing more: its numbers are not checked for range, its text for surrogates, or its nesting for
# depth. Python's parser cannot read that way, so the record is read here, a token at a time.
_FIELDS = ("seat", "id", "started", "finished", "exit", "timed_out", "stdout", "stderr", "command")
_FIELD_KINDS = {"seat": ("str",), "id": ("str",), "started": ("str",), "finished": ("str", "null"), "exit": ("int", "null"),
          "timed_out": ("bool",), "stdout": ("str",), "stderr": ("str",), "command": ("str",)}
_WHAT = {"finished": "text or null", "exit": "a whole number that fits in 32 bits, or null",
         "timed_out": "true or false"}
_NUM_TOKEN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_LITERAL = re.compile(r"true|false|null")


def _ws(text: str, i: int) -> int:
    return _WS.match(text, i).end()


def _string(token: str) -> str:
    """The text of a JSON string token. Half of a surrogate pair is not text."""
    value = jsonread.loads(token)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _Refused("bad json", "it holds half of a surrogate pair") from None
    return value


def _member(text: str, i: int) -> tuple[str, int]:
    """The name token of the object member at i, and the index just after the colon that follows it."""
    m = _STRING.match(text, i)
    if not m:
        raise _Refused("bad json", "a member of an object has no name, or its name is cut off")
    j = _ws(text, m.end())
    if text[j:j + 1] != ":":
        raise _Refused("bad json", "a member of an object has no colon after its name")
    return m.group(), j + 1


def _skip_value(text: str, i: int) -> int:
    """The index just after the JSON value that starts at i, its syntax checked and nothing else, at any depth."""
    closers: list[str] = []   # the containers the scan is inside, as the character that closes each
    while True:
        i = _ws(text, i)
        c = text[i:i + 1]
        if c in ("{", "["):
            closer = "}" if c == "{" else "]"
            j = _ws(text, i + 1)
            if text[j:j + 1] != closer:
                closers.append(closer)
                i = _member(text, j)[1] if c == "{" else j
                continue
            i = j + 1   # an empty container is a whole value
        else:
            m = _STRING.match(text, i) or _NUM_TOKEN.match(text, i) or _LITERAL.match(text, i)
            if not m:
                raise _Refused("bad json", "it is not JSON")
            i = m.end()
        while True:   # a value has ended: it may end the containers it is in, or be followed by another member
            if not closers:
                return i
            i = _ws(text, i)
            c = text[i:i + 1]
            if c == ",":
                i += 1
                if closers[-1] == "}":
                    i = _member(text, _ws(text, i))[1]
                break
            if c != closers[-1]:
                raise _Refused("bad json", "it is not JSON")
            closers.pop()
            i += 1


def _field(key: str, text: str, i: int) -> tuple[object, int]:
    """The value of the field `key` of a run record, which starts at i, checked against the field's type, and the index
    after it."""
    c = text[i:i + 1]
    if c in ("{", "["):
        kind, value, end = "container", None, i
    elif m := _STRING.match(text, i):
        kind, value, end = "str", _string(m.group()), m.end()
    elif m := _LITERAL.match(text, i):
        kind, value, end = ("null", None, m.end()) if m.group() == "null" else ("bool", m.group() == "true", m.end())
    elif m := _NUM_TOKEN.match(text, i):
        whole = not re.search(r"[.eE]", m.group()) and m.group() != "-0"   # the inbox's parser reads -0 as a float
        kind, value, end = ("int", int(m.group()) if len(m.group()) < 40 else None, m.end()) if whole \
            else ("float", None, m.end())
    else:
        raise _Refused("bad json", "it is not JSON")
    if kind not in _FIELD_KINDS[key]:
        raise _Refused("bad run record", f"its {key} is not {_WHAT.get(key, 'text')}")
    if key == "exit" and kind == "int" and (value is None or not -2 ** 31 <= value < 2 ** 31):
        raise _Refused("bad run record", f"its {key} is not {_WHAT[key]}")
    return value, end


def _record_object(text: str, i: int) -> tuple[dict, int]:
    """The fields of a run record written as an object, i being just after its opening brace, and the index after it."""
    got: dict = {}
    i = _ws(text, i)
    if text[i:i + 1] == "}":
        return got, i + 1
    while True:
        token, i = _member(text, i)
        key = _string(token)
        i = _ws(text, i)
        if key in _FIELDS:
            if key in got:
                raise _Refused("bad run record", f"its {key} appears twice")
            got[key], i = _field(key, text, i)
        else:
            i = _skip_value(text, i)
        i = _ws(text, i)
        c = text[i:i + 1]
        if c not in (",", "}"):
            raise _Refused("bad json", "it is not JSON")
        i += 1
        if c == "}":
            return got, i
        i = _ws(text, i)


def _record_array(text: str, i: int) -> tuple[dict, int]:
    """The fields of a run record written as an array of them in order, i being just after its opening bracket, and
    the index after it."""
    got: dict = {}
    i = _ws(text, i)
    if text[i:i + 1] == "]":
        return got, i + 1
    while True:
        if len(got) == len(_FIELDS):
            raise _Refused("bad json", "an array has more than the nine fields of a run record")
        key = _FIELDS[len(got)]
        got[key], i = _field(key, text, i)
        i = _ws(text, i)
        c = text[i:i + 1]
        if c not in (",", "]"):
            raise _Refused("bad json", "it is not JSON")
        i += 1
        if c == "]":
            return got, i
        i = _ws(text, i)


def _run_record(line: str) -> dict:
    """One line of runs.jsonl as the inbox keeps it ({seat, id, started, finished, exit, timed_out}), or a _Refused
    saying what is wrong with it."""
    i = _ws(line, 0)
    c = line[i:i + 1]
    if c == "{":
        got, end = _record_object(line, i + 1)
    elif c == "[":
        got, end = _record_array(line, i + 1)
    else:
        _skip_value(line, i)   # if it is not JSON at all, that is the problem; if it is, it is JSON of another shape
        raise _Refused("bad run record", "it is not a JSON object")
    if _ws(line, end) != len(line):
        raise _Refused("bad json", "there is more after the record")
    absent = [k for k in _FIELDS[:3] if k not in got]
    if absent:
        raise _Refused("bad run record", "it has no " + ", ".join(absent))
    return {"seat": got["seat"], "id": got["id"], "started": got["started"], "finished": got.get("finished"),
            "exit": got.get("exit"), "timed_out": got.get("timed_out", False),
            "stdout": got.get("stdout") or "", "stderr": got.get("stderr") or ""}


def _log(path: Path, problems: list, consequence: str) -> str | None:
    """The text of a shared log, or None: when it is not there, which is nothing to report, or when it cannot be read,
    which is a problem. The inbox reads a log whole or not at all, so one byte that is not UTF-8 means none of it is
    read."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        problems.append(problem(path, None, "file", f"cannot be read ({e}), so {consequence}"))
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        problems.append(problem(path, None, "bad encoding", f"it holds bytes that are not UTF-8 text ({e.reason}, at "
                                                            f"byte {e.start}), so none of it is read and {consequence}"))
        return None


def _runs(path: Path, problems: list, outputs: dict | None = None) -> tuple[dict, int]:
    """The runs so far, by (agent, id), and how many lines the log has. A started line comes first and the result
    after it, so the later good line for a request replaces the earlier one. A line the inbox cannot read as a run record
    is a problem and no run, and never replaces a record before it. The log is read without the line limit and without
    dropping a byte-order mark: a record holds a command's output and can be long, and the inbox has no limit. Each
    run's stdout and stderr, as the inbox shows them under Output, go into `outputs` by the same key when it is given."""
    out: dict[tuple[str, str], dict] = {}
    text = _log(path, problems, "a card that has run may show as waiting")
    if text is None:
        return out, 0
    count = 0
    for n, line in _lines(text):
        if _blank(line):
            continue
        count += 1
        try:
            record = _run_record(line)
        except _Refused as e:
            problems.append(problem(path, n, e.kind, f"{e.text}, so a card that has run may show as waiting"))
            continue
        out[(record["seat"], record["id"])] = {k: record[k] for k in ("started", "finished", "exit", "timed_out")}
        if outputs is not None:
            outputs[(record["seat"], record["id"])] = {"stdout": record["stdout"], "stderr": record["stderr"]}
    return out, count


# ---------------------------------------------------------------------------------------------------- parking
def _parked(path: Path, problems: list) -> tuple[dict, dict, list]:
    """What is parked, from an append-only log whose latest event for a card wins: the cards parked now by (agent, id),
    the register decisions brought back by id, and every event understood as (line, agent, id), with no agent for a
    register decision, so the caller can check each names a card. Read as the inbox reads it: every byte-order mark at
    the start dropped, no limit on a line's length, and a line parsed as it stands (only JSON white space around it)."""
    cards: dict[tuple[str, str], str] = {}
    back: dict[str, str] = {}
    events: list[tuple[int, str | None, str]] = []
    text = _log(path, problems, "no parking is shown")
    if text is None:
        return cards, back, events
    for n, line in _lines(text.lstrip(BOM)):
        if _blank(line):
            continue
        try:
            v = _parse(line)
        except ValueError as e:
            problems.append(problem(path, n, "bad json", f"not JSON ({e})"))
            continue
        v = v if isinstance(v, dict) else {}
        event, seat, wanted, register = (_text(v, k) for k in ("event", "seat", "id", "register"))
        at = _text(v, "at") or ""
        if event in ("park", "back") and seat and wanted and register is None:
            events.append((n, seat, wanted))
            if event == "park":
                cards[(seat, wanted)] = at
            else:
                cards.pop((seat, wanted), None)
        elif event == "back" and seat is None and wanted is None and register:
            events.append((n, None, register))
            back[register] = at
        else:
            problems.append(problem(path, n, "unknown parking", "it is not a parking this reader knows"))
    return cards, back, events


def _link(cards: list[dict], records: list[dict], requests: _Requests) -> None:
    """A decision card that names a change of the same agent asks about it: each is linked to the other. An id that
    names no change of that agent is a problem on the card's line, and nothing is linked."""
    by_id = {r["id"]: r for r in records}
    for c in cards:
        wanted = c.get("change_id")
        if not wanted:
            continue
        record = by_id.get(wanted)
        if record is None:
            requests.note(c["line"], "unknown change", f"{c['id']} names the change {wanted[:60]}, which is not one of "
                                                       f"its changes")
            c["change_id"] = None
            c["change_unknown"] = wanted
            continue
        record["asked_in"].append(c["id"])


def _state(card: dict) -> str:
    if card["run"]:
        return "run"
    if card["closing"]:
        return "closed"
    return "waiting" if card["parked_at"] is None else "parked"


def load(cfg: dict) -> dict:
    """Every agent's requests as cards, from the config's "seats" file and "inbox" folder (and its "group", when it has
    one: then only the agents in that group are read, as the inbox reads only its own).

    Without both keys: {"off": True, "missing": [the keys], "problems": []}. Otherwise a dict with
      seats     one row per agent in the seats file: seat, groups, home, file, present, lines, cards, closings, refused
      cards     seat, id, kind, title, why, question, options, command, does, undo, cwd, at, state (waiting, parked,
                closed or run), closing {at, how, line, raw, earlier} or None, run {started, finished, exit, timed_out}
                or None, output {stdout, stderr} (the run's, as text) or None, parked_at, asks and acts (the agent) with asks_basis and acts_basis, line and raw (the line's
                number and exact text). A decision has a question and options, a command has command, does, undo, cwd
      counts    cards, by_state and by_seat
      runs      lines in the log, cards it names, and how many of those are no card read here
      parking   events understood, cards parked now, parkings on cards that are done, decisions_back {id: when}
      problems  every line or file that could not be used: source, line (or None), kind and text. The kinds are seats file,
                inbox folder, file, line too long, bad json, not an object, missing field, unknown kind, bad field,
                bad encoding (a file with a byte that is not UTF-8, which is read not at all), hidden character,
                duplicate id, closing with no card, bad run record, unknown parking and parking with no card. One that
                left its card shown has "shown": True
    A card that has run is "run" even when it is also closed: the run is the thing that happened. A run is only a line of
    runs.jsonl the inbox reads as a run record; a line it refuses is a problem here and leaves its card as it was."""
    missing = [k for k in ("seats", "inbox") if not cfg.get(k)]
    if missing:
        return {"off": True, "missing": missing, "problems": []}
    problems: list[dict] = []
    group = cfg["group"] if isinstance(cfg.get("group"), str) and cfg["group"] else None
    agents = _seats(cfg["seats"], problems, group)
    name = cfg["requests"] if isinstance(cfg.get("requests"), str) and cfg["requests"].strip() else FILE
    if Path(name).name != name:
        problems.append(problem(name, None, "bad field", "the requests key names a file, not a path; using " + FILE))
        name = FILE
    inbox = Path(cfg["inbox"])
    runs, run_lines, parked, back, events, outputs = {}, 0, {}, {}, [], {}
    if inbox.is_dir():
        runs, run_lines = _runs(inbox / "runs.jsonl", problems, outputs)
        parked, back, events = _parked(inbox / "parked.jsonl", problems)
    else:
        problems.append(problem(inbox, None, "inbox folder", "it is not a folder, so no run or parking is read"))
    kept = cfg["changes"] if isinstance(cfg.get("changes"), str) and cfg["changes"].strip() else CHANGES
    if Path(kept).name != kept:
        problems.append(problem(kept, None, "bad field", "the changes key names a file, not a path; using " + CHANGES))
        kept = CHANGES
    cards: list[dict] = []
    changes: list[dict] = []
    from .closed import closures as _closures   # here: the card hook's status line never reads a requests file
    # read once for every agent, beside the sources file this config came from (as the run reader reads them); None,
    # closures that cannot be read, closes every file
    where = cfg.get("_file")
    shut = _closures(Path(where).parent if isinstance(where, str) and where else None) if agents else ()
    for agent in agents:
        requests = _Requests(agent["seat"], Path(agent["home"]) / name if agent["home"] else None, problems, shut)
        mine = requests.cards()
        cards.extend(mine)
        agent.update(requests.tally)
        records = _Changes(agent["seat"], Path(agent["home"]) / kept if agent["home"] else None, problems, shut)
        theirs = records.records()
        changes.extend(theirs)
        agent["changes"] = {k: records.tally[k] for k in ("file", "present", "lines", "records", "outcomes", "refused")}
        _link(mine, theirs, requests)
    for c in cards:
        key = (c["seat"], c["id"])
        c["run"] = runs.get(key)
        c["output"] = outputs.get(key) if c["run"] else None
        c["parked_at"] = None if c["run"] or c["closing"] else parked.get(key)
        c["state"] = _state(c)
    known = {(c["seat"], c["id"]) for c in cards}
    for n, seat, wanted in events:
        if seat is not None and (seat, wanted) not in known:
            problems.append(problem(inbox / "parked.jsonl", n, "parking with no card",
                                    f"it names {wanted} of {seat}, which is not one of the requests read"))
    by_state = {s: sum(c["state"] == s for c in cards) for s in STATES}
    by_seat = {a["seat"]: {"cards": 0, **{s: 0 for s in STATES}} for a in agents}
    for c in cards:
        by_seat[c["seat"]]["cards"] += 1
        by_seat[c["seat"]][c["state"]] += 1
    return {"off": False, "seats": agents, "cards": cards, "changes": changes,
            "counts": {"cards": len(cards), "by_state": by_state, "by_seat": by_seat},
            "runs": {"lines": run_lines, "cards": len(runs), "unmatched": len(runs.keys() - known)},
            "parking": {"events": len(events), "parked": by_state["parked"],
                        "on_done_cards": sum(k in known for k in parked) - by_state["parked"],
                        "decisions_back": back},
            "problems": problems}
