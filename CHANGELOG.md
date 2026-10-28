# Changelog

All notable changes to Semantext are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.3.0] - 2026-10-28

Two new things, Work and the v2 page, and the first plug-in API. Outside plug-ins stay off: none reads anything until
the closed places are named (`"closed"` or a `"closures_file"` in the sources file), and none loads until you turn it
on at your console.

### Added: Work
- **A work store with one writer** (`semantext.work`): items, epics, moves, links, comments and decisions, kept as a
  hash chain of events and folded into the board. Only the chain mints item numbers; one writer appends, under a lock,
  only after the prefix it has verified, and a line whose write was cut off is adopted by the next append and only
  that one.
- **`semantext work new|move|link|unlink|comment|list|show`**, the command line. Who may make each move is a rule
  (`work/rules.py`): void is the owner's, parked and reopening are the person's, review needs a deliverable.
- **Your word, checked against the transcript.** A move that is yours carries the span of your own words in the
  session transcript (path, offset, length, sha256), which the card hook writes to `<home>/work/turns/`. It is checked
  again whenever it is read; a span that does not match, an absurd offset, or an act with no span is "unverified",
  never yours. One record of your words authorizes one act. A cached verdict stands only while the span's sha256
  does.
- **Clauses read for real:** a decision counts for an item only when its own words name the item or its epic (notes
  never count); run records come through `runs.py` and verdicts from the verdicts file; evidence or a piece that names
  no maker leaves its clause "unknown", never "independent".
- **The Work place on the v2 page:** Waiting on you, the board, the backlog, the estate's columns and the item panel,
  with the open item in the address.

### Added: the v2 page
- **`/v2`**, read-only, in files (`index.html`, `style.css` and one ES module per place): Waiting, Projects,
  Documents, Record, Estate and Work. Its Content-Security-Policy has `style-src 'self'` and no `'unsafe-inline'`.
  Documents are served by row (`/api/v2/doc/<place>/<row_id>`) and checked again when served. A write whose referer is
  a plug-in's page module, or that is not a plain fetch, is refused.

### Security (from the reviews of Work and of the gate reader)
- A forged or replayed act of yours, an act with no span, and a span offset past 2**63 are all unverified.
- The inbox reads no requests file that is a link of any kind (symbolic, junction or hard) or that sits in a closed
  place; before, a `requests.jsonl` hard-linked to any readable file was shown as that agent's cards.
- A package that calls itself built-in is an outside plug-in, with every guard on. Anything a plug-in call raises,
  SystemExit with any code included, is an error, and a document is served only on its check's explicit pass.
- Calls into plug-ins: at most 4 in flight per plug-in and 16 hanging in all, waiting for a turn kept apart from the
  run budget, and one page's answers capped at 8 MB.
- A seat's home is joined in one place for the places and the gates readers, which refuses a path that names its own
  start. A settings or seats file that gives a key twice is refused.
- The gate reader runs on Python 3.10 again (a regex used a quantifier 3.10 does not know; every regex is now compiled
  by a test). Later git extensions (`refStorage`, `relativeWorktrees`) are ignored at format 0 and refused by name at
  format 1, as git 2.39 does.

### Fixed
- **A junction is refused on every Python.** The work store's writer and the run-record reader asked
  `Path.is_junction` / `os.path.isjunction`, which exist only from 3.12, so on 3.10 and 3.11 a junction at the work
  store was written through. Both now read the link from `lstat`, as the rules and places readers do.
- **The package says its own version.** 1.2.3 was released with `version = "1.2.2"` in its metadata; 1.3.0 says
  1.3.0.

### Phase 1: claims that said more than was measured

Each change has a test that fails on 1.2.2.

#### Changed
- **A change's evidence is chosen by structure, not by name (git index).** Names lost to the next name: an audit
  found 34 of 35 new secret-shaped names digested and 16 of 32 honest names refused. Evidence is now a file a real
  repository's index lists as an ordinary file (`.git/HEAD` must name a ref or a commit), read from `.git/index` in
  pure Python (versions 2, 3 and 4, SHA-1 or SHA-256); untracked and ignored files are "unknown". The index is not a
  boundary: an agent can write it, so this chooses relevant files and is not a defence against an agent that breaks
  rules. A short name belt refuses a few listed names (`.env*`, `id_rsa*`, `*.pem`, `*.key`, `credentials*`,
  `token.*`, `*_token*`, `*-token*`, `*.token`, `wallet.*`, `wallet_*`, `wallet-*`). A home below its repository's top is read when that top is inside one of the named roots. The kind
  allowlist and the full secret-name list no longer decide; the full list stays in `sources/evidence.py`, off.
  Which files are evidence is now one small policy module (`evidence_gitindex.py`) behind `evidence.Policy`, so
  another way can be added without touching `change.py`; `fingerprint` and `freshness` take a policy, or a list of
  roots as before (`semantext.api.fingerprint`), which is read through the page's way. See docs/evidence-ways.md.
- **The gates' all-clear says what was read.** A worktree with a hook file for each act and an `.identity` line is
  now "a hook for each act, identity named (read; not tested)", never "gated, identity declared", and the holds line
  says every worktree "has a hook for each act and an .identity that names someone (read; not tested)": no hook is
  run, so none is known to refuse. The reader's notes say it deliberately differs from the hook checker on VACUOUS
  (only when at least one act is gated).
- **A hook git would not run is not counted.** On POSIX a hook file without the executable bit is ignored, as git
  ignores it, and listed under `not_executable`. On Windows there is no bit to read: every file counts, and each record
  says "executable bit not checked on Windows". Measured on Windows only; the POSIX branch is tested by setting the
  platform flag and the executable check by hand.
- **Every gates record carries the time it was read** (`read_at`, UTC), and so does the holds line ("Gates (read at
  ...)").
- **A change card's Brier score always comes with both counts:** n scored of m made, where m = scored + left out of
  its outcome + awaiting an outcome + unusable (no direction, a chance missing or outside 0 to 1, no name), so neither
  leaving a measure out nor writing one that cannot be scored improves a score. A coin's 0.25 stands beside it. The
  interval counts changes, not predictions (ten predictions on one change are one): from ten changes scored, a 95%
  Hoeffding bound on the mean score per change, which never has zero width; below ten, "too few to state an
  interval", with the number of changes beside it.
- **envcard says when an environment holds no rules** (`(no rules: this environment holds no entries)` under its
  header), rather than a bare header. `envcard.KNOWN_DIGEST_DIFFERENCES` names the two empty shapes on which the
  estate's digest.py knowingly differs, with why, for a parity check.
- **A rule written into a file by hand is marked, without growing the card per rule.** Semantext's card carries one
  line, "N rules are hand-written (no provenance)", for rules with none of the provenance Semantext writes; the page
  marks each and says "Hand-written" where it said "Came with Semantext". envcard counts rules with no provenance in
  one line per environment and marks each in the reference; the Rules drawer of ratified environments marks each.

#### Fixed
- **A file error no longer reaches the page as its own text.** The server answers a fixed message and an error id
  (the error's kind, such as `PermissionError/EACCES`), never `str(e)`, which carries a path.

#### Security
- SECURITY.md states the price of 1.2.2's two-day bound on history names: a clock that ran more than two days ahead and
  was corrected leaves `undo_last` restoring a future-named version for a while; a name up to two days ahead holds
  later names at that time, with the order kept.

#### Added
- **The registry and `semantext.api` 0.1** (the first step of the ecosystem). Sources, places and checkers are
  plug-ins by kind; the built-in readers and the page's places register as built-ins, and the page asks the registry
  instead of fixed tuples, with the same answers. Outside plug-ins come from installed packages' `semantext.plugins`
  entry points and load only once turned on: `semantext plugins enable <kind>.<name>`, typed at your console (a bar
  for an agent that follows the rules, and no more; SECURITY.md, Plug-ins). `semantext plugins` lists them;
  `semantext plugins check` says the kits are not built yet. The card hook loads none, and a test pins its imports.
- **`semantext.api.is_closed_place(path)`**, the one shared check of the folders the sources file lists under
  `"closed"`; it fails closed.
- **`semantext.api` 0.2**, from what the first outside plug-ins asked for: `Source.read(config, ctx)` with a
  `ReadContext` (0.1's `read(config)` still works); `named_roots`, `seat_rows`, `inside_roots`, `taken_names` and
  `closures_known`; list settings (texts, numbers, flat records) that reach a plug-in's read; documents served by row
  (`/api/v2/doc/<place>/<row_id>`, re-checked at serve time); closures that must be named (`"closed"` or a
  `"closures_file"`) before a plug-in reads anything or is turned on; a time budget and size caps on every call into
  a plug-in; and a v2 page policy with no `'unsafe-inline'`. The module's docstring and SECURITY.md state each limit.

#### Fixed (on the way to api 0.2)
- A path written with the `\\?\` prefix was judged open inside a closed folder.
- A plug-in's list setting never reached its read.
- A name two packages declared could never load; an attribute that raised took every page place down; SystemExit
  from a plug-in escaped; `semantext plugins` printed package names raw (escape sequences included).
- A run record whose own outcome is `failed` or `not proved` could be shown as guarded.

## [1.2.3] - 2026-10-23: runs on Linux and macOS (CI passed on every job)

1.2.2 passed every test on Windows, but CI failed 10 to 13 tests on each Linux and macOS job and 1 to 4 on each
Windows job. Two were the product; the rest were tests that took the machine they ran on for granted.

### Fixed
- **Outside Windows, a checker's `where` with a backslash or a colon is looked up as the local name it is.** The
  guard that never looks up a share, a device or a stream held back `hooks:x`, `\\host\share` and even `C:\hooks\x`
  on Linux and macOS, where those are ordinary names, so such a checker was wrongly reported as "a network or device
  path". On Windows, and under Python built for Cygwin or MSYS (whose `os.name` is "posix" though its paths reach
  Windows' shares), the rule is unchanged: it is chosen by `sys.platform`. Elsewhere only a path that starts with
  exactly two slashes is held back (POSIX leaves its meaning to the system, and some take it as a share).
- **JSON nested past the parser's depth gets the same answer on every machine, at every reader.** Whether 30,000
  levels overflow Python's parser depends on the interpreter's stack: on Windows they did, and on Linux and macOS
  under 3.14 they parse. So the register called such a line "not JSON" on one and "not an object" on the other; the
  seats file, the sources file and the reading-card hook crashed on Windows; the guards file was `bad-guards` on
  Windows and `bad-checker` on Linux; and a deep request to the page's server got no answer and printed a traceback.
  Every reader now goes through one loader (`semantext/jsonread.py`), which refuses a text nested more than 256
  levels deep before parsing it, and an overflow the same way. The register says `too-deep`; the server answers 400
  with "the request is nested too deeply to be read". Its depth count reads a string with no closing quote to the end
  of the text in one pass (before, the count began again at every later quote: one 64 KB line of `\"` took 20 s).

### Tests
- The missing-system-settings test no longer depends on the machine having no `/etc/gitconfig` (the packaged places
  are now a module constant the test moves into its own folder).
- The `%(prefix)/../..` include test makes its prefix folder: outside Windows `..` is taken on the disk, so a path
  climbing through a folder that is not there names no file, as it does for git.
- The rooted-include test runs from its temporary folder's drive (a Windows runner keeps its checkout on another
  drive than its temp folder).
- The file-open watchers also watch Python 3.10's pathlib, which kept its own reference to `io.open`; on 3.10 they saw
  no file opened at all.

## [1.2.2] - 2026-10-23

### Fixed
- **A name far in the future in a history folder no longer stops saving.** 1.2.1 never named a kept version below
  one already in its folder, so a file dated 9999 made every save fail, and one dated 2099 pinned every later name to
  2099. Names more than two days ahead of now are ignored; a name a day ahead (a clock east of UTC) still counts.

## [1.2.1] - 2026-10-23

### Fixed
- **A version kept before a clock change is never restored in place of a later one.** Kept versions and backups were
  named in local time, so after a restart with the clock an hour earlier (as when summer time ends) a later save could
  get an earlier name, and `undo_last` restored the wrong version. Names are now in UTC, and never sort below a name
  already in the folder, which also covers names written in local time before this change. Tests set the clock back
  across a restart; they fail on 1.2.0.

## [1.2.0] - 2026-10-23

A minor version after 1.1.0: the v2 page (slices 1b and 2), the reading card from a folder of ratified environments (envcard, envhook), and 1.1.0's one fix carried in. Every part was attacked by an independent auditor before release; the known limits are in SECURITY.md. Not yet run: CI on Linux and macOS (the 1.1.0 notes say the v2 preview had failed there), which needs a push.

### Fixed
- **1.1.0's stamp fix is carried in:** a backup or a kept version is never overwritten by the next one (`store.stamp`, `tests/test_stamp.py`), as in 1.1.0.

### Added
- **v2 slice 2: the proposed-change card, the Record as zoom, and how firmly each rule is held** (still read-only).
  A request line of kind `change` is a card on Waiting: what it changes, the hypothesis, the measures it should move
  (with a stated chance), the risk, why a smaller change would not do, the retroactive check, what changes (files
  added, removed and changed, and the change in always-on characters), whether its evidence is still today's (a
  SHA-256 digest of the files it names; "stale" once one moves), and its undo, shown as a commit or a file to restore
  and never performed. Later `outcome` lines are new entries (an undo too, never an erase), judged against the
  prediction, with a per-agent Brier score and its count. `diff_summary` and `fingerprint` are reworked from harness2
  and the fields and the scoring from rrsi, both Apache-2.0, with their notices kept and the changes marked. The
  Record zooms: threads by subject, then a thread's decisions (words whole up to 512 bytes), then one decision at its
  source (your words whole, the offer, where they were written down as the register pins them, what superseded them,
  and the scribe's reading labelled as an agent's); search reads your words, not the readings. A rule is **guarded**
  only when the sources file's new `guards` file names a checker for it with a must-pass and a must-refuse arm; a
  guard a card only mentions is shown as its claim and counts for nothing. The Rules drawer gives each rule's level
  with its source, and the share at each level.
- **v2 slice 1b: the cards lead, and the page reads what the inbox reads** (still read-only). On Waiting the
  heading, its sentence, the search and By project sit in the bar, so the first card is the first thing under it; the
  problems box gives way to a quiet count in the bar ("2 file problems") that opens the list on a click, and stays
  folded in the other places. A card's extras (who asks and acts, its project, your earlier words) open on a click,
  and the line says how many earlier words there are. A new **Documents** place lists every cv/<project> folder with
  a MASTER.md and reads it in the page: MASTER.md with a Copy button, the detailed documents beside it, and its
  diagrams through an `<img>` on their own light ground. Markdown is built from text, so HTML in a document shows
  as text; an https link opens in a new tab with `rel=noopener`, a relative .md link opens that document here, and
  anything else is plain text. The read (`GET /api/v2/document`, the page's header required) serves only a file the
  documents reader lists in a folder it lists, and refuses `..`, full paths, drive letters, links and anything else.
  Done shows each run's **Output** (stdout and stderr from runs.jsonl, as text). A **gaming indicator** in the bar
  reads the inbox's gaming.json as its gaming.py does ("Gaming hold until HH:MM", nothing when off, "Gaming state
  unknown" when it cannot be read); it never writes the flag and never runs gaming.py. The flag's file is the sources
  file's new `gaming` key, or gaming.json in the `inbox` folder.
- **v2 preview: one view of the records you already keep** (`/v2`, read-only). Five readers in `semantext/sources/`
  read the files a person who runs several agents already has, where they lie, and never write: each agent's requests
  (`cards`), the decision register (`record`), rule cards (`rules`), each repository's git gates by a static read of
  git's own files, worktree by worktree (`gates`), and the agents, projects, map and documents (`places`). Every line a
  reader cannot use is listed as a problem, never dropped. The page has four places on one bar: Waiting (the home,
  card for card), Projects, the map and Record, with drawers for an agent, its rules, a gate and documents.
  `semantext statusline` gives Claude Code's status bar one line. Each reader was checked against the tool that owns
  its data on real files, attacked by an independent reviewer, and shown to catch planted faults; a gate's state is
  only ever a read, never "armed".
- **Answer from chat.** Send a request's number and your choice to any of your AIs, as a message of its own: `#12 2`,
  `#12 2, but after the tests` (words follow one of `. , ; :`), `#12: your own words` (for a question with no
  options), `#13 done`, `#14 add`. The hook records it as your answer, the way the page and the terminal record theirs
  (a proposed rule you add is added), and tells the AI what was recorded, or that nothing was, and why. It takes one
  only from a message that opens as your own words, that the tool's own record says you typed, and that is that one
  answer and nothing else: pasted notes or a list that mentions requests answers nothing.
- **Corrections kept as tests.** When you teach a rule, you can keep the message your AI got wrong beside it, as the
  rule's test: `semantext teach "..." --misread "..."`, the correction box on Today, or "Not read the way you meant?"
  under Try a message. Each test is re-checked whenever your rules change: it is covered while every rule it needs is
  on, and switching such a rule off says which correction it uncovers (never blocked). `semantext cases` lists them,
  `--export` writes them in the back-test's case form, the card says how many there are, the constellation rings
  their rules, and Today counts them.
- **The register.** Everything you decided stays on record, with your words: `semantext decisions [WORDS]`, the MCP
  `decisions` tool, and the page's On record list, with a search. When an agent asks a question you answered before,
  the earlier answer is shown beside it, to you and to the agent, and never used for it.
- **What Semantext noticed.** The feed's line now keeps, for your own words only, what Semantext's quick reading noticed,
  by kind alone: a question, a maybe, an ask that needs your word, an answer, and the rest. Older lines are read as
  noticing nothing.
- **Counts of what it did,** from its own records only: your messages that carried your rules; the questions, maybes
  and risky asks it saw, and whether the rule for each went with it; messages from other agents and tools marked as not
  yours, and those claiming to be you; decisions answered, how fast, and how; the rules you added.
- **DESIGN.md:** the page's design, in Google's DESIGN.md format for design tools and agents. Its colours, type,
  shapes and components come from the page's own code, and the copy comes from the page and the README.

### Changed
- **The page, in four places,** each answering one question, and Settings. It is quiet by design: neutral greys, one
  accent (gold) for what is yours or needs you, red only for what is broken, a few groups per screen set apart by
  space, and explanations that open only when asked for. It follows the system's light or dark setting. DESIGN.md
  gives the rules and the design research behind them.
  - **Today:** is it working, and does anything need me? One sentence of status, the decisions waiting (one click, or
    typed in chat), three counts of what it did with the rest one click away, and the latest messages, each opening to
    the five steps behind it.
  - **Rules:** your rules as a constellation that shows their structure: the centre applies everywhere, each ring out
    applies more narrowly (an environment, then one agent), and your own words are gold, joined in the order you added
    them. Below it the same rules as lists, each with its switch. Try a message lives here.
  - **Agents:** every agent in a list, the map of them at work once there are two agents or two environments, and What
    an agent gets.
  - **Decisions:** what waits for you, and everything you decided, on record.
  - Calm by default: nothing replays and no example plays; the constellation moves only when a real message arrives.
    The old addresses (`#live`, `#inbox`) still work.
- The inbox notes on every card say the user can answer by sending `#<number>` and their choice as a message of its
  own.

### Security
- An answer that looks like it holds a key, a token or a password of a known shape is now refused from anywhere;
  before, only a request was checked. A long run shaped like an unlisted key is kept but withheld from everything sent
  to an agent, as the feed withholds it.
- The counts and the register are given only to the page's own script, like the feed.

## [1.1.0] - 2026-10-14

### Fixed
- **A backup or a kept version is never overwritten by the next one.** Files named by the time could be given the same
  name twice on a clock that repeats a microsecond (seen on Windows with Python 3.10), so the second overwrote the
  first. Every such name now comes from one stamp that never repeats in a process and keeps the order the files were
  made; tests freeze the clock to prove it.

### Added
- **Answer from chat.** Send a request's number and your choice to any of your AIs, as a message of its own: `#12 2`,
  `#12 2, but after the tests` (words follow one of `. , ; :`), `#12: your own words` (for a question with no
  options), `#13 done`, `#14 add`. The hook records it as your answer, the way the page and the terminal record theirs
  (a proposed rule you add is added), and tells the AI what was recorded, or that nothing was, and why. It takes one
  only from a message that opens as your own words, that the tool's own record says you typed, and that is that one
  answer and nothing else: pasted notes or a list that mentions requests answers nothing.
- **Corrections kept as tests.** When you teach a rule, you can keep the message your AI got wrong beside it, as the
  rule's test: `semantext teach "..." --misread "..."`, the correction box on Today, or "Not read the way you meant?"
  under Try a message. Each test is re-checked whenever your rules change: it is covered while every rule it needs is
  on, and switching such a rule off says which correction it uncovers (never blocked). `semantext cases` lists them,
  `--export` writes them in the back-test's case form, the card says how many there are, the constellation rings
  their rules, and Today counts them.
- **The register.** Everything you decided stays on record, with your words: `semantext decisions [WORDS]`, the MCP
  `decisions` tool, and the page's On record list, with a search. When an agent asks a question you answered before,
  the earlier answer is shown beside it, to you and to the agent, and never used for it.
- **What Semantext noticed.** The feed's line now keeps, for your own words only, what Semantext's quick reading noticed,
  by kind alone: a question, a maybe, an ask that needs your word, an answer, and the rest. Older lines are read as
  noticing nothing.
- **Counts of what it did,** from its own records only: your messages that carried your rules; the questions, maybes
  and risky asks it saw, and whether the rule for each went with it; messages from other agents and tools marked as not
  yours, and those claiming to be you; decisions answered, how fast, and how; the rules you added.
- **DESIGN.md:** the page's design, in Google's DESIGN.md format for design tools and agents. Its colours, type,
  shapes and components come from the page's own code, and the copy comes from the page and the README.

### Changed
- **The page, in four places,** each answering one question, and Settings. It is quiet by design: neutral greys, one
  accent (gold) for what is yours or needs you, red only for what is broken, a few groups per screen set apart by
  space, and explanations that open only when asked for. It follows the system's light or dark setting. DESIGN.md
  gives the rules and the design research behind them.
  - **Today:** is it working, and does anything need me? One sentence of status, the decisions waiting (one click, or
    typed in chat), three counts of what it did with the rest one click away, and the latest messages, each opening to
    the five steps behind it.
  - **Rules:** your rules as a constellation that shows their structure: the centre applies everywhere, each ring out
    applies more narrowly (an environment, then one agent), and your own words are gold, joined in the order you added
    them. Below it the same rules as lists, each with its switch. Try a message lives here.
  - **Agents:** every agent in a list, the map of them at work once there are two agents or two environments, and What
    an agent gets.
  - **Decisions:** what waits for you, and everything you decided, on record.
  - Calm by default: nothing replays and no example plays; the constellation moves only when a real message arrives.
    The old addresses (`#live`, `#inbox`) still work.
- The inbox notes on every card say the user can answer by sending `#<number>` and their choice as a message of its
  own.

### Security
- An answer that looks like it holds a key, a token or a password of a known shape is now refused from anywhere;
  before, only a request was checked. A long run shaped like an unlisted key is kept but withheld from everything sent
  to an agent, as the feed withholds it.
- The counts and the register are given only to the page's own script, like the feed.

## [1.0.0] - 2026-10-13

### Added
- The page, rebuilt around what Semantext does, one view each for:
  - **Live:** your agents at work, drawn as a space.
    - Each environment is a zone, and zones overlap as sets do.
    - Each agent sits in the zones it works in, carrying its card as a ring: base, environment, its own. A name it
      only claims is drawn dashed.
    - Lines show what passes: your words; another agent's relayed words, dashed, as information and never your voice;
      a tool's notices; an agent asking you; and your answers, the only lines that change anything.
    - Point at anything to read it. Select an agent for its card, or to test a message to it.
    Under the space, the five steps every prompt passes through (who asked, whose words, which card, its layers, what
    was sent), which move the space as they step. Below that, a feed with one column per dimension. When nothing new
    is happening, recent activity is replayed, marked as such, or marked examples play when there is none.
  - **Layers:** the card built base, then environment, then agent, for any agent and for your own or relayed words,
    beside the exact text it receives.
  - **Agents:** each environment drawn as a set inside the shared base, with the agents that work in it. An agent in
    more than one set works across them; several in one share its rules, each with a layer of its own. The same in
    numbers, and naming, binding and teaching each agent.
  - **Rules:** every rule with when it applies and where it came from, layer by layer; add one in your own words, for
    every agent or one.
  - **Test:** the same five steps for words you type, what their cue words point to, and the card they would get.
    Nothing is saved.
  - **Inbox:** decision cards, the switch that tells your agents to ask there, and each answer's way back to the agent
    that asked.
  - **Settings:** one panel.
  Each view has its own address, so Back works.
- The feed: one line for each card the hook hands out. It records:
  - who asked, and how Semantext knew;
  - whose words (yours, another agent's, a tool's), and what told;
  - for another agent's message, the name its opening tag gives the sender. This is a claim, and it is dropped when it
    looks like a key;
  - the environment and the card's form;
  - its rules, layer by layer, its size, and any the size limit left out;
  - the inbox answers and requests that went with it.
  Never what was said: no prompt's text is kept, and a value shaped like a key is withheld. Only the newest lines are
  kept (it is cut back past 512 kB). `semantext feed` shows it; `semantext feed off`, or Settings on the page, writes
  nothing at all.
- The inbox. An AI files a request with `semantext ask`: a decision (the question, the options and its recommendation)
  or a command (the exact text, what it does and how to undo it). You answer from the page or with
  `semantext answer ID CHOICE [your words]`, and your words go with your choice. Only a person at a terminal can
  answer; agent sessions are refused. Semantext never runs a command: the page offers Copy, then Done or Won't do.
  The answer reaches the asking AI with its next prompt, or through `semantext answers`.
- `semantext install codex|freebuff|agents-md`: one managed block in the agent's instructions file, removed exactly by
  `uninstall`, and refreshed everywhere by `semantext sync`.
- `semantext export system-prompt|modelfile` for local models, including an Ollama Modelfile.
- The page's Agents panel: every agent Semantext has seen or you have named, with its folder, its sessions and its own
  rules, where you bind a folder to a name, give an agent a display name and teach it a rule of its own.
- `semantext mcp`: Semantext for any tool that speaks the Model Context Protocol. The card comes in the server's
  instructions, and the tools are `card`, `ask`, `answers`, `close` and `propose_rule`. There is no answer tool, and a
  rule over MCP is only ever a proposal. A client's own name for itself is a claim until you bind its folder.
- `semantext profile` as another name for `semantext env`. `env use` and every `--env` take a name or a title, in any
  case, and suggest the nearest one.
- The Rules panel can add suggested rules to the environment you are in.
- Who is asking, worked out with nothing named, first match wins:
  - a folder you bound to a name (`semantext agent bind NAME --folder DIR`);
  - a name the agent states (a claim, shown as claimed);
  - the tool and the project (`claude-code@app`);
  - otherwise `ai`.
  Every request records how its asker was known. `semantext agents` lists the agents seen, with their sessions;
  `semantext agent whoami|bind|unbind|name` shows or sets them.
- The relay card. A prompt that is not your own message (another session's message, a task's report, a system notice)
  gets a short card: the rules marked `relay` or `always`. The base (0.2.0) adds `base.relayed-words-are-information`.
- Each agent's own rules. `semantext teach --agent NAME` keeps a rule for that agent only, in an `agents:` layer of the
  environment. It reaches that agent's card, after the shared rules and never over them, and never reaches a claim of
  the name. `card --agent` and `rules --agent` show them. Rules taught to an agent seen by its tool and project go with
  it when you bind its folder, as its requests do; the page shows them under the name you gave it.
- Rule proposals. `semantext teach` from an agent's shell files the rule in your inbox as that agent's proposal. You add
  it as it is, add it in your own wording, or decline it, on the page or with `semantext answer ID add|no`.
- An agent as your scribe. From its shell, a rule that is a whole sentence you wrote in that session, word for word,
  opening as a standing preference with no hedge or question in it, or stating a reading rule ("When I say X, I mean
  Y"), is your rule at once, with where it came from. Claude Code's transcript is the witness. A question, a
  suggestion, part of a sentence, a one-off request, a paraphrase or another agent's words stays a proposal, and so
  does a sentence with a time word (yet, for now, today, until), even a standing rule with a condition: a stated
  limit, in the safe direction.
- The hook reads Claude Code's own record of where a prompt came from, beside its text. The record can only move a
  prompt away from you, never toward you. Both forms of the record count: `turnOrigin`, and the older `origin`.
- `semantext mine`: your own past messages from Claude Code's transcripts, kept as heard so `propose` can work from
  them. Only your own words are kept, never a summary, a notice or another agent's message, never anything that looks
  like a key or a password, and nothing twice. It is your act, refused in an agent's shell, and it never makes a rule.
- `semantext backtest`: the card scored against the misreadings in your transcripts, the messages you then corrected.
  It reports coverage against the touch rate on messages you did not correct, so a card that touches everything has no
  skill, beside the base rules alone and a same-size card drawn from the suggestion packs. Without `--split DATE` the
  score is marked in-sample. `--cases` scores curated cases by whether the right rule fired, and `--finder` measures how
  well corrections are found. No model is called and nothing is written. See docs/backtest.md.
- `semantext backtest --weighed`: each cue weighed by its evidence on your earlier messages, under a conformal ceiling
  on the share of ordinary messages touched (`--alpha`, 10% by default), scored on later messages beside the plain
  touch, with a GO, UNDERPOWERED or KILL verdict. Counts only; nothing is written.
- `semantext backtest --reader`: an optional model reading, scored in the same harness. Off unless you name a reader
  (a model on this machine through Ollama, or an OpenAI-compatible endpoint, announced before its first call when it
  is outside this machine; its key is read from a variable you name and never stored). A reader sees only the card,
  the message and the reply before it, never a secret; only rule ids and one line are taken from its answer. Card
  against blind in independent calls, two judges of other model families, McNemar's exact test, an ablation per rule,
  and the power of the test stated. A model's reading is a measurement, never a rule. A local model reads with one
  fixed decoding (temperature 0, a context of 8,192 tokens, its thinking off), recorded in the report with its digest
  as its version; a reply that reaches the context limit stops the run. `--clean-sample N` reads every misread message
  and a fixed sample of N clean ones, and the report gives the sizes of the card and of its null.

### Changed
- Testing a message on the page writes nothing: it no longer files the acts it flags as pending decisions.
- `doctor` reports the feed.
- Only you change your rules. In an agent's shell, or anywhere without a console, these are refused: toggle, pin,
  undo, feature, `env use|new|add`, config, hear, forget and `propose --accept`.
- The hook keeps only your own prompts as heard words, never another agent's or a tool's.
- A refusal names no variable to clear, and no way round it.
- A second environment with a title already in use is numbered: Cooking, then Cooking 2.
- `semantext answers` reads and marks only its own asker's answers ("ai" when an agent gives no name), and the hook
  shows each agent only its own.
- The hook's inbox notes keep to their own byte budget: whole answers only, the rest counted, so the card keeps its
  room.

### Fixed
- `semantext sync` reports a connected file it cannot refresh safely (two blocks, broken markers) as a problem, leaves
  it untouched and exits 1, as `doctor` does.
- "Did you mean" suggests only a near miss of a name or title.
- The source distribution ships `tests/conftest.py`, the docs and the examples, so its own tests run from it.
- The page's server drains a refused request's body before answering, so the client always reads the refusal.
- Agents starting at once no longer fail on Windows. Every change to `agents.json` and `sessions.json` is made under a
  lock, through a temporary file of the writer's own, and is never written over a file that could not be read. A
  plain shell writes nothing.
- A home folder kept in git is no longer one project for every folder under it.
- A rule file broken by a hand edit no longer takes the card away: the AI still gets the base rules, with one line
  naming the file and the problem. `card` refuses naming the file and the rule (for YAML, the line and the column),
  `doctor` lists every file it cannot read and carries on, and the page shows the problem instead of going blank.
- An empty or damaged `state.json` falls back to the defaults and is kept before it is replaced; it is written through
  a temporary file. A folder copied into `profiles/` is skipped and named by `doctor`.
- `undo --last` says which rules it takes off, and where the version it replaced is kept.
- `teach` from a shell that is neither a console nor an agent's is refused, instead of filing your own words as an
  AI's proposal.
- Windows: a settings file saved with a byte-order mark is read; `semantext.exe hook`, a quoted path or `--home` is
  known as Semantext's hook, so it is never added twice; backups made in the same second no longer overwrite each
  other; a hook installed from another home names that home.

### Security
- A relayed message whose opening tag names the person as its sender ("user", "system", this machine's account name)
  stays another agent's words, with the short card: whose words a prompt carries is never decided by the name it gives.
  The page flags it: "claims to be you".
- A name shaped like a key is never taken as an agent's name: not a name a shell states in `SEMANTEXT_AGENT`, not an
  MCP client's own name, and `--from` refuses one. The name is checked as given, before it is cleaned, since cleaning
  reshapes the very marks a key is known by ("my password is ..." would become "my-password-is-..."). The inbox checks
  the sender's name too.
- Only the page itself reads the feed. The server answers it only to a request carrying the page's own header, which
  another site can send only after a preflight this server never grants, and it refuses a browser that names any
  other site. The feed is never served as a file.
- The inbox matches a request on its asker's key and session, not on the name. A stated name (`--from`,
  `$SEMANTEXT_AGENT`) never reads, marks or withdraws another agent's requests. A claimed request's answer never shows
  in another agent's card.
- An answer reaches the agent that asked, even if you bind its folder after it asked.
- A shell takes its session's identity only when its own facts agree: the same tool, inside that project.
- The relay card keeps the rule that an act waits for your word, whatever the marks say.
- In an agent's shell, `uninstall --apply` and `install` with a hook command other than the standard one are refused.
- Every change through the page needs the page's own `Origin`, as answers already did. A request with none is a local
  program, not the page, and could otherwise change the rules an agent's shell may not.
- Who answers is checked where answers are recorded, and the page takes an answer only from its own page.
- An answer that did not come from you is labelled "not from the user" wherever it shows.
- Only a request's asker, or you at your own terminal, can withdraw it.
- Every field of a request is checked for keys and tokens. A command is kept exactly as written, control characters
  refused. Ids are never reused, even after a hand edit.
- The FAQ now says that every change rewrites the rule file from its data, so comments are not kept in the live file;
  the copy in `history/` keeps them.
- The key filter knows more shapes: JSON web tokens, Stripe, npm, GitLab and Google OAuth tokens, webhook secrets,
  `user:password@` in a URL, and a password said in prose. On the way off the machine, any long run of mixed letters
  and digits counts as a key too, and a card holding one is never sent.
- Everything a judge is given is checked for keys, not only the message: a hit calls no judge, and is counted.
- One key goes to one host: each endpoint can name its own key variable, one `--key-env` for two hosts is refused, and
  a key never goes over plain http to another machine. The notice before a cloud call says what that endpoint
  receives.
- Judges are compared with the reader by lineage, not by name: qwen2.5 and qwen3.6 are one.
- `backtest --show` holds back a text that looks like it holds a key, and counts it.

## [0.1.0] - 2026-10-13

### Added
- Environments as plain YAML rule files you own, with a shared base, a Default to start from, and new environments
  made from suggestion packs (work, home, game, research).
- Teaching: a correction becomes a rule with your exact words kept beside it; rules can be switched off, pinned as
  stationary or adaptive, and undone.
- Undo that never deletes: every write keeps the previous version, an undone rule is archived in its file, and
  `undo --last` walks back one change at a time.
- The card: a compact text of your active rules for your AI, kept under the hook size limit without cutting a rule.
- A Claude Code hook (`semantext hook`) and `semantext install claude-code`, which prints the change and makes it
  only with `--apply`, after a backup.
- Hearing and proposals: messages you choose to keep (or prompts, if you switch `hear-prompts` on) stay on your
  machine, and rule-shaped sentences among them are proposed as rules for you to accept.
- A local page (`semantext serve`) with the deck and the systems view, served on this machine only, and a CLI over the
  same store.
- A pytest suite, run in CI on Linux, Windows and macOS for Python 3.10 to 3.14.
