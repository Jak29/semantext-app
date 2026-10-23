# Parts of this file are reworked from harness2 and rrsi, both under the Apache License, Version 2.0:
#
#   diff_summary  from harness2/core/tree.py, diff_summary (Copyright 2026 Google LLC)
#   fingerprint   from harness2/core/runmark.py, fingerprint (Copyright 2026 Google LLC)
#   the fields    from rrsi/propose.py, the done() contract and the prune proposal (Copyright 2026 The rrsi Authors;
#                 Copyright 2026 Google LLC)
#   score         from rrsi/loop.py, attribute: predicted measures against the outcome, and the regressions nobody
#                 predicted (Copyright 2026 The rrsi Authors; Copyright 2026 Google LLC)
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
# an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.
#
# CHANGED, 23 October 2026, for Semantext: diff_summary takes two {path: text} trees and a list of always-on paths
# instead of a SurfaceSpec; fingerprint digests the files a card names (not a folder walked), with SHA-256, reads only
# plain files inside the filing agent's own home and its projects, through no link or junction at any level, never a
# name that holds secrets, a hard link or an alternate stream, through one checked handle; the fields are read from a
# request line instead of an agent's done() call; the score is a Brier score over stated probabilities instead of a
# hit rate. Nothing here runs a command, calls git or writes a file: rrsi's gitops (subprocess), its history rewrite
# and its unattended fast-forward are not lifted.
"""The proposed-change card: an agent that wants to change how the estate works shows the change as one card.

A change is a record, not an ask: a line with "kind": "change" in the agent's own changes.jsonl (beside its requests
file; the folder that holds it is the agent, never a field in the line). When a change needs the person's word, the
agent files an ordinary decision card in its requests file naming the change's id ("change": id). A change line:

    id, at, title, why            as every card has them (required)
    component                     what it changes: a rule, a hook, a gate, a setting, a skill... (required)
    hypothesis                    one sentence: the mechanism, and why it should help (required)
    trigger                       the condition that showed the need
    predicted                     the named measures it should move: a list of {"measure", "direction": "up" or
                                  "down", "p": the stated chance, 0 to 1}; a bare text is a measure with no direction
    regression_risk               what could break outside the predicted measures
    why_not_smaller               why a smaller change would not do
    retroactive_check             would it have changed a recorded case, and which
    undo                          {"commit": a commit hash} or {"restore": a file, "from": an optional commit}: shown
                                  as data, never performed
    prune                         true when the change removes machinery that stopped helping
    tree                          {"before": {path: text}, "after": {path: text}, "always_on": [paths]}: what changes
    evidence                      {"files": [up to 50 full paths], "digest": fingerprint(files, roots) when the
                                  evidence was measured}: files inside the agent's own home or its projects only

A later line {"outcome": <the card's id>, "at", "moved": {measure: "up" | "down" | "none"}, "regressions": [texts],
"undone": true or false} records what happened after the change, as a new entry: an outcome is never edited, and an
undo is one more outcome, never an erase.
"""
from __future__ import annotations

import fnmatch
import hashlib
import math
import os
import re
import stat
import time
from pathlib import Path

from .places import _linked   # a symlink or a junction; a cloud placeholder is not a link

REQUIRED = ("id", "at", "title", "why", "component", "hypothesis")
TEXTS = ("component", "hypothesis", "trigger", "regression_risk", "why_not_smaller", "retroactive_check")
DIRECTIONS = ("up", "down")
MOVES = ("up", "down", "none")
COMMIT = re.compile(r"[0-9a-fA-F]{7,64}")
MAX_FILES = 50                  # files one card's evidence may name; more is said, and none is read
FILE_CAP = 16 * 1024 * 1024     # a file larger than this is not digested, and the evidence is unknown
TREE_CAP = 256                  # paths one side of a tree may hold


def _t(v, key) -> str | None:
    x = v.get(key) if isinstance(v, dict) else None
    return (x.strip() or None) if isinstance(x, str) else None


# ---- what changes (harness2 tree.diff_summary, reworked) ----------------------------------------------------------
def diff_summary(before: dict, after: dict, always_on=()) -> dict:
    """Files added, removed and changed between two {path: text} trees, and the change in always-on characters: the
    characters of the always-on files that every session carries, after minus before."""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
    on = [p for p in always_on if isinstance(p, str)]
    size = lambda tree: sum(len(tree.get(p) or "") for p in on)   # noqa: E731
    return {"added": added, "removed": removed, "changed": changed, "always_on_char_delta": size(after) - size(before)}


def _tree(value, notes: list) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        notes.append(("bad field", "its tree is not a record of before and after"))
        return None
    sides = {}
    for side in ("before", "after"):
        got = value.get(side) or {}
        if not isinstance(got, dict) or len(got) > TREE_CAP or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in got.items()):
            notes.append(("bad field", f"its tree's {side} is not a record of up to {TREE_CAP} paths and their text"))
            return None
        sides[side] = got
    on = value.get("always_on") or []
    if not isinstance(on, list) or not all(isinstance(p, str) for p in on):
        notes.append(("bad field", "its tree's always_on is not a list of paths"))
        on = []
    return diff_summary(sides["before"], sides["after"], on)


# ---- is the evidence current (harness2 runmark.fingerprint, reworked) ----------------------------------------------
# A digest says only "same" or "different", but that is enough to confirm a guess about a file's bytes, or that a file
# exists. So the evidence of a change is read only where the filing agent can already read: its own home and the
# projects the places reader binds to it (the caller passes those roots; there is no default). Inside them, nothing is
# followed and nothing that holds secrets is read: every folder below the root is checked to be no link or junction,
# the file's real path must lie inside the root's real path, a name that carries secrets in ANY part of the path is
# refused, as is a hard link, an alternate stream, a device name, and a short (8.3) name. The bytes are read through
# one read-only handle checked against the file as examined, and the folder is checked again after the read.
# The first layer: evidence is a document or source text, by its kind. Anything else is not read.
EVIDENCE_KINDS = (".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".py", ".ts", ".tsx", ".js", ".mjs", ".cs",
                  ".rs", ".lean", ".svg", ".csv", ".sh", ".ps1", ".bat", ".cmd", ".html", ".css", ".xml", ".cfg", ".ini",
                  ".go", ".java", ".c", ".h", ".hpp", ".cpp", ".log")
EVIDENCE_NAMES = ("license", "makefile", "dockerfile", "readme", ".gitignore", ".gitattributes", ".editorconfig")
# The second layer: a part of the path, taken whole (case aside), that holds or guards secrets. The kinds above are the
# places secrets live too (.json, .yaml, .txt), so this layer carries the weight. A trade-off, stated: "token" is
# matched as a whole word (token, tokens, token.*, tokens.*, *_token*, *-token*) so that tokenizer.py stays evidence,
# while vault*, wallet*, .ssh*, *kaggle* and password* refuse a few honest names (vault_notes.md, wallets.md).
SECRET_NAMES = (".env*", ".npmrc", ".netrc", ".pgpass", ".git-credentials", "id_rsa*", "id_dsa*", "id_ecdsa*",
                "id_ed25519*", "*.pem", "*.key", "*.key.*", "*.pfx", "*.p12", "*.kdbx", "credentials*", "cred", "cred.*",
                "wallet*", "vault*", "*kaggle*", ".ssh*",
                "token", "tokens", "token.*", "tokens.*", "*_token*", "*-token*",
                "secret", "secrets", "secret.*", "secrets.*", "*_secret*", "*-secret*", "client_secret*",
                "settings.local.json", "service-account*", "service_account*", "*api_key*", "*api-key*", "*apikey*",
                "password*", "passwd*", "seed", "seed.*", "mnemonic*", "recovery_code*", "auth.json", "env.json",
                "key", "key.*", "keys", "keys.*", "private_key*", "private-key*")
SECRET_FOLDERS = (".ssh", ".kube", ".docker", ".aws", ".gnupg", ".kaggle")
SECRET_IN = {"gh": ("hosts.yml", "hosts.yaml")}   # a name that holds secrets only under a folder of this name
DEVICE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?", re.IGNORECASE)
SHORT = re.compile(r"~[0-9]")
EDGE = 4096                      # bytes at each end of a file that key the cache, beside its size, time and inode
CACHE_S = 60.0                   # how long a cached digest of one file stands
_CACHE: dict = {}                # in memory only, never written: key -> (content digest, when)


def _key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def _below(path: str, root: str) -> list[str] | None:
    """The parts of `path` below `root` (both as compared), or None when it is not below it."""
    p, r = _key(path), _key(root).rstrip("\\/")
    if not p.startswith(r + os.sep):
        return None
    return [x for x in p[len(r) + 1:].split(os.sep) if x]


def _bad_name(part: str) -> str | None:
    """Why one part of a path may not be read, or None."""
    low = part.lower()
    if ":" in part:
        return "it holds a colon (an alternate stream or a drive)"
    if part != part.rstrip(" ."):
        return "it ends with a dot or a space"
    if DEVICE.fullmatch(part):
        return "it is a device name"
    if SHORT.search(part):
        return "it is a short (8.3) name"
    if low in SECRET_FOLDERS or any(fnmatch.fnmatchcase(low, pat) for pat in SECRET_NAMES):
        return "its name is one that holds secrets"
    return None


def _kind(name: str) -> str | None:
    """Why a file of this name is not evidence, or None: evidence is one of EVIDENCE_KINDS by its extension, or one of
    EVIDENCE_NAMES whole."""
    low = name.lower()
    if low in EVIDENCE_NAMES or os.path.splitext(low)[1] in EVIDENCE_KINDS:
        return None
    return "it is not a kind of file read as evidence (" + ", ".join(EVIDENCE_KINDS + EVIDENCE_NAMES) + ")"


def _secret_in(parts: list[str]) -> str | None:
    """A part that holds secrets only under a certain folder (gh/hosts.yml), or None."""
    for folder, part in zip(parts, parts[1:]):
        if part.lower() in SECRET_IN.get(folder.lower(), ()):
            return part
    return None


class _Unread(Exception):
    pass


OVER_BUDGET = "not checked: over the read budget"


def _content(path: str, root: str, now: float, budget: dict | None = None) -> str:
    """The SHA-256 of one file's bytes, read as the top of this section says, or _Unread with the reason."""
    if path.startswith(("\\\\", "//")) or not os.path.isabs(path) or ".." in re.split(r"[\\/]", path):
        raise _Unread(f"{path} is not a plain full path")
    parts = _below(path, root)
    if not parts:
        raise _Unread(f"{path} is outside the filing agent's home and its projects, so it is not read")
    for part in parts:
        why = _bad_name(part)
        if why:
            raise _Unread(f"{path} is not read: {part!r} {why}")
    why = _kind(parts[-1])
    if why:
        raise _Unread(f"{path} is not read: {why}")
    here = root
    for i, part in enumerate(parts):       # every folder below the root, and then the file: no link, no junction
        here = os.path.join(here, part)
        try:
            st = os.lstat(here)
        except FileNotFoundError:
            raise _Unread(f"{path} is not there, so whether it matches is unknown") from None
        except (OSError, ValueError) as e:
            raise _Unread(f"{path} cannot be examined ({getattr(e, 'strerror', None) or e})") from None
        if _linked(st):
            raise _Unread(f"{path} passes through a link or junction ({part}), so it is not followed")
        if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            raise _Unread(f"{path}: {part} is not a folder")
    if not stat.S_ISREG(st.st_mode):
        raise _Unread(f"{path} is not a plain file")
    if st.st_nlink > 1:
        raise _Unread(f"{path} is a hard link (it has {st.st_nlink} names), so it is not read")
    if st.st_size > FILE_CAP:
        raise _Unread(f"{path} is over {FILE_CAP // (1024 * 1024)} MB, so it is not digested")
    real, real_root = os.path.realpath(path), os.path.realpath(root)
    real_parts = _below(real, real_root)
    if not real_parts:
        raise _Unread(f"{path} resolves outside its root, so it is not read")
    for part in real_parts:                # the long names, as the file system resolves them
        why = _bad_name(part)
        if why:
            raise _Unread(f"{path} is not read: {part!r} {why}")
    why = _kind(real_parts[-1])
    if why:
        raise _Unread(f"{path} is not read: {why}")
    held = _secret_in(list(Path(real).parts))
    if held:
        raise _Unread(f"{path} is not read: {held!r} its name is one that holds secrets in that folder")
    parent = os.path.dirname(path)
    before = os.lstat(parent)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        if not _same(os.fstat(fd), st):
            raise _Unread(f"{path} changed before it was read")
        head = os.read(fd, EDGE)
        os.lseek(fd, max(0, st.st_size - EDGE), os.SEEK_SET)
        tail = os.read(fd, EDGE)
        key = (_key(real), st.st_size, st.st_mtime_ns, st.st_ino, hashlib.sha256(head + b"\0" + tail).hexdigest())
        hit = _CACHE.get(key)
        if hit and now - hit[1] < CACHE_S:
            digest = hit[0]
        else:
            if budget is not None:   # bytes one page build may still read across all evidence; a cached file costs none
                if st.st_size > budget["left"]:
                    raise _Unread(OVER_BUDGET)
                budget["left"] -= st.st_size
            os.lseek(fd, 0, os.SEEK_SET)
            h, left = hashlib.sha256(), FILE_CAP + 1
            while left > 0:
                chunk = os.read(fd, min(left, 1 << 20))
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
            if left <= 0:
                raise _Unread(f"{path} is over {FILE_CAP // (1024 * 1024)} MB, so it is not digested")
            digest = h.hexdigest()
            for k in [k for k, (_, at) in _CACHE.items() if now - at >= CACHE_S]:
                del _CACHE[k]
            _CACHE[key] = (digest, now)
    finally:
        os.close(fd)
    after, again = os.lstat(parent), os.lstat(path)
    if _linked(after) or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or not _same(again, st):
        raise _Unread(f"{path} or its folder changed while it was read")
    return digest


def _same(a, b) -> bool:
    return (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_dev, b.st_ino, b.st_size, b.st_mtime_ns)


def fingerprint(files, roots, budget: dict | None = None) -> dict:
    """A digest of the files a card names, as they are now: SHA-256 over each path as written (sorted), a NUL, the
    SHA-256 of its bytes, and a NUL. {"digest": hex} when every file could be digested; {"digest": None, "why": ...}
    when one cannot be: a path that is not full, one outside `roots` (the filing agent's home and its projects: required,
    with no default), one that passes through a link or junction, a name that holds secrets, a hard link, something that
    is not a plain file, a file too large, or a file that is not there (whether it matches is then unknown, never
    "current"). `budget`, when given, is {"left": bytes} shared across one page build: a file whose bytes would pass it
    is not read ("not checked: over the read budget"). The filer computes the same function when it measures."""
    if not isinstance(files, list) or not files or not all(isinstance(f, str) and f.strip() for f in files):
        return {"digest": None, "why": "the evidence should name its files"}
    if len(files) > MAX_FILES:
        return {"digest": None, "why": f"the evidence names {len(files)} files; at most {MAX_FILES} are read"}
    roots = [r for r in (roots or []) if isinstance(r, str) and r.strip()]
    if not roots:
        return {"digest": None, "why": "no folder is given where the filing agent's evidence may be read"}
    now = time.monotonic()
    h = hashlib.sha256()
    for f in sorted(set(files)):
        root = next((r for r in sorted(roots, key=len, reverse=True) if _below(f, r)), None)
        try:
            if root is None:
                raise _Unread(f"{f} is outside the filing agent's home and its projects, so it is not read")
            digest = _content(f, root, now, budget)
        except _Unread as e:
            return {"digest": None, "why": str(e)}
        except OSError as e:
            return {"digest": None, "why": f"{f} cannot be read ({e.strerror or e})"}
        h.update(f.encode("utf-8", "surrogatepass") + b"\0" + digest.encode("ascii") + b"\0")
    return {"digest": h.hexdigest()}


def freshness(evidence, roots, budget: dict | None = None) -> dict | None:
    """Whether the evidence a change was measured on is still today's: "current" when today's digest is the card's,
    "stale" when it differs, "unknown" (with why) when today's cannot be worked out or the card carries none."""
    if not isinstance(evidence, dict):
        return None
    files, said = evidence.get("files"), evidence.get("digest")
    if not isinstance(said, str) or not said.strip():
        return {"state": "unknown", "why": "the card carries no digest of its evidence", "files": files or []}
    now = fingerprint(files, roots, budget)
    if now["digest"] is None:
        return {"state": "unknown", "why": now["why"], "files": files or []}
    state = "current" if now["digest"].lower() == said.strip().lower() else "stale"
    return {"state": state, "files": files, "digest": said.strip(), "today": now["digest"]}


# ---- the card (rrsi's done() contract, reworked) ------------------------------------------------------------------
def _predicted(value, notes: list) -> list[dict]:
    if value is None:
        notes.append(("missing field", "it predicts no measure, so its effect cannot be checked"))
        return []
    if not isinstance(value, list):
        notes.append(("bad field", "its predicted measures are not a list"))
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append({"measure": item.strip(), "direction": None, "p": None})
            continue
        m = _t(item, "measure")
        if m is None:
            notes.append(("bad field", f"a predicted measure has no name: {str(item)[:60]}"))
            continue
        d = _t(item, "direction")
        p = item.get("p")
        ok_p = isinstance(p, (int, float)) and not isinstance(p, bool) and math.isfinite(p) and 0 <= p <= 1
        if d is not None and d not in DIRECTIONS:
            notes.append(("bad field", f"the measure {m} has the direction {d!r}, not up or down"))
            d = None
        if p is not None and not ok_p:
            notes.append(("bad field", f"the measure {m} has the chance {p!r}, not a number from 0 to 1"))
        out.append({"measure": m, "direction": d, "p": float(p) if ok_p else None})
    return out


def _undo(value, notes: list) -> dict | None:
    if value is None:
        notes.append(("missing field", "it has no undo"))
        return None
    commit = _t(value, "commit")
    if commit and COMMIT.fullmatch(commit):
        return {"commit": commit}
    restore = _t(value, "restore")
    if restore:
        frm = _t(value, "from")
        if frm and not COMMIT.fullmatch(frm):
            notes.append(("bad field", "its undo's from is not a commit hash"))
            frm = None
        return {"restore": restore, "from": frm}
    notes.append(("bad field", "its undo is neither {\"commit\": a hash} nor {\"restore\": a file}"))
    return None


def fields(v: dict) -> tuple[dict, list[tuple[str, str]]]:
    """A change card's own fields, and the problems that leave it still shown (the caller has checked REQUIRED)."""
    notes: list[tuple[str, str]] = []
    out = {k: _t(v, k) for k in TEXTS}
    out["predicted"] = _predicted(v.get("predicted"), notes)
    out["undo"] = _undo(v.get("undo"), notes)
    out["prune"] = v.get("prune") is True
    out["what_changes"] = _tree(v.get("tree"), notes)
    ev = v.get("evidence")
    if ev is not None and not (isinstance(ev, dict) and isinstance(ev.get("files"), list)):
        notes.append(("bad field", "its evidence is not {\"files\": [...], \"digest\": ...}"))
        ev = None
    out["evidence"] = {"files": [f for f in ev["files"] if isinstance(f, str)],
                       "digest": _t(ev, "digest")} if ev else None
    return out, notes


# ---- after the change (rrsi loop.attribute, reworked) --------------------------------------------------------------
def outcome(v: dict) -> tuple[dict | None, str | None]:
    """An outcome line as an entry, or (None, why) when it cannot be one."""
    moved = v.get("moved")
    if moved is None:
        moved = {}
    if not isinstance(moved, dict) or not all(isinstance(k, str) and m in MOVES for k, m in moved.items()):
        return None, "its moved is not a record of measures, each up, down or none"
    regressions = v.get("regressions") or []
    if not isinstance(regressions, list) or not all(isinstance(r, str) for r in regressions):
        return None, "its regressions are not a list of texts"
    undone = v.get("undone", False)
    if not isinstance(undone, bool):
        return None, "its undone is not true or false"
    return {"at": _t(v, "at") or "", "moved": dict(moved), "regressions": list(regressions), "undone": undone}, None


def judged(change: dict, outcomes: list) -> dict | None:
    """The card's predictions against the last outcome measured while the change was in place (the latest with undone
    false): each measure hit, missed or not measured, and the Brier terms of those with a stated chance and a
    direction. An undo records the undo, and never rescores or erases that measurement. None before any outcome."""
    if not outcomes:
        return None
    measured = [o for o in outcomes if not o["undone"]]
    last = measured[-1] if measured else {"moved": {}, "regressions": []}
    rows, terms = [], []
    for p in change.get("predicted") or []:
        got = last["moved"].get(p["measure"])
        if got is None or p["direction"] is None:
            rows.append({**p, "moved": got, "hit": None})
            continue
        hit = got == p["direction"]
        rows.append({**p, "moved": got, "hit": hit})
        if p["p"] is not None:
            terms.append((p["p"] - (1.0 if hit else 0.0)) ** 2)
    named = {p["measure"] for p in change.get("predicted") or []}
    unpredicted = [r for r in last["regressions"] if r not in named]
    return {"measures": rows, "terms": terms, "unpredicted_regressions": unpredicted,
            "undone": outcomes[-1]["undone"], "measured_at": last.get("at")}


def score(records: list[dict]) -> dict:
    """Per agent: changes filed, decided (a decision card asking about it was answered, or it has an outcome), and the
    Brier score of their stated chances against what was measured (0 is perfect, 1 the worst), with how many
    predictions it counts. A score over no prediction is None, never 0."""
    out: dict = {}
    for c in records:
        if c.get("kind") != "change":
            continue
        a = out.setdefault(c.get("seat"), {"filed": 0, "decided": 0, "brier": None, "scored": 0, "_terms": []})
        a["filed"] += 1
        a["decided"] += bool(c.get("decided") or c.get("outcomes"))
        j = c.get("judged")
        if j:
            a["_terms"] += j["terms"]
    for a in out.values():
        terms = a.pop("_terms")
        a["scored"] = len(terms)
        a["brier"] = round(sum(terms) / len(terms), 4) if terms else None
    return out
