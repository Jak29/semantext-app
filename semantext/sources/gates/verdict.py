"""A worktree's gate states from the facts read about it: a total, pure function. Nothing here opens a file, and the
same facts always give the same states.

The facts are four, all read before this is asked:

    hooks_path_set     core.hooksPath names a folder (bool)
    own_folder         git's own hooks folder holds a file that could be a hook, of any name (bool); None when it was
                       not looked at, which is right only when core.hooksPath is set, as git does not look there then
    covered            for each act, in order, whether a hook for it is where git looks (a tuple of bools, not empty)
    identity_entries   the lines of .identity that name someone, 0 when there is no such file (an int, not negative)

and the states follow from them alone:

    INERT      no folder is set and git's own holds nothing: alone, whatever else is true
    UNCOVERED  some act is not covered
    VACUOUS    at least one act is covered and .identity names nobody
    ARMED      every act is covered and VACUOUS is not

A worktree can be UNCOVERED and VACUOUS at once; INERT and ARMED are always alone. Facts outside the domain above (a
wrong type, a negative count, own_folder unknown where it decides the answer) give None: no states, never a guess.
"""
from __future__ import annotations

from typing import NamedTuple

INERT, UNCOVERED, VACUOUS, ARMED = "INERT", "UNCOVERED", "VACUOUS", "ARMED"
ORDER = (INERT, UNCOVERED, VACUOUS, ARMED)   # the order the checker prints them
# An act's state in the record: a hook for it is where git looks, or none is. A token, not words for the page.
ACT_COVERED, ACT_OPEN = "gated", "open"


class Facts(NamedTuple):
    hooks_path_set: bool
    own_folder: bool | None
    covered: tuple
    identity_entries: int


def well_formed(facts) -> bool:
    """Whether the facts are in the domain the states are defined on."""
    if not isinstance(facts, tuple) or len(facts) != 4:
        return False
    hooks_path_set, own_folder, covered, entries = facts
    if type(hooks_path_set) is not bool or (own_folder is not None and type(own_folder) is not bool):
        return False
    if not isinstance(covered, tuple) or not covered or any(type(c) is not bool for c in covered):   # VD1: no acts,
        return False                                          # and "every act is covered" would be true of nothing
    if type(entries) is not int or entries < 0:
        return False
    return hooks_path_set or own_folder is not None


def states(facts) -> tuple | None:
    """The states the facts make, in the checker's order; None for facts outside the domain."""
    if not well_formed(facts):
        return None
    hooks_path_set, own_folder, covered, entries = facts
    if not hooks_path_set and not own_folder:
        return (INERT,)
    uncovered = covered.count(False)
    gated = len(covered) - uncovered
    return ((UNCOVERED,) if uncovered else ()) + (
        (VACUOUS,) if entries == 0 and gated else (ARMED,) if not uncovered else ())


def act_state(covered: bool) -> str:
    return ACT_COVERED if covered else ACT_OPEN
