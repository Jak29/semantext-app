"""How a plug-in's last call ended, kept by the kernel for the Plug-ins tab (outside.health). Each rule has both arms:
what must pass and what must be refused. The words kept are the kernel's, never the plug-in's."""
from __future__ import annotations

import threading

import pytest

from semantext import outside


def test_a_plug_in_that_made_no_call_has_no_last_call():   # must refuse: nothing is made up
    assert outside.health("source.never-called") == {"last": None, "loading": None, "holding": 0}


def test_loading_it_is_kept_apart_from_its_own_work():   # must refuse: an import is not a read that answered
    outside.run(lambda: 1, owner="source.health-load", budget=2, call="import")
    got = outside.health("source.health-load")
    assert got["last"] is None and got["loading"]["call"] == "import"
    outside.run(lambda: 1, owner="source.health-load", budget=2, call="read")
    outside.run(lambda: 1, owner="source.health-load", budget=2, call="signature")
    got = outside.health("source.health-load")
    assert got["last"]["call"] == "read" and got["loading"]["call"] == "signature" and "t" not in got["last"]


def test_a_call_named_otherwise_is_kept_as_a_call():   # must refuse a name the kernel does not use
    outside.run(lambda: 1, owner="source.health-named", budget=2, call="anything <b>")
    assert outside.health("source.health-named")["last"]["call"] == "call"


def test_an_answer_is_kept_as_answered():   # must pass
    assert outside.run(lambda: 1, owner="source.health-ok", budget=2) == 1
    got = outside.health("source.health-ok")
    assert got["last"]["outcome"] == "answered" and got["holding"] == 0
    assert got["last"]["at"].endswith("Z") and got["last"]["seconds"] >= 0


def test_an_error_is_kept_as_an_error_and_never_its_words():   # must refuse its words
    def boom():
        raise ValueError("a plug-in's own words")
    with pytest.raises(RuntimeError):
        outside.run(boom, owner="source.health-boom", budget=2)
    last = outside.health("source.health-boom")["last"]
    assert last["outcome"] == "error" and "own words" not in str(last)


def test_a_late_call_is_kept_as_late_and_counted_as_holding():
    release = threading.Event()
    try:
        with pytest.raises(outside.Late):
            outside.run(lambda: release.wait(10), owner="source.health-late", budget=0.05)
        got = outside.health("source.health-late")
        assert got["last"]["outcome"] == "late" and got["holding"] == 1
        with pytest.raises(outside.Busy):   # the next call is refused at once, and kept as busy
            outside.run(lambda: 1, owner="source.health-late", budget=2)
        assert outside.health("source.health-late")["last"]["outcome"] == "busy"
    finally:
        release.set()


def test_the_record_is_bounded():   # must refuse unbounded growth
    for i in range(outside.MAX_LAST + 5):
        outside.run(lambda: 1, owner=f"source.bound-{i}", budget=2)
    assert len(outside._LAST) <= outside.MAX_LAST
    assert outside.health("source.bound-0")["last"] is None              # the oldest went
    assert outside.health(f"source.bound-{outside.MAX_LAST + 4}")["last"]["outcome"] == "answered"   # the newest stays
