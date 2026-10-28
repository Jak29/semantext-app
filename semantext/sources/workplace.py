"""The Work place: the Work source's answer (sources/work.py), with each link's live state read from the other
sources of the same build (PM-DESIGN r5, the layout; slice 2).

A link only points at a candidate (r4); its badge is what the source it names says now, in words:
  card       the Waiting reader's card of that id: "waiting on your word", "answered", "run", "parked";
  decision   the register's entry: its status ("in force", "parked", "reopened"), or "not in your register";
  item       the linked item's status on this board, or "no such item";
and "not read yet" for a kind no reader reads here (a commit, a run record, a board post ...). A card that still waits
for the person's word puts "waiting on <card id>" on the item (r4: waiting-on comes from links). The page has no write
path: this place only reads.
"""
from __future__ import annotations

CARD_WORDS = {"waiting": "waiting on your word", "closed": "answered", "run": "answered (run)", "parked": "parked"}
NOT_READ = "not read yet"


def _cards(src) -> dict:
    by = {}
    for c in (src.get("waiting") or {}).get("cards") or []:
        cid = c.get("id")
        if isinstance(cid, str):
            by.setdefault(cid, []).append(c.get("state"))
    return by


def _decisions(src) -> dict:
    by = {}
    for e in (src.get("record") or {}).get("entries") or []:
        if isinstance(e.get("id"), str):
            by.setdefault(e["id"], e.get("computed_status"))
    return by


def reader(cards: dict, decisions: dict, items: dict):
    """read_link for clauses.link_badges: one link's state in words, or None (shown "unknown")."""
    def read(link):
        t, ref = link.get("type"), link.get("ref")
        if t == "card":
            states = cards.get(ref)
            if not states:
                return {"state": "not among your cards"}
            st = "waiting" if "waiting" in states else states[0]
            return {"state": CARD_WORDS.get(st, str(st))}
        if t == "decision":
            return {"state": decisions[ref] if ref in decisions and decisions[ref] else "not in your register"}
        if t == "item":
            i = items.get(ref)
            return {"state": i["status_word"] if i else "no such item"}
        return {"state": NOT_READ}
    return read


def work_place(src) -> dict:
    from ..work.clauses import link_badges
    w = src.get("work") or {}
    if w.get("off"):
        return {"off": True, "failed": w.get("failed"), "items": [], "asks": [], "ranking": []}
    items = [dict(i) for i in w.get("items") or []]
    by_id = {i["id"]: i for i in items}
    cards = _cards(src)
    read = reader(cards, _decisions(src), by_id)
    for i in items:
        i["links"] = link_badges(i, read)
        for x in i["links"]:
            if x["type"] == "card" and "waiting" in (cards.get(x["ref"]) or []) and x["ref"] not in i["waiting_on"]:
                i["waiting_on"] = i["waiting_on"] + [x["ref"]]
                if i["shown"] != "done" and not i["voided"]:
                    i["badges"] = i["badges"] + [f"waiting on {x['ref']}"]
    return {k: v for k, v in w.items() if k not in ("problems", "items")} | {"items": items, "off": False}
