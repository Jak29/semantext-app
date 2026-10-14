"""Mining: your own past words, from your AI tool's transcripts on this machine.

`semantext mine` reads Claude Code's transcripts (the current project's, by default) and keeps the user's own prompts
as heard items, so rules can be proposed from how the user actually talks. A prompt is kept only when its text reads
as the user's and the tool's own record of where it came from does not say otherwise: the hook's rule, under which the
record can only move a prompt away from the user. Compaction summaries, notices, tool results and other agents'
messages are never kept, and nor is anything that looks like a key, a token or a password. Nothing is kept twice.

Nothing leaves this machine, and nothing becomes a rule: `semantext propose` lists the rule-shaped sentences, and only
the user accepts them.

The same reading finds corrections: a prompt of the user's that opens by correcting the reply before it ("no, I
meant ...", "that's not what I asked"). Each comes with the prompt it corrected and the end of the reply between them:
the unit `semantext backtest` scores. The openings are a list, and a list misses some: a missed correction costs a
back-test row, never a rule, and `semantext backtest --finder` measures how many it misses.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .agents import _user_home, project_root
from .heard import Heard
from .inbox import SECRET
from .sender import USER, _record_origin, record_text, sender_of
from .store import Store

REPLY_TAIL = 400
# How a correction of the reply before it opens. Left out on purpose, for their precision: "wait", "actually" and
# "hold on" open as many new thoughts as corrections. "no" is a correction, "no problem" and "no rush" are not.
CORRECTION = re.compile(
    r"^\W*(?:no\b(?!\s+(?:problem|worries|rush|need|thanks?|idea)\b)|nope\b|nah\b|not quite\b|not what i\b"
    r"|that'?s not\b|that is not\b|that isn'?t\b|that'?s wrong\b|wrong\b|what i meant\b"
    r"|(?:again,?\s+)?(?:as |like )?i (?:already )?(?:said|asked|meant|mean)\b"
    r"|i didn'?t (?:ask|say|mean|want)\b|i'?m not (?:asking|saying|talking)\b|i don'?t think you\b"
    r"|you (?:misread|misunderstood|missed|got it wrong|were supposed to|should have)\b|you'?re (?:not\b|mis|confus|ignor)"
    r"|this (?:was|is) my original\b|read it (?:again|first)\b|stop\b|why (?:did|are|would|have) you\b)", re.I)
# ... or one that says, early on, what was meant: "don't stop is what I mean".
SAID_EARLY = re.compile(r"\b(?:is|was) what i (?:mean|meant|said|asked|wanted)\b", re.I)


def is_correction(text: str) -> bool:
    text = text or ""
    return bool(CORRECTION.match(text) or SAID_EARLY.search(text[:120]))


def encode_project(path) -> str:
    """The folder name Claude Code gives a project's transcripts: every character but a letter or a digit is a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def project_transcripts(cwd) -> list[Path]:
    """Claude Code's transcripts for the project a folder belongs to: those started in the folder itself, and those
    started at its project's root."""
    home = _user_home()
    if home is None:
        return []
    base = home / ".claude" / "projects"
    here = Path(cwd).resolve()
    out: list[Path] = []
    for folder in dict.fromkeys(encode_project(p) for p in (here, project_root(here)) if p is not None):
        d = base / folder
        if d.is_dir():
            out += sorted(p for p in d.glob("*.jsonl") if p.is_file())
    return out


def turns(path: Path):
    """A transcript's prompts and replies, in order: ("prompt", record) for each prompt, with its text, time, id and
    where the record says it came from (or "summary" for a compaction summary, never the user's words), and
    ("reply", text) for each piece of the AI's own text."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict) or r.get("isSidechain"):
                continue                         # a subagent's own conversation, not the user's
            if r.get("type") == "assistant":
                m = r.get("message") if isinstance(r.get("message"), dict) else {}
                c = m.get("content")
                text = ("".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
                        if isinstance(c, list) else c if isinstance(c, str) else "")
                if text.strip():
                    yield "reply", text
                continue
            queued = isinstance(r.get("attachment"), dict) and r["attachment"].get("type") == "queued_command"
            if r.get("type") != "user" and not queued:
                continue
            if r.get("type") == "user" and (r.get("isCompactSummary") or r.get("isVisibleInTranscriptOnly")):
                yield "prompt", {"text": record_text(r), "origin": "summary", "at": r.get("timestamp"),
                                 "record": r.get("uuid")}
                continue
            text, origin = _record_origin(r)
            if r.get("type") == "user" and text is None and origin is None:
                text = record_text(r)            # a record that says nothing of itself: the text decides
                if text is not None and r.get("isMeta"):
                    origin = "meta"              # added by the tool, never typed
            if text is None:
                continue
            yield "prompt", {"text": text, "origin": origin, "at": r.get("timestamp"), "record": r.get("uuid")}


def units(path: Path) -> list[dict]:
    """The user's own prompts in one transcript, each marked misread when the user's next prompt after a reply opens
    as a correction of it, with that correction and the end of the reply between them."""
    out: list[dict] = []
    last, reply = None, ""
    for kind, x in turns(path):
        if kind == "reply":
            reply += ("\n" if reply else "") + x
            continue
        own = x["origin"] in (None, USER) and sender_of(x["text"]) == USER and x["text"].strip()
        if not own:
            continue                             # other words between two of the user's do not break the pair
        unit = {"text": x["text"], "at": x["at"], "record": x["record"], "misread": False, "corrects": False,
                "before": reply[-REPLY_TAIL:] or None}           # the reply this message answers, if any
        if last is not None and reply and is_correction(x["text"]):
            last.update(misread=True, correction=x["text"], reply_tail=reply[-REPLY_TAIL:])
            unit["corrects"] = True              # itself a correction: neither misread nor clean, unless corrected
        out.append(unit)
        last, reply = unit, ""
    return out


def mine(store: Store, name: str, files, dry_run: bool = False) -> dict:
    """Keep the user's own prompts from these transcripts as heard items in this environment, and count everything:
    what was kept, and why the rest was not."""
    report = {"env": name, "dry_run": dry_run, "files": 0, "prompts": 0, "kept": 0, "by_record": 0, "by_text_only": 0,
              "not_users": 0, "summaries": 0, "secrets": 0, "duplicates": 0, "empty": 0, "corrections": 0}
    heard = Heard(store.root)
    have = {(i.get("from") or {}).get("key") for i in heard.items(name)} - {None}
    keep: list[dict] = []
    for path in map(Path, files):
        report["files"] += 1
        seen_text: set[str] = set()
        for kind, x in turns(path):
            if kind != "prompt":
                continue
            report["prompts"] += 1
            text = " ".join((x["text"] or "").split())
            if x["origin"] == "summary":
                report["summaries"] += 1
                continue
            if x["origin"] not in (None, USER) or sender_of(x["text"]) != USER:
                report["not_users"] += 1
                continue
            if not text:
                report["empty"] += 1
                continue
            if SECRET.search(text):
                report["secrets"] += 1            # never stored, never shown
                continue
            key = f"{path.name}#{x['record'] or text[:80]}"
            if key in have or text in seen_text:
                report["duplicates"] += 1
                continue
            seen_text.add(text)
            have.add(key)
            report["kept"] += 1
            report["by_record" if x["origin"] == USER else "by_text_only"] += 1
            keep.append({"text": text, "when": x["at"], "from": {"key": key, "file": path.name, "record": x["record"]}})
        report["corrections"] += sum(1 for u in units(path) if u["misread"])
    if keep and not dry_run:
        heard.keep(name, keep, source="transcript")
    return report
