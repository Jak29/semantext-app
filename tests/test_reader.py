"""The optional model reading, with fake readers only: no real model is ever called here. Each reader records every
prompt it is given, so what it saw can be checked."""
import json
import re

import pytest

from semantext.reader import (EndpointReader, build_prompt, mcnemar_exact, min_net_gain, model_backtest, paired_diff,
                              parse_reply)
from semantext.store import Refused

KEY = "sk-" + "q7w8e9r0" * 3                 # built at run time: no key-shaped literal in the source
RULE = "Use the staging database for every experiment."


class Fake:
    def __init__(self, fn, name="fake", family="fakefam"):
        self.fn, self.name, self.family, self.version, self.prompts = fn, name, family, "test", []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.fn(prompt)


def ids_in(prompt):
    block = prompt.split("<<<RULES", 1)[1].split("RULES>>>", 1)[0] if "<<<RULES" in prompt else ""
    return re.findall(r"^- ([^:\s]+):", block, re.M)


def message_of(prompt):
    return prompt.split("<<<THE MESSAGE\n", 1)[1].split("\nTHE MESSAGE>>>", 1)[0]


def reply(rules, reading):
    return json.dumps({"rules": rules, "reading": reading})


def judge(name, family):
    """Says 'expected' when the reading to judge equals the expected reading, word for word."""
    def fn(prompt):
        got = prompt.split("<<<THE READING TO JUDGE\n", 1)[1].split("\nTHE READING TO JUDGE>>>", 1)[0]
        want = prompt.split("<<<EXPECTED\n", 1)[1].split("\nEXPECTED>>>", 1)[0]
        return "expected" if got == want else "forbidden"
    return Fake(fn, name, family)


def cases_file(tmp_path, cases):
    p = tmp_path / "cases.jsonl"
    p.write_text("\n".join(json.dumps(c) for c in cases), encoding="utf-8")
    return p


def make_cases(rid):
    return [{"message": f"Migrate the staging database run {i}.", "rules": [rid], "context_before": "Shall I?",
             "expected_reading": f"run {i} on staging", "forbidden_reading": f"run {i} on production",
             "correction": f"CORRECTION-{i}"} for i in range(6)] + \
           [{"message": f"Tidy page {i}.", "rules": ["base.show-your-work"], "expected_reading": f"tidy {i}",
             "forbidden_reading": f"delete {i}"} for i in range(4)]


# ---- arm 4 and the instrument's arithmetic -------------------------------------------------------------------------
def test_the_paired_test_gives_the_known_answers():
    assert mcnemar_exact(10, 0) == pytest.approx(2 / 2 ** 10)
    assert mcnemar_exact(5, 5) == 1.0 and mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(9, 1) == pytest.approx(2 * (1 + 10) / 2 ** 10)
    d = paired_diff(10, 10, 0, 10)
    assert d["value"] == pytest.approx(1 / 3, abs=1e-4) and d["lo"] > 0
    assert paired_diff(5, 3, 3, 5)["value"] == 0 and paired_diff(5, 3, 3, 5)["lo"] < 0 < paired_diff(5, 3, 3, 5)["hi"]


def test_the_power_statement_shrinks_with_more_pairs():
    small, large = min_net_gain(30), min_net_gain(200)
    assert small is not None and 0.2 <= small <= 0.5 and large < small


# ---- the parse: strict, data only ------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw, want", [
    (reply(["a", "zz"], "one\ntwo"), (frozenset({"a"}), "one")),           # unknown ids dropped, first line only
    ('Sure! {"rules": ["a"], "reading": "x"}', None),                       # prose around it
    (json.dumps({"rules": ["a"], "reading": "x", "act": "rm -rf"}), None),  # anything more
    (json.dumps({"rules": "a", "reading": "x"}), None),                     # the wrong types
    (json.dumps([1, 2]), None), (None, None),
])
def test_only_ids_the_card_holds_and_one_line_are_taken(raw, want):
    assert parse_reply(raw, {"a", "b"}) == want


# ---- arms 1 to 3: the fake readers ------------------------------------------------------------------------------------
def test_a_reader_that_names_every_rule_has_no_skill_over_the_null(store, tmp_path):
    from tests.test_backtest import CLEAN, MISREAD, history
    store.learn("default", RULE)
    every = Fake(lambda p: reply(ids_in(p), "something"))
    r = model_backtest(store, "default", every, files=[history(tmp_path / "t.jsonl", MISREAD, CLEAN)])
    t = r["touched"]
    assert t["coverage"]["p"] == 1.0 and t["false_touch"]["p"] == 1.0 and t["skill"]["value"] == 0
    assert t["skill"]["value"] <= t["nulls"]["matched"]["skill"]["value"]
    shown = {len(ids_in(p)) for p in every.prompts if "<<<RULES" in p}          # the sizes the reader was given
    assert shown == {t["rules"], t["nulls"]["matched"]["rules"]}


def test_a_reader_that_ignores_the_card_shows_no_card_effect(store, tmp_path):
    rid = store.learn("default", RULE)
    deaf = Fake(lambda p: reply([], "the same reading"))
    r = model_backtest(store, "default", deaf, judges=[judge("j1", "fam1"), judge("j2", "fam2")],
                       cases=cases_file(tmp_path, make_cases(rid)))
    assert (r["reading"]["b"], r["reading"]["c"]) == (0, 0) and r["reading"]["diff"]["value"] == 0


def test_an_oracle_reader_scores_high(store, tmp_path):
    rid = store.learn("default", RULE)
    cases = make_cases(rid)
    label = {c["message"]: c for c in cases}
    oracle = Fake(lambda p: reply(label[message_of(p)]["rules"] if "<<<RULES" in p else [],
                                  label[message_of(p)]["expected_reading"]))
    r = model_backtest(store, "default", oracle, judges=[judge("j1", "fam1"), judge("j2", "fam2")],
                       cases=cases_file(tmp_path, cases))
    assert r["cases"]["hit"]["p"] == 1.0 and r["reading"]["a"] == 10 and r["reading"]["disputed"] == 0


def test_a_card_that_helps_shows_in_the_paired_test(store, tmp_path):
    rid = store.learn("default", RULE)
    cases = make_cases(rid)
    label = {c["message"]: c for c in cases}
    helped = Fake(lambda p: reply([rid] if "<<<RULES" in p and "staging" in message_of(p) else [],
                                  label[message_of(p)]["expected_reading"] if "<<<RULES" in p else "a guess"))
    r = model_backtest(store, "default", helped, judges=[judge("j1", "fam1"), judge("j2", "fam2")],
                       cases=cases_file(tmp_path, cases))
    assert (r["reading"]["b"], r["reading"]["c"]) == (10, 0) and r["reading"]["mcnemar_p"] < 0.01
    assert r["reading"]["diff"]["lo"] > 0 and r["noninferiority"]["card_broke"] == 0


def test_corrected_messages_are_read_blind_and_with_the_card_and_judged_on_a_stated_proxy(store, tmp_path):
    from tests.test_backtest import CLEAN, MISREAD, history
    store.learn("default", RULE)
    fixed = Fake(lambda p: reply([], "No, I meant the other one." if "<<<RULES" in p else "a guess"))
    r = model_backtest(store, "default", fixed, judges=[judge("j1", "fam1"), judge("j2", "fam2")],
                       files=[history(tmp_path / "t.jsonl", MISREAD, CLEAN)])
    g = r["reading_corrected"]
    assert (g["n"], g["b"], g["c"]) == (8, 8, 0) and g["mcnemar_p"] < 0.01 and g["grounding"].startswith("proxy")
    assert (g["neither"], g["disputed"], g["informative"]) == (0, 0, True)
    blind = [p for p in fixed.prompts if "<<<RULES" not in p]
    assert len(blind) == 16                                             # one blind call per misread and clean message
    assert not any("No, I meant" in p for p in fixed.prompts)          # the correction reaches the judges only
    shrug = model_backtest(store, "default", fixed, judges=[Fake(lambda p: "neither", "j1", "fam1"),
                                                            Fake(lambda p: "neither", "j2", "fam2")],
                           files=[history(tmp_path / "t.jsonl", MISREAD, CLEAN)])["reading_corrected"]
    assert (shrug["neither"], shrug["informative"]) == (8, False)      # judges who cannot tell: not a result


def test_a_reduced_reading_reads_every_misread_message_and_exactly_the_drawn_clean_ones(store, tmp_path):
    import random

    from semantext.mine import units
    from tests.test_backtest import CLEAN, MISREAD, history
    store.learn("default", RULE)
    path = history(tmp_path / "t.jsonl", MISREAD, CLEAN)
    us = units(path)
    clean = [u["text"] for u in us if not u.get("misread") and not u.get("corrects")]
    misread = [u["text"] for u in us if u.get("misread")]
    want = {clean[j] for j in random.Random(13).sample(range(len(clean)), 3)}
    seen = Fake(lambda p: reply([], "x"))
    r = model_backtest(store, "default", seen, files=[path], clean_sample=3)
    read = [message_of(p) for p in seen.prompts]
    assert {m for m in read if m in clean} == want                              # exactly the drawn clean messages
    assert all(read.count(m) == 3 for m in [*misread, *want])                  # each blind, with the card, the null
    assert (r["clean_sample"]["n"], r["clean_sample"]["of"]) == (3, len(clean))
    with pytest.raises(Refused):
        model_backtest(store, "default", seen, files=[path], clean_sample=len(clean) + 1)


# ---- arms 5 to 9: what the reader sees, and what it never becomes ------------------------------------------------------
def test_each_call_is_one_message_in_one_form_and_sees_nothing_it_must_not(store, tmp_path):
    rid = store.learn("default", RULE)
    cases = make_cases(rid)
    seen = Fake(lambda p: reply([], "x"))
    model_backtest(store, "default", seen, judges=[judge("j1", "fam1"), judge("j2", "fam2")],
                   cases=cases_file(tmp_path, cases))
    assert seen.prompts and all(p.count("<<<THE MESSAGE") == 1 for p in seen.prompts)
    assert sum("<<<RULES" in p for p in seen.prompts) == sum("<<<RULES" not in p for p in seen.prompts)   # paired
    joined = "\n".join(seen.prompts)
    for c in cases:
        assert c["expected_reading"] not in joined and c["forbidden_reading"] not in joined
        assert c.get("correction", "CORRECTION-x") not in joined


def test_the_reader_never_sees_a_secret(store, tmp_path):
    rid = store.learn("default", RULE)
    seen = Fake(lambda p: reply([], "x"))
    r = model_backtest(store, "default", seen, cases=cases_file(tmp_path, [
        {"message": f"deploy with {KEY}", "rules": [rid]},
        {"message": "Tidy page 1.", "context_before": f"the token is {KEY}", "rules": [rid]},
        {"message": "Tidy page 2.", "context_before": "Shall I?", "rules": [rid]}]))
    assert KEY not in "\n".join(seen.prompts) and r["calls"]["secret_skipped"] == 4      # blind and card, twice
    plain = [p for p in seen.prompts if "Tidy page 2." in p]
    assert plain and all("Shall I?" in p for p in plain)                                 # must pass: the rest arrives
    assert build_prompt(None, "m", None).count("<<<") == 1                               # the message, and nothing else


def test_a_models_reading_never_becomes_a_rule_or_a_case(store, tmp_path):
    rid = store.learn("default", RULE)
    cases = cases_file(tmp_path, make_cases(rid))
    rules_before, cases_before = store.source("default"), cases.read_text(encoding="utf-8")
    writer = Fake(lambda p: reply([rid] if "<<<RULES" in p else [], "MODEL-TEXT-SHOULD-STAY-IN-THE-REPORT"))
    r = model_backtest(store, "default", writer, judges=[judge("j1", "fam1"), judge("j2", "fam2")], cases=cases)
    assert store.source("default") == rules_before and cases.read_text(encoding="utf-8") == cases_before
    assert r["kind"] == "MODEL" and r["reader"] == {"name": "fake", "version": "test", "family": "fakefam"}


def test_the_judge_is_never_the_readers_own_family(store, tmp_path):
    reader = Fake(lambda p: reply([], "x"), family="samefam")
    with pytest.raises(Refused):
        model_backtest(store, "default", reader, judges=[judge("j1", "samefam"), judge("j2", "other")],
                       cases=cases_file(tmp_path, [{"message": "m"}]))


def test_removing_the_rule_a_case_needs_drops_only_its_hits(store, tmp_path):
    rid = store.learn("default", RULE)
    other = store.learn("default", "Keep answers brief.")
    cases = [{"message": "Use staging for run 1.", "rules": [rid]}, {"message": "Use staging for run 2.", "rules": [rid]},
             {"message": "Short answer please.", "rules": [other]}]
    needs = {c["message"]: c["rules"][0] for c in cases}
    honest = Fake(lambda p: reply([needs[message_of(p)]] if needs[message_of(p)] in ids_in(p) else [], "x"))
    r = model_backtest(store, "default", honest, cases=cases_file(tmp_path, cases), ablate=True)
    row = next(x for x in r["ablation"] if x["rule"] == rid)
    assert row["needing"] == {"n": 2, "hit_before": 2, "hit_after": 0}
    assert row["others"] == {"n": 1, "hit_before": 1, "hit_after": 1}


# ---- the ablation's second pass, from a registered table -------------------------------------------------------------
def ablation_setup(store, tmp_path):
    import hashlib
    a = store.learn("default", RULE)
    b = store.learn("default", "Keep answers brief.")
    need = {"C1": [a], "C2": [a], "C3": [a, b], "C4": [b], "C5": [b], "C6": [b]}
    cases = [{"id": k, "message": f"message {k}", "rules": v, "expected_reading": f"right {k}",
              "forbidden_reading": f"wrong {k}"} for k, v in need.items()]
    path = cases_file(tmp_path, cases)

    def table(entry_rules, sham, name="table.json"):
        p = tmp_path / name
        p.write_text(json.dumps({"rules": entry_rules, "sham": sham}), encoding="utf-8")
        return p, hashlib.sha256(p.read_bytes()).hexdigest()

    def reads_with(full_only=False):
        """Right only when the rules the case needs are on the card; with full_only, only when nothing is removed."""
        def fn(prompt):
            cid = message_of(prompt).split()[-1]
            on, needed = set(ids_in(prompt)), set(need[cid])
            right = "<<<RULES" in prompt and ({a, b} <= on if full_only else needed <= on)
            return reply(sorted(needed & on), f"right {cid}" if right else "a guess")
        return fn

    return a, b, path, table, reads_with


def test_the_ablation_holds_when_only_the_needing_cases_fall(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", honest, judges=judges, cases=cases)
    assert base["per_case"]["C1"]["card_verdict"] == "expected"
    t, sha = table([{"rule": a, "needing": ["C1", "C2", "C3"], "others": ["C4", "C5"]}], ["C4", "C6"])
    r = ablation_pass(store, "default", honest, judges, cases, t, sha, base)
    assert (r["tally"]["needing"]["fell"], r["tally"]["needing"]["right_before"]) == (3, 3)
    assert (r["tally"]["others"]["fell"], r["tally"]["sham"]["fell"]) == (0, 0)
    assert r["diff"]["lo"] > 0 and r["holds"] is True and r["kind"] == "MODEL"
    c3 = next(x for x in r["rows"] if x["case"] == "C3" and x["kind"] == "needing")
    assert (c3["hit_before"], c3["hit_after"]) == (True, True)            # its other rule is still read


def test_a_reader_that_falls_whatever_is_removed_does_not_hold(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    fragile = Fake(reads_with(full_only=True))
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", fragile, judges=judges, cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1", "C2", "C3"], "others": ["C4", "C5"]}], ["C4", "C6"])
    r = ablation_pass(store, "default", fragile, judges, cases, t, sha, base)
    assert r["tally"]["others"]["fell"] == 2 and r["holds"] is False         # it reacts to the card, not the rule


def test_the_effect_needs_the_others_to_fall_no_more_than_the_sham():
    from semantext.reader import effect_holds

    def tally(n_fell, n, o_fell, o, s_fell, s):
        return {"needing": {"fell": n_fell, "right_before": n}, "others": {"fell": o_fell, "right_before": o},
                "sham": {"fell": s_fell, "right_before": s}}
    assert effect_holds(tally(20, 20, 0, 10, 0, 10))[2] is True                # the rule's own effect
    rate, diff, holds = effect_holds(tally(20, 20, 6, 10, 0, 10))
    assert diff["lo"] > 0 and holds is False                                   # others fall beyond the sham's noise
    assert effect_holds(tally(5, 10, 4, 10, 0, 10))[2] is False                # no difference from the others


def test_the_second_pass_reads_only_the_registered_table(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", honest, judges=judges, cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1"], "others": ["C4"]}], [])
    with pytest.raises(Refused):
        ablation_pass(store, "default", honest, judges, cases, t, "0" * 64, base)      # not the registered bytes
    t2, sha2 = table([{"rule": a, "needing": ["C1"], "others": ["C3"]}], [], "t2.json")  # C3 names the rule
    with pytest.raises(Refused):
        ablation_pass(store, "default", honest, judges, cases, t2, sha2, base)
    t3, sha3 = table([{"rule": b, "needing": ["C4"], "others": ["C1", "C2", "C1"]}], [], "t3.json")  # pool of 2
    with pytest.raises(Refused):
        ablation_pass(store, "default", honest, judges, cases, t3, sha3, base)
    other_model = {**base, "reader": {"name": "another-model"}}
    with pytest.raises(Refused):
        ablation_pass(store, "default", honest, judges, cases, t, sha, other_model)
    assert ablation_pass(store, "default", honest, judges, cases, t, sha, base)["calls"]["made"] == 2   # must pass


def test_the_baseline_must_be_this_models_version_and_decoding(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    honest.decoding = {"temperature": 0, "think": False}
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", honest, judges=judges, cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1"], "others": ["C4"]}], [])
    for changed in ({"version": "another-build"}, {"decoding": {"temperature": 0.7, "think": False}}):
        with pytest.raises(Refused):
            ablation_pass(store, "default", honest, judges, cases, t, sha,
                          {**base, "reader": {**base["reader"], **changed}})
    saved = json.loads(json.dumps(base))                       # a first pass kept in a file, as a real run keeps it
    assert ablation_pass(store, "default", honest, judges, cases, t, sha, saved)["calls"]["made"] == 2


def test_the_second_pass_refuses_a_judge_of_the_readers_family(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    base = model_backtest(store, "default", honest, judges=[judge("j1", "fam1"), judge("j2", "fam2")], cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1"], "others": ["C4"]}], [])
    with pytest.raises(Refused):
        ablation_pass(store, "default", honest, [judge("j1", "fakefam"), judge("j2", "fam2")], cases, t, sha, base)


def test_a_case_with_no_first_pass_verdict_is_counted_apart_from_a_dispute(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", honest, judges=judges, cases=cases)
    del base["per_case"]["C1"]                                 # its first pass left no verdict
    t, sha = table([{"rule": a, "needing": ["C1", "C2", "C3"], "others": ["C4", "C5"]}], ["C4", "C6"])
    r = ablation_pass(store, "default", honest, judges, cases, t, sha, base)
    assert (r["tally"]["needing"]["no_baseline"], r["tally"]["needing"]["disputed"]) == (1, 0)
    assert r["tally"]["needing"]["right_before"] == 2


def test_a_table_naming_a_case_the_file_lacks_is_refused_before_any_read(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", honest, judges=judges, cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1", "C9"], "others": ["C4"]}], ["C8"])
    n = len(honest.prompts)
    with pytest.raises(Refused, match="C8, C9"):
        ablation_pass(store, "default", honest, judges, cases, t, sha, base)
    assert len(honest.prompts) == n


def test_both_passes_record_the_cases_files_sha256(store, tmp_path):
    import hashlib
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    honest = Fake(reads_with())
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", honest, judges=judges, cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1"], "others": ["C4"]}], [])
    want = hashlib.sha256(cases.read_bytes()).hexdigest()
    assert base["cases_sha256"] == want
    assert ablation_pass(store, "default", honest, judges, cases, t, sha, base)["cases_sha256"] == want


def test_hits_lost_are_counted_per_kind(store, tmp_path):
    from semantext.reader import ablation_pass
    a, b, cases, table, reads_with = ablation_setup(store, tmp_path)
    full = reads_with()

    def silent_when_cut(prompt):                               # names no rule once any rule is off the card
        if "<<<RULES" in prompt and not {a, b} <= set(ids_in(prompt)):
            return reply([], "a guess")
        return full(prompt)
    reader = Fake(silent_when_cut)
    judges = [judge("j1", "fam1"), judge("j2", "fam2")]
    base = model_backtest(store, "default", reader, judges=judges, cases=cases)
    t, sha = table([{"rule": a, "needing": ["C1", "C2", "C3"], "others": ["C4", "C5"]}], ["C4", "C6"])
    r = ablation_pass(store, "default", reader, judges, cases, t, sha, base)
    assert [r["tally"][k]["hit_lost"] for k in ("needing", "others", "sham")] == [1, 2, 0]


# ---- a local model: its thinking off, never read past its context ------------------------------------------------------
def test_a_local_model_reads_with_its_thinking_off_and_never_past_its_context(monkeypatch):
    from semantext.reader import OllamaReader
    sent, said = [], {"response": reply([], "x"), "prompt_eval_count": 3000, "eval_count": 60}

    class Resp:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self.body).encode()

    def fake_open(req, timeout=0):
        if isinstance(req, str):                               # the version lookup
            return Resp({"models": [{"name": "qwen3.6:latest", "digest": "07d35212591f" + "0" * 52}]})
        sent.append(json.loads(req.data.decode("utf-8")))
        return Resp(said)

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    reader = OllamaReader("qwen3.6")
    assert reader.resolve_version() == "sha256:07d35212591f"
    assert reader("prompt") == reply([], "x")
    assert sent[0]["think"] is False and sent[0]["options"] == {"temperature": 0, "num_ctx": 8192}
    said.update(prompt_eval_count=8100, eval_count=92)          # at the context: the card may have been cut
    with pytest.raises(Refused):
        reader("prompt")
    said.update(prompt_eval_count=300, eval_count=3)
    schema = {"type": "string", "enum": ["expected", "forbidden", "neither"]}
    judge_ = OllamaReader("gemma2:2b", decoding={"temperature": 0, "num_ctx": 8192, "think": False, "format": schema})
    judge_("prompt")
    assert sent[-1]["format"] == schema and "format" not in sent[-1]["options"]     # a judge held to its verdicts


def test_a_verdict_in_markdown_is_still_a_verdict():
    from semantext.reader import Reading, verdict
    bold, plain = Fake(lambda p: "**Expected**", "j1", "fam1"), Fake(lambda p: '"expected"', "j2", "fam2")
    assert verdict([bold, plain], "m", Reading(frozenset(), "r", "x", "v"), "e", "f") == "expected"
    prose = Fake(lambda p: "The reading is closer to the expected one.", "j3", "fam3")
    assert verdict([bold, prose], "m", Reading(frozenset(), "r", "x", "v"), "e", "f") == "disputed"   # prose is no verdict


# ---- the command: named readers only, an outside endpoint announced first --------------------------------------------
def test_the_command_announces_an_outside_endpoint_before_any_call(capsys, home, tmp_path, monkeypatch):
    from semantext.cli import main, make_reader
    order = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": reply([], "x")}}]}).encode()

    def fake_open(req, timeout=0):
        order.append(("call", req.full_url))
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("semantext.reader._open", fake_open)          # an endpoint's own opener: no redirects
    main(["init"])
    capsys.readouterr()
    cases = cases_file(tmp_path, [{"message": "Tidy page 1."}])
    monkeypatch.setattr("semantext.cli._out", lambda s: order.append(("said", s)))
    assert main(["backtest", "--cases", str(cases), "--reader", "endpoint:https://models.example/v1/chat#acme-1"]) == 0
    assert order[0][0] == "said" and "models.example, outside this machine" in order[0][1]
    assert any(k == "call" for k, _ in order)
    order.clear()
    main(["backtest", "--cases", str(cases), "--reader", "endpoint:http://127.0.0.1:8080/v1/chat#local-1"])
    assert not any(k == "said" and "outside this machine" in s for k, s in order)   # a local endpoint: no notice
    assert make_reader("ollama:qwen2.5:3b", None).model == "qwen2.5:3b"
    for bad in ("ollama:", "endpoint:no-model-here", "openai:gpt"):
        with pytest.raises(Refused):
            make_reader(bad, None)
    assert main(["backtest", "--cases", str(cases), "--judge", "ollama:x"]) == 1       # judges go with a reader


# ---- arms 10 and 11: off by default, no key stored --------------------------------------------------------------------
def test_an_endpoints_key_is_read_at_call_time_and_never_written(store, monkeypatch, tmp_path):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": reply([], "x")}}]}).encode()

    def fake_open(req, timeout=0):
        sent.update(url=req.full_url, auth=req.get_header("Authorization"))
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_open)
    monkeypatch.setattr("semantext.reader._open", fake_open)          # an endpoint's own opener: no redirects
    monkeypatch.setenv("TEST_READER_KEY", KEY)
    reader = EndpointReader("https://models.example/v1/chat/completions", "acme-1", key_env="TEST_READER_KEY")
    model_backtest(store, "default", reader, cases=cases_file(tmp_path, [{"message": "Tidy page 1."}]))
    assert sent["auth"] == "Bearer " + KEY
    assert not any(KEY in p.read_text(encoding="utf-8", errors="replace")
                   for p in store.root.rglob("*") if p.is_file())
    monkeypatch.delenv("TEST_READER_KEY")
    with pytest.raises(Refused):
        reader("prompt")
