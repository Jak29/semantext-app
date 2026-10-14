"""The Waiting place: what your agents have asked of you, read the way your own inbox reads it.

An agent that needs your word files a request: one JSON object a line, appended to to_jak.jsonl in the agent's own home
folder. A request is a decision (a question and its options) or a command (what to run, what it does, how to undo it).
A line with a "close" field closes the request it names. A command you ran is noted in runs.jsonl and a card you parked
in parked.jsonl, both in the shared inbox folder.

This reader folds those files into cards, each waiting, parked, closed or run, and only ever opens files for reading.
It takes every file as your own inbox does, so that what it shows is what the inbox shows: a request file that is not
all UTF-8 is not read at all, a number too large for a float is not JSON, a line of runs.jsonl that is not a whole run
record is not a run, and a line of parked.jsonl is parsed as it stands. Every line it cannot use is a problem in the
result, never silence: a line that is not JSON, a field that is missing, an id used twice (the first stands), a closing
that names no request, a parking it does not know. A card that is still shown but has something wrong in it (no "does",
a hidden character in its command) carries a problem too, marked "shown". Which agent a card is from comes from the home
folder in the seats file, never from a field in the line. A card that has run is never waiting, whether or not anyone
has closed it.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

from . import MAX_LINE, problem

FILE = "to_jak.jsonl"
FILE_CAP = 5 * 1024 * 1024   # the inbox leaves a bigger file unread until it is trimmed
MAX_DEPTH = 127              # the deepest nesting of arrays and objects the inbox reads in a request or a parking
STATES = ("waiting", "parked", "closed", "run")
KINDS = ("decision", "command")
REQUIRED = {"decision": ("id", "at", "title", "why", "question"), "command": ("id", "at", "title", "why", "command")}
ASKS = "the agent whose home folder holds the line, from the seats file; a field in the line is never read"
ACTS = ("by a rule in the decision register, a card whose act another agent performs is filed by that agent, so the "
        "agent whose home holds the line is the one that acts; the line itself does not say who acts")
BOM = chr(0xFEFF)
# What the inbox trims from a line and from a text field: Unicode white space. str.strip() trims four more characters
# (U+001C to U+001F), and a line of only those is not blank to the inbox: it is not JSON.
SPACE = "".join(map(chr, (*range(0x09, 0x0E), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B),
                          0x2028, 0x2029, 0x202F, 0x205F, 0x3000)))
# Characters that can make a command's text differ from what runs: direction marks and overrides, zero-width and
# soft-hyphen characters, a byte-order mark inside the text. The inbox will not run such a command; this reader shows
# it with a note. Control characters other than tab and line breaks count too (see _hidden).
HIDDEN = {*range(0x200B, 0x2010), *range(0x202A, 0x202F), *range(0x2060, 0x2065), *range(0x2066, 0x206A),
          0xFEFF, 0xAD, 0x61C, 0x180E}


class _Refused(Exception):
    """A line that cannot be used, and which kind of problem it is."""

    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind, self.text = kind, text


def _text(v: dict, key: str) -> str | None:
    """A text field as the inbox reads it: a string, trimmed, and not empty. Anything else counts as missing."""
    x = v.get(key)
    return (x.strip(SPACE) or None) if isinstance(x, str) else None


def _hidden(*texts: str | None) -> str | None:
    """The first character in these texts that could make the text shown differ from the text that runs, as "U+202E", or
    None."""
    for text in texts:
        for ch in text or "":
            if ord(ch) in HIDDEN or (unicodedata.category(ch) == "Cc" and ch not in "\t\n\r"):
                return f"U+{ord(ch):04X}"
    return None


# ---------------------------------------------------------------------------------------------------- lines
def _lines(text: str) -> list[tuple[int, str]]:
    """(number, line) for every line of a file's text, blank ones too, split as the inbox splits: at a line feed, with
    one carriage return before it going with it. A carriage return on its own is part of the line."""
    parts = text.split("\n")
    last = parts.pop()   # what follows the final line feed: the last line when it has no line feed, else nothing
    lines = [p[:-1] if p.endswith("\r") else p for p in parts]
    if last:
        lines.append(last)
    return list(enumerate(lines, 1))


def _blank(line: str) -> bool:
    return not line.strip(SPACE)


# ---------------------------------------------------------------------------------------------------- JSON
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


_BRACKETS = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"|[\[\]{}]')


def _nesting(text: str) -> int:
    """How deeply arrays and objects are nested in this JSON text, counted on the text itself and not on what was parsed
    from it: the inbox's parser counts a deep value that a later member of the same name would have replaced."""
    opened = text.count("[") + text.count("{")
    if opened <= MAX_DEPTH:
        return opened   # an upper bound, and enough: it cannot be deeper than the number of brackets opened
    depth = deepest = 0
    for m in _BRACKETS.finditer(text):
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


def _parse(text: str):
    """A line as JSON, the way the inbox's parser reads it into a value: NaN, Infinity and a number the parser calls out
    of range are not JSON, half of a surrogate pair is not text, and a line nested deeper than MAX_DEPTH is not read."""
    def refuse(name):
        raise ValueError(f"{name} is not JSON")
    try:
        value = json.loads(text, parse_constant=refuse, parse_int=_int_token, parse_float=_float_token)
    except RecursionError:
        raise ValueError("it is nested too deeply") from None
    if _half_pair(text):
        raise ValueError("it holds half of a surrogate pair")
    if _nesting(text) > MAX_DEPTH:
        raise ValueError("it is nested too deeply")
    return value


# ---------------------------------------------------------------------------------------------------- seats
def _seats(path: str, problems: list, group: str | None = None) -> list[dict]:
    """The agents in the seats file, each with the folder its requests are in. With a group, only the agents in that
    group, as the inbox reads only its own group's: the others are left out and not mentioned. A home that is empty, that
    holds a NUL character, or that steps outside the base folder is a problem and is not followed."""
    where = Path(path)
    try:
        data = _parse(where.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        problems.append(problem(where, None, "seats file", f"cannot be read ({e})"))
        return []
    base = data.get("base") if isinstance(data, dict) else None
    table = data.get("seats") if isinstance(data, dict) else None
    if not (isinstance(base, str) and base.strip() and isinstance(table, dict)):
        problems.append(problem(where, None, "seats file", "it needs a base folder and a table of seats"))
        return []
    if not Path(base).is_dir():
        problems.append(problem(where, None, "seats file", f"the base folder {base} does not exist"))
        return []
    out = []
    for name in sorted(table):
        entry = table[name] if isinstance(table[name], dict) else {}
        groups, home = entry.get("groups"), entry.get("home")
        names = [g for g in groups if isinstance(g, str)] if isinstance(groups, list) else []
        if group is not None and group not in names:
            continue
        row = {"seat": name, "groups": names, "home": None}
        out.append(row)
        if not (isinstance(home, str) and home.strip()):
            problems.append(problem(where, None, "seats file",
                                    f"{name} has no home folder, so its requests are not read"))
        elif "\x00" in home:
            problems.append(problem(where, None, "seats file",
                                    f"{name}'s home holds a NUL character, so its requests are not read"))
        elif ".." in Path(home).parts or (Path(home).anchor and not (Path(base) / home).is_relative_to(base)):
            problems.append(problem(where, None, "seats file",
                                    f"{name}'s home {home!r} is not inside the base folder, so it is not read"))
        else:
            row["home"] = str(Path(base) / home)   # a full path inside the base stands as it is, as in the inbox
            if not Path(row["home"]).is_dir():
                problems.append(problem(where, None, "seats file",
                                        f"{name}'s home folder {row['home']} does not exist"))
    return out


# ---------------------------------------------------------------------------------------------------- requests
def _options(v: dict) -> tuple[list[str], tuple[str, str] | None]:
    """A decision's options, and the problem with them if there is one. Only text is kept, as the inbox does."""
    if "options" not in v:
        return [], ("missing field", "it has no options")
    if not isinstance(v["options"], list):
        return [], ("bad field", "its options are not a list")
    kept = [o for o in v["options"] if isinstance(o, str)]
    left_out = len(v["options"]) - len(kept)
    return kept, ("bad field", f"{left_out} of its options are not text, and are left out") if left_out else None


def _card(v: dict) -> tuple[dict, list[tuple[str, str]]]:
    """A request as the inbox reads it, and the problems that leave it still shown. A line that cannot be a card is
    refused. A missing does, undo or options is a problem too, and so is a command or folder with a hidden character in
    it, but the card stays: something is waiting on you."""
    kind = _text(v, "kind")
    if kind is None:
        raise _Refused("missing field", "it has no kind")
    if kind not in KINDS:
        raise _Refused("unknown kind", f"its kind {kind[:40]!r} is neither decision nor command")
    missing = [k for k in REQUIRED[kind] if _text(v, k) is None]
    if missing:
        raise _Refused("missing field", "it has no " + ", ".join(missing))
    decision = kind == "decision"
    card = {"id": _text(v, "id"), "kind": kind, "title": _text(v, "title"), "why": _text(v, "why"),
            "question": _text(v, "question") if decision else None, "options": [],
            "command": None if decision else _text(v, "command"), "does": None if decision else _text(v, "does"),
            "undo": None if decision else _text(v, "undo"), "cwd": None if decision else _text(v, "cwd"),
            "at": _text(v, "at")}
    if decision:
        card["options"], bad = _options(v)
        return card, [bad] if bad else []
    absent = [k for k in ("does", "undo") if card[k] is None]
    noted = [("missing field", "it has no " + ", ".join(absent))] if absent else []
    hidden = _hidden(card["command"], card["cwd"])
    if hidden:
        noted.append(("hidden character", f"its command or folder holds an invisible or direction-changing character "
                                          f"({hidden}), so the text shown may not be what runs"))
    return card, noted


def _closing(v: dict, n: int, text: str, before: dict | None) -> dict:
    """A closing as the card shows it. A card closed twice shows the later closing, and keeps the earlier ones."""
    kept = [*before["earlier"], {k: before[k] for k in ("at", "how", "line")}] if before else []
    return {"at": _text(v, "at") or "", "how": _text(v, "how") or "", "line": n, "raw": text, "earlier": kept}


class _Requests:
    """One agent's request file, read. Every non-blank line becomes a card, a closing that took effect or a refused line
    with a problem, so tally lines = cards + closings + refused."""

    def __init__(self, seat: str, file: Path | None, problems: list):
        self.seat, self.file, self.problems = seat, file, problems
        self.tally = {"file": str(file) if file else None, "present": False, "lines": 0, "cards": 0, "closings": 0,
                      "refused": 0}

    def refuse(self, n: int, kind: str, text: str) -> None:
        self.tally["refused"] += 1
        self.problems.append(problem(self.file, n, kind, f"{self.seat}: {text}"))

    def note(self, n: int, kind: str, text: str) -> None:
        self.problems.append({**problem(self.file, n, kind, f"{self.seat}: {text} (the card is still shown)"),
                              "shown": True})

    def lines(self) -> list:
        """The file's lines. Nothing when it is not there (an agent that has asked nothing has no file yet), and nothing
        with a problem when it is there but cannot be read. The inbox reads a file whole or not at all: one byte that
        is not UTF-8 and none of it is read."""
        if self.file is None:
            return []
        try:
            size = self.file.stat().st_size
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as e:
            return self.unusable(f"cannot be read ({e})")
        self.tally["present"] = True
        if not self.file.is_file():
            return self.unusable(f"{FILE} is not a file")
        if size > FILE_CAP:
            return self.unusable(f"{FILE} is over 5 MB, so it is not read until it is trimmed")
        try:
            raw = self.file.read_bytes()
        except (OSError, ValueError) as e:
            return self.unusable(f"cannot be read ({e})")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            return self.unusable(f"it holds bytes that are not UTF-8 text ({e.reason}, at byte {e.start}), so none of "
                                 f"the file is read", "bad encoding")
        return _lines(text.lstrip(BOM))

    def unusable(self, why: str, kind: str = "file") -> list:
        self.problems.append(problem(self.file, None, kind, f"{self.seat}: {why}"))
        return []

    def cards(self) -> list[dict]:
        cards, seen, closings = [], set(), []
        for n, line in self.lines():
            trimmed = line.strip(SPACE)
            if not trimmed:
                continue
            self.tally["lines"] += 1
            if len(trimmed.encode("utf-8")) > MAX_LINE:   # measured after trimming, in bytes, as the inbox does
                self.refuse(n, "line too long", f"longer than {MAX_LINE // 1024} KB, so skipped")
                continue
            try:
                v = _parse(trimmed)
            except ValueError as e:
                self.refuse(n, "bad json", f"not JSON ({e})")
                continue
            if not isinstance(v, dict):
                self.refuse(n, "not an object", "it is JSON, but not an object")
                continue
            if _text(v, "close"):
                closings.append((n, line, _text(v, "close"), v))
                continue
            try:
                card, notes = _card(v)
            except _Refused as e:
                self.refuse(n, e.kind, e.text)
                continue
            if card["id"] in seen:
                self.refuse(n, "duplicate id", f"the id {card['id']} is used twice, and the first stands")
                continue
            seen.add(card["id"])
            self.tally["cards"] += 1
            cards.append({"seat": self.seat, **card, "state": "waiting", "closing": None, "run": None,
                          "parked_at": None, "asks": self.seat, "asks_basis": ASKS, "acts": self.seat,
                          "acts_basis": ACTS, "line": n, "raw": line})
            for kind, why in notes:
                self.note(n, kind, why)
        self.close(cards, closings)
        return cards

    def close(self, cards: list[dict], closings: list) -> None:
        """Apply the closings once every request is read, so a closing may come before its card."""
        by_id = {c["id"]: c for c in cards}
        for n, line, wanted, v in closings:
            card = by_id.get(wanted)
            if card is None:
                self.refuse(n, "closing with no card", f"a closing names {wanted}, which is not one of its requests")
                continue
            self.tally["closings"] += 1
            card["closing"] = _closing(v, n, line, card["closing"])


# ---------------------------------------------------------------------------------------------------- runs
# A run record is read as the inbox reads it: a JSON object (or an array of its nine fields in order) whose seat, id and
# started are text, whose finished is text or null, whose exit is a 32-bit whole number or null, whose timed_out is true
# or false, and whose stdout, stderr and command are text; a field twice is an error. A field it does not know is
# skipped as JSON and nothing more: its numbers are not checked for range, its text for surrogates, or its nesting for
# depth. Python's parser cannot read that way, so the record is read here, a token at a time.
_FIELDS = ("seat", "id", "started", "finished", "exit", "timed_out", "stdout", "stderr", "command")
_FIELD_KINDS = {"seat": ("str",), "id": ("str",), "started": ("str",), "finished": ("str", "null"), "exit": ("int", "null"),
          "timed_out": ("bool",), "stdout": ("str",), "stderr": ("str",), "command": ("str",)}
_WHAT = {"finished": "text or null", "exit": "a whole number that fits in 32 bits, or null",
         "timed_out": "true or false"}
_NUM_TOKEN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_LITERAL = re.compile(r"true|false|null")


def _ws(text: str, i: int) -> int:
    return _WS.match(text, i).end()


def _string(token: str) -> str:
    """The text of a JSON string token. Half of a surrogate pair is not text."""
    value = json.loads(token)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _Refused("bad json", "it holds half of a surrogate pair") from None
    return value


def _member(text: str, i: int) -> tuple[str, int]:
    """The name token of the object member at i, and the index just after the colon that follows it."""
    m = _STRING.match(text, i)
    if not m:
        raise _Refused("bad json", "a member of an object has no name, or its name is cut off")
    j = _ws(text, m.end())
    if text[j:j + 1] != ":":
        raise _Refused("bad json", "a member of an object has no colon after its name")
    return m.group(), j + 1


def _skip_value(text: str, i: int) -> int:
    """The index just after the JSON value that starts at i, its syntax checked and nothing else, at any depth."""
    closers: list[str] = []   # the containers the scan is inside, as the character that closes each
    while True:
        i = _ws(text, i)
        c = text[i:i + 1]
        if c in ("{", "["):
            closer = "}" if c == "{" else "]"
            j = _ws(text, i + 1)
            if text[j:j + 1] != closer:
                closers.append(closer)
                i = _member(text, j)[1] if c == "{" else j
                continue
            i = j + 1   # an empty container is a whole value
        else:
            m = _STRING.match(text, i) or _NUM_TOKEN.match(text, i) or _LITERAL.match(text, i)
            if not m:
                raise _Refused("bad json", "it is not JSON")
            i = m.end()
        while True:   # a value has ended: it may end the containers it is in, or be followed by another member
            if not closers:
                return i
            i = _ws(text, i)
            c = text[i:i + 1]
            if c == ",":
                i += 1
                if closers[-1] == "}":
                    i = _member(text, _ws(text, i))[1]
                break
            if c != closers[-1]:
                raise _Refused("bad json", "it is not JSON")
            closers.pop()
            i += 1


def _field(key: str, text: str, i: int) -> tuple[object, int]:
    """The value of the field `key` of a run record, which starts at i, checked against the field's type, and the index
    after it."""
    c = text[i:i + 1]
    if c in ("{", "["):
        kind, value, end = "container", None, i
    elif m := _STRING.match(text, i):
        kind, value, end = "str", _string(m.group()), m.end()
    elif m := _LITERAL.match(text, i):
        kind, value, end = ("null", None, m.end()) if m.group() == "null" else ("bool", m.group() == "true", m.end())
    elif m := _NUM_TOKEN.match(text, i):
        whole = not re.search(r"[.eE]", m.group()) and m.group() != "-0"   # the inbox's parser reads -0 as a float
        kind, value, end = ("int", int(m.group()) if len(m.group()) < 40 else None, m.end()) if whole \
            else ("float", None, m.end())
    else:
        raise _Refused("bad json", "it is not JSON")
    if kind not in _FIELD_KINDS[key]:
        raise _Refused("bad run record", f"its {key} is not {_WHAT.get(key, 'text')}")
    if key == "exit" and kind == "int" and (value is None or not -2 ** 31 <= value < 2 ** 31):
        raise _Refused("bad run record", f"its {key} is not {_WHAT[key]}")
    return value, end


def _record_object(text: str, i: int) -> tuple[dict, int]:
    """The fields of a run record written as an object, i being just after its opening brace, and the index after it."""
    got: dict = {}
    i = _ws(text, i)
    if text[i:i + 1] == "}":
        return got, i + 1
    while True:
        token, i = _member(text, i)
        key = _string(token)
        i = _ws(text, i)
        if key in _FIELDS:
            if key in got:
                raise _Refused("bad run record", f"its {key} appears twice")
            got[key], i = _field(key, text, i)
        else:
            i = _skip_value(text, i)
        i = _ws(text, i)
        c = text[i:i + 1]
        if c not in (",", "}"):
            raise _Refused("bad json", "it is not JSON")
        i += 1
        if c == "}":
            return got, i
        i = _ws(text, i)


def _record_array(text: str, i: int) -> tuple[dict, int]:
    """The fields of a run record written as an array of them in order, i being just after its opening bracket, and
    the index after it."""
    got: dict = {}
    i = _ws(text, i)
    if text[i:i + 1] == "]":
        return got, i + 1
    while True:
        if len(got) == len(_FIELDS):
            raise _Refused("bad json", "an array has more than the nine fields of a run record")
        key = _FIELDS[len(got)]
        got[key], i = _field(key, text, i)
        i = _ws(text, i)
        c = text[i:i + 1]
        if c not in (",", "]"):
            raise _Refused("bad json", "it is not JSON")
        i += 1
        if c == "]":
            return got, i
        i = _ws(text, i)


def _run_record(line: str) -> dict:
    """One line of runs.jsonl as the inbox keeps it ({seat, id, started, finished, exit, timed_out}), or a _Refused
    saying what is wrong with it."""
    i = _ws(line, 0)
    c = line[i:i + 1]
    if c == "{":
        got, end = _record_object(line, i + 1)
    elif c == "[":
        got, end = _record_array(line, i + 1)
    else:
        _skip_value(line, i)   # if it is not JSON at all, that is the problem; if it is, it is JSON of another shape
        raise _Refused("bad run record", "it is not a JSON object")
    if _ws(line, end) != len(line):
        raise _Refused("bad json", "there is more after the record")
    absent = [k for k in _FIELDS[:3] if k not in got]
    if absent:
        raise _Refused("bad run record", "it has no " + ", ".join(absent))
    return {"seat": got["seat"], "id": got["id"], "started": got["started"], "finished": got.get("finished"),
            "exit": got.get("exit"), "timed_out": got.get("timed_out", False)}


def _log(path: Path, problems: list, consequence: str) -> str | None:
    """The text of a shared log, or None: when it is not there, which is nothing to report, or when it cannot be read,
    which is a problem. The inbox reads a log whole or not at all, so one byte that is not UTF-8 means none of it is
    read."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        problems.append(problem(path, None, "file", f"cannot be read ({e}), so {consequence}"))
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as e:
        problems.append(problem(path, None, "bad encoding", f"it holds bytes that are not UTF-8 text ({e.reason}, at "
                                                            f"byte {e.start}), so none of it is read and {consequence}"))
        return None


def _runs(path: Path, problems: list) -> tuple[dict, int]:
    """The runs so far, by (agent, id), and how many lines the log has. A started line comes first and the result
    after it, so the later good line for a request replaces the earlier one. A line the inbox cannot read as a run record
    is a problem and no run, and never replaces a record before it. The log is read without the line limit and without
    dropping a byte-order mark: a record holds a command's output and can be long, and the inbox has no limit."""
    out: dict[tuple[str, str], dict] = {}
    text = _log(path, problems, "a card that has run may show as waiting")
    if text is None:
        return out, 0
    count = 0
    for n, line in _lines(text):
        if _blank(line):
            continue
        count += 1
        try:
            record = _run_record(line)
        except _Refused as e:
            problems.append(problem(path, n, e.kind, f"{e.text}, so a card that has run may show as waiting"))
            continue
        out[(record["seat"], record["id"])] = {k: record[k] for k in ("started", "finished", "exit", "timed_out")}
    return out, count


# ---------------------------------------------------------------------------------------------------- parking
def _parked(path: Path, problems: list) -> tuple[dict, dict, list]:
    """What is parked, from an append-only log whose latest event for a card wins: the cards parked now by (agent, id),
    the register decisions brought back by id, and every event understood as (line, agent, id), with no agent for a
    register decision, so the caller can check each names a card. Read as the inbox reads it: every byte-order mark at
    the start dropped, no limit on a line's length, and a line parsed as it stands (only JSON white space around it)."""
    cards: dict[tuple[str, str], str] = {}
    back: dict[str, str] = {}
    events: list[tuple[int, str | None, str]] = []
    text = _log(path, problems, "no parking is shown")
    if text is None:
        return cards, back, events
    for n, line in _lines(text.lstrip(BOM)):
        if _blank(line):
            continue
        try:
            v = _parse(line)
        except ValueError as e:
            problems.append(problem(path, n, "bad json", f"not JSON ({e})"))
            continue
        v = v if isinstance(v, dict) else {}
        event, seat, wanted, register = (_text(v, k) for k in ("event", "seat", "id", "register"))
        at = _text(v, "at") or ""
        if event in ("park", "back") and seat and wanted and register is None:
            events.append((n, seat, wanted))
            if event == "park":
                cards[(seat, wanted)] = at
            else:
                cards.pop((seat, wanted), None)
        elif event == "back" and seat is None and wanted is None and register:
            events.append((n, None, register))
            back[register] = at
        else:
            problems.append(problem(path, n, "unknown parking", "it is not a parking this reader knows"))
    return cards, back, events


def _state(card: dict) -> str:
    if card["run"]:
        return "run"
    if card["closing"]:
        return "closed"
    return "waiting" if card["parked_at"] is None else "parked"


def load(cfg: dict) -> dict:
    """Every agent's requests as cards, from the config's "seats" file and "inbox" folder (and its "group", when it has
    one: then only the agents in that group are read, as the inbox reads only its own).

    Without both keys: {"off": True, "missing": [the keys], "problems": []}. Otherwise a dict with
      seats     one row per agent in the seats file: seat, groups, home, file, present, lines, cards, closings, refused
      cards     seat, id, kind, title, why, question, options, command, does, undo, cwd, at, state (waiting, parked,
                closed or run), closing {at, how, line, raw, earlier} or None, run {started, finished, exit, timed_out}
                or None, parked_at, asks and acts (the agent) with asks_basis and acts_basis, line and raw (the line's
                number and exact text). A decision has a question and options, a command has command, does, undo, cwd
      counts    cards, by_state and by_seat
      runs      lines in the log, cards it names, and how many of those are no card read here
      parking   events understood, cards parked now, parkings on cards that are done, decisions_back {id: when}
      problems  every line or file that could not be used: source, line (or None), kind and text. The kinds are seats file,
                inbox folder, file, line too long, bad json, not an object, missing field, unknown kind, bad field,
                bad encoding (a file with a byte that is not UTF-8, which is read not at all), hidden character,
                duplicate id, closing with no card, bad run record, unknown parking and parking with no card. One that
                left its card shown has "shown": True
    A card that has run is "run" even when it is also closed: the run is the thing that happened. A run is only a line of
    runs.jsonl the inbox reads as a run record; a line it refuses is a problem here and leaves its card as it was."""
    missing = [k for k in ("seats", "inbox") if not cfg.get(k)]
    if missing:
        return {"off": True, "missing": missing, "problems": []}
    problems: list[dict] = []
    group = cfg["group"] if isinstance(cfg.get("group"), str) and cfg["group"] else None
    agents = _seats(cfg["seats"], problems, group)
    inbox = Path(cfg["inbox"])
    runs, run_lines, parked, back, events = {}, 0, {}, {}, []
    if inbox.is_dir():
        runs, run_lines = _runs(inbox / "runs.jsonl", problems)
        parked, back, events = _parked(inbox / "parked.jsonl", problems)
    else:
        problems.append(problem(inbox, None, "inbox folder", "it is not a folder, so no run or parking is read"))
    cards: list[dict] = []
    for agent in agents:
        requests = _Requests(agent["seat"], Path(agent["home"]) / FILE if agent["home"] else None, problems)
        cards.extend(requests.cards())
        agent.update(requests.tally)
    for c in cards:
        key = (c["seat"], c["id"])
        c["run"] = runs.get(key)
        c["parked_at"] = None if c["run"] or c["closing"] else parked.get(key)
        c["state"] = _state(c)
    known = {(c["seat"], c["id"]) for c in cards}
    for n, seat, wanted in events:
        if seat is not None and (seat, wanted) not in known:
            problems.append(problem(inbox / "parked.jsonl", n, "parking with no card",
                                    f"it names {wanted} of {seat}, which is not one of the requests read"))
    by_state = {s: sum(c["state"] == s for c in cards) for s in STATES}
    by_seat = {a["seat"]: {"cards": 0, **{s: 0 for s in STATES}} for a in agents}
    for c in cards:
        by_seat[c["seat"]]["cards"] += 1
        by_seat[c["seat"]][c["state"]] += 1
    return {"off": False, "seats": agents, "cards": cards,
            "counts": {"cards": len(cards), "by_state": by_state, "by_seat": by_seat},
            "runs": {"lines": run_lines, "cards": len(runs), "unmatched": len(runs.keys() - known)},
            "parking": {"events": len(events), "parked": by_state["parked"],
                        "on_done_cards": sum(k in known for k in parked) - by_state["parked"],
                        "decisions_back": back},
            "problems": problems}
