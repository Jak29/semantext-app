"""envhook: a folder of ratified environments, handed to an agent with every prompt (a UserPromptSubmit hook).

  python -m semantext.envhook --config envhook.json [--part core|seat] < event.json

The config names the environments folder, the shared environment every session gets, how a seat's own environment is
named, the header words, the rules of the short relay form, and how a session's seat is found. Nothing here names any
one owner: all of that is the config's.

WHO SEES WHAT.
  - Every session gets the shared environment ("core"). A session also gets its seat's own environment when the folder
    holds one ("seat_pattern", for example "{name}-seat").
  - The seat is the LATEST name the session declared: a command segment that runs a program with the declaring flag
    ("declare_flag", for example --agent-scope) as a bare argument. A flag inside a quoted argument, or later in the same
    segment, is argument text and does not count, so an agent writing about another seat is never handed that seat.
    Names in "commons" are shared stores, the identity of no one, and are skipped. Until a session has declared
    anything, its seat is the one whose home folder (the "roots" file) holds its working folder.
  - A prompt that is not the owner's own message (another session's message, a task notice, the tool's bracketed
    notice, or one the tool's own record marks as not the owner's) gets the short relay form: only the rules for
    reading relayed words, each whole and verbatim from the rendered card. The record can only take a prompt away from
    the owner, never toward: no record, or any failure, leaves the text to decide.
  - It never blocks a prompt: any failure prints one line saying the card is unavailable, and the exit code is 0.
  - Each part is whole. A part over the size limit says so on its first line, since a preview would hide the rest.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from . import envcard, jsonread

SEGMENT = re.compile(r"[\r\n;|]|&&")  # one command per segment; a here-string's lines are segments of their own
RUNS = re.compile(r"^\s*(?:\$[\w:]+\s*=\s*)?(?:&\s*)?(?:[\"']?[^\s\"']*?(?:python[0-9.]*|py)(?:\.exe)?[\"']?|\$\w+)\s",
                  re.IGNORECASE)
CHUNK = 8_000_000
TAIL_BYTES = 4_000_000
NOT_OWNER = ("<task-notification>", "Another Claude session sent a message:", "<cross-session-message")
NOTICE = re.compile(r"\[[^\]\n]{0,120}?(?:cross-session|not user input|non-user source|system notification)[^\]\n]{0,120}\]",
                    re.IGNORECASE)
# The tool can wrap another session's message, or a notice, in a system-reminder tag.
WRAPPED = re.compile(r"<system-reminder[^>]*>\s*(?:Another Claude session sent a message|\[SYSTEM NOTIFICATION)",
                     re.IGNORECASE)
TURN_ORIGIN = {"human": "own", "peer": "not", "task_notification": "not", "system": "not"}
ORIGIN_KIND = {"human": "own", "peer": "not", "task-notification": "not", "task_notification": "not", "system": "not"}
RULE_ID = re.compile(r"^- ([A-Za-z][A-Za-z0-9]*\.[A-Za-z0-9_.-]+):")
# Text that is not a command: a here-string's or a heredoc's body, and a quoted argument that holds a line break or a
# command separator. A line inside them that looks like a declaration is text (audit of 0515b12, finding 1). One linear
# pass (the recheck of 4fbf76f found the first, regex form quadratic on unclosed openers, and wrong in three ways).
HERE_OPEN = re.compile(r"@(['\"])[ \t]*\r?$")              # PowerShell: @' or @" ends its line
HEREDOC_OPEN = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1")
MASK_LIMIT = 200_000  # a command longer than this declares nothing: no real declaration is that long


def _blank_bodies(command: str) -> str:
    """Here-string and heredoc bodies as blanks, line by line. A body that never closes runs to the end."""
    out, close = [], None
    for line in command.split("\n"):
        if close is not None:
            kind, mark = close
            if kind == "here" and line.startswith(mark):
                out.append(" _ " + line[len(mark):])
                close = None
            elif kind == "doc" and line.strip() == mark:
                out.append(" _ ")
                close = None
            else:
                out.append(" _ ")
            continue
        m = HERE_OPEN.search(line)
        if m:
            out.append(line[:m.start()] + " _ ")
            close = ("here", m.group(1) + "@")
            continue
        m = HEREDOC_OPEN.search(line)
        if m:
            out.append(line[:m.start()] + " _ ")
            close = ("doc", m.group(2))
            continue
        out.append(line)
    return "\n".join(out)


def _blank_quotes(command: str) -> str:
    """Quoted arguments that hold a line break or a separator, as blanks. A quote opens only where an argument can
    start (not after a letter, a digit, a quote or a backtick, so "it's" opens nothing). Inside double quotes only
    PowerShell's backtick escapes a quote; a backslash is a plain character ("C:\\x\\" closes). An unclosed quote
    ends the scan, leaving the rest as it is."""
    out, i, n = [], 0, len(command)
    while i < n:
        ch = command[i]
        prev = command[i - 1] if i else " "
        if ch in "'\"" and not (prev.isalnum() or prev in "_'\"`"):
            j = command.find(ch, i + 1)
            while ch == '"' and j > 0 and command[j - 1] == "`":
                j = command.find(ch, j + 1)
            if j < 0:
                out.append(command[i:])
                break
            body = command[i:j + 1]
            out.append(" _ " if SEGMENT.search(body) else body)
            i = j + 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def quote_spans(text: str) -> list[tuple[int, int]]:
    """Where the quoted arguments are, by the same rules as masked(): a quote opens only where an argument can start,
    only a backtick escapes a double quote, and an unclosed quote runs to the end. This decides "inside a quote" for
    the seat reader and the line join, where counting quote characters took an apostrophe for a quote (audit of
    2679184, item 2: `--text "Ann's lesson" --agent-scope x` lost its real declaration)."""
    spans, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        prev = text[i - 1] if i else " "
        if ch in "'\"" and not (prev.isalnum() or prev in "_'\"`"):
            j = text.find(ch, i + 1)
            while ch == '"' and j > 0 and text[j - 1] == "`":
                j = text.find(ch, j + 1)
            if j < 0:
                spans.append((i, n))
                break
            spans.append((i, j + 1))
            i = j + 1
            continue
        i += 1
    return spans


def _outside_quotes(text: str) -> str:
    out, at = [], 0
    for a, b in quote_spans(text):
        out.append(text[at:a])
        at = b
    out.append(text[at:])
    return "".join(out)


def joined(command: str, tool) -> str:
    """PowerShell's line continuation: a line whose LAST character is a backtick (before any CR) runs on into the next
    (recheck of 4fbf76f, H07). Only for the PowerShell tool: in bash a backtick is command substitution. Never a line
    with a comment, where the backtick is literal. Applied after masking, so a here-string or quoted body is already
    a blank."""
    mark = {"PowerShell": "`", "Bash": "\\"}.get(tool)   # bash continues a line with a backslash (audit of 7bf7aa5)
    if mark is None:
        return command
    out, carry = [], ""
    for line in command.split("\n"):
        core = line[:-1] if line.endswith("\r") else line
        trailing = len(core) - len(core.rstrip(mark))
        unquoted = _outside_quotes(core)   # a # inside quotes is not a comment (audits of 84270dc and 2679184)
        if trailing % 2 and not re.search(r"(?:^|\s)#", unquoted):
            carry += core[:-1] + " "
            continue
        out.append(carry + line)
        carry = ""
    if carry:
        out.append(carry)
    return "\n".join(out)


def masked(command: str) -> str:
    """The command with its text blanked: here-string and heredoc bodies, and quoted arguments holding a line break or
    a separator. A quoted path or a quoted single-line value stays as it is."""
    if len(command) > MASK_LIMIT:
        return ""
    return _blank_quotes(_blank_bodies(command))


def _same(text: str) -> str:
    """A prompt's text in the form the record is compared in: CRLF and CR as LF, a no-break space as a space, no
    byte-order mark, no outer whitespace. The hook's prompt and the record's text can differ in exactly these
    (audit of 0515b12, finding 6: two prompts with CRLF got the owner's card in production)."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ").lstrip("﻿").strip()


def _head(prompt: str) -> str:
    """The prompt's opening, past whitespace and a byte-order mark (str.lstrip does not remove U+FEFF)."""
    return prompt.lstrip().lstrip("\ufeff").lstrip()


class Config:
    def __init__(self, data: dict, base: Path | None = None):
        d = dict(data)
        root = Path(d["environments"])
        self.envs = root if root.is_absolute() or base is None else base / root
        self.core = d["core"]
        self.seat_pattern = d.get("seat_pattern", "{name}-seat")
        self.headers = d["headers"]
        self.relay_rules = tuple(d.get("relay_rules") or ())
        self.relay_seat_suffix = d.get("relay_seat_suffix")
        self.flag = d.get("declare_flag", "--agent-scope")
        self.scope = re.compile(re.escape(self.flag) + r"[ =]+[\"']?([A-Za-z0-9_-]+)")
        self.commons = {c.lower() for c in d.get("commons") or ()}
        self.roots = Path(d["roots"]) if d.get("roots") else None
        self.relay_form = d.get("relay_form", True)
        self.record_check = d.get("record_check", True)
        self.limit = int(d.get("limit_bytes", 9_500))
        self.read_hint = d.get("read_hint", "{env}")

    @classmethod
    def load(cls, path) -> "Config":
        p = Path(path)
        return cls(jsonread.loads(p.read_text(encoding="utf-8")), p.parent)

    def env(self, name: str) -> Path:
        return self.envs / name / "SEMANTICS.yaml"

    def seat_env(self, seat: str) -> Path:
        return self.env(self.seat_pattern.format(name=seat))


def declared_in(rec: dict, cfg: Config) -> str | None:
    """The last name this transcript record declared: a bare flag argument of a command segment that runs a program."""
    content = (rec.get("message") or {}).get("content") if isinstance(rec.get("message"), dict) else None
    if not isinstance(content, list):
        return None
    found = None
    for c in content:
        if not (isinstance(c, dict) and c.get("type") == "tool_use"):
            continue
        command = (c.get("input") or {}).get("command")
        if not isinstance(command, str):
            continue
        for seg in SEGMENT.split(joined(masked(command), c.get("name"))):
            if not RUNS.match(seg):
                continue
            # the first flag OUTSIDE a quoted argument: a flag named inside text earlier in the segment no longer hides
            # a real one after it (audit of 86dfd4d, N17 and N18)
            spans = quote_spans(seg)
            m = next((x for x in cfg.scope.finditer(seg) if not any(a <= x.start() < b for a, b in spans)), None)
            if not m:
                continue
            name = m.group(1).lower()
            if name not in cfg.commons:
                found = name
    return found


def latest_scope(transcript, cfg: Config, chunk: int = CHUNK) -> str | None:
    """The name the session declared LAST, read backwards from the end of its transcript."""
    mark = cfg.flag.encode("utf-8")
    try:
        fh = open(transcript, "rb")
    except (OSError, TypeError, ValueError):
        return None
    with fh:
        fh.seek(0, 2)
        pos, tail = fh.tell(), b""
        while pos > 0:
            n = min(chunk, pos)
            pos -= n
            fh.seek(pos)
            lines = (fh.read(n) + tail).split(b"\n")
            tail = lines.pop(0) if pos > 0 else b""
            for line in reversed(lines):
                if mark not in line or b'"tool_use"' not in line:
                    continue
                try:
                    name = declared_in(jsonread.loads(line), cfg)
                except ValueError:
                    continue
                if name:
                    return name
    return None


def folder_seat(cwd, cfg: Config) -> str | None:
    """The seat whose home folder holds this working folder (the deepest, if homes nest). None on any doubt."""
    if cfg.roots is None:
        return None
    try:
        data = jsonread.loads(cfg.roots.read_text(encoding="utf-8"))
        base = data["base"]
        here = os.path.normcase(os.path.normpath(str(cwd)))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    best, depth = None, -1
    for name, seat in (data.get("seats") or {}).items():
        home = seat.get("home") if isinstance(seat, dict) else None
        if not home:
            continue
        h = os.path.normcase(os.path.normpath(os.path.join(base, home)))
        if (here == h or here.startswith(h + os.sep)) and len(h) > depth:
            best, depth = name.lower(), len(h)
    return best


def session_seat(transcript, cwd, cfg: Config) -> str | None:
    """The declared seat; or, while the session has declared nothing at all, its folder's seat."""
    name = latest_scope(transcript, cfg)
    if name is None:
        name = folder_seat(cwd, cfg)
    return name if name and cfg.seat_env(name).is_file() else None


def _kind(origin) -> str | None:
    return ORIGIN_KIND.get(origin.get("kind")) if isinstance(origin, dict) else None


def _record_text(rec: dict) -> str | None:
    content = (rec.get("message") or {}).get("content") if isinstance(rec.get("message"), dict) else None
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") or None
    return content if isinstance(content, str) else None


def _record_says(rec: dict) -> tuple[str | None, str | None]:
    a = rec.get("attachment") if isinstance(rec.get("attachment"), dict) else {}
    if a.get("type") == "queued_command":
        text = a.get("prompt") if isinstance(a.get("prompt"), str) else None
        if a.get("humanTurn"):
            return text, "own"
        if a.get("commandMode") == "task-notification" or a.get("isMeta"):
            return text, "not"
        return text, _kind(a.get("origin")) or _kind(rec.get("origin"))
    if rec.get("type") == "user":
        text = _record_text(rec)
        if rec.get("isCompactSummary") or rec.get("isVisibleInTranscriptOnly"):
            return text, "not"
        says = TURN_ORIGIN.get(rec.get("turnOrigin")) or _kind(rec.get("origin"))
        if says is None and rec.get("isMeta"):
            says = "not"
        return text, says
    return None, None


def record_says(transcript, prompt, tail: int = TAIL_BYTES) -> str | None:
    """What the tool's own record says of this prompt: 'own', 'not', or None. The newest matching record decides."""
    if not transcript or not isinstance(prompt, str) or not prompt.strip():
        return None
    want = _same(prompt)
    # the needle is the first word only (up to 40 characters), so line ends and no-break spaces cannot hide a record;
    # the exact comparison below decides. A record may store non-ASCII as itself or as \u escapes: both are looked for
    first = re.split(r"\s", want, maxsplit=1)[0][:40] or want[:40]
    needles = {json.dumps(first, ensure_ascii=a)[1:-1].encode("utf-8") for a in (False, True)}
    try:
        with open(transcript, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - tail))
            lines = fh.read().splitlines()
    except (OSError, ValueError, TypeError):
        return None
    for line in reversed(lines):
        if not any(n in line for n in needles):
            continue
        try:
            rec = jsonread.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        text, says = _record_says(rec)
        if text is not None and _same(text) == want:
            return says
    return None


def from_owner(prompt, transcript, cfg: Config) -> bool:
    """False for a prompt that opens as another session's message, a task notice or the tool's bracketed notice, and
    for one the tool's own record marks as not the owner's. The record can only take a prompt away from the owner."""
    if not isinstance(prompt, str):
        return True
    head = _head(prompt)
    if head.startswith(NOT_OWNER) or NOTICE.match(head) or WRAPPED.match(head):
        return False
    if not cfg.record_check:
        return True
    try:
        return record_says(transcript, prompt) != "not"
    except Exception:  # noqa: BLE001  the record is a second opinion: it never costs the owner the card
        return True


def seat_only(card: str, section: str) -> str:
    i = card.find(f"## {section}")
    if i < 0:
        raise RuntimeError("the seat's header is not in the card")
    return card[i:].strip()


def rule_id(line: str) -> str | None:
    m = RULE_ID.match(line)
    return m.group(1) if m else None


def relay_rules(card: str, wanted) -> list[str]:
    out = [line for line in card.splitlines() if line.startswith("## ")][:1]
    out += [line for line in card.splitlines() if rule_id(line) and wanted(rule_id(line))]
    return out


def compose(part: str, seat: str | None, own: bool, cfg: Config) -> str:
    """The text one hook entry prints; an empty string means print nothing."""
    h = cfg.headers
    seat_section = cfg.seat_pattern.format(name=seat) if seat else None
    if not own and cfg.relay_form:
        if part == "seat":
            if not seat:
                return ""
            card = seat_only(envcard.card(cfg.seat_env(seat)), seat_section)
            lines = relay_rules(card, lambda i: bool(cfg.relay_seat_suffix) and i.endswith(cfg.relay_seat_suffix))
            if len(lines) < 2:
                return ""
            return h["seat_relay"].format(Seat=seat.capitalize()) + "\n\n" + "\n".join(lines)
        lines = relay_rules(envcard.card(cfg.env(cfg.core)), lambda i: i in cfg.relay_rules)
        missing = [r for r in cfg.relay_rules if not any(rule_id(line) == r for line in lines)]
        if missing:  # a relay form without its rules is worse than none (audit of 0515b12, finding 2)
            raise RuntimeError(f"relay rule not in the card: {', '.join(missing)}")
        return h["relay"] + "\n\n" + "\n".join(lines)
    core_header = h["core_own"] if own else h["core_other"]
    if part == "core":
        return core_header + "\n\n" + envcard.card(cfg.env(cfg.core))
    if part == "seat":
        if not seat:
            return ""
        return h["seat"].format(Seat=seat.capitalize()) + "\n\n" + seat_only(envcard.card(cfg.seat_env(seat)),
                                                                              seat_section)
    return core_header + "\n\n" + envcard.card(cfg.seat_env(seat) if seat else cfg.env(cfg.core))


def with_size_warning(text: str, env: Path, cfg: Config) -> str:
    n = len(text.encode("utf-8"))
    if n <= cfg.limit:
        return text
    return (f"WARNING: this card is {n} bytes, over the harness's limit of about 10 KB, so only a preview is shown and "
            f"the rest is NOT in front of you. Read it whole: {cfg.read_hint.format(env=env)}\n\n" + text)


def part_of(argv: list[str]) -> str:
    if "--part" in argv:
        i = argv.index("--part")
        if i + 1 < len(argv) and argv[i + 1] in ("core", "seat"):
            return argv[i + 1]
    return "all"


def parse_payload(raw: str) -> dict:
    """The hook's JSON input; a leading byte-order mark is stripped, and anything unreadable gives {}."""
    try:
        payload = jsonread.loads(raw.lstrip("﻿") or "{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def run(raw: str, argv: list[str], cfg: Config) -> str:
    """What the hook prints for one event (without the final newline), or an empty string."""
    payload = parse_payload(raw)
    part = part_of(argv)
    env = cfg.env(cfg.core)
    try:
        seat = None if part == "core" else session_seat(payload.get("transcript_path") or "", payload.get("cwd"), cfg)
        if seat:
            env = cfg.seat_env(seat)
        text = compose(part, seat, from_owner(payload.get("prompt"), payload.get("transcript_path"), cfg), cfg)
    except Exception as e:  # noqa: BLE001  never block the message
        return (f"Semantext reading card unavailable (part {part}: {e.__class__.__name__}: {e}). "
                f"Read it by hand: {cfg.read_hint.format(env=env)}")
    return with_size_warning(text, env, cfg) if text else ""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        cfg = Config.load(argv[argv.index("--config") + 1])
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
        text = run(raw, argv, cfg)
    except Exception as e:  # noqa: BLE001  never block the message
        text = f"Semantext reading card unavailable ({type(e).__name__})."
    if text:
        out = (text + "\n").encode("utf-8", "replace")
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            buf.write(out)
            buf.flush()
        else:
            sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
