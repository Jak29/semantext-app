"""The reader's clip (R7): the reader reads exactly the first MAX_CHARS characters, and what is SHOWN of the clause that
runs to the clip is withheld at its end.

The round-2 cut-back (R3) changed what is READ: it dropped a hold written in the word the clip falls inside, so a held
act read ALLOWED, and for a key longer than 200 characters it only moved the leak. The cut-back is gone. Reading is as it
was before it, and the withholding is in what is shown: the clause that runs to the clip ends "(the rest is withheld at
the clip)" in place of its final token, whatever its length. Each behaviour has a must-pass and a must-refuse beside it.
"""
from __future__ import annotations

import pytest

from semantext import feed, reading

MARK = "(the rest is withheld at the clip)"     # the words, as the page and `semantext read` show them
FILL = "qj "   # letters no key below holds, so a key fragment in the shown text is never mistaken for the filler


def padded(key: str, cut: int) -> str:
    """A message whose 20,000th character is the `cut`-th of the key, with words after it that the clip drops."""
    pad = reading.MAX_CHARS - cut
    prefix = (FILL * (pad // len(FILL) + 1))[: pad - 1] + " "
    assert len(prefix) == pad and prefix.endswith(" ")
    return prefix + key + " and the rest of the message goes on after it"


def last_shown(msg: str) -> dict:
    return reading.report(msg)["readings"][-1]


def everything_shown(msg: str, acts=None) -> str:
    """Every string the answer carries: the clauses and the quotes of the advice."""
    out = reading.report(msg, acts=acts)
    return "\n".join([x["clause"] for x in out["readings"]] + [a["quote"] for a in out["advice"]])


def test_the_mark_is_the_words_the_finding_asked_for():
    assert reading.CLIP_MARK == MARK


# ---------------------------------------------------------------- what is READ: the first MAX_CHARS, as before the cut-back
def test_the_clip_is_the_first_max_chars_and_nothing_less():   # fails on 4756135: it cut up to 200 back
    msg = "word " * 3999 + "wordabcdefgh tail"                    # the 20,000th character is inside the last word
    assert reading.clip(msg) == msg[: reading.MAX_CHARS]
    cs, clipped = reading.clauses(msg)
    assert clipped is True and cs[0].split() == ["word"] * 3999 + ["worda"]


def test_a_run_with_no_space_is_read_to_the_clip():   # fails on 4756135: its length was MAX_CHARS - 200
    cs, clipped = reading.clauses("x" * 30_000)
    assert clipped is True and len(cs[0]) == reading.MAX_CHARS
    assert reading.read("x" * 30_000).clipped is True


def test_a_message_within_the_clip_is_read_whole_and_nothing_is_cut():   # must-refuse: nothing changes below the clip
    msg = "Publish the release tonight. " * 300
    assert len(msg) < reading.MAX_CHARS
    whole = reading.read(msg)
    assert whole.clipped is False and len(whole.readings) == 300
    assert reading.clauses(msg)[0][0] == "Publish the release tonight."
    assert reading.clip(msg) == msg
    assert MARK not in everything_shown(msg)
    edge = "a" * (reading.MAX_CHARS - 1) + "b"                   # exactly MAX_CHARS: not clipped
    assert reading.read(edge).clipped is False and MARK not in everything_shown(edge)


def hold_in_the_word_the_clip_falls_inside() -> str:
    """The attacker's input: a hold written 100 characters before the clip, in a run with no space that the clip cuts."""
    head = "Fix the bug. "
    assert len(head) + len(FILL) * 6629 == 19900
    m = head + FILL * 6629 + "Don't-fix-it-" + "z" * 587 + " tail"
    assert m.index("Don't-fix-it-") == 19900 and len(m) > reading.MAX_CHARS > m.index("z")
    return m


def test_a_hold_in_the_word_the_clip_falls_inside_is_read_as_a_hold():   # fails on 4756135: edit read ALLOWED
    m = hold_in_the_word_the_clip_falls_inside()
    adv = reading.advise(reading.read(m), "edit")
    assert (adv.word, adv.rule) == ("ASK", "conflict-restrictive")
    held = reading.held_by_words(m, ["edit"])
    assert held is not None and held["act"] == "edit" and held["rule"] == "conflict-restrictive"
    out = reading.report(m)
    assert out["clipped"] is True and out["max_chars"] == reading.MAX_CHARS      # the page says what was read, and it was


def test_the_same_words_with_no_hold_in_them_still_read_allowed():   # must-refuse: the hold is what holds, not the clip
    m = hold_in_the_word_the_clip_falls_inside().replace("Don't-fix-it-", "Fix-the-thing-")
    assert reading.advise(reading.read(m), "edit").word == "ALLOWED"
    assert reading.held_by_words(m, ["edit"]) is None


def test_a_material_act_in_a_clipped_message_still_asks():   # must-pass: whole-message-not-read, as before
    m = hold_in_the_word_the_clip_falls_inside().replace("Fix the bug.", "Publish the release now.")
    assert reading.advise(reading.read(m), "publish").word == "ASK"


# ---------------------------------------------------------------- what is SHOWN: the clause that runs to the clip
def test_the_clause_that_runs_to_the_clip_ends_withheld_in_place_of_its_final_token():
    first = "Publish the release tonight. "
    pad = reading.MAX_CHARS - 5 - len(first)
    msg = first + (FILL * (pad // 3 + 1))[: pad - 1] + " " + "ghp_A" + " and more after the clip"
    assert msg.index("ghp_A") + 5 == reading.MAX_CHARS
    got = reading.report(msg)
    last = got["readings"][-1]["clause"]
    assert got["clipped"] is True and last.endswith(" " + MARK) and "ghp_A" not in last
    assert got["readings"][0]["clause"] == "Publish the release tonight."        # earlier clauses are shown as they were
    assert sum(MARK in x["clause"] for x in got["readings"]) == 1                # only the one that runs to the clip


def test_a_one_token_clause_at_the_clip_is_shown_as_the_mark_alone():   # whatever its length
    tail = "Publish the release tonight. Stop"
    msg = (FILL * 7000)[: reading.MAX_CHARS - len(tail) - 2] + ". " + tail + " and the rest goes on after it"
    assert msg.index("Stop") + 4 == reading.MAX_CHARS
    got = reading.report(msg)["readings"]
    assert got[-1]["clause"] == MARK
    assert got[-2]["clause"] == "Publish the release tonight."       # the clause before it is shown whole
    assert len(got) == 3


@pytest.mark.parametrize("n", [1, 3, 40, 199, 200, 201, 5000, 19_000])
def test_the_mark_replaces_a_final_token_of_any_length(n):
    head = "Publish it. "
    pre = head + (FILL * 7000)[: reading.MAX_CHARS - len(head) - n - 1]
    pre = pre.rstrip() + " "
    token = "Z" * (reading.MAX_CHARS - len(pre))
    assert token and len(pre) + len(token) == reading.MAX_CHARS
    last = last_shown(pre + token + " beyond the clip")["clause"]
    assert last.endswith(MARK) and "ZZ" not in last and "Z" not in last.replace(MARK, "")


def test_the_advice_quote_of_the_cut_clause_is_withheld_too():
    # a hold in the final clause is quoted by the advice: the quote is the shown text, not the clause as read
    base = "Do not publish " + "A1" * 30
    lead = ("qj " * 7000)[: reading.MAX_CHARS - 40]
    lead = lead[:-1] + ". "
    m = lead + base + " beyond the clip"
    assert m.index("A1") < reading.MAX_CHARS < m.index("A1") + 60
    out = reading.report(m, acts=["publish"])
    adv = out["advice"][0]
    assert adv["word"] == "BLOCKED" and adv["quote"].endswith(MARK) and "A1A1" not in adv["quote"]
    assert "A1A1" not in everything_shown(m, ["publish"])
    assert "Do not publish" in adv["quote"]                      # must-pass: the words before the cut token stay


def test_a_clause_that_does_not_run_to_the_clip_is_shown_whole():   # must-refuse: the mark is for the cut clause only
    msg = "Publish the release tonight. Then stop. " + FILL * 7000
    got = reading.report(msg)
    assert got["clipped"] is True and len(got["readings"]) == 3
    assert all(MARK not in x["clause"] for x in got["readings"][:-1])
    assert got["readings"][0]["clause"] == "Publish the release tonight."
    assert got["readings"][-1]["clause"].endswith(MARK)


def test_a_message_clipped_by_the_clause_cap_only_shows_no_mark():   # must-refuse: no clause runs to the length clip
    msg = "Publish it. " * 500                                   # 6,000 characters, 500 clauses: the cap, not the clip
    assert len(msg) < reading.MAX_CHARS
    got = reading.report(msg)
    assert got["clipped"] is True and len(got["readings"]) == reading.MAX_CLAUSES
    assert all(MARK not in x["clause"] for x in got["readings"])


def test_a_clause_cap_on_a_message_also_clipped_by_length_marks_nothing():   # must-refuse: the cap's last is not the clip's
    msg = "Publish it. " * 3000                                  # 36,000 characters: 400 clauses are kept, none runs to the clip
    got = reading.report(msg)
    assert got["clipped"] is True and all(MARK not in x["clause"] for x in got["readings"])


# ---------------------------------------------------------------- every key shape and length cut at the clip shows no key characters
SHAPES = [
    ("openai", "sk-ABCDEFGHIJKLMNOP"),
    ("stripe-live", "sk_live_ABCDEFGHIJKLMNOP"),
    ("stripe-restricted", "rk_test_ABCDEFGHIJKLMNOP"),
    ("webhook", "whsec_ABCDEFGHIJKLMNOPQRST"),
    ("github-p", "ghp_ABCDEFGHIJKLMNOPQRST"),
    ("github-o", "gho_ABCDEFGHIJKLMNOPQRST"),
    ("github-u", "ghu_ABCDEFGHIJKLMNOPQRST"),
    ("github-s", "ghs_ABCDEFGHIJKLMNOPQRST"),
    ("github-r", "ghr_ABCDEFGHIJKLMNOPQRST"),
    ("github-pat", "github_pat_ABCDEFGHIJKLMNOPQRST"),
    ("gitlab", "glpat-ABCDEFGHIJKLMNOPQRST"),
    ("aws", "AKIAABCDEFGHIJKLMNOP"),
    ("google", "AIza" + "A" * 35),
    ("google-oauth", "ya29.ABCDEFGHIJKLMNOPQRST"),
    ("slack", "xoxb-1234567890"),
    ("slack-hook", "hooks.slack.com/services/ABCDEFGHIJKLMNOPQRST"),
    ("hugging-face", "hf_" + "A" * 30),
    ("npm", "npm_" + "A" * 30),
    ("jwt", "eyJABCDEFGH.ABCDEFGHIJ.ABCDEFGHIJ"),
    ("pem", "-----BEGIN RSA PRIVATE KEY-----"),
    ("url-password", "https://user:secretpw@host"),
    ("assignment", "api_key=ABCDEFGH1234"),
    ("assignment-spaced", "password: ABCDEFGH1234"),
    ("said-in-prose", "the password is hunter2xyz"),
    ("long-run", "A1" * 20),                                      # no list names it: token_like
]
# The keys the cut-back could not cover: longer than the 200 characters it looked back (R7), from 150 to 300 characters.
LONG = [
    ("opaque", "A1" * 150),
    ("sk-proj", "sk-proj-" + "A1" * 146),
    ("ya29", "ya29." + "A1" * 148),
    ("github_pat", "github_pat_" + "A1" * 145),
    ("glpat", "glpat-" + "A1" * 147),
    ("hf", "hf_" + "A1" * 148),
    ("npm", "npm_" + "A1" * 148),
    ("aws-session", "IQoJb3JpZ2luX2VjEJr" + "Z" * 281),
    ("sts-json", '"SessionToken": "IQoJb3JpZ2luX2VjEJr' + "Z" * 270),
]


def test_each_shape_is_a_key_the_scrub_knows_whole():   # must-pass: the cut tests below start from real keys
    assert len(SHAPES) >= 24 and len(LONG) == 9
    for name, key in SHAPES + LONG:
        assert feed.scrub(key) == feed.WITHHELD, name


@pytest.mark.parametrize("name,key", SHAPES, ids=[s[0] for s in SHAPES])
def test_a_key_cut_at_the_clip_at_any_length_shows_no_key_characters(name, key):   # fails on 4756135 for the gaps the cut-back left
    for cut in range(1, len(key) + 1):
        msg = padded(key, cut)
        assert len(msg) > reading.MAX_CHARS
        shown = last_shown(msg)["clause"]
        if shown == feed.WITHHELD:                               # the mark itself read as the value of "the password is": withheld whole
            continue
        assert shown.endswith(MARK), (name, cut, shown[-40:])
        body = shown[: -len(MARK)]
        last = key[:cut].split()[-1]                             # the final token the clip leaves of the key
        assert last not in body, (name, cut, body[-40:])
        assert last not in everything_shown(msg).replace(MARK, ""), (name, cut)


@pytest.mark.parametrize("name,key", LONG, ids=[s[0] for s in LONG])
def test_a_key_longer_than_200_characters_cut_at_the_clip_shows_no_key_characters(name, key):   # fails on 4756135: 1-31 characters
    cuts = sorted(set(range(1, len(key) + 1, 7)) | set(range(150, min(len(key), 259) + 1)) | {len(key)})
    for cut in cuts:
        msg = padded(key, cut)
        assert len(msg) > reading.MAX_CHARS
        shown = last_shown(msg)["clause"]
        assert shown.endswith(MARK), (name, cut)
        body = shown[: -len(MARK)]
        assert "A1A1" not in body and "ZZZZ" not in body, (name, cut, body[-50:])
        assert body.endswith(" "), (name, cut, body[-30:])        # the mark stands after a space, where the token began


def test_the_attackers_own_inputs_show_no_key_characters():   # the finding's two inputs, as the route and the CLI give them
    key = "A1" * 150
    m = (FILL * 6700)[:19768] + " " + key + " and the rest goes on after it"
    assert m.index(key) == 19769 and len(m) > reading.MAX_CHARS
    shown = last_shown(m)["clause"]
    assert shown.endswith(MARK) and "A1" not in shown
    sts = ("log line " * 2200)[:19750] + ' {"Credentials": {"AccessKeyId": "ASIAEXAMPLEEXAMPLE", "SessionToken": "IQoJb3JpZ2luX2VjEJr' + "Z" * 400
    assert sts.index("SessionToken") + 40 < reading.MAX_CHARS < len(sts)
    shown = last_shown(sts)["clause"]
    assert "IQoJb3JpZ2luX2VjEJrZ" not in shown and "ZZZZ" not in shown


def test_a_whole_key_is_withheld_as_ever():   # must-pass: the whole key in the middle of a message is not shown
    assert "ABCDEFGHIJKLMNOPQRSTUV" not in everything_shown("Use sk-ABCDEFGHIJKLMNOPQRSTUV1234 and publish it.")
