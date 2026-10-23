"""Places: the agents, the projects they work in, the map's levels and file, the documents, and which project a card
belongs to. Each check has an arm that must pass and an arm that must refuse: a planted defect the reader has to report,
or a wrong value the comparison has to catch. Every fixture is made here, in a temporary folder."""
import copy
import json
import ntpath
import os
import posixpath
import random
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from semantext.sources import places

T = 1_700_000_000   # a fixed time, so a file's date is the same on every machine

MAP = {
    "measured": "2026-01-02",
    "sectors": [{"sector": "Alpha", "title": "The first sector", "items": []},
                {"sector": "Beta", "title": "The second sector", "items": []}],
    "repos": [{}, {}],
    "contradictions": ["a", "b", "c"],
    "overlay": {"places": [{"sector": "Alpha", "shape": "circle"}, {"sector": "Alpha", "shape": "not-a-place"},
                            {"sector": "Beta", "shape": "not-a-place"}, {"sector": "Gamma"}],
                "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}, {"from": "c", "to": "a"}]},
}


def write(path: Path, text="", when: int | None = None) -> Path:
    """A file, written as bytes so a line ending is exactly what the test says; dated `when` if given."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    if when is not None:
        os.utime(path, (when, when))
    return path


def stamp(secs: int) -> str:
    return datetime.fromtimestamp(secs, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def by(items: list, name: str) -> dict:
    return next(x for x in items if x["name"] == name)


def kinds(loaded: dict) -> list[str]:
    return [p["kind"] for p in loaded["problems"]]


def seats_data(desk: Path) -> dict:
    return {
        "_about": "a note the reader leaves alone",
        "base": str(desk),
        "seats": {
            "Ada": {"names": ["Ada", "Adah"], "groups": ["Crew", "Crew-old"],
                    "emails": ["ada@example.test", "adah@example.test"], "home": "ada",
                    "sigils": {"wire": ["A"], "board": ["A", "AD"]}},
            "Bram": {"names": ["Bram"], "groups": ["Crew"], "emails": ["bram@example.test"], "home": "bram",
                     "sigils": {"wire": ["B"]}},
            "Cleo": {"names": ["Cleo"], "groups": ["Guests"], "emails": ["cleo@example.test"], "home": "guests/cleo",
                     "sigils": {}},
        },
        "roots": [{"name": "main", "path": "shared/main", "kind": "repo"},
                  {"name": "tools", "path": "shared/tools", "kind": "repo"},
                  {"name": "notes", "path": "notes", "kind": "folder"},
                  {"name": "home", "path": "{home}", "kind": "repo"}],
    }


@pytest.fixture
def world(tmp_path):
    """Three agents with homes, two shared projects, a seats file and a map file. Bram's home has no .identity."""
    desk = tmp_path / "desk"
    write(desk / "ada" / ".identity", "Ada <ada@example.test>\n")
    write(desk / "guests" / "cleo" / ".identity", "Cleo <cleo@example.test>\n")
    (desk / "bram").mkdir(parents=True)
    write(desk / "shared" / "main" / ".identity",
          "# who works here\nAda <ada@example.test>\n\nBram <BRAM@Example.test>   # by hand\n"
          "Zed <zed@example.test>\n")
    write(desk / "shared" / "tools" / ".identity", "Cleo <cleo@example.test>\n")
    (desk / "notes").mkdir()
    data = seats_data(desk)
    seats = write(tmp_path / "seats.json", json.dumps(data))
    mapfile = write(tmp_path / "map.json", json.dumps(MAP))
    cfg = {"name": "Everything", "seats": str(seats), "map": str(mapfile)}
    return SimpleNamespace(desk=desk, seats=seats, map=mapfile, cfg=cfg, data=copy.deepcopy(data))


def resave(world, data: dict) -> None:
    write(world.seats, json.dumps(data))


def make_dir_link(target: Path, link: Path) -> bool:
    """A link to a folder: a junction on Windows (it needs no privilege), a symlink elsewhere. False if this machine
    cannot make one."""
    try:
        if sys.platform == "win32":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, ImportError, AttributeError):
        return False


# ---------------------------------------------------------------- off, and files that cannot be read
def test_a_missing_key_turns_its_part_off():
    nothing = places.load({})
    assert nothing["off"] is True and nothing["missing"] == ["seats", "map"]
    assert nothing["agents"] == [] and nothing["projects"] == [] and nothing["documents"] == []
    assert nothing["map"] == {"off": True} and nothing["levels"] is None and nothing["problems"] == []
    assert places.load({"name": "Mine"})["name"] == "Mine"          # the word is kept even with nothing to show


def test_one_key_alone_turns_only_the_other_part_off(world):
    seats_only = places.load({"seats": world.cfg["seats"]})
    assert seats_only["off"] is False and seats_only["missing"] == ["map"] and seats_only["map"] == {"off": True}
    assert len(seats_only["agents"]) == 3
    assert seats_only["levels"]["name"] is None and seats_only["levels"]["measured"] is None
    map_only = places.load({"name": "Everything", "map": world.cfg["map"]})
    assert map_only["off"] is False and map_only["missing"] == ["seats"] and map_only["agents"] == []
    both = places.load({"seats": world.cfg["seats"], "map": world.cfg["map"]})
    assert both["off"] is False and both["missing"] == []                         # control: nothing is missing
    assert map_only["map"]["places"] == 4 and map_only["levels"]["measured"] == "2026-01-02"
    assert map_only["levels"]["children"] == []


def test_a_file_that_cannot_be_read_is_a_problem_never_a_failure(tmp_path):
    loaded = places.load({"seats": str(tmp_path / "nope.json"), "map": str(tmp_path / "also-nope.json")})
    assert loaded["off"] is False and kinds(loaded) == ["unreadable", "unreadable"]
    assert loaded["agents"] == [] and loaded["map"]["places"] is None
    json.dumps(loaded)


def test_a_config_path_no_file_can_have_is_a_problem_never_a_failure():
    loaded = places.load({"seats": "bad\x00name.json", "map": "also\x00bad.json"})
    assert kinds(loaded) == ["unreadable", "unreadable"] and loaded["agents"] == [] and loaded["map"]["places"] is None
    json.dumps(loaded)


def test_a_leading_tilde_is_the_users_home_and_one_that_cannot_be_expanded_is_a_problem(world, monkeypatch):
    monkeypatch.setenv("HOME", str(world.seats.parent))
    monkeypatch.setenv("USERPROFILE", str(world.seats.parent))
    assert len(places.load({"seats": "~/seats.json"})["agents"]) == 3                        # control: it is expanded

    def cannot(self):
        raise RuntimeError("Could not determine home directory.")
    monkeypatch.setattr(Path, "expanduser", cannot)
    loaded = places.load({"seats": "~ghost/seats.json", "map": "~ghost/map.json"})
    assert kinds(loaded) == ["unreadable", "unreadable"] and loaded["agents"] == []


@pytest.mark.parametrize("text, kind", [
    (b"{not json", "not-json"),
    (b"\xff\xfe\x00", "encoding"),
    (b"[1, 2]", "shape"),
    (b'{"seats": ["Ada"]}', "shape"),
])
def test_a_seats_file_of_the_wrong_shape_is_reported(tmp_path, text, kind):
    f = write(tmp_path / "seats.json", text)
    loaded = places.load({"seats": str(f)})
    assert kind in kinds(loaded) and loaded["agents"] == []
    json.dumps(loaded)


def test_a_file_over_its_limit_is_not_read_and_says_so(world, monkeypatch):
    monkeypatch.setattr(places, "MAX_SEATS", 20)
    loaded = places.load(world.cfg)
    assert loaded["agents"] == [] and "too-big" in kinds(loaded) and loaded["map"]["places"] == 4
    monkeypatch.undo()
    monkeypatch.setattr(places, "MAX_MAP", 20)
    loaded = places.load(world.cfg)
    assert loaded["map"]["places"] is None and "too-big" in kinds(loaded) and len(loaded["agents"]) == 3


def test_a_seats_file_with_a_byte_order_mark_reads(world):
    write(world.seats, b"\xef\xbb\xbf" + json.dumps(world.data).encode("utf-8"))
    assert [a["name"] for a in places.load(world.cfg)["agents"]] == ["Ada", "Bram", "Cleo"]


# ---------------------------------------------------------------- settings that are not text
@pytest.mark.parametrize("settings, key", [
    ({"seats": 5}, "seats"), ({"seats": True}, "seats"), ({"seats": {"a": 1}}, "seats"), ({"map": ["x"]}, "map"),
    ({"map": 1.5}, "map"), ({"name": {"a": 1}}, "name"), ({"name": 7}, "name"), ({"group": 7}, "group"),
    ({"group": ["Crew"]}, "group"),
])
def test_a_setting_that_is_not_text_is_a_problem_never_a_failure(settings, key):
    loaded = places.load(settings)                                  # a direct caller: load_config would have dropped it
    shape = [p for p in loaded["problems"] if p["kind"] == "shape"]
    assert len(shape) == 1 and f"'{key}'" in shape[0]["text"]
    json.dumps(loaded)


@pytest.mark.parametrize("settings", [[1, 2], "text", 7, ("seats",)])
def test_settings_that_are_not_a_record_are_a_problem_never_a_failure(settings):
    loaded = places.load(settings)
    assert loaded["off"] is True and [p["kind"] for p in loaded["problems"]] == ["shape"]
    json.dumps(loaded)


def test_a_setting_that_is_not_text_leaves_the_rest_to_be_read(world):
    named = places.load({**world.cfg, "name": {"a": 1}})
    assert named["name"] is None and named["levels"]["name"] is None and len(named["agents"]) == 3
    assert "shape" in kinds(named) and named["map"]["places"] == 4
    grouped = places.load({**world.cfg, "group": 7})                  # no group is no filter: every seat is read
    assert [a["name"] for a in grouped["agents"]] == ["Ada", "Bram", "Cleo"] and "shape" in kinds(grouped)
    seats_gone = places.load({**world.cfg, "seats": 5})               # that part is off, the other still reads
    assert seats_gone["missing"] == ["seats"] and seats_gone["agents"] == [] and seats_gone["map"]["places"] == 4
    assert kinds(places.load(world.cfg)) == ["absent"]            # control: settings that are text raise only that


# ---------------------------------------------------------------- the group
def test_only_the_seats_in_the_group_are_read(world):
    write(world.desk / "guests" / "cleo" / "cv" / "plan" / "MASTER.md", "# Cleo plan\n", T)
    write(world.desk / "bram" / "cv" / "plan" / "MASTER.md", "# Bram plan\n", T)
    everyone = places.load(world.cfg)
    assert [a["name"] for a in everyone["agents"]] == ["Ada", "Bram", "Cleo"]                   # control: no group, all
    assert {d["agent"] for d in everyone["documents"]} == {"Bram", "Cleo"}
    loaded = places.load({**world.cfg, "group": "Crew"})
    assert [a["name"] for a in loaded["agents"]] == ["Ada", "Bram"]                             # Cleo is a Guest
    assert [p["name"] for p in loaded["projects"]] == ["main", "tools", "Ada home", "Bram home"]  # no home for Cleo
    assert [d["agent"] for d in loaded["documents"]] == ["Bram"]
    assert [g["name"] for g in loaded["levels"]["children"]] == ["Crew"]
    assert [m["name"] for m in by(loaded["projects"], "main")["members"]] == ["Ada", "Bram"]
    tools = by(loaded["projects"], "tools")           # Cleo is listed there, but Cleo is no agent of this group
    assert tools["members"] == [] and tools["others"] == [{"name": "Cleo", "email": "cleo@example.test"}]
    assert loaded["group"] == "Crew" and everyone["group"] is None                              # the page can say which
    json.dumps(loaded)


def test_a_seat_is_in_a_group_only_when_its_list_holds_the_word_exactly(world):
    data = world.data
    data["seats"]["Dov"] = {"names": ["Dov"], "groups": "Crew", "emails": [], "home": "dov"}       # not a list
    data["seats"]["Eve"] = {"names": ["Eve"], "groups": ["crew", "Crew ", 7, None], "emails": [], "home": "eve"}
    data["seats"]["Fay"] = {"names": ["Fay"], "groups": [7, "Crew"], "emails": [], "home": "fay"}   # any position
    resave(world, data)
    assert [a["name"] for a in places.load({**world.cfg, "group": "Crew"})["agents"]] == ["Ada", "Bram", "Fay"]
    assert "Dov" in [a["name"] for a in places.load(world.cfg)["agents"]]       # control: no group reads every seat


def test_a_group_no_seat_is_in_is_said_and_reads_no_agent(world):
    loaded = places.load({**world.cfg, "group": "Nobody"})
    assert loaded["agents"] == [] and loaded["documents"] == [] and "empty-group" in kinds(loaded)
    assert [p["name"] for p in loaded["projects"]] == ["main", "tools"] and loaded["levels"]["children"] == []
    assert "empty-group" not in kinds(places.load({**world.cfg, "group": "Crew"}))


def test_a_seat_outside_the_group_is_not_examined_but_one_that_is_no_record_is_still_said(world):
    data = world.data
    data["seats"]["Cleo"].pop("home")                      # a defect in a seat the group leaves out: not this page's
    data["seats"]["Dov"] = "not a record"                  # not a record: its group cannot be told, so it is said
    resave(world, data)
    assert "no-home" in kinds(places.load(world.cfg))      # control: with no group it is a defect to report
    grouped = places.load({**world.cfg, "group": "Crew"})
    assert "no-home" not in kinds(grouped) and kinds(grouped).count("shape") == 1


# ---------------------------------------------------------------- agents
def test_an_agent_is_one_per_seat_with_names_groups_emails_home_and_sigils(world):
    loaded = places.load(world.cfg)
    assert [a["name"] for a in loaded["agents"]] == ["Ada", "Bram", "Cleo"]
    ada, bram = loaded["agents"][0], loaded["agents"][1]
    assert ada["other_names"] == ["Adah"] and ada["groups"] == ["Crew", "Crew-old"]
    assert ada["emails"] == ["ada@example.test", "adah@example.test"]
    assert ada["home"] == str(world.desk / "ada")                      # in full, under the base
    assert ada["sigils"] == {"wire": ["A"], "board": ["A", "AD"]}
    assert bram["other_names"] == [] and re.fullmatch(r"[0-9a-f]{10}", ada["id"])
    assert loaded["base"] == str(world.desk) and loaded["name"] == "Everything"


def test_a_seat_with_a_defect_is_reported_and_the_rest_still_read(world):
    data = world.data
    data["seats"]["Bram"].pop("home")                       # no home
    data["seats"]["Cleo"]["names"] = 7                      # names that are not a list
    data["seats"]["Ada"]["sigils"] = ["A"]                  # sigils that are not a record
    data["seats"]["Dov"] = "not a record"
    data["seats"]["Eve"] = {"names": ["Eve"], "groups": ["Crew"], "emails": [], "home": "../outside"}
    resave(world, data)
    loaded = places.load(world.cfg)
    assert {"no-home", "shape", "bad-path"} <= set(kinds(loaded))
    assert [a["name"] for a in loaded["agents"]] == ["Ada", "Bram", "Cleo", "Eve"]     # Dov is not a seat
    assert by(loaded["agents"], "Bram")["home"] is None and by(loaded["agents"], "Eve")["home"] is None
    assert by(loaded["agents"], "Ada")["sigils"] == {} and by(loaded["agents"], "Cleo")["other_names"] == []
    assert by(loaded["agents"], "Ada")["home"] == str(world.desk / "ada")               # untouched


@pytest.mark.parametrize("text, unfit", [
    ("an ok name/with\\both slashes", False), ("caf\xe9", False), ("a\x00b", True), ("a\x1fb", True), ("a\x7fb", True),
    ("a" + chr(0xD800) + "b", True),                                          # a lone surrogate, which no file can have
])
def test_a_path_holding_a_control_character_or_a_lone_surrogate_is_unfit(text, unfit):
    assert places._unfit(text) is unfit


def test_a_path_no_folder_can_have_is_refused_not_followed(world):
    data = world.data
    data["seats"]["Bram"]["home"] = "bram\x00x"                 # a NUL cannot be in a name
    data["seats"]["Cleo"]["home"] = "guests/cl\x07eo"           # nor is a control character one to trust
    resave(world, data)
    loaded = places.load(world.cfg)
    assert kinds(loaded).count("bad-path") == 2
    assert by(loaded["agents"], "Bram")["home"] is None and by(loaded["agents"], "Cleo")["home"] is None
    assert by(loaded["agents"], "Ada")["home"] == str(world.desk / "ada")                  # the others are untouched
    assert [p["name"] for p in loaded["projects"]] == ["main", "tools", "Ada home"]
    json.dumps(loaded)


@pytest.mark.parametrize("base", ["relative/folder", 5, "  ", "bad\x00base"])
def test_a_base_that_is_not_a_full_folder_path_is_reported(world, base):
    data = world.data
    data["base"] = base
    resave(world, data)
    loaded = places.load(world.cfg)
    assert "shape" in kinds(loaded) and loaded["base"] is None
    assert all(a["home"] is None for a in loaded["agents"])
    assert kinds(loaded).count("bad-path") == 5 and loaded["projects"] == []             # 3 homes and 2 roots


def test_two_seats_that_differ_only_in_spaces_are_one_agent_and_said(world):
    data = world.data
    data["seats"]["Ada "] = {"names": ["Imposter"], "groups": ["Crew"], "emails": [], "home": "ada"}
    resave(world, data)
    loaded = places.load(world.cfg)
    assert [a["name"] for a in loaded["agents"]] == ["Ada", "Bram", "Cleo"]
    assert by(loaded["agents"], "Ada")["other_names"] == ["Adah"]                          # the first listing stands
    assert "duplicate-seat" in kinds(loaded) and len(all_ids(loaded)) == len(set(all_ids(loaded)))


def test_an_email_two_agents_share_is_reported_and_names_both(world):
    data = world.data
    data["seats"]["Bram"]["emails"].append("ADA@example.test")
    resave(world, data)
    loaded = places.load(world.cfg)
    problem = next(p for p in loaded["problems"] if p["kind"] == "shared-email")
    assert "Ada" in problem["text"] and "Bram" in problem["text"]
    assert {m["name"] for m in by(loaded["projects"], "main")["members"]} == {"Ada", "Bram"}


# ---------------------------------------------------------------- projects and their members
def test_a_project_is_one_per_repo_root_and_a_home_root_gives_one_per_agent(world):
    loaded = places.load(world.cfg)
    assert [p["name"] for p in loaded["projects"]] == ["main", "tools", "Ada home", "Bram home", "Cleo home"]
    assert {p["kind"] for p in loaded["projects"]} == {"repo"}           # the "notes" root is a folder, no project
    main = by(loaded["projects"], "main")
    assert main["path"] == str(world.desk / "shared" / "main") and main["exists"] is True and main["root"] == "main"
    assert by(loaded["projects"], "Cleo home")["path"] == str(world.desk / "guests" / "cleo")
    assert by(loaded["projects"], "Ada home")["root"] == "home"


def test_who_works_in_a_project_comes_from_its_identity_file_or_its_home_and_says_which(world):
    loaded = places.load(world.cfg)
    main = by(loaded["projects"], "main")
    assert [(m["name"], m["basis"], m["emails"]) for m in main["members"]] == [
        ("Ada", ["identity"], ["ada@example.test"]), ("Bram", ["identity"], ["BRAM@Example.test"])]   # ignoring case
    assert main["others"] == [{"name": "Zed", "email": "zed@example.test"}] and main["home_of"] == []
    assert [(m["name"], m["basis"]) for m in by(loaded["projects"], "Ada home")["members"]] == [
        ("Ada", ["home", "identity"])]
    bram = by(loaded["projects"], "Bram home")                  # no .identity there: the home agent alone
    assert [(m["name"], m["basis"], m["emails"]) for m in bram["members"]] == [("Bram", ["home"], [])]
    assert bram["home_of"] == ["Bram"]
    assert [m["name"] for m in by(loaded["projects"], "tools")["members"]] == ["Cleo"]
    assert main["identity"]["state"] == "read" and main["identity"]["entries"] == 3


def test_an_agent_is_listed_by_any_one_of_its_emails(world):
    write(world.desk / "shared" / "tools" / ".identity", "Someone <adah@example.test>\nCleo <cleo@example.test>\n")
    tools = by(places.load(world.cfg)["projects"], "tools")
    assert [(m["name"], m["emails"]) for m in tools["members"]] == [("Ada", ["adah@example.test"]),
                                                                    ("Cleo", ["cleo@example.test"])]


def test_a_line_planted_in_an_identity_file_changes_the_members(world):
    before = places.load(world.cfg)
    with open(world.desk / "shared" / "main" / ".identity", "a", encoding="utf-8") as f:
        f.write("Cleo <cleo@example.test>\n")
    after = places.load(world.cfg)
    assert by(before["projects"], "main")["members"] != by(after["projects"], "main")["members"]
    assert [m["name"] for m in by(before["projects"], "main")["members"]] == ["Ada", "Bram"]
    assert [m["name"] for m in by(after["projects"], "main")["members"]] == ["Ada", "Bram", "Cleo"]
    assert by(before["projects"], "tools") == by(after["projects"], "tools")       # nothing else moved


def test_identity_lines_that_cannot_be_used_are_reported_with_their_line(world):
    write(world.desk / "shared" / "main" / ".identity",
          "\ufeffAda <ada@example.test>\r\nnot an identity\r\n\r\n# fine\r\nBram <bram@example.test> and words\r\n"
          "bram@example.test\r\n")
    loaded = places.load(world.cfg)
    bad = [p for p in loaded["problems"] if p["kind"] == "bad-line"]
    assert [p["line"] for p in bad] == [2, 5, 6]                   # the blank and comment lines are counted
    assert all(p["source"].endswith(".identity") for p in bad)
    assert [m["name"] for m in by(loaded["projects"], "main")["members"]] == ["Ada"]


def test_a_line_longer_than_the_limit_is_reported_not_parsed(world):
    write(world.desk / "shared" / "main" / ".identity",
          "Ada <ada@example.test>\n" + "Bram <" + "b" * 70_000 + "@example.test>\n")
    loaded = places.load(world.cfg)
    assert [(p["kind"], p["line"]) for p in loaded["problems"] if p["kind"] == "bad-line"] == [("bad-line", 2)]
    assert [m["name"] for m in by(loaded["projects"], "main")["members"]] == ["Ada"]


@pytest.mark.parametrize("ending", ["\n", "\r\n", "\r", "\x85", " ", "\x0b", "\x0c", "\x1c"])
def test_an_identity_line_ends_wherever_a_text_line_ends(world, ending):
    """Other tools read this file with splitlines(); a file saved with lone carriage returns (an old editor, a tool) is
    the same list. Read as one line, it listed no one and said its one 'line' was not an identity."""
    body = ending.join(["Ada <ada@example.test>", "# a comment", "Bram <bram@example.test>",
                        "Cleo <cleo@example.test>"])
    write(world.desk / "shared" / "main" / ".identity", body + ending)
    loaded = places.load(world.cfg)
    main = by(loaded["projects"], "main")
    assert [m["name"] for m in main["members"]] == ["Ada", "Bram", "Cleo"] and main["identity"]["entries"] == 3
    assert "bad-line" not in kinds(loaded)


def test_the_lines_of_an_identity_file_are_counted_whatever_their_endings(world):
    write(world.desk / "shared" / "main" / ".identity",
          "Ada <ada@example.test>\rnot an identity\r\n\n# c\x85bad again\n")
    bad = [p for p in places.load(world.cfg)["problems"] if p["kind"] == "bad-line"]
    assert [(p["line"], p["text"]) for p in bad] == [(2, 'is not "Name <email>": not an identity'),
                                                     (5, 'is not "Name <email>": bad again')]


def test_an_identity_line_that_is_not_utf8_is_used_and_said(world):
    tools = world.desk / "shared" / "tools" / ".identity"
    write(tools, "Jos\xe9 <cleo@example.test>\nAda <ada@example.test>\n")                # a name with an accent: fine
    loaded = places.load(world.cfg)
    assert "encoding" not in kinds(loaded)
    assert [m["name"] for m in by(loaded["projects"], "tools")["members"]] == ["Ada", "Cleo"]
    write(tools, b"Jos\xe9 <cleo@example.test>\nAda <ada@example.test>\n")                   # the same bytes in Latin-1
    loaded = places.load(world.cfg)
    assert [(p["kind"], p["line"]) for p in loaded["problems"] if p["kind"] == "encoding"] == [("encoding", 1)]
    assert [m["name"] for m in by(loaded["projects"], "tools")["members"]] == ["Ada", "Cleo"]   # the email is plain


def test_a_missing_identity_file_is_reported_not_skipped(world):
    loaded = places.load(world.cfg)
    bram = by(loaded["projects"], "Bram home")
    assert bram["identity"]["state"] == "absent"
    absent = [p for p in loaded["problems"] if p["kind"] == "absent"]
    assert [p["source"] for p in absent] == [bram["identity"]["path"]]       # and only where it is missing


def test_an_identity_file_that_cannot_be_used_is_reported(world, monkeypatch):
    data = world.data
    data["roots"] += [{"name": "odd", "path": "shared/odd", "kind": "repo"}]
    resave(world, data)
    (world.desk / "shared" / "odd" / ".identity").mkdir(parents=True)             # a folder where the file should be
    loaded = places.load(world.cfg)
    odd = by(loaded["projects"], "odd")
    assert odd["identity"]["state"] == "unreadable" and odd["members"] == []
    assert any(p["kind"] == "unreadable" and p["text"] == "is not a file" for p in loaded["problems"])
    monkeypatch.setattr(places, "MAX_IDENTITY", 20)                               # too big to be a list
    loaded = places.load(world.cfg)
    assert by(loaded["projects"], "main")["identity"]["state"] == "unreadable"
    assert any("so it is not read" in p["text"] for p in loaded["problems"])
    monkeypatch.setattr(places, "_linked", lambda st: True)                      # a link is not followed
    loaded = places.load(world.cfg)
    assert by(loaded["projects"], "tools")["identity"]["state"] == "unreadable"
    assert any("is a link" in p["text"] for p in loaded["problems"])


def test_a_root_that_cannot_be_used_is_reported(world):
    data = world.data
    data["roots"] += [{"name": "ghost", "path": "shared/ghost", "kind": "repo"},       # the folder is not there
                      {"name": "again", "path": "shared/main", "kind": "repo"},        # the same folder as main
                      {"name": "escape", "path": "../elsewhere", "kind": "repo"},
                      {"name": "nameless"}, "not a record"]
    resave(world, data)
    loaded = places.load(world.cfg)
    found = kinds(loaded)
    assert {"missing-folder", "duplicate-root", "bad-path"} <= set(found) and found.count("bad-root") == 2
    ghost = by(loaded["projects"], "ghost")
    assert ghost["exists"] is False and ghost["members"] == [] and ghost["identity"]["state"] == "absent"
    names = [p["name"] for p in loaded["projects"]]
    assert "again" not in names and "escape" not in names and names.count("main") == 1    # the first listing stands


def test_two_seats_with_one_home_are_said_to_share_it_not_merged_in_silence(world):
    assert "shared-home" not in kinds(places.load(world.cfg))                       # control: three homes, none shared
    data = world.data
    data["seats"]["Bram"]["home"] = "ada"
    resave(world, data)
    loaded = places.load(world.cfg)
    shared = [p for p in loaded["problems"] if p["kind"] == "shared-home"]
    assert len(shared) == 1 and "Ada, Bram" in shared[0]["text"] and str(world.desk / "ada") in shared[0]["text"]
    assert "duplicate-root" not in kinds(loaded)            # the seats file lists that folder once: it is not "twice"
    assert [p["name"] for p in loaded["projects"]] == ["main", "tools", "Ada home", "Cleo home"]   # one folder, one
    assert by(loaded["projects"], "Ada home")["home_of"] == ["Ada", "Bram"]


def test_a_folder_listed_by_a_root_and_as_a_home_is_one_project_and_both_listings_are_named(world):
    data = world.data
    data["roots"] = [{"name": "ada-folder", "path": "ada", "kind": "repo"}] + data["roots"]
    resave(world, data)
    loaded = places.load(world.cfg)
    again = [p for p in loaded["problems"] if p["kind"] == "duplicate-root"]
    assert len(again) == 1 and "the root ada-folder" in again[0]["text"] and "Ada's home" in again[0]["text"]
    assert [p["name"] for p in loaded["projects"]] == ["ada-folder", "main", "tools", "Bram home", "Cleo home"]
    assert [m["name"] for m in by(loaded["projects"], "ada-folder")["members"]] == ["Ada"]    # still at home in it


def test_a_home_that_is_not_there_is_reported_once(world):
    data = world.data
    data["seats"]["Dov"] = {"names": ["Dov"], "groups": ["Crew"], "emails": [], "home": "dov"}
    resave(world, data)
    loaded = places.load(world.cfg)
    assert kinds(loaded).count("missing-folder") == 1                 # by the agent, not again by its home project
    assert by(loaded["projects"], "Dov home")["exists"] is False


# ---------------------------------------------------------------- the map's levels and ids
def test_the_levels_run_from_the_whole_through_groups_to_one_environment_per_home(world):
    loaded = places.load(world.cfg)
    top = loaded["levels"]
    assert (top["kind"], top["name"], top["measured"], top["members"]) == ("whole", "Everything", "2026-01-02", [])
    assert [(g["kind"], g["name"]) for g in top["children"]] == [("group", "Crew"), ("group", "Guests")]
    crew, guests = top["children"]                     # the first group only: "Crew-old" is no level
    assert [m["name"] for m in crew["members"]] == ["Ada", "Bram"]
    assert [m["name"] for m in guests["members"]] == ["Cleo"]
    assert [(e["kind"], e["name"], [m["name"] for m in e["members"]]) for e in crew["children"]] == [
        ("environment", "ada", ["Ada"]), ("environment", "bram", ["Bram"])]
    ada_env = crew["children"][0]
    assert ada_env["path"] == str(world.desk / "ada")
    assert ada_env["project_id"] == by(loaded["projects"], "Ada home")["id"]
    assert guests["children"][0]["name"] == "cleo"      # the folder's name, not the agent's


def test_an_agent_is_one_agent_in_every_place_it_appears(world):
    loaded = places.load(world.cfg)
    ada = by(loaded["agents"], "Ada")
    seen = []

    def walk(node):
        seen.extend(m["agent_id"] for m in node["members"] if m["name"] == "Ada")
        for child in node["children"]:
            walk(child)
    walk(loaded["levels"])
    in_projects = [p["id"] for p in loaded["projects"] if any(m["name"] == "Ada" for m in p["members"])]
    seen += [m["agent_id"] for p in loaded["projects"] for m in p["members"] if m["name"] == "Ada"]
    assert len(seen) == 4 and set(seen) == {ada["id"]}              # her group, her environment, main and her home
    assert ada["placed"]["projects"] == in_projects and len(in_projects) == 2
    assert ada["placed"]["group"] == loaded["levels"]["children"][0]["id"]
    assert ada["placed"]["environment"] == loaded["levels"]["children"][0]["children"][0]["id"]


def all_ids(loaded: dict) -> list[str]:
    ids = [a["id"] for a in loaded["agents"]] + [p["id"] for p in loaded["projects"]]
    ids += [d["id"] for d in loaded["documents"]]

    def walk(node):
        ids.append(node["id"])
        for child in node["children"]:
            walk(child)
    walk(loaded["levels"])
    return ids


def test_ids_are_short_stable_and_not_the_name_alone(world):
    write(world.desk / "ada" / "cv" / "alpha" / "MASTER.md", "# A\n", T)
    first, second = places.load(world.cfg), places.load(world.cfg)
    assert first == second                                            # the same files give the same ids
    ids = all_ids(first)
    assert len(ids) == len(set(ids)) and all(re.fullmatch(r"[0-9a-f]{10}", i) for i in ids)
    data = world.data
    data["seats"]["Cleo"]["groups"] = ["Ada"]                         # a group with an agent's name
    data["roots"][0]["name"] = "renamed"                              # a root with a new name
    resave(world, data)
    third = places.load(world.cfg)
    group = next(g for g in third["levels"]["children"] if g["name"] == "Ada")
    assert group["id"] != by(third["agents"], "Ada")["id"]            # same name, different kind of place
    assert by(third["projects"], "renamed")["id"] == by(first["projects"], "main")["id"]   # the folder keeps its id
    assert len(all_ids(third)) == len(set(all_ids(third)))
    elsewhere = write(world.seats.parent / "seats-elsewhere.json", json.dumps(world.data))
    other = places.load({**world.cfg, "seats": str(elsewhere)})
    assert by(other["agents"], "Bram")["id"] != by(first["agents"], "Bram")["id"]      # another file is another world


def test_a_seat_with_no_group_sits_directly_under_the_top_and_is_reported(world):
    data = world.data
    data["seats"]["Bram"]["groups"] = []
    resave(world, data)
    loaded = places.load(world.cfg)
    direct = [c for c in loaded["levels"]["children"] if c["kind"] == "environment"]
    assert [c["name"] for c in direct] == ["bram"] and by(loaded["agents"], "Bram")["placed"]["group"] is None
    assert "no-group" in kinds(loaded)
    assert [m["name"] for m in by(loaded["levels"]["children"], "Crew")["members"]] == ["Ada"]


def test_an_environment_carries_its_documents_count_and_newest_date(world):
    write(world.desk / "ada" / "cv" / "alpha" / "MASTER.md", "# A\n", T)
    write(world.desk / "ada" / "cv" / "beta" / "MASTER.md", "# B\n", T + 90)
    env = next(e for g in places.load(world.cfg)["levels"]["children"] for e in g["children"] if e["name"] == "ada")
    assert env["documents"] == 2 and env["updated"] == stamp(T + 90)
    other = next(e for g in places.load(world.cfg)["levels"]["children"] for e in g["children"] if e["name"] == "bram")
    assert other["documents"] == 0 and other["updated"] is None


# ---------------------------------------------------------------- the map file
def test_the_map_file_is_summed_up_and_never_written(world):
    before = (world.map.read_bytes(), world.map.stat().st_mtime_ns)
    summary = places.load(world.cfg)["map"]
    assert (summary["off"], summary["measured"], summary["places"], summary["edges"]) == (False, "2026-01-02", 4, 3)
    assert [(s["name"], s["title"], s["places"]) for s in summary["sectors"]] == [
        ("Alpha", "The first sector", 2), ("Beta", "The second sector", 1), ("Gamma", None, 1)]   # Gamma: not declared
    assert summary["top_level"] == {"sectors": 2, "repos": 2, "contradictions": 3,
                                    "overlay": {"places": 4, "edges": 3}}
    assert summary["file_updated"] == stamp(before[1] // 1_000_000_000) and summary["path"] == str(world.map)
    assert (world.map.read_bytes(), world.map.stat().st_mtime_ns) == before


def test_the_map_says_how_many_entries_carry_each_shape_it_gives_them(world, tmp_path):
    """'places' counts the entries of the map's list of places, and the map itself calls some of them not a place: the
    page must not say 'places' alone for what the map does not."""
    summary = places.load(world.cfg)["map"]
    assert summary["places"] == 4 and summary["shapes"] == {"circle": 1, "not-a-place": 2}    # the fourth gives none
    assert sum(summary["shapes"].values()) < summary["places"]
    odd = write(tmp_path / "odd.json", json.dumps({"measured": "d", "edges": [], "places": [
        {"shape": "line"}, {"shape": 5}, {"shape": None}, "not a record", {"shape": "line"}, {}]}))
    got = places.load({"map": str(odd)})["map"]
    assert got["places"] == 6 and got["shapes"] == {"line": 2}                       # only a shape in words is counted
    nothing = write(tmp_path / "none.json", json.dumps({"measured": "d"}))
    assert places.load({"map": str(nothing)})["map"]["shapes"] == {}


def test_places_and_edges_are_found_at_the_top_or_inside_overlay(tmp_path):
    flat = write(tmp_path / "flat.json", json.dumps({"measured": "2026-03-04", "places": [{}, {}], "edges": [{}]}))
    summary = places.load({"map": str(flat)})["map"]
    assert (summary["places"], summary["edges"], summary["measured"]) == (2, 1, "2026-03-04")
    assert summary["sectors"] == [{"name": None, "title": None, "places": 2}]     # places that name no sector


@pytest.mark.parametrize("text, kind", [
    (b"{not json", "not-json"),
    (b"[1, 2]", "shape"),
    (b'{"measured": "2026-01-01"}', "shape"),                     # no places and no edges
    (b'{"places": [], "edges": []}', "no-date"),                  # no date: the page must not guess one
    (b'{"measured": 20260101, "places": [], "edges": []}', "no-date"),
])
def test_a_map_of_the_wrong_shape_is_reported_and_says_nothing_it_does_not_know(tmp_path, text, kind):
    loaded = places.load({"map": str(write(tmp_path / "map.json", text))})
    assert kind in kinds(loaded)
    summary = loaded["map"]
    assert summary["measured"] is None or kind != "no-date"
    if kind == "shape":
        assert summary["places"] is None or summary["edges"] is None or isinstance(summary["places"], int)
    json.dumps(loaded)


def test_a_map_with_no_lists_counts_none_not_zero(tmp_path):
    summary = places.load({"map": str(write(tmp_path / "m.json", b'{"measured": "2026-01-01"}'))})["map"]
    assert summary["places"] is None and summary["edges"] is None and summary["measured"] == "2026-01-01"


@pytest.mark.parametrize("sectors", [2.5, True, "text", {"a": 1}, -1])
def test_a_map_whose_sectors_are_not_a_list_is_reported_not_a_failure(tmp_path, sectors):
    m = write(tmp_path / "m.json", json.dumps({"measured": "d", "sectors": sectors, "places": [{"sector": "X"}],
                                               "edges": []}))
    loaded = places.load({"map": str(m)})
    assert [p["kind"] for p in loaded["problems"]] == ["shape"]
    assert loaded["map"]["places"] == 1 and [s["name"] for s in loaded["map"]["sectors"]] == ["X"]   # still counted


def test_a_map_sector_with_no_name_or_a_repeated_one_is_counted_in_one_problem(tmp_path):
    sectors = [{"sector": "A", "title": "first"}, {"title": "no name"}, 5, {"sector": "A", "title": "again"},
               {"sector": "B"}]
    m = write(tmp_path / "m.json", json.dumps({"measured": "d", "sectors": sectors, "edges": [],
                                               "places": [{"sector": "A"}, {"sector": "B"}]}))
    loaded = places.load({"map": str(m)})
    shape = [p for p in loaded["problems"] if p["kind"] == "shape"]
    assert len(shape) == 1 and shape[0]["text"].startswith("3 of the map's 5 sectors")
    groups = [(s["name"], s["title"], s["places"]) for s in loaded["map"]["sectors"]]
    assert groups == [("A", "first", 1), ("B", None, 1)]
    clean = write(tmp_path / "c.json", json.dumps({"measured": "d", "sectors": sectors[:1] + sectors[4:], "edges": [],
                                                   "places": []}))
    assert places.load({"map": str(clean)})["problems"] == []              # well formed, the same way: nothing is said


def test_a_long_group_title_is_cut_at_a_word(tmp_path):
    title = "word " * 100
    m = write(tmp_path / "m.json", json.dumps({"measured": "d", "places": [], "edges": [],
                                               "sectors": [{"sector": "Long", "title": title}]}))
    cut = places.load({"map": str(m)})["map"]["sectors"][0]["title"]
    assert len(cut) <= places.TITLE_LIMIT + 1 and cut.endswith("word…") and title.startswith(cut[:-1])


# ---------------------------------------------------------------- documents
def test_a_cv_folder_with_a_master_is_a_document_dated_by_its_newest_file(world):
    cv = world.desk / "ada" / "cv"
    write(cv / "alpha" / "MASTER.md", "\ufeff# Alpha plan\n\nbody\n", T)
    write(cv / "alpha" / "notes.md", "intro\n# Detailed notes\n", T + 500)
    write(cv / "alpha" / "bare.md", "no heading here\n", T + 100)
    write(cv / "alpha" / "figure.svg", "<svg/>", T + 1000)
    write(cv / "alpha" / "data.csv", "a,b\n", T + 2000)                    # not a document, but it dates the folder
    write(world.desk / "bram" / "cv" / "gamma" / "MASTER.md", "# Gamma\n", T + 9000)
    documents = places.load(world.cfg)["documents"]
    assert [(d["agent"], d["slug"]) for d in documents] == [("Bram", "gamma"), ("Ada", "alpha")]     # newest first
    alpha = documents[1]
    assert (alpha["title"], alpha["master"], alpha["updated"]) == ("Alpha plan", "MASTER.md", stamp(T + 2000))
    assert alpha["path"] == str(cv / "alpha") and alpha["agent_id"] == by(places.load(world.cfg)["agents"], "Ada")["id"]
    assert alpha["docs"] == [{"file": "bare.md", "title": "bare", "updated": stamp(T + 100)},
                             {"file": "notes.md", "title": "Detailed notes", "updated": stamp(T + 500)}]
    assert alpha["diagrams"] == ["figure.svg"]


def test_what_the_shelf_rule_leaves_out_is_left_out(world):
    cv = world.desk / "ada" / "cv"
    write(cv / "kept" / "MASTER.md", "# Kept\n", T)
    write(cv / "kept" / ".hidden-newest", "x", T + 5000)               # a hidden file does not date the folder
    write(cv / "kept" / "sub" / "deep.txt", "x", T + 6000)             # nor does a file in a subfolder
    write(cv / "nomaster" / "notes.md", "# Notes\n", T)                # no MASTER.md: not shown, and said so
    write(cv / ".hidden" / "MASTER.md", "# Hidden\n", T)               # a hidden folder is not looked in
    write(cv / "loose.md", "# Loose\n", T)                             # a file in cv/ is no project
    loaded = places.load(world.cfg)
    mine = [d for d in loaded["documents"] if d["agent"] == "Ada"]
    assert [d["slug"] for d in mine] == ["kept"] and mine[0]["updated"] == stamp(T)
    missing = [p for p in loaded["problems"] if p["kind"] == "no-master"]
    assert [p["source"] for p in missing] == [str(cv / "nomaster")]
    assert missing[0]["text"] == "it has no MASTER.md, so it is not shown"
    assert not any(".hidden" in p["source"] or "loose" in p["source"] for p in loaded["problems"])


def test_two_agents_that_share_a_home_each_get_their_own_document_ids(world):
    data = world.data
    data["seats"]["Bram"]["home"] = "ada"
    resave(world, data)
    write(world.desk / "ada" / "cv" / "alpha" / "MASTER.md", "# A\n", T)
    loaded = places.load(world.cfg)
    mine = [d for d in loaded["documents"] if d["slug"] == "alpha"]
    assert sorted(d["agent"] for d in mine) == ["Ada", "Bram"] and len({d["id"] for d in mine}) == 2
    assert len(all_ids(loaded)) == len(set(all_ids(loaded)))
    assert by(loaded["projects"], "Ada home")["home_of"] == ["Ada", "Bram"]    # one folder, one project, both at home


def test_a_master_in_any_case_counts(world):
    write(world.desk / "bram" / "cv" / "lower" / "master.md", "# Lower\n", T)
    doc = next(d for d in places.load(world.cfg)["documents"] if d["slug"] == "lower")
    assert doc["master"] == "master.md" and doc["title"] == "Lower"


def test_a_document_over_the_size_cap_is_not_read(world, monkeypatch):
    monkeypatch.setattr(places, "DOC_CAP", 100)
    cv = world.desk / "bram" / "cv"
    write(cv / "big" / "MASTER.md", "# Big\n" + "x" * 200, T)           # too large to be the master at all
    write(cv / "big" / "extra.md", "# Extra\n" + "x" * 200, T + 100)
    write(cv / "small" / "MASTER.md", "# Small\n", T)
    loaded = places.load(world.cfg)
    assert [d["slug"] for d in loaded["documents"]] == ["small"]
    assert kinds(loaded).count("too-big") == 2 and kinds(loaded).count("no-master") == 1


def fill(folder: Path, count: int, when: int = T) -> None:
    for i in range(count):
        write(folder / f"f{i:03d}.txt", "x", when)


def test_a_folder_over_the_entry_limit_is_unknown_never_shown_wrong(world, monkeypatch):
    """Your inbox reads every entry. A reader that stops at a limit and carries on with the entries it has would either
    say 'no MASTER.md' (the file was past the cut) or give an older date (the newest file was): both wrong, and
    silent."""
    monkeypatch.setattr(places, "MAX_ENTRIES", 6)
    cv = world.desk / "ada" / "cv"
    fill(cv / "edge", 4)                                          # 4 + MASTER.md + late.txt = 6: at the limit, all read
    write(cv / "edge" / "MASTER.md", "# Edge\n", T)
    write(cv / "edge" / "late.txt", "x", T + 700)
    fill(cv / "big", 6)                                           # 6 + MASTER.md + late.txt = 8: over it
    write(cv / "big" / "MASTER.md", "# Big\n", T)
    write(cv / "big" / "late.txt", "x", T + 5000)
    loaded = places.load(world.cfg)
    assert [(d["slug"], d["updated"]) for d in loaded["documents"]] == [("edge", stamp(T + 700))]
    cut = [p for p in loaded["problems"] if p["kind"] == "too-many"]
    assert [Path(p["source"]).name for p in cut] == ["big"] and "unknown" in cut[0]["text"]
    assert "no-master" not in kinds(loaded)                       # it was not that the folder has none
    monkeypatch.setattr(places, "MAX_ENTRIES", 8)                 # control: with room for it, the folder is a document
    again = places.load(world.cfg)
    assert [(d["slug"], d["updated"]) for d in again["documents"]] == [("big", stamp(T + 5000)),
                                                                       ("edge", stamp(T + 700))]
    assert "too-many" not in kinds(again)


def test_a_cv_folder_over_the_entry_limit_shows_none_of_its_projects(world, monkeypatch):
    monkeypatch.setattr(places, "MAX_ENTRIES", 3)
    for slug in ("a", "b", "c", "d"):                             # four project folders: over the limit of three
        write(world.desk / "ada" / "cv" / slug / "MASTER.md", f"# {slug}\n", T)
    for slug in ("e", "f", "g"):                                  # three: at it
        write(world.desk / "bram" / "cv" / slug / "MASTER.md", f"# {slug}\n", T)
    loaded = places.load(world.cfg)
    assert sorted((d["agent"], d["slug"]) for d in loaded["documents"]) == [("Bram", "e"), ("Bram", "f"), ("Bram", "g")]
    cut = [p for p in loaded["problems"] if p["kind"] == "too-many"]
    assert [p["source"] for p in cut] == [str(world.desk / "ada" / "cv")] and "unknown" in cut[0]["text"]


def test_a_folder_that_cannot_be_listed_is_not_said_to_have_no_master(world, monkeypatch):
    write(world.desk / "ada" / "cv" / "locked" / "MASTER.md", "# L\n", T)
    write(world.desk / "ada" / "cv" / "open" / "MASTER.md", "# O\n", T)
    real = os.scandir

    def scandir(path="."):
        if Path(path).name == "locked":
            raise PermissionError(13, "Access is denied")
        return real(path)
    monkeypatch.setattr(places.os, "scandir", scandir)
    loaded = places.load(world.cfg)
    assert [d["slug"] for d in loaded["documents"]] == ["open"]
    assert [p["kind"] for p in loaded["problems"] if p["source"].endswith("locked")] == ["unreadable"]


def test_a_master_over_the_size_cap_is_said_to_be_too_big_not_to_be_missing(world, monkeypatch):
    monkeypatch.setattr(places, "DOC_CAP", 100)
    cv = world.desk / "bram" / "cv"
    write(cv / "big" / "MASTER.md", "# Big\n" + "x" * 200, T)
    write(cv / "none" / "notes.md", "# Notes\n", T)
    said = {Path(p["source"]).name: p["text"] for p in places.load(world.cfg)["problems"] if p["kind"] == "no-master"}
    assert said["none"] == "it has no MASTER.md, so it is not shown"          # control: here it is true
    assert "has no MASTER.md" not in said["big"] and said["big"].startswith("its MASTER.md is over")


def test_a_file_dated_before_1970_counts_as_the_start_of_1970(world):
    folder = world.desk / "ada" / "cv" / "old"
    write(folder / "MASTER.md", "# Old\n", T)
    extra = write(folder / "extra.md", "# Extra\n")
    try:
        os.utime(extra, (-86400, -86400))
    except (OSError, OverflowError, ValueError):
        pytest.skip("this machine cannot date a file before 1970")
    doc = next(d for d in places.load(world.cfg)["documents"] if d["slug"] == "old")
    assert doc["docs"] == [{"file": "extra.md", "title": "Extra", "updated": "1970-01-01T00:00:00Z"}]
    assert doc["updated"] == stamp(T)                                    # control: a file after 1970 dates as it is


def test_a_document_that_is_not_utf8_keeps_its_file_name_as_title_and_is_reported(world):
    write(world.desk / "ada" / "cv" / "latin" / "MASTER.md", b"# Caf\xe9 plan\n", T)
    loaded = places.load(world.cfg)
    assert next(d for d in loaded["documents"] if d["slug"] == "latin")["title"] == "MASTER"
    assert "encoding" in kinds(loaded)


@pytest.mark.parametrize("text, title", [
    ("# Title\n", "Title"), ("\ufeff# Title\r\n", "Title"), ("intro\n\n#  Later  \n", "Later"),
    ("#NoSpace\n", ""), ("## Deeper\n", ""), ("  # Indented\n", ""), ("", ""),
    ("# \n# Second\n", ""),               # an empty first heading is not stood in for by a later one
])
def test_the_first_heading_is_a_files_title(text, title):
    assert places._heading(text) == title


@pytest.mark.parametrize("name, why", [
    ("ok name", ""), ("a.b", ""), (".hidden", "hidden"), ("x..y", "not one plain segment"),
    ("a/b", "not one plain segment"), ("a\\b", "not one plain segment"), ("c:d", "not one plain segment"),
    ("a\x07b", "not one plain segment"), ("é" * 61, "empty or over 120 bytes"), ("é" * 60, ""),
])
def test_a_plain_name_is_one_path_segment_of_at_most_120_bytes(name, why):
    assert places._plain(name) == why


def test_no_cv_folder_means_no_documents_and_no_problem(world):
    loaded = places.load(world.cfg)
    assert loaded["documents"] == [] and kinds(loaded) == ["absent"]       # Bram's missing .identity, and nothing else


def test_a_link_in_cv_is_never_followed(world):
    cv = world.desk / "ada" / "cv"
    cv.mkdir(parents=True)
    write(world.desk / "bram" / "cv" / "real" / "MASTER.md", "# Real\n", T)      # reachable only through the link
    if not make_dir_link(world.desk / "bram" / "cv" / "real", cv / "linked"):
        pytest.skip("this machine cannot make a link")
    loaded = places.load(world.cfg)
    found = [(d["agent"], d["slug"]) for d in loaded["documents"]]
    assert found == [("Bram", "real")]                  # listed once, under its owner; never again through the link
    assert [p["source"] for p in loaded["problems"] if p["kind"] == "link"] == [str(cv / "linked")]


def test_a_cv_folder_that_is_itself_a_link_is_not_followed(world):
    write(world.desk / "bram" / "cv" / "real" / "MASTER.md", "# Real\n", T)
    if not make_dir_link(world.desk / "bram" / "cv", world.desk / "ada" / "cv"):
        pytest.skip("this machine cannot make a link")
    loaded = places.load(world.cfg)
    assert [d["agent"] for d in loaded["documents"]] == ["Bram"]
    assert [p["source"] for p in loaded["problems"] if p["kind"] == "link"] == [str(world.desk / "ada" / "cv")]


def test_a_link_to_a_file_inside_a_document_folder_does_not_date_it(world, monkeypatch):
    folder = world.desk / "ada" / "cv" / "alpha"
    write(folder / "MASTER.md", "# A\n", T)
    write(folder / "pointer.md", "x" * 77, T + 9000)    # a plain file, which the reader is made to see as a link below
    doc = next(d for d in places.load(world.cfg)["documents"] if d["slug"] == "alpha")
    assert doc["updated"] == stamp(T + 9000)                                   # control: as a plain file it counts
    assert [d["file"] for d in doc["docs"]] == ["pointer.md"]
    real = places._linked
    monkeypatch.setattr(places, "_linked", lambda st: st.st_size == 77 or real(st))
    loaded = places.load(world.cfg)
    doc = next(d for d in loaded["documents"] if d["slug"] == "alpha")
    assert doc["updated"] == stamp(T) and doc["docs"] == []
    assert [p["source"] for p in loaded["problems"] if p["kind"] == "link"] == [str(folder / "pointer.md")]


def test_a_symbolic_link_inside_a_document_folder_does_not_date_it(world):
    folder = world.desk / "ada" / "cv" / "alpha"
    write(folder / "MASTER.md", "# A\n", T)
    newer = write(world.desk / "bram" / "newer.md", "# N\n", T + 9000)
    try:
        os.symlink(newer, folder / "pointer.md")
    except OSError:
        pytest.skip("this machine cannot make a symbolic link without a privilege")
    doc = next(d for d in places.load(world.cfg)["documents"] if d["slug"] == "alpha")
    assert doc["updated"] == stamp(T) and doc["docs"] == []


def fake(mode: int, attributes: int | None = None, tag: int = 0):
    out = SimpleNamespace(st_mode=mode)
    if attributes is not None:
        out.st_file_attributes, out.st_reparse_tag = attributes, tag
    return out


@pytest.mark.parametrize("st, linked", [
    (fake(stat.S_IFLNK | 0o777), True),                              # a symbolic link
    (fake(stat.S_IFDIR, 0x410, 0xA0000003), True),                   # a Windows junction
    (fake(stat.S_IFREG, 0x400, 0xA000000C), True),                   # a Windows symbolic link
    (fake(stat.S_IFREG, 0x420, 0x9000001A), False),                  # a cloud placeholder holds its own bytes
    (fake(stat.S_IFDIR, 0x10, 0), False),
    (fake(stat.S_IFREG), False),                                     # a POSIX stat has no Windows attributes at all
])
def test_a_link_is_a_symlink_or_a_reparse_point_that_names_another_place(st, linked):
    assert places._linked(st) is linked


def test_loading_writes_nothing(world):
    write(world.desk / "ada" / "cv" / "alpha" / "MASTER.md", "# A\n", T)

    def snapshot():
        return {str(p): (p.stat().st_size, p.stat().st_mtime_ns, p.read_bytes())
                for p in world.desk.parent.rglob("*") if p.is_file()}
    before = snapshot()
    json.dumps(places.load(world.cfg))
    assert snapshot() == before
    write(world.desk / "ada" / "requests.jsonl.x", b"")                    # the snapshot does see a file planted beside
    assert snapshot() != before
    before = snapshot()
    write(world.desk / "ada" / "cv" / "alpha" / "MASTER.md", "# B\n", T)     # ... and one rewritten as long as before
    assert snapshot() != before


# ---------------------------------------------------------------- which project a card belongs to
PROJECTS = [{"id": "outer", "path": "C:\\work\\Proj"},
            {"id": "inner", "path": "C:\\work\\Proj\\inner"},
            {"id": "spaced", "path": "C:\\My Work\\Proj A"},
            {"id": "unix", "path": "/srv/app"}]


def adds_up(result: dict, cards: list) -> bool:
    return sum(len(v) for v in result.values()) == len(cards)


@pytest.mark.parametrize("cwd, project", [
    ("C:\\work\\Proj", "outer"), ("c:/WORK/proj/src/deep", "outer"), ("C:\\work\\Proj\\", "outer"),
    ("C:\\work\\Proj\\inner", "inner"), ("C:/work/Proj/inner/x", "inner"),
    ("C:\\work\\Proj\\.\\src\\..\\inner", "inner"),
    ("C:\\My Work\\Proj A\\tests", "spaced"), ("/srv/app/bin", "unix"),
])
def test_a_card_belongs_to_the_project_its_cwd_lies_in(cwd, project):
    got = places.placement({"id": "c", "cwd": cwd}, PROJECTS)
    assert (got["project"], got["via"], got["field"]) == (project, "cwd", "cwd")


@pytest.mark.parametrize("cwd", ["C:\\work\\Proj-old", "C:\\work\\Project", "C:\\work", "D:\\work\\Proj",
                                 "C:\\work\\Prof", "/srv/application", "/SRV/app", ".", "proj", "..\\Proj", "", None,
                                 7])
def test_a_folder_that_only_looks_like_a_project_is_not_in_it(cwd):
    assert places.placement({"id": "c", "cwd": cwd}, PROJECTS)["project"] is None


def test_the_deepest_project_wins():
    assert places.placement({"cwd": "C:\\work\\Proj\\inner\\src"}, PROJECTS)["project"] == "inner"
    assert places.placement({"cwd": "C:\\work\\Proj\\other"}, PROJECTS)["project"] == "outer"
    both = {"why": "see C:\\work\\Proj\\README.md and C:\\work\\Proj\\inner\\notes.md"}
    assert places.placement(both, PROJECTS)["project"] == "inner"             # though the outer is written first
    assert places.placement({"why": "see C:\\work\\Proj\\README.md"}, PROJECTS)["project"] == "outer"


@pytest.mark.parametrize("card, project, field", [
    ({"command": "git -C C:\\work\\Proj status"}, "outer", "command"),
    ({"options": ["Leave it", "Move C:/My Work/Proj A/data to the archive"]}, "spaced", "options"),
    ({"why": 'The file "C:\\work\\Proj\\inner\\a.txt" is stale.'}, "inner", "why"),
    ({"title": "Look in c:\\WORK\\PROJ."}, "outer", "title"),                 # a full stop ending a sentence
    ({"question": "Is /srv/app/config ok?"}, "unix", "question"),
    ({"does": "writes to C:\\\\work\\\\Proj\\\\out"}, "outer", "does"),         # slashes doubled by quoting
    ({"why": "(C:\\work\\Proj)"}, "outer", "why"),
    ({"why": "file:///C:/work/Proj/x.txt"}, "outer", "why"),
])
def test_a_path_written_in_the_text_places_a_card_that_has_no_cwd(card, project, field):
    got = places.placement({"id": "c", **card}, PROJECTS)
    assert (got["project"], got["via"], got["field"], got["path"]) == (
        project, "text", field, next(p["path"] for p in PROJECTS if p["id"] == project))


@pytest.mark.parametrize("text", [
    "see Proj/inner/readme.md", "the work\\Proj folder", "C:\\work\\Proj-old\\x", "C:\\work\\Proj.md",
    "C:\\work\\Projects", "xC:\\work\\Proj", "~/srv/app/x", "/srv/application/x", "https://example.test/work/Proj",
    "no path at all", "C:\\work\\Proj_2", "C:\\work\\Prof",
])
def test_text_that_only_looks_like_a_path_to_a_project_places_nothing(text):
    assert places.placement({"id": "c", "why": text}, PROJECTS)["project"] is None


def test_the_folder_a_card_ran_in_outranks_a_path_in_its_text():
    card = {"id": "c", "cwd": "C:\\work\\Proj", "why": "it edits C:\\My Work\\Proj A\\x"}
    got = places.placement(card, PROJECTS)
    assert (got["project"], got["via"]) == ("outer", "cwd")
    got = places.placement({**card, "cwd": "D:\\elsewhere"}, PROJECTS)         # outside every project: the text decides
    assert (got["project"], got["via"]) == ("spaced", "text")


def test_a_card_that_ran_in_one_project_is_not_moved_by_a_deeper_project_its_words_name():
    """The plan's rule, decided and not reopened: where a card ran comes first; its words decide only for a card whose
    folder is in no project."""
    pair = [{"id": "hub", "path": "C:\\w\\hub"}, {"id": "ada", "path": "C:\\w\\homes\\ada"}]
    card = {"id": "c1", "cwd": "C:\\w\\hub\\inbox", "why": "it rewrites C:\\w\\homes\\ada\\notes.md"}
    got = places.placement(card, pair)
    assert (got["project"], got["via"], got["field"]) == ("hub", "cwd", "cwd")
    assert places.assign([card], pair) == {"hub": ["c1"], "ada": [], "unassigned": []}
    no_folder = {k: v for k, v in card.items() if k != "cwd"}
    assert places.placement(no_folder, pair)["project"] == "ada"                                       # then the words
    assert places.placement({**card, "cwd": "D:\\elsewhere"}, pair)["project"] == "ada"                  # in no project


KINDS = [{"id": "drive", "path": "C:\\w\\Proj"}, {"id": "ica", "path": "C:\\w\\To be observed\\Ica"},
         {"id": "share", "path": "\\\\nas\\team"}, {"id": "posix", "path": "/srv/app"}]


def where(text: str):
    return places.placement({"id": "c", "why": text}, KINDS)["project"]


@pytest.mark.parametrize("text", [
    "the old copy is in C:\\w\\Proj Archive\\old.md", "moved to C:\\w\\To be observed\\Ica Backup\\x.md",
    "see C:\\w\\Proj (copy)\\notes.md", "C:\\w\\Proj(copy)\\x", "C:\\w\\Proj[1]\\x", "C:\\w\\Proj's notes",
    "C:\\w\\Proj,old\\x", "C:\\w\\Proj.old\\x", "C:\\w\\Proj+more", "the Proj folder: C:\\w\\Proj-2\\x", "C:\\w\\Projx",
])
def test_a_path_that_goes_on_into_a_longer_folder_name_is_not_in_the_project(text):
    assert where(text) is None


@pytest.mark.parametrize("text", [
    "see C:\\w\\Proj for details", "git -C C:\\w\\Proj diff src/main.py", "cd C:\\w\\Proj;git status",
    "cd /d C:\\w\\Proj&& dir", "'C:\\w\\Proj'", '"C:\\w\\Proj"', "`C:\\w\\Proj`", "(edit C:\\w\\Proj)", "[C:\\w\\Proj]",
    "{C:\\w\\Proj}", "<C:\\w\\Proj>", "C:\\w\\Proj, then", "Is it C:\\w\\Proj?", "Look in C:\\w\\Proj!", "C:\\w\\Proj.",
    "C:\\w\\Proj...", "C:\\w\\Proj:", "C:\\w\\Proj\\", "C:\\w\\Proj/", "C:\\w\\Proj\\sub\\a.md", "C:\\w\\Proj \\sub",
    "path=C:\\w\\Proj", "a,C:\\w\\Proj", "C:\\w\\Proj C:\\w\\Other", "C:\\w\\Proj\\*.md", "C:\\w\\Proj\\.",
    "C:\\w\\Proj\\.\\sub", "C:\\w\\Proj", "  C:\\w\\Proj  ", "C:\\w\\Proj\nnext line", "C:\\w\\Proj\tx",
])
def test_a_path_that_ends_at_a_boundary_is_in_the_project(text):
    assert where(text) == "drive"


def test_a_space_ends_the_path_unless_the_one_word_after_it_is_followed_by_a_slash():
    """'Proj Archive\\old.md' is a folder called 'Proj Archive'; 'Proj diff src/main.py' is the project, then words. A
    folder named by two words after the project's own cannot be told from the words that follow, and counts as the
    words (this is the known limit, written down so that it is chosen and not found)."""
    assert where("C:\\w\\Proj Archive\\old.md") is None and where("C:\\w\\Proj diff src/main.py") == "drive"
    assert where("C:\\w\\To be observed\\Ica Backup\\x") is None and where("C:\\w\\To be observed\\Ica now") == "ica"
    assert where("C:\\w\\Proj Old Stuff\\a.md") == "drive"            # the limit
    assert where("C:\\w\\Proj src/main.py") is None                   # one word, then a slash: more of the name


@pytest.mark.parametrize("text", [
    "see C:\\nas\\team\\notes.txt", "copy C:\\srv\\app\\x.txt", "\\\\host\\srv\\app\\x", "//host/srv/app/x",
    "https://example.test/srv/app/x", "ftp://nas/team/x", "x/nas/team", "x\\\\nas\\team", "C:\\Users\\nas\\team\\x",
    "~/srv/app", "$HOME/srv/app", "./srv/app/x", "..\\srv\\app", "file:C:/srv/app",
])
def test_a_path_of_another_kind_that_holds_the_projects_names_is_not_in_it(text):
    assert where(text) is None


@pytest.mark.parametrize("text, project", [
    ("see \\\\nas\\team\\notes.txt", "share"), ("see //NAS/Team/notes.txt", "share"),
    ("\\\\\\\\nas\\\\team\\\\x", "share"),                                         # every slash doubled by quoting
    ("copy /srv/app/x.txt", "posix"), ("file:///srv/app/x", "posix"), ("file://nas/team/x", "share"),
    ("file:///C:/w/Proj/x", "drive"), ("cd '/srv/app'", "posix"), ("--cwd=/srv/app", "posix"),
    ("\\\\?\\C:\\w\\Proj\\x", "drive"), ("(/srv/app)", "posix"), ("a\n/srv/app\nb", "posix"),
])
def test_a_path_of_the_projects_own_kind_is_found_however_it_is_written(text, project):
    assert where(text) == project


@pytest.mark.parametrize("card, project", [
    ({"cwd": "C:\\..\\w\\Proj\\src"}, "drive"),                   # ".." at the top of a drive stays at the top
    ({"cwd": "C:\\..\\..\\w\\Proj"}, "drive"), ({"cwd": "C:\\w\\other\\..\\Proj"}, "drive"),
    ({"cwd": "C:\\w\\.\\Proj\\."}, "drive"), ({"cwd": "C:\\w\\Proj.\\src"}, "drive"),    # Windows drops end dots
    ({"cwd": "\\\\nas\\team\\..\\..\\x"}, "share"),               # nor can ".." take away a share's server or its name
    ({"cwd": "/srv/../srv/app/./x"}, "posix"), ({"cwd": "/../srv/app"}, "posix"),
    ({"why": "edit C:\\w\\other\\..\\Proj\\x.md"}, "drive"), ({"why": "edit C:\\..\\w\\Proj\\x.md"}, "drive"),
    ({"why": "edit C:\\w\\.\\Proj\\x.md"}, "drive"), ({"why": "edit \\\\nas\\team\\..\\team\\x"}, "share"),
    ({"why": "cd /srv/./app/../app"}, "posix"), ({"why": "edit C:\\My Work\\..\\w\\Proj\\x"}, "drive"),
    ({"why": "edit C:\\w\\Proj\\sub\\.."}, "drive"),
])
def test_dots_are_worked_out_as_windows_works_them_out_before_a_path_is_compared(card, project):
    assert places.placement({"id": "c", **card}, KINDS)["project"] == project


@pytest.mark.parametrize("card", [
    {"cwd": "C:\\w\\Proj\\..\\other"}, {"cwd": "C:\\w\\Proj\\..\\..\\x"}, {"cwd": "C:\\..\\Proj"},
    {"cwd": "/srv/app/../other"},
    {"why": "edit C:\\w\\Proj\\..\\other\\x.md"}, {"why": "edit C:\\w\\Proj\\sub\\..\\..\\x"},
    {"why": "C:\\w\\Proj\\.."},
    {"why": "edit C:\\w\\Proj\\..\\Proj-old\\x"}, {"why": "cd /srv/app/../other"},
])
def test_a_path_that_dots_take_out_of_the_project_is_not_in_it(card):
    assert places.placement({"id": "c", **card}, KINDS)["project"] is None


def test_a_comma_or_a_bang_before_a_slash_is_part_of_a_folder_name_and_a_dot_is_not():
    assert where("C:\\w\\Proj!\\sub") is None
    assert where("C:\\w\\Proj!") == "drive" and where("C:\\w\\Proj!, then") == "drive"
    assert where("C:\\w\\Proj.\\sub") == "drive"              # Windows drops the dot from the end of a name
    assert where("C:\\w\\Proj,/srv/other") == "drive"         # a slash after a comma starts another path


def test_a_project_that_is_a_drive_root_or_the_root_holds_what_lies_under_it():
    roots = [{"id": "c", "path": "C:\\"}, {"id": "deep", "path": "C:\\w"}, {"id": "slash", "path": "/"}]

    def got(card):
        return places.placement(card, roots)["project"]
    assert got({"cwd": "C:\\x\\y"}) == "c" and got({"cwd": "C:\\w\\y"}) == "deep"            # the deepest holds it
    assert got({"why": "see C:\\x\\y for it"}) == "c" and got({"why": "see D:\\x"}) is None
    assert got({"why": "see /srv/x"}) == "slash" and got({"why": "rm -rf /*"}) is None        # a glob is not a path


def test_a_share_with_no_server_is_not_a_project_or_a_folder():
    assert places.placement({"cwd": "\\\\"}, [{"id": "r", "path": "\\\\"}])["project"] is None
    assert places.placement({"cwd": "//"}, [{"id": "r", "path": "//"}])["project"] is None
    server = places.placement({"cwd": "\\\\nas"}, [{"id": "r", "path": "\\\\nas"}])
    assert server["project"] == "r"                                                       # a server alone is one


@pytest.mark.parametrize("card, project", [
    ({"cwd": "\\\\?\\C:\\w\\Proj\\src"}, "drive"), ({"cwd": "\\\\.\\C:\\w\\Proj"}, "drive"),
    ({"cwd": "\\\\?\\UNC\\nas\\team\\x"}, "share"), ({"cwd": "\\\\?\\unc\\nas\\team"}, "share"),
])
def test_an_extended_path_prefix_is_the_path_it_prefixes(card, project):
    assert places.placement({"id": "c", **card}, KINDS)["project"] == project
    ext = [{"id": "ext", "path": "\\\\?\\C:\\w\\Ext"}, {"id": "extshare", "path": "\\\\?\\UNC\\nas\\other"}]
    assert places.placement({"cwd": "C:\\w\\Ext\\x"}, ext)["project"] == "ext"                # and a project written so
    assert places.placement({"cwd": "\\\\nas\\other\\x"}, ext)["project"] == "extshare"


def test_names_of_only_dots_and_spaces_are_nothing_on_windows_and_names_elsewhere():
    assert places.placement({"cwd": "C:\\w\\...\\Proj\\src"}, KINDS)["project"] == "drive"
    assert places.placement({"cwd": "C:\\w\\ \\Proj"}, KINDS)["project"] == "drive"
    assert where("edit C:\\w\\...\\Proj\\x") == "drive"
    assert places.placement({"cwd": "/srv/.../app/x"}, KINDS)["project"] is None       # on a POSIX path they are names
    assert places.placement({"cwd": "/srv/ /app"}, KINDS)["project"] is None


def test_the_fields_a_path_can_be_found_in_are_the_ones_the_agent_asked_in():
    asked = places.placement({"options": ["no", "see C:\\w\\Proj for it"]}, KINDS)
    assert (asked["project"], asked["via"], asked["field"], asked["path"]) == (
        "drive", "text", "options", "C:\\w\\Proj")


# ---------------------------------------------------------------- the same rule, stated the other way round
# The reader finds the full paths written in a text and compares each with the projects. This states the rule from the
# project's side: a regular expression of the project's folder over the whole text, a boundary after its last name, and
# Python's own ntpath/posixpath to work the dots out. The two are built differently, so a slip in one shows against the
# other.
_HARD = "\\x00-\\x1f\\x7f\"<>|*?:;&"                         # no folder name holds these; in a command they end a path
_OPENERS = "\\s\"'`(\\[{<>=,;|"                                # what may stand before a path that has no drive letter
_WORD = "[^\\s/" + _HARD + "]"
_END = ("(?=$|/|[)\\]}" + _HARD + "'`]|\\.+(?=/)|[.,!]*,(?=/+[^/\\s])|[.,!]+(?:$|\\s|[)\\]}" + _HARD + "'`])"
        "|(?=\\s)(?!\\s+" + _WORD + "*[^\\s/" + _HARD + "'`(\\[{=,]/))")


def _ref_view(text: str) -> str:
    t = text.replace("\\", "/")
    for pat in (r"(?i)(?<![\w.~-])file:/{2,3}(?=[A-Za-z]:/)", r"(?i)(?<![\w.~-])file://(?=/[^/\s])",
                r"(?i)(?<![\w.~-])file:(?=//[^/\s])"):
        t = re.sub(pat, lambda m: " " * len(m.group()), t)

    def worked_out(m):
        run = m.group(0)
        if not re.search(r"(?:^|/)\.\.?(?:/|$)", run) or "/" not in run:
            return run
        head, _, tail = run.rpartition("/")
        if tail in (".", ".."):
            head, tail = run, ""
        lead = "//" if run.startswith("//") else ""
        head = lead + re.sub(r"/+", "/", head.lstrip("/") if lead else head)
        walk = ntpath if re.match(r"[A-Za-z]:/", run) or lead else posixpath
        return walk.normpath(head + "/").replace("\\", "/").rstrip("/") + "/" + tail
    body = r"(?:(?!(?<![\w.~-])[A-Za-z]:/)(?!(?<=[" + _OPENERS + r"])/+[^/\s])[^" + _HARD + r"])*"
    return re.sub(r"(?:(?<![\w.~-])[A-Za-z]:|(?<![^" + _OPENERS + r"])/+(?=[^/\s]))" + body, worked_out, t)


def ref_written(text: str, path: str) -> bool:
    """Whether the project's folder is written in the text, at a boundary of names."""
    p = path.strip().replace("\\", "/")
    if re.match(r"[A-Za-z]:(/|$)", p):
        norm = ntpath.normpath(p).replace("\\", "/")
        head, names, flags = r"(?<![\w.~-])" + re.escape(norm[:2]) + "/+", norm[2:].strip("/").split("/"), re.I
    elif p.startswith("//"):
        names = ntpath.normpath(p).replace("\\", "/").strip("/").split("/")
        head, flags = r"(?<![^" + _OPENERS + r"])/{2,}", re.I
    else:
        head, names, flags = r"(?<![^" + _OPENERS + r"])/(?!/)", posixpath.normpath(p).strip("/").split("/"), 0
    seen = _ref_view(text)
    for m in re.finditer(head + "/+".join(re.escape(n) for n in names if n) + _END, seen, flags):
        opened = seen[m.start() - 1] if m.start() else ""
        after = seen[m.end():m.end() + 1]
        if after in ("'", "`") and after != opened:
            continue                                  # an apostrophe that did not open the path is part of a name
        if after and after in ".,!" and seen[m.end():].lstrip(".,!")[:1] in ("'", "`") \
                and seen[m.end():].lstrip(".,!")[:1] != opened:
            continue
        return True
    return False


_REF_PROJECTS = {"drive": "C:\\w\\Proj", "ica": "C:\\w\\To be observed\\Ica", "spaced": "C:\\My Work\\Proj A",
                 "share": "\\\\nas\\team", "posix": "/srv/app", "dd": "D:\\x"}
_REF_PREFIXES = ["", "", "see ", "cd ", "git -C ", "(", "'", '"', "`", "[", "{", "<", "=", "path=", "a,", "x;", "\n",
                 "  ", "file:///", "file://", "xC:", "$", "~", "./", "1) "]
_REF_SUFFIXES = ["", "", "\\sub", "/sub\\x.md", " for details", " diff src/main.py", " Archive\\old.md", " (copy)\\x",
                 "(copy)", "-old", "_2", ".md", ".", "..", ",", ", then", ";", "; echo", ":", "!", "?", ")", "]", "'",
                 "'s", '"', ">", "|", "*", "\\.", "\\..", "\\..\\other", "\\.\\sub", "\\sub\\..", " x", "&&", "\n",
                 "\tnext", "!\\sub", "!/", ",\\sub", ".\\sub", ",.\\x",
                 " /x", " foo/bar", " Old Stuff\\a.md", " (/x)", "\\", "/", "\\*.md", " C:\\w\\Other", " /srv/other",
                 "é", "ß", "+", "#", "@", "%", "^"]


def _ref_spelling(path: str, rng: random.Random) -> str:
    p = path.replace("\\", "/") if rng.random() < 0.25 else path
    if rng.random() < 0.2:
        p = p.upper() if rng.random() < 0.5 else p.lower()
    sep, share = ("\\" if "\\" in p else "/"), p.startswith(("\\\\", "//"))
    parts = p.split(sep)
    if rng.random() < 0.15 and len(parts) > 3:
        parts.insert(rng.randrange(4 if share else 2, len(parts) + (1 if share else 0)),
                     rng.choice(["x", "other"]) + sep + "..")
    if rng.random() < 0.08 and len(parts) > 2:
        parts.insert(rng.randrange(4 if share else 1, len(parts) + (1 if share else 0)), ".")
    p = sep.join(parts)
    if rng.random() < 0.15:
        p = p.replace("\\", "\\\\") if "\\" in p else p.replace("/", "//")
    return p


def _ref_text(rng: random.Random) -> str:
    paths = list(_REF_PROJECTS.values())
    text = rng.choice(_REF_PREFIXES) + _ref_spelling(rng.choice(paths), rng) + rng.choice(_REF_SUFFIXES)
    if rng.random() < 0.3:
        text += rng.choice([" and ", ", ", "; ", "\n", " "]) + rng.choice(_REF_PREFIXES) \
            + _ref_spelling(rng.choice(paths), rng) + rng.choice(_REF_SUFFIXES)
    return text


def _ref_disagreements(texts: list) -> list:
    out = []
    for text in texts:
        for pid, path in _REF_PROJECTS.items():
            got = places.placement({"id": "c", "why": text}, [{"id": pid, "path": path}])["project"] is not None
            if got != ref_written(text, path):
                out.append((text, pid, got))
    return out


def test_the_reader_agrees_with_the_rule_stated_from_the_projects_side():
    rng = random.Random(20261014)
    texts = [_ref_text(rng) for _ in range(1500)]
    wrong = _ref_disagreements(texts)
    assert wrong == [], wrong[:5]
    hits = sum(ref_written(t, p) for t in texts for p in _REF_PROJECTS.values())
    assert 500 < hits < len(texts) * len(_REF_PROJECTS) // 2        # control: the words write paths, but not all


def test_that_comparison_fails_for_a_reader_that_ignores_boundaries(monkeypatch):
    rng = random.Random(20261014)
    texts = [_ref_text(rng) for _ in range(300)]
    assert _ref_disagreements(texts) == []                          # control: the reader as it is
    monkeypatch.setattr(places, "_ends", lambda rest, closed, opened: True)
    assert len(_ref_disagreements(texts)) > 20                      # a reader that takes any ending as one is caught
    monkeypatch.undo()
    monkeypatch.setattr(places, "_ends", lambda rest, closed, opened: not rest)
    assert len(_ref_disagreements(texts)) > 20                      # and one that takes only the end of the words


def test_no_words_can_break_assign_or_make_its_count_wrong():
    pieces = ["C:", "c:", "D:", "/", "\\", "\\\\", "//", ".", "..", "work", "Proj", "srv", "app", "nas", "team", " ",
              "  ", "\t", "\n", "'", '"', "`", "(", ")", "[", "]", ";", "&", ":", "?", "*", "<", ">", "|", ",", "!",
              "-", "_", "é", "ß", "\x00", "file:", "~", "%", "a b", "\ufffd", "\u2028"]
    projects = PROJECTS + KINDS + [{"id": "root", "path": "C:\\"}, {"id": "slash", "path": "/"}]
    rng = random.Random(20261014)
    for _ in range(3000):
        text = "".join(rng.choice(pieces) for _ in range(rng.randrange(0, 30)))
        card = {"id": "c", "why": text, "cwd": rng.choice([text, "C:\\work\\Proj", None, "", 5]),
                "options": [text, 5, None], "command": {"a": [text]}}
        got = places.placement(card, projects)
        assert set(got) == {"project", "via", "field", "path"}
        assert (got["project"] is None) == (got["via"] is None) and got["via"] in ("cwd", "text", None)
        assert adds_up(places.assign([card, card], projects), [card, card])


def test_at_equal_depth_the_path_written_first_wins():
    pair = [{"id": "a", "path": "C:\\w\\one"}, {"id": "b", "path": "C:\\w\\two"}]
    assert places.placement({"why": "C:\\w\\two then C:\\w\\one"}, pair)["project"] == "b"
    assert places.placement({"why": "C:\\w\\one then C:\\w\\two"}, pair)["project"] == "a"
    assert places.placement({"title": "C:\\w\\one", "why": "C:\\w\\two"}, pair)["project"] == "a"


def test_a_path_in_what_was_added_to_a_card_after_it_was_asked_places_nothing():
    path = "C:\\work\\Proj\\x"
    asked = {"id": "c", "why": f"edit {path}"}
    assert places.placement(asked, PROJECTS)["project"] == "outer"                     # control: written in the ask
    added = {"id": "c", "why": "no path here", "state": path, "seat": path, "at": path,
             "raw": '{"why": "' + path.replace("\\", "\\\\") + '"}', "closing": {"how": f"done in {path}", "raw": path},
             "run": {"started": path, "exit": 0}, "asks": path}
    assert places.placement(added, PROJECTS)["project"] is None


def test_the_fields_are_read_in_a_fixed_order_whatever_order_a_card_keeps_them_in():
    pair = [{"id": "a", "path": "C:\\w\\one"}, {"id": "b", "path": "C:\\w\\two"}]
    assert places.placement({"title": "C:\\w\\one", "why": "C:\\w\\two"}, pair)["project"] == "a"
    assert places.placement({"why": "C:\\w\\two", "title": "C:\\w\\one"}, pair)["project"] == "a"    # title comes first
    assert places.placement({"undo": "C:\\w\\one", "does": "C:\\w\\two"}, pair)["project"] == "b"    # does before undo


def test_every_card_lands_in_exactly_one_list():
    cards = [{"id": "a", "cwd": "C:\\work\\Proj"},
             {"id": "b", "why": "C:\\work\\Proj\\inner"},
             {"id": "c", "why": "nothing here"},
             {"id": "a", "cwd": "/srv/app"},                       # the same id again: both are kept
             {"cwd": "C:\\work\\Proj"},                            # no id: listed as its place
             "not a record", 7, None, {}]
    out = places.assign(cards, PROJECTS)
    assert adds_up(out, cards)
    assert set(out) == {"outer", "inner", "spaced", "unix", "unassigned"}
    assert out["outer"] == ["a", "#5"] and out["inner"] == ["b"] and out["unix"] == ["a"] and out["spaced"] == []
    assert out["unassigned"] == ["c", "#6", "#7", "#8", "#9"]
    dropped = {k: list(v) for k, v in out.items()}
    dropped["outer"].pop()                                          # a result that lost a card must not add up
    assert not adds_up(dropped, cards)
    doubled = {k: list(v) for k, v in out.items()}
    doubled["unassigned"].append("again")                           # nor one that counted a card twice
    assert not adds_up(doubled, cards)


def test_assign_takes_no_cards_no_projects_or_a_stream_of_cards():
    assert places.assign([], PROJECTS) == {"outer": [], "inner": [], "spaced": [], "unix": [], "unassigned": []}
    assert places.assign([{"id": "x", "cwd": "C:\\work\\Proj"}], []) == {"unassigned": ["x"]}
    assert places.assign(({"id": n} for n in range(3)), PROJECTS)["unassigned"] == [0, 1, 2]


def test_a_project_cannot_take_the_name_of_the_unassigned_list():
    with pytest.raises(ValueError):
        places.assign([{"id": "x"}], [{"id": "unassigned", "path": "C:\\work\\Proj"}])


def test_assign_places_the_cards_of_a_loaded_world(world):
    projects = places.load(world.cfg)["projects"]
    main, ada = by(projects, "main"), by(projects, "Ada home")
    cards = [{"id": "1", "cwd": str(world.desk / "shared" / "main" / "src")},
             {"id": "2", "why": f"the notes are in {world.desk / 'ada' / 'cv'}"},
             {"id": "3", "cwd": str(world.desk / "notes")},
             {"id": "4", "why": "no path"}]
    out = places.assign(cards, projects)
    assert adds_up(out, cards)
    assert out[main["id"]] == ["1"] and out[ada["id"]] == ["2"] and out["unassigned"] == ["3", "4"]
    assert places.placement(cards[1], projects)["project"] == ada["id"]
