"""Work: the person's own changes from the page (PAGE-ACTS r2, 1.5.15).

Jak's "yes go ahead" to acting from the page (create, edit, move including drag, park, rank). A new kind of the person's
evidence, the page's, as strong as the page's answer to a card and no stronger, applied only on the chain. Koinos's
attack of r1 (M1 a version on every change, M2 an allowlist of fields, M3 a positive sign the page sent it) is held
here. The must-refuse arms come first.
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from semantext import cli, paths
from semantext.work import span
from semantext.work.events import PERSON, WorkRefused
from semantext.work.fold import fold
from semantext.work.writer import Actor, Writer

PAGE = {"kind": "page", "route": "/api/work"}


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    assert cli.main(["--home", str(h), "init"]) == 0
    (h / "work").mkdir(parents=True, exist_ok=True)
    (h / "work" / "projects.json").write_text(json.dumps(["demo"]), encoding="utf-8")
    return h


@pytest.fixture
def server(home):
    from semantext.server import make_server
    from semantext.store import Store
    s = make_server(Store.open(home), port=0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def call(server, body, *, origin=True, referer="/v2", extra=None, path="/api/work", raw=None):
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"X-Semantext": "1", "Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin if isinstance(origin, str) else f"http://{host}"
    if referer is not None:
        headers["Referer"] = referer if referer.startswith("http") else f"http://{host}{referer}"
    headers.update(extra or {})
    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://{host}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


KEYS = iter(f"k{n}" for n in range(1, 100000))


def change(server, action, request, version=None, confirm=None, **kw):
    body = {"action": action, "request": {**request, "request_key": next(KEYS)}}
    if version is not None:
        body["version"] = version
    if confirm is not None:
        body["confirm"] = confirm
    return call(server, body, **kw)


def item(home, ident):
    return Writer(home).state()["items"][ident]


def new(server, home, title="First"):
    code, got = change(server, "create", {"project": "demo", "title": title})
    assert code == 200, got
    return got["id"]


# ---------------------------------------------------------------- must pass: the person's own changes
def test_the_person_files_moves_edits_ranks_parks_and_ends_an_item_from_the_page(server, home):
    iid = new(server, home)
    i = item(home, iid)
    assert (i["state"], i["owner"], i["creator"]) == ("backlog", None, PERSON)
    for to in ("next", "doing", "review"):
        i = item(home, iid)
        assert change(server, "act", {"id": iid, "act": to, "from": i["state"]}, i["events"][-1])[0] == 200
    i = item(home, iid)
    assert change(server, "edit", {"id": iid, "title": "Renamed", "kind": "bug"}, i["events"][-1])[0] == 200
    i = item(home, iid)
    assert change(server, "act", {"id": iid, "act": "priority", "value": 2}, i["events"][-1])[0] == 200
    i = item(home, iid)
    assert change(server, "act", {"id": iid, "act": "park"}, i["events"][-1])[0] == 200
    i = item(home, iid)
    assert i["state"] == "parked"
    assert change(server, "act", {"id": iid, "act": "unpark"}, i["events"][-1])[0] == 200
    i = item(home, iid)
    assert change(server, "act", {"id": iid, "act": "done", "from": "review"}, i["events"][-1], confirm=iid)[0] == 200
    i = item(home, iid)
    assert (i["state"], i["done_by"], i["title"], i["kind"], i["priority"]) == ("done", "word", "Renamed", "bug", 2)
    events = [e for e in Writer(home).state()["events"] if e["id"] == iid]
    assert all(e["applied"] and e["check"] == span.PAGE for e in events)
    assert {e["who"] for e in events} == {PERSON}


def test_the_page_shows_each_item_with_the_version_a_change_names(server, home):
    iid = new(server, home)
    from semantext.sources import view
    got = view.answer("work", home=home)
    shown = next(i for i in got["items"] if i["id"] == iid)
    assert shown["version"] == item(home, iid)["events"][-1]


# ---------------------------------------------------------------- must refuse: where it came from (M3 and do_POST)
@pytest.mark.parametrize("kw", [
    {"origin": False},
    {"origin": "http://evil.example"},
    {"origin": "http://localhost:1"},
    {"referer": None},                                   # a no-referrer fetch hides where it runs
    {"referer": "http://evil.example/v2"},
    {"referer": "/v2/plugin/x/page.html"},
    {"referer": "/v2/workact.js"},
    {"referer": "/v2?x=1"},
    {"extra": {"Sec-Fetch-Site": "cross-site"}},
    {"extra": {"Sec-Fetch-Site": "same-site"}},
    {"extra": {"Sec-Fetch-Dest": "iframe"}},
    {"extra": {"Sec-Fetch-Mode": "navigate"}},
    {"extra": {"X-Semantext": "0"}},
])
def test_a_change_not_sent_by_the_page_itself_is_refused_and_writes_nothing(server, home, kw):   # must refuse
    code, _ = change(server, "create", {"project": "demo", "title": "planted"}, **kw)
    assert code == 403
    assert Writer(home).state()["items"] == {}


@pytest.mark.parametrize("referer", ["/", "/v2", "/index.html"])
def test_each_address_the_page_is_served_at_may_send_a_change(server, home, referer):   # must pass
    assert change(server, "create", {"project": "demo", "title": "x"}, referer=referer)[0] == 200


# ---------------------------------------------------------------- must refuse: what it carries (M2)
@pytest.mark.parametrize("field", ["who", "at", "assurance", "channel", "evidence", "session", "seq", "hash", "owner",
                                   "state", "source", "colour", "claimed_x", "reviewer", "to_seat", "clauses", "links"])
def test_a_field_the_page_does_not_send_is_refused(server, home, field):   # must refuse
    code, got = change(server, "create", {"project": "demo", "title": "x", field: "person"})
    assert code == 400, got
    assert Writer(home).state()["items"] == {}


@pytest.mark.parametrize("body", [
    {"action": "create"},
    {"action": "delete", "request": {"id": "W-demo-1"}},
    {"action": "create", "request": {"project": "demo", "title": "x"}},              # no request_key
    {"action": "create", "request": {"project": "demo", "title": "x", "request_key": ""}},
    {"action": "create", "request": {"project": "demo", "title": "x", "request_key": "a"}, "who": "person"},
    {"action": "create", "request": {"project": "demo", "title": "x", "request_key": "b"}, "version": 1},
    {"action": "create", "request": [1, 2]},
])
def test_a_body_of_another_shape_is_refused(server, home, body):   # must refuse
    assert call(server, body)[0] == 400
    assert Writer(home).state()["items"] == {}


def test_assign_and_clauses_are_not_page_acts(server, home):   # must refuse: they stay typed lines
    iid = new(server, home)
    v = item(home, iid)["events"][-1]
    assert change(server, "act", {"id": iid, "act": "assign", "value": "koinos"}, v)[0] == 400
    assert change(server, "act", {"id": iid, "act": "clauses"}, v)[0] == 400


def test_done_and_void_are_confirmed_by_naming_the_item(server, home):   # must refuse without, pass with
    iid = new(server, home)
    v = item(home, iid)["events"][-1]
    assert change(server, "act", {"id": iid, "act": "void"}, v)[0] == 400
    assert change(server, "act", {"id": iid, "act": "void"}, v, confirm="W-demo-99")[0] == 400
    assert change(server, "act", {"id": iid, "act": "park"}, v, confirm=iid)[0] == 400   # only done and void
    assert item(home, iid)["voided"] is None and item(home, iid)["state"] == "backlog"
    assert change(server, "act", {"id": iid, "act": "void"}, v, confirm=iid)[0] == 200
    assert item(home, iid)["voided"]["by"] == PERSON


# ---------------------------------------------------------------- must refuse: a change against what the page did not see (M1)
def test_two_tabs_cannot_both_change_one_version(server, home):
    iid = new(server, home)
    v = item(home, iid)["events"][-1]
    assert change(server, "act", {"id": iid, "act": "priority", "value": 1}, v)[0] == 200
    code, got = change(server, "act", {"id": iid, "act": "priority", "value": 5}, v)   # the other tab, drawn before
    assert code == 400 and "STALE_VERSION" in got["error"]
    code, got = change(server, "edit", {"id": iid, "title": "late"}, v)
    assert code == 400 and "STALE_VERSION" in got["error"]
    assert (item(home, iid)["priority"], item(home, iid)["title"]) == (1, "First")


@pytest.mark.parametrize("version", [None, True, 0, -1, "3", 1.0])
def test_an_edit_or_act_names_a_whole_version(server, home, version):   # must refuse
    iid = new(server, home)
    body = {"action": "act", "request": {"id": iid, "act": "park", "request_key": next(KEYS)}}
    if version is not None:
        body["version"] = version
    assert call(server, body)[0] == 400
    assert item(home, iid)["state"] == "backlog"


def test_a_move_names_the_state_it_was_drawn_in(server, home):   # must refuse
    iid = new(server, home)
    v = item(home, iid)["events"][-1]
    assert change(server, "act", {"id": iid, "act": "doing"}, v)[0] == 400
    assert change(server, "act", {"id": iid, "act": "doing", "from": "next"}, v)[0] == 400
    assert change(server, "act", {"id": iid, "act": "done", "from": "backlog"}, v, confirm=iid)[0] == 400


# ---------------------------------------------------------------- must refuse: what is filed and written
@pytest.mark.parametrize("req", [
    {"project": "elsewhere", "title": "x"},
    {"project": "demo", "title": "a‮b"},
    {"project": "demo", "title": "line\nbreak"},
    {"project": "demo", "title": "x" * 201},
    {"project": "demo", "title": "key sk-ant-api03-" + "A" * 40},
    {"project": "demo", "title": "x", "kind": "saga"},
])
def test_a_create_the_kernel_would_refuse_is_refused_from_the_page_too(server, home, req):   # must refuse
    assert change(server, "create", req)[0] == 400
    assert Writer(home).state()["items"] == {}


def test_a_refused_body_is_not_written_to_the_log(server, home):   # Koinos: refused bodies not logged
    change(server, "create", {"project": "demo", "title": "key sk-ant-api03-" + "B" * 40})
    log = home / "work" / "events.jsonl"
    assert not log.exists() or "sk-ant" not in log.read_text(encoding="utf-8")


def test_a_retry_records_once_and_another_body_under_its_key_is_refused(home):
    w = Writer(home)
    a = w.person_from_page("create", {"project": "demo", "title": "once", "request_key": "same"})
    b = w.person_from_page("create", {"project": "demo", "title": "once", "request_key": "same"})
    assert b.get("repeat") and b["seq"] == a["seq"]
    with pytest.raises(WorkRefused) as e:
        w.person_from_page("create", {"project": "demo", "title": "other", "request_key": "same"})
    assert e.value.code == "CONFLICT"
    assert len(Writer(home).state()["items"]) == 1


# ---------------------------------------------------------------- must refuse: the page's evidence read back
def rec(seq, event, evidence=PAGE, who=PERSON, **fields):
    r = {"v": 1, "seq": seq, "event": event, "who": who, "assurance": "bound", "channel": "page",
         "at": "2026-11-02T22:00:00Z", **fields}
    if evidence is not None:
        r["evidence"] = evidence
    return r


def folded(records):
    return fold(records, checks=span.checks(records, []))


def test_the_pages_evidence_applies_on_the_chain_only():
    c = rec(1, "create", id="W-demo-1", project="demo", title="x")
    assert "W-demo-1" in folded([(1, c, True)])["items"]
    off = folded([(1, c, False)])
    assert off["items"] == {} and not off["events"][0]["applied"]


def test_the_read_back_alone_holds_the_page_to_the_chain():   # each layer on its own: the rules refuse it too
    c = rec(1, "create", id="W-demo-1", project="demo", title="x")
    assert span.check(c, [], on_chain=True)[0] == span.PAGE
    assert span.check(c, [], on_chain=False)[0] == span.UNVERIFIED
    assert span.check({**c, "evidence": {**PAGE, "extra": 1}}, [], on_chain=True)[0] == span.UNVERIFIED


@pytest.mark.parametrize("evidence", [
    None,                                                            # the person's create with no evidence at all
    {"kind": "page"},
    {"kind": "page", "route": "/api/answer"},
    {"kind": "page", "route": "/api/work", "span": {"path": "x", "offset": 0, "length": 1, "sha256": "0" * 64}},
    {"kind": "chat", "route": "/api/work"},
    {"route": "/api/work"},
    "page",
])
def test_any_other_evidence_for_the_persons_create_is_not_applied(evidence):   # must refuse
    c = rec(1, "create", evidence, id="W-demo-1", project="demo", title="x")
    got = folded([(1, c, True)])
    assert got["items"] == {} and not got["events"][0]["applied"]


def test_a_planted_page_edit_or_act_off_the_chain_is_not_applied():   # must refuse
    c = rec(1, "create", id="W-demo-1", project="demo", title="x")
    e = rec(2, "edit", id="W-demo-1", title="planted")
    p = rec(3, "person_act", id="W-demo-1", act="park")
    got = folded([(1, c, True), (2, e, False), (3, p, False)])
    i = got["items"]["W-demo-1"]
    assert (i["title"], i["state"]) == ("x", "backlog")


def test_a_seat_never_edits_with_the_pages_evidence():   # must refuse: page evidence is the person's only
    c = rec(1, "create", id="W-demo-1", project="demo", title="x")
    e = rec(2, "edit", who="koinos", id="W-demo-1", title="seat")
    got = folded([(1, c, True), (2, e, True)])
    assert got["items"]["W-demo-1"]["title"] == "x"


def test_an_agent_still_never_acts_as_the_person(home):   # must refuse (unchanged)
    w = Writer(home)
    for actor in (Actor(PERSON, "bound", "mcp"), Actor("koinos", "bound", "page")):
        with pytest.raises(WorkRefused):
            w.write(actor, "person_act", {"id": "W-demo-1", "act": "park"})
    with pytest.raises(WorkRefused):
        w.write(Actor(PERSON, "bound", "page"), "create", {"project": "demo", "title": "x"})


# ---------------------------------------------------------------- must refuse: one caller, one poster
def test_only_the_page_server_calls_the_pages_writer():
    src = paths.static_dir().parent
    callers = sorted(p.relative_to(src).as_posix() for p in src.rglob("*.py")
                     if "person_from_page(" in p.read_text(encoding="utf-8"))
    assert callers == ["server.py", "work/writer.py"]


def test_only_workact_names_the_work_route_and_it_names_no_other():
    v2 = paths.static_dir() / "v2"
    naming = sorted(p.name for p in v2.glob("*.js") if "/api/work" in p.read_text(encoding="utf-8"))
    assert naming == ["workact.js"]
    t = (v2 / "workact.js").read_text(encoding="utf-8")
    assert set(re.findall(r'"(/api/[a-z0-9/-]*)"', t)) == {"/api/work"}
    assert "innerHTML" not in t and "insertAdjacentHTML" not in t


# ---------------------------------------------------------------- Koinos's attack of b8f1a35 (RESULT_page_acts_code_b8f1a35.md)
def test_f1_an_agents_comment_does_not_make_the_persons_click_stale(server, home):   # must pass
    iid = new(server, home)
    v = item(home, iid)["version"]
    Writer(home).write(Actor("koinos", "bound", "mcp"), "comment", {"id": iid, "text": "a note"})
    assert item(home, iid)["comments"] and item(home, iid)["version"] == v
    assert change(server, "act", {"id": iid, "act": "park"}, v)[0] == 200


def test_f1_a_change_to_the_item_still_makes_it_stale(server, home):   # must refuse (M1 kept)
    iid = new(server, home)
    v = item(home, iid)["version"]
    assert change(server, "edit", {"id": iid, "title": "changed"}, v)[0] == 200
    code, got = change(server, "act", {"id": iid, "act": "park"}, v)
    assert code == 400 and "STALE_VERSION" in got["error"]


@pytest.mark.parametrize("value", [True, False, "2", "abc", None, [1], 0, 1000, -3, 10 ** 15, 2.0])
def test_f2_a_priority_is_a_whole_number_from_1_to_999(server, home, value):   # must refuse
    iid = new(server, home)
    v = item(home, iid)["version"]
    assert change(server, "act", {"id": iid, "act": "priority", "value": value}, v)[0] == 400
    assert item(home, iid)["priority"] is None


@pytest.mark.parametrize("value", [1, 999])
def test_f2_the_ends_of_the_range_are_taken(server, home, value):   # must pass
    iid = new(server, home)
    assert change(server, "act", {"id": iid, "act": "priority", "value": value}, item(home, iid)["version"])[0] == 200
    assert item(home, iid)["priority"] == value


def test_f2_another_act_carries_no_value(server, home):   # must refuse
    iid = new(server, home)
    assert change(server, "act", {"id": iid, "act": "park", "value": 3}, item(home, iid)["version"])[0] == 400


@pytest.mark.parametrize("channel", ["mcp", "cli", "person", None])
def test_f3_the_pages_evidence_on_another_channel_is_not_the_pages(channel):   # must refuse
    c = rec(1, "create", id="W-demo-1", project="demo", title="x")
    if channel is None:
        c.pop("channel")
    else:
        c["channel"] = channel
    got = folded([(1, c, True)])
    assert got["items"] == {} and not got["events"][0]["applied"]
    ok = rec(1, "create", id="W-demo-1", project="demo", title="x")
    e = rec(2, "edit", id="W-demo-1", title="other channel")
    e["channel"] = channel or "mcp"
    p = rec(3, "person_act", id="W-demo-1", act="park")
    p["channel"] = channel or "mcp"
    i = folded([(1, ok, True), (2, e, True), (3, p, True)])["items"]["W-demo-1"]
    assert (i["title"], i["state"]) == ("x", "backlog")


def test_f4_an_exact_retry_of_an_applied_act_answers_as_a_retry(home):   # must pass
    w = Writer(home)
    iid = w.person_from_page("create", {"project": "demo", "title": "x", "request_key": "c"})["id"]
    v = w.state()["items"][iid]["version"]
    a = w.person_from_page("person_act", {"id": iid, "act": "park", "request_key": "p"}, v)
    b = w.person_from_page("person_act", {"id": iid, "act": "park", "request_key": "p"}, v)
    assert b.get("repeat") and b["seq"] == a["seq"]


def test_f6_a_key_named_twice_is_refused(server, home):   # must refuse
    raw = b'{"action": "create", "request": {"project": "demo", "title": "x", "title": "y", "request_key": "d1"}}'
    assert call(server, None, raw=raw)[0] == 400
    raw = b'{"action": "create", "action": "edit", "request": {"project": "demo", "title": "x", "request_key": "d2"}}'
    assert call(server, None, raw=raw)[0] == 400
    assert Writer(home).state()["items"] == {}