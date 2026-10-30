"""semantext.api 0.2: what the first outside plug-in asked for (docs/plugin-api.md). Each section is one
change, with must-pass and must-refuse arms."""
from __future__ import annotations

import importlib.metadata
import json
import os

import pytest

from semantext import registry
from semantext.sources import load_config, view


class Dist:
    name, version = "semantext-diagrams", "0.1"


class Point:
    def __init__(self, name, make):
        self.name, self.group, self.dist, self._make = name, registry.GROUP, Dist(), make

    def load(self):
        return self._make()


@pytest.fixture
def offered(monkeypatch):
    points = []
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    return points


def turn_on(home, *keys):
    registry.write_enabled({k: {"origin": Dist.name, "version": Dist.version, "at": "2026-10-23T00:00:00Z"}
                            for k in keys}, home)


def sources_file(tmp_path, monkeypatch, value: dict):
    f = tmp_path / "sources.json"
    f.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(f))
    return f


# ---- a plug-in's list setting reaches its read (load_config dropped every list) ---------------------------------
class Readmes:
    kind, name, title, keys = "source", "readmes", "Readmes", ("readmes",)
    seen: list = []

    def read(self, config):
        Readmes.seen.append(config.get("readmes"))
        return {"off": "readmes" not in config, "problems": []}


def test_a_plugin_list_setting_reaches_its_read(home, offered, tmp_path, monkeypatch):   # must pass
    offered.append(Point("source.readmes", Readmes))
    turn_on(home, "source.readmes")
    sources_file(tmp_path, monkeypatch, {"readmes": ["C:\\a\\README.md", "/b/README.md", 3]})
    Readmes.seen.clear()
    view.answer("sources", home=home)
    assert Readmes.seen == [["C:\\a\\README.md", "/b/README.md", 3]]


@pytest.mark.parametrize("value", [[], [["nested"]], [True], [None], [""], ["  "], [float("nan")], [float("inf")],
                                   {"a": 1}, 3, True,
                                   [{"project": "p", "path": {"nested": "x"}}], [{"project": ["a"]}], [{}],
                                   [{"": "x"}], [{"project": True}], [{"project": None}],
                                   [{f"k{i}": "v" for i in range(17)}], ["x"] * 201,
                                   [{"project": "p", "path": "x"}] * 201])
def test_a_list_of_anything_but_plain_values_and_flat_records_is_not_kept(tmp_path, monkeypatch, value):   # refuse
    f = sources_file(tmp_path, monkeypatch, {"readmes": value})
    assert load_config(f, keys=("readmes",)) == {}


@pytest.mark.parametrize("value", [[{"project": "semantext", "path": "C:\\x\\README.md"}, {"project": "b", "path": "/b"}],
                                   [{"project": "p", "n": 3}, "plain", 4], [{f"k{i}": "v" for i in range(16)}],
                                   ["x"] * 200])
def test_a_list_of_flat_records_is_kept_whole(tmp_path, monkeypatch, value):   # must pass: the readmes shape
    f = sources_file(tmp_path, monkeypatch, {"readmes": value})
    assert load_config(f, keys=("readmes",)) == {"readmes": value}


def test_a_setting_that_is_not_kept_is_a_problem_line(home, offered, tmp_path, monkeypatch):   # must refuse, said
    offered.append(Point("source.readmes", Readmes))
    turn_on(home, "source.readmes")
    sources_file(tmp_path, monkeypatch, {"readmes": [{"project": "p", "path": {"nested": 1}}]})
    Readmes.seen.clear()
    got = view.answer("sources", home=home)
    assert Readmes.seen == [None]
    assert [p["kind"] for p in got["frame"]["problems"] if p["reader"] == "readmes"] == ["bad-setting"]


def test_the_readmes_records_reach_the_read(home, offered, tmp_path, monkeypatch):   # must pass
    offered.append(Point("source.readmes", Readmes))
    turn_on(home, "source.readmes")
    rows = [{"project": "semantext", "path": "C:\\x\\README.md"}]
    sources_file(tmp_path, monkeypatch, {"readmes": rows})
    Readmes.seen.clear()
    got = view.answer("sources", home=home)
    assert Readmes.seen == [rows] and not [p for p in got["frame"]["problems"] if p["reader"] == "readmes"]


def test_a_built_in_text_key_still_takes_text_only(tmp_path, monkeypatch):   # must refuse: its reader wants a text
    f = sources_file(tmp_path, monkeypatch, {"seats": ["a.json"], "cards": "c", "readmes": ["r"]})
    assert load_config(f) == {"cards": "c"}
    assert load_config(f, keys=("seats", "readmes")) == {"readmes": ["r"]}


# ---- api.named_roots and api.seat_rows: the kernel's rows, so a plug-in keeps no copy of the rules ---------------
def estate(tmp_path, monkeypatch, group="g"):
    base = tmp_path / "base"
    for d in ("A", "B", "proj", "d"):
        (base / d).mkdir(parents=True)
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({
        "base": str(base),
        "seats": {"A": {"groups": ["g"], "home": "A"}, "B": {"groups": ["h"], "home": "B"},
                  "C": {"groups": ["g", "h"], "home": "../outside"}},
        "roots": [{"name": "proj", "path": "proj", "kind": "repo"}, {"name": "homes", "path": "{home}", "kind": "repo"},
                  {"name": "docs", "path": "d", "kind": "docs"}, {"name": "out", "path": "../out", "kind": "repo"},
                  "not a root"]}), encoding="utf-8")
    (tmp_path / "inbox").mkdir()
    cfg = {"seats": str(seats), "map": str(tmp_path / "no-map.json"), "inbox": str(tmp_path / "inbox")}
    if group:
        cfg["group"] = group
    sources_file(tmp_path, monkeypatch, cfg)
    return base


def test_named_roots_are_the_seats_files_roots_resolved(home, tmp_path, monkeypatch):   # must pass
    from semantext import api
    base = estate(tmp_path, monkeypatch)
    assert api.named_roots(home) == [{"name": "proj", "path": str(base / "proj"), "kind": "repo"},
                                     {"name": "homes", "path": str(base / "A"), "kind": "repo"},
                                     {"name": "docs", "path": str(base / "d"), "kind": "docs"}]
    # the same folders the Places reader makes projects of: one rule, not two
    projects = view.answer("projects", home=home)
    assert {p["path"] for p in view._Sources(home).got["places"]["projects"]} == {str(base / "proj"), str(base / "A")}
    assert projects["place"] == "projects"


def test_a_root_that_steps_out_or_is_not_a_record_is_left_out(home, tmp_path, monkeypatch):   # must refuse
    from semantext import api
    estate(tmp_path, monkeypatch)
    assert "out" not in {r["name"] for r in api.named_roots(home)}
    assert len(api.named_roots(home)) == 3


def test_seat_rows_are_the_waiting_readers(home, tmp_path, monkeypatch):   # must pass
    from semantext import api
    from semantext.sources import cards
    base = estate(tmp_path, monkeypatch, group=None)
    rows = api.seat_rows(home)
    assert rows == [{"seat": "A", "home": str(base / "A"), "groups": ["g"]},
                    {"seat": "B", "home": str(base / "B"), "groups": ["h"]},
                    {"seat": "C", "home": None, "groups": ["g", "h"]}]   # a home outside the base is not followed
    said = cards.load(load_config(tmp_path / "sources.json"))["seats"]
    assert [(s["seat"], s["home"]) for s in said] == [(r["seat"], r["home"]) for r in rows]


def test_seat_rows_keep_to_the_group(home, tmp_path, monkeypatch):   # must refuse the other group's seats
    from semantext import api
    estate(tmp_path, monkeypatch, group="h")
    assert [r["seat"] for r in api.seat_rows(home)] == ["B", "C"]
    assert [r["path"] for r in api.named_roots(home) if r["name"] == "homes"] == [str(tmp_path / "base" / "B")]


@pytest.mark.parametrize("cfg", [None, {}, {"seats": "missing.json"}, {"seats": "BROKEN"}])
def test_no_readable_seats_file_gives_no_rows(home, tmp_path, monkeypatch, cfg):
    from semantext import api
    if cfg is None:
        f = tmp_path / "sources.json"
        f.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("SEMANTEXT_SOURCES", str(f))
    else:
        if cfg.get("seats") == "BROKEN":
            (tmp_path / "broken.json").write_text("[1,", encoding="utf-8")
            cfg = {"seats": str(tmp_path / "broken.json")}
        elif cfg.get("seats"):
            cfg = {"seats": str(tmp_path / cfg["seats"])}
        sources_file(tmp_path, monkeypatch, cfg)
    assert api.named_roots(home) == [] and api.seat_rows(home) == []


# ---- Source.read(config, ctx): the home and the closures, and read(config) still works ---------------------------
class WithCtx:
    kind, name, title, keys = "source", "withctx", "With a context", ("readmes",)
    got: list = []

    def read(self, config, ctx):
        WithCtx.got.append(ctx)
        return {"off": False, "problems": []}


class Plain:
    kind, name, title, keys = "source", "plain", "Plain", ("readmes",)
    calls = 0

    def read(self, config):   # api 0.1's shape: called with the config alone
        Plain.calls += 1
        return {"off": False, "problems": []}


def test_a_read_that_takes_a_context_gets_the_home_and_the_closures(home, offered, tmp_path, monkeypatch):
    from semantext import api
    shut = tmp_path / "Private"
    shut.mkdir()
    offered += [Point("source.withctx", WithCtx), Point("source.plain", Plain)]
    turn_on(home, "source.withctx", "source.plain")
    sources_file(tmp_path, monkeypatch, {"readmes": "x", "closed": [str(shut)]})
    WithCtx.got.clear()
    Plain.calls = 0
    view.answer("sources", home=home)
    (ctx,) = WithCtx.got
    assert isinstance(ctx, api.ReadContext) and ctx.home == str(home) and ctx.closures == (str(shut),)
    assert api.is_closed_place(shut / "a.md", ctx) and not api.is_closed_place(tmp_path / "open.md", ctx)
    assert Plain.calls == 1   # must pass: the 0.1 shape is not broken


@pytest.mark.parametrize("read, takes", [(lambda self, config: 0, False), (lambda self, config, ctx: 0, True),
                                         (lambda self, config, ctx=None: 0, True), (lambda self, *a: 0, True),
                                         (lambda self, config, *, ctx=None: 0, False), (len, False)])
def test_the_signature_decides_once_at_registration(read, takes):
    obj = type("S", (), {"kind": "source", "name": "s", "keys": (), "read": read})()
    entry = registry.Registry().add("source", "s", obj, origin="pkg")
    assert entry.reads_ctx is takes


def test_is_closed_place_judges_by_the_contexts_closures_not_the_file(tmp_path, monkeypatch):
    from semantext import api
    shut = tmp_path / "Private"
    sources_file(tmp_path, monkeypatch, {"closed": []})             # the file closes nothing
    assert api.is_closed_place(shut / "a.md", api.ReadContext("h", (str(shut),)))   # must refuse: ctx closes it
    assert api.is_closed_place(tmp_path / "b.md", api.ReadContext("h", None))      # unknown closures close all
    assert not api.is_closed_place(tmp_path / "b.md", api.ReadContext("h", ()))
    sources_file(tmp_path, monkeypatch, {"closed": [str(shut)]})
    assert not api.is_closed_place(shut / "a.md", api.ReadContext("h", ()))   # the context, not a re-read of the file
    assert api.is_closed_place(shut / "a.md")                                # no context: the file, as in 0.1


def test_named_roots_take_a_context(home, tmp_path, monkeypatch):
    from semantext import api
    from semantext.sources import closed
    estate(tmp_path, monkeypatch)
    assert api.named_roots(closed.context(home)) == api.named_roots(home) != []
    assert api.seat_rows(closed.context(home)) == api.seat_rows(home) != []


# ---- is_closed_place and the \\?\ prefix (finding 2 of the attack on the first outside plug-in) ------------------
windows_only = pytest.mark.skipif(os.name != "nt", reason="the \\\\?\\ prefix and these spellings are Windows paths")


def _shut(tmp_path, monkeypatch):
    shut = tmp_path / "closedfolder"
    shut.mkdir()
    (shut / "README.md").write_text("x", encoding="utf-8")
    sources_file(tmp_path, monkeypatch, {"closed": [str(shut)]})
    return shut, str(shut / "README.md")


@windows_only
@pytest.mark.parametrize("spell", [lambda s: "\\\\?\\" + s, lambda s: "//?/" + s.replace("\\", "/"),
                                   lambda s: "\\\\?/" + s, lambda s: "//?\\" + s])
def test_a_file_written_with_the_long_path_prefix_is_closed(tmp_path, monkeypatch, spell):   # fails on 2fc2736
    from semantext import api
    _, f = _shut(tmp_path, monkeypatch)
    assert api.is_closed_place(spell(f))


@windows_only
def test_the_unc_long_path_prefix_is_the_share_it_names(tmp_path, monkeypatch):
    from semantext import api
    from semantext.sources import closed
    sources_file(tmp_path, monkeypatch, {"closed": ["\\\\host\\share\\private"]})
    for spelled in ("\\\\?\\UNC\\host\\share\\private\\a.md", "//?/unc/host/share/private/a.md"):
        assert closed._unprefixed(spelled.replace("/", "\\")).lower() == "\\\\host\\share\\private\\a.md"
        assert api.is_closed_place(spelled)                                       # must refuse
    # since the audit of 784faf6 (finding 2), any share path is closed while a closure exists: a share can name a
    # closed folder's bytes by a spelling no comparison sees (tests/test_api02_round2.py has the open arms)
    assert api.is_closed_place("\\\\?\\UNC\\host\\share\\public\\a.md")


@windows_only
def test_a_closure_written_with_the_prefix_closes_the_plain_spelling(tmp_path, monkeypatch):
    from semantext import api
    shut = tmp_path / "closedfolder"
    shut.mkdir()
    sources_file(tmp_path, monkeypatch, {"closed": ["\\\\?\\" + str(shut)]})
    assert api.is_closed_place(shut / "README.md") and not api.is_closed_place(tmp_path / "open.md")


def _short(path: str) -> str | None:
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(path, buf, 1024)
    return buf.value if 0 < n < 1024 and buf.value != path else None


@windows_only
@pytest.mark.parametrize("arm", ["plain", "mixed-case", "forward", "dot-segment", "trailing-dot", "trailing-space",
                                 "short", "junction", "device", "stream"])
def test_every_other_spelling_of_a_closed_file_stays_closed(tmp_path, monkeypatch, arm):   # must pass
    from semantext import api
    shut, f = _shut(tmp_path, monkeypatch)
    if arm == "junction":
        import _winapi
        _winapi.CreateJunction(str(shut), str(tmp_path / "door"))
    spelled = {"plain": lambda: f, "mixed-case": lambda: f.swapcase(), "forward": lambda: f.replace("\\", "/"),
               "dot-segment": lambda: str(shut) + "\\.\\x\\..\\README.md",
               "trailing-dot": lambda: str(shut) + ".\\README.md", "trailing-space": lambda: str(shut) + " \\README.md",
               "short": lambda: _short(f), "junction": lambda: str(tmp_path / "door" / "README.md"),
               "device": lambda: "\\\\.\\" + f, "stream": lambda: f + ":hidden"}[arm]()
    if spelled is None:
        pytest.skip("this volume makes no 8.3 names")
    assert api.is_closed_place(spelled)


def test_a_file_outside_the_closed_folder_stays_open(tmp_path, monkeypatch):   # must pass
    from semantext import api
    _shut(tmp_path, monkeypatch)
    outside = str(tmp_path / "open" / "README.md")
    assert not api.is_closed_place(outside)
    if os.name == "nt":
        assert not api.is_closed_place("\\\\?\\" + outside) and not api.is_closed_place("//?/" + outside)


# ---- api.inside_roots: the one "inside a named root" judgement ---------------------------------------------------
@pytest.fixture
def rooted(home, tmp_path, monkeypatch):
    base = tmp_path / "base"
    (base / "d" / "secret").mkdir(parents=True)
    (base / "A").mkdir()
    (base / "d" / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / "outside.md").write_text("x", encoding="utf-8")
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"base": str(base), "seats": {"A": {"home": "A"}},
                                 "roots": [{"name": "docs", "path": "d", "kind": "repo"}]}), encoding="utf-8")
    sources_file(tmp_path, monkeypatch, {"seats": str(seats), "closed": [str(base / "d" / "secret")]})
    return base


def test_a_file_inside_a_named_root_is_inside(home, rooted):   # must pass
    from semantext import api
    assert api.inside_roots(rooted / "d" / "README.md", home)
    assert api.inside_roots(str(rooted / "d" / "README.md"), api.ReadContext(str(home), ()))


def test_a_file_outside_every_root_is_outside(home, rooted, tmp_path):   # must refuse
    from semantext import api
    assert not api.inside_roots(tmp_path / "outside.md", home) and not api.inside_roots(rooted / "A" / "x", home)
    assert not api.inside_roots("", home) and not api.inside_roots(None, home)


def test_a_dot_dot_escape_is_outside(home, rooted):   # must refuse
    from semantext import api
    assert not api.inside_roots(str(rooted / "d") + os.sep + ".." + os.sep + ".." + os.sep + "outside.md", home)


def test_a_link_inside_a_root_that_leads_out_is_outside(home, rooted, tmp_path):   # must refuse
    from semantext import api
    door = rooted / "d" / "door"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(tmp_path), str(door))
        else:
            door.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot make a link")
    assert not api.inside_roots(door / "outside.md", home)


@windows_only
def test_a_prefixed_spelling_is_judged_as_the_path_it_names(home, rooted, tmp_path):
    from semantext import api
    assert api.inside_roots("\\\\?\\" + str(rooted / "d" / "README.md"), home)               # must pass
    assert api.inside_roots("//?/" + str(rooted / "d" / "README.md").replace("\\", "/"), home)
    assert not api.inside_roots("\\\\?\\" + str(tmp_path / "outside.md"), home)              # must refuse


def test_a_closed_place_inside_a_root_is_not_inside(home, rooted):   # must refuse: closures win
    from semantext import api
    assert not api.inside_roots(rooted / "d" / "secret" / "x.md", home)
    assert not api.inside_roots(rooted / "d" / "README.md", api.ReadContext(str(home), None))   # closures unknown


def test_the_serve_hook_and_the_api_judge_alike(home, rooted, tmp_path):
    from semantext import docserve
    from semantext.sources import kernel
    assert docserve.kernel.inside_named_root is kernel.inside_named_root
    for p in (rooted / "d" / "README.md", rooted / "d" / "secret" / "x.md", tmp_path / "outside.md"):
        from semantext import api
        assert api.inside_roots(p, home) == kernel.inside_named_root(p, home)


# ---- api.taken_names ---------------------------------------------------------------------------------------------
def test_taken_names_hold_the_built_ins_and_what_is_installed(home, offered):   # must pass
    from semantext import api
    offered.append(Point("place.diagrams", lambda: (_ for _ in ()).throw(AssertionError("no code may run"))))
    places = api.taken_names("place")
    assert {"waiting", "map", "rules", "diagrams"} <= set(places) and places == sorted(places)
    assert "waiting" in api.taken_names("source") and "runs" in api.taken_names("checker")
    every = api.taken_names()
    assert "place.diagrams" in every and "source.waiting" in every and "checker.guards" in every
    assert api.taken_names("door") == []


def test_taken_names_refuse_a_kind_that_does_not_exist(offered):   # must refuse
    from semantext import api
    with pytest.raises(ValueError):
        api.taken_names("widget")
