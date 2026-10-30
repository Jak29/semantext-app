"""The independent attack on the Plug-ins tab (v2-14-plugins): each probe it made is a must-refuse test here, beside a
must-pass partner that shows the refusal is not the tab refusing everything. Numbered as the attack numbered them."""
from __future__ import annotations

import json
import os
import shlex
import time
from pathlib import Path

import pytest

from semantext import plugincmd, pluginpage, registry
from semantext.sources import view
from plugin_fakes import DECLARED
from test_plugins_tab import KEY, PAGE, apply, cfg, post, proposed_label, served, world, write_cfg  # noqa: F401


@pytest.fixture(autouse=True)
def fresh_gate():
    pluginpage._RECENT.clear()
    yield
    pluginpage._RECENT.clear()


# A1 and B1 (a reader that declares nothing, and a rollback judged apart from a change) were findings against the page
# deciding which settings changes it could make; it makes none now (the owner's choice: the page proposes, the console applies), so they are
# covered by test_plugins_tab.py's test_the_page_never_writes_a_setting and its rollback tests.
def test_the_page_reaches_the_write_path_only_to_turn_a_plug_in_off(world):   # must refuse anything else
    import inspect
    world.offer(on=True)
    with pluginpage.locked(world.home):
        for field, after in (("settings", {"values": {"project": "x"}, "absent": []}),
                             ("on", {"origin": "semantext-jira", "version": "0.3", "at": "x"})):
            with pytest.raises(pluginpage.Refused, match="turns a plug-in off and proposes"):
                pluginpage._make(world.home, "page", "x", field, KEY, None, after)
    assert cfg(world)["project"] == "alpha" and not pluginpage.log_file(world.home).exists()
    for name in ("change",):   # a settings change from the page never reaches the write path at all
        body = inspect.getsource(getattr(pluginpage, name))
        assert "_make(" not in body and "_apply(" not in body and "_write(" not in body, name
    assert "_apply(" not in inspect.getsource(pluginpage._propose)


def test_the_page_turns_a_plug_in_off_through_the_one_write_path(world):   # must pass
    world.offer(on=True)
    made = pluginpage.turn_off(world.home, KEY)
    assert made["what"] == "off" and KEY not in registry.enabled(world.home)[0]


# ---- A2 and item 4: taking a setting out -------------------------------------------------------------------------
def test_A2_taking_out_a_path_whose_default_is_wider_is_labelled_widens(world):
    declared = json.loads(json.dumps(DECLARED))
    declared["plugins"][KEY]["settings"][0]["default"] = str(world.tmp)   # wider than the tickets folder
    world.offer(declared=declared)
    assert proposed_label(world, {"tickets": None}) == "widens"


def test_A2_taking_out_a_path_whose_default_lies_inside_it_is_labelled_narrows(world):
    declared = json.loads(json.dumps(DECLARED))
    declared["plugins"][KEY]["settings"][0]["default"] = str(world.old / "inner")
    world.offer(declared=declared)
    assert proposed_label(world, {"tickets": None}) == "narrows"


# ---- A3 and item 3: the log is bounded ------------------------------------------------------------------------------
LIST = {"plugins": {KEY: {"settings": [{"key": "tags", "type": "list"}]}}}


def test_A3_a_change_whose_record_is_over_the_cap_is_refused_and_not_proposed(world):   # must refuse
    world.offer(declared=LIST)
    big = ["a" * 950 + str(i) for i in range(190)]
    before = world.cfg.read_bytes()
    with pytest.raises(pluginpage.Refused, match="KB one record may be"):
        pluginpage.change(world.home, KEY, {"tags": big})
    assert world.cfg.read_bytes() == before and not pluginpage.log_file(world.home).exists()


def test_A3_a_change_under_the_cap_is_applied(world):   # must pass
    world.offer(declared=LIST)
    d = cfg(world)
    d["tags"] = ["a" * 900 + str(i) for i in range(21)]
    write_cfg(world.cfg, d)
    apply(world.home, KEY, {"tags": d["tags"][:20]})
    assert len(cfg(world)["tags"]) == 20


def test_A3_the_page_is_held_to_its_rate(world, monkeypatch):   # must refuse past it, and pass after it
    monkeypatch.setattr(pluginpage, "PAGE_RATE", 3)
    world.offer()
    for v in ("b", "c", "d"):
        with pytest.raises(pluginpage.AtTheTerminal):
            pluginpage.change(world.home, KEY, {"project": v})
    with pytest.raises(pluginpage.Refused, match="the most it may") as e:
        pluginpage.change(world.home, KEY, {"project": "e"})
    assert not isinstance(e.value, pluginpage.AtTheTerminal) and len(pluginpage.changes(world.home)[0]) == 3
    monkeypatch.setattr(pluginpage, "PAGE_WINDOW", 0.0)   # the minute has passed
    time.sleep(0.01)
    with pytest.raises(pluginpage.AtTheTerminal):
        pluginpage.change(world.home, KEY, {"project": "e"})


def test_A3_the_log_is_rotated_once_and_its_numbers_go_on(world, monkeypatch):
    monkeypatch.setattr(pluginpage, "MAX_LOG", 2500)
    world.offer()
    ns = []
    for i in range(12):
        with pytest.raises(pluginpage.AtTheTerminal) as e:
            pluginpage.change(world.home, KEY, {"project": f"p{i}"})
        ns.append(e.value.proposal)
    assert ns == list(range(1, 13))                                           # must pass: numbering never restarts
    rotated = world.home / pluginpage.ROTATED
    assert rotated.is_file() and pluginpage.log_file(world.home).stat().st_size <= 2500
    recs, problems = pluginpage.changes(world.home)
    assert not problems and recs[-1]["n"] == 12 and recs[0]["n"] > 1
    with pytest.raises(pluginpage.Refused, match="superseded by proposal 12"):  # must refuse: not open (the chain's end)
        pluginpage.proposal(world.home, 1)
    assert pluginpage.proposal(world.home, 12)["n"] == 12                       # must pass: found past any rotation


def test_A3_the_tab_reads_only_the_tail_it_shows(world, monkeypatch):
    world.offer()
    for i in range(20):
        with pytest.raises(pluginpage.AtTheTerminal):
            pluginpage.change(world.home, KEY, {"project": f"p{i}"})
    size = pluginpage.log_file(world.home).stat().st_size
    monkeypatch.setattr(pluginpage, "TAIL", size // 4)
    seen = []
    real = pluginpage._tail
    monkeypatch.setattr(pluginpage, "_tail", lambda p, n: (seen.append(n), real(p, n))[1])
    got = view.answer("plugins", home=world.home)
    assert seen and max(seen) <= size // 4                                    # must refuse: never the whole file
    assert 0 < len(got["changes"]) < 20 and got["changes"][0]["n"] == 20      # must pass: the newest are shown
    assert not [p for p in got["problems"] if p["kind"] == "change log"]      # a cut first line is not a problem


def test_A3_the_same_proposal_asked_again_and_again_is_one_record(world):   # must refuse growth
    world.offer()
    for _ in range(5):
        with pytest.raises(pluginpage.AtTheTerminal):
            pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "x")})
    assert len(pluginpage.changes(world.home)[0]) == 1


# ---- A5: a path that reads as inside and is not ---------------------------------------------------------------------
@pytest.mark.parametrize("tail", ["..", ".. ", "...", "sub\\..\\..", "sub/../..", "x.", "x "])
def test_A5_a_path_with_dot_parts_or_trimmed_ends_is_refused(world, tail):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="without . or .."):
        pluginpage.change(world.home, KEY, {"tickets": str(world.old) + os.sep + tail + os.sep + "Windows"})


def test_A5_a_verbatim_prefix_is_refused(world):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="prefix"):
        pluginpage.change(world.home, KEY, {"tickets": "\\\\?\\" + str(world.old) + "\\x"})


def test_A5_a_plain_path_inside_is_applied(world):   # must pass
    world.offer()
    apply(world.home, KEY, {"tickets": str(world.old / "sub.d" / "x")})
    assert cfg(world)["tickets"] == str(world.old / "sub.d" / "x")


# ---- A7, A8, A9: the log's lines -------------------------------------------------------------------------------
@pytest.mark.parametrize("sep", ["\u2028", "\u0085", "\u2029"])
def test_A7_unicode_line_separators_in_a_value_are_refused(world, sep):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="invisible"):
        pluginpage.change(world.home, KEY, {"project": "x" + sep + "y"})


def test_A7_plain_values_keep_the_numbering(world):   # must pass
    world.offer()
    apply(world.home, KEY, {"project": "x y"})
    apply(world.home, KEY, {"project": "plain"})
    recs, problems = pluginpage.changes(world.home)
    assert [r["n"] for r in recs] == [1, 2, 3, 4] and not problems


def test_A7_a_line_break_in_a_value_is_refused(world):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="control"):
        pluginpage.change(world.home, KEY, {"project": "a\nb"})


def test_A8_a_cut_off_line_is_a_problem_and_the_next_record_follows_the_last_whole(world):   # must pass
    world.offer()
    apply(world.home, KEY, {"project": "beta"})                      # records 1 and 2
    with open(pluginpage.log_file(world.home), "ab") as f:
        f.write(b'{"n": 3, "who": "page"')
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "gamma"})
    recs, problems = pluginpage.changes(world.home)
    assert e.value.proposal == 3 and [r["n"] for r in recs] == [1, 2, 3] and len(problems) == 1   # the fragment, said


def test_A8_a_log_whose_end_cannot_be_read_takes_no_change(world):   # must refuse
    world.offer()
    pluginpage.log_file(world.home).write_text("not a record\n", encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="cannot be read"):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert cfg(world)["project"] == "alpha"


def test_A9_the_log_is_never_written_through_a_link(world, tmp_path):   # must refuse
    world.offer()
    target = tmp_path / "elsewhere.txt"
    target.write_text("", encoding="utf-8")
    try:
        os.symlink(target, pluginpage.log_file(world.home))
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a link")
    with pytest.raises(pluginpage.Refused, match="link"):
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert target.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize("which", ["log", "rotated", "last", "proposals"])
def test_no_file_of_the_tab_is_written_while_it_has_a_second_name(world, tmp_path, which):   # must refuse
    world.offer(on=True)
    path = {"log": pluginpage.log_file(world.home),
            "rotated": pluginpage.log_file(world.home).with_name(pluginpage.ROTATED),
            "last": pluginpage.last_file(world.home), "proposals": pluginpage.proposals_file(world.home)}[which]
    body = {"last": '{"keys": {}, "plugins": {}}\n',
            "proposals": '{"confirmed": {}, "open": {}, "superseded": {}}\n'}.get(which, "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    other = tmp_path / "second-name.txt"
    try:
        os.link(path, other)
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a hard link")
    with pytest.raises(pluginpage.Refused, match="another name"):
        if which == "proposals":   # a turning-off only reads it for numbering; a proposal writes it
            pluginpage.change(world.home, KEY, {"project": "beta"})
        else:
            pluginpage.turn_off(world.home, KEY)
    assert KEY in registry.enabled(world.home)[0] and cfg(world)["project"] == "alpha"   # nothing was changed
    assert other.read_text(encoding="utf-8") == body                      # and nothing written through it


def test_the_tab_writes_its_files_when_each_has_one_name(world):   # must pass
    world.offer(on=True)
    pluginpage.log_file(world.home).parent.mkdir(parents=True, exist_ok=True)
    pluginpage.log_file(world.home).with_name(pluginpage.ROTATED).write_text("", encoding="utf-8")
    made = pluginpage.turn_off(world.home, KEY)
    assert made["what"] == "off" and KEY not in registry.enabled(world.home)[0]
    assert pluginpage.log_file(world.home).read_text(encoding="utf-8").count("\n") == 1


# ---- A10 and item 5: a proposal is bound to the file it was made on, and expires --------------------------------------
@pytest.fixture
def proposed(world):
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "elsewhere")})
    return e.value.proposal


def test_A10_a_proposal_whose_file_changed_and_changed_back_is_not_confirmed(world, proposed):   # must refuse
    d = cfg(world)
    d["tickets"] = str(world.tmp)
    write_cfg(world.cfg, d)
    d["tickets"] = str(world.old)
    world.cfg.write_text(json.dumps(d), encoding="utf-8")   # the same values, not the same file
    with pytest.raises(pluginpage.Refused, match="changed since"):
        pluginpage.proposal(world.home, proposed)


def test_A10_a_proposal_on_the_file_as_it_was_is_confirmed(world, proposed):   # must pass
    assert pluginpage.confirm(world.home, proposed)["confirms"] == proposed
    assert cfg(world)["tickets"] == str(world.tmp / "elsewhere")


def test_A10_an_expired_proposal_is_not_confirmed(world, monkeypatch):   # must refuse
    monkeypatch.setattr(pluginpage, "PROPOSAL_SECONDS", 0)
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "elsewhere")})
    with pytest.raises(pluginpage.Refused, match="expired"):
        pluginpage.proposal(world.home, e.value.proposal)


def test_a_newer_proposal_for_the_same_key_supersedes_the_older(world, proposed):
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "other")})
    with pytest.raises(pluginpage.Refused, match="superseded"):            # must refuse the older
        pluginpage.proposal(world.home, proposed)
    assert pluginpage.proposal(world.home, e.value.proposal)["n"] == e.value.proposal   # must pass the newer


# ---- A11: keys that read as the closures --------------------------------------------------------------------------
@pytest.mark.parametrize("k", ["Closed", "CLOSURES_FILE", "Closures_Key", "SEATS"])
def test_A11_a_key_that_reads_as_a_reserved_one_is_refused(world, k):   # must refuse
    world.offer(declared={"plugins": {KEY: {"settings": [{"key": k, "type": "text"}]}}})
    with pytest.raises(pluginpage.Refused, match="declares no settings"):
        pluginpage.change(world.home, KEY, {k: "x"})
    assert k not in cfg(world)


@pytest.mark.parametrize("k", ["closed_", "roots"])
def test_A11_a_key_that_only_resembles_one_is_kept(world, k):   # must pass
    world.offer(declared={"plugins": {KEY: {"settings": [{"key": k, "type": "text"}]}}})
    apply(world.home, KEY, {k: "x"})
    assert cfg(world)[k] == "x"


# ---- item 6: the line to type is inert in the shell it is typed into ------------------------------------------------
HOSTILE = "/tmp/a b/$(touch pwned)/`id`/'q'"


def test_6_a_home_with_shell_characters_is_left_out_of_the_line():   # must refuse to carry it
    for shell in ("posix", "powershell"):
        line = pluginpage.command(HOSTILE, "plugins", "enable", "source.x", shell=shell)
        assert line == "semantext plugins enable source.x"
        assert "SEMANTEXT_HOME" in pluginpage.command_note(HOSTILE, shell=shell)


def test_6_a_home_of_plain_characters_and_spaces_is_shown(tmp_path):   # must pass
    home = str(Path("C:/Users/me/Semantext Home" if os.name == "nt" else "/home/me/Semantext Home"))
    posix = pluginpage.command(home, "plugins", "enable", "source.x", shell="posix")
    assert shlex.split(posix) == ["semantext", "--home", home, "plugins", "enable", "source.x"]
    assert pluginpage.command(home, "plugins", shell="powershell") == f"semantext --home '{home}' plugins"
    assert "SEMANTEXT_HOME" not in pluginpage.command_note(home)


def test_6_a_plain_home_is_left_bare(tmp_path):   # must pass
    plain = str(Path("/home/me/.semantext-test"))
    for shell in ("posix", "powershell"):
        line = pluginpage.command(plain, "plugins", shell=shell)
        if "\\" in plain and shell == "posix":   # item 7 of round 4: a backslash is quoted for a POSIX shell
            assert line == f"semantext --home {shlex.quote(plain)} plugins"
        else:
            assert line == f"semantext --home {plain} plugins"


@pytest.mark.parametrize("home", ["C:\\Users\\me\\home", "/home/me\\odd", "C:\\a b\\c"])
def test_6_a_home_with_a_backslash_is_quoted_for_posix(home):   # must refuse it bare: a POSIX shell eats \
    line = pluginpage.command(home, "plugins", shell="posix")
    assert shlex.split(line) == ["semantext", "--home", str(Path(home)), "plugins"]
    assert "\\" not in line or "'" in line


# ---- item 7: every writer takes the one lock ----------------------------------------------------------------------
@pytest.mark.parametrize("act", ["enable", "disable", "confirm", "page off", "page change"])
def test_7_every_writer_waits_for_the_lock(world, monkeypatch, act):   # must refuse while another holds it
    monkeypatch.setattr(pluginpage, "LOCK_SECONDS", 0.2)
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    world.offer(on=act != "enable")
    n = None
    if act == "confirm":
        with pytest.raises(pluginpage.AtTheTerminal) as e:
            pluginpage.change(world.home, KEY, {"tickets": str(world.tmp / "x")})
        n = e.value.proposal
    log = pluginpage.log_file(world.home)
    state = lambda: (registry.enabled(world.home)[0], world.cfg.read_bytes(),   # noqa: E731
                     log.read_bytes() if log.exists() else b"")
    before = state()
    run = {"enable": lambda: plugincmd._enable(KEY, world.home, lambda s: None, ask=lambda _: KEY),
           "disable": lambda: plugincmd._disable(KEY, world.home, lambda s: None),
           "confirm": lambda: pluginpage.confirm(world.home, n),
           "page off": lambda: pluginpage.turn_off(world.home, KEY),
           "page change": lambda: pluginpage.change(world.home, KEY, {"project": "b"})}[act]
    with pluginpage.locked(world.home):
        with pytest.raises(pluginpage.Refused, match="held by another writer"):
            run()
    assert state() == before
    try:
        run()                                                                # must pass once the lock is free
    except pluginpage.AtTheTerminal:
        assert act == "page change"                                          # it proposes, and records that
    assert state() != before


# ---- the HTTP probes ---------------------------------------------------------------------------------------------
REFUSED = [
    ("no X-Semantext", "off", {"plugin": KEY}, {"X-Semantext": None}, None, 403),
    ("cross origin", "off", {"plugin": KEY}, {"Origin": "http://evil.test"}, None, 403),
    ("origin of another port", "off", {"plugin": KEY}, {"Origin": "http://127.0.0.1:1"}, None, 403),
    ("origin null", "off", {"plugin": KEY}, {"Origin": "null"}, None, 403),
    ("referer a plug-in module", "off", {"plugin": KEY}, {"Referer": "MODULE"}, None, 403),
    ("not a plain fetch", "off", {"plugin": KEY}, {"Sec-Fetch-Dest": "script"}, None, 403),
    ("turn on", "on", {"plugin": KEY}, {}, None, 403),
    ("a key twice", "off", None, {}, b'{"plugin":"source.a","plugin":"source.tickets"}', 400),
    ("an inner key twice", "settings", None, {}, b'{"plugin":"source.tickets","settings":{"project":"a","project":"b"}}', 400),
    ("a field it does not take", "off", {"plugin": KEY, "who": "terminal"}, {}, None, 400),
    ("NaN", "rollback", None, {}, b'{"change": NaN}', 400),
    ("a truth value", "rollback", {"change": True}, {}, None, 400),
    ("a huge number", "rollback", None, {}, b'{"change": ' + b"9" * 5000 + b"}", 400),
    ("nested deep", "settings", None, {}, b'{"plugin":"source.tickets","settings":' + b"[" * 5000 + b"]" * 5000 + b"}", 400),
    ("a body too large", "settings", None, {}, b'{"plugin":"source.tickets","settings":{"project":"' + b"a" * 300000 + b'"}}', 400),
    ("not a record", "off", None, {}, b"[1,2]", 400),
    ("not UTF-8", "off", None, {}, b'{"plugin":"\xff\xfe"}', 400),
    ("an act the page does not have", "confirm", {"change": 1}, {}, None, 404),
    ("a path that steps out", "../active", {"x": 1}, {}, None, 404),
    ("a built-in off", "off", {"plugin": "place.plugins"}, {}, None, 400),
    ("a closure key", "settings", {"plugin": KEY, "settings": {"closed": None}}, {}, None, 400),
    ("a kind in capitals", "off", {"plugin": "SOURCE.tickets"}, {}, None, 400),
    ("no such change", "rollback", {"change": 99}, {}, None, 400),
]


@pytest.mark.parametrize("name, act, body, headers, raw, code", REFUSED, ids=[r[0] for r in REFUSED])
def test_http_probes_are_refused_and_write_nothing(served, world, name, act, body, headers, raw, code):   # must refuse
    world.offer(on=True)
    port = served.server_address[1]
    headers = {k: (f"http://127.0.0.1:{port}/v2/plugin/x.js" if v == "MODULE" else v) for k, v in headers.items()}
    before = (registry.enabled(world.home)[0], world.cfg.read_bytes())
    got, _ = _post_raw(served, act, body, raw, {**PAGE, **headers})
    # a body over the server's cap is refused unread, and a client still sending may see the connection reset instead
    # of the 400 (server.py, _drain): refused either way
    assert got == code or (name == "a body too large" and got == 0)
    assert (registry.enabled(world.home)[0], world.cfg.read_bytes()) == before
    assert not pluginpage.log_file(world.home).exists() or act == "on"


def test_http_the_same_requests_done_right_are_made(served, world):   # must pass
    world.offer(on=True)
    code, body = _post_raw(served, "settings", {"plugin": KEY, "settings": {"project": "b"}}, None, PAGE)
    assert code == 202 and b"plugins confirm" in body                    # proposed: accepted, with its line
    assert _post_raw(served, "off", {"plugin": KEY}, None, PAGE)[0] == 200
    assert cfg(world)["project"] == "alpha" and KEY not in registry.enabled(world.home)[0]


def _post_raw(srv, act, body, raw, headers):
    """A POST as a client of its own makes it, headers left out when given as None."""
    import http.client
    port = srv.server_address[1]
    data = raw if raw is not None else json.dumps(body).encode("utf-8")
    h = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", "X-Semantext": "1",
         "Origin": f"http://127.0.0.1:{port}", **headers}
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        c.request("POST", f"/api/v2/plugins/{act}", body=data, headers={k: v for k, v in h.items() if v is not None})
        r = c.getresponse()
        return r.status, r.read()
    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
        return 0, b""
    finally:
        c.close()
