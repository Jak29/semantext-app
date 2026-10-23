"""The gaming reader (sources/gaming.py), on temporary flag files: it reads the inbox's gaming.json the way the inbox's
gaming.py reads it, and never writes it. Every check has a must-pass arm and a must-refuse arm.
"""
from __future__ import annotations

import json
from pathlib import Path

from semantext.sources import gaming, view
from test_v2_page import listing

T0 = 1_791_000_000


def flag(tmp_path: Path, text) -> dict:
    f = tmp_path / "inbox" / "gaming.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(text if isinstance(text, str) else json.dumps(text), encoding="utf-8")
    return {"inbox": str(f.parent)}


def state(cfg, now=T0) -> str:
    return gaming.load(cfg, now)["state"]


def test_on_until_its_end_time_and_off_from_then(tmp_path):
    cfg = flag(tmp_path, {"on": True, "since": "2026-10-23T12:00:00", "until": "2026-10-23T18:00:00",
                          "until_epoch": T0 + 60})
    got = gaming.load(cfg, T0)
    assert got["state"] == "on" and got["until_epoch"] == T0 + 60 and got["until"] == "2026-10-23T18:00:00"
    assert state(cfg, T0 + 59.5) == "on"
    # must-refuse: it lapses at until_epoch, as gaming.py's flag() does
    assert state(cfg, T0 + 60) == "off" and state(cfg, T0 + 3600) == "off"


def test_off_when_lowered_or_missing_or_not_truly_on(tmp_path):
    assert gaming.load({"inbox": str(tmp_path / "inbox")}, T0)["state"] == "off"         # no file is down
    for g in ({"on": False, "until_epoch": T0 + 60}, {"on": True}, {"on": "yes", "until_epoch": T0 + 60},
              {"on": 1, "until_epoch": T0 + 60}, {"on": True, "until_epoch": "soon"}):
        assert state(flag(tmp_path, g)) == "off", g
    assert state(flag(tmp_path, {"on": True, "until_epoch": T0 + 60})) == "on"           # must pass beside them


def test_unknown_when_the_flag_cannot_be_read(tmp_path):
    for bad in ("not json", "[1, 2]", '"on"', "", '{"on": true, "until_epoch": Infinity}',
                json.dumps({"on": True, "until_epoch": T0 * 1000})):                     # milliseconds as seconds
        got = gaming.load(flag(tmp_path, bad), T0)
        assert got["state"] == "unknown" and got["why"], bad
    (tmp_path / "inbox" / "gaming.json").write_bytes(b'{"on": true, "until_epoch": \xff}')
    assert state({"inbox": str(tmp_path / "inbox")}) == "unknown"
    # must-refuse: a flag within the button's six hours (and gaming.py's ten minutes of slack) is read, not unknown
    assert state(flag(tmp_path, {"on": True, "until_epoch": T0 + 6 * 3600 + 600})) == "on"
    assert state(flag(tmp_path, {"on": True, "until_epoch": T0 + 6 * 3600 + 601})) == "unknown"


def test_the_file_comes_from_the_gaming_key_else_the_inbox_folder(tmp_path):
    own = tmp_path / "elsewhere.json"
    own.write_text(json.dumps({"on": True, "until_epoch": T0 + 60}), encoding="utf-8")
    cfg = flag(tmp_path, {"on": False})
    assert state(cfg) == "off" and gaming.path_of(cfg) == tmp_path / "inbox" / "gaming.json"
    assert state({**cfg, "gaming": str(own)}) == "on" and gaming.path_of({**cfg, "gaming": str(own)}) == own
    # must-refuse: with neither key, there is no flag to read, and the reader says it is off
    assert gaming.load({}, T0) == {"off": True, "state": "off", "file": None, "missing": ["gaming"]}


def test_the_new_readers_have_no_call_that_could_write_a_file():
    from test_sources_cards import writers
    for module in (gaming, view):
        source = Path(module.__file__).read_text(encoding="utf-8")
        # view.py's "replace" calls are str.replace on text it shows (a name check cannot tell them from Path.replace)
        assert [w for w in writers(source) if not (module is view and w == "replace")] == [], module.__name__
        assert "subprocess" not in source and "gaming.py --" not in source
    # must-refuse: the same check finds a planted write
    assert writers(Path(gaming.__file__).read_text(encoding="utf-8") + "\nPath('x').write_text('on')") == ["write_text"]


def test_the_frame_carries_the_flag_and_nothing_is_written(tmp_path, monkeypatch):
    cfg = flag(tmp_path, {"on": True, "until_epoch": 4_000_000_000})                   # beyond six hours from now
    config = tmp_path / "sources.json"
    config.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(config))
    before = listing(tmp_path)
    assert view.answer("waiting")["frame"]["gaming"]["state"] == "unknown"
    (tmp_path / "inbox" / "gaming.json").write_text("{}", encoding="utf-8")
    assert view.answer("sources")["frame"]["gaming"]["state"] == "off"
    assert view.answer("sources")["keys"]["gaming"] is None
    after = listing(tmp_path)
    # must-refuse: the only change is the one this test made itself
    assert {k for k in after if after[k] != before.get(k)} == {str(Path("inbox") / "gaming.json")}
