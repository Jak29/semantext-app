"""Connecting Semantext to Claude Code: a UserPromptSubmit hook entry (the card) and a SessionStart one (the start screen).

`semantext install claude-code` only prints what it would add. With --apply it merges the entry into the settings
file, after saving a backup beside it; an entry that is already there is never added twice, and a settings file that
is not valid JSON is never overwritten. Running it again on an older install adds only the entry that is missing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from . import jsonread
from .store import Refused, stamp

EVENT = "UserPromptSubmit"
START_EVENT = "SessionStart"
# Our hook however it is spelled: `semantext hook`, `semantext.exe hook`, a quoted path to either, `python -m semantext
# hook`, each with or without `--home DIR`.
OURS = re.compile(r'(?<![\w.-])semantext(?:\.exe)?["\']?(?:\s+--home\s+(?:"[^"]*"|\'[^\']*\'|\S+))?\s+(?:hook|start\s+--hook)(?=\s|$)', re.I)


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


def start_command(command: str) -> str | None:
    """The start screen's command, from the card's: None for a command given by hand that does not end in `hook`."""
    return command[:-len("hook")] + "start --hook" if command.endswith(" hook") and _ours(command) else None


def entry(command: str) -> dict:
    return {"hooks": [{"type": "command", "command": command}]}


def snippet(command: str) -> dict:
    start = start_command(command)
    return {"hooks": {EVENT: [entry(command)], **({START_EVENT: [entry(start)]} if start else {})}}


def _ours(cmd: str) -> bool:
    return isinstance(cmd, str) and bool(OURS.search(cmd))


def _groups(settings: dict, path: Path | str = "the settings file", event: str = EVENT) -> list:
    """An event's groups, after checking every level has the shape Claude Code uses. An odd shape is
    refused, so a file Semantext does not understand is never rewritten."""
    if "hooks" not in settings:
        return []
    hooks = settings["hooks"]
    if not isinstance(hooks, dict):
        raise Refused(f"{path}: 'hooks' is not an object; it was left untouched")
    if event not in hooks:
        return []
    groups = hooks[event]
    if not isinstance(groups, list) or not all(isinstance(g, dict) for g in groups):
        raise Refused(f"{path}: '{event}' is not a list of hook groups; it was left untouched")
    for g in groups:
        inner = g.get("hooks", [])
        if not isinstance(inner, list) or not all(isinstance(h, dict) for h in inner):
            raise Refused(f"{path}: a '{event}' group's 'hooks' is not a list of hooks; it was left untouched")
    return groups


def is_installed(settings: dict) -> bool:
    try:
        groups = _groups(settings)
    except Refused:
        return False
    return any(_ours(h.get("command", "")) for g in groups for h in g.get("hooks", []))


def _has(settings: dict, event: str) -> bool:
    return any(_ours(h.get("command", "")) for g in _groups(settings, event=event) for h in g.get("hooks", []))


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:   # utf-8-sig: Windows PowerShell 5.1 saves files with a byte-order mark
        data = jsonread.loads(path.read_text(encoding="utf-8-sig") or "{}")
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
    """Add whichever hook entry is missing. Returns (changed, backup)."""
    data = _load(path)
    _groups(data, path)            # refuses an odd shape before anything is written
    _groups(data, path, START_EVENT)
    # a card hook already there says which home this person's hooks read: the start screen must read the same one
    there = next((h["command"] for g in _groups(data, path) for h in g.get("hooks", []) if _ours(h.get("command", ""))), command)
    add = [(e, c) for e, c in ((EVENT, command), (START_EVENT, start_command(there))) if c and not _has(data, e)]
    if not add:
        return False, None
    if path.exists() and not os.access(path, os.W_OK):   # said before the backup, so a refusal leaves nothing behind
        raise Refused(f"{path} cannot be written to; it was left untouched")
    backup = _backup(path)
    for event, line in add:
        data.setdefault("hooks", {}).setdefault(event, []).append(entry(line))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True, backup


def uninstall(path: Path) -> tuple[bool, Path | None]:
    """Remove every Semantext hook entry, and nothing else. Returns (changed, backup)."""
    data = _load(path)
    current = {e: _groups(data, path, e) for e in (EVENT, START_EVENT)}  # refuses an odd shape before anything is written
    present = [e for e in current if _has(data, e)]
    if not present:
        return False, None
    backup = _backup(path)
    for event in present:
        groups = []
        for group in current[event]:
            hooks = group.get("hooks", [])
            kept = [h for h in hooks if not _ours(h.get("command", ""))]
            if kept or not hooks:
                groups.append(dict(group, hooks=kept) if hooks else group)
        if groups:
            data["hooks"][event] = groups
        else:
            data["hooks"].pop(event)
    if not data["hooks"]:
        data.pop("hooks")  # nothing else was there: leave no empty object behind
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True, backup
