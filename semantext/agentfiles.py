"""Connecting agents that read an instructions file: Codex (AGENTS.md), freebuff (knowledge.md), or any other.

Semantext keeps one block in the file, between two markers, and never touches anything outside them. The block tells
the agent to run `semantext card` for the live rules, and carries a copy of the card for when it cannot; it names no
local path, because these files are often shared. `semantext sync` refreshes the copy in every file it installed into.

Files are read and written as bytes, so line endings, a byte-order mark and a missing final newline all survive:
install followed by uninstall gives back the file exactly as it was.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from .store import Refused, Store, stamp

START = "<!-- semantext:start"       # the start line is START + " -->", or START + " +newline -->" (see install)
START_PLAIN, START_ADDED_NL = START + " -->", START + " +newline -->"
END = "<!-- semantext:end -->"


def project_root(start: Path | None = None) -> Path:
    """The project a command runs in: the nearest folder holding .git, or else the current folder."""
    here = (start or Path.cwd()).resolve()
    for p in (here, *here.parents):
        if (p / ".git").exists():
            return p
    return here


def default_file(target: str) -> Path:
    """Where each agent reads its instructions: Codex's global file (created if Codex has not made it yet), or
    knowledge.md at the root of the project for freebuff."""
    if target == "codex":
        return Path.home() / ".codex" / "AGENTS.md"
    if target == "freebuff":
        return project_root() / "knowledge.md"
    raise Refused(f"{target} has no default file: name one with --file PATH")


def block(card: str, nl: str = "\n", added_newline: bool = False) -> str:
    lines = [START_ADDED_NL if added_newline else START_PLAIN,
             "## Semantext: how to read this user",
             "",
             "This block is kept by Semantext. Change the rules with the `semantext` command, not here.",
             "",
             "Before you act on a request, run `semantext card` and follow the rules it prints. If you cannot run it,",
             "follow this copy, which may be out of date:",
             "",
             "````text", *card.splitlines(), "````",
             END]
    return nl.join(lines) + nl


def _read(path: Path) -> str:
    if path.is_dir():
        raise Refused(f"{path} is a folder; name a file")
    if not path.exists():
        return ""
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise Refused(f"{path} is not UTF-8 text; it was left untouched")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _split(text: str, path: Path) -> tuple[str, str, str, bool] | None:
    """(before, block, after, added_newline) when the file holds one well-formed block; None when it holds none.
    Broken markers are refused, so nothing is ever cut from the wrong place."""
    starts, ends = text.count(START), text.count(END)
    if starts == 0 and ends == 0:
        return None
    if starts != 1 or ends != 1 or text.index(END) < text.index(START):
        raise Refused(f"{path} holds Semantext markers that do not form one block; fix them by hand. "
                      f"The file was left untouched")
    i, j = text.index(START), text.index(END) + len(END)
    for nl in ("\r\n", "\n"):
        if text.startswith(nl, j):
            j += len(nl)
            break
    added = text.startswith(START_ADDED_NL, i)
    return text[:i], text[i:j], text[j:], added


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.semantext-backup-{stamp()}")
    shutil.copyfile(path, backup)
    return backup


def install(path: Path, card: str) -> tuple[bool, Path | None]:
    """Write or refresh the block. Returns (changed, backup).

    A new block goes at the end, after a blank line. If the file's last line had no newline, install adds one and
    says so in the start marker, so uninstall can take exactly that newline away again."""
    text = _read(path)
    nl = _newline(text)
    parts = _split(text, path)
    if parts:
        before, old, after, added = parts
        new = block(card, nl, added)
        if old == new:
            return False, None
        out = before + new + after
    elif not text:
        out = block(card, nl)
    else:
        added = not text.endswith(("\n", "\r"))
        out = text + (nl if added else "") + nl + block(card, nl, added)
    backup = _backup(path)
    _write(path, out)
    return True, backup


def uninstall(path: Path) -> tuple[bool, Path | None]:
    """Remove the block and the separator install added, and nothing else. Returns (changed, backup)."""
    text = _read(path)
    parts = _split(text, path)
    if not parts:
        return False, None
    before, _, after, added = parts
    nl = _newline(text)
    if before:
        if before.endswith(nl):
            before = before[: -len(nl)]          # the blank line install put before the block
        if added and before.endswith(nl):
            before = before[: -len(nl)]          # the newline install added to the last line
    backup = _backup(path)
    _write(path, before + after)
    return True, backup


def has_block(path: Path) -> bool:
    try:
        return _split(_read(path), path) is not None
    except Refused:
        return False


def remember(store: Store, path: Path) -> None:
    s = store.state()
    s["agent_files"] = [f for f in s.get("agent_files", []) if f != str(path)] + [str(path)]
    store.put_state(s)


def forget(store: Store, path: Path) -> None:
    s = store.state()
    s["agent_files"] = [f for f in s.get("agent_files", []) if f != str(path)]
    store.put_state(s)


def sync(store: Store) -> list[tuple[str, str]]:
    """Refresh the copy of the card in every file installed into. Returns (path, what happened) for each; a file that
    cannot be refreshed safely (broken markers, a folder, not UTF-8) is left untouched and reported as a PROBLEM."""
    card = store.card(store.state()["active"])
    out = []
    for f in store.state().get("agent_files", []):
        p = Path(f)
        try:
            if _split(_read(p), p) is None:
                out.append((f, "no block there any more (left alone)"))
                continue
            changed, _ = install(p, card)
            out.append((f, "refreshed" if changed else "already current"))
        except Refused as e:
            out.append((f, f"PROBLEM: {e}"))
    return out


def modelfile(card: str, base: str) -> str:
    """An Ollama Modelfile that gives a local model the card as its system prompt."""
    if not base or any(c in base for c in "\n\r\"'`") or len(base) > 120:
        raise Refused("name the base model, for example: --base llama3.2")
    return f'FROM {base}\nSYSTEM """\n{card.replace(chr(34) * 3, chr(34) * 2)}\n"""\n'
