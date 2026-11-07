"""The block format and its validator: the first thing the proxy builds on (ARCHITECTURE.md v1.3, section 10, B1).

A block is a small YAML file in a space's folder, one block a file, named `<id>.yaml`. Beside the blocks a space keeps
one `space.yaml` with the space's own settings. Every block has `id`, `kind` and `tests`; the rest of its fields come
from its kind (KINDS below).

Loading fails closed: one fault anywhere and the folder loads NOTHING, with every fault named. A fault is

  - a file in the folder that is not `<id>.yaml` or `space.yaml` (a block is never read from another name);
  - text the strict reader below refuses: an anchor or an alias, an explicit tag, a key given twice, a key that is not
    text, `null`, a float, a date, YAML 1.1's yes/no/on/off, a file over MAX_FILE bytes;
  - an unknown kind, an unknown field, a missing required field, a value of the wrong type or outside its enum;
  - `locked` or `owner` written in a block: locks and ownership are never read from a block's own text (A1); they come
    from where the block sits;
  - two blocks with one id, or a file name that is not its block's id;
  - a block that names an id no block in the set has (a dangling referent, Koinos G14).

The block-set digest is SHA-256 over every file's name and bytes in name order: the kernel keeps the digest of the set
it last wrote and refuses to decide when the folder no longer matches (A1). Nothing here writes a block.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

MAX_FILE = 256 * 1024            # bytes in one block file; a larger one is a fault, never parsed
MAX_FILES = 2000                 # files in one space folder
SPACE_FILE = "space.yaml"
ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
INT = re.compile(r"-?(0|[1-9][0-9]*)\Z")
NEVER_IN_A_BLOCK = ("locked", "owner")


class Fault(Exception):
    """The folder is not loaded; `faults` names every reason, each with the file it is in."""

    def __init__(self, faults: list[str]):
        super().__init__("; ".join(faults))
        self.faults = faults


# ---- the strict reader --------------------------------------------------------------------------------------------
class _Strict(yaml.SafeLoader):
    """A YAML reader that resolves only what a block needs: text, whole numbers, and `true` / `false`. Everything YAML
    would otherwise read in silence is refused: anchors and aliases (one alias can make a small file huge), explicit
    tags, a key given twice (YAML keeps the last), null, floats, dates, and YAML 1.1's yes/no/on/off as booleans."""

    def fetch_alias(self):
        raise yaml.YAMLError("an alias (*name) is not allowed in a block")

    def fetch_anchor(self):
        raise yaml.YAMLError("an anchor (&name) is not allowed in a block")

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            if not isinstance(key_node, yaml.ScalarNode) or key_node.tag != "tag:yaml.org,2002:str":
                raise yaml.YAMLError(f"a key that is not text, at line {key_node.start_mark.line + 1}")
            if key_node.value in seen:
                raise yaml.YAMLError(f"the key {key_node.value[:40]!r} is given twice, at line "
                                     f"{key_node.start_mark.line + 1}")
            seen.add(key_node.value)
        return super().construct_mapping(node, deep=deep)


_Strict.yaml_implicit_resolvers = {}     # no implicit types at all; scalars are text until _scalar reads them


def _scalar(loader, node):
    # Only text reaches here: any other tag, explicit or not, has no constructor below and is refused by the None one.
    text = node.value
    if node.style is None:               # a plain scalar: only a whole number or true/false is read as such
        if INT.match(text):
            return int(text)
        if text in ("true", "false"):
            return text == "true"
        if text in ("", "~", "null", "Null", "NULL"):
            raise yaml.YAMLError(f"an empty value or null, at line {node.start_mark.line + 1}")
    return text


def _refuse_tag(loader, suffix, node=None):
    raise yaml.YAMLError("an explicit tag is not allowed in a block")


# Only three constructors exist: text, mapping, list. SafeLoader's own (int, float, bool, null, timestamp, binary, set,
# omap, pairs ...) are dropped, so an explicit `!!int` or `!!binary` reaches the None constructor and is refused.
_Strict.yaml_constructors = {
    "tag:yaml.org,2002:str": _scalar,
    "tag:yaml.org,2002:map": yaml.SafeLoader.construct_yaml_map,
    "tag:yaml.org,2002:seq": yaml.SafeLoader.construct_yaml_seq,
    None: lambda loader, node: _refuse_tag(loader, None, node),
}
_Strict.yaml_multi_constructors = {}


def read(text: str):
    """One block file's text as a value, by the strict reader. Raises yaml.YAMLError with the reason."""
    loader = _Strict(text)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


# ---- the kinds ----------------------------------------------------------------------------------------------------
# A field spec: (type, required, extra). type is "text", "int", "bool", "ids" (a list of ids of the named kind),
# "texts" (a list of text), "enum" (extra holds the values), "map" (extra holds the inner field specs), "tests".
# A field naming other blocks carries the kind it names in extra, so a dangling referent is found.
@dataclass(frozen=True)
class F:
    type: str
    required: bool = False
    extra: object = None


TEST = {"name": F("text", True), "given": F("any", True), "expect": F("enum", True, ("hold", "pass", "refuse"))}

KINDS: dict[str, dict[str, F]] = {
    "rule": {"words": F("text", True), "scope": F("texts"), "mode": F("enum", False, ("stationary", "adaptive"))},
    "gate": {
        "match": F("map", True, {"tools": F("ids", False, "tool"), "acts": F("texts"), "models": F("ids", False, "model"),
                                 "spend_over": F("int"), "classes": F("texts")}),
        "answer": F("texts", True),
        "timeout_s": F("int"),
        "on_timeout": F("enum", False, ("refuse",)),
    },
    "agent": {
        "identity": F("text", True),
        "harness": F("text"),
        "models": F("ids", False, "model"),
        "tools": F("ids", False, "tool"),
        "budgets": F("map", False, {"tokens_per_day": F("int"), "asks_open": F("int")}),
    },
    "model": {
        "provider": F("enum", True, ("anthropic", "openai-chat")),
        "model": F("text", True),
        "endpoint": F("text", True),
        "credential_host": F("text", True),
        "cidr": F("texts"),
        "budget": F("map", False, {"tokens_per_turn": F("int")}),
        "digest": F("text"),
        "delta_keys": F("texts"),
    },
    "tool": {
        "name": F("text", True),
        "runs_as": F("enum", True, ("client", "mcp", "cli", "http")),   # not `kind`: that names the block's kind
        "runs_programs": F("bool"),
        "touches": F("texts"),
    },
    "source": {"reader": F("text", True), "reads": F("texts"), "closures": F("texts")},
    "record": {"keep": F("texts", True), "retention_days": F("int"), "readers": F("texts"), "export": F("text")},
    "flow": {"steps": F("texts", True), "on_failure": F("enum", True, ("stop",))},
}

SPACE: dict[str, F] = {
    "default": F("enum", True, ("hold", "pass")),
    "after_expiry": F("enum", False, ("hold", "keep")),
    "unknown_request_fields": F("enum", False, ("refuse", "pass")),
    "extra_header_names": F("texts"),
    "extra_fields": F("texts"),          # request fields the person added by a console act (dotted paths)
    "text_like_types": F("texts"),
    "vendor_side": F("enum", False, ("refuse", "record")),
}


@dataclass
class Space:
    """A space folder, loaded whole: its settings and its blocks by id, and the digest of the set as read."""
    settings: dict
    blocks: dict[str, dict] = field(default_factory=dict)
    digest: str = ""

    def of(self, kind: str) -> dict[str, dict]:
        return {i: b for i, b in self.blocks.items() if b["kind"] == kind}


def _check(where: str, value, spec: F, path: str, faults: list, refs: list) -> None:
    t = spec.type
    if t == "any":
        return
    if t == "text":
        if not isinstance(value, str) or not value.strip():
            faults.append(f"{where}: {path} must be text")
    elif t == "int":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            faults.append(f"{where}: {path} must be a whole number, 0 or more")
    elif t == "bool":
        if not isinstance(value, bool):
            faults.append(f"{where}: {path} must be true or false")
    elif t == "enum":
        if value not in spec.extra:
            faults.append(f"{where}: {path} must be one of {', '.join(spec.extra)}")
    elif t in ("texts", "ids"):
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            faults.append(f"{where}: {path} must be a list of text")
        elif t == "ids":
            refs.extend((where, path, spec.extra, v) for v in value)
    elif t == "map":
        _fields(where, value, spec.extra, path, faults, refs)
    elif t == "tests":
        if not isinstance(value, list):
            faults.append(f"{where}: {path} must be a list of tests")
            return
        for n, test in enumerate(value):
            _fields(where, test, TEST, f"{path}[{n}]", faults, refs)


def _fields(where: str, value, specs: dict[str, F], path: str, faults: list, refs: list) -> None:
    if not isinstance(value, dict):
        faults.append(f"{where}: {path or 'the file'} must be a mapping")
        return
    for name in value:
        if name not in specs:
            faults.append(f"{where}: unknown field {(path + '.' if path else '') + name[:40]!r}")
    for name, spec in specs.items():
        if name in value:
            _check(where, value[name], spec, (path + "." if path else "") + name, faults, refs)
        elif spec.required:
            faults.append(f"{where}: missing field {(path + '.' if path else '') + name!r}")


def check_block(where: str, block, faults: list, refs: list) -> None:
    """Every fault of one parsed block, appended to `faults`; the ids it names, appended to `refs`."""
    if not isinstance(block, dict):
        faults.append(f"{where}: a block must be a mapping")
        return
    for name in NEVER_IN_A_BLOCK:
        if name in block:
            faults.append(f"{where}: {name!r} is never read from a block's own text; it comes from where the block sits")
    kind = block.get("kind")
    if kind not in KINDS:
        faults.append(f"{where}: unknown kind {str(kind)[:40]!r}" if "kind" in block else f"{where}: missing field 'kind'")
        return
    bid = block.get("id")
    if not isinstance(bid, str) or not ID.match(bid):
        faults.append(f"{where}: id must be 1 to 64 of a-z, 0-9, '.', '_', '-', starting with a letter or digit")
    specs = {"id": F("text", True), "kind": F("text", True), "tests": F("tests", True), **KINDS[kind]}
    _fields(where, {k: v for k, v in block.items() if k not in NEVER_IN_A_BLOCK}, specs, "", faults, refs)


def digest(folder: Path) -> str:
    """SHA-256 over every file's name and bytes, in name order: the block set as it is on disk."""
    h = hashlib.sha256()
    for p in sorted(folder.iterdir(), key=lambda p: p.name):
        data = p.read_bytes() if p.is_file() else b""
        h.update(len(p.name.encode()).to_bytes(4, "big") + p.name.encode())
        h.update(len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def load(folder: str | Path) -> Space:
    """A space folder, loaded whole or not at all (Fault names every reason)."""
    folder = Path(folder)
    faults: list[str] = []
    refs: list = []
    blocks: dict[str, dict] = {}
    settings = None
    entries = sorted(folder.iterdir(), key=lambda p: p.name) if folder.is_dir() else None
    if entries is None:
        raise Fault([f"{folder}: not a folder"])
    if len(entries) > MAX_FILES:
        raise Fault([f"{folder}: more than {MAX_FILES} files"])
    for p in entries:
        where = p.name[:80]
        if not p.is_file() or p.is_symlink():
            faults.append(f"{where}: not a plain file")
            continue
        if not p.name.endswith(".yaml"):
            faults.append(f"{where}: only <id>.yaml and {SPACE_FILE} belong in a space folder")
            continue
        data = p.read_bytes()
        if len(data) > MAX_FILE:
            faults.append(f"{where}: over {MAX_FILE} bytes, not read")
            continue
        try:
            value = read(data.decode("utf-8"))
        except UnicodeDecodeError:
            faults.append(f"{where}: not UTF-8")
            continue
        except yaml.YAMLError as e:
            faults.append(f"{where}: {str(e).splitlines()[0][:200]}")
            continue
        if p.name == SPACE_FILE:
            _fields(where, value, SPACE, "", faults, refs)
            settings = value
            continue
        before = len(faults)
        check_block(where, value, faults, refs)
        if len(faults) > before:
            continue
        bid = value["id"]
        if p.name != f"{bid}.yaml":
            faults.append(f"{where}: the file must be named {bid}.yaml, after its block's id")
        elif bid in blocks:
            faults.append(f"{where}: the id {bid!r} is given twice")
        else:
            blocks[bid] = value
    if settings is None and not any(f.startswith(SPACE_FILE) for f in faults):
        faults.append(f"{SPACE_FILE}: missing; a space states its default (hold or pass)")
    for where, path, kind, ref in refs:
        target = blocks.get(ref)
        if target is None or target["kind"] != kind:
            faults.append(f"{where}: {path} names {ref[:64]!r}, which is no {kind} block in this space")
    if faults:
        raise Fault(faults)
    return Space(settings=settings, blocks=blocks, digest=digest(folder))
