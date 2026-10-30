"""The registry: every plug-in by kind, the built-in ones and the ones a person installed and turned on.

A plug-in is a source (a reader of the person's files), a place (a part of the page), or a checker (something that
runs outside the package and leaves run records). The other kinds the ecosystem names are reserved: listed, empty, and
refused if a package offers one (docs/plugin-api.md, "Kinds": the registry plus Source, Place and Checker first).

The built-in parts register here exactly as an outside one does, so the way in is proven by use. An outside plug-in is
an installed Python package declaring an entry point in the group `semantext.plugins`, named "<kind>.<name>" so that
listing it needs no code of it to run. Nothing is fetched, and no folder of loose scripts is ever loaded.

**Installed is not enabled** (the ecosystem review, section 4). Which plug-ins are on is the person's list in
<home>/plugins.json, and an entry point is loaded only when that list names it, at the version it was turned on for.
The list is written only by `semantext plugins enable`, at a console, by the person typing the plug-in's name back.

**Which processes load plug-ins** (the ecosystem review, section 1): the page's server and the command line. The card
hook loads none, and never imports this module; a test pins the hook's import set. A plug-in is code in the same
process, so the laws (read-only, no subprocess, text set as text) are checked on its code path, never inherited, and a
plug-in holds the whole process's reach. A plug-in that fails to load, or offers the wrong shape, becomes a problem
line; it never stops the rest.
"""
from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import jsonread, outside, paths

GROUP = "semantext.plugins"
KINDS = ("source", "place", "checker")                                       # open now
RESERVED = ("card-format", "evidence-policy", "door", "tool", "exporter")    # named, empty, refused
BUILT_IN = "built-in"   # the words shown for a built-in's origin; never how one is told apart (Entry.builtin)
ENABLED_FILE = "plugins.json"
# A plug-in's name, after its kind: letters, digits, _ and -, so "<kind>.<name>" holds one dot and nothing a shell, a
# path or a page would read as more than a word (an entry point named "source.x$(calc)" is refused, never listed).
NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
# What each open kind must offer: the attributes the page or the command line reaches (api.py states the contracts).
NEEDS = {"source": ("name", "keys", "read"), "place": ("name", "title", "build"), "checker": ("name", "records")}


@dataclass(frozen=True)
class Entry:
    kind: str
    name: str
    origin: str          # "built-in", or the distribution that installed it
    obj: object
    version: str | None = None
    dist: object = None  # the installed distribution (importlib.metadata), for an outside plug-in: its files
    reads_ctx: bool | None = False   # a source's read(config, ctx) or a place's build(sources, ctx); False: called as in
    # api 0.1; None: not known for this answer (its signature could not be read), so it is not called at all
    ctx_trouble: str | None = None   # why reads_ctx is None
    builtin: bool = False   # set by Registry.add alone, for the package's own code registered with no origin: never
    # read from a name. An installed distribution may be called "built-in"; it is an outside plug-in all the same, held
    # to the worker, the budget, the caps and the ctx (the Fable review of 70f2d3c, finding 1)


def _own_code(obj) -> bool:
    """Whether obj is this package's own: its class is defined in a module of semantext."""
    module = getattr(type(obj), "__module__", None)
    return type(module) is str and (module == "semantext" or module.startswith("semantext."))


def _shape_takes_ctx(read) -> bool:
    """takes_ctx's question, asked directly: for the built-ins' own code, and in the worker for an outside plug-in's."""
    params = list(inspect.signature(read).parameters.values())
    if any(p.kind is inspect.Parameter.VAR_POSITIONAL for p in params):
        return True
    return len([p for p in params if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                                inspect.Parameter.POSITIONAL_OR_KEYWORD)]) >= 2


def _built_in_takes_ctx(read) -> bool:
    try:
        return _shape_takes_ctx(read)
    except Exception:  # noqa: BLE001  a signature that cannot be read is the 0.1 shape
        return False


def ctx_shape(read, owner: str) -> tuple[bool | None, str | None]:
    """Whether a source's read, a place's build or its resolve can be given a second argument, the read context (api
    0.2): two positional parameters, or *args. Asked once for read and build, when the plug-in is added (for that one
    answer: load_enabled makes a new registry for every answer), and for resolve when a document is served.

    Reading a signature can run the plug-in's code (a __signature__ property, a __wrapped__ chain), so it is read in the
    worker, under the budget, as the plug-in's own call (the recheck of 4d78973, NH2: on the caller's thread a property
    that slept and then raised CancelledError held the handler and escaped registry.add). `owner` is the plug-in's
    registration name, "<kind>.<name>" (key): the read is counted with its other calls.

    (True or False, None) when it was read; (None, why) when it could not be: Busy, Late, or an error. None is never
    taken as False: before, a Busy or Late answer was kept as the 0.1 shape for the whole answer, so a build that takes
    ctx was then called without it, and judged closed places against the default home (the recheck of 17021c2, NH4).
    A caller given None skips that call for this answer, with a problem line; the next answer asks again."""
    try:
        got = outside.run(_shape_takes_ctx, read, owner=owner, call="signature")
    except outside.Busy as e:
        return None, f"Busy: {e}"
    except outside.Late as e:
        return None, f"Late: {e}"
    except Exception as e:  # noqa: BLE001  run says every BaseException of the plug-in's as a RuntimeError
        return None, f"{type(e).__name__}: {e}"
    if type(got) is not bool:
        return None, "its signature gave no plain answer"
    return got, None


def takes_ctx(read, owner: str) -> bool | None:
    """ctx_shape's answer alone: True, False, or None when it could not be told (never read as False)."""
    return ctx_shape(read, owner)[0]


def not_without_ctx(what: str, why: str | None) -> str:
    """The words for a call skipped because whether it takes the read context could not be told: what matters first,
    the reason (a Busy can name four plug-ins) last, so a cut to 300 characters never loses it."""
    return (f"not called without the read context, and asked again at the next answer: whether its {what} takes one "
            f"could not be told ({why})")[:300]


def key(kind: str, name: str) -> str:
    """A plug-in's registration name, "<kind>.<name>", as its entry point names it: what every call made on its behalf
    is counted under (outside.run's owner)."""
    return f"{kind}.{name}"


def _problem(name: str, kind: str, text: str) -> dict:
    return {"source": f"plug-in {name}", "line": None, "kind": kind, "text": str(text)[:300]}


class Registry:
    """Plug-ins by kind, in the order they were added. A name is one plug-in within its kind: a second one of the same
    name is refused, so an outside plug-in can never stand in for a built-in."""

    def __init__(self):
        self._by: dict[str, dict[str, Entry]] = {k: {} for k in KINDS + RESERVED}
        self.problems: list[dict] = []

    def add(self, kind: str, name: str, obj, origin: str | None = None, version: str | None = None,
            dist=None) -> Entry:
        """Add a plug-in. With no origin it is a built-in: the package's own code (its class defined under semantext),
        flagged here and nowhere else. With an origin, the distribution that installed it, it is an outside plug-in,
        whatever that name says ("built-in" included)."""
        if kind not in KINDS:
            raise ValueError(f"{kind!r} is not a kind of plug-in that is open ({', '.join(KINDS)})")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise ValueError(f"a plug-in's name is letters, digits, _ and - (at most 64), not {str(name)[:80]!r}")
        if name in self._by[kind]:
            raise ValueError(f"there is already a {kind} named {name!r} ({self._by[kind][name].origin})")
        missing = [a for a in NEEDS[kind] if not hasattr(obj, a)]
        if missing:
            raise ValueError(f"a {kind} needs {', '.join(missing)}")
        if kind == "source":
            from .sources.closed import RESERVED_KEYS   # here: the registry is read before the sources package
            reserved = {r.casefold() for r in RESERVED_KEYS}   # in any case, as the page and load_enabled judge them
            taken = [k for k in (getattr(obj, "keys", None) or ()) if isinstance(k, str)
                     and k.strip().casefold() in reserved]
            if taken:   # else load_config would hand a plug-in the person's closures as its own settings
                raise ValueError(f"its keys name {', '.join(map(repr, taken))}, which are reserved: the person's "
                                 f"closures, given to a plug-in in its ReadContext and never as settings")
        builtin = origin is None
        if builtin and not _own_code(obj):
            raise ValueError(f"a {kind} added with no origin is a built-in, and a built-in is Semantext's own code; "
                             f"an outside plug-in is added with the distribution that installed it")
        if not builtin and (type(origin) is not str or not origin):
            raise ValueError("an outside plug-in is added with the name of the distribution that installed it")
        call = obj.read if kind == "source" else obj.build if kind == "place" else None
        if call is not None and not callable(call):   # said once, plainly: never "asked again" for a fault that stays
            raise ValueError(f"its {'read' if kind == 'source' else 'build'} cannot be called, so it is not added")
        # a built-in's signature is the package's own code, read here; an outside one's is read in the worker
        ctx, why = (False, None) if call is None else (_built_in_takes_ctx(call), None) if builtin else \
            ctx_shape(call, key(kind, name))
        entry = Entry(kind, name, BUILT_IN if builtin else origin, obj, version, dist, ctx, why, builtin)
        self._by[kind][name] = entry
        return entry

    def get(self, kind: str, name: str) -> Entry | None:
        return self._by.get(kind, {}).get(name)

    def names(self, kind: str) -> tuple[str, ...]:
        return tuple(self._by.get(kind, {}))

    def entries(self, kind: str | None = None) -> list[Entry]:
        kinds = (kind,) if kind else KINDS + RESERVED
        return [e for k in kinds for e in self._by.get(k, {}).values()]

    def copy(self) -> "Registry":
        other = Registry()
        other._by = {k: dict(v) for k, v in self._by.items()}
        other.problems = list(self.problems)
        return other


# ---- what is installed (metadata only: no plug-in code runs) ----------------------------------------------------
@dataclass(frozen=True)
class Installed:
    name: str            # the plug-in's name, after the kind
    kind: str
    origin: str          # the distribution
    version: str | None
    point: object        # the entry point, loaded only when enabled
    dist: object = None  # the distribution, whose listed files a place's page module must be among (pagemodule.py)


def _entry_points():
    from importlib.metadata import entry_points   # here, not at the top: the import itself is part of discovery
    return entry_points(group=GROUP)


def installed() -> tuple[list[Installed], list[dict]]:
    """Every plug-in an installed package declares, read from the packages' metadata: nothing is imported. An entry
    point whose name is not "<kind>.<name>" is a problem, never guessed at. A "<kind>.<name>" that more than one
    package declares is a problem naming each, and none of them is listed, so none loads until all but one are removed:
    before, the command line took the first and the loader the last, so the loader said "changed, turn it on again"
    forever (the audit of the registry, c696d0b)."""
    found, problems = _declared()
    by_key: dict[str, list[Installed]] = {}
    for i in found:
        by_key.setdefault(f"{i.kind}.{i.name}", []).append(i)
    kept = []
    for key, same in by_key.items():
        if len(same) == 1:
            kept.append(same[0])
            continue
        who = "; ".join(f"{i.origin} {i.version or '(no version)'}" for i in same)
        problems.append(_problem(key, "declared twice", f"{len(same)} installed packages declare {key} ({who}), so "
                                                        f"none of them is loaded until all but one are removed"))
    return kept, problems


def _declared() -> tuple[list[Installed], list[dict]]:
    found, problems = [], []
    for ep in _entry_points():
        kind, _, name = str(ep.name).partition(".")
        dist = getattr(ep, "dist", None)
        origin = (getattr(dist, "name", None) or "an unknown package") if dist is not None else "an unknown package"
        version = getattr(dist, "version", None) if dist is not None else None
        if not name or kind not in KINDS + RESERVED:
            problems.append(_problem(ep.name, "unnamed", f"{origin} declares {ep.name!r}; a plug-in's entry point is "
                                                         f"named <kind>.<name>, the kind one of {', '.join(KINDS)}"))
            continue
        if not NAME.fullmatch(name):
            problems.append(_problem(repr(str(ep.name)[:80]), "bad name",
                                     f"{origin} declares a plug-in named {str(ep.name)[:80]!r}; a name is letters, "
                                     f"digits, _ and - (at most 64), so it is not listed and never loads"))
            continue
        found.append(Installed(name, kind, origin, version, ep, dist))
    return found, problems


# ---- what the person turned on ------------------------------------------------------------------------------------
def enabled_file(home=None) -> Path:
    return Path(home) / ENABLED_FILE if home else paths.home() / ENABLED_FILE


def enabled(home=None) -> tuple[dict, list[dict]]:
    """{"<kind>.<name>": {"origin", "version", "at"}} as the person turned them on, and a problem when the file cannot
    be read (then nothing is on: a list that cannot be read turns nothing on). A list that names a plug-in twice, or
    gives any key twice, cannot be read: JSON would keep the last in silence (the audit of 784faf6, protection item 9)."""
    path = enabled_file(home)
    if not path.is_file():
        return {}, []
    try:
        data = jsonread.loads(path.read_text(encoding="utf-8-sig"), unique=True)
        rows = data.get("enabled") if isinstance(data, dict) else None
        if not isinstance(rows, dict):
            raise ValueError("it holds no \"enabled\" record")
    except (OSError, ValueError) as e:
        return {}, [_problem("list", "unreadable", f"{path} cannot be read, so no plug-in is on ({e})")]
    return {k: v for k, v in rows.items() if isinstance(k, str) and isinstance(v, dict)}, []


def write_enabled(rows: dict, home=None) -> Path:
    """Save the person's list: a new file beside the old, then put in its place, so a reader never sees half of one.
    Called only by the command line's enable and disable."""
    from .store import write_atomic   # here: the store is not needed to read the list
    path = enabled_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, json.dumps({"enabled": rows}, indent=2, sort_keys=True) + "\n")   # synced, then swapped in
    return path


# ---- loading ----------------------------------------------------------------------------------------------------
def load_enabled(base: Registry, home=None) -> Registry:
    """A copy of `base` with every plug-in the person turned on added, and a problem for each that could not be. With
    nothing turned on the packages' metadata is not even read. Loading one runs its package's code; a failure there is
    caught and said, and the rest load."""
    reg = base.copy()
    rows, trouble = enabled(home)
    reg.problems += trouble
    if not rows:
        return reg
    try:
        found, problems = installed()
    except Exception as e:  # noqa: BLE001  broken metadata costs the outside plug-ins, never the built-ins
        reg.problems.append(_problem("metadata", "unreadable", f"the installed packages cannot be read ({e})"))
        return reg
    reg.problems += problems
    by_key = {f"{i.kind}.{i.name}": i for i in found}
    for key, row in rows.items():
        i = by_key.get(key)
        if i is None:
            reg.problems.append(_problem(key, "not installed", "it is turned on but no installed package offers it"))
            continue
        if i.kind not in KINDS:
            reg.problems.append(_problem(key, "reserved", f"{i.kind} plug-ins are not open yet, so it is not loaded"))
            continue
        if (row.get("origin"), row.get("version")) != (i.origin, i.version):
            reg.problems.append(_problem(key, "changed", f"it was turned on as {row.get('origin')} "
                                                         f"{row.get('version')}, and {i.origin} {i.version} is "
                                                         f"installed now; turn it on again to load it"))
            continue
        try:   # importing it runs its package's code: in the worker, under the budget, as its other calls are (the
            # Fable review of 70f2d3c, F2: an import that blocked held every load_enabled, so every page answer)
            outside.identify(key, i.origin, i.version)   # its calls' health is this package and version's
            obj = outside.run(i.point.load, owner=key, call="import")
        except Exception as e:  # noqa: BLE001  a plug-in that fails to import, or is late, is a problem line
            reg.problems.append(_problem(key, "failed to load", f"{type(e).__name__}: {e}"))
            continue
        try:   # every attribute read once, guarded; from here on only the snapshot is read (outside.py)
            obj = outside.snapshot(obj)
        except outside.Bad as e:
            reg.problems.append(_problem(key, "bad attribute", e))
            continue
        declared = getattr(obj, "kind", i.kind)
        if declared != i.kind:
            reg.problems.append(_problem(key, "wrong kind", f"its entry point says {i.kind}, the object says "
                                                            f"{declared!r}"))
            continue
        if getattr(obj, "name", None) != i.name:
            reg.problems.append(_problem(key, "wrong name", f"its entry point says {i.name!r}, the object says "
                                                            f"{getattr(obj, 'name', None)!r}"))
            continue
        from . import pluginpage   # here: the reserved keys, read only when one loads, are the ones the page refuses:
        kept = pluginpage.reserved_keys(home)   # Semantext's own, and the keys your sources file reads closures from
        asked = tuple(getattr(obj, "keys", ()) or ()) + tuple(getattr(obj, "needs", ()) or ())
        taken = [k for k in asked if type(k) is str and k.strip().casefold() in kept]
        if taken:   # its keys would be given Semantext's own settings, or the closures: it is not loaded
            reg.problems.append(_problem(key, "reserved key", f"its keys name {taken[0]!r}, a key of Semantext's own "
                                                              f"or of your closures, so it is not loaded"))
            continue
        try:
            reg.add(i.kind, i.name, obj, origin=i.origin, version=i.version, dist=i.dist)
        except ValueError as e:
            reg.problems.append(_problem(key, "refused", e))
    return reg
