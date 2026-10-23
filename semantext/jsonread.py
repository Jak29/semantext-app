"""One way to read JSON, so a text nested too deeply gets the same answer on every machine.

How deep json's parser can go is the interpreter's stack, not JSON: 30,000 levels overflow it on Windows (a
RecursionError, which several readers did not catch) and parse under 3.14 on Linux and macOS (a value several readers
then took for something else). Here a text that nests deeper than MAX_DEPTH is refused before it is parsed, on its
text alone, and an overflow that still happens is refused the same way. Both, and every text json itself refuses,
raise NotJSON: a json.JSONDecodeError and so a ValueError, so a reader that already catches either keeps working, with
json's own words for a text that is not JSON. An error raised by the caller's own parse_* hook passes through as is.
"""
from __future__ import annotations

import json
import re

MAX_DEPTH = 256   # far below any parser's limit, and far above anything Semantext reads or is sent
# A string, or a bracket. A string with no closing quote runs to the end of the text (a lone backslash at the very end
# included): when it had to close, the search failed and began again at every later quote, so 64 KB of \" after one
# opening quote took 16 s and 256 KB over four minutes. An unclosed string is never valid JSON, so no valid text moves.
BRACKETS = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*(?:"|\\?\Z)|[\[\]{}]', re.S)


class NotJSON(json.JSONDecodeError):
    """The text is not JSON, or is nested too deeply to be read: `deep` says which."""

    def __init__(self, msg: str, doc: str, pos: int, deep: bool = False):
        super().__init__(msg, doc, pos)
        self.deep = deep
        if deep:
            self.args = (msg,)   # said plainly: a line and column would point at no fault


def depth(text: str) -> int:
    """How deeply arrays and objects are nested in this text, counted on the text and not on a parse of it. Brackets
    inside a string do not count. Never more than the number of brackets opened."""
    opened = text.count("[") + text.count("{")
    if opened <= MAX_DEPTH:
        return opened   # an upper bound, and enough: it cannot be deeper than that
    level = deepest = 0
    for m in BRACKETS.finditer(text):
        if m.group() in ("[", "{"):
            level += 1
            deepest = max(deepest, level)
        elif m.group() in ("]", "}"):
            level -= 1
    return deepest


def loads(text: str | bytes | bytearray, **kw):
    """json.loads, refusing with NotJSON a text nested deeper than MAX_DEPTH (never handed to the parser), one the
    parser overflows on, and one json calls bad. Bytes are decoded as json.loads decodes them."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode(json.detect_encoding(text), "surrogatepass")
    if depth(text) > MAX_DEPTH:
        raise NotJSON(f"it is nested more than {MAX_DEPTH} levels deep, so it is not read", text, 0, deep=True)
    try:
        return json.loads(text, **kw)
    except RecursionError:
        raise NotJSON(f"it is nested more than {MAX_DEPTH} levels deep, so it is not read", text, 0, deep=True) from None
    except NotJSON:
        raise
    except json.JSONDecodeError as e:
        raise NotJSON(e.msg, e.doc, e.pos) from None
