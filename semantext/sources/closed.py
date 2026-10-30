"""Closed places: folders the person has said nothing of Semantext's may read, judged in one place.

Before this, no shared check existed: each part judged on its own (docs/plugin-api.md, "Closed places must be named
first": one shared `is_closed_place(path)`, fed from the configured closures). The closures are the person's, written
in the sources file under one more key, or kept in a file of their own that the sources file names (or both, and the
lists merge):

    "closed": ["C:\\Users\\me\\Private", "~/secrets-folder"],
    "closures_file": "C:\\Users\\me\\closures.json",   a JSON file of the person's own
    "closures_key": "closed"                              the key in it holding the list ("closed" when not given)

each a full path (a leading ~ is the user's home). A path is closed when it is one of them or lies inside one, compared
as this system compares paths, both as written and with every link resolved, so a link that leads into a closed folder
is closed too.

Closures by NAME close a folder or file wherever it is, beside the paths, under one more key in either place, in the
closures-file format (schema "estate.closures/0"): a list of entries, each with an `id`, a
`form` and that form's fields (an entry may also carry `regex`, `closes`, `note`, `sentence` and `examples`, which
describe it and are never read for matching):

    segment                   {"segment": "private-notes"}: a segment of exactly this, and everything inside it
    segment-pair              {"segments": ["archive", "boxa"], "needs_separator_before": true,
                              "then": ["separator", ":", "end"]}: a separator, the two segments, then a separator, a
                              ':' (an NTFS stream) or the end
    segment-prefix-except     {"prefix": "vaultx", "segment_chars_after_prefix": "word characters (Unicode, as \\w),
                              '.' and '-'", "except_when_remainder_starts": "-public not followed by an ASCII letter or
                              digit"}: a segment that is the prefix and then only those characters, unless the rest
                              starts so (the two descriptions are read only in exactly these phrasings)
    segment-or-dotted-prefix  {"segment": ".secretrc", "or_segment_starts": ".secretrc."}: the segment, or one
                              starting with it and a dot
    substring                 {"substrings": ["coinjar.txt"]}: anywhere in the WHOLE path: my_coinjar.txt,
                              coinjar.txt.d\\a
    suffix                    {"suffixes": [".vaultfile"]}: at the end of the whole path
    "closures_names_key": "closed_names"         the key in the closures file holding them (this when not given)

Matching is the file's own `matching` rules: a search over the whole path string; case-insensitive as Python's
IGNORECASE takes it or wider (U+0130 and U+0131 as i, U+017F as s, the Kelvin sign as k; full case folding beyond);
both separators on every system; a single trailing newline is an end; applied to the path as given, as written in full,
and with every link resolved, and any entry closes. A path is closed when ANY of four legs closes it: the field matcher
on the path as given (case folded, not normalised), on its composed form (NFC) and on its decomposed form (NFD), and
the entry's own `regex` (case-insensitive, searched over the whole string; compiled once, at most 2,000 characters, or
the closures are unknown). So a path is closed whenever the entry's regex closes it, by construction: Semantext closes
more than the regex, never less. (Composing alone opened paths: a combining mark after a literal merges into its last
letter under NFC, and letters such as U+0958 decompose under NFC into a base and a mark that ends a prefix's segment.)
Semantext also tries the path as Windows reads it, each part without an NTFS stream suffix and trailing dots and spaces
(`private-notes::$INDEX_ALLOCATION`, `private-notes.`), closing more again. Where an entry's fields and its regex
disagree on the file's own `examples`, or either differs from an example's label, the page says so (information: the
path stays closed if either closes it). Names are judged by spelling: the folder-identity comparison closed paths also
get (a mapped or subst drive, below) is not made for them. A list given as null (`"closed_paths": null`, the file's way
of saying not supplied yet) is unknown, never [], and the reason says so, whichever key is read; a `schema` other than
"estate.closures/0" is unknown; a closures file that holds names and says no schema is unknown. A file that says its
schema may hold only the keys the schema has (schema, source, matching, closed_paths, closed_paths_complete,
known_closed_paths, known_open_paths_near, closed_names, _about, closed_paths_note, and the keys the sources file
names): any other key may be a closure this code cannot read, so the closures are unknown. Its `matching` is read for a
version only: one carrying a version this code does not know is unknown. Every reason names the entry's id and field.

The closures-file format is read ONLY in a closures file the sources file names, and only when that file says the
format's schema (another version of the format is unknown; any other closures file keeps 1.3.0's rule: its paths key
holds full paths). The sources file keeps 1.3.0's closures rules, with closed names beside them; its own format-looking
keys (FORMAT_KEYS, or the format's schema) mean nothing there and are said as a problem, never closing anything, so
nothing 1.3.0 read changes meaning (tests/test_closed_names.py holds that against 1.3.0 itself). A system that gives no
home folder is unknown, said as a problem, never a failure.

Three views, each reader taking one (SECURITY.md says which, and why): the plug-in view (named(), is_closed_place);
the strict view (strict_closures: nothing closed while none are named, everything while they are named and incomplete
or unknown), for a built-in reader that shows what files hold; and the lower-bound view (closures(), in_closed_place).
closures_state() says which state a person is in (known, none named, incomplete, unknown), why, and what fixes it.

Paths in a closures file that says its schema have two readers. A PLUG-IN is judged by `closed_paths` only when it is a
list, `closed_paths_complete` is exactly true, and every path in `known_closed_paths` is in it; anything else (null, not
complete, the two lists disagreeing) closes every path to a plug-in, with the reason said. The BUILT-IN readers read
`known_closed_paths` (and `closed_paths` when it is a list) beside every name: a lower bound, never complete, and the
page says "incomplete: files under a named root that no rule matches are readable until the list is complete". A listed
path closes itself and what is below it by component (`/` read as `\\`, trailing separators dropped, any case), as given
and with its links resolved; a sibling whose name only starts the same is not closed by it (a name entry may close it).
In a file that says the schema, a listed path may be a record holding it under "path" (with an id, a source, a note);
anywhere else ("closed" in the sources file, a closures file without the schema) a record is not a full path and the
closures are unknown, as in 1.3.0. `known_open_paths_near` is read for its shape only. A form beginning with two
separators (a share, \\\\?\\UNC, \\\\?\\GLOBALROOT, a device, \\\\.\\C:\\ included) cannot be read by string and is
closed while any closure exists, on every system, as in 1.3.0; only \\\\?\\C:\\ is read as C:\\ (1.3.0 did too). A
named root that is, or holds, a closed path (contains_closed) is refused by the Places reader's walk, which reads its
files without asking the closures; the rows the serve hook and plug-ins read keep it, since those ask of every path.

It fails closed. For a plug-in (is_closed_place, the api's check) the closures must be KNOWN: named as 1.3.0 named
them (a "closed" list, or a closures file read by its rules), and readable. Closed names ADD closures; they never by
themselves make the closures known: a sources file with "closed_names" and neither of those is none named for a
plug-in (every path closed), and its names close what they name for the built-in readers and the strict view. In a
sources file shaped like the closures-file format (its schema, or its keys) and naming no closures file,
"closed_names" is one of the format's keys there: said, not read. No closures named at all (no "closed" key and no
closures file, or no sources file) closes every path, and `semantext plugins enable` refuses until some are named (an owner ruling of 24 October:
the person's own sources file named none, so the check refused nothing). An explicit empty list is a statement that
nothing is closed, and is known. A closures file must hold its paths key (the one named, or "closed"), as in 1.3.0; its
names key is needed when the sources file names it, and may be left out while it is the default. Unknown too, closing
every path: a sources file or closures file that cannot be read, one that gives any key twice (JSON would keep only the
last), a list that is not of full paths, a closures file without a key it must hold, or holding, under any key that is
neither key read, a list SHAPED like closures (not empty, and all full paths, or all records whose "form" is one of the
forms): a list nobody reads would close nothing, in silence. Prose, texts and records of other shapes beside the lists
are another tool's and left alone, so a file kept for more than one tool can serve. Unknown too: a names entry without
an id (or with one given twice), with an unknown form, without a field its form needs, or with a field neither its
form nor the descriptive ones has; or a literal (a segment, prefix, substring, suffix...) that is empty or dot-only,
starts or ends with white space, holds a separator, a control, format or separator character (an inner ASCII space
aside), or is only combining marks, all of which would close nothing as typed. A ':' or a glob character (* ? [ ]) in a
literal is refused too, so one closures list means the same on every system and no entry is read as a pattern. Why
they cannot be known is said: why_unknown(), a "closures" problem on the page, and the refusal of `semantext plugins
enable`. The page also says, without closing anything more, a closed name that closes nearly every path (a substring,
suffix or prefix under 3 characters), and a list shaped like closures under a key of the sources file that no reader
reads.

The built-in readers keep their own rule (in_closed_place): no closures named closes nothing, as in 1.3.0 (the
person has said nothing is closed only by naming none, so the readers read what the sources file points them at);
what cannot be read still closes everything. Like the rest of the sources file this
is a file an agent can edit; the check holds a plug-in that follows the rules, and is no bar against code set on
reading a closed place. A plug-in is handed the person's closed paths and names (its ReadContext), so they are not
secret from one; the keys above are reserved (RESERVED_KEYS), and a plug-in that declares one is not added.
"""
from __future__ import annotations

import copy
import functools
import hashlib
import hmac
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .. import jsonread, paths
from . import config_path, problem

KEY = "closed"
NAMES_KEY = "closed_names"                             # closures by name, in any folder
FILE_KEY, LIST_KEY = "closures_file", "closures_key"   # a closures file of the person's own, and the key in it
NAMES_LIST_KEY = "closures_names_key"                  # the key in that file holding the names ("closed_names")
MAX_CLOSURES_FILE = 1024 * 1024                        # bytes; a larger closures file is unknown, never read
NOT_NAMED = "no closures are named"                    # what named() says when neither key is there
SCHEMA = "estate.closures/0"                           # the closures file format these entries follow
# each form, and its own fields (an entry may also carry COMMON's): read from the fields, never from a `regex`
FORMS = {
    "segment": ("segment",),
    "segment-pair": ("segments", "needs_separator_before", "then"),
    "segment-prefix-except": ("prefix", "segment_chars_after_prefix", "except_when_remainder_starts"),
    "segment-or-dotted-prefix": ("segment", "or_segment_starts"),
    "substring": ("substrings",),
    "suffix": ("suffixes",),
}
OPTIONAL = {"except_when_remainder_starts"}             # the one field a form may leave out
COMMON = ("id", "form", "regex", "closes", "note", "sentence", "examples")   # every other field is refused
PAIR_THEN = ["separator", ":", "end"]                  # what may follow a segment-pair, the one phrasing read
PREFIX_CHARS = "word characters (Unicode, as \\w), '.' and '-'"   # what may follow a prefix, the one phrasing read
EXCEPT_PHRASE = re.compile(r"(\S+) not followed by an ASCII letter or digit")   # the remainder that keeps one open
SEPARATORS = ("/", "\\")                               # both, on every system: a name holding either is refused
# refused so one closures list means the same on every system and no entry is read as a pattern
REFUSED_IN_NAMES = frozenset("\0:*?[]")
FOLD_EXTRA = {"İ": "i", "ı": "i", "ſ": "s"}   # as Python's case-insensitive matching takes them
from ..manifest import CLOSURE_KEYS as RESERVED_KEYS   # the person's; no plug-in declares one (one definition)
# the keys of the closures-file format: in the sources file, any of them means it holds closures in that format
FORMAT_KEYS = frozenset({"schema", "closed_paths", "closed_paths_complete", "known_closed_paths",
                         "known_open_paths_near"})
_UNRESERVED = ({KEY, NAMES_KEY, FILE_KEY, LIST_KEY, NAMES_LIST_KEY} | FORMAT_KEYS) - set(RESERVED_KEYS)
if _UNRESERVED:   # a real check, not an assert: it holds under python -O too, and stops the import
    raise ImportError(f"closures keys not reserved in manifest.CLOSURE_KEYS: {sorted(_UNRESERVED)}")
WIDE = 3   # a substring, suffix or prefix shorter than this closes nearly every path, and is said to
ASCII_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
MAX_REGEX = 2000   # characters of one entry's regex; a longer one makes the closures unknown
# a closures file that says its schema may hold these keys and no other (beside the keys the sources file names):
# a key it does not know may be a kind of closure this code cannot read, so the closures are unknown
SCHEMA_KEYS = frozenset({"schema", "source", "matching", "closed_paths", "closed_paths_complete", "known_closed_paths",
                         "known_open_paths_near", "closed_names", "_about", "closed_paths_note"})
LIST_KEYS = ("closed_paths", "known_closed_paths", "known_open_paths_near", "closed_names")   # null in any: unknown
MATCHING_VERSIONS = ()   # the `matching` versions this code knows; one carrying any other version is unknown
PATH_RECORD = frozenset({"id", "path", "source", "note", "why"})   # what a listed path may say beside its path
# what the page says while the closed paths are a lower bound (the closures file's own words)
INCOMPLETE = "incomplete: files under a named root that no rule matches are readable until the list is complete"


@dataclass(frozen=True)
class Name:
    """One closed name, as matched: its `id`, its `form`, and its literals folded (_fold): the segment, the two
    segments of a pair, the prefix, the segment and its dotted start, the substrings, or the suffixes. `excepted` is a
    segment-prefix-except's remainder that keeps a segment open ("" for none). `regex` is the entry's own, when it
    gives one: a path it matches (case-insensitive, searched over the whole string) is closed too."""
    id: str
    form: str
    texts: tuple[str, ...]
    excepted: str = ""
    regex: str = ""


def _file(home=None) -> Path:
    named = os.environ.get("SEMANTEXT_SOURCES")
    if named:
        return Path(named).expanduser()
    return Path(home) / "sources.json" if home else config_path()


NO_HOME = "the sources file cannot be found: this system gives no home folder (and no Semantext home is set)"


def _file_or_none(home=None) -> Path | None:
    """The sources file, or None when it cannot be found (a home that cannot be expanded: a problem, never a failure).
    None closes every path."""
    try:
        return _file(home)
    except (RuntimeError, KeyError, OSError, ValueError):
        return None


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


def _paths(said, records: bool = False) -> list[str] | None:
    """A list of full paths (a leading ~ expanded), or None when it is anything else. With `records` (only inside a
    closures file that says the closures-file format's schema), an entry may also be a record holding its path under
    "path" (with an id, a source, a note, and nothing else); everywhere else a record is not a path, as in 1.3.0."""
    if not isinstance(said, list):
        return None
    out = []
    for c in said:
        if isinstance(c, dict):
            if not records:
                return None
            if set(c) - PATH_RECORD or any(k != "path" and not isinstance(v, str) for k, v in c.items()):
                return None
            c = c.get("path")
        if not isinstance(c, str) or not c.strip():
            return None
        full = os.path.expanduser(c.strip())
        if not os.path.isabs(full):
            return None
        out.append(full)
    return out


def _fold(text: str) -> str:
    """A text as names are compared: composed (NFC, so macOS's decomposed spelling of a name is the same name), and
    without case, as Python's case-insensitive matching takes it or wider (U+0130 and U+0131 as i, U+017F as s, the
    Kelvin sign as k; full case folding beyond), so a fold closes whatever such matching would, and maybe more."""
    for _ in range(4):   # to a fixed point, so a folded name folds to itself (what a ReadContext's check asks)
        text0 = unicodedata.normalize("NFC", text)
        again = unicodedata.normalize("NFC", "".join(FOLD_EXTRA.get(c, c) for c in text0).casefold())
        if again == text:
            break
        text = again
    return text


def _visible(text: str) -> bool:
    """No control, format, surrogate or separator character but an inner ASCII space, and not only combining marks:
    otherwise a name closes nothing as the person typed it."""
    for c in text:
        cat = unicodedata.category(c)
        if c != " " and (cat[0] == "Z" or cat in ("Cc", "Cf", "Cs")):
            return False
    return not all(unicodedata.category(c)[0] == "M" for c in text)


def _word(said) -> str | None:
    """One literal of a name as compared, or None when it is not a text, starts or ends with white space, holds a
    separator, a ':', a glob character, a control, format or separator character (an inner ASCII space aside), is only
    combining marks, or names nothing ("", or made only of dots)."""
    if not isinstance(said, str) or not said or said != said.strip() or any(s in said for s in SEPARATORS) \
            or REFUSED_IN_NAMES.intersection(said) or not _visible(said) or not said.strip("."):
        return None
    return _fold(said) or None


def _words(said, count=None) -> tuple | None:
    """A non-empty list of literals (exactly `count` of them when given), folded; None when it is anything else."""
    if not isinstance(said, list) or not said or (count is not None and len(said) != count):
        return None
    out = tuple(_word(s) for s in said)
    return None if None in out else out


def _canonical(n) -> bool:
    """Whether `n` is a Name as named() makes one: an id, a known form, its literals folded and usable, and as many
    of them as the form has."""
    if not (type(n) is Name and isinstance(n.id, str) and n.id and n.id == n.id.strip() and n.form in FORMS
            and isinstance(n.texts, tuple) and n.texts and all(isinstance(t, str) and _word(t) == t for t in n.texts)
            and isinstance(n.excepted, str)):
        return False
    if n.excepted and (n.form != "segment-prefix-except" or _word(n.excepted) != n.excepted):
        return False
    wanted = {"segment": 1, "segment-pair": 2, "segment-prefix-except": 1, "segment-or-dotted-prefix": 2}.get(n.form)
    if wanted is not None and len(n.texts) != wanted:
        return False
    if not isinstance(n.regex, str) or (n.regex and _regex_why(n.regex)):
        return False
    return n.form != "segment-or-dotted-prefix" or n.texts[1] == n.texts[0] + "."


@functools.lru_cache(maxsize=512)
def _compiled(pattern: str):
    """An entry's regex, compiled once, as the closures file says it is applied: case-insensitive."""
    return re.compile(pattern, re.IGNORECASE)


def _regex_why(pattern) -> str | None:
    """Why an entry's regex cannot be used, or None: not a text, over MAX_REGEX characters, or not compiling."""
    if not isinstance(pattern, str):
        return "is not a text"
    if len(pattern) > MAX_REGEX:
        return f"is over {MAX_REGEX} characters"
    try:
        _compiled(pattern)
    except (re.error, OverflowError, ValueError, RecursionError, TypeError) as e:
        return f"does not compile ({type(e).__name__}: {str(e)[:80]})"
    return None


def _good_names(names) -> bool:
    return isinstance(names, (list, tuple)) and all(_canonical(n) for n in names)


def _shaped(value) -> bool:
    """Whether a value is shaped like a closures list: not empty, and all full paths, or all records naming one of
    the forms (a "form" this file reads). Prose, texts, and records of other shapes are not: a record such as
    {"name": ..., "url": ...} is another tool's, not a closed name."""
    if not isinstance(value, list) or not value:
        return False
    return _paths(value, records=True) is not None or all(isinstance(c, dict) and c.get("form") in FORMS
                                                          for c in value)


def _short(value) -> str:
    said = repr(value)
    return said if len(said) <= 60 else said[:57] + "..."


def _name_why(said, n: int) -> tuple[Name | None, str | None]:
    """One entry of a names list, in the closures file format, and None; or None and why it cannot be used, naming
    the entry (its id, or its place) and the field. An entry is an object with an `id`, a `form` and exactly that
    form's fields (and, besides, only `regex`, `closes`, `note`, `sentence` and `examples`, which describe it; the
    regex is applied too)."""
    if not isinstance(said, dict):
        return None, f"closed name {n} is not an object"
    id_ = said.get("id")
    who = f"closed name {id_!r}" if isinstance(id_, str) and id_ else f"closed name {n}"
    if not (isinstance(id_, str) and id_ and id_ == id_.strip()):
        return None, f"{who}: field 'id' must be a text without edge white space, not {_short(id_)}"
    form = said.get("form")
    if form not in FORMS:
        return None, f"{who}: field 'form' is {_short(form)}, not one of {', '.join(FORMS)}"
    fields = FORMS[form]
    extra = sorted(set(said) - set(COMMON) - set(fields))
    if extra:
        return None, f"{who}: field {extra[0]!r} is not one a {form} entry has"
    missing = [f for f in fields if f not in OPTIONAL and f not in said]
    if missing:
        return None, f"{who}: field {missing[0]!r} is missing"
    for k in ("closes", "note", "sentence"):
        if k in said and not isinstance(said[k], str):
            return None, f"{who}: field {k!r} must be a text"
    if "regex" in said and _regex_why(said["regex"]):
        return None, f"{who}: field 'regex' {_regex_why(said['regex'])}"
    if "examples" in said and not isinstance(said["examples"], dict):
        return None, f"{who}: field 'examples' must be a record"

    def literal(field, value, count=None, many=False):
        """A field's literals folded, and None; or None and why. A single text unless `many` (a list, `count` long)."""
        if many:
            texts = _words(value, count)
        else:
            texts = (_word(value),) if isinstance(value, str) and _word(value) else None
        if texts is not None:
            return texts, None
        shape = (f"a list of {count} literals" if count else "a non-empty list of literals") if many else "a literal"
        return None, (f"{who}: field {field!r} holds {_short(value)}, not {shape} (each a text with no separator, ':', "
                      f"glob character, control or format character or edge white space, nor only combining marks)")

    excepted = ""
    if form == "segment":
        texts, why = literal("segment", said["segment"])
    elif form == "segment-pair":
        texts, why = literal("segments", said["segments"], 2, many=True)
        if why is None and said["needs_separator_before"] is not True:
            why = f"{who}: field 'needs_separator_before' must be true"
        if why is None and said["then"] != PAIR_THEN:
            why = f"{who}: field 'then' must be {PAIR_THEN}"
    elif form == "segment-prefix-except":
        texts, why = literal("prefix", said["prefix"])
        if why is None and said["segment_chars_after_prefix"] != PREFIX_CHARS:
            why = f"{who}: field 'segment_chars_after_prefix' is read only as {PREFIX_CHARS!r}"
        if why is None and "except_when_remainder_starts" in said:
            told = said["except_when_remainder_starts"]
            got = EXCEPT_PHRASE.fullmatch(told) if isinstance(told, str) else None
            excepted = _word(got.group(1)) if got else None
            if excepted is None:
                why = (f"{who}: field 'except_when_remainder_starts' is read only as '<remainder> not followed by an "
                       f"ASCII letter or digit'")
    elif form == "segment-or-dotted-prefix":
        texts, why = literal("segment", said["segment"])
        if why is None:
            dotted, why = literal("or_segment_starts", said["or_segment_starts"])
            if why is None and dotted[0] != texts[0] + ".":
                why = f"{who}: field 'or_segment_starts' must be the segment and a dot"
            texts = (texts[0], dotted[0]) if why is None else None
    else:   # substring, suffix
        field = "substrings" if form == "substring" else "suffixes"
        texts, why = literal(field, said[field], many=True)
    if why is not None:
        return None, why
    return Name(id_, form, texts, excepted, said.get("regex", "")), None


def _names_why(said) -> tuple[list | None, str | None]:
    """A list of closed names and None, or None and why not: not a list, an entry that cannot be used, an id twice."""
    if not isinstance(said, list):
        return None, "is not a list"
    out, seen = [], set()
    for n, c in enumerate(said, 1):
        name, why = _name_why(c, n)
        if why:
            return None, why
        if name.id in seen:
            return None, f"closed name {name.id!r}: field 'id' is given to two entries"
        seen.add(name.id)
        out.append(name)
    return out, None


def _name(said) -> Name | None:
    return _name_why(said, 1)[0]


def _names(said) -> list[Name] | None:
    """A list of closed names, or None when it is not a list, any entry cannot be used, or an id is given twice."""
    return _names_why(said)[0]


def _examples(said) -> list[str]:
    """Where an entry's own examples disagree, said: its fields and its regex give two answers, or what they close
    is not what the example is labelled. Information only: nothing is closed or opened by it."""
    out = []
    for c in said if isinstance(said, list) else ():
        ex = c.get("examples") if isinstance(c, dict) else None
        name = _name(c) if isinstance(ex, dict) else None
        if name is None:
            continue
        for label in ("closed", "open"):
            for text in ex.get(label) or () if isinstance(ex.get(label), list) else ():
                if not isinstance(text, str):
                    continue
                fields = _matches_text(name, text)
                regex = bool(name.regex) and _compiled(name.regex).search(text) is not None
                if name.regex and fields != regex:
                    out.append(("closures examples",
                                f"the closed name {name.id!r}: its fields and its regex disagree on its own example "
                                f"{_short(text)} (fields: {'closed' if fields else 'open'}, regex: "
                                f"{'closed' if regex else 'open'}); the path is closed if either closes it"))
                elif (fields or regex) != (label == "closed"):
                    out.append(("closures examples",
                                f"the closed name {name.id!r}: its own example {_short(text)} is labelled {label}, "
                                f"and it is {'closed' if fields or regex else 'open'} here"))
    return out


def _text(said) -> bool:
    return isinstance(said, str) and bool(said.strip())


def keys_named(data: dict) -> tuple:
    """The two keys a closures file is read from, exactly as the sources file writes them (never trimmed): the paths
    key and the names key. The one place they are found; the Plug-ins tab reserves what this gives."""
    return data.get(LIST_KEY, KEY), data.get(NAMES_LIST_KEY, NAMES_KEY)


@dataclass(frozen=True)
class _Read:
    """One reading of the person's closures: what a plug-in is judged by (`plugin`) and what the built-in readers are
    (`builtin`), each a list, NOT_NAMED, or None when unknown; why the plug-in side is unknown; and notes to say."""
    plugin: object
    builtin: object
    why: str | None
    notes: tuple = ()


def _unknown(why: str, notes=()) -> _Read:
    return _Read(None, None, why, tuple(notes))


def _list_why(where: str, key: str, value, kind: str) -> tuple:
    """A closures list read (paths or names), and None; or None and why not. Null is said as itself: not supplied
    yet, which is unknown, never taken as an empty list."""
    if value is None:
        return None, (f'"{key}" in {where} is null: not supplied yet, which is unknown, so every path is treated as '
                      f'closed')
    if kind == "names":
        got, why = _names_why(value)
        return got, None if why is None else f'"{key}" in {where}: {why}'
    got = _paths(value, records=kind == "path records")   # records only in a closures file under the format's schema
    return got, None if got is not None else f'"{key}" in {where} is not a list of full paths'


def _reading(home=None) -> _Read:
    """The person's closures, read once: see the module's note for every rule. The sources file keeps 1.3.0's rules
    (with closed names beside them): the closures-file format is read only in a closures file it names, never in the
    sources file itself, whose format-looking keys mean nothing here (problems() says so)."""
    path = _file_or_none(home)
    if path is None:
        return _unknown(NO_HOME)
    if not path.is_file():
        return _Read(NOT_NAMED, NOT_NAMED, None)
    data = _load(path)
    if data is None:
        return _unknown("the sources file cannot be read as one JSON record giving each key once")
    out, found, notes = [], False, []
    # closed names ADD closures; they never by themselves make the closures known. In a sources file shaped like the
    # closures-file format (and naming no closures file), "closed_names" is one of the format's keys: said, not read
    shaped = FILE_KEY not in data and _format_shaped(data)
    for key, kind in ((KEY, "paths"), (NAMES_KEY, "names")):
        if key in data and not (kind == "names" and shaped):
            listed, why = _list_why("the sources file", key, data[key], kind)
            if why:
                return _unknown(why)
            out = out + listed
            if kind == "paths":
                found = True
            else:
                notes += _examples(data[key])
    if FILE_KEY in data or LIST_KEY in data or NAMES_LIST_KEY in data:
        where, (key, names_key) = data.get(FILE_KEY), keys_named(data)
        if not (_text(where) and _text(key) and _text(names_key)):
            # a closures key without a closures file, or any of them not a text, is a malformed setting
            return _unknown(f'"{FILE_KEY}" must name a closures file, and "{LIST_KEY}" and "{NAMES_LIST_KEY}" be texts')
        where = Path(os.path.expanduser(where.strip()))
        if not where.is_absolute():
            return _unknown(f'"{FILE_KEY}" is not a full path')
        kept = _load(where, MAX_CLOSURES_FILE)
        if kept is None:
            return _unknown("the closures file cannot be read as one JSON record, at most 1 MB, giving each key once")
        return _document(kept, "the closures file", key, names_key, NAMES_LIST_KEY in data, out, notes)
    said = list(dict.fromkeys(out))
    if found:
        return _Read(said, said, None, tuple(notes))
    # no "closed" list and no closures file: none named, as in 1.3.0 (every path closed to a plug-in); names alone
    # close what they name for the built-in readers and the strict view, which 1.3.0 left open
    return _Read(NOT_NAMED, said if said else NOT_NAMED, None, tuple(notes))


SCHEMA_FAMILY = SCHEMA.rsplit("/", 1)[0] + "/"   # "estate.closures/": another version of the format is unknown


def _in_format(kept: dict) -> bool | None:
    """Whether a closures file says the closures-file format: True for its schema, None for another version of the
    format (unknown), False for anything else, a schema of another tool included (read by 1.3.0's rule)."""
    said = kept.get("schema")
    if said == SCHEMA:
        return True
    if isinstance(said, str) and said.startswith(SCHEMA_FAMILY):
        return None
    return False


def _document(kept: dict, where: str, key: str, names_key: str, names_named: bool, out: list, notes: list) -> _Read:
    """The closures a closures file holds. One that says the closures-file format's schema is read by that format's
    rules; any other is read by 1.3.0's rule (its paths key must hold a list of full paths), with closed names only
    when it says the schema. `out` and `notes` are what the sources file said beside it."""
    notes = list(notes)
    schema = _in_format(kept)
    if schema is None:
        return _unknown(f"{where}'s schema is {_short(kept['schema'])}, a version of the closures-file format this "
                        f"does not read (only {SCHEMA!r})")
    if schema:
        # a key the schema does not have may be a closure this code cannot read: unknown, whatever it holds
        stray = sorted(k for k in kept if k not in SCHEMA_KEYS and k not in (key, names_key))
        if stray:
            return _unknown(f"{where} holds {', '.join(map(repr, stray))}, which its schema {SCHEMA!r} does not have")
        matching = kept.get("matching", {})
        if not isinstance(matching, dict):
            return _unknown(f"{where}'s 'matching' is not a record")
        if "version" in matching and matching["version"] not in MATCHING_VERSIONS:
            return _unknown(f"{where}'s matching version {_short(matching['version'])} is not one this reads "
                            f"({', '.join(MATCHING_VERSIONS) or 'none yet: only the unversioned rules'})")
        # null in any closures list is unknown, whichever key is read (a null beside an empty list included); the
        # paths key's null is the format's own "not supplied yet": plug-ins find every path closed, and the built-in
        # readers read the known paths (below)
        nulls = sorted(k for k in set(LIST_KEYS) | {names_key, "closed_paths_complete"}
                       if k in kept and kept[k] is None and k != key)
        if nulls:
            return _unknown(f'"{nulls[0]}" in {where} is null: not supplied yet, which is unknown, so every path is '
                            f'treated as closed')
    elif names_key in kept:
        return _unknown(f"{where} holds closed names under {names_key!r} and does not say its schema ({SCHEMA!r}), so "
                        f"what its names mean is not known")
    # the paths key must be there, as in 1.3.0 (an empty list says no folder is closed); the names key must be there
    # when the sources file names it, and may be left out while it is the default
    if key not in kept:
        return _unknown(f'{where} has no "{key}" list (write "{key}": [] when no folder is closed)')
    if names_named and names_key not in kept:
        return _unknown(f'{where} has no "{names_key}" list, which "{NAMES_LIST_KEY}" names')
    if not schema:   # 1.3.0's rule, exactly: its list is the closures, for plug-ins and readers alike
        listed, why = _list_why(where, key, kept[key], "paths")
        if why:
            return _unknown(why)
        said = list(dict.fromkeys(out + listed))
        return _Read(said, said, None, tuple(notes))
    # a list shaped like closures under a key nobody reads would close nothing, in silence: whatever its key's name
    # (closed_paths or closed_names under keys other than the ones read included; the format's information lists,
    # known_closed_paths and known_open_paths_near, are read by name); only in a file that says the format's schema
    informed = SCHEMA_KEYS - {"closed_paths", "closed_names"}
    unread = sorted(k for k in kept if k not in (key, names_key) and k not in informed and _shaped(kept[k]))
    if unread:
        return _unknown(f"{where} holds a list shaped like closures under {', '.join(repr(k) for k in unread)}, which "
                        f"is not read (the paths are read from {key!r}, the names from {names_key!r})")
    known = None
    for extra in ("known_closed_paths", "known_open_paths_near"):
        if extra in kept and extra not in (key, names_key):
            got = _paths(kept[extra], records=True)
            if got is None:
                return _unknown(f'"{extra}" in {where} is not a list of full paths')
            if extra == "known_closed_paths":
                known = got
    complete = kept.get("closed_paths_complete", None)
    if "closed_paths_complete" in kept and not isinstance(complete, bool):
        return _unknown(f"'closed_paths_complete' in {where} is not true or false")
    names = []
    if names_key in kept:
        names, why = _list_why(where, names_key, kept[names_key], "names")
        if why:
            return _unknown(why)
        notes += _examples(kept[names_key])
    listed = None
    if kept[key] is not None:
        listed, why = _list_why(where, key, kept[key], "path records")
        if why:
            return _unknown(why)
    # plug-ins: only a list that says it is complete, and holds every path known to be closed
    plugin_why = None
    if listed is None:
        plugin_why = (f'"{key}" in {where} is null: the complete list is not supplied yet, which is unknown, so every '
                      f'path is closed to a plug-in')
    elif complete is not True:
        plugin_why = (f"{where} does not say its closed paths are complete (closed_paths_complete is not true), so "
                      f"every path is closed to a plug-in")
    elif known and any(not any(_components(k) == _components(c) for c in listed) for k in known):
        plugin_why = (f"{where} says {key!r} is complete, and a path in known_closed_paths is not in it: the two lists "
                      f"disagree, so every path is closed to a plug-in")
    # the built-in readers: the paths known to be closed (a lower bound) and every name, never as complete
    if known is None and listed is None:
        return _unknown(f'"{key}" in {where} is null (the complete list is not supplied yet) and there is no '
                        f'known_closed_paths list, so no path is known to be closed and every path is treated as closed')
    reader_paths = list(dict.fromkeys((known or []) + (listed or [])))
    if plugin_why is not None:
        notes.append(("closures incomplete", INCOMPLETE))
    plugin = None if plugin_why is not None else list(dict.fromkeys(out + listed + names))
    builtin = list(dict.fromkeys(out + reader_paths + names))
    return _Read(plugin, builtin, plugin_why, tuple(notes))


def named(home=None) -> list | None | str:
    """The closures a plug-in is judged by, from "closed", "closed_names" and the closures file together: each closed
    folder as a full path (a text), each closed name as a Name; NOT_NAMED when none of them is there (or there is no
    sources file); None when they cannot be known."""
    return _reading(home).plugin


def why_unknown(home=None) -> str | None:
    """Why the closures the person named cannot be known, in a sentence; None when they are known or none are named."""
    r = _reading(home)
    return r.why if r.plugin is None else None


def _too_wide(n: Name) -> str | None:
    """Why a closed name closes nearly every path, or None: a substring, suffix or prefix shorter than WIDE characters,
    or one that matches a drive's part of a path (C:\\)."""
    if n.form in ("substring", "suffix", "segment-prefix-except") and any(len(t) < WIDE for t in n.texts):
        return f"a {n.form} under {WIDE} characters matches most paths"
    if any(_fields_hit(n, d) for d in ("c:\\", "c:/", "/")):
        return "it matches the drive or root part of every path"
    return None


def _looks_like_closures(path: Path | None) -> str | None:
    """What to say when the sources file looks like a closures file of the closures-file format (its schema, or the
    format's keys) and names no closures file: those keys mean nothing in the sources file, and nothing is read from
    them. Never a reason to close anything: the sources file keeps 1.3.0's rules."""
    data = _load(path) if path is not None and path.is_file() else None
    if data is None or FILE_KEY in data or not _format_shaped(data):
        return None
    keys = sorted(((FORMAT_KEYS - {"schema"}) | {NAMES_KEY}) & set(data))
    shown = ", ".join(map(repr, (["schema"] if "schema" in data else []) + keys))
    return (f"this looks like a closures file ({shown}); those keys are not read in your sources file, so nothing is "
            f"closed by them. Point closures_file at it to use it")


def _format_shaped(data: dict) -> bool:
    """Whether a sources file looks like a closures file of the closures-file format: the format's schema (any
    version), or any of the format's keys besides it."""
    said = data.get("schema")
    return (isinstance(said, str) and said.startswith(SCHEMA_FAMILY)) or bool((FORMAT_KEYS - {"schema"}) & set(data))


def _unread_in_sources(path: Path, declared) -> list[str]:
    """The sources file's keys that no one reads and that hold a list shaped like closures."""
    from . import KEYS   # here: the built-ins' keys are gathered once the package has loaded
    data = _load(path) if path is not None and path.is_file() else None
    if data is None:
        return []
    read = set(KEYS) | set(RESERVED_KEYS) | set(declared)
    return sorted(k for k in data if k not in read and _shaped(data[k]))


def problems(home=None, declared=()) -> list[dict]:
    """The page's problems about the closures, said aloud: closures named that cannot be known (every path is then
    closed); a closed name that closes nearly every path (kept: the person's choice); and a list shaped like closures
    under a key of the sources file nobody reads (`declared`: the keys the plug-ins turned on read), which closes
    nothing and so is said, never taken as closing everything. An entry on a list in a form that cannot be compared
    (two separators, a share or a device) closes every path, and is said too."""
    where = _file_or_none(home)
    r = _reading(home)
    said = r.builtin   # every list a reader judges by: the plug-in's is part of it, and names alone are only here

    def row(kind, text):
        return {**problem(where if where is not None else "sources file", None, kind, text), "reader": "closures"}

    out = []
    if r.plugin is None and r.why:
        whom = "every path is treated as closed" if r.builtin is None else "every path is closed to a plug-in"
        out.append(row("closures unknown", f"{whom}: {r.why}"))
    out += [row(kind, text) for kind, text in r.notes]
    for n in said if isinstance(said, list) else ():
        wide = _too_wide(n) if isinstance(n, Name) else None
        if wide:
            out.append(row("closures too wide", f"the closed name {n.id!r} ({n.form}) closes nearly every path: "
                                                f"{wide}"))
        if isinstance(n, str) and None in _component_forms(n):   # no path compares with it: closed, and said
            out.append(row("closures too wide", f"an entry in a form that cannot be compared closes every path: {n}"))
    for k in _unread_in_sources(where, declared):
        out.append(row("closures unread", f"a list shaped like closures under {k!r} is not read; closures are read "
                                          f"from 'closed' and 'closed_names'"))
    look = _looks_like_closures(where)
    if look:
        out.append(row("closures lookalike", look))
    return out


def closures(home=None) -> list | None:
    """The closures, closed folders as full paths and closed names as Names; [] when none are named; None when they
    cannot be known. The built-in readers' view: none named closes nothing (see the module's note)."""
    said = _reading(home).builtin
    return [] if said == NOT_NAMED else said


def closures_state(home=None) -> dict:
    """What a person is told of their closures, one place for the page, the console and the plug-ins tab: "known";
    "none named" (no closures at all); "incomplete" (named, read by the built-in readers as a lower bound, closed to
    plug-ins until the list says it is complete); or "unknown" (named and cannot be read). With the reason and what
    fixes it, in plain words."""
    r = _reading(home)
    if r.plugin == NOT_NAMED:
        alone = isinstance(r.builtin, list) and bool(r.builtin)
        return {"known": False, "state": "none named",
                "why": ('closed names alone never name your closures: they close what they name, and every other path '
                        'stays closed to a plug-in until a "closed" list or a closures file is there') if alone else None,
                "fix": 'name your closed places: a "closed" list of folders in your sources file (an empty list says '
                       'no folder is closed), or a closures file it names ("closures_file"); "closed_names" then '
                       'closes names too'}
    if r.plugin is not None:
        return {"known": True, "state": "known", "why": None, "fix": None}
    if r.builtin is not None:
        return {"known": False, "state": "incomplete", "why": r.why,
                "fix": "when every closed path is listed, give closed_paths as a list holding each path of "
                       "known_closed_paths and set closed_paths_complete to true; until then every path is closed to "
                       "a plug-in"}
    return {"known": False, "state": "unknown", "why": r.why,
            "fix": "correct your closures so they can be read (the reason says what is wrong); until then every path "
                   "is closed"}


def closures_known(home=None) -> bool:
    """Whether the person's closures are named and readable: what a plug-in's reads, and turning one on, need."""
    return isinstance(named(home), list)


def _unprefixed(path: str) -> str:
    """A Windows path without the \\\\?\\ prefix that turns off its parsing: \\\\?\\C:\\x is C:\\x, and \\\\?\\UNC\\host\\share
    is \\\\host\\share, with either slash in the prefix. realpath keeps the prefix it is given, so before this a closed
    folder's file written as \\\\?\\C:\\...\\closed\\README.md compared open (an attack on the first outside plug-in,
    finding 2). A \\\\.\\ form is a device path, kept as it is, so it stays a two-separator form, closed while any closure
    exists, as in 1.3.0. Elsewhere a path is returned as it is."""
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
    path). is_closed_place(path, ctx) judges against these, so a plug-in and the page agree on one home. `names` are
    the closed names (Names), read with them; a context made without it closes no name. `seal` is set when it is made
    (_seal_of): a context whose fields are changed afterwards (object.__setattr__ on a frozen record) no longer matches
    it, and is_closed_place then closes every path; it is never sealed anew. The seal's key lives in this process: it
    stops accidents (a field, or a name's field, set afterwards), not a hostile plug-in in the same process, which can
    read the key. Each plug-in is given its own copy (own_copy)."""
    home: str
    closures: tuple[str, ...] | None
    names: tuple[Name, ...] = ()
    seal: str = field(default="", init=False, repr=False, compare=False)

    def __post_init__(self):
        """A context built by hand is checked here: a name given as a text or a record would close nothing. It is
        sealed once: called again on a made context (to seal it anew after a change), it refuses."""
        if getattr(self, "seal", ""):
            raise TypeError("a ReadContext is sealed once, when it is made; make a new one instead")
        if self.closures is not None and not (isinstance(self.closures, (list, tuple))
                                              and all(isinstance(c, str) for c in self.closures)):
            raise TypeError("a ReadContext's closures are a tuple of full paths, or None when they cannot be known")
        if not _good_names(self.names):
            raise TypeError("a ReadContext's names are a tuple of closed.Name, each as the closures file is read "
                            "into one (a known form, its text folded); texts and records are not names")
        object.__setattr__(self, "seal", _seal_of(self))


_SEAL_KEY = os.urandom(32)   # this process's own: a seal made elsewhere never matches


def _seal_of(ctx) -> str:
    """The seal of a context's fields as they are now: each name by its own fields, never by its repr (a subclass's
    own repr could hide a change)."""
    names = tuple((type(n).__qualname__, n.id, n.form, tuple(n.texts), n.excepted, n.regex) for n in ctx.names)
    said = json.dumps([ctx.home, None if ctx.closures is None else list(ctx.closures), names], ensure_ascii=True)
    return hmac.new(_SEAL_KEY, said.encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()


def own_copy(ctx):
    """A fresh, sealed copy of a context, for one plug-in: what one plug-in does to its own (its names included) never
    reaches another's. A context already changed since it was made is never sealed anew: its copy closes every path."""
    if not _sealed(ctx):
        return ReadContext(str(ctx.home) if isinstance(getattr(ctx, "home", None), str) else "", None)
    return ReadContext(ctx.home, None if ctx.closures is None else tuple(ctx.closures),
                       tuple(copy.copy(n) for n in ctx.names))


def _sealed(ctx) -> bool:
    try:
        return isinstance(ctx.seal, str) and hmac.compare_digest(ctx.seal, _seal_of(ctx))
    except (TypeError, ValueError, AttributeError):
        return False


def context(home=None) -> ReadContext:
    """The context for one build of the page, from the home given (the default home when None). Its closures are None
    unless they are known, so a plug-in's read judges every path closed until the person names them."""
    said = named(home)
    where = str(home) if home else str(paths.home())
    if not isinstance(said, list):
        return ReadContext(where, None)
    return ReadContext(where, tuple(c for c in said if isinstance(c, str)),
                       tuple(c for c in said if isinstance(c, Name)))


def is_closed_place(path, ctx=None) -> bool:
    """Whether `path` is in a place the person closed: the api's check, for a plug-in. `ctx` is a ReadContext (its
    closures and names are used), or a Semantext home (api 0.1's second argument), or None for the default home. True
    for every path while the closures are not known (none named, or unreadable), and for anything that cannot be
    judged."""
    if isinstance(ctx, ReadContext):
        # checked again here: a context altered after it was made (its seal no longer matches), or with names that
        # are not Names, closes every path
        known = _sealed(ctx) and isinstance(ctx.closures, (list, tuple)) \
            and all(isinstance(c, str) for c in ctx.closures) and _good_names(ctx.names)
        said = list(ctx.closures) + list(ctx.names) if known else None
    else:
        said = named(ctx)
    return _judge(path, said if isinstance(said, (list, tuple)) else None)


def strict_closures(home=None) -> list | None:
    """The view of a built-in reader that reaches what files hold (the run-record reader): [] when no closures are
    named at all (nothing is closed, as for every built-in reader), the closures a plug-in is judged by when those are
    known, and None otherwise: closures named and incomplete, or unknown, close every path, as for a plug-in. Never the
    lower bound: a file under a named root that no rule matches is not read until the list says it is complete."""
    r = _reading(home)
    if r.plugin == NOT_NAMED:   # none named: nothing closed, but for names alone, which close what they name
        return r.builtin if isinstance(r.builtin, list) else []
    return r.plugin


def in_closed_place_strict(path, home=None) -> bool:
    """The strict built-in check (strict_closures)."""
    return _judge(path, strict_closures(home))


def in_closed_place(path, home=None) -> bool:
    """The built-in readers' check: as is_closed_place, except that no closures named closes nothing."""
    return _judge(path, closures(home))


LONG_DRIVE = re.compile(r"[\\/]{2}\?[\\/][A-Za-z]:(?:[\\/]|$)")   # \\?\C:\..., the one prefixed form taken as local
MAX_PARTS = 128                                                     # ancestors whose identity one judgement compares


def _shared(text: str) -> bool:
    """A path that starts with two separators and is not the \\\\?\\X: drive form: a share
    (\\\\localhost\\C$, \\\\127.0.0.1\\C$), \\\\?\\UNC\\..., \\\\?\\GLOBALROOT\\Device\\..., a device
    (\\\\.\\pipe\\...).
    Each can name a closed folder's bytes by a spelling no path comparison sees (the audit of 784faf6, finding 2;
    rules.not_local holds the same paths back for one reader), so while any closure exists such a path is closed, on
    every system (the closures file's matching.paths: such a form cannot be read by string)."""
    return text[:2] in ("\\\\", "//", "\\/", "/\\") and not LONG_DRIVE.match(text)


def _components(path: str) -> tuple | None:
    """A path's components as the closures file's path rule compares them: `/` read as `\\`, empty parts dropped (so
    trailing separators too), case folded; \\\\?\\C:\\ read as C:\\. None for any other form beginning with two
    separators, \\\\.\\C:\\ (a device path) included, which cannot be read by string (and so counts as closed, as in
    1.3.0)."""
    p = path.replace("/", "\\")
    if p.startswith("\\\\?\\"):
        rest = p[4:]
        if len(rest) >= 2 and rest[0].isascii() and rest[0].isalpha() and rest[1] == ":" and (len(rest) == 2 or
                                                                                               rest[2] == "\\"):
            p = rest
        else:
            return None
    elif p.startswith("\\\\"):
        return None
    return tuple(c for c in _casefold(p).split("\\") if c)


def _component_forms(path: str) -> set:
    """The components of a path as given and composed (NFC); {None} when it cannot be read."""
    return {_components(path), _components(unicodedata.normalize("NFC", path))}


def _listed_closed(text: str, listed) -> bool:
    """The path rule on one string: it is a listed path or lies below one, component by component (a sibling whose
    name only starts the same is not); a form that cannot be read is closed."""
    wants = [w for k in listed for w in _component_forms(k)]
    for have in _component_forms(text):
        if have is None or any(w is None or have[:len(w)] == w for w in wants):
            return True
    return False


def _contains_listed(root: str, listed) -> bool:
    """The other direction, on one string: the root is a listed path or an ancestor of one; one that cannot be read
    counts as holding one."""
    wants = [w for k in listed for w in _component_forms(k)]
    for have in _component_forms(root):
        if have is None or any(w is None or w[:len(have)] == have for w in wants):
            return True
    return False


def contains_closed(root, closures) -> bool:
    """Whether a named root may not be walked: it is closed itself (by any closure), or it is, or holds, a closed
    path, both as given and with links resolved on BOTH sides (a closed folder written through a junction or an 8.3
    name is the same folder), or the closures cannot be known (None). A reader refuses such a root (or prunes the
    closed path from its walk): a walk from it would enter the closed place, and the closed check says nothing of an
    ancestor."""
    if closures is None or not isinstance(root, (str, os.PathLike)) or not str(root).strip():
        return True
    if _judge(root, closures):
        return True
    folders = [c for c in closures if isinstance(c, str)]
    if not folders:
        return False
    text = os.path.expanduser(str(root))
    try:
        forms = _forms(os.path.abspath(text)) | {text}
        listed = [f for folder in folders for f in ({folder} | _forms(os.path.abspath(folder)))]
    except (OSError, ValueError):
        return True
    return any(_contains_listed(f, listed) for f in forms)


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


# ---- matching a closed name: the closures file's `matching` rules, from the fields alone --------------------------
# A search over the whole path string, case-insensitive (_fold), "\" and "/" both separators, a single trailing newline
# also an end (as Python's `$`). Each function below is the rule one form's `regex` states; the tests hold them equal.
def _end(s: str, i: int) -> bool:
    return i == len(s) or (i == len(s) - 1 and s[i] == "\n")


def _sep(s: str, i: int) -> bool:
    return i < len(s) and s[i] in SEPARATORS


def _starts(s: str):
    """Every index where a segment may start: the string's start, and just after each separator."""
    yield 0
    for i, ch in enumerate(s):
        if ch in SEPARATORS:
            yield i + 1


def _at(s: str, i: int, text: str) -> bool:
    return s.startswith(text, i)


def _whole_segment(s: str, i: int, text: str) -> bool:
    return _at(s, i, text) and (_end(s, i + len(text)) or _sep(s, i + len(text)))


def _match(n: Name, s: str, texts=None, rest=None) -> bool:
    """Whether a folded path string `s` holds the closed name `n` (its literals `texts`, its excepted remainder
    `rest`: the Name's own unless given, so one leg can compare them in another normal form)."""
    texts = n.texts if texts is None else texts
    rest = n.excepted if rest is None else rest
    if n.form == "segment":
        return any(_whole_segment(s, i, texts[0]) for i in _starts(s))
    if n.form == "segment-pair":   # a separator BEFORE the first, then a separator, ':' or the end after the second
        a, b = texts
        for i, ch in enumerate(s):
            if ch in SEPARATORS and _at(s, i + 1, a) and _sep(s, i + 1 + len(a)):
                j = i + 2 + len(a)
                if _at(s, j, b) and (_end(s, j + len(b)) or _sep(s, j + len(b)) or s[j + len(b)] == ":"):
                    return True
        return False
    if n.form == "segment-prefix-except":   # the prefix, then word characters, '.' and '-' to the segment's end
        p = texts[0]
        for i in _starts(s):
            if not _at(s, i, p):
                continue
            j = i + len(p)
            if rest and _at(s, j, rest) and not (j + len(rest) < len(s) and s[j + len(rest)] in ASCII_ALNUM):
                continue   # the excepted remainder, not followed by an ASCII letter or digit: kept open
            while j < len(s) and (s[j].isalnum() or s[j] in "_.-"):
                j += 1
            if _end(s, j) or _sep(s, j):
                return True
        return False
    if n.form == "segment-or-dotted-prefix":
        v, dotted = texts
        return any(_at(s, i, dotted) or _whole_segment(s, i, v) for i in _starts(s))
    if n.form == "substring":   # anywhere in the whole path, a longer name or a folder too
        return any(t in s for t in texts)
    if n.form == "suffix":   # at the end of the whole path (before a single trailing newline too)
        t = s[:-1] if s.endswith("\n") else s
        return any(s.endswith(x) or t.endswith(x) for x in texts)
    return True   # a form this code does not know closes (never reached: names are checked when read)


def _casefold(text: str) -> str:
    """Case folded as _fold does, and NOT normalised: a combining mark after a literal stays after it (under NFC it can
    merge into the literal's last letter, and the literal would vanish from the string)."""
    return "".join(FOLD_EXTRA.get(c, c) for c in text).casefold()


@functools.lru_cache(maxsize=4096)
def _forms_of(texts: tuple, form: str) -> tuple:
    """A Name's literals in each normal form it is compared in: as read (NFC) and decomposed (NFD)."""
    return tuple(dict.fromkeys((texts, tuple(unicodedata.normalize(form, t) for t in texts))))


def _fields_hit(n: Name, text: str) -> bool:
    """The field matcher's three legs on one string: as given (case folded, not normalised), composed (NFC) and
    decomposed (NFD), each against the literals as read and decomposed. Any leg closes."""
    rests = (n.excepted, unicodedata.normalize("NFD", n.excepted))
    for s in dict.fromkeys((_casefold(text), _casefold(unicodedata.normalize("NFC", text)),
                            _casefold(unicodedata.normalize("NFD", text)))):
        for texts in _forms_of(n.texts, "NFD"):
            for rest in dict.fromkeys(rests):
                if _match(n, s, texts, rest):
                    return True
    return False


def _matches_text(n: Name, text: str) -> bool:
    """Whether the closed name's FIELDS match the string `text` exactly as given (not the regex): the legs above."""
    return _fields_hit(n, text)


def _regex_hit(n: Name, text: str) -> bool:
    """The fourth leg: the entry's own regex, case-insensitive, searched over the whole string (the closures file
    says it is normative). A path it matches is closed, so a path is closed whenever the regex would close it."""
    return bool(n.regex) and _compiled(n.regex).search(text) is not None


DRIVE = re.compile(r"[A-Za-z]:")


def _aliases(text: str) -> str:
    """The same path as Windows would also take it: each part without an NTFS stream suffix (`name:stream`,
    `name::$INDEX_ALLOCATION` names the folder itself) and without trailing dots and spaces. A drive (C:) is kept."""
    parts = re.split(r"[\\/]", text)
    return "/".join(p if DRIVE.fullmatch(p) else p.split(":", 1)[0].rstrip(" .") for p in parts)


def _named(path: str, names) -> bool:
    """Whether a closed name matches `path`, as given or as Windows would also read it: by its fields (three legs) or
    by its regex. So a path is closed whenever the entry's regex closes it, and maybe more: never less."""
    variants = dict.fromkeys((path, _aliases(path)))
    return any(_fields_hit(n, s) or _regex_hit(n, s) for s in variants for n in names)


def _judge(path, closed) -> bool:
    if not isinstance(path, (str, os.PathLike)) or not str(path).strip():
        return True
    if closed is None:
        return True
    names = [c for c in closed if isinstance(c, Name)]
    folders = [c for c in closed if not isinstance(c, Name)]
    try:
        text = os.path.expanduser(str(path))
        if closed and _shared(text):
            return True
        here = _forms(os.path.abspath(text))
    except (OSError, ValueError):
        return True
    # names: the path as given, as this system writes it in full, and with its links resolved (_forms); any closes
    if names and any(_named(p, names) for p in here | {text}):
        return True
    if any(_inside(p, c) for folder in folders for c in _forms(folder) for p in here):
        return True
    if not folders:
        return False
    # the closures file's path rule beside it: by component, either separator, any case, as given and real
    if any(_listed_closed(p, folders) for p in here | {text}):
        return True
    # The same folder by another name a path cannot show (a mapped or subst drive, a share): compare what the system
    # says each is, the path's folders against the closed ones. A hard link to a closed file is not seen this way: a
    # file's other names cannot be listed. The serve hook refuses any file with a second name (docserve, nlink).
    shut = {i for i in (_identity(f) for folder in folders for f in _forms(folder)) if i}
    return bool(shut) and any(i in shut for p in here for i in _ancestry(p))
