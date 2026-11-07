"""The proxy's key-shape check in windows (Koinos's margin after X1, 3 November 2026).

A held call's input is checked whole, but one search over 4 MiB held the GIL for about 2 s. The check now runs in
overlapping windows. Must-pass: a key anywhere, including across a window's edge, is still found. Must-refuse: no
single stretch holds the other threads for long.
"""
from __future__ import annotations

import threading
import time

import pytest

from semantext import proxy

KEY = "sk-" + "A1b2C3d4E5f6G7h8J9k0"
W, O = proxy.SCAN_WINDOW, proxy.SCAN_OVERLAP


@pytest.mark.parametrize("at", [0, W - O - 5, W - 10, W - 1, W, 3 * (W - O) - 7, 4 * 1024 * 1024 - len(KEY)],
                         ids=["start", "inside the overlap", "across the first edge", "starting at the edge's last",
                              "just past the first window", "across a later edge", "at the end of 4 MiB"])
def test_a_key_anywhere_in_a_long_input_is_found(at):                          # must-pass: nothing skipped
    text = "a" * at + KEY + "a" * max(0, 4 * 1024 * 1024 - at - len(KEY))
    assert proxy._secret(text)


LONG = {
    "URL password of 3,000": "https://u:" + "p" * 3000 + "@h",
    "URL user of 2,000": "https://" + "u" * 2000 + ":pw@h",
    "JWT payload of 6,000": "eyJ" + "a" * 20 + "." + "b" * 6000 + "." + "c" * 40,
    "PEM label of 100": "-----BEGIN " + "A" * 100 + "-----",
    "200 spaces around =": "password" + " " * 200 + "=" + " " * 10 + "hunter22x",
}


EDGES = {"across the first edge": W, "across the second edge": (W - O) + W, "across the third edge": 2 * (W - O) + W}


def _across(key, cut):
    at = cut - len(key) // 2
    return "a " * (at // 2) + ("a" if at % 2 else "") + key + " a" * ((4 * W - at - len(key)) // 2)


@pytest.mark.parametrize("edge", list(EDGES))
@pytest.mark.parametrize("key,found", [
    ("https://u:" + "p" * 4096 + "@h", True), ("https://u:" + "p" * 4097 + "@h", False),
    ("https://" + "u" * 4096 + ":pw@h", True), ("https://" + "u" * 4097 + ":pw@h", False),
    ("eyJ" + "a" * 20 + "." + "b" * 8192 + "." + "c" * 40, True), ("eyJ" + "a" * 20 + "." + "b" * 8193 + "." + "c" * 40, False),
    ("-----BEGIN " + "A" * 128 + "-----", True), ("-----BEGIN " + "A" * 129 + "-----", False),
], ids=["password 4096", "password 4097", "user 4096", "user 4097", "JWT 8192", "JWT 8193", "label 128", "label 129"])
def test_the_bound_is_pinned_from_both_sides(key, found, edge):              # the stated limit (Orithises)
    assert proxy._secret(_across(key, EDGES[edge])) is found


@pytest.mark.parametrize("name", list(LONG))
@pytest.mark.parametrize("edge", list(EDGES))
def test_a_long_key_across_a_window_edge_is_found(name, edge):                 # must-pass (Orithises F1)
    key = LONG[name]
    cut = EDGES[edge]
    at = cut - len(key) // 2
    text = "a " * (at // 2) + ("a" if at % 2 else "") + key + " a" * ((4 * W - at - len(key)) // 2)
    assert proxy.SECRET.search(text)                                           # the single search finds it
    assert proxy._secret(text), name                                          # and so does the windowed one


def test_the_bounded_pattern_still_needs_every_swap():                        # must-refuse a silent drift
    with pytest.raises(RuntimeError):
        proxy._bounded(proxy.SECRET.pattern.replace("-----BEGIN ", "-----START "))


def test_a_long_plain_input_is_not_a_key():                                    # must-refuse a false key
    assert not proxy._secret("a" * (4 * 1024 * 1024))


def test_other_threads_run_while_4_mib_is_checked():                          # must-refuse the stall
    ticks, stop = [], threading.Event()

    def other():
        while not stop.is_set():
            ticks.append(time.perf_counter())
            time.sleep(0.005)

    t = threading.Thread(target=other, daemon=True)
    t.start()
    time.sleep(0.05)
    start = time.perf_counter()
    assert not proxy._secret("a1" * (2 * 1024 * 1024))
    took = time.perf_counter() - start
    stop.set()
    t.join()
    during = [x for x in ticks if start <= x <= start + took]
    gaps = [b - a for a, b in zip(during, during[1:])]
    assert took < 5.0
    assert len(during) >= 3 and max(gaps) < 0.5                               # the other thread kept running
