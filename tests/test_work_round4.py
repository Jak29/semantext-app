"""Review round 4 of the Work system: the findings at 0e81e3d, each a must-refuse with its must-pass partner."""
import hashlib
import json
from datetime import timedelta

import pytest

from semantext.sources import work
from work_kit import NOW, P, bound, make, new, person, plant, say, stamp, transcripts


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def page(w):
    return work.load({"_home": str(w.home), "transcripts": [str(transcripts(w.home))]}, now=NOW, projects={P, "atlas"})


def act(ident, what, span, frm=None, **ev):
    rec = {"event": "person_act", "id": ident, "act": what, "who": "person", "assurance": "bound",
           "evidence": {"session": "s1", "turn": "t9", "turn_at": stamp(NOW - timedelta(seconds=60)),
                        "line": f"{ident} {what}", **ev, **({"span": span} if span is not None else {})}}
    if frm:
        rec["from"] = frm
    return rec


# ---- high 1: a span offset no file position holds is unverified, and never stops a read ------------------------------
@pytest.mark.parametrize("move_head", [True, False], ids=["chained", "off-chain"])
@pytest.mark.parametrize("offset", [2 ** 63, 2 ** 70])
def test_an_absurd_span_offset_is_unverified_and_never_raises(w, move_head, offset):
    ident = new(w, "alpha")
    say(w, "hello")
    path = transcripts(w.home) / "s1.jsonl"
    plant(w, act(ident, "park", {"path": str(path), "offset": offset, "length": 10, "sha256": "0" * 64}),
          move_head=move_head)
    st = w.state()                                                          # never raises
    row = [e for e in st["events"] if e["event"] == "person_act"][-1]
    assert not row["applied"] and st["items"][ident]["state"] == "backlog"
    assert next(i for i in page(w)["items"] if i["id"] == ident)["state"] == "backlog"
    other = new(w, "alpha")                                                 # the writer still writes
    assert w.state()["items"][other]["state"] == "backlog"


def test_partner_a_real_span_is_still_read(w):
    ident = new(w, "alpha")
    person(w, ident, "park")
    assert w.state()["items"][ident]["state"] == "parked"


# ---- high 2a: an off-chain create never moves the item numbers, and is never an item ---------------------------------
def test_an_off_chain_create_does_not_move_minted_and_is_never_shown(w):
    first = new(w, "alpha")
    plant(w, {"event": "create", "id": f"W-{P}-999999", "project": P, "title": "x", "who": "alpha",
              "assurance": "bound"}, move_head=False)
    st = w.state()
    assert st["minted"][P] == 1 and f"W-{P}-999999" not in st["items"]
    assert f"W-{P}-999999" not in [i["id"] for i in page(w)["items"]]
    assert new(w, "alpha") == f"W-{P}-2"                                    # the next number, never STORE_FULL


def test_partner_an_on_chain_create_counts_for_minting_even_when_not_applied(w):
    new(w, "alpha")
    # on the chain, refused by the table (an actor no writer stamps), yet its number is used: never minted twice
    plant(w, {"event": "create", "id": f"W-{P}-5", "project": P, "title": "x", "who": "9bad", "assurance": "bound"})
    st = w.state()
    assert f"W-{P}-5" not in st["items"] and st["minted"][P] == 5
    assert new(w, "alpha") == f"W-{P}-6"
