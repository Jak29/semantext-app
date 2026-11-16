"""Reader fixes, round 5: R13 (a written clause is paired with its normalised clause only when the pair is verified),
R14 (the proxy's windowed scan still finds a JWT glued after a long run), R15 (/api/explain does not carry the key),
R16 (the CJK false alarm's width is predicted by the stated rule).

Each behaviour has a must-pass and a must-refuse beside it. The R13 shapes are the round-4 attacker's own
(a1_misalign.py: 6 shapes x 6 characters) and a seeded fuzz of his (a5_r11_fuzz.py).
"""
from __future__ import annotations

import io
import json
import random
import re
import time
import contextlib

import pytest

from semantext import cli, decide, feed, inbox, proxy, reading
from test_reader_route import call, home, server   # noqa: F401  (the route's own fixtures)

KEY_PART = "ABCDEFGHIJKLMNOPQRSTUV1234"
LOOK = {"U+FFE3": "￣", "U+00AD": "­", "U+200B": "​", "U+FE4D": "﹍", "U+0331": "̱", "U+2017": "‗"}
CASES = {
    "ellipsis line + U+FF01": lambda k: "Thanks!\n…\nUse " + k + " and publish it！ Then tell me.",
    "ZWSP line + .ZWSP": lambda k: "Okay.\n​\nUse " + k + " now.​ Then publish it.",
    "em-dash line + U+FF1F": lambda k: "Hi.\n—\nUse " + k + " and publish it？ Thanks.",
    "composed 'and' + U+FF0E": lambda k: "Fix it, anḋ then use " + k + "． Publish it.",
    "fullwidth stars + U+FF01 U+3000": lambda k: "＊＊＊\nキーは " + k + " です！　公開してください。",
    "400-clause cap + U+FF01 early": lambda k: "Hello！ There.\n" + "Ok.\n" * 100 + "Use " + k + " now.\n" + "Ok.\n" * 298,
}
SHAPES = [(c, l) for c in CASES for l in LOOK]


def key(ch: str) -> str:
    return "sk" + ch + KEY_PART


def everything(message: str) -> str:
    return json.dumps(reading.report(message), ensure_ascii=False) + json.dumps(reading.read(message).to_dict(),
                                                                               ensure_ascii=False)


# ---------------------------------------------------------------- R13: pair only what is verified
@pytest.mark.parametrize("case,look", SHAPES, ids=lambda x: x if isinstance(x, str) else None)
def test_a_key_is_not_shown_when_normalisation_moves_clause_ends_both_ways(case, look):   # fails on 3e5e2ac: 36 of 36 show it
    m = CASES[case](key(LOOK[look]))
    assert feed.scrub(m) == feed.WITHHELD                       # the premise: the text as written is withheld by the scrub
    assert KEY_PART not in everything(m)
    got = reading.report(m)
    assert got["readings"] and all(r["clause"] == feed.WITHHELD for r in got["readings"])   # the law: every clause is withheld
    assert all(a["quote"] in ("", feed.WITHHELD) or KEY_PART not in a["quote"] for a in got["advice"])


def test_the_exact_example_of_the_finding():
    m = "Thanks!\n…\nUse sk￣" + KEY_PART + " and publish it！ Then tell me."
    written = reading._split(reading.clip(m))
    shown = reading.clauses(m)[0]
    assert len(written) == len(shown)                           # the premise: equal counts, so the old code paired by index
    assert [c.clause for c in reading.read(m).readings] == shown
    assert all(r.shown == feed.WITHHELD for r in reading.read(m).readings)


@pytest.mark.parametrize("case,look", [("ellipsis line + U+FF01", "U+FFE3"), ("fullwidth stars + U+FF01 U+3000", "U+00AD")])
def test_the_route_and_the_command_line_do_not_show_it_either(server, home, case, look):
    m = CASES[case](key(LOOK[look]))
    status, got = call(server, {"message": m})
    assert status == 200 and KEY_PART not in json.dumps(got, ensure_ascii=False)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert cli.main(["--home", str(home), "read", "--", m]) == 0
    assert KEY_PART not in out.getvalue()


def test_the_cap_shape_is_all_or_none():
    m = CASES["400-clause cap + U+FF01 early"](key(LOOK["U+200B"]))
    written = reading._split(reading.clip(m))
    assert len(written) == reading.MAX_CLAUSES and len(reading._split(reading.normalize(reading.clip(m))[0])) > reading.MAX_CLAUSES
    assert len(reading.clauses(m)[0]) == reading.MAX_CLAUSES    # the cap made the two counts equal
    assert all(r.shown == feed.WITHHELD for r in reading.read(m).readings)


def test_seeded_fuzz_of_the_attackers_messages_shows_no_key():             # a5_r11_fuzz.py's 3,000 messages
    rnd = random.Random(1107)
    looks = list(LOOK.values()) + ["⁠", "﻿", "¯", "‾"]
    plain = ["Thanks.", "Fix the build.", "Please check it.", "That looks fine.", "Run the tests.", "Good morning.", "Ok.",
             "了解です。", "Then tell me.", "Let me know."]
    create = ["！ ", "？ ", "． ", "； ", ".​ ", "！　"]
    remove = ["\n…\n", "\n—\n", "\n＊＊＊\n", "\n​\n", "\n―\n", "\n–\n"]
    shown = 0
    for _ in range(3000):
        k = "sk" + rnd.choice(looks) + KEY_PART
        pieces = [rnd.choice(plain) + " " for _ in range(rnd.randint(0, 4))]
        if rnd.random() < 0.8:
            pieces.insert(rnd.randint(0, len(pieces)), rnd.choice(remove))
        pieces.append("Use " + k + " and publish it" + rnd.choice(create) + rnd.choice(plain) + " ")
        pieces += [rnd.choice(plain) + " " for _ in range(rnd.randint(0, 3))]
        if rnd.random() < 0.3:
            pieces.insert(rnd.randint(0, len(pieces)), rnd.choice(plain)[:-1] + rnd.choice(create))
        if rnd.random() < 0.3:
            pieces.insert(rnd.randint(0, len(pieces)), rnd.choice(remove))
        m = "".join(pieces).strip()
        shown += KEY_PART in json.dumps(reading.report(m), ensure_ascii=False)
    assert shown == 0                                                       # 3e5e2ac: a number of them show it


# must-pass: what is not in the hole is shown as before
def test_a_message_unchanged_by_normalisation_shows_its_keyless_clauses():
    got = reading.report("Please fix the build. Use sk-" + KEY_PART + " now. Then publish it.")
    clauses = [r["clause"] for r in got["readings"]]
    assert clauses == ["Please fix the build.", feed.WITHHELD, "Then publish it."]


def test_a_look_alike_key_in_a_message_whose_ends_do_not_move_withholds_only_its_clause():   # the verified pairing is used
    got = reading.report("Thanks. Use sk￣" + KEY_PART + " and publish it. Then tell me.")
    assert [r["clause"] for r in got["readings"]] == ["Thanks.", feed.WITHHELD, "Then tell me."]


@pytest.mark.parametrize("case", list(CASES))
def test_a_misaligned_message_with_no_key_is_shown_whole(case):            # must-pass: nothing is withheld for nothing
    m = CASES[case]("the code word")
    got = reading.report(m)
    assert got["readings"] and all(r["clause"] != feed.WITHHELD for r in got["readings"])


def test_written_forms_pairs_only_what_it_verifies():
    ok = "Thanks. Use sk-" + KEY_PART + " now."
    cs = reading.clauses(ok)[0]
    assert reading.written_forms(ok, cs) == [("Thanks.", False), ("Use sk-" + KEY_PART + " now.", False)]
    bad = CASES["ellipsis line + U+FF01"](key(LOOK["U+FFE3"]))
    cs = reading.clauses(bad)[0]
    forms = reading.written_forms(bad, cs)
    assert forms == [("", True)] * len(cs)                                  # unpaired, and held because a written clause shows a key
    clean = CASES["ellipsis line + U+FF01"]("the code word")
    cs = reading.clauses(clean)[0]
    assert reading.written_forms(clean, cs) == [("", False)] * len(cs)      # unpaired, nothing to hold


def test_the_pairing_is_linear_on_a_long_message():
    m = "Thanks! " * 2400 + "…\n" + "Fine. " * 100
    start = time.perf_counter()
    reading.report(m)
    assert time.perf_counter() - start < 1.0


# ---------------------------------------------------------------- R14: the windowed scan keeps what 99f9116 found
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
OLD_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{8,8192}\.[A-Za-z0-9_-]{8,8192}\.[A-Za-z0-9_-]{8,}", re.I)   # 99f9116's bounded arm


def old_finds(text: str) -> bool:
    for start in range(0, len(text), proxy.SCAN_WINDOW - proxy.SCAN_OVERLAP):
        if OLD_JWT.search(text, start, start + proxy.SCAN_WINDOW):
            return True
    return False


def padded(lead: str, offset: int) -> str:
    text = " " * offset + lead + JWT
    return text + " " * max(0, 200_000 - len(text))


@pytest.mark.parametrize("offset", [0, 5_000, 40_000, 60_000, 70_000, 75_000, 100_000])
@pytest.mark.parametrize("lead", ["eyJ" + "q" * 8297, "eyJ" + "q" * 8300, "eyJ" + "A" * 20_000, "eyJ" + "q" * 100_000,
                                  "q" * 9_000, "q" * 30_000, "q" * 100_000, "x" * 25_000, "eyJ" + "q" * 2000, ""],
                         ids=lambda s: f"{s[:3]}+{len(s)}" if s else "none")
def test_a_jwt_after_a_long_run_is_found_as_99f9116_found_it(lead, offset):       # fails on 3e5e2ac: 73 of 154 missed
    text = padded(lead, offset)
    assert old_finds(text)                                                         # the premise: 99f9116 found it
    assert proxy._secret(text)


def test_the_attackers_call_site_keeps_the_turn_unkept():                           # a3b: decide.keepable itself
    for lead in ("", "eyJ" + "q" * 8300, "eyJ" + "A" * 8200, "q" * 9000, "x" * 25_000):
        content = "Here is the file.\n" + " " * 100_000 + lead + JWT + "\n"
        msg = {"role": "assistant", "content": [{"type": "text", "text": "ok"},
               {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": "notes.txt", "content": content}}]}
        assert decide.keepable(msg, proxy._secret) is False, lead[:3] + str(len(lead))


@pytest.mark.parametrize("text", [
    " " * 100_000 + "eyJ" + "q" * 8300 + "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0",         # no third dot
    " " * 100_000 + "eyJ" + "q" * 8300 + "eyJhbGciOiJIUzI1NiJ9.eyJzdWIi",                              # second segment short
    " " * 100_000 + "q" * 8300 + "xyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVm",   # no eyJ
    " " * 100_000 + "eyJ" + "q" * 9000 + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVm",                  # first segment over the bound
    " " * 100_000 + "eyJ" + "q" * 4 + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVm",                     # first segment under 8
    " " * 100_000 + "eyJ" + "q" * 8 + "." + "r" * 9000 + ".dozjgNryP4J3jVm",                              # second segment over the bound
], ids=["no third dot", "short second", "no eyJ", "first over bound", "first under 8", "second over bound"])
def test_what_99f9116_did_not_find_is_not_found(text):                             # must-refuse a false key
    text += " " * max(0, 200_000 - len(text))
    assert not old_finds(text)
    assert not proxy._secret(text)


@pytest.mark.parametrize("text", ["eyJa" * 50_000, "a." * 100_000, "a" * 200_000, "eyJ" + "a" * 11 + "." * 100_000,
                                  ("a" * 12 + ".") * 15_000, "eyJ" + "a" * 8200 + ("." + "a" * 9000) * 20,
                                  "eyJé" * 50_000, ("eyJaaaaaaaa." + "b" * 8193) * 20],
                         ids=["eyJa", "a.", "a", "dots", "short runs", "long second segments", "e-acute", "second over bound"])
def test_the_windowed_scan_stays_linear(text):
    start = time.perf_counter()
    assert not proxy._secret(text)
    assert time.perf_counter() - start < 1.0


def test_the_bound_that_remains_is_the_one_stated():
    assert "R14" in proxy._secret.__doc__ and "8,192" in proxy._secret.__doc__


# ---------------------------------------------------------------- R15: /api/explain does not carry the key
def explain(server, message):
    status, got = call(server, {"message": message, "words": None, "agent": "helper"}, path="/api/explain")
    assert status == 200
    return got


@pytest.mark.parametrize("message", [
    "Use sk-" + KEY_PART + " and publish it.",
    "Use sk˗" + KEY_PART + " and publish it.",
    "Use sk￣" + KEY_PART + " and publish it.",
    "Use sk​" + KEY_PART + " and publish it.",
    "x" * 150 + " publish sk-" + KEY_PART,
], ids=["ascii", "U+02D7", "U+FFE3", "U+200B", "key across the 160 cut"])
def test_explain_does_not_carry_the_key(server, message):                           # fails on 3e5e2ac: decisions[0].message
    got = explain(server, message)
    assert got["reading"]["decisions"]                                              # the decision itself is kept
    assert all(d["message"] == feed.WITHHELD for d in got["reading"]["decisions"])
    assert KEY_PART not in json.dumps(got["reading"], ensure_ascii=False)


def test_explain_still_carries_an_ordinary_message(server):                         # must-pass
    got = explain(server, "Please publish the notes tomorrow.")
    assert got["reading"]["decisions"] and got["reading"]["decisions"][0]["message"] == "Please publish the notes tomorrow."


def test_explain_with_a_key_but_no_decision_is_unchanged(server):                   # must-pass: nothing to withhold
    got = explain(server, "the code is sk-" + KEY_PART)
    assert got["reading"]["decisions"] == [] and got["reading"]["readings"]


# ---------------------------------------------------------------- R16: the stated width predicts what is withheld
RUN = re.compile(r"[A-Za-z0-9+/=_\-]{32,}")
SIBLINGS = re.compile(r"(?:sk-[A-Za-z0-9_-]{16,}|glpat-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})", re.I)


def stated(text: str) -> bool:
    """The docstring's two rules, written out (the sibling arms and the token run on the folded text), or the raw test."""
    folded = feed._folded(text)
    return (bool(SIBLINGS.search(folded)) or any(re.search("[A-Za-z]", r) and re.search("[0-9]", r) for r in RUN.findall(folded))
            or bool(inbox.SECRET.search(text)) or inbox.token_like(text))


PLAIN_CJK = [
    "このtaskは明日までに終わらせてください。お願いします。",
    "そのdiskはもう容量がいっぱいなので新しいものを注文してください。",
    "このriskについては来週の会議で詳しく説明させていただきます。",
    "请把这个task分配给小王，他明天上午会处理完毕并汇报进度。",
    "これはdeskの上に置いてある書類のことですので確認をお願いします。",
    "Please ask田中さんに明日の会議の資料を準備してもらってください。",
    "この件はaskしておきますので少々お待ちくださいませ、よろしくお願いします。",
    "移动硬盘的disk空间不够了，请尽快清理一下不需要的文件，谢谢。",
    "この作業のtaskは完了しましたか？まだなら今日中にお願いします。",
    "그 task는 내일까지 끝내야 합니다. 부탁드립니다.",
    "このタスクは明日までに終わらせてください。",
]


def generated():
    rnd = random.Random(25)
    cjk = "的一是不了人我在有他这为之大来以个中上们到说国和地也子时道出而要于就下得可你年生自会那后能对着事其里所去行过家十用发天如然作方成者多日都三小军二无同么经法当起与好看学进种将还分此心前面又定见只主没公从"
    words = ["task", "disk", "risk", "desk", "ask", "mask", "flask", "kiosk", "whisk", "dusk"]
    for _ in range(300):
        yield "".join(rnd.choice(cjk) for _ in range(rnd.randint(0, 20))) + rnd.choice(words) + \
              "".join(rnd.choice(cjk) for _ in range(rnd.randint(10, 40)))


@pytest.mark.parametrize("text", PLAIN_CJK)
def test_the_stated_width_predicts_the_ordinary_sentences(text):                     # fails with the round-4 statement: 9 of 11
    assert (feed.scrub(text) == feed.WITHHELD) == stated(text)


def test_the_stated_width_predicts_all_300_generated_strings():
    wrong = [t for t in generated() if (feed.scrub(t) == feed.WITHHELD) != stated(t)]
    assert wrong == []


def test_the_stated_rule_has_a_must_refuse_side():                                   # the rule does not over-predict either
    assert feed.scrub("ask田中さん") != feed.WITHHELD and not stated("ask田中さん")  # too short: fewer than 16 after "sk-"
    assert feed.scrub("このタスクは明日までに終わらせてください。") != feed.WITHHELD     # no ASCII "sk"
    assert "sk-" in feed.scrub.__doc__ and "glpat" in feed.scrub.__doc__
