"""Connecting Semantext to Claude Code: one UserPromptSubmit hook entry in its settings file.

`semantext install claude-code` only prints what it would add. With --apply it merges the entry into the settings
file, after saving a backup beside it; an entry that is already there is never added twice, and a settings file that
is not valid JSON is never overwritten.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from .store import Refused, stamp

EVENT = "UserPromptSubmit"
# Our hook however it is spelled: `semantext hook`, `semantext.exe hook`, a quoted path to either, `python -m semantext
# hook`, each with or without `--home DIR`.
OURS = re.compile(r'semantext(?:\.exe)?["\']?(?:\s+--home\s+(?:"[^"]*"|\'[^\']*\'|\S+))?\s+hook\b', re.I)


def default_settings() -> Path:
    return Path.home() / ".claude" / "settings.json"


def hook_command(home: Path | str | None = None) -> str:
    """`semantext hook` when the command is on PATH; otherwise this Python running the module, which always works. A
    home other than the default is named in the command, so the hook reads the rules it was installed from."""
    where = ""
    if home is not None and Path(home).expanduser().resolve() != (Path.home() / ".semantext").resolve():
        where = f' --home "{Path(home).expanduser().resolve()}"'
    if shutil.which("semantext"):
        return f"semantext{where} hook"
    return f'"{sys.executable}" -m semantext{where} hook'


def entry(command: str) -> dict:
    return {"hooks": [{"type": "command", "command": command}]}


def snippet(command: str) -> dict:
    return {"hooks": {EVENT: [entry(command)]}}


def _ours(cmd: str) -> bool:
    return isinstance(cmd, str) and bool(OURS.search(cmd))


def _groups(settings: dict, path: Path | str = "the settings file") -> list:
    """The UserPromptSubmit groups, after checking every level has the shape Claude Code uses. An odd shape is
    refused, so a file Semantext does not understand is never rewritten."""
    hooks = settings.get("hooks")
    if hooks is None:
        return []
    if not isinstance(hooks, dict):
        raise Refused(f"{path}: 'hooks' is not an object; it was left untouched")
    groups = hooks.get(EVENT)
    if groups is None:
        return []
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        raise Refused(f"{path}: '{EVENT}' is not a list of hook groups; it was left untouched")
    for g in groups:
        inner = g.get("hooks", [])
        if not isinstance(inner, list) or not all(isinstance(h, dict) for h in inner):
            raise Refused(f"{path}: a '{EVENT}' group's 'hooks' is not a list of hooks; it was left untouched")
    return groups


def is_installed(settings: dict) -> bool:
    try:
        groups = _groups(settings)
    except Refused:
        return False
    return any(_ours(h.get("command", "")) for g in groups for h in g.get("hooks", []))


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:   # utf-8-sig: Windows PowerShell 5.1 saves files with a byte-order mark
        data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    except UnicodeDecodeError:
        raise Refused(f"{path} is not saved as UTF-8 text; it was left untouched")
    except json.JSONDecodeError as e:
        raise Refused(f"{path} is not valid JSON ({e.msg}, line {e.lineno}); it was left untouched")
    if not isinstance(data, dict):
        raise Refused(f"{path} does not hold a JSON object; it was left untouched")
    return data


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    mark = stamp()   # to the microsecond: two in one second never collide
    backup = path.with_name(f"{path.name}.semantext-backup-{mark}")
    shutil.copyfile(path, backup)
    return backup


def install(path: Path, command: str) -> tuple[bool, Path | None]:
    """Add the hook entry. Returns (changed, backup)."""
    data = _load(path)
    _groups(data, path)            # refuses an odd shape before anything is written
    if is_installed(data):
        return False, None
    backup = _backup(path)
    data.setdefault("hooks", {}).setdefault(EVENT, []).append(entry(command))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True, backup


def uninstall(path: Path) -> tuple[bool, Path | None]:
    """Remove every Semantext hook entry, and nothing else. Returns (changed, backup)."""
    data = _load(path)
    current = _groups(data, path)  # refuses an odd shape before anything is written
    if not is_installed(data):
        return False, None
    backup = _backup(path)
    groups = []
    for group in current:
        hooks = group.get("hooks", [])
        kept = [h for h in hooks if not _ours(h.get("command", ""))]
        if kept or not hooks:
            groups.append(dict(group, hooks=kept) if hooks else group)
    if groups:
        data["hooks"][EVENT] = groups
    else:
        data["hooks"].pop(EVENT)
        if not data["hooks"]:
            data.pop("hooks")  # nothing else was there: leave no empty object behind
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True, backup
