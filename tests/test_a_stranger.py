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


def tree(home):
    return {str(f): f.read_bytes() for f in home.rglob("*") if f.is_file()}


def test_what_you_answer_is_the_record_and_what_is_withdrawn_is_not(stranger):
    inbox = Inbox(stranger)
    asked = inbox.ask("Pick a colour", "for the header", question="Which?", options=["red", "blue"], source="Helper")
    gone = inbox.ask("Pick a size", "why", question="Which?", options=["s"], source="Helper")
    open_one = inbox.ask("Pick a font", "why", question="Which?", options=["f"], source="Helper")
    assert view.answer("record", home=stranger)["counts"]["entries"] == 0
    inbox.answer(asked["id"], "2", "the darker one", via="page")
    inbox.close(gone["id"], "not needed")
    before = tree(stranger)
    got = view.answer("record", home=stranger)
    assert tree(stranger) == before   # reading writes nothing
    assert got["off"] is False and got["own"] is True and "record" not in got["frame"]["off"]
    assert [e["id"] for e in got["entries"]] == [f"#{asked['id']}"] and open_one["id"] not in [e["id"] for e in got["entries"]]
    e = got["entries"][0]
    assert e["words"] == "the darker one" and e["reading"] == "You picked: blue" and "2. blue" in e["offer"]
    assert e["to"] == "Helper" and e["added_by"] == "you, on the page" and e["computed_status"] == "answered"
    assert got["threads"][0]["subject"] == "Pick a colour"
    inbox.close(open_one["id"])
    assert view.status_line(stranger) == "nothing waiting · 1 answer kept"


def test_someone_elses_inbox_or_register_is_never_mixed_with_your_own(stranger, tmp_path, monkeypatch):
    inbox = Inbox(stranger)
    asked = inbox.ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    inbox.answer(asked["id"], "1", via="page")
    for setting in ({"inbox": str(tmp_path)}, {"seats": str(tmp_path / "s")}):
        sources = tmp_path / "sources.json"
        sources.write_text(json.dumps(setting), encoding="utf-8")
        monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
        assert view.answer("record", home=stranger)["off"] is True, setting
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(tmp_path / "gone.json"))
    assert view.answer("record", home=stranger)["off"] is True
    assert view.answer("projects", home=stranger)["off"] is True


def test_a_named_project_and_a_seen_agent_show_on_projects_and_the_map(stranger, tmp_path):
    from semantext.agents import Agents, Identity
    empty = view.answer("projects", home=stranger)
    assert empty["off"] is False and empty["own"] is True and empty["projects"] == []
    assert cli.main(["--home", str(stranger), "work", "project", "my-thing"]) == 0
    folder = tmp_path / "repo"
    folder.mkdir()
    Agents(stranger).bind("Helper", folder)
    before = tree(stranger)
    got = view.answer("projects", home=stranger)
    assert tree(stranger) == before
    assert sorted(p["name"] for p in got["projects"]) == ["my-thing", "repo"]
    assert next(p for p in got["projects"] if p["name"] == "repo")["agents"][0]["name"] == "helper"
    assert got["frame"]["problems"] == []
    m = view.answer("map", home=stranger)
    assert m["off"] is False and m["own"] is True and m["root"] and len(m["projects"]) == 2
    assert [a["name"] for a in m["agents"].values()] == ["helper"]
    # the same answer twice names the same things: a link holds
    assert sorted(view.answer("map", home=stranger)["projects"]) == sorted(m["projects"])


def test_a_projects_list_that_cannot_be_read_is_said_and_stops_nothing(stranger):
    (stranger / "work").mkdir(exist_ok=True)
    (stranger / "work" / "projects.json").write_text("not json", encoding="utf-8")
    got = view.answer("projects", home=stranger)
    assert got["off"] is False and any("list of projects" in str(p.get("text")) for p in got["frame"]["problems"])


def test_parking_your_own_request_sets_it_aside_and_brings_it_back(stranger):
    asked = Inbox(stranger).ask("Pick", "why", question="Which?", options=["a", "b"], source="Helper")
    rid = asked["id"]
    server = serve(stranger)
    try:
        # must refuse: not from the page, no number, a truth value for a number, a word for the flag, no such request
        assert call(server, "/api/park", {"id": rid, "parked": True}, origin=False)[0] == 403
        for bad in ({"parked": True}, {"id": True, "parked": True}, {"id": rid, "parked": "no"}, {"id": rid}, {"id": 99, "parked": True}):
            assert call(server, "/api/park", bad)[0] == 400, bad
        assert Inbox(stranger).get(rid)["parked"] is False
        assert call(server, "/api/park", {"id": rid, "parked": True})[0] == 200
        got = json.loads(call(server, "/api/v2/waiting")[1])
        card = got["cards"][0]
        assert got["frame"]["waiting"] == 0 and card["state"] == "parked" and card["parked_at"] and card["choices"] == []
        assert "waiting" not in view.status_line(stranger).replace("nothing waiting", "")
        assert call(server, "/api/park", {"id": rid, "parked": True})[0] == 200      # again: one line, no change
        assert sum('"park"' in x for x in (stranger / "inbox.jsonl").read_text(encoding="utf-8").splitlines()) == 1
        assert call(server, "/api/park", {"id": rid, "parked": False})[0] == 200
        got = json.loads(call(server, "/api/v2/waiting")[1])
        assert got["frame"]["waiting"] == 1 and got["cards"][0]["parked_at"] is None and len(got["cards"][0]["choices"]) == 2
        # an answer still counts while parked, and a closed request cannot be parked
        assert call(server, "/api/park", {"id": rid, "parked": True})[0] == 200
        assert call(server, "/api/answer", {"id": rid, "choice": "1"})[0] == 200
        assert json.loads(call(server, "/api/v2/waiting")[1])["cards"][0]["state"] == "closed"
        assert call(server, "/api/park", {"id": rid, "parked": True})[0] == 400
    finally:
        server.shutdown()
        server.server_close()


def test_parking_is_the_users(stranger):
    asked = Inbox(stranger).ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    from semantext.inbox import Refused
    with pytest.raises(Refused):
        Inbox(stranger).park(asked["id"], True, via="agent")
    # a line edited by hand that is not a yes or no changes nothing
    with (stranger / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "park", "id": asked["id"], "parked": "yes"}) + "\n")
    assert Inbox(stranger).get(asked["id"])["parked"] is False


@pytest.mark.parametrize("setting", ["seats", "inbox", "register", "map"])
def test_any_one_source_named_keeps_your_own_files_out_of_every_page(stranger, tmp_path, monkeypatch, setting):
    inbox = Inbox(stranger)
    asked = inbox.ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    inbox.answer(asked["id"], "1", via="page")
    inbox.ask("Another", "why", question="Which?", options=["a"], source="Helper")
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({setting: str(tmp_path / "named.json")}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    assert view.answer("waiting", home=stranger)["cards"] == [], setting
    machine = view.answer("waiting", home=stranger)                    # apart from the setup's cards, and still counted
    assert [c["title"] for c in machine["machine_inbox"]] == ["Another"] and machine["frame"]["waiting"] == 1
    record = view.answer("record", home=stranger)
    assert not record["own"] and [e for e in record["entries"] if str(e.get("id")).startswith("#")] == []
    assert not view.answer("projects", home=stranger)["own"] and not view.answer("map", home=stranger)["own"]
    # must pass: with no source named, the same home shows them all
    monkeypatch.delenv("SEMANTEXT_SOURCES")
    assert view.answer("waiting", home=stranger)["frame"]["waiting"] == 1 and view.answer("record", home=stranger)["own"]


def test_an_answer_with_no_fields_or_from_nowhere_is_closed_and_says_so(stranger):
    inbox = Inbox(stranger)
    one, two = (inbox.ask(t, "why", question="Which?", options=["a"], source="Helper")["id"] for t in ("One", "Two"))
    with (stranger / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "answer", "id": one}) + "\n")
        f.write(json.dumps({"type": "answer", "id": two, "picked": "a", "via": "agent"}) + "\n")
    got = view.answer("waiting", home=stranger)
    assert got["frame"]["waiting"] == 0 and {c["state"] for c in got["cards"]} == {"closed"}
    assert all("does not say it came from you" in c["closing"]["how"] for c in got["cards"])
    assert {e["added_by"] for e in view.answer("record", home=stranger)["entries"]} == {"the line does not say it came from you"}


def test_a_bad_agents_file_costs_only_the_agents_and_reading_makes_nothing(stranger):
    before = tree(stranger)
    assert view.answer("map", home=stranger)["off"] is False
    assert tree(stranger) == before     # a fresh home: reading makes no file
    from semantext.agents import Agents
    Agents(stranger).sessions_path.write_text(json.dumps({"s": 5}), encoding="utf-8")
    assert cli.main(["--home", str(stranger), "card"]) == 0
    got = view.answer("projects", home=stranger)
    assert got["off"] is False and got["projects"] == []   # that one line costs itself


def test_one_agent_however_its_name_is_written_and_a_name_given_to_a_folder_is_one_project(stranger, tmp_path):
    from semantext.agents import Agents
    from semantext.work.writer import Writer
    folder = tmp_path / "repo"
    folder.mkdir()
    Agents(stranger).bind("helper", folder)
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Helper")
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Other")
    Writer(stranger).add_project("repo")
    m = view.answer("map", home=stranger)
    assert {a["name"]: len(a["waiting"]) for a in m["agents"].values()} == {"Helper": 1, "Other": 1}
    assert [p["name"] for p in m["projects"].values()] == ["repo"] and next(iter(m["projects"].values()))["path"] == str(folder)


def test_a_group_setting_leaves_your_own_projects_and_agents(stranger, tmp_path, monkeypatch):
    Inbox(stranger).ask("Pick", "why", question="Which?", source="Helper")
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({"group": "team"}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    assert [a["name"] for a in view.answer("map", home=stranger)["agents"].values()] == ["Helper"]


@pytest.mark.parametrize("value", [5, ["x"], None, "", "   "])
def test_a_source_named_in_a_shape_that_cannot_be_used_is_still_a_setup(stranger, tmp_path, monkeypatch, value):
    Inbox(stranger).ask("Pick", "why", question="Which?", options=["a"], source="Helper")
    sources = tmp_path / "s.json"
    sources.write_text(json.dumps({"seats": value}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    got = view.answer("waiting", home=stranger)
    assert got["cards"] == [] and any("'seats' should name" in str(x.get("text")) for x in got["frame"]["problems"])
    assert not view.answer("record", home=stranger)["own"] and not view.answer("map", home=stranger)["own"]
    assert view.status_line(stranger) == view.UNAVAILABLE


def test_a_park_line_that_is_not_the_users_hides_nothing(stranger):
    one, two = (Inbox(stranger).ask(t, "why", question="Which?", options=["a"], source="Helper")["id"] for t in ("One", "Two"))
    with (stranger / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "park", "id": one, "parked": True, "via": "agent"}) + "\n")
        f.write(json.dumps({"type": "park", "id": two, "parked": True}) + "\n")
    assert view.answer("waiting", home=stranger)["frame"]["waiting"] == 2


@pytest.mark.parametrize("names", [{"x": 5}, {"x": ["a"]}])
def test_a_label_that_is_not_text_stops_no_page(stranger, names):
    (stranger / "agents.json").write_text(json.dumps({"names": names, "bindings": [], "projects": {}}), encoding="utf-8")
    for route in ROUTES:
        assert view.answer(route, home=stranger) is not None, route
    assert "x" in [a["name"] for a in view.answer("map", home=stranger)["agents"].values()]


def test_one_bad_session_or_binding_costs_itself_and_a_blank_name_is_no_project(stranger, tmp_path):
    from semantext.agents import Agents
    ag = Agents(stranger)
    good = {"agent": "good", "project": "real", "last": "2026-01-01T00:00:00+00:00"}
    ag.sessions_path.write_text(json.dumps({"a": good, "b": "notadict", "c": {"agent": {"x": 1}, "last": 5}}), encoding="utf-8")
    (stranger / "agents.json").write_text(json.dumps({"names": {}, "projects": {}, "bindings": [{"agent": "bad"}, 5]}), encoding="utf-8")
    (stranger / "work").mkdir(exist_ok=True)
    (stranger / "work" / "projects.json").write_text(json.dumps(["", "  ", "kept"]), encoding="utf-8")
    assert "good" in [a["name"] for a in ag.overview()]
    got = view.answer("projects", home=stranger)
    assert sorted(p["name"] for p in got["projects"]) == ["kept", "real"]
    assert not [p for p in got["frame"]["problems"] if "cannot be read" in str(p.get("text"))]
