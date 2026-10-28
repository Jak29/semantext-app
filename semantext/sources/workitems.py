"""One work item as the page shows it: the fold's item, its clauses judged now, its status and badges in words, what it
waits on, and what of it waits on the person (PM-DESIGN r4, r5; the Work source, sources/work.py, calls this).

The fold's state is never changed here. The status words follow r2 and r5:
  done (your word)        the person's own act made it done (the fold's done_by "word"), its turn checked again;
  done (checked)          in review, and every clause is met now by evidence a reader can see;
  done (claimed)          in review, no clause unmet, and at least one that no reader can see (unknown);
  proof no longer holds   in review, and evidence that met a clause no longer meets it (stale);
and otherwise the fold's own state. What waits on the person: a pending propose_park or propose_reassign, an item in
review with no clause (nothing can derive its done, so only the person's word ends it), and an item in backlog (the
next edge, ranking, is the person's). Each ask carries the exact line the kernel accepts (turns.act_line).
"""
from __future__ import annotations

from .work import HISTORY_CAP, TEXT_CAP, WORD, _shown

# The inbox carries park, bring back and done (the person's word) in slice 4 (r5); ranking and reassigning are typed.
INBOX_ACTS = ("park", "unpark", "done")
COMMENT_CAP = 50   # comments shown per item, the newest kept; the rest are counted (comments_more)


def _judge(item, readers, now, ctx=None):
    from ..work import clauses
    return clauses.evaluate(item, readers, now, ctx)


def status(item: dict, judged: list) -> tuple[str, str | None]:
    """(shown state, status word key or None) from the fold's item and its judged clauses."""
    st = item["state"]
    states = {j["state"] for j in judged}
    if st == "done":
        return "done", "done-word" if item.get("done_by") == "word" else "done-checked"
    if st != "review" or not judged:
        return st, None
    if "stale" in states:
        return "review", "proof-gone"
    if states == {"met"}:
        return "done", "done-checked"
    if "unmet" not in states:
        return "done", "done-claimed"
    return "review", None


def _pending(item: dict, rows: list) -> list:
    """The proposals the person has not yet answered: the newest of each kind, while what it asks is not so."""
    later = {}
    for r in rows:
        if r["event"] == "person_act" and r["applied"] and r["act"]:
            later[r["act"]] = max(later.get(r["act"], 0), r["seq"] or 0)
    out, seen = [], set()
    for p in reversed(item["proposals"]):
        if p["what"] in seen:
            continue
        seen.add(p["what"])
        if p["what"] == "park":
            open_ = item["state"] not in ("parked", "done") and later.get("park", 0) < (p["seq"] or 0)
        else:
            open_ = item["state"] != "done" and item["owner"] != p["to"] and later.get("assign", 0) < (p["seq"] or 0)
        if open_:
            out.append(p)
    return list(reversed(out))


def _ask(item, act, value, why, who, assurance=None):
    from ..work.turns import act_line
    return {"act": act, "line": act_line(item["id"], act, value), "why": why, "who": who, "assurance": assurance,
            "pressed": act in INBOX_ACTS}


def inbox_link(item, known) -> tuple[str | None, str | None]:
    """(the inbox's link for this item, or None and why not): jak-inbox://work/<project>/<n>, which only selects and
    shows the item there (r5). The project must be one the seats file names."""
    from ..work.events import WorkRefused
    from ..work.turns import deep_link
    try:
        return deep_link(item["id"], known), None
    except WorkRefused:
        return None, f"no inbox link: {item['project']} is not a project in your seats file"


def _asks(item, judged, pending) -> list:
    if item["voided"]:
        return []
    out = []
    for p in pending:   # each proposer with its assurance: a claimed name is the shell's, never a seat the kernel knows
        by = f"{p['who']} ({p['assurance']})"
        if p["what"] == "park":
            out.append(_ask(item, "park", None, f"{by} proposes parking it", p["who"], p["assurance"]))
        elif p["to"]:
            out.append(_ask(item, "assign", p["to"], f"{by} proposes giving it to {p['to']}", p["who"],
                            p["assurance"]))
    if item["state"] == "review" and not judged:
        out.append(_ask(item, "done", None, "in review with no acceptance clause: only your word makes it done",
                        item["owner"]))
    return out


def _next_edge(item, shown):
    if item["voided"] or shown == "done":
        return None
    return {"backlog": "ranking", "next": "owner", "doing": "owner", "review": "reviewer", "parked": "person"}.get(
        item["state"])


def _waits(item, judged, shown) -> str | None:
    """Who and what the item waits on, in one line (r5: the review column says who and what)."""
    if item["voided"] or shown == "done":
        return None
    if item["held_by"]:
        return "held by " + ", ".join(item["held_by"]) + ", which you parked"
    if item["state"] == "review":
        unmet = [j for j in judged if j["state"] != "met"]
        who = f"{item['reviewer']}'s review" if item["reviewer"] else "a review"
        return f"waits on {who}" + (f" and {len(unmet)} of {len(judged)} clauses" if unmet else "")
    if item["state"] == "backlog":
        return "waits on your ranking (backlog to next)"
    if item["state"] == "parked":
        return "parked by you; only you bring it back"
    if not item["owner"]:
        return "waits on a seat to take it (no owner)"
    return f"with {item['owner']}"


def item_view(item: dict, rows: list, readers, now, known, ctx=None) -> dict:
    """The page's record of one item. `ctx` is the build's closures (closed.ReadContext)."""
    got = _judge(item, readers, now, ctx)
    judged = got["clauses"]
    shown, key = status(item, judged)
    pending = _pending(item, rows)
    badges = [WORD[key]] if key else []
    badges += [f"held by {h}" for h in item["held_by"]]
    # a claimed or off-chain link to a parked decision holds nothing: shown as a proposal (round 4, finding 4a)
    badges += [f"proposed hold {h} (a claimed link; holds nothing)" for h in item.get("hold_proposed") or []]
    badges += [f"waiting on {w}" for w in item["waiting_on"] if shown != "done"]
    if item["voided"]:
        badges.append("void")
    if not item["owner"] and not item["voided"]:
        badges.append("no owner")
    if item["source"] == "import":
        badges.append("imported")
    if item["creator_assurance"] != "bound":
        badges.append(f"filed {item['creator_assurance']}")
    shown_rows = rows[-HISTORY_CAP:]
    from ..work.turns import act_line
    link, no_link = inbox_link(item, known)
    edge = _next_edge(item, shown)
    return {
        "id": item["id"], "project": item["project"], "n": item["n"], "title": _shown(item["title"], 200),
        "text": _shown(item["text"], TEXT_CAP, lines=True), "kind": item["kind"], "state": item["state"],
        "shown": shown, "status": key, "status_word": WORD[key] if key else item["state"], "badges": badges,
        "owner": item["owner"], "creator": item["creator"], "creator_assurance": item["creator_assurance"],
        "reviewer": item["reviewer"], "priority": item["priority"], "epic": item["epic"],
        "epic_path": item["epic_path"], "voided": item["voided"], "done_by": item["done_by"], "source": item["source"],
        "links": [{k: x.get(k) for k in ("type", "ref", "by", "assurance")} for x in item["links"]],
        "clauses": judged, "held_by": item["held_by"], "hold_proposed": list(item.get("hold_proposed") or []),
        "waiting_on": list(item["waiting_on"]) if shown != "done" else [],
        "waits": _waits(item, judged, shown), "next_edge": edge,
        "rank_line": act_line(item["id"], "next") if edge == "ranking" else None,
        "inbox": link, "no_inbox": no_link,
        "proposals": [{**p, "text": _shown(p.get("text"), 300), "pending": p in pending} for p in item["proposals"]],
        "comments": [{**c, "text": _shown(c["text"], 2000, lines=True)} for c in item["comments"][-COMMENT_CAP:]],
        "comments_more": max(0, len(item["comments"]) - COMMENT_CAP),   # counted, as the history is (finding 21)
        "asks": _asks(item, judged, pending), "history": shown_rows,
        "history_more": len(rows) - len(shown_rows),
    }
