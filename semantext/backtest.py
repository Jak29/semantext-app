"""The back-test: does the card speak to the misreadings the user actually had?

Each of the user's own messages in their transcripts is a unit (see mine.py). One the user then corrected is MISREAD;
a correction that was not itself corrected is a CORRECTION, counted apart, since its own wording ("no, ...") always
trips a reading; every other message is CLEAN. The card "touches" a message when its reading flags at least one rule
for it, never counting the plain fallback ("an instruction"). The score is the difference:

    coverage    = the share of misread messages the card touches
    false-touch = the share of clean messages it touches
    skill       = coverage minus false-touch

so a card that touches everything scores no skill. Each comes with a 95% interval, and beside the card, two null cards
score the same messages: the base rules alone, and as many rules as the card has, drawn from the suggestion packs (a
card of the same size, with other people's words). A card that scores like the drawn one is matching words, not fit.

Touched is not prevented: it says a rule bears on the message, not that an AI reading the card would have read it
right. That needs a model reading the card, which this does not call. Nothing leaves the machine, and nothing is
written.

Rules learned from the very corrections they are scored on touch them by construction, so a score without `--split`
is marked in-sample. With `--split DATE`, rules learned on or after DATE are left off the card, and only messages from
DATE on are scored.
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

from . import jsonread
from .inbox import SECRET, token_like
from .mine import is_correction, units
from .store import Refused, Store, provenance_of

FALLBACK = "base.show-your-work"
SEED = 13
Z = 1.959964


def wilson(k: int, n: int) -> dict:
    if not n:
        return {"p": None, "lo": None, "hi": None}
    p = k / n
    d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return {"p": round(p, 4), "lo": round(max(0.0, c - h), 4), "hi": round(min(1.0, c + h), 4)}


def newcombe(k1: int, n1: int, k2: int, n2: int) -> dict:
    """The difference of two shares, with Newcombe's hybrid score interval (from the two Wilson intervals)."""
    if not n1 or not n2:
        return {"value": None, "lo": None, "hi": None}
    a, b = wilson(k1, n1), wilson(k2, n2)
    p1, p2 = k1 / n1, k2 / n2
    d = p1 - p2
    lo = d - math.sqrt((p1 - a["lo"]) ** 2 + (b["hi"] - p2) ** 2)
    hi = d + math.sqrt((a["hi"] - p1) ** 2 + (p2 - b["lo"]) ** 2)
    return {"value": round(d, 4), "lo": round(lo, 4), "hi": round(hi, 4)}


def touch(store: Store, name: str, text: str, entries: list) -> set[str]:
    """The rules the card's reading flags for a message: never the plain fallback."""
    r = store.read(name, text, dry=True, entries=entries)
    return ({x["rule"] for x in r["readings"]} - {FALLBACK}) | set(r["touched"]) | {d["rule"] for d in r["decisions"]}


def classify(u: dict) -> str:
    return "misread" if u.get("misread") else "corrections" if u.get("corrects") else "clean"


def score(store: Store, name: str, us: list[dict], entries: list) -> dict:
    hits = {"misread": [0, 0, 0], "clean": [0, 0, 0]}          # touched, scored, rules flagged
    for u in us:
        cls = classify(u)
        if cls == "corrections":
            continue
        t = touch(store, name, u["text"], entries)
        h = hits[cls]
        h[0] += bool(t)
        h[1] += 1
        h[2] += len(t)
    (km, nm, rm), (kc, nc, rc) = hits["misread"], hits["clean"]
    return {"coverage": wilson(km, nm), "false_touch": wilson(kc, nc), "skill": newcombe(km, nm, kc, nc),
            "rules_per_message": {"misread": round(rm / nm, 3) if nm else None,
                                  "clean": round(rc / nc, 3) if nc else None}}


def _when(e: dict) -> str:
    return str(provenance_of(e).get("when") or "")


def matched_null(store: Store, entries: list) -> list:
    """As many rules as the card has, drawn from the suggestion packs with a fixed seed, leaving out any the card
    already holds: a card of the same size, with other people's words."""
    have = {" ".join(str(e.get("statement", "")).lower().split()) for e in entries}
    pool = [e for p in store.packs() for e in (p.get("entries") or [])
            if isinstance(e, dict) and e.get("statement")
            and " ".join(str(e["statement"]).lower().split()) not in have]
    return random.Random(SEED).sample(pool, min(len(entries), len(pool)))


def read_jsonl(path) -> list[dict]:
    out = []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            x = jsonread.loads(line)
        except ValueError:
            raise Refused(f"{path}, line {n}: not valid JSON")
        if not isinstance(x, dict):
            raise Refused(f"{path}, line {n}: each line must be an object")
        out.append(x)
    return out


def backtest(store: Store, name: str, files=(), cases=None, finder=None, split: str | None = None,
             show: bool = False) -> dict:
    entries = store.live(store.load(name).get("entries"))
    report: dict = {"env": name, "transcripts": len(files)}
    if split:
        kept = [e for e in entries if not (_when(e) and _when(e)[:10] >= split)]
        report["split"] = {"date": split, "in_sample": False, "rules_left_off": len(entries) - len(kept)}
        entries = kept
    else:
        report["split"] = {"date": None, "in_sample": True}
    us = [u for f in files for u in units(Path(f))]
    if split:
        dated = [u for u in us if u.get("at")]
        report["split"]["undated_left_out"] = len(us) - len(dated)
        us = [u for u in dated if str(u["at"])[:10] >= split]
    classes = [classify(u) for u in us]
    report["units"] = {c: classes.count(c) for c in ("misread", "clean", "corrections")}
    if files:
        report.update(score(store, name, us, entries))
        drawn = matched_null(store, entries)
        report["nulls"] = {"base": score(store, name, us, []),
                           "matched": {**score(store, name, us, drawn), "rules": len(drawn),
                                       "drawn_from": "suggestion packs", "seed": SEED}}
        report["card_rules"] = len(entries)
        if show:
            silent = [u for u in us if classify(u) == "misread" and not touch(store, name, u["text"], entries)]
            # A report can be pasted anywhere, and pasting it is leaving the machine: a text that looks like it holds a
            # key, by a known shape or a long run of mixed letters and digits, is held back, and counted.
            held = [u for u in silent if any(SECRET.search(t) or token_like(t)
                                             for t in (u["text"], u.get("correction") or ""))]
            report["silent"] = [{"message": u["text"][:300], "correction": u.get("correction", "")[:300],
                                 "at": u.get("at")} for u in silent if u not in held]
            report["silent_held_back"] = len(held)
    if cases:
        cs = read_jsonl(cases)
        if not all(isinstance(c.get("message"), str) and c["message"].strip() for c in cs):
            raise Refused("every case needs its message: the words that were misread")
        touched = [touch(store, name, c["message"], entries) for c in cs]
        ruled = [(t, set(c.get("rules") or [])) for t, c in zip(touched, cs) if c.get("rules")]
        grounded = {}
        for c in cs:
            g = str(c.get("grounded") or "unstated").upper() if c.get("grounded") else "unstated"
            grounded[g] = grounded.get(g, 0) + 1
        report["cases"] = {"n": len(cs), "touched": wilson(sum(bool(t) for t in touched), len(cs)),
                           "hit": wilson(sum(bool(t & r) for t, r in ruled), len(ruled)), "with_rules": len(ruled),
                           "grounded": grounded}
    if finder:
        fs = read_jsonl(finder)
        tp = sum(1 for x in fs if x.get("correction") and is_correction(str(x.get("text", ""))))
        fp = sum(1 for x in fs if not x.get("correction") and is_correction(str(x.get("text", ""))))
        fn = sum(1 for x in fs if x.get("correction") and not is_correction(str(x.get("text", ""))))
        report["finder"] = {"n": len(fs), "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                            "recall": round(tp / (tp + fn), 4) if tp + fn else None}
    return report
