"""Git's settings as git finds them on a machine: the system's and your own settings files, and each file with its
includes followed in the order git applies them. Also the small file-reading helpers every part of the reader uses.

It opens files for reading and never writes or runs anything. Where it cannot be sure (an include git applies only on
a condition, a variable that moves where git looks) it says so in the notes it returns.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Mapping, NamedTuple

from .. import problem
from .values import WINDOWS, git_absolute, include_condition, parse_bool, parse_config, sha1_only_problem, value_problem

MAX_FILE = 1_000_000     # a settings file or an .identity over this is a problem, never read (the seats file has its
#                          own cap, 4 MB, the one every reader reads it by: pathrule.MAX_SEATS)
MAX_INCLUDES = 10        # how deep git lets includes nest (measured: ten files deep work, eleven are refused)
MAX_VISITS = 500         # files opened while following the includes of one settings file
# Variables that change where git finds its settings. They are named, not evaluated.
NOT_EVALUATED = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG", "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")
CONDITIONS = ("gitdir:", "gitdir/i:", "onbranch:", "hasconfig:remote.*.url:")   # the includeIf kinds git knows
# Where a packaged git keeps its system settings file when no git on the path names one: a distribution's, then Homebrew's
SYSTEM_FILES = ("/etc/gitconfig", "/usr/local/etc/gitconfig", "/opt/homebrew/etc/gitconfig")


class Cannot(Exception):
    """A file the checker would crash on: the worktree gets no answer, and says why."""


class Setting(NamedTuple):
    key: str
    value: str | None
    scope: str
    file: str
    line: int
    via: tuple           # the files that included this one, outermost first


class World(NamedTuple):
    """Where git looks for its settings on a machine: the environment, the user's home, the system level's files."""
    env: Mapping
    home: Path
    system: tuple        # the system-level settings files, lowest priority first
    tried: tuple = ()    # every place looked at for the system file
    notes: tuple = ()    # what about this machine makes an answer less than sure
    prefix: Path | None = None   # git's install prefix, the folder "%(prefix)/" names (None when it was not found)


class Parsed(NamedTuple):
    settings: list       # (name, value, line) in the order written
    error: tuple | None  # (line, why): the first thing git would refuse
    unread: str | None   # why the file could not be read at all


class Expanded(NamedTuple):
    """One settings file with every include replaced by what it brings in, in the order git applies them."""
    settings: list
    notes: list          # what could not be settled
    refused: list        # what git would refuse to run with
    unread: list         # files that could not be read, so there is no answer
    files: list
    sha1_only: list      # (file, line, why): what git refuses only in a SHA-1 repository (a core.abbrev over 40)


_LONE = re.compile("[\ud800-\udc7f\udd00-\udfff]")   # a lone surrogate that is no escaped byte (a Windows name can hold one)


def show(path) -> str:
    """A path as the record writes it: forward slashes, and a byte that was not UTF-8 (kept as a surrogate escape so
    the file can still be opened, D1) written as U+FFFD, so the record is always text. Any other lone surrogate (a
    Windows name, or a JSON escape in the seats file) is written as U+FFFD too: this never raises (F1)."""
    text = _LONE.sub("�", str(path).replace("\\", "/"))
    return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")


def resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def same_place(a, b) -> bool:
    """Whether two paths name the same folder or file: by identity when both exist, else by their spelling."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except (OSError, ValueError):
        pass
    return os.path.normcase(str(resolved(Path(a)))) == os.path.normcase(str(resolved(Path(b))))


def read_text(path, problems: list, strict: bool = False, lossy: set | None = None) -> str | None:
    """The text of a small file, or None with a problem. Not UTF-8: refused when strict, else read with replacements
    (and the file's key, as SettingsReader keys a file, is put in `lossy` when one is given)."""
    try:
        if os.path.getsize(path) > MAX_FILE:
            problems.append(problem(path, None, "too-big", f"over {MAX_FILE} bytes; not read"))
            return None
        raw = Path(path).read_bytes()
    except (OSError, ValueError) as e:
        problems.append(problem(path, None, "unreadable", e))
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        problems.append(problem(path, None, "not-utf8", "not valid UTF-8" + ("" if strict else "; read with replacements")))
        if not strict and lossy is not None:
            lossy.add(file_key(path))
        return None if strict else raw.decode("utf-8", errors="replace")


def file_key(path) -> str:
    """A file as the reader keys it: one key for every spelling of its path."""
    return os.path.normcase(os.path.abspath(path))


def last_setting(settings: list, key: str) -> Setting | None:
    return next((s for s in reversed(settings) if s.key == key), None)


# ---- where git looks on this machine --------------------------------------------------------------------------------
def normalised(env: Mapping) -> dict:
    """The variables as git sees them. Windows matches their names without regard to case, so there they are upper-cased."""
    return {(k.upper() if os.name == "nt" else k): v for k, v in env.items()}


def user_home(env: Mapping) -> Path:
    """The home git uses: HOME, else (on Windows) the home drive and path when that folder is there, else the profile."""
    if env.get("HOME"):
        return Path(env["HOME"])
    drive, tail = env.get("HOMEDRIVE"), env.get("HOMEPATH")
    if drive and tail and os.path.isdir(drive + tail):
        return Path(drive + tail)
    if env.get("USERPROFILE"):
        return Path(env["USERPROFILE"])
    return Path.home()


def git_folders(env: Mapping) -> list:
    """The folders on the path that hold a git program, in the order the path lists them."""
    return [Path(f) for f in (env.get("PATH") or "").split(os.pathsep)
            if f and any(os.path.isfile(os.path.join(f, n)) for n in ("git.exe", "git"))]


def system_candidates(env: Mapping) -> list:
    """Where the system settings file may be: beside the git on the path first (Git for Windows keeps it in
    <install>/etc/gitconfig), then the usual installs."""
    out = []
    for folder in git_folders(env):
        top = folder.parent                 # <install> for cmd/ and bin/, <install>/mingw64 for mingw64/bin/
        out.append(top / "etc" / "gitconfig")
        if top.name.lower().startswith("mingw"):
            out.append(top.parent / "etc" / "gitconfig")
        else:                               # a 64-bit Git for Windows, or a 32-bit one (as install_prefix finds it)
            out += [top / sub / "etc" / "gitconfig" for sub in ("mingw64", "mingw32")]
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        if env.get(var):
            out.append(Path(env[var]) / "Git" / "etc" / "gitconfig")
    if env.get("LOCALAPPDATA"):
        out.append(Path(env["LOCALAPPDATA"]) / "Programs" / "Git" / "etc" / "gitconfig")
    out += [Path(p) for p in SYSTEM_FILES]
    return list(dict.fromkeys(out))


def install_prefix(env: Mapping) -> Path | None:
    """What "%(prefix)/" in a path setting stands for: the folder above the bin folder the real git program runs from.
    Git for Windows runs it from <install>/mingw64/bin (the git in <install>/cmd and the one in <install>/bin hand over
    to it, C8); elsewhere it is the folder above bin. None when no git program is on the path."""
    for folder in git_folders(env):
        top = folder.parent
        if folder.name.lower() in ("cmd", "bin"):
            for sub in ("mingw64", "mingw32"):
                if any((top / sub / "bin" / n).is_file() for n in ("git.exe", "git")):
                    return top / sub
        return top
    return None


def system_level(env: Mapping) -> tuple:
    """(places tried, files read, notes): git's system level, honouring GIT_CONFIG_NOSYSTEM and GIT_CONFIG_SYSTEM."""
    if "GIT_CONFIG_NOSYSTEM" in env and parse_bool(env["GIT_CONFIG_NOSYSTEM"]):
        return (), (), ()
    if "GIT_CONFIG_SYSTEM" in env:
        one = env["GIT_CONFIG_SYSTEM"]
        return ((one,), (Path(one),), ()) if one else ((), (), ())
    tried = system_candidates(env)
    found = next((p for p in tried if os.path.isfile(p)), None)
    files, notes = ([found] if found else []), []
    if not found:
        notes.append("no system settings file was found, so none was read (looked in: "
                     + ", ".join(show(p) for p in tried[:4]) + ", ...)")
    program_data = env.get("PROGRAMDATA")
    if os.name == "nt" and program_data and os.path.isfile(Path(program_data) / "Git" / "config"):
        files.insert(0, Path(program_data) / "Git" / "config")
        notes.append(f"{show(files[0])} exists; it is read first among the system files, an order taken on trust")
    return tuple(tried), tuple(files), tuple(notes)


def this_machine(env: Mapping | None = None) -> World:
    env = normalised(os.environ if env is None else env)
    tried, files, notes = system_level(env)
    notes = [*notes, *(f"{n} is set; git's settings may come from a place this reader does not look"
                       for n in NOT_EVALUATED if env.get(n))]
    return World(env, user_home(env), tuple(files), tuple(str(t) for t in tried), tuple(notes), install_prefix(env))


def global_files(world: World) -> tuple:
    """Your own settings files, lowest priority first: the XDG one, then ~/.gitconfig."""
    env = world.env
    if "GIT_CONFIG_GLOBAL" in env:
        return (Path(env["GIT_CONFIG_GLOBAL"]),) if env["GIT_CONFIG_GLOBAL"] else ()
    xdg = env.get("XDG_CONFIG_HOME")
    return ((Path(xdg) if xdg else world.home / ".config") / "git" / "config", world.home / ".gitconfig")


# ---- one settings file and its includes ----------------------------------------------------------------------------
class SettingsReader:
    """The part of the reader that opens settings files. Holds what was already parsed, so a settings file shared by
    every worktree is opened once and its problems are reported once."""

    def __init__(self, world: World, problems: list):
        self.world, self.problems = world, problems
        self._parsed, self._expanded, self._said, self._might, self._format = {}, {}, set(), {}, {}
        self.lossy: set = set()      # the files read with replacements (by file_key): a U+FFFD there may be a byte
        self.lossy_shown: set = set()    # the same files, as the record shows them

    def report(self, path, line, kind: str, text: str) -> None:
        """A problem, once: the same include or setting is met again by every worktree that reads the file, and by any
        spelling of its path (C7: keyed as parse keys a file)."""
        key = (os.path.normcase(os.path.abspath(path)), line, kind, text)
        if key not in self._said:
            self._said.add(key)
            self.problems.append(problem(path, line, kind, text))

    def parse(self, path: Path) -> Parsed | None:
        """The settings of a settings file, or None when there is no such file (git skips it)."""
        key = os.path.normcase(os.path.abspath(path))
        if key not in self._parsed:
            got = None
            if os.path.isfile(path):
                text = read_text(path, self.problems, lossy=self.lossy)
                if key in self.lossy:
                    self.lossy_shown.add(show(path))
                if text is None:
                    got = Parsed([], None, "could not be read")
                else:
                    settings, error = parse_config(text)
                    got = Parsed(settings, error, None)
                    if error:
                        why = f"{error[1]}; git would refuse to run in any repository that reads this file"
                        self.problems.append(problem(path, error[0], "bad-config", why))
            self._parsed[key] = got
        return self._parsed[key]

    def include_target(self, value: str, source: Path) -> tuple:
        """(the file an include.path names, None), or (None, why it cannot be told). Git expands "%(prefix)/" to its
        install prefix, "~" and "~/" to the home, and (on Windows) a path that starts with a single "/" as it would
        "%(prefix)/" and the rest; "~name/" needs the user database, which this does not read."""
        if value.startswith("~"):
            if value == "~" or value.startswith("~/"):
                return self.world.home / value[2:], None
            return None, f"the include path {value!r} names another user's home, which only the user database can answer"
        rest = value[len("%(prefix)/"):] if value.startswith("%(prefix)/") else value[1:] if WINDOWS and value.startswith("/") else None
        if rest is not None:
            if git_absolute(rest):
                return Path(rest), None
            if self.world.prefix is None:
                return None, f"the include path {value!r} starts at git's install prefix, which was not found"
            return self.world.prefix / rest, None
        return (Path(value) if git_absolute(value) else source.parent / value), None

    def might_set_hooks(self, path: Path | None, scope: str = "global", seen: tuple = ()) -> bool:
        """Whether a file git might include on a condition could change the answer: set core.hooksPath or hold a value
        git stops on, read at the scope of the file that includes it (C9: a name read only from the system's and your
        own settings is no stop in a repository's file); looking through its own includes. `seen` holds the files
        that include it, outermost first (by file_key), as many as git counts against its depth limit (F3: a
        conditional include deep in a chain is counted from there). Each file is looked through once for each scope
        and depth, however many includes name it."""
        if path is None or len(seen) > MAX_INCLUDES:
            return True
        key = (scope, file_key(path), len(seen))
        if key not in self._might:
            self._might[key] = self._could_set_hooks(path, scope, seen)
        return self._might[key]

    def _could_set_hooks(self, path: Path, scope: str, seen: tuple) -> bool:
        got = self.parse(path)
        if got is None:
            return os.path.exists(path)               # not there: skipped. A folder is no file: git stops on it
        if got.error or got.unread:
            return True
        for key, value, _ in got.settings:
            if key == "core.hookspath" or value_problem(key, value, scope) or sha1_only_problem(key, value):
                return True
            cond = include_condition(key)
            if cond is None or (cond and not cond.startswith(CONDITIONS)):   # F4: a kind git never applies is no include
                continue
            target = self.include_target(value, path)[0] if value is not None else None
            if target is None or file_key(target) in seen or \
                    self.might_set_hooks(target, scope, (*seen, file_key(path))):
                return True
        return False

    def expand(self, scope: str, path: Path) -> Expanded:
        """One settings file with each include replaced by what it brings in (see Expanded)."""
        key = (scope, file_key(path))
        if key not in self._expanded:
            out = Expanded([], [], [], [], [], [])
            self._walk(scope, Path(path), (), out, [0], ())
            self._expanded[key] = out
        return self._expanded[key]

    def refuse(self, out: Expanded, path, line: int, kind: str, text: str) -> None:
        """Something git would refuse to run with: said in the worktree's doubts and once in the problems."""
        out.refused.append(f"{show(path)} line {line}: {text}")
        self.report(path, line, kind, f"{text}; git would refuse to run in any repository that reads this file")

    def _walk(self, scope: str, path: Path, via: tuple, out: Expanded, visits: list, keys: tuple) -> None:
        """`via` holds the including files as the record shows them; `keys` the same files by file_key, which tell two
        files apart even where show() writes them alike (F2: two names that are not UTF-8)."""
        got = self.parse(path)
        if got is None:
            return
        here = show(path)
        mine = (*keys, file_key(path))
        out.files.append({"scope": scope, "file": here, "included_by": via[-1] if via else None})
        if got.unread:
            out.unread.append(f"{here} {got.unread}")
            return
        for key, value, line in got.settings:
            out.settings.append(Setting(key, value, scope, here, line, via))
            cond = include_condition(key)
            if cond is None:
                why = value_problem(key, value, scope)
                if why and value is not None and "�" in value and file_key(path) in self.lossy:
                    # a.F4: the value held a byte that is not UTF-8, which the text cannot show, so what git makes of
                    # it cannot be told (git may take one byte as one character)
                    out.unread.append(f"{here} line {line}: {key} holds a byte that is not UTF-8, so whether git "
                                      f"takes its value cannot be told")
                elif why:
                    self.refuse(out, path, line, "bad-value", why)
                elif sha1_only_problem(key, value):
                    out.sha1_only.append((path, line, sha1_only_problem(key, value)))
                continue
            where = f"{here} line {line}"
            target, cannot = self.include_target(value, path) if value is not None else (None, None)
            if cond:
                if cond.startswith(CONDITIONS):          # a kind git applies on a condition; any other it never applies
                    unevaluated = f'{where}: includeIf "{cond}" is not evaluated'
                    if self.might_set_hooks(target, scope, mine):
                        out.notes.append(f"{unevaluated}, and what it includes may set core.hooksPath or make git refuse to run")
                    elif target is not None and os.path.exists(target):       # a file that is not there is skipped
                        out.notes.append(f"{unevaluated}; what it includes does not set core.hooksPath, "
                                         f"so this answer does not depend on it")
                continue
            if value is None:
                self.refuse(out, path, line, "bad-include", "include.path has no value")
            elif target is None:
                out.unread.append(f"{where}: {cannot}")
                self.report(path, line, "unknown-include", f"{cannot}; the worktrees that read this file have no answer")
            elif os.path.exists(target):               # git skips an include that is not there
                visits[0] += 1
                if not os.path.isfile(target):
                    self.refuse(out, path, line, "bad-include", f"includes {show(target)}, which is not a file")
                elif file_key(target) in mine:
                    self.refuse(out, path, line, "bad-include", "includes a file that includes it back")
                elif len(via) + 1 > MAX_INCLUDES:
                    self.refuse(out, path, line, "bad-include", f"includes go deeper than git allows ({MAX_INCLUDES})")
                elif visits[0] > MAX_VISITS:
                    if visits[0] == MAX_VISITS + 1:      # F6: said once, however many more there are
                        out.unread.append(f"{where}: more than {MAX_VISITS} includes; the rest are not followed")
                else:
                    self._walk(scope, target, (*via, here), out, visits, mine)
        if got.error:
            out.refused.append(f"{here} line {got.error[0]}: {got.error[1]}")
