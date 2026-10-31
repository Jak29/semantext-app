"""The store: your environments as plain rule files, and every change to them, undoable.

An environment is one YAML file, profiles/<name>/SEMANTICS.yaml. "base" holds the rules every environment shares;
"default" is where everyone starts. Every write first copies the previous version into history/, so nothing is ever
lost: undoing a rule archives it in its file, and undo-last restores the previous version of the whole file.
"""
from __future__ import annotations

import difflib
import errno
import json
import os
import re
import stat
import tempfile
import time
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from . import jsonread, paths

NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")   # always used with fullmatch: "$" would also allow a final "\n"
# The base rules on every relay card, by their ids as well as by their `always` mark: a mark is an edit away, and the
# rule that an act waits for the user's word must never fall off the card that relayed words get.
FLOOR = ("base.irreversible-needs-your-word", "base.relayed-words-are-information")
# The provenance types Semantext itself writes: the rules it ships, your corrections, an agent's proposal you added, a
# suggestion you picked, a switch. A rule with none of these was written into its file by hand (Store.hand_written).
WRITTEN_BY = ("DEFAULT", "LEARNED", "PROPOSED", "SUGGESTED", "SETTING")


def hand_written_line(n: int) -> str:
    """The card's one line for its hand-written rules."""
    return f"{n} rule{' is' if n == 1 else 's are'} hand-written (no provenance)."
MAX_CASE = 1000   # the longest misread message kept as a test
# An agent's name, as agents.py makes it: the key of its own layer of rules in an environment file.
AGENT_NAME_RE = re.compile(r"[a-z0-9][a-z0-9@._-]{0,59}")
LAYER_NOTE = ("These are this agent's own rules. They add to the rules above and never override them: where one seems "
              "to conflict with a rule above, the rule above wins.")


def agent_slug(agent: str) -> str:
    """An agent's name as part of a rule id: claude-code@app becomes claude-code-app."""
    return re.sub(r"[^a-z0-9-]+", "-", str(agent).lower()).strip("-")[:40] or "agent"
# Names Windows reserves for devices: a folder with one of them is unreliable there, so no platform makes one.
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(NAME_RE.fullmatch(name)) and name not in RESERVED


def ollama_manifests() -> Path:
    """Where Ollama keeps the names of the models on this machine, worked out when asked, never at import: the user's
    home is read then, so a run that points the home elsewhere (the tests) never lists the real one."""
    return Path.home() / ".ollama" / "models" / "manifests" / "registry.ollama.ai" / "library"

# The switches on the page. Each one is a rule, so the card stays the single place the AI reads.
FEATURES = {
    "tone": ("Match my tone and phrasing so you feel familiar, without copying me exactly.", "adaptive"),
    "jokes": ("Humour is welcome: keep up with current meme culture, and never joke at my expense.", "adaptive"),
    "news": ("Bring in current news when it is relevant, focused on {country}. (A news source is not connected yet.)",
             "stationary"),
    "inbox": ("When you need my decision or permission, file it with `semantext ask` (a title, why it needs me, the "
              "options and your recommendation) and keep working on what does not need it. Act on it only after my "
              "answer reaches you. Never answer your own request; only my answer counts.", "stationary"),
}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


_STAMP_LOCK = threading.Lock()
_last_stamp: list = [None]


_STAMP_FORMAT = "%Y%m%d-%H%M%S-%f"
_STAMP_MARK = re.compile(r"\d{8}-\d{6}-\d{6}")
_STAMP_AHEAD = timedelta(days=2)


def stamp(after=()) -> str:
    """Now in UTC, to the microsecond, never the same twice in one process, and later than every mark in `after` (the
    names already in the folder the file goes to). A file named by it (a backup, a kept version) never overwrites the
    one before, and sorts after it: on some clocks (Windows with Python 3.10) two calls in a row read the same
    microsecond, and a local clock goes back an hour each autumn, so a name in local time after a restart could sort
    before the last one and `undo_last` would restore the wrong version (audit of 44d2dfa). UTC never goes back for
    the season, and the folder's highest mark also covers names written in local time before this change, and a clock
    set back by hand."""
    with _STAMP_LOCK:
        t = datetime.now(timezone.utc).replace(tzinfo=None)
        floor = _last_stamp[0]
        # a mark more than two days ahead of now is no real time on any clock or offset: it is ignored, so a planted
        # far-future name cannot make every later name overflow or pin it (audit of 4599bda)
        latest_real = t + _STAMP_AHEAD
        for name in after:
            for m in _STAMP_MARK.findall(str(name)):
                try:
                    v = datetime.strptime(m, _STAMP_FORMAT)
                except ValueError:
                    continue
                if v > latest_real:
                    continue
                if floor is None or v > floor:
                    floor = v
        if floor is not None and t <= floor:
            t = floor + timedelta(microseconds=1)
        _last_stamp[0] = t
    return t.strftime(_STAMP_FORMAT)


def dump(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110)


_WRITE_LOCK = threading.Lock()
# Every temporary file write_atomic makes starts with this, so the store can tell its own from anything else: a kill
# between the write and the swap leaves one behind, and the store sweeps those at open (sweep_temps).
TEMP_PREFIX = ".semantext-write-"
TEMP_STALE_S = 3600   # a temporary file older than this is no write in progress


def sweep_temps(folder) -> int:
    """Remove this store's own stale temporary files from one folder (not below it): a name that starts with
    TEMP_PREFIX and ends .tmp, a plain file (never a link), last changed over TEMP_STALE_S ago. Anything else is left
    alone. Returns how many went; a file that cannot be examined or removed is skipped, never an error."""
    gone, cutoff = 0, time.time() - TEMP_STALE_S
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for name in names:
        if not (name.startswith(TEMP_PREFIX) and name.endswith(".tmp")):
            continue
        p = os.path.join(folder, name)
        try:
            st = os.lstat(p)
            if os.path.islink(p) or not os.path.isfile(p) or st.st_mtime > cutoff:
                continue
            os.unlink(p)
            gone += 1
        except OSError:
            continue
    return gone


READ_TRIES = 21   # 50 ms apart: about a second


def read_settled(path, binary: bool = False):
    """A file's text (or bytes), read as the store reads its own files: Windows refuses a read for a moment while
    write_atomic swaps the file in, and for longer on a busy machine, so a PermissionError is tried again for about a
    second, as write_atomic tries its swap, before it is raised."""
    path = Path(path)
    for attempt in range(READ_TRIES):
        try:
            return path.read_bytes() if binary else path.read_text(encoding="utf-8")
        except PermissionError:
            if attempt == READ_TRIES - 1:
                raise
            time.sleep(0.05)


class _NotRead(dict):
    """Settings at their defaults because state.json could not be READ just now (the system refused it), not because
    it is damaged. put_state refuses these: saving them would put the defaults over settings that are still there."""


def write_atomic(target, data) -> None:
    """Every file the store writes, written whole or not at all (review of 1.2.2, S1): into a temporary file in the
    same folder, flushed and synced to disk, then put in place with os.replace, so a crash or a reader at the same
    moment sees the old file or the new one, never half of one. Text is written as write_text writes it (the system's
    line endings); bytes are copied as they are. The temporary name is unique to this one write, not to the process
    (review of 1.2.2, S2: the page's server writes from several threads at once), and an in-process lock keeps two
    threads from racing on the swap. Windows refuses the swap while another process is reading the file, so it is
    retried for a second before the error is raised; a write that cannot land leaves no temporary file behind."""
    target = Path(target)
    if isinstance(data, str):     # a text's CRLF is one line end: written in text mode it would become CR CR LF
        data = data.replace("\r\n", "\n")
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f"{TEMP_PREFIX}{target.stem}-", suffix=".tmp")
    try:
        with (os.fdopen(fd, "wb") if isinstance(data, bytes) else os.fdopen(fd, "w", encoding="utf-8")) as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        for attempt in range(20):
            try:
                with _WRITE_LOCK:     # the lock covers the swap only: a wait for a busy file never holds up the others
                    os.replace(tmp, target)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


LOCK_TIMEOUT = 10.0   # seconds append_checked waits for another writer before it refuses


class Tail:
    """What append_checked hands its check, read under the lock: `raw`, the file's bytes; `lines`, its complete lines
    as text without their newline (a carriage return before it is kept, for the reader to judge), made only when asked
    for, so a check that reads only the end of a long file never splits all of it; and `torn`, the text after the last
    newline when the file does not end in one (None when it does, or is empty). `size` is the file's length in bytes."""

    def __init__(self, raw: bytes):
        self.raw, self.size = raw, len(raw)
        cut = raw.rfind(b"\n") + 1
        self.torn = raw[cut:].decode("utf-8", errors="replace") if cut < len(raw) else None
        self._lines = None

    @property
    def lines(self) -> list[str]:
        if self._lines is None:
            body = self.raw[:self.raw.rfind(b"\n") + 1]
            self._lines = [p.decode("utf-8", errors="replace") for p in body.split(b"\n")[:-1]]
        return self._lines


@contextmanager
def file_lock(lock_path, timeout: float = LOCK_TIMEOUT):
    """An exclusive lock on <lock_path>, held across processes and threads: the operating system's own lock on its
    first byte (msvcrt.locking on Windows, fcntl.flock elsewhere), which the system releases when the holder's process
    ends, however it ends. So there is no stale-lock rule, and none is needed: a lock file left behind is only a file
    and never blocks anyone. Waits up to `timeout` seconds, then refuses.

    No holder can shut out a waiter, by a turnstile: a writer first takes the gate, a second lock on <lock_path>.gate
    (a second file, since flock locks a whole file; the same on Windows, for one rule on both), then the lock itself,
    then lets the gate go. A writer waiting for the lock waits standing in the gate, so a holder that lets the lock go
    and wants it again must pass the gate first, where the waiter already stands. With two writers that is exact: the
    waiter goes next. With three or more, only the one standing in the gate is sure to go next; the others wait for
    the gate itself, which the operating system gives to whoever asks first once it is let go, so their order is
    first-come at best, not a queue, and a wait grows with the number of writers (measured worst waits of about 12, 55,
    78 and 113 ms for 2, 3, 4 and 6 writers in tight loops). Without the gate the system picks whoever asks first after
    a release, and a writer in a tight loop asks first nearly every time, so even with two the other could wait past
    its timeout (seen in CI). The wait at the gate counts against the same `timeout`."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fd = _open_lock(lock_path)
    try:
        if _GATED:
            gate = _open_lock(lock_path.with_name(lock_path.name + ".gate"))
            try:
                _wait_for(gate, deadline, lock_path, timeout)
                try:
                    _wait_for(fd, deadline, lock_path, timeout)
                finally:
                    _lock_byte(gate, False)
            finally:
                os.close(gate)
        else:
            _wait_for(fd, deadline, lock_path, timeout)
        try:
            yield
        finally:
            _lock_byte(fd, False)
    finally:
        os.close(fd)


_GATED = True   # the turnstile; off only in the test that shows a tight loop wins the bare lock without it


def _open_lock(path: Path) -> int:
    """The lock file (or the gate) opened, made when it is not there. Only a plain file with one name is ever a lock:
    a folder, a link or a junction standing at the name is refused before it is opened (a link would be followed, and
    the lock made wherever it leads), and so is a second hard link (the lock would be taken on another file's bytes,
    and on Windows a byte lock on it can fail, or hold up whoever uses that file). Where the system can, the open itself
    refuses a link (O_NOFOLLOW). Where it cannot (Windows), something swapped in between the look and the open is
    caught after it: the file opened must be, by its identity (device and file number), the one the name was before
    the open, and the one the name is after it; and it must still be one plain file with one name.

    Two limits, said rather than hidden. The identity check needs a file system that gives file numbers; on one that
    does not (FAT, some network drives: st_ino is 0) the swap check does not run, and only the checks by name do. And
    on Windows a link planted at the name in the moment between the look and the open is followed by the open itself:
    the lock is then refused, but the open may already have made an empty file where the link leads."""
    before = _plain_lock(path)
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError as e:
        if _not_plain(path) or e.errno in (errno.ELOOP, errno.EISDIR):   # it changed after the look, or it is a link
            raise Refused(f"{path.name} is {_standing(path) or 'a link or a folder'}, not a lock file; it is not taken "
                          f"as a lock") from None
        raise
    try:
        opened = os.fstat(fd)
        after = _plain_lock(path)
        if not stat.S_ISREG(opened.st_mode):
            raise Refused(f"{path.name} is not a plain file, so it is not taken as a lock")
        if opened.st_nlink > 1:
            raise Refused(f"{path.name} has another name on disk (a hard link), so it is not taken as a lock")
        if after is None or any(st is not None and _identity(st) and _identity(st) != _identity(opened)
                                for st in (before, after)):
            raise Refused(f"{path.name} changed while it was opened (something else was put at its name), so it is "
                          f"not taken as a lock")
    except BaseException:
        os.close(fd)
        raise
    return fd


def _identity(st) -> tuple | None:
    """A file's identity, (device, file number), or None where the file system gives no file number (st_ino 0: FAT,
    some network drives), and then no identity is compared (see _open_lock)."""
    return (st.st_dev, st.st_ino) if st.st_ino else None


def _plain_lock(path: Path):
    """What lstat says stands at a lock's name: None when nothing does, its stat when it is one plain file with one
    name; Refused for anything else."""
    what = _standing(path)
    if what:
        raise Refused(f"{path.name} is {what}, not a lock file; it is not taken as a lock")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if st.st_nlink > 1:
        raise Refused(f"{path.name} has another name on disk (a hard link), so it is not taken as a lock")
    return st


NAME_SURROGATE = 0x20000000   # a reparse tag with this bit names another place: a symbolic link or a junction


def _not_plain(path: Path) -> bool:
    """Whether something other than a plain file stands at `path` (_standing says what). Nothing there is plain: the
    lock is made."""
    return _standing(path) is not None


def _standing(path: Path) -> str | None:
    """What stands at `path` when it is not a plain file, in words, read from lstat so it holds on every Python: "a
    folder", "a link or a junction" (a symbolic link, or a Windows reparse point whose tag names another place), or
    "something that is not a plain file". None when nothing is there, or a plain file is: a reparse point whose tag
    names no other place, such as a cloud-storage placeholder of a file (OneDrive's), is that file, as places._linked
    and the work writer read one."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return "something that cannot be looked at"
    if stat.S_ISLNK(st.st_mode) or (getattr(st, "st_file_attributes", 0)
                                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
                                    and getattr(st, "st_reparse_tag", 0) & NAME_SURROGATE):
        return "a link or a junction"
    if stat.S_ISDIR(st.st_mode):
        return "a folder"
    if not stat.S_ISREG(st.st_mode):
        return "something that is not a plain file"
    return None


def _wait_for(fd: int, deadline: float, lock_path: Path, timeout: float) -> None:
    """Takes the operating system's lock on fd, asking again every few milliseconds until the deadline, then refuses."""
    while True:
        try:
            _lock_byte(fd, True)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise Refused(f"{lock_path.name} is held by another writer for over {timeout:g} s; try again")
            time.sleep(0.005)


def _lock_byte(fd: int, on: bool) -> None:
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK if on else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if on else fcntl.LOCK_UN)


def append_checked(path, check, line, timeout: float = LOCK_TIMEOUT, after=None) -> str:
    """One line appended to a JSON-lines file, checked first, as one act no other writer can split (doors spec v0.6,
    rule 10): under file_lock(<path>.lock) the file is read whole, check(tail) is called with its Tail and may refuse
    by raising Refused (then nothing is written), the line is made (`line` is the text, or a function of the same Tail
    that returns it, so a number minted from the file is minted under the lock), one line ending in a newline is
    appended, then flushed and synced to disk. `after(tail, text)`, when given, runs still under the lock, after the
    sync (the work store writes its head there). Returns the line written.

    A torn tail, the file not ending in a newline (a writer that died mid-write), is never glued to: the new line is
    started on a fresh line, so the fragment stays a line of its own for the reader to report, and the line written is
    whole. The check sees the fragment in tail.torn and decides what it means."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.with_name(path.name + ".lock"), timeout):
        raw = path.read_bytes() if path.exists() else b""
        tail = Tail(raw)
        if check is not None:
            check(tail)
        text = line(tail) if callable(line) else line
        if not isinstance(text, str) or "\n" in text or "\r" in text:
            raise Refused("append_checked writes one line of text, with no line break inside it")
        data = (b"\n" if tail.torn is not None else b"") + text.encode("utf-8") + b"\n"
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        if after is not None:
            after(tail, text)
    return text


def provenance_of(x) -> dict:
    """A rule's provenance, or {} when none is recorded. A hand edit can leave it a plain string ("learned") or a
    list; that reads as none recorded, never as an AttributeError in the hook or the page (review of 1.2.2, S3)."""
    p = x.get("provenance") if isinstance(x, dict) else None
    return p if isinstance(p, dict) else {}


class Refused(ValueError):
    """A request the store will not carry out, with the reason shown to the user."""


def check_environment(d, where: str) -> None:
    """The shape every rule file needs, checked when it is read and before the editor saves one: a hand edit that went
    wrong is refused in one line naming the file and the rule, never a traceback later (in the hook, on every
    prompt)."""
    if not isinstance(d, dict) or not isinstance(d.get("environment"), dict) or not d["environment"].get("id"):
        raise Refused(f"{where} is not a Semantext rule file (it needs an 'environment' section with an id)")
    if not isinstance(d.get("entries") or [], list):
        raise Refused(f"{where}: 'entries' must be a list")
    agents = d.get("agents")
    if agents is not None and (not isinstance(agents, dict) or not all(
            isinstance(k, str) and AGENT_NAME_RE.fullmatch(k) and isinstance(v, dict)
            and isinstance(v.get("entries") or [], list) for k, v in agents.items())):
        raise Refused(f"{where}: 'agents' must map each agent's name, as `semantext agents` shows it, to its own "
                      f"entries")
    layered = [x for v in (agents or {}).values() for x in (v.get("entries") or [])]
    for n, x in enumerate([*(d.get("entries") or []), *layered], 1):
        if not isinstance(x, dict):
            raise Refused(f"{where}: rule {n} is not a rule (each one starts '- id:', with its statement below)")
        rid = x.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise Refused(f"{where}: rule {n} has no id")
        if not isinstance(x.get("statement"), str) or not x["statement"].strip():
            raise Refused(f"{where}: rule {rid} has no statement, or one that is not text (put it in quotes)")
    # Corrections kept as tests (see Store.cases): each one the message that was misread, and the rules it needs.
    if not isinstance(d.get("tests") or [], list):
        raise Refused(f"{where}: 'tests' must be a list")
    for n, t in enumerate(d.get("tests") or [], 1):
        if not isinstance(t, dict) or not isinstance(t.get("message"), str) or not t["message"].strip():
            raise Refused(f"{where}: test {n} has no message (each one starts '- case:', with the misread message)")
        if not isinstance(t.get("rules") or [], list) or not all(isinstance(r, str) for r in t.get("rules") or []):
            raise Refused(f"{where}: test {n}'s rules must be a list of rule ids")


class Store:
    def __init__(self, root: Path | None = None, suggestions: Path | None = None):
        self.root = Path(root) if root else paths.home()
        self.profiles_dir = self.root / "profiles"
        self.history_dir = self.root / "history"
        self.state_path = self.root / "state.json"
        self.suggest_dir = Path(suggestions) if suggestions else paths.suggestions_dir()
        self.state_problem: str | None = None   # set by state() when state.json cannot be read
        self.last_undo: dict = {}               # what undo_last took off, and where the version it replaced is kept

    @classmethod
    def open(cls, root: Path | None = None) -> "Store":
        """The store at root (or your home), created with the starting environments if it is new. Its own stale
        temporary files (see sweep_temps) are swept from the folders write_atomic writes into: the store's folder, its
        history, and each environment's folder; nothing below those, and nothing else."""
        store = cls(paths.ensure_home(root))
        try:   # environments only: a stray folder (see strays) is left alone, as strays() says
            envs = [p for p in store.profiles_dir.iterdir() if valid_name(p.name) and not p.is_symlink()
                    and (p / "SEMANTICS.yaml").is_file()]
        except OSError:
            envs = []
        for folder in (store.root, store.history_dir, *envs):
            sweep_temps(folder)
        return store

    # ---- files ------------------------------------------------------------------------------------------------
    def path(self, name: str) -> Path:
        if not valid_name(name):
            raise Refused(f"not an environment name: {name!r}")
        p = self.profiles_dir / name / "SEMANTICS.yaml"
        if not p.is_file():
            raise Refused(f"no such environment: {name}")
        return p

    def load(self, name: str) -> dict:
        """The environment's rule file, or a refusal naming the file if it is not one (for example after a hand
        edit went wrong): never a traceback."""
        p = self.path(name)
        try:
            d = yaml.safe_load(read_settled(p))
        except UnicodeDecodeError:
            raise Refused(f"{p} is not saved as UTF-8 text; save it again as UTF-8")
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            at = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            raise Refused(f"{p} is not valid YAML{at} ({getattr(e, 'problem', None) or str(e).splitlines()[0]}). Fix "
                          f"that line; or `semantext undo --last --env {name}` restores the last version Semantext "
                          f"saved, and keeps this one in history/")
        check_environment(d, str(p))
        return d

    def _keep(self, name: str) -> None:
        """The previous version goes to history/ before any write: undo at the file level, and nothing lost."""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        mark = stamp(p.name for p in self.history_dir.glob(f"{name}-*.yaml"))
        write_atomic(self.history_dir / f"{name}-{mark}.yaml", read_settled(self.path(name), binary=True))

    def save(self, name: str, data: dict) -> None:
        self._keep(name)
        write_atomic(self.path(name), dump(data))

    def names(self) -> list[str]:
        """Default first, then your own environments by name, then base (shared, never shown as an environment)."""
        found = {p.parent.name for p in self.profiles_dir.glob("*/SEMANTICS.yaml") if valid_name(p.parent.name)}
        own = sorted(n for n in found if n not in ("default", "base"))
        return (["default"] if "default" in found else []) + own + (["base"] if "base" in found else [])

    def strays(self) -> list[str]:
        """Folders in profiles/ that are not environments Semantext can use (a copy made in a file manager, say):
        left alone, and reported by `semantext doctor`."""
        if not self.profiles_dir.is_dir():
            return []
        return sorted(p.name for p in self.profiles_dir.iterdir()
                      if p.is_dir() and not (valid_name(p.name) and (p / "SEMANTICS.yaml").is_file()))

    def title(self, name: str) -> str:
        return str(self.load(name)["environment"].get("title") or name.title())

    def title_or_name(self, name: str) -> str:
        """The title for a message, or the name when the file cannot be read: a message never fails on it."""
        try:
            return self.title(name)
        except (Refused, OSError):
            return name

    def titles(self) -> tuple[dict, list]:
        """Every environment's title by name (base left out), and the problems of the files that cannot be read. One
        broken file is skipped and reported, and never blocks switching to, or making, any other (review of 1.2.2,
        S4)."""
        titles, problems = {}, []
        for n in self.names():
            if n == "base":
                continue
            try:
                titles[n] = self.title(n)
            except (Refused, OSError) as e:
                problems.append({"name": n, "problem": str(e)})
        return titles, problems

    def _base_version(self) -> str:
        """The version of the base rules in this home, so a new environment pins what is really there."""
        try:
            got = yaml.safe_load((self.profiles_dir / "base" / "SEMANTICS.yaml").read_text(encoding="utf-8"))
            version = got["environment"]["version"]
        except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError):
            return "0.1.0"
        return version if isinstance(version, str) and version else "0.1.0"

    def resolve(self, text: str) -> str:
        """An environment's name, from its name or its title, ignoring case: "Gardening" finds gardening."""
        text = " ".join(str(text or "").split())
        if text.lower() == "base":
            return "base"
        names = [n for n in self.names() if n != "base"]
        if text in names:
            return text
        got, problems = self.titles()
        titles = {n: t.lower() for n, t in got.items()}
        names = [n for n in names if n in titles or n == text.lower()]
        titles.update({n: n for n in names if n not in titles})   # a broken file still answers to its own name
        hits = [n for n in names if n == text.lower() or titles[n] == text.lower()]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise Refused(f"{text!r} is the title of {len(hits)} environments; use a name: {', '.join(hits)}")
        # A near miss only: "gardenin" finds gardening, but "Kayaking" does not suggest baking.
        close = difflib.get_close_matches(text.lower(), names + list(titles.values()), n=1, cutoff=0.8)
        hint = ""
        if close:
            hint = f"; did you mean {next((n for n in names if close[0] in (n, titles[n])), close[0])}?"
        skipped = (f"; {len(problems)} environment file{'s' if len(problems) != 1 else ''} could not be read, so "
                   f"{'their titles were' if len(problems) != 1 else 'its title was'} not searched: "
                   + "; ".join(p["problem"] for p in problems)) if problems else ""
        raise Refused(f"no environment called {text!r}{hint} (see them with: semantext env list){skipped}")

    # ---- state ------------------------------------------------------------------------------------------------
    def state(self) -> dict:
        """The settings and the log. A state.json that cannot be read (empty after a crash, say) holds settings only,
        so the defaults stand in, and `state_problem` names the file; the next change keeps a copy of it first."""
        s = {"active": "default", "model": None, "hear_prompts": False, "feed": True, "log": [], "pending": []}
        self.state_problem = None
        if self.state_path.exists() and not self.state_path.is_file():
            self.state_problem = self._not_a_file()
        elif self.state_path.exists():
            try:
                got = jsonread.loads(read_settled(self.state_path))
                if not isinstance(got, dict):
                    raise ValueError("it does not hold settings")
                s.update(got)
            except (ValueError, OSError) as e:
                self.state_problem = (f"{self.state_path} could not be read ({e}), so the settings are at their "
                                      f"defaults until it is fixed or replaced")
                if isinstance(e, OSError):
                    s = _NotRead(s)
        s["log"] = s["log"] if isinstance(s.get("log"), list) else []
        s["pending"] = s["pending"] if isinstance(s.get("pending"), list) else []
        if not valid_name(s["active"]) or not (self.profiles_dir / s["active"] / "SEMANTICS.yaml").is_file():
            s["active"] = "default"   # an environment that no longer exists falls back to Default
        return s

    def put_state(self, s: dict) -> None:
        """Written whole or not at all: to a temporary file, then put in place, so a crash never leaves it empty. An
        unreadable file it replaces is kept beside it first. Settings that stood in only because the file could not be
        read just now are refused, so they never go over the real ones."""
        if isinstance(s, _NotRead):
            raise Refused(f"{self.state_path} could not be read just now, so nothing is saved over it; try again")
        s["log"] = s["log"][-60:]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists() and not self.state_path.is_file():
            raise Refused(self._not_a_file())
        if self.state_path.exists():
            try:
                readable = isinstance(jsonread.loads(read_settled(self.state_path)), dict)
            except (ValueError, OSError):
                readable = False
            if not readable:
                mark = stamp()
                try:
                    old = read_settled(self.state_path, binary=True)
                except OSError as e:     # never replace a file whose copy cannot be kept
                    raise Refused(f"{self.state_path} cannot be read ({e}), so it is not replaced; the settings are "
                                  f"not saved until it can be read or is moved aside")
                write_atomic(self.state_path.with_name(f"state-unreadable-{mark}.json"), old)
        write_atomic(self.state_path, json.dumps(s, indent=1, ensure_ascii=False))

    def _not_a_file(self) -> str:
        return (f"{self.state_path} is not a file, so the settings are at their defaults and cannot be saved until it "
                f"is moved aside")

    def log(self, what: str) -> None:
        s = self.state()
        s["log"].append({"when": now(), "what": what})
        self.put_state(s)

    def set_option(self, key: str, value) -> None:
        if key not in ("hear_prompts", "feed"):
            raise Refused(f"no such setting: {key}")
        if not isinstance(value, bool):
            raise Refused(f"{key} is on or off")
        s = self.state()
        s[key] = value
        self.put_state(s)
        self.log(f"Set {key} to {value}")

    # ---- reading ----------------------------------------------------------------------------------------------
    @staticmethod
    def live(entries):
        return [e for e in entries or [] if e.get("enabled", True) and not e.get("archived")]

    @classmethod
    def served_rules(cls, name: str, entries) -> list:
        """The rules of one layer the card carries: the live ones, and in base the FLOOR rules whatever their switch
        says. Switched off, undone, or restored to a version where they were off, the floor would leave the relay card
        and the full card both (review of 1.2.2, S6); the toggle and undo refuse it, and a hand edit cannot take it
        off either. Only deleting the rule from the file removes it."""
        live = cls.live(entries)
        if name != "base":
            return live
        keep = {id(e) for e in live}
        return [e for e in entries or [] if id(e) in keep or (isinstance(e, dict) and e.get("id") in FLOOR)]

    @staticmethod
    def _floor_guard(name: str, rule_id: str, what: str) -> None:
        if name == "base" and rule_id in FLOOR:
            raise Refused(f"{rule_id} is on every card, relayed or not, so it cannot be {what}; change its words in "
                          f"the editor if they are wrong")

    @staticmethod
    def hand_written(x: dict) -> bool:
        """A rule that carries none of the provenance Semantext writes (WRITTEN_BY): typed into the file by hand, by
        the user in the page's editor or by any other program. Its file says nothing of who wrote it."""
        p = x.get("provenance")
        return not (isinstance(p, dict) and p.get("type") in WRITTEN_BY)

    @staticmethod
    def _line(x: dict) -> str:
        """One rule as the card shows it, with a mark when it is not the user's own rule as written."""
        p = provenance_of(x)
        mark = (" (learned)" if p.get("type") == "LEARNED" else
                f" (proposed by {p.get('by') or 'an agent'}, added by the user: not the user's own words)"
                if p.get("type") == "PROPOSED" else "")
        return f"- {x.get('id', '?')}: {' '.join(str(x.get('statement', '')).split())}{mark}"

    def plan(self, name: str, form: str = "full", agent: str | list | None = None) -> dict:
        """What the card holds, layer by layer: the shared base, the environment, then the agent's own rules. card()
        writes it out; the hook and the page report it, so what they show is what was built.

        form "relay" is for a prompt that is not the user's own message (another agent's, a tool's notice): only the
        rules marked relay, and those marked always, which every card carries. The short card needs its floor from the
        base itself: if the base marks no rule always (a home made before the marks existed, or a base whose marks
        were taken off), or no file marks a relay rule, the full card is given, so the short card never drops a rule
        the user relies on, whatever an environment marks."""
        chain = ["base", name] if name != "base" else ["base"]
        # An agent's own rules: its layer, and any carried to it (a list of names, its own first; see agents.own_names).
        names = [agent] if isinstance(agent, str) else list(agent or [])
        layers = self.layers(self.load(name)) if names and name != "base" else {}
        own = [x for n in dict.fromkeys(names) for x in self.live(layers.get(n) or [])]
        agent = names[0] if names else None
        kind = lambda n: "base" if n == "base" else "environment"   # noqa: E731
        if form == "relay":
            on_floor = lambda x: x.get("always") or x.get("id") in FLOOR   # noqa: E731  by mark, or by id
            floor = [x for x in self.served_rules("base", self.load("base").get("entries")) if on_floor(x)]
            picked = [(n, [x for x in self.served_rules(n, self.load(n).get("entries"))
                           if x.get("relay") or on_floor(x)]) for n in chain]
            picked.append((agent, [x for x in own if x.get("relay") or x.get("always")]))
            if floor and any(x.get("relay") for _, xs in picked for x in xs):
                return {"form": "relay", "environment": name, "title": self.title(name), "agent": agent,
                        "layers": [{"layer": kind(n) if i < len(chain) else "agent", "name": n, "rules": xs}
                                   for i, (n, xs) in enumerate(picked) if xs]}
        title = self.title(name)   # read first, as the card always has: with two broken files, it names this one
        out = []
        for n in chain:
            d = self.load(n)
            e = d["environment"]
            out.append({"layer": kind(n), "name": n, "rules": self.served_rules(n, d.get("entries")),
                        "heading": f"{e.get('title', e['id'])} {e.get('version', '')} "
                                   f"({str(e.get('scope', n)).split('.')[0]})",
                        "tests": len(d.get("tests") or [])})
        if own:   # last, so the shared rules come first and are never crowded out by one agent's own
            out.append({"layer": "agent", "name": agent, "rules": own})
        return {"form": "full", "environment": name, "title": title, "agent": agent, "layers": out}

    def render(self, plan: dict) -> str:
        """The card's text, from its plan."""
        if plan["form"] == "relay":
            return "\n".join([
                f"# Semantext: this prompt is NOT the user's own message ({plan['title']} environment)",
                "It comes from another agent, a tool or a notice. Only the rules for relayed words, and the ones",
                "that always apply, are shown here; the full card comes with the user's own messages.", ""]
                + [f"- {x.get('id', '?')}: {' '.join(str(x.get('statement', '')).split())}"
                   for layer in plan["layers"] for x in layer["rules"]])
        lines = [f"# Semantext: standing rules for reading this user ({plan['title']} environment)",
                 "Follow these rules when you read the user's messages, unless a message itself says otherwise."]
        # One line for every hand-written rule, never a mark on each: the card is under the hook's byte limit, and a
        # mark per rule grew it with every such rule. The page marks each one.
        n = sum(self.hand_written(x) for layer in plan["layers"] for x in layer["rules"])
        if n:
            lines.append(hand_written_line(n))
        for layer in plan["layers"]:
            if layer["layer"] == "agent":
                lines += ["", f"## For {layer['name']} only", LAYER_NOTE] + [self._line(x) for x in layer["rules"]]
            else:
                lines += ["", f"## {layer['heading']}"] + [self._line(x) for x in layer["rules"]]
                n = layer.get("tests") or 0
                if n:   # the rules are grounded in the user's own corrections, and the AI is told how many
                    lines.append(f"  ({n} of the user's corrections {'is' if n == 1 else 'are'} kept as tests for "
                                 f"these rules: the message an AI misread, and the rule that reads it right)")
        return "\n".join(lines)

    def card(self, name: str, form: str = "full", agent: str | list | None = None) -> str:
        """The card the AI receives: a header, the shared base rules, the environment's own rules, then the agent's
        (see plan)."""
        return self.render(self.plan(name, form, agent))

    def served(self, name: str, form: str = "full", agent: str | list | None = None) -> tuple[str, dict]:
        """The card as the hook and the MCP server hand it out, and its plan. If the environment's file cannot be
        read, the AI still gets the base rules, with one line naming the file and the problem; if the base cannot be
        read either, that line alone. `semantext card` refuses instead, so the person sees the problem plainly."""
        self.state()
        head = f"Semantext: {self.state_problem}.\n\n" if self.state_problem else ""
        try:
            p = self.plan(name, form, agent=agent)
            return head + self.render(p), {**p, "problem": bool(head)}
        except (Refused, OSError) as e:
            problem = f"Semantext: {e}. Until it is fixed, only the base rules are shown."
        try:
            p = self.plan("base", form)
            return head + problem + "\n\n" + self.render(p), {**p, "environment": name, "problem": True}
        except (Refused, OSError) as e:
            return (head + problem + f" The base rules could not be read either: {e}.",
                    {"form": form, "environment": name, "title": name, "agent": None, "layers": [], "problem": True})

    def served_card(self, name: str, form: str = "full", agent: str | list | None = None) -> str:
        """The card's text as served (see served)."""
        return self.served(name, form, agent)[0]

    def overview(self) -> dict:
        s = self.state()
        out, problems = [], []
        for n in self.names():
            try:
                d = self.load(n)
            except (Refused, OSError) as e:   # one broken file never takes the others, or the page, down with it
                problems.append({"name": n, "problem": str(e)})
                continue
            live = self.live(d.get("entries"))
            out.append({"name": n, "title": d["environment"].get("title", n.title()),
                        "scope": d["environment"].get("scope", ""), "rules": len(live),
                        "learned": sum(1 for x in live if provenance_of(x).get("type") == "LEARNED"),
                        "features": [k for k in FEATURES if any(x["id"] == f"feature.{k}" for x in live)]})
        return {"active": s["active"], "model": s["model"], "feed": bool(s.get("feed", True)),
                "hear_prompts": bool(s.get("hear_prompts")), "profiles": out, "log": s["log"][-25:][::-1],
                "pending": s["pending"], "problems": problems + ([{"name": "state.json", "problem": self.state_problem}]
                                                                 if self.state_problem else [])}

    # ---- writes -----------------------------------------------------------------------------------------------
    def layers(self, d: dict) -> dict[str, list]:
        """An environment's agent layers: {agent name: its own entries}. A layer is served to that agent only."""
        a = d.get("agents")
        if not isinstance(a, dict):
            return {}
        return {k: (v.get("entries") or []) for k, v in a.items() if isinstance(v, dict)}

    def every_entry(self, d: dict) -> list:
        """The environment's rules and every agent layer's, together: one id space."""
        return [*(d.get("entries") or []), *(e for es in self.layers(d).values() for e in es)]

    def _entry(self, d: dict, rule_id: str) -> dict:
        for x in self.every_entry(d):
            if isinstance(x, dict) and x.get("id") == rule_id:
                return x
        raise Refused(f"no rule {rule_id!r} in this environment")

    def set_active(self, name: str) -> None:
        self.path(name)
        if name == "base":
            raise Refused("base is shared by every environment; pick an environment")
        s = self.state()
        s["active"] = name
        self.put_state(s)
        self.log(f"Switched to the {self.title(name)} environment")

    # ---- new environments, from suggestions ------------------------------------------------------------------
    def packs(self) -> list[dict]:
        return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(self.suggest_dir.glob("*.yaml"))]

    def suggest(self, title: str) -> dict:
        """Suggested rules for an environment called `title`. A pack matches when a word of the name is one of its
        keywords (or shares its first four letters: 'studies' finds 'study'). Matched packs offer all their rules,
        ticked; with no match, one rule from each pack is offered as an idea, unticked."""
        words = set(re.findall(r"[a-z]+", (title or "").lower()))
        packs = self.packs()

        def hit(p):
            keys = [str(k).lower() for k in p["environment"].get("keywords") or []]
            return bool(words & set(keys)) or any(len(w) >= 4 and len(k) >= 4 and w[:4] == k[:4]
                                                  for w in words for k in keys)
        matched = [p for p in packs if hit(p)]
        chosen = matched or packs
        rules = []
        for p in chosen:
            env = p["environment"]
            for e in (p.get("entries") or [])[: None if matched else 1]:
                rules.append({"pack": env["id"], "pack_title": env.get("title", env["id"]), "id": e["id"],
                              "statement": e["statement"], "mode": e.get("mode", "stationary"),
                              "ticked": bool(matched)})
        return {"matched": bool(matched),
                "packs": [p["environment"].get("title", p["environment"]["id"]) for p in chosen], "rules": rules}

    def create(self, title: str, picks: list) -> str:
        """A new environment, named by you, holding the suggested rules you kept. Never overwrites one."""
        title = (title or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 '\-]{0,39}", title):
            raise Refused("name it with letters, numbers and spaces, up to 40 characters")
        # A title already in use gets a number, so the switcher never shows two the same: Cooking, then Cooking 2.
        taken = {t.lower() for t in self.titles()[0].values()}   # a broken file is skipped (review of 1.2.2, S4)
        if title.lower() in taken:
            k = 2
            while f"{title} {k}".lower() in taken:
                k += 1
            title = f"{title} {k}"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:28] or "environment"
        if not slug[0].isalpha():
            slug = "e-" + slug
        # Before the taken-name check: on Windows a reserved name such as "nul" reads as an existing folder.
        if slug in RESERVED:
            raise Refused(f"{title!r} is a name Windows reserves for a device; pick another")
        stem, n = slug, 2
        while (self.profiles_dir / slug).exists() or slug == "base":
            slug, n = f"{stem}-{n}", n + 1
        if not valid_name(slug):
            raise Refused("that name cannot be used")
        index = {(p["environment"]["id"], e["id"]): e for p in self.packs() for e in p.get("entries") or []}
        entries, seen = [], set()
        for pk in picks or []:
            key = (pk.get("pack"), pk.get("id"))
            if key not in index:
                raise Refused(f"no such suggestion: {key[1]}")
            if key in seen:
                continue
            seen.add(key)
            e = index[key]
            entries.append({"id": f"{slug}.{e['id'].split('.', 1)[-1]}", "kind": "rule", "statement": e["statement"],
                            "applies_when": e.get("applies_when", ""), "mode": e.get("mode", "stationary"),
                            "enabled": True,
                            "provenance": {"type": "SUGGESTED", "pack": key[0], "from": key[1], "when": now()}})
        env = {"environment": {"id": slug, "version": "0.1.0", "status": "candidate", "owner": "you", "title": title,
                               "scope": f"Made for {title}" + (f", from {len(entries)} suggested rules."
                                                               if entries else "."),
                               "inherits": [f"base@{self._base_version()}"]},
               "entries": entries, "tests": []}
        (self.profiles_dir / slug).mkdir(parents=True)
        write_atomic(self.profiles_dir / slug / "SEMANTICS.yaml", dump(env))
        s = self.state()
        s["active"] = slug
        self.put_state(s)
        self.log(f"Made the {title} environment, with {len(entries)} suggested rule{'s' if len(entries) != 1 else ''}")
        return slug

    def ideas(self, name: str) -> list[dict]:
        """Every pack's suggested rules, each marked with whether this environment already holds it."""
        have = {x.get("id") for x in self.load(name).get("entries") or []}
        return [{"pack": p["environment"]["id"], "title": p["environment"].get("title", p["environment"]["id"]),
                 "rules": [{"id": e["id"], "statement": e["statement"], "mode": e.get("mode", "stationary"),
                            "held": f"{name}.{e['id'].split('.', 1)[-1]}" in have} for e in p.get("entries") or []]}
                for p in self.packs()]

    def add_suggestions(self, name: str, ids: list[str]) -> list[str]:
        """Add suggested rules, from any pack, to an environment that already exists. A rule it already holds is
        skipped. Returns the ids of the rules added."""
        d = self.load(name)
        d["entries"] = d.get("entries") or []
        index = {e["id"]: (p["environment"]["id"], e) for p in self.packs() for e in p.get("entries") or []}
        missing = [i for i in ids if i not in index]
        if missing:
            raise Refused(f"no such suggestion: {', '.join(missing)} (see them with: semantext env ideas)")
        have = {x.get("id") for x in d["entries"]}
        added = []
        for i in dict.fromkeys(ids):
            pack, e = index[i]
            rid = f"{name}.{i.split('.', 1)[-1]}"
            if rid in have:
                continue
            d["entries"].append({"id": rid, "kind": "rule", "statement": e["statement"],
                                 "applies_when": e.get("applies_when", ""), "mode": e.get("mode", "stationary"),
                                 "enabled": True, "provenance": {"type": "SUGGESTED", "pack": pack, "from": i,
                                                                 "when": now()}})
            have.add(rid)
            added.append(rid)
        if added:
            self.save(name, d)
            self.log(f"Added {len(added)} suggested rule{'s' if len(added) != 1 else ''} to {self.title(name)}")
        return added

    def toggle(self, name: str, rule_id: str) -> bool:
        d = self.load(name)
        x = self._entry(d, rule_id)
        if x.get("enabled", True):
            self._floor_guard(name, rule_id, "switched off")
        x["enabled"] = not x.get("enabled", True)
        self.save(name, d)
        self.log(f"Turned {'on' if x['enabled'] else 'off'} {rule_id} in {self.title(name)}")
        return x["enabled"]

    def pin(self, name: str, rule_id: str) -> str:
        d = self.load(name)
        x = self._entry(d, rule_id)
        x["mode"] = "adaptive" if x.get("mode") == "stationary" else "stationary"
        self.save(name, d)
        self.log(f"Made {rule_id} {x['mode']} in {self.title(name)}")
        return x["mode"]

    def learn(self, name: str, words: str, provenance: dict | None = None, applies_when: str = "",
              agent: str | None = None, misread: str | None = None) -> str:
        """Your correction becomes a rule, with your exact words kept beside it. A rule an agent proposed, which you
        added (see adopt), carries that provenance instead. With `agent`, the rule goes into that agent's own layer
        of this environment, served to that agent only. With `misread`, the message your AI got wrong is kept too,
        as a test of the new rule (see cases)."""
        words = (words or "").strip()
        if not words:
            raise Refused("nothing to learn: the correction is empty")
        if len(words) > 400:
            raise Refused("keep a correction under 400 characters")
        misread = str(misread or "").strip()
        if len(misread) > MAX_CASE:
            raise Refused(f"keep the misread message under {MAX_CASE} characters")
        from .inbox import SECRET, token_like   # here, not at the top: inbox imports this module
        if misread and (SECRET.search(misread) or token_like(misread)):
            raise Refused("that message looks like it holds a key, a token or a password; it is not kept")
        d = self.load(name)
        d["entries"] = d.get("entries") or []
        if agent:
            if not AGENT_NAME_RE.fullmatch(agent):
                raise Refused("name the agent as `semantext agents` shows it")
            if d.get("agents") is not None and not isinstance(d.get("agents"), dict):
                raise Refused(f"{self.path(name)}: 'agents' must map each agent's name to its rules")
            d["agents"] = d.get("agents") or {}
            layer = d["agents"].setdefault(agent, {})
            target, prefix = layer.setdefault("entries", []), f"{name}.{agent_slug(agent)}"
            if not isinstance(target, list):
                raise Refused(f"{self.path(name)}: {agent}'s 'entries' must be a list")
        else:
            target, prefix = d["entries"], name
        # One more than the highest number in use, so an id never repeats, even after rules were removed by hand.
        taken = [int(m.group(1)) for x in self.every_entry(d) if isinstance(x, dict)
                 if (m := re.fullmatch(re.escape(prefix) + r"\.learned-(\d+)", str(x.get("id", ""))))]
        rid = f"{prefix}.learned-{1 + max(taken, default=0)}"
        where = "this agent's own rules in this environment" if agent else "this environment"
        target.append({"id": rid, "kind": "rule", "statement": words,
                       "applies_when": applies_when or f"Learned from your correction; applies in {where}.",
                       "mode": "adaptive", "enabled": True,
                       "provenance": provenance or {"type": "LEARNED", "words": words, "when": now()}})
        if misread:   # the correction kept as a test, in the back-test's case fields (docs/backtest.md)
            tests = d["tests"] = d.get("tests") or []
            taken = [int(m.group(1)) for t in tests if (m := re.fullmatch(re.escape(name) + r"\.case-(\d+)",
                                                                           str(t.get("case", ""))))]
            tests.append({"case": f"{name}.case-{1 + max(taken, default=0)}", "message": misread, "correction": words,
                          "rules": [rid], "source": "person", "grounded": "EXPLICIT", "at": now()})
        self.save(name, d)
        by, mine = (provenance or {}).get("by"), f" (for {agent} only)" if agent else ""
        self.log(f'Added {rid} in {self.title(name)}{mine}, proposed by {by}: "{words}"' if by
                 else f'Learned {rid} in {self.title(name)}{mine}: "{words}"')
        return rid

    # ---- corrections kept as tests ------------------------------------------------------------------------------
    def cases(self, name: str) -> list[dict]:
        """The environment's corrections kept as tests, each with whether it is still covered: every rule it needs is
        in the file and switched on (an agent's own rule counts for that agent's card). A rule switched off or removed
        leaves its correction uncovered: the misreading it was taught against can come back."""
        d = self.load(name)
        live = {x.get("id") for x in self.live(self.every_entry(d))}
        if name != "base":
            try:
                live |= {x.get("id") for x in self.live(self.load("base").get("entries"))}
            except Refused:
                pass
        out = []
        for t in d.get("tests") or []:
            needs = [r for r in t.get("rules") or [] if isinstance(r, str)]
            missing = [r for r in needs if r not in live]
            out.append({**t, "covered": bool(needs) and not missing, "missing": missing})
        return out

    def depends_on(self, name: str, rule_id: str) -> list[dict]:
        """The kept corrections that need this rule: what switching it off, or removing it, would uncover."""
        return [t for t in self.cases(name) if rule_id in (t.get("rules") or [])]

    def check_adoptable(self, r: dict, choice: str) -> None:
        """Before an answer that adds a proposed rule is kept: the environment it was proposed for must still exist."""
        if r.get("kind") == "rule" and str(choice or "").strip().lower() == "add":
            try:
                self.path(str(r.get("env") or ""))
            except Refused:
                raise Refused(f"#{r['id']} was proposed for the environment {r.get('env')!r}, which no longer exists: "
                              f"answer no, and teach the rule yourself where you want it")

    def adopt(self, r: dict) -> str | None:
        """A rule an agent proposed in the inbox, once the user has answered: added if they said add. It is kept as
        the agent's proposal, or, if they gave their own wording, as their words. Returns the new rule's id, or
        None if nothing was added."""
        a = r.get("answer") or {}
        if r.get("kind") != "rule" or a.get("picked") != "Add":
            return None
        by, words, agent = r.get("from") or "an agent", (a.get("words") or "").strip(), r.get("agent") or None
        if words:
            return self.learn(r["env"], words, {"type": "LEARNED", "words": words, "when": now(), "drafted_by": by,
                                                "request": r["id"]}, agent=agent)
        where = f"{agent}'s own rules in this environment" if agent else "this environment"
        return self.learn(r["env"], r["statement"],
                          {"type": "PROPOSED", "by": by, "how": r.get("from_how") or "", "request": r["id"],
                           "proposed": r.get("at"), "added": now(), "via": a.get("via")},
                          f"Proposed by {by} and added by you; applies in {where}.", agent=agent)

    def undo(self, name: str, rule_id: str) -> None:
        """Undo never deletes: the rule is archived in its file, with its words, and leaves the card."""
        d = self.load(name)
        x = self._entry(d, rule_id)
        self._floor_guard(name, rule_id, "undone")
        x["archived"], x["enabled"], x["archived_at"] = True, False, now()
        self.save(name, d)
        self.log(f"Undid {rule_id} in {self.title(name)} (kept in the file, off the card)")

    def feature(self, name: str, key: str, on: bool, country: str = "") -> None:
        if key not in FEATURES:
            raise Refused(f"no such feature: {key}")
        statement, mode = FEATURES[key]
        if key == "news":
            country = re.sub(r"[^A-Za-z .'-]", "", country or "")[:40].strip() or "my country"
            statement = statement.format(country=country)
        d = self.load(name)
        d["entries"] = d.get("entries") or []
        rid = f"feature.{key}"
        old = [x for x in d["entries"] if x.get("id") == rid]
        if on:
            if old:
                old[0].update(statement=statement, enabled=True, archived=False)
            else:
                d["entries"].append({"id": rid, "kind": "rule", "statement": statement,
                                     "applies_when": "Always, while this switch is on.", "mode": mode,
                                     "enabled": True, "provenance": {"type": "SETTING", "when": now()}})
        elif old:
            old[0]["enabled"] = False
        self.save(name, d)
        self.log(f"{key.title()} turned {'on' if on else 'off'} in {self.title(name)}")

    def undo_last(self, name: str) -> str:
        """Undo the last change to an environment, whatever it was: restore the newest saved version. Nothing is
        deleted. The version undone is kept as '...-redo.yaml', and the version restored is marked '...-used.yaml'
        so the next undo goes one step further back."""
        p = self.path(name)
        # Only this environment's own versions: "work-*" would also match "work-2-..." and "work-a-...".
        own = re.compile(re.escape(name) + r"-\d{8}-\d{6}-\d{6}")
        cands = sorted(h for h in self.history_dir.glob(f"{name}-*.yaml") if own.fullmatch(h.stem))
        if not cands:
            raise Refused("nothing to undo in this environment")
        newest = cands[-1]
        try:   # what the restore takes off; a file broken by a hand edit cannot say, but it is kept all the same
            before = {x.get("id") for x in self.every_entry(self.load(name))}
        except Refused:
            before = None
        mark = stamp(p.name for p in self.history_dir.glob(f"{name}-*.yaml"))
        kept = self.history_dir / f"{name}-{mark}-redo.yaml"
        current, restored = read_settled(p, binary=True), read_settled(newest, binary=True)   # both before any write
        write_atomic(kept, current)
        write_atomic(p, restored)
        # The restore has happened: from here on nothing raises (review of 1.2.2, S5). A step that fails is named in
        # last_undo["problem"] and in the log, and the caller says so.
        problems = []
        try:
            newest.replace(newest.with_name(newest.stem + "-used.yaml"))
        except OSError as e:
            problems.append(f"the restored version could not be marked as used ({e}), so the next undo may restore it "
                            f"again")
        try:
            after = {x.get("id") for x in self.every_entry(self.load(name))}
        except (Refused, OSError) as e:
            after = set()
            problems.append(f"the restored version cannot be read: {e}")
        problem = "; ".join(problems) or None
        self.last_undo = {"kept": str(kept), "took_off": None if before is None else sorted(before - after),
                          "problem": problem}
        try:
            self.log(f"Undid the last change in {self.title_or_name(name)}; the version it replaced is kept as "
                     f"{kept.name}" + (f". Problem: {problem}" if problem else ""))
        except OSError as e:
            self.last_undo["problem"] = "; ".join(filter(None, [problem, f"the log could not be written ({e})"]))
        return newest.name

    def source(self, name: str) -> str:
        return read_settled(self.path(name))

    def write_source(self, name: str, text: str) -> None:
        """The editor's save. Refused unless the text is a valid environment for the same name, so a typo cannot
        break it."""
        try:
            d = yaml.safe_load(text)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            at = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            raise Refused(f"not valid{at}: {getattr(e, 'problem', None) or str(e).splitlines()[0]}")
        if not isinstance(d, dict) or not isinstance(d.get("environment"), dict):
            raise Refused("an environment needs an 'environment' section")
        if d["environment"].get("id") != name:
            raise Refused(f"the environment id must stay {name!r}")
        check_environment(d, "the text")   # the same check as reading the file: what saves will also load
        entries = d.get("entries") or []
        every = self.every_entry(d)
        ids = [x["id"] for x in every]
        if len(set(ids)) != len(ids):
            raise Refused("two rules share an id")
        self._keep(name)
        write_atomic(self.path(name), text)
        self.log(f"Edited {self.title(name)} by hand ({len(entries)} rules)")

    # ---- reading a message: cue words only ---------------------------------------------------------------------
    MATERIAL = re.compile(r"\b(send|email|publish|post|buy|pay|order|delete|remove all|wipe|download|install|"
                          r"share|upload|transfer)\b", re.I)
    COMMON = {"that", "this", "with", "from", "have", "what", "when", "your", "will", "just", "like", "them", "then",
              "they", "there", "about", "would", "could", "should", "please", "into", "only", "more", "some", "want",
              "make", "does", "been", "were", "it's", "i'm", "can't", "don't", "maybe", "every", "thing", "things"}

    def read(self, name: str, message: str, dry: bool = False, entries: list | None = None) -> dict:
        """How a message is read before your AI acts on it, from cue words. dry=True saves nothing: the page's
        opening example uses it, so a reload never piles up pending decisions. `entries`, when given, stands in for
        the environment's own rules: the back-test reads the same message with another card."""
        m = (message or "").strip()
        low = m.lower()
        out = []
        if not m:
            return {"readings": [], "decisions": [], "touched": []}
        if m.endswith("?") or re.match(r"^(who|what|where|when|why|how|can|could|should|would|is|are|do|does|did)\b",
                                       low):
            out.append(("A question", "It answers, and changes nothing until you ask it to.",
                        "base.question-not-instruction"))
        if re.search(r"\b(maybe|we could|we should|i was thinking|what if|perhaps|might)\b", low):
            out.append(("A suggestion", "It opens options. It won't treat this as an order.",
                        "base.suggest-not-require"))
        if re.match(r"^(yes|yeah|yep|ok|okay|go ahead|do it|let'?s do (it|that)|sounds good|sure)\b", low):
            out.append(("A yes", "It accepts the latest offer exactly as offered, and says which reading it took.",
                        "base.yes-binds-to-offer"))
        if re.search(r"\b(park|parked|hold off|not now|pause|shelve)\b", low):
            out.append(("A pause", "What you park stays parked until you reopen it.", "base.parked-stays-parked"))
        t = re.search(r"\b(for now|tonight|tomorrow|next week|later|this weekend)\b", low)
        if t:
            out.append(("A time limit", f'Kept word for word: "{t.group(1)}". No date is invented.',
                        "base.time-kept-verbatim"))
        # "no," ends in a comma, so no word boundary may follow it (", " has none: the old pattern never matched it).
        if re.search(r"\b(?:no,|(?:don'?t|stop|that'?s wrong|not what i)\b)", low):
            out.append(("A correction", "Kept as a rule with your exact words. Use Teach it to keep it.",
                        "base.corrections-become-rules"))
        if not out:
            out.append(("An instruction", "It acts, within this environment's rules, and shows what it did.",
                        "base.show-your-work"))
        kinds = {"A question": "question", "A suggestion": "suggestion", "A yes": "yes", "A pause": "pause",
                 "A time limit": "time", "A correction": "correction", "An instruction": "instruction"}
        # Which of this environment's own rules the words touch: shared meaningful words (four letters or more,
        # not common ones). A stand-in: an AI reading with the card can say which apply more precisely.
        said = {w for w in re.findall(r"[a-z']+", low) if len(w) >= 4 and w not in self.COMMON}
        touched = []
        try:
            for e in self.live(self.load(name).get("entries") if entries is None else entries):
                if said & {w for w in re.findall(r"[a-z']+", str(e.get("statement", "")).lower()) if len(w) >= 4}:
                    touched.append(e["id"])
        except Refused:
            pass
        decisions = []
        for v in sorted({x.lower() for x in self.MATERIAL.findall(m)}):
            decisions.append({"id": f"d{datetime.now().strftime('%H%M%S%f')}-{v}",
                              "ask": f'Needs your word before it can "{v}": that leaves your machine or cannot be '
                                     f'undone.',
                              "rule": "base.irreversible-needs-your-word", "message": m[:160]})
        if decisions and not dry:
            s = self.state()
            s["pending"] = (s["pending"] + decisions)[-12:]
            self.put_state(s)
        return {"readings": [{"label": a, "says": b, "rule": c, "kind": kinds[a]} for a, b, c in out],
                "decisions": decisions, "touched": touched}

    def decide(self, did: str, answer: str) -> None:
        s = self.state()
        hit = [d for d in s["pending"] if d["id"] == did]
        if not hit:
            raise Refused("no such pending decision")
        s["pending"] = [d for d in s["pending"] if d["id"] != did]
        self.put_state(s)
        word = "Yes" if answer == "yes" else "No"
        self.log(f"You said {word}: {hit[0]['ask'].split(':')[0]}")

    # ---- models: names only, nothing is started or downloaded --------------------------------------------------
    @staticmethod
    def local_models(base: Path | None = None) -> list[str]:
        base = ollama_manifests() if base is None else base
        if not base.is_dir():
            return []
        return sorted(f"{m.name}:{t.name}" for m in base.iterdir() if m.is_dir() for t in m.iterdir() if t.is_file())

    def set_model(self, model: str | None) -> None:
        if model is not None and model not in self.local_models():
            raise Refused("that model is not on this machine")
        s = self.state()
        s["model"] = model
        self.put_state(s)
        self.log(f"Chose the model {model}" if model else "Cleared the model choice")
