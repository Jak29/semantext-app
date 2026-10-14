# How Semantext is tested

Every promise Semantext makes has a check that can fail. Five of them are laws: properties a proof would state,
checked case by case. The rest are measures of what each action touches, and promises from these docs, each with a
case that must pass and a case that must be refused. Laws are in `tests/test_laws.py`, promises across the test suite,
and measures in `tools/measure.py` (run it to see the current numbers on your machine).

## Laws: properties a proof would state, checked case by case

Each law borrows the mechanism of a known result. Where a law holds only on a finite family, the test checks every
case of it.

| Law | Borrowed from | The check |
|---|---|---|
| **Loops close.** A change followed by `undo --last` gives back the exact bytes, and only in its own environment. | Consistency on a network: data comes from one potential exactly when every loop closes, and a loop that does not close is the certificate. | Every kind of change, then undo; random walks of 120 steps over 12 seeds against a reference model, over environments whose names share a prefix (`work`, `work-2`, `work-a`). |
| **The instrument can fail.** | (method) | The same walks, run on a build with a known undo fault, catch it within a few dozen steps. A law test that cannot fail is not evidence. |
| **Settling.** Repeating a maintenance step reaches a fixed point or a 2-cycle, never a drift. | Majority dynamics on symmetric networks settle with period at most 2 (Goles and Olivos). | `toggle` and `pin` are exact 2-cycles; installing into the settings file settles at once; the card and its file are fixed points of reading them. |
| **Exhaustive certificates.** A claim about every case of a finite family is checked case by case. | Proof by exhaustion, with the table's hash as the certificate. | Name validity on every string of length 0 to 3 over a 12-symbol alphabet, plus the length limits and the reserved names; the page's guards on every combination of Host, Origin, X-Semantext and method; the card's size limit on every card of 0 to 6 rules, at three limits. |
| **The window law.** A fault that needs k steps is invisible to every shorter test. | Frustration: a frustrated loop is invisible to every measurement smaller than the loop. | The undo fault needed 4 steps (create, create, teach, undo), so the walks run 120. |
| **What a save keeps.** The live file keeps the data; `history/` keeps the text. | Change of basis: a transform keeps only what its basis leaves invariant. | A comment written by hand in a rule file, then a `teach`: the comment leaves the live file, and the copy history made just before that change holds the edited text exactly. The FAQ says so. |

## Measures: what each action touches

| Measure | One count is | Target |
|---|---|---|
| Undeclared touches | a file an action creates, changes or removes beyond its declared ones | 0 |
| Outbound connections | one connection opened during an action (the page's own listening socket is not one) | 0, except `backtest --reader`, which calls the model you name (announced before its first call off this machine) |
| Processes started | one process an action starts | 0 (no module imports `subprocess`) |
| Hostile-input tracebacks | one input from a fixed, seeded corpus (hook events, bad command lines) that ends in a traceback, or a hook exit other than 0 | 0 |
| Hook bytes | the bytes the hook writes for one prompt | at most 9,500 |
| Card fidelity | live rules shown on the hook's card, out of all live rules | all, until the size limit; then the card says how many were left out |
| Hook time | one call to the hook | tracked: it grows with the number of rules, since the rule files are read on every prompt |
| Settings round trip | one settings file, installed into and then uninstalled from | the same JSON |
| Guard mutation score | one guard removed from a copy of the package | every removal makes a test fail |

## Promises, each with its check

| # | Promise (from these docs) | Must pass | Must be refused, or survived |
|---|---|---|---|
| 1 | The hook never blocks a prompt | a normal prompt: exit 0 | hostile inputs and the seeded corpus: exit 0, no traceback |
| 2 | The hook stays under its byte limit | a card just under the limit stays under it | the size limit on every small card |
| 3 | A rule is never cut in the middle | whole lines are kept | the same, at three limits |
| 4 | Undo never deletes | undoing a rule archives it | the random walks |
| 5 | `undo --last` restores this environment's last version | the walks hold | it refuses with no history, and never reads another environment's |
| 6 | The page is served on this machine only | 127.0.0.1 and localhost serve | 0.0.0.0, the empty host, ::, 127.0.0.2, LOCALHOST and a LAN address are refused |
| 7 | The page answers only requests addressed to it | its own Host | the full Host, Origin and method table |
| 8 | A change comes only from its own page | X-Semantext and its own Origin | the same table |
| 9 | A settings file that is not valid JSON is never overwritten | (valid files install) | odd-shaped JSON is refused and left untouched |
| 10 | The hook entry is never added twice | installing twice leaves one entry | it settles at once |
| 11 | Nothing leaves your machine unless you ask | no connection in any action | with sockets patched to refuse, every action still works; the model reader, which you name, is the one exception |
| 12 | Nothing is heard unless you switch it on | hearing on: the prompt is kept exactly | hearing off: nothing is written |
| 13 | Your exact words are kept | YAML specials and Unicode survive | prompts in any language, on Windows |
| 14 | `read` saves nothing | reading "delete ...": no file touched | (the touch audit) |
| 15 | A rule file cannot run code | safe loading | a `!!python/object` file is refused, and nothing runs |
| 16 | Importing the package writes nothing and connects nowhere | importing in an empty home | sockets patched to refuse |
| 17 | A valid hand edit is kept; any change rewrites the file from its data, and history keeps the text | a valid hand edit is accepted; history holds the edited text exactly | the FAQ says comments are not kept in the live file |

## Also tested
- **The inbox:** ids stay distinct under concurrent asks, and every line parses; a damaged line is skipped; answers
  come from a person at their own terminal only, never from an agent's shell; words are kept verbatim; a closed or
  unknown id is refused; the hook writes the inbox only for an answer the user typed in their own message (by how it
  opens and by the tool's own record), and a relayed message, a notice or a message with no record answers nothing;
  only a message that is one answer in the strict form and nothing else is an answer, so pasted notes, issue lists,
  ranked lists and a line that only mentions a request answer nothing; an answer's key-like run is withheld from
  everything sent to an agent; the hook stays within its byte limit with many answers waiting.
- **The register and the counts:** an answer to the same question is shown beside a new request and never used for
  it; the counts say whether the rule for each kind of message went with it (a rule switched off did not); only the
  page reads them; a feed line written before `noticed` was kept is still read.
- **Instruction files:** the byte round trip for LF, CRLF, a byte-order mark, no final newline, empty and Unicode files;
  one block only; no local path in the block; malformed markers refused, with the file untouched; `sync` restores only
  the block, and settles at once.
