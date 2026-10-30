"""The security floor (docs/security-floor.md) names, for each promise, the tests that hold it, by node id. This check
reads the page and the source of each named test (parsed, never imported; only a [case] is looked up in pytest's own
collection, in a second process) and refuses exactly the patterns listed below. It is a static reader of source and
can never be complete: a test written to evade it is out of its reach, and the floor is also attacked by an
independent reader each release. Read from a source checkout; skipped when the package is installed without its docs.

The page. Refused: a line numbered like a property ("2.", " 2.", "2)", "2.  ", "2. not bold") that is not written
`N. **the promise**` on one line; numbers out of order from 1; a property naming no test; in a property, anything in
backticks holding ".py" or "::" that is not a node id as pytest writes it (tests/test_<file>.py::<test>, or
::<Class>::<test>, optionally [<case>]; so no ./, no backslash, no bare file), and any ".py" or "::" outside backticks.

Where the test is. Refused: no such file; no such test at module level, or as a method of a class Test*; a name pytest
does not collect (not test*); a name bound twice at its level (test_x = None later; an attribute assignment such as
test_x.attr = 1 does not count); a [case] pytest does not collect.

Switched off. Refused, from the test's own file, with pytest, unittest and contextlib imported under any alias or by
name, anywhere in the file (a function's own `import pytest as q` included):
  - __test__ set to a literal false value (False, None, 0, "", an empty display; a computed value such as bool(0) is
    not read) at the module's level or a class's, in any block there (if, for, while, with, try), by: __test__ = v
    (annotated, or a target of a tuple assignment or of a for over a literal list), (__test__ := v),
    globals()/vars()/locals()["__test__"] = v, globals().update({"__test__": v}) or update(__test__=v), and, for a
    name X that is the test or one of its classes, X.__test__ = v, X.__dict__["__test__"] = v, setattr(X, "__test__",
    v); a setattr on an expression that is not a name counts as the module's. For a test in a class, the nearest of its
    class and the same-file classes it inherits from (by plain name) that writes __test__ decides, as Python looks it
    up;
  - a Test* class with an __init__ or a __new__, its own or one it inherits from a class of the same file;
  - a file that calls pytest.exit anywhere;
  - a test whose name is also removed or bound again at its level: del test_x, test_x = ..., or a globals(),
    vars() or locals() item set to it (or with a key that is not a literal);
  - an async def test (pytest runs one only with a plug-in), or a test whose own body yields;
  - pytest.mark.skip or pytest.mark.xfail, unittest.skip or unittest.expectedFailure, as a decorator of the test or of
    its class or of a same-file class it inherits from, or in a pytestmark of any of those classes or of the module
    (=, +=, an annotated assignment, .append, .extend) or one set on the test at module level (test_x.pytestmark =
    ...); a mark kept in a module-level name, or a list or tuple of marks kept in one, is read as those marks;
  - a decorator defined in the same file whose body names one of those marks;
  - pytest.mark.parametrize over a literal empty list or tuple, list() or tuple(); or a requested fixture of its own
    file or a conftest.py above it parametrized so (@pytest.fixture(params=[]));
  - pytest.skip, pytest.xfail or pytest.fail as a statement, or raise unittest.SkipTest, at the module's top level or
    at the test's own top level.

No check that can fail. Refused unless the test's own body holds, reachable, an assert, a `with pytest.raises(E)`,
or a pytest.raises(E, what_to_run, ...) call (a bare pytest.raises(E) checks nothing, and a raises of AssertionError,
Exception or BaseException is no check): reachable means not after a return, raise, break or continue in its block,
not in an if or while branch a literal test shuts, not only inside a nested def, class or lambda, and not inside a try
whose except takes AssertionError, Exception, BaseException or anything, a with of contextlib.suppress, or a with of
a pytest.raises of those; and the assert's expression must not have one fixed value: a literal, a non-empty display,
a name the test binds only to literals, an or with a true literal or an and with a false one, or not, an operator, a
comparison or and/or of nothing but those. A return at the test's top level before its first check is refused.

May skip. A test that can skip itself must be named on a "Skips:" line of its property: a skipif or unittest
skipIf/skipUnless mark (where the marks above are read); a case of its parametrize given a skip or skipif mark
(pytest.param(..., marks=...)); pytest.skip, xfail, fail or importorskip, or raise
SkipTest, anywhere in its body; one at module level under an if or a try; a same-file decorator naming a skip; a
return under a branch before its first check; or a helper of its own file it calls by name, or a fixture of its own
file or of a conftest.py above it that it requests (as a parameter or in pytest.mark.usefixtures), that can skip,
followed by name to a fixed point.

Out of its reach, and these are examples, not a complete list: a base class reached other than by its plain name
(class TestK(ns.Base)); a __test__ given a computed value; a mark reached by subscript or getattr
(pytest.mark["skip"], getattr(pytest.mark, "skip")); _pytest.outcomes or another private module; a decorator of the
same file that replaces or wraps the function (one that swallows its failure, or returns another); a test deselected
by the configuration (addopts = --deselect in pytest.ini, pyproject or setup.cfg); a skip through a helper imported
from another module, a method called on an object, a plug-in's fixture or hook, or a conftest's collection hook; marks
added at collection; a helper's assert (a test that checks only through a helper is refused, not trusted); and any
check that can run but cannot fail for a reason its source does not show. A test written to evade the check is out of
its reach; the floor is also attacked by an independent reader each release."""
import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

import semantext

ROOT = Path(semantext.__file__).resolve().parents[1]
FLOOR = ROOT / "docs" / "security-floor.md"
NUMBERED = re.compile(r"^\s*\d+\s*[.)]")                      # any line numbered like a property
HEADING = re.compile(r"^(\d+)\. \*\*(.+?)\*\*")               # the one way a property is written
TICKED = re.compile(r"`([^`\n]*)`")
NODE = re.compile(r"(tests/(?:[\w-]+/)*test_\w+\.py)((?:::[A-Za-z_]\w*){1,2})(\[[^\]\s`]+\])?")
SKIPS = re.compile(r"^\s*Skips:", re.M)


def items(text: str) -> tuple[list[tuple[int, str, str]], list[str]]:
    """([(number, the promise, its body)], errors): every line numbered like a property is one, or an error."""
    out, errors = [], []
    lines = text.split("\n")
    starts = []
    for k, line in enumerate(lines):
        if NUMBERED.match(line):
            m = HEADING.match(line)
            if m:
                starts.append((k, int(m.group(1)), m.group(2)))
            else:
                errors.append(f"line {k + 1} is numbered like a property but not written `N. **promise**`: "
                              f"{line.strip()[:60]!r}")
    for i, (k, n, promise) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(lines)
        out.append((n, promise, "\n".join([lines[k][len(HEADING.match(lines[k]).group(0)):]] + lines[k + 1:end])))
    return out, errors


def _named(body: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """The node ids a property names, as (id, file, parts-and-case), and every way it names a test that is not one."""
    nodes, errors = [], []
    for span in TICKED.findall(body):
        if ".py" in span or "::" in span:
            m = NODE.fullmatch(span)
            if m:
                nodes.append((span, m.group(1), m.group(2) + (m.group(3) or "")))
            else:
                errors.append(f"`{span}` is not a node id as pytest writes it (tests/test_<file>.py::<test>)")
    bare = TICKED.sub("", body)
    for word in re.findall(r"\S*(?:\.py|::)\S*", bare):
        errors.append(f"{word} names a test without backticks")
    return nodes, errors


SKIP_MARKS = {("pytest", "mark", "skip"), ("pytest", "mark", "xfail"), ("unittest", "skip"),
              ("unittest", "expectedFailure")}                                   # never runs, or never fails
MAYBE_MARKS = {("pytest", "mark", "skipif"), ("unittest", "skipIf"), ("unittest", "skipUnless")}
ALWAYS_CALLS = {("pytest", "skip"), ("pytest", "xfail"), ("pytest", "fail"), ("unittest", "SkipTest")}
SKIP_CALLS = ALWAYS_CALLS | {("pytest", "importorskip")}   # importorskip skips only when the module is missing
RAISES = {("pytest", "raises")}
SUPPRESS = {("contextlib", "suppress")}
PARAMETRIZE = {("pytest", "mark", "parametrize")}
USEFIXTURES = {("pytest", "mark", "usefixtures")}
PARAM = {("pytest", "param")}
EXIT = {("pytest", "exit")}
TRACKED = ("pytest", "unittest", "contextlib")
SWALLOWERS = (None, "AssertionError", "Exception", "BaseException")   # an except clause that catches a failed assert


class Module:
    """A test file as pytest and Python would read its names: every import of pytest or unittest, under any alias
    (import pytest as pt; from pytest import mark, skip), and every module-level name bound to a value, so a mark
    kept in a name (windows_only = pytest.mark.skipif(...)) is read as the mark it is."""

    def __init__(self, tree: ast.Module):
        self.tree, self.alias, self.named = tree, {}, {}
        for s in ast.walk(tree):   # an import anywhere, a function's own `import pytest as q` included
            if isinstance(s, ast.Import):
                for a in s.names:
                    top = a.name.split(".")[0]
                    if top in TRACKED:
                        self.alias[a.asname or top] = tuple(a.name.split(".")) if a.asname else (top,)
            elif isinstance(s, ast.ImportFrom) and (s.module or "").split(".")[0] in TRACKED:
                for a in s.names:
                    self.alias[a.asname or a.name] = tuple(s.module.split(".")) + (a.name,)
        for s in tree.body:
            if isinstance(s, ast.Assign):
                self.named.update({t.id: s.value for t in s.targets if isinstance(t, ast.Name)})
        self.defs = {s.name: s for s in tree.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}

    def dotted(self, node) -> tuple:
        """The full name an expression (or the call of one) stands for: ("pytest", "mark", "skip"), or ()."""
        for _ in range(16):   # a name bound to a name bound to a mark, to a bound
            if isinstance(node, ast.Call):
                node = node.func
            elif isinstance(node, ast.Name) and node.id in self.named and node.id not in self.alias:
                node = self.named[node.id]
            else:
                break
        names = []
        while isinstance(node, ast.Attribute):
            names.append(node.attr)
            node = node.value
        if not isinstance(node, ast.Name) or node.id not in self.alias:
            return ()
        return self.alias[node.id] + tuple(reversed(names))

    def is_(self, node, names: set) -> bool:
        return self.dotted(node) in names


def _pytestmarks(body) -> tuple[list, bool]:
    """(every mark a pytestmark at this level holds, whether __test__ is set false here): pytestmark = x, = [x, y],
    pytestmark: list = [...], pytestmark += [...], pytestmark.append(x) and .extend([...]) alike."""
    marks, off = [], False

    def take(value):
        marks.extend(value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value])
    for s in body:
        targets = s.targets if isinstance(s, ast.Assign) else [s.target] if isinstance(
            s, (ast.AnnAssign, ast.AugAssign)) else []
        for t in targets:
            if isinstance(t, ast.Name) and t.id == "pytestmark" and s.value is not None:
                take(s.value)
            if isinstance(t, ast.Name) and t.id == "__test__" and s.value is not None:
                off = off or not (isinstance(s.value, ast.Constant) and s.value.value is True)
        if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call) and isinstance(s.value.func, ast.Attribute) \
                and isinstance(s.value.func.value, ast.Name) and s.value.func.value.id == "pytestmark" \
                and s.value.func.attr in ("append", "extend") and s.value.args:
            take(s.value.args[0])
    return marks, off


def _const(test) -> bool | None:
    """The truth an expression has whatever runs, when it has one: a literal, a non-empty display (a tuple, a list,
    an f-string), or `not` of one. None when it depends on what runs."""
    if isinstance(test, ast.Constant):
        return bool(test.value)
    if isinstance(test, (ast.Tuple, ast.List, ast.Set)) and test.elts or isinstance(test, ast.Dict) and test.keys:
        return True
    if isinstance(test, ast.JoinedStr) and test.values:
        return True
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _const(test.operand)
        return None if inner is None else not inner
    return None


def _fixed(test, consts: set) -> bool:
    """Whether an expression has one value whatever runs: a literal or a non-empty display, a name the test binds only
    to literals, or an operation (not, +, ==, and, ...) on nothing but such values. An assert of one cannot fail, or
    always fails, by its source."""
    if _const(test) is not None or isinstance(test, ast.Name) and test.id in consts:
        return True
    if isinstance(test, ast.UnaryOp):
        return _fixed(test.operand, consts)
    if isinstance(test, ast.BinOp):
        return _fixed(test.left, consts) and _fixed(test.right, consts)
    if isinstance(test, ast.BoolOp):   # x or True is always true, x and False always false, whatever x is
        short = True if isinstance(test.op, ast.Or) else False
        return any(_const(v) is short for v in test.values) or all(_fixed(v, consts) for v in test.values)
    if isinstance(test, ast.Compare):
        return all(_fixed(v, consts) for v in [test.left, *test.comparators])
    return False


def _literal_names(fn) -> set:
    """The names a test binds only to literals in its own body, and never takes as a parameter or from outside."""
    params = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    bound: dict = {}
    for n in ast.walk(fn):
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            params.update(n.names)
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(
            n, (ast.AnnAssign, ast.AugAssign, ast.For, ast.AsyncFor, ast.NamedExpr)) else []
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name):
                    value = getattr(n, "value", None)
                    literal = isinstance(n, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and isinstance(
                        t, ast.Name) and value is not None and _const(value) is not None
                    bound[x.id] = bound.get(x.id, True) and literal
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                for x in ast.walk(item.optional_vars) if item.optional_vars is not None else ():
                    if isinstance(x, ast.Name):
                        bound[x.id] = False
    return {k for k, literal in bound.items() if literal and k not in params}


def _swallows(mod: Module, s) -> bool:
    """Whether a statement runs its body with a failed assert caught: a try whose except takes AssertionError (or
    Exception, BaseException, or anything), or a with of contextlib.suppress."""
    if isinstance(s, ast.Try) or type(s).__name__ == "TryStar":
        for h in s.handlers:
            kinds = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
            if any(k is None or isinstance(k, ast.Name) and k.id in SWALLOWERS or isinstance(k, ast.Attribute)
                   and k.attr in SWALLOWERS for k in kinds):
                return True
    if isinstance(s, (ast.With, ast.AsyncWith)):
        return any(mod.is_(item.context_expr, SUPPRESS) or _broad_raises(mod, item.context_expr) for item in s.items)
    return False


def _swallower(kind) -> bool:
    """Whether an exception type, as written, catches a failed assert: AssertionError, Exception or BaseException."""
    kinds = kind.elts if isinstance(kind, ast.Tuple) else [kind]
    return any(isinstance(k, ast.Name) and k.id in SWALLOWERS or isinstance(k, ast.Attribute) and k.attr in SWALLOWERS
               for k in kinds)


def _broad_raises(mod: Module, node) -> bool:
    """A pytest.raises of AssertionError, Exception or BaseException: around an assert it passes when the assert
    fails, so it is no check, and what it wraps is swallowed."""
    return isinstance(node, ast.Call) and mod.is_(node, RAISES) and bool(node.args) and _swallower(node.args[0])


def _reachable(body, mod: Module | None = None, swallowed: bool = False):
    """(statement, whether a failure in it is swallowed) for each statement of a block that can run, the blocks inside
    them included, in order: none after a return, a raise, a break or a continue in the same block; no branch a
    constant test shuts; never into a nested def, class or lambda, whose body runs only if something calls it. A
    statement inside a try that catches AssertionError, or a with of contextlib.suppress, is swallowed."""
    for s in body:
        yield s, swallowed
        if isinstance(s, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            return
        inner = swallowed or (mod is not None and _swallows(mod, s))
        if isinstance(s, (ast.If, ast.While)):
            c = _const(s.test)
            if c is not False:
                yield from _reachable(s.body, mod, swallowed)
            if c is not True:
                yield from _reachable(s.orelse, mod, swallowed)
        elif isinstance(s, (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith)):
            yield from _reachable(s.body, mod, inner)
            yield from _reachable(getattr(s, "orelse", []), mod, swallowed)
        elif isinstance(s, ast.Try) or type(s).__name__ == "TryStar":
            yield from _reachable(s.body, mod, inner)
            for h in s.handlers:
                yield from _reachable(h.body, mod, swallowed)
            yield from _reachable(s.orelse, mod, swallowed)
            yield from _reachable(s.finalbody, mod, swallowed)
        elif type(s).__name__ == "Match":
            for case in s.cases:
                yield from _reachable(case.body, mod, swallowed)


def _expressions(stmt):
    """The expressions a statement itself evaluates, without the blocks inside it, nor a nested def or lambda."""
    blocks = ("body", "orelse", "finalbody", "handlers", "cases")
    stack = [getattr(stmt, f) for f in stmt._fields if f not in blocks]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, ast.AST) and not isinstance(x, (ast.Lambda, ast.stmt)):
            yield x
            stack.extend(getattr(x, f) for f in x._fields)


def _bindings(body, name: str) -> int:
    """How many statements at this level bind `name`: defs, classes, assignments and imports."""
    n = 0
    for s in body:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and s.name == name:
            n += 1
        elif isinstance(s, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = list(s.targets if isinstance(s, ast.Assign) else [s.target])
            while targets:   # the names bound, unpacking included; test_x.attr = ... binds no name
                t = targets.pop()
                if isinstance(t, (ast.Tuple, ast.List)):
                    targets.extend(t.elts)
                elif isinstance(t, ast.Starred):
                    targets.append(t.value)
                elif isinstance(t, ast.Name) and t.id == name:
                    n += 1
                elif isinstance(t, ast.Subscript) and isinstance(t.value, ast.Call) and isinstance(
                        t.value.func, ast.Name) and t.value.func.id in ("globals", "vars", "locals"):
                    key = t.slice
                    if not isinstance(key, ast.Constant) or key.value == name:   # globals()["test_x"] = ..., or any
                        n += 1
        elif isinstance(s, ast.Delete):   # del test_x leaves pytest nothing of that name
            n += sum(isinstance(t, ast.Name) and t.id == name for t in s.targets)
        elif isinstance(s, (ast.Import, ast.ImportFrom)):
            n += sum((a.asname or a.name.split(".")[0]) == name for a in s.names)
    return n


def _target(tree: ast.Module, parts: list[str]):
    """(the test's def where pytest collects it, its class or None, None), or (None, None, why there is none)."""
    funcs = (ast.FunctionDef, ast.AsyncFunctionDef)
    level, name, cls = tree.body, parts[-1], None
    if len(parts) == 2:
        cls = next((s for s in tree.body if isinstance(s, ast.ClassDef) and s.name == parts[0]), None)
        if cls is None or not parts[0].startswith("Test"):
            return None, None, f"no class Test* named {parts[0]}"
        if _bindings(tree.body, parts[0]) != 1:
            return None, None, f"{parts[0]} is bound more than once"
        level = cls.body
    if not name.startswith("test"):
        return None, None, f"{name} is not a name pytest collects"
    found = [s for s in level if isinstance(s, funcs) and s.name == name]
    if not found:
        return None, None, "no such test"
    if _bindings(level, name) != 1:
        return None, None, f"{name} is bound more than once, so pytest may run something else or nothing"
    return found[0], cls, None


def _always(mod: Module, s) -> bool:
    """Whether a statement is, of itself, a skip or an expected failure: pytest.skip(...), pytest.xfail(...),
    pytest.fail(...) as a statement, or raise unittest.SkipTest."""
    if isinstance(s, ast.Expr):
        return isinstance(s.value, ast.Call) and mod.is_(s.value, ALWAYS_CALLS)
    return isinstance(s, ast.Raise) and s.exc is not None and mod.is_(s.exc, ALWAYS_CALLS)


def _mentions_skip(mod: Module, node) -> bool:
    """Whether anything inside a node can skip: a call of a skip, or raise of SkipTest, anywhere in it."""
    return any(isinstance(n, ast.Call) and mod.is_(n, SKIP_CALLS)
               or isinstance(n, ast.Raise) and n.exc is not None and mod.is_(n.exc, SKIP_CALLS) for n in ast.walk(node))


def _skippers(mods: list[Module]) -> set[str]:
    """The names of the functions and fixtures in these files that can skip whoever calls or requests them: one that
    mentions a skip itself, or calls by name, or requests as a fixture, one that can (worked out to a fixed point). A
    fixture is known by its own name, or by the name= its fixture mark gives."""
    defs = {}
    for mod in mods:
        for s in mod.tree.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [s.name] + [k.value.value for d in s.decorator_list if isinstance(d, ast.Call)
                                    for k in d.keywords if k.arg == "name" and isinstance(k.value, ast.Constant)]
                for name in names:
                    defs.setdefault(name, []).append((mod, s))
    can = {name for name, found in defs.items() if any(_mentions_skip(m, s) for m, s in found)}
    while True:
        more = {name for name, found in defs.items() if name not in can and any(_reaches(s) & can for _, s in found)}
        if not more:
            return can
        can |= more


def _no_cases(mods: list[Module]) -> set[str]:
    """The fixtures in these files parametrized over a literal empty list (@pytest.fixture(params=[])): a test that
    requests one never runs. Known by the fixture's own name or its name=."""
    out = set()
    for mod in mods:
        for s in mod.tree.body:
            if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in s.decorator_list:
                    if isinstance(d, ast.Call) and any(k.arg == "params" and _empty(k.value) for k in d.keywords):
                        out |= {s.name} | {k.value.value for k in d.keywords
                                           if k.arg == "name" and isinstance(k.value, ast.Constant)}
    return out


def _reaches(fn) -> set[str]:
    """The names a function calls directly and the fixtures it requests (its parameters)."""
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return called | {a.arg for a in fn.args.args + fn.args.kwonlyargs}


def _conftests(root: Path, file: str) -> list[Module]:
    """The conftest.py files pytest would load for a test file: in its folder and each one above it, up to root."""
    out, here = [], (root / file).parent
    while True:
        c = here / "conftest.py"
        if c.is_file():
            out.append(Module(ast.parse(c.read_text(encoding="utf-8"))))
        if here == root or here.parent == here:
            return out
        here = here.parent


def _lineage(tree: ast.Module, cls) -> list:
    """A test's class and every class of the same file it inherits from, nearest first."""
    out, todo = [], [cls] if cls is not None else []
    while todo:
        c = todo.pop(0)
        if c is None or c in out:
            continue
        out.append(c)
        todo += [next((s for s in tree.body if isinstance(s, ast.ClassDef) and s.name == b.id), None)
                 for b in c.bases if isinstance(b, ast.Name)]
    return out


def _marks(mod: Module, fn, cls=None) -> list:
    """Every mark on a test: its decorators; the decorators and the pytestmark of its class and of every class of the
    same file it inherits from; the module's pytestmark; and a pytestmark set on the function at module level
    (test_x.pytestmark = ...). A module-level name bound to a list or tuple of marks is read as those marks."""
    own = []
    for s in mod.tree.body:
        if isinstance(s, (ast.Assign, ast.AugAssign)):
            for t in (s.targets if isinstance(s, ast.Assign) else [s.target]):
                if isinstance(t, ast.Attribute) and t.attr == "pytestmark" and isinstance(t.value, ast.Name) \
                        and t.value.id == fn.name:
                    own += list(s.value.elts) if isinstance(s.value, (ast.List, ast.Tuple)) else [s.value]
    classes = _lineage(mod.tree, cls)
    marks = (list(fn.decorator_list) + [d for c in classes for d in c.decorator_list]
             + [m for c in classes for m in _pytestmarks(c.body)[0]] + _pytestmarks(mod.tree.body)[0] + own)
    out = []
    while marks:   # MARKS = [pytest.mark.skip(...)]; pytestmark = MARKS: the name is read as the marks it holds
        m = marks.pop(0)
        bound = mod.named.get(m.id) if isinstance(m, ast.Name) else None
        if isinstance(bound, (ast.List, ast.Tuple)) and len(out) < 1000:
            marks = list(bound.elts) + marks
        else:
            out.append(m)
    return out


def _level(body):
    """The statements of one level (the module's, or a class's) and those inside its if, for, while, with, try and
    match blocks, never inside a def or a class: what runs when the module or the class is made."""
    for s in body:
        yield s
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            yield from _level(getattr(s, field, None) or [])
        for block in (getattr(s, "handlers", None) or []) + (getattr(s, "cases", None) or []):
            yield from _level(block.body)


def _pairs(target, value):
    """(each target, the value given to it) of an assignment, a tuple of targets matched to a tuple of values by place
    (a target whose value cannot be matched gets None, an unknown value)."""
    if isinstance(target, (ast.Tuple, ast.List)):
        values = value.elts if isinstance(value, (ast.Tuple, ast.List)) and len(value.elts) == len(target.elts) \
            else [None] * len(target.elts)
        for t, v in zip(target.elts, values):
            yield from _pairs(t, v)
    else:
        yield target, value


def _test_writes(body) -> tuple[list, dict]:
    """The values written to __test__ by one level's statements: (the level's own __test__, as a list of values;
    {a name: the values written to that name's __test__}). Read, in every block of the level: __test__ = v (an
    annotated or a tuple assignment too), (__test__ := v), globals()/vars()/locals()["__test__"] = v,
    globals().update({"__test__": v}) or update(__test__=v); and for a name X: X.__test__ = v,
    X.__dict__["__test__"] = v, setattr(X, "__test__", v). A setattr on an expression that is not a name (the module,
    as sys.modules[__name__]) counts as the level's own."""
    own, named = [], {}
    def key(node):   # "__test__" as a literal subscript key
        return isinstance(node, ast.Constant) and node.value == "__test__"
    for s in _level(body):
        pairs = []
        if isinstance(s, ast.Assign):
            pairs = [p for t in s.targets for p in _pairs(t, s.value)]
        elif isinstance(s, ast.AnnAssign) and s.value is not None:
            pairs = [(s.target, s.value)]
        elif isinstance(s, (ast.For, ast.AsyncFor)):   # for __test__ in [False]: each value it may be given
            items = s.iter.elts if isinstance(s.iter, (ast.List, ast.Tuple, ast.Set)) else [None]
            pairs = [p for v in items for p in _pairs(s.target, v)]
        for t, v in pairs:
            if isinstance(t, ast.Name) and t.id == "__test__":
                own.append(v)
            elif isinstance(t, ast.Attribute) and t.attr == "__test__" and isinstance(t.value, ast.Name):
                named.setdefault(t.value.id, []).append(v)
            elif isinstance(t, ast.Subscript) and key(t.slice):
                holder = t.value
                if isinstance(holder, ast.Call) and isinstance(holder.func, ast.Name) and \
                        holder.func.id in ("globals", "vars", "locals"):
                    own.append(v)
                elif isinstance(holder, ast.Attribute) and holder.attr == "__dict__" and isinstance(holder.value,
                                                                                                    ast.Name):
                    named.setdefault(holder.value.id, []).append(v)
        for n in ast.walk(s) if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else ():
            if isinstance(n, ast.NamedExpr) and n.target.id == "__test__":
                own.append(n.value)
            if not isinstance(n, ast.Call):
                continue
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "update" and isinstance(f.value, ast.Call) and \
                    isinstance(f.value.func, ast.Name) and f.value.func.id in ("globals", "vars", "locals"):
                for a in n.args:
                    if isinstance(a, ast.Dict):
                        own += [v for k, v in zip(a.keys, a.values) if k is not None and key(k)]
                own += [k.value for k in n.keywords if k.arg == "__test__"]
            if isinstance(f, ast.Name) and f.id == "setattr" and len(n.args) >= 3 and key(n.args[1]):
                target = n.args[0]
                if isinstance(target, ast.Name):
                    named.setdefault(target.id, []).append(n.args[2])
                else:
                    own.append(n.args[2])
    return own, named


def _off(values) -> bool:
    """Whether any of these values written to __test__ is a literal false (False, None, 0, "", an empty display, not
    True): only such a value is read as switching the test off. A value computed when it runs (bool(0), a name) is not
    read, and so never switches a test off here (no false refusal, and no claim to catch it)."""
    return any(v is not None and _const(v) is False for v in values)


def _switched_off(mod: Module, fn, cls=None) -> bool:
    """Whether __test__ is set to a literal false for this test, in the forms _test_writes reads: on the module; on the
    nearest of its class and the same-file classes it inherits from that writes __test__ at all (the nearest wins over
    a base's, as Python looks it up); or on the test itself, or on one of those classes, by name at module level."""
    own, named = _test_writes(mod.tree.body)
    if _off(own) or _off(named.get(fn.name, [])):
        return True
    for c in _lineage(mod.tree, cls):
        values = _test_writes(c.body)[0] + named.get(c.name, [])
        if values:
            return _off(values)
    return False


def _empty(values) -> bool:
    """A literal empty list of cases: [], (), list() or tuple()."""
    if isinstance(values, (ast.List, ast.Tuple)):
        return not values.elts
    return isinstance(values, ast.Call) and isinstance(values.func, ast.Name) and values.func.id in ("list", "tuple") \
        and not values.args and not values.keywords


def _class_trouble(tree: ast.Module, cls, seen=()) -> str | None:
    """Why pytest does not collect a Test* class: an __init__ or a __new__ of its own, or one it inherits from a class
    of the same file."""
    if cls is None or cls.name in seen:
        return None
    if any(isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name in ("__init__", "__new__")
           for s in cls.body):
        return "its class has an __init__ or a __new__ (its own or a same-file base's), so pytest does not collect it"
    for b in cls.bases:
        base = next((s for s in tree.body if isinstance(s, ast.ClassDef) and isinstance(b, ast.Name)
                     and s.name == b.id), None)
        why = _class_trouble(tree, base, seen + (cls.name,))
        if why:
            return why
    return None


def usefixtures(mod: Module, fn, cls=None) -> set:
    """The fixtures a test's usefixtures marks name, as texts."""
    return {a.value for d in _marks(mod, fn, cls) if isinstance(d, ast.Call) and mod.is_(d, USEFIXTURES)
            for a in d.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}


def _check(mod: Module, s, consts: set) -> bool:
    """Whether a statement is a check that can fail: an assert of an expression without one fixed value, or a
    pytest.raises that checks something: as a with (`with pytest.raises(E):`) or called with what to run
    (`pytest.raises(E, f, x)`); a bare `pytest.raises(E)` checks nothing, and one of AssertionError, Exception or
    BaseException is no check (_broad_raises)."""
    if isinstance(s, ast.Assert):
        return not _fixed(s.test, consts)
    if isinstance(s, (ast.With, ast.AsyncWith)):
        return any(mod.is_(i.context_expr, RAISES) and not _broad_raises(mod, i.context_expr) for i in s.items)
    return any(isinstance(n, ast.Call) and mod.is_(n, RAISES) and len(n.args) >= 2 and not _broad_raises(mod, n)
               for n in _expressions(s))


def _judge(mod: Module, fn, cls=None) -> tuple[str | None, bool]:
    """(why the test cannot hold a promise, or None; whether it can skip itself), from its source alone. The patterns
    it recognises are the ones the module's docstring lists; nothing else."""
    if _switched_off(mod, fn, cls):
        return "pytest is told not to collect it (__test__ is set false)", False
    why = _class_trouble(mod.tree, cls)
    if why:
        return why, False
    if any(isinstance(n, ast.Call) and mod.is_(n, EXIT) for n in ast.walk(mod.tree)):
        return "its file calls pytest.exit, which can end the run before it", False
    if isinstance(fn, ast.AsyncFunctionDef):
        return "it is an async def, which pytest runs only with a plug-in", False
    if any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in _own_nodes(fn) if n is not fn):
        return "it yields, and pytest does not run a test that is a generator", False
    marks = _marks(mod, fn, cls)
    if any(mod.is_(d, SKIP_MARKS) for d in marks):
        return "it is marked to skip or to fail outright", False
    can_skip = any(mod.is_(d, MAYBE_MARKS) for d in marks)
    for d in fn.decorator_list:   # parametrized over a literal empty list of cases: it never runs
        if isinstance(d, ast.Call) and mod.is_(d, PARAMETRIZE):
            values = d.args[1] if len(d.args) > 1 else next((k.value for k in d.keywords if k.arg == "argvalues"), None)
            if _empty(values):
                return "it is parametrized over no cases, so it never runs", False
            for case in ast.walk(values) if values is not None else ():   # a case with its own skip mark
                if isinstance(case, ast.Call) and mod.is_(case, PARAM) and any(
                        k.arg == "marks" and any(mod.is_(n, SKIP_MARKS | MAYBE_MARKS) for n in ast.walk(k.value)
                                                 if isinstance(n, (ast.Call, ast.Attribute)))
                        for k in case.keywords):
                    can_skip = True
    for d in fn.decorator_list:   # a decorator of its own file that applies a mark, or skips
        name = (d.func if isinstance(d, ast.Call) else d)
        own = mod.defs.get(name.id) if isinstance(name, ast.Name) else None
        if own is not None:
            if any(mod.is_(n, SKIP_MARKS) for n in ast.walk(own) if isinstance(n, (ast.Call, ast.Attribute))):
                return "a decorator of its own file marks it to skip or to fail outright", False
            can_skip = can_skip or _mentions_skip(mod, own) or any(
                mod.is_(n, MAYBE_MARKS) for n in ast.walk(own) if isinstance(n, (ast.Call, ast.Attribute)))
    for s in mod.tree.body:   # a module-level skip: at the top level always, under an if or a try only sometimes
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if _always(mod, s):
            return "its module skips itself at its top level", False
        can_skip = can_skip or _mentions_skip(mod, s)
    for s, _ in _reachable(fn.body):   # a skip in the test's own block, not under a branch: it runs every time
        if s in fn.body and _always(mod, s):
            return "it skips itself at its own top level, every time it reaches it", False
    can_skip = can_skip or _mentions_skip(mod, fn)
    consts = _literal_names(fn)
    checks = [s for s, swallowed in _reachable(fn.body, mod) if not swallowed and _check(mod, s, consts)]
    if not checks:
        return ("it holds no assert of something that can be false, and no pytest.raises, that can run and is not "
                "caught"), can_skip
    for s in fn.body:   # a return before its first check: unconditional, nothing is checked; under a branch, sometimes
        if any(c is s or c in ast.walk(s) for c in checks):
            break
        if isinstance(s, ast.Return):
            return "it returns before its first check, every time", False
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue   # a nested def's return is its own
        if any(isinstance(n, ast.Return) for n in _own_nodes(s)):
            can_skip = True
    return None, can_skip


def _own_nodes(s):
    """Every node of a statement, not entering a nested def, class or lambda."""
    stack = [s]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(c for c in ast.iter_child_nodes(n)
                     if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)))


def _skips(body: str) -> str:
    """A property's Skips: paragraphs: each from its Skips: line up to the next list line or blank line."""
    out, inside = [], False
    for line in body.split("\n"):
        if SKIPS.match(line):
            inside = True
        elif not line.strip() or line.lstrip().startswith("- "):
            inside = False
        if inside:
            out.append(line)
    return "\n".join(out)


def _collected(root: Path, files: set[str]) -> set[str]:
    """pytest's own node ids for these files, collected in a second process."""
    run = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                          f"--rootdir={root}", *sorted(files)], cwd=str(root), capture_output=True, text=True,
                         timeout=300)
    return {line.strip() for line in run.stdout.splitlines() if "::" in line}


def trouble(text: str, root: Path) -> list[str]:
    """Everything wrong with the floor's text, judged against the tests under `root`."""
    listed, out = items(text)
    if not listed:
        out.append("no numbered property")
    parsed, cases, helpers = {}, [], {}
    for want, (n, promise, body) in enumerate(listed, 1):
        if n != want:
            out.append(f"property {n} is numbered out of order (expected {want})")
        nodes, errors = _named(body)
        out += [f"property {n}: {e}" for e in errors]
        if not nodes:
            out.append(f"property {n} ({promise[:40]}) names no test")
        skips_line = _skips(body)
        for node, file, rest in nodes:
            path = root / file
            if not path.is_file():
                out.append(f"{node}: no such test file")
                continue
            if file not in parsed:
                parsed[file] = Module(ast.parse(path.read_text(encoding="utf-8")))
            parts = rest.split("[")[0].split("::")[1:]
            fn, cls, why = _target(parsed[file].tree, parts)
            if fn is None:
                out.append(f"{node}: {why} in {file}")
                continue
            why, can_skip = _judge(parsed[file], fn, cls)
            if file not in helpers:   # the helpers and fixtures of its file and of the conftests above it
                mods = [parsed[file]] + _conftests(root, file)
                helpers[file] = (_skippers(mods), _no_cases(mods))
            asks = _reaches(fn) | usefixtures(parsed[file], fn, cls)
            if not why and asks & helpers[file][1]:
                why = "it requests a fixture parametrized over no cases, so it never runs"
            can_skip = can_skip or bool(asks & helpers[file][0])   # a skip it reaches through a helper or fixture
            if why:
                out.append(f"{node}: {why}")
            elif can_skip and f"`{node}`" not in skips_line:
                out.append(f"{node} can skip itself, and property {n} has no Skips: line naming it")
            if "[" in rest:
                cases.append((node, file))
    if cases:
        have = _collected(root, {f for _, f in cases})
        out += [f"{node}: pytest collects no such case" for node, _ in cases if node not in have]
    return out


@pytest.fixture
def floor():
    if not FLOOR.is_file():
        pytest.skip("docs/security-floor.md is not beside the package (installed from a wheel)")
    return FLOOR.read_text(encoding="utf-8")


def test_every_test_the_floor_names_exists_and_can_fail(floor):   # must pass
    listed, _ = items(floor)
    assert len(listed) >= 10 and sum(len(_named(body)[0]) for _, _, body in listed) >= 20   # the parse sees the list
    assert trouble(floor, ROOT) == []


# The kit: test files written for the two arms below. Each must-pass test checks something that can be false.
KIT = '''import pytest


@pytest.mark.skip(reason="never")
def test_skipped():
    assert False


@pytest.mark.xfail
def test_xfailed():
    assert False


def test_empty():
    pass


def test_shadowed():
    assert False


test_shadowed = None


def test_real():
    assert int("1") == 1


def test_raises():
    with pytest.raises(ValueError):
        int("x")


@pytest.mark.skipif(True, reason="not here")
def test_may_skip():
    assert int("1") == 1


def test_skips_in_body():
    try:
        int("1")
    except ValueError:
        pytest.skip("no link here")
    assert int("1") == 1


@pytest.mark.parametrize("case", ["one", "two"])
def test_cases(case):
    assert case


class TestGroup:
    def test_inside(self):
        assert int("1") == 1


def helper():
    assert int("1") == 1


def outer():
    def test_nested():
        assert int("1") == 1
'''

MARKED = '''import pytest

never = pytest.mark.skip(reason="never")
maybe = pytest.mark.skipif(True, reason="not here")
pytestmark = [pytest.mark.filterwarnings("ignore")]


@never
def test_named_skip():
    assert False


@maybe
def test_named_skipif():
    assert int("1") == 1


@pytest.mark.xfail
class TestFailing:
    def test_in_it(self):
        assert False
'''

# The second attack's twelve: each skips or can never fail, by a form the first checker did not read.
HOLES = {
    "test_alias.py": 'import pytest as pt\n\n\n@pt.mark.skip(reason="x")\ndef test_a():\n    assert False\n',
    "test_frommark.py": 'from pytest import mark, skip\n\n\n@mark.skip\ndef test_b():\n    assert False\n\n\n'
                        'def test_c():\n    skip("always")\n    assert False\n',
    "test_classmark.py": 'import pytest\n\n\nclass TestK:\n    pytestmark = pytest.mark.skip(reason="x")\n\n'
                         '    def test_d(self):\n        assert False\n',
    "test_notest.py": '__test__ = False\n\n\ndef test_e():\n    assert False\n',
    "test_modskip.py": 'import pytest\n\npytest.skip("whole module", allow_module_level=True)\n\n\n'
                       'def test_f():\n    assert False\n',
    "test_vacuous.py": 'def test_g():\n    if False:\n        assert False\n\n\ndef test_h():\n    def never():\n'
                       '        assert False\n\n\ndef test_i():\n    assert True\n\n\ndef test_j():\n    return\n'
                       '    assert False\n',
    "test_unittest.py": 'import unittest\n\n\n@unittest.skip("x")\ndef test_k():\n    assert False\n',
    "test_aug.py": 'import pytest\n\npytestmark = []\npytestmark += [pytest.mark.skip(reason="x")]\n\n\n'
                   'def test_l():\n    assert False\n',
    "test_whole.py": 'import pytest\n\npytestmark = pytest.mark.skip(reason="the whole file")\n\n\n'
                     'def test_any():\n    assert False\n',
    "test_more.py": 'import pytest\nfrom unittest import skip as later\n\n\n@later("x")\ndef test_m():\n'
                    '    assert False\n\n\ndef test_n():\n    assert (1 == 2, "a tuple is always true")\n\n\n'
                    'def test_o():\n    while False:\n        assert False\n\n\ndef test_p():\n'
                    '    raise RuntimeError("never gets to the check")\n    assert False\n\n\n'
                    'def test_q():\n    assert not 0\n\n\ndef test_r():\n    test_r.__test__ = False\n'
                    '    pytest.importorskip("no_such_module_anywhere")\n    assert int("1") == 1\n\n\n'
                    'def test_s():\n    assert False\n\n\ntest_s.__test__ = False\n',
    "test_through.py": 'import pytest\n\n\ndef make_link():\n    try:\n        int("1")\n    except ValueError:\n'
                       '        pytest.skip("no link")\n\n\ndef plant():\n    make_link()\n\n\n'
                       'def test_t():\n    plant()\n    assert int("1") == 1\n\n\n'
                       'def test_u(needs_link):\n    assert int("1") == 1\n',
    "conftest.py": 'import pytest\n\n\n@pytest.fixture(name="needs_link")\ndef _link():\n'
                   '    if int("1") != 1:\n        pytest.skip("no link")\n    return 1\n',
    # the third attack's cheap holes, each with a must-pass partner (test_y*) where one can be written
    "test_cheap.py": '''import contextlib
import pytest


@pytest.mark.parametrize("x", [])
def test_v(x):
    assert x


class TestInit:
    def __init__(self):
        self.x = 1

    def test_w(self):
        assert self.x == 2


def test_x1():
    assert 1 == 1


def test_x2():
    n = 3
    assert n == 3


def test_x3():
    try:
        assert int("1") == 2
    except AssertionError:
        pass


def test_x4():
    with contextlib.suppress(AssertionError):
        assert int("1") == 2


def test_x5():
    return
    assert int("1") == 2


def test_x6():
    if int("1") == 1:
        return
    assert int("1") == 2


def never(f):
    return pytest.mark.skip(reason="x")(f)


@never
def test_x7():
    assert int("1") == 2


@pytest.fixture
def gone():
    if int("1") == 1:
        pytest.skip("not here")


@pytest.mark.usefixtures("gone")
def test_x8():
    assert int("1") == 2


def test_x9():
    import pytest as q
    q.skip("always")
    assert int("1") == 2


async def test_z1():
    assert int("1") == 2


def test_z2():
    yield
    assert int("1") == 2


def test_y1():
    n = int("3")
    for m in [3]:
        assert n == m


def test_y2():
    try:
        assert int("1") == 1
    except KeyError:
        pass
''',
    # the fourth attack's
    "test_fourth.py": '''import pytest


def test_f1():
    pytest.raises(ValueError)


def test_f2():
    assert int("1") == 2 or True


def test_f3():
    with pytest.raises(AssertionError):
        assert int("1") == 2


def test_f4():
    with pytest.raises(Exception):
        assert int("1") == 2


@pytest.mark.parametrize("x", [pytest.param(1, marks=pytest.mark.skip(reason="x"))])
def test_f5(x):
    assert int("1") == x


@pytest.mark.parametrize("x", list())
def test_f6(x):
    assert x


def test_f7():
    assert int("1") == 2


test_f7.pytestmark = [pytest.mark.skip(reason="x")]


def test_f8():
    assert int("1") == 2


del test_f8


def test_f9():
    assert int("1") == 2


globals()["test_f9"] = None


class Base:
    def __init__(self):
        self.x = 1


class TestInherits(Base):
    def test_f10(self):
        assert int("1") == 2


class TestNew:
    def __new__(cls):
        return super().__new__(cls)

    def test_f11(self):
        assert int("1") == 2


@pytest.fixture(params=[])
def nothing(request):
    return request.param


def test_f12(nothing):
    assert int("1") == nothing


def test_g1():
    assert pytest.raises(ValueError, int, "x")


def test_g2():
    with pytest.raises(ValueError):
        int("x")
''',
    "test_exits.py": 'import pytest\n\n\ndef test_e1():\n    assert int("1") == 1\n\n\n'
                     'def teardown_module():\n    pytest.exit("stop")\n',
    # the fifth attack's
    "test_fifth_names.py": 'import pytest\n\nMARKS = [pytest.mark.skip(reason="x")]\npytestmark = MARKS\n\n\n'
                           'def test_h1():\n    assert int("1") == 2\n',
    "test_fifth_bases.py": '''import pytest


class Marked:
    pytestmark = pytest.mark.skip(reason="x")


class TestA(Marked):
    def test_h2(self):
        assert int("1") == 2


class Off:
    __test__ = False


class TestB(Off):
    def test_h3(self):
        assert int("1") == 2


@pytest.mark.skip(reason="x")
class Decorated:
    pass


class TestC(Decorated):
    def test_h4(self):
        assert int("1") == 2


class Plain:
    pass


class TestD(Plain):
    def test_h5(self):
        assert int("1") == 1
''',
    "test_fifth_globals.py": 'globals()["__test__"] = False\n\n\ndef test_h6():\n    assert int("1") == 2\n',
    "test_fifth_setattr.py": 'def test_h7():\n    assert int("1") == 2\n\n\ndef helper():\n    return 1\n\n\n'
                             'def test_h8():\n    assert int("1") == 1\n\n\n'
                             'setattr(test_h7, "__test__", False)\nsetattr(helper, "__test__", False)\n',
    # the sixth attack's: every form of a module's __test__ the check reads
    "test_six_if.py": 'import sys\n\nif sys.platform:\n    __test__ = False\n\n\ndef test_i1():\n'
                      '    assert int("1") == 2\n',
    "test_six_tuple.py": '__test__, other = False, 1\n\n\ndef test_i2():\n    assert int("1") == 2\n',
    "test_six_walrus.py": 'if (__test__ := False) is None:\n    pass\n\n\ndef test_i3():\n    assert int("1") == 2\n',
    "test_six_update.py": 'globals().update({"__test__": False})\n\n\ndef test_i4():\n    assert int("1") == 2\n',
    "test_six_dict.py": 'def test_i5():\n    assert int("1") == 2\n\n\ntest_i5.__dict__["__test__"] = False\n',
    "test_six_for.py": 'for __test__ in [False]:\n    pass\n\n\ndef test_i8():\n    assert int("1") == 2\n',
    "test_six_classes.py": '''class Off:
    __test__ = False


class TestNearest(Off):
    __test__ = True

    def test_i6(self):
        assert int("1") == 1


class Helper:
    pass


setattr(Helper, "__test__", False)
__test__ = bool(1)


def test_i7():
    assert int("1") == 1
''',
}
NOT_RUN = "marked to skip or to fail outright"
NO_CHECK = "no assert of something that can be false"


@pytest.fixture
def kit(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text(KIT, encoding="utf-8")
    (tmp_path / "tests" / "test_marked.py").write_text(MARKED, encoding="utf-8")
    for name, text in HOLES.items():
        (tmp_path / "tests" / name).write_text(text, encoding="utf-8")
    return tmp_path


GOOD = ("Preamble naming tests/test_security_floor.py, which is not a property.\n\n"
        "1. **Held.**\n"
        "   - `tests/test_x.py::test_real`\n"
        "   - `tests/test_x.py::test_raises`\n"
        "   - `tests/test_x.py::TestGroup::test_inside`\n"
        "   - `tests/test_cheap.py::test_y1`\n"
        "   - `tests/test_cheap.py::test_y2`\n"
        "   - `tests/test_fourth.py::test_g1`\n"
        "   - `tests/test_fourth.py::test_g2`\n"
        "   - `tests/test_fifth_bases.py::TestD::test_h5`\n"
        "   - `tests/test_fifth_setattr.py::test_h8`\n"
        "   - `tests/test_six_classes.py::TestNearest::test_i6`\n"   # the nearest class's __test__ = True wins
        "   - `tests/test_six_classes.py::test_i7`\n"                # setattr(Helper, ...) and bool(1): not read

        "   - `tests/test_x.py::test_cases`\n"
        "   - `tests/test_x.py::test_cases[two]`\n"
        "2. **Held, on a test that may skip.**\n"
        "   - `tests/test_x.py::test_may_skip`\n"
        "   - `tests/test_x.py::test_skips_in_body`\n"
        "   - `tests/test_more.py::test_r`\n"
        "   - `tests/test_through.py::test_t`\n"
        "   - `tests/test_through.py::test_u`\n"
        "   Skips: `tests/test_x.py::test_may_skip`, `tests/test_x.py::test_skips_in_body`,\n"
        "   `tests/test_more.py::test_r`, `tests/test_through.py::test_t` and `tests/test_through.py::test_u`, where\n"
        "   they cannot run.\n")


def test_a_floor_whose_every_test_can_fail_passes(kit):   # must pass: the partner of the arm below
    assert trouble(GOOD, kit) == []


def one(node):
    return f"1. **A.**\n   - `{node}`\n"


@pytest.mark.parametrize("bad, said", [
    (one("tests/test_x.py::test_skipped"), NOT_RUN),
    (one("tests/test_x.py::test_xfailed"), NOT_RUN),
    (one("tests/test_x.py::test_empty"), NO_CHECK),
    (one("tests/test_x.py::test_shadowed"), "bound more than once"),
    (one("tests/test_x.py::test_gone"), "no such test"),
    (one("tests/test_x.py::test_cases[three]"), "pytest collects no such case"),
    (one("tests/test_x.py::test_real") + "   - `tests/test_gone.py::test_real`\n", "no such test file"),
    (one("tests/test_x.py::test_real") + "   - `tests/test_x.py`\n", "not a node id"),
    (one("tests/test_x.py::test_real") + "   - `./tests/test_x.py::test_real`\n", "not a node id"),
    (one("tests/test_x.py::test_real") + "   - `tests\\test_x.py::test_real`\n", "not a node id"),
    (one("tests/test_x.py::test_real") + "   - tests/test_x.py::test_gone\n", "without backticks"),
    (one("tests/test_x.py::helper"), "not a name pytest collects"),
    (one("tests/test_x.py::test_nested"), "no such test"),
    (one("tests/test_x.py::Group::test_inside"), "no class Test*"),
    (one("tests/test_x.py::test_may_skip"), "no Skips: line"),
    (one("tests/test_x.py::test_skips_in_body"), "no Skips: line"),
    (one("tests/test_more.py::test_r"), "no Skips: line"),
    (one("tests/test_marked.py::test_named_skip"), NOT_RUN),
    (one("tests/test_marked.py::test_named_skipif"), "no Skips: line"),
    (one("tests/test_marked.py::TestFailing::test_in_it"), NOT_RUN),
    (one("tests/test_whole.py::test_any"), NOT_RUN),
    # the second attack's twelve, and four more of the same kinds
    (one("tests/test_alias.py::test_a"), NOT_RUN),
    (one("tests/test_frommark.py::test_b"), NOT_RUN),
    (one("tests/test_frommark.py::test_c"), "skips itself at its own top level"),
    (one("tests/test_classmark.py::TestK::test_d"), NOT_RUN),
    (one("tests/test_notest.py::test_e"), "__test__ is set false"),
    (one("tests/test_modskip.py::test_f"), "its module skips itself"),
    (one("tests/test_vacuous.py::test_g"), NO_CHECK),
    (one("tests/test_vacuous.py::test_h"), NO_CHECK),
    (one("tests/test_vacuous.py::test_i"), NO_CHECK),
    (one("tests/test_vacuous.py::test_j"), NO_CHECK),
    (one("tests/test_unittest.py::test_k"), NOT_RUN),
    (one("tests/test_aug.py::test_l"), NOT_RUN),
    (one("tests/test_more.py::test_m"), NOT_RUN),
    (one("tests/test_more.py::test_n"), NO_CHECK),
    (one("tests/test_more.py::test_o"), NO_CHECK),
    (one("tests/test_more.py::test_p"), NO_CHECK),
    (one("tests/test_more.py::test_q"), NO_CHECK),
    (one("tests/test_more.py::test_s"), "__test__ is set false"),
    (one("tests/test_through.py::test_t"), "no Skips: line"),      # through a helper that calls a helper that skips
    (one("tests/test_through.py::test_u"), "no Skips: line"),      # through a conftest fixture, by its name=
    # the third attack's
    (one("tests/test_cheap.py::test_v"), "parametrized over no cases"),
    (one("tests/test_cheap.py::TestInit::test_w"), "has an __init__"),
    (one("tests/test_cheap.py::test_x1"), NO_CHECK),
    (one("tests/test_cheap.py::test_x2"), NO_CHECK),
    (one("tests/test_cheap.py::test_x3"), NO_CHECK),
    (one("tests/test_cheap.py::test_x4"), NO_CHECK),
    (one("tests/test_cheap.py::test_x5"), NO_CHECK),
    (one("tests/test_cheap.py::test_x6"), "no Skips: line"),
    (one("tests/test_cheap.py::test_x7"), "a decorator of its own file"),
    (one("tests/test_cheap.py::test_x8"), "no Skips: line"),
    (one("tests/test_cheap.py::test_x9"), "skips itself at its own top level"),
    (one("tests/test_cheap.py::test_z1"), "async def"),
    (one("tests/test_cheap.py::test_z2"), "yields"),
    # the fourth attack's
    (one("tests/test_fourth.py::test_f1"), NO_CHECK),             # a bare pytest.raises(E) checks nothing
    (one("tests/test_fourth.py::test_f2"), NO_CHECK),             # x or True
    (one("tests/test_fourth.py::test_f3"), NO_CHECK),             # raises(AssertionError) swallows the assert
    (one("tests/test_fourth.py::test_f4"), NO_CHECK),
    (one("tests/test_fourth.py::test_f5"), "no Skips: line"),     # a case marked to skip
    (one("tests/test_fourth.py::test_f6"), "parametrized over no cases"),
    (one("tests/test_fourth.py::test_f7"), NOT_RUN),              # test_x.pytestmark = skip
    (one("tests/test_fourth.py::test_f8"), "bound more than once"),   # del test_x
    (one("tests/test_fourth.py::test_f9"), "bound more than once"),   # globals()["test_x"] = None
    (one("tests/test_fourth.py::TestInherits::test_f10"), "__init__ or a __new__"),
    (one("tests/test_fourth.py::TestNew::test_f11"), "__init__ or a __new__"),
    (one("tests/test_exits.py::test_e1"), "pytest.exit"),
    (one("tests/test_fourth.py::test_f12"), "fixture parametrized over no cases"),
    # the fifth attack's
    (one("tests/test_fifth_names.py::test_h1"), NOT_RUN),                     # pytestmark = a name holding marks
    (one("tests/test_fifth_bases.py::TestA::test_h2"), NOT_RUN),              # a base class's pytestmark
    (one("tests/test_fifth_bases.py::TestB::test_h3"), "__test__ is set false"),   # a base class's __test__
    (one("tests/test_fifth_bases.py::TestC::test_h4"), NOT_RUN),              # a base class's decorator
    (one("tests/test_fifth_globals.py::test_h6"), "__test__ is set false"),   # globals()["__test__"] = False
    (one("tests/test_fifth_setattr.py::test_h7"), "__test__ is set false"),   # setattr(test_x, "__test__", False)
    # the sixth attack's
    (one("tests/test_six_if.py::test_i1"), "__test__ is set false"),          # under an if
    (one("tests/test_six_tuple.py::test_i2"), "__test__ is set false"),       # a tuple target
    (one("tests/test_six_walrus.py::test_i3"), "__test__ is set false"),      # a walrus
    (one("tests/test_six_update.py::test_i4"), "__test__ is set false"),      # globals().update(...)
    (one("tests/test_six_dict.py::test_i5"), "__test__ is set false"),        # test_x.__dict__["__test__"]
    (one("tests/test_six_for.py::test_i8"), "__test__ is set false"),         # a for target
    # the headings
    (one("tests/test_x.py::test_real") + " 2. **B, held by nothing.**\n   Why.\n", "numbered like a property"),
    (one("tests/test_x.py::test_real") + "2.  **B, held by nothing.**\n", "numbered like a property"),
    (one("tests/test_x.py::test_real") + "2) **B, held by nothing.**\n", "numbered like a property"),
    (one("tests/test_x.py::test_real") + "2. B, held by nothing.\n", "numbered like a property"),
    (one("tests/test_x.py::test_real") + "2. **B, held by nothing.**\n   Why.\n", "names no test"),
    (one("tests/test_x.py::test_real") + "3. **C.**\n   - `tests/test_x.py::test_real`\n", "out of order"),
    ("Nothing is promised here.\n", "no numbered property"),
])
def test_a_floor_that_names_a_test_that_cannot_fail_or_none_is_refused(kit, bad, said):   # must refuse
    found = trouble(bad, kit)
    assert any(said in t for t in found), found


