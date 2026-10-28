"""The fold: a pure function from the work store's lines (and its head) to the state of every item (PM-DESIGN r3, r4).

The file is readable and writable on disk by anything running as the person, so the fold trusts no line for what it
says: it walks the hash chain (chain.walk), then re-applies the whole authority table and edge table (rules.apply) to
EVERY event, in append order. A refused event is kept in the history as "not applied", with its code and reason; an
authority-bearing event from an actor the kernel did not stamp is a proposal, not applied; a record off the chain
counts only as claimed. Nothing here reads a clock, a file, the locale or the time zone, so the same bytes give the
same state on every machine and every run (the attack, F5): the time of an event is the kernel's stamp, kept as text
and never used to order anything (F6). Live evidence (clauses, link badges) is a separate overlay (clauses.py).
"""
from __future__ import annotations

import hashlib
import re
from datetime import timedelta

from .chain import canonical, walk
from .events import ASSURANCE, PERSON, WorkRefused, from_record, parse_id
from .rules import AUTHORITY, Refuse, apply, bound_link
from .span import UNVERIFIED

EPIC_DEPTH = 64          # an epic chain deeper than this is reported, never followed further (the attack, F8)
FUTURE_SECONDS = 2 * 24 * 3600
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", re.ASCII)


def fold_lines(lines, torn=None, head=None, parked=(), now=None, checks=None) -> dict:
    """The state from the log's lines (store.Tail's lines and torn fragment) and its head ({"seq", "hash"} or None).
    `parked` is the register's parked decisions (J- ids), a snapshot given in; `now` (an aware datetime), when given,
    only flags stamps more than two days ahead of it; `checks` is span.checks() of the records, given in."""
    w = walk(lines, torn, head)
    return fold(w["records"], w["problems"], parked=parked, now=now, end=w["end"], intact=w["intact"], checks=checks)


def fold(records, problems=(), parked=(), now=None, end=None, intact=True, checks=None) -> dict:
    """records: [(line number, record, on_chain)] in the file's order. Returns {"items", "events", "problems",
    "minted", "keys", "end", "intact", "acts"}: each event with what happened to it, "minted" the highest n ever used
    in each project (by any create ON THE CHAIN, applied or not, so an id is never minted twice; a create off the
    chain moves no number and is never an item, so one appended line cannot use up a project's numbers), "keys" the
    request keys seen. The same as Folder(parked).feed(records, problems, checks) and its snapshot.

    `checks` ({line: (verdict, why)}, span.checks) is what reading each person_act's transcript span found, read by
    the caller so the fold reads nothing itself: an act whose span does not hold, or that names none, is "not applied
    (unverified)". With no `checks` (None) no person's act is applied: none was checked (round 4, decision 1a)."""
    f = Folder(parked)
    f.feed(records, problems, checks, intact)
    return f.snapshot(now, end, intact)


class Folder:
    """The fold, resumable: feed() takes records in the file's order, any number of times, and snapshot() gives the
    state so far. Feeding a log in two parts gives exactly what feeding it whole gives (the writer's cache relies on
    it; tests/test_work_cache.py checks it)."""

    def __init__(self, parked=()):
        self.parked = frozenset(parked)
        self.items, self.events, self.minted, self.keys, self.acts = {}, [], {}, {}, set()
        self.problems = []

    def feed(self, records, problems=(), checks=None, intact=True) -> None:
        """`intact` False is a broken store (chain.walk): every record is off the chain there and is still shown, as
        claimed. In an intact store a create off the chain is never an item and uses no number."""
        self.problems.extend(problems)
        checks = checks or {}
        items, events, minted, keys, acts, parked = (self.items, self.events, self.minted, self.keys, self.acts,
                                                     self.parked)
        for n, rec, on_chain in records:
            get = rec.get
            said, who, seq = get("assurance"), get("who"), get("seq")
            eff = said if on_chain and said in ASSURANCE else "claimed"
            # "at" is the kernel's fixed-width UTC stamp, so text order is time order; snapshot() notes the clock
            row = {"line": n, "seq": seq, "event": get("event"), "id": get("id"), "who": who, "assurance": said,
                   "effective": eff, "on_chain": on_chain, "at": get("at"), "applied": False, "code": None,
                   "reason": None}
            off = intact and not on_chain
            if row["event"] == "create" and not off:   # only the chain moves the numbers (round 4, high 2a)
                _mint(rec, minted)
            try:
                if row["event"] == "create" and off:
                    raise Refuse("OFF_CHAIN", "an item is filed only on the chain; a create off it is never an item "
                                              "and uses no number")
                event, f = from_record(rec)
                row["id"] = f.get("id", row["id"])
                if on_chain and "request_key" in f:
                    keys.setdefault((who, f["request_key"]), (seq, _req_hash(rec)))
                verdict, why = checks.get(n, (None, None))
                if verdict is None and event == "person_act" and who == PERSON and isinstance(get("evidence"), dict):
                    verdict, why = UNVERIFIED, "it was not checked against its transcript span"   # never the table alone
                if verdict == UNVERIFIED:
                    raise Refuse("UNVERIFIED", f"not applied (unverified): {why}")
                apply(items, event, f, rec, eff, parked, acts)   # VERIFIED and ATTESTED are applied
                row["applied"] = True
                if verdict is not None:
                    row["check"] = verdict
            except WorkRefused as e:
                row["code"], row["reason"] = "MALFORMED", e.reason
            except Refuse as e:
                row["code"], row["reason"] = ("PROPOSAL" if e.code == "NOT_BOUND" else e.code), e.reason
            except Exception as e:  # noqa: BLE001  an untrusted line is one "not applied" row, never a stopped fold
                row["code"], row["reason"] = "MALFORMED", f"a field the checks could not read ({type(e).__name__})"
            if not on_chain:
                row["reason"] = (row["reason"] + "; " if row["reason"] else "") + "off the chain: counted as claimed"
            events.append(row)

    def snapshot(self, now=None, end=None, intact=True) -> dict:
        """The state so far. The derived parts (epic paths, holds, who it waits on, the clock notes) are made here,
        fresh each time, never stored by feed()."""
        ahead = (now + timedelta(seconds=FUTURE_SECONDS)).strftime("%Y-%m-%dT%H:%M:%SZ") if now is not None else None
        last = None   # the newest stamp so far that is not itself flagged ahead (G6, finding 17)
        for row in self.events:
            at = row["at"] if isinstance(row["at"], str) and STAMP.fullmatch(row["at"]) else None
            if ahead is not None and at is not None and at > ahead:
                row["clock"] = "more than two days ahead of now; its place is its line"
                continue      # one line stamped far ahead never makes every later record "a clock set back"
            if at is not None and last is not None and at < last:
                row["clock"] = "earlier than the event before it (a clock set back); its place is its line"
            else:
                row.pop("clock", None)
            last = at or last
        problems = list(self.problems)
        for item in self.items.values():
            item["epic_path"], deep = _epics(item, self.items)
            if deep:
                problems.append({"line": None, "kind": "depth", "text": f"{item['id']}: an epic chain deeper than "
                                                                         f"{EPIC_DEPTH}, not followed further"})
            mine = [x for x in item["links"] if x["type"] == "decision" and x["ref"] in self.parked]
            item["held_by"] = sorted({x["ref"] for x in mine if bound_link(item, x)})   # only a bound link holds
            item["hold_proposed"] = sorted({x["ref"] for x in mine} - set(item["held_by"]))
            item["waiting_on"] = [item["reviewer"]] if item["state"] == "review" and item["reviewer"] else []
        problems.sort(key=lambda p: (p["line"] is None, p["line"] or 0))   # one order, whole or in parts
        return {"items": self.items, "events": self.events, "problems": problems, "minted": self.minted,
                "keys": self.keys, "end": end, "intact": intact, "acts": self.acts}

def _mint(rec, minted):
    if rec.get("event") == "create":
        got = parse_id(rec.get("id"))
        if got:
            minted[got[0]] = max(minted.get(got[0], 0), got[1])


def _req_hash(rec) -> str:
    """What makes two requests under one key the same request: everything but the stamps, and the item id too except
    for a create, whose id the writer mints (round 4, finding 2c: a key repeated on another item is another request)."""
    drop = ("seq", "prev", "hash", "at", "id") if rec.get("event") == "create" else ("seq", "prev", "hash", "at")
    body = {k: v for k, v in rec.items() if k not in drop}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _epics(item, items):
    """The epics above an item, nearest first, followed without recursion and at most EPIC_DEPTH deep."""
    path, seen, cur = [], {item["id"]}, item.get("epic")
    while cur and cur in items and cur not in seen:
        if len(path) >= EPIC_DEPTH:
            return path, True
        path.append(cur)
        seen.add(cur)
        cur = items[cur].get("epic")
    return path, False


def state_hash(state: dict) -> str:
    """A digest of the folded items and events, for comparing two folds."""
    return hashlib.sha256(canonical({"items": state["items"], "events": state["events"]}).encode("utf-8")).hexdigest()


def open_items(state: dict, who: str | None = None, project: str | None = None) -> list[dict]:
    """The items shown on a board: not void, optionally one owner's and one project's, by project then number."""
    out = [i for i in state["items"].values() if not i["voided"] and (who is None or i["owner"] == who) and
           (project is None or i["project"] == project)]
    return sorted(out, key=lambda i: (i["project"], i["n"]))


def card_line(state: dict, who: str, project: str, cap: int = 12) -> str:
    """The reading card's line (r3, r4; slice 5 is held): ids and states only, never a title or any agent's text."""
    mine = [i for i in open_items(state, who, project) if i["state"] not in ("done", "parked")]
    shown = ", ".join(f"{i['id']} {i['state']}" for i in mine[:cap])
    more = f" (+{len(mine) - cap} more)" if len(mine) > cap else ""
    return f"Work in {project} for {who}: {shown or 'none open'}{more}"


__all__ = ["fold", "fold_lines", "state_hash", "open_items", "card_line", "AUTHORITY", "PERSON"]
