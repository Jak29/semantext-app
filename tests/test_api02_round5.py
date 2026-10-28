"""The Fable 5.1 review of api 0.2 at 70f2d3c (h-113): each test fails at 70f2d3c and says whether its arm must pass
or must refuse."""
from __future__ import annotations

import json
import os
import threading

import pytest

from semantext import outside, registry
from test_doc_route import estate  # noqa: F401  (a fixture)


@pytest.fixture
def offered(monkeypatch, home, tmp_path):
    """offer("<kind>.<name>", obj, dist="name"): an installed package of that name declaring obj, turned on in the home."""
    import importlib.metadata
    points = []
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"closed": []}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))

    class Dist:
        def __init__(self, name, version="1.0"):
            self.name, self.version, self.files = name, version, None

    class Point:
        def __init__(self, name, obj, dist):
            self.name, self.group, self.dist, self._obj = name, registry.GROUP, dist, obj

        def load(self):
            return self._obj

    def offer(key, obj, dist="semantext-probe", on=True):
        points.append(Point(key, obj, Dist(dist)))
        if on:
            registry.write_enabled({p.name: {"origin": p.dist.name, "version": p.dist.version, "at": "x"}
                                    for p in points}, home)
    return offer


# ---- item 1. a distribution named "built-in" is an outside plug-in like any other ------------------------------------
class _Seen:
    def __init__(self):
        self.threads = []


def _source(name, seen):
    def read(self, config, ctx):
        seen.threads.append(threading.current_thread().name)
        return {"off": False, "problems": []}
    return type("S", (), {"kind": "source", "name": name, "title": name, "keys": (), "read": read})()


def _place(name, seen, **more):
    def build(self, sources, ctx):
        seen.threads.append(threading.current_thread().name)
        return {"fine": True}
    return type("P", (), {"kind": "place", "name": name, "title": name, "build": build, **more})()


def test_a_package_named_built_in_is_not_a_built_in(home, offered):   # must refuse: no guard is switched off
    from semantext.sources import view
    seen = _Seen()
    offered("source.foo", _source("foo", seen), dist="built-in")
    offered("place.board", _place("board", seen), dist="built-in")
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "foo").builtin is False and reg.get("place", "board").builtin is False
    assert reg.get("source", "waiting").builtin is True
    got = view.answer("board", home=home)
    assert got["fine"] is True
    # its read and its build ran in the worker, under the budget, as every outside plug-in's do
    assert seen.threads and all(t == "semantext-plugin" for t in seen.threads)
    assert "board" in [p["name"] for p in got["frame"]["outside"]]   # shown as a place the person turned on


def test_a_package_named_built_in_has_its_documents_served_as_an_outside_place(home, offered):   # must pass
    from semantext import docserve
    seen = _Seen()
    offered("place.board", _place("board", seen, resolve=lambda self, row: None,
                                  check_bytes=lambda self, data: None), dist="built-in")
    assert docserve._place("board", home) is not None   # before: refused as a built-in (404)


def test_the_built_in_flag_is_only_for_the_packages_own_code():   # must refuse
    seen = _Seen()
    with pytest.raises(ValueError, match="Semantext's own"):
        registry.Registry().add("source", "foo", _source("foo", seen))   # no origin: asks to be a built-in
    e = registry.Registry().add("source", "foo", outside.snapshot(_source("foo", seen)), origin=registry.BUILT_IN)
    assert e.builtin is False   # the words "built-in" given as an origin make nothing built-in


def test_enable_names_the_package_a_built_in_named_plug_in_comes_from(home, offered, monkeypatch):   # must pass
    from semantext import plugincmd
    monkeypatch.setattr("semantext.plugincmd.human_terminal", lambda: None)
    offered("source.foo", _source("foo", _Seen()), dist="built-in", on=False)
    said = []
    plugincmd._enable("source.foo", home, said.append, ask=lambda _: "source.foo")
    first = said[0]
    assert "installed package" in first and "built-in 1.0" in first
    assert "from built-in 1.0" not in first


def test_list_never_shows_a_package_named_built_in_as_on_for_a_built_ins_name(home, offered):   # must refuse
    from semantext import plugincmd
    seen = _Seen()
    offered("source.waiting", _source("waiting", seen), dist="built-in")
    said = []
    plugincmd._list(home, said.append)
    row = next(line for line in said if line.split()[:2] == ["source", "waiting"] and "1.0" in line)
    assert not row.rstrip().endswith(" on")


# ---- item 2. a failed call never comes back as None, and a check passes only on its explicit pass --------------------
class _Unsayable:
    def __repr__(self):
        raise ValueError("no words")

    __str__ = __repr__


class _Odd(BaseException):
    def __str__(self):
        raise RuntimeError("no words either")


@pytest.mark.parametrize("raised", [SystemExit(_Unsayable()), SystemExit(1), _Odd(), KeyboardInterrupt(),
                                    GeneratorExit()])
def test_a_call_that_raises_anything_is_an_error_never_none(raised):   # must refuse
    def call():
        raise raised
    with pytest.raises(RuntimeError):
        outside.run(call, owner="place.p")


def test_a_call_that_gives_none_still_gives_none():   # must pass: None is a plug-in's own answer
    assert outside.run(lambda: None, owner="place.p") is None


def test_a_worker_that_leaves_no_answer_and_no_error_is_an_error(monkeypatch):   # must refuse
    monkeypatch.setattr(outside, "_said", lambda e: (_ for _ in ()).throw(ValueError("cannot say")))

    def call():
        raise SystemExit(2)
    with pytest.raises(RuntimeError):
        outside.run(call, owner="place.p")


def test_a_check_that_raises_systemexit_with_an_unsayable_code_refuses_the_document(estate, monkeypatch):   # refuse
    from test_doc_route import Diagrams
    from semantext import docserve

    def check(self, data):
        raise SystemExit(_Unsayable())
    monkeypatch.setattr(Diagrams, "check_bytes", check)
    with pytest.raises(docserve.Refused) as e:
        docserve.serve("diagrams", "r1", estate["home"])
    assert e.value.status == 409


def test_serve_passes_a_document_only_on_the_checks_explicit_pass(estate, monkeypatch):   # must refuse
    from semantext import docserve
    real = outside.run

    def run(fn, *args, **kw):   # a run that hands back None for the check, as a lost answer did
        if getattr(fn, "__name__", "") == "check_bytes":
            return None
        return real(fn, *args, **kw)
    monkeypatch.setattr(docserve.outside, "run", run)
    with pytest.raises(docserve.Refused) as e:
        docserve.serve("diagrams", "r1", estate["home"])
    assert e.value.status == 409
    monkeypatch.setattr(docserve.outside, "run", real)
    assert docserve.serve("diagrams", "r1", estate["home"])[1] == "image/svg+xml"   # its None, said by itself, passes

# ---- item 3. a requests file that is a link, or in a closed place, is not read ----------------------------------------
def _ask(i="d1"):
    return {"kind": "decision", "id": i, "title": "t", "why": "w", "question": "q?", "options": ["a", "b"],
            "at": "2026-10-24T10:00:00Z"}


@pytest.fixture
def seats(tmp_path, monkeypatch):
    from test_sources_cards import World
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    monkeypatch.setenv("SEMANTEXT_HOME", str(tmp_path / "no-home"))   # no sources file: nothing is closed
    return World(tmp_path)


def test_a_requests_file_that_is_a_hard_link_is_not_read(seats, tmp_path):   # must refuse
    import os
    from semantext.sources import cards
    other = tmp_path / "elsewhere.jsonl"
    other.write_text(json.dumps(_ask("theirs")) + "\n", encoding="utf-8")
    try:
        os.link(other, seats.file("Alder"))
    except OSError as e:
        pytest.skip(f"no hard link here: {e}")
    got = cards.load(seats.cfg())
    assert not [c for c in got["cards"] if c["seat"] == "Alder"]
    said = [p for p in got["problems"] if p["kind"] == "link" and "Alder" in p["text"]]
    assert said and "hard link" in said[0]["text"]


def test_a_requests_file_that_is_a_symbolic_link_is_not_read(seats, tmp_path):   # must refuse
    from semantext.sources import cards
    other = tmp_path / "elsewhere.jsonl"
    other.write_text(json.dumps(_ask("theirs")) + "\n", encoding="utf-8")
    try:
        seats.file("Alder").symlink_to(other)
    except OSError as e:
        pytest.skip(f"no symbolic link here: {e}")
    got = cards.load(seats.cfg())
    assert not [c for c in got["cards"] if c["seat"] == "Alder"]
    assert [p for p in got["problems"] if p["kind"] == "link" and "Alder" in p["text"]]


def test_a_requests_file_in_a_closed_place_is_not_read(seats, tmp_path, monkeypatch):   # must refuse
    from semantext.sources import cards
    seats.put("Alder", _ask("a1"))
    seats.put("Birch", _ask("b1"))
    src = tmp_path / "sources.json"
    src.write_text(json.dumps({"closed": [str(seats.file("Alder").parent)]}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(src))
    got = cards.load(seats.cfg())
    assert [c["id"] for c in got["cards"]] == ["b1"]   # the open seat is read as before
    assert [p for p in got["problems"] if p["kind"] == "closed-place" and "Alder" in p["text"]]


def test_the_closures_are_read_beside_the_sources_file_the_config_came_from(seats, tmp_path):   # must refuse
    from semantext.sources import cards
    seats.put("Alder", _ask("a1"))
    seats.put("Birch", _ask("b1"))
    started = tmp_path / "started-home"   # the home the page was started with, not the default one
    started.mkdir()
    (started / "sources.json").write_text(json.dumps({"closed": [str(seats.file("Alder").parent)]}), encoding="utf-8")
    got = cards.load({**seats.cfg(), "_file": str(started / "sources.json")})
    assert [c["id"] for c in got["cards"]] == ["b1"]


def test_a_requests_file_that_is_a_plain_file_is_read(seats):   # must pass
    from semantext.sources import cards
    seats.put("Alder", _ask("a1"))
    got = cards.load(seats.cfg())
    assert [c["id"] for c in got["cards"]] == ["a1"] and not [p for p in got["problems"] if p["kind"] == "link"]

# ---- item 4. an .identity file at the cap is read in time linear in its lines ------------------------------------------
def _identity_at_cap(folder, line):
    """An .identity file of distinct lines, as many as fit under MAX_IDENTITY."""
    from semantext.sources import places
    out, size, i = [], 0, 0
    while True:
        text = line(i) + "\n"
        if size + len(text) > places.MAX_IDENTITY:
            break
        out.append(text)
        size += len(text)
        i += 1
    (folder / ".identity").write_text("".join(out), encoding="utf-8", newline="\n")
    return i


def _case_variant(i: int, local: str = "abcdefghijklmnopqrst") -> str:
    return "".join(c.upper() if i >> k & 1 else c for k, c in enumerate(local))


def test_an_identity_file_of_others_at_the_cap_is_read_in_linear_time(tmp_path):   # must pass, quickly
    import time
    from semantext.sources import places
    n = _identity_at_cap(tmp_path, lambda i: f"Person {i} <p{i}@example.test>")
    assert n > 25_000   # quadratic: near a minute at this many
    start = time.perf_counter()
    got = places._project("p", "r", str(tmp_path), [], {}, [])
    took = time.perf_counter() - start
    assert len(got["others"]) == n
    assert took < 5, f"{n} lines took {took:.1f} s"   # before: quadratic in the lines


def test_an_identity_file_of_one_agents_case_variants_at_the_cap_is_read_in_linear_time(tmp_path):   # must pass
    import time
    from semantext.sources import places
    agents = [{"id": "agent:a", "name": "A", "home": None, "placed": {"projects": []}}]
    by_email = {"abcdefghijklmnopqrst@example.test": [0]}
    n = _identity_at_cap(tmp_path, lambda i: f"A <{_case_variant(i)}@example.test>")
    assert n > 25_000
    start = time.perf_counter()
    got = places._project("p", "r", str(tmp_path), agents, by_email, [])
    took = time.perf_counter() - start
    assert len(got["members"][0]["emails"]) == n
    assert took < 5, f"{n} lines took {took:.1f} s"


def test_an_identity_file_keeps_each_other_once_in_order(tmp_path):   # must refuse a repeat, keep the order
    from semantext.sources import places
    (tmp_path / ".identity").write_text("B <b@x.test>\nA <a@x.test>\nB <B@X.test>\nB2 <b@x.test>\nA <a@x.test>\n",
                                        encoding="utf-8")
    got = places._project("p", "r", str(tmp_path), [], {}, [])
    assert got["others"] == [{"name": "B", "email": "b@x.test"}, {"name": "A", "email": "a@x.test"},
                             {"name": "B2", "email": "b@x.test"}]

# ---- item 5. a seats file's path never leaves its base ------------------------------------------------------------------
ESCAPES = ["D:\\other", "D:other", "\\Windows", "/etc", "\\\\srv\\share\\x", "//srv/share/x", "\\\\?\\C:\\x"]


@pytest.mark.parametrize("rel", ESCAPES)
def test_a_seat_home_or_root_that_names_its_own_start_is_refused_in_places(tmp_path, rel):   # must refuse
    from semantext.sources import places
    problems = []
    assert places._under(str(tmp_path), rel, "seats.json", "A's home", problems) is None
    assert problems and problems[0]["kind"] == "bad-path"


@pytest.mark.parametrize("rel", ["A", "teams/cedar", "teams\\cedar"])
def test_a_seat_home_under_the_base_is_kept_in_places(tmp_path, rel):   # must pass
    from semantext.sources import places
    problems = []
    got = places._under(str(tmp_path), rel, "seats.json", "A's home", problems)
    assert got is not None and not problems
    assert os.path.normcase(got).startswith(os.path.normcase(str(tmp_path)))


def test_a_full_path_with_no_base_is_kept_in_places(tmp_path):   # must pass: with no base, a path is written in full
    from semantext.sources import places
    assert places._under(None, str(tmp_path / "A"), "seats.json", "A's home", []) == str(tmp_path / "A")


def _roots(tmp_path, rel):
    from semantext.sources.gates import discover
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"base": str(tmp_path), "seats": {"A": {"home": rel}},
                                 "roots": [{"name": "r", "path": rel, "kind": "repo"},
                                           {"name": "home", "path": "{home}", "kind": "repo"}]}), encoding="utf-8")
    problems = []
    found, _ = discover.read_roots(str(seats), problems)
    return found, problems


@pytest.mark.parametrize("rel", ESCAPES)
def test_a_root_or_home_that_names_its_own_start_is_refused_in_gates(tmp_path, rel):   # must refuse
    found, problems = _roots(tmp_path, rel)
    assert found == [] and len(problems) == 2 and all(p["kind"] == "bad-path" for p in problems)


def test_a_root_and_home_under_the_base_are_kept_in_gates(tmp_path):   # must pass
    found, problems = _roots(tmp_path, "A")
    assert [(n, s, str(f)) for n, s, f in found] == [("r", None, str(tmp_path / "A")), ("home", "A", str(tmp_path / "A"))]
    assert not problems


def test_places_and_gates_use_one_join():   # the same helper, so the two never judge one path apart
    import inspect
    from semantext import sources
    from semantext.sources import places
    from semantext.sources.gates import discover
    assert "under(" in inspect.getsource(places._under) and sources.under is discover.under

# ---- item 6. a write from a plug-in's page module path is refused (the server-side guard; the sandbox is designed) -----
@pytest.fixture
def served(store):
    from semantext.server import make_server
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def _post(srv, path, body, **headers):
    import urllib.error
    import urllib.request
    port = srv.server_address[1]
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "X-Semantext": "1",
                                          "Origin": f"http://127.0.0.1:{port}", **headers})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


SETTING = {"key": "feed", "on": False}


def test_a_write_from_the_page_itself_is_accepted(served):   # must pass
    port = served.server_address[1]
    assert _post(served, "/api/setting", SETTING, Referer=f"http://127.0.0.1:{port}/v2",
                 **{"Sec-Fetch-Dest": "empty", "Sec-Fetch-Site": "same-origin"}) == 200
    assert _post(served, "/api/setting", SETTING) == 200   # a client that sends neither header, as before


@pytest.mark.parametrize("path", ["/v2/plugin/board.js", "/v2/plugin/board.js?x=1", "/v2/plugin/"])
def test_a_write_whose_referer_is_a_plug_in_module_is_refused(served, path):   # must refuse
    port = served.server_address[1]
    assert _post(served, "/api/setting", SETTING, Referer=f"http://127.0.0.1:{port}{path}") == 403
    assert _post(served, "/api/answer", {"id": 1, "choice": "a"}, Referer=f"http://127.0.0.1:{port}{path}") == 403


@pytest.mark.parametrize("dest", ["script", "worker", "sharedworker", "serviceworker", "iframe", "document", "frame"])
def test_a_write_that_is_not_a_plain_fetch_is_refused(served, dest):   # must refuse
    assert _post(served, "/api/setting", SETTING, **{"Sec-Fetch-Dest": dest}) == 403

# ---- item 7, the lows: the calls into plug-ins ---------------------------------------------------------------------
def _plugin_threads() -> int:
    return sum(t.name == "semantext-plugin" and t.is_alive() for t in threading.enumerate())


@pytest.fixture
def release():
    ev = threading.Event()
    yield ev
    ev.set()


def _many(calls):
    """Each of `calls` on its own thread at once: what each gave, or the name of what it raised."""
    out = []

    def one(call):
        try:
            out.append(call())
        except outside.Late as e:
            out.append(type(e).__name__)
    ts = [threading.Thread(target=one, args=(c,)) for c in calls]
    for t in ts:
        t.start()
    for t in ts:
        t.join(20)
    return out


def test_the_callers_waiting_for_a_turn_are_bounded(monkeypatch, release):   # must refuse the rest at once
    import time
    monkeypatch.setattr(outside, "MAX_IN_FLIGHT", 1)
    monkeypatch.setattr(outside, "MAX_WAITING", 2)
    held = threading.Thread(target=lambda: outside.run(lambda: release.wait(10), owner="place.p", budget=5))
    held.start()
    time.sleep(0.1)
    started = time.monotonic()
    got = _many([lambda: outside.run(lambda: "x", owner="place.p", budget=1.0)] * 6)
    assert sorted(got) == ["Crowded"] * 4 + ["Late"] * 2   # two waited their budget; four were refused at once
    assert not any(isinstance(x, str) and x == "Busy" for x in got)
    assert time.monotonic() - started < 3
    release.set()
    held.join(5)


def test_a_crowded_call_is_late_never_busy():   # must pass: a full line is not a hanging plug-in
    assert issubclass(outside.Crowded, outside.Late) and not issubclass(outside.Crowded, outside.Busy)


def test_threads_past_their_budget_never_pass_the_cap_however_many_plug_ins(monkeypatch, release):   # must refuse
    monkeypatch.setattr(outside, "MAX_HANGING", 4)
    peak = []

    def call():
        peak.append(_plugin_threads())
        release.wait(1.0)
        return "late"
    owners = [f"source.s{i}" for i in range(4)]
    _many([(lambda o=o: outside.run(call, owner=o, budget=0.2)) for o in owners for _ in range(4)])
    assert max(peak) <= outside.MAX_HANGING
    assert sum(outside.holding().values()) <= outside.MAX_HANGING
    assert _plugin_threads() <= outside.MAX_HANGING


def test_the_in_flight_comment_says_how_long_a_caller_waits():   # must pass: the stale words are gone
    import inspect
    text = inspect.getsource(outside)
    assert "one more waits its turn, inside its own budget" not in text


def test_loading_a_plug_in_is_held_to_the_budget(home, offered, monkeypatch, release):   # must refuse the stall
    import time
    from semantext.sources import view
    monkeypatch.setenv("SEMANTEXT_PLUGIN_SECONDS", "0.3")
    seen = _Seen()
    offered("source.foo", _source("foo", seen))
    point = __import__("importlib.metadata").metadata.entry_points(group=registry.GROUP)[0]
    point.load = lambda: (release.wait(10), _source("foo", seen))[1]
    started = time.monotonic()
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert time.monotonic() - started < 3
    assert reg.get("source", "foo") is None
    assert [p for p in reg.problems if p["kind"] == "failed to load" and "Late" in p["text"]]


def test_a_read_that_cannot_be_called_is_refused_once_never_asked_again(home, offered):   # must refuse, plainly
    from semantext.sources import view
    todo = type("S", (), {"kind": "source", "name": "foo", "title": "foo", "keys": (), "read": "todo"})()
    offered("source.foo", todo)
    reg = registry.load_enabled(view.BUILT_IN, home)
    assert reg.get("source", "foo") is None
    said = [p for p in reg.problems if p["source"] == "plug-in source.foo"]
    assert said and said[0]["kind"] == "refused" and "cannot be called" in said[0]["text"]
    assert "asked again" not in json.dumps(view.answer("sources", home=home)["frame"]["problems"])

# ---- item 7, the lows: what the page says, and how much a reader reads -------------------------------------------
def test_a_plug_in_sources_problem_never_passes_as_a_built_in_readers(home, offered):   # must refuse the disguise
    from semantext.sources import view

    def read(self, config, ctx):
        return {"off": False, "problems": [{"reader": "waiting", "source": "requests.jsonl", "line": 1,
                                            "kind": "bad json", "text": "looks like the Waiting reader's"}]}
    offered("source.foo", type("S", (), {"kind": "source", "name": "foo", "title": "foo", "keys": (), "read": read})())
    got = view.answer("sources", home=home)["frame"]["problems"]
    said = [p for p in got if p.get("text") == "looks like the Waiting reader's"]
    assert len(said) == 1 and said[0]["reader"] == "foo"
    assert said[0]["source"].startswith("plug-in source.foo") and "requests.jsonl" in said[0]["source"]


def test_read_lines_reads_no_more_than_its_cap(tmp_path, monkeypatch):   # must refuse a file over the cap
    import semantext.sources as sources
    monkeypatch.setattr(sources, "MAX_FILE", 1024)
    big = tmp_path / "big.jsonl"
    big.write_bytes(b'{"a": 1}\n' * 200)
    with pytest.raises(OSError, match="over"):
        list(sources.read_lines(big))
    small = tmp_path / "small.jsonl"
    small.write_bytes(b'{"a": 1}\n' * 10)   # must pass
    assert [n for n, _ in sources.read_lines(small)] == list(range(1, 11))

# ---- item 7, the lows: the gates reader's repository files ----------------------------------------------------------
def test_a_commondir_holding_a_nul_is_a_problem_never_a_raise(tmp_path):   # must refuse, and say why
    from semantext.sources.gates import discover
    from test_sources_gates import repo
    top = repo(tmp_path / "base", "r")
    (top / ".git" / "commondir").write_bytes(b"../x\x00y\n")
    why = discover.git_dir_problem(top / ".git")
    assert isinstance(why, str) and "NUL" in why


def _format(tmp_path, text):
    from semantext.sources.gates import discover
    from test_sources_gates import touch, world
    common = tmp_path / "g"
    touch(common / "config", text)
    return discover.RepositoryReader(world(tmp_path), [])._read_format(common)


@pytest.mark.parametrize("ext", ["refStorage = files", "refStorage = reftable", "relativeWorktrees = true"])
def test_the_later_extensions_at_format_0_are_ignored_as_this_git_ignores_them(tmp_path, ext):   # must pass
    got = _format(tmp_path, f"[core]\n\trepositoryformatversion = 0\n[extensions]\n\t{ext}\n")
    assert got.refused == ()


@pytest.mark.parametrize("ext, name, since", [("refStorage = reftable", "refStorage", "2.45"),
                                              ("relativeWorktrees = true", "relativeWorktrees", "2.48")])
def test_the_later_extensions_at_format_1_are_refused_by_name_never_as_unknown(tmp_path, ext, name, since):   # refuse
    got = _format(tmp_path, f"[core]\n\trepositoryformatversion = 1\n[extensions]\n\t{ext}\n")
    assert len(got.refused) == 1 and "unknown" not in got.refused[0]
    assert f"extensions.{name}" in got.refused[0] and f"git {since}" in got.refused[0] and "2.39" in got.refused[0]