"""Which AI agent is asking, worked out without the user having to name anything.

An agent is what a card layer and an inbox belong to. Most people never name their agents, so Semantext works the
name out from what it can observe, and lets the user rename or bind it later. Identity comes only from facts a
model's text cannot write, and every identity says how it was found (its assurance). First match wins:

  1. bound: a folder the user bound to a name (`semantext agent bind NAME --folder DIR`), the deepest binding that
     holds the working folder. Only the user makes bindings, from their own terminal or the page. A different name
     stated in the shell is kept beside it as a claim, and changes nothing;
  2. claimed: the name the agent's own shell states, in SEMANTEXT_AGENT. The agent runs that shell, so this is a
     claim: it names a new, unbound agent, it is shown as claimed wherever it appears, and it is never served the
     own rules of an agent the user bound to a folder;
  3. observed: the tool and the project, such as claude-code@semantext-app or codex@notes. The tool is read from the
     hook event (a Claude Code hook event names its event) or from the shell's own markers (CLAUDECODE,
     CODEX_SANDBOX); the project is the working folder's git root, or the folder itself;
  4. fallback: "ai", the name an unnamed agent has always had.

A name only labels whose rules and answers these are. It never grants anything.

The same rules run in the hook and in the agent's shell, so a request the agent files with `semantext ask` and the
card its next prompt carries agree on who it is. Where the tool gives the shell its session id (Claude Code's
CLAUDE_CODE_SESSION_ID), the shell takes the identity the hook recorded for that session, when the shell's own facts
agree with it (the same tool, a folder inside that project), so a shell in a subfolder is still the same agent.

Sessions are recorded as the hook sees them, in sessions.json: per session id, its agent, tool, folder and when it
was first and last seen. Never the prompt text. Only the newest MAX_SESSIONS are kept, so the file stays small.

Several agents can start at once, so every change to either file is made under one lock, through a temporary file of
the writer's own. A change is never written over an agents.json that could not be read: it holds the user's bindings
and names. Working out a name never fails on this bookkeeping: if the file is busy, the name is still given, and only
remembering it waits for another time.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from .inbox import SECRET, file_lock, token_like
from .store import Refused, now

AGENT_ENV = "SEMANTEXT_AGENT"
SESSION_ENV = "CLAUDE_CODE_SESSION_ID"   # the session id Claude Code puts in the shell it gives its agent
FALLBACK = "ai"
MAX_SESSIONS = 200
BUSY = "the agents file is busy; try again in a moment"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9@._-]{0,59}")
# The marker each tool sets in the shell it gives its agent, and the name Semantext uses for that tool.
TOOL_MARKERS = (("CLAUDECODE", "claude-code"), ("CODEX_SANDBOX", "codex"), ("CODEX_SANDBOX_NETWORK_DISABLED", "codex"))


def clean(name) -> str:
    """A name as Semantext stores it: lower case, with anything outside letters, digits and @ . _ - made a dash."""
    s = re.sub(r"[^a-z0-9@._-]+", "-", str(name or "").strip().lower()).strip("-._")
    return s[:60]


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(NAME_RE.fullmatch(name))


def key_shaped(name) -> bool:
    """Whether a name, as given, looks like it holds a key, a token or a password. Checked before the name is cleaned,
    since cleaning reshapes the very marks a key is known by ("my password is x" becomes "my-password-is-x"). Such a
    name is never taken as a claim, so it never reaches the inbox, the sessions, the feed or the page."""
    s = str(name or "")
    return bool(SECRET.search(s)) or token_like(s)


def tool_of(event: dict | None = None, env=None) -> str | None:
    """The tool running the agent: from the hook event first, then from the shell's own markers."""
    if isinstance(event, dict) and event.get("hook_event_name"):
        return "claude-code"
    env = os.environ if env is None else env
    for marker, tool in TOOL_MARKERS:
        if env.get(marker):
            return tool
    return None


def norm(path) -> str:
    """A folder as a key: one spelling per folder on this machine."""
    return os.path.normcase(os.path.normpath(str(path)))


def _user_home() -> Path | None:
    try:
        return Path.home().resolve()
    except (OSError, RuntimeError, KeyError):
        return None


def project_root(cwd) -> Path | None:
    """The project a working folder belongs to: its git root, or the folder itself. The search stops at the user's
    home folder: a home kept in git (dotfiles) is not one project holding every folder under it."""
    if not cwd:
        return None
    try:
        here = Path(cwd).resolve()
    except (OSError, ValueError):
        return None
    home = _user_home()
    for p in (here, *here.parents):
        if p == home and p != here:
            break
        if (p / ".git").exists():
            return p
    return here


def project_of(cwd) -> str | None:
    """The project's plain name: its root folder's name, cleaned."""
    root = project_root(cwd)
    return (clean(root.name) or None) if root else None


def free_name(base: str, taken) -> str:
    """base, or base-2, base-3 and so on: the first one not taken."""
    taken, name, n = set(taken), base, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    return name


class Identity:
    """Who is asking: the agent's name, how it was found (bound, claimed, observed or fallback), what was seen, and
    any different name the shell claimed.

    `key` is what the inbox matches a request on, never the name alone: the binding's folder for a bound agent, the
    tool and the project's path for an observed one, "claim:NAME" for a claim, so a claim never reaches the requests
    of an agent bound or observed under the same name. `root` is the project's folder, as a key."""

    def __init__(self, name: str, how: str, tool: str | None = None, project: str | None = None,
                 session: str | None = None, claimed: str | None = None, key: str | None = None,
                 root: str | None = None):
        self.name, self.how, self.tool, self.project, self.session = name, how, tool, project, session
        self.claimed, self.key, self.root = claimed, key or name, root

    def __repr__(self):
        return f"Identity({self.name!r}, {self.how})"


class Agents:
    """The user's bindings and display names (agents.json) and the sessions seen (sessions.json), in the home."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.path = self.root / "agents.json"
        self.sessions_path = self.root / "sessions.json"
        self.lock_path = self.root / "agents.lock"

    # ---- the files -----------------------------------------------------------------------------------------------
    def _read(self, path: Path, empty, strict: bool = False):
        """The file's data, or `empty` if there is no file yet. A file that is there but cannot be read, or is not in
        the form Semantext writes, reads as `empty` too, unless strict: then it is refused, so that no change is
        written over it."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return empty
        except (OSError, ValueError):
            data = None
        if isinstance(data, type(empty)):
            return data
        if strict:
            raise Refused(f"{path} could not be read, so it was left as it is: fix it or move it aside, then try again")
        return empty

    def _write(self, path: Path, data) -> None:
        """Through a temporary file of this writer's own, renamed over the old file. On Windows the rename fails while
        another program has the file open, so it is retried for about a second."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            for _ in range(40):
                try:
                    tmp.replace(path)
                    return
                except PermissionError:
                    time.sleep(0.025)
            raise Refused(f"{path.name} is held open by another program; try again in a moment")
        finally:
            with suppress(OSError):
                tmp.unlink(missing_ok=True)

    def config(self, strict: bool = False) -> dict:
        c = self._read(self.path, {}, strict)
        for key, kind in (("bindings", list), ("names", dict), ("projects", dict)):
            if not isinstance(c.get(key), kind):
                c[key] = kind()
        return c

    # ---- who is asking -------------------------------------------------------------------------------------------
    def identify(self, env=None, cwd=None, event: dict | None = None) -> Identity:
        env = os.environ if env is None else env
        event = event if isinstance(event, dict) else {}
        cwd = event.get("cwd") or cwd
        if cwd is None:
            try:
                cwd = os.getcwd()
            except OSError:
                cwd = None
        if event:
            session = event.get("session_id") if isinstance(event.get("session_id"), str) else None
        else:
            session = str(env.get(SESSION_ENV) or "").strip()[:100] or None
        tool = tool_of(event, env)
        if session and not event:
            linked = self._linked(session, tool, cwd)   # the hook's own view of this session, when the facts agree
            if linked:
                return linked
            session = None   # a session id the hook never saw here is not this shell's: it counts for nothing
        root = project_root(cwd) if tool else None
        rootkey = norm(root) if root else None
        project = self.project_name(cwd) if tool else None   # no tool seen: no name uses the project, nothing is written
        raw = env.get(AGENT_ENV)
        stated = None if key_shaped(raw) else (clean(raw) or None)   # a key-shaped name is not taken, nor kept
        binding = self.binding(cwd)
        if binding:
            name, folder = binding
            return Identity(name, "bound", tool, project, session, claimed=stated if stated != name else None,
                            key=f"bound:{norm(folder)}", root=rootkey)
        if stated:
            return Identity(stated, "claimed", tool, project, session, key=f"claim:{stated}", root=rootkey)
        if tool:
            return Identity(f"{tool}@{project}" if project else tool, "observed", tool, project, session,
                            key=f"{tool}@{rootkey}" if rootkey else tool, root=rootkey)
        return Identity(FALLBACK, "fallback", tool, project, session, key=FALLBACK, root=rootkey)

    def _linked(self, session: str, tool: str | None, cwd) -> Identity | None:
        """The identity the hook recorded for this session, taken only when the shell's own facts agree with it: the
        same tool, and a working folder inside the project the hook saw. A shell that inherited another session's
        id, in another project, keeps its own identity and reaches none of that session's answers."""
        rec = self._read(self.sessions_path, {}).get(session)
        if not isinstance(rec, dict) or not rec.get("key") or not rec.get("root") or rec.get("tool") != tool:
            return None
        try:
            here = norm(Path(cwd).resolve())
        except (OSError, ValueError, TypeError):
            return None
        root = rec["root"]
        if here != root and not here.startswith(root.rstrip(os.sep) + os.sep):
            return None
        return Identity(rec.get("agent") or FALLBACK, rec.get("how") or "observed", tool, rec.get("project"), session,
                        key=rec["key"], root=root)

    def project_name(self, cwd) -> str | None:
        """A stable name per project PATH, not per folder name: the first project called app is "app", another
        folder called app elsewhere is "app-2", and each keeps its name. Two projects never merge into one agent."""
        root = project_root(cwd)
        if root is None:
            return None
        key = os.path.normcase(str(root))
        known = self.config()["projects"]
        if key in known:
            return known[key]
        base = clean(root.name) or "project"
        try:
            with file_lock(self.lock_path, BUSY):
                c = self.config(strict=True)        # again, under the lock: another agent may have just named it
                if key not in c["projects"]:
                    c["projects"][key] = free_name(base, c["projects"].values())
                    self._write(self.path, c)
                return c["projects"][key]
        except (OSError, Refused):
            return free_name(base, known.values())   # the name stands; remembering it waits for another time

    def is_bound_anywhere(self, agent: str) -> bool:
        return any(b.get("agent") == agent for b in self.config()["bindings"])

    def serves_own_rules(self, ident: Identity) -> bool:
        """Whether this identity gets its agent's own rules: when bound or observed, never when merely claimed. A
        claim is a name a shell states; until the user binds it, it gets the shared rules only, so no claim takes the
        rules of an agent bound or seen under that name."""
        return ident.how != "claimed"

    def own_names(self, ident: Identity) -> list[str]:
        """The names whose own rules this agent gets: its own, and, once the user binds a folder, those of the agents
        seen in a project inside that folder (claude-code@app), since the binding names those same agents. The rules
        taught to an agent before the user named it go with it, as its requests do. A claim gets none (see
        serves_own_rules)."""
        names = [ident.name]
        if ident.how == "bound" and str(ident.key).startswith("bound:"):
            names += self.carried_names(ident.key[len("bound:"):])
        return names

    def carried_names(self, folder) -> list[str]:
        """The names a binding of this folder takes over: the agents seen in a project at or inside it, unless a
        deeper binding holds that project, since the deepest binding names the agent (see binding). Never a project
        that holds the folder: outside a subfolder's binding, that project's agent is still itself."""
        c, folder = self.config(), norm(folder)
        deeper = [f for f in (norm(b["folder"]) for b in c["bindings"] if b.get("folder")) if len(f) > len(folder)]

        def under(path, top):
            return path == top or path.startswith(top.rstrip(os.sep) + os.sep)

        inside = {name for path, name in c["projects"].items()
                  if under(path, folder) and not any(under(path, f) for f in deeper)}
        return [f"{tool}@{project}" for project in sorted(inside) for tool in sorted({t for _, t in TOOL_MARKERS})]

    def binding(self, cwd) -> tuple[str, str] | None:
        """The agent bound to the deepest folder holding cwd, and that folder, if any."""
        if not cwd:
            return None
        try:
            here = norm(Path(cwd).resolve())
        except (OSError, ValueError):
            return None
        best, depth = None, -1
        for b in self.config()["bindings"]:
            folder = norm(b.get("folder", "")) if b.get("folder") else ""
            if folder and (here == folder or here.startswith(folder.rstrip(os.sep) + os.sep)) and len(folder) > depth:
                best, depth = (b.get("agent"), b.get("folder")), len(folder)
        return best

    def bound(self, cwd) -> str | None:
        """The agent bound to the deepest folder holding cwd, if any."""
        b = self.binding(cwd)
        return b[0] if b else None

    # ---- what the user sets ----------------------------------------------------------------------------------------
    def bind(self, agent: str, folder) -> Path:
        name = clean(agent)
        if not valid_name(name):
            raise Refused("name the agent with letters, digits and @ . _ -, up to 60 characters")
        try:
            path = Path(folder).resolve()
        except (OSError, ValueError):
            raise Refused(f"cannot use the folder {folder!r}")
        if not path.is_dir():
            raise Refused(f"{path} is not a folder")
        with file_lock(self.lock_path, BUSY):
            c = self.config(strict=True)
            c["bindings"] = [b for b in c["bindings"] if Path(b.get("folder", "")) != path]
            c["bindings"].append({"folder": str(path), "agent": name, "at": now()})
            self._write(self.path, c)
        return path

    def unbind(self, folder) -> bool:
        path = Path(folder).resolve()
        with file_lock(self.lock_path, BUSY):
            c = self.config(strict=True)
            kept = [b for b in c["bindings"] if Path(b.get("folder", "")) != path]
            if len(kept) == len(c["bindings"]):
                return False
            c["bindings"] = kept
            self._write(self.path, c)
        return True

    def rename(self, agent: str, label: str) -> None:
        """A display name for an agent, shown on the page. The agent's own name, which its rules hang on, stays."""
        name, label = clean(agent), " ".join(str(label or "").split())[:60]
        if not valid_name(name):
            raise Refused("name the agent to rename, as `semantext agents` shows it")
        with file_lock(self.lock_path, BUSY):
            c = self.config(strict=True)
            if label:
                c["names"][name] = label
            else:
                c["names"].pop(name, None)
            self._write(self.path, c)

    # ---- sessions ------------------------------------------------------------------------------------------------
    def seen(self, ident: Identity, transcript: str | None = None) -> None:
        """Record that the hook saw this session, and where the tool keeps its transcript. Never the prompt. The newest
        MAX_SESSIONS are kept. This is bookkeeping: an unreadable sessions.json starts over, and a busy one is skipped
        this time, so a prompt never fails because of it."""
        if not ident.session:
            return
        try:
            with file_lock(self.lock_path, BUSY):
                sessions = self._read(self.sessions_path, {})
                rec = sessions.pop(ident.session, None) or {"first": now(), "prompts": 0}
                rec.update(agent=ident.name, how=ident.how, tool=ident.tool, project=ident.project, key=ident.key,
                           root=ident.root, last=now(), prompts=int(rec.get("prompts", 0)) + 1)
                if transcript:
                    rec["transcript"] = str(transcript)[:1000]
                sessions[ident.session] = rec
                if len(sessions) > MAX_SESSIONS:
                    newest = sorted(sessions.items(), key=lambda kv: kv[1].get("last", ""))[-MAX_SESSIONS:]
                    sessions = dict(newest)
                self._write(self.sessions_path, sessions)
        except (OSError, Refused):
            pass

    def transcript_of(self, ident: Identity) -> str | None:
        """Where the tool keeps this session's transcript, as the hook recorded it. Only for a session the shell's own
        facts agreed with (identify() keeps no other), so a borrowed session id lends no one's words."""
        if not ident.session:
            return None
        rec = self._read(self.sessions_path, {}).get(ident.session)
        path = rec.get("transcript") if isinstance(rec, dict) else None
        return path if isinstance(path, str) and path else None

    def overview(self) -> list[dict]:
        """Every agent the user has bound or named, or the hook has seen: newest first, with its sessions."""
        c, sessions = self.config(), self._read(self.sessions_path, {})
        agents: dict[str, dict] = {}
        for sid, rec in sessions.items():
            a = agents.setdefault(rec.get("agent") or FALLBACK, {"sessions": [], "last": ""})
            a["sessions"].append({"id": sid, **{k: rec.get(k) for k in ("tool", "project", "first", "last", "prompts",
                                                                        "how")}})
            a["last"] = max(a["last"], rec.get("last") or "")
        for b in c["bindings"]:
            agents.setdefault(b["agent"], {"sessions": [], "last": ""}).setdefault("folders", []).append(b["folder"])
        for name in c["names"]:
            agents.setdefault(name, {"sessions": [], "last": ""})
        out = []
        for name, a in agents.items():
            a["sessions"].sort(key=lambda s: s.get("last") or "", reverse=True)
            out.append({"name": name, "label": c["names"].get(name, ""), "folders": a.get("folders", []),
                        "last": a["last"], "sessions": a["sessions"]})
        return sorted(out, key=lambda a: a["last"], reverse=True)


def since(stamp: str) -> str:
    """'3 minutes ago' style, for a stored timestamp."""
    try:
        then = datetime.fromisoformat(stamp)
        secs = max(0, int((datetime.now(then.tzinfo) - then).total_seconds()))
    except (TypeError, ValueError):
        return "some time ago"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if secs >= size:
            n = secs // size
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "moments ago"
