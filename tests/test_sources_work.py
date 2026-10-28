"""The Work source and the Work place (PM-DESIGN r4, r5; slice 2): the store read through slice 1's fold, never folded
again; every event with its assurance, every "not applied" one with its reason; the status in words; what waits on the
person; and nothing added to the card hook's imports. Each check has a must-pass arm and a must-refuse arm."""
import json

from semantext.sources import builtin, view, work
from semantext.sources.workitems import status
from semantext.work.turns import parse_deep_link
from test_registry import HOOK_MODULES, _python
from work_kit import bound
from work_world import CARD, MET, PROJECTS, Readers, answer, build, place, writer


def by_id(a):
    return {i["id"]: i for i in a["items"]}


# ---- the empty store ------------------------------------------------------------------------------------------------
def test_an_empty_home_is_an_empty_board_and_no_problem(tmp_path):
    a = answer(tmp_path)
    assert a["off"] is False and a["store"]["exists"] is False and a["items"] == [] and a["problems"] == []
    assert a["asks"] == [] and a["counts"] == {}
    # must refuse: a store with one event is not empty
    writer(tmp_path).write(bound("Alder"), "create", {"project": "lab", "title": "One"})
    b = answer(tmp_path)
    assert b["store"]["exists"] and [i["id"] for i in b["items"]] == ["W-lab-1"] and b["counts"] == {"lab": {"backlog": 1}}


def test_the_work_reader_is_a_built_in_source_and_the_place_a_built_in_place():
    assert "work" in [s.name for s in builtin.SOURCES] and "work" in view.ROUTES
    assert view.BUILT_IN.get("place", "work").obj.needs == ("work", "waiting", "record")


# ---- the world ------------------------------------------------------------------------------------------------------
def test_status_words_follow_the_clauses_read_now(tmp_path):
    w = build(tmp_path)
    got = by_id(answer(tmp_path))
    ids = w.ids
    assert (got[ids["checked"]]["shown"], got[ids["checked"]]["status_word"]) == ("done", "done (checked)")
    assert (got[ids["unknown"]]["shown"], got[ids["unknown"]]["status_word"]) == ("done", "done (claimed)")
    assert got[ids["stale"]]["status_word"] == "proof no longer holds" and got[ids["stale"]]["shown"] == "review"
    assert got[ids["done"]]["status_word"] == "done (your word)"
    assert got[ids["epic"]]["status_word"] == "backlog" and got[ids["epic"]]["status"] is None
    # each word is read now, never stored: the same item with another reader is another word
    class Nothing(Readers):
        def decision(self, clause):
            return None
    again = by_id(answer(tmp_path, readers=Nothing()))
    assert again[ids["checked"]]["shown"] == "review" and again[ids["checked"]]["status_word"] == "review"
    assert all("done (checked)" not in json.dumps(json.loads(line)) for line in w.path.read_text("utf-8").splitlines())


def test_a_done_with_an_unmet_clause_is_never_checked(tmp_path):
    w = build(tmp_path)
    got = by_id(answer(tmp_path))
    unmet = got[w.ids["unmet"]]                       # in review: one clause met, one not
    assert unmet["shown"] == "review" and unmet["status"] is None
    assert [c["state"] for c in unmet["clauses"]] == ["met", "unmet"]
    assert unmet["waits"] == "waits on Birch's review and 1 of 2 clauses"
    word = got[w.ids["done"]]                         # the person's word made it done; its clause is still shown unmet
    assert word["status_word"] == "done (your word)" and [c["state"] for c in word["clauses"]] == ["unmet"]
    # must refuse: the judge alone, with every clause met, says checked
    assert status({"state": "review"}, [{"state": "met"}, {"state": "met"}]) == ("done", "done-checked")
    assert status({"state": "review"}, [{"state": "met"}, {"state": "unmet"}]) == ("review", None)


def test_a_forged_event_is_shown_not_applied_with_its_reason(tmp_path):
    w = build(tmp_path)
    a = answer(tmp_path)
    item = by_id(a)[w.ids["checked"]]
    forged = [e for e in item["history"] if e["seq"] == w.ids["forged_seq"]]
    assert len(forged) == 1 and forged[0]["applied"] is False and forged[0]["code"] == "NOT_AUTHORIZED"
    assert forged[0]["event"] == "person_act" and forged[0]["who"] == "Birch" and forged[0]["what"].startswith("park")
    assert "person's own act" in forged[0]["reason"]
    assert item["state"] == "review" and a["not_applied"] == 1          # the park never became state
    applied = [e for e in item["history"] if e["applied"]]
    assert applied and all(e["assurance"] == e["effective"] for e in applied)


def test_a_broken_chain_is_shown_as_broken_and_nothing_in_it_is_trusted(tmp_path):
    w = build(tmp_path)
    lines = w.path.read_text("utf-8").splitlines(keepends=True)
    w.path.write_text("".join(lines[1:]), encoding="utf-8")     # the first record cut away
    a = answer(tmp_path)
    assert a["store"]["intact"] is False
    assert any(p["kind"] == "broken" for p in a["problems"])
    rows = [e for i in a["items"] for e in i["history"]] + a["orphans"]
    assert rows and all(e["effective"] == "claimed" for e in rows)
    assert not any(i["state"] in ("doing", "review") for i in a["items"])   # a move needs a bound seat
    # must refuse: the same world, left whole, is whole
    build(tmp_path / "other")
    assert answer(tmp_path / "other")["store"]["intact"] is True


def test_what_waits_on_the_person(tmp_path):
    w = build(tmp_path)
    a = answer(tmp_path)
    asks = {(x["item"], x["act"]): x for x in a["asks"]}
    assert set(asks) == {(w.ids["word"], "done"), (w.ids["proposed"], "park")}
    assert asks[(w.ids["proposed"], "park")]["line"] == f"{w.ids['proposed']} park"
    assert asks[(w.ids["word"], "done")]["pressed"] is True
    assert a["ranking"] == [w.ids["epic"], w.ids["claimed"], w.ids["proposed"]]
    assert by_id(a)[w.ids["claimed"]]["rank_line"] == f"{w.ids['claimed']} next"
    # must refuse: once the person parks it, the proposal waits no more
    from work_kit import person
    person(w, w.ids["proposed"], "park")
    after = answer(tmp_path)
    assert (w.ids["proposed"], "park") not in {(x["item"], x["act"]) for x in after["asks"]}


def test_each_item_carries_the_inbox_link_only_for_a_known_project(tmp_path):
    w = build(tmp_path)
    got = by_id(answer(tmp_path))
    i = got[w.ids["checked"]]
    assert i["inbox"] == "jak-inbox://work/lab/2" and parse_deep_link(i["inbox"], PROJECTS) == i["id"]
    other = by_id(answer(tmp_path, projects={"orchard"}))[w.ids["checked"]]       # must refuse: lab is not known
    assert other["inbox"] is None and "not a project in your seats file" in other["no_inbox"]


def test_the_history_keeps_every_event_with_its_assurance(tmp_path):
    w = build(tmp_path)
    i = by_id(answer(tmp_path))[w.ids["claimed"]]
    assert [(e["event"], e["assurance"], e["applied"]) for e in i["history"]] == [("create", "claimed", True)]
    assert "filed claimed" in i["badges"] and "no owner" in i["badges"]


def test_a_store_over_the_read_cap_is_not_folded(tmp_path, monkeypatch):
    build(tmp_path)
    monkeypatch.setattr(work, "READ_CAP", 100)
    a = answer(tmp_path)
    assert a["items"] == [] and [p["kind"] for p in a["problems"]] == ["too large"]
    monkeypatch.setattr(work, "READ_CAP", 10 ** 9)
    assert answer(tmp_path)["items"]


def test_the_register_reader_meets_a_decision_clause_and_landed_and_outcome_stay_unknown(tmp_path):
    w = writer(tmp_path)
    ident = w.write(bound("Alder"), "create", {"project": "lab", "title": "T", "clauses": [
        {"kind": "jak-decision", "register": MET},
        {"kind": "landed", "repo": "lab", "commit": "abc1234", "branch": "main"},
        {"kind": "outcome", "out_id": "out_" + "A" * 26}]})["id"]
    readers = work.Evidence([{"id": MET, "words": f"Yes, {ident}.", "computed_status": "in force", "added_by": "Rowan"}])
    got = by_id(answer(tmp_path, readers=readers))[ident]["clauses"]
    assert [c["state"] for c in got] == ["met", "unknown", "unknown"]
    assert got[1]["why"] == got[2]["why"] == work.NO_READER and "no reader for this yet" in work.NO_READER
    parked = work.Evidence([{"id": MET, "words": f"Yes, {ident}.", "computed_status": "parked", "added_by": "Rowan"}])
    assert by_id(answer(tmp_path, readers=parked))[ident]["clauses"][0]["state"] == "unmet"   # must refuse


# ---- the place ------------------------------------------------------------------------------------------------------
def test_the_place_reads_each_links_live_state_and_a_waiting_card(tmp_path):
    w = build(tmp_path)
    got = by_id(place(tmp_path))
    proposed = got[w.ids["proposed"]]
    assert proposed["links"][0]["state"] == "waiting on your word" and CARD in proposed["waiting_on"]
    assert f"waiting on {CARD}" in proposed["badges"]
    assert got[w.ids["checked"]]["links"][0]["state"] == "not read yet"         # a commit has no reader here
    # must refuse: an answered card puts nothing on the item
    from semantext.sources.workplace import work_place
    src = {"work": answer(tmp_path), "waiting": {"cards": [{"id": CARD, "state": "closed"}]}, "record": {}}
    again = by_id(work_place(src))[w.ids["proposed"]]
    assert again["links"][0]["state"] == "answered" and CARD not in again["waiting_on"]


def test_the_place_answers_through_the_view_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    build(tmp_path)
    before = sorted((p.name, p.stat().st_mtime_ns) for p in (tmp_path / "work").iterdir())
    a = view.answer("work", home=tmp_path)
    assert a["place"] == "work" and a["store"]["exists"] and len(a["items"]) == 9
    assert sorted((p.name, p.stat().st_mtime_ns) for p in (tmp_path / "work").iterdir()) == before


# ---- the hook --------------------------------------------------------------------------------------------------------
def test_the_work_place_adds_nothing_to_the_card_hooks_imports(tmp_path):
    code = ("import sys, json, semantext.hook, semantext.envhook\n"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('semantext'))))")
    run = _python(code, tmp_path)
    assert run.returncode == 0, run.stderr
    mods = json.loads(run.stdout.strip().splitlines()[-1])
    assert mods == HOOK_MODULES and not [m for m in mods if "work" in m]
    # the control: the page's view does import the Work place, and the same check sees it
    run = _python("import sys, json, semantext.sources.view\n"
                  "print(json.dumps(sorted(m for m in sys.modules if m.startswith('semantext'))))", tmp_path)
    assert "semantext.sources.workplace" in json.loads(run.stdout.strip().splitlines()[-1])


def test_the_fold_is_slice_ones_never_a_copy():
    import inspect
    text = inspect.getsource(work) + inspect.getsource(__import__("semantext.sources.workitems", fromlist=["x"]))
    assert "from ..work.fold import fold" in text and "def fold" not in text and "rules.apply" not in text
    assert "import apply" not in text and "_person(" not in text


# ---- an unreadable register is a problem shown, never an empty one (review round 3, G6 medium 6) -------------------
def _decision_world(tmp_path):
    from work_kit import person
    w = writer(tmp_path)
    ident = w.write(bound("Alder"), "create", {"project": "lab", "title": "T", "links": [{"type": "commit",
                                                                                           "ref": "abc1234"}],
                                               "clauses": [{"kind": "jak-decision", "register": MET}]})["id"]
    person(w, ident, "next", frm="backlog")
    w.write(bound("Alder"), "move", {"id": ident, "from": "next", "to": "doing"})
    w.write(bound("Alder"), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": "Birch"})
    return ident


def _load(tmp_path, register):
    from work_world import NOW
    return work.load({"_home": str(tmp_path), "register": str(register)}, now=NOW, projects=PROJECTS)


def test_an_unreadable_register_is_a_problem_and_its_decisions_are_unknown(tmp_path, monkeypatch):
    ident = _decision_world(tmp_path)
    for reg, broken in ((tmp_path / "no-register.jsonl", None), (tmp_path / "register.jsonl", "raise")):
        if broken:
            reg.write_text("", encoding="utf-8")
            from semantext.sources import record
            def boom(cfg):
                raise PermissionError("denied")
            monkeypatch.setattr(record, "load", boom)
        a = _load(tmp_path, reg)
        assert any(p["kind"] == "register-unreadable" for p in a["problems"]), a["problems"]
        [c] = by_id(a)[ident]["clauses"]
        assert c["state"] == "unknown" and "register" in c["why"], c
        monkeypatch.undo()


def test_partner_a_readable_register_meets_the_decision_and_says_no_problem(tmp_path):
    ident = _decision_world(tmp_path)
    reg = tmp_path / "register.jsonl"
    entry = {"id": MET, "date": "2026-10-20", "time_utc": None, "to": "Ana", "subject": "beds", "status": "in force",
             "words": f"Yes, ship {ident}.", "offer": None, "reading": "yes", "source": "box@abc1234:NOTES.md:7",
             "supersedes": [], "added_by": "Rowan", "added": "2026-10-20"}
    reg.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    a = _load(tmp_path, reg)
    assert not any(p["kind"] == "register-unreadable" for p in a["problems"])
    assert by_id(a)[ident]["clauses"][0]["state"] == "met"

# ---- review round 3 (G6): what is cut is counted ---------------------------------------------------------------------
def test_reader_problems_past_the_cap_are_counted_never_dropped(tmp_path):
    build(tmp_path)

    class Noisy(Readers):
        problems = [{"source": "v", "line": n, "kind": "bad-row", "text": "x"} for n in range(work.PROBLEM_CAP + 7)]
    got = answer(tmp_path, readers=Noisy())["problems"]
    assert [p for p in got if p["kind"] == "bad-row"].__len__() == work.PROBLEM_CAP
    assert any(p["kind"] == "more" and "7 more" in p["text"] for p in got), got[-1]

    class Quiet(Readers):
        problems = [{"source": "v", "line": 1, "kind": "bad-row", "text": "x"}]
    assert not any(p["kind"] == "more" for p in answer(tmp_path, readers=Quiet())["problems"])   # must pass


def test_comments_past_the_fifty_shown_are_counted(tmp_path):
    w = writer(tmp_path)
    ident = w.write(bound("Alder"), "create", {"project": "lab", "title": "Talky"})["id"]
    for k in range(60):
        w.write(bound("Birch"), "comment", {"id": ident, "text": f"note {k}"})
    got = by_id(answer(tmp_path))[ident]
    assert len(got["comments"]) == 50 and got["comments_more"] == 10 and got["comments"][-1]["text"] == "note 59"
    other = w.write(bound("Alder"), "create", {"project": "lab", "title": "Quiet"})["id"]
    assert by_id(answer(tmp_path))[other]["comments_more"] == 0               # must pass

def test_a_proposal_waiting_on_the_person_says_its_assurance(tmp_path):   # the attack on the Work page, A3
    from work_kit import claimed
    w = build(tmp_path)
    w.write(claimed("someone"), "propose_reassign", {"id": w.ids["word"], "to_seat": "Alder"})
    asks = {(x["item"], x["act"]): x for x in answer(tmp_path)["asks"]}
    park, give = asks[(w.ids["proposed"], "park")], asks[(w.ids["word"], "assign")]
    assert park["why"] == "Birch (bound) proposes parking it" and park["assurance"] == "bound"
    assert give["why"] == "someone (claimed) proposes giving it to Alder" and give["assurance"] == "claimed"

def test_the_register_reader_says_which_items_an_entry_names(tmp_path):   # PM-DESIGN, decided 24 October, A2
    w = writer(tmp_path)
    ident = w.write(bound("Alder"), "create", {"project": "lab", "title": "T", "clauses": [
        {"kind": "jak-decision", "register": MET}]})["id"]
    def entry(words, **more):
        return {"id": MET, "words": words, "computed_status": "in force", "added_by": "Rowan", **more}
    for e, state in ((entry("Yes."), "unmet"), (entry("Yes, W-lab-12 ships."), "unmet"),
                     (entry(f"Yes, {ident} ships."), "met"), (entry("Yes.", subject=f"about {ident}"), "met"),
                     # a note never counts (round 4, decision 2): its text, quote and source are not the entry's words
                     (entry("Yes.", notes=[{"text": f"see {ident}", "quote": ident, "source": ident}]), "unmet"),
                     (entry("Yes.", reading=f"ships {ident}"), "met"), (entry("Yes.", offer=f"{ident}?"), "met"),
                     (entry("Yes.", to=f"{ident}"), "met")):
        got = by_id(answer(tmp_path, readers=work.Evidence([e])))[ident]["clauses"][0]
        assert got["state"] == state, (e, got)