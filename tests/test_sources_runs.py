"""Run records (docs/run-record-schema.md, schema 1): "guarded" comes only from a run record, on the bytes in place now.

Every row of the schema's table has an arm that must pass and one that must refuse, and every refusal reason is planted
and named. The cards, the files checked and the records are all written here, in a temporary folder; the clock is
fixed (NOW), and the person's closures are a sources file written here too.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from semantext import api, jsonread
from semantext.sources import load_config, rules, runs, view

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc)
WORDS = "Ask before you act on a guess."
HOOK = {"name": "pre-write hook", "rules": ["core.a", "core.b"], "must_pass": "a short answer",
        "must_refuse": "a long answer"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git_blob(data: bytes, algo=hashlib.sha1) -> str:
    return algo(b"blob %d\x00" % len(data) + data).hexdigest()


@pytest.fixture
def world(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "secret").mkdir()
    (repo / "runs").mkdir()
    (repo / "src" / "hook.py").write_bytes(b"print('hi')\n")
    (repo / "secret" / "key.py").write_bytes(b"x = 1\n")
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps({"closed": [str(repo / "secret"), str(tmp_path / "shut")]}), encoding="utf-8")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(sources))
    card = {"environment": {"id": "core", "version": "1", "ratified_by": "pat"},
            "entries": [{"id": "core.a", "statement": WORDS, "ratified_by": "pat", "provenance": {"cases": ["C-1"]}},
                        {"id": "core.b", "statement": "Keep it short.", "ratified_by": "pat"}],
            "tests": [{"case": "C-1", "message": "Tidy it?"}]}
    (tmp_path / "cards" / "core").mkdir(parents=True)
    (tmp_path / "cards" / "core" / "SEMANTICS.yaml").write_text(yaml.safe_dump(card), encoding="utf-8")
    return SimpleNamespace(root=tmp_path, cards=tmp_path / "cards", repo=repo, file=repo / "src" / "hook.py")


def good(w, rule="core.a", words=WORDS, **over) -> dict:
    rec = {"schema": 1, "checker": {"name": "semantext-prove", "version": "0.1.0", "sha256": "a" * 64},
           "rule": {"id": rule, "sha256": sha(words)},
           "subject": [{"path": "src/hook.py", "blob": git_blob(w.file.read_bytes())}],
           "arms": {"must_pass": {"ran": 3, "passed": 3, "how": "real git in a scratch copy"},
                    "must_refuse": {"ran": 4, "refused": 4, "how": "same topology"}},
           "at": "2026-10-23T20:00:00Z", "by": "pat", "note": "free text"}
    rec.update(over)
    return rec


def write(w, *lines, name="semantext-prove.jsonl"):
    with open(w.repo / "runs" / name, "a", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


def load(w, **cfg) -> dict:
    return rules.load({"cards": str(w.cards), "run_records": [str(w.repo)], **cfg}, now=NOW)


def rule_of(out: dict, rid: str = "core.a") -> dict:
    return next(r for e in out["environments"] for r in e["rules"] if r["id"] == rid)


def kinds(out: dict) -> list[str]:
    return [p["kind"] for p in out["problems"]]


# ---------------------------------------------------------------- the table: guarded
def test_a_fresh_passing_record_on_the_bytes_in_place_makes_the_rule_guarded(world):   # must pass
    write(world, good(world), good(world, rule="core.b", words="Keep it short."))
    out = load(world)
    a, b = rule_of(out, "core.a"), rule_of(out, "core.b")
    assert (a["held"], b["held"]) == ("guarded", "guarded") and out["problems"] == []
    [v] = a["runs"]
    assert (v["state"], v["stale"], v["checker"], v["version"], v["at"]) == (
        "guarded", [], "semantext-prove", "0.1.0", "2026-10-23T20:00:00Z")
    assert v["arms"]["must_pass"]["passed"] == 3 and v["arms"]["must_refuse"]["refused"] == 4
    assert out["counts"]["guarded"] == 2 and out["counts"]["guarded_once"] == 0
    assert out["run_records"] == [str(world.repo)] and out["run_record_days"] == 30


def test_with_no_record_the_level_is_checked_or_written_as_before(world):   # must refuse: nothing earns guarded
    out = load(world)
    assert (rule_of(out)["held"], rule_of(out, "core.b")["held"]) == ("checked", "written")
    assert rule_of(out)["runs"] == [] and out["problems"] == []
    off = rules.load({"cards": str(world.cards)}, now=NOW)
    assert off["run_records"] is None and rule_of(off)["held"] == "checked"


def test_the_guards_file_alone_never_makes_a_rule_guarded(world):
    guards = world.root / "guards.json"
    guards.write_text(json.dumps({"checkers": [HOOK]}), encoding="utf-8")
    out = load(world, guards=str(guards))
    a, b = rule_of(out), rule_of(out, "core.b")
    assert (a["held"], b["held"]) == ("checked", "written")              # must refuse: a name is a claim
    assert [k["name"] for k in a["checkers"]] == ["pre-write hook"]       # shown beside the rule
    write(world, good(world))
    assert rule_of(load(world, guards=str(guards)))["held"] == "guarded"   # must pass: a record is what earns it


def test_the_rule_hash_is_of_the_words_as_the_card_shows_them(world):
    card = world.cards / "core" / "SEMANTICS.yaml"
    card.write_text(card.read_text(encoding="utf-8").replace(WORDS, '"Ask  before\\tyou act on a guess. "'),
                    encoding="utf-8")
    write(world, good(world))                                            # hashed from the joined words: guarded
    assert rule_of(load(world))["held"] == "guarded"
    (world.repo / "runs" / "semantext-prove.jsonl").unlink()
    write(world, good(world, words="Ask  before\tyou act on a guess. "))  # hashed from the raw text: not the card's
    assert rule_of(load(world))["runs"][0]["stale"] == ["the rule's words have changed since it was recorded"]


def test_a_sha256_blob_id_is_accepted(world):
    rec = good(world, subject=[{"path": "src/hook.py", "blob": git_blob(world.file.read_bytes(), hashlib.sha256)}])
    write(world, rec)
    assert rule_of(load(world))["held"] == "guarded"


def test_the_blob_id_is_gits():
    assert runs.blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"   # git hash-object of "hello\n"
    assert runs.blob_id(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"          # git's empty blob
    assert runs.blob_id(b"hello\n") != runs.blob_id(b"hello\r\n")


# ---------------------------------------------------------------- the table: guarded once (stale), and which
def test_a_changed_byte_makes_it_stale_and_says_which_file(world):
    write(world, good(world))
    world.file.write_bytes(b"print('hi!')\n")
    a = rule_of(load(world))
    assert a["held"] == "guarded once" and a["runs"][0]["stale"] == ["src/hook.py has changed since it was checked"]
    world.file.write_bytes(b"print('hi')\n")                             # must pass: the same bytes again
    assert rule_of(load(world))["held"] == "guarded"


def test_a_subject_gone_is_stale(world):
    write(world, good(world))
    world.file.unlink()
    assert rule_of(load(world))["runs"][0]["stale"] == ["src/hook.py is not there now"]


def test_changed_rule_words_make_it_stale(world):
    write(world, good(world, words="Ask before you act."))
    a = rule_of(load(world))
    assert a["held"] == "guarded once" and a["runs"][0]["stale"] == ["the rule's words have changed since it was recorded"]


@pytest.mark.parametrize("age_days,cfg_days,state", [
    (29, None, "guarded"), (31, None, "stale"), (31, 60, "guarded"), (61, 60, "stale"), (2, 1, "stale")])
def test_the_age_bound_defaults_to_30_days_and_is_configurable(world, age_days, cfg_days, state):
    at = (NOW - timedelta(days=age_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    write(world, good(world, at=at))
    out = load(world, **({"run_record_days": cfg_days} if cfg_days else {}))
    [v] = rule_of(out)["runs"]
    assert v["state"] == state and out["run_record_days"] == (cfg_days or 30)
    if state == "stale":
        assert v["stale"] == [f"it was recorded {age_days} days ago, past the {cfg_days or 30}-day bound"]


def test_every_stale_reason_is_said_together(world):
    write(world, good(world, words="Other words.", at="2026-08-01T00:00:00Z"))
    world.file.write_bytes(b"changed\n")
    [v] = rule_of(load(world))["runs"]
    assert len(v["stale"]) == 3 and v["state"] == "stale"


# ---------------------------------------------------------------- a failed run earns nothing
@pytest.mark.parametrize("arms", [
    {"must_pass": {"ran": 3, "passed": 2}, "must_refuse": {"ran": 4, "refused": 4}},
    {"must_pass": {"ran": 3, "passed": 3}, "must_refuse": {"ran": 4, "refused": 3}}])
def test_a_run_that_did_not_pass_falls_back_to_checked_or_written(world, arms):
    write(world, good(world, arms=arms), good(world, rule="core.b", words="Keep it short.", arms=arms))
    out = load(world)
    assert (rule_of(out)["held"], rule_of(out, "core.b")["held"]) == ("checked", "written")
    assert rule_of(out)["runs"][0]["state"] == "failed" and out["problems"] == []


# ---------------------------------------------------------------- the newest record decides
def test_the_newest_record_for_a_rule_and_checker_decides(world):
    failing = {"must_pass": {"ran": 3, "passed": 1}, "must_refuse": {"ran": 4, "refused": 4}}
    write(world, good(world, at="2026-10-23T19:00:00Z"), good(world, at="2026-10-23T20:00:00Z", arms=failing))
    assert rule_of(load(world))["runs"][0]["state"] == "failed"         # a later failure undoes an earlier pass
    (world.repo / "runs" / "semantext-prove.jsonl").unlink()
    write(world, good(world, at="2026-10-23T20:00:00Z"), good(world, at="2026-10-23T19:00:00Z", arms=failing))
    assert rule_of(load(world))["held"] == "guarded"                    # newest by its time, not its line


def test_each_checker_is_judged_on_its_own_newest_record(world):
    write(world, good(world))
    write(world, good(world, checker={"name": "other", "version": "2"},
                      arms={"must_pass": {"ran": 1, "passed": 0}, "must_refuse": {"ran": 1, "refused": 1}}),
          name="other.jsonl")
    a = rule_of(load(world))
    assert a["held"] == "guarded" and sorted(v["state"] for v in a["runs"]) == ["failed", "guarded"]


def test_a_refused_newer_line_does_not_displace_the_older_record(world):
    write(world, good(world), good(world, at="2026-10-23T23:00:00Z"))   # the newer one is from the future
    out = load(world)
    assert rule_of(out)["held"] == "guarded" and kinds(out) == ["future-time"]


# ---------------------------------------------------------------- refused, each a problem with its reason
def _set(rec, path, value):
    *head, last = path
    for k in head:
        rec = rec[k]
    if value is KeyError:
        del rec[last]
    else:
        rec[last] = value


REFUSALS = [
    (("schema",), KeyError, "no-schema"),
    (("schema",), 2, "wrong-schema"),
    (("schema",), "1", "wrong-schema"),
    (("schema",), True, "wrong-schema"),
    (("arms", "must_pass", "ran"), 0, "arm-not-run"),
    (("arms", "must_refuse", "ran"), 0, "arm-not-run"),
    (("arms", "must_pass", "passed"), 4, "bad-field"),            # more passed than ran
    (("arms", "must_refuse", "refused"), -1, "bad-field"),
    (("arms", "must_pass", "ran"), True, "bad-field"),
    (("arms", "must_refuse"), KeyError, "bad-field"),
    (("at",), "2026-10-23T21:02:01Z", "future-time"),             # past the two minutes of skew
    (("at",), "2027-01-01T00:00:00Z", "future-time"),
    (("at",), "2026-10-23T20:00:00+00:00", "bad-time"),           # not in Z form
    (("at",), "2026-10-23 20:00:00Z", "bad-time"),
    (("at",), "2026-13-01T00:00:00Z", "bad-time"),
    (("at",), KeyError, "bad-time"),
    (("subject",), [{"path": "../outside.py", "blob": "0" * 40}], "outside-roots"),
    (("subject",), [{"path": "secret/key.py", "blob": "0" * 40}], "closed-place"),
    (("subject",), [{"path": "\\\\host\\share\\x.py" if os.name == "nt" else "//host/share/x.py",   # a share, as
                     "blob": "0" * 40}], "outside-roots"),                                          # each system writes it
    (("subject",), [], "bad-field"),
    (("subject",), [{"path": "src/hook.py", "blob": "XYZ"}], "bad-field"),
    (("checker", "name"), "two\nlines", "bad-checker-name"),
    (("checker", "name"), "", "bad-checker-name"),
    (("checker", "name"), " padded", "bad-checker-name"),
    (("checker", "name"), "x" * 101, "bad-checker-name"),
    (("checker", "name"), ["a list"], "bad-checker-name"),
    (("checker", "name"), "zero\u200bwidth", "bad-checker-name"),
    (("checker", "version"), KeyError, "bad-field"),
    (("rule", "sha256"), "short", "bad-field"),
    (("rule", "id"), "", "bad-field"),
    (("detail",), {"must_pass": [{"ok": True}] * 2}, "detail-disagrees"),              # 2 listed, 3 ran
    (("detail",), {"must_refuse": [{"ok": True}] * 3 + [{"ok": False}]}, "detail-disagrees"),   # 3 ok, 4 refused
    (("by",), 7, "bad-field"),
]


@pytest.mark.parametrize("path,value,kind", REFUSALS, ids=[f"{'.'.join(p)}-{k}-{n}" for n, (p, _, k) in
                                                          enumerate(REFUSALS)])
def test_every_refusal_is_a_problem_with_its_reason_and_earns_nothing(world, path, value, kind):
    rec = good(world)
    _set(rec, path, value)
    write(world, rec)
    out = load(world)
    assert rule_of(out)["held"] == "checked" and rule_of(out)["runs"] == []
    [p] = out["problems"]
    assert p["kind"] == kind and p["line"] == 1 and p["source"].endswith("semantext-prove.jsonl") and p["text"]


def test_a_time_within_two_minutes_of_skew_is_read_as_now(world):   # must pass beside future-time
    write(world, good(world, at="2026-10-23T21:01:59Z"))
    assert rule_of(load(world))["held"] == "guarded"


def test_counts_that_agree_with_detail_are_read(world):            # must pass beside detail-disagrees
    detail = {"must_pass": [{"id": "p1", "ok": True}] * 3, "must_refuse": [{"id": "r", "expected": "no"}] * 4}
    write(world, good(world, detail=detail))
    assert rule_of(load(world))["held"] == "guarded"


# ---------------------------------------------------------------- the record's own outcome (docs/run-record-schema.md)
@pytest.mark.parametrize("outcome", ["clean", "with findings", None])
def test_a_clean_outcome_with_passing_counts_is_guarded(world, outcome):   # must pass
    write(world, good(world, **({"outcome": outcome} if outcome else {}), findings=["one"]))
    out = load(world)
    [v] = rule_of(out)["runs"]
    assert rule_of(out)["held"] == "guarded" and v["state"] == "guarded" and v["outcome"] == outcome
    assert v["findings"] == ["one"]


@pytest.mark.parametrize("outcome", ["failed", "not proved"])
def test_a_failed_or_not_proved_outcome_is_never_guarded_whatever_the_counts(world, outcome):   # must refuse
    write(world, good(world, outcome=outcome, findings=["the two answers differ"]))
    out = load(world)
    [v] = rule_of(out)["runs"]
    assert v["state"] == "failed" and v["outcome"] == outcome and rule_of(out)["held"] != "guarded"
    assert v["findings"] == ["the two answers differ"] and out["problems"] == []
    assert v["arms"]["must_pass"]["passed"] == v["arms"]["must_pass"]["ran"]   # the counts did pass


@pytest.mark.parametrize("outcome", ["passed", "Clean", "", 1, True, ["clean"]])
def test_an_unknown_outcome_is_a_problem(world, outcome):   # must refuse
    write(world, good(world, outcome=outcome))
    out = load(world)
    assert kinds(out) == ["bad-outcome"] and rule_of(out)["held"] != "guarded"


def test_a_warned_open_case_ran_and_was_not_refused(world):   # must refuse: the counts then disagree with detail
    cases = ([{"class": "must_pass", "status": "passed"}] * 3 + [{"class": "must_refuse", "status": "passed"}] * 3
             + [{"class": "must_refuse", "status": "warned-open"}])
    write(world, good(world, detail={"arms": cases}))       # arms say 4 of 4 refused; detail says 3 of 4
    out = load(world)
    assert kinds(out) == ["detail-disagrees"] and "detail lists 3 passed of 4 run" in out["problems"][0]["text"]
    honest = good(world, detail={"arms": cases})
    honest["arms"]["must_refuse"]["refused"] = 3                # must pass: counts that say so are read, and fail
    write(world, honest, name="second.jsonl")
    [v] = rule_of(load(world))["runs"]
    assert v["state"] == "failed"


def test_a_summary_decides_nothing(world):
    write(world, good(world, summary={"by_status": {"failed": 99}}, outcome="clean"))
    assert rule_of(load(world))["held"] == "guarded"


@pytest.mark.parametrize("line,kind", [
    ("{ not json", "not-json"),
    ("[1, 2]", "not-a-record"),
    ("\"text\"", "not-a-record"),
    ("NaN", "not-json"),
    ("[" * 300 + "]" * 300, "too-deep"),
    ("{\"a\": " * 300 + "1" + "}" * 300, "too-deep"),
])
def test_a_line_that_is_not_a_record_is_a_problem(world, line, kind):
    write(world, line, good(world))
    out = load(world)
    assert kinds(out) == [kind] and out["problems"][0]["line"] == 1
    assert rule_of(out)["held"] == "guarded"                            # the good line after it is still read


def test_a_line_too_long_is_a_problem(world):
    write(world, good(world, note="x" * (api.MAX_LINE + 10)))
    out = load(world)
    assert kinds(out) == ["too-long"] and rule_of(out)["held"] == "checked"


def test_the_depth_bound_is_the_shared_loaders(world):
    deep = "[" * jsonread.MAX_DEPTH + "]" * jsonread.MAX_DEPTH
    write(world, deep, "[" + deep + "]")
    assert kinds(load(world)) == ["not-a-record", "too-deep"]


def test_extra_fields_are_allowed_and_decide_nothing(world):
    rec = good(world, environment={"git": "2.47", "os": "Windows"}, record_sha256="b" * 64, colour="red",
               checker={"name": "semantext-prove", "version": "0.1.0", "plugin": "x"})
    rec["rule"]["aside"] = 1
    rec["subject"][0]["mode"] = "100644"
    write(world, rec)
    out = load(world)
    assert rule_of(out)["held"] == "guarded" and out["problems"] == []


def test_every_unusable_line_is_its_own_problem_never_dropped(world):
    write(world, "{", good(world, schema=3), "", good(world, at="soon"), good(world))
    out = load(world)
    assert [(p["kind"], p["line"]) for p in out["problems"]] == [("not-json", 1), ("wrong-schema", 2), ("bad-time", 4)]
    assert rule_of(out)["held"] == "guarded"


def test_a_record_for_a_rule_no_card_holds_is_a_problem(world):
    write(world, good(world, rule="core.zz"))
    out = load(world)
    assert kinds(out) == ["unknown-rule"] and "core.zz" in out["problems"][0]["text"]


# ---------------------------------------------------------------- findings: shown, never hidden, never a level
def test_findings_go_with_a_guarded_record_and_leave_the_level_as_the_counts_say(world):
    said = ["the gate's two answers differ: first-ever push vs remote-tracking refs present", "<b>text</b>"]
    write(world, good(world, findings=said))
    a = rule_of(load(world))
    assert a["held"] == "guarded" and a["runs"][0]["findings"] == said


@pytest.mark.parametrize("findings", [[], None, KeyError])
def test_no_findings_is_plain_guarded(world, findings):
    rec = good(world, findings=findings)
    if findings is KeyError:
        del rec["findings"]
    write(world, rec)
    a = rule_of(load(world))
    assert a["held"] == "guarded" and a["runs"][0]["findings"] == []


@pytest.mark.parametrize("findings", ["one finding", {"a": 1}, 3, ["ok", 4], True])
def test_findings_that_are_not_a_list_of_texts_are_a_problem(world, findings):
    write(world, good(world, findings=findings))
    out = load(world)
    assert kinds(out) == ["bad-findings"] and rule_of(out)["held"] == "checked"


# ---------------------------------------------------------------- the first outside checker's own record
SAMPLE = Path(__file__).with_name("data") / "sample_run_record.jsonl"


FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")


@pytest.mark.parametrize("at", [
    "2026-10-23T21:00:00Z".translate(FULLWIDTH),          # every digit fullwidth
    "2026-10-23T21:00:0０Z",                          # one fullwidth digit
    "٢٠٢٦-10-23T21:00:00Z",          # Arabic-Indic digits for the year
    "2026-10-23T21:00:00.１Z",                        # in the fraction
])
def test_a_time_in_digits_of_another_script_is_not_a_time(at):   # must refuse: the schema says [0-9]
    with pytest.raises(runs.Refused) as e:
        runs.parse_at(at)
    assert e.value.kind == "bad-time"


def test_a_time_in_ascii_digits_is_read(at="2026-10-23T21:00:00.5Z"):   # must pass
    assert runs.parse_at(at) == datetime(2026, 10, 23, 21, 0, 0, 500000, tzinfo=timezone.utc)


def test_the_first_outside_checkers_record_parses(tmp_path):
    [line] = [x for x in SAMPLE.read_text(encoding="utf-8").splitlines() if x.strip()]
    data = json.loads(line)
    when = runs.parse_at(data["at"]) + timedelta(minutes=1)
    rec = runs.record(line, str(tmp_path), [str(tmp_path)], when)
    assert (rec["rule"], rec["checker"], rec["version"]) == ("example.test-pre-push-gate", "semantext-prove", "0.1.0")
    assert rec["arms"]["must_pass"]["ran"] == 5 and rec["arms"]["must_refuse"]["refused"] == 10
    assert [s["path"] for s in rec["subject"]] == ["scripts/pre-push", "scripts/pre_push_gate.py"]
    assert len(rec["findings"]) == 3 and "THE TWO ANSWERS DIFFER" in rec["findings"][1]   # shown beside a pass
    # its own outcome is "failed": not guarded, though both arms' counts pass, and its findings go with the verdict
    assert rec["outcome"] == "failed"
    v = runs.verdict(rec, "any words", when)
    assert v["state"] == "failed" and v["outcome"] == "failed" and v["findings"] == rec["findings"]
    assert v["arms"]["must_refuse"]["refused"] == v["arms"]["must_refuse"]["ran"] == 10
    # its detail agrees with its counts: 5 must-pass cases, and 10 must-refuse ones run (one listed as not-run)
    NOW = when
    data["arms"]["must_refuse"]["refused"] = 9                           # must refuse: counts that disagree
    with pytest.raises(runs.Refused) as e:
        runs.record(json.dumps(data), str(tmp_path), [str(tmp_path)], NOW)
    assert e.value.kind == "detail-disagrees"
    data["arms"]["must_refuse"]["refused"] = 10
    data["detail"]["arms"] = [c for c in data["detail"]["arms"] if c["id"] != "A9.pass"]
    with pytest.raises(runs.Refused, match="detail lists 4 passed of 4 run"):
        runs.record(json.dumps(data), str(tmp_path), [str(tmp_path)], NOW)


# ---------------------------------------------------------------- the folders
def test_folders_that_cannot_be_read_are_problems(world, tmp_path):
    (tmp_path / "bare").mkdir()
    (tmp_path / "shut").mkdir()
    out = rules.load({"cards": str(world.cards), "run_records": [str(tmp_path / "gone"), str(tmp_path / "bare"),
                                                                  "relative/folder", str(tmp_path / "shut")]}, now=NOW)
    assert kinds(out) == ["no-folder", "no-folder", "closed-place", "no-runs"]   # the folders first, then inside


def test_a_subject_inside_a_second_listed_folder_is_inside_the_roots(world, tmp_path):
    other = tmp_path / "other"
    (other / "runs").mkdir(parents=True)
    rec = good(world, subject=[{"path": str(world.file), "blob": git_blob(world.file.read_bytes())}])
    (other / "runs" / "x.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")
    out = rules.load({"cards": str(world.cards), "run_records": [str(other)]}, now=NOW)
    assert kinds(out) == ["outside-roots"]                              # must refuse: the repo is not listed
    both = rules.load({"cards": str(world.cards), "run_records": [str(other), str(world.repo)]}, now=NOW)
    assert rule_of(both)["held"] == "guarded" and both["problems"] == []


# ---------------------------------------------------------------- the config, the registry, the schema
def test_the_sources_file_keeps_the_run_record_folders_and_the_bound(tmp_path):
    f = tmp_path / "sources.json"
    f.write_text(json.dumps({"run_records": ["C:\\a", "/b"], "run_record_days": 14, "cards": "c"}), encoding="utf-8")
    assert load_config(f) == {"run_records": ["C:\\a", "/b"], "run_record_days": 14, "cards": "c"}
    f.write_text(json.dumps({"run_records": ["ok", 3], "run_record_days": True}), encoding="utf-8")
    assert load_config(f) == {}                                         # must refuse: not texts, not a number


def test_the_run_reader_is_the_built_in_checker():
    runs_entry, guards_entry = view.BUILT_IN.get("checker", "runs"), view.BUILT_IN.get("checker", "guards")
    assert isinstance(runs_entry.obj, api.Checker) and runs_entry.obj.records and runs_entry.origin == "built-in"
    assert guards_entry.obj.records is None                             # a list of names is not a record
    assert runs_entry.obj.read({})["off"] is True


def test_the_schema_file_is_json_and_states_what_the_reader_requires():
    schema = json.loads(runs.SCHEMA_FILE.read_text(encoding="utf-8"))
    assert schema["$schema"].endswith("2020-12/schema") and schema["properties"]["schema"] == {"const": 1}
    assert set(schema["required"]) == {"schema", "checker", "rule", "subject", "arms", "at"}
    assert schema["additionalProperties"] is True


def test_the_rules_place_carries_each_run_and_the_folders(world, monkeypatch):
    sources = json.loads((world.root / "sources.json").read_text(encoding="utf-8"))
    sources.update(cards=str(world.cards), run_records=[str(world.repo)])
    (world.root / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    write(world, good(world, at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
    got = view.answer("rules", home=world.root)
    [env] = got["environments"]
    a = next(r for r in env["rules"] if r["id"] == "core.a")
    assert a["held"] == "guarded" and a["runs"][0]["checker"] == "semantext-prove"
    assert got["run_records"] == [str(world.repo)] and got["counts"]["guarded"] == 1
    json.dumps(got)                                                     # the answer is JSON: no time objects in it
