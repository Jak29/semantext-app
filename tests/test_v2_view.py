"""The page's places (sources/view.py), built from synthetic sources in tmp_path.

A world here is everything a person keeps: four agents' homes (each a repository with its own gates), a shared
repository, the inbox folder, a register and its notes, rule cards and a map. Three agents are in the config's group and
one is not. Every check has a must-pass arm and a must-refuse arm: the place agrees with the readers, and a planted change
or a planted defect moves it, or a wrong value is told apart from the right one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from semantext.sources import cards, gates, places, record, rules, view
from semantext.sources.gates import World as GitWorld

ALL_FOUR = ("pre-commit", "commit-msg", "applypatch-msg", "pre-push")
GATED = "\thooksPath = chain\n"


def touch(path: Path, text: str = "") -> Path:
    """A file, made executable: on POSIX the gates reader, as git, ignores a hook without the bit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    path.chmod(0o755)
    return path


def lines(path: Path, *rows) -> None:
    """A JSON-lines file; a row that is a string is written as it is (a damaged line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows).encode("utf-8"))


def append(path: Path, *rows) -> None:
    with path.open("ab") as f:
        f.write("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows).encode("utf-8"))


def ask(id_, at, **kw):
    return {"id": id_, "at": at, "kind": "decision", "title": f"Title {id_}", "why": "because", "question": "Which?",
            "options": ["first (my pick)", "second"], **kw}


def cmd(id_, at, **kw):
    return {"id": id_, "at": at, "kind": "command", "title": f"Title {id_}", "why": "because",
            "command": "Write-Output 1", "does": "prints one", "undo": "nothing to undo", **kw}


def decision(id_, words, status="in force", **kw):
    day = f"{id_[2:6]}-{id_[6:8]}-{id_[8:10]}"
    return {"id": id_, "date": day, "time_utc": None, "to": "Alder", "subject": f"subject of {id_}", "status": status,
            "words": words, "offer": None, "reading": f"reading of {id_}", "source": "box@abc1234:NOTES.md:7",
            "supersedes": [], "added_by": "Ben", "added": day, **kw}


CORE = """\
environment:
  id: core
  version: 1.0.0
  status: ratified
  ratified_by: pat
entries:
  - id: core.ask-first
    kind: ruling
    statement: Ask before you act on a guess.
    ratified_by: pat
    provenance:
      type: EXPLICIT
      cases: [C-1]
tests:
  - case: C-1
    message: Tidy it up?
    expected: Only tidy.
"""
SEAT = """\
environment:
  id: alder-seat
  version: 1.0.0
  status: ratified
  ratified_by: pat
  inherits: [core@1.0.0]
entries:
  - id: al.short
    kind: distinction
    statement: Keep answers short.
    ratified_by: pat
"""


class World:
    """Everything a person keeps, under tmp_path, and the config that names it."""

    def __init__(self, root: Path):
        self.root, self.base = root, root / "base"
        self.repo("alder", GATED, ALL_FOUR, "Alder <alder@crew.test>\n")
        self.repo("birch", GATED, ALL_FOUR, "# nobody is declared yet\n")              # checks nothing
        self.repo("cedar", GATED, ("pre-commit",), "Cedar <cedar@crew.test>\n")        # open
        touch(self.base / "cedar" / "hooks" / "pre-push", "#!/bin/sh\n")              # stranded: git never looks here
        self.repo("dune", GATED, ALL_FOUR, "Dune <dune@guest.test>\n")
        self.repo("lab", GATED, ALL_FOUR, "Alder <alder@crew.test>\nBirch <birch@crew.test>\n")
        touch(self.base / "alder" / "cv" / "notes" / "MASTER.md", "# Notes for the lab\n")
        touch(self.base / "alder" / "cv" / "notes" / "part.md", "# A part\n")
        people = {"Alder": "crew", "Birch": "crew", "Cedar": "crew", "Dune": "guests"}
        self.seats = touch(root / "seats.json", json.dumps({
            "base": self.base.as_posix(),
            "seats": {n: {"names": [n], "groups": [g], "emails": [f"{n.lower()}@{g[:5]}.test"], "home": n.lower()}
                      for n, g in people.items()},
            "roots": [{"name": "lab", "path": "lab", "kind": "repo"}, {"name": "home", "path": "{home}", "kind": "repo"}]}))
        self.lab = (self.base / "lab").as_posix()
        lines(self.file("Alder"), ask("A-20261001-100000", "2026-10-01T10:00:00+01:00",
                                      why="We agreed this in J-20991001-1, as before."),
              cmd("A-20261001-110000", "2026-10-01T11:00:00+01:00"),
              {"close": "A-20261001-110000", "at": "2026-10-01T12:00:00+01:00", "how": "done by hand"})
        lines(self.file("Birch"), ask("B-20261002-090000", "2026-10-02T09:00:00+01:00",
                                      why=f"It touches {self.lab}/notes, as A-20261001-100000 did."),
              cmd("B-20261002-080000", "2026-10-02T08:00:00+01:00", cwd=self.lab),
              ask("B-20261002-090000-2", "2026-10-02T09:30:00+01:00"),
              {"close": "B-20261002-090000-2", "at": "2026-10-02T10:00:00+01:00", "how": "answered"})
        lines(self.file("Cedar"), ask("C-20261003-070000", "2026-10-03T07:00:00+01:00", why="See J-20991002-3."))
        lines(self.file("Dune"), ask("D-20261004-060000", "2026-10-04T06:00:00+01:00"))
        self.inbox = root / "inbox"
        lines(self.inbox / "runs.jsonl", {"seat": "Birch", "id": "B-20261002-080000", "started": "2026-10-02T08:05:00Z",
                                          "finished": "2026-10-02T08:05:02Z", "exit": 0, "timed_out": False,
                                          "stdout": "1", "stderr": "", "command": "Write-Output 1"})
        lines(self.inbox / "parked.jsonl", {"event": "park", "seat": "Cedar", "id": "C-20261003-070000",
                                            "at": "2026-10-03T08:00:00Z", "by": "the person"})
        self.register = root / "register.jsonl"
        lines(self.register, decision("J-20991001-1", "A-20261001-100000 1."),
              decision("J-20991001-2", "B-20261002-090000-2 2."),
              decision("J-20991001-10", "Nothing yet."),
              decision("J-20991002-3", "Not now.", status="parked"),
              decision("J-20991002-4", "Later, this instead.", supersedes=["J-20991001-10"]))
        self.notes = root / "notes.jsonl"
        lines(self.notes, {"on": "J-20991001-1", "text": "more of the offer", "quote": "the first one",
                           "source": "box@abc1234:NOTES.md:3-4", "added_by": "Ben", "added": "2026-10-14"})
        self.cards = root / "cards"
        touch(self.cards / "core" / "SEMANTICS.yaml", CORE)
        touch(self.cards / "alder-seat" / "SEMANTICS.yaml", SEAT)
        self.map = touch(root / "map.json", json.dumps({
            "measured": "2026-09-24", "places": [{"id": "p1", "sector": "One"}, {"id": "p2", "sector": "One"},
                                                 {"id": "p3", "sector": "Two"}],
            "edges": [{"a": "p1", "b": "p2"}, {"a": "p2", "b": "p3"}],
            "sectors": [{"sector": "One", "title": "The first"}, {"sector": "Two", "title": "The second"}]}))
        self.config = root / "sources.json"
        self.write_config()

    def repo(self, name: str, config: str, hooks, identity: str | None) -> None:
        """A repository as git lays one out (a HEAD naming a branch, objects and refs folders, its settings), with
        the hook files named in its chain folder and, when given, an .identity file."""
        top = self.base / name
        touch(top / ".git" / "config", "[core]\n\trepositoryformatversion = 0\n" + config)
        touch(top / ".git" / "HEAD", "ref: refs/heads/main\n")
        (top / ".git" / "objects").mkdir()
        (top / ".git" / "refs" / "heads").mkdir(parents=True)
        for n in hooks:
            touch(top / "chain" / n, "#!/bin/sh\n")
        if identity is not None:
            touch(top / ".identity", identity)

    def file(self, seat: str) -> Path:
        return self.base / seat.lower() / "requests.jsonl"

    def cfg(self, **change) -> dict:
        out = {"name": "Hollow", "seats": str(self.seats), "inbox": str(self.inbox), "register": str(self.register),
               "notes": str(self.notes), "cards": str(self.cards), "map": str(self.map), "group": "crew"}
        out.update(change)
        return {k: v for k, v in out.items() if v is not None}

    def write_config(self, **change) -> None:
        self.config.write_text(json.dumps(self.cfg(**change)), encoding="utf-8")

    def readers(self) -> dict:
        cfg = self.cfg()
        return {"cards": cards.load(cfg), "record": record.load(cfg), "rules": rules.load(cfg),
                "gates": gates.load(cfg), "places": places.load(cfg)}


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "user"
    user.mkdir()
    # git's own settings on this machine are never read: the gates reader sees a machine with none
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    return w


def place(name: str) -> dict:
    got = view.answer(name)
    assert got is not None, name
    return got


GROUP = {"Alder", "Birch", "Cedar"}


# ---------------------------------------------------------------- each place's numbers are the readers'
def test_each_place_counts_equal_the_readers(world):
    got = world.readers()
    shown = [c for c in got["cards"]["cards"] if c["seat"] in GROUP]
    w = place("waiting")
    assert w["frame"]["waiting"] == sum(c["state"] == "waiting" for c in shown) == 2
    assert w["counts"]["cards"] == len(shown) == 6
    assert {k: v for k, v in w["counts"]["by_state"].items() if v} == {"waiting": 2, "parked": 1, "closed": 2, "run": 1}
    assert sorted(c["key"] for c in w["cards"]) == sorted(f"{c['seat']}/{c['id']}" for c in shown)
    for c in w["cards"]:   # card for card: every field the inbox shows is the reader's own
        mine = next(x for x in shown if x["seat"] == c["seat"] and x["id"] == c["id"])
        assert {k: c[k] for k in ("title", "why", "question", "options", "command", "does", "undo", "cwd", "at",
                                  "state")} == {k: mine[k] for k in ("title", "why", "question", "options", "command",
                                                                     "does", "undo", "cwd", "at", "state")}
    r = place("record")
    assert r["counts"] == got["record"]["counts"] and [e["id"] for e in r["entries"]] == [
        e["id"] for e in got["record"]["entries"]]
    assert r["counts"]["by_status"] == {"in force": 3, "parked": 1, "reopened": 0, "superseded": 1}
    assert place("rules")["counts"] == got["rules"]["counts"]
    p = place("projects")
    repos = [x for x in got["gates"]["repos"] if x["seat"] in (None, *GROUP)]
    assert p["worktrees"] == sum(len(x["worktrees"]) for x in repos) == 4
    assert [x["id"] for x in p["projects"]] == [x["id"] for x in got["places"]["projects"] if
                                                not x["home_of"] or set(x["home_of"]) & GROUP]
    m = place("map")
    assert sorted(m["agents"]) == sorted(a["id"] for a in got["places"]["agents"] if a["name"] in GROUP)
    assert (m["map"]["places"], m["map"]["edges"], m["map"]["measured"]) == (3, 2, "2026-09-24")
    assert len(p["documents"]) == len(got["places"]["documents"]) == 1
    # must-refuse: a card filed now moves the page, which still equals the reader, and a wrong count is told apart
    append(world.file("Cedar"), ask("C-20261005-090000", "2026-10-05T09:00:00+01:00"))
    again = place("waiting")
    assert again["frame"]["waiting"] == 3 != w["frame"]["waiting"]
    assert again["frame"]["waiting"] == sum(c["state"] == "waiting" for c in cards.load(world.cfg())["cards"]
                                            if c["seat"] in GROUP)


def test_every_place_carries_the_same_frame(world):
    frames = [place(n)["frame"] for n in view.ROUTES]
    assert all(f["waiting"] == 2 and f["name"] == "Hollow" and f["word"] == "hollow" for f in frames)
    assert all({k: v for k, v in f.items() if k != "checked"} == {k: v for k, v in frames[0].items() if k != "checked"}
               for f in frames)
    world.write_config(name=None)   # must-refuse: no word for the whole, so no alias and no name
    assert place("waiting")["frame"]["word"] is None and view.answer("hollow") is None


# ---------------------------------------------------------------- problems, from every reader
def test_problems_are_collected_from_every_reader(world):
    assert place("waiting")["frame"]["problems"] == []   # must-refuse arm first: a clean world shows no banner
    append(world.file("Alder"), "{not json")
    append(world.register, "not json either")
    touch(world.cards / "broken" / "SEMANTICS.yaml", "environment: [unclosed\n")
    append(world.base / "cedar" / ".git" / "config", "\tthis is not a setting\n")
    append(world.base / "lab" / ".identity", "not an identity line")
    frame = place("projects")["frame"]
    by_reader = {p["reader"] for p in frame["problems"]}
    assert by_reader == {"waiting", "record", "rules", "gates", "places"}
    assert all({"source", "line", "kind", "text"} <= set(p) for p in frame["problems"])
    got = world.readers()
    assert len(frame["problems"]) == sum(len(got[k]["problems"]) for k in got)
    bad = next(p for p in frame["problems"] if p["reader"] == "waiting")
    assert bad["kind"] == "bad json" and bad["line"] == 4 and Path(bad["source"]) == world.file("Alder")


def test_an_unreadable_sources_file_is_a_problem_not_a_failure(world):
    world.config.write_text("{ not json", encoding="utf-8")
    for name in view.ROUTES:
        got = place(name)
        assert [p["reader"] for p in got["frame"]["problems"]] == ["sources"]
    assert place("waiting")["off"] is True
    assert view.status_line() == view.UNAVAILABLE
    world.write_config()   # must-refuse: the same file, mended, answers again
    assert place("waiting")["frame"]["problems"] == [] and place("waiting")["off"] is False


# ---------------------------------------------------------------- earlier words, joined by the exact id
def test_earlier_words_join_by_the_exact_id(world):
    by = {c["key"]: c for c in place("waiting")["cards"]}
    alder = by["Alder/A-20261001-100000"]["earlier"]
    assert [(e["id"], e["link"]) for e in alder] == [("J-20991001-1", "cites this card")]
    assert alder[0]["words"] == "A-20261001-100000 1." and alder[0]["status"] == "in force"
    # must-refuse: J-20991001-10 is not J-20991001-1, though one id begins with the other
    assert "J-20991001-10" not in [e["id"] for e in alder]
    birch = by["Birch/B-20261002-090000"]["earlier"]
    assert [(e["id"], e["link"]) for e in birch] == [("J-20991001-1",
                                                      "cites A-20261001-100000, which this card cites")]
    # must-refuse: a decision on B-20261002-090000-2 is another card's, and only that card shows it
    assert "J-20991001-2" not in [e["id"] for e in birch]
    assert [e["id"] for e in by["Birch/B-20261002-090000-2"]["earlier"]] == ["J-20991001-2"]
    cedar = by["Cedar/C-20261003-070000"]["earlier"]
    assert [(e["id"], e["status"], e["link"]) for e in cedar] == [("J-20991002-3", "parked", "this card cites it")]
    assert by["Alder/A-20261001-110000"]["earlier"] == []


def test_done_carries_each_runs_output_cut_to_its_cap(world):
    by = {c["key"]: c for c in place("waiting")["cards"]}
    ran = by["Birch/B-20261002-080000"]
    assert ran["state"] == "run" and ran["output"] == {"stdout": "1", "stdout_cut": 0, "stderr": "", "stderr_cut": 0}
    assert by["Alder/A-20261001-100000"]["output"] is None                   # must refuse: no run, no output
    lines(world.inbox / "runs.jsonl", {"seat": "Birch", "id": "B-20261002-080000", "started": "s", "finished": "f",
                                       "exit": 1, "timed_out": False, "stdout": "x" * (view.OUTPUT_CAP + 5),
                                       "stderr": "boom", "command": "c"})
    out = {c["key"]: c for c in place("waiting")["cards"]}["Birch/B-20261002-080000"]["output"]
    assert len(out["stdout"]) == view.OUTPUT_CAP and out["stdout_cut"] == 5 and out["stderr"] == "boom"
    lines(world.inbox / "runs.jsonl", {"seat": "Birch", "id": "B-20261002-080000", "started": "s", "finished": "f",
                                       "exit": 0, "timed_out": False, "stdout": "  \n", "stderr": "", "command": "c"})
    assert {c["key"]: c for c in place("waiting")["cards"]}["Birch/B-20261002-080000"]["output"] is None   # blank


def test_the_record_gives_each_thread_a_stable_address_from_its_exact_subject(world):
    r = place("record")
    keys = [t["key"] for t in r["threads"]]
    assert len(keys) == len(set(keys)) == r["counts"]["threads"] and r["whole_bytes"] == 512
    assert keys == [t["key"] for t in place("record")["threads"]]           # the same file, the same addresses
    t = next(t for t in r["threads"] if "J-20991001-10" in t["entries"])
    assert t["key"] == view.thread_key({"subject": t["subject"]})
    # must-refuse: a subject that differs by one space is another thread with another address, as the tool keeps it
    assert view.thread_key({"subject": t["subject"] + " "}) != t["key"]
    assert view.thread_key({"subject": None, "entries": ["J-1"]}) != view.thread_key({"subject": None, "entries": ["J-2"]})


def test_who_asks_and_who_acts_carry_their_basis(world):
    c = next(x for x in place("waiting")["cards"] if x["id"] == "A-20261001-100000")
    assert (c["asks"], c["acts"]) == ("Alder", "Alder")
    assert c["asks_basis"] and c["acts_basis"] and c["asks_basis"] != c["acts_basis"]


# ---------------------------------------------------------------- what holds, measured when shown
def test_the_holds_line_is_computed_live(world):
    for seat, id_ in (("Alder", "A-20261001-100000"), ("Birch", "B-20261002-090000")):
        append(world.file(seat), {"close": id_, "at": "2026-10-06T10:00:00+01:00", "how": "answered"})
    w = place("waiting")
    assert w["frame"]["waiting"] == 0
    in_force = record.load(world.cfg())["counts"]["by_status"]["in force"]
    text = w["holds"]["text"]
    assert f"Your word holds: {in_force} decisions in force and 1 parked." in text
    assert "No problem in your files" in text
    assert "1 worktree in 1 repo checks nothing" in text and "1 worktree in 1 repo is open" in text
    # must-refuse: a decision given now, and a gate mended, change the line: no number is fixed
    append(world.register, decision("J-20991006-5", "Yes."))
    touch(world.base / "birch" / ".identity", "Birch <birch@crew.test>\n")
    text2 = place("waiting")["holds"]["text"]
    assert f"{in_force + 1} decisions in force" in text2 and f"{in_force} decisions in force" not in text2
    assert "checks nothing" not in text2


# ---------------------------------------------------------------- the group
def test_the_group_leaves_other_agents_out(world):
    w = place("waiting")
    assert "Dune" not in w["seats"] and not any(c["seat"] == "Dune" for c in w["cards"])
    m = place("map")
    assert "Dune" not in [a["name"] for a in m["agents"].values()]
    assert not any(p["name"] == "Dune home" for p in place("projects")["projects"])
    assert w["frame"]["waiting"] == 2
    world.write_config(group=None)   # must-refuse: with no group, every agent is shown
    w2 = place("waiting")
    assert w2["frame"]["waiting"] == 3 and any(c["seat"] == "Dune" for c in w2["cards"])
    assert any(p["name"] == "Dune home" for p in place("projects")["projects"])


# ---------------------------------------------------------------- the map's marks rise
def test_marks_rise_through_the_map(world):
    m = place("map")
    nodes = m["nodes"]
    top = nodes[m["root"]]
    assert top["kind"] == "whole" and top["name"] == "Hollow" and top["waiting"] == 2 and top["broken"] == 2
    (group,) = [nodes[i] for i in top["children"]]
    assert group["name"] == "crew" and (group["waiting"], group["broken"]) == (2, 2)
    env = {nodes[i]["name"]: nodes[i] for i in group["children"]}
    assert set(env) == {"alder", "birch", "cedar"}
    # Alder's card waits, and Birch's card waits in the lab, where Alder works too
    assert (env["alder"]["waiting"], env["alder"]["broken"]) == (2, 0)
    assert (env["birch"]["waiting"], env["birch"]["broken"]) == (1, 1)
    assert env["birch"]["broken_words"] == {"checks nothing": 1}
    # must-refuse: a parked card is not waiting, and a gated home is not broken
    assert (env["cedar"]["waiting"], env["cedar"]["broken"]) == (0, 1) and env["cedar"]["broken_words"] == {"open": 1}
    names = {m["projects"][p]["name"] for p in env["alder"]["projects"]}
    assert names == {"Alder home", "lab"} and m["projects"][env["alder"]["projects"][0]]["name"] == "Alder home"
    a = next(x for x in m["agents"].values() if x["name"] == "Alder")
    assert a["waiting"] == ["Alder/A-20261001-100000"] and a["rules"]["environments"] == ["alder-seat"]
    assert [w["name"] for w in a["works"]] == ["lab", "Alder home"]


def test_the_persons_word_names_the_map(world):
    assert place("hollow")["place"] == "map"
    assert {k: v for k, v in place("hollow").items() if k != "frame"} == {
        k: v for k, v in place("map").items() if k != "frame"}
    assert view.answer("nowhere") is None   # must-refuse: any other name is no place
    world.write_config(name="Record")         # a word that is another place's name never hides it
    assert view.word_of("Record") is None and place("record")["place"] == "record"


# ---------------------------------------------------------------- projects add up
def test_projects_add_up(world):
    p = place("projects")
    rows = {r["name"]: r for r in p["projects"]}
    assert set(rows) == {"lab", "Alder home", "Birch home", "Cedar home"}
    placed = sorted(k for r in p["projects"] for k in r["cards"])
    assert placed == ["Birch/B-20261002-080000", "Birch/B-20261002-090000"] == sorted(rows["lab"]["cards"])
    assert p["assigned"] + p["unassigned"] == p["total"] == 6 and p["assigned"] == 2
    via = {c["id"]: c["project"]["via"] for c in p["cards"].values()}
    assert via == {"B-20261002-080000": "cwd", "B-20261002-090000": "text"}
    assert rows["lab"]["waiting"] == ["Birch/B-20261002-090000"]
    for r in p["projects"]:   # each project's gate state is the worst of its own worktrees
        words = [x for t in r["gates"]["worktrees"] for x in t["words"]]
        assert r["gates"]["worst"] == view.worst(words)
    assert rows["Birch home"]["gates"]["worst"] == "checks nothing"
    assert rows["Cedar home"]["gates"]["worktrees"][0]["words"] == ["open", "stranded"]
    # must-refuse: a gated repository is not called broken, and its worst is its one state
    assert rows["lab"]["gates"]["worst"] == gates.ARMED_WORDS and rows["lab"]["gates"]["broken"] == 0
    assert [d["slug"] for d in p["documents"]] == ["notes"] and rows["Alder home"]["documents"] == [
        p["documents"][0]["id"]]
    assert p["documents"][0]["docs"][0]["title"] == "A part"


def test_rules_are_the_cards_with_how_firmly_each_is_held(world):
    r = place("rules")
    held = {x["id"]: x["held"] for e in r["environments"] for x in e["rules"]}
    assert held == {"al.short": "written", "core.ask-first": "checked"}
    assert r["agents"]["Alder"]["environments"] == ["alder-seat"] and r["agents"]["Birch"]["environments"] == []


# ---------------------------------------------------------------- the status line
def test_the_status_line_says_what_waits_or_what_holds(world):
    assert view.status_line() == "2 waiting · newest: Birch B-20261002-090000 Title B-20261002-090000"
    cut = view.status_line(width=44)
    assert len(cut) <= 44 and cut.endswith("…") and cut.startswith("2 waiting · newest: Birch B-20261002-090000")
    for seat, id_ in (("Alder", "A-20261001-100000"), ("Birch", "B-20261002-090000")):
        append(world.file(seat), {"close": id_, "at": "2026-10-06T10:00:00+01:00", "how": "answered"})
    assert view.status_line() == "nothing waiting · 3 decisions in force"
    world.write_config(seats=None)   # must-refuse: with no seats file there is nothing to say
    assert view.status_line() == view.UNAVAILABLE


@pytest.mark.parametrize("tree, said", [
    pytest.param({"words": ["a hook for each act, identity named"], "verdicts": [{"stranded": ["pre-commit"]}]},
                 "1 worktree in 1 repo is stranded", id="must-refuse: a stranded tree is named"),
    pytest.param({"words": ["a hook for each act, identity named", "a word no reader wrote"]},
                 "every worktree has a hook for each act", id="must-pass: the all-clear is still the worst"),
    pytest.param({"words": ["a word no reader wrote"]}, "1 worktree could not be read",
                 id="must-refuse: a word the line cannot say is counted as unread"),
    pytest.param({"words": ["a hook for each act, identity named"]}, "every worktree has a hook for each act",
                 id="must-pass: all gated"),
])
def test_the_gates_line_never_gives_the_all_clear_over_a_stranded_worktree(tree, said):
    # review of 1.2.2, V1: holds() said only off, checks nothing and open, so a stranded tree read as all gated
    from types import SimpleNamespace
    src = SimpleNamespace(got={"record": {"off": True},
                               "gates": {"repos": [{"root": "/r", "worktrees": [{"path": "/r/a", **tree}]}]}},
                          problems=[])
    text = view.holds(src)["text"]
    assert said in text, text
    if "hook for each act" not in said:
        assert "every worktree has a hook" not in text
