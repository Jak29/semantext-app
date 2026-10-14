"""The store: your environments as plain rule files, and every change to them, undoable.

An environment is one YAML file, profiles/<name>/SEMANTICS.yaml. "base" holds the rules every environment shares;
"default" is where everyone starts. Every write first copies the previous version into history/, so nothing is ever
lost: undoing a rule archives it in its file, and undo-last restores the previous version of the whole file.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from . import paths

NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,30}")   # always used with fullmatch: "$" would also allow a final "\n"
# The base rules on every relay card, by their ids as well as by their `always` mark: a mark is an edit away, and the
# rule that an act waits for the user's word must never fall off the card that relayed words get.
FLOOR = ("base.irreversible-needs-your-word", "base.relayed-words-are-information")
MAX_CASE = 1000   # the longest misread message kept as a test
# An agent's name, as agents.py makes it: the key of its own layer of rules in an environment file.
AGENT_NAME_RE = re.compile(r"[a-z0-9][a-z0-9@._-]{0,59}")
LAYER_NOTE = ("These are this agent's own rules. They add to the rules above and never override them: where one seems "
              "to conflict with a rule above, the rule above wins.")


def agent_slug(agent: str) -> str:
    """An agent's name as part of a rule id: claude-code@app becomes claude-code-app."""
    return re.sub(r"[^a-z0-9-]+", "-", str(agent).lower()).strip("-")[:40] or "agent"
# Names Windows reserves for devices: a folder with one of them is unreliable there, so no platform makes one.
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def valid_name(name) -> bool:
    return isinstance(name, str) and bool(NAME_RE.fullmatch(name)) and name not in RESERVED
OLLAMA_MANIFESTS = Path.home() / ".ollama" / "models" / "manifests" / "registry.ollama.ai" / "library"

# The switches on the page. Each one is a rule, so the card stays the single place the AI reads.
FEATURES = {
    "tone": ("Match my tone and phrasing so you feel familiar, without copying me exactly.", "adaptive"),
    "jokes": ("Humour is welcome: keep up with current meme culture, and never joke at my expense.", "adaptive"),
    "news": ("Bring in current news when it is relevant, focused on {country}. (A news source is not connected yet.)",
             "stationary"),
    "inbox": ("When you need my decision or permission, file it with `semantext ask` (a title, why it needs me, the "
              "options and your recommendation) and keep working on what does not need it. Act on it only after my "
              "answer reaches you. Never answer your own request; only my answer counts.", "stationary"),
}


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


_STAMP_LOCK = threading.Lock()
_last_stamp: list = [None]


def stamp() -> str:
    """Now, to the microsecond, and never the same twice in one process. A file named by it (a backup, a kept version)
    never overwrites the one before: on some clocks (Windows with Python 3.10) two calls in a row read the same
    microsecond, so the second is moved on by one, which keeps the names in the order they were made."""
    with _STAMP_LOCK:
        t = datetime.now()
        if _last_stamp[0] is not None and t <= _last_stamp[0]:
            t = _last_stamp[0] + timedelta(microseconds=1)
        _last_stamp[0] = t
    return t.strftime("%Y%m%d-%H%M%S-%f")


def dump(data: dict) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110)


class Refused(ValueError):
    """A request the store will not carry out, with the reason shown to the user."""


def check_environment(d, where: str) -> None:
    """The shape every rule file needs, checked when it is read and before the editor saves one: a hand edit that went
    wrong is refused in one line naming the file and the rule, never a traceback later (in the hook, on every
    prompt)."""
    if not isinstance(d, dict) or not isinstance(d.get("environment"), dict) or not d["environment"].get("id"):
        raise Refused(f"{where} is not a Semantext rule file (it needs an 'environment' section with an id)")
    if not isinstance(d.get("entries") or [], list):
        raise Refused(f"{where}: 'entries' must be a list")
    agents = d.get("agents")
    if agents is not None and (not isinstance(agents, dict) or not all(
            isinstance(k, str) and AGENT_NAME_RE.fullmatch(k) and isinstance(v, dict)
            and isinstance(v.get("entries") or [], list) for k, v in agents.items())):
        raise Refused(f"{where}: 'agents' must map each agent's name, as `semantext agents` shows it, to its own "
                      f"entries")
    layered = [x for v in (agents or {}).values() for x in (v.get("entries") or [])]
    for n, x in enumerate([*(d.get("entries") or []), *layered], 1):
        if not isinstance(x, dict):
            raise Refused(f"{where}: rule {n} is not a rule (each one starts '- id:', with its statement below)")
        rid = x.get("id")
        if not isinstance(rid, str) or not rid.strip():
            raise Refused(f"{where}: rule {n} has no id")
        if not isinstance(x.get("statement"), str) or not x["statement"].strip():
            raise Refused(f"{where}: rule {rid} has no statement, or one that is not text (put it in quotes)")
    # Corrections kept as tests (see Store.cases): each one the message that was misread, and the rules it needs.
    if not isinstance(d.get("tests") or [], list):
        raise Refused(f"{where}: 'tests' must be a list")
    for n, t in enumerate(d.get("tests") or [], 1):
        if not isinstance(t, dict) or not isinstance(t.get("message"), str) or not t["message"].strip():
            raise Refused(f"{where}: test {n} has no message (each one starts '- case:', with the misread message)")
        if not isinstance(t.get("rules") or [], list) or not all(isinstance(r, str) for r in t.get("rules") or []):
            raise Refused(f"{where}: test {n}'s rules must be a list of rule ids")


class Store:
    def __init__(self, root: Path | None = None, suggestions: Path | None = None):
        self.root = Path(root) if root else paths.home()
        self.profiles_dir = self.root / "profiles"
        self.history_dir = self.root / "history"
        self.state_path = self.root / "state.json"
        self.suggest_dir = Path(suggestions) if suggestions else paths.suggestions_dir()
        self.state_problem: str | None = None   # set by state() when state.json cannot be read
        self.last_undo: dict = {}               # what undo_last took off, and where the version it replaced is kept

    @classmethod
    def open(cls, root: Path | None = None) -> "Store":
        """The store at root (or your home), created with the starting environments if it is new."""
        return cls(paths.ensure_home(root))

    # ---- files ------------------------------------------------------------------------------------------------
    def path(self, name: str) -> Path:
        if not valid_name(name):
            raise Refused(f"not an environment name: {name!r}")
        p = self.profiles_dir / name / "SEMANTICS.yaml"
        if not p.is_file():
            raise Refused(f"no such environment: {name}")
        return p

    def load(self, name: str) -> dict:
        """The environment's rule file, or a refusal naming the file if it is not one (for example after a hand
        edit went wrong): never a traceback."""
        p = self.path(name)
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            raise Refused(f"{p} is not saved as UTF-8 text; save it again as UTF-8")
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            at = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            raise Refused(f"{p} is not valid YAML{at} ({getattr(e, 'problem', None) or str(e).splitlines()[0]}). Fix "
                          f"that line; or `semantext undo --last --env {name}` restores the last version Semantext "
                          f"saved, and keeps this one in history/")
        check_environment(d, str(p))
        return d

    def _keep(self, name: str) -> None:
        """The previous version goes to history/ before any write: undo at the file level, and nothing lost."""
        self.history_dir.mkdir(parents=True, exist_ok=True)
        mark = stamp()
        shutil.copyfile(self.path(name), self.history_dir / f"{name}-{mark}.yaml")

    def save(self, name: str, data: dict) -> None:
        self._keep(name)
        self.path(name).write_text(dump(data), encoding="utf-8")

    def names(self) -> list[str]:
        """Default first, then your own environments by name, then base (shared, never shown as an environment)."""
        found = {p.parent.name for p in self.profiles_dir.glob("*/SEMANTICS.yaml") if valid_name(p.parent.name)}
        own = sorted(n for n in found if n not in ("default", "base"))
        return (["default"] if "default" in found else []) + own + (["base"] if "base" in found else [])

    def strays(self) -> list[str]:
        """Folders in profiles/ that are not environments Semantext can use (a copy made in a file manager, say):
        left alone, and reported by `semantext doctor`."""
        if not self.profiles_dir.is_dir():
            return []
        return sorted(p.name for p in self.profiles_dir.iterdir()
                      if p.is_dir() and not (valid_name(p.name) and (p / "SEMANTICS.yaml").is_file()))

    def title(self, name: str) -> str:
        return str(self.load(name)["environment"].get("title") or name.title())

    def resolve(self, text: str) -> str:
        """An environment's name, from its name or its title, ignoring case: "Gardening" finds gardening."""
        text = " ".join(str(text or "").split())
        if text.lower() == "base":
            return "base"
        names = [n for n in self.names() if n != "base"]
        if text in names:
            return text
        titles = {n: self.title(n).lower() for n in names}
        hits = [n for n in names if n == text.lower() or titles[n] == text.lower()]
        if len(hits) == 1:
            return hits[0]
        if hits:
            raise Refused(f"{text!r} is the title of {len(hits)} environments; use a name: {', '.join(hits)}")
        # A near miss only: "gardenin" finds gardening, but "Kayaking" does not suggest baking.
        close = difflib.get_close_matches(text.lower(), names + list(titles.values()), n=1, cutoff=0.8)
        hint = ""
        if close:
            hint = f"; did you mean {next((n for n in names if close[0] in (n, titles[n])), close[0])}?"
        raise Refused(f"no environment called {text!r}{hint} (see them with: semantext env list)")

    # ---- state ------------------------------------------------------------------------------------------------
    def state(self) -> dict:
        """The settings and the log. A state.json that cannot be read (empty after a crash, say) holds settings only,
        so the defaults stand in, and `state_problem` names the file; the next change keeps a copy of it first."""
        s = {"active": "default", "model": None, "hear_prompts": False, "feed": True, "log": [], "pending": []}
        self.state_problem = None
        if self.state_path.exists():
            try:
                got = json.loads(self.state_path.read_text(encoding="utf-8"))
                if not isinstance(got, dict):
                    raise ValueError("it does not hold settings")
                s.update(got)
            except (ValueError, OSError) as e:
                self.state_problem = (f"{self.state_path} could not be read ({e}), so the settings are at their "
                                      f"defaults until it is fixed or replaced")
        s["log"] = s["log"] if isinstance(s.get("log"), list) else []
        s["pending"] = s["pending"] if isinstance(s.get("pending"), list) else []
        if not valid_name(s["active"]) or not (self.profiles_dir / s["active"] / "SEMANTICS.yaml").is_file():
            s["active"] = "default"   # an environment that no longer exists falls back to Default
        return s

    def put_state(self, s: dict) -> None:
        """Written whole or not at all: to a temporary file, then put in place, so a crash never leaves it empty. An
        unreadable file it replaces is kept beside it first."""
        s["log"] = s["log"][-60:]
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_path.exists():
            try:
                readable = isinstance(json.loads(self.state_path.read_text(encoding="utf-8")), dict)
            except (ValueError, OSError):
                readable = False
            if not readable:
                mark = stamp()
                shutil.copyfile(self.state_path, self.state_path.with_name(f"state-unreadable-{mark}.json"))
        tmp = self.state_path.with_name(f"state-{os.getpid()}.tmp")
        tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
        for attempt in range(20):   # Windows refuses the swap while another process is reading the file
            try:
                os.replace(tmp, self.state_path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)

    def log(self, what: str) -> None:
        s = self.state()
        s["log"].append({"when": now(), "what": what})
        self.put_state(s)

    def set_option(self, key: str, value) -> None:
        if key not in ("hear_prompts", "feed"):
            raise Refused(f"no such setting: {key}")
        if not isinstance(value, bool):
            raise Refused(f"{key} is on or off")
        s = self.state()
        s[key] = value
        self.put_state(s)
        self.log(f"Set {key} to {value}")

    # ---- reading ----------------------------------------------------------------------------------------------
    @staticmethod
    def live(entries):
        return [e for e in entries or [] if e.get("enabled", True) and not e.get("archived")]

    @staticmethod
    def _line(x: dict) -> str:
        """One rule as the card shows it, with a mark when it is not the user's own rule as written."""
        p = x.get("provenance") or {}
        mark = (" (learned)" if p.get("type") == "LEARNED" else
                f" (proposed by {p.get('by') or 'an agent'}, added by the user: not the user's own words)"
                if p.get("type") == "PROPOSED" else "")
        return f"- {x.get('id', '?')}: {' '.join(str(x.get('statement', '')).split())}{mark}"

    def plan(self, name: str, form: str = "full", agent: str | list | None = None) -> dict:
        """What the card holds, layer by layer: the shared base, the environment, then the agent's own rules. card()
        writes it out; the hook and the page report it, so what they show is what was built.

        form "relay" is for a prompt that is not the user's own message (another agent's, a tool's notice): only the
        rules marked relay, and those marked always, which every card carries. The short card needs its floor from the
        base itself: if the base marks no rule always (a home made before the marks existed, or a base whose marks
        were taken off), or no file marks a relay rule, the full card is given, so the short card never drops a rule
        the user relies on, whatever an environment marks."""
        chain = ["base", name] if name != "base" else ["base"]
        # An agent's own rules: its layer, and any carried to it (a list of names, its own first; see agents.own_names).
        names = [agent] if isinstance(agent, str) else list(agent or [])
        layers = self.layers(self.load(name)) if names and name != "base" else {}
        own = [x for n in dict.fromkeys(names) for x in self.live(layers.get(n) or [])]
        agent = names[0] if names else None
        kind = lambda n: "base" if n == "base" else "environment"   # noqa: E731
        if form == "relay":
            on_floor = lambda x: x.get("always") or x.get("id") in FLOOR   # noqa: E731  by mark, or by id
            floor = [x for x in self.live(self.load("base").get("entries")) if on_floor(x)]
            picked = [(n, [x for x in self.live(self.load(n).get("entries")) if x.get("relay") or on_floor(x)])
                      for n in chain]
            picked.append((agent, [x for x in own if x.get("relay") or x.get("always")]))
            if floor and any(x.get("relay") for _, xs in picked for x in xs):
                return {"form": "relay", "environment": name, "title": self.title(name), "agent": agent,
                        "layers": [{"layer": kind(n) if i < len(chain) else "agent", "name": n, "rules": xs}
                                   for i, (n, xs) in enumerate(picked) if xs]}
        title = self.title(name)   # read first, as the card always has: with two broken files, it names this one
        out = []
        for n in chain:
            d = self.load(n)
            e = d["environment"]
            out.append({"layer": kind(n), "name": n, "rules": self.live(d.get("entries")),
                        "heading": f"{e.get('title', e['id'])} {e.get('version', '')} "
                                   f"({str(e.get('scope', n)).split('.')[0]})",
                        "tests": len(d.get("tests") or [])})
        if own:   # last, so the shared rules come first and are never crowded out by one agent's own
            out.append({"layer": "agent", "name": agent, "rules": own})
        return {"form": "full", "environment": name, "title": title, "agent": agent, "layers": out}

    def render(self, plan: dict) -> str:
        """The card's text, from its plan."""
        if plan["form"] == "relay":
            return "\n".join([
                f"# Semantext: this prompt is NOT the user's own message ({plan['title']} environment)",
                "It comes from another agent, a tool or a notice. Only the rules for relayed words, and the ones",
                "that always apply, are shown here; the full card comes with the user's own messages.", ""]
                + [f"- {x.get('id', '?')}: {' '.join(str(x.get('statement', '')).split())}"
                   for layer in plan["layers"] for x in layer["rules"]])
        lines = [f"# Semantext: standing rules for reading this user ({plan['title']} environment)",
                 "Follow these rules when you read the user's messages, unless a message itself says otherwise."]
        for layer in plan["layers"]:
            if layer["layer"] == "agent":
                lines += ["", f"## For {layer['name']} only", LAYER_NOTE] + [self._line(x) for x in layer["rules"]]
            else:
                lines += ["", f"## {layer['heading']}"] + [self._line(x) for x in layer["rules"]]
                n = layer.get("tests") or 0
                if n:   # the rules are grounded in the user's own corrections, and the AI is told how many
                    lines.append(f"  ({n} of the user's corrections {'is' if n == 1 else 'are'} kept as tests for "
                                 f"these rules: the message an AI misread, and the rule that reads it right)")
        return "\n".join(lines)

    def card(self, name: str, form: str = "full", agent: str | list | None = None) -> str:
        """The card the AI receives: a header, the shared base rules, the environment's own rules, then the agent's
        (see plan)."""
        return self.render(self.plan(name, form, agent))

    def served(self, name: str, form: str = "full", agent: str | list | None = None) -> tuple[str, dict]:
        """The card as the hook and the MCP server hand it out, and its plan. If the environment's file cannot be
        read, the AI still gets the base rules, with one line naming the file and the problem; if the base cannot be
        read either, that line alone. `semantext card` refuses instead, so the person sees the problem plainly."""
        self.state()
        head = f"Semantext: {self.state_problem}.\n\n" if self.state_problem else ""
        try:
            p = self.plan(name, form, agent=agent)
            return head + self.render(p), {**p, "problem": bool(head)}
        except (Refused, OSError) as e:
            problem = f"Semantext: {e}. Until it is fixed, only the base rules are shown."
        try:
            p = self.plan("base", form)
            return head + problem + "\n\n" + self.render(p), {**p, "environment": name, "problem": True}
        except (Refused, OSError) as e:
            return (head + problem + f" The base rules could not be read either: {e}.",
                    {"form": form, "environment": name, "title": name, "agent": None, "layers": [], "problem": True})

    def served_card(self, name: str, form: str = "full", agent: str | list | None = None) -> str:
        """The card's text as served (see served)."""
        return self.served(name, form, agent)[0]

    def overview(self) -> dict:
        s = self.state()
        out, problems = [], []
        for n in self.names():
            try:
                d = self.load(n)
            except (Refused, OSError) as e:   # one broken file never takes the others, or the page, down with it
                problems.append({"name": n, "problem": str(e)})
                continue
            live = self.live(d.get("entries"))
            out.append({"name": n, "title": d["environment"].get("title", n.title()),
                        "scope": d["environment"].get("scope", ""), "rules": len(live),
                        "learned": sum(1 for x in live if (x.get("provenance") or {}).get("type") == "LEARNED"),
                        "features": [k for k in FEATURES if any(x["id"] == f"feature.{k}" for x in live)]})
        return {"active": s["active"], "model": s["model"], "feed": bool(s.get("feed", True)),
                "hear_prompts": bool(s.get("hear_prompts")), "profiles": out, "log": s["log"][-25:][::-1],
                "pending": s["pending"], "problems": problems + ([{"name": "state.json", "problem": self.state_problem}]
                                                                 if self.state_problem else [])}

    # ---- writes -----------------------------------------------------------------------------------------------
    def layers(self, d: dict) -> dict[str, list]:
        """An environment's agent layers: {agent name: its own entries}. A layer is served to that agent only."""
        a = d.get("agents")
        if not isinstance(a, dict):
            return {}
        return {k: (v.get("entries") or []) for k, v in a.items() if isinstance(v, dict)}

    def every_entry(self, d: dict) -> list:
        """The environment's rules and every agent layer's, together: one id space."""
        return [*(d.get("entries") or []), *(e for es in self.layers(d).values() for e in es)]

    def _entry(self, d: dict, rule_id: str) -> dict:
        for x in self.every_entry(d):
            if isinstance(x, dict) and x.get("id") == rule_id:
                return x
        raise Refused(f"no rule {rule_id!r} in this environment")

    def set_active(self, name: str) -> None:
        self.path(name)
        if name == "base":
            raise Refused("base is shared by every environment; pick an environment")
        s = self.state()
        s["active"] = name
        self.put_state(s)
        self.log(f"Switched to the {self.title(name)} environment")

    # ---- new environments, from suggestions ------------------------------------------------------------------
    def packs(self) -> list[dict]:
        return [yaml.safe_load(p.read_text(encoding="utf-8")) for p in sorted(self.suggest_dir.glob("*.yaml"))]

    def suggest(self, title: str) -> dict:
        """Suggested rules for an environment called `title`. A pack matches when a word of the name is one of its
        keywords (or shares its first four letters: 'studies' finds 'study'). Matched packs offer all their rules,
        ticked; with no match, one rule from each pack is offered as an idea, unticked."""
        words = set(re.findall(r"[a-z]+", (title or "").lower()))
        packs = self.packs()

        def hit(p):
            keys = [str(k).lower() for k in p["environment"].get("keywords") or []]
            return bool(words & set(keys)) or any(len(w) >= 4 and len(k) >= 4 and w[:4] == k[:4]
                                                  for w in words for k in keys)
        matched = [p for p in packs if hit(p)]
        chosen = matched or packs
        rules = []
        for p in chosen:
            env = p["environment"]
            for e in (p.get("entries") or [])[: None if matched else 1]:
                rules.append({"pack": env["id"], "pack_title": env.get("title", env["id"]), "id": e["id"],
                              "statement": e["statement"], "mode": e.get("mode", "stationary"),
                              "ticked": bool(matched)})
        return {"matched": bool(matched),
                "packs": [p["environment"].get("title", p["environment"]["id"]) for p in chosen], "rules": rules}

    def create(self, title: str, picks: list) -> str:
        """A new environment, named by you, holding the suggested rules you kept. Never overwrites one."""
        title = (title or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 '\-]{0,39}", title):
            raise Refused("name it with letters, numbers and spaces, up to 40 characters")
        # A title already in use gets a number, so the switcher never shows two the same: Cooking, then Cooking 2.
        taken = {self.title(n).lower() for n in self.names() if n != "base"}
        if title.lower() in taken:
            k = 2
            while f"{title} {k}".lower() in taken:
                k += 1
            title = f"{title} {k}"
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:28] or "environment"
        if not slug[0].isalpha():
            slug = "e-" + slug
        # Before the taken-name check: on Windows a reserved name such as "nul" reads as an existing folder.
        if slug in RESERVED:
            raise Refused(f"{title!r} is a name Windows reserves for a device; pick another")
        stem, n = slug, 2
        while (self.profiles_dir / slug).exists() or slug == "base":
            slug, n = f"{stem}-{n}", n + 1
        if not valid_name(slug):
            raise Refused("that name cannot be used")
        index = {(p["environment"]["id"], e["id"]): e for p in self.packs() for e in p.get("entries") or []}
        entries, seen = [], set()
        for pk in picks or []:
            key = (pk.get("pack"), pk.get("id"))
            if key not in index:
                raise Refused(f"no such suggestion: {key[1]}")
            if key in seen:
                continue
            seen.add(key)
            e = index[key]
            entries.append({"id": f"{slug}.{e['id'].split('.', 1)[-1]}", "kind": "rule", "statement": e["statement"],
                            "applies_when": e.get("applies_when", ""), "mode": e.get("mode", "stationary"),
                            "enabled": True,
                            "provenance": {"type": "SUGGESTED", "pack": key[0], "from": key[1], "when": now()}})
        env = {"environment": {"id": slug, "version": "0.1.0", "status": "candidate", "owner": "you", "title": title,
                               "scope": f"Made for {title}" + (f", from {len(entries)} suggested rules."
                                                               if entries else "."),
                               "inherits": ["base@0.1.0"]},
               "entries": entries, "tests": []}
        (self.profiles_dir / slug).mkdir(parents=True)
        (self.profiles_dir / slug / "SEMANTICS.yaml").write_text(dump(env), encoding="utf-8")
        s = self.state()
        s["active"] = slug
        self.put_state(s)
        self.log(f"Made the {title} environment, with {len(entries)} suggested rule{'s' if len(entries) != 1 else ''}")
        return slug

    def ideas(self, name: str) -> list[dict]:
        """Every pack's suggested rules, each marked with whether this environment already holds it."""
        have = {x.get("id") for x in self.load(name).get("entries") or []}
        return [{"pack": p["environment"]["id"], "title": p["environment"].get("title", p["environment"]["id"]),
                 "rules": [{"id": e["id"], "statement": e["statement"], "mode": e.get("mode", "stationary"),
                            "held": f"{name}.{e['id'].split('.', 1)[-1]}" in have} for e in p.get("entries") or []]}
                for p in self.packs()]

    def add_suggestions(self, name: str, ids: list[str]) -> list[str]:
        """Add suggested rules, from any pack, to an environment that already exists. A rule it already holds is
        skipped. Returns the ids of the rules added."""
        d = self.load(name)
        d["entries"] = d.get("entries") or []
        index = {e["id"]: (p["environment"]["id"], e) for p in self.packs() for e in p.get("entries") or []}
        missing = [i for i in ids if i not in index]
        if missing:
            raise Refused(f"no such suggestion: {', '.join(missing)} (see them with: semantext env ideas)")
        have = {x.get("id") for x in d["entries"]}
        added = []
        for i in dict.fromkeys(ids):
            pack, e = index[i]
            rid = f"{name}.{i.split('.', 1)[-1]}"
            if rid in have:
                continue
            d["entries"].append({"id": rid, "kind": "rule", "statement": e["statement"],
                                 "applies_when": e.get("applies_when", ""), "mode": e.get("mode", "stationary"),
                                 "enabled": True, "provenance": {"type": "SUGGESTED", "pack": pack, "from": i,
                                                                 "when": now()}})
            have.add(rid)
            added.append(rid)
        if added:
            self.save(name, d)
            self.log(f"Added {len(added)} suggested rule{'s' if len(added) != 1 else ''} to {self.title(name)}")
        return added

    def toggle(self, name: str, rule_id: str) -> bool:
        d = self.load(name)
        x = self._entry(d, rule_id)
        x["enabled"] = not x.get("enabled", True)
        self.save(name, d)
        self.log(f"Turned {'on' if x['enabled'] else 'off'} {rule_id} in {self.title(name)}")
        return x["enabled"]

    def pin(self, name: str, rule_id: str) -> str:
        d = self.load(name)
        x = self._entry(d, rule_id)
        x["mode"] = "adaptive" if x.get("mode") == "stationary" else "stationary"
        self.save(name, d)
        self.log(f"Made {rule_id} {x['mode']} in {self.title(name)}")
        return x["mode"]

    def learn(self, name: str, words: str, provenance: dict | None = None, applies_when: str = "",
              agent: str | None = None, misread: str | None = None) -> str:
        """Your correction becomes a rule, with your exact words kept beside it. A rule an agent proposed, which you
        added (see adopt), carries that provenance instead. With `agent`, the rule goes into that agent's own layer
        of this environment, served to that agent only. With `misread`, the message your AI got wrong is kept too,
        as a test of the new rule (see cases)."""
        words = (words or "").strip()
        if not words:
            raise Refused("nothing to learn: the correction is empty")
        if len(words) > 400:
            raise Refused("keep a correction under 400 characters")
        misread = str(misread or "").strip()
        if len(misread) > MAX_CASE:
            raise Refused(f"keep the misread message under {MAX_CASE} characters")
        from .inbox import SECRET, token_like   # here, not at the top: inbox imports this module
        if misread and (SECRET.search(misread) or token_like(misread)):
            raise Refused("that message looks like it holds a key, a token or a password; it is not kept")
        d = self.load(name)
        d["entries"] = d.get("entries") or []
        if agent:
            if not AGENT_NAME_RE.fullmatch(agent):
                raise Refused("name the agent as `semantext agents` shows it")
            if d.get("agents") is not None and not isinstance(d.get("agents"), dict):
                raise Refused(f"{self.path(name)}: 'agents' must map each agent's name to its rules")
            d["agents"] = d.get("agents") or {}
            layer = d["agents"].setdefault(agent, {})
            target, prefix = layer.setdefault("entries", []), f"{name}.{agent_slug(agent)}"
            if not isinstance(target, list):
                raise Refused(f"{self.path(name)}: {agent}'s 'entries' must be a list")
        else:
            target, prefix = d["entries"], name
        # One more than the highest number in use, so an id never repeats, even after rules were removed by hand.
        taken = [int(m.group(1)) for x in self.every_entry(d) if isinstance(x, dict)
                 if (m := re.fullmatch(re.escape(prefix) + r"\.learned-(\d+)", str(x.get("id", ""))))]
        rid = f"{prefix}.learned-{1 + max(taken, default=0)}"
        where = "this agent's own rules in this environment" if agent else "this environment"
        target.append({"id": rid, "kind": "rule", "statement": words,
                       "applies_when": applies_when or f"Learned from your correction; applies in {where}.",
                       "mode": "adaptive", "enabled": True,
                       "provenance": provenance or {"type": "LEARNED", "words": words, "when": now()}})
        if misread:   # the correction kept as a test, in the back-test's case fields (docs/backtest.md)
            tests = d["tests"] = d.get("tests") or []
            taken = [int(m.group(1)) for t in tests if (m := re.fullmatch(re.escape(name) + r"\.case-(\d+)",
                                                                           str(t.get("case", ""))))]
            tests.append({"case": f"{name}.case-{1 + max(taken, default=0)}", "message": misread, "correction": words,
                          "rules": [rid], "source": "person", "grounded": "EXPLICIT", "at": now()})
        self.save(name, d)
        by, mine = (provenance or {}).get("by"), f" (for {agent} only)" if agent else ""
        self.log(f'Added {rid} in {self.title(name)}{mine}, proposed by {by}: "{words}"' if by
                 else f'Learned {rid} in {self.title(name)}{mine}: "{words}"')
        return rid

    # ---- corrections kept as tests ------------------------------------------------------------------------------
    def cases(self, name: str) -> list[dict]:
        """The environment's corrections kept as tests, each with whether it is still covered: every rule it needs is
        in the file and switched on (an agent's own rule counts for that agent's card). A rule switched off or removed
        leaves its correction uncovered: the misreading it was taught against can come back."""
        d = self.load(name)
        live = {x.get("id") for x in self.live(self.every_entry(d))}
        if name != "base":
            try:
                live |= {x.get("id") for x in self.live(self.load("base").get("entries"))}
            except Refused:
                pass
        out = []
        for t in d.get("tests") or []:
            needs = [r for r in t.get("rules") or [] if isinstance(r, str)]
            missing = [r for r in needs if r not in live]
            out.append({**t, "covered": bool(needs) and not missing, "missing": missing})
        return out

    def depends_on(self, name: str, rule_id: str) -> list[dict]:
        """The kept corrections that need this rule: what switching it off, or removing it, would uncover."""
        return [t for t in self.cases(name) if rule_id in (t.get("rules") or [])]

    def check_adoptable(self, r: dict, choice: str) -> None:
        """Before an answer that adds a proposed rule is kept: the environment it was proposed for must still exist."""
        if r.get("kind") == "rule" and str(choice or "").strip().lower() == "add":
            try:
                self.path(str(r.get("env") or ""))
            except Refused:
                raise Refused(f"#{r['id']} was proposed for the environment {r.get('env')!r}, which no longer exists: "
                              f"answer no, and teach the rule yourself where you want it")

    def adopt(self, r: dict) -> str | None:
        """A rule an agent proposed in the inbox, once the user has answered: added if they said add. It is kept as
        the agent's proposal, or, if they gave their own wording, as their words. Returns the new rule's id, or
        None if nothing was added."""
        a = r.get("answer") or {}
        if r.get("kind") != "rule" or a.get("picked") != "Add":
            return None
        by, words, agent = r.get("from") or "an agent", (a.get("words") or "").strip(), r.get("agent") or None
        if words:
            return self.learn(r["env"], words, {"type": "LEARNED", "words": words, "when": now(), "drafted_by": by,
                                                "request": r["id"]}, agent=agent)
        where = f"{agent}'s own rules in this environment" if agent else "this environment"
        return self.learn(r["env"], r["statement"],
                          {"type": "PROPOSED", "by": by, "how": r.get("from_how") or "", "request": r["id"],
                           "proposed": r.get("at"), "added": now(), "via": a.get("via")},
                          f"Proposed by {by} and added by you; applies in {where}.", agent=agent)

    def undo(self, name: str, rule_id: str) -> None:
        """Undo never deletes: the rule is archived in its file, with its words, and leaves the card."""
        d = self.load(name)
        x = self._entry(d, rule_id)
        x["archived"], x["enabled"], x["archived_at"] = True, False, now()
        self.save(name, d)
        self.log(f"Undid {rule_id} in {self.title(name)} (kept in the file, off the card)")

    def feature(self, name: str, key: str, on: bool, country: str = "") -> None:
        if key not in FEATURES:
            raise Refused(f"no such feature: {key}")
        statement, mode = FEATURES[key]
        if key == "news":
            country = re.sub(r"[^A-Za-z .'-]", "", country or "")[:40].strip() or "my country"
            statement = statement.format(country=country)
        d = self.load(name)
        d["entries"] = d.get("entries") or []
        rid = f"feature.{key}"
        old = [x for x in d["entries"] if x.get("id") == rid]
        if on:
            if old:
                old[0].update(statement=statement, enabled=True, archived=False)
            else:
                d["entries"].append({"id": rid, "kind": "rule", "statement": statement,
                                     "applies_when": "Always, while this switch is on.", "mode": mode,
                                     "enabled": True, "provenance": {"type": "SETTING", "when": now()}})
        elif old:
            old[0]["enabled"] = False
        self.save(name, d)
        self.log(f"{key.title()} turned {'on' if on else 'off'} in {self.title(name)}")

    def undo_last(self, name: str) -> str:
        """Undo the last change to an environment, whatever it was: restore the newest saved version. Nothing is
        deleted. The version undone is kept as '...-redo.yaml', and the version restored is marked '...-used.yaml'
        so the next undo goes one step further back."""
        p = self.path(name)
        # Only this environment's own versions: "work-*" would also match "work-2-..." and "work-a-...".
        own = re.compile(re.escape(name) + r"-\d{8}-\d{6}-\d{6}")
        cands = sorted(h for h in self.history_dir.glob(f"{name}-*.yaml") if own.fullmatch(h.stem))
        if not cands:
            raise Refused("nothing to undo in this environment")
        newest = cands[-1]
        try:   # what the restore takes off; a file broken by a hand edit cannot say, but it is kept all the same
            before = {x.get("id") for x in self.every_entry(self.load(name))}
        except Refused:
            before = None
        mark = stamp()
        kept = self.history_dir / f"{name}-{mark}-redo.yaml"
        shutil.copyfile(p, kept)
        shutil.copyfile(newest, p)
        newest.replace(newest.with_name(newest.stem + "-used.yaml"))
        try:
            after = {x.get("id") for x in self.every_entry(self.load(name))}
        except Refused:
            after = set()
        self.last_undo = {"kept": str(kept), "took_off": None if before is None else sorted(before - after)}
        self.log(f"Undid the last change in {self.title(name)}; the version it replaced is kept as {kept.name}")
        return newest.name

    def source(self, name: str) -> str:
        return self.path(name).read_text(encoding="utf-8")

    def write_source(self, name: str, text: str) -> None:
        """The editor's save. Refused unless the text is a valid environment for the same name, so a typo cannot
        break it."""
        try:
            d = yaml.safe_load(text)
        except yaml.YAMLError as e:
            mark = getattr(e, "problem_mark", None)
            at = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
            raise Refused(f"not valid{at}: {getattr(e, 'problem', None) or str(e).splitlines()[0]}")
        if not isinstance(d, dict) or not isinstance(d.get("environment"), dict):
            raise Refused("an environment needs an 'environment' section")
        if d["environment"].get("id") != name:
            raise Refused(f"the environment id must stay {name!r}")
        check_environment(d, "the text")   # the same check as reading the file: what saves will also load
        entries = d.get("entries") or []
        every = self.every_entry(d)
        ids = [x["id"] for x in every]
        if len(set(ids)) != len(ids):
            raise Refused("two rules share an id")
        self._keep(name)
        self.path(name).write_text(text, encoding="utf-8")
        self.log(f"Edited {self.title(name)} by hand ({len(entries)} rules)")

    # ---- reading a message: cue words only ---------------------------------------------------------------------
    MATERIAL = re.compile(r"\b(send|email|publish|post|buy|pay|order|delete|remove all|wipe|download|install|"
                          r"share|upload|transfer)\b", re.I)
    COMMON = {"that", "this", "with", "from", "have", "what", "when", "your", "will", "just", "like", "them", "then",
              "they", "there", "about", "would", "could", "should", "please", "into", "only", "more", "some", "want",
              "make", "does", "been", "were", "it's", "i'm", "can't", "don't", "maybe", "every", "thing", "things"}

    def read(self, name: str, message: str, dry: bool = False, entries: list | None = None) -> dict:
        """How a message is read before your AI acts on it, from cue words. dry=True saves nothing: the page's
        opening example uses it, so a reload never piles up pending decisions. `entries`, when given, stands in for
        the environment's own rules: the back-test reads the same message with another card."""
        m = (message or "").strip()
        low = m.lower()
        out = []
        if not m:
            return {"readings": [], "decisions": [], "touched": []}
        if m.endswith("?") or re.match(r"^(who|what|where|when|why|how|can|could|should|would|is|are|do|does|did)\b",
                                       low):
            out.append(("A question", "It answers, and changes nothing until you ask it to.",
                        "base.question-not-instruction"))
        if re.search(r"\b(maybe|we could|we should|i was thinking|what if|perhaps|might)\b", low):
            out.append(("A suggestion", "It opens options. It won't treat this as an order.",
                        "base.suggest-not-require"))
        if re.match(r"^(yes|yeah|yep|ok|okay|go ahead|do it|let'?s do (it|that)|sounds good|sure)\b", low):
            out.append(("A yes", "It accepts the latest offer exactly as offered, and says which reading it took.",
                        "base.yes-binds-to-offer"))
        if re.search(r"\b(park|parked|hold off|not now|pause|shelve)\b", low):
            out.append(("A pause", "What you park stays parked until you reopen it.", "base.parked-stays-parked"))
        t = re.search(r"\b(for now|tonight|tomorrow|next week|later|this weekend)\b", low)
        if t:
            out.append(("A time limit", f'Kept word for word: "{t.group(1)}". No date is invented.',
                        "base.time-kept-verbatim"))
        # "no," ends in a comma, so no word boundary may follow it (", " has none: the old pattern never matched it).
        if re.search(r"\b(?:no,|(?:don'?t|stop|that'?s wrong|not what i)\b)", low):
            out.append(("A correction", "Kept as a rule with your exact words. Use Teach it to keep it.",
                        "base.corrections-become-rules"))
        if not out:
            out.append(("An instruction", "It acts, within this environment's rules, and shows what it did.",
                        "base.show-your-work"))
        kinds = {"A question": "question", "A suggestion": "suggestion", "A yes": "yes", "A pause": "pause",
                 "A time limit": "time", "A correction": "correction", "An instruction": "instruction"}
        # Which of this environment's own rules the words touch: shared meaningful words (four letters or more,
        # not common ones). A stand-in: an AI reading with the card can say which apply more precisely.
        said = {w for w in re.findall(r"[a-z']+", low) if len(w) >= 4 and w not in self.COMMON}
        touched = []
        try:
            for e in self.live(self.load(name).get("entries") if entries is None else entries):
                if said & {w for w in re.findall(r"[a-z']+", str(e.get("statement", "")).lower()) if len(w) >= 4}:
                    touched.append(e["id"])
        except Refused:
            pass
        decisions = []
        for v in sorted({x.lower() for x in self.MATERIAL.findall(m)}):
            decisions.append({"id": f"d{datetime.now().strftime('%H%M%S%f')}-{v}",
                              "ask": f'Needs your word before it can "{v}": that leaves your machine or cannot be '
                                     f'undone.',
                              "rule": "base.irreversible-needs-your-word", "message": m[:160]})
        if decisions and not dry:
            s = self.state()
            s["pending"] = (s["pending"] + decisions)[-12:]
            self.put_state(s)
        return {"readings": [{"label": a, "says": b, "rule": c, "kind": kinds[a]} for a, b, c in out],
                "decisions": decisions, "touched": touched}

    def decide(self, did: str, answer: str) -> None:
        s = self.state()
        hit = [d for d in s["pending"] if d["id"] == did]
        if not hit:
            raise Refused("no such pending decision")
        s["pending"] = [d for d in s["pending"] if d["id"] != did]
        self.put_state(s)
        word = "Yes" if answer == "yes" else "No"
        self.log(f"You said {word}: {hit[0]['ask'].split(':')[0]}")

    # ---- models: names only, nothing is started or downloaded --------------------------------------------------
    @staticmethod
    def local_models(base: Path = OLLAMA_MANIFESTS) -> list[str]:
        if not base.is_dir():
            return []
        return sorted(f"{m.name}:{t.name}" for m in base.iterdir() if m.is_dir() for t in m.iterdir() if t.is_file())

    def set_model(self, model: str | None) -> None:
        if model is not None and model not in self.local_models():
            raise Refused("that model is not on this machine")
        s = self.state()
        s["model"] = model
        self.put_state(s)
        self.log(f"Chose the model {model}" if model else "Cleared the model choice")
