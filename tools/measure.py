"""measure.py -- what Semantext does, measured: its actions, the files and connections it touches, how it holds up
against hostile input, and how close the hook runs to its limits.

Usage:  python measure.py [--json OUT] [--quick]

Every number states its unit, so a reader knows what one count is. Every run happens in a fresh temporary home, never
in the user's own. Measured:
  touches     for each action: the files it created, changed or removed under the home, against what it is
              declared to touch. The target is no undeclared touch. Paths are normalised, so a timestamp in a file
              name reads <stamp>.
  network     outbound connections opened during each action (target 0); a socket the page server binds is not a
              connection.
  processes   processes started during each action (target 0).
  hostile     inputs from a corpus that end in a traceback, with a 95% upper bound on the rate (with 0 seen in N, the
              bound is about 3/N, so it shrinks only as N grows).
  hook        bytes written against the limit, rules shown against live rules, and time per call, for stores of 10
              to 5,000 rules.
  round trip  settings files whose install-then-uninstall gives back the same JSON.
Not measured here: the guard mutation score, a sweep that edits a copy of the package once per guard and reruns the
tests.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import semantext
from semantext import claude, cli, hook
from semantext import inbox as inbox_module
from semantext.inbox import AGENT_MARKERS
from semantext.store import Store

STAMP = re.compile(r"\d{8}-\d{6}(?:-\d{6})?")


# ---------------------------------------------------------------- instruments
class Watch:
    """Counts outbound connections and process starts while active."""

    def __init__(self):
        self.connects, self.spawns = [], []

    def __enter__(self):
        self._c, self._cc = socket.socket.connect, socket.create_connection
        self._p, self._s = subprocess.Popen.__init__, os.system
        w = self

        def connect(sock, addr, *a, **k):
            w.connects.append(str(addr))
            return w._c(sock, addr, *a, **k)

        def create_connection(addr, *a, **k):
            w.connects.append(str(addr))
            return w._cc(addr, *a, **k)

        def popen_init(proc, args, *a, **k):
            w.spawns.append(str(args)[:80])
            return w._p(proc, args, *a, **k)

        def system(cmd):
            w.spawns.append(str(cmd)[:80])
            return w._s(cmd)

        socket.socket.connect, socket.create_connection = connect, create_connection
        subprocess.Popen.__init__, os.system = popen_init, system
        return self

    def __exit__(self, *exc):
        socket.socket.connect, socket.create_connection = self._c, self._cc
        subprocess.Popen.__init__, os.system = self._p, self._s
        return False


def snapshot(root: Path) -> dict:
    out = {}
    for p in root.rglob("*"):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = p.read_bytes()
    return out


def diff(before: dict, after: dict) -> list[str]:
    norm = lambda p: STAMP.sub("<stamp>", p)  # noqa: E731
    changes = []
    for p in sorted(set(before) | set(after)):
        if p not in before:
            changes.append(f"+{norm(p)}")
        elif p not in after:
            changes.append(f"-{norm(p)}")
        elif before[p] != after[p]:
            changes.append(f"~{norm(p)}")
    return sorted(set(changes))


def upper95(failures: int, n: int) -> float:
    """The exact (Clopper-Pearson) 95% upper bound on a rate, from failures in n trials."""
    if n == 0:
        return 1.0
    if failures >= n:
        return 1.0
    lo, hi = failures / n, 1.0
    for _ in range(60):  # bisection on the binomial tail P(X <= failures) = 0.05
        mid = (lo + hi) / 2
        tail = sum(math.comb(n, k) * mid ** k * (1 - mid) ** (n - k) for k in range(failures + 1))
        lo, hi = (mid, hi) if tail > 0.05 else (lo, mid)
    return hi


# ---------------------------------------------------------------- the sandbox
class Sandbox:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="semantext_measure_"))
        self.home, self.user, self.cwd = self.root / "semantext", self.root / "user", self.root / "cwd"
        self.user.mkdir()
        self.cwd.mkdir()
        os.environ.update(SEMANTEXT_HOME=str(self.home), HOME=str(self.user), USERPROFILE=str(self.user))

    def run(self, argv: list[str], stdin: str | None = None, console: bool = True):
        """One action in-process, under a stated premise, whatever shell this tool itself runs in: a person at a
        console (console=True), or a plain shell with no console (False); in both, no agent's marker is set.
        Returns (exit code, touches, connections, spawns, stdout, stderr)."""
        before = snapshot(self.root)
        out, err = io.StringIO(), io.StringIO()
        old_cwd, old_stdin = os.getcwd(), sys.stdin
        old_console = inbox_module.stdin_is_console
        markers = {m: os.environ.pop(m) for m in AGENT_MARKERS if m in os.environ}
        inbox_module.stdin_is_console = lambda: console
        os.chdir(self.cwd)
        code = None
        try:
            with Watch() as w, redirect_stdout(out), redirect_stderr(err):
                if argv[:1] == ["hook"]:
                    code = hook.main(stdin or "")
                else:
                    try:
                        code = cli.main(argv)
                    except SystemExit as e:
                        code = e.code if isinstance(e.code, int) else 1
        except Exception as e:  # noqa: BLE001  a traceback: counted by the caller
            err.write(f"Traceback: {type(e).__name__}: {e}")
            code = "traceback"
        finally:
            os.chdir(old_cwd)
            sys.stdin = old_stdin
            inbox_module.stdin_is_console = old_console
            os.environ.update(markers)
        return code, diff(before, snapshot(self.root)), w.connects, w.spawns, out.getvalue(), err.getvalue()


# Each action, the touches it is declared to make (relative to the sandbox: semantext/ is the home, user/ the user), and
# optionally its premise: run by a person at a console (the default), or in a plain shell with no console (False).
ACTIONS = [
    ("init", ["init"], {"+semantext/profiles/base/SEMANTICS.yaml", "+semantext/profiles/default/SEMANTICS.yaml"}),
    ("card", ["card"], set()),
    ("rules", ["rules", "--all", "--base"], set()),
    ("env list", ["env", "list"], set()),
    ("env new", ["env", "new", "Office", "--none"], {"+semantext/profiles/office/SEMANTICS.yaml", "~semantext/state.json",
                                                    "+semantext/state.json"}),
    ("env use", ["env", "use", "default"], {"~semantext/state.json"}),
    ("teach", ["teach", "always", "answer", "in", "one", "line"],
     {"~semantext/profiles/default/SEMANTICS.yaml", "+semantext/history/default-<stamp>.yaml", "~semantext/state.json"}),
    # a correction kept as its rule's test: the misread message goes into the same rule file, nothing else
    ("teach with its test", ["teach", "keep", "it", "short", "--misread", "write me a novel"],
     {"~semantext/profiles/default/SEMANTICS.yaml", "+semantext/history/default-<stamp>.yaml", "~semantext/state.json"}),
    ("cases", ["cases"], set()),
    ("toggle", ["toggle", "default.learned-1"],
     {"~semantext/profiles/default/SEMANTICS.yaml", "+semantext/history/default-<stamp>.yaml", "~semantext/state.json"}),
    ("pin", ["pin", "default.learned-1"],
     {"~semantext/profiles/default/SEMANTICS.yaml", "+semantext/history/default-<stamp>.yaml", "~semantext/state.json"}),
    ("undo rule", ["undo", "default.learned-1"],
     {"~semantext/profiles/default/SEMANTICS.yaml", "+semantext/history/default-<stamp>.yaml", "~semantext/state.json"}),
    ("undo --last", ["undo", "--last"],
     {"~semantext/profiles/default/SEMANTICS.yaml", "+semantext/history/default-<stamp>-redo.yaml",
      "+semantext/history/default-<stamp>-used.yaml", "-semantext/history/default-<stamp>.yaml",
      "~semantext/state.json"}),
    ("read (says nothing is saved)", ["read", "please", "delete", "the", "old", "file"], set()),
    ("where", ["where"], set()),
    ("hear", ["hear", "from", "now", "on", "keep", "it", "short"], {"+semantext/heard/default.jsonl"}),
    ("recall", ["recall"], set()),
    ("propose", ["propose"], set()),
    ("forget", ["forget", "--all"], {"~semantext/heard/default.jsonl"}),
    ("config", ["config", "hear-prompts", "off"], {"~semantext/state.json"}),
    # the feed is on by default: one line of what was sent (never what was said), under its own lock
    ("hook, hearing off", ["hook"], {"+semantext/feed.jsonl", "+semantext/feed.lock"}),
    ("feed", ["feed"], set()),
    ("feed off", ["feed", "off"], {"~semantext/state.json"}),
    ("hook, feed off", ["hook"], set()),   # switched off, the hook writes no feed at all
    ("feed on", ["feed", "on"], {"~semantext/state.json"}),
    ("install, dry", ["install", "claude-code", "--settings", "{user}/settings.json"], set()),
    ("install --apply", ["install", "claude-code", "--apply", "--settings", "{user}/settings.json"],
     {"+user/settings.json"}),
    ("uninstall --apply", ["uninstall", "claude-code", "--apply", "--settings", "{user}/settings.json"],
     {"~user/settings.json", "+user/settings.json.semantext-backup-<stamp>"}),
    ("doctor", ["doctor"], set()),
    # the inbox and the instruction files (from 0.1.0 at b795a0e)
    ("ask", ["ask", "--title", "Pick", "--why", "w", "--question", "q", "--option", "a", "--option", "b"],
     {"+semantext/inbox.jsonl", "+semantext/inbox.lock", "+semantext/inbox.seq", "~semantext/inbox.jsonl",
      "~semantext/inbox.seq"}),
    ("inbox", ["inbox", "--all"], set()),
    ("answers (none yet)", ["answers"], set()),
    # the user's own message answers request #1 in chat: the tool's own record says they typed it, so the hook records
    # the answer, then hands out the card as always (the record is written before the action, so it is not a touch)
    ("hook, an answer typed", ["hook"], {"~semantext/inbox.jsonl", "~semantext/feed.jsonl"}, True,
     {"prompt": "#1 2", "transcript": True}),
    # with no asker named and no console, close is refused (exit 1) and touches nothing
    ("close (no asker, no console)", ["close", "1", "--how", "not", "needed"], set(), False),
    ("install agents-md, dry", ["install", "agents-md", "--file", "{user}/AGENTS.md"], set()),
    # the installed file is listed in state.json's agent_files, which is what `sync` refreshes
    ("install agents-md --apply", ["install", "agents-md", "--file", "{user}/AGENTS.md", "--apply"],
     {"+user/AGENTS.md", "~user/AGENTS.md", "~semantext/state.json"}),
    ("uninstall agents-md --apply", ["uninstall", "agents-md", "--file", "{user}/AGENTS.md", "--apply"],
     {"~user/AGENTS.md", "+user/AGENTS.md.semantext-backup-<stamp>", "~semantext/state.json"}),
]


def measure_touches(sb: Sandbox) -> list[dict]:
    rows = []
    for name, argv, declared, *premise in ACTIONS:
        console = premise[0] if premise else True
        event = premise[1] if len(premise) > 1 else {"prompt": "hello"}
        if event.get("transcript"):   # the tool's own record that the user typed this prompt
            t = sb.user / "transcript.jsonl"
            t.write_text(json.dumps({"type": "user", "turnOrigin": "human", "message": {"content": event["prompt"]}})
                         + "\n", encoding="utf-8")
            event = {"prompt": event["prompt"], "transcript_path": str(t)}
        argv = [a.replace("{user}", str(sb.user)) for a in argv]
        code, touched, conns, spawns, out, err = sb.run(argv, stdin=json.dumps(event), console=console)
        undeclared = [t for t in touched if t not in declared]
        rows.append({"action": name, "console": console, "exit": code, "touched": touched, "undeclared": undeclared,
                     # an action declared to touch something that was refused measured a refusal, not the action
                     "measured": not (declared and code != 0),
                     "connections": len(conns), "processes": len(spawns),
                     "traceback": code == "traceback" or "Traceback" in err})
    return rows


# ---------------------------------------------------------------- hostile inputs
def hostile_corpus(r: random.Random, n_random: int) -> list[tuple[str, list[str], str | None]]:
    fixed_hook = ["", "not json", "[1, 2]", '{"prompt": 7}', '{"prompt": null}', "{" * 5000, "[" * 50_000,
                  '{"prompt": "' + "y" * 200_000 + '"}', "\x00\x01\x02", '{"prompt": "\udcff"}']
    cases = [("hook", ["hook"], s) for s in fixed_hook]
    for _ in range(n_random):
        k = r.randrange(0, 60)
        s = "".join(chr(r.choice([r.randrange(32, 127), r.randrange(0, 0x3000)])) for _ in range(k))
        cases.append(("hook", ["hook"], r.choice([s, json.dumps({"prompt": s}), json.dumps([s, {"prompt": s}])])))
    bad_cli = [["frobnicate"], ["env", "use"], ["env", "use", "../x"], ["env", "use", "CON"], ["toggle", "nope"],
               ["pin", ""], ["undo"], ["undo", "x", "--env", "../../etc"], ["teach"], ["teach", "x" * 5000],
               ["read"], ["hear"], ["forget"], ["propose", "--accept", "99"], ["config", "nope"],
               ["install", "nope"], ["install", "claude-code", "--settings", "{cwd}"], ["--home", "{user}", "card"],
               ["env", "new", "Con"], ["env", "new", "‮"]]
    cases += [("cli", a, None) for a in bad_cli]
    return cases


def measure_hostile(sb: Sandbox, n_random: int) -> dict:
    r = random.Random(20261013)
    cases = hostile_corpus(r, n_random)
    tracebacks, n = [], 0
    for kind, argv, stdin in cases:
        argv = [a.replace("{user}", str(sb.user)).replace("{cwd}", str(sb.cwd)) for a in argv]
        # A command-line input runs under both premises: without a console the user-only commands are refused
        # before their arguments are parsed, so only the console run reaches the parsing.
        for console in ((True, False) if kind == "cli" else (True,)):
            n += 1
            code, _, _, _, out, err = sb.run(argv, stdin, console=console)
            if code == "traceback" or "Traceback" in err or (kind == "hook" and code != 0):
                tracebacks.append(f"{kind} {argv} console={console} {repr(stdin)[:40]}")
    return {"inputs": n, "tracebacks": len(tracebacks), "upper95": upper95(len(tracebacks), n),
            "examples": tracebacks[:5]}


# ---------------------------------------------------------------- the hook's budget
def measure_hook(sizes=(10, 100, 1000, 5000), runs=15) -> list[dict]:
    rows = []
    for n in sizes:
        root = Path(tempfile.mkdtemp(prefix="semantext_hook_")) / "semantext"
        s = Store.open(root)
        d = s.load("default")
        d["entries"] = [{"id": f"default.r{i}", "statement": f"rule number {i}: answer plainly and say why"}
                        for i in range(n)]
        s.write_source("default", __import__("yaml").safe_dump(d, sort_keys=False))
        live = len(s.live(s.load("base").get("entries"))) + n
        times, out = [], ""
        for _ in range(runs):
            t0 = time.perf_counter()
            out = hook.run('{"prompt": "hi"}', s)
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        shown = sum(1 for line in out.splitlines() if line.startswith("- "))
        rows.append({"rules": n, "live": live, "shown": shown, "bytes": len(out.encode("utf-8")) + 1,
                     "limit": hook.LIMIT_BYTES, "ms_p50": round(times[len(times) // 2], 2),
                     "ms_p95": round(times[min(len(times) - 1, int(len(times) * 0.95))], 2)})
    return rows


# ---------------------------------------------------------------- settings round trip
def measure_settings_roundtrip(n=200) -> dict:
    r = random.Random(7)
    same, refused = 0, 0
    base = Path(tempfile.mkdtemp(prefix="semantext_settings_"))
    for i in range(n):
        groups = [{"hooks": [{"type": "command", "command": r.choice(["other", "fmt", "lint"]) + str(j)}]}
                  for j in range(r.randrange(0, 3))]
        data = {"model": r.choice(["a", "b"]), "env": {"X": str(r.random())}}
        if r.random() < 0.7:
            data["hooks"] = {"UserPromptSubmit": groups} if groups else {"Stop": [{"hooks": []}]}
        p = base / f"s{i}.json"
        p.write_text(json.dumps(data, ensure_ascii=False, indent=r.choice([None, 2, 4])), encoding="utf-8")
        try:
            claude.install(p, "semantext hook")
            claude.uninstall(p)
        except Exception:  # noqa: BLE001
            refused += 1
            continue
        same += json.loads(p.read_text(encoding="utf-8")) == data
    return {"files": n, "same_json": same, "refused": refused}


def main():
    ap = argparse.ArgumentParser(description="Measure what Semantext does.")
    ap.add_argument("--json")
    ap.add_argument("--quick", action="store_true", help="a smaller hostile corpus and fewer timing runs")
    a = ap.parse_args()
    sb = Sandbox()
    report = {"version": semantext.__version__, "python": sys.version.split()[0], "platform": sys.platform,
              "touches": measure_touches(sb),
              "hostile": measure_hostile(Sandbox(), 100 if a.quick else 600),
              "hook": measure_hook(runs=5 if a.quick else 15),
              "settings_roundtrip": measure_settings_roundtrip()}
    t = report["touches"]
    unmeasured = [x["action"] for x in t if not x["measured"]]
    print(f"Semantext {report['version']} on Python {report['python']} ({report['platform']})")
    print(f"touches: {len(t)} actions; undeclared touches: {sum(len(x['undeclared']) for x in t)}; "
          f"connections: {sum(x['connections'] for x in t)}; processes: {sum(x['processes'] for x in t)}; "
          f"tracebacks: {sum(x['traceback'] for x in t)}; not measured: {len(unmeasured)}")
    for x in t:
        flag = "  <- UNDECLARED: " + ", ".join(x["undeclared"]) if x["undeclared"] else ""
        flag += "  <- NOT MEASURED: refused, though it is declared to act" if not x["measured"] else ""
        premise = "console" if x["console"] else "no console"
        print(f"  {x['action']:<30} [{premise:<10}] exit {x['exit']!s:<9} {', '.join(x['touched']) or '(nothing)'}"
              f"{flag}")
    h = report["hostile"]
    print(f"hostile: {h['tracebacks']} tracebacks in {h['inputs']} inputs; 95% upper bound on the rate "
          f"{h['upper95']:.2%}")
    for e in h["examples"]:
        print(f"  {e}")
    print("hook: rules | live | shown | bytes / limit | ms p50 | ms p95")
    for x in report["hook"]:
        print(f"  {x['rules']:>5} | {x['live']:>5} | {x['shown']:>5} | {x['bytes']:>5} / {x['limit']} | "
              f"{x['ms_p50']:>7} | {x['ms_p95']:>7}")
    rt = report["settings_roundtrip"]
    print(f"settings round trip: {rt['same_json']} of {rt['files']} give back the same JSON ({rt['refused']} refused)")
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    failed = (unmeasured or any(x["undeclared"] or x["traceback"] or x["connections"] or x["processes"] for x in t)
              or h["tracebacks"])
    if failed:
        print("FAILED: a row above was not measured, touched what it did not declare, connected, started a process, or "
              "raised a traceback")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
