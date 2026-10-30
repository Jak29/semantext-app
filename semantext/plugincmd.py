"""`semantext plugins`: every plug-in with where it came from and whether it is on; turning one on or off; and
`confirm`, which applies a settings change the page proposed (the page never writes a plug-in's settings).
Turning one on or off here is recorded in the change log the page's Plug-ins tab shows (pluginpage.py).

Turning a plug-in on is the person's act, like answering (the ecosystem review, section 4: installed is not enabled,
and the list of what is on is a file an agent could edit). So `enable` refuses in an agent's shell and anywhere that
is not an interactive console, and asks the person to type the plug-in's name back.

A KNOWN LIMIT, DECIDED (docs/plugin-api.md, "Turning one on, at the console"): this rests on the agent markers and
on whether standard input is a console. It bars an agent that follows the rules. It is no bar against one that does
not: a program running as the person can open a console and type, or write plugins.json itself. SECURITY.md says the
same.
"""
from __future__ import annotations

from . import registry
from .inbox import human_terminal
from .store import Refused, now


def shown(value) -> str:
    """Every line this command prints, rendered by the one renderer (pluginpage.ascii_only): printable ASCII alone,
    one to one, nothing deleted. A package's name, version or text printed raw could move the cursor, recolour or
    rewrite the console (the audit of the registry, c696d0b, protection item d), or read as something it is not:
    name<U+202E>gpj.exe as nameexe.jpg (the audit of 784faf6, protection item 8), a Cyrillic a as a Latin one. Each
    such character is printed as its escape, so it is seen, never taken out. A review line pluginpage has already
    rendered (pluginpage.Rendered) is printed as it is, never rendered twice, once its content is checked: the type
    is not trusted alone, so a Rendered holding anything but printable ASCII is rendered all the same."""
    from .pluginpage import Rendered, ascii_only
    if isinstance(value, Rendered) and all(" " <= c <= "~" for c in value):
        return value
    return Rendered(ascii_only(value))


def _rows(home):
    """(the registry with what is on loaded, what is installed, what is on, problems)."""
    from .sources import view   # the built-ins; only this command and the page import them
    reg = registry.load_enabled(view.BUILT_IN, home)
    found, problems = registry.installed()
    on, trouble = registry.enabled(home)
    return reg, found, on, problems + trouble


def _from(origin, version) -> str:
    """Where an installed plug-in comes from, as printed: "package: <name>  version: <version>", each field rendered
    on its own (shown) under its fixed label, never joined first. A rendered field holds no two spaces together (a run
    is escaped), so the two-space break between them is found in one place only, and two different (name, version)
    pairs never print alike; a package named like the built-ins still reads as the package it is (the Fable review of
    70f2d3c, finding 1)."""
    from .pluginpage import Rendered
    said = f"  version: {shown(version)}" if version is not None else "  no version given"
    return Rendered(f"package: {shown(origin)}{said}")


def _list(home, out) -> int:
    reg, found, on, problems = _rows(home)
    out(_row("kind", "name", "from", "state"))
    for e in reg.entries():
        if e.builtin:
            out(_row(e.kind, e.name, "built-in", "on"))
    for i in found:
        key = f"{i.kind}.{i.name}"
        origin = _from(i.origin, i.version)
        loaded = reg.get(i.kind, i.name)
        if key not in on:
            state = "installed, not on"
        elif loaded and not loaded.builtin and loaded.origin == i.origin:
            state = "on"
        else:
            state = "on, not loaded (see below)"
        out(_row(i.kind, i.name, origin, state))
    out(shown(f"Reserved, none open yet: {', '.join(registry.RESERVED)}."))
    for p in problems + [p for p in reg.problems if p not in problems]:
        out(_indented(f"problem: {p['source']}: {p['text']}"))
    from . import outside   # the calls into plug-ins this process made, loading them above, that still run
    for text in outside.holding_said():
        out(_indented(f"still running: {text}"))
    return 0


def _row(*cells) -> str:
    """One row of the list: each cell rendered (shown), then padded, so the padding is never taken for the text."""
    from .pluginpage import Rendered
    a, b, c, d = (shown(x) for x in cells)
    return Rendered(f"{a:<9} {b:<22} {c:<28} {d}")


def _indented(text) -> str:
    """A line indented under another: the text rendered (shown; a Rendered one checked, never twice), then the indent
    put before it."""
    from .pluginpage import Rendered
    return Rendered("  " + shown(text))


def _find(key: str, found, problems=()):
    i = next((x for x in found if f"{x.kind}.{x.name}" == key), None)
    twice = next((p for p in problems if p.get("kind") == "declared twice" and p.get("source") == f"plug-in {key}"), None)
    if twice:
        raise Refused(twice["text"])
    if i is None:
        raise Refused(f"no installed package offers a plug-in named {key!r}; `semantext plugins` lists them as "
                      f"<kind>.<name>")
    return i


def _enable(key: str, home, out, ask=None, reviewed_full: str | None = None) -> int:
    ask = ask or input   # looked up when asked, so a test can stand in for the person typing
    why_not = human_terminal()
    if why_not:   # see the module's note: a bar for an agent that follows the rules, and no more
        raise Refused(f"cannot turn a plug-in on here: {why_not}. Only you turn a plug-in on, at your own console")
    from .sources import closed   # here: only turning one on needs it
    state = closed.closures_state(home)
    if not state["known"]:
        if state["state"] == "none named":
            why = f" ({state['why']})" if state["why"] else ""
            raise Refused(f"cannot turn a plug-in on yet: name your closed places first{why}. To fix it, "
                          f"{state['fix']}. Until then every path is closed to a plug-in")
        raise Refused(f"cannot turn a plug-in on yet: your closed places are named, and "
                      f"{'the list is incomplete' if state['state'] == 'incomplete' else 'they cannot be used'}: "
                      f"{state['why']}. To fix it, {state['fix']}")
    found, problems = registry.installed()
    i = _find(key, found, problems)
    if i.kind not in registry.KINDS:
        raise Refused(f"{i.kind} plug-ins are not open yet, so {key} cannot be turned on")
    on, trouble = registry.enabled(home)
    if trouble:
        raise Refused(trouble[0]["text"])
    row = on.get(key)
    if row and (row.get("origin"), row.get("version")) == (i.origin, i.version):
        out(shown(f"{key} is already on, from:"))
        out(_indented(_from(i.origin, i.version)))
        return 0
    from . import manifest, pluginpage
    cols = pluginpage.width()
    declared, why = manifest.read(i.point, i.dist, key)
    head = pluginpage.narrow_note(cols) + [
        shown(f"{key}: a {i.kind}, from an installed package (not part of Semantext):"),
        _indented(_from(i.origin, i.version)),
        shown("A plug-in is code you chose to install. Once on, it runs in the page and the command line with their "
              "whole reach (never in the card hook).")] + ([shown(f"Its declaration cannot be used: {why}")] if why else [])
    snapshot = pluginpage.enable_snapshot(home, key)   # what the review is shown from; checked again after the yes
    review = pluginpage.enable_review(home, key, declared)   # the console is the point of review: nothing in it is cut
    show = pluginpage.command(home, "plugins", "show", key, "--full")
    if reviewed_full is not None:   # read in full with `show --full`: the code it printed must be this review's now
        pluginpage.check_code(reviewed_full, pluginpage.enable_code(home, key, declared), show)
    else:   # counted as printed: its head included, at the console's own width
        pluginpage.too_long(head + review, "What it would read", show,
                            pluginpage.command(home, "plugins", "enable", key), cols)
    for line in head + review:
        out(shown(line))
    try:
        typed = ask(shown(f"Having seen the above, type {key} to turn it on: "))
    except EOFError:
        raise Refused("not turned on: nothing was typed") from None
    if typed.strip() != key:
        raise Refused("not turned on: what was typed is not the plug-in's name")
    pluginpage.console_on_off(home, key, {"origin": i.origin, "version": i.version, "at": now()}, snapshot=snapshot)
    out(shown(f"{key} is on (kept in {registry.enabled_file(home)}). `semantext plugins disable {key}` turns it off."))
    return 0


def _disable(key: str, home, out) -> int:
    """Turning a plug-in off takes reach away, so it is not held to the console."""
    on, trouble = registry.enabled(home)
    if trouble:
        raise Refused(trouble[0]["text"])
    from . import pluginpage
    if key not in on or pluginpage.console_on_off(home, key, None) is None:
        out(shown(f"{key} is not on."))
        return 0
    out(shown(f"{key} is off."))
    return 0


def _confirm(number: str, home, out, ask=None, reviewed_full: str | None = None) -> int:
    """Apply a settings change the page proposed: held to the console as turning one on is, and made only once the
    person has seen its before and after and typed the plug-in's name back, and only while the proposal is not stale
    (checked again under the lock after the yes)."""
    ask = ask or input
    why_not = human_terminal()
    if why_not:   # the same bar as enable, and the same limit (the module's note)
        raise Refused(f"cannot confirm a change here: {why_not}. Only you apply a plug-in's settings, at your own "
                      f"console")
    from . import pluginpage
    n = pluginpage.number(number)   # ASCII digits alone: int() would also take "\u0661" or " 5 "
    if n is None:
        raise Refused("name the proposal by its number, as the page shows it: semantext plugins confirm <n>")
    r = pluginpage.proposal(home, n)
    key = r["plugin"]
    cols = pluginpage.width()
    review = pluginpage.confirm_lines(home, r)   # all of it covered by the review code (proposal_code)
    show = pluginpage.command(home, "plugins", "show", n, "--full")
    if reviewed_full is not None:   # exactly what it applies, or nothing: read with `show --full`, bound by its code
        pluginpage.check_code(reviewed_full, pluginpage.proposal_code(home, n), show)
    else:
        pluginpage.too_long(pluginpage.narrow_note(cols) + review, f"Proposal {n}", show,
                            pluginpage.command(home, "plugins", "confirm", n), cols)
    for line in pluginpage.narrow_note(cols) + review:
        out(shown(line))
    try:
        typed = ask(shown(f"Having seen the above, type {key} to make this change: "))
    except EOFError:
        raise Refused("not changed: nothing was typed") from None
    if typed.strip() != key:
        raise Refused("not changed: what was typed is not the plug-in's name")
    made = pluginpage.confirm(home, n)
    out(shown(f"Changed (change {made['n']} in the change log; the page can roll it back)."))
    return 0


def _show(name: str | None, home, out, full: bool = False) -> int:
    """`semantext plugins show <n>` (a proposal) or `show <kind>.<name>` (what enabling that plug-in would show): in
    full, exactly, however long, in printable ASCII. Changes nothing. With --full it ends with the review code that
    `confirm <n> --reviewed-full <code>` or `enable <kind>.<name> --reviewed-full <code>` must give back."""
    from . import manifest, pluginpage
    n = pluginpage.number(name)   # ASCII digits alone: "\u00b2" passes isdigit() and fails int()
    if n is not None:
        lines = pluginpage.show_proposal(home, n)
        code = pluginpage.proposal_code(home, n) if full else None
    elif name and "." not in name and any(c.isdigit() for c in name):
        raise Refused("name the proposal by its number in the digits 0 to 9, as the page shows it")
    elif name:
        found, problems = registry.installed()
        i = _find(name, found, problems)
        declared, _ = manifest.read(i.point, i.dist, name)
        lines = pluginpage.enable_review(home, name, declared)
        code = pluginpage.enable_code(home, name, declared) if full else None
    else:
        raise Refused("name a proposal by its number, or a plug-in as <kind>.<name>: semantext plugins show <n>")
    for line in lines:
        out(shown(line))
    if code:
        out(shown(f"Review code: {code} (give it to --reviewed-full; it holds only while all of the above is "
                  f"unchanged)"))
    return 0


def run(home, action: str, name: str | None, out, reviewed_full: str | None = None, full: bool = False) -> int:
    """`semantext plugins <action>`. Every line it prints, and the text of whatever it raises, go through the one
    renderer (shown): a refusal keeps its type with its text rendered; any other exception becomes a refusal holding
    the very text cli.main would have printed for it, rendered, so nothing of a package, a record or a path reaches
    the console raw however it fails."""
    say = (lambda line: out(shown(line)))   # every line, checked once more at the door
    try:
        return _run(home, action, name, say, reviewed_full, full)
    except Refused as e:   # a refusal is printed too: its paths and names rendered as every other line is
        e.args = (shown(str(e)),)
        raise
    except (OSError, ValueError) as e:   # cli.main prints these as their text alone
        raise Refused(shown(str(e))) from e
    except Exception as e:  # noqa: BLE001  cli.main's last resort, its words kept, rendered
        raise Refused(shown(f"an unexpected {type(e).__name__}: {e}. `semantext doctor` checks the files; please "
                            f"report it if it persists")) from e


def _run(home, action: str, name: str | None, out, reviewed_full: str | None, full: bool) -> int:
    if action == "list":
        return _list(home, out)
    if action == "check":
        # The conformance kits (docs/plugin-api.md) are not built yet. Not checked is never said as passed.
        out(shown("Not checked: the conformance kits are not built yet, so there is nothing to check a plug-in "
                  "against."))
        return 1
    if action == "confirm":
        return _confirm(name, home, out, reviewed_full=reviewed_full)
    if action == "show":
        return _show(name, home, out, full=full)
    if not name:
        raise Refused(f"name the plug-in, as `semantext plugins` lists it: semantext plugins {action} <kind>.<name>")
    if action == "enable":
        return _enable(name, home, out, reviewed_full=reviewed_full)
    return _disable(name, home, out)
