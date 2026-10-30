"""The eighth independent attack on the Plug-ins tab. The rule: every key the closures are read from is reserved,
always, from one list; every console line and every error text of `semantext plugins` goes through the one renderer;
a sources file that could not be written back whole is never read for a change; health is the loaded package's own;
entries are compared as written everywhere; the width is the console's real one; numbering ends in a refusal. Each
probe is a must-refuse test here, beside a must-pass partner."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from semantext import manifest, outside, plugincmd, pluginpage, registry
from test_plugins_tab import KEY, cfg, row, world, write_cfg  # noqa: F401  (fixtures)
from test_plugins_tab_attack7 import REAL_WIDTH

LISTED = {"plugins": {KEY: {"reads": ["x"], "settings": [
    {"key": "tickets", "type": "path", "title": "Tickets file"}, {"key": "project", "type": "text", "title": "Project"},
    {"key": "rules", "type": "list", "title": "Rules"}]}}}


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


def _set(world, **values):
    d = cfg(world)
    d.update(values)
    write_cfg(world.cfg, d)


def _printable(text: str) -> bool:
    return all(" " <= c <= "~" for c in text)


# ---- 1. every key the closures are read from is reserved, always -----------------------------------------------------
def _keys_closed_reads() -> set[str]:
    """The keys sources/closed.py reads, from its source: every text a module-level name ending in KEY is set to (one
    or a tuple of them), and every text in RESERVED_KEYS when it has one (the closures-by-name work does)."""
    from semantext.sources import closed
    tree = ast.parse(Path(closed.__file__).read_text(encoding="utf-8"))
    texts: dict[str, str] = {}
    found: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            names = [target] if isinstance(target, ast.Name) else list(getattr(target, "elts", []))
            values = [node.value] if isinstance(target, ast.Name) else list(getattr(node.value, "elts", []))
            for t, v in zip(names, values):
                if isinstance(t, ast.Name) and isinstance(v, ast.Constant) and type(v.value) is str:
                    texts[t.id] = v.value
                    if t.id.endswith("KEY"):
                        found.add(v.value)
                if isinstance(t, ast.Name) and t.id == "RESERVED_KEYS":
                    for e in getattr(v, "elts", []):
                        found.add(e.value if isinstance(e, ast.Constant) else texts.get(getattr(e, "id", ""), "?"))
    return found


def test_1_every_key_closed_reads_is_reserved():   # must refuse a key left out
    reads = _keys_closed_reads()
    assert {"closed", "closures_file", "closures_key"} <= reads           # must pass: the scan finds what it reads
    assert reads <= set(manifest.CLOSURE_KEYS) <= set(manifest.reserved())


def test_1_closed_names_and_the_names_key_are_reserved_always(world):   # must refuse
    kept = pluginpage.reserved_keys(world.home)
    assert {"closed", "closed_names", "closures_file", "closures_key", "closures_names_key"} <= kept
    for key in ("closed_names", "Closed_Names", "CLOSURES_NAMES_KEY"):
        with pytest.raises(pluginpage.Refused, match="of your closures"):
            pluginpage._no_reserved(world.home, [key])
    pluginpage._no_reserved(world.home, ["tickets", "project"])          # must pass: a plug-in's own keys


@pytest.mark.parametrize("field", ["closures_names_key", "Closures_Names_Key", "closures_key"])
def test_1_the_keys_the_naming_keys_name_are_reserved(world, field):   # must refuse, under any case of the field
    _set(world, **{field: "People"})
    assert "people" in pluginpage.reserved_keys(world.home)
    with pytest.raises(pluginpage.Refused, match="of your closures"):
        pluginpage._no_reserved(world.home, ["people"])


def test_1_a_declaration_of_closed_names_is_refused_and_its_plug_in_never_loads(world):   # must refuse
    class Names:
        kind, name, title, keys, needs = "source", "tickets", "Tickets", ("closed_names",), ("closed_names",)

        def read(self, config):
            return {"off": False, "problems": [], "rows": []}
    world.offer(make=Names, declared=None, on=True)
    from semantext.sources import view
    reg = registry.load_enabled(view.BUILT_IN, world.home)
    assert reg.get("source", "tickets") is None or reg.get("source", "tickets").builtin
    assert any(p.get("kind") == "reserved key" for p in reg.problems)
    with pytest.raises(manifest.Bad):
        manifest.parse({"plugins": {KEY: {"settings": [{"key": "closed_names", "type": "list"}]}}}, KEY)


# ---- 2. every error text of `semantext plugins` is rendered ---------------------------------------------------------
def test_2_a_planted_number_in_a_record_is_a_rendered_refusal(world, capsys):   # must refuse it raw, or a crash
    from semantext import cli
    world.offer()
    n = _propose(world, {"project": "beta"})
    f = pluginpage.proposals_file(world.home)
    store = json.loads(f.read_text(encoding="utf-8"))
    store["open"].pop(str(n))
    store["superseded"][str(n)] = {"by": "9\u0430\u202e", "at": "t", "who": "page"}
    f.write_text(json.dumps(store), encoding="utf-8")
    assert cli.main(["--home", str(world.home), "plugins", "confirm", str(n)]) == 1
    err = capsys.readouterr().err.strip()
    assert _printable(err) and "9\\u0430\\u202e" in err and "unexpected" not in err


def test_2_command_refuses_a_word_that_is_not_plain(world):   # must refuse, as a Refused
    with pytest.raises(pluginpage.Refused, match="plain word"):
        pluginpage.command(world.home, "plugins", "show", "9 x")
    assert pluginpage.command(world.home, "plugins", "show", 9).endswith("plugins show 9")   # must pass


@pytest.mark.parametrize("error", [OSError("cannot read C:\\x\\\u0430"), ValueError("bad \u202e"),
                                   KeyError("k\u0430")])
def test_2_any_error_in_a_plugins_command_is_rendered(world, capsys, monkeypatch, error):   # must refuse it raw
    from semantext import cli

    def boom(*a, **k):
        raise error
    monkeypatch.setattr(plugincmd, "_run", boom)
    assert cli.main(["--home", str(world.home), "plugins"]) == 1
    err = capsys.readouterr().err.strip()
    assert err.startswith("semantext: ") and _printable(err) and "\\u0430" in err or "\\u202e" in err


def test_2_a_plain_refusal_is_said_as_it_is(world, capsys):   # must pass
    from semantext import cli
    world.offer()
    assert cli.main(["--home", str(world.home), "plugins", "confirm", "41"]) == 1
    assert capsys.readouterr().err.strip() == \
        "semantext: there is no open proposal 41: it was confirmed, expired, or never made"


# ---- 3. no record is appended while LAST cannot be read ------------------------------------------------------------
def test_3_a_proposal_is_refused_while_last_cannot_be_read(world):   # must refuse
    world.offer()
    pluginpage.last_file(world.home).write_text("{not json", encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="cannot be read"):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert not pluginpage.log_file(world.home).exists()
    pluginpage.last_file(world.home).write_text('{"keys": {}, "plugins": {}}', encoding="utf-8")
    assert _propose(world, {"project": "beta"})                         # must pass: once it can be read


# ---- 4. a lone surrogate anywhere in the sources file -------------------------------------------------------------
def test_4_a_sources_file_holding_a_lone_surrogate_is_never_changed(world):   # must refuse, never half-made
    world.offer()
    text = world.cfg.read_text(encoding="utf-8").rstrip().rstrip("}") + ', "note": "\\ud800"}\n'
    world.cfg.write_text(text, encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="lone surrogate"):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert world.cfg.read_text(encoding="utf-8") == text and not pluginpage.log_file(world.home).exists()


def test_4_a_new_file_that_cannot_be_written_whole_is_refused_before_the_record(world, monkeypatch):   # must refuse
    world.offer()
    n = _propose(world, {"project": "beta"})
    real = pluginpage._raw
    monkeypatch.setattr(pluginpage, "_raw", lambda path: {**real(path), "note": "\ud800"})
    lines = len(pluginpage.log_file(world.home).read_text(encoding="utf-8").splitlines())
    with pytest.raises(pluginpage.Refused, match="could not be written whole"):
        pluginpage._make(world.home, "terminal", "settings", "settings", KEY,
                         {"values": {"project": "alpha"}, "absent": []}, {"values": {"project": "beta"}, "absent": []})
    assert len(pluginpage.log_file(world.home).read_text(encoding="utf-8").splitlines()) == lines
    assert pluginpage.last_changes(world.home)["keys"].get("project") is None and n


def test_4_a_plain_note_elsewhere_is_kept(world):   # must pass
    world.offer()
    _set(world, note="ok \u00e9")
    n = _propose(world, {"project": "beta"})
    _said(plugincmd._confirm, world, str(n))
    assert cfg(world)["project"] == "beta" and cfg(world)["note"] == "ok \u00e9"


# ---- 5. health is the loaded package's own, and starts again on off and on -----------------------------------------
def test_5_health_after_off_and_after_another_version(world):   # must refuse a stale last call
    from semantext.sources import view
    world.offer(on=True)
    view.answer("waiting", home=world.home)
    r, _ = row(home=world.home)
    assert r["health"]["last"] is not None                                 # must pass: called, said
    pluginpage.turn_off(world.home, KEY)
    r, _ = row(home=world.home)
    assert r["health"]["last"] is None and r["health"]["words"] == "not on, so never called"
    world.points.clear()
    world.offer(version="0.4")
    rows, _ = registry.enabled(world.home)
    rows[KEY] = {"origin": "semantext-jira", "version": "0.4", "at": "x"}
    registry.write_enabled(rows, world.home)
    r, _ = row(home=world.home)
    assert r["health"]["words"] == "not called yet"


def test_5_health_is_kept_by_package_and_version():
    outside.identify("source.h8", "pkg", "1")
    outside._ended("source.h8", "answered", 0.1, "read")
    assert outside.health("source.h8", "pkg", "1")["last"]["outcome"] == "answered"   # must pass
    assert outside.health("source.h8", "pkg", "2")["last"] is None                   # must refuse another version's
    assert outside.health("source.h8", "other", "1")["last"] is None
    outside.forget("source.h8")
    assert outside.health("source.h8", "pkg", "1")["last"] is None


# ---- 6. the label compares as written ------------------------------------------------------------------------------
def test_6_floats_for_ints_in_a_list_are_not_narrows(world):   # must refuse "narrows"
    world.offer(declared=LISTED)
    _set(world, rules=[1, 2])
    n = _propose(world, {"rules": [1.0, 2.0]})
    assert pluginpage.open_proposals(world.home)[str(n)]["label"] == "widens"
    assert pluginpage.widens({"type": "list", "widens": False}, [1, 2], [1.0, 2.0], False, False)


def test_6_taking_an_entry_out_still_narrows(world):   # must pass
    world.offer(declared=LISTED)
    _set(world, rules=[1, 2])
    n = _propose(world, {"rules": [1]})
    assert pluginpage.open_proposals(world.home)[str(n)]["label"] == "narrows"


# ---- 7. origin and version rendered each on its own ----------------------------------------------------------------
def test_7_two_different_packages_never_print_alike():   # must refuse a collision
    pairs = [("semantext-jira 0.3", "(not part of Semantext). It is checked and safe"),
             ("semantext-jira", "0.3 (not part of Semantext). It is checked and safe"),
             ("a  version: b", "c"), ("a", "b  version: c"), ("a", None), ("a", "None"), ("a  no version given", None),
             ("a", " "), ("a ", ""), ("a", ""), ("built-in", "1"), ("package built-in", "1")]
    seen = {}
    for p in pairs:
        said = plugincmd._from(*p)
        assert _printable(said) and seen.setdefault(said, p) == p, (p, seen[said])


def test_7_a_plain_package_reads_plainly():   # must pass
    assert plugincmd._from("semantext-jira", "0.3") == "package: semantext-jira  version: 0.3"


# ---- 8. the width is the console's real one -------------------------------------------------------------------------
def _tty(monkeypatch, cols):
    import sys

    class Out:
        def isatty(self):
            return True

        def fileno(self):
            return 1
    monkeypatch.setattr(pluginpage, "width", REAL_WIDTH)
    monkeypatch.setattr(sys, "stdout", Out())
    monkeypatch.setattr(os, "get_terminal_size", lambda fd=None: os.terminal_size((cols, 24)))


def test_8_columns_wider_than_the_terminal_is_not_believed(monkeypatch):   # must refuse COLUMNS=100000
    _tty(monkeypatch, 80)
    monkeypatch.setenv("COLUMNS", "100000")
    assert pluginpage.width() == 80


def test_8_a_tiny_console_is_counted_at_its_own_width(monkeypatch):   # must refuse a floor that hides rows
    _tty(monkeypatch, 10)
    monkeypatch.delenv("COLUMNS", raising=False)
    assert pluginpage.width() == 10 and pluginpage.rows(["x" * 100], 10) == 10
    assert pluginpage.narrow_note(10)[0].startswith("Your console is 10 columns wide, under 20")


def test_8_columns_inside_the_terminal_is_used(monkeypatch):   # must pass
    _tty(monkeypatch, 200)
    monkeypatch.setenv("COLUMNS", "132")
    assert pluginpage.width() == 132


# ---- 9. numbering ends in a refusal, never in a number no one can read --------------------------------------------
def _last_at(world, n):
    last = {"keys": {"project": {"n": n, "at": "t", "who": "terminal", "what": "settings", "field": "settings",
                                 "plugin": KEY, "before": {"values": {}, "absent": ["project"]},
                                 "after": {"values": {"project": "alpha"}, "absent": []}}}, "plugins": {}}
    pluginpage.last_file(world.home).write_text(json.dumps(last), encoding="utf-8")


def test_9_numbering_past_the_last_number_is_exhausted(world):   # must refuse
    world.offer()
    _last_at(world, pluginpage.MAX_NUMBER)
    with pytest.raises(pluginpage.Refused, match="numbering exhausted"):
        pluginpage.change(world.home, KEY, {"project": "beta"})


def test_9_the_last_number_is_given_and_read(world):   # must pass
    world.offer()
    _last_at(world, pluginpage.MAX_NUMBER - 1)
    n = _propose(world, {"project": "beta"})
    assert n == pluginpage.MAX_NUMBER and pluginpage.number(str(n)) == n
    assert pluginpage.proposal(world.home, n)["n"] == n


# ---- 10. a Rendered is checked, not trusted ------------------------------------------------------------------------
def test_10_a_rendered_holding_an_escape_is_rendered_all_the_same():   # must refuse it raw
    got = plugincmd.shown(pluginpage.Rendered("\x1b[2J\u202e"))
    assert got == "\\u001b[2J\\u202e"
    assert _printable(plugincmd._row(pluginpage.Rendered("\x1b[31m"), "n", "o", "s"))


def test_10_a_rendered_line_is_printed_as_it_is():   # must pass
    line = pluginpage._line("  already rendered \\u0441")
    assert plugincmd.shown(line) is line
