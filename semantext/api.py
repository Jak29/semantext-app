"""semantext.api: the one surface a plug-in imports, and nothing else of the package is public.

Version 0.2, and experimental: it stays 0.x until each kind has a user that is not a built-in (ECOSYSTEM.md, "Settled
from the reviews"; the ecosystem review, section 5), since until then a contract is only the built-ins' shape. 0.2 is
what the first outside plug-ins asked for (ECOSYSTEM.md, "semantext.api 0.2"); everything in 0.1 still works as it did.

A plug-in is an installed package with an entry point in the group `semantext.plugins`, named "<kind>.<name>", that
points at an object of one of the three kinds below. Installing it turns nothing on: the person turns it on at a
console with `semantext plugins enable <kind>.<name>`, and only once they have named their closed places. It is loaded
by the page's server and the command line, never by the card hook. It runs in their process with their whole reach;
the laws (read only, start no process, set a person's text as text) are checked on its code path, never inherited
(SECURITY.md, "Plug-ins").

What is here, and why each:
    VERSION, GROUP, KINDS   which surface this is, where plug-ins are declared, and which kinds are open
    Source, Place, Checker  the three contracts open now (ship order: these first)
    problem, read_lines     the text-only helpers every built-in reader uses: an unusable line becomes a problem
                            record, never dropped; a JSON-lines file read with its BOM and over-long lines handled
    is_closed_place         the one shared judgement of where nothing may be read, from the person's closures
    fingerprint             the change-evidence digest, as the page computes it, so a filer imports nothing else
  new in 0.2:
    ReadContext             what Source.read(config, ctx) is given: the home, and the closures read once per build
    closures_known(ctx)     whether the person's closures are named and readable
    named_roots(ctx)        the seats file's roots, [{name, path, kind}], resolved by the Places reader's rules
    seat_rows(ctx)          the seats in the group, [{seat, home, groups}], by the Waiting reader's rules
    inside_roots(path, ctx) the one "inside a named root, outside every closed place" judgement
    taken_names(kind)       the names already registered, built-ins and installed, to avoid a collision

What changed in 0.2:
  - Source.read(config, ctx): a read that takes two arguments is given the build's ReadContext; read(config) is called
    as before (the signature is read once, at registration). A Source's `needs` is part of the contract. A Place's
    build(sources, ctx) and its resolve(row_id, ctx) are given the same context when they take two arguments.
  - A Source's keys may hold lists: of plain texts and numbers, or of flat records (at most 200 entries, 16 plain
    fields each); any other shape is a problem line of that source. Before, every list was dropped.
  - is_closed_place(path, ctx=None) takes a ReadContext as well as a home. It is True for every path while the
    closures are not known: none named (no "closed" key, no "closures_file"), or not readable. It takes the \\\\?\\
    prefix off a Windows path before comparing (before, \\\\?\\C:\\...\\closed\\x compared open).
  - A Place may serve documents by row: resolve(row_id) and check_bytes(data), at /api/v2/doc/<name>/<row_id>. A
    resolve may name a byte span of a file, (path, start, end), so a row of a larger file is sent alone.
  - Each call into a plug-in has a time budget (5 s, SEMANTEXT_PLUGIN_SECONDS) and its answer has caps (200 problems,
    300 characters a field, 2 MB of JSON, 8 MB for one page's together); SystemExit is caught, KeyboardInterrupt is
    not. A plug-in's attributes are read once, at load, and must be plain values. A Place is given a copy of the
    sources' answers. A name two packages declare loads neither.

Stated limits (SECURITY.md, "Plug-ins", says each):
  - A plug-in is code in the person's process: none of the above is a sandbox, only what the kernel does on its side.
  - A late call is not stopped: a thread cannot be killed, so it runs on in the background until it returns.
  - The serve hook checks a path and then opens it: a folder swapped for a link between the two is not seen.
  - A page module is unrestricted code in the page. The page's policy stops loads from other sites (and, since 0.2,
    inline styles as well as inline scripts); the text-only helpers are the easy path, not a sandbox.
  - The closures, the plug-in list and the sources file are files an agent can edit; "typed at a console" bars an
    agent that follows the rules, and no more.

Not here yet: the evidence policy (which files a change card may cite). It lives in `semantext/sources/evidence.py`,
with one module per way (the page's is git-index: a file the project's git index lists); it is not a plug-in kind
yet, so only the fingerprint that applies it is exposed. fingerprint(files, roots) takes the filer's roots as before
and reads them through the page's way, so a filer gets the page's digest; since git-index, a file no repository lists
gets no digest ("unknown"), where before 0.2's kind and name lists decided.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .registry import GROUP, KINDS
from .sources import MAX_LINE, problem, read_lines
from .sources.change import fingerprint
from .sources import kernel as _kernel
from .sources import closed as _closed
from .sources.closed import ReadContext, is_closed_place

VERSION = "0.2"


def _home(ctx):
    return ctx.home if isinstance(ctx, ReadContext) else ctx


def closures_known(ctx=None) -> bool:
    """Whether the person's closed places are named and readable. While they are not, is_closed_place says True for
    every path. `ctx` is the read's ReadContext, or a Semantext home, or None for the default home."""
    if isinstance(ctx, ReadContext):
        return ctx.closures is not None
    return _closed.closures_known(ctx)


def named_roots(ctx=None) -> list[dict]:
    """The seats file's named roots, read only: [{"name", "path", "kind"}], each path in full as the Places reader
    resolves it against the base, a "{home}" root as one row per seat home in the group. [] when there is no seats
    file or it cannot be read. `ctx` is the read's ReadContext, or a Semantext home, or None for the default home."""
    return _kernel.named_roots(_home(ctx))


def inside_roots(path, ctx=None) -> bool:
    """Whether `path` lies inside one of the named roots and outside every closed place: the one judgement, the same
    the serve hook makes. The path is judged as it leads now: the \\\\?\\ prefix taken off, ".." worked out, every link
    resolved, so a link inside a root that leads out is outside. Closures win: a closed place inside a root is False,
    and while the closures are not known every path is. `ctx` as for named_roots."""
    return _kernel.inside_named_root(path, ctx)


def taken_names(kind=None) -> list[str]:
    """The names already taken, so a plug-in can avoid a collision before it ships (the registry refuses one at load):
    for a kind, the names of that kind, every built-in's and every one an installed package declares; for no kind,
    "<kind>.<name>" for all of them. Read from the packages' metadata: no plug-in code runs."""
    return _kernel.taken_names(kind)


def seat_rows(ctx=None) -> list[dict]:
    """The seats in the person's group, read only: [{"seat", "home", "groups"}], by the Waiting reader's rules (home is
    None where that reader would not follow it). [] when there is no seats file or it cannot be read. `ctx` as for
    named_roots."""
    return _kernel.seat_rows(_home(ctx))


@runtime_checkable
class Source(Protocol):
    """A reader of files the person already keeps. `keys` are the keys of the person's sources file it reads (each a
    text, or a list of texts and numbers). `read(config, ctx)` is given those keys and the build's ReadContext (`home`,
    and `closures`: the person's closed folders, or None when they cannot be known), and returns a record: its data,
    "problems" (a list of problem(...) records, one for every line it could not use), and "off": True when a key it
    needs is missing. It opens files for reading only, and asks is_closed_place(path, ctx) before opening one.

    `needs` (optional, a tuple of keys) IS part of the contract: the keys it cannot run without. The page reads it to
    say which settings a source that is off is missing (all of `keys` when it declares none).

    A read that takes one argument, `read(config)` as in api 0.1, is still called that way: the registry looks at the
    signature once, when the source is added."""

    kind: str     # "source"
    name: str
    title: str
    keys: tuple
    # needs: tuple   optional; see above

    def read(self, config: dict, ctx: ReadContext | None = None) -> dict: ...


@runtime_checkable
class Place(Protocol):
    """A part of the page, at /api/v2/<name>. `build(sources, ctx)` returns a record of what the place shows, where
    `sources[name]` is that source's answer for the person's group; nothing else of the argument is part of this
    contract. `ctx` is the ReadContext of the home the page was started with, as a Source's read is given; a build that
    takes one argument, `build(sources)`, is called that way. A built-in place's name or the person's own word cannot
    be taken.

    It may also declare `page_module`: the path of one ES module among its distribution's own installed files, relative
    and with forward slashes (e.g. "semantext_board/board.js"). When the person has turned the place on, the server
    serves it at /v2/plugin/<name>.js (the name a plain word: lower-case letters, digits, - and _), and the page imports
    it when you go to the place and calls its exported render(data, el, helpers): data is the place's JSON (build's
    record, without the frame), el an empty element of its own, and helpers dom.js's text-only {h, text}. A module that
    throws shows a problem line in its frame; the rest of the page goes on (pagemodule.py, static/v2/outside.js).

    It may also serve documents by row (api 0.2; docserve.py), by declaring both `resolve(row_id) -> path | None` (the
    full path of one row of its last read; `resolve(row_id, ctx)` is given the ReadContext the path is then judged
    against; it may instead give a span, `(path, start, end)`, a plain tuple of the path and two whole numbers, when
    the row is the bytes from start up to end of a larger file, and then only those bytes are read, checked and sent)
    and `check_bytes(data) -> problem | None` (None when the bytes pass). The
    kernel then answers /api/v2/doc/<name>/<row_id> to the page: the row id must be letters, digits, - and _ (never a
    path), and at serve time the path must lie, as it leads now, inside a named root and outside every closed place;
    the bytes are read once, and exactly those bytes go to check_bytes. They are sent with the document policy
    (default-src 'none'; sandbox), as `doc_type` says ("image/svg+xml" unless it names image/png or plain text)."""

    kind: str     # "place"
    name: str
    title: str

    def build(self, sources, ctx: ReadContext | None = None) -> dict: ...


@runtime_checkable
class Checker(Protocol):
    """Something that runs OUTSIDE the package and leaves run records; the page only reads them. `records` is where
    they are kept (None when it keeps none, as the built-in guards file does: a list of what should have a record is
    not a record)."""

    kind: str     # "checker"
    name: str
    records: str | None


__all__ = ["VERSION", "GROUP", "KINDS", "Source", "Place", "Checker", "problem", "read_lines", "MAX_LINE",
           "is_closed_place", "fingerprint", "named_roots", "seat_rows", "ReadContext", "closures_known",
           "inside_roots", "taken_names"]
