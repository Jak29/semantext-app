"""The serve hook by row (api 0.2): /api/v2/doc/<place>/<row_id> for an enabled outside place. No path from the
request reaches the file system; at serve time the path the place resolves is re-checked (inside a named root, not in
a closed place) and the bytes read once are the bytes its check sees. Each arm says whether it must pass or refuse."""
from __future__ import annotations

import importlib.metadata
import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from semantext import docserve, registry
from semantext.server import make_server

SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></svg>'
PAGE = {"X-Semantext": "1"}


class Dist:
    name, version = "semantext-diagrams", "0.1"


class Point:
    def __init__(self, name, make):
        self.name, self.group, self.dist, self._make = name, registry.GROUP, Dist(), make

    def load(self):
        return self._make()


class Diagrams:
    kind, name, title = "place", "diagrams", "Diagrams"
    rows: dict = {}
    asked: list = []

    def build(self, sources):
        return {"rows": sorted(self.rows)}

    def resolve(self, row_id):
        Diagrams.asked.append(row_id)
        return self.rows.get(row_id)

    def check_bytes(self, data):
        return "it holds a script" if b"<script" in data else None


PLACE = Diagrams()


class NoServe:
    kind, name, title = "place", "board", "Board"

    def build(self, sources):
        return {}


@pytest.fixture
def estate(home, tmp_path, monkeypatch):
    """A base with one named root (d) holding a diagram and a closed folder, a file outside every root, and the
    Diagrams place installed and turned on."""
    base = tmp_path / "base"
    (base / "d" / "secret").mkdir(parents=True)
    (base / "A").mkdir()
    ok = base / "d" / "flow.svg"
    ok.write_bytes(SVG)
    shut = base / "d" / "secret" / "hidden.svg"
    shut.write_bytes(SVG)
    out = tmp_path / "outside.svg"
    out.write_bytes(SVG)
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"base": str(base), "seats": {"A": {"home": "A"}},
                                 "roots": [{"name": "docs", "path": "d", "kind": "repo"}]}), encoding="utf-8")
    cfg = tmp_path / "sources.json"
    cfg.write_text(json.dumps({"seats": str(seats), "closed": [str(base / "d" / "secret")]}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(cfg))
    points = [Point("place.diagrams", lambda: PLACE), Point("place.board", NoServe)]
    monkeypatch.setattr(importlib.metadata, "entry_points",
                        lambda **kw: [p for p in points if kw.get("group") == registry.GROUP])
    registry.write_enabled({"place.diagrams": {"origin": Dist.name, "version": Dist.version, "at": "x"},
                            "place.board": {"origin": Dist.name, "version": Dist.version, "at": "x"}}, home)
    Diagrams.rows = {"r1": str(ok), "closed": str(shut), "out": str(out), "relative": "d/flow.svg"}
    Diagrams.asked = []
    return {"base": base, "ok": ok, "out": out, "home": home, "tmp": tmp_path}


def refused(place, row, home) -> int:
    with pytest.raises(docserve.Refused) as e:
        docserve.serve(place, row, home)
    return e.value.status


def test_a_row_of_an_enabled_place_is_served_as_its_bytes(estate):   # must pass
    data, ctype = docserve.serve("diagrams", "r1", estate["home"])
    assert data == SVG and ctype == "image/svg+xml" and Diagrams.asked == ["r1"]


@pytest.mark.parametrize("row", ["../flow.svg", "..", "flow.svg", "a/b", "a\\b", "C:x", "a b", "", "%2e%2e", "-x",
                                 "x" * 129, "r1\x00", "r1\n"])
def test_a_path_shaped_row_is_refused_before_anything_is_looked_up(estate, row):   # must refuse
    assert refused("diagrams", row, estate["home"]) == 400
    assert Diagrams.asked == []


@pytest.mark.parametrize("place", ["../diagrams", "Diagrams", "", "a/b"])
def test_a_place_name_that_is_not_a_plain_word_is_not_found(estate, place):   # must refuse
    assert refused(place, "r1", estate["home"]) == 404 and Diagrams.asked == []


def test_a_place_not_turned_on_is_not_found(estate):   # must refuse
    registry.write_enabled({}, estate["home"])
    assert refused("diagrams", "r1", estate["home"]) == 404 and Diagrams.asked == []


def test_a_built_in_or_a_place_that_serves_nothing_is_not_found(estate):   # must refuse
    assert refused("map", "r1", estate["home"]) == 404
    assert refused("board", "r1", estate["home"]) == 404


def test_a_row_not_in_the_last_read_is_not_found(estate):   # must refuse
    assert refused("diagrams", "r2", estate["home"]) == 404


def test_a_file_changed_after_the_read_is_refused_by_its_check(estate):   # must refuse
    estate["ok"].write_bytes(SVG.replace(b"<rect", b"<script>alert(1)</script><rect"))
    assert refused("diagrams", "r1", estate["home"]) == 409


def test_a_closed_place_is_refused(estate):   # must refuse
    assert refused("diagrams", "closed", estate["home"]) == 403


def test_a_file_outside_the_named_roots_is_refused(estate):   # must refuse
    assert refused("diagrams", "out", estate["home"]) == 403
    assert refused("diagrams", "relative", estate["home"]) == 404   # not a full path: never joined to anything


def test_a_link_inside_a_root_that_leads_out_is_refused(estate):   # must refuse
    door = estate["base"] / "d" / "door"
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(estate["tmp"]), str(door))
        else:
            door.symlink_to(estate["tmp"], target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot make a link")
    Diagrams.rows["door"] = str(door / "outside.svg")
    assert refused("diagrams", "door", estate["home"]) == 403


def test_a_document_over_the_cap_is_not_served(estate, monkeypatch):   # must refuse
    monkeypatch.setattr(docserve, "MAX_DOC", len(SVG) - 1)
    assert refused("diagrams", "r1", estate["home"]) == 413


# ---- over HTTP: the page's header, the document policy -----------------------------------------------------------
@pytest.fixture
def server(store, estate):
    srv = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_the_route_serves_with_the_document_policy(server):   # must pass
    status, body, headers = get(server, "/api/v2/doc/diagrams/r1", PAGE)
    assert status == 200 and body == SVG and headers["Content-Type"] == "image/svg+xml"
    assert headers["Content-Security-Policy"] == docserve.DOC_CSP == "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    assert headers["X-Content-Type-Options"] == "nosniff"


@pytest.mark.parametrize("path, status", [("/api/v2/doc/diagrams/..%2F..%2Foutside.svg", 400),
                                          ("/api/v2/doc/diagrams/r1/../../x", 400),
                                          ("/api/v2/doc/diagrams/out", 403), ("/api/v2/doc/nowhere/r1", 404),
                                          ("/api/v2/doc/diagrams", 400)])
def test_the_route_refuses_what_the_hook_refuses(server, path, status):   # must refuse
    assert get(server, path, PAGE)[0] == status


def test_the_route_is_read_only_by_the_page(server):   # must refuse
    assert get(server, "/api/v2/doc/diagrams/r1")[0] == 403
    assert get(server, "/api/v2/doc/diagrams/r1", {**PAGE, "Sec-Fetch-Site": "cross-site"})[0] == 403
