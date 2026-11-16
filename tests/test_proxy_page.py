"""Answering the proxy from the page: "The proxy holds" in Waiting, its read route and its one answer route.

The person's yes, no or revoke to a call the proxy holds, as their own page act (proxycmd.answer, the command's answer,
sent from the page). It is held as the Work route is: the X-Semantext header, the page's own Origin, a Referer naming one
of the page's own addresses, a same-origin plain fetch, and nothing from a plug-in's page module. The refusals come first.
These tests build the proxy's run, asks and record files directly (no proxy process, no model SDK), the way the proxy and
the command write them.
"""
from __future__ import annotations

import json
import re
import threading
from contextlib import ExitStack
import time
import urllib.error
import urllib.request

import pytest

from semantext import cli, decide, paths, proxycmd
from semantext.proxy_record import Record
from semantext.store import file_lock
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
ANSWER, ASKS = "/api/proxy/answer", "/api/proxy/asks"


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    assert cli.main(["--home", str(h), "init"]) == 0
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


_HELD: dict = {}


def hold_proxy(proxy_home):
    """What a running proxy does for its whole life: hold serve.lock in its home (proxycmd.serve). The list and the answer
    ask whether a proxy runs by trying that lock, so a test that lists or answers stands in for the running proxy by
    holding it, here, until the test ends. Held once per folder, however many Worlds name it."""
    key = str(proxy_home)
    if key not in _HELD:
        stack = ExitStack()
        stack.enter_context(file_lock(proxy_home / "serve.lock"))
        _HELD[key] = stack


def stop_proxy(proxy_home):
    """The proxy ends: the operating system lets its lock go."""
    stack = _HELD.pop(str(proxy_home), None)
    if stack is not None:
        stack.close()


@pytest.fixture(autouse=True)
def _proxies_end_with_the_test():
    yield
    for key in list(_HELD):
        _HELD.pop(key).close()


class World:
    """The proxy's folder as the proxy leaves it: run.json, the asks file and the chained record. `running` (the
    default) also holds serve.lock, as a running proxy does."""

    def __init__(self, home, run_id="run-1", running=True):
        self.home = proxycmd.proxy_home(home)
        proxycmd.write_run(self.home, run_id, 8790)
        if running:
            hold_proxy(self.home)
        self.record = Record(self.home / "proxy.jsonl")
        self.asks = decide.Asks(self.home / "asks.json", run=run_id, record=self.record)

    def hold(self, tool="Bash", agent="coder", rule="Confirm before deleting", n=1, ago=0.0):
        return self.asks.open(agent, "space", tool, "delete", f"digest-{tool}-{n}", "conv-1", time.monotonic() - ago,
                              reading={"act": "delete", "word": "PRIVATE WORDS", "rule": rule} if rule else None)

    def status(self, aid):
        return next(a["status"] for a in self.asks._read() if a["id"] == aid)

    def chain(self):
        return [(r["body"]["ask"], r["body"]["word"]) for r in self.record.lines() if r.get("kind") == "answered"]


@pytest.fixture
def world(home):
    return World(home)


def call(server, body, *, origin=True, referer="/v2", extra=None, path=ANSWER, raw=None, method="POST"):
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"X-Semantext": "1", "Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin if isinstance(origin, str) else f"http://{host}"
    if referer is not None:
        headers["Referer"] = referer if referer.startswith("http") else f"http://{host}{referer}"
    headers.update(extra or {})
    data = None if method == "GET" else (raw if raw is not None else json.dumps(body).encode())
    req = urllib.request.Request(f"http://{host}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def listed(server, **kw):
    kw.setdefault("origin", False)
    kw.setdefault("referer", None)
    return call(server, None, path=ASKS, method="GET", **kw)


def answer(server, ask, word, **kw):
    return call(server, {"ask": ask, "word": word}, **kw)


# ---------------------------------------------------------------- must refuse: a read from anywhere but the page
@pytest.mark.parametrize("kw", [
    {"extra": {"X-Semantext": "0"}},
    {"extra": {"Sec-Fetch-Site": "cross-site"}},
    {"extra": {"Sec-Fetch-Site": "same-site"}},
    {"origin": "http://evil.example"},
    {"referer": "/v2/plugin/x/page.html"},
    {"referer": "/v2/plugin/x.js"},
    {"extra": {"Sec-Fetch-Dest": "script"}},
])
def test_the_list_is_read_only_by_the_page_itself(server, world, kw):   # must refuse
    world.hold()
    code, got = listed(server, **kw)
    assert code == 403 and "asks" not in got


def test_the_list_needs_the_header_at_all(server, world):   # must refuse
    world.hold()
    host = f"127.0.0.1:{server.server_address[1]}"
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(urllib.request.Request(f"http://{host}{ASKS}"), timeout=20)
    assert e.value.code == 403


# ---------------------------------------------------------------- must refuse: where an answer came from (do_POST and M3)
@pytest.mark.parametrize("kw", [
    {"origin": False},
    {"origin": "http://evil.example"},
    {"origin": "http://localhost:1"},
    {"referer": None},                                   # a no-referrer fetch hides where it runs
    {"referer": "http://evil.example/v2"},
    {"referer": "/v2/plugin/x/page.html"},               # a plug-in's page module
    {"referer": "/v2/proxyholds.js"},
    {"referer": "/v2?x=1"},
    {"extra": {"Sec-Fetch-Site": "cross-site"}},
    {"extra": {"Sec-Fetch-Site": "same-site"}},
    {"extra": {"Sec-Fetch-Dest": "iframe"}},
    {"extra": {"Sec-Fetch-Mode": "navigate"}},
    {"extra": {"X-Semantext": "0"}},
])
def test_an_answer_not_sent_by_the_page_itself_is_refused_and_answers_nothing(server, world, kw):   # must refuse
    aid = world.hold()
    code, _ = answer(server, aid, "yes", **kw)
    assert code == 403
    assert world.status(aid) == "open" and world.chain() == []


# ---------------------------------------------------------------- must refuse: what the answer names
def test_an_ask_that_is_not_there_is_refused(server, world):   # must refuse
    aid = world.hold()
    code, got = answer(server, "ask-nope", "yes")
    assert code == 400 and "no ask" in got["error"]
    assert world.status(aid) == "open"


def test_an_ask_of_an_earlier_run_is_neither_listed_nor_answered(server, home):   # must refuse
    old = World(home, "run-0")
    aid = old.hold()
    now = World(home, "run-1")
    assert listed(server)[1]["asks"] == []
    code, got = answer(server, aid, "yes")
    assert code == 400 and "earlier run" in got["error"]
    assert old.status(aid) == "open" and now.chain() == []


def test_an_ask_that_has_run_out_is_neither_listed_nor_answered(server, world):   # must refuse
    aid = world.hold(ago=10 ** 6)
    assert listed(server)[1]["asks"] == []
    assert answer(server, aid, "yes")[0] == 400
    assert world.chain() == []


def test_a_broken_record_answers_nothing(server, world):   # must refuse
    aid = world.hold()
    (world.home / "proxy.jsonl").write_text("not a sealed line\n", encoding="utf-8")
    code, got = answer(server, aid, "yes")
    assert code == 400 and "record is broken" in got["error"]
    assert world.status(aid) == "open"
    assert [a["id"] for a in listed(server)[1]["asks"]] == [aid]     # still listed: the answer, not the list, says so


@pytest.mark.parametrize("word", ["maybe", "YES", "Yes", "", " yes", "yes ", "approve", None, 1, True, ["yes"], {"yes": 1}])
def test_a_word_that_is_not_yes_no_or_revoke_is_refused(server, world, word):   # must refuse
    aid = world.hold()
    code, got = answer(server, aid, word)
    assert code == 400 and "yes, no or revoke" in got["error"]
    assert world.status(aid) == "open" and world.chain() == []


@pytest.mark.parametrize("ask", [None, 1, True, "", ["x"], {"a": 1}, "x" * 81])
def test_an_ask_that_is_not_an_id_is_refused(server, world, ask):   # must refuse
    aid = world.hold()
    assert answer(server, ask, "yes")[0] == 400
    assert world.status(aid) == "open" and world.chain() == []


@pytest.mark.parametrize("body", [{"ask": "a"}, {"word": "yes"}, {}, [], "yes", 3, None,
                                  {"ask": "a", "word": "yes", "note": "x"}, {"ask": "a", "word": "yes", "via": "page"}])
def test_a_body_that_is_not_exactly_ask_and_word_is_refused(server, world, body):   # must refuse
    world.hold()
    code, _ = call(server, body)
    assert code == 400
    assert world.chain() == []


def test_a_key_named_twice_is_refused(server, world):   # must refuse
    aid = world.hold()
    raw = ('{"ask": "%s", "word": "no", "word": "yes"}' % aid).encode()
    assert call(server, None, raw=raw)[0] == 400
    assert world.status(aid) == "open" and world.chain() == []


def test_a_revoke_of_an_ask_with_no_yes_is_refused(server, world):   # must refuse
    aid = world.hold()
    code, got = answer(server, aid, "revoke")
    assert code == 400 and "cannot take" in got["error"]
    assert world.status(aid) == "open" and world.chain() == []


def test_an_ask_answered_cannot_be_answered_again(server, world):   # must refuse
    aid = world.hold()
    assert answer(server, aid, "no")[0] == 200
    code, got = answer(server, aid, "yes")
    assert code == 400 and "cannot take" in got["error"]
    assert world.status(aid) == "no" and world.chain() == [(aid, "no")]


def test_two_presses_at_once_make_one_answer(server, world):   # must refuse the second
    aid = world.hold()
    out = []
    ts = [threading.Thread(target=lambda: out.append(answer(server, aid, "yes")[0])) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == [200, 400, 400, 400]
    assert world.chain() == [(aid, "yes")]


def test_no_answer_is_made_where_no_proxy_has_run(server, home):   # must refuse
    code, got = answer(server, "ask-1", "yes")
    assert code == 400 and "no proxy has run" in got["error"]
    assert not (proxycmd.proxy_home(home)).exists()                   # answering made nothing


# ---------------------------------------------------------------- must pass: the list
def test_where_no_proxy_has_run_the_list_says_so(server):
    assert listed(server) == (200, {"state": "none", "asks": []})


def test_the_list_holds_the_commands_fields_and_nothing_of_the_call(server, world):
    aid = world.hold()
    code, got = listed(server)
    assert code == 200 and got["state"] == "ok"
    (a,) = got["asks"]
    assert set(a) == {"id", "agent", "tool", "why", "minutes_left", "status"}
    assert (a["id"], a["agent"], a["tool"], a["why"], a["status"]) == (aid, "coder", "Bash", "Confirm before deleting", "open")
    assert 0 <= a["minutes_left"] <= 60
    text = json.dumps(got)
    assert "PRIVATE WORDS" not in text and "digest-" not in text and "conv-1" not in text      # not the call, not your words


def test_the_list_lists_what_the_command_lists(server, world):
    world.hold(tool="Bash")
    world.hold(tool="Write", n=2)
    page = [(a["id"], a["agent"], a["tool"], a["why"], a["minutes_left"]) for a in listed(server)[1]["asks"]]
    cmd = [(a["id"], a["agent"], a["tool"], a["why"], a["minutes_left"]) for a in proxycmd.open_asks(world.home)]
    assert page == cmd and len(page) == 2


def test_a_tool_the_agent_may_not_call_is_said_so(server, world):
    world.hold(tool="undeclared:Secret", rule=None)
    (a,) = listed(server)[1]["asks"]
    assert a["tool"] == "a tool the agent may not call" and a["why"] == "a gate holds this tool"


def test_a_field_with_control_characters_is_listed_without_them(server, world):
    world.hold(agent="co\x1b[2Jder")
    (a,) = listed(server)[1]["asks"]
    assert a["agent"] == "co?[2Jder"


def test_a_damaged_asks_file_or_run_file_is_said_and_lists_nothing(server, world):
    world.hold()
    (world.home / "asks.json").write_text("{not json", encoding="utf-8")
    assert listed(server) == (200, {"state": "unreadable", "asks": []})
    (world.home / "asks.json").write_text(json.dumps([{"id": "x", "expires": "soon"}, 7, None]), encoding="utf-8")
    assert listed(server) == (200, {"state": "ok", "asks": []})          # a row the proxy did not write is never listed
    (world.home / "run.json").write_text("[]", encoding="utf-8")
    assert listed(server) == (200, {"state": "unreadable", "asks": []})


def test_a_yes_the_chain_does_not_hold_is_not_listed(server, world):   # must refuse to show a yes that releases nothing
    aid = world.hold()
    rows = world.asks._read()
    rows[0]["status"] = "yes"                                              # the file says yes; the chain says nothing
    (world.home / "asks.json").write_text(json.dumps(rows), encoding="utf-8")
    assert listed(server)[1]["asks"] == []


# ---------------------------------------------------------------- must pass: the answers
def test_a_yes_from_the_page_is_the_commands_yes(server, world):
    aid = world.hold()
    code, got = answer(server, aid, "yes")
    assert (code, got) == (200, {"ok": True, "ask": aid, "status": "yes"})
    assert world.status(aid) == "yes" and world.chain() == [(aid, "yes")]       # the chain, and the file after it
    assert world.asks.yes_for("coder", "space", "Bash", "digest-Bash-1", "conv-1", time.monotonic()) == aid
    (a,) = listed(server)[1]["asks"]
    assert (a["id"], a["status"]) == (aid, "yes")                                # listed for a revoke, not as open
    assert [x["id"] for x in proxycmd.open_asks(world.home)] == []              # and the command lists only the open


def test_a_revoke_takes_a_yes_not_yet_used_back(server, world):
    aid = world.hold()
    answer(server, aid, "yes")
    code, got = answer(server, aid, "revoke")
    assert (code, got["status"]) == (200, "revoked")
    assert world.chain() == [(aid, "yes"), (aid, "revoke")]
    assert world.asks.yes_for("coder", "space", "Bash", "digest-Bash-1", "conv-1", time.monotonic()) is None
    assert listed(server)[1]["asks"] == []


def test_a_yes_already_used_cannot_be_revoked_or_listed(server, world):
    aid = world.hold()
    answer(server, aid, "yes")
    assert world.asks.spend([aid], time.monotonic())
    assert listed(server)[1]["asks"] == []
    code, got = answer(server, aid, "revoke")
    assert code == 400 and "cannot take" in got["error"]


def test_a_no_drops_the_call(server, world):
    aid = world.hold()
    other = world.hold(tool="Write", n=2)
    code, got = answer(server, aid, "no")
    assert (code, got["status"]) == (200, "no")
    assert world.asks.yes_for("coder", "space", "Bash", "digest-Bash-1", "conv-1", time.monotonic()) is None
    assert [a["id"] for a in listed(server)[1]["asks"]] == [other]
    assert world.status(other) == "open"                                         # the answer touched only its own ask


def test_the_page_and_the_command_answer_the_same_file(server, world):
    a1, a2 = world.hold(), world.hold(tool="Write", n=2)
    assert proxycmd.answer(world.home, a1, "no") == "no"
    assert answer(server, a2, "yes")[0] == 200
    assert world.chain() == [(a1, "no"), (a2, "yes")]


def test_the_list_is_only_the_default_proxy_home(server, home, tmp_path):
    elsewhere = World(tmp_path / "other")
    elsewhere.hold()
    assert listed(server) == (200, {"state": "none", "asks": []})


# ---------------------------------------------------------------- the page's code: one more route, named once
def js(name):
    return (paths.static_dir() / "v2" / name).read_text(encoding="utf-8")


def test_the_module_writes_only_to_its_own_route():   # must refuse any other write
    t = js("proxyholds.js")
    assert t.count('method: "POST"') == 1 and "innerHTML" not in t and "insertAdjacentHTML" not in t
    assert re.findall(r'fetch\(([^,]+),', t) == ["ASKS_ROUTE", "PROXY_ROUTE"]
    assert 'export const PROXY_ROUTE = "/api/proxy/answer";' in t and 'export const ASKS_ROUTE = "/api/proxy/asks";' in t
    assert '"X-Semantext": "1"' in t
    for name in (p.name for p in (paths.static_dir() / "v2").glob("*.js")):
        if name != "proxyholds.js":
            assert "/api/proxy/" not in js(name), name                  # no other part of the page names it


def test_the_server_names_the_route_once_in_each_direction():
    from semantext import server
    assert server.PROXY_ANSWER == ANSWER and server.PROXY_ASKS == ASKS and "/v2/proxyholds.js" in server.V2_FILES


# ---------------------------------------------------------------- the Waiting place, in node
SET_UP = """
let asks = [], state = "ok", posts = [], reads = 0, refuse = null, hang = false, down = false;
globalThis.fetch = (url, opts) => {
  if (url === "/api/proxy/asks") {
    reads++;
    if (down) return Promise.reject(new Error("offline"));
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ state, asks: asks.map((a) => ({ ...a })) }) });
  }
  if (url === "/api/proxy/answer") {
    posts.push({ url, method: opts.method, headers: opts.headers, body: JSON.parse(opts.body) });
    if (hang) return new Promise(() => {});
    if (refuse) return Promise.resolve({ ok: false, json: () => Promise.resolve({ error: refuse }) });
    const b = JSON.parse(opts.body), a = asks.find((x) => x.id === b.ask);
    if (b.word === "yes") a.status = "yes"; else asks = asks.filter((x) => x.id !== b.ask);
    return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, ask: b.ask, status: b.word }) });
  }
  return new Promise(() => {});
};
const ask = (id, over) => ({ id, agent: "coder", tool: "Bash", why: "Confirm before deleting", minutes_left: 7, status: "open", ...over });
S.place = "waiting"; S.mounted = "waiting/";
mount();
S.data.waiting = { cards: [], seats: [], holds: { text: "" }, machine_inbox: [], change_records: [], changes: {}, frame: {} };
const place = () => document.getElementById("place");
const section = () => place().all((e) => e.tagName === "SECTION" && e.attributes["aria-label"] === "The proxy holds")[0];
const buttons = () => section().all((e) => e.tagName === "BUTTON").map((b) => b.textContent);
const press = (label) => section().all((e) => e.tagName === "BUTTON" && e.textContent === label)[0].click();
async function settle() { for (let i = 0; i < 40; i++) await Promise.resolve(); }   // every stub answers in microtasks
"""


def drive(body):
    """The test body runs after the set-up, in an async function, so it may wait for the stubs to answer."""
    return run(SET_UP + "return (async () => {\n" + body + "\n})();")


@needs_node
def test_before_the_first_read_nothing_is_drawn_and_a_slow_server_costs_nothing():
    got = drive("""
fill();
report([section().childNodes.length, reads]);
""")
    assert got == [0, 0]


@needs_node
def test_no_proxy_run_is_said_in_plain_words():
    got = drive("""
state = "none";
fill(); await holdsRead(); await settle();
report(section().textContent);
""")
    assert "The proxy holds" in got and "No proxy has run from this Semantext home" in got and "semantext proxy serve" in got
    assert "Nothing waits" not in got


@needs_node
def test_nothing_waiting_is_said_in_plain_words():
    got = drive("""
fill(); await holdsRead(); await settle();
report([section().textContent, buttons(), place().textContent.includes("Nothing is waiting for you.")]);
""")
    assert "Nothing waits for your word at the proxy." in got[0] and "No proxy has run" not in got[0]
    assert got[1] == [] and got[2] is True


@needs_node
def test_an_unreadable_proxy_and_a_failed_read_are_said_not_hidden():
    got = drive("""
state = "unreadable";
fill(); await holdsRead(); await settle();
const a = section().textContent;
state = "ok"; down = true; await holdsRead(); await settle();
report([a, section().textContent, buttons()]);
""")
    assert "could not be read, so nothing is listed" in got[0] and "semantext proxy asks" in got[0]
    assert "Could not read what the proxy holds." in got[1] and got[2] == []


@needs_node
def test_each_held_call_is_listed_with_yes_once_and_no_and_a_yes_with_revoke_only():
    got = drive("""
asks = [ask("ask-1"), ask("ask-2", { tool: "Write", minutes_left: 0 }), ask("ask-3", { status: "yes", agent: "other" })];
fill(); await holdsRead(); await settle();
const cards = section().all((e) => e.tagName === "ARTICLE");
report({ n: cards.length, buttons: cards.map((c) => c.all((e) => e.tagName === "BUTTON").map((b) => b.textContent)),
  first: cards[0].textContent, second: cards[1].textContent, third: cards[2].textContent, head: section().textContent.slice(0, 60),
  say: document.getElementById("bar-place").textContent });
""")
    assert got["n"] == 3
    assert got["buttons"] == [["Yes once", "No"], ["Yes once", "No"], ["Revoke"]]
    assert "coder wants to call Bash" in got["first"] and "Confirm before deleting" in got["first"] and "7 minutes left" in got["first"]
    assert "less than a minute left" in got["second"] and "Write" in got["second"]
    assert "other wants to call Bash" in got["third"] and "You said yes" in got["third"]
    assert got["head"].startswith("The proxy holds · 2 waiting, 1 said yes")
    assert got["say"].startswith("No card is waiting for you. The proxy holds 2 calls for you.")


@needs_node
def test_a_press_sends_exactly_the_one_answer_and_the_list_follows_it():
    got = drive("""
asks = [ask("ask-1"), ask("ask-2", { tool: "Write" })];
fill(); await holdsRead(); await settle();
press("Yes once"); await settle();
const afterYes = { buttons: buttons(), note: section().textContent };
press("No"); await settle();
report({ posts, afterYes, afterNo: buttons(), text: section().textContent, reads });
""")
    assert [p["body"] for p in got["posts"]] == [{"ask": "ask-1", "word": "yes"}, {"ask": "ask-2", "word": "no"}]
    assert all(p["url"] == "/api/proxy/answer" and p["method"] == "POST" and p["headers"]["X-Semantext"] == "1" for p in got["posts"])
    assert got["afterYes"]["buttons"] == ["Revoke", "Yes once", "No"]          # ask-1 now takes only a revoke
    assert "Said yes to coder's call of Bash: the proxy releases that call once" in got["afterYes"]["note"]
    assert got["afterNo"] == ["Revoke"]                                          # the no'd ask is gone
    assert "Said no to coder's call of Write." in got["text"] and got["reads"] >= 3


@needs_node
def test_a_revoke_is_sent_for_a_yes_and_takes_it_off_the_list():
    got = drive("""
asks = [ask("ask-1", { status: "yes" })];
fill(); await holdsRead(); await settle();
press("Revoke"); await settle();
report([posts.map((p) => p.body), buttons(), section().textContent]);
""")
    assert got[0] == [{"ask": "ask-1", "word": "revoke"}] and got[1] == []
    assert "Took the yes back to coder's call of Bash." in got[2] and "Nothing waits for your word" in got[2]


@needs_node
def test_a_refused_answer_is_said_and_the_list_is_as_it_was():   # must refuse
    got = drive("""
asks = [ask("ask-1")];
fill(); await holdsRead(); await settle();
refuse = "the proxy's record is broken; nothing is answered until it is looked at";
press("Yes once"); await settle();
report([buttons(), section().textContent, section().all((e) => e.attributes.role === "alert").length]);
""")
    assert got[0] == ["Yes once", "No"]
    assert "Not taken: the proxy's record is broken" in got[1] and got[2] == 1


@needs_node
def test_a_press_while_its_answer_is_on_the_way_is_not_sent_twice():   # must refuse the second
    got = drive("""
asks = [ask("ask-1")];
fill(); await holdsRead(); await settle();
hang = true;
const yes = section().all((e) => e.tagName === "BUTTON" && e.textContent === "Yes once")[0];
yes.click(); yes.click(); await settle();
report([posts.length, section().all((e) => e.tagName === "BUTTON").map((b) => b.disabled)]);
""")
    assert got == [1, [True, True]]


@needs_node
def test_the_page_draws_only_the_named_fields_of_an_ask():   # must refuse anything else the server might send
    got = drive("""
asks = [ask("ask-1", { input: "rm -rf SECRET-INPUT", words: "SECRET-WORDS", d_act: "DIGEST" })];
fill(); await holdsRead(); await settle();
report(place().textContent);
""")
    assert "SECRET" not in got and "DIGEST" not in got and "coder wants to call Bash" in got


@needs_node
def test_waiting_reads_the_proxy_again_when_it_reads_again():
    got = drive("""
asks = [];
S.sig.waiting = null;
globalThis.fetch = ((was) => (url, o) => url === "/api/v2/waiting" ? Promise.resolve({ ok: true, json: () => Promise.resolve({ ...S.data.waiting, frame: { name: null, word: null, waiting: 0, problems: [], outside: [] } }) }) : was(url, o))(globalThis.fetch);
await load("waiting"); await settle();
const first = reads;
asks = [ask("ask-9")];
S.sig.waiting = null; await load("waiting"); await settle();
report([first, reads, buttons()]);
""")
    assert got == [1, 2, ["Yes once", "No"]]
