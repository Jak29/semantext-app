"""What semantext.api reads for a plug-in from the person's sources file, by the built-in readers' own rules.

A plug-in that judged roots or seat homes by its own copy of those rules could drift from them (the first outside
plug-in's REQUESTS.md, items 2 and 3, kept such a copy). Here the seat rows are the Waiting reader's (cards._seats) and
the named roots the Places reader's (places.named_roots), on the same sources file the page reads (view.config_file),
with the group it names. Read only; a file that cannot be read gives no rows, never an error. The one "inside a named
root" judgement (inside_named_root) and the names already taken (taken_names) are here for the same reason: the
second outside plug-in kept three copies of a stand-in for the first.
"""
from __future__ import annotations

from . import cards, closed, load_config, places


def config(home=None) -> dict:
    """The person's sources file as the page reads it, or {} when it cannot be read."""
    from .view import config_file   # here, not at the top: view imports the readers and the registry
    try:
        return load_config(config_file(home))
    except Exception:  # noqa: BLE001  an unreadable file gives no rows, as it gives the page a problem line
        return {}


def named_roots(home=None) -> list[dict]:
    """The seats file's named roots: {name, path, kind}, a "{home}" root as one row per seat home."""
    return places.named_roots(config(home))[0]


def inside_named_root(path, ctx=None) -> bool:
    """The one "inside a named root" judgement: `path`, as it leads now (the \\\\?\\ prefix off, every link resolved),
    lies inside one of the named roots, and is not in a closed place (closures win). `ctx` is a ReadContext, a
    Semantext home, or None. Used by the serve hook and by api.inside_roots, so a plug-in keeps no copy of it."""
    home = ctx.home if isinstance(ctx, closed.ReadContext) else ctx
    if not closed.inside_roots(path, [r["path"] for r in named_roots(home)]):
        return False
    return not closed.is_closed_place(path, ctx if isinstance(ctx, closed.ReadContext) else home)


def taken_names(kind=None) -> list[str]:
    """The names already registered: every built-in's, and every name an installed package declares (read from the
    packages' metadata; no plug-in code runs). For one kind, its names; for none, "<kind>.<name>" for every kind."""
    from .. import registry
    from .view import BUILT_IN   # here: view imports every reader
    if kind is not None and kind not in registry.KINDS + registry.RESERVED:
        raise ValueError(f"{kind!r} is not a kind of plug-in ({', '.join(registry.KINDS + registry.RESERVED)})")
    pairs = {(e.kind, e.name) for e in BUILT_IN.entries()}
    try:
        found, _problems = registry._declared()   # every declaration, the ones declared twice included: all taken
    except Exception:  # noqa: BLE001  metadata that cannot be read takes no name; the built-ins are still listed
        found = []
    pairs |= {(i.kind, i.name) for i in found}
    if kind is not None:
        return sorted(n for k, n in pairs if k == kind)
    return sorted(f"{k}.{n}" for k, n in pairs)


def seat_rows(home=None) -> list[dict]:
    """The seats in the group the sources file names (every seat when none): {seat, home, groups}. home is the full
    folder by the Waiting reader's rule, or None when that reader would not follow it (empty, a NUL, outside the base).
    A home that does not exist is still given; the Waiting reader says so as a problem."""
    cfg = config(home)
    if not cfg.get("seats"):
        return []
    group = cfg["group"] if isinstance(cfg.get("group"), str) and cfg["group"] else None
    return [{"seat": r["seat"], "home": r["home"], "groups": list(r["groups"])}
            for r in cards._seats(cfg["seats"], [], group)]
