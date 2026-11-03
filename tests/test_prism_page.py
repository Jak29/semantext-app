"""Prism, the home of the page (1.6.2): the illustrated reading and the five bands of your spectrum.

Drawn in node (tests/v2_dom.js through tests/v2_node.py) with the page's own modules, as test_one_page.py draws.
"""
from __future__ import annotations

import re

import pytest

from v2_node import NODE, run

needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRAW = """
applyFrame({ name: null, word: null, waiting: %d, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const place = document.getElementById("place");
  const links = place.all((e) => e.tagName === "A").map((a) => [a.getAttribute("href"), a.textContent]);
  report({ text: place.textContent, links });
});
"""


@needs_node
def test_prism_reads_the_example_message_and_says_it_is_an_illustration():
    got = run(DRAW % 0)
    for kind in ("QUESTION", "SUGGESTION", "TIME", "YOUR WORD"):                       # "Could we maybe ship ... later?"
        assert kind in got["text"], kind
    assert "INSTRUCTION" not in got["text"]                                             # must-refuse: no false fallback
    assert "An illustration of how Semantext reads" in got["text"]
    assert "Semantext sends nothing you type here" in got["text"]                      # P4's wording


@needs_node
@pytest.mark.parametrize("waiting", [0, 3])
def test_the_five_bands_open_their_places_and_waiting_carries_the_count(waiting):
    got = run(DRAW % waiting)
    hrefs = [h for h, _ in got["links"]]
    assert hrefs == ["#rules", "#map/~agents", "#work", "#record", "#waiting"]
    waiting_text = got["links"][-1][1]
    assert waiting_text.startswith("Waiting on you" + str(waiting))


@needs_node
def test_with_nothing_read_the_waiting_band_says_so():   # must-refuse (Koinos P1): never a false "0, nothing"
    got = run("""
location.hash = "#prism";
route();
return settled().then(() => {
  const band = document.getElementById("place").querySelector(".band-waiting");
  report([band.querySelector(".band-count").textContent, band.getAttribute("aria-label")]);
});
""")
    assert got == ["…", "Waiting on you, not read yet"]


@needs_node
def test_typing_reading_and_the_presets_send_and_keep_nothing():   # must-refuse (Koinos P3)
    got = run("""
const sent = [];
globalThis.fetch = (path, opts) => { sent.push(String(path)); return new Promise(() => {}); };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => {
  const before = [sent.length, location.hash, document.title];
  const place = document.getElementById("place");
  const input = place.querySelector("input.prism-input");
  input.value = "MARKER-7f3a delete everything";
  place.querySelector("form.prism-form").dispatch("submit");
  for (const b of place.all((e) => e.tagName === "BUTTON" && e.classList.contains("chip"))) b.click();
  report({ before, after: [sent.length, location.hash, document.title], sent,
           input: [input.getAttribute("spellcheck"), input.getAttribute("autocomplete")] });
});
""")
    assert got["after"] == got["before"]                                                 # no request, address or title
    assert not [p for p in got["sent"] if "MARKER" in p]
    assert got["input"] == ["false", "off"]                                             # P4


@needs_node
def test_the_prism_page_sends_nothing():   # must-refuse: the reading is drawn here, never asked of a server
    got = run("""
const sent = [];
globalThis.fetch = (path, opts) => { sent.push([path, (opts && opts.method) || "GET"]); return new Promise(() => {}); };
applyFrame({ name: null, word: null, waiting: 0, problems: [], outside: [] });
location.hash = "#prism";
route();
return settled().then(() => report(sent));
""")
    assert all(method == "GET" for _, method in got)                                   # reads only, as every place
    assert not [p for p, _ in got if re.search(r"read|card|model|ask", p)]             # nothing about the message
