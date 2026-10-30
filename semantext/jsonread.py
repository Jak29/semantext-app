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
import math
import re

INBOX_DEPTH = 127   # the deepest nesting the person's inbox reads (inbox_loads)
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


class _Twice(Exception):
    """A key given twice in one object: raised inside the parse, said as NotJSON by loads."""


def _once(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise _Twice(k)
        out[k] = v
    return out


def loads(text: str | bytes | bytearray, unique: bool = False, **kw):
    """json.loads, refusing with NotJSON a text nested deeper than MAX_DEPTH (never handed to the parser), one the
    parser overflows on, and one json calls bad. Bytes are decoded as json.loads decodes them. With `unique`, a text in
    which any object gives one key twice is refused too: JSON keeps the last of the two in silence, so a first value
    the person wrote would be replaced unseen (the audit of 784faf6, protection item 9). It is for the files the
    person keeps settings in, and cannot be given with an object_pairs_hook of the caller's."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode(json.detect_encoding(text), "surrogatepass")
    if depth(text) > MAX_DEPTH:
        raise NotJSON(f"it is nested more than {MAX_DEPTH} levels deep, so it is not read", text, 0, deep=True)
    if unique:
        if "object_pairs_hook" in kw or "object_hook" in kw:
            raise TypeError("unique cannot be given with a hook of the caller's")
        kw["object_pairs_hook"] = _once
    try:
        return json.loads(text, **kw)
    except _Twice as e:
        raise NotJSON(f"the key {str(e.args[0])[:80]!r} is given twice in one object, so it is not read", text, 0) from None
    except RecursionError:
        raise NotJSON(f"it is nested more than {MAX_DEPTH} levels deep, so it is not read", text, 0, deep=True) from None
    except NotJSON:
        raise
    except json.JSONDecodeError as e:
        raise NotJSON(e.msg, e.doc, e.pos) from None


# ---- the inbox's reading: strict, as the person's own inbox parses a request, a parking and the seats file ----
# The inbox's parser reads a number by gathering its digits into a 64-bit whole number until one more would not fit,
# counting the rest as a power of ten, and then scales a float by that power: a number whose float would be infinite is
# refused as out of range. Python's parser would take any whole number, so the same steps are taken here.
_NUMBER = re.compile(r"-?(0|[1-9][0-9]*)(?:\.([0-9]+))?(?:[eE]([+-]?)([0-9]+))?\Z")
_U64, _I32 = 2 ** 64 - 1, 2 ** 31 - 1
_POW10 = [float(f"1e{k}") for k in range(309)]   # 1e0 to 1e308, the powers the inbox's parser has


def _scaled_ok(significand: int, exponent: int) -> bool:
    """Whether significand x 10**exponent is a float the parser accepts (not infinite)."""
    f = float(significand)
    while True:
        if exponent != -2 ** 31 and abs(exponent) < len(_POW10):
            return exponent < 0 or not math.isinf(f * _POW10[exponent])
        if f == 0.0:
            return True
        if exponent >= 0:
            return False
        f /= 1e308
        exponent += 308


def _in_range(token: str) -> bool:
    """Whether the inbox's parser takes this JSON number token. False: it is out of range."""
    whole, fraction, sign, digits = _NUMBER.match(token).groups()
    significand, exponent = 0, 0
    if whole != "0":
        significand = int(whole[0])
        for at in range(1, len(whole)):
            if significand * 10 + int(whole[at]) > _U64:
                exponent = len(whole) - at   # this digit and the ones after it only count as a power of ten
                break
            significand = significand * 10 + int(whole[at])
    if fraction is not None:
        for digit in fraction:
            if significand * 10 + int(digit) > _U64:
                break   # the rest of the digits are ignored
            significand = significand * 10 + int(digit)
            exponent -= 1
    if digits is not None:
        power = 0
        for digit in digits:
            if power * 10 + int(digit) > _I32:
                return significand == 0 or sign == "-"   # an exponent too big for 32 bits: zero, or out of range
            power = power * 10 + int(digit)
        exponent = max(-2 ** 31, min(_I32, exponent + (-power if sign == "-" else power)))
    elif fraction is None and exponent == 0:
        return True   # a whole number that fitted in 64 bits is never made a float
    return _scaled_ok(significand, exponent)


def _int_token(token: str):
    if not _in_range(token):
        raise ValueError("a number is too large")
    return -0.0 if token == "-0" else int(token)   # the inbox's parser reads -0 as a float


def _float_token(token: str):
    if not _in_range(token):
        raise ValueError("a number is too large")
    return float(token)


def _nesting(text: str) -> int:
    """How deeply arrays and objects are nested in this JSON text, counted on the text itself and not on what was parsed
    from it: the inbox's parser counts a deep value that a later member of the same name would have replaced."""
    opened = text.count("[") + text.count("{")
    if opened <= INBOX_DEPTH:
        return opened   # an upper bound, and enough: it cannot be deeper than the number of brackets opened
    depth = deepest = 0
    for m in BRACKETS.finditer(text):
        if m.group() in ("[", "{"):
            depth += 1
            deepest = max(deepest, depth)
        elif m.group() in ("]", "}"):
            depth -= 1
    return deepest


_WS = re.compile(r"[ \t\n\r]*")
_STRING = re.compile(r'"[^"\\\x00-\x1f]*(?:\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})[^"\\\x00-\x1f]*)*"')
_SURROGATE = re.compile(r"\\u[dD][89a-fA-F][0-9a-fA-F]{2}")


def _half_pair(text: str) -> bool:
    """Whether any string in this JSON text, a name or a value, has half of a surrogate pair written as an escape: a
    high half not straight away followed by a low half, or a low half on its own. It looks at the text, not at what was
    parsed, because the inbox's parser refuses it in a value that a later member of the same name would have replaced."""
    if not _SURROGATE.search(text):
        return False
    for token in _STRING.finditer(text):
        s, i = token.group(), 0
        while (i := s.find("\\", i)) >= 0:
            if s[i + 1] != "u":
                i += 2
                continue
            code = int(s[i + 2:i + 6], 16)
            if 0xD800 <= code <= 0xDBFF:
                if s[i + 6:i + 8] != "\\u" or not 0xDC00 <= int(s[i + 8:i + 12], 16) <= 0xDFFF:
                    return True
                i += 12
            elif 0xDC00 <= code <= 0xDFFF:
                return True
            else:
                i += 6
    return False


def inbox_loads(text: str, unique: bool = False):
    """A line as JSON, the way the inbox's parser reads it into a value: NaN, Infinity and a number the parser calls out
    of range are not JSON, half of a surrogate pair is not text, and a line nested deeper than INBOX_DEPTH is not
    read. Every reader of the seats file, and the card hook, reads it this way, with `unique` (pathrule.seats)."""
    def refuse(name):
        raise ValueError(f"{name} is not JSON")
    try:
        value = loads(text, unique=unique, parse_constant=refuse, parse_int=_int_token,
                               parse_float=_float_token)
    except NotJSON as e:
        if e.deep:
            raise ValueError("it is nested too deeply") from None
        raise
    if _half_pair(text):
        raise ValueError("it holds half of a surrogate pair")
    if _nesting(text) > INBOX_DEPTH:
        raise ValueError("it is nested too deeply")
    return value
