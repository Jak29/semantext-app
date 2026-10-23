"""`semantext mcp`: Semantext as an MCP server, so any AI tool that speaks the Model Context Protocol gets your card and
your inbox, on this machine.

It speaks JSON-RPC 2.0 over standard input and output, one message per line, as MCP's stdio transport does. What it
offers, and what it never does:

- Your card: in the server's instructions, which most clients put before the conversation, and as the `card` tool,
  with that agent's own rules and its inbox notes, as the Claude Code hook gives them.
- The inbox, from the agent's side: `ask`, `answers` and `close`. There is no tool to answer. Answers stay at your own
  terminal and on your page.
- `propose_rule`: a rule the agent proposes, filed in your inbox for you to add or decline. Over MCP a rule is always a
  proposal: there is no transcript here to show that the words are yours.
- Who is asking: a tool that marks its own processes (Claude Code, Codex) is seen as itself, and a folder you bound
  wins. Otherwise the client's own name for itself is a claim, until you bind its folder to a name.

Nothing here changes your rules, and nothing leaves this machine.
"""
from __future__ import annotations

import json
import os
import sys

from . import __version__, jsonread
from .agents import Agents, Identity, clean, key_shaped
from .hook import LIMIT_BYTES, fit
from .inbox import Inbox, asked_before, card_notes, describe_answer, mine, register_line
from .store import Refused, Store

VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")   # newest first; a client's own is used when it is one of these
PREFACE = ("Semantext: the user's standing rules for reading them, below. Call the `card` tool at the start of each "
           "task to read them fresh, with your own requests and the user's answers to them. When you need the user's "
           "decision or permission, file it with `ask` and keep working on what does not need it.")

TOOLS = [
    {"name": "card", "description": "The user's reading card: their standing rules for how to read them, with your "
                                    "own rules and your inbox notes. Read it at the start of each task.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "ask", "description": "File a request in the user's inbox, and keep working on what does not need it: "
                                   "a decision (question and options) or a command for them to run themselves. "
                                   "Act on it only once their answer reaches you.",
     "inputSchema": {"type": "object", "required": ["title", "why"], "properties": {
         "title": {"type": "string", "description": "a short title"},
         "why": {"type": "string", "description": "why it needs the user"},
         "question": {"type": "string", "description": "a decision: the question"},
         "options": {"type": "array", "items": {"type": "string"}, "description": "a decision: up to 9 options"},
         "recommend": {"type": "integer", "description": "a decision: the number of the option you recommend"},
         "command": {"type": "string", "description": "a command for the user to run themselves; never run for them"},
         "does": {"type": "string", "description": "a command: what it does"},
         "undo": {"type": "string", "description": "a command: how to undo it, or 'cannot be undone'"}}}},
    {"name": "answers", "description": "The user's new answers to your requests, in full; they are then marked read.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "decisions", "description": "Search what the user has already decided (every answered request, newest "
                                         "first), before you ask. An answer holds for what was offered when it was "
                                         "given: if anything has changed, ask again.",
     "inputSchema": {"type": "object", "properties": {
         "words": {"type": "string", "description": "words the request held; empty for the newest"}}}},
    {"name": "close", "description": "Withdraw one of your own requests that is no longer needed.",
     "inputSchema": {"type": "object", "required": ["id"], "properties": {
         "id": {"type": "integer"}, "how": {"type": "string", "description": "why it is withdrawn"}}}},
    {"name": "propose_rule", "description": "Propose a rule for how to read the user, after they corrected you. It "
                                            "waits in their inbox, and reaches the card only if they add it.",
     "inputSchema": {"type": "object", "required": ["rule"], "properties": {
         "rule": {"type": "string", "description": "the rule, in the user's own words where you can"},
         "why": {"type": "string", "description": "why you propose it"},
         "for_me_only": {"type": "boolean", "description": "a rule for you alone, not for every agent"}}}},
]


class Server:
    """One client's connection. Who it is, is worked out afresh on every call, so a binding made meanwhile counts."""

    def __init__(self, store: Store, env=None, cwd=None):
        self.store, self.env, self.cwd = store, os.environ if env is None else env, cwd
        self.client: str | None = None

    # ---- who is asking -------------------------------------------------------------------------------------------
    def who(self) -> Identity:
        agents = Agents(self.store.root)
        ident = agents.identify(env=self.env, cwd=self.cwd)
        if ident.how in ("bound", "observed", "claimed") or not self.client:
            return ident
        # the client's own name for itself: a claim, until the user binds the folder; one shaped like a key is not taken
        name = "" if key_shaped(self.client) else clean(self.client)
        return Identity(name, "claimed", None, None, None, key=f"claim:{name}") if name else ident

    def card(self) -> str:
        who, agents = self.who(), Agents(self.store.root)
        name = self.store.state()["active"]
        layer = agents.own_names(who) if agents.serves_own_rules(who) else None
        notes = card_notes(Inbox(self.store.root), who)
        card = self.store.served_card(name, agent=layer)   # a broken rule file still leaves the base rules
        if not notes:
            return fit(card, LIMIT_BYTES - 1)
        return notes + "\n\n" + fit(card, LIMIT_BYTES - 1 - len(notes.encode("utf-8")) - 2)

    # ---- the tools ---------------------------------------------------------------------------------------------------
    def call(self, tool: str, args: dict) -> str:
        if tool == "card":
            return self.card()
        who, inbox = self.who(), Inbox(self.store.root)
        if tool == "ask":
            options = args.get("options") or []
            if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
                raise Refused("options must be a list of short texts")
            r = inbox.ask(args.get("title", ""), args.get("why", ""), args.get("question") or "",
                          options, int(args.get("recommend") or 0), args.get("command") or "",
                          args.get("does") or "", args.get("undo") or "", "", who.name, how=who.how, key=who.key,
                          session=who.session or "")
            return (f"[#{r['id']}] {r['title']}: filed in the user's inbox. Keep working on what does not need it; "
                    f"their answer arrives through `answers`, or with the card. They can answer on their page, or by "
                    f"sending you #{r['id']} and their choice as a message of its own." + asked_before(inbox, r))
        if tool == "decisions":
            found = inbox.search(str(args.get("words") or ""), limit=20)
            return "\n".join(register_line(r) for r in found) if found else "Nothing on record matches."
        if tool == "answers":
            unread = inbox.unread_answers(who)
            if not unread:
                waiting = inbox.open_requests(who)
                return "No new answers." + (" Still waiting: " + ", ".join(f"#{r['id']}" for r in waiting)
                                            if waiting else "")
            inbox.mark_read([r["id"] for r in unread], by=who.name)
            return "\n".join(describe_answer(r) for r in unread) + "\nMarked as read."
        if tool == "close":
            rid = args.get("id")
            if not isinstance(rid, int):
                raise Refused("name the request by its number")
            if not mine(inbox.get(rid), who):
                raise Refused(f"#{rid} is not one of your requests; only its asker, or the user, can withdraw it")
            r = inbox.close(rid, str(args.get("how") or ""), by=who.name)
            return f"Withdrew #{r['id']} {r['title']}."
        if tool == "propose_rule":
            env = self.store.state()["active"]
            agent = None
            if args.get("for_me_only"):
                if not Agents(self.store.root).serves_own_rules(who):
                    raise Refused(f"{who.name} is a name stated, not one the user bound: propose a rule for every "
                                  f"agent, or ask the user to bind this agent's folder first")
                agent = who.name
            title = (f"Add a rule for {agent} in {self.store.title(env)}?" if agent
                     else f"Add a rule to {self.store.title(env)}?")
            r = inbox.ask(title, args.get("why") or "An AI agent proposes this rule. It reaches the card only if you "
                                                     "add it.", rule=str(args.get("rule") or ""), env=env,
                          source=who.name, how=who.how, key=who.key, session=who.session or "", agent=agent or "")
            return (f"[#{r['id']}] Proposed, not learned. The rule waits in the user's inbox, and reaches the card only "
                    f"when they add it.")
        raise LookupError(tool)

    # ---- JSON-RPC ----------------------------------------------------------------------------------------------------
    def handle(self, msg):
        """The reply to one message, or None for a notification or a client's own response."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            if isinstance(msg, dict) and "method" not in msg and ("result" in msg or "error" in msg):
                return None   # a response to a request of ours: we send none, so there is nothing to do
            return _error(msg.get("id") if isinstance(msg, dict) else None, -32600, "not a JSON-RPC 2.0 request")
        method, params, rid = msg["method"], msg.get("params") or {}, msg.get("id")
        if "id" not in msg:
            return None   # a notification (notifications/initialized and the rest): no reply, ever
        if not isinstance(params, dict):
            return _error(rid, -32602, "params must be an object")
        if method == "initialize":
            info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
            self.client = str(info.get("name") or "")[:60] or None
            asked = params.get("protocolVersion")
            try:
                instructions = PREFACE + "\n\n" + self.card()
            except (Refused, OSError) as e:
                instructions = PREFACE + f"\n\n(The card is unavailable just now: {e}. Call `card` to try again.)"
            return _result(rid, {"protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
                                 "capabilities": {"tools": {}},
                                 "serverInfo": {"name": "semantext", "version": __version__},
                                 "instructions": instructions})
        if method == "ping":
            return _result(rid, {})
        if method == "tools/list":
            return _result(rid, {"tools": TOOLS})
        if method == "tools/call":
            tool, args = params.get("name"), params.get("arguments") or {}
            if not isinstance(tool, str) or tool not in {t["name"] for t in TOOLS}:
                return _error(rid, -32602, f"no such tool: {tool!r}")
            if not isinstance(args, dict):
                return _error(rid, -32602, "arguments must be an object")
            try:
                return _result(rid, {"content": [{"type": "text", "text": self.call(tool, args)}], "isError": False})
            except (Refused, ValueError, TypeError) as e:
                return _result(rid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            except OSError as e:
                return _result(rid, {"content": [{"type": "text", "text": f"could not use your files: {e}"}],
                                     "isError": True})
        return _error(rid, -32601, f"no such method: {method}")

    def handle_line(self, line: str):
        try:
            msg = jsonread.loads(line)
        except (ValueError, RecursionError):
            return _error(None, -32700, "not valid JSON")
        if isinstance(msg, list):   # a batch, as the 2025-03-26 protocol allows
            replies = [r for r in (self._safely(m) for m in msg) if r is not None]
            return replies or None
        return self._safely(msg)

    def _safely(self, msg):
        """One message's reply; whatever goes wrong becomes an error reply, and the server keeps serving."""
        try:
            return self.handle(msg)
        except Exception as e:  # noqa: BLE001  one bad message must not end the client's connection
            rid = msg.get("id") if isinstance(msg, dict) else None
            return None if isinstance(msg, dict) and "id" not in msg else _error(rid, -32603, type(e).__name__)


def _result(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def serve(store: Store, stdin=None, stdout=None) -> int:
    """Read one JSON-RPC message per line until the client closes standard input. UTF-8 both ways, whatever this
    machine's own code page is, and plain newlines."""
    src = stdin if stdin is not None else getattr(sys.stdin, "buffer", sys.stdin)
    out = stdout if stdout is not None else getattr(sys.stdout, "buffer", sys.stdout)
    server = Server(store)
    for raw in src:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.lstrip("﻿").strip()
        if not line:
            continue
        reply = server.handle_line(line)
        if reply is None:
            continue
        text = json.dumps(reply, ensure_ascii=False) + "\n"
        out.write(text.encode("utf-8") if not hasattr(out, "encoding") else text)
        out.flush()
    return 0
