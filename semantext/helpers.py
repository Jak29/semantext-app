"""Long-lived helpers: sub-agents an agent starts, keeps, renames and retires for itself. You never manage them.

A helper is worth keeping only for a long-lived part of the work whose kept context is reused, so starting one says what
context it keeps; anything else is a job for a fresh agent. Every hand-off is logged: a prediction before the job, its tokens
after. A helper's work is taken in only once an agent other than the helper and its owner has checked it (attacks.py), or
with the reason it was not, which stays on the record. A helper idle for a week, or dearer per job than the owner's fresh
agents, is flagged, and retiring one says where its notes are.

Only a helper's owner can change it, and the page only reads. Nothing here reaches your inbox or asks you for anything.

Semantext starts no agent: it keeps the roster and the session to resume, and your tool does the starting. A name is known as
agents.py knows it, so this keeps honest agents honest: anything that can write to your home could forge it. Tokens are
what the agent reports.

The file is append-only, <home>/helpers.jsonl, kept as the board's is.
"""
from __future__ import annotations

from datetime import datetime

from .attacks import Attacks
from .board import Board, _line, _moment, shown
from .store import Refused

IDLE_DAYS = 7
MAX_TEXT = 600
MAX_TOKENS = 10 ** 13   # far past any job: a number too big to average must never reach the file
FRESH = "(fresh agent)"   # a hand-off to a fresh agent, logged the same way: what a helper's cost is compared with


class Helpers(Board):
    NAME = "helpers"
    TYPES = ("start", "rename", "retire", "job", "done", "take")

    @staticmethod
    def _whole(e: dict) -> bool:
        return True   # each kind's fields are read with care in state()

    def state(self) -> tuple[dict, dict]:
        """({(owner key, name): helper}, {job id: job}), folded from the events. Only a line from the owner counts."""
        helpers: dict[tuple[str, str], dict] = {}
        jobs: dict[int, dict] = {}
        for e in self.events():
            kind, key, name = e["type"], e["key"], str(e.get("name") or "").casefold()
            h = helpers.get((key, name))
            if kind == "start" and isinstance(e.get("name"), str):
                if h is None or h["retired"]:
                    helpers[(key, name)] = {**e, "retired": None, "jobs": [], "names": {name}}
            elif kind == "rename" and h and not h["retired"] and isinstance(e.get("to"), str):
                helpers.pop((key, name))
                h["names"].add(e["to"].casefold())   # the one set its jobs hold: they see every later name too
                helpers[(key, e["to"].casefold())] = {**h, "name": e["to"]}
            elif kind == "retire" and h and not h["retired"]:
                h["retired"] = e
            elif kind == "job" and (h and not h["retired"] or e.get("fresh") is True):
                # every name the helper has had: a rename does not make it someone else
                job = {**e, "owner": key, "tokens": None, "outcome": None, "taken": None, "names": h["names"] if h else set()}
                jobs[e["id"]] = job
                if h:
                    h["jobs"].append(job)
            elif kind in ("done", "take") and type(e.get("job")) is int and e["job"] in jobs and jobs[e["job"]]["owner"] == key:
                job = jobs[e["job"]]
                if kind == "done" and job["tokens"] is None and type(e.get("tokens")) is int and 0 <= e["tokens"] <= MAX_TOKENS:
                    job["tokens"], job["outcome"] = e["tokens"], e.get("outcome")
                elif kind == "take" and job["taken"] is None and job["tokens"] is not None:
                    job["taken"] = e
        return helpers, jobs

    def _mine(self, who, name: str) -> dict:
        h = self.state()[0].get((who.key, str(name).casefold()))
        if h is None or h["retired"]:
            raise Refused(f"you have no helper called {name}; only its owner can change a helper")
        return h

    # ---- start, rename, retire --------------------------------------------------------------------------------
    def start(self, who, name: str, keeps: str, session: str = "") -> dict:
        name = _line(name, "a helper's name", 60)
        keeps = _line(keeps, "what kept context earns it its place (--keeps); with none, use a fresh agent", MAX_TEXT)
        session = _line(session, "a session", 200, required=False)
        self._clean(name, keeps, session)
        if name.casefold() == FRESH:
            raise Refused("that name is kept for fresh agents")
        h = self.state()[0].get((who.key, name.casefold()))
        if h and not h["retired"]:
            raise Refused(f"you already have a helper called {name}")
        return self._add({"type": "start", **self._sender(who), "name": name, "keeps": keeps, "session": session})

    def rename(self, who, name: str, to: str) -> dict:
        self._mine(who, name)
        to = _line(to, "the new name", 60)
        self._clean(to)
        if to.casefold() == FRESH:
            raise Refused("that name is kept for fresh agents")
        h = self.state()[0].get((who.key, to.casefold()))
        if h and not h["retired"] and to.casefold() != str(name).casefold():   # a change of case alone is the same helper
            raise Refused(f"you already have a helper called {to}")
        return self._add({"type": "rename", **self._sender(who), "name": name, "to": to})

    def retire(self, who, name: str, notes: str) -> dict:
        self._mine(who, name)
        notes = _line(notes, "where its notes are kept (--notes)", MAX_TEXT)
        self._clean(notes)
        return self._add({"type": "retire", **self._sender(who), "name": name, "notes": notes})

    # ---- hand-offs --------------------------------------------------------------------------------------------
    def job(self, who, name: str | None, predict: str) -> dict:
        """Log a hand-off before it runs: to a helper by name, or, with no name, to a fresh agent."""
        predict = _line(predict, "a prediction, written before the job (--predict)", MAX_TEXT)
        self._clean(predict)
        if name:
            h = self._mine(who, name)
            return self._add({"type": "job", **self._sender(who), "name": h["name"], "predict": predict})
        return self._add({"type": "job", **self._sender(who), "name": FRESH, "fresh": True, "predict": predict})

    def _job(self, who, jid: int) -> dict:
        if type(jid) is not int:
            raise Refused("name the job by its number")
        job = self.state()[1].get(jid)
        if job is None or job["owner"] != who.key:
            raise Refused(f"you have no job #{jid}; only whoever handed it off can close it")
        return job

    def done(self, who, jid: int, tokens: int, outcome: str = "") -> dict:
        job = self._job(who, jid)
        if job["tokens"] is not None:
            raise Refused(f"job #{jid} is already closed")
        if type(tokens) is not int or not 0 <= tokens <= MAX_TOKENS:
            raise Refused("say the job's tokens as a whole number (--tokens)")
        outcome = _line(outcome, "an outcome", MAX_TEXT, required=False)
        self._clean(outcome)
        return self._add({"type": "done", **self._sender(who), "job": jid, "tokens": tokens, "outcome": outcome})

    def take(self, who, jid: int, attack: int | None = None, unreviewed: str = "") -> dict:
        """Take a job's work in: checked by a claim tied to this job that survived, judged by neither the helper, under
        any name it has had, nor its owner; or with the reason it was not checked, which stays on the record."""
        job = self._job(who, jid)
        if job["tokens"] is None:
            raise Refused(f"job #{jid} is not closed yet: close it with its tokens first")
        if job["taken"] is not None:
            raise Refused(f"job #{jid} was already taken in")
        unreviewed = _line(unreviewed, "why it was not checked", MAX_TEXT, required=False)
        self._clean(unreviewed)
        if attack is None:
            if not unreviewed:
                raise Refused("work is taken in once a fresh reviewer has checked it (--attack), or say why it was not (--unreviewed)")
            return self._add({"type": "take", **self._sender(who), "job": jid, "attack": None, "unreviewed": unreviewed})
        claim = Attacks(self.path.parent).get(attack)
        if claim.get("job") != jid:
            raise Refused(f"claim #{attack} does not check job #{jid}; put one up with `semantext attack ask ... --job {jid}`")
        builders = {*job["names"], str(job.get("name")).casefold(), str(who.name).casefold()}
        fair = [v for v in claim["verdicts"] if v["verdict"] == "survived" and v["key"] != who.key and str(v.get("from")).casefold() not in builders]
        if claim["state"] != "survived" or not fair:
            raise Refused(f"claim #{attack} has not survived an attack by someone other than the helper and you; it stands at {claim['state']}")
        return self._add({"type": "take", **self._sender(who), "job": jid, "attack": attack, "unreviewed": ""})


    def report(self, owner: str | None = None, now: datetime | None = None) -> list[dict]:
        """What report() says, with the claims it needs read here."""
        try:
            claims = {c["id"]: c for c in Attacks(self.path.parent).all()}
        except OSError:   # it costs only this one flag, said on each helper that was taken in on a check
            claims = None
        rows = report(*self.state(), owner=owner, now=now, claims=claims or {})
        if claims is None:
            for r in rows:
                r["flags"].append("the attacks file could not be read, so a check broken since would not show here")
        return rows


def _days(at, now: datetime) -> float | None:
    moment = _moment(at)
    return (now - moment).total_seconds() / 86400 if moment else None


def report(helpers: dict, jobs: dict, owner: str | None = None, now: datetime | None = None, claims: dict | None = None) -> list[dict]:
    """Each helper still kept, with its metrics, and what they say. The flags advise; retiring is its owner's call."""
    now = now or datetime.now().astimezone()
    out = []
    for (key, _), h in helpers.items():
        if h["retired"] or (owner is not None and key != owner):
            continue
        closed = [j for j in h["jobs"] if j["tokens"] is not None]
        fresh = [j["tokens"] for j in jobs.values() if j["owner"] == key and j.get("fresh") and j["tokens"] is not None]
        average = sum(j["tokens"] for j in closed) / len(closed) if closed else None
        cheap = sum(fresh) / len(fresh) if fresh else None
        last = max((_days(j.get("at"), now) for j in h["jobs"] if _days(j.get("at"), now) is not None), default=_days(h.get("at"), now))
        flags = []
        if last is not None and last >= IDLE_DAYS:
            flags.append(f"idle {int(last)} days: retire it, and keep its notes")
        if average is not None and cheap is not None and average > cheap:
            flags.append(f"dearer than your fresh agents ({int(average)} tokens a job against {int(cheap)}): retire it, and keep its notes")
        for j in h["jobs"]:   # taken in, and the check has since been broken: the work is in, and that must be seen
            attack = (j["taken"] or {}).get("attack")
            if attack is not None and (claims or {}).get(attack, {}).get("state") == "killed":
                flags.append(f"job #{j['id']} was taken in on claim #{attack}, which has since been killed: look at that work again")
        out.append({"name": shown(h["name"]), "key": key, "owner": shown(h.get("from")), "how": h.get("how"), "keeps": shown(h.get("keeps")), "session": shown(h.get("session")),
                    "jobs": len(h["jobs"]), "closed": len(closed), "tokens": sum(j["tokens"] for j in closed),
                    "average": average, "fresh_average": cheap, "idle_days": None if last is None else int(last),
                    "unreviewed": sum(1 for j in h["jobs"] if j["taken"] and not j["taken"].get("attack")), "flags": flags})
    return sorted(out, key=lambda r: str(r["name"]).casefold())


def helper_row(r: dict, session: bool = True) -> str:
    bits = [f"{r['jobs']} job{'s' if r['jobs'] != 1 else ''}", f"{r['tokens']} tokens"]
    if r["unreviewed"]:
        bits.append(f"{r['unreviewed']} taken in unchecked")
    if session and r["session"]:
        bits.append(f"resume: {shown(r['session'])}")
    flags = "".join(f"\n    {f}" for f in r["flags"])
    return f"{' '.join(shown(r['name']).split())}: {' · '.join(bits)}{flags}"


__all__ = ["FRESH", "Helpers", "IDLE_DAYS", "helper_row", "report"]
