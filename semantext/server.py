"""The page: one local web page over your rule files, served on this machine only.

`semantext serve` starts it on http://127.0.0.1:8765. It listens on the loopback address only, answers only requests
addressed to that host, and accepts a change only with the page's own X-Semantext header, which a page on another
site cannot send without permission. So nothing outside your machine, and no other website open in your browser,
can change your rules.
"""
from __future__ import annotations

import getpass
import json
import socket
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from pathlib import Path

from . import __version__, agentfiles, claude, jsonread, paths
from .agents import Agents, clean, since
from .feed import Feed
from .hook import LIMIT_BYTES, WORDS, compose, fit, rule_lines, sender_name, sent_layers
from .inbox import Inbox, age, card_notes
from .sender import whose
from .sources import view
from .store import Refused, Store


def agents_view(st: Store) -> dict:
    """Every agent the user has bound, named or given rules, or the hook has seen, each with its own rules in the
    active environment, for the page."""
    active = st.state()["active"]
    layers = st.layers(st.load(active))
    agents = Agents(st.root)
    rows = {a["name"]: a for a in agents.overview()}
    by_env = {}                               # each environment's agent layers: how many live rules each agent has there
    for n in st.names():
        if n == "base":
            continue
        try:
            by_env[n] = {k: len([e for e in v if not e.get("archived")]) for k, v in st.layers(st.load(n)).items()}
        except (Refused, OSError):
            by_env[n] = {}
    for name in [*layers, *(k for counts in by_env.values() for k in counts)]:   # known only by the rules you gave it
        rows.setdefault(name, {"name": name, "label": "", "folders": [], "last": "", "sessions": []})
    live = lambda name: [e for e in layers.get(name, []) if not e.get("archived")]   # noqa: E731
    taken = {}                                # a seen name -> the agent whose binding took it over
    for a in rows.values():
        a["carried"] = []
        for folder in a["folders"]:
            for n in agents.carried_names(folder):
                if n != a["name"] and n not in taken:
                    taken[n] = a["name"]
                    if live(n):
                        a["carried"].append({"from": n, "rules": live(n)})
    out = []
    for a in rows.values():
        a["envs"] = {n: counts[a["name"]] for n, counts in by_env.items() if counts.get(a["name"])}
        a["rules"] = live(a["name"])
        a["now"] = taken.get(a["name"], "")  # its folder is bound: its rules go with that agent
        a["seen"] = since(a["last"]) if a.get("last") else ""
        for s in a["sessions"]:
            s["seen"] = since(s.get("last") or "")
        out.append(a)
    return {"active": active, "agents": out}


PERSON = ("you", "user", "the-user", "human", "person", "me", "owner", "admin", "root", "system")


def person_names() -> list[str]:
    """The names a relayed message would use to pass itself off as the person: the usual words, and this machine's
    account name. The page flags a sender that gives one ("claims to be you"); whose words a prompt carries is never
    decided by it (sender.whose)."""
    try:
        account = clean(getpass.getuser())
    except Exception:  # noqa: BLE001  no account name to be had: the usual words still stand
        account = ""
    return sorted({*PERSON, *([account] if account else [])})


def connections(st: Store) -> dict:
    """What hands the card out, read only: Claude Code's hook in its settings (None when the file cannot be read),
    and the instructions files Semantext keeps a copy of the card in."""
    settings = claude.default_settings()
    try:
        hooked = claude.is_installed(jsonread.loads(settings.read_text(encoding="utf-8-sig"))) if settings.exists() else False
    except (ValueError, OSError, UnicodeDecodeError, AttributeError):
        hooked = None
    files = [{"file": str(f), "ok": agentfiles.has_block(Path(f))} for f in st.state().get("agent_files", [])
             if isinstance(f, str)]
    return {"claude_code": hooked, "settings": str(settings), "files": files}


def layer_for(st: Store, agent: str) -> list[str] | None:
    """The names whose own rules this agent gets, as the hook works them out (agents.own_names): its own name, and
    the names a binding of its folder carries. None for no agent, or for a name only ever claimed, which the hook
    gives the shared rules alone."""
    if not agent:
        return None
    ag = Agents(st.root)
    a = next((x for x in ag.overview() if x["name"] == agent), None)
    if a and not a["folders"] and a["sessions"] and all(s.get("how") == "claimed" for s in a["sessions"]):
        return None
    names = [agent]
    for folder in (a or {}).get("folders", []):
        names += [n for n in ag.carried_names(folder) if n not in names]
    return names


def explain(st: Store, b: dict) -> dict:
    """What Semantext would hand an agent for these words, and how its cue words read them: the page's "Test a
    message", and its examples. The same steps as the hook (compose), with nothing written: no feed line, no heard
    item, no session, no pending decision."""
    message = str(b.get("message") or "")
    if len(message) > 4000:
        raise Refused("keep the message under 4,000 characters")
    words = b.get("words")
    basis = "page"
    if words not in WORDS.values():
        kind, basis = whose(message)            # detected from how the words open, as the hook does first
        words = WORDS[kind]
    agent = str(b.get("agent") or "")
    name = st.state()["active"]
    inbox = Inbox(st.root)
    notes = card_notes(inbox, agent) if agent else ""
    text, served = compose(st, name, "full" if words == "own" else "relay", layer_for(st, agent), notes)
    asked = [r for r in inbox.requests().values() if agent and r.get("from") == agent]
    return {"words": words, "basis": basis, "agent": agent, "from": sender_name(message), "text": text, **served,
            "answers": [r["id"] for r in asked if r["status"] == "answered" and not r["read"]],
            "waiting": [r["id"] for r in asked if r["status"] == "open"],
            "reading": st.read(name, message, dry=True)}


# What the quick reading noticed, and the base rule that speaks to it: a message was covered when that rule was on the
# card as sent (a rule switched off, or left out by the size limit, was not).
RULE_FOR = {"question": "base.question-not-instruction", "suggestion": "base.suggest-not-require",
            "yes": "base.yes-binds-to-offer", "pause": "base.parked-stays-parked", "time": "base.time-kept-verbatim",
            "correction": "base.corrections-become-rules", "instruction": "base.show-your-work",
            "needs-word": "base.irreversible-needs-your-word"}
ORIGIN = {"LEARNED": "yours", "PROPOSED": "proposed", "SUGGESTED": "suggested", "SETTING": "switch"}


def _minutes(a: str, b: str) -> float | None:
    try:
        return max(0.0, (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60)
    except (TypeError, ValueError):
        return None


def metrics(st: Store) -> dict:
    """What Semantext did, counted from its own records and nothing else: the feed, as far back as it still reaches
    (the newest lines are kept), and the inbox, all of it. Counts of what was done, never of what was said."""
    recs = Feed(st.root).recent(1_000_000)
    own = [r for r in recs if r["words"] == "own"]
    noticed: dict[str, dict] = {}
    for r in own:
        ids = {i for x in r["layers"] for i in x["ids"]}
        for k in dict.fromkeys(r["noticed"]):
            n = noticed.setdefault(k, {"n": 0, "covered": 0, "rule": RULE_FOR.get(k, "")})
            n["n"] += 1
            n["covered"] += RULE_FOR.get(k) in ids
    days: dict[str, dict] = {}
    for r in recs:
        d = days.setdefault(r["at"][:10], {"day": r["at"][:10], "own": 0, "agent": 0, "tool": 0})
        d[r["words"]] += 1
    others = [r for r in recs if r["words"] != "own"]
    you = set(person_names())
    reqs = list(Inbox(st.root).requests().values())
    answered = [r for r in reqs if r["status"] == "answered"]
    waits = sorted(m for m in (_minutes(r["at"], (r["answer"] or {}).get("at")) for r in answered) if m is not None)
    rules = {"base": 0, "environment": 0, "agents": 0, "yours": 0, "proposed": 0, "suggested": 0, "switch": 0,
             "built_in": 0, "cases": 0, "covered": 0}
    try:
        cases = st.cases(st.state()["active"])
        rules["cases"], rules["covered"] = len(cases), sum(t["covered"] for t in cases)
        d = st.load(st.state()["active"])
        rules["base"] = len(st.live(st.load("base").get("entries")))
        env = st.live(d.get("entries"))
        mine = [e for es in st.layers(d).values() for e in st.live(es)]
        rules["environment"], rules["agents"] = len(env), len(mine)
        for e in env + mine:
            rules[ORIGIN.get((e.get("provenance") or {}).get("type"), "built_in")] += 1
    except (Refused, OSError):
        pass
    return {
        "window": {"records": len(recs), "since": recs[-1]["at"] if recs else None,
                   "until": recs[0]["at"] if recs else None, "on": bool(st.state().get("feed", True))},
        "messages": {"own": len(own), "agent": sum(r["words"] == "agent" for r in recs),
                     "tool": sum(r["words"] == "tool" for r in recs)},
        "agents": len({r["agent"] for r in recs}),
        "cards": {"whole": sum(not r["left_out"] and not r["problem"] for r in own),
                  "cut": sum(bool(r["left_out"]) for r in own), "base_only": sum(r["problem"] for r in own)},
        "noticed": noticed,
        "others": {"n": len(others), "short": sum(r["form"] == "relay" for r in others),
                   "claims_you": sum(r["words"] == "agent" and clean(r["from"]) in you for r in others)},
        "decisions": {"asked": len(reqs), "open": sum(r["status"] == "open" for r in reqs), "answered": len(answered),
                      "withdrawn": sum(r["status"] == "closed" for r in reqs),
                      "via": {v: sum((r["answer"] or {}).get("via") == v for r in answered)
                              for v in ("page", "chat", "terminal")},
                      "median_minutes": round(waits[len(waits) // 2], 1) if waits else None,
                      "rules_proposed": sum(r.get("kind") == "rule" for r in reqs),
                      "rules_added": sum(r.get("kind") == "rule" and (r["answer"] or {}).get("picked") == "Add"
                                         for r in answered)},
        "rules": rules,
        "days": sorted(days.values(), key=lambda x: x["day"])[-14:],
    }


HOST, PORT = "127.0.0.1", 8765
MAX_BODY = 200_000
DEEP_BODY = "the request is nested too deeply to be read"
LOOPBACK = ("127.0.0.1", "localhost")   # the server is IPv4; an address it cannot serve is not offered


class Handler(BaseHTTPRequestHandler):
    server_version = f"Semantext/{__version__}"
    timeout = 10  # seconds; a request that stalls is dropped, not waited on forever
    store: Store  # set by make_server

    def log_message(self, fmt, *args):  # a quiet console
        pass

    def _send(self, code: int, body, ctype="application/json; charset=utf-8", extra: dict | None = None):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _own(self) -> set[str]:
        port = self.server.server_address[1]
        return {f"{h}:{port}" for h in LOOPBACK}

    def _host_ok(self) -> bool:
        """Only requests addressed to this machine's own name for the server (a DNS-rebinding guard)."""
        return (self.headers.get("Host") or "").strip() in self._own()

    def _origin_ok(self) -> bool:
        """A change is the user's act, made on their page: a browser always names the page a POST comes from, so a
        change must name this one. One from another page is refused, and so is one that names no page at all: a
        local process, not the page, which would otherwise change the rules that only the user changes. A process that
        forges the page's own name is the limit SECURITY.md states."""
        return self.headers.get("Origin") in {f"http://{h}" for h in self._own()}

    def _page_reads(self) -> bool:
        """A read only the page's own script may make (the feed: what your agents were sent, and when). It must carry
        the page's X-Semantext header, which a page on another site can send only after a preflight this server never
        grants; and a browser that names the requesting site must name this one."""
        site = self.headers.get("Sec-Fetch-Site")
        origin = self.headers.get("Origin")
        return (self.headers.get("X-Semantext") == "1" and site in (None, "same-origin")
                and (origin is None or self._origin_ok()))

    def _drain(self) -> None:
        """Read and drop a refused request's body before answering. A socket closed with unread data is reset, and
        the client can then lose the 403 before reading it (seen on Windows). A body over MAX_BODY is not read, so
        that refusal can still be reset; only an abnormal client sends one."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < n <= MAX_BODY:
            try:
                self.rfile.read(n)
            except OSError:
                pass   # a client that stalls past the timeout, or goes away, still gets the refusal (or nothing)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0:
            raise Refused("bad Content-Length")
        if n > MAX_BODY:
            raise Refused("request too large")
        try:
            return jsonread.loads(self.rfile.read(n) or b"{}")
        except jsonread.NotJSON as e:
            if e.deep:   # before, a RecursionError here left the page with no answer and the console with a traceback
                raise Refused(DEEP_BODY) from None
            raise

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "this server answers only on this machine's own address"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        st = self.store
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (paths.static_dir() / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._send(200, {**st.overview(), "version": __version__, "connections": connections(st),
                                        "you": person_names()})
            if u.path == "/api/profile":
                name = q.get("name", "")
                d = st.load(name)
                return self._send(200, {"environment": d["environment"], "entries": d.get("entries") or [],
                                        "tests": st.cases(name)})
            if u.path == "/api/card":   # the card one agent gets, for the user's or relayed words; strict: a broken
                form = "relay" if q.get("form") == "relay" else "full"   # file is refused by name, not covered over
                plan = st.plan(q.get("name", ""), form, agent=layer_for(st, q.get("agent", "")))
                card = st.render(plan)
                body = fit(card, LIMIT_BYTES - 1)
                return self._send(200, {"card": card, "form": plan["form"], "layers": sent_layers(plan["layers"], body),
                                        "bytes": len(body.encode("utf-8")), "limit": LIMIT_BYTES,
                                        "left_out": rule_lines(card) - rule_lines(body)})
            if u.path == "/api/feed":
                if not self._page_reads():
                    return self._send(403, {"error": "the feed is read only by the Semantext page itself"})
                n = max(1, min(200, int(q.get("n") or 100)))
                return self._send(200, {"on": bool(st.state().get("feed", True)), "limit": LIMIT_BYTES,
                                        "records": Feed(st.root).recent(n)})
            if u.path == "/api/source":
                return self._send(200, {"text": st.source(q.get("name", ""))})
            if u.path == "/api/models":
                return self._send(200, {"local": Store.local_models(), "chosen": st.state()["model"]})
            if u.path == "/api/suggest":
                return self._send(200, st.suggest(q.get("title", "")))
            if u.path == "/api/ideas":
                return self._send(200, {"packs": st.ideas(q.get("name", ""))})
            if u.path == "/api/inbox":
                inbox = Inbox(st.root)
                folded = inbox.requests()
                reqs = sorted(folded.values(), key=lambda r: r["id"], reverse=True)
                for r in reqs:
                    r["age"] = age(r["at"])
                    if r["status"] == "open":     # the same question, answered before: shown beside it, never used
                        e = inbox.earlier(r, folded)
                        r["earlier"] = {"id": e["id"], "answer": e["answer"], "age": age(e["answer"]["at"])} if e else None
                return self._send(200, {"open": [r for r in reqs if r["status"] == "open"],
                                        "recent": [r for r in reqs if r["status"] != "open"][:10]})
            if u.path == "/api/register":
                if not self._page_reads():
                    return self._send(403, {"error": "the register is read only by the Semantext page itself"})
                items = Inbox(st.root).search(q.get("q", ""), limit=200)
                for r in items:
                    r["age"] = age((r.get("answer") or r.get("closed") or {}).get("at") or r["at"])
                return self._send(200, {"items": items})
            if u.path == "/api/metrics":
                if not self._page_reads():
                    return self._send(403, {"error": "the counts are read only by the Semantext page itself"})
                return self._send(200, metrics(st))
            if u.path == "/api/agents":
                return self._send(200, agents_view(st))
            if u.path == "/v2":   # the page in four places, read-only on the person's own files (sources/view.py)
                return self._send(200, (paths.static_dir() / "v2.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/v2/document":   # one listed file of one listed cv/<project> folder, read (view.document)
                if not self._page_reads():
                    return self._send(403, {"error": "these reads are made only by the Semantext page itself"})
                try:
                    got = view.document(q.get("doc", ""), q.get("file", ""), home=st.root)
                except view.DocumentRefused as e:
                    return self._send(e.status, {"error": e.why})
                if got["kind"] == "diagram":   # an image the page shows through <img>, which never runs its script
                    return self._send(200, got["bytes"], "image/svg+xml",
                                      {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})
                return self._send(200, got)
            if u.path.startswith("/api/v2/"):
                if not self._page_reads():
                    return self._send(403, {"error": "these reads are made only by the Semantext page itself"})
                body = view.answer(u.path[len("/api/v2/"):], home=st.root)
                return self._send(200, body) if body is not None else self._send(404, {"error": "not found"})
            return self._send(404, {"error": "not found"})
        except (Refused, ValueError, KeyError, TypeError) as e:
            return self._send(400, {"error": str(e)})
        except OSError as e:
            return self._send(500, {"error": f"could not read your files: {e}"})

    def do_POST(self):
        if not self._host_ok():
            self._drain()
            return self._send(403, {"error": "this server answers only on this machine's own address"})
        if self.headers.get("X-Semantext") != "1" or not self._origin_ok():
            self._drain()
            return self._send(403, {"error": "changes are accepted only from the Semantext page"})
        u = urlparse(self.path)
        st = self.store
        try:
            b = self._body()
            r = {"ok": True}
            if u.path == "/api/active":
                st.set_active(b.get("name"))
            elif u.path == "/api/toggle":
                r["enabled"] = st.toggle(b.get("name"), b.get("id"))
                # switched off: the kept corrections that needed it, so the page can say what may come back
                r["uncovered"] = [] if r["enabled"] else st.depends_on(b.get("name"), b.get("id"))
            elif u.path == "/api/learn":
                r["id"] = st.learn(b.get("name"), b.get("words"), agent=b.get("agent") or None,
                                   misread=str(b.get("misread") or "") or None)
            elif u.path == "/api/agent-bind":       # the user names an agent by its folder, on their own page
                r["folder"] = str(Agents(st.root).bind(str(b.get("agent") or ""), str(b.get("folder") or "")))
            elif u.path == "/api/agent-unbind":
                r["unbound"] = Agents(st.root).unbind(str(b.get("folder") or ""))
            elif u.path == "/api/agent-name":
                Agents(st.root).rename(str(b.get("agent") or ""), str(b.get("label") or ""))
            elif u.path == "/api/undo":
                st.undo(b.get("name"), b.get("id"))
                r["uncovered"] = st.depends_on(b.get("name"), b.get("id"))
            elif u.path == "/api/undo-last":   # the newest saved version of this environment's file, and what that undid
                r["restored"] = st.undo_last(b.get("name"))
                r.update(took_off=st.last_undo.get("took_off"), kept=st.last_undo.get("kept"))
            elif u.path == "/api/feature":
                st.feature(b.get("name"), b.get("feature"), bool(b.get("on")), b.get("country", ""))
            elif u.path == "/api/source":
                st.write_source(b.get("name"), b.get("text", ""))
            elif u.path == "/api/explain":   # "Test a message", and the page's examples: nothing is written
                r.update(explain(st, b))
            elif u.path == "/api/setting":
                if b.get("key") not in ("feed", "hear_prompts") or not isinstance(b.get("on"), bool):
                    raise Refused("name a setting (feed or hear_prompts), and on as true or false")
                st.set_option(b["key"], b["on"])
            elif u.path == "/api/create":
                r["name"] = st.create(b.get("title"), b.get("picks") or [])
            elif u.path == "/api/add-suggestions":
                ids = b.get("ids")
                if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
                    raise Refused("name the suggestions to add")
                r["added"] = st.add_suggestions(b.get("name"), ids)
            elif u.path == "/api/answer":
                # Answering is the user's act: a browser always names the page it comes from, so an answer must come
                # from this page. A script without the header is refused (one that forges it is the limit SECURITY.md
                # names).
                if self.headers.get("Origin") not in {f"http://{h}" for h in self._own()}:
                    return self._send(403, {"error": "an answer is accepted only from the Semantext page"})
                rid = b.get("id")
                if not isinstance(rid, int):
                    raise Refused("name the request by its number")
                inbox, choice = Inbox(st.root), str(b.get("choice") or "")
                st.check_adoptable(inbox.get(rid), choice)
                r["request"] = inbox.answer(rid, choice, str(b.get("words") or ""), via="page")
                r["added"] = st.adopt(r["request"])   # a proposed rule the user added
            else:
                return self._send(404, {"error": "not found"})
            return self._send(200, r)
        except Refused as e:
            return self._send(400, {"error": str(e)})
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            return self._send(400, {"error": f"bad request: {e}"})
        except OSError as e:
            return self._send(500, {"error": f"could not write your files: {e}"})


class LocalServer(ThreadingHTTPServer):
    """The server, owning its port alone. On Windows, SO_REUSEADDR (which http.server turns on) lets a second socket
    bind a port that is already in use, so two servers could answer on one address. There the port is taken
    exclusively instead, and a busy port fails at bind time."""
    daemon_threads = True
    allow_reuse_address = sys.platform != "win32"

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def handle_error(self, request, client_address):
        """A browser or client that hangs up mid-reply is not a fault worth a traceback; anything else still is."""
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def make_server(store: Store, host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    if host not in LOOPBACK:
        raise Refused("Semantext serves this machine only: use 127.0.0.1 or localhost")
    handler = type("BoundHandler", (Handler,), {"store": store})
    return LocalServer((host, port), handler)


def serve(store: Store, host: str = HOST, port: int = PORT, open_browser: bool = False) -> int:
    try:
        srv = make_server(store, host, port)
    except OSError as e:
        raise Refused(f"cannot listen on {host}:{port} ({e.strerror or e}); is it already in use? Try --port {port + 1}")
    url = f"http://{host}:{srv.server_address[1]}"
    print(f"Semantext {__version__} on {url} (this machine only). Ctrl+C stops it.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0
