"""Where Semantext keeps its files.

Your home holds everything that is yours: the rule files (profiles/), every earlier version of them (history/), what
was heard (heard/) and the settings (state.json). It is ~/.semantext unless SEMANTEXT_HOME names another folder.
The package itself only ships the starting rules and the suggestion packs.
"""
from __future__ import annotations

import os
import shutil
from importlib import resources
from pathlib import Path

STARTERS = ("base", "default")


def home() -> Path:
    env = os.environ.get("SEMANTEXT_HOME")
    return Path(env).expanduser() if env else Path.home() / ".semantext"


def package_data() -> Path:
    return Path(str(resources.files("semantext") / "data"))


def suggestions_dir() -> Path:
    return package_data() / "suggestions"


def static_dir() -> Path:
    return Path(str(resources.files("semantext") / "static"))


def ensure_home(root: Path | None = None) -> Path:
    """Create the home on first use by copying in the starting environments. Nothing that exists is overwritten."""
    root = Path(root) if root else home()
    for name in STARTERS:
        target = root / "profiles" / name / "SEMANTICS.yaml"
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(package_data() / "profiles" / name / "SEMANTICS.yaml", target)
    return root
