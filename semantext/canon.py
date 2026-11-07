"""One strict reading of a tool call's input, and the digest an approval binds to (ARCHITECTURE.md v1.3, G3 and H1).

The proxy reads a request body, a streamed `partial_json` and its own stash with this one parser, so what it judged,
what it forwards and what it releases are the same value. The parser refuses, rather than reads in silence:

  - a key given twice in one object (JSON keeps the last);
  - NaN, Infinity and -Infinity (not JSON, though Python's json reads them);
  - half of a surrogate pair written as an escape (not text);
  - nesting deeper than jsonread.MAX_DEPTH;
  - anything json itself refuses (a trailing comma, a comment, single quotes).

Every number keeps its own text (Number): 9007199254740993 and 9007199254740992 stay two numbers, where a double would
make them one, and 1.0 stays 1.0.

The canonical form is RFC 8785's shape with that one change: keys sorted by their UTF-16 code units, no whitespace,
strings escaped as JSON requires and no more, numbers as written. D_act is SHA-256 of its UTF-8 bytes; an input that
is a free-form string (a custom tool's text) is not parsed at all, and D_act is SHA-256 of its exact bytes (D10).
D_rec, the only digest the record keeps, is HMAC-SHA-256 of D_act under the node's key (H1).
"""
from __future__ import annotations

import hashlib
import hmac
import json

from . import jsonread


class Number(str):
    """A JSON number, kept as the text it was written as."""


class NotCanonical(ValueError):
    """The text is not one strict JSON value; the message says why."""


def _constant(name):
    raise NotCanonical(f"{name} is not JSON")


def loads(text: str | bytes):
    """One strict JSON value, numbers kept as Number. Raises NotCanonical with the reason."""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeDecodeError:
            raise NotCanonical("not UTF-8") from None
    try:
        value = jsonread.loads(text, unique=True, parse_int=Number, parse_float=Number, parse_constant=_constant)
    except NotCanonical:
        raise
    except jsonread.NotJSON as e:
        raise NotCanonical(str(e.args[0]) if e.args else "not JSON") from None
    if jsonread._half_pair(text):
        raise NotCanonical("it holds half of a surrogate pair")
    return value


def _key(k: str):
    return k.encode("utf-16-be")


def dumps(value) -> str:
    """The canonical text of a value read by loads (or built from str, Number, bool, None, list and dict)."""
    if isinstance(value, Number):
        return str(value)
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, (int, float)):
        raise NotCanonical("a number that was not read as text: canonical form keeps each number as written")
    if isinstance(value, list):
        return "[" + ",".join(dumps(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + dumps(value[k])
                              for k in sorted(value, key=_key)) + "}"
    raise NotCanonical(f"a {type(value).__name__} has no canonical form")


def d_act(value) -> str:
    """SHA-256 of the canonical input. A str that is not a Number is a free-form input: its exact bytes (D10). The two
    are hashed under different prefixes, so a free-form text that happens to spell a JSON input's canonical form is
    never the same act (found by test_a_free_form_input_is_its_exact_bytes)."""
    if isinstance(value, str) and not isinstance(value, Number):
        data = b"text\0" + value.encode("utf-8", "surrogatepass")
    else:
        data = b"json\0" + dumps(value).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def d_rec(node_key: bytes, act_digest: str) -> str:
    """The only digest of an input the record keeps: keyed, so a short input cannot be guessed back from it (H1)."""
    if not node_key:
        raise NotCanonical("no node key: nothing is recorded or passed without one")
    return hmac.new(node_key, act_digest.encode("ascii"), hashlib.sha256).hexdigest()
