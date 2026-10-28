"""Your gates: whether each repository you work in can refuse a commit or a push, read from the files git keeps.

A repository can refuse a commit or a push only if git runs a hook there, and git runs one only where its settings
point (core.hooksPath, else the repository's own hooks folder). A hook file that exists is not a gate that works. For
every worktree of every repository the seats file names, this says which of four states it is in, under the four
names the hook checker prints:

    ARMED      a hook for each act,       every act has a hook file where git looks, and .identity has a line that
               identity named             names someone. Read, not tested: no hook is run, so whether one refuses
                                          anything is never known here
    INERT      off                        no hook folder is set and git's own holds no hooks: every gate is down
    UNCOVERED  open                       some acts have no hook where git looks (listed); a hook that exists
                                          elsewhere is stranded: real, never run
    VACUOUS    checks nothing             a hook runs but .identity names nobody, so every commit and push passes

A worktree can be two at once (open and checks nothing). The acts are an ordinary commit, a merge that makes a commit,
git am and git push.

This reader deliberately differs from the hook checker on VACUOUS: here a worktree is VACUOUS only when at least one act
is gated. Where no act has a hook, nothing runs to check nothing, so the worktree is only UNCOVERED (or INERT).

A hook file counts only if git would run it. On POSIX git ignores a hook that is not executable, so a file without
the executable bit is not a hook here either (it is listed in `not_executable`). On Windows there is no such bit to
read and every file counts, as git for Windows runs it; each record says "executable bit not checked on Windows".

Every record carries `read_at`, the time (UTC) its files were read: a later edit is not in it.

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

The parts, each depending only on those before it: values (what git makes of a value, and the table of names it
checks), config (the settings files and their includes), discover (repositories, worktrees, the seats file), verdict
(the states, from facts alone), wording (the words), hooks (the hook folders, and the reader that uses them all). This
file is the loader.
"""
from __future__ import annotations

import os
import re
import sys
import types

from .. import problem
from . import config, discover, hooks, values, verdict, wording
from .config import World, show, this_machine
from .discover import find_worktrees, read_roots
from .hooks import EVENTS, Reader, read_at
from .verdict import ORDER
from .wording import ARMED_WORDS, NOT_TESTED, READ, READ_NOTE, WORDS


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

    Without the "seats" key: {"off": True, "key": "seats", ...}. Otherwise {"off": False, "read": "static", "read_at":
    when the read began (UTC), "repos":
    [{"name", "seat", "root", "present", "worktrees": [...], "counts"}], "summary", "system_config", "home", "group",
    "outside_group", "problems"}. With a "group" key only the seats in that group are read; the others are named in
    "outside_group". `world` stands in for this machine's git settings (the tests give one)."""
    path = (cfg or {}).get("seats")
    if not path:      # I4: the same keys as an answer that was read, so a caller can index either
        return {"off": True, "key": "seats", "seats": None, "read": READ, "read_note": READ_NOTE, "read_at": read_at(),
                "repos": [], "summary": counts([]), "system_config": None, "home": None, "group": None,
                "outside_group": [], "problems": []}
    problems: list = []
    group = cfg.get("group")
    # F3: a word has something in it and no blank inside it (a blank at an end is matched whole, as before)
    if group is not None and not (isinstance(group, str) and re.fullmatch(r"\s*\S+\s*", group)):
        # I2: a group that is not a word is no filter, as in the places source, and the problem says so
        problems.append(problem(path, None, "shape", f"the setting 'group' should be a word, not {group!r}, so it is "
                                                     f"no filter: every seat is read"))
        group = None
    started = read_at()
    world = world or this_machine()
    reader = Reader(world, problems)
    repos = []
    roots, left_out = read_roots(path, problems, group)
    for name, seat, folder in roots:
        out = {"name": name, "seat": seat, "root": show(folder), "present": os.path.isdir(folder), "worktrees": []}
        if out["present"]:
            try:
                seeds = find_worktrees(folder, problems)
            except (OSError, ValueError) as e:
                problems.append(problem(folder, None, "unreadable", e))
                seeds = []
            for s in seeds:               # F2: a worktree that cannot be read costs only itself, and is named
                try:
                    out["worktrees"].append(reader.record(s))
                except (OSError, ValueError) as e:
                    problems.append(problem(s.top, None, "unreadable", e))
        else:
            problems.append(problem(folder, None, "missing-root", f"the folder for {name} is not there"))
        out["counts"] = counts(out["worktrees"])
        repos.append(out)
    return {"off": False, "key": "seats", "read": READ, "read_note": READ_NOTE, "read_at": started, "seats": str(path),
            "system_config": {"file": show(world.system[-1]) if world.system else None,
                              "files": [show(f) for f in world.system], "tried": [show(t) for t in world.tried]},
            "home": show(world.home), "group": group, "outside_group": left_out, "repos": repos,
            "summary": counts([w for r in repos for w in r["worktrees"]]), "problems": problems}


# ---- compatibility shim: the names of the single gates.py, before the split of 2026-10-23 -------------------------
# tests/test_sources_gates.py and tests/test_gates_read_claims.py reach into the reader's internals by these names and
# patch some of them on this package (WINDOWS, MAX_FILE, read_at, find_worktrees, ...). The names are re-exported
# here, and a patch on the package is carried to every part that holds the name, so a patched value reaches the code
# that reads it as it did in one module. Remove this section once those tests name the parts (proposed: 2026-12-31).
from .config import (CONDITIONS, MAX_FILE, MAX_INCLUDES, MAX_VISITS, NOT_EVALUATED, SYSTEM_FILES, Cannot,  # noqa: E402,F401
                     Expanded,
                     Parsed, Setting, git_folders, global_files, install_prefix, last_setting, normalised, read_text,
                     resolved, same_place, system_candidates, system_level, user_home)
from .discover import (MAX_GITFILE, MAX_WORKTREES, Format, Seed, common_dir_of, git_dir_problem,  # noqa: E402,F401
                       head_is_valid, in_group, linked_seed, own_gitfile_problems, path_text, read_gitfile)
from .hooks import LIVE, MAX_NAMES, runnable  # noqa: E402,F401
from .values import (BAD_HEADER, BAD_LINE, BOM, C_NUMBER, C_SPACE, DISPLAY, ESCAPES, NT_PATHS, PROTECTED,  # noqa: E402,F401
                     RULES, SPACE, ULONG_BITS, UNITS, WINDOWS, WINDOWS_ONLY, Refusal, _rules, c_ulong_bits,
                     git_absolute, git_number, include_condition, parse_bool, parse_config, parse_value, section,
                     subsection, value_problem, word_in)
from .wording import BARE_NOTE, EMPTY_HOOKS_PATH, EXEC_POSIX, EXEC_WINDOWS, STRANDED  # noqa: E402,F401

_PARTS = (values, config, discover, verdict, wording, hooks)


def gone_note(seed) -> str:
    """The note on a missing worktree, from its seed (the old signature; wording.missing_note takes the two fields)."""
    return wording.missing_note(seed.gone, seed.locked)


# a name set here that only the parts held: what each part held, given back when it is deleted. Kept across a reload
# (F6): a patch entered before importlib.reload is still unwound against the records it made.
_SHADOWED: dict = globals().get("_SHADOWED", {})


class _Package(types.ModuleType):
    """This package, with a setattr that also sets the name in every part that holds it. A module's own dunders
    (__name__, __file__, __spec__, which importlib.reload sets) stay its own (I1); a name that only the parts held,
    set here and then deleted (patch.object(..., create=True)), gives each part its own value back (I6)."""

    def __setattr__(self, name, value):
        if not (name.startswith("__") and name.endswith("__")):
            if name not in vars(self) and name not in _SHADOWED:
                _SHADOWED[name] = [(part, vars(part)[name]) for part in _PARTS if name in vars(part)]
            for part in _PARTS:
                if name in vars(part):
                    setattr(part, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        super().__delattr__(name)
        for part, held in _SHADOWED.pop(name, ()):
            setattr(part, name, held)


sys.modules[__name__].__class__ = _Package
