"""`semantext statusline` counts this machine's own inbox, as the page does.

With a setup named (a seats file and an inbox folder) the requests agents filed in the machine's own inbox are not among
the setup's cards; the page shows them apart and its frame counts them. The status line used to read the setup's cards
only, so it said less than the page. Each check has a must-pass arm (the count is the page's) and a must-refuse arm (a
parked, answered or withdrawn request is not counted, an unreadable inbox is said and never taken for empty, and a
home with no setup counts each request once).
"""
from __future__ import annotations

import pytest

from semantext import cli
from semantext.inbox import Inbox
from semantext.sources import own_inbox, view
from tests.test_v2_view import world  # noqa: F401  (the fixture: a setup of four agents, two of them waiting)

BASE = "2 waiting · newest: Birch B-20261002-090000 Title B-20261002-090000"


@pytest.fixture
def machine(tmp_path):
    return tmp_path / "machine"


def file(machine, title, **kw):
    kw.setdefault("question", "Which?")
    kw.setdefault("options", ["a", "b"])
    return Inbox(machine).ask(title, "because", source=kw.pop("source", "ci-bot"), **kw)


def count(line: str) -> int:
    return int(line.split(" waiting")[0])


def test_the_setup_alone_is_unchanged(world, machine):
    assert view.status_line(machine) == BASE            # no machine inbox at all: what it always said


def test_the_machines_own_inbox_is_counted_with_the_setups_cards(world, machine):
    file(machine, "First thing")
    file(machine, "Second thing")
    line = view.status_line(machine)
    assert line.startswith("4 waiting · newest: ci-bot #")
    assert count(line) == 4


def test_the_line_and_the_page_count_the_same_thing(world, machine):
    for n in range(3):
        file(machine, f"Request {n}")
    page = view.answer("waiting", home=machine)["frame"]["waiting"]
    assert page == 5 and count(view.status_line(machine)) == page


def test_a_parked_request_is_not_waiting(world, machine):                          # must-refuse
    file(machine, "Keep"), file(machine, "Set aside")
    Inbox(machine).park(2, True, via="page")
    assert count(view.status_line(machine)) == 3
    assert view.answer("waiting", home=machine)["frame"]["waiting"] == 3
    Inbox(machine).park(2, False, via="page")
    assert count(view.status_line(machine)) == 4


def test_an_answered_or_withdrawn_request_is_not_waiting(world, machine):          # must-refuse
    file(machine, "One"), file(machine, "Two"), file(machine, "Three")
    Inbox(machine).answer(1, "1", via="terminal")
    Inbox(machine).close(2, "no longer needed", by="ci-bot")
    assert count(view.status_line(machine)) == 3


def test_only_the_machines_waiting_request_when_the_setup_has_nothing_waiting(world, machine):
    from tests.test_v2_view import append
    for seat, id_ in (("Alder", "A-20261001-100000"), ("Birch", "B-20261002-090000")):
        append(world.file(seat), {"close": id_, "at": "2026-10-06T10:00:00+01:00", "how": "answered"})
    assert view.status_line(machine) == "nothing waiting · 3 decisions in force"
    file(machine, "Only this one")
    assert view.status_line(machine).startswith("1 waiting · newest: ci-bot #1 Only this one")


def test_a_setup_whose_waiting_is_off_is_still_said_to_be_unavailable(world, machine):   # must-refuse, as before
    world.write_config(seats=None)
    assert view.status_line(machine) == view.UNAVAILABLE
    file(machine, "Waits")
    assert view.status_line(machine) == view.UNAVAILABLE   # limit, stated: the page still draws it; this line does not


def test_an_unreadable_own_inbox_is_said_and_not_counted_as_empty(world, machine, monkeypatch):   # must-refuse
    def broken(home):
        raise OSError("disk")
    monkeypatch.setattr(own_inbox, "load", broken)
    line = view.status_line(machine)
    assert line.startswith("2 waiting · newest: Birch") and line.endswith("own inbox unreadable")
    assert len(line) <= 80 and len(view.status_line(machine, width=40)) <= 40
    assert view.status_line(machine, width=40).endswith("own inbox unreadable")    # the saying is never the part cut


def test_a_long_title_is_cut_but_the_count_is_not(world, machine):
    file(machine, "T" * 110)
    line = view.status_line(machine, width=50)
    assert len(line) <= 50 and line.startswith("3 waiting") and line.endswith("…")


def test_with_no_setup_each_request_counts_once(tmp_path, monkeypatch):            # must-refuse: no double count
    home = tmp_path / "plain"
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    file(home, "Only")
    assert view.status_line(home).startswith("1 waiting · newest: ci-bot #1 Only")
    assert view.answer("waiting", home=home)["frame"]["waiting"] == 1


def test_the_command_prints_the_same_line(world, machine, capsys):
    file(machine, "Through the command")
    capsys.readouterr()
    assert cli.main(["--home", str(machine), "statusline"]) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("3 waiting · newest: ci-bot #1 Through the command")

