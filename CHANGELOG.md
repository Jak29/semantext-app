# Changelog

All notable changes to Semantext are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.5.0] - 2026-10-31

The first step to a standalone app: more of the page works from a clean install, with nothing set up. Your rules, your own inbox and your work show on the v2 page, and a compute monitor says whether this machine is free for heavy work. Everything an estate's files gave still works when they are named.

### Added
- **The compute monitor**, read and never changed: `semantext compute` for a job about to start (exit 0 free, 2 could not tell, 3 hold or light work only), and a word in the page's bar. It sees a program in the common game stores' folders (Steam, Epic, GOG, Riot, Xbox, Battle.net, Ubisoft, EA, Lutris; the Epic, Battle.net and Riot launchers themselves are not games) or in folders you name under `"game_folders"`, a full-screen program on Windows, a busy processor and short memory (Windows and Linux). Only "free" means go; a sign it cannot read, or a setting it cannot use, is never a clear one, and it says what it did not read. The GPU is not read; on macOS only the switch below is.
- **An I'm gaming switch**: `semantext compute hold [--hours N]` and `release`, a flag in your home that lapses by itself within six hours. A flag your settings place elsewhere belongs to whatever writes it, and is refused.
- **`semantext work project NAME`**: name your own projects, so work can be filed with no seats file.
- A test of the whole product as a stranger, with nothing set up (`tests/test_a_stranger.py`).

### Changed
- **The v2 page's Rules** reads the environments in your home when no `"cards"` setting names others.
- **The v2 page's Waiting** reads your own inbox when neither `"seats"` nor `"inbox"` is set: agents' requests as cards, answered from the card through the same guarded route as the home page. That is the page's one write outside the Plug-ins tab. A sources file that `SEMANTEXT_SOURCES` names and that is not there is said as a problem, and is never read as no setup.
- **Links into an inbox app (`jak-inbox://`) appear only with `"inbox_app": true`** in your sources file, including the Work item's link, which used to show for everyone. Anyone who uses that app needs to add the line.

### Fixed
- A clean install reported its own default environment as pinning an old base (`base@0.1.0`, with base at 0.2.0). A new environment now pins the base in your home. A home made before this keeps its pin, and the page keeps saying so.
- `/api/answer` took the JSON value `true` as request number 1.
- A line of your inbox file holding a number too long to read stopped the whole inbox, and with it the card your AI receives. It is now a damaged line, skipped like any other.

## [1.4.0] - 2026-10-30

Closes by name as well as by path, a Plug-ins tab on which the page proposes and the console applies, a fair store lock, one rule for reading a seat's folder, and a written security floor. Outside plug-ins read nothing until your closed places are named in full, and none loads until you turn it on at your console.

### Added
- **The plug-in API, written down** (`docs/plugin-api.md`): the 0.2 contract, from the code. And the run-record
  format a checker writes (`docs/run-record-schema.md`). The code cited both under names that were never in the
  repository; a test now fails if the package cites a `docs/` page that is not there.
- **The security floor** (`docs/security-floor.md`): every refusal Semantext promises, with the tests that hold it. A
  test fails if any test it names is renamed or deleted.
- A test that holds the trailing `Z` on every Python: the 1.3.0 fix had none that could fail on 3.11 or later.
- **Closures by name.** A `"closed_names"` list, in the sources file or in the closures file (under
  `"closures_names_key"`, `"closed_names"` when not given), closes a folder or file by its name in any folder, beside
  the closed paths, in the closures-file format (schema `estate.closures/0`): entries with an
  `id`, a `form` and that form's fields (`segment`, `segment-pair`, `segment-prefix-except`,
  `segment-or-dotted-prefix`, `substring`, `suffix`). Matching follows the file's own rules: a search over the whole
  path string, so a substring matches anywhere; case-insensitive as Python's IGNORECASE takes it or wider; both
  separators; a single trailing newline as an end; the path as given, written in full and with links resolved. A path
  is closed when any of four legs closes it: the field matcher on the path as given (not normalised), composed (NFC)
  and decomposed (NFD), and the entry's own `regex` (at most 2,000 characters): so it closes more than the regex, never
  less, by construction. It also reads a path as Windows does (stream suffix, trailing dots and spaces), closing only
  more. Where an entry's fields and regex disagree on its own examples, the page says so. `is_closed_place`, the
  built-in readers' check and the card readers apply names wherever they apply paths. **Closed names add closures;
  they never by themselves make the closures known:** for a plug-in and the strict view, known needs what 1.3.0
  needed (a `"closed"` list, or a closures file read by its rules), and names then close more. A sources file with
  `"closed_names"` and neither is none named for a plug-in, as in 1.3.0 (every path closed, `semantext plugins enable`
  refuses), and its names close what they name for the built-in readers and the strict view. In a sources file shaped
  like the closures-file format (its schema or its keys, and no closures file), `"closed_names"` is one of the format's
  keys there: said, not read. `ReadContext` gains `names` (empty by default, so a context made by hand without it closes no name). It
  fails closed as the paths do: an entry without an id (or one given twice), with an unknown form, a missing field or
  a field it does not have; a literal that is empty or dot-only, starts or ends with white space, holds a control,
  format or separator character (an inner ASCII space aside), is only combining marks, or holds a separator, a `:` or
  a glob character (refused so one list means the same on every system and no entry is read as a pattern); a list
  given as null (`"closed_paths": null`: not supplied yet), whichever key is read; another version of the format's `schema` (another tool's is read by 1.3.0's rule); names in a
  closures file that says no schema; a key a schema file's schema does not have; or a `matching` version this code
  does not know: each makes the closures unknown, and every path closed, with a reason naming the entry and field. A
  closures file must still hold its paths key, as in 1.3.0; its names key is needed when `"closures_names_key"` names
  it. A `ReadContext` built by hand with names that are not `Name`s is refused
  (TypeError). See SECURITY.md, "Closed names".
- **A complete list for plug-ins, a lower bound for the readers.** A closures file with a schema is known to a plug-in
  only when the list under the key `closures_key` names (`closed` when not given) is a list, `closed_paths_complete` is exactly true and every `known_closed_paths` entry is
  in it; otherwise every path is closed to a plug-in, with the reason said. The built-in readers read
  `known_closed_paths` beside every name, by component, as given and through links, and the page says the list is
  incomplete. The Places reader refuses a named root that is, or holds, a closed path (each listed path and the root
  compared as given and with links resolved, so a junction or 8.3 spelling of either is caught). Two-separator forms
  are closed while any closure exists, on every system, `\\.\C:\` (a device path) included, as in 1.3.0; only
  `\\?\C:\` is read as the drive, as 1.3.0 read it. The closures-file format is read only in a closures file the
  sources file names, and only when it says the format's schema; a path record (`{"path": ...}`) is read only there.
  The sources file keeps 1.3.0's closures rules (with `closed_names` beside them), and the format's keys written in it
  mean nothing there and are said, when no `closures_file` is named ("this looks like a closures file (...); those keys are not read in your sources file, so nothing is closed by them. Point closures_file at it to use it"), never
  closing anything. **Nothing 1.3.0 read changes meaning, with one deliberate exception: a closures file in the
  closures-file format (schema `estate.closures/0`), new in 1.4, is read by that format's rules. Where its complete
  list is not supplied, it is read by the built-in card readers and the root rule as a lower bound (its known paths and
  names), and stays unknown to plug-ins and the strict view; and its path records are read as its paths, where 1.3.0
  found them unreadable. Every other change closes more** (listed under Changed). A test holds twenty-one 1.3.0-shaped
  sources files to the closures 1.3.0 gave, and judges a fixed set of paths (on Windows also written with `\\?\` and
  `\\.\`) in the plug-in, built-in and strict views as 1.3.0 judges them; it asserts the exception case by case, and
  that each closes-more file closes every path 1.3.0 closed. It runs against the 1.3.0 tree itself (CI fetches the
  whole history for it).
- **Closures are said aloud** on the page as "closures" problems: closures that cannot be used (also in the refusal
  of `semantext plugins enable`, and from `closed.why_unknown()`); a closed name that closes nearly every path (a
  substring, suffix or prefix under 3 characters), kept as the person's choice; and a list shaped like closures under
  a key of the sources file no reader reads, which closes nothing. The Plug-ins tab, its rows, `semantext plugins
  enable` and Work say the true state (`closed.closures_state`): none named, named and incomplete, or named and
  unreadable, with the reason and what fixes it.
- **A strict view of the closures for the run-record reader** (`closed.strict_closures`): with no closures named,
  nothing is closed, as for every built-in reader; named and incomplete, or unknown, every path is, as for a plug-in,
  since a run record's subject is shown. SECURITY.md says which reader uses which of the three views, and why.
- **A Plug-ins place on the v2 page** (`/api/v2/plugins`, `plugins.js`): every plug-in, built in or installed, with
  its package and version, its trust state (installed, not on; on; on, not loaded; turned on, not installed; turned
  on, but its name is no longer allowed), its health, what it declares it reads, and its settings with their values.
  Drawing it calls no plug-in and never loads the entry point of one that is off.
- **A package declares its settings and what it reads as data**, in `semantext-plugin.json` beside the module its
  entry point names (`semantext/manifest.py`): each setting a key of the sources file, typed `text`, `path`, `paths`
  or `list`, with an optional `default`, `required` and `widens`. A declaration not of the shape, or taking a key of
  Semantext's own or of the closures (in any case), is refused whole.
- **The page proposes; the console applies** (the owner's choice). The page turns a plug-in off (never held to the
  page's rate limit), and never turns one on (it shows `semantext plugins enable <kind>.<name>`). It never writes a
  plug-in's settings: a change from the settings form, and a rollback of one, is kept as a proposal, labelled
  `widens`, `narrows` or `unknown`, or `order changed` (never `narrows`) from the declarations for you to read (the
  label decides nothing), answered 202 Accepted, and applied by **`semantext plugins confirm <n>`** at your own
  console. **What confirm applies is shown exactly, or it refuses:** entries added at the end, or only taken out, as
  such; any other list change (an order changed above all), and a list set for the first time, as the whole list
  before and after, one numbered entry a line; every other value whole; entries compared as written (`1`, `1.0` and
  `true` differ). Every line `semantext plugins` prints goes through one renderer: printable ASCII alone and one to
  one, every other character as its escape and the backslash as `\\`, nothing deleted, collapsed or cut. A review over
  60 rows at the console's width (its header counted) is read with **`semantext plugins show <n> --full`**, which ends
  with a review code, and applied with `confirm <n> --reviewed-full <code>`. A proposal is applied only on exactly the
  sources file it was made on (its sha256 and its path) with no change recorded to its keys since; it expires after an
  hour; a newer one for the same setting supersedes it, and a superseded proposal is never applied in place of another
  (both are named; the newer is confirmed by its own number). Open proposals are kept by number in
  `plugin-proposals.json`, so one is found however many records follow it. No proposal is made on a sources file that
  is also the closures file, and no record, rollback or proposal writes a reserved key (the key `closures_key` names
  included, in any case); a plug-in whose `keys` or `needs` name one is never loaded. A proposal number is ASCII digits
  alone.
- **The console is the point of review:** `semantext plugins enable` shows, before you type the name, every setting
  the plug-in declares (with its value now, or its declared default when not set), every other key of the sources file
  it may read without declaring it, the keys Semantext keeps for itself, and every settings change recorded since it
  was last turned off, with who and when, all of it exactly and uncut in printable ASCII (over 60 rows, read with
  `semantext plugins show <kind>.<name> --full` and its code given to `enable --reviewed-full`). The review is
  snapshotted (the sources file, the declaration, the package's version, and the last change to the plug-in and to
  each key it will be given), and the plug-in is turned on only if the snapshot still holds after the yes; a page
  turning another plug-in off, or proposing, never refuses it.
- **A change log**, `<home>/plugin-changes.jsonl`, appended to and never rewritten, never through a link or a second
  hard link, with the console's enable and disable too, every writer under one lock (`plugins.lock`). Each record is
  written, then the last change to its key or plug-in in `plugin-last-changes.json` (never rotated; refused if it is
  not one plain file with one name, or unreadable; never reset), and only then the change. A record whose file does
  not now hold its "after", with no later record to explain it, is shown "not applied". Bounded: 64 KB a record, 30
  proposals and settings rollbacks a minute, rotated once at 4 MB (the rotated file is dropped at the next rotation),
  and only its last 512 KB is read. Numbers never start again: a log moved aside goes on from the highest number known,
  and a number that does not go up is said as a problem.
- The line to type holds no free text: a plug-in's name is a plain word, and `--home` is shown only for a home of
  letters, digits, spaces and `\ / : . _ -` (quoted for a POSIX shell whenever it holds a backslash or a space), else
  left out with a note to type it where `SEMANTEXT_HOME` is set; lines are for PowerShell on Windows and a POSIX shell
  elsewhere, never cmd.exe.
- A plug-in's name is letters, digits, `_` and `-`; an entry point named otherwise is a problem, never listed or
  loaded. One left on from before under such a name says so, and the page offers no Off it would refuse.
- Path settings refuse `.` and `..` parts, parts ending in a dot or a space, device names (in the path rule's shape, `con .txt` too), `:` past a drive letter,
  and verbatim prefixes written with any mix of slashes; a text holding a lone surrogate, or a control, format or bidi
  character or a line or paragraph separator, is refused. An error in a POST that no one wrote for the page is a fixed answer with its kind
  (400 or 500), never its words and never a dropped connection.
- **Health:** the kernel keeps how each plug-in's last call ended (answered, raised, late, busy, crowded), its own
  work apart from the calls that load it.

### Changed
- **The inbox joins a seat's home the way the places and gates readers do.** A home written as a full path, even one
  inside the base folder, is now a problem in the inbox too. The three readers and the card hook (which gives a
  session its seat) judge the base and read a home or a root by one rule (`semantext/pathrule.py`), exactly as
  written, on every system: one that holds a control character, has a space before or after it, has a part ending in
  a dot or a space, holds a colon past a drive letter, is written with the `\\?\` prefix, or has a part that is a
  device name (CON, NUL, COM1, `con .txt`, ...: refused on every system because many Windows versions read them as
  devices; recent Windows 11 does not) is refused; `~name` and a `..` step are refused in a base; and with no base,
  or one that is not an existing folder, no home is read by any of them. The seats file itself is parsed one way by
  all four, as the person's inbox parses it, with no key given twice. Before, the inbox read `" birch"` as a folder
  whose name starts with a space, the gates reader trimmed it, only the places reader refused control characters, the base was read three ways, the hook joined homes its own
  way (a `..` home gave a session that seat), and a missing base read no homes in the inbox but every full-path home
  in the others. `docs/plugin-api.md` lists what the rule refuses and what it does not. `semantext.api.seat_rows` and
  `named_roots` follow it.
- A closures file that says the closures-file format's schema and holds, under a key that is not one of the keys read, a list shaped like closures (all full paths,
  or all name records), such as `"closed_paths"` beside `"closed"`, now makes the closures unknown, so every path is
  closed; before, the list was passed over in silence. A closures file without that schema keeps 1.3.0's rule
  (`{"closed": [], "closed_paths": ["..."]}` is known). Prose, texts and other records beside the lists are left alone.
- A plug-in may no longer declare a closures key (`"closed"`, `"closed_names"`, `"closures_file"`, `"closures_key"`,
  `"closures_names_key"`, and the closures-file format's `"schema"`, `"closed_paths"`, `"closed_paths_complete"`,
  `"known_closed_paths"`, `"known_open_paths_near"`), compared by Unicode case folding, as its own: such a plug-in is
  not added. Before, one declaring `"closed"` was handed the list as a setting.
- The run-record reader (and the Work runs reader through it) reads with the strict view: while the closures are
  unknown, or are a closures file in the closures-file format not marked complete (`closed_paths_complete` not true,
  or `closed_paths` null), every path is closed to it, so it reads no run folder and no subject; 1.3.0 read a schema
  file's list as complete. With no closures named, or closures that are known, it reads as in 1.3.0.
- **These files now close more than in 1.3.0 (never less):** a sources file with `"closed_names"` and no `"closed"`
  list or closures file (still none named for a plug-in, as in 1.3.0; its names now close what they name for the
  built-in readers and the strict view, which 1.3.0 left open); `"closed_names"` beside a `"closed"` list or a
  closures file (known as before, the names closing more); a sources file with
  `"closed_names": null` beside its list (`{"closed": [...], "closed_names": null}`); a sources file naming
  `"closures_names_key"` with no closures file (`{"closed": [], "closures_names_key": "x"}`); a `closures_file` with
  `"closures_names_key"` naming a closures file that does not say the schema (names without the schema are unknown);
  a closures file holding `"closed_names"` that says no schema, with or without `"closures_names_key"`; a closures file
  whose schema is another version of the format (`estate.closures/1`); an entry on a list in a form that cannot be
  compared (`{"closed": ["\\\\server\\share\\x"]}`, or `\\.\C:\x`), which closes every path in every view with the
  closures still known, and is said on the page; and a closures file in the closures-file format not marked complete (unknown to plug-ins and the strict view, its
  list a lower bound for the built-in readers, as 1.3.0 read it). Each is unknown, or reads more as closed, with the
  reason said.

### Fixed
- **A settings read refused on a busy machine no longer costs you your settings.** On Windows a read can be refused while the file is being swapped in. After 150 ms of that the settings stood at their defaults, and the next save wrote those defaults over the real ones. A refused read is now tried for about a second, and defaults that stood in for a read that was refused are never saved; a damaged file is still replaced, with a copy kept.
- **A writer in a tight loop no longer shuts another out of the store's lock.** A writer waiting for it now goes
  before a holder that asks again, so a tight loop can no longer keep another out past its 10 s timeout (seen in CI).
  With two writers the waiter goes next; with three or more the gate is first-come, not a queue. A folder, a link, a
  junction or a second hard link at the lock's name is refused, at the work store's lock and gate and at the inbox's
  and the feed's locks too (a cloud placeholder of a plain file is a plain file); the card hook says, as one line,
  when the feed's lock was refused for what stands at its name, and stays silent when the feed was only busy. The
  wait is a turnstile of two OS locks (a second file, `<lock>.gate`), so there is still no stale-lock rule.
- **The work writer's seat checks fail closed.** When a seats file is configured but cannot be used (unreadable, no
  table of seats, a `"seats"` that is not a path, a misspelt key, `SEMANTEXT_SOURCES` naming nothing), a reviewer, a
  to_seat and an assignment are refused with the reason, never skipped; a wrong base drops the homes, never the seats.
  The one mode without seat checks, no seats configured at all, is said on the Work place and in `semantext work
  list`.
- **A problem's text keeps its reason.** Texts over 300 characters were cut at the end, losing the reason after a long
  path. Now the long words are shortened in the middle first, then the span of paths, each cut keeping a short hash of
  what it cut; only a text with no path, or whose start or reason alone is over the cap, has its end cut, with an
  ellipsis (and then the reason keeps its start).
- **No home folder is a problem, never a failure.** Where the system gives no home (and no Semantext home is set), the
  Places reader failed, and every route of the page raised; now the closures are unknown and said so, and every
  built-in route answers with "no home folder" as a problem.
- A plug-in given a `ReadContext` whose fields (or whose names' fields) are set after it was made finds every path
  closed: it is sealed once, when made, and never sealed anew. Each plug-in is given its own sealed copy, so one
  plug-in's change to its context never reaches another's. The seal stops accidents, not a hostile plug-in running in
  the same process (SECURITY.md says why).
- The Plug-ins place answered with an error where a Semantext home was set and the system gave no home folder; it
  answers now, as every route does.
- The key `"closures_key"` names is found one way for reading the closures and for reserving it from plug-ins
  (`closed.keys_named`): exactly as written, reserved in lower case as written and trimmed.
- The Plug-ins tab offered a settings form on a sources file that is also the closures file, where it proposes
  nothing; it offers none there now, and says why.
- The page's Plug-ins tab and `semantext plugins enable` said "not named" for closures that were named and
  incomplete, or named and unreadable; they say the true state now.
- The Plug-ins tab's files (the change log, the rotated log, the last-changes file, the proposals) are no longer
  written while one has a second name on disk (a hard link), nor through a link or at a folder.

### Documented
- SECURITY.md now says which built-in readers apply the closures, and which do not (the places reader's `.identity`
  and `MASTER.md` title reads, the gates, the gaming check, the rules reader, the Record reader
  and the git-index evidence policy), as was already so in 1.3.0; and that a plug-in is handed the closed paths and
  names in its ReadContext. It also says which view of the closures each reader uses (plug-in, strict, lower bound).
- `docs/plugin-api.md` now describes 1.4: closed names and `ReadContext.names`, the complete-list rule for plug-ins,
  the reserved keys, the `semantext-plugin.json` declaration, and the Plug-ins tab (the page proposes, the console
  applies).
- The security floor holds eleven more promises: the Plug-ins tab only proposes and turns off; closures by name fail
  closed; a partial list of closed paths is never read as complete by a plug-in; a root that holds a closed path is
  not walked; nothing 1.3.0 read changes meaning, with one deliberate exception; every spelling of a closed place is closed; answering is the person's act; the page answers only itself; MCP answers nothing; an agent touches only its own requests; the readers named refuse a hard link.

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
- **On Python 3.10 your acts and the verdicts are read.** Their times end in `Z`, which `datetime.fromisoformat`
  takes only from 3.11, so on 3.10 every act of yours was "undecidable" and every verdict "no evidence found". The
  span and the verdicts reader now read a trailing `Z` as UTC.
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
