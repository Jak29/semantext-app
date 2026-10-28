"""The values git reads, as git reads them: numbers, a yes or no, the names whose values git checks at start-up, and
the text of a settings file. Pure: nothing here opens a file or looks at the machine beyond its platform.

The table of names (RULES) is a measured fact about one git, not a rule of git's: it was measured against
MEASURED_AGAINST, and a later git may accept or refuse other values (one behaviour noted in discover changed in git
2.48).
"""
from __future__ import annotations

import os
import re
import struct

MEASURED_AGAINST = "Git for Windows 2.39.1"
WINDOWS = os.name == "nt"
# How this machine spells a path: kept apart from WINDOWS, which the tests set by hand to read an answer as POSIX would,
# because the paths of such a test are still this machine's.
NT_PATHS = os.name == "nt"


def c_ulong_bits(size: int | None = None) -> int:
    """How wide C's unsigned long is here, from the size this Python was built with (V4: 32 bits on Windows and on a
    32-bit POSIX build, 64 on a 64-bit POSIX one), never from the platform's name alone."""
    return 8 * (struct.calcsize("L") if size is None else size)


ULONG_BITS = c_ulong_bits()             # git's unsigned long settings are as wide as the platform's
SPACE = " \t\r"          # what git skips inside a settings file, besides the line break
C_SPACE = " \t\n\v\f\r"  # what C calls white space (git trims the end of a file it reads with it)
ESCAPES = {"t": "\t", "b": "\b", "n": "\n", "\\": "\\", '"': '"'}   # the only backslash escapes git accepts in a value
BAD_LINE, BAD_HEADER = "bad config line", "bad section header"
BOM = chr(0xFEFF)       # a byte-order mark, as it shows at the start of a text that is read as UTF-8


class Refusal(Exception):
    """Git would refuse the settings file here. `extra` is how many lines past the one being read git names."""

    def __init__(self, why: str, extra: int = 0):
        super().__init__(why)
        self.extra = extra


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
    unit = value[m.end():]
    unit = unit.lower() if unit.isascii() else None     # V3: git folds ASCII only; KELVIN SIGN is no "k" to it
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
        if low not in ("", "false", "no", "off", "auto") and (n is None or not 4 <= n <= 64):
            return f"{name} = {value!r} is neither auto, a no, nor a length from 4 to 40 (64 in a SHA-256 repository)"
    elif kind == "commentchar":
        if value.lower() != "auto" and len(value.encode("utf-8", errors="replace")) != 1:
            return f"{name} = {value!r} is neither auto nor one character"
    return None


def sha1_only_problem(key: str, value: str | None) -> str | None:
    """Why git stops on this value in a SHA-1 repository only, or None: core.abbrev is held to the length of the
    repository's object names, 40 for SHA-1 and 64 for SHA-256 (measured with Git for Windows 2.39.1: 48 is refused in
    a SHA-1 repository and taken in a SHA-256 one)."""
    if key != "core.abbrev" or value is None or value_problem(key, value):
        return None
    n = git_number(value) if value.lower() not in ("", "false", "no", "off", "auto") else None
    return f"core.abbrev = {value!r} is longer than 40, which a SHA-1 repository does not take" if n and n > 40 else None


def word_in(value: str, rule: tuple) -> bool:
    return (value.lower() in rule[1]) if rule[2] else (value in rule[1])


# ---- the text of a settings file, read the way git reads it --------------------------------------------------------
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
    """Whether git takes a path as absolute: one starting with "/"; on Windows also "\\" and a drive ("C:"), which
    elsewhere are ordinary names (V2)."""
    if not NT_PATHS:
        return text[:1] == "/"
    return text[:1] in ("/", "\\") or bool(re.match(r"[A-Za-z]:", text))
