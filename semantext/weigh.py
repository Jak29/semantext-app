"""The weighed touch: `semantext backtest --weighed`. A cue counts only as far as its evidence goes on your own history,
and the threshold is set so that at most a chosen share of your ordinary messages is touched.

Measured out of sample, beside the back-test's own (unweighed) touch:

- **Cues.** A message's cues are exactly what the back-test touches it by: each reading other than the fallback, each
  decision verb, and each word it shares with a rule on the card (four letters or more, not a common word). A
  consistency count compares them with the back-test's own touch on every message.
- **Weights,** fit on the earlier messages only: a cue firing in k_m of n_m misread messages and k_c of n_c clean ones
  weighs ln(c/q), with c = (k_m + 1/2)/(n_m + 1) and q = (k_c + 1/2)/(n_c + 1). A cue seen fewer than three times
  weighs 0. No weight may exceed its ceiling ln(1/q): a cue that fires on a share q of clean messages multiplies the
  odds of a misreading by at most 1/q, and a cue as common in clean messages as in misread ones weighs nothing.
- **Score:** the sum of a message's positive cue weights. Summing assumes the cues are independent within each class,
  which nothing here proves; the held-out score is what tests it.
- **Threshold,** set on held-apart clean messages: the k-th smallest of their n scores, k = ceil((1 - alpha)(n + 1)),
  and a message is touched only when its score is strictly above it. If clean messages are exchangeable, a new one is
  touched with chance at most alpha (ties only make that more cautious). Exchangeability over time is not assumed: the
  held-out count checks it.
- **The decision:** GO when the false-touch ceiling holds, the weighed touch's skill interval excludes 0, and its
  precision beats the unweighed touch's (a paired bootstrap interval above 0); KILL when the ceiling fails, or either
  point is 0 or below; UNDERPOWERED between. Skill alone (coverage minus false-touch) cannot see the gain: dropping a
  cue that is as common in clean messages as in misread ones leaves skill where it was, while each remaining touch
  carries more evidence.

The parts, by time: the test part holds the later half of the misread messages and every message from the first of
them on. Before it, the misread messages and the earlier half of the clean ones fit the weights, and the later half of
the clean ones set the threshold. The card holds the rules learned before the test part (rules with no date are kept,
as with `--split`); a second report scores the whole live card, marked in-sample.

Aggregates only: counts, rates and intervals. No message text is reported, and nothing is written.
"""
from __future__ import annotations

import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from .backtest import FALLBACK, classify, matched_null, newcombe, touch, wilson
from .mine import units
from .store import Refused, Store, provenance_of

SUPPORT = 3          # a cue seen fewer times than this, in the fit part, weighs 0
WORD = re.compile(r"[a-z']+")


# ---- cues -----------------------------------------------------------------------------------------------------------
def rule_words(entries) -> set[str]:
    return {w for e in entries for w in WORD.findall(str(e.get("statement", "")).lower()) if len(w) >= 4}


def cues(store: Store, name: str, text: str, entries: list, words: set[str] | None = None) -> set[str]:
    """The cues the back-test touches a message by: readings (not the fallback), decision verbs, and the message's words
    shared with a rule on the card."""
    text = (text or "").strip()
    r = store.read(name, text, dry=True, entries=entries)
    out = {f"reading:{x['rule']}" for x in r["readings"] if x["rule"] != FALLBACK}
    out |= {f"decision:{v.lower()}" for v in store.MATERIAL.findall(text)}
    said = {w for w in WORD.findall(text.lower()) if len(w) >= 4 and w not in store.COMMON}
    out |= {f"word:{w}" for w in said & (rule_words(store.live(entries)) if words is None else words)}
    return out


def agrees(store: Store, name: str, text: str, entries: list, found: set[str]) -> bool:
    """Whether these cues touch a message exactly when the back-test's own touch does."""
    return bool(found) == bool(touch(store, name, text, entries))


# ---- weights, threshold and touch -----------------------------------------------------------------------------------
def fit_weights(misread: list[set], clean: list[set]) -> dict[str, dict]:
    """Each cue's evidence from the fit part: its counts, weight ln(c/q), and ceiling ln(1/q)."""
    n_m, n_c = len(misread), len(clean)
    if not n_m or not n_c:
        raise Refused("the fit part needs misread and clean messages")
    out = {}
    for x in sorted({x for s in misread + clean for x in s}):
        k_m = sum(1 for s in misread if x in s)
        k_c = sum(1 for s in clean if x in s)
        c, q = (k_m + 0.5) / (n_m + 1), (k_c + 0.5) / (n_c + 1)
        w = math.log(c / q) if k_m + k_c >= SUPPORT else 0.0
        out[x] = {"k_misread": k_m, "k_clean": k_c, "weight": w, "ceiling": math.log(1 / q)}
    check_ceilings(out)
    return out


def check_ceilings(weights: dict[str, dict]) -> None:
    """No cue may weigh more than ln(1/q): the evidence a cue carries is capped by how often it fires on clean
    messages."""
    for x, v in weights.items():
        if v["weight"] > v["ceiling"] + 1e-12:
            raise Refused(f"a cue weighs {v['weight']:.3f}, above its ceiling {v['ceiling']:.3f}: {x.split(':')[0]}")


def score(found: set[str], weights: dict[str, dict]) -> float:
    return sum(max(weights[x]["weight"], 0.0) for x in found if x in weights)


def threshold(scores: list[float], alpha: float) -> float:
    """The k-th smallest calibration score, k = ceil((1 - alpha)(n + 1)); infinite when k > n."""
    n = len(scores)
    k = math.ceil((1 - alpha) * (n + 1) - 1e-9)
    return math.inf if k > n or n == 0 else sorted(scores)[k - 1]


def over(s: float, t: float) -> bool:
    """Touched only when strictly above the threshold: with ties, a non-strict test could touch every message."""
    return s > t


# ---- the parts --------------------------------------------------------------------------------------------------------
def _when(u: dict) -> datetime:
    t = datetime.fromisoformat(str(u["at"]).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def split(us: list[dict]) -> dict:
    """Order the scored messages by time and cut them: the test part from the first of the later half of the misread
    messages on; before it, fit (all misread, the earlier half of the clean) and calibration (the later half)."""
    scored = [(i, u) for i, u in enumerate(us) if u.get("at") and classify(u) != "corrections"]
    scored.sort(key=lambda p: (_when(p[1]), p[0]))
    order = [u for _, u in scored]
    mis = [i for i, u in enumerate(order) if classify(u) == "misread"]
    if len(mis) < 4:
        raise Refused(f"{len(mis)} dated misread messages: at least 4 are needed to split")
    cut = mis[len(mis) // 2]
    before, test = order[:cut], order[cut:]
    clean = [u for u in before if classify(u) == "clean"]
    half = (len(clean) + 1) // 2
    return {"fit_misread": [u for u in before if classify(u) == "misread"], "fit_clean": clean[:half],
            "calib_clean": clean[half:], "test": test, "test_from": _when(order[cut])}


def card_before(store: Store, name: str, t: datetime) -> tuple[list, dict]:
    """The live rules learned before the test part; rules with no date are kept."""
    live = store.live(store.load(name).get("entries"))
    day = t.date().isoformat()
    kept = [e for e in live if not (str(provenance_of(e).get("when") or "")[:10] >= day
                                    and provenance_of(e).get("when"))]
    undated = sum(1 for e in kept if not provenance_of(e).get("when"))
    return kept, {"on_card": len(kept), "left_off": len(live) - len(kept), "undated_kept": undated}


# ---- one card, measured -----------------------------------------------------------------------------------------------
def measure_card(store: Store, name: str, parts: dict, entries: list, alpha: float, seed: int, boot: int) -> dict:
    words = rule_words(store.live(entries))
    found, disagree = {}, 0
    for kind in ("fit_misread", "fit_clean", "calib_clean", "test"):
        found[kind] = []
        for u in parts[kind]:
            f = cues(store, name, u["text"], entries, words)
            disagree += not agrees(store, name, u["text"], entries, f)
            found[kind].append(f)
    weights = fit_weights(found["fit_misread"], found["fit_clean"])
    t = threshold([score(f, weights) for f in found["calib_clean"]], alpha)
    rows = [(classify(u), bool(f), over(score(f, weights), t)) for u, f in zip(parts["test"], found["test"])]
    mis = [r for r in rows if r[0] == "misread"]
    cln = [r for r in rows if r[0] == "clean"]

    def block(i):
        km, kc = sum(r[i] for r in mis), sum(r[i] for r in cln)
        out = {"coverage": wilson(km, len(mis)), "false_touch": wilson(kc, len(cln)),
               "skill": newcombe(km, len(mis), kc, len(cln)), "precision": wilson(km, km + kc),
               "touched": {"misread": km, "clean": kc}}
        # The weight of one touch, ln(coverage / false-touch), and its ceiling ln(1 / false-touch): reported, not tested.
        if km and kc:
            out["weight_of_a_touch"] = round(math.log((km / len(mis)) / (kc / len(cln))), 4)
            out["its_ceiling"] = round(math.log(len(cln) / kc), 4)
        return out
    weighed, unweighed = block(2), block(1)
    ft = weighed["false_touch"]
    weighed["ceiling"] = {"alpha": alpha, "holds": ft["lo"] is not None and ft["lo"] <= alpha}
    weighed["skill_shown"] = weighed["skill"]["lo"] is not None and weighed["skill"]["lo"] > 0
    return {"rules": len(entries), "threshold": None if math.isinf(t) else round(t, 6),
            "calibration_n": len(found["calib_clean"]), "consistency": {"disagreements": disagree},
            "cues": {"fit": len(weights), "positive": sum(1 for v in weights.values() if v["weight"] > 0),
                     "below_support": sum(1 for v in weights.values() if v["k_misread"] + v["k_clean"] < SUPPORT)},
            "weighed": weighed, "unweighed": unweighed,
            "precision_gain": paired_precision_gain(mis, cln, seed, boot), "_weights": weights}


def _precision(rows: list, i: int) -> float:
    """The share of touched messages that were misread; 0 when nothing is touched (the cautious value)."""
    tp = sum(1 for r in rows if r[i] and r[0] == "misread")
    fp = sum(1 for r in rows if r[i] and r[0] == "clean")
    return tp / (tp + fp) if tp + fp else 0.0


def paired_precision_gain(mis: list, cln: list, seed: int, boot: int) -> dict:
    """Precision weighed minus precision unweighed on the same messages, with a bootstrap 95% interval that resamples
    the misread and the clean messages apart (so the share of misread messages stays the observed one)."""
    if not mis or not cln:
        return {"value": None, "lo": None, "hi": None, "boot": 0}
    rng = random.Random(seed)

    def gain(m, c):
        return _precision(m + c, 2) - _precision(m + c, 1)
    vals = sorted(gain(rng.choices(mis, k=len(mis)), rng.choices(cln, k=len(cln))) for _ in range(boot))
    lo, hi = vals[int(0.025 * (boot - 1))], vals[int(math.ceil(0.975 * (boot - 1)))]
    return {"value": round(gain(mis, cln), 4), "lo": round(lo, 4), "hi": round(hi, 4), "boot": boot, "seed": seed}


def verdict(card: dict) -> str:
    """GO, UNDERPOWERED or KILL. KILL if the ceiling fails on the held-out messages, or the weighed touch shows no sign
    of skill (its point is 0 or below), or no sign of a precision gain. GO if both intervals exclude 0. Otherwise
    UNDERPOWERED."""
    w, g = card["weighed"], card["precision_gain"]
    if not w["ceiling"]["holds"] or (w["skill"]["value"] or 0) <= 0 or (g["value"] or 0) <= 0:
        return "KILL"
    return "GO" if w["skill_shown"] and g["lo"] is not None and g["lo"] > 0 else "UNDERPOWERED"


# ---- the whole measurement ---------------------------------------------------------------------------------------------
def measure(store: Store, name: str, files, alpha: float = 0.10, seed: int = 13, boot: int = 10_000,
            ledger: bool = False) -> dict:
    if not 0 < alpha < 1:
        raise Refused("the ceiling is a share between 0 and 1")
    us = [u for f in files for u in units(Path(f))]
    parts = split(us)
    entries, card_info = card_before(store, name, parts["test_from"])
    live = store.live(store.load(name).get("entries"))
    count = {k: (len(v) if isinstance(v, list) else None) for k, v in parts.items() if k != "test_from"}
    count["test_misread"] = sum(1 for u in parts["test"] if classify(u) == "misread")
    count["test_clean"] = sum(1 for u in parts["test"] if classify(u) == "clean")
    report = {"env": name, "alpha": alpha, "support": SUPPORT, "parts": count, "card_rules": card_info,
              "undated_left_out": sum(1 for u in us if not u.get("at") and classify(u) != "corrections")}
    cards = {"card": entries, "nulls_base": [], "nulls_matched": matched_null(store, entries), "card_all_in_sample": live}
    for key, es in cards.items():
        m = measure_card(store, name, parts, es, alpha, seed, boot)
        w = m.pop("_weights")
        if ledger and key == "card":
            m["ledger"] = {x: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}
                           for x, d in sorted(w.items(), key=lambda kv: -kv[1]["weight"])}
        report[key] = m
    report["card"]["verdict"] = verdict(report["card"])
    return report
