"""The sixth independent attack on the Plug-ins tab, on what confirm, enable and show SHOW. The rule: every line a yes
depends on is in printable ASCII, measured as it is rendered, shows an order change whole, and is bound by a code when
it is read elsewhere. Each probe is a must-refuse test here, beside a must-pass partner."""
from __future__ import annotations

import json
import os

import pytest

from semantext import plugincmd, pluginpage, registry
from test_plugins_tab import KEY, apply, cfg, world, write_cfg  # noqa: F401  (fixtures)

SECRET = "C:\\Users\\someone\\Secret" if os.name == "nt" else "/home/someone/Secret"
LISTED = {"plugins": {KEY: {"reads": ["x"], "settings": [
    {"key": "tickets", "type": "path", "title": "Tickets file"}, {"key": "project", "type": "text", "title": "Project"},
    {"key": "extra", "type": "paths", "title": "More folders"}, {"key": "rules", "type": "list", "title": "Rules"}]}}}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    pluginpage._RECENT.clear()
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    yield
    pluginpage._RECENT.clear()


def _propose(world, given):
    pluginpage._RECENT.clear()
    with pytest.raises(pluginpage.Proposed) as e:
        pluginpage.change(world.home, KEY, given)
    return e.value.proposal


def _confirm(world, n, **kw):
    said = []
    plugincmd._confirm(str(n), world.home, said.append, ask=lambda p: (said.append(p), KEY)[1], **kw)
    return said


def _review(said):
    return said[:next(i for i, s in enumerate(said) if s.startswith("Having seen the above"))]


def _set(world, **values):
    d = cfg(world)
    d.update(values)
    write_cfg(world.cfg, d)


# ---- B1: the review is measured as it is rendered -------------------------------------------------------------------
def test_B1_a_first_time_list_is_one_entry_a_line_and_counted_in_rows(world):   # must refuse to fit it on one line
    world.offer()
    many = [str(world.old / f"f{i:03d}" / ("d" * 120)) for i in range(150)]
    many.insert(100, SECRET)
    n = _propose(world, {"extra": many})
    with pytest.raises(pluginpage.Refused, match="too large to review here"):
        _confirm(world, n)
    assert "extra" not in cfg(world)
    shown = pluginpage.show_proposal(world.home, n)
    assert f"      101. {json.dumps(SECRET)}" in shown                       # entry by entry, numbered, in full


def test_B1_a_short_first_time_list_is_shown_one_entry_a_line(world):   # must pass
    world.offer()
    n = _propose(world, {"extra": [str(world.old / "a"), SECRET]})
    review = _review(_confirm(world, n))
    assert "    was: (not set)" in review and "    now: a list of 2:" in review
    assert f"      2. {json.dumps(SECRET)}" in review and SECRET in cfg(world)["extra"]


def test_B1_rows_are_counted_at_the_boundary():
    w = pluginpage.WIDTH
    assert pluginpage.rows(["x" * w]) == 1 and pluginpage.rows(["x" * (w + 1)]) == 2 and pluginpage.rows([""]) == 1
    pluginpage.too_long(["x" * w] * pluginpage.REVIEW_LINES, "it", "s", "a")          # must pass: 60 rows
    with pytest.raises(pluginpage.Refused, match="61 rows"):                          # must refuse: 61 rows
        pluginpage.too_long(["x" * w] * (pluginpage.REVIEW_LINES - 1) + ["x" * (w + 1)], "it", "s", "a")


def test_B1_an_enable_review_of_long_values_is_refused(world):   # must refuse
    world.offer()
    _set(world, unrelated=[("x" * 900) + str(i) for i in range(60)])
    with pytest.raises(pluginpage.Refused, match="too large to review here"):
        plugincmd._enable(KEY, world.home, lambda s: None, ask=lambda _: KEY)
    assert KEY not in registry.enabled(world.home)[0]


# ---- B2: order -----------------------------------------------------------------------------------------------------
def test_B2_an_order_change_with_an_addition_shows_the_whole_lists(world):   # must refuse to show only the addition
    world.offer(declared=LISTED)
    _set(world, rules=["!secret/**", "**"])
    n = _propose(world, {"rules": ["**", "!secret/**", "notes/**"]})
    review = _review(_confirm(world, n))
    text = "\n".join(review)
    assert "rules: its order changed (meaning unknown); the whole list before and after:" in text
    assert '      1. "!secret/**"' in review and '      2. "**"' in review          # before, numbered
    assert '      1. "**"' in review and '      3. "notes/**"' in review          # after, numbered
    assert "+ put in" not in text and "As things stand now it widens" in text


def test_B2_a_pure_reorder_is_labelled_order_changed_never_narrows(world):   # must refuse "narrows"
    world.offer(declared=LISTED)
    _set(world, rules=["!secret/**", "**"])
    n = _propose(world, {"rules": ["**", "!secret/**"]})
    r = next(x for x in pluginpage.changes(world.home)[0] if x["n"] == n)
    assert r["label"] == "order changed"
    assert "As things stand now it order changed" in "\n".join(_review(_confirm(world, n)))


def test_B2_a_pure_append_is_shown_as_put_in(world):   # must pass
    world.offer(declared=LISTED)
    _set(world, rules=["a", "b"])
    review = _review(_confirm(world, _propose(world, {"rules": ["a", "b", "c"]})))
    assert '    + put in, as entry 3: "c"' in review


def test_B2_entries_only_taken_out_are_shown_as_taken_out(world):   # must pass
    world.offer(declared=LISTED)
    _set(world, rules=["a", "b", "c"])
    review = _review(_confirm(world, _propose(world, {"rules": ["a", "c"]})))
    assert '    - taken out: "b"' in review and not any("whole list" in x for x in review)


# ---- B3: printable ASCII only --------------------------------------------------------------------------------------
LOOKALIKE = ["\u3164", "\u115f", "\uffa0", "\u2800", "\u034f", "\ufe0f", "\u180b", "\u0338", "\u20dd", "\u043e",
             "\uff21", "\u05d0", "\u0627", "\U0001f600", "\u00e9"]


@pytest.mark.parametrize("ch", LOOKALIKE)
def test_B3_a_character_outside_printable_ascii_is_shown_as_its_escape(world, ch):   # must refuse to show it raw
    world.offer(declared=LISTED)
    _set(world, rules=["docs"])
    n = _propose(world, {"rules": ["d" + ch + "cs"]})
    review = _review(_confirm(world, n))
    assert all(all(" " <= c <= "~" for c in line) for line in review)
    esc = f"\\u{ord(ch):04x}" if ord(ch) <= 0xFFFF else f"\\U{ord(ch):08x}"
    assert any(esc in line for line in review)


def test_B3_plain_ascii_is_shown_as_itself(world):   # must pass
    world.offer(declared=LISTED)
    _set(world, rules=["docs"])
    review = _review(_confirm(world, _propose(world, {"rules": ["docs", "notes"]})))
    assert '    + put in, as entry 2: "notes"' in review


def test_B3_the_sources_path_itself_is_shown_in_ascii(world, monkeypatch, tmp_path):
    odd = tmp_path / "s\u043eurces.json"
    odd.write_bytes(world.cfg.read_bytes())
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(odd))
    world.offer()
    review = _review(_confirm(world, _propose(world, {"project": "beta"})))
    assert review[1].startswith("Sources file: ") and "s\\u043eurces.json" in review[1]


# ---- N1: --reviewed-full binds to what was read ---------------------------------------------------------------------
def _long(world):
    world.offer()
    _set(world, extra=[str(world.old)])
    return _propose(world, {"extra": [str(world.old)] + [str(world.old / f"f{i}") for i in range(80)]})


def _code(world, name):
    said = []
    plugincmd._show(str(name), world.home, said.append, full=True)
    assert said[-1].startswith("Review code: ")
    return said[-1].split()[2]


def test_N1_confirm_with_the_code_show_printed_applies_it(world):   # must pass
    n = _long(world)
    _confirm(world, n, reviewed_full=_code(world, n))
    assert len(cfg(world)["extra"]) == 81


@pytest.mark.parametrize("code", ["", "x", "deadbeef"])
def test_N1_confirm_with_a_wrong_code_is_refused(world, code):   # must refuse
    n = _long(world)
    with pytest.raises(pluginpage.Refused, match="not the review code"):
        _confirm(world, n, reviewed_full=code)
    assert cfg(world)["extra"] == [str(world.old)]


def test_N1_a_code_of_a_review_that_changed_since_is_refused(world):   # must refuse
    n = _long(world)
    code = _code(world, n)
    _set(world, project="changed by hand")   # the sources file is not what was read
    with pytest.raises(pluginpage.Refused):
        _confirm(world, n, reviewed_full=code)
    assert cfg(world)["extra"] == [str(world.old)]


def test_N1_enable_is_bound_by_its_code_too(world):
    world.offer()
    _set(world, unrelated=[("x" * 900) + str(i) for i in range(60)])
    with pytest.raises(pluginpage.Refused, match="not the review code"):          # must refuse
        plugincmd._enable(KEY, world.home, lambda s: None, ask=lambda _: KEY, reviewed_full="00000000")
    plugincmd._enable(KEY, world.home, lambda s: None, ask=lambda _: KEY, reviewed_full=_code(world, KEY))
    assert KEY in registry.enabled(world.home)[0]                                  # must pass


# ---- N2: numbering never restarts ------------------------------------------------------------------------------------
def test_N2_a_log_moved_aside_never_restarts_the_numbers(world):   # must refuse to go back to 1
    world.offer()
    row = {"origin": "semantext-jira", "version": "0.3", "at": "x"}
    for _ in range(4):
        pluginpage.console_on_off(world.home, KEY, row)
        pluginpage.console_on_off(world.home, KEY, None)
    log = pluginpage.log_file(world.home)
    os.replace(log, log.with_name("moved-aside.jsonl"))   # what the refusal's advice says to do
    n = _propose(world, {"project": "beta"})
    assert n == 9
    made = pluginpage.confirm(world.home, n)
    seen = pluginpage.changed_while_off(world.home, KEY)
    assert made["n"] == 10 and [c["n"] for c in seen] == [10]                     # must pass: still seen
    assert not pluginpage.changes(world.home)[1]


def test_N2_a_number_that_goes_back_is_said_aloud(world):   # must refuse
    world.offer()
    apply(world.home, KEY, {"project": "beta"})
    log = pluginpage.log_file(world.home)
    first = log.read_text(encoding="utf-8").splitlines()[0]
    with open(log, "a", encoding="utf-8") as f:
        f.write(first + "\n")
    recs, problems = pluginpage.changes(world.home)
    assert [r["n"] for r in recs] == [1, 2] and any("does not go up" in p["text"] for p in problems)


# ---- N3: pruning by number ----------------------------------------------------------------------------------------
def test_N3_the_oldest_by_number_go_first(tmp_path):
    store = {"open": {}, "superseded": {str(i): {"by": i + 1} for i in range(801, 1001)}, "confirmed": {}}
    (tmp_path / pluginpage.PROPOSALS).write_text(json.dumps(store, sort_keys=True), encoding="utf-8")
    s = pluginpage._proposals_ok(tmp_path)
    s["superseded"]["1001"] = {"by": 1002}
    pluginpage._keep_proposals(tmp_path, s)
    kept = set(pluginpage._proposals_ok(tmp_path)["superseded"])
    assert "801" not in kept                                                       # must refuse to keep the oldest
    assert {"1000", "1001", "802"} <= kept                                         # must pass: the newest stay


# ---- N4: turning a plug-in off is never held to the page's rate ---------------------------------------------------
def test_N4_off_works_when_the_rate_is_full(world, monkeypatch):   # must pass
    monkeypatch.setattr(pluginpage, "PAGE_RATE", 2)
    world.offer(on=True)
    for v in ("b", "c"):
        with pytest.raises(pluginpage.Proposed):
            pluginpage.change(world.home, KEY, {"project": v})
    with pytest.raises(pluginpage.Refused, match="the most it may"):              # must refuse: the rate is full
        pluginpage.change(world.home, KEY, {"project": "d"})
    pluginpage.turn_off(world.home, KEY)                                           # and yet Off works
    assert KEY not in registry.enabled(world.home)[0]
