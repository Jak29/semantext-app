"""The work store's hash chain: each line names the hash of the line before it and carries its own (PM-DESIGN r2, r4;
doors spec v0.6, rule 3).

A line is a record in the writer's canonical form: the record without its "hash" as JSON with sorted keys, no spaces,
UTF-8, then "hash" as its last key, and nothing else. "hash" is the SHA-256 of that canonical record without it (so one
serialisation both checks the form and gives the hash); "prev" is the hash of the record before it on the chain (64
zeros for the first); "seq" is its place on the chain, from 1. The writer keeps the head, {"seq", "hash"} of the last
record it wrote, in events.head.json beside the log, under the same lock.

Reading: the chain is followed back from the head by hash, and a record is ON the chain when it is the head's ancestry
(seq counting down to 1, prev naming the record before, each hash its own, in file order). Everything else is reported,
never hidden:
  - a line that is not a record in the writer's form (a torn write, duplicate keys, NaN, a BOM, a NUL, over 64 KB,
    nested too deep, an unknown version) is a problem and is not folded (the attack, F3 and F4);
  - a record not in that ancestry (after the head, beside the writer's own line, a copy, or changed after it was
    written) is OFF the chain: reported, and folded only as "claimed", so it can carry no authority (the attack,
    finding 1 and A11). A writer that died after its line and before moving the head leaves such a line too; a retry
    with its request_key writes it again;
  - a head whose ancestry is not whole (a record removed, edited or out of order) is a broken store: every record is
    off the chain, and the writer writes nothing more until it is looked at.
A carriage return before the newline is read as if absent (the attack, F5: the same state with CRLF). The limit, as the
doors spec states it: a program that can write both the log and its head can forge a chain; this detects an edit, a
deletion, a reorder or an insertion by anything that does not rewrite the head too.
"""
from __future__ import annotations

import hashlib
import json
import re

from .. import jsonread
from ..sources import MAX_LINE
from .events import VERSION

GENESIS = "0" * 64


# One encoder and one decoder, made once: json.dumps and json.loads build a new one on every call that passes options,
# and that was a fifth of a fold's time.
_ENCODE = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode
_DECODE = json.JSONDecoder(parse_constant=lambda name: _refuse_constant(name)).decode
HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)


def canonical(rec: dict) -> str:
    return _ENCODE(rec)


def digest(rec: dict) -> str:
    return hashlib.sha256(_ENCODE({k: v for k, v in rec.items() if k != "hash"}).encode("utf-8")).hexdigest()


def line_of(rec: dict) -> str:
    """A sealed record as the line the writer writes: its body in canonical form, then its hash, last."""
    body = _ENCODE({k: v for k, v in rec.items() if k != "hash"})
    return body[:-1] + ',"hash":"' + rec["hash"] + '"}'


def seal(rec: dict, seq: int, prev: str) -> dict:
    """The record with its place on the chain and its own hash."""
    rec = {**rec, "seq": seq, "prev": prev}
    rec["hash"] = digest(rec)
    return rec


def _refuse_constant(name):
    raise ValueError(f"{name} is not a JSON number")



def _duplicates(text: str) -> bool:
    found = []

    def hook(pairs):
        keys = [k for k, _ in pairs]
        if len(keys) != len(set(keys)):
            found.append(True)
        return dict(pairs)
    try:
        json.loads(text, object_pairs_hook=hook)
    except (ValueError, RecursionError):
        return False
    return bool(found)


def parse_line(text: str):
    """(record, None, its hash is its own) for a line in the writer's form, or (None, why not, False). One
    serialisation: the canonical body both checks the line's form and is what its hash is of."""
    if text.endswith("\r"):
        text = text[:-1]
    rec, why = _parse(text)
    if rec is None:
        return None, why, False
    h = rec.pop("hash", None)
    try:
        body = _ENCODE(rec)
    except ValueError:
        return None, "not JSON", False
    if not (isinstance(h, str) and HEX64.fullmatch(h)) or body[:-1] + ',"hash":"' + h + '"}' != text:
        return None, ("duplicate keys" if _duplicates(text) else "not in the writer's form (spacing, key order or "
                                                                  "hash)"), False
    try:
        own = hashlib.sha256(body.encode("utf-8")).hexdigest() == h
    except UnicodeEncodeError:   # a lone surrogate (round 4, low): no writer writes one, so the line is not ours
        return None, "a lone surrogate", False
    rec["hash"] = h
    return rec, None, own


def _parse(text: str):
    if not text.strip():
        return None, "a blank line"
    if len(text) > MAX_LINE // 4 and len(text.encode("utf-8", "surrogatepass")) > MAX_LINE:
        return None, f"a line over {MAX_LINE // 1024} KB, not parsed"
    if text.startswith("\ufeff"):
        return None, "a byte-order mark"
    if "\x00" in text:
        return None, "a NUL"
    if text.count("[") + text.count("{") > jsonread.MAX_DEPTH and jsonread.depth(text) > jsonread.MAX_DEPTH:
        return None, f"not JSON (nested more than {jsonread.MAX_DEPTH} levels)"
    try:
        # An integer too large to be one of ours is not refused here: a line holding one is either not in the
        # writer's form, or carries it in a field whose own check refuses it (check_plain), and json itself refuses
        # one over 4,300 digits. A scan for long digit runs cost a fifth of the fold.
        rec = _DECODE(text)
    except (ValueError, RecursionError) as e:
        return None, f"not JSON ({str(e)[:120]})"
    if not isinstance(rec, dict):
        return None, "not a record"
    if type(rec.get("v")) is not int or rec["v"] != VERSION:   # true and 1.0 equal 1, and are not our version
        return None, f"an unknown version {rec.get('v')!r}"
    return rec, None

def read_head(text):
    """The head as {"seq", "hash"}, or None when it is missing or not one."""
    if text is None:
        return None
    try:
        h = jsonread.loads(text)
    except ValueError:
        return None
    if isinstance(h, dict) and isinstance(h.get("seq"), int) and not isinstance(h.get("seq"), bool) and \
            h["seq"] >= 0 and isinstance(h.get("hash"), str):
        return {"seq": h["seq"], "hash": h["hash"]}
    return None


def walk(lines, torn, head) -> dict:
    """The log's lines (and a torn fragment, if any) read against the head: {"records": [(line no., record,
    on_chain)], "problems": [...], "end": the head the next record chains to, "intact": the chain from the head back
    to the first record is whole and in file order}. `head` None with records present means the head is missing:
    nothing is on the chain.

    The chain is followed BACKWARDS from the head, by hash: the records on it are exactly the head's ancestry. So a
    record planted beside the writer's own (the same seq and prev, appended by something else) is never on it, however
    the head moves later, and a copy of a line is a copy, not a second record."""
    problems, parsed, by_hash = _parse_all(lines, 0)
    if torn is not None:
        problems.append({"line": len(lines) + 1, "kind": "torn", "text": "a torn last line (no newline), dropped"})
    # no head: intact only for an empty store; anything at all in the log (a record, a line that is not one, a torn
    # fragment) is a store whose head is missing, never a fresh chain to start beneath it (round 4, low)
    empty = not parsed and not lines and torn is None
    on, why = _ancestry(head, by_hash) if head else ((set(), None) if empty else (set(), "no head"))
    intact = why is None
    if not intact:
        problems.append({"line": None, "kind": "broken", "text": "no head beside the log, so no record is trusted"
                         if why == "no head" else f"the chain from the head is broken ({why}): the store was cut, "
                                                  f"edited or reordered; no record is trusted"})
        on = set()
    limit = head["seq"] if head else 0
    out = []
    for n, rec, own in parsed:
        ok = n in on
        if not ok and intact:
            problems.append({"line": n, "kind": "off-chain", "text": _why_off(rec, own, limit)})
        out.append((n, rec, ok))
    end = dict(head) if head else {"seq": 0, "hash": GENESIS}
    return {"records": out, "problems": problems, "end": end, "intact": intact}


def _parse_all(lines, start):
    problems, parsed, by_hash = [], [], {}
    for n, text in enumerate(lines, start + 1):
        rec, why, own = parse_line(text)
        if rec is None:
            problems.append({"line": n, "kind": "malformed", "text": why})
            continue
        parsed.append((n, rec, own))
        if own:
            by_hash.setdefault(rec["hash"], (n, rec))
    return problems, parsed, by_hash


def extend(lines, start: int, base: dict, head) -> dict | None:
    """The lines after a prefix already verified up to `base` (its head then), numbered from start + 1, read against
    the head now: {"records", "problems"} as walk() gives them, or None when the head's ancestry does not come back to
    `base` through these lines alone (the head moved back, or the chain runs through an older line), so the caller
    verifies the whole store again. A torn fragment is the caller's to report."""
    if not head or head["seq"] < base["seq"]:
        return None
    problems, parsed, by_hash = _parse_all(lines, start)
    on, h, seq, last_line = set(), head["hash"], head["seq"], None
    while seq > base["seq"]:
        got = by_hash.get(h) if isinstance(h, str) else None
        if got is None or got[1].get("seq") != seq or (last_line is not None and got[0] >= last_line):
            return None
        on.add(got[0])
        h, seq, last_line = got[1].get("prev"), seq - 1, got[0]
    if h != base["hash"]:
        return None
    out = []
    for n, rec, own in parsed:
        if n not in on:
            problems.append({"line": n, "kind": "off-chain", "text": _why_off(rec, own, head["seq"])})
        out.append((n, rec, n in on))
    return {"records": out, "problems": problems}


def _ancestry(head, by_hash):
    """The line numbers of the head's ancestry, or why it is not whole."""
    on, h, seq, last_line = set(), head["hash"], head["seq"], None
    while seq > 0:
        got = by_hash.get(h) if isinstance(h, str) else None   # a prev that is not text names no record
        if got is None or got[1].get("seq") != seq:
            return set(), f"no record {seq} with the hash the chain names"
        n, rec = got
        if last_line is not None and n >= last_line:
            return set(), f"record {seq} comes after record {seq + 1} in the file"
        on.add(n)
        h, seq, last_line = rec.get("prev"), seq - 1, n
    if h != GENESIS:
        return set(), "the first record does not start the chain"
    return on, None


def _why_off(rec, own, limit=None) -> str:
    """Why a record is off the chain, in words that do not depend on where the head is now, so a fold in parts and a
    fold from scratch say the same."""
    if not own:
        return "its hash is not its own: it was changed after it was written"
    return ("not on the chain from the head: appended by something other than the kernel's writer (or by a writer "
            "that died before moving the head), beside the writer's own line, or a copy")