"""A stranger: Semantext on a machine with nothing of anyone's estate. No sources file, no seats, no inbox, no plug-in.
Standalone first (MINORS.md, 31 October): what is here must keep working for someone who is not its author, and every
page answers without naming what only one person has.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request

import pytest

from semantext import cli
from semantext.inbox import Inbox
from semantext.work.events import WorkRefused
from semantext.sources import view

ROUTES = ["waiting", "projects", "documents", "map", "record", "rules", "sources", "work"]
ONE_PERSONS = ("jak-inbox", "Hermes", "Spartan", "Tribune", "Icarus", "Koinos", "Orithises", "Desktop")


@pytest.fixture
def stranger(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    assert cli.main(["--home", str(home), "init"]) == 0
    return home


def test_the_card_works_from_a_clean_install(stranger, capsys):
    capsys.readouterr()
    assert cli.main(["--home", str(stranger), "card"]) == 0
    assert len(capsys.readouterr().out) > 200


@pytest.mark.parametrize("route", ROUTES)
def test_every_page_answers_and_names_nothing_of_one_persons(stranger, route):
    got = view.answer(route, home=stranger)
    assert got is not None and got["frame"]["inbox_app"] is False
    text = json.dumps(got, default=str)
    assert [w for w in ONE_PERSONS if w in text] == []


def test_their_own_rules_show_with_no_setup_and_a_clean_install_has_no_problem(stranger):
    got = view.answer("rules", home=stranger)
    assert got["counts"]["rules"] > 0 and {e["id"] for e in got["environments"]} == {"base", "default"}
    assert [p for p in got["frame"]["problems"] if p.get("reader") == "rules"] == []


def test_a_new_environment_pins_the_base_it_really_has(stranger):
    assert cli.main(["--home", str(stranger), "env", "new", "Deep", "Work"]) == 0
    got = view.answer("rules", home=stranger)
    assert [p for p in got["frame"]["problems"] if "pins" in str(p.get("text"))] == []
    assert len(got["environments"]) == 3


def test_a_cards_setting_still_wins_and_a_home_with_none_stays_off(tmp_path, monkeypatch):
    theirs = tmp_path / "theirs"
    theirs.mkdir()
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({"cards": str(theirs)}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    assert view.answer("rules", home=tmp_path / "h")["environments"] == []
    # must refuse: a home that has no environments folder is not guessed at
    monkeypatch.delenv("SEMANTEXT_SOURCES")
    got = view.answer("rules", home=tmp_path / "none")
    assert got["environments"] == [] and "rules" in got["frame"]["off"]


def test_the_gaming_switch_needs_no_inbox(stranger, capsys):
    assert view.answer("rules", home=stranger)["frame"]["gaming"]["state"] == "off"
    assert cli.main(["--home", str(stranger), "compute", "hold", "--hours", "2"]) == 0
    got = view.answer("rules", home=stranger)["frame"]
    assert got["gaming"]["state"] == "on" and got["compute"]["verdict"] == "hold"
    assert "the I'm gaming button is on" in got["compute"]["reasons"]
    assert cli.main(["--home", str(stranger), "compute"]) == 3   # jobs asking are told to hold
    assert cli.main(["--home", str(stranger), "compute", "release"]) == 0
    assert view.answer("rules", home=stranger)["frame"]["gaming"]["state"] == "off"


@pytest.mark.parametrize("hours", ["0", "-1", "6.5", "99", "soon", "nan", "inf"])
def test_the_switch_refuses_a_time_it_could_not_keep(stranger, capsys, hours):
    assert cli.main(["--home", str(stranger), "compute", "hold", "--hours", hours]) == 1
    assert view.answer("rules", home=stranger)["frame"]["gaming"]["state"] == "off"


def test_the_switch_never_writes_a_flag_another_program_owns(stranger, tmp_path, monkeypatch, capsys):
    inbox = tmp_path / "their-inbox"
    inbox.mkdir()
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({"inbox": str(inbox)}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    for act in ("hold", "release"):
        assert cli.main(["--home", str(stranger), "compute", act]) == 1
        assert not (inbox / "gaming.json").exists() and not (stranger / "gaming.json").exists()
    assert "their-inbox" in capsys.readouterr().err


def serve(home):
    from semantext.server import make_server
    from semantext.store import Store
    server = make_server(Store.open(home), port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def call(server, path, body=None, origin=True):
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"X-Semantext": "1", "Content-Type": "application/json"}
    if origin:
        headers["Origin"] = f"http://{host}"
    req = urllib.request.Request(f"http://{host}{path}", data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_an_agents_ask_waits_on_both_pages_and_is_answered_on_v2(stranger, monkeypatch):
    asked = Inbox(stranger).ask("Pick a colour", "for the header", question="Which?", options=["red", "blue"], source="Helper")
    server = serve(stranger)
    try:
        assert call(server, "/")[0] == 200 and call(server, "/v2")[0] == 200
        old = json.loads(call(server, "/api/inbox")[1])
        assert [r["id"] for r in old["open"]] == [asked["id"]]
        got = json.loads(call(server, "/api/v2/waiting")[1])
        assert got["off"] is False and got["frame"]["waiting"] == 1
        card = got["cards"][0]
        assert card["id"] == f"#{asked['id']}" and card["seat"] == "Helper" and card["state"] == "waiting"
        assert [c["label"] for c in card["choices"]] == ["red", "blue"]
        # must refuse: a post that is not from the page answers nothing, and an option that does not exist neither
        assert call(server, "/api/answer", {"id": card["number"], "choice": "2"}, origin=False)[0] == 403
        assert call(server, "/api/answer", {"id": card["number"], "choice": "9"})[0] == 400
        assert Inbox(stranger).get(asked["id"])["status"] == "open"
        assert call(server, "/api/answer", {"id": card["number"], "choice": "2"})[0] == 200
        got = json.loads(call(server, "/api/v2/waiting")[1])
        assert got["frame"]["waiting"] == 0 and got["cards"][0]["closing"]["how"] == "You answered: blue" and got["cards"][0]["choices"] == []
        # must refuse: a second answer does not change the first
        assert call(server, "/api/answer", {"id": card["number"], "choice": "1"})[0] == 400
        assert Inbox(stranger).get(asked["id"])["answer"]["picked"] == "blue"
    finally:
        server.shutdown()
        server.server_close()


def test_one_bad_line_costs_that_request_and_never_the_others(stranger):
    good = Inbox(stranger).ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    with (stranger / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "request", "id": 99, "at": 5, "kind": "decision", "options": 5, "from": {"a": 1}, "title": []}) + "\n")
    got = view.answer("waiting", home=stranger)
    assert got["off"] is False and f"#{good['id']}" in [c["id"] for c in got["cards"]]


def test_a_claimed_name_is_shown_as_claimed(stranger):
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Anthropic Support", how="claimed")
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Helper", how="bound")
    seats = [c["seat"] for c in view.answer("waiting", home=stranger)["cards"]]
    assert sorted(seats) == ["Anthropic Support (claimed)", "Helper"]


def test_an_escape_code_never_reaches_the_status_line(stranger):
    Inbox(stranger).ask("Pick\x1b[2J\x1b]0;pwned\x07", "why", question="Which?", source="Helper\x1b[31m")
    line = view.status_line(stranger)
    assert "1 waiting" in line and "\x1b" not in line and "\x07" not in line


def test_a_group_setting_does_not_hide_your_own_inbox(stranger, tmp_path, monkeypatch):
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Helper")
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({"group": "team"}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    assert "1 waiting" in view.status_line(stranger)
    assert view.answer("waiting", home=stranger)["frame"]["waiting"] == 1


def test_a_truth_value_is_not_a_request_number(stranger):
    asked = Inbox(stranger).ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    assert asked["id"] == 1
    server = serve(stranger)
    try:
        assert call(server, "/api/answer", {"id": True, "choice": "1"})[0] == 400
        assert Inbox(stranger).get(1)["status"] == "open"
    finally:
        server.shutdown()
        server.server_close()


def test_a_mistyped_home_is_not_made_and_a_hold_too_short_to_keep_is_refused(tmp_path, stranger):
    missing = tmp_path / "typo" / "home"
    assert cli.main(["--home", str(missing), "compute", "hold"]) == 1 and not missing.exists()
    assert cli.main(["--home", str(missing), "compute", "release"]) == 1 and not missing.exists()
    for hours in ("1e-9", "0.0001"):
        assert cli.main(["--home", str(stranger), "compute", "hold", "--hours", hours]) == 1, hours


def test_a_sources_file_named_and_missing_is_a_broken_setup_not_no_setup(stranger, tmp_path, monkeypatch):
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Helper")
    assert view.answer("waiting", home=stranger)["frame"]["waiting"] == 1
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(tmp_path / "gone.json"))
    assert view.answer("waiting", home=stranger)["off"] is True and view.status_line(stranger) == view.UNAVAILABLE


def test_a_stranger_names_a_project_and_files_work_and_the_page_shows_it(stranger, capsys):
    new = ["--home", str(stranger), "work", "new", "--project", "my-thing", "--title", "A first task"]
    assert cli.main(new) == 1                                  # must refuse: a project nobody named
    assert "semantext work project my-thing" in capsys.readouterr().err
    assert cli.main(["--home", str(stranger), "work", "project", "My Thing"]) == 0
    assert cli.main(new) == 0
    got = view.answer("work", home=stranger)
    assert [i["title"] for i in got["items"]] == ["A first task"]
    assert cli.main(["--home", str(stranger), "work", "project", "my-thing"]) == 0   # again: once in the list
    assert json.loads((stranger / "work" / "projects.json").read_text(encoding="utf-8")) == ["my-thing"]


def test_adding_a_project_is_the_persons_and_never_replaces_a_list_it_cannot_read(stranger, monkeypatch):
    listing = stranger / "work" / "projects.json"
    listing.parent.mkdir(exist_ok=True)
    listing.write_text("not json", encoding="utf-8")
    assert cli.main(["--home", str(stranger), "work", "project", "x"]) == 1
    assert listing.read_text(encoding="utf-8") == "not json"
    assert cli.main(["--home", str(stranger), "work", "project", "!!!"]) == 1
    import semantext.cli as main_cli
    monkeypatch.setattr(main_cli, "human_terminal", lambda: "this is an agent's shell")
    listing.write_text("[]", encoding="utf-8")
    assert cli.main(["--home", str(stranger), "work", "project", "x"]) == 1
    assert listing.read_text(encoding="utf-8") == "[]"


@pytest.mark.parametrize("bad", [
    '{"type":"request","id":' + "9" * 5000 + ',"at":"x"}',
    '{"type":"request","id":7,"at":' + "9" * 5000 + '}',
    '{"type":"request","id":7,"at":NaN,"title":NaN,"why":NaN,"question":Infinity,"kind":"decision","options":[]}',
    '{"type":"request","id":7,"kind":"command","command":NaN,"does":NaN,"undo":NaN,"cwd":NaN,"at":"x","title":"t","why":"w"}',
    '{"type":"request","id":true,"at":"x","title":"t","why":"w","kind":"decision"}',
    '{"type":"request","id":7,"at":"x","title":"t","why":"w","kind":"decision","options":[NaN,1],"recommend":NaN}',
])
def test_no_bad_line_stops_the_page_the_status_line_or_the_card(stranger, bad, capsys):
    good = Inbox(stranger).ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    with (stranger / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(bad + "\n")
    server = serve(stranger)
    try:
        status, body = call(server, "/api/v2/waiting")
        assert status == 200 and f"#{good['id']}".encode() in body
        assert b"NaN" not in body and b"#True" not in body
    finally:
        server.shutdown()
        server.server_close()
    assert "waiting" in view.status_line(stranger)
    capsys.readouterr()
    assert cli.main(["--home", str(stranger), "card"]) == 0


def test_a_missing_sources_file_is_said_and_is_never_free(stranger, tmp_path, monkeypatch):
    from semantext.sources import compute
    def signs():
        return type("M", (), {"programs": staticmethod(lambda: []), "screen": staticmethod(lambda: 5),
                              "cpu_times": staticmethod(lambda: (1, 2)), "memory_free": staticmethod(lambda: 50.0), "clock": staticmethod(lambda: 0.0)})
    assert compute.verdict({"_sources_missing": True}, signs=signs())["verdict"] == "unknown"
    for named in (tmp_path / "gone.json", tmp_path):   # missing, and a folder
        monkeypatch.setenv("SEMANTEXT_SOURCES", str(named))
        frame = view.answer("waiting", home=stranger)["frame"]
        assert any("is not there" in str(p.get("text")) for p in frame["problems"]), named


def test_a_junction_is_never_written_through_and_many_adds_lose_nothing(stranger, tmp_path):
    from semantext.work.writer import Writer
    names = [f"p{i}" for i in range(20)]
    threads = [threading.Thread(target=Writer(stranger).add_project, args=(n,)) for n in names]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(json.loads((stranger / "work" / "projects.json").read_text(encoding="utf-8"))) == sorted(names)
    with pytest.raises(WorkRefused):
        Writer(stranger).add_project(["a list"])
    # must refuse: a store folder that leads elsewhere is never written through
    home, outside = tmp_path / "other-home", tmp_path / "elsewhere"
    home.mkdir()
    outside.mkdir()
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(home / "work"), str(outside)], check=True, capture_output=True)
    else:
        (home / "work").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkRefused):
        Writer(home).add_project("x")
    assert list(outside.iterdir()) == []


def test_a_launcher_is_judged_in_its_own_stores_folder_only():
    from semantext.sources import compute
    for p in (r"C:\\Program Files\\Epic Games\\Launcher\\EpicGamesLauncher.exe", r"C:\\Battle.net\\Agent\\Agent.exe"):
        assert not compute.is_game_path(p), p
    # must refuse: a real game with a launcher's name is still a game
    for p in (r"D:\\steamapps\\common\\Agent\\Agent.exe", r"D:\\steamapps\\common\\X\\battle.net.exe", r"C:\\Epic Games\\Fortnite\\f.exe"):
        assert compute.is_game_path(p), p


def test_a_clean_install_reports_no_problem_on_any_page(stranger):
    for route in ROUTES:
        assert view.answer(route, home=stranger)["frame"]["problems"] == [], route
    # must refuse: a seats file that is named and broken is still said
    broken = stranger / "s.json"
    broken.write_text(json.dumps({"seats": str(stranger / "gone.json")}), encoding="utf-8")
    import os
    os.environ["SEMANTEXT_SOURCES"] = str(broken)
    try:
        assert view.answer("work", home=stranger)["frame"]["problems"]
    finally:
        del os.environ["SEMANTEXT_SOURCES"]


def test_a_half_setup_is_still_said_and_not_read_from_the_home(stranger, tmp_path, monkeypatch):
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Helper")
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({"seats": str(tmp_path / "seats.json")}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    got = view.answer("waiting", home=stranger)
    assert got["off"] is True and got["missing"] == ["inbox"] and got["cards"] == []


def test_the_compute_command_answers_from_a_clean_install(stranger, capsys):
    capsys.readouterr()
    assert cli.main(["--home", str(stranger), "compute"]) == 2   # the tests' system lets nothing be read
    assert "the GPU" in capsys.readouterr().out
