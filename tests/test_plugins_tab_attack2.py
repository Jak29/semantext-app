"""The second independent attack on the Plug-ins tab: each probe it made is a must-refuse test here, beside a must-pass
partner. Its rule then was "when the page cannot know, it proposes"; since the owner's choice (the page proposes, the console applies) the page
proposes every settings change, so the probes now hold that whatever they set up, the page writes no setting."""
from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

from semantext import outside, pluginpage, registry
from semantext.sources import closed, view
from test_plugins_tab import (KEY, PAGE, apply, apply_back, cfg, post, proposed_label, served,  # noqa: F401
                              world, write_cfg)

WIDE = "C:\\Windows" if os.name == "nt" else "/etc"
TEXT_TICKETS = {"plugins": {KEY: {"settings": [{"key": "tickets", "type": "text"}]}}}
FILES_TEXT = {"plugins": {"source.files": {"settings": [{"key": "tickets", "type": "text"}]}}}


@pytest.fixture(autouse=True)
def fresh_gate():
    pluginpage._RECENT.clear()
    yield
    pluginpage._RECENT.clear()


class Files:
    """On, reads "tickets" through its keys."""
    kind, name, title, keys, needs = "source", "files", "Files", ("tickets",), ("tickets",)

    def read(self, config):
        return {"off": True, "problems": []}


def _x(world, make=Files, declared=None, version="1.0"):
    return world.offer("source.files", make=make, declared=declared, on=True, name="semantext-files",
                       module="semantext_files", version=version)


# ---- H1, H2, H3: plug-ins on but not loaded -------------------------------------------------------------------------
# These were findings against the page deciding, at write time, which settings changes it could make; it makes none
# now (the owner's choice). What holds instead, whatever is on and whether it loads: the page writes nothing.
class Slow(Files):
    def read(self, config):
        time.sleep(3)
        return {"off": True, "problems": []}


def _version_changed(world):
    _x(world, declared=FILES_TEXT).dist.version = "1.1"


def _import_fails(world):
    def broken():
        raise ImportError("a dependency is missing today")
    _x(world, make=broken, declared=FILES_TEXT)


def _busy(world):
    _x(world, make=Slow, declared=FILES_TEXT)
    view.answer("sources", home=world.home)   # its read passes the budget and hangs: its next calls are Busy
    assert outside.health("source.files")["holding"] >= 1


def _gone(world):
    rows, _ = registry.enabled(world.home)
    rows["source.gone"] = {"origin": "semantext-gone", "version": "1", "at": "x"}
    registry.write_enabled(rows, world.home)


@pytest.mark.parametrize("make", [_version_changed, _import_fails, _busy, _gone, lambda w: _x(w, declared=FILES_TEXT)],
                         ids=["version changed", "import fails", "busy", "no package", "loaded and declared"])
def test_H_whatever_is_on_the_page_writes_no_setting(world, monkeypatch, make):   # must refuse a write
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.5")
    world.offer(declared=TEXT_TICKETS)
    make(world)
    before = world.cfg.read_bytes()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    assert world.cfg.read_bytes() == before and e.value.command.endswith(f"plugins confirm {e.value.proposal}")


def test_H_a_proposal_loads_no_plug_in(world, monkeypatch):   # must pass: proposing runs no plug-in code
    world.offer()
    _x(world, declared=FILES_TEXT)
    calls = []
    monkeypatch.setattr(registry, "load_enabled", lambda *a, **k: calls.append(a))
    with pytest.raises(pluginpage.AtTheTerminal):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert calls == []


def test_H1_over_http(served, world):   # must refuse, as the page sends it
    world.offer(declared=TEXT_TICKETS)
    _x(world).dist.version = "9"
    code, body = post(served, "settings", {"plugin": KEY, "settings": {"tickets": WIDE}}, **PAGE)
    assert code == 202 and "confirm" in body["line"] and cfg(world)["tickets"] == str(world.old)




# ---- C1: the closures, read from a key of the person's naming in the sources file itself ---------------------------
def _closures_here(world, key="private"):
    secret = world.tmp / "secret"
    secret.mkdir()
    d = cfg(world)
    d.pop("closed")
    d.update({"closures_file": str(world.cfg), "closures_key": key, key: [str(secret)]})
    write_cfg(world.cfg, d)
    assert closed.closures(world.home) == [str(secret)]
    return secret


@pytest.mark.parametrize("key", ["private", "Private"])
def test_C1_the_key_the_closures_are_read_from_is_never_a_setting(world, key):   # must refuse
    secret = _closures_here(world, key="private")
    world.offer(declared={"plugins": {KEY: {"settings": [{"key": key, "type": "list"}]}}})
    with pytest.raises(pluginpage.Refused, match="closures"):
        pluginpage.change(world.home, KEY, {key: [str(world.tmp / "nothing")]})
    assert closed.closures(world.home) == [str(secret)]


def test_C1_nothing_is_changed_in_a_sources_file_that_is_the_closures_file(world):   # must refuse
    _closures_here(world)
    world.offer()
    with pytest.raises(pluginpage.Refused, match="also your closures file"):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert cfg(world)["project"] == "alpha"


def test_C1_format_keys_in_the_sources_file_do_not_make_it_the_closures_file(world):   # must pass
    # the closures-file format is read only in a closures file: such keys in the sources file mean nothing there,
    # so it is an ordinary sources file to the page, and its format keys are never touched by a proposal
    d = cfg(world)
    d.update({"schema": "estate.closures/0", "closed_paths": [str(world.tmp / "shut")], "closed_paths_complete": True})
    write_cfg(world.cfg, d)
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    after = cfg(world)
    assert after["project"] == "alpha" and after["closed_paths_complete"] is True   # proposed, nothing written
    with pytest.raises(pluginpage.Refused, match="Semantext's own or of your closures"):
        pluginpage._no_reserved(world.home, ["closed_paths_complete"])               # a reserved key, as a setting


def test_C1_no_settings_form_is_offered_on_a_sources_file_that_is_the_closures_file(world):   # must refuse
    _closures_here(world)
    world.offer()
    row = next(r for r in view.answer("plugins", home=world.home)["plugins"] if r["key"] == KEY)
    assert row["can"]["change"] is False and "closures file" in row["change_note"]


def test_C1_a_settings_form_is_offered_on_an_ordinary_sources_file(world):   # must pass
    world.offer()
    row = next(r for r in view.answer("plugins", home=world.home)["plugins"] if r["key"] == KEY)
    assert row["can"]["change"] is True and row["change_note"] is None


def test_C1_a_closures_file_of_its_own_leaves_the_sources_file_changeable(world):   # must pass
    own = world.tmp / "closures.json"
    own.write_text(json.dumps({"private": []}), encoding="utf-8")
    d = cfg(world)
    d.pop("closed")
    d.update({"closures_file": str(own), "closures_key": "private"})
    write_cfg(world.cfg, d)
    world.offer()
    apply(world.home, KEY, {"project": "beta"})
    assert cfg(world)["project"] == "beta" and json.loads(own.read_text(encoding="utf-8")) == {"private": []}


def test_C1_over_http(served, world):   # must refuse
    secret = _closures_here(world)
    world.offer(declared={"plugins": {KEY: {"settings": [{"key": "private", "type": "list"}]}}})
    code, _ = post(served, "settings", {"plugin": KEY, "settings": {"private": [str(world.tmp / "x")]}}, **PAGE)
    assert code == 400 and closed.closures(world.home) == [str(secret)]


def test_C1_a_rollback_into_a_closures_file_is_refused(world):   # must refuse
    world.offer()
    made = apply(world.home, KEY, {"project": "beta"})
    d = cfg(world)
    d.update({"closures_file": str(world.cfg), "closures_key": "closed"})
    write_cfg(world.cfg, d)
    with pytest.raises(pluginpage.Refused, match="also your closures file"):
        pluginpage.roll_back(world.home, made["n"])


LIST = {"plugins": {KEY: {"settings": [{"key": "tags", "type": "list"}]}}}


def test_a_list_that_gains_an_entry_is_labelled_widens(world):   # its entries may be paths
    world.offer(declared=LIST)
    d = cfg(world)
    d["tags"] = ["a"]
    write_cfg(world.cfg, d)
    assert proposed_label(world, {"tags": ["a", WIDE]}) == "widens"
    assert proposed_label(world, {"tags": [WIDE]}) == "widens"


def test_a_list_that_only_loses_entries_is_labelled_narrows(world):   # must pass
    world.offer(declared=LIST)
    d = cfg(world)
    d["tags"] = ["a", "b"]
    write_cfg(world.cfg, d)
    assert proposed_label(world, {"tags": ["b"]}) == "narrows"
    pluginpage._RECENT.clear()
    apply(world.home, KEY, {"tags": ["b"]})
    assert cfg(world)["tags"] == ["b"]


# ---- Q1: a plug-in's name, and every word of the line to type --------------------------------------------------------
@pytest.mark.parametrize("name", ["source.x$(calc)", "source.a;calc", "source.a b", "source.a.b", "source.`id`",
                                  "source.a|b", "source.é"])
def test_Q1_a_name_that_is_not_a_plain_word_is_never_listed(world, name):   # must refuse
    world.offer(name, declared=None)
    got = view.answer("plugins", home=world.home)
    assert name not in [r["key"] for r in got["plugins"]]
    assert any(p["kind"] == "bad name" for p in registry.installed()[1])
    with pytest.raises(pluginpage.Refused) as e:
        pluginpage.turn_on(world.home, name)
    assert not isinstance(e.value, pluginpage.AtTheTerminal)   # no line to type is ever made of it


def test_Q1_a_plain_name_is_listed_with_its_line(world):   # must pass
    world.offer("source.ok-name_1", declared=None)
    got = view.answer("plugins", home=world.home)
    r = next(r for r in got["plugins"] if r["key"] == "source.ok-name_1")
    assert r["on_command"].endswith("plugins enable source.ok-name_1")


@pytest.mark.parametrize("word", ["a b", "$(calc)", "`id`", "a;b", "it's", "x|y", "a&b", "a’b", "%x%", "a^b"])
def test_Q1_no_word_of_the_line_is_free_text(word):   # must refuse: a word that is not plain is never put in a line
    for shell in ("posix", "powershell"):
        with pytest.raises(ValueError, match="plain word"):
            pluginpage.command(None, "plugins", word, shell=shell)


def test_Q1_plain_words_stay_bare():   # must pass
    assert pluginpage.command(None, "plugins", "enable", "source.ok-1", shell="posix").endswith(
        " plugins enable source.ok-1")


# ---- P1: change-and-revert ---------------------------------------------------------------------------------------
def test_P1_a_proposal_is_not_applied_after_its_own_key_changed(world):   # must refuse
    world.offer(declared={"plugins": {KEY: {"settings": [{"key": "tickets", "type": "path"},
                                                         {"key": "project", "type": "text"}]}}})
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    made = apply(world.home, KEY, {"tickets": str(world.old / "inner")})   # its own key, changed and back
    apply_back(world.home, made["n"])
    with pytest.raises(pluginpage.Refused, match="stale|superseded"):
        pluginpage.proposal(world.home, e.value.proposal)


def test_P1_a_change_and_back_of_another_key_leaves_it_confirmable(world):   # must pass: no refusal by noise
    world.offer(declared={"plugins": {KEY: {"settings": [{"key": "tickets", "type": "path"},
                                                         {"key": "project", "type": "text"}]}}})
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    made = apply(world.home, KEY, {"project": "gamma"})
    apply_back(world.home, made["n"])
    assert pluginpage.confirm(world.home, e.value.proposal)["confirms"] == e.value.proposal


def test_P1_a_proposal_with_nothing_after_it_is_confirmed(world):   # must pass
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    assert pluginpage.confirm(world.home, e.value.proposal)["confirms"] == e.value.proposal


def test_P1_turning_another_plug_in_off_after_a_proposal_leaves_it_confirmable(world):   # must pass (A7 of round 5)
    world.offer()
    world.offer("source.other", declared=None, on=True, name="semantext-other", module="semantext_other")
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": WIDE})
    pluginpage.turn_off(world.home, "source.other")
    assert pluginpage.proposal(world.home, e.value.proposal)["n"] == e.value.proposal


# ---- R1: the rate under threads -----------------------------------------------------------------------------------
def test_R1_the_rate_holds_under_threads(home):   # must refuse past it, and pass up to it
    pluginpage._RECENT.clear()
    was = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        ok, bar = [], threading.Barrier(100)

        def go():
            bar.wait()
            try:
                pluginpage._gate(home)
                ok.append(1)
            except pluginpage.Refused:
                pass
        ts = [threading.Thread(target=go) for _ in range(100)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    finally:
        sys.setswitchinterval(was)
    assert len(ok) == pluginpage.PAGE_RATE


# ---- L1: a change never stands unrecorded ---------------------------------------------------------------------------
def test_L1_a_rotation_that_fails_changes_nothing(world, monkeypatch):   # must refuse
    world.offer(declared=TEXT_TICKETS)
    apply(world.home, KEY, {"tickets": "a"})
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": "b" * 400})
    monkeypatch.setattr(pluginpage, "MAX_LOG", 600)

    def fails(src, dst):
        raise OSError(13, "the rotation cannot be made")
    with monkeypatch.context() as m:
        m.setattr(pluginpage.os, "replace", fails)   # the rotation fails
        with pytest.raises(OSError):
            pluginpage.confirm(world.home, e.value.proposal)
    assert cfg(world)["tickets"] == "a"
    (world.home / pluginpage.ROTATED).mkdir()   # the rotated name is a folder: refused before anything is changed
    with pytest.raises(pluginpage.Refused, match="is a folder"):
        pluginpage.confirm(world.home, e.value.proposal)
    assert cfg(world)["tickets"] == "a"


def test_L1_a_record_that_cannot_be_written_changes_nothing(world, monkeypatch):   # must refuse
    world.offer()
    before = cfg(world)
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "beta"})

    def full(fd, data):
        os.close(fd)
        raise OSError(28, "no space left on the device")
    monkeypatch.setattr(pluginpage, "_write", full)
    with pytest.raises(OSError):
        pluginpage.confirm(world.home, e.value.proposal)
    assert cfg(world) == before


def test_L1_with_room_the_change_is_made_and_recorded(world):   # must pass
    world.offer()
    made = apply(world.home, KEY, {"project": "beta"})
    assert cfg(world)["project"] == "beta" and pluginpage.changes(world.home)[0][-1]["n"] == made["n"]


# ---- paths that Windows reads apart from how they look ----------------------------------------------------------
@pytest.mark.parametrize("make", [
    lambda o: "\\/?\\" + o + "\\sub", lambda o: "/\\?\\" + o + "\\sub", lambda o: "//?/" + o + "/sub",
    lambda o: "\\\\.\\" + o, lambda o: "\\??\\" + o,
    lambda o: o + "\\..:$DATA", lambda o: o + "\\in.txt:ads", lambda o: o + "\\sub\\..::$INDEX_ALLOCATION",
    lambda o: o + "\\CON", lambda o: o + "\\nul.txt", lambda o: o + "\\COM1", lambda o: o + "\\CONIN$",
])
def test_a_path_windows_reads_apart_is_refused(make):   # must refuse
    old = "C:\\data\\old" if os.name == "nt" else "/data/old"
    with pytest.raises(pluginpage.Refused):
        pluginpage._path(make(old), "the setting 't'")


@pytest.mark.parametrize("value", ["C:/data/old/sub", "C:\\data\\old\\con-notes", "C:\\data\\old\\nullable"]
                         if os.name == "nt" else ["/data/old/sub", "/data/old/con-notes", "/data/old/nullable"])
def test_a_plain_path_is_kept(value):   # must pass
    assert pluginpage._path(value, "t") == value
