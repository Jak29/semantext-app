"""A parked request is shown as parked wherever requests are listed.

The user can set a request aside (park it). It stays open for its asker, and an answer still counts, but it does not wait
for the user's word. Until now the asking agent's note before the card, its start screen, `answers`, the inbox command,
the doctor, the Agents preview, the counts and `/api/inbox` listed it with the waiting ones. Each check has its must-pass
(a request that waits is still listed as waiting) and its must-refuse (a parked one is not).
"""
from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from semantext import cli, hook, mcp, start
from semantext.agents import Agents
from semantext.feed import Feed
from semantext.inbox import Inbox, card_notes, register_line, still_open
from semantext.store import Store


@pytest.fixture
def box(home):
    return Inbox(home)


def two(box):
    """#1 waits; #2 was parked by the user. Both are the asker 'coder''s."""
    box.ask("Waits for you", "w", "Which?", ["x", "y"], source="coder")
    box.ask("Set aside", "w", "Which?", ["x", "y"], source="coder")
    box.park(2, True, via="page")
    return box


# ---- the inbox's own lists ----------------------------------------------------------------------------------------
def test_the_two_lists_split_the_open_requests(box):
    two(box)
    assert [r["id"] for r in box.open_requests()] == [1, 2]            # still open: the asker holds both
    assert [r["id"] for r in box.waiting_requests()] == [1] and [r["id"] for r in box.parked_requests()] == [2]
    box.park(2, False, via="page")                                      # brought back
    assert [r["id"] for r in box.waiting_requests()] == [1, 2] and box.parked_requests() == []


def test_a_park_line_that_is_not_the_users_parks_nothing(box):          # must-refuse
    box.ask("A", "w", "Which?", ["x", "y"], source="coder")
    with (box.path).open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "park", "id": 1, "parked": True, "via": "agent"}) + "\n")
    assert [r["id"] for r in box.waiting_requests()] == [1] and box.parked_requests() == []


def test_the_register_line_says_parked(box):
    two(box)
    reqs = box.requests()
    assert "still waiting for the user's answer" in register_line(reqs[1])
    assert "still waiting" not in register_line(reqs[2]) and "parked" in register_line(reqs[2])


def test_an_answer_to_a_parked_request_still_counts(box):                 # parking changes nothing about answering
    two(box)
    box.answer(2, "1", via="page")
    assert box.parked_requests() == [] and box.requests()[2]["status"] == "answered"


# ---- what the asking agent is told --------------------------------------------------------------------------------
def test_the_note_before_the_card_lists_parked_apart(box):
    two(box)
    note = card_notes(box, "coder")
    waiting, parked = note.split("## Set aside by the user")
    assert "#1 Waits for you" in waiting and "#2" not in waiting.split("Waiting for the user's answer")[1]
    assert "Waiting for the user's answer (1)" in waiting
    assert "(1)" in parked and "#2 Set aside" in parked and "do not ask them again" in parked


def test_a_parked_request_is_not_in_the_waiting_count_of_the_note(box):    # must-refuse
    box.ask("Only this", "w", "Which?", ["x", "y"], source="coder")
    box.park(1, True, via="page")
    note = card_notes(box, "coder")
    assert "Waiting for the user's answer" not in note and "Set aside by the user (1)" in note


def test_a_request_that_waits_is_still_listed_as_waiting(box):             # must-pass
    box.ask("Only this", "w", "Which?", ["x", "y"], source="coder")
    note = card_notes(box, "coder")
    assert "Waiting for the user's answer (1)" in note and "Set aside" not in note


def test_the_note_stays_within_its_room_with_many_of_both(box):
    for i in range(30):
        box.ask(f"Waiting {i} " + "w" * 80, "w", "Which?", ["x", "y"], source="coder")
        box.ask(f"Parked {i} " + "p" * 80, "w", "Which?", ["x", "y"], source="coder")
    for rid in range(2, 61, 2):
        box.park(rid, True, via="page")
    note = card_notes(box, "coder")
    assert len(note.encode("utf-8")) <= 3_000 + 400
    assert note.count("more: run `semantext inbox`") == 2             # both lists say how many are not shown


def test_the_hook_sends_the_split_note(home, monkeypatch):
    store = Store.open(home)
    two(Inbox(home))
    out = hook.run(json.dumps({"prompt": "hello"}), store)
    assert "Set aside" not in out and "Waits for you" not in out      # must-refuse: another asker's requests are not its
    monkeypatch.setenv("SEMANTEXT_AGENT", "coder")
    out = hook.run(json.dumps({"prompt": "hello"}), store)
    assert "## Waiting for the user's answer (1)" in out and "#1 Waits for you" in out
    assert "## Set aside by the user (1)" in out and "#2 Set aside" in out


def test_the_feed_does_not_record_a_parked_request_as_waiting(home, monkeypatch):
    store = Store.open(home)
    monkeypatch.setenv("SEMANTEXT_AGENT", "coder")
    two(Inbox(home))
    hook.run(json.dumps({"prompt": "hello"}), store)
    rec = Feed(home).recent(1)[0]
    assert rec["waiting"] == [1]


def test_still_open_names_waiting_and_parked_apart(box):
    two(box)
    assert still_open(box, "coder") == " Still waiting: #1. Parked by the user (set aside, not answered): #2"
    box.park(2, False, via="page")
    assert still_open(box, "coder") == " Still waiting: #1, #2"
    box.close(1, "done", by="coder")
    box.close(2, "done", by="coder")
    assert still_open(box, "coder") == ""


def test_answers_command_and_tool_say_parked(home, capsys):
    store = Store.open(home)
    two(Inbox(home))
    capsys.readouterr()
    assert cli.main(["--home", str(home), "answers", "--from", "coder"]) == 0
    out = capsys.readouterr().out
    assert "Still waiting: #1." in out and "Parked by the user (set aside, not answered): #2" in out
    said = mcp.Server(store, env={"SEMANTEXT_AGENT": "coder"}).call("answers", {})
    assert "Still waiting: #1." in said and "Parked by the user (set aside, not answered): #2" in said
    assert "waiting: #1, #2" not in out + said


def test_the_start_screen_says_parked(home):
    store = Store.open(home)
    two(Inbox(home))
    who = Agents(home).identify(env={"SEMANTEXT_AGENT": "coder"})
    text, _ = start.screen(store, who)
    assert "#1 still waiting: Waits for you" in text
    assert "#2 parked by the user (set aside, not answered): Set aside" in text and "#2 still waiting" not in text


# ---- the person's own listings ------------------------------------------------------------------------------------
def test_the_inbox_command_marks_a_parked_request(home, capsys):
    two(Inbox(home))
    capsys.readouterr()
    assert cli.main(["--home", str(home), "inbox"]) == 0
    out = capsys.readouterr().out
    assert "#2  Set aside" in out and "[parked: set aside by you, not answered]" in out
    first = out.split("#2  Set aside")[0]
    assert "[parked" not in first                                       # the waiting one is not marked
    assert "1 of these is parked" in out


def test_the_inbox_command_with_only_parked_says_nothing_waits(home, capsys):
    box = Inbox(home)
    box.ask("Only", "w", "Which?", ["x", "y"], source="coder")
    box.park(1, True, via="page")
    capsys.readouterr()
    cli.main(["--home", str(home), "inbox"])
    assert "Nothing is waiting for you now; the requests above are the ones you parked." in capsys.readouterr().out


def test_the_doctor_counts_waiting_and_parked_apart(home, capsys):
    two(Inbox(home))
    capsys.readouterr()
    cli.main(["--home", str(home), "doctor"])
    out = capsys.readouterr().out
    assert "1 waiting for you, 1 parked (set aside by you)" in out


# ---- the page's data ----------------------------------------------------------------------------------------------
@pytest.fixture
def served(home):
    from semantext.server import make_server
    server = make_server(Store.open(home), port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


def get(server, path):
    port = server.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers={"Referer": f"http://127.0.0.1:{port}/"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_api_inbox_lists_parked_apart(home, served):
    two(Inbox(home))
    got = get(served, "/api/inbox")
    assert [r["id"] for r in got["open"]] == [1] and [r["id"] for r in got["parked"]] == [2]
    assert got["parked"][0]["parked"] is True


def test_the_counts_do_not_call_a_parked_request_open(home):
    from semantext.server import metrics
    store = Store.open(home)
    two(Inbox(home))
    d = metrics(store)["decisions"]
    assert (d["asked"], d["open"], d["parked"]) == (2, 1, 1)
