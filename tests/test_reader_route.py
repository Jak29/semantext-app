"""The reader on the page (1.8.0): POST /api/read, the Prism message box and Rules' Try a message, one reader for the
command line and the page.

The route reads a message and answers with the reader's clause readings and its advice for each act (reading.report, the
same call `semantext read` prints from). It is a POST only so that the person's words never travel in an address; it
changes nothing and writes nothing. The must-refuse arms come first: where a request came from, what it carries, how big
it is, and that nothing is written. Then the equivalence: the route, reading.advise and the command line agree on the
reader's own corpus (tests/test_reading.py). Then the page's side, drawn in node from the real reader's answers.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from semantext import cli, reading
from semantext.server import READ_BODY
from test_one_page import WORLD
from test_reading import ATTACK_R1, CASES
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


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


def call(server, body=None, *, origin=True, referer="/v2", extra=None, path="/api/read", raw=None, semantext="1"):
    """POST to the route as the page does (its own Origin, header and Referer), each of which a test may take away."""
    host = f"127.0.0.1:{server.server_address[1]}"
    headers = {"Content-Type": "application/json"}
    if semantext is not None:
        headers["X-Semantext"] = semantext
    if origin:
        headers["Origin"] = origin if isinstance(origin, str) else f"http://{host}"
    if referer is not None:
        headers["Referer"] = referer if referer.startswith("http") else f"http://{host}{referer}"
    headers.update(extra or {})
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"http://{host}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def listing(root: Path) -> dict:
    """Every file and folder under root: (kind, size, modification time)."""
    out = {}
    for here, dirs, files in os.walk(root):
        for name in dirs + files:
            p = Path(here) / name
            st = p.lstat()
            out[str(p.relative_to(root))] = (p.is_dir(), 0 if p.is_dir() else st.st_size, st.st_mtime_ns)
    return out


MARK = "MARKER-91c2 publish it"


# ---------------------------------------------------------------- must refuse: where it came from
@pytest.mark.parametrize("kw", [
    {"origin": False},
    {"origin": "http://evil.example"},
    {"origin": "http://localhost:1"},
    {"semantext": None},
    {"semantext": "0"},
    {"referer": None},                                   # a no-referrer fetch hides where it runs
    {"referer": "http://evil.example/v2"},
    {"referer": "/v2/plugin/x/page.html"},               # a plug-in's page module
    {"referer": "/v2/reader.js"},
    {"referer": "/v2?x=1"},
    {"extra": {"Sec-Fetch-Site": "cross-site"}},
    {"extra": {"Sec-Fetch-Site": "same-site"}},
    {"extra": {"Sec-Fetch-Dest": "iframe"}},
    {"extra": {"Sec-Fetch-Mode": "navigate"}},
    {"extra": {"Host": "evil.example"}},
], ids=lambda kw: json.dumps(kw))
def test_a_read_not_asked_by_the_page_itself_is_refused_and_says_nothing_of_the_words(server, home, kw):   # must refuse
    before = listing(home)
    code, got = call(server, {"message": MARK}, **kw)
    assert code == 403 and MARK not in json.dumps(got) and "readings" not in got
    assert listing(home) == before


# ---------------------------------------------------------------- must refuse: what it carries
@pytest.mark.parametrize("raw", [b"not json", b"", b"{", b'{"message": "a", "message": "b"}', b"[1]", b'"text"', b"null", b"7",
                                 b'{"message": "a"} trailing', b"\xff\xfe"], ids=lambda r: repr(r)[:30])
def test_a_body_that_is_not_one_json_record_is_refused(server, raw):   # must refuse
    code, got = call(server, raw=raw)
    assert code == 400 and "readings" not in got and "error" in got


@pytest.mark.parametrize("body", [
    {}, {"message": 7}, {"message": None}, {"message": ["a"]}, {"message": "a", "offer": 7}, {"message": "a", "offer": ["x"]},
    {"message": "a", "acts": "publish"}, {"message": "a", "acts": ["launch"]}, {"message": "a", "acts": [7]},
    {"message": "a", "acts": ["publish"] * 8}, {"message": "a", "extra": 1}, {"message": "a", "house": ["No pushing."]},
], ids=lambda b: json.dumps(b)[:40])
def test_a_request_of_the_wrong_shape_is_refused_by_name(server, body):   # must refuse
    code, got = call(server, body)
    assert code == 400 and "readings" not in got
    assert "message" in got["error"] and "acts" in got["error"]            # it says what to send


def test_a_body_over_the_cap_is_refused_unread_and_a_body_at_it_is_read(server):   # must refuse / must pass
    big = json.dumps({"message": "x" * (READ_BODY + 10)}).encode("utf-8")
    code, got = call(server, raw=big)
    assert code == 400 and got["error"] == "request too large"
    inside = json.dumps({"message": "Publish it. " + "x" * 30_000}).encode("utf-8")      # over MAX_CHARS, under the cap
    code, got = call(server, raw=inside)
    assert code == 200 and got["clipped"] is True and got["max_chars"] == reading.MAX_CHARS


def test_the_words_never_travel_in_an_address(server, home):   # must refuse
    before = listing(home)
    word = "MARKER-91c2-publish-it"
    for path in (f"/api/read?message={word}", "/api/read?", "/api/read;x=1", "/api/read?offer=x&message=y"):
        code, got = call(server, {"message": MARK}, path=path)
        assert code == 400 and "address" in got["error"] and word not in json.dumps(got), path
    host = f"127.0.0.1:{server.server_address[1]}"
    for path in ("/api/read", f"/api/read?message={word}"):          # and no GET reads them, with the page's header or not
        for headers in ({}, {"X-Semantext": "1", "Origin": f"http://{host}"}):
            req = urllib.request.Request(f"http://{host}{path}", headers=headers)
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=20)
            assert e.value.code in (403, 404) and word.encode() not in e.value.read()
    assert listing(home) == before


@pytest.mark.parametrize("path", ["/api/read/", "/api/READ", "/api//read", "/api/reading", "/api/read.json"])
def test_no_other_spelling_reaches_the_reader(server, path):   # must refuse
    assert call(server, {"message": "Publish it."}, path=path)[0] == 404


# ---------------------------------------------------------------- must pass: the reader's answer, and nothing written
def test_the_page_gets_the_readers_answer(server):
    code, got = call(server, {"message": "Publish the release tonight."})
    assert code == 200 and got["ok"] is True
    assert got["acts"] == ["publish"] and got["means"] == {"publish": "publish or share it"}
    r, a = got["readings"][0], got["advice"][0]
    assert (r["kind"], r["label"], r["acts"], r["time"]) == ("instruction", "INSTRUCTION", ["publish"], "tonight")
    assert (a["word"], a["rule"], a["covers"], a["bound"]) == ("ASK", "your-words-appear-to-cover-it", True, "tonight")
    assert got["clipped"] is False and got["unreadable"] is False and got["max_chars"] == reading.MAX_CHARS


def test_a_yes_binds_to_the_offer_through_the_route(server):
    code, got = call(server, {"message": "Yes", "offer": "Shall I publish the release?"})
    assert code == 200 and got["acts"] == ["publish"] and got["advice"][0]["covers"] is True      # the offer's act is asked about
    code, got = call(server, {"message": "Yes"})                                                       # control: no offer
    assert code == 200 and got["acts"] == [] and got["advice"] == []
    code, got = call(server, {"message": "Yes", "offer": "Shall I publish the release?", "acts": ["push"]})
    assert got["advice"][0]["act"] == "push" and got["advice"][0]["covers"] is False                   # only its own act


def test_a_key_in_the_words_does_not_come_back(server):
    key = "sk-" + "A1b2C3d4E5f6G7h8J9k0L1m2N3p4Q5r6"
    code, got = call(server, {"message": f"Publish it with {key}"})
    assert code == 200 and key not in json.dumps(got)
    code, got = call(server, {"message": "Yes", "offer": f"Shall I publish it with {key}?"})
    assert code == 200 and key not in json.dumps(got)


def test_letters_the_reader_cannot_vouch_for_are_said(server):
    code, got = call(server, {"message": "Publish it. Stоp."})
    assert code == 200 and got["unreadable"] is True and got["advice"][0]["covers"] is False


def test_reading_writes_nothing_anywhere_in_the_home(server, home):   # the route is a POST that changes nothing
    before = listing(home)
    for msg in ("Publish it.", "Delete the old branch.", "I'll push it myself.", MARK):
        assert call(server, {"message": msg})[0] == 200
    assert call(server, {"message": "x"}, origin="http://evil.example")[0] == 403
    assert listing(home) == before


# ---------------------------------------------------------------- the equivalence: one reader
OFFERS = [None, "Shall I publish the release?", "Shall I fix the release notes?", "Should I delete the old branch, or keep it?",
          "Want me to hold off on publishing?"]
CORPUS = sorted({*(m for m, *_ in CASES), *(m for m, *_ in ATTACK_R1),
                 "Postgres is down.", "Published it.", "Publish it, I guess.", "Publish it sometime.", "Publish it. 🛑",
                 "Publish it, wa͏it", "Publish it. Ok, internal only.", "Publish it, he said", "Yes", "Yes. Wait.",
                 "Sure, but not yet", "Great! Send the update to the team.", "Publish it now, thank you!",
                 "Publish it, but don't push.", "Not now.", "Push it. Thanks.", "", "   ", "?!",
                 "Publish it. " + "x " * 3000 + "Don't."})


def test_the_route_and_the_reader_agree_on_the_readers_own_corpus(server):
    seen = 0
    for msg in CORPUS:
        for offer in OFFERS:
            code, got = call(server, {"message": msg, **({"offer": offer} if offer else {}), "acts": list(reading.ACTS)})
            assert code == 200, (msg, offer)
            whole = reading.read(msg)
            assert got["readings"] == whole.to_dict()["readings"], (msg, offer)
            assert (got["clipped"], got["unreadable"]) == (whole.clipped, whole.unreadable), (msg, offer)
            assert [a["act"] for a in got["advice"]] == list(reading.ACTS)
            for a in got["advice"]:
                assert a == reading.advise(whole, a["act"], offer=offer).to_dict(), (msg, offer, a["act"])
                seen += 1
    assert seen > 2000                                  # the corpus really ran, in the thousands of readings


def test_the_route_names_the_same_acts_the_command_line_does(server):
    for msg in CORPUS[:60]:
        for offer in (None, "Shall I publish the release?"):
            _, got = call(server, {"message": msg, **({"offer": offer} if offer else {})})
            assert got == {"ok": True, **reading.report(msg, offer=offer)}, (msg, offer)


def test_the_command_line_prints_what_the_route_sends(server, home, capsys):
    for msg, offer in [("Publish the release tonight.", None), ("Yes", "Shall I publish the release?"),
                       ("Looks great! I'll push it myself next week.", None), ("Can you publish it?", None),
                       ("hold off on publishing but don't stop", None), ("Fix the release notes.", None)]:
        _, got = call(server, {"message": msg, **({"offer": offer} if offer else {})})
        capsys.readouterr()
        assert cli.main(["--home", str(home), "read", *(["--offer", offer] if offer else []), msg]) == 0
        out = capsys.readouterr().out
        for a in got["advice"]:
            q = f'  "{a["quote"]}"' if a["quote"] else ""
            assert f"{a['act']}: {a['word']} ({a['rule']}) {a['why']}{q}" in out, (msg, a)
        for r in got["readings"]:
            extra = "".join([f" [{', '.join(r['acts'])}]" if r["acts"] else "", f' ("{r["time"]}")' if r["time"] else ""])
            assert f"  {r['label']}{extra}: {r['clause']}" in out, (msg, r)


def test_the_equivalence_can_fail():   # must refuse: a changed word in the advice is seen by the same comparison
    whole = reading.read("Publish the release tonight.")
    good = reading.advise(whole, "publish").to_dict()
    assert good == reading.advise(whole, "publish").to_dict()
    assert {**good, "covers": False} != good and {**good, "word": "ALLOWED"} != good
    assert reading.advise(reading.read("Can you publish it?"), "publish").to_dict() != good


# ---------------------------------------------------------------- the page: Try a message, drawn from the real reader
EXPLAIN = ('{ agent: "helper", words: "own", basis: "text", environment: "default", form: "full", layers: [], bytes: 1, '
           'left_out: 0, answers: [], waiting: [], reading: { readings: [], decisions: [] }, text: "card" }')


def answers(*pairs):
    """The real reader's answers by 'message|offer', as JSON for a stub; a pair may name a failure instead."""
    out = {}
    for msg, offer in pairs:
        out[f"{msg}|{offer or ''}"] = {"ok": True, **reading.report(msg, offer=offer)}
    return json.dumps(out, ensure_ascii=False)


def box(by, js, explain_ok=True):
    """The Try a message view, fed by a stub fetch: /api/read answers from `by`, /api/explain a fixed record."""
    return WORLD + """
const sent = [];
const BY = %s;
globalThis.fetch = (path, opts) => {
  const b = opts && opts.body ? JSON.parse(opts.body) : null;
  sent.push([String(path), b]);
  if (path === "/api/read") {
    const r = BY[b.message + "|" + (b.offer || "")];
    return Promise.resolve(r && r.fail ? { ok: false, status: 500, statusText: "x", json: () => Promise.resolve({ error: r.fail }) }
      : { ok: true, status: 200, json: () => Promise.resolve(r) });
  }
  if (path === "/api/explain") return Promise.resolve(%s ? { ok: true, status: 200, json: () => Promise.resolve(%s) }
    : { ok: false, status: 500, statusText: "x", json: () => Promise.resolve({ error: "explain failed" }) });
  return new Promise(() => {});
};
const flow = () => document.getElementById("testFlow").textContent;
""" % (by, "true" if explain_ok else "false", EXPLAIN) + js


@needs_node
def test_try_a_message_shows_each_clause_as_a_chip_and_the_advice_for_each_act():
    msg = "Publish the release tonight. Fix the release notes."
    got = run(box(answers((msg, None)), f"""
return moved.tryMessage({json.dumps(msg)}, "", "helper", "").then(() => {{
  const chips = document.getElementById("testFlow").all((e) => e.className.includes("chip")).map((e) => e.textContent);
  report({{ text: flow(), chips, sent }});
}});
"""))
    t = got["text"]
    assert "Clause by clause: what it asks for, act by act" in t and "The quick reading: what kind of message this is" in t                                # both readings, side by side
    assert {"INSTRUCTION", "publish", "edit", "“tonight”"} <= set(got["chips"])
    # every word of the advice is the reader's own, drawn as it came; here "release notes" is a mention of publishing, so
    # publish only asks, and edit (not a material act) is allowed
    want = {a["act"]: a for a in reading.report(msg)["advice"]}
    assert want["publish"]["covers"] is False and want["edit"]["word"] == "ALLOWED"
    for a in want.values():
        assert f"The rule: {a['rule']}" in t and a["why"] in t, a
    assert "appear to say go" not in t and t.count("ALLOWED") == 1                          # only edit is allowed
    assert [s[0] for s in got["sent"] if s[1]] == ["/api/read", "/api/explain"]
    assert got["sent"][0][1] == {"message": msg}                                            # no offer sent when there is none


@needs_node
def test_an_ask_whose_words_appear_to_cover_the_act_is_shown_as_confirm():
    msg = "Publish the release tonight."
    got = run(box(answers((msg, None)), f"return moved.tryMessage({json.dumps(msg)}, '', 'helper', '').then(() => report(flow()));"))
    assert "your words appear to say go: confirm (within “tonight”)" in got
    assert "The rule: your-words-appear-to-cover-it" in got and "ASK" in got
    assert "ALLOWED" not in got and "BLOCKED" not in got                                    # never shown as a go


@needs_node
def test_the_offer_goes_with_the_message_and_a_yes_covers_only_the_offered_act():
    offer = "Shall I publish the release?"
    got = run(box(answers(("Yes", offer)), f"""
return moved.tryMessage("Yes", "", "helper", {json.dumps(offer)}).then(() => report({{ text: flow(), sent }}));
"""))
    assert got["sent"][0][1] == {"message": "Yes", "offer": offer}
    assert "publish" in got["text"] and "your words appear to say go: confirm" in got["text"]
    assert "ALLOWED" not in got["text"]                                                     # a material act is never shown allowed


@needs_node
@pytest.mark.parametrize("msg,says,never", [
    ("Can you publish the release tonight?", "You mentioned it as question, which is not a go.", "appear to say go"),
    ("Looks great! I'll push it myself next week.", "You said you will do this yourself", "appear to say go"),
    ("hold off on publishing but don't stop", "Held.", "appear to say go"),
    ("If the tests pass, publish it.", "You mentioned it as condition, which is not a go.", "appear to say go"),
    ("Push it tomorrow.", "later time", "appear to say go"),
])
def test_a_message_that_is_not_a_go_is_never_drawn_as_one(msg, says, never):   # must refuse
    got = run(box(answers((msg, None)), f"""
return moved.tryMessage({json.dumps(msg)}, "", "helper", "").then(() => report(flow()));
"""))
    assert says in got and never not in got and "ALLOWED" not in got.replace("ALLOWED:", "")


@needs_node
def test_the_blocked_word_is_drawn():
    msg = "Looks great! I'll push it myself next week."
    got = run(box(answers((msg, None)), f"return moved.tryMessage({json.dumps(msg)}, '', 'helper', '').then(() => report(flow()));"))
    assert "BLOCKED" in got and "owner-reserved-action" in got and "YOURS TO DO" in got


@needs_node
def test_a_message_naming_no_act_says_there_is_nothing_to_advise_on():
    got = run(box(answers(("Hello there", None)), "return moved.tryMessage('Hello there', '', 'helper', '').then(() => report(flow()));"))
    assert "The words name no act, so there is nothing to advise on." in got and "NOTE" in got


@needs_node
def test_the_readers_failure_is_said_and_the_quick_reading_still_shows():   # must refuse: no reading made up
    by = json.dumps({"Publish it.|": {"fail": "request too large"}})
    got = run(box(by, "return moved.tryMessage('Publish it.', '', 'helper', '').then(() => report(flow()));"))
    assert "Could not read it clause by clause: request too large. No reading is shown." in got
    assert "The quick reading: what kind of message this is" in got and "INSTRUCTION" not in got


@needs_node
def test_the_quick_readings_failure_is_said_and_the_clause_reading_still_shows():   # the two fail apart
    got = run(box(answers(("Publish it.", None)), """
let toasted = null;
return moved.tryMessage('Publish it.', '', 'helper', '').then(() => report({ text: flow(), test: moved.S.test }));
""", explain_ok=False))
    assert got["test"] is None and "The quick reading" not in got["text"]                      # not left as a stale one
    assert "Clause by clause" in got["text"] and "INSTRUCTION" in got["text"]


@needs_node
def test_it_says_reading_while_the_reader_has_not_answered():   # must refuse: never an empty reading
    got = run(WORLD + """
globalThis.fetch = () => new Promise(() => {});
moved.tryMessage("Publish it.", "", "helper", "");
report(document.getElementById("testFlow").textContent);
""")
    assert "Clause by clause" in got and "Reading…" in got and "INSTRUCTION" not in got


@needs_node
def test_a_slower_older_try_never_replaces_a_newer_one():   # must refuse
    old, new = "Delete the old branch.", "Why is the build failing?"
    got = run(WORLD + f"""
const BY = {answers((old, None), (new, None))};
const wait = {{}};
globalThis.fetch = (path, opts) => {{
  const b = opts && opts.body ? JSON.parse(opts.body) : null;
  if (path === "/api/read") return new Promise((go) => {{ wait[b.message] = () => go({{ ok: true, status: 200, json: () => Promise.resolve(BY[b.message + "|"]) }}); }});
  if (path === "/api/explain") return Promise.resolve({{ ok: true, status: 200, json: () => Promise.resolve({EXPLAIN}) }});
  return new Promise(() => {{}});
}};
const ticks = () => {{ let t = Promise.resolve(); for (let i = 0; i < 40; i++) t = t.then(() => null); return t; }};
const first = moved.tryMessage({json.dumps(old)}, "", "helper", "");
const second = moved.tryMessage({json.dumps(new)}, "", "helper", "");
return ticks().then(() => {{ wait[{json.dumps(new)}](); return second; }})
  .then(() => {{ wait[{json.dumps(old)}](); return first; }})
  .then(() => report(document.getElementById("testFlow").textContent));
""")
    assert "QUESTION" in got and "INSTRUCTION" not in got


@needs_node
def test_the_try_form_has_one_optional_offer_box_and_the_view_draws():
    got = run(WORLD + """
const view = moved.VIEWS.test();
const offer = view.all((e) => e.getAttribute("name") === "offer");
report({ n: offer.length, tag: offer[0].tagName, label: offer[0].getAttribute("aria-label"), required: offer[0].hasAttribute("required"),
         text: view.textContent });
""")
    assert got["n"] == 1 and got["tag"] == "INPUT" and not got["required"]
    assert "last offer" in got["label"] and "Try a message" in got["text"] and "undefined" not in got["text"]


@needs_node
def test_the_try_a_message_view_draws_with_the_reader_state_in_every_shape():   # no name left behind, no "undefined"
    got = run(WORLD + """
const shapes = [undefined, { busy: true, message: "m" }, { err: "no", message: "m" },
  { message: "m", offer: "", data: { ok: true, readings: [], advice: [], acts: [], means: {}, clipped: true, unreadable: true, max_chars: 20000 } }];
const out = [];
for (const s of shapes) { moved.S.reader = s; const el = document.createElement("div"); el.append(...[moved.testFlow()].flat(Infinity).filter(Boolean)); out.push(el.textContent); }
report(out);
""")
    assert all("undefined" not in t and "[object" not in t for t in got)
    assert "Reading…" in got[1] and "Could not read it clause by clause: no." in got[2]
    assert "Nothing to read: the message is empty." in got[3] and "Read up to 20000 characters" in got[3] and "Latin script" in got[3]
