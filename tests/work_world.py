"""A fixture world for the Work source and the Work place: a store written by the kernel's writer (and one line it never
wrote), readers that stand in for the evidence, and the other sources' answers the place reads links from."""
from semantext.sources import work
from semantext.sources.workplace import work_place
from work_kit import NOW, bound, claimed, make, person, plant, transcripts

PROJECTS = {"lab", "orchard"}
SEATS = {"Alder", "Birch", "Cedar"}
MET, UNMET = "J-20261020-1", "J-20261020-2"
CARD = "A-20261020-101"


class Readers:
    """Evidence as the readers would find it: one register decision with the person's line, a landed fact that was on
    its branch and no longer is, and no reader for run records (unknown, never met)."""

    def decision(self, clause):
        if clause["register"] == MET:
            # the decision names the beds' epic, W-lab-1, so it is about every item under it
            return {"entry": {"id": MET, "line": "Yes, ship the beds.", "state": "in force", "names": ["W-lab-1"]},
                    "producer": "Rowan"}
        return None

    def landed(self, clause):
        return {"fact": {"repo": clause["repo"], "commit": clause["commit"], "branch": clause["branch"],
                         "ancestor": False, "was_ancestor": True}, "producer": "git-checker",
                "checker_by": "Dogwood"}

    def run_record(self, clause):
        return {"unknown": work.NO_READER}

    def verdict(self, clause):
        return None

    def outcome(self, clause):
        return None


def writer(home):
    return make(home, projects=PROJECTS, seats=SEATS)


def _review(w, who, ident, reviewer="Birch"):
    person(w, ident, "next", frm="backlog")
    w.write(bound(who), "move", {"id": ident, "from": "next", "to": "doing"})
    w.write(bound(who), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": reviewer})


def build(home) -> dict:
    """The world's store; returns its writer and the ids by name."""
    w = writer(home)
    commit = [{"type": "commit", "ref": "abc1234"}]
    new = lambda who, project, title, **kw: w.write(bound(who), "create", {"project": project, "title": title, **kw})["id"]
    ids = {"epic": new("Alder", "lab", "Garden beds", kind="epic", text="All the raised beds.")}
    ids["checked"] = new("Alder", "lab", "Build the first bed", epic=ids["epic"], links=commit,
                         clauses=[{"kind": "jak-decision", "register": MET}])
    _review(w, "Alder", ids["checked"])
    ids["unmet"] = new("Alder", "lab", "Build the second bed", epic=ids["epic"], links=commit,
                       clauses=[{"kind": "jak-decision", "register": MET}, {"kind": "jak-decision", "register": UNMET}])
    _review(w, "Alder", ids["unmet"])
    ids["word"] = new("Birch", "lab", "Water the beds", links=commit)
    _review(w, "Birch", ids["word"], reviewer="Cedar")
    ids["claimed"] = w.write(claimed("someone"), "create", {"project": "lab", "title": "Buy compost"})["id"]
    ids["proposed"] = new("Alder", "lab", "Paint the shed", links=[{"type": "card", "ref": CARD}])
    w.write(bound("Birch"), "propose_park", {"id": ids["proposed"], "text": "Wait for spring."})
    ids["unknown"] = new("Cedar", "orchard", "Prune the pears", links=commit,
                         clauses=[{"kind": "run-record", "rule": "prune-rule", "outcome": "clean", "max_findings": 0,
                                   "fresh_days": 30}])
    _review(w, "Cedar", ids["unknown"], reviewer="Alder")
    ids["stale"] = new("Cedar", "orchard", "Graft the apples", links=commit,
                       clauses=[{"kind": "landed", "repo": "orchard", "commit": "abc1234", "branch": "main"}])
    _review(w, "Cedar", ids["stale"], reviewer="Alder")
    ids["done"] = new("Cedar", "orchard", "Fence the orchard", links=commit,
                      clauses=[{"kind": "jak-decision", "register": UNMET}])
    person(w, ids["done"], "next", frm="backlog")
    w.write(bound("Cedar"), "move", {"id": ids["done"], "from": "next", "to": "doing"})
    person(w, ids["done"], "done", frm="doing")
    # a line the writer never wrote: a seat parking an item, chained and with the head moved, as a forger would
    ids["forged_seq"] = plant(w, {"event": "person_act", "id": ids["checked"], "act": "park", "from": "review",
                                  "who": "Birch", "assurance": "bound"})
    w.ids = ids
    return w


def answer(home, **kw) -> dict:
    return work.load({"_home": str(home), "transcripts": [str(transcripts(home))]}, readers=kw.pop("readers", Readers()),
                     now=NOW,
                     projects=kw.pop("projects", PROJECTS), **kw)


def place(home) -> dict:
    src = {"work": answer(home), "waiting": {"cards": [{"id": CARD, "state": "waiting"}]},
           "record": {"entries": [{"id": MET, "computed_status": "in force"}]}}
    return work_place(src)
