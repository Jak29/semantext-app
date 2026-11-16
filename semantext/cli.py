"""The `semantext` command."""
from __future__ import annotations

import argparse
import functools
import json
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

from . import __version__, agentfiles, claude, jsonread, paths
from .feed import Feed
from .heard import Heard
from .hook import LIMIT_BYTES
from .hook import main as hook_main
from .agents import Agents, Identity, clean, key_shaped, since
from .inbox import (AGENT_MARKERS, HOW_WORDS, SECRET, TOKEN_RUN, Inbox, age, asked_before, describe_answer,
                    human_terminal, mine, register_line, still_open, token_like)
from .backtest import backtest as run_backtest
from . import reading
from .reader import EndpointReader, OllamaReader, is_local, model_backtest
from .mine import mine as mine_history, project_transcripts
from .sender import users_sentence
from .store import FEATURES, Refused, Store, now


def _out(text: str = "") -> None:
    print(text)


_NOT_REPEATED = "(a key-shaped value, not repeated)"


def _shown(value) -> str:
    """A word the person typed, as it may be repeated in a message: quoted, unless it looks like a key, a token or a
    password. A key typed in the wrong place (a name, a profile, an id) must not come back out on the screen, in a log or
    in an agent's transcript; the parser's own errors are scrubbed the same way (_Parser). An ordinary wrong word is
    still named, since naming it is what lets the person see the typo."""
    return _NOT_REPEATED if key_shaped(value) else repr(value)


def _plain(value) -> str:
    """A typed word as it may be repeated, unquoted (a file name): the value, or the note that it is not repeated."""
    return _NOT_REPEATED if key_shaped(value) else str(value)


def _resolve(store: Store, text) -> str:
    """store.resolve, which refuses a key-shaped word without repeating it (a key typed after --env would be printed)
    and still finds an existing environment whose slug is key-shaped (made before `env new` refused such titles)."""
    return store.resolve(text)


# The secret itself, as the shapes in inbox.SECRET find it, cut out of a typed word. Whole-word matching was the first
# backstop's flaw (attack 22, O4): a message echoes a typed word changed (a URL lowercased, a path normalised, a
# backslash doubled, a tab written \t), so the line no longer held the word, and the key stayed in it. The backstop now
# collects the VALUES (the key; the password of user:password@; the word after "password is") and cuts every
# spelling of each from what is written.
_URL_PASSWORD = re.compile(r"[a-z][a-z0-9+.-]{0,31}://[^\s/:@]+:([^\s/@]+)@", re.I)
_ASSIGNED = re.compile(r"(?:password|passwd|passphrase|secret|token|api[_-]?key)\s*[=:]\s*(\S{6,})", re.I)
_PROSE = re.compile(r"\b(?:password|passphrase|passcode)\s+(?:is|was)\s+(\S{4,})", re.I)
# key=VALUE from 4 characters, as the prose form is. inbox.SECRET's key=VALUE arm needs 6 characters after the "=" (it is
# the shared, wide key check), so a 4- or 5-character value with no tail, or a 1-character tail, was never collected and
# the folder message that printed it printed it whole (attack 25, L7). The arm is not widened there (a false alarm in the
# shared check skips a call); the backstop, which only cuts, collects it here.
_ASSIGNED_SHORT = re.compile(r"(?:password|passwd|passphrase|secret|token|api[_-]?key)\s*[=:]\s*(\S{4,})", re.I)
# A JSON web token from its own "eyJ", as inbox.SECRET found it before the arm began at the start of its run (R10): the
# match is now lead+JWT, and a line that prints the JWT without its glued lead must still be cut (attack 25, L9).
_JWT_OWN = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}", re.I)
# Case-insensitive like _JWT_OWN, so a run is the same run for both: under re.I the class also takes U+212A, U+017F, U+0131
# and U+0130, and a run cut at one of them made every "eyJ" of ("eyJ" + U+212A) * n a run of its own, each scanned to the end
# of the text (attack 26, K1: quadratic, 2.7 s at 32,000 characters; 3e5e2ac was linear).
_TOKEN_CHARS = re.compile(r"[A-Za-z0-9_-]+", re.I)
_EYJ = re.compile("eyj", re.I)
_EYJ_TRIES = 8   # "eyJ"s of one run tried; a limit, stated in _jwt_starts


def _jwt_starts(text: str):
    """Yield (start, token, run_start) for every JSON web token in the text from an "eyJ", as inbox.SECRET found them before R10 (the
    old arm had no lead and no lookbehind, so a token glued after anything was found; the arm now begins at the start of
    its run, and a token glued after a key that SECRET has already taken (AKIA + 16 characters, then the token) is not found
    by it at all). Every "eyJ" of a run meets the same dot, so the ones after the first give the same token with a shorter
    first segment: the first _EYJ_TRIES of each run are tried, not only the first, because a key typed glued before the token
    may itself hold e-y-j in some case (attack 26, K3: the first "eyJ" is then inside the key, and the token printed alone was
    left). Linear: at most _EYJ_TRIES attempts per run, each a match() at one place, and a run inside a token already taken
    is not tried again, as finditer would not. Limit: a token whose own "eyJ" is the ninth or later of its run, in a word
    that holds eight earlier ones, is found whole from the earlier ones and not alone."""
    end = 0
    for run in _TOKEN_CHARS.finditer(text):
        if run.start() < end:
            continue
        for n, e in enumerate(_EYJ.finditer(text, run.start(), run.end())):
            if n >= _EYJ_TRIES:
                break
            m = _JWT_OWN.match(text, e.start())
            if m:
                end = max(end, m.end())
                yield e.start(), m.group(0), run.start()


def _jwts(text: str) -> list[str]:
    """Every JSON web token in the text from its own "eyJ" (see _jwt_starts)."""
    return [tok for _, tok, _ in _jwt_starts(text)]
_URL_USER = re.compile(r"[a-z][a-z0-9+.-]{0,31}://([^\s/:@]+):[^\s/@]+@", re.I)
_VALUE_END = re.compile(r"""[\s"'`,;&#()\[\]{}<>/\\]""")   # where a value stops when it is written inside something else
_RUN_NO_SLASH = re.compile(r"[A-Za-z0-9+=_-]{32,}")
_SHORTEST_CUT = 4   # a value shorter than this is not cut (it would be cut out of every word); a limit, stated


def _value_alone(value: str, shortest: int) -> str | None:
    """The value of key=VALUE as a message may print it by itself: _ASSIGNED and _PROSE take everything up to the next
    space (a path tail, a "#model@VAR", "&b=2"), but the secret ends at the first quote, comma, semicolon, &, #, bracket,
    slash or space (attack 22b, O8). None when what is left is shorter than the shapes allow."""
    v = value.lstrip("\"'`")
    end = _VALUE_END.search(v)
    v = v[:end.start()] if end else v
    return v if len(v) >= shortest else None


def secret_values(argv, runs: bool = True) -> set[str]:
    """The secret values typed on a command line: each key-shaped token as the shapes find it inside a word or a path
    component, the password of a user:password@ URL and its user when that is key-shaped (GitHub's token:x-oauth-basic),
    the word after "password is" and the like, each both with whatever follows it up to the next space and alone (cut
    at a quote, comma, semicolon, &, #, bracket or slash, so a message that prints the value without its tail is cut).
    Each argument is looked at alone and all of them joined (a password said across several words). A long run of
    letters and digits that holds a "/" is a token only when it does not look like a path (it does not begin with / or .
    or hold //); its slash-free parts are always looked at. Limit: a token with a "/" inside that begins like a path is
    cut only in its parts. key=VALUE is collected from 4 characters of value whether or not a tail follows (L7; the shared
    key check needs 6, so this module reads the short ones itself); a JSON web token is collected from its own "eyJ" as
    well as with whatever token characters are glued before it (L9). Limit: a word typed after "token:" or "secret="
    and the like is cut from every later message from 4 characters, a key or not (a false alarm costs a word).
    runs=False leaves out the last two arms (a long run of token characters that is no more than key-shaped), for a
    caller that must not call an ordinary long folder name a key (proxycmd.revoke_line, L8)."""
    typed = [str(a) for a in argv or ()]
    found: set[str] = set()
    for text in [*typed, " ".join(typed)]:
        for m in SECRET.finditer(text):
            whole = m.group(0)
            url = _URL_PASSWORD.fullmatch(whole)
            inner = url or _ASSIGNED.fullmatch(whole) or _PROSE.fullmatch(whole)
            found.add(inner.group(1) if inner else whole)
            if url:   # the user half: a key there is as much a key as the password (the key arms never see it: finditer)
                user = _URL_USER.match(whole).group(1)
                found.update(k.group(0) for k in SECRET.finditer(user))
                if token_like(user):
                    found.add(user)
            elif inner:
                # From _SHORTEST_CUT for key=VALUE as for prose (attack 24, L5): the line is key-shaped when SECRET finds
                # VALUE plus a path tail, so the value alone is as much a secret at 4 or 5 characters as at 6; it was
                # collected only from 6, and `password=abcde/h` printed the folder `password=abcde` whole.
                alone = _value_alone(inner.group(1), _SHORTEST_CUT)
                if alone:
                    found.add(alone)
        for at, tok, begin in _jwt_starts(text):   # the token from its own "eyJ", beside whatever SECRET holds of it (L9)
            found.add(tok)
            # The key printed alone, when it was typed glued before the token (attack 26, K3): SECRET's token arm starts at the
            # start of the run and takes the key with it, so the key's own arm never ran; look at the lead of each token. A "_"
            # or "-" typed between the key and the token is the key's own token character: the key is also kept without it.
            for k in SECRET.finditer(text[begin:at]):
                found.update((k.group(0), k.group(0).rstrip("_-")))
        for m in _ASSIGNED_SHORT.finditer(text):   # the 4- and 5-character values SECRET's arm does not reach (L7)
            # The value as typed, to the next space, always (attack 26, K4: with a "#", ",", "/" and the like among its first
            # four characters there is no part "alone" of 4 characters, and the value was not collected at all).
            # Not when it begins with a path or list separator (token=/abc is a path, password="",x is an empty value): limit.
            if not m.group(1).lstrip("\"'`").startswith(("/", "\\", ",", ";", "&")):
                found.add(m.group(1))
            alone = _value_alone(m.group(1), _SHORTEST_CUT)
            if alone:
                found.add(alone)
        if not runs:
            continue
        for m in TOKEN_RUN.finditer(text):
            run = m.group(0)
            if token_like(run) and "/" in run and not run.startswith(("/", ".")) and "//" not in run:
                found.add(run)
        for m in _RUN_NO_SLASH.finditer(text):
            if token_like(m.group(0)):
                found.add(m.group(0))
    return {v for v in found if len(v) >= _SHORTEST_CUT}


def _console_escaped(s: str) -> str:
    """s as pluginpage.ascii_only writes it (a value has no space at its edge): the backslash doubled, every character
    outside U+0020 to U+007E as \\uXXXX or, past U+FFFF, \\UXXXXXXXX."""
    return "".join("\\\\" if c == "\\" else c if " " <= c <= "~" else
                   f"\\u{ord(c):04x}" if ord(c) <= 0xFFFF else f"\\U{ord(c):08x}" for c in s)


def _spellings(value: str) -> set[str]:
    """Every way a message may write a typed value: as typed, with / turned to \\ (a path made native), and each of
    those repr-escaped (a tab as \\t, a quote), ASCII-escaped (\\xe9), \\uXXXX-escaped (JSON's way), escaped the way
    the plug-in console writes text (pluginpage.ascii_only: \\uXXXX up to U+FFFF and \\UXXXXXXXX above, so a Latin-1
    letter beside an astral character is \\u00e4 and \\U0001f600, a mix none of the others makes; attack 22b, O11), and
    with the backslashes doubled (a repr of a repr).

    The plug-in console writes a message through ascii_only AFTER the message has put the typed name through repr
    (`named {key!r}`), so the spelling it prints is ascii_only(repr(name)): repr doubles a backslash and escapes an
    invisible or control character (\\u200b, \\x07) and leaves a Latin-1 letter alone, and ascii_only then doubles every
    backslash again and writes the letter as \\u00e4. That spelling was never built, and a secret holding a letter
    beyond ASCII and also a backslash or an invisible character was printed whole by `plugins show` (attack 24, L4).
    Now ascii_only is applied to EVERY base form (the raw value, its repr, its ascii, its JSON), not to the raw value
    alone; and each base is built from the value as typed and from the value lowered (a message that lowers the name
    before it escapes it writes \\u00e4 where the typed Ä is \\u00c4). The case of the rest is the cut's.
    Limit: that module is not imported (the hook runs this one on every prompt), so its rule is written out here and
    must be kept in step."""
    out = set()
    for typed in {value, value.lower()}:
        for s in (typed, typed.replace("/", "\\")):
            r = repr(s)[1:-1]
            out |= {s, r, r.replace("\\'", "'").replace("'", "\\'"),   # repr escapes a ' only when the name holds " too
                    ascii(s)[1:-1], json.dumps(s)[1:-1], s.encode("unicode_escape").decode("ascii")}
    out |= {_console_escaped(f) for f in out}                         # ascii_only of each: of the raw, of the repr, ...
    for _ in range(2):
        out |= {s.replace("\\", "\\\\") for s in out}
    return {s for s in out if len(s) >= _SHORTEST_CUT}


# The characters the re module reads as one in a case-insensitive match and that casefolding does not join: dotless i
# with i; the two Greek letters with tonos and dialytika (U+0390, U+03B0) with their polytonic twins; the two long-s-t
# ligatures. (The rest of the re module's table is joined by casefold: the Kelvin sign, the long s, the micro sign, ...)
_SAME_CASE = {"ı": "i", "ΐ": "ΐ", "ΰ": "ΰ", "ﬆ": "ﬅ"}


@functools.lru_cache(maxsize=None)
def _fold(c: str) -> str:
    """One character in the case the cut compares in, always one character (so a position in the folded text is the same
    position in the text): its case-folded form when that is one character (K, the Kelvin sign, is k; the long s is
    s), else its lowered form, else the first character of that (a capital I with a dot above is i, as the re module
    reads it), else itself; then the few that the re module joins and casefolding does not (_SAME_CASE)."""
    f = c.casefold()
    if len(f) != 1:
        low = c.lower()
        f = low if len(low) == 1 else low[:1]
    return _SAME_CASE.get(f, f)


def _folded(text: str) -> str:
    return text.lower() if text.isascii() else "".join(map(_fold, text))


_TIERS = (16, 8, 4)   # the forms are looked up by their first 16, 8 or 4 characters (none is shorter than 4)


def _cut(text: str, values) -> str:
    """text without any spelling of any of the values, in any case: the longest first, so a value inside another is
    not left half cut.

    One pass over the text, linear in its length however many values there are (attack 24, L6: one alternation of every
    spelling made each position try every form, 0.44 s for a thousand secrets and 1.7 s for two thousand). The
    spellings are filed by their first 16, 8 or 4 characters, folded to one case; at each position that could begin one
    the text is looked up by those few characters and only the few forms filed under them are compared, the longest
    first. Limit: forms that share their first 16 (or 8, or 4) characters are compared one by one at a position where
    that prefix is met, so a hostile line of thousands of secrets with one prefix and a text full of that prefix costs
    that product; a command line cannot hold enough of them to matter. Case is folded character by character
    (_fold), which is the re module's case-insensitive rule for every character that has one. Forms that overlap are cut
    as their union (a value that ends where a key begins does not leave the rest of the key)."""
    if not text:
        return text
    index: dict[int, dict[str, list[str]]] = {k: {} for k in _TIERS}
    for form in {_folded(f) for v in values for f in _spellings(v)}:
        tier = next(k for k in _TIERS if len(form) >= k)
        index[tier].setdefault(form[:tier], []).append(form)
    if not any(index.values()):
        return text
    for tier in index.values():
        for forms in tier.values():
            forms.sort(key=len, reverse=True)
    begins = re.compile("[" + "".join(re.escape(c) for c in {f[0] for t in index.values() for fs in t.values()
                                                               for f in fs}) + "]")
    folded = _folded(text)
    def size_at(i: int) -> int:
        for tier in _TIERS:                            # a longer tier's forms are all longer than a shorter tier's
            for form in index[tier].get(folded[i:i + tier], ()):
                if folded.startswith(form, i):
                    return len(form)
        return 0

    out, last, i = [], 0, 0
    while True:
        m = begins.search(folded, i)
        if m is None:
            break
        i = m.start()
        size = size_at(i)
        if size:
            # The union of the forms that overlap, not the leftmost alone (attack 26, K5): a short value that ends where a
            # key begins took the cut and the rest of the key was printed. Every position inside the cut is looked at, and a
            # form that begins inside and ends beyond it extends the cut.
            end, j = i + size, i + 1
            while j < end:
                m2 = begins.search(folded, j, end)
                if m2 is None:
                    break
                j = m2.start()
                end = max(end, j + size_at(j))
                j += 1
            out += (text[last:i], _NOT_REPEATED)
            i = last = end
        else:
            i += 1
    out.append(text[last:])
    return "".join(out)


def _unkeyed(text: str, argv) -> str:
    """The last line of defence for what main prints: any secret value typed on this command line is cut out of the
    text wherever it came from, however the message that held it was worded and however it changed the value (see
    secret_values, _spellings). The named sites say it better (_shown, _resolve); this catches the rest, in store.py
    and beyond."""
    return _cut(text, secret_values(argv))


class _Cutting:
    """A text stream that cuts the typed secrets out of what is written through it. On stderr, line by line, as it goes.
    On stdout the lines are held until the command ends, and are cut only if it failed: a command that worked
    prints what it prints. Everything else (encoding, isatty, buffer) is the stream underneath's. Over no stream at all
    (sys.stdout is None under pythonw) it writes nothing, as print() does (attack 22b, O10)."""

    def __init__(self, inner, values, hold: bool = False):
        self._inner, self._values, self._hold = inner, values, hold
        self._tail = ""
        self._held: list[str] = []

    def release(self) -> None:
        """The command turned out to be one a reader waits on line by line (see _streams): give back what was held,
        as it is, and put the stream underneath back in place of this one, so it is as if nothing had been wrapped."""
        held, self._held, self._hold = "".join(self._held), [], False
        if sys.stdout is self:
            sys.stdout = self._inner
        if held and self._inner is not None:
            self._inner.write(held)

    def write(self, s):
        s = s if isinstance(s, str) else str(s)
        if self._inner is None:
            return len(s)
        if self._hold:
            self._held.append(s)
            return len(s)
        head, nl, self._tail = (self._tail + s).rpartition("\n")
        if nl:
            self._inner.write(_cut(head + nl, self._values))
        return len(s)

    def flush(self):
        try:
            self._inner.flush()
        except (OSError, ValueError, AttributeError):   # AttributeError: no stream underneath
            pass

    def finish(self, failed: bool) -> None:
        if self._inner is None:
            self._held, self._tail = [], ""
            return
        if self._hold:
            text, self._held = "".join(self._held), []
            self._inner.write(_cut(text, self._values) if failed else text)
        elif self._tail:
            self._inner.write(_cut(self._tail, self._values))
            self._tail = ""
        self.flush()

    def __getattr__(self, name):
        return getattr(self._inner, name)


_STREAMING = {"hook", "mcp", "serve"}   # commands whose output a reader waits on, line by line: never held


def _streams(args) -> bool:
    """Whether the PARSED command is one a reader waits on: hook, mcp, serve, `start --hook`, `proxy serve`. It is the
    command that decides, never a word typed somewhere in the line (attack 22b, O9: `start --since KEY --from serve`
    printed KEY on stdout because "serve" was typed). Limit: stdout of these is left alone; only stderr is cut."""
    command = getattr(args, "command", None)
    return (command in _STREAMING or (command == "start" and bool(getattr(args, "hook", False)))
            or (command == "proxy" and getattr(args, "action", None) == "serve"))


def _env(store: Store, args) -> str:
    given = getattr(args, "env", None)
    name = _resolve(store, given) if given else store.state()["active"]   # a name or a title; refuses an unknown one
    store.path(name)
    return name


_RULES_SAID = ("Only the user changes their rules, at their own terminal or on the page. Propose a rule with "
               "`semantext teach`; ask for anything else with `semantext ask`")
# What each act that is not a change of rules says after the refusal: the guard is the same, the words fit the act.
# The repo's contract (tests/test_your_words.py): every change refused in an agent's shell names BOTH routes, `teach`
# (a proposed rule) and `ask` (anything else). The owed attack found four acts that had lost `teach`.
_BOTH = "asks with `semantext ask`, or proposes a rule with `semantext teach`"
_ACT_SAID = {
    "start the proxy": ("Only the user starts the proxy, at their own terminal. An agent that needs a call let through "
                        f"{_BOTH}"),
    "answer the proxy": ("Only the user answers what the proxy holds, at their own terminal. An agent cannot release "
                         f"its own held call; it {_BOTH}"),
    "keep a message as the user's": ("Only the user keeps their own words as theirs, at their own terminal. An agent "
                                     f"{_BOTH}"),
    "keep your past messages as yours": ("Only the user keeps their own past messages as theirs, at their own "
                                         f"terminal. An agent {_BOTH}"),
    "forget what was heard": f"Only the user forgets what was heard, at their own terminal. An agent {_BOTH}",
    "accept a proposal": ("Only the user accepts a proposed rule, at their own terminal or on the page. An agent "
                          "proposes a rule with `semantext teach`, or asks with `semantext ask`"),
    "change a setting": f"Only the user changes a setting, at their own terminal or on the page. An agent {_BOTH}",
    "switch a feature": f"Only the user switches a feature, at their own terminal or on the page. An agent {_BOTH}",
    "set the model": f"Only the user chooses the model Semantext uses, at their own terminal. An agent {_BOTH}",
    "clear the model": f"Only the user clears the model Semantext uses, at their own terminal. An agent {_BOTH}",
}


def _users_act(what: str) -> None:
    """An act that is the user's, like answering: refused in an agent's shell, or anywhere that is not their own
    terminal. The guard is one for every act; what is said after it fits the act (changing rules, starting or answering
    the proxy, and the rest). An agent proposes a rule with `teach`, and asks for anything else in the inbox."""
    why_not = human_terminal()
    if why_not:
        raise Refused(f"cannot {what} here: {why_not}. {_ACT_SAID.get(what, _RULES_SAID)}")


# ---- environments and rules -------------------------------------------------------------------------------------
def cmd_init(store: Store, args) -> int:
    _out(f"Semantext {__version__} is ready in {store.root}")
    _out(f"Active environment: {store.title(store.state()['active'])}")
    _out("Next: `semantext card` shows what your AI will receive; `semantext install claude-code` connects it.")
    return 0


def cmd_card(store: Store, args) -> int:
    _out(store.card(_env(store, args), agent=args.agent))
    return 0


def cmd_env(store: Store, args) -> int:
    active = store.state()["active"]
    if args.action in ("use", "new", "add"):
        _users_act({"use": "switch environments", "new": "make an environment", "add": "add rules"}[args.action])
    if args.action == "use":
        if not args.name_or_title:
            raise Refused("name one environment to use, for example: semantext env use default")
        name = _resolve(store, " ".join(args.name_or_title))   # its name or its title: env use "Deep Work"
        store.set_active(name)
        _out(f"Active environment: {store.title(name)}")
        return 0
    if args.action == "new":
        title = " ".join(args.name_or_title)
        if not title:
            raise Refused("give the new environment a title, for example: semantext env new Office")
        sg = store.suggest(title)
        if args.none:
            picks = []
        elif args.pick:
            # Any suggestion from any pack may be picked, by its id (for example work.outcome-first).
            every = {e["id"]: p["environment"]["id"] for p in store.packs() for e in p.get("entries") or []}
            missing = [i for i in args.pick if i not in every]
            if missing:
                raise Refused(f"no such suggestion: {', '.join(_NOT_REPEATED if key_shaped(i) else i for i in missing)} (see them with: semantext env ideas)")
            picks = [{"pack": every[i], "id": i} for i in args.pick]
        elif sg["matched"]:
            picks = [{"pack": r["pack"], "id": r["id"]} for r in sg["rules"] if r["ticked"]]
        else:
            picks = []
        name = store.create(title, picks)
        _out(f"Made {store.title(name)} ({name}) with {len(picks)} suggested rule{'s' if len(picks) != 1 else ''}; "
             f"it is now active.")
        for x in store.load(name).get("entries") or []:
            _out(f"  {x['id']}: {x['statement']}")
        if picks:
            _out("Switch one off with `semantext toggle ID`.")
        if not sg["matched"] and not args.pick and not args.none:
            _out(f"No suggestion pack matches \"{title}\", so it starts empty. Ideas, one from each pack:")
            for r in sg["rules"]:
                _out(f"  {r['id']}: {r['statement']}")
        _out(f"Add suggestions with `semantext env add ID [ID ...]` (every idea: semantext env ideas), "
             f"or teach your own with `semantext teach WORDS`.")
        return 0
    if args.action == "add":
        if not args.name_or_title:
            raise Refused("name the suggestions to add, for example: semantext env add work.outcome-first")
        target = _resolve(store, args.env) if args.env else store.state()["active"]
        added = store.add_suggestions(target, args.name_or_title)
        _out(f"Added {len(added)} rule{'s' if len(added) != 1 else ''} to {store.title(target)}"
             + (f": {', '.join(added)}" if added else " (it already holds them)."))
        return 0
    if args.action == "ideas":
        for p in store.packs():
            env = p["environment"]
            _out(f"{env.get('title', env['id'])} ({env['id']}): {', '.join(env.get('keywords') or [])}")
            for e in p.get("entries") or []:
                _out(f"  {e['id']}: {e['statement']}")
        return 0
    for n in store.names():
        if n == "base":
            continue
        d = store.load(n)
        live = store.live(d.get("entries"))
        mark = "*" if n == active else " "
        _out(f"{mark} {n:<20} {d['environment'].get('title', n):<20} {len(live)} rule{'s' if len(live) != 1 else ''}")
    _out("(* active; every environment also carries the base rules)")
    return 0


def cmd_rules(store: Store, args) -> int:
    name = _env(store, args)
    chain = ["base", name] if args.base else [name]
    for n in chain:
        d = store.load(n)
        entries = d.get("entries") or []
        if args.agent and n == name:   # that agent's own layer, instead of the shared rules
            entries = store.layers(d).get(args.agent) or []
            _out(f"{d['environment'].get('title', n)} ({n}), for {_plain(args.agent)} only")
        else:
            _out(f"{d['environment'].get('title', n)} ({n})")
        shown = 0
        for x in entries:
            if x.get("archived") and not args.all:
                continue
            state = "archived" if x.get("archived") else ("on" if x.get("enabled", True) else "off")
            _out(f"  [{state:<8}] {x.get('mode', 'stationary'):<10} {x['id']}")
            _out(f"             {' '.join(str(x['statement']).split())}")
            shown += 1
        if not shown:
            _out("  (no rules of its own yet)")
        hidden = sum(1 for x in entries if x.get("archived")) if not args.all else 0
        if hidden:
            _out(f"  ({hidden} undone rule{'s' if hidden != 1 else ''} hidden; --all shows {'them' if hidden != 1 else 'it'})")
    return 0


def cmd_teach(store: Store, args) -> int:
    if args.agent and key_shaped(args.agent):   # the name would be written to the file and said back: never a key
        raise Refused("that agent name looks like it holds a key, a token or a password; never put one in a name")
    name, words, agent = _env(store, args), " ".join(args.words), clean(args.agent) if args.agent else None
    if human_terminal() is None:
        rid = store.learn(name, words, agent=agent, misread=args.misread)
        _out(f"Learned {rid}" + (f", for {agent} only," if agent else "") + " with your words kept beside it"
             + (", and the message it was taught from kept as its test." if args.misread else "."))
        return 0
    if args.misread:   # the message an AI misread is kept only as the user's own act, like the rule itself
        raise Refused("a misread message is kept as a test only from your own terminal or the page")
    who = _who(store)
    # An agent may be the scribe of the user's own words: a whole sentence the user wrote in this very session, as
    # the tool's transcript records it, itself shaped as a standing preference, and no question. That is the user's rule.
    spoken = users_sentence(Agents(store.root).transcript_of(who), words)
    if spoken:
        rid = store.learn(name, spoken["sentence"], {
            "type": "LEARNED", "words": spoken["sentence"], "when": now(), "scribe": who.name, "session": who.session,
            "prompt": {"sha256": spoken["sha256"], "at": spoken["at"], "offset": spoken["offset"]}}, agent=agent)
        _out(f"Learned {rid}: the user's own sentence, word for word, from their message in this session.")
        return 0
    # No console, and no agent's tool marks this shell (a script, a pipe, or a terminal window that is not a console):
    # whose words these are cannot be told. Filing them as an agent's proposal would label the user's own typing as an
    # AI's, and learning them would let an unmarked agent write rules; so, as with the user's other acts, refuse.
    if not any(os.environ.get(m) for m in AGENT_MARKERS):
        raise Refused("cannot teach here: not an interactive terminal, and no AI agent's tool marks this shell, so whose "
                      "words these are cannot be told. Teach at your own terminal (in Git Bash's window: winpty "
                      "semantext teach ...) or on the page")
    # In an agent's shell the words came through the agent: they are its proposal, never the user's words. The
    # proposal waits in the inbox and reaches the card only when the user adds it, as it is or in their own wording.
    title = f"Add a rule for {agent} in {store.title(name)}?" if agent else f"Add a rule to {store.title(name)}?"
    r = Inbox(store.root).ask(title, args.why or "An AI agent proposes this rule. It reaches the card only if you add it.",
                              rule=words, env=name, source=who.name, how=who.how, key=who.key,
                              session=who.session or "", agent=agent or "")
    _out(f"[#{r['id']}] Proposed, not learned. The rule waits in the user's inbox, and reaches the card only when they "
         f"add it.")
    return 0


def _uncovered(store: Store, name: str, rule_id: str) -> None:
    """After a rule goes off the card: the kept corrections that needed it, named, so the change is made knowingly."""
    for t in store.depends_on(name, rule_id):
        _out(f"  Uncovered: your correction of \"{_short(t['message'], 70)}\" ({t.get('case', 'a test')}) needed "
             f"{rule_id}; that misreading can come back.")


def _short(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 3] + "..."


def cmd_toggle(store: Store, args) -> int:
    _users_act("switch a rule")
    name = _env(store, args)
    on = store.toggle(name, args.rule_id)
    _out(f"{args.rule_id} is now {'on' if on else 'off'}.")
    if not on:
        _uncovered(store, name, args.rule_id)
    return 0


def cmd_cases(store: Store, args) -> int:
    name = _env(store, args)
    cases = store.cases(name)
    if args.export:
        fields = ("message", "context_before", "reply_tail", "correction", "source", "at", "supersedes", "grounded",
                  "rules", "categories", "expected_reading", "forbidden_reading")
        lines = [json.dumps({k: t[k] for k in fields if k in t}, ensure_ascii=False) for t in cases]
        Path(args.export).write_text("".join(x + "\n" for x in lines), encoding="utf-8")
        _out(f"Wrote {len(lines)} case{'s' if len(lines) != 1 else ''} to {args.export}, in the back-test's case form "
             f"(semantext backtest --cases {args.export}).")
        return 0
    if not cases:
        _out(f"No corrections are kept as tests in {store.title(name)} yet. Teach a rule with the message your AI got "
             f"wrong: semantext teach \"what you meant\" --misread \"the message\".")
        return 0
    covered = sum(t["covered"] for t in cases)
    _out(f"{store.title(name)}: {len(cases)} correction{'s' if len(cases) != 1 else ''} kept as tests, {covered} covered.")
    for t in cases:
        state = "covered" if t["covered"] else f"UNCOVERED: {', '.join(t['missing']) or 'it names no rule'}"
        _out(f"  {t.get('case', '?')}  \"{_short(t['message'], 60)}\"  ->  {', '.join(t.get('rules') or [])}  [{state}]")
    return 0


def cmd_pin(store: Store, args) -> int:
    _users_act("pin a rule")
    mode = store.pin(_env(store, args), args.rule_id)
    _out(f"{args.rule_id} is now {mode}.")
    return 0


def cmd_undo(store: Store, args) -> int:
    _users_act("undo a rule")
    name = _env(store, args)
    if args.last:
        restored = store.undo_last(name)
        _out(f"Undid the last change in {store.title_or_name(name)} (restored {restored}).")
        off, kept = store.last_undo.get("took_off"), store.last_undo.get("kept")
        if store.last_undo.get("problem"):   # after the restore, a step that failed (review of 1.2.2, S5)
            _out(f"But: {store.last_undo['problem']}.")
        if off is None:
            _out(f"The file it replaced could not be read, so what it held cannot be listed. It is kept, as it was, "
                 f"at {kept}: copy back any rule you still want.")
        else:
            if off:
                _out(f"This took off {len(off)} rule{'s' if len(off) != 1 else ''}: {', '.join(off)}.")
            _out(f"The version it replaced is kept at {kept}.")
        return 0
    if not args.rule_id:
        raise Refused("name a rule to undo, or use --last")
    store.undo(name, args.rule_id)
    _out(f"Undid {args.rule_id}: kept in the file, off the card.")
    _uncovered(store, name, args.rule_id)
    return 0


def cmd_read(store: Store, args) -> int:
    r = store.read(_env(store, args), " ".join(args.message), dry=True)
    for x in r["readings"]:
        _out(f"{x['label']}: {x['says']}  [{x['rule']}]")
    for d in r["decisions"]:
        _out(f"{d['ask']}  [{d['rule']}]")
    if r["touched"]:
        _out("Touches: " + ", ".join(r["touched"]))
    # The reader, clause by clause, and its advice for each act (advice only: it can make the gate stricter, never
    # looser). Printed after the lines above, which stay as they were.
    # reading.report is the one reading: the page's reader route (POST /api/read) sends the same, so they never differ.
    got = reading.report(" ".join(args.message), offer=args.offer, acts=args.act)
    if got["readings"]:
        _out("Clause by clause:")
    for d in got["readings"]:
        extra = "".join([f" [{', '.join(d['acts'])}]" if d["acts"] else "", f' ("{d["time"]}")' if d["time"] else ""])
        _out(f"  {d['label']}{extra}: {d['clause']}")
    if got["clipped"]:
        _out(f"  (read up to {reading.MAX_CHARS} characters; the rest was not read)")
    for adv in got["advice"]:
        q = f'  "{adv["quote"]}"' if adv["quote"] else ""
        _out(f"{adv['act']}: {adv['word']} ({adv['rule']}) {adv['why']}{q}")
    return 0


# ---- the proxy --------------------------------------------------------------------------------------------------
def cmd_proxy(store: Store, args) -> int:
    # Imported here, not at the top: the card hook runs this module on every prompt and must not load the proxy's
    # kernel (tests/test_registry.py::test_running_the_hook_scans_no_entry_point).
    from . import proxycmd
    home = proxycmd.proxy_home(store.root, args.proxy_home)
    if args.port is None:
        args.port = proxycmd.DEFAULT_PORT
    if args.action == "serve":
        _users_act("start the proxy")
        if not args.space:
            raise Refused("name the space folder: semantext proxy serve --space FOLDER")
        card = store.card(_env(store, args))
        _out(f"Semantext proxy on http://127.0.0.1:{args.port} for the space in {args.space}, its blocks pinned as they "
             f"are now. Point your AI tool's base URL here and name its agent in the header x-semantext-agent. "
             f"What it holds waits for you: `semantext proxy asks`, then `semantext proxy answer ASK yes|no`. "
             f"Stop it with Ctrl+C.")
        try:
            proxycmd.serve(args.space, home, card, args.port)
        except KeyboardInterrupt:
            _out("Proxy stopped.")
        return 0
    if args.action == "asks":
        try:
            rows = proxycmd.held_asks(home)
        except proxycmd.Starting:
            _out(f"{proxycmd.STARTING[0].upper()}{proxycmd.STARTING[1:]}. Nothing waits for your word yet; ask again "
                 f"in a moment.")
            return 0
        except proxycmd.Stopped:
            _out(f"{proxycmd.STOPPED[0].upper()}{proxycmd.STOPPED[1:]}. Nothing waits for your word; start one with "
                 f"`semantext proxy serve`.")
            return 0
        if not rows:
            _out("Nothing waits for your word.")
        for r in rows:
            line = f"{r['id']}  {r['agent']} -> {r['tool']}  ({r['why']}; {r['minutes_left']} min left)"
            if r["status"] == "yes":
                # A yes not yet used can still be taken back: the line that does it is printed with it, quoted for the
                # shell it is printed in (K7). An id the proxy did not mint, or a home that cannot be quoted, gets no line.
                take_back = proxycmd.revoke_line(r["id"], args.proxy_home, args.home)   # every option that chose the home
                note = proxycmd.revoke_note(args.proxy_home, args.home) if take_back else ""
                line += ("  a yes not yet used; to take it back: " + take_back + (f"  {note}" if note else "") if take_back else
                         "  a yes not yet used (its id or home cannot be pasted safely, so no command is printed for it)")
            _out(line)
        return 0
    if args.action == "answer":
        _users_act("answer the proxy")
        if len(args.rest) != 2:
            raise Refused("answer one ask: semantext proxy answer ASK yes|no|revoke")
        state = proxycmd.answer(home, args.rest[0], args.rest[1].lower())
        _out(f"Ask {args.rest[0]} is now {state}." + (
            " The held call can go through once, in that chat: with its held turn at the chat's next message if every"
            " call of the turn has your yes, or when the agent makes the call again. Not while your newest message in"
            " that chat names one of its acts other than as a plain go (\"skip the delete\"); a bare \"stop\" names"
            " none. `semantext proxy answer ASK revoke` takes the yes back."
            if state == "yes" else ""))
        return 0
    raise Refused("say serve, asks or answer")


def cmd_where(store: Store, args) -> int:
    _out(str(store.path(_env(store, args))))
    return 0


# ---- what was heard ---------------------------------------------------------------------------------------------
def cmd_hear(store: Store, args) -> int:
    _users_act("keep a message as the user's")
    item = Heard(store.root).hear(_env(store, args), " ".join(args.text))
    _out(f"Heard #{item['id']} (kept on this machine).")
    return 0


def cmd_recall(store: Store, args) -> int:
    items = Heard(store.root).recall(_env(store, args), " ".join(args.query or []), args.n)
    if not items:
        _out("Nothing heard" + (" that matches." if args.query else " yet."))
    for i in items:
        _out(f"#{i['id']} {i['when']} ({i.get('source', 'you')}): {i['text']}")
    return 0


def cmd_forget(store: Store, args) -> int:
    _users_act("forget what was heard")
    if not args.all and not args.ids:
        raise Refused("name the items to forget, or use --all")
    gone = Heard(store.root).forget(_env(store, args), None if args.all else args.ids)
    _out(f"Forgot {gone} item{'s' if gone != 1 else ''}.")
    return 0


def cmd_propose(store: Store, args) -> int:
    name = _env(store, args)
    if args.accept:
        _users_act("accept a proposal")
    props = Heard(store.root).propose(name, store)
    if args.accept:
        chosen = {p["n"]: p for p in props}
        for n in args.accept:
            if n not in chosen:
                raise Refused(f"no proposal number {n}")
        for n in args.accept:
            rid = store.learn(name, chosen[n]["statement"])
            _out(f"Accepted {n} as {rid}.")
        return 0
    if not props:
        _out("No proposals yet: nothing heard sounds like a standing preference or a correction.")
        return 0
    for p in props:
        _out(f"{p['n']}. {p['statement']}  (from heard #{p['heard']})")
    _out("Accept with: semantext propose --accept N [N ...]")
    return 0


def cmd_mine(store: Store, args) -> int:
    name = _env(store, args)
    if not args.dry_run:
        _users_act("keep your past messages as yours")
    files = args.files or project_transcripts(args.project or os.getcwd())
    if not files:
        raise Refused("no transcripts found for this project: name the files, or use --project DIR")
    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        raise Refused(f"not a file: {_plain(missing[0])}")
    r = mine_history(store, name, files, dry_run=args.dry_run)
    if args.json:
        _out(json.dumps(r))
        return 0
    verb = "Would keep" if args.dry_run else "Kept"
    _out(f"Read {r['files']} transcript{'s' if r['files'] != 1 else ''}: {r['prompts']} prompts.")
    _out(f"{verb} {r['kept']} of your own messages in {store.title(name)} ({r['by_record']} by the tool's record, "
         f"{r['by_text_only']} by their words alone).")
    _out(f"Left out: {r['not_users']} not yours (other agents' messages, notices), {r['summaries']} summaries, "
         f"{r['secrets']} that looked like a key or a password, {r['duplicates']} already kept, {r['empty']} empty.")
    _out(f"Found {r['corrections']} correction{'s' if r['corrections'] != 1 else ''} of a reply.")
    _out("Nothing became a rule. `semantext propose` lists the rules your words suggest; only you accept them.")
    return 0


def _pct(x: dict) -> str:
    return "n/a" if x["p"] is None else f"{x['p']:.0%} ({x['lo']:.0%} to {x['hi']:.0%})"


def _skill(s: dict) -> str:
    return "n/a" if s["value"] is None else f"{s['value']:+.2f} ({s['lo']:+.2f} to {s['hi']:+.2f})"


def cmd_backtest(store: Store, args) -> int:
    name = _env(store, args)
    if args.split and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.split):
        raise Refused("give --split as a date, YYYY-MM-DD")
    files = args.files or ([] if (args.cases or args.finder) and not args.project
                           else project_transcripts(args.project or os.getcwd()))
    if not files and not args.cases and not args.finder:
        raise Refused("no transcripts found for this project: name the files, or use --project DIR")
    for f in [*files, *(x for x in (args.cases, args.finder) if x)]:
        if not Path(f).is_file():
            raise Refused(f"not a file: {_plain(f)}")
    if args.weighed:
        if (args.reader or args.cases or args.finder or args.split or args.show or args.judge or args.ablate
                or args.samples != 1 or args.clean_sample is not None):
            raise Refused("--weighed reads transcripts only, and cuts them by time itself: leave off --reader, --judge, "
                          "--ablate, --samples, --clean-sample, --cases, --finder, --split and --show")
        return _weighed_backtest(store, name, args, files)
    if args.reader:
        return _model_backtest(store, name, args, files)
    if args.judge or args.ablate or args.samples != 1 or args.clean_sample is not None:
        raise Refused("--judge, --ablate, --samples and --clean-sample go with --reader")
    r = run_backtest(store, name, files, cases=args.cases, finder=args.finder, split=args.split, show=args.show)
    if args.json:
        _out(json.dumps(r))
        return 0
    u = r["units"]
    if files:
        _out(f"Back-test of {store.title(name)} ({r['card_rules']} rules of its own) on {len(files)} transcript"
             f"{'s' if len(files) != 1 else ''}: {u['misread']} messages you then corrected, {u['clean']} you did "
             f"not, and {u['corrections']} corrections.")
        _out(f"  Touched, of the corrected: {_pct(r['coverage'])}. Of the rest: {_pct(r['false_touch'])}.")
        _out(f"  Skill (the difference): {_skill(r['skill'])}. Base rules alone: {_skill(r['nulls']['base']['skill'])}."
             f" {r['nulls']['matched']['rules']} rules drawn from the suggestion packs: "
             f"{_skill(r['nulls']['matched']['skill'])}.")
        if r["split"]["in_sample"]:
            _out("  In-sample: rules taught from these very corrections touch them. Use --split DATE for a fair score.")
        _out("  Touched means a rule bears on the message, not that an AI would have read it right.")
        for s in r.get("silent", []):
            _out(f"  - silent on: {s['message']!r}\n    you said: {s['correction']!r}")
    if "cases" in r:
        c = r["cases"]
        _out(f"Cases: {c['n']}. Touched: {_pct(c['touched'])}. The right rule, of the {c['with_rules']} that name "
             f"one: {_pct(c['hit'])}.")
    if "finder" in r:
        f = r["finder"]
        _out(f"Finding corrections, on {f['n']} labelled messages: precision {f['precision']}, recall {f['recall']}.")
    return 0


def _weighed_backtest(store: Store, name: str, args, files) -> int:
    from .weigh import measure
    r = measure(store, name, files, alpha=args.alpha)
    if args.json:
        _out(json.dumps(r))
        return 0
    c, p = r["card"], r["parts"]
    w, u, g = c["weighed"], c["unweighed"], c["precision_gain"]
    _out(f"Weighed back-test of {store.title(name)} ({c['rules']} rules of its own) on {len(files)} transcript"
         f"{'s' if len(files) != 1 else ''}. Weights from the earlier {p['fit_misread']} corrected and {p['fit_clean']} "
         f"other messages; the threshold from the next {p['calib_clean']}; scored on the last {p['test_misread']} "
         f"corrected and {p['test_clean']} others.")
    _out(f"  Weighed: touched {_pct(w['coverage'])} of the corrected, {_pct(w['false_touch'])} of the rest "
         f"(ceiling {r['alpha']:.0%}: {'holds' if w['ceiling']['holds'] else 'FAILS'}). Skill {_skill(w['skill'])}.")
    _out(f"  Unweighed, on the same messages: {_pct(u['coverage'])} and {_pct(u['false_touch'])}. "
         f"Skill {_skill(u['skill'])}.")
    _out(f"  Precision gain: {_skill(g)}. Verdict: {c['verdict']}.")
    if c["consistency"]["disagreements"]:
        _out(f"  On {c['consistency']['disagreements']} messages the weighed cues differ from the back-test's own "
             f"touch, so this result is not to be read.")
    return 0


def make_reader(spec: str, key_env: str | None):
    """ollama:MODEL, on this machine; or endpoint:URL#MODEL[@VARIABLE], an OpenAI-compatible endpoint, with the
    environment variable that holds its own key (otherwise --key-env's)."""
    kind, _, rest = spec.partition(":")
    if kind == "ollama" and rest:
        return OllamaReader(rest)
    if kind == "endpoint" and "#" in rest:
        url, _, model = rest.rpartition("#")
        model, _, own_key = model.partition("@")
        if url.startswith(("http://", "https://")) and model:
            return EndpointReader(url, model, key_env=own_key or key_env or "")
    raise Refused(f"not a reader: {_shown(spec)}. Use ollama:MODEL or endpoint:URL#MODEL[@KEY_VARIABLE]")


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].lower()


def _via_proxy(url: str) -> str:
    """", by way of the proxy HOST" when this machine's proxy settings route the call: an address off this machine
    keeps them (reader._open), so the notice names every host the words pass through (Orithises, 1.5.13)."""
    import urllib.parse
    import urllib.request
    scheme = url.split("://", 1)[0].lower()
    proxy = urllib.request.getproxies().get(scheme)
    # the very host urllib's ProxyHandler hands proxy_bypass, port and all, so the answer is the one the call gets
    if not proxy or urllib.request.proxy_bypass(urllib.request.Request(url).host):
        return ""
    try:   # its host and port only: a proxy's address can carry a name and password, and those are never printed
        p = urllib.parse.urlsplit(proxy if "://" in proxy else "http://" + proxy)
        where = (f"[{p.hostname}]" if ":" in (p.hostname or "") else p.hostname or "?") + (f":{p.port}" if p.port else "")
    except ValueError:
        where = "named in your proxy settings"
    return f", by way of the proxy {where}"


def _model_backtest(store: Store, name: str, args, files) -> int:
    reader = make_reader(args.reader, args.key_env)
    judges = [make_reader(j, args.key_env) for j in args.judge]
    if judges and len(judges) != 2:
        raise Refused("name two judges, or none: only their agreement counts")
    if not files and not args.cases:
        raise Refused("a model reading needs transcripts or --cases")
    hosts_by_key: dict[str, set] = {}   # whoever named the variable, --key-env or the endpoint itself
    for x in (reader, *judges):
        if isinstance(x, EndpointReader) and x.key_env:
            hosts_by_key.setdefault(x.key_env, set()).add(_host(x.url))
    for var, hosts in sorted(hosts_by_key.items()):
        if len(hosts) > 1:   # one key goes to the one host it was issued for, never to another provider
            raise Refused(f"the key in {var} would go to {', '.join(sorted(hosts))}: one key goes to one host. Give "
                          f"each endpoint its own key variable: endpoint:URL#MODEL@VARIABLE")
    off = [x for x in (reader, *judges) if isinstance(x, EndpointReader) and not is_local(x.url)]
    why_not = human_terminal() if off else None
    if why_not:   # the same shape as record topics (Orithises's attack on 1.5.10, K1): off this machine is yours to start
        raise Refused(f"a reading that leaves this machine ({_host(off[0].url)}) is yours to start, at your own "
                      f"terminal: this is {why_not}")
    for x in (reader, *judges):
        if isinstance(x, EndpointReader) and not is_local(x.url):
            what = ("the card and the messages" if x is reader else
                    "the messages, their readings, and what each is judged against (for your transcripts, your "
                    "corrections and the end of each reply you corrected)")
            clear = (", in clear: readable on the network on its way" if x.url.lower().startswith("http://")
                     else "")
            _out(f"This sends {what} to {_host(x.url)}, outside this machine{clear}{_via_proxy(x.url)} ({x.name}).")
        if isinstance(x, OllamaReader):
            x.resolve_version()                    # the model's digest on this machine, so a reading names its build
    r = model_backtest(store, name, reader, judges=judges, files=files, cases=args.cases, split=args.split,
                       samples=max(1, args.samples), ablate=args.ablate, clean_sample=args.clean_sample)
    if args.json:
        _out(json.dumps(r))
        return 0
    c = r["calls"]
    _out(f"Model reading by {r['reader']['name']} (version {r['reader']['version']}): {c['made']} calls, "
         f"{c['secret_skipped']} left out for a secret, {c['unparsed']} replies that were not a reading.")
    if "touched" in r:
        t = r["touched"]
        _out(f"  Touched, of the corrected: {_pct(t['coverage'])}. Of the rest: {_pct(t['false_touch'])}. Skill: "
             f"{_skill(t['skill'])}; the same model on a same-size drawn card: {_skill(t['nulls']['matched']['skill'])}.")
    if "reading" in r:
        g = r["reading"]
        _out(f"  The reading, card against blind, on {g['n']} judged cases: {g['b']} put right, {g['c']} put wrong "
             f"(McNemar p={g['mcnemar_p']}); difference {_skill(g['diff'])}; {g['disputed']} disputed.")
    if "cases" in r:
        _out(f"  The right rule, of the {r['cases']['with_rules']} cases that name one: {_pct(r['cases']['hit'])}.")
    if r.get("power", {}).get("corrected_n"):
        p = r["power"]
        gain = "no gain up to the largest" if p["min_net_gain_80"] is None else f"a net gain of {p['min_net_gain_80']}"
        _out(f"  Power: with {p['corrected_n']} pairs, the test finds {gain} four times in five.")
    _out(f"  Every number here is one model's: {r['reader']['name']}. A reading is a measurement, never a rule.")
    return 0


def cmd_config(store: Store, args) -> int:
    if args.key == "hear-prompts":
        if args.value is None:
            _out(f"hear-prompts: {'on' if store.state().get('hear_prompts') else 'off'}")
            return 0
        _users_act("change a setting")
        store.set_option("hear_prompts", args.value == "on")
        _out(f"hear-prompts: {args.value}")
    return 0


WORDS_SAID = {"own": "your words", "agent": "an agent's", "tool": "a tool's"}


def cmd_feed(store: Store, args) -> int:
    """What Semantext sent with each prompt, newest first: never what was said. On and off are the user's act."""
    if args.state:
        _users_act("change a setting")
        store.set_option("feed", args.state == "on")
        _out(f"feed: {args.state}" + ("" if args.state == "on" else
                                      " (nothing more is written; what is kept stays until it is cut back)"))
        return 0
    records = Feed(store.root).recent(max(1, min(200, args.n)))
    _out(f"feed: {'on' if store.state().get('feed', True) else 'off'}. What each prompt was sent, newest first "
         f"(never what was said): {len(records)} shown.")
    for r in records:
        layers = " + ".join(f"{x['layer']} {len(x['ids'])}" for x in r["layers"]) or "no rules"
        extra = "".join([f", {r['left_out']} left out by the size limit" if r["left_out"] else "",
                         f", answers #{', #'.join(map(str, r['answers']))}" if r["answers"] else "",
                         ", a file could not be read" if r["problem"] else ""])
        _out(f"{r['at'][11:19]}  {r['agent']} ({HOW_WORDS.get(r['how'], r['how'])}): {WORDS_SAID[r['words']]}, "
             f"{'full' if r['form'] == 'full' else 'short'} card in {r['environment']}, {layers}, {r['bytes']} bytes"
             f"{extra}")
    return 0


# ---- the page, the hook and Claude Code -------------------------------------------------------------------------
def cmd_serve(store: Store, args) -> int:
    from .server import serve
    return serve(store, args.host, args.port, args.open)


def cmd_mcp(store: Store, args) -> int:
    from .mcp import serve
    return serve(store)


def cmd_statusline(args) -> int:
    """One line for Claude Code's status bar, from your sources: what waits for your word, or how many of your
    decisions are in force. It reads whatever Claude Code sends on standard input and ignores it, writes nothing (it
    never opens the home, so it never creates one), and never fails: on any trouble it prints "Semantext: unavailable"
    and exits 0."""
    sys.dont_write_bytecode = True   # nothing is written, not even a cached copy of the code it loads
    line = "Semantext: unavailable"
    try:
        stdin = sys.stdin
        if stdin is not None and not stdin.isatty():
            import threading   # read in the background, so a sender that never closes cannot hold the line up

            def drain():
                try:
                    getattr(stdin, "buffer", stdin).read(1 << 20)
                except Exception:  # noqa: BLE001
                    pass
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            reader.join(0.5)
    except Exception:  # noqa: BLE001  what Claude Code sends is not used, so a fault reading it changes nothing
        pass
    try:
        from .sources import view
        line = view.status_line(Path(args.home).expanduser() if args.home else None, args.width)
    except Exception:  # noqa: BLE001  the last resort: still one line
        pass
    try:
        print(line)
    except Exception:  # noqa: BLE001
        pass
    return 0


def _target_file(args) -> Path:
    if args.file:
        return Path(args.file).expanduser()
    return agentfiles.default_file(args.tool)


def _not_an_agents_shell(what: str) -> None:
    """Disconnecting Semantext, or wiring a command of one's own into the hook, is the user's act: refused in a shell an
    AI tool marks as its agent's. The user's own scripts may still do it, so this asks for no console."""
    if any(os.environ.get(m) for m in AGENT_MARKERS):
        raise Refused(f"cannot {what} here: an agent's shell. The user runs this themselves")


def cmd_install(store: Store, args) -> int:
    if args.tool == "claude-code":
        path = Path(args.settings).expanduser() if args.settings else claude.default_settings()
        command = args.hook_command or claude.hook_command(store.root)
        if args.apply and command != claude.hook_command(store.root):
            _not_an_agents_shell("connect a hook command of your own")   # the standard hook stays an agent's to add
        if not args.apply:
            _out(f"These entries would be added to {path}, leaving out any already there:")
            _out(json.dumps(claude.snippet(command), indent=2))
            _out("One sends your card with every prompt; the other shows the start screen when a session starts.")
            _out("Run again with --apply to add them (a backup of the file is saved first).")
            return 0
        changed, backup = claude.install(path, command)
        if not changed:
            _out(f"Already connected: {path} runs Semantext's hook.")
            return 0
        start = claude.start_command(command)
        _out(f"Connected: {path} runs Semantext's hook on every prompt" + (f", and `{start}` when a session starts." if start else "."))
    else:
        path = _target_file(args)
        card = store.card(store.state()["active"])
        if not args.apply:
            _out(f"This block would be added to {path} (everything else in the file stays as it is):")
            _out(agentfiles.block(card))
            _out("Run again with --apply to add it (a backup of the file is saved first).")
            return 0
        changed, backup = agentfiles.install(path, card)
        agentfiles.remember(store, path)
        if not changed:
            _out(f"Already connected and current: {path}.")
            return 0
        _out(f"Connected: {path} tells your agent to run `semantext card`, with a copy of the card. "
             f"`semantext sync` refreshes the copy after you change your rules.")
    if backup:
        _out(f"Backup of the previous file: {backup}")
    return 0


def cmd_uninstall(store: Store, args) -> int:
    if args.apply:
        _not_an_agents_shell("disconnect Semantext")   # taking the card away from every agent is the user's act
    if args.tool == "claude-code":
        path = Path(args.settings).expanduser() if args.settings else claude.default_settings()
        if not args.apply:
            _out(f"Every Semantext hook entry would be removed from {path}. Run again with --apply to remove it.")
            return 0
        changed, backup = claude.uninstall(path)
        _out(f"Disconnected: removed from {path}." if changed else f"Nothing to remove: {path} has no Semantext hook.")
    else:
        path = _target_file(args)
        if not args.apply:
            _out(f"Semantext's block would be removed from {path}, and nothing else. Run again with --apply to remove it.")
            return 0
        changed, backup = agentfiles.uninstall(path)
        agentfiles.forget(store, path)
        _out(f"Disconnected: removed the block from {path}." if changed else f"Nothing to remove: {path} has no block.")
    if backup:
        _out(f"Backup of the previous file: {backup}")
    return 0


def cmd_sync(store: Store, args) -> int:
    results = agentfiles.sync(store)
    if not results:
        _out("Nothing to sync: no instructions file is connected (semantext install codex | freebuff | agents-md).")
    for path, what in results:
        _out(what if path in what else f"{what}: {path}")   # a problem's own words already name the file
    return 1 if any(what.startswith("PROBLEM") for _, what in results) else 0   # as doctor does


def cmd_export(store: Store, args) -> int:
    card = store.card(_env(store, args))
    if args.kind == "system-prompt":
        _out(card)
    else:
        if '"""' in card:
            raise Refused('a rule holds three double quotes ("""), which a Modelfile cannot carry; change that rule, '
                          "or use `semantext export system-prompt`")
        _out(agentfiles.modelfile(card, args.base or ""))
    return 0


def cmd_feature(store: Store, args) -> int:
    _users_act("switch a feature")
    name = _env(store, args)
    store.feature(name, args.name, args.state == "on", args.country or "")
    _out(f"{args.name}: {args.state} in {store.title(name)}")
    return 0


# ---- the inbox ----------------------------------------------------------------------------------------------------
def _show_request(r: dict, full: bool = True) -> None:
    how = HOW_WORDS.get(r.get("from_how") or "")
    sender = f"from {r['from']} ({how})" if how else f"from, as stated: {r['from']}"
    head = f"#{r['id']}  {r['title']}   ({sender}; asked {age(r['at'])} ago)"
    if r["status"] != "open":
        head += f"  [{r['status']}]"
    elif r.get("parked"):   # open, and set aside by the user: never listed as if it waited
        head += "  [parked: set aside by you, not answered]"
    _out(head)
    if not full:
        return
    _out(f"    why: {r['why']}")
    if r["kind"] == "decision":
        _out(f"    {r['question']}")
        for i, o in enumerate(r["options"], 1):
            _out(f"      {i}. {o}" + ("  (recommended)" if r.get("recommend") == i else ""))
    elif r["kind"] == "rule":
        target = f"{r['agent']} only, in {r['env']}" if r.get("agent") else r["env"]
        _out(f"    the proposed rule, for {target}: {r['statement']}")
        _out("    It reaches the card only if you add it. Answer add, or add followed by your own wording (which "
             "replaces the agent's), or no.")
    else:
        _out(f"    command: {r['command']}" + (f"   (in {r['cwd']})" if r.get("cwd") else ""))
        _out(f"    what it does: {r['does']}")
        _out(f"    to undo it: {r['undo']}")
        if r.get("flags"):
            _out(f"    second look: {'; '.join(r['flags'])} (no flag does not mean safe)")
        _out("    Semantext never runs it. Run it yourself if you agree, then answer Done or Won't do.")
    if r.get("answer"):
        via = r["answer"].get("via")
        _out(f"    answered: {describe_answer(r)}" + (f" (via {via})" if via in ("terminal", "page", "chat") else ""))
    if r.get("closed"):
        by = r["closed"].get("by")
        _out(f"    withdrawn{f' by {by}' if by else ''}: {r['closed'].get('how') or 'no reason given'}")


def _who(store: Store) -> Identity:
    """The agent this shell belongs to, worked out the way the hook works it out (see agents.py)."""
    return Agents(store.root).identify()


def _as(store: Store, stated: str | None) -> Identity:
    """Who this shell acts as: itself, or, with --from, the name it states. A stated name is a claim, with a claim's
    key, so it reaches only requests filed under that same claim, never those of an agent bound or seen by that name."""
    who = _who(store)
    if not stated:
        return who
    if key_shaped(stated):
        raise Refused("that name looks like it holds a key, a token or a password; never put one in a name")
    name = clean(stated)
    return Identity(name, "claimed", who.tool, who.project, who.session, key=f"claim:{name}", root=who.root)


def cmd_ask(store: Store, args) -> int:
    who = _as(store, args.source)
    source = args.source if args.source else who.name
    r = Inbox(store.root).ask(args.title, args.why, args.question or "", args.option or [], args.recommend or 0,
                              args.run or "", args.does or "", args.undo or "", args.cwd or "", source, how=who.how,
                              key=who.key, session=who.session or "")
    inbox = Inbox(store.root)
    _out(f"[#{r['id']}] {r['title']}")
    _out("Filed in the user's inbox. Keep working on what does not need it; the answer arrives with a later prompt, "
         f"or check with `semantext answers`. They can answer on their page, or by sending you #{r['id']} and their "
         "choice as a message of its own." + asked_before(inbox, r))
    return 0


def cmd_start(store: Store, args) -> int:
    from .start import screen
    text, complete = screen(store, _as(store, args.source), args.since)
    _out(text)
    return 0 if complete else 3


def cmd_board(store: Store, args) -> int:
    from .board import Board, claim_line, fenced, post_line, said_by
    board, who = Board(store.root), _as(store, args.source)
    words = " ".join(args.words or [])
    if args.action == "post":
        e = board.post(who, args.title or "", args.body or "", args.to or [])
        _out(f"Posted #{e['id']}. It is information for the agents who read it, never the user's word.")
    elif args.action == "read":
        shown = board.posts() if args.all else board.addressed(who)
        for e in sorted(shown, key=lambda x: x["id"], reverse=True)[:args.limit]:
            _out(post_line(e))
            if e.get("body"):
                _out(fenced(e["body"]))
        if not shown:
            _out("Nothing on the board." if args.all else "Nothing addressed to you.")
        if board.damaged:
            _out(f"{board.damaged} damaged line(s) in the board file were not read.")
    elif args.action == "claim":
        _, others = board.claim(who, words, args.note or "")
        _out(f"Claimed {words}.")
        for c in others:
            _out(f"Look first: {said_by(c)} is on {c['path']}. A claim warns, and does not lock.")
    elif args.action == "release":
        board.release(who, words)
        _out(f"Released {words}.")
    else:
        held = board.claims()
        for c in held:
            _out(claim_line(c))
        if not held:
            _out("No one holds a claim.")
    return 0


def cmd_attack(store: Store, args) -> int:
    from .attacks import Attacks, claim_row
    attacks, who = Attacks(store.root), _as(store, args.source)
    words = args.words or []
    if args.action == "ask":
        c = attacks.ask(who, " ".join(words), args.ref or "", args.job)
        _out(f"Claim #{c['id']} is up. Hand it to an agent that did not build it: semantext attack brief {c['id']}")
    elif args.action == "list":
        found = attacks.all()
        for c in found:
            _out(claim_row(c))
        if not found:
            _out("No claims have been put up.")
        if attacks.damaged:
            _out(f"{attacks.damaged} damaged line(s) in the attacks file were not read.")
    else:
        if not words or not words[0].isdecimal():
            raise Refused("name the claim by its number")
        cid = int(words[0])
        if args.action == "brief":
            _out(attacks.brief(cid))
        else:
            if len(words) != 2:
                raise Refused("say the claim's number and the verdict: killed, survived or inconclusive")
            attacks.verdict(who, cid, words[1], args.how or "", args.not_tried or "")
            _out(f"Verdict kept: #{cid} {words[1]}.")
    return 0


def cmd_record(store: Store, args) -> int:
    """record topics: the model you chose in Semantext (or --reader) gives a topic to each decision no project groups,
    for the Record's threads. Run only when you ask; the page never calls a model."""
    from . import topics
    from .sources import view
    # Your words go to a model, so asking is your act: at your own terminal, never from an agent's shell (Orithises's
    # attack on 1.5.10, K1: an agent could run this and name any host).
    why_not = human_terminal()
    if why_not:
        raise Refused(f"record topics is yours to run, at your own terminal: this is {why_not}")
    if args.reader:
        reader = make_reader(args.reader, args.key_env)
    else:
        model = store.state().get("model")
        if not model:
            raise Refused("name the model to ask, on this machine: --reader ollama:MODEL (`ollama list` shows yours). "
                          "Until you do, the Record groups by project and subject only")
        reader = OllamaReader(model)
    if isinstance(reader, EndpointReader) and not is_local(reader.url):
        raise Refused(f"your decisions stay on this machine: {_host(reader.url)} is not. Use a model on this machine "
                      f"(ollama:MODEL, or an endpoint at 127.0.0.1)")
    identity = None
    if isinstance(reader, OllamaReader):
        why = reader.missing()
        if why:
            raise Refused(why)
        reader.resolve_version()
        identity = _record_identity(store, reader)
    got = view.answer("record", home=store.root)
    if not got or got.get("off"):
        raise Refused("your Record is off: your sources file names no register, and you have answered nothing yet")
    by_id = {e.get("id"): e for e in got.get("entries") or []}
    loose = [by_id[i] for g in got.get("groups") or [] if g.get("kind") != "project" for i in g.get("entries") or []
             if i in by_id and not by_id[i].get("superseded_by")]
    if args.limit:
        loose = loose[: max(0, args.limit)]
    c = topics.run(store.root, loose, reader, again=args.again, identity=identity)
    _out(f"Topics by {reader.name} (version {getattr(reader, 'version', '?')}): {c['named']} named, {c['kept']} kept from "
         f"before, {c['secret_skipped']} left out for a secret, {c['unparsed']} answers that were not a topic, "
         f"{c['failed']} calls that failed. A topic is the model's reading, and the page says so.")
    if c.get("stopped"):
        _out(f"Stopped after {topics.STOP_AFTER} calls in a row failed: is the model still running? What was named is "
             "kept; run this again to go on.")
        return 1
    return 0


def _record_identity(store: Store, reader) -> str:
    """The gap 1.5.10 left (ECOSYSTEM, the ninth point): the runtime's own digest, compared with the one the person
    named in their model settings when those name this model. Differs: refused, or each topic marked, as the settings
    say. None named: said, and each topic marked as the runtime's claim."""
    from . import model
    raw = store.state().get(model.SETTING)
    try:
        conf = model.settings(raw) if raw else None
    except Refused:
        conf = None
    if not conf or model._model_name(conf["model"]) != model._model_name(reader.model) or not conf["digest"]:
        _out(f"The version of {reader.model} is its runtime's own report: you have named no digest to compare it with "
             f"(semantext model set --model {reader.model} --digest D). Each topic is marked so.")
        return "the runtime's claim"
    got = getattr(reader, "digest", None)
    if model.whole_digest(got) and model.digest_matches(got, conf["digest"]):
        return "matches yours"
    problem = (f"{reader.model} reports {(got or 'no digest')[:19]}{'' if model.whole_digest(got) else ' (not a full digest)'}"
               f", but your settings expect {conf['digest'][:19]}")
    if conf["on_mismatch"] == "refuse":
        raise model.ModelRefused("M-ID", problem + ": nothing is asked. If the model changed, name its new digest")
    _out(f"Problem: {problem}. Your settings say to flag it: the run goes on, and each topic is marked.")
    return "differs from yours"


def cmd_model(store: Store, args) -> int:
    """The model point (1.6): your settings for a model on this machine, and asking it. Its answers wait in your
    inbox as proposals labelled MODEL; nothing is ever done with them unless you act."""
    from . import model
    a = args.action
    if a == "set":
        _users_act("set the model")
        cur = dict(store.state().get(model.SETTING) or {})
        for k, v in (("address", args.address), ("model", args.model_name), ("digest", args.digest),
                     ("budget_s", args.budget), ("max_tokens", args.tokens), ("on_mismatch", args.on_mismatch),
                     ("asks_per_hour", args.asks_per_hour)):
            if v is not None:
                cur[k] = v
        if args.budget is not None and float(args.budget).is_integer():
            cur["budget_s"] = int(args.budget)
        store.set_model_provider(cur)
        a = "show"
    if a == "clear":
        _users_act("clear the model")
        store.set_model_provider(None)
        _out("The model settings are cleared: nothing will be asked until you set them again.")
        return 0
    if a == "show":
        raw = store.state().get(model.SETTING)
        if not raw:
            _out("No model is set. Set one: semantext model set --address http://127.0.0.1:PORT --model NAME "
                 "--digest D")
            return 0
        c = model.settings(raw)
        _out(f"Model: {c['model']} at {c['address']} (the one address it may use)")
        _out(f"  Expected digest: {c['digest'] or 'none: every call is refused until you name one'}")
        _out(f"  Budget: {c['budget_s']} s a call, at most {c['max_tokens']} tokens; {c['asks_per_hour']} asks an hour")
        _out(f"  A digest that differs is {'refused' if c['on_mismatch'] == 'refuse' else 'shown as a problem'}.")
        return 0
    if a == "check":
        if not args.file:
            raise Refused("name the model's file: semantext model check --file PATH")
        c = model.settings(store.state().get(model.SETTING))
        got = model.check_file(args.file, c, args.manifest)
        _out(f"The manifest {got['manifest_path']} hashes to {got['manifest'][:19]}, the model ID you named, and "
             f"{args.file} to {got['weights'][:19]}, the weights it names. This checks the files on disk; each call "
             f"checks what the runtime reports, separately.")
        return 0
    words = " ".join(args.words or []).strip()
    if not words:
        raise Refused("say what to ask: semantext model ask WORDS")
    got = model.ask(store, words, by="console")
    inbox = Inbox(store.root)
    for rid in got["filed"]:
        r = inbox.get(rid)
        _out(f"[#{rid}] {r['title']}: it waits in your inbox as a proposal, never a rule or an answer.")
    for p in got["problems"]:
        _out(f"  Problem: {p}")
    if not got["filed"]:
        _out("The model proposed nothing.")
    return 0


def cmd_helper(store: Store, args) -> int:
    from .helpers import FRESH, Helpers, helper_row
    keeper, who = Helpers(store.root), _as(store, args.source)
    a, w = args.action, args.words or []

    def word(i: int, what: str) -> str:
        if len(w) <= i:
            raise Refused(f"say {what}")
        return w[i]

    def number(i: int) -> int:
        if not word(i, "the job's number").isdecimal():
            raise Refused("name the job by its number")
        return int(w[i])

    if a == "start":
        keeper.start(who, word(0, "the helper's name"), args.keeps or "", args.session or "")
        _out(f"Started keeping {w[0]}. Your tool starts the agent itself; log each hand-off with `semantext helper job {w[0]} --predict ...`.")
    elif a == "rename":
        keeper.rename(who, word(0, "the helper's name"), word(1, "the new name"))
        _out(f"{w[0]} is now {w[1]}.")
    elif a == "retire":
        keeper.retire(who, word(0, "the helper's name"), args.notes or "")
        _out(f"Retired {w[0]}. Its record and your note of where its notes are stay on file.")
    elif a == "job":
        j = keeper.job(who, w[0] if w else None, args.predict or "")
        _out(f"Job #{j['id']} to {w[0] if w else FRESH}. Close it with: semantext helper done {j['id']} --tokens N")
    elif a == "done":
        if args.tokens is None:
            raise Refused("say the job's tokens as a whole number (--tokens)")
        keeper.done(who, number(0), args.tokens, args.outcome or "")
        _out(f"Job #{w[0]} closed. Have it checked before you take it in: semantext attack ask CLAIM --job {w[0]}, then semantext helper take {w[0]} --attack N")
    elif a == "take":
        keeper.take(who, number(0), args.attack, args.unreviewed or "")
        _out(f"Job #{w[0]} taken in" + ("." if args.attack is not None else ", unchecked; that stays on the record."))
    else:
        rows = keeper.report(owner=None if args.all else who.key)
        for r in rows:
            _out(helper_row(r, session=not args.all or r["key"] == who.key))   # another agent's session is its own
        if not rows:
            _out("No helpers are kept." if args.all else "You keep no helpers. Most jobs are for a fresh agent.")
        if keeper.damaged:
            _out(f"{keeper.damaged} damaged line(s) in the helpers file were not read.")
    return 0


def cmd_decisions(store: Store, args) -> int:
    found = Inbox(store.root).search(" ".join(args.words or []), limit=args.limit)
    if not found:
        _out("Nothing on record matches." if args.words else "Nothing has been decided yet.")
        return 0
    for r in found:
        _out(register_line(r))
    return 0


def cmd_inbox(store: Store, args) -> int:
    inbox = Inbox(store.root)
    items = sorted(inbox.requests().values(), key=lambda r: r["id"])
    shown = items if args.all else [r for r in items if r["status"] == "open"]
    if not shown:
        _out("Nothing is waiting for you." if not args.all else "The inbox is empty.")
        return 0
    for r in shown:
        _show_request(r)
        _out("")
    if not args.all:
        parked = sum(bool(r.get("parked")) for r in shown)
        if not parked < len(shown):
            _out("Nothing is waiting for you now; the requests above are the ones you parked.")
        elif parked:
            _out(f"{parked} of these {'is' if parked == 1 else 'are'} parked: set aside by you, still open for their asker.")
        _out("Answer with: semantext answer ID CHOICE [your words]")
    return 0


def cmd_answer(store: Store, args) -> int:
    why_not = human_terminal()
    if why_not:
        raise Refused(f"cannot answer here: {why_not}. Answer from your own terminal, or from the page")
    inbox = Inbox(store.root)
    store.check_adoptable(inbox.get(args.id), args.choice)
    r = inbox.answer(args.id, args.choice, " ".join(args.words or []), via="terminal")
    rid = store.adopt(r)
    _out(f"Answered {describe_answer(r)}. Your AI sees it with its next prompt.")
    if rid:
        _out(f"Added {rid} to {store.title(r['env'])}: it is on the card from the next prompt.")
    return 0


def cmd_answers(store: Store, args) -> int:
    # Only this asker's answers, and only those are marked read: another agent's answer must still reach it.
    inbox = Inbox(store.root)
    who = _as(store, args.source)
    unread = inbox.unread_answers(who)
    if not unread:
        _out("No new answers." + still_open(inbox, who))
        return 0
    for r in unread:
        _out(describe_answer(r))
    inbox.mark_read([r["id"] for r in unread], by=who.name)
    _out("Marked as read.")
    return 0


def cmd_close(store: Store, args) -> int:
    # The asker withdraws its own request; the user, at their own terminal, may withdraw any.
    inbox = Inbox(store.root)
    r = inbox.get(args.id)
    who = _as(store, args.source)
    # A tool's own marker or a claimed name makes this shell an agent's. A bound folder alone does not: the user works
    # in those folders too, and withdraws from a console.
    if who.tool or who.how == "claimed":
        if not mine(r, who):
            raise Refused(f"#{r['id']} was asked by {r['from']}, not by this agent; only its asker, or the user at "
                          f"their own terminal, can withdraw it")
        by = who.name
    else:
        why_not = human_terminal()
        if why_not:
            raise Refused(f"cannot withdraw it here: {why_not}. Only its asker, or the user at their own terminal, can "
                          f"withdraw it")
        by = "the user"
    r = inbox.close(args.id, " ".join(args.how or []), by=by)
    _out(f"Withdrew #{r['id']} {r['title']}.")
    return 0


def cmd_agents(store: Store, args) -> int:
    rows, me = Agents(store.root).overview(), _who(store)
    if not rows:
        _out("No agents yet. An agent appears here once it uses Semantext: its hook, or `semantext ask`.")
    for a in rows:
        label = f"  ({a['label']})" if a["label"] else ""
        _out(f"{'*' if a['name'] == me.name else ' '} {a['name']}{label}")
        for f in a["folders"]:
            _out(f"    bound to {f}")
        for s in a["sessions"][:3]:
            _out(f"    session {s['id'][:8]}: {s.get('prompts') or 0} prompts, last {since(s.get('last') or '')}")
        if len(a["sessions"]) > 3:
            _out(f"    and {len(a['sessions']) - 3} older sessions")
    _out(f"This shell is {me.name} ({me.how}).")
    return 0


def cmd_agent(store: Store, args) -> int:
    agents = Agents(store.root)
    if args.action == "whoami":
        who = agents.identify()
        _out(f"{who.name}  (found by: {who.how}; tool: {who.tool or 'none seen'}; project: {who.project or 'none'})")
        return 0
    # Which rules an agent gets is the user's to set, like answering: never from an agent's own shell.
    why_not = human_terminal()
    if why_not:
        raise Refused(f"cannot change agents here: {why_not}")
    if args.action == "bind":
        if not args.name:
            raise Refused("name the agent, for example: semantext agent bind reviewer --folder C:\\work\\api")
        path = agents.bind(args.name, args.folder or os.getcwd())
        _out(f"Every agent working in {path} is now {agents.bound(path)}.")
    elif args.action == "unbind":
        folder = args.folder or os.getcwd()
        _out("Unbound." if agents.unbind(folder) else f"No binding for {folder}.")
    elif args.action == "name":
        agents.rename(args.name or "", " ".join(args.label or []))
        _out("Named." if args.label else "Name removed.")
    return 0


def cmd_plugins(store: Store, args) -> int:
    # Imported here, not at the top: `semantext hook` runs through this module, and the hook loads no plug-in, nor the
    # registry (the ecosystem review, section 1; tests/test_registry.py pins the hook's imports).
    from . import plugincmd
    return plugincmd.run(store.root, args.action, args.name, _out, reviewed_full=args.reviewed_full, full=args.full)


def cmd_doctor(store: Store, args) -> int:
    s = store.state()
    name = s["active"]
    problems = 0
    broken = []   # each file that cannot be read is named, and the checks go on
    for n in store.names():
        try:
            store.load(n)
        except (Refused, OSError) as e:
            broken.append(str(e))
    card = store.served_card(name)
    size = len(card.encode("utf-8"))
    settings = Path(args.settings).expanduser() if getattr(args, "settings", None) else claude.default_settings()
    try:
        connected = claude.is_installed(jsonread.loads(settings.read_text(encoding="utf-8-sig"))) if settings.exists() else False
        claude_row = f"connected ({settings})" if connected else "not connected (semantext install claude-code)"
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, AttributeError) as e:
        claude_row, problems = f"PROBLEM: cannot read {settings} ({type(e).__name__})", problems + 1
    inbox = Inbox(store.root)
    rows = [
        ("Semantext", __version__),
        ("PyYAML", yaml.__version__),
        ("home", str(store.root)),
        ("environments", ", ".join(n for n in store.names() if n != "base")),
        ("active", f"{_title_or_name(store, name)} ({name})"),
        ("card", f"{card.count(chr(10) + '- ')} rules, {size} bytes "
                 f"({'fits' if size <= LIMIT_BYTES else 'over'} the {LIMIT_BYTES}-byte hook limit)"),
        ("on PATH", "yes" if shutil.which("semantext") else "no (the hook can use python -m semantext)"),
        ("Claude Code", claude_row),
    ]
    for f in s.get("agent_files", []):
        ok = agentfiles.has_block(Path(f))
        problems += not ok
        rows.append(("agent file", f"{'connected' if ok else 'PROBLEM: block missing or broken'} ({f})"))
    parked = len(inbox.parked_requests())
    rows += [("inbox", f"{len(inbox.waiting_requests())} waiting for you"
                       + (f", {parked} parked (set aside by you)" if parked else "")
                       + f", {len(inbox.unread_answers())} answers unread"),
             ("hear-prompts", "on" if s.get("hear_prompts") else "off"),
             ("feed", f"{'on' if s.get('feed', True) else 'off'} ({len(Feed(store.root).recent(200))} deliveries kept; "
                      f"what was sent, never what was said)")]
    found = ([f"PROBLEM: {b}" for b in broken]
             + [f"PROBLEM: {store.profiles_dir / x} is not an environment Semantext can use: it is left alone "
                f"(rename it with lowercase letters, digits and hyphens, or move it out)" for x in store.strays()]
             + ([f"PROBLEM: {store.state_problem}"] if store.state_problem else []))
    rows += [("file", f) for f in found]
    problems += len(found)
    for k, v in rows:
        _out(f"{k:<13} {v}")
    return 1 if problems else 0


def _title_or_name(store: Store, name: str) -> str:
    try:
        return store.title(name)
    except (Refused, OSError):
        return name


def _gaming_switch(args, cfg: dict, trouble) -> int:
    """`semantext compute hold` and `release`: the built-in I'm gaming switch, a flag in your home. A flag the settings
    place anywhere else belongs to whatever writes it there, so it is refused and never written."""
    import json
    import math
    from datetime import datetime, timedelta
    from .sources import gaming
    from .store import paths as _paths, write_atomic
    home = Path(cfg.get("_home") or _paths.home())
    flag = gaming.path_of(cfg)
    if trouble or flag is None or Path(flag) != home / gaming.FILE:
        where = f"your settings place the flag at {flag}, which another program owns" if flag else "your settings cannot be read"
        raise Refused(f"{where}, so this switch changes nothing: use that program's own button")
    if not home.is_dir():   # a mistyped --home makes nothing and is told so: `semantext init` makes a home
        raise Refused(f"there is no Semantext home at {home}: `semantext init` makes one")
    if args.action == "release":
        if flag.exists():
            write_atomic(flag, json.dumps({"on": False}))
        _out("released: the gaming hold is off")
        return 0
    try:
        hours = float(args.hours)
    except ValueError:
        raise Refused(f"--hours is a number of hours, not {_shown(args.hours)}") from None
    if not math.isfinite(hours) or not 1 / 60 <= hours <= gaming.LAPSE_S / 3600:
        raise Refused(f"--hours is at least a minute (0.02) and at most {gaming.LAPSE_S // 3600}, since a hold always "
                      f"lapses by itself")
    start = datetime.now().astimezone()
    end = start + timedelta(hours=hours)
    write_atomic(flag, json.dumps({"on": True, "since": start.isoformat(timespec="seconds"),
                                   "until": end.isoformat(timespec="seconds"), "until_epoch": end.timestamp()}))
    _out(f"holding heavy work until {end:%H:%M}: `semantext compute release` lifts it sooner")
    return 0


def cmd_compute(args) -> int:
    """The compute monitor for a job about to start. Only exit 0 means go; a sources file that cannot be read is
    "could not tell", since the button's flag is named there. With hold or release, the built-in gaming switch."""
    from .sources import compute, view
    cfg, _path, trouble = view._config(Path(args.home).expanduser() if args.home else None)
    if args.action != "ask":
        return _gaming_switch(args, cfg, trouble)
    got = compute.ask(cfg)
    code = compute.EXIT[got["verdict"]]
    if trouble and code == 0:
        got, code = {**got, "verdict": compute.UNKNOWN, "reasons": [str(trouble)[:300]]}, compute.EXIT[compute.UNKNOWN]
    _out(got["verdict"] + (": " + "; ".join(got["reasons"]) if got["reasons"] else ""))
    if got["not_read"]:
        _out("not read: " + ", ".join(got["not_read"]))
    told = [x for x in got.get("could_not_tell") or [] if x not in got["reasons"]]
    if told:
        _out("could not tell: " + "; ".join(told))
    return code


class _Parser(argparse.ArgumentParser):
    """argparse, except that it never repeats a key-shaped value, and that it reads a command line the same way on every
    Python the package supports. Its own errors quote what was typed ("invalid choice: 'sk-...'", "unrecognized
    arguments: ..."), and a key typed in the wrong place would reach the screen, a log, or an agent's transcript.
    Sub-commands are made with the same class.

    The same on every Python: argparse before 3.12.7 gives a word to nobody when it follows an option and an earlier
    word of the command was already taken, so `semantext env add --env work an-id` left `an-id` unread there
    ("unrecognized arguments") while newer Pythons read it. A sub-command that is left with unread words therefore
    reads its own part of the line once more with options and words intermixed (parse_known_intermixed_args, in every
    supported Python); that reading stands only if it reads every word, and otherwise the first one does, with its
    refusal. So a line that newer Pythons read is read the same by the older ones. It also reads, on every Python, one
    kind of line that every Python refused before: words of ONE many-word argument split by an option
    (`semantext backtest a.jsonl --env work b.jsonl` now reads both files; before, the second was "unrecognized").
    A line with more words than the command takes is refused as before, in the same words. Limit: only sub-commands
    do this (the top parser's own options are --home and --version)."""

    _again = False      # true while this parser is reading its line the second way, so the second way is not re-entered

    def parse_known_args(self, args=None, namespace=None):
        if self._again or namespace is not None or any(isinstance(a, argparse._SubParsersAction) for a in self._actions):
            return super().parse_known_args(args, namespace)
        line = list(sys.argv[1:] if args is None else args)
        got, left = super().parse_known_args(list(line), None)
        if not left:
            return got, left
        self._again = True
        try:
            again, still = self.parse_known_intermixed_args(list(line), None)
        except TypeError:           # a parser the intermixed reading does not take: the first reading stands
            return got, left
        finally:
            self._again = False
        return (again, still) if not still else (got, left)

    def error(self, message):
        if key_shaped(message):
            message = "an argument looks like it holds a key, a token or a password, so it is not repeated here"
        super().error(message)

    def _print_message(self, message, file=None):
        # Python 3.10's argparse writes its usage and its error to sys.stderr without asking whether there is one, so
        # with no console streams (pythonw) a refused line raised AttributeError there instead of exiting 2. Where
        # there is no stream there is nowhere to say it, and the exit code still does. Found by the first run on a
        # real Python 3.10 (15 November 2026); newer Pythons already check.
        if (file if file is not None else sys.stderr) is None:
            return
        super()._print_message(message, file)


def _act_word(value: str) -> str:
    """One act the reader knows. Any other word is refused WITHOUT being repeated: it may be a key typed in the wrong
    place, and argparse's own "invalid choice" message would print it."""
    if value in reading.ACTS:
        return value
    raise argparse.ArgumentTypeError("that is not an act the reader knows (the word is not repeated). The acts are: "
                                     + ", ".join(reading.ACTS))


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(
        prog="semantext",
        description="Keep your standing rules for how an AI assistant reads you, and hand them to it with every "
                    "prompt.")
    p.add_argument("--version", action="version", version=f"semantext {__version__}")
    p.add_argument("--home", help="the folder holding your rules (default: ~/.semantext, or $SEMANTEXT_HOME)")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, fn, help_text, env=False, aliases=()):
        sp = sub.add_parser(name, aliases=list(aliases), help=help_text, description=help_text)
        sp.set_defaults(fn=fn)
        if env:
            sp.add_argument("--env", help="the environment (default: the active one)")
        return sp

    add("init", cmd_init, "create your home with the starting environments")
    sp = add("compute", cmd_compute, "say whether this machine is free for heavy work (exit 0 free, 2 could not tell, "
                                     "3 hold or light work only); hold and release are your I'm gaming switch")
    sp.add_argument("action", nargs="?", choices=("ask", "hold", "release"), default="ask")
    sp.add_argument("--hours", default="6", help="how long a hold lasts, at most 6 (default 6)")
    sp = add("card", cmd_card, "print the card your AI receives", env=True)
    sp.add_argument("--agent", help="the card that agent receives, with its own rules (as `semantext agents` names it)")
    sp = add("env", cmd_env, "list, switch or make environments (profiles); add suggested rules (`ideas` lists the "
                             "packs)", aliases=("profile",))
    sp.add_argument("action", nargs="?", choices=("list", "use", "new", "add", "ideas"), default="list")
    sp.add_argument("name_or_title", nargs="*", metavar="ARG",
                    help="use NAME or TITLE, new TITLE..., or add ID [ID ...]")
    sp.add_argument("--env", help="for add: the environment, by name or title (default: the active one)")
    sp.add_argument("--none", action="store_true", help="for new: start without suggested rules")
    sp.add_argument("--pick", nargs="+", metavar="ID", help="for new: start with these suggestions, from any pack")
    sp = add("rules", cmd_rules, "list an environment's rules", env=True)
    sp.add_argument("--all", action="store_true", help="include undone (archived) rules")
    sp.add_argument("--base", action="store_true", help="show the shared base rules too")
    sp.add_argument("--agent", help="that agent's own rules in the environment, instead of the shared ones")
    sp = add("teach", cmd_teach, "keep a correction as a rule, with your exact words (from an agent's shell: propose "
                                 "it, for the user to add)", env=True)
    sp.add_argument("words", nargs="+", help="your correction, in your own words")
    sp.add_argument("--why", help="for an agent: why it proposes the rule, shown to the user")
    sp.add_argument("--agent", help="a rule for that agent only, in its own layer of the environment")
    sp.add_argument("--misread", metavar="MESSAGE", help="the message your AI got wrong, kept as the rule's test")
    sp = add("cases", cmd_cases, "your corrections kept as tests, and whether each is still covered by a rule that is on",
             env=True)
    sp.add_argument("--export", metavar="FILE", help="write them as a JSONL of cases for `semantext backtest --cases`")
    rule_help = "the rule's id, as `semantext rules` shows it"
    sp = add("toggle", cmd_toggle, "switch a rule on or off", env=True)
    sp.add_argument("rule_id", help=rule_help)
    sp = add("pin", cmd_pin, "switch a rule between stationary and adaptive", env=True)
    sp.add_argument("rule_id", help=rule_help)
    sp = add("undo", cmd_undo, "undo a rule (kept in the file, off the card), or the last change", env=True)
    sp.add_argument("rule_id", nargs="?", help=rule_help)
    sp.add_argument("--last", action="store_true", help="undo the last change to the environment")
    sp = add("proxy", cmd_proxy, "the proxy between your AI tool and its model: start it, list what it holds for your "
                                 "word, answer it", env=True)
    sp.add_argument("action", choices=("serve", "asks", "answer"))
    sp.add_argument("rest", nargs="*", metavar="ARG", help="for answer: the ask id, then yes, no or revoke")
    sp.add_argument("--space", help="for serve: the folder of the space's blocks")
    sp.add_argument("--port", type=int, default=None, help="for serve: the port on 127.0.0.1 (default 8790)")
    sp.add_argument("--proxy-home", help="the folder the proxy keeps its asks and record in (default: proxy in "
                                         "your home)")
    sp = add("read", cmd_read, "show how a message is read (nothing is saved)", env=True)
    sp.add_argument("message", nargs="+", help="the message to read")
    sp.add_argument("--act", action="append", type=_act_word, metavar="{" + ",".join(reading.ACTS) + "}",
                    help="say what the words advise for this act (repeatable; default: every act the words name)")
    sp.add_argument("--offer", help="the agent's last offer, which a bare yes binds to")
    add("where", cmd_where, "print the path of an environment's rule file", env=True)
    sp = add("hear", cmd_hear, "keep a message you sent, on this machine", env=True)
    sp.add_argument("text", nargs="+", help="the message to keep")
    sp = add("recall", cmd_recall, "show what was heard, newest first", env=True)
    sp.add_argument("query", nargs="*", help="words to look for (an item must hold them all)")
    sp.add_argument("-n", type=int, default=20, help="how many (default 20)")
    sp = add("forget", cmd_forget, "forget heard items", env=True)
    sp.add_argument("ids", nargs="*", type=int, help="the numbers `semantext recall` shows")
    sp.add_argument("--all", action="store_true", help="forget everything heard in the environment")
    sp = add("propose", cmd_propose, "propose rules from what was heard; accept the ones you want", env=True)
    sp.add_argument("--accept", nargs="+", type=int, metavar="N", help="the numbers of the proposals to accept")
    sp = add("mine", cmd_mine, "keep your own past messages from your AI tool's transcripts as heard (on this machine; "
                               "rules come only from `propose`)", env=True)
    sp.add_argument("files", nargs="*", metavar="FILE", help="Claude Code transcripts (.jsonl); default: the project's")
    sp.add_argument("--project", help="the project folder whose transcripts to read (default: this folder)")
    sp.add_argument("--dry-run", action="store_true", help="count only: keep nothing")
    sp.add_argument("--json", action="store_true", help="the counts as JSON")
    sp = add("backtest", cmd_backtest, "score the card against the misreadings in your transcripts (on this machine; "
                                       "nothing is written)", env=True)
    sp.add_argument("files", nargs="*", metavar="FILE", help="Claude Code transcripts (.jsonl); default: the project's")
    sp.add_argument("--project", help="the project folder whose transcripts to read (default: this folder)")
    sp.add_argument("--split", metavar="YYYY-MM-DD",
                    help="leave off rules learned on or after this date, and score only messages from it on")
    sp.add_argument("--cases", metavar="FILE", help="a JSONL of curated cases (see docs/backtest.md)")
    sp.add_argument("--finder", metavar="FILE",
                    help='a JSONL of {"text": ..., "correction": true|false}: how well corrections are found')
    sp.add_argument("--show", action="store_true", help="list the misread messages the card is silent on")
    sp.add_argument("--json", action="store_true", help="the report as JSON")
    sp.add_argument("--reader", metavar="SPEC",
                    help="score a model's reading instead: ollama:MODEL (on this machine) or endpoint:URL#MODEL "
                         "(an OpenAI-compatible endpoint; off this machine unless the URL is local)")
    sp.add_argument("--judge", action="append", metavar="SPEC", default=[],
                    help="with --reader: a judge of the readings, given twice, each of another model lineage than the "
                         "reader")
    sp.add_argument("--key-env", metavar="NAME", help="the environment variable holding an endpoint's key "
                                                       "(the key itself is never stored)")
    sp.add_argument("--samples", type=int, default=1, help="with --reader: readings per case, for their agreement")
    sp.add_argument("--ablate", action="store_true", help="with --reader and --cases: drop each needed rule in turn")
    sp.add_argument("--clean-sample", type=int, metavar="N",
                    help="with --reader on transcripts: read every misread message and a fixed sample of N clean ones")
    sp.add_argument("--weighed", action="store_true",
                    help="score a weighed touch instead: each cue weighed by its evidence on your earlier messages, "
                         "with the threshold set so that at most --alpha of your ordinary messages are touched")
    sp.add_argument("--alpha", type=float, default=0.10,
                    help="with --weighed: the share of ordinary messages that may be touched (default 0.10)")
    sp = add("config", cmd_config, "show or change a setting")
    sp.add_argument("key", choices=("hear-prompts",),
                    help="hear-prompts: keep each prompt you send in your heard log, on this machine (off by default)")
    sp.add_argument("value", nargs="?", choices=("on", "off"))
    sp = add("feed", cmd_feed, "what each prompt was sent, newest first (never what was said); on or off")
    sp.add_argument("state", nargs="?", choices=("on", "off"), help="switch the feed on or off (on by default)")
    sp.add_argument("-n", type=int, default=20, help="how many to show (default 20)")
    sp = add("serve", cmd_serve, "open the page on this machine (http://127.0.0.1:8765)")
    sp.add_argument("--host", default="127.0.0.1", help="127.0.0.1 or localhost; any other host is refused")
    sp.add_argument("--port", type=int, default=8765, help="the port (default 8765)")
    sp.add_argument("--open", action="store_true", help="open it in your browser")
    add("hook", None, "the Claude Code hook: reads the prompt event on stdin and prints the card (Claude Code runs it "
                      "for you)")
    add("mcp", cmd_mcp, "Semantext for any AI tool that speaks MCP: the card and the inbox, over stdin and stdout (the "
                        "tool runs it for you)")
    sp = add("statusline", None, "one line for Claude Code's status bar: what waits for your word, from your sources "
                                 "(it writes nothing, and on any trouble prints \"Semantext: unavailable\")")
    sp.add_argument("--width", default="80", help="the most characters the line may take (default 80)")
    tools = ("claude-code", "codex", "freebuff", "agents-md")
    for verb, fn, text in (("install", cmd_install, "connect an AI tool (prints the change; --apply makes it)"),
                           ("uninstall", cmd_uninstall, "disconnect an AI tool (--apply makes the change)")):
        sp = add(verb, fn, text)
        sp.add_argument("tool", choices=tools,
                        help="claude-code: a hook in its settings; codex: a block in ~/.codex/AGENTS.md; freebuff: a "
                             "block in the project's knowledge.md; agents-md: a block in the file you name")
        sp.add_argument("--apply", action="store_true", help="make the change (a backup is saved first)")
        sp.add_argument("--settings", help="claude-code: the settings file (default: ~/.claude/settings.json)")
        sp.add_argument("--file", help="codex, freebuff, agents-md: the instructions file (needed for agents-md)")
        if verb == "install":
            # dest must not be "command": that name holds the sub-command itself, and a default of None would hide it.
            sp.add_argument("--command", dest="hook_command",
                            help="claude-code: the command the hook runs (default: chosen for this machine)")
    add("sync", cmd_sync, "refresh the card's copy in every connected instructions file")
    sp = add("export", cmd_export, "print the card for a local model: as a system prompt, or an Ollama Modelfile",
             env=True)
    sp.add_argument("kind", choices=("system-prompt", "modelfile"))
    sp.add_argument("--base", help="modelfile: the model to build on, for example llama3.2")
    sp = add("feature", cmd_feature, "switch a feature rule on or off (inbox, tone, jokes, news)", env=True)
    sp.add_argument("name", choices=tuple(FEATURES))
    sp.add_argument("state", choices=("on", "off"))
    sp.add_argument("--country", help="news: the country to focus on")
    # The inbox: an agent asks, withdraws and reads answers; only the user answers.
    sp = add("ask", cmd_ask, "file a request in the user's inbox (for an AI: a decision, or a command for them to run)")
    sp.add_argument("--title", required=True, help="a short title")
    sp.add_argument("--why", required=True, help="why it needs the user")
    sp.add_argument("--question", help="a decision: the question")
    sp.add_argument("--option", action="append", help="a decision: an option (repeat it, up to 9)")
    sp.add_argument("--recommend", type=int, help="a decision: the number of the option you recommend")
    sp.add_argument("--command", dest="run", help="a command for the user to run themselves (never run for them)")
    sp.add_argument("--does", help="a command: what it does")
    sp.add_argument("--undo", help="a command: how to undo it, or 'cannot be undone'")
    sp.add_argument("--cwd", help="a command: the folder to run it in")
    sp.add_argument("--from", dest="source", help="who is asking, as stated (default: $SEMANTEXT_AGENT, or 'ai')")
    sp = add("inbox", cmd_inbox, "show the requests waiting for your answer")
    sp.add_argument("--all", action="store_true", help="include answered and withdrawn requests")
    sp = add("answer", cmd_answer, "answer a request (you, from your own terminal; never an agent)")
    sp.add_argument("id", type=int, help="the request's number, as `semantext inbox` shows it")
    sp.add_argument("choice", help="an option's number; for a command, done or wont (an apostrophe needs quotes in "
                                   "a shell); for a proposed rule, add or no")
    sp.add_argument("words", nargs="*", help="your answer in your own words, kept exactly")
    sp = add("decisions", cmd_decisions, "what the user has decided: every answered request, newest first (for an AI: "
                                         "look here before you ask)")
    sp.add_argument("words", nargs="*", help="only those holding all these words")
    sp.add_argument("--limit", type=int, default=20, help="at most this many (default 20)")
    sp = add("answers", cmd_answers, "for an AI: read the user's new answers to you, and mark them read")
    sp.add_argument("--from", dest="source", help="the asker whose answers these are (default: $SEMANTEXT_AGENT, or "
                                                  "'ai')")
    sp = add("close", cmd_close, "withdraw a request that is no longer needed (its asker, or you from your own "
                                 "terminal; it never answers)")
    sp.add_argument("id", type=int, help="the request's number")
    sp.add_argument("--how", nargs="+", help="why it is withdrawn, for example: superseded by #14")
    sp.add_argument("--from", dest="source", help="who is withdrawing it: the asker, as stated (default: "
                                                  "$SEMANTEXT_AGENT, or you at your own terminal)")
    sp = add("start", cmd_start, "what this agent should know when it starts or comes back; marks nothing as read "
                                 "(exit 3 if a part could not be read)")
    sp.add_argument("--since", help="list what was addressed to you since this time, instead of since your last post")
    sp.add_argument("--hook", action="store_true", help="the form a session-start hook runs: reads its event, never blocks, makes no home")
    sp.add_argument("--from", dest="source", help="who you are, as stated: a claim (default: worked out from this shell)")
    sp = add("board", cmd_board, "where your agents leave word for each other, and say what they are working on; "
                                 "information, never the user's word")
    sp.add_argument("action", choices=("post", "read", "claim", "release", "claims"))
    sp.add_argument("words", nargs="*", help="claim, release: the path")
    sp.add_argument("--title", help="post: a short title")
    sp.add_argument("--body", help="post: what you have to say")
    sp.add_argument("--to", nargs="+", help="post: who it is for, by name (default: everyone)")
    sp.add_argument("--note", help="claim: what you are doing there")
    sp.add_argument("--all", action="store_true", help="read: every post, not only those to you")
    sp.add_argument("--limit", type=int, default=30, help="read: at most this many, newest first (default 30)")
    sp.add_argument("--from", dest="source", help="who you are, as stated: a claim (default: worked out from this shell)")
    sp = add("attack", cmd_attack, "attack before trust: put a claim up, hand it to an agent that did not build it, and "
                                   "keep the verdict")
    sp.add_argument("action", choices=("ask", "list", "brief", "verdict"))
    sp.add_argument("words", nargs="*", help="ask: the claim; brief: its number; verdict: its number, then killed, survived or inconclusive")
    sp.add_argument("--ref", help="ask: where it can be tested, such as a commit")
    sp.add_argument("--job", type=int, help="ask: the helper job this claim checks")
    sp.add_argument("--how", help="verdict: what you did and what you saw")
    sp.add_argument("--not-tried", dest="not_tried", help="verdict: what you did not try (survived must say)")
    sp.add_argument("--from", dest="source", help="who you are, as stated: a claim (default: worked out from this shell)")
    sp = add("helper", cmd_helper, "long-lived helpers an agent keeps for itself: start, job, done, take, rename, retire, list; "
                                   "only where kept context is reused, otherwise use a fresh agent")
    sp.add_argument("action", choices=("start", "job", "done", "take", "rename", "retire", "list"))
    sp.add_argument("words", nargs="*", help="the helper's name (rename: and the new name); done, take: the job's number; job with no name: a fresh agent")
    sp.add_argument("--keeps", help="start: what kept context earns it its place")
    sp.add_argument("--session", help="start: the session your tool resumes it from")
    sp.add_argument("--predict", help="job: your prediction, written before the job")
    sp.add_argument("--tokens", type=int, help="done: the tokens the job took")
    sp.add_argument("--outcome", help="done: how it went")
    sp.add_argument("--attack", type=int, help="take: the claim that survived a fresh reviewer's attack")
    sp.add_argument("--unreviewed", help="take: why it was not checked; this stays on the record")
    sp.add_argument("--notes", help="retire: where its notes are kept")
    sp.add_argument("--all", action="store_true", help="list: every agent's helpers")
    sp.add_argument("--from", dest="source", help="who you are, as stated: a claim (default: worked out from this shell)")
    sp = add("record", cmd_record, "topics: the model you chose gives a topic to each decision no project groups, for "
                                   "the Record's threads (run only when you ask)")
    sp.add_argument("action", choices=("topics",))
    sp.add_argument("--reader", help="ollama:MODEL or endpoint:URL#MODEL[@KEY_VARIABLE] (default: the model chosen in Semantext)")
    sp.add_argument("--key-env", dest="key_env", help="the environment variable holding an endpoint's key")
    sp.add_argument("--again", action="store_true", help="ask again for every decision, not only the new or changed ones")
    sp.add_argument("--limit", type=int, help="at most this many decisions")
    sp = add("model", cmd_model, "a model on this machine: set its address, name and expected digest; ask it (you, "
                                 "at your own console); its answers wait in your inbox as proposals labelled MODEL")
    sp.add_argument("action", choices=("show", "set", "clear", "ask", "check"))
    sp.add_argument("words", nargs="*", help="ask: what to ask; the card goes with it")
    sp.add_argument("--address", help="set: http://127.0.0.1:PORT or http://[::1]:PORT, a runtime you started")
    sp.add_argument("--model", dest="model_name", help="set: the model's name, as the runtime names it")
    sp.add_argument("--digest", help="set: the model's ID as `ollama list` shows it (12 hex digits, or the full 64): "
                                     "its manifest's sha256, which every call compares with the runtime's report")
    sp.add_argument("--budget", type=float, help=f"set: seconds a call may take (default 60, at most 600)")
    sp.add_argument("--tokens", type=int, help="set: the token cap of one answer (default 512)")
    sp.add_argument("--on-mismatch", dest="on_mismatch", choices=("refuse", "flag"),
                    help="set: a digest that differs from yours is refused (default) or shown as a problem")
    sp.add_argument("--asks-per-hour", dest="asks_per_hour", type=int, help="set: your own cap (default 20)")
    sp.add_argument("--file", help="check: the model's weights file, hashed here and compared with the blob its "
                                   "manifest names")
    sp.add_argument("--manifest", help="check: the model's manifest (default: Ollama's, by the model's name), hashed "
                                       "here and compared with the model ID you named")
    add("agents", cmd_agents, "list the AI agents Semantext has seen or you have named, with their sessions")
    sp = add("agent", cmd_agent, "who this shell's agent is; bind a folder to an agent; give an agent a display name")
    sp.add_argument("action", choices=("whoami", "bind", "unbind", "name"))
    sp.add_argument("name", nargs="?", help="bind: the agent's name; name: the agent to label")
    sp.add_argument("label", nargs="*", help="name: the display name (none removes it)")
    sp.add_argument("--folder", help="bind, unbind: the folder (default: this one)")
    sp = add("plugins", cmd_plugins, "list plug-ins, where each came from and whether it is on; turn one on (you, at "
                                     "your own console, typing its name) or off; confirm, to apply a settings "
                                     "change the page proposed")
    sp.add_argument("action", nargs="?", choices=("list", "enable", "disable", "confirm", "show", "check"),
                    default="list", help="show: a proposal, or what enabling a plug-in would show, in full; check: the "
                                         "conformance kits (not built yet)")
    sp.add_argument("name", nargs="?", help="enable, disable: the plug-in, as <kind>.<name>; confirm: the proposal's "
                                            "number, as the page shows it; show: either")
    sp.add_argument("--full", action="store_true", help="show: everything, exactly, ending with its review code")
    sp.add_argument("--reviewed-full", metavar="CODE",
                    help="enable, confirm: the review code `show --full` printed, after you read it all there")
    sp = add("doctor", cmd_doctor, "check the setup (exits 1 if something is broken)")
    sp.add_argument("--settings", help="the Claude Code settings file to check (default: ~/.claude/settings.json)")
    from .work.cli import register as add_work   # here: the work package is only loaded by the command line
    add_work(add)
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the command. If a secret was typed on the command line (secret_values), everything written to stderr is cut
    of it line by line, and stdout is held and cut if the command fails, so no message, whatever its words and
    wherever it was made (the parser's own errors included), can say it back. Without one the streams are untouched.
    Limits, stated: output written below Python's streams (a child process, a buffer) is not seen; the stdout of a
    command a reader waits on (_streams) is left alone, only its stderr is cut; a value shorter than _SHORTEST_CUT is
    not cut; a message showing only part of a secret is not caught."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):   # nobody is reading; the command still runs
            pass
    typed = list(sys.argv[1:] if argv is None else argv)
    values = secret_values(typed)
    if not values:
        return _main(argv, typed)
    real_out, real_err = sys.stdout, sys.stderr
    # A stream that is None (pythonw) stays None: print() to it writes nothing, as before. Stdout is held from the start
    # and given back as it is once the parsed command turns out to be one a reader waits on (_main, _streams).
    err = None if real_err is None else _Cutting(real_err, values)
    out = None if real_out is None else _Cutting(real_out, values, hold=True)
    if err is not None:
        sys.stderr = err
    if out is not None:
        sys.stdout = out
    failed = True   # until the command returns: an exit by SystemExit or an exception counts by its own code
    try:
        code = _main(argv, typed)
        failed = bool(code)
        return code
    except SystemExit as e:
        failed = e.code not in (None, 0)
        raise
    finally:
        sys.stderr, sys.stdout = real_err, real_out
        if out is not None:
            out.finish(failed)
        if err is not None:
            err.finish(failed)


def _main(argv, typed) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if isinstance(sys.stdout, _Cutting) and _streams(args):   # decided by the parsed command, not by a typed word
        sys.stdout.release()
    if args.command == "hook":
        if args.home:
            os.environ["SEMANTEXT_HOME"] = args.home
        return hook_main()
    if args.command == "start" and args.hook:   # before the home is opened: a session start makes no home
        if args.home:
            os.environ["SEMANTEXT_HOME"] = args.home
        from .start import hook_main as start_hook
        code = start_hook()
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        os._exit(code)   # at once: its stdin reader may still be waiting, and nobody should wait for it
    if args.command == "statusline":   # before the home is opened: the status line writes nothing, not even a new home
        return cmd_statusline(args)
    if args.command == "compute":      # the same: a job asking whether it may start changes nothing
        try:
            return cmd_compute(args)
        except (Refused, OSError) as e:
            print("semantext: " + _unkeyed(str(e), typed), file=sys.stderr)
            return 1
    if not args.command:
        parser.print_help()
        return 0
    try:
        store = Store.open(Path(args.home).expanduser() if args.home else None)
        return args.fn(store, args)
    except (Refused, OSError, ValueError) as e:
        # A refusal, or a file that could not be read or written (a home that is a file, a damaged state.json):
        # one line, never a traceback.
        print("semantext: " + _unkeyed(_said(args, e, str(e)), typed), file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  the last resort: still one line, with what failed, never a traceback
        print("semantext: " + _unkeyed(_said(args, e, f"an unexpected {type(e).__name__}: {e}. `semantext doctor` checks "
                                                      f"the files; please report it if it persists"), typed),
              file=sys.stderr)
        return 1


def _said(args, e: BaseException, text: str) -> str:
    """An error's words as printed. For `semantext plugins`, through the one renderer of its console (plugincmd.shown),
    whatever raised it and wherever; a refusal plugincmd.run has rendered already (its text a Rendered) is printed as
    it is once checked, never rendered twice."""
    if getattr(args, "command", None) != "plugins":
        return text
    from . import plugincmd
    given = e.args[0] if len(e.args) == 1 else None
    return plugincmd.shown(given if given is not None and str(given) == text else text)
