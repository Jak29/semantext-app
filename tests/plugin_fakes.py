"""Installed packages for the Plug-ins tab's tests: a distribution with real files in a folder of the test's, and its
entry points, offered through a stand-in for importlib.metadata.entry_points. Nothing is installed, and a plug-in's
object is made only when its entry point is loaded, which is counted."""
from __future__ import annotations

import json
from pathlib import Path

from semantext import registry


class Dist:
    """A distribution as importlib.metadata gives one: a name, a version, its listed files, and where they lie."""

    def __init__(self, folder: Path, name="semantext-jira", version="0.3", files=()):
        self.name, self.version, self._folder = name, version, Path(folder)
        self.files = list(files)

    def locate_file(self, rel):
        return self._folder / str(rel)


class Point:
    """An entry point: a name, its value ("module:attr"), its distribution, and load(), counted."""

    def __init__(self, name, make, dist, value="semantext_jira.reader:SOURCE"):
        self.name, self.group, self.dist, self.value, self._make, self.loads = name, registry.GROUP, dist, value, make, 0

    def load(self):
        self.loads += 1
        return self._make()


def package(folder: Path, name="semantext-jira", version="0.3", module="semantext_jira", declared=None,
            raw: str | None = None) -> Dist:
    """A package installed in `folder`: its module, and its declaration file when `declared` (a record) or `raw` (the
    file's text) is given."""
    pkg = Path(folder) / module
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "reader.py").write_text("", encoding="utf-8")
    files = [f"{module}/__init__.py", f"{module}/reader.py"]
    if declared is not None or raw is not None:
        (pkg / "semantext-plugin.json").write_text(raw if raw is not None else json.dumps(declared), encoding="utf-8")
        files.append(f"{module}/semantext-plugin.json")
    return Dist(folder, name, version, files)


class Tickets:
    kind, name, title, keys, needs = "source", "tickets", "Tickets", ("tickets", "project", "extra"), ("tickets",)
    calls = 0

    def read(self, config):
        Tickets.calls += 1
        return {"off": not config.get("tickets"), "problems": []}


DECLARED = {"plugins": {"source.tickets": {
    "reads": ["the tickets file you name, and nothing else"],
    "settings": [{"key": "tickets", "type": "path", "title": "Tickets file", "required": True},
                 {"key": "project", "type": "text", "title": "Project", "default": "all"},
                 {"key": "extra", "type": "paths", "title": "More folders"}]}}}
