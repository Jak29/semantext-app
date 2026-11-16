"""R5 (Orithises's fourth attack on actclass, v2-25): the reader is linear BY CONSTRUCTION, and a test finds the next
quadratic pattern before an attacker does.

Three rounds had each added a regex feature and each feature a super-linear shape (the printf format 156 s, the method
chain 11.6 s, the find/here-string product 5 s, the string literal 13.6 s at 64 KiB). Patching the shape found each time
did not end it, so this file does three things that do:

  1. GUARD. Every compiled pattern in actclass (found by walking the module; a pattern held in a dict or a tuple too) is
     searched on inputs made from its OWN literal fragments and character classes, each fragment of 1 to 4 characters
     repeated to 16 KiB and 64 KiB, with and without a tail that does not match. Each search must take under 0.2 s at
     64 KiB and grow about linearly (64 KiB under 6 times 16 KiB plus a small constant). A pattern built inside a
     function cannot be found that way, so none may exist (an AST check): add a pattern at module level.
  2. END TO END. The shapes every attacker has timed (round 2b's 62, round 3's, the four this round) go through
     decide.decide: each under 0.5 s at 64 KiB, and a 1 MiB command returns at once as every act.
  3. THE BOUND ITSELF. A command over MAX_COMMAND is every act and is not read; a command whose reading would pass the
     work budget is every act, never a part; every text handed to a reader is charged to that budget.

The guard is shown to catch the quadratic patterns of earlier rounds (test_the_guard_catches_...): re-introduce one of
them into actclass and test_every_pattern_is_linear fails."""
from __future__ import annotations

import ast
import base64
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import pytest

try:                                                  # Python 3.11 and after
    import re._constants as _k
    import re._parser as _sp
except ImportError:                                   # 3.10
    import sre_constants as _k
    import sre_parse as _sp
# the parse-tree nodes 3.11 added (possessive repeats, atomic groups): None on 3.10, where the parser makes neither, so
# the samplers below run there too (the E7 tests are not limited to 3.11)
_POSSESSIVE_REPEAT = getattr(_k, "POSSESSIVE_REPEAT", None)
_ATOMIC_GROUP = getattr(_k, "ATOMIC_GROUP", None)

from semantext import actclass, decide
from tests.test_decide import call, msg, space_of, text

K = 1024
ALL = actclass.ORDER
DATA = Path(__file__).parent / "data" / "actclass"
POSSESSIVE = actclass._POSSESSIVE_OK    # 3.11 or later AND an interpreter that matches possessive repeats rightly (L2.1)
needs_possessive = pytest.mark.skipif(not POSSESSIVE, reason="possessive quantifiers are Python 3.11's: the guarantee is from there")


# =================================================================================================================
# 1. the guard
# =================================================================================================================
def _patterns(mod=actclass) -> dict:
    found: dict = {}

    def add(name, v, depth=0):
        if isinstance(v, re.Pattern):
            found[name] = v
        elif isinstance(v, dict) and depth < 2:
            for key, x in v.items():
                add(f"{name}[{key!r}]", x, depth + 1)
        elif isinstance(v, (tuple, list, frozenset, set)) and depth < 2:
            for i, x in enumerate(sorted(v, key=repr) if isinstance(v, (set, frozenset)) else v):
                add(f"{name}[{i}]", x, depth + 1)

    for name, v in list(vars(mod).items()):
        add(name, v)
    return found


PATTERNS = _patterns()
_CATEGORY_SAMPLE = {_k.CATEGORY_DIGIT: "1", _k.CATEGORY_SPACE: " ", _k.CATEGORY_WORD: "a", _k.CATEGORY_NOT_DIGIT: "a",
                    _k.CATEGORY_NOT_SPACE: "a", _k.CATEGORY_NOT_WORD: "-"}


_LEAD_CAP = 16                                     # characters kept of a literal run with what stands before it
_LEAD_SETS = 64                                    # literal runs followed at once through the alternatives of a pattern


def lead_runs(pattern: re.Pattern) -> set:
    """Every literal run of the pattern WITH the literal text that can stand just before it, across groups and
    alternatives, its first _LEAD_CAP characters: `(?:\\.|::)(send|delete)` gives '.send', '::send', '.delete',
    '::delete'. E7 (round 5): the sampler cut runs to 4 characters and paired only 4 punctuation characters with them, so it
    built '.dele' but neither '.send' nor '.delete', and the old _METHOD (11.6 s at 64 KiB, one repeated fragment) was
    caught only by the explicit OLD list. Read from the parse tree: a literal extends every run that can end before it;
    any other node ends them (zero-width ones do not)."""
    out: set = set()

    def walk(seq, leads):
        for op, av in seq:
            if op is _k.LITERAL:
                leads = {s if len(s) >= _LEAD_CAP else s + chr(av) for s in leads}
            elif op is _k.BRANCH:
                new: set = set()
                for alt in av[1]:
                    new |= walk(alt, leads)
                leads = new
            elif op is _k.SUBPATTERN:
                leads = walk(av[3], leads)
            elif op in (_k.MAX_REPEAT, _k.MIN_REPEAT, _POSSESSIVE_REPEAT):
                body = walk(av[2], leads)
                leads = body | leads if av[0] == 0 else body
            elif op is _ATOMIC_GROUP:
                leads = walk(av, leads)
            elif op in (_k.AT, _k.ASSERT, _k.ASSERT_NOT, _k.GROUPREF):
                pass                                   # zero-width (or a reference): the run goes on after it
            else:
                out.update(s for s in leads if s)      # a class, a negated literal, any character: the run ends here
                leads = {""}
            if len(leads) > _LEAD_SETS:
                leads = set(sorted(leads)[:_LEAD_SETS])
        return leads

    out.update(s for s in walk(_sp.parse(pattern.pattern, pattern.flags), {""}) if s)
    return out


def fragments(pattern: re.Pattern) -> list:
    """The pieces an adversary would repeat against the pattern: its literals (1 to 4 characters, whole and cut), one
    sample of each character class, the two pad characters, and every literal run with what stands before it
    (lead_runs: '.send', '::delete'). Read from the pattern's parse tree, so it grows with it."""
    tree = _sp.parse(pattern.pattern, pattern.flags)
    chars, words, runs = set(), set(), set()

    def sample(items):
        for op, av in items:
            if op is _k.LITERAL:
                chars.add(chr(av))
            elif op is _k.RANGE:
                chars.add(chr(av[0]))
                chars.add(chr(av[1]))
            elif op is _k.CATEGORY:
                chars.add(_CATEGORY_SAMPLE.get(av, "a"))

    def walk(seq):
        run = ""
        for op, av in seq:
            if op is _k.LITERAL:
                run += chr(av)
                chars.add(chr(av))
                continue
            if run:
                words.update({run[:4], run[-4:]})
                runs.add(run[:12])
                run = ""
            if op is _k.NOT_LITERAL:
                chars.add("a" if chr(av) != "a" else "b")
            elif op is _k.IN:
                sample(av)
            elif op is _k.ANY:
                chars.add("x")
            elif op is _k.BRANCH:
                for alt in av[1]:
                    walk(alt)
            elif op is _k.SUBPATTERN:
                walk(av[3])
            elif op in (_k.MAX_REPEAT, _k.MIN_REPEAT, _POSSESSIVE_REPEAT):
                walk(av[2])
            elif op is _ATOMIC_GROUP:
                walk(av)
            elif op in (_k.ASSERT, _k.ASSERT_NOT):
                walk(av[1])
        if run:
            words.update({run[:4], run[-4:]})
            runs.add(run[:12])

    walk(tree)
    singles = sorted(chars | {" ", "a"})[:20]
    wordl = sorted(w for w in words if w)[:20]
    runl = sorted(r for r in runs if len(r) > 1)[:12]
    punct = [ch for ch in singles if not ch.isalnum() and ch not in "\n\r"][:4]
    # the 1 to 4 character fragments; whole literals (`explain`) and each followed by a space (words in a row); and a
    # punctuation fragment before a word (`.send`, which is how `.send.send.send` was found)
    pairs = [x + y for x in punct for y in wordl[:12]] + [r + " " for r in runl]
    # E7: every literal run with the punctuation that stands before it in the pattern, whole ('.send', '.delete')
    led = sorted(r for r in lead_runs(pattern) if not r[0].isalnum() and len(r) > 1)[:_LEAD_SETS]
    out = []
    for f in singles + wordl + runl + pairs + led:
        if f and f not in out:
            out.append(f)
    # a lead-in and then one fragment repeated (`%` then `0` x n, which is how printf's format was found: the run is not
    # something a pattern's own text repeats, it is what comes after its first character)
    out += [(lead, body) for lead in punct[:3] for body in (singles + wordl)[:12] if body != lead]
    return out


TAIL = "\x7f!~"                                    # a tail no pattern here accepts


def _inputs(unit, n: int):
    """The text of n characters made of a fragment repeated (or of a lead-in and a fragment repeated), bare and with the tail."""
    lead, rep = unit if isinstance(unit, tuple) else ("", unit)
    body = (lead + rep * ((n - len(lead)) // len(rep) + 1))[:n]
    return body, body + TAIL


def _best(fn, runs=2) -> float:
    best = 9e9
    for _ in range(runs):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def slow_input(pattern: re.Pattern, small=16 * K, big=64 * K, limit=0.2, ratio=6.0, extra=0.03):
    """The first (unit, tail?, t16, t64) at which the pattern is not linear, or None."""
    for unit in fragments(pattern):
        for k in (0, 1):
            s16, s64 = _inputs(unit, small)[k], _inputs(unit, big)[k]
            t16 = _best(lambda: pattern.search(s16), runs=1)
            if t16 > limit * 2:                      # already slow at 16 KiB: no need to wait minutes for the 64 KiB one
                return unit, bool(k), t16, None
            t64 = _best(lambda: pattern.search(s64), runs=1)
            if t64 > limit or t64 > ratio * t16 + extra:                  # slow once: measure again before saying so
                t16 = _best(lambda: pattern.search(s16), runs=3)
                t64 = _best(lambda: pattern.search(s64), runs=3)
                if t64 > limit or t64 > ratio * t16 + extra:
                    return unit, bool(k), t16, t64
    return None


def test_the_module_has_patterns_to_guard():
    assert len(PATTERNS) > 50, sorted(PATTERNS)


@pytest.mark.parametrize("name", sorted(PATTERNS))
@needs_possessive
def test_every_pattern_is_linear(name):
    """Searched on its own fragments repeated to 16 KiB and 64 KiB, with and without a non-matching tail: under 0.2 s at
    64 KiB, and 64 KiB under 6 times 16 KiB plus a small constant (4 times the text is 4 times the work, not 16)."""
    bad = slow_input(PATTERNS[name])
    assert bad is None, (name, PATTERNS[name].pattern[:90], bad)


def test_no_pattern_is_built_inside_a_function():
    """A pattern made inside a function cannot be found by the guard above. None exists; to add one put it at module level
    (the guard then finds it by itself) and keep to the four rules in the comment above _ORD_SH."""
    tree = ast.parse(Path(actclass.__file__).read_text(encoding="utf-8"))
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                        isinstance(node.func.value, ast.Name) and node.func.value.id == "re":
                    bad.append((node.func.attr, node.lineno))
    assert not bad, bad


# the quadratic patterns of earlier rounds, each with the input that found it: the guard must call every one slow
OLD = {
    "A12 _METHOD": (re.compile(r"(?:\.|::)(delete|send)[\x00\x01]*(?:\.\w+)*$"), lambda n: ".send" * (n // 5) + "!"),
    "A11 printf spec": (re.compile(r"%([-+ #0]*\d*(?:\.\d+)?[sbdiouxXeEfgGcq%])"), lambda n: "%" + "0" * n + "z"),
    "A21 _STR": (re.compile(r"""'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*\""""), lambda n: "'" + "\\'" * (n // 2)),
    "explain analyze": (re.compile(r"explain\s*(?:\([^)]*\banaly[sz]e\b|(?:\w+\s+)*analy[sz]e\b)"),
                        lambda n: "explain a " * (n // 10)),
    "ENV_ASSIGN search": (re.compile(r"\$?[A-Za-z_][A-Za-z0-9_]*="), lambda n: "a" * n),
}


def _greedy_copy(monkeypatch):
    """The module as Python 3.10 loads it (no possessive quantifiers: every one becomes the plain greedy repeat)."""
    monkeypatch.setattr(sys, "version_info", (3, 10, 14, "final", 0))
    spec = importlib.util.spec_from_file_location("semantext_actclass_greedy", actclass.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.undo()
    assert mod._POSSESSIVE_OK is False
    return mod


def test_l21_the_interpreter_is_asked_whether_possessive_repeats_match_rightly(monkeypatch):
    """CPython 3.11.0 to 3.11.4 have possessive repeats and match two shapes of them wrongly (CPython issues 100061 and
    106052, both fixed in 3.11.5; Debian 12 ships 3.11.2), and two patterns of the module have the first shape, where
    the fault would be a missed act. So the module uses possessive repeats only from 3.11 AND where both upstream
    reproductions come out right. Here: it says what this interpreter does; and a copy loaded where either reproduction
    comes out wrong is the greedy copy with the smaller backstop. (Not run on a real 3.11.0 to 3.11.4.)"""
    if sys.version_info < (3, 11):
        assert actclass._POSSESSIVE_OK is False              # no such syntax to get wrong
        return
    right = re.findall("(((?!C).)++)", "ABC") == [("AB", "B")] and re.fullmatch("(?:ab?c)*+", "a") is None
    assert actclass._POSSESSIVE_OK is right
    real_findall, real_fullmatch = re.findall, re.fullmatch
    faults = {
        "100061": ("findall", lambda p, s, *a, **k: [("ABC", "B")] if p == "(((?!C).)++)" else real_findall(p, s, *a, **k)),
        "106052": ("fullmatch", lambda p, s, *a, **k: real_fullmatch("a", "a") if p == "(?:ab?c)*+" else real_fullmatch(p, s, *a, **k)),
    }
    for issue, (name, fake) in faults.items():
        monkeypatch.setattr(re, name, fake)
        spec = importlib.util.spec_from_file_location("semantext_actclass_fault_" + issue, actclass.__file__)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        monkeypatch.undo()
        assert mod._POSSESSIVE_OK is False, issue
        assert mod.MAX_COMMAND == mod.MAX_COMMAND_310 and "*+" not in mod.PRINTF_SPEC.pattern, issue
        assert mod.acts_of_call("Bash", {"command": "git push origin main"}) == ("push",), issue
        assert mod.acts_of_call("Bash", {"command": "lftp -e 'mirror -vR ./site /www' host"}) \
            == actclass.acts_of_call("Bash", {"command": "lftp -e 'mirror -vR ./site /www' host"}), issue


def test_the_greedy_fallback_matches_what_the_possessive_patterns_match(monkeypatch):
    """pyproject says Python >= 3.10 and possessive quantifiers came with 3.11. So the module compiles its patterns through
    a shim that, below 3.11, drops the extra `+`. Nothing may change but the speed: the copy loaded that way answers every
    row of every corpus here as the real module does, except that a call longer than the 3.10 backstop (E9,
    MAX_COMMAND_310) is every act there, as any over-long call is (the guarantee of linear time is from 3.11)."""
    greedy = _greedy_copy(monkeypatch)
    assert greedy.PRINTF_SPEC.pattern == "%([-+ #0]*\\d*(?:\\.\\d+)?[sbdiouxXeEfgGcq%])"       # the shim dropped every extra +
    assert greedy.re.compile("a*+b").pattern == "a*b" and greedy.re.compile(r"\+\++b").pattern == r"\+\++b"   # an escaped + stays
    rows = []
    for name in ("round3_regress.json", "gate_a.json", "koinos.json"):
        for r in json.loads((DATA / name).read_text(encoding="utf-8")):
            tool = r.get("tool") or ("PowerShell" if r.get("shell") in ("ps", "cmd") else "Bash")
            rows.append((tool, {"command": r.get("cmd")}))
    fresh = json.loads((DATA / "round3_fresh.json").read_text(encoding="utf-8"))
    rows += [(r["tool"], r["inp"] if isinstance(r["inp"], dict) else {"command": r["inp"]}) for r in fresh["material"] + fresh["benign"]]
    rows += [(r["tool"], r["inp"] if isinstance(r["inp"], dict) else {"command": r["inp"]})
             for r in json.loads((DATA / "round2b_corpus.json").read_text(encoding="utf-8"))]
    assert len(rows) > 3500
    diff, over = [], 0
    for t, i in rows:
        cmd, got = greedy._command(i), greedy.acts_of_call(t, i)
        if cmd is not None and len(cmd) > greedy.MAX_COMMAND:
            over += 1                                    # E9: past the 3.10 backstop, every act, as any over-long call
            if got != ALL:
                diff.append(("over", t, i))
        elif got != actclass.acts_of_call(t, i):
            diff.append((t, i))
    assert diff == [], diff[:5]
    assert over < len(rows) // 50, over                  # the 3.10 backstop holds back few corpus calls


# the worst known shapes of the greedy copy (E9): printf's zeros, method chains, _blank on runs of \', find/here-strings
E9_WORST = ("printf_zeros", "printf_zeros_many", "method_chain_send", "method_chain_send_ps", "method_chain_delete",
            "method_chain_download_ps", "blank_bs_squote_python", "blank_bs_dquote_python", "find_many_herestr_sh",
            "find_many_herestr_psql", "find_many_herestr_sftp", "find_many_herestr_distinct", "find_many_heredoc_sh")


def test_e9_on_python_3_10_a_smaller_backstop_bounds_the_greedy_patterns(monkeypatch):
    """E9: the gate reader imports on 3.10 (docs/security-floor.md item 1), where its patterns are greedy and NOT linear
    by construction; its worst case is bounded by a smaller backstop instead (MAX_COMMAND_310). Read by the greedy copy
    at that size, EVERY shape this file times stays under the bound test_end_to_end_64k_is_under_half_a_second asserts
    (0.5 s; on 3.10 that test reads at most MAX_COMMAND_310, so it holds there too). From 3.11 the backstop is 64 KiB.
    The times of the worst known shapes are printed (pytest -s, or -rP)."""
    greedy = _greedy_copy(monkeypatch)
    assert actclass.MAX_COMMAND == (64 * K if POSSESSIVE else actclass.MAX_COMMAND_310)
    assert greedy.MAX_COMMAND == greedy.MAX_COMMAND_310 < 64 * K
    n = greedy.MAX_COMMAND
    slow, worst = [], []
    for name, (tool, gen) in sorted(SHAPES.items()):
        cmd = gen(n)[:n]
        t = _best(lambda: greedy.acts_of_call(tool, {"command": cmd}), runs=1)
        if t >= 0.2:                                     # slow once: measure again before saying so
            t = _best(lambda: greedy.acts_of_call(tool, {"command": cmd}), runs=3)
        if name in E9_WORST:
            worst.append(f"{name} {t:.3f}s")
        if t >= 0.5:
            slow.append((name, len(cmd), round(t, 3)))
    print(f"greedy copy at {n} characters: " + ", ".join(worst))
    assert slow == [], slow
    assert greedy.acts_of_call("Bash", {"command": "x" * (n + 1)}) == ALL          # one over: every act, not read
    assert greedy.acts_of_call("Bash", {"command": "git push; " + "x" * (n - 20)}) == ("push",)   # under it: read


def _nodes(seq):
    """Every node kind of a parse tree, groups, repeats, branches and look-arounds walked into."""
    for op, av in seq:
        yield op
        if op in (_k.MAX_REPEAT, _k.MIN_REPEAT, _POSSESSIVE_REPEAT):
            yield from _nodes(av[2])
        elif op is _k.BRANCH:
            for alt in av[1]:
                yield from _nodes(alt)
        elif op is _k.SUBPATTERN:
            yield from _nodes(av[3])
        elif op is _ATOMIC_GROUP:
            yield from _nodes(av)
        elif op in (_k.ASSERT, _k.ASSERT_NOT):
            yield from _nodes(av[1])
        elif op is _k.GROUPREF_EXISTS:
            yield from _nodes(av[1])
            if av[2]:
                yield from _nodes(av[2])


def test_e9_the_shim_leaves_no_pattern_that_3_10_cannot_parse(monkeypatch):
    """E9: every pattern is compiled through the shim, so on 3.10 none may keep a possessive repeat or an atomic group
    (3.10's parser has neither, and the import would fail there). Read from the greedy copy's own parse trees: the check
    tests/test_provenance_round3.py's scan of the package's literals cannot make for this module, whose literals are
    written possessive on purpose. Must-refuse: the same walk finds the possessive repeats the module keeps from 3.11."""
    greedy = _greedy_copy(monkeypatch)
    newer = {_POSSESSIVE_REPEAT, _ATOMIC_GROUP} - {None}
    pats = _patterns(greedy)
    assert len(pats) == len(PATTERNS)
    kept = {name: p.pattern[:60] for name, p in pats.items() if newer & set(_nodes(_sp.parse(p.pattern, p.flags)))}
    assert kept == {}, kept
    if POSSESSIVE:
        assert sum(_POSSESSIVE_REPEAT in set(_nodes(_sp.parse(p.pattern, p.flags))) for p in PATTERNS.values()) > 20


def test_e9_the_guard_holds_on_the_greedy_patterns_at_the_smaller_backstop(monkeypatch):
    """E9: the guard of section 1 on every pattern the shim CHANGES (the others are the very patterns the guard times
    above), as the greedy copy compiles it, searched on its own fragments at MAX_COMMAND_310, with and without the tail:
    each search under 0.5 s, the bound a whole command is held to end to end (the guard's 0.2 s is for a linear search
    at 64 KiB). There they are not linear, only bounded by the size: printf's format is quadratic and the slowest,
    measured at 18 ms at 1 KiB, 76 to 115 ms at 2 KiB and 289 ms at 4 KiB. (A pattern that backtracked without end would
    not finish here: the parse-tree test below fails first.) Printed (pytest -s, or -rP)."""
    greedy = _greedy_copy(monkeypatch)
    n = greedy.MAX_COMMAND_310
    pats = _patterns(greedy)
    assert set(pats) == set(PATTERNS)
    # from 3.11 the patterns the shim leaves alone are the very ones section 1 times; on 3.10 the module itself is the
    # greedy copy, so every pattern is timed here
    changed = {name: p for name, p in pats.items() if p.pattern != PATTERNS[name].pattern} if POSSESSIVE else pats
    assert len(changed) > 20 and "PRINTF_SPEC" in changed
    slow, worst = [], (0.0, "")
    for name, p in sorted(changed.items()):
        for unit in fragments(p):
            for s in _inputs(unit, n):
                t = _best(lambda: p.search(s), runs=1)
                if t > 0.5:                              # slow once: measure again before saying so
                    t = _best(lambda: p.search(s), runs=3)
                    if t > 0.5:
                        slow.append((name, repr(unit)[:20], round(t, 3)))
                worst = max(worst, (t, name))
    print(f"greedy patterns timed: {len(changed)}; the slowest search at {n} characters: {worst[1]} {worst[0]:.4f}s")
    assert slow == [], slow[:5]


def _nested_repeats(seq, inside=False):
    """Every unbounded repeat that stands inside another unbounded repeat: the shape that can backtrack without end once
    the shim drops a possessive `+` (`(?:\\w+\\s*)*`)."""
    for op, av in seq:
        if op in (_k.MAX_REPEAT, _k.MIN_REPEAT, _POSSESSIVE_REPEAT):
            unbounded = av[1] == _k.MAXREPEAT or av[1] > 64
            if inside and unbounded:
                yield av
            yield from _nested_repeats(av[2], inside or unbounded)
        elif op is _k.BRANCH:
            for alt in av[1]:
                yield from _nested_repeats(alt, inside)
        elif op is _k.SUBPATTERN:
            yield from _nested_repeats(av[3], inside)
        elif op is _ATOMIC_GROUP:
            yield from _nested_repeats(av, False)
        elif op in (_k.ASSERT, _k.ASSERT_NOT):
            yield from _nested_repeats(av[1], inside)


def test_e9_no_new_greedy_pattern_nests_an_unbounded_repeat(monkeypatch):
    """E9: the smaller backstop bounds a quadratic pattern on 3.10, not one that backtracks without end, and that needs
    an unbounded repeat inside an unbounded repeat once the shim drops the possessive `+`. The greedy copy holds two,
    each unit ending in a character its own repeat cannot take, so a unit splits one way only: _METHOD's `\\w+\\.` and
    _SQL_EXPLAIN_RUNS's `\\w+\\s+`. A NEW one fails here at once (read from the parse trees), where the timing tests
    above would not finish. Must-refuse: the walk finds the shape in `(?:\\w+\\s*)*`."""
    greedy = _greedy_copy(monkeypatch)
    nested = sorted(name for name, p in _patterns(greedy).items()
                    if any(True for _ in _nested_repeats(_sp.parse(p.pattern, p.flags))))
    assert nested == ["_METHOD", "_SQL_EXPLAIN_RUNS"], nested
    assert any(True for _ in _nested_repeats(_sp.parse(r"(?:\w+\s*)*$", 0)))
    assert not any(True for _ in _nested_repeats(_sp.parse(r"\w+\s*$", 0)))


@pytest.mark.parametrize("name", sorted(OLD))
@needs_possessive
def test_the_guard_catches_the_old_quadratic_patterns(name):
    """Mutant check: each of these was in actclass and each is quadratic. Timed at 2 KiB and 8 KiB (x4 text), the work
    grows far more than x6, which is what test_every_pattern_is_linear would assert on it."""
    pat, make = OLD[name]
    t_small = _best(lambda: pat.search(make(2 * K)), runs=1)
    t_big = _best(lambda: pat.search(make(8 * K)), runs=1)
    assert t_big > 8 * t_small and t_big > 0.02, (name, t_small, t_big)


# E7 (round 5): the old patterns as they were in actclass, the A12 one with all twenty of its verbs, and the fragment
# that the generic guard must build for each by itself (not handed to it as the OLD list's input is)
_OLD_METHOD = re.compile(r"(?:\.|::)(" + "|".join(actclass._METHOD_VERBS) + r")[\x00\x01]*(?:\.\w+)*$")
OLD_TRIGGERS = {
    "A12 _METHOD": (OLD["A12 _METHOD"][0], [".send"]), "A12 _METHOD, every verb": (_OLD_METHOD, [".send", ".delete"]),
    "A11 printf spec": (OLD["A11 printf spec"][0], [("%", "0")]), "A21 _STR": (OLD["A21 _STR"][0], ["\\'"]),
    "explain analyze": (OLD["explain analyze"][0], ["explain "]), "ENV_ASSIGN search": (OLD["ENV_ASSIGN search"][0], ["a"]),
}


@pytest.mark.parametrize("name", sorted(OLD_TRIGGERS))
def test_e7_the_generic_guard_builds_the_trigger_of_every_old_pattern(name):
    """E7: the fragments hold every literal of a pattern WITH the punctuation before it ('.send', '.delete'); the sampler
    of r5 built '.dele' and not '.send', so the old _METHOD was caught only by the explicit list. No timing here."""
    pat, triggers = OLD_TRIGGERS[name]
    fr = fragments(pat)
    assert all(t in fr for t in triggers), (name, [t for t in triggers if t not in fr])
    assert {".send", "::send", ".delete", "::deleteasync"} <= lead_runs(_OLD_METHOD)
    assert lead_runs(re.compile(r"abc")) == {"abc"} and lead_runs(re.compile(r"a\d+b")) == {"a", "b"}


@needs_possessive
def test_e7_the_generic_guard_alone_catches_the_old_method_pattern():
    """The mutant check through the guard's own detector (slow_input, as test_every_pattern_is_linear runs it): the old
    _METHOD with every verb is reported slow from its fragments alone; the pattern that replaced it is not."""
    bad = slow_input(_OLD_METHOD)
    assert bad is not None and isinstance(bad[0], str) and bad[0][:1] in (".", ":"), bad    # a led run caught it
    assert slow_input(actclass._METHOD) is None


def test_e7_the_guard_covers_every_module_level_pattern_and_prints_the_counts():
    """The report says 'every module-level pattern' and no number: this test prints the numbers (pytest -s, or -rP)."""
    found = [v for v in vars(actclass).values() if isinstance(v, re.Pattern)]
    assert set(map(id, found)) <= set(map(id, PATTERNS.values()))      # every module-level pattern is guarded
    assert len(set(SHAPES)) == len(SHAPES)
    print(f"guard: {len(PATTERNS)} module-level patterns, {sum(len(fragments(p)) for p in PATTERNS.values())} fragments; "
          f"end to end: {len(SHAPES)} shapes")


# =================================================================================================================
# 2. end to end through decide.decide
# =================================================================================================================
def fill(unit: str, size: int, head: str = "", tail: str = "") -> str:
    n = max(1, (size - len(head) - len(tail)) // max(1, len(unit)))
    return head + unit * n + tail


def find_exec_doc(size, prog, body_unit, doc=True):
    half = size // 2
    execs = "-exec " + prog + " \\; "
    k = max(1, half // len(execs))
    body = body_unit * max(1, (size - half - 40) // len(body_unit))
    if doc:
        return "find . " + execs * k + "<<'EOF'\n" + body + "\nEOF"
    return "find . " + execs * k + "<<< '" + body + "'"


def many_herestr(n, prog="sh", ex="-ok", term="+"):
    """A14: find with N -exec siblings and M here-strings on the same segment (each sibling used to walk all M)."""
    unit_x = f"{ex} {prog} {term} "
    k = max(1, (n // 2) // len(unit_x))
    m = max(1, (n - n // 2 - 8) // len("<<<x"))
    return "find . " + unit_x * k + "<<<x" * m


def many_heredoc(n, prog="sh"):
    unit_x = f"-exec {prog} \\; "
    k = max(1, (n // 2) // len(unit_x))
    m = max(1, (n - n // 2 - 8) // 5)
    return "find . " + unit_x * k + "<<A" * m + "\n" + "A\n" * m


def herestr_distinct(n, prog="sh"):
    unit_x = f"-ok {prog} + "
    k = max(1, (n // 2) // len(unit_x))
    hs, size, i = [], 0, 0
    while size < n - n // 2 - 16:
        h = f"<<<x{i}"
        hs.append(h)
        size += len(h)
        i += 1
    return "find . " + unit_x * k + "".join(hs)


def method_chain_delete(n):
    k = max(1, (n - 1) // 7)
    return "x.delete" + ".delete" * (k - 1) + "!"


# every shape an attacker timed: round 2b's 62 (the first block), round 3's, and the four of this round (A11, A12, A14, A21)
SHAPES = {
    "comment_lf": ("Bash", lambda n: fill("#\n", n)),
    "comment_lf_ucs4": ("Bash", lambda n: fill("#\n", n, head="\U0001F600 ")),
    "comment_cr": ("Bash", lambda n: fill("# x\r", n)),
    "comment_ps": ("PowerShell", lambda n: fill("# c\n", n, head="中 ")),
    "pipe_sudo_chain": ("Bash", lambda n: fill("sudo ", n, head="echo hi | ", tail="sh")),
    "pipe_env_chain": ("Bash", lambda n: fill("env ", n, head="echo hi | ", tail="sh")),
    "exec_hops_words": ("Bash", lambda n: fill("a ", n, head="nice " * 39 + "rm ")),
    "find_exec_doc_sql": ("Bash", lambda n: find_exec_doc(n, "psql", ";")),
    "find_exec_doc_sql_text": ("Bash", lambda n: find_exec_doc(n, "psql", "select 1;\n")),
    "find_exec_doc_mongo": ("Bash", lambda n: find_exec_doc(n, "mongosh", "db.a.find({});\n")),
    "find_exec_doc_python": ("Bash", lambda n: find_exec_doc(n, "python3", "x = 1\n")),
    "find_exec_herestr_sql": ("Bash", lambda n: find_exec_doc(n, "psql", ";", doc=False)),
    "find_exec_herestr_sftp": ("Bash", lambda n: find_exec_doc(n, "sftp", "ls\n", doc=False)),
    "find_exec_doc_redis": ("Bash", lambda n: find_exec_doc(n, "redis-cli", "get a;\n")),
    "heredoc_plain": ("Bash", lambda n: fill("line\n", n, head="cat <<EOF\n", tail="EOF")),
    "heredoc_to_sh": ("Bash", lambda n: fill("echo hi\n", n, head="bash <<'EOF'\n", tail="EOF")),
    "many_heredoc_tags": ("Bash", lambda n: "cat " + "<<A " * (n // 8) + "\n" + "A\n" * (n // 8)),
    "herestring_sh": ("Bash", lambda n: fill("echo a; ", n, head="bash <<< '", tail="'")),
    "nested_subst": ("Bash", lambda n: "$(" * (n // 4) + "a" + ")" * (n // 4)),
    "sibling_subst": ("Bash", lambda n: fill("$(a)", n)),
    "backticks": ("Bash", lambda n: fill("`a` ", n)),
    "dq_subst": ("Bash", lambda n: fill("$(a)", n, head='echo "', tail='"')),
    "dq_unclosed_subst": ("Bash", lambda n: fill("$(", n, head='echo "', tail='"')),
    "squotes": ("Bash", lambda n: fill("'a' ", n)),
    "ansi_c": ("Bash", lambda n: fill("\\'", n, head="$'", tail="'")),
    "continuations": ("Bash", lambda n: fill("a \\\n", n)),
    "escapes": ("Bash", lambda n: fill("\\a", n)),
    "unclosed_dq_esc": ("Bash", lambda n: fill('\\"', n, head='"')),
    "dollar_brace": ("Bash", lambda n: fill("${a} ", n)),
    "dollar_brace_open": ("Bash", lambda n: fill("${", n, head="x ")),
    "arith": ("Bash", lambda n: fill("$((1)) ", n)),
    "procsub": ("Bash", lambda n: fill("<(a) ", n)),
    "redirects": ("Bash", lambda n: fill("> f ", n)),
    "segments": ("Bash", lambda n: fill("a; ", n)),
    "pipes_to_sh": ("Bash", lambda n: fill("a | ", n, tail="sh")),
    "git_push_chain": ("Bash", lambda n: fill("git push && ", n, tail="true")),
    "groups": ("Bash", lambda n: fill("( a ) ", n)),
    "nested_parens": ("Bash", lambda n: "(" * (n // 2) + ")" * (n // 2)),
    "paren_dq_mix": ("Bash", lambda n: fill('("', n)),
    "ps_braces_nested": ("PowerShell", lambda n: "{ " * (n // 4) + "}" * (n // 4)),
    "ps_braces_sibling": ("PowerShell", lambda n: fill("{ a } ", n)),
    "ps_herestring": ("PowerShell", lambda n: fill("x\n", n, head="@'\n", tail="'@")),
    "ps_backtick": ("PowerShell", lambda n: fill("`a", n)),
    "ps_block_comment": ("PowerShell", lambda n: fill("<# a #> ", n)),
    "cmd_amp": ("cmd", lambda n: fill("a & ", n, head="cmd /c ")),
    "ps_encoded": ("PowerShell", lambda n: "pwsh -enc " + base64.b64encode(("git push; " * (n // 14)).encode(
        "utf-16-le")).decode()[: n - 12]),
    "psql_semicolons": ("Bash", lambda n: fill(";", n, head='psql -c "', tail='"')),
    "psql_alter": ("Bash", lambda n: fill("alter table " + "a" * 200 + " ", n, head='psql -c "', tail='"')),
    "python_system": ("Bash", lambda n: fill("os.system('a') ", n, head='python -c "', tail='"')),
    "python_fetch": ("Bash", lambda n: fill("fetch(a, {b: c}) ", n, head="node -e '", tail="'")),
    "eval_chain": ("Bash", lambda n: fill("eval ", n, tail="git push")),
    "sudo_chain": ("Bash", lambda n: fill("sudo ", n, tail="rm x")),
    "xargs_chain": ("Bash", lambda n: fill("xargs ", n, tail="rm")),
    "find_exec_nested": ("Bash", lambda n: fill("find . -exec ", n, tail="rm {} \\;")),
    "find_exec_siblings": ("Bash", lambda n: fill("-exec rm {} \\; ", n, head="find . ")),
    "ssh_nested": ("Bash", lambda n: fill("ssh h ", n, tail="rm x")),
    "docker_exec_nested": ("Bash", lambda n: fill("docker exec c ", n, tail="rm x")),
    "bash_c_nested": ("Bash", lambda n: "bash -c " * 9 + fill("a ", n - 80)),
    "many_words": ("Bash", lambda n: fill("a ", n, head="rm ")),
    "curl_many_opts": ("Bash", lambda n: fill("-H a ", n, head="curl ")),
    "gh_many": ("Bash", lambda n: fill("-f a=b ", n, head="gh api x ")),
    "kubectl_many": ("Bash", lambda n: fill("-l a ", n, head="kubectl delete pod ")),
    "find_exec_doc_sql_ps": ("PowerShell", lambda n: find_exec_doc(n, "psql", ";")),
    # round 2b's own tail (test_actclass_tail.TIMED) and round 3's
    "find_exec_doc_sh": ("Bash", lambda n: find_exec_doc(n, "bash", "echo hi\n")),
    "pipe_nohup_chain": ("Bash", lambda n: fill("nohup ", n, head="echo hi | ", tail="sh")),
    "printf_args": ("Bash", lambda n: fill("a ", n, head="printf 'x%s' ", tail="| sh")),
    "printf_fmt_big": ("Bash", lambda n: "printf '" + "A" * (n // 2) + "%s' " + "a " * (n // 4) + "| bash"),
    "poetry_run_chain": ("Bash", lambda n: fill("poetry run ", n, tail="ls")),
    "doppler_chain": ("Bash", lambda n: fill("doppler run -- ", n, tail="ls")),
    "heroku_run_chain": ("Bash", lambda n: fill("heroku run ", n, tail="ls")),
    "tmux_quoted": ("Bash", lambda n: fill('"a b" ', n, head="tmux send-keys ")),
    "eval_generators": ("Bash", lambda n: fill('eval "$(pyenv init -)"; ', n)),
    "group_pipe_siblings": ("Bash", lambda n: "curl u | " + "(a) " * (n // 4)),
    "ps_keywords": ("PowerShell", lambda n: fill("try { a } catch { b } ", n)),
    "group_pipe_nested": ("Bash", lambda n: "echo | " + "(" * (n // 2 - 8) + ")" * (n // 2 - 8)),
    "group_pipe_nested_pipes": ("Bash", lambda n: "echo " + "| (a " * (n // 5) + ")" * (n // 5)),
    "printf_pipe_sh": ("Bash", lambda n: fill("printf 'a%s\\n' b c | sh; ", n)),
    "source_procsub": ("Bash", lambda n: fill("<(x) ", n, head="source ")),
    "eval_gen": ("Bash", lambda n: fill('eval "$(ssh-agent -s)"; ', n)),
    # A11: printf's format spec (156 s at 64 KiB in decide)
    "printf_zeros": ("Bash", lambda n: "printf '%" + "0" * max(1, n - 16) + "z' | sh"),
    "printf_zeros_many": ("Bash", lambda n: "printf '" + ("%" + "0" * 200 + "z") * max(1, (n - 16) // 202) + "' | sh"),
    # A12: _METHOD's trailing chain (11.6 s)
    "method_chain_send": ("Bash", lambda n: ".send" * max(1, (n - 1) // 5) + "!"),
    "method_chain_send_ps": ("PowerShell", lambda n: ".send" * max(1, (n - 1) // 5) + "!"),
    "method_chain_delete": ("Bash", method_chain_delete),
    "method_chain_download_ps": ("PowerShell", lambda n: "$a" + ".DownloadString" * max(1, (n - 3) // 15) + "!"),
    # A14: find with many -exec siblings and many here-strings / here-documents (5 s, sftp 12 s)
    "find_many_herestr_sh": ("Bash", lambda n: many_herestr(n, "sh")),
    "find_many_herestr_psql": ("Bash", lambda n: many_herestr(n, "psql")),
    "find_many_herestr_py": ("Bash", lambda n: many_herestr(n, "python3")),
    "find_many_herestr_sftp": ("Bash", lambda n: many_herestr(n, "sftp")),
    "find_many_herestr_ssh": ("Bash", lambda n: many_herestr(n, "ssh h")),
    "find_many_heredoc_sh": ("Bash", lambda n: many_heredoc(n, "sh")),
    "find_many_herestr_distinct": ("Bash", lambda n: herestr_distinct(n, "sh")),
    "find_many_herestr_ps": ("PowerShell", lambda n: many_herestr(n, "sh")),
    "find_many_redirs_curl": ("Bash", lambda n: "find . " + "-exec curl u \\; " * (n // 40) + "> f " * (n // 8)),
    # A21: _blank's string pattern on a run of \' (13.6 s)
    "blank_bs_squote_python": ("Bash", lambda n: "python -c \"'" + "\\'" * max(1, (n - 16) // 2) + "\""),
    "blank_bs_dquote_python": ("Bash", lambda n: "python -c '\"" + '\\"' * max(1, (n - 16) // 2) + "'"),
    # the shapes the r5 features could add: the second reading, groups, here-document commands, pipe wrappers, arrays
    "alt_many_options": ("Bash", lambda n: fill("-n a ", n, head="kubectl ", tail="delete pod x")),
    "alt_docker_options": ("Bash", lambda n: fill("--label a ", n, head="docker run ", tail="alpine rm x")),
    "alt_nested_exec": ("Bash", lambda n: fill("docker --debug exec c ", n, tail="rm x")),
    "heredoc_cmd_subs": ("Bash", lambda n: fill("$(a)\n", n, head="cat <<EOF\n", tail="EOF")),
    "herestr_cmd_subs": ("Bash", lambda n: fill('<<< "$(a)" ', n, head="cat ")),
    "pipe_timeout_chain": ("Bash", lambda n: fill("timeout 5 ", n, head="echo hi | ", tail="sh")),
    "pipe_unknown_wrapper": ("Bash", lambda n: fill("foo ", n, head="echo hi | ", tail="sh")),
    "pipe_flock_chain": ("Bash", lambda n: fill("flock /tmp/l ", n, head="echo hi | ", tail="sh")),
    "group_scripts": ("Bash", lambda n: fill("./a.sh; ", n, head="(", tail=")")),
    "group_scripts_nested": ("Bash", lambda n: "(./a.sh; " * (n // 10) + ")" * (n // 10)),
    "ps_arglist_array": ("PowerShell", lambda n: fill("'a', ", n, head="Start-Process x -ArgumentList ", tail="'b'")),
    "ps_arglist_glued": ("PowerShell", lambda n: fill("'a',", n, head="Start-Process x -ArgumentList ", tail="'b'")),
    "ps_arglist_at": ("PowerShell", lambda n: fill("'a',", n, head="Start-Process x -ArgumentList @(", tail="'b')")),
    "ps_run_vars": ("PowerShell", lambda n: fill("Start-Process $a; ", n)),
    "sql_explain": ("Bash", lambda n: fill("explain ", n, head='psql -c "', tail='"')),
    "sql_delete_words": ("Bash", lambda n: fill("delete a ", n, head='psql -c "', tail='"')),
    "sql_unterminated_dq": ("Bash", lambda n: fill('" a ', n, head="psql -c '", tail="'")),
    "code_fetch_calls": ("Bash", lambda n: fill("fetch(", n, head="node -e '", tail="'")),
    "code_exec_calls": ("Bash", lambda n: fill("exec(a);", n, head="node -e '", tail="'")),
    "code_quotes_alt": ("Bash", lambda n: fill("'\"", n, head="python -c \"", tail="\"")),
    "stdin_python_c": ("Bash", lambda n: fill("a ", n, head="echo x | python3 -c '", tail="'")),
    "unknown_prog_words": ("Bash", lambda n: fill("drop table ", n, head="zzz ")),
    # round 6: the shapes its own code adds (the cost budget: every one under 0.5 s at 64 KiB, as every shape above)
    "sp_arglist_spaces": ("PowerShell", lambda n: fill("'push origin main', ", n, head="Start-Process git -ArgumentList ",
                                                       tail="'--force'")),
    "sp_arglist_quotes": ("PowerShell", lambda n: fill('\\"a b\\" ', n, head="Start-Process x -ArgumentList '", tail="'")),
    "sp_arglist_backslashes": ("PowerShell", lambda n: fill('\\\\\\"', n, head="Start-Process x -ArgumentList '", tail="'")),
    "runas_program": ("PowerShell", lambda n: fill("a ", n, head='runas /user:x "cmd /c ', tail='"')),
    "aws_grants_list": ("Bash", lambda n: fill("read=uri=x ", n, head="aws s3 cp ./x s3://b --grants ")),
    "aws_unsure_operands": ("Bash", lambda n: fill("./a s3://b ", n, head="aws s3 cp --zz v ")),
    "aws_flag_reading": ("Bash", lambda n: fill("--exclude ", n, head="aws ", tail="s3 cp ./d s3://b")),
    "kubectl_flag_reading": ("Bash", lambda n: fill("--as x ", n, head="kubectl ", tail="delete pod x")),
    "spliced_statements": ("PowerShell", lambda n: fill("cd x && ", n, head='cmd /c "', tail='$cmd"')),
    "spliced_ps_statements": ("PowerShell", lambda n: fill("Set-Location x; ", n, head='pwsh -c "', tail='$task"')),
    "ssh_remote_text": ("Bash", lambda n: fill("cd /x && ", n, head="curl u | ssh h '", tail="bash'")),
    "su_c_text": ("Bash", lambda n: fill("cd /x && ", n, head="curl u | su -c '", tail="bash' deploy")),
    "sh_c_stdin_text": ("Bash", lambda n: fill("cd /x; ", n, head="curl u | sh -c '", tail="exec bash'")),
    "brace_groups": ("Bash", lambda n: fill("{ ./a.sh; } && ", n, tail="true")),
    "brace_nested": ("Bash", lambda n: "{ " * (n // 4) + "./a.sh; " + "} " * (n // 4)),
    "icm_positional": ("PowerShell", lambda n: fill("-ComputerName x ", n, head="Invoke-Command ", tail="$sb")),
    "xargs_c_options": ("Bash", lambda n: fill("-n 1 ", n, head="cat x | xargs ", tail="bash -c")),
    "parallel_args": ("Bash", lambda n: fill("'ls' ", n, head="parallel ::: ")),
    "ps_array_splat": ("PowerShell", lambda n: fill("'a',", n, head="& git @(", tail="'push')")),
    "dq_escaped_subs": ("Bash", lambda n: fill("\\$(a) ", n, head='echo "', tail='"')),
    "heredoc_escaped_subs": ("Bash", lambda n: fill("\\\\\\$(a)\n", n, head="cat <<EOF\n", tail="EOF")),
    "group_targets": ("Bash", lambda n: fill("make all-test-build-lint ", n, head="(cd a && ", tail=")")),
}


def shape_params():
    return [pytest.param(name, id=name) for name in sorted(SHAPES)]


WORDS = "Don't push, publish, delete, send, pay or download anything."
_TOOLS = {
    "ps.yaml": "id: ps\nkind: tool\nname: PowerShell\nruns_as: client\nruns_programs: true\ntests: []\n",
    "shell.yaml": "id: shell\nkind: tool\nname: shell\nruns_as: client\nruns_programs: true\ntests: []\n",
    "cmdt.yaml": "id: cmdt\nkind: tool\nname: cmd\nruns_as: client\nruns_programs: true\ntests: []\n",
}
_CODER = ("id: coder\nkind: agent\nidentity: claude-code\nmodels: [claude]\ntools: [bash, ps, shell, cmdt]\n"
          "budgets: {asks_open: 400}\ntests: []\n")


@pytest.fixture(scope="module")
def space(tmp_path_factory):
    return space_of(tmp_path_factory.mktemp("lin"), {**_TOOLS, "coder.yaml": _CODER}, drop=("shell-held.yaml",))


_n = [0]


def _decide(space, tmp_path, tool, cmd):
    """One turn with the call in it and the person's words that hold every act: the time decide.decide takes."""
    _n[0] += 1
    asks = decide.Asks(tmp_path / f"asks{_n[0]}.json", run="r")
    t0 = time.perf_counter()
    out = decide.decide(space, "s", "coder", "claude", msg(text("Doing it now."), call(tool, {"command": cmd})),
                        f"c{_n[0]}", asks, 100.0, words=WORDS)
    return time.perf_counter() - t0, out


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_end_to_end_64k_is_under_half_a_second(name, space, tmp_path):
    """The four HIGH shapes of this round and every shape the round-2b and round-3 attackers timed: through
    decide.decide (the reading, the words, the ask), best of two, 64 KiB under 0.5 s."""
    tool, gen = SHAPES[name]
    cmd = gen(64 * K - 64)[:actclass.MAX_COMMAND]
    best = min(_decide(space, tmp_path, tool, cmd)[0] for _ in range(2))
    assert best < 0.5, (name, len(cmd), best)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_end_to_end_one_mib_returns_at_once_as_every_act(name, space, tmp_path):
    """A command over the stated size (MAX_COMMAND, 64 KiB) is every act and is not read at all."""
    tool, gen = SHAPES[name]
    cmd = gen(K * K)
    assert len(cmd) > actclass.MAX_COMMAND
    dt, out = _decide(space, tmp_path, tool, cmd)
    assert dt < 0.5, (name, dt)
    assert out.held, name                                # every act: the words hold it
    assert actclass.acts_of_call(tool, {"command": cmd}) == ALL


@pytest.mark.parametrize("name", ["printf_zeros", "method_chain_send", "method_chain_delete",
                                  "find_many_herestr_sh", "find_many_herestr_sftp", "blank_bs_squote_python"])
def test_the_high_shapes_grow_about_linearly(name):
    """16 KiB to 64 KiB (x4 text): under x9 the time, as the shapes of r4 are pinned (they were x4 per doubling)."""
    tool, gen = SHAPES[name]
    small = _best(lambda: actclass.acts_of_call(tool, {"command": gen(16 * K)[:actclass.MAX_COMMAND]}))
    big = _best(lambda: actclass.acts_of_call(tool, {"command": gen(64 * K - 64)[:actclass.MAX_COMMAND]}))
    assert big < 0.5 and big < 9 * small + 0.03, (name, small, big)


# =================================================================================================================
# 3. the bound itself
# =================================================================================================================
def test_the_stated_size_is_64_kib_and_a_longer_command_is_not_read(monkeypatch):
    """(A15e) The backstop: over MAX_COMMAND is every act, decided before any text is lexed or read. It is 64 KiB from
    Python 3.11; on 3.10, where the patterns are greedy, it is the smaller MAX_COMMAND_310 (E9)."""
    assert actclass.MAX_COMMAND == (64 * K if POSSESSIVE else actclass.MAX_COMMAND_310)

    def boom(*a, **k):
        raise AssertionError("the command was read")
    monkeypatch.setattr(actclass, "_Lex", boom)
    monkeypatch.setattr(actclass, "_read", boom)
    assert actclass.acts_of_call("Bash", {"command": "x" * (actclass.MAX_COMMAND + 1)}) == ALL
    assert actclass.acts_of_call("PowerShell", {"command": ["x"] * (actclass.MAX_COMMAND + 1)}) == ALL
    assert actclass.acts_of_call("Bash", {"command": "x" * (4 * K * K)}) == ALL


def test_a_command_over_the_work_budget_is_every_act_never_a_part(monkeypatch):
    """(A15b) 'git push; rm x' is push and delete; when the budget cannot pay for reading it, it is all six, not one."""
    cmd = "git push; rm x; echo hi"
    assert actclass.acts_of_call("Bash", {"command": cmd}) == ("push", "delete")
    monkeypatch.setattr(actclass, "WORK_FACTOR", 0)
    monkeypatch.setattr(actclass, "WORK_SLACK", 0)
    assert actclass.acts_of_call("Bash", {"command": cmd}) == ALL
    # and when the reading itself fits but a reader's text does not, the answer is again all of them
    monkeypatch.undo()
    for src in ("psql -c 'select 1'", "python3 -c 'print(1)'", "osascript -e 'tell app \"x\" to quit'",
                "sftp host 'ls -l'", "printf 'git push\\n' | sh", "printf '%s' a b | bash", "echo 'ls' | psql",
                "echo hi | (cat; bash)", "echo x | python3 -c 'print(1)'"):
        got = actclass._read(src, False, 0, [0, len(src) + 1, {}])
        assert got == set(ALL), (src, got)             # exactly the command's own length is paid; the text read is not
    for src in ("ls -la", "git status", "echo hello"):
        assert actclass._read(src, False, 0, [0, len(src) + 1, {}]) == set(), src       # must-refuse: nothing more is read


def test_budget_exhausted_anywhere_in_the_call_is_every_act(monkeypatch):
    """The last word on the budget is in _shell_acts: a reader that stopped on it cannot leave a part behind."""
    monkeypatch.setattr(actclass, "WORK_FACTOR", 0)
    monkeypatch.setattr(actclass, "WORK_SLACK", 0)
    for cmd in ("ls", "echo hi", "git push", "x=1", "psql -c 'select 1'"):
        assert actclass.acts_of_call("Bash", {"command": cmd}) == ALL, cmd
