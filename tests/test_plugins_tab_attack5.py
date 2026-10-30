"""The fifth independent attack on the Plug-ins tab ("the page writes nothing on its own, but confirm does not show what
is agreed to"). The rule it holds the console to: what confirm applies is shown exactly, or confirm refuses; and what
a page can do to the console's acts is bounded. Each probe is a must-refuse test here, beside a must-pass partner."""
from __future__ import annotations

import json
import os

import pytest

from semantext import plugincmd, pluginpage, registry
from semantext.sources import view
from test_plugins_tab import KEY, PAGE, apply, cfg, post, served, world, write_cfg  # noqa: F401  (fixtures)

SECRET = "C:\\Users\\someone\\Secret" if os.name == "nt" else "/home/someone/Secret"


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    pluginpage._RECENT.clear()
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    yield
    pluginpage._RECENT.clear()


def _propose(world, given, key=KEY):
    pluginpage._RECENT.clear()
    with pytest.raises(pluginpage.Proposed) as e:
        pluginpage.change(world.home, key, given)
    return e.value.proposal


def _confirm(world, n, ask=None, **kw):
    said = []

    def answer(prompt):
        said.append(prompt)
        return (ask or (lambda _: KEY))(prompt)
    plugincmd._confirm(str(n), world.home, said.append, ask=answer, **kw)
    return said


def _before_the_yes(said):
    return said[:next(i for i, s in enumerate(said) if s.startswith("Having seen the above"))]


# ---- A1 and item 2: a near-copy that supersedes the person's proposal ---------------------------------------------------
def test_A1_a_superseded_proposal_is_never_applied_in_its_place(world):   # must refuse
    world.offer()
    benign = [str(world.old), str(world.old / "a"), str(world.old / "b")]
    n = _propose(world, {"extra": benign})
    m = _propose(world, {"extra": benign + [SECRET]})               # the page module's, superseding the person's
    with pytest.raises(pluginpage.Refused) as e:
        _confirm(world, n)
    said = str(e.value)
    assert f"proposal {n} was superseded by proposal {m}, made by this page" in said
    assert f"{n} itself was made by this page at 20" in said                         # both named, who and when
    assert f"{m} is not applied in its place" in said and f"plugins confirm {m}" in said
    assert "extra" not in cfg(world)                                 # nothing applied


def test_A1_the_superseding_proposal_shows_its_secret_entry_before_its_own_yes(world):   # must pass
    world.offer()
    benign = [str(world.old), str(world.old / "a"), str(world.old / "b")]
    _propose(world, {"extra": benign})
    m = _propose(world, {"extra": benign + [SECRET]})
    review = "\n".join(_before_the_yes(_confirm(world, m)))
    assert json.dumps(SECRET) in review and "    was: (not set)" in review   # the whole new list, every entry exactly


# ---- A2 and item 1: a long "before" can no longer hide the "after" ------------------------------------------------------
def test_A2_an_entry_added_to_a_long_list_is_shown_in_full(world):   # must refuse to hide it
    world.offer()
    d = cfg(world)
    d["extra"] = [str(world.old / f"folder{i}" / ("deep" * 40)) for i in range(6)]
    write_cfg(world.cfg, d)
    n = _propose(world, {"extra": d["extra"] + [SECRET]})
    review = _before_the_yes(_confirm(world, n))
    assert f"    + put in, as entry 7: {json.dumps(SECRET)}" in review
    assert "a list of 6 becomes a list of 7, entries only added at the end" in "\n".join(review)
    assert not any("more)" in line for line in review)                # nothing a yes depends on is cut


def test_A2_an_entry_taken_out_is_shown_in_full(world):   # must pass
    world.offer()
    d = cfg(world)
    d["extra"] = [str(world.old / "keep"), SECRET]
    write_cfg(world.cfg, d)
    n = _propose(world, {"extra": [str(world.old / "keep")]})
    assert f"    - taken out: {json.dumps(SECRET)}" in _before_the_yes(_confirm(world, n))


def test_1_a_difference_longer_than_a_page_is_refused_and_shown_by_show(world):   # must refuse here
    world.offer()
    d = cfg(world)
    d["extra"] = [str(world.old)]
    write_cfg(world.cfg, d)
    big = [str(world.old)] + [str(world.old / f"f{i}") for i in range(80)]
    n = _propose(world, {"extra": big})
    with pytest.raises(pluginpage.Refused, match="too large to review here") as e:
        _confirm(world, n)
    assert f"plugins show {n} --full" in str(e.value) and cfg(world)["extra"] == [str(world.old)]
    said = []
    plugincmd._show(str(n), world.home, said.append, full=True)       # must pass: every entry, there, and a code
    assert sum(line.startswith("    + put in, as entry") for line in said) == 80
    code = said[-1].split()[2]
    with pytest.raises(pluginpage.Refused, match="not the review code"):   # must refuse a wrong code
        _confirm(world, n, reviewed_full="00000000")
    _confirm(world, n, reviewed_full=code)
    assert cfg(world)["extra"] == big


# ---- A3, A3b and item 6: shown equals written ----------------------------------------------------------------------
def test_A3_a_run_of_spaces_is_shown_exactly(world):   # must pass: never collapsed
    world.offer()
    v = "alpha      beta"
    n = _propose(world, {"project": v})
    line = next(s for s in _confirm(world, n) if s.startswith("    now: "))
    assert line == "    now: " + json.dumps(v).replace(" ", "\\u0020") and cfg(world)["project"] == v
    assert json.loads(line[len("    now: "):].replace("\\u0020", " ")) == v


@pytest.mark.parametrize("ch", ["\u200b", "\u202e", "\ufeff", "\u2066", "\u00ad", "\u0085", "\ue000"])
def test_A3b_an_invisible_or_direction_changing_character_is_refused(world, ch):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="invisible") as e:
        pluginpage.change(world.home, KEY, {"project": "al" + ch + "pha"})
    assert not isinstance(e.value, pluginpage.AtTheTerminal) and not pluginpage.log_file(world.home).exists()


def test_A3b_a_plain_value_is_kept(world):   # must pass
    world.offer()
    apply(world.home, KEY, {"project": "alpha-beta é"})
    assert cfg(world)["project"] == "alpha-beta é"


def test_6_exact_escapes_what_does_not_show_as_itself():
    assert pluginpage.exact("a\u200bb") == '"a\\u200bb"' and pluginpage.exact("a b") == '"a b"'
    assert pluginpage.exact("a  b") == '"a\\u0020\\u0020b"' and pluginpage.exact("\u00a0") == '"\\u00a0"'


# ---- A4 and item 3: what a page can do to the console's acts ---------------------------------------------------------
def test_A4_a_page_superseding_during_the_yes_refuses_it(world):   # must refuse: never another than the one named
    world.offer()
    n = _propose(world, {"project": "wanted"})
    with pytest.raises(pluginpage.Refused, match="superseded"):
        _confirm(world, n, ask=lambda _: (_propose(world, {"project": "other"}), KEY)[1])
    assert cfg(world)["project"] == "alpha"


def test_A4_a_page_proposing_for_another_key_during_the_yes_refuses_nothing(world):   # must pass
    world.offer()
    n = _propose(world, {"project": "wanted"})
    _confirm(world, n, ask=lambda _: (_propose(world, {"tickets": str(world.old / "x")}), KEY)[1])
    assert cfg(world)["project"] == "wanted"


def test_A7_the_page_turning_another_plug_in_off_does_not_refuse_enable(world):   # must pass
    world.offer()
    world.offer("source.other", declared=None, on=True, name="semantext-o", module="semantext_o")

    def ask(_):
        pluginpage._RECENT.clear()
        pluginpage.turn_off(world.home, "source.other")
        return KEY
    plugincmd._enable(KEY, world.home, lambda s: None, ask=ask)
    assert KEY in registry.enabled(world.home)[0]


def test_A7_a_change_to_a_key_it_will_be_given_during_the_yes_refuses_enable(world):   # must refuse
    world.offer()
    n = _propose(world, {"project": "changed"})

    def ask(_):
        pluginpage.confirm(world.home, n)   # a key source.tickets declares, changed after its review was shown
        return KEY
    with pytest.raises(pluginpage.Refused, match="after the review"):
        plugincmd._enable(KEY, world.home, lambda s: None, ask=ask)
    assert KEY not in registry.enabled(world.home)[0]


def test_A8_a_proposal_is_found_however_many_records_follow_it(world, monkeypatch):   # must pass
    world.offer()
    n = _propose(world, {"project": "wanted"})
    monkeypatch.setattr(pluginpage, "TAIL", 4096)                     # the tail the tab reads: far behind it
    root = "C:\\Users\\someone\\" if os.name == "nt" else "/home/someone/"
    for j in range(9):
        _propose(world, {"extra": [root + f"p{j}-{i}-" + "x" * 280 for i in range(40)]})
    assert pluginpage.proposal(world.home, n)["n"] == n
    assert pluginpage.confirm(world.home, n)["confirms"] == n and cfg(world)["project"] == "wanted"


def test_A8_the_store_of_proposals_is_never_reset(world):   # must refuse to lose which are open
    world.offer()
    n = _propose(world, {"project": "wanted"})
    pluginpage.proposals_file(world.home).write_text("{ not json", encoding="utf-8")
    for act in (lambda: pluginpage.proposal(world.home, n),
                lambda: pluginpage.change(world.home, KEY, {"project": "other"})):
        with pytest.raises(pluginpage.Refused, match="cannot be read") as e:
            act()
        assert not isinstance(e.value, pluginpage.Proposed)
    assert pluginpage.proposals_file(world.home).read_text(encoding="utf-8") == "{ not json"


# ---- A5, A6 and item 4: reserved keys, whatever the log says --------------------------------------------------------
def _forge(world, before, after, n=1):
    path = pluginpage.log_file(world.home)
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"n": n, "at": "2026-10-29T00:00:00+00:00", "who": "terminal", "what": "settings", "field": "settings",
           "plugin": KEY, "before": before, "after": after}
    path.write_text(json.dumps(rec) + "\n", encoding="utf-8")


@pytest.mark.parametrize("key", ["closed", "Closures_File", "seats", "private"])
def test_A5_a_forged_record_on_a_reserved_key_is_never_rolled_back(world, key):   # must refuse
    world.offer()
    d = cfg(world)
    d["closures_key"] = "private"   # the key named by closures_key is reserved too
    write_cfg(world.cfg, d)
    _forge(world, {"values": {}, "absent": [key]}, {"values": {key: d.get(key, [])}, "absent": []})
    d[key] = d.get(key, [])
    write_cfg(world.cfg, d)
    with pytest.raises(pluginpage.Refused, match="Semantext's own or of your closures") as e:
        pluginpage.roll_back(world.home, 1)
    assert not isinstance(e.value, pluginpage.AtTheTerminal) and key in cfg(world)


def test_A5_a_reserved_key_is_refused_at_the_write_whatever_the_proposal_says(world):   # must refuse
    world.offer()
    with pluginpage.locked(world.home):
        with pytest.raises(pluginpage.Refused, match="Semantext's own"):
            pluginpage._make(world.home, "terminal", "settings", "settings", KEY,
                             {"values": {"closed": []}, "absent": []}, {"values": {}, "absent": ["closed"]})
    assert cfg(world)["closed"] == [] and not pluginpage.log_file(world.home).exists()


def test_A5_a_record_on_an_ordinary_key_is_rolled_back_as_a_proposal(world):   # must pass
    world.offer()
    _forge(world, {"values": {"project": "alpha"}, "absent": []}, {"values": {"project": "beta"}, "absent": []})
    d = cfg(world)
    d["project"] = "beta"
    write_cfg(world.cfg, d)
    with pytest.raises(pluginpage.Proposed):
        pluginpage.roll_back(world.home, 1)


def test_7_a_record_with_no_before_is_not_a_record(world):   # must refuse, never a KeyError
    world.offer()
    path = pluginpage.log_file(world.home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"n": 1, "at": "x", "who": "page", "what": "off", "field": "on", "plugin": KEY,
                                "after": None}) + "\n", encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="no change 1"):
        pluginpage.roll_back(world.home, 1)
    recs, problems = pluginpage.changes(world.home)
    assert recs == [] and problems


class ReadsClosed:
    kind, name, title, keys, needs = "source", "reader2", "R", ("closed", "k0"), ()

    def read(self, config):
        return {"off": True, "problems": []}


class ReadsPlain(ReadsClosed):
    keys = ("k0", "k1")


def test_A6_a_plug_in_whose_keys_name_a_reserved_key_is_never_loaded(world):   # must refuse
    world.offer("source.reader2", make=ReadsClosed, declared=None, on=True, name="semantext-r2", module="semantext_r2")
    reg = registry.load_enabled(view.BUILT_IN, world.home)
    assert reg.get("source", "reader2") is None
    assert any(p["kind"] == "reserved key" and "'closed'" in p["text"] for p in reg.problems)


def test_A6_a_plug_in_with_ordinary_keys_is_loaded(world):   # must pass
    world.offer("source.reader2", make=ReadsPlain, declared=None, on=True, name="semantext-r2", module="semantext_r2")
    assert registry.load_enabled(view.BUILT_IN, world.home).get("source", "reader2") is not None


def test_5_the_enable_review_shows_every_other_key_and_names_the_reserved_ones(world):
    world.offer("source.reader2", make=ReadsClosed, declared={"plugins": {"source.reader2": {"settings": []}}},
                name="semantext-r2", module="semantext_r2")
    d = cfg(world)
    for i in range(25):
        d[f"k{i}"] = f"v{i}"
    write_cfg(world.cfg, d)
    review = pluginpage.enable_review(world.home, "source.reader2", {"settings": []})
    assert all(f'  k{i} = "v{i}"' in review for i in range(25))           # must pass: all of them, exactly
    assert not any("more" in line for line in review)
    kept = next(line for line in review if line.startswith("Kept by Semantext"))
    assert "closed" in kept and "refused" in kept                          # must refuse to hide them


# ---- item 7: the server says no more than it means to ----------------------------------------------------------------
def test_7_an_error_no_one_wrote_for_the_page_is_a_fixed_400(served, world, monkeypatch):   # must refuse its words
    world.offer(on=True)

    def boom(home, key):
        raise KeyError("C:\\private\\path that must not be sent")
    monkeypatch.setattr(pluginpage, "turn_off", boom)
    code, body = post(served, "off", {"plugin": KEY}, **PAGE)
    assert code == 400 and body == {"error": "bad request", "error_id": "KeyError"}


def test_7_a_refusal_keeps_its_own_words(served, world):   # must pass
    world.offer()
    code, body = post(served, "off", {"plugin": KEY}, **PAGE)
    assert code == 400 and body["error"] == f"{KEY} is not on"


# ---- item 8: a proposal is accepted, not refused ------------------------------------------------------------------
def test_8_a_proposal_answers_202_with_its_number_and_line(served, world):   # must pass
    world.offer()
    code, body = post(served, "settings", {"plugin": KEY, "settings": {"project": "beta"}}, **PAGE)
    assert code == 202 and type(body["proposed"]) is int and body["line"].endswith(f"confirm {body['proposed']}")
    assert "error" not in body


def test_8_turning_on_is_still_refused_with_403(served, world):   # must refuse
    world.offer()
    code, body = post(served, "on", {"plugin": KEY}, **PAGE)
    assert code == 403 and "proposed" not in body
