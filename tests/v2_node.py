"""Runs a test's JavaScript against the v2 page in node, on the small stand-in for the browser's document in
tests/v2_dom.js. Shared by the page-script tests and the pin, so a change to how the page is laid out on disk is made
here once and never in the tests themselves. Tests only: nothing in semantext/ runs a process."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from semantext import paths

NODE = shutil.which("node")
HARNESS = Path(__file__).with_name("v2_dom.js")
PAGE = paths.static_dir() / "v2" / "index.html"


def run(js: str, plugins: str | Path | None = None):
    """What the test passed to report(), as JSON; the test runs after the page's own modules have started. `plugins`
    is a folder of <name>.js files the page may import as /v2/plugin/<name>.js, as the server would serve them."""
    extra = [str(plugins)] if plugins else []
    r = subprocess.run([NODE, "--experimental-vm-modules", "--no-warnings", str(HARNESS), str(PAGE), *extra],
                       input=js.encode("utf-8"), capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    return json.loads(r.stdout.decode("utf-8"))
