"""`semantext work new|move|link|comment|list|show` (PM-DESIGN slice 1).

A write from the command line is recorded with assurance "claimed": the name is the shell's, and nothing the kernel can
stand behind. By design a claimed writer holds none of the table's rights (r2): its create files an item with no
owner, its move is a proposal, shown and not applied. `show` says so on every such line. There is no flag that names
who acts, when, or as whom: --as, --by, --time and the like are refused by the parser.
"""
from __future__ import annotations

import json
import unicodedata

from .events import KINDS, STATES   # only these at import: the hook builds this parser and must load no reader


def shown(text, cap: int, lines: bool = False) -> str:
    """An agent's text as text (the attack, F12): control and format characters removed, capped."""
    out = []
    for c in str(text or ""):
        if lines and c == "\n":
            out.append(c)
        elif unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp"):
            out.append(" " if c in "\t\r" else "")
        else:
            out.append(c)
    s = "".join(out)
    return s if len(s) <= cap else s[:cap - 1] + "…"


def _link(text: str) -> dict:
    kind, sep, ref = str(text).partition(":")
    return {"type": kind, "ref": ref} if sep else {"type": "", "ref": text}


def _say(r: dict, what: str, out) -> None:
    if r.get("repeat"):
        out(f"{r['id']}: already recorded (the same request_key and request), seq {r['seq']}")
    elif r["proposal"]:
        out(f"{r['id']}: {what} recorded as a PROPOSAL, not applied: this shell's name is claimed, and a claimed "
            f"writer holds no rights. A seat does it through the kernel's tool, or the person does.")
    else:
        item = r["item"] or {}
        owner = item.get("owner") or "nobody (a claimed create names no owner)"
        out(f"{r['id']}: {what} recorded (seq {r['seq']}, {r['assurance']}). Now {item.get('state')}, owner {owner}.")


def cmd_work(store, args, out=print) -> int:
    from ..agents import Agents
    from .writer import Writer, cli_actor
    w = Writer(store.root)
    actor = cli_actor(Agents(store.root).identify().name)
    # an empty key goes to the writer, which refuses it: dropped, a retry with an unset variable would record twice
    key = {"request_key": args.request_key} if getattr(args, "request_key", None) is not None else {}
    a = args.work_action
    if a == "new":
        req = {"project": args.project, "title": args.title, "kind": args.kind, **key}
        if args.text:
            req["text"] = args.text
        if args.epic:
            req["epic"] = args.epic
        if args.link:
            req["links"] = [_link(x) for x in args.link]
        if args.clause:
            req["clauses"] = [json.loads(x) for x in args.clause]
        _say(w.write(actor, "create", req), "created", out)
    elif a == "move":
        req = {"id": args.id, "from": args.from_state, "to": args.to_state, **key}
        if args.reviewer:
            req["reviewer"] = args.reviewer
        _say(w.write(actor, "move", req), f"{args.from_state} -> {args.to_state}", out)
    elif a == "link":
        _say(w.write(actor, "link", {"id": args.id, "link": _link(args.link), **key}), "link", out)
    elif a == "unlink":
        _say(w.write(actor, "unlink", {"id": args.id, "link": _link(args.link), **key}), "unlink", out)
    elif a == "comment":
        _say(w.write(actor, "comment", {"id": args.id, "text": " ".join(args.words), **key}), "comment", out)
    elif a == "list":
        _list(w.state(), args, out)
    elif a == "show":
        return _show(w.state(), args.id, out)
    return 0


def _list(st, args, out) -> None:
    items = sorted(st["items"].values(), key=lambda i: (i["project"], i["n"]))
    items = [i for i in items if (args.project is None or i["project"] == args.project) and
             (args.all or (not i["voided"] and i["state"] not in ("done",)))]
    if not items:
        out("No work items." if not st["items"] else "No open work items (--all shows done and void ones).")
    for i in items:
        mark = "  [void]" if i["voided"] else ""
        out(f"{i['id']:<22} {i['state']:<8} {i['owner'] or '-':<14} {shown(i['title'], 80)}{mark}")
    _problems(st, out)


def _show(st, ident, out) -> int:
    i = st["items"].get(ident)
    rows = [e for e in st["events"] if e["id"] == ident]
    if i is None:
        out(f"No item {ident}." + (f" {len(rows)} event(s) name it, none applied." if rows else ""))
    else:
        out(f"{i['id']}  {shown(i['title'], 200)}")
        out(f"  written by {i['creator']} ({i['creator_assurance']}){'; imported' if i['source'] else ''}")
        out(f"  state {i['state']}" + (" (the person's word)" if i["done_by"] == "word" else "") +
            f"; owner {i['owner'] or 'nobody'}; reviewer {i['reviewer'] or 'none'}; priority {i['priority'] or '-'}"
            + (f"; epic {i['epic']}" if i["epic"] else "") + (f"; VOID: {shown(i['voided']['reason'], 200)}"
                                                              if i["voided"] else ""))
        if i["held_by"]:
            out(f"  held by {', '.join(i['held_by'])} (parked by the person)")
        if i.get("hold_proposed"):
            out(f"  a claimed link names {', '.join(i['hold_proposed'])} (parked): a proposal, holding nothing")
        if i["text"]:
            out("  " + shown(i["text"], 2000, lines=True).replace("\n", "\n  "))
        for x in i["links"]:
            by = f" (linked by {x['by']}, {x['assurance']})" if "by" in x else ""
            out(f"  link {x['type']}:{x['ref']}{by}: a candidate, never proof by itself")
        for c in i["clauses"]:
            out(f"  clause {json.dumps(c, sort_keys=True)}")
        for c in i["comments"]:
            out(f"  comment by {c['who']} ({c['assurance']}): {shown(c['text'], 500)}")
        for p in i["proposals"]:
            out(f"  proposal by {p['who']} ({p['assurance']}): {p['what']}{' to ' + p['to'] if p['to'] else ''}")
    out("  history:")
    for e in rows:
        # every field of a row may come from a line nobody's writer wrote: each is shown as text (round 4, low)
        s = {k: shown(e.get(k), 200) for k in ("seq", "at", "event", "who", "assurance", "effective", "code",
                                                 "reason")}
        if e["applied"]:
            what = "applied"
        elif e["code"] == "PROPOSAL":
            what = f"PROPOSAL, not applied: {s['who']} is {s['effective']}, and a claimed writer holds no rights"
        else:
            what = f"NOT APPLIED: {s['code']}: {s['reason']}"
        out(f"    {s['seq']}  {s['at']}  {s['event']:<16} {s['who']} ({s['assurance']})  {what}")
    _problems(st, out)
    return 0 if i is not None else 1


def _problems(st, out) -> None:
    """What the fold could not trust, as `list` says it: a store that does not match its head first."""
    if not st.get("intact", True):
        out("  the store is not whole: it does not match its head (cut, edited or reordered), so nothing in it is "
            "trusted")
    for p in st["problems"]:
        out(f"problem: line {p['line']}: {p['kind']}: {p['text']}")


def register(add) -> None:
    """Adds `work` to the command line; `add` is cli.build_parser's own helper."""
    sp = add("work", cmd_work, "work items: new, move, link, unlink, comment, list, show (a write from here is claimed and "
                               "holds no rights; see `semantext work show`)")
    sub = sp.add_subparsers(dest="work_action", metavar="<action>", required=True)
    n = sub.add_parser("new", help="file an item (from here it has no owner until a seat takes it)")
    n.add_argument("--project", required=True, help="the project, as the seats or projects file names it")
    n.add_argument("--title", required=True)
    n.add_argument("--kind", choices=KINDS, default="task")
    n.add_argument("--text")
    n.add_argument("--epic", help="the epic it belongs to, an item id")
    n.add_argument("--link", action="append", metavar="TYPE:REF", help="a link, e.g. commit:1a2b3c4 (repeat it)")
    n.add_argument("--clause", action="append", metavar="JSON", help="an acceptance clause as JSON (repeat it)")
    m = sub.add_parser("move", help="move an item: from-state to-state (a proposal from here)")
    m.add_argument("id")
    m.add_argument("from_state", choices=STATES)
    m.add_argument("to_state", choices=STATES)
    m.add_argument("--reviewer", help="for review: the seat that reviews it")
    li = sub.add_parser("link", help="link an item to a card, commit, run record, post, requirement or item")
    li.add_argument("id")
    li.add_argument("link", metavar="TYPE:REF")
    ul = sub.add_parser("unlink", help="undo a link (one a bound seat made: a proposal from here)")
    ul.add_argument("id")
    ul.add_argument("link", metavar="TYPE:REF")
    c = sub.add_parser("comment", help="comment on an item")
    c.add_argument("id")
    c.add_argument("words", nargs="+")
    for p in (n, m, li, ul, c):
        p.add_argument("--request-key", help="a key that makes a retry of this request record it once")
    ls = sub.add_parser("list", help="the open items")
    ls.add_argument("--project")
    ls.add_argument("--all", action="store_true", help="done and void items too")
    sh = sub.add_parser("show", help="one item, its links, clauses and every event with its assurance")
    sh.add_argument("id")
