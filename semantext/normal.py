"""Unicode normalisation in time linear in the text, and exactly as unicodedata gives it: nfkc(), nfc(), nfd(), nfkd()
and normalize(form, text).

THE FINDING (Orithises, round-4 attack on actclass, finding 3). CPython's unicodedata.normalize takes time that grows
with the square of the text, on text an agent can send, in two shapes:
- A long run of combining marks. Canonical reordering is an insertion sort, so a run whose classes descend costs the
  square of its length: `git push a` + U+0316 U+0301 x 32,731 took 1.4 s through decide.decide, and marks of 26
  classes in descending order about 3 s at 64 KiB.
- A text that expands a lot. The decomposition buffer grows 10 characters at a time, so 64 Ki x U+FDFA (18 characters
  each under NFKC) took 0.52 s in normalize alone, x4 per doubling.
Every normalisation of text an agent or a page can send goes through here: actclass._shell_acts (every shell command),
inbox._reads_as, model._plain, reading.normalize (the page's Try a message, `semantext read`, and the proxy's reading
of the person's words), and the folds of sources/closed.py (a path from a plug-in, a work fact or a run record).

THE GUARANTEE. normalize(form, text) returns what unicodedata.normalize(form, text) returns, character for character,
for every text and each of the four forms; and its work is a constant times the length of the text plus the length of
its decomposition, which is at most 18 times the text (U+FDFA's).

HOW.
1. A text of PIECE characters or fewer, or one that is all ASCII, goes to unicodedata.normalize whole: its cost is
   bounded by PIECE squared, and ASCII is returned as it is.
2. A longer text is decomposed (NFD, or NFKD for the compatibility forms) PIECE characters at a time. WHY A CUT MAY FALL
   ANYWHERE: a text's full decomposition is each character's decomposition in turn (UAX #15, D68), so no character's
   result depends on a neighbour; and each call's buffer holds at most PIECE x 18 characters, so its growth by 10s
   stays small.
3. Canonical ordering is the one step of decomposition that reads across characters: each run of non-starters
   (combining class not 0) is sorted by class, stably. Each piece comes back in that order, so the joined text can be
   out of order only where two pieces meet inside a run. One linear pass (unicodedata.is_normalized("NFD", ...), a
   quick check that stops at the first mark out of order) says whether any is; where one is, that run and nothing else
   is sorted again, by a counting sort on the class: linear in the run, however long it is.
4. NFC and NFKC are then ONE call of unicodedata.normalize("NFC", ...) over the whole decomposition: NFKC is NFC of
   NFKD (UAX #15), and composition, the step that joins a character to its neighbours, is never cut. That call is
   linear: its own decomposition of a decomposed text copies it, its insertion sort has nothing to move, and its
   composition is one pass, a scan from each starter that stops at the next.

WHY NOT UAX #15's STREAM-SAFE TEXT FORMAT (the item asked for it: U+034F after every 30 non-starters, then normalise).
It bounds a run by changing the text, and a changed text changes what a reader decides, here in the costly direction.
Measured on sources/closed.py: the closed name "café" (a substring) closes "Q:/d/cafe" + U+0316 x 30 + U+0301 + "/x"
under unicodedata, whose NFC sorts U+0301 (class 230) past the thirty marks of class 220 and composes "é"; with U+034F
after the thirtieth mark, U+0301 can no longer reach the "e", no leg holds "café", and the path opens (pinned in
tests/test_normal_linear.py). Sorting a run by class costs time in proportion to the run, so no run needs a cap, and
nothing any reader decides changes.

LIMITS, stated.
- The decomposition is as long as it is: 64 KiB of U+FDFA is 1.18 million characters out, and a caller that then walks
  it character by character (actclass's and reading's Cf filters) pays for each of them too.
- Linear, with constants: about one unicodedata call per PIECE characters of a long non-ASCII text, and a pass in
  Python over any run of marks that a cut leaves out of order (about 0.2 us a character).
- Measured worst shapes (close-1 attack, this machine; figures move with the machine, the growth does not): the helper
  on 64 KiB takes at most 0.08 s (U+FDFA with one NFC_QC=Maybe mark: that mark turns off unicodedata's quick check on
  the 1.18 million-character decomposition); decide.decide on a 64 KiB command at most 0.25 s; a 1 MiB in-piece shape
  (marks of classes 230/132/131 cycled) 0.8 s, x3.4 to x4.6 per x4 of text. All are the sampled shapes, not a proof
  for every shape; the proof is the construction above, and the bars the tests hold are 0.1 s and 0.5 s.
- "Every normalisation ... goes through here" means the package's own calls. The standard library's own
  normalisations are not routed: urllib's netloc check in semantext/server.py runs NFKC on a request target or Referer
  host, which http.server decodes as Latin-1, so it is bounded and measured at 15 ms on 64 K. The test that forbids a
  bare call elsewhere matches the module by name (aliases, getattr, partial, ucd_3_2_0, from-imports) but not
  importlib.import_module; the spy test is the second guard.
- Not this module's: the reader re-reads the expanded offer once per act (reading.py), so POST /api/read with an offer
  and every act, at its cap, costs 1.2 s (U+33C6 cycled), 2.2 s (U+FDFA U+3000) and 3.7 s (U+FDFA), the same on the
  base; the cause is any text that expands, not the two shapes pinned in the tests. The fix lives in reading.py.
- Exactness rests on CPython normalising as UAX #15 says (each character decomposed alone, a stable sort by class, one
  composition pass); tests/test_normal_linear.py holds it on every code point of this Python's Unicode version, on
  every pair that composes or reorders placed across a cut, and on a seeded fuzz.
"""
from __future__ import annotations

import unicodedata

PIECE = 64   # characters decomposed per unicodedata call; a text this short or shorter is handed to it whole
_DECOMPOSE = {"NFC": "NFD", "NFD": "NFD", "NFKC": "NFKD", "NFKD": "NFKD"}
_COMPOSE = frozenset({"NFC", "NFKC"})


def normalize(form: str, text: str) -> str:
    """unicodedata.normalize(form, text), in time linear in the text and its decomposition (see the module's docstring).
    A form or a text unicodedata would refuse goes to it, so its error is the same."""
    decompose = _DECOMPOSE.get(form) if type(form) is str else None
    if decompose is None or not isinstance(text, str) or len(text) <= PIECE or text.isascii():
        return unicodedata.normalize(form, text)
    out = _decomposed(text, decompose)
    return unicodedata.normalize("NFC", out) if form in _COMPOSE else out


def nfkc(text: str) -> str:
    return normalize("NFKC", text)


def nfc(text: str) -> str:
    return normalize("NFC", text)


def nfd(text: str) -> str:
    return normalize("NFD", text)


def nfkd(text: str) -> str:
    return normalize("NFKD", text)


def _decomposed(text: str, form: str) -> str:
    """NFD or NFKD of a text, a piece at a time, then put in canonical order where two pieces meet (steps 2 and 3)."""
    parts = [unicodedata.normalize(form, text[i:i + PIECE]) for i in range(0, len(text), PIECE)]
    out = "".join(parts)
    return out if unicodedata.is_normalized("NFD", out) else _ordered(out, parts)


def _ordered(text: str, parts: list) -> str:
    """The joined pieces in canonical order. Each piece is in order, so a mark is out of order only at the first
    character of a piece; each run of non-starters holding such a place is sorted again by class (a counting sort, so
    the same class keeps its order), once, and the rest of the text is copied as it is."""
    comb = unicodedata.combining
    n, out, done, at = len(text), [], 0, 0
    for p in parts[:-1]:
        at += len(p)                                   # where this piece ends and the next begins
        if at < done:
            continue                                   # inside a run already sorted
        c = comb(text[at])
        if not c or comb(text[at - 1]) <= c:
            continue                                   # in order here
        start = at - 1
        while start > done and comb(text[start - 1]):
            start -= 1                                 # back to the run's first mark
        by_class: dict = {}
        end = start
        while end < n:                                 # on to its end, each mark into its class's list
            ch = text[end]
            k = comb(ch)
            if not k:
                break
            same = by_class.get(k)
            if same is None:
                by_class[k] = [ch]
            else:
                same.append(ch)
            end += 1
        out.append(text[done:start])
        out.extend("".join(by_class[k]) for k in sorted(by_class))
        done = end
    out.append(text[done:])
    return "".join(out)
