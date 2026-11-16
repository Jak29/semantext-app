"""A hand-made huge list of projects is capped the way the own inbox is (tests/test_owed_cap.py).

`<home>/work/projects.json` is a list of names anyone can edit by hand. With no setup the Projects page and the Map drew
every name in it. Now the newest PROJECT_CAP distinct names are drawn, in the list's order, and the rest are counted and
said (a problem line, a number in the Projects place, and a plain "N more" line on the page). Must-pass: a short list is
drawn whole, a name just added is drawn, and the work store still knows every name. Must-refuse: nothing is dropped
without a word, and the cap does not shrink what the work store accepts.
"""
from __future__ import annotations

import json

import pytest

from semantext.sources import own_places, view
from semantext.work.writer import Writer
from v2_node import NODE, run


def write_list(home, names):
    (home / "work").mkdir(parents=True, exist_ok=True)
    (home / "work" / "projects.json").write_text(json.dumps(names), encoding="utf-8")


def drawn(home):
    problems: list = []
    got = own_places.load(home, "Mine", None, problems)
    return [p["name"] for p in got["projects"]], got, problems


def test_a_huge_list_draws_the_newest_and_counts_the_rest(tmp_path):
    write_list(tmp_path, [f"p{i}" for i in range(1, 1001)])
    names, got, problems = drawn(tmp_path)
    assert len(names) == own_places.PROJECT_CAP == 200
    assert names == [f"p{i}" for i in range(801, 1001)]                    # the newest, in the list's order
    assert got["projects_more"] == 800
    said = [p for p in problems if p["kind"] == "more projects"]
    # Under the first-mention rule the drawn names are the LAST 200 of the list, not the newest by date: say so (O6).
    assert len(said) == 1 and "800 more names" in said[0]["text"] and "the last 200 in your list" in said[0]["text"]
    assert "newest" not in said[0]["text"]


def test_nothing_is_dropped_without_a_word(tmp_path):                       # must-refuse
    for total in (200, 201, 450):
        write_list(tmp_path, [f"n{i}" for i in range(total)])
        names, got, problems = drawn(tmp_path)
        assert len(names) + got["projects_more"] == total
        assert bool([p for p in problems if p["kind"] == "more projects"]) == (total > 200)


def test_a_short_list_is_drawn_whole_and_says_nothing(tmp_path):            # must-pass
    write_list(tmp_path, ["alpha", "beta", "gamma"])
    names, got, problems = drawn(tmp_path)
    assert names == ["alpha", "beta", "gamma"] and got["projects_more"] == 0 and problems == []


def test_a_name_just_added_is_drawn_though_the_list_is_huge(tmp_path):
    write_list(tmp_path, [f"p{i}" for i in range(1, 501)])
    Writer(tmp_path).add_project("brand-new")
    names, got, _ = drawn(tmp_path)
    assert names[-1] == "brand-new" and got["projects_more"] == 301


def test_the_work_store_still_knows_every_name(tmp_path):                    # must-refuse: the cap is the drawing's, not the check's
    write_list(tmp_path, [f"p{i}" for i in range(1, 1001)])
    known = Writer(tmp_path).projects()
    assert "p1" in known and "p1000" in known and len(known) >= 1000


def test_the_same_name_in_two_cases_is_one_project(tmp_path):
    write_list(tmp_path, ["Alpha", "beta", "alpha", "BETA", "gamma"])
    names, got, problems = drawn(tmp_path)
    assert sorted(n.casefold() for n in names) == ["alpha", "beta", "gamma"] and got["projects_more"] == 0 and problems == []


def test_a_list_that_is_not_a_list_of_names_is_as_before(tmp_path):
    write_list(tmp_path, {"not": "a list"})
    assert drawn(tmp_path)[0] == []
    write_list(tmp_path, [1, None, "", "  ", "real"])
    assert drawn(tmp_path)[0] == ["real"]


def test_an_unreadable_list_is_said_and_not_capped(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "projects.json").write_text("{not json", encoding="utf-8")
    names, got, problems = drawn(tmp_path)
    assert names == [] and got["projects_more"] == 0 and problems[0]["kind"] == "unreadable"


def test_the_projects_place_carries_the_number_and_the_problem(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    write_list(tmp_path, [f"p{i}" for i in range(1, 401)])
    got = view.answer("projects", home=tmp_path)
    assert got["more"] == 200 and len(got["projects"]) == 200
    assert any(p.get("kind") == "more projects" for p in got["frame"]["problems"])


def test_the_place_for_a_short_list_has_no_more(tmp_path, monkeypatch):            # must-pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    write_list(tmp_path, ["a", "b"])
    got = view.answer("projects", home=tmp_path)
    assert got["more"] == 0 and len(got["projects"]) == 2


@pytest.mark.skipif(NODE is None, reason="node is not installed")
@pytest.mark.parametrize("more, said", [(7, True), (0, False)])
def test_the_page_says_how_many_more_names_there_are(more, said):
    got = run("""
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
S.data.projects = { off: false, own: true, projects: [{ id: "p1", name: "alpha", path: "", agents: [], gates: { found: false, worktrees: [] },
  waiting: [], cards: [], documents: [] }], more: %d, total: 0, assigned: 0, worktrees: 0, cards: {}, documents: [] };
location.hash = "#projects";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  report({ text: place.textContent, more: place.all((e) => (e.getAttribute("data-more") || "") !== "").map((e) => e.textContent) });
});
""" % more)
    assert "alpha" in got["text"] and "null" not in got["text"].replace("nobody", "")      # nothing stray where the line is not
    if said:
        assert got["more"] == ["7 more project names in your list of projects not drawn here: the last 200 in your list are "
                               "shown. All of them are in your projects.json."]
    else:
        assert got["more"] == []
