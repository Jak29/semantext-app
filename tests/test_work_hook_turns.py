"""The hook is the producer of the person's turn records (PM-DESIGN, follow-ups to A1, (a)): `semantext hook` keeps,
for each turn, where its record lies in the session's transcript (path, byte offset, length), so the kernel can find
the turn, write the person's act with its span, and check it again whenever the store is read. End to end: a hook
event, then a person act written, then a read, giving "applied (checked against your turn)"."""
import json
import os
from pathlib import Path

import pytest

from semantext import hook
from semantext.sources import work
from semantext.work.events import WorkRefused
from semantext.work.turns import TranscriptTurns, turns_root
from semantext.work.writer import Actor, Writer

SESSION = "0b6a1c2e-4d5f-4a7b-9c8d-112233445566"


def transcript(home_user: Path, *records) -> Path:
    """A session transcript in the tool's own folder (~/.claude/projects), one record a line."""
    t = home_user / ".claude" / "projects" / "proj" / f"{SESSION}.jsonl"
    t.parent.mkdir(parents=True, exist_ok=True)
    with open(t, "ab") as f:
        for r in records:
            f.write(json.dumps(r).encode("utf-8") + b"\n")
    return t


def user_dir() -> Path:
    return Path(os.environ["USERPROFILE"])


def typed(prompt, origin="human", uuid="u-1"):
    """A typed turn as the tool records it: its session, uuid and own time (the kernel reads them from here)."""
    from datetime import datetime, timezone
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {"type": "user", "turnOrigin": origin, "uuid": uuid, "sessionId": SESSION, "timestamp": at,
            "message": {"role": "user", "content": prompt}}


def event(prompt, t):
    return json.dumps({"prompt": prompt, "transcript_path": str(t), "session_id": SESSION})


def test_the_hook_keeps_each_turns_span_beside_it(home, store):
    said = typed("hello there")
    t = transcript(user_dir(), {"type": "assistant", "message": {"content": "earlier"}}, said)
    hook.run(event("hello there", t), store)
    rec = json.loads((turns_root(home) / f"{SESSION}.json").read_text(encoding="utf-8"))
    raw = t.read_bytes()
    first = raw.index(b"\n") + 1
    assert (rec["transcript"], rec["offset"], rec["length"]) == (str(t), first, len(raw) - first - 1)
    assert raw[rec["offset"]:rec["offset"] + rec["length"]] == json.dumps(said).encode("utf-8")
    assert rec["origin"] == "own" and rec["basis"] == "transcript" and "text" not in rec   # the words stay in the
    turn = TranscriptTurns(turns_root(home)).turn(SESSION)                                  # transcript, read from it
    assert (turn.text, turn.origin, turn.transcript, turn.offset) == ("hello there", "own", str(t), first)


def test_a_relayed_turn_is_kept_as_relayed(home, store):
    t = transcript(user_dir(), typed("W-semantext-1 park", origin="peer"))
    hook.run(event("W-semantext-1 park", t), store)
    assert TranscriptTurns(turns_root(home)).turn(SESSION).origin == "relayed"


def _writer(home):
    return Writer(home, projects={"semantext"}, seats={"alpha", "beta"}, turns=TranscriptTurns(turns_root(home)))


def test_end_to_end_a_hook_event_then_the_persons_act_then_a_read_is_checked_against_the_turn(home, store):
    w = _writer(home)
    ident = w.write(Actor("alpha", "bound", "mcp"), "create", {"project": "semantext", "title": "A task"})["id"]
    t = transcript(user_dir(), typed(f"{ident} park"))
    hook.run(event(f"{ident} park", t), store)
    got = w.person_act(SESSION, {"id": ident, "act": "park"})
    assert got["applied"] and got["item"]["state"] == "parked"
    page = work.load({"_home": str(home)}, projects={"semantext"})
    [item] = [i for i in page["items"] if i["id"] == ident]
    row = next(e for e in item["history"] if e["event"] == "person_act")
    assert row["applied"] and row["check"] == "verified" and item["state"] == "parked"
    from v2_node import NODE
    if NODE is None:
        pytest.skip("node is not installed: the page's own words for the row are not drawn")
    from semantext.sources.workplace import work_place
    from test_v2_work_page import draw
    data = json.loads(json.dumps(work_place({"work": page, "waiting": {"cards": []}, "record": {}})))
    assert any("applied (checked against your turn)" in line for line in draw(data, ident)["panel"])


def test_end_to_end_a_relayed_turn_writes_no_act(home, store):
    w = _writer(home)
    ident = w.write(Actor("alpha", "bound", "mcp"), "create", {"project": "semantext", "title": "A task"})["id"]
    t = transcript(user_dir(), typed(f"{ident} park", origin="peer"))
    hook.run(event(f"{ident} park", t), store)
    with pytest.raises(WorkRefused) as e:
        w.person_act(SESSION, {"id": ident, "act": "park"})
    assert e.value.code == "NOT_AUTHORIZED" and w.state()["items"][ident]["state"] == "backlog"
