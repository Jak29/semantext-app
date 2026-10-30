"""The seventh independent attack on the Plug-ins tab. The rule: ONE function renders every console line around a yes
(pluginpage.ascii_only, which plugincmd.shown() is), one to one and deleting nothing; entries are compared as written,
never by Python's ==; the keys the closures are read from are refused at load as on the page; rows are counted at the
console's own width; a record number is ASCII digits alone; and the review code covers every line confirm prints.
Each probe is a must-refuse test here, beside a must-pass partner."""
from __future__ import annotations

import ast
import itertools
import json
from pathlib import Path

import pytest

from semantext import plugincmd, pluginpage, registry
from semantext.pluginpage import console_width as REAL_WIDTH   # conftest holds width() at 100, never this
from test_plugins_tab import KEY, cfg, world, write_cfg  # noqa: F401  (fixtures)
from plugin_fakes import DECLARED

LISTED = {"plugins": {KEY: {"reads": ["x"], "settings": [
    {"key": "tickets", "type": "path", "title": "Tickets file"}, {"key": "project", "type": "text", "title": "Project"},
    {"key": "extra", "type": "paths", "title": "More folders"}, {"key": "rules", "type": "list", "title": "Rules"}]}}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    pluginpage._RECENT.clear()
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    yield
    pluginpage._RECENT.clear()


def _propose(world, given):
    pluginpage._RECENT.clear()
    with pytest.raises(pluginpage.Proposed) as e:
        pluginpage.change(world.home, KEY, given)
    return e.value.proposal


def _said(fn, world, name, **kw):
    said = []
    fn(name, world.home, said.append, ask=lambda p: (said.append(p), KEY)[1], **kw)
    return said


def _before_yes(said):
    return said[:next(i for i, s in enumerate(said) if s.startswith("Having seen the above"))]


def _ascii(lines):
    return all(" " <= c <= "~" for s in lines for c in s)


def _set(world, **values):
    d = cfg(world)
    d.update(values)
    write_cfg(world.cfg, d)


# ---- 1. one renderer for every line around a yes --------------------------------------------------------------------
def test_1_a_package_name_and_version_are_rendered_before_the_yes(world):   # must refuse them raw
    world.offer(name="semantext-jirа", version="0.3١")   # a Cyrillic a, an Arabic-Indic one
    said = _said(plugincmd._enable, world, KEY)
    head = _before_yes(said)
    assert _ascii(said) and "  package: semantext-jir\\u0430  version: 0.3\\u0661" in head


def test_1_a_plain_package_name_is_printed_as_it_is(world):   # must pass
    world.offer()
    head = _before_yes(_said(plugincmd._enable, world, KEY))
    assert "  package: semantext-jira  version: 0.3" in head


def test_1_a_declaration_problem_is_rendered_before_the_yes(world):   # must refuse it raw
    world.offer(declared={"plugins": {KEY: {"reads": ["x"], "settings": [
        {"key": "tickets", "type": "path", "tіtle": "x"}]}}})            # a Cyrillic i in a field's name
    said = _said(plugincmd._enable, world, KEY)
    problem = [s for s in _before_yes(said) if s.startswith("Its declaration cannot be used")]
    assert problem and _ascii(said) and "\\u0456" in problem[0]


def test_1_a_refusal_around_a_yes_is_rendered(world, monkeypatch):   # must refuse a raw path in a Refused
    world.offer()
    n = _propose(world, {"project": "beta"})
    f = pluginpage.proposals_file(world.home)
    store = json.loads(f.read_text(encoding="utf-8"))
    store["open"][str(n)]["sources_file"] = str(world.tmp / "Pаth" / "sources.json")
    f.write_text(json.dumps(store), encoding="utf-8")
    with pytest.raises(pluginpage.Refused) as e:
        plugincmd.run(world.home, "confirm", str(n), [].append)
    assert "P\\u0430th" in str(e.value) and _ascii([str(e.value)])


def test_1_a_plain_refusal_is_said_as_it_is(world):   # must pass
    world.offer()
    with pytest.raises(pluginpage.Refused) as e:
        plugincmd.run(world.home, "confirm", "41", [].append)
    assert str(e.value) == "there is no open proposal 41: it was confirmed, expired, or never made"


def test_1_the_labels_are_rendered(world):   # must refuse a raw label
    world.offer()
    n = _propose(world, {"project": "beta"})
    f = pluginpage.proposals_file(world.home)
    store = json.loads(f.read_text(encoding="utf-8"))
    store["open"][str(n)]["label"] = "narrows‮"
    f.write_text(json.dumps(store), encoding="utf-8")
    review = _before_yes(_said(plugincmd._confirm, world, str(n)))
    assert "Labelled when proposed: narrows\\u202e." in review and _ascii(review)
    assert any(s.startswith("As things stand now it ") for s in review)


def test_1_shown_never_deletes():   # must refuse a deletion; must pass a rendered line as it is
    assert plugincmd.shown("a‮b\x1b[2Jc") == "a\\u202eb\\u001b[2Jc"
    line = pluginpage._line("  already rendered \\u0441")
    assert plugincmd.shown(line) is line and plugincmd.shown(plugincmd.shown("\\")) == "\\\\"   # never twice
    with pytest.raises(ValueError):
        pluginpage._line("not rendered с")


RENDERERS = ("shown", "_row", "_indented", "_said")   # shown, and what renders each part with it
PRINTERS = ("out", "ask")


def _rendered(arg) -> bool:
    if isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name) and arg.func.id in RENDERERS:
        return True
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, ast.Add):   # "semantext: " + _said(...)
        return all(isinstance(x, ast.Constant) and type(x.value) is str or _rendered(x) for x in (arg.left, arg.right))
    return False


def _bypasses(source: str) -> list[str]:
    """Every way a line could reach the console without the renderer (round 8: wider than out/ask): a call to out or
    ask whose argument is not rendered; any print(), any .write() (sys.stdout, sys.stderr, a file), any logging
    call; and out or ask passed on under another name (say = out; partial(out, ...)), which the first rule would not
    see."""
    bad = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else None
            if name in PRINTERS or name == "print":
                if not (node.args and _rendered(node.args[0])):
                    bad.append(f"line {node.lineno}: {ast.unparse(node)}")
            elif isinstance(f, ast.Attribute) and (f.attr == "write" or (isinstance(f.value, ast.Name)
                                                                          and f.value.id in ("logging", "log", "logger"))):
                bad.append(f"line {node.lineno}: {ast.unparse(node)}")
            elif any(isinstance(a, ast.Name) and a.id in PRINTERS for a in node.args) and name not in (
                    "_list", "_enable", "_confirm", "_show", "_disable", "_run"):   # handed on, under another name
                bad.append(f"line {node.lineno}: {ast.unparse(node)}")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(node.value, ast.Name) and node.value.id in PRINTERS and not all(
                    isinstance(t, ast.Name) and t.id == node.value.id for t in targets):
                bad.append(f"line {node.lineno}: {ast.unparse(node)}")
    return bad


def _plugins_path_of_cli() -> str:
    """The functions of cli.py the `plugins` command runs through: cmd_plugins, and _said, which renders its errors."""
    from semantext import cli
    tree = ast.parse(Path(cli.__file__).read_text(encoding="utf-8"))
    return "\n".join(ast.unparse(n) for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name in ("cmd_plugins", "_said"))


def test_1_no_line_plugincmd_prints_bypasses_the_renderer():   # must refuse any bypass
    source = Path(plugincmd.__file__).read_text(encoding="utf-8")
    assert _bypasses(source) == [] and _bypasses(_plugins_path_of_cli()) == []
    assert "def cmd_plugins" in _plugins_path_of_cli() and "def _said" in _plugins_path_of_cli()


def test_1_the_scan_finds_a_bypass():   # must pass: the scan can fail, every way
    assert len(_bypasses('out(f"{x} is on")\nask("type it: ")\nout(shown(x))\n')) == 2
    found = _bypasses("print(x)\nsys.stdout.write(x)\nsys.stderr.write(x)\nsay = out\nlogging.warning(x)\n"
                      "functools.partial(out, 1)\nout(shown(x))\nprint('semantext: ' + _said(a, e, t))\n")
    assert len(found) == 6, found


# ---- 2. the keys the closures are read from are refused at load -----------------------------------------------------
class _Peek:
    kind, name, title = "source", "tickets", "Tickets"
    keys, needs = ("privacy",), ("privacy",)

    def read(self, config):
        return {"off": False, "problems": [], "rows": []}


def _closures_in(world, key="privacy"):
    d = cfg(world)
    d.pop("closed", None)
    d.update({"closures_file": str(world.cfg), "closures_key": key, key: [str(world.tmp / "secret")]})
    write_cfg(world.cfg, d)


@pytest.mark.parametrize("named", ["privacy", "Privacy", "PRIVACY"])
def test_2_a_plug_in_whose_keys_name_the_closures_key_is_not_loaded(world, named):   # must refuse
    _closures_in(world, named)
    world.offer(make=_Peek, declared=None, on=True)
    from semantext.sources import view
    reg = registry.load_enabled(view.BUILT_IN, world.home)
    assert reg.get("source", "tickets") is None or reg.get("source", "tickets").builtin
    assert any(p.get("kind") == "reserved key" for p in reg.problems)


def test_2_the_names_key_is_refused_too(world):   # must refuse
    d = cfg(world)
    d["closures_names_key"] = "people"
    write_cfg(world.cfg, d)
    assert "people" in pluginpage.reserved_keys(world.home)
    with pytest.raises(pluginpage.Refused, match="of your closures"):
        pluginpage._no_reserved(world.home, ["People"])


def test_2_a_plug_in_whose_keys_are_its_own_loads(world):   # must pass
    _closures_in(world)

    class Own(_Peek):
        keys, needs = ("tickets",), ("tickets",)
    world.offer(make=Own, declared=None, on=True)
    from semantext.sources import view
    reg = registry.load_enabled(view.BUILT_IN, world.home)
    e = reg.get("source", "tickets")
    assert e is not None and not e.builtin and not [p for p in reg.problems if p.get("kind") == "reserved key"]


# ---- 3. entries compared as written, never by == --------------------------------------------------------------------
@pytest.mark.parametrize("before, after", [([1, 2], [1.0, 2.0, "x"]), ([True, False], [1, 0, "x"])])
def test_3_a_type_change_is_never_shown_as_only_added(world, before, after):   # must refuse "only added"
    world.offer(declared=LISTED)
    _set(world, rules=before)
    n = _propose(world, {"rules": after})
    review = "\n".join(_before_yes(_said(plugincmd._confirm, world, str(n))))
    assert "only added at the end" not in review and "the whole list before and after" in review
    assert f"      1. {json.dumps(after[0])}" in review


def test_3_entries_only_added_are_still_shown_as_added(world):   # must pass
    world.offer(declared=LISTED)
    _set(world, rules=[1, 2])
    n = _propose(world, {"rules": [1, 2, "x"]})
    review = _before_yes(_said(plugincmd._confirm, world, str(n)))
    assert any("entries only added at the end" in s for s in review) and '    + put in, as entry 3: "x"' in review


def test_3_a_change_from_true_to_1_is_a_change(world):   # must refuse "nothing would change"
    world.offer(declared=LISTED)
    _set(world, rules=[True])   # the page never writes true (an entry is a text or a number); the file may hold it
    assert _propose(world, {"rules": [1]})
    _set(world, rules=[1])
    with pytest.raises(pluginpage.Refused, match="nothing would change"):   # must pass: the same, as written
        pluginpage.change(world.home, KEY, {"rules": [1]})


def test_3_same_is_as_written():
    assert not pluginpage.same(True, 1) and not pluginpage.same(1, 1.0) and not pluginpage.same([0], [False])
    assert pluginpage.same({"a": 1, "b": [2]}, {"b": [2], "a": 1}) and pluginpage.same(None, None)


def test_3_a_proposal_differing_only_by_type_is_not_the_same_proposal(world):   # must refuse to reuse it
    world.offer(declared=LISTED)
    one = _propose(world, {"rules": [1]})
    two = _propose(world, {"rules": [1.0]})
    assert one != two and _propose(world, {"rules": [1.0]}) == two     # must pass: the same one again is reused


# ---- 4. the renderer is one to one ----------------------------------------------------------------------------------
def test_4_two_keys_never_look_alike(world):   # must refuse
    world.offer()
    _set(world, **{"aс": "one", "a\\u0441": "one"})
    lines = pluginpage.enable_review(world.home, KEY, DECLARED["plugins"][KEY])
    assert "  a\\u0441 = \"one\"" in lines and "  a\\\\u0441 = \"one\"" in lines


CORPUS = ["", " ", "  ", "\\", "\\\\", "u", "\\u0441", "с", "\\\\u0441", "\\U00010000", "\U00010000", "a b",
          "a  b", " a", "a ", "\\u0020", "‮", "\\u202e", "\\x", "\x1b", "\\u001b", "\"", "\\\""]


def test_4_distinct_texts_never_render_alike():   # must refuse a collision, over every short mix of the hard parts
    parts = ["\\", "u", "0", "4", "1", "с", " ", "a", "‮", "U"]
    texts = {"".join(t) for n in range(4) for t in itertools.product(parts, repeat=n)} | set(CORPUS)
    texts |= {a + b for a in CORPUS for b in CORPUS}
    rendered = {}
    for t in texts:
        r = pluginpage.ascii_only(t)
        assert all(" " <= c <= "~" for c in r)
        assert rendered.setdefault(r, t) == t, f"{t!r} and {rendered[r]!r} both render as {r!r}"


def test_4_distinct_values_never_render_alike():   # must refuse a collision of values
    values = CORPUS + [1, 1.0, True, "1", "true", None, "null", [1], ["1"], [True], {"a": 1}, {"a": "1"}]
    seen = {}
    for v in values:
        r = pluginpage.exact(v)
        assert seen.setdefault(r, json.dumps(v)) == json.dumps(v)


def test_4_plain_text_renders_as_it_is():   # must pass
    assert pluginpage.ascii_only("semantext plugins confirm 3") == "semantext plugins confirm 3"


# ---- 5. rows at the console's width ---------------------------------------------------------------------------------
def test_5_rows_are_counted_at_the_console_width():   # must refuse at 80 what fits at 100
    lines = ["x" * 100] * 60
    pluginpage.too_long(lines, "it", "s", "a", 100)
    with pytest.raises(pluginpage.Refused, match="120 rows at 80 columns"):
        pluginpage.too_long(lines, "it", "s", "a", 80)


def test_5_the_width_is_read_from_the_console(monkeypatch):
    monkeypatch.setattr(pluginpage, "width", REAL_WIDTH)
    monkeypatch.setenv("COLUMNS", "80")
    assert pluginpage.width() == 80
    monkeypatch.setenv("COLUMNS", "132")
    assert pluginpage.width() == 132


def test_5_a_narrow_console_is_said_in_the_review(world, monkeypatch):   # must refuse to measure it silently
    world.offer()
    n = _propose(world, {"project": "beta"})
    monkeypatch.setattr(pluginpage, "width", lambda: 80)
    review = _before_yes(_said(plugincmd._confirm, world, str(n)))
    assert review[0].startswith("Your console is 80 columns wide, narrower than 100")


def test_5_a_console_of_100_columns_says_nothing_of_its_width(world):   # must pass
    world.offer()
    n = _propose(world, {"project": "beta"})
    review = _before_yes(_said(plugincmd._confirm, world, str(n)))
    assert not any("columns wide" in s for s in review)


def _enable_with(world, monkeypatch, n):
    world.offer()
    monkeypatch.setattr(pluginpage, "enable_review", lambda home, key, declared: [pluginpage._line("r")] * n)
    return _said(plugincmd._enable, world, KEY)


# The head enable prints before its review: the plug-in's line and its package's (1 row each at 100 columns), and the
# note that a plug-in is code (2 rows), 4 rows in all (round 8: the package on a line of its own).
def test_5_the_enable_head_is_counted(world, monkeypatch):   # must refuse: 4 head rows + 57 = 61 rows
    with pytest.raises(pluginpage.Refused, match="61 rows at 100 columns"):
        _enable_with(world, monkeypatch, pluginpage.REVIEW_LINES - 3)


def test_5_an_enable_review_with_its_head_inside_60_rows_is_shown(world, monkeypatch):   # must pass: 4 + 56 = 60
    said = _enable_with(world, monkeypatch, pluginpage.REVIEW_LINES - 4)
    head = _before_yes(said)
    assert pluginpage.rows(head) == pluginpage.REVIEW_LINES and plugincmd.registry.enabled(world.home)[0].get(KEY)


# ---- 6. a record number is ASCII digits alone -----------------------------------------------------------------------
@pytest.mark.parametrize("text", ["²", "١", "５", " 5", "5 ", "+5", "-5", "5_0", "", "5.0", None, 5])
def test_6_a_number_not_in_ascii_digits_is_no_number(text):   # must refuse
    assert pluginpage.number(text) is None


def test_6_ascii_digits_are_a_number():   # must pass
    assert pluginpage.number("5") == 5 and pluginpage.number("0012") == 12


@pytest.mark.parametrize("text", ["²", "١", "１"])
def test_6_confirm_and_show_refuse_another_scripts_digits(world, text):   # must refuse, never crash or act
    world.offer()
    _propose(world, {"project": "beta"})
    with pytest.raises(pluginpage.Refused, match="number"):
        plugincmd.run(world.home, "confirm", text, [].append)
    with pytest.raises(pluginpage.Refused, match="number"):
        plugincmd.run(world.home, "show", text, [].append)
    assert cfg(world).get("project") != "beta"


def test_6_confirm_by_ascii_digits_applies(world):   # must pass
    world.offer()
    n = _propose(world, {"project": "beta"})
    _said(plugincmd._confirm, world, str(n))
    assert cfg(world)["project"] == "beta"


def test_6_a_store_naming_a_proposal_in_other_digits_is_a_problem(world):   # must refuse, never crash
    world.offer()
    n = _propose(world, {"project": "beta"})
    f = pluginpage.proposals_file(world.home)
    store = json.loads(f.read_text(encoding="utf-8"))
    store["confirmed"]["²"] = n
    f.write_text(json.dumps(store), encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="not a number in ASCII digits"):
        pluginpage.proposal(world.home, n)
    from semantext.sources import view
    got = view.answer("plugins", home=world.home)
    assert any("not a number in ASCII digits" in p["text"] for p in got["problems"])


# ---- 7. the review code covers the label confirm prints -------------------------------------------------------------
def test_7_a_code_read_before_the_label_changed_is_refused(world):   # must refuse
    world.offer()
    n = _propose(world, {"project": "beta"})
    code = pluginpage.proposal_code(world.home, n)
    other = {"plugins": {"source.other": {"settings": [{"key": "project", "type": "text", "widens": True}]}}}
    world.offer("source.other", declared=other, name="semantext-other", module="semantext_other")   # installed since
    assert pluginpage.proposal_code(world.home, n) != code
    with pytest.raises(pluginpage.Refused, match="not the review code"):
        _said(plugincmd._confirm, world, str(n), reviewed_full=code)
    assert cfg(world).get("project") != "beta"


def test_7_the_code_of_an_unchanged_review_applies_and_show_prints_the_label(world):   # must pass
    world.offer()
    n = _propose(world, {"project": "beta"})
    shown = pluginpage.show_proposal(world.home, n)
    assert shown[-1].startswith("As things stand now it ")
    _said(plugincmd._confirm, world, str(n), reviewed_full=pluginpage.proposal_code(world.home, n))
    assert cfg(world)["project"] == "beta"
