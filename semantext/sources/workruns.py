"""The run-record reader for work clauses (PM-DESIGN r4, slice 2b): a run-record clause read through runs.py, the run
reader the Rules place uses, never a copy of it.

A clause names a rule by id. Its words come from the rule cards (rules.load, the "cards" folder), since a record is
judged against the rule's words now; its records from runs.read (the "run_records" folders). The newest record for the
rule, of any checker, decides, and runs.verdict judges it with the clause's own age bound (fresh_days): both arms run
and passed, the outcome not failed or not proved, the rule's words and every subject's bytes as they were, within the
bound. The fact names who ran it ("by"), so the judge refuses the item's own builder's evidence, who built the checker
("built_by", optional; while a record does not say, the clause is unknown, never met), and the record's file.
No folder, no card, a rule no card holds, a rule two environments hold in different words: unknown, with the reason,
never met. Read once per page build, lazily.
"""
from __future__ import annotations

from datetime import datetime, timezone


AMBIGUOUS = object()   # a rule id two environments hold in different words (G6, finding 22)


def _words(environments) -> dict:
    """rule id -> its words across every environment; AMBIGUOUS for an id held in different words by two of them (the
    rule cards check duplicate ids only within one card)."""
    words = {}
    for e in environments:
        for r in e.get("rules") or []:
            rid, said = r["id"], r["words"]
            words[rid] = said if words.get(rid, said) == said else AMBIGUOUS
    return words


class RunRecords:
    def __init__(self, cfg: dict, now: datetime | None = None):
        self.cfg, self.now = cfg, now or datetime.now(timezone.utc)
        self._read = None
        self.problems: list[dict] = []

    def _load(self):
        if self._read is None:
            from . import rules, runs
            words, why = {}, None
            if not self.cfg.get("run_records"):
                why = "your sources file names no run-record folder (run_records)"
            elif not self.cfg.get("cards"):
                why = "your sources file names no rule cards (cards), so no rule's words can be read"
            else:
                try:
                    got = rules.load(self.cfg, self.now)
                    words = _words(got.get("environments") or [])
                    ran = runs.read(self.cfg, self.now)
                    self._records = ran.get("records") or {}
                except Exception as e:  # noqa: BLE001  a reader that stops leaves every such clause unknown
                    why = f"the run records could not be read ({type(e).__name__})"
            self._read = (words, why)
        return self._read

    def __call__(self, clause: dict):
        from . import runs
        words, why = self._load()
        if why:
            return {"unknown": why}
        rule = clause["rule"]
        if rule not in words:
            return {"unknown": f"no rule card holds the rule {rule}"}
        if words[rule] is AMBIGUOUS:
            return {"unknown": f"more than one environment holds the rule {rule}, in other words, so which words its "
                               f"records were made against cannot be told"}
        recs = self._records.get(rule) or []
        if not recs:
            return None
        rec = max(recs, key=lambda r: r["when"])
        v = runs.verdict(rec, words[rule], self.now, clause["fresh_days"])
        # checker_by: who built the checker, when the record says (built_by); absent, the checker rule stays unknown
        return {"run": v, "producer": rec.get("by"), "checker_by": rec.get("built_by"), "path": rec.get("source")}
