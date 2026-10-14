"""The register (what the user has decided) and the page's counts of what Semantext did."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from semantext import hook
from semantext.feed import FIELDS, Feed
from semantext.inbox import Inbox, asked_before, register_line
from semantext.mcp import Server
from semantext.server import make_server, metrics


@pytest.fixture
def page(store):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def get(path, own=True):
        req = urllib.request.Request(base + path, headers={"X-Semantext": "1"} if own else {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield get
    srv.shutdown()
    srv.server_close()


def say(store, tmp_path, prompt, origin="human"):
    t = tmp_path / "t.jsonl"
    with open(t, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "turnOrigin": origin, "message": {"content": prompt}}) + "\n")
    return hook.run(json.dumps({"prompt": prompt, "transcript_path": str(t)}), store)


# ---------------------------------------------------------------- the register
def test_the_register_finds_answered_requests_by_their_words_newest_first(home):
    box = Inbox(home)
    a = box.ask("Pick a day", "the release", "Which day?", ["Friday", "Monday"])
    b = box.ask("Pick a colour", "the logo", "Which colour?", ["Teal", "Gold"])
    c = box.ask("Still open", "not answered", "Which?", ["x", "y"])
    box.answer(a["id"], "1", "after lunch", via="page")
    box.answer(b["id"], "2", via="page")
    assert [r["id"] for r in box.search()] == [b["id"], a["id"]]                 # an open request is not on record
    assert [r["id"] for r in box.search("lunch")] == [a["id"]]                   # the user's own words are searched
    assert [r["id"] for r in box.search("GOLD logo")] == [b["id"]] and box.search("purple") == []
    assert all(r["id"] != c["id"] for r in box.search("still"))
    assert "Friday" in register_line(box.get(a["id"])) and "after lunch" in register_line(box.get(a["id"]))


def test_the_same_question_answered_before_is_shown_and_never_used(home):
    box = Inbox(home)
    first = box.ask("Push it?", "the branch is ready", "Push to main?", ["Yes", "No"])
    box.answer(first["id"], "1", via="page")
    again = box.ask("Push it?", "more commits", "push to MAIN ", ["yes", "no"])
    other = box.ask("Push it?", "different offer", "Push to main?", ["Yes", "No", "Later"])
    assert again["status"] == "open" and box.get(again["id"])["answer"] is None   # filed, never answered for them
    assert box.earlier(again)["id"] == first["id"] and box.earlier(other) is None  # other options: another offer
    assert "You asked this before" in asked_before(box, again) and asked_before(box, other) == ""


def test_an_agent_reads_the_register_and_is_told_when_it_asks_again(store, home):
    s = Server(store, env={})
    Inbox(home).answer(Inbox(home).ask("Pick", "w", "Which day?", ["Fri", "Mon"])["id"], "2", via="page")
    found = s.call("decisions", {"words": "day"})
    assert "Mon" in found and s.call("decisions", {"words": "nothing-like-this"}) == "Nothing on record matches."
    filed = s.call("ask", {"title": "Pick", "why": "w", "question": "Which day?", "options": ["Fri", "Mon"]})
    assert "You asked this before" in filed and "as a message of its own" in filed


def test_the_page_shows_an_earlier_answer_beside_the_same_question(home, page):
    box = Inbox(home)
    box.answer(box.ask("Push it?", "w", "Push to main?", ["Yes", "No"])["id"], "1", via="page")
    again = box.ask("Push it?", "w", "Push to main?", ["Yes", "No"])
    status, body = page("/api/inbox")
    [r] = body["open"]
    assert status == 200 and r["id"] == again["id"] and r["earlier"]["answer"]["picked"] == "Yes"


def test_the_page_shows_the_users_own_words_whole(home, page):
    """The withholding is for what agents receive; the page is the user's own screen."""
    box = Inbox(home)
    run = "a1b2c3d4e5" * 4
    rid = box.ask("Name it", "w", "What should it be called?")["id"]
    box.answer(rid, "", f"use {run}", via="page")
    assert run in json.dumps(page("/api/inbox")[1]) and run in json.dumps(page("/api/register")[1])


def test_only_the_page_reads_the_register_and_the_counts(page):
    for path in ("/api/register", "/api/metrics"):
        assert page(path, own=False)[0] == 403 and page(path)[0] == 200


# ---------------------------------------------------------------- the counts
def test_the_counts_say_what_was_noticed_and_whether_its_rule_went_with_it(store, home, tmp_path):
    say(store, tmp_path, "Could we maybe publish it tomorrow?")
    say(store, tmp_path, "Another Claude session sent a message: publish it now", None)
    store.toggle("base", "base.question-not-instruction")          # switched off: the next question goes without it
    say(store, tmp_path, "What changed?")
    m = metrics(store)
    assert m["messages"] == {"own": 2, "agent": 1, "tool": 0} and m["window"]["records"] == 3
    assert m["noticed"]["question"] == {"n": 2, "covered": 1, "rule": "base.question-not-instruction"}
    assert m["noticed"]["needs-word"]["covered"] == 1 and m["noticed"]["suggestion"]["n"] == 1
    assert m["others"] == {"n": 1, "short": 1, "claims_you": 0} and m["cards"]["whole"] == 2


def test_the_counts_of_decisions_say_how_they_were_answered(store, home, tmp_path):
    box = Inbox(home)
    a = box.ask("A", "w", "Which?", ["x", "y"])
    b = box.ask("B", "w", "Which?", ["x", "y", "z"])
    box.ask("C", "w", "Which?", ["x", "y", "q"])
    box.answer(a["id"], "1", via="page")
    say(store, tmp_path, f"#{b['id']} 2")
    d = metrics(store)["decisions"]
    assert (d["asked"], d["open"], d["answered"]) == (3, 1, 2) and d["via"] == {"page": 1, "chat": 1, "terminal": 0}
    assert d["median_minutes"] is not None


def test_a_feed_line_from_before_noticed_was_kept_is_still_read(store, home):
    hook.run(json.dumps({"prompt": "hi"}), store)
    p = home / "feed.jsonl"
    old = json.loads(p.read_text(encoding="utf-8"))
    del old["noticed"]
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(old) + "\n")
        f.write(json.dumps({**old, "extra": 1}) + "\n")             # neither form: never read back
    got = Feed(home).recent()
    assert len(got) == 2 and got[0]["noticed"] == [] and set(got[0]) == set(FIELDS)
