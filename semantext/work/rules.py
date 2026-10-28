"""The authority table and the edge table, applied to one event (PM-DESIGN r2 to r4). The fold applies it to every
event in the store, and the writer asks it before it writes, so there is one copy of the table, never two.

Who may do what:
  - only a seat the kernel stamped ("bound", the MCP channel) holds a seat's rights. A claimed actor (the command line)
    holds none: its authority-bearing events are proposals, shown and never applied (r2, r4);
  - comment, link, unlink and propose_* bear no authority: applied from any actor, each shown with its assurance. A
    link only points at a candidate; it never proves (r4). An unlink undoes a link, except that a link a bound seat
    made is undone only by a bound seat (from anyone else it is a proposal);
  - create from a bound seat makes the seat the owner; from a claimed actor, the item has no owner until a bound seat
    takes it (assign_self applies only to an UNASSIGNED item, r3);
  - edit changes only title, text and kind, of one's own item (r3), never while the person holds it parked;
  - the edges (r4): backlog -> next is the person's (ranking); next -> doing and doing -> review are the owner's, and
    review names a reviewer who is neither its owner nor its creator; review -> doing is the reviewer's; review ->
    done is nobody's move (the clauses derive it); doing or review -> done is the person's word; park and back are
    the person's, and back returns to the state it left; done is terminal, and the person may reopen;
  - void: an agent's own item (the one it owns now), before it ever reached doing (r4's default); the person, always;
  - an item that links a decision the register holds as parked refuses every way into doing (next -> doing, the
    person's doing, reopen, the reviewer's review -> doing, the person's unpark of an item parked from doing), for
    everyone (ec.parked-holds). Only a bound link holds: a claimed or off-chain one is a
    proposal, shown and holding nothing (round 4, finding 4a).
"""
from __future__ import annotations

import hashlib

from .chain import canonical
from .events import PERSON, SEAT_RE, parse_id
from .turns import ACT_SECONDS, act_line, when

AUTHORITY = ("create", "edit", "assign_self", "move", "void", "person_act")   # comment, link, propose_* bear none
OWNER_EDGES = {("next", "doing"), ("doing", "review")}
PERSON_MOVES = ("backlog", "next", "doing", "review")
DELIVERABLES = ("commit", "run", "change")   # what review needs linked; a card, post or decision is not the work


class Refuse(Exception):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code, self.reason = code, reason


def new_item(ident: str, f: dict, who: str, assurance: str, seq: int, imported: bool) -> dict:
    project, n = parse_id(ident)
    return {"id": ident, "project": project, "n": n, "title": f["title"], "text": f.get("text", ""),
            "kind": f.get("kind", "task"), "state": "backlog", "priority": None, "epic": f.get("epic"),
            "owner": who if assurance == "bound" and who != PERSON else None, "creator": who,
            "creator_assurance": assurance, "reviewer": None, "links": list(f.get("links") or []),
            "clauses": list(f.get("clauses") or []), "parked_from": None, "voided": None, "reached_doing": False,
            "done_by": None, "comments": [], "proposals": [], "source": "import" if imported else None,
            "events": [seq]}


def apply(items: dict, event: str, f: dict, rec: dict, assurance: str, parked: frozenset, used_acts: set) -> None:
    """Apply one event to `items` in place, or raise Refuse(code, reason) and change nothing. `assurance` is the
    event's effective assurance (claimed for a record off the chain)."""
    who = rec.get("who")
    if not isinstance(who, str) or not who:
        raise Refuse("MALFORMED", "the record names no actor")
    if not SEAT_RE.fullmatch(who):   # the writer stamps only a seat-shaped name; a line by hand is held to the same
        raise Refuse("MALFORMED", "the record's actor is not a name the kernel stamps (a letter, then at most 39 "
                                  "letters, digits and . _ -)")
    seat = assurance == "bound" and who != PERSON
    if event in AUTHORITY and event != "person_act" and event != "create" and not seat:
        raise Refuse("NOT_BOUND", f"{who} is {assurance}, not a seat the kernel stamped, so this is a proposal "
                                  f"and holds no rights")
    if event == "create":
        return _create(items, f, rec, who, assurance)
    item = items.get(f["id"])
    if item is None:
        raise Refuse("UNKNOWN_ID", f"no item {f['id']} was ever created")
    if item["voided"] and event not in ("comment",):
        raise Refuse("TERMINAL", "the item is void")
    if event == "comment":
        item["comments"].append({"who": who, "assurance": assurance, "text": f["text"], "seq": rec["seq"]})
    elif event == "link":
        if f["link"]["type"] == "item" and f["link"]["ref"] == item["id"]:
            raise Refuse("MALFORMED", "an item never links itself")
        item["links"].append({**f["link"], "by": who, "assurance": assurance})
    elif event == "unlink":
        want = (f["link"]["type"], f["link"]["ref"])
        match = [x for x in item["links"] if (x["type"], x["ref"]) == want]
        if not match:
            raise Refuse("UNKNOWN_ID", f"{item['id']} has no link {want[0]}:{want[1]}")
        if not seat and any(bound_link(item, x) for x in match):
            raise Refuse("NOT_BOUND", f"{who} is {assurance}: a link a bound seat made is undone only by a bound "
                                      f"seat, so this is a proposal")
        item["links"] = [x for x in item["links"] if (x["type"], x["ref"]) != want]
    elif event in ("propose_park", "propose_reassign"):
        item["proposals"].append({"what": event[8:], "to": f.get("to_seat"), "who": who, "assurance": assurance,
                                  "text": f.get("text", ""), "seq": rec["seq"]})
    elif event == "edit":
        if item["owner"] != who:
            raise Refuse("NOT_AUTHORIZED", "only the item's owner edits it")
        if item["state"] == "done":
            raise Refuse("TERMINAL", "a done item is not edited; a later defect is a new item linking it")
        if item["state"] == "parked":
            raise Refuse("PARKED", "a parked item is the person's until they bring it back")
        item.update({k: f[k] for k in ("title", "text", "kind") if k in f})
    elif event == "assign_self":
        if item["owner"] is not None:
            raise Refuse("NOT_AUTHORIZED", f"{item['id']} is {item['owner']}'s; only an unassigned item is taken")
        if item["state"] in ("done", "parked"):
            raise Refuse("TERMINAL" if item["state"] == "done" else "PARKED", f"the item is {item['state']}")
        item["owner"] = who
    elif event == "move":
        _move(item, f, who, parked)
    elif event == "void":
        if item["state"] == "parked":
            raise Refuse("PARKED", "a parked item is the person's until they bring it back")
        # its own: the item's owner now (the person may have reassigned it), never its creator (G6, finding 4)
        if item["owner"] != who or item["reached_doing"]:
            raise Refuse("NOT_AUTHORIZED", "an agent voids only an item it owns, before it ever reached doing")
        item["voided"] = {"reason": f["reason"], "survivor": f.get("survivor"), "by": who}
    elif event == "person_act":
        _person(item, f, rec, assurance, parked, used_acts)
    item["events"].append(rec["seq"])


def _create(items, f, rec, who, assurance):
    ident = rec.get("id")
    if parse_id(ident) is None:
        raise Refuse("MALFORMED", f"{ident!r} is not an item id")
    if parse_id(ident)[0] != f["project"]:
        raise Refuse("MALFORMED", "the id's project is not the create's project")
    if ident in items:
        raise Refuse("CONFLICT", f"{ident} was already created; the first stands")
    imported = rec.get("source") == "import"
    if rec.get("source") not in (None, "import"):
        raise Refuse("MALFORMED", "an unknown source")
    if imported and who == PERSON:
        raise Refuse("NOT_AUTHORIZED", "an import is never the person's act")
    epic = f.get("epic")
    if epic is not None and (epic == ident or epic not in items or items[epic]["kind"] != "epic" or
                             items[epic]["project"] != f["project"] or items[epic]["voided"]):
        raise Refuse("MALFORMED", "the epic must be an existing epic of the same project, not void, never the item "
                                  "itself")
    items[ident] = new_item(ident, f, who, assurance, rec["seq"], imported)


def _move(item, f, who, parked):
    frm, to = f["from"], f["to"]
    if item["state"] != frm:
        raise Refuse("STALE_VERSION", f"{item['id']} is {item['state']}, not {frm}")
    if frm == "parked" or to == "parked":
        raise Refuse("PARKED", "parking and bringing back are the person's own acts")
    if frm == "done":
        raise Refuse("TERMINAL", "done is terminal; the person may reopen")
    if to == "done":
        raise Refuse("BAD_EDGE", "nobody moves an item to done: the clauses derive it from review, or the person "
                                 "says so")
    if (frm, to) == ("review", "doing"):
        if who != item["reviewer"]:
            raise Refuse("NOT_AUTHORIZED", "only the named reviewer sends it back to doing")
        _not_held(item, parked)   # a way into doing, so the hold is for it too (round 4, low)
        item["state"] = "doing"
        return
    if (frm, to) not in OWNER_EDGES:
        raise Refuse("BAD_EDGE", f"{frm} -> {to} is not an agent's edge" + (" (ranking is the person's)" if to ==
                                                                              "next" else ""))
    if item["owner"] != who:
        raise Refuse("NOT_AUTHORIZED", f"{item['id']} is {item['owner'] or 'unassigned'}'s to move")
    if to == "doing":
        _not_held(item, parked)
        item["reached_doing"] = True
    if to == "review":
        rv = f.get("reviewer")
        if not rv or rv in (item["owner"], item["creator"]):
            raise Refuse("NOT_AUTHORIZED", "review names a reviewer, never the item's owner or creator")
        if not any(_deliverable(item, x) for x in item["links"]):
            raise Refuse("MALFORMED", "review needs a deliverable linked by a bound seat (a commit, a run record, "
                                      "a change)")
        item["reviewer"] = rv
    item["state"] = to


def _deliverable(item, link) -> bool:
    """A link that can stand for the work done: a commit, a run record or a change, linked by a bound seat (a create's
    own links are its creator's)."""
    return link.get("type") in DELIVERABLES and bound_link(item, link)


def bound_link(item, link) -> bool:
    """A link a bound seat made (a create's own links are its creator's); any other is a candidate only."""
    return link.get("assurance", item["creator_assurance"]) == "bound"


def holds(item, parked) -> tuple[list, list]:
    """(the parked decisions that hold the item: its bound links to them and its clauses; the parked decisions only a
    claimed or off-chain link names, which hold nothing and are shown as proposals) (round 4, finding 4a)."""
    links = [x for x in item["links"] if x["type"] == "decision" and x["ref"] in parked]
    held = {x["ref"] for x in links if bound_link(item, x)}
    held |= {c["register"] for c in item["clauses"] if c["kind"] == "jak-decision" and c["register"] in parked}
    return sorted(held), sorted({x["ref"] for x in links} - held)


def _not_held(item, parked):
    held = holds(item, parked)[0]
    if held:
        raise Refuse("HELD", f"held by {', '.join(held)}, which the person parked")


def clauses_hash(clauses) -> str:
    return hashlib.sha256(canonical(clauses).encode("utf-8")).hexdigest()[:8]


def _person(item, f, rec, assurance, parked, used_acts):
    """The person's act: bound, carrying the evidence of the turn that names it, used once, within its window."""
    ev = rec.get("evidence")
    if rec.get("who") != PERSON or assurance != "bound":
        raise Refuse("NOT_AUTHORIZED", "only the person's own act, bound to a turn of theirs, does this")
    if not isinstance(ev, dict) or not all(isinstance(ev.get(k), str) for k in ("session", "turn", "turn_at", "line")):
        raise Refuse("NOT_AUTHORIZED", "the person's act carries no evidence of their turn")
    act, value = f["act"], f.get("value")
    if act == "clauses":
        value = clauses_hash(f.get("clauses") or [])
    expect = act_line(item["id"], act, value)
    if expect is None or ev["line"] != expect:
        raise Refuse("NOT_AUTHORIZED", "the evidence's line is not this act")
    t0, t1 = when(ev["turn_at"]), when(rec.get("at"))
    if t0 is None or t1 is None or not 0 <= (t1 - t0).total_seconds() <= ACT_SECONDS:
        raise Refuse("UNDECIDABLE", "the turn is older than the act's window, or has no time")
    # used once: one transcript record, named by the sha256 of its span, authorizes at most one act (round 4, 1b), so
    # a turn is never used twice, whatever turn id or item the evidence names
    sp = ev.get("span") if isinstance(ev.get("span"), dict) else {}
    key = sp.get("sha256")
    if not (isinstance(key, str) and len(key) == 64):
        raise Refuse("NOT_AUTHORIZED", "the person's act names no span of their turn")
    if key in used_acts:
        raise Refuse("CONFLICT", "this turn of the person's was already used for an act; they say it again to use "
                                 "it again")
    _person_effect(item, act, f, value, parked)
    used_acts.add(key)


def _person_effect(item, act, f, value, parked):
    st = item["state"]
    if act in PERSON_MOVES or act == "done":
        if f.get("from") != st:
            raise Refuse("STALE_VERSION", f"{item['id']} is {st}, not {f.get('from')}")
        if st in ("done", "parked"):
            raise Refuse("TERMINAL" if st == "done" else "PARKED", f"the item is {st}")
        if act == "done":
            if st not in ("doing", "review"):
                raise Refuse("BAD_EDGE", "the person's word makes done from doing or review")
            item.update(state="done", done_by="word")
            return
        if act == "doing" and st != "doing":
            _not_held(item, parked)
        if act in ("doing", "review"):   # review lies past doing, however the person got it there (G6, finding 4)
            item["reached_doing"] = True
        item["state"] = act
    elif act == "park":
        if st in ("done", "parked"):
            raise Refuse("BAD_EDGE", f"a {st} item is not parked")
        item.update(parked_from=st, state="parked")
    elif act == "unpark":
        if st != "parked":
            raise Refuse("BAD_EDGE", "only a parked item is brought back")
        if item["parked_from"] == "doing":
            _not_held(item, parked)   # bringing it back into doing is a way into doing (round 4, low)
        item.update(state=item["parked_from"], parked_from=None)
    elif act == "reopen":
        if st != "done":
            raise Refuse("BAD_EDGE", "only a done item is reopened")
        _not_held(item, parked)   # reopen re-enters doing, and the hold is for everyone (ec.parked-holds)
        item.update(state="doing", done_by=None)
    elif act == "priority":
        item["priority"] = value
    elif act == "assign":
        item["owner"] = value
    elif act == "clauses":
        item["clauses"] = list(f.get("clauses") or [])
    elif act == "void":
        item["voided"] = {"reason": "the person's act", "survivor": None, "by": PERSON}
