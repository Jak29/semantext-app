"""A yes and the person's newest words. Without the Anthropic SDK: the proxy's own decision and replay are driven
directly (a Proxy on a temporary home, its handler's methods called with the reply captured).

First the yes paths as they are (a yes passes the call made again; a kept turn of two calls with both asks yes is sent
on whole; one yes of two is not; a no or a revoke drops it; another chat's yes does nothing). Then the newest words:
words the person writes AFTER the held turn that hold the act hold it again, on both paths, and the yes is not spent by
that; words that do not hold it let the yes through as before."""
from __future__ import annotations

import json

import pytest

from semantext import canon, decide, proxy
from tests.test_decide import call, msg, space_of, text

RM = canon.loads('{"command": "rm -rf logs"}')
RM2 = canon.loads('{"command": "rm -rf cache"}')
SECRET_RM = canon.loads('{"command": "rm -rf logs  # password = hunter22xyz"}')
STOP = "wait, do not delete anything. I changed my mind."
MODEL = "claude-opus-5-5"


class Rig:
    """One proxy (gated: Bash is held by its gate) and a handler whose replies are captured, not sent."""

    def __init__(self, tmp_path, drop=()):
        space_of(tmp_path, drop=drop)                       # writes tmp_path/space
        model = (f"id: claude\nkind: model\nprovider: anthropic\nmodel: {MODEL}\n"
                 f"endpoint: http://127.0.0.1:9\ncredential_host: 127.0.0.1\ntests: []\n")
        (tmp_path / "space" / "claude.yaml").write_text(model, encoding="utf-8")
        home = tmp_path / "home"
        home.mkdir()
        self.p = proxy.Proxy(tmp_path / "space", home, "card")
        self.sent, self.emitted = [], []

    def handler(self, body):
        h = object.__new__(proxy.Handler)
        h.proxy, h.path = self.p, "/v1/messages"
        h.chain = decide.Chain(self.p.key, body.get("messages"), body.get("system"), body.get("tools"), None)
        h._send = lambda code, data: self.sent.append((code, json.loads(data)))
        h._emit_whole = lambda m, stream: self.emitted.append(m)
        return h

    def conv(self, body):
        return proxy.conversation_key(self.p.key, body, None, "coder")

    def turn(self, messages, *blocks_):
        """The model answers this request with these blocks: the proxy's decision, as the client would get it."""
        body = self.body(messages)
        self.sent.clear()
        self.handler(body)._decide_and_emit(self.p.space(), "coder", "claude", body, self.conv(body),
                                            msg(text("deleting"), *blocks_), stream=False, live=False)
        return self.sent[-1][1]

    def replay(self, messages):
        """Whether this request is answered by the kept turn (True), and what was sent on."""
        body = self.body(messages)
        self.emitted.clear()
        got = self.handler(body)._replay(self.p.space(), "coder", "claude", body, self.conv(body))
        return got, self.emitted[-1] if self.emitted else None

    @staticmethod
    def body(messages):
        return {"model": MODEL, "messages": messages, "max_tokens": 10,
                "tools": [{"name": "Bash", "input_schema": {"type": "object"}}]}

    def yes(self, aid):
        assert self.p.asks.answer(aid, "yes", _now())

    def status(self, aid):
        return self.p.asks.status(aid, _now())


def _now():
    import time
    return time.monotonic()


def tool_uses(reply):
    return [b for b in reply["content"] if b.get("type") == "tool_use"]


def held_text(reply):
    return reply["content"][-1]["text"]


FIRST = [{"role": "user", "content": "go"}]


def after(held, last, first="go"):
    return [{"role": "user", "content": first},
            {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": held}]},
            {"role": "user", "content": last}]


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def hold(rig, *calls):
    reply = rig.turn(FIRST, *calls)
    assert not tool_uses(reply) and reply["stop_reason"] == "end_turn"
    asks = [a["id"] for a in rig.p.asks.snapshot().asks]
    return held_text(reply), asks


# ---- the yes paths as they are (characterisation) ----
def test_a_yes_passes_the_call_made_again(rig):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))           # a secret shape: not kept, so made again
    assert "not kept" in held
    rig.yes(aid)
    reply = rig.turn(after(held, "carry on"), call("Bash", SECRET_RM, "t2"))
    assert len(tool_uses(reply)) == 1 and rig.status(aid) == "spent"


def test_a_kept_turn_of_two_calls_with_both_yes_is_sent_on_whole(rig):
    held, aids = hold(rig, call("Bash", RM), call("Bash", RM2, "t2"))
    assert len(aids) == 2
    for a in aids:
        rig.yes(a)
    got, sent = rig.replay(after(held, "carry on"))
    assert got and [b["input"] for b in sent["content"]] == [RM, RM2]
    assert [rig.status(a) for a in aids] == ["spent", "spent"]


def test_one_yes_of_two_sends_nothing(rig):
    held, aids = hold(rig, call("Bash", RM), call("Bash", RM2, "t2"))
    rig.yes(aids[0])
    got, sent = rig.replay(after(held, "carry on"))
    assert not got and sent is None and rig.status(aids[0]) == "yes"


@pytest.mark.parametrize("word", ["no", "revoke"])
def test_a_no_or_a_revoke_drops_the_kept_turn(rig, word):
    held, (aid,) = hold(rig, call("Bash", RM))
    if word == "revoke":
        rig.yes(aid)
    assert rig.p.asks.answer(aid, word, _now())
    got, sent = rig.replay(after(held, "carry on"))
    assert not got and sent is None


def test_another_chats_yes_does_nothing(rig):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))
    rig.yes(aid)
    other = after(held, "carry on", first="another chat")
    assert not rig.replay(other)[0]
    reply = rig.turn(other, call("Bash", SECRET_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "yes"


# ---- the newest words win over an earlier yes, in the holding direction only ----
def test_words_after_the_yes_hold_the_kept_turn(rig):
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    got, sent = rig.replay(after(held, STOP))
    assert not got and sent is None                    # not sent on: the request goes on to the model instead
    assert rig.status(aid) == "yes"                    # and the yes is not spent by that


def test_words_after_the_yes_hold_the_call_made_again(rig):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))
    rig.yes(aid)
    reply = rig.turn(after(held, STOP), call("Bash", SECRET_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "yes"
    assert aid in held_text(reply) and "has the person's yes" in held_text(reply)   # on the same ask, said so
    assert "rm -rf" not in json.dumps(reply) and STOP not in held_text(reply)        # fixed words only
    assert [a["id"] for a in rig.p.asks.snapshot().asks] == [aid]


def test_the_control_the_same_words_with_no_yes_hold_the_call(rig):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))
    reply = rig.turn(after(held, STOP), call("Bash", SECRET_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "open"


def test_when_the_newest_words_no_longer_hold_the_yes_goes_through_once(rig):
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    stopped = after(held, STOP)
    assert not rig.replay(stopped)[0]
    # the model then makes the call again while the words still hold: held again, on the same ask, and kept
    again = rig.turn(stopped, call("Bash", RM, "t2"))
    assert not tool_uses(again) and [a["id"] for a in rig.p.asks.snapshot().asks] == [aid]
    later = stopped + [{"role": "assistant", "content": again["content"]},
                       {"role": "user", "content": "ok, go ahead now"}]
    got, sent = rig.replay(later)
    assert got and [b["input"] for b in sent["content"]] == [RM] and rig.status(aid) == "spent"


@pytest.mark.parametrize("words", ["Don't delete them yet.", "I'll delete the logs myself.",
                                   "Delete them tomorrow.", "Delete the logs. But don't delete anything yet.",
                                   "Ask me before you delete anything."])
def test_each_way_of_withholding_it_holds_the_kept_turn(rig, words):
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    assert not rig.replay(after(held, words))[0] and rig.status(aid) == "yes"


@pytest.mark.parametrize("words", ["ok, go ahead now", "carry on", "did the tests pass?", "thanks", "stop",
                                   "yes, delete them", "Delete the logs."])
def test_words_that_do_not_name_the_act_or_plainly_say_go_do_not_undo_it(rig, words):
    """The reader holds "ok, go ahead" here (it answers the proxy's own held text, not an offer of the act); but it names
    no act of the call, and the person's yes has answered the ask. Words that name the act as a plain go leave it too."""
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    got, sent = rig.replay(after(held, words))
    assert got and [b["input"] for b in sent["content"]] == [RM] and rig.status(aid) == "spent"


PUSH_RM = canon.loads('{"command": "git push origin main && rm -rf logs"}')
SECRET_PUSH_RM = canon.loads('{"command": "git push origin main && rm -rf logs  # password = hunter22xyz"}')
PUSH = canon.loads('{"command": "git push origin main"}')
BOTH = ["go ahead and push. do not delete anything.", "push it, but do not delete anything",
        "you can push if the tests pass, but do not delete anything"]


@pytest.mark.parametrize("words", BOTH)
def test_each_act_is_read_a_go_for_one_does_not_hide_a_stop_for_another_kept_turn(rig, words):
    held, (aid,) = hold(rig, call("Bash", PUSH_RM))
    rig.yes(aid)
    assert not rig.replay(after(held, words))[0] and rig.status(aid) == "yes"


@pytest.mark.parametrize("words", BOTH)
def test_each_act_is_read_a_go_for_one_does_not_hide_a_stop_for_another_made_again(rig, words):
    held, (aid,) = hold(rig, call("Bash", SECRET_PUSH_RM))
    rig.yes(aid)
    reply = rig.turn(after(held, words), call("Bash", SECRET_PUSH_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "yes"
    assert [a["id"] for a in rig.p.asks.snapshot().asks] == [aid]


@pytest.mark.parametrize("words", ["I forbid deleting", "abort the rm", "skip the delete", "refrain from deleting",
                                   "hold the delete", "Can you delete them?", "I already deleted the logs"])
def test_words_that_name_the_act_and_are_not_a_plain_go_hold_it(rig, words):
    """The last two are the cheap direction: a question and a statement about the past name the act, so they hold."""
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    assert not rig.replay(after(held, words))[0] and rig.status(aid) == "yes"


@pytest.mark.parametrize("words", ["push it now", "Push it.", "yes, push it"])
def test_a_plain_go_for_the_calls_own_act_leaves_the_yes(rig, words):
    held, (aid,) = hold(rig, call("Bash", PUSH))
    rig.yes(aid)
    got, sent = rig.replay(after(held, words))
    assert got and [b["input"] for b in sent["content"]] == [PUSH] and rig.status(aid) == "spent"


def test_a_revoke_after_words_held_it_drops_the_yes(rig):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))
    rig.yes(aid)
    stopped = after(held, "skip the delete")
    again = rig.turn(stopped, call("Bash", SECRET_RM, "t2"))
    assert not tool_uses(again)
    assert rig.p.asks.answer(aid, "revoke", _now())
    later = stopped + [{"role": "assistant", "content": again["content"]}, {"role": "user", "content": "carry on"}]
    reply = rig.turn(later, call("Bash", SECRET_RM, "t3"))
    assert not tool_uses(reply) and rig.status(aid) == "revoked"


def test_two_identical_calls_in_a_kept_turn_are_refused_with_a_true_reason(rig):
    held, (aid,) = hold(rig, call("Bash", RM), call("Bash", RM, "t2"))
    rig.yes(aid)
    body = rig.body(after(held, "carry on"))
    with pytest.raises(proxy.Refused) as e:
        rig.handler(body)._replay(rig.p.space(), "coder", "claude", body, rig.conv(body))
    assert "gates changed" not in e.value.reason and "same call" in e.value.reason
    assert rig.status(aid) == "yes"


# ---- words typed beside a tool's result, or after a reminder tag never closed: read for holds, never as a go ----
def beside(text, result="ok"):
    return [{"type": "tool_result", "tool_use_id": "zz", "content": result}, {"type": "text", "text": text}]


NEWER = {
    "beside a tool result": beside("do not delete anything"),
    "after an unclosed tag": "here is the old transcript: <system-reminder> blah\n\nanyway: do not delete anything",
}


def after_any(held, last, first="go"):
    return [{"role": "user", "content": first},
            {"role": "assistant", "content": [{"type": "text", "text": "deleting"}, {"type": "text", "text": held}]},
            {"role": "user", "content": last}]


@pytest.mark.parametrize("form", sorted(NEWER))
def test_a_withhold_beside_a_tool_result_holds_the_kept_turn(rig, form):
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    assert not rig.replay(after_any(held, NEWER[form]))[0] and rig.status(aid) == "yes"


@pytest.mark.parametrize("form", sorted(NEWER))
def test_a_withhold_beside_a_tool_result_holds_the_call_made_again(rig, form):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))
    rig.yes(aid)
    reply = rig.turn(after_any(held, NEWER[form]), call("Bash", SECRET_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "yes"
    assert [a["id"] for a in rig.p.asks.snapshot().asks] == [aid]


@pytest.fixture
def open_rig(tmp_path):
    return Rig(tmp_path, drop=("shell-held.yaml",))              # Bash not gated: without words, a push passes


PUSHING = [{"role": "user", "content": "go"}, {"role": "assistant", "content": [{"type": "text", "text": "running"}]}]


@pytest.mark.parametrize("last", [beside("don't push yet"),
                                  "notes: <system-reminder> pasted\n\nanyway: don't push yet"])
def test_the_plain_path_reads_a_withhold_beside_a_tool_result(open_rig, last):
    reply = open_rig.turn(PUSHING + [{"role": "user", "content": last}], call("Bash", PUSH))
    assert not tool_uses(reply)
    assert json.loads(open_rig.p.asks.path.read_text(encoding="utf-8"))[0]["reading"]["act"] == "push"


def test_a_tool_result_alone_holds_nothing(open_rig):
    last = [{"type": "tool_result", "tool_use_id": "zz", "content": "do not push anything"}]
    reply = open_rig.turn(PUSHING + [{"role": "user", "content": last}], call("Bash", PUSH))
    assert len(tool_uses(reply)) == 1


@pytest.mark.parametrize("text", ["yes", "Yes, push it now.", "push it"])
def test_text_beside_a_tool_result_never_releases_or_answers(rig, text):
    """A gated push with no yes stays held, its ask stays open; text there binds no yes to the offer."""
    held, (aid,) = hold(rig, call("Bash", SECRET_PUSH_RM))
    reply = rig.turn(after_any(held, beside(text)), call("Bash", SECRET_PUSH_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "open"


def test_text_beside_a_tool_result_does_not_replace_the_persons_own_hold(open_rig):
    msgs = [{"role": "user", "content": "Don't push yet."},
            {"role": "assistant", "content": [{"type": "text", "text": "Shall I push?"}]},
            {"role": "user", "content": beside("Yes")}]
    assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))


@pytest.mark.parametrize("text", ["ok, carry on", "thanks", "yes, delete them"])
def test_text_beside_a_tool_result_that_does_not_hold_leaves_the_yes(rig, text):
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    got, sent = rig.replay(after_any(held, beside(text)))
    assert got and [b["input"] for b in sent["content"]] == [RM] and rig.status(aid) == "spent"


# ---- the client's own sentences around words typed while a tool ran are not the person's words ----
# As Claude Code sends them (measured on its own requests, November 2026: 33 of 33 in one long session): a user message
# with the tool's result and ONE text block: the lead line, the person's words, a blank line, the client's paragraph.
LEAD = "The user sent a new message while you were working:"
TAIL = ("This is how Claude Code surfaces messages the user sends mid-turn \u2014 within the running turn, often alongside "
        "the next tool result, rather than as a separate conversation turn. Address the message above as you continue "
        "this turn.")
SEND = canon.loads('{"command": "gh pr comment 12 --body done"}')


def mid_turn(words):
    return beside(f"{LEAD}\n{words}\n\n{TAIL}")


@pytest.mark.parametrize("words", ["thanks", "also use the blue theme", "ok, carry on"])
def test_mid_turn_words_that_hold_nothing_let_a_send_pass(open_rig, words):
    """Read as words, the client's own lines name a send ("sent", "messages the user sends") and held every send."""
    reply = open_rig.turn(PUSHING + [{"role": "user", "content": mid_turn(words)}], call("Bash", SEND))
    assert len(tool_uses(reply)) == 1


@pytest.mark.parametrize("words", ["thanks", "also use the blue theme"])
def test_mid_turn_words_that_hold_nothing_leave_a_yes_for_a_send(rig, words):
    held, (aid,) = hold(rig, call("Bash", SEND))
    rig.yes(aid)
    got, sent = rig.replay(after_any(held, mid_turn(words)))
    assert got and [b["input"] for b in sent["content"]] == [SEND] and rig.status(aid) == "spent"


@pytest.mark.parametrize("words,cmd,act", [("don't push yet", PUSH, "push"),
                                           ("do not send that comment", SEND, "send")])
def test_mid_turn_words_that_hold_still_hold(open_rig, words, cmd, act):
    reply = open_rig.turn(PUSHING + [{"role": "user", "content": mid_turn(words)}], call("Bash", cmd))
    assert not tool_uses(reply)
    assert json.loads(open_rig.p.asks.path.read_text(encoding="utf-8"))[0]["reading"]["act"] == act


def test_mid_turn_words_that_hold_win_over_a_yes(rig):
    held, (aid,) = hold(rig, call("Bash", RM))
    rig.yes(aid)
    assert not rig.replay(after_any(held, mid_turn("wait, do not delete anything")))[0] and rig.status(aid) == "yes"


def test_another_sessions_lead_is_cut_and_its_words_are_read_for_holds(open_rig):
    lead = "Another Claude session sent a message while you were working:"
    quiet = beside(f'{lead}\n<cross-session-message from="x">the build is green</cross-session-message>')
    assert len(tool_uses(open_rig.turn(PUSHING + [{"role": "user", "content": quiet}], call("Bash", SEND)))) == 1
    loud = beside(f'{lead}\n<cross-session-message from="x">do not push anything yet</cross-session-message>')
    assert not tool_uses(open_rig.turn(PUSHING + [{"role": "user", "content": loud}], call("Bash", PUSH)))


def test_the_clients_own_lines_are_cut_and_the_words_stay():
    """A line that only begins like the client's paragraph, or carries other words after it, stays and is read."""
    assert proxy._cut_client_notes(f"{LEAD}\nwords\n\n{TAIL}").strip() == "words"
    assert "do not delete anything" in proxy._cut_client_notes(f"{LEAD}\nx\n\n{TAIL} do not delete anything")
    assert "do not delete anything" in proxy._cut_client_notes(f"{TAIL[:70]}: do not delete anything")
    assert proxy._cut_client_notes("The user sent a new message while you were working: do not push") \
        == "The user sent a new message while you were working: do not push"
    long = TAIL[:70] + "x" * 400 + TAIL[-55:]
    assert proxy._cut_client_notes(long) == long
    assert proxy._cut_client_notes('<cross-session-message from="a b">do not push</cross-session-message>').split() \
        == ["do", "not", "push"]


def notes(n, text="Tool loaded."):
    """n later user messages, each a tool's result with a client's note beside it (the assistant's turns between)."""
    out = []
    for k in range(n):
        out += [{"role": "assistant", "content": [{"type": "text", "text": "next"}]},
                {"role": "user", "content": beside(text if isinstance(text, str) else text(k))}]
    return out


@pytest.mark.parametrize("later", [notes(20), notes(20, lambda k: f"note number {k}"), notes(1, "filler words. " * 3000)],
                         ids=["twenty notes", "twenty different notes", "one long note"])
def test_what_the_person_typed_mid_turn_is_read_first_whatever_follows(open_rig, later):
    """A "don't push yet" typed while a tool ran, then more tool results with the client's notes beside them (or another
    session's long message): the typed words are still read. Before, the newest 16 texts were read, joined, up to the
    reader's 20,000 characters, so sixteen notes or one long one pushed the person's words out of the reading."""
    msgs = PUSHING + [{"role": "user", "content": mid_turn("don't push yet")}] + later
    assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))
    got = proxy.hold_only_words({"messages": msgs})
    assert "don't push yet" in got[0][0] and LEAD not in got[0][0]


def test_identical_notes_are_read_once_and_each_kind_is_capped():
    same = proxy.hold_only_words({"messages": PUSHING + notes(30)})
    assert [t.strip() for t, _ in same] == ["Tool loaded."] and same[0][1] == len(PUSHING) + 2 * 30 - 1
    msgs = PUSHING + [{"role": "user", "content": mid_turn(f"typed {k}")} for k in range(20)] \
        + notes(30, lambda k: f"note number {k}")
    got = proxy.hold_only_words({"messages": msgs})
    assert [t.strip() for t, _ in got[:proxy.MAX_HOLD_ONLY]] == [f"typed {k}" for k in range(19, 3, -1)]
    assert [t.strip() for t, _ in got[proxy.MAX_HOLD_ONLY:]] == [f"note number {k}" for k in range(29, 13, -1)]


def typed_block(words):
    return {"type": "text", "text": f"{LEAD}\n{words}\n\n{TAIL}"}


def result_block(n=0):
    return {"type": "tool_result", "tool_use_id": f"zz{n}", "content": "ok"}


XS = ("Another Claude session sent a message while you were working:\n"
      '<cross-session-message from="x">{}</cross-session-message>')


def test_typed_words_are_known_block_by_block(open_rig):
    """J1: a note in an earlier block of the same message ("Tool loaded.", which an agent makes by loading a tool) made
    the whole message other text, and one long later message from another session then pushed the typed hold out."""
    typed = {"role": "user", "content": [result_block(), {"type": "text", "text": "Tool loaded."},
                                         typed_block("don't push yet")]}
    msgs = PUSHING + [typed] + notes(1, XS.format("filler words. " * 2000))
    assert proxy.hold_only_words({"messages": msgs})[0][0].strip() == "don't push yet"
    assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))


def test_typed_words_are_read_whatever_the_size_of_the_blocks_after_them(open_rig):
    """J3: a message's text was read from its newest block back, up to 4 MiB, so 4 MiB of another session's message in
    a later block of the SAME message hid the typed block."""
    big = {"type": "text", "text": XS.format("x" * (proxy.MAX_RAW + 10))}
    msgs = PUSHING + [{"role": "user", "content": [result_block(), typed_block("don't push yet"), big]}]
    assert proxy.hold_only_words({"messages": msgs})[0][0].strip() == "don't push yet"
    assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))


def test_typed_words_at_the_end_of_a_message_of_too_many_blocks_are_read(open_rig):
    """J4: a message of more than MAX_BLOCKS blocks was skipped whole. Its last MAX_TYPED_TAIL blocks are now looked at
    for typed words, and for nothing else."""
    blocks = [result_block(k) for k in range(proxy.MAX_BLOCKS + 1)] \
        + [{"type": "text", "text": "do not push"}, typed_block("don't push yet")]
    msgs = PUSHING + [{"role": "user", "content": blocks}]
    assert [t.strip() for t, _ in proxy.hold_only_words({"messages": msgs})] == ["don't push yet"]
    assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))


@pytest.mark.parametrize("lead", ["\ufeff" + LEAD, "\u200b" + LEAD, LEAD.upper(), "  " + LEAD + "  "],
                         ids=["a byte-order mark", "a zero-width space", "upper case", "spaces"])
def test_the_lead_is_known_in_another_case_and_behind_a_mark(open_rig, lead):
    """J2: a byte-order mark, a zero-width character or another case made the typed words other text and left the lead
    in the reading, where it names a send."""
    block = {"type": "text", "text": f"{lead}\nthanks\n\n{TAIL}"}
    msgs = PUSHING + [{"role": "user", "content": [result_block(), block]}]
    assert [t.strip() for t, _ in proxy.hold_only_words({"messages": msgs})] == ["thanks"]
    assert len(tool_uses(open_rig.turn(msgs, call("Bash", SEND)))) == 1


def test_a_reminder_at_the_head_of_the_typed_block_does_not_hide_the_lead(open_rig):
    """R1: the lead was looked for at the raw start of the block, so a closed reminder section before it made the typed
    words other text (which a long later note crowds out); the commit before had cut closed reminders first."""
    block = {"type": "text",
             "text": f"<system-reminder>todo list changed</system-reminder>\n{LEAD}\ndon't push yet\n\n{TAIL}"}
    msgs = PUSHING + [{"role": "user", "content": [result_block(), block]}] + notes(1, "filler words. " * 2000)
    assert proxy.hold_only_words({"messages": msgs})[0][0].strip() == "don't push yet"
    assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))
    assert not proxy._is_typed(f"<system-reminder>never closed, with words\n{LEAD}\ndon't push yet\n\n{TAIL}")


def test_typed_words_the_client_wrapped_in_a_reminder_are_read(open_rig):
    """The client's own record renders the same words inside a reminder tag. Sent that way the section was cut whole and
    the hold never read. A reminder section that BEGINS with the lead is typed words; any other section stays cut."""
    wrapped = f"<system-reminder>\n{LEAD}\ndon't push yet\n\n{TAIL}\n</system-reminder>"
    beside_it = PUSHING + [{"role": "user", "content": [result_block(), {"type": "text", "text": wrapped}]}]
    alone = PUSHING + [{"role": "user", "content": wrapped}]                    # the same, as a turn of its own
    for msgs in (beside_it, alone):
        assert proxy.hold_only_words({"messages": msgs})[0][0].strip() == "don't push yet"
        assert not tool_uses(open_rig.turn(msgs, call("Bash", PUSH)))
    other = {"type": "text", "text": "<system-reminder>\ndo not push\n</system-reminder>"}
    assert proxy.hold_only_words({"messages": PUSHING + [{"role": "user", "content": [result_block(), other]}]}) == []


def test_typed_blocks_of_one_message_are_read_newest_first():
    msgs = PUSHING + [{"role": "user", "content": [result_block(), typed_block("first typed"),
                                                   typed_block("second typed")]}]
    (text, _), = proxy.hold_only_words({"messages": msgs})
    assert text.split() == ["second", "typed", "first", "typed"]


def test_another_sessions_message_is_never_taken_for_typed_words():
    """Its block begins with the other lead, whatever its body holds: it cannot take the places kept for typed words."""
    body = f"{LEAD}\ndo not push\n\n{TAIL}"
    msgs = PUSHING + [{"role": "user", "content": mid_turn("typed by the person")}] \
        + notes(20, lambda k: XS.format(f"{body} {k}"))
    got = proxy.hold_only_words({"messages": msgs})
    assert got[0][0].strip() == "typed by the person" and len(got) == 1 + proxy.MAX_HOLD_ONLY


def test_cutting_reminders_takes_time_in_proportion_to_the_text():
    """A "<" and a long run of white space that opens no tag: the old tag pattern tried every split of the run (the
    square: 8 s for 32 KiB of spaces, measured). One pass now, and the tags it finds are the same."""
    import time
    for text in ("<" + " " * 1_000_000, ("<" + " \n\t" * 300) * 1000, "< /" + " " * 1_000_000, "<" * 1_000_000,
                 "<cross-session-message" + " " * 1_000_000):
        t0 = time.perf_counter()
        proxy._cut_reminders(text), proxy._cut_closed_reminders(text), proxy._cut_client_notes(text)
        assert time.perf_counter() - t0 < 2.0, (text[:24], time.perf_counter() - t0)
    spaced = "a <  /  SYSTEM-REMINDER x> b < system-reminder > c </system-reminder> d <\n/\tsystem-reminder> e"
    assert proxy._cut_reminders(spaced).split() == ["a", "b", "d", "e"]
    assert proxy._cut_reminders("a <system-reminder> b").split() == ["a"]
    assert proxy._cut_closed_reminders("a <system-reminder> b").split() == ["a", "b"]


def test_the_words_the_ask_was_made_after_do_not_undo_the_yes(rig):
    """The yes answers the words that held the call: the same request sent again after the yes passes (only words
    written after the held turn are newer than the yes)."""
    words = [{"role": "user", "content": "Do not delete anything yet."}]
    reply = rig.turn(words, call("Bash", SECRET_RM))
    assert not tool_uses(reply)
    (aid,) = [a["id"] for a in rig.p.asks.snapshot().asks]
    rig.yes(aid)
    again = rig.turn(words, call("Bash", SECRET_RM, "t2"))
    assert len(tool_uses(again)) == 1 and rig.status(aid) == "spent"


def test_a_go_in_the_newest_words_releases_nothing_without_a_yes(rig):
    held, (aid,) = hold(rig, call("Bash", SECRET_RM))
    reply = rig.turn(after(held, "Yes, delete the logs now."), call("Bash", SECRET_RM, "t2"))
    assert not tool_uses(reply) and rig.status(aid) == "open"
