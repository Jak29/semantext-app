"""What was heard: your own messages, kept on your machine, so rules can be proposed from how you actually talk.

One JSON-lines file per environment, heard/<name>.jsonl. Nothing here leaves your machine, and nothing is heard
unless you say `semantext hear ...` yourself or switch on hearing prompts (`semantext config hear-prompts on`).
A proposal is only a proposal: a rule is added when you accept it, with your words kept beside it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .inbox import SECRET
from .store import Refused, Store, now, valid_name

MAX_TEXT = 4000
# Sentences that sound like a standing preference or a correction: the shape a rule is made from.
RULE_SHAPED = re.compile(r"\b(always|never|don'?t|do not|stop|no more|from now on|i prefer|i'?d rather|make sure|"
                         r"remember to|avoid|please don'?t|keep it|i want you to)\b"
                         # ... or a reading rule in its own tight form: "When I say X, I mean Y" (say, ask, write, use;
                         # mean, am asking, want). The loose "When I ..., I ..." would also catch "When I get home,
                         # I'll call you".
                         r"|\bwhen i (?:say|ask|write|use)\b.{1,200}?\bi(?:'m| am)?\s+(?:mean|meant|asking|want)\b",
                         re.I)


class Heard:
    def __init__(self, root: Path):
        self.dir = Path(root) / "heard"

    def path(self, name: str) -> Path:
        if not valid_name(name):
            raise Refused(f"not an environment name: {name!r}")
        return self.dir / f"{name}.jsonl"

    def items(self, name: str) -> list[dict]:
        p = self.path(name)
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue          # a damaged line is skipped, never fatal
        return out

    def hear(self, name: str, text: str, source: str = "you") -> dict:
        text = " ".join((text or "").split())
        if not text:
            raise Refused("nothing to hear: the text is empty")
        if SECRET.search(text):
            raise Refused("that looks like it holds a key, a token or a password; it is not kept")
        text = text[:MAX_TEXT]
        items = self.items(name)
        item = {"id": 1 + max((i.get("id", 0) for i in items), default=0), "when": now(), "source": source,
                "text": text}
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.path(name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def keep(self, name: str, items: list[dict], source: str) -> int:
        """Many items at once, each {text, when, from}: one read of the file and one append. The caller has already
        left out anything empty, secret or kept before."""
        path = self.path(name)
        start = 1 + max((i.get("id", 0) for i in self.items(name)), default=0)
        lines = []
        for n, x in enumerate(items):
            text = " ".join(str(x.get("text") or "").split())[:MAX_TEXT]
            if not text or SECRET.search(text):
                continue
            lines.append(json.dumps({"id": start + n, "when": x.get("when") or now(), "source": source, "text": text,
                                     "from": x.get("from")}, ensure_ascii=False) + "\n")
        if lines:
            self.dir.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write("".join(lines))
        return len(lines)

    def recall(self, name: str, query: str = "", n: int = 20) -> list[dict]:
        """The newest first. With a query, only the items holding every one of its words."""
        words = [w for w in re.findall(r"\w+", (query or "").lower())]
        hits = [i for i in self.items(name) if all(w in i.get("text", "").lower() for w in words)]
        return hits[::-1][:n]

    def forget(self, name: str, ids: list[int] | None = None) -> int:
        """Forget the given items, or everything heard in this environment when ids is None. Returns how many."""
        items = self.items(name)
        keep = [] if ids is None else [i for i in items if i.get("id") not in set(ids)]
        gone = len(items) - len(keep)
        if gone:
            p = self.path(name)
            p.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in keep), encoding="utf-8")
        return gone

    def propose(self, name: str, store: Store, limit: int = 10) -> list[dict]:
        """Candidate rules from what was heard: sentences shaped like a standing preference or a correction, that
        are not already rules here. Each keeps the id of the item it came from."""
        have = {" ".join(str(x.get("statement", "")).lower().split()) for x in store.live(store.load(name).get("entries"))}
        seen, out = set(), []
        for item in self.items(name)[::-1]:
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", item.get("text", "")):
                s = sentence.strip().strip("\"'")
                if not (12 <= len(s) <= 300) or not RULE_SHAPED.search(s):
                    continue
                s = s[0].upper() + s[1:]
                if s[-1] not in ".!?":
                    s += "."
                key = " ".join(s.lower().split())
                if key in have or key in seen:
                    continue
                seen.add(key)
                out.append({"n": len(out) + 1, "statement": s, "heard": item.get("id")})
                if len(out) >= limit:
                    return out
        return out
