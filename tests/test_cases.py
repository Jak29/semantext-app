"""Corrections kept as tests: the message an AI misread, kept beside the rule taught from it, and re-checked whenever
the rules change."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from semantext.cli import main
from semantext.server import make_server, metrics
from semantext.store import Refused, Store

MISREAD = "Could you tidy the README before the release?"
RULE = "When I say tidy, I mean format only: no rewording."


def run(capsys, *args):
    code = main(list(args))
    return code, capsys.readouterr().out


@pytest.fixture
def page(store):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None):
        h = {"Content-Type": "application/json", "X-Semantext": "1", "Origin": base}
        req = urllib.request.Request(base + path, method="POST" if body is not None else "GET", headers=h,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    srv.shutdown()
    srv.server_close()


def test_a_correction_with_its_misread_message_is_kept_as_the_rules_test(store):
    rid = store.learn("default", RULE, misread=MISREAD)
    again = store.learn("default", "Keep my voice.", misread="Rewrite the intro, maybe?")
    store.learn("default", "Answer in one line first.")                  # no message given: no test
    tests = store.load("default")["tests"]
    assert [t["case"] for t in tests] == ["default.case-1", "default.case-2"]
    t = tests[0]
    assert (t["message"], t["correction"], t["rules"], t["source"], t["grounded"]) == (MISREAD, RULE, [rid], "person",
                                                                                       "EXPLICIT")
    assert tests[1]["rules"] == [again] and t["at"]


@pytest.mark.parametrize("misread", ["x" * 1001, "here: my password is hunter2!", "ghp_" + "a1" * 15,
                                     "use a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8 for it"])
def test_a_misread_message_too_long_or_holding_a_key_is_refused_and_nothing_is_written(store, misread):
    before = store.path("default").read_bytes()
    with pytest.raises(Refused):
        store.learn("default", RULE, misread=misread)
    assert store.path("default").read_bytes() == before


def test_a_test_is_covered_while_every_rule_it_needs_is_on(store):
    rid = store.learn("default", RULE, misread=MISREAD)
    assert [(t["covered"], t["missing"]) for t in store.cases("default")] == [(True, [])]
    store.toggle("default", rid)
    assert [(t["covered"], t["missing"]) for t in store.cases("default")] == [(False, [rid])]
    assert [t["case"] for t in store.depends_on("default", rid)] == ["default.case-1"]
    store.toggle("default", rid)
    store.undo("default", rid)                                              # removed: kept in the file, off the card
    assert store.cases("default")[0]["covered"] is False


def test_an_agents_own_rule_covers_its_test(store):
    rid = store.learn("default", "Cite the file and the line.", agent="reviewer", misread="Is the parser safe?")
    [t] = store.cases("default")
    assert t["rules"] == [rid] and t["covered"] is True


def test_undo_last_takes_the_test_off_with_its_rule(store):
    store.learn("default", RULE, misread=MISREAD)
    store.undo_last("default")
    assert store.cases("default") == []


@pytest.mark.parametrize("tests,why", [
    ("tests: a list of nothing", "'tests' must be a list"),
    ("tests:\n- case: x\n  rules: [a]", "test 1 has no message"),
    ("tests:\n- message: hi\n  rules: a", "test 1's rules must be a list"),
])
def test_a_hand_edited_tests_list_that_is_wrong_is_refused_in_one_line(store, tests, why):
    text = store.source("default").split("tests:")[0] + tests + "\n"
    with pytest.raises(Refused, match=why):
        store.write_source("default", text)


def test_the_card_says_how_many_corrections_are_kept_as_tests(store):
    assert "kept as tests" not in store.card("default")
    store.learn("default", RULE, misread=MISREAD)
    assert "(1 of the user's corrections is kept as tests for these rules" in store.card("default")
    store.learn("default", "Keep my voice.", misread="Rewrite the intro.")
    assert "(2 of the user's corrections are kept as tests" in store.card("default")
    assert "kept as tests" not in store.card("default", form="relay")   # the short card carries the floor only


# ---------------------------------------------------------------- the command line
def test_teach_keeps_the_misread_message_and_cases_lists_and_exports_them(capsys, home, tmp_path):
    code, out = run(capsys, "teach", *RULE.split(), "--misread", MISREAD)
    assert code == 0 and "kept as its test" in out
    code, out = run(capsys, "cases")
    assert code == 0 and "1 correction kept as tests, 1 covered" in out and "default.learned-1" in out and "[covered]" in out
    code, out = run(capsys, "toggle", "default.learned-1")
    assert "Uncovered: your correction of" in out
    code, out = run(capsys, "cases")
    assert "UNCOVERED: default.learned-1" in out
    path = tmp_path / "cases.jsonl"
    code, out = run(capsys, "cases", "--export", str(path))
    [case] = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    assert code == 0 and case["message"] == MISREAD and case["rules"] == ["default.learned-1"]
    assert not {"case", "covered", "missing"} & set(case)                   # the back-test's case fields only


def test_an_agents_shell_cannot_keep_a_misread_message(capsys, home, monkeypatch, tmp_path):
    (tmp_path / "proj" / ".git").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "proj")
    monkeypatch.setenv("CLAUDECODE", "1")
    code = main(["teach", "Keep", "it", "short.", "--misread", "Write me a novel."])
    assert code != 0 and "only from your own terminal or the page" in capsys.readouterr().err
    assert Store.open(home).load("default").get("tests") in (None, [])
    assert not any(str(x.get("id", "")).startswith("default.learned") for x in Store.open(home).load("default")["entries"])


# ---------------------------------------------------------------- the page
def test_the_page_keeps_a_test_and_says_what_switching_its_rule_off_uncovers(store, page):
    status, body = page("/api/learn", {"name": "default", "words": RULE, "misread": MISREAD})
    rid = body["id"]
    assert status == 200 and store.cases("default")[0]["rules"] == [rid]
    status, prof = page("/api/profile?name=default")
    assert status == 200 and prof["tests"][0]["covered"] is True and prof["tests"][0]["message"] == MISREAD
    status, off = page("/api/toggle", {"name": "default", "id": rid})
    assert off["enabled"] is False and [t["case"] for t in off["uncovered"]] == ["default.case-1"]
    status, on = page("/api/toggle", {"name": "default", "id": rid})
    assert on["enabled"] is True and on["uncovered"] == []
    status, gone = page("/api/undo", {"name": "default", "id": rid})
    assert [t["case"] for t in gone["uncovered"]] == ["default.case-1"]
    m = metrics(store)["rules"]
    assert (m["cases"], m["covered"]) == (1, 0)
