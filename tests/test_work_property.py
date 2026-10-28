"""A property: several writers (separate Writer objects on one home, in threads, each making random requests from a
seeded generator) interleave however the scheduler lets them, and the log they leave always replays to one state.

For each seed it checks: the chain is whole and every line is on it; ids are unique and dense per project; folding the
same bytes again, and with CRLF, gives the same state; and every write's own answer is what a replay of the log up to
that write says (the writer and the fold apply one table)."""
import random
import threading

import pytest

from semantext.work.events import WorkRefused
from semantext.work.fold import fold, fold_lines, state_hash
from semantext.work.chain import walk
from work_kit import P, Clock, Turns, bound, checks_of, claimed, make, say

SEATS = ("alpha", "beta", "gamma")


def _one(rng, w, actor, ids, log, lock):
    with lock:
        known = list(ids)
    choice = rng.random()
    target = rng.choice(known) if known else None
    try:
        if choice < 0.25 or not known:
            r = w.write(actor, "create", {"project": rng.choice((P, "atlas")), "title": f"t{rng.random():.3f}"})
            with lock:
                ids.append(r["id"])
        elif choice < 0.4:
            r = w.write(actor, "comment", {"id": target, "text": "c"})
        elif choice < 0.5:
            r = w.write(actor, "assign_self", {"id": target})
        elif choice < 0.75:
            st = w.state()["items"].get(target)
            frm = st["state"] if st else "backlog"
            to = rng.choice(("next", "doing", "review", "backlog", "done"))
            r = w.write(actor, "move", {"id": target, "from": frm, "to": to, "reviewer": rng.choice(SEATS)})
        elif choice < 0.85:
            r = w.write(actor, "link", {"id": target, "link": {"type": "commit", "ref": "abc1234"}})
        else:
            st = w.state()["items"].get(target)
            act = rng.choice(("next", "park", "unpark", "doing", "done"))
            frm = st["state"] if st else "backlog"
            session = f"p{id(w)}"          # one transcript per writer's thread, so no two appends race on one file
            say(w, f"{target} {act}", session=session, turn=f"{id(w)}-{rng.random()}")
            req = {"id": target, "act": act}
            if act not in ("park", "unpark"):
                req["from"] = frm
            r = w.person_act(session, req)
    except WorkRefused:
        return
    with lock:
        log.append(r)


@pytest.mark.parametrize("seed", range(6))
def test_random_interleavings_of_several_writers_replay_to_one_state(tmp_path, seed):
    home = tmp_path / "home"
    writers = [make(home, clock=Clock(), turns=Turns(), rate=10 ** 6) for _ in range(4)]
    actors = [bound("alpha"), bound("beta"), claimed("gamma"), bound("gamma")]
    ids, log, lock = [], [], threading.Lock()

    def run(k):
        rng = random.Random(seed * 100 + k)
        for _ in range(40):
            _one(rng, writers[k], actors[k], ids, log, lock)
    threads = [threading.Thread(target=run, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    w = writers[0]
    st = w.state()
    assert st["intact"] and not st["problems"] and all(e["on_chain"] for e in st["events"])
    for project in (P, "atlas"):
        ns = sorted(i["n"] for i in st["items"].values() if i["project"] == project)
        assert ns == list(range(1, len(ns) + 1))

    text = w.path.read_text(encoding="utf-8")
    head = w._head()
    checks = checks_of(w, text.split("\n")[:-1], head)          # the person's acts, checked against their spans
    again = fold_lines(text.split("\n")[:-1], None, head, checks=checks)
    crlf = fold_lines(text.replace("\n", "\r\n").split("\n")[:-1], None, head, checks=checks)
    assert state_hash(st) == state_hash(again) == state_hash(crlf)

    records = walk(text.split("\n")[:-1], None, head)["records"]
    for r in log:
        if r.get("repeat"):
            continue
        prefix = fold([x for x in records if x[1]["seq"] <= r["seq"]], checks=checks)
        replayed = prefix["items"].get(r["id"])
        assert replayed is not None
        derived = ("events", "epic_path", "held_by", "hold_proposed", "waiting_on")   # made by snapshot(), fresh
        mine = {k: v for k, v in (r["item"] or {}).items() if k not in derived}
        theirs = {k: v for k, v in replayed.items() if k not in derived}
        if r["applied"]:
            assert mine == theirs, (seed, r["seq"])
        else:
            assert prefix["events"][-1]["code"] == "PROPOSAL"
    print(f"\nseed {seed}: {len(st['events'])} events, {len(st['items'])} items, "
          f"{sum(1 for e in st['events'] if e['code'] == 'PROPOSAL')} proposals")
