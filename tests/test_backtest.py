"""The back-test: coverage of the messages the user corrected, against the touch rate on the ones they did not, beside
two null cards. Every transcript here is made up."""
import json
import socket

from semantext.backtest import backtest, newcombe, wilson
from semantext.cli import main

RULE = "Use the staging database for every experiment."
LATE = "Check each invoice total twice."


def user(text, at):
    return {"type": "user", "uuid": f"u-{at}-{len(text)}", "timestamp": at, "turnOrigin": "human",
            "message": {"role": "user", "content": text}}


def reply(text="Done."):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def history(path, misread, clean, day="2026-10-15"):
    """Each misread message, then a reply, the user's correction and a reply; then a clean message and a reply."""
    recs = []
    for i, (m, c) in enumerate(zip(misread, clean)):
        at = f"{day}T{10 + i:02d}:00:00Z"
        recs += [user(m, at), reply(), user("No, I meant the other one.", at), reply(), user(c, at), reply()]
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return path


MISREAD = [f"Run the migration on the staging database number {i}." for i in range(8)]
CLEAN = [f"Tidy the layout of page {i}." for i in range(8)]


def test_the_fallback_never_counts(store, tmp_path):
    r = backtest(store, "default", [history(tmp_path / "t.jsonl", MISREAD, CLEAN)])
    assert r["units"] == {"misread": 8, "clean": 8, "corrections": 8}
    assert r["coverage"]["p"] == 0 and r["false_touch"]["p"] == 0       # plain instructions, no rule of its own
    assert r["nulls"]["base"]["coverage"]["p"] == 0


def test_a_rule_that_fits_scores_and_the_nulls_do_not(store, tmp_path):
    store.learn("default", RULE)
    r = backtest(store, "default", [history(tmp_path / "t.jsonl", MISREAD, CLEAN)])
    assert (r["coverage"]["p"], r["false_touch"]["p"]) == (1.0, 0.0)
    assert r["skill"]["lo"] > 0
    assert r["skill"]["value"] - r["nulls"]["matched"]["skill"]["value"] >= 0.5
    assert (r["nulls"]["matched"]["rules"], r["nulls"]["matched"]["drawn_from"]) == (1, "suggestion packs")
    assert r["split"]["in_sample"] is True                              # marked, with no split


def test_a_card_that_touches_everything_has_no_skill(store, tmp_path):
    store.learn("default", "Staging database migration number layout page tidy.")
    r = backtest(store, "default", [history(tmp_path / "t.jsonl", MISREAD, CLEAN)])
    assert (r["coverage"]["p"], r["false_touch"]["p"]) == (1.0, 1.0)
    assert abs(r["skill"]["value"]) < 0.2 and r["skill"]["lo"] <= 0 <= r["skill"]["hi"]


def test_a_rule_learned_after_the_split_is_left_off(store, tmp_path):
    store.learn("default", RULE)
    late = store.learn("default", LATE)
    d = store.load("default")
    for e in d["entries"]:
        if e["id"] == late:
            e["provenance"]["when"] = "2026-10-20T09:00:00+00:00"       # taught after the corrections
    store.save("default", d)
    misread = MISREAD[:4] + [f"Total the invoice for client {i}." for i in range(4)]
    t = history(tmp_path / "t.jsonl", misread, CLEAN, day="2026-10-18")
    assert backtest(store, "default", [t])["coverage"]["p"] == 1.0     # in-sample: both rules
    r = backtest(store, "default", [t], split="2026-10-17")
    assert r["split"] == {"date": "2026-10-17", "in_sample": False, "rules_left_off": 1, "undated_left_out": 0}
    assert r["coverage"]["p"] == 0.5                                    # only the rule taught before
    assert backtest(store, "default", [t], split="2026-10-19")["units"]["misread"] == 0   # nothing after it


def test_cases_score_the_right_rule_apart_from_any_rule(store, tmp_path):
    rid = store.learn("default", RULE)
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps(c) for c in [
        {"message": "Migrate the staging database tonight.", "rules": [rid], "grounded": "EXPLICIT"},
        {"message": "Maybe we try the staging database.", "rules": ["base.time-kept-verbatim"], "grounded": "INFERRED"},
        {"message": "Paint the fence."},
    ]), encoding="utf-8")
    r = backtest(store, "default", cases=cases)
    assert r["cases"]["n"] == 3 and r["cases"]["with_rules"] == 2
    assert r["cases"]["touched"]["p"] == round(2 / 3, 4) and r["cases"]["hit"]["p"] == 0.5
    assert r["cases"]["grounded"] == {"EXPLICIT": 1, "INFERRED": 1, "unstated": 1}


def test_the_finder_is_measured(store, tmp_path):
    f = tmp_path / "finder.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in [
        {"text": "No, I meant the blue one.", "correction": True},
        {"text": "That's not what I asked.", "correction": True},
        {"text": "Hmm, the other file please.", "correction": True},        # a correction the list misses
        {"text": "No problem.", "correction": False},
        {"text": "Why did you pick that? Just curious.", "correction": False},   # a question it flags
    ]), encoding="utf-8")
    assert backtest(store, "default", finder=f)["finder"] == {"n": 5, "precision": round(2 / 3, 4),
                                                              "recall": round(2 / 3, 4)}


def test_it_writes_nothing_and_opens_no_connection(capsys, home, tmp_path, monkeypatch):
    t = history(tmp_path / "t.jsonl", MISREAD, CLEAN)
    main(["init"])
    capsys.readouterr()
    before = sorted((p.relative_to(home), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file())

    def refuse(*a, **k):
        raise AssertionError("the back-test opened a connection")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert main(["backtest", str(t), "--json", "--show"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert len(r["silent"]) == 8 and r["silent"][0]["correction"] == "No, I meant the other one."
    assert sorted((p.relative_to(home), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()) == before


def test_the_intervals():
    assert wilson(0, 0) == {"p": None, "lo": None, "hi": None}
    w = wilson(8, 8)
    assert w["p"] == 1.0 and 0.6 < w["lo"] < 0.7 and w["hi"] == 1.0
    d = newcombe(8, 8, 0, 8)
    assert d["value"] == 1.0 and 0.5 < d["lo"] < 1.0 and d["hi"] == 1.0
