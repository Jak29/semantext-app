"""The `semantext` command."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

import yaml

from . import __version__, agentfiles, claude, jsonread, paths
from .feed import Feed
from .heard import Heard
from .hook import LIMIT_BYTES
from .hook import main as hook_main
from .agents import Agents, Identity, clean, key_shaped, since
from .inbox import (AGENT_MARKERS, HOW_WORDS, Inbox, age, asked_before, describe_answer, human_terminal, mine,
                    register_line)
from .backtest import backtest as run_backtest
from .reader import EndpointReader, OllamaReader, is_local, model_backtest
from .mine import mine as mine_history, project_transcripts
from .sender import users_sentence
from .store import FEATURES, Refused, Store, now


def _out(text: str = "") -> None:
    print(text)


def _env(store: Store, args) -> str:
    given = getattr(args, "env", None)
    name = store.resolve(given) if given else store.state()["active"]   # a name or a title; refuses an unknown one
    store.path(name)
    return name


def _users_act(what: str) -> None:
    """Changing the user's rules is the user's act, like answering: refused in an agent's shell, or anywhere that is
    not their own terminal. An agent proposes a rule with `teach`, and asks for anything else in the inbox."""
    why_not = human_terminal()
    if why_not:
        raise Refused(f"cannot {what} here: {why_not}. Only the user changes their rules, at their own terminal or on "
                      f"the page. Propose a rule with `semantext teach`; ask for anything else with `semantext ask`")


# ---- environments and rules -------------------------------------------------------------------------------------
def cmd_init(store: Store, args) -> int:
    _out(f"Semantext {__version__} is ready in {store.root}")
    _out(f"Active environment: {store.title(store.state()['active'])}")
    _out("Next: `semantext card` shows what your AI will receive; `semantext install claude-code` connects it.")
    return 0


def cmd_card(store: Store, args) -> int:
    _out(store.card(_env(store, args), agent=args.agent))
    return 0


def cmd_env(store: Store, args) -> int:
    active = store.state()["active"]
    if args.action in ("use", "new", "add"):
        _users_act({"use": "switch environments", "new": "make an environment", "add": "add rules"}[args.action])
    if args.action == "use":
        if not args.name_or_title:
            raise Refused("name one environment to use, for example: semantext env use default")
        name = store.resolve(" ".join(args.name_or_title))   # its name or its title: env use "Deep Work"
        store.set_active(name)
        _out(f"Active environment: {store.title(name)}")
        return 0
    if args.action == "new":
        title = " ".join(args.name_or_title)
        if not title:
            raise Refused("give the new environment a title, for example: semantext env new Office")
        sg = store.suggest(title)
        if args.none:
            picks = []
        elif args.pick:
            # Any suggestion from any pack may be picked, by its id (for example work.outcome-first).
            every = {e["id"]: p["environment"]["id"] for p in store.packs() for e in p.get("entries") or []}
            missing = [i for i in args.pick if i not in every]
            if missing:
                raise Refused(f"no such suggestion: {', '.join(missing)} (see them with: semantext env ideas)")
            picks = [{"pack": every[i], "id": i} for i in args.pick]
        elif sg["matched"]:
            picks = [{"pack": r["pack"], "id": r["id"]} for r in sg["rules"] if r["ticked"]]
        else:
            picks = []
        name = store.create(title, picks)
        _out(f"Made {store.title(name)} ({name}) with {len(picks)} suggested rule{'s' if len(picks) != 1 else ''}; "
             f"it is now active.")
        for x in store.load(name).get("entries") or []:
            _out(f"  {x['id']}: {x['statement']}")
        if picks:
            _out("Switch one off with `semantext toggle ID`.")
        if not sg["matched"] and not args.pick and not args.none:
            _out(f"No suggestion pack matches \"{title}\", so it starts empty. Ideas, one from each pack:")
            for r in sg["rules"]:
                _out(f"  {r['id']}: {r['statement']}")
        _out(f"Add suggestions with `semantext env add ID [ID ...]` (every idea: semantext env ideas), "
             f"or teach your own with `semantext teach WORDS`.")
        return 0
    if args.action == "add":
        if not args.name_or_title:
            raise Refused("name the suggestions to add, for example: semantext env add work.outcome-first")
        target = store.resolve(args.env) if args.env else store.state()["active"]
        added = store.add_suggestions(target, args.name_or_title)
        _out(f"Added {len(added)} rule{'s' if len(added) != 1 else ''} to {store.title(target)}"
             + (f": {', '.join(added)}" if added else " (it already holds them)."))
        return 0
    if args.action == "ideas":
        for p in store.packs():
            env = p["environment"]
            _out(f"{env.get('title', env['id'])} ({env['id']}): {', '.join(env.get('keywords') or [])}")
            for e in p.get("entries") or []:
                _out(f"  {e['id']}: {e['statement']}")
        return 0
    for n in store.names():
        if n == "base":
            continue
        d = store.load(n)
        live = store.live(d.get("entries"))
        mark = "*" if n == active else " "
        _out(f"{mark} {n:<20} {d['environment'].get('title', n):<20} {len(live)} rule{'s' if len(live) != 1 else ''}")
    _out("(* active; every environment also carries the base rules)")
    return 0


def cmd_rules(store: Store, args) -> int:
    name = _env(store, args)
    chain = ["base", name] if args.base else [name]
    for n in chain:
        d = store.load(n)
        entries = d.get("entries") or []
        if args.agent and n == name:   # that agent's own layer, instead of the shared rules
            entries = store.layers(d).get(args.agent) or []
            _out(f"{d['environment'].get('title', n)} ({n}), for {args.agent} only")
        else:
            _out(f"{d['environment'].get('title', n)} ({n})")
        shown = 0
        for x in entries:
            if x.get("archived") and not args.all:
                continue
            state = "archived" if x.get("archived") else ("on" if x.get("enabled", True) else "off")
            _out(f"  [{state:<8}] {x.get('mode', 'stationary'):<10} {x['id']}")
            _out(f"             {' '.join(str(x['statement']).split())}")
            shown += 1
        if not shown:
            _out("  (no rules of its own yet)")
        hidden = sum(1 for x in entries if x.get("archived")) if not args.all else 0
        if hidden:
            _out(f"  ({hidden} undone rule{'s' if hidden != 1 else ''} hidden; --all shows {'them' if hidden != 1 else 'it'})")
    return 0


def cmd_teach(store: Store, args) -> int:
    name, words, agent = _env(store, args), " ".join(args.words), clean(args.agent) if args.agent else None
    if human_terminal() is None:
        rid = store.learn(name, words, agent=agent, misread=args.misread)
        _out(f"Learned {rid}" + (f", for {agent} only," if agent else "") + " with your words kept beside it"
             + (", and the message it was taught from kept as its test." if args.misread else "."))
        return 0
    if args.misread:   # the message an AI misread is kept only as the user's own act, like the rule itself
        raise Refused("a misread message is kept as a test only from your own terminal or the page")
    who = _who(store)
    # An agent may be the scribe of the user's own words: a whole sentence the user wrote in this very session, as
    # the tool's transcript records it, itself shaped as a standing preference, and no question. That is the user's rule.
    spoken = users_sentence(Agents(store.root).transcript_of(who), words)
    if spoken:
        rid = store.learn(name, spoken["sentence"], {
            "type": "LEARNED", "words": spoken["sentence"], "when": now(), "scribe": who.name, "session": who.session,
            "prompt": {"sha256": spoken["sha256"], "at": spoken["at"], "offset": spoken["offset"]}}, agent=agent)
        _out(f"Learned {rid}: the user's own sentence, word for word, from their message in this session.")
        return 0
    # No console, and no agent's tool marks this shell (a script, a pipe, or a terminal window that is not a console):
    # whose words these are cannot be told. Filing them as an agent's proposal would label the user's own typing as an
    # AI's, and learning them would let an unmarked agent write rules; so, as with the user's other acts, refuse.
    if not any(os.environ.get(m) for m in AGENT_MARKERS):
        raise Refused("cannot teach here: not an interactive terminal, and no AI agent's tool marks this shell, so whose "
                      "words these are cannot be told. Teach at your own terminal (in Git Bash's window: winpty "
                      "semantext teach ...) or on the page")
    # In an agent's shell the words came through the agent: they are its proposal, never the user's words. The
    # proposal waits in the inbox and reaches the card only when the user adds it, as it is or in their own wording.
    title = f"Add a rule for {agent} in {store.title(name)}?" if agent else f"Add a rule to {store.title(name)}?"
    r = Inbox(store.root).ask(title, args.why or "An AI agent proposes this rule. It reaches the card only if you add it.",
                              rule=words, env=name, source=who.name, how=who.how, key=who.key,
                              session=who.session or "", agent=agent or "")
    _out(f"[#{r['id']}] Proposed, not learned. The rule waits in the user's inbox, and reaches the card only when they "
         f"add it.")
    return 0


def _uncovered(store: Store, name: str, rule_id: str) -> None:
    """After a rule goes off the card: the kept corrections that needed it, named, so the change is made knowingly."""
    for t in store.depends_on(name, rule_id):
        _out(f"  Uncovered: your correction of \"{_short(t['message'], 70)}\" ({t.get('case', 'a test')}) needed "
             f"{rule_id}; that misreading can come back.")


def _short(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[:n - 3] + "..."


def cmd_toggle(store: Store, args) -> int:
    _users_act("switch a rule")
    name = _env(store, args)
    on = store.toggle(name, args.rule_id)
    _out(f"{args.rule_id} is now {'on' if on else 'off'}.")
    if not on:
        _uncovered(store, name, args.rule_id)
    return 0


def cmd_cases(store: Store, args) -> int:
    name = _env(store, args)
    cases = store.cases(name)
    if args.export:
        fields = ("message", "context_before", "reply_tail", "correction", "source", "at", "supersedes", "grounded",
                  "rules", "categories", "expected_reading", "forbidden_reading")
        lines = [json.dumps({k: t[k] for k in fields if k in t}, ensure_ascii=False) for t in cases]
        Path(args.export).write_text("".join(x + "\n" for x in lines), encoding="utf-8")
        _out(f"Wrote {len(lines)} case{'s' if len(lines) != 1 else ''} to {args.export}, in the back-test's case form "
             f"(semantext backtest --cases {args.export}).")
        return 0
    if not cases:
        _out(f"No corrections are kept as tests in {store.title(name)} yet. Teach a rule with the message your AI got "
             f"wrong: semantext teach \"what you meant\" --misread \"the message\".")
        return 0
    covered = sum(t["covered"] for t in cases)
    _out(f"{store.title(name)}: {len(cases)} correction{'s' if len(cases) != 1 else ''} kept as tests, {covered} covered.")
    for t in cases:
        state = "covered" if t["covered"] else f"UNCOVERED: {', '.join(t['missing']) or 'it names no rule'}"
        _out(f"  {t.get('case', '?')}  \"{_short(t['message'], 60)}\"  ->  {', '.join(t.get('rules') or [])}  [{state}]")
    return 0


def cmd_pin(store: Store, args) -> int:
    _users_act("pin a rule")
    mode = store.pin(_env(store, args), args.rule_id)
    _out(f"{args.rule_id} is now {mode}.")
    return 0


def cmd_undo(store: Store, args) -> int:
    _users_act("undo a rule")
    name = _env(store, args)
    if args.last:
        restored = store.undo_last(name)
        _out(f"Undid the last change in {store.title_or_name(name)} (restored {restored}).")
        off, kept = store.last_undo.get("took_off"), store.last_undo.get("kept")
        if store.last_undo.get("problem"):   # after the restore, a step that failed (review of 1.2.2, S5)
            _out(f"But: {store.last_undo['problem']}.")
        if off is None:
            _out(f"The file it replaced could not be read, so what it held cannot be listed. It is kept, as it was, "
                 f"at {kept}: copy back any rule you still want.")
        else:
            if off:
                _out(f"This took off {len(off)} rule{'s' if len(off) != 1 else ''}: {', '.join(off)}.")
            _out(f"The version it replaced is kept at {kept}.")
        return 0
    if not args.rule_id:
        raise Refused("name a rule to undo, or use --last")
    store.undo(name, args.rule_id)
    _out(f"Undid {args.rule_id}: kept in the file, off the card.")
    _uncovered(store, name, args.rule_id)
    return 0


def cmd_read(store: Store, args) -> int:
    r = store.read(_env(store, args), " ".join(args.message), dry=True)
    for x in r["readings"]:
        _out(f"{x['label']}: {x['says']}  [{x['rule']}]")
    for d in r["decisions"]:
        _out(f"{d['ask']}  [{d['rule']}]")
    if r["touched"]:
        _out("Touches: " + ", ".join(r["touched"]))
    return 0


def cmd_where(store: Store, args) -> int:
    _out(str(store.path(_env(store, args))))
    return 0


# ---- what was heard ---------------------------------------------------------------------------------------------
def cmd_hear(store: Store, args) -> int:
    _users_act("keep a message as the user's")
    item = Heard(store.root).hear(_env(store, args), " ".join(args.text))
    _out(f"Heard #{item['id']} (kept on this machine).")
    return 0


def cmd_recall(store: Store, args) -> int:
    items = Heard(store.root).recall(_env(store, args), " ".join(args.query or []), args.n)
    if not items:
        _out("Nothing heard" + (" that matches." if args.query else " yet."))
    for i in items:
        _out(f"#{i['id']} {i['when']} ({i.get('source', 'you')}): {i['text']}")
    return 0


def cmd_forget(store: Store, args) -> int:
    _users_act("forget what was heard")
    if not args.all and not args.ids:
        raise Refused("name the items to forget, or use --all")
    gone = Heard(store.root).forget(_env(store, args), None if args.all else args.ids)
    _out(f"Forgot {gone} item{'s' if gone != 1 else ''}.")
    return 0


def cmd_propose(store: Store, args) -> int:
    name = _env(store, args)
    if args.accept:
        _users_act("accept a proposal")
    props = Heard(store.root).propose(name, store)
    if args.accept:
        chosen = {p["n"]: p for p in props}
        for n in args.accept:
            if n not in chosen:
                raise Refused(f"no proposal number {n}")
        for n in args.accept:
            rid = store.learn(name, chosen[n]["statement"])
            _out(f"Accepted {n} as {rid}.")
        return 0
    if not props:
        _out("No proposals yet: nothing heard sounds like a standing preference or a correction.")
        return 0
    for p in props:
        _out(f"{p['n']}. {p['statement']}  (from heard #{p['heard']})")
    _out("Accept with: semantext propose --accept N [N ...]")
    return 0


def cmd_mine(store: Store, args) -> int:
    name = _env(store, args)
    if not args.dry_run:
        _users_act("keep your past messages as yours")
    files = args.files or project_transcripts(args.project or os.getcwd())
    if not files:
        raise Refused("no transcripts found for this project: name the files, or use --project DIR")
    missing = [f for f in files if not Path(f).is_file()]
    if missing:
        raise Refused(f"not a file: {missing[0]}")
    r = mine_history(store, name, files, dry_run=args.dry_run)
    if args.json:
        _out(json.dumps(r))
        return 0
    verb = "Would keep" if args.dry_run else "Kept"
    _out(f"Read {r['files']} transcript{'s' if r['files'] != 1 else ''}: {r['prompts']} prompts.")
    _out(f"{verb} {r['kept']} of your own messages in {store.title(name)} ({r['by_record']} by the tool's record, "
         f"{r['by_text_only']} by their words alone).")
    _out(f"Left out: {r['not_users']} not yours (other agents' messages, notices), {r['summaries']} summaries, "
         f"{r['secrets']} that looked like a key or a password, {r['duplicates']} already kept, {r['empty']} empty.")
    _out(f"Found {r['corrections']} correction{'s' if r['corrections'] != 1 else ''} of a reply.")
    _out("Nothing became a rule. `semantext propose` lists the rules your words suggest; only you accept them.")
    return 0


def _pct(x: dict) -> str:
    return "n/a" if x["p"] is None else f"{x['p']:.0%} ({x['lo']:.0%} to {x['hi']:.0%})"


def _skill(s: dict) -> str:
    return "n/a" if s["value"] is None else f"{s['value']:+.2f} ({s['lo']:+.2f} to {s['hi']:+.2f})"


def cmd_backtest(store: Store, args) -> int:
    name = _env(store, args)
    if args.split and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.split):
        raise Refused("give --split as a date, YYYY-MM-DD")
    files = args.files or ([] if (args.cases or args.finder) and not args.project
                           else project_transcripts(args.project or os.getcwd()))
    if not files and not args.cases and not args.finder:
        raise Refused("no transcripts found for this project: name the files, or use --project DIR")
    for f in [*files, *(x for x in (args.cases, args.finder) if x)]:
        if not Path(f).is_file():
            raise Refused(f"not a file: {f}")
    if args.weighed:
        if (args.reader or args.cases or args.finder or args.split or args.show or args.judge or args.ablate
                or args.samples != 1 or args.clean_sample is not None):
            raise Refused("--weighed reads transcripts only, and cuts them by time itself: leave off --reader, --judge, "
                          "--ablate, --samples, --clean-sample, --cases, --finder, --split and --show")
        return _weighed_backtest(store, name, args, files)
    if args.reader:
        return _model_backtest(store, name, args, files)
    if args.judge or args.ablate or args.samples != 1 or args.clean_sample is not None:
        raise Refused("--judge, --ablate, --samples and --clean-sample go with --reader")
    r = run_backtest(store, name, files, cases=args.cases, finder=args.finder, split=args.split, show=args.show)
    if args.json:
        _out(json.dumps(r))
        return 0
    u = r["units"]
    if files:
        _out(f"Back-test of {store.title(name)} ({r['card_rules']} rules of its own) on {len(files)} transcript"
             f"{'s' if len(files) != 1 else ''}: {u['misread']} messages you then corrected, {u['clean']} you did "
             f"not, and {u['corrections']} corrections.")
        _out(f"  Touched, of the corrected: {_pct(r['coverage'])}. Of the rest: {_pct(r['false_touch'])}.")
        _out(f"  Skill (the difference): {_skill(r['skill'])}. Base rules alone: {_skill(r['nulls']['base']['skill'])}."
             f" {r['nulls']['matched']['rules']} rules drawn from the suggestion packs: "
             f"{_skill(r['nulls']['matched']['skill'])}.")
        if r["split"]["in_sample"]:
            _out("  In-sample: rules taught from these very corrections touch them. Use --split DATE for a fair score.")
        _out("  Touched means a rule bears on the message, not that an AI would have read it right.")
        for s in r.get("silent", []):
            _out(f"  - silent on: {s['message']!r}\n    you said: {s['correction']!r}")
    if "cases" in r:
        c = r["cases"]
        _out(f"Cases: {c['n']}. Touched: {_pct(c['touched'])}. The right rule, of the {c['with_rules']} that name "
             f"one: {_pct(c['hit'])}.")
    if "finder" in r:
        f = r["finder"]
        _out(f"Finding corrections, on {f['n']} labelled messages: precision {f['precision']}, recall {f['recall']}.")
    return 0


def _weighed_backtest(store: Store, name: str, args, files) -> int:
    from .weigh import measure
    r = measure(store, name, files, alpha=args.alpha)
    if args.json:
        _out(json.dumps(r))
        return 0
    c, p = r["card"], r["parts"]
    w, u, g = c["weighed"], c["unweighed"], c["precision_gain"]
    _out(f"Weighed back-test of {store.title(name)} ({c['rules']} rules of its own) on {len(files)} transcript"
         f"{'s' if len(files) != 1 else ''}. Weights from the earlier {p['fit_misread']} corrected and {p['fit_clean']} "
         f"other messages; the threshold from the next {p['calib_clean']}; scored on the last {p['test_misread']} "
         f"corrected and {p['test_clean']} others.")
    _out(f"  Weighed: touched {_pct(w['coverage'])} of the corrected, {_pct(w['false_touch'])} of the rest "
         f"(ceiling {r['alpha']:.0%}: {'holds' if w['ceiling']['holds'] else 'FAILS'}). Skill {_skill(w['skill'])}.")
    _out(f"  Unweighed, on the same messages: {_pct(u['coverage'])} and {_pct(u['false_touch'])}. "
         f"Skill {_skill(u['skill'])}.")
    _out(f"  Precision gain: {_skill(g)}. Verdict: {c['verdict']}.")
    if c["consistency"]["disagreements"]:
        _out(f"  On {c['consistency']['disagreements']} messages the weighed cues differ from the back-test's own "
             f"touch, so this result is not to be read.")
    return 0


def make_reader(spec: str, key_env: str | None):
    """ollama:MODEL, on this machine; or endpoint:URL#MODEL[@VARIABLE], an OpenAI-compatible endpoint, with the
    environment variable that holds its own key (otherwise --key-env's)."""
    kind, _, rest = spec.partition(":")
    if kind == "ollama" and rest:
        return OllamaReader(rest)
    if kind == "endpoint" and "#" in rest:
        url, _, model = rest.rpartition("#")
        model, _, own_key = model.partition("@")
        if url.startswith(("http://", "https://")) and model:
            return EndpointReader(url, model, key_env=own_key or key_env or "")
    raise Refused(f"not a reader: {spec!r}. Use ollama:MODEL or endpoint:URL#MODEL[@KEY_VARIABLE]")


def _host(url: str) -> str:
    return url.split("://", 1)[-1].split("/", 1)[0].lower()


def _model_backtest(store: Store, name: str, args, files) -> int:
    reader = make_reader(args.reader, args.key_env)
    judges = [make_reader(j, args.key_env) for j in args.judge]
    if judges and len(judges) != 2:
        raise Refused("name two judges, or none: only their agreement counts")
    if not files and not args.cases:
        raise Refused("a model reading needs transcripts or --cases")
    hosts_by_key: dict[str, set] = {}   # whoever named the variable, --key-env or the endpoint itself
    for x in (reader, *judges):
        if isinstance(x, EndpointReader) and x.key_env:
            hosts_by_key.setdefault(x.key_env, set()).add(_host(x.url))
    for var, hosts in sorted(hosts_by_key.items()):
        if len(hosts) > 1:   # one key goes to the one host it was issued for, never to another provider
            raise Refused(f"the key in {var} would go to {', '.join(sorted(hosts))}: one key goes to one host. Give "
                          f"each endpoint its own key variable: endpoint:URL#MODEL@VARIABLE")
    for x in (reader, *judges):
        if isinstance(x, EndpointReader) and not is_local(x.url):
            what = ("the card and the messages" if x is reader else
                    "the messages, their readings, and what each is judged against (for your transcripts, your "
                    "corrections and the end of each reply you corrected)")
            clear = (", in clear: readable on the network on its way" if x.url.lower().startswith("http://")
                     else "")
            _out(f"This sends {what} to {_host(x.url)}, outside this machine{clear} ({x.name}).")
        if isinstance(x, OllamaReader):
            x.resolve_version()                    # the model's digest on this machine, so a reading names its build
    r = model_backtest(store, name, reader, judges=judges, files=files, cases=args.cases, split=args.split,
                       samples=max(1, args.samples), ablate=args.ablate, clean_sample=args.clean_sample)
    if args.json:
        _out(json.dumps(r))
        return 0
    c = r["calls"]
    _out(f"Model reading by {r['reader']['name']} (version {r['reader']['version']}): {c['made']} calls, "
         f"{c['secret_skipped']} left out for a secret, {c['unparsed']} replies that were not a reading.")
    if "touched" in r:
        t = r["touched"]
        _out(f"  Touched, of the corrected: {_pct(t['coverage'])}. Of the rest: {_pct(t['false_touch'])}. Skill: "
             f"{_skill(t['skill'])}; the same model on a same-size drawn card: {_skill(t['nulls']['matched']['skill'])}.")
    if "reading" in r:
        g = r["reading"]
        _out(f"  The reading, card against blind, on {g['n']} judged cases: {g['b']} put right, {g['c']} put wrong "
             f"(McNemar p={g['mcnemar_p']}); difference {_skill(g['diff'])}; {g['disputed']} disputed.")
    if "cases" in r:
        _out(f"  The right rule, of the {r['cases']['with_rules']} cases that name one: {_pct(r['cases']['hit'])}.")
    if r.get("power", {}).get("corrected_n"):
        p = r["power"]
        gain = "no gain up to the largest" if p["min_net_gain_80"] is None else f"a net gain of {p['min_net_gain_80']}"
        _out(f"  Power: with {p['corrected_n']} pairs, the test finds {gain} four times in five.")
    _out(f"  Every number here is one model's: {r['reader']['name']}. A reading is a measurement, never a rule.")
    return 0


def cmd_config(store: Store, args) -> int:
    if args.key == "hear-prompts":
        if args.value is None:
            _out(f"hear-prompts: {'on' if store.state().get('hear_prompts') else 'off'}")
            return 0
        _users_act("change a setting")
        store.set_option("hear_prompts", args.value == "on")
        _out(f"hear-prompts: {args.value}")
    return 0


WORDS_SAID = {"own": "your words", "agent": "an agent's", "tool": "a tool's"}


def cmd_feed(store: Store, args) -> int:
    """What Semantext sent with each prompt, newest first: never what was said. On and off are the user's act."""
    if args.state:
        _users_act("change a setting")
        store.set_option("feed", args.state == "on")
        _out(f"feed: {args.state}" + ("" if args.state == "on" else
                                      " (nothing more is written; what is kept stays until it is cut back)"))
        return 0
    records = Feed(store.root).recent(max(1, min(200, args.n)))
    _out(f"feed: {'on' if store.state().get('feed', True) else 'off'}. What each prompt was sent, newest first "
         f"(never what was said): {len(records)} shown.")
    for r in records:
        layers = " + ".join(f"{x['layer']} {len(x['ids'])}" for x in r["layers"]) or "no rules"
        extra = "".join([f", {r['left_out']} left out by the size limit" if r["left_out"] else "",
                         f", answers #{', #'.join(map(str, r['answers']))}" if r["answers"] else "",
                         ", a file could not be read" if r["problem"] else ""])
        _out(f"{r['at'][11:19]}  {r['agent']} ({HOW_WORDS.get(r['how'], r['how'])}): {WORDS_SAID[r['words']]}, "
             f"{'full' if r['form'] == 'full' else 'short'} card in {r['environment']}, {layers}, {r['bytes']} bytes"
             f"{extra}")
    return 0


# ---- the page, the hook and Claude Code -------------------------------------------------------------------------
def cmd_serve(store: Store, args) -> int:
    from .server import serve
    return serve(store, args.host, args.port, args.open)


def cmd_mcp(store: Store, args) -> int:
    from .mcp import serve
    return serve(store)


def cmd_statusline(args) -> int:
    """One line for Claude Code's status bar, from your sources: what waits for your word, or how many of your
    decisions are in force. It reads whatever Claude Code sends on standard input and ignores it, writes nothing (it
    never opens the home, so it never creates one), and never fails: on any trouble it prints "Semantext: unavailable"
    and exits 0."""
    sys.dont_write_bytecode = True   # nothing is written, not even a cached copy of the code it loads
    line = "Semantext: unavailable"
    try:
        stdin = sys.stdin
        if stdin is not None and not stdin.isatty():
            import threading   # read in the background, so a sender that never closes cannot hold the line up

            def drain():
                try:
                    getattr(stdin, "buffer", stdin).read(1 << 20)
                except Exception:  # noqa: BLE001
                    pass
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            reader.join(0.5)
    except Exception:  # noqa: BLE001  what Claude Code sends is not used, so a fault reading it changes nothing
        pass
    try:
        from .sources import view
        line = view.status_line(Path(args.home).expanduser() if args.home else None, args.width)
    except Exception:  # noqa: BLE001  the last resort: still one line
        pass
    try:
        print(line)
    except Exception:  # noqa: BLE001
        pass
    return 0


def _target_file(args) -> Path:
    if args.file:
        return Path(args.file).expanduser()
    return agentfiles.default_file(args.tool)


def _not_an_agents_shell(what: str) -> None:
    """Disconnecting Semantext, or wiring a command of one's own into the hook, is the user's act: refused in a shell an
    AI tool marks as its agent's. The user's own scripts may still do it, so this asks for no console."""
    if any(os.environ.get(m) for m in AGENT_MARKERS):
        raise Refused(f"cannot {what} here: an agent's shell. The user runs this themselves")


def cmd_install(store: Store, args) -> int:
    if args.tool == "claude-code":
        path = Path(args.settings).expanduser() if args.settings else claude.default_settings()
        command = args.hook_command or claude.hook_command(store.root)
        if args.apply and command != claude.hook_command(store.root):
            _not_an_agents_shell("connect a hook command of your own")   # the standard hook stays an agent's to add
        if not args.apply:
            _out(f"This entry would be added to {path}:")
            _out(json.dumps(claude.snippet(command), indent=2))
            _out("Run again with --apply to add it (a backup of the file is saved first).")
            return 0
        changed, backup = claude.install(path, command)
        if not changed:
            _out(f"Already connected: {path} runs Semantext's hook.")
            return 0
        _out(f"Connected: {path} now runs `{command}` on every prompt.")
    else:
        path = _target_file(args)
        card = store.card(store.state()["active"])
        if not args.apply:
            _out(f"This block would be added to {path} (everything else in the file stays as it is):")
            _out(agentfiles.block(card))
            _out("Run again with --apply to add it (a backup of the file is saved first).")
            return 0
        changed, backup = agentfiles.install(path, card)
        agentfiles.remember(store, path)
        if not changed:
            _out(f"Already connected and current: {path}.")
            return 0
        _out(f"Connected: {path} tells your agent to run `semantext card`, with a copy of the card. "
             f"`semantext sync` refreshes the copy after you change your rules.")
    if backup:
        _out(f"Backup of the previous file: {backup}")
    return 0


def cmd_uninstall(store: Store, args) -> int:
    if args.apply:
        _not_an_agents_shell("disconnect Semantext")   # taking the card away from every agent is the user's act
    if args.tool == "claude-code":
        path = Path(args.settings).expanduser() if args.settings else claude.default_settings()
        if not args.apply:
            _out(f"Every Semantext hook entry would be removed from {path}. Run again with --apply to remove it.")
            return 0
        changed, backup = claude.uninstall(path)
        _out(f"Disconnected: removed from {path}." if changed else f"Nothing to remove: {path} has no Semantext hook.")
    else:
        path = _target_file(args)
        if not args.apply:
            _out(f"Semantext's block would be removed from {path}, and nothing else. Run again with --apply to remove it.")
            return 0
        changed, backup = agentfiles.uninstall(path)
        agentfiles.forget(store, path)
        _out(f"Disconnected: removed the block from {path}." if changed else f"Nothing to remove: {path} has no block.")
    if backup:
        _out(f"Backup of the previous file: {backup}")
    return 0


def cmd_sync(store: Store, args) -> int:
    results = agentfiles.sync(store)
    if not results:
        _out("Nothing to sync: no instructions file is connected (semantext install codex | freebuff | agents-md).")
    for path, what in results:
        _out(what if path in what else f"{what}: {path}")   # a problem's own words already name the file
    return 1 if any(what.startswith("PROBLEM") for _, what in results) else 0   # as doctor does


def cmd_export(store: Store, args) -> int:
    card = store.card(_env(store, args))
    if args.kind == "system-prompt":
        _out(card)
    else:
        if '"""' in card:
            raise Refused('a rule holds three double quotes ("""), which a Modelfile cannot carry; change that rule, '
                          "or use `semantext export system-prompt`")
        _out(agentfiles.modelfile(card, args.base or ""))
    return 0


def cmd_feature(store: Store, args) -> int:
    _users_act("switch a feature")
    name = _env(store, args)
    store.feature(name, args.name, args.state == "on", args.country or "")
    _out(f"{args.name}: {args.state} in {store.title(name)}")
    return 0


# ---- the inbox ----------------------------------------------------------------------------------------------------
def _show_request(r: dict, full: bool = True) -> None:
    how = HOW_WORDS.get(r.get("from_how") or "")
    sender = f"from {r['from']} ({how})" if how else f"from, as stated: {r['from']}"
    head = f"#{r['id']}  {r['title']}   ({sender}; asked {age(r['at'])} ago)"
    if r["status"] != "open":
        head += f"  [{r['status']}]"
    _out(head)
    if not full:
        return
    _out(f"    why: {r['why']}")
    if r["kind"] == "decision":
        _out(f"    {r['question']}")
        for i, o in enumerate(r["options"], 1):
            _out(f"      {i}. {o}" + ("  (recommended)" if r.get("recommend") == i else ""))
    elif r["kind"] == "rule":
        target = f"{r['agent']} only, in {r['env']}" if r.get("agent") else r["env"]
        _out(f"    the proposed rule, for {target}: {r['statement']}")
        _out("    It reaches the card only if you add it. Answer add, or add followed by your own wording (which "
             "replaces the agent's), or no.")
    else:
        _out(f"    command: {r['command']}" + (f"   (in {r['cwd']})" if r.get("cwd") else ""))
        _out(f"    what it does: {r['does']}")
        _out(f"    to undo it: {r['undo']}")
        if r.get("flags"):
            _out(f"    second look: {'; '.join(r['flags'])} (no flag does not mean safe)")
        _out("    Semantext never runs it. Run it yourself if you agree, then answer Done or Won't do.")
    if r.get("answer"):
        via = r["answer"].get("via")
        _out(f"    answered: {describe_answer(r)}" + (f" (via {via})" if via in ("terminal", "page", "chat") else ""))
    if r.get("closed"):
        by = r["closed"].get("by")
        _out(f"    withdrawn{f' by {by}' if by else ''}: {r['closed'].get('how') or 'no reason given'}")


def _who(store: Store) -> Identity:
    """The agent this shell belongs to, worked out the way the hook works it out (see agents.py)."""
    return Agents(store.root).identify()


def _as(store: Store, stated: str | None) -> Identity:
    """Who this shell acts as: itself, or, with --from, the name it states. A stated name is a claim, with a claim's
    key, so it reaches only requests filed under that same claim, never those of an agent bound or seen by that name."""
    who = _who(store)
    if not stated:
        return who
    if key_shaped(stated):
        raise Refused("that name looks like it holds a key, a token or a password; never put one in a name")
    name = clean(stated)
    return Identity(name, "claimed", who.tool, who.project, who.session, key=f"claim:{name}", root=who.root)


def cmd_ask(store: Store, args) -> int:
    who = _as(store, args.source)
    source = args.source if args.source else who.name
    r = Inbox(store.root).ask(args.title, args.why, args.question or "", args.option or [], args.recommend or 0,
                              args.run or "", args.does or "", args.undo or "", args.cwd or "", source, how=who.how,
                              key=who.key, session=who.session or "")
    inbox = Inbox(store.root)
    _out(f"[#{r['id']}] {r['title']}")
    _out("Filed in the user's inbox. Keep working on what does not need it; the answer arrives with a later prompt, "
         f"or check with `semantext answers`. They can answer on their page, or by sending you #{r['id']} and their "
         "choice as a message of its own." + asked_before(inbox, r))
    return 0


def cmd_decisions(store: Store, args) -> int:
    found = Inbox(store.root).search(" ".join(args.words or []), limit=args.limit)
    if not found:
        _out("Nothing on record matches." if args.words else "Nothing has been decided yet.")
        return 0
    for r in found:
        _out(register_line(r))
    return 0


def cmd_inbox(store: Store, args) -> int:
    inbox = Inbox(store.root)
    items = sorted(inbox.requests().values(), key=lambda r: r["id"])
    shown = items if args.all else [r for r in items if r["status"] == "open"]
    if not shown:
        _out("Nothing is waiting for you." if not args.all else "The inbox is empty.")
        return 0
    for r in shown:
        _show_request(r)
        _out("")
    if not args.all:
        _out("Answer with: semantext answer ID CHOICE [your words]")
    return 0


def cmd_answer(store: Store, args) -> int:
    why_not = human_terminal()
    if why_not:
        raise Refused(f"cannot answer here: {why_not}. Answer from your own terminal, or from the page")
    inbox = Inbox(store.root)
    store.check_adoptable(inbox.get(args.id), args.choice)
    r = inbox.answer(args.id, args.choice, " ".join(args.words or []), via="terminal")
    rid = store.adopt(r)
    _out(f"Answered {describe_answer(r)}. Your AI sees it with its next prompt.")
    if rid:
        _out(f"Added {rid} to {store.title(r['env'])}: it is on the card from the next prompt.")
    return 0


def cmd_answers(store: Store, args) -> int:
    # Only this asker's answers, and only those are marked read: another agent's answer must still reach it.
    inbox = Inbox(store.root)
    who = _as(store, args.source)
    unread = inbox.unread_answers(who)
    if not unread:
        waiting = inbox.open_requests(who)
        _out("No new answers." + (" Still waiting: " + ", ".join(f"#{r['id']}" for r in waiting) if waiting else ""))
        return 0
    for r in unread:
        _out(describe_answer(r))
    inbox.mark_read([r["id"] for r in unread], by=who.name)
    _out("Marked as read.")
    return 0


def cmd_close(store: Store, args) -> int:
    # The asker withdraws its own request; the user, at their own terminal, may withdraw any.
    inbox = Inbox(store.root)
    r = inbox.get(args.id)
    who = _as(store, args.source)
    # A tool's own marker or a claimed name makes this shell an agent's. A bound folder alone does not: the user works
    # in those folders too, and withdraws from a console.
    if who.tool or who.how == "claimed":
        if not mine(r, who):
            raise Refused(f"#{r['id']} was asked by {r['from']}, not by this agent; only its asker, or the user at "
                          f"their own terminal, can withdraw it")
        by = who.name
    else:
        why_not = human_terminal()
        if why_not:
            raise Refused(f"cannot withdraw it here: {why_not}. Only its asker, or the user at their own terminal, can "
                          f"withdraw it")
        by = "the user"
    r = inbox.close(args.id, " ".join(args.how or []), by=by)
    _out(f"Withdrew #{r['id']} {r['title']}.")
    return 0


def cmd_agents(store: Store, args) -> int:
    rows, me = Agents(store.root).overview(), _who(store)
    if not rows:
        _out("No agents yet. An agent appears here once it uses Semantext: its hook, or `semantext ask`.")
    for a in rows:
        label = f"  ({a['label']})" if a["label"] else ""
        _out(f"{'*' if a['name'] == me.name else ' '} {a['name']}{label}")
        for f in a["folders"]:
            _out(f"    bound to {f}")
        for s in a["sessions"][:3]:
            _out(f"    session {s['id'][:8]}: {s.get('prompts') or 0} prompts, last {since(s.get('last') or '')}")
        if len(a["sessions"]) > 3:
            _out(f"    and {len(a['sessions']) - 3} older sessions")
    _out(f"This shell is {me.name} ({me.how}).")
    return 0


def cmd_agent(store: Store, args) -> int:
    agents = Agents(store.root)
    if args.action == "whoami":
        who = agents.identify()
        _out(f"{who.name}  (found by: {who.how}; tool: {who.tool or 'none seen'}; project: {who.project or 'none'})")
        return 0
    # Which rules an agent gets is the user's to set, like answering: never from an agent's own shell.
    why_not = human_terminal()
    if why_not:
        raise Refused(f"cannot change agents here: {why_not}")
    if args.action == "bind":
        if not args.name:
            raise Refused("name the agent, for example: semantext agent bind reviewer --folder C:\\work\\api")
        path = agents.bind(args.name, args.folder or os.getcwd())
        _out(f"Every agent working in {path} is now {agents.bound(path)}.")
    elif args.action == "unbind":
        folder = args.folder or os.getcwd()
        _out("Unbound." if agents.unbind(folder) else f"No binding for {folder}.")
    elif args.action == "name":
        agents.rename(args.name or "", " ".join(args.label or []))
        _out("Named." if args.label else "Name removed.")
    return 0


def cmd_plugins(store: Store, args) -> int:
    # Imported here, not at the top: `semantext hook` runs through this module, and the hook loads no plug-in, nor the
    # registry (the ecosystem review, section 1; tests/test_registry.py pins the hook's imports).
    from . import plugincmd
    return plugincmd.run(store.root, args.action, args.name, _out)


def cmd_doctor(store: Store, args) -> int:
    s = store.state()
    name = s["active"]
    problems = 0
    broken = []   # each file that cannot be read is named, and the checks go on
    for n in store.names():
        try:
            store.load(n)
        except (Refused, OSError) as e:
            broken.append(str(e))
    card = store.served_card(name)
    size = len(card.encode("utf-8"))
    settings = Path(args.settings).expanduser() if getattr(args, "settings", None) else claude.default_settings()
    try:
        connected = claude.is_installed(jsonread.loads(settings.read_text(encoding="utf-8-sig"))) if settings.exists() else False
        claude_row = f"connected ({settings})" if connected else "not connected (semantext install claude-code)"
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, AttributeError) as e:
        claude_row, problems = f"PROBLEM: cannot read {settings} ({type(e).__name__})", problems + 1
    inbox = Inbox(store.root)
    rows = [
        ("Semantext", __version__),
        ("PyYAML", yaml.__version__),
        ("home", str(store.root)),
        ("environments", ", ".join(n for n in store.names() if n != "base")),
        ("active", f"{_title_or_name(store, name)} ({name})"),
        ("card", f"{card.count(chr(10) + '- ')} rules, {size} bytes "
                 f"({'fits' if size <= LIMIT_BYTES else 'over'} the {LIMIT_BYTES}-byte hook limit)"),
        ("on PATH", "yes" if shutil.which("semantext") else "no (the hook can use python -m semantext)"),
        ("Claude Code", claude_row),
    ]
    for f in s.get("agent_files", []):
        ok = agentfiles.has_block(Path(f))
        problems += not ok
        rows.append(("agent file", f"{'connected' if ok else 'PROBLEM: block missing or broken'} ({f})"))
    rows += [("inbox", f"{len(inbox.open_requests())} waiting for you, {len(inbox.unread_answers())} answers unread"),
             ("hear-prompts", "on" if s.get("hear_prompts") else "off"),
             ("feed", f"{'on' if s.get('feed', True) else 'off'} ({len(Feed(store.root).recent(200))} deliveries kept; "
                      f"what was sent, never what was said)")]
    found = ([f"PROBLEM: {b}" for b in broken]
             + [f"PROBLEM: {store.profiles_dir / x} is not an environment Semantext can use: it is left alone "
                f"(rename it with lowercase letters, digits and hyphens, or move it out)" for x in store.strays()]
             + ([f"PROBLEM: {store.state_problem}"] if store.state_problem else []))
    rows += [("file", f) for f in found]
    problems += len(found)
    for k, v in rows:
        _out(f"{k:<13} {v}")
    return 1 if problems else 0


def _title_or_name(store: Store, name: str) -> str:
    try:
        return store.title(name)
    except (Refused, OSError):
        return name


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="semantext",
        description="Keep your standing rules for how an AI assistant reads you, and hand them to it with every "
                    "prompt.")
    p.add_argument("--version", action="version", version=f"semantext {__version__}")
    p.add_argument("--home", help="the folder holding your rules (default: ~/.semantext, or $SEMANTEXT_HOME)")
    sub = p.add_subparsers(dest="command", metavar="<command>")

    def add(name, fn, help_text, env=False, aliases=()):
        sp = sub.add_parser(name, aliases=list(aliases), help=help_text, description=help_text)
        sp.set_defaults(fn=fn)
        if env:
            sp.add_argument("--env", help="the environment (default: the active one)")
        return sp

    add("init", cmd_init, "create your home with the starting environments")
    sp = add("card", cmd_card, "print the card your AI receives", env=True)
    sp.add_argument("--agent", help="the card that agent receives, with its own rules (as `semantext agents` names it)")
    sp = add("env", cmd_env, "list, switch or make environments (profiles); add suggested rules (`ideas` lists the "
                             "packs)", aliases=("profile",))
    sp.add_argument("action", nargs="?", choices=("list", "use", "new", "add", "ideas"), default="list")
    sp.add_argument("name_or_title", nargs="*", metavar="ARG",
                    help="use NAME or TITLE, new TITLE..., or add ID [ID ...]")
    sp.add_argument("--env", help="for add: the environment, by name or title (default: the active one)")
    sp.add_argument("--none", action="store_true", help="for new: start without suggested rules")
    sp.add_argument("--pick", nargs="+", metavar="ID", help="for new: start with these suggestions, from any pack")
    sp = add("rules", cmd_rules, "list an environment's rules", env=True)
    sp.add_argument("--all", action="store_true", help="include undone (archived) rules")
    sp.add_argument("--base", action="store_true", help="show the shared base rules too")
    sp.add_argument("--agent", help="that agent's own rules in the environment, instead of the shared ones")
    sp = add("teach", cmd_teach, "keep a correction as a rule, with your exact words (from an agent's shell: propose "
                                 "it, for the user to add)", env=True)
    sp.add_argument("words", nargs="+", help="your correction, in your own words")
    sp.add_argument("--why", help="for an agent: why it proposes the rule, shown to the user")
    sp.add_argument("--agent", help="a rule for that agent only, in its own layer of the environment")
    sp.add_argument("--misread", metavar="MESSAGE", help="the message your AI got wrong, kept as the rule's test")
    sp = add("cases", cmd_cases, "your corrections kept as tests, and whether each is still covered by a rule that is on",
             env=True)
    sp.add_argument("--export", metavar="FILE", help="write them as a JSONL of cases for `semantext backtest --cases`")
    rule_help = "the rule's id, as `semantext rules` shows it"
    sp = add("toggle", cmd_toggle, "switch a rule on or off", env=True)
    sp.add_argument("rule_id", help=rule_help)
    sp = add("pin", cmd_pin, "switch a rule between stationary and adaptive", env=True)
    sp.add_argument("rule_id", help=rule_help)
    sp = add("undo", cmd_undo, "undo a rule (kept in the file, off the card), or the last change", env=True)
    sp.add_argument("rule_id", nargs="?", help=rule_help)
    sp.add_argument("--last", action="store_true", help="undo the last change to the environment")
    sp = add("read", cmd_read, "show how a message is read (nothing is saved)", env=True)
    sp.add_argument("message", nargs="+", help="the message to read")
    add("where", cmd_where, "print the path of an environment's rule file", env=True)
    sp = add("hear", cmd_hear, "keep a message you sent, on this machine", env=True)
    sp.add_argument("text", nargs="+", help="the message to keep")
    sp = add("recall", cmd_recall, "show what was heard, newest first", env=True)
    sp.add_argument("query", nargs="*", help="words to look for (an item must hold them all)")
    sp.add_argument("-n", type=int, default=20, help="how many (default 20)")
    sp = add("forget", cmd_forget, "forget heard items", env=True)
    sp.add_argument("ids", nargs="*", type=int, help="the numbers `semantext recall` shows")
    sp.add_argument("--all", action="store_true", help="forget everything heard in the environment")
    sp = add("propose", cmd_propose, "propose rules from what was heard; accept the ones you want", env=True)
    sp.add_argument("--accept", nargs="+", type=int, metavar="N", help="the numbers of the proposals to accept")
    sp = add("mine", cmd_mine, "keep your own past messages from your AI tool's transcripts as heard (on this machine; "
                               "rules come only from `propose`)", env=True)
    sp.add_argument("files", nargs="*", metavar="FILE", help="Claude Code transcripts (.jsonl); default: the project's")
    sp.add_argument("--project", help="the project folder whose transcripts to read (default: this folder)")
    sp.add_argument("--dry-run", action="store_true", help="count only: keep nothing")
    sp.add_argument("--json", action="store_true", help="the counts as JSON")
    sp = add("backtest", cmd_backtest, "score the card against the misreadings in your transcripts (on this machine; "
                                       "nothing is written)", env=True)
    sp.add_argument("files", nargs="*", metavar="FILE", help="Claude Code transcripts (.jsonl); default: the project's")
    sp.add_argument("--project", help="the project folder whose transcripts to read (default: this folder)")
    sp.add_argument("--split", metavar="YYYY-MM-DD",
                    help="leave off rules learned on or after this date, and score only messages from it on")
    sp.add_argument("--cases", metavar="FILE", help="a JSONL of curated cases (see docs/backtest.md)")
    sp.add_argument("--finder", metavar="FILE",
                    help='a JSONL of {"text": ..., "correction": true|false}: how well corrections are found')
    sp.add_argument("--show", action="store_true", help="list the misread messages the card is silent on")
    sp.add_argument("--json", action="store_true", help="the report as JSON")
    sp.add_argument("--reader", metavar="SPEC",
                    help="score a model's reading instead: ollama:MODEL (on this machine) or endpoint:URL#MODEL "
                         "(an OpenAI-compatible endpoint; off this machine unless the URL is local)")
    sp.add_argument("--judge", action="append", metavar="SPEC", default=[],
                    help="with --reader: a judge of the readings, given twice, each of another model lineage than the "
                         "reader")
    sp.add_argument("--key-env", metavar="NAME", help="the environment variable holding an endpoint's key "
                                                       "(the key itself is never stored)")
    sp.add_argument("--samples", type=int, default=1, help="with --reader: readings per case, for their agreement")
    sp.add_argument("--ablate", action="store_true", help="with --reader and --cases: drop each needed rule in turn")
    sp.add_argument("--clean-sample", type=int, metavar="N",
                    help="with --reader on transcripts: read every misread message and a fixed sample of N clean ones")
    sp.add_argument("--weighed", action="store_true",
                    help="score a weighed touch instead: each cue weighed by its evidence on your earlier messages, "
                         "with the threshold set so that at most --alpha of your ordinary messages are touched")
    sp.add_argument("--alpha", type=float, default=0.10,
                    help="with --weighed: the share of ordinary messages that may be touched (default 0.10)")
    sp = add("config", cmd_config, "show or change a setting")
    sp.add_argument("key", choices=("hear-prompts",),
                    help="hear-prompts: keep each prompt you send in your heard log, on this machine (off by default)")
    sp.add_argument("value", nargs="?", choices=("on", "off"))
    sp = add("feed", cmd_feed, "what each prompt was sent, newest first (never what was said); on or off")
    sp.add_argument("state", nargs="?", choices=("on", "off"), help="switch the feed on or off (on by default)")
    sp.add_argument("-n", type=int, default=20, help="how many to show (default 20)")
    sp = add("serve", cmd_serve, "open the page on this machine (http://127.0.0.1:8765)")
    sp.add_argument("--host", default="127.0.0.1", help="127.0.0.1 or localhost; any other host is refused")
    sp.add_argument("--port", type=int, default=8765, help="the port (default 8765)")
    sp.add_argument("--open", action="store_true", help="open it in your browser")
    add("hook", None, "the Claude Code hook: reads the prompt event on stdin and prints the card (Claude Code runs it "
                      "for you)")
    add("mcp", cmd_mcp, "Semantext for any AI tool that speaks MCP: the card and the inbox, over stdin and stdout (the "
                        "tool runs it for you)")
    sp = add("statusline", None, "one line for Claude Code's status bar: what waits for your word, from your sources "
                                 "(it writes nothing, and on any trouble prints \"Semantext: unavailable\")")
    sp.add_argument("--width", default="80", help="the most characters the line may take (default 80)")
    tools = ("claude-code", "codex", "freebuff", "agents-md")
    for verb, fn, text in (("install", cmd_install, "connect an AI tool (prints the change; --apply makes it)"),
                           ("uninstall", cmd_uninstall, "disconnect an AI tool (--apply makes the change)")):
        sp = add(verb, fn, text)
        sp.add_argument("tool", choices=tools,
                        help="claude-code: a hook in its settings; codex: a block in ~/.codex/AGENTS.md; freebuff: a "
                             "block in the project's knowledge.md; agents-md: a block in the file you name")
        sp.add_argument("--apply", action="store_true", help="make the change (a backup is saved first)")
        sp.add_argument("--settings", help="claude-code: the settings file (default: ~/.claude/settings.json)")
        sp.add_argument("--file", help="codex, freebuff, agents-md: the instructions file (needed for agents-md)")
        if verb == "install":
            # dest must not be "command": that name holds the sub-command itself, and a default of None would hide it.
            sp.add_argument("--command", dest="hook_command",
                            help="claude-code: the command the hook runs (default: chosen for this machine)")
    add("sync", cmd_sync, "refresh the card's copy in every connected instructions file")
    sp = add("export", cmd_export, "print the card for a local model: as a system prompt, or an Ollama Modelfile",
             env=True)
    sp.add_argument("kind", choices=("system-prompt", "modelfile"))
    sp.add_argument("--base", help="modelfile: the model to build on, for example llama3.2")
    sp = add("feature", cmd_feature, "switch a feature rule on or off (inbox, tone, jokes, news)", env=True)
    sp.add_argument("name", choices=tuple(FEATURES))
    sp.add_argument("state", choices=("on", "off"))
    sp.add_argument("--country", help="news: the country to focus on")
    # The inbox: an agent asks, withdraws and reads answers; only the user answers.
    sp = add("ask", cmd_ask, "file a request in the user's inbox (for an AI: a decision, or a command for them to run)")
    sp.add_argument("--title", required=True, help="a short title")
    sp.add_argument("--why", required=True, help="why it needs the user")
    sp.add_argument("--question", help="a decision: the question")
    sp.add_argument("--option", action="append", help="a decision: an option (repeat it, up to 9)")
    sp.add_argument("--recommend", type=int, help="a decision: the number of the option you recommend")
    sp.add_argument("--command", dest="run", help="a command for the user to run themselves (never run for them)")
    sp.add_argument("--does", help="a command: what it does")
    sp.add_argument("--undo", help="a command: how to undo it, or 'cannot be undone'")
    sp.add_argument("--cwd", help="a command: the folder to run it in")
    sp.add_argument("--from", dest="source", help="who is asking, as stated (default: $SEMANTEXT_AGENT, or 'ai')")
    sp = add("inbox", cmd_inbox, "show the requests waiting for your answer")
    sp.add_argument("--all", action="store_true", help="include answered and withdrawn requests")
    sp = add("answer", cmd_answer, "answer a request (you, from your own terminal; never an agent)")
    sp.add_argument("id", type=int, help="the request's number, as `semantext inbox` shows it")
    sp.add_argument("choice", help="an option's number; for a command, done or wont (an apostrophe needs quotes in "
                                   "a shell); for a proposed rule, add or no")
    sp.add_argument("words", nargs="*", help="your answer in your own words, kept exactly")
    sp = add("decisions", cmd_decisions, "what the user has decided: every answered request, newest first (for an AI: "
                                         "look here before you ask)")
    sp.add_argument("words", nargs="*", help="only those holding all these words")
    sp.add_argument("--limit", type=int, default=20, help="at most this many (default 20)")
    sp = add("answers", cmd_answers, "for an AI: read the user's new answers to you, and mark them read")
    sp.add_argument("--from", dest="source", help="the asker whose answers these are (default: $SEMANTEXT_AGENT, or "
                                                  "'ai')")
    sp = add("close", cmd_close, "withdraw a request that is no longer needed (its asker, or you from your own "
                                 "terminal; it never answers)")
    sp.add_argument("id", type=int, help="the request's number")
    sp.add_argument("--how", nargs="+", help="why it is withdrawn, for example: superseded by #14")
    sp.add_argument("--from", dest="source", help="who is withdrawing it: the asker, as stated (default: "
                                                  "$SEMANTEXT_AGENT, or you at your own terminal)")
    add("agents", cmd_agents, "list the AI agents Semantext has seen or you have named, with their sessions")
    sp = add("agent", cmd_agent, "who this shell's agent is; bind a folder to an agent; give an agent a display name")
    sp.add_argument("action", choices=("whoami", "bind", "unbind", "name"))
    sp.add_argument("name", nargs="?", help="bind: the agent's name; name: the agent to label")
    sp.add_argument("label", nargs="*", help="name: the display name (none removes it)")
    sp.add_argument("--folder", help="bind, unbind: the folder (default: this one)")
    sp = add("plugins", cmd_plugins, "list plug-ins, where each came from and whether it is on; turn one on (you, at "
                                     "your own console, typing its name) or off")
    sp.add_argument("action", nargs="?", choices=("list", "enable", "disable", "check"), default="list",
                    help="check: the conformance kits (not built yet)")
    sp.add_argument("name", nargs="?", help="enable, disable: the plug-in, as <kind>.<name>")
    sp = add("doctor", cmd_doctor, "check the setup (exits 1 if something is broken)")
    sp.add_argument("--settings", help="the Claude Code settings file to check (default: ~/.claude/settings.json)")
    from .work.cli import register as add_work   # here: the work package is only loaded by the command line
    add_work(add)
    return p


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "hook":
        if args.home:
            import os
            os.environ["SEMANTEXT_HOME"] = args.home
        return hook_main()
    if args.command == "statusline":   # before the home is opened: the status line writes nothing, not even a new home
        return cmd_statusline(args)
    if not args.command:
        parser.print_help()
        return 0
    try:
        store = Store.open(Path(args.home).expanduser() if args.home else None)
        return args.fn(store, args)
    except (Refused, OSError, ValueError) as e:
        # A refusal, or a file that could not be read or written (a home that is a file, a damaged state.json):
        # one line, never a traceback.
        print(f"semantext: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001  the last resort: still one line, with what failed, never a traceback
        print(f"semantext: an unexpected {type(e).__name__}: {e}. `semantext doctor` checks the files; "
              f"please report it if it persists", file=sys.stderr)
        return 1
