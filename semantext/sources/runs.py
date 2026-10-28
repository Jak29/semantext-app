"""Run records: what a checker that runs outside Semantext recorded about a rule, read and judged, never re-run.

The shape is schema 1 (semantext/schemas/run-record-1.json; RUN-RECORD-SCHEMA.md). A record is one line of
`runs/<checker>.jsonl` under a folder the sources file lists in "run_records". Each line that cannot be used is a
problem with its reason, never dropped, and the newest usable record for a (rule, checker) pair decides.

What a record can earn a rule, and nothing more (verdict):
  guarded       both arms ran (ran > 0) and every case passed, the rule's text hashes to rule.sha256 now, every subject
                blob is the git blob id of the bytes in place now, and `at` is within the age bound;
  stale         the same record, but the rule's text, a subject's bytes or the age no longer hold; it says which. The
                page shows it as "guarded once";
  failed        a well-formed record whose arms did not all pass: it earns nothing, and the page says so.
A record's `findings` (a list of short texts) never change the level; they go with the verdict and the page shows
"guarded, with N findings" and each one as text, so a passing count never hides them. A record's own `outcome`
(OUTCOMES) is read too: "failed" or "not proved" is never guarded, whatever the counts say (the state is failed, and
the outcome goes with it); an outcome not in OUTCOMES refuses the record. `summary` is an extra and decides nothing.
In `detail`, a case whose status is "warned-open" (a warning, the violation let through) ran and was not refused.

Refused, each a problem (the kinds): too-long, not-json, too-deep (deeper than semantext.jsonread allows),
not-a-record, no-schema, wrong-schema, bad-checker-name, bad-field, bad-findings, bad-outcome, arm-not-run,
detail-disagrees, bad-time,
future-time (more than SKEW after now), outside-roots, closed-place. A folder that cannot be read is no-folder,
no-runs, link, unreadable or closed-place.

A record is what the checker says: its shape and its freshness against the bytes are checked here, and nothing about
whether the checker is honest. Files are opened for reading only; nothing is started.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import jsonread
from . import problem, read_lines
from .closed import in_closed_place as is_closed_place   # the built-in rule

SCHEMA = 1
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schemas" / "run-record-1.json"
KEY, DAYS_KEY = "run_records", "run_record_days"
DAYS = 30                               # the age bound when the sources file sets none
SKEW = timedelta(minutes=2)             # a record this far ahead of the clock is still read as now
MAX_SUBJECT = 64 * 1024 * 1024          # bytes hashed for one subject; a larger file is stale, never read whole
MAX_TEXT = 100                          # characters in a checker's name or version
MAX_FINDINGS = 100                      # findings shown from one record, each cut to 300 characters
HEX = re.compile(r"[0-9a-f]{64}")
BLOB = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
AT = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z")
ARMS = (("must_pass", "passed"), ("must_refuse", "refused"))
OUTCOMES = ("clean", "with findings", "failed", "not proved")   # a record's own word for its run (RUN-RECORD-SCHEMA.md)
NOT_GUARDED = ("failed", "not proved")                          # an outcome that no count can make guarded


class Refused(ValueError):
    def __init__(self, kind: str, text: str):
        super().__init__(text)
        self.kind = kind


# ---- small judgements ---------------------------------------------------------------------------------------------
def rule_hash(words: str) -> str:
    """The rule's text as the card shows it (spaces already joined by the rules reader), hashed as a record names it."""
    return hashlib.sha256(words.encode("utf-8", "surrogatepass")).hexdigest()


def blob_id(data: bytes, hex_len: int = 40) -> str:
    """The git blob id of these bytes: SHA-1 of "blob <length>\\0" and the bytes, or SHA-256 for a 64-hex id."""
    algo = hashlib.sha256 if hex_len == 64 else hashlib.sha1
    return algo(b"blob %d\x00" % len(data) + data).hexdigest()


def _plain(value) -> bool:
    """Plain text: printable characters only, no space at either end, at most MAX_TEXT long."""
    return isinstance(value, str) and 0 < len(value) <= MAX_TEXT and value.isprintable() and value == value.strip()


def _count(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _key(path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _within(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)


def parse_at(text) -> datetime:
    m = AT.fullmatch(text) if isinstance(text, str) else None
    if not m:
        raise Refused("bad-time", "'at' is not a UTC time written as 2026-10-23T21:00:00Z")
    y, mo, d, h, mi, s, frac = m.groups()
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), int((frac or "0").ljust(6, "0")),
                        tzinfo=timezone.utc)
    except ValueError:
        raise Refused("bad-time", f"'at' is not a real time ({text})") from None


def folders(cfg: dict) -> list[str]:
    said = cfg.get(KEY)
    items = [said] if isinstance(said, str) else said if isinstance(said, list) else []
    return [s for s in items if isinstance(s, str) and s.strip()]


def bound(cfg: dict) -> int:
    """The age bound in days: the sources file's run_record_days when it is a whole number over 0, else DAYS."""
    days = cfg.get(DAYS_KEY)
    return days if isinstance(days, int) and not isinstance(days, bool) and days > 0 else DAYS


def _home(cfg: dict):
    """Where the person's closures are read from: beside the sources file this config came from, if it says."""
    f = cfg.get("_file")
    return Path(f).parent if isinstance(f, str) and f else None


# ---- one line -----------------------------------------------------------------------------------------------------
def _section(record: dict, name: str) -> dict:
    value = record.get(name)
    if not isinstance(value, dict):
        raise Refused("bad-field", f"'{name}' is missing or is not a section")
    return value


def _arms(record: dict) -> dict:
    arms = _section(record, "arms")
    out = {}
    for arm, ok in ARMS:
        a = arms.get(arm)
        if not isinstance(a, dict) or not _count(a.get("ran")) or not _count(a.get(ok)):
            raise Refused("bad-field", f"arms.{arm} needs ran and {ok}, each a whole number")
        if a["ran"] == 0:
            raise Refused("arm-not-run", f"arms.{arm} ran 0 cases, so it shows nothing")
        if a[ok] > a["ran"]:
            raise Refused("bad-field", f"arms.{arm} says {a[ok]} {ok} of {a['ran']} run")
        out[arm] = {"ran": a["ran"], ok: a[ok], "how": a.get("how") if isinstance(a.get("how"), str) else None}
    detail = record.get("detail")
    if isinstance(detail, dict) and isinstance(detail.get("arms"), list):
        # The first outside checker's shape: one case per item, with its "class" (the arm) and "status"; a case with
        # status "not-run" is listed and never counted. Any other status ran, and only "passed" is a pass or a refusal:
        # "warned-open" (a warning with the violation let through) is a must-refuse case that ran and was not refused.
        cases = [c for c in detail["arms"] if isinstance(c, dict)]
        for arm, ok in ARMS:
            mine = [c for c in cases if c.get("class") == arm and c.get("status") != "not-run"]
            good = sum(c.get("status") == "passed" for c in mine)
            if (len(mine), good) != (out[arm]["ran"], out[arm][ok]):
                raise Refused("detail-disagrees", f"arms.{arm} says {out[arm][ok]} {ok} of {out[arm]['ran']}, and "
                                                  f"detail lists {good} passed of {len(mine)} run")
    if isinstance(detail, dict):
        for arm, ok in ARMS:
            cases = detail.get(arm)
            if cases is None:
                continue
            if not isinstance(cases, list) or len(cases) != out[arm]["ran"]:
                listed = len(cases) if isinstance(cases, list) else "no list of"
                raise Refused("detail-disagrees", f"arms.{arm} ran {out[arm]['ran']}, and detail lists {listed} cases")
            oks = [c.get("ok") if isinstance(c, dict) else None for c in cases]
            if all(isinstance(o, bool) for o in oks) and sum(oks) != out[arm][ok]:
                raise Refused("detail-disagrees", f"arms.{arm} says {out[arm][ok]} {ok}, and detail marks {sum(oks)} ok")
    return out


def _subjects(record: dict, root: str, roots: list[str], home) -> list[dict]:
    from .rules import not_local   # here: rules imports this module
    items = record.get("subject")
    if not isinstance(items, list) or not items:
        raise Refused("bad-field", "'subject' needs at least one {path, blob}")
    out = []
    for s in items:
        path, blob = (s.get("path"), s.get("blob")) if isinstance(s, dict) else (None, None)
        if not isinstance(path, str) or not path.strip() or "\x00" in path:
            raise Refused("bad-field", "a subject has no path, or one that is not text")
        if not isinstance(blob, str) or not BLOB.fullmatch(blob):
            raise Refused("bad-field", f"the subject {path[:80]} has no git blob id (40 or 64 lowercase hex)")
        if not_local(path):
            raise Refused("outside-roots", f"the subject {path[:80]} is a network or device path")
        full = os.path.abspath(os.path.join(root, os.path.expanduser(path)))
        forms = {_key(full)}
        try:
            forms.add(_key(os.path.realpath(full)))
        except (OSError, ValueError):
            pass
        inside = [r for r in roots if all(any(_within(f, k) for k in _forms(r)) for f in forms)]
        if not inside:
            raise Refused("outside-roots", f"the subject {path[:80]} lies outside the listed run-record folders")
        if is_closed_place(full, home):
            raise Refused("closed-place", f"the subject {path[:80]} is in a place you closed")
        out.append({"path": path, "full": full, "blob": blob})
    return out


def _forms(root: str) -> set[str]:
    out = {_key(root)}
    try:
        out.add(_key(os.path.realpath(root)))
    except (OSError, ValueError):
        pass
    return out


def record(text: str, root: str, roots: list[str], now: datetime, home=None) -> dict:
    """One line as a usable record, or Refused with the kind and the reason."""
    def constant(name):
        raise ValueError(f"{name} is not JSON")
    try:
        data = jsonread.loads(text, parse_constant=constant)
    except jsonread.NotJSON as e:
        if e.deep:
            raise Refused("too-deep", str(e)) from None
        raise Refused("not-json", f"the line is not JSON ({e.msg})") from None
    except ValueError as e:
        raise Refused("not-json", f"the line is not JSON ({e})") from None
    if not isinstance(data, dict):
        raise Refused("not-a-record", "the line is not a record (a JSON object)")
    if "schema" not in data:
        raise Refused("no-schema", "the record names no schema")
    if data["schema"] != SCHEMA or isinstance(data["schema"], bool):
        raise Refused("wrong-schema", f"the record is schema {str(data['schema'])[:20]}, and only schema 1 is read")
    checker = _section(data, "checker")
    if not _plain(checker.get("name")):
        raise Refused("bad-checker-name", "the checker's name is not plain text (printable, at most 100 characters)")
    if not _plain(checker.get("version")):
        raise Refused("bad-field", "checker.version is not plain text")
    if checker.get("sha256") is not None and not (isinstance(checker["sha256"], str) and HEX.fullmatch(checker["sha256"])):
        raise Refused("bad-field", "checker.sha256 is not 64 lowercase hex")
    rule = _section(data, "rule")
    rid = rule.get("id")
    if not isinstance(rid, str) or not rid.strip():
        raise Refused("bad-field", "rule.id is missing or not text")
    if not isinstance(rule.get("sha256"), str) or not HEX.fullmatch(rule["sha256"]):
        raise Refused("bad-field", "rule.sha256 is not 64 lowercase hex")
    arms = _arms(data)
    at = parse_at(data.get("at"))
    if at > now + SKEW:
        raise Refused("future-time", f"the record is dated {data['at']}, after now")
    for name in ("by", "built_by", "note"):   # built_by: who built the checker (schema 1, optional and additive)
        if data.get(name) is not None and not isinstance(data[name], str):
            raise Refused("bad-field", f"'{name}' is not text")
    findings = data.get("findings")
    if findings is not None and not (isinstance(findings, list) and all(isinstance(f, str) for f in findings)):
        raise Refused("bad-findings", "'findings' is not a list of texts")
    outcome = data.get("outcome")
    if outcome is not None and outcome not in OUTCOMES:
        raise Refused("bad-outcome", f"'outcome' is {str(outcome)[:40]!r}, and only {', '.join(OUTCOMES)} are known")
    subject = _subjects(data, root, roots, home)
    return {"rule": " ".join(rid.split()), "rule_sha256": rule["sha256"], "checker": checker["name"],
            "version": checker["version"], "checker_sha256": checker.get("sha256"), "at": data["at"], "when": at,
            "by": (data.get("by") or "")[:300] or None, "built_by": (data.get("built_by") or "").strip()[:300] or None,
            "note": (data.get("note") or "")[:300] or None,
            "findings": [f[:300] for f in findings or [] if f.strip()][:MAX_FINDINGS], "arms": arms, "subject": subject,
            "outcome": outcome}


# ---- the folders --------------------------------------------------------------------------------------------------
def _linked(p: Path) -> bool:
    try:
        return p.is_symlink() or bool(getattr(os.path, "isjunction", lambda _: False)(p))
    except OSError:
        return True


def read(cfg: dict, now: datetime | None = None) -> dict:
    """Every usable record, the newest per (rule, checker): {"off", "folders", "records": {rule id: [records]},
    "days", "problems"}. Off when the sources file lists no run-record folder."""
    from .rules import not_local   # here: rules imports this module
    listed = folders(cfg)
    if not listed:
        return {"off": True, "folders": [], "records": {}, "days": bound(cfg), "problems": []}
    now = now or datetime.now(timezone.utc)
    home = _home(cfg)
    problems: list[dict] = []
    roots, usable = [], []
    for said in listed:
        full = os.path.expanduser(said.strip())
        if not_local(full):
            problems.append(problem(said, None, "no-folder", "a network or device path is not read"))
        elif not os.path.isabs(full):
            problems.append(problem(said, None, "no-folder", "a run-record folder must be a full path"))
        elif is_closed_place(full, home):
            problems.append(problem(said, None, "closed-place", "this folder is in a place you closed, so it is not read"))
        elif not os.path.isdir(full):
            problems.append(problem(said, None, "no-folder", "the run-record folder is not there"))
        else:
            roots.append(os.path.abspath(full))
    newest: dict[tuple[str, str], tuple] = {}
    order = 0
    for root in roots:
        runs = Path(root) / "runs"
        if _linked(runs):
            problems.append(problem(runs, None, "link", "is a link, so it is not followed"))
            continue
        if not runs.is_dir():
            problems.append(problem(runs, None, "no-runs", "this run-record folder holds no runs folder"))
            continue
        for f in sorted(runs.glob("*.jsonl"), key=lambda p: p.name):
            if _linked(f):
                problems.append(problem(f, None, "link", "is a link, so it is not followed"))
                continue
            if not f.is_file():
                continue
            try:
                lines = list(read_lines(f))
            except OSError as e:
                problems.append(problem(f, None, "unreadable", f"{type(e).__name__}: {e.strerror or e}"))
                continue
            for n, text in lines:
                order += 1
                if text is None:
                    problems.append(problem(f, n, "too-long", "the line is too long to be read"))
                    continue
                try:
                    rec = record(text, root, roots, now, home)
                except Refused as e:
                    problems.append(problem(f, n, e.kind, str(e)))
                    continue
                rec.update(source=str(f), line=n)
                key = (rec["rule"], rec["checker"])
                if key not in newest or (rec["when"], order) >= newest[key][0]:
                    newest[key] = ((rec["when"], order), rec)
    by_rule: dict[str, list[dict]] = {}
    for (rid, _), (_, rec) in sorted(newest.items()):
        by_rule.setdefault(rid, []).append(rec)
    return {"off": False, "folders": roots, "records": by_rule, "days": bound(cfg), "problems": problems}


# ---- what a record earns ------------------------------------------------------------------------------------------
def _bytes_now(full: str) -> tuple[bytes | None, str | None]:
    try:
        size = os.path.getsize(full)
        if not os.path.isfile(full):
            return None, "is not a file now"
        if size > MAX_SUBJECT:
            return None, f"is over {MAX_SUBJECT // 2**20} MiB, so its bytes are not hashed"
        with open(full, "rb") as fh:
            return fh.read(), None
    except FileNotFoundError:
        return None, "is not there now"
    except OSError as e:
        return None, f"could not be read now ({type(e).__name__})"


def verdict(rec: dict, words: str, now: datetime | None = None, days: int = DAYS) -> dict:
    """What one record earns a rule whose text is `words` now: state guarded, stale (with which reasons) or failed."""
    now = now or datetime.now(timezone.utc)
    arms = rec["arms"]
    out = {k: rec[k] for k in ("checker", "version", "at", "by", "note", "findings", "outcome", "source", "line")
           if k in rec}
    out.update(arms={a: dict(v) for a, v in arms.items()}, subject=[s["path"] for s in rec["subject"]], stale=[])
    if any(arms[a][ok] != arms[a]["ran"] for a, ok in ARMS) or rec.get("outcome") in NOT_GUARDED:
        out["state"] = "failed"
        return out
    if rule_hash(words) != rec["rule_sha256"]:
        out["stale"].append("the rule's words have changed since it was recorded")
    for s in rec["subject"]:
        data, why = _bytes_now(s["full"])
        if why:
            out["stale"].append(f"{s['path']} {why}")
        elif blob_id(data, len(s["blob"])) != s["blob"]:
            out["stale"].append(f"{s['path']} has changed since it was checked")
    age = now - rec["when"]
    if age > timedelta(days=days):
        out["stale"].append(f"it was recorded {age.days} days ago, past the {days}-day bound")
    out["state"] = "stale" if out["stale"] else "guarded"
    return out
