"""Closed places: folders the person has said nothing of Semantext's may read, judged in one place.

Before this, no shared check existed: each part judged on its own (ECOSYSTEM.md, "Settled from the reviews": one shared
`is_closed_place(path)`, fed from the configured closures). The closures are the person's, written in the sources file
under one more key, or kept in a file of their own that the sources file names (or both, and the lists merge):

    "closed": ["C:\\Users\\me\\Private", "~/secrets-folder"],
    "closures_file": "C:\\Users\\me\\closures.json",   a JSON file of the person's own
    "closures_key": "closed"                              the key in it holding the list ("closed" when not given)

each a full path (a leading ~ is the user's home). A path is closed when it is one of them or lies inside one, compared
as this system compares paths, both as written and with every link resolved, so a link that leads into a closed folder
is closed too.

It fails closed. For a plug-in (is_closed_place, the api's check) the closures must be KNOWN: named by one of the two
keys, and readable. No closures named at all (no "closed" key and no closures file, or no sources file) closes every
path, and `semantext plugins enable` refuses until some are named (an owner ruling of 24 October: the person's own
sources file named none, so the check refused nothing). An explicit empty list is a statement that nothing is closed,
and is known. A sources file or closures file that cannot be read, one that gives any key twice (JSON would keep only
the last), or a list that is not of full paths, is unknown too, and closes every path.

The built-in readers keep their own rule (in_closed_place): no closures named closes nothing, since then no roots are
named either and nothing is read; what cannot be read still closes everything. Like the rest of the sources file this
is a file an agent can edit; the check holds a plug-in that follows the rules, and is no bar against code set on
reading a closed place.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .. import jsonread, paths
from . import config_path

KEY = "closed"
FILE_KEY, LIST_KEY = "closures_file", "closures_key"   # a closures file of the person's own, and the key in it
MAX_CLOSURES_FILE = 1024 * 1024                        # bytes; a larger closures file is unknown, never read
NOT_NAMED = "no closures are named"                    # what named() says when neither key is there


def _file(home=None) -> Path:
    named = os.environ.get("SEMANTEXT_SOURCES")
    if named:
        return Path(named).expanduser()
    return Path(home) / "sources.json" if home else config_path()


def _load(path: Path, limit: int | None = None):
    """A JSON file as a record, or None when it cannot be read, is too large, is not a record, or gives any key twice
    in one object (JSON keeps the last of two equal keys, so a first closures_file or closures_key would be replaced
    unseen; before, only "closed" twice was refused: the audit of 784faf6, protection item 9)."""
    try:
        if limit is not None and path.stat().st_size > limit:
            return None
        data = jsonread.loads(path.read_text(encoding="utf-8-sig"), unique=True)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _paths(said) -> list[str] | None:
    """A list of full paths (a leading ~ expanded), or None when it is anything else."""
    if not isinstance(said, list):
        return None
    out = []
    for c in said:
        if not isinstance(c, str) or not c.strip():
            return None
        full = os.path.expanduser(c.strip())
        if not os.path.isabs(full):
            return None
        out.append(full)
    return out


def named(home=None) -> list[str] | None | str:
    """The closed folders the person named, as full paths, from "closed" and the closures file together; NOT_NAMED
    when neither is there (or there is no sources file); None when they cannot be known."""
    path = _file(home)
    if not path.is_file():
        return NOT_NAMED
    data = _load(path)
    if data is None:
        return None
    out, found = [], False
    if KEY in data:
        listed = _paths(data[KEY])
        if listed is None:
            return None
        out, found = out + listed, True
    if FILE_KEY in data or LIST_KEY in data:
        where, key = data.get(FILE_KEY), data.get(LIST_KEY, KEY)
        if not (isinstance(where, str) and where.strip() and isinstance(key, str) and key.strip()):
            return None   # a closures key without a closures file, or either not a text, is a malformed setting
        where = Path(os.path.expanduser(where.strip()))
        if not where.is_absolute():
            return None
        kept = _load(where, MAX_CLOSURES_FILE)
        listed = _paths(kept.get(key)) if kept is not None and key in kept else None
        if listed is None:
            return None
        out, found = out + listed, True
    return list(dict.fromkeys(out)) if found else NOT_NAMED


def closures(home=None) -> list[str] | None:
    """The closed folders, as full paths; [] when none are named; None when they cannot be known. The built-in
    readers' view: none named closes nothing (see the module's note)."""
    said = named(home)
    return [] if said == NOT_NAMED else said


def closures_known(home=None) -> bool:
    """Whether the person's closures are named and readable: what a plug-in's reads, and turning one on, need."""
    return isinstance(named(home), list)


def _unprefixed(path: str) -> str:
    """A Windows path without the \\\\?\\ prefix that turns off its parsing: \\\\?\\C:\\x is C:\\x, and \\\\?\\UNC\\host\\share
    is \\\\host\\share, with either slash in the prefix. realpath keeps the prefix it is given, so before this a closed
    folder's file written as \\\\?\\C:\\...\\closed\\README.md compared open (an attack on the first outside plug-in,
    finding 2). Elsewhere a path is returned as it is."""
    if os.name != "nt" or path[:4].replace("/", "\\") != "\\\\?\\":
        return path
    rest = path[4:]
    if rest[:4].replace("/", "\\").upper() == "UNC\\":
        return "\\\\" + rest[4:]
    return rest


def _forms(path: str) -> set[str]:
    """A path as written and with its links resolved, each as this system compares paths, the \\\\?\\ prefix taken off
    first (and off what realpath gives back)."""
    path = _unprefixed(path)
    out = {os.path.normcase(os.path.normpath(path))}
    try:
        out.add(os.path.normcase(_unprefixed(os.path.realpath(path))))
    except (OSError, ValueError):
        pass
    return out


def _inside(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)


def _real(path: str) -> str | None:
    """Where a path really leads, every link resolved and the \\\\?\\ prefix off, as this system compares paths."""
    try:
        return os.path.normcase(_unprefixed(os.path.realpath(_unprefixed(os.path.abspath(str(path))))))
    except (OSError, ValueError):
        return None


def inside_roots(path, roots) -> bool:
    """Whether `path`, with its links resolved, lies inside one of `roots` (each resolved the same way). Stricter than
    the closed check on purpose: there any spelling inside a closure closes the path; here only where the path really
    leads counts, so a link inside a root that leads out of every root is outside."""
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        return False
    real = _real(path)
    if real is None:
        return False
    return any(r is not None and _inside(real, r) for r in (_real(root) for root in roots if root))


@dataclass(frozen=True)
class ReadContext:
    """What a Source's read(config, ctx) is given (api 0.2): the Semantext home the page was started with, and the
    person's closures as read once for this build (full paths; None when they cannot be known, which closes every
    path). is_closed_place(path, ctx) judges against these, so a plug-in and the page agree on one home."""
    home: str
    closures: tuple[str, ...] | None


def context(home=None) -> ReadContext:
    """The context for one build of the page, from the home given (the default home when None). Its closures are None
    unless they are known, so a plug-in's read judges every path closed until the person names them."""
    said = named(home)
    return ReadContext(str(home) if home else str(paths.home()), tuple(said) if isinstance(said, list) else None)


def is_closed_place(path, ctx=None) -> bool:
    """Whether `path` is in a place the person closed: the api's check, for a plug-in. `ctx` is a ReadContext (its
    closures are used), or a Semantext home (api 0.1's second argument), or None for the default home. True for
    every path while the closures are not known (none named, or unreadable), and for anything that cannot be judged."""
    said = ctx.closures if isinstance(ctx, ReadContext) else named(ctx)
    return _judge(path, said if isinstance(said, (list, tuple)) else None)


def in_closed_place(path, home=None) -> bool:
    """The built-in readers' check: as is_closed_place, except that no closures named closes nothing."""
    return _judge(path, closures(home))


LONG_DRIVE = re.compile(r"[\\/]{2}\?[\\/][A-Za-z]:(?:[\\/]|$)")   # \\?\C:\..., the one prefixed form taken as local
MAX_PARTS = 128                                                     # ancestors whose identity one judgement compares


def _shared(text: str) -> bool:
    """A Windows path that starts with two separators and is not the \\\\?\\X: drive form: a share (\\\\localhost\\C$,
    \\\\127.0.0.1\\C$), \\\\?\\UNC\\..., \\\\?\\GLOBALROOT\\Device\\..., \\\\.\\.... Each can name a closed folder's bytes
    by a spelling no path comparison sees (the audit of 784faf6, finding 2; rules.not_local holds the same paths back
    for one reader), so while any closure exists such a path is closed."""
    return os.name == "nt" and text[:2] in ("\\\\", "//", "\\/", "/\\") and not LONG_DRIVE.match(text)


def _identity(path: str):
    try:
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    return (st.st_dev, st.st_ino) if st.st_ino else None   # no file index on this volume: nothing to compare


def _ancestry(path: str) -> set:
    """The (volume, file index) of the path and of each folder above it, where the system gives one."""
    out, here = set(), path
    for _ in range(MAX_PARTS):
        ident = _identity(here)
        if ident:
            out.add(ident)
        up = os.path.dirname(here)
        if not up or up == here:
            break
        here = up
    return out


def _judge(path, closed) -> bool:
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        return True
    if closed is None:
        return True
    try:
        text = os.path.expanduser(str(path))
        if closed and _shared(text):
            return True
        here = _forms(os.path.abspath(text))
    except (OSError, ValueError):
        return True
    if any(_inside(p, c) for folder in closed for c in _forms(folder) for p in here):
        return True
    if not closed:
        return False
    # The same folder by another name a path cannot show (a mapped or subst drive, a share): compare what the system
    # says each is, the path's folders against the closed ones. A hard link to a closed file is not seen this way: a
    # file's other names cannot be listed. The serve hook refuses any file with a second name (docserve, nlink).
    shut = {i for i in (_identity(f) for folder in closed for f in _forms(folder)) if i}
    return bool(shut) and any(i in shut for p in here for i in _ancestry(p))
