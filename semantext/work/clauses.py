"""Acceptance clauses: what proves an item done, declared at create, judged now against live evidence (PM-DESIGN r4).

A clause names a kind of evidence and what it must show. The evidence is read through injected readers (the Readers
protocol below), so this module judges and never reads: slice 1 needs no real reader, and the run-record, landed and
verdict readers come later (the review's slice 2b). A link only points at a candidate; the clause decides.

Done is derived, never moved to: an item in review whose every clause is met NOW, by evidence whose producer is not the
item's builder, shows as done, with the strength of its evidence named (landed, verified, installed, accepted). When a
clause stops holding (a record gone stale, a blob changed) the item shows "proof no longer holds". A target the reader
cannot read, or one in a closed place, is "unknown", never met (the attack, F11).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from ..sources.closed import is_closed_place
from .events import LINK_TYPES, WorkRefused, check_plain

KINDS = {
    "run-record": {"rule", "outcome", "max_findings", "fresh_days"},
    "landed": {"repo", "commit", "branch"},
    "verdict": {"piece"},
    "jak-decision": {"register"},
    "outcome": {"out_id"},
}
STRENGTH = {"run-record": "verified", "verdict": "verified", "landed": "landed", "outcome": "installed",
            "jak-decision": "accepted"}
READER = {"run-record": "run_record", "landed": "landed", "verdict": "verdict", "jak-decision": "decision",
          "outcome": "outcome"}
GOOD_OUTCOMES = ("clean", "with findings")     # never failed or not proved (the run-record rule, r4)
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", re.ASCII)
MAX_CLAUSES = 16


@runtime_checkable
class Readers(Protocol):
    """Each method is given one clause and returns the fact it found, a record, or None when it found none; a fact
    {"unknown": why} says the reader could not read (the clause is unknown, never met). A run-record fact may carry
    "run", what runs.verdict made of the record, in place of the record and the bytes now. Every fact
    carries "producer" (who made the evidence; a fact that names no maker is unknown), and may carry "checker_by" and "checker_cleared" (who built the checker that made
    it, and whether that checker has its own clean verdict), and "path" (where it was read, judged against the
    closures). The kinds' own fields are in judge()."""

    def run_record(self, clause: dict): ...
    def landed(self, clause: dict): ...
    def verdict(self, clause: dict): ...
    def decision(self, clause: dict): ...
    def outcome(self, clause: dict): ...


def check_clauses(clauses) -> list[dict]:
    if not isinstance(clauses, list) or len(clauses) > MAX_CLAUSES:
        raise WorkRefused("MALFORMED", f"clauses is a list of at most {MAX_CLAUSES}")
    out = []
    for c in clauses:
        check_plain(c)
        if not isinstance(c, dict) or not isinstance(c.get("kind"), str) or c["kind"] not in KINDS:
            raise WorkRefused("MALFORMED", f"a clause's kind is one of {', '.join(KINDS)}")
        if set(c) != KINDS[c["kind"]] | {"kind"}:
            raise WorkRefused("MALFORMED", f"a {c['kind']} clause has exactly "
                                           f"{', '.join(sorted(KINDS[c['kind']]))}")
        _shape(c)
        out.append(dict(c))
    return out


def _shape(c: dict) -> None:
    k = c["kind"]
    bad = None
    if k == "run-record":
        n, d = c["max_findings"], c["fresh_days"]
        if not isinstance(c["rule"], str) or not NAME_RE.fullmatch(c["rule"]):
            bad = "rule is a rule id"
        elif c["outcome"] not in GOOD_OUTCOMES:
            bad = "outcome is clean or with findings"
        elif isinstance(n, bool) or not isinstance(n, int) or n < 0:
            bad = "max_findings is a whole number"
        elif isinstance(d, bool) or not isinstance(d, int) or not 1 <= d <= 3650:
            bad = "fresh_days is a whole number of days, 1 to 3650"
    elif k == "landed":
        if not all(isinstance(c[x], str) and NAME_RE.fullmatch(c[x]) for x in ("repo", "branch")):
            bad = "repo and branch are names"
        elif not isinstance(c["commit"], str) or not LINK_TYPES["commit"].fullmatch(c["commit"]):
            bad = "commit is a commit id"
    elif k == "verdict":
        bad = None if isinstance(c["piece"], str) and LINK_TYPES["piece"].fullmatch(c["piece"]) else "piece is an id"
    elif k == "jak-decision":
        ok = isinstance(c["register"], str) and LINK_TYPES["decision"].fullmatch(c["register"])
        bad = None if ok else "register is a J- id"
    elif k == "outcome":
        bad = None if isinstance(c["out_id"], str) and re.fullmatch(r"out_[0-9A-Z]{26}", c["out_id"]) else \
            "out_id is an out_ id"
    if bad:
        raise WorkRefused("MALFORMED", f"{k} clause: {bad}")


def named(who) -> bool:
    """A name that names someone: text with something in it besides blanks. None, "", "  " and a non-text value name
    nobody, so they can be told from no builder."""
    return isinstance(who, str) and bool(who.strip())


def _when(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def judge(clause: dict, fact, builders: set, now: datetime, ctx=None, about=None) -> dict:
    """One clause against what its reader found: {"state": met | unmet | stale | unknown, "why", "strength"}. "stale"
    is evidence that once met the clause and no longer does (proof no longer holds). `about` is the item's id and its
    epic's: the ids a decision must name."""
    out = {"clause": clause, "strength": STRENGTH[clause["kind"]]}
    if fact is None:
        return {**out, "state": "unmet", "why": "no evidence found"}
    if not isinstance(fact, dict):
        return {**out, "state": "unknown", "why": "the reader gave something that is not a record"}
    if isinstance(fact.get("unknown"), str):   # the reader could not read (no file, no reader yet), and says why
        return {**out, "state": "unknown", "why": fact["unknown"]}
    if fact.get("path") is not None and is_closed_place(fact["path"], ctx):
        return {**out, "state": "unknown", "why": "the evidence is in a closed place, so it is not read"}
    if not named(fact.get("producer")):   # a missing maker is unknown, never independent (G6, finding 1)
        return {**out, "state": "unknown", "why": "the evidence names no maker, so it cannot be told from the "
                                                  "builder's own"}
    if fact.get("producer") in builders:
        return {**out, "state": "unmet", "why": "the evidence was made by the item's own builder"}
    if fact.get("checker_by") in builders and fact.get("checker_cleared") is not True:
        return {**out, "state": "unmet", "why": "the checker was built by the item's builder and has no clean "
                                                "verdict of its own"}
    state, why = KIND_JUDGES[clause["kind"]](clause, fact, now)
    if state == "met":
        state, why = _about_and_checker(clause, fact, about or set(), state, why)
    return {**out, "state": state, "why": why}


CHECKED = ("run-record", "landed", "outcome")   # evidence a checker made: who built the checker bears on it


def _about_and_checker(clause, fact, about, state, why):
    """Two rules a met clause must still pass (PM-DESIGN, decided 24 October, A2). A decision must be about this item:
    the register entry's own words name the item's id or its epic's id; the item naming the J-id is not enough, since
    the builder chooses the clause. And a checker's evidence counts only when the checker's builder is named (and is
    not the item's builder, judged above) or the checker has its own clean verdict; no reader names it yet, so until
    then the clause is unknown, never met."""
    if clause["kind"] == "jak-decision":
        names = fact["entry"].get("names") if isinstance(fact["entry"].get("names"), list) else []
        if not about & set(names):
            return "unmet", "the decision does not name this item or its epic (the item naming the decision is not " \
                            "enough)"
    if clause["kind"] in CHECKED and not named(fact.get("checker_by")) and fact.get("checker_cleared") is not True:
        return "unknown", "who built the checker is not known yet, so whether it is the item's builder cannot be told"
    return state, why


def _from_runs(c, v):
    """A clause against what runs.verdict made of the newest run record for its rule, with the clause's own age bound:
    the run reader's judgement of the arms, the outcome, the rule's words, the subjects' bytes and the age, never a
    copy of it (slice 2b)."""
    findings = v.get("findings") if isinstance(v.get("findings"), list) else []
    if v.get("state") == "failed":
        return "unmet", f"its run {'was ' + repr(v['outcome']) if v.get('outcome') else 'did not pass both arms'}, " \
                        f"never guarded"
    outcome = v.get("outcome") or ("with findings" if findings else "clean")
    if c["outcome"] == "clean" and outcome != "clean":
        return "unmet", "the clause asks for a clean outcome"
    if len(findings) > c["max_findings"]:
        return "unmet", f"{len(findings)} findings, more than the clause's {c['max_findings']}"
    if v.get("state") == "stale":
        return "stale", "; ".join(v.get("stale") or ["the record no longer holds"])
    if v.get("state") == "guarded":
        return "met", f"a run record of {v.get('checker')} for this rule, on these bytes, within {c['fresh_days']} days"
    return "unmet", "the run reader gave no verdict"


def _run_record(c, f, now):
    if isinstance(f.get("run"), dict):
        return _from_runs(c, f["run"])
    rec = f.get("record")
    if not isinstance(rec, dict) or rec.get("schema") != 1:
        return "unmet", "no run record of schema 1"
    if rec.get("outcome") not in GOOD_OUTCOMES:
        return "unmet", f"its outcome is {rec.get('outcome')!r}, never guarded"
    if c["outcome"] == "clean" and rec["outcome"] != "clean":
        return "unmet", "the clause asks for a clean outcome"
    rule = rec.get("rule") if isinstance(rec.get("rule"), dict) else {}
    if rule.get("id") != c["rule"]:
        return "unmet", "the record is for another rule"
    findings = rec.get("findings") if isinstance(rec.get("findings"), list) else None
    if findings is None or len(findings) > c["max_findings"]:
        return "unmet", "more findings than the clause accepts, or none listed"
    at = _when(rec.get("at"))
    if at is None:
        return "unmet", "the record has no time"
    blobs, now_blobs = rec.get("subject"), f.get("blobs_now")
    if rule.get("sha256") != f.get("rule_sha_now") or not isinstance(blobs, dict) or blobs != now_blobs:
        return "stale", "the rule's text or a subject's bytes changed since the record"
    if now - at > timedelta(days=c["fresh_days"]):
        return "stale", f"the record is older than {c['fresh_days']} days"
    return "met", "a run record for this rule, on these bytes, within its bound"


def _landed(c, f, now):
    fact = f.get("fact")
    if not isinstance(fact, dict):
        return "unmet", "no fact record from a git-reading checker (a commit id alone is never proof)"
    if (fact.get("commit"), fact.get("branch"), fact.get("repo")) != (c["commit"], c["branch"], c["repo"]):
        return "unmet", "the fact is about another commit, branch or repository"
    if fact.get("ancestor") is True:
        return "met", "the commit is on the branch, by an outside checker's fact"
    return ("stale", "the commit was on the branch and is no longer") if fact.get("was_ancestor") else \
        ("unmet", "the commit is not on the branch")


def _name(x) -> str:
    """A name as two verdict rows are compared: stripped and case-folded, so 'alice ' is alice (round 4, low)."""
    return x.strip().casefold() if isinstance(x, str) else ""


def _verdict(c, f, now):
    v, piece = f.get("verdict"), f.get("piece")
    if not isinstance(v, dict) or not isinstance(piece, dict) or v.get("piece") != c["piece"] or \
            piece.get("id") != c["piece"]:
        return "unmet", "no verdict row against this piece"
    if not named(piece.get("originator")):   # unknown, never independent (G6, finding 2)
        return "unknown", "the piece names no originator, so its attacker cannot be told from its author"
    if not _name(v.get("attacker")) or _name(v.get("attacker")) == _name(piece.get("originator")):
        return "unmet", "the verdict's attacker is the piece's originator"
    if v.get("verdict") != "survived":
        return ("stale", "a later verdict killed it") if f.get("was_survived") else \
            ("unmet", f"the verdict is {v.get('verdict')!r}")
    return "met", "an independent verdict: survived"


def _decision(c, f, now):
    e = f.get("entry")
    if not isinstance(e, dict) or e.get("id") != c["register"]:
        return "unmet", "no register entry (a closed card is never the person's decision)"
    if not isinstance(e.get("line"), str) or not e["line"].strip():
        return "unmet", "the register entry carries no transcript line of the person's"
    if e.get("state") == "parked":
        return "unmet", "the person parked this decision"
    return "met", "a register entry with the person's own line"


def _outcome(c, f, now):
    e = f.get("entry")
    if not isinstance(e, dict) or e.get("id") != c["out_id"]:
        return "unmet", "no outcome entry"
    if e.get("undo"):
        return "stale", "the outcome was undone"
    verify = e.get("verify") if isinstance(e.get("verify"), dict) else {}
    if e.get("state") != "applied" or verify.get("ok") is not True:
        return "unmet", "not applied, or its verify did not pass"
    return "met", "applied and verified, with no undo"


KIND_JUDGES = {"run-record": _run_record, "landed": _landed, "verdict": _verdict, "jak-decision": _decision,
               "outcome": _outcome}


def evaluate(item: dict, readers, now: datetime | None = None, ctx=None) -> dict:
    """What the page shows of an item's progress, read now: each clause judged, the shown state and its badge. The
    fold's state is never changed; this is an overlay with its own time ("read_at")."""
    now = now or datetime.now(timezone.utc)
    builders = {x for x in (item.get("owner"), item.get("creator")) if x}
    about = {x for x in (item.get("id"), item.get("epic")) if x}
    judged = []
    for c in item.get("clauses") or []:
        try:
            fact = getattr(readers, READER[c["kind"]])(c)
        except Exception as e:  # noqa: BLE001  a reader that fails leaves the clause unknown, never met
            judged.append({"clause": c, "strength": STRENGTH[c["kind"]], "state": "unknown",
                           "why": f"the reader failed: {type(e).__name__}"})
            continue
        judged.append(judge(c, fact, builders, now, ctx, about))
    states = {j["state"] for j in judged}
    shown, badge = item["state"], None
    if item["state"] == "done":
        badge = "done (the person's word)" if item.get("done_by") == "word" else "done"
    elif item["state"] == "review" and judged:
        if "stale" in states:
            badge = "proof no longer holds"
        elif states == {"met"}:
            shown = "done"
            badge = "done (" + ", ".join(sorted({j["strength"] for j in judged})) + ")"
        elif "unknown" in states and "unmet" not in states:
            badge = "review (proof unknown)"
    return {"id": item["id"], "state": item["state"], "shown": shown, "badge": badge, "clauses": judged,
            "read_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


def link_badges(item: dict, read_link, ctx=None) -> list[dict]:
    """Each link with its live state from `read_link(link) -> {"state", "path"?} | None`. A target in a closed place,
    or one that cannot be read, is "unknown", never its state (the attack, F11)."""
    out = []
    for link in item.get("links") or []:
        try:
            got = read_link(link)
        except Exception:  # noqa: BLE001
            got = None
        if not isinstance(got, dict) or not isinstance(got.get("state"), str):
            state = "unknown"
        elif got.get("path") is not None and is_closed_place(got["path"], ctx):
            state = "unknown"
        else:
            state = got["state"]
        out.append({**link, "state": state})
    return out
