"""Reader fixes, round 4: R10 (the page's server is not stalled by one read), R11 (a key is not shown as normalisation
changed it), R12 (a keystroke in the offer box touches only the advice).

R10's unit rows (the key-shape check in proportion to its input) are in tests/test_secret_linear.py. Here: the same
message through the route, answered under a second, and another request answered while it is out. Each behaviour has a
must-pass and a must-refuse beside it.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
import urllib.request

import pytest

from semantext import feed, reading
from test_reader_fixes_offer import GONE, HINT, OFFER, YES, answers, stub
from test_reader_route import call, home, server   # noqa: F401  (the route's own fixtures)
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
ACTS = "publish push delete send pay download fix "


# ---------------------------------------------------------------- R10: one request does not stall the server
@pytest.mark.parametrize("unit", ["eyJa", "eyJé", "eyJ㌖", "eyJ㎉"], ids=["ascii", "e-acute", "U+3316", "U+3389"])
def test_the_attackers_message_is_answered_in_under_a_second(server, unit):   # fails on the base: 5.6 to 18.5 s
    message = ACTS + unit * ((20_000 - len(ACTS)) // 4)
    assert len(message) in range(19_990, 20_001)
    start = time.perf_counter()
    status, got = call(server, {"message": message})
    assert status == 200 and got["readings"]
    assert time.perf_counter() - start < 1.0


def test_another_request_is_not_held_while_the_long_read_is_out(server):   # the GIL: the base held a GET for 17.7 s
    message = ACTS + "eyJa" * ((20_000 - len(ACTS)) // 4)
    box = {}
    thread = threading.Thread(target=lambda: box.update(got=call(server, {"message": message})))
    thread.start()
    time.sleep(0.05)
    start = time.perf_counter()
    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/api/state", timeout=20) as r:
        r.read()
    waited = time.perf_counter() - start
    thread.join()
    assert box["got"][0] == 200 and waited < 1.0


def test_an_ordinary_long_message_is_still_read():                     # must-pass: the fix did not narrow what is read
    got = reading.report("Fix the bug. " * 300)
    assert got["clipped"] is False and got["readings"]


# ---------------------------------------------------------------- R11: scrub the clause as written too
KEY_PART = "ABCDEFGHIJKLMNOPQRSTUV1234"
EXAMPLES = [0xFFE3, 0x00AF, 0x203E, 0xFE49, 0xFE4A, 0xFE4B, 0xFE4C, 0x2017, 0xFE4D, 0xFE4E, 0xFE4F, 0xFF3F, 0xFE33, 0xFE34,
            0x0331, 0x200B, 0x2060, 0xFEFF, 0x00AD]


def shown(message: str) -> str:
    return json.dumps(reading.read(message).to_dict()) + json.dumps(reading.report(message), ensure_ascii=False)


@pytest.mark.parametrize("cp", EXAMPLES, ids=lambda cp: f"U+{cp:04X}")
def test_a_key_spelled_with_a_character_normalisation_changes_is_not_shown(cp):   # fails on the base: the key is echoed
    message = "Use sk" + chr(cp) + KEY_PART + " and publish it."
    assert feed.scrub(message) == feed.WITHHELD                          # the premise: the raw scrub withholds it
    assert KEY_PART not in shown(message)
    assert reading.read(message).readings[0].shown == feed.WITHHELD


def test_the_attackers_characters_over_the_basic_plane_are_all_withheld():   # the 1,822 of the finding, found here by walking
    candidates = []
    for cp in range(0x10000):
        c = chr(cp)
        if 0xD800 <= cp < 0xE000 or c.isspace():
            continue
        written = "Use sk" + c + KEY_PART + " and publish it."
        if feed.scrub(written) != feed.WITHHELD:
            continue
        clause = reading.clauses(written)[0]
        if len(clause) == 1 and feed.scrub(clause[0]) != feed.WITHHELD:
            candidates.append(c)
    assert len(candidates) > 800, len(candidates)                        # the premise: normalisation hides it from the scrub (the finding's 1,822 are over all planes)
    for c in candidates:
        got = reading.read("Use sk" + c + KEY_PART + " and publish it.")
        assert got.readings[0].shown == feed.WITHHELD, f"U+{ord(c):04X}"
        assert KEY_PART not in json.dumps(got.to_dict()), f"U+{ord(c):04X}"


def test_the_route_does_not_echo_it_either(server):
    status, got = call(server, {"message": "Use sk￣" + KEY_PART + " and publish it."})
    assert status == 200 and KEY_PART not in json.dumps(got, ensure_ascii=False)
    assert got["readings"][0]["clause"] == feed.WITHHELD


def test_only_the_clause_with_the_key_is_withheld():                    # must-refuse: the rest of the message is still shown
    got = reading.report("Please fix the build. Use sk￣" + KEY_PART + " now. Then publish it.")
    clauses = [r["clause"] for r in got["readings"]]
    assert clauses[0] == "Please fix the build." and clauses[1] == feed.WITHHELD and clauses[2] == "Then publish it."
    assert got["advice"]                                               # the reading itself is unchanged: the acts are still advised on


def test_the_reading_is_the_same_with_the_clause_withheld():            # withholding is in what is shown, never in what is read
    plain = reading.read("Do not publish it. Use sk-" + KEY_PART + " now.")
    odd = reading.read("Do not publish it. Use sk￣" + KEY_PART + " now.")
    assert [(r.kind, r.acts) for r in plain.readings] == [(r.kind, r.acts) for r in odd.readings]
    assert reading.advise(odd, "publish").word == reading.advise(plain, "publish").word


@pytest.mark.parametrize("text", ["café au lait and crème brûlée.", "naïve résumé of the Zoë project.", "Ünïcödé — pages 10–20.",
                                  "Привет мир, это обычный текст.", "emoji \U0001f6d1 stop.", "Use the sk˗ prefix.",
                                  "Please publish the release."])
def test_ordinary_clauses_are_shown_as_they_were(text):                # must-refuse: no false alarm for plain text
    r, = reading.read(text).readings
    assert r.shown == reading.normalize(text)[0].strip() and r.to_dict()["clause"] == r.shown


def test_ascii_keys_are_still_withheld_and_a_plain_clause_still_is_not():
    assert reading.read("Use sk-" + KEY_PART + " now.").to_dict()["readings"][0]["clause"] == feed.WITHHELD
    assert reading.read("Use the key from the vault now.").to_dict()["readings"][0]["clause"] == "Use the key from the vault now."


def test_a_message_whose_clauses_normalisation_re_cuts_is_withheld_whole_when_it_holds_a_key():
    # U+FF0E is a full stop only after NFKC, so the written form has one clause where the normalised form has two.
    keyed = reading.read("Okay．  Use sk￣" + KEY_PART + " and publish it.")
    assert len(keyed.readings) == 2
    assert all(r.shown == feed.WITHHELD for r in keyed.readings) and KEY_PART not in shown("Okay．  Use sk￣" + KEY_PART)
    plain = reading.read("Okay．  Fine then, publish it.")           # must-refuse: no key, nothing withheld
    assert len(plain.readings) == 2 and not any(r.shown == feed.WITHHELD for r in plain.readings)
    assert plain.readings[1].shown == "Fine then, publish it."


def test_house_rules_and_the_offer_keep_the_mark():                     # the places a Reading is made again from another
    house = reading.read_rules(["Never publish with sk￣" + KEY_PART])
    assert house and all(r.shown == feed.WITHHELD for r in house)
    got = reading.advise(reading.read("Yes"), "publish", offer="Shall I publish the release?")
    assert got.covers
    offered = reading.read("Yes sk￣" + KEY_PART)
    assert KEY_PART not in json.dumps(reading.advise(offered, "publish", offer="Shall I publish the release?").to_dict())


def test_a_long_message_is_checked_in_proportion_to_its_length():       # the second scrub is not a new quadratic
    message = ("Fix the build sk￣ and then publish it. " * 400)[:20_000]
    start = time.perf_counter()
    reading.report(message)
    assert time.perf_counter() - start < 1.0


# ---------------------------------------------------------------- R12: a keystroke in the offer box touches only the advice
OPEN = """
const all = (view, tag) => view.all((e) => e.tagName === tag);
const fold = (view) => all(view, "DETAILS").find((e) => e.textContent.startsWith("Not read the way you meant?"));
const teach = (view) => all(view, "INPUT").find((e) => e.getAttribute("name") === "words");
const adviceSlot = (view) => view.querySelector('[data-slot="advice"]');
const type = (box, v) => { box.value = v; box.dispatch("input"); };
"""


@needs_node
def test_typing_in_the_offer_box_keeps_the_fold_the_teach_words_and_the_node():   # fails on the base: all three are lost
    got = run(stub(answers((YES, OFFER))) + OPEN + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const view = moved.VIEWS.test(), box = offerBox(view);
  type(box, %s);                                            // the offer put in: the hint is drawn
  const f0 = fold(view), t0 = teach(view);
  f0.open = true; t0.value = "Never publish without asking me";
  const steps = { drawn: flowOf(view) };
  type(box, %s + " now");                                   // a keystroke that changes the offer: the advice is withdrawn
  steps.changed = { text: flowOf(view), open: fold(view).open, words: teach(view).value, sameFold: fold(view) === f0, sameTeach: teach(view) === t0 };
  type(box, %s);                                            // typed back: the advice is drawn again
  steps.restored = { text: flowOf(view), open: fold(view).open, words: teach(view).value, sameTeach: teach(view) === t0 };
  report(steps);
});
""" % (json.dumps(YES), json.dumps(OFFER), json.dumps(OFFER), json.dumps(OFFER), json.dumps(OFFER)))
    assert HINT in got["drawn"]                                  # must-pass: the control drew the hint
    c = got["changed"]
    assert HINT not in c["text"] and GONE in c["text"]           # the advice still goes when the offer changes
    assert c["open"] is True and c["words"] == "Never publish without asking me" and c["sameFold"] and c["sameTeach"]
    r = got["restored"]
    assert HINT in r["text"] and GONE not in r["text"]
    assert r["open"] is True and r["words"] == "Never publish without asking me" and r["sameTeach"]


@needs_node
def test_a_keystroke_that_changes_nothing_leaves_the_advice_node_alone():       # must-refuse: no redraw without a change
    got = run(stub(answers((YES, OFFER))) + OPEN + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const view = moved.VIEWS.test(), box = offerBox(view);
  type(box, %s);
  const a0 = adviceSlot(view).children[0];
  type(box, "  " + %s + "  ");                                // spaces round it: not a change
  report({ same: adviceSlot(view).children[0] === a0, hint: flowOf(view).includes(%s) });
});
""" % (json.dumps(YES), json.dumps(OFFER), json.dumps(OFFER), json.dumps(OFFER), json.dumps(HINT)))
    assert got["same"] is True and got["hint"] is True


@needs_node
def test_a_reading_made_with_no_offer_is_not_touched_by_typing():             # must-refuse: no offer made it, none is missing
    msg = "Publish the release tonight."
    got = run(stub(answers((msg, ""))) + OPEN + """
return moved.tryMessage(%s, "", "helper", "").then(() => {
  const view = moved.VIEWS.test(), box = offerBox(view);
  const a0 = adviceSlot(view).children[0];
  type(box, "Shall I delete it?");
  report({ same: adviceSlot(view).children[0] === a0, text: flowOf(view) });
});
""" % json.dumps(msg))
    assert got["same"] is True and "appear to say go" in got["text"] and GONE not in got["text"]


@needs_node
def test_typing_before_any_reading_is_drawn_does_nothing_and_does_not_throw():   # must-pass: no slot, no reading
    got = run(stub({}) + OPEN + """
const view = moved.VIEWS.test(), box = offerBox(view);
type(box, "Shall I publish it?");
report({ slot: adviceSlot(view) === null, offer: moved.S.offerBox });
""")
    assert got["slot"] is True and got["offer"] == "Shall I publish it?"


@needs_node
def test_the_keystroke_does_not_draw_the_whole_flow_again():                    # pins the cause: no fill of the flow
    got = run(stub(answers((YES, OFFER))) + OPEN + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const view = moved.VIEWS.test(), box = offerBox(view);
  const flow = view.querySelector("#testFlow"), before = flow.children.slice();
  type(box, "Shall I delete the release?");
  report({ sameChildren: flow.children.length === before.length && flow.children.every((c, i) => c === before[i]) });
});
""" % (json.dumps(YES), json.dumps(OFFER)))
    assert got["sameChildren"] is True
