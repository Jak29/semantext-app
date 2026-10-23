"""The Waiting place's reader, on synthetic files in tmp_path.

Every check has a must-pass arm and a must-refuse arm: a line the reader has to use, and a planted defect it has to
report. The defects are the ones the reading rules name: a line that is not JSON, a missing field, an id used twice, a
closing that names no request, a parking it does not know, and a card that has run but would show as waiting. The rest
pin the reader to the way the person's own inbox reads the same files: a file that is not all UTF-8 is not read, a
number out of float range is not JSON, a run record must be a whole one, a line is measured after it is trimmed, and
only the seats in the configured group are read.
"""
import ast
import builtins
import contextlib
import io
import json
import os
from pathlib import Path

import pytest

from semantext.sources import MAX_LINE, cards, load_config
from semantext.sources.cards import FILE, FILE_CAP

HOMES = {"Alder": "alder", "Birch": "birch", "Cedar": "teams/cedar"}   # each agent's home, under the base folder
AT = "2026-10-01T10:00:00+01:00"
BIG = "1" + "0" * 400   # a whole number far beyond any float
HALF = '"\\ud800"'      # JSON text for half of a surrogate pair


class World:
    """A base folder holding three agents' homes, a seats file and an inbox folder, all under tmp_path."""

    def __init__(self, root: Path):
        self.root, self.base, self.inbox, self.seats = root, root / "base", root / "inbox", root / "seats.json"
        self.inbox.mkdir()
        for home in HOMES.values():
            (self.base / home).mkdir(parents=True)
        self.write_seats({n: {"names": [n], "groups": ["posters"], "home": h} for n, h in HOMES.items()})

    def write_seats(self, table: dict, base: Path | None = None) -> None:
        self.seats.write_text(json.dumps({"base": str(base or self.base), "seats": table}), encoding="utf-8")

    def cfg(self, group: str | None = None) -> dict:
        cfg = {"seats": str(self.seats), "inbox": str(self.inbox)}
        return {**cfg, "group": group} if group is not None else cfg

    def file(self, seat: str) -> Path:
        return self.base / HOMES[seat] / FILE

    def put(self, seat: str, *lines, bom: bool = False, eol: str = "\n") -> None:
        self.file(seat).write_bytes(lines_of(lines, bom, eol))

    def put_bytes(self, seat: str, data: bytes) -> None:
        self.file(seat).write_bytes(data)

    def runs(self, *lines, bom: bool = False) -> None:
        (self.inbox / "runs.jsonl").write_bytes(lines_of(lines, bom, "\n"))

    def runs_bytes(self, data: bytes) -> None:
        (self.inbox / "runs.jsonl").write_bytes(data)

    def parked(self, *lines) -> None:
        (self.inbox / "parked.jsonl").write_bytes(lines_of(lines, False, "\n"))

    def parked_bytes(self, data: bytes) -> None:
        (self.inbox / "parked.jsonl").write_bytes(data)

    def load(self, group: str | None = None) -> dict:
        return cards.load(self.cfg(group))


def lines_of(lines, bom: bool, eol: str) -> bytes:
    """A dict is written as JSON, a string as it is."""
    text = "".join((x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)) + eol for x in lines)
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def ask(id_: str, **kw) -> dict:
    return {"id": id_, "at": AT, "kind": "decision", "title": f"Title {id_}", "why": "because",
            "question": "Which one?", "options": ["first", "second"], **kw}


def cmd(id_: str, **kw) -> dict:
    return {"id": id_, "at": AT, "kind": "command", "title": f"Title {id_}", "why": "because",
            "command": "Write-Output 1", "does": "prints one", "undo": "nothing to undo", **kw}


def close(id_: str, how: str = "answered") -> dict:
    return {"close": id_, "at": "2026-10-01T11:00:00+01:00", "how": how}


def run_line(seat: str, id_: str, **kw) -> dict:
    return {"seat": seat, "id": id_, "started": "2026-10-02T09:00:00Z", "finished": "2026-10-02T09:00:05Z", "exit": 0,
            "timed_out": False, "stdout": "hi", "stderr": "", "command": "Write-Output 1", **kw}


def park(seat: str, id_: str, at: str = "2026-10-03T08:00:00Z") -> dict:
    return {"event": "park", "seat": seat, "id": id_, "at": at, "by": "the person"}


def back(seat: str, id_: str, at: str = "2026-10-03T09:00:00Z") -> dict:
    return {"event": "back", "seat": seat, "id": id_, "at": at, "by": "the person"}


def without(d: dict, *keys: str) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def states(out: dict) -> dict:
    return {(c["seat"], c["id"]): c["state"] for c in out["cards"]}


def text_of(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)


def with_extra(card: dict, text: str) -> str:
    """The card's line with one more field written as raw JSON text."""
    return text_of(card)[:-1] + ', "extra": ' + text + "}"


# ---------------------------------------------------------------- a source with a key missing is off
def test_a_missing_key_turns_the_source_off(world):
    for cfg, missing in (({}, ["seats", "inbox"]), ({"seats": "x"}, ["inbox"]), ({"inbox": "x"}, ["seats"]),
                         ({"seats": "", "inbox": "x"}, ["seats"])):
        out = cards.load(cfg)
        assert out["off"] is True and out["missing"] == missing and out["problems"] == []
    assert world.load()["off"] is False   # must pass: both keys given


def test_the_config_file_feeds_the_reader(world, tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({**world.cfg(), "name": "Mine", "register": "elsewhere.jsonl"}), encoding="utf-8")
    world.put("Alder", ask("A-1"))
    assert [c["id"] for c in cards.load(load_config(path))["cards"]] == ["A-1"]


# ---------------------------------------------------------------- a card is read field for field
def test_a_decision_and_a_command_are_read_field_for_field(world):
    d = ask("A-1", title="  Pick one  ", options=["first", " second "], recommend=2, seat="Cedar", score=1.5)
    c = cmd("A-2", cwd="C:/work")
    world.put("Alder", "", d, c)   # a blank line first, so the cards are lines 2 and 3
    out = world.load()
    a, b = out["cards"]
    assert (a["seat"], a["id"], a["kind"], a["title"], a["why"], a["question"], a["options"], a["at"], a["line"]) == (
        "Alder", "A-1", "decision", "Pick one", "because", "Which one?", ["first", " second "], AT, 2)
    assert a["command"] is a["does"] is a["undo"] is a["cwd"] is None
    assert a["raw"] == json.dumps(d, ensure_ascii=False)
    assert (b["kind"], b["command"], b["does"], b["undo"], b["cwd"], b["question"], b["options"], b["line"]) == (
        "command", "Write-Output 1", "prints one", "nothing to undo", "C:/work", None, [], 3)
    assert a["state"] == b["state"] == "waiting" and a["closing"] is a["run"] is a["parked_at"] is None
    assert out["problems"] == []


def test_the_seat_is_the_home_folder_never_a_field_and_an_id_may_repeat_across_agents(world):
    world.put("Alder", ask("X-1", seat="Birch", asks="Birch"))
    world.put("Birch", ask("X-1", title="Birch's own"))
    out = world.load()
    assert sorted((c["seat"], c["title"]) for c in out["cards"]) == [("Alder", "Title X-1"), ("Birch", "Birch's own")]
    assert out["problems"] == []


def test_who_asks_and_who_acts_come_from_the_file_with_their_basis(world):
    world.put("Cedar", ask("C-1", acts="Alder", asks="Birch", seat="Birch"))
    (c,) = world.load()["cards"]
    assert (c["asks"], c["acts"]) == ("Cedar", "Cedar")
    assert "home folder" in c["asks_basis"] and "filed by that agent" in c["acts_basis"]


@pytest.mark.parametrize("bom,eol", [(False, "\n"), (True, "\n"), (True, "\r\n"), (False, "\r\n")])
def test_a_byte_order_mark_and_windows_line_ends_do_not_spoil_a_line(world, bom, eol):
    world.put("Alder", ask("A-1"), "   ", ask("A-2"), bom=bom, eol=eol)
    out = world.load()
    assert [(c["id"], c["line"]) for c in out["cards"]] == [("A-1", 1), ("A-2", 3)]
    assert out["cards"][0]["raw"] == json.dumps(ask("A-1"), ensure_ascii=False)
    assert out["problems"] == [] and out["seats"][0]["lines"] == 2


def test_a_carriage_return_on_its_own_does_not_end_a_line_and_one_before_a_line_feed_goes_with_it(world):
    one = json.dumps(ask("A-1"))
    world.put_bytes("Alder", (one + "\r" + json.dumps(ask("A-2")) + "\n" + json.dumps(ask("A-3")) + "\r\n").encode())
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-3"]   # must refuse: lines 1 holds two objects, as the inbox sees it
    (p,) = out["problems"]
    assert (p["line"], p["kind"]) == (1, "bad json") and out["cards"][0]["line"] == 2
    assert out["cards"][0]["raw"] == json.dumps(ask("A-3"))   # the carriage return of a CRLF is not part of the line


def test_a_line_keeps_its_padding_in_raw_but_not_in_the_card(world):
    world.put_bytes("Alder", ("\u00a0 " + json.dumps(ask("A-1")) + " \t\u3000\n").encode())
    (c,) = world.load()["cards"]
    assert c["raw"] == "\u00a0 " + json.dumps(ask("A-1")) + " \t\u3000" and c["title"] == "Title A-1"


def test_a_line_of_unicode_blanks_is_skipped_like_the_inbox_trims_it(world):
    world.put("Alder", "\u00a0\u2003", "\u0085\u3000\u200a", ask("A-1"), "\u00a0x")
    out = world.load()
    assert [c["line"] for c in out["cards"]] == [3]
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(4, "bad json")]   # must refuse: not blank
    assert out["seats"][0]["lines"] == 2


def test_the_four_separators_that_str_strip_alone_trims_are_not_blank_to_the_inbox(world):
    world.put("Alder", "\x1c\x1d", ask("A-1"), "\x1f")   # must refuse: each is a line that is not JSON
    out = world.load()
    assert [c["line"] for c in out["cards"]] == [2]
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(1, "bad json"), (3, "bad json")]
    assert out["seats"][0]["lines"] == 3


def test_a_text_field_is_trimmed_of_white_space_and_of_nothing_else(world):
    world.put("Alder", ask("A-1", title="\u3000\u00a0Pick one\u2003 "), ask("A-2", title="\x1c"))
    got = {c["id"]: c["title"] for c in world.load()["cards"]}
    assert got == {"A-1": "Pick one", "A-2": "\x1c"}   # a field of only U+001C is text, as to the inbox


# ---------------------------------------------------------------- lines that cannot be used
def test_a_line_over_64_kb_is_a_problem_and_one_at_the_limit_is_read(world):
    pad = "x" * (MAX_LINE - len(json.dumps(ask("A-1", why=""), ensure_ascii=False)))
    at_limit = ask("A-1", why=pad)
    assert len(json.dumps(at_limit, ensure_ascii=False).encode()) == MAX_LINE
    world.put("Alder", at_limit, ask("A-2", why=pad + "x"), ask("A-3"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-1", "A-3"]
    (p,) = out["problems"]
    assert (p["line"], p["kind"]) == (2, "line too long") and out["seats"][0]["refused"] == 1


def padded_to(limit_text: int) -> str:
    """A card's line text of exactly `limit_text` bytes."""
    base = len(text_of(ask("A-1", why="")).encode())
    return text_of(ask("A-1", why="x" * (limit_text - base)))


@pytest.mark.parametrize("before,after,text_bytes,read", [
    pytest.param("", "", MAX_LINE, True, id="must-pass: exactly at the limit"),
    pytest.param(" ", "\t", MAX_LINE, True, id="must-pass: at the limit, with a space before and a tab after"),
    pytest.param("\u3000" * 40, "\u00a0" * 40, MAX_LINE, True, id="must-pass: at the limit, with wide spaces around"),
    pytest.param("", "", MAX_LINE + 1, False, id="must-refuse: one byte over"),
    pytest.param(" ", "\t", MAX_LINE + 1, False, id="must-refuse: one byte over, with padding"),
])
def test_the_64_kb_limit_is_measured_on_the_trimmed_line_in_bytes(world, before, after, text_bytes, read):
    world.put_bytes("Alder", (before + padded_to(text_bytes) + after + "\n").encode())
    out = world.load()
    assert [c["id"] for c in out["cards"]] == (["A-1"] if read else [])
    assert [p["kind"] for p in out["problems"]] == ([] if read else ["line too long"])


def test_the_limit_counts_bytes_not_characters(world):
    base = len(text_of(ask("A-1", why="")).encode())
    pairs, odd = divmod(MAX_LINE - base, 2)   # "e acute" is two bytes: this many fill the line, and an x makes it exact
    exact = ask("A-1", why="\u00e9" * pairs + "x" * odd)
    over = ask("A-1", why="\u00e9" * (pairs + 1) + "x" * odd)
    assert len(text_of(exact).encode()) == MAX_LINE and len(text_of(over).encode()) == MAX_LINE + 2
    assert len(text_of(over)) < MAX_LINE   # more bytes than the limit, fewer characters: only bytes count
    world.put("Alder", exact, over)
    out = world.load()
    assert [c["line"] for c in out["cards"]] == [1] and [(p["line"], p["kind"]) for p in out["problems"]] == [
        (2, "line too long")]


def test_a_line_of_only_white_space_is_blank_however_long(world):
    world.put_bytes("Alder", ("\u3000" * 30000 + "\n" + json.dumps(ask("A-1")) + "\n").encode())   # 90,000 bytes
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-1"] and out["problems"] == []   # must pass: blank, not "too long"
    assert out["seats"][0]["lines"] == 1
    world.put_bytes("Alder", ("x" * 70000 + "\n" + json.dumps(ask("A-1")) + "\n").encode())
    out = world.load()
    assert [p["kind"] for p in out["problems"]] == ["line too long"]   # must refuse: long and not blank


@pytest.mark.parametrize("marks", [0, 1, 2, 5])
def test_every_byte_order_mark_at_the_start_of_a_request_file_is_dropped(world, marks):
    world.put_bytes("Alder", b"\xef\xbb\xbf" * marks + json.dumps(ask("A-1")).encode() + b"\n")
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-1"] and out["problems"] == []


def test_a_byte_order_mark_that_is_not_at_the_start_of_the_file_is_not_dropped(world):
    one = json.dumps(ask("A-1")).encode()
    world.put_bytes("Alder", b" \xef\xbb\xbf" + one + b"\n" + b"\xef\xbb\xbf" + json.dumps(ask("A-2")).encode() + b"\n")
    out = world.load()
    assert out["cards"] == [] and [(p["line"], p["kind"]) for p in out["problems"]] == [
        (1, "bad json"), (2, "bad json")]   # must refuse: after a space, and on the second line


@pytest.mark.parametrize("line,kind", [
    ("{not json", "bad json"), ('{"id": "A-9",', "bad json"), ('{"id": NaN}', "bad json"),
    ('{"id": -Infinity}', "bad json"), ('{"score": 1e999}', "bad json"), ("[" * 20000, "bad json"),
    ("[1, 2]", "not an object"), ('"text"', "not an object"), ("5", "not an object"), ("null", "not an object")])
def test_a_line_that_is_not_a_json_object_is_a_problem(world, line, kind):
    world.put("Alder", ask("A-1"), line, ask("A-2"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-1", "A-2"]   # the good lines around it are still read
    (p,) = out["problems"]
    assert (p["line"], p["kind"], p["source"]) == (2, kind, str(world.file("Alder")))
    assert p["text"].startswith("Alder: ")
    assert (out["seats"][0]["lines"], out["seats"][0]["refused"]) == (3, 1)


def test_half_a_surrogate_pair_is_not_text_and_a_whole_pair_is(world):
    world.put("Alder", with_extra(ask("A-1"), '"\\ud800"'), with_extra(ask("A-2"), '"\\ud83d\\ude00"'))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-2"]   # must pass: the whole pair, an emoji
    (p,) = out["problems"]
    assert (p["line"], p["kind"]) == (1, "bad json") and "surrogate" in p["text"]   # must refuse: half of one


@pytest.mark.parametrize("depth,read", [(2, True), (50, True), (127, True), (128, False), (300, False), (5000, False)])
def test_a_line_nested_deeper_than_the_inbox_reads_is_a_problem(world, depth, read):
    deep = "[" * (depth - 1) + "]" * (depth - 1)   # the card's own object is the first level
    world.put("Alder", with_extra(ask("A-1"), deep))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == (["A-1"] if read else [])
    assert [p["kind"] for p in out["problems"]] == ([] if read else ["bad json"])


# A number is read by the inbox's parser as 64-bit digits and a power of ten, and refused when the float would be
# infinite. Python's parser would take any whole number, so a 400-digit one used to be a card.
@pytest.mark.parametrize("token,read", [
    pytest.param("1" + "0" * 24, True, id="must-pass: a 25-digit whole number, too big for 64 bits but a float holds it"),
    pytest.param("18446744073709551615", True, id="must-pass: the largest 64-bit whole number"),
    pytest.param("18446744073709551616", True, id="must-pass: the next one"),
    pytest.param("1" + "0" * 308, True, id="must-pass: 309 digits, 1e308"),
    pytest.param("-" + "1" + "0" * 308, True, id="must-pass: minus 1e308"),
    pytest.param("1.7976931348623157e308", True, id="must-pass: the largest float"),
    pytest.param("1e-999", True, id="must-pass: too small for a float, which is zero"),
    pytest.param("0e99999999999", True, id="must-pass: zero with a huge exponent"),
    pytest.param("1e-99999999999", True, id="must-pass: a tiny number with a huge negative exponent"),
    pytest.param("-0", True, id="must-pass: minus zero"),
    pytest.param("1" + "0" * 309, False, id="must-refuse: 310 digits, 1e309"),
    pytest.param(BIG, False, id="must-refuse: 401 digits"),
    pytest.param("-" + BIG, False, id="must-refuse: minus 401 digits"),
    pytest.param("9" * 400 + ".5", False, id="must-refuse: 400 digits and a fraction"),
    pytest.param("1e309", False, id="must-refuse: 1e309"),
    pytest.param("1.7976931348623159e308", False, id="must-refuse: just over the largest float"),
    pytest.param("1e99999999999", False, id="must-refuse: an exponent too big for 32 bits"),
    pytest.param("1e999", False, id="must-refuse: 1e999"),
])
def test_a_number_the_inbox_parser_calls_out_of_range_is_not_json(world, token, read):
    world.put("Alder", with_extra(ask("A-1"), token), ask("A-2"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == (["A-1", "A-2"] if read else ["A-2"])
    assert [(p["line"], p["kind"]) for p in out["problems"]] == ([] if read else [(1, "bad json")])


@pytest.mark.parametrize("token,closes", [
    pytest.param("1" + "0" * 24, True, id="must-pass: a closing with a 25-digit number closes"),
    pytest.param(BIG, False, id="must-refuse: a closing with a 401-digit number closes nothing"),
])
def test_a_closing_that_holds_a_number_out_of_range_closes_nothing(world, token, closes):
    world.put("Alder", ask("A-1"), text_of(close("A-1"))[:-1] + ', "n": ' + token + "}")
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "closed" if closes else "waiting"}
    assert [p["kind"] for p in out["problems"]] == ([] if closes else ["bad json"])
    assert (out["seats"][0]["closings"], out["seats"][0]["refused"]) == ((1, 0) if closes else (0, 1))


@pytest.mark.parametrize("token,read", [
    pytest.param("2", True, id="must-pass: an option list with a small number in it"),
    pytest.param(BIG, False, id="must-refuse: an option list with a 401-digit number in it"),
])
def test_options_holding_a_number_out_of_range_make_the_line_a_problem(world, token, read):
    world.put("Alder", text_of(ask("A-1"))[:-1].replace('"second"', '"second", ' + token) + "}")
    out = world.load()
    assert [c["id"] for c in out["cards"]] == (["A-1"] if read else [])
    assert [p["kind"] for p in out["problems"] if not p.get("shown")] == ([] if read else ["bad json"])


# The inbox's parser checks every value it reads, including one that a later member of the same name replaces. Python
# keeps only the last member of a name, so a check made on what was parsed would never see the first.
@pytest.mark.parametrize("first,read", [
    pytest.param('"\\ud83d\\ude00"', True, id="must-pass: a whole pair that is replaced"),
    pytest.param("1" + "0" * 24, True, id="must-pass: a 25-digit number that is replaced"),
    pytest.param("[" * 125 + "]" * 125, True, id="must-pass: 126 levels, with the card's own, that are replaced"),
    pytest.param(HALF, False, id="must-refuse: half of a surrogate pair that is replaced"),
    pytest.param('"\\udc00"', False, id="must-refuse: a low half on its own that is replaced"),
    pytest.param(BIG, False, id="must-refuse: a 401-digit number that is replaced"),
    pytest.param("[" * 127 + "]" * 127, False, id="must-refuse: 128 levels, with the card's own, that are replaced"),
    pytest.param('{"k\\ud800": 1}', False, id="must-refuse: a name that is half a pair, in a value that is replaced"),
])
def test_a_value_that_a_later_member_of_the_same_name_replaces_is_still_checked(world, first, read):
    world.put("Alder", text_of(ask("A-1"))[:-1] + ', "note": ' + first + ', "note": false}')
    out = world.load()
    assert [c["id"] for c in out["cards"]] == (["A-1"] if read else [])
    assert [p["kind"] for p in out["problems"]] == ([] if read else ["bad json"])


@pytest.mark.parametrize("first,read", [
    pytest.param('"\\ud83d\\ude00"', True, id="must-pass: a whole pair that is replaced"),
    pytest.param("[" * 125 + "]" * 125, True, id="must-pass: 126 levels that are replaced"),
    pytest.param(HALF, False, id="must-refuse: half of a surrogate pair that is replaced"),
    pytest.param("[" * 127 + "]" * 127, False, id="must-refuse: 128 levels that are replaced"),
])
def test_a_value_of_the_parking_log_that_a_later_member_replaces_is_still_checked(world, first, read):
    world.put("Alder", ask("A-1"))
    world.parked_bytes(('{"event": "park", "seat": "Alder", "id": "A-1", "at": "t1", "x": ' + first
                        + ', "x": 1}\n').encode())
    out = world.load()
    assert out["cards"][0]["state"] == ("parked" if read else "waiting")
    assert [p["kind"] for p in out["problems"]] == ([] if read else ["bad json"])


REQUIRED = [(ask, f) for f in ("id", "at", "title", "why", "question")] + [(cmd, f) for f in
                                                                           ("id", "at", "title", "why", "command")]


@pytest.mark.parametrize("make,field", REQUIRED)
@pytest.mark.parametrize("value", [None, "", "   ", 5, ["x"]])   # None: the field is absent
def test_a_card_missing_a_required_field_is_a_problem_and_not_a_card(world, make, field, value):
    bad = without(make("A-1"), field) if value is None else {**make("A-1"), field: value}
    world.put("Alder", bad, make("A-2"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-2"]   # must pass: the whole card next to it
    (p,) = out["problems"]
    assert (p["line"], p["kind"]) == (1, "missing field") and field in p["text"] and not p.get("shown")


def test_every_missing_field_is_named(world):
    world.put("Alder", without(ask("A-1"), "title", "why", "question"))
    (p,) = world.load()["problems"]
    assert "title, why, question" in p["text"]


@pytest.mark.parametrize("kind", [None, "", 3, "rule", "Decision", "ask"])
def test_a_missing_or_unknown_kind_is_a_problem(world, kind):
    world.put("Alder", without(ask("A-1"), "kind") if kind is None else {**ask("A-1"), "kind": kind}, ask("A-2"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-2"]
    (p,) = out["problems"]
    assert p["kind"] == ("unknown kind" if kind in ("rule", "Decision", "ask") else "missing field")


@pytest.mark.parametrize("line,absent", [
    (without(cmd("A-1"), "does"), "does"), (without(cmd("A-1"), "undo"), "undo"),
    (without(cmd("A-1"), "does", "undo"), "does, undo"), ({**cmd("A-1"), "undo": "  "}, "undo"),
    (without(ask("A-1"), "options"), "options")])
def test_a_card_missing_what_it_does_how_to_undo_it_or_its_options_is_shown_with_a_problem(world, line, absent):
    world.put("Alder", line)
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting"}   # something is waiting on the person, so it is shown
    (p,) = out["problems"]
    assert (p["line"], p["kind"], p["shown"]) == (1, "missing field", True) and f"no {absent}" in p["text"]
    assert (out["seats"][0]["cards"], out["seats"][0]["refused"]) == (1, 0)


HIDDEN = [chr(0x202E), chr(0x200B), chr(0x2066), chr(0xFEFF), chr(0xAD), chr(0x61C), chr(0x180E), "\x1b", "\x7f",
          "\x85", "\x00"]


@pytest.mark.parametrize("ch", HIDDEN)
@pytest.mark.parametrize("where", ["command", "cwd"])
def test_a_command_or_folder_with_a_hidden_character_is_shown_with_a_note(world, ch, where):
    world.put("Alder", cmd("A-1", **({"command": f"echo a{ch}b"} if where == "command" else {"cwd": f"C:/w{ch}ork"})))
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting"}   # shown: something is waiting on the person
    (p,) = out["problems"]
    assert (p["line"], p["kind"], p["shown"]) == (1, "hidden character", True) and f"U+{ord(ch):04X}" in p["text"]
    assert (out["seats"][0]["cards"], out["seats"][0]["refused"]) == (1, 0)


def test_tabs_line_breaks_and_ordinary_text_in_a_command_are_not_hidden(world):
    text = "echo 'caf" + chr(0xE9) + "\t" + chr(0x65E5) + chr(0x672C) + "'\r\nWrite-Output " + chr(0x1F600) + "\n"
    elsewhere = f"prints {chr(0x202E)} and {chr(0x200B)}"   # only the command and its folder are checked
    world.put("Alder", cmd("A-1", command=text, does=elsewhere, undo=elsewhere, why=elsewhere, title=elsewhere))
    out = world.load()
    assert out["problems"] == [] and out["cards"][0]["command"] == text.strip()


def test_a_hidden_character_is_noted_after_a_missing_field_on_the_same_card(world):
    world.put("Alder", without(cmd("A-1", command=f"echo {chr(0x202E)}"), "does"))
    assert [(p["line"], p["kind"]) for p in world.load()["problems"]] == [(1, "missing field"), (1, "hidden character")]


def test_a_decision_with_no_options_listed_is_an_open_question_not_a_problem(world):
    world.put("Alder", ask("A-1", options=[]))   # must pass: asked for words, not a pick
    out = world.load()
    assert out["cards"][0]["options"] == [] and out["problems"] == []


def test_options_that_are_not_text_are_left_out_and_flagged(world):
    world.put("Alder", ask("A-1", options=["a", 2, None, "b"]), ask("A-2", options="yes or no"))
    out = world.load()
    assert [c["options"] for c in out["cards"]] == [["a", "b"], []]
    assert [(p["line"], p["kind"], p["shown"]) for p in out["problems"]] == [
        (1, "bad field", True), (2, "bad field", True)]


# ---------------------------------------------------------------- bytes that are not UTF-8
# The inbox reads a file whole or not at all: one byte that is not UTF-8 and none of the file is read. A tool that
# writes the Windows code page (PowerShell 5.1's Add-Content, for one) leaves such bytes.
@pytest.mark.parametrize("bad", [
    pytest.param(b"\xe9", id="a lone Latin-1 e acute"), pytest.param(b"\xff", id="0xFF"),
    pytest.param(b"\xc3", id="a cut-off two-byte sequence"), pytest.param(b"\xed\xa0\x80", id="an encoded surrogate"),
    pytest.param(b"\xc0\xaf", id="an overlong slash"), pytest.param(b"\xf8\x88\x80\x80\x80", id="a five-byte form")])
def test_a_request_file_with_one_byte_that_is_not_utf8_is_not_read_at_all(world, bad):
    first = text_of(ask("A-1", title="CAFE")).encode().replace(b"CAFE", b"caf" + bad)
    world.put_bytes("Alder", first + b"\n" + text_of(ask("A-2")).encode() + b"\n" + text_of(close("A-2")).encode())
    world.put("Birch", ask("B-1"))
    out = world.load()
    assert [c["seat"] for c in out["cards"]] == ["Birch"]   # must refuse: none of Alder's file is read
    (p,) = out["problems"]
    assert (p["kind"], p["line"], p["source"]) == ("bad encoding", None, str(world.file("Alder")))
    assert not p.get("shown") and "UTF-8" in p["text"] and p["text"].startswith("Alder: ")
    alder, birch = out["seats"][0], out["seats"][1]
    assert (alder["present"], alder["lines"], alder["cards"], alder["closings"], alder["refused"]) == (True, 0, 0, 0, 0)
    assert (birch["cards"], birch["refused"]) == (1, 0)   # a neighbour's file is read as before


@pytest.mark.parametrize("good", ["caf\u00e9", "\u65e5\u672c", "\U0001F600", "\ufffd", "\u00a0", "a\u0301"])
def test_text_that_is_valid_utf8_is_read_and_a_replacement_mark_in_it_is_no_problem(world, good):
    world.put("Alder", ask("A-1", title=good + "T"), cmd("A-2", command=f"echo {good}"), close("A-2", f"how {good}"))
    out = world.load()
    assert [c["title"] for c in out["cards"]] == [good.strip() + "T", "Title A-2"]
    assert out["problems"] == [] and states(out) == {("Alder", "A-1"): "waiting", ("Alder", "A-2"): "closed"}
    assert out["cards"][1]["closing"]["how"] == f"how {good}".strip()


def test_a_request_file_with_a_byte_that_is_not_utf8_inside_a_value_that_is_never_read_is_still_not_read(world):
    raw = text_of(ask("A-1")).encode()[:-1] + b', "ignored": "\xff"}\n'
    world.put_bytes("Alder", raw)
    out = world.load()
    assert out["cards"] == [] and [p["kind"] for p in out["problems"]] == ["bad encoding"]


@pytest.mark.parametrize("bad,run", [(b"", True), (b"\xff", False)])
def test_a_runs_log_with_a_byte_that_is_not_utf8_gives_no_runs(world, bad, run):
    world.put("Alder", cmd("A-1"))
    world.runs_bytes(text_of(run_line("Alder", "A-1")).encode() + b"\n" + b'{"seat": "x", "id": "y", "started": "' + bad
                     + b'"}\n')
    out = world.load()
    assert out["cards"][0]["state"] == ("run" if run else "waiting")   # must refuse: the inbox reads none of the log
    assert [p["kind"] for p in out["problems"]] == ([] if run else ["bad encoding"])
    if not run:
        (p,) = out["problems"]
        assert p["source"] == str(world.inbox / "runs.jsonl") and p["line"] is None and "may show as waiting" in p["text"]
        assert out["runs"] == {"lines": 0, "cards": 0, "unmatched": 0}


@pytest.mark.parametrize("bad,parked", [(b"", True), (b"\xff", False)])
def test_a_parking_log_with_a_byte_that_is_not_utf8_gives_no_parking(world, bad, parked):
    world.put("Alder", ask("A-1"), ask("A-2"))
    world.parked_bytes(text_of(park("Alder", "A-1")).encode() + b"\n" + b'{"event": "park", "seat": "Alder", '
                       b'"id": "A-2", "at": "' + bad + b'"}\n')
    out = world.load()
    assert {c["id"]: c["state"] for c in out["cards"]} == (   # must refuse: no parking at all
        {"A-1": "parked", "A-2": "parked"} if parked else {"A-1": "waiting", "A-2": "waiting"})
    assert [p["kind"] for p in out["problems"]] == ([] if parked else ["bad encoding"])
    if not parked:
        (p,) = out["problems"]
        assert p["source"] == str(world.inbox / "parked.jsonl") and p["line"] is None and "no parking" in p["text"]
        assert out["parking"] == {"events": 0, "parked": 0, "on_done_cards": 0, "decisions_back": {}}


# ---------------------------------------------------------------- closings
def test_a_closing_closes_its_card_even_when_it_comes_first(world):
    world.put("Alder", close("A-1", "answered in chat: '1'"), ask("A-1"), ask("A-2"))
    out = world.load()
    got = {c["id"]: c for c in out["cards"]}
    closing = got["A-1"]["closing"]
    assert got["A-1"]["state"] == "closed"
    assert (closing["at"], closing["how"], closing["line"]) == ("2026-10-01T11:00:00+01:00", "answered in chat: '1'", 1)
    assert closing["raw"] == json.dumps(close("A-1", "answered in chat: '1'"))
    assert got["A-2"]["state"] == "waiting" and got["A-2"]["closing"] is None
    assert out["problems"] == [] and out["seats"][0]["closings"] == 1


def test_a_closing_with_no_at_or_how_still_closes(world):
    world.put("Alder", ask("A-1"), {"close": "A-1"})
    (c,) = world.load()["cards"]
    assert c["state"] == "closed" and (c["closing"]["at"], c["closing"]["how"]) == ("", "")


def test_a_closing_that_names_no_card_is_a_problem_and_never_crosses_agents(world):
    world.put("Alder", ask("A-1"), close("A-9"))
    world.put("Birch", close("A-1"))
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting"}   # Birch's closing does not touch Alder's card
    assert sorted((p["source"], p["line"], p["kind"]) for p in out["problems"]) == [
        (str(world.file("Alder")), 2, "closing with no card"), (str(world.file("Birch")), 1, "closing with no card")]
    assert [(s["seat"], s["closings"], s["refused"]) for s in out["seats"]] == [
        ("Alder", 0, 1), ("Birch", 0, 1), ("Cedar", 0, 0)]


def test_a_card_closed_twice_shows_the_later_closing_and_keeps_the_earlier(world):
    world.put("Alder", ask("A-1"), close("A-1", "first note"), close("A-1", "a correction"))
    out = world.load()
    (c,) = out["cards"]
    assert (c["closing"]["how"], c["closing"]["line"]) == ("a correction", 3)
    assert c["closing"]["earlier"] == [{"at": "2026-10-01T11:00:00+01:00", "how": "first note", "line": 2}]
    assert out["seats"][0]["closings"] == 2 and out["problems"] == []


@pytest.mark.parametrize("closing", [{"close": 7, "at": AT, "how": "x"}, {"close": "   ", "at": AT, "how": "x"},
                                     {"close": "", "at": AT}])
def test_a_close_field_that_is_not_text_closes_nothing(world, closing):
    world.put("Alder", ask("A-1"), closing)
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting"}
    assert [p["kind"] for p in out["problems"]] == ["missing field"]   # read as a request, which it is not


def test_an_id_used_twice_keeps_the_first_and_flags_the_later_line(world):
    world.put("Alder", ask("A-1", title="first"), ask("A-2"), ask(" A-1 ", title="second"))
    out = world.load()
    assert [(c["id"], c["title"]) for c in out["cards"]] == [("A-1", "first"), ("A-2", "Title A-2")]
    (p,) = out["problems"]
    assert (p["line"], p["kind"]) == (3, "duplicate id") and "A-1" in p["text"]


def test_a_line_that_failed_to_parse_does_not_claim_its_id(world):
    world.put("Alder", without(ask("A-1", title="broken"), "why"), ask("A-1", title="whole"))
    out = world.load()
    assert [(c["id"], c["title"]) for c in out["cards"]] == [("A-1", "whole")]
    assert [p["kind"] for p in out["problems"]] == ["missing field"]


# ---------------------------------------------------------------- runs: a card that has run is never waiting
def test_a_card_that_has_run_is_never_waiting(world):
    world.put("Alder", cmd("A-1"), cmd("A-2"), cmd("A-3"), cmd("A-4"), close("A-4"))
    world.runs(run_line("Alder", "A-1", finished=None, exit=None),   # started, no result recorded
               run_line("Alder", "A-2", finished=None, exit=None),   # started, then the result
               run_line("Alder", "A-2"), run_line("Alder", "A-4", exit=3))
    out = world.load()
    got = {c["id"]: c for c in out["cards"]}
    assert got["A-1"]["state"] == "run"
    assert got["A-1"]["run"] == {"started": "2026-10-02T09:00:00Z", "finished": None, "exit": None, "timed_out": False}
    assert got["A-2"]["run"] == {"started": "2026-10-02T09:00:00Z", "finished": "2026-10-02T09:00:05Z", "exit": 0,
                                 "timed_out": False}   # the later line replaced the earlier
    assert got["A-3"]["state"] == "waiting" and got["A-3"]["run"] is None   # must refuse: no run, no change
    assert got["A-4"]["state"] == "run" and got["A-4"]["run"]["exit"] == 3
    assert got["A-4"]["closing"]["how"] == "answered"   # the closing is kept beside the run
    assert out["runs"] == {"lines": 4, "cards": 3, "unmatched": 0} and out["problems"] == []


def test_a_runs_output_is_kept_beside_the_run_as_text(world):
    world.put("Alder", cmd("A-1"), cmd("A-2"), cmd("A-3"))
    world.runs(run_line("Alder", "A-1", stdout="first", finished=None, exit=None),
               run_line("Alder", "A-1", stdout="<b>one</b>\n", stderr="a warning"),   # the later line replaces the earlier
               {"seat": "Alder", "id": "A-2", "started": "2026-10-02T09:00:00Z"},     # a run that left no output
               '{"seat": "Alder", "id": "A-3", "started": "x", "stdout": 7}')          # refused: stdout is not text
    out = world.load()
    got = {c["id"]: c for c in out["cards"]}
    assert got["A-1"]["output"] == {"stdout": "<b>one</b>\n", "stderr": "a warning"}
    assert got["A-1"]["run"] == {"started": "2026-10-02T09:00:00Z", "finished": "2026-10-02T09:00:05Z", "exit": 0,
                                 "timed_out": False}   # the run itself is as it was
    assert got["A-2"]["output"] == {"stdout": "", "stderr": ""}
    # must-refuse: a line the inbox would not read gives no run and no output
    assert got["A-3"]["state"] == "waiting" and got["A-3"]["output"] is None
    assert [p["kind"] for p in out["problems"]] == ["bad run record"]


def test_a_timed_out_run_is_a_run(world):
    world.put("Alder", cmd("A-1"))
    world.runs(run_line("Alder", "A-1", exit=None, timed_out=True))
    (c,) = world.load()["cards"]
    assert c["state"] == "run" and c["run"]["timed_out"] is True and c["run"]["exit"] is None


def test_a_run_of_another_agent_or_id_does_not_touch_the_card(world):
    world.put("Alder", cmd("A-1"))
    world.put("Birch", cmd("A-1"))
    world.runs(run_line("Birch", "A-1"), run_line("alder", "A-1"), run_line("Alder", "A-9"))
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting", ("Birch", "A-1"): "run"}
    assert out["runs"] == {"lines": 3, "cards": 3, "unmatched": 2}


def run_text(**kw) -> str:
    return text_of({**run_line("Alder", "A-1"), **kw})


def run_with(pairs: str) -> str:
    """The full run line with more members written as raw JSON text."""
    return run_text()[:-1] + ", " + pairs + "}"


# Lines of runs.jsonl the inbox does not read as run records. Each is a problem and no run, so the card stays waiting.
BAD_RUNS = [
    pytest.param(text_of({"seat": "Alder", "id": "A-1"}), "bad run record", id="no started"),
    pytest.param(run_text(started=None), "bad run record", id="started null"),
    pytest.param(run_text(started=5), "bad run record", id="started a number"),
    pytest.param(run_text(seat=None), "bad run record", id="seat null"),
    pytest.param(run_text(id=3), "bad run record", id="id a number"),
    pytest.param(run_text(exit="0"), "bad run record", id="exit a string"),
    pytest.param(run_text().replace('"exit": 0', '"exit": 1.0'), "bad run record", id="exit a float"),
    pytest.param(run_text().replace('"exit": 0', '"exit": -0'), "bad run record", id="exit minus zero"),
    pytest.param(run_text().replace('"exit": 0', '"exit": 1e2'), "bad run record", id="exit written with an exponent"),
    pytest.param(run_text(exit=2 ** 31), "bad run record", id="exit one past the 32-bit top"),
    pytest.param(run_text(exit=-2 ** 31 - 1), "bad run record", id="exit one past the 32-bit bottom"),
    pytest.param(run_text(exit=True), "bad run record", id="exit true"),
    pytest.param(run_text(finished=5), "bad run record", id="finished a number"),
    pytest.param(run_text(timed_out=None), "bad run record", id="timed_out null"),
    pytest.param(run_text(timed_out="no"), "bad run record", id="timed_out a string"),
    pytest.param(run_text(timed_out=0), "bad run record", id="timed_out a number"),
    pytest.param(run_text(stdout=None), "bad run record", id="stdout null"),
    pytest.param(run_text(stderr=5), "bad run record", id="stderr a number"),
    pytest.param(run_text(command=None), "bad run record", id="command null"),
    pytest.param(run_with('"seat": "Alder"'), "bad run record", id="a field it knows, twice"),
    pytest.param(run_with('"timed_out": false'), "bad run record", id="timed_out twice"),
    pytest.param('["Alder","A-1"]', "bad run record", id="an array of two"),
    pytest.param('["Alder","A-1",5]', "bad run record", id="an array whose third is a number"),
    pytest.param('["Alder","A-1","t","f",0,false,"o","e","c","x"]', "bad json", id="an array of ten"),
    pytest.param("[]", "bad run record", id="an empty array"),
    pytest.param("5", "bad run record", id="a number"),
    pytest.param("null", "bad run record", id="null"),
    pytest.param('"Alder"', "bad run record", id="a string"),
    pytest.param("\ufeff" + run_text(), "bad json", id="a byte-order mark before the object"),
    pytest.param("\u00a0" + run_text() + "\u00a0", "bad json", id="no-break spaces around the object"),
    pytest.param(run_text().replace('"stdout": "hi"', '"stdout": "\\ud800"'), "bad json",
                 id="half of a surrogate pair in a field it knows"),
    pytest.param(run_with('"k\\ud800": 1'), "bad json", id="half of a surrogate pair in a name"),
    pytest.param(run_with('"x": 01'), "bad json", id="a leading zero in a field it does not know"),
    pytest.param(run_with('"x": NaN'), "bad json", id="NaN in a field it does not know"),
    pytest.param(run_with('"x": "\\q"'), "bad json", id="a bad escape in a field it does not know"),
    pytest.param(run_with('"x": [1,]'), "bad json", id="a trailing comma in a field it does not know"),
    pytest.param(run_text()[:-1], "bad json", id="a record cut off"),
    pytest.param(run_text() + " x", "bad json", id="more after the record"),
]
# Lines the inbox does read as run records, though some look odd. Each is a run.
GOOD_RUNS = [
    pytest.param(text_of({"seat": "Alder", "id": "A-1", "started": "t"}), id="the three required fields"),
    pytest.param(run_text(), id="every field"),
    pytest.param(run_text(exit=-2 ** 31), id="exit at the 32-bit bottom"),
    pytest.param(run_text(exit=2 ** 31 - 1), id="exit at the 32-bit top"),
    pytest.param(run_text(finished=None, exit=None), id="finished and exit null"),
    pytest.param(run_text(timed_out=True), id="timed out"),
    pytest.param(run_with('"note": [1, {"a": null}], "n": 2.5'), id="fields it does not know"),
    pytest.param(run_with('"z": 1, "z": 2'), id="a name it does not know, twice"),
    pytest.param(run_with('"x": 1e999'), id="an unknown field holding 1e999"),
    pytest.param(run_with('"x": ' + BIG), id="an unknown field holding a 401-digit number"),
    pytest.param(run_with('"x": ' + HALF), id="an unknown field holding half of a surrogate pair"),
    pytest.param(run_with('"x": {"k\\ud800": ["\\udc00"]}'), id="half pairs deep in an unknown field"),
    pytest.param(run_with('"x": ' + "[" * 4999 + "]" * 4999), id="an unknown field nested 5000 deep"),
    pytest.param(run_with('"x": ' + '{"a":' * 3000 + "1" + "}" * 3000), id="an unknown field of 3000 objects"),
    pytest.param(run_text().replace('"seat"', '"s\\u0065at"'), id="a known name written with an escape"),
    pytest.param(run_with('"k\\ud83d\\ude00": 1'), id="a whole pair in a name"),
    pytest.param('["Alder","A-1","t"]', id="an array of three"),
    pytest.param('["Alder","A-1","t",null,null]', id="an array of five with nulls"),
    pytest.param('["Alder","A-1","t","f",0,false,"o","e","c"]', id="an array of the nine fields"),
    pytest.param(' [ "Alder" , "A-1" , "t" ] ', id="an array with white space"),
    pytest.param(" \t" + run_text() + " \t", id="JSON white space around the object"),
]


@pytest.mark.parametrize("line,kind", BAD_RUNS)
def test_a_line_of_runs_the_inbox_does_not_read_as_a_run_record_is_a_problem_and_no_run(world, line, kind):
    world.put("Alder", cmd("A-1"))
    world.runs_bytes(line.encode("utf-8") + b"\n")
    out = world.load()
    assert out["cards"][0]["state"] == "waiting" and out["cards"][0]["run"] is None   # must refuse: no run
    (p,) = out["problems"]
    assert (p["source"], p["line"], p["kind"]) == (str(world.inbox / "runs.jsonl"), 1, kind)
    assert "may show as waiting" in p["text"]
    assert out["runs"] == {"lines": 1, "cards": 0, "unmatched": 0}


@pytest.mark.parametrize("line", GOOD_RUNS)
def test_a_line_of_runs_the_inbox_reads_as_a_run_record_is_a_run(world, line):
    world.put("Alder", cmd("A-1"))
    world.runs_bytes(line.encode("utf-8") + b"\n")
    out = world.load()
    assert out["cards"][0]["state"] == "run" and out["cards"][0]["run"] is not None   # must pass
    assert out["problems"] == [] and out["runs"] == {"lines": 1, "cards": 1, "unmatched": 0}


def test_a_later_bad_line_never_replaces_an_earlier_good_record(world):
    world.put("Alder", cmd("A-1"), cmd("A-2"))
    world.runs(run_line("Alder", "A-1", finished="F", exit=7), run_line("Alder", "A-1", exit="zero"),
               run_line("Alder", "A-2", finished="G", exit=8), {"seat": "Alder", "id": "A-2", "note": "no started"},
               run_line("Alder", "A-2", exit=None, finished="H"))   # a later good line does replace
    out = world.load()
    got = {c["id"]: c["run"] for c in out["cards"]}
    assert got["A-1"] == {"started": "2026-10-02T09:00:00Z", "finished": "F", "exit": 7, "timed_out": False}
    assert got["A-2"] == {"started": "2026-10-02T09:00:00Z", "finished": "H", "exit": None, "timed_out": False}
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(2, "bad run record"), (4, "bad run record")]
    assert out["runs"] == {"lines": 5, "cards": 2, "unmatched": 0}


def test_a_byte_order_mark_at_the_start_of_runs_is_not_dropped_so_the_first_line_is_a_problem(world):
    world.put("Alder", cmd("A-1"), cmd("A-2"))
    world.runs(run_line("Alder", "A-1"), run_line("Alder", "A-2"), bom=True)
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting", ("Alder", "A-2"): "run"}   # must refuse: line 1 is not a record
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(1, "bad json")]
    world.runs(run_line("Alder", "A-1"), run_line("Alder", "A-2"))   # must pass: the same lines with no mark
    assert set(states(world.load()).values()) == {"run"}


def test_blank_lines_of_runs_are_skipped_and_do_not_count(world):
    world.put("Alder", cmd("A-1"))
    world.runs_bytes(b"\n\xe3\x80\x80\n  \t\n" + text_of(run_line("Alder", "A-1")).encode() + b"\r\n\r\n")
    out = world.load()
    assert out["cards"][0]["state"] == "run" and out["runs"]["lines"] == 1 and out["problems"] == []


def test_a_run_for_an_id_with_a_space_around_it_is_for_that_id_exactly(world):
    world.put("Alder", cmd("A-1"))
    world.runs(run_line("Alder", " A-1 "), run_line(" Alder", "A-1"))   # a run's names are not trimmed, a card's id is
    out = world.load()
    assert out["cards"][0]["state"] == "waiting" and out["runs"] == {"lines": 2, "cards": 2, "unmatched": 2}


def test_a_run_record_over_64_kb_still_counts(world):
    world.put("Alder", cmd("A-1"))
    world.runs(run_line("Alder", "A-1", stdout="x" * (3 * MAX_LINE)))   # a command's output makes a long record
    out = world.load()
    assert out["cards"][0]["state"] == "run" and out["problems"] == []


# ---------------------------------------------------------------- parking
def test_parking_follows_the_latest_event_and_only_an_open_card_can_be_parked(world):
    world.put("Alder", ask("A-1"), ask("A-2"), ask("A-3"), close("A-3"), cmd("A-4"), ask("A-5"))
    world.runs(run_line("Alder", "A-4"))
    world.parked(park("Alder", "A-1"), park("Alder", "A-2"), back("Alder", "A-2"), park("Alder", "A-3"),
                 park("Alder", "A-4"), park("Alder", "A-5"), back("Alder", "A-5"), park("Alder", "A-5", at="later"))
    out = world.load()
    got = {c["id"]: c for c in out["cards"]}
    assert {i: c["state"] for i, c in got.items()} == {
        "A-1": "parked", "A-2": "waiting", "A-3": "closed", "A-4": "run", "A-5": "parked"}
    assert (got["A-1"]["parked_at"], got["A-5"]["parked_at"]) == ("2026-10-03T08:00:00Z", "later")
    assert got["A-3"]["parked_at"] is got["A-4"]["parked_at"] is got["A-2"]["parked_at"] is None
    assert out["parking"] == {"events": 8, "parked": 2, "on_done_cards": 2, "decisions_back": {}}
    assert out["problems"] == []


@pytest.mark.parametrize("bad", [
    {"event": "snooze", "seat": "Alder", "id": "A-1", "at": "t"}, {"event": "park", "id": "A-1"},
    {"event": "park", "seat": "Alder"}, {"event": "park", "seat": "Alder", "id": "A-1", "register": "J-1"},
    {"event": "back", "seat": "Alder", "id": "A-1", "register": "J-1"},
    {"event": "back", "seat": "Alder", "register": "J-1"}, {"event": "back", "id": "A-1"}, {"event": "back"},
    {"event": 5, "seat": "Alder", "id": "A-1"},
    {"seat": "Alder", "id": "A-1"}, {}, "[1]", "7"])
def test_a_parking_event_the_reader_does_not_know_is_a_problem(world, bad):
    world.put("Alder", ask("A-1"))
    world.parked(park("Alder", "A-1"), bad)
    out = world.load()
    (p,) = out["problems"]
    assert (p["line"], p["kind"], p["source"]) == (2, "unknown parking", str(world.inbox / "parked.jsonl"))
    assert out["cards"][0]["state"] == "parked"   # must pass: the good event before it still counts


def test_bringing_back_a_card_that_is_not_parked_changes_nothing_and_says_nothing(world):
    world.put("Alder", ask("A-1"), ask("A-2"))
    world.parked(back("Alder", "A-1"), park("Alder", "A-2"), back("Alder", "A-1"))
    out = world.load()
    assert states(out) == {("Alder", "A-1"): "waiting", ("Alder", "A-2"): "parked"}
    assert out["problems"] == [] and out["parking"]["events"] == 3


def test_a_parking_line_that_is_not_json_is_a_problem(world):
    world.put("Alder", ask("A-1"))
    world.parked("{oops", park("Alder", "A-1"))
    out = world.load()
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(1, "bad json")]
    assert out["cards"][0]["state"] == "parked"


def test_a_register_decision_brought_back_is_recorded_and_the_latest_stands(world):
    world.parked({"event": "back", "register": "J-1", "at": "t1"}, {"event": "back", "register": "J-1", "at": "t2"},
                 {"event": "back", "register": "J-2", "at": "t3"})
    out = world.load()
    assert out["parking"]["decisions_back"] == {"J-1": "t2", "J-2": "t3"} and out["problems"] == []


def test_a_parking_that_names_no_card_is_a_problem(world):
    world.put("Alder", ask("A-1"))
    world.parked(park("Alder", "A-1"), park("Alder", "A-9"), park("Nobody", "A-1"), back("Alder", "A-8"))
    out = world.load()
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(n, "parking with no card") for n in (2, 3, 4)]
    assert out["cards"][0]["state"] == "parked"


# The parking log is read as the inbox reads it: no limit on a line, every leading byte-order mark dropped, and a line
# parsed as it stands, with only JSON white space allowed around it.
@pytest.mark.parametrize("pad", [pytest.param(1, id="an ordinary line"), pytest.param(60000, id="a line of 120 KB")])
def test_a_line_of_the_parking_log_has_no_length_limit(world, pad):
    world.put("Alder", ask("A-1"))
    world.parked({**park("Alder", "A-1"), "pad": "\u00e9" * pad})
    out = world.load()
    assert out["cards"][0]["state"] == "parked" and out["problems"] == []


@pytest.mark.parametrize("around,parked", [
    pytest.param(" \t", True, id="must-pass: spaces and tabs around the line"),
    pytest.param("\r", True, id="must-pass: a carriage return around the line"),
    pytest.param("\u00a0", False, id="must-refuse: no-break spaces around the line"),
    pytest.param("\u3000", False, id="must-refuse: ideographic spaces around the line"),
    pytest.param("\u0085", False, id="must-refuse: a next-line character around the line"),
    pytest.param("\x0b", False, id="must-refuse: a vertical tab around the line"),
    pytest.param("\ufeff", False, id="must-refuse: a byte-order mark around the line"),
])
def test_a_parking_line_is_parsed_as_it_stands_so_only_json_white_space_may_surround_it(world, around, parked):
    world.put("Alder", ask("A-1"))
    world.parked_bytes((around + text_of(park("Alder", "A-1")) + around + "\n").encode())
    out = world.load()
    assert out["cards"][0]["state"] == ("parked" if parked else "waiting")
    assert [p["kind"] for p in out["problems"]] == ([] if parked else ["bad json"])


@pytest.mark.parametrize("marks", [1, 2, 4])
def test_every_byte_order_mark_at_the_start_of_the_parking_log_is_dropped(world, marks):
    world.put("Alder", ask("A-1"))
    world.parked_bytes(b"\xef\xbb\xbf" * marks + text_of(park("Alder", "A-1")).encode() + b"\n")
    out = world.load()
    assert out["cards"][0]["state"] == "parked" and out["problems"] == []   # old: two marks were a "bad json" line


def test_a_line_of_only_white_space_in_the_parking_log_is_blank_however_long(world):
    world.put("Alder", ask("A-1"))
    world.parked_bytes(("\u3000" * 30000 + "\n\x1c\n").encode() + text_of(park("Alder", "A-1")).encode() + b"\n")
    out = world.load()
    assert out["cards"][0]["state"] == "parked"
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(2, "bad json")]   # U+001C is not white space to it


@pytest.mark.parametrize("token,parked", [
    pytest.param("1" + "0" * 24, True, id="must-pass: a 25-digit number"),
    pytest.param(BIG, False, id="must-refuse: a 401-digit number"),
])
def test_a_parking_line_holding_a_number_out_of_range_parks_nothing(world, token, parked):
    world.put("Alder", ask("A-1"))
    world.parked_bytes((text_of(park("Alder", "A-1"))[:-1] + ', "n": ' + token + "}\n").encode())
    out = world.load()
    assert out["cards"][0]["state"] == ("parked" if parked else "waiting")
    assert [p["kind"] for p in out["problems"]] == ([] if parked else ["bad json"])


# ---------------------------------------------------------------- the counts
def test_the_counts_add_up(world):
    world.put("Alder", ask("A-1"), ask("A-2"), close("A-2"), cmd("A-3"), ask("A-4"), "{junk", close("A-9"))
    world.put("Birch", ask("B-1"), ask("B-1"), without(ask("B-2"), "why"))
    world.runs(run_line("Alder", "A-3"))
    world.parked(park("Alder", "A-4"))
    out = world.load()
    assert out["counts"]["by_state"] == {"waiting": 2, "parked": 1, "closed": 1, "run": 1}
    assert out["counts"]["cards"] == len(out["cards"]) == 5
    assert out["counts"]["by_seat"] == {
        "Alder": {"cards": 4, "waiting": 1, "parked": 1, "closed": 1, "run": 1},
        "Birch": {"cards": 1, "waiting": 1, "parked": 0, "closed": 0, "run": 0},
        "Cedar": {"cards": 0, "waiting": 0, "parked": 0, "closed": 0, "run": 0}}
    for s in out["seats"]:
        assert s["lines"] == s["cards"] + s["closings"] + s["refused"]
        refusals = [p for p in out["problems"] if p["source"] == s["file"] and p["line"] and not p.get("shown")]
        assert len(refusals) == s["refused"]   # every refused line has exactly one problem
    assert [(s["seat"], s["lines"], s["cards"], s["closings"], s["refused"]) for s in out["seats"]] == [
        ("Alder", 7, 4, 1, 2), ("Birch", 3, 1, 0, 2), ("Cedar", 0, 0, 0, 0)]


# ---------------------------------------------------------------- files that cannot be used
def test_an_agent_that_has_asked_nothing_is_not_a_problem(world):
    out = world.load()
    assert out["cards"] == [] and out["problems"] == []
    assert [(s["seat"], s["present"], s["groups"]) for s in out["seats"]] == [
        ("Alder", False, ["posters"]), ("Birch", False, ["posters"]), ("Cedar", False, ["posters"])]


def test_a_request_file_that_cannot_be_used_is_a_problem(world):
    world.file("Alder").mkdir()                               # a folder where the file should be
    world.file("Birch").write_bytes(b"\n" * (FILE_CAP + 1))   # over 5 MB
    world.put("Cedar", ask("C-1"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["C-1"]
    assert sorted(p["source"] for p in out["problems"]) == sorted([str(world.file("Alder")), str(world.file("Birch"))])
    assert {p["kind"] for p in out["problems"]} == {"file"}
    said = {Path(p["source"]).parent.name: p["text"] for p in out["problems"]}
    assert "is not a file" in said["alder"] and "over 5 MB" in said["birch"]


def test_a_request_file_of_exactly_5_mb_is_read(world):
    world.file("Alder").write_bytes(b" " * (FILE_CAP - 1) + b"\n")
    out = world.load()
    assert out["problems"] == [] and out["seats"][0]["present"] is True


def test_a_seats_file_that_cannot_be_used_is_a_problem(world):
    for text in ("", "{not json", "[1]", '{"base": 5, "seats": {}}', '{"seats": {}}', '{"base": "x"}'):
        world.seats.write_text(text, encoding="utf-8")
        out = world.load()
        assert out["cards"] == [] and out["seats"] == [], text
        assert [p["kind"] for p in out["problems"]] == ["seats file"], text
    world.write_seats({}, base=world.root / "no-such-base")
    assert [p["kind"] for p in world.load()["problems"]] == ["seats file"]
    world.seats.unlink()
    assert [p["kind"] for p in world.load()["problems"]] == ["seats file"]


def test_a_home_that_is_missing_or_leaves_the_base_is_a_problem_and_the_others_still_read(world):
    outside = world.root / "outside"
    outside.mkdir()
    (outside / FILE).write_text(json.dumps(ask("X-1")) + "\n", encoding="utf-8")
    world.write_seats({"Alder": {"home": "alder"}, "Birch": {"home": "../outside"}, "Cedar": {"home": str(outside)},
                       "Dune": {}, "Elm": {"home": "gone"}, "Fir": 7})
    world.put("Alder", ask("A-1"))
    out = world.load()
    assert [c["id"] for c in out["cards"]] == ["A-1"]   # nothing was read from outside the base folder
    assert [(s["seat"], s["home"] is not None) for s in out["seats"]] == [
        ("Alder", True), ("Birch", False), ("Cedar", False), ("Dune", False), ("Elm", True), ("Fir", False)]
    assert [p["kind"] for p in out["problems"]] == ["seats file"] * 5
    assert [p["text"].split()[0] for p in out["problems"]] == ["Birch's", "Cedar's", "Dune", "Elm's", "Fir"]


def test_a_home_written_as_a_full_path_is_read_when_it_is_inside_the_base_and_not_when_it_is_outside(world):
    outside = world.root / "outside"
    outside.mkdir()
    (outside / FILE).write_text(json.dumps(ask("X-1")) + "\n", encoding="utf-8")
    world.write_seats({"Alder": {"home": str(world.base / "alder")}, "Birch": {"home": str(outside)},
                       "Cedar": {"home": str(world.base / "teams" / ".." / "alder")}})
    world.put("Alder", ask("A-1"))
    out = world.load()
    assert [(c["seat"], c["id"]) for c in out["cards"]] == [("Alder", "A-1")]   # must pass: the full path inside
    assert [(s["seat"], s["home"] is not None) for s in out["seats"]] == [
        ("Alder", True), ("Birch", False), ("Cedar", False)]   # must refuse: outside, and one with a ".." step
    assert [p["text"].split()[0] for p in out["problems"]] == ["Birch's", "Cedar's"]


def test_a_missing_inbox_folder_is_a_problem_but_the_cards_still_show(world):
    world.put("Alder", ask("A-1"))
    out = cards.load({**world.cfg(), "inbox": str(world.root / "nowhere")})
    assert states(out) == {("Alder", "A-1"): "waiting"} and [p["kind"] for p in out["problems"]] == ["inbox folder"]


def test_an_inbox_that_is_a_file_is_one_problem_and_no_run_or_parking_is_read(world):
    world.put("Alder", ask("A-1"))
    not_a_folder = world.root / "inbox-file"
    not_a_folder.write_text("x", encoding="utf-8")
    out = cards.load({**world.cfg(), "inbox": str(not_a_folder)})
    assert states(out) == {("Alder", "A-1"): "waiting"} and [p["kind"] for p in out["problems"]] == ["inbox folder"]


# ---------------------------------------------------------------- a NUL in a path is a problem, never an exception
def test_a_nul_character_in_a_home_is_a_problem_and_the_other_homes_still_read(world):
    world.write_seats({"Alder": {"home": "alder"}, "Birch": {"home": "bi\u0000rch"}, "Cedar": {"home": "teams/cedar"}})
    world.put("Alder", ask("A-1"))
    world.put("Cedar", ask("C-1"))
    out = world.load()   # must refuse: not an exception, and nothing is read from a home with a NUL in it
    assert [(c["seat"], c["id"]) for c in out["cards"]] == [("Alder", "A-1"), ("Cedar", "C-1")]
    (p,) = out["problems"]
    assert (p["kind"], p["line"]) == ("seats file", None) and p["text"].startswith("Birch's home") and "NUL" in p["text"]
    assert [(s["seat"], s["home"] is None) for s in out["seats"]] == [("Alder", False), ("Birch", True), ("Cedar", False)]


def test_a_nul_character_in_the_inbox_path_is_a_problem_and_the_cards_still_show(world):
    world.put("Alder", ask("A-1"))
    assert world.load()["problems"] == []   # must pass: the same files with the path as it is
    out = cards.load({**world.cfg(), "inbox": str(world.inbox) + "\x00x"})
    assert states(out) == {("Alder", "A-1"): "waiting"} and [p["kind"] for p in out["problems"]] == ["inbox folder"]


def test_a_nul_character_in_the_seats_path_is_a_problem(world):
    out = cards.load({**world.cfg(), "seats": str(world.seats) + "\x00"})
    assert out["cards"] == [] and [p["kind"] for p in out["problems"]] == ["seats file"]


def test_a_nul_character_in_the_base_folder_is_a_problem(world):
    world.write_seats({"Alder": {"home": "alder"}}, base=Path(str(world.base) + "\x00"))
    out = world.load()
    assert out["cards"] == [] and [p["kind"] for p in out["problems"]] == ["seats file"]


# ---------------------------------------------------------------- the group: only its seats are read
GROUPED = {"Alder": {"groups": ["posters"], "home": "alder"}, "Birch": {"groups": ["readers"], "home": "birch"},
           "Cedar": {"groups": ["posters", "readers"], "home": "teams/cedar"}}


def test_with_a_group_only_the_seats_in_it_are_read(world):
    world.write_seats(GROUPED)
    for seat, id_ in (("Alder", "A-1"), ("Birch", "B-1"), ("Cedar", "C-1")):
        world.put(seat, ask(id_))
    assert [c["id"] for c in world.load("posters")["cards"]] == ["A-1", "C-1"]
    out = world.load("readers")
    assert [c["id"] for c in out["cards"]] == ["B-1", "C-1"] and [s["seat"] for s in out["seats"]] == ["Birch", "Cedar"]
    assert set(out["counts"]["by_seat"]) == {"Birch", "Cedar"}
    assert [s["seat"] for s in world.load("nobody")["seats"]] == [] and world.load("nobody")["cards"] == []   # refuse
    assert [c["id"] for c in world.load()["cards"]] == ["A-1", "B-1", "C-1"]   # must pass: no group is every seat


def test_the_group_comes_from_the_config_file(world, tmp_path):
    world.write_seats(GROUPED)
    world.put("Alder", ask("A-1"))
    world.put("Birch", ask("B-1"))
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({**world.cfg(), "group": "readers"}), encoding="utf-8")
    assert [c["id"] for c in cards.load(load_config(path))["cards"]] == ["B-1"]
    path.write_text(json.dumps(world.cfg()), encoding="utf-8")
    assert [c["id"] for c in cards.load(load_config(path))["cards"]] == ["A-1", "B-1"]


def test_a_seat_outside_the_group_is_not_mentioned_even_when_its_entry_is_broken(world):
    world.write_seats({"Alder": {"groups": ["posters"], "home": "alder"}, "Birch": {"groups": ["readers"]},
                       "Cedar": 7, "Dune": {"groups": "posters", "home": "dune"}, "Elm": {"groups": [5, None]},
                       "Fir": {"groups": ["readers"], "home": "../outside"}})
    world.put("Alder", ask("A-1"))
    out = world.load("posters")
    assert [s["seat"] for s in out["seats"]] == ["Alder"] and out["problems"] == []   # must pass: nothing to say
    assert len(world.load()["problems"]) == 5   # must refuse: without a group, each of the others is a problem


def test_a_seat_in_the_group_with_no_home_is_a_problem(world):
    world.write_seats({"Alder": {"groups": ["posters"], "home": "alder"}, "Birch": {"groups": ["posters"]},
                       "Cedar": {"groups": ["readers"]}})
    out = world.load("posters")
    assert [(p["kind"], p["text"].split()[0]) for p in out["problems"]] == [("seats file", "Birch")]


# ---------------------------------------------------------------- read only, plain data, and a changed byte shows
def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def test_nothing_is_written_and_the_result_is_plain_json(world):
    world.put("Alder", ask("A-1"), cmd("A-2"), close("A-1"), "{junk")
    world.runs(run_line("Alder", "A-2"))
    world.parked(park("Alder", "A-2"), {"event": "back", "register": "J-1", "at": "t"})
    before = tree(world.root)
    out = world.load()
    assert json.loads(json.dumps(out)) == out
    assert tree(world.root) == before
    (world.root / "stray.txt").write_text("x", encoding="utf-8")   # must refuse: the comparison sees a new file
    assert tree(world.root) != before


@contextlib.contextmanager
def watching(monkeypatch):
    """Record every file opened (with its mode) and every folder listed while the block runs."""
    opened, listed = [], []
    real_open, real_scandir, real_listdir = io.open, os.scandir, os.listdir

    def open_(file, mode="r", *a, **k):
        opened.append((Path(file), mode))
        return real_open(file, mode, *a, **k)

    def lister(real):
        def inner(*a, **k):
            listed.append(a)
            return real(*a, **k)
        return inner
    with monkeypatch.context() as m:
        m.setattr(io, "open", open_)
        m.setattr(builtins, "open", open_)
        m.setattr(os, "scandir", lister(real_scandir))
        m.setattr(os, "listdir", lister(real_listdir))
        yield opened, listed


def test_the_reader_opens_only_the_named_files_for_reading_and_lists_no_folder(world, monkeypatch):
    world.put("Alder", ask("A-1"), close("A-1"))
    world.put("Birch", cmd("B-1"))   # Cedar has no file yet, and so none is opened for it
    world.runs(run_line("Birch", "B-1"))
    world.parked(park("Alder", "A-1"))
    with watching(monkeypatch) as (opened, listed):
        out = world.load()
    assert len(out["cards"]) == 2
    assert {p for p, _ in opened} == {world.seats, world.file("Alder"), world.file("Birch"),
                                      world.inbox / "runs.jsonl", world.inbox / "parked.jsonl"}
    assert {mode for _, mode in opened} <= {"r", "rb"} and listed == []


def test_the_reader_with_a_group_opens_nothing_of_a_seat_outside_it(world, monkeypatch):
    world.write_seats(GROUPED)
    world.put("Alder", ask("A-1"))
    world.put("Birch", ask("B-1"))
    with watching(monkeypatch) as (opened, listed):
        out = world.load("posters")
    assert [c["id"] for c in out["cards"]] == ["A-1"]   # must refuse: Birch's file is never opened
    assert world.file("Birch") not in {p for p, _ in opened} and world.file("Alder") in {p for p, _ in opened}


def test_the_watcher_sees_a_write_and_a_folder_listing(world, monkeypatch):
    world.put("Alder", ask("A-1"))   # must refuse: what the reader must never do is seen by the watcher
    with watching(monkeypatch) as (opened, listed):
        os.listdir(world.root)
        open(world.file("Alder"), "ab").close()
    assert len(listed) == 1 and opened == [(world.file("Alder"), "ab")]


def test_a_card_changed_by_one_byte_shows_differently(world):
    world.put("Alder", ask("A-1", title="Plain title"), ask("A-2"))
    before = world.load()["cards"]
    data = bytearray(world.file("Alder").read_bytes())
    data[data.index(b"Plain title")] ^= 0x20   # P becomes p
    world.file("Alder").write_bytes(bytes(data))
    after = world.load()["cards"]
    assert (before[0]["title"], after[0]["title"]) == ("Plain title", "plain title")
    assert after[0]["raw"] != before[0]["raw"] and after[1] == before[1]


def test_reading_twice_gives_the_same_answer(world):
    world.put("Alder", ask("A-1"), cmd("A-2"), close("A-1"))
    world.runs(run_line("Alder", "A-2"))
    assert world.load() == world.load()


WRITES = {"write_text", "write_bytes", "unlink", "mkdir", "rmdir", "rename", "replace", "touch", "chmod", "symlink_to",
          "hardlink_to", "open"}


READ_ONLY_FLAGS = {"O_RDONLY", "O_BINARY"}


def _read_only_os_open(node) -> bool:
    """True only for os.open(path, FLAGS) whose FLAGS name nothing but O_RDONLY and O_BINARY (os.O_X, or the
    getattr(os, "O_BINARY", 0) spelling), joined by |. Any other flag, a flags variable, a mode, or a bare open() is
    not this shape. The one exception the writer check allows (a document read through one checked handle)."""
    f = node.func
    if not (isinstance(f, ast.Attribute) and f.attr == "open" and isinstance(f.value, ast.Name) and f.value.id == "os"):
        return False
    if len(node.args) != 2 or node.keywords:
        return False

    def ok(e) -> bool:
        if isinstance(e, ast.BinOp) and isinstance(e.op, ast.BitOr):
            return ok(e.left) and ok(e.right)
        # O_RDONLY directly from os; O_BINARY only as getattr(os, "O_BINARY", 0), the spelling that does not raise off
        # Windows (audit of 84270dc: getattr of any other object was accepted, and os.O_BINARY raises on Linux)
        if isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name) and e.value.id == "os":
            return e.attr == "O_RDONLY"
        if (isinstance(e, ast.Call) and isinstance(e.func, ast.Name) and e.func.id == "getattr" and len(e.args) == 3
                and isinstance(e.args[0], ast.Name) and e.args[0].id == "os"
                and isinstance(e.args[1], ast.Constant) and e.args[1].value == "O_BINARY"
                and isinstance(e.args[2], ast.Constant) and e.args[2].value == 0):
            return True
        return False
    return ok(node.args[1])


def writers(source: str) -> list[str]:
    """Calls that could write or change a file: an attribute call by one of those names, or a call to open(), except
    os.open with read-only flags alone."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
            if name in WRITES and not (name == "open" and _read_only_os_open(node)):
                found.append(name)
    return found


def test_the_reader_has_no_call_that_could_write_a_file():
    assert writers(Path(cards.__file__).read_text(encoding="utf-8")) == []
    assert writers("from pathlib import Path\nPath('x').write_text('y')") == ["write_text"]   # must refuse
    assert writers("open('x', 'w')") == ["open"]


def test_the_writer_check_allows_one_read_only_os_open_and_refuses_everything_it_refused_before():
    # must-refuse, written before the check was narrowed: every open() shape it refused stays refused
    for src in ("open('x')", "open('x', 'w')", "open('x', 'rb')", "io.open('x')", "Path('x').open('rb')",
                "os.open('x', os.O_WRONLY)", "os.open('x', os.O_RDWR)", "os.open('x', os.O_RDONLY | os.O_CREAT)",
                "os.open('x', os.O_RDONLY | os.O_TRUNC)", "os.open('x', os.O_APPEND)", "os.open('x', flags)",
                "os.open('x', os.O_RDONLY, 0o644)", "os.open('x', flags=os.O_RDONLY)",
                "os.open('x', os.O_RDONLY | getattr(os, 'O_CREAT', 0))", "os.open('x', os.O_RDONLY | 64)",
                "osx.open('x', os.O_RDONLY)",
                "os.open('x', getattr(M, 'O_BINARY', 0))", "os.open('x', os.O_RDONLY | getattr(M, 'O_BINARY', 0))",
                "os.open('x', os.O_RDONLY | os.O_BINARY)", "os.open('x', getattr(os, 'O_RDONLY', 0))"):
        assert writers(src) == ["open"], src
    # must-pass: the one shape view.py uses
    assert writers("os.open(p, os.O_RDONLY | getattr(os, 'O_BINARY', 0))") == []
    assert writers("os.open(p, os.O_RDONLY)") == []


def test_the_requests_file_name_comes_from_the_config_and_defaults_to_requests_jsonl(world):
    assert FILE == "requests.jsonl"
    (world.base / HOMES["Alder"] / "inbox-cards.jsonl").write_bytes(lines_of([ask("X-1")], False, "\n"))
    world.put("Alder", ask("X-2"))
    named = cards.load({**world.cfg(), "requests": "inbox-cards.jsonl"})
    assert [c["id"] for c in named["cards"]] == ["X-1"]          # must pass: the named file is the one read
    assert [c["id"] for c in world.load()["cards"]] == ["X-2"]   # must refuse: without the key, the named file is not read


def test_a_requests_key_that_names_a_path_is_a_problem_and_the_default_is_used(world):
    world.put("Alder", ask("X-1"))
    out = cards.load({**world.cfg(), "requests": "../elsewhere/cards.jsonl"})
    assert [c["id"] for c in out["cards"]] == ["X-1"]
    assert [p["kind"] for p in out["problems"]] == ["bad field"]