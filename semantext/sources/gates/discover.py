"""Which worktrees there are, and whether git would run in each: what makes a folder a git folder and a .git file a
good one, the worktrees a repository lists, what git takes from a repository's own settings file before anything else
(its format, core.bare, core.worktree), and the seats file that names the repositories.

It opens files for reading and never writes or runs anything.
"""
from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from typing import NamedTuple

from ...pathrule import SeatsUnread, read_seats
from .. import base_of, home_base, problem, under
from .config import Expanded, SettingsReader, global_files, read_text, same_place, show
from .values import C_SPACE, NT_PATHS, git_absolute, git_number, parse_bool, parse_config, value_problem

MAX_WORKTREES = 500      # linked worktrees looked at in one repository
MAX_GITFILE = 1 << 20    # git refuses a .git file longer than this
FOLLOWS = "2.39"         # the git whose reading of a repository's format this file follows (measured with it)
# Extensions a later git reads, which git FOLLOWS does not know: ignored at format 0, refused at format 1, as that
# git does, and said by name with the version that reads them (the Fable review of 70f2d3c, F2: they were "unknown")
LATER_GIT = {"refstorage": ("refStorage", "2.45"), "relativeworktrees": ("relativeWorktrees", "2.48")}


class Seed(NamedTuple):
    top: Path
    git_dir: Path        # where this worktree keeps its own files (the common dir, for the main one)
    common: Path         # where the repository's shared files are
    name: str | None     # None for the main worktree
    exists: bool
    locked: bool
    shown: str | None = None     # the path as git lists it; None when that is `top` (it can be empty: a damaged record)
    bare: bool = False           # the repository's own folder, which has no work tree
    gone: str | None = None      # why a missing worktree is missing: "folder", "gitfile", "blank" or "empty"
    refuses: tuple = ()          # why git would refuse to run here, or would find another repository
    unsure: tuple = ()           # why this reader cannot tell what git would do here


class Format(NamedTuple):
    """What git takes from a repository's own settings file before it reads anything else (never following includes)."""
    valid: bool          # a version was given and is not negative: if not, git throws the format settings away
    on: bool             # extensions.worktreeConfig is on, so a worktree's own file is read
    refused: tuple       # why git stops at this file
    settings: tuple      # the core.bare and core.worktree lines, as (key, value, line)
    file: str
    hash: str = "sha1"   # the object format: "sha256" only where format 1 says extensions.objectformat = sha256


# ---- what makes a folder a git folder, and a .git file a good one --------------------------------------------------
def head_is_valid(raw: bytes) -> bool:
    """Whether a HEAD file reads as git needs: "ref:", blanks, then a name under refs/; or an object name (forty hex)."""
    raw = raw[:256]
    if raw.startswith(b"ref:"):
        return raw[4:].lstrip(b" \t\n\r").startswith(b"refs/")     # git's own blanks: no \v or \f (F6)
    return re.match(rb"[0-9a-fA-F]{40}", raw) is not None


def path_text(raw: bytes) -> str:
    """A path git wrote into a file, as text. Git keeps it as bytes: UTF-8 is read as UTF-8; other bytes are kept as
    the file system's own (surrogate escapes, which name the same file) on POSIX, where a name can be any bytes (D1),
    and replaced on Windows, where git writes UTF-8 and a name that is not cannot be opened."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace") if NT_PATHS else raw.decode(sys.getfilesystemencoding(),
                                                                                   errors="surrogateescape")


def common_dir_of(git_dir: Path) -> Path:
    """The folder a git folder shares its objects and refs from: the one its commondir file names, else itself. Git
    trims only the line ends from the file (F4: a tab is part of the path), and normalises the path either way."""
    path = git_dir / "commondir"
    if not os.path.isfile(path):
        return git_dir
    try:
        text = path_text(path.read_bytes()).rstrip("\r\n")
    except OSError:
        return git_dir
    if not text:
        return git_dir                                  # git refuses it: see commondir_problem
    return Path(os.path.normpath(text if git_absolute(text) else git_dir / text))


def commondir_problem(git_dir: Path) -> str | None:
    """Why git cannot read this folder's commondir file, or None: git stops on one that is empty."""
    path = git_dir / "commondir"
    try:
        if os.path.isfile(path) and not path_text(path.read_bytes()).rstrip("\r\n"):
            return "its commondir file is empty, which git cannot read"
    except OSError as e:
        return f"its commondir file cannot be read ({e})"
    return None


def git_dir_problem(path: Path) -> str | None:
    """Why git does not take this folder for a git folder, or None: it needs a HEAD that reads right and, in the folder
    it shares with (its own, unless it has a commondir file), the objects and refs folders."""
    why = commondir_problem(path)
    if why:
        return why
    head = path / "HEAD"
    try:
        if os.path.islink(head):
            good = os.readlink(head).startswith("refs/")
        else:
            with open(head, "rb") as f:
                good = head_is_valid(f.read(256))
    except OSError:
        good = False
    if not good:
        return "it has no HEAD that names a branch or a commit"
    common = common_dir_of(path)
    if "\x00" in str(common):   # before, os.access raised ValueError and the whole Gates reader stopped (the Fable
        # review of 70f2d3c, F3); a NUL is no character a folder's name can hold
        return "its commondir file names a folder with a NUL character in it, which no folder can have"
    for name in ("objects", "refs"):
        if not os.access(common / name, os.X_OK):
            return f"it has no {name} folder" + ("" if common == path else f" in {show(common)}")
    return None


def read_gitfile(dot: Path) -> tuple:
    """(the folder a .git file names, None) when git accepts the file, else (None, why git would refuse it). Git wants
    a regular file under 1 MB that starts with exactly "gitdir: ", then a path (what is left after the line breaks
    that end the file; a relative one is taken from the file's folder) that is itself a git folder."""
    try:
        info = os.stat(dot)
        if not stat.S_ISREG(info.st_mode):
            return None, f"{show(dot)} is not a file"
        if info.st_size > MAX_GITFILE:
            return None, f"{show(dot)} is too large to be a .git file"
        raw = dot.read_bytes()
    except (OSError, ValueError) as e:
        return None, f"{show(dot)} cannot be read ({e})"
    if not raw.startswith(b"gitdir: "):
        return None, f"invalid gitfile format: {show(dot)} must start with 'gitdir: '"
    end = len(raw)
    while end and raw[end - 1] in b"\r\n":
        end -= 1
    if end < 9:
        return None, f"no path in gitfile: {show(dot)}"
    text = path_text(raw[8:end].split(b"\0", 1)[0])    # a C string ends at the first NUL
    target = Path(os.path.normpath(text if git_absolute(text) else dot.parent / text))
    why = git_dir_problem(target)
    if why:
        return None, f"not a git repository: {show(dot)} names {show(target)}, and {why}"
    return target, None


def own_gitfile_problems(top: Path, admin: Path) -> tuple:
    """(why git, run in a linked worktree's folder, would refuse or look elsewhere, why it cannot be told): git uses
    whatever the folder's own .git file names, and the repository's folder `admin` that lists the worktree is only
    right when that file names it."""
    dot = top / ".git"
    if not os.path.lexists(dot):
        return (f"{show(top)} has no .git, so git looks in the folders above it",), ()
    if os.path.isdir(dot):
        return (f".git in {show(top)} is a folder, not the file that links it to this repository: git uses that folder's "
                f"own repository",), ()
    target, why = read_gitfile(dot)
    if why:
        return (why,), ()
    if not same_place(target, admin):
        return (), (f"the .git file in {show(top)} names {show(target)}, not {show(admin)}, the folder this repository keeps "
                    f"for it, so git would read the settings of that other folder",)
    return (), ()


# ---- the worktrees of a repository ----------------------------------------------------------------------------------
def linked_seed(listing: Path, wid: str, common: Path, problems: list) -> Seed | None:
    """The worktree a repository's folder for it (<common>/worktrees/<wid>) lists, as git lists it: its gitdir file names
    the worktree's .git file. A missing or empty file lists nothing. A file of blanks lists a worktree with no path."""
    folder = listing / wid
    gd = folder / "gitdir"
    if not os.path.isfile(gd):
        problems.append(problem(gd, None, "worktree-skipped", "no gitdir file, so git lists no worktree for it"))
        return None
    try:                       # a path git wrote as bytes, read as every such path is (D1, round 3 F2)
        if os.path.getsize(gd) > MAX_GITFILE:
            problems.append(problem(gd, None, "too-big", f"over {MAX_GITFILE} bytes; not read"))
            return None
        text = path_text(gd.read_bytes())
    except (OSError, ValueError) as e:
        problems.append(problem(gd, None, "unreadable", e))
        return None
    if text == "":
        problems.append(problem(gd, None, "worktree-skipped", "the gitdir file is empty, so git lists no worktree for it"))
        return None
    raw = text.rstrip(C_SPACE)                              # git trims the end of the file, never the start
    locked = os.path.exists(folder / "locked")
    if raw == "":
        problems.append(problem(gd, None, "worktree-damaged", "the gitdir file holds only blanks; git lists a worktree with "
                                                              "no path and calls it prunable"))
        return Seed(Path("."), folder, common, wid, False, locked, shown="", gone="empty")
    listed = raw[:-len("/.git")] if raw.endswith("/.git") else raw
    if raw[0] in C_SPACE:                                   # a leading blank is part of the path, which is then not absolute
        problems.append(problem(gd, None, "worktree-damaged", "the gitdir file starts with a blank, which git keeps as part of "
                                                              "the path; it names no folder, and git calls it prunable"))
        return Seed(Path(listed), folder, common, wid, False, locked, show(listed), gone="blank")
    if git_absolute(raw):
        gitfile = Path(os.path.normpath(raw))
        top, shown = (gitfile.parent if raw.endswith("/.git") else gitfile), show(listed)
    else:                                                   # relative: from git 2.48 on, taken from the admin folder
        gitfile = Path(os.path.normpath(folder / raw))
        top = gitfile.parent if raw.endswith("/.git") else gitfile
        shown = show(top)
    if os.path.exists(gitfile):
        refuses, unsure = own_gitfile_problems(top, folder)
        return Seed(top, folder, common, wid, True, locked, shown, refuses=refuses, unsure=unsure)
    return Seed(top, folder, common, wid, False, locked, shown, gone="folder" if not os.path.isdir(top) else "gitfile")


def own_folder_seed(common: Path, problems: list) -> Seed | None:
    """The main worktree of a repository whose git folder is not named .git, read from a linked worktree (D2). It is
    bare unless its own settings say otherwise (round 3 F5): core.worktree names its work tree, and core.bare = false
    with no core.worktree names none, which is a problem. Read from that one file, as git first reads it."""
    text = read_text(common / "config", [])
    settings = parse_config(text)[0] if text is not None else []
    bare = next((v for k, v, _ in reversed(settings) if k == "core.bare"), None)
    work = next((v for k, v, _ in reversed(settings) if k == "core.worktree"), None)
    if bare is not None and parse_bool(bare):
        return Seed(common, common, common, None, True, False, bare=True)
    if work:
        top = Path(os.path.normpath(work if git_absolute(work) else common / work))
        return Seed(top, common, common, None, os.path.isdir(top), False, gone=None if os.path.isdir(top) else "folder")
    if bare is not None and parse_bool(bare) is False:
        problems.append(problem(common / "config", None, "no-main-worktree",
                                "core.bare is off but core.worktree names no work tree, so the main worktree is not known"))
        return None
    return Seed(common, common, common, None, True, False, bare=True)


def find_worktrees(root: Path, problems: list) -> list:
    """The main worktree of the repository at root and each linked one, as git lists them: from the folder the
    repository keeps for each linked worktree (<common>/worktrees/<name>/gitdir names that worktree's .git file). A
    bare repository's own folder is its main worktree, which has no work tree to read."""
    dot = root / ".git"
    seeds: list = []
    if os.path.isdir(dot):
        git_dir, common = dot, common_dir_of(dot)       # D5: a commondir in the folder is honoured, as git honours it
        why = git_dir_problem(dot)
        seeds.append(Seed(root, git_dir, common, None, True, False,
                          refuses=(f"git does not take {show(dot)} for a git folder ({why}), so it looks in the folders above",)
                          if why else ()))
        if why:
            return seeds
    elif os.path.isfile(dot):
        target, why = read_gitfile(dot)
        if why:
            problems.append(problem(dot, 1, "bad-gitfile", why))
            return [Seed(root, dot, dot, None, True, False, refuses=(why,))]
        git_dir = target
        common = common_dir_of(git_dir)
        main_top = root if common == git_dir else common.parent if common.name == ".git" else None
        if main_top is None:            # D2: a folder not named .git is a bare repository's own, as when read from it
            why = git_dir_problem(common)
            if why:
                problems.append(problem(common, None, "no-main-worktree", f"the repository's own folder is not named .git, "
                                                                          f"and git does not take it for a git folder ({why})"))
            else:
                seed = own_folder_seed(common, problems)
                if seed is not None:
                    seeds.append(seed)
        else:
            why = git_dir_problem(common)
            seeds.append(Seed(main_top, common, common, None, True, False,
                              refuses=(f"git does not take {show(common)} for a git folder ({why})",) if why else ()))
    elif git_dir_problem(root) is None:
        common = common_dir_of(root)
        seeds.append(Seed(root, root, common, None, True, False, bare=True))
    else:
        problems.append(problem(dot, None, "not-a-repository", "there is no .git here, so there are no gates to read"))
        return []
    listing = common / "worktrees"
    if not os.path.isdir(listing):
        return seeds
    try:
        with os.scandir(listing) as found:
            ids = sorted(e.name for e in found if e.is_dir())
    except OSError as e:
        problems.append(problem(listing, None, "unreadable", e))
        return seeds
    if len(ids) > MAX_WORKTREES:
        problems.append(problem(listing, None, "too-many", f"{len(ids)} linked worktrees; only {MAX_WORKTREES} are read"))
    for wid in ids[:MAX_WORKTREES]:
        seed = linked_seed(listing, wid, common, problems)
        if seed is not None:
            seeds.append(seed)
    return seeds


# ---- what git takes from the repository's own file before anything else ---------------------------------------------
class RepositoryReader(SettingsReader):
    """The part of the reader that reads a repository's own settings file the way git first reads it, and puts together
    every settings file a worktree sees."""

    def repo_format(self, common: Path) -> Format:
        """The repository format, its extensions, and the core.bare and core.worktree lines of <common>/config, read the
        way git reads them first: from that one file, without following includes. With no version, or a negative one,
        git throws all of it away (but a line it cannot read still stops it)."""
        key = os.path.normcase(os.path.abspath(common))
        if key not in self._format:
            self._format[key] = self._read_format(common)
        return self._format[key]

    def _read_format(self, common: Path) -> Format:
        path = common / "config"
        got, where, refused = self.parse(path), show(path), []
        version, extensions, lines, on = None, [], [], False
        for key, value, line in (got.settings if got else []):
            if key == "core.repositoryformatversion":
                number = git_number(value)
                if number is None:
                    refused.append(f"{where} line {line}: core.repositoryformatversion "
                                   + ("has no value" if value is None else f"= {value!r} is not a number git reads"))
                else:
                    version = number
            elif key.startswith("extensions."):
                extensions.append((key[len("extensions."):], value, line))
            elif key == "core.bare":
                why = value_problem(key, value, "local")
                if why:
                    refused.append(f"{where} line {line}: {why}")
                lines.append((key, value, line))
            elif key == "core.worktree":
                if value is None:
                    refused.append(f"{where} line {line}: core.worktree has no value")
                lines.append((key, value, line))
        unknown, newer, later, hash_ = [], [], [], "sha1"
        for ext, value, line in extensions:
            here = f"{where} line {line}: extensions.{ext}"
            if ext in ("preciousobjects", "worktreeconfig"):
                said = parse_bool(value)
                if said is None:
                    refused.append(f"{here} = {value!r} is not a yes or no")
                elif ext == "worktreeconfig":
                    on = said
            elif ext in LATER_GIT:
                later.append(ext)
            elif ext == "partialclone":
                if value is None:
                    refused.append(f"{here} has no value")
            elif ext == "objectformat":
                newer.append(ext)
                if value not in ("sha1", "sha256"):
                    refused.append(f"{here} " + ("has no value" if value is None else f"= {value!r} is not a hash git knows"))
                else:
                    hash_ = value
            elif ext == "noop-v1":
                newer.append(ext)
            elif ext != "noop":
                unknown.append(ext)
        valid = version is not None and version >= 0
        if valid and version > 1:
            refused.append(f"{where}: this git reads repository format 1 at most, and this is format {version}")
        for ext in dict.fromkeys(later) if valid and version >= 1 else ():
            name, since = LATER_GIT[ext]
            refused.append(f"{where}: extensions.{name} is read only by git {since} and later; these readings follow "
                           f"git {FOLLOWS}, which refuses a format {version} repository that holds it, so no answer is "
                           f"given (with a newer git, what it would do is not read here yet)")
        if valid and version >= 1 and unknown:
            refused.append(f"{where}: unknown repository extension{'s' if len(unknown) > 1 else ''} for format {version}: "
                           + ", ".join(dict.fromkeys(unknown)))
        if valid and version == 0 and newer:
            refused.append(f"{where}: repository format 0, but it holds an extension that needs format 1: "
                           + ", ".join(dict.fromkeys(newer)))
        return Format(valid, on and valid, tuple(refused), tuple(lines), where,
                      hash_ if valid and version >= 1 else "sha1")

    def worktree_file_on(self, common: Path) -> bool:
        """Whether a worktree's own settings file is read: the repository's file says extensions.worktreeConfig."""
        return self.repo_format(common).on

    def settings_for(self, seed: Seed) -> Expanded:
        """What git sees in this worktree, lowest priority first, the last setting winning."""
        plan = [("system", f) for f in self.world.system] + [("global", f) for f in global_files(self.world)]
        plan.append(("local", seed.common / "config"))
        if self.worktree_file_on(seed.common):
            plan.append(("worktree", seed.git_dir / "config.worktree"))
        fmt = self.repo_format(seed.common)
        got = Expanded([], [], list(fmt.refused), [], [], [])
        for scope, path in plan:
            for mine, theirs in zip(got, self.expand(scope, path)):
                mine.extend(theirs)
        if fmt.hash != "sha256":        # values.a/F3: refused in a SHA-1 repository only
            for path, line, why in got.sha1_only:
                got.refused.append(f"{show(path)} line {line}: {why}")
                self.report(path, line, "bad-value", f"{why}; git would refuse to run in a SHA-1 repository that "
                                                     f"reads this file")
        got.refused[:] = list(dict.fromkeys(got.refused))
        got.unread[:] = list(dict.fromkeys(got.unread))
        return got

    def work_tree_state(self, seed: Seed, fmt: Format) -> tuple:
        """(what git stops on, or None, or ("bare" | "moved", the reason)): what core.bare and core.worktree make of this
        worktree. Git takes them from the repository's own file for the main worktree, and for a linked one only when
        extensions.worktreeConfig is on; then the worktree's own file overrides the repository's. With no usable
        repository format git ignores them. A git folder that shares from another through its commondir file is read
        as git reads a linked worktree's, whatever its name (D5 seed, round 3 F1)."""
        shares = os.path.normcase(os.path.normpath(seed.git_dir)) != os.path.normcase(os.path.normpath(seed.common))
        if not fmt.valid or ((seed.name is not None or shares) and not fmt.on):
            return [], None
        lines = [(k, v, ln, fmt.file) for k, v, ln in fmt.settings]
        if fmt.on:
            own, mine = self.parse(seed.git_dir / "config.worktree"), show(seed.git_dir / "config.worktree")
            lines += [(k, v, ln, mine) for k, v, ln in (own.settings if own else []) if k in ("core.bare", "core.worktree")]
        bare = next((x for x in reversed(lines) if x[0] == "core.bare"), None)
        work = next((x for x in reversed(lines) if x[0] == "core.worktree"), None)
        stops = []
        if bare and value_problem("core.bare", bare[1]):
            stops.append(f"{bare[3]} line {bare[2]}: {value_problem('core.bare', bare[1])}")
        if work and work[1] is None:
            stops.append(f"{work[3]} line {work[2]}: core.worktree has no value")
        if stops:
            return stops, None
        if bare and parse_bool(bare[1]):
            return [], ("bare", f"core.bare is on ({bare[3]} line {bare[2]}), so git takes this for a bare repository")
        if work:
            where, value = f"{work[3]} line {work[2]}", work[1]
            if value == "":
                return [f"{where}: core.worktree is empty, so git cannot go to it"], None
            target = Path(value) if git_absolute(value) else Path(os.path.normpath(seed.git_dir / value))
            if not os.path.isdir(target):            # D4: absolute or relative, a missing folder is where git stops
                return [f"{where}: core.worktree = {value!r} names {show(target)}, which is not a folder"], None
            if not same_place(target, seed.top):
                return [], ("moved", f"core.worktree ({where}) makes git use {show(target)} as the work tree, "
                                     f"not {show(seed.top)}")
        return [], None


# ---- the seats file -------------------------------------------------------------------------------------------------
def in_group(line, group: str) -> bool:
    """Whether a seat's record lists the group, as the inbox decides whom to read."""
    return isinstance(line, dict) and isinstance(line.get("groups"), list) and group in line["groups"]


def read_roots(path: str, problems: list, group: str | None = None) -> tuple:
    """(the repositories the seats file names, the seats left out): each as (root name, seat or None, folder), for each
    root of kind "repo", and for the root whose path is {home}, one for every seat that declares a home. With a group,
    only the seats listed in it are read; the others are left out, by name."""
    try:   # read one way by every reader and the card hook (pathrule.read_seats): a key twice, no roots
        data = read_seats(path)
    except SeatsUnread as e:
        problems.append(problem(path, None, "bad-json" if e.kind == "not-json" else e.kind, f"the seats file: {e}"))
        return [], []
    if not isinstance(data, dict) or not isinstance(data.get("roots"), list):
        problems.append(problem(path, None, "no-roots", "the seats file should hold a list of roots"))
        return [], []
    base = ""
    if data.get("base") is not None:   # judged as the places and inbox readers judge it (sources.base_of)
        base, why = base_of(data["base"])
        if base is None:
            problems.append(problem(path, None, "bad-path", why))
            base = ""   # no base, as the places reader then has: a root must be written in full
    seats = data["seats"] if isinstance(data.get("seats"), dict) else {}
    found, left_out, said_no_base = [], [], False
    for k, root in enumerate(data["roots"], 1):
        if isinstance(root, dict) and root.get("kind") not in (None, "repo"):    # D8: a root of another kind is not
            continue                                                            # this reader's to check
        if not isinstance(root, dict) or not isinstance(root.get("path"), str) or not root["path"].strip():
            problems.append(problem(path, k, "bad-root", f"root {k} should have a name and a path"))
        elif root.get("kind") != "repo":
            continue
        elif root["path"].strip() == "{home}":   # as the places reader reads a {home} root
            # the base the homes are joined to (pathrule.home_base, as every reader and the card hook judge it): with
            # none given, or one that is not an existing folder, no home is read, said once (a refused base is said)
            home_base_, why = home_base(data.get("base"))
            if home_base_ is None and (data.get("base") is None or base) and not said_no_base:
                problems.append(problem(path, k, "no-base", why))
                said_no_base = True   # once for the file, however many {home} roots it lists
            for seat, line in seats.items():
                if group and not in_group(line, group):
                    if seat not in left_out:
                        left_out.append(seat)
                    continue
                if home_base_ is None:
                    continue
                home = line.get("home") if isinstance(line, dict) else None
                if isinstance(home, str) and home.strip():
                    full, why = under(home_base_, home)
                    if full is None:
                        problems.append(problem(path, k, "bad-path", f"{seat}'s home: {why}"))
                    else:
                        found.append((str(root.get("name") or "home"), seat, Path(full)))
                else:
                    problems.append(problem(path, k, "no-home",
                                            f"{seat} declares no home, so has no {root.get('name')} root"))
        else:
            full, why = under(base, root["path"])   # the one join the places and inbox readers make too
            if full is None:
                problems.append(problem(path, k, "bad-path", f"root {k}: {why}"))
            else:
                found.append((str(root.get("name") or root["path"]), None, Path(full)))
    return found, left_out
