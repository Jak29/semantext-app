"""Sources: the files a person already keeps, read where they lie and never written.

Someone who runs agents already has records: each agent's requests to them, the decisions they have given, the rules
they hold, the repositories their agents work in. Semantext reads those files as its first dataset instead of asking
for them to be copied in. Every reader here opens files for reading only, never starts a process, and reports every
line it could not use as a problem rather than dropping it.

Which files to read is the person's own choice, written in <home>/sources.json (or the file SEMANTEXT_SOURCES names):

    {
      "name":     "the person's own word for the whole, shown at the top of the map",
      "seats":    "a seats file: a base folder, the named roots, and each agent's names, groups and home",
      "group":    "only the seats in this group, as the person's own inbox reads them (every seat when missing)",
      "requests": "the name of each agent's requests file in its home (requests.jsonl when missing)",
      "changes":  "the name of each agent's proposed-changes file in its home (changes.jsonl when missing)",
      "inbox":    "the folder holding the shared runs.jsonl and parked.jsonl",
      "register": "the decision register, one decision per line",
      "notes":    "the register's notes, one per line",
      "cards":    "a folder of rule cards, one <name>/SEMANTICS.yaml each",
      "map":      "a map of places and edges, as JSON",
      "gaming":   "the inbox's gaming flag (gaming.json in the inbox folder when missing)",
      "guards":   "a JSON file naming the checkers that refuse a break of a rule, each with its two arms",
      "run_records":     ["folders whose runs/<checker>.jsonl hold run records (schema 1; sources/runs.py)"],
      "run_record_days": 30,
      "verdicts": "a JSON-lines file of verdicts on pieces, {piece, verdict, by, at} (work clauses)",
      "pieces":   "its pieces file, {id, originator} a line"
    }

"run_records" may be one folder or a list of them, and "run_record_days" (the age past which a record is stale) is a
whole number; every other built-in key is text. A key only an outside source declares may be text, or a list of at
most 200 entries, each a text, a number, or a flat record (at most 16 keys, each value a text or a number); any other
shape is not kept, and the page says so as a problem of that source.

A key that is missing turns that source off, and the page says which ones are off. The gaming flag is the one
exception: with no "gaming" key it is read from the "inbox" folder, where the inbox keeps it.
"""
from __future__ import annotations

import errno
import json
import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from .. import jsonread, paths
from .builtin import config_keys

KEYS = config_keys()   # the frame's keys and every built-in source's (builtin.py), no longer a fixed tuple here
MAX_LINE = 64 * 1024   # a longer line is a problem, never parsed


def config_path() -> Path:
    env = os.environ.get("SEMANTEXT_SOURCES")
    return Path(env).expanduser() if env else paths.home() / "sources.json"


def load_config(path: str | Path | None = None, keys=None) -> dict:
    """The configured sources, keeping only known keys with a non-empty string value. `keys` names others to keep
    instead (an outside source's own, as it declares them). A key no built-in reads may also hold a non-empty list of
    plain texts and numbers, kept as a list: before api 0.2 every list was dropped here, so a plug-in's list setting
    never reached its read (the first outside plug-in's REQUESTS.md, item 5)."""
    p = Path(path) if path else config_path()
    if not p.is_file():
        return {}
    # a key given twice is refused, never last-one-wins (the audit of 784faf6, protection item 9): every caller says
    # the file cannot be read, as a problem line
    data = jsonread.loads(p.read_text(encoding="utf-8-sig"), unique=True)
    return {k: data[k] for k in (KEYS if keys is None else keys) if _kept(k, data.get(k))}


LISTS = ("run_records",)        # a key that may also hold a list of texts (the run-record folders)
NUMBERS = ("run_record_days",)  # a key that holds a whole number over 0 (the run records' age bound)


def _plain(v) -> bool:
    """A text, or a finite number that is not a truth value: what a plug-in's list setting may hold."""
    if isinstance(v, bool):
        return False
    if isinstance(v, str):
        return bool(v.strip())
    return isinstance(v, (int, float)) and v == v and v not in (float("inf"), float("-inf"))


def _kept(key: str, value) -> bool:
    if key in NUMBERS:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0
    if key in LISTS and isinstance(value, list):
        return bool(value) and all(isinstance(v, str) and v.strip() for v in value)
    if key not in KEYS and isinstance(value, list):   # a built-in's text key stays text: its reader expects one
        return bool(value) and len(value) <= MAX_ENTRIES and all(_plain(v) or _flat(v) for v in value)
    return isinstance(value, str) and bool(value)


MAX_ENTRIES = 200   # entries in one list setting
MAX_FIELDS = 16     # keys in one record of a list setting


def _flat(v) -> bool:
    """A flat record: at most MAX_FIELDS keys, each a text, each value a plain text or number (the first outside
    plug-in's readmes: [{project, path}])."""
    return (isinstance(v, dict) and 0 < len(v) <= MAX_FIELDS
            and all(isinstance(k, str) and k.strip() and _plain(x) for k, x in v.items()))


def refused_keys(path: str | Path | None, keys) -> list[dict]:
    """A problem for each of `keys` the sources file gives that load_config does not keep: an outside source's setting
    of a shape it may not take (a nested record, a list that is too long), said rather than dropped in silence."""
    p = Path(path) if path else config_path()
    try:
        data = jsonread.loads(p.read_text(encoding="utf-8-sig"), unique=True) if p.is_file() else {}
    except (OSError, ValueError):
        return []   # the page already says the file cannot be read
    if not isinstance(data, dict):
        return []
    return [problem(p, None, "bad-setting", f"{k!r} is not kept: a setting is a text, or a list of at most "
                    f"{MAX_ENTRIES} texts, numbers or flat records of at most {MAX_FIELDS} plain fields")
            for k in keys if k in data and data[k] not in (None, "", []) and not _kept(k, data[k])]


def rooted(rel: str) -> bool:
    """Whether a path names its own start: a drive (D:\\x, or D:x), a root (\\Windows, /etc), or a share (\\\\srv\\x,
    //srv/x, \\\\?\\...), read the Windows way and the POSIX way alike, whatever this system is."""
    w = PureWindowsPath(rel)
    return bool(w.drive or w.root or PurePosixPath(rel).root)


def under(base: str | None, rel) -> tuple[str | None, str | None]:
    """A folder as a seats file writes it, in full: (the path, None), or (None, why it cannot be). The one join of a
    seats file's homes and roots, for the places reader and the gates reader alike (places._under, discover.read_roots).

    With a base, the path is put under it and must stay there: one that steps out with "..", or that names its own
    start (rooted: a drive, a root or a share) is refused, since joined to the base it would leave it (Path("C:\\seats")
    / "D:\\other" is D:\\other; the Fable review of 70f2d3c, finding 5). With no base, the path must be written in
    full."""
    if not isinstance(rel, str) or not rel.strip():
        return None, "has no path"
    rel = rel.strip()
    if ".." in re.split(r"[\\/]", rel):
        return None, f"a path may not step out with '..': {rel}"
    if base and rooted(rel):
        return None, (f"{rel} names a drive, a root or a share of its own, so it would leave the base folder; a path "
                      f"under the base is written without one")
    full = Path(base) / rel if base else Path(rel)
    if not full.is_absolute():
        return None, f"{rel} is not a full path, and the seats file gives no base folder to put it under"
    return str(full), None


def problem(source: str | Path, line: int | None, kind: str, text: str) -> dict:
    """One thing a reader could not use. Every reader returns these instead of dropping the line."""
    return {"source": str(source), "line": line, "kind": kind, "text": str(text)[:300]}


MAX_FILE = 16 * 1024 * 1024   # bytes read_lines reads of one file; a larger one is refused, never read whole


def read_lines(path: str | Path):
    """Yield (line number, text) for each non-blank line of a JSON-lines file, with a leading BOM removed.

    A line over MAX_LINE bytes yields (number, None), so the caller can report it as a problem without parsing it. A
    file over MAX_FILE bytes is an OSError, read no further than one byte past the cap (the Fable review of 70f2d3c,
    F2: MAX_LINE bounded a line, never the file)."""
    with open(path, "rb") as f:
        raw = f.read(MAX_FILE + 1)
    if len(raw) > MAX_FILE:
        cap = f"{MAX_FILE // (1024 * 1024)} MB" if MAX_FILE >= 1024 * 1024 else f"{MAX_FILE} bytes"
        raise OSError(errno.EFBIG, f"it is over {cap}, so it is not read")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for n, line in enumerate(raw.split(b"\n"), 1):
        line = line.rstrip(b"\r")
        if not line.strip():
            continue
        if len(line) > MAX_LINE:
            yield n, None
            continue
        yield n, line.decode("utf-8", errors="replace")
