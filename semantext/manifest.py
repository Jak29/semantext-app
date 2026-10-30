"""A plug-in's declaration: its settings and what it reads, kept as data among its package's files, so the page can
show both before the plug-in is on, and no code of it ever runs to draw them.

A package declares it in one file, semantext-plugin.json, in the folder of the module its entry point names
(semantext_jira/semantext-plugin.json for "semantext_jira.reader:SOURCE"), listed among its installed files as a page
module is (pagemodule.py). One file can declare every plug-in of the package:

    {"plugins": {"source.tickets": {
        "reads":    ["the tickets file you name, and nothing else"],
        "settings": [{"key": "tickets", "type": "path", "title": "Tickets file", "required": true},
                     {"key": "project", "type": "text"}]}}}

A setting's type is how the page draws it and how a proposed change to it is labelled:
    text    one text; a change never widens what the plug-in reads
    path    one full path; a change widens unless the new path lies inside the old one (links resolved)
    paths   a list of full paths; a change widens unless every new one lies inside one of the old
    list    a list of texts and numbers; a change widens when the list gains an entry (what its entries mean is not
            known: they may be paths), never when it only loses some
and "widens": true makes every change to it widen, whatever its type. The page makes no settings change at all: these
types only label the proposal it keeps for the person, who applies it at their console (pluginpage.py).
A setting may give its "default", what the plug-in reads when the setting is not given: taking the setting out then
widens only when that default is wider than the value taken out; with no default, taking it out always widens.
Keys are compared without case against Semantext's own and the closures' ("Closed" is refused as "closed" is).

The declaration is the package's word, not a fence: a plug-in is code with the process's whole reach (SECURITY.md,
"Plug-ins"). Reading it is a read of one small file the package installed; nothing is imported. A file that is not
there is no declaration; one that cannot be read, or is not of this shape, is a problem, and then no form is drawn.
"""
from __future__ import annotations

import os
import re

from . import jsonread

FILE = "semantext-plugin.json"
MAX_FILE = 64 * 1024
TYPES = ("text", "path", "paths", "list")
FIELDS = ("key", "type", "title", "widens", "required", "default")
MAX_SETTINGS, MAX_READS, MAX_WORDS = 32, 20, 200
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
MODULE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*")
# Keys a plug-in's settings may never be: the frame's and every built-in reader's, and the person's closures. A
# plug-in that declares one is refused whole, so the page can never rewrite the closures or a built-in's file.
# Every key the closures are read from, always reserved, whether or not the sources file uses it: "closed" and
# "closed_names" (the lists, by path and by name), "closures_file" (a closures file of the person's own), and
# "closures_key" and "closures_names_key" (the keys in that file holding them; the keys THOSE name are reserved too,
# by pluginpage.reserved_keys, in any case). The ONE definition: sources/closed.py's RESERVED_KEYS is this tuple, and
# closed.py refuses to import when a closures key it reads is not in it (tests/test_plugins_tab_attack8.py checks too).
# The closures-file format's own keys are reserved too: a sources file that holds any of them is read as holding the
# closures in that format (closed.FORMAT_KEYS), so a plug-in's setting may never add one.
CLOSURE_KEYS = ("closed", "closed_names", "closures_file", "closures_key", "closures_names_key",
                "schema", "closed_paths", "closed_paths_complete", "known_closed_paths", "known_open_paths_near")
NAMING_KEYS = ("closures_key", "closures_names_key")   # their values are keys of the closures too


class Bad(Exception):
    """A declaration that cannot be used, with the reason."""


def reserved() -> tuple[str, ...]:
    from .sources import KEYS   # here: the sources package is not needed to find the file
    return tuple(KEYS) + CLOSURE_KEYS


def _folder(module: str, files: set[str]) -> str | None:
    """The folder of the module an entry point names, as its distribution lists it: a package's own folder, or the
    folder a plain module lies in. None for a module at the top of the install, which has no folder of its own."""
    path = module.replace(".", "/")
    if f"{path}/__init__.py" in files:
        return path
    if f"{path}.py" in files and "/" in path:
        return path.rsplit("/", 1)[0]
    return None


def locate(point, dist) -> str | None:
    """The full path of the declaration file of the plug-in at this entry point, or None when it ships none. Bad when
    the file is listed but lies outside the folder its package is installed in. Only names are read: nothing loads."""
    value = getattr(point, "value", None)
    files = getattr(dist, "files", None) if dist is not None else None
    if type(value) is not str or not files:
        return None
    module = value.partition(":")[0].strip()
    if not MODULE.fullmatch(module):
        return None
    listed = {str(f).replace("\\", "/") for f in files}
    folder = _folder(module, listed)
    rel = f"{folder}/{FILE}" if folder else None
    if rel is None or rel not in listed:
        return None
    base = os.path.realpath(str(dist.locate_file("")))
    found = os.path.realpath(str(dist.locate_file(rel)))
    if not (found == base or found.startswith(base.rstrip("\\/") + os.sep)):
        raise Bad(f"{rel} resolves outside the folder its package is installed in")
    return found


def _setting(s, taken: set) -> dict:
    if not isinstance(s, dict):
        raise Bad("a setting is a record")
    extra = [k for k in s if k not in FIELDS]
    if extra:
        raise Bad(f"a setting has a field Semantext does not know: {str(extra[0])[:40]!r}")
    key = s.get("key")
    if type(key) is not str or not KEY.fullmatch(key):
        raise Bad(f"a setting's key is a plain word, not {str(key)[:40]!r}")
    if key.casefold() in {r.casefold() for r in reserved()}:   # "Closed" reads as "closed" to a person
        raise Bad(f"{key!r} is a key of Semantext's own or of your closures, so no plug-in may take it as a setting")
    if key in taken:
        raise Bad(f"the setting {key!r} is declared twice")
    if s.get("type") not in TYPES:
        raise Bad(f"the setting {key!r} has the type {str(s.get('type'))[:20]!r}; a type is one of {', '.join(TYPES)}")
    title = s.get("title", key)
    if type(title) is not str or not title.strip() or len(title) > 80:
        raise Bad(f"the setting {key!r} has a title that is not a short text")
    for flag in ("widens", "required"):
        if flag in s and type(s[flag]) is not bool:
            raise Bad(f"the setting {key!r} says {flag} as something other than true or false")
    taken.add(key)
    out = {"key": key, "type": s["type"], "title": title.strip(), "widens": s.get("widens", False),
           "required": s.get("required", False)}
    if "default" in s:   # what it reads when the setting is not given: taking the setting out is judged against it
        d, t = s["default"], s["type"]

        def one(v) -> bool:   # a text, or for a list a number too
            return (type(v) is str and bool(v.strip())) or (t == "list" and type(v) in (int, float))
        if not (one(d) if t in ("text", "path") else type(d) is list and bool(d) and all(one(v) for v in d)):
            raise Bad(f"the setting {key!r} gives a default that is not of its type")
        out["default"] = d
    return out


def parse(data, key: str) -> dict | None:
    """The declaration of the plug-in `key` ("<kind>.<name>") in a declaration file's record, or None when the file
    declares nothing for it. Bad when it is not of the shape the module's note gives."""
    if not isinstance(data, dict) or set(data) != {"plugins"} or not isinstance(data["plugins"], dict):
        raise Bad('a declaration file holds one record, "plugins", of "<kind>.<name>" to what each declares')
    mine = data["plugins"].get(key)
    if mine is None:
        return None
    if not isinstance(mine, dict) or any(k not in ("reads", "settings") for k in mine):
        raise Bad(f'what {key} declares is a record of "reads" and "settings"')
    reads = mine.get("reads", [])
    if (not isinstance(reads, list) or len(reads) > MAX_READS
            or not all(type(r) is str and r.strip() and len(r) <= MAX_WORDS for r in reads)):
        raise Bad(f'"reads" is a list of at most {MAX_READS} short texts')
    settings = mine.get("settings", [])
    if not isinstance(settings, list) or len(settings) > MAX_SETTINGS:
        raise Bad(f'"settings" is a list of at most {MAX_SETTINGS} records')
    taken: set = set()
    return {"reads": [r.strip() for r in reads], "settings": [_setting(s, taken) for s in settings]}


def read(point, dist, key: str) -> tuple[dict | None, str | None]:
    """(the declaration, None); (None, None) when the package ships none for this plug-in; (None, why) when it cannot
    be used. Never raises, and never imports anything."""
    try:
        where = locate(point, dist)
        if where is None:
            return None, None
        with open(where, "rb") as f:
            raw = f.read(MAX_FILE + 1)
        if len(raw) > MAX_FILE:
            raise Bad(f"{FILE} is over {MAX_FILE // 1024} KB, so it is not read")
        return parse(jsonread.loads(raw, unique=True), key), None
    except Bad as e:
        return None, str(e)[:300]
    except jsonread.NotJSON as e:   # json's own words, or ours: they carry no path
        return None, f"{FILE} is not JSON Semantext can read ({e})"[:300]
    except Exception as e:  # noqa: BLE001  a file, or a package's metadata, that cannot be read is a problem line
        return None, f"{FILE} cannot be read ({type(e).__name__})"
