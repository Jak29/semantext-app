"""The recheck of the api 0.2 fix round at 17021c2 (RECHECK_api02_17021c2): calls counted against the wrong plug-in
(V, and NH3 through it), the global cap of hanging calls, a wait for a turn counted as hanging (NH1's residual), and a
signature that could not be read taken as "no ctx" (NH4). Each test fails on 17021c2 and says whether its arm must
pass or must refuse."""
from __future__ import annotations

import json
import threading
import time
import types

import pytest

from semantext import outside


def _plugin_threads() -> int:
    return sum(t.name == "semantext-plugin" and t.is_alive() for t in threading.enumerate())


def _drained(timeout: float = 5.0) -> None:
    """Wait for every plug-in thread a test left to finish, so the next test starts from none."""
    end = time.monotonic() + timeout
    while _plugin_threads() and time.monotonic() < end:
        time.sleep(0.01)


@pytest.fixture
def release():
    """An event every hanging call in a test waits on; set at the end, so no thread outlives the test."""
    ev = threading.Event()
    yield ev
    ev.set()
    _drained()


@pytest.fixture
def offered(monkeypatch, home, tmp_path):
    """offer("<kind>.<name>", obj): an installed package declaring obj, turned on in the home."""
    import importlib.metadata
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


def _place(name, build, **more):
    return type(name.title(), (), {"kind": "place", "name": name, "title": name.title(), "build": build, **more})()


# ---- item 1 (V, and NH3 through it). calls are counted against the plug-in's registration name -----------------------
def test_a_call_names_whose_it_is():   # must refuse: no call is counted against the callable it is given
    with pytest.raises(TypeError):
        outside.run(lambda: 1)
    with pytest.raises(TypeError):
        f = (lambda: 1)
        outside.run(f, owner=f)
    assert outside.run(lambda: 1, owner="place.p") == 1


def test_two_plug_ins_sharing_a_helper_are_counted_apart(home, offered, monkeypatch, release):   # must pass
    from semantext.sources import view
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    hang = threading.Event()

    def shared(sources, ctx=None):   # one module-level helper, as a shared base class gives it
        if hang.is_set():
            release.wait(10)
        return {"fine": True}
    offered("place.p1", _place("p1", staticmethod(shared)))
    offered("place.p2", _place("p2", staticmethod(shared)))
    hang.set()
    assert view.answer("p1", home=home)["off"] is True      # p1's call passes its budget and still runs
    hang.clear()
    assert view.answer("p2", home=home).get("fine") is True   # p2 is its own plug-in: never Busy for p1's call


def test_a_plug_in_bound_to_anothers_object_is_counted_as_itself(home, offered, monkeypatch, release):   # must pass
    from semantext.sources import view
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")

    class B:
        kind, name, title = "place", "b", "B"

        def build(self, sources, ctx=None):
            return {"b": "fine"}
    victim = B()

    def slow(self, sources, ctx=None):
        release.wait(10)
        return {}
    a = _place("a", None)
    a.build = types.MethodType(slow, victim)   # A's build is bound to B's own object
    offered("place.b", victim)
    offered("place.a", a)
    assert view.answer("a", home=home)["off"] is True
    assert view.answer("b", home=home).get("b") == "fine"


def _hanging_resolve(release):
    def r(row_id, ctx=None):
        release.wait(10)
        return None
    return r


def test_a_place_with_a_fresh_resolve_on_every_load_holds_its_own_share(home, monkeypatch, release):   # must refuse
    from semantext import docserve
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.1")

    class Fresh:
        kind, name, title = "place", "fresh", "F"

        @property
        def resolve(self):   # a new function on every read, and load_enabled snapshots on every serve
            return _hanging_resolve(release)

        def check_bytes(self, data):
            return None
    for _ in range(8):
        snap = outside.snapshot(Fresh())
        monkeypatch.setattr(docserve, "_place", lambda name, h, s=snap: s)
        with pytest.raises(docserve.Refused):
            docserve.serve("fresh", "r1", home)
    assert outside._hanging() <= outside.MAX_IN_FLIGHT   # its calls are one plug-in's: 8 serves made at most 4 threads
    good = type("Good", (), {"resolve": staticmethod(lambda row_id: None), "check_bytes": staticmethod(lambda d: None)})()
    monkeypatch.setattr(docserve, "_place", lambda name, h: good)
    with pytest.raises(docserve.Refused) as e:
        docserve.serve("good", "r1", home)
    assert "last read" in e.value.why   # it was asked, never refused as Busy


def test_static_methods_of_one_place_are_one_plug_in(home, offered, monkeypatch, release):   # must refuse
    from semantext import docserve
    from semantext.sources import view
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.1")

    def build(sources, ctx=None):
        release.wait(10)
        return {}

    def resolve(row_id, ctx=None):
        release.wait(10)

    offered("place.st", _place("st", staticmethod(build), resolve=staticmethod(resolve),
                               check_bytes=staticmethod(lambda data: None)))
    assert view.answer("st", home=home)["off"] is True   # its build passes its budget and still runs
    for _ in range(4):
        with pytest.raises(docserve.Refused):
            docserve.serve("st", "r1", home)
    assert outside._hanging() <= 1   # build and resolve are one plug-in's calls: the rest are its own Busy


# ---- item 2 (NH3). each plug-in holds a fair share of the global cap, and who holds it is named ---------------------
def _hang(owner, release, budget=0.05):
    """One call under `owner` that passes its budget and still runs until release is set."""
    with pytest.raises(outside.Late):
        outside.run(lambda: release.wait(10), owner=owner, budget=budget)


def _at_once(n, call):
    out = []

    def one():
        try:
            out.append(call())
        except outside.Busy:
            out.append("Busy")
        except outside.Late:
            out.append("Late")
    ts = [threading.Thread(target=one) for _ in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    return out


def test_one_plug_in_holds_at_most_its_share_and_others_are_still_called(release):   # must refuse the hog
    got = _at_once(12, lambda: outside.run(lambda: release.wait(10), owner="source.hog", budget=0.2))
    assert set(got) <= {"Late", "Busy"}
    assert outside.holding()["source.hog"] <= outside.MAX_IN_FLIGHT
    assert outside.run(lambda: "answered", owner="source.fine", budget=2) == "answered"


def test_a_full_cap_names_the_plug_ins_holding_it(monkeypatch, release):   # must refuse, and say who
    monkeypatch.setattr(outside, "MAX_HANGING", 2)
    _hang("source.alpha", release)
    _hang("place.beta", release)
    assert outside.holding() == {"place.beta": 1, "source.alpha": 1}
    with pytest.raises(outside.Busy) as e:
        outside.run(lambda: 1, owner="place.innocent", budget=2)
    assert "source.alpha" in str(e.value) and "place.beta" in str(e.value)


def test_the_page_names_the_plug_ins_holding_calls(home, release):   # must refuse to be silent
    from semantext.sources import view
    _hang("place.hog", release)
    got = view.answer("waiting", home=home)
    said = [p for p in got["frame"]["problems"] if "place.hog" in str(p.get("text"))]
    assert said and said[0]["reader"] == "plug-ins"


def test_semantext_plugins_names_the_plug_ins_holding_calls(home, release):   # must refuse to be silent
    from semantext import plugincmd
    _hang("place.hog", release)
    out = []
    assert plugincmd.run(home, "list", None, out.append) == 0
    assert any("place.hog" in line for line in out)


def test_nothing_is_said_when_nothing_hangs(home):   # must pass
    from semantext.sources import view
    assert outside.holding() == {}
    got = view.answer("waiting", home=home)
    assert not [p for p in got["frame"]["problems"] if p.get("kind") == "calls still running"]

# ---- item 3 (NH1's residual). a wait for a turn never makes a call hanging ------------------------------------------
def test_a_call_that_waited_its_turn_gets_its_whole_budget_to_run(monkeypatch):   # must pass
    monkeypatch.setattr(outside, "MAX_IN_FLIGHT", 1)

    def first():
        time.sleep(0.5)
        return "first"

    def second():
        time.sleep(0.8)   # started at about 0.5 s: past the budget counted from when it asked, inside its own
        return "second"
    t = threading.Thread(target=lambda: outside.run(first, owner="place.p", budget=1.0))
    t.start()
    time.sleep(0.05)
    assert outside.run(second, owner="place.p", budget=1.0) == "second"
    t.join(5)
    assert outside.holding() == {}


def test_a_call_that_never_got_a_turn_is_late_and_says_so(monkeypatch, release):   # must refuse, honestly
    monkeypatch.setattr(outside, "MAX_IN_FLIGHT", 1)
    t = threading.Thread(target=lambda: outside.run(lambda: release.wait(10), owner="place.p", budget=5))
    t.start()
    time.sleep(0.05)
    with pytest.raises(outside.Late) as e:
        outside.run(lambda: "never", owner="place.p", budget=0.3)
    assert not isinstance(e.value, outside.Busy)
    assert "waited for a turn and none came in time" in str(e.value)
    assert outside.holding() == {}   # it never ran, so it is not hanging, and neither is the call that held the turn
    release.set()
    t.join(5)


def test_many_well_behaved_calls_are_answered_or_late_never_hanging():   # must pass
    def call():
        time.sleep(0.4)
        return "answered"
    got = _at_once(24, lambda: outside.run(call, owner="place.busy", budget=1.0))
    assert "Busy" not in got and len(got) == 24
    assert got.count("answered") >= 8
    assert outside.holding() == {}

# ---- item 4 (NH4). a signature that cannot be read is never taken as "no ctx" ---------------------------------------
class NoSig:
    """A callable whose signature cannot be read (its __signature__ raises), and which counts how it was called."""

    def __init__(self, answer=None):
        self.calls, self.answer = [], answer

    @property
    def __signature__(self):
        raise RuntimeError("no signature here")

    def __call__(self, *args):
        self.calls.append(len(args))
        return self.answer


class Needs:
    kind, name, title = "place", "needs", "N"

    def __init__(self):
        self.got = []

    def build(self, sources, ctx=None):
        self.got.append(ctx is not None)
        return {"ctx": ctx is not None}


class _Src:
    def __init__(self, reg, home):
        self.got, self.reg, self.home, self.problems, self.spent = {}, reg, str(home), [], 0


def test_a_build_registered_while_the_cap_was_full_is_skipped_then_asked_again(home, monkeypatch, release):   # refuse
    from semantext import registry
    from semantext.sources import view
    monkeypatch.setattr(outside, "MAX_HANGING", 1)
    _hang("place.hog", release)
    nd = Needs()
    reg = registry.Registry()
    entry = reg.add("place", "needs", outside.snapshot(nd), origin="pkg")
    assert entry.reads_ctx is None                   # not known: nothing is kept as "no ctx"
    release.set()
    _drained()
    src = _Src(reg, home)
    got = view._built(entry, src)                     # the same answer, the cap clear by now
    assert nd.got == [] and got["off"] is True       # never called without its ctx
    assert any("needs" in p["source"] and "without" in p["text"] for p in src.problems)
    again = registry.Registry().add("place", "needs", outside.snapshot(nd), origin="pkg")   # the next answer
    assert again.reads_ctx is True
    assert view._built(again, _Src(reg, home)) == {"ctx": True} and nd.got == [True]


def test_a_source_registered_while_the_cap_was_full_is_not_read_without_ctx(home, monkeypatch, release):   # refuse
    from semantext import registry
    from semantext.sources import view
    monkeypatch.setattr(outside, "MAX_HANGING", 1)
    _hang("place.hog", release)
    seen = []

    class Tickets:
        kind, name, title, keys = "source", "tickets", "T", ("tickets",)

        def read(self, config, ctx=None):
            seen.append(ctx is not None)
            return {"off": False, "problems": []}
    reg = view.BUILT_IN.copy()
    entry = reg.add("source", "tickets", outside.snapshot(Tickets()), origin="pkg")
    assert entry.reads_ctx is None
    release.set()
    _drained()
    got, failed, _spent = view._read({}, None, reg, None, home)
    assert seen == [] and got["tickets"]["off"] is True
    assert any(f["reader"] == "tickets" and "without" in f["text"] for f in failed)


def test_a_build_whose_signature_cannot_be_read_is_not_called_without_ctx(home, offered):   # must refuse
    from semantext.sources import view
    build = NoSig({"called": True})
    offered("place.nosig", _place("nosig", build))
    got = view.answer("nosig", home=home)
    assert build.calls == [] and got["off"] is True
    assert any("nosig" in p["source"] for p in got["frame"]["problems"])


def test_a_resolve_whose_signature_cannot_be_read_is_not_called_without_ctx(home, monkeypatch):   # must refuse
    from semantext import docserve
    resolve = NoSig("C:/x")
    place = type("Place", (), {"resolve": resolve, "check_bytes": staticmethod(lambda d: None)})()
    monkeypatch.setattr(docserve, "_place", lambda name, h: place)
    with pytest.raises(docserve.Refused) as e:
        docserve.serve("board", "r1", home)
    assert resolve.calls == [] and e.value.status == 503 and "again" in e.value.why

def test_the_skip_says_what_matters_first_however_long_the_reason(home):   # must refuse to bury it
    from semantext import registry
    from semantext.sources import view
    entry = registry.Entry("place", "needs", "pkg", outside.snapshot(Needs()), reads_ctx=None, ctx_trouble="x" * 400)
    src = _Src(registry.Registry(), home)
    got = view._built(entry, src)
    assert "not called without the read context" in got["failed"]
    assert "not called without the read context" in src.problems[0]["text"]