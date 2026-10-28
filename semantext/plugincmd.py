"""`semantext plugins`: every plug-in with where it came from and whether it is on; turning one on or off.

Turning a plug-in on is the person's act, like answering (the ecosystem review, section 4: installed is not enabled,
and the list of what is on is a file an agent could edit). So `enable` refuses in an agent's shell and anywhere that
is not an interactive console, and asks the person to type the plug-in's name back.

A KNOWN LIMIT, DECIDED (ECOSYSTEM.md, the conformance kits, "Honest limit of typed at a console"): this rests on the
agent markers and on whether standard input is a console. It bars an agent that follows the rules. It is no bar
against one that does not: a program running as the person can open a console and type, or write plugins.json itself.
SECURITY.md says the same.
"""
from __future__ import annotations

import re
import unicodedata

from . import registry
from .inbox import human_terminal
from .store import Refused, now


# An escape sequence (ESC ] ... BEL, ESC [ ... final byte, or ESC and one more character), then any other control
# character. A
# package's name, version or text printed raw could move the cursor, recolour or rewrite the console (the audit of
# the registry, c696d0b, protection item d); every printed field goes through shown().
CONTROL = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b\[[0-?]*[ -/]*[@-~]|\x1b.?|\x9b[0-?]*[ -/]*[@-~]|[\x00-\x1f\x7f-\x9f]", re.S)
# Characters that change how the rest of a line is shown without being seen: format characters (Cf: the bidirectional
# overrides and isolates such as U+202E, zero-width ones, U+FEFF, the tag characters), the line and paragraph
# separators (Zl, Zp) and lone surrogates (Cs). name<U+202E>gpj.exe reads as nameexe.jpg (the audit of 784faf6,
# protection item 8).
UNSEEN = ("Cf", "Zl", "Zp", "Cs")


def shown(value) -> str:
    """A field as printed: control characters, escape sequences and the characters in UNSEEN taken out."""
    return "".join(ch for ch in CONTROL.sub("", str(value)) if unicodedata.category(ch) not in UNSEEN)


def _rows(home):
    """(the registry with what is on loaded, what is installed, what is on, problems)."""
    from .sources import view   # the built-ins; only this command and the page import them
    reg = registry.load_enabled(view.BUILT_IN, home)
    found, problems = registry.installed()
    on, trouble = registry.enabled(home)
    return reg, found, on, problems + trouble


def _package(origin: str) -> str:
    """An installed distribution's name as printed. One whose name is the words the built-ins are shown with is said
    as the package it is, so it never reads as one of Semantext's own (the Fable review of 70f2d3c, finding 1)."""
    return f"package {origin}" if str(origin).strip().casefold() == registry.BUILT_IN else str(origin)


def _list(home, out) -> int:
    reg, found, on, problems = _rows(home)
    out(f"{'kind':<9} {'name':<22} {'from':<28} state")
    for e in reg.entries():
        if e.builtin:
            out(f"{shown(e.kind):<9} {shown(e.name):<22} {'built-in':<28} on")
    for i in found:
        key = f"{i.kind}.{i.name}"
        origin = shown(f"{_package(i.origin)} {i.version or ''}".strip())
        loaded = reg.get(i.kind, i.name)
        if key not in on:
            state = "installed, not on"
        elif loaded and not loaded.builtin and loaded.origin == i.origin:
            state = "on"
        else:
            state = "on, not loaded (see below)"
        out(f"{shown(i.kind):<9} {shown(i.name):<22} {origin:<28} {state}")
    out(f"Reserved, none open yet: {', '.join(registry.RESERVED)}.")
    for p in problems + [p for p in reg.problems if p not in problems]:
        out(f"  problem: {shown(p['source'])}: {shown(p['text'])}")
    from . import outside   # the calls into plug-ins this process made, loading them above, that still run
    for text in outside.holding_said():
        out(f"  still running: {shown(text)}")
    return 0


def _find(key: str, found, problems=()):
    i = next((x for x in found if f"{x.kind}.{x.name}" == key), None)
    twice = next((p for p in problems if p.get("kind") == "declared twice" and p.get("source") == f"plug-in {key}"), None)
    if twice:
        raise Refused(shown(twice["text"]))
    if i is None:
        raise Refused(f"no installed package offers a plug-in named {key!r}; `semantext plugins` lists them as "
                      f"<kind>.<name>")
    return i


def _enable(key: str, home, out, ask=None) -> int:
    ask = ask or input   # looked up when asked, so a test can stand in for the person typing
    why_not = human_terminal()
    if why_not:   # see the module's note: a bar for an agent that follows the rules, and no more
        raise Refused(f"cannot turn a plug-in on here: {why_not}. Only you turn a plug-in on, at your own console")
    from .sources import closed   # here: only turning one on needs it
    if not closed.closures_known(home):
        raise Refused("cannot turn a plug-in on yet: name your closed places first, under \"closed\" in your sources "
                      "file or in a closures file it names (\"closures_file\"); until then every path is closed to "
                      "a plug-in. An empty list says nothing is closed")
    found, problems = registry.installed()
    i = _find(key, found, problems)
    if i.kind not in registry.KINDS:
        raise Refused(f"{i.kind} plug-ins are not open yet, so {key} cannot be turned on")
    on, trouble = registry.enabled(home)
    if trouble:
        raise Refused(trouble[0]["text"])
    row = on.get(key)
    if row and (row.get("origin"), row.get("version")) == (i.origin, i.version):
        out(shown(f"{key} is already on ({i.origin} {i.version or '(no version)'})."))
        return 0
    out(shown(f"{key}: a {i.kind}, from the installed package {i.origin} {i.version or '(no version)'} "
              f"(not part of Semantext)."))
    out("A plug-in is code you chose to install. Once on, it runs in the page and the command line with their whole "
        "reach (never in the card hook).")
    try:
        typed = ask(f"Type {key} to turn it on: ")
    except EOFError:
        raise Refused("not turned on: nothing was typed") from None
    if typed.strip() != key:
        raise Refused("not turned on: what was typed is not the plug-in's name")
    on[key] = {"origin": i.origin, "version": i.version, "at": now()}
    path = registry.write_enabled(on, home)
    out(f"{key} is on (kept in {path}). `semantext plugins disable {key}` turns it off.")
    return 0


def _disable(key: str, home, out) -> int:
    """Turning a plug-in off takes reach away, so it is not held to the console."""
    on, trouble = registry.enabled(home)
    if trouble:
        raise Refused(trouble[0]["text"])
    if key not in on:
        out(f"{key} is not on.")
        return 0
    del on[key]
    registry.write_enabled(on, home)
    out(f"{key} is off.")
    return 0


def run(home, action: str, name: str | None, out) -> int:
    if action == "list":
        return _list(home, out)
    if action == "check":
        # The kits (ECOSYSTEM.md, the conformance kits) are not built yet. Not checked is never said as passed.
        out("Not checked: the conformance kits are not built yet, so there is nothing to check a plug-in against.")
        return 1
    if not name:
        raise Refused(f"name the plug-in, as `semantext plugins` lists it: semantext plugins {action} <kind>.<name>")
    return _enable(name, home, out) if action == "enable" else _disable(name, home, out)
