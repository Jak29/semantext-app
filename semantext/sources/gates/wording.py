"""The words the Gates reader puts in its record about a gate: the only place they are written. Pure.

Words are chosen from two separate inputs: the verdict, and the kind of evidence behind it. This reader has one kind,
a static read of git's files (STATIC), and its words say what was read, never that a hook works: "gated",
"protected", "enforced" and the like are claims a static read cannot make (the forbidden-words test holds this file
to that). A kind of evidence that could carry such a claim, a record that a hook refused something, has no words yet,
and asking for them is an error, not a fallback to the static words.

The reasons a worktree has no answer (a setting git refuses, a file that cannot be read) are written where they are
found, beside the code that reads the file: they name what was read, not the state of a gate.
"""
from __future__ import annotations

STATIC = "static"   # the evidence kind of a read of git's files; the record names it under "read"
EVIDENCE = (STATIC,)
READ = STATIC
READ_NOTE = "a static read of git's own files: it can say a gate is reachable, never that it still refuses"
ARMED_WORDS = "a hook for each act, identity named"
WORDS = {"INERT": "off", "UNCOVERED": "open", "VACUOUS": "checks nothing", "ARMED": ARMED_WORDS}
NOT_TESTED = "read; not tested"   # how an ARMED worktree is marked wherever its words are shown: no hook was run
STRANDED = "stranded"
EXEC_POSIX = "executable bit checked: a hook file git would ignore as not executable is not counted"
EXEC_WINDOWS = "executable bit not checked on Windows"
BARE_NOTE = "a bare repository: it has no work tree, so nothing is committed here and there is no gate to read"
EMPTY_HOOKS_PATH = ("core.hooksPath is set but empty: git 2.39.1 then looks for each hook by its bare name, as "
                    "\"/pre-commit\", and not in its own hooks folder (measured: a hook there did not run); a hook at "
                    "that place is not read here, so every act is counted open")
GONE = ("folder", "gitfile", "blank", "empty")   # why a listed worktree is missing (None: its folder, as "folder")


def words(verdict: str, evidence: str) -> str:
    """The words for a verdict reached on this kind of evidence."""
    if evidence not in EVIDENCE:
        raise ValueError(f"no words are written for evidence of kind {evidence!r}")
    if verdict not in WORDS:
        raise ValueError(f"no words are written for the verdict {verdict!r}")
    return WORDS[verdict]


def executable(windows: bool) -> str:
    """What the record says about the executable bit on this platform."""
    return EXEC_WINDOWS if windows else EXEC_POSIX


def bare_note(why: str | None = None) -> str:
    return BARE_NOTE if why is None else f"{BARE_NOTE} ({why})"


def main_note(common: str) -> str:
    """The note on a main worktree whose git folder is not its own .git."""
    return f"git worktree list names this repository's git folder, {common}, as its main worktree; this names the checkout"


def missing_note(gone: str | None, locked: bool) -> str:
    """The note on a worktree the repository lists and that is not there: what is gone, and whether git would prune it.
    A `gone` it has no words for is an error, as in words() (W1), never the folder's words by default."""
    if gone is not None and gone not in GONE:
        raise ValueError(f"no words are written for a worktree gone as {gone!r}")
    if gone == "empty":
        what = "the repository's record of it names no folder"
    elif gone == "blank":
        what = "the repository's record of it starts with a blank, so it names no folder"
    elif gone == "gitfile":
        what = "the worktree's .git file is gone, though its folder is still there"
    else:
        what = "the worktree's folder is gone"
    if locked:
        return f"{what}, but it is locked, so git does not call it prunable"
    return f"{what}; git lists it as prunable"


def via_note(by: str, preferred: str) -> str:
    """The note on an act covered by a hook other than the one the checker prefers."""
    return f"via {by}; {preferred} is the preferred point"
