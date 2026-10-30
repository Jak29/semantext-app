"""The Record: the decisions you have given, read from the register where it lies.

A register is a file of decisions, one per line, kept by a scribe that only adds lines and never edits one. A decision
holds your words as you gave them, whom you said them to, what they were about (its subject), the status they give that
subject (in force, parked or reopened), the scribe's one-line reading of them, and where they were first written down,
pinned to a commit, a file and a line so that a later edit cannot move them. When your words were only a pick or a
"yes", the decision also holds the offer you accepted. A later decision can name earlier ones it supersedes. A second
file holds notes: later additions to one decision, quoting more of what you were offered. A note is the scribe's and
never a decision of yours, and it changes no status.

This reader shows what the register says and works out what the register's own tool works out, and no more:
- the same lines are decisions to both. The file is read as UTF-8 and cut into lines where Python's str.splitlines()
  cuts it (at a line feed, a carriage return, and also at a vertical tab, a form feed, U+001C to U+001E, U+0085, U+2028
  and U+2029); a line holding only white space, of any kind, is skipped; every other line is one decision, however long.
  The tool's own quirks are kept on purpose, so that a link it counts is a link this reader counts: a byte-order mark
  is not skipped, and a line cut in two by U+2028, U+2029 or U+0085 inside your words is two lines that are not JSON;
- a decision is superseded when another names it in `supersedes`, as the tool counts it, whatever the line that names it
  looks like otherwise (a repeated id, no id, an object in place of a list); otherwise its status is the one stored on it
  (parking and reopening are stored statuses; nothing is worked out for them);
- the reverse of `supersedes` is drawn for every link: the tool keeps one superseder per decision, the last, and this
  reader lists them all, the last of them being the tool's;
- a subject's current status is its latest live decision's: the newest, by date and then by place in the file, that
  nothing supersedes;
- a note belongs to the decision it names.
Decisions are grouped by subject into threads, the subject being the exact text of the subject (the tool never merges
subjects), and every card id (a request to you, such as I-20991014-140041) that a decision or its notes mention is listed
with the decisions that mention it, so a request can be shown beside what you said about it before. Your words, the
offer and the reading are passed on exactly as written, and so is any value that is not text (it is reported, and not
changed). Nothing is written back.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .. import jsonread
from . import problem

STATUSES = ("in force", "parked", "reopened")
SUPERSEDED = "superseded"
REQUIRED = ("date", "to", "subject", "status", "words", "reading", "source")   # a decision without one is a problem
NOTE_REQUIRED = ("on", "text", "quote", "source")
CARD_FIELDS = ("subject", "words", "offer", "reading", "source")
# ASCII digits only ([0-9], re.ASCII): \d would take any script's digits, and int() reads them too
PIN = re.compile(r"(?P<repo>[a-z]+)@(?P<commit>[0-9a-f]{7,40}):(?P<file>[^:]+):(?P<line>[0-9]+)(?:-(?P<last>[0-9]+))?",
                 re.ASCII)
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
# A card id as a request to you carries it: one or two capitals, a date, and a time of day, and sometimes a number after
# that (O-20991010-195202-2 is another card than O-20991010-195202, so the number is part of the id). The register's own
# ids start with J and are decisions, not cards. A card is found wherever it stands, unless a letter or a digit touches
# it (xQ-..., ...-1400419, Q-...-12x are not cards); a hyphen, a dot, a slash or an underscore beside it does not stop it,
# since a card is often named inside a file name. The digits are ASCII digits, counted loosely on purpose: a card missed
# is silent, while a stray id in the index costs nothing.
CARD = re.compile(r"(?<![A-Za-z0-9])(?!J-)[A-Z]{1,2}-[0-9]{8}-[0-9]{1,6}(?:-[0-9]{1,3})?(?![A-Za-z0-9])")
BAD_BYTE = re.compile("[\udc80-\udcff]")   # what a byte that is not UTF-8 becomes when the file is decoded for reading
MAX_DEPTH = 64   # no decision nests its values deeper; a line that does is not read, so the answer stays easy to carry


def _blank() -> dict:
    return {"off": False, "notes_off": False, "files": {"register": None, "notes": None}, "entries": [], "threads": [],
            "counts": _counts([], [], 0, {}), "cards": {}, "problems": []}


def _bucket(status) -> str:
    """The name a status is counted under: its text; a missing one is "none"; another kind of value, its JSON."""
    if status is None or status == "":
        return "none"
    return status if isinstance(status, str) else json.dumps(status, ensure_ascii=False, sort_keys=True)


def _tally(statuses, known) -> dict:
    counts = dict.fromkeys(known, 0)
    for s in statuses:
        counts[_bucket(s)] = counts.get(_bucket(s), 0) + 1
    return counts


def _counts(entries: list, threads: list, attached: int, cards: dict) -> dict:
    return {"entries": len(entries), "threads": len(threads), "notes": attached, "cards": len(cards),
            "by_status": _tally((e["computed_status"] for e in entries), (*STATUSES, SUPERSEDED)),
            "stored": _tally((e["stored_status"] for e in entries), STATUSES)}


def _key(value):
    """What names a value when values are matched: text names itself; any other value, its JSON (so 5 is not "5")."""
    if isinstance(value, str):
        return value
    return ("value", json.dumps(value, ensure_ascii=False, sort_keys=True))


def _strings(value) -> list:
    """Every piece of text inside a value, however it is nested (found without recursion)."""
    stack, out = [value], []
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            stack.extend(reversed(list(v.values())))
        elif isinstance(v, list):
            stack.extend(reversed(v))
    return out


def _too_deep(value) -> bool:
    stack = [(value, 1)]
    while stack:
        v, depth = stack.pop()
        if depth > MAX_DEPTH:
            return True
        if isinstance(v, dict):
            stack.extend((x, depth + 1) for x in v.values())
        elif isinstance(v, list):
            stack.extend((x, depth + 1) for x in v)
    return False


def _name(id_, line: int) -> str:
    """How a problem calls a decision: by its id when it has a usable one, otherwise by its line."""
    return id_ if _usable(id_) else f"the decision on line {line}"


def _usable(id_) -> bool:
    return isinstance(id_, str) and bool(id_.strip())


# ---- reading the files --------------------------------------------------------------------------------------------
def _rows(path: Path, what: str) -> tuple[list, list]:
    """The lines of a JSON-lines file that hold an object, as (line number, object), and a problem for each that does
    not. The lines are the register's own: the file is decoded as UTF-8 and cut where str.splitlines() cuts it, a line
    that is only white space is skipped, and a line is as long as it is. A file that is missing or cannot be opened is
    one problem, not a crash; so is a byte that is not UTF-8 (the line is still read, with the replacement character in
    that byte's place, and said)."""
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        return [], [problem(path, None, "missing-file", f"there is no {what} at this path")]
    except (OSError, ValueError) as e:   # a ValueError is a path the system cannot take at all, such as one with a NUL
        return [], [problem(path, None, "unreadable", f"the {what} could not be read: {e}")]
    rows, problems = [], []
    for n, line in enumerate(raw.decode("utf-8", errors="surrogateescape").splitlines(), 1):
        if not line.strip():
            continue
        damaged = BAD_BYTE.search(line) is not None
        text = line.encode("utf-8", "surrogateescape").decode("utf-8", "replace") if damaged else line
        # A line too deep for any parser is said as too deep on every machine (see jsonread)
        obj, deep = None, False
        try:
            obj = jsonread.loads(text)
        except ValueError as e:
            deep = getattr(e, "deep", False)
            if not deep:
                why = ("the line begins with a byte-order mark, which JSON does not allow and the register's own tool "
                       "refuses too" if text.startswith("\ufeff") else f"the line is not JSON ({e})")
                problems.append(problem(path, n, "not-json", f"{why}; it begins {text[:60]!r}"))
                continue
        if deep or _too_deep(obj):
            problems.append(problem(path, n, "too-deep", f"the line nests its values more than {MAX_DEPTH} levels "
                                                         f"deep, which no entry of the {what} does, so it was not read"))
            continue
        if not isinstance(obj, dict):
            problems.append(problem(path, n, "not-an-object", f"the line is JSON but holds {type(obj).__name__}, "
                                                              f"not one entry of the {what}"))
            continue
        if damaged:   # a genuine U+FFFD in valid UTF-8 is just text; only a byte that is not UTF-8 is said
            problems.append(problem(path, n, "replacement-character", "the line holds bytes that are not valid UTF-8; "
                                    "each is shown as the replacement character, so its text may not be as written"))
        rows.append((n, obj))
    return rows, problems


def _field(obj: dict, key: str, n: int, path: Path, problems: list):
    """A field as written. A value that is not text is passed on as it is, and said."""
    value = obj.get(key)
    if value is not None and not isinstance(value, str):
        problems.append(problem(path, n, "bad-field", f"{key} should be text, not {type(value).__name__}"))
    return value


def _missing(got: dict, keys) -> list:
    """The keys with no value: absent, null, or text of nothing but white space. Another kind of value is not missing."""
    return [k for k in keys if got[k] is None or (isinstance(got[k], str) and not got[k].strip())]


def _pin(source) -> dict | None:
    """Where words were first written down, from "repo@commit:file:line" (or ":first-last" for a run of lines)."""
    m = PIN.fullmatch(source) if isinstance(source, str) else None
    if not m:
        return None
    line = int(m["line"])
    return {"repo": m["repo"], "commit": m["commit"], "file": m["file"], "line": line,
            "last_line": int(m["last"] or line)}


def _links(obj: dict, who: str, n: int, path: Path, problems: list) -> list:
    """The ids a decision names in `supersedes`, as written. Anything else in the list is a problem. An object in place
    of a list is read as the tool reads it, by its keys, and said."""
    raw = obj.get("supersedes")
    if raw is None:
        return []
    if isinstance(raw, dict):
        problems.append(problem(path, n, "bad-supersedes", f"{who}: supersedes should be a list of ids, not an object; "
                                                           f"its keys are read as the ids, as the register's tool does"))
        raw = list(raw)
    elif not isinstance(raw, list):
        problems.append(problem(path, n, "bad-supersedes", f"{who}: supersedes should be a list of ids, not "
                                                           f"{type(raw).__name__}"))
        return []
    out = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            problems.append(problem(path, n, "bad-supersedes", f"{who}: supersedes holds {item!r}, which is not an id"))
        elif item in out:
            problems.append(problem(path, n, "bad-supersedes", f"{who}: supersedes names {item} twice"))
        else:
            out.append(item)
    return out


def _entry(n: int, id_, obj: dict, path: Path, problems: list) -> dict:
    who = _name(id_, n)
    got = {k: _field(obj, k, n, path, problems) for k in (*REQUIRED, "offer", "time_utc", "added_by", "added")}
    missing = _missing(got, REQUIRED)
    if missing:
        problems.append(problem(path, n, "missing-field", f"{who} has no {', '.join(missing)}"))
    if isinstance(got["date"], str) and got["date"] and not DATE.fullmatch(got["date"]):
        problems.append(problem(path, n, "bad-date", f"{who} has the date {got['date']!r}, not YYYY-MM-DD"))
    if got["status"] and got["status"] not in STATUSES:
        problems.append(problem(path, n, "unknown-status", f"{who} has the status {got['status']!r}; the register uses "
                                                           f"{', '.join(STATUSES)}"))
    pin = _pin(got["source"])
    if isinstance(got["source"], str) and got["source"] and pin is None:
        problems.append(problem(path, n, "bad-source", f"{who} cites {got['source']!r}, which is not "
                                                       f"repo@commit:file:line"))
    return {"id": id_, "line": n, "date": got["date"], "time": got["time_utc"], "to": got["to"],
            "subject": got["subject"], "words": got["words"], "offer": got["offer"], "reading": got["reading"],
            "source": got["source"], "pin": pin, "stored_status": got["status"], "computed_status": got["status"],
            "supersedes": _links(obj, who, n, path, problems), "superseded_by": [], "notes": [], "mentions": {},
            "added_by": got["added_by"], "added": got["added"]}


def _entries(rows: list, path: Path, problems: list) -> tuple[list, dict]:
    """The decisions, in the order of the file, and each usable id with the decisions that hold it. Every line that
    holds an object is a decision, as it is to the register's tool. One with no usable id cannot be referred to, and one
    whose id is already used is referred to together with the first: each is said, and each is kept, since what it
    supersedes counts all the same."""
    out, by_id = [], {}
    for n, obj in rows:
        id_ = obj.get("id")
        if not _usable(id_):
            problems.append(problem(path, n, "no-id", "the decision has no id, so nothing can refer to it; it is kept, "
                                                      "and what it supersedes still counts"))
        elif id_ in by_id:
            problems.append(problem(path, n, "duplicate-id", f"{id_} is already the id of the decision on line "
                                    f"{by_id[id_][0]['line']}; both are kept, and a link to {id_} reaches both"))
        e = _entry(n, id_, obj, path, problems)
        out.append(e)
        if _usable(id_):
            by_id.setdefault(id_, []).append(e)
    return out, by_id


def _draw_links(entries: list, by_id: dict, path: Path, problems: list) -> None:
    """Draw superseded_by from every supersedes, then work out each decision's status. A link to a decision that is not
    in the register cannot be drawn. One to itself or to a later one is drawn, as the tool draws it, and reported. A
    link to an id held by two decisions is drawn to both."""
    for e in entries:
        for old in e["supersedes"]:
            targets = by_id.get(old)
            if not targets:
                problems.append(problem(path, e["line"], "dangling-supersedes",
                                        f"{_name(e['id'], e['line'])} supersedes {old}, which is not in the register"))
                continue
            for target in targets:
                target["superseded_by"].append(e["id"])
            if all(target["line"] >= e["line"] for target in targets):
                problems.append(problem(path, e["line"], "supersedes-not-earlier",
                                        f"{_name(e['id'], e['line'])} supersedes {old}, which is not an earlier decision"))
    for e in entries:
        e["computed_status"] = SUPERSEDED if e["superseded_by"] else e["stored_status"]


# ---- notes --------------------------------------------------------------------------------------------------------
def _note(n: int, obj: dict, path: Path, problems: list) -> dict:
    got = {k: _field(obj, k, n, path, problems) for k in (*NOTE_REQUIRED, "added_by", "added")}
    missing = _missing(got, NOTE_REQUIRED)
    if missing:
        problems.append(problem(path, n, "missing-field", f"the note has no {', '.join(missing)}"))
    pin = _pin(got["source"])
    if isinstance(got["source"], str) and got["source"] and pin is None:
        problems.append(problem(path, n, "bad-source", f"the note cites {got['source']!r}, which is not "
                                                       f"repo@commit:file:line"))
    return {"line": n, "on": got["on"], "text": got["text"], "quote": got["quote"], "source": got["source"],
            "pin": pin, "added_by": got["added_by"], "added": got["added"]}


def _attach_notes(rows: list, by_id: dict, path: Path, problems: list) -> int:
    """Put each note under the decision it names (under each, when two hold that id, as the tool's page does). A note
    that names none, or one that is not there, is a problem and is attached to nothing. Returns how many were attached."""
    attached = 0
    for n, obj in rows:
        note = _note(n, obj, path, problems)
        on = note["on"]
        targets = by_id.get(on) if isinstance(on, str) else None
        if not targets:
            why = ("names no decision" if on is None or (isinstance(on, str) and not on.strip())
                   else f"is on {on if isinstance(on, str) else repr(on)}, which is not in the register")
            problems.append(problem(path, n, "note-unattached", f"the note {why}"))
            continue
        for i, target in enumerate(targets):
            target["notes"].append(note if i == 0 else dict(note))
        attached += 1
    return attached


# ---- cards, threads -----------------------------------------------------------------------------------------------
def _mentions(entry: dict) -> dict:
    """Every card id mentioned in a decision or in its notes, with the fields it was found in, in the order found. A
    value that is not text is searched for the text inside it."""
    found: dict = {}
    texts = [(f, entry[f]) for f in CARD_FIELDS]
    texts += [("note", v) for note in entry["notes"] for v in (note["text"], note["quote"], note["source"])]
    for field, value in texts:
        for text in _strings(value):
            for card in CARD.findall(text):
                if field not in found.setdefault(card, []):
                    found[card].append(field)
    return found


def _card_index(entries: list) -> dict:
    index: dict = {}
    for e in entries:
        for card in e["mentions"]:
            index.setdefault(card, []).append(e["id"])
    return dict(sorted(index.items()))


def _when(entry: dict) -> str:
    return entry["date"] if isinstance(entry["date"], str) else ""


def _thread_key(entry: dict):
    """What a decision is grouped under: its subject exactly as written. One with no subject stands alone."""
    subject = entry["subject"]
    if subject is None or (isinstance(subject, str) and not subject.strip()):
        return ("alone", entry["line"])
    return _key(subject)


def _threads(entries: list) -> list:
    """The decisions grouped by subject (exactly as written: the tool never merges subjects, not even for spaces), the
    most recently touched first. A decision with no subject stands alone, since nothing says what it shares with
    another."""
    groups: dict = {}
    for e in sorted(entries, key=lambda x: (_when(x), x["line"])):
        groups.setdefault(_thread_key(e), []).append(e)
    threads = []
    for rows in groups.values():
        live = [e for e in rows if not e["superseded_by"]]
        latest = live[-1] if live else None
        to: dict = {}
        for e in rows:
            if e["to"]:
                to.setdefault(_key(e["to"]), e["to"])
        threads.append(((_when(rows[-1]), rows[-1]["line"]), {
            "subject": rows[0]["subject"], "entries": [e["id"] for e in rows], "live": [e["id"] for e in live],
            "latest": latest["id"] if latest else None,
            "current": latest["stored_status"] if latest else SUPERSEDED,
            "mixed": len({_bucket(e["stored_status"]) for e in live}) > 1,
            "to": list(to.values()), "first": rows[0]["date"],
            "last": rows[-1]["date"]}))
    return [t for _, t in sorted(threads, key=lambda x: x[0], reverse=True)]


# ---- the record ---------------------------------------------------------------------------------------------------
def load(cfg: dict) -> dict:
    """The record, from the "register" file (and the "notes" file, when there is one) of the configured sources.

    With no "register" the source is off: {"off": True, ...} with everything else empty. Otherwise:
      entries   every decision, in the order of the file: id, line (in the file, counted as the register's tool counts
                it), date, time (UTC, as the register keeps it), to, subject, words, offer, reading, source, pin (repo,
                commit, file, line, last_line), stored_status, computed_status, supersedes, superseded_by (every
                decision that names it), notes (attached), mentions (card id -> the fields it is mentioned in),
                added_by, added. A value that is not text is as written; so is an id, which is None when there is none
      threads   the decisions grouped by subject, the most recently touched first: subject, entries (oldest first),
                live (those nothing supersedes), latest (the newest of those), current (its status; "superseded" when
                every decision under the subject is), mixed (live decisions that disagree on status), to, first, last
      counts    entries, threads, notes (attached), cards, by_status (computed) and stored
      cards     each card id mentioned in a decision or in its notes -> the decisions that mention it, in file order
      files, notes_off, problems   the paths read, whether there is no notes file, and everything that could not be used
    """
    out = _blank()
    if not cfg.get("register"):
        out["off"] = True
        return out
    register = Path(cfg["register"]).expanduser()
    notes = Path(cfg["notes"]).expanduser() if cfg.get("notes") else None
    out["notes_off"] = notes is None
    out["files"] = {"register": str(register), "notes": str(notes) if notes else None}
    rows, problems = _rows(register, "register")
    entries, by_id = _entries(rows, register, problems)
    _draw_links(entries, by_id, register, problems)
    problems.sort(key=lambda p: p["line"] or 0)
    attached = 0
    if notes:
        note_rows, note_problems = _rows(notes, "notes file")
        attached = _attach_notes(note_rows, by_id, notes, note_problems)
        problems += sorted(note_problems, key=lambda p: p["line"] or 0)
    for e in entries:
        e["mentions"] = _mentions(e)
    threads, cards = _threads(entries), _card_index(entries)
    out.update(entries=entries, threads=threads, cards=cards, counts=_counts(entries, threads, attached, cards),
               problems=problems)
    return out
