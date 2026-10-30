"""The Plug-ins tab (semantext/pluginpage.py): what it shows, the changes the page may make, the guards on them, the
change log and rolling back. Each rule has both arms: what must pass and what must be refused. The plug-ins are
defined in tests/plugin_fakes.py and offered through a stand-in for importlib.metadata.entry_points; nothing is
installed, and the person's own files are never touched (every home and sources file is the test's)."""
from __future__ import annotations

import importlib.metadata
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from semantext import outside, plugincmd, pluginpage, registry
from semantext.sources import view
from plugin_fakes import DECLARED, Point, Tickets, package

KEY = "source.tickets"


@pytest.fixture
def world(home, tmp_path, monkeypatch):
    """A home, a sources file of the test's (closures named, one setting set), and the installed packages."""
    home.mkdir(parents=True, exist_ok=True)
    points = []
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    cfg = tmp_path / "sources.json"
    old = tmp_path / "tickets"
    old.mkdir()
    write_cfg(cfg, {"closed": [], "tickets": str(old), "project": "alpha"})
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    Tickets.calls = 0

    class W:
        pass
    w = W()
    w.home, w.cfg, w.points, w.old, w.tmp = home, cfg, points, old, tmp_path

    def offer(key=KEY, make=Tickets, declared=DECLARED, on=False, name="semantext-jira", version="0.3",
              module="semantext_jira"):
        dist = package(tmp_path / f"site-{name}", name=name, version=version, module=module, declared=declared)
        p = Point(key, make, dist, value=f"{module}.reader:SOURCE")
        points.append(p)
        if on:
            rows, _ = registry.enabled(home)
            rows[key] = {"origin": name, "version": version, "at": "2026-10-28T00:00:00Z"}
            registry.write_enabled(rows, home)
        return p
    w.offer = offer
    return w


def write_cfg(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def cfg(w) -> dict:
    return json.loads(w.cfg.read_text(encoding="utf-8"))


def row(key=KEY, home=None):
    got = view.answer("plugins", home=home)
    return next(r for r in got["plugins"] if r["key"] == key), got


# ---- what the tab shows ----------------------------------------------------------------------------------------------
def test_an_installed_plug_in_is_shown_and_never_loaded(world):   # must refuse: installed is not on, nothing imported
    p = world.offer()
    r, got = row(home=world.home)
    assert r["trust"] == "installed, not on" and r["on"] is False and r["loaded"] is False
    assert (r["package"], r["version"], r["builtin"]) == ("semantext-jira", "0.3", False)
    assert p.loads == 0 and Tickets.calls == 0
    assert r["on_command"].startswith("semantext --home") and r["on_command"].endswith(f"plugins enable {KEY}")
    assert r["health"]["words"] == "not on, so never called" and r["health"]["last"] is None
    # what it may read is shown before it is on: its own words, and its path settings as they stand
    assert "the tickets file you name, and nothing else" in r["reads"]
    assert f"Tickets file: {world.old}" in r["reads"]
    assert [(s["key"], s["type"], s["set"]) for s in r["settings"]] == [
        ("tickets", "path", True), ("project", "text", True), ("extra", "paths", False)]
    assert r["can"] == {"off": False, "change": True}


def test_an_enabled_plug_in_is_on_and_drawing_the_tab_calls_none(world):   # must pass, and must refuse a call
    p = world.offer(on=True)
    r, _ = row(home=world.home)
    assert r["trust"] == "on" and r["loaded"] is True and p.loads == 1
    assert Tickets.calls == 0 and r["health"]["words"] == "not called yet"
    view.answer("waiting", home=world.home)          # another place reads it, in the worker
    assert Tickets.calls == 1
    r, _ = row(home=world.home)
    assert Tickets.calls == 1 and r["health"]["last"]["outcome"] == "answered"
    assert r["health"]["words"].startswith("its last read answered") and r["health"]["loading"]["call"] == "signature"
    assert r["on_command"] is None and r["can"]["off"] is True


def test_a_changed_version_is_on_but_not_loaded(world):   # must refuse to call it loaded
    world.offer(on=True)
    world.points[0].dist.version = "0.4"
    r, _ = row(home=world.home)
    assert r["trust"] == "on, not loaded" and "turn it on again" in r["health"]["words"]


def test_a_plug_in_with_no_declaration_says_so_and_gets_no_form(world):   # must refuse to make a form up
    world.offer(declared=None, on=True)
    r, _ = row(home=world.home)
    assert r["declared"] is False and r["settings"] == [] and r["can"]["change"] is False
    assert any("declares nothing it reads" in x for x in r["reads"])
    assert [u["key"] for u in r["undeclared"]] == ["tickets", "project", "extra"]   # its keys, shown, not changeable


def test_the_built_ins_are_shown_as_built_in_and_always_on(world):
    got = view.answer("plugins", home=world.home)
    built = [r for r in got["plugins"] if r["builtin"]]
    assert {r["key"] for r in built} >= {"source.waiting", "place.plugins", "checker.runs"}
    assert all(r["trust"] == "built-in" and r["can"] == {"off": False, "change": False} for r in built)


def test_the_tab_carries_the_frame_and_reads_no_outside_source(world):
    world.offer(on=True)
    got = view.answer("plugins", home=world.home)
    assert got["place"] == "plugins" and "problems" in got["frame"] and Tickets.calls == 0
    assert "tickets" not in got["frame"]["off"]   # it was not read, so it is not said to be off either


# ---- the page's acts -----------------------------------------------------------------------------------------------
def test_turning_off_is_made_and_recorded(world):   # must pass
    world.offer(on=True)
    made = pluginpage.turn_off(world.home, KEY)
    assert KEY not in registry.enabled(world.home)[0]
    assert (made["who"], made["what"], made["field"], made["after"]) == ("page", "off", "on", None)
    assert made["before"]["origin"] == "semantext-jira"


@pytest.mark.parametrize("key, said", [("source.waiting", "always on"), (KEY, "is not on"), ("tickets", "<kind>.<name>")])
def test_turning_off_what_cannot_be_is_refused(world, key, said):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match=said):
        pluginpage.turn_off(world.home, key)


def test_turning_on_from_the_page_is_never_made(world):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.turn_on(world.home, KEY)
    assert e.value.command.endswith(f"plugins enable {KEY}") and registry.enabled(world.home)[0] == {}


def apply(home, key, given) -> dict:
    """A settings change as it is made now: proposed on the page, applied at the console (the made record)."""
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(home, key, given)
    return pluginpage.confirm(home, e.value.proposal)


def apply_back(home, n) -> dict:
    """A settings rollback as it is made now: proposed on the page, applied at the console."""
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.roll_back(home, n)
    return pluginpage.confirm(home, e.value.proposal)


def proposed_label(world, given) -> str:
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, given)
    return next(r for r in pluginpage.changes(world.home)[0] if r["n"] == e.value.proposal)["label"]


@pytest.mark.parametrize("given", [{"project": "beta"}, {"tickets": "INNER"}, {"tickets": "SIBLING"},
                                   {"extra": ["NEW"]}, {"tickets": None}, {"project": None}])
def test_the_page_never_writes_a_setting(world, given):   # must refuse, whatever the change
    world.offer()
    sub = {"INNER": str(world.old / "inner"), "SIBLING": str(world.tmp / "elsewhere")}
    given = {k: ([str(world.tmp / "x")] if v == ["NEW"] else sub.get(v, v) if isinstance(v, str) else v)
             for k, v in given.items()}
    before = world.cfg.read_bytes()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, given)
    assert world.cfg.read_bytes() == before and "proposed, not changed" in str(e.value)
    n = e.value.proposal
    assert e.value.command.endswith(f"plugins confirm {n}")
    recs, _ = pluginpage.changes(world.home)
    assert recs[-1]["what"] == "proposed" and recs[-1]["n"] == n and recs[-1]["after"]["values"] == \
        {k: v for k, v in given.items() if v is not None}


def test_a_proposal_applied_at_the_console_changes_only_its_keys(world):   # must pass
    world.offer()
    made = apply(world.home, KEY, {"project": "beta"})
    got = cfg(world)
    assert got["project"] == "beta" and got["closed"] == [] and got["tickets"] == str(world.old)
    assert made["before"] == {"values": {"project": "alpha"}, "absent": []}
    assert made["after"] == {"values": {"project": "beta"}, "absent": []} and made["who"] == "terminal"


def test_the_same_change_sent_again_is_the_same_proposal(world):   # must refuse to grow the log for nothing
    world.offer()
    given = {"tickets": str(world.tmp / "elsewhere")}
    ns = []
    for _ in range(3):
        with pytest.raises(pluginpage.AtTheTerminal) as e:
            pluginpage.change(world.home, KEY, given)
        ns.append(e.value.proposal)
    assert ns[0] == ns[1] == ns[2] and len(pluginpage.changes(world.home)[0]) == 1
    with pytest.raises(pluginpage.AtTheTerminal) as e:   # must pass: another change is another proposal
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "further")})
    assert e.value.proposal == ns[0] + 1


# ---- the label: for the person to read, deciding nothing -------------------------------------------------------------
@pytest.mark.parametrize("given, want", [
    ({"tickets": "SIBLING"}, "widens"), ({"tickets": "INNER"}, "narrows"), ({"project": "beta"}, "narrows"),
    ({"tickets": None}, "widens"),            # no default declared: it may fall back to anything
    ({"project": None}, "narrows"),           # declared default "all", a text
    ({"extra": ["NEW"]}, "widens"),           # a folder where there was none
])
def test_a_proposal_is_labelled_by_the_declared_types(world, given, want):
    world.offer()
    sub = {"INNER": str(world.old / "inner"), "SIBLING": str(world.tmp / "elsewhere")}
    given = {k: ([str(world.tmp / "x")] if v == ["NEW"] else sub.get(v, v) if isinstance(v, str) else v)
             for k, v in given.items()}
    assert proposed_label(world, given) == want


def test_a_label_names_another_plug_in_it_widens_for(world):
    world.offer()
    other = {"plugins": {"source.other": {"settings": [{"key": "project", "type": "path"}]}}}
    world.offer("source.other", declared=other, name="semantext-other", module="semantext_other")
    with pytest.raises(pluginpage.AtTheTerminal):
        pluginpage.change(world.home, KEY, {"project": str(world.tmp / "beta")})
    r = pluginpage.changes(world.home)[0][-1]
    assert r["label"] == "widens" and any("wider for source.other" in x for x in r["reasons"])


def test_a_setting_declared_to_widen_is_labelled_so(world):
    declared = json.loads(json.dumps(DECLARED))
    declared["plugins"][KEY]["settings"][1]["widens"] = True
    world.offer(declared=declared)
    assert proposed_label(world, {"project": "beta"}) == "widens"


def test_a_link_inside_the_old_folder_that_leads_out_is_labelled_widens(world):
    out = world.tmp / "outside"
    out.mkdir()
    link = world.old / "link"
    try:
        os.symlink(out, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a link")
    world.offer()
    assert proposed_label(world, {"tickets": str(link)}) == "widens"


@pytest.mark.parametrize("given, said", [
    ({"tickets": 3}, "is a text"),
    ({"tickets": "relative/path"}, "full path"),
    ({"project": "a\x1bb"}, "control"),
    ({"project": "x" * 1001}, "at most"),
    ({"project": "x\ud800y"}, "lone surrogate"),
    ({"extra": "not a list"}, "list of 1 to"),
    ({"extra": []}, "list of 1 to"),
    ({"extra": ["relative"]}, "full path"),
    ({"nope": "x"}, "declares no setting"),
    ({"closed": []}, "declares no setting"),
    ({}, "at least one"),
    ("project=beta", "at least one"),
    ({"project": "alpha"}, "nothing would change"),
])
def test_a_value_not_of_the_declared_schema_is_refused(world, given, said):   # must refuse
    world.offer()
    before = world.cfg.read_bytes()
    with pytest.raises(pluginpage.Refused, match=said) as e:
        pluginpage.change(world.home, KEY, given)
    assert not isinstance(e.value, pluginpage.AtTheTerminal)   # refused, not even proposed
    assert world.cfg.read_bytes() == before and not pluginpage.log_file(world.home).exists()


def test_a_built_in_or_undeclared_plug_in_has_no_settings_changed(world):   # must refuse
    world.offer(declared=None)
    for key in ("source.waiting", KEY):
        with pytest.raises(pluginpage.Refused):
            pluginpage.change(world.home, key, {"project": "beta"})


def test_an_unreadable_sources_file_is_never_written_over(world):   # must refuse
    world.offer()
    world.cfg.write_text('{"project": "a", "project": "b"}', encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="cannot be read"):
        pluginpage.change(world.home, KEY, {"project": "c"})
    assert world.cfg.read_text(encoding="utf-8") == '{"project": "a", "project": "b"}'


# ---- rolling back --------------------------------------------------------------------------------------------------
def test_a_settings_rollback_from_the_page_is_a_proposal(world):   # must refuse to write it
    world.offer()
    a = apply(world.home, KEY, {"project": "beta"})
    before = world.cfg.read_bytes()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.roll_back(world.home, a["n"])
    assert world.cfg.read_bytes() == before and e.value.command.endswith(f"plugins confirm {e.value.proposal}")


def test_a_rollback_applied_restores_exactly_and_is_recorded(world):   # must pass
    world.offer()
    before = world.cfg.read_bytes()
    a = apply(world.home, KEY, {"project": None})
    back = apply_back(world.home, a["n"])
    assert world.cfg.read_bytes() == before
    assert (back["what"], back["rolls_back"], back["before"], back["after"]) == ("rollback", a["n"], a["after"],
                                                                                a["before"])


def test_a_rollback_of_a_setting_that_was_absent_takes_it_out(world):   # must pass
    world.offer()
    write_cfg(world.cfg, {"closed": [], "tickets": str(world.old)})
    before = world.cfg.read_bytes()
    a = apply(world.home, KEY, {"project": "beta"})
    apply_back(world.home, a["n"])
    assert world.cfg.read_bytes() == before and "project" not in cfg(world)


def test_a_rollback_after_a_later_change_is_refused(world):   # must refuse
    world.offer()
    a = apply(world.home, KEY, {"project": "beta"})
    apply(world.home, KEY, {"project": "gamma"})
    with pytest.raises(pluginpage.Refused, match="changed since"):
        pluginpage.roll_back(world.home, a["n"])
    assert cfg(world)["project"] == "gamma"


def test_rolling_back_a_turn_off_never_turns_it_on_from_the_page(world):   # must refuse
    world.offer(on=True)
    off = pluginpage.turn_off(world.home, KEY)
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.roll_back(world.home, off["n"])
    assert e.value.command.endswith(f"plugins enable {KEY}") and KEY not in registry.enabled(world.home)[0]


def test_rolling_back_a_turn_on_turns_it_off(world, monkeypatch):   # must pass
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    world.offer()
    plugincmd._enable(KEY, world.home, lambda s: None, ask=lambda _: KEY)
    recs, _ = pluginpage.changes(world.home)
    assert (recs[-1]["who"], recs[-1]["what"]) == ("terminal", "on")
    pluginpage.roll_back(world.home, recs[-1]["n"])
    assert KEY not in registry.enabled(world.home)[0]


def test_a_rollback_confirmed_at_the_console_records_both_links(world, monkeypatch):
    world.offer()
    a = apply(world.home, KEY, {"tickets": str(world.old / "inner")})
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.roll_back(world.home, a["n"])
    assert cfg(world)["tickets"] == str(world.old / "inner")
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    said = []
    plugincmd._confirm(str(e.value.proposal), world.home, said.append, ask=lambda _: KEY)
    assert cfg(world)["tickets"] == str(world.old)
    recs, _ = pluginpage.changes(world.home)
    assert (recs[-1]["who"], recs[-1]["what"], recs[-1]["confirms"], recs[-1]["rolls_back"]) == (
        "terminal", "rollback", e.value.proposal, a["n"])


@pytest.mark.parametrize("n", [0, 99, "1", None, True])
def test_a_rollback_of_no_such_change_is_refused(world, n):   # must refuse
    with pytest.raises(pluginpage.Refused):
        pluginpage.roll_back(world.home, n)


def test_a_proposal_is_never_rolled_back(world):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "elsewhere")})
    with pytest.raises(pluginpage.Refused, match="never made"):
        pluginpage.roll_back(world.home, e.value.proposal)


# ---- confirming at the console --------------------------------------------------------------------------------------
@pytest.fixture
def proposed(world):
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "elsewhere")})
    return e.value.proposal


def test_confirming_makes_the_change_and_records_it(world, proposed, monkeypatch):   # must pass
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    said = []
    assert plugincmd._confirm(str(proposed), world.home, said.append, ask=lambda _: KEY) == 0
    assert cfg(world)["tickets"] == str(world.tmp / "elsewhere")
    assert "Labelled when proposed: widens." in said
    assert any(s.startswith("Sources file: ") for s in said)                 # which file the console acts on
    assert "  tickets:" in said and any(s.startswith("    was: ") for s in said) \
        and any(s.startswith("    now: ") and "elsewhere" in s for s in said)   # the full before and after of every key
    assert any("As things stand now it widens" in s for s in said)          # worked out again, not remembered
    recs, _ = pluginpage.changes(world.home)
    assert (recs[-1]["what"], recs[-1]["confirms"]) == ("settings", proposed)
    with pytest.raises(pluginpage.Refused, match="confirmed already"):   # must refuse: once only
        plugincmd._confirm(str(proposed), world.home, said.append, ask=lambda _: KEY)


def test_confirming_in_an_agents_shell_is_refused(world, proposed, monkeypatch):   # must refuse
    monkeypatch.setenv("CLAUDECODE", "1")
    with pytest.raises(pluginpage.Refused, match="agent"):
        plugincmd._confirm(str(proposed), world.home, lambda s: None, ask=lambda _: KEY)
    assert cfg(world)["tickets"] == str(world.old)


def test_confirming_with_the_wrong_name_typed_is_refused(world, proposed, monkeypatch):   # must refuse
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    with pytest.raises(pluginpage.Refused, match="not the plug-in's name"):
        plugincmd._confirm(str(proposed), world.home, lambda s: None, ask=lambda _: "yes")
    assert cfg(world)["tickets"] == str(world.old)


def test_a_stale_proposal_is_not_confirmed(world, proposed, monkeypatch):   # must refuse
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    apply(world.home, KEY, {"project": "beta"})   # a change applied after it: stale by the log's order and the file
    with pytest.raises(pluginpage.Refused, match="changed since|stale|superseded"):
        plugincmd._confirm(str(proposed), world.home, lambda s: None, ask=lambda _: KEY)


# ---- the change log ----------------------------------------------------------------------------------------------
def test_the_change_log_is_only_ever_appended_to(world, monkeypatch):   # must pass
    world.offer(on=True)
    seen = []
    snap = lambda: seen.append(pluginpage.log_file(world.home).read_bytes())   # noqa: E731
    a = apply(world.home, KEY, {"project": "beta"}); snap()
    apply_back(world.home, a["n"]); snap()
    with pytest.raises(pluginpage.AtTheTerminal):
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "elsewhere")})
    snap()
    pluginpage.turn_off(world.home, KEY); snap()
    assert all(later.startswith(earlier) for earlier, later in zip(seen, seen[1:]))
    recs, problems = pluginpage.changes(world.home)
    assert [r["n"] for r in recs] == [1, 2, 3, 4, 5, 6] and not problems
    assert [r["what"] for r in recs] == ["proposed", "settings", "proposed", "rollback", "proposed", "off"]


def test_a_record_out_of_its_place_is_a_problem_and_not_rolled_back(world):   # must refuse
    world.offer()
    a = apply(world.home, KEY, {"project": "beta"})   # change 2, after its proposal, 1
    path = pluginpage.log_file(world.home)
    text = path.read_text(encoding="utf-8").replace('"n": 2', '"n": 1')   # a number that does not go up
    path.write_text(text, encoding="utf-8")
    recs, problems = pluginpage.changes(world.home)
    assert [r["n"] for r in recs] == [1] and problems and "in its place" in problems[0]["text"]
    with pytest.raises(pluginpage.Refused, match="no change"):
        pluginpage.roll_back(world.home, a["n"])


def test_the_tab_shows_the_log_newest_first_with_the_line_to_confirm(world, proposed):
    _, got = row(home=world.home)
    first = got["changes"][0]
    assert first["n"] == proposed and first["confirmed"] is False
    assert first["command"].endswith(f"plugins confirm {proposed}")


def test_the_terminal_records_turning_on_and_off(world, monkeypatch):   # must pass
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    world.offer()
    plugincmd._enable(KEY, world.home, lambda s: None, ask=lambda _: KEY)
    plugincmd._disable(KEY, world.home, lambda s: None)
    recs, _ = pluginpage.changes(world.home)
    assert [(r["who"], r["what"]) for r in recs] == [("terminal", "on"), ("terminal", "off")]
    assert recs[0]["before"] is None and recs[0]["after"] == recs[1]["before"]


# ---- the page's routes and their guards ----------------------------------------------------------------------------
@pytest.fixture
def served(store, world):
    from semantext.server import make_server
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def post(srv, act, body, raw: bytes | None = None, origin=True, **headers):
    port = srv.server_address[1]
    sent = {"Content-Type": "application/json", "X-Semantext": "1", **headers}
    if origin:
        sent.setdefault("Origin", f"http://127.0.0.1:{port}")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v2/plugins/{act}", method="POST",
                                 data=raw if raw is not None else json.dumps(body).encode("utf-8"), headers=sent)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


PAGE = {"Sec-Fetch-Dest": "empty", "Sec-Fetch-Site": "same-origin"}


def test_the_page_turns_a_plug_in_off_and_proposes_a_setting(served, world):   # must pass, and must refuse a write
    world.offer(on=True)
    port = served.server_address[1]
    code, body = post(served, "settings", {"plugin": KEY, "settings": {"project": "beta"}},
                      Referer=f"http://127.0.0.1:{port}/v2", **PAGE)
    assert code == 202 and body["line"].endswith(f"plugins confirm {body['proposed']}")   # accepted, not refused
    assert cfg(world)["project"] == "alpha" and ("PowerShell" in body["note"] or "POSIX" in body["note"])
    code, body = post(served, "off", {"plugin": KEY}, Referer=f"http://127.0.0.1:{port}/v2", **PAGE)
    assert code == 200 and KEY not in registry.enabled(world.home)[0]
    code, body = post(served, "rollback", {"change": body["change"]["n"]}, **PAGE)
    assert code == 403 and body["command"].endswith(f"plugins enable {KEY}")


def test_the_page_cannot_turn_a_plug_in_on(served, world):   # must refuse
    world.offer()
    code, body = post(served, "on", {"plugin": KEY}, **PAGE)
    assert code == 403 and body["command"].endswith(f"plugins enable {KEY}") and body["proposal"] is None
    assert registry.enabled(world.home)[0] == {}
    code, _ = post(served, "settings", {"plugin": KEY, "settings": {"project": "b"}, "on": True}, **PAGE)
    assert code == 400 and registry.enabled(world.home)[0] == {}   # no field turns it on by the way


def test_the_page_cannot_widen_what_a_plug_in_reads(served, world):   # must refuse
    world.offer()
    code, body = post(served, "settings", {"plugin": KEY, "settings": {"tickets": str(world.tmp / "elsewhere")}},
                      **PAGE)
    assert code == 202 and body["line"].endswith(f"plugins confirm {body['proposed']}")
    assert cfg(world)["tickets"] == str(world.old)


@pytest.mark.parametrize("headers", [
    {"Referer": "PLUGIN"}, {"Sec-Fetch-Dest": "script"}, {"Sec-Fetch-Dest": "iframe"}, {"Sec-Fetch-Dest": "worker"},
])
def test_a_change_from_a_plug_in_module_or_not_a_plain_fetch_is_refused(served, world, headers):   # must refuse
    world.offer(on=True)
    port = served.server_address[1]
    headers = {k: (f"http://127.0.0.1:{port}/v2/plugin/board.js" if v == "PLUGIN" else v) for k, v in headers.items()}
    for act, body in (("off", {"plugin": KEY}), ("settings", {"plugin": KEY, "settings": {"project": "b"}})):
        code, _ = post(served, act, body, **headers)
        assert code == 403
    assert KEY in registry.enabled(world.home)[0] and cfg(world)["project"] == "alpha"


def test_a_change_from_no_page_or_another_page_is_refused(served, world):   # must refuse
    world.offer(on=True)
    assert post(served, "off", {"plugin": KEY}, origin=False)[0] == 403
    assert post(served, "off", {"plugin": KEY}, Origin="http://evil.example")[0] == 403
    assert KEY in registry.enabled(world.home)[0]


def test_a_body_that_gives_a_key_twice_is_refused(served, world):   # must refuse
    world.offer()
    raw = b'{"plugin": "source.tickets", "settings": {"project": "beta", "project": "gamma"}}'
    code, body = post(served, "settings", None, raw=raw, **PAGE)
    assert code == 400 and "twice" in body["error"] and cfg(world)["project"] == "alpha"
    raw = b'{"plugin": "source.tickets", "plugin": "source.other", "settings": {"project": "beta"}}'
    assert post(served, "settings", None, raw=raw, **PAGE)[0] == 400


@pytest.mark.parametrize("act, body", [
    ("settings", {"plugin": KEY, "settings": {"tickets": 3}}),
    ("settings", {"plugin": KEY, "settings": {"nope": "x"}}),
    ("settings", {"plugin": KEY, "settings": {"project": "b"}, "who": "terminal"}),
    ("off", {"plugin": "source.waiting"}),
    ("rollback", {"change": "1"}),
])
def test_a_bad_change_is_refused_by_the_server(served, world, act, body):   # must refuse
    world.offer(on=True)
    assert post(served, act, body, **PAGE)[0] == 400
    assert cfg(world)["project"] == "alpha" and KEY in registry.enabled(world.home)[0]


def test_an_act_the_page_does_not_have_is_not_found(served, world):   # must refuse
    assert post(served, "enable", {"plugin": KEY}, **PAGE)[0] == 404


def test_the_tab_is_read_by_the_page_like_the_other_places(served, world):   # must pass, and refuse without the header
    port = served.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/v2/plugins", headers={"X-Semantext": "1"})
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read())["place"] == "plugins"
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v2/plugins")
    assert e.value.code == 403


def test_the_health_words_follow_the_kernel(world):
    world.offer(on=True)
    outside.identify(KEY, "semantext-jira", "0.3")   # its health is kept for the package and version loaded
    outside._ended(KEY, "late", 5.0)
    r, _ = row(home=world.home)
    assert r["health"]["words"].startswith("its last call did not answer in time")
