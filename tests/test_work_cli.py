"""`semantext work`: a write from the command line is claimed, so it holds no rights, and `show` says so."""
import json
from datetime import datetime, timezone

import pytest

from semantext import cli
from semantext.work.writer import Writer, cli_actor
from work_kit import Clock, bound, make, person


@pytest.fixture
def work_home(home):
    (home / "work").mkdir(parents=True)
    (home / "work" / "projects.json").write_text(json.dumps(["Semantext", "Atlas"]), encoding="utf-8")
    return home


def run(capsys, *argv):
    rc = cli.main(["work", *argv])
    got = capsys.readouterr()
    return rc, got.out, got.err


def test_new_files_an_item_with_no_owner_and_show_says_it_is_claimed(work_home, capsys):
    rc, out, _ = run(capsys, "new", "--project", "semantext", "--title", "Board", "--link", "commit:abc1234")
    assert rc == 0 and "W-semantext-1: created recorded" in out and "owner nobody" in out
    rc, out, _ = run(capsys, "show", "W-semantext-1")
    assert rc == 0 and "(claimed)" in out and "owner nobody" in out
    assert "link commit:abc1234" in out and "never proof by itself" in out


def test_a_move_from_the_command_line_is_a_proposal_never_applied(work_home, capsys):
    w = Writer(work_home)
    run(capsys, "new", "--project", "semantext", "--title", "Board")
    from semantext.agents import Agents
    name = cli_actor(Agents(work_home).identify().name).who
    w.write(bound(name), "assign_self", {"id": "W-semantext-1"})      # a seat of the same name takes it, bound
    rc, out, _ = run(capsys, "move", "W-semantext-1", "backlog", "next")
    assert rc == 1                                                     # ranking is the person's: refused outright
    rc, out, err = run(capsys, "comment", "W-semantext-1", "looks", "good")
    assert rc == 0 and "recorded" in out
    w2 = Writer(work_home)
    st = w2.state()
    assert st["items"]["W-semantext-1"]["state"] == "backlog"
    rc, out, _ = run(capsys, "show", "W-semantext-1")
    assert "comment by" in out and "(claimed)" in out


def test_a_claimed_move_the_table_would_allow_a_bound_owner_is_recorded_as_a_proposal(work_home, capsys, monkeypatch):
    from semantext.agents import Agents
    from semantext.work import span
    from work_kit import transcripts
    # the command line's writer reads the person's acts again in the default transcript roots: here, the kit's
    monkeypatch.setattr(span, "transcript_roots", lambda cfg=None: [transcripts(work_home)])
    name = cli_actor(Agents(work_home).identify().name).who
    w = make(work_home, projects=None, seats=None, clock=Clock(datetime.now(timezone.utc).replace(microsecond=0)))
    ident = w.write(bound(name), "create", {"project": "semantext", "title": "Mine"})["id"]
    person(w, ident, "next", frm="backlog")
    rc, out, _ = run(capsys, "move", ident, "next", "doing")
    assert rc == 0 and "PROPOSAL, not applied" in out
    rc, out, _ = run(capsys, "show", ident)
    assert "PROPOSAL, not applied" in out and "holds no rights" in out and "state next" in out


def test_list_shows_open_items_and_problems(work_home, capsys):
    run(capsys, "new", "--project", "semantext", "--title", "One")
    rc, _, err = run(capsys, "new", "--project", "atlas", "--title", "Two\u202e")
    assert rc == 1 and "bidirectional" in err
    rc, out, _ = run(capsys, "list")
    assert "W-semantext-1" in out and "W-atlas-1" not in out
    rc, out, _ = run(capsys, "list", "--project", "atlas")
    assert "No work items" in out or "No open" in out


def test_refusals_are_one_line_with_their_code(work_home, capsys):
    rc, _, err = run(capsys, "new", "--project", "nowhere", "--title", "x")
    assert rc == 1 and "UNKNOWN_ID" in err and "Traceback" not in err
    rc, _, err = run(capsys, "show", "W-semantext-07")
    assert rc == 1
    rc, _, err = run(capsys, "link", "W-semantext-1", "C:/Users/x")
    assert rc == 1 and ("MALFORMED" in err or "UNKNOWN_ID" in err)


def test_the_cli_actor_is_always_claimed_and_never_the_person():
    assert cli_actor("alpha").assurance == "claimed" and cli_actor("person").who != "person"
    assert cli_actor("../x").who.startswith(("x", "cli"))


# A8 and A11 (the attack): no flag names an actor, a time or a file
@pytest.mark.parametrize("flag", ["--as", "--by", "--time", "--who", "--file"])
def test_a8_the_command_line_has_no_flag_that_names_an_actor_a_time_or_a_file(home, flag, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["work", "new", "--project", "semantext", "--title", "x", flag, "person"])
    assert e.value.code == 2 and "unrecognized arguments" in capsys.readouterr().err


# ---- review round 3 (G6): show says when the store is not whole; an empty request key is refused, never dropped -----
def test_show_says_when_the_store_does_not_match_its_head(work_home, capsys):
    run(capsys, "new", "--project", "semantext", "--title", "One")
    run(capsys, "comment", "W-semantext-1", "first")
    rc, out, _ = run(capsys, "show", "W-semantext-1")
    assert "not whole" not in out                                       # must pass: a whole store says nothing
    log = work_home / "work" / "events.jsonl"
    log.write_text(log.read_text(encoding="utf-8").splitlines(keepends=True)[0], encoding="utf-8")   # cut after
    rc, out, _ = run(capsys, "show", "W-semantext-1")
    assert "not whole" in out and "problem:" in out


def test_an_empty_request_key_is_refused_never_dropped(work_home, capsys):
    rc, _, err = run(capsys, "new", "--project", "semantext", "--title", "One", "--request-key", "")
    assert rc == 1 and "request_key" in err
    assert not (work_home / "work" / "events.jsonl").exists() or \
        (work_home / "work" / "events.jsonl").read_text(encoding="utf-8") == ""
    rc, out, _ = run(capsys, "new", "--project", "semantext", "--title", "One", "--request-key", "k1")
    assert rc == 0 and "created recorded" in out                         # must pass