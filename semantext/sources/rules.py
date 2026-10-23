"""Rules: the rule cards you have ratified, read where they lie and never written.

A card is one environment: a folder holding SEMANTICS.yaml, which says who ratified it and at which version, lists its
rules (each with an id, a kind, its own words and when it applies) and keeps the corrections it was built from as
tests. The "cards" source is a folder with one such folder per environment. This reads them all, and reports every
folder, file, rule or correction it cannot use as a problem, never by leaving it out in silence.

WHAT IS CHANGED IN WHAT A CARD SAYS, exactly, and nothing else:
  spaces  every run of space characters in a text is joined into one ordinary space, and the ends are trimmed. A space
          character is one of the 29 that Python's str.split() reads as one: U+0009 to U+000D (tab, line feed,
          vertical tab, form feed, carriage return), U+001C to U+001F, U+0020 (the ordinary space), U+0085, U+00A0
          (the no-break space), U+1680, U+2000 to U+200A (the en, em and thin spaces among them), U+2028, U+2029,
          U+202F, U+205F and U+3000 (the ideographic space). SPACES holds them and a test checks the list against the
          Python that runs. This makes a rule's words, a correction's message, every other text shown as a line, and
          every id (the id of an environment or a rule, and an id a card names) in the same way.
          Not changed: case, punctuation, and every character not listed, the zero-width space U+200B included.
  ids     a whole number written without quotes is an id, shown as its digits. A yes/no, a decimal, a date or a list is
          not an id: it is a problem that names it and says what it reads as.
  who     a ratifier that is empty, only spaces, `false` or an empty list names nobody, and what it ratified is a
          candidate.

A card is read as plain data, as yaml.safe_load reads it: no tags, so nothing a card says is ever run, and an alias
(*name) is read as safe_load reads it. Two bounds keep a card from costing without limit, and a card over either is a
problem that gives the bound, while the other cards are still read: the file may be MAX_CARD bytes (4 MiB), and with
every alias written out in full the data may come to MAX_EXPANDED characters (8 MiB; each value counts one and each text
its length). An alias that points back inside what it names never finishes writing out, so it is over every bound.
A folder or card that is a link is reported and not followed.

How firmly a rule is held is worked out from the cards alone and never guessed. A rule shows the highest of three:
  written  its words, and nothing that tests or guards them;
  checked  a correction kept as a test in some card is tied to it, because the rule's provenance names the case
           (cases: [id]) or the test names the rule (rules: [id]). A case a rule names that no card keeps is listed
           beside the rule and earns it nothing: an id alone cannot be run against anything;
  guarded  a checker refuses a break of it: the config's "guards" file names a checker for the rule's id, with what it
           must let pass and what it must refuse. The page names the checker. Nothing else makes a rule guarded.

A card may also record a `guard:` entry on a rule, as text or a list of texts (a bare yes or no, and the words none or
n/a, record none). That is the card's own claim. It is shown beside the rule, and it earns the rule nothing, since no
checker is named with the arms that would show it refuses a break.

The guards file is JSON: {"checkers": [{"name": what the checker is, "rules": [rule ids], "must_pass": what it lets
through, "must_refuse": what it refuses, "where": where it lives (optional)}]}. Each arm is a text or a list of texts,
and a checker with either arm empty is a problem and guards nothing. This reader does not run a checker; it reads what
the file says one does.

Nothing here starts a process or runs what a card says.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from datetime import date
from pathlib import Path

import yaml

from .. import jsonread
from . import problem

CARD = "SEMANTICS.yaml"
MAX_CARD = 4 * 1024 * 1024             # bytes in the file; a larger card is a problem, never parsed
MAX_EXPANDED = 2 * MAX_CARD            # characters with every alias written out in full; a larger card is a problem
NAME_SURROGATE = 0x20000000            # a reparse tag with this bit names another place: a symlink or a junction
GUARD_KEYS = ("guard", "guards")       # where a card may record what guards a rule
NO_GUARD = {"none", "no", "n/a", "na", "nil", "null", "false", "-"}   # a card saying there is none
RATIFICATION_FIELDS = ("date", "words", "mode", "record")
CHANGE_FIELDS = ("version", "date", "what", "ratified_by", "words", "record")
COUNTED = ("rules", "candidates", "written", "checked", "guarded", "cases")
# The 29 characters read as a space (see the top of this file). The code uses str.split(), which folds exactly these on
# the Python that runs; a test compares the two over every code point, so a Python that changed them would be caught.
SPACES = "".join(map(chr, [*range(0x09, 0x0E), *range(0x1C, 0x20), 0x20, 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B),
                           0x2028, 0x2029, 0x202F, 0x205F, 0x3000]))


class _Plain(yaml.SafeLoader):
    """yaml.safe_load's own loader, which also counts the aliases (*name) it meets, so that a card with none costs
    nothing extra."""
    aliases = 0

    def fetch_alias(self):
        self.aliases += 1
        super().fetch_alias()


def _children(node) -> list:
    if isinstance(node, yaml.SequenceNode):
        return node.value
    if isinstance(node, yaml.MappingNode):
        return [part for pair in node.value for part in pair]
    return []


def _expanded(root) -> int | None:
    """How big a card's data is with every alias written out in full: one for each value plus the characters of each
    text, a value met again through an alias counted again. It is worked out on the parsed nodes, without writing
    anything out, so a card that would never finish costs no more to measure than the card is long. Counting stops as
    soon as the total passes MAX_EXPANDED, and the number returned is then only 'more than that'. None when an alias
    points back inside what it names: written out in full it has no end."""
    size: dict[int, int] = {}
    state: dict[int, int] = {}                   # 1: being counted (an ancestor of what is), 2: counted
    stack = [(root, False)]
    while stack:
        node, leaving = stack.pop()
        key = id(node)
        if leaving:
            total = 1 + (len(node.value) if isinstance(node, yaml.ScalarNode) else 0)
            total += sum(size[id(child)] for child in _children(node))
            size[key], state[key] = min(total, MAX_EXPANDED + 1), 2
            if total > MAX_EXPANDED:
                return size[key]
        elif state.get(key) == 1:
            return None
        elif state.get(key) is None:
            state[key] = 1
            stack.append((node, True))
            stack.extend((child, False) for child in _children(node))
    return size[id(root)]


# ---- links ----------------------------------------------------------------------------------------------------
def _stat(path: Path):
    """The path's own stat (a link is not followed), or None when nothing is there."""
    try:
        return path.lstat()
    except OSError:
        return None


def _linked(st) -> bool:
    """A symbolic link, or a Windows junction or other link (a reparse point whose tag names another place). A cloud
    placeholder is a reparse point too, but it holds its own bytes, so it is not a link."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                and getattr(st, "st_reparse_tag", 0) & NAME_SURROGATE)


def _holds_card(folder: Path) -> bool | None:
    """Whether the folder holds an entry named SEMANTICS.yaml, whatever that entry is: True or False, or None when that
    could not be told."""
    try:
        (folder / CARD).lstat()
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False
    except OSError:
        return None


# ---- fields ---------------------------------------------------------------------------------------------------
def _squash(text: str) -> str:
    """The one change made to a text: its runs of space characters become one space, and the ends are trimmed."""
    return " ".join(text.split())


def _say(value) -> str:
    """Any field of a card as one line of text: a date in ISO form, a section as 'key: value; key: value'."""
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return "; ".join(f"{_squash(str(k))}: {s}" for k, v in value.items() if (s := _say(v)))
    if isinstance(value, (list, tuple)):
        return ", ".join(s for s in map(_say, value) if s)
    return _squash(str(value))


def _text(value) -> str | None:
    return _say(value) or None


def _name(value) -> str | None:
    """An id, its spaces joined like any text: text, or a whole number written without quotes. None for anything else,
    which is not an id: a yes/no, a decimal, a date, a list, nothing."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return _squash(str(value)) or None


def _reads_as(value) -> str:
    """What a value that is not an id reads as, in a card writer's words."""
    for kind, words in ((bool, "a yes/no"), (float, "a decimal number"), (date, "a date"), (list, "a list"),
                        (dict, "a section")):
        if isinstance(value, kind):
            return words
    return type(value).__name__


def _no_id(whose: str, value) -> str:
    """The message for a value that is not an id, telling an id that is missing from one that is the wrong kind."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return f"{whose} has no id"
    return f"{whose} has an id that reads as {_reads_as(value)} ({_say(value)[:40]}), not text; put it in quotes"


def _who(value) -> str | None:
    """Who ratified: the name the card gives, or None for anything that names nobody, such as an empty field or a
    `false`. A rule or card nobody ratified is a candidate."""
    return _text(value) if value else None


def _first(section: dict, *keys: str) -> str:
    """The first of these fields that says anything: the same thing under the names different cards use for it."""
    return next((s for s in (_say(section.get(k)) for k in keys) if s), "")


def _ids(value, what: str, bad) -> list[str]:
    """The ids in a field holding one id or a list of them, in order and without repeats. Anything else is a problem."""
    items = [] if value is None else value if isinstance(value, list) else [value]
    out = [_name(i) for i in items]
    if None in out:
        bad("bad-field", f"{what} should hold an id or a list of ids")
    return list(dict.fromkeys(i for i in out if i))


def _guards(entry: dict) -> list[str]:
    """What the card records as guarding a rule: the texts under `guard:`, if any. A bare yes or no is not a guard, and
    neither is a card saying there is none."""
    found = []
    for key in GUARD_KEYS:
        value = entry.get(key)
        for item in value if isinstance(value, list) else [value]:
            said = "" if item is None or isinstance(item, bool) else _say(item)
            if said and said.lower() not in NO_GUARD:
                found.append(said)
    return found


def _relation(value, rid: str, bad) -> dict[str, list[str]]:
    """How a rule stands to others, as the card says it: {"specializes": [ids], "replaces": [ids]}."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        bad("bad-field", f"rule {rid}: 'relation' should name, for each kind (specializes, replaces), the rule ids")
        return {}
    found = {_say(k): _ids(v, f"rule {rid}: relation {_say(k)}", bad) for k, v in value.items()}
    return {k: ids for k, ids in found.items() if k and ids}


# ---- one card -------------------------------------------------------------------------------------------------
def _why(e: Exception) -> str:
    return getattr(e, "problem", None) or (str(e).splitlines() or [type(e).__name__])[0]


def _parse(path: Path, bad) -> dict | None:
    """The card's data, or None (after saying why) when the file cannot be read as a card."""
    try:
        with path.open("rb") as f:
            raw = f.read(MAX_CARD + 1)
    except OSError as e:
        bad("unreadable", e)
        return None
    if len(raw) > MAX_CARD:
        bad("too-large", f"a card over {MAX_CARD:,} bytes ({MAX_CARD // 2**20} MiB) is not read")
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        bad("not-utf8", "the card is not saved as UTF-8 text; save it again as UTF-8")
        return None
    try:
        loader = _Plain(text)
        try:                                    # yaml.safe_load, with any aliases measured before they are used
            node = loader.get_single_node()
            if node is not None and loader.aliases:
                size = _expanded(node)
                if size is None:
                    bad("too-large", "an alias points back inside what it names, so written out in full the card "
                                     "never ends; it is not read")
                    return None
                if size > MAX_EXPANDED:
                    bad("too-large", f"its aliases, written out in full, come to more than {MAX_EXPANDED:,} "
                                     f"characters ({MAX_EXPANDED // 2**20} MiB); it is not read")
                    return None
            data = loader.construct_document(node) if node is not None else None
        finally:
            loader.dispose()
    except (yaml.YAMLError, ValueError, RecursionError) as e:   # ValueError: a date such as 2026-13-45
        mark = getattr(e, "problem_mark", None)
        bad("bad-yaml", _why(e), mark.line + 1 if mark else None)
        return None
    env = data.get("environment") if isinstance(data, dict) else None
    if not isinstance(env, dict):
        bad("not-a-card", "it is not a rule card: it needs an 'environment' section with an id")
        return None
    if _name(env.get("id")) is None:
        bad("not-a-card", _no_id("the 'environment' section", env.get("id")))
        return None
    return data


def _rule(x, label: str, agent: str | None, bad) -> dict | None:
    """One rule as it is shown, or None (after saying why) when it cannot be used."""
    if not isinstance(x, dict):
        bad("bad-rule", f"{label} is not a rule (each one starts '- id:', with its statement below)")
        return None
    rid, words = _name(x.get("id")), x.get("statement")
    if rid is None:
        bad("bad-rule", _no_id(label, x.get("id")))
        return None
    if not isinstance(words, str) or not words.strip():
        bad("bad-rule", f"rule {rid} has no statement, or one that is not text (put it in quotes)")
        return None
    prov = x.get("provenance")
    if prov is not None and not isinstance(prov, dict):
        bad("bad-field", f"rule {rid}: 'provenance' should be a section")
    prov = prov if isinstance(prov, dict) else {}
    ratified_by = _who(x.get("ratified_by"))
    return {
        "id": rid, "kind": _text(x.get("kind")), "words": _squash(words),
        "applies_when": _say(x.get("applies_when")), "as_of": _text(x.get("as_of")),
        "basis": _text(prov.get("type")), "quote": _text(prov.get("quote")),
        "ratified_by": ratified_by, "candidate": not ratified_by,
        "live": bool(x.get("enabled", True)) and not x.get("archived"),
        "agent": agent, "relation": _relation(x.get("relation"), rid, bad), "guards": _guards(x),
        "cases": _ids(prov.get("cases"), f"rule {rid}: the cases in its provenance", bad),   # ids until _tie
    }


def _entries(value, agent: str | None, what: str, bad) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        bad("bad-field", f"{what} should be a list")
        return []
    found = (_rule(x, f"{agent}'s rule {n}" if agent else f"rule {n}", agent, bad) for n, x in enumerate(value, 1))
    return [r for r in found if r]


def _rules(data: dict, bad) -> list[dict]:
    """The environment's own rules, then each agent's layer, all in one id space."""
    out = _entries(data.get("entries"), None, "'entries'", bad)
    agents = data.get("agents")
    if agents is not None and not isinstance(agents, dict):
        bad("bad-field", "'agents' should map each agent's name to its own entries")
    for name, layer in agents.items() if isinstance(agents, dict) else ():
        if isinstance(layer, dict):
            out += _entries(layer.get("entries"), str(name), f"{name}'s entries", bad)
        else:
            bad("bad-field", f"agent {name}: expected a section holding entries")
    seen = set()
    for r in out:
        if r["id"] in seen:
            bad("duplicate-id", f"two rules share the id {r['id']}")
        seen.add(r["id"])
    return out


def _case(t, n: int, bad) -> dict | None:
    """One correction kept as a test, or None (after saying why) when it cannot be used."""
    if not isinstance(t, dict):
        bad("bad-case", f"case {n} is not a case (each one starts '- case:', with the misread message)")
        return None
    cid = _text(t.get("case"))
    if not cid:
        bad("bad-case", f"case {n} has no case id, so no rule can name it")
        return None
    return {
        "id": cid, "message": _first(t, "message", "message_excerpt"),
        "excerpt": not t.get("message") and bool(t.get("message_excerpt")),
        "correction": _first(t, "correction", "his_correction"),
        "refinement": _first(t, "refinement", "his_refinement"),
        "expected": _say(t.get("expected")), "forbidden": _say(t.get("forbidden")), "source": _text(t.get("source")),
        "rules": _ids(t.get("rules"), f"case {cid}: 'rules'", bad),   # the rules it names, until _tie
    }


def _cases(value, bad) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        bad("bad-field", "'tests' should be a list")
        return []
    out, seen = [], set()
    for n, t in enumerate(value, 1):
        c = _case(t, n, bad)
        if c is None:
            continue
        if c["id"] in seen:
            bad("duplicate-id", f"two cases share the id {c['id']}")
        seen.add(c["id"])
        out.append(c)
    return out


def _lines(value, what: str, bad) -> list[str]:
    """A list of sentences, such as the rules for reading a card's rules; blank ones are left out."""
    if value is None:
        return []
    if not isinstance(value, list):
        bad("bad-field", f"{what} should be a list")
        return []
    return [s for s in map(_say, value) if s]


def _ratification(value, bad) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        bad("bad-field", "'ratification' should be a section (date, words, mode, record)")
        return None
    return {k: _text(value.get(k)) for k in RATIFICATION_FIELDS}


def _changes(value, bad) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        bad("bad-field", "'changes' should be a list")
        return []
    out = []
    for n, c in enumerate(value, 1):
        if isinstance(c, dict):
            out.append({k: _text(c.get(k)) for k in CHANGE_FIELDS})
        else:
            bad("bad-field", f"change {n} is not a section (version, date, what, ratified_by, words)")
    return out


def _environment(folder: Path, problems: list[dict]) -> dict | None:
    """One environment folder as it is shown, or None with the reason in `problems`."""
    path = folder / CARD

    def bad(kind: str, text, line: int | None = None) -> None:
        problems.append(problem(path, line, kind, text))

    st = _stat(path)
    if st is not None and _linked(st):
        bad("link", "is a link, so it is not followed")
        return None
    if st is None or not stat.S_ISREG(st.st_mode):
        problems.append(problem(folder, None, "no-card", f"this folder has no {CARD}"))
        return None
    data = _parse(path, bad)
    if data is None:
        return None
    e = data["environment"]
    eid = _name(e.get("id"))
    if eid != folder.name:
        bad("name-mismatch", f"the folder is {folder.name}, but the card says its id is {eid}")
    return {
        "name": folder.name, "id": eid, "title": _text(e.get("title")), "path": str(path),
        "version": _text(e.get("version")), "status": _text(e.get("status")),
        "ratified_by": _who(e.get("ratified_by")), "owner": _text(e.get("owner")), "scope": _say(e.get("scope")),
        "seat": _text(e.get("seat")), "evidence": _text(e.get("evidence")),
        "reading_rules": _lines(e.get("reading_rules"), "'reading_rules'", bad),
        "ratification": _ratification(e.get("ratification"), bad), "changes": _changes(e.get("changes"), bad),
        "parents": _ids(e.get("inherits"), "'inherits'", bad),   # name@version pins until _link_parents
        "rules": _rules(data, bad), "cases": _cases(data.get("tests"), bad),
    }


# ---- all the cards --------------------------------------------------------------------------------------------
def _held(rule: dict) -> str:
    if rule.get("checkers"):
        return "guarded"
    return "checked" if any(c["kept_in"] for c in rule["cases"]) else "written"


MAX_GUARDS = 1024 * 1024   # bytes in the guards file
NOT_LOCAL = "not checked: a network or device path"
# Where Windows' rules for a path hold. Python built for Cygwin or MSYS says os.name "posix", yet its paths reach the
# same shares and devices, so the platform is asked, when the path is judged, not os.name.
WINDOWS_PLATFORMS = ("win32", "cygwin", "msys")


def not_local(path: str) -> str | None:
    """NOT_LOCAL for a path whose lookup could leave this machine or reach a device. On Windows, Cygwin and MSYS: one
    that starts with two slashes of either kind (a share, \\\\?\\ or \\\\.\\), or holds a colon anywhere but after a
    leading drive letter (a stream, or a device such as CON:). Elsewhere a backslash and a colon are characters of a
    name like any other, so only a path that starts with exactly two slashes is held back: POSIX leaves its meaning to
    the system, and some systems take it as a share. Decided on the text alone, before any call to the file system.
    None for a local path."""
    s = str(path).strip()
    if sys.platform not in WINDOWS_PLATFORMS:
        return NOT_LOCAL if s[:2] == "//" and s[2:3] != "/" else None
    if s[:2] in ("\\\\", "//", "\\/", "/\\"):
        return NOT_LOCAL
    rest = s[2:] if len(s) >= 2 and s[1] == ":" and s[0].isascii() and s[0].isalpha() else s
    return NOT_LOCAL if ":" in rest else None


def _arm(value) -> list[str]:
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [_squash(x) for x in items if isinstance(x, str) and x.strip()]


def checkers(path, problems: list[dict]) -> dict[str, list[dict]]:
    """{rule id: the checkers the guards file names for it}. A checker without a name, a rule, or both arms is a
    problem and guards nothing."""
    if not path:
        return {}
    p = Path(path).expanduser()
    try:
        if p.stat().st_size > MAX_GUARDS:
            problems.append(problem(p, None, "too-large", "the guards file is over 1 MiB, so no checker is read"))
            return {}
        data = jsonread.loads(p.read_bytes().decode("utf-8-sig"))
    except FileNotFoundError:
        problems.append(problem(p, None, "no-guards-file", "the guards file named in your sources file is not there"))
        return {}
    except (OSError, ValueError, UnicodeDecodeError, RecursionError) as e:
        problems.append(problem(p, None, "bad-guards", f"the guards file cannot be read ({type(e).__name__}: {e})"))
        return {}
    listed = data.get("checkers") if isinstance(data, dict) else None
    if not isinstance(listed, list):
        problems.append(problem(p, None, "bad-guards", "the guards file needs a list under \"checkers\""))
        return {}
    out: dict[str, list[dict]] = {}
    for n, c in enumerate(listed, 1):
        name = _squash(c.get("name")) if isinstance(c, dict) and isinstance(c.get("name"), str) else ""
        rules_ = [_squash(r) for r in (c.get("rules") if isinstance(c, dict) and isinstance(c.get("rules"), list)
                                       else []) if isinstance(r, str) and r.strip()]
        must_pass, must_refuse = (_arm(c.get(k)) if isinstance(c, dict) else [] for k in ("must_pass", "must_refuse"))
        lacking = [w for w, ok in (("a name", name), ("a rule", rules_), ("a must-pass arm", must_pass),
                                   ("a must-refuse arm", must_refuse)) if not ok]
        if lacking:
            problems.append(problem(p, None, "bad-checker", f"checker {n} has no {', '.join(lacking)}, so it guards "
                                                            f"nothing"))
            continue
        where = c.get("where") if isinstance(c.get("where"), str) and c.get("where").strip() else None
        found, note = None, None   # whether the checker's path is there now: a fact about the path, never that it ran
        if where:
            note = not_local(where)
            if note is None:
                spot = Path(where).expanduser()
                spot = spot if spot.is_absolute() else p.parent / spot
                note = not_local(str(spot))   # a home or a guards file on a share makes the joined path one too
                if note is None:
                    try:
                        found = os.path.lexists(spot)
                    except (OSError, ValueError):
                        found = False
        for rid in rules_:
            out.setdefault(rid, []).append({"name": name, "must_pass": must_pass, "must_refuse": must_refuse,
                                            "where": where, "where_exists": found, "where_note": note})
    return out


def _name_ties(envs: list[dict], problems: list[dict]) -> None:
    """A correction that names its rules backs them: each rule it names gains the case among its own."""
    holders: dict[str, list[dict]] = {}
    for env in envs:
        for r in env["rules"]:
            holders.setdefault(r["id"], []).append(r)
    for env in envs:
        for c in env["cases"]:
            for rid in c["rules"]:
                if rid not in holders:
                    problems.append(problem(env["path"], None, "unknown-rule",
                                            f"case {c['id']} names the rule {rid}, which no card holds"))
                for r in holders.get(rid, []):
                    if c["id"] not in r["cases"]:
                        r["cases"].append(c["id"])


def _index(pairs) -> dict[str, list[str]]:
    """{key: its values} from (key, value) pairs, in the order met and each value once."""
    out: dict[str, list[str]] = {}
    for key, value in pairs:
        if value not in out.setdefault(key, []):
            out[key].append(value)
    return out


def _tie(envs: list[dict], problems: list[dict], guards: dict | None = None, guards_file=None) -> None:
    """Join the cards: which rules each kept correction backs, where each case is kept, which checkers guard each rule,
    and so how firmly each rule is held. A case counts wherever it is kept, since a rule and the tests for it need not
    share a file."""
    _name_ties(envs, problems)
    guards = guards or {}
    held_ids = {r["id"] for env in envs for r in env["rules"]}
    for rid in guards:
        if rid not in held_ids:
            problems.append(problem(guards_file or "guards", None, "unknown-rule",
                                    f"a checker names the rule {rid}, which no card holds"))
    kept = _index((c["id"], env["name"]) for env in envs for c in env["cases"])
    backs = _index((cid, r["id"]) for env in envs for r in env["rules"] for cid in r["cases"])
    for env in envs:
        for r in env["rules"]:
            r["cases"] = [{"id": cid, "kept_in": list(kept.get(cid, []))} for cid in r["cases"]]
            r["checkers"] = list(guards.get(r["id"], []))
            r["held"] = _held(r)
        for c in env["cases"]:
            c["rules"] = list(backs.get(c["id"], []))
        env["counts"] = _counts(env)


def _counts(env: dict) -> dict:
    held = [r["held"] for r in env["rules"]]
    return {"rules": len(held), "candidates": sum(r["candidate"] for r in env["rules"]),
            "written": held.count("written"), "checked": held.count("checked"), "guarded": held.count("guarded"),
            "cases": len(env["cases"])}


def _link_parents(envs: list[dict], unread: dict[str, tuple[str, str]], problems: list[dict]) -> None:
    """What each environment inherits, and whether that parent is still at the version it was ratified against. A parent
    whose folder is there but whose card was not read is told apart from one that is nowhere among the cards."""
    by_name = {e["name"]: e for e in envs}
    for env in envs:
        linked = []
        for pin in env["parents"]:
            name, _, wanted = (part.strip() for part in pin.partition("@"))
            parent = by_name.get(name)
            if parent is None and name in unread:
                state = "unread"
                kind, why = unread[name]
                problems.append(problem(env["path"], None, "unread-parent",
                                        f"{env['id']} inherits {name}, whose folder is there but whose card was not "
                                        f"read ({kind}: {why})"))
            elif parent is None:
                state = "missing"
                problems.append(problem(env["path"], None, "missing-parent",
                                        f"{env['id']} inherits {name}, which is not among the cards"))
            elif wanted and parent["version"] != wanted:
                state = "changed"
                problems.append(problem(env["path"], None, "stale-pin",
                                        f"{env['id']} pins {name}@{wanted}, but {name} is at "
                                        f"{parent['version'] or 'no version'}"))
            else:
                state = "current"
            linked.append({"name": name, "pin": wanted or None, "state": state,
                           "version": parent["version"] if parent else None})
        env["parents"] = linked


def _read_folder(folder: Path, problems: list[dict]) -> tuple[list[dict], list[str], dict[str, tuple[str, str]]]:
    """Every environment folder in name order, the names of everything else in the folder (such as the records of a
    ratification), and the folders that are there but whose card was not read, each with its first problem. A folder is
    an environment when it holds a SEMANTICS.yaml, whatever its name, or when its name starts with a letter or digit
    (then a missing card is a problem). A folder whose name starts with anything else and holds no card, such as .git,
    is listed with the rest. A link is a problem and is not followed."""
    try:
        children = sorted(folder.iterdir(), key=lambda p: (p.name.lower(), p.name))
    except OSError as e:
        problems.append(problem(folder, None, "unreadable", e))
        return [], [], {}
    envs, others, unread = [], [], {}

    def said(name: str, since: int, fallback: tuple[str, str]) -> None:
        unread[name] = (problems[since]["kind"], problems[since]["text"]) if len(problems) > since else fallback

    for p in children:
        since = len(problems)
        st = _stat(p)
        if st is None:
            problems.append(problem(p, None, "unreadable", "it could not be looked at"))
            continue
        if _linked(st):
            problems.append(problem(p, None, "link", "is a link, so it is not followed"))
            said(p.name, since, ("link", "is a link, so it is not followed"))
            continue
        if not stat.S_ISDIR(st.st_mode):
            others.append(p.name)
            continue
        if not p.name[:1].isalnum() and _holds_card(p) is False:
            others.append(p.name)
            unread[p.name] = ("no-card", f"it holds no {CARD}")
            continue
        try:
            env = _environment(p, problems)
        except Exception as e:   # whatever one card holds, the others are still read and this one is still said
            problems.append(problem(p, None, "unreadable", f"{type(e).__name__}: {e}"))
            env = None
        if env:
            envs.append(env)
        else:
            said(p.name, since, ("unreadable", "it was not read"))
    return envs, others, unread


def load(cfg: dict) -> dict:
    """The rule cards in the "cards" folder, or {"off": True, ...} when that key is missing.

    {"off": False, "cards": the folder, "environments": [...], "others": [...], "counts": {...}, "problems": [...]}.
    An environment is a folder that holds a SEMANTICS.yaml, or whose name starts with a letter or digit (see
    _read_folder); "others" names the rest: the files, and the folders with no card whose names start with anything
    else, such as .git. A folder or card that is a link is a problem and is not read. An environment holds its name
    (its folder's), id, title, version, status, who ratified it, owner, scope (or seat), evidence, the rules for reading
    its rules, how it was ratified (a date, the words, the record), its changes, its parents (each with the version
    pinned and whether the parent is still at it: state is current, changed, missing when no folder of that name is
    there, or unread when the folder is there but its card was not read), its rules and the corrections it keeps as
    tests ("cases").

    A rule holds its id, kind, words, when it applies, the date it was last known to hold (as_of), where it came from
    (basis, and the quote), who ratified it (a rule nobody ratified is a candidate), whether it is live (not switched
    off or undone), the agent whose layer it is in (None for the environment's own), how it stands to other rules
    (relation), the guards the card claims (shown, and counted for nothing), the checkers the config's "guards" file
    names for it (checkers), its cases (each with the cards that keep it) and how firmly it is held:
    written, checked or guarded. A case holds its id, the message that was misread, the owner's correction and
    refinement of it, the reading expected and the one forbidden, where it came from, and the rules it backs.

    A problem is {"source", "line", "kind", "text"}. The kinds: no-folder, unreadable, link, no-card, too-large,
    not-utf8, bad-yaml, not-a-card, name-mismatch, bad-rule, bad-field, bad-case, duplicate-id, unknown-rule,
    missing-parent, unread-parent, stale-pin, and for the guards file no-guards-file, bad-guards and bad-checker."""
    root = cfg.get("cards")
    if not root:
        return {"off": True, "environments": [], "problems": []}
    folder, problems = Path(root).expanduser(), []
    envs, others, unread = [], [], {}
    if folder.is_dir():
        envs, others, unread = _read_folder(folder, problems)
    else:
        problems.append(problem(folder, None, "no-folder", "the cards folder is not there"))
    guards_file = cfg.get("guards") if isinstance(cfg.get("guards"), str) and cfg.get("guards").strip() else None
    _tie(envs, problems, checkers(guards_file, problems), guards_file)
    _link_parents(envs, unread, problems)
    totals = {"environments": len(envs), **{k: sum(e["counts"][k] for e in envs) for k in COUNTED}}
    return {"off": False, "cards": str(folder), "environments": envs, "others": others, "counts": totals,
            "guards": guards_file, "problems": problems}
