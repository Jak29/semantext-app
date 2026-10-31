"""The Work source: the work store read through slice 1's fold, and what the page shows of each item (PM-DESIGN r4, r5).

Read only. The store is <home>/work/events.jsonl with its head beside it (semantext/work/writer.py); this module walks
it with chain.walk and folds it with fold.fold, the one copy of the authority and edge tables, and never folds itself.
Over the fold it lays what is read now, never stored:
  - each acceptance clause judged by clauses.evaluate, through Evidence (slice 2b): the register for a jak-decision
    clause, runs.py for a run-record clause, the verdicts file for a verdict clause; landed and outcome are "unknown",
    never met, until an outside fact record exists;
  - the status in words (r2, r5): "done (checked)" when every clause is met now, "done (claimed)" when none is unmet
    but a reader cannot see one, "done (your word)" for the person's own act, "proof no longer holds" when evidence
    that met a clause stopped meeting it; held-by (parked decisions, ec.parked-holds) and waiting-on as words;
  - what waits on the person (r5, "Waiting on you"): an agent's proposals, an item in review with no clause (only the
    person's word can end it), and the items whose next edge is the person's ranking. Each carries the line the person
    would type (turns.act_line) and, where it can be made, the inbox's link (turns.deep_link);
  - each item's events, with their assurance, and every "not applied" event with its code and reason.
A store over READ_CAP bytes is not read whole: the page says so. Nothing is written, started or kept.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .. import paths, store
from . import problem

READ_CAP = 64 * 1024 * 1024   # bytes of the store one page build folds; past it, a problem and no items
HISTORY_CAP = 200             # events shown per item, the newest kept
PROBLEM_CAP = 200
TEXT_CAP = 4000
WORD = {"done-checked": "done (checked)", "done-claimed": "done (claimed)", "done-word": "done (your word)",
        "proof-gone": "proof no longer holds"}
J_ID = re.compile(r"J-\d{8}-\d{1,4}", re.ASCII)


NO_READER = "no reader for this yet: it needs a fact record from an outside checker, so it is unknown, never met"
# A work item id as it appears in a decision's own words: whole, so W-lab-1 is never found inside W-lab-12
ITEM_IN_TEXT = re.compile(r"(?<![A-Za-z0-9-])W-[a-z](?:[a-z0-9-]{0,62}[a-z0-9])?-[1-9][0-9]{0,5}(?![A-Za-z0-9])",
                          re.ASCII)
ENTRY_TEXT = ("words", "subject", "reading", "offer", "to")   # the fields of a decision written in words


def names_in(entry: dict) -> list:
    """The work item ids a register entry names in its own words: its words, subject, reading, offer and to
    (PM-DESIGN, decided 24 October, A2: a decision is about an item only when it names the item or its epic). Notes
    never count (round 4, decision 2): a note is the scribe's later addition, and its source a citation, so a note
    naming an item never makes another decision about it."""
    texts = [entry.get(k) for k in ENTRY_TEXT]
    return sorted({m for t in texts if isinstance(t, str) for m in ITEM_IN_TEXT.findall(t)})


class Evidence:
    """clauses.Readers for the page (slice 2b), each kind behind its own small reader: a jak-decision clause from the
    register's entry; a run-record clause through runs.py (workruns.py); a verdict clause from the verdicts file
    (workverdicts.py); landed and outcome stay unknown until an outside fact record exists (NO_READER)."""

    def __init__(self, entries, cfg=None, now=None, ctx=None, unread=None):
        from .workruns import RunRecords
        from .workverdicts import Verdicts
        self.unread = unread   # why the register could not be read: every decision is then unknown, never unmet
        self.by = {}
        for e in entries or []:
            if isinstance(e, dict) and isinstance(e.get("id"), str):
                self.by.setdefault(e["id"], e)   # an id used twice: the first, as the register reads it
        self.run_record, self.verdict = RunRecords(cfg or {}, now), Verdicts(cfg or {}, ctx)

    @property
    def problems(self) -> list:
        return self.run_record.problems + self.verdict.problems

    def decision(self, clause):
        if self.unread:
            return {"unknown": self.unread}
        e = self.by.get(clause.get("register"))
        if e is None:
            return None
        words = e.get("words") if isinstance(e.get("words"), str) else ""
        return {"entry": {"id": e["id"], "line": words, "state": e.get("computed_status"), "names": names_in(e)},
                "producer": e.get("added_by") if isinstance(e.get("added_by"), str) else None}

    def landed(self, clause):
        return {"unknown": NO_READER}

    outcome = landed


def _home(cfg) -> Path:
    said = cfg.get("_home")
    return Path(said) if isinstance(said, str) and said else paths.home()


REGISTER_GONE = ("missing-file", "unreadable")   # record.load's problems for a register it could not read at all


def _register(cfg) -> tuple[list, str | None]:
    """(the register's entries, why it could not be read, or None). A register the sources file names and that cannot
    be read is never an empty one: its decisions are unknown, and the page says so (G6, finding 5)."""
    if not cfg.get("register"):
        return [], None
    from . import record   # here: the register is read only when the sources file names one
    try:
        got = record.load(cfg)
    except Exception as e:  # noqa: BLE001  a reader that stops leaves every decision unknown, and says why
        return [], f"the register could not be read ({type(e).__name__})"
    gone = [p for p in got.get("problems") or [] if p.get("kind") in REGISTER_GONE]
    if gone:
        return [], f"the register could not be read: {gone[0].get('text')}"
    return got.get("entries") or [], None


def _shown(text, cap=TEXT_CAP, lines=False):
    from ..work.cli import shown
    return shown(text, cap, lines)


def load(cfg: dict, readers=None, now=None, projects=None) -> dict:
    """The work store as the page reads it. `readers` (clauses.Readers), `now` and `projects` (the slugs an inbox link
    may name) are the tests' stand-ins; by default the register, the clock and the seats file give them."""
    from ..work import span
    from ..work.chain import walk
    from ..work.fold import fold
    from ..work.writer import Writer
    now = now or datetime.now(timezone.utc)
    w = Writer(_home(cfg))
    out = {"off": False, "store": {"path": str(w.path), "exists": w.path.is_file(), "intact": True, "events": 0},
           "items": [], "asks": [], "ranking": [], "counts": {}, "projects": [], "known_projects": [], "problems": [],
           "words": dict(WORD), "read_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    said = w.seats_said()   # the seats' mode: unchecked (no seats, which is no fault), or refused because they cannot be known
    out["seats_said"] = said
    if said and w.seats_unknown():
        out["problems"].append(problem(cfg.get("_file") or "the sources file", None, "seats", said))
    if not out["store"]["exists"]:
        return out
    size = w.path.stat().st_size
    if size > READ_CAP:
        out["problems"].append(problem(w.path, None, "too large", f"the work store is {size} bytes, over the "
                                                                  f"{READ_CAP} the page reads; it is not folded"))
        return out
    entries, unread = _register(cfg)
    if unread:
        out["problems"].append(problem(cfg["register"], None, "register-unreadable",
                                       f"{unread}; every decision clause is unknown, and no item can be shown held by "
                                       f"a parked decision"))
    parked ={e["id"] for e in entries if isinstance(e.get("id"), str) and J_ID.fullmatch(e["id"])
              and e.get("computed_status") == "parked"}
    raw, head = w.read()   # the head first, then the log: a write landing between them never reads as broken
    tail = store.Tail(raw)
    walked = walk(tail.lines, tail.torn, head)
    # each person_act's transcript span read again before the fold (A1): made-up evidence is never state
    checks = span.checks(walked["records"], span.transcript_roots(cfg))
    st = fold(walked["records"], walked["problems"], parked=parked, now=now, end=walked["end"],
              intact=walked["intact"], checks=checks)
    by_line = {n: rec for n, rec, _ in walked["records"]}
    known = set(projects) if projects is not None else _projects(w)
    out["store"].update(intact=st["intact"], events=len(st["events"]), end=st["end"]["seq"])
    out["known_projects"] = sorted(known)
    out["problems"] += [problem(w.path, p.get("line"), p.get("kind"), p.get("text")) for p in st["problems"][:PROBLEM_CAP]]
    if len(st["problems"]) > PROBLEM_CAP:
        out["problems"].append(problem(w.path, None, "more", f"{len(st['problems']) - PROBLEM_CAP} more problems"))
    from .closed import context
    ctx = context(_home(cfg))   # one set of closures for every clause of this build
    readers = readers if readers is not None else Evidence(entries, cfg, now, ctx, unread)
    rows = [_event(e, by_line.get(e["line"])) for e in st["events"]]
    by_item = {}
    for r in rows:
        by_item.setdefault(r["id"], []).append(r)
    from .workitems import item_view
    items = [item_view(i, by_item.get(i["id"], []), readers, now, known, ctx) for i in
             sorted(st["items"].values(), key=lambda i: (i["project"], i["n"]))]
    out["items"] = items
    read = list(getattr(readers, "problems", None) or [])
    out["problems"] += read[:PROBLEM_CAP]
    if len(read) > PROBLEM_CAP:   # counted, never cut unseen (G6, finding 20)
        out["problems"].append(problem("the evidence readers", None, "more",
                                       f"{len(read) - PROBLEM_CAP} more problems in the evidence files"))
    out["orphans"] = [r for r in rows if r["id"] not in st["items"]][-HISTORY_CAP:]
    out["not_applied"] = sum(not r["applied"] for r in rows)
    _summary(out, items)
    return out


def _projects(w) -> set:
    try:
        return w.projects()
    except Exception:  # noqa: BLE001  no seats file read: no inbox link can be made, and the page says why
        return set()


def _event(row: dict, rec) -> dict:
    """One event as the history shows it: the fold's row, and what it said, in words, from its own record."""
    rec = rec if isinstance(rec, dict) else {}
    ev = row.get("event")
    what = ""
    if ev == "create":
        what = "filed " + _shown(rec.get("title"), 120)
    elif ev == "move":
        what = f"{rec.get('from')} to {rec.get('to')}" + (f", reviewer {rec['reviewer']}" if rec.get("reviewer") else "")
    elif ev == "person_act":
        what = str(rec.get("act")) + (f" {rec['value']}" if rec.get("value") is not None else "") + \
            (f" (from {rec['from']})" if rec.get("from") else "")
    elif ev in ("link", "unlink"):
        link = rec.get("link") if isinstance(rec.get("link"), dict) else {}
        what = ("removed " if ev == "unlink" else "") + f"{link.get('type')}:{link.get('ref')}"
    elif ev in ("comment", "propose_park"):
        what = _shown(rec.get("text"), 300)
    elif ev == "propose_reassign":
        what = f"to {rec.get('to_seat')}" + (": " + _shown(rec.get("text"), 200) if rec.get("text") else "")
    elif ev == "edit":
        what = "changed " + ", ".join(k for k in ("title", "text", "kind") if k in rec)
    elif ev == "void":
        what = _shown(rec.get("reason"), 200)
    return {"line": row["line"], "seq": row["seq"], "id": row["id"], "event": ev, "who": row["who"],
            "assurance": row["assurance"], "effective": row["effective"], "on_chain": row["on_chain"],
            "at": row["at"], "applied": row["applied"], "code": row["code"], "reason": row["reason"],
            "clock": row.get("clock"), "what": what, "act": rec.get("act") if ev == "person_act" else None,
            "check": row.get("check")}   # a person_act read again from its span: verified (else it is not applied)


def _summary(out: dict, items: list) -> None:
    counts, names = {}, []
    for i in items:
        p = counts.setdefault(i["project"], {})
        # each done word, and proof no longer holds, is its own column: done (claimed) is never counted as done
        key = "void" if i["voided"] else WORD[i["status"]] if i["status"] else i["shown"]
        p[key] = p.get(key, 0) + 1
        if i["project"] not in names:
            names.append(i["project"])
        for a in i["asks"]:
            out["asks"].append({**a, "item": i["id"], "title": i["title"], "project": i["project"]})
        if i["next_edge"] == "ranking":
            out["ranking"].append(i["id"])
    out["counts"] = counts
    out["projects"] = [{"name": n, "known": n in out["known_projects"]} for n in sorted(names)]
