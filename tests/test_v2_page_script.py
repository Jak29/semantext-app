"""The v2 page's own modules, run in node on a small stand-in for the browser's document (tests/v2_dom.js).

These check what the page draws, not what the server answers: a waiting card's extras are folded, the problems count
equals the problems, markdown is set as text, the gaming indicator says what the flag says, and Done shows each run's
output. Every check has a must-pass arm and a must-refuse arm. Skipped where node is not installed.
"""
from __future__ import annotations

import re

import pytest

from v2_node import NODE, run

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


CARD = """
const card = (over) => Object.assign({ key: "Alder/A-1", seat: "Alder", id: "A-1", kind: "decision", title: "Pick one",
  why: "because", question: "Which?", options: ["first", "second"], state: "waiting", asks: "Alder", acts: "Alder",
  asks_basis: "it filed the card", acts_basis: "it acts on it", at: "2026-10-01T10:00:00Z", notes: [],
  project: { id: "p1", name: "lab", via: "cwd" },
  earlier: [{ id: "J-1", date: "2026-10-01", status: "in force", words: "Yes, the first.", link: "cites this card" }] }, over || {});
const details = (n) => n.all((e) => e.tagName === "DETAILS");
"""


def test_a_waiting_cards_extras_are_folded_until_clicked():
    got = run(CARD + """
const n = cardNode(card());
const more = details(n).filter((d) => d.className === "more");
const outside = n.childNodes.filter((c) => !(c.tagName === "DETAILS")).map((c) => c.textContent).join(" ");
S.open.add("more:Alder/A-1");
const again = details(cardNode(card())).filter((d) => d.className === "more");
const bare = cardNode(card({ earlier: [], project: null }));
report({ count: more.length, open: more.map((d) => d.open), summary: more[0].children[0].textContent,
         inside: more[0].textContent, outside, reopened: again.map((d) => d.open),
         bareSummary: details(bare)[0].children[0].textContent });
""")
    assert got["count"] == 1 and got["open"] == [False]                      # must pass: folded by default
    assert got["summary"] == "Your earlier words (1) · Asks, acts, project"   # the line still says they are there
    assert "Asks: Alder" in got["inside"] and "Yes, the first." in got["inside"]
    assert "Asks:" not in got["outside"] and "Yes, the first." not in got["outside"]   # not shown outside the fold
    assert got["reopened"] == [True]                                         # must refuse: a click's opening is kept
    assert got["bareSummary"] == "Asks, acts"


def test_the_bar_counts_the_problems_and_opens_them_on_a_click():
    got = run("""
const problems = (n) => Array.from({ length: n }, (_, i) => ({ reader: "waiting", source: "f" + i, line: i + 1, kind: "bad json", text: "line " + i }));
S.place = "waiting";
const state = () => ({ count: $("problems-count").textContent, countHidden: $("problems-count").hidden,
  expanded: $("problems-count").getAttribute("aria-expanded"), boxHidden: $("problems").hidden,
  items: $("problems").all((e) => e.tagName === "LI").length });
applyFrame({ waiting: 1, problems: problems(3), gaming: { state: "off" } });
const closed = state();
$("problems-count").click();
const opened = state();
$("problems-count").click();
const shut = state();
applyFrame({ waiting: 1, problems: problems(1), gaming: { state: "off" } });
const one = state();
applyFrame({ waiting: 1, problems: [], gaming: { state: "off" } });
const none = state();
S.place = "projects";
applyFrame({ waiting: 1, problems: problems(2), gaming: { state: "off" } });
const elsewhere = Object.assign(state(), { folded: $("problems").all((e) => e.tagName === "DETAILS").length });
report({ closed, opened, shut, one, none, elsewhere });
""")
    assert got["closed"] == {"count": "3 file problems", "countHidden": False, "expanded": "false", "boxHidden": True,
                             "items": 3}                                     # the cards lead: the list waits for a click
    assert got["opened"]["boxHidden"] is False and got["opened"]["expanded"] == "true" and got["opened"]["items"] == 3
    assert got["shut"]["boxHidden"] is True
    assert got["one"]["count"] == "1 file problem"
    # must refuse: no problems, no count and no box; elsewhere the folded box stays and the bar shows no count
    assert got["none"]["countHidden"] is True and got["none"]["boxHidden"] is True
    assert got["elsewhere"]["countHidden"] is True and got["elsewhere"]["boxHidden"] is False
    assert got["elsewhere"]["folded"] == 1 and got["elsewhere"]["items"] == 2


def test_waiting_puts_its_heading_search_and_toggle_in_the_bar():
    got = run(CARD + """
S.place = "waiting"; mount();
S.data.waiting = { off: false, missing: [], cards: [card(), card({ key: "Alder/A-2", id: "A-2" })], seats: ["Alder"],
  record: { off: true }, holds: { text: "" } };
fill();
const bar = $("bar-place");
const place = $("place");
const before = [];
for (const c of place.childNodes) { if (c === W.list) break; before.push(c); }
const visible = before.filter((c) => !c.hidden).flatMap((c) => c.all((e) => !/sr-only/.test(e.className))).map((e) => e.tagName);
const heading = before.map((c) => c.all((e) => e.tagName === "H1").map((e) => e.className)).flat();
const firstCard = W.list.children[0] && W.list.children[0].getAttribute("data-card");
S.data.waiting = { off: true, missing: ["seats"], cards: [], seats: [] };
fill();
report({ barInputs: bar.all((e) => e.tagName === "INPUT").length, barButtons: bar.all((e) => e.tagName === "BUTTON").map((b) => b.textContent),
  say: W.say.textContent, placeInputs: place.all((e) => e.tagName === "INPUT").length, visible,
  firstCard, heading, offHeading: W.head.all((e) => e.tagName === "H1").map((e) => [e.className, e.textContent]), toolsHidden: W.tools.hidden });
""")
    assert got["barInputs"] == 1 and got["barButtons"] == ["By project"] and got["placeInputs"] == 0
    assert got["say"] == "2 cards wait for your word, newest first."
    assert got["visible"] == [] and got["heading"] == ["sr-only"]           # nothing visible above the first card
    assert got["firstCard"] == "Alder/A-1"
    # must refuse: when Waiting is off, there are no cards to lead, and the heading says why in the place
    assert got["offHeading"] == [["", "Waiting"]] and got["toolsHidden"] is True


def test_markdown_is_set_as_text_and_links_are_kept_to_what_is_safe():
    got = run("""
const doc = { id: "abc1234567", master: "MASTER.md", docs: [{ file: "part.md", title: "A part" }], diagrams: ["flow.svg"], updated: "x" };
const md = [
  "# Title <b>bold</b>", "", "Some **strong** and *soft* and `code <i>x</i>`.", "",
  "<script>alert(1)</script>", "", "<img src=x onerror=alert(1)>", "",
  "- one", "- two", "", "1. first", "", "> a quote", "", "```", "<b>in code</b>", "```", "",
  "| a | b |", "|---|---|", "| 1 | <u>2</u> |", "",
  "[web](https://example.test/x) [part](part.md) [back](MASTER.md) [other](other.md) [js](javascript:alert(1))",
  "[plain](http://example.test) [up](../x.md) ![flow](flow.svg) ![away](https://example.test/x.svg)"].join("\\n");
const root = document.createElement("div");
root.append(renderMarkdown(md, { doc }));
const tags = root.all().map((e) => e.tagName);
const links = root.all((e) => e.tagName === "A").map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("target"), a.getAttribute("rel")]);
report({ tags: [...new Set(tags)].sort(), text: root.textContent, links,
  imgs: root.all((e) => e.tagName === "IMG").length, figures: root.all((e) => e.tagName === "FIGURE").length });
""")
    tags = set(got["tags"])
    assert {"H2", "P", "STRONG", "EM", "CODE", "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "TABLE", "TH", "TD"} <= tags
    # must refuse: markup in the document is never markup on the page; it is there as the text it is
    assert not tags & {"B", "I", "U", "SCRIPT", "IMG"}
    for written in ("<b>bold</b>", "<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "<b>in code</b>",
                    "<u>2</u>", "<i>x</i>"):
        assert written in got["text"], written
    assert got["links"] == [["web", "https://example.test/x", "_blank", "noopener noreferrer"],
                            ["part", "#documents/abc1234567/part.md", None, None],
                            ["back", "#documents/abc1234567", None, None]]
    for plain in ("other (other.md)", "js (javascript:alert(1))", "plain (http://example.test)", "up (../x.md)",
                  "[diagram: away]"):
        assert plain in got["text"], plain                                   # anything else is plain text
    assert got["figures"] == 2 and got["imgs"] == 0                          # the listed diagram waits for its read


def test_the_gaming_indicator_says_what_the_flag_says():
    got = run("""
const now = Date.parse("2026-10-23T12:00:00Z");
const until = now / 1000 + 3600;
const words = (g, t) => { const w = gamingWords(g, t); return w && w.text; };
const show = (g) => { applyFrame({ waiting: 0, problems: [], gaming: g }); return [$("gaming").hidden, $("gaming").textContent]; };
report({ on: words({ state: "on", until_epoch: until }, now), expect: "Gaming hold until " + hhmm(until * 1000),
  lapsed: words({ state: "on", until_epoch: until }, until * 1000), early: words({ state: "on", until_epoch: until }, until * 1000 - 1),
  off: words({ state: "off" }, now), unknown: words({ state: "unknown", why: "not JSON" }, now), noEnd: words({ state: "on" }, now),
  shownOff: show({ state: "off" }), shownUnknown: show({ state: "unknown" }), shownNone: show(undefined),
  shownOn: show({ state: "on", until_epoch: Date.now() / 1000 + 600 }) });
""")
    assert got["on"] == got["expect"] and got["on"].startswith("Gaming hold until ")
    assert got["early"] == got["on"]
    # must refuse: at its end time it lapses; off shows nothing; an unreadable flag is never shown as off
    assert got["lapsed"] is None and got["off"] is None and got["noEnd"] is None
    assert got["unknown"] == "Gaming state unknown"
    assert got["shownOff"] == [True, ""] and got["shownUnknown"] == [False, "Gaming state unknown"]
    assert got["shownNone"] == [True, ""]        # a server too old to send the flag: nothing is claimed either way
    assert got["shownOn"][0] is False and got["shownOn"][1].startswith("Gaming hold until ")


def test_a_change_card_shows_its_proposal_and_never_an_act():
    got = run(CARD + """
const ch = (over) => card(Object.assign({ kind: "change", question: null, options: [], asked_in: ["Alder/A-2"], decided: false, change: Object.assign({
  component: "rule", hypothesis: "A shorter card is read.", trigger: "three long answers", regression_risk: "a detail is cut",
  why_not_smaller: "chat was tried", retroactive_check: "C-1 would pass", prune: false,
  predicted: [{ measure: "answer length", direction: "down", p: 0.8 }], undo: { commit: "abc1234" },
  what_changes: { added: ["NEW.md"], removed: [], changed: ["CLAUDE.md"], always_on_char_delta: -9 },
  evidence: { files: ["C:/lab/rule.md"], digest: "aa" }, freshness: { state: "stale", digest: "aa", today: "bb" } }, over || {}) }));
const n = cardNode(ch());
const text = n.textContent;
const buttons = n.all((e) => e.tagName === "BUTTON").map((b) => b.textContent);
const reasoning = details(n).filter((d) => d.children[0].textContent === "How it was reasoned");
const fresh = cardNode(Object.assign(ch({ freshness: { state: "current" }, undo: null, predicted: [], prune: true }), { asked_in: [] }));
const bads = (x) => x.all((e) => e.className === "bad").map((e) => e.textContent);
const asking = cardNode(card({ key: "Alder/A-2", id: "A-2", change_id: "A-1" })).textContent;
const plain = cardNode(card({ key: "Alder/A-3", id: "A-3", change_id: null, change_unknown: "A-404" })).textContent;
report({ text, buttons, asking, plain, kind: n.all((e) => /chip kind/.test(e.className))[0].textContent, bad: bads(n),
  reasoningOpen: reasoning.map((d) => d.open), reasoningText: reasoning[0].textContent,
  freshText: fresh.textContent, freshBad: bads(fresh), freshKind: fresh.all((e) => /chip kind/.test(e.className))[0].textContent });
""")
    assert got["kind"] == "Change" and got["freshKind"] == "Prune"
    for said in ("A shorter card is read.", "answer length down (chance stated 80%)", "a detail is cut",
                 "1 file added, 1 file changed; always-on text \u22129 characters", "back to commit abc1234",
                 "Asked in A-2. Nothing proposed runs before your word."):
        assert said in got["text"], said
    assert got["bad"] == ["stale: the files it was measured on have changed since"]
    assert got["reasoningOpen"] == [False] and "C-1 would pass" in got["reasoningText"]
    # must-refuse: no button performs the undo or anything else: the agent chip, the ID copy, and the link to the
    # decision card that asks about it
    assert got["buttons"] == ["Alder", "A-1", "A-2"]
    assert "It asks about the proposed change A-1." in got["asking"]
    assert "proposed change" not in got["plain"]                            # an unknown id is never linked
    assert "No decision card asks about it yet" in got["freshText"]
    assert "current: the files it was measured on are unchanged" in got["freshText"]
    assert set(got["freshBad"]) == {"no measure named, so its effect cannot be checked", "none given"}


def test_the_record_zooms_from_threads_to_entries_to_the_source():
    got = run("""
const long = "x".repeat(600);
S.place = "record"; mount();
S.data.record = { off: false, notes_off: false, files: { register: "r.jsonl" }, whole_bytes: 512,
  counts: { entries: 3, threads: 2, by_status: { "in force": 1, superseded: 1, parked: 1 } },
  threads: [{ key: "t1", subject: "Gaming", entries: ["J-1", "J-2"], current: "in force", to: ["Alder"], first: "2026-10-01", last: "2026-10-02" },
            { key: "t2", subject: "Holds", entries: ["J-3"], current: "parked", to: [], first: "2026-10-03", last: "2026-10-03" }],
  entries: [
    { id: "J-1", subject: "Gaming", date: "2026-10-01", words: "Hold heavy work <b>now</b>.", computed_status: "superseded", stored_status: "in force",
      superseded_by: ["J-2"], supersedes: [], source: "box@abc1234:NOTES.md:7", pin: { repo: "box", commit: "abc1234", file: "NOTES.md", line: 7, last_line: 7 },
      reading: "The scribe's reading.", notes: [] },
    { id: "J-2", subject: "Gaming", date: "2026-10-02", words: long, offer: "the offer", computed_status: "in force", stored_status: "in force",
      superseded_by: [], supersedes: ["J-1"], source: "not a pin", pin: null, notes: [] },
    { id: "J-3", subject: "Holds", date: "2026-10-03", words: "Not now.", computed_status: "parked", stored_status: "parked", superseded_by: [], supersedes: [], source: "box@abc1234:N.md:3-5",
      pin: { repo: "box", commit: "abc1234", file: "N.md", line: 3, last_line: 5 }, notes: [] }] };
const at = (sub) => { S.sub = sub; fill(); return $("place").textContent; };
const level1 = at(null);
const rows = $("place").all((e) => e.tagName === "A" && /threadrow/.test(e.className)).map((a) => a.getAttribute("href"));
const level2 = at("t/t1");
const level2Bytes = $("place").all((e) => e.tagName === "BLOCKQUOTE").map((b) => new TextEncoder().encode(b.textContent).length);
const level3 = at("J-1");
const level3Long = at("J-2");
const hold = at("J-3");
const missing = at("J-404");
S.sub = null; S.q.record = "heavy work"; fill();
const found = $("place").all((e) => e.getAttribute && e.getAttribute("data-entry")).map((e) => e.getAttribute("data-entry"));
S.q.record = "scribe's reading"; fill();
const notFound = $("place").all((e) => e.getAttribute && e.getAttribute("data-entry")).length;
report({ level1, rows, level2, level2Bytes, level3, level3Long, hold, missing, found, notFound });
""")
    assert got["rows"] == ["#record/t/t1", "#record/t/t2"] and "Gaming" in got["level1"]
    assert "Hold heavy work" not in got["level1"]                          # level 1 is threads, one line each
    assert "Superseded by J-2" in got["level2"] and "more bytes, not shown here" in got["level2"]
    assert max(got["level2Bytes"]) <= 512 + 3                                # cut at 512 bytes, with an ellipsis
    assert "Hold heavy work <b>now</b>." in got["level2"]                    # short words whole, as text
    assert "box at commit abc1234, NOTES.md, line 7" in got["level3"]
    assert "An agent's one-line reading of your words, not your words." in got["level3"]
    assert "Superseded by J-2" in got["level3"] and "x" * 600 in got["level3"]   # what superseded it, whole
    assert "x" * 600 in got["level3Long"]                                    # the source level is whole
    # must-refuse: a source that is not a pin gets no invented line; a hold says what the register does not hold
    written = got["level3Long"].split("Written down")[1]
    assert written.startswith("not a pin (not in repo@commit:file:line form, so no line is given)")
    assert re.search(r"lines? \d", written) is None
    assert "lines 3 to 5" in got["hold"] and "keeps no separate field for what it stops or who lifts it" in got["hold"]
    assert "No decision in your register has the id J-404" in got["missing"]
    assert got["found"] == ["J-1"] and got["notFound"] == 0                 # search reads your words, not the reading


def test_the_rules_drawer_shows_each_level_with_its_source():
    got = run("""
const rule = (over) => Object.assign({ id: "core.a", words: "Ask first.", held: "written", cases: [], checkers: [], guards: [] }, over || {});
const text = (r) => ruleNode(rule(r)).textContent;
const data = (folders, once) => ({ off: false, run_records: folders, counts: { rules: 4, environments: 1, written: 2, checked: 2, guarded_once: once || 0, guarded: 0 },
  environments: [{ name: "core", rules: [rule()] }], agents: {} });
const drawer = (f, once) => DRAW.rules(data(f, once), {})[1].map((p) => p.textContent).join(" ");
const run = (state, over) => Object.assign({ checker: "semantext-prove", version: "0.1.0", at: "2026-10-23T20:00:00Z", state, stale: [],
  arms: { must_pass: { ran: 3, passed: 3 }, must_refuse: { ran: 4, refused: 4 } } }, over || {});
const named = { name: "pre-write hook", where: "hooks/x", must_pass: ["a short answer"], must_refuse: ["a long one"] };
report({ written: text(), checked: text({ held: "checked", cases: [{ id: "C-1", kept_in: ["core"] }, { id: "C-9", kept_in: [] }] }),
  named: text({ held: "checked", checkers: [named] }),
  guarded: text({ held: "guarded", runs: [run("guarded", { note: "<b>n</b>" })] }),
  stale: text({ held: "guarded once", runs: [run("stale", { stale: ["src/hook.py has changed since it was checked"] })] }),
  failed: text({ held: "written", runs: [run("failed", { arms: { must_pass: { ran: 3, passed: 2 }, must_refuse: { ran: 4, refused: 4 } } })] }),
  found: text({ held: "guarded", runs: [run("guarded", { findings: ["the two answers differ", "<i>x</i>"] })] }),
  claimed: text({ guards: ["a hook"] }), noFile: drawer(null), withFile: drawer(["/repo"], 1) });
""")
    # findings are shown with their count and as text, and never change the level
    assert "core.a · guarded, with 2 findings" in got["found"] and "Guarded, with 2 findings: must-pass" in got["found"]
    assert "Finding: the two answers differ" in got["found"] and "Finding: <i>x</i>" in got["found"]
    assert "core.a · guarded" in got["guarded"] and "finding" not in got["guarded"]   # none: plain guarded
    assert "Its words alone" in got["written"]
    assert "Checked by C-1 (kept in core)" in got["checked"] and "C-9, which no card keeps" in got["checked"]
    recorded = "(recorded by semantext-prove 0.1.0 at 2026-10-23T20:00:00Z; not re-run by this page)"
    assert ("Guarded: must-pass 3 of 3 passed, must-refuse 4 of 4 refused " + recorded) in got["guarded"]
    assert "Its note: <b>n</b>" in got["guarded"]                          # a note is text, shown as text
    assert ("Guarded once, now stale: src/hook.py has changed since it was checked." in got["stale"]
            and recorded in got["stale"] and "guarded once" in got["stale"])
    assert "did not pass (must-pass 2 of 3 passed" in got["failed"] and "earns nothing" in got["failed"]
    # must-refuse: a checker the guards file names is listed as a claim, and the rule stays checked
    assert "Your guards file names pre-write hook (hooks/x): it must let pass a short answer, and it must refuse a long one." in got["named"]
    assert "earns nothing by itself" in got["named"] and "Guarded:" not in got["named"]
    assert "2 written (50%), 2 checked (50%), 0 guarded (0%)" in got["noFile"] and "guarded once (" not in got["noFile"]
    assert "1 guarded once (25%)" in got["withFile"]
    # must-refuse: a guard the card only mentions is a claim, never "guarded"; with no run-record folder, the drawer says so
    assert "guarded" not in got["claimed"].split("Ask first.")[1].split("The card says")[0]
    assert "counts for nothing" in got["claimed"]
    assert "names no run-record folder" in got["noFile"] and "names no run-record folder" not in got["withFile"]


def test_done_shows_each_runs_output_as_text():
    got = run(CARD + """
const ran = card({ kind: "command", state: "run", command: "Write-Output 1", run: { started: "s", finished: "f", exit: 0, timed_out: false },
  output: { stdout: "  <b>one</b>\\n", stderr: "a warning", stdout_cut: 0, stderr_cut: 5 } });
const n = cardNode(ran);
const out = details(n).filter((d) => d.className === "output");
const silent = details(cardNode(card({ kind: "command", state: "run", command: "x", run: { started: "s", finished: "f", exit: 0 }, output: null })))
  .filter((d) => d.className === "output");
const blank = details(cardNode(card({ kind: "command", state: "run", command: "x", run: { started: "s", finished: "f", exit: 0 },
  output: { stdout: "  ", stderr: "" } }))).filter((d) => d.className === "output");
report({ count: out.length, open: out.map((d) => d.open), summary: out[0].children[0].textContent,
  pres: out[0].all((e) => e.tagName === "PRE").map((p) => [p.className, p.textContent]),
  tags: out[0].all().map((e) => e.tagName), text: out[0].textContent, silent: silent.length, blank: blank.length });
""")
    assert got["count"] == 1 and got["open"] == [False] and got["summary"] == "Output"
    assert got["pres"] == [["command out", "<b>one</b>"], ["command err", "a warning"]]   # trimmed, as the inbox shows it
    assert "B" not in got["tags"] and "5 more characters of stderr" in got["text"]
    assert got["silent"] == 0 and got["blank"] == 0                          # must refuse: no output, no Output
