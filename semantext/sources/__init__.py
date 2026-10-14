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
      "inbox":    "the folder holding the shared runs.jsonl and parked.jsonl",
      "register": "the decision register, one decision per line",
      "notes":    "the register's notes, one per line",
      "cards":    "a folder of rule cards, one <name>/SEMANTICS.yaml each",
      "map":      "a map of places and edges, as JSON"
    }

A key that is missing turns that source off, and the page says which ones are off.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import paths

KEYS = ("name", "seats", "group", "inbox", "register", "notes", "cards", "map")
MAX_LINE = 64 * 1024   # a longer line is a problem, never parsed


def config_path() -> Path:
    env = os.environ.get("SEMANTEXT_SOURCES")
    return Path(env).expanduser() if env else paths.home() / "sources.json"


def load_config(path: str | Path | None = None) -> dict:
    """The configured sources, keeping only known keys with a non-empty string value."""
    p = Path(path) if path else config_path()
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8-sig"))
    return {k: data[k] for k in KEYS if isinstance(data.get(k), str) and data[k]}


def problem(source: str | Path, line: int | None, kind: str, text: str) -> dict:
    """One thing a reader could not use. Every reader returns these instead of dropping the line."""
    return {"source": str(source), "line": line, "kind": kind, "text": str(text)[:300]}


def read_lines(path: str | Path):
    """Yield (line number, text) for each non-blank line of a JSON-lines file, with a leading BOM removed.

    A line over MAX_LINE bytes yields (number, None), so the caller can report it as a problem without parsing it."""
    raw = Path(path).read_bytes()
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
