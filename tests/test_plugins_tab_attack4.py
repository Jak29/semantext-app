"""The fourth independent attack on the Plug-ins tab, and the owner's answer to it (the owner's choice, in their words: "Page
proposes, console applies"): the page never writes a plug-in's settings, and what the console shows before its yes is
true, snapshotted, and checked again after it. Each probe is a must-refuse test here, beside a must-pass partner."""
from __future__ import annotations

import json
import os
import threading

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


def _enable(world, key, during=None):
    said = []

    def ask(prompt):
        said.append(prompt)
        if during:
            during()
        return key
    plugincmd._enable(key, world.home, said.append, ask=ask)
    return said


def _review(said):
    return said[:next(i for i, s in enumerate(said) if s.startswith("Having seen the above"))]


# ---- P1, item 2: the review is snapshotted, and the yes holds only for what was shown -----------------------------
def _page_proposes(world):
    pluginpage._RECENT.clear()
    with pytest.raises(pluginpage.AtTheTerminal):
        pluginpage.change(world.home, KEY, {"project": "EVIL-AFTER-REVIEW"})


def _hand_edit(world):
    d = cfg(world)
    d["project"] = "EVIL-AFTER-REVIEW"
    write_cfg(world.cfg, d)


def _declaration_changes(world):
    world.points[0].dist  # the declaration file of source.tickets, rewritten after the review
    path = world.tmp / "site-semantext-jira" / "semantext_jira" / "semantext-plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["plugins"][KEY]["settings"].append({"key": "more", "type": "path"})
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("during", [_hand_edit, _declaration_changes],
                         ids=["the file is edited", "the declaration changes"])
def test_P1_enable_refuses_when_anything_changed_after_the_review(world, during):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="after the review was shown"):
        _enable(world, KEY, during=lambda: during(world))
    assert KEY not in registry.enabled(world.home)[0]


def test_P1_enable_with_nothing_changed_turns_it_on(world):   # must pass
    world.offer()
    _enable(world, KEY)
    assert KEY in registry.enabled(world.home)[0]


def test_P1_a_page_proposal_during_the_review_does_not_refuse_the_yes(world):   # must pass: it changes nothing read
    world.offer()
    _enable(world, KEY, during=lambda: _page_proposes(world))
    assert KEY in registry.enabled(world.home)[0]


def test_P1_confirm_refuses_when_the_file_changed_after_its_review(world):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "beta"})

    def ask(prompt):
        _hand_edit(world)
        return KEY
    with pytest.raises(pluginpage.Refused, match="stale"):
        plugincmd._confirm(str(e.value.proposal), world.home, lambda s: None, ask=ask)
    assert cfg(world)["project"] == "EVIL-AFTER-REVIEW"   # the hand edit stands; the proposal was not applied


def test_P1_confirm_with_nothing_changed_applies_it(world):   # must pass
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "beta"})
    plugincmd._confirm(str(e.value.proposal), world.home, lambda s: None, ask=lambda _: KEY)
    assert cfg(world)["project"] == "beta"


# ---- P2, P7, P6, item 3: the review is true ------------------------------------------------------------------------
class Partial:
    kind, name, title, keys, needs = "source", "partial", "Partial", ("other", "project"), ("other",)

    def read(self, config):
        return {"off": True, "problems": []}


PARTIAL = {"plugins": {"source.partial": {"reads": ["other"], "settings": [{"key": "other", "type": "text"}]}}}


def test_P2_keys_it_may_read_without_declaring_are_shown_with_their_values(world):   # must refuse to hide them
    world.offer()
    world.offer("source.partial", make=Partial, declared=PARTIAL, name="semantext-partial", module="semantext_partial")
    made = apply(world.home, KEY, {"project": SECRET})
    review = "\n".join(_review(_enable(world, "source.partial")))
    assert "may also read settings it has not declared" in review
    assert f"project = {json.dumps(SECRET)}" in review                      # the key, with its value
    assert f"change {made['n']}" in review                                    # and its change, any key


def test_P2_reserved_keys_are_not_listed_as_its_own(world):   # must pass: the frame's and the closures' keys are not
    world.offer()
    world.offer("source.partial", make=Partial, declared=PARTIAL, name="semantext-partial", module="semantext_partial")
    review = _review(_enable(world, "source.partial"))
    assert not any(line.startswith("  closed = ") for line in review)


class ReadsOnly:
    kind, name, title, keys, needs = "source", "readsonly", "ReadsOnly", ("project",), ("project",)

    def read(self, config):
        return {"off": True, "problems": []}


READS_ONLY = {"plugins": {"source.readsonly": {"reads": ["the project you name"], "settings": []}}}


def test_P7_an_empty_settings_list_shows_every_change(world):   # must refuse to filter all out
    world.offer()
    world.offer("source.readsonly", make=ReadsOnly, declared=READS_ONLY, name="semantext-ro", module="semantext_ro")
    made = apply(world.home, KEY, {"project": SECRET})
    review = "\n".join(_review(_enable(world, "source.readsonly")))
    assert "It declares no settings." in review and f"change {made['n']}" in review and json.dumps(SECRET) in review
    assert "is listed below" not in review                                    # no promise it does not keep


def test_P6_a_declared_default_is_shown(world):   # must refuse to leave it out
    world.offer()
    apply(world.home, KEY, {"project": None})                                 # tickets declares the default "all"
    review = "\n".join(_review(_enable(world, KEY)))
    assert 'project: not set; it then reads its declared default "all"' in review


def test_P6_a_setting_with_no_default_says_only_not_set(world):   # must pass
    world.offer()
    review = "\n".join(_review(_enable(world, KEY)))
    assert "  extra: not set" in review and "extra: not set;" not in review


# ---- P3, item 4 of round 4, and item 1 of round 5: a value is shown exactly, and never fakes a line -----------------
def test_P3_a_padded_value_cannot_make_a_line_of_its_own(world):   # must refuse
    world.offer()
    fake = ("beta" + " " * 200 + "No settings change is recorded since it was last turned off." + " " * 60
            + "change 1, 2026-10-29T00:00:00Z, by the terminal: project \"alpha\" -> \"beta\"")
    apply(world.home, KEY, {"project": fake})
    review = _review(_enable(world, KEY))
    values = [line for line in review if not line.startswith("  package: ")]   # its two-space break is the label's
    assert all("  " not in line.lstrip(" ") for line in values)                # no run of spaces to wrap on
    spoof = next(line for line in review if line.startswith("  project = "))
    assert spoof.startswith('  project = "beta\\u0020\\u0020')               # the run shown as it is, escaped
    assert json.loads(spoof[len("  project = "):].replace("\\u0020", " ")) == fake   # exactly the value written
    assert not any(line.startswith("No settings change") for line in review)


def test_P3_a_long_value_is_shown_whole(world):   # must refuse to cut what the yes depends on
    world.offer()
    apply(world.home, KEY, {"project": "x" * 900})
    line = next(x for x in _review(_enable(world, KEY)) if x.startswith("  project = "))
    assert line == '  project = "' + "x" * 900 + '"' and "more)" not in line


def test_P3_a_review_longer_than_a_page_is_refused_and_shown_by_show(world):   # must refuse here
    world.offer()
    for i in range(25):
        pluginpage._RECENT.clear()
        apply(world.home, KEY, {"project": f"v{i}"})
    with pytest.raises(pluginpage.Refused, match="too large to review here") as e:
        _enable(world, KEY)
    assert "plugins show source.tickets --full" in str(e.value) and "--reviewed-full" in str(e.value)
    assert KEY not in registry.enabled(world.home)[0]
    said = []
    plugincmd._show(KEY, world.home, said.append, full=True)                   # must pass: all of it, there
    assert sum(line.startswith("  change ") for line in said) == 25
    code = said[-1].split()[2]
    plugincmd._enable(KEY, world.home, said.append, ask=lambda _: KEY, reviewed_full=code)
    assert KEY in registry.enabled(world.home)[0]


# ---- P4, item 5: a lone surrogate, and anything unforeseen, is a plain answer ---------------------------------------
def test_P4_a_lone_surrogate_is_refused_never_a_crash(world):   # must refuse
    world.offer()
    with pytest.raises(pluginpage.Refused, match="lone surrogate") as e:
        pluginpage.change(world.home, KEY, {"project": "x\ud800y"})
    assert not isinstance(e.value, pluginpage.AtTheTerminal) and not pluginpage.log_file(world.home).exists()


def test_P4_over_http_a_surrogate_is_a_400(served, world):   # must refuse, and answer
    world.offer()
    code, body = post(served, "settings", None, raw=b'{"plugin": "source.tickets", "settings": {"project": "x\\ud800y"}}',
                      **PAGE)
    assert code == 400 and "lone surrogate" in body["error"]


def test_P4_an_unforeseen_error_in_a_post_is_a_plain_500(served, world, monkeypatch):   # must refuse to drop it
    world.offer(on=True)

    def boom(home, key):
        raise RuntimeError("something no one foresaw, with a path C:\\private\\x")
    monkeypatch.setattr(pluginpage, "turn_off", boom)
    code, body = post(served, "off", {"plugin": KEY}, **PAGE)
    assert code == 500 and body == {"error": "the change could not be made", "error_id": "RuntimeError"}


def test_P4_the_same_post_done_right_answers_200(served, world):   # must pass
    world.offer(on=True)
    assert post(served, "off", {"plugin": KEY}, **PAGE)[0] == 200


# ---- P5, item 6: "not applied" says exactly what it means --------------------------------------------------------------
def test_P5_a_hand_edit_after_a_change_is_said_as_the_file_not_holding_it(world):
    world.offer()
    made = apply(world.home, KEY, {"project": "beta"})
    d = cfg(world)
    d["project"] = "alpha"
    write_cfg(world.cfg, d)
    got = view.answer("plugins", home=world.home)
    assert next(c["status"] for c in got["changes"] if c["n"] == made["n"]) == "not applied"
    words = (pluginpage.paths.static_dir() / "v2" / "plugins.js").read_text(encoding="utf-8")
    assert 'does not now hold its \\"after\\"' in words                        # the page's words, exactly that


def test_P5_a_record_the_file_holds_is_not_flagged(world):   # must pass
    world.offer()
    made = apply(world.home, KEY, {"project": "beta"})
    got = view.answer("plugins", home=world.home)
    assert next(c["status"] for c in got["changes"] if c["n"] == made["n"]) is None


# ---- item 8: LAST is never written through a link, never reset, and written before the change --------------------------
def test_8_last_as_a_link_is_refused_and_nothing_is_changed(world, tmp_path):   # must refuse
    world.offer()
    target = tmp_path / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    try:
        os.symlink(target, pluginpage.last_file(world.home))
    except (OSError, NotImplementedError):
        pytest.skip("this system does not let the test make a link")
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "beta"})
    with pytest.raises(pluginpage.Refused, match="link"):
        pluginpage.confirm(world.home, e.value.proposal)
    assert cfg(world)["project"] == "alpha" and target.read_text(encoding="utf-8") == "{}"


def test_8_an_unreadable_last_is_never_reset(world):   # must refuse
    world.offer()
    pluginpage.last_file(world.home).write_text("{ not json", encoding="utf-8")
    with pytest.raises(pluginpage.Refused, match="cannot be read"):   # round 8: not even proposed
        pluginpage.change(world.home, KEY, {"project": "beta"})
    assert cfg(world)["project"] == "alpha" and not pluginpage.open_proposals(world.home)
    assert pluginpage.last_file(world.home).read_text(encoding="utf-8") == "{ not json"


def test_8_last_is_written_before_the_change(world, monkeypatch):   # must pass, in that order
    world.offer()
    with pytest.raises(pluginpage.AtTheTerminal) as e:
        pluginpage.change(world.home, KEY, {"project": "beta"})
    seen = []
    monkeypatch.setattr(pluginpage, "_apply", lambda *a: seen.append(pluginpage.last_changes(world.home)))
    pluginpage.confirm(world.home, e.value.proposal)
    assert seen and seen[0]["keys"]["project"]["after"] == {"values": {"project": "beta"}, "absent": []}


# ---- the page's settings form only ever proposes, from every door -------------------------------------------------
def test_the_page_never_writes_settings_from_many_threads(world):   # must refuse, under load too
    world.offer()
    before = world.cfg.read_bytes()
    seen = []

    def go(i):
        try:
            pluginpage.change(world.home, KEY, {"project": f"v{i}"})
        except pluginpage.AtTheTerminal:
            seen.append("proposed")
        except pluginpage.Refused:
            seen.append("refused")
    ts = [threading.Thread(target=go, args=(i,)) for i in range(20)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert world.cfg.read_bytes() == before and "proposed" in seen
