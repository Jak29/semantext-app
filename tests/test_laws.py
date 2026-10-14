"""Laws Semantext must obey, each written as a check that can fail.

Each law borrows the mechanism of a proved family of results:
- loops close: every change followed by its inverse returns the exact bytes;
- settling: repeating a maintenance step reaches a fixed point or a 2-cycle, never a drift;
- exhaustive certificates: a claim about every case of a small finite family is checked case by case;
- the window law: a fault seen only on sequences of length k is invisible to every shorter test, so the random walks
  run well past the longest minimal counterexample found so far (4 steps);
- what a transform keeps: what a save rewrites is exactly what a user can lose.
"""
import hashlib
import http.client
import itertools
import json
import random
import threading
from pathlib import Path

import pytest
import yaml

from semantext import claude, hook
from semantext.server import make_server
from semantext.store import RESERVED, Refused, Store, valid_name


@pytest.fixture
def law_home(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("SEMANTEXT_HOME", str(tmp_path / "semantext"))
    return tmp_path / "semantext"


@pytest.fixture
def law_store(law_home):
    return Store.open(law_home)


def raw(s: Store, name: str) -> bytes:
    return s.path(name).read_bytes()


def rule_ids(s: Store, name: str) -> list:
    return [e["id"] for e in s.load(name).get("entries") or []]


# ---------------------------------------------------------------- loops close
CHANGES = {
    "learn": lambda s, n, r: s.learn(n, f"keep answers short, rule {r.randrange(10**6)}"),
    "toggle": lambda s, n, r: s.toggle(n, r.choice(rule_ids(s, n))) if rule_ids(s, n) else None,
    "pin": lambda s, n, r: s.pin(n, r.choice(rule_ids(s, n))) if rule_ids(s, n) else None,
    "feature": lambda s, n, r: s.feature(n, r.choice(["jokes", "news", "tone"]), r.random() < 0.5),
    "undo-rule": lambda s, n, r: s.undo(n, r.choice(rule_ids(s, n))) if rule_ids(s, n) else None,
}


@pytest.mark.parametrize("change", sorted(CHANGES))
def test_every_change_then_undo_last_returns_the_exact_bytes(law_store, change):
    s, r = law_store, random.Random(1)
    s.learn("default", "a first rule, so there is something to change")
    before = raw(s, "default")
    if CHANGES[change](s, "default", r) is None and raw(s, "default") == before and change != "feature":
        pytest.skip("nothing to change")
    s.undo_last("default")
    assert raw(s, "default") == before


@pytest.mark.parametrize("seed", range(12))
def test_random_walks_keep_every_environment_on_its_own_history(law_store, seed):
    """A reference model of undo_last (a stack of earlier versions per environment, each used once) against the real
    store, on environments whose names share prefixes. 120 random steps per walk."""
    s, r = law_store, random.Random(seed)
    envs = ["default", s.create("Work", []), s.create("Work", []), s.create("Work A", [])]
    assert envs[1:] == ["work", "work-2", "work-a"]
    hist = {n: [] for n in envs}            # each item: [bytes, used]
    for step in range(120):
        n = r.choice(envs)
        others = {m: raw(s, m) for m in envs if m != n}
        if r.random() < 0.3:
            unused = [h for h in hist[n] if not h[1]]
            if not unused:
                with pytest.raises(Refused):
                    s.undo_last(n)
            else:
                s.undo_last(n)
                unused[-1][1] = True
                assert raw(s, n) == unused[-1][0], f"seed {seed}, step {step}: undo_last({n}) restored the wrong bytes"
        else:
            kind = r.choice(sorted(CHANGES))
            current = raw(s, n)
            if kind in ("toggle", "pin", "undo-rule") and not rule_ids(s, n):
                kind = "learn"
            CHANGES[kind](s, n, r)
            hist[n].append([current, False])
        for m, b in others.items():
            assert raw(s, m) == b, f"seed {seed}, step {step}: a change to {n} touched {m}"


# ---------------------------------------------------------------- settling
@pytest.mark.parametrize("op", ["toggle", "pin"])
def test_a_switch_repeated_is_a_two_cycle_not_a_drift(law_store, op):
    s = law_store
    rid = s.learn("default", "answer in one line")
    states = [s.load("default")]
    for _ in range(6):
        getattr(s, op)("default", rid)
        states.append(s.load("default"))
    assert all(states[i] == states[i + 2] for i in range(len(states) - 2))
    assert states[0] != states[1]


def test_installing_claude_code_settles_at_once(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"model": "x"}), encoding="utf-8")
    seen = []
    for _ in range(4):
        claude.install(p, "semantext hook")
        seen.append(p.read_bytes())
    assert len(set(seen)) == 1


def test_the_card_is_a_fixed_point_of_reading_it(law_store):
    s = law_store
    s.learn("default", "say which reading you took")
    cards = {s.card("default") for _ in range(3)}
    files = {raw(s, "default") for _ in range(3)}
    assert len(cards) == 1 and len(files) == 1


# ---------------------------------------------------------------- exhaustive certificates
ALPHABET = "az09-./\\ \nA_"


def reference_valid(x: str) -> bool:
    import re
    return bool(re.fullmatch(r"[a-z][a-z0-9-]{0,30}", x)) and x not in RESERVED


def test_name_validity_on_every_short_string():
    cases = ["".join(t) for k in range(4) for t in itertools.product(ALPHABET, repeat=k)]
    cases += ["a" * 31, "a" * 32, "a" * 30 + "\n", *sorted(RESERVED), *(w.upper() for w in sorted(RESERVED)),
              "con-1", "nul2", "com10", "lpt0"]
    wrong = [repr(x) for x in cases if valid_name(x) != reference_valid(x)]
    digest = hashlib.sha256("\n".join(f"{x!r}:{reference_valid(x)}" for x in cases).encode()).hexdigest()[:16]
    assert not wrong, f"{len(wrong)} of {len(cases)} disagree (table {digest}): {wrong[:10]}"


def test_fit_on_every_small_card():
    """For whole-line cards of up to 6 rules, at three limits: within the limit, whole lines, the longest prefix."""
    lengths = [1, 30, 120]
    for limit in (400, 1000, hook.LIMIT_BYTES - 1):
        for k in range(7):
            for sizes in itertools.product(lengths, repeat=k):
                lines = ["# head", ""] + [f"- r{i}: " + "x" * n for i, n in enumerate(sizes)]
                card = "\n".join(lines)
                out = hook.fit(card, limit)
                assert len(out.encode("utf-8")) <= limit, (limit, sizes)
                kept = out.splitlines()
                if out != card:
                    assert kept[:-1] == lines[:len(kept) - 1], (limit, sizes)
                    assert kept[-1].startswith("(") and "more rules not shown" in kept[-1]


def test_the_page_guards_on_every_combination(law_store):
    """Host x Origin x X-Semantext x method, 490 requests, each against the reference rule."""
    srv = make_server(law_store, port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    port = srv.server_address[1]
    own = {f"127.0.0.1:{port}", f"localhost:{port}"}
    hosts = [f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}", "127.0.0.1", "127.0.0.1:1", "evil.example",
             ""]
    origins = [None, f"http://127.0.0.1:{port}", f"http://localhost:{port}", "null", "http://evil.example",
               f"https://127.0.0.1:{port}", f"http://127.0.0.1:{port}/"]
    marks = [None, "1", "0", "true", " 1"]
    wrong, table = [], []
    try:
        for host, origin, mark, method in itertools.product(hosts, origins, marks, ("GET", "POST")):
            # HTTP trims the whitespace around a header's value, so " 1" on the wire is the value "1".
            if method == "GET":
                allowed = host in own
            else:
                # A change must name the page itself: none named is a local process, not the page.
                allowed = (host in own and mark is not None and mark.strip() == "1"
                           and origin in {f"http://{h}" for h in own})
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.putrequest(method, "/api/state" if method == "GET" else "/api/active", skip_host=True,
                         skip_accept_encoding=True)
            if host:
                c.putheader("Host", host)
            if origin is not None:
                c.putheader("Origin", origin)
            if mark is not None:
                c.putheader("X-Semantext", mark)
            body = b'{"name": "default"}' if method == "POST" else None
            if body:
                c.putheader("Content-Type", "application/json")
                c.putheader("Content-Length", str(len(body)))
            c.endheaders(body)
            status = c.getresponse().status
            c.close()
            table.append(f"{host}|{origin}|{mark}|{method}|{status}")
            if allowed != (status != 403):
                wrong.append((host, origin, mark, method, status))
    finally:
        srv.shutdown()
        srv.server_close()
    digest = hashlib.sha256("\n".join(table).encode()).hexdigest()[:16]
    assert len(table) == 490
    assert not wrong, f"{len(wrong)} of 490 disagree with the rule (table {digest}): {wrong[:8]}"


# ---------------------------------------------------------------- what a save keeps
NOTE = "# my own note: keep this line"


def test_a_change_rewrites_the_live_file_and_history_keeps_the_text(law_store):
    """What a save keeps: the live file keeps the data, and history keeps the text. A hand comment leaves the live
    file at the next change, and the copy history made just before that change holds it exactly."""
    s = law_store
    edited = s.source("default").rstrip("\n") + f"\n{NOTE}\n"
    s.write_source("default", edited)
    s.learn("default", "use plain words")
    assert NOTE not in s.source("default"), "comments now survive a change: update the FAQ, and this law"
    newest = max((p for p in s.history_dir.glob("default-*.yaml") if not p.stem.endswith(("-used", "-redo"))),
                 key=lambda p: p.name)
    assert newest.read_text(encoding="utf-8") == edited


def test_the_faq_says_what_a_change_keeps():
    """The docs must say it: a change rewrites the file from its data, so comments are not kept, and history/ keeps
    every earlier version. Read from a source checkout; skipped when the package is installed without its docs."""
    import semantext
    faq = Path(semantext.__file__).resolve().parents[1] / "docs" / "faq.md"
    if not faq.exists():
        pytest.skip("docs/faq.md is not beside the package (installed from a wheel)")
    text = " ".join(faq.read_text(encoding="utf-8").lower().split())
    assert "comment" in text and any(w in text for w in ("not kept", "aren't kept", "are not kept", "not preserved",
                                                         "are lost", "dropped")), "the FAQ does not say comments go"
    assert "history" in text, "the FAQ does not say where earlier versions are kept"
