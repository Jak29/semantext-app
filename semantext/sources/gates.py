"""Your gates: whether each repository you work in can refuse a commit or a push, read from the files git keeps.

A repository can refuse a commit or a push only if git runs a hook there, and git runs one only where its settings
point (core.hooksPath, else the repository's own hooks folder). A hook file that exists is not a gate that works. For
every worktree of every repository the seats file names, this says which of four states it is in, the same four the
hook checker prints:

    ARMED      gated, identity declared   every act has a hook where git looks, and .identity names who may commit
    INERT      off                        no hook folder is set and git's own holds no hooks: every gate is down
    UNCOVERED  open                       some acts have no hook where git looks (listed); a hook that exists
                                          elsewhere is stranded: real, never run
    VACUOUS    checks nothing             a hook runs but .identity names nobody, so every commit and push passes

A worktree can be two at once (open and checks nothing). The acts are an ordinary commit, a merge that makes a commit,
git am and git push.

This is a static read and every answer says so: it never starts git or anything else. It opens the files for reading:
git's settings (the system's, yours, the repository's, and a worktree's own where the repository allows one, following
include.path), the folders that may hold hooks, and .identity. Where it cannot be sure (an include git applies only on
a condition, a variable that moves where git looks) the worktree lists the doubt in `uncertain`.

Where git itself would refuse to run, or would find another work tree than the one asked about, the worktree is
"unknown": no verdict is better than a guessed one, and the reason is in `uncertain`. Git refuses for a settings file
it cannot parse, a value it cannot read (a yes or no that is neither, a name that needs a value and has none, a
repository format or extension it does not know), an include it cannot expand, a .git file or git folder it does not
accept, and a repository that is bare. It finds another work tree when core.worktree points elsewhere. The values it
reads at start-up were measured against Git for Windows 2.39.1 (see RULES). Two refusals are not seen: a folder owned
by someone else (git's ownership check) and settings handed in by the environment. A repository whose own folder is
bare, or says it is, has no work tree and so no gate to read: its status is "bare". A line or a file the reader cannot
use is a problem in the list, never silence.
"""
from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Mapping, NamedTuple

from . import problem

READ = "static"
READ_NOTE = "a static read of git's own files: it can say a gate is reachable, never that it still refuses"
MAX_FILE = 1_000_000     # a settings file, a seats file or an .identity over this is a problem, never read
MAX_NAMES = 5_000        # entries looked at in one hook folder; a folder with more gives no answer
MAX_WORKTREES = 500      # linked worktrees looked at in one repository
MAX_INCLUDES = 10        # how deep git lets includes nest (measured: ten files deep work, eleven are refused)
MAX_VISITS = 500         # files opened while following the includes of one settings file
MAX_GITFILE = 1 << 20    # git refuses a .git file longer than this
WINDOWS = os.name == "nt"
ULONG_BITS = 32 if WINDOWS else 64      # git's unsigned long settings are as wide as the platform's

# The acts a gate must cover. An act is covered when any one of its hooks is there; they are listed best first.
EVENTS = (
    ("ordinary commit", ("pre-commit",)),
    ("git merge --no-ff", ("commit-msg",)),
    ("git am", ("applypatch-msg", "pre-applypatch")),
    ("git push", ("pre-push",)),
)
LIVE = tuple(sorted({n for _, names in EVENTS for n in names}))
ORDER = ("INERT", "UNCOVERED", "VACUOUS", "ARMED")   # the order the checker prints them
WORDS = {"INERT": "off", "UNCOVERED": "open", "VACUOUS": "checks nothing", "ARMED": "gated, identity declared"}
STRANDED = "stranded"
# Variables that change where git finds its settings. They are named, not evaluated.
NOT_EVALUATED = ("GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG", "GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")
CONDITIONS = ("gitdir:", "gitdir/i:", "onbranch:", "hasconfig:remote.*.url:")   # the includeIf kinds git knows
SPACE = " \t\r"          # what git skips inside a settings file, besides the line break
C_SPACE = " \t\n\v\f\r"  # what C calls white space (git trims the end of a file it reads with it)
ESCAPES = {"t": "\t", "b": "\b", "n": "\n", "\\": "\\", '"': '"'}   # the only backslash escapes git accepts in a value
BAD_LINE, BAD_HEADER = "bad config line", "bad section header"
BOM = chr(0xFEFF)       # a byte-order mark, as it shows at the start of a text that is read as UTF-8


class Cannot(Exception):
    """A file the checker would crash on: the worktree gets no answer, and says why."""


class Refusal(Exception):
    """Git would refuse the settings file here. `extra` is how many lines past the one being read git names."""

    def __init__(self, why: str, extra: int = 0):
        super().__init__(why)
        self.extra = extra


class Setting(NamedTuple):
    key: str
    value: str | None
    scope: str
    file: str
    line: int
    via: tuple           # the files that included this one, outermost first


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


class Format(NamedTuple):
    """What git takes from a repository's own settings file before it reads anything else (never following includes)."""
    valid: bool          # a version was given and is not negative: if not, git throws the format settings away
    on: bool             # extensions.worktreeConfig is on, so a worktree's own file is read
    refused: tuple       # why git stops at this file
    settings: tuple      # the core.bare and core.worktree lines, as (key, value, line)
    file: str


def show(path) -> str:
    return str(path).replace("\\", "/")


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


def read_text(path, problems: list, strict: bool = False) -> str | None:
    """The text of a small file, or None with a problem. Not UTF-8: refused when strict, else read with replacements."""
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
        return None if strict else raw.decode("utf-8", errors="replace")


# ---- the values git reads, as git reads them -----------------------------------------------------------------------
C_NUMBER = re.compile(r"[ \t\n\v\f\r]*([+-]?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)")
UNITS = {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30}


def git_number(value: str | None, bits: int = 32, signed: bool = True) -> int | None:
    """The number git reads from a settings value (git_parse_int, git_parse_unsigned): C's strtoimax with base 0 (a 0x
    prefix is hexadecimal, a leading 0 is octal), then nothing or one of k, m, g. None when git calls the value bad or
    too big for a number that wide."""
    if not value or (not signed and "-" in value):
        return None
    m = C_NUMBER.match(value)
    if not m:
        return None
    digits = m.group(2)
    n = int(digits, 16) if digits[:2] in ("0x", "0X") else int(digits, 8) if len(digits) > 1 and digits[0] == "0" else int(digits)
    n = -n if m.group(1) == "-" else n
    unit = value[m.end():].lower()
    if unit not in UNITS or not -(1 << 63) <= n <= (1 << 64) - 1:
        return None
    factor = UNITS[unit]
    top = (1 << (bits - 1)) - 1 if signed else (1 << bits) - 1
    if (n < 0 and -(top // factor) > n) or (n > 0 and top // factor < n):
        return None
    return n * factor


def parse_bool(value: str | None) -> bool | None:
    """A yes or no as git reads one: a key with no value is yes; None when the text is neither."""
    if value is None:
        return True
    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("", "false", "no", "off"):
        return False
    n = git_number(value)
    return None if n is None else n != 0


def _rules() -> dict:
    rules: dict = {}

    def add(kind: str, names: str, *extra) -> None:
        for name in names.split():
            rules[name] = (kind, *extra)

    # a name that needs a value: git stops when it has none
    add("text", "author.email author.name committer.email committer.name core.askpass core.checkroundtripencoding core.editor "
                "core.fsync core.fsyncmethod core.notesref core.unsetenvvars core.untrackedcache core.whitespace "
                "i18n.commitencoding i18n.logoutputencoding mailmap.blob user.email user.name "
                "trace2.configparams trace2.destinationdebug trace2.envvars trace2.eventbrief trace2.eventnesting "
                "trace2.eventtarget trace2.maxfiles trace2.normalbrief trace2.normaltarget trace2.perfbrief trace2.perftarget")
    # a path: needs a value, and ~name/ cannot be expanded (git on Windows never expands another user's home)
    add("path", "core.attributesfile core.excludesfile core.hookspath mailmap.file")
    # a yes or no
    add("bool", "advice.addembeddedrepo advice.addemptypathspec advice.addignoredfile advice.ambiguousfetchrefspec advice.amworkdir "
                "advice.checkoutambiguousremotebranchname advice.commitbeforemerge advice.detachedhead advice.fetchshowforcedupdates "
                "advice.graftfiledeprecated advice.ignoredhook advice.implicitidentity advice.nametoolong advice.nestedtag "
                "advice.objectnamewarning advice.pushalreadyexists advice.pushfetchfirst advice.pushneedsforce "
                "advice.pushnonfastforward advice.pushnonffcurrent advice.pushnonffmatching advice.pushrefneedsupdate "
                "advice.pushunqualifiedrefname advice.pushupdaterejected advice.resetnorefresh advice.resolveconflict advice.rmhints "
                "advice.sequencerinuse advice.setupstreamfailure advice.skippedcherrypicks advice.statusaheadbehindwarning "
                "advice.statushints advice.statusuoption advice.submodulealternateerrorstrategydie advice.submodulesnotupdated "
                "advice.suggestdetachinghead advice.updatesparsepath advice.usecorefsmonitorconfig advice.waitingforeditor "
                "color.pager commitgraph.readchangedpaths core.bare core.commitgraph core.filemode core.fscache core.fsyncobjectfiles "
                "core.ignorecase core.ignorestat core.longpaths core.multipackindex core.precomposeunicode core.prefersymlinkrefs "
                "core.preloadindex core.protecthfs core.protectntfs core.quotepath core.sparsecheckout core.sparsecheckoutcone "
                "core.symlinks core.trustctime core.usereplacerefs core.warnambiguousrefs feature.experimental feature.manyfiles "
                "fetch.writecommitgraph gc.writecommitgraph index.sparse pack.usesparse pager.color "
                "sparse.expectfilesoutsideofpatterns user.useconfigonly")
    # a yes or no, or one more word (the flag says whether the word's case is ignored)
    add("words+bool", "branch.autosetupmerge", ("always", "inherit", "simple"), False)
    add("words+bool", "color.advice", ("always", "never", "auto"), True)
    add("words+bool", "core.autocrlf", ("input",), True)
    add("words+bool", "core.hidedotfiles", ("dotgitonly",), True)
    add("words+bool", "core.logallrefupdates", ("always",), True)
    add("words+bool", "core.restrictinheritedhandles", ("auto",), True)
    add("words+bool", "core.safecrlf", ("warn",), True)
    # one of a few words
    add("words", "branch.autosetuprebase", ("always", "never", "local", "remote"), False)
    add("words", "core.createobject", ("rename", "link"), False)
    add("words", "core.disambiguate", ("commit", "committish", "tree", "treeish", "blob", "none"), True)
    add("words", "fetch.negotiationalgorithm", ("default", "noop", "skipping"), True)
    add("words", "push.default", ("nothing", "matching", "simple", "upstream", "tracking", "current"), False)
    # numbers
    add("int", "commitgraph.generationversion index.version", None, None)
    add("int", "core.compression core.loosecompression pack.compression", -1, 9)
    add("ulong", "core.bigfilethreshold core.deltabasecachelimit core.packedgitlimit core.packedgitwindowsize pack.packsizelimit")
    add("abbrev", "core.abbrev")
    add("commentchar", "core.commentchar")
    return rules


# What git refuses in a setting's value when it reads its default settings, measured against Git for Windows 2.39.1:
# every name found as a string in git's own program file, and every word in that file as a name in each section git's
# default settings reader handles, was written with no value, with a nonsense word and with an empty one, and git was
# asked to find its work tree (the hook checker's first step). What git refused is here, with the values it accepts.
RULES = _rules()
# Names only the system's and your own settings are read for (a repository's own file is never searched for them).
PROTECTED = frozenset("core.longpaths trace2.configparams trace2.destinationdebug trace2.envvars trace2.eventbrief "
                      "trace2.eventnesting trace2.eventtarget trace2.maxfiles trace2.normalbrief trace2.normaltarget "
                      "trace2.perfbrief trace2.perftarget".split())
WINDOWS_ONLY = frozenset("core.fscache core.hidedotfiles core.longpaths core.restrictinheritedhandles core.unsetenvvars".split())
DISPLAY = {"core.hookspath": "core.hooksPath"}


def value_problem(key: str, value: str | None, scope: str = "local") -> str | None:
    """Why git stops on this setting's value (or lack of one), or None. `key` is lower case; `scope` is where it was
    written, which matters for the few names only the system's and your own settings are read for."""
    rule = RULES.get(key)
    if rule is None or (key in WINDOWS_ONLY and not WINDOWS) or (key in PROTECTED and scope not in ("system", "global")):
        return None
    kind, name = rule[0], DISPLAY.get(key, key)
    if kind in ("text", "path", "words", "int", "ulong", "abbrev", "commentchar") and value is None:
        return f"{name} has no value"
    if kind == "path":
        if WINDOWS and value.startswith("~") and value != "~" and not value.startswith("~/"):
            return f"{name} = {value!r} names another user's home, which git cannot expand"
    elif kind in ("bool", "words+bool"):
        if parse_bool(value) is None and not (kind == "words+bool" and word_in(value, rule)):
            return f"{name} = {value!r} is not a yes or no"
    elif kind == "words":
        if not word_in(value, rule):
            return f"{name} = {value!r} is not one of {', '.join(rule[1])}"
    elif kind == "int":
        n, low, high = git_number(value), rule[1], rule[2]
        if n is None or (low is not None and not low <= n <= high):
            return f"{name} = {value!r} is not " + (f"a number from {low} to {high}" if low is not None else "a number")
    elif kind == "ulong":
        if git_number(value, ULONG_BITS, signed=False) is None:
            return f"{name} = {value!r} is not a number git can hold"
    elif kind == "abbrev":
        low = value.lower()
        n = None if low in ("", "false", "no", "off", "auto") else git_number(value)
        if low not in ("", "false", "no", "off", "auto") and (n is None or not 4 <= n <= 40):
            return f"{name} = {value!r} is neither auto, a no, nor a length from 4 to 40"
    elif kind == "commentchar":
        if value.lower() != "auto" and len(value.encode("utf-8", errors="replace")) != 1:
            return f"{name} = {value!r} is neither auto nor one character"
    return None


def word_in(value: str, rule: tuple) -> bool:
    return (value.lower() in rule[1]) if rule[2] else (value in rule[1])


# ---- git's settings files, read the way git reads them -------------------------------------------------------------
def parse_config(text: str) -> tuple:
    """The settings in a git settings file as (name, value, line), and the first thing git would refuse as
    (line, why) or None. Names are lower case except a quoted subsection; a key with no value has the value None.

    The end of the file counts as a line break, and two are added so that a backslash ending the file reads as git
    reads it. `end` is where the file really ends: a few refusals are numbered by whether a real line break or the
    end of the file ended the header, as git numbers them."""
    if text.startswith(BOM):
        text = text[1:]
    text = text.replace("\r\n", "\n")
    end = len(text)
    text += "\n\n"
    out, base, i, line = [], "", 0, 1
    try:
        while i < end:
            c = text[i]
            if c == "\n":
                line, i = line + 1, i + 1
            elif c in SPACE:
                i += 1
            elif c in "#;":
                i = text.index("\n", i)
            elif c == "[":
                base, i = section(text, i + 1, end)
            elif c.isascii() and c.isalpha():
                j = i
                while text[j].isascii() and (text[j].isalnum() or text[j] == "-"):
                    j += 1
                key, k = (base + text[i:j].lower()).split("\x00", 1)[0], j     # git's names are C strings too
                while text[k] in " \t":
                    k += 1
                if text[k] == "\n":
                    out.append((key, None, line))
                    i = k
                elif text[k] == "=":
                    value, i, extra = parse_value(text, k + 1)
                    out.append((key, value, line))
                    line += extra
                else:
                    raise Refusal(BAD_LINE)
            else:
                raise Refusal(BAD_LINE)
    except Refusal as e:
        return out, (line + e.extra, str(e))
    return out, None


def section(text: str, i: int, end: int) -> tuple:
    """A section header after its '[': ("name.", next index) for [name], or ("name.sub.", next index) for [name "sub"]."""
    name = []
    while True:
        c = text[i]
        i += 1
        if c == "]":
            if not name:
                raise Refusal(BAD_HEADER)
            return "".join(name) + ".", i
        if c in " \t\r\n":
            if c == "\n" and i - 1 >= end:
                raise Refusal(BAD_HEADER, 1)          # the file ends inside the header, which git numbers one line on
            return subsection("".join(name), text, i - 1)
        if not (c.isascii() and (c.isalnum() or c in "-.")):
            raise Refusal(BAD_HEADER)
        name.append(c.lower())


def subsection(name: str, text: str, i: int) -> tuple:
    """The rest of a header written [name "sub"], from the blank that ended the name."""
    while text[i] in " \t\r\n":
        if text[i] == "\n":
            raise Refusal(BAD_HEADER)                 # a line break before the quote
        i += 1
    if text[i] != '"':
        raise Refusal(BAD_HEADER)
    sub, i = [], i + 1
    while True:
        c = text[i]
        i += 1
        if c == "\n":
            raise Refusal(BAD_HEADER)
        if c == '"':
            break
        if c == "\\":
            c = text[i]
            i += 1
            if c == "\n":
                raise Refusal(BAD_HEADER)
        sub.append(c)
    if text[i] != "]":
        raise Refusal(BAD_HEADER, 1 if text[i] == "\n" else 0)   # git has already counted the line break it stopped at
    return f"{name}.{''.join(sub)}.", i + 1


def parse_value(text: str, i: int) -> tuple:
    """A value after its '=': (value, index of its line break, extra lines it spans). A refusal says how many lines it
    had spanned. The value ends at the first NUL, as a C string does."""
    out, quote, comment, space, extra = [], False, False, 0, 0
    while True:
        c = text[i]
        i += 1
        if c == "\n":
            if quote:
                raise Refusal(BAD_LINE, extra)
            return "".join(out).split("\x00", 1)[0], i - 1, extra
        if comment:
            continue
        if c in SPACE and not quote:
            space += 1 if out else 0
            continue
        if c in "#;" and not quote:
            comment = True
            continue
        if space:
            out.append(" " * space)
            space = 0
        if c == "\\":
            c = text[i]
            i += 1
            if c == "\n":
                extra += 1            # a backslash at the end of a line joins the next one
                continue
            c = ESCAPES.get(c)
            if c is None:
                raise Refusal(BAD_LINE, extra)
        elif c == '"':
            quote = not quote
            continue
        out.append(c)


def include_condition(key: str) -> str | None:
    """None for a setting that is not an include; "" for include.path; else the condition of an includeIf."""
    if key == "include.path":
        return ""
    if key.startswith("includeif.") and key.endswith(".path") and len(key) > len("includeif..path"):
        return key[len("includeif."):-len(".path")]
    return None


def git_absolute(text: str) -> bool:
    return text[:1] in ("/", "\\") or bool(re.match(r"[A-Za-z]:", text))


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
        out.append(top.parent / "etc" / "gitconfig" if top.name.lower().startswith("mingw") else top / "mingw64" / "etc" / "gitconfig")
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        if env.get(var):
            out.append(Path(env[var]) / "Git" / "etc" / "gitconfig")
    if env.get("LOCALAPPDATA"):
        out.append(Path(env["LOCALAPPDATA"]) / "Programs" / "Git" / "etc" / "gitconfig")
    out += [Path("/etc/gitconfig"), Path("/usr/local/etc/gitconfig"), Path("/opt/homebrew/etc/gitconfig")]
    return list(dict.fromkeys(out))


def install_prefix(env: Mapping) -> Path | None:
    """What "%(prefix)/" in a path setting stands for: the folder above the bin folder the real git program runs from.
    Git for Windows runs it from <install>/mingw64/bin (the git in <install>/cmd hands over to it); elsewhere it is
    the folder above bin. None when no git program is on the path."""
    for folder in git_folders(env):
        top = folder.parent
        if folder.name.lower() == "cmd":
            for sub in ("mingw64", "mingw32"):
                if any((top / sub / "bin" / n).is_file() for n in ("git.exe", "git")):
                    return top / sub
            return top
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


# ---- what makes a folder a git folder, and a .git file a good one --------------------------------------------------
def head_is_valid(raw: bytes) -> bool:
    """Whether a HEAD file reads as git needs: "ref:", blanks, then a name under refs/; or an object name (forty hex)."""
    raw = raw[:256]
    if raw.startswith(b"ref:"):
        return raw[4:].lstrip(b" \t\n\v\f\r").startswith(b"refs/")
    return re.match(rb"[0-9a-fA-F]{40}", raw) is not None


def common_dir_of(git_dir: Path) -> Path:
    """The folder a git folder shares its objects and refs from: the one its commondir file names, else itself."""
    path = git_dir / "commondir"
    if not os.path.isfile(path):
        return git_dir
    try:
        text = path.read_bytes().decode("utf-8", errors="replace").rstrip(C_SPACE)
    except OSError:
        return git_dir
    return Path(text) if git_absolute(text) else Path(os.path.normpath(git_dir / text))


def git_dir_problem(path: Path) -> str | None:
    """Why git does not take this folder for a git folder, or None: it needs a HEAD that reads right and, in the folder
    it shares with (its own, unless it has a commondir file), the objects and refs folders."""
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
    text = raw[8:end].split(b"\0", 1)[0].decode("utf-8", errors="replace")    # a C string ends at the first NUL
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
    text = read_text(gd, problems)
    if text is None:
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


def find_worktrees(root: Path, problems: list) -> list:
    """The main worktree of the repository at root and each linked one, as git lists them: from the folder the
    repository keeps for each linked worktree (<common>/worktrees/<name>/gitdir names that worktree's .git file). A
    bare repository's own folder is its main worktree, which has no work tree to read."""
    dot = root / ".git"
    seeds: list = []
    if os.path.isdir(dot):
        git_dir = common = dot
        why = git_dir_problem(dot)
        seeds.append(Seed(root, common, common, None, True, False,
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
        if main_top is None:
            problems.append(problem(common, None, "no-main-worktree", "the repository's own folder is not named .git"))
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


def gone_note(seed: Seed) -> str:
    if seed.gone == "empty":
        what = "the repository's record of it names no folder"
    elif seed.gone == "blank":
        what = "the repository's record of it starts with a blank, so it names no folder"
    elif seed.gone == "gitfile":
        what = "the worktree's .git file is gone, though its folder is still there"
    else:
        what = "the worktree's folder is gone"
    if seed.locked:
        return f"{what}, but it is locked, so git does not call it prunable"
    return f"{what}; git lists it as prunable"


# ---- one repository's worktrees, judged ----------------------------------------------------------------------------
def last_setting(settings: list, key: str) -> Setting | None:
    return next((s for s in reversed(settings) if s.key == key), None)


class Reader:
    """Reads the files once and answers for each worktree. Holds what was already parsed, so a settings file shared by
    every worktree is opened once and its problems are reported once."""

    def __init__(self, world: World, problems: list):
        self.world, self.problems = world, problems
        self._parsed, self._expanded, self._said, self._might, self._format = {}, {}, set(), {}, {}

    def report(self, path, line, kind: str, text: str) -> None:
        """A problem, once: the same include or setting is met again by every worktree that reads the file."""
        key = (os.path.normcase(str(path)), line, kind, text)
        if key not in self._said:
            self._said.add(key)
            self.problems.append(problem(path, line, kind, text))

    # -- settings files
    def parse(self, path: Path) -> Parsed | None:
        """The settings of a settings file, or None when there is no such file (git skips it)."""
        key = os.path.normcase(os.path.abspath(path))
        if key not in self._parsed:
            got = None
            if os.path.isfile(path):
                text = read_text(path, self.problems)
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

    def might_set_hooks(self, path: Path | None, seen: tuple = ()) -> bool:
        """Whether a file git might include on a condition could change the answer: set core.hooksPath or hold a value
        git stops on; looking through its own includes. Each file is looked through once, however many includes name it."""
        if path is None or len(seen) > MAX_INCLUDES:
            return True
        key = os.path.normcase(os.path.abspath(path))
        if key not in self._might:
            self._might[key] = self._could_set_hooks(path, seen)
        return self._might[key]

    def _could_set_hooks(self, path: Path, seen: tuple) -> bool:
        got = self.parse(path)
        if got is None:
            return os.path.exists(path)               # not there: skipped. A folder is no file: git stops on it
        if got.error or got.unread:
            return True
        for key, value, _ in got.settings:
            if key == "core.hookspath" or value_problem(key, value, "global"):
                return True
            if include_condition(key) is not None:
                target = self.include_target(value, path)[0] if value is not None else None
                if target is None or os.path.normcase(str(target)) in seen or \
                        self.might_set_hooks(target, (*seen, os.path.normcase(str(path)))):
                    return True
        return False

    def expand(self, scope: str, path: Path) -> Expanded:
        """One settings file with each include replaced by what it brings in (see Expanded)."""
        key = (scope, os.path.normcase(os.path.abspath(path)))
        if key not in self._expanded:
            out = Expanded([], [], [], [], [])
            self._walk(scope, Path(path), (), out, [0])
            self._expanded[key] = out
        return self._expanded[key]

    def refuse(self, out: Expanded, path, line: int, kind: str, text: str) -> None:
        """Something git would refuse to run with: said in the worktree's doubts and once in the problems."""
        out.refused.append(f"{show(path)} line {line}: {text}")
        self.report(path, line, kind, f"{text}; git would refuse to run in any repository that reads this file")

    def _walk(self, scope: str, path: Path, via: tuple, out: Expanded, visits: list) -> None:
        got = self.parse(path)
        if got is None:
            return
        here = show(path)
        out.files.append({"scope": scope, "file": here, "included_by": via[-1] if via else None})
        if got.unread:
            out.unread.append(f"{here} {got.unread}")
            return
        for key, value, line in got.settings:
            out.settings.append(Setting(key, value, scope, here, line, via))
            cond = include_condition(key)
            if cond is None:
                why = value_problem(key, value, scope)
                if why:
                    self.refuse(out, path, line, "bad-value", why)
                continue
            where = f"{here} line {line}"
            target, cannot = self.include_target(value, path) if value is not None else (None, None)
            if cond:
                if cond.startswith(CONDITIONS):          # a kind git applies on a condition; any other it never applies
                    unevaluated = f'{where}: includeIf "{cond}" is not evaluated'
                    if self.might_set_hooks(target):
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
                chain = [os.path.normcase(v) for v in (*via, here)]
                visits[0] += 1
                if not os.path.isfile(target):
                    self.refuse(out, path, line, "bad-include", f"includes {show(target)}, which is not a file")
                elif os.path.normcase(show(target)) in chain:
                    self.refuse(out, path, line, "bad-include", "includes a file that includes it back")
                elif len(via) + 1 > MAX_INCLUDES:
                    self.refuse(out, path, line, "bad-include", f"includes go deeper than git allows ({MAX_INCLUDES})")
                elif visits[0] > MAX_VISITS:
                    out.unread.append(f"{where}: more than {MAX_VISITS} includes; the rest are not followed")
                else:
                    self._walk(scope, target, (*via, here), out, visits)
        if got.error:
            out.refused.append(f"{here} line {got.error[0]}: {got.error[1]}")

    # -- what git takes from the repository's own file before anything else
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
        unknown, newer = [], []
        for ext, value, line in extensions:
            here = f"{where} line {line}: extensions.{ext}"
            if ext in ("preciousobjects", "worktreeconfig"):
                said = parse_bool(value)
                if said is None:
                    refused.append(f"{here} = {value!r} is not a yes or no")
                elif ext == "worktreeconfig":
                    on = said
            elif ext == "partialclone":
                if value is None:
                    refused.append(f"{here} has no value")
            elif ext == "objectformat":
                newer.append(ext)
                if value not in ("sha1", "sha256"):
                    refused.append(f"{here} " + ("has no value" if value is None else f"= {value!r} is not a hash git knows"))
            elif ext == "noop-v1":
                newer.append(ext)
            elif ext != "noop":
                unknown.append(ext)
        valid = version is not None and version >= 0
        if valid and version > 1:
            refused.append(f"{where}: this git reads repository format 1 at most, and this is format {version}")
        if valid and version >= 1 and unknown:
            refused.append(f"{where}: unknown repository extension{'s' if len(unknown) > 1 else ''} for format {version}: "
                           + ", ".join(dict.fromkeys(unknown)))
        if valid and version == 0 and newer:
            refused.append(f"{where}: repository format 0, but it holds an extension that needs format 1: "
                           + ", ".join(dict.fromkeys(newer)))
        return Format(valid, on and valid, tuple(refused), tuple(lines), where)

    def worktree_file_on(self, common: Path) -> bool:
        """Whether a worktree's own settings file is read: the repository's file says extensions.worktreeConfig."""
        return self.repo_format(common).on

    def settings_for(self, seed: Seed) -> Expanded:
        """What git sees in this worktree, lowest priority first, the last setting winning."""
        plan = [("system", f) for f in self.world.system] + [("global", f) for f in global_files(self.world)]
        plan.append(("local", seed.common / "config"))
        if self.worktree_file_on(seed.common):
            plan.append(("worktree", seed.git_dir / "config.worktree"))
        got = Expanded([], [], list(self.repo_format(seed.common).refused), [], [])
        for scope, path in plan:
            for mine, theirs in zip(got, self.expand(scope, path)):
                mine.extend(theirs)
        got.refused[:] = list(dict.fromkeys(got.refused))
        got.unread[:] = list(dict.fromkeys(got.unread))
        return got

    def work_tree_state(self, seed: Seed, fmt: Format) -> tuple:
        """(what git stops on, or None, or ("bare" | "moved", the reason)): what core.bare and core.worktree make of this
        worktree. Git takes them from the repository's own file for the main worktree, and for a linked one only when
        extensions.worktreeConfig is on; then the worktree's own file overrides the repository's. With no usable
        repository format git ignores them."""
        if not fmt.valid or (seed.name is not None and not fmt.on):
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
            if not git_absolute(value) and not os.path.isdir(target):
                return [f"{where}: core.worktree = {value!r} names {show(target)}, which is not a folder"], None
            if not same_place(target, seed.top):
                return [], ("moved", f"core.worktree ({where}) makes git use {show(target)} as the work tree, "
                                     f"not {show(seed.top)}")
        return [], None

    # -- a worktree
    def record(self, seed: Seed) -> dict:
        rec = {"path": show(seed.top) if seed.shown is None else seed.shown, "name": seed.name, "main": seed.name is None,
               "exists": seed.exists, "locked": seed.locked, "git_dir": show(seed.git_dir), "common_dir": show(seed.common),
               "status": "read", "read": READ, "set": [], "words": [], "verdicts": [], "events": [],
               "hooks_path": None, "hooks_dir": None, "reachable": [], "identity": None, "files": [],
               "uncertain": [], "note": None}
        if seed.name is None and not seed.bare and \
                os.path.normcase(os.path.normpath(seed.common)) != os.path.normcase(os.path.normpath(seed.top / ".git")):
            rec["note"] = (f"git worktree list names this repository's git folder, {show(seed.common)}, as its main worktree; "
                           f"this names the checkout")
        if seed.bare:
            rec["status"], rec["note"] = "bare", BARE_NOTE
            return rec
        if not seed.exists:
            rec["status"], rec["note"] = "missing", gone_note(seed)
            return rec
        if seed.refuses or seed.unsure:
            self.unknown(rec, *(f"git would not run here as this worktree: {why}" for why in seed.refuses),
                         *(f"cannot tell: {why}" for why in seed.unsure))
            return rec
        try:
            self.read(seed, rec)
        except Cannot as e:
            self.unknown(rec, str(e))
        except Exception as e:    # a surprise in one worktree is not a verdict, and never costs the others theirs
            self.unknown(rec, f"unexpected {type(e).__name__}: {e}")
            self.problems.append(problem(seed.top, None, "unexpected", f"{type(e).__name__}: {e}"))
        return rec

    @staticmethod
    def unknown(rec: dict, *why: str) -> None:
        """No answer for this worktree. Nothing that was half worked out is kept (no verdict, hooks setting, folder,
        hook list or identity): only why, and the doubts about the files that were read."""
        rec.update(status="unknown", set=[], words=[], verdicts=[], events=[], hooks_path=None, hooks_dir=None, reachable=[],
                   identity=None)
        rec["uncertain"] = [*why, *(u for u in rec["uncertain"] if u not in why)]

    def read(self, seed: Seed, rec: dict) -> None:
        fmt = self.repo_format(seed.common)
        got = self.settings_for(seed)
        rec["files"] = [dict(f) for f in got.files]        # copies: every worktree reports the shared files as its own
        doubts = rec["uncertain"] = [*self.world.notes, *got.notes]     # the same list: judge adds what it finds
        stops, state = (list(got.refused), None) if got.refused else self.work_tree_state(seed, fmt)
        if state and state[0] == "bare" and seed.name is not None:      # a linked worktree has no bare state: git stops
            stops, state = [state[1]], None
        if stops or got.unread or (state and state[0] == "moved"):
            self.unknown(rec, *(f"git would refuse to run here: {b}" for b in stops),
                         *([f"git would use another work tree here: {state[1]}"] if state and state[0] == "moved" else []),
                         *(f"cannot tell: {u}" for u in got.unread))
            return
        if state:
            rec["status"], rec["note"] = "bare", f"{BARE_NOTE} ({state[1]})"
            return
        try:
            self.judge(seed, got.settings, rec, doubts)
        except Exception:
            rec["uncertain"] = doubts[:len(self.world.notes) + len(got.notes)]       # what judge noted is half worked out
            raise

    def names_in(self, folder: Path, notes: list, cache: dict) -> set:
        """The files in a folder that could be hooks: every file whose name does not end in .sample."""
        key = os.path.normcase(str(folder))
        if key not in cache:
            names = set()
            if os.path.isdir(folder):
                try:
                    with os.scandir(folder) as found:
                        for seen, entry in enumerate(found, 1):
                            if seen > MAX_NAMES:
                                raise Cannot(f"cannot tell: {show(folder)} holds more than {MAX_NAMES} entries, more than this "
                                             f"reader lists, so it cannot say which are hooks")
                            if not entry.name.endswith(".sample") and entry.is_file():
                                names.add(entry.name)
                except OSError as e:
                    raise Cannot(f"{show(folder)} could not be listed ({e}), so the checker has no answer here")
            cache[key] = names
        return cache[key]

    def identity_entries(self, top: Path, notes: list) -> tuple:
        """(present, how many entries): the lines of .identity that are not blank and not comments."""
        path = top / ".identity"
        if not os.path.isfile(path):
            return False, 0
        text = read_text(path, self.problems, strict=True)
        if text is None:
            raise Cannot(f"{show(path)} could not be read, so the checker has no answer here")
        if text.startswith(BOM):
            notes.append(f"{show(path)} starts with a byte-order mark; the checker counts that first line even if it is a "
                         f"comment")
        return True, len([ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")])

    def judge(self, seed: Seed, settings: list, rec: dict, notes: list) -> None:
        top, common, cache = seed.top, resolved(seed.common), {}
        hooks = last_setting(settings, "core.hookspath")
        hp = (hooks.value or "").strip() if hooks else ""
        rec["hooks_path"] = {"set": bool(hp), "value": hp or None, "scope": hooks.scope if hooks else None,
                             "file": hooks.file if hooks else None, "line": hooks.line if hooks else None,
                             "via": list(hooks.via) if hooks else []}
        if hp.startswith("~") or hp.startswith("%(prefix)/"):
            notes.append(f"core.hooksPath {hp!r} starts with {'~' if hp.startswith('~') else '%(prefix)/'}: git expands it, "
                         f"the checker does not, and this follows the checker")
        default_dir = common / "hooks"
        named = Path(hp) if hp else None
        run_dir = (named if named.is_absolute() else top / named) if named else default_dir
        rec["hooks_dir"] = show(run_dir)
        present = self.names_in(run_dir, notes, cache)
        rec["reachable"] = sorted(present & set(LIVE))

        uncovered, missing = [], set()
        for event, names in EVENTS:
            hit = [n for n in names if n in present]
            row = {"event": event, "state": "gated" if hit else "open", "by": hit[0] if hit else None,
                   "preferred": names[0], "needs": None if hit else list(names), "note": None}
            if hit and hit[0] != names[0]:
                row["note"] = f"via {hit[0]}; {names[0]} is the preferred point"
            if not hit:
                uncovered.append(event)
                missing.update(names)
            rec["events"].append(row)
        gated = len(EVENTS) - len(uncovered)

        elsewhere = {}                  # only for acts that are open: a name a better sibling replaces is not stranded
        for cand in (top / "hooks", top / "chain", default_dir):
            if resolved(cand) != resolved(run_dir):
                for name in self.names_in(cand, notes, cache) & missing:
                    elsewhere.setdefault(name, []).append(show(cand))
        present_identity, entries = self.identity_entries(top, notes)
        rec["identity"] = {"file": show(top / ".identity"), "present": present_identity, "entries": entries}

        if not hp and not self.names_in(default_dir, notes, cache):
            found = ["INERT"]
        else:
            found = (["UNCOVERED"] if uncovered else []) + (
                ["VACUOUS"] if entries == 0 and gated else ["ARMED"] if not uncovered else [])
        for verdict in found:
            item = {"verdict": verdict, "words": WORDS[verdict], "read": READ}
            if verdict == "UNCOVERED":
                item["open"] = uncovered
                item["none_gated"] = gated == 0
                item["stranded"] = [{"name": n, "words": STRANDED, "where": w} for n, w in sorted(elsewhere.items())]
            rec["verdicts"].append(item)
        rec["set"] = found
        rec["words"] = [WORDS[v] for v in found]


BARE_NOTE = "a bare repository: it has no work tree, so nothing is committed here and there is no gate to read"


# ---- the seats file, and the answer ---------------------------------------------------------------------------------
def place(base: str, path: str) -> Path:
    return Path(base) / path if base else Path(path)


def in_group(line, group: str) -> bool:
    """Whether a seat's record lists the group, as the inbox decides whom to read."""
    return isinstance(line, dict) and isinstance(line.get("groups"), list) and group in line["groups"]


def read_roots(path: str, problems: list, group: str | None = None) -> tuple:
    """(the repositories the seats file names, the seats left out): each as (root name, seat or None, folder), for each
    root of kind "repo", and for the root whose path is {home}, one for every seat that declares a home. With a group,
    only the seats listed in it are read; the others are left out, by name."""
    text = read_text(Path(path), problems)
    if text is None:
        return [], []
    try:
        data = json.loads(text.lstrip(BOM))
    except ValueError as e:
        problems.append(problem(path, None, "bad-json", e))
        return [], []
    if not isinstance(data, dict) or not isinstance(data.get("roots"), list):
        problems.append(problem(path, None, "no-roots", "the seats file should hold a list of roots"))
        return [], []
    base = data["base"] if isinstance(data.get("base"), str) else ""
    seats = data["seats"] if isinstance(data.get("seats"), dict) else {}
    found, left_out = [], []
    for k, root in enumerate(data["roots"], 1):
        if not isinstance(root, dict) or not isinstance(root.get("path"), str) or not root["path"].strip():
            problems.append(problem(path, k, "bad-root", f"root {k} should have a name and a path"))
        elif root.get("kind") != "repo":
            continue
        elif root["path"] == "{home}":
            for seat, line in seats.items():
                if group and not in_group(line, group):
                    if seat not in left_out:
                        left_out.append(seat)
                    continue
                home = line.get("home") if isinstance(line, dict) else None
                if isinstance(home, str) and home.strip():
                    found.append((str(root.get("name") or "home"), seat, place(base, home)))
                else:
                    problems.append(problem(path, k, "no-home",
                                            f"{seat} declares no home, so has no {root.get('name')} root"))
        else:
            found.append((str(root.get("name") or root["path"]), None, place(base, root["path"])))
    return found, left_out


def counts(worktrees: list) -> dict:
    out = {"worktrees": len(worktrees), **{v: 0 for v in ORDER}, "unknown": 0, "missing": 0, "bare": 0, "uncertain": 0}
    for w in worktrees:
        for v in w["set"]:
            out[v] += 1
        out["unknown"] += w["status"] == "unknown"
        out["missing"] += w["status"] == "missing"
        out["bare"] += w["status"] == "bare"
        out["uncertain"] += bool(w["uncertain"])
    return out


def load(cfg: dict, world: World | None = None) -> dict:
    """The Gates drawer: every repository the seats file names, with the gate state of each of its worktrees.

    Without the "seats" key: {"off": True, "key": "seats", ...}. Otherwise {"off": False, "read": "static", "repos":
    [{"name", "seat", "root", "present", "worktrees": [...], "counts"}], "summary", "system_config", "home", "group",
    "outside_group", "problems"}. With a "group" key only the seats in that group are read; the others are named in
    "outside_group". `world` stands in for this machine's git settings (the tests give one)."""
    path = (cfg or {}).get("seats")
    if not path:
        return {"off": True, "key": "seats", "read": READ, "repos": [], "summary": counts([]), "problems": []}
    group = cfg.get("group") if isinstance(cfg.get("group"), str) and cfg.get("group") else None
    problems: list = []
    world = world or this_machine()
    reader = Reader(world, problems)
    repos = []
    roots, left_out = read_roots(path, problems, group)
    for name, seat, folder in roots:
        out = {"name": name, "seat": seat, "root": show(folder), "present": os.path.isdir(folder), "worktrees": []}
        if out["present"]:
            try:
                out["worktrees"] = [reader.record(s) for s in find_worktrees(folder, problems)]
            except (OSError, ValueError) as e:
                problems.append(problem(folder, None, "unreadable", e))
        else:
            problems.append(problem(folder, None, "missing-root", f"the folder for {name} is not there"))
        out["counts"] = counts(out["worktrees"])
        repos.append(out)
    return {"off": False, "read": READ, "read_note": READ_NOTE, "seats": str(path),
            "system_config": {"file": show(world.system[-1]) if world.system else None,
                              "files": [show(f) for f in world.system], "tried": [show(t) for t in world.tried]},
            "home": show(world.home), "group": group, "outside_group": left_out, "repos": repos,
            "summary": counts([w for r in repos for w in r["worktrees"]]), "problems": problems}
