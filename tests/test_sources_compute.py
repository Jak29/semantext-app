"""The compute monitor (sources/compute.py), on a stand-in for the machine. A sign can only add a hold, and only a machine
fully read is free. Every check has a must-pass arm and a must-refuse arm.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from semantext import cli
from semantext.sources import compute, view
from test_sources_cards import writers
from test_v2_page import listing

GAME = r"C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game\bin\win64\deadlock.exe"
T0 = 1_791_000_000


def fails(*a):
    raise OSError("no answer")


def machine(programs=(), screen=5, busy=10.0, memory=50.0, **over):
    """A machine whose processor has been `busy` percent busy since its last reading; the first reading is taken."""
    tick = {"t": 0.0, "idle": 0, "total": 0}

    def times():
        tick["idle"] += int(100 - busy)
        tick["total"] += 100
        return tick["idle"], tick["total"]

    def clock():
        tick["t"] += 10.0   # past both FRESH_S and CPU_GAP_S, so each verdict reads the machine afresh
        return tick["t"]
    fields = {"programs": staticmethod(programs if callable(programs) else lambda: list(programs)),
              "screen": staticmethod(screen if callable(screen) else lambda: screen),
              "cpu_times": staticmethod(times), "memory_free": staticmethod(lambda: memory), "clock": staticmethod(clock)}
    fields.update({k: staticmethod(v) if callable(v) else v for k, v in over.items()})
    signs = type("Machine", (), fields)
    compute._reset()
    compute.verdict({}, T0, signs)   # the first reading of the processor
    return signs


def flag(tmp_path, **g) -> dict:
    f = tmp_path / "inbox" / "gaming.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text(json.dumps(g), encoding="utf-8")
    return {"inbox": str(f.parent)}


def test_a_quiet_machine_fully_read_is_free_and_nothing_else_is():
    assert compute.verdict({}, T0, machine())["verdict"] == "free"
    # must refuse: the very first reading has no processor to compare, so it is not free
    compute._reset()
    signs = machine()
    compute._reset()
    got = compute.verdict({}, T0, signs)
    assert got["verdict"] == "unknown" and any("processor" in n for n in got["not_read"])
    assert got["could_not_tell"] == []


def test_a_game_or_a_full_screen_program_holds_without_the_button():
    got = compute.verdict({}, T0, machine(programs=[GAME]))
    assert got["verdict"] == "hold" and got["games"] == ["deadlock.exe"] and "deadlock.exe" in got["reasons"][0]
    for state in (2, 3):
        assert compute.verdict({}, T0, machine(screen=state))["verdict"] == "hold"
    # must refuse: every other screen state is not a game
    for state in (1, 4, 5, 6, 7):
        assert compute.verdict({}, T0, machine(screen=state))["verdict"] == "free", state


def test_only_the_game_programs_file_name_leaves_never_a_path_or_another_program():
    got = compute.verdict({}, T0, machine(programs=[GAME, r"C:\Users\someone\secret-project\tool.exe"]))
    text = json.dumps(got)
    assert "deadlock.exe" in text and "secret-project" not in text and "tool.exe" not in text and "Steam" not in got["games"]


def test_a_busy_or_short_machine_is_light_work_only():
    assert compute.verdict({}, T0, machine(busy=95.0))["verdict"] == "light"
    assert compute.verdict({}, T0, machine(memory=5.0))["verdict"] == "light"
    # must refuse: just under each line is free
    assert compute.verdict({}, T0, machine(busy=89.0))["verdict"] == "free"
    assert compute.verdict({}, T0, machine(memory=10.0))["verdict"] == "free"


@pytest.mark.parametrize("sign", ["programs", "screen", "cpu_times", "memory_free"])
def test_a_sign_that_cannot_be_read_is_never_a_clear_one(sign):
    got = compute.verdict({}, T0, machine(**{sign: fails}))
    assert got["verdict"] == "unknown" and got["could_not_tell"]
    assert compute.EXIT[got["verdict"]] != 0
    # must refuse: and it never lifts a hold that another sign gives
    if sign != "programs":
        assert compute.verdict({}, T0, machine(programs=[GAME], **{sign: fails}))["verdict"] == "hold"


def test_the_button_holds_and_can_only_add_a_hold(tmp_path):
    cfg = flag(tmp_path, on=True, until_epoch=T0 + 60)
    got = compute.verdict(cfg, T0, machine())
    assert got["verdict"] == "hold" and "button" in got["reasons"][0]
    # must refuse: lowered or lapsed, it lifts nothing the machine shows
    low = flag(tmp_path, on=False)
    assert compute.verdict(low, T0, machine())["verdict"] == "free"
    assert compute.verdict(low, T0, machine(programs=[GAME]))["verdict"] == "hold"
    assert compute.verdict(flag(tmp_path, on=True, until_epoch=T0 + 60), T0 + 60, machine())["verdict"] == "free"


def test_an_unreadable_button_is_never_free_and_never_lifts_a_hold(tmp_path):
    f = tmp_path / "inbox" / "gaming.json"
    f.parent.mkdir()
    f.write_text("not json", encoding="utf-8")
    cfg = {"inbox": str(f.parent)}
    assert compute.verdict(cfg, T0, machine())["verdict"] == "unknown"
    assert compute.verdict(cfg, T0, machine(programs=[GAME]))["verdict"] == "hold"


def test_lowering_the_button_shows_at_once_though_the_machine_is_kept(tmp_path):
    signs = machine()
    signs.clock = staticmethod(lambda: 100.0)   # the clock stands still, so the machine's reading is kept
    compute._reset()
    cfg_low = {}
    compute._KEPT.update(signs=signs, folders=compute.game_folders(cfg_low), at=100.0, machine={"hold": [], "light": [], "trouble": [], "not_read": ["the GPU"],
                                                         "games": [], "blind": False, "cpu_busy": 1.0, "memory_free": 50.0})
    calls = []
    signs.programs = staticmethod(lambda: calls.append(1) or [])
    assert compute.verdict(flag(tmp_path, on=True, until_epoch=T0 + 60), T0, signs)["verdict"] == "hold"
    assert compute.verdict(flag(tmp_path, on=False), T0, signs)["verdict"] == "free"
    assert calls == []   # must refuse: the machine was not read again within FRESH_S


def cannot(*a):
    raise NotImplementedError


def test_a_system_that_lets_nothing_be_read_is_never_free(tmp_path):
    signs = machine(programs=cannot, screen=cannot, cpu_times=cannot, memory_free=cannot)
    got = compute.verdict({}, T0, signs)
    assert got["verdict"] == "unknown" and compute.EXIT[got["verdict"]] == 2
    assert {"running games", "full-screen programs", "the processor", "memory"} <= set(got["not_read"])
    assert got["could_not_tell"] == []                   # it is not a fault, so the page stays quiet
    # must refuse: the button still holds there
    assert compute.verdict(flag(tmp_path, on=True, until_epoch=T0 + 60), T0, signs)["verdict"] == "hold"


def test_a_system_without_a_full_screen_sign_can_be_free_and_says_what_it_did_not_read():
    got = compute.verdict({}, T0, machine(screen=cannot))
    assert got["verdict"] == "free" and "full-screen programs" in got["not_read"]
    # must refuse: and its other signs still hold
    assert compute.verdict({}, T0, machine(screen=cannot, programs=[GAME]))["verdict"] == "hold"


@pytest.mark.parametrize("path", [
    GAME, r"D:\SteamLibrary\steamapps\common\Foo\foo.exe", "/home/a/.steam/steam/steamapps/common/Bar/bar",
    r"C:\Program Files\Epic Games\Fortnite\f.exe", r"C:\GOG Games\Witcher\w.exe", r"C:\Riot Games\VALORANT\v.exe",
    r"C:\XboxGames\Halo\h.exe"])
def test_every_common_store_is_seen(path):
    assert compute.verdict({}, T0, machine(programs=[path]))["verdict"] == "hold", path


@pytest.mark.parametrize("path", [
    r"C:\Program Files (x86)\Steam\steam.exe", r"C:\Tools\steamapps common\x.exe", r"C:\Games\common\x.exe",
    r"C:\Epic Games Notes\x.exe", r"C:\notes\Epic Games", r"C:\work\MyGOG Games\x.exe"])
def test_a_folder_that_only_looks_like_a_store_is_not_one(path):
    assert compute.verdict({}, T0, machine(programs=[path]))["verdict"] == "free", path


def test_a_person_can_name_their_own_game_folders():
    path = r"D:\Stuff\Games\Blizzard\wow.exe"
    assert compute.verdict({}, T0, machine(programs=[path]))["verdict"] == "free"
    for named in ("Games/Blizzard", r"games\blizzard"):
        assert compute.verdict({"game_folders": [named]}, T0, machine(programs=[path]))["verdict"] == "hold", named
    # must refuse: a setting that is wrong is a sign that could not be read, never free, and never lifts a hold
    for bad in ("Games", 3, [3, None, "", "  "], {"a": 1}, [f"f{i}" for i in range(65)]):
        got = compute.verdict({"game_folders": bad}, T0, machine(programs=[path]))
        assert got["verdict"] == "unknown" and "game_folders" in got["could_not_tell"][0], bad
        assert compute.verdict({"game_folders": bad}, T0, machine(programs=[GAME]))["verdict"] == "hold", bad


def test_the_settings_come_through_a_real_sources_file(tmp_path, monkeypatch):
    path = r"D:\\Stuff\\Games\\Blizzard\\wow.exe"
    sources = tmp_path / "s.json"
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    monkeypatch.setattr(compute.Signs, "programs", staticmethod(lambda: [path]))
    cases = [({"game_folders": ["Games/Blizzard"]}, {"hold"}), ({"game_folders": "Games/Blizzard"}, {"unknown"}), ({}, {"free"})]
    for settings, want in cases:
        sources.write_text(json.dumps(settings), encoding="utf-8")
        got = view.answer("sources", home=tmp_path / "h")["frame"]["compute"]
        assert got["verdict"] in want, settings
    # inbox_app: true itself turns the links on; nothing else does, and a wrong one is said
    for value, on, said in ((True, True, False), (False, False, False), ("true", False, True), (1, False, True)):
        sources.write_text(json.dumps({"inbox_app": value}), encoding="utf-8")
        frame = view.answer("sources", home=tmp_path / "h")["frame"]
        assert frame["inbox_app"] is on, value
        assert any("inbox_app" in str(p.get("text")) for p in frame["problems"]) is said, value


def test_a_store_left_open_is_not_a_game():
    for p in (r"C:\\Program Files\\Epic Games\\Launcher\\Portal\\EpicGamesLauncher.exe", r"C:\\Battle.net\\Battle.net.exe"):
        assert compute.verdict({}, T0, machine(programs=[p]))["verdict"] == "free", p


@pytest.mark.skipif(sys.platform not in ("win32", "linux"), reason="read on Windows and Linux")
def test_the_real_readers_answer_on_this_system():
    programs, times, free = (compute._process_paths, compute._cpu_times, compute._memory_free) if sys.platform == "win32" else (
        compute._linux_programs, compute._linux_cpu_times, compute._linux_memory_free)
    idle, total = times()
    assert programs() and 0 <= idle <= total and total > 0 and 0 < free() <= 100
    if sys.platform == "win32":
        assert 1 <= compute._screen_state() <= 7


def test_the_gpu_is_always_said_to_be_unread():
    assert "the GPU" in compute.verdict({}, T0, machine())["not_read"]


def test_a_single_question_can_be_answered_free_and_uses_nothing_kept():
    signs = machine()
    slept = []
    assert compute.ask({}, signs, sleep=slept.append)["verdict"] == "free" and slept
    # must refuse: a game started after a kept "free" is seen by the next question
    signs.programs = staticmethod(lambda: [GAME])
    assert compute.ask({}, signs, sleep=lambda s: None)["verdict"] == "hold"


def test_it_has_no_call_that_could_write_or_start_anything():
    source = Path(compute.__file__).read_text(encoding="utf-8")
    assert writers(source) == [] and "subprocess" not in source and "os.system" not in source
    # must refuse: the same check finds a planted write
    assert writers(source + "\nPath('x').write_text('on')") == ["write_text"]


def test_the_frame_carries_it_and_nothing_is_written(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text(json.dumps(flag(tmp_path, on=True, until_epoch=T0)), encoding="utf-8")   # long lapsed
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(config))
    before = listing(tmp_path)
    got = view.answer("sources")["frame"]["compute"]
    assert got["verdict"] in ("free", "unknown", "light", "hold") and "the GPU" in got["not_read"]
    assert listing(tmp_path) == before


def test_a_monitor_that_stops_is_unknown_on_the_page_not_free(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(config))

    def stops(*a, **k):
        raise RuntimeError("stopped")
    monkeypatch.setattr(compute, "verdict", stops)
    got = view.answer("sources")["frame"]["compute"]
    assert got["verdict"] == "unknown" and got["could_not_tell"]


def test_a_broken_sources_file_is_never_free_on_the_page(tmp_path, monkeypatch):
    config = tmp_path / "sources.json"
    config.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(config))
    monkeypatch.setattr(compute, "verdict", lambda cfg: {"verdict": "free", "reasons": [], "could_not_tell": [], "not_read": []})
    got = view.answer("sources")["frame"]["compute"]
    assert got["verdict"] == "unknown" and got["could_not_tell"]
    # must refuse: a readable file leaves "free" as it is
    config.write_text("{}", encoding="utf-8")
    assert view.answer("sources")["frame"]["compute"]["verdict"] == "free"


def test_the_command_exits_as_gaming_py_does_and_opens_no_home(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    config = tmp_path / "sources.json"
    config.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(config))
    for answer, code in (("free", 0), ("unknown", 2), ("light", 3), ("hold", 3)):
        monkeypatch.setattr(compute, "ask", lambda cfg, a=answer: {"verdict": a, "reasons": ["why"], "not_read": ["the GPU"]})
        assert cli.main(["--home", str(home), "compute"]) == code, answer
        assert answer in capsys.readouterr().out
    assert not home.exists()   # must refuse: asking makes no home


def test_the_command_says_could_not_tell_over_a_broken_sources_file(tmp_path, monkeypatch, capsys):
    config = tmp_path / "sources.json"
    config.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(config))
    monkeypatch.setattr(compute, "ask", lambda cfg: {"verdict": "free", "reasons": [], "not_read": []})
    assert cli.main(["--home", str(tmp_path / "h"), "compute"]) == 2
    assert "unknown" in capsys.readouterr().out
