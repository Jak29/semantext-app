"""What semantext.api reads for a plug-in from the person's sources file, by the built-in readers' own rules.

A plug-in that judged roots or seat homes by its own copy of those rules could drift from them (the first outside
plug-in's REQUESTS.md, items 2 and 3, kept such a copy). Here the seat rows are the Waiting reader's (cards._seats) and
the named roots the Places reader's (places.named_roots), on the same sources file the page reads (view.config_file),
with the group it names. Read only; a file that cannot be read gives no rows, never an error. The one "inside a named
root" judgement (inside_named_root) and the names already taken (taken_names) are here for the same reason: the
second outside plug-in kept three copies of a stand-in for the first.
"""
from __future__ import annotations

import difflib
import os
from pathlib import Path

from ..pathrule import SeatsUnread, seats_path
from . import cards, closed, load_config, places


def config(home=None) -> dict:
    """The person's sources file as the page reads it, or {} when it cannot be read. "_file" says where it is, so the
    closures are read beside it (as the page's own config says, view._config)."""
    from .view import config_file   # here, not at the top: view imports the readers and the registry
    try:
        path = config_file(home)
        return {**load_config(path), "_file": str(path)}
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


def seat_names(home=None) -> tuple[set[str] | None, str | None]:
    """Who is a seat, for a check that must know: (the seat names, None), or (None, None) in exactly one case, no seats
    configured at all: no sources file where the default one would be (SEMANTEXT_SOURCES not set), or a readable
    sources file with no "seats" key and no key that looks like a misspelling of it. Then there is nothing to check a
    seat against, and the caller says so aloud. Every other case is (None, why), and a caller given why refuses
    rather than skips its check: SEMANTEXT_SOURCES naming a file that is not there; a sources file that is a folder,
    cannot be read, or is not a record; a key near "seats" ("Seats", "seat") with no "seats"; a "seats" that is not
    the path of a file (a number, null, a list, a record, an empty text); a seats file that cannot be read or holds no
    table of seats. A base that is wrong drops only the homes (cards._seats), never the names."""
    from .. import jsonread
    from .view import config_file   # here, not at the top: view imports the readers and the registry
    path = Path(config_file(home))
    if not path.exists():
        if os.environ.get("SEMANTEXT_SOURCES"):
            return None, f"SEMANTEXT_SOURCES names {path}, which is not there"
        return None, None
    if not path.is_file():
        return None, f"the sources file {path} is not a file"
    try:
        data = jsonread.loads(path.read_text(encoding="utf-8-sig"), unique=True)
    except (OSError, ValueError) as e:   # a sources file that cannot be read is not "no seats configured"
        return None, f"the sources file {path} cannot be read ({type(e).__name__})"
    if not isinstance(data, dict):
        return None, f"the sources file {path} is not a record of settings"
    if "seats" not in data:
        near = [k for k in data if isinstance(k, str) and _near_seats(k)]
        if near:
            return None, f"the sources file has {near[0]!r} and no 'seats'; if it is meant as the seats file, spell it 'seats'"
        return None, None
    value = data["seats"]
    if not (isinstance(value, str) and value.strip()):
        return None, f"'seats' in the sources file is {type(value).__name__}, not the path of a seats file"
    group = data["group"] if isinstance(data.get("group"), str) and data["group"] else None
    try:   # relative to the sources file's folder, as every reader and the card hook resolve it
        value = str(seats_path(value, path.parent))
    except SeatsUnread as e:
        return None, f"the seats file {value}: {e}"
    problems: list[dict] = []
    rows = cards._seats(value, problems, group)
    if not rows and problems:
        return None, problems[0]["text"]
    return {r["seat"] for r in rows}, None


def _near_seats(key: str) -> bool:
    """A key that looks meant for "seats": the same word in another case or with spaces around it, the singular, or
    one letter from it ("seets", "seatss")."""
    k = key.strip().casefold()
    return k in ("seats", "seat", "seats_file", "seatsfile", "seats file") or (
        k != "seats" and len(k) in (4, 5, 6) and difflib.SequenceMatcher(None, k, "seats").ratio() >= 0.8)


def seat_rows(home=None) -> list[dict]:
    """The seats in the group the sources file names (every seat when none): {seat, home, groups}. home is the full
    folder by the Waiting reader's rule, or None when that reader would not follow it (empty, a NUL, or a home
    sources.under refuses: a control character, a space before or after it, a part ending in a dot or a space, a colon
    past a drive letter, a ".." step, or a drive, a root or a share of its own, a full path among them; or every home,
    when sources.base_of refuses the base). That is the join the places and gates readers make too, so a seat row and a
    named root agree on a home. A home that does not exist is still given; the Waiting reader says so as a problem."""
    cfg = config(home)
    if not cfg.get("seats"):
        return []
    group = cfg["group"] if isinstance(cfg.get("group"), str) and cfg["group"] else None
    return [{"seat": r["seat"], "home": r["home"], "groups": list(r["groups"])}
            for r in cards._seats(cfg["seats"], [], group)]
