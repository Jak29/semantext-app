"""Every package in the source tree ships in the wheel.

pyproject lists its packages by hand, so a new subpackage (the gates split made one) is left out of an installed copy
unless it is added there too. The suite runs from the source tree and would never notice.
"""
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:   # Python 3.10: tomli if installed, else this file is skipped there (3.11+ checks it)
    tomllib = pytest.importorskip("tomli")

ROOT = Path(__file__).resolve().parent.parent


def listed() -> set:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return set(tomllib.load(f)["tool"]["setuptools"]["packages"])


def on_disk() -> set:
    return {".".join(p.parent.relative_to(ROOT).parts) for p in (ROOT / "semantext").rglob("__init__.py")}


def test_every_package_in_the_tree_is_listed_for_the_wheel():
    assert on_disk() - listed() == set()


def test_every_listed_package_exists():
    assert listed() - on_disk() == set()


def test_the_check_sees_a_package_left_out():
    # must-refuse: drop one listed package and the first check must notice it
    assert "semantext.sources.gates" in on_disk()
    assert on_disk() - (listed() - {"semantext.sources.gates"}) == {"semantext.sources.gates"}


# The page's files are data, not packages: a file under semantext/static ships only when a package-data pattern
# matches it, and the pages split into a folder (static/v2/) were left out of the wheel until it was named.
def data_patterns() -> list:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["tool"]["setuptools"]["package-data"]["semantext"]


def unshipped(patterns, folder: str = "static") -> set:
    """Files under semantext/<folder> that no pattern matches, globbed from the package folder as setuptools globs
    them."""
    pkg = ROOT / "semantext"
    shipped = {p for pattern in patterns for p in pkg.glob(pattern) if p.is_file()}
    return {p.relative_to(pkg).as_posix() for p in (pkg / folder).rglob("*") if p.is_file()} - {
        p.relative_to(pkg).as_posix() for p in shipped}


# The run-record schema is read by checkers outside the package (RUN-RECORD-SCHEMA.md: "a checker reads that file,
# never imports the package"), so an installed copy must carry it.
def test_the_run_record_schema_ships_in_the_wheel():
    assert (ROOT / "semantext" / "schemas" / "run-record-1.json").is_file()
    assert unshipped(data_patterns(), "schemas") == set()


def test_the_check_sees_the_schema_left_out():
    # must-refuse: without its pattern the schema is left out
    left = unshipped([p for p in data_patterns() if p != "schemas/*.json"], "schemas")
    assert left == {"schemas/run-record-1.json"}


def test_every_file_of_the_pages_ships_in_the_wheel():
    assert (ROOT / "semantext" / "static" / "v2" / "app.js").is_file()
    assert unshipped(data_patterns()) == set()


def test_the_check_sees_a_page_file_left_out():
    # must-refuse: without the folder's pattern, every file of the split page is left out, and nothing else is
    left = unshipped([p for p in data_patterns() if p != "static/v2/*"])
    assert left == {p.relative_to(ROOT / "semantext").as_posix() for p in (ROOT / "semantext" / "static" / "v2").iterdir()}
    assert "static/v2/index.html" in left and "static/index.html" not in left
