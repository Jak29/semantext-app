"""The Record place: the decisions you have given, read from a register and its notes, and never written back.

Every fixture here is made up. Each check has a must-pass arm (what a correct register gives) and a must-refuse arm (a
planted defect the reader has to report, or a wrong answer the reader must not give). Where a fix is pinned, the two arms
are two tests with the same name and the endings `__must_pass` and `__must_refuse`, so a run against an older reader
shows which arm caught it. A must-refuse arm names the answer it refuses (a decision lost, a status left in force) and, after
that, what must still be said."""
import json
import os
import stat

import pytest

from semantext.sources import MAX_LINE, record


def decision(id_, **more):
    """One decision as the register keeps it. The id gives the day, as the register's own ids do."""
    day = f"{id_[2:6]}-{id_[6:8]}-{id_[8:10]}"
    return {"id": id_, "date": day, "time_utc": None, "to": "Ana", "subject": f"subject of {id_}", "status": "in force",
            "words": f"words of {id_}", "offer": None, "reading": f"reading of {id_}",
            "source": "box@abc1234:NOTES.md:7", "supersedes": [], "added_by": "Ben", "added": day, **more}


def note(on, **more):
    return {"on": on, "text": f"text on {on}", "quote": f"quote on {on}", "source": "box@abc1234:NOTES.md:3-4",
            "added_by": "Ben", "added": "2099-10-14", **more}


def dumps(row) -> str:
    """A row as one JSON line, non-ASCII text kept as it is, except the three characters the register's own way of cutting
    lines would cut at: those are written as escapes, so that a value holding one still reads back whole."""
    text = json.dumps(row, ensure_ascii=False)
    for ch in "\u2028\u2029\u0085":
        text = text.replace(ch, "\\u%04x" % ord(ch))
    return text


def write(path, *rows):
    """A JSON-lines file of the rows. A row that is a str or bytes is written as it is: a damaged line."""
    parts = [r if isinstance(r, bytes) else (r if isinstance(r, str) else dumps(r)).encode() for r in rows]
    path.write_bytes(b"\n".join(parts) + b"\n")
    return str(path)


def read(tmp_path, *rows, notes=()):
    cfg = {"register": write(tmp_path / "register.jsonl", *rows)}
    if notes:
        cfg["notes"] = write(tmp_path / "notes.jsonl", *notes)
    return record.load(cfg)


def read_bytes(tmp_path, data, name="register.jsonl"):
    (tmp_path / name).write_bytes(data)
    return record.load({"register": str(tmp_path / name)})


def kinds(out):
    return [p["kind"] for p in out["problems"]]


def where(out):
    return [(p["line"], p["kind"]) for p in out["problems"]]


def entry(out, id_):
    return next(e for e in out["entries"] if e["id"] == id_)


def thread(out, subject):
    return next(t for t in out["threads"] if t["subject"] == subject)


# ---------------------------------------------------------------- off, and the words as written
def test_a_source_with_no_register_is_off_and_one_with_a_register_is_not(tmp_path):
    off = record.load({})
    assert off["off"] is True and off["entries"] == [] and off["threads"] == [] and off["problems"] == []
    assert record.load({"notes": str(tmp_path / "notes.jsonl")})["off"] is True      # notes alone are not a record
    on = read(tmp_path, decision("J-20991001-1"))                                      # must-refuse: this one is on
    assert on["off"] is False and [e["id"] for e in on["entries"]] == ["J-20991001-1"]


def test_a_register_with_no_lines_is_a_record_with_nothing_in_it_and_no_problem(tmp_path):
    (tmp_path / "register.jsonl").write_bytes(b"\n\n")
    (tmp_path / "notes.jsonl").write_bytes(b"")
    out = record.load({"register": str(tmp_path / "register.jsonl"), "notes": str(tmp_path / "notes.jsonl")})
    assert out["off"] is False and out["entries"] == [] and out["threads"] == [] and out["cards"] == {}
    assert out["problems"] == [] and out["counts"]["entries"] == 0 and out["counts"]["notes"] == 0
    # must-refuse: the same files are not "off" and not "missing": a missing file is its own problem
    assert kinds(record.load({"register": str(tmp_path / "gone.jsonl")})) == ["missing-file"]


ODD = (" Yes\N{NO-BREAK SPACE}to \N{LEFT DOUBLE QUOTATION MARK}both\N{RIGHT DOUBLE QUOTATION MARK},  but not\t"
       "the third \N{LINE SEPARATOR} line \N{EM DASH} \N{GRINNING FACE} \\ \"quoted\" ")


def test_your_words_the_offer_the_reading_and_the_subject_pass_on_exactly_as_written(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", words=ODD, offer=ODD + "1", reading=ODD + "2", subject=ODD + "3"))
    e = out["entries"][0]
    assert (e["words"], e["offer"], e["reading"], e["subject"]) == (ODD, ODD + "1", ODD + "2", ODD + "3")
    assert out["problems"] == []
    # must-refuse: the fixture catches a reader that tidied the spaces
    assert " ".join(ODD.split()) != ODD


def test_an_offer_and_a_time_are_kept_as_the_register_keeps_them(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", offer="", time_utc="21:56:29"),
               decision("J-20991001-2", offer="   "), decision("J-20991001-3", offer="1, take it", time_utc="12:52"),
               decision("J-20991001-4"))
    assert [e["offer"] for e in out["entries"]] == ["", "   ", "1, take it", None]   # nothing is tidied or guessed
    assert [e["time"] for e in out["entries"]] == ["21:56:29", None, "12:52", None]
    assert out["problems"] == []


def test_a_decision_and_a_note_are_passed_on_field_by_field(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", time_utc="12:52", offer="1, take it", added_by="Cleo", added="2099-10-02"),
               decision("J-20991002-1", supersedes=["J-20991001-1"]),
               notes=[note("J-20991001-1", added_by="Dov", added="2099-10-03")])
    assert out["entries"][0] == {
        "id": "J-20991001-1", "line": 1, "date": "2099-10-01", "time": "12:52", "to": "Ana",
        "subject": "subject of J-20991001-1", "words": "words of J-20991001-1", "offer": "1, take it",
        "reading": "reading of J-20991001-1", "source": "box@abc1234:NOTES.md:7",
        "pin": {"repo": "box", "commit": "abc1234", "file": "NOTES.md", "line": 7, "last_line": 7},
        "stored_status": "in force", "computed_status": "superseded", "supersedes": [], "superseded_by": ["J-20991002-1"],
        "notes": [{"line": 1, "on": "J-20991001-1", "text": "text on J-20991001-1", "quote": "quote on J-20991001-1",
                   "source": "box@abc1234:NOTES.md:3-4",
                   "pin": {"repo": "box", "commit": "abc1234", "file": "NOTES.md", "line": 3, "last_line": 4},
                   "added_by": "Dov", "added": "2099-10-03"}],
        "mentions": {}, "added_by": "Cleo", "added": "2099-10-02"}
    assert out["entries"][1]["supersedes"] == ["J-20991001-1"] and out["entries"][1]["superseded_by"] == []
    assert set(out) == {"off", "notes_off", "files", "entries", "threads", "counts", "cards", "problems"}
    assert out["counts"] == {"entries": 2, "threads": 2, "notes": 1, "cards": 0,
                             "by_status": {"in force": 1, "parked": 0, "reopened": 0, "superseded": 1},
                             "stored": {"in force": 2, "parked": 0, "reopened": 0}}
    assert out["threads"][0] == {"subject": "subject of J-20991002-1", "entries": ["J-20991002-1"], "live": ["J-20991002-1"],
                                 "latest": "J-20991002-1", "current": "in force", "mixed": False, "to": ["Ana"],
                                 "first": "2099-10-02", "last": "2099-10-02"}
    # must-refuse: a field that is not given is None, not made up
    bare = read(tmp_path, {"id": "J-20991001-1"})
    assert [bare["entries"][0][k] for k in ("date", "time", "to", "subject", "words", "offer", "reading", "source", "pin",
                                           "stored_status", "added_by", "added")] == [None] * 12


def test_the_source_is_split_into_its_pin_and_kept_whole(tmp_path):
    full = "box@" + "0123456789abcdef" * 2 + "0123456789abcdef"[:8] + ":docs/NOTES.md:12-15"
    out = read(tmp_path, decision("J-20991001-1", source=full), decision("J-20991001-2", source="box@abc1234:A.md:9"))
    a, b = out["entries"]
    assert a["source"] == full and a["pin"] == {"repo": "box", "commit": full[4:44], "file": "docs/NOTES.md",
                                                "line": 12, "last_line": 15}
    assert b["pin"] == {"repo": "box", "commit": "abc1234", "file": "A.md", "line": 9, "last_line": 9}
    assert out["problems"] == []
    # must-refuse: a source that is not a pin keeps its words and has no pin, and is reported
    bad = read(tmp_path, decision("J-20991001-1", source="box@abc12:A.md:9"), decision("J-20991001-2", source="no pin"))
    assert [e["pin"] for e in bad["entries"]] == [None, None] and kinds(bad) == ["bad-source", "bad-source"]
    assert [e["source"] for e in bad["entries"]] == ["box@abc12:A.md:9", "no pin"]


def test_a_source_with_anything_after_the_pin_is_not_a_pin(tmp_path):
    ok = read(tmp_path, decision("J-20991001-1", source="box@abc1234:A.md:9"))
    assert ok["entries"][0]["pin"]["line"] == 9 and ok["problems"] == []
    # must-refuse: words after the line, or a letter stuck to it, make it no pin (a pin has to be all of the source)
    bad = read(tmp_path, decision("J-20991001-1", source="box@abc1234:A.md:9 and more"),
               decision("J-20991001-2", source="box@abc1234:A.md:9x"), decision("J-20991001-3", source="see box@abc1234:A.md:9"))
    assert [e["pin"] for e in bad["entries"]] == [None, None, None] and kinds(bad) == ["bad-source"] * 3


# ---------------------------------------------------------------- status: stored, and computed
def test_a_decision_is_superseded_when_another_names_it_and_keeps_the_status_it_was_given(tmp_path):
    out = read(tmp_path,
               decision("J-20991001-1", status="parked", subject="the gate"),
               decision("J-20991002-1", status="reopened", subject="the gate", supersedes=["J-20991001-1"]),
               decision("J-20991003-1", status="parked", subject="the gate", supersedes=["J-20991002-1"]),
               decision("J-20991004-1", status="in force", subject="the roof"))
    stored = {e["id"]: e["stored_status"] for e in out["entries"]}
    computed = {e["id"]: e["computed_status"] for e in out["entries"]}
    assert stored == {"J-20991001-1": "parked", "J-20991002-1": "reopened", "J-20991003-1": "parked",
                      "J-20991004-1": "in force"}
    assert computed == {"J-20991001-1": "superseded", "J-20991002-1": "superseded", "J-20991003-1": "parked",
                        "J-20991004-1": "in force"}
    assert out["counts"]["by_status"] == {"in force": 1, "parked": 1, "reopened": 0, "superseded": 2}
    assert out["counts"]["stored"] == {"in force": 1, "parked": 2, "reopened": 1}
    assert out["counts"]["entries"] == 4 and out["problems"] == []


def test_a_decision_nothing_names_is_never_called_superseded(tmp_path):
    # must-refuse: a reopening that names nothing does not retire the parking before it (the register's own rule)
    out = read(tmp_path, decision("J-20991001-1", status="parked", subject="the gate"),
               decision("J-20991002-1", status="reopened", subject="the gate"))
    assert [e["computed_status"] for e in out["entries"]] == ["parked", "reopened"]
    assert all(e["superseded_by"] == [] for e in out["entries"])


def test_a_status_the_register_does_not_use_is_reported_and_still_shown(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", status="maybe"), decision("J-20991001-2"))
    assert kinds(out) == ["unknown-status"] and out["problems"][0]["line"] == 1       # the clean one adds none
    assert "maybe" in out["problems"][0]["text"]
    assert entry(out, "J-20991001-1")["computed_status"] == "maybe" and out["counts"]["by_status"]["maybe"] == 1


# ---------------------------------------------------------------- the reverse relation
def test_every_supersedes_link_is_drawn_back_and_the_counts_match_both_ways(tmp_path):
    out = read(tmp_path,
               decision("J-20991001-1"), decision("J-20991001-2"), decision("J-20991001-3"),
               decision("J-20991002-1", supersedes=["J-20991001-1", "J-20991001-2"]),
               decision("J-20991003-1", supersedes=["J-20991001-2"]))
    back = {e["id"]: e["superseded_by"] for e in out["entries"]}
    assert back == {"J-20991001-1": ["J-20991002-1"], "J-20991001-2": ["J-20991002-1", "J-20991003-1"],
                    "J-20991001-3": [], "J-20991002-1": [], "J-20991003-1": []}      # all of them, in file order
    drawn = {(by, e["id"]) for e in out["entries"] for by in e["superseded_by"]}
    named = {(e["id"], old) for e in out["entries"] for old in e["supersedes"]}
    assert drawn == named and len(drawn) == 3
    assert sum(len(e["superseded_by"]) for e in out["entries"]) == sum(len(e["supersedes"]) for e in out["entries"])
    assert out["problems"] == []
    # must-refuse: nothing is superseded unless something names it
    assert entry(out, "J-20991001-3")["computed_status"] == "in force"


def test_a_link_to_a_decision_that_is_not_there_is_reported_and_not_drawn(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", supersedes=["J-20990101-9"]))
    assert kinds(out) == ["dangling-supersedes"] and out["problems"][0]["line"] == 2
    assert "J-20990101-9" in out["problems"][0]["text"]
    assert all(e["superseded_by"] == [] for e in out["entries"])
    assert entry(out, "J-20991002-1")["supersedes"] == ["J-20990101-9"]               # what it says is passed on
    # must-pass: the same link to a decision that is there raises nothing
    ok = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", supersedes=["J-20991001-1"]))
    assert ok["problems"] == [] and entry(ok, "J-20991001-1")["superseded_by"] == ["J-20991002-1"]


def test_a_link_to_itself_or_to_a_later_decision_is_drawn_as_the_tool_draws_it_and_reported(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", supersedes=["J-20991002-1"]),
               decision("J-20991002-1", supersedes=["J-20991002-1"]))
    assert kinds(out) == ["supersedes-not-earlier", "supersedes-not-earlier"]
    assert entry(out, "J-20991002-1")["superseded_by"] == ["J-20991001-1", "J-20991002-1"]
    assert entry(out, "J-20991002-1")["computed_status"] == "superseded"


def test_a_supersedes_that_is_not_a_clean_list_of_ids_is_reported_and_draws_nothing_it_cannot_stand_behind(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991001-2"),
               decision("J-20991002-1", supersedes="J-20991001-1"),                    # a bare id, not a list
               decision("J-20991002-2", supersedes=["J-20991001-2", "J-20991001-2", 7, ""]))
    assert kinds(out) == ["bad-supersedes", "bad-supersedes", "bad-supersedes", "bad-supersedes"]
    assert entry(out, "J-20991001-1")["superseded_by"] == []                           # not guessed from a bare id
    assert entry(out, "J-20991002-2")["supersedes"] == ["J-20991001-2"]                # the good id counted once
    assert entry(out, "J-20991001-2")["superseded_by"] == ["J-20991002-2"]


def test_a_supersedes_kept_as_an_object__must_pass(tmp_path):
    # the register's tool reads the keys of an object as the ids it names, so a link it counts is a link this reader counts
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991001-2"), decision("J-20991001-3"),
               decision("J-20991002-1", supersedes={"J-20991001-1": "why", "J-20991001-2": "why too"}))
    assert entry(out, "J-20991002-1")["supersedes"] == ["J-20991001-1", "J-20991001-2"]
    assert [entry(out, i)["computed_status"] for i in ("J-20991001-1", "J-20991001-2", "J-20991001-3")] == [
        "superseded", "superseded", "in force"]
    assert entry(out, "J-20991001-2")["superseded_by"] == ["J-20991002-1"]
    assert where(out) == [(4, "bad-supersedes")] and "object" in out["problems"][0]["text"]       # and the shape is said


def test_a_supersedes_kept_as_an_object__must_refuse(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", supersedes={"J-20991001-1": "why"}))
    assert entry(out, "J-20991001-1")["computed_status"] != "in force"     # the answer refused: a decision left in force
    assert entry(out, "J-20991001-1")["superseded_by"] != []               # that the tool calls superseded
    # and what is not a list or an object still draws nothing, and is still said
    bad = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", supersedes="J-20991001-1"),
               decision("J-20991003-1", supersedes=5), decision("J-20991004-1", supersedes=True))
    assert kinds(bad) == ["bad-supersedes"] * 3 and entry(bad, "J-20991001-1")["superseded_by"] == []


# ---------------------------------------------------------------- notes
def test_a_note_belongs_to_the_decision_it_names_and_changes_no_status(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991001-2"),
               notes=[note("J-20991001-2"), note("J-20991001-1", quote="q1"), note("J-20991001-2", quote="q2")])
    assert [n["quote"] for n in entry(out, "J-20991001-2")["notes"]] == ["quote on J-20991001-2", "q2"]
    assert [n["quote"] for n in entry(out, "J-20991001-1")["notes"]] == ["q1"]
    n = entry(out, "J-20991001-1")["notes"][0]
    assert (n["on"], n["line"], n["added"], n["added_by"], n["text"]) == (
        "J-20991001-1", 2, "2099-10-14", "Ben", "text on J-20991001-1")
    assert n["pin"] == {"repo": "box", "commit": "abc1234", "file": "NOTES.md", "line": 3, "last_line": 4}
    assert out["counts"]["notes"] == 3 and out["problems"] == [] and out["notes_off"] is False
    assert [e["computed_status"] for e in out["entries"]] == ["in force", "in force"]
    # must-refuse: with no notes file the decisions are read and the page is told the notes are off
    bare = read(tmp_path, decision("J-20991001-1"))
    assert bare["notes_off"] is True and bare["files"]["notes"] is None and bare["counts"]["notes"] == 0


def test_a_note_on_a_decision_that_is_not_there_is_reported_and_attached_to_nothing(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"),
               notes=[note("J-20991001-1"), note("J-20990101-1"), {"text": "names nothing"}, "not json at all"])
    assert out["counts"]["notes"] == 1 and len(entry(out, "J-20991001-1")["notes"]) == 1
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [
        (2, "note-unattached"), (3, "missing-field"), (3, "note-unattached"), (4, "not-json")]
    assert all(p["source"].endswith("notes.jsonl") for p in out["problems"])
    assert "J-20990101-1" in out["problems"][0]["text"]


# ---------------------------------------------------------------- a repeated id, no id
def repeated_id(tmp_path):
    return read(tmp_path,
                decision("J-20991001-1", subject="the gate"),                                              # 1 the target
                decision("J-20991002-1", subject="the roof"),                                              # 2
                decision("J-20991002-1", status="parked", subject="the roof", supersedes=["J-20991001-1"]),   # 3 same id as 2
                decision("J-20991003-1", subject="the porch", supersedes=["J-20991002-1"]),                # 4 names that id
                notes=[note("J-20991002-1")])


def test_an_id_used_on_two_lines_keeps_both_and_counts_every_link__must_pass(tmp_path):
    # the register's tool keeps every line and works a status out by id, so both lines of a repeated id are decisions
    out = repeated_id(tmp_path)
    assert [e["line"] for e in out["entries"]] == [1, 2, 3, 4]
    assert entry(out, "J-20991001-1")["computed_status"] == "superseded"                 # by the line that repeats an id
    assert entry(out, "J-20991001-1")["superseded_by"] == ["J-20991002-1"]
    held = [e for e in out["entries"] if e["id"] == "J-20991002-1"]
    assert [e["computed_status"] for e in held] == ["superseded", "superseded"]          # a link to an id reaches both
    assert [e["superseded_by"] for e in held] == [["J-20991003-1"], ["J-20991003-1"]]
    assert [e["supersedes"] for e in out["entries"]] == [[], [], ["J-20991001-1"], ["J-20991002-1"]]
    assert out["counts"]["by_status"] == {"in force": 1, "parked": 0, "reopened": 0, "superseded": 3}
    assert out["counts"]["stored"] == {"in force": 3, "parked": 1, "reopened": 0}
    assert [len(e["notes"]) for e in held] == [1, 1] and out["counts"]["notes"] == 1     # a note shows under both, counts once
    # a link from between the two lines names an earlier decision (the first holder), so it is not called a link to a later one
    between = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", supersedes=["J-20991001-1"]),
                   decision("J-20991001-1", words="again"))
    assert where(between) == [(3, "duplicate-id")]
    assert [e["computed_status"] for e in between["entries"]] == ["superseded", "in force", "superseded"]


def test_an_id_used_on_two_lines_keeps_both_and_counts_every_link__must_refuse(tmp_path):
    out = repeated_id(tmp_path)
    assert len(out["entries"]) == 4                                                       # the answer refused: a decision lost
    assert entry(out, "J-20991001-1")["computed_status"] != "in force"                     # and a status left in force
    assert out["counts"]["by_status"]["in force"] != 3                                     # that the tool calls superseded
    # and the repeat is not silent: said once, on the later line, naming the earlier one
    assert where(out) == [(3, "duplicate-id")] and "line 2" in out["problems"][0]["text"]
    assert "both are kept" in out["problems"][0]["text"]
    # a line that is not a decision does not share an id with anything
    junk = read(tmp_path, decision("J-20991001-1"), '{"id": "J-20991001-1", "words": "cut off', decision("J-20991002-1"))
    assert where(junk) == [(2, "not-json")] and [e["id"] for e in junk["entries"]] == ["J-20991001-1", "J-20991002-1"]


def no_usable_id(tmp_path):
    no_key = {k: v for k, v in decision("J-20991004-1", supersedes=["J-20991001-2"]).items() if k != "id"}
    return read(tmp_path,
                decision("J-20991001-1"), decision("J-20991001-2"),
                decision("J-20991003-1", id="", supersedes=["J-20991001-1"]),            # 3 an empty id
                no_key,                                                                  # 4 no id at all
                decision("J-20991005-1", id=7),                                          # 5 an id that is a number
                notes=[note(""), {"text": "t", "quote": "q", "source": "box@abc1234:NOTES.md:3"}])


def test_a_decision_with_no_usable_id_is_kept_and_its_links_count__must_pass(tmp_path):
    # the register's tool keeps an empty id and counts what it supersedes; a line with no id at all it cannot name
    out = no_usable_id(tmp_path)
    assert [e["line"] for e in out["entries"]] == [1, 2, 3, 4, 5]
    assert [e["id"] for e in out["entries"]] == ["J-20991001-1", "J-20991001-2", "", None, 7]       # as written
    assert entry(out, "J-20991001-1")["computed_status"] == "superseded"
    assert entry(out, "J-20991001-1")["superseded_by"] == [""]
    assert entry(out, "J-20991001-2")["computed_status"] == "superseded"
    assert entry(out, "J-20991001-2")["superseded_by"] == [None]
    assert out["counts"]["by_status"] == {"in force": 3, "parked": 0, "reopened": 0, "superseded": 2}
    assert [e["supersedes"] for e in out["entries"]][2:4] == [["J-20991001-1"], ["J-20991001-2"]]
    assert json.loads(json.dumps(out)) == out


def test_a_decision_with_no_usable_id_is_kept_and_its_links_count__must_refuse(tmp_path):
    out = no_usable_id(tmp_path)
    assert len(out["entries"]) == 5                                                        # the answer refused: lines lost
    assert entry(out, "J-20991001-1")["computed_status"] != "in force"                      # and decisions left in force
    assert entry(out, "J-20991001-2")["computed_status"] != "in force"                      # that the tool supersedes
    # and each is said, once; nothing can refer to it, so a note on it attaches to nothing
    assert where(out) == [(3, "no-id"), (4, "no-id"), (5, "no-id"), (1, "missing-field"), (1, "note-unattached"),
                          (2, "missing-field"), (2, "note-unattached")]
    assert out["counts"]["notes"] == 0 and all(e["notes"] == [] for e in out["entries"])
    assert "names no decision" in out["problems"][4]["text"] and "names no decision" in out["problems"][6]["text"]


# ---------------------------------------------------------------- a line of any length
def test_a_decision_of_any_length_is_read_whole_with_its_links__must_pass(tmp_path):
    # the register's tool has no limit on a line, and your words are as long as they were
    over, far = "x" * (MAX_LINE + 1), "y" * (3 * MAX_LINE)
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", words=over, supersedes=["J-20991001-1"]),
               decision("J-20991003-1", reading=far, supersedes=["J-20991002-1"]))
    assert [len(e["words"]) for e in out["entries"][1:2]] == [MAX_LINE + 1] and len(out["entries"][2]["reading"]) == 3 * MAX_LINE
    assert [e["computed_status"] for e in out["entries"]] == ["superseded", "superseded", "in force"]
    assert out["problems"] == [] and out["counts"]["entries"] == 3


def test_a_decision_of_any_length_is_read_whole_with_its_links__must_refuse(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"), decision("J-20991002-1", words="x" * (MAX_LINE + 1), supersedes=["J-20991001-1"]))
    assert len(out["entries"]) == 2 and "too-long" not in kinds(out)                      # the answer refused: a decision lost
    assert entry(out, "J-20991001-1")["computed_status"] != "in force"                      # and a status left in force
    # a long line that is not a decision is still said, as what it is, without carrying the line in the problem
    bad = read(tmp_path, "z" * (3 * MAX_LINE), decision("J-20991001-1"))
    assert where(bad) == [(1, "not-json")] and len(bad["problems"][0]["text"]) <= 300
    assert [e["id"] for e in bad["entries"]] == ["J-20991001-1"]


# ---------------------------------------------------------------- values that are not text
def not_text(tmp_path):
    return read(tmp_path,
                decision("J-20991001-1", offer=["1, take it", "2, wait for I-20991001-120000"], to=["Ana", "Ben"],
                         time_utc=12),
                decision("J-20991002-1", subject=["a", "list"], words=5),
                decision("J-20991003-1", subject=["a", "list"]),
                decision("J-20991004-1", to=["Ana", "Ben"], subject="the roof"))


def test_a_value_that_is_not_text_is_passed_on_unchanged_and_said__must_pass(tmp_path):
    out = not_text(tmp_path)
    one, two, three, four = out["entries"]
    assert (one["offer"], one["to"], one["time"]) == (["1, take it", "2, wait for I-20991001-120000"], ["Ana", "Ben"], 12)
    assert (two["subject"], two["words"]) == (["a", "list"], 5)                              # as written, not tidied
    assert where(out) == [(1, "bad-field"), (1, "bad-field"), (1, "bad-field"), (2, "bad-field"), (2, "bad-field"),
                          (3, "bad-field"), (4, "bad-field")]
    assert "to should be text, not list" in out["problems"][0]["text"] and "offer" in out["problems"][1]["text"]
    assert "time_utc should be text, not int" in out["problems"][2]["text"]
    assert thread(out, ["a", "list"])["entries"] == ["J-20991002-1", "J-20991003-1"]        # the same list, the same thread
    assert thread(out, "the roof")["to"] == [["Ana", "Ben"]]
    assert out["cards"] == {"I-20991001-120000": ["J-20991001-1"]}                           # the card inside the offer is found
    assert one["mentions"] == {"I-20991001-120000": ["offer"]}
    assert json.loads(json.dumps(out)) == out


def test_a_value_that_is_not_text_is_passed_on_unchanged_and_said__must_refuse(tmp_path):
    out = not_text(tmp_path)
    one, two = out["entries"][:2]
    assert one["offer"] is not None and one["to"] is not None and one["time"] is not None    # the answer refused: values dropped
    assert two["words"] is not None and two["subject"] is not None
    assert "missing-field" not in kinds(out)                                                  # a value that is there is not missing
    # a value that is not there, or is only white space, still is
    gone = read(tmp_path, decision("J-20991001-1", words=None, to="  "))
    assert kinds(gone) == ["missing-field"] and "words" in gone["problems"][0]["text"] and "to" in gone["problems"][0]["text"]


def test_a_decision_made_of_values_of_every_kind_is_read_and_passed_on(tmp_path):
    odd = decision("J-20991001-1", id=["x"], date=5, to={"a": 1}, subject=[], status=["parked"], words=True, reading=1.5,
                   source={}, offer=[[]], time_utc={}, supersedes=[["J-20991001-2"]], added_by=[], added=7)
    out = read(tmp_path, odd, decision("J-20991001-2"), decision("J-20991001-3", date=["2099"], subject=[], status={"a": 1}))
    first, second, third = out["entries"]
    assert (first["id"], first["date"], first["to"], first["subject"], first["words"], first["reading"]) == (
        ["x"], 5, {"a": 1}, [], True, 1.5)
    assert (first["stored_status"], first["offer"], first["time"], first["added"]) == (["parked"], [[]], {}, 7)
    assert first["supersedes"] == [] and second["superseded_by"] == []                    # an item that is not an id draws nothing
    assert thread(out, [])["entries"] == [["x"], "J-20991001-3"]                            # the same value, the same thread
    assert out["counts"]["stored"]['["parked"]'] == 1 and out["counts"]["stored"]['{"a": 1}'] == 1
    assert out["counts"]["by_status"]["in force"] == 1 and out["counts"]["entries"] == 3
    assert json.loads(json.dumps(out)) == out
    # must-refuse: a value of the wrong kind never makes the reader stop: every line that is an object is a decision
    assert set(kinds(out)) >= {"no-id", "bad-field", "unknown-status", "bad-supersedes"}
    assert second["id"] == "J-20991001-2" and third["id"] == "J-20991001-3"


# ---------------------------------------------------------------- threads
def test_a_subject_is_a_thread_and_its_latest_live_decision_gives_its_status(tmp_path):
    out = read(tmp_path,
               decision("J-20991002-1", subject="the gate", status="in force"),
               decision("J-20990930-1", subject="the gate", status="parked"),         # said earlier, written down later
               decision("J-20991003-1", subject="the roof", status="in force"),
               decision("J-20991004-1", subject="the gate", status="reopened", supersedes=["J-20990930-1"]),
               decision("J-20991005-1", subject="the porch", status="in force"),
               decision("J-20991001-9", subject="the porch", status="parked"))        # last in the file, oldest by date
    gate, porch = thread(out, "the gate"), thread(out, "the porch")
    assert gate["entries"] == ["J-20990930-1", "J-20991002-1", "J-20991004-1"]        # by date, not place in the file
    assert gate["live"] == ["J-20991002-1", "J-20991004-1"] and gate["latest"] == "J-20991004-1"
    assert gate["current"] == "reopened" and gate["mixed"] is True and gate["to"] == ["Ana"]
    assert (gate["first"], gate["last"]) == ("2099-09-30", "2099-10-04")
    assert porch["latest"] == "J-20991005-1" and porch["current"] == "in force"
    # must-refuse: the last line of the file is not the latest decision
    assert porch["entries"][-1] == "J-20991005-1" and porch["current"] != "parked"
    assert [t["subject"] for t in out["threads"]] == ["the porch", "the gate", "the roof"]    # the newest touched first
    assert out["counts"]["threads"] == 3


def test_decisions_given_on_one_day_keep_the_order_they_were_written_down(tmp_path):
    out = read(tmp_path, decision("J-20991001-2", subject="the gate", status="parked", time_utc="09:00"),
               decision("J-20991001-1", subject="the gate", status="in force", time_utc="18:00"))
    gate = thread(out, "the gate")
    assert gate["entries"] == ["J-20991001-2", "J-20991001-1"]       # the register's own order stands: no time is read
    assert gate["latest"] == "J-20991001-1" and gate["current"] == "in force"
    # must-refuse: swapping the lines swaps the answer, so the tie is broken by the file and by nothing else
    swapped = read(tmp_path, decision("J-20991001-1", subject="the gate", status="in force", time_utc="18:00"),
                   decision("J-20991001-2", subject="the gate", status="parked", time_utc="09:00"))
    assert thread(swapped, "the gate")["latest"] == "J-20991001-2" and thread(swapped, "the gate")["current"] == "parked"


def test_a_thread_names_each_seat_it_was_spoken_to_once_in_the_order_it_was_given(tmp_path):
    out = read(tmp_path, decision("J-20991002-1", subject="the gate", to="Ben"),
               decision("J-20991001-1", subject="the gate", to="Ana"),
               decision("J-20991003-1", subject="the gate", to="Ben"),
               decision("J-20991004-1", subject="the gate", to=""),               # no seat: reported, and not a name
               decision("J-20991005-1", subject="the roof", to="Ana"), decision("J-20991006-1", subject="the roof", to="Ana"))
    assert thread(out, "the gate")["to"] == ["Ana", "Ben"] and kinds(out) == ["missing-field"]
    # must-refuse: a thread spoken to one seat names it once, not once per decision
    assert thread(out, "the roof")["to"] == ["Ana"]


def test_live_decisions_that_agree_are_not_mixed(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", subject="the gate"), decision("J-20991002-1", subject="the gate"),
               decision("J-20991003-1", subject="the roof", status="parked"),
               decision("J-20991004-1", subject="the roof", status="in force"))
    assert thread(out, "the gate")["mixed"] is False and thread(out, "the roof")["mixed"] is True


def test_only_live_decisions_can_make_a_thread_mixed(tmp_path):
    out = read(tmp_path,
               decision("J-20991001-1", subject="the gate", status="parked"),                # superseded below: not live
               decision("J-20991002-1", subject="the gate", status="in force", supersedes=["J-20991001-1"]),
               decision("J-20991003-1", subject="the gate", status="in force"),
               decision("J-20991004-1", subject="the roof", status="parked"),
               decision("J-20991005-1", subject="the roof", status="in force"))
    gate = thread(out, "the gate")
    assert gate["live"] == ["J-20991002-1", "J-20991003-1"] and gate["mixed"] is False    # the parking was retired
    # must-refuse: two live decisions that disagree are mixed, though the same disagreement in a retired one is not
    assert thread(out, "the roof")["mixed"] is True


def test_a_subject_with_every_decision_superseded_is_superseded_with_no_latest(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", subject="the old plan"),
               decision("J-20991002-1", subject="the new plan", supersedes=["J-20991001-1"]))
    old, new = thread(out, "the old plan"), thread(out, "the new plan")
    assert old["live"] == [] and old["latest"] is None and old["current"] == "superseded" and old["mixed"] is False
    assert new["latest"] == "J-20991002-1" and new["current"] == "in force"          # must-refuse: only the old is


def test_decisions_with_no_subject_stand_alone(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", subject=""), decision("J-20991001-2", subject=""),
               decision("J-20991001-3", subject="   "), decision("J-20991001-4", subject=None))
    assert [t["entries"] for t in out["threads"]] == [["J-20991001-4"], ["J-20991001-3"], ["J-20991001-2"], ["J-20991001-1"]]
    assert out["counts"]["threads"] == 4                  # nothing says what a decision with no subject shares with another


def test_subjects_are_grouped_by_their_exact_text__must_pass(tmp_path):
    # the register's tool never merges subjects, and neither does a thread: the same text is one subject
    out = read(tmp_path, decision("J-20991001-1", subject="the garden gate"), decision("J-20991001-2", subject="the roof"),
               decision("J-20991001-3", subject="the garden gate"))
    assert thread(out, "the garden gate")["entries"] == ["J-20991001-1", "J-20991001-3"]
    assert out["counts"]["threads"] == 2


def test_subjects_are_grouped_by_their_exact_text__must_refuse(tmp_path):
    spelled = ("the garden gate", "the  garden gate", "the\N{NO-BREAK SPACE}garden gate", "the garden gate ", " the garden gate",
               "the garden\tgate", "The garden gate", "the garden gate\n")
    out = read(tmp_path, *[decision(f"J-20991001-{n}", subject=s) for n, s in enumerate(spelled, 1)])
    # the answer refused: spaces made even, or a no-break space made a space, so that several subjects become one
    assert out["counts"]["threads"] == len(spelled)
    assert sorted(t["subject"] for t in out["threads"]) == sorted(spelled)                  # each as it was written
    assert all(len(t["entries"]) == 1 for t in out["threads"])
    # and a subject differing in nothing at all is still the same subject
    again = read(tmp_path, decision("J-20991001-1", subject=spelled[1]), decision("J-20991001-2", subject=spelled[1]))
    assert again["counts"]["threads"] == 1


# ---------------------------------------------------------------- card ids
def test_card_ids_are_indexed_to_every_decision_that_mentions_them(tmp_path):
    out = read(tmp_path,
               decision("J-20991014-1", words="I-20991014-140041 1, take it",
                        reading="Card T-20991013-101500 (the first)",
                        source="box@abc1234:cards/GK-20991013-143522.json:1"),
               decision("J-20991014-2", offer='the offer on I-20991014-140041: "yes"',
                        subject="about G-20991012-090000"),
               decision("J-20991014-3", reading="see J-20991014-1, and card O-20991014-090000."),
               notes=[note("J-20991014-3", text="quotes the offer of K-20991014-090000")])
    assert out["cards"] == {"G-20991012-090000": ["J-20991014-2"], "GK-20991013-143522": ["J-20991014-1"],
                            "I-20991014-140041": ["J-20991014-1", "J-20991014-2"],
                            "K-20991014-090000": ["J-20991014-3"], "O-20991014-090000": ["J-20991014-3"],
                            "T-20991013-101500": ["J-20991014-1"]}
    assert entry(out, "J-20991014-1")["mentions"] == {"I-20991014-140041": ["words"], "T-20991013-101500": ["reading"],
                                                     "GK-20991013-143522": ["source"]}
    assert entry(out, "J-20991014-2")["mentions"] == {"I-20991014-140041": ["offer"], "G-20991012-090000": ["subject"]}
    assert entry(out, "J-20991014-3")["mentions"] == {"O-20991014-090000": ["reading"], "K-20991014-090000": ["note"]}
    assert out["counts"]["cards"] == 6


def test_a_card_id_named_twice_is_listed_once_for_the_field_and_once_for_the_decision(tmp_path):
    out = read(tmp_path, decision("J-20991014-1", reading="O-20991014-090000 again O-20991014-090000, and in the offer too",
                                  offer="O-20991014-090000 twice: O-20991014-090000"))
    assert entry(out, "J-20991014-1")["mentions"] == {"O-20991014-090000": ["offer", "reading"]}      # each field once
    assert out["cards"] == {"O-20991014-090000": ["J-20991014-1"]}
    # must-refuse: one decision is not listed under a card once for each time the card is named
    assert out["counts"]["cards"] == 1 and len(out["cards"]["O-20991014-090000"]) == 1


def test_a_card_id_in_a_notes_quote_or_source_is_found_as_well_as_one_in_its_text(tmp_path):
    out = read(tmp_path, decision("J-20991014-1"), decision("J-20991014-2"), decision("J-20991014-3"),
               notes=[note("J-20991014-1", text="plain", quote="the offer was K-20991014-090000"),
                      note("J-20991014-2", text="plain", quote="plain", source="box@abc1234:cards/O-20991013-101500.json:3"),
                      note("J-20991014-3", text="plain", quote="plain")])
    assert out["cards"] == {"K-20991014-090000": ["J-20991014-1"], "O-20991013-101500": ["J-20991014-2"]}
    assert entry(out, "J-20991014-1")["mentions"] == {"K-20991014-090000": ["note"]}
    assert entry(out, "J-20991014-2")["mentions"] == {"O-20991013-101500": ["note"]}
    assert entry(out, "J-20991014-3")["mentions"] == {}                  # must-refuse: a note that names no card adds none


def test_a_card_id_with_a_number_after_it_is_another_card_than_the_one_without(tmp_path):
    out = read(tmp_path,
               decision("J-20991014-1", reading="the second card (O-20991010-195202-2) and the first (O-20991010-195202)"),
               decision("J-20991014-2", words="O-20991010-195202-3 1, take it"),
               decision("J-20991014-3", reading="dated I-20991014-140041-2099-10-14 and numbered K-20991014-090000-12."))
    assert out["cards"] == {"I-20991014-140041": ["J-20991014-3"], "K-20991014-090000-12": ["J-20991014-3"],
                            "O-20991010-195202": ["J-20991014-1"], "O-20991010-195202-2": ["J-20991014-1"],
                            "O-20991010-195202-3": ["J-20991014-2"]}
    assert entry(out, "J-20991014-1")["mentions"] == {"O-20991010-195202-2": ["reading"], "O-20991010-195202": ["reading"]}
    # must-refuse: a date after a card id is not a number after it (the year is four digits), so only the card is taken
    assert "I-20991014-140041-2099" not in out["cards"] and "I-20991014-140041-202" not in out["cards"]


def test_the_digits_of_a_card_id_are_counted_loosely_and_the_number_after_it_up_to_three(tmp_path):
    out = read(tmp_path, decision("J-20991014-1", reading="short I-20991014-12 and K-20991014-1234 and O-20991014-123456."),
               decision("J-20991014-2", reading="numbered Q-20991014-140041-1 and Q-20991014-140042-12 and Q-20991014-140043-123 ."))
    assert sorted(out["cards"]) == ["I-20991014-12", "K-20991014-1234", "O-20991014-123456", "Q-20991014-140041-1",
                                    "Q-20991014-140042-12", "Q-20991014-140043-123"]
    # must-refuse: seven digits of time, or four after the time, are not a card id's shape; a card with four after its
    # time is the card without them, as the date after a card id is
    bad = read(tmp_path, decision("J-20991014-1", reading="long I-20991014-1234567 and Q-20991014-140041-1234 here."))
    assert sorted(bad["cards"]) == ["Q-20991014-140041"]


def test_what_is_not_a_card_id_is_not_indexed(tmp_path):
    not_cards = ("J-20991014-12, t-20991013-101500, pre-20991013-101500, ABC-20991014-140041, I-20991014-1400419, "
                 "I-2099101-140041, I-20991014, 20991014-140041")
    out = read(tmp_path, decision("J-20991014-1", reading=not_cards), decision("J-20991014-2", words="no ids here"))
    assert out["cards"] == {} and entry(out, "J-20991014-1")["mentions"] == {}
    # must-pass: the same shapes with a clean edge are found, so the refusals above are not an empty index
    ok = read(tmp_path, decision("J-20991014-1", reading="(I-20991014-140041), GK-20991013-143522."))
    assert sorted(ok["cards"]) == ["GK-20991013-143522", "I-20991014-140041"]


def test_a_card_id_edging_other_text_is_found_unless_a_letter_or_digit_touches_it__must_pass(tmp_path):
    # a card is often named inside a file name, joined to words by a hyphen, a dot, a slash or an underscore
    joined = ("reply-Q-20991014-111111.md", "Q-20991014-222222-2099-10-14", "Q-20991014-333333- then",
              "Q-20991014-444444_reply.md", "_Q-20991014-555555", "cards/Q-20991014-666666/x", "[Q-20991014-777777]")
    out = read(tmp_path, decision("J-20991014-1", reading=" ".join(joined)))
    assert sorted(out["cards"]) == ["Q-20991014-%d" % (n * 111111) for n in range(1, 8)]
    assert all(ids == ["J-20991014-1"] for ids in out["cards"].values()) and out["problems"] == []


def test_a_card_id_edging_other_text_is_found_unless_a_letter_or_digit_touches_it__must_refuse(tmp_path):
    out = read(tmp_path, decision("J-20991014-1", reading="Q-20991014-444444_reply.md and _Q-20991014-555555"))
    assert sorted(out["cards"]) == ["Q-20991014-444444", "Q-20991014-555555"]      # the answer refused: a card missed
    near = ("Q-20991014-1400419 xQ-20991014-100002 Q-20991014-100003x ABQ-20991014-100004 Q-20991014-100005A "
            "Q-2099101-100006 Q-20991014-")
    none = read(tmp_path, decision("J-20991014-1", reading=near))
    assert none["cards"] == {}                                                     # and a letter or a digit touching it still stops it
    # the digits are ASCII digits: full-width ones are not a card id
    wide = read(tmp_path, decision("J-20991014-1", reading="Q-\uff12\uff10\uff12\uff16\uff11\uff10\uff11\uff14-140041"))
    assert wide["cards"] == {}


# ---------------------------------------------------------------- lines and files that cannot be used
def test_a_line_that_cannot_be_used_is_a_problem_and_the_rest_are_still_read(tmp_path):
    e_acute = "\N{LATIN SMALL LETTER E WITH ACUTE}"
    cafe = dumps(decision("J-20991001-3", words="caf" + e_acute))
    not_utf8 = cafe.encode().replace(e_acute.encode(), b"\xe9")                           # one byte, not valid UTF-8
    out = read(tmp_path,
               decision("J-20991001-1"),                                              # 1
               "this is not json",                                                    # 2
               '["a", "list"]',                                                       # 3
               "",                                                                    # 4 blank: skipped, no problem
               {"words": "no id"},                                                    # 5 no id: kept, and said
               decision("J-20991001-1", words="again"),                               # 6 the id is used already: kept, and said
               dumps(decision("J-20991001-7", words="x" * (MAX_LINE + 10))),          # 7 long: no limit
               decision("J-20991001-2"),                                              # 8
               not_utf8,                                                              # 9 read, with the byte shown as U+FFFD
               '{"id": "J-20991001-4", "words": "cut off in the mid')                 # 10 half written
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [
        (2, "not-json"), (3, "not-an-object"), (5, "no-id"), (5, "missing-field"), (6, "duplicate-id"),
        (9, "replacement-character"), (10, "not-json")]
    assert all(p["source"].endswith("register.jsonl") for p in out["problems"])
    assert [e["id"] for e in out["entries"]] == ["J-20991001-1", None, "J-20991001-1", "J-20991001-7", "J-20991001-2",
                                                 "J-20991001-3"]
    assert out["entries"][0]["words"] == "words of J-20991001-1" and out["entries"][2]["words"] == "again"
    assert [e["line"] for e in out["entries"]] == [1, 5, 6, 7, 8, 9]


def test_a_byte_order_mark_is_not_skipped_as_the_tool_does_not_skip_it__must_pass(tmp_path):
    rows = [dumps(decision(f"J-20991001-{n}")) for n in (1, 2)]
    out = read_bytes(tmp_path, "\r\n".join(rows).encode("utf-8") + b"\r\n\r\n")           # Windows line ends, no mark
    assert [e["id"] for e in out["entries"]] == ["J-20991001-1", "J-20991001-2"] and out["problems"] == []
    assert [e["line"] for e in out["entries"]] == [1, 2]


def test_a_byte_order_mark_is_not_skipped_as_the_tool_does_not_skip_it__must_refuse(tmp_path):
    rows = [dumps(decision(f"J-20991001-{n}")) for n in (1, 2)]
    out = read_bytes(tmp_path, b"\xef\xbb\xbf" + "\r\n".join(rows).encode("utf-8") + b"\r\n")
    # the answer refused: the mark skipped, so that a line the tool refuses is read. The line it begins is said, and the rest read
    assert where(out) == [(1, "not-json")] and "byte-order mark" in out["problems"][0]["text"]
    assert [(e["id"], e["line"]) for e in out["entries"]] == [("J-20991001-2", 2)]
    only = read_bytes(tmp_path, b"\xef\xbb\xbf")                                           # a file of nothing else
    assert only["entries"] == [] and where(only) == [(1, "not-json")]
    middle = read_bytes(tmp_path, rows[0].encode() + b"\n\xef\xbb\xbf" + rows[1].encode() + b"\n")    # and one in the middle
    assert where(middle) == [(2, "not-json")] and [e["id"] for e in middle["entries"]] == ["J-20991001-1"]


CUTS = (b"\r\n", b"\r", b"\x0b", b"\x0c", b"\x1c", "\u0085".encode(), "\u2028".encode(), "\u2029".encode(), b"\n")


def test_a_register_is_cut_into_lines_where_its_own_tool_cuts_it__must_pass(tmp_path):
    ids = [f"J-20991001-{n}" for n in range(1, len(CUTS) + 2)]
    lines = [dumps(decision(i)).encode("utf-8") for i in ids]
    out = read_bytes(tmp_path, b"".join(line + cut for line, cut in zip(lines, (*CUTS, b"\n"))))
    assert [e["id"] for e in out["entries"]] == ids and out["problems"] == []
    assert [e["line"] for e in out["entries"]] == list(range(1, len(ids) + 1))             # each break is a line, as the tool counts
    # the same holds for a notes file
    (tmp_path / "notes.jsonl").write_bytes(b"\r".join(dumps(note(i)).encode("utf-8") for i in ids[:3]) + b"\r")
    both = record.load({"register": str(tmp_path / "register.jsonl"), "notes": str(tmp_path / "notes.jsonl")})
    assert both["counts"]["notes"] == 3 and [n["line"] for n in entry(both, ids[2])["notes"]] == [3]


def test_a_register_is_cut_into_lines_where_its_own_tool_cuts_it__must_refuse(tmp_path):
    for ch in ("\u2028", "\u2029", "\u0085"):
        # as the tool's own writer writes your words: the character raw. The tool cuts the line there, and so does this reader
        torn = dumps(decision("J-20991001-2", words="before X after")).replace("X", ch)
        out = read(tmp_path, decision("J-20991001-1"), torn, decision("J-20991001-3"))
        assert [e["id"] for e in out["entries"]] == ["J-20991001-1", "J-20991001-3"], repr(ch)    # the answer refused: read whole
        assert where(out) == [(2, "not-json"), (3, "not-json")], repr(ch)
        assert [e["line"] for e in out["entries"]] == [1, 4], repr(ch)                  # one line cut in two makes the next one the fourth
    # the notes file is cut the same way: a note torn by one of them is two lines that are not JSON, and the next note is read
    torn = dumps(note("J-20991001-1")).replace("text on", "text\u2029on")
    both = read(tmp_path, decision("J-20991001-1"), decision("J-20991001-2"), notes=[torn, note("J-20991001-2")])
    assert [(p["line"], p["kind"], os.path.basename(p["source"])) for p in both["problems"]] == [
        (1, "not-json", "notes.jsonl"), (2, "not-json", "notes.jsonl")]
    assert both["counts"]["notes"] == 1 and [n["line"] for n in entry(both, "J-20991001-2")["notes"]] == [3]
    # a character that only looks like a line end is not one: the same words, with it escaped, read whole
    whole = read(tmp_path, decision("J-20991001-1", words="before \u2028 after"))
    assert whole["entries"][0]["words"] == "before \u2028 after" and whole["problems"] == []


def test_a_line_of_only_white_space_of_any_kind_is_skipped_as_the_tool_skips_it__must_pass(tmp_path):
    blanks = ("\u00a0", "\u3000 \u2003", "\x1f", "\t \u00a0 ", "\u2002\u2009", "    ")
    out = read(tmp_path, decision("J-20991001-1"), *blanks, decision("J-20991001-2"), "\u00a0", decision("J-20991001-3"))
    assert [(e["id"], e["line"]) for e in out["entries"]] == [("J-20991001-1", 1), ("J-20991001-2", 8), ("J-20991001-3", 10)]
    assert out["problems"] == []
    # and a notes file with such a line
    (tmp_path / "notes.jsonl").write_bytes(("\u00a0\n" + dumps(note("J-20991001-2")) + "\n").encode("utf-8"))
    both = record.load({"register": str(tmp_path / "register.jsonl"), "notes": str(tmp_path / "notes.jsonl")})
    assert both["problems"] == [] and entry(both, "J-20991001-2")["notes"][0]["line"] == 2


def test_a_line_of_only_white_space_of_any_kind_is_skipped_as_the_tool_skips_it__must_refuse(tmp_path):
    out = read(tmp_path, decision("J-20991001-1"), "\u00a0", "\u00a0" + dumps(decision("J-20991001-2")))
    # the answer refused: a line of white space called JSON that is not; and the same space before a decision does not hide it
    assert where(out) == [(3, "not-json")] and [e["id"] for e in out["entries"]] == ["J-20991001-1"]
    # what is not white space to the tool is not skipped: a zero-width space, a mark inside the file, a Mongolian vowel separator
    invisible = read(tmp_path, decision("J-20991001-1"), "\u200b", "\ufeff", "\u180e")
    assert where(invisible) == [(2, "not-json"), (3, "not-json"), (4, "not-json")]


def test_a_genuine_replacement_character_is_text_and_a_byte_that_is_not_utf8_is_said__must_pass(tmp_path):
    # U+FFFD written as UTF-8 is a character like another: the register's tool reads it with no complaint
    out = read(tmp_path, decision("J-20991001-1", words="before \ufffd after"), decision("J-20991001-2", reading="\ufffd"))
    assert out["problems"] == [] and out["entries"][0]["words"] == "before \ufffd after" and out["entries"][1]["reading"] == "\ufffd"


def test_a_genuine_replacement_character_is_text_and_a_byte_that_is_not_utf8_is_said__must_refuse(tmp_path):
    stray = dumps(decision("J-20991001-3", words="caf\u00e9")).encode("utf-8").replace("\u00e9".encode("utf-8"), b"\xe9")
    cut_short = dumps(decision("J-20991001-4", words="end\u2603")).encode("utf-8").replace(b"\xe2\x98\x83", b"\xe2\x98")
    out = read(tmp_path, decision("J-20991001-1", words="genuine \ufffd"), decision("J-20991001-2"), stray, cut_short)
    # the answer refused: a valid U+FFFD called invalid UTF-8. Only the bytes that are not UTF-8 are said, each line once
    assert where(out) == [(3, "replacement-character"), (4, "replacement-character")]
    assert "not valid UTF-8" in out["problems"][0]["text"] and "stands for" not in out["problems"][0]["text"]
    assert out["entries"][0]["words"] == "genuine \ufffd"                                   # as written
    assert out["entries"][2]["words"] == "caf\ufffd" and out["entries"][3]["words"] == "end\ufffd"   # the byte shown as U+FFFD


@pytest.mark.parametrize("parser", ["overflows", "copes"])
def test_a_line_nested_past_the_parsers_depth_is_a_problem_not_a_crash(tmp_path, monkeypatch, parser):
    """Whether 30,000 levels overflow json's parser depends on the interpreter's stack (they do on Windows; under 3.14
    on Linux and macOS they parse). Both are run here on any machine, and both are said the same way: too deep."""
    deep = "[" * 30000 + "]" * 30000                   # valid JSON under the line limit
    real = json.loads

    def loads(text, *a, **k):
        if text != deep:
            return real(text, *a, **k)
        if parser == "overflows":
            raise RecursionError("maximum recursion depth exceeded")
        value = []
        for _ in range(29999):
            value = [value]
        return value
    monkeypatch.setattr(json, "loads", loads)
    out = read(tmp_path, deep, decision("J-20991001-1"))
    assert len(deep) < MAX_LINE and [(p["line"], p["kind"]) for p in out["problems"]] == [(1, "too-deep")]
    assert [e["id"] for e in out["entries"]] == ["J-20991001-1"]                      # the line after it is still read


def test_a_line_nested_past_the_parsers_depth_with_this_machines_own_parser(tmp_path):
    deep = "[" * 30000 + "]" * 30000
    out = read(tmp_path, deep, decision("J-20991001-1"))
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [(1, "too-deep")]
    assert [e["id"] for e in out["entries"]] == ["J-20991001-1"]


def test_a_value_nested_deeper_than_any_decision_is_not_read__must_pass(tmp_path):
    shallow = [1]
    for _ in range(record.MAX_DEPTH - 4):
        shallow = [shallow]
    out = read(tmp_path, decision("J-20991001-1", offer=shallow), decision("J-20991001-2"))
    assert out["problems"] == [{"source": out["files"]["register"], "line": 1, "kind": "bad-field",
                                "text": "offer should be text, not list"}]
    assert out["entries"][0]["offer"] == shallow and json.loads(json.dumps(out)) == out     # passed on, and plain JSON


def test_a_value_nested_deeper_than_any_decision_is_not_read__must_refuse(tmp_path):
    deep = [1]
    for _ in range(record.MAX_DEPTH + 40):
        deep = [deep]
    out = read(tmp_path, decision("J-20991001-1", offer=deep), decision("J-20991001-2"))
    assert where(out) == [(1, "too-deep")] and [e["id"] for e in out["entries"]] == ["J-20991001-2"]
    assert "levels deep" in out["problems"][0]["text"]
    assert json.loads(json.dumps(out)) == out and len(json.dumps(out)) < 20000              # the answer stays easy to carry


def test_a_file_that_is_missing_or_cannot_be_opened_is_a_problem_not_a_crash(tmp_path):
    out = record.load({"register": str(tmp_path / "nowhere.jsonl")})
    assert out["off"] is False and out["entries"] == [] and kinds(out) == ["missing-file"]
    assert out["problems"][0]["line"] is None and out["problems"][0]["source"].endswith("nowhere.jsonl")
    folder = tmp_path / "a-folder"
    folder.mkdir()
    assert kinds(record.load({"register": str(folder)})) == ["unreadable"]
    assert kinds(record.load({"register": str(tmp_path / "bad\x00name")})) == ["unreadable"]   # a path no system takes
    # must-pass: with the register there and the notes file missing, the decisions are still read
    reg = write(tmp_path / "register.jsonl", decision("J-20991001-1"))
    both = record.load({"register": reg, "notes": str(tmp_path / "no-notes.jsonl")})
    assert len(both["entries"]) == 1 and kinds(both) == ["missing-file"]
    assert both["problems"][0]["source"].endswith("no-notes.jsonl")


def test_a_field_that_is_missing_or_not_text_is_reported_and_the_decision_is_kept(tmp_path):
    out = read(tmp_path,
               decision("J-20991001-1", words=None),                                  # 1 missing
               decision("J-20991001-2", words=5),                                     # 2 not text
               decision("J-20991001-3", date="1 Oct"),                                # 3
               decision("J-20991001-4", offer=["a", "list"]),                         # 4
               decision("J-20991001-5"))                                              # 5 clean: the control
    assert [(p["line"], p["kind"]) for p in out["problems"]] == [
        (1, "missing-field"), (2, "bad-field"), (3, "bad-date"), (4, "bad-field")]
    assert "words" in out["problems"][0]["text"] and "int" in out["problems"][1]["text"]
    assert len(out["entries"]) == 5 and entry(out, "J-20991001-2")["words"] == 5          # a value that is there is passed on
    assert entry(out, "J-20991001-3")["date"] == "1 Oct" and entry(out, "J-20991001-4")["offer"] == ["a", "list"]


# ---------------------------------------------------------------- plain data, and no writing
def test_the_record_is_plain_json_all_the_way_down(tmp_path):
    out = read(tmp_path, decision("J-20991001-1", reading="card I-20991001-120000"),
               decision("J-20991002-1", supersedes=["J-20991001-1", "J-20990101-1"], words=ODD), "damaged",
               notes=[note("J-20991001-1"), note("J-20990101-1")])
    assert out["problems"] and out["cards"] and out["entries"][0]["notes"]
    assert json.loads(json.dumps(out)) == out
    # must-refuse: an off source is plain too, and carries the same keys, so a page can read it without a check
    off = record.load({})
    assert json.loads(json.dumps(off)) == off and set(off) == set(out)


def test_reading_changes_nothing_and_needs_no_right_to_write(tmp_path):
    reg = write(tmp_path / "register.jsonl", decision("J-20991001-1"), decision("J-20991002-1"))
    nts = write(tmp_path / "notes.jsonl", note("J-20991001-1"))
    files = [tmp_path / "register.jsonl", tmp_path / "notes.jsonl"]
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    for p in files:
        os.chmod(p, stat.S_IREAD)                      # a reader that opened either for writing would be refused
    try:
        out = record.load({"register": reg, "notes": nts})
        record.load({"register": reg, "notes": nts})
    finally:
        for p in files:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    assert len(out["entries"]) == 2 and out["problems"] == []
    assert after == before                              # the same files, bytes and times, and nothing new beside them


FULLWIDTH = str.maketrans("0123456789", "０１２３４５６７８９")
PIN_TEXT = "box@" + "0123456789abcdef" * 2 + "01234567:docs/NOTES.md:12-15"


@pytest.mark.parametrize("date", ["2026-10-23".translate(FULLWIDTH), "2026-10-2３", "٢٠٢٦-10-23"])
def test_a_date_in_digits_of_another_script_is_not_a_date(date):   # must refuse: YYYY-MM-DD in ASCII digits
    assert record.DATE.fullmatch(date) is None


@pytest.mark.parametrize("line", ["１２", "1２", "١٢"])
def test_a_pin_whose_line_is_in_digits_of_another_script_is_not_a_pin(line):   # must refuse
    assert record.PIN.fullmatch(PIN_TEXT.replace(":12-15", f":{line}-15")) is None
    assert record.PIN.fullmatch(PIN_TEXT.replace(":12-15", f":12-{line}")) is None


def test_a_date_and_a_pin_in_ascii_digits_are_read():   # must pass
    assert record.DATE.fullmatch("2026-10-23")
    m = record.PIN.fullmatch(PIN_TEXT)
    assert m and (m.group("line"), m.group("last")) == ("12", "15")
