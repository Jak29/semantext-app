"""The registry, the one stable surface, and turning plug-ins on (ECOSYSTEM.md and the ecosystem review of 23 October).

Each rule here has both arms: what must pass and what must be refused. The plug-ins are defined in this file, offered
through a stand-in for importlib.metadata.entry_points; nothing is installed.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from semantext import api, cli, registry
from semantext.sources import KEYS, builtin, view
from semantext.sources import closed as closed_mod

REPO = Path(__file__).resolve().parents[1]


# ---- plug-ins defined here, and a stand-in for the installed packages -------------------------------------------
class Dist:
    def __init__(self, name="semantext-jira", version="0.3"):
        self.name, self.version = name, version


class Point:
    """An entry point as importlib.metadata gives one: a name, a distribution, and load(), counted."""

    def __init__(self, name, make, dist=None):
        self.name, self.group, self.dist, self._make, self.loads = name, registry.GROUP, dist or Dist(), make, 0

    def load(self):
        self.loads += 1
        return self._make()


class Tickets:
    kind, name, title, keys = "source", "tickets", "Tickets", ("tickets",)

    def read(self, config):
        if not config.get("tickets"):
            return {"off": True, "problems": []}
        return {"off": False, "count": 2, "problems": [api.problem(config["tickets"], 3, "shape", "not a ticket")]}


class Board:
    kind, name, title = "place", "board", "Board"

    def build(self, sources):
        return {"tickets": sources["tickets"].get("count"), "waiting_off": bool(sources["waiting"].get("off"))}


def broken():
    raise ImportError("a module the plug-in needs is missing")


@pytest.fixture
def offered(monkeypatch):
    """What the installed packages offer; a test fills it. Every call to entry_points is counted."""
    points, calls = [], []

    def entry_points(**kw):
        calls.append(kw)
        return [p for p in points if kw.get("group") == registry.GROUP]

    monkeypatch.setattr(importlib.metadata, "entry_points", entry_points)
    return points, calls


def turn_on(home, *keys, dist=None):
    dist = dist or Dist()
    registry.write_enabled({k: {"origin": dist.name, "version": dist.version, "at": "2026-10-23T00:00:00Z"}
                            for k in keys}, home)


# ---- installed is not enabled -------------------------------------------------------------------------------------
def test_installed_but_not_enabled_is_never_loaded(home, offered):   # must refuse
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "tickets") is None and points[0].loads == 0
    found, problems = registry.installed()
    assert [(i.kind, i.name, i.origin) for i in found] == [("source", "tickets", "semantext-jira")] and not problems
    assert points[0].loads == 0   # listing reads metadata only


def test_nothing_on_reads_no_metadata_at_all(home, offered):
    _, calls = offered
    registry.load_enabled(view.BUILT_IN, home)
    view.answer("sources", home=home)
    assert calls == []


def test_enabled_is_loaded_and_listed_with_its_origin(home, offered, capsys):   # must pass
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    turn_on(home, "source.tickets")
    reg = registry.load_enabled(view.BUILT_IN, home)
    e = reg.get("source", "tickets")
    assert e is not None and (e.origin, e.version) == ("semantext-jira", "0.3") and points[0].loads == 1
    assert cli.main(["--home", str(home), "plugins"]) == 0
    row = next(line for line in capsys.readouterr().out.splitlines() if " tickets " in line)
    assert "semantext-jira 0.3" in row and row.rstrip().endswith("on")


def test_a_plugin_that_raises_on_load_is_a_problem_and_the_rest_load(home, offered):
    points, _ = offered
    points += [Point("source.broken", broken), Point("source.tickets", Tickets)]
    turn_on(home, "source.broken", "source.tickets")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "broken") is None and reg.get("source", "tickets") is not None
    assert [p["kind"] for p in reg.problems] == ["failed to load"]
    assert "ImportError" in reg.problems[0]["text"]
    built = builtin.registry().names("source")
    assert reg.names("source")[:len(built)] == built   # the built-ins are all there
    got = view.answer("waiting", home=home)
    assert any(p["reader"] == "plug-ins" and p["kind"] == "failed to load" for p in got["frame"]["problems"])


def test_a_changed_version_is_not_loaded_until_turned_on_again(home, offered):   # must refuse
    points, _ = offered
    points.append(Point("source.tickets", Tickets, Dist(version="0.4")))
    turn_on(home, "source.tickets")   # turned on at 0.3
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "tickets") is None and points[0].loads == 0
    assert reg.problems[0]["kind"] == "changed"


def test_a_plugin_cannot_take_a_built_ins_name(home, offered):   # must refuse
    class Waiting(Tickets):
        name = "waiting"
    points, _ = offered
    points.append(Point("source.waiting", Waiting))
    turn_on(home, "source.waiting")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "waiting").origin == registry.BUILT_IN
    assert reg.problems[0]["kind"] == "refused"


@pytest.mark.parametrize("make, kind", [(lambda: type("P", (Board,), {"kind": "source"})(), "wrong kind"),
                                        (lambda: type("P", (Board,), {"name": "other"})(), "wrong name"),
                                        (lambda: type("P", (), {"kind": "place", "name": "board"})(), "refused")])
def test_a_plugin_of_the_wrong_shape_is_refused(home, offered, make, kind):   # must refuse
    points, _ = offered
    points.append(Point("place.board", make))
    turn_on(home, "place.board")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("place", "board") is None and reg.problems[0]["kind"] == kind


def test_reserved_kinds_are_named_and_never_loaded(home, offered):   # must refuse
    points, _ = offered
    points.append(Point("door.grants", Board))
    turn_on(home, "door.grants")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert points[0].loads == 0 and reg.problems[0]["kind"] == "reserved"
    assert all(reg.names(k) == () for k in registry.RESERVED)
    with pytest.raises(ValueError):
        registry.Registry().add("door", "x", Board())


def test_an_unreadable_list_turns_nothing_on(home, offered):
    points, calls = offered
    points.append(Point("source.tickets", Tickets))
    home.mkdir(parents=True, exist_ok=True)
    registry.enabled_file(home).write_text("{not json", encoding="utf-8")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert points[0].loads == 0 and calls == [] and reg.problems[0]["kind"] == "unreadable"


def test_an_entry_point_not_named_kind_dot_name_is_a_problem(offered):
    points, _ = offered
    points.append(Point("tickets", Tickets))
    found, problems = registry.installed()
    assert found == [] and problems[0]["kind"] == "unnamed"


# ---- the page reads through the registry ----------------------------------------------------------------------
def test_an_outside_source_and_place_reach_the_page(home, offered, tmp_path, monkeypatch):
    points, _ = offered
    points += [Point("source.tickets", Tickets), Point("place.board", Board)]
    turn_on(home, "source.tickets", "place.board")
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"tickets": str(tmp_path / "t.jsonl")}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    src = view.answer("sources", home=home)
    assert "tickets" in src["readers"] and "board" in src["routes"]
    assert any(p["reader"] == "tickets" and p["line"] == 3 for p in src["frame"]["problems"])
    board = view.answer("board", home=home)
    assert board["place"] == "board" and board["tickets"] == 2
    assert view.answer("waiting", home=home)["place"] == "waiting"   # a built-in route is still the built-in


def test_an_outside_place_that_stops_costs_only_itself(home, offered):
    class Stops(Board):
        def build(self, sources):
            raise RuntimeError("no")
    points, _ = offered
    points.append(Point("place.board", Stops))
    turn_on(home, "place.board")
    got = view.answer("board", home=home)
    assert got["off"] is True and "RuntimeError" in got["failed"]
    assert any(p["kind"] == "place stopped" for p in got["frame"]["problems"])


def test_built_in_places_and_keys_are_what_they_were():
    # The fixed tuples these replaced (1.2.2): the registry must give the same routes, in order, and the same keys.
    # One place and one source more since: Work (PM-DESIGN slice 2), after the others, so their order is kept.
    assert view.ROUTES == ("waiting", "projects", "documents", "map", "record", "rules", "sources", "work")
    # Two keys more since: the run-record folders and their age bound, read by the rules reader (runs.py). The Work
    # source adds two, for its verdict clauses (slice 2b): its store lies in the Semantext home.
    assert set(KEYS) == {"name", "seats", "group", "requests", "changes", "inbox", "register", "notes", "cards", "map",
                         "gaming", "guards", "run_records", "run_record_days", "verdicts", "pieces"} and len(KEYS) == 16
    assert view.BUILT_IN.names("source") == ("waiting", "record", "rules", "gates", "places", "work")
    assert all(e.origin == registry.BUILT_IN for e in view.BUILT_IN.entries())


# ---- turning one on is typed at a console ---------------------------------------------------------------------
@pytest.fixture
def named(tmp_path, monkeypatch):
    """Closures named (an explicit empty list), so each enable test refuses or passes for its own reason."""
    f = tmp_path / "named-sources.json"
    f.write_text(json.dumps({"closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(f))


def test_enable_refuses_until_closed_places_are_named(home, offered, monkeypatch, capsys):   # must refuse
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    monkeypatch.setattr("builtins.input", lambda _p: "source.tickets")
    assert cli.main(["--home", str(home), "plugins", "enable", "source.tickets"]) == 1
    assert "name your closed places first" in capsys.readouterr().err and not registry.enabled_file(home).exists()


def test_enable_refuses_in_an_agents_shell(home, offered, monkeypatch, named):   # must refuse
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    monkeypatch.setenv("SEMANTEXT_AGENT", "builder")
    monkeypatch.setattr("builtins.input", lambda _p: "source.tickets")
    assert cli.main(["--home", str(home), "plugins", "enable", "source.tickets"]) == 1
    assert not registry.enabled_file(home).exists()


def test_enable_refuses_without_a_console(home, offered, monkeypatch, named):   # must refuse
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _p: "source.tickets")
    assert cli.main(["--home", str(home), "plugins", "enable", "source.tickets"]) == 1
    assert not registry.enabled_file(home).exists()


@pytest.mark.parametrize("typed", ["y", "yes", "tickets", "source.ticket", ""])
def test_enable_refuses_unless_the_name_is_typed_back(home, offered, monkeypatch, typed, named):   # must refuse
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    monkeypatch.setattr("builtins.input", lambda _p: typed)
    assert cli.main(["--home", str(home), "plugins", "enable", "source.tickets"]) == 1
    assert not registry.enabled_file(home).exists()


def test_enable_with_the_name_typed_back_turns_it_on_and_disable_off(home, offered, monkeypatch, named):   # must pass
    points, _ = offered
    points.append(Point("source.tickets", Tickets))
    monkeypatch.setattr("builtins.input", lambda _p: "source.tickets")
    assert cli.main(["--home", str(home), "plugins", "enable", "source.tickets"]) == 0
    on, _ = registry.enabled(home)
    assert on["source.tickets"]["origin"] == "semantext-jira" and on["source.tickets"]["version"] == "0.3"
    assert points[0].loads == 0   # turning on loads nothing; the page and the command line load it when they read
    assert cli.main(["--home", str(home), "plugins", "disable", "source.tickets"]) == 0
    assert registry.enabled(home)[0] == {}


def test_enable_refuses_a_reserved_kind_and_an_unknown_name(home, offered, monkeypatch, named):
    points, _ = offered
    points.append(Point("door.grants", Board))
    monkeypatch.setattr("builtins.input", lambda p: p.split()[1])
    assert cli.main(["--home", str(home), "plugins", "enable", "door.grants"]) == 1
    assert cli.main(["--home", str(home), "plugins", "enable", "source.nothing"]) == 1
    assert not registry.enabled_file(home).exists()


def test_check_says_not_checked_and_never_passes(home, capsys):
    assert cli.main(["--home", str(home), "plugins", "check"]) == 1
    assert "not built yet" in capsys.readouterr().out


# ---- the card hook loads no plug-in -----------------------------------------------------------------------------
HOOK_MODULES = ["semantext", "semantext.agents", "semantext.envcard", "semantext.envhook", "semantext.feed",
                "semantext.heard", "semantext.hook", "semantext.inbox", "semantext.jsonread", "semantext.paths",
                "semantext.provenance",
                "semantext.sender", "semantext.store"]


def _python(code: str, tmp_path, stdin: str = "") -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_SANDBOX",
                                                            "CODEX_SANDBOX_NETWORK_DISABLED", "SEMANTEXT_AGENT",
                                                            "SEMANTEXT_SOURCES")}
    env.update(PYTHONPATH=str(REPO), SEMANTEXT_HOME=str(tmp_path / "semantext"), HOME=str(tmp_path),
               USERPROFILE=str(tmp_path), PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, "-c", code], cwd=str(REPO), env=env, input=stdin, capture_output=True,
                          text=True, encoding="utf-8", timeout=120)


def test_the_hook_imports_a_pinned_set_and_no_registry(tmp_path):   # must refuse a new import
    code = ("import sys, json, semantext.hook, semantext.envhook\n"
            "print(json.dumps([sorted(m for m in sys.modules if m.startswith('semantext')),"
            " 'importlib.metadata' in sys.modules]))")
    run = _python(code, tmp_path)
    assert run.returncode == 0, run.stderr
    mods, metadata = json.loads(run.stdout.strip().splitlines()[-1])
    assert mods == HOOK_MODULES
    assert "semantext.registry" not in mods and "semantext.api" not in mods and metadata is False


# the hook starts nothing and opens no connection; urllib.parse only quotes text (pathlib imports it on 3.11 and 3.12)
NO_REACH = ("subprocess", "socket", "http", "urllib.request")


def _reach(extra: str, tmp_path) -> list[str]:
    code = (f"import sys, json, semantext.hook, semantext.envhook{extra}\n"
            f"print(json.dumps(sorted(m for m in sys.modules if any(m == n or m.startswith(n + '.') "
            f"for n in {list(NO_REACH)!r}))))")
    run = _python(code, tmp_path)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def test_the_hook_imports_no_process_or_network_module(tmp_path):   # must refuse (the audit of the registry, f)
    assert _reach("", tmp_path) == []


def test_the_reach_check_can_fail(tmp_path):   # the control: the same check sees one when it is imported
    assert _reach(", subprocess, urllib.request", tmp_path) != []


def test_running_the_hook_scans_no_entry_point(tmp_path):
    # Every entry-point door is replaced by one that records; then the hook runs on a prompt, as Claude Code runs it.
    code = ("import sys, json, importlib.metadata as md\n"
            "calls = []\n"
            "md.entry_points = lambda *a, **k: calls.append('entry_points') or []\n"
            "md.EntryPoint.load = lambda self: calls.append('load')\n"
            "from semantext import cli\n"
            "rc = cli.main(['hook'])\n"
            "print('\\n' + json.dumps([rc, calls, sorted(m for m in sys.modules if m.startswith('semantext'))]))")
    event = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "hello", "session_id": "s1",
                        "cwd": str(tmp_path)})
    run = _python(code, tmp_path, stdin=event)
    assert run.returncode == 0, run.stderr
    rc, calls, mods = json.loads(run.stdout.strip().splitlines()[-1])
    assert rc == 0 and calls == []
    assert not {"semantext.registry", "semantext.api", "semantext.plugincmd", "semantext.sources"} & set(mods)


def test_the_hook_check_can_fail(tmp_path):   # the control: the same check sees the registry when it is imported
    code = ("import sys, json, semantext.hook, semantext.registry\n"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('semantext'))))")
    run = _python(code, tmp_path)
    assert "semantext.registry" in json.loads(run.stdout.strip().splitlines()[-1])


# ---- semantext.api ------------------------------------------------------------------------------------------------
def test_the_api_is_small_and_versioned():
    assert api.VERSION == "0.2" and api.GROUP == "semantext.plugins" and api.KINDS == ("source", "place", "checker")
    assert sorted(api.__all__) == sorted(["VERSION", "GROUP", "KINDS", "Source", "Place", "Checker", "problem",
                                          "read_lines", "MAX_LINE", "is_closed_place", "fingerprint", "named_roots",
                                          "seat_rows", "ReadContext", "closures_known",
                                          "inside_roots", "taken_names"])
    assert all(isinstance(e.obj, api.Source) for e in view.BUILT_IN.entries("source"))
    assert all(isinstance(e.obj, api.Place) for e in view.BUILT_IN.entries("place"))
    assert isinstance(view.BUILT_IN.get("checker", "guards").obj, api.Checker)
    assert isinstance(Tickets(), api.Source) and isinstance(Board(), api.Place)
    assert not isinstance(Board(), api.Source)


def test_the_api_fingerprint_is_the_pages():
    from semantext.sources import change
    assert api.fingerprint is change.fingerprint


# ---- closed places ----------------------------------------------------------------------------------------------
def _closures(tmp_path, value) -> Path:
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    (home / "sources.json").write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
    return home


def test_a_closed_folder_and_everything_in_it_is_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "Private"
    (shut / "deep").mkdir(parents=True)
    home = _closures(tmp_path, {"closed": [str(shut)]})
    assert api.is_closed_place(shut, home) and api.is_closed_place(shut / "deep" / "x.md", home)   # must refuse
    assert not api.is_closed_place(tmp_path / "Public" / "x.md", home)                            # must pass
    assert not api.is_closed_place(tmp_path / "PrivateNotes", home)   # a sibling sharing the name's start is open
    if os.name == "nt":
        assert api.is_closed_place(str(shut).upper() + "\\DEEP", home)


def test_a_link_into_a_closed_folder_is_closed(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "Private"
    shut.mkdir()
    link = tmp_path / "door"
    try:
        if os.name == "nt":   # a junction needs no privilege on Windows, as test_change_evidence.py makes them
            import _winapi
            _winapi.CreateJunction(str(shut), str(link))
        else:
            link.symlink_to(shut, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot make a link")
    home = _closures(tmp_path, {"closed": [str(shut)]})
    assert api.is_closed_place(link / "x.md", home)


@pytest.mark.parametrize("value", ["{broken", {"closed": "C:\\one"}, {"closed": ["relative\\path"]}, {"closed": [3]},
                                   {"closed": [""]}, []])
def test_closures_that_cannot_be_known_close_everything(tmp_path, monkeypatch, value):   # fails closed
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    home = _closures(tmp_path, value)
    assert closed_mod.closures(home) is None
    assert api.is_closed_place(tmp_path / "anything.md", home)


def test_no_closures_named_closes_everything_to_a_plug_in(tmp_path, monkeypatch):   # must refuse (24 October)
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    home = _closures(tmp_path, {"seats": "x"})
    assert not api.closures_known(home) and api.is_closed_place(tmp_path / "a.md", home)
    assert api.is_closed_place(tmp_path / "a.md", closed_mod.context(home))
    # the built-in readers' rule is unchanged: none named closes nothing to them
    assert closed_mod.closures(home) == [] and not closed_mod.in_closed_place(tmp_path / "a.md", home)
    assert api.is_closed_place("", home) and api.is_closed_place(None, home)


def test_no_sources_file_is_closures_unknown(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    assert not api.closures_known(tmp_path / "nowhere") and api.is_closed_place(tmp_path / "a.md", tmp_path / "nowhere")


def test_an_explicit_empty_list_closes_nothing(tmp_path, monkeypatch):   # must pass: a statement, so known
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    home = _closures(tmp_path, {"closed": []})
    assert api.closures_known(home) and not api.is_closed_place(tmp_path / "a.md", home)


def _closures_file(tmp_path, value, name="closures.json") -> Path:
    f = tmp_path / name
    f.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return f


def test_closures_are_read_from_a_closures_file(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "Private"
    f = _closures_file(tmp_path, {"places": [str(shut)]})
    home = _closures(tmp_path, {"closures_file": str(f), "closures_key": "places"})
    assert api.closures_known(home) and closed_mod.closures(home) == [str(shut)]
    assert api.is_closed_place(shut / "a.md", home) and not api.is_closed_place(tmp_path / "Open" / "a.md", home)
    f2 = _closures_file(tmp_path, {"closed": [str(shut)]}, "default-key.json")   # "closed" when no key is named
    home2 = _closures(tmp_path, {"closures_file": str(f2)})   # the same home, its sources file written anew
    assert closed_mod.closures(home2) == [str(shut)]


def test_inline_and_file_closures_merge(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    a, b = tmp_path / "A", tmp_path / "B"
    f = _closures_file(tmp_path, {"closed": [str(b), str(a)]})
    home = _closures(tmp_path, {"closed": [str(a)], "closures_file": str(f)})
    assert closed_mod.closures(home) == [str(a), str(b)]
    assert api.is_closed_place(a / "x", home) and api.is_closed_place(b / "x", home)


@pytest.mark.parametrize("file_value, setting", [
    ("{broken", {}), ({"closed": "C:\\one"}, {}), ({"closed": ["relative"]}, {}), ({"other": []}, {}), ([], {}),
    ('{"closed": [], "closed": []}', {}), (None, {}), ({"closed": []}, {"closures_key": 3}),
    ({"closed": []}, {"closures_file": "relative.json"}), ({"closed": []}, {"closures_file": None}),
])
def test_a_closures_file_that_cannot_be_used_is_unknown(tmp_path, monkeypatch, file_value, setting):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    where = str(_closures_file(tmp_path, file_value)) if file_value is not None else str(tmp_path / "missing.json")
    home = _closures(tmp_path, {"closed": [], "closures_file": where, **setting})
    assert not api.closures_known(home) and closed_mod.closures(home) is None
    assert api.is_closed_place(tmp_path / "a.md", home) and closed_mod.in_closed_place(tmp_path / "a.md", home)


def test_a_closures_key_without_a_file_is_unknown(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    home = _closures(tmp_path, {"closed": [], "closures_key": "places"})
    assert not api.closures_known(home)


def test_a_closures_file_over_the_bound_is_unknown(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    monkeypatch.setattr(closed_mod, "MAX_CLOSURES_FILE", 10)
    f = _closures_file(tmp_path, {"closed": [str(tmp_path / "Private")]})
    home = _closures(tmp_path, {"closures_file": str(f)})
    assert not api.closures_known(home)
