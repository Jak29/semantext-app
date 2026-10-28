"""The hooks of a worktree: which folder git runs them from, which acts have one there, which files git would not run
as not executable, the hooks stranded where git never looks, and .identity. The reader that puts one worktree's
record together lives here too: it reads these facts, hands them to verdict for the states and to wording for the
words.

It opens files and lists folders for reading; it never runs a hook, git or anything else.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .. import problem
from .config import Cannot, last_setting, read_text, resolved, show
from .discover import Format, RepositoryReader, Seed
from .values import BOM, WINDOWS
from .verdict import UNCOVERED, Facts, act_state, states
from .wording import EMPTY_HOOKS_PATH, STATIC, STRANDED, bare_note, executable, main_note, missing_note, via_note, words

MAX_NAMES = 5_000        # entries looked at in one hook folder; a folder with more gives no answer

# The acts a gate must cover. An act is covered when any one of its hooks is there; they are listed best first.
EVENTS = (
    ("ordinary commit", ("pre-commit",)),
    ("git merge --no-ff", ("commit-msg",)),
    ("git am", ("applypatch-msg", "pre-applypatch")),
    ("git push", ("pre-push",)),
)
LIVE = tuple(sorted({n for _, names in EVENTS for n in names}))


class Unlisted(Cannot):
    """A folder that could not be listed. `why` says so in a few words, for a note that is not the verdict's (F4)."""

    def __init__(self, text: str, why: str):
        super().__init__(text)
        self.why = why


def runnable(path: str) -> bool:
    """Whether git would run this hook file: on POSIX only when it is executable; on Windows always, as there is no
    bit to read (the record says so)."""
    return WINDOWS or os.access(path, os.X_OK)


def read_at() -> str:
    """Now, in UTC, to the second: when a record's files were read."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Reader(RepositoryReader):
    """Reads the files once and answers for each worktree. Holds what was already parsed, so a settings file shared by
    every worktree is opened once and its problems are reported once."""

    def record(self, seed: Seed) -> dict:
        rec = {"path": show(seed.top) if seed.shown is None else seed.shown, "name": seed.name, "main": seed.name is None,
               "exists": seed.exists, "locked": seed.locked, "git_dir": show(seed.git_dir), "common_dir": show(seed.common),
               "status": "read", "read": STATIC, "set": [], "words": [], "verdicts": [], "events": [],
               "hooks_path": None, "hooks_dir": None, "reachable": [], "identity": None, "files": [],
               "uncertain": [], "note": None, "read_at": read_at(), "tested": False,
               "executable": executable(WINDOWS), "not_executable": []}
        if seed.name is None and not seed.bare and \
                os.path.normcase(os.path.normpath(seed.common)) != os.path.normcase(os.path.normpath(seed.top / ".git")):
            rec["note"] = main_note(show(seed.common))
        if seed.bare:
            rec["status"], rec["note"] = "bare", bare_note()
            return rec
        if not seed.exists:
            rec["status"], rec["note"] = "missing", missing_note(seed.gone, seed.locked)
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
                   identity=None, not_executable=[])
        rec["uncertain"] = [*why, *(u for u in rec["uncertain"] if u not in why)]

    def read(self, seed: Seed, rec: dict) -> None:
        fmt: Format = self.repo_format(seed.common)
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
            rec["status"], rec["note"] = "bare", bare_note(state[1])
            return
        self.judge(seed, got.settings, rec, doubts)   # what judge notes is about files it read: kept if it then fails (H6)

    def names_in(self, folder: Path, notes: list, cache: dict) -> set:
        """The files in a folder that could be hooks: every file whose name does not end in .sample and, on POSIX, that
        is executable (git ignores one that is not). The files left out for want of the bit are kept beside, under
        (key, "not executable")."""
        key = os.path.normcase(str(folder))
        if key not in cache:
            names, idle = set(), set()
            if os.path.isdir(folder):
                try:
                    with os.scandir(folder) as found:
                        for seen, entry in enumerate(found, 1):
                            if seen > MAX_NAMES:
                                raise Unlisted(f"cannot tell: {show(folder)} holds more than {MAX_NAMES} entries, more than "
                                               f"this reader lists, so it cannot say which are hooks",
                                               f"it holds more than {MAX_NAMES} entries, more than this reader lists")
                            if not entry.name.endswith(".sample") and entry.is_file():
                                (names if runnable(entry.path) else idle).add(entry.name)
                except FileNotFoundError:
                    pass      # not there after all (Windows takes "x\\ " for "x"): no hook in it, as git finds none
                except OSError as e:
                    raise Unlisted(f"{show(folder)} could not be listed ({e}), so the checker has no answer here",
                                   f"it could not be listed ({e})")
            cache[key], cache[(key, "not executable")] = names, idle
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
        # The value as git has it: the settings parser already dropped what git drops, so a quoted blank is kept (F6)
        hp = (hooks.value or "") if hooks else ""
        # An empty core.hooksPath is still set (H3): git 2.39.1 then puts each hook's bare name where the folder would
        # be, so it looks for "/pre-commit" and never in git's own hooks folder; measured, a hook there did not run.
        # The reader takes that as no hook folder at all: every act is open, and git's own folder holds only strays.
        is_set = hooks is not None
        rec["hooks_path"] = {"set": is_set, "value": hp if is_set else None, "scope": hooks.scope if hooks else None,
                             "file": hooks.file if hooks else None, "line": hooks.line if hooks else None,
                             "via": list(hooks.via) if hooks else []}
        # C10: a byte that is not UTF-8 was replaced, so the folder it names is not known. Only in a file read with
        # replacements: a U+FFFD written as UTF-8 is a name like any other (F3)
        if "�" in hp and self._lossy_setting(hooks):
            raise Cannot(f"core.hooksPath {hp!r} holds bytes that are not UTF-8 ({hooks.file} line {hooks.line}), so the "
                         f"folder it names cannot be told")
        if hp.startswith("~") or hp.startswith("%(prefix)/"):
            notes.append(f"core.hooksPath {hp!r} starts with {'~' if hp.startswith('~') else '%(prefix)/'}: git expands it, "
                         f"the checker does not, and this follows the checker")
        default_dir = common / "hooks"
        named = Path(hp) if hp else None
        run_dir = (named if named.is_absolute() else top / named) if named else None if is_set else default_dir
        if run_dir is None:            # its note is written once the record is read whole (F1: never on an unknown)
            rec["hooks_dir"], present = None, set()
        else:
            rec["hooks_dir"] = show(run_dir)
            present = self.names_in(run_dir, notes, cache)
            rec["not_executable"] = sorted(cache[(os.path.normcase(str(run_dir)), "not executable")] & set(LIVE))
        rec["reachable"] = sorted(present & set(LIVE))

        hits = [[n for n in names if n in present] for _, names in EVENTS]
        uncovered, missing = [], set()
        for (event, names), hit in zip(EVENTS, hits):
            rec["events"].append({"event": event, "state": act_state(bool(hit)), "by": hit[0] if hit else None,
                                  "preferred": names[0], "needs": None if hit else list(names),
                                  "note": via_note(hit[0], names[0]) if hit and hit[0] != names[0] else None})
            if not hit:
                uncovered.append(event)
                missing.update(names)
        gated = len(EVENTS) - len(uncovered)

        elsewhere = {}                  # only for acts that are open: a name a better sibling replaces is not stranded
        for cand in (top / "hooks", top / "chain", default_dir) if missing else ():   # F5: none open, none stranded
            if run_dir is None or resolved(cand) != resolved(run_dir):
                try:
                    stray = self.names_in(cand, notes, cache) & missing
                except Cannot as e:     # H1: the strays are a note on the verdict, never a fact it rests on
                    notes.append(f"stranded hooks in {show(cand)} are not listed: {getattr(e, 'why', e)}")
                    continue
                for name in stray:
                    elsewhere.setdefault(name, []).append(show(cand))
        present_identity, entries = self.identity_entries(top, notes)
        rec["identity"] = {"file": show(top / ".identity"), "present": present_identity, "entries": entries}

        # git's own folder is looked at only when no folder is set, as git looks there only then
        own = None if is_set else bool(self.names_in(default_dir, notes, cache))
        found = states(Facts(is_set, own, tuple(bool(h) for h in hits), entries))
        if found is None:
            raise Cannot("the facts read about this worktree do not make a verdict")
        for v in found:
            item = {"verdict": v, "words": words(v, STATIC), "read": STATIC, "tested": False}
            if v == UNCOVERED:
                item["open"] = uncovered
                item["none_gated"] = gated == 0
                item["stranded"] = [{"name": n, "words": STRANDED, "where": w} for n, w in sorted(elsewhere.items())]
            rec["verdicts"].append(item)
        rec["set"] = list(found)
        rec["words"] = [words(v, STATIC) for v in found]
        if run_dir is None:
            rec["note"] = "; ".join(filter(None, (rec["note"], EMPTY_HOOKS_PATH)))

    def _lossy_setting(self, setting) -> bool:
        """Whether the file a setting came from was read with replacements (a setting names it as the record shows
        it)."""
        return setting.file in self.lossy_shown
