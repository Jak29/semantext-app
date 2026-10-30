"""The audit of the registry (c696d0b) and a second review: "a plug-in never stops the rest" held at load only. Each
test fails on 2fc2736 and says whether its arm must pass or must refuse."""
from __future__ import annotations

import importlib.metadata
import json
import threading
import time

import pytest

from semantext import cli, outside, registry, store
from semantext.sources import closed, view


class Dist:
    def __init__(self, name="semantext-tickets", version="0.1"):
        self.name, self.version = name, version


class Point:
    def __init__(self, name, make, dist=None):
        self.name, self.group, self.dist, self._make, self.loads = name, registry.GROUP, dist or Dist(), make, 0

    def load(self):
        self.loads += 1
        return self._make()


class Tickets:
    kind, name, title, keys = "source", "tickets", "Tickets", ("tickets",)

    def read(self, config):
        return {"off": False, "count": 2, "problems": [{"source": "t", "line": 1, "kind": "shape", "text": "x"}]}


class Board:
    kind, name, title = "place", "board", "Board"

    def build(self, sources):
        return {"tickets": sources["tickets"].get("count")}


@pytest.fixture
def offered(monkeypatch, home, tmp_path):
    points = []
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"tickets": "t", "closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    return points


def turn_on(home, *keys, dist=None):
    d = dist or Dist()
    registry.write_enabled({k: {"origin": d.name, "version": d.version, "at": "x"} for k in keys}, home)


def source(read):
    return type("S", (Tickets,), {"read": read})


def place(build):
    return type("P", (Board,), {"build": build})


# ---- (a) a key two packages declare loads neither, and says why --------------------------------------------------
def test_a_key_declared_by_two_packages_loads_neither_and_names_both(home, offered):   # must refuse
    offered += [Point("source.tickets", Tickets, Dist("pkg-one", "1")), Point("source.tickets", Tickets, Dist("pkg-two", "2"))]
    found, problems = registry.installed()
    assert found == [] and [p["kind"] for p in problems] == ["declared twice"]
    assert "pkg-one 1" in problems[0]["text"] and "pkg-two 2" in problems[0]["text"]
    turn_on(home, "source.tickets", dist=Dist("pkg-two", "2"))
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "tickets") is None and offered[0].loads == offered[1].loads == 0
    assert any(p["kind"] == "declared twice" for p in reg.problems)


def test_enable_says_a_key_is_declared_twice(home, offered, monkeypatch):   # must refuse
    offered += [Point("source.tickets", Tickets, Dist("pkg-one", "1")), Point("source.tickets", Tickets, Dist("pkg-two", "2"))]
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    with pytest.raises(store.Refused, match="declare source.tickets"):
        from semantext import plugincmd
        plugincmd._enable("source.tickets", home, print, ask=lambda _: "source.tickets")


def test_one_package_declaring_a_key_still_loads(home, offered):   # must pass
    offered.append(Point("source.tickets", Tickets))
    turn_on(home, "source.tickets")
    assert registry.load_enabled(view.BUILT_IN, home).get("source", "tickets") is not None


# ---- R1: an attribute that raises is a problem line, never a page that goes down --------------------------------
class Raises:
    kind, name, keys = "source", "tickets", ("tickets",)

    @property
    def title(self):
        raise ValueError("a property with a bug")

    def read(self, config):
        return {"off": False, "problems": []}


class Exits(Board):
    @property
    def page_module(self):
        raise SystemExit(3)


def test_an_attribute_that_raises_skips_that_plug_in_only(home, offered, capsys):   # must refuse it, keep the rest
    offered += [Point("source.tickets", Raises), Point("place.board", Exits)]
    turn_on(home, "source.tickets", "place.board")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "tickets") is None and reg.get("place", "board") is None
    assert [p["kind"] for p in reg.problems] == ["bad attribute", "bad attribute"]
    said = {p["source"]: p["text"] for p in reg.problems}
    assert "ValueError" in said["plug-in source.tickets"] and "SystemExit" in said["plug-in place.board"]
    got = view.answer("waiting", home=home)
    assert got["place"] == "waiting" and sum(p["kind"] == "bad attribute" for p in got["frame"]["problems"]) == 2
    assert cli.main(["--home", str(home), "plugins"]) == 0


def test_an_attribute_that_is_not_a_plain_value_is_refused(home, offered):   # must refuse
    offered.append(Point("source.tickets", lambda: type("S", (Tickets,), {"title": object()})()))
    turn_on(home, "source.tickets")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "tickets") is None and reg.problems[0]["kind"] == "bad attribute"


def test_after_load_only_the_snapshot_is_read(home, offered):   # must pass: the plug-in's attributes are read once
    reads = []

    class Counted(Tickets):
        @property
        def title(self):
            reads.append(1)
            return "Tickets"
    offered.append(Point("source.tickets", Counted))
    turn_on(home, "source.tickets")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert isinstance(reg.get("source", "tickets").obj, outside.Snapshot) and len(reads) == 1
    view._Sources(home, reg=reg).frame()
    assert len(reads) == 1


# ---- (b) SystemExit, the time budget, the size caps ---------------------------------------------------------------
def test_systemexit_in_a_read_or_a_build_costs_only_that_plug_in(home, offered):   # must refuse it, keep the rest
    def read(self, config):
        raise SystemExit(1)

    def build(self, sources):
        raise SystemExit(2)
    offered += [Point("source.tickets", source(read)), Point("place.board", place(build))]
    turn_on(home, "source.tickets", "place.board")
    got = view.answer("board", home=home)
    assert got["off"] is True and "SystemExit" in got["failed"]
    assert any(p["kind"] == "reader stopped" and "SystemExit" in p["text"] for p in got["frame"]["problems"])


def test_the_persons_own_ctrl_c_goes_through(monkeypatch):   # it arrives on the calling thread, never the worker's
    def interrupted(self, timeout=None):
        raise KeyboardInterrupt
    monkeypatch.setattr(threading.Thread, "join", interrupted)
    with pytest.raises(KeyboardInterrupt):
        outside.run(lambda: 1, owner="source.s")


def test_a_late_read_or_build_is_a_problem_and_its_answer_is_not_used(home, offered, monkeypatch):   # must refuse
    release = threading.Event()

    def read(self, config):
        release.wait(10)
        return {"off": False, "count": 99, "problems": []}

    def build(self, sources):
        release.wait(10)
        return {"tickets": 99}
    offered += [Point("source.tickets", source(read)), Point("place.board", place(build))]
    turn_on(home, "source.tickets", "place.board")
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    try:
        started = time.monotonic()
        got = view.answer("board", home=home)
        assert time.monotonic() - started < 5
        assert got["off"] is True and "did not answer within 0.3 s" in got["failed"]
        assert any("did not answer" in p["text"] for p in got["frame"]["problems"] if p["reader"] == "tickets")
    finally:
        release.set()


def test_a_read_within_its_budget_is_used(home, offered, monkeypatch):   # must pass
    offered += [Point("source.tickets", Tickets), Point("place.board", Board)]
    turn_on(home, "source.tickets", "place.board")
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "5")
    assert view.answer("board", home=home)["tickets"] == 2


def test_problems_are_capped_in_count_and_length(home, offered):   # must refuse the excess
    def read(self, config):
        # many problems, each field long, the whole answer under the 2 MB cap (over it, the answer is not used at all)
        return {"off": False, "problems": [{"source": "s" * 600, "line": 1, "kind": "k", "text": "t" * 600}] * 1000}
    offered.append(Point("source.tickets", source(read)))
    turn_on(home, "source.tickets")
    mine = [p for p in view.answer("waiting", home=home)["frame"]["problems"] if p["reader"] == "tickets"]
    assert len(mine) == outside.MAX_PROBLEMS + 1 and mine[-1]["kind"] == "too many problems"
    assert all(len(p["text"]) <= outside.MAX_TEXT and len(p["source"]) <= outside.MAX_TEXT for p in mine)


def test_an_answer_over_the_size_cap_is_not_used(home, offered):   # must refuse
    def read(self, config):
        return {"off": False, "blob": "x" * (3 * 1024 * 1024), "problems": []}

    def build(self, sources):
        return {"blob": "y" * (3 * 1024 * 1024)}
    offered += [Point("source.tickets", source(read)), Point("place.board", place(build))]
    turn_on(home, "source.tickets", "place.board")
    got = view.answer("board", home=home)
    assert got["off"] is True and "cap" in got["failed"] and "blob" not in got
    assert any("cap" in p["text"] for p in got["frame"]["problems"] if p["reader"] == "tickets")


# ---- (c) an outside place gets a copy, never the live reading -----------------------------------------------------
def test_an_outside_place_cannot_change_what_the_page_reads(home, offered):   # must refuse the change
    def build(self, sources):
        sources["tickets"]["problems"].clear()
        sources["tickets"]["count"] = 1000
        getattr(sources, "problems", []).clear()
        return {"tickets": sources["tickets"]["count"]}
    offered += [Point("source.tickets", Tickets), Point("place.board", place(build))]
    turn_on(home, "source.tickets", "place.board")
    reg = registry.load_enabled(view.BUILT_IN, home)
    src = view._Sources(home, reg=reg)
    body = view._built(reg.get("place", "board"), src)
    assert body == {"tickets": 1000}                                         # it changed its own copy
    assert src.got["tickets"]["count"] == 2 and src.got["tickets"]["problems"]   # and nothing the page reads
    assert any(p["reader"] == "tickets" for p in src.problems)


# ---- (d) what `semantext plugins` prints carries no control character ----------------------------------------------
def test_an_escape_in_a_package_name_is_not_printed(home, offered, capsys):   # must refuse the escape
    evil = Dist("evil\x1b[2J\x1b]0;owned\x07pkg\r\n", "1\x1b[31m")
    offered.append(Point("source.tickets", Tickets, evil))
    turn_on(home, "source.tickets", dist=Dist("other", "9"))   # a mismatch, so a problem line is printed too
    assert cli.main(["--home", str(home), "plugins"]) == 0
    out = capsys.readouterr().out
    assert "evil\\u001b[2J\\u001b]0;owned\\u0007pkg\\u000d\\u000a 1\\u001b[31m" in out   # seen, as its escapes
    assert not any(c in out for c in "\x1b\x07\r\x9b")


# ---- (e) a sources file that names "closed" twice closes everything ------------------------------------------------
def test_a_doubled_closed_key_fails_closed(tmp_path, monkeypatch):   # must refuse, for plug-ins and built-ins
    f = tmp_path / "sources.json"
    f.write_text('{"closed": ["%s"], "closed": []}' % str(tmp_path / "Private").replace("\\", "\\\\"), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(f))
    assert closed.closures() is None and closed.is_closed_place(tmp_path / "anything.md")
    assert closed.in_closed_place(tmp_path / "anything.md")


def test_one_closed_key_is_read_as_before(tmp_path, monkeypatch):   # must pass
    f = tmp_path / "sources.json"
    f.write_text(json.dumps({"closed": [], "seats": {"closed": 1}}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(f))
    assert closed.closures() == [] and not closed.is_closed_place(tmp_path / "anything.md")


# ---- R5: the list of what is on is written whole and synced ---------------------------------------------------------
def test_the_enabled_list_is_written_through_the_stores_atomic_write(home, monkeypatch):
    seen = []
    real = store.write_atomic
    monkeypatch.setattr(store, "write_atomic", lambda target, data: (seen.append(str(target)), real(target, data)))
    path = registry.write_enabled({"source.x": {"origin": "o", "version": "1", "at": "x"}}, home)
    assert seen == [str(path)] and registry.enabled(home)[0] == {"source.x": {"origin": "o", "version": "1", "at": "x"}}
    assert [p.name for p in path.parent.iterdir()] == ["plugins.json"]   # no temporary file left beside it
