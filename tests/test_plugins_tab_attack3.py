"""The third independent attack on the Plug-ins tab: each probe it made is a must-refuse test here, beside a must-pass
partner. The decision they hold the tab to: the console is the point of review. Every settings change recorded while a
plug-in was off is shown, with who made it and when, before the person turns that plug-in on. (Its A6, a page change
importing plug-ins under the lock, went with the page's write-time judgement: a proposal imports nothing.)"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from semantext import plugincmd, pluginpage, registry
from semantext.sources import view
from test_plugins_tab import KEY, apply, cfg, world, write_cfg  # noqa: F401  (fixtures)

WIDE = "C:\\Windows" if os.name == "nt" else "/etc"


@pytest.fixture(autouse=True)
def fresh_gate(monkeypatch):
    pluginpage._RECENT.clear()
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    yield
    pluginpage._RECENT.clear()


class Reader:
    """Reads "project" through its keys and declares nothing."""
    kind, name, title, keys, needs = "source", "reader", "Reader", ("project",), ("project",)

    def read(self, config):
        return {"off": True, "problems": []}


def _reader(world, on=True):
    return world.offer("source.reader", make=Reader, declared=None, on=on, name="semantext-reader",
                       module="semantext_reader")


def _enable(world, key, typed=None):
    said = []
    plugincmd._enable(key, world.home, said.append, ask=lambda prompt: (said.append(prompt), typed or key)[1])
    return said


# ---- A1: changed while off, turned on at the console ---------------------------------------------------------------
def test_A1_turning_on_shows_every_change_made_while_it_was_off(world):   # must refuse to show nothing
    world.offer()
    _reader(world)
    pluginpage.turn_off(world.home, "source.reader")
    made = apply(world.home, KEY, {"project": WIDE})   # proposed on the page, applied at the console
    said = _enable(world, "source.reader")
    prompt = next(i for i, s in enumerate(said) if s.startswith("Having seen the above"))
    review = "\n".join(said[:prompt])                               # all of it before the yes
    assert f"change {made['n']}" in review and "by the terminal" in review and json.dumps(WIDE) in review
    assert "declares no settings" in review and "project = " in review   # its value now, among the keys it may read
    assert "source.reader" in registry.enabled(world.home)[0]


def test_A1_a_declared_plug_in_is_shown_its_settings_and_every_change(world):   # must pass
    world.offer()                                                  # source.tickets declares tickets, project, extra
    apply(world.home, KEY, {"project": "beta"})
    said = "\n".join(_enable(world, KEY))
    assert "It declares these settings" in said and 'project = "beta"' in said
    assert "extra: not set" in said and "by the terminal: project" in said


def test_A1_a_plug_in_nothing_was_changed_for_says_so(world):   # must pass
    world.offer()
    said = "\n".join(_enable(world, KEY))
    assert "No settings change is recorded since it was last turned off." in said


def test_A1_only_changes_since_it_was_last_turned_off_are_shown(world):
    world.offer()
    _reader(world)
    early = apply(world.home, KEY, {"project": "beta"})
    off = pluginpage.turn_off(world.home, "source.reader")
    later = apply(world.home, KEY, {"project": "gamma"})
    said = "\n".join(_enable(world, "source.reader"))
    assert f"change {later['n']}" in said                                    # must pass
    assert f"change {early['n']}," not in said and f"change {off['n']}," not in said   # must refuse the rest


def test_A1_the_review_outlives_the_logs_rotation(world, monkeypatch):   # must refuse to lose it
    world.offer()
    _reader(world)
    pluginpage.turn_off(world.home, "source.reader")
    made = apply(world.home, KEY, {"project": WIDE})
    monkeypatch.setattr(pluginpage, "MAX_LOG", 3000)
    for i in range(40):   # proposals push the log past two rotations
        pluginpage._RECENT.clear()
        with pytest.raises(pluginpage.AtTheTerminal):
            pluginpage.change(world.home, KEY, {"tickets": str(Path(WIDE) / f"p{i}")})
    tail = pluginpage.log_file(world.home).read_text(encoding="utf-8") + \
        (world.home / pluginpage.ROTATED).read_text(encoding="utf-8")
    assert f'"n": {made["n"]},' not in tail                        # gone from both logs ...
    said = "\n".join(_enable(world, "source.reader"))
    assert f"change {made['n']}" in said and json.dumps(WIDE) in said   # ... and still shown, from the last-change file




# ---- A2: a plug-in on under a name no longer allowed -----------------------------------------------------------------
def test_A2_a_dotted_name_already_on_says_why_and_offers_no_page_off(world):   # must refuse to offer what it refuses
    world.offer()
    world.offer("source.my.notes", make=Reader, declared=None, on=True, name="semantext-notes", module="semantext_notes")
    got = view.answer("plugins", home=world.home)
    row = next(r for r in got["plugins"] if r["key"] == "source.my.notes")
    assert row["trust"] == "turned on, but its name is no longer allowed"
    assert row["can"]["off"] is False and "no longer allowed" in row["health"]["words"]
    assert row["off_command"].endswith("plugins disable source.my.notes")
    with pytest.raises(pluginpage.Refused):
        pluginpage.turn_off(world.home, "source.my.notes")


def test_A2_the_console_takes_it_off(world):   # must pass
    world.offer("source.my.notes", make=Reader, declared=None, on=True, name="semantext-notes", module="semantext_notes")
    said = []
    plugincmd._disable("source.my.notes", world.home, said.append)
    assert "source.my.notes" not in registry.enabled(world.home)[0] and said == ["source.my.notes is off."]


def test_A2_a_name_the_line_cannot_carry_gets_no_line(world):   # must refuse to put it in a line
    rows, _ = registry.enabled(world.home)
    rows["source.a$(calc)"] = {"origin": "x", "version": "1", "at": "x"}
    registry.write_enabled(rows, world.home)
    got = view.answer("plugins", home=world.home)
    row = next(r for r in got["plugins"] if r["key"] == "source.a$(calc)")
    assert row["off_command"] is None and "plugins.json" in row["off_note"] and row["can"]["off"] is False


# ---- A4: rotation never loses the last change to a key, and says what it drops ----------------------------------------
def test_A4_the_refusal_for_a_rotated_record_says_what_is_dropped(world, monkeypatch):   # must refuse the old claim
    world.offer()
    first = apply(world.home, KEY, {"project": "beta"})
    monkeypatch.setattr(pluginpage, "MAX_LOG", 2500)
    for i in range(30):
        pluginpage._RECENT.clear()
        with pytest.raises(pluginpage.AtTheTerminal):
            pluginpage.change(world.home, KEY, {"tickets": str(Path(WIDE) / f"q{i}")})
    pluginpage._RECENT.clear()
    with pytest.raises(pluginpage.Refused) as e:
        pluginpage.roll_back(world.home, first["n"])
    assert "then dropped" in str(e.value) and pluginpage.LAST in str(e.value)
    assert "older records are kept" not in str(e.value)


def test_A4_the_last_change_to_each_key_is_kept_for_good(world, monkeypatch):   # must pass
    world.offer()
    first = apply(world.home, KEY, {"project": "beta"})
    monkeypatch.setattr(pluginpage, "MAX_LOG", 2500)
    for i in range(30):
        pluginpage._RECENT.clear()
        with pytest.raises(pluginpage.AtTheTerminal):
            pluginpage.change(world.home, KEY, {"tickets": str(Path(WIDE) / f"q{i}")})
    kept = pluginpage.last_changes(world.home)["keys"]["project"]
    assert kept["n"] == first["n"] and kept["after"] == {"values": {"project": "beta"}, "absent": []}


# ---- A5: the line to type holds no free text ----------------------------------------------------------------------
QUOTES = ["\u2018", "\u2019", "\u201a", "\u201b", "\u201c", "\u201d", "\u201e", "\u201f", '"', "'", "`", "\u00b4",
          "\uff07", "\u02bc", "&", "|", "^", "%", "!", "$(x)", ";", "<", ">", "\u00e9", "\t"]


@pytest.mark.parametrize("bad", QUOTES)
def test_A5_a_home_with_any_quote_or_shell_character_is_never_in_the_line(bad):   # must refuse
    home = ("C:\\tmp\\a" if os.name == "nt" else "/tmp/a") + bad + "b"
    for shell in ("posix", "powershell"):
        line = pluginpage.command(home, "plugins", "confirm", 7, shell=shell)
        assert line == "semantext plugins confirm 7" and bad not in line
        assert "SEMANTEXT_HOME" in pluginpage.command_note(home, shell=shell)


def test_A5_the_note_names_the_shell_and_cmd_is_not_supported():   # must pass
    assert "PowerShell" in pluginpage.command_note(None, shell="powershell")
    assert "cmd.exe is not supported" in pluginpage.command_note(None, shell="powershell")
    assert "POSIX shell" in pluginpage.command_note(None, shell="posix")


def test_A5_the_probes_injection_lines_carry_nothing():   # must refuse: the attack's own two homes
    for home in ("C:\\tmp\\Avery\u2019s; Write-Output INJECTED-PS; \u2019x", "C:\\tmp\\a&echo INJECTED-CMD&"):
        line = pluginpage.command(home, "plugins", "confirm", 7, shell="powershell")
        assert "INJECTED" not in line


# ---- A7: a kill between the record and the change ---------------------------------------------------------------
def test_A7_a_change_that_failed_after_its_record_is_shown_not_applied(world, monkeypatch):   # must refuse to hide it
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "beta"})

    def stop(*a):
        raise RuntimeError("the process stopped here")
    with monkeypatch.context() as m:   # only _apply is put back: undo() would undo the run's home redirect too
        m.setattr(pluginpage, "_apply", stop)
        with pytest.raises(RuntimeError):
            pluginpage.confirm(world.home, e.value.proposal)
    pluginpage._RECENT.clear()
    assert cfg(world)["project"] == "alpha"                     # never a change without its record ...
    got = view.answer("plugins", home=world.home)
    rec = got["changes"][0]
    assert rec["status"] == "not applied"                       # ... and a record without its change is said
    with pytest.raises(pluginpage.Refused, match="changed since"):
        pluginpage.roll_back(world.home, rec["n"])


def test_A7_a_change_made_whole_is_not_flagged(world):   # must pass
    world.offer()
    apply(world.home, KEY, {"project": "beta"})
    got = view.answer("plugins", home=world.home)
    assert got["changes"][0]["status"] is None


CHILD = r"""
import importlib.metadata, json, os, sys
sys.path[:0] = [sys.argv[2], sys.argv[3]]
from pathlib import Path
base = Path(sys.argv[1])
from semantext import pluginpage, registry
from plugin_fakes import DECLARED, Point, Tickets, package
dist = package(base / "site", declared=DECLARED)
pt = Point("source.tickets", Tickets, dist, value="semantext_jira.reader:SOURCE")
importlib.metadata.entry_points = lambda **kw: [pt] if kw.get("group") == registry.GROUP else []
try:
    pluginpage.change(base / "home", "source.tickets", {"project": "beta"})
except pluginpage.AtTheTerminal as e:
    n = e.proposal
pluginpage._apply = lambda *a: os._exit(9)   # a kill between the record and the change
pluginpage.confirm(base / "home", n)
"""


def test_A7_a_real_kill_between_record_and_change(tmp_path):   # must refuse a change with no record
    (tmp_path / "home").mkdir()
    (tmp_path / "user").mkdir()
    (tmp_path / "sources.json").write_text(json.dumps({"closed": [], "project": "alpha"}), encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "SEMANTEXT_HOME": str(tmp_path / "home"), "SEMANTEXT_SOURCES": str(tmp_path / "sources.json"),
           "USERPROFILE": str(tmp_path / "user"), "HOME": str(tmp_path / "user")}
    r = subprocess.run([sys.executable, "-c", CHILD, str(tmp_path), str(repo), str(repo / "tests")], env=env,
                       capture_output=True, timeout=60)
    assert r.returncode == 9, r.stderr.decode("utf-8", "replace")
    assert json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))["project"] == "alpha"
    recs, _ = pluginpage.changes(tmp_path / "home")
    assert [(x["what"], x["after"]) for x in recs] == [("proposed", {"values": {"project": "beta"}, "absent": []}),
                                                      ("settings", {"values": {"project": "beta"}, "absent": []})]


# ---- item 7: confirm, at the console that is reading another sources file ------------------------------------------
def test_7_a_confirm_on_another_sources_file_is_refused(world, monkeypatch, tmp_path):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    other = tmp_path / "other-sources.json"
    other.write_bytes(world.cfg.read_bytes())   # the same bytes: only the path tells them apart
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(other))
    with pytest.raises(pluginpage.Refused, match="SEMANTEXT_SOURCES differs"):
        pluginpage.proposal(world.home, e.value.proposal)


def test_7_the_confirm_review_is_worked_out_now(world):   # must pass
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    r = pluginpage.proposal(world.home, e.value.proposal)
    other = {"plugins": {"source.other": {"settings": [{"key": "tickets", "type": "path"}]}}}
    world.offer("source.other", declared=other, name="semantext-other", module="semantext_other")   # installed since
    lines = pluginpage.confirm_review(world.home, r)
    assert lines[0] == f"Sources file: {pluginpage.ascii_only(world.cfg)}" and "  tickets:" in lines
    assert "wider for source.other" in lines[-1]                       # the label worked out now names it
