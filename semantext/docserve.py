"""The serve hook by row: one document of an enabled outside place, at /api/v2/doc/<place>/<row_id> (api 0.2).

The first outside plug-in needed to show its SVGs and had no route (its REQUESTS.md, item 1; docs/plugin-api.md,
"Documents by row: the serve hook"). A place may declare

    resolve(row_id) -> path | (path, start, end) | None
                                       the file behind one row of its last read, or a span of it (the bytes from start
                                       up to end), or None; resolve(row_id, ctx) is given the ReadContext as well
    check_bytes(data) -> problem | None   its own check of the bytes about to be served (None: they pass)

A span is for a row that is part of a larger file, such as a leaf of a log: only those bytes are read, checked and
sent, never the whole file, and the span (not the file) is held to MAX_DOC. A span that runs past the file's end as
it is now is refused (416).

and the kernel serves the row. No part of the request ever reaches the file system: the place name and the row id
must each match a strict pattern before anything is looked up, the place must be one the person turned on, and the
path comes only from the place's resolve. At serve time the kernel re-checks that path, as it leads now: inside one
of the named roots (api.named_roots), and not in a closed place; then it reads the bytes once and hands exactly those
bytes to check_bytes, so a file changed after the read (a script added to an SVG) is refused, not served. The answer
carries the document policy the page already uses for diagrams (DOC_CSP), and is shown only through <img>.

Limit: the check and the open are two steps, so a folder swapped for a link between them is not seen. The file opened
is the path as resolved for the check, which narrows that window to a change of a folder on the way to it.
"""
from __future__ import annotations

import os
import re
import stat

from . import outside, pagemodule, registry
from .sources import closed, kernel

ROW = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")   # no dot, slash, colon or space: never a path
MAX_DOC = 4 * 1024 * 1024   # bytes in one served document; a larger one is refused, never read whole
DOC_CSP = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
TYPES = {"image/svg+xml", "image/png", "text/plain; charset=utf-8"}   # what a place may say its documents are
DEFAULT_TYPE = "image/svg+xml"


class Refused(Exception):
    def __init__(self, status: int, why: str):
        super().__init__(why)
        self.status, self.why = status, why


def _place(name: str, home):
    from .sources.view import BUILT_IN   # here: view imports every reader
    entry = registry.load_enabled(BUILT_IN, home).get("place", name)
    if entry is None or entry.builtin:
        raise Refused(404, "no place the person turned on has that name")
    if not (callable(getattr(entry.obj, "resolve", None)) and callable(getattr(entry.obj, "check_bytes", None))):
        raise Refused(404, "that place serves no documents (it declares no resolve and check_bytes)")
    return entry.obj


def _over() -> str:
    return f"{MAX_DOC // (1024 * 1024)} MB" if MAX_DOC >= 1024 * 1024 else f"{MAX_DOC} bytes"


SCALARS = (str, int, float, bool, type(None))   # the exact types a span's parts may cross back as


def _plain_path(p):
    """In the worker: a path as an exact str. An os.PathLike's __fspath__ is its own code, so it runs here."""
    if isinstance(p, os.PathLike):
        p = os.fspath(p)
    if type(p) is not str:
        raise TypeError("the place gave something other than a path")
    return p


def _plain_found(got):
    """In the worker, as resolve's post: what it gave, as exact built-in types and nothing else (None, a str, or a tuple
    of exact str, int, float, bool or None), or TypeError. Before, the serve hook called str() and os.path on it on the
    handler thread, so a str subclass or a PathLike whose own __str__ slept and then raised CancelledError held the
    handler and escaped serve (the recheck of 4d78973, row 1). Iterating a plain tuple or list runs no plug-in code."""
    if got is None or type(got) is str:
        return got
    if type(got) in (tuple, list):
        return tuple(x if type(x) in SCALARS else _plain_path(x) for x in got)
    return _plain_path(got)


PASSED = object()   # what check_bytes's post gives for a check that said None: the one value serve passes bytes on


def _plain_trouble(said):
    """In the worker, as check_bytes's post: PASSED when the check said None (the bytes pass), or what it said as an
    exact str of at most 200 characters. Its own __str__ runs here, under the budget, never on the handler thread.

    The pass is an explicit value made here, never None itself: serve passes the bytes only on PASSED, so a call that
    came back with nothing, whatever the reason, is a check that did not pass (the Fable review of 70f2d3c, finding
    2: a check raising SystemExit with an unreadable code came back as None, and the document was served)."""
    if said is None:
        return PASSED
    text = said if type(said) is str else str(said)
    if type(text) is not str:
        raise TypeError("its check said something that is not text")
    return text[:200]


def _span(got):
    """(path, start, end) from what resolve gave: a path, or a span of one, (path, start, end), the bytes from start up
    to end. Only a plain tuple or list of three is a span, and its start and end plain whole numbers: a subclass's own
    code would run here, on the caller's thread, outside the budget (as in the audit of 784faf6, findings 5 and 6)."""
    if type(got) not in (tuple, list):
        return got, None, None
    if len(got) != 3:
        raise Refused(404, "a span is (path, start, end)")
    path, start, end = got
    if type(start) is not int or type(end) is not int or not 0 <= start < end:
        raise Refused(404, "a span's start and end are whole numbers, with 0 <= start < end")
    if end - start > MAX_DOC:
        raise Refused(413, f"the span is over {_over()}, so it is not served")
    return path, start, end


def _read_once(path: str, start: int | None = None, end: int | None = None) -> bytes:
    """The document's bytes, or with a span the bytes from start up to end, read once from one descriptor. A span is
    held to MAX_DOC, not the file: a leaf of a large log is served without the rest of it."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except (OSError, ValueError):
        raise Refused(404, "the document is not there") from None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused(404, "the row does not name a file")
        if st.st_nlink > 1:   # a hard link is a second path to the same bytes: the closures judge paths, so a closed
            # file linked into a root would pass them (the audit of 784faf6, finding 3; the change reader refuses too)
            raise Refused(403, "the document has more than one name on disk (a hard link), so it is not served")
        if start is not None:
            if end > st.st_size:
                raise Refused(416, "the span runs past the end of the document as it is now, so it is not served")
            os.lseek(fd, start, os.SEEK_SET)
            want = end - start
        elif st.st_size > MAX_DOC:
            raise Refused(413, f"the document is over {_over()}, so it is not served")
        else:
            want = MAX_DOC + 1
        chunks, left = [], want
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
        data = b"".join(chunks)
        if start is not None and len(data) != want:
            raise Refused(416, "the document grew shorter while it was read, so the span is not served")
        if len(data) > MAX_DOC:
            raise Refused(413, f"the document is over {_over()}, so it is not served")
        return data
    finally:
        os.close(fd)


def serve(place: str, row_id: str, home=None) -> tuple[bytes, str]:
    """(bytes, content type) for one row of an enabled place, or Refused with the status and why."""
    if not (isinstance(place, str) and pagemodule.NAME.fullmatch(place)):
        raise Refused(404, "not found")
    if not (isinstance(row_id, str) and ROW.fullmatch(row_id)):
        raise Refused(400, "a row id is letters, digits, - and _ only, never a path")
    obj = _place(place, home)
    # one reading of the closures for this document: a resolve that takes two arguments is given it (as a source's
    # read is; the audit of 784faf6, note 10), and the path it names is judged against the same reading
    ctx = closed.context(home)
    owner = registry.key("place", place)   # every call below is this place's, counted under the name it was added by
    shape, why = registry.ctx_shape(obj.resolve, owner)
    if shape is None:   # not known now: never called without its ctx (the recheck of 17021c2, NH4); asked again next time
        raise Refused(503, registry.not_without_ctx("resolve", why))
    try:
        args = (row_id, ctx) if shape else (row_id,)
        path = outside.run(obj.resolve, *args, owner=owner, post=_plain_found, call="resolve")   # exact built-in types, in the worker
    except Exception as e:  # noqa: BLE001  a place that fails or is late here costs this document only
        raise Refused(404, f"the place could not find the row ({type(e).__name__})") from None
    path, start, end = _span(path)
    if path is None:
        raise Refused(404, "that row is not in the place's last read")
    if type(path) is not str or not os.path.isabs(path):
        raise Refused(404, "the place gave something other than a full path")
    if "\x00" in path:   # before, os.open raised ValueError and the request got no answer (the audit of 784faf6, 7)
        raise Refused(404, "the place gave a path no file can have (a NUL in it)")
    if not kernel.inside_named_root(path, ctx):   # the one judgement api.inside_roots gives plug-ins
        raise Refused(403, "the document is not inside a named root, or it is in a closed place")
    data = _read_once(closed._real(path) or path, start, end)
    try:
        trouble = outside.run(obj.check_bytes, data, owner=owner, post=_plain_trouble, call="check_bytes")   # PASSED or an exact str
    except Exception as e:  # noqa: BLE001  a check that fails or is late is a check that did not pass
        trouble = f"its check stopped ({type(e).__name__})"
    if trouble is not PASSED:   # fail closed: only the explicit pass passes, never None or anything else
        if type(trouble) is not str:
            trouble = "its check gave no answer"
        raise Refused(409, f"the document does not pass its place's check now: {trouble}")
    kind = getattr(obj, "doc_type", DEFAULT_TYPE)
    return data, kind if type(kind) is str and kind in TYPES else DEFAULT_TYPE
