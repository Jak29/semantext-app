"""Every normalisation of text an agent or a page can send is linear, and is unicodedata's own (round 5, items N1 to N3:
semantext/normal.py).

The finding (Orithises, round-4 attack on actclass, finding 3): unicodedata.normalize takes time in the square of the text
on two shapes an agent can send. A long run of combining marks, since canonical reordering is an insertion sort: `git push
a` + U+0316 U+0301 x 32,731 took 1.4 s through decide.decide, and 26 classes in descending order about 3 s at 64 KiB. And
a text that expands a lot, since the decomposition buffer grows 10 characters at a time: 64 Ki x U+FDFA took 0.52 s in
normalize alone and 0.67 s through decide.decide. The same call read the person's words (reading.normalize), a model's
proposal and the person's card (model._plain), a request's title (inbox._reads_as) and the paths a plug-in, a work fact or
a run record names (sources/closed.py).

This file holds four things:
  1. EQUALITY. normal.normalize(form, t) is unicodedata.normalize(form, t), in the four forms: every code point of this
     Python's Unicode inside a long text, every pair that composes or reorders placed across a cut (and a sample of
     starter-mark-mark triples), a seeded fuzz over all planes, and the corpora and messages of the readers. A text of
     PIECE characters or fewer goes to unicodedata whole, so each text here is longer: the cut-and-sort path runs.
  2. LINEAR. Each shape at 16, 64, 256 and 1024 KiB grows about x4 per x4 of text, and 64 KiB is under 0.1 s in the helper.
  3. THE CALL SITES. Each goes through the helper (an AST guard and a spy), decides what it decided with unicodedata (a
     differential on the corpora, and must-refuse controls: a fullwidth letter, a ligature, the hyphens NFKC folds, a key
     folded by NFKC), and is linear end to end: decide.decide on 64 KiB of each shape under 0.5 s (the attacker's own case
     among them), POST /api/read at its cap under 1 s, the proxy's reading of a 1 MiB message under 1 s, and the model
     point, the inbox and the closed-places check on long text.
  4. WHY NOT UAX #15's STREAM-SAFE FORMAT: the path that U+034F after thirty marks would open stays closed.
"""
from __future__ import annotations

import ast
import functools
import json
import random
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from semantext import actclass, api, cli, decide, inbox, model, normal, proxy, reading
from semantext.feed import WITHHELD
from semantext.server import READ_BODY
from semantext.sources import closed
from tests.test_decide import call, msg, space_of, text
from tests.test_reading import ATTACK_R1, CASES

K = 1024
PIECE = normal.PIECE
FORMS = ("NFC", "NFD", "NFKC", "NFKD")
FILL = "\u4e00"        # a starter that decomposes to nothing and composes with nothing: the space between test cases
DATA = Path(__file__).parent / "data" / "actclass"
# 26 combining classes in descending order (240 down to 1): the reversed run an insertion sort pays most for
DESC26 = "".join(map(chr, [0x0345, 0x035D, 0x035C, 0x0315, 0x0301, 0x0316, 0x031B, 0x0321, 0x0F74, 0x0F72, 0x0F71,
                           0x0EC8, 0x0EB8, 0x0E48, 0x0E38, 0x0652, 0x0651, 0x0650, 0x064F, 0x064E, 0x064D, 0x064C,
                           0x064B, 0x05B1, 0x05B0, 0x0334]))


def _differs(t: str) -> list:
    """The forms in which the helper and unicodedata disagree on t: none, anywhere."""
    return [f for f in FORMS if normal.normalize(f, t) != unicodedata.normalize(f, t)]


@functools.lru_cache(maxsize=None)
def _unicode():
    """One walk of every code point of this Python's Unicode: a mark of each combining class, every mark, the
    compatibility characters, every primary composition (a pair that composes; Hangul's L+V and LV+T added, which the
    data gives by rule), and the starters whose decomposition begins with a mark (U+0F73, U+FF9E ...)."""
    by_class, marks, compat, pairs, leading = {}, [], [], [], []
    for cp in range(0x110000):
        ch = chr(cp)
        k = unicodedata.combining(ch)
        if k:
            marks.append(ch)
            by_class.setdefault(k, ch)
        d = unicodedata.decomposition(ch)
        if not d:
            continue
        if d.startswith("<"):
            compat.append(ch)
        else:
            two = "".join(chr(int(x, 16)) for x in d.split())
            if len(two) == 2 and unicodedata.normalize("NFC", two) == ch:
                pairs.append(two)
        if not k and any(unicodedata.combining(unicodedata.normalize(f, ch)[0]) for f in ("NFD", "NFKD")):
            leading.append(ch)
    lead_j = [chr(c) for c in range(0x1100, 0x1113)]
    vowel_j = [chr(c) for c in range(0x1161, 0x1176)]
    tail_j = [chr(c) for c in range(0x11A8, 0x11C3)]
    pairs += [a + b for a in lead_j for b in vowel_j]
    pairs += [chr(0xAC00 + 28 * i) + t for i in range(len(lead_j) * len(vowel_j)) for t in tail_j]   # every LV, every T
    return by_class, marks, compat, pairs, leading


def _placed(cases: list, lead: int) -> str:
    """One text holding each case (all of one length), each placed so that `lead` of its characters fall before a cut
    (a multiple of PIECE): lead 0 puts the cut just before it, 1 after its first character, and so on."""
    size = len(cases[0])
    return FILL * (PIECE - lead) + (FILL * (PIECE - size)).join(cases) + FILL * PIECE


def _across_cuts(cases, leads) -> list:
    """Each case at each lead, 64 to a text; a text that differs is taken apart to name its cases."""
    bad, by_len = [], {}
    for c in cases:
        by_len.setdefault(len(c), []).append(c)
    for size, group in sorted(by_len.items()):
        for lead in (x for x in leads if x <= size):
            for i in range(0, len(group), 64):
                chunk = group[i:i + 64]
                if _differs(_placed(chunk, lead)):
                    bad += [(ascii(c), lead) for c in chunk if _differs(_placed([c], lead))]
    return bad


# =================================================================================================================
# 1. equality
# =================================================================================================================
def test_the_walk_finds_what_it_must():   # the corpora below are live: a walk that found nothing would pass anything
    by_class, marks, compat, pairs, leading = _unicode()
    # the counts are the running Python's Unicode: 872 marks in Unicode 13 (Python 3.10), over 900 from Unicode 14
    assert len(by_class) > 50 and len(marks) > 800 and len(compat) > 3000 and len(pairs) > 10_000
    assert {"\u0f73", "\u0f75", "\u0f81", "\uff9e", "\uff9f"} <= set(leading)
    assert {"e\u0301", "\u1100\u1161", "\uac00\u11a8", "=\u0338", "\u304b\u3099"} <= set(pairs)
    # the filler is inert: no decomposition, class 0, in no composition
    assert unicodedata.decomposition(FILL) == "" and not unicodedata.combining(FILL)
    assert all(FILL not in p for p in pairs)


@pytest.mark.parametrize("shift", [0, 37])
def test_every_code_point_in_a_long_text_is_normalised_as_unicodedata_does(shift):
    """All 1,114,112 code points, 256 in a row per text (so each text takes the cut-and-sort path), at two alignments
    to the cuts."""
    bad = []
    for start in range(0, 0x110000, 256):
        t = FILL * shift + "".join(map(chr, range(start, min(start + 256, 0x110000))))
        if _differs(t):
            bad.append(hex(start))
    assert not bad, bad[:20]


def _pairs() -> list:
    """Every pair whose two characters act on each other: each primary composition (Hangul's too), each order of two
    combining classes, each starter that decomposes to a mark beside a mark of each class, and each character whose
    decomposition begins with a composition's second half, after that half's first characters."""
    by_class, marks, compat, comps, leading = _unicode()
    reps = list(by_class.values())
    out = set(comps)
    out |= {x + y for x in reps for y in reps}
    out |= {x + y for x in leading for y in reps} | {y + x for x in leading for y in reps}
    firsts: dict = {}
    for p in comps:
        firsts.setdefault(p[1], []).append(p[0])
    for ch in compat + leading:
        for form in ("NFD", "NFKD"):
            out |= {a + ch for a in firsts.get(unicodedata.normalize(form, ch)[0], ())[:40]}
    return sorted(out)


def test_every_pair_that_composes_or_reorders_is_normalised_alike_across_a_cut():
    """Each pair before a cut, across it and after it. The decomposition may be cut anywhere; the canonical order is
    mended where pieces meet; composition is one pass over the whole: a pair across a cut is where any of that breaks."""
    pairs = _pairs()
    assert len(pairs) > 15_000
    bad = _across_cuts(pairs, (0, 1, 2))
    assert not bad, bad[:10]


def test_a_starter_and_two_marks_across_a_cut_are_normalised_alike():
    """A sample of triples: a starter, a mark of another class, then the mark the starter composes with (blocked or
    not, moved past the other or not), with the cut at each of the four places."""
    by_class, marks, compat, comps, leading = _unicode()
    reps = list(by_class.values())
    rng = random.Random(1108)
    takes_a_mark = [p for p in comps if unicodedata.combining(p[1])]
    triples = sorted({p[0] + rng.choice(reps) + p[1] for p in rng.choices(takes_a_mark, k=3000)}
                     | {p[0] + p[1] + rng.choice(reps) for p in rng.choices(takes_a_mark, k=1500)})
    assert len(triples) > 3000
    bad = _across_cuts(triples, (0, 1, 2, 3))
    assert not bad, bad[:10]


def _fuzz(n: int, seed: int) -> list:
    """Texts over all planes, weighted to marks (and runs of them, of any length), Hangul jamo and syllables,
    compatibility characters, the two halves of compositions and the starters that decompose to marks."""
    by_class, marks, compat, comps, leading = _unicode()
    rng = random.Random(seed)
    jamo = ([chr(c) for c in range(0x1100, 0x1200)] + [chr(c) for c in range(0xA960, 0xA980)]
            + [chr(c) for c in range(0xD7B0, 0xD800)] + [chr(c) for c in range(0x3131, 0x318F)]
            + [chr(0xAC00 + rng.randrange(11172)) for _ in range(400)])
    pools = [marks, jamo, compat, [p[0] for p in comps], [p[1] for p in comps], leading,
             [chr(c) for c in range(0x20, 0x7F)]]
    weights = [30, 15, 15, 10, 10, 5, 10]
    out = []
    for _ in range(n):
        size = rng.choice((rng.randint(PIECE + 1, 200), rng.randint(200, 800), rng.randint(800, 2500)))
        t: list = []
        while len(t) < size:
            r = rng.random()
            if r < 0.05:
                t.append(chr(rng.randrange(0x110000)))                                     # any plane
            elif r < 0.10:
                t.extend(rng.choice(marks) for _ in range(rng.randint(2, 300)))           # a run of marks
            else:
                t.append(rng.choice(rng.choices(pools, weights)[0]))
        out.append("".join(t[:size]))
    return out


def test_a_seeded_fuzz_over_all_planes_is_normalised_as_unicodedata_does():
    bad = [ascii(t[:60]) for t in _fuzz(1200, 20261108) if _differs(t)]
    assert not bad, bad[:5]


def _commands() -> list:
    """Every call in the actclass corpora, as (tool, input)."""
    out = []
    for f in sorted(DATA.glob("*.json")):
        v = json.loads(f.read_text(encoding="utf-8"))
        rows = v if isinstance(v, list) else [r for x in v.values() if isinstance(x, list) for r in x]
        for r in rows:
            if not isinstance(r, dict):
                continue
            inp = r.get("inp", r.get("cmd"))
            tool = r.get("tool") or ("PowerShell" if r.get("shell") in ("ps", "cmd") else "Bash")
            if isinstance(inp, (str, list)):
                inp = {"command": inp}
            if isinstance(inp, dict):
                out.append((tool, inp))
    return out


def _messages() -> list:
    """The reader's own messages: its cases, the attack it was built against, their offers and house rules."""
    out = [m for m, *_ in CASES]
    for m, _act, offer, house in ATTACK_R1:
        out += [m] + ([offer] if offer else []) + list(house)
    return [m for m in dict.fromkeys(out) if m]


def _texts() -> list:
    out = []
    for _tool, inp in _commands():
        c = inp.get("command")
        out.append(c if isinstance(c, str) else " ".join(map(str, c)) if isinstance(c, list) else json.dumps(inp))
    return out + _messages()


def _long(t: str) -> list:
    """t made long enough for the cut-and-sort path, three ways: after a run of é, twice with marks between, repeated."""
    return ["\u00e9" * PIECE + t, t + "\u0301\u0316" + t + FILL * PIECE, (t + "\u3000") * (1 + 2 * PIECE // (len(t) + 1))]


def test_the_corpora_and_messages_are_normalised_as_unicodedata_does():
    texts = _texts()
    assert len(texts) > 4000
    bad = [ascii(v[:60]) for t in texts for v in [t] + _long(t) if _differs(v)]
    assert not bad, bad[:5]


def test_short_ascii_and_refused_input_go_to_unicodedata_unchanged():
    assert normal.nfkc("git push") == "git push" and normal.nfc("") == ""
    s = "x" * (10 * PIECE)                                   # ASCII: returned as it is, whatever its length
    assert normal.nfkc(s) is unicodedata.normalize("NFKC", s)
    for bad_form in ("nfc", "NFX", ""):                      # unicodedata's own refusal, word for word
        with pytest.raises(ValueError):
            normal.normalize(bad_form, "\u00e9" * 100)
    with pytest.raises(TypeError):
        normal.nfkc(None)


# =================================================================================================================
# 2. linear: the helper alone
# =================================================================================================================
SHAPES = {
    # the finding's own: a run of marks out of order (two classes; 26 descending), and a text that expands a lot
    "two_marks": lambda n: "git push a" + "\u0316\u0301" * ((n - 10) // 2),
    "desc26": lambda n: "a" + (DESC26 * (n // 26 + 1))[: n - 1],
    "fdfa": lambda n: "\ufdfa" * n,
    "cjk_compat": lambda n: ("\u3316\u3389" * (n // 2 + 1))[:n],          # 1 MiB of these has no ASCII at all
    "one_mark": lambda n: "a" + "\u0316" * (n - 1),
    "hangul_lvt": lambda n: ("\u1100\u1161\u11a8" * (n // 3 + 1))[:n],
    "hangul_v": lambda n: "\u1100" + "\u1161" * (n - 1),
    "hangul_syllables": lambda n: ("\uac01\ud7a3" * (n // 2 + 1))[:n],
    # aimed at the helper itself: a starter that decomposes to marks out of order with its neighbours at every cut,
    # and expansion with marks out of order between
    "tibetan_split": lambda n: ("\u0f74\u0f73" * (n // 2 + 1))[:n],
    "fdfa_marks": lambda n: ("\ufdfa\u0301\u0316" * (n // 3 + 1))[:n],
}
CANONICAL = ("two_marks", "desc26", "one_mark", "hangul_lvt", "hangul_syllables", "tibetan_split")   # closed.py's NFC, NFD
LADDER = (16 * K, 64 * K, 256 * K, K * K)


def _clock(fn, *args) -> float:
    t0 = time.perf_counter()
    fn(*args)
    return time.perf_counter() - t0


def _best(fn, *args, runs=2) -> float:
    return min(_clock(fn, *args) for _ in range(runs))


def _ladder_params():
    return ([pytest.param(name, "NFKC", id=f"{name}-NFKC") for name in SHAPES]
            + [pytest.param(name, form, id=f"{name}-{form}") for name in CANONICAL for form in ("NFC", "NFD")])


@pytest.mark.parametrize("name,form", _ladder_params())
def test_each_shape_grows_about_four_times_per_four_times_the_text(name, form):
    """16, 64, 256 and 1024 KiB: each step x4 the text and under x6 the time (quadratic is x16), and 64 KiB under 0.1 s
    in the helper alone. A slow step is measured again before it counts (the machine may be busy)."""
    gen = SHAPES[name]
    texts = {n: gen(n) for n in LADDER}
    times = {n: _clock(normal.normalize, form, texts[n]) for n in LADDER}
    for small, big in zip(LADDER, LADDER[1:]):
        if times[big] >= 6 * times[small] + 0.01:
            times[small] = _best(normal.normalize, form, texts[small], runs=3)
            times[big] = _best(normal.normalize, form, texts[big], runs=3)
        assert times[big] < 6 * times[small] + 0.01, (name, form, {k // K: round(v, 4) for k, v in times.items()})
    if times[64 * K] >= 0.1:
        times[64 * K] = _best(normal.normalize, form, texts[64 * K], runs=3)
    assert times[64 * K] < 0.1, (name, form, times[64 * K])


def test_unicodedata_itself_is_quadratic_on_the_findings_shape():
    """The finding, pinned: unicodedata.normalize on the attacker's run of marks, at 4 KiB then 16 KiB (x4 the text),
    takes far more than x4 the time; the helper does not. Where CPython's own normalize is linear on this shape the
    finding does not apply and this says so, as a skip: the first Linux runs (Python 3.10 and 3.12, 15 November 2026)
    measured 0.1 ms and 0.45 ms, where the Windows builds of 3.11 and 3.14 take over 20 ms for the larger text."""
    small, big = SHAPES["two_marks"](4 * K), SHAPES["two_marks"](16 * K)
    assert _best(normal.nfkc, big) < 6 * _best(normal.nfkc, small) + 0.005      # the helper is linear everywhere
    t_small, t_big = _best(unicodedata.normalize, "NFKC", small), _best(unicodedata.normalize, "NFKC", big)
    if not (t_big > 8 * t_small and t_big > 0.02):
        pytest.skip(f"unicodedata.normalize is not quadratic on this build ({t_small:.5f} s, then {t_big:.5f} s): "
                    "the helper is not needed here, and does no harm")


# =================================================================================================================
# 3. the call sites
# =================================================================================================================
_NORMALISERS = ("normalize", "is_normalized")   # is_normalized normalises whole on a MAYBE


def _calls_to_normalize(tree: ast.AST) -> list:
    """Every spelling of unicodedata's normaliser a source file can use without the helper (close-1 finding 2: the
    first guard matched only `unicodedata.normalize(`, and passed 9 of 12 spellings). Found by name, not call shape:
    - `.normalize` / `.is_normalized` on a name that holds the module (`import unicodedata as ud`, `u = unicodedata`),
      or on `unicodedata.ucd_3_2_0`; this also catches functools.partial(unicodedata.normalize, ...);
    - getattr(<module>, "normalize");
    - importing either name (or *) from unicodedata.
    LIMIT, named: a module reached by importlib.import_module("unicodedata"), and the standard library's own
    normalisations (urllib's netloc check, bounded to Latin-1 text on the server's request path), are not seen here;
    the dynamic spy test below catches the call sites that matter."""
    mods = {"unicodedata"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.asname for a in node.names if a.name == "unicodedata" and a.asname}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in mods:
            mods |= {t.id for t in node.targets if isinstance(t, ast.Name)}

    def holds_module(v: ast.AST) -> bool:
        return (isinstance(v, ast.Name) and v.id in mods) or (
            isinstance(v, ast.Attribute) and v.attr == "ucd_3_2_0" and holds_module(v.value))

    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _NORMALISERS and holds_module(node.value):
            out.append(node.lineno)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and len(node.args) >= 2 and holds_module(node.args[0]) and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in _NORMALISERS):
            out.append(node.lineno)
        if isinstance(node, ast.ImportFrom) and node.module == "unicodedata" and \
                any(a.name in (*_NORMALISERS, "*") for a in node.names):
            out.append(node.lineno)
    return sorted(set(out))


@pytest.mark.parametrize("src", [
    "import unicodedata\nunicodedata.normalize('NFC', 'x')",
    "import unicodedata as ud\nud.normalize('NFC', 'x')",
    "import unicodedata\nu = unicodedata\nu.normalize('NFC', 'x')",
    "import unicodedata\ngetattr(unicodedata, 'normalize')('NFC', 'x')",
    "import unicodedata, functools\nfunctools.partial(unicodedata.normalize, 'NFC')",
    "import unicodedata\nunicodedata.ucd_3_2_0.normalize('NFC', 'x')",
    "import unicodedata\nunicodedata.is_normalized('NFC', 'x')",
    "from unicodedata import normalize as n\nn('NFC', 'x')",
])
def test_the_guard_sees_every_spelling_of_the_call(src):   # close-1 finding 2: fails on the first guard for 6 of these
    assert _calls_to_normalize(ast.parse(src)) != []


@pytest.mark.parametrize("src", [
    "import unicodedata\nunicodedata.category('x')\nunicodedata.combining('x')",
    "import unicodedata as ud\nud.name('x')",
    "class A:\n    def normalize(self): pass\nA().normalize()",
    "from semantext import normal\nnormal.nfkc('x')",
])
def test_the_guard_leaves_other_calls_alone(src):   # must-pass: it is not a ban on the module
    assert _calls_to_normalize(ast.parse(src)) == []


def test_no_module_but_the_helper_calls_unicodedata_normalize():
    """The guard: a bare call anywhere else in the package is the quadratic one again (write normal.nfkc and kin)."""
    root = Path(normal.__file__).parent
    bad = [(str(f.relative_to(root)), line) for f in sorted(root.rglob("*.py")) if f.name != "normal.py"
           for line in _calls_to_normalize(ast.parse(f.read_text(encoding="utf-8")))]
    assert not bad, bad
    assert _calls_to_normalize(ast.parse("import unicodedata\nunicodedata.normalize('NFC', 'x')\n")) == [2]   # it can fail


NAMES = closed._names([
    {"id": "notes", "form": "segment", "segment": "private-notes"},
    {"id": "cafe", "form": "substring", "substrings": ["caf\u00e9"]},
    {"id": "resume", "form": "segment", "segment": "re\u0301sume\u0301-box"},
    {"id": "vault", "form": "segment-prefix-except", "prefix": "vaultx",
     "segment_chars_after_prefix": "word characters (Unicode, as \\w), '.' and '-'",
     "except_when_remainder_starts": "-public not followed by an ASCII letter or digit"},
])


def test_every_call_site_goes_through_the_helper(monkeypatch):
    """A spy on normal.normalize: each site, given a long non-ASCII text, calls it (put a bare unicodedata call back at
    one and its row fails)."""
    seen: list = []
    real = normal.normalize

    def spy(form, t):
        seen.append(form)
        return real(form, t)

    monkeypatch.setattr(normal, "normalize", spy)
    closed._forms_of.cache_clear()
    long = "\u00e9" * (2 * PIECE)
    sites = {
        "actclass._shell_acts": lambda: actclass.acts_of_call("Bash", {"command": "echo " + long}),
        "reading.normalize": lambda: reading.normalize(long),
        "inbox._reads_as": lambda: inbox._reads_as(long),
        "model._plain": lambda: model._plain(long),
        "closed._fold": lambda: closed._fold(long),
        "closed._component_forms": lambda: closed._component_forms("Q:/" + long),
        "closed._forms_of": lambda: closed._forms_of(("x" + long,), "NFD"),
        "closed._fields_hit": lambda: closed._fields_hit(NAMES[0], "Q:/" + long),
    }
    missed = []
    for site, fn in sites.items():
        seen.clear()
        fn()
        if not seen:
            missed.append(site)
    closed._forms_of.cache_clear()
    assert not missed, missed


# ---- decides what it decided: a differential against unicodedata on the corpora ------------------------------------
def _fullwidth(t: str) -> str:
    """Each printable ASCII character as its fullwidth form, and a space as U+3000: NFKC gives t back."""
    return "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else "\u3000" if c == " " else c for c in t)


def _marked(t: str) -> str:
    """t with a run of 31 to 56 marks, classes descending, at its middle: past the thirty Stream-Safe would cap."""
    k = 31 + len(t) % 26
    return t[: len(t) // 2] + (DESC26 * 3)[:k] + t[len(t) // 2:]


def _with_unicodedata(monkeypatch):
    """From here on every call site normalises as 3e5e2ac did: unicodedata.normalize itself."""
    monkeypatch.setattr(normal, "normalize", unicodedata.normalize)
    closed._forms_of.cache_clear()


def test_actclass_names_every_corpus_call_as_it_did_with_unicodedata(monkeypatch):
    calls = []
    for tool, inp in _commands():
        calls.append((tool, inp))
        c = inp.get("command")
        if isinstance(c, str):
            calls += [(tool, {**inp, "command": _fullwidth(c)}), (tool, {**inp, "command": _marked(c)})]
    mine = [actclass.acts_of_call(t, i) for t, i in calls]
    _with_unicodedata(monkeypatch)
    base = [actclass.acts_of_call(t, i) for t, i in calls]
    diff = [(t, ascii(str(i))[:90], m, b) for (t, i), m, b in zip(calls, mine, base) if m != b]
    assert len(calls) > 10_000 and not diff, diff[:5]


def test_a_fullwidth_command_is_still_folded_and_named_as_its_ascii_self():   # must-refuse: the fold still happens
    """NFKC turns a fullwidth command into the ASCII one, so its acts are the ASCII command's: for every string command
    of the corpora (those over PIECE characters through the cut-and-sort path)."""
    rows = [(t, i) for t, i in _commands() if isinstance(i.get("command"), str)]
    diff = [(t, i["command"][:60]) for t, i in rows
            if actclass.acts_of_call(t, {**i, "command": _fullwidth(i["command"])}) != actclass.acts_of_call(t, i)]
    named = sum(bool(actclass.acts_of_call(t, i)) for t, i in rows if len(i["command"]) > PIECE)
    assert named > 300 and not diff, diff[:5]


def test_the_reader_reads_every_message_as_it_did_with_unicodedata(monkeypatch):
    msgs = _messages()
    texts = msgs + [_fullwidth(m) for m in msgs] + [_marked(m) for m in msgs] + [m + " " + "\u00e9" * PIECE for m in msgs]
    material = tuple(a for a in reading.ACTS if a in reading.MATERIAL)
    mine = [reading.report(t) for t in texts]
    held = [reading.held_by_words(t, material) for t in texts]
    assert any(held) and not all(held)                                                 # live both ways
    _with_unicodedata(monkeypatch)
    assert [reading.report(t) for t in texts] == mine
    assert [reading.held_by_words(t, material) for t in texts] == held


def _paths() -> list:
    """Paths near each closed name: as written, NFC and NFD spellings, marks and decomposable letters beside and inside
    it, long ones (over PIECE characters, so the cut-and-sort path runs) and runs of marks past thirty."""
    lits = ["private-notes", "caf\u00e9", "cafe\u0301", "re\u0301sume\u0301-box", "r\u00e9sum\u00e9-box", "vaultx2",
            "vaultx-public", "VAULTX-PUBLIC2"]
    adds = ["", "\u0301", "\u0316\u0301", "\u0958", "\u00e9", "\u0338", DESC26[:31], "\u0316" * 30 + "\u0301"]
    out = []
    for lit in lits:
        for a in adds:
            for p in ("Q:/d/" + lit + a + "/z", "Q:/d/" + a + lit, "Q:\\d\\" + lit[:3] + a + lit[3:] + "\\z"):
                out += [p, "Q:/" + "x/" * 40 + p[3:], "Q:/" + "\u00e9/" * 40 + p[3:]]
    return out


def test_the_closed_places_check_judges_every_path_as_it_did_with_unicodedata(monkeypatch):
    paths = _paths()
    names = list(NAMES)
    mine = [(closed._named(p, names), closed._judge(p, names + ["Q:\\shut"]), closed._fold(p),
             closed._component_forms(p)) for p in paths]
    assert sum(m[0] for m in mine) > 100 and sum(not m[0] for m in mine) > 100      # live both ways
    _with_unicodedata(monkeypatch)
    base = [(closed._named(p, names), closed._judge(p, names + ["Q:\\shut"]), closed._fold(p),
             closed._component_forms(p)) for p in paths]
    diff = [ascii(p) for p, m, b in zip(paths, mine, base) if m != b]
    assert not diff, diff[:5]


def test_the_key_checks_and_the_inbox_fold_answer_as_they_did_with_unicodedata(monkeypatch):
    key = "sk-" + "a1b2c3d4" * 3
    texts = _messages() + [key, _fullwidth(key), "x \u00e9 " * 30 + _fullwidth(key), "MODEL proposal",
                           _fullwidth("MODEL") + " proposal " + "\u00e9" * PIECE, _marked("MODEL " + key)]
    mine = [(model._secret(t), model._plain(t), inbox._reads_as(t), inbox.model_shaped("ai", t)) for t in texts]
    _with_unicodedata(monkeypatch)
    base = [(model._secret(t), model._plain(t), inbox._reads_as(t), inbox.model_shaped("ai", t)) for t in texts]
    assert mine == base


# ---- the must-refuse controls: what NFKC changes still changes, through the cut-and-sort path ---------------------
def test_what_nfkc_folds_is_still_folded():
    long_tail = " " + "\u00e9" * PIECE
    assert normal.nfkc("\uff47\uff49\uff54 \uff50\uff55\uff53\uff48" + long_tail).startswith("git push")   # fullwidth
    assert normal.nfkc("\ufb01nd . -delete" + long_tail).startswith("find . -delete")                  # a ligature
    assert normal.nfkc("sk\uff0dabc" + long_tail).startswith("sk-abc")                                  # fullwidth hyphen
    assert normal.nfkc("sk\ufe63abc" + long_tail).startswith("sk-abc")                                  # small hyphen
    assert normal.nfkc("\u00e9" * (PIECE - 1) + "e\u0301").endswith("\u00e9\u00e9")                    # composed at a cut


@pytest.mark.parametrize("cmd,acts", [
    ("\uff47\uff49\uff54 \uff50\uff55\uff53\uff48 origin main", ("push",)),
    ("\uff47\uff49\uff54 \uff50\uff55\uff53\uff48 origin main # " + "\u00e9" * PIECE, ("push",)),
    ("\ufb01nd . -name '*.log' -delete", ("delete",)),
    ("\ufb01nd . -name '*.log' -delete # " + "\uff58" * PIECE, ("delete",)),
    ("echo " + "\u00e9" * (PIECE - 10) + " && \uff52\uff4d -rf build", ("delete",)),   # the cut between its r and m
], ids=["fullwidth", "fullwidth-long", "ligature", "ligature-long", "rm-across-a-cut"])
def test_a_fullwidth_or_ligature_command_is_still_named(cmd, acts, monkeypatch):   # must-refuse
    assert actclass.acts_of_call("Bash", {"command": cmd}) == acts
    monkeypatch.setattr(actclass.normal, "nfkc", lambda t: t)          # the control can fail: without the fold, nothing
    assert actclass.acts_of_call("Bash", {"command": cmd}) != acts


def test_a_key_folded_by_nfkc_is_still_found_by_the_key_checks():   # must-refuse
    key = "sk-" + "a1b2c3d4" * 3
    for k in (_fullwidth(key), key.replace("-", "\uff0d"), key.replace("-", "\ufe63")):
        for t in (k, "x \u00e9 " * 30 + k + " y", "\u00e9" * (PIECE - 2) + k):          # short, long, across a cut
            assert model._secret(t), ascii(t[-40:])
            shown = [r.to_dict()["clause"] for r in reading.read("My key is " + t).readings]   # the normalised clause, scrubbed
            assert WITHHELD in shown and not any(key in s for s in shown), ascii(t[-40:])
    assert not model._secret("x \u00e9 " * 30 + "sk-short")                              # must-pass: no key, no find


def test_a_lookalike_model_label_is_still_refused_by_the_inbox():   # must-refuse
    long = " " + "\u00e9" * PIECE
    assert inbox.model_shaped("ai", _fullwidth("MODEL") + " proposal" + long)
    assert inbox.model_shaped(_fullwidth("MODEL"), "a title")
    assert not inbox.model_shaped("ai", "MODELS to deploy" + long)                       # must-pass: another word


def test_the_person_s_fullwidth_hold_still_holds():   # must-refuse
    words = _fullwidth("Don't push it yet.") + " Thanks, " + "\u00e9" * PIECE
    assert reading.held_by_words(words, ("push",))["act"] == "push"
    assert reading.read(words).readings[0].clause.startswith("Don't push it yet")


def test_a_closed_name_is_closed_whatever_the_spelling_through_the_long_path():   # must-refuse, and its near miss
    deep = "Q:/" + "x/" * 40
    names = list(NAMES)
    for p in ("caf\u00e9/a", "cafe\u0301/a", "CAFE\u0301/a", "r\u00e9sum\u00e9-box/a", "private-notes/a"):
        assert closed._judge(deep + p, names) and api.is_closed_place(deep + p, closed.ReadContext("", (), tuple(NAMES)))
    for p in ("cafe/a", "resume-box/a", "private-notes2/a"):
        assert not closed._judge(deep + p, names)                                         # must-pass
    # the composition falls across a cut: "e" the last character of a piece, U+0301 the first of the next
    cut = "Q:/" + "\u00e9" * (PIECE - 7) + "caf"
    assert len(cut) == PIECE - 1 and closed._judge(cut + "e\u0301/x", names)
    assert not closed._judge(cut + "e/x", names)                                          # must-pass: no mark, no é


# ---- linear end to end ---------------------------------------------------------------------------------------------
WORDS = "Don't push, publish, delete, send, pay or download anything."
CODER = ("id: coder\nkind: agent\nidentity: claude-code\nmodels: [claude]\ntools: [bash]\n"
         "budgets: {asks_open: 400}\ntests: []\n")


@pytest.fixture(scope="module")
def space(tmp_path_factory):
    return space_of(tmp_path_factory.mktemp("normal"), {"coder.yaml": CODER}, drop=("shell-held.yaml",))


_n = [0]


def _decide(space, tmp_path, cmd, words=WORDS, offer=None):
    """One turn holding the call, with the person's words: the time decide.decide takes, and what it decided."""
    _n[0] += 1
    asks = decide.Asks(tmp_path / f"asks{_n[0]}.json", run="r")
    t0 = time.perf_counter()
    out = decide.decide(space, "s", "coder", "claude", msg(text("Doing it now."), call("Bash", {"command": cmd})),
                        f"c{_n[0]}", asks, 100.0, words=words, offer=offer)
    return time.perf_counter() - t0, out


def test_the_attackers_own_command_is_held_in_under_half_a_second(space, tmp_path):
    """Finding 3's exact input: `git push a` + U+0316 U+0301 x 32,731 (65,472 characters), the words "Don't push yet.".
    1.4 s at 3e5e2ac; held then and now."""
    cmd = "git push " + "a" + "\u0316\u0301" * 32731
    assert len(cmd) == 65_472
    best, out = min((_decide(space, tmp_path, cmd, words="Don't push yet.") for _ in range(2)), key=lambda r: r[0])
    assert out.held and best < 0.5, best
    # below Python 3.11 the act reader's backstop is 2 KiB, and a longer command counts as every act (E9)
    want = ("push",) if len(cmd) <= actclass.MAX_COMMAND else actclass.ORDER
    assert actclass.acts_of_call("Bash", {"command": cmd}) == want


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_decide_on_a_64_kib_command_of_each_shape_is_under_half_a_second(name, space, tmp_path):
    cmd = SHAPES[name](64 * K - 64)
    best = min(_decide(space, tmp_path, cmd)[0] for _ in range(2))
    assert best < 0.5, (name, best)


@pytest.fixture
def server(tmp_path, monkeypatch):
    from semantext.server import make_server
    from semantext.store import Store
    home = tmp_path / "home"
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    assert cli.main(["--home", str(home), "init"]) == 0
    s = make_server(Store.open(home), port=0)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def _post(server, raw: bytes):
    """POST /api/read as the page does: its own Origin, header and Referer."""
    host = f"127.0.0.1:{server.server_address[1]}"
    req = urllib.request.Request(f"http://{host}/api/read", data=raw, headers={
        "Content-Type": "application/json", "X-Semantext": "1", "Origin": f"http://{host}", "Referer": f"http://{host}/v2"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _at_the_cap(gen, offer: bool) -> bytes:
    """A body as near READ_BODY bytes as it goes: the message of the shape alone, or the message and an offer of the
    shape, half the cap each, with every act asked for."""
    n = READ_BODY // (2 if offer else 1)
    while True:
        body = {"message": "Publish it. " + gen(n)}
        if offer:
            body.update(offer="Shall I publish it? " + gen(n), acts=list(reading.ACTS))
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(raw) <= READ_BODY:
            return raw
        n -= max(1, (len(raw) - READ_BODY) // 6 + 1)


def _read_at_the_cap(server, name, offer):
    """The best of two POSTs of the body at the cap (as decide.decide is timed): the time, after the answer is checked."""
    raw = _at_the_cap(SHAPES[name], offer)
    assert READ_BODY - 64 <= len(raw) <= READ_BODY
    best = 9e9
    for _ in range(2):
        t0 = time.perf_counter()
        code, got = _post(server, raw)
        best = min(best, time.perf_counter() - t0)
        assert code == 200 and "publish" in got["acts"], (name, code)
    return best


# At the bound, and why (measured, best of 3 through the route): U+FDFA alone at the cap takes 0.76 s in a process of its
# own and about 1.05 s inside this suite; 3e5e2ac 0.78 s and 1.11 s. The normalisation is about 12 ms of it (60 ms at
# 3e5e2ac): the rest is reading.py reading, scrubbing and sending the 360,000 characters NFKC makes of 20,000 U+FDFA.
# Not strict: it passes on a quiet machine. The fix is reading.py's owner's (see ONE_READING_EACH below).
AT_THE_BOUND = "reading.py's work on the 360,000 characters NFKC makes of 20,000 U+FDFA: 0.76 to 1.05 s, 0.78 to 1.11 at 3e5e2ac"


@pytest.mark.parametrize("name", [pytest.param(n, marks=pytest.mark.xfail(strict=False, reason=AT_THE_BOUND))
                                  if n == "fdfa" else n for n in sorted(SHAPES)])
def test_the_pages_reader_at_its_cap_answers_each_shape_in_under_a_second(name, server):
    """The message fills the route's cap (READ_BODY bytes); the reader reads 20,000 characters of it."""
    dt = _read_at_the_cap(server, name, offer=False)
    assert dt < 1.0, (name, dt)


# The offer is read ONCE per report (reading.report -> _plain_offer, handed on to each act's advice). Until 15 November
# 2026 it was read again for every act (reading.advise -> _plain_offer -> read(offer)): an offer and every act asked for
# was nine readings, 1.5 s for a shape NFKC widens (cjk_compat, found by the first whole-suite runs) and 2 to 4 s for
# U+FDFA. What is left is one cause, the same as AT_THE_BOUND above: one reading works on the text as NFKC gives it, up to
# 18 times the 20,000 characters the reader clips (360,000 for U+FDFA), so the two U+FDFA shapes sit at the 1 s bar here
# as the message alone does. Bounding a reading by the length NFKC gives is still reading.py's to do.
ONE_READING_EACH = ("one reading of the message and one of the offer, each on what NFKC makes of U+FDFA (up to 18x): at "
                    "the 1 s bar; it passes on a quiet machine")


@pytest.mark.parametrize("name", [pytest.param(n, marks=pytest.mark.xfail(strict=False, reason=ONE_READING_EACH))
                                  if n in ("fdfa", "fdfa_marks") else n for n in sorted(SHAPES)])
def test_the_pages_reader_at_its_cap_with_an_offer_and_every_act_answers_in_under_a_second(name, server):
    """The message and an offer of the shape, half the cap each, and every act asked for: the reader's heaviest body."""
    dt = _read_at_the_cap(server, name, offer=True)
    assert dt < 1.0, (name, dt)


@pytest.mark.parametrize("name", sorted(SHAPES))
def test_an_offer_is_read_once_however_many_acts_are_asked(name, server):
    """The law of the offer-once change, as a ratio so that it holds on a slow or busy machine where a bar in seconds
    does not: the message and an offer of the shape (half the cap each) with every act asked for takes no more than
    2.5 times the message alone at the cap, plus 0.2 s. Read once per act it took 3 to 5 times (cjk_compat: 1.55 s
    against 0.48 s), and this test fails on that code."""
    alone = _read_at_the_cap(server, name, offer=False)
    both = _read_at_the_cap(server, name, offer=True)
    assert both <= 2.5 * alone + 0.2, (name, alone, both)


def _proxy_turn(space, tmp_path, gen, n, lead):
    """The proxy's own path: the person's words (the newest user message: `lead`, then n characters of the shape) and
    the offer before them taken from a request (proxy.person_words), then the turn decided on them (decide.decide, which
    reads them: reading.held_by_words)."""
    body = {"messages": [{"role": "assistant", "content": [{"type": "text", "text": "Shall I push it?"}]},
                         {"role": "user", "content": [{"type": "text", "text": lead + " " + gen(n)}]}]}
    t0 = time.perf_counter()
    words, offer = proxy.person_words(body)
    dt, out = _decide(space, tmp_path, 'eval "$CMD"', words=words, offer=offer)
    return time.perf_counter() - t0, out


@pytest.mark.parametrize("lead", [WORDS, "Thanks."], ids=["words-that-hold", "words-that-hold-nothing"])
@pytest.mark.parametrize("name", sorted(SHAPES))
def test_the_proxys_reading_of_a_1_mib_message_is_linear_and_under_a_second(name, lead, space, tmp_path):
    """Stated bound: the newest user message at 1 MiB of each shape is read and the turn decided in under 1 s, and x4
    the message (256 KiB to 1 MiB) is under x6 the time. The proxy keeps 64 KiB of the words (proxy.MAX_WORDS) and the
    reader 20,000 characters of those (reading.MAX_CHARS), so the time is person_words' pass over the 1 MiB, the helper
    on those characters, and the reader on what NFKC makes of them (up to 18 times as many). Words that hold nothing
    make the decision advise every act the opaque call is."""
    gen = SHAPES[name]

    def measure(runs):
        t256, _ = min((_proxy_turn(space, tmp_path, gen, 256 * K, lead) for _ in range(runs)), key=lambda r: r[0])
        t1m, out = min((_proxy_turn(space, tmp_path, gen, K * K, lead) for _ in range(runs)), key=lambda r: r[0])
        return t256, t1m, out

    t256, t1m, out = measure(2)
    if not (t1m < 1.0 and t1m < 6 * t256 + 0.05):      # a slow pair is measured again before it counts
        t256, t1m, out = measure(3)
    if lead == WORDS:
        assert out.held, name                           # words that hold every act hold the opaque call
    assert t1m < 1.0 and t1m < 6 * t256 + 0.05, (name, t256, t1m)


FOLDS = {"model._secret": lambda t: model._secret(t), "model._plain": lambda t: model._plain(t),
         "inbox._reads_as": lambda t: inbox._reads_as(t)}


@pytest.mark.parametrize("fold", sorted(FOLDS))
@pytest.mark.parametrize("name", sorted(SHAPES))
def test_the_model_points_and_the_inboxs_folds_are_linear(name, fold):
    """model._secret folds the person's card and words before any call, and every proposal (at most 4,000 bytes);
    inbox._reads_as folds a request's sender and title (at most 60 and 120 characters). Unbounded here: 16 KiB to 64 KiB
    of each shape is under x6 the time, and 64 KiB under 1 s, most of it the key pattern and the Cf filter over what
    NFKC makes of the text (1.18 million characters for U+FDFA)."""
    small, big = SHAPES[name](16 * K), SHAPES[name](64 * K)
    t_small, t_big = _best(FOLDS[fold], small), _best(FOLDS[fold], big)
    if not (t_big < 1.0 and t_big < 6 * t_small + 0.02):      # a slow pair is measured again before it counts
        t_small, t_big = _best(FOLDS[fold], small, runs=3), _best(FOLDS[fold], big, runs=3)
    assert t_big < 1.0 and t_big < 6 * t_small + 0.02, (name, fold, t_small, t_big)


@pytest.mark.parametrize("name", CANONICAL)
def test_the_closed_places_check_on_a_long_path_is_linear(name):
    """A path at Windows' length limit (30,000 characters) of each shape, judged against four closed names and a closed
    folder: the check normalises it about forty times (three spellings, two aliases, NFC and NFD, per name), each now
    linear. At 3e5e2ac the shapes with marks out of order took over a second for each of those."""
    path = "Q:/d/" + SHAPES[name](30_000) + "/x"
    names = list(NAMES) + ["Q:\\shut"]
    assert _best(closed._judge, path, names) < 1.5, name
    assert _best(closed._fold, path) < 0.2 and _best(closed._component_forms, path) < 0.2, name


# =================================================================================================================
# 4. why not the Stream-Safe Text Format
# =================================================================================================================
def test_the_path_stream_safe_would_open_stays_closed():   # must-refuse
    """UAX #15's Stream-Safe Text Format puts U+034F after every 30 non-starters. Here U+0301 (class 230) follows thirty
    U+0316 (class 220): unicodedata's NFC sorts it past them and composes "é", so the closed name "café" closes the
    path; after a U+034F it could not reach the "e", and the path would open. The helper is unicodedata's, exactly."""
    path = "Q:/d/cafe" + "\u0316" * 30 + "\u0301" + "/x"
    assert "caf\u00e9" in normal.nfc(path) and normal.nfc(path) == unicodedata.normalize("NFC", path)
    stream_safe = path.replace("\u0316" * 30, "\u0316" * 30 + "\u034f")
    assert "caf\u00e9" not in unicodedata.normalize("NFC", stream_safe)        # what the insertion would have done
    names = list(NAMES)
    assert closed._judge(path, names)
    assert api.is_closed_place(path, closed.ReadContext("", (), tuple(NAMES)))
    assert normal.nfkc("a" + DESC26 * 4) == unicodedata.normalize("NFKC", "a" + DESC26 * 4)   # a run of 104, uncapped
