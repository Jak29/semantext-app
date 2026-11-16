"""What the page says when its own inbox is longer than it draws (sources/own_inbox.py), drawn in node with the page's own
modules (tests/v2_dom.js through tests/v2_node.py), as test_prism_page.py draws.

Must-pass: a short inbox gets no "more" line. Must-refuse: the cap is never silent (a plain "N more" line, and the counts
are of the whole inbox), and a command that was drawn cut is not offered to copy.
"""
from __future__ import annotations

import pytest

from v2_node import NODE, run
from tests.test_prism_page import CARD, OPEN

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

PLACE = """
applyFrame({ name: null, word: null, waiting: %d, problems: [], outside: [] });
%s
location.hash = "#waiting";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  report({ text: place.textContent, say: document.getElementById("bar-place").textContent, more: place.all((e) => (e.getAttribute("data-more") || "") !== "").map((e) => [e.getAttribute("data-more"), e.textContent]) });
});
"""


def own(n, state="waiting", **extra):
    fields = ", ".join(f"{k}: {v}" for k, v in extra.items())
    return ('{ key: "agent/#%d", seat: "agent", id: "#%d", number: %d, kind: "decision", title: "Request %d", why: "because", '
            'question: "Which?", options: [], choices: [], state: "%s", asks: "agent", acts: "agent", own_inbox: true, '
            'at: "2026-10-01T10:00:00Z", notes: [], cut: [] %s}' % (n, n, n, n, state, ", " + fields if fields else ""))


@needs_node
def test_a_long_own_inbox_says_how_many_more_wait():
    data = ('S.data.waiting = { off: false, cards: [%s, %s], seats: ["agent"], more: { waiting: 148, parked: 0, closed: 0 }, '
            'machine_inbox: [], machine_more: {}, change_records: [], changes: {} };' % (own(1), own(2)))
    got = run(PLACE % (150, data))
    assert ["waiting", "148 more waiting requests not drawn here: the newest are shown, and the older ones appear as you "
            "answer or park these. All of them are in your inbox file."] in got["more"]
    assert "150 cards wait for your word" in got["say"]                          # the sentence counts the whole inbox, not the drawn


@needs_node
def test_a_short_own_inbox_has_no_more_line():                                       # must-pass
    data = ('S.data.waiting = { off: false, cards: [%s], seats: ["agent"], more: { waiting: 0, parked: 0, closed: 0 }, '
            'machine_inbox: [], machine_more: {}, change_records: [], changes: {} };' % own(1))
    got = run(PLACE % (1, data))
    assert got["more"] == [] and "1 card waits for your word" in got["say"]


@needs_node
def test_one_more_is_said_in_the_singular():
    data = ('S.data.waiting = { off: false, cards: [%s], seats: ["agent"], more: { waiting: 1, parked: 0, closed: 0 }, '
            'machine_inbox: [], machine_more: {}, change_records: [], changes: {} };' % own(1))
    got = run(PLACE % (2, data))
    assert got["more"][0][1].startswith("1 more waiting request not drawn here")


@needs_node
def test_the_machines_own_inbox_beside_a_setup_says_its_count_and_its_more():
    machine = own(1).replace('"agent/#1"', '"machine/agent/#1"')
    data = ('S.data.waiting = { off: false, cards: [], seats: [], more: {}, machine_inbox: [%s], '
            'machine_more: { waiting: 99, parked: 0 }, change_records: [], changes: {} };' % machine)
    got = run(PLACE % (100, data))
    assert "This machine's own inbox · 100 waiting" in got["text"]
    assert any(k == "waiting" and t.startswith("99 more waiting requests") for k, t in got["more"])


@needs_node
def test_the_home_band_says_it_too():
    data = ('S.data.waiting = { cards: [%s], seats: [], more: { waiting: 41 }, machine_inbox: [%s], '
            'machine_more: { waiting: 7 } };' % (CARD % "waiting", (CARD % "waiting").replace("A-1", "M-1")))
    got = run(OPEN % (50, data))
    assert "41 more waiting requests not drawn here" in got["text"] and "7 more waiting requests not drawn here" in got["text"]
    assert "This machine's own inbox · 8 waiting" in got["text"]


@needs_node
def test_a_card_drawn_cut_says_so_and_a_cut_command_is_not_offered_to_copy():      # must-refuse
    got = run("""
const base = { key: "agent/#3", seat: "agent", id: "#3", number: 3, kind: "command", title: "Run it", why: "because",
  command: "echo hi", does: "d", undo: "u", cwd: "", state: "waiting", asks: "agent", acts: "agent", own_inbox: true,
  at: "2026-10-01T10:00:00Z", notes: [], choices: [{ label: "Done", choice: "done" }], flags: [] };
const copies = (n) => n.all((e) => (e.getAttribute("data-k") || "").startsWith("copy:")).length;
const whole = cardNode(Object.assign({}, base, { cut: [] }));
const cutOther = cardNode(Object.assign({}, base, { cut: ["why"] }));
const cutCommand = cardNode(Object.assign({}, base, { cut: ["command", "why"] }));
report({ wholeCopies: copies(whole), wholeSaid: whole.textContent.includes("longer than this page draws"),
  otherCopies: copies(cutOther), otherSaid: cutOther.textContent,
  commandCopies: copies(cutCommand), commandSaid: cutCommand.textContent });
""")
    assert got["wholeCopies"] == 1 and got["wholeSaid"] is False                      # must-pass: a whole card is as it was
    assert got["otherCopies"] == 1 and "(why) is longer than this page draws" in got["otherSaid"]
    assert "The whole of it is in your inbox file." in got["otherSaid"]
    assert got["commandCopies"] == 0 and "Its command is not offered to copy" in got["commandSaid"]
