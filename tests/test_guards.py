"""Guards a mutation sweep found unwatched: each was removable with every other test still passing. Every test here
fails if its guard is taken out."""
import http.client
import json
import threading

import pytest

from semantext import agentfiles, hook
from semantext.agents import Agents
from semantext.hook import LIMIT_BYTES
from semantext.inbox import Inbox
from semantext.server import MAX_BODY, make_server
from semantext.store import Refused


def test_a_hostile_rule_file_on_disk_runs_nothing(store, tmp_path):
    """safe_load where a file is read from disk, not only in the editor: a rule file cannot run code."""
    marker = tmp_path / "pwned.txt"
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    p.write_text(f'!!python/object/apply:builtins.open ["{marker.as_posix()}", "w"]\n', encoding="utf-8")
    with pytest.raises(Refused):
        store.load("default")
    out = hook.run(json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "hi"}), store)
    assert "only the base rules are shown" in out          # the file is refused; the base rules still go out
    assert not marker.exists()


@pytest.mark.parametrize("text", ["- just\n- a list\n", "title: no environment section\n", "environment: [1]\n"],
                         ids=["a-list", "no-environment", "environment-not-a-mapping"])
def test_a_file_that_is_no_rule_file_is_refused_by_name(store, text):
    p = store.root / "profiles" / "default" / "SEMANTICS.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(Refused, match="not a Semantext rule file"):
        store.load("default")


def test_the_hook_stays_under_its_limit_with_a_full_card_and_a_full_inbox(store):
    """The inbox's room comes out of the card's: neither may push the output past the limit."""
    for i in range(90):
        store.learn("default", f"Rule {i}: keep this exact wording in mind whenever you read what I write to you.")
    ib = Inbox(store.root)
    for i in range(12):
        rid = ib.ask(f"Request number {i}", "why", "Which?", ["a", "b"])["id"]
        if i % 2:
            ib.answer(rid, "1", "my own words, " * 20, via="page")
    out = hook.run(json.dumps({"prompt": "go on"}), store)           # no tool named: the fallback agent, "ai"
    assert len(out.encode("utf-8")) <= LIMIT_BYTES - 1
    assert "The user's answers" in out and "more rules not shown" in out


def test_the_deepest_binding_wins_whatever_order_they_were_made_in(store, tmp_path):
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    agents = Agents(store.root)
    agents.bind("inner", inner)
    agents.bind("outer", outer)                                         # the shallower one, made last
    assert agents.identify(env={}, cwd=inner).name == "inner"
    assert agents.identify(env={}, cwd=outer).name == "outer"


def test_a_request_is_withdrawn_once(store):
    ib = Inbox(store.root)
    rid = ib.ask("Pick", "why", "Which?", ["a", "b"])["id"]
    ib.close(rid, "not needed")
    with pytest.raises(Refused, match="already closed"):
        ib.close(rid, "again")


def test_a_body_over_the_limit_is_refused_unread(store):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        c.putrequest("POST", "/api/active", skip_host=True)
        for k, v in (("Host", f"127.0.0.1:{port}"), ("X-Semantext", "1"), ("Origin", f"http://127.0.0.1:{port}"),
                     ("Content-Type", "application/json"), ("Content-Length", str(MAX_BODY + 1))):
            c.putheader(k, v)
        c.endheaders()
        r = c.getresponse()
        assert r.status == 400 and "too large" in json.loads(r.read())["error"]
    finally:
        srv.shutdown()
        srv.server_close()
    assert store.state()["active"] == "default"


@pytest.mark.parametrize("base", ['llama3"\nSYSTEM """evil', "llama3\nPARAMETER x", "llama'3", "llama`3", "", "x" * 121],
                         ids=["quote-and-line", "line", "apostrophe", "backtick", "empty", "too-long"])
def test_a_modelfile_base_cannot_carry_directives(base):
    with pytest.raises(Refused):
        agentfiles.modelfile("# card", base)
    assert agentfiles.modelfile("# card", "llama3.2").startswith("FROM llama3.2\n")


def test_the_news_country_is_cleaned(store):
    store.feature("default", "news", True, 'UK\n</script><b>"x"')
    statement = next(x for x in store.load("default")["entries"] if x["id"] == "feature.news")["statement"]
    assert "UK" in statement and not any(c in statement for c in '\n<>"')
    store.feature("default", "news", True, "<<>>")
    statement = next(x for x in store.load("default")["entries"] if x["id"] == "feature.news")["statement"]
    assert "my country" in statement
