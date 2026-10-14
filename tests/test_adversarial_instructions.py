"""Adversarial tests for writing Semantext into an agent's instruction file (install agents-md | codex | freebuff
--file PATH), and a static guard that no module can run a command.

The instruction-file arms skip themselves until `semantext install --help` offers agents-md.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from semantext import paths

START, END = b"<!-- semantext:start -->", b"<!-- semantext:end -->"
# By design, a file with no final newline gets a start marker that records the newline install added.
START_ANY = re.compile(rb"<!-- semantext:start(?: \+newline)? -->")


# ---------------------------------------------------------------- a static guard: no Run button anywhere
def test_no_module_can_run_a_command():
    """Requests and answers are words. Nothing in the package may start a process or evaluate text as code."""
    pkg = Path(paths.__file__).resolve().parent
    banned_modules = {"subprocess", "pty", "pexpect"}
    banned_calls = {("os", "system"), ("os", "popen"), ("os", "startfile")}
    found = []
    for f in sorted(pkg.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [f"{f.name}:{node.lineno} import {a.name}" for a in node.names
                          if a.name.split(".")[0] in banned_modules]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in banned_modules:
                found.append(f"{f.name}:{node.lineno} from {node.module} import ...")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in ("eval", "exec"):
                    found.append(f"{f.name}:{node.lineno} {fn.id}(...)")
                elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                    if (fn.value.id, fn.attr) in banned_calls or (fn.value.id == "os" and
                                                                  fn.attr.startswith(("exec", "spawn"))):
                        found.append(f"{f.name}:{node.lineno} {fn.value.id}.{fn.attr}(...)")
    assert not found, found


# ---------------------------------------------------------------- instruction files
def env_for(tmp: Path) -> dict:
    user = tmp / "user"
    user.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    src = str(Path(paths.__file__).resolve().parent.parent)
    env.update(SEMANTEXT_HOME=str(tmp / "semantext"), HOME=str(user), USERPROFILE=str(user),
               PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=src + os.pathsep + os.environ.get("PYTHONPATH", ""))
    return env


def cli(tmp: Path, *args):
    return subprocess.run([sys.executable, "-m", "semantext", *args], capture_output=True, env=env_for(tmp),
                          timeout=60)


def _install_help(tmp: Path) -> str:
    return cli(tmp, "install", "--help").stdout.decode("utf-8", "replace")


@pytest.fixture
def target(tmp_path):
    """The instruction-file target and whether install/uninstall need --apply; skips until the feature exists."""
    h = _install_help(tmp_path)
    if "agents-md" not in h:
        pytest.skip("install agents-md is not in this build yet")
    return {"apply": ["--apply"] if "--apply" in h else []}


def install(tmp, target, p, kind="agents-md"):
    return cli(tmp, "install", kind, "--file", str(p), *target["apply"])


def uninstall(tmp, target, p, kind="agents-md"):
    return cli(tmp, "uninstall", kind, "--file", str(p), *target["apply"])


ORIGINALS = {
    "lf": b"# Project notes\n\nUse tabs.\n",
    "crlf": b"# Project notes\r\n\r\nUse tabs.\r\n",
    "bom": b"\xef\xbb\xbf# Project notes\n\nUse tabs.\n",
    "no-final-newline": b"# Project notes\n\nUse tabs.",
    "empty": b"",
    "unicode": "# Notizen über café ☃\n".encode("utf-8"),
}


@pytest.mark.parametrize("kind", sorted(ORIGINALS))
def test_install_then_uninstall_gives_back_the_same_bytes(tmp_path, target, kind):
    p = tmp_path / "AGENTS.md"
    p.write_bytes(ORIGINALS[kind])
    r = install(tmp_path, target, p)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]
    data = p.read_bytes()
    assert len(START_ANY.findall(data)) == 1 and data.count(END) == 1
    r = uninstall(tmp_path, target, p)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]
    assert p.read_bytes() == ORIGINALS[kind]


def test_installing_twice_adds_no_second_block(tmp_path, target):
    p = tmp_path / "AGENTS.md"
    p.write_bytes(ORIGINALS["lf"])
    install(tmp_path, target, p)
    once = p.read_bytes()
    install(tmp_path, target, p)
    assert p.read_bytes().count(START) == 1
    assert p.read_bytes() == once


def test_a_crlf_file_gets_a_crlf_block(tmp_path, target):
    p = tmp_path / "AGENTS.md"
    p.write_bytes(ORIGINALS["crlf"])
    install(tmp_path, target, p)
    data = p.read_bytes()
    assert data.count(b"\n") == data.count(b"\r\n"), "the block mixes LF into a CRLF file"


def test_the_block_holds_no_local_path(tmp_path, target):
    """Instruction files get committed, often to public repositories."""
    p = tmp_path / "AGENTS.md"
    p.write_bytes(ORIGINALS["lf"])
    install(tmp_path, target, p)
    data = p.read_bytes()
    block = data[data.index(START):data.index(END) + len(END)].decode("utf-8", "replace")
    assert not re.search(r"[A-Za-z]:[\\/]|/(?:home|Users|root)/", block), block
    assert str(tmp_path) not in block and sys.executable not in block


@pytest.mark.parametrize("case", ["two-starts", "start-without-end", "end-without-start", "end-before-start"])
def test_a_malformed_file_is_refused_and_left_untouched(tmp_path, target, case):
    body = {"two-starts": START + b"\nx\n" + START + b"\ny\n" + END + b"\n",
            "start-without-end": b"notes\n" + START + b"\nx\n",
            "end-without-start": b"notes\n" + END + b"\n",
            "end-before-start": END + b"\nx\n" + START + b"\n"}[case]
    p = tmp_path / "AGENTS.md"
    p.write_bytes(body)
    for act in (install, uninstall):
        r = act(tmp_path, target, p)
        assert b"Traceback" not in r.stderr, r.stderr.decode("utf-8", "replace")[-300:]
        assert p.read_bytes() == body
    assert install(tmp_path, target, p).returncode != 0


def test_a_directory_is_refused_with_nothing_written(tmp_path, target):
    d = tmp_path / "somedir"
    d.mkdir()
    r = install(tmp_path, target, d)
    assert r.returncode != 0
    assert b"Traceback" not in r.stderr
    assert list(d.iterdir()) == []


def test_sync_restores_a_tampered_block_and_nothing_else(tmp_path, target):
    p = tmp_path / "AGENTS.md"
    p.write_bytes(ORIGINALS["lf"])
    install(tmp_path, target, p)
    good = p.read_bytes()
    i, j = good.index(START) + len(START), good.index(END)
    p.write_bytes(good[:i] + b"\ntampered\n" + good[j:])
    r = cli(tmp_path, "sync")
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")[-300:]
    assert p.read_bytes() == good
