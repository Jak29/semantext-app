"""What the feed and the reader show, scrubbed (R2, R8): hyphen look-alikes in a key.

The scrub withholds a shown value that has the shape of a key (feed.scrub); the reader shows its clauses through it
(reading.Reading.to_dict). A key spelled with a character that only looks like the hyphen was echoed. The clip's own
tests (a key cut by the clip) are in test_reader_fixes_clip.py.
"""
from __future__ import annotations

import json
import unicodedata

import pytest

from semantext import feed, reading
from semantext.inbox import SECRET

KEY = "sk-ABCDEFGHIJKLMNOPQRSTUV1234"
DASHES = ["‐", "‑", "‒", "–", "—", "―", "−", "﹘", "﹣", "－"]


# ---------------------------------------------------------------- R2: a hyphen that only looks like one
def test_the_ascii_form_is_withheld_the_control():
    assert feed.scrub(KEY) == feed.WITHHELD


@pytest.mark.parametrize("dash", DASHES, ids=lambda d: f"U+{ord(d):04X}")
def test_a_key_whose_hyphen_is_a_lookalike_is_withheld(dash):   # fails on the base: the key is echoed
    key = KEY.replace("-", dash)
    assert SECRET.search(key) is None                   # the premise: the shape test alone does not see it
    assert feed.scrub(key) == feed.WITHHELD
    assert feed.scrub(["a", {"k": key}]) == ["a", {"k": feed.WITHHELD}]
    assert feed.scrub(f"here is the key {key} for you") == feed.WITHHELD


@pytest.mark.parametrize("dash", DASHES, ids=lambda d: f"U+{ord(d):04X}")
def test_a_look_alike_inside_the_key_is_withheld(dash):
    assert feed.scrub("sk-ABCDEFGH" + dash + "IJKLMNOPQRSTUV") == feed.WITHHELD
    assert feed.scrub("glpat" + dash + "ABCDEFGHIJKLMNOPQRSTUVWX") == feed.WITHHELD
    assert feed.scrub("a" * 20 + dash + "B1" * 6) == feed.WITHHELD          # a run no list names, joined by the look-alike


@pytest.mark.parametrize("dash", DASHES, ids=lambda d: f"U+{ord(d):04X}")
def test_ordinary_text_with_those_dashes_is_left_as_it_is(dash):   # must-refuse: no false alarm, nothing rewritten
    for text in (f"pages 10{dash}20 and a pause {dash} then more", f"2020{dash}2021 was fine", f"well{dash}known, sk{dash}8",
                 f"a short sk{dash}ABC", "plain - text"):
        assert feed.scrub(text) == text


def test_what_is_shown_is_withheld_never_rewritten():
    out = feed.scrub("sk‑ABCDEFGHIJKLMNOPQRSTUV1234")
    assert out == "(withheld)" and "‑" not in out and "-" not in out


# ---------------------------------------------------------------- R8: every dash, and the minus signs, and the rest that look like one
MINUS = [0x2212, 0x207B, 0x208B, 0xFE63, 0xFF0D]
PD = [cp for cp in range(0x110000) if unicodedata.category(chr(cp)) == "Pd"]
# The attacker's 36 characters (p1_scrub.py): Unicode's own confusables for the hyphen, the Japanese IME's dash, the
# box-drawing lines and the ideographs that look like one, beside the dashes in Pd.
OTHERS = [0x00AD, 0x02D7, 0x058A, 0x05BE, 0x06D4, 0x1400, 0x1806, 0x1428, 0x2043, 0x207B, 0x208B, 0x2796, 0x2CBA,
          0x2E17, 0x2E1A, 0x2E3A, 0x2E3B, 0x2E40, 0x2E5D, 0x301C, 0x3030, 0x30A0, 0x30FC, 0xFF70, 0xFE31, 0xFE32,
          0x10EAD, 0x2500, 0x2501, 0x23AF, 0x2574, 0x4E00, 0x3161, 0x1173, 0x02C9, 0x02CD]
SECRET_PART = "ABCDEFGHIJKLMNOPQRSTUV1234"


def forms(c: str) -> dict:
    """The attacker's four key forms, each spelled with `c` where the key has a hyphen (or inside the key)."""
    return {"sk": ("sk" + c + SECRET_PART, SECRET_PART),
            "glpat": ("glpat" + c + "ABCDEFGHIJKLMNOPQRSTUVWX", "ABCDEFGHIJKLMNOPQRSTUVWX"),
            "xoxb": ("xoxb" + c + "1234567890" + c + "abcdefghij", "abcdefghij"),
            "inner": ("sk-ABCDEFGH" + c + "IJKLMNOPQRSTUV", "IJKLMNOPQRSTUV")}


def leaks(key: str, secret: str) -> bool:
    return secret in json.dumps(reading.report("Use " + key + " and publish it."), ensure_ascii=False)


def test_the_set_is_what_the_finding_names():   # must-pass: the premise of the tests below
    assert len(PD) >= 25 and 0x2011 in PD and 0x10EAD in PD and 0x2E3A in PD
    assert 0x2212 not in PD and 0x207B not in PD                  # the minus signs are not all dash punctuation: they are named beside it
    assert len(OTHERS) * 4 == 144


@pytest.mark.parametrize("cp", PD + MINUS, ids=lambda cp: f"U+{cp:04X}")
def test_every_dash_punctuation_and_minus_sign_in_a_key_is_withheld(cp):   # fails on the base for all but ten
    for name, (key, secret) in forms(chr(cp)).items():
        assert feed.scrub(key) == feed.WITHHELD, (name, f"U+{cp:04X}")
        assert not leaks(key, secret), (name, f"U+{cp:04X}")


@pytest.mark.parametrize("cp", OTHERS, ids=lambda cp: f"U+{cp:04X}")
def test_the_attackers_144_cases_are_withheld_raw(cp):   # fails on the base: 127 of 144 echo through the reader, all 144 raw
    for name, (key, secret) in forms(chr(cp)).items():
        assert feed.scrub(key) == feed.WITHHELD, (name, f"U+{cp:04X}")
        assert feed.scrub("Use " + key + " and publish it.") == feed.WITHHELD


@pytest.mark.parametrize("cp", OTHERS, ids=lambda cp: f"U+{cp:04X}")
def test_the_attackers_cases_through_the_reader_never_echo_the_key(cp):
    for name, (key, secret) in forms(chr(cp)).items():
        assert not leaks(key, secret), (name, f"U+{cp:04X}")


def test_a_soft_hyphen_in_the_hyphens_place_is_withheld_in_the_reader():   # R11: was a stated limit (a strict xfail)
    assert not leaks("sk\u00ad" + SECRET_PART, SECRET_PART)


def test_the_soft_hyphen_is_withheld_raw():   # must-pass: the feed's own path sees it
    assert feed.scrub("sk­" + SECRET_PART) == feed.WITHHELD


PLAIN = ["café au lait and crème brûlée", "naïve résumé of the Zoë project", "日本語のテキストと漢字の一覧です。", "Ünïcödé — pages 10–20",
         "a short sk˗ABC", "sk˗8", "→ then ✓ done", "Привет мир, это обычный текст", "emoji 🛑 stop"]


@pytest.mark.parametrize("text", PLAIN)
def test_ordinary_non_ascii_text_is_left_as_it_is(text):   # must-refuse: no false alarm, nothing rewritten
    assert feed.scrub(text) == text
    assert feed.scrub([text, {"k": text}]) == [text, {"k": text}]


def test_a_space_is_not_a_hyphen():   # must-refuse: only a character that can stand for the hyphen is read as one
    for sp in (" ", " ", "　", " "):
        assert feed.scrub("sk" + sp + SECRET_PART) == "sk" + sp + SECRET_PART


def test_ascii_only_text_is_scrubbed_as_before():   # must-pass: the ASCII path is unchanged
    assert feed.scrub("Use sk-ABCDEFGHIJKLMNOPQRSTUV1234 now") == feed.WITHHELD
    assert feed.scrub("plain words, no key") == "plain words, no key"
    assert feed.scrub(None) is None and feed.scrub(5) == 5
