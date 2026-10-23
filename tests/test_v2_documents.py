"""Documents read in the page: the Documents place, and one listed file of one listed cv/<project> folder, read.

Every check has a must-pass arm and a must-refuse arm: a listed MASTER.md, detailed document and diagram are read, and a
path that steps out, a full path, a drive letter, a link, a folder named like a file, a file or a folder the reader does
not list, and another group's document are refused; the route answers only the page, only GET, and writes nothing.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from semantext.server import make_server
from semantext.sources import gates, places, view
from semantext.sources.gates import World as GitWorld
from test_v2_page import listing
from test_v2_view import World, touch

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><script>alert(1)</script><rect width="10" height="10"/></svg>'


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    notes = w.base / "alder" / "cv" / "notes"
    touch(notes / "MASTER.md", "# Notes for the lab\n\nSee [the part](part.md). <b>not bold</b>\n")
    touch(notes / "flow.svg", SVG)
    touch(notes / ".hidden.md", "# hidden\n")
    touch(w.base / "alder" / "cv" / "outside.md", "# not in a project folder\n")
    touch(w.base / "alder" / "secret.md", "# beside the cv folder\n")
    touch(w.base / "dune" / "cv" / "guest" / "MASTER.md", "# Dune's, outside the group\n")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "git-user"
    user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    w.notes_dir = notes
    return w


def doc_id(slug: str = "notes") -> str:
    found = view.answer("documents")["documents"]
    return next(d["id"] for d in found if d["slug"] == slug)


def refused(doc, file) -> int:
    with pytest.raises(view.DocumentRefused) as e:
        view.document(doc, file)
    return e.value.status


# ---------------------------------------------------------------- the Documents place
def test_the_documents_place_lists_every_folder_with_a_master(world):
    got = view.answer("documents")
    assert got["place"] == "documents" and got["frame"]["waiting"] == 2
    docs = got["documents"]
    assert [d["slug"] for d in docs] == ["notes"]                                  # Dune is outside the group
    d = docs[0]
    assert d["master"] == "MASTER.md" and d["title"] == "Notes for the lab" and d["agent"] == "Alder"
    assert [x["file"] for x in d["docs"]] == ["part.md"] and d["diagrams"] == ["flow.svg"]
    assert d["project_name"] == "Alder home"
    # must-refuse: a folder whose MASTER.md is gone is no document, and the place says so at once
    (world.notes_dir / "MASTER.md").unlink()
    assert view.answer("documents")["documents"] == []


# ---------------------------------------------------------------- one file, read
def test_a_listed_file_is_read_and_nothing_else_is(world):
    d = doc_id()
    master = view.document(d, "MASTER.md")
    assert master["kind"] == "markdown" and master["master"] is True and master["title"] == "Notes for the lab"
    assert "<b>not bold</b>" in master["text"]                                     # the text as written; the page sets it as text
    part = view.document(d, "part.md")
    assert part["master"] is False and part["text"] == "# A part\n" and part["title"] == "A part"
    svg = view.document(d, "flow.svg")
    assert svg["kind"] == "diagram" and svg["bytes"] == SVG.encode("utf-8")
    # must-refuse: every way out of the folder, and every file or folder the reader does not list
    for file in ("../outside.md", "..\\outside.md", "../../secret.md", "..", "../notes/MASTER.md",
                 str(world.base / "alder" / "secret.md"), "/etc/passwd.md", "C:secret.md", "C:/secret.md",
                 "notes/MASTER.md", "notes\\MASTER.md", ".hidden.md", " MASTER.md", "MASTER.md\x00.md"):
        assert refused(d, file) == 400, file
    assert refused(d, "missing.md") == 404
    assert refused(d, "MASTER.txt") == 400                                          # only .md and .svg
    assert refused("0000000000", "MASTER.md") == 404                                # a folder the reader does not list
    assert refused("", "MASTER.md") == 400 and refused(d, "") == 400
    world.write_config(group=None)
    dune = doc_id("guest")
    assert view.document(dune, "MASTER.md")["text"].startswith("# Dune's")
    world.write_config()                                                            # back in the group: Dune's is not read
    assert refused(dune, "MASTER.md") == 404


def test_a_file_checked_again_when_read_is_refused_when_it_is_not_plain(world, monkeypatch):
    """The reader lists only plain files; the read checks again, in case what is there changed after the listing."""
    d = doc_id()
    real = places.load

    def forged(cfg):   # a listing that names what the reader would never list
        out = real(cfg)
        for doc in out["documents"]:
            doc["docs"] = doc["docs"] + [{"file": "folder.md", "title": "x"}, {"file": "link.md", "title": "x"}]
        return out

    (world.notes_dir / "folder.md").mkdir()
    linked = False
    try:
        os.symlink(world.base / "alder" / "secret.md", world.notes_dir / "link.md")
        linked = True
    except (OSError, NotImplementedError):
        pass
    if linked:   # the reader leaves a link out, so the page never lists it
        assert "link.md" not in [x["file"] for x in view.answer("documents")["documents"][0]["docs"]]
        assert refused(d, "link.md") == 404
    monkeypatch.setattr(places, "load", forged)
    assert refused(d, "folder.md") == 403                                           # must refuse: not a plain file
    if linked:
        assert refused(d, "link.md") == 403                                         # must refuse: a link is not followed
    assert view.document(d, "part.md")["text"] == "# A part\n"                     # must pass: the plain file still reads


def test_a_hard_link_and_a_file_swapped_before_the_read_are_refused(world, monkeypatch):
    """Audit of 7bf7aa5, protection items 1 and 2: a second name for a file elsewhere on the volume, and a handle that
    opens a different file from the one first checked (a folder swapped for a link to a decoy)."""
    d = doc_id()
    os.link(world.base / "alder" / "secret.md", world.notes_dir / "hard.md")
    assert refused(doc_id(), "hard.md") in (403, 404)                               # must refuse: never served
    decoy = world.base / "alder" / "secret.md"
    real_open = os.open
    monkeypatch.setattr(view.os, "open", lambda path, flags, *a: real_open(str(decoy), flags, *a))
    assert refused(d, "part.md") == 409                                             # must refuse: not the checked file
    monkeypatch.setattr(view.os, "open", real_open)
    assert view.document(d, "part.md")["text"] == "# A part\n"                     # must pass: the plain file reads
    # audit of 84270dc, item 1: the folder is a link by the time the read is done -> refused before the file's check
    real_read, real_linked = view._read_checked, places._linked

    def read_then_swap(target, st):
        raw = real_read(target, st)
        monkeypatch.setattr(places, "_linked", lambda s: True)
        return raw
    monkeypatch.setattr(view, "_read_checked", read_then_swap)
    assert refused(d, "part.md") == 409                                             # must refuse
    monkeypatch.setattr(places, "_linked", real_linked)
    monkeypatch.setattr(view, "_read_checked", real_read)
    assert view.document(d, "part.md")["text"] == "# A part\n"                     # must pass, unpatched


# ---------------------------------------------------------------- the route
@pytest.fixture
def server(store, world):
    srv = make_server(store, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def call(srv, path, headers=None, method="GET", body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", headers=headers or {},
                                 method=method, data=body)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


PAGE = {"X-Semantext": "1"}


def doc_path(d, file):
    return "/api/v2/document?" + urllib.parse.urlencode({"doc": d, "file": file})


def test_the_document_route_answers_the_page_alone_and_only_reads(server, world, tmp_path):
    d = doc_id()
    own = f"http://127.0.0.1:{server.server_address[1]}"
    before = listing(tmp_path)
    status, body, headers = call(server, doc_path(d, "MASTER.md"), PAGE)
    assert status == 200 and "json" in headers["Content-Type"]
    assert json.loads(body)["text"].startswith("# Notes for the lab")
    status, body, headers = call(server, doc_path(d, "flow.svg"), {**PAGE, "Origin": own})
    assert status == 200 and headers["Content-Type"] == "image/svg+xml" and body == SVG.encode("utf-8")
    assert "default-src 'none'" in headers["Content-Security-Policy"] and headers["X-Content-Type-Options"] == "nosniff"
    assert call(server, "/api/v2/documents", PAGE)[0] == 200
    # must-refuse: without the page's header, from another site, a step out of the folder, an unknown folder
    assert call(server, doc_path(d, "MASTER.md"))[0] == 403
    assert call(server, doc_path(d, "MASTER.md"), {**PAGE, "Origin": "http://evil.example"})[0] == 403
    assert call(server, doc_path(d, "MASTER.md"), {**PAGE, "Sec-Fetch-Site": "cross-site"})[0] == 403
    assert call(server, doc_path(d, "../outside.md"), PAGE)[0] == 400
    assert call(server, doc_path("0000000000", "MASTER.md"), PAGE)[0] == 404
    assert call(server, "/api/v2/document", PAGE)[0] == 400
    # must-refuse: the new routes are GET only, whatever a POST carries
    for path in (doc_path(d, "MASTER.md"), "/api/v2/documents"):
        assert call(server, path, method="POST", body=b"{}")[0] == 403
        assert call(server, path, {**PAGE, "Origin": own, "Content-Type": "application/json"}, "POST", b"{}")[0] == 404
        assert call(server, path, PAGE, "PUT", b"{}")[0] == 501
    assert listing(tmp_path) == before                                              # nothing was written
