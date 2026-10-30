"""Who is a seat, when the writer is given no list and reads the seats file: a check that needs the seats refuses when
they cannot be known, and is never skipped. Before 1.4's fix, a base the path rule refused emptied the seat list, the
writer took an empty list for "no seats file", and the reviewer, to_seat and assign checks were skipped: any name went
through. Each check has its must-refuse arm here, and its must-pass partners: a seats file whose base is wrong still
names its seats (only the homes are dropped), and with no seats file configured at all there is nothing to check a
seat against, a mode the writer keeps and says."""
import json

import pytest

from work_kit import bound, make, new, person, refused, to_doing


@pytest.fixture
def home(tmp_path, monkeypatch):
    base = tmp_path / "base"
    (base / "alpha").mkdir(parents=True)
    sources = tmp_path / "sources.json"
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    return tmp_path


def seats_file(home, text):
    p = home / "seats.json"
    p.write_text(text, encoding="utf-8")
    (home / "sources.json").write_text(json.dumps({"seats": str(p)}), encoding="utf-8")


TABLE = '{"alpha": {"home": "alpha"}, "beta": {}, "gamma": {}}'
UNKNOWABLE = {
    "not JSON": "{not json",
    "a key twice": '{"base": %s, "seats": %s, "seats": %s}',
    "no table of seats": '{"base": %s}',
}


def writer(home, label):
    base = json.dumps(str(home / "base"))
    text = UNKNOWABLE[label]
    seats_file(home, text % ((base, TABLE, TABLE) if text.count("%s") == 3 else (base,) if "%s" in text else ()))
    return make(home / "work-home", seats=None)


@pytest.mark.parametrize("label", sorted(UNKNOWABLE))
def test_to_seat_is_refused_when_the_seats_cannot_be_known(home, label):   # must refuse
    w = writer(home, label)
    ident = new(w, "alpha")
    e = refused("UNKNOWN_ID", w.write, bound("beta"), "propose_reassign", {"id": ident, "to_seat": "gamma"})
    assert "the seats cannot be known" in e.reason


@pytest.mark.parametrize("label", sorted(UNKNOWABLE))
def test_a_reviewer_is_refused_when_the_seats_cannot_be_known(home, label):   # must refuse
    w = writer(home, label)
    ident = to_doing(w, "alpha")
    e = refused("UNKNOWN_ID", w.write, bound("alpha"), "move",
                {"id": ident, "from": "doing", "to": "review", "reviewer": "beta"})
    assert "the seats cannot be known" in e.reason


@pytest.mark.parametrize("label", sorted(UNKNOWABLE))
def test_an_assignment_is_refused_when_the_seats_cannot_be_known(home, label):   # must refuse
    w = writer(home, label)
    ident = new(w, "alpha")
    e = refused("UNKNOWN_ID", person, w, ident, "assign", value="beta")
    assert "the seats cannot be known" in e.reason


@pytest.mark.parametrize("base", ["teams/../base", "  ", None, "no-such-folder"])
def test_a_wrong_base_drops_the_homes_and_keeps_the_seats_so_every_check_still_runs(home, base):   # must pass
    data = {"seats": json.loads(TABLE)}
    if base is not None:
        data["base"] = str(home / base) if base not in ("  ",) else base
    seats_file(home, json.dumps(data))
    w = make(home / "work-home", seats=None)
    ident = new(w, "alpha")
    assert w.write(bound("beta"), "propose_reassign", {"id": ident, "to_seat": "gamma"})   # a seat: it goes through
    refused("UNKNOWN_ID", w.write, bound("beta"), "propose_reassign", {"id": ident, "to_seat": "zeta"})   # no seat


def test_with_no_seats_file_configured_there_is_nothing_to_check_a_seat_against(home):   # the mode, said
    (home / "sources.json").write_text(json.dumps({}), encoding="utf-8")
    w = make(home / "work-home", seats=None)
    assert w.seats() is None
    ident = new(w, "alpha")
    assert w.write(bound("beta"), "propose_reassign", {"id": ident, "to_seat": "zeta"})


BROKEN_SOURCES = {   # a sources file that configures the seats but not usably: every one refuses, none skips
    "seats is a number": {"seats": 42},
    "seats is null": {"seats": None},
    "seats is a list": {"seats": ["seats.json"]},
    "seats is empty": {"seats": ""},
    "seats is a record": {"seats": {"path": "seats.json"}},
    "Seats, misspelt in case": {"Seats": "seats.json"},
    "seat, misspelt": {"seat": "seats.json"},
    "seets, misspelt": {"seets": "seats.json"},
}


@pytest.mark.parametrize("label", sorted(BROKEN_SOURCES) + ["the sources file is a folder",
                                                            "SEMANTEXT_SOURCES names nothing"])
def test_a_seats_setting_that_cannot_be_used_refuses_every_seat_check(home, label):   # must refuse
    sources = home / "sources.json"
    if label == "the sources file is a folder":
        sources.mkdir()
    elif label != "SEMANTEXT_SOURCES names nothing":
        sources.write_text(json.dumps(BROKEN_SOURCES[label]), encoding="utf-8")
    w = make(home / "work-home", seats=None)
    ident = new(w, "alpha")
    e = refused("UNKNOWN_ID", w.write, bound("beta"), "propose_reassign", {"id": ident, "to_seat": "gamma"})
    assert "the seats cannot be known" in e.reason
    assert w.seats_said().startswith("the seats cannot be known")   # and the mode is said


def test_no_sources_file_at_all_is_the_one_mode_with_no_seat_checks_and_it_is_said(home, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)   # no sources file named, and none where the default is
    w = make(home / "work-home", seats=None)
    assert w.seats() is None and "not checked" in w.seats_said()
    ident = new(w, "alpha")
    assert w.write(bound("beta"), "propose_reassign", {"id": ident, "to_seat": "zeta"})


def test_the_mode_is_said_on_the_work_list(home, monkeypatch, capsys):
    from types import SimpleNamespace
    from semantext.work import cli
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    said = []
    cli.cmd_work(SimpleNamespace(root=home / "work-home"), SimpleNamespace(work_action="list", project=None, all=False,
                                                                          request_key=None), out=said.append)
    assert [s for s in said if s.startswith("Seats:")] == ["Seats: no seats file is configured, so a reviewer, a "
                                                            "to_seat and an assignment are not checked against any "
                                                            "seat."]
    seats_file(home, json.dumps({"base": str(home / "base"), "seats": json.loads(TABLE)}))   # must pass: said nothing
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(home / "sources.json"))
    said.clear()
    cli.cmd_work(SimpleNamespace(root=home / "work-home"), SimpleNamespace(work_action="list", project=None, all=False,
                                                                          request_key=None), out=said.append)
    assert not [s for s in said if s.startswith("Seats:")]


def test_the_seats_file_read_names_its_seats(home):   # must pass: the plain case
    seats_file(home, json.dumps({"base": str(home / "base"), "seats": json.loads(TABLE)}))
    assert make(home / "work-home", seats=None).seats() == {"alpha", "beta", "gamma"}


def test_the_refusal_says_why_the_seats_cannot_be_known(home):
    w = writer(home, "a key twice")
    ident = new(w, "alpha")
    e = refused("UNKNOWN_ID", w.write, bound("beta"), "propose_reassign", {"id": ident, "to_seat": "gamma"})
    assert "the seats cannot be known" in e.reason and "given twice" in e.reason