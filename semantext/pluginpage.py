"""The Plug-ins tab: every plug-in, where it came from, whether it is on, its health, its settings and what it reads;
and what the page may ask for, each recorded.

What the tab shows is read, never asked of a plug-in: the packages' metadata (registry.installed), the person's list
of what is on (plugins.json), each package's declaration file (manifest.py), the sources file, the tail of the change
log, and how each plug-in's last call ended in this process (outside.health). No read, build or resolve of any plug-in
is called to draw it, and the entry point of a plug-in that is off is never loaded. The page loads the plug-ins that
are on, as every other place of the page does, and that is all.

**The page proposes; the console applies** (the owner's choice). The page:
  - turns a plug-in off (plugins.json), recorded;
  - never turns one on: it shows the line to type, `semantext plugins enable <kind>.<name>`;
  - never writes a plug-in's settings. A change from the settings form, and a rollback of a settings change, is kept
    as a proposal, answered 202 (asking again for exactly an open one gives that one; a newer one for any of the same
    plug-in's keys supersedes the older), and the page shows the line to type, `semantext plugins confirm <n>`.
Open proposals are kept by number in PROPOSALS (plugin-proposals.json), with which superseded which, so one is found
however many records follow it in the log. A proposal is labelled for the person to read ("widens", "narrows",
"unknown", by the declarations' types); the label decides nothing.

**What confirm applies is shown exactly, or confirm refuses.** `confirm`, held to an interactive console as `enable`
is, shows the exact difference (difference(): every entry a list gains or loses, each in full; any other value whole,
before and after), every value rendered by exact(): JSON, with every character that does not show as itself (control,
format, bidi, separators, a run of spaces) written as an escape, never collapsed or cut. A review longer than
REVIEW_LINES is refused there, and read in full with `semantext plugins show <n> --full`, then applied with `confirm <n>
--reviewed-full`. It is applied under the lock only while the sources file is byte for byte what it was made on (its
sha256 and path), and no change has been recorded to its keys since (from LAST, never only the log's tail). A
superseded proposal is never applied in place of the one that took its place: both are named, and the newer is
confirmed by its own number, after its own review. Values a setting may not hold at all: control, format, bidi and
separator characters (whitespace is kept, and shown exactly).

**The console is the point of review.** `enable` shows, before the person types the name, exactly and uncut: every
setting the plug-in declares (with its value now, or its declared default when not set), every other key of the
sources file it may read without declaring it (a plug-in that is off cannot be asked: its code is not loaded), the
keys Semantext keeps for itself (refused to any plug-in), and every settings change recorded since it was last turned
off. The review is snapshotted (the sources file's sha256, the declaration file's sha256 and the package's version, and
the last recorded change to the plug-in and to each key it will be given, from LAST), and the plug-in is turned on
only if that snapshot still holds under the lock after the yes: a record touching neither (the page turning another
plug-in off, a proposal) never refuses it.

**Every change is recorded** in <home>/plugin-changes.jsonl, under one lock (LOCK, which every writer of plugins.json,
the sources file, the change log and LAST takes): who, what, the plug-in, the state before and after, and when. The
record, and LAST, are written and synced before the change is made, so no change stands unrecorded. A record is "not
applied" when the file it names does not now hold its "after", and no later record explains it (a kill between the
record and the change, or an edit by hand since). The log is bounded: one record at most MAX_RECORD bytes; at most
PAGE_RATE page requests a minute; rotated once at MAX_LOG (the rotated file is dropped at the next rotation); only its
last TAIL bytes are ever read. LAST (plugin-last-changes.json) keeps the last change to each key and each plug-in's on
or off, is never rotated, and is refused when it cannot be read, never reset. No file of this tab (the log, the rotated
log, LAST, PROPOSALS) is written unless it is one plain file with one name (_plain_file: never a link or junction, a
folder, or a second hard link, whose bytes an append would change too).

A KNOWN LIMIT (SECURITY.md, "Plug-ins"): a plug-in's page module runs in the page with the page's whole reach, so it
can do what the page can: turn plug-ins off and make proposals. It cannot apply one or turn a plug-in on. A
declaration is the package's word, not a fence.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
import threading
import time
import unicodedata
from collections import Counter
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import __version__, jsonread, manifest, outside, paths, pathrule, registry
from .store import Refused, file_lock, now, write_atomic

LOG = "plugin-changes.jsonl"
ROTATED = "plugin-changes.1.jsonl"
LAST = "plugin-last-changes.json"   # the last change to each key and plug-in: never rotated
LOCK = "plugins.lock"
KEY = re.compile(r"(?:" + "|".join(map(re.escape, registry.KINDS + registry.RESERVED)) + r")\." + registry.NAME.pattern)
WHO = ("page", "terminal")
WHAT = ("on", "off", "settings", "rollback", "proposed")
MAX_TEXT = 1000                 # characters of one text setting
MAX_ENTRIES = 200               # entries of one list setting (as the sources file keeps them)
MAX_RECORD = 64 * 1024          # bytes of one change record; a page change whose record would be larger is refused
MAX_LOG = 4 * 1024 * 1024       # bytes of the change log before it is rotated (one rotation kept)
TAIL = 512 * 1024               # bytes of the log's end that the tab and every act read
SHOWN = 200                     # records the tab shows, newest first
PAGE_RATE = 30                  # changes the page may make in PAGE_WINDOW seconds, per home
PAGE_WINDOW = 60.0
PROPOSAL_SECONDS = 3600         # a proposal not confirmed within this is expired
LOCK_SECONDS = 10.0             # how long a writer waits for another before it is refused
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
INVISIBLE = ("Cc", "Cf", "Zl", "Zp", "Co", "Cn")   # control (C1 too), format (zero-width, bidi), separators, unassigned
PROPOSALS = "plugin-proposals.json"           # the open proposals by number, and which superseded which
REVIEW_LINES = 60                             # a console review longer than this is refused here, and shown in full
KEEP_DONE = 200                               # superseded and confirmed proposals remembered, newest kept
_RECENT: dict[str, deque] = {}  # a home -> when the page's latest changes were asked for (time.monotonic)
_GATE = threading.Lock()


class AtTheTerminal(Refused):
    """A change the page does not make: turning a plug-in on, or widening what one reads. It carries the one line the
    person types at their own console instead, and, for a widening, the number of the proposal that line confirms."""

    def __init__(self, why: str, command: str, proposal: int | None = None):
        super().__init__(why)
        self.command, self.proposal = command, proposal


# ---- small things ---------------------------------------------------------------------------------------------------
WORD = re.compile(r"[A-Za-z0-9_.-]+")          # a word of the line as it is: a plug-in's name, a number, a verb
HOME_CHARS = re.compile(r"[A-Za-z0-9 \\/:._-]+")  # a home the line may show: no quote of any kind, no $ & | ^ % ! `


def _shell(shell: str | None) -> str:
    return shell or ("powershell" if os.name == "nt" else "posix")


def _not_default(home) -> bool:
    """Whether a home is not the default one (~/.semantext). With no system home to compare with, any home given is
    not the default: the line then carries --home, never a crash (a problem, never a failure)."""
    try:
        default = Path.home() / ".semantext"
    except (RuntimeError, KeyError, OSError):
        return True
    return os.path.normcase(os.path.abspath(home)) != os.path.normcase(os.path.abspath(default))


def command(home, *words, shell: str | None = None) -> str:
    """The exact line to type, holding no free text: `semantext`, then --home only when the page's home is not the
    default one AND is made of letters, digits, space and \\ / : . _ - alone (no quote of any kind: PowerShell takes
    the curly quotes U+2018 to U+201B for quotes too, and cmd.exe reads & | ^ % ! as its own), then `words`, each a
    plain word. A home of any other character is left out of the line (command_note says to type it in a console where
    the home is set). The line is for PowerShell on Windows and for a POSIX shell elsewhere; pasting into cmd.exe is not
    supported."""
    said = ["semantext"]
    home = Path(home) if home else paths.home()
    text = str(home)
    if _not_default(home) and HOME_CHARS.fullmatch(text):
        if _shell(shell) == "posix":   # quoted whenever it holds anything but a plain word: a backslash, a space
            said += ["--home", shlex.quote(text)]
        else:                          # PowerShell: a backslash is plain; a space is held in single quotes
            said += ["--home", "'" + text + "'" if " " in text else text]
    for w in words:
        if not WORD.fullmatch(str(w)):   # a planted number or name in a record: refused, said, never a crash
            raise Refused(f"a word of the line to type is a plain word, not this: {str(w)[:40]} (so no line is given)")
        said.append(str(w))
    return " ".join(said)


def command_note(home, shell: str | None = None) -> str:
    """What the page says beside every line to type: which shell it is for, and, when the home is left out of it, where
    to type it."""
    shell = _shell(shell)
    said = ("The lines to type are for PowerShell (pasting into cmd.exe is not supported)." if shell == "powershell"
            else "The lines to type are for a POSIX shell (sh, bash, zsh).")
    home = Path(home) if home else paths.home()
    if _not_default(home) and not HOME_CHARS.fullmatch(str(home)):
        said += (" Your Semantext home's path holds characters the line will not carry, so it is left out: type the "
                 "line in a console where SEMANTEXT_HOME names your home.")
    return said


def _key(key) -> tuple[str, str]:
    if type(key) is not str or not KEY.fullmatch(key):
        raise Refused("name the plug-in as <kind>.<name>, as `semantext plugins` lists it (the name letters, digits, "
                      "_ and -)")
    kind, _, name = key.partition(".")
    return kind, name


def _builtin(key: str) -> bool:
    from .sources import view   # here: the built-ins are the page's
    kind, _, name = key.partition(".")
    return view.BUILT_IN.get(kind, name) is not None


def _sources_file(home) -> Path:
    from .sources import view
    return view.config_file(home)


def _raw(path: Path) -> dict:
    """The sources file as a record, read strictly: one that cannot be read, gives a key twice, or is not a record is
    refused, so a change is never made over a file the page cannot read whole."""
    if not path.is_file():
        return {}
    try:
        data = jsonread.loads(path.read_text(encoding="utf-8-sig"), unique=True)
    except (OSError, ValueError) as e:
        raise Refused(f"your sources file cannot be read, so no setting is changed ({type(e).__name__})") from None
    if not isinstance(data, dict):
        raise Refused("your sources file is not a record, so no setting is changed")
    if _lone_surrogate(data):   # as the seats reader does: such a file could never be written back whole
        raise Refused("your sources file holds a lone surrogate (an escape such as \\ud800 that is no character), so "
                      "no setting is changed; take it out in your own editor")
    return data


def _lone_surrogate(v) -> bool:
    """Whether a value read from JSON holds a lone surrogate anywhere, in a key or a text, at any depth."""
    if isinstance(v, str):
        return any("\ud800" <= c <= "\udfff" for c in v)
    if isinstance(v, dict):
        return any(_lone_surrogate(k) or _lone_surrogate(x) for k, x in v.items())
    if isinstance(v, list):
        return any(_lone_surrogate(x) for x in v)
    return False


def _digest(path: Path) -> str:
    """The sources file's sha256 as it is now ("" when there is none): what a proposal is bound to."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


def _state(raw: dict, keys) -> dict:
    """The settings `keys` as they stand: {"values": {key: value}, "absent": [key, ...]}, each list sorted."""
    keys = sorted(set(keys))
    return {"values": {k: raw[k] for k in keys if k in raw}, "absent": [k for k in keys if k not in raw]}


def _keys_of(state: dict) -> list[str]:
    return sorted(set(state.get("values") or {}) | set(state.get("absent") or []))


def locked(home):
    """The one lock every writer of plugins.json, the sources file and the change log takes (the page's acts and the
    console's enable, disable and confirm). Not re-entrant: take it once, around the whole read, check and write."""
    return file_lock((Path(home) if home else paths.home()) / LOCK, LOCK_SECONDS)


def _gate(home) -> None:
    """At most PAGE_RATE proposals and rollbacks from the page in PAGE_WINDOW seconds, per home: each one is a record,
    so a page module sending them in a loop cannot grow the log faster than this. The page and every page module share
    it, so turning a plug-in OFF is not counted (it only ever takes reach away, and can happen at most once for each
    plug-in that is on): a module filling the limit can never keep you from turning it, or another, off."""
    with _GATE:   # the page's server answers on many threads at once: the count and the check are one act
        seen = _RECENT.setdefault(str(Path(home).resolve()) if home else "", deque())
        t = time.monotonic()
        while seen and t - seen[0] > PAGE_WINDOW:
            seen.popleft()
        if len(seen) >= PAGE_RATE:
            raise Refused(f"the page has asked for {PAGE_RATE} changes in the last {PAGE_WINDOW:g} s, the most it "
                          f"may; wait a minute and try again")
        seen.append(t)


# ---- the change log -------------------------------------------------------------------------------------------------
def log_file(home=None) -> Path:
    return (Path(home) if home else paths.home()) / LOG


def _problem(path, line, text) -> dict:
    return {"source": str(path), "line": line, "kind": "change log", "text": text[:300]}


def _tail(path: Path, size: int) -> tuple[bytes, bool]:
    """The last `size` bytes of a file, and whether that is the whole of it; only that much is ever read."""
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        start = max(0, end - size)
        f.seek(start)
        return f.read(end - start), start == 0


def _parse(line: str):
    try:
        r = jsonread.loads(line, unique=True)
    except ValueError:
        return None
    ok = (isinstance(r, dict) and type(r.get("n")) is int and r["n"] > 0 and r.get("who") in WHO
          and r.get("what") in WHAT and r.get("field") in ("on", "settings") and isinstance(r.get("plugin"), str)
          and "before" in r and "after" in r)
    if ok and r["field"] == "settings":   # a settings record says both states in full, or it is not one
        ok = all(isinstance(r[s], dict) and isinstance(r[s].get("values", {}), dict)
                 and isinstance(r[s].get("absent", []), list) for s in ("before", "after"))
    return r if ok else None


def _rotated_last(home) -> int:
    """The number of the last record of the rotated log, or 0: where the current log's numbers start from."""
    path = (Path(home) if home else paths.home()) / ROTATED
    if not path.is_file():
        return 0
    try:
        raw, _ = _tail(path, MAX_RECORD * 2)
    except OSError:
        return 0
    ns = [r["n"] for r in map(_parse, raw.decode("utf-8", "replace").split("\n")) if r]
    return ns[-1] if ns else 0


def changes(home=None) -> tuple[list[dict], list[dict]]:
    """The recorded changes in the last TAIL bytes of the log, oldest first, and a problem for each line that is not
    one. Numbers only ever go up (the first of the file above the rotated log's last); they may skip (a log moved aside
    and begun again goes on from the highest number known, never from 1). A number not above the one before it (an edit,
    a copy, a log put back) is a problem said aloud, and is not offered for a rollback. A line cut off at the end (a
    writer that died) is a problem, and the next record follows the last whole one."""
    path = log_file(home)
    if not path.is_file():
        return [], []
    try:
        raw, whole = _tail(path, TAIL)
    except OSError as e:
        return [], [_problem(path, None, f"the change log cannot be read ({type(e).__name__})")]
    lines = raw.decode("utf-8", errors="replace").split("\n")
    if not whole:
        lines = lines[1:]   # the first line in the window is likely cut by it
    out, problems = [], []
    last = _rotated_last(home) if whole else None
    for line in lines:
        if not line.strip():
            continue
        r = _parse(line)
        if r is None:
            problems.append(_problem(path, None, "a line of the change log is not a change record"))
            continue
        if last is not None and r["n"] <= last:
            problems.append(_problem(path, r["n"], f"change {r['n']} is not in its place in the log (its number does "
                                                   f"not go up from change {last}), so it is not used"))
            continue
        last = r["n"]
        out.append(r)
    return out, problems


def _plain_file(path: Path, name: str) -> None:
    """Refused unless what stands at `path` is nothing, or one plain file with one name: never a link or junction (a
    write would go where it leads), a folder, or a file with a second name on disk (a hard link: an append would
    change the other name's bytes too). The store's own checks (store._standing), for every file of this tab."""
    from .store import _standing   # here: the store's one judgement of what stands at a name
    what = _standing(path)
    if what:
        raise Refused(f"{name} is {what}, so nothing is written through it and no change is made; put a plain file "
                      f"there, or none")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return
    except (OSError, ValueError):
        raise Refused(f"{name} cannot be looked at, so no change is made") from None
    if st.st_nlink > 1:
        raise Refused(f"{name} has another name on disk (a hard link), so nothing is written through it and no change "
                      f"is made; put a plain file there, or none")


def _slot(home) -> tuple[int, bool]:
    """Where the next record goes (the caller holds the lock): the number of the last whole record, and whether the
    file ends in a cut-off line. Refused, before anything is changed, when the log or the rotated log is not one plain
    file with one name (_plain_file) or its end cannot be read, so a change is never made that could not be
    recorded."""
    path = log_file(home)
    _plain_file(path, LOG)
    _plain_file(path.with_name(ROTATED), ROTATED)
    last, torn = 0, False
    if path.is_file():
        raw, whole = _tail(path, MAX_RECORD * 2 + 16)
        torn = bool(raw) and not raw.endswith(b"\n")
        ns = [r["n"] for r in map(_parse, raw.decode("utf-8", "replace").split("\n")) if r]
        if not ns and raw.strip() and not (torn and raw.count(b"\n") == 0 and whole):
            raise Refused("the end of the change log cannot be read, so no change is made or recorded; move "
                          f"{LOG} aside, and a new one begins (its numbers go on from the highest known in {LAST} "
                          f"and {PROPOSALS}, never from 1)")
        last = ns[-1] if ns else (_rotated_last(home) if whole else 0)
    else:
        last = _rotated_last(home)
    return max(last, _known_max(home)), torn


def _known_max(home) -> int:
    """The highest record number LAST or the proposals' store knows: a record is never numbered at or below it, so a
    log moved aside never makes numbers start again from 1 (changed_while_off compares them)."""
    ns = [0]
    last = last_changes(home)
    for part in ("keys", "plugins"):
        ns += [r["n"] for r in last[part].values() if isinstance(r, dict) and type(r.get("n")) is int]
    try:
        store = _proposals_ok(home)
    except Refused:
        store = {"open": {}, "superseded": {}, "confirmed": {}}
    for part in ("open", "superseded", "confirmed"):
        ns += [number(k) for k in store[part] if number(k) is not None]
    ns += [s["by"] for s in store["superseded"].values() if isinstance(s, dict) and type(s.get("by")) is int]
    ns += [v for v in store["confirmed"].values() if type(v) is int]
    return max(ns)


def _prepare(home, rec: dict) -> tuple[int, bytes, dict]:
    """Everything an append needs, done before any change is made (the caller holds the lock): the record numbered one
    more than the last whole record and written out within MAX_RECORD, the log rotated when the record would take it
    past MAX_LOG, and the file opened for appending. (the open file, the bytes to write, the record); whatever of this
    fails, fails before anything is changed. LAST must be readable first (_last_ok): no record, a proposal's included,
    is appended while it cannot be, since numbering and staleness are read from it."""
    _last_ok(home)
    last, torn = _slot(home)
    if last + 1 > MAX_NUMBER:   # never a number number() would not read back: refused, not wrapped or widened
        raise Refused(f"numbering exhausted: the change log has reached record {MAX_NUMBER}, the last number it gives, "
                      f"so no change is recorded; move {LOG}, {LAST} and {PROPOSALS} aside to start again from 1")
    made = {**rec, "n": last + 1, "at": now()}
    data = (json.dumps(made, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if len(data) > MAX_RECORD:
        raise Refused(f"this change is {len(data) // 1024} KB written down, over the {MAX_RECORD // 1024} KB one record "
                      f"may be, so it is not made; change it in your sources file")
    path = log_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size + len(data) > MAX_LOG:
        os.replace(path, path.with_name(ROTATED))   # the one rotation kept; the one before it is let go
        torn = False
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0)
                 | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:   # looked at again as opened: something put at its name between the look and the open is not written
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink > 1:
            raise Refused(f"{LOG} changed as it was opened (it is not one plain file with one name), so no change is "
                          f"made")
        _plain_file(path, LOG)
    except BaseException:
        os.close(fd)
        raise
    return fd, (b"\n" if torn else b"") + data, made


def _write(fd: int, data: bytes) -> None:
    """The prepared bytes, written whole and synced; the file is closed whatever happens."""
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _size_ok(rec: dict) -> None:
    """Refuse, before anything is written, a change whose record could not be kept."""
    n = len((json.dumps({**rec, "n": 10 ** 9, "at": now()}, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    if n > MAX_RECORD:
        raise Refused(f"this change is {n // 1024} KB written down, over the {MAX_RECORD // 1024} KB one record may be, "
                      f"so it is not made; change it in your sources file")


# ---- judging a setting ----------------------------------------------------------------------------------------------
def _text(v, title: str) -> str:
    if type(v) is not str or not v.strip():
        raise Refused(f"{title} is a text that is not empty")
    if len(v) > MAX_TEXT or CONTROL.search(v):
        raise Refused(f"{title} is a text of at most {MAX_TEXT} characters, with no control characters")
    if any("\ud800" <= c <= "\udfff" for c in v):   # a lone surrogate: no file, record or answer can be written of it
        raise Refused(f"{title} holds a character that cannot be written as UTF-8 (a lone surrogate)")
    unseen = next((c for c in v if unicodedata.category(c) in INVISIBLE), None)
    if unseen is not None:   # shown or not, it would make the value read as something it is not
        raise Refused(f"{title} holds an invisible or direction-changing character (U+{ord(unseen):04X}), which a "
                      f"setting may not")
    return v.strip()


def _path(v, title: str) -> str:
    """A path setting as the page accepts it: refused, on every system alike so one value is judged the same
    everywhere, when Windows would read it apart from how it looks. That is: a device or verbatim prefix (\\\\?\\,
    \\\\.\\, \\??\\, with either slash in any mix: Windows reads / as \\ there); a ":" anywhere but after a drive letter
    (an alternate data stream, "x\\..:$DATA", names another file than its text); a part that is "." or "..", or ends in
    a dot or a space, which Windows trims ("x\\.. \\.." leaves x the way ".." does); and a part that is a device name
    (CON, NUL, COM1 ...), which opens the device, not a file."""
    v = _text(v, title)
    flat = v.replace("/", "\\")
    if flat.startswith(("\\\\?\\", "\\\\.\\", "\\??\\")):
        raise Refused(f"{title} is written without a \\\\?\\, \\\\.\\ or \\??\\ prefix")
    rest = flat[2:] if re.match(r"[A-Za-z]:\\", flat) else flat
    if ":" in rest:
        raise Refused(f"{title} has no ':' but the one after a drive letter")
    parts = [p for p in flat.split("\\") if p]
    if any(p in (".", "..") or p.endswith((".", " ")) for p in parts):
        raise Refused(f"{title} is written without . or .. and without a part that ends in a dot or a space")
    if any(pathrule.device(p) for p in parts):   # one shape with the path rule: "con .txt" is CON too
        raise Refused(f"{title} names a device (CON, NUL, COM1 ...), not a file or a folder")
    if not os.path.isabs(os.path.expanduser(v)):
        raise Refused(f"{title} is a full path")
    return v


def _plain(v, title: str):
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        raise Refused(f"each entry of {title} is a text or a number")
    if isinstance(v, str):
        return _text(v, title)
    if v != v or v in (float("inf"), float("-inf")):
        raise Refused(f"each entry of {title} is a number JSON can carry")
    return v


def check_value(setting: dict, v):
    """A value given for a setting, checked against its declared type: the value as it is kept, or Refused. None
    means the setting is taken out of the sources file."""
    if v is None:
        return None
    title, t = f"the setting {setting['key']!r}", setting["type"]
    if t == "text":
        return _text(v, title)
    if t == "path":
        return _path(v, title)
    if type(v) is not list or not v or len(v) > MAX_ENTRIES:
        raise Refused(f"{title} is a list of 1 to {MAX_ENTRIES} entries (null takes it out)")
    return [_path(x, title) if t == "paths" else _plain(x, title) for x in v]


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expanduser(p)))


def _within(child: str, parent: str) -> bool:
    a, b = _norm(child), _norm(parent)
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def inside(child: str, parent: str) -> bool:
    """Whether a path lies inside another, as written and with every link resolved (so a link inside the old folder
    that leads out of it is not inside)."""
    try:
        real = _within(os.path.realpath(os.path.expanduser(child)), os.path.realpath(os.path.expanduser(parent)))
    except (OSError, ValueError):
        return False
    return _within(child, parent) and real


def widens(setting: dict, before, after, absent_before: bool, absent_after: bool) -> bool:
    """Whether a change of one setting widens what the plug-in that declares it reads (manifest.py, the types). Taking
    it out widens unless the declaration gives a default that is not wider than the value taken out."""
    if absent_before and absent_after:
        return False
    if absent_after:
        if "default" not in setting:
            return True   # it may fall back to anything, wider included
        return widens(setting, before, setting["default"], False, False)
    if not absent_before and same(before, after):
        return False
    if setting["widens"]:
        return True
    if setting["type"] == "text":
        return False
    if absent_before:
        return True
    if setting["type"] == "list":   # what its entries mean is not known (they may be paths): a new entry widens
        return not (isinstance(before, list) and isinstance(after, list)   # as written: 1.0 is not 1 (never `in`)
                    and all(any(same(x, o) for o in before) for x in after))
    olds = [before] if setting["type"] == "path" else before
    news = [after] if setting["type"] == "path" else after
    if not isinstance(olds, list) or not all(type(o) is str for o in olds):
        return True   # the old value is not of the type: nothing is known to be inside it
    if not isinstance(news, list) or not all(type(x) is str for x in news):
        return True
    return not all(any(inside(n, o) for o in olds) for n in news)


# ---- who reads what -------------------------------------------------------------------------------------------------
def _found():
    found, problems = registry.installed()
    return {f"{i.kind}.{i.name}": i for i in found}, problems


def _declaration(i) -> tuple[dict | None, str | None]:
    return manifest.read(i.point, i.dist, f"{i.kind}.{i.name}")


def readers(found: dict, reg) -> dict[str, list[tuple[str, dict | None]]]:
    """Each settings key to every plug-in that reads it: (its "<kind>.<name>", its declared setting), the setting None
    when it is on and reads the key through its `keys` without declaring a type for it. `reg` is a registry with the
    plug-ins that are on loaded (registry.load_enabled): its outside entries' keys are read from their snapshot."""
    by: dict[str, list[tuple[str, dict | None]]] = {}
    declared_by: dict[str, set] = {}
    for pk, i in found.items():
        d, _ = _declaration(i)
        for s in (d or {}).get("settings") or []:
            by.setdefault(s["key"], []).append((pk, s))
            declared_by.setdefault(pk, set()).add(s["key"])
    for e in reg.entries() if reg is not None else ():
        if e.builtin:
            continue
        pk = registry.key(e.kind, e.name)
        for k in getattr(e.obj, "keys", ()) or ():
            if type(k) is str and k not in declared_by.get(pk, set()):
                by.setdefault(k, []).append((pk, None))
    return by


def _closures_here(path: Path, raw: dict) -> tuple[bool, set]:
    """Whether the sources file is also the person's closures file (its "closures_file" leads back to it, links
    resolved), and then the key the closures are read from there, in lower case (closed.py reads "closures_key"). The
    closures-file format is read only in a closures file, so format keys in the sources file itself do not make it
    one (closed.problems says they are not read)."""
    where = raw.get("closures_file")
    if type(where) is not str or not where.strip():
        return False, set()
    other = Path(os.path.expanduser(where.strip()))
    try:
        same = path.exists() and other.exists() and os.path.samefile(path, other)
    except OSError:
        same = False
    same = same or os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(other))
    key = raw.get("closures_key", "closed")
    return same, ({key.casefold()} if same and type(key) is str else set())


# ---- a proposal's label: for the person to read, deciding nothing -----------------------------------------------------
def label(by: dict, before: dict, after: dict) -> tuple[str, list[str]]:
    """How a settings change looks against the declarations (readers(found, None)): ("widens", reasons) when it is
    wider for some plug-in that declares a key it touches; ("unknown", reasons) when a key it touches has no declared
    type; ("order changed", reasons) when a list's entries change their order (first-match rules, an exclusion before
    an inclusion: what an order means is not known, so it is never "narrows"); else ("narrows", [...]). Shown on the
    page and at the console. It decides nothing: every settings change is a proposal, applied only at the console."""
    wide, unknown, order = [], [], []
    for k in _keys_of(after):
        b_abs, a_abs = k in before["absent"], k in after["absent"]
        b, a = before["values"].get(k), after["values"].get(k)
        if (b_abs and a_abs) or (not b_abs and not a_abs and same(b, a)):
            continue
        if order_changed(b, a):
            order.append(f"{k}: the order of its entries changed (meaning unknown)")
        typed = [(pk, s) for pk, s in by.get(k) or [] if s is not None]
        if not typed:
            unknown.append(f"{k}: no plug-in declares a type for it")
        for pk, s in typed:
            if widens(s, b, a, b_abs, a_abs):
                wide.append(f"{k}: wider for {pk}" + (" (it may fall back to a wider default)" if a_abs else ""))
    if wide:
        return "widens", wide + order + unknown
    if order:
        return "order changed", order + unknown
    if unknown:
        return "unknown", unknown
    return "narrows", ["no plug-in that declares these keys reads more (one may read a key without declaring it)"]


def order_changed(b, a) -> bool:
    """Whether two lists keep their common entries in a different order (entries only added at the end, or only taken
    out, keep it)."""
    if not (isinstance(b, list) and isinstance(a, list)):
        return False
    eb, ea = [exact(x) for x in b], [exact(x) for x in a]
    return _common(eb, Counter(ea)) != _common(ea, Counter(eb))


def _common(seq: list, other: Counter) -> list:
    """seq with each entry kept only as many times as it is in other (its first ones)."""
    left, out = Counter(other), []
    for x in seq:
        if left[x] > 0:
            left[x] -= 1
            out.append(x)
    return out


# ---- the one write path ---------------------------------------------------------------------------------------------
def _expired(r: dict) -> bool:
    try:
        return datetime.now(timezone.utc) >= datetime.fromisoformat(str(r.get("expires")).replace("Z", "+00:00"))
    except ValueError:
        return True


def reserved_keys(home) -> set:
    """The keys no plug-in's setting may be, in lower case: the frame's and every built-in reader's, every key the
    closures are read from (manifest.CLOSURE_KEYS, always, used or not), and the keys closures_key and
    closures_names_key name when the sources file names them (under any case of those two). registry.load_enabled
    refuses a plug-in whose keys name any of them, as the page does."""
    out = {r.casefold() for r in manifest.reserved()}
    try:
        raw = _raw(_sources_file(home))
    except Refused:
        raw = {}
    if isinstance(raw, dict):
        # the keys closed.py reads, found as closed.py finds them (closed.keys_named), each in lower case
        from .sources import closed
        out.update(k.casefold() for k in closed.keys_named(raw) if type(k) is str)
    naming = {k.casefold() for k in manifest.NAMING_KEYS}
    for field, named in raw.items():
        if field.casefold() in naming and type(named) is str and named.strip():
            # closed.py looks the named key up exactly as written; it is reserved both as written and trimmed, so a
            # space before or after it never lets a setting land on the key the closures are read from
            out.add(named.casefold())
            out.add(named.strip().casefold())
    return out


def _no_reserved(home, keys) -> None:
    taken = sorted(k for k in keys if type(k) is str and k.casefold() in reserved_keys(home))
    if taken:
        raise Refused(f"{taken[0]!r} is a key of Semantext's own or of your closures, so no plug-in's setting is "
                      f"changed there, whatever a record or a proposal says")


def _apply(home, field: str, plugin: str, after) -> None:
    if field == "on":
        on, trouble = registry.enabled(home)
        if trouble:
            raise Refused(trouble[0]["text"])
        if after is None:
            on.pop(plugin, None)
        else:
            on[plugin] = after
        registry.write_enabled(on, home)
        outside.forget(plugin)   # turned on or off: its health starts again from nothing
        return
    path = _sources_file(home)
    text = _new_sources(home, after)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path, text)


def _new_sources(home, after: dict) -> str:
    """The whole sources file as a settings change would write it, refused unless every character of it can be
    written (encoded as UTF-8): made before the record, so a change that could not be written is never recorded."""
    new = dict(_raw(_sources_file(home)))
    for k in after["absent"]:
        new.pop(k, None)
    new.update(after["values"])
    text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused("your sources file could not be written whole with this change (it would hold a lone "
                      "surrogate), so nothing is changed") from None
    return text


def _make(home, who: str, what: str, field: str, plugin: str, before, after, **more) -> dict:
    """The one way a change is made, with the lock held by the caller. From the page it is only turning a plug-in off;
    every other change is the console's. The record is written and synced first, then LAST, then the change: if the
    record or LAST cannot be written, nothing is changed. A kill after the record and before the change leaves a
    record the tab shows "not applied" (the file it names does not now hold its "after")."""
    if who == "page" and not (field == "on" and after is None):
        raise Refused("the page turns a plug-in off and proposes; it changes nothing else")
    if field == "settings":   # whatever a record or a proposal says, these keys are never written here
        _no_reserved(home, _keys_of(after) + _keys_of(before if isinstance(before, dict) else {}))
        _new_sources(home, after)   # the whole new file can be written, checked before the record
    rec = {"who": who, "what": what, "field": field, "plugin": plugin, "before": before, "after": after, **more}
    _size_ok(rec)
    keep = _last_ok(home)                  # LAST readable, and no link, before anything is written
    fd, data, made = _prepare(home, rec)
    _write(fd, data)                       # the record first
    _keep_last(home, made, keep)           # then LAST, in the same order
    _apply(home, field, plugin, after)     # then the change; failing (or killed) here: "not applied"
    return made


def last_file(home=None) -> Path:
    return (Path(home) if home else paths.home()) / LAST


def last_changes(home=None) -> dict:
    """The last change made to each setting key, and the last turning on or off of each plug-in: kept in LAST, which is
    never rotated, so they outlive the log's rotation. {"keys": {key: record}, "plugins": {plugin: record}}, each
    record cut to that key's (or that plug-in's) part. {} parts when the file is missing or cannot be read."""
    try:
        data = jsonread.loads(last_file(home).read_text(encoding="utf-8"), unique=True)
    except (OSError, ValueError):
        return {"keys": {}, "plugins": {}}
    ok = isinstance(data, dict) and isinstance(data.get("keys"), dict) and isinstance(data.get("plugins"), dict)
    return data if ok else {"keys": {}, "plugins": {}}


def _last_ok(home) -> dict:
    """LAST as it stands, for a write: refused when it is a link, or exists and cannot be read as LAST, since writing
    it then would throw its history away. Missing is empty."""
    path = last_file(home)
    _plain_file(path, LAST)
    if not path.exists():
        return {"keys": {}, "plugins": {}}
    try:
        data = jsonread.loads(path.read_text(encoding="utf-8"), unique=True)
    except (OSError, ValueError):
        data = None
    if not (isinstance(data, dict) and isinstance(data.get("keys"), dict) and isinstance(data.get("plugins"), dict)):
        raise Refused(f"{LAST} cannot be read, so no change is made (writing it would lose the last change to each "
                      f"setting it keeps); move it aside to start a new one")
    return data


def _keep_last(home, made: dict, keep: dict) -> None:
    """Note a made change in LAST: one entry per settings key, one per plug-in turned on or off, so the file is bounded
    by how many keys and plug-ins there are, never by how many changes."""
    slim = {k: made[k] for k in ("n", "at", "who", "what", "field", "plugin") if k in made}
    if made["field"] == "on":
        keep["plugins"][made["plugin"]] = {**slim, "before": made["before"], "after": made["after"]}
    else:
        for k in _keys_of(made["after"]):
            keep["keys"][k] = {**slim, "before": _part(made["before"], k), "after": _part(made["after"], k)}
    write_atomic(last_file(home), json.dumps(keep, ensure_ascii=False, sort_keys=True) + "\n")


def _part(state, k: str) -> dict:
    state = state if isinstance(state, dict) else {}
    values = state.get("values") or {}
    return {"values": {k: values[k]} if k in values else {}, "absent": [k] if k in (state.get("absent") or []) else []}


class Proposed(AtTheTerminal):
    """A settings change the page asked for, recorded as proposal `proposal`: not refused, and not made. The server
    answers it 202 Accepted with the line that applies it at the console."""


# ---- the open proposals, by number ---------------------------------------------------------------------------------
def proposals_file(home=None) -> Path:
    return (Path(home) if home else paths.home()) / PROPOSALS


def _proposals_ok(home) -> dict:
    """PROPOSALS as it stands: {"open": {n: record}, "superseded": {n: {"by", "at", "who", "made_by", "made_at"}},
    "confirmed": {n: m}}.
    Refused when it is a link, or exists and cannot be read (it is never reset: that would lose which proposals are
    open). Missing is empty. Its size is bounded: open proposals by the plug-ins' declared keys (each new one supersedes
    every open one of the same plug-in it shares a key with), the rest to KEEP_DONE each."""
    path = proposals_file(home)
    _plain_file(path, PROPOSALS)
    if not path.exists():
        return {"open": {}, "superseded": {}, "confirmed": {}}
    try:
        data = jsonread.loads(path.read_text(encoding="utf-8"), unique=True)
    except (OSError, ValueError):
        data = None
    if not (isinstance(data, dict) and all(isinstance(data.get(k), dict) for k in ("open", "superseded", "confirmed"))):
        raise Refused(f"{PROPOSALS} cannot be read, so no proposal is made or applied (writing it would lose which are "
                      f"open); move it aside to start a new one")
    bad = next((k for part in ("open", "superseded", "confirmed") for k in data[part] if number(k) is None), None)
    if bad is not None:   # a number is ASCII digits alone: "²" or "١" would be taken by isdigit() or int(), not here
        raise Refused(f"{PROPOSALS} names a proposal {bad!r}, which is not a number in ASCII digits, so no "
                      f"proposal is made or applied; move it aside to start a new one")
    return data


def _keep_proposals(home, store: dict) -> None:
    for part in ("superseded", "confirmed"):   # the oldest go first, by NUMBER (as text, "1000" sorts before "801")
        while len(store[part]) > KEEP_DONE:
            del store[part][min(store[part], key=lambda k: -1 if number(k) is None else number(k))]
    write_atomic(proposals_file(home), json.dumps(store, ensure_ascii=False, sort_keys=True) + "\n")


def open_proposals(home=None) -> dict:
    """The open proposals by number (as text), for the tab: {} when the store cannot be read."""
    try:
        return _proposals_ok(home)["open"]
    except Refused:
        return {}


def _propose(home, plugin: str, before: dict, after: dict, by: dict, **more) -> dict:
    """The open proposal for exactly this change; or a new one, labelled, bound to the sources file as it is now, which
    supersedes every open proposal of the same plug-in that shares a key with it (each named in the store with what
    superseded it, so the person is told, and never given the new one in its place)."""
    store = _proposals_ok(home)
    path = _sources_file(home)
    digest = _digest(path)
    for k, r in list(store["open"].items()):
        if _expired(r):
            del store["open"][k]
    found = next((r for r in store["open"].values() if r["plugin"] == plugin and same(r["before"], before)
                  and same(r["after"], after) and r.get("sources_sha256") == digest
                  and same(r.get("rolls_back"), more.get("rolls_back"))), None)
    if found is not None:
        return found
    lab, why = label(by, before, after)
    rec = {"who": "page", "what": "proposed", "field": "settings", "plugin": plugin, "before": before, "after": after,
           "label": lab, "reasons": why, "sources_sha256": digest, "sources_file": str(path),
           "expires": (datetime.now(timezone.utc) + timedelta(seconds=PROPOSAL_SECONDS)).strftime(
               "%Y-%m-%dT%H:%M:%SZ"), **more}
    _size_ok(rec)
    fd, data, made = _prepare(home, rec)
    _write(fd, data)
    keys = set(_keys_of(after))
    for k, r in list(store["open"].items()):
        if r["plugin"] == plugin and keys & set(_keys_of(r["after"])):
            del store["open"][k]
            store["superseded"][k] = {"by": made["n"], "at": made["at"], "who": "page",
                                      "made_by": r.get("who"), "made_at": r.get("at")}
    store["open"][str(made["n"])] = made
    _keep_proposals(home, store)
    return made


# ---- what the console shows before its yes: exactly what it applies -------------------------------------------------
SHOW = 200          # characters of one value the PAGE shows (its display only; nothing a yes depends on is cut)
SHOW_LINE = 300
SHOW_CHANGES = 20


WIDTH = 100   # columns a review line is wrapped at when its rows are counted against REVIEW_LINES


def _escape(c: str) -> str:
    return f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}"


def exact(v) -> str:
    """A value exactly as it is written, in printable ASCII alone: JSON, with every character outside U+0020 to U+007E
    written as its escape (\\uXXXX, or \\UXXXXXXXX past U+FFFF), and every space of a run of two or more as \\u0020
    (so a value can never wrap into a line of its own). So two values that differ are never shown alike: a Cyrillic o
    is \\u043e, a Hangul filler \\u3164, a combining stroke \\u0338, a right-to-left letter its code, never itself.
    Exact and unambiguous rather than pretty; never collapsed or cut."""
    text = json.dumps(v, ensure_ascii=False)
    out = []
    for i, c in enumerate(text):
        run = c == " " and (text[i - 1:i] == " " or text[i + 1:i + 2] == " ")
        out.append(_escape(c) if run or not " " <= c <= "~" else c)
    return "".join(out)


def ascii_only(text) -> str:
    """The one renderer of text on the console (plugincmd.shown() is it): printable ASCII alone, one to one. The
    backslash is written \\\\, every character outside U+0020 to U+007E its escape (\\uXXXX, or \\UXXXXXXXX), and a
    space that begins or ends the text, or is one of a run, \\u0020; so two different texts are never rendered alike
    (a Cyrillic es is \\u0441, the six characters backslash-u-0-4-4-1 are \\\\u0441), and none can pass for the
    indentation around it. Nothing is deleted or cut. A value is rendered by exact(), whose JSON writes the backslash
    the same way."""
    text = str(text)
    out = []
    for i, c in enumerate(text):
        edge = c == " " and (i == 0 or i == len(text) - 1 or text[i - 1] == " " or text[i + 1] == " ")
        out.append("\\\\" if c == "\\" else _escape(c) if edge or not " " <= c <= "~" else c)
    return "".join(out)


class Rendered(str):
    """A console line already rendered (its texts by ascii_only, its values by exact): what plugincmd.shown() prints
    as it is, never rendered twice. Made only by _line(), which refuses anything but printable ASCII."""


def _line(text: str) -> Rendered:
    if any(not " " <= c <= "~" for c in text):
        raise ValueError(f"a review line was built from a text not rendered: {ascii(text)}")
    return Rendered(text)


def _r(x) -> str:
    """A text inside a review line, rendered: a name, a key, a path, a time, a reason."""
    return ascii_only("" if x is None else x)


NUMBER = re.compile(r"[0-9]{1,18}", re.ASCII)   # a record's number as text: ASCII digits only ("²" and "١" are not)
MAX_NUMBER = 10 ** 18 - 1                        # the last number given: the next is refused, "numbering exhausted"


def number(text) -> int | None:
    """A record number written as text, or None: ASCII digits alone, never what str.isdigit() or int() also take
    (superscripts, other scripts' digits, spaces, signs, underscores)."""
    return int(text) if type(text) is str and NUMBER.fullmatch(text) else None


def width() -> int:
    """The width a review is counted at: console_width(), held here so tests can fix it at one place."""
    return console_width()


def console_width() -> int:
    """The console's width in columns, as rows are counted at it: COLUMNS or the terminal's (shutil), never wider than
    the real terminal when standard output is one (a COLUMNS above it would count fewer rows than are shown), and
    WIDTH when it cannot be told. Never raised to a floor: a console under MIN_WIDTH is counted at its own width (and
    so refuses all but the shortest review), never at a wider one."""
    import shutil
    import sys
    try:
        cols = shutil.get_terminal_size((WIDTH, 24)).columns
    except (OSError, ValueError):
        cols = WIDTH
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            real = os.get_terminal_size(sys.stdout.fileno()).columns
            if real > 0:
                cols = min(cols, real)
    except (OSError, ValueError, AttributeError):
        pass
    return cols if cols > 0 else WIDTH


def rows(lines: list[str], width: int = WIDTH) -> int:
    """How many screen rows the lines take, each wrapped at `width` columns: what REVIEW_LINES is measured in, so one
    long line of a whole list counts as the many rows it fills."""
    return sum(max(1, -(-len(line) // width)) for line in lines)


def same(a, b) -> bool:
    """Whether two values are the same as written: their JSON, keys sorted. Never Python's ==, under which True, 1 and
    1.0 are equal; a change from one to another is a change."""
    def text(v):
        return json.dumps(v, ensure_ascii=True, sort_keys=True, default=repr)
    return text(a) == text(b)


def review_code(lines: list[str], *bound) -> str:
    """The short code `show --full` prints and `--reviewed-full` must give back: the first 8 hex of the sha256 of the
    review exactly as shown and of what it is bound to (the proposal and the sources file's sha256, or the plug-in and
    its enable snapshot). A wrong code, or one of a review that has changed since, refuses."""
    text = "\n".join(lines) + "\n" + json.dumps(bound, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def shown_value(v) -> str:
    """A value as the PAGE's display shows it: exact, then cut at SHOW characters. Never used for a console yes."""
    text = exact(v)
    return text if len(text) <= SHOW else text[:SHOW] + f"…({len(text) - SHOW} more)"


def _whole(word: str, has: bool, v) -> list[str]:
    """One side of a change, whole: a list one numbered entry a line, anything else on its own line."""
    if not has:
        return [f"    {word}: (not set)"]
    if isinstance(v, list):
        return [f"    {word}: a list of {len(v)}" + (":" if v else "")] + \
            [f"      {i}. {exact(x)}" for i, x in enumerate(v, 1)]
    return [f"    {word}: {exact(v)}"]


def difference(before: dict, after: dict) -> list[str]:
    """The exact difference a change makes, key by key, nothing cut, every value in printable ASCII (exact). Only two
    list changes are shown as their parts: entries added at the end alone ("+ put in", with each one's place), and
    entries taken out alone, the rest kept in order ("- taken out"). Any other list change (an order changed at all,
    or entries both added and taken out) shows the WHOLE list before and the WHOLE list after, numbered entry by entry,
    since what an order means is not known; so does a list set for the first time, or taken out. Anything else is its
    whole old and new value."""
    out = []
    for key in _keys_of(after):
        k = _r(key)
        b_has, a_has = key in (before.get("values") or {}), key in (after.get("values") or {})
        b, a = (before.get("values") or {}).get(key), (after.get("values") or {}).get(key)
        if b_has and a_has and isinstance(b, list) and isinstance(a, list):
            gone = Counter(exact(x) for x in b) - Counter(exact(x) for x in a)
            if [exact(x) for x in a[:len(b)]] == [exact(x) for x in b]:   # as written, never == (True == 1 == 1.0)
                out.append(f"  {k}: a list of {len(b)} becomes a list of {len(a)}, entries only added at the end")
                out += [f"    + put in, as entry {i}: {exact(x)}" for i, x in enumerate(a[len(b):], len(b) + 1)]
                continue
            if not order_changed(b, a) and not Counter(exact(x) for x in a) - Counter(exact(x) for x in b):
                out.append(f"  {k}: a list of {len(b)} becomes a list of {len(a)}, entries only taken out, the rest "
                           f"in the same order")
                out += [f"    - taken out: {x}" for x, c in gone.items() for _ in range(c)]
                continue
            how = "its order changed (meaning unknown)" if order_changed(b, a) else "entries both added and taken out"
            out.append(f"  {k}: {how}; the whole list before and after:")
        else:
            out.append(f"  {k}:")
        out += _whole("was", b_has, b) + _whole("now", a_has, a)
    return [_line(x) for x in out]


def _who(r: dict) -> str:
    return "this page" if r.get("who") == "page" else "the terminal"


def changed_while_off(home, key: str) -> list[dict]:
    """Every settings change recorded since `key` was last turned off, or ever when it was never on, to ANY key: a
    plug-in that is off cannot be asked which keys it reads. From the log's tail and, past it, from LAST. One entry per
    key changed: {"n", "at", "who", "key", "before", "after"} (each that key's part of the state), oldest first."""
    recs, _ = changes(home)
    last = last_changes(home)
    marks = [r["n"] for r in recs if r["field"] == "on" and r["plugin"] == key and r["what"] != "proposed"]
    kept = last["plugins"].get(key)
    if isinstance(kept, dict) and type(kept.get("n")) is int:
        marks.append(kept["n"])
    since = max(marks, default=0)
    out: dict = {}
    for r in recs:
        if r["n"] <= since or r["what"] == "proposed" or r["field"] != "settings":
            continue
        for k in _keys_of(r["after"]):
            out[(r["n"], k)] = {"n": r["n"], "at": r.get("at"), "who": _who(r), "key": k,
                                "before": _part(r.get("before"), k), "after": _part(r["after"], k)}
    for k, r in last["keys"].items():
        if isinstance(r, dict) and type(r.get("n")) is int and r["n"] > since and (r["n"], k) not in out:
            out[(r["n"], k)] = {"n": r["n"], "at": r.get("at"), "who": _who(r), "key": k,
                                "before": _part(r.get("before"), k), "after": _part(r.get("after"), k)}
    return [out[x] for x in sorted(out)]


def _declaration_sha(i) -> str:
    """The declaration file's sha256 ("" when it ships none, "unreadable" when it cannot be found or read)."""
    try:
        where = manifest.locate(i.point, i.dist)
        return hashlib.sha256(Path(where).read_bytes()).hexdigest() if where else ""
    except Exception:  # noqa: BLE001  a declaration that cannot be found is a state of its own, compared as such
        return "unreadable"


def enable_snapshot(home, key: str) -> tuple:
    """What the enable review was shown from: the sources file's sha256, the plug-in's declaration file's sha256 and
    its package's version, and the last recorded change to the plug-in and to each key it will be given (to every key,
    when it declares none), from LAST. A record that touches neither (the page turning another plug-in off, a proposal)
    changes none of it, so it never refuses the yes."""
    found, _ = _found()
    i = found.get(key)
    declared, _ = _declaration(i) if i is not None else (None, None)
    keys = {s["key"] for s in (declared or {}).get("settings") or []} or None
    last = last_changes(home)
    touched = sorted((k, r.get("n")) for k, r in last["keys"].items() if keys is None or k in keys)
    plugin = (last["plugins"].get(key) or {}).get("n")
    return (_digest(_sources_file(home)), _declaration_sha(i) if i is not None else None,
            (i.origin, i.version) if i is not None else None, plugin, tuple(touched))


def enable_review(home, key: str, declared: dict | None) -> list[str]:
    """What the console shows before the person types a plug-in's name to turn it on, every line true and every value
    exact (nothing cut): the settings it declares, as the sources file holds them now (or the declared default it then
    reads); every other key of the sources file, which it may read without declaring it (it is off, so it cannot be
    asked); the keys Semantext keeps for itself, which no plug-in is given; and every settings change recorded since it
    was last turned off. Longer than REVIEW_LINES, it is refused at enable and shown by `semantext plugins show`."""
    path = _sources_file(home)
    raw = _raw(path)
    settings = (declared or {}).get("settings") or []
    mine = {s["key"] for s in settings}
    lines = [f"Sources file: {_r(path)}"]
    if settings:
        lines.append("It declares these settings, and will be given them as your sources file holds them now:")
        for s in settings:
            if s["key"] in raw:
                lines += _value_lines(f"  {_r(s['key'])} =", raw[s["key"]])
            elif "default" in s:
                lines += _value_lines(f"  {_r(s['key'])}: not set; it then reads its declared default", s["default"])
            else:
                lines.append(f"  {_r(s['key'])}: not set")
    else:
        lines.append("It declares no settings.")
    reserved = reserved_keys(home)
    others = [k for k in raw if k not in mine and k.casefold() not in reserved]
    if others:
        lines.append(f"It may also read settings it has not declared (a plug-in that is off cannot be asked which). "
                     f"These {len(others)} keys of your sources file are not among its declared ones:")
        for k in others:
            lines += _value_lines(f"  {_r(k)} =", raw[k])
    kept = [k for k in raw if k.casefold() in reserved]
    if kept:
        lines.append("Kept by Semantext, refused to any plug-in (one whose keys name them is never loaded): "
                     + ", ".join(_r(k) for k in kept))
    seen = changed_while_off(home, key)
    if seen:
        lines.append(f"Settings changed since it was last turned off ({len(seen)}), to any key:")
        for c in seen:
            k = c["key"]
            lines.append(f"  change {_r(c['n'])}, {_r(c['at'])}, by {_r(c['who'])}: {_r(k)}")
            lines += _whole("was", k in c["before"]["values"], c["before"]["values"].get(k))
            lines += _whole("now", k in c["after"]["values"], c["after"]["values"].get(k))
    else:
        lines.append("No settings change is recorded since it was last turned off.")
    return [_line(x) for x in lines]


def _value_lines(head: str, v) -> list[str]:
    """A value under a heading: a list one numbered entry a line, anything else after the heading."""
    if isinstance(v, list):
        return [f"{head} a list of {len(v)}" + (":" if v else "")] + [f"      {i}. {exact(x)}" for i, x in enumerate(v, 1)]
    return [f"{head} {exact(v)}"]


def confirm_review(home, r: dict) -> list[str]:
    """What the console shows before a proposal is applied: the sources file, who proposed it and when, its exact
    difference against the file as it is now (proposal() has checked the file still holds its "before"), and its label
    worked out again now from the declarations (it decides nothing)."""
    lines = [f"Sources file: {_r(_sources_file(home))}",
             f"Proposal {_r(r['n'])} for {_r(r['plugin'])}, made by {_who(r)} at {_r(r.get('at'))}. Exactly what it "
             f"changes:"]
    return [_line(x) for x in lines] + difference(r["before"], r["after"]) + [label_now(r)]


def label_now(r: dict) -> Rendered:
    """The proposal's label worked out again now from the declarations, as one rendered line: shown by confirm and by
    show, and so covered by the review code."""
    found, _ = _found()
    lab, why = label(readers(found, None), r["before"], r["after"])
    return _line(f"As things stand now it {_r(lab)}: " + "; ".join(_r(w) for w in why))


MIN_WIDTH = 20   # under this the head of a review says so plainly: it is counted at its own width all the same


def narrow_note(cols: int) -> list[Rendered]:
    """The line said at the head of a review when the console is narrower than WIDTH columns."""
    if cols >= WIDTH:
        return []
    if cols < MIN_WIDTH:
        return [_line(f"Your console is {cols} columns wide, under {MIN_WIDTH}: this review is counted at {cols}, "
                      f"so all but the shortest is refused here; widen it, or read it with show --full.")]
    return [_line(f"Your console is {cols} columns wide, narrower than {WIDTH}: this review is measured at {cols}, "
                  f"so it is refused here sooner.")]


def too_long(lines: list[str], what: str, show: str, again: str, cols: int | None = None) -> None:
    """Refuse a review longer than REVIEW_LINES rows, measured as it is RENDERED at the console's own width (width(),
    WIDTH when it cannot be told): every line wrapped at that many columns, and the rows counted (rows), so one long
    line is the many rows it fills. `lines` is everything printed before the yes, its header lines included. It is
    shown in full by `show --full`, which prints a review code, and the act is then made with `--reviewed-full <code>`.
    Nothing a yes depends on is cut."""
    cols = cols or width()
    n = rows(lines, cols)
    if n > REVIEW_LINES:
        raise Refused(f"{what} is too large to review here ({n} rows at {cols} columns). Read it in full with "
                      f"`{show}`, which ends with a review code, then run `{again} --reviewed-full <that code>`")


def proposal_code(home, n: int) -> str:
    """The review code of proposal n: of `show <n> --full` exactly as it prints now (its label worked out now
    included), of what confirm prints before its yes, the proposal, and the sources file's sha256."""
    store = _proposals_ok(home)
    r = store["open"].get(str(n)) or _find(home, n, "proposal")[0]
    shown = show_proposal(home, n)
    said = confirm_lines(home, r) if str(n) in store["open"] else []
    return review_code(shown + said, r, _digest(_sources_file(home)))


def confirm_lines(home, r: dict) -> list[Rendered]:
    """Everything `confirm` prints before its yes, rendered: the label it was made with, then confirm_review."""
    return [_line(f"Labelled when proposed: {_r(r.get('label', 'unknown'))}.")] + confirm_review(home, r)


def enable_code(home, key: str, declared: dict | None) -> str:
    """The review code of enabling `key`: of `show <key> --full` exactly as it prints now, and its enable snapshot."""
    return review_code(enable_review(home, key, declared), key, enable_snapshot(home, key))


def check_code(given: str, want: str, show: str) -> None:
    """Refuse a --reviewed-full code that is not the one `show --full` prints now (mistyped, or of a review that has
    changed since it was read)."""
    if type(given) is not str or given.strip().lower() != want:
        raise Refused(f"that is not the review code of what would be applied now (it was mistyped, or what you read has "
                      f"changed since): read it again with `{show}`, and give the code it ends with")


def show_proposal(home, n) -> list[str]:
    """`semantext plugins show <n>`: a proposal exactly, open or not, with its full before and after and its
    difference. Nothing is cut."""
    if type(n) is not int or n < 1:
        raise Refused("name the proposal by its number, as the page shows it")
    store = _proposals_ok(home)
    r = store["open"].get(str(n))
    if r is None:
        r, _ = _find(home, n, "proposal")
    lines = [f"Proposal {n} for {_r(r['plugin'])}, made by {_who(r)} at {_r(r.get('at'))}; labelled then: "
             f"{_r(r.get('label', 'unknown'))}.", f"Sources file it was made on: {_r(r.get('sources_file'))}"]
    sup = store["superseded"].get(str(n))
    if sup:
        who = "this page" if sup.get("who") == "page" else "the terminal"
        lines.append(f"It was superseded by proposal {_r(sup['by'])}, made by {who} at {_r(sup.get('at'))}.")
    for word, state in (("Before", r["before"]), ("After", r["after"])):
        lines.append(f"{word}, in full:")
        for k in _keys_of(state):
            has = k in (state.get("values") or {})
            lines += _value_lines(f"  {_r(k)} =", state["values"][k]) if has else [f"  {_r(k)}: not set"]
    lines.append("The difference:")
    return [_line(x) for x in lines] + difference(r["before"], r["after"]) + [label_now(r)]


# ---- the acts -------------------------------------------------------------------------------------------------------
def turn_on(home, key: str):
    """Never from the page: the line the person types instead."""
    _key(key)
    raise AtTheTerminal("a plug-in is turned on only by you, at your own console, typing its name",
                        command(home, "plugins", "enable", key))


def turn_off(home, key: str) -> dict:
    """Turn a plug-in off, from the page. Never held to the page's rate (_gate): it only takes reach away, and a
    plug-in that is off cannot be turned off again, so it cannot grow the log in a loop."""
    _key(key)
    if _builtin(key):
        raise Refused(f"{key} is part of Semantext and is always on")
    with locked(home):
        on, trouble = registry.enabled(home)
        if trouble:
            raise Refused(trouble[0]["text"])
        if key not in on:
            raise Refused(f"{key} is not on")
        return _make(home, "page", "off", "on", key, on[key], None)


def console_on_off(home, key: str, row: dict | None, snapshot: tuple | None = None) -> dict | None:
    """The console's enable (row) or disable (None), with the lock held across the check, the read and the write; None
    when nothing would change. With `snapshot` (enable_snapshot, taken when the review was shown), refused unless it
    still holds: the plug-in is turned on only as the person saw it."""
    with locked(home):
        if snapshot is not None and enable_snapshot(home, key) != snapshot:
            raise Refused("something it would read changed after the review was shown (your sources file, a recorded "
                          "change to this plug-in or a key it will be given, or its declaration or version), so it is "
                          "not turned on; run `semantext plugins enable` again to see it as it is now")
        on, trouble = registry.enabled(home)
        if trouble:
            raise Refused(trouble[0]["text"])
        before = on.get(key)
        if before == row or (row is None and before is None):
            return None
        return _make(home, "terminal", "on" if row is not None else "off", "on", key, before, row)


def _schema_for(key: str, found: dict) -> dict:
    i = found.get(key)
    if i is None:
        raise Refused(f"no installed package offers {key}")
    declared, why = _declaration(i)
    if declared is None:
        raise Refused(f"{key} declares no settings, so none of them is changed on the page"
                      + (f" ({why})" if why else ""))
    return {s["key"]: s for s in declared["settings"]}


def _not_closures(path: Path, raw: dict) -> None:
    """No proposal is made, or applied, on a sources file that is also the person's closures file (closures_file leads
    back to it): its closures are edited in the person's own editor, never by way of the page."""
    if _closures_here(path, raw)[0]:
        raise Refused("your sources file is also your closures file (its closures_file leads back to it), so the page "
                      "proposes nothing in it; change it in your own editor")


def change(home, key: str, given) -> dict:
    """A settings change from the page, `given` ({key: value, null to take one out}) as the plug-in's declaration types
    it: never made here. It is kept as a proposal (Proposed carries its number and the line that applies it)."""
    _key(key)
    if _builtin(key):
        raise Refused(f"{key} is part of Semantext; its settings are the keys of your sources file")
    if not isinstance(given, dict) or not given:
        raise Refused("name at least one setting to change")
    found, _ = _found()
    schema = _schema_for(key, found)
    unknown = [k for k in given if k not in schema]
    if unknown:
        raise Refused(f"{key} declares no setting {str(unknown[0])[:40]!r}")
    values = {k: check_value(schema[k], v) for k, v in given.items()}
    _gate(home)
    by = readers(found, None)
    with locked(home):
        path = _sources_file(home)
        raw = _raw(path)
        _not_closures(path, raw)
        _no_reserved(home, values)
        before = _state(raw, values)
        after = {"values": {k: x for k, x in sorted(values.items()) if x is not None},
                 "absent": sorted(k for k, x in values.items() if x is None)}
        if same(before, after):
            raise Refused("nothing would change")
        p = _propose(home, key, before, after, by)
    raise Proposed(f"proposed, not changed: the page never writes a plug-in's settings. Proposal {p['n']} "
                   f"({p.get('label', 'unknown')}) is applied at your own console, which shows exactly what it changes",
                   command(home, "plugins", "confirm", p["n"]), p["n"])


def _now_of(home, field: str, plugin: str, keys) -> object:
    if field == "on":
        on, trouble = registry.enabled(home)
        if trouble:
            raise Refused(trouble[0]["text"])
        return on.get(plugin)
    return _state(_raw(_sources_file(home)), keys)


def _find(home, n, what: str) -> tuple[dict, list[dict]]:
    if type(n) is not int or n < 1:
        raise Refused(f"name the {what} by its number, as the page shows it")
    recs, _ = changes(home)
    r = next((x for x in recs if x["n"] == n), None)
    if r is None:
        first = recs[0]["n"] if recs else None
        if first is not None and n < first:
            raise Refused(f"{what} {n} is further back than the change log the page reads (its last {TAIL // 1024} KB), "
                          f"so it is no longer acted on. A rotated log is kept, to read, in {ROTATED} until the next "
                          f"rotation, and is then dropped; the last change to each setting and each plug-in is kept "
                          f"for good in {LAST}, and open proposals in {PROPOSALS}")
        raise Refused(f"there is no {what} {n} in the change log")
    return r, recs


def roll_back(home, n) -> dict:
    """Restore the "before" of change n while the state is still its "after". Turning a plug-in off is made here;
    turning one on is never (the line to type instead); a settings rollback is a proposal, as any settings change. A
    record touching a reserved key is refused, whatever it says."""
    r, _ = _find(home, n, "change")
    if r["what"] == "proposed":
        raise Refused(f"change {n} is a proposal that was never made, so there is nothing to roll back")
    if r["field"] == "settings":
        _no_reserved(home, _keys_of(r["after"]) + _keys_of(r["before"]))
    if r["field"] == "settings":   # a settings rollback is a proposal, counted; one that turns a plug-in off is not
        _gate(home)
    by = readers(_found()[0], None) if r["field"] == "settings" else {}
    with locked(home):
        keys = _keys_of(r["after"]) if r["field"] == "settings" else ()
        current = _now_of(home, r["field"], r["plugin"], keys)
        if not same(current, r["after"]):
            raise Refused(f"{r['plugin']} has changed since change {n}, so it is not rolled back; roll back the later "
                          f"change first")
        if r["field"] == "on":
            if r["before"] is not None:
                raise AtTheTerminal(f"rolling back change {n} would turn {r['plugin']} on, which only you do, at "
                                    f"your own console", command(home, "plugins", "enable", r["plugin"]))
            return _make(home, "page", "rollback", "on", r["plugin"], current, None, rolls_back=n)
        path = _sources_file(home)
        _not_closures(path, _raw(path))
        p = _propose(home, r["plugin"], current, r["before"], by, rolls_back=n)
    raise Proposed(f"proposed, not changed: rolling back change {n} is proposal {p['n']} "
                   f"({p.get('label', 'unknown')}), applied at your own console",
                   command(home, "plugins", "confirm", p["n"]), p["n"])


def _superseded_by(store: dict, n: int) -> list[tuple[int, dict]]:
    """The chain of proposals that superseded n, oldest first: [(m, what the store says of n's supersession)]."""
    chain, seen, k = [], set(), str(n)
    while k in store["superseded"] and k not in seen:
        seen.add(k)
        s = store["superseded"][k]
        chain.append((s["by"], s))
        k = str(s["by"])
    return chain


def proposal(home, n) -> dict:
    """Proposal n as it stands, ready to be applied, or Refused with why it cannot be: not open (confirmed already,
    superseded, expired, or never made), made on another sources file, touching a reserved key, or stale: its sources
    file not byte for byte what it was made on (sha256), or a change recorded after it to one of its keys (from LAST,
    never only the log's tail). A superseded proposal is never applied in place of the one that took its place: both
    are named, and the person confirms the newer by its own number, after its own review."""
    if type(n) is not int or n < 1:
        raise Refused("name the proposal by its number, as the page shows it")
    store = _proposals_ok(home)
    r = store["open"].get(str(n))
    if r is None:
        chain = _superseded_by(store, n)
        if chain:
            m, s = chain[-1]
            newest = store["open"].get(str(m))
            who = "this page" if s.get("who") == "page" else "the terminal"
            mine = store["superseded"][str(n)]
            older = "this page" if mine.get("made_by") == "page" else "the terminal"
            raise Refused(f"proposal {n} was superseded by proposal {m}, made by {who} at "
                          f"{(newest or s).get('at')}; {n} itself was made by {older} at {mine.get('made_at')}. It is "
                          f"not applied, and {m} is not applied in its place. Read "
                          f"{m} with `{command(home, 'plugins', 'show', m)}`, and if it is what you want, confirm it "
                          f"by its own number: `{command(home, 'plugins', 'confirm', m)}`")
        if str(n) in store["confirmed"]:
            raise Refused(f"proposal {n} was confirmed already")
        raise Refused(f"there is no open proposal {n}: it was confirmed, expired, or never made")
    if _expired(r):
        raise Refused(f"proposal {n} expired (a proposal is confirmed within {PROPOSAL_SECONDS // 60} minutes); make "
                      f"the change again on the page")
    here, there = _sources_file(home), r.get("sources_file")
    if type(there) is not str or os.path.normcase(os.path.abspath(there)) != os.path.normcase(os.path.abspath(here)):
        raise Refused(f"proposal {n} was made on the sources file {there}, and this console acts on {here} "
                      f"(SEMANTEXT_SOURCES differs), so it is not confirmed here")
    keys = _keys_of(r["after"])
    _no_reserved(home, keys + _keys_of(r["before"]))
    raw = _raw(here)
    _not_closures(here, raw)
    last = last_changes(home)["keys"]
    later = sorted(last[k]["n"] for k in keys if isinstance(last.get(k), dict) and type(last[k].get("n")) is int
                   and last[k]["n"] > n)
    if later:
        raise Refused(f"change {later[0]} was made to one of its settings after proposal {n}, so it is stale and not "
                      f"confirmed; make the change again on the page")
    if r.get("sources_sha256") != _digest(here) or not same(_state(raw, keys), r["before"]):
        raise Refused(f"your sources file has changed since proposal {n} was made, so it is stale and not confirmed; "
                      f"make the change again on the page")
    return r


def confirm(home, n) -> dict:
    """Apply proposal n, as the person confirmed it at their console (plugincmd.py), with every check of proposal()
    made again under the lock: exactly its "after", on exactly the file it was made on; then it is no longer open."""
    with locked(home):
        r = proposal(home, n)
        more = {"confirms": n, **({"rolls_back": r["rolls_back"]} if "rolls_back" in r else {})}
        made = _make(home, "terminal", "rollback" if "rolls_back" in r else "settings", "settings", r["plugin"],
                     r["before"], r["after"], **more)
        store = _proposals_ok(home)
        store["open"].pop(str(n), None)
        store["confirmed"][str(n)] = made["n"]
        _keep_proposals(home, store)
        return made


# ---- the place ------------------------------------------------------------------------------------------------------
def _package(origin) -> str:
    return f"package {origin}" if str(origin).strip().casefold() == registry.BUILT_IN else str(origin)


def _health(key: str, loaded: bool, on: bool, why: str | None, origin=None, version=None) -> dict:
    """How its calls stand, for THIS package and version (another installed under the same name never lends its
    last call), and nothing when it is off (turning it on or off lets its last calls go: outside.forget)."""
    h = outside.health(key, origin, version) if on else {"last": None, "loading": None, "holding": 0}
    last = h["last"]
    if not on:
        words = "not on, so never called"
    elif not loaded:
        words = "on, but not loaded" + (f": {why}" if why else "")
    elif last is None:
        words = "not called yet"
    else:
        call = last["call"]
        words = {"answered": f"its last {call} answered", "error": f"its last {call} raised an error",
                 "late": f"its last {call} did not answer in time",
                 "busy": f"its last {call} was refused: it was busy",
                 "crowded": f"its last {call} was refused: too many calls waited"}[last["outcome"]]
        words += f" ({last['seconds']:g} s, {last['at']})"
    if h["holding"]:
        words += f"; {h['holding']} of its calls did not answer in time and still run"
    return {"words": words, "last": last, "loading": h["loading"], "holding": h["holding"]}


def _setting_rows(settings, raw: dict, raw_ok: bool) -> list[dict]:
    return [{**s, "set": raw_ok and s["key"] in raw, "value": raw.get(s["key"]) if raw_ok else None} for s in settings]


CLOSURES_HERE_NOTE = ("No settings form: your sources file is also your closures file (its closures_file leads back "
                      "to it), so the page proposes nothing in it. Change it in your own editor.")
CLOSURES_SAID = {"known": "they are named.",
                 "none named": "none are named yet, so every path is closed to it.",
                 "incomplete": "they are named, and the list of closed paths is incomplete, so every path is closed "
                               "to it until the list says it is complete.",
                 "unknown": "they are named and cannot be read, so every path is closed to it."}


def _reads(declared, settings, state: str) -> list[str]:
    out = list((declared or {}).get("reads") or [])
    for s in settings:
        if s["type"] in ("path", "paths"):
            v = s["value"]
            shown = ", ".join(map(str, v)) if isinstance(v, list) else str(v) if s["set"] else "not set"
            out.append(f"{s['title']}: {shown}")
    if not declared:
        out.append("It declares nothing it reads. Semantext imports no code of a plug-in to find out.")
    out.append("Held to your closed places when it asks (semantext.api.is_closed_place): " + CLOSURES_SAID[state])
    return out


def _builtin_rows(src) -> list[dict]:
    rows = []
    for e in src.reg.entries():
        if not e.builtin:
            continue
        keys = list(getattr(e.obj, "keys", ()) or ())
        reads = {"source": "the files the keys of your sources file below name",
                 "place": "the readers' answers, on this page", "checker": str(getattr(e.obj, "records", None) or
                                                                           "no run records: a list, not a record")}
        said = reads[e.kind] if (e.kind, e.name) != ("place", "plugins") else \
            "the packages' metadata, their declaration files, plugins.json, your sources file and the change log"
        rows.append({"key": f"{e.kind}.{e.name}", "kind": e.kind, "name": e.name,
                     "title": str(getattr(e.obj, "title", "") or e.name), "builtin": True, "package": "semantext",
                     "version": __version__, "trust": "built-in", "installed": True, "on": True, "loaded": True,
                     "health": {"words": "part of Semantext, read in the page's own code", "last": None,
                                "loading": None, "holding": 0},
                     "reads": [said],
                     "settings": [{"key": k, "type": None, "title": k, "widens": False, "required": False,
                                   "set": k in src.cfg, "value": src.cfg.get(k)} for k in keys],
                     "undeclared": [], "declared": None, "declaration_problem": None,
                     "can": {"off": False, "change": False}, "on_command": None})
    return rows


def place(src) -> dict:
    """The Plug-ins tab's data. `src` is the answer's reading (sources/view.py), made with no outside source read."""
    from .sources import closed
    home = src.home if src.home is not None else paths.home()
    found, installed_problems = _found()
    on, on_trouble = registry.enabled(home)
    state = closed.closures_state(home)
    known = state["known"]
    try:
        raw, raw_ok = _raw(src.path), True
    except Refused:
        raw, raw_ok = {}, False
    by_key = {p["source"][len("plug-in "):]: p["text"] for p in src.reg.problems if p["source"].startswith("plug-in ")}
    shared = {k for k, rs in readers(found, src.reg).items() if len({pk for pk, _ in rs}) > 1}
    # the page proposes nothing in a sources file that is also the closures file: no settings form is offered then
    closures_here = raw_ok and _closures_here(src.path, raw)[0]
    change_note = (CLOSURES_HERE_NOTE if closures_here else None)
    rows = _builtin_rows(src)
    for key, i in found.items():
        loaded = src.reg.get(i.kind, i.name)
        loaded = loaded if loaded is not None and not loaded.builtin and loaded.origin == i.origin else None
        is_on = key in on
        if i.kind not in registry.KINDS:
            trust = "reserved: this kind cannot be turned on yet"
        elif not is_on:
            trust = "installed, not on"
        elif loaded is not None:
            trust = "on"
        else:
            trust = "on, not loaded"
        declared, why = _declaration(i)
        settings = _setting_rows((declared or {}).get("settings") or [], raw, raw_ok)
        undeclared = []
        if loaded is not None:
            names = {s["key"] for s in settings}
            undeclared = [{"key": k, "set": raw_ok and k in raw, "value": raw.get(k) if raw_ok else None}
                          for k in getattr(loaded.obj, "keys", ()) or () if k not in names]
        rows.append({"key": key, "kind": i.kind, "name": i.name, "title": str(getattr(loaded.obj, "title", "") or i.name)
                     if loaded is not None else i.name, "builtin": False, "package": _package(i.origin),
                     "version": i.version, "trust": trust, "installed": True, "on": is_on, "loaded": loaded is not None,
                     "health": _health(key, loaded is not None, is_on, by_key.get(key), i.origin, i.version),
                     "reads": _reads(declared, settings, state["state"]), "settings": settings, "undeclared": undeclared,
                     "declared": declared is not None, "declaration_problem": why,
                     "shared": sorted(k for k in shared if any(s["key"] == k for s in settings)),
                     "can": {"off": is_on,
                             "change": declared is not None and bool(settings) and raw_ok and not closures_here},
                     "change_note": change_note if declared is not None and settings else None,
                     "on_command": command(home, "plugins", "enable", key)
                     if not is_on and i.kind in registry.KINDS else None})
    for key, row in on.items():   # turned on, and no installed package offers it now
        if key in found:
            continue
        kind, _, name = key.partition(".")
        allowed = bool(KEY.fullmatch(key))
        if allowed:
            trust, why, off_line = "turned on, not installed", "no installed package offers it", None
        else:   # on from before names were held to the pattern: it never loads, and the page cannot name it
            trust = "turned on, but its name is no longer allowed"
            why = ("its name is no longer allowed (a plug-in's name is letters, digits, _ and -), so it never loads; "
                   "take it off your list at your console")
            off_line = command(home, "plugins", "disable", key) if WORD.fullmatch(key) else None
        rows.append({"key": key, "kind": kind, "name": name, "title": name, "builtin": False,
                     "package": _package(row.get("origin") if isinstance(row, dict) else None),
                     "version": row.get("version") if isinstance(row, dict) else None,
                     "trust": trust, "installed": False, "on": True, "loaded": False,
                     "health": _health(key, False, True, why, *((row.get("origin"), row.get("version"))
                                                                    if isinstance(row, dict) else (None, None))),
                     "reads": [],
                     "settings": [], "undeclared": [], "declared": False, "declaration_problem": None, "shared": [],
                     "can": {"off": allowed, "change": False}, "on_command": None, "off_command": off_line,
                     "off_note": None if allowed or off_line else
                     "Its name holds characters the line to type will not carry: take it out of plugins.json in "
                     "your home in your own editor."})
    recs, log_problems = changes(home)
    try:
        store = _proposals_ok(home)
    except Refused as e:
        store = {"open": {}, "superseded": {}, "confirmed": {}}
        log_problems = log_problems + [_problem(proposals_file(home), None, str(e))]
    confirmed = {r["confirms"] for r in recs if isinstance(r.get("confirms"), int)} | \
        {number(k) for k in store["confirmed"] if number(k) is not None}
    newest = _newest_made(recs)
    shown = []
    for r in reversed(recs[-SHOWN:]):
        status = None
        if r["what"] == "proposed":
            status = ("confirmed" if r["n"] in confirmed else "superseded" if str(r["n"]) in store["superseded"]
                      else "expired" if _expired(r) else "open" if str(r["n"]) in store["open"] else "expired")
        elif r["n"] in newest and raw_ok and not on_trouble and _not_applied(r, raw, on):
            status = "not applied"
        shown.append({**r, "confirmed": r["n"] in confirmed if r["what"] == "proposed" else None, "status": status,
                      "command": command(home, "plugins", "confirm", r['n']) if status == "open" else None})
    return {"plugins": rows, "changes": shown, "closures_known": known, "closures_state": state["state"],
            "closures_why": state["why"], "closures_fix": state["fix"], "sources_file": str(src.path),
            "sources_readable": raw_ok, "list_command": command(home, "plugins"), "command_note": command_note(home),
            "problems": installed_problems + on_trouble + log_problems}


def _newest_made(recs: list[dict]) -> set:
    """The made records that no later made record follows for any of their keys (or their plug-in, turning on or off):
    the ones whose "after" should be the state now."""
    seen_keys, seen_plugins, out = set(), set(), set()
    for r in reversed(recs):
        if r["what"] == "proposed":
            continue
        if r["field"] == "on":
            if r["plugin"] not in seen_plugins:
                out.add(r["n"])
            seen_plugins.add(r["plugin"])
        elif isinstance(r.get("after"), dict):
            keys = set(_keys_of(r["after"]))
            if keys and not keys & seen_keys:
                out.add(r["n"])
            seen_keys |= keys
    return out


def _not_applied(r: dict, raw: dict, on: dict) -> bool:
    """Whether a newest made record's "after" is not the state now: its process stopped between recording it and
    making it (or the file was changed by hand since; either way the record is not what stands)."""
    if r["field"] == "on":
        return not same(on.get(r["plugin"]), r.get("after"))
    after = r.get("after") if isinstance(r.get("after"), dict) else {}
    return not same(_state(raw, _keys_of(after)), after)
