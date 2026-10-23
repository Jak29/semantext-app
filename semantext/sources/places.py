"""Places: who your agents are, the projects they work in, the map those sit on, and the documents they keep.

You already keep these facts in files, so the page shows them where they lie instead of asking for a copy. Nothing is
written and no process is started.

The seats file names each agent (its names, groups, emails, home folder and sigils) and the roots: the folders that are
projects. With a group in the settings only the seats in that group are read, as your own inbox reads only its group's
seats: a seat is in a group when its list of groups holds that word, exactly. A root whose path is "{home}" stands for
every agent's own home, one project each. Seats that share one home folder are reported as sharing it, and the folder
stays one project. A project's .identity file lists who works in it, one "Name <email>" per line, with # for comments;
its lines end where str.splitlines() ends them (a line feed, a carriage return, or both). An agent works in a project
when its email is listed, or when the project is its home, and each membership says which. Emails listed that belong to
no agent are kept apart as "others", so nothing listed is lost.

The map is drawn in levels: the whole (named by you), a group for each agent's first group, and under it one
environment for each agent's home, holding that agent. Agents are members, never levels: an agent that works in two
places is one agent, with one id, shown in both.

The map file is a large JSON of places and edges. It is only summed up: how many entries its list of places holds and
how many of them carry each shape the map gives them (it calls some "not-a-place"), how many edges, when it was
measured, how its places group, and what its top level holds.

Documents are what an agent keeps for its projects, in <home>/cv/<project>/, listed as your own inbox lists them. A
folder counts when it holds a MASTER.md and is dated by its newest file; the first heading of a file is its title.
Links and junctions are never followed. Your inbox puts no limit on how many entries it reads in a folder; this reader
keeps one so that a folder of millions cannot stall it, and a folder over it is unknown: left out, with a problem that
says so, and never shown with a date or a missing MASTER.md that only part of it would give.

assign() says which project a card (a request in the inbox) belongs to. Where a card ran comes first: a card whose cwd
lies in a project belongs to the deepest project that holds it, whatever else its words mention. Only a card with no
cwd inside a project is placed by what it writes: the deepest project that holds a full path written in the words the
agent asked in. This is the rule of the plan, and it is not reopened here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePath
from typing import NamedTuple

from .. import jsonread
from . import MAX_LINE, problem

MAX_SEATS = 4 * 1024 * 1024   # a seats file over this is a mistake, not a list of seats
MAX_IDENTITY = 1024 * 1024    # likewise for an .identity file
MAX_MAP = 64 * 1024 * 1024    # the map is large; this only stops a file that is not one
DOC_CAP = 2 * 1024 * 1024     # a document over this is not read
MAX_ENTRIES = 2000            # entries read from one folder; a folder over it is unknown (see _entries)
TITLE_LIMIT = 160             # a group's title in the map's summary
NAME_SURROGATE = 0x20000000   # a reparse tag with this bit names another place: a symlink or a junction
CV = "cv"
MASTER = "master.md"
UNASSIGNED = "unassigned"
TEXT_FIELDS = ("title", "why", "question", "options", "command", "does", "undo")   # what an agent writes to ask
# "Name <email>", with an optional comment after it. Nothing else is an identity.
IDENTITY_LINE = re.compile(r"^(?P<name>[^<>#]*?)\s*<\s*(?P<email>[^<>\s@]+@[^<>\s]+)\s*>\s*(?:#.*)?$")
DRIVE = re.compile(r"[A-Za-z]:(?:/|$)")
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# ---- ids, paths and links -------------------------------------------------------------------------------------
def _node_id(kind: str, *parts: str) -> str:
    """A short, stable id from what a place is and where it lies, never from its name alone: the same place always has
    the same id, and two places that share a name do not."""
    return hashlib.sha256("\x1f".join((kind, *parts)).encode("utf-8", "surrogatepass")).hexdigest()[:10]


class _Where(NamedTuple):
    """A full path taken apart. `root` is "c:" for a drive, "//" for a share (whose server and name are its first two
    names) or "/" for a POSIX path; `names` are the folder names under it, with "." and ".." worked out the way Windows
    works them out and, on Windows, in lower case without the dots and spaces Windows drops from the end of a name."""
    root: str
    names: tuple[str, ...]


def _windows(root: str) -> bool:
    """Whether a root is a Windows one (a drive or a share): they cannot tell Desktop from desktop."""
    return root != "/"


def _fold(name: str, windows: bool) -> str:
    """A folder name as it is compared."""
    return name.rstrip(". ").casefold() if windows else name


def _steps(parts: list[str], windows: bool, keep: int) -> list[tuple[str, bool]]:
    """The folder names in a path split at its slashes, each with whether a slash follows it, with "." and ".." worked
    out. A ".." never takes away the first `keep` names (a share's server and name) or goes above the root. On Windows
    a name of only dots and spaces is nothing."""
    out: list[tuple[str, bool]] = []
    last = len(parts) - 1
    for i, raw in enumerate(parts):
        if raw in ("", "."):
            continue
        if raw == "..":
            if len(out) > keep:
                out.pop()
            continue
        if windows and not _fold(raw, True):
            continue
        out.append((raw, i < last))
    return out


def _top(s: str) -> tuple[str, str] | None:
    """(root, the rest) of a path written with forward slashes, or None when it is not a full path: a card's "." says
    nothing about where it ran, and "C:work" is a drive's own current folder."""
    if s.startswith(("//?/", "//./")):
        s = s[4:]
        if s[:4].upper() == "UNC/":
            s = "//" + s[4:]
    if DRIVE.match(s):
        return s[:2].casefold(), s[2:]
    if s.startswith("//"):
        return "//", s.lstrip("/")
    if s.startswith("/"):
        return "/", s[1:]
    return None


def _split(path) -> _Where | None:
    """A full path taken apart, or None when it is not one."""
    top = _top(str(path or "").strip().replace("\\", "/"))
    if top is None:
        return None
    root, rest = top
    windows = _windows(root)
    names = tuple(_fold(raw, windows) for raw, _ in _steps(rest.split("/"), windows, 2 if root == "//" else 0))
    return None if root == "//" and not names else _Where(root, names)


def _key(path) -> str | None:
    """A full path as it is compared: slashes forward, "." and ".." worked out, and lower case when it is a Windows path
    (a drive letter or a share), which cannot tell Desktop from desktop. None for a path that is not full."""
    where = _split(path)
    if where is None:
        return None
    return ("/" if where.root == "//" else "" if where.root == "/" else where.root) \
        + "".join("/" + n for n in where.names) or "/"


def _linked(st) -> bool:
    """A symbolic link, or a Windows junction or other link (a reparse point whose tag names another place). A cloud
    placeholder is a reparse point too, but it holds its own bytes, so it is not a link."""
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                and getattr(st, "st_reparse_tag", 0) & NAME_SURROGATE)


def _iso(secs: int) -> str:
    try:
        return (EPOCH + timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OverflowError:
        return ""


def _unfit(text: str) -> bool:
    """Whether a path holds a character no folder name can: a control character (a NUL among them) or a lone
    surrogate, which the file system would refuse or the reader could not write out."""
    return any(unicodedata.category(c) in ("Cc", "Cs") for c in text)


def _under(base: str | None, rel, source, what: str, problems: list) -> str | None:
    """A folder as the seats file writes it, in full: the base joined with a path that does not step out with "..".
    None, with the reason, when it cannot be."""
    if not isinstance(rel, str) or not rel.strip():
        problems.append(problem(source, None, "bad-path", f"{what} has no path"))
        return None
    if _unfit(rel):
        problems.append(problem(source, None, "bad-path", f"{what}: a path may not hold a control character"))
        return None
    if ".." in re.split(r"[\\/]", rel):
        problems.append(problem(source, None, "bad-path", f"{what}: a path may not step out with '..': {rel}"))
        return None
    full = Path(base) / rel.strip() if base else Path(rel.strip())
    if not full.is_absolute():
        problems.append(problem(source, None, "bad-path", f"{what}: {rel} is not a full path, and the seats file "
                                f"gives no base folder to put it under"))
        return None
    return str(full)


# ---- reading files --------------------------------------------------------------------------------------------
def _expand(path) -> Path:
    """A path with a leading ~ expanded. One that cannot be (a user this system does not know) is left as written, to
    be reported when it is opened."""
    try:
        return Path(path).expanduser()
    except RuntimeError:
        return Path(path)


def _json(path, limit: int, problems: list, what: str):
    """A JSON file, or None with the reason in problems."""
    p = _expand(path)
    try:
        if p.stat().st_size > limit:
            problems.append(problem(p, None, "too-big",
                                    f"{what} is over {limit // (1024 * 1024)} MB, so it is not read"))
            return None
        raw = p.read_bytes()
    except (OSError, ValueError) as e:   # a ValueError is a name the system cannot take, such as one holding a NUL
        problems.append(problem(p, None, "unreadable", f"{what} cannot be read: {getattr(e, 'strerror', None) or e}"))
        return None
    try:
        return jsonread.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:
        problems.append(problem(p, None, "encoding", f"{what} is not saved as UTF-8 text"))
    except (ValueError, RecursionError) as e:
        problems.append(problem(p, None, "not-json", f"{what} is not valid JSON ({e})"))
    return None


def _words(value, source, what: str, problems: list) -> list[str]:
    """The words in a list of the seats file (one word alone counts as a list of one). A blank, or anything that is not
    text, is reported."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        problems.append(problem(source, None, "shape", f"{what} should be a list of words"))
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            if item.strip() not in out:
                out.append(item.strip())
        else:
            problems.append(problem(source, None, "shape", f"{what} holds something that is not a word: {item!r}"))
    return out


def _entries(folder, problems: list, unknown: str) -> list | None:
    """The entries of a folder by name, or None when they cannot all be known: the folder cannot be listed, or holds
    more than MAX_ENTRIES (your inbox reads every entry; this limit only keeps a folder of millions from stalling the
    reader). Either way what the entries would tell is unknown, `unknown` says what in the problem, and nothing is
    worked out from some of the entries."""
    found: list = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                if len(found) >= MAX_ENTRIES:
                    problems.append(problem(folder, None, "too-many",
                                            f"holds over {MAX_ENTRIES} entries, so {unknown}"))
                    return None
                found.append(e)
    except OSError as e:
        problems.append(problem(folder, None, "unreadable", f"cannot be listed: {e.strerror or e}"))
        return None
    return sorted(found, key=lambda e: e.name)


def _stat(entry, problems: list):
    try:
        return entry.stat(follow_symlinks=False)
    except OSError as e:
        problems.append(problem(entry.path, None, "unreadable", f"cannot be examined: {e.strerror or e}"))
        return None


def _text(path, problems: list) -> str:
    """A file's text, or "" with the reason in problems when it is not UTF-8 or cannot be read."""
    try:
        return Path(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        problems.append(problem(path, None, "encoding", "is not saved as UTF-8 text, so its first heading is not read"))
    except OSError as e:
        problems.append(problem(path, None, "unreadable", f"cannot be read: {e.strerror or e}"))
    return ""


# ---- the seats file: agents -----------------------------------------------------------------------------------
def _sigils(value, source, who: str, problems: list) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append(problem(source, None, "shape", f"{who}: sigils should map a board's name to its sigils"))
        return {}
    return {str(k): _words(v, source, f"{who}: sigils for {k}", problems) for k, v in value.items()}


def _in_group(groups, group: str) -> bool:
    """Whether a seat's list of groups holds `group`, word for word: the way your own inbox picks its seats."""
    return isinstance(groups, list) and any(isinstance(g, str) and g == group for g in groups)


def _agents(seats, base: str | None, source, seats_key: str, group: str | None, problems: list) -> list[dict]:
    """One agent per seat in the group (every seat when there is no group), in the order the seats file gives them."""
    out: list[dict] = []
    taken: set[str] = set()
    for name, seat in seats.items():
        who = str(name).strip()
        if not who or not isinstance(seat, dict):
            problems.append(problem(source, None, "shape", f"seat {name!r} is not a record of names, groups, emails "
                                    f"and a home"))
            continue
        if group is not None and not _in_group(seat.get("groups"), group):
            continue
        if who in taken:   # two keys that differ only in their spaces: one agent must not be two
            problems.append(problem(source, None, "duplicate-seat", f"{who} is listed twice as a seat, so the first "
                                    f"listing stands"))
            continue
        taken.add(who)
        names = _words(seat.get("names"), source, f"{who}: names", problems)
        home = None
        if seat.get("home") is None:
            problems.append(problem(source, None, "no-home", f"{who} has no home folder, so it has no environment and "
                                    f"no project of its own"))
        else:
            home = _under(base, seat["home"], source, f"{who}'s home", problems)
        if home and not os.path.isdir(home):
            problems.append(problem(home, None, "missing-folder", f"{who}'s home folder does not exist"))
        out.append({
            "id": _node_id("agent", seats_key, who),
            "name": who,
            "other_names": [n for n in names if n.casefold() != who.casefold()],
            "groups": _words(seat.get("groups"), source, f"{who}: groups", problems),
            "emails": _words(seat.get("emails"), source, f"{who}: emails", problems),
            "home": home,
            "sigils": _sigils(seat.get("sigils"), source, who, problems),
            "placed": {"group": None, "environment": None, "projects": []},
        })
    if group is not None and not out:
        problems.append(problem(source, None, "empty-group", f"no seat is in the group {group!r}, so no agent is read"))
    return out


def _emails(agents: list[dict], source, problems: list) -> dict[str, list[int]]:
    """Which agents each email belongs to (ignoring case). An email two agents share is reported."""
    by_email: dict[str, list[int]] = {}
    for i, a in enumerate(agents):
        for e in a["emails"]:
            by_email.setdefault(e.casefold(), []).append(i)
    for e, who in by_email.items():
        if len(who) > 1:
            problems.append(problem(source, None, "shared-email", f"{e} is listed for {len(who)} agents "
                                    f"({', '.join(agents[i]['name'] for i in who)}), so it names all of them"))
    return by_email


def _shared_homes(agents: list[dict], source, problems: list) -> None:
    """Seats that have one home folder are said to, once for the folder. They are not merged without a word: the folder
    is one project (with each of them at home in it), but each keeps its own environment, documents and id."""
    homes: dict[str, list[dict]] = {}
    for a in agents:
        if a["home"]:
            homes.setdefault(_key(a["home"]) or a["home"], []).append(a)
    for who in homes.values():
        if len(who) > 1:
            problems.append(problem(source, None, "shared-home", f"{', '.join(a['name'] for a in who)} have one home "
                                    f"folder, {who[0]['home']}: it is one project, each of them is at home in it, and "
                                    f"its documents are listed under each of them"))


# ---- projects and who works in them ---------------------------------------------------------------------------
def _identity(folder: str, problems: list):
    """The (name, email) pairs of a project's .identity file, and what became of the file."""
    path = os.path.join(folder, ".identity")
    info = {"path": path, "state": "absent", "entries": 0}
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        problems.append(problem(path, None, "absent", "there is no .identity file, so no one is listed from it"))
        return [], info
    except OSError as e:
        info["state"] = "unreadable"
        problems.append(problem(path, None, "unreadable", f"cannot be examined: {e.strerror or e}"))
        return [], info
    why = ""
    if _linked(st):
        why = "is a link, so it is not followed"
    elif not stat.S_ISREG(st.st_mode):
        why = "is not a file"
    elif st.st_size > MAX_IDENTITY:
        why = f"is over {MAX_IDENTITY // (1024 * 1024)} MB, so it is not read"
    if why:
        info["state"] = "unreadable"
        problems.append(problem(path, None, "unreadable", why))
        return [], info
    found: list[tuple[str, str]] = []
    try:
        raw = Path(path).read_bytes()
    except OSError as e:
        info["state"] = "unreadable"
        problems.append(problem(path, None, "unreadable", f"cannot be read: {e.strerror or e}"))
        return [], info
    # The lines are the text's own lines, as str.splitlines() ends them (a lone carriage return among them): the way the
    # person's other tools read this file.
    for n, text in enumerate(raw.decode("utf-8-sig", errors="replace").splitlines(), 1):
        if len(text.encode("utf-8", "surrogatepass")) > MAX_LINE:
            problems.append(problem(path, n, "bad-line", f"is longer than {MAX_LINE} bytes, so it is skipped"))
            continue
        text = text.strip()
        if not text or text.startswith("#"):
            continue
        m = IDENTITY_LINE.match(text)
        if m:
            found.append((m["name"].strip(), m["email"]))
            if "\N{REPLACEMENT CHARACTER}" in text:   # bytes that are not UTF-8 were replaced: used, and said
                problems.append(problem(path, n, "encoding", "has bytes that are not UTF-8, so its name or email "
                                        "may be altered"))
        else:
            problems.append(problem(path, n, "bad-line", f'is not "Name <email>": {text}'))
    info["state"], info["entries"] = "read", len(found)
    return found, info


def _project(name: str, root: str, path: str, agents: list[dict], by_email: dict, problems: list) -> dict:
    key = _key(path)
    exists = os.path.isdir(path)
    if not exists and not any(_key(a["home"]) == key for a in agents if a["home"]):
        problems.append(problem(path, None, "missing-folder", f"the folder of the project {name} does not exist"))
    found, info = _identity(path, problems) if exists else ([], {"path": os.path.join(path, ".identity"),
                                                                 "state": "absent", "entries": 0})
    listed: dict[int, list[str]] = {}
    others: list[dict] = []
    for who, email in found:
        hit = by_email.get(email.casefold())
        if hit:
            for i in hit:
                if email not in listed.setdefault(i, []):
                    listed[i].append(email)
        elif not any(o["email"].casefold() == email.casefold() and o["name"] == who for o in others):
            others.append({"name": who, "email": email})
    pid = _node_id("project", key or path)
    members = []
    for i, a in enumerate(agents):
        basis = (["home"] if a["home"] and _key(a["home"]) == key else []) + (["identity"] if i in listed else [])
        if basis:
            members.append({"agent_id": a["id"], "name": a["name"], "basis": basis, "emails": listed.get(i, [])})
            a["placed"]["projects"].append(pid)
    return {"id": pid, "name": name, "root": root, "path": path, "kind": "repo", "exists": exists,
            "home_of": [m["name"] for m in members if "home" in m["basis"]], "members": members, "others": others,
            "identity": info}


def _projects(roots, agents: list[dict], by_email: dict, base: str | None, source, problems: list) -> list[dict]:
    """One project per root of kind "repo"; a "{home}" root gives one per agent that has a home. A folder listed twice
    is one project, the first listing standing and the problem naming both listings."""
    out: list[dict] = []
    seen: dict[str, tuple[str, bool]] = {}   # the folder -> how it was first listed, and whether as a home

    def add(name: str, root: str, path: str, listing: str, as_home: bool) -> None:
        key = _key(path) or path
        if key in seen:
            first, first_as_home = seen[key]
            if not (as_home and first_as_home):   # two seats with one home are said once, by _shared_homes
                problems.append(problem(source, None, "duplicate-root", f"{path} is listed twice as a project "
                                        f"({first}; and {listing}), so the first listing stands"))
            return
        seen[key] = (listing, as_home)
        out.append(_project(name, root, path, agents, by_email, problems))

    for n, root in enumerate(roots, 1):
        if not (isinstance(root, dict) and isinstance(root.get("name"), str) and isinstance(root.get("path"), str)):
            problems.append(problem(source, None, "bad-root", f"root {n} needs a name and a path"))
            continue
        if root.get("kind") != "repo":
            continue
        if root["path"].strip() == "{home}":
            for a in agents:
                if a["home"]:
                    add(f"{a['name']} home", root["name"], a["home"], f"{a['name']}'s home, by the root "
                        f"{root['name']}", True)
        else:
            path = _under(base, root["path"], source, f"the root {root['name']}", problems)
            if path:
                add(root["name"], root["name"], path, f"the root {root['name']}", False)
    return out


# ---- documents: <home>/cv/<project>/MASTER.md -----------------------------------------------------------------
def _plain(name: str) -> str:
    """"" when the name is one plain path segment; otherwise why not. A plain name has no separator, drive mark, "..",
    control character or leading dot, and at most 120 bytes; "hidden" is a leading dot. The same rule keeps a name from
    stepping out of the folder it is listed in."""
    if not name or len(name.encode("utf-8", "surrogatepass")) > 120:
        return "empty or over 120 bytes"
    if name.startswith("."):
        return "hidden"
    if ".." in name or any(c in "/\\:" or unicodedata.category(c) == "Cc" for c in name):
        return "not one plain segment"
    return ""


def _heading(text: str) -> str:
    """The first "# " heading, where a line starts with it (after a byte-order mark). "" if there is none or it is
    empty; a later heading does not stand in for an empty first one."""
    for line in text.split("\n"):
        line = line.lstrip("\ufeff")
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _folder(agent: dict, slug: str, path: str, problems: list) -> dict | None:
    """One cv/<project> folder as a document, or None (with the reason) when it holds no MASTER.md, or when it cannot be
    known whether it does. Only the plain files in it count, and every one of them dates it."""
    entries = _entries(path, problems, "whether it has a MASTER.md and which file is newest are unknown, and it is "
                                       "not shown")
    if entries is None:
        return None
    docs: list[dict] = []
    diagrams: list[str] = []
    master, title, newest = None, slug, 0
    skipped = ""   # why a file called MASTER.md was not used, when one was not
    for e in entries:
        st = _stat(e, problems)
        if st is None:
            if e.name.lower() == MASTER:
                skipped = "cannot be examined"
            continue
        if _linked(st):
            problems.append(problem(e.path, None, "link", "is a link, so it is not followed"))
            continue
        if not stat.S_ISREG(st.st_mode):
            continue
        why = _plain(e.name)
        if why:
            if why != "hidden":
                problems.append(problem(e.path, None, "name", f"is not a plain file name ({why}), so it is left out"))
            continue
        secs = max(0, st.st_mtime_ns // 1_000_000_000)   # your inbox counts nothing before 1970
        newest = max(newest, secs)
        low = e.name.lower()
        if low.endswith(".svg"):
            diagrams.append(e.name)
        elif low.endswith(".md"):
            if st.st_size > DOC_CAP:
                problems.append(problem(e.path, None, "too-big", f"is over {DOC_CAP // (1024 * 1024)} MB, so it is "
                                        f"not read"))
                if low == MASTER:
                    skipped = f"is over {DOC_CAP // (1024 * 1024)} MB"
                continue
            heading = _heading(_text(e.path, problems)) or e.name[:-3]
            if low == MASTER:
                master, title = e.name, heading
            else:
                docs.append({"file": e.name, "title": heading, "updated": _iso(secs)})
    if master is None:
        if skipped:   # the folder has a MASTER.md; the problem above says why it is not used
            problems.append(problem(path, None, "no-master", f"its MASTER.md {skipped}, so the folder is not shown"))
        else:
            problems.append(problem(path, None, "no-master", "it has no MASTER.md, so it is not shown"))
        return None
    return {"id": _node_id("document", agent["id"], _key(path) or path), "agent": agent["name"],
            "agent_id": agent["id"], "slug": slug, "title": title, "path": path, "updated": _iso(newest),
            "master": master, "docs": sorted(docs, key=lambda d: d["file"]), "diagrams": sorted(diagrams)}


def _shelf(agent: dict, problems: list) -> list[dict]:
    """The documents in one agent's <home>/cv/. A cv folder that is itself a link is not followed."""
    cv = os.path.join(agent["home"], CV)
    try:
        st = os.lstat(cv)
    except FileNotFoundError:
        return []
    except OSError as e:
        problems.append(problem(cv, None, "unreadable", f"cannot be examined: {e.strerror or e}"))
        return []
    if _linked(st):
        problems.append(problem(cv, None, "link", "is a link, so it is not followed"))
        return []
    if not stat.S_ISDIR(st.st_mode):
        problems.append(problem(cv, None, "shape", "is not a folder"))
        return []
    entries = _entries(cv, problems, "which projects it holds are unknown, and none of its documents is shown")
    if entries is None:
        return []
    out: list[dict] = []
    for e in entries:
        st = _stat(e, problems)
        if st is None:
            continue
        if _linked(st):
            problems.append(problem(e.path, None, "link", "is a link, so it is not followed"))
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue
        why = _plain(e.name)
        if why:
            if why != "hidden":
                problems.append(problem(e.path, None, "name", f"is not a plain folder name ({why}), so it is left out"))
            continue
        doc = _folder(agent, e.name, e.path, problems)
        if doc:
            out.append(doc)
    return out


# ---- the map's levels -----------------------------------------------------------------------------------------
def _member(agent: dict, basis: str) -> dict:
    return {"agent_id": agent["id"], "name": agent["name"], "basis": [basis], "emails": []}


def _levels(name, seats_key: str, agents: list[dict], projects: list[dict], documents: list[dict],
            measured, source, problems: list) -> dict:
    """The whole, under it a group for each agent's first group, under that one environment for each agent's home."""
    top = {"id": _node_id("whole", seats_key, name or ""), "kind": "whole", "name": name, "measured": measured,
           "members": [], "children": []}
    groups: dict[str, dict] = {}
    project_at = {}
    for p in projects:
        project_at.setdefault(_key(p["path"]), p["id"])
    for a in agents:
        parent = top
        if a["groups"]:
            g = a["groups"][0]
            if g not in groups:
                groups[g] = {"id": _node_id("group", seats_key, g), "kind": "group", "name": g, "measured": None,
                             "members": [], "children": []}
                top["children"].append(groups[g])
            groups[g]["members"].append(_member(a, "group"))
            a["placed"]["group"] = groups[g]["id"]
            parent = groups[g]
        else:
            problems.append(problem(source, None, "no-group", f"{a['name']} has no group, so it sits directly under "
                                    f"the top"))
        if not a["home"]:
            continue
        mine = [d for d in documents if d["agent_id"] == a["id"]]
        env = {"id": _node_id("environment", _key(a["home"]) or a["home"], a["name"]), "kind": "environment",
               "name": PurePath(a["home"]).name or a["name"], "path": a["home"], "measured": None,
               "updated": max((d["updated"] for d in mine), default=None), "documents": len(mine),
               "project_id": project_at.get(_key(a["home"])), "members": [_member(a, "home")], "children": []}
        parent["children"].append(env)
        a["placed"]["environment"] = env["id"]
    return top


# ---- the map file ---------------------------------------------------------------------------------------------
def _counts(data: dict) -> dict:
    """What the top level of the map holds: each list by its length, each record by the size of the lists and records
    inside it (a record's size is its number of keys)."""
    out: dict = {}
    for k, v in data.items():
        if isinstance(v, list):
            out[k] = len(v)
        elif isinstance(v, dict):
            out[k] = {kk: len(vv) for kk, vv in v.items() if isinstance(vv, (list, dict))}
    return out


def _short(text, limit: int = TITLE_LIMIT) -> str | None:
    """A map's own title for a group, cut at a word's end when it runs on: titles there can be paragraphs."""
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def _held(data: dict, key: str):
    """A list the map keeps at its top, or inside its "overlay"."""
    for holder in (data, data.get("overlay")):
        if isinstance(holder, dict) and isinstance(holder.get(key), list):
            return holder[key]
    return None


def _declared(sectors, source, problems: list) -> list[tuple[str, object]]:
    """The groups the map names itself, (name, title) in its order. A group with no name, or a name already given, is
    left out, and the problem counts them."""
    if sectors is None:
        return []
    if not isinstance(sectors, list):
        problems.append(problem(source, None, "shape", "'sectors' should be a list of groups"))
        return []
    out: list[tuple[str, object]] = []
    names: set[str] = set()
    for s in sectors:
        if isinstance(s, dict) and isinstance(s.get("sector"), str) and s["sector"] not in names:
            names.add(s["sector"])
            out.append((s["sector"], s.get("title")))
    if len(out) < len(sectors):
        problems.append(problem(source, None, "shape", f"{len(sectors) - len(out)} of the map's {len(sectors)} sectors "
                                f"have no name, or repeat one, so they are left out of its groups"))
    return out


def _map(path, problems: list) -> dict:
    """The map file summed up. It is read once and never written. `places` is how many entries its list of places
    holds, whatever the map says they are; `shapes` says how many carry each shape the map gives them (it calls some
    "not-a-place")."""
    p = _expand(path)
    out = {"off": False, "path": str(p), "measured": None, "file_updated": None, "places": None, "edges": None,
           "shapes": {}, "sectors": [], "top_level": {}}
    data = _json(p, MAX_MAP, problems, "the map")
    if data is None:
        return out
    if not isinstance(data, dict):
        problems.append(problem(p, None, "shape", "the map should be one JSON object"))
        return out
    try:
        out["file_updated"] = _iso(p.stat().st_mtime_ns // 1_000_000_000)
    except (OSError, ValueError):
        pass
    when = data.get("measured")
    if isinstance(when, str) and when.strip():
        out["measured"] = when.strip()
    else:
        problems.append(problem(p, None, "no-date", "the map does not say when it was measured (no 'measured' field)"))
    places, edges = _held(data, "places"), _held(data, "edges")
    for what, found in (("places", places), ("edges", edges)):
        if found is None:
            problems.append(problem(p, None, "shape", f"the map holds no list of {what} (at '{what}' or "
                                    f"'overlay.{what}')"))
    out["places"] = None if places is None else len(places)
    out["edges"] = None if edges is None else len(edges)
    out["shapes"] = dict(sorted(Counter(x["shape"] for x in places or []
                                        if isinstance(x, dict) and isinstance(x.get("shape"), str)).items()))
    declared = _declared(data.get("sectors"), p, problems)
    seen = Counter(x["sector"] if isinstance(x, dict) and isinstance(x.get("sector"), str) else None
                   for x in places or [])
    out["sectors"] = [{"name": n, "title": _short(t), "places": seen.pop(n, 0)} for n, t in declared] + \
                     [{"name": n, "title": None, "places": c} for n, c in seen.items()]
    out["top_level"] = _counts(data)
    return out


# ---- the source -----------------------------------------------------------------------------------------------
def _base(value, source, problems: list) -> str | None:
    """The seats file's base folder as a full path, or None (said) when what it holds is not one."""
    if value is None:
        return None
    full = _expand(value.strip()) if isinstance(value, str) and value.strip() else None
    if full is None or _unfit(str(full)) or not full.is_absolute():
        problems.append(problem(source, None, "shape", "'base' should be a full folder path"))
        return None
    return str(full)


def _seats(path, key: str, group: str | None, out: dict, problems: list) -> None:
    """Fill agents, projects and documents from the seats file, whose path as compared is `key`."""
    data = _json(path, MAX_SEATS, problems, "the seats file")
    if data is None:
        return
    source = _expand(path)
    if not isinstance(data, dict) or not isinstance(data.get("seats"), dict):
        problems.append(problem(source, None, "shape", "the seats file needs a 'seats' record of agents"))
        return
    base = _base(data.get("base"), source, problems)
    out["base"] = base
    agents = _agents(data["seats"], base, source, key, group, problems)
    by_email = _emails(agents, source, problems)
    _shared_homes(agents, source, problems)
    roots = data.get("roots")
    if roots is not None and not isinstance(roots, list):
        problems.append(problem(source, None, "shape", "'roots' should be a list of folders"))
        roots = []
    out["agents"] = agents
    out["projects"] = _projects(roots or [], agents, by_email, base, source, problems)
    docs = [d for a in agents if a["home"] for d in _shelf(a, problems)]
    out["documents"] = sorted(docs, key=lambda d: (d["agent"], d["slug"]))
    out["documents"].sort(key=lambda d: d["updated"], reverse=True)


def _setting(cfg: dict, key: str, problems: list) -> str | None:
    """A setting that should be text. Missing or empty is missing; anything else that is not text is said, and counts as
    missing too."""
    value = cfg.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    problems.append(problem("settings", None, "shape", f"'{key}' should be text, not {type(value).__name__}"))
    return None


def load(cfg: dict) -> dict:
    """Agents, projects, the map's levels, documents and the map file's summary, read from the files the settings name.

    The sources are "seats" (agents, projects, levels, documents) and "map" (the summary); "name" is the word at the top
    of the levels, and "group" keeps only the seats in that group. With neither source named, "off" is true; with one,
    "missing" says which is missing and its part is empty (the map's is {"off": True}). A setting that is not text is a
    problem and counts as missing. Whatever could not be used is in "problems", never dropped."""
    problems: list[dict] = []
    if not isinstance(cfg, dict):
        if cfg is not None:
            problems.append(problem("settings", None, "shape", "the settings should be a record of keys"))
        cfg = {}
    seats, mapfile = _setting(cfg, "seats", problems), _setting(cfg, "map", problems)
    name, group = _setting(cfg, "name", problems), _setting(cfg, "group", problems)
    missing = [k for k, v in (("seats", seats), ("map", mapfile)) if not v]
    out: dict = {"off": len(missing) == 2, "missing": missing, "name": name or None, "group": group or None,
                 "seats_file": seats or None, "base": None, "agents": [], "projects": [], "levels": None,
                 "documents": [], "map": {"off": True}, "problems": problems}
    if out["off"]:
        return out
    key = _key(_expand(seats or mapfile)) or str(seats or mapfile)   # what the whole is known by: the file defining it
    if mapfile:
        out["map"] = _map(mapfile, problems)
    if seats:
        _seats(seats, key, group or None, out, problems)
    out["levels"] = _levels(out["name"], key, out["agents"], out["projects"], out["documents"],
                            out["map"].get("measured"), seats, problems)
    return out


# ---- which project a card belongs to --------------------------------------------------------------------------
class _Project(NamedTuple):
    id: str
    path: str
    where: _Where


def _prepare(projects) -> list[_Project]:
    out = []
    for p in projects or []:
        where = _split(p.get("path")) if isinstance(p, dict) else None
        if where and isinstance(p.get("id"), str):
            out.append(_Project(p["id"], p["path"], where))
    return out


def _strings(card: dict):
    """(field, text) for each piece of the words an agent wrote to ask, in the order of TEXT_FIELDS, whatever order the
    card keeps its fields in. What was added to the card afterwards (its closing, its run, the line it came from) is not
    the agent's asking, so a path there places nothing."""
    def walk(value, field, depth):
        if isinstance(value, str):
            yield field, value
        elif depth < 4 and isinstance(value, dict):
            for v in value.values():
                yield from walk(v, field, depth + 1)
        elif depth < 4 and isinstance(value, (list, tuple)):
            for v in value:
                yield from walk(v, field, depth + 1)
    for field in TEXT_FIELDS:
        yield from walk(card.get(field), field, 0)


# Where a full path can start in a text, once its backslashes are slashes: a drive ("C:" and a slash), or a slash (two
# or more is a share's, one a POSIX path's) after the start, a space or one of the marks that open or join things.
_BREAKS = r"""\s"'`(\[{<>=,;|"""
_ANCHOR = re.compile(r"(?<![\w.~-])[A-Za-z]:(?=/)|(?<![^" + _BREAKS + r"])/+(?=[^/\s])")
# What can never be in a folder name, or ends a path in a command: the path stops there.
_STOP = re.compile(r"[\x00-\x1f\x7f\"<>|*?:;&]")
# "file:///C:/x", "file:///srv/x" and "file://host/share/x": the path inside, found as if the prefix were spaces.
_FILE_URL = re.compile(r"(?i)(?<![\w.~-])file:(?:/{2,3}(?=[A-Za-z]:/)|//(?=/[^/\s])|(?=//[^/\s]))")


def _written(text: str):
    """The full paths written in a text, as (position, root, folders, opened): `folders` are the names after the root as
    (text, closed) pairs with "." and ".." worked out, closed when a slash follows the name, and `opened` is the
    character just before the path. A path runs from its start to the next path's start or to a character no name can
    hold, so what follows the last name is open: the name may go on into words."""
    view = _FILE_URL.sub(lambda m: " " * len(m.group()), text.replace("\\", "/"))
    starts = [m.start() for m in _ANCHOR.finditer(view)]
    for n, at in enumerate(starts):
        drive = view[at] != "/"
        stop = _STOP.search(view, at + 2 if drive else at)
        end = min(starts[n + 1] if n + 1 < len(starts) else len(view), stop.start() if stop else len(view))
        run = view[at:end]
        if drive:
            root, rest = run[:2].casefold(), run[2:]
        else:
            lead = len(run) - len(run.lstrip("/"))
            root, rest = ("//" if lead > 1 else "/"), run[lead:]
        folders = _steps(rest.split("/"), _windows(root), 2 if root == "//" else 0)
        if folders or drive:
            yield at, root, folders, view[at - 1] if at else ""


def _prefix(raw: str, name: str, windows: bool) -> int | None:
    """How much of `raw` is the folder name `name`, or None when `raw` does not begin with it."""
    if not windows:
        return len(name) if raw.startswith(name) else None
    if not raw.casefold().startswith(name):
        return None
    for cut in range(1, len(raw) + 1):
        folded = raw[:cut].casefold()
        if folded == name:
            return cut
        if len(folded) > len(name):
            break
    return None


def _ends(rest: str, closed: bool, opened: str) -> bool:
    """Whether a folder name ends where `rest` (what follows the project's name, up to the next slash or the end of the
    path) begins. It does at the end; at a closing bracket; at a quote that closes the one the path was opened with; at
    sentence punctuation that is itself followed by the end, a space or a closing mark; and at a space, unless the one
    word after it is followed by a slash (then it is more of the name: "Proj Archive\\old.md" is not in "Proj"). Any
    other character goes on into a longer name."""
    if not rest:
        return True
    c = rest[0]
    if c.isspace():
        after = rest.lstrip()
        return not after or any(ch.isspace() for ch in after) or not closed
    if c in ")]}":
        return True
    if c in "'`":
        return c == opened
    if c in ".,!":
        tail = rest.lstrip(".,!")
        if not tail:   # at the end of the name: Windows drops dots from it, but a comma or a bang is part of a name
            return not closed or not rest.strip(".")
        return tail[0].isspace() or tail[0] in ")]}" or (tail[0] in "'`" and tail[0] == opened)
    return False


def _holds(p: _Project, folders: list[tuple[str, bool]], opened: str) -> bool:
    """Whether a written path, which has the project's own kind of root, lies in the project: every folder name of the
    project but the last is the same as the path's whole name, and the last one is reached at a boundary (see _ends)."""
    names = p.where.names
    if len(folders) < len(names):
        return False
    windows = _windows(p.where.root)
    if any(_fold(folders[i][0], windows) != name for i, name in enumerate(names[:-1])):
        return False
    if not names:
        return True
    raw, closed = folders[len(names) - 1]
    cut = _prefix(raw, names[-1], windows)
    return cut is not None and _ends(raw[cut:], closed, opened)


def _place(card, prepared: list[_Project]) -> dict:
    none = {"project": None, "via": None, "field": None, "path": None}
    if not isinstance(card, dict) or not prepared:
        return none
    cwd = _split(card["cwd"]) if isinstance(card.get("cwd"), str) else None
    if cwd:
        inside = [p for p in prepared if p.where.root == cwd.root and cwd.names[:len(p.where.names)] == p.where.names]
        if inside:
            best = max(inside, key=lambda p: len(p.where.names))
            return {"project": best.id, "via": "cwd", "field": "cwd", "path": best.path}
    # A drive's folders are never a share's or a POSIX path's, so a written path is compared only with projects of its own
    # kind of root (which also keeps a text of thousands of paths from being compared with every project).
    by_root: dict[str, list[_Project]] = {}
    for p in prepared:
        by_root.setdefault(p.where.root, []).append(p)
    first: dict[str, tuple[int, int, str]] = {}   # per project: the text it is first written in, where, its field
    for n, (field, text) in enumerate(_strings(card)):
        for at, root, folders, opened in _written(text):
            for p in by_root.get(root, ()):
                if p.id not in first and _holds(p, folders, opened):
                    first[p.id] = (n, at, field)
    if not first:
        return none
    by_id = {p.id: p for p in prepared}
    best_id = max(first, key=lambda i: (len(by_id[i].where.names), -first[i][0], -first[i][1]))
    return {"project": best_id, "via": "text", "field": first[best_id][2], "path": by_id[best_id].path}


def placement(card, projects) -> dict:
    """Where one card belongs and why: {"project": id or None, "via": "cwd" or "text" or None, "field": the card field
    the path was found in, "path": the project's path}. See assign for the rule."""
    return _place(card, _prepare(projects))


def assign(cards, projects) -> dict:
    """Which project each card belongs to: {project id: [card ids], "unassigned": [card ids]}.

    The rule is the plan's. A card belongs to the project its "cwd" lies in (the deepest, where several hold it), and
    that comes first: where a card ran outranks any path its words mention, even one in a deeper project. Only a card
    whose cwd is in no project is placed by the full paths written in the words the agent asked in (TEXT_FIELDS): to
    the deepest project that holds one of them, and at equal depth to the one written first (title before why, and so
    on down TEXT_FIELDS). A relative path says nothing.

    A path written in the words is read as Windows reads a path (a slash either way, any case on a drive or a share,
    "." and ".." worked out: "C:\\w\\x\\..\\Proj" is "C:\\w\\Proj" and "C:\\..\\w" is "C:\\w"), and it lies in a project
    only at a boundary of names: the project's last folder name must be followed by a slash, the end of the words, a
    closing bracket or quote, sentence punctuation, or a space that ends the path. So it is not in a longer name
    ("Proj-old", "Proj.md", "Proj(copy)", "Proj Archive\\old.md"), nor in another kind of path: a share's folders are
    not a drive's, and a POSIX path is not found inside either. A space ends the path unless the one word after it is
    followed by a slash; a folder named by two words after the project's own cannot be told from the words that
    follow, and counts as the words.

    Every project is a key, every card is in exactly one list, and a card with no id is listed as "#<its place in
    cards>", so the lists always add up to the number of cards given. A card that is not a record is unassigned."""
    ids = [p["id"] for p in projects or [] if isinstance(p, dict) and isinstance(p.get("id"), str)]
    if UNASSIGNED in ids:
        raise ValueError(f"a project cannot have the id {UNASSIGNED!r}")
    prepared = _prepare(projects)
    out: dict[str, list] = {i: [] for i in ids}
    out[UNASSIGNED] = []
    for n, card in enumerate(cards or [], 1):
        card_id = card.get("id") if isinstance(card, dict) else None
        out[_place(card, prepared)["project"] or UNASSIGNED].append(f"#{n}" if card_id in (None, "") else card_id)
    return out
