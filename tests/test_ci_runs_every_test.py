"""In CI, no test file may skip itself for want of a package.

Some test files skip themselves when a package they use is not installed (pytest.importorskip): the proxy's tests drive
it with the Anthropic SDK as their client. That is right on a person's machine and wrong in CI, where a skipped file
looks like a passed one. From 1.7.0 until this test, CI installed only the package and pytest, so the proxy's tests (13
files and 455 tests by the 1.8.0 candidate) never ran there, on any system; they ran only on the one machine that had
the SDK. Found on 15 November 2026 by running the suite under a second Python that had no SDK.

The law, in three parts, each of which can fail:
1. every module a test file may skip for is named by the `test` extra in pyproject.toml;
2. every CI job that runs pytest installs that extra;
3. in CI itself (GitHub sets CI=true), each of those modules imports, so nothing is skipped for it.
Limit: a test that skips for another reason (a platform, a missing program) is not seen here; tests/test_security_floor.py
polices those.
"""
from __future__ import annotations

import ast
import importlib
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# A module that is only skipped for below a Python version, because the standard library has it from there on.
ONLY_BELOW = {"tomli": (3, 11)}


def skipped_for(sources: dict) -> dict:
    """The modules that test files may skip for: {module: [file, ...]}, from every pytest.importorskip("module") call.
    sources is {file name: its text}."""
    found: dict = {}
    for name, text in sorted(sources.items()):
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "importorskip" \
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                found.setdefault(node.args[0].value.split(".")[0], []).append(name)
    return found


def extra_names(pyproject: str) -> set:
    """The names the `test` extra installs, lower case, read from pyproject's text (no TOML reader: Python 3.10 has none
    of its own, and this test must not be one more that skips for a package)."""
    section = pyproject.split("[project.optional-dependencies]", 1)[1].split("\n[", 1)[0]
    line = re.search(r"(?m)^test\s*=\s*\[(.*?)\]", section, re.S)
    assert line, "pyproject has no `test` extra"
    return {re.split(r"[<>=!~;\[ ]", req, maxsplit=1)[0].strip().lower() for req in re.findall(r"""["']([^"']+)["']""", line.group(1))}


def not_installed_by(extra: set, wanted: dict) -> dict:
    """The modules a test file may skip for that the extra does not install."""
    return {mod: files for mod, files in wanted.items() if mod.lower() not in extra}


def pytest_jobs(workflow: str) -> dict:
    """Each job of the CI workflow that runs pytest: {job: its text}."""
    jobs = workflow.split("\njobs:\n", 1)[1]
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):\s*$", jobs)
    found = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    return {name: text for name, text in found.items() if "-m pytest" in text}


def _tests() -> dict:
    # utf-8-sig: one test file begins with a byte-order mark, which ast would refuse
    return {p.name: p.read_text(encoding="utf-8-sig") for p in sorted((ROOT / "tests").glob("*.py")) if p.name != Path(__file__).name}


def test_every_module_a_test_may_skip_for_is_in_the_test_extra():
    wanted = skipped_for(_tests())
    assert "anthropic" in wanted and len(wanted["anthropic"]) >= 7      # the scan sees the proxy's tests
    extra = extra_names((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "pytest" in extra                                             # and reads the extra
    assert not_installed_by(extra, wanted) == {}
    # must refuse: a module no extra installs is named, with the files that would skip
    assert not_installed_by({"pytest"}, {"anthropic": ["test_proxy.py"]}) == {"anthropic": ["test_proxy.py"]}
    planted = skipped_for({"test_x.py": 'import pytest\nthing = pytest.importorskip("some_sdk.sub")\n',
                           "test_y.py": '"""pytest.importorskip("in_a_string")"""\n'})
    assert planted == {"some_sdk": ["test_x.py"]}                        # a call is seen; the same words in a string are not


def test_every_ci_job_that_runs_pytest_installs_the_test_extra():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    jobs = pytest_jobs(workflow)
    assert len(jobs) >= 2, sorted(jobs)                                  # the scan sees the test jobs
    without = sorted(name for name, text in jobs.items() if not re.search(r"""pip install\s+["']?\.\[test\]""", text))
    assert without == [], f"these CI jobs run pytest without the test extra, so tests would skip themselves there: {without}"
    # must refuse: a job that installs pytest alone is caught
    old = "\njobs:\n  test:\n    steps:\n      - run: |\n          python -m pip install . pytest\n          python -m pytest -q\n"
    assert [n for n, t in pytest_jobs(old).items() if not re.search(r"""pip install\s+["']?\.\[test\]""", t)] == ["test"]


def test_in_ci_nothing_is_skipped_for_want_of_a_package():
    if not os.environ.get("CI"):
        pytest.skip("not in CI: on a person's machine a test may skip for a package they do not have")
    missing = {}
    for mod, files in skipped_for(_tests()).items():
        if mod in ONLY_BELOW and sys.version_info >= ONLY_BELOW[mod]:
            continue
        try:
            importlib.import_module(mod)
        except ImportError as e:
            missing[mod] = f"{len(files)} test file(s) would skip themselves ({', '.join(files[:4])}...): {e}"
    assert missing == {}, "in CI every test must run; install the `test` extra"
