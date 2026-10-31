"""The page's places: what the person sees, built from the five readers, with nothing written anywhere.

The page has four places, each one click from the others. Waiting is the home: every card an agent filed for the
person's word, card for card as their own inbox shows it, with what this page adds beside each card (the person's
earlier words that cite it, who asks and who acts, and the project it belongs to). Projects shows each repository with
its agents, its gates, its cards and its documents. The map shows the whole, under the person's own word for it, in
levels: its groups, their environments (each agent's home) and the projects each agent works in. The Record shows every
decision as threads. Documents lists every cv/<project> folder with a MASTER.md, as the inbox's Documents does, and
document() reads one listed file of one listed folder, and nothing else. Drawers show an agent, the rules, one
worktree's gates and one project's documents. The frame carries the inbox's gaming flag, read as its gaming.py reads it.

Every answer carries the frame: the person's word for the whole, how many cards wait, which sources are off and every
problem any reader reported, so the problems banner shows wherever the person is.

This module reads through the readers alone, which open files for reading only. It writes nothing, starts nothing and
keeps nothing between two answers: every number is measured when it is asked for.

The config may name a group. Then only the agents in that group are shown, as the person's own inbox reads only its
group's seats; the readers may already have left the others out, and leaving them out again changes nothing.
"""
from __future__ import annotations

import hashlib
import os
import copy
import json
import re
import stat
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .. import jsonread, outside, paths, registry
from . import builtin, cards, closed, compute, config_path, gaming, gates, load_config, places, problem, record, refused_keys, rules
from . import change as change_card
from . import evidence_gitindex as evidence_way   # which files a change may cite: one module per way (evidence.py)
from .workplace import work_place

# Which readers and places exist is the registry's (semantext/registry.py): the built-in ones are registered at the
# foot of this file, and ROUTES is read from it there. An answer adds the plug-ins the person turned on.
UNAVAILABLE = "Semantext: unavailable"
TEXT = ("title", "why", "question", "options", "command", "does", "undo")   # the words an agent writes to ask
# An id as a card or a decision carries it: one or two capitals, a date, a time or a number, and sometimes a number
# after that (X-20261010-195202-2 is another card than X-20261010-195202, so the number is part of the id).
ID = re.compile(r"(?<![A-Za-z0-9_])[A-Z]{1,2}-\d{8}-\d{1,6}(?:-\d{1,3})?(?![A-Za-z0-9_])")
# The gate words, worst first. A worktree whose words hold one of BROKEN can let a commit or a push through unchecked.
WORST = ("off", "checks nothing", "open", "stranded", "unknown", "folder gone", gates.ARMED_WORDS)
BROKEN = ("off", "checks nothing", "open", "stranded")
NO_PROJECT = "unassigned"
WHOLE_BYTES = 512   # words that fit are shown whole at every level of the Record; longer ones whole at their source
RECORD_CAP = 200    # change records per agent whose evidence one page build digests; later ones say they were not
READ_BUDGET = 256 * 1024 * 1024   # bytes of evidence one page build reads in all; past it, "over the read budget"


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
    try:   # "_file": where the run reader reads the person's closures from (runs._home); no reader shows it.
        # "_home": the Semantext home the server was started with, where the work store lies (sources/work.py).
        cfg = {**load_config(path), "_file": str(path), "_home": str(home or paths.home())}
        # Your own rules need no setting: with no "cards" key, the Rules page reads the environments in your home.
        own = Path(cfg["_home"]) / "profiles"
        if "cards" not in cfg and own.is_dir():
            cfg["cards"] = str(own)
        if os.environ.get("SEMANTEXT_SOURCES") and not path.is_file():   # named and missing: a broken setup, not no setup
            cfg["_sources_missing"] = True
        return cfg, path, None
    except Exception as e:  # noqa: BLE001  whatever is wrong with the file, every place still answers
        return {}, path, {"reader": "sources", "source": str(path), "line": None, "kind": "unreadable",
                          "text": f"your sources file cannot be read ({type(e).__name__}: {e})"[:300]}


def _route(name: str, cfg: dict, reg=None) -> str | None:
    """The place a name asks for: a built-in place, the person's word for the whole (the map), then a place the person
    turned on, so no plug-in can take a built-in's name or the person's word."""
    if name in ROUTES:
        return name
    word = word_of(cfg.get("name"))
    if word and name == word:
        return "map"
    return name if reg is not None and reg.get("place", name) else None


# ---- reading ------------------------------------------------------------------------------------------------------
def _capped(part: dict, what: str) -> dict:
    """An outside answer held to the caps (outside.py): its problems kept short and few, its whole size bounded."""
    kept, left_out = outside.problems(part.get("problems"))
    if left_out:
        kept.append({"source": what, "line": None, "kind": "too many problems",
                     "text": f"{left_out} more problems were left out (at most {outside.MAX_PROBLEMS} are kept)"})
    body = {**part, "problems": kept}
    n = outside.size(body)
    if n is None:
        raise TypeError("its answer cannot be written as JSON")
    if n > outside.MAX_BYTES:
        raise ValueError(f"its answer is {n // 1024} KB, over the {outside.MAX_BYTES // (1024 * 1024)} MB cap, so it "
                         f"is not used")
    return body


def _outside(entry, path, ctx=None) -> dict:
    """An outside source's answer, read on its own keys of the sources file, held to the shape the page reads: a
    record, its problems a list of records, within the caps. A read that takes a context (api 0.2) is given the
    build's ReadContext. The read runs with a time budget (outside.run)."""
    if entry.reads_ctx is None:   # not known for this answer: never read without its ctx (the recheck of 17021c2, NH4)
        raise RuntimeError(registry.not_without_ctx("read", entry.ctx_trouble))
    cfg = load_config(path, keys=tuple(entry.obj.keys)) if path else {}
    # the answer comes back as plain data: made into bounded, depth-checked JSON text in the worker (outside.run_json)
    owner = registry.key(entry.kind, entry.name)   # counted against the name the registry gave it, never the callable
    given = (cfg, ctx) if entry.reads_ctx else (cfg,)
    part = outside.run_json(entry.obj.read, *given, owner=owner, call="read")
    if not isinstance(part, dict):
        raise TypeError(f"its answer is a {type(part).__name__}, not a record")
    body = _capped(part, f"plug-in source.{entry.name}")
    body["problems"] = (refused_keys(path, tuple(entry.obj.keys)) if path else []) + body["problems"]
    return body


def _over_total(spent: int, n: int) -> None:
    if spent + n > outside.MAX_TOTAL:
        cap = outside.MAX_TOTAL
        said = f"{cap // (1024 * 1024)} MB" if cap >= 1024 * 1024 else f"{cap // 1024} KB"
        raise ValueError(f"its answer ({n // 1024} KB) would take the outside answers of this page over the {said} "
                         f"they may come to together, so it is not used")


def _read(cfg: dict, world=None, reg=None, path=None, home=None, outside_reads=True) -> tuple[dict, list, int]:
    """Every reader's answer on this config, a problem for each reader that stopped, and the bytes the outside
    answers came to: one that fails costs the page that reader's part, never the rest. A reader the person turned on
    is read the same way, on its own keys; one whose answer would take the outside answers together over
    outside.MAX_TOTAL is refused (the audit of 784faf6, note 11). With outside_reads False no outside reader is read
    at all (the Plug-ins place: no plug-in is called to draw it)."""
    got, failed, spent = {}, [], 0
    ctx = None
    for entry in (reg or BUILT_IN).entries("source"):
        name = entry.name
        if not entry.builtin and not outside_reads:
            continue
        if entry.reads_ctx and not entry.builtin and ctx is None:
            ctx = closed.context(home)   # once per build, so every reader judges against the same closures
        try:
            if entry.builtin:
                got[name] = entry.obj.read(cfg, world)
            else:
                # each plug-in its own sealed copy: one plug-in's change to its context never reaches another's
                body = _outside(entry, path, closed.own_copy(ctx) if ctx is not None else None)
                n = outside.size(body) or 0   # plain data by now (outside.run_json): no plug-in code runs here
                _over_total(spent, n)
                got[name], spent = body, spent + n
        except (Exception, SystemExit) as e:  # noqa: BLE001  KeyboardInterrupt, the person's Ctrl-C, goes through
            got[name] = {"off": True, "failed": f"{type(e).__name__}: {e}", "problems": []}
            title = getattr(entry.obj, "title", None) or name
            failed.append({"reader": name, "source": "", "line": None, "kind": "reader stopped",
                           "text": f"the {title} reader stopped ({type(e).__name__}: {e})"[:300]})
    return got, failed, spent


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
    if allowed is None or got["waiting"].get("own_inbox"):   # your own inbox has no seats to be in a group
        return got
    c = dict(got["waiting"])
    c["seats"] = [s for s in c.get("seats") or [] if s.get("seat") in allowed]
    c["cards"] = [x for x in c.get("cards") or [] if x.get("seat") in allowed]
    c["changes"] = [x for x in c.get("changes") or [] if x.get("seat") in allowed]
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


def _off(got: dict, reg=None) -> dict:
    """Each source that is off, with the keys the sources file would need to turn it on (as each source declares)."""
    reg = reg or BUILT_IN
    out = {}
    for name, part in got.items():
        if part.get("off"):
            obj = reg.get("source", name).obj
            needs = list(getattr(obj, "needs", None) or obj.keys)
            out[name] = {"missing": part.get("missing") or needs, "failed": part.get("failed")}
        elif part.get("missing"):
            out[name] = {"missing": part["missing"], "failed": None, "partly": True}
    return out


def _held() -> list[dict]:
    """A problem line for each plug-in holding calls that did not answer in time, and one more when they fill the cap of
    every plug-in together (outside.holding_said): the page names who is holding them (the recheck of 17021c2, NH3)."""
    return [{"reader": "plug-ins", "source": "plug-in calls", "line": None, "kind": "calls still running",
             "text": text[:300]} for text in outside.holding_said()]


def _said_by(name: str, p: dict, outside_source: bool) -> dict:
    """A reader's problem as the page lists it: the reader is always the one that said it, set last so no field of the
    problem's own stands in for it. An outside source's problem names it in its source too, so it never reads as a
    built-in reader's, about the person's own file (the Fable review of 70f2d3c, F5: {"reader": name, **p} let a plug-in
    set both)."""
    row = {**p, "reader": name}
    if outside_source:
        said = p.get("source")
        row["source"] = (f"plug-in source.{name}" + (f": {said}" if said not in (None, "") else ""))[:300]
    return row


class _Sources:
    """One answer's reading: the config, every reader's answer for the group, and the problems, gathered once.

    `sources[name]` is that source's answer for the group: the one part of this object a place outside the package may
    rely on (api.py, Place). A plug-in that could not be loaded is one more problem, under "plug-ins"."""

    def __init__(self, home=None, world=None, reg=None, outside_reads=True):
        self.home = home   # the home the page was started with: an outside place's build(sources, ctx) is given it
        self.reg = reg if reg is not None else registry.load_enabled(BUILT_IN, home)
        self.cfg, self.path, trouble = _config(home)
        self.config_trouble = trouble
        self.bad_settings = [
            problem(self.path, None, "bad-setting", "'inbox_app' is not kept: it is true or false")
            for _ in refused_keys(self.path, ("inbox_app",))] if not trouble else []
        if self.cfg.get("_sources_missing"):
            self.bad_settings.append(problem(self.path, None, "unreadable", "SEMANTEXT_SOURCES names this file, and it "
                                             "is not there, so nothing it would name is read"))
        got, failed, self.spent = _read(self.cfg, world, self.reg, self.path, home,   # spent: outside bytes so far
                                        outside_reads)
        self.allowed = _allowed(self.cfg, got)
        self.got = _in_group(got, self.allowed)
        mine = {e.name for e in self.reg.entries("source") if not e.builtin}
        # closures named but unusable close every path: said here, never only by what stops being read (a sources
        # file that cannot be read is already the problem above)
        declared = tuple(k for e in self.reg.entries("source") if not e.builtin for k in (e.obj.keys or ()))
        self.problems = ([trouble] if trouble else closed.problems(home, declared)) + failed + [
            _said_by(name, p, name in mine) for name in self.reg.names("source")
            for p in self.got.get(name, {}).get("problems") or []
        ] + [{"reader": "plug-ins", **p} for p in self.reg.problems]
        self._cards = None
        self._projects = None

    def __getitem__(self, name: str) -> dict:
        return self.got[name]

    def get(self, name: str, default=None):
        return self.got.get(name, default)

    # -- the frame every place carries
    def frame(self) -> dict:
        c = self.got["waiting"]
        return {"name": self.cfg.get("name"), "word": word_of(self.cfg.get("name")), "group": self.cfg.get("group"),
                "checked": _now(), "config": str(self.path),
                "waiting": sum(x.get("state") == "waiting" for x in c.get("cards") or []),
                "seats": [s.get("seat") for s in c.get("seats") or []], "off": _off(self.got, self.reg),
                "problems": self.problems + self.bad_settings + _held(), "gaming": self.gaming(), "compute": self.compute(),
                "inbox_app": self.cfg.get("inbox_app") is True,   # links into an inbox app only where the person says they have one
                "outside": self.outside()}

    def outside(self) -> list[dict]:
        """The places the person turned on, after the built-ins in the bar: each with its title, the package it came
        from, and whether it ships a page module the server will serve (pagemodule.py)."""
        from .. import pagemodule   # here: the page module rules are the server's, read only for the bar
        return [{"name": e.name, "title": str(getattr(e.obj, "title", "") or e.name)[:80], "origin": e.origin,
                 "version": e.version, "module": pagemodule.offers(e)}
                for e in self.reg.entries("place") if not e.builtin]

    def gaming(self) -> dict:
        """The inbox's gaming flag, as its own gaming.py reads it; "unknown" when the reader itself stops."""
        try:
            return gaming.load(self.cfg)
        except Exception as e:  # noqa: BLE001  the indicator says unknown; the page goes on
            return {"off": False, "state": "unknown", "file": None, "why": f"{type(e).__name__}: {e}"[:300]}

    def compute(self) -> dict:
        """The compute monitor's verdict; "unknown" when the monitor itself stops, never "free"."""
        try:
            got = compute.verdict(self.cfg)
            if self.config_trouble and got["verdict"] == compute.FREE:   # the button's flag is named in that file
                why = "your sources file could not be read, so the button's flag was not read"
                return {**got, "verdict": compute.UNKNOWN, "reasons": [why], "could_not_tell": [why]}
            return got
        except Exception as e:  # noqa: BLE001  the indicator says unknown; the page goes on
            why = f"{type(e).__name__}: {e}"[:300]
            return {"verdict": "unknown", "reasons": [why], "could_not_tell": [why], "not_read": [], "games": [],
                    "cpu_busy": None, "memory_free": None}

    # -- cards, as every place shows them
    def projects_list(self) -> list:
        return self.got["places"].get("projects") or []

    def card_views(self) -> list[dict]:
        if self._cards is None:
            joiner = _Cards(self)
            self._cards = [joiner.view(c) for c in self.got["waiting"].get("cards") or []]
            self._changes = [joiner.change(r, self._cards) for r in self.got["waiting"].get("changes") or []]
        return self._cards

    def change_views(self) -> list[dict]:
        self.card_views()
        return self._changes


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
        self.changes_files = {s.get("seat"): (s.get("changes") or {}).get("file") for s in c.get("seats") or []}
        self.homes = {s.get("seat"): s.get("home") for s in c.get("seats") or []}
        self.digested: Counter = Counter()   # change records whose evidence this build has digested, per agent
        self.budget = {"left": READ_BUDGET}  # bytes of evidence this build may still read, across every agent
        self.got = src.got
        self.policies: dict = {}             # the evidence policy of each agent, built once per page build
        self.notes: dict = {}
        for p in c.get("problems") or []:
            if p.get("shown"):
                self.notes.setdefault((_key(p.get("source")), p.get("line")), []).append(p.get("text"))

    def roots(self, seat) -> list[str]:
        """The filing agent's own home and the projects the places reader binds to it (as a member or as its home): the
        most a change's evidence may be read from, so a digest confirms nothing that agent could not read. The evidence
        way (evidence_way.for_seat) narrows it to the files that are evidence."""
        out = [self.homes.get(seat)]
        for p in self.projects:
            if seat in (p.get("home_of") or []) or any(m.get("name") == seat for m in p.get("members") or []):
                out.append(p.get("path"))
        return [str(x) for x in out if x]

    def policy(self, seat):
        """Which files that agent's change records may cite as evidence, as the page's evidence way decides."""
        if seat not in self.policies:
            self.policies[seat] = evidence_way.for_seat(seat, self.got, self.roots(seat))
        return self.policies[seat]

    def view(self, c: dict) -> dict:
        closing, run = c.get("closing"), c.get("run")
        file = self.files.get(c.get("seat"))
        return {
            "key": f"{c.get('seat')}/{c.get('id')}",
            **{k: c.get(k) for k in ("seat", "id", "kind", "title", "why", "question", "command", "does", "undo", "cwd",
                                     "at", "state", "parked_at", "asks", "asks_basis", "acts", "acts_basis", "line")},
            "options": [o for o in c.get("options") or [] if isinstance(o, str)],
            "number": c.get("number"), "choices": c.get("choices") or [], "own_inbox": bool(c.get("own_inbox")),
            "closing": {"at": closing.get("at"), "how": closing.get("how"),
                        "earlier": len(closing.get("earlier") or [])} if isinstance(closing, dict) else None,
            "run": {k: run.get(k) for k in ("started", "finished", "exit", "timed_out")} if isinstance(run, dict)
            else None,
            "output": _output(c.get("output")) if isinstance(run, dict) else None,
            "change_id": c.get("change_id"), "change_unknown": c.get("change_unknown"),
            "file": file,
            "notes": self.notes.get((_key(file), c.get("line")), []),
            "project": self.place(c),
            "earlier": self.earlier(c),
        }

    def change(self, r: dict, views: list[dict]) -> dict:
        """A change record as the page shows it: its fields, whether its evidence is still today's (measured now), its
        outcomes, and the decision cards that ask about it, with whether one of them has been answered."""
        own = r.get("change") if isinstance(r.get("change"), dict) else {}
        seat = r.get("seat")
        if own.get("evidence") and self.digested[seat] >= RECORD_CAP:
            fresh = {"state": "unknown", "why": f"not checked: over the cap of {RECORD_CAP} change records whose "
                                                f"evidence one page build digests for one agent"}
        else:
            self.digested[seat] += bool(own.get("evidence"))
            try:
                fresh = change_card.freshness(own.get("evidence"), self.policy(seat), self.budget)
            except Exception as e:  # noqa: BLE001  a record whose evidence cannot be checked says so
                fresh = {"state": "unknown", "why": f"{type(e).__name__}: {e}"[:300]}
        asked = [f"{r.get('seat')}/{i}" for i in r.get("asked_in") or []]
        by_key = {v["key"]: v for v in views}
        return {"key": f"{r.get('seat')}/{r.get('id')}", "seat": r.get("seat"), "id": r.get("id"), "kind": "change",
                "title": r.get("title"), "why": r.get("why"), "at": r.get("at"), "line": r.get("line"),
                "file": self.changes_files.get(r.get("seat")),
                "notes": self.notes.get((_key(self.changes_files.get(r.get("seat"))), r.get("line")), []),
                "change": {**own, "freshness": fresh},
                "outcomes": r.get("outcomes") or [], "judged": r.get("judged"), "asked_in": asked,
                "decided": bool(r.get("outcomes")) or any((by_key.get(k) or {}).get("state") in ("closed", "run")
                                                          for k in asked)}

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


OUTPUT_CAP = 64 * 1024   # characters of one stream a card carries; the rest is counted, not sent


def _output(out) -> dict | None:
    """A run's stdout and stderr as the inbox shows them under Output, each cut at OUTPUT_CAP characters (with how many
    were cut), so one long run does not make every answer long. None when the run left no text."""
    if not isinstance(out, dict):
        return None
    got = {}
    for k in ("stdout", "stderr"):
        text = out.get(k) if isinstance(out.get(k), str) else ""
        got[k] = text[:OUTPUT_CAP]
        got[k + "_cut"] = max(0, len(text) - OUTPUT_CAP)
    return got if got["stdout"].strip() or got["stderr"].strip() else None


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
            "files": w.get("files") or [], "read_at": w.get("read_at"), "tested": False,
            "executable": w.get("executable"), "not_executable": w.get("not_executable") or [],
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
                 "open": ("is open", "are open"),
                 "stranded": ("is stranded (a hook git cannot reach)", "are stranded (hooks git cannot reach)")}
        found = {k: worst(gate_words(w)) for k, w in trees.items()}
        for word, (one, many) in verbs.items():
            hit = [k for k, w in found.items() if w == word]
            if hit:
                repos = len({repo_of[k] for k in hit})
                said.append(f"{_n(len(hit), 'worktree')} in {_n(repos, 'repo')} {one if len(hit) == 1 else many}")
        # The all-clear only when every worktree's worst word IS the all-clear: any word not said above, stranded
        # once among them, is counted as unread rather than passed over (review of 1.2.2, V1)
        unread = sum(w not in verbs and w != WORST[-1] for w in found.values())
        if not said and not unread:   # what was read, never more: no hook was run, so none is known to refuse
            said.append(f"every worktree has a hook for each act and an .identity that names someone ({gates.NOT_TESTED})")
        if unread:
            said.append(f"{_n(unread, 'worktree')} could not be read")
        at = src.got["gates"].get("read_at")
        parts.append(f"Gates (read{' at ' + at if at else ''}): " + "; ".join(said))
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
            "holds": holds(src), "change_records": src.change_views(), "changes": change_card.score(src.change_views())}


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
            "read": g.get("read"), "read_note": g.get("read_note"), "read_at": g.get("read_at"),
            "not_tested": gates.NOT_TESTED, "armed_words": gates.ARMED_WORDS, "projects": rows,
            "cards": {v["key"]: v for v in views if v["key"] in placed},
            "documents": [_doc(d, homes.get(d.get("id"))) for d in src.got["places"].get("documents") or []],
            "total": len(views), "assigned": len(placed), "unassigned": len(views) - len(placed),
            "worktrees": sum(len(r["gates"]["worktrees"]) for r in rows)}


def documents_place(src: _Sources) -> dict:
    """Every project folder an agent keeps in its cv/ with a MASTER.md, as the inbox's Documents lists them: newest
    first, each with its detailed documents and diagrams, and the project it lies in when it lies in one."""
    rows, homes = _project_rows(src)
    names = {r["id"]: r["name"] for r in rows}
    docs = []
    for d in src.got["places"].get("documents") or []:
        home = homes.get(d.get("id"))
        docs.append(_doc(d, home) | {"project_name": names.get(home)})
    return {"off": bool(src.got["places"].get("off")), "documents": docs}


# ---- one document, read ------------------------------------------------------------------------------------------
class DocumentRefused(Exception):
    """A document read the page may not make, with the HTTP status to answer and the reason in plain words."""

    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status, self.why = status, why


def _same_file(a, b) -> bool:
    return (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_dev, b.st_ino, b.st_size, b.st_mtime_ns)


def _read_checked(target: str, st) -> bytes:
    """The file's bytes, read through ONE read-only handle whose identity is checked against the earlier lstat. A
    folder swapped for a link to a decoy at any moment gives a different file, which is refused; a swap during the
    read cannot change what this handle reads (audit of 7bf7aa5, protection item 1)."""
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        if not _same_file(os.fstat(fd), st):
            raise DocumentRefused(409, "the file changed before it was read; try again")
        chunks, left = [], places.DOC_CAP + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def document(doc_id, file, home=None) -> dict:
    """One file of one document folder, read: {"kind": "markdown", "doc", "file", "title", "master", "text"} for a .md
    file, {"kind": "diagram", "doc", "file", "bytes"} for an .svg. Only a folder the documents reader lists (a cv/<project>
    folder in a seat's home, holding a MASTER.md, in the config's group) and only a file it lists there: its MASTER.md,
    a detailed .md document, or a diagram. The file must be one plain name; it is checked again when read, and refused
    when it is a link, is not a plain file, or resolves anywhere but directly inside its folder. Nothing is written."""
    if not isinstance(doc_id, str) or not doc_id or not isinstance(file, str) or not file:
        raise DocumentRefused(400, "name the document and the file")
    why = places._plain(file)
    if why or os.path.isabs(file) or places.DRIVE.match(file) or file != file.strip():
        raise DocumentRefused(400, f"the file must be one plain name in its folder ({why or 'a full path'})")
    low = file.lower()
    if not low.endswith((".md", ".svg")):
        raise DocumentRefused(400, "only .md documents and .svg diagrams are read")
    cfg, _path, trouble = _config(home)
    if trouble:
        raise DocumentRefused(404, "your sources file cannot be read")
    found = places.load(cfg)
    d = next((x for x in found.get("documents") or [] if x.get("id") == doc_id), None)
    if d is None:
        raise DocumentRefused(404, "no document of yours has this id now")
    listed = {d.get("master")} | {x.get("file") for x in d.get("docs") or []} | set(d.get("diagrams") or [])
    if file not in listed:
        raise DocumentRefused(404, "this file is not one the documents reader lists in that folder")
    folder = d.get("path")
    if not isinstance(folder, str) or os.path.basename(os.path.dirname(folder)).lower() != places.CV:
        raise DocumentRefused(403, "the folder is not a cv/<project> folder")
    target = os.path.join(folder, file)
    try:
        if places._linked(os.lstat(folder)):
            raise DocumentRefused(403, "the folder is a link, so it is not followed")
        st = os.lstat(target)
        if places._linked(st):
            raise DocumentRefused(403, "the file is a link, so it is not followed")
        if not stat.S_ISREG(st.st_mode):
            raise DocumentRefused(403, "it is not a plain file")
        if st.st_nlink > 1:   # a hard link is a plain file with a second name somewhere else on the volume
            raise DocumentRefused(403, "the file has another name elsewhere (a hard link), so it is not read")
        real_folder = os.path.normcase(os.path.realpath(folder))
        real = os.path.normcase(os.path.realpath(target))
        if os.path.dirname(real) != real_folder:
            raise DocumentRefused(403, "the file resolves outside its folder")
        if st.st_size > places.DOC_CAP:
            raise DocumentRefused(413, f"it is over {places.DOC_CAP // (1024 * 1024)} MB, so it is not read")
        raw = _read_checked(target, st)
        # The folder is checked again BEFORE the file: a folder still swapped for a link is refused here, and one swapped
        # back by now makes the file below a different file from the one read. Serving a decoy then takes two swaps
        # timed between adjacent calls (audit of 84270dc, protection item 1; the window is documented, not closed).
        if places._linked(os.lstat(folder)) or os.path.normcase(os.path.realpath(folder)) != real_folder:
            raise DocumentRefused(409, "the folder changed while the file was being read; try again")
        again = os.lstat(target)   # the same plain file after the read as before it: a swap for a link is refused
        if places._linked(again) or not _same_file(again, st):
            raise DocumentRefused(409, "the file changed while it was being read; try again")
    except FileNotFoundError:
        raise DocumentRefused(404, "the file is gone") from None
    except OSError as e:
        raise DocumentRefused(500, f"the file cannot be read: {e.strerror or e}") from None
    if len(raw) > places.DOC_CAP:
        raise DocumentRefused(413, f"it is over {places.DOC_CAP // (1024 * 1024)} MB, so it is not read")
    if low.endswith(".svg"):
        return {"kind": "diagram", "doc": doc_id, "file": file, "bytes": raw}
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise DocumentRefused(415, "it is not saved as UTF-8 text") from None
    return {"kind": "markdown", "doc": doc_id, "file": file, "master": file == d.get("master"),
            "title": d.get("title") if file == d.get("master") else
            next((x.get("title") for x in d.get("docs") or [] if x.get("file") == file), file),
            "text": text}


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


def thread_key(thread: dict) -> str:
    """A thread's address in the page: from its subject exactly as written (the register's tool never merges subjects),
    or, for a decision with no subject, from its own id and line. The register stays the authority; this is an index."""
    subject = thread.get("subject")
    basis = subject if isinstance(subject, str) and subject.strip() else "\x1f".join(
        str(x) for x in (thread.get("entries") or [])) + "\x1falone"
    return hashlib.sha256(basis.encode("utf-8", "surrogatepass")).hexdigest()[:12]


def record_place(src: _Sources) -> dict:
    r = src.got["record"]
    threads = [{**t, "key": thread_key(t)} for t in r.get("threads") or []]
    return {"off": bool(r.get("off")), "notes_off": bool(r.get("notes_off")), "files": r.get("files") or {},
            "entries": r.get("entries") or [], "threads": threads, "counts": r.get("counts") or {},
            "whole_bytes": WHOLE_BYTES}


RULE_FIELDS = ("id", "kind", "words", "applies_when", "as_of", "basis", "quote", "ratified_by", "candidate", "live",
               "agent", "no_provenance", "guards", "checkers", "runs", "held", "relation")
ENV_FIELDS = ("name", "id", "title", "version", "status", "ratified_by", "owner", "scope", "seat", "path",
              "ratification", "counts", "parents")


def rules_place(src: _Sources) -> dict:
    r = src.got["rules"]
    envs = []
    for e in r.get("environments") or []:
        envs.append({k: e.get(k) for k in ENV_FIELDS} | {
            "cases": len(e.get("cases") or []),
            "rules": [{k: x.get(k) for k in RULE_FIELDS} | {"cases": [{"id": c.get("id"),
                                                                       "kept_in": list(c.get("kept_in") or [])}
                                                                      for c in x.get("cases") or []
                                                                      if isinstance(c, dict)]}
                      for x in e.get("rules") or []]})
    agents = {a.get("name"): {"id": a.get("id"), **_rules_for(a, envs)} for a in src.got["places"].get("agents") or []}
    return {"off": bool(r.get("off")), "cards": r.get("cards"), "environments": envs, "counts": r.get("counts") or {},
            "others": r.get("others") or [], "agents": agents, "guards": r.get("guards"),
            "run_records": r.get("run_records"), "run_record_days": r.get("run_record_days")}


def sources_place(src: _Sources) -> dict:
    keys = {k: src.cfg.get(k) for k in ("name", "seats", "group", "inbox", "register", "notes", "cards", "map",
                                        "gaming", "guards", "run_records", "run_record_days")}
    readers = {name: {"off": bool(src.got[name].get("off")), "failed": src.got[name].get("failed"),
                      "missing": src.got[name].get("missing") or [],
                      "problems": len(src.got[name].get("problems") or [])} for name in src.reg.names("source")}
    return {"config": {"path": str(src.path), "exists": src.path.is_file()}, "keys": keys, "readers": readers,
            "group": {"name": src.cfg.get("group"), "agents": sorted(src.allowed) if src.allowed is not None else None},
            "routes": list(src.reg.names("place")), "word": word_of(src.cfg.get("name"))}


def plugins_place(src: _Sources) -> dict:
    from .. import pluginpage   # here: only this place needs it
    return pluginpage.place(src)


class Place:
    """A built-in place, registered as an outside one is: its route, its title, the sources it reads, and build.
    With reads_outside False, drawing it reads no outside source (the Plug-ins place calls no plug-in)."""

    kind = "place"

    def __init__(self, name: str, title: str, build, needs: tuple, reads_outside: bool = True):
        self.name, self.title, self.build, self.needs = name, title, build, needs
        self.reads_outside = reads_outside


_ALL = tuple(s.name for s in builtin.SOURCES)
BUILT_IN = builtin.registry()
for _place in (Place("waiting", "Waiting", waiting_place, ("waiting", "record", "places", "gates")),
               Place("projects", "Projects", projects_place, ("places", "gates", "waiting", "record")),
               Place("documents", "Documents", documents_place, ("places", "gates", "waiting", "record")),
               Place("map", "Map", map_place, ("places", "gates", "waiting", "record", "rules")),
               Place("record", "Record", record_place, ("record",)),
               Place("rules", "Rules", rules_place, ("rules", "places")),
               Place("sources", "Sources", sources_place, _ALL),
               Place("work", "Work", work_place, ("work", "waiting", "record")),
               Place("plugins", "Plug-ins", plugins_place, (), reads_outside=False)):
    BUILT_IN.add("place", _place.name, _place)
ROUTES = BUILT_IN.names("place")


class _Copy:
    """What an outside place is given as `sources`: a copy of every source's answer, so it can read them all and
    change nothing the page or another place reads (the audit of the registry, c696d0b, protection item c). The
    built-in places keep the live object. An outside source's answer is already plain data of bounded depth
    (outside.run_json), and is copied as JSON text, never by copy.deepcopy, which would run a __deepcopy__ of the
    plug-in's or recurse past the stack on a deep answer (the audit of 784faf6, findings 5 and 6)."""

    def __init__(self, got: dict, outside_names=()):
        self._got = {name: (jsonread.loads(json.dumps(part)) if name in outside_names else copy.deepcopy(part))
                     for name, part in got.items()}

    def __getitem__(self, name: str) -> dict:
        return self._got[name]

    def get(self, name: str, default=None):
        return self._got.get(name, default)


def _built(entry, src: _Sources) -> dict:
    """A place's data. A place the person turned on that stops, is late, answers with something other than a record,
    or answers over the caps, gives an answer that says so and one more problem; it never costs the frame. A build
    that takes two arguments is given the ReadContext of the page's home, as a source's read is (before, a place could
    only ask is_closed_place with no ctx, which reads the default home: the audit of 784faf6, note 10)."""
    if entry.builtin:
        return entry.obj.build(src)
    try:
        if entry.reads_ctx is None:   # not known for this answer: never built without its ctx (the recheck of 17021c2, NH4)
            raise RuntimeError(registry.not_without_ctx("build", entry.ctx_trouble))
        mine = {e.name for e in src.reg.entries("source") if not e.builtin}
        given = (_Copy(src.got, mine),) + ((closed.context(src.home),) if entry.reads_ctx else ())
        body = outside.run_json(entry.obj.build, *given,   # plain data back, its size and depth bounded
                                owner=registry.key(entry.kind, entry.name), call="build")
        if not isinstance(body, dict):
            raise TypeError(f"its answer is a {type(body).__name__}, not a record")
        body = {k: v for k, v in body.items() if k not in ("place", "frame")}
        n = outside.size(body)
        if n is None:
            raise TypeError("its answer cannot be written as JSON")
        if n > outside.MAX_BYTES:
            raise ValueError(f"its answer is {n // 1024} KB, over the {outside.MAX_BYTES // (1024 * 1024)} MB cap")
        _over_total(getattr(src, "spent", 0), n)   # the place's body counts with the sources' answers it was built on
        return body
    except (Exception, SystemExit) as e:  # noqa: BLE001  KeyboardInterrupt, the person's Ctrl-C, goes through
        why = f"{type(e).__name__}: {e}"[:300]
        src.problems.append({"reader": "plug-ins", "source": f"plug-in place.{entry.name}", "line": None,
                             "kind": "place stopped", "text": f"the {entry.name} place stopped ({why})"[:300]})
        return {"off": True, "failed": why}


NO_HOME = "no home folder: this system gives none, and no Semantext home is set, so nothing is read"


def _no_home(home) -> bool:
    """Whether the home cannot be found: no home given, and the system gives none (paths.home raises)."""
    if home is not None:
        return False
    try:
        paths.home()
        config_file(None)
    except (RuntimeError, KeyError, OSError):
        return True
    return False


def _answer_without_home(name: str) -> dict | None:
    """A built-in route's answer when there is no home: its frame says so as a problem, and nothing is read."""
    if str(name or "") not in ROUTES:
        return None
    said = {"reader": "sources", "source": "home", "line": None, "kind": "no home", "text": NO_HOME}
    frame = {"name": None, "word": None, "group": None, "checked": _now(), "config": None, "waiting": 0, "seats": [],
             "off": True, "problems": [said], "gaming": {"off": True, "state": "unknown", "file": None, "why": NO_HOME},
             "outside": []}
    return {"place": str(name), "frame": frame, "off": True, "failed": NO_HOME}


def answer(name: str, home=None, world=None) -> dict | None:
    """The page's data for one route: waiting, projects, documents, map (also under the person's own word for the
    whole), record, rules, sources, or a place the person turned on. None for a name that is no route. Every answer
    carries the frame. With no home at all (the system gives none, and none is set), every built-in route answers with
    that said as a problem, never an exception."""
    if _no_home(home):
        return _answer_without_home(name)
    try:
        return _answer(name, home, world)
    except RuntimeError:
        if _no_home(home):   # the home went away while it was read: said, never raised
            return _answer_without_home(name)
        raise


def _answer(name: str, home=None, world=None) -> dict | None:
    cfg, _path, _trouble = _config(home)
    reg = registry.load_enabled(BUILT_IN, home)
    place = _route(str(name or ""), cfg, reg)
    if place is None:
        return None
    entry = reg.get("place", place)
    src = _Sources(home, world, reg, outside_reads=getattr(entry.obj, "reads_outside", True) is not False)
    if entry.builtin:
        return {"place": place, "frame": src.frame(), **_built(entry, src)}
    body = _built(entry, src)
    return {"place": place, "frame": src.frame(), **body}


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
        if c.get("off") or not (c.get("seats") or c.get("own_inbox")):
            return UNAVAILABLE
        group = None if c.get("own_inbox") else cfg.get("group")
        allowed = {s.get("seat") for s in c["seats"] if group in (s.get("groups") or [])} if group else None
        waiting = [x for x in c.get("cards") or [] if x.get("state") == "waiting"
                   and (allowed is None or x.get("seat") in allowed)]
        if waiting:
            top = newest_first(waiting)[0]
            title = " ".join(str(top.get("title") or "").split())
            line = f"{len(waiting)} waiting · newest: {top.get('seat')} {top.get('id')} {title}".rstrip()
            line = "".join(ch for ch in line if ch.isprintable())   # no escape code from a request reaches a terminal
            return line if len(line) <= width else line[:width - 1].rstrip() + "…"   # the title is cut to fit
        r = record.load(cfg)
        if r.get("off"):
            return "nothing waiting"
        n = ((r.get("counts") or {}).get("by_status") or {}).get("in force", 0)
        return f"nothing waiting · {_n(n, 'decision')} in force"
    except Exception:  # noqa: BLE001  a status bar line never fails
        return UNAVAILABLE
