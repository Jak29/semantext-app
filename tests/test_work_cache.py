"""The writer's cache of its verified prefix (writer._folded): only the lines after it are walked and folded, and the
state is always the one a fold from scratch gives. Each behaviour has a test that must pass and, where it can go wrong,
one that must be refused."""
import json

import pytest

import semantext.work.chain as chain
from semantext.work.fold import Folder, fold_lines, state_hash
from work_kit import bound, checks_of, claimed, item, lines, make, new, person, plant, refused, to_doing


@pytest.fixture
def w(tmp_path):
    return make(tmp_path / "home")


def scratch(w):
    """The state a fold from scratch gives, with no cache (and the person's acts checked against their spans, as the
    writer's own fold checks them)."""
    text = w.path.read_text(encoding="utf-8")
    head = json.loads(w.head_path.read_text(encoding="utf-8"))
    lines = text.split("\n")[:-1]
    return fold_lines(lines, None, head, checks=checks_of(w, lines, head))


def busy(w, n=12):
    for k in range(n):
        ident = new(w, "alpha", title=f"t{k}")
        w.write(bound("beta"), "comment", {"id": ident, "text": "c"})
    ident = to_doing(w)
    w.write(claimed("alpha"), "move", {"id": ident, "from": "doing", "to": "review", "reviewer": "beta"})
    return ident


def test_the_cached_state_is_the_state_a_fold_from_scratch_gives_across_two_writers(w, tmp_path):
    other = make(w.home)                                   # another writer on the same store, its own cache
    busy(w)
    new(other, "gamma")
    busy(w, 3)
    for writer in (w, other):
        assert state_hash(writer.state()) == state_hash(scratch(w))


def test_an_append_parses_only_the_lines_after_the_cached_prefix(w, monkeypatch):
    busy(w, 30)
    w.state()                                              # warm
    seen = []
    real = chain.parse_line
    monkeypatch.setattr(chain, "parse_line", lambda text: seen.append(text) or real(text))
    new(w, "alpha")
    assert len(seen) == 0                                  # its own check: nothing new yet since the last fold
    w.state()
    assert len(seen) == 1                                  # the one line it wrote


def test_an_edit_inside_the_cached_prefix_is_always_seen(w):
    busy(w)
    w.state()
    text = lines(w)
    edited = text[1].replace('"text":"c"', '"text":"x"')
    assert edited != text[1]
    text[1] = edited
    w.path.write_text("\n".join(text) + "\n", encoding="utf-8")
    assert not w.state()["intact"]
    refused("CONFLICT", new, w, "alpha")


def test_a_head_moved_back_verifies_the_whole_store_again(w):
    busy(w)
    w.state()
    head = json.loads(w.head_path.read_text(encoding="utf-8"))
    first = json.loads(lines(w)[0])
    w.head_path.write_text(json.dumps({"seq": first["seq"], "hash": first["hash"]}), encoding="utf-8")
    st = w.state()
    assert st["intact"] and sum(e["on_chain"] for e in st["events"]) == 1      # the rest is after the head now
    assert state_hash(st) == state_hash(scratch(w))
    w.head_path.write_text(json.dumps(head), encoding="utf-8")
    assert state_hash(w.state()) == state_hash(scratch(w))


def test_a_line_planted_beside_the_writers_own_stays_off_the_chain_as_a_full_fold_says(w):
    ident = busy(w)
    w.state()
    plant(w, {"event": "person_act", "id": ident, "act": "park", "who": "person", "assurance": "bound"},
          move_head=False)
    new(w, "alpha")                                        # chains from the head, beside the planted line
    st = w.state()
    assert st["intact"] and state_hash(st) == state_hash(scratch(w))
    off = [e for e in st["events"] if not e["on_chain"]]
    assert len(off) == 1 and off[0]["who"] == "person" and not off[0]["applied"]


def test_a_chain_through_a_planted_line_in_the_prefix_verifies_again_and_is_refused(w):
    ident = busy(w)
    w.state()
    plant(w, {"event": "comment", "id": ident, "text": "planted", "who": "alpha", "assurance": "bound"},
          move_head=False)
    w.state()                                              # the planted line is now inside the cached prefix
    plant(w, {"event": "comment", "id": ident, "text": "on it", "who": "alpha", "assurance": "bound"})
    assert state_hash(w.state()) == state_hash(scratch(w))


def test_a_torn_tail_under_the_cache_is_reported_and_the_next_append_starts_fresh(w):
    ident = busy(w)
    w.state()
    plant(w, None, raw='{"v":1,"ev')
    assert [p["kind"] for p in w.state()["problems"]] == ["torn"]
    w.write(bound("alpha"), "comment", {"id": ident, "text": "after"})
    st = w.state()
    assert st["intact"] and [p["kind"] for p in st["problems"]] == ["malformed"]
    assert state_hash(st) == state_hash(scratch(w))


def test_a_state_handed_out_does_not_move_when_the_store_grows(w):
    ident = new(w)
    before = w.state()["items"][ident]
    w.write(bound("alpha"), "comment", {"id": ident, "text": "later"})
    assert before["comments"] == [] and len(item(w, ident)["comments"]) == 1


def test_a_folder_fed_in_two_parts_is_the_folder_fed_whole(w):
    busy(w)
    person(w, new(w), "park")
    recs = chain.walk(lines(w), None, json.loads(w.head_path.read_text(encoding="utf-8")))["records"]
    whole, parts = Folder(), Folder()
    whole.feed(recs)
    parts.feed(recs[:7])
    parts.feed(recs[7:])
    assert state_hash(whole.snapshot()) == state_hash(parts.snapshot())
