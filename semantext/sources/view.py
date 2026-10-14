"""The page's places: what the person sees, built from the five readers, with nothing written anywhere.

The page has four places, each one click from the others. Waiting is the home: every card an agent filed for the
person's word, card for card as their own inbox shows it, with what this page adds beside each card (the person's
earlier words that cite it, who asks and who acts, and the project it belongs to). Projects shows each repository with
its agents, its gates, its cards and its documents. The map shows the whole, under the person's own word for it, in
levels: its groups, their environments (each agent's home) and the projects each agent works in. The Record shows every
decision as threads. Drawers show an agent, the rules, one worktree's gates and one project's documents.

Every answer carries the frame: the person's word for the whole, how many cards wait, which sources are off and every
problem any reader reported, so the problems banner shows wherever the person is.

This module reads through the readers alone, which open files for reading only. It writes nothing, starts nothing and
keeps nothing between two answers: every number is measured when it is asked for.

The config may name a group. Then only the agents in that group are shown, as the person's own inbox reads only its
group's seats; the readers may already have left the others out, and leaving them out again changes nothing.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import cards, config_path, gates, load_config, places, record, rules

ROUTES = ("waiting", "projects", "map", "record", "rules", "sources")
READERS = (("waiting", cards), ("record", record), ("rules", rules), ("gates", gates), ("places", places))
NAMES = {"waiting": "Waiting", "record": "Record", "rules": "Rules", "gates": "Gates", "places": "Places",
         "sources": "Sources"}
UNAVAILABLE = "Semantext: unavailable"
TEXT = ("title", "why", "question", "options", "command", "does", "undo")   # the words an agent writes to ask
# An id as a card or a decision carries it: one or two capitals, a date, a time or a number, and sometimes a number
# after that (X-20261010-195202-2 is another card than X-20261010-195202, so the number is part of the id).
ID = re.compile(r"(?<![A-Za-z0-9_])[A-Z]{1,2}-\d{8}-\d{1,6}(?:-\d{1,3})?(?![A-Za-z0-9_])")
# The gate words, worst first. A worktree whose words hold one of BROKEN can let a commit or a push through unchecked.
WORST = ("off", "checks nothing", "open", "stranded", "unknown", "folder gone", "gated, identity declared")
BROKEN = ("off", "checks nothing", "open", "stranded")
NO_PROJECT = "unassigned"


# ---- small things ---------------------------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _n(count: int, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else plural or word + 's'}"


def _key(path) -> str:
    """A path as it is compared: separators and case as this system treats them."""
    return os.path.normcase(os.path.normpath(str(path))) if path else ""


def _inside(child: str, parent: str) -> bool:
    return bool(child and parent) and (child == parent or child.startswith(parent.rstrip("\\/") + os.sep))


def _stamp(at) -> float:
    """When a card was filed, as a number for ordering, the way the inbox orders cards; 0 when it cannot be read."""
    try:
        when = datetime.fromisoformat(str(at).strip().replace("Z", "+00:00"))
        return when.timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return 0.0


def newest_first(items: list) -> list:
    """Cards newest first, as the inbox orders them: by when each was filed, the earlier in the list first on a tie."""
    return [c for _, c in sorted(enumerate(items), key=lambda t: (-_stamp(t[1].get("at")), t[0]))]


def word_of(name) -> str | None:
    """The person's word for the whole as a link writes it: lower case, any run of other characters as one hyphen.
    None when there is no word, or when it would take the name of a place of the page."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").casefold()).strip("-")
    return slug if slug and slug not in (*ROUTES, "v2") else None


# ---- the config -----------------------------------------------------------------------------------------------
def config_file(home=None) -> Path:
    """The person's sources file: the one SEMANTEXT_SOURCES names, else sources.json in the home given (the home the
    server was started with), else the default home's."""
    named = os.environ.get("SEMANTEXT_SOURCES")
    if named:
        return Path(named).expanduser()
    return Path(home) / "sources.json" if home else config_path()


def _config(home=None) -> tuple[dict, Path, dict | None]:
    """(config, its file, a problem): a sources file that cannot be read is a problem to show, never a failed page."""
    path = config_file(home)
    try:
        return load_config(path), path, None
    except Exception as e:  # noqa: BLE001  whatever is wrong with the file, every place still answers
        return {}, path, {"reader": "sources", "source": str(path), "line": None, "kind": "unreadable",
                          "text": f"your sources file cannot be read ({type(e).__name__}: {e})"[:300]}


def _route(name: str, cfg: dict) -> str | None:
    if name in ROUTES:
        return name
    word = word_of(cfg.get("name"))
    return "map" if word and name == word else None


# ---- reading ------------------------------------------------------------------------------------------------------
def _read(cfg: dict, world=None) -> tuple[dict, list]:
    """Every reader's answer on this config, and a problem for each reader that stopped: one that fails costs the page
    that reader's part, never the rest."""
    got, failed = {}, []
    for name, module in READERS:
        try:
            got[name] = module.load(cfg, world) if module is gates and world is not None else module.load(cfg)
        except Exception as e:  # noqa: BLE001
            got[name] = {"off": True, "failed": f"{type(e).__name__}: {e}", "problems": []}
            failed.append({"reader": name, "source": "", "line": None, "kind": "reader stopped",
                           "text": f"the {NAMES[name]} reader stopped ({type(e).__name__}: {e})"[:300]})
    return got, failed


def _allowed(cfg: dict, got: dict) -> set | None:
    """The agents in the config's group, by name, or None when no group is named (every agent is shown)."""
    group = cfg.get("group")
    if not group:
        return None
    names = {s.get("seat") for s in got["waiting"].get("seats") or [] if group in (s.get("groups") or [])}
    names |= {a.get("name") for a in got["places"].get("agents") or [] if group in (a.get("groups") or [])}
    return {n for n in names if n}


def _prune(node, keep: set):
    """A level of the map with only the agents kept: a group or an environment left with nobody in it goes."""
    if not isinstance(node, dict):
        return node
    members = [m for m in node.get("members") or [] if m.get("agent_id") in keep]
    children = [c for c in (_prune(ch, keep) for ch in node.get("children") or []) if c is not None]
    if node.get("kind") != "whole" and not members and not children:
        return None
    return {**node, "members": members, "children": children}


def _in_group(got: dict, allowed: set | None) -> dict:
    if allowed is None:
        return got
    c = dict(got["waiting"])
    c["seats"] = [s for s in c.get("seats") or [] if s.get("seat") in allowed]
    c["cards"] = [x for x in c.get("cards") or [] if x.get("seat") in allowed]
    p = dict(got["places"])
    agents = [a for a in p.get("agents") or [] if a.get("name") in allowed]
    keep = {a.get("id") for a in agents}
    shown = []
    for proj in p.get("projects") or []:
        homes = proj.get("home_of") or []
        if homes and not any(h in allowed for h in homes):
            continue   # the home of an agent outside the group
        shown.append({**proj, "members": [m for m in proj.get("members") or [] if m.get("agent_id") in keep]})
    p.update(agents=agents, projects=shown, levels=_prune(p.get("levels"), keep),
             documents=[d for d in p.get("documents") or [] if d.get("agent") in allowed])
    g = dict(got["gates"])
    g["repos"] = [r for r in g.get("repos") or [] if r.get("seat") is None or r.get("seat") in allowed]
    return {**got, "waiting": c, "places": p, "gates": g}


def _off(got: dict) -> dict:
    """Each source that is off, with the keys the sources file would need to turn it on."""
    needs = {"waiting": ["seats", "inbox"], "record": ["register"], "rules": ["cards"], "gates": ["seats"],
             "places": ["seats", "map"]}
    out = {}
    for name, part in got.items():
        if part.get("off"):
            out[name] = {"missing": part.get("missing") or needs[name], "failed": part.get("failed")}
        elif part.get("missing"):
            out[name] = {"missing": part["missing"], "failed": None, "partly": True}
    return out


class _Sources:
    """One answer's reading: the config, every reader's answer for the group, and the problems, gathered once."""

    def __init__(self, home=None, world=None):
        self.cfg, self.path, trouble = _config(home)
        got, failed = _read(self.cfg, world)
        self.allowed = _allowed(self.cfg, got)
        self.got = _in_group(got, self.allowed)
        self.problems = ([trouble] if trouble else []) + failed + [
            {"reader": name, **p} for name, _ in READERS for p in self.got[name].get("problems") or []]
        self._cards = None
        self._projects = None

    # -- the frame every place carries
    def frame(self) -> dict:
        c = self.got["waiting"]
        return {"name": self.cfg.get("name"), "word": word_of(self.cfg.get("name")), "group": self.cfg.get("group"),
                "checked": _now(), "config": str(self.path),
                "waiting": sum(x.get("state") == "waiting" for x in c.get("cards") or []),
                "seats": [s.get("seat") for s in c.get("seats") or []], "off": _off(self.got),
                "problems": self.problems}

    # -- cards, as every place shows them
    def projects_list(self) -> list:
        return self.got["places"].get("projects") or []

    def card_views(self) -> list[dict]:
        if self._cards is None:
            joiner = _Cards(self)
            self._cards = [joiner.view(c) for c in self.got["waiting"].get("cards") or []]
        return self._cards


class _Cards:
    """What the page adds to a card: the earlier words that cite it, its project, and the notes its reader left on it."""

    def __init__(self, src: _Sources):
        rec = src.got["record"]
        self.entries = {e.get("id"): e for e in rec.get("entries") or [] if e.get("id")}
        self.index = rec.get("cards") or {}
        self.projects = src.projects_list()
        self.names = {p.get("id"): p.get("name") for p in self.projects}
        c = src.got["waiting"]
        self.files = {s.get("seat"): s.get("file") for s in c.get("seats") or []}
        self.notes: dict = {}
        for p in c.get("problems") or []:
            if p.get("shown"):
                self.notes.setdefault((_key(p.get("source")), p.get("line")), []).append(p.get("text"))

    def view(self, c: dict) -> dict:
        closing, run = c.get("closing"), c.get("run")
        file = self.files.get(c.get("seat"))
        return {
            "key": f"{c.get('seat')}/{c.get('id')}",
            **{k: c.get(k) for k in ("seat", "id", "kind", "title", "why", "question", "command", "does", "undo", "cwd",
                                     "at", "state", "parked_at", "asks", "asks_basis", "acts", "acts_basis", "line")},
            "options": [o for o in c.get("options") or [] if isinstance(o, str)],
            "closing": {"at": closing.get("at"), "how": closing.get("how"),
                        "earlier": len(closing.get("earlier") or [])} if isinstance(closing, dict) else None,
            "run": {k: run.get(k) for k in ("started", "finished", "exit", "timed_out")} if isinstance(run, dict)
            else None,
            "file": file,
            "notes": self.notes.get((_key(file), c.get("line")), []),
            "project": self.place(c),
            "earlier": self.earlier(c),
        }

    def place(self, c: dict) -> dict | None:
        try:
            at = places.placement(c, self.projects)
        except Exception:  # noqa: BLE001  a card that cannot be placed is shown unplaced
            return None
        pid = at.get("project") if isinstance(at, dict) else None
        if not pid:
            return None
        return {"id": pid, "name": self.names.get(pid), "via": at.get("via"), "field": at.get("field")}

    def earlier(self, c: dict) -> list[dict]:
        """The person's earlier words beside a card: each decision that cites the card, each decision the card cites,
        and each decision that cites an id the card cites. Every join is by the exact id."""
        own = c.get("id")
        found: dict[str, str] = {}
        for eid in self.index.get(own) or []:
            found.setdefault(eid, "cites this card")
        for cid in cited(c):
            if cid == own:
                continue
            if cid in self.entries:
                found.setdefault(cid, "this card cites it")
            for eid in self.index.get(cid) or []:
                found.setdefault(eid, f"cites {cid}, which this card cites")
        rows = sorted((self.entries[e] for e in found if e in self.entries),
                      key=lambda e: (e.get("date") or "", e.get("line") or 0), reverse=True)
        return [{"id": e.get("id"), "date": e.get("date"), "status": e.get("computed_status") or e.get("stored_status"),
                 "words": e.get("words"), "subject": e.get("subject"), "link": found[e.get("id")]} for e in rows]


def cited(card: dict) -> list[str]:
    """The ids written in the words an agent asked in, in the order written, each once."""
    out: list[str] = []
    for field in TEXT:
        value = card.get(field)
        for text in value if isinstance(value, list) else [value]:
            if isinstance(text, str):
                out += [i for i in ID.findall(text) if i not in out]
    return out


# ---- gates ----------------------------------------------------------------------------------------------------
def gate_words(w: dict) -> list[str]:
    """A worktree's states in plain words: the reader's words, "stranded" when a hook exists that git cannot reach, and
    "unknown" or "folder gone" when the reader has no verdict."""
    status = w.get("status")
    if status == "missing":
        return ["folder gone"]
    if status == "unknown":
        return ["unknown"]
    words = [x for x in w.get("words") or [] if isinstance(x, str)]
    if any(v.get("stranded") for v in w.get("verdicts") or [] if isinstance(v, dict)):
        words.append("stranded")
    return words or ["unknown"]


def worst(words) -> str | None:
    words = [w for w in words if w]
    return min(words, key=lambda w: WORST.index(w) if w in WORST else len(WORST)) if words else None


def _short(path, base) -> str:
    """A worktree's path from its project's folder ("." for the folder itself), or in full when it lies elsewhere."""
    try:
        rel = os.path.relpath(os.path.normpath(str(path)), os.path.normpath(str(base)))
    except (ValueError, TypeError):
        return str(path)
    if rel == ".":
        return "."
    return str(path) if rel.startswith("..") else rel.replace("\\", "/")


def _worktree(w: dict, base) -> dict:
    words = gate_words(w)
    return {"path": w.get("path"), "short": _short(w.get("path"), base), "name": w.get("name"), "main": w.get("main"),
            "exists": w.get("exists"), "locked": w.get("locked"), "status": w.get("status"), "read": w.get("read"),
            "set": w.get("set") or [], "words": words, "worst": worst(words),
            "broken": any(x in BROKEN for x in words), "events": w.get("events") or [],
            "hooks_path": w.get("hooks_path"), "hooks_dir": w.get("hooks_dir"), "reachable": w.get("reachable") or [],
            "identity": w.get("identity"), "uncertain": w.get("uncertain") or [], "note": w.get("note"),
            "files": w.get("files") or [],
            "open": [e for v in w.get("verdicts") or [] if isinstance(v, dict) for e in v.get("open") or []],
            "stranded": [s for v in w.get("verdicts") or [] if isinstance(v, dict) for s in v.get("stranded") or []]}


def _gates_of(project: dict, repos: dict) -> dict:
    repo = repos.get(_key(project.get("path")))
    trees = [_worktree(w, project.get("path")) for w in (repo or {}).get("worktrees") or []]
    words = [x for t in trees for x in t["words"]]
    return {"found": repo is not None, "repo": (repo or {}).get("name"), "present": (repo or {}).get("present"),
            "worktrees": trees, "worst": worst(words), "broken": sum(t["broken"] for t in trees),
            "by_word": dict(Counter(t["worst"] for t in trees if t["worst"]))}


# ---- the places -----------------------------------------------------------------------------------------------
def holds(src: _Sources) -> dict:
    """What holds, in one line, measured now: the person's decisions in force, the problems in their files, and the
    gates a static read finds broken. The page shows it when nothing waits."""
    rec, parts = src.got["record"], []
    in_force = parked = None
    if rec.get("off"):
        parts.append("Your register is off, so your decisions are not counted")
    else:
        by = (rec.get("counts") or {}).get("by_status") or {}
        in_force, parked = by.get("in force", 0), by.get("parked", 0)
        parts.append(f"Your word holds: {_n(in_force, 'decision')} in force"
                     + (f" and {parked} parked" if parked else ""))
    problems = src.problems
    if problems:
        first = problems[0]
        where = Path(str(first.get("source") or "")).parts[-2:]
        parts.append(f"{_n(len(problems), 'problem')} in your files; the first: "
                     + (f"{os.sep.join(where)}: " if where else "") + str(first.get("text") or ""))
    else:
        parts.append("No problem in your files")
    trees = {_key(w.get("path")): w for r in src.got["gates"].get("repos") or [] for w in r.get("worktrees") or []}
    repo_of = {_key(w.get("path")): r.get("root") for r in src.got["gates"].get("repos") or []
               for w in r.get("worktrees") or []}
    if not src.got["gates"].get("off") and trees:
        said = []
        verbs = {"off": ("is off", "are off"), "checks nothing": ("checks nothing", "check nothing"),
                 "open": ("is open", "are open")}
        found = {k: worst(gate_words(w)) for k, w in trees.items()}
        for word, (one, many) in verbs.items():
            hit = [k for k, w in found.items() if w == word]
            if hit:
                repos = len({repo_of[k] for k in hit})
                said.append(f"{_n(len(hit), 'worktree')} in {_n(repos, 'repo')} {one if len(hit) == 1 else many}")
        unread = sum(w in ("unknown", "folder gone") for w in found.values())
        if not said and not unread:
            said.append("every worktree is gated, identity declared")
        if unread:
            said.append(f"{_n(unread, 'worktree')} could not be read")
        parts.append("Gates (read): " + "; ".join(said))
    return {"text": ". ".join(parts) + ".", "in_force": in_force, "parked": parked, "problems": len(problems)}


def waiting_place(src: _Sources) -> dict:
    c = src.got["waiting"]
    views = src.card_views()
    by_state = Counter(v["state"] for v in views)
    rec = src.got["record"]
    states = list(dict.fromkeys(("waiting", "parked", "closed", "run", *by_state)))
    return {"off": bool(c.get("off")), "missing": c.get("missing") or [], "cards": views,
            "counts": {"cards": len(views), "by_state": {s: by_state.get(s, 0) for s in states}},
            "seats": [s.get("seat") for s in c.get("seats") or []],
            "projects": [{"id": p.get("id"), "name": p.get("name")} for p in src.projects_list()],
            "record": {"off": bool(rec.get("off")),
                       "parked": ((rec.get("counts") or {}).get("by_status") or {}).get("parked", 0)},
            "holds": holds(src)}


def _project_rows(src: _Sources) -> tuple[list, dict]:
    if src._projects is None:
        repos = {_key(r.get("root")): r for r in src.got["gates"].get("repos") or []}
        views = src.card_views()
        docs = src.got["places"].get("documents") or []
        rows = []
        for p in src.projects_list():
            rows.append({k: p.get(k) for k in ("id", "name", "root", "path", "exists", "home_of", "others",
                                                "identity")}
                        | {"agents": p.get("members") or [], "gates": _gates_of(p, repos), "cards": [],
                           "waiting": [], "documents": []})
        by_id = {r["id"]: r for r in rows}
        for v in views:
            row = by_id.get((v.get("project") or {}).get("id"))
            if row:
                row["cards"].append(v["key"])
                if v["state"] == "waiting":
                    row["waiting"].append(v["key"])
        keys = sorted(((_key(r["path"]), r["id"]) for r in rows), key=lambda t: len(t[0]), reverse=True)
        homes = {}
        for d in docs:
            home = next((pid for k, pid in keys if _inside(_key(d.get("path")), k)), None)
            homes[d.get("id")] = home
            if home:
                by_id[home]["documents"].append(d.get("id"))
        src._projects = (rows, homes)
    return src._projects


def _doc(d: dict, project) -> dict:
    return {k: d.get(k) for k in ("id", "agent", "agent_id", "slug", "title", "path", "updated", "master")} | {
        "docs": d.get("docs") or [], "diagrams": d.get("diagrams") or [], "project": project}


def projects_place(src: _Sources) -> dict:
    rows, homes = _project_rows(src)
    views = src.card_views()
    placed = {k for r in rows for k in r["cards"]}
    g = src.got["gates"]
    return {"off": bool(src.got["places"].get("off")), "gates_off": bool(g.get("off")),
            "read": g.get("read"), "read_note": g.get("read_note"), "projects": rows,
            "cards": {v["key"]: v for v in views if v["key"] in placed},
            "documents": [_doc(d, homes.get(d.get("id"))) for d in src.got["places"].get("documents") or []],
            "total": len(views), "assigned": len(placed), "unassigned": len(views) - len(placed),
            "worktrees": sum(len(r["gates"]["worktrees"]) for r in rows)}


def _rules_for(agent: dict, envs: list) -> dict:
    """Which rule environments are an agent's own, and why: an environment whose name begins with one of the agent's
    names (as "alder-seat" is Alder's), or whose seat line opens with one. Every other environment is shared."""
    names = [n for n in [agent.get("name"), *(agent.get("other_names") or [])] if n]
    folded = {n.casefold() for n in names}
    own, basis = [], {}
    for e in envs:
        first = str(e.get("name") or "").split("-", 1)[0].casefold()
        seat = str(e.get("seat") or "")
        opener = next((n for n in names if re.match(re.escape(n) + r"(?![A-Za-z])", seat, re.IGNORECASE)), None)
        if first in folded:
            own.append(e.get("name"))
            basis[e.get("name")] = f"its name begins with {agent.get('name')}'s name"
        elif opener:
            own.append(e.get("name"))
            basis[e.get("name")] = f"its seat line opens with {opener}"
    layer = sum(1 for e in envs for r in e.get("rules") or [] if (r.get("agent") or "").casefold() in folded)
    return {"environments": own, "basis": basis, "layer": layer}


def map_place(src: _Sources) -> dict:
    p = src.got["places"]
    rows, homes = _project_rows(src)
    views = src.card_views()
    waiting = [v for v in views if v["state"] == "waiting"]
    agents = {a.get("id"): a for a in p.get("agents") or []}
    names = {a.get("name"): a.get("id") for a in agents.values()}
    projects = {r["id"]: r for r in rows}
    broken_at = {r["id"]: {t["path"]: t["worst"] for t in r["gates"]["worktrees"] if t["broken"]} for r in rows}
    nodes: dict = {}

    def walk(node, parent):
        kind, nid = node.get("kind"), node.get("id")
        members = [m for m in node.get("members") or [] if m.get("agent_id") in agents]
        here = []
        if kind == "environment":
            home = node.get("project_id")
            mine = [pid for m in members for pid in (agents[m["agent_id"]].get("placed") or {}).get("projects") or []]
            here = list(dict.fromkeys(([home] if home in projects else []) + [x for x in mine if x in projects]))
        children = [walk(ch, nid) for ch in node.get("children") or []]
        seats = {agents[m["agent_id"]].get("name") for m in members}
        cards_below = {v["key"] for v in waiting if v["seat"] in seats}
        broke: dict = {}
        for pid in here:
            cards_below |= set(projects[pid]["waiting"])
            broke.update(broken_at[pid])
        for ch in children:
            cards_below |= ch["_cards"]
            broke.update(ch["_broke"])
        nodes[nid] = {"id": nid, "kind": kind, "name": node.get("name"), "path": node.get("path"), "parent": parent,
                      "children": [ch["id"] for ch in children], "projects": here,
                      "members": [{"agent_id": m["agent_id"], "name": m.get("name"), "basis": m.get("basis") or []}
                                  for m in members],
                      "project_id": node.get("project_id"), "documents": node.get("documents"),
                      "updated": node.get("updated"), "measured": node.get("measured"),
                      "waiting": len(cards_below), "broken": len(broke), "broken_words": dict(Counter(broke.values())),
                      "_cards": cards_below, "_broke": broke}
        return nodes[nid]

    levels = p.get("levels")
    root = walk(levels, None)["id"] if isinstance(levels, dict) else None
    for n in nodes.values():
        del n["_cards"], n["_broke"]
    envs = src.got["rules"].get("environments") or []
    agent_rows = {}
    for aid, a in agents.items():
        works = [{"project_id": r["id"], "name": r["name"],
                  "basis": next((m.get("basis") for m in r["agents"] if m.get("agent_id") == aid), []),
                  "emails": next((m.get("emails") for m in r["agents"] if m.get("agent_id") == aid), [])}
                 for r in rows if any(m.get("agent_id") == aid for m in r["agents"])]
        agent_rows[aid] = {k: a.get(k) for k in ("id", "name", "other_names", "groups", "emails", "home", "sigils")} | {
            "environment": (a.get("placed") or {}).get("environment"), "works": works,
            "waiting": [v["key"] for v in waiting if v["seat"] == a.get("name")],
            "cards": sum(v["seat"] == a.get("name") for v in views),
            "documents": [d.get("id") for d in p.get("documents") or [] if d.get("agent_id") == aid],
            "rules": _rules_for(a, envs)}
    project_tiles = {r["id"]: {"id": r["id"], "name": r["name"], "path": r["path"], "home_of": r["home_of"],
                               "waiting": len(r["waiting"]), "broken": r["gates"]["broken"],
                               "worst": r["gates"]["worst"], "worktrees": len(r["gates"]["worktrees"]),
                               "broken_words": dict(Counter(t["worst"] for t in r["gates"]["worktrees"]
                                                            if t["broken"]))} for r in rows}
    summary = p.get("map") or {"off": True}
    return {"off": bool(p.get("off")), "missing": p.get("missing") or [], "name": src.cfg.get("name"),
            "root": root, "nodes": nodes, "agents": agent_rows, "projects": project_tiles,
            "documents": [_doc(d, homes.get(d.get("id"))) for d in p.get("documents") or []],
            "cards": {v["key"]: {k: v[k] for k in ("key", "seat", "id", "kind", "title", "at", "state")}
                      for v in waiting},
            "names": names,
            "map": {k: summary.get(k) for k in ("off", "path", "measured", "file_updated", "places", "edges",
                                                "sectors")},
            "read_note": src.got["gates"].get("read_note")}


def record_place(src: _Sources) -> dict:
    r = src.got["record"]
    return {"off": bool(r.get("off")), "notes_off": bool(r.get("notes_off")), "files": r.get("files") or {},
            "entries": r.get("entries") or [], "threads": r.get("threads") or [], "counts": r.get("counts") or {}}


RULE_FIELDS = ("id", "kind", "words", "applies_when", "as_of", "basis", "quote", "ratified_by", "candidate", "live",
               "agent", "guards", "held", "relation")
ENV_FIELDS = ("name", "id", "title", "version", "status", "ratified_by", "owner", "scope", "seat", "path",
              "ratification", "counts", "parents")


def rules_place(src: _Sources) -> dict:
    r = src.got["rules"]
    envs = []
    for e in r.get("environments") or []:
        envs.append({k: e.get(k) for k in ENV_FIELDS} | {
            "cases": len(e.get("cases") or []),
            "rules": [{k: x.get(k) for k in RULE_FIELDS} | {"cases": [c.get("id") for c in x.get("cases") or []
                                                                      if isinstance(c, dict)]}
                      for x in e.get("rules") or []]})
    agents = {a.get("name"): {"id": a.get("id"), **_rules_for(a, envs)} for a in src.got["places"].get("agents") or []}
    return {"off": bool(r.get("off")), "cards": r.get("cards"), "environments": envs, "counts": r.get("counts") or {},
            "others": r.get("others") or [], "agents": agents}


def sources_place(src: _Sources) -> dict:
    keys = {k: src.cfg.get(k) for k in ("name", "seats", "group", "inbox", "register", "notes", "cards", "map")}
    readers = {name: {"off": bool(src.got[name].get("off")), "failed": src.got[name].get("failed"),
                      "missing": src.got[name].get("missing") or [],
                      "problems": len(src.got[name].get("problems") or [])} for name, _ in READERS}
    return {"config": {"path": str(src.path), "exists": src.path.is_file()}, "keys": keys, "readers": readers,
            "group": {"name": src.cfg.get("group"), "agents": sorted(src.allowed) if src.allowed is not None else None},
            "routes": list(ROUTES), "word": word_of(src.cfg.get("name"))}


PLACES = {"waiting": waiting_place, "projects": projects_place, "map": map_place, "record": record_place,
          "rules": rules_place, "sources": sources_place}


def answer(name: str, home=None, world=None) -> dict | None:
    """The page's data for one route: waiting, projects, map (also under the person's own word for the whole),
    record, rules or sources. None for a name that is no route. Every answer carries the frame."""
    cfg, _path, _trouble = _config(home)
    place = _route(str(name or ""), cfg)
    if place is None:
        return None
    src = _Sources(home, world)
    return {"place": place, "frame": src.frame(), **PLACES[place](src)}


# ---- the status line ------------------------------------------------------------------------------------------
def status_line(home=None, width: int = 80) -> str:
    """One line for a status bar: "2 waiting · newest: <agent> <id> <title>", cut to the width, or "nothing waiting
    · N decisions in force". Only the cards and the register are read. On any trouble, "Semantext: unavailable"."""
    try:
        width = max(40, int(width))
    except (TypeError, ValueError):
        width = 80
    try:
        cfg, _path, trouble = _config(home)
        if trouble:
            return UNAVAILABLE
        c = cards.load(cfg)
        if c.get("off") or not c.get("seats"):
            return UNAVAILABLE
        group = cfg.get("group")
        allowed = {s.get("seat") for s in c["seats"] if group in (s.get("groups") or [])} if group else None
        waiting = [x for x in c.get("cards") or [] if x.get("state") == "waiting"
                   and (allowed is None or x.get("seat") in allowed)]
        if waiting:
            top = newest_first(waiting)[0]
            title = " ".join(str(top.get("title") or "").split())
            line = f"{len(waiting)} waiting · newest: {top.get('seat')} {top.get('id')} {title}".rstrip()
            return line if len(line) <= width else line[:width - 1].rstrip() + "…"   # the title is cut to fit
        r = record.load(cfg)
        if r.get("off"):
            return "nothing waiting"
        n = ((r.get("counts") or {}).get("by_status") or {}).get("in force", 0)
        return f"nothing waiting · {_n(n, 'decision')} in force"
    except Exception:  # noqa: BLE001  a status bar line never fails
        return UNAVAILABLE
