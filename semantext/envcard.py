"""envcard: a folder of ratified environments, rendered as the reading card an agent is shown, and as its reference.

An environment is a folder holding SEMANTICS.yaml: who ratified it, its version, its rules and the corrections kept as
its tests. An environment may inherit one parent (`inherits: [name@version]`); the card shows the parent first, then the
child, and warns when the child was ratified against an older parent.

Every rule is shown WHOLE, because a cut rule loses its limit: a rule's limit is often its second sentence. An owner may
ratify a LINE for a rule, a short form checked against the whole statement before it was ratified; the card then shows
the line, and the statement stays whole in the reference. A line is ratified text and is never derived here. When an
environment's rules carry lines, the rules with no line come first and whole, under the environment's own section
titles, then one line per rule, then the environment's own sentence naming where every rule is in full.

Nothing is written here and nothing a card says is run: a card is read as plain data (yaml.safe_load).
"""
from __future__ import annotations

from pathlib import Path

import yaml


def rule_text(text) -> str:
    """The whole text, every run of spaces joined into one, never cut."""
    return " ".join(str(text or "").split())


def chain(path: Path) -> tuple[list[tuple[Path, dict]], list[str]]:
    """[(path, env), ...] from the root parent down to the given environment, and the pin warnings."""
    out, warnings, seen = [], [], set()
    p = Path(path)
    while p and p not in seen:
        seen.add(p)
        env = yaml.safe_load(p.read_text(encoding="utf-8"))
        out.append((p, env))
        pins = env["environment"].get("inherits") or []
        if not pins:
            break
        name, _, version = pins[0].partition("@")
        parent = p.parent.parent / name / "SEMANTICS.yaml"
        if not parent.exists():
            warnings.append(f"parent {name} not found beside {p.parent.name}")
            break
        actual = str(yaml.safe_load(parent.read_text(encoding="utf-8"))["environment"]["version"])
        if version and actual != version:
            warnings.append(f"{env['environment']['id']} pins {name}@{version}, but {name} is at {actual}")
        p = parent
    return list(reversed(out)), warnings


def _entry(entry: dict, text) -> str:
    mark = "" if entry.get("ratified_by") else " (candidate)"
    return f"- {entry['id']}: {rule_text(text)}{mark}"


def card_lines(path: Path) -> tuple[list[str], list[tuple[Path, dict]], list[str]]:
    envs, warnings = chain(path)
    lines = []
    for _, env in envs:
        e = env["environment"]
        who = e.get("ratified_by") or "not ratified"
        lines.append(f"## {e['id']} {e['version']} ({e.get('status', '?')}, ratified by {who})")
        entries = env.get("entries") or []
        if any(x.get("line") for x in entries):
            titles = e.get("card_sections") or {}
            lines += ["", titles.get("whole", "Whole:")]
            lines += [_entry(x, x["statement"]) for x in entries if not x.get("line")]
            lines += ["", titles.get("lines", "One line each:")]
            lines += [_entry(x, x["line"]) for x in entries if x.get("line")]
            if e.get("reference_line"):
                lines += ["", rule_text(e["reference_line"]).replace("{reference}", str(e.get("reference", "")))]
        else:
            lines += [_entry(x, x["statement"]) for x in entries]
        n = len(env.get("tests") or [])
        if n:
            lines.append(f"  ({n} regression cases: the owner's corrections, kept as tests)")
    lines += [f"WARNING: {w}" for w in warnings]
    return lines, envs, warnings


def card(path: Path) -> str:
    """The card for one environment and its parents, as one text."""
    return "\n".join(card_lines(path)[0])


def reference(path: Path) -> str:
    """Every rule of the environment itself (not its parents) in full: its statement, its ratified line, when it
    applies, the owner's words, its cases and what changed, then the corrections kept as tests."""
    _, env = chain(path)[0][-1]
    e = env["environment"]
    out = [f"# {e['id']} {e['version']} reference: every rule in full", "",
           f"*Generated from environments/{e['id']}/SEMANTICS.yaml. Do not edit it by hand: change the environment "
           "and generate it again.*", ""]
    for x in env.get("entries") or []:
        out += [f"## {x['id']}", "", rule_text(x["statement"]), ""]
        pv = x.get("provenance") or {}
        for label, value in (("On the card", x.get("line")), ("Applies when", x.get("applies_when")),
                             ("The owner's words", pv.get("quote") and f'"{rule_text(str(pv["quote"]))}"'),
                             ("Cases", ", ".join(map(str, pv.get("cases") or [])) or None),
                             ("Revised", x.get("revised"))):
            if value:
                out += [f"- **{label}:** {rule_text(str(value))}"]
        out += [""]
    tests = env.get("tests") or []
    if tests:
        out += ["## Regression cases", ""]
        for t in tests:
            exp = t.get("expected")
            exp = exp.get("reading") if isinstance(exp, dict) else exp
            out += [f"- **{t.get('case')}** \"{rule_text(str(t.get('message', '')))}\": expected {rule_text(str(exp))}; "
                    f"forbidden {rule_text(str(t.get('forbidden', '')))}"]
    return "\n".join(out) + "\n"
