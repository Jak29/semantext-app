"""Your inbox: where an AI asks for your word instead of acting, and keeps working until you answer.

A request is a decision (a question with options, one of them perhaps recommended) or a command (what to run, what it
does and how to undo it). Only you answer: from the page, from your own terminal, or in chat, by sending its number and
your choice to any of your AIs as a message of its own ("#12 2"; see CHAT_ANSWER). An agent can file a request and
withdraw it, never answer it. Your choice and your own words are kept, and the next prompt your AI sends carries the answer, through the hook,
until the asking agent marks it read with `semantext answers`.

Semantext never runs a command for you. A command request shows the command, what it does and how to undo it, with a
second-look flag where it may delete, use the network or ask for admin rights; you run it yourself, then answer Done or
Won't do.

The file is append-only, <home>/inbox.jsonl: one event per line (request, answer, close or read). A request's first
answer or withdrawal stands; anything after it is ignored. Every write holds a file lock, so agents filing at the
same moment never clobber each other, and ids are never reused, even after a hand edit.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import jsonread
from .store import Refused, _open_lock, now, stamp

MAX_TITLE, MAX_TEXT, MAX_OPTIONS, CARD_LINES = 120, 1000, 9, 5
MAX_RULE = 400        # the same limit as a rule taught at the user's own terminal
# How an asker's name was known (agents.py), in the words the user reads.
HOW_WORDS = {"bound": "bound by you", "claimed": "claimed", "observed": "seen", "fallback": "unnamed"}
NOTES_BYTES = 3_000   # the inbox's share of the hook's output, so the card always keeps most of the room
ASKER = "ai"          # who is asking when an agent does not say: `ask --from`, `answers` and the hook all default to it
FROM_THE_USER = ("terminal", "page", "chat")
# The shape of an answer typed in chat: "#12 2" (an option), "#12 done" or "#12 won't" (a command), each with the
# user's words after one of the marks . , ; : ("#12 2, after lunch"); "#12 add" or "#12 no" alone (a proposed rule;
# rewording one is the page's); or "#12: their own words" (only for a question with no options). Nothing looser: "#1
# priority is speed", "#4 1 broken link", "#4 1 - broken link" and "#12 2-3 tests failing" are sentences, not answers
# (a dash and a closing bracket are left out of the marks: issue lists and ranges use them). A message is taken as an
# answer only when it is ONE such line and nothing else, its ends trimmed (typed_answer): pasted notes, an issue list
# or a ranked list of "#N" lines is text that mentions requests, which the tool's record of who typed it cannot tell
# apart from an answer.
CHAT_ANSWER = re.compile(
    r"^[ \t]*#(\d{1,7})(?:"
    r"[ \t]+(\d{1,2})(?:[ \t]*[.,;:][ \t]*(.*?))?"                                # an option; words after a mark
    r"|[ \t]+(done|won['’]?t(?:[ \t]+do)?)(?:[ \t]*[.,;:][ \t]*(.*?))?"           # a command; words after a mark
    r"|[ \t]+(add|no)[ \t]*\.?"                                                    # a proposed rule: the word alone
    r"|[ \t]*:[ \t]*(\S.*?)"                                                       # their own words
    r")[ \t]*$", re.M | re.I)

FLAGS = {
    "may delete or overwrite": re.compile(r"\b(rm|rmdir|del|erase|rd|remove-item|unlink|shred|truncate|format|mkfs|dd|"
                                          r"move-item|mv|clear-content|set-content)\b|(^|[^>])>(?!>)\s*\S", re.I),
    "uses the network": re.compile(r"https?://|\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm|ssh|scp|sftp|ftp|"
                                   r"git\s+(push|pull|clone|fetch)|pip\s+install|npm\s+(i|install)|winget|choco|brew)\b",
                                   re.I),
    "asks for admin": re.compile(r"\b(sudo|runas|doas|set-executionpolicy)\b|-verb\s+runas", re.I),
}
# Key-shaped strings. A miss here is the silent direction (the key is kept, or sent), so the list is wide on purpose:
# a false alarm only skips one message.
SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}|whsec_[A-Za-z0-9]{20,}|"   # OpenAI-style, Stripe
    r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20,}|"    # GitHub, GitLab
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|ya29\.[0-9A-Za-z_-]{20,}|"                     # AWS, Google
    r"xox[baprs]-[A-Za-z0-9-]{10,}|hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,}|"          # Slack
    r"hf_[A-Za-z0-9]{30,}|npm_[A-Za-z0-9]{30,}|"                                             # Hugging Face, npm
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|"                          # a JSON web token
    r"-----BEGIN [A-Z0-9 ]+-----|"                                                           # a PEM key
    r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@|"                                              # user:password@ in a URL
    r"(password|passwd|passphrase|secret|token|api[_-]?key)\s*[=:]\s*\S{6,}|"
    r"\b(password|passphrase|passcode)\s+(is|was)\s+\S{4,})", re.I)                          # said in prose
TOKEN_RUN = re.compile(r"[A-Za-z0-9+/=_-]{32,}")


def token_like(text: str) -> bool:
    """An unbroken run of 32 or more letters, digits and token marks, with both letters and digits in it: the shape of
    a key no list names. Checked only before anything leaves the machine, where a false alarm costs one skipped call."""
    return any(any(c.isdigit() for c in m) and any(c.isalpha() for c in m)
               for m in TOKEN_RUN.findall(text or ""))
# Set in an agent's own shell. A terminal where one of these is set is an agent's, so it cannot answer.
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED",
                 "SEMANTEXT_AGENT")


def _text(value, field: str, limit: int, required: bool = True) -> str:
    value = " ".join(str(value or "").split())
    if required and not value:
        raise Refused(f"a request needs {field}")
    if len(value) > limit:
        raise Refused(f"keep {field} under {limit} characters")
    return value


def _command(value) -> str:
    """A command is kept exactly as written: its spaces, its line breaks, a here-string. Only the ends are trimmed,
    and control characters other than newline and tab are refused, since they could hide what the command does."""
    value = str(value or "").replace("\r\n", "\n").strip()
    if not value:
        raise Refused("a request needs a command")
    if len(value) > MAX_TEXT:
        raise Refused(f"keep a command under {MAX_TEXT} characters")
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in value):
        raise Refused("a command may not hold control characters (only line breaks and tabs)")
    return value


def flags(command: str) -> list[str]:
    """A second look, never a guarantee: no flag does not mean safe."""
    return [name for name, rx in FLAGS.items() if rx.search(command or "")]


def stdin_is_console() -> bool:
    """Whether standard input is a person's terminal.

    On Windows, os.isatty() is also true for NUL, the null device that agents' shells attach to standard input, so
    there the console itself is asked: GetConsoleMode succeeds only on a real console."""
    try:
        if sys.platform == "win32":
            import ctypes
            import msvcrt
            mode = ctypes.c_uint32()
            handle = ctypes.c_void_p(msvcrt.get_osfhandle(0))
            return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
        return os.isatty(0)
    except (OSError, ValueError, AttributeError):
        return False


def human_terminal() -> str | None:
    """Why this is not the user at their own terminal, or None if it is. Answering, and changing the user's rules or
    agents, are the user's acts, refused anywhere else."""
    # The refusal names no variable: a message that says which one to clear is a recipe, not a reason. SECURITY.md
    # lists them for the user.
    if any(os.environ.get(m) for m in AGENT_MARKERS):
        return "an agent's shell"
    if not stdin_is_console():
        return "not an interactive terminal"
    return None


def age(stamp: str) -> str:
    try:
        secs = (datetime.now().astimezone() - datetime.fromisoformat(stamp)).total_seconds()
    except (TypeError, ValueError):
        return ""
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= size:
            n = int(secs // size)
            return f"{n} {unit}{'s' if n != 1 else ''}"
    return "moments"


@contextmanager
def file_lock(lock_path: Path, busy: str, tries: int = 200):
    """One writer at a time, across processes. The lock is the operating system's, so nothing is left behind. About
    five seconds of patience on every platform (tries of 25 ms each), then a clear refusal. The lock file is opened
    as the store's are (store._open_lock): only a plain file with one name is a lock, never a folder, a link, a
    junction or a second hard link standing at its name, which would be followed, or lock another file's bytes."""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(_open_lock(lock_path), "r+b") as f:
        if os.name == "nt":
            import msvcrt
            for _ in range(tries):
                try:
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.025)
            else:
                raise Refused(busy)
            try:
                yield
            finally:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            for _ in range(tries):
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    time.sleep(0.025)
            else:
                raise Refused(busy)
            try:
                yield
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class Inbox:
    def __init__(self, root: Path):
        self.path = Path(root) / "inbox.jsonl"
        self.lock_path = Path(root) / "inbox.lock"
        self.seq_path = Path(root) / "inbox.seq"   # the last id given out: a hand-deleted line never frees its id

    def _seq(self) -> int:
        try:
            return int(self.seq_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0

    # ---- the file ---------------------------------------------------------------------------------------------
    @contextmanager
    def _locked(self):
        with file_lock(self.lock_path, "the inbox is busy; try again in a moment"):
            yield

    def events(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                e = jsonread.loads(line)
            except json.JSONDecodeError:
                continue  # a damaged line is skipped, never fatal
            if isinstance(e, dict) and isinstance(e.get("id"), int) and e.get("type") in (
                    "request", "answer", "close", "read"):
                out.append(e)
        return out

    def _append(self, event: dict) -> None:
        with open(self.path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def requests(self) -> dict[int, dict]:
        """Every request with its current state, folded from the events: the latest wins."""
        out: dict[int, dict] = {}
        for e in self.events():
            rid = e["id"]
            if e["type"] == "request":
                if rid not in out:
                    out[rid] = {**{k: v for k, v in e.items() if k != "type"}, "status": "open", "answer": None,
                                "closed": None, "read": False, "read_at": None}
            elif rid in out:
                r = out[rid]
                if e["type"] == "answer" and r["status"] == "open":
                    r["status"], r["answer"] = "answered", {k: v for k, v in e.items() if k not in ("type", "id")}
                elif e["type"] == "close" and r["status"] == "open":
                    r["status"], r["closed"] = "closed", {k: v for k, v in e.items() if k not in ("type", "id")}
                elif e["type"] == "read" and r["status"] == "answered" and not r["read"]:
                    r["read"], r["read_at"] = True, e.get("at")
        return out

    def get(self, rid: int) -> dict:
        r = self.requests().get(rid)
        if r is None:
            raise Refused(f"no request #{rid}")
        return r

    # ---- asking (an agent may) --------------------------------------------------------------------------------
    def ask(self, title: str, why: str, question: str = "", options: list[str] | None = None, recommend: int = 0,
            command: str = "", does: str = "", undo: str = "", cwd: str = "", source: str = "ai",
            how: str = "", rule: str = "", env: str = "", key: str = "", session: str = "", agent: str = "") -> dict:
        """File a request: a decision, a command, or a rule an agent proposes for the environment `env`. `how` is how
        the asker's name was known (bound, claimed, observed or fallback, from agents.py); a claimed name is shown as
        claimed wherever the request appears. `key` and `session` say whose request it is (see mine())."""
        title, why = _text(title, "a title", MAX_TITLE), _text(why, "a why (--why)", MAX_TEXT)
        source = _text(source, "a sender name", 60)
        how = how if how in ("bound", "claimed", "observed", "fallback") else ""
        # Every field is kept in the inbox file, shown on the page and sent with the next prompt, so none may carry one;
        # the sender's name neither. A seen agent's name comes from its folder's, so the name gets the key shapes only:
        # the wide long-run check (agents.key_shaped) would refuse every request from a project with a long name.
        if any(SECRET.search(str(x)) for x in (title, why, question, command, does, undo, cwd, rule, source,
                                               *(options or [])) if x):
            raise Refused("that looks like it holds a key, a token or a password; never put one in a request")
        if sum(map(bool, (command, rule, question or options))) > 1:
            raise Refused("a request is one thing: a decision, a command or a rule")
        if rule:
            body = {"kind": "rule", "statement": _text(rule, "the rule", MAX_RULE),
                    "env": _text(env, "an environment", 60)}
            if agent:   # for that agent's own layer of the environment, not the shared rules
                body["agent"] = _text(agent, "an agent", 60)
        elif command:
            body = {"kind": "command", "command": _command(command),
                    "does": _text(does, "what the command does (--does)", MAX_TEXT),
                    "undo": _text(undo, "how to undo it, or 'cannot be undone' (--undo)", MAX_TEXT),
                    "cwd": _text(cwd, "a folder", 400, required=False), "flags": flags(command)}
        else:
            opts = [_text(o, "an option", 300) for o in options or []]
            if len(opts) > MAX_OPTIONS:
                raise Refused(f"offer at most {MAX_OPTIONS} options")
            if len({o.lower() for o in opts}) != len(opts):
                raise Refused("two options say the same thing")
            if recommend and not 1 <= recommend <= len(opts):
                raise Refused(f"--recommend must name one of the options, 1 to {len(opts)}")
            body = {"kind": "decision", "question": _text(question, "a question (--question)", MAX_TEXT),
                    "options": opts, "recommend": recommend or None}
        with self._locked():
            rid = 1 + max(self._seq(), max((e["id"] for e in self.events()), default=0))
            event = {"type": "request", "id": rid, "uid": stamp(), "at": now(),
                     "from": source, "title": title, "why": why, **body}
            if how:
                event["from_how"] = how
            if key:
                event["from_key"] = str(key)[:600]
            if session:
                event["from_session"] = str(session)[:100]
            self._append(event)
            self.seq_path.write_text(str(rid), encoding="utf-8")
        return self.get(rid)

    def close(self, rid: int, how: str = "", by: str = ASKER) -> dict:
        """The asker withdraws a request it no longer needs. It stays in the file, closed. Callers check who may
        (the asker, as stated, or the user at their own terminal)."""
        how = _text(how, "a reason", MAX_TEXT, required=False)
        with self._locked():
            r = self.get(rid)
            if r["status"] != "open":
                raise Refused(f"request #{rid} is already {r['status']}")
            self._append({"type": "close", "id": rid, "at": now(), "how": how, "by": by})
        return self.get(rid)

    def mark_read(self, rids: list[int], by: str = "ai") -> None:
        if not rids:
            return
        with self._locked():
            for rid in rids:
                self._append({"type": "read", "id": rid, "at": now(), "by": by})

    # ---- answering (only the user) ----------------------------------------------------------------------------
    def answer(self, rid: int, choice: str, words: str = "", *, via: str) -> dict:
        """The user's answer: an option's number, Done or Won't do for a command, or their own words. Their words
        are kept exactly, beside the choice, with where the answer came from.

        Who may answer is a rule with an audit trail, not a lock. From a terminal, an agent's shell or anything that
        is not a console is refused here; from the page, the server accepts only its own page's requests; from chat,
        only the hook answers, and only for a message that both its text and the tool's own record call the user's
        (hook.py). That stops an agent answering by accident. It cannot stop a program that already acts as you and
        fakes a console, the page or the tool's record; for that, every answer records where it came from, and one not
        from you is labelled wherever it shows."""
        if via not in FROM_THE_USER:
            raise Refused("an answer comes from the user's terminal, the page or their own message in chat")
        if via == "terminal":
            why_not = human_terminal()
            if why_not:
                raise Refused(f"cannot answer here: {why_not}. Only the user answers, from a terminal or the page")
        choice, words = str(choice or "").strip(), str(words or "").strip()
        if len(words) > MAX_TEXT or len(choice) > MAX_TEXT:
            raise Refused(f"keep your answer under {MAX_TEXT} characters")
        if SECRET.search(words):   # an answer is kept, shown on the page and sent with the asker's next prompt
            raise Refused("that looks like it holds a key, a token or a password; never put one in an answer")
        with self._locked():
            r = self.get(rid)
            if r["status"] != "open":
                raise Refused(f"request #{rid} is already {r['status']}")
            picked = None
            if r["kind"] == "decision" and r["options"] and choice.isdigit():
                n = int(choice)
                if not 1 <= n <= len(r["options"]):
                    raise Refused(f"request #{rid} has options 1 to {len(r['options'])}")
                picked = r["options"][n - 1]
            elif r["kind"] == "command" and choice.lower() in ("done", "won't", "wont", "won't do", "wont do"):
                picked = "Done" if choice.lower() == "done" else "Won't do"
            elif r["kind"] == "command" and choice:
                raise Refused("answer a command with Done or Won't do (and your words, if you like)")
            elif r["kind"] == "rule":
                if choice.lower() not in ("add", "no"):
                    raise Refused("answer a proposed rule with add or no (with add, your own wording replaces the "
                                  "agent's)")
                picked = "Add" if choice.lower() == "add" else "Don't add"
                if picked == "Add" and len(words) > MAX_RULE:
                    raise Refused(f"keep your wording of a rule under {MAX_RULE} characters")
            elif not (choice or words):
                raise Refused("give a choice, or your answer in your own words")
            self._append({"type": "answer", "id": rid, "at": now(), "choice": choice, "picked": picked,
                          "words": words, "via": via})
        return self.get(rid)

    # ---- reading ----------------------------------------------------------------------------------------------
    def open_requests(self, who=None) -> list[dict]:
        """Every open request, or, given an asker (an Identity, or a name), only that asker's own (see mine())."""
        return [r for r in self.requests().values() if r["status"] == "open" and (who is None or mine(r, who))]

    def unread_answers(self, who=None) -> list[dict]:
        return [r for r in self.requests().values()
                if r["status"] == "answered" and not r["read"] and (who is None or mine(r, who))]

    # ---- the register: what the user has decided --------------------------------------------------------------
    def earlier(self, r: dict, reqs: dict | None = None) -> dict | None:
        """The newest decision answered before this one that asked the same question with the same options, or None.
        Shown beside it, never used for it: an answer holds for what was offered when it was given."""
        if r.get("kind") != "decision":
            return None
        key = _ask_key(r)
        hits = [x for x in (reqs or self.requests()).values()
                if x["id"] < r["id"] and x["status"] == "answered" and x.get("kind") == "decision" and _ask_key(x) == key]
        return max(hits, key=lambda x: x["id"]) if hits else None

    def search(self, words: str = "", limit: int = 50) -> list[dict]:
        """The register: requests answered or withdrawn, newest first, those holding every one of `words` in their
        title, why, question, options, rule, command or answer."""
        want = _norm(words).split()
        out = []
        for r in sorted(self.requests().values(), key=lambda x: x["id"], reverse=True):
            if r["status"] == "open":
                continue
            a = r.get("answer") or {}
            hay = _norm(" ".join(str(v) for v in (r.get("title"), r.get("why"), r.get("question"), r.get("statement"),
                                                  r.get("command"), *(r.get("options") or []), a.get("picked"),
                                                  a.get("choice"), a.get("words")) if v))
            if all(w in hay for w in want):
                out.append(r)
                if len(out) >= limit:
                    break
        return out


def _norm(text) -> str:
    """Text as the register compares it: case, spacing and closing punctuation set aside."""
    return " ".join(re.sub(r"[?.!\s]+$", "", str(text or "")).casefold().split())


def _ask_key(r: dict) -> tuple:
    return _norm(r.get("question")), tuple(_norm(o) for o in r.get("options") or [])


def chat_answers(prompt) -> list[tuple[int, str, str]]:
    """Every line of a message shaped like an answer (see CHAT_ANSWER): (request number, choice, the user's words). The
    shape alone takes nothing: see typed_answer."""
    out = []
    for m in CHAT_ANSWER.finditer(prompt if isinstance(prompt, str) else ""):
        rid = int(m.group(1))
        if m.group(2):
            out.append((rid, m.group(2), m.group(3) or ""))
        elif m.group(4):
            out.append((rid, "done" if m.group(4).lower() == "done" else "won't", m.group(5) or ""))
        elif m.group(6):
            out.append((rid, m.group(6).lower(), ""))
        else:
            out.append((rid, "", m.group(7) or ""))
    return out


def typed_answer(prompt) -> tuple[int, str, str] | None:
    """The answer a message gives, only when the whole message is one answer line and nothing else; otherwise None. A
    paste, a list or a sentence that mentions a request answers nothing."""
    if not isinstance(prompt, str):
        return None
    text = prompt.lstrip("﻿").strip()
    if not text or "\n" in text or "\r" in text:
        return None
    found = chat_answers(text)   # one line: at most one answer
    return found[0] if found else None


LINE_REF = re.compile(r"^[ \t]*#(\d{1,7})\b", re.M)


def mentioned(prompt) -> list[int]:
    """The request numbers a message puts at the start of a line, the place an answer would put one."""
    return sorted({int(x) for x in LINE_REF.findall(prompt if isinstance(prompt, str) else "")})


def chat_notes(results: list[dict] | None, confirmed: bool = True) -> str:
    """The lines the hook puts first when the user's message answers a request: what was recorded, or what was not and
    why. Not `confirmed`: the tool kept no record saying the user typed it, so nothing was recorded."""
    if results is None:
        return ""
    if not confirmed:
        return ("## Not recorded as the user's answer: Semantext could not confirm, from the tool's own record, that the "
                "user typed this message. They can answer on the page, or with `semantext answer <number> <choice>` in "
                "their own terminal.")
    lines = ["## The user answered in this message (recorded in the inbox; the agent that asked gets the answer)"
             if any(x["ok"] for x in results) else "## Not recorded as the user's answer"]
    for x in results:
        line = f"- {x['said']}" if x["ok"] else f"- #{x['id']} was not recorded: {x['why']}"
        lines.append(line if len(line) <= 400 else line[:397] + "...")
    return "\n".join(lines)


def not_taken_note(ids: list[int]) -> str:
    """For a message that starts a line with a waiting request's number but is not one answer in the strict form."""
    named = ", ".join(f"#{i}" for i in ids[:6])
    return (f"## Not taken as the user's answer: this message names {named} where an answer would, but an answer is taken "
            f"only from a message that is one answer and nothing else (#12 2; #12 2, then words after a comma; "
            f"#12 done; #12 add; or #12: words, for a question with no options). Nothing was recorded.")


def withhold(text) -> str:
    """The text with every run shaped like a key no list names (token_like: 32 or more letters, digits and token marks,
    with both letters and digits) replaced by "(withheld)". Applied to the user's answers wherever Semantext prints or
    sends them, as the feed does; a full commit hash is withheld too. The page, the user's own screen, shows them whole."""
    def one(m):
        s = m.group()
        return "(withheld)" if any(c.isdigit() for c in s) and any(c.isalpha() for c in s) else s
    return TOKEN_RUN.sub(one, str(text or ""))


def mine(r: dict, who) -> bool:
    """Whether a request is this asker's own. An asker is an Identity (agents.py): the request is its own when it was
    filed in the same session, or under the same key, which a claim never shares with a bound or seen agent of the
    same name. A request with no key goes by its name and the assurance it was filed with: a claimed one reaches only
    claims, any other only what is not a claim, and one that never said (filed before anyone did) any asker of that
    name, as it always has. A plain name, as older callers pass, matches by name."""
    if isinstance(who, str):
        return r.get("from") == who
    session = getattr(who, "session", None)
    if session and r.get("from_session") == session:
        return True
    if r.get("from_key"):
        return r["from_key"] == getattr(who, "key", None) or carried(r["from_key"], getattr(who, "key", None))
    if r.get("from") != getattr(who, "name", None):
        return False
    filed = r.get("from_how") or ""
    return not filed or (filed == "claimed") == (getattr(who, "how", "") == "claimed")


def describe_answer(r: dict) -> str:
    """One line for an answer, as Semantext prints or sends it: a key-like run in it is withheld (see withhold). An
    answer that did not come from the user's terminal, the page or their own message (a hand-edited file, say) is
    labelled as such, wherever it is shown."""
    a = r["answer"]
    said = withhold(a.get("picked") or a.get("choice") or "")
    words = f' "{withhold(a["words"])}"' if a.get("words") else ""
    via = a.get("via")
    who = "" if via in FROM_THE_USER else f" (not from the user: via {via or 'unknown'})"
    return f"#{r['id']} {r['title']}: {said}{words}".rstrip(": ") + who


def register_line(r: dict) -> str:
    """One request on record, for an agent or the terminal: what was asked, what the user said, and when."""
    if r["status"] == "closed":
        return f"#{r['id']} {r['title']}: withdrawn {age((r.get('closed') or {}).get('at') or r['at'])} ago"
    if r["status"] == "open":
        return f"#{r['id']} {r['title']}: still waiting for the user's answer"
    return f"{describe_answer(r)} ({age(r['answer']['at'])} ago{', typed in chat' if r['answer'].get('via') == 'chat' else ''})"


def asked_before(inbox: Inbox, r: dict) -> str:
    """A note for an asker when the same question was answered before. The request is filed all the same."""
    e = inbox.earlier(r)
    if not e:
        return ""
    return (f" You asked this before: {describe_answer(e)}, {age(e['answer']['at'])} ago. It is filed again, since an "
            f"answer holds for what was offered when it was given; the user sees the earlier answer beside it.")


def carried(filed: str, key) -> bool:
    """A request an agent filed while seen (its tool and project) belongs to the bound agent once the user binds a
    folder holding that project: the binding names the same agent, so its requests and answers go with it, as pairing
    keeps a device's history. Only a seen agent's requests are carried; a claim's never are."""
    if not (isinstance(key, str) and key.startswith("bound:")) or filed.startswith(("claim:", "bound:")) or "@" not in filed:
        return False
    folder, path = key[len("bound:"):], filed.split("@", 1)[1]
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def card_notes(inbox: Inbox, who=ASKER, limit: int = NOTES_BYTES) -> str:
    """The inbox lines the hook puts BEFORE the card: answers not yet read, then what is still waiting. Read-only.
    Whole notes only, never a cut answer, and within `limit` bytes; what does not fit is counted, with the command
    that shows it."""
    sections = []
    answers = inbox.unread_answers(who)
    if answers:
        sections.append(("## The user's answers (act on these, then run `semantext answers` to mark them read)",
                         [f"- {describe_answer(r)}" for r in answers], "semantext answers"))
    waiting = inbox.open_requests(who)
    if waiting:
        sections.append((f"## Waiting for the user's answer ({len(waiting)}): do not act on these yet (they can answer "
                         f"by sending #<number> and their choice as a message of its own)",
                         [f"- #{r['id']} {r['title']} (asked {age(r['at'])} ago)" for r in waiting], "semantext inbox"))
    size = lambda s: len(s.encode("utf-8")) + 1   # noqa: E731 (one newline per line)
    lines = []
    for header, items, command in sections:
        room = limit // len(sections) - size(header) - 64   # 64: room kept for the "more" line
        lines.append(header)
        shown = 0
        for item in items[:CARD_LINES]:
            if size(item) > room:
                break
            lines.append(item)
            room -= size(item)
            shown += 1
        if shown < len(items):
            lines.append(f"- {len(items) - shown} more: run `{command}`")
    return "\n".join(lines)
