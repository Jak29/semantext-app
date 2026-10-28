"""The audit of api 0.2 at 784faf6 (VERDICT_api02_784faf6): seven behaviour findings and four protection items.
Each test fails on 784faf6 and says whether its arm must pass or must refuse."""
from __future__ import annotations

import asyncio
import importlib.metadata
import json

import pytest

from semantext import docserve, outside, registry
from semantext.sources import view


class Dist:
    name, version = "semantext-probe", "0.1"


class Point:
    def __init__(self, name, make):
        self.name, self.group, self.dist, self._make = name, registry.GROUP, Dist(), make

    def load(self):
        return self._make()


@pytest.fixture
def offered(monkeypatch, home, tmp_path):
    points = []
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"tickets": "t", "closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    return points


def turn_on(home, *keys):
    registry.write_enabled({k: {"origin": Dist.name, "version": Dist.version, "at": "x"} for k in keys}, home)


class Custom(BaseException):
    """A BaseException of a plug-in's own."""


RAISED = [KeyboardInterrupt, GeneratorExit, asyncio.CancelledError, Custom, SystemExit]


# ---- 1. a BaseException from the worker is the plug-in's ---------------------------------------------------------
@pytest.mark.parametrize("kind", RAISED)
def test_any_base_exception_from_a_read_or_a_build_costs_only_that_plug_in(home, offered, kind):   # must refuse it
    def boom(*_a):
        raise kind()
    offered += [Point("source.tickets", lambda: type("S", (), {"kind": "source", "name": "tickets", "title": "T",
                                                               "keys": ("tickets",), "read": boom})()),
                Point("place.board", lambda: type("P", (), {"kind": "place", "name": "board", "title": "B",
                                                            "build": boom})())]
    turn_on(home, "source.tickets", "place.board")
    got = view.answer("board", home=home)                  # answers: nothing escaped
    assert got["off"] is True and kind.__name__ in got["failed"]
    assert any(p["kind"] == "reader stopped" and kind.__name__ in p["text"] for p in got["frame"]["problems"])


@pytest.mark.parametrize("kind", RAISED)
def test_any_base_exception_from_resolve_or_check_is_refused_not_raised(home, monkeypatch, kind):   # must refuse it
    def boom(*_a):
        raise kind()

    class Place:
        resolve = staticmethod(boom)
        check_bytes = staticmethod(boom)
    monkeypatch.setattr(docserve, "_place", lambda name, home: Place())
    with pytest.raises(docserve.Refused) as e:
        docserve.serve("board", "r1", home)
    assert e.value.status == 404


@pytest.mark.parametrize("kind", RAISED)
def test_outside_run_says_every_base_exception_as_a_runtime_error(kind):
    def boom():
        raise kind()
    with pytest.raises(RuntimeError, match=kind.__name__):
        outside.run(boom, owner="source.boom")


# ---- 7. a NUL in the path a place resolves is refused, never a ValueError ------------------------------------------
@pytest.fixture
def rooted(home, tmp_path, monkeypatch):
    """A seats file with one named root (base/d), a closed folder inside it, and the sources file naming both."""
    base = tmp_path / "base"
    (base / "d" / "secret").mkdir(parents=True)
    (base / "A").mkdir()
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"base": str(base), "seats": {"A": {"home": "A"}},
                                 "roots": [{"name": "docs", "path": "d", "kind": "repo"}]}), encoding="utf-8")
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"seats": str(seats), "closed": [str(base / "d" / "secret")]}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    return base


def serving(monkeypatch, path, check=lambda data: None, doc_type="text/plain; charset=utf-8"):
    """The serve hook with a stub place whose resolve gives `path`; the place lookup is the only part stood in."""
    place = type("Place", (), {"resolve": staticmethod(lambda row_id: path), "check_bytes": staticmethod(check),
                               "doc_type": doc_type})()
    monkeypatch.setattr(docserve, "_place", lambda name, home: place)


def status(home, row="r1") -> int:
    with pytest.raises(docserve.Refused) as e:
        docserve.serve("board", row, home)
    return e.value.status


@pytest.mark.parametrize("tail", ["a\x00.svg", "\x00", "sub\x00dir\\a.svg"])
def test_a_nul_in_a_resolved_path_inside_a_root_is_refused(home, rooted, monkeypatch, tail):   # must refuse
    serving(monkeypatch, str(rooted / "d") + "\\" + tail)
    assert status(home) == 404


def test_a_plain_file_inside_a_root_is_served(home, rooted, monkeypatch):   # must pass, beside the arms above
    (rooted / "d" / "a.txt").write_bytes(b"twelve bytes")
    serving(monkeypatch, str(rooted / "d" / "a.txt"))
    assert docserve.serve("board", "r1", home) == (b"twelve bytes", "text/plain; charset=utf-8")

# ---- 3. a hard link inside a root to a closed file is not served ---------------------------------------------------
def test_a_hard_link_to_a_closed_file_is_refused(home, rooted, monkeypatch):   # must refuse
    import os
    shut = rooted / "d" / "secret" / "key.txt"
    shut.write_bytes(b"closed bytes")
    link = rooted / "d" / "innocent.txt"
    try:
        os.link(shut, link)
    except OSError:
        pytest.skip("this volume cannot make a hard link")
    serving(monkeypatch, str(link))
    assert status(home) == 403


def test_a_file_with_one_name_is_still_served(home, rooted, monkeypatch):   # must pass
    (rooted / "d" / "one.txt").write_bytes(b"one name")
    serving(monkeypatch, str(rooted / "d" / "one.txt"))
    assert docserve.serve("board", "r1", home)[0] == b"one name"

# ---- 2. a share, UNC or device spelling of a closed file is closed -------------------------------------------------
windows_only = pytest.mark.skipif(__import__("os").name != "nt", reason="share and device spellings are Windows paths")


def _spellings(f: str) -> dict:
    drive, rest = f[0], f[2:]   # "C", "\Users\..."
    return {"localhost share": f"\\\\localhost\\{drive}$" + rest, "loopback share": f"\\\\127.0.0.1\\{drive}$" + rest,
            "long UNC": f"\\\\?\\UNC\\localhost\\{drive}$" + rest,
            "global root": "\\\\?\\GLOBALROOT\\Device\\HarddiskVolume3" + rest,
            "forward share": f"//localhost/{drive}$" + rest.replace("\\", "/")}


@windows_only
@pytest.mark.parametrize("spelling", ["localhost share", "loopback share", "long UNC", "global root", "forward share"])
def test_a_share_or_device_spelling_of_a_closed_file_is_closed(rooted, spelling):   # must refuse (fails on 784faf6)
    from semantext import api
    from semantext.sources import closed
    f = str(rooted / "d" / "secret" / "key.txt")
    spelled = _spellings(f)[spelling]
    assert api.is_closed_place(spelled) and closed.in_closed_place(spelled)


@windows_only
def test_the_plain_and_long_drive_forms_are_judged_by_where_they_lead(rooted):
    from semantext import api
    inside, outside = str(rooted / "d" / "secret" / "key.txt"), str(rooted / "d" / "open.txt")
    assert api.is_closed_place(inside) and api.is_closed_place("\\\\?\\" + inside)          # must refuse
    assert not api.is_closed_place(outside) and not api.is_closed_place("\\\\?\\" + outside)   # must pass


@windows_only
def test_with_nothing_closed_a_share_path_is_not_closed(tmp_path, monkeypatch):   # must pass: the owner's ruling
    from semantext import api
    from semantext.sources import closed
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    assert not api.is_closed_place("\\\\localhost\\C$\\Users\\x.txt")
    assert not closed.in_closed_place("\\\\localhost\\C$\\Users\\x.txt")


def test_a_folder_reached_by_a_name_no_path_shows_is_closed_by_identity(rooted, monkeypatch, tmp_path):
    import os
    from semantext.sources import closed
    door = tmp_path / "door"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(rooted / "d" / "secret"), str(door))
        else:
            door.symlink_to(rooted / "d" / "secret", target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot make a link")
    (rooted / "d" / "secret" / "key.txt").write_bytes(b"x")
    # stand in for a spelling realpath cannot see through (a subst or mapped drive): forms that resolve nothing
    monkeypatch.setattr(closed, "_forms", lambda p: {os.path.normcase(os.path.normpath(closed._unprefixed(p)))})
    assert closed.is_closed_place(door / "key.txt")                         # must refuse: the same folder by identity
    assert not closed.is_closed_place(rooted / "d" / "open.txt")            # must pass

# ---- 4. one call in flight per plug-in ------------------------------------------------------------------------------
def _plugin_threads() -> int:
    import threading
    return sum(t.name == "semantext-plugin" and t.is_alive() for t in threading.enumerate())


def test_forty_calls_to_a_plug_in_that_hangs_leave_one_thread(monkeypatch):   # must refuse the pile-up
    import threading
    release = threading.Event()

    class Hangs:
        def read(self, config):
            release.wait(10)
            return {}
    plug = Hangs()
    before = _plugin_threads()
    try:
        outcomes = []
        for _ in range(40):
            try:
                outside.run(plug.read, {}, owner="source.plug", budget=0.05)
            except outside.Busy:
                outcomes.append("busy")
            except outside.Late:
                outcomes.append("late")
        assert outcomes == ["late"] + ["busy"] * 39
        assert _plugin_threads() - before <= 1
    finally:
        release.set()


def test_a_busy_plug_in_is_called_again_once_its_last_call_returns():   # must pass
    import threading
    import time
    release = threading.Event()

    class Slow:
        def read(self, config):
            release.wait(10)
            return {"n": 1}
    plug = Slow()
    with pytest.raises(outside.Late):
        outside.run(plug.read, {}, owner="source.plug", budget=0.05)
    release.set()
    for _ in range(100):   # the late call finishes on its own, and gives the plug-in back
        if _plugin_threads() == 0:
            break
        time.sleep(0.02)
    assert outside.run(plug.read, {}, owner="source.plug", budget=2) == {"n": 1}


def test_two_plug_ins_are_counted_apart():   # must pass: one hanging plug-in never blocks another
    import threading
    release = threading.Event()

    class Hangs:
        def read(self, config):
            release.wait(10)

    class Quick:
        def read(self, config):
            return "ok"
    try:
        with pytest.raises(outside.Late):
            outside.run(Hangs().read, {}, owner="source.hangs", budget=0.05)
        assert outside.run(Quick().read, {}, owner="source.quick", budget=2) == "ok"
    finally:
        release.set()

# ---- 5 and 6. the answer is made into bounded JSON in the worker; the caller only parses it -----------------------
def _source(read):
    return type("S", (), {"kind": "source", "name": "tickets", "title": "T", "keys": ("tickets",), "read": read})


def _place(build, name="board"):
    return type("P", (), {"kind": "place", "name": name, "title": "B", "build": build})


class SlowItems(dict):
    def items(self):   # json.dumps calls this; before, on the caller's thread and outside the budget
        __import__("time").sleep(1.5)
        return super().items()


def test_a_slow_answer_is_late_not_waited_for(home, offered, monkeypatch):   # must refuse
    import time
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    offered.append(Point("source.tickets", lambda: _source(lambda self, c: SlowItems(off=False, problems=[]))()))
    turn_on(home, "source.tickets")
    started = time.monotonic()
    got = view.answer("waiting", home=home)
    assert time.monotonic() - started < 1.2
    assert any("did not answer" in p["text"] for p in got["frame"]["problems"] if p["reader"] == "tickets")


class CopyHook:
    def __deepcopy__(self, memo):   # before, view._Copy ran this on the caller's thread for every outside place
        raise AssertionError("a plug-in's __deepcopy__ ran")


def test_an_answer_that_is_not_plain_data_is_refused_in_the_worker(home, offered):   # must refuse
    offered += [Point("source.tickets", lambda: _source(lambda self, c: {"off": False, "x": CopyHook(), "problems": []})()),
                Point("place.board", lambda: _place(lambda self, s: {"seen": sorted(k for k in ("waiting",) if s.get(k))})())]
    turn_on(home, "source.tickets", "place.board")
    got = view.answer("board", home=home)
    assert got.get("off") is not True and got["seen"] == ["waiting"]
    assert any("cannot be written as JSON" in p["text"] for p in got["frame"]["problems"] if p["reader"] == "tickets")


def _nest(n):
    x = "bottom"
    for _ in range(n):
        x = [x]
    return x


@pytest.mark.parametrize("depth", [300, 500, 900])
def test_one_deep_answer_stops_only_its_own_plug_in(home, offered, depth):   # must refuse it, keep the others
    offered += [Point("source.tickets", lambda: _source(lambda self, c: {"off": False, "deep": _nest(depth), "problems": []})()),
                Point("place.good", lambda: _place(lambda self, s: {"ok": True}, "good")())]
    turn_on(home, "source.tickets", "place.good")
    got = view.answer("good", home=home)
    assert got.get("ok") is True and "failed" not in got
    assert any("nested more than" in p["text"] for p in got["frame"]["problems"] if p["reader"] == "tickets")


def test_an_answer_within_the_depth_bound_is_used(home, offered):   # must pass
    offered += [Point("source.tickets", lambda: _source(lambda self, c: {"off": False, "deep": _nest(200), "problems": []})()),
                Point("place.board", lambda: _place(lambda self, s: {"depth_ok": s["tickets"]["deep"] is not None})())]
    turn_on(home, "source.tickets", "place.board")
    got = view.answer("board", home=home)
    assert got.get("depth_ok") is True and not [p for p in got["frame"]["problems"] if p["reader"] == "tickets"]


def test_a_place_answer_is_made_into_json_in_the_worker(home, offered, monkeypatch):   # must refuse
    import time
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    offered.append(Point("place.board", lambda: _place(lambda self, s: SlowItems(x=1))()))
    turn_on(home, "place.board")
    started = time.monotonic()
    got = view.answer("board", home=home)
    assert time.monotonic() - started < 1.2 and got["off"] is True and "did not answer" in got["failed"]

# ---- protection 8. characters that change how a line is shown are taken out of a printed field -------------------
@pytest.mark.parametrize("ch", ["‮", "⁦", "‎", "​", " ", " ", "\U000e0041", "﻿",
                                "\ud800"])
def test_a_display_changing_character_is_not_printed(ch):   # must refuse
    from semantext.plugincmd import shown
    assert shown(f"name{ch}gpj.exe") == "namegpj.exe"


def test_plain_text_in_any_script_is_printed_as_it_is():   # must pass
    from semantext.plugincmd import shown
    for text in ("semantext-board 0.1", "Ó Fíorainn", "日本語のパッケージ", "пакет", "a b\tc"):
        assert shown(text) == text.replace("\t", "")

# ---- protection 9. a key given twice is refused in every file the kernel keeps settings in -----------------------
def test_unique_refuses_a_key_twice_at_any_depth_and_plain_loads_does_not():
    from semantext import jsonread
    with pytest.raises(jsonread.NotJSON, match="given twice"):
        jsonread.loads('{"a": {"b": 1, "b": 2}}', unique=True)                  # must refuse
    assert jsonread.loads('{"a": {"b": 1, "b": 2}}') == {"a": {"b": 2}}         # unchanged without it
    assert jsonread.loads('{"a": [{"b": 1}, {"b": 2}]}', unique=True) == {"a": [{"b": 1}, {"b": 2}]}   # must pass


def _sources(tmp_path, monkeypatch, text):
    cfg = tmp_path / "sources.json"
    cfg.write_text(text, encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    return cfg


def test_a_closures_file_named_twice_makes_the_closures_unknown(tmp_path, monkeypatch):   # must refuse
    from semantext import api
    shut, open_ = tmp_path / "shut", tmp_path / "open"
    (tmp_path / "real.json").write_text(json.dumps({"closed": [str(shut)]}), encoding="utf-8")
    _sources(tmp_path, monkeypatch, '{"closures_file": %s, "closures_file": %s}'
             % (json.dumps(str(tmp_path / "missing.json")), json.dumps(str(tmp_path / "real.json"))))
    assert not api.closures_known() and api.is_closed_place(open_ / "a.txt")


@pytest.mark.parametrize("key", ["closures_key", "seats", "tickets"])
def test_any_key_twice_in_the_sources_file_closes_every_path(tmp_path, monkeypatch, key):   # must refuse
    from semantext import api
    _sources(tmp_path, monkeypatch, '{"closed": [], "%s": "a", "%s": "b"}' % (key, key))
    assert not api.closures_known() and api.is_closed_place(tmp_path / "x.txt")


def test_a_sources_file_with_a_key_twice_is_said_unreadable_on_the_page(home, tmp_path, monkeypatch):   # must refuse
    _sources(tmp_path, monkeypatch, '{"closed": [], "seats": "a.json", "seats": "b.json"}')
    got = view.answer("waiting", home=home)
    assert any(p["kind"] == "unreadable" and "given twice" in p["text"] for p in got["frame"]["problems"])


def test_a_sources_file_with_each_key_once_is_read(tmp_path, monkeypatch):   # must pass
    from semantext import api
    from semantext.sources import load_config
    cfg = _sources(tmp_path, monkeypatch, json.dumps({"closed": [], "seats": "a.json", "tickets": "t"}))
    assert api.closures_known() and not api.is_closed_place(tmp_path / "x.txt")
    assert load_config(cfg)["seats"] == "a.json"


def test_a_plugin_list_that_names_one_twice_turns_nothing_on(home):   # must refuse
    registry.enabled_file(home).parent.mkdir(parents=True, exist_ok=True)
    registry.enabled_file(home).write_text('{"enabled": {"place.board": {"origin": "a"}, "place.board": {"origin": "b"}}}',
                                           encoding="utf-8")
    rows, trouble = registry.enabled(home)
    assert rows == {} and trouble and "given twice" in trouble[0]["text"]
    registry.write_enabled({"place.board": {"origin": "a", "version": "1", "at": "x"}}, home)
    assert list(registry.enabled(home)[0]) == ["place.board"]                    # must pass: written once, read

# ---- note 10. a place's build and its resolve are given the ReadContext of the page's home ------------------------
@pytest.fixture
def elsewhere(home, offered, tmp_path, monkeypatch):
    """A second home, the page started with --home there and no SEMANTEXT_SOURCES: its own sources file closes one
    folder, and the default home's names none."""
    other, shut = tmp_path / "elsewhere", tmp_path / "shut"
    other.mkdir()
    (other / "sources.json").write_text(json.dumps({"tickets": "t", "closed": [str(shut)]}), encoding="utf-8")
    monkeypatch.delenv("SEMANTEXT_SOURCES")
    return other, shut


def test_a_build_that_takes_a_context_judges_by_the_pages_home(elsewhere, offered):   # must refuse the default home's
    from semantext import api
    other, shut = elsewhere

    def build(self, sources, ctx):
        return {"home": ctx.home, "shut": api.is_closed_place(str(shut / "x.txt"), ctx),
                "open": api.is_closed_place(str(other / "x.txt"), ctx)}
    offered.append(Point("place.board", lambda: _place(build)()))
    turn_on(other, "place.board")
    got = view.answer("board", home=other)
    assert (got.get("home"), got.get("shut"), got.get("open")) == (str(other), True, False)


def test_a_build_of_one_argument_is_called_as_before(elsewhere, offered):   # must pass
    other, _shut = elsewhere
    offered.append(Point("place.board", lambda: _place(lambda self, s: {"ok": True})()))
    turn_on(other, "place.board")
    assert view.answer("board", home=other).get("ok") is True


def test_a_resolve_that_takes_a_context_is_given_the_homes(home, rooted, monkeypatch):   # must pass
    (rooted / "d" / "a.txt").write_bytes(b"by ctx")
    seen = []

    def resolve(row_id, ctx):
        seen.append(ctx)
        return str(rooted / "d" / "a.txt")
    place = type("Place", (), {"resolve": staticmethod(resolve), "check_bytes": staticmethod(lambda d: None),
                               "doc_type": "text/plain; charset=utf-8"})()
    monkeypatch.setattr(docserve, "_place", lambda name, h: place)
    assert docserve.serve("board", "r1", home)[0] == b"by ctx"
    assert len(seen) == 1 and seen[0].closures == (str(rooted / "d" / "secret"),)

# ---- note 11. every outside answer of one page together is capped -------------------------------------------------
def _sized(name, kb):
    return Point(f"source.{name}", lambda: type("S", (), {"kind": "source", "name": name, "title": name,
                                                          "keys": ("tickets",),
                                                          "read": lambda self, c: {"off": False, "pad": "x" * (kb * 1024),
                                                                                   "problems": []}})())


def test_the_source_that_would_pass_the_total_is_refused_and_the_rest_kept(home, offered, monkeypatch):   # must refuse
    monkeypatch.setattr(outside, "MAX_TOTAL", 100 * 1024)
    offered += [_sized("one", 40), _sized("two", 40), _sized("three", 40)]
    turn_on(home, "source.one", "source.two", "source.three")
    got = view.answer("waiting", home=home)
    stopped = [p for p in got["frame"]["problems"] if p["kind"] == "reader stopped"]   # the last read, whichever
    assert len(stopped) == 1 and "over the 100 KB they may come to together" in stopped[0]["text"]


def test_a_place_body_counts_with_the_answers_it_was_built_on(home, offered, monkeypatch):   # must refuse
    monkeypatch.setattr(outside, "MAX_TOTAL", 100 * 1024)
    offered += [_sized("one", 60), Point("place.board", lambda: _place(lambda self, s: {"pad": "y" * 60 * 1024})())]
    turn_on(home, "source.one", "place.board")
    got = view.answer("board", home=home)
    assert got["off"] is True and "together" in got["failed"]


def test_answers_under_the_total_are_all_used(home, offered, monkeypatch):   # must pass
    monkeypatch.setattr(outside, "MAX_TOTAL", 100 * 1024)
    offered += [_sized("one", 30), _sized("two", 30), Point("place.board", lambda: _place(lambda self, s: {"ok": 1})())]
    turn_on(home, "source.one", "source.two", "place.board")
    got = view.answer("board", home=home)
    assert got.get("ok") == 1 and not [p for p in got["frame"]["problems"] if p["kind"] == "reader stopped"]

# ---- the span form: resolve -> (path, start, end), one row of a larger file served alone ---------------------------
def _log(rooted, data=b"0123456789"):
    f = rooted / "d" / "log.txt"
    f.write_bytes(data)
    return str(f)


def test_a_span_serves_only_its_bytes_and_checks_only_those(home, rooted, monkeypatch):   # must pass
    checked = []
    serving(monkeypatch, (_log(rooted), 2, 5), check=lambda data: checked.append(data))
    assert docserve.serve("board", "r1", home)[0] == b"234" and checked == [b"234"]


def test_a_span_of_a_file_over_the_cap_is_served_when_the_span_is_under_it(home, rooted, monkeypatch):   # must pass
    monkeypatch.setattr(docserve, "MAX_DOC", 8)
    path = _log(rooted, b"x" * 20 + b"leaf")
    serving(monkeypatch, (path, 20, 24))
    assert docserve.serve("board", "r1", home)[0] == b"leaf"
    serving(monkeypatch, path)
    assert status(home) == 413                                    # must refuse: the whole file is over the cap


def test_a_span_over_the_cap_is_refused(home, rooted, monkeypatch):   # must refuse
    monkeypatch.setattr(docserve, "MAX_DOC", 4)
    serving(monkeypatch, (_log(rooted), 0, 5))
    assert status(home) == 413


def test_a_span_past_the_end_is_refused(home, rooted, monkeypatch):   # must refuse
    serving(monkeypatch, (_log(rooted), 5, 11))
    assert status(home) == 416


class Tup(tuple):
    def __len__(self):   # a plug-in's own code, which would run on the caller's thread
        raise AssertionError("a span's own code ran")


@pytest.mark.parametrize("bad", ["neg", "bool", "float", "empty", "backwards", "two", "four", "subclass", "str end"])
def test_a_span_of_the_wrong_shape_is_refused(home, rooted, monkeypatch, bad):   # must refuse
    p = _log(rooted)
    span = {"neg": (p, -1, 3), "bool": (p, False, True), "float": (p, 0.0, 3), "empty": (p, 3, 3),
            "backwards": (p, 5, 2), "two": (p, 3), "four": (p, 0, 3, 4), "subclass": Tup((p, 0, 3)),
            "str end": (p, 0, "3")}[bad]
    serving(monkeypatch, span)
    assert status(home) == 404


def test_a_span_of_a_closed_file_is_refused(home, rooted, monkeypatch):   # must refuse
    shut = rooted / "d" / "secret" / "key.txt"
    shut.write_bytes(b"closed bytes")
    serving(monkeypatch, (str(shut), 0, 6))
    assert status(home) == 403


def test_a_list_span_is_taken_as_a_tuple_is(home, rooted, monkeypatch):   # must pass
    serving(monkeypatch, [_log(rooted), 0, 3])
    assert docserve.serve("board", "r1", home)[0] == b"012"