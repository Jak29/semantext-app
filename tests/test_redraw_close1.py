"""The attack on round five of the re-draw (close1): what the person did while an async render waited is theirs.

1  a field the draw replaced had its OLD range put back, and the focus given back, over what the person did in the new
   field the page showed during the wait (D21 x D25); the next key replaced other characters.
2  an unkeyed field was found again at its old path in ANOTHER row whose empty box read the same; the reply landed there.
3  words the person released or replaced came back when the place was drawn twice more in the same wait (D22's takeover).
4  a render that never settled was never dropped: its held words came back much later, or on another place.
5  a scroll the person made in the new keyed text box during the wait was undone at the finish.

The cases are the attacker's own, copied whole into tests/redraw_close1 with the plug-in modules they draw. Each must-pass
has its must-refuse (the untouched control) beside it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")
HERE = Path(__file__).with_name("redraw_close1")


def case(name: str):
    return run((HERE / f"{name}.js").read_text(encoding="utf-8"), plugins=HERE / "plugins")


@needs_node
def test_what_the_person_did_in_a_replaced_field_during_the_wait_is_kept():                          # finding 1
    got = case("c1_field_async_person")
    assert got["summary"] == {"personCases": 10, "PERSON_UNDONE": 0, "nextKeyElsewhere": 0}
    for name, c in got["out"].items():
        if name.startswith("control_untouched"):                                    # must still pass: D21, nobody touched it
            assert c["verdict"] == "kept" and c["focused"] is True, (name, c)
        elif "verdict" in c:
            assert c["verdict"] == "PERSON_KEPT", (name, c)


@needs_node
def test_a_focus_is_not_given_back_to_a_field_the_person_left_for_the_pages_words():                  # finding 1, c13
    got = case("c13_focus_after_wait")
    for s in ("_real", "_quiet"):
        assert got["personClickedOnThePagesWords" + s]["focusAfterTheFinish"] == "nothing"
        assert got["control_personWentToAnotherControl" + s]["focusAfterTheFinish"] == "the button"
        untouched = got["control_untouched" + s]                                    # must still pass: given back with its range
        assert untouched["focusAfterTheFinish"] == "the field" and untouched["fieldRange"] == [2, 7, "forward"]


@needs_node
def test_an_unkeyed_field_is_never_found_again_in_another_row():                                       # finding 2
    got = case("c2_unkeyed_newest_first")
    assert got["summary"]["OTHER_TICKET"] == 0
    out = got["out"]
    assert out["control_sameTickets_real"]["verdict"] == "SAME_TICKET"              # must still pass: the same rows, same row
    assert out["control_sameTickets_quiet"]["verdict"] == "SAME_TICKET"
    for name in ("reply_newTicketOnTop", "reply_ticketAboveClosed", "reply_resorted"):
        assert out[name]["verdict"] == "letGo", (name, out[name])


@needs_node
def test_a_fuzz_of_rows_moved_under_an_unkeyed_field_never_lands_on_another_row():                    # finding 2, a2_fuzz
    tally = case("a2_fuzz")["tally"]
    assert not any("OTHER" in k for k in tally), tally
    assert tally.get("same/SAME_ROW", 0) > 0, tally                                 # must still pass


@needs_node
def test_words_the_person_released_or_replaced_never_come_back_after_more_draws():                    # finding 3
    got = case("c3_takeover_sequences")
    assert "OLD_BACK" not in got["tally"] and "OTHER" not in got["tally"], got["tally"]
    for more in (1, 2, 3):
        assert got["out"][f"nothing_{more}more"]["verdict"] == "kept"               # must still pass: the page's own damage
        assert got["out"][f"other_{more}more"]["verdict"] == "PERSONS"


@needs_node
def test_a_fuzz_of_takeovers_brings_no_old_words_back():                                                # finding 3, a3_fuzz
    tally = case("a3_fuzz")["tally"]
    assert not any("OLD" in k or "OTHER" in k for k in tally), tally
    assert any(k.startswith("nothing/") and k.endswith("/kept") for k in tally), tally   # must still pass


@needs_node
def test_a_render_that_never_settles_holds_nothing_for_later_or_for_another_place():                  # finding 4
    got = case("c4_hung_render")
    for k in ("hung_A_samePlaceLater", "hung_B_otherPlace", "control_settles_A_samePlaceLater", "control_settles_B_otherPlace"):
        assert got[k]["verdict"] == "nothing_selected", (k, got[k])
    assert got["control_settles_A_samePlaceLater"]["afterThatRead"] == "the printer"   # must still pass: a settling draw keeps it


@needs_node
def test_a_scroll_the_person_made_in_the_new_box_during_the_wait_is_kept():                            # finding 5
    got = case("c7_textarea_scroll")
    assert got["scrolledOnWhileItWaited"]["verdict"] == "PERSON_KEPT"
    assert got["control_untouched"]["verdict"] == "kept"                            # must still pass: put back at 500
    # The stated limit: scrolled to the very top of a new box reads as untouched (the state is the same), and is put back.
    assert got["scrolledBackToTheTop"]["afterTheFinish"] == 500
