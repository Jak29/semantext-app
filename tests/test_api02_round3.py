"""The recheck of the api 0.2 fix round at 4d78973 (RECHECK_api02_4d78973): two new holes, row 1 by a second route,
item 9 for the seats file, and NaN in an outside answer. Each test fails on 4d78973 and says whether its arm must pass
or must refuse."""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from semantext import outside


def _plugin_threads() -> int:
    return sum(t.name == "semantext-plugin" and t.is_alive() for t in threading.enumerate())


def _drained(timeout: float = 5.0) -> None:
    """Wait for every plug-in thread a test left to finish, so the next test starts from none."""
    end = time.monotonic() + timeout
    while _plugin_threads() and time.monotonic() < end:
        time.sleep(0.01)


def _at_once(n, call):
    """n calls of call(), the i-th started i * 20 ms after the first, all overlapping; what each gave, "Busy", or
    "Late". Staggered, so each finds the calls before it already running, as requests from one page do."""
    out = []

    def one(i):
        time.sleep(0.02 * i)
        try:
            out.append(call())
        except outside.Busy:
            out.append("Busy")
        except outside.Late:
            out.append("Late")
    ts = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    return out


# ---- NH1. calls that overlap but are not late are served ------------------------------------------------------------
class Slowish:
    def build(self, sources):
        time.sleep(0.3)
        return {"ok": True}


def test_overlapping_calls_within_the_budget_are_all_answered():   # must pass (1 answered, 3 Busy on 4d78973)
    plug = Slowish()
    got = _at_once(4, lambda: outside.run(plug.build, {}, owner="place.plug", budget=5))
    assert got == [{"ok": True}] * 4
    _drained()


def test_more_overlapping_calls_than_may_run_at_once_wait_their_turn():   # must pass
    plug = Slowish()
    n = outside.MAX_IN_FLIGHT * 2 + 1
    got = _at_once(n, lambda: outside.run(plug.build, {}, owner="place.plug", budget=5))
    assert got == [{"ok": True}] * n
    _drained()


def test_a_call_waiting_its_turn_is_late_when_its_budget_runs_out(monkeypatch):   # must refuse the wait
    monkeypatch.setattr(outside, "MAX_IN_FLIGHT", 1)
    release = threading.Event()

    class Holds:
        def read(self, config):
            release.wait(10)
            return "first"
    plug = Holds()
    first = threading.Thread(target=lambda: outside.run(plug.read, {}, owner="source.plug", budget=5))
    first.start()
    try:
        time.sleep(0.1)
        started = time.monotonic()
        with pytest.raises(outside.Late) as e:
            outside.run(plug.read, {}, owner="source.plug", budget=0.3)
        assert time.monotonic() - started < 2 and not isinstance(e.value, outside.Busy)
    finally:
        release.set()
        first.join(5)
        _drained()


def test_overlapping_calls_on_a_plug_in_that_hangs_hold_few_threads():   # must refuse the pile-up
    release = threading.Event()

    class Hangs:
        def read(self, config):
            release.wait(10)
    plug = Hangs()
    before = _plugin_threads()
    try:
        got = _at_once(12, lambda: outside.run(plug.read, {}, owner="source.plug", budget=0.2))
        assert set(got) <= {"Late", "Busy"} and "Late" in got
        assert _plugin_threads() - before <= outside.MAX_IN_FLIGHT
        with pytest.raises(outside.Busy, match="did not answer in time"):   # the words are true now
            outside.run(plug.read, {}, owner="source.plug", budget=0.2)
    finally:
        release.set()
        _drained()


def test_hanging_calls_are_capped_across_all_plug_ins(monkeypatch):   # must refuse past the cap
    monkeypatch.setattr(outside, "MAX_HANGING", 3)
    release = threading.Event()

    class Hangs:
        def read(self, config):
            release.wait(10)
    before = _plugin_threads()
    outcomes = []
    try:
        for i in range(8):   # eight plug-ins, one call each: the cap is of every plug-in together
            try:
                outside.run(Hangs().read, {}, owner=f"source.h{i}", budget=0.05)
            except outside.Busy:
                outcomes.append("Busy")
            except outside.Late:
                outcomes.append("Late")
        assert outcomes == ["Late"] * 3 + ["Busy"] * 5
        assert _plugin_threads() - before <= 3
    finally:
        release.set()
        _drained()
    assert outside.run(lambda: "back", owner="source.back", budget=2) == "back"   # must pass: once they finish, calls are made again


def test_whose_call_it_is_is_found_without_running_the_plug_ins_code():   # must refuse its code on the caller
    class Owner:
        @property
        def __self__(self):
            raise asyncio.CancelledError()

        def __call__(self):
            return "answered"
    assert outside.run(Owner(), owner="place.owner", budget=2) == "answered"


# ---- NH2. a plug-in's signature is read in the worker, under the budget ---------------------------------------------
class SigProp:
    """A callable whose __signature__ is its own code: it waits, then raises a BaseException."""

    def __init__(self, wait=0.0):
        self.wait = wait

    @property
    def __signature__(self):
        time.sleep(self.wait)
        raise asyncio.CancelledError()

    def __call__(self, *args):
        return {}


def test_a_signature_that_raises_a_base_exception_does_not_escape_registration():   # must refuse the escape
    from semantext import registry
    place = outside.snapshot(type("P", (), {"kind": "place", "name": "p", "title": "P", "build": SigProp()})())
    entry = registry.Registry().add("place", "p", place, origin="pkg")
    assert entry.reads_ctx is None   # not known: never taken as the 0.1 shape (the recheck of 17021c2, NH4)


def test_a_slow_signature_costs_at_most_the_budget(monkeypatch):   # must refuse the wait
    from semantext import registry
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    started = time.monotonic()
    assert registry.takes_ctx(SigProp(wait=3), "place.p") is None
    assert time.monotonic() - started < 1.5
    _drained(5)


def test_a_resolve_whose_signature_raises_is_refused_not_raised(home, monkeypatch):   # must refuse the escape
    from semantext import docserve
    place = type("Place", (), {"resolve": SigProp(), "check_bytes": staticmethod(lambda d: None)})()
    monkeypatch.setattr(docserve, "_place", lambda name, h: place)
    with pytest.raises(docserve.Refused):
        docserve.serve("board", "r1", home)


@pytest.mark.parametrize("shape, want", [(lambda self, s: None, False), (lambda self, s, ctx: None, True),
                                         (lambda self, *a: None, True)])
def test_plain_signatures_are_still_read(shape, want):   # must pass
    from semantext import registry
    obj = type("P", (), {"build": shape})()
    assert registry.takes_ctx(obj.build, "place.p") is want

# ---- row 1. what resolve and check_bytes give is made plain in the worker ------------------------------------------
@pytest.fixture
def rooted(home, tmp_path, monkeypatch):
    """A seats file with one named root (base/d), and the sources file naming it."""
    import json
    base = tmp_path / "base"
    (base / "d").mkdir(parents=True)
    (base / "d" / "a.txt").write_bytes(b"plain bytes")
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"base": str(base), "seats": {}, "roots": [{"name": "docs", "path": "d", "kind": "repo"}]}),
                     encoding="utf-8")
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"seats": str(seats), "closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    return base


def _serving(monkeypatch, got, check=None):
    place = type("Place", (), {"resolve": staticmethod(lambda row_id: got),
                               "check_bytes": staticmethod(lambda data: check),
                               "doc_type": "text/plain; charset=utf-8"})()
    from semantext import docserve
    monkeypatch.setattr(docserve, "_place", lambda name, h: place)


def _served(home):
    from semantext import docserve
    return docserve.serve("board", "r1", home)


class Waits(str):
    """A path whose own __str__ (and __hash__, __eq__) waits, then raises a BaseException."""

    def __str__(self):
        time.sleep(3)
        raise asyncio.CancelledError()

    __hash__ = __eq__ = __fspath__ = None


class WaitsWords:
    def __str__(self):
        time.sleep(3)
        raise asyncio.CancelledError()


class FinePath:
    """An os.PathLike whose __fspath__ is plain and whose __str__ waits."""

    def __init__(self, p):
        self.p = p

    def __fspath__(self):
        return self.p

    def __str__(self):
        time.sleep(3)
        raise asyncio.CancelledError()


@pytest.mark.parametrize("shape", ["path", "span"])
def test_a_str_subclass_from_resolve_is_refused_without_running_its_code(home, rooted, monkeypatch, shape):   # refuse
    from semantext import docserve
    p = Waits(str(rooted / "d" / "a.txt"))
    _serving(monkeypatch, p if shape == "path" else (p, 0, 3))
    started = time.monotonic()
    with pytest.raises(docserve.Refused) as e:
        _served(home)
    assert e.value.status == 404 and time.monotonic() - started < 1


def test_a_path_like_from_resolve_is_read_in_the_worker_and_served(home, rooted, monkeypatch):   # must pass
    _serving(monkeypatch, FinePath(str(rooted / "d" / "a.txt")))
    started = time.monotonic()
    assert _served(home)[0] == b"plain bytes" and time.monotonic() - started < 1


def test_a_pathlib_path_and_a_span_of_one_are_still_served(home, rooted, monkeypatch):   # must pass
    _serving(monkeypatch, rooted / "d" / "a.txt")
    assert _served(home)[0] == b"plain bytes"
    _serving(monkeypatch, (rooted / "d" / "a.txt", 0, 5))
    assert _served(home)[0] == b"plain"


def test_a_check_whose_words_wait_costs_its_budget_and_is_not_served(home, rooted, monkeypatch):   # must refuse
    from semantext import docserve
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    _serving(monkeypatch, str(rooted / "d" / "a.txt"), check=WaitsWords())
    started = time.monotonic()
    with pytest.raises(docserve.Refused) as e:
        _served(home)
    assert e.value.status == 409 and time.monotonic() - started < 1.5
    _drained(5)


def test_a_check_that_says_text_is_still_said(home, rooted, monkeypatch):   # must pass
    from semantext import docserve
    _serving(monkeypatch, str(rooted / "d" / "a.txt"), check="a script in it")
    with pytest.raises(docserve.Refused) as e:
        _served(home)
    assert e.value.status == 409 and "a script in it" in e.value.why


@pytest.mark.parametrize("attr", ["name", "doc_type", "title"])
def test_a_plug_in_attribute_of_a_str_subclass_is_bad(attr):   # must refuse: its __eq__ would run on the caller
    class Sub(str):
        pass
    obj = type("P", (), {"kind": "place", "name": "p", "title": "P", attr: Sub("x")})()
    with pytest.raises(outside.Bad):
        outside.snapshot(obj)


def test_a_list_attribute_holding_a_str_subclass_is_bad():   # must refuse
    obj = type("S", (), {"kind": "source", "name": "s", "keys": (type("Sub", (str,), {})("k"),)})()
    with pytest.raises(outside.Bad):
        outside.snapshot(obj)

# ---- item 9, the seats file. a key given twice is refused, and the named roots close, never widen -------------------
@pytest.fixture
def seated(tmp_path, monkeypatch):
    """A base with a root folder and a narrow folder inside it, a sources file naming the seats file; write(raw)
    replaces the seats file's text."""
    import json
    base = tmp_path / "base"
    (base / "root" / "narrow").mkdir(parents=True)
    (base / "root" / "ok.txt").write_text("x", encoding="utf-8")
    (base / "ana").mkdir()
    seats = tmp_path / "seats.json"
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"seats": str(seats), "closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    b = json.dumps(str(base))

    def write(raw):
        seats.write_text(raw.replace("BASE", b), encoding="utf-8")
    return base, seats, write


TWICE = {
    "roots": '{"base": BASE, "seats": {"ana": {"home": "ana"}}, "roots": [{"name": "r", "path": "root/narrow", '
             '"kind": "repo"}], "roots": [{"name": "w", "path": ".", "kind": "repo"}]}',
    "base": '{"base": BASE, "base": "C:/", "seats": {"ana": {"home": "ana"}}, "roots": [{"name": "r", '
            '"path": "root/narrow", "kind": "repo"}]}',
    "seats": '{"base": BASE, "seats": {"ana": {"home": "ana"}}, "seats": {"bob": {"home": "root"}}, '
             '"roots": [{"name": "h", "path": "{home}", "kind": "repo"}]}',
    "path in a root": '{"base": BASE, "seats": {"ana": {"home": "ana"}}, "roots": [{"name": "r", "path": "root/narrow", '
                      '"path": ".", "kind": "repo"}]}',
    "home in a seat": '{"base": BASE, "seats": {"ana": {"home": "ana", "home": "root"}}, "roots": []}',
}
ONCE = ('{"base": BASE, "seats": {"ana": {"home": "ana"}}, "roots": [{"name": "r", "path": "root/narrow", '
        '"kind": "repo"}, {"name": "h", "path": "{home}", "kind": "repo"}]}')


@pytest.mark.parametrize("which", list(TWICE))
def test_a_key_twice_in_the_seats_file_names_no_roots_and_no_seats(seated, which):   # must refuse: closed, not widened
    from semantext import api
    base, _seats, write = seated
    write(TWICE[which])
    assert api.named_roots() == [] and api.seat_rows() == []
    assert not api.inside_roots(str(base / "root" / "ok.txt"))
    assert not api.inside_roots(str(base / "root" / "narrow" / "n.txt"))


@pytest.mark.parametrize("which", list(TWICE))
def test_each_reader_of_the_seats_file_says_why(seated, which):   # must refuse, with a problem line
    from semantext.sources import cards, places
    from semantext.sources.gates import discover
    _base, seats, write = seated
    write(TWICE[which])
    roots, problems = places.named_roots({"seats": str(seats)})
    assert roots == [] and any("given twice" in p["text"] for p in problems)
    page = places.load({"seats": str(seats)})
    assert page["projects"] == [] and any("given twice" in p["text"] for p in page["problems"])
    said = []
    assert cards._seats(str(seats), said) == [] and any("given twice" in p["text"] for p in said)
    said = []
    assert discover.read_roots(str(seats), said) == ([], []) and any("given twice" in str(p["text"]) for p in said)


def test_a_seats_file_with_each_key_once_is_read(seated):   # must pass
    from semantext import api
    base, _seats, write = seated
    write(ONCE)
    assert sorted(r["name"] for r in api.named_roots()) == ["h", "r"]
    assert [r["seat"] for r in api.seat_rows()] == ["ana"]
    assert api.inside_roots(str(base / "root" / "narrow" / "n.txt"))
    assert not api.inside_roots(str(base / "root" / "ok.txt"))

# ---- R. NaN or Infinity in an outside answer is refused in the worker, never sent bare ------------------------------
NOT_JSON = [float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("v", NOT_JSON)
def test_a_number_json_cannot_carry_is_refused_in_the_worker(v):   # must refuse
    with pytest.raises(RuntimeError, match="NaN or Infinity"):
        outside.run_json(lambda: {"deep": [{"v": v}]}, owner="place.p")


@pytest.fixture
def offered(monkeypatch, home, tmp_path):
    import importlib.metadata
    import json
    from semantext import registry
    points = []
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"tickets": "t", "closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))

    class Dist:
        name, version = "semantext-probe", "0.1"

    class Point:
        def __init__(self, name, obj):
            self.name, self.group, self.dist, self._obj = name, registry.GROUP, Dist(), obj

        def load(self):
            return self._obj

    def offer(key, obj):
        points.append(Point(key, obj))
        registry.write_enabled({p.name: {"origin": Dist.name, "version": Dist.version, "at": "x"} for p in points}, home)
    return offer


def _strict(answer) -> None:
    """The answer as the server writes it, read back as a browser's JSON.parse reads it: no NaN, no Infinity."""
    import json

    def refuse(c):
        raise ValueError(f"bare {c}")
    json.loads(json.dumps(answer, ensure_ascii=False), parse_constant=refuse)


@pytest.mark.parametrize("v", NOT_JSON)
def test_a_place_answering_nan_is_off_with_why_and_the_page_is_json(home, offered, v):   # must refuse
    from semantext.sources import view
    offered("place.board", type("P", (), {"kind": "place", "name": "board", "title": "B",
                                          "build": lambda self, s: {"v": v}})())
    got = view.answer("board", home=home)
    assert got["off"] is True and "NaN or Infinity" in got["failed"]
    _strict(got)


def test_a_source_answering_nan_is_a_problem_line_and_the_rest_are_kept(home, offered):   # must refuse it, keep others
    from semantext.sources import view
    offered("source.tickets", type("S", (), {"kind": "source", "name": "tickets", "title": "T", "keys": ("tickets",),
                                             "read": lambda self, c: {"off": False, "v": float("nan"), "problems": []}})())
    offered("place.board", type("P", (), {"kind": "place", "name": "board", "title": "B",
                                          "build": lambda self, s: {"fine": True}})())
    got = view.answer("board", home=home)
    assert got.get("fine") is True
    assert any("NaN or Infinity" in p["text"] for p in got["frame"]["problems"] if p.get("reader") == "tickets")
    _strict(got)


def test_plain_numbers_are_still_carried(home, offered):   # must pass
    from semantext.sources import view
    offered("place.board", type("P", (), {"kind": "place", "name": "board", "title": "B",
                                          "build": lambda self, s: {"v": 1.5, "big": 1e308, "n": -0.0}})())
    got = view.answer("board", home=home)
    assert (got.get("v"), got.get("big")) == (1.5, 1e308)


def test_the_server_never_writes_a_bare_nan():   # must refuse: an answer that cannot be strict JSON is not sent as one
    import io
    from semantext import server
    h = server.Handler.__new__(server.Handler)
    sent = {}
    h.wfile = io.BytesIO()
    h.send_response = lambda code: sent.setdefault("code", code)
    h.send_header = lambda k, v: None
    h.end_headers = lambda: None
    h._send(200, {"v": float("nan")})
    import json

    def refuse(c):
        raise ValueError(f"bare {c}")
    said = json.loads(h.wfile.getvalue(), parse_constant=refuse)   # the bytes as written, read strictly
    assert sent["code"] == 500 and "NaN or Infinity" in said["error"]