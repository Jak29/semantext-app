"""Try a message and the offer box (R9): the go-hint made from an offer is drawn only while that offer is in the box.

A bare yes answers the agent's last offer, so the reader's "your words appear to say go: confirm" for "Yes" is made from
the offer in the second box. After the box is emptied (or the person comes back to the view, which draws it empty) the
reading still stood beside words that were not in the boxes. It is cleared at once when the offer it was made from is no
longer in the box, and drawn again when the offer is put back. Drawn in node (tests/v2_dom.js), as test_reader_fixes.py
does. Each behaviour has a must-pass and a must-refuse beside it.
"""
from __future__ import annotations

import json

import pytest

from semantext import reading
from test_one_page import WORLD
from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

YES, OFFER = "Yes", "Shall I publish the release?"
HINT = "your words appear to say go: confirm"
GONE = "The offer this was read with is no longer in the box"


def stub(by: dict) -> str:
    """A page whose /api/read answers from `by` ({"message|offer": answer}) and whose other requests give a plain quick reading."""
    return WORLD + """
const BY = %s;
globalThis.fetch = (path, opts) => {
  const b = opts && opts.body ? JSON.parse(opts.body) : null;
  if (path === "/api/read") return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(BY[b.message + "|" + (b.offer || "")]) });
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ agent: "helper", words: "own", basis: "text", environment: "default",
    form: "full", layers: [], bytes: 1, left_out: 0, answers: [], waiting: [], reading: { readings: [], decisions: [] }, text: "card" }) });
};
const offerBox = (view) => view.querySelector('[name="offer"]');
const flowOf = (view) => view.querySelector("#testFlow").textContent;
""" % json.dumps(by, ensure_ascii=False)


def answers(*pairs):
    return {f"{m}|{o}": {"ok": True, **reading.report(m, offer=o or None)} for m, o in pairs}


def test_the_reader_itself_gives_the_hint_for_a_yes_with_the_offer_and_none_without():   # the premise of the page tests
    with_offer = reading.report(YES, offer=OFFER)
    assert [a["covers"] for a in with_offer["advice"]] == [True] and with_offer["advice"][0]["act"] == "publish"
    assert reading.report(YES)["advice"] == []


@needs_node
def test_coming_back_to_the_view_clears_the_hint_whose_offer_is_not_in_the_box():   # fails on 4756135: the hint stays
    got = run(stub(answers((YES, OFFER))) + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const drawn = document.getElementById("testFlow").textContent;
  const view = moved.VIEWS.test();                       // leave and come back: the view is drawn again, the offer box empty
  report({ drawn, back: flowOf(view), offer: offerBox(view).value });
});
""" % (json.dumps(YES), json.dumps(OFFER)))
    assert HINT in got["drawn"]                          # must-pass: the control drew the hint while the offer was in the box
    assert got["offer"] == ""
    assert HINT not in got["back"] and "appear to say go" not in got["back"] and GONE in got["back"]


@needs_node
def test_emptying_the_offer_box_clears_the_hint_and_putting_the_offer_back_draws_it_again():
    got = run(stub(answers((YES, OFFER))) + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const view = moved.VIEWS.test();
  const box = offerBox(view);
  const steps = { back: flowOf(view) };
  box.value = %s; box.dispatch("input"); steps.restored = flowOf(view);                 // the offer typed back: the hint is its own again
  box.value = "  " + %s + "  "; box.dispatch("input"); steps.spaced = flowOf(view);    // spaces round it are not a change
  box.value = ""; box.dispatch("input"); steps.emptied = flowOf(view);
  box.value = "Shall I delete the release?"; box.dispatch("input"); steps.other = flowOf(view);   // a different offer is not this one
  report(steps);
});
""" % (json.dumps(YES), json.dumps(OFFER), json.dumps(OFFER), json.dumps(OFFER)))
    assert HINT not in got["back"]
    assert HINT in got["restored"] and GONE not in got["restored"]
    assert HINT in got["spaced"]
    assert HINT not in got["emptied"] and GONE in got["emptied"]
    assert HINT not in got["other"] and GONE in got["other"]


@needs_node
def test_a_reading_made_with_no_offer_keeps_its_hint_when_the_box_is_empty():   # must-refuse: no offer made it, none is missing
    msg = "Publish the release tonight."
    got = run(stub(answers((msg, ""))) + """
return moved.tryMessage(%s, "", "helper", "").then(() => {
  const drawn = document.getElementById("testFlow").textContent;
  const view = moved.VIEWS.test();
  report({ drawn, back: flowOf(view) });
});
""" % json.dumps(msg))
    assert "appear to say go" in got["drawn"]
    assert "appear to say go" in got["back"] and GONE not in got["back"]


@needs_node
def test_the_clause_chips_and_the_message_stay_when_the_hint_is_cleared():   # must-pass: only what the offer made is withdrawn
    got = run(stub(answers((YES, OFFER))) + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const view = moved.VIEWS.test();
  report({ back: flowOf(view), message: view.querySelector("textarea").textContent });
});
""" % (json.dumps(YES), json.dumps(OFFER)))
    assert got["message"] == YES and "Clause by clause" in got["back"] and "Yes" in got["back"]


@needs_node
def test_a_new_ask_with_an_offer_draws_its_hint_and_a_new_ask_without_clears_it():
    got = run(stub(answers((YES, OFFER), (YES, ""))) + """
return moved.tryMessage(%s, "", "helper", %s).then(() => {
  const withOffer = document.getElementById("testFlow").textContent;
  return moved.tryMessage(%s, "", "helper", "").then(() => report({ withOffer, without: document.getElementById("testFlow").textContent }));
});
""" % (json.dumps(YES), json.dumps(OFFER), json.dumps(YES)))
    assert HINT in got["withOffer"]
    assert HINT not in got["without"] and GONE not in got["without"] and "The words name no act" in got["without"]
