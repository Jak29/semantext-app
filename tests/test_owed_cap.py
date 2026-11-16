"""A very long own inbox stays fast and bounded on the page and in the card hook, and nothing that waits is dropped.

The page draws the newest `CARD_CAP` cards of each kind and COUNTS the rest ("more"); the counts, the bar's number and the
status line are of the whole inbox. A field over `FIELD_CAP` characters is drawn cut and the card says which. The hook's
note reads the file once, makes a line only for the few it can show, cuts a very long title, and says how many more.
Each check has its must-pass (a short inbox is drawn whole) and its must-refuse (the cap never hides a count, an older
request comes back when a newer one is answered, a cut command is not offered to copy).
"""
from __future__ import annotations

import json
import time

import pytest

from semantext import hook
from semantext.inbox import NOTE_TITLE, NOTES_BYTES, Inbox, card_notes
from semantext.sources import own_inbox, record, view
from semantext.store import Store
from tests.test_v2_view import world  # noqa: F401  (the fixture: a setup of four agents, two of them waiting)


def fill(home, n, *, parked_every=0, answered_every=0, long=0, source="agent"):
    """n requests written as the inbox writes them (one pass, no lock per line), some parked or answered, as the page and
    the terminal would write those events."""
    home.mkdir(parents=True, exist_ok=True)
    with open(home / "inbox.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i in range(1, n + 1):
            f.write(json.dumps({"type": "request", "id": i, "uid": str(i), "at": "2026-11-01T10:00:00Z", "from": source,
                                "title": f"T{i}" + "x" * long, "why": "w" + "y" * long, "kind": "decision",
                                "question": "Which?" + "q" * long, "options": ["a", "b"], "recommend": None}) + "\n")
            if parked_every and i % parked_every == 0:
                f.write(json.dumps({"type": "park", "id": i, "at": "2026-11-01T11:00:00Z", "parked": True, "via": "page"}) + "\n")
            elif answered_every and i % answered_every == 0:
                f.write(json.dumps({"type": "answer", "id": i, "at": "2026-11-01T12:00:00Z", "choice": "1", "picked": "a",
                                    "words": "", "via": "page"}) + "\n")
    (home / "inbox.seq").write_text(str(n), encoding="utf-8")
    return Inbox(home)


# ---- the cards ----------------------------------------------------------------------------------------------------
def test_the_page_draws_the_newest_of_each_kind_and_counts_the_rest(tmp_path):
    box = fill(tmp_path, 600, parked_every=5, answered_every=7)
    got = own_inbox.load(tmp_path)
    by_state = {s: [c for c in got["cards"] if c["state"] == s] for s in ("waiting", "parked", "closed")}
    true = {s: sum(r["status"] == "open" and (r["parked"] == (s == "parked")) for r in box.requests().values())
            for s in ("waiting", "parked")}
    true["closed"] = sum(r["status"] != "open" for r in box.requests().values())
    assert got["counts"]["by_state"]["waiting"] == true["waiting"] and got["counts"]["by_state"]["parked"] == true["parked"]
    assert got["counts"]["by_state"]["closed"] == true["closed"] and got["counts"]["cards"] == 600
    for s in ("waiting", "parked", "closed"):
        assert len(by_state[s]) == min(own_inbox.CARD_CAP, true[s])
        assert got["more"][s] == true[s] - len(by_state[s])
        assert len(by_state[s]) + got["more"][s] == true[s]                        # nothing is dropped: drawn plus said
    waiting_ids = sorted(c["number"] for c in by_state["waiting"])
    every = sorted(r["id"] for r in box.requests().values() if r["status"] == "open" and not r["parked"])
    assert waiting_ids == every[-own_inbox.CARD_CAP:]                               # the newest are the ones drawn


def test_a_short_inbox_is_drawn_whole(tmp_path):                                    # must-pass
    fill(tmp_path, 12, parked_every=4, answered_every=5)
    got = own_inbox.load(tmp_path)
    assert len(got["cards"]) == 12 and got["more"] == {"waiting": 0, "parked": 0, "closed": 0}


def test_answering_a_newer_card_brings_an_older_one_back(tmp_path):                 # must-refuse: the cap hides nothing for good
    box = fill(tmp_path, own_inbox.CARD_CAP + 5)
    first = own_inbox.load(tmp_path)
    assert first["more"]["waiting"] == 5 and 1 not in {c["number"] for c in first["cards"]}
    box.answer(own_inbox.CARD_CAP + 5, "1", via="page")
    again = own_inbox.load(tmp_path)
    assert again["more"]["waiting"] == 4 and 6 in {c["number"] for c in again["cards"] if c["state"] == "waiting"}


def test_the_cap_is_set_by_the_caller(tmp_path):
    fill(tmp_path, 30)
    got = own_inbox.load(tmp_path, cap=10)
    assert len(got["cards"]) == 10 and got["more"]["waiting"] == 20 and got["cap"] == 10


def test_every_agent_that_filed_is_known_though_its_cards_are_not_drawn(tmp_path):
    box = fill(tmp_path, own_inbox.CARD_CAP + 1, source="old-agent")
    for i in range(own_inbox.CARD_CAP):
        box.ask(f"New {i}", "w", "Which?", ["a", "b"], source="new-agent")
    got = own_inbox.load(tmp_path)
    assert got["asked_by"] == ["new-agent", "old-agent"] and [s["seat"] for s in got["seats"]] == ["new-agent"]


# ---- very long texts ----------------------------------------------------------------------------------------------
def test_a_very_long_text_is_cut_and_the_card_says_which_field(tmp_path):
    fill(tmp_path, 3, long=60_000)
    got = own_inbox.load(tmp_path)
    card = got["cards"][0]
    for field in ("title", "why", "question"):
        assert len(card[field]) < own_inbox.FIELD_CAP + 200 and "more characters are in your inbox file" in card[field]
    assert set(card["cut"]) == {"title", "why", "question"}
    assert len(json.dumps(got)) < 100_000                                           # 3 cards of 180 KB each are not sent whole


def test_a_text_at_the_limit_is_not_cut(tmp_path):                                  # must-pass
    box = Inbox(tmp_path)
    box.ask("t", "w" * 1000, "q" * 1000, ["a", "b"], source="agent")                # the longest the inbox itself files
    card = own_inbox.load(tmp_path)["cards"][0]
    assert card["cut"] == [] and card["why"] == "w" * 1000 and "more characters" not in card["question"]


def test_a_cut_command_still_has_its_warning_and_says_it_is_cut(tmp_path):         # the flags come from the whole command
    tmp_path.mkdir(exist_ok=True)
    command = "echo hi\n" + "# pad\n" * 1000 + "Remove-Item -Recurse -Force C:\\scratch"
    with open(tmp_path / "inbox.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"type": "request", "id": 1, "at": "2026-11-01T10:00:00Z", "from": "agent", "title": "run", "why": "w",
                            "kind": "command", "command": command, "does": "d", "undo": "u", "cwd": ""}) + "\n")
    card = own_inbox.load(tmp_path)["cards"][0]
    assert "command" in card["cut"] and card["flags"] and len(card["command"]) < len(command)
    assert [c["choice"] for c in card["choices"]] == ["done", "won't"]               # it can still be answered


def test_many_options_are_capped_and_the_choices_follow_the_drawn_ones(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with open(tmp_path / "inbox.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"type": "request", "id": 1, "at": "2026-11-01T10:00:00Z", "from": "agent", "title": "pick", "why": "w",
                            "kind": "decision", "question": "Which?", "options": [f"o{i}" for i in range(400)]}) + "\n")
    card = own_inbox.load(tmp_path)["cards"][0]
    assert len(card["options"]) == own_inbox.OPTION_CAP == len(card["choices"]) and "options" in card["cut"]
    assert card["choices"][-1] == {"label": f"o{own_inbox.OPTION_CAP - 1}", "choice": str(own_inbox.OPTION_CAP)}


# ---- the page ---------------------------------------------------------------------------------------------------
def test_the_waiting_place_counts_the_whole_inbox(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    fill(tmp_path, 450, parked_every=9)
    got = view.answer("waiting", home=tmp_path)
    waiting = 450 - 50
    assert got["frame"]["waiting"] == waiting                                       # the bar says what waits, not what is drawn
    assert got["counts"]["by_state"]["waiting"] == waiting and got["counts"]["by_state"]["parked"] == 50
    assert got["counts"]["cards"] == 450
    assert sum(c["state"] == "waiting" for c in got["cards"]) == own_inbox.CARD_CAP
    assert got["more"]["waiting"] == waiting - own_inbox.CARD_CAP and got["cap"] == own_inbox.CARD_CAP


def test_the_page_stays_small_and_quick_on_a_long_inbox(tmp_path, monkeypatch):    # must-refuse: no growth with the inbox
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    fill(tmp_path, 3000, parked_every=4, answered_every=5, long=1500)
    start = time.perf_counter()
    got = view.answer("waiting", home=tmp_path)
    took = time.perf_counter() - start
    assert len(got["cards"]) <= 3 * own_inbox.CARD_CAP
    assert len(json.dumps(got, default=str)) < 2_500_000
    assert took < 10, took                                                          # generous: it is ~1 s on a slow machine


def test_the_machines_own_inbox_beside_a_setup_is_capped_and_counted(world, tmp_path):
    machine = tmp_path / "machine"
    fill(machine, 260)
    got = view.answer("waiting", home=machine)
    drawn = [c for c in got["machine_inbox"] if c["state"] == "waiting"]
    assert len(drawn) == own_inbox.CARD_CAP and got["machine_more"] == {"waiting": 160, "parked": 0}
    assert got["frame"]["waiting"] == 2 + 260                                       # the setup's two, and all of the machine's
    assert view.status_line(machine).startswith("262 waiting")


def test_the_status_line_counts_all_not_the_drawn(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    fill(tmp_path, 400)
    assert view.status_line(tmp_path).startswith("400 waiting · newest: agent #")


def test_the_record_draws_the_newest_answers_and_says_the_rest(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    fill(tmp_path, 700, answered_every=1)
    got = view.answer("record", home=tmp_path)
    ids = [e["id"] for e in got["entries"]]
    assert len(ids) == own_inbox.RECORD_CAP and ids[-1] == "#700" and "#201" in ids and "#200" not in ids
    said = [p for p in got["frame"]["problems"] if p.get("kind") == "more answers"] or \
           [p for p in got.get("problems", []) if p.get("kind") == "more answers"]
    assert said and "700 answers" in said[0]["text"] and "200" in said[0]["text"]
    assert view.status_line(tmp_path) == "nothing waiting · 700 answers kept"       # the line counts them all


def test_a_short_record_says_nothing_about_more(tmp_path, monkeypatch):            # must-pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    fill(tmp_path, 40, answered_every=1)
    entries, _path, problems = own_inbox.decisions(tmp_path)
    assert len(entries) == 40 and problems == []


# ---- the card hook ------------------------------------------------------------------------------------------------
def test_the_hook_note_is_small_and_counts_what_it_leaves(tmp_path):
    box = fill(tmp_path, 4000, parked_every=4, long=800)
    start = time.perf_counter()
    note = card_notes(box, "agent")
    took = time.perf_counter() - start
    assert len(note.encode("utf-8")) <= NOTES_BYTES + 200
    assert "Waiting for the user's answer (3000)" in note and "Set aside by the user (1000)" in note
    assert note.count("more: run `semantext inbox`") == 2
    assert "- 2995 more: run `semantext inbox`" in note and "- 995 more: run `semantext inbox`" in note
    assert took < 5, took


def test_a_very_long_title_does_not_hide_the_lines_after_it(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with open(tmp_path / "inbox.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for i in range(1, 8):
            f.write(json.dumps({"type": "request", "id": i, "at": "2026-11-01T10:00:00Z", "from": "agent",
                                "title": f"Title{i}" + ("z" * 30_000 if i == 1 else ""), "why": "w", "kind": "decision",
                                "question": "Which?", "options": ["a", "b"]}) + "\n")
    note = card_notes(Inbox(tmp_path), "agent")
    lines = [l for l in note.splitlines() if l.startswith("- #")]
    assert [l.split()[1] for l in lines] == ["#1", "#2", "#3", "#4", "#5"] and "- 2 more:" in note
    assert "…" in lines[0] and len(lines[0]) < NOTE_TITLE + 80                      # the first is cut, the others are whole


def test_a_title_the_inbox_files_is_never_cut_in_the_note(tmp_path):               # must-pass: MAX_TITLE is 120
    box = Inbox(tmp_path)
    box.ask("t" * 120, "w", "Which?", ["a", "b"], source="agent")
    assert "t" * 120 + " (asked" in card_notes(box, "agent")


def test_the_hook_runs_on_a_long_inbox_and_stays_inside_its_note(tmp_path, monkeypatch):
    fill(tmp_path, 3000, parked_every=3, long=600)
    monkeypatch.setenv("SEMANTEXT_AGENT", "agent")
    start = time.perf_counter()
    out = hook.run(json.dumps({"prompt": "hello"}), Store.open(tmp_path))
    took = time.perf_counter() - start
    assert "more: run `semantext inbox`" in out and took < 10, took
    assert len(out.encode("utf-8")) < 12_000                                         # the card's own limit, note included


def test_the_note_reads_the_file_once(tmp_path, monkeypatch):
    box = fill(tmp_path, 50, parked_every=3)
    reads = []
    real = Inbox.events

    def counted(self):
        reads.append(1)
        return real(self)
    monkeypatch.setattr(Inbox, "events", counted)
    card_notes(box, "agent")
    assert len(reads) == 1
