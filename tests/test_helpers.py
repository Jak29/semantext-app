"""Long-lived helpers: an agent runs its own, by metrics, and the user is never asked. Each rule has an arm that must pass and
one that must refuse."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from semantext import cli
from semantext.agents import Identity
from semantext.attacks import Attacks
from semantext.helpers import Helpers, helper_row, report
from semantext.inbox import Inbox
from semantext.mcp import Server
from semantext.start import screen
from semantext.store import Refused


def agent(name, how="bound"):
    return Identity(name, how, None, None, None, key=f"claim:{name}" if how == "claimed" else f"bound:{name}")


A, B, C = agent("alice"), agent("bob"), agent("carol")


@pytest.fixture
def keeper(tmp_path):
    return Helpers(tmp_path)


def closed_job(keeper, name="scout", tokens=100):
    j = keeper.job(A, name, "it will find two")
    keeper.done(A, j["id"], tokens, "found two")
    return j["id"]


@pytest.fixture
def scout(keeper):
    keeper.start(A, "scout", "the hub code it has read", "session-1")
    return keeper


def test_a_helper_must_say_what_kept_context_earns_it_its_place(keeper):   # must refuse
    with pytest.raises(Refused, match="use a fresh agent"):
        keeper.start(A, "scout", "")


def test_only_its_owner_changes_a_helper(scout):   # must refuse
    for act in (lambda: scout.rename(B, "scout", "x"), lambda: scout.retire(B, "scout", "n"), lambda: scout.job(B, "scout", "p")):
        with pytest.raises(Refused, match="only its owner"):
            act()
    assert [r["name"] for r in report(*scout.state())] == ["scout"]


def test_two_agents_can_use_one_name_and_one_agent_cannot_twice(scout):
    scout.start(B, "scout", "its own part")
    assert len(report(*scout.state())) == 2
    with pytest.raises(Refused, match="already have"):
        scout.start(A, "SCOUT", "again")                               # must refuse


def test_a_rename_keeps_its_jobs_and_the_old_name_is_gone(scout):
    closed_job(scout)
    scout.rename(A, "scout", "ranger")
    assert [(r["name"], r["jobs"]) for r in report(*scout.state())] == [("ranger", 1)]
    with pytest.raises(Refused):
        scout.job(A, "scout", "p")


def test_retiring_says_where_the_notes_are_and_frees_the_name(scout):
    with pytest.raises(Refused, match="notes"):
        scout.retire(A, "scout", "")                                   # must refuse
    scout.retire(A, "scout", "notes/scout.md")
    assert report(*scout.state()) == []
    with pytest.raises(Refused):
        scout.job(A, "scout", "p")                                     # must refuse: retired
    scout.start(A, "scout", "a new part")
    assert [r["jobs"] for r in report(*scout.state())] == [0]


def test_a_prediction_comes_before_the_job_and_tokens_after(scout):
    with pytest.raises(Refused, match="prediction"):
        scout.job(A, "scout", "")                                      # must refuse
    j = scout.job(A, "scout", "it will find two")
    for bad in (-1, True, 1.5, "9"):
        with pytest.raises(Refused, match="whole number"):
            scout.done(A, j["id"], bad)
    scout.done(A, j["id"], 100)
    with pytest.raises(Refused, match="already closed"):
        scout.done(A, j["id"], 5)
    with pytest.raises(Refused, match="only whoever"):
        scout.take(B, j["id"], unreviewed="x")


def test_work_is_not_taken_in_unclosed_or_unchecked(scout):   # must refuse
    j = scout.job(A, "scout", "p")
    with pytest.raises(Refused, match="not closed"):
        scout.take(A, j["id"], unreviewed="x")
    scout.done(A, j["id"], 1)
    with pytest.raises(Refused, match="fresh reviewer"):
        scout.take(A, j["id"])


@pytest.mark.parametrize("judge,verdict,ok", [("carol", "survived", True), ("carol", "killed", False), ("carol", "inconclusive", False), ("scout", "survived", False)])
def test_a_check_counts_only_if_it_survived_someone_other_than_the_helper(scout, judge, verdict, ok):
    jid = closed_job(scout)
    attacks = Attacks(scout.path.parent)
    c = attacks.ask(B, "The work is sound", job=jid)
    attacks.verdict(agent(judge), c["id"], verdict, "ran it", "x")
    if ok:
        scout.take(A, jid, c["id"])
        assert scout.state()[1][jid]["taken"]["attack"] == c["id"]
    else:
        with pytest.raises(Refused, match="has not survived"):
            scout.take(A, jid, c["id"])


def test_taking_in_unchecked_says_why_and_stays_on_the_record(scout):
    jid = closed_job(scout)
    scout.take(A, jid, unreviewed="a one-line typo")
    r = report(*scout.state())[0]
    assert r["unreviewed"] == 1 and "1 taken in unchecked" in helper_row(r)
    with pytest.raises(Refused, match="already taken"):
        scout.take(A, jid, unreviewed="again")


def test_a_helper_idle_a_week_is_flagged_and_a_busy_one_is_not(scout):
    assert report(*scout.state())[0]["flags"] == []                    # must refuse a false flag
    assert "idle 8 days" in report(*scout.state(), now=datetime.now().astimezone() + timedelta(days=8.5))[0]["flags"][0]


def test_a_helper_dearer_than_fresh_agents_is_flagged_and_a_cheaper_one_is_not(scout):
    closed_job(scout, tokens=1000)
    assert report(*scout.state())[0]["flags"] == []                    # nothing to compare with yet
    j = scout.job(A, None, "a fresh agent will do it")
    scout.done(A, j["id"], 100)
    assert "dearer than your fresh agents" in report(*scout.state())[0]["flags"][0]
    j = scout.job(A, None, "another")
    scout.done(A, j["id"], 5000)
    assert report(*scout.state())[0]["flags"] == []


def test_another_agents_fresh_jobs_are_not_the_comparison(scout):
    closed_job(scout, tokens=1000)
    j = scout.job(B, None, "cheap")
    scout.done(B, j["id"], 1)
    assert report(*scout.state(), owner=A.key)[0]["flags"] == []


def test_a_hand_added_line_from_someone_else_changes_nothing(scout):
    import json
    with open(scout.path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "retire", "id": 99, "key": B.key, "name": "scout", "notes": "x"}) + "\n")
    assert [r["name"] for r in report(*scout.state())] == ["scout"]


def test_nothing_reaches_the_users_inbox(store):
    Helpers(store.root).start(A, "scout", "kept")
    assert Inbox(store.root).requests() == {}


@pytest.mark.parametrize("bad", ["\x1b[2Jx", "a\u202eb", "sk-abcdefghijklmnopqrstuvwx"])
def test_keys_and_hidden_characters_are_refused(keeper, bad):   # must refuse
    with pytest.raises(Refused):
        keeper.start(A, "scout", bad)


def test_the_screen_shows_your_helpers_only(store):
    keeper = Helpers(store.root)
    keeper.start(A, "scout", "kept", "session-1")
    keeper.start(B, "bobs", "kept")
    keeper.job(A, "scout", "p")
    text = screen(store, A)[0]
    assert "scout: 1 job" in text and "resume: session-1" in text and "is not closed" in text and "bobs" not in text


def test_a_helpers_file_that_cannot_be_read_says_so(store):
    (store.root / "helpers.jsonl").mkdir()
    text, complete = screen(store, A)
    assert not complete and "NOT READ" in text and "YOUR HELPERS" in text.split("READ INCOMPLETE")[1]


def test_the_ways_in_work(store, capsys):
    home = ["--home", str(store.root)]
    run = lambda *a: cli.main(home + list(a) + ["--from", "alice"])   # noqa: E731
    assert run("helper", "start", "scout", "--keeps", "the hub") == 0
    assert run("helper", "job", "scout", "--predict", "two") == 0
    assert run("helper", "done", "2", "--tokens", "10") == 0
    assert run("helper", "take", "2", "--unreviewed", "typo") == 0
    assert run("helper", "list") == 0 and "1 taken in unchecked" in capsys.readouterr().out
    assert run("helper", "done", "x", "--tokens", "1") != 0
    s = Server(store, env={"SEMANTEXT_AGENT": "carol"}, cwd=str(store.root))
    assert s.call("helper_start", {"name": "m", "keeps": "k"}).startswith("Kept")
    jid = int(s.call("helper_job", {"name": "m", "predict": "p"}).split("#")[1].rstrip("."))
    with pytest.raises(Refused):
        s.call("helper_done", {"job": True, "tokens": 1})              # must refuse: true is an int to Python
    s.call("helper_done", {"job": jid, "tokens": 1})
    assert "m:" in s.call("helper_list", {})


# ---------------------------------------------------------------- what the attack found
def checked(keeper, jid, judge="carol"):
    attacks = Attacks(keeper.path.parent)
    c = attacks.ask(B, "It is sound", job=jid)
    attacks.verdict(agent(judge), c["id"], "survived", "ran it", "x")
    return c["id"]


@pytest.mark.parametrize("tokens", [10 ** 13 + 1, 10 ** 400])
def test_a_huge_token_count_is_refused(scout, tokens):   # must refuse: it would break every report for good
    j = scout.job(A, "scout", "p")
    with pytest.raises(Refused, match="whole number"):
        scout.done(A, j["id"], tokens)


def test_a_huge_token_count_put_in_by_hand_breaks_nothing(store):
    import json
    keeper = Helpers(store.root)
    keeper.start(A, "scout", "k")
    j = keeper.job(A, "scout", "p")
    with open(keeper.path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "done", "id": 9, "key": A.key, "job": j["id"], "tokens": 10 ** 400}) + "\n")
    assert keeper.report()[0]["closed"] == 0 and screen(store, A)[1]


def test_a_claim_that_is_not_about_this_job_clears_nothing(scout):   # must refuse
    jid, other = closed_job(scout), closed_job(scout)
    attacks = Attacks(scout.path.parent)
    unrelated = attacks.ask(B, "The sky is blue")
    attacks.verdict(C, unrelated["id"], "survived", "looked up", "x")
    with pytest.raises(Refused, match="does not check job"):
        scout.take(A, jid, unrelated["id"])
    with pytest.raises(Refused, match="does not check job"):
        scout.take(A, other, checked(scout, jid))


def test_a_rename_does_not_make_the_helper_someone_else(scout):   # must refuse
    jid = closed_job(scout)
    scout.rename(A, "scout", "ranger")
    for judge in ("scout", "ranger"):
        with pytest.raises(Refused, match="has not survived"):
            scout.take(A, jid, checked(scout, jid, judge))


def test_a_rename_after_the_job_still_counts_its_new_name(scout):   # must refuse
    jid = closed_job(scout)
    scout.rename(A, "scout", "ranger")
    assert "ranger" in scout.state()[1][jid]["names"]
    new = scout.job(A, "ranger", "p")["id"]
    scout.done(A, new, 1)
    with pytest.raises(Refused, match="has not survived"):
        scout.take(A, new, checked(scout, new, "scout"))


def test_the_owner_under_another_name_with_the_same_key_cannot_clear_it(scout):   # the by-key arm alone
    jid = closed_job(scout)
    attacks = Attacks(scout.path.parent)
    c = attacks.ask(B, "It is sound", job=jid)
    attacks.verdict(Identity("someone", "bound", None, None, None, key=A.key), c["id"], "survived", "ran it", "x")
    with pytest.raises(Refused, match="has not survived"):
        scout.take(A, jid, c["id"])


def test_a_claim_killed_after_the_work_was_taken_in_is_flagged(scout):
    jid = closed_job(scout)
    cid = checked(scout, jid)
    scout.take(A, jid, cid)
    assert scout.report()[0]["flags"] == []                            # must refuse a false flag
    Attacks(scout.path.parent).verdict(agent("dan"), cid, "killed", "it broke")
    assert "since been killed" in scout.report()[0]["flags"][0]


@pytest.mark.parametrize("name", ["(fresh agent)", "(FRESH AGENT)"])
def test_the_fresh_agents_name_is_kept(scout, name):   # must refuse
    with pytest.raises(Refused, match="kept for fresh"):
        scout.start(A, name, "k")
    with pytest.raises(Refused, match="kept for fresh"):
        scout.rename(A, "scout", name)


def test_a_rename_can_change_only_the_case_and_never_lands_on_a_live_helper(scout):
    scout.rename(A, "scout", "Scout")
    assert [r["name"] for r in scout.report()] == ["Scout"]
    scout.start(A, "other", "k")
    with pytest.raises(Refused, match="already have"):
        scout.rename(A, "Scout", "OTHER")                              # must refuse


@pytest.mark.parametrize("act", [lambda k, s: k.start(A, "n", "keeps", s), lambda k, s: k.job(A, None, s), lambda k, s: k.retire(A, "scout", s), lambda k, s: k.rename(A, "scout", s),
                                 lambda k, s: k.done(A, k.job(A, None, "p")["id"], 1, s), lambda k, s: k.take(A, closed_job(k), unreviewed=s)])
def test_a_key_is_refused_in_every_field(scout, act):   # must refuse
    with pytest.raises(Refused, match="never put one"):
        act(scout, "sk-abcdefghijklmnopqrstuvwx")


@pytest.mark.parametrize("days,flagged", [(6.9, False), (7.1, True)])
def test_the_idle_flag_fires_at_a_week_and_not_before(scout, days, flagged):
    assert bool(report(*scout.state(), now=datetime.now().astimezone() + timedelta(days=days))[0]["flags"]) is flagged


def test_a_line_from_another_agent_cannot_take_in_or_close_a_job(scout):
    import json
    j = scout.job(A, "scout", "p")
    with open(scout.path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "done", "id": 90, "key": B.key, "job": j["id"], "tokens": 1}) + "\n")
    assert scout.state()[1][j["id"]]["tokens"] is None
    scout.done(A, j["id"], 1)
    with open(scout.path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "take", "id": 91, "key": B.key, "job": j["id"]}) + "\n")
    assert scout.state()[1][j["id"]]["taken"] is None


def test_another_agents_session_stays_its_own_in_the_full_list(store, capsys):
    Helpers(store.root).start(B, "bobs", "k", "secret-session")
    assert cli.main(["--home", str(store.root), "helper", "list", "--all", "--from", "alice"]) == 0
    out = capsys.readouterr().out
    assert "bobs" in out and "secret-session" not in out


@pytest.mark.parametrize("line", ['{"type":"start","id":5,"key":"k","name":"a\\nFAKE LINE","keeps":["x"],"from":{"a":1}}', '{"type":"start","id":5,"key":"k","name":7}',
                                  '{"type":"job","id":6,"key":"k","name":"x"}', '{"type":"done","id":6,"key":"k","job":true,"tokens":"x"}', '{"type":"start","id":5,"key":"k","name":"z","at":"nope"}'])
def test_a_line_edited_by_hand_never_takes_down_a_report(store, line):
    keeper = Helpers(store.root)
    with open(keeper.path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    rows = keeper.report()
    assert all("\n" not in helper_row(r).split("\n    ")[0] for r in rows) and screen(store, A)[1]
