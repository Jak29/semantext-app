"""The page's Agents panel: the agents, their own rules, and the user's acts of naming and binding, on their own page."""
import json
import threading
import urllib.error
import urllib.request

import pytest

from semantext import paths
from semantext.agents import Agents
from semantext.server import make_server


@pytest.fixture
def page(store):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None, origin=True):
        headers = {"Content-Type": "application/json", "X-Semantext": "1"}
        if origin:
            headers["Origin"] = base
        req = urllib.request.Request(base + path, method="POST" if body is not None else "GET", headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    srv.shutdown()
    srv.server_close()


def test_the_panel_lists_the_agents_with_their_own_rules(store, page):
    store.learn("default", "Cite the file and the line for every point.", agent="reviewer")
    status, body = page("/api/agents")
    reviewer = next(a for a in body["agents"] if a["name"] == "reviewer")
    assert status == 200 and body["active"] == "default"
    assert [r["statement"] for r in reviewer["rules"]] == ["Cite the file and the line for every point."]


def test_the_user_binds_names_and_teaches_an_agent_on_the_page(store, page, tmp_path):
    folder = tmp_path / "review"
    folder.mkdir()
    assert page("/api/agent-bind", {"agent": "reviewer", "folder": str(folder)})[0] == 200
    assert Agents(store.root).bound(folder) == "reviewer"
    assert page("/api/agent-name", {"agent": "reviewer", "label": "The Reviewer"})[0] == 200
    assert page("/api/learn", {"name": "default", "words": "Cite every line.", "agent": "reviewer"})[0] == 200
    agent = next(a for a in page("/api/agents")[1]["agents"] if a["name"] == "reviewer")
    assert agent["label"] == "The Reviewer" and agent["folders"] == [str(folder.resolve())]
    assert [r["statement"] for r in agent["rules"]] == ["Cite every line."]
    assert page("/api/agent-unbind", {"folder": str(folder)})[1]["unbound"] is True
    assert Agents(store.root).bound(folder) is None


def test_a_bound_agent_shows_the_rules_it_took_over(store, page, tmp_path):
    folder = tmp_path / "review"
    (folder / ".git").mkdir(parents=True)
    assert Agents(store.root).project_name(folder) == "review"               # seen there before it had a name
    store.learn("default", "Cite every line.", agent="claude-code@review")
    page("/api/agent-bind", {"agent": "reviewer", "folder": str(folder)})
    agents = {a["name"]: a for a in page("/api/agents")[1]["agents"]}
    assert [(c["from"], [r["statement"] for r in c["rules"]]) for c in agents["reviewer"]["carried"]] == [
        ("claude-code@review", ["Cite every line."])]
    assert agents["claude-code@review"]["now"] == "reviewer" and agents["reviewer"]["now"] == ""


def test_only_the_page_itself_may_bind(store, page, tmp_path):
    folder = tmp_path / "review"
    folder.mkdir()
    status, _ = page("/api/agent-bind", {"agent": "reviewer", "folder": str(folder)}, origin=False)
    assert status == 403 and Agents(store.root).bound(folder) is None


def test_a_change_that_names_no_page_is_refused(store, page):
    """A local process, not the page, cannot change the rules through the page's address."""
    status, _ = page("/api/learn", {"name": "default", "words": "Injected by a script"}, origin=False)
    assert status == 403 and "Injected by a script" not in store.card("default")
    assert page("/api/learn", {"name": "default", "words": "From the page"})[0] == 200


def test_the_page_has_the_agents_panel():
    text = (paths.static_dir() / "index.html").read_text(encoding="utf-8")
    assert '"data-part": "agents"' in text and "agents: () =>" in text and '"/api/agent-bind"' in text
