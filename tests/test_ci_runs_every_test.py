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


# ---- the tests CI reports and does not require (1.8.1) ----
# A time bound holds on the machine it was measured on. 1.8.0 required every test on every system, and on GitHub's
# runners six test functions missed bounds the project's own machine meets, by a little and not every time: jobs of
# the same system and Python met them on one runner and missed them on another. These six, and no others, carry the
# `timing` mark. CI runs them in a step of their own on every system, where a miss is reported and does not fail the
# run, and requires every other test everywhere. `python -m pytest` runs them with the rest; the whole suite is run on
# the project's own machine before a release.
# The mark is a release from CI's requirement, so the list is pinned here, and so is the workflow's shape: the steps,
# the systems and Pythons, and the ways a run could be made not to count. A test that asserts behaviour beside a time
# bound is NOT a candidate for the mark (most tests with a time bound are of that kind, and CI requires them):
# separate the two first, as test_normal_linear.py does for the one behaviour assertion these six held.
# How far the checks reach: they read the text of the workflow, of pyproject.toml and of the test files. A mark given
# by a decorator (under any name it is imported as), by `pytest.mark.timing` in a module's pytestmark or in a
# parameter's marks is seen. One made when pytest runs is not (a hook or a plug-in that adds it or changes what is
# collected, a name built by getattr, an alias inside pytestmark), and no reader of text could see it.
import hashlib  # noqa: E402

REPORTED = {    # test: what GitHub's runners measured for 1.8.0 (two runs of one commit, 16 November 2026)
    "test_actclass_linear.py::test_end_to_end_64k_is_under_half_a_second":
        "0.60 to 0.74 s against 0.5 s (Linux, macOS, Windows)",
    "test_actclass_linear.py::test_the_guard_catches_the_old_quadratic_patterns":
        "a control that must be slow: 7.4 times slower where it asks for 8 (macOS)",
    "test_actclass_tail.py::test_a1_a2_time_at_64k_is_under_half_a_second":
        "a ratio of 9.2 against 9 (Linux, Windows)",
    "test_actclass_tail.py::test_every_shape_of_64_kib_reads_fast":
        "0.501 to 0.751 s against 0.5 s on four shapes (Linux, macOS, Windows)",
    "test_normal_linear.py::test_the_proxys_reading_of_a_1_mib_message_is_linear_and_under_a_second":
        "1.09 to 1.30 s against 1 s (Linux, Windows)",
    "test_reading_gate.py::test_classifier_is_linear_on_hostile_commands":
        "0.51 to 0.58 s against 0.5 s (macOS, Windows)",
}
NOT_TIMED = 'python -m pytest -q -m "not timing"'
TIMED = "python -m pytest -q -m timing"
# Each job's systems and Pythons, as its strategy block must stand: a cell taken out is a release from CI too.
STRATEGY = {
    "test": (
        "    strategy:\n"
        "      fail-fast: false\n"
        "      matrix:\n"
        "        os: [ubuntu-latest]\n"
        '        python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]\n'
        "        include:\n"
        "          - os: windows-latest\n"
        '            python-version: "3.10"\n'
        "          - os: windows-latest\n"
        '            python-version: "3.14"\n'),
    "test-full": (
        "    strategy:\n"
        "      fail-fast: false\n"
        "      matrix:\n"
        "        os: [windows-latest, macos-latest]\n"
        '        python-version: ["3.10", "3.11", "3.12", "3.13", "3.14"]\n'
        "        exclude:\n"
        "          - os: windows-latest\n"
        '            python-version: "3.10"\n'
        "          - os: windows-latest\n"
        '            python-version: "3.14"\n'),
}
# The one condition a job may carry: the rest of the matrix waits for a tag or a run by hand on a private repository.
JOB_IF = {"test": None,
          "test-full": "${{ !github.event.repository.private || github.event_name == 'workflow_dispatch' || "
                       "startsWith(github.ref, 'refs/tags/') }}"}


# The workflow from its triggers to the end of the two test jobs, word for word, as a hash: any change to that part,
# however small, fails here until this line is changed with it. That is its use: read the laws below, check that the
# change keeps them, then pin the new text. The laws catch what they name; the hash catches what nobody named (a step
# added before the tests, another kind of runner, a narrower trigger).
PINNED = "95a360c4a051899ed60ab70409951c8f92fcc290d518d9979492152a62b23ee7"


def pinned_part(workflow: str) -> str:
    """The part of the workflow that decides what CI requires: from `on:` to the end of the test jobs."""
    return workflow[workflow.index("\non:\n") + 1:workflow.index("\n  package:\n") + 1]


def pytest_runs(job: str) -> list:
    """Each `python -m pytest ...` command of a job's text, with the `if:` of its step ('' when the step has none) and
    whether a failure of the step would not fail the job (any `continue-on-error` but a plain false)."""
    out = []
    for step in re.split(r"(?m)^      - ", job)[1:]:
        run = re.search(r"(?m)^\s*run: (python -m pytest[^\n]*)$", step)
        if run:
            cond = re.search(r"(?m)^\s*if: ([^\n]*)$", step)
            soft = bool(re.search(r"(?m)^\s*continue-on-error:(?!\s*false\s*$)", step))
            out.append((run.group(1).strip(), cond.group(1).strip() if cond else "", soft))
    return out


def reported_tests_in_ci(workflow: str, pyproject: str = "") -> list:
    """What is wrong with how the workflow runs the tests; [] when nothing is. The law, for every job that runs pytest:
    one run of every test but the reported ones, with no condition and required (so every system runs them and a
    failure fails the run); one run of the reported tests whose failure does not fail the run and which still runs
    when the step before it failed; nothing else that runs pytest; the job itself required, on the systems and Pythons
    pinned above, under no condition but the pinned one. And nothing named here that changes what pytest selects from
    outside the command: no PYTEST_ variable in the workflow, no addopts and no second pytest table in pyproject."""
    wrong = []
    jobs = pytest_jobs(workflow)
    if sorted(jobs) != sorted(STRATEGY):
        wrong.append(f"the jobs that run pytest are {sorted(jobs)}, not {sorted(STRATEGY)}")
    for name, text in sorted(jobs.items()):
        head = text.split("\n    steps:\n", 1)[0] + "\n"
        if re.search(r"(?m)^\s*continue-on-error:", head):
            wrong.append(f"{name}: the whole job would not fail the run")
        cond = re.search(r"(?m)^    if: ([^\n]*)$", head)
        if (cond.group(1).strip() if cond else None) != JOB_IF.get(name):
            wrong.append(f"{name}: the job's condition is not the pinned one")
        block = re.search(r"(?ms)^    strategy:\n.*?(?=^    [a-z]|\Z)", head)
        if (block.group(0) if block else None) != STRATEGY.get(name):
            wrong.append(f"{name}: its systems and Pythons are not the pinned ones")
        runs = pytest_runs(text)
        if runs.count((NOT_TIMED, "", False)) != 1:
            wrong.append(f"{name}: not exactly one unconditional, required run of every test but the reported ones")
        if len([r for r in runs if r[0] == TIMED]) != 1:
            wrong.append(f"{name}: the reported tests are run {len([r for r in runs if r[0] == TIMED])} times, not once")
        for cmd, when, soft in runs:
            if cmd == NOT_TIMED:
                if soft or when:
                    wrong.append(f"{name}: the tests that must pass are conditional or would not fail the run")
            elif cmd == TIMED:
                if not soft:
                    wrong.append(f"{name}: a hosted runner's clock would decide the run")
                if "!cancelled()" not in when:
                    wrong.append(f"{name}: the reported tests would not run after a failure of the required ones")
    for line in workflow.splitlines():                  # anywhere in the file, in any job, in any form
        ln = line.strip()
        if "pytest" in ln and not ln.startswith(("#", "name:", "- name:")) and ln not in (f"run: {NOT_TIMED}", f"run: {TIMED}"):
            wrong.append(f"{ln!r} runs pytest in a way that is neither the required run nor the reported one")
    for var in sorted(set(re.findall(r"\bPYTEST_[A-Z_]+", workflow))):
        wrong.append(f"{var} changes what pytest does from outside the command")
    table = pyproject.split("[tool.pytest.ini_options]", 1)[1].split("\n[", 1)[0] if "[tool.pytest.ini_options]" in pyproject else ""
    if re.search(r"(?m)^\s*addopts\s*=", table):
        wrong.append("pyproject's addopts changes what pytest selects from outside the command")
    if re.search(r"(?m)^\[tool\.pytest\]\s*$", pyproject):
        wrong.append("pyproject has a second pytest table, whose settings this test does not read")
    return wrong


def _is_the_mark(d) -> bool:
    """Whether a decorator is the timing mark as the text gives it: an attribute named timing at the end of any chain
    (pytest.mark.timing, or an alias such as mk.timing), or the bare name, called or not."""
    if isinstance(d, ast.Call):
        d = d.func
    return (isinstance(d, ast.Attribute) and d.attr == "timing") or (isinstance(d, ast.Name) and d.id == "timing")


def marked_tests(sources: dict) -> set:
    """Every test that carries the timing mark as far as the text shows, as 'file::name': a decorated function, method
    or class. A mark given another way that the text shows (a module's pytestmark, a parameter's marks) is returned as
    'file::?'. sources is {file name: its text}."""
    found = set()
    for name, text in sorted(sources.items()):
        plain = 0                                # the decorators that spell it mark.timing, to set against the text
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):        # a file kept broken on purpose (a fixture): its text is still read
            if "mark.timing" in text:
                found.add(f"{name}::?")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if any(_is_the_mark(d) for d in node.decorator_list):
                    found.add(f"{name}::{node.name}")
                plain += sum("mark.timing" in ast.unparse(d) for d in node.decorator_list)
        if text.count("mark.timing") != plain:   # the words stand somewhere that is not a decorator
            found.add(f"{name}::?")
    return found


def floor_tests(page: str) -> set:
    """The tests docs/security-floor.md names, as 'file::name'."""
    return {f"{f}::{t}" for f, t in re.findall(r"`tests/(test_[a-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)", page)}


def _every_python_file() -> dict:
    """Every Python file a mark could be given in: the tests folder with its subfolders (conftest.py among them) and a
    conftest.py at the root. This file is left out, because its own text plants marks below; its own tests are checked
    apart, by their decorators."""
    files = {p.relative_to(ROOT / "tests").as_posix(): p for p in sorted((ROOT / "tests").rglob("*.py")) if p.name != Path(__file__).name}
    if (ROOT / "conftest.py").is_file():
        files["../conftest.py"] = ROOT / "conftest.py"
    return {name: p.read_text(encoding="utf-8-sig", errors="replace") for name, p in files.items()}


def test_ci_requires_every_test_but_the_listed_ones_and_reports_those():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert reported_tests_in_ci(workflow, pyproject) == []
    assert hashlib.sha256(pinned_part(workflow).encode("utf-8")).hexdigest() == PINNED, \
        "the workflow's triggers or test jobs changed: check the change against the laws in this file, then pin the new text"
    assert not [f for f in ("pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg") if (ROOT / f).exists()], \
        "a second place for pytest's settings, which this test does not read"
    assert re.search(r'(?m)^markers = \["timing: ', pyproject)
    # must refuse: 1.8.0's shape, every test in one required step, which a slower runner's clock decided
    old = "\njobs:\n  test:\n    steps:\n      - name: Run the tests\n        run: python -m pytest -q\n"
    assert reported_tests_in_ci(old) != []

    def broken(change, words, pyproject=pyproject):
        return any(words in w for w in reported_tests_in_ci(change, pyproject))

    # must refuse: the reported step required, or not run after a failure, or gone; the required step reported only
    assert broken(workflow.replace("        continue-on-error: true\n", ""), "clock would decide")
    assert broken(workflow.replace("        if: ${{ !cancelled() }}\n", ""), "would not run after a failure")
    assert broken(workflow.replace(f"        run: {TIMED}\n", f"        run: {NOT_TIMED}\n"), "run 0 times")
    for soft in ("true", "${{ true }}", "${{ matrix.os == 'windows-latest' }}"):
        assert broken(workflow.replace(f"        run: {NOT_TIMED}\n", f"        continue-on-error: {soft}\n        run: {NOT_TIMED}\n"),
                      "would not fail the run")
    # must refuse: the whole job made not to count, a system taken out, a condition put on a job
    assert broken(workflow.replace("    timeout-minutes: 60\n", "    timeout-minutes: 60\n    continue-on-error: true\n"),
                  "whole job would not fail")
    assert broken(workflow.replace("        os: [windows-latest, macos-latest]\n", "        os: [macos-latest]\n"), "not the pinned ones")
    assert broken(workflow.replace('          - os: windows-latest\n            python-version: "3.14"\n', "", 1), "not the pinned ones")
    assert broken(workflow.replace("    runs-on: ${{ matrix.os }}\n", "    runs-on: ${{ matrix.os }}\n    if: ${{ false }}\n", 1),
                  "condition is not the pinned one")
    # must refuse: pytest run another way, and a selection changed from outside the command
    assert broken(workflow.replace(f"        run: {TIMED}\n", f"        run: {TIMED}\n      - run: pytest -q -k fast\n", 1), "neither the required run")
    assert broken(workflow.replace("    timeout-minutes: 60\n", "    timeout-minutes: 60\n    env:\n      PYTEST_ADDOPTS: -m nothing\n", 1),
                  "PYTEST_ADDOPTS")
    assert broken(workflow.replace("    timeout-minutes: 60\n", "    timeout-minutes: 60\n    env:\n      PYTEST_PLUGINS: other\n", 1),
                  "PYTEST_PLUGINS")
    assert broken(workflow, "addopts", pyproject.replace('testpaths = ["tests"]\n', 'testpaths = ["tests"]\naddopts = "-m nothing"\n'))
    assert broken(workflow, "second pytest table", pyproject + '\n[tool.pytest]\naddopts = ["-m", "nothing"]\n')
    # must refuse, by the hash, what no law names: a narrower trigger, a step put before the tests, another runner
    for change in (workflow.replace("  pull_request:\n", "", 1),
                   workflow.replace("      - uses: actions/setup-python@v6\n",
                                    "      - run: git rm -q tests/test_x.py\n      - uses: actions/setup-python@v6\n", 1),
                   workflow.replace("    runs-on: ${{ matrix.os }}\n", "    runs-on: self-hosted\n", 1)):
        assert change != workflow and hashlib.sha256(pinned_part(change).encode("utf-8")).hexdigest() != PINNED
    # each planted change above did change the text it was planted in
    assert "        continue-on-error: true\n" in workflow and "        if: ${{ !cancelled() }}\n" in workflow
    assert workflow.count("    timeout-minutes: 60\n") == 2 and "        os: [windows-latest, macos-latest]\n" in workflow
    assert workflow.count("    runs-on: ${{ matrix.os }}\n") == 2 and 'testpaths = ["tests"]\n' in pyproject


def test_only_the_listed_tests_are_reported_and_none_of_them_is_a_floor_test():
    sources = _every_python_file()
    marked = marked_tests(sources)
    assert marked == set(REPORTED), (sorted(marked - set(REPORTED)), sorted(set(REPORTED) - marked))
    own = ast.parse(Path(__file__).read_text(encoding="utf-8-sig"))
    assert not [n.name for n in ast.walk(own) if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                and any(_is_the_mark(d) for d in n.decorator_list)]
    floor = floor_tests((ROOT / "docs" / "security-floor.md").read_text(encoding="utf-8"))
    assert len(floor) > 100                                              # the scan reads the page
    assert marked & floor == set(), sorted(marked & floor)
    # must refuse: a mark on a test that is not listed, in each way the text can give it
    assert marked_tests({"test_x.py": "import pytest\n\n\n@pytest.mark.timing\ndef test_new():\n    pass\n"}) == {"test_x.py::test_new"}
    assert marked_tests({"test_y.py": "import pytest\npytestmark = pytest.mark.timing\n\n\ndef test_new():\n    pass\n"}) == {"test_y.py::?"}
    assert marked_tests({"test_z.py": "import pytest\nP = [pytest.param(1, marks=pytest.mark.timing)]\n"}) == {"test_z.py::?"}
    assert marked_tests({"conftest.py": "import pytest\n\n\nclass TestA:\n    @pytest.mark.timing\n    def test_m(self):\n        pass\n"}) \
        == {"conftest.py::test_m"}
    assert marked_tests({"test_a.py": "from pytest import mark as mk\n\n\n@mk.timing\ndef test_new():\n    pass\n"}) == {"test_a.py::test_new"}
    assert marked_tests({"test_b.py": "import pytest\n\n\n@pytest.mark.timing()\ndef test_new():\n    pass\n"}) == {"test_b.py::test_new"}
    assert marked_tests({"test_c.py": "def test_new(:\n    pytest.mark.timing\n"}) == {"test_c.py::?"}     # not Python: its text is still read
    # must refuse: a mark on a test the floor names (planted on the real file)
    name = sorted(floor)[0]
    file, test = name.split("::")
    planted = sources[file].replace(f"def {test}(", f"@pytest.mark.timing\ndef {test}(", 1)
    assert planted != sources[file] and name in marked_tests({file: planted}) & floor
