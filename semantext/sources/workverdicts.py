"""The verdict reader for work clauses (PM-DESIGN r4, slice 2b): a verdict clause read from the verdicts file the
sources file names.

  "verdicts": a JSON-lines file, one verdict a line: {"piece", "verdict", "by", "at"} ("survived" is the one that holds);
  "pieces":   its pieces file, one piece a line: {"id", "originator"}.

The newest verdict on the piece decides (by "at", read as a time, then by its place in the file; an "at" that is not
an ISO 8601 time is a problem, never read); one that is not "survived" after an
earlier "survived" is "proof no longer holds". The verdict's "by" is the attacker, and it counts only when it is neither
the item's owner nor its creator (the judge refuses the builder's own evidence) nor the piece's originator; a piece
that names no originator leaves the clause unknown, since its attacker cannot be told from its author. A file that
is missing, unreadable or in a closed place leaves the clause unknown, with the reason (and while the person's closures
are not known, every file is closed, api 0.2's rule, said as that); a line that cannot be used is a problem, never read. Both files are read once per page build, lazily, and never written.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .. import jsonread
from . import problem, read_lines
from .closed import ReadContext, closures_known, is_closed_place


def _when(text):
    """An ISO 8601 time as an aware UTC datetime (one with no zone is read as UTC), or None: verdicts are ordered by
    time, never by their text."""
    try:
        t = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


class Verdicts:
    def __init__(self, cfg: dict, ctx=None):
        self.cfg, self.ctx = cfg, ctx
        self._read = None
        self.problems: list[dict] = []

    def _rows(self, key: str, need: tuple):
        said = self.cfg.get(key)
        if not isinstance(said, str) or not said.strip():
            return None, f"your sources file names no {key} file ({key})"
        path = Path(said).expanduser()
        if is_closed_place(str(path), self.ctx):
            # api 0.2: while the person's closures are not known every path is closed; say which of the two it is
            known = self.ctx.closures is not None if isinstance(self.ctx, ReadContext) else closures_known(self.ctx)
            if not known:
                return None, (f"your closed places are not named (or cannot be read), so the {key} file is not read; "
                              f"name them in your sources file first")
            return None, f"the {key} file is in a place you closed, so it is not read"
        if not path.is_file():
            return None, f"the {key} file is not there ({path})"
        rows = []
        try:
            for n, text in read_lines(path):
                try:
                    row = jsonread.loads(text) if text is not None else None
                except ValueError:
                    row = None
                # each needed field is text with something in it besides blanks: "  " names nobody (G6, finding 25)
                if not isinstance(row, dict) or not all(isinstance(row.get(k), str) and row[k].strip() for k in need):
                    self.problems.append(problem(path, n, "bad-row", f"not a {key} row with {', '.join(need)}"))
                    continue
                if "at" in need:
                    row = {**row, "_when": _when(row["at"])}
                    if row["_when"] is None:   # compared as text, "2024-5-9" outranks "2024-05-10" (finding 24)
                        self.problems.append(problem(path, n, "bad-row", f"its at {row['at'][:40]!r} is not a time "
                                                                         f"(ISO 8601, such as 2026-10-24T14:00:00Z)"))
                        continue
                rows.append((n, row))
        except OSError as e:
            return None, f"the {key} file cannot be read ({type(e).__name__})"
        return (path, rows), None

    def _load(self):
        if self._read is None:
            v, why = self._rows("verdicts", ("piece", "verdict", "by", "at"))
            p, why_p = (None, None) if why else self._rows("pieces", ("id",))
            self._read = (v, p, why or why_p)
        return self._read

    def __call__(self, clause: dict):
        v, p, why = self._load()
        if why:
            return {"unknown": why}
        piece = clause["piece"]
        pieces = [row for _, row in p[1] if row["id"] == piece]
        if not pieces:   # with or without a verdict on it: a piece no line holds is unknown, never "no evidence"
            return {"unknown": f"the pieces file holds no piece {piece}"}
        mine = sorted(((row["_when"], n), row) for n, row in v[1] if row["piece"] == piece)
        if not mine:
            return None
        last = mine[-1][1]
        return {"verdict": {"piece": piece, "verdict": last["verdict"], "attacker": last["by"], "at": last["at"]},
                "piece": pieces[0], "producer": last["by"], "path": str(v[0]),
                "was_survived": any(row["verdict"] == "survived" for _, row in mine[:-1])}
