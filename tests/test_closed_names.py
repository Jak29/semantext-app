"""Closures by name, beside closures by path: a "closed_names" list closes a folder or file by its name in any folder.

The entries take a closures file's shape: each has an `id`, a `form` and that form's fields (segment, segment-pair,
segment-prefix-except, segment-or-dotted-prefix, substring, suffix), and may carry the `regex` a reader using Python's
`re` would apply. Semantext matches from the fields, never the regex; the agreement test below holds the two equal.

Every form is tried both ways: a spelling that must be refused, and a near miss beside it that must stay open. Each
name here is made up for the test.
"""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

import pytest

from semantext import api
from semantext.sources import closed as closed_mod

SEP = r"[\\/]"
WORDS = "word characters (Unicode, as \\w), '.' and '-'"


def seg(id_, v):
    return {"id": id_, "form": "segment", "segment": v, "regex": rf"(?:^|{SEP}){re.escape(v)}(?:{SEP}|$)"}


def pair(id_, a, b):
    return {"id": id_, "form": "segment-pair", "segments": [a, b], "needs_separator_before": True,
            "then": ["separator", ":", "end"], "regex": rf"{SEP}{re.escape(a)}{SEP}{re.escape(b)}(?:[\\/:]|$)"}


def prefix(id_, p, rest=None):
    d = {"id": id_, "form": "segment-prefix-except", "prefix": p, "segment_chars_after_prefix": WORDS}
    look = ""
    if rest:
        d["except_when_remainder_starts"] = f"{rest} not followed by an ASCII letter or digit"
        look = f"(?!{re.escape(rest)}(?![a-z0-9]))"
    d["regex"] = rf"(?:^|{SEP}){re.escape(p)}{look}[\w.-]*(?:{SEP}|$)"
    return d


def dotted(id_, v):
    return {"id": id_, "form": "segment-or-dotted-prefix", "segment": v, "or_segment_starts": v + ".",
            "regex": rf"(?:^|{SEP}){re.escape(v)}(?:\.|$|{SEP})"}


def substr(id_, *subs):
    return {"id": id_, "form": "substring", "substrings": list(subs), "regex": "|".join(map(re.escape, subs))}


def suffix(id_, *sufs):
    return {"id": id_, "form": "suffix", "suffixes": list(sufs), "regex": rf"(?:{'|'.join(map(re.escape, sufs))})$"}


ASCII_NAMES = [
    seg("notes", "private-notes"),
    pair("box", "archive", "boxa"),
    prefix("vaultx", "vaultx", "-public"),
    prefix("plainx", "plainx"),
    dotted("rc", ".secretrc"),
    substr("ledger", "ledgerbox", "coinjar.txt"),
    suffix("files", ".vaultfile", ".lockbox"),
    seg("kiss", "kiss-notes"),
]
NAMES = ASCII_NAMES + [
    seg("cafe", "caf\u00e9-notes"),          # composed (NFC)
    seg("resume", "re\u0301sume\u0301-box"),   # decomposed (NFD)
]


def _home(tmp_path, value) -> Path:
    home = tmp_path / "h"
    home.mkdir(exist_ok=True)
    (home / "sources.json").write_text(json.dumps(value) if not isinstance(value, str) else value, encoding="utf-8")
    return home


def _file(tmp_path, value, name="closures.json") -> Path:
    f = tmp_path / name
    f.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
    return f


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    return _home(tmp_path, {"closed": [], "closed_names": NAMES})


def _both(path, home) -> bool:
    """The plug-ins' check and the built-in readers' check, which must agree once the closures are known."""
    a, b = api.is_closed_place(path, home), closed_mod.in_closed_place(path, home)
    assert a == b, (path, a, b)
    return a


def _text(base: Path, rest: str, sep: str) -> str:
    return str(base) + sep + rest.replace("/", sep)


SCHEMED = {"schema": "estate.closures/0", "closed_paths_complete": True}   # a closures file that says its list is whole


def _sub(value, keep):
    return json.loads(json.dumps(value).replace('"@keep"', json.dumps(str(keep))))


# ---- each form, with a near miss beside it ---------------------------------------------------------------------
PAIRS = [
    # segment: the folder, a file in it, a deeper one, case, a trailing separator, streams, Windows' trailing dots
    ("private-notes", "private-notes2"),
    ("private-notes/a.md", "my-private-notes/a.md"),
    ("a/b/c/private-notes/d.md", "a/b/c/notes-private/d.md"),
    ("Private-Notes/a.md", "Private-Notesx/a.md"),
    ("private-notes/", "private-notes-x/"),
    ("private-notes::$INDEX_ALLOCATION/a.md", "private-notesx::$INDEX_ALLOCATION/a.md"),
    ("private-notes./a.md", "private-notes.d/a.md"),
    ("private-notes /a.md", "private-notes x/a.md"),
    # segment-pair: a separator, the pair, then a separator, a ':' or the end
    ("x/archive/boxa", "x/archive/boxab"),
    ("archive/BOXA/a.md", "archive/boxa.txt"),
    ("x/ARCHIVE/boxa:s", "x/archive2/boxa"),
    ("archive/boxa::$INDEX_ALLOCATION/x", "x/archivebox/boxa"),
    # segment-prefix-except: the prefix, then word characters, '.' and '-' to the segment's end
    ("vaultx", "vault"),
    ("vaultx2/a.md", "a-vaultx/a.md"),
    ("VaultX-Private/a.md", "vaultx-public/a.md"),
    ("vaultx-public2/a.md", "VAULTX-PUBLIC/a.md"),
    ("vaultx-publicx", "vaultx-public_x"),
    ("vaultx-public/vaultx-inner/a.md", "vaultx-public/inner/a.md"),
    ("vaultx.d", "vaultx x"),
    ("vaultx_old/a", "notvaultx/a"),
    ("plainx-anything.md", "plain-x"),
    # segment-or-dotted-prefix: the segment exactly, or a segment starting with it and a dot
    (".secretrc", ".secretrcx"),
    (".secretrc.local", "a.secretrc"),
    (".SECRETRC/a", ".secretrc2/a"),
    ("x/.secretrc.example", "x/secretrc"),
    # substring: anywhere in the whole path, a longer name or a folder too
    ("x/my_ledgerbox", "x/ledger-box"),
    ("x/coinjar.txt.d/a", "x/coinjar.json"),
    ("x/MY_COINJAR.TXTX", "x/coinjar txt"),
    ("ledgerbox2/a", "ledgerbo/a"),
    # suffix: at the end of the path only
    ("x/db.vaultfile", "x/db.vaultfile.txt"),
    ("x/DB.LOCKBOX", "x/dbvaultfile"),
    ("db.vaultfile:stream", "db.vaultfil"),
    ("db.vaultfile.", "db.vaultfile-notes"),
    ("x/store.lockbox", "store.vaultfile/inner.txt"),
    # Unicode: a decomposed spelling (as macOS writes) and a composed one name the same folder
    ("cafe\u0301-notes/a.md", "cafe-notes/a.md"),
    ("CAF\u00c9-NOTES", "cafe\u0301-notes2"),
    ("r\u00e9sum\u00e9-box/a.md", "resume-box/a.md"),
    ("re\u0301sume\u0301-box", "r\u00e9sum\u00e9-boxes"),
    # the folding Python's case-insensitive matching does: U+0130, U+0131 as i, U+017F as s, the Kelvin sign as k
    ("K\u0130SS-NOTES", "kis-notes"),
    ("k\u0131ss-notes", "kiss-note"),
    ("ki\u017fs-notes/a", "kiss-notes2/a"),
    ("\u212aiss-notes", "kiss_notes"),
]


@pytest.mark.parametrize("shut, near", PAIRS)
@pytest.mark.parametrize("sep", ["/", "\\"])
def test_a_closed_name_is_refused_and_its_near_miss_is_not(tmp_path, home, shut, near, sep):
    base = tmp_path / "work"
    assert _both(_text(base, shut, sep), home)          # must refuse
    assert not _both(_text(base, near, sep), home)      # must pass


def _parsed():
    return {n.id: n for n in closed_mod._names(NAMES)}


@pytest.mark.parametrize("entry, text, shut", [
    # a segment-pair needs a separator BEFORE its first segment
    ("box", "archive/boxa/x", False), ("box", "/archive/boxa", True), ("box", "\\archive\\boxa\\x", True),
    # a single trailing newline is an end, as Python's `$` takes it; two are not
    ("notes", "x/private-notes\n", True), ("notes", "x/private-notes\n\n", False),
    ("files", "x/db.vaultfile\n", True), ("files", "x/db.vaultfile\n\n", False),
    ("box", "x/archive/boxa\n", True), ("vaultx", "x/vaultx2\n", True), ("rc", "x/.secretrc\n", True),
    # a segment at the very start of a string, with no separator before it
    ("notes", "private-notes", True), ("rc", ".secretrc.local", True), ("vaultx", "vaultx", True),
    # a substring anywhere, across separators' neighbours
    ("ledger", "a\\b\\xcoinjar.txt.bak\\y", True), ("ledger", "coinjar\\txt", False),
])
def test_the_matcher_on_the_string_as_given(entry, text, shut):
    assert closed_mod._matches_text(_parsed()[entry], text) is shut


def _corpus(n=6000, seed=20261029):
    """Invented names and near misses, joined into paths every way the forms treat differently."""
    words = ["a", "notes.md", "x", "Archive", "boxa", "box", "vault", "plain"]
    for e in ASCII_NAMES:
        for lit in (e.get("segments") or []) + [e.get("segment"), e.get("prefix"), e.get("or_segment_starts")] + \
                (e.get("substrings") or []) + (e.get("suffixes") or []):
            if not lit:
                continue
            words += [lit, lit.upper(), lit + "2", "my_" + lit, lit + ".bak", lit[:-1], lit + ":s",
                      lit + "::$INDEX_ALLOCATION", lit + " x", lit + "-public", lit + "-publicx", lit + "_x", lit + "."]
    rng = random.Random(seed)
    heads, joins, tails = ["", "/", "\\", "C:\\", "C:/", "\\\\?\\C:\\"], ["/", "\\"], ["", "/", "\\", "\n", "\n\n", ":"]
    out = []
    for _ in range(n):
        parts = [rng.choice(words) for _ in range(rng.randint(1, 4))]
        j = rng.choice(joins)
        out.append(rng.choice(heads) + j.join(parts) + rng.choice(tails))
    return out


def test_the_matcher_agrees_with_each_entrys_regex():
    corpus = _corpus()
    names = _parsed()
    seen = {e["id"]: [0, 0] for e in ASCII_NAMES}
    for e in ASCII_NAMES:
        pattern = re.compile(e["regex"], re.IGNORECASE)
        for text in corpus:
            want = pattern.search(text) is not None
            assert closed_mod._matches_text(names[e["id"]], text) is want, (e["id"], text)
            seen[e["id"]][want] += 1
    # the corpus is live: every entry both closes and leaves open some of it
    assert all(shut and open_ for open_, shut in seen.values()), seen


def test_folding_closes_whatever_case_insensitive_matching_would():
    # every code point Python's IGNORECASE matches to an ASCII letter folds to that letter (closes more, never less)
    letters = [(a, re.compile(a, re.IGNORECASE)) for a in "abcdefghijklmnopqrstuvwxyz"]
    for cp in range(0x20, 0x30000):
        c = chr(cp)
        if 0xD800 <= cp <= 0xDFFF:
            continue
        for a, pat in letters:
            if pat.fullmatch(c):
                assert closed_mod._fold(c) == a, (hex(cp), a)


def test_a_name_is_closed_whether_or_not_it_exists(tmp_path, home):
    made = tmp_path / "work" / "private-notes"
    made.mkdir(parents=True)
    (made / "a.md").write_text("x", encoding="utf-8")
    assert _both(made / "a.md", home) and _both(made, home)                          # must refuse
    other = tmp_path / "work" / "open-notes"
    other.mkdir()
    (other / "a.md").write_text("x", encoding="utf-8")
    assert not _both(other / "a.md", home)                                          # must pass


def test_mixed_separators_in_one_path(tmp_path, home):
    assert _both(str(tmp_path) + "\\work/private-notes\\a.md", home)                 # must refuse
    assert not _both(str(tmp_path) + "\\work/private-notes1\\a.md", home)           # must pass


def _link(target: Path, link: Path):
    try:
        if os.name == "nt":   # a junction needs no privilege on Windows
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot make a link")


def test_a_link_that_leads_into_a_closed_name_is_closed(tmp_path, home):
    # the real path is judged as well as the path as given
    shut = tmp_path / "work" / "private-notes"
    shut.mkdir(parents=True)
    (shut / "a.md").write_text("x", encoding="utf-8")
    door = tmp_path / "door"
    _link(shut, door)
    assert _both(door / "a.md", home) and _both(door, home)                          # must refuse
    fine = tmp_path / "work" / "open-notes"
    fine.mkdir()
    (fine / "a.md").write_text("x", encoding="utf-8")
    door2 = tmp_path / "door2"
    _link(fine, door2)
    assert not _both(door2 / "a.md", home)                                          # must pass


def test_a_link_into_a_closed_substring_folder_is_closed(tmp_path, home):
    shut = tmp_path / "work" / "coinjar.txt.d"
    shut.mkdir(parents=True)
    door = tmp_path / "plain"
    _link(shut, door)
    assert _both(door / "inner.txt", home)                                           # must refuse
    fine = tmp_path / "work" / "coinjar.d"
    fine.mkdir()
    door2 = tmp_path / "plain2"
    _link(fine, door2)
    assert not _both(door2 / "inner.txt", home)                                     # must pass


def test_a_link_whose_own_name_is_closed_is_closed(tmp_path, home):
    fine = tmp_path / "work" / "open-notes"
    fine.mkdir(parents=True)
    door = tmp_path / "private-notes"
    _link(fine, door)
    assert _both(door / "a.md", home)                                                # must refuse
    assert not _both(fine / "a.md", home)                                           # must pass


def test_a_long_path_prefix_does_not_open_a_closed_name(tmp_path, home):
    if os.name != "nt":
        pytest.skip("the \\\\?\\ prefix is Windows's")
    base = str(tmp_path / "work")
    assert _both("\\\\?\\" + base + "\\private-notes\\a.md", home)                  # must refuse
    assert not _both("\\\\?\\" + base + "\\public-notes\\a.md", home)               # must pass


def test_a_share_path_is_closed_while_only_names_are_closed(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("shares are Windows's")
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shared = "\\\\localhost\\C$\\work\\a.md"
    h = _home(tmp_path, {"closed": [], "closed_names": [seg("n", "private-notes")]})
    assert _both(shared, h)                                                          # must refuse
    h = _home(tmp_path, {"closed": [], "closed_names": []})
    assert not closed_mod.in_closed_place(shared, h)                                # must pass: nothing is closed


def test_a_one_letter_segment_does_not_close_a_drive(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [seg("c", "c"), seg("d", "d")]})
    assert not _both("C:\\work\\a.md", h) and not _both("D:/work/a.md", h)
    assert _both(str(tmp_path / "c" / "a.md"), h)                                    # the segment itself: closed


# ---- the read context a plug-in is given ---------------------------------------------------------------------
def test_the_read_context_carries_the_names(tmp_path, home):
    ctx = closed_mod.context(home)
    assert api.closures_known(ctx) and len(ctx.names) == len(NAMES)
    assert api.is_closed_place(tmp_path / "w" / "private-notes" / "a.md", ctx)      # must refuse
    assert not api.is_closed_place(tmp_path / "w" / "open-notes" / "a.md", ctx)    # must pass


def test_a_read_context_made_without_names_still_works(tmp_path):
    ctx = closed_mod.ReadContext("", ())
    assert not api.is_closed_place(tmp_path / "private-notes" / "a.md", ctx)       # must pass: nothing closed
    assert api.is_closed_place(tmp_path / "a.md", closed_mod.ReadContext("", None))  # must refuse: unknown


def test_the_card_readers_judge_names_too(tmp_path, home):
    shut = closed_mod.closures(home)
    assert closed_mod._judge(str(tmp_path / "private-notes" / "requests.jsonl"), shut)     # must refuse
    assert not closed_mod._judge(str(tmp_path / "open-notes" / "requests.jsonl"), shut)   # must pass


@pytest.mark.parametrize("names", [("private-notes",), (seg("n", "private-notes"),), "private-notes",
                                   (closed_mod.Name("n", "segment", ("Private-Notes",)),),
                                   (closed_mod.Name("n", "glob", ("x",)),),
                                   (closed_mod.Name("n", "segment", ("a:b",)),),
                                   (closed_mod.Name("n", "segment-pair", ("a",)),),
                                   (closed_mod.Name("n", "segment", ("x",), "er"),),
                                   (closed_mod.Name("", "segment", ("x",)),)])
def test_a_read_context_with_malformed_names_is_refused(names):   # must refuse, with a clear error
    with pytest.raises(TypeError, match="names"):
        closed_mod.ReadContext("", (), names)


def test_a_read_context_with_real_names_judges_them(tmp_path):   # must pass
    ctx = closed_mod.ReadContext("", (), (closed_mod.Name("n", "segment", ("private-notes",)),))
    assert api.is_closed_place(tmp_path / "private-notes" / "a.md", ctx)
    assert not api.is_closed_place(tmp_path / "open" / "a.md", ctx)


def test_a_read_context_altered_after_it_is_made_fails_closed(tmp_path):   # must refuse
    ctx = closed_mod.ReadContext("", (), ())
    object.__setattr__(ctx, "names", ("private-notes",))
    assert api.is_closed_place(tmp_path / "open" / "a.md", ctx)


# ---- where the names are written --------------------------------------------------------------------------------
@pytest.mark.parametrize("names", [[seg("n", "private-notes")], []])
def test_names_alone_never_make_the_closures_known(tmp_path, monkeypatch, names):   # must refuse: none named
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed_names": names})
    assert not api.closures_known(h) and api.is_closed_place(tmp_path / "open" / "a.md", h)   # as in 1.3.0
    state = closed_mod.closures_state(h)
    assert state["state"] == "none named" and '"closed"' in state["fix"]
    assert (state["why"] is not None) == bool(names)                                  # said when names are there
    from semantext.sources import runs
    # the built-in readers and the strict view: the names close what they name (1.3.0 closed nothing here)
    for check in (closed_mod.in_closed_place, runs.is_closed_place):
        assert check(tmp_path / "w" / "private-notes" / "a.md", h) == bool(names)
        assert not check(tmp_path / "open" / "a.md", h)


def test_names_beside_a_closed_list_are_known_and_close_more(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [seg("n", "private-notes")]})
    assert api.closures_known(h) and not api.is_closed_place(tmp_path / "open" / "a.md", h)
    assert api.is_closed_place(tmp_path / "w" / "private-notes" / "a.md", h)


def test_an_empty_names_list_closes_nothing(tmp_path, monkeypatch):   # must pass: a statement, so known
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": []})
    assert api.closures_known(h) and not api.is_closed_place(tmp_path / "private-notes" / "a.md", h)


def test_a_sources_file_shaped_like_the_format_is_not_known_by_its_names(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    secret = tmp_path / "secretdir"
    h = _home(tmp_path, {"schema": "estate.closures/0", "closed_names": [seg("n", "zzprivate")], "closed_paths": None,
                         "closed_paths_complete": False, "known_closed_paths": [str(secret)]})
    assert not api.closures_known(h)
    assert api.is_closed_place(secret / "x.txt", h) and api.is_closed_place(tmp_path / "open" / "a.md", h)
    assert closed_mod.closures_state(h)["state"] == "none named"                      # plugins enable refuses
    rows = [r for r in closed_mod.problems(h) if r["kind"] == "closures lookalike"]
    assert len(rows) == 1 and "'closed_names'" in rows[0]["text"]                     # said, not read
    assert not closed_mod.in_closed_place(tmp_path / "w" / "zzprivate" / "a.md", h)   # as in 1.3.0: not read here


def test_names_and_paths_merge(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "Shut"
    h = _home(tmp_path, {"closed": [str(shut)], "closed_names": [seg("n", "private-notes")]})
    assert _both(shut / "a.md", h) and _both(tmp_path / "w" / "private-notes" / "a.md", h)   # must refuse
    assert not _both(tmp_path / "w" / "open" / "a.md", h)                                  # must pass


def test_names_are_read_from_a_closures_file(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {**SCHEMED, "closed": [], "closed_names": [substr("k", "secret.key")]})
    h = _home(tmp_path, {"closures_file": str(f)})
    assert api.closures_known(h)
    assert _both(tmp_path / "x" / "secret.key", h) and not _both(tmp_path / "x" / "secret.txt", h)
    f2 = _file(tmp_path, {**SCHEMED, "places": [], "shut_names": [suffix("v", ".vaultfile")]}, "named-keys.json")
    h2 = _home(tmp_path, {"closures_file": str(f2), "closures_key": "places", "closures_names_key": "shut_names"})
    assert api.closures_known(h2)
    assert _both(tmp_path / "db.vaultfile", h2) and not _both(tmp_path / "db.txt", h2)


def test_names_in_the_sources_file_and_the_closures_file_merge(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {**SCHEMED, "closed": [], "closed_names": [substr("k", "secret.key")]})
    h = _home(tmp_path, {"closed": [], "closed_names": [seg("n", "private-notes")], "closures_file": str(f)})
    assert _both(tmp_path / "secret.key", h) and _both(tmp_path / "private-notes", h)       # must refuse
    assert not _both(tmp_path / "public.key", h)                                          # must pass


def test_a_closures_file_in_the_published_shape_is_known(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    entry = {**seg("n", "private-notes"), "closes": "the notes folder, anywhere", "note": "a note",
             "examples": {"closed": ["C:/x/private-notes"], "open": ["C:/x/private-notes2"]}}
    f = _file(tmp_path, {
        "_about": "name closures, as data", "schema": "estate.closures/0",
        "source": {"file": "x.py", "symbol": "X", "flags": "re.IGNORECASE", "pattern_sha256": "0" * 64},
        "matching": {"operation": "search", "separators": ["\\", "/"]},
        "closed_names": [entry, substr("l", "ledgerbox")],
        "closed_paths": [str(keep)], "closed_paths_note": "a note", "closed_paths_complete": True,
    })
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert api.closures_known(h) and closed_mod.why_unknown(h) is None
    assert _both(keep / "a.md", h) and _both(tmp_path / "private-notes", h) and _both(tmp_path / "my_ledgerbox", h)
    assert not _both(tmp_path / "open" / "a.md", h)


def _published(tmp_path, closed_paths):
    """A closures file shaped exactly like the published one: each top-level key it has, every form, invented values."""
    def described(e):
        return {**e, "closes": "what it closes, said", "examples": {"closed": [], "open": []}}
    return _file(tmp_path, {
        "_about": "name closures, as data", "schema": "estate.closures/0",
        "source": {"file": "x.py", "symbol": "X", "flags": "re.IGNORECASE", "pattern_sha256": "0" * 64},
        "matching": {"operation": "search", "case": "IGNORECASE", "separators": ["\\", "/"], "end": "end",
                     "applied_to": "both", "entries_combine": "any", "the_entry_regex": "normative"},
        "closed_names": [described(pair("p", "archive", "boxa")), {**described(seg("s", ".hidebox")), "note": "n"},
                         described(prefix("x", "vaultx", "-public")), described(substr("w", "coinjar.txt")),
                         described(dotted("d", ".secretrc")), described(suffix("k", ".vaultfile"))],
        "closed_paths": closed_paths, "closed_paths_note": "a note",
        **({"closed_paths_complete": True} if closed_paths is not None else {}),
    }, "published.json")


def test_a_published_closures_file_with_paths_null_is_unknown(tmp_path, monkeypatch):   # must refuse, end to end
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _published(tmp_path, None)
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths", "closures_names_key": "closed_names"})
    assert not api.closures_known(h) and closed_mod.closures(h) is None
    somewhere = tmp_path / "open" / "a.md"
    assert api.is_closed_place(somewhere, h) and closed_mod.in_closed_place(somewhere, h)
    assert "null" in closed_mod.why_unknown(h)
    assert any(r["kind"] == "closures unknown" and "null" in r["text"] for r in closed_mod.problems(h))


def test_a_published_closures_file_with_paths_is_known(tmp_path, monkeypatch):   # must pass, end to end
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    f = _published(tmp_path, [str(keep)])
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths", "closures_names_key": "closed_names"})
    assert api.closures_known(h) and closed_mod.why_unknown(h) is None
    assert len([c for c in closed_mod.closures(h) if isinstance(c, closed_mod.Name)]) == 6
    for shut in (keep / "a.md", tmp_path / "x" / "archive" / "boxa", tmp_path / ".hidebox", tmp_path / "vaultx2",
                 tmp_path / "my_coinjar.txt", tmp_path / ".secretrc.local", tmp_path / "db.vaultfile"):
        assert _both(shut, h), shut
    assert not _both(tmp_path / "open" / "a.md", h) and not _both(tmp_path / "vaultx-public" / "a.md", h)


def test_closed_paths_null_is_unknown_and_said(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {"schema": "estate.closures/0", "closed_names": [seg("n", "private-notes")],
                         "closed_paths": None, "closed_paths_note": "not supplied yet"})
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert not api.closures_known(h) and api.is_closed_place(tmp_path / "open" / "a.md", h)
    assert closed_mod.in_closed_place(tmp_path / "open" / "a.md", h)
    assert "null" in closed_mod.why_unknown(h)


def test_another_schema_is_unknown(tmp_path, monkeypatch):   # must refuse: other rules may be meant
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {"schema": "estate.closures/1", "closed": [], "closed_names": []})
    h = _home(tmp_path, {"closures_file": str(f)})
    assert not api.closures_known(h) and "schema" in closed_mod.why_unknown(h)


GOOD = seg("n", "private-notes")
BAD_NAMES = [
    "private-notes",                                                # not a list
    ["private-notes"],                                              # an entry must be an object
    [{"segment": "private-notes"}],                                 # no id, no form
    [{"id": "n", "segment": "private-notes"}],                      # no form
    [{"form": "segment", "segment": "private-notes"}],              # no id
    [{**GOOD, "id": ""}], [{**GOOD, "id": 3}], [{**GOOD, "id": " n"}],
    [GOOD, {**GOOD, "segment": "other"}],                           # an id given twice
    [{**GOOD, "form": "glob"}], [{**GOOD, "form": "name"}],         # an unknown form
    [{"id": "n", "form": "segment"}],                               # its field missing
    [{**GOOD, "note2": "x"}], [{**GOOD, "prefix": "x"}],            # a field the form does not have
    [{**GOOD, "regex": 3}], [{**GOOD, "closes": ["x"]}], [{**GOOD, "examples": "x"}],
    # literals that close nothing as typed, or would not mean the same on every system
    [{**GOOD, "segment": ""}], [{**GOOD, "segment": " x"}], [{**GOOD, "segment": "x "}], [{**GOOD, "segment": "a/b"}],
    [{**GOOD, "segment": "a\\b"}], [{**GOOD, "segment": "a:b"}], [{**GOOD, "segment": "*"}],
    [{**GOOD, "segment": "[x]"}],
    [{**GOOD, "segment": "x?"}], [{**GOOD, "segment": "."}], [{**GOOD, "segment": ".."}], [{**GOOD, "segment": 3}],
    [{**GOOD, "segment": "vault\u200bx"}], [{**GOOD, "segment": "x\u00a0"}], [{**GOOD, "segment": "a\tb"}],
    [{**GOOD, "segment": "\u0301"}], [{**GOOD, "segment": "a\nb"}],
    # segment-pair
    [{**pair("p", "a", "b"), "segments": ["a"]}], [{**pair("p", "a", "b"), "segments": ["a", "b", "c"]}],
    [{**pair("p", "a", "b"), "segments": "ab"}], [{**pair("p", "a", "b"), "needs_separator_before": False}],
    [{k: v for k, v in pair("p", "a", "b").items() if k != "needs_separator_before"}],
    [{**pair("p", "a", "b"), "then": ["separator", "end"]}], [{**pair("p", "a", "b"), "segments": ["a", "b/c"]}],
    # segment-prefix-except: its two descriptions are read only in the closures file's own phrasing
    [{**prefix("v", "vaultx", "-public"), "segment_chars_after_prefix": "letters only"}],
    [{**prefix("v", "vaultx", "-public"), "except_when_remainder_starts": "-public unless a digit follows"}],
    [{**prefix("v", "vaultx", "-public"),
      "except_when_remainder_starts": "a/b not followed by an ASCII letter or digit"}],
    [{k: v for k, v in prefix("v", "vaultx").items() if k != "segment_chars_after_prefix"}],
    [{**prefix("v", "vaultx"), "prefix": ""}],
    # segment-or-dotted-prefix: the dotted start is the segment and a dot
    [{**dotted("d", ".secretrc"), "or_segment_starts": ".secret."}],
    [{**dotted("d", ".secretrc"), "or_segment_starts": 3}],
    # substring and suffix
    [{**substr("s", "a"), "substrings": []}], [{**substr("s", "a"), "substrings": "abc"}],
    [{**substr("s", "a"), "substrings": ["abc", ""]}], [{**substr("s", "a"), "substrings": ["a*c"]}],
    [{**suffix("x", ".a"), "suffixes": []}], [{**suffix("x", ".a"), "suffixes": [".a:b"]}],
    '{"closed_names": [{"id": "n", "form": "segment", "segment": "a", "segment": "b"}]}',   # a key given twice
    '{"closed_names": [], "closed_names": []}',                                            # the list given twice
]


@pytest.mark.parametrize("value", BAD_NAMES)
def test_names_that_cannot_be_known_close_everything(tmp_path, monkeypatch, value):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, value if isinstance(value, str) else {"closed": [], "closed_names": value})
    assert not api.closures_known(h) and closed_mod.closures(h) is None
    assert api.is_closed_place(tmp_path / "anything.md", h) and closed_mod.in_closed_place(tmp_path / "anything.md", h)


@pytest.mark.parametrize("file_value, setting", [
    ({"closed": []}, {"closures_names_key": "shut_names"}),          # a names key named, and not in the file
    ({"closed_names": []}, {"closures_key": "places"}),               # a paths key named, and not in the file
    ({"closed": [], "closed_names": "x"}, {}),                       # the names in the file are not a list
    ({"closed": [], "closed_names": None}, {}),                      # null: not supplied, so unknown
    ({"closed": [], "closed_names": [{**GOOD, "segment": "a/b"}]}, {}),
    ({"other": []}, {}),
    ({"closed": [], "closed_names": []}, {"closures_names_key": 3}),
    ({"closed": [], "closed_names": []}, {"closures_names_key": ""}),
    ('{"closed_names": [], "closed_names": []}', {}),
    # the paths key must be in the file, as in 1.3.0
    ({"closed_names": [GOOD]}, {}),
    ({"closed_paths": ["@keep"], "closed_names": [GOOD]}, {}),
    ({"closed_paths": ["@keep"], "closed_names": []}, {}),
    ({"closed_paths": ["@keep"], "closed_names": [GOOD]}, {"closures_names_key": "closed_names"}),
    ({"close": ["@keep"], "closed_names": [GOOD]}, {}),
    # in a file that says the format's schema, a list SHAPED like closures (full paths, or name entries) under a key
    # nobody reads, whatever the key's name (a schema-less closures file keeps 1.3.0's rule: see the 1.3.0 test)
    ({"schema": "estate.closures/0", "closed": [], "closed_paths": ["@keep"]}, {}),
    ({"closed": [], "closed_names": [], "Closures": ["@keep"]}, {}),
    ({"schema": "estate.closures/0", "closed": [], "closd": ["@keep"]}, {}),
    ({"schema": "estate.closures/0", "closed": [], "shut": ["@keep"]}, {}),
    ({"schema": "estate.closures/0", "places": [], "closed": ["@keep"]}, {"closures_key": "places"}),
    ({"schema": "estate.closures/0", "places": [], "closed_paths": ["@keep"]}, {"closures_key": "places"}),
    ({"closed": [], "shut_names": [], "closed_names": [GOOD]}, {"closures_names_key": "shut_names"}),
    ({"schema": "estate.closures/0", "closed": [], "hidden": [GOOD, substr("s", "abc")]}, {}),
    ({"schema": "estate.closures/1", "closed": []}, {}),               # another version of the format
])
def test_a_closures_file_that_cannot_be_used_is_unknown(tmp_path, monkeypatch, file_value, setting):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    f = _file(tmp_path, file_value if isinstance(file_value, str) else _sub(file_value, keep))
    h = _home(tmp_path, {"closures_file": str(f), **setting})
    assert not api.closures_known(h) and closed_mod.closures(h) is None                        # must refuse
    assert api.is_closed_place(tmp_path / "a.md", h) and closed_mod.in_closed_place(tmp_path / "a.md", h)
    assert api.is_closed_place(keep / "x.txt", h) and closed_mod.in_closed_place(keep / "x.txt", h)
    assert closed_mod.why_unknown(h)                                                           # and said why


@pytest.mark.parametrize("file_value, setting", [
    ({"closed": ["@keep"]}, {}),                                       # the names key is optional while defaulted
    ({**SCHEMED, "closed": ["@keep"], "closed_names": []}, {}),
    ({"closed": ["@keep"], "note": "kept by hand"}, {}),
    # keys named like closures whose values are not shaped like closures are another tool's
    ({"closed": ["@keep"], "disclosure": ["a sentence about it"], "enclosed_notes": "x", "Closures": []}, {}),
    ({"closed": ["@keep"], "shut": [], "other": [{"text": "x"}], "mixed": ["@keep", "a sentence"]}, {}),
    ({"closed": ["@keep"], "links": [{"name": "site", "url": "https://example.invalid"}]}, {}),
    ({**SCHEMED, "places": ["@keep"], "shut_names": []},
     {"closures_key": "places", "closures_names_key": "shut_names"}),
])
def test_a_closures_file_with_its_paths_key_is_known(tmp_path, monkeypatch, file_value, setting):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    f = _file(tmp_path, _sub(file_value, keep))
    h = _home(tmp_path, {"closures_file": str(f), **setting})
    assert api.closures_known(h) and closed_mod.why_unknown(h) is None
    assert _both(keep / "x.txt", h) and not _both(tmp_path / "open" / "x.txt", h)


def test_a_closures_file_kept_for_another_tool_is_known(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    doc = {
        "_about": "the hub's roots, read by more than one tool",
        "base": str(tmp_path),
        "page_owner": "someone",
        "closures": ["Leave the box alone.", "Never read the notes folder.", "Ask before the archive.",
                     "Nothing under the old drive.", "The vault stays shut.", {"text": "x", "not_for": ["A"]}],
        "seats": {"A": {"home": str(tmp_path / "a")}},
        "roots": {"one": {"path": str(tmp_path / "one")}},
        "external": [{"name": "site", "url": "https://example.invalid"}],
        "next": "the next step",
        "closed_paths": [str(keep)],
    }
    f = _file(tmp_path, doc)
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert api.closures_known(h) and closed_mod.why_unknown(h) is None
    assert _both(keep / "x.txt", h)                                                           # closed
    assert not _both(tmp_path / "one" / "a.md", h)                                            # open
    # names in a closures file need the file to say its schema: a file without one holding names is unknown
    f2 = _file(tmp_path, {**doc, "closed_names": [GOOD]}, "with-names.json")
    h2 = _home(tmp_path, {"closures_file": str(f2), "closures_key": "closed_paths"})
    assert not api.closures_known(h2) and "schema" in closed_mod.why_unknown(h2)              # must refuse


def test_a_list_nobody_reads_is_said_aloud(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {"schema": "estate.closures/0", "closed": [], "closed_paths": [str(tmp_path / "keep")]})
    h = _home(tmp_path, {"closures_file": str(f)})
    assert "closed_paths" in closed_mod.why_unknown(h)                                         # must refuse, aloud
    rows = closed_mod.problems(h)
    assert len(rows) == 1 and "closed_paths" in rows[0]["text"] and rows[0]["reader"] == "closures"
    ok = _home(tmp_path, {"closed": []})
    assert closed_mod.problems(ok) == [] and closed_mod.why_unknown(ok) is None                # must pass
    assert closed_mod.problems(_home(tmp_path, {"seats": "x"})) == []                         # none named


def test_the_page_lists_closures_it_cannot_use(tmp_path, monkeypatch):
    from semantext.sources import view
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {"close": [str(tmp_path / "keep")], "closed_names": []})
    h = _home(tmp_path, {"closures_file": str(f)})
    assert any(p.get("reader") == "closures" and "close" in p["text"] for p in view._Sources(h).problems)  # refuse
    h2 = _home(tmp_path, {"closed": []})
    assert not any(p.get("reader") == "closures" for p in view._Sources(h2).problems)                   # pass


def test_a_names_key_without_a_file_is_unknown(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closures_names_key": "shut_names"})
    assert not api.closures_known(h)


def test_the_path_list_still_refuses_what_it_did(tmp_path, monkeypatch):   # must refuse, unchanged
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    for bad in ({"closed": ["relative"], "closed_names": []}, {"closed": [""], "closed_names": []},
                {"closed": "C:\\one", "closed_names": [GOOD]}, {"closed": None, "closed_names": []}):
        h = _home(tmp_path, bad)
        assert not api.closures_known(h) and api.is_closed_place(tmp_path / "a.md", h)


# ---- a lookalike in the sources file is said, never fail-closed --------------------------------------------------
def _rows(h, declared=()):
    return [p for p in closed_mod.problems(h, declared) if p["reader"] == "closures"]


def test_a_closures_shaped_list_in_the_sources_file_is_said(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    h = _home(tmp_path, {"closed": [], "shut": [str(keep)], "hidden": [GOOD]})
    assert api.closures_known(h) and not _both(keep / "x.txt", h)        # known still: reported, not fail-closed
    rows = _rows(h)                                                       # must refuse, aloud
    assert {r["kind"] for r in rows} == {"closures unread"} and len(rows) == 2
    assert any("'shut'" in r["text"] and "'closed' and 'closed_names'" in r["text"] for r in rows)
    assert _rows(h, declared=("shut", "hidden")) == []                    # must pass: a plug-in's own keys
    ok = _home(tmp_path, {"closed": [], "notes": ["a sentence"], "group": "g", "shut": []})
    assert _rows(ok) == []                                                # must pass: not shaped like closures


def test_the_page_says_a_lookalike_in_the_sources_file(tmp_path, monkeypatch):
    from semantext.sources import view
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "shut": [str(tmp_path / "keep")]})
    assert any(p.get("kind") == "closures unread" for p in view._Sources(h).problems)          # must refuse
    h2 = _home(tmp_path, {"closed": [str(tmp_path / "keep")]})
    assert not any(p.get("reader") == "closures" for p in view._Sources(h2).problems)          # must pass


# ---- names that close nearly everything are said ----------------------------------------------------------------
@pytest.mark.parametrize("entry", [substr("s", "ab"), substr("s", "abc", "e"), suffix("x", ".h"), prefix("p", "ab"),
                                   substr("s", "-")])
def test_a_name_that_closes_nearly_every_path_is_said(tmp_path, monkeypatch, entry):   # must refuse, aloud
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [entry]})
    assert api.closures_known(h)                                          # the person's choice: kept
    assert any(r["kind"] == "closures too wide" and "closes nearly every path" in r["text"] for r in _rows(h))


@pytest.mark.parametrize("entry", [GOOD, substr("s", "abc"), prefix("p", "vaultx"), suffix("x", ".vf"),
                                   seg("c", "c"), pair("p", "a", "b"), dotted("d", ".rc")])
def test_a_narrow_name_is_not_said(tmp_path, monkeypatch, entry):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [entry]})
    assert api.closures_known(h) and _rows(h) == []


def test_an_inner_ascii_space_is_a_name(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [seg("n", "private notes")]})
    assert api.closures_known(h)
    assert _both(tmp_path / "private notes" / "a.md", h) and not _both(tmp_path / "private notes2" / "a.md", h)


# ---- a plug-in cannot declare the person's closures as its own keys ---------------------------------------------
class _Source:
    name, title = "tickets", "Tickets"

    def __init__(self, keys):
        self.keys = keys

    def read(self, config):
        return {"problems": []}


@pytest.mark.parametrize("key", ["closed", "closed_names", "closures_file", "closures_key", "closures_names_key"])
def test_a_plug_in_may_not_declare_a_closures_key(key):   # must refuse
    from semantext import outside, registry
    with pytest.raises(ValueError, match="reserved"):
        registry.Registry().add("source", "tickets", outside.snapshot(_Source(("tickets_file", key))), origin="pkg")


def test_a_plug_in_with_its_own_keys_is_added():   # must pass
    from semantext import outside, registry
    e = registry.Registry().add("source", "tickets", outside.snapshot(_Source(("tickets_file",))), origin="pkg")
    assert e.name == "tickets"


# ---- closes more, never less, than each entry's regex --------------------------------------------------------------
MARKS = ["\u0301", "\u030c", "\u0307", "\u093c", "\u0302\u0303", "\u05bc"]          # combining marks, two in a row
DECOMPOSABLE = ["\u0958", "\u09dc", "\u0a33", "\ufb1d", "\ufb2a", "\u00e9", "\u1e9b", "\u2adc"]   # NFC changes these


def _literals(e):
    if e["form"] == "segment-pair":
        return ["/".join(e["segments"])]
    out = list(e.get("substrings") or []) + list(e.get("suffixes") or [])
    return out + [e[k] for k in ("segment", "prefix", "or_segment_starts") if e.get(k)]


def _non_ascii_corpus(e):
    for lit in _literals(e):
        for c in MARKS + DECOMPOSABLE:
            yield from ("Q:/d/" + lit + c, "Q:/d/" + lit + c + "/z", "Q:/d/" + c + lit + "/z", "Q:/d/x" + c + lit,
                        "Q:/d/" + lit + "er" + c + "/z", "Q:/d/" + lit + "x" + c + "/z", "Q:\\d\\" + lit + c + "\\z",
                        "Q:/d/" + lit + c + c, "/d/" + lit + "-public" + c + "/z")
            for i in range(len(lit)):
                yield "Q:/d/" + lit[:i] + c + lit[i + 1:] + "/z"
                yield "Q:/d/" + lit[:i + 1] + c + lit[i + 1:] + "/z"


def test_the_fields_close_whatever_the_regex_closes_beyond_ascii():
    # the field matcher alone (as given, NFC and NFD), never the regex, over marks and decomposable letters
    names = _parsed()
    misses = []
    for e in ASCII_NAMES:
        pattern = re.compile(e["regex"], re.IGNORECASE)
        for text in _non_ascii_corpus(e):
            if pattern.search(text) and not closed_mod._matches_text(names[e["id"]], text):
                misses.append((e["id"], ascii(text)))
    assert not misses, misses[:10]


def test_a_path_is_closed_whenever_its_entrys_regex_closes_it():   # by construction: the regex is one of the legs
    names = _parsed()
    for e in ASCII_NAMES:
        pattern = re.compile(e["regex"], re.IGNORECASE)
        for text in list(_non_ascii_corpus(e)) + _corpus(800, seed=7):
            if pattern.search(text):
                assert closed_mod._named(text, [names[e["id"]]]), (e["id"], ascii(text))


@pytest.mark.parametrize("text", ["Q:/d/coinjar.txt\u030c", "Q:/d/coinjar.txt\u0307.bak/a", "Q:/d/my_idx_rsa\u0301.pub",
                                  "Q:\\d\\coinjar.txt\u030c\\z"])
def test_a_mark_after_a_substring_does_not_open_it(tmp_path, text):   # must refuse (the third attack's sweep)
    ns = closed_mod._names([substr("s", "coinjar.txt", "idx_rsa")])
    ctx = closed_mod.ReadContext("", (), tuple(ns))
    assert api.is_closed_place(text, ctx) and closed_mod._judge(text, list(ns))


@pytest.mark.parametrize("ch", ["\u0958", "\u09dc", "\u0a33", "\ufb1d", "\ufb2a"])
def test_a_letter_that_nfc_decomposes_does_not_open_a_prefix(ch):   # must refuse (the third attack's sweep)
    ns = closed_mod._names([prefix("p", "blorp", "er")])
    ctx = closed_mod.ReadContext("", (), tuple(ns))
    assert api.is_closed_place("Q:/d/blorp" + ch + "/z.md", ctx)
    assert not api.is_closed_place("Q:/d/blorper/z.md", ctx)                      # must pass: the exception holds


def test_a_regex_wider_than_its_fields_closes_what_it_closes():   # must refuse
    e = {"id": "w1", "form": "segment", "segment": ".zork", "regex": r"zork"}
    ns = closed_mod._names([e])
    assert closed_mod._named("Q:/d/my-zork-notes/a", ns)
    assert not closed_mod._named("Q:/d/my-zor-notes/a", ns)                     # must pass


def test_a_regex_narrower_than_its_fields_leaves_the_fields_closing():   # must refuse
    ns = closed_mod._names([{**GOOD, "regex": "never-in-any-path-xyz"}])
    assert closed_mod._named("Q:/d/private-notes/a", ns) and not closed_mod._named("Q:/d/open/a", ns)


@pytest.mark.parametrize("regex, why", [("(", "regex"), ("a" * 2001, "regex"), ("x{1,99999999999}", "regex")])
def test_a_regex_that_cannot_be_used_is_unknown(tmp_path, monkeypatch, regex, why):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [{**GOOD, "id": "zq", "regex": regex}]})
    assert not api.closures_known(h)
    reason = closed_mod.why_unknown(h)
    assert "'zq'" in reason and why in reason


@pytest.mark.parametrize("entry, field", [({**GOOD, "id": "zq", "segment": "a/b"}, "segment"),
                                          ({**GOOD, "id": "zq", "form": "glob"}, "form"),
                                          ({**GOOD, "id": "zq", "note2": "x"}, "note2"),
                                          ({"id": "zq", "form": "segment"}, "segment"),
                                          ({**pair("zq", "a", "b"), "then": ["end"]}, "then"),
                                          ({**prefix("zq", "vaultx"), "segment_chars_after_prefix": "x"},
                                           "segment_chars_after_prefix")])
def test_a_reason_names_the_entry_and_the_field(tmp_path, monkeypatch, entry, field):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [entry]})
    reason = closed_mod.why_unknown(h)
    assert "'zq'" in reason and repr(field) in reason, reason


def test_the_examples_are_checked_and_a_disagreement_said(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    odd = {**seg("zap", "zap"), "regex": "zapx", "examples": {"closed": ["Q:/d/zap"], "open": []}}
    wrong = {**seg("zip", "zip"), "examples": {"closed": [], "open": ["Q:/d/zip"]}}
    fine = {**seg("zop", "zop"), "examples": {"closed": ["Q:/d/zop"], "open": ["Q:/d/zopper"]}}
    h = _home(tmp_path, {"closed": [], "closed_names": [odd, wrong, fine]})
    assert api.closures_known(h)                                          # information, never opening or closing more
    rows = [r for r in _rows(h) if r["kind"] == "closures examples"]
    assert any("'zap'" in r["text"] for r in rows) and any("'zip'" in r["text"] for r in rows)   # must refuse
    assert not any("'zop'" in r["text"] for r in rows)                                           # must pass
    assert _both(tmp_path / "zip", h)                                     # the fields still close it


# ---- what a closures file with a schema may hold ------------------------------------------------------------------
@pytest.mark.parametrize("extra", [{"closed_patterns": ["zork.*"]}, {"closed_regexes": [{"id": "r", "regex": "zork"}]},
                                   {"closed_names_v2": [{"id": "r", "form": "glob", "glob": "*zork*"}]},
                                   {"mixed": ["@keep", GOOD]}, {"notes": "a text"}, {"matching": "search"},
                                   {"matching": {"version": "2"}}, {"schema": ["estate.closures/0"]},
                                   {"known_closed_paths": None}, {"known_open_paths_near": None},
                                   {"closed_paths_complete": None}])
def test_a_schema_file_holding_what_it_does_not_know_is_unknown(tmp_path, monkeypatch, extra):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    f = _file(tmp_path, _sub({**SCHEMED, "closed_paths": ["@keep"], "closed_names": [GOOD], **extra}, keep))
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert not api.closures_known(h) and closed_mod.why_unknown(h)
    assert api.is_closed_place(tmp_path / "open" / "a.md", h)


def test_a_schema_file_with_every_key_it_knows_is_known(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    keep = tmp_path / "keep"
    f = _file(tmp_path, {**SCHEMED, "_about": "x", "source": {"file": "x"}, "matching": {"operation": "search"},
                         "closed_paths": [str(keep)], "known_closed_paths": [str(keep)],
                         "known_open_paths_near": [str(tmp_path / "near")], "closed_names": [GOOD],
                         "closed_paths_note": "x"})
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert api.closures_known(h), closed_mod.why_unknown(h)
    assert _both(keep / "a.md", h) and not _both(tmp_path / "near" / "a.md", h)


def test_a_null_beside_an_empty_list_is_unknown(tmp_path, monkeypatch):   # must refuse, whichever key is read
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {**SCHEMED, "closed_names": [], "closed_paths": None, "closed": []})
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed"})
    assert not api.closures_known(h) and "null" in closed_mod.why_unknown(h)
    f2 = _file(tmp_path, {"closed": [], "closed_paths": None}, "no-schema.json")
    h2 = _home(tmp_path, {"closures_file": str(f2)})
    assert api.closures_known(h2) and closed_mod.closures(h2) == []   # must pass: a schema-less file, 1.3.0's rule


# ---- a complete list for plug-ins; a lower bound for the built-in readers ----------------------------------------
INCOMPLETE = "incomplete: files under a named root that no rule matches are readable until the list is complete"


def _listed_file(tmp_path, listed, closed_paths=None, complete=None, names=(), name="listed.json", **extra):
    doc = {"schema": "estate.closures/0", "closed_names": list(names), "closed_paths": closed_paths,
           "known_closed_paths": [{"id": f"p{i}", "path": str(p), "source": "measured"} for i, p in enumerate(listed)],
           "known_open_paths_near": [{"path": str(tmp_path / "near"), "why": "beside a closed one"}], **extra}
    if complete is not None:
        doc["closed_paths_complete"] = complete
    f = _file(tmp_path, doc, name)
    return _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths",
                            "closures_names_key": "closed_names"})


def test_a_partial_list_is_never_read_as_complete(tmp_path, monkeypatch):   # must refuse: the control
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "shut"
    h = _listed_file(tmp_path, [shut], None, False, [seg("n", "private-notes")])
    # read as complete, these three would be let through; a plug-in must find every one of them closed
    for p in (tmp_path / "x" / "my-coinjar.txt", tmp_path / "x" / ".secretrc", tmp_path / "x" / "server.vaultfile"):
        assert api.is_closed_place(p, h) and api.is_closed_place(p, closed_mod.context(h))
    assert not api.closures_known(h) and "complete" in closed_mod.why_unknown(h)


@pytest.mark.parametrize("closed_paths, complete, listed", [
    (None, False, ["shut"]), (None, True, ["shut"]), ([], None, ["shut"]), ("@keep", "true", ["shut"]),
    ("@keep", 1, ["shut"]), ("@keep", False, ["shut"]),
    ("@keep", True, ["shut", "other"]),                     # complete, and a known closed path is not in it: disagree
])
def test_the_plug_in_side_needs_a_complete_list_that_agrees(tmp_path, monkeypatch, closed_paths, complete, listed):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    paths = [str(tmp_path / "shut")] if closed_paths == "@keep" else closed_paths
    h = _listed_file(tmp_path, [tmp_path / p for p in listed], paths, complete)
    assert not api.closures_known(h) and api.is_closed_place(tmp_path / "open" / "a.md", h)          # must refuse


def test_a_complete_list_that_agrees_is_known(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "shut"
    h = _listed_file(tmp_path, [shut], [str(shut), str(tmp_path / "also")], True)
    assert api.closures_known(h) and closed_mod.why_unknown(h) is None
    assert _both(shut / "a.md", h) and _both(tmp_path / "also" / "b.md", h)
    assert not _both(tmp_path / "open" / "a.md", h)
    assert not [r for r in _rows(h) if r["kind"] == "closures incomplete"]


def test_the_built_in_readers_read_the_known_paths_and_say_the_list_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "Data" / "Shut-Spec"
    h = _listed_file(tmp_path, [shut], None, False, [seg("n", "private-notes")])
    assert closed_mod.closures(h) is not None                                      # the built-ins have a lower bound
    for p in (shut, shut / "a.md", str(shut).upper() + "\\deep", str(shut).replace("\\", "/") + "/x",
              str(shut) + "\\", tmp_path / "w" / "private-notes" / "a.md"):
        assert closed_mod.in_closed_place(p, h), p                                 # must refuse
    for p in (tmp_path / "Data" / "Shut-Specs", tmp_path / "Data" / "Shut", tmp_path / "open" / "a.md"):
        assert not closed_mod.in_closed_place(p, h), p                             # must pass: a sibling is not closed
    assert api.is_closed_place(tmp_path / "open" / "a.md", h)                      # and a plug-in finds all closed
    rows = [r for r in _rows(h) if r["kind"] == "closures incomplete"]
    assert len(rows) == 1 and INCOMPLETE in rows[0]["text"]


def test_the_built_in_readers_follow_a_link_into_a_known_path(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "Data" / "Shut"
    (shut / "inner").mkdir(parents=True)
    door = tmp_path / "door"
    _link(shut, door)
    h = _listed_file(tmp_path, [shut], None, False)
    assert closed_mod.in_closed_place(door / "inner" / "a.md", h)                  # must refuse: the real path
    fine = tmp_path / "Data" / "Open"
    fine.mkdir()
    door2 = tmp_path / "door2"
    _link(fine, door2)
    assert not closed_mod.in_closed_place(door2 / "a.md", h)                       # must pass


def test_without_any_path_list_the_built_ins_are_unknown_too(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    f = _file(tmp_path, {"schema": "estate.closures/0", "closed_names": [GOOD], "closed_paths": None})
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert closed_mod.closures(h) is None and closed_mod.in_closed_place(tmp_path / "open" / "a.md", h)


@pytest.mark.parametrize("text", ["//srv/share/a.md", "\\\\srv\\share\\a.md", "\\\\?\\UNC\\srv\\share\\a.md",
                                  "\\\\?\\GLOBALROOT\\Device\\x", "\\\\.\\pipe\\x", "\\/srv/a", "/\\srv\\a"])
def test_two_separator_forms_are_closed_while_any_closure_exists(tmp_path, monkeypatch, text):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _listed_file(tmp_path, [tmp_path / "shut"], None, False)
    assert closed_mod.in_closed_place(text, h)
    h2 = _home(tmp_path, {"closed": []})
    assert not closed_mod.in_closed_place(text, h2)                    # must pass: nothing is closed, nothing to hide


def test_a_long_drive_prefix_is_read_as_the_drive(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("the drive forms are Windows's")
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "shut"
    for h in (_listed_file(tmp_path, [shut], None, False), _home(tmp_path, {"closed": [str(shut)]})):
        for prefix_ in ("\\\\?\\", "//?/"):   # the long form of a drive path, read as the drive (as 1.3.0 did)
            assert closed_mod.in_closed_place(prefix_ + str(shut) + "\\a.md", h)                # must refuse
            assert not closed_mod.in_closed_place(prefix_ + str(tmp_path / "open" / "a.md"), h)  # must pass
        for prefix_ in ("\\\\.\\", "//./"):   # a device path: closed whenever a closure is named, as in 1.3.0
            assert closed_mod.in_closed_place(prefix_ + str(shut) + "\\a.md", h)                # must refuse
            assert closed_mod.in_closed_place(prefix_ + str(tmp_path / "open" / "a.md"), h)      # must refuse
            assert closed_mod.is_closed_place(prefix_ + str(tmp_path / "open" / "a.md"), h)


# ---- the path rule and the root rule, against a reference written from the file's own `matching.paths` ----------
def _ref_components(path):
    p = path.replace("/", "\\")
    if p.startswith("\\\\?\\"):   # \\.\ (a device path) is read as no drive: closed, as in 1.3.0
        rest = p[4:]
        if len(rest) >= 2 and rest[0].isascii() and rest[0].isalpha() and rest[1] == ":" and (len(rest) == 2 or
                                                                                               rest[2] == "\\"):
            p = rest
        else:
            return [], False
    elif p.startswith("\\\\"):
        return [], False
    return [c for c in p.lower().split("\\") if c != ""], True


def _ref_path_closed(path, listed):
    have, readable = _ref_components(path)
    return not readable or any(have[:len(w)] == w for w in (_ref_components(k)[0] for k in listed))


def _ref_contains_closed(root, listed):
    have, readable = _ref_components(root)
    return not readable or any(w[:len(have)] == have for w in (_ref_components(k)[0] for k in listed))


LISTED = ["C:\\Users\\me\\Shut", "C:/data/Arch/Box2", "D:\\x"]


def _path_corpus(n=5000, seed=1029):
    rng = random.Random(seed)
    heads = ["C:", "c:", "D:", "d:", "E:", "\\\\?\\C:", "\\\\.\\C:", "\\\\?\\c:", "//?/C:", "//srv", "\\\\srv",
             "\\\\?\\UNC\\s", "\\\\?\\Q", ""]
    comps = ["Users", "users", "me", "ME", "Shut", "shut", "Shut-specs", "Shutx", "data", "Arch", "ARCH", "Box2",
             "box2", "Box", "x", "X", "a.md", ""]
    out = []
    for _ in range(n):
        parts = [rng.choice(heads)] + [rng.choice(comps) for _ in range(rng.randint(0, 5))]
        out.append(rng.choice(["\\", "/", "\\\\", "/\\"]).join(parts) + rng.choice(["", "\\", "/"]))
    return out


def test_the_path_rule_agrees_with_the_reference():
    seen = [0, 0]
    for text in _path_corpus():
        want = _ref_path_closed(text, LISTED)
        assert closed_mod._listed_closed(text, LISTED) is want, text
        seen[want] += 1
    assert all(seen), seen                                      # the corpus is live: both answers occur


def test_the_root_rule_agrees_with_the_reference():
    seen = [0, 0]
    for text in _path_corpus(seed=7):
        want = _ref_contains_closed(text, LISTED)
        assert closed_mod._contains_listed(text, LISTED) is want, text
        seen[want] += 1
    assert all(seen), seen


# ---- a named root that is, or holds, a closed path is refused ------------------------------------------------------
def test_a_root_that_holds_a_closed_path_is_refused(tmp_path, monkeypatch):
    from semantext.sources import places
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    base = tmp_path / "base"
    for d in ("desk/shut", "proj", "inside/shut2/deep"):
        (base / d).mkdir(parents=True)
    seats = tmp_path / "seats.json"
    seats.write_text(json.dumps({"base": str(base), "seats": {}, "roots": [
        {"name": "desk", "path": "desk", "kind": "repo"}, {"name": "proj", "path": "proj", "kind": "repo"},
        {"name": "deep", "path": "inside/shut2/deep", "kind": "repo"}]}), encoding="utf-8")
    h = _home(tmp_path, {"seats": str(seats), "closed": [str(base / "desk" / "shut"), str(base / "inside" / "shut2")]})
    cfg = {"seats": str(seats), "_file": str(h / "sources.json")}
    got = places.load(cfg)
    assert [p["name"] for p in got["projects"]] == ["proj"]                          # must pass: proj is kept
    said = [p for p in got["problems"] if p["kind"] == "contains-closed"]
    assert len(said) == 2 and all("desk" in p["text"] or "deep" in p["text"] for p in said)   # must refuse
    assert closed_mod.contains_closed(str(base), closed_mod.closures(h))             # the base holds one
    assert not closed_mod.contains_closed(str(base / "proj"), closed_mod.closures(h))
    # the rows a plug-in and the serve hook read keep every root: they ask the closures of every path (pruned)
    roots, _ = places.named_roots(cfg)
    assert [r["name"] for r in roots] == ["desk", "proj", "deep"]
    shut = closed_mod.closures(h)
    assert closed_mod._judge(str(base / "desk" / "shut" / "a.md"), shut)
    assert not closed_mod._judge(str(base / "desk" / "open.md"), shut)


# ---- no home folder: a problem, never a failure ---------------------------------------------------------------------
def test_no_home_folder_is_closures_unknown_not_a_failure(tmp_path, monkeypatch):   # must refuse, quietly
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)

    def no_home():
        raise RuntimeError("Could not determine home directory.")
    monkeypatch.setattr(closed_mod, "config_path", no_home)
    assert not api.closures_known() and closed_mod.closures() is None
    assert api.is_closed_place(tmp_path / "a.md") and closed_mod.in_closed_place(tmp_path / "a.md")
    rows = closed_mod.problems()
    assert [r["kind"] for r in rows] == ["closures unknown"] and "home" in rows[0]["text"]
    assert closed_mod.contains_closed(str(tmp_path), closed_mod.closures())   # every root refused while unknown


# ---- which view each reader uses ------------------------------------------------------------------------------------
def test_the_strict_view_closes_everything_while_the_list_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut = tmp_path / "shut"
    h = _listed_file(tmp_path, [shut], None, False)
    assert closed_mod.in_closed_place_strict(tmp_path / "open" / "a.md", h)            # must refuse: incomplete
    assert not closed_mod.in_closed_place(tmp_path / "open" / "a.md", h)              # the lower bound reads it
    none = _home(tmp_path, {"seats": "x"})
    assert not closed_mod.in_closed_place_strict(tmp_path / "open" / "a.md", none)    # must pass: none named
    known = _home(tmp_path, {"closed": [str(shut)]})
    assert closed_mod.in_closed_place_strict(shut / "a.md", known)
    assert not closed_mod.in_closed_place_strict(tmp_path / "open" / "a.md", known)   # must pass: known, open
    from semantext.sources import runs
    assert runs.is_closed_place is closed_mod.in_closed_place_strict                  # run records use it


# ---- the state a person is told -----------------------------------------------------------------------------------
def test_the_state_said_is_the_true_one(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    none = closed_mod.closures_state(_home(tmp_path, {"seats": "x"}))
    assert none["state"] == "none named" and not none["known"] and "closed_names" in none["fix"]
    bad = closed_mod.closures_state(_home(tmp_path, {"closed": ["relative"]}))
    assert bad["state"] == "unknown" and "full paths" in bad["why"] and bad["fix"]
    part = closed_mod.closures_state(_listed_file(tmp_path, [tmp_path / "shut"], None, False))
    assert part["state"] == "incomplete" and "complete" in part["why"] and "closed_paths_complete" in part["fix"]
    good = closed_mod.closures_state(_home(tmp_path, {"closed": []}))
    assert good == {"known": True, "state": "known", "why": None, "fix": None}
    from semantext import pluginpage
    assert set(pluginpage.CLOSURES_SAID) == {"known", "none named", "incomplete", "unknown"}
    assert "incomplete" in pluginpage.CLOSURES_SAID["incomplete"] and "none" not in pluginpage.CLOSURES_SAID["unknown"]


# ---- the closures-file format is read only in a closures file, never in the sources file ---------------------------
def test_format_keys_in_the_sources_file_mean_nothing_and_are_said(tmp_path, monkeypatch):
    secret = tmp_path / "secretdir"
    secret.mkdir()
    f = _file(tmp_path, {"schema": "estate.closures/0", "closed_names": [seg("n", "zzprivate")], "closed_paths": None,
                         "closed_paths_complete": False, "known_closed_paths": [str(secret)],
                         "known_open_paths_near": []}, "src.json")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(f))
    h = tmp_path / "h"
    # read by the sources file's own rules: no "closed" list and no closures file, so none named, as in 1.3.0; its
    # format keys, closed_names among them here, are not read
    assert not api.closures_known(h) and closed_mod.why_unknown(h) is None
    assert api.is_closed_place(secret / "x.txt", h)                           # every path closed to a plug-in
    assert not closed_mod.in_closed_place(secret / "x.txt", h)                # known_closed_paths: not read here
    assert not closed_mod.in_closed_place(tmp_path / "w" / "zzprivate" / "a.md", h)   # nor its names
    rows = [r for r in closed_mod.problems(h) if r["kind"] == "closures lookalike"]
    assert len(rows) == 1 and "point closures_file at it" in rows[0]["text"].lower()   # said, never closing
    # beside a "closed" list: known by that list, the format-shaped file's names still not read
    f.write_text(json.dumps({**json.loads(f.read_text(encoding="utf-8")), "closed": []}), encoding="utf-8")
    assert api.closures_known(h) and not api.is_closed_place(tmp_path / "w" / "zzprivate" / "a.md", h)
    from semantext import pluginpage
    assert not pluginpage._closures_here(f, json.loads(f.read_text(encoding="utf-8")))[0]
    assert {"known_closed_paths", "closed_paths_complete", "schema"} <= pluginpage.reserved_keys(h)   # as settings


def test_a_sources_file_that_does_not_look_like_a_closures_file_is_not_said(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    for doc in ({"schema": "my-config/2", "closed": []}, {"closed": []},
                {"closed": [], "closures_file": str(tmp_path / "h" / "sources.json")}):
        h = _home(tmp_path, doc)
        assert not [r for r in closed_mod.problems(h) if r["kind"] == "closures lookalike"], doc


def test_the_same_file_named_as_the_closures_file_is_read_in_the_format(tmp_path, monkeypatch):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    secret = tmp_path / "secretdir"
    f = _file(tmp_path, {"schema": "estate.closures/0", "closed_names": [], "closed_paths": None,
                         "closed_paths_complete": False, "known_closed_paths": [str(secret)]}, "fmt.json")
    h = _home(tmp_path, {"closures_file": str(f), "closures_key": "closed_paths"})
    assert not api.closures_known(h) and closed_mod.in_closed_place(secret / "x.txt", h)


# ---- nothing 1.3.0 read changes meaning, with one deliberate exception ---------------------------------------------
# Each case is a sources file as 1.3.0 could read it (with "@" for the test's folder), a closures file beside it when
# it names one, and whether it names itself as its closures file. RECORDED is what Semantext 1.3.0 (v1.3.0) gave for
# each: closures_known, and closures() with the folder written "@". HEAD must give the same, and must judge every path
# in WHERE as 1.3.0 judges it, in each of three views (below).
CASES_130 = {
    "no sources file": (None, None, False),
    "an empty list": ({"closed": []}, None, False),
    "one folder": ({"closed": ["@/shut"]}, None, False),
    "another tool's schema": ({"schema": "my-config/2", "closed": [], "run_records": ["@/root"]}, None, False),
    "another tool's schema, nothing named": ({"schema": "my-config/2", "run_records": ["@/root"]}, None, False),
    "itself as closures file, run records": ({"closed": [], "run_records": ["@/root"]}, None, True),
    "itself as closures file, seats": ({"closed": [], "seats": "@/root/seats.json"}, None, True),
    "a closures file, its own key": ({"closures_file": "@/c.json", "closures_key": "places"},
                                     {"places": ["@/shut"], "notes": ["@/x"]}, False),
    "a closures file with other lists": ({"closures_file": "@/c.json"},
                                         {"closed": ["@/shut"], "closed_paths": ["@/other"]}, False),
    "not a list": ({"closed": "notalist"}, None, False),
    "a relative path": ({"closed": ["relative"]}, None, False),
    "a closures file that is not there": ({"closures_file": "@/missing.json"}, None, False),
    "format keys in the sources file": ({"closed": [], "known_closed_paths": ["@/x"]}, None, False),
    "the format's schema in the sources file": ({"schema": "estate.closures/0", "closed": ["@/shut"],
                                                 "closed_paths": None}, None, False),
    "a closures file with another tool's schema": ({"closures_file": "@/c.json"},
                                                   {"schema": "my-tool/3", "closed": ["@/shut"]}, False),
    "both lists merge": ({"closed": ["@/shut"], "closures_file": "@/c.json"}, {"closed": ["@/b"]}, False),
    "itself, a null beside": ({"closed": ["@/shut"], "closed_paths": None}, None, True),
    "a closures key with no file": ({"closures_key": "closed"}, None, False),
    "path records in the sources file": ({"closed": [{"path": "@/shut"}]}, None, False),
    "path records in a closures file without the schema": ({"closures_file": "@/c.json"},
                                                           {"closed": [{"path": "@/shut", "id": "x"}]}, False),
    "the format's shape as the sources file": ({"schema": "estate.closures/0", "closed_names": [seg("z", "zzprivate")],
                                                "closed_paths": None, "closed_paths_complete": False,
                                                "known_closed_paths": ["@/shut"]}, None, False),
}
RECORDED = {
    "no sources file": (False, []),
    "an empty list": (True, []),
    "one folder": (True, ["@/shut"]),
    "another tool's schema": (True, []),
    "another tool's schema, nothing named": (False, []),
    "itself as closures file, run records": (True, []),
    "itself as closures file, seats": (True, []),
    "a closures file, its own key": (True, ["@/shut"]),
    "a closures file with other lists": (True, ["@/shut"]),
    "not a list": (False, None),
    "a relative path": (False, None),
    "a closures file that is not there": (False, None),
    "format keys in the sources file": (True, []),
    "the format's schema in the sources file": (True, ["@/shut"]),
    "a closures file with another tool's schema": (True, ["@/shut"]),
    "both lists merge": (True, ["@/shut", "@/b"]),
    "itself, a null beside": (True, ["@/shut"]),
    "a closures key with no file": (False, None),
    "path records in the sources file": (False, None),
    "path records in a closures file without the schema": (False, None),
    "the format's shape as the sources file": (False, []),
}
# The one deliberate exception: a closures file in the closures-file format (its schema), new in 1.4, is read by that
# format's rules. 1.3.0 read neither file below (unknown: every path closed).
EXCEPTION_14 = {
    "the format, its complete list not supplied": (
        {"closures_file": "@/c.json", "closures_key": "closed_paths"},
        {"schema": "estate.closures/0", "closed_paths": None, "closed_paths_complete": False,
         "known_closed_paths": ["@/shut"]}, False),
    "the format, its complete list as path records": (
        {"closures_file": "@/c.json", "closures_key": "closed_paths"},
        {"schema": "estate.closures/0", "closed_paths": [{"path": "@/shut"}], "closed_paths_complete": True}, False),
}
EXCEPTION_AT_HEAD = {
    "the format, its complete list not supplied": (False, ["@/shut"]),       # the lower bound, for built-in readers
    "the format, its complete list as path records": (True, ["@/shut"]),
}
# Files that 1.4 closes more (never less): every path 1.3.0 closed stays closed, in every view.
CLOSES_MORE_14 = {
    "closed names null": ({"closed": ["@/shut"], "closed_names": None}, None, False),
    "a names key with no closures file": ({"closed": [], "closures_names_key": "x"}, None, False),
    "a names key on a closures file without the schema": (
        {"closures_file": "@/c.json", "closures_names_key": "closed_names"}, {"closed": ["@/shut"]}, False),
    "the format, a list not marked complete": (
        {"closures_file": "@/c.json", "closures_key": "closed_paths"},
        {"schema": "estate.closures/0", "closed_paths": ["@/shut"]}, False),
    "closed names alone": ({"closed_names": [seg("z", "zzprivate")]}, None, False),
    "closed names beside an empty list": ({"closed": [], "closed_names": [seg("z", "zzprivate")]}, None, False),
    "another version of the format": ({"closures_file": "@/c.json"},
                                      {"schema": "estate.closures/1", "closed": ["@/shut"]}, False),
    "names in a closures file without the schema": ({"closures_file": "@/c.json"},
                                                    {"closed": ["@/shut"], "closed_names": []}, False),
    "an entry that cannot be compared": ({"closed": ["//server/share/x"]}, None, False),
}
CLOSES_MORE_AT_HEAD = {
    "closed names null": (False, None),
    "a names key with no closures file": (False, None),
    "a names key on a closures file without the schema": (False, None),
    "the format, a list not marked complete": (False, ["@/shut"]),
    "closed names alone": (False, ["name:z"]),                  # none named for a plug-in; the names close more
    "closed names beside an empty list": (True, ["name:z"]),
    "another version of the format": (False, None),
    "names in a closures file without the schema": (False, None),
    "an entry that cannot be compared": (True, ["//server/share/x"]),   # known, closing every path: said as a problem
}
ALL_14 = {**CASES_130, **EXCEPTION_14, **CLOSES_MORE_14}
# the paths judged in each case; on Windows also each written with \\?\ (read as the drive) and \\.\ (a device path)
WHERE = ["shut/a.md", "open/a.md", "b/a.md", "other/a.md", "x/a.md", "root/a.md", "w/zzprivate/a.md"]
VIEWS = ("plug-in", "built-in", "strict")   # is_closed_place; in_closed_place; the run-record reader's (runs)
RUN_130 = r'''
import json, os, sys
root, base, cases = sys.argv[1], sys.argv[2], json.loads(open(sys.argv[3], encoding="utf-8").read())
where = json.loads(sys.argv[4])
sys.path.insert(0, root)
for k in ("HOME", "USERPROFILE"):
    os.environ[k] = os.path.join(base, "user")
os.environ["SEMANTEXT_HOME"] = os.path.join(base, "user", ".semantext")
from semantext.sources import closed, runs
out = {}
for name, (doc, other, selfref) in cases.items():
    here = os.path.join(base, "".join(c if c.isalnum() else "-" for c in name))
    for d in ("h", "shut", "open", "b", "other", "x", "root"):
        os.makedirs(os.path.join(here, d), exist_ok=True)
    def put(v):
        return json.loads(json.dumps(v).replace('"@/', json.dumps(here + "/")[:-1]))
    src = os.path.join(here, "sources.json")
    if doc is not None:
        doc = put(doc)
        if selfref:
            doc = {"closures_file": src, **doc}
        open(src, "w", encoding="utf-8").write(json.dumps(doc))
    if other is not None:
        open(os.path.join(here, "c.json"), "w", encoding="utf-8").write(json.dumps(put(other)))
    os.environ["SEMANTEXT_SOURCES"] = src
    h = os.path.join(here, "h")
    got = closed.closures(h)
    shown = None if got is None else [str(c).replace(here, "@").replace("\\", "/") if isinstance(c, str)
                                      else "name:" + c.id for c in got]
    judged = {}
    for rel in where:
        full = os.path.join(here, *rel.split("/"))
        forms = {rel: full}
        if os.name == "nt":
            forms["\\\\?\\ " + rel], forms["\\\\.\\ " + rel] = "\\\\?\\" + full, "\\\\.\\" + full
        for label, p in forms.items():
            judged[label] = [closed.is_closed_place(p, h), closed.in_closed_place(p, h), runs.is_closed_place(p, h)]
    out[name] = [closed.closures_known(h), shown, judged]
print(json.dumps(out))
'''


def _run_closures(root: Path, tmp_path: Path, tag: str, cases=None) -> dict:
    """Each case's (closures_known, closures with the folder as "@", {path label: [one answer per view]})."""
    import subprocess
    import sys
    base = tmp_path / tag
    base.mkdir()
    said = tmp_path / f"{tag}-cases.json"
    said.write_text(json.dumps(CASES_130 if cases is None else cases), encoding="utf-8")
    got = subprocess.run([sys.executable, "-I", "-B", "-c", RUN_130, str(root), str(base), str(said), json.dumps(WHERE)],
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stderr
    return {k: (v[0], v[1], v[2]) for k, v in json.loads(got.stdout).items()}


def _said(run: dict) -> dict:
    return {k: (v[0], v[1]) for k, v in run.items()}


def test_nothing_1_3_0_read_changes_meaning(tmp_path):   # must pass: every case as 1.3.0 gave it
    root = Path(__file__).resolve().parents[1]
    head = _run_closures(root, tmp_path, "head", ALL_14)
    assert _said({k: head[k] for k in CASES_130}) == RECORDED
    # the one deliberate exception, explicitly: the format's file whose complete list is not supplied is read by the
    # built-in readers as its lower bound (1.3.0: unknown), and stays unknown to plug-ins and the strict view
    assert _said({k: head[k] for k in EXCEPTION_14}) == EXCEPTION_AT_HEAD
    lower = head["the format, its complete list not supplied"][2]
    assert lower["shut/a.md"] == [True, True, True]                                  # closed in every view
    assert lower["open/a.md"] == [True, False, True]                                 # open to the built-in view only
    assert _said({k: head[k] for k in CLOSES_MORE_14}) == CLOSES_MORE_AT_HEAD
    names = [n for n in CLOSES_MORE_14 if n.startswith("closed names ")]
    for name in set(CLOSES_MORE_14) - set(names):                                     # for plug-ins: all closed
        assert all(v[0] and v[2] for v in head[name][2].values()), name
    # names never name the closures alone: none named for a plug-in (all closed), and they close what they name
    alone, beside = head["closed names alone"][2], head["closed names beside an empty list"][2]
    assert all(v[0] for v in alone.values())
    for judged in (alone, beside):
        assert judged["w/zzprivate/a.md"] == [True, True, True]
        assert judged["open/a.md"][1:] == [False, False]
    assert beside["open/a.md"][0] is False


def _v130(tmp_path: Path) -> Path:
    """The 1.3.0 tree (the v1.3.0 tag, or its source commit 42ab4ce where the tag is not fetched), unpacked; a skip
    where the repository holds neither."""
    import subprocess
    import tarfile
    root = Path(__file__).resolve().parents[1]
    tar = None
    for ref in ("v1.3.0", "42ab4ce"):
        try:
            tar = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", ref, "semantext"],
                                 capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            pytest.skip("git cannot be run here")
        if tar.returncode == 0:
            break
    if tar.returncode != 0:
        pytest.skip("this checkout does not hold 1.3.0 (the v1.3.0 tag, or its source commit): a shallow clone")
    old = tmp_path / "v130"
    old.mkdir()
    (tmp_path / "v130.tar").write_bytes(tar.stdout)
    with tarfile.open(tmp_path / "v130.tar") as t:
        if hasattr(tarfile, "data_filter"):
            t.extractall(old, filter="data")
        else:
            t.extractall(old)
    return old


def test_the_recorded_1_3_0_meanings_are_what_1_3_0_gives(tmp_path):
    # the recording itself, and how every path is judged in each view, checked against the 1.3.0 tree
    root = Path(__file__).resolve().parents[1]
    old = _run_closures(_v130(tmp_path), tmp_path, "run130", ALL_14)
    head = _run_closures(root, tmp_path, "head", ALL_14)
    assert _said({k: old[k] for k in CASES_130}) == RECORDED
    labels = set(old["one folder"][2])
    assert len(labels) == len(WHERE) * (3 if os.name == "nt" else 1)                 # the corpus is what it says
    for name in CASES_130:                                                            # identity: each path, each view
        assert head[name][2] == old[name][2], name
    seen = {"closed": 0, "open": 0}
    for name in CASES_130:
        for v in old[name][2].values():
            seen["closed" if v[0] else "open"] += 1
    assert all(seen.values()), seen                                                   # both answers occur
    # the one deliberate exception: unknown in 1.3.0, read by the format's rules now
    for name in EXCEPTION_14:
        assert _said({name: old[name]}) == {name: (False, None)}, name
        assert all(v == [True, True, True] for v in old[name][2].values()), name
    lower_old, lower = old["the format, its complete list not supplied"][2], \
        head["the format, its complete list not supplied"][2]
    for label in labels:
        assert lower[label][0] == lower_old[label][0] and lower[label][2] == lower_old[label][2], label
    assert lower["open/a.md"][1] is False and lower["shut/a.md"][1] is True           # only the built-in view opens
    records = head["the format, its complete list as path records"][2]
    assert records["shut/a.md"] == [True, True, True] and records["open/a.md"] == [False, False, False]
    if os.name == "nt":                                                              # a device path stays closed
        assert records["\\\\.\\ open/a.md"] == [True, True, True]
        assert records["\\\\?\\ open/a.md"] == [False, False, False]                 # the long drive form is the drive
    # closes more, never less: every path 1.3.0 closed stays closed, in every view, and some path closes now
    for name in CLOSES_MORE_14:
        more = 0
        for label in labels:
            for i, view in enumerate(VIEWS):
                assert head[name][2][label][i] or not old[name][2][label][i], (name, label, view)
                more += head[name][2][label][i] and not old[name][2][label][i]
        assert more, name


# ---- the root rule resolves the listed path too ---------------------------------------------------------------------
def test_a_root_holding_a_closed_folder_written_through_a_link_is_refused(tmp_path):   # must refuse
    real_root = tmp_path / "realroot"
    (real_root / "secret").mkdir(parents=True)
    door = tmp_path / "J"
    _link(real_root, door)
    via_link = [str(door / "secret")]
    assert closed_mod.contains_closed(str(real_root), via_link)
    assert closed_mod.contains_closed(str(door), via_link)
    other = tmp_path / "other"
    other.mkdir()
    assert not closed_mod.contains_closed(str(other), via_link)                 # must pass


def test_a_root_holding_a_closed_folder_written_in_its_short_name_is_refused(tmp_path):   # must refuse
    if os.name != "nt":
        pytest.skip("8.3 short names are Windows's")
    import ctypes
    real_root = tmp_path / "a-long-root-name"
    (real_root / "secret-folder").mkdir(parents=True)
    buf = ctypes.create_unicode_buffer(1024)
    if not ctypes.windll.kernel32.GetShortPathNameW(str(real_root / "secret-folder"), buf, 1024):
        pytest.skip("no short name on this volume")
    short = buf.value
    if os.path.normcase(short) == os.path.normcase(str(real_root / "secret-folder")):
        pytest.skip("short names are off on this volume")
    assert closed_mod.contains_closed(str(real_root), [short])
    assert not closed_mod.contains_closed(str(tmp_path / "elsewhere"), [short])     # must pass


# ---- reserved keys judged by casefold everywhere ---------------------------------------------------------------------
@pytest.mark.parametrize("key", ["cloſed", "CLOSED", "Known_Closed_Paths", "closed_paths_complete", "schema",
                                 " closed_names "])
def test_a_plug_in_may_not_declare_a_closures_key_in_any_case(key):   # must refuse
    from semantext import outside, registry
    with pytest.raises(ValueError, match="reserved"):
        registry.Registry().add("source", "tickets", outside.snapshot(_Source(("tickets_file", key))), origin="pkg")


# ---- the reserved-keys check survives python -O ----------------------------------------------------------------------
def test_the_reserved_keys_check_holds_under_python_O(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    code = ("import semantext.manifest as m; m.CLOSURE_KEYS = ('closed',); "
            "import semantext.sources.closed")
    got = subprocess.run([sys.executable, "-O", "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert got.returncode != 0 and "not reserved" in got.stderr                          # must refuse
    ok = subprocess.run([sys.executable, "-O", "-c", "import semantext.sources.closed"], cwd=root,
                        capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0, ok.stderr                                                 # must pass


# ---- a read context changed after it was made closes every path ---------------------------------------------------
@pytest.mark.parametrize("field, value", [("closures", ()), ("names", ()), ("home", "elsewhere")])
def test_a_read_context_whose_fields_are_set_afterwards_closes_every_path(tmp_path, field, value):   # must refuse
    shut = tmp_path / "shut"
    ctx = closed_mod.ReadContext(str(tmp_path), (str(shut),), (closed_mod.Name("n", "segment", ("private-notes",)),))
    assert not api.is_closed_place(tmp_path / "open" / "a.md", ctx)                  # must pass, as it was made
    assert api.is_closed_place(shut / "a.md", ctx)
    object.__setattr__(ctx, field, value)                                             # the shut folder "opened"
    assert api.is_closed_place(shut / "a.md", ctx) and api.is_closed_place(tmp_path / "open" / "a.md", ctx)


def test_a_read_context_made_again_is_sealed_again(tmp_path):   # must pass
    import dataclasses
    ctx = closed_mod.ReadContext(str(tmp_path), ())
    again = dataclasses.replace(ctx, closures=(str(tmp_path / "shut"),))
    assert not api.is_closed_place(tmp_path / "open" / "a.md", again)
    assert api.is_closed_place(tmp_path / "shut" / "a.md", again)


# ---- no home at all: every route answers, saying so ---------------------------------------------------------------
def test_every_route_answers_with_no_home(monkeypatch):
    from semantext import paths
    from semantext.sources import view
    for name in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SEMANTEXT_HOME", "SEMANTEXT_SOURCES"):
        monkeypatch.delenv(name, raising=False)

    def no_home():
        raise RuntimeError("Could not determine home directory.")
    monkeypatch.setattr(paths, "home", no_home)
    for route in view.ROUTES:
        got = view.answer(route)                                                     # must pass: never raises
        assert got["off"] is True and any(p["kind"] == "no home" for p in got["frame"]["problems"]), route
    assert view.answer("no-such-route") is None


def test_with_a_home_a_route_is_read_as_before(tmp_path, monkeypatch):   # must pass: the partner
    from semantext.sources import view
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    got = view.answer("projects", home=tmp_path)
    assert got["place"] == "projects" and not any(p["kind"] == "no home" for p in got["frame"]["problems"])


# ---- path records are read only where the closures-file format's schema says so ------------------------------------
def test_path_records_are_read_only_in_a_file_that_says_the_schema(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    shut, elsewhere = tmp_path / "shut", tmp_path / "open" / "a.md"
    h = _home(tmp_path, {"closed": [{"path": str(shut)}]})                 # must refuse: unknown, as in 1.3.0
    assert not api.closures_known(h) and closed_mod.in_closed_place(elsewhere, h)
    plain = _file(tmp_path, {"closed": [{"path": str(shut), "id": "x"}]}, "plain.json")
    h = _home(tmp_path, {"closures_file": str(plain)})                     # must refuse: no schema, unknown
    assert not api.closures_known(h) and closed_mod.in_closed_place(elsewhere, h)
    fmt = _file(tmp_path, {"schema": "estate.closures/0", "closed_paths": [{"path": str(shut)}],
                           "closed_paths_complete": True}, "fmt.json")
    h = _home(tmp_path, {"closures_file": str(fmt), "closures_key": "closed_paths"})
    assert api.closures_known(h) and api.is_closed_place(shut / "a.md", h)  # must pass: read under the schema
    assert not api.is_closed_place(elsewhere, h)


# ---- the seal: once, on every field, the names inside included ------------------------------------------------------
def test_a_made_read_context_is_never_sealed_anew(tmp_path):   # must refuse
    ctx = closed_mod.ReadContext(str(tmp_path), (str(tmp_path / "shut"),))
    object.__setattr__(ctx, "closures", ())
    with pytest.raises(TypeError, match="sealed once"):
        ctx.__post_init__()
    assert api.is_closed_place(tmp_path / "open" / "a.md", ctx)


def test_a_name_changed_after_its_context_was_made_closes_every_path(tmp_path):
    n = closed_mod.Name("n", "segment", ("private-notes",))
    ctx = closed_mod.ReadContext(str(tmp_path), (), (n,))
    assert not api.is_closed_place(tmp_path / "open" / "a.md", ctx)                  # must pass, as made
    object.__setattr__(n, "texts", ("zzz",))
    assert api.is_closed_place(tmp_path / "open" / "a.md", ctx)                      # must refuse

    class Sub(closed_mod.Name):
        pass
    with pytest.raises(TypeError):                                                    # must refuse: only a Name
        closed_mod.ReadContext(str(tmp_path), (), (Sub("n", "segment", ("private-notes",)),))


def test_each_plug_in_gets_its_own_sealed_copy(tmp_path):
    shut, elsewhere = tmp_path / "shut", tmp_path / "open" / "a.md"
    ctx = closed_mod.ReadContext(str(tmp_path), (str(shut),), (closed_mod.Name("n", "segment", ("private-notes",)),))
    a, b = closed_mod.own_copy(ctx), closed_mod.own_copy(ctx)
    assert a is not ctx and a is not b and a.names[0] is not ctx.names[0] and a.names[0] is not b.names[0]
    object.__setattr__(a, "closures", ())
    object.__setattr__(a.names[0], "texts", ("zzz",))
    assert api.is_closed_place(elsewhere, a)                                          # must refuse: the changed copy
    for kept in (b, ctx):                                                             # must pass: the others hold
        assert not api.is_closed_place(elsewhere, kept)
        assert api.is_closed_place(shut / "a.md", kept) and api.is_closed_place(tmp_path / "private-notes" / "x", kept)
    object.__setattr__(ctx, "closures", ())
    assert api.is_closed_place(elsewhere, closed_mod.own_copy(ctx))                   # must refuse: never resealed


# ---- the Plug-ins route with a Semantext home and no home of the system's -----------------------------------------
def test_the_plugins_route_answers_with_no_system_home(tmp_path, monkeypatch):
    from semantext.sources import view
    for name in ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "SEMANTEXT_SOURCES"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SEMANTEXT_HOME", str(tmp_path / "sh"))

    def no_home(cls):
        raise RuntimeError("Could not determine home directory.")
    with monkeypatch.context() as m:
        m.setattr(Path, "home", classmethod(no_home))
        got = view.answer("plugins")                                                  # must pass: never raises
    assert isinstance(got, dict)


# ---- the keys the closures are read from: found one way, reserved as found -----------------------------------------
def test_the_named_keys_are_reserved_as_closed_py_reads_them(tmp_path, monkeypatch):
    from semantext import pluginpage
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    doc = {"closures_file": str(tmp_path / "c.json"), "closures_key": " My Closed ", "closures_names_key": "Nm"}
    h = _home(tmp_path, doc)
    assert closed_mod.keys_named(doc) == (" My Closed ", "Nm")                       # exactly as written
    keys = pluginpage.reserved_keys(h)
    assert {" my closed ", "my closed", "nm"} <= keys                                 # must refuse
    assert "tickets_file" not in keys                                                 # must pass
    assert closed_mod.keys_named({}) == ("closed", "closed_names")


# ---- a docs attack: what the docs promised and the code did not -----------------------------------------------------
@pytest.mark.parametrize("entry", [{"id": "d", "form": "segment", "segment": "..."},
                                   {"id": "d", "form": "substring", "substrings": ["...."]},
                                   {"id": "d", "form": "suffix", "suffixes": ["ok", "..."]}])
def test_a_literal_made_only_of_dots_is_unknown(tmp_path, monkeypatch, entry):   # must refuse
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [entry]})
    assert not api.closures_known(h) and api.is_closed_place(tmp_path / "open" / "a.md", h)


def test_a_literal_with_dots_and_more_is_a_name(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [], "closed_names": [seg("d", "...a")]})
    assert api.closures_known(h) and api.is_closed_place(tmp_path / "...a" / "x.md", h)


def test_a_wide_name_is_said_with_names_alone_too(tmp_path, monkeypatch):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    wide = {"id": "w", "form": "substring", "substrings": ["a"]}
    h = _home(tmp_path, {"closed_names": [wide]})
    assert [r for r in closed_mod.problems(h) if r["kind"] == "closures too wide"]    # must refuse the silence
    h = _home(tmp_path, {"closed_names": [seg("n", "private-notes")]})
    assert not [r for r in closed_mod.problems(h) if r["kind"] == "closures too wide"]   # must pass


@pytest.mark.parametrize("entry", ["//server/share/x", "\\\\server\\share\\x", "\\\\.\\C:\\x"])
def test_an_entry_that_cannot_be_compared_closes_every_path_and_is_said(tmp_path, monkeypatch, entry):
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    if not os.path.isabs(entry):
        pytest.skip("not a full path on this system: unknown, and said as that")
    h = _home(tmp_path, {"closed": [entry]})
    assert closed_mod.closures_state(h)["state"] == "known"
    assert api.is_closed_place(tmp_path / "open" / "a.md", h) and closed_mod.in_closed_place(tmp_path / "a.md", h)
    assert closed_mod.in_closed_place_strict(tmp_path / "a.md", h)                    # must refuse, in all three views
    rows = [r["text"] for r in closed_mod.problems(h)]
    assert any("cannot be compared closes every path" in t and entry in t for t in rows), rows


def test_an_entry_that_can_be_compared_is_not_said(tmp_path, monkeypatch):   # must pass
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    h = _home(tmp_path, {"closed": [str(tmp_path / "shut")]})
    assert not any("cannot be compared" in r["text"] for r in closed_mod.problems(h))
    assert not api.is_closed_place(tmp_path / "open" / "a.md", h)


def test_enable_with_names_alone_says_why_and_a_fix_that_works(tmp_path, monkeypatch):
    from semantext import plugincmd
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)
    monkeypatch.setattr(plugincmd, "human_terminal", lambda: None)
    h = _home(tmp_path, {"closed_names": [seg("n", "private-notes")]})
    with pytest.raises(plugincmd.Refused) as e:                                       # must refuse
        plugincmd.run(h, "enable", "source.x", print)
    said = str(e.value)
    assert "name your closed places first" in said and "alone never name" in said
    assert 'a "closed" list' in said and all(ord(c) < 127 for c in said)              # through the renderer


@pytest.mark.parametrize("value", ["C:\\x\\con .txt", "C:\\x\\AUX  .d", "/x/nul .txt", "C:\\x\\COM\u00b9", "C:\\x\\CONIN$"])
def test_a_path_setting_refuses_a_device_in_the_path_rules_shape(value):   # must refuse
    from semantext import pluginpage
    with pytest.raises(pluginpage.Refused, match="device"):
        pluginpage.check_value({"key": "k", "type": "path"}, value)


def test_a_path_setting_keeps_a_name_that_only_starts_like_a_device(tmp_path):   # must pass
    from semantext import pluginpage
    good = str(tmp_path / "console" / "con-notes.txt")
    assert pluginpage.check_value({"key": "k", "type": "path"}, good) == good
