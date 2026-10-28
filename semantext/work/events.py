"""Work events: the schema the kernel's one writer stamps and the fold reads (PM-DESIGN r2 to r5).

A request names its event and carries only that event's own fields. The fields that say who acted, when, with what
assurance, and every field that has a row of its own in the authority table (state, owner, priority, parked, proof)
are the kernel's: a request that carries one is refused, never quietly ignored (the attack on the design, A3 to A5 and
A8). Any other extra field is kept as claimed_<name> and never read (r2). Bodies get the door checks (doors spec
v0.6, rule 9): size, depth, NUL, bidirectional and control characters, lone surrogates, floats, secret shapes.
"""
from __future__ import annotations

import contextvars
import functools
import re

from ..store import RESERVED as DEVICE_NAMES, Refused

EVENTS = ("create", "edit", "comment", "link", "unlink", "assign_self", "move", "void", "propose_park", "propose_reassign",
          "person_act")
ASSURANCE = ("bound", "claimed", "observed", "fallback")   # how sure the kernel is of who acted (r4)
STATES = ("backlog", "next", "doing", "review", "done", "parked")
KINDS = ("epic", "story", "task", "bug", "research")
PERSON = "person"            # the person's own acts; a seat is never this name
VERSION = 1

# A project slug: lower-case ASCII, a letter first, no trailing hyphen, at most 64 characters (the attack, F10 and
# finding 9). An item id: W-<project>-<n>, n decimal with no leading zero and at most 6 digits (r5).
PROJECT_RE = re.compile(r"[a-z](?:[a-z0-9-]{0,62}[a-z0-9])?", re.ASCII)
ID_RE = re.compile(r"W-([a-z](?:[a-z0-9-]{0,62}[a-z0-9])?)-([1-9][0-9]{0,5})", re.ASCII)
SEAT_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]{0,39}", re.ASCII)

# Links are typed ids matched to known patterns, never paths (r2). A W- id in a card link, or a card id in an item
# link, is refused (r5).
LINK_TYPES = {
    "card": re.compile(r"[A-Z]-\d{8}-\d{1,6}", re.ASCII),           # an inbox card, A-20260101-120000
    "change": re.compile(r"C-\d{8}-\d{1,6}", re.ASCII),              # a change card
    "commit": re.compile(r"[0-9a-f]{7,40}", re.ASCII),
    "run": re.compile(r"[a-z0-9][a-z0-9._-]{0,63}#[1-9][0-9]{0,8}", re.ASCII),   # checker#line of its run records
    "post": re.compile(r"[A-Z][0-9]{1,5}", re.ASCII),                # a board post, P100
    "requirement": re.compile(r"R[1-9][0-9]{0,2}", re.ASCII),
    "assessment": re.compile(r"A-[A-Za-z0-9][A-Za-z0-9-]{0,63}", re.ASCII),
    "decision": re.compile(r"J-\d{8}-\d{1,4}", re.ASCII),            # a register entry
    "piece": re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", re.ASCII),
    "item": ID_RE,
}

COMMON = {"request_key"}
EDITABLE = {"title", "text", "kind"}   # an edit carries at least one of these
FIELDS = {
    "create": {"project", "title", "kind", "text", "epic", "clauses", "links"},
    "edit": {"id", "title", "text", "kind"},
    "comment": {"id", "text"},
    "link": {"id", "link"},
    "unlink": {"id", "link"},
    "assign_self": {"id"},
    "move": {"id", "from", "to", "reviewer"},
    "void": {"id", "reason", "survivor"},
    "propose_park": {"id", "text"},
    "propose_reassign": {"id", "to_seat", "text"},
    "person_act": {"id", "act", "from", "value", "clauses"},
}
REQUIRED = {"create": {"project", "title"}, "edit": {"id"}, "comment": {"id", "text"}, "link": {"id", "link"},
            "unlink": {"id", "link"}, "assign_self": {"id"}, "move": {"id", "from", "to"}, "void": {"id", "reason"},
            "propose_park": {"id"}, "propose_reassign": {"id", "to_seat"}, "person_act": {"id", "act"}}
# The kernel's own fields, and the fields with rows of their own: a request carrying one is refused.
KERNEL = {"v", "seq", "event", "who", "at", "assurance", "channel", "prev", "hash", "evidence", "source", "seat",
          "owner", "as", "by", "time", "session", "transcript", "turn", "n", "state", "priority", "parked", "proof",
          "id_minted"}
ALL_FIELDS = set().union(*FIELDS.values()) | COMMON
OWN = {e: frozenset(FIELDS[e] | COMMON) for e in FIELDS}

TITLE_MAX, TEXT_MAX, DEPTH_MAX = 200, 16384, 8
BIDI = {chr(c) for c in (0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069, 0x200E, 0x200F,
                         0x061C)}
_BIDI = "".join(sorted(BIDI))
BAD_IN_LINE = re.compile("[\x00-\x1f\x7f-\x9f" + _BIDI + "\ud800-\udfff]")
BAD_IN_TEXT = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f" + _BIDI + "\ud800-\udfff]")
# The secret-shape check is the writer's, before anything is kept. The fold reads what is already on disk, so it runs
# every other check and skips that one (it is the costliest); STRICT is per thread, so a fold never loosens a write.
STRICT: contextvars.ContextVar = contextvars.ContextVar("strict", default=True)


class WorkRefused(Refused):
    """A refusal with its code (the doors spec's codes, and the work table's own: BAD_EDGE, HELD, PARKED, TERMINAL,
    NOT_BOUND, RATE_LIMIT, STORE_FULL)."""

    def __init__(self, code: str, reason: str):
        super().__init__(f"{code}: {reason}")
        self.code, self.reason = code, reason


def valid_project(p) -> bool:
    return isinstance(p, str) and bool(PROJECT_RE.fullmatch(p)) and p not in DEVICE_NAMES


def parse_id(ident):
    """(project, n) for a well-formed item id, else None. Exact: W-p-07, W-P-7, a look-alike letter, a separator or a
    device name are not ids."""
    return _parse_id(ident) if isinstance(ident, str) and len(ident) <= 80 else None


@functools.lru_cache(maxsize=65536)      # a fold meets the same ids again and again
def _parse_id(ident: str):
    m = ID_RE.fullmatch(ident)
    if not m or m.group(1) in DEVICE_NAMES:
        return None
    return m.group(1), int(m.group(2))


def check_link(link) -> dict:
    if not isinstance(link, dict) or set(link) != {"type", "ref"}:
        raise WorkRefused("MALFORMED", "a link is {type, ref}, nothing else")
    t, ref = link["type"], link["ref"]
    if not isinstance(t, str) or t not in LINK_TYPES or not isinstance(ref, str):   # a list or object is no type
        raise WorkRefused("MALFORMED", f"a link's type is one of {', '.join(LINK_TYPES)}, and its ref is text")
    if t != "item" and ref.startswith("W-"):
        raise WorkRefused("MALFORMED", "a work item id is linked as type item, never as a card or another kind")
    if t == "item" and parse_id(ref) is None:
        raise WorkRefused("MALFORMED", f"{ref!r} is not an item id (W-<project>-<n>)")
    if not LINK_TYPES[t].fullmatch(ref):
        raise WorkRefused("MALFORMED", f"{ref!r} is not a {t} id; links are ids, never paths")
    return {"type": t, "ref": ref}


def check_text(value, what: str, limit: int, lines: bool, secrets: bool = True) -> str:
    """A person's or an agent's text, as the door checks it. `lines` allows newlines and tabs (text), else none."""
    if not isinstance(value, str):
        raise WorkRefused("MALFORMED", f"{what} must be text")
    if len(value) > limit:
        raise WorkRefused("MALFORMED", f"{what} is over {limit} characters")
    bad = (BAD_IN_TEXT if lines else BAD_IN_LINE).search(value)
    if bad:
        c = bad.group()
        kind = ("a NUL" if c == "\x00" else "a lone surrogate" if 0xD800 <= ord(c) <= 0xDFFF else
                "a bidirectional control" if c in BIDI else "a control character")
        raise WorkRefused("MALFORMED", f"{what} holds {kind}")
    if not (secrets and STRICT.get()):
        return value
    from ..inbox import SECRET, token_like   # here: inbox imports the store, which this package imports
    if SECRET.search(value) or token_like(value):
        raise WorkRefused("MALFORMED", f"{what} looks like it holds a key, a token or a password; it is not kept")
    return value


def check_plain(value, depth: int = 0, secrets: bool = False) -> None:
    """A structured field (a clause, a link): JSON with integers only, no deeper than DEPTH_MAX. `secrets` adds the
    secret-shape scan to every text in it, for a field whose words are the caller's own (a claimed extra, a value)."""
    if depth > DEPTH_MAX:
        raise WorkRefused("MALFORMED", f"nested deeper than {DEPTH_MAX} levels")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise WorkRefused("MALFORMED", "a key that is not text")
            check_text(k, "a key", 64, False, secrets=secrets)
            check_plain(v, depth + 1, secrets)
    elif isinstance(value, list):
        for v in value:
            check_plain(v, depth + 1, secrets)
    elif isinstance(value, float):
        raise WorkRefused("MALFORMED", "a float (integers only)")
    elif isinstance(value, str):
        check_text(value, "a value", 512, False, secrets=secrets)
    elif not (value is None or isinstance(value, (bool, int))):
        raise WorkRefused("MALFORMED", "a value that is not JSON")
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 10 ** 15:
        raise WorkRefused("MALFORMED", "an integer too large")


def request(event: str, req) -> tuple[dict, dict]:
    """The request's own fields, checked, and its extras as {claimed_<name>: value}. Refuses an unknown event, a
    missing field, any of the kernel's fields, and a field that belongs to another event's row."""
    if event not in EVENTS:
        raise WorkRefused("MALFORMED", f"no such event {event!r}")
    if not isinstance(req, dict):
        raise WorkRefused("MALFORMED", "a request is a record of fields")
    own, keys, claimed = OWN[event], req.keys(), {}
    if keys & KERNEL or (event == "create" and "id" in keys):
        k = next(k for k in req if k in KERNEL or (event == "create" and k == "id"))
        raise WorkRefused("NOT_AUTHORIZED", f"{k!r} is the kernel's to set (or has its own act), never the "
                                            f"caller's; send the request without it")
    if keys - own:          # the rare case: a field of another event's row, or an extra
        for k, v in req.items():
            if k in own:
                continue
            if not isinstance(k, str):
                raise WorkRefused("MALFORMED", "a field name that is not text")
            if k in ALL_FIELDS:
                raise WorkRefused("NOT_AUTHORIZED", f"{event} cannot carry {k!r}: it has its own act and its own row")
            if re.fullmatch(r"[a-z][a-z0-9_]{0,31}", k, re.ASCII) and not k.startswith("claimed_"):
                check_plain(v, secrets=True)   # kept in the append-only log, so scanned before it is kept
                claimed["claimed_" + k] = v
            else:
                raise WorkRefused("MALFORMED", f"{k!r} is not a field name")
        fields = {k: v for k, v in req.items() if k in own}
    else:
        fields = dict(req)
    missing = REQUIRED[event] - keys
    if missing:
        raise WorkRefused("MALFORMED", f"{event} needs {', '.join(sorted(missing))}")
    return _checked(event, fields), claimed


STAMPS = {"v", "seq", "event", "who", "at", "assurance", "channel", "prev", "hash"}
STAMPED_FOR = {"create": {"id", "source"}, "person_act": {"evidence"}}   # what the writer adds to these events


def from_record(rec: dict) -> tuple[str, dict]:
    """A stored record read back as (event, its own fields), by the same checks a request gets, so a line written into
    the file by hand is judged as the writer would have judged it. Refuses a record that carries a field no writer
    stamps (a forged `state`, `owner` or `parked`)."""
    event = rec.get("event")
    if event not in EVENTS:
        raise WorkRefused("MALFORMED", f"no such event {event!r}")
    stamped = STAMPS | STAMPED_FOR.get(event, set())
    own = {k: v for k, v in rec.items() if k not in stamped and not k.startswith("claimed_")}
    token = STRICT.set(False)
    try:
        fields, extra = request(event, own)
    finally:
        STRICT.reset(token)
    if extra:
        raise WorkRefused("MALFORMED", f"carries fields no writer stamps: {', '.join(sorted(extra))}")
    return event, fields


def _checked(event: str, f: dict) -> dict:
    if "request_key" in f and not (isinstance(f["request_key"], str)
                                   and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", f["request_key"], re.ASCII)):
        raise WorkRefused("MALFORMED", "a request_key is 1 to 128 letters, digits and . _ : -")
    if "id" in f and parse_id(f["id"]) is None:
        raise WorkRefused("UNKNOWN_ID", f"{f['id']!r} is not an item id (W-<project>-<n>, lower case, no leading "
                                        f"zero)")
    if "project" in f and not valid_project(f["project"]):
        raise WorkRefused("MALFORMED", f"{f['project']!r} is not a project slug")
    if "title" in f:
        check_text(f["title"], "the title", TITLE_MAX, False)
        if not f["title"].strip():
            raise WorkRefused("MALFORMED", "the title is empty")
    for k in ("text", "reason"):
        if k in f:   # a Windows line end is a newline, kept as one (round 4, low); a lone carriage return is refused
            f[k] = check_text(f[k].replace("\r\n", "\n") if isinstance(f[k], str) else f[k], k, TEXT_MAX, True)
    if "kind" in f and f["kind"] not in KINDS:
        raise WorkRefused("MALFORMED", f"a kind is one of {', '.join(KINDS)}")
    for k in ("from", "to"):
        if k in f and f[k] not in STATES:
            raise WorkRefused("MALFORMED", f"{k!r} is one of {', '.join(STATES)}")
    for k in ("reviewer", "to_seat"):
        if k in f and (not isinstance(f[k], str) or not SEAT_RE.fullmatch(f[k]) or f[k] == PERSON):
            raise WorkRefused("MALFORMED", f"{k!r} names a seat")
    for k in ("epic", "survivor"):
        if k in f and parse_id(f[k]) is None:
            raise WorkRefused("MALFORMED", f"{k!r} is an item id")
    if "link" in f:
        f["link"] = check_link(f["link"])
    if "links" in f:
        if not isinstance(f["links"], list) or len(f["links"]) > 64:
            raise WorkRefused("MALFORMED", "links is a list of at most 64 links")
        f["links"] = [check_link(x) for x in f["links"]]
    if "clauses" in f:
        from .clauses import check_clauses
        f["clauses"] = check_clauses(f["clauses"])
    if "value" in f:
        check_plain(f["value"], secrets=True)
    if event == "edit" and not f.keys() & EDITABLE:
        raise WorkRefused("MALFORMED", f"an edit changes at least one of {', '.join(sorted(EDITABLE))}; nothing "
                                       f"else is an edit")
    return f
