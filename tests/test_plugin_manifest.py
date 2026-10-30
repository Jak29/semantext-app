"""A plug-in's declaration file (semantext/manifest.py): found among its package's listed files, read as data, and
refused whole when it is not of the shape. Each rule has both arms: what must pass and what must be refused."""
from __future__ import annotations

import json

import pytest

from semantext import manifest
from plugin_fakes import DECLARED, Point, Tickets, package


def _read(tmp_path, **kw):
    dist = package(tmp_path / "site", **kw)
    return manifest.read(Point("source.tickets", Tickets, dist), dist, "source.tickets")


def test_a_declaration_is_read_as_data(tmp_path):   # must pass
    got, why = _read(tmp_path, declared=DECLARED)
    assert why is None and got["reads"] == ["the tickets file you name, and nothing else"]
    assert [(s["key"], s["type"], s["required"], s["widens"]) for s in got["settings"]] == [
        ("tickets", "path", True, False), ("project", "text", False, False), ("extra", "paths", False, False)]


def test_no_file_is_no_declaration_and_no_problem(tmp_path):   # must refuse to make one up
    assert _read(tmp_path) == (None, None)


def test_a_file_the_package_does_not_list_is_not_read(tmp_path):   # must refuse
    dist = package(tmp_path / "site", declared=DECLARED)
    dist.files = [f for f in dist.files if not f.endswith(manifest.FILE)]
    assert manifest.read(Point("source.tickets", Tickets, dist), dist, "source.tickets") == (None, None)


def test_a_module_at_the_top_of_the_install_has_no_folder_to_declare_in(tmp_path):   # must refuse: shared by all
    dist = package(tmp_path / "site", declared=DECLARED)
    dist.files.append("toplevel.py")
    point = Point("source.tickets", Tickets, dist, value="toplevel:SOURCE")
    assert manifest.read(point, dist, "source.tickets") == (None, None)


def test_a_plain_module_declares_beside_itself(tmp_path):   # must pass
    dist = package(tmp_path / "site", declared=DECLARED)
    dist.files = [f for f in dist.files if not f.endswith("__init__.py")]
    got, why = manifest.read(Point("source.tickets", Tickets, dist, value="semantext_jira.reader:SOURCE"), dist,
                             "source.tickets")
    assert why is None and got is not None


def test_another_plug_ins_declaration_is_none_of_this_ones(tmp_path):
    other = {"plugins": {"source.other": DECLARED["plugins"]["source.tickets"]}}
    assert _read(tmp_path, declared=other) == (None, None)


@pytest.mark.parametrize("bad, said", [
    ({"plugins": {"source.tickets": {"settings": [{"key": "closed", "type": "paths"}]}}}, "closures"),
    ({"plugins": {"source.tickets": {"settings": [{"key": "seats", "type": "path"}]}}}, "Semantext's own"),
    ({"plugins": {"source.tickets": {"settings": [{"key": "a", "type": "text"}, {"key": "a", "type": "text"}]}}}, "twice"),
    ({"plugins": {"source.tickets": {"settings": [{"key": "a", "type": "number"}]}}}, "type"),
    ({"plugins": {"source.tickets": {"settings": [{"key": "a", "type": "text", "secret": 1}]}}}, "does not know"),
    ({"plugins": {"source.tickets": {"settings": [{"key": "a", "type": "text", "widens": "yes"}]}}}, "true or false"),
    ({"plugins": {"source.tickets": {"settings": [{"key": "../a", "type": "text"}]}}}, "plain word"),
    ({"plugins": {"source.tickets": {"reads": "everything"}}}, "short texts"),
    ({"plugins": {"source.tickets": {"runs": True}}}, "a record of"),
    ({"plugins": {}, "more": 1}, "one record"),
])
def test_a_declaration_not_of_the_shape_is_refused_whole(tmp_path, bad, said):   # must refuse
    got, why = _read(tmp_path, declared=bad)
    assert got is None and said in why


def test_a_key_given_twice_in_the_file_is_refused(tmp_path):   # must refuse: JSON would keep the last in silence
    raw = '{"plugins": {"source.tickets": {"reads": ["a"]}, "source.tickets": {"reads": ["b"]}}}'
    got, why = _read(tmp_path, raw=raw)
    assert got is None and "twice" in why


def test_a_file_over_the_cap_is_not_read(tmp_path):   # must refuse
    raw = json.dumps({"plugins": {"source.tickets": {"reads": ["x"]}}}) + " " * manifest.MAX_FILE
    got, why = _read(tmp_path, raw=raw)
    assert got is None and "over" in why


def test_reading_a_declaration_loads_nothing(tmp_path):   # must refuse: no code of the plug-in runs
    dist = package(tmp_path / "site", declared=DECLARED)
    point = Point("source.tickets", Tickets, dist)
    manifest.read(point, dist, "source.tickets")
    assert point.loads == 0
