"""The reader, v0 (semantext/reading.py): clause readings and the advice they give for one act.

Every case is the person's correction kept as a test (the estate's card cases and the design's built-in cases), each
with its control: the same act, words changed so the answer must differ. Advice is never authority: tighten() only
ever makes the gate stricter."""
import time

import pytest

from semantext import reading as R


def word(msg, act, offer=None, house=()):
    a = R.advise(R.read(msg), act, offer=offer, house=R.read_rules(house))
    return "GO" if a.covers else a.word     # GO: ASK, with the words appearing to cover the act (a hint, never a pass)


CASES = [
    # (message, act, expected word, the rule it carries)
    ("Publish the release tonight.", "publish", "ASK", "your-words-appear-to-cover-it"),
    ("Can you publish the release tonight?", "publish", "ASK", "question-not-instruction"),
    ("I love this release.", "publish", "ASK", "sentiment-not-authority"),
    ("Looks great! I'll push it myself next week.", "push", "BLOCKED", "owner-reserved-action"),
    ("maybe we should delete the old branches", "delete", "ASK", "suggest-not-require"),
    ("Publish it. But don't publish yet.", "publish", "ASK", "conflict-restrictive"),
    ("carry on with the design.", "pay", "ASK", "material-acts-need-words"),
    ("Send the update to the team.", "send", "ASK", "your-words-appear-to-cover-it"),
    ("Push it tomorrow.", "push", "ASK", "time-kept-verbatim"),
    ("If the tests pass, publish it.", "publish", "ASK", "condition-not-checked"),
    ("Fix the release notes.", "publish", "ASK", "go-not-plain"),
    ("Fix the release notes.", "edit", "ALLOWED", "your-words-cover-it"),
    ("hold off on publishing but don't stop", "publish", "BLOCKED", "withheld-stays-held"),
    ("let me know when it's published", "publish", "ASK", "go-not-plain"),
]


@pytest.mark.parametrize("msg,act,want,rule", CASES)
def test_case(msg, act, want, rule):
    a = R.advise(R.read(msg).readings, act)
    assert (a.word, a.rule) == (want, rule), (msg, a)


def test_controls_each_case_can_fail():
    """Must-refuse: the same act with the words changed gives a different word, so no case passes by default."""
    assert word("Publish the release tonight.", "publish") == "GO"
    assert word("Publish the release tomorrow.", "publish") == "ASK"
    assert word("Can you publish it?", "publish") == "ASK"
    assert word("Publish it.", "publish") == "GO"
    assert word("I'll push it myself.", "push") == "BLOCKED"
    assert word("Push it.", "push") == "GO"
    assert word("Delete the old branches.", "delete") == "GO"
    assert word("maybe delete the old branches", "delete") == "ASK"


def test_time_word_kept_verbatim_as_the_bound():
    a = R.advise(R.read("Publish the release Tonight.").readings, "publish")
    assert (a.word, a.covers, a.bound) == ("ASK", True, "Tonight")


def test_bare_yes_binds_to_the_offer_and_only_its_acts():
    offer = "Shall I publish the release?"
    assert word("Yes", "publish", offer=offer) == "GO"
    assert word("Yes", "push", offer=offer) == "ASK"
    assert word("Yes", "publish") == "ASK"               # control: no offer, nothing to bind to


def test_keep_going_with_a_held_act():
    m = "hold off on publishing but don't stop"
    assert word(m, "publish") == "BLOCKED"
    assert word(m, "edit") == "ALLOWED"


def test_house_rules_add_holds():
    ask = ["Ask me before deleting anything."]
    assert word("Delete the old branches.", "delete", house=ask) == "ASK"
    assert word("Delete the old branches.", "delete") == "GO"           # control
    never = ["Never release on a Friday"]
    assert word("Publish the release tonight.", "publish", house=never) == "ASK"
    assert word("Fix the tests.", "publish", house=never) == "BLOCKED"


def test_a_mention_is_not_a_go():
    """Must-refuse: an instruction that only mentions a material act never allows it."""
    for msg, act in [("Fix the release notes.", "publish"), ("Write the email template.", "send"),
                     ("Update the payment page.", "pay"), ("Refactor the delete handler.", "delete"),
                     ("Build the push button.", "push")]:
        assert word(msg, act) != "ALLOWED", (msg, act)


def test_holds_win_over_goes_in_one_clause():
    for msg in ["Don't publish it.", "Do not publish.", "Never publish without me.", "Publish nothing yet.",
                "Publish it, not now", "Stop publishing."]:
        assert word(msg, "publish") in ("ASK", "BLOCKED"), msg


@pytest.mark.parametrize("gate,adv,want", [
    ("ALLOWED", "ASK", "ASK"), ("ALLOWED", "BLOCKED", "BLOCKED"), ("ASK", "ALLOWED", "ASK"),
    ("BLOCKED", "ALLOWED", "BLOCKED"), ("ASK", "BLOCKED", "BLOCKED"), ("ALLOWED", "ALLOWED", "ALLOWED"),
    ("allowed", "ALLOWED", "BLOCKED"), ("", "ALLOWED", "BLOCKED"), (None, "ALLOWED", "BLOCKED"),
])
def test_tighten_never_loosens(gate, adv, want):
    assert R.tighten(gate, R.Advice(adv, "publish", "r", "w")) == want


def test_unknown_act_is_refused():
    with pytest.raises(ValueError):
        R.advise([], "launch")


def test_a_key_in_a_clause_is_withheld_when_shown():
    key = "sk-" + "A1b2C3d4E5f6G7h8J9k0L1m2N3p4Q5r6"
    d = R.read(f"Publish it with {key}").to_dict()
    assert key not in str(d)
    a = R.advise(R.read(f"Publish it with {key}").readings, "publish").to_dict()
    assert key not in str(a)


def test_long_input_is_clipped_and_quick():
    t0 = time.perf_counter()
    r = R.read("a, but " * 50_000)
    assert r.clipped and time.perf_counter() - t0 < 2
    t0 = time.perf_counter()
    R.read("x" * 100_000 + "?")
    R.read("publish " * 5_000)
    assert time.perf_counter() - t0 < 2


def test_a_hold_naming_no_act_holds_the_act_before_it():
    # the go and the hold both cover the act, so the conflict comes back to the person (conflict-restrictive)
    for msg, act in [("Publish it, not now", "publish"), ("Push it. Wait.", "push")]:
        a = R.advise(R.read(msg).readings, act)
        assert (a.word, a.rule) == ("ASK", "conflict-restrictive"), msg
    assert word("Not now.", "push") == "ASK"                                  # nothing before it to attach to
    assert word("Push it. Thanks.", "push") == "GO"                     # control: a note adds no hold


def test_cli_read_prints_clauses_and_advice(tmp_path, capsys):
    from semantext.cli import main
    home = str(tmp_path / "home")
    assert main(["--home", home, "init"]) == 0
    capsys.readouterr()
    assert main(["--home", home, "read", "Looks great! I'll push it myself next week."]) == 0
    out = capsys.readouterr().out
    assert "Clause by clause:" in out and "YOURS TO DO [push]" in out
    assert "push: BLOCKED (owner-reserved-action)" in out
    assert main(["--home", home, "read", "--offer", "Shall I publish it?", "--act", "publish", "yes"]) == 0
    assert "publish: ASK (your-words-appear-to-cover-it)" in capsys.readouterr().out


def test_empty_and_odd_input():
    assert R.read("").readings == [] and R.read(None).readings == []
    assert word("", "publish") == "ASK" and word("", "edit") == "ALLOWED"


# Koinos's attack on r1 (39 false ALLOWED in 12 families, replayed and confirmed before r2): every one must now ask or
# block, and each family's plain control must still be ALLOWED, so the fix is not "never allow".
ATTACK_R1 = [
    ("Publish it. Don\u2019t.", "publish", None, ()), ("Publish it. Don`t.", "publish", None, ()),
    ("Publish it. Do n't.", "publish", None, ()), ("Push it, I\u2019ll do it", "push", None, ()),
    ("Push it. No.", "push", None, ()), ("Push it. Nope.", "push", None, ()),
    ("Publish it. Hold on.", "publish", None, ()), ("Publish it. Scratch that.", "publish", None, ()),
    ("Publish it. Forget it.", "publish", None, ()), ("Publish it. Hang on.", "publish", None, ()),
    ("Publish it. Thanks. Don't.", "publish", None, ()),
    ("Sure, but not yet", "publish", "Shall I publish it?", ()), ("Yes. Wait.", "publish", "Shall I publish it?", ()),
    ("Yes. Not yet.", "publish", "Shall I publish it?", ()),
    ("yes", "publish", "Want me to hold off on publishing?", ()),
    ("yes", "delete", "Should I delete the old branch, or keep it?", ()),
    ("Publish it unless the tests fail.", "publish", None, ()), ("Publish it once CI passes.", "publish", None, ()),
    ("Publish it when the build is green.", "publish", None, ()), ("Publish it after review.", "publish", None, ()),
    ("Publish it as soon as CI passes.", "publish", None, ()), ("Publish it on Friday.", "publish", None, ()),
    ("Publish it in an hour.", "publish", None, ()), ("Publish it next month.", "publish", None, ()),
    ("Publish it at 5pm.", "publish", None, ()), ("Publish it. Tomorrow.", "publish", None, ()),
    ("Publish it\ntomorrow", "publish", None, ()), ("Push it or leave it, your call.", "push", None, ()),
    ("Push it. I'd rather push it myself.", "push", None, ()),
    ("", "publish", None, ("Publishing needs my approval.",)), ("", "delete", None, ("Deleting files is forbidden.",)),
    ("Push it.", "push", None, ("No pushing to main.",)),
    ("Publish it. " + "x " * 10000 + "Don't.", "publish", None, ()),
    ("Publish it. " + "ok. " * 500 + "Don't.", "publish", None, ()),
    ("Publish it. Wa\u200bit.", "publish", None, ()), ("Publish it. St\u043ep.", "publish", None, ()),
]


@pytest.mark.parametrize("msg,act,offer,house", ATTACK_R1)
def test_attack_r1_no_false_allowed(msg, act, offer, house):
    assert word(msg, act, offer=offer, house=house) not in ("ALLOWED", "GO"), (msg, act, offer, house)


def test_attack_r1_controls_still_allowed():
    for msg, act, offer in [("Publish it.", "publish", None), ("Push it. Thanks.", "push", None),
                            ("Publish it tonight.", "publish", None), ("Publish it now, thank you!", "publish", None),
                            ("Yes", "publish", "Shall I publish it?"), ("Delete the old branch.", "delete", None),
                            ("Great! Send the update to the team.", "send", None)]:
        assert word(msg, act, offer=offer) == "GO", (msg, act, offer)
    assert word("Publish it, but don't push.", "push") == "BLOCKED"
    assert word("Publish it, but don't push.", "publish") == "ASK"      # a hold word anywhere: no hint, only an ask

def test_attack_r2_no_material_allowed_and_house_rules_without_an_act_ask():
    """Orithises's attack on r2 (run: 1,517 inputs, false ALLOWED in 8 families). r3: no material act is ever ALLOWED
    by words; a house rule naming no material act asks first for all of them; the hint does not fire on these."""
    for msg in ["Postgres is down.", "Published it.", "Publish it, I guess.", "Publish it sometime.", "Publish it. 🛑",
                "Publish it, wa\u034fit", "Publish it. Ok, internal only.", "Publish it, he said",
                "Publish it. Wait, fix the typo first.", "Publish it, but not until the build is green."]:
        a = R.advise(R.read(msg), "publish")
        assert a.word != "ALLOWED" and not a.covers, msg
    for rule in ["Nothing leaves the building", "Keep main untouched", "Hold everything", "Prod is read-only",
                 "Nothing goes to GitHub without me"]:
        assert word("Publish it.", "publish", house=[rule]) in ("ASK", "BLOCKED"), rule
    assert word("Yes", "publish", offer="Shall I fix the release notes?") == "ASK"
    assert word("Yes", "publish", offer="Shall I publish it?") == "GO"                          # control