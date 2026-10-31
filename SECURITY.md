# Security

Semantext runs on your machine. It reads and writes files in one folder, and it serves one page to your own browser.
This page says what it touches, how it protects you, what it does not protect against, and how to report a problem.
The refusals Semantext promises, each with the tests that hold it, are listed in
[the security floor](docs/security-floor.md).

## What it touches

- **Files.** Semantext reads and writes only `~/.semantext`, or the folder named by `SEMANTEXT_HOME` or `--home`. Your
  inbox (`inbox.jsonl`) lives there too. The two exceptions follow.
- **Claude Code's settings.** It changes `~/.claude/settings.json` only when you run `semantext install claude-code
  --apply` or `semantext uninstall claude-code --apply`.
  - It saves a backup beside the file first.
  - It refuses a settings file it does not understand, and leaves that file untouched.
- **Other agents' instruction files.** It changes `~/.codex/AGENTS.md`, a project's `knowledge.md`, or the file you name
  with `--file` only when you run `semantext install codex|freebuff|agents-md --apply` (or `uninstall`), and
  `semantext sync` refreshes only the files it installed into.
  - It writes only between its own two markers, and saves a backup first.
  - `uninstall` gives the file back byte for byte, and broken markers are refused, not guessed at.
  - The paths of the files it installed into are kept in `state.json`, in your home, so `sync` can find them.
- **What it reads outside that folder.** `semantext mine` and `semantext backtest` read Claude Code's transcripts for
  the current project (`~/.claude/projects/`). `semantext teach`, run from Claude Code's shell, reads that session's
  transcript to check that the words are yours. The hook records each session's transcript path, never its prompts, in
  `sessions.json`. The page lists the names of local Ollama models, from `~/.ollama/models/manifests/`.
- **The network:** none by default. There is no telemetry, no account and no update check, and the page listens on this
  machine only. The one exception is opt-in: `semantext backtest --reader` sends the card and the messages it scores to
  the model you name (Ollama on this machine, or an endpoint you give; one off this machine is announced before its
  first call).
- **Your prompts.** They are not kept unless you switch on `semantext config hear-prompts on`, which is off by default.
  If you do, they are kept in `~/.semantext/heard/`, on this machine.
- **The feed.** The hook keeps one line per card it hands out in `~/.semantext/feed.jsonl`, so the page can show what
  Semantext is doing. A line says what Semantext decided, never what was said:
  - who asked and how it was known, whose words they were and what told;
  - for another agent's message, the name its opening tag gives the sender: that sender's own claim, taken from the tag
    alone, never checked, and dropped when it looks like a key;
  - the environment, the card's form, and the rule ids on it, layer by layer;
  - its size, and the numbers of the inbox answers and requests that went with it;
  - for your own words only, what Semantext's quick reading noticed, by kind and nothing more: a question, a maybe, a
    yes, a pause, a time phrase, a correction, an instruction, an ask that needs your word, an answer to a request.
  No prompt's text is written. Every value is checked for the shape of a key, a token or a password, and one that has
  it is kept as `(withheld)`. A line with any field beyond these is refused, and never read back. The file is cut back
  to its newest half past 512 kB. `semantext feed off` (or Settings on the page) stops it, and then nothing is written,
  not even its lock file. A busy feed is skipped, never waited on.

## The page (`semantext serve`)

- **The address:** it binds only to `127.0.0.1` or `localhost`. Any other host, including `::1`, is refused before
  anything is bound.
- **The port, on Windows:** it is taken exclusively (`SO_EXCLUSIVEADDRUSE`), so no second program can listen on it at
  the same time.
- **Requests:** it answers only requests addressed to its own host and port. A request with any other `Host` header gets
  403, which guards against DNS rebinding.
- **Changes:**
  - It accepts a change only when the request carries the page's own `X-Semantext: 1` header.
  - Every change needs the page's own `Origin`, which your browser always sends with it. A change from a foreign
    `Origin` gets 403, and so does one with no `Origin` at all: that is a local program, not your page. This covers
    answers to your inbox, changes to your rules, and naming or binding your agents, so an agent cannot use the page's
    address to do what its own shell is refused.
  - It never sends a CORS header, so another website open in your browser cannot read from it or change your rules.
- **The feed, the counts and the register:** the server gives them only to the page's own script. A request must carry
  the page's `X-Semantext: 1` header, which another website can send only after a preflight this server never grants,
  and a browser that names the requesting site must name this one. The feed is never served as a file. Trying a
  message, from the page's Try a message, writes nothing: no feed line, no rule, no request and no pending decision.
  - It always sends `X-Content-Type-Options: nosniff`.
- **Request bodies:** it refuses a negative or oversized `Content-Length` (over 200,000 bytes). It drops a request that
  stalls for 10 seconds.
- **The page's own code:** it builds all rule text with safe DOM calls, with no `innerHTML` and no `eval`, so a rule
  cannot inject a script into the page. A test fails if such a call appears.
- **The v2 page's policy:** `/v2` and every file beside it carry a Content-Security-Policy: scripts and styles only
  from this server's own files (`script-src 'self'; style-src 'self'`, no `'unsafe-inline'` for either since api
  0.2), reads only back to this server, images only the `blob:` URLs a diagram is shown through, and no framing. A
  test fails if a module or the page sets an inline style or holds an inline script. A document (an SVG) is served
  with its own policy (`default-src 'none'; style-src 'unsafe-inline'; sandbox`) and shown only through `<img>`.

## Rule files

- **Your words in them:** a learned rule keeps your correction, and a correction kept as a test keeps the message
  your AI got wrong. A message that looks like it holds a key, a token or a password is refused before it is kept.
  Both stay in the file on this machine; mind them before you share an environment's file. The card carries only how
  many tests there are, never their messages.
- **Loading:** rule files are loaded with `yaml.safe_load`, so a rule file cannot run code.
- **Saving:** the editor refuses a file that would break. That means invalid YAML, a changed environment id, a rule
  without an id or a statement, and duplicate ids.
- **History:** every change keeps the previous version in `~/.semantext/history/`. Nothing is ever deleted.

## The Claude Code hook

- **What it prints:** the card for your active environment, and before it, short notes from your inbox (what is waiting
  for you, your answers to the AI that asked, and, when your own message answered requests, what was recorded), and
  nothing else. It never blocks a prompt: on any failure it prints one line and exits 0.
- **What it writes:** the feed's line (unless the feed is off), and an answer you typed in your own message, to the
  inbox (see below). Nothing else.
- **Its size:** what it prints stays under 9,500 bytes. The inbox notes take at most 3,000 of them. An answer too long
  to fit is counted, never cut, and the notes tell your AI to run `semantext answers` to read it whole.

## The inbox

- **Answering is your act.** An agent may file a request and withdraw its own; it must never answer one. Semantext
  holds that rule where it can:
  - `semantext answer` refuses in an agent's shell, which it knows by `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`,
    `CODEX_SANDBOX`, `CODEX_SANDBOX_NETWORK_DISABLED` or `SEMANTEXT_AGENT`. It also refuses without an interactive
    console. On Windows it asks the console itself, since the null device also looks like a terminal there. The
    refusal names none of these variables.
  - The page accepts an answer, like every change, only with its own `Origin` (above).
  - In chat (`#12 2`), only the hook records an answer, and only for a message that opens as your own words **and**
    that the tool's own record says you typed (Claude Code keeps one for every prompt). The record can take a message
    away from you, never give one to you. Another agent's message, a tool's notice, or a message with no record answers
    nothing, whatever it says, so a relayed "approved, #12 1" is never your word.
  - The record proves you typed or pasted a message, not that a line in it was meant as an answer. So a message counts
    only when it is one answer in the strict form and nothing else (see [docs/inbox.md](docs/inbox.md)): pasted
    notes, an issue list or a ranked list of `#N` lines answers nothing, and the AI is told so. The limit that remains:
    one pasted line in exactly that form, sent as the whole message, is taken as an answer, and the AI is told what
    was recorded.
  - An answer that looks like it holds a key, a token or a password of a known shape is refused, from anywhere. A long
    run shaped like an unlisted key (32 or more mixed letters and digits, a full commit hash included) is kept, and
    shown on your page, but withheld from everything Semantext sends to an agent: the card's notes, `semantext answers`
    and `semantext decisions`, and the MCP tools.
  - Every answer records whether it came from your terminal, the page or your own message in chat, and
    `semantext inbox --all` shows it.
  - An agent that runs its commands in a real console, and sets none of those variables, passes the check. Give such an
    agent `SEMANTEXT_AGENT=<its name>` in its own environment. The check then refuses it, and its requests and answers
    carry its name.
- **Withdrawing.** A withdrawn request stays in the file, with who withdrew it, as they stated it. The command line lets
  only the request's asker, or you at your own terminal, withdraw it.
- **Whose request is whose.** A request records its asker's key and session, and an agent reads, marks or withdraws
  only its own. A bound agent's key is its folder, and a seen agent's is its tool and project. A stated name (`--from`,
  `$SEMANTEXT_AGENT`) is a claim, with a key of its own, so it never reaches the requests or answers of an agent bound
  or seen under that name. A name only labels whose rules and answers these are; it never grants anything.

## Over MCP

- `semantext mcp` speaks only over the standard input and output of the tool that started it, on this machine. It
  opens no port.
- **No tool answers** a request, and **no tool changes** your rules. `propose_rule` files a proposal for you to add or
  decline, and over MCP no rule is ever taken as your words, since there is no transcript to show they are.
- **Who is asking:** a tool that marks its own processes is seen as itself, and a folder you bound wins. Otherwise a
  client's own name for itself is a claim, which never reaches the requests or the rules of an agent bound or seen
  under that name.
- **No relay card over MCP.** Your prompts do not pass through Semantext there, so it cannot tell your own words from
  another agent's or a tool's notice. The client's AI reads everything under your full card, and only the hook path
  can tell whose words a prompt carries.

## Your rules

- **Changing them is your act,** like answering. In an agent's shell, or anywhere without an interactive console,
  `semantext teach` files the rule in your inbox as the agent's proposal, never as your words. One exception, in Claude
  Code: if the words are a whole sentence you typed in that same session, word for word, shaped as a standing
  preference with no hedge, question or time word, they become your rule at once, with the session and your message's
  hash recorded. `toggle`, `pin`, `undo`,
  `feature`, `env use|new|add`, `config`, `hear`, `forget` and `propose --accept` are refused there.
- **Disconnecting Semantext** (`uninstall --apply`), and wiring a hook command other than the standard one into Claude
  Code (`install --command`), are refused in an agent's shell. Installing the standard hook is left to agents, since
  setting Semantext up is often their job.
- **Provenance.** A rule you taught carries your words. A rule an agent proposed, which you added as it was, says so,
  on the card and on the page. The hook keeps only your own prompts as heard words.
- **Commands are never run.** A command request shows the command exactly as the agent wrote it, what it does and how
  to undo it, with a second-look flag for deleting, the network or admin rights. You run it yourself, then answer Done
  or Won't do.
- **Secrets are refused.** A request that looks like it carries a key, a token or a password, in any of its fields, is
  not filed.

## Plug-ins

- **What one is.** A plug-in is a source (a reader of your files), a place (a part of the page) or a checker, offered
  by a Python package you installed, through an entry point in the group `semantext.plugins`. Nothing is fetched, and
  no folder of loose scripts is loaded. `semantext plugins` lists every plug-in, built-in or not, with the package it
  came from and whether it is on. The built-in parts are registered the same way. A built-in is told apart by being
  the package's own code, flagged when the package registers it, never by a name: an installed package called
  `built-in` is an outside plug-in like any other, held to every guard below.
- **Installed is not on.** A package's plug-in is loaded only when you have turned it on, and only at the version you
  turned on: an upgrade turns it off until you turn it on again. What is on is kept in `plugins.json` in your home.
- **Turning one on is typed at your console.** `semantext plugins enable <kind>.<name>` refuses in an agent's shell
  (the same markers as answering) and anywhere that is not an interactive console, and asks you to type the plug-in's
  name back. **This bars an agent that follows the rules. It is no bar against one that does not:** a program
  running as you can open a console and type the name, or write `plugins.json` itself. A known limit, decided.
  Turning a plug-in off (`disable`) is not held to the console, since it takes reach away.
- **Where plug-ins run.** The page's server and the command line load them. The card hook loads none: it never imports
  the registry, and a test pins the modules it imports.
- **A plug-in holds the whole process's reach.** It runs in the same Python process as the page or the command line,
  so it can read and write what they can, start a process, or change any function, the checks on whose words a
  message carries included. Semantext's laws (read only, start no process, set your text as text) are checked on a
  plug-in's code path, never inherited, and the conformance kits that will check them are not built yet
  (`semantext plugins check` says so, and exits 1). A plug-in is code you chose to install: install only what you
  would run yourself.
- **A plug-in that fails** to load, offers the wrong shape, takes a built-in's name, has an attribute that raises when
  read, or is declared under one `<kind>.<name>` by two packages (then neither loads) is not loaded, and the page and
  `semantext plugins` show it as a problem. Its attributes are read once, at load; after that the kernel reads only
  that copy. One that stops while being read, raises SystemExit, or answers over the caps (200 problems, 300
  characters a field, 2 MB of JSON, 8 MB for every outside answer of one page together) costs only its own part of
  the page. Your own Ctrl-C is never caught.
- **A late plug-in is not stopped.** Each call into an outside plug-in (a read, a build, a document's resolve and
  check, and the import that loads it) has a time budget, 5 s unless `SEMANTEXT_PLUGIN_SECONDS` says otherwise,
  counted from when it starts to run; a call waiting for one of its plug-in's 4 turns waits at most that long again,
  and is late without running. At most 8 calls of one plug-in, and 32 of every plug-in together, wait in line; one
  more is refused at once. A call that is late is a problem and its answer is not used, but **a thread cannot be
  killed**: the call goes on in the background, with the process's whole reach, until it returns or the server stops.
  One plug-in holds at most 4 such calls, and at most 16 threads of every plug-in's calls are alive at once, late or
  not, so no more than 16 can hang; while 16 hang every plug-in's call is refused until one returns. The page and
  `semantext plugins` name the plug-ins holding them.
- **An outside place reads a copy.** It is given a copy of every source's answer, so it cannot change what the page or
  another place reads. It is still code in the process (above).
- **What `semantext plugins` prints** has every control character and escape sequence escaped first (shown as its escape,
  never taken out), so a package's name or version cannot move or rewrite your console.
- **Closed places.** The sources file may list folders under `"closed"`, or name a closures file of your own
  (`"closures_file"`, a full path, and `"closures_key"`, the key in it holding the list; `"closed"` when not given);
  the two lists merge. `semantext.api.is_closed_place` says whether a path is in one of them, also through a link,
  for any part that asks. **Until your closures are named, every path is closed to a plug-in:** with no `"closed"` key
  and no closures file (or no sources file), whatever `"closed_names"` says, `semantext.api.closures_known()` is false,
  `is_closed_place` says true for every path, and `semantext plugins enable` refuses with "name your closed places
  first". An empty list is a statement that nothing is closed. A list or file that cannot be read, a closures file over
  1 MB (the sources file has no such cap), one that holds anything but full paths (a path record, `{"path": ...}`, is read only in a closures file that says the
  closures-file format's schema), or names its key twice, is unknown in the same way. A closures file must hold
  its paths key (the one `"closures_key"` names, or `"closed"`), even as an empty list. In a closures file that says the
  closures-file format's schema, a key that is neither key read and holds a list shaped like closures (not empty, and
  all full paths, or all records of one name form and nothing else) is a list nobody would read, so it makes the
  closures unknown too, whatever the key is called. A closures file without that schema keeps 1.3.0's rule:
  `{"closed": [], "closed_paths": ["..."]}` is known, and the second list is not read. Prose, texts and records of
  other shapes beside the lists are left alone, so one file can serve more than one tool; the one exception is the
  names key in a file without the schema, which makes the closures unknown whatever it holds, prose too. Why
  closures cannot be used is said: on the page as a "closures" problem, and in the refusal of `semantext plugins
  enable`. In the sources file such a list under a key no reader reads is said as a "closures" problem, and does not
  close anything. The built-in readers keep their rule: with nothing named they close nothing (roots do not depend
  on the closures: a root named in the seats file is read all the same), and what cannot be read closes everything. These are files an agent can edit, like
  the rest of the sources file, and a plug-in that does not ask is not stopped.
  A Windows path written with the `\\?\` prefix (or `\\?\UNC\`, with either slash) is judged as the path it names; before
  api 0.2 such a spelling of a file in a closed folder compared open.
- **Closed names.** Beside the folders, `"closed_names"` (in the sources file, or in the closures file under
  `"closures_names_key"`, `"closed_names"` when not given) closes a folder or file by its name in any folder. The
  entries are in the closures-file format (schema `estate.closures/0`): each has an `id`, a
  `form` and that form's fields, and may carry `regex`, `closes`, `note`, `sentence` and `examples`, which describe it
  and are never read for matching. The forms: `segment` (a segment of exactly that text, and what is inside it);
  `segment-pair` (a separator, two segments, then a separator, a `:` or the end); `segment-prefix-except` (a segment
  that is a prefix and then only word characters, `.` and `-`, unless what follows the prefix is the excepted
  remainder not followed by an ASCII letter or digit; its two descriptions are read only in the file's own phrasing);
  `segment-or-dotted-prefix` (a segment of exactly that text, or one starting with it and a dot); `substring` (the text
  anywhere in the **whole** path, so `my_coinjar.txt` and `coinjar.txt.d\a` are closed); and `suffix` (the end of the
  whole path). Matching follows the file's own rules: a search over the whole path string; case-insensitive as
  Python's IGNORECASE takes it or wider (U+0130 and U+0131 as `i`, U+017F as `s`, the Kelvin sign as `k`); `/` and `\`
  both separators on every system; a single trailing newline as an end; the path as given, as written in full and with
  every link resolved, any entry closing. **A path is closed when any of four legs closes it:** the field matcher on
  the path as given (case folded, not normalised), on its composed form (NFC), and on its decomposed form (NFD); and
  the entry's own `regex`, case-insensitive and searched over the whole string (compiled once; over 2,000 characters,
  or not compiling, makes the closures unknown). So Semantext closes every path the entry's regex closes, by
  construction, and may close more: never less. (Composing alone was measured to open paths: a combining mark after a
  literal merges into its last letter under NFC, and some letters decompose under NFC into a base and a mark that ends
  a prefix's segment.) Semantext also reads the path as Windows does, each part without an NTFS stream suffix and
  trailing dots and spaces (`private-notes::$INDEX_ALLOCATION`, `private-notes.`), closing more again. Where an
  entry's fields and its regex disagree on the file's own examples, or either differs from an example's label, the
  page says so; nothing is opened by it. **Closed names add closures; they never by themselves make the closures
  known.** For a plug-in and the strict view, known needs what 1.3.0 needed (a `"closed"` list, or a closures file
  read by its rules), and names then close more. A sources file with `"closed_names"` and neither is none named for a
  plug-in, as in 1.3.0 (every path closed, and `semantext plugins enable` refuses), and its names close what they name
  for the built-in readers and the strict view. In a sources file shaped like the closures-file format (its schema or
  its keys, and no closures file), `"closed_names"` is one of the format's keys there: said, not read. In a
  closures file the paths key must be there too, and the names key must be there when `"closures_names_key"` names
  it. A list given as null (`"closed_paths": null`, not supplied yet) is unknown, never an empty list, and the reason
  says so, whichever key is read; so is a closures file whose `schema` is another version of the format (`estate.closures/` and anything but `0`;
  another tool's schema is read by 1.3.0's rule), a closures file that
  holds names and says no schema, one that says the schema and holds a key the schema does not have (it may be a kind
  of closure this code cannot read), and one whose `matching` carries a version this code does not know. Each reason
  names the entry's id and the field. An entry without an id (or with one given
  twice), with an unknown form, without a field its form needs, or with a field neither its form nor the descriptive
  ones has, makes the closures unknown, and every path closed. So does a literal that would close nothing as typed:
  empty or dot-only, starting or ending with white space, holding a control, format or separator character (an inner
  ASCII space aside), or only combining marks. A separator, a `:` or a glob character (`*`, `?`, `[`, `]`) in a
  literal is refused too, so one closures list means the same on every system and no entry is read as a pattern. A
  name that closes nearly every path (a substring, suffix or prefix under 3 characters) is kept, as your choice, and
  said on the page. Names are judged by
  spelling: the folder-identity comparison closed folders also get (a mapped or subst drive) is not made for a name,
  and a hard link to a closed file under another name is not seen (the serve hook refuses any file with a second
  name).
- **Which built-in readers ask, and with which view.** There are three views of your closures. The **plug-in view**
  (`semantext.api.is_closed_place`): known only when the closures are named, readable and, in the closures-file
  format, complete; otherwise every path is closed, none named included. The **strict view** (`closed.strict_closures`):
  as the plug-in view, except that with no closures named nothing is closed but what closed names alone name. The
  **lower-bound view** (`closed.closures`): with no closures named, the same; a closures file that is named and incomplete is read
  for what it does list (`known_closed_paths` and every name), never as complete. Which reader uses which:
  - the plug-in view: the serve hook (with `semantext.api.inside_roots`, for a plug-in place's documents), Work's
    clause facts and its verdict and pieces files, and every plug-in;
  - the strict view: the run-record reader (its folders and each run's subject), which the Work runs reader reads
    through too;
  - the lower-bound view: the requests and change-record card readers, and the places reader's root rule (below).
  The serve hook, Work and the run records reach what files hold and show it, so while your list is incomplete they
  read nothing (Work says "your list of closed paths is incomplete"). The lower-bound readers show what files hold
  too, and read the list for what it lists: the card readers show the lines of each seat's requests file
  (`requests.jsonl`) and change-record file, and so a requests file under a named root that no rule matches is read
  and shown while the list is incomplete; the root rule only decides whether a root is walked, and the places reader
  then shows each project's `.identity` emails and each document's `MASTER.md` title from roots it walks.
  The closures are **not** applied by the places reader's reads of `.identity` files and `MASTER.md` titles (beyond
  the root rule), the gates, the gaming check, the compute monitor, the rules reader, the Record reader (its register and notes files), or
  the git-index evidence policy. A closed place where one of those reads is not kept from it, with one exception: the
  places reader refuses a named root that is, or holds, a closed path (its walk would enter the closed place), and
  says so; the rows the serve hook and plug-ins read keep such a root, since they ask the closures of every path
  under it.
- **A complete list for plug-ins, a lower bound for the readers.** In a closures file that says its schema, a plug-in
  is judged by the list under the key `closures_key` names (`closed` when not given, so a file that uses `closed_paths`
  needs `"closures_key": "closed_paths"`, and is unknown without it) only when it is a list, `closed_paths_complete`
  is exactly `true`, and every path in `known_closed_paths` is in it, compared by component (two forms that cannot be
  read by string, such as two different shares, compare equal here). Anything else (null, not complete, the two lists disagreeing) closes every path to a
  plug-in, and the reason is said: a partial list is never read as complete. The readers of the lower-bound view (the
  card readers, the root rule) read `known_closed_paths` (and the paths key's list when there is one) beside every name
  entry, and the page says "incomplete: files under a named root that no rule matches are readable until the list is
  complete"; the readers of the plug-in and strict views read nothing meanwhile. The closures-file format is read
  **only in a closures file** your sources file names (`closures_file`), and only when that file says the format's
  schema; another version of the format is unknown, and any other closures file, another tool's schema included, keeps 1.3.0's
  rule. Your sources file
  keeps 1.3.0's closures rules (with `closed_names` beside them): the format's keys written in it (its schema,
  `closed_paths`, `known_closed_paths` and the like) mean nothing there, and, when no `closures_file` is named, the page says
  "this looks like a closures file (...); those keys are not read in your sources file, so nothing is closed by them. Point closures_file at it to use it", never closing anything for
  them (with a `closures_file` named it says nothing of them). **Nothing 1.3.0 read changes meaning,
  with one deliberate exception: a closures file in the closures-file format (schema `estate.closures/0`), new in 1.4,
  is read by that format's rules. Where its complete list is not supplied, it is read by the built-in card readers and
  the root rule as a lower bound (its known paths and names), and stays unknown to plug-ins and the strict view; and
  its path records are read as its paths, where 1.3.0 found them unreadable. Every other change closes more.** A test
  holds a set of 1.3.0's sources files to the closures 1.3.0 gave and judges a fixed set of paths in all three views
  as 1.3.0 judges them, against the 1.3.0 tree itself; it asserts the exception case by case, and that each file 1.4
  closes more closes every path 1.3.0 closed (CHANGELOG.md lists them). A listed
  path closes itself and everything below it, compared by component (`/` read as `\`, trailing separators dropped,
  any case), applied to the path as given and to its real path (a trailing dot or space, `..`, a stream suffix or an
  8.3 short name shows only there); a sibling whose name merely starts the same is not closed by it. A form beginning
  with two separators (a share, `\\?\UNC\`, `\\?\GLOBALROOT\`, a device path, `\\.\C:\` included) cannot be read by
  string and counts as closed while any closure exists, on every system, as in 1.3.0; only `\\?\C:\` is read as
  `C:\`, as 1.3.0 read it. **An entry on a list in such a form compares with nothing, so it closes every path**, in
  all three views, with the closures still known, which closes more than 1.3.0 did; the page says "an entry in a form
  that cannot be compared closes every path: <the entry>".
- **Plug-ins are handed your closures.** A plug-in's read is given a `ReadContext` holding your closed paths and closed
  names, so it can ask `is_closed_place`; they are not secret from a plug-in you turned on. The closures keys
  (`"closed"`, `"closed_names"`, `"closures_file"`, `"closures_key"`, `"closures_names_key"`, and the closures-file
  format's `"schema"`, `"closed_paths"`, `"closed_paths_complete"`, `"known_closed_paths"`, `"known_open_paths_near"`)
  are reserved, in any case: a plug-in that declares one as its own key is not added, so none is handed them as
  settings, and the Plug-ins tab never writes one.
  **The context's seal stops accidents, not a hostile plug-in.** A `ReadContext` is sealed once, when it is made (a
  keyed hash of its home, closures and names, with a key made fresh in each process): one whose fields, or whose
  names' fields, are set afterwards closes every path, and it is never sealed anew. Each plug-in is given its own
  sealed copy, so a plug-in that changes its context closes only its own reads, and never opens a path for another
  plug-in. But every plug-in runs in Semantext's process, with its whole reach: one in-process plug-in that means harm
  can read the seal's key, make a context of its own, or change the closures that copies are made from, and so open the
  closures for others. Against such a plug-in the protection is turning it on only once you trust it (above), not the
  seal.
- **Page modules are unrestricted code in the page.** An outside place may ship one ES module, served only from its
  own distribution's listed files, only once you turned the place on. The page's policy stops it loading anything from
  another site, and the text-only helpers it is handed (`h`, `text`) make setting text as text the easy path. **They
  are not a sandbox:** the module runs with the page's whole reach, as the plug-in's Python runs with the process's.
  **So a page module can act as you on the page:** answer requests, teach or change rules, and change settings,
  since it can send everything the page sends. A change whose `Referer` is a module's path, or that a browser marks
  as anything but a plain fetch, is refused; a module calling `fetch()` from inside the page is not told apart by
  that. Running each module in a sandboxed frame of its own is designed, not built (`docs/page-module-sandbox.md`).
- **Documents by row.** An outside place may serve its own files to the page at `/api/v2/doc/<place>/<row_id>`. The
  row id is letters, digits, `-` and `_`, checked before anything is looked up; the path comes only from the place's
  own `resolve`, and at serve time it must lie, as it leads now (links resolved, the `\\?\` prefix off), inside a named
  root and outside every closed place (`semantext.api.inside_roots`, the same judgement plug-ins are given). The bytes
  are read once (at most 4 MB) and exactly those go to the place's `check_bytes`. **A known limit:** the check and the
  open are two steps, so a folder swapped for a link between them is not seen.
- **The Plug-ins tab: the page proposes, the console applies.** Drawing the tab calls no plug-in, and never loads the
  entry point of one that is off: it reads the packages' metadata, each package's declaration file
  (`semantext-plugin.json`, data among its listed files), `plugins.json`, the sources file, the closures file it
  names, `plugin-proposals.json`, the last 512 KB of the change log and of the rotated log, and how each plug-in's last call ended. **A module two plug-ins share runs** when the one that is on is
  loaded, as every page answer loads it: "never loads the entry point of one that is off" is not "no code of its
  package runs". The page's acts are POSTs under the page's write guards above, read with any key given twice refused.
  **The page turns a plug-in off. It never turns one on, and it never writes a plug-in's settings:** a change from the
  settings form, and a rollback of a settings change, is checked against the plug-in's declared settings and kept as a
  proposal, and the page shows the line that applies it, `semantext plugins confirm <n>`. A proposal carries a label,
  `widens`, `narrows`, `unknown` or `order changed`, worked out from the declarations' types (a path not inside the old one, a link
  inside it that leads out, a list that gains an entry, a setting declared `widens`, or taking a setting out without a
  declared default no wider all read as `widens`); **the label is for you to read, and decides nothing.** The page's
  answer to a proposal is 202 Accepted, with its number and the line; a refusal is a 4xx. A setting may not hold a
  control, format or bidi character, or a line or paragraph separator (a zero-width space, U+202E, U+2028, U+2029 ...;
  a space separator such as U+00A0 or U+3000 is accepted), nor a lone surrogate; a path
  setting is refused, on every system alike, when it holds a `\\?\`, `\\.\` or `\??\` prefix (with `/` or `\` in any mix),
  a `:` anywhere but after a drive letter, a part that is `.` or `..` or ends in a dot or a space, or a part that is a
  device name in the shape the path rule reads one (`CON`, `NUL`, `COM1`, `CONIN$`, `con .txt` ...). An error in a POST that no one wrote for the page is a fixed
  answer with its kind, its words withheld (400 for a bad value, 500 for anything else).
- **What confirm applies is shown exactly, or confirm refuses.** `semantext plugins confirm <n>`, held to an
  interactive console as `enable` is, shows the sources file, who proposed it and when, and its exact difference. A
  list is shown as its parts only when entries were just added at the end ("+ put in, as entry 7: ...") or just taken
  out with the rest in the same order ("- taken out: ..."); any other list change, an order changed at all above all
  (labelled "order changed": what an order means is not known, so never "narrows"), and a list set for the first time,
  shows the WHOLE list before and the WHOLE list after, one numbered entry a line. Anything else is its whole value
  before and after. **Every line `semantext plugins` prints, every line around a yes above all (confirm, enable,
  show, and their refusals), goes through one renderer, in printable ASCII alone and one to one:** each value as
  JSON, and every character outside U+0020 to U+007E, in a value, a path, a name, a version, a label or a refusal, as
  its escape (`\uXXXX`, or `\UXXXXXXXX` past U+FFFF), the backslash itself as `\\`, a run of spaces (or a space at
  the edge of a name) as `\u0020` each; so a Cyrillic letter, a Hangul filler, a combining stroke, a variation
  selector, a control character or a right-to-left letter is never shown as itself, never taken out either, and two
  texts or values that differ never look alike (a key `a` and a Cyrillic es is `a\u0441`; the key of the six
  characters `a\u0441` is `a\\u0441`). Exact and unambiguous rather than pretty; never collapsed, deleted or cut. (The
  page's own display may show them as themselves.) List entries are compared as written, never by equality (`1`,
  `1.0` and `true` differ). A review is measured as it is rendered: every line, its header included, wrapped at the
  console's own width (100 columns when it cannot be told; a narrower console is said at the review's head), and the
  rows counted; past 60 rows confirm refuses, and names `semantext plugins show <n> --full`, which prints all of it
  (the label as things stand now included) and ends with a review code (8 hex of the sha256 of what it printed, of
  what confirm prints before its yes, the proposal and the sources file's sha256), and
  `semantext plugins confirm <n> --reviewed-full <code>`, which applies it only if that code is the review's now: a
  wrong code, or one of a review that has changed since, refuses. The proposal is applied under the lock
  only if the sources file is byte for byte what it was made on (its sha256), at the same path (a console whose
  `SEMANTEXT_SOURCES` names another file does not confirm it), and no change has been recorded to its keys since it;
  else it is stale. A proposal expires after an hour. **A superseded proposal is never applied in place of another:**
  when the page (or anything sending as it) makes a newer proposal for one of the same plug-in's settings, the older
  one is refused, both are named with who made each and when, and the newer is confirmed only by its own number, after
  its own review against the file as it is now. Open proposals are kept by number in `plugin-proposals.json` (one
  open per plug-in and setting; the rest remembered to 200), so one is found however many records follow it in the
  log; that file is refused if it is a link, and if it cannot be read nothing is proposed or applied (it is never
  reset). No proposal is made or applied on a sources file that is also your closures file (`closures_file` leads
  back to it, links resolved), and **no record, rollback or proposal ever writes a reserved key**: a key of
  Semantext's own, of your closures, or the key `closures_key` (or `closures_names_key`) names, in any case; a
  plug-in whose `keys` or `needs` name one is never loaded (said as a problem), by the same list the page uses. A
  record or proposal number is ASCII digits alone: `²` or `١`, which other checks take for digits, is refused, and a
  proposals file naming one is refused whole (said on the page as a problem).
- **The console is the point of review.** `semantext plugins enable` shows, before you type the plug-in's name, exactly
  and uncut: every setting it declares, with its value now (or the declared default it then reads); every other key of
  your sources file, with its value, since a plug-in that is off cannot be asked which keys it reads (it may read keys
  it never declared); the keys Semantext keeps for itself, which no plug-in is given; and every settings change
  recorded since it was last turned off, to any key, with who made it and when, kept even past the log's rotation, in
  printable ASCII as confirm's review is, the package's name and version and any declaration problem included. A
  review over 60 rows at the console's width (its header lines counted) is refused there and shown by
  `semantext plugins show <kind>.<name> --full`, whose review code (bound to that review and the enable snapshot)
  `enable <kind>.<name> --reviewed-full <code>` must give back. The review is snapshotted (the sources file's sha256, the declaration file's
  sha256, the package's version, and the last recorded change to the plug-in and to each key it will be given), and
  the plug-in is turned on only if the snapshot still holds under the lock after your yes; else it is refused, and you
  run `enable` again to see it as it is now. A record touching neither (the page turning another plug-in off, a
  proposal) never refuses it.
- **What a page module can still do, and the way out.** It can do what the page does: turn plug-ins off, and make
  proposals and rollbacks, at most 30 a minute. That limit is shared with the page itself, so a module filling it can
  keep YOUR proposals and settings rollbacks from the page refused for a minute at a time; turning a plug-in off is
  never counted against it, so it can never keep you from turning that plug-in, or another, off. It cannot apply a
  proposal or turn a plug-in on. It can keep superseding a
  proposal of yours for the same setting, so that each confirm names a newer one to review; and it can fill the change
  log so that older records rotate out (proposals stay findable). The way out is yours at the console: confirm the
  newest after reading it, or don't; `semantext plugins disable <kind>.<name>` for the plug-in whose page module it is
  (or stop the page); `semantext plugins` to list what is on; or edit `sources.json` and `plugins.json` by hand, which
  the page never prevents.
- **The change log is bounded, and comes first.** `plugin-changes.jsonl` is appended to and never rewritten, never
  through a link; every writer of `plugins.json`, the sources file, the change log and `plugin-last-changes.json` (the
  page's turn-off, and the console's `enable`, `disable` and `confirm`) takes one lock, `plugins.lock` in your home.
  For each change the record is written and synced first, then the last change to its key or plug-in in
  `plugin-last-changes.json`, then the change itself. Under a kill: before the record, nothing happened; after the
  record and before the change, the record stands, and the tab shows it "not applied", which means exactly: **the file
  this record names does not now hold its "after", and no later record explains it** (a hand edit since reads the same
  way); it is never rolled back. One record is at most 64 KB (a larger one is refused, and nothing is made); the page
  may make at most 30 proposals and settings rollbacks a minute (turning a plug-in off is never held to it); asking again for exactly an open proposal writes nothing. When an append would
  take the log past 4 MB it is rotated once, to `plugin-changes.1.jsonl`, its numbers going on in the new log; its
  records can be read there but are no longer rolled back (an open proposal is still confirmed, from
  `plugin-proposals.json`), and **at the next rotation they are dropped**,
  so a page sending large proposals at its rate can push a record out of both logs in minutes. What is never dropped:
  the last change to each setting and to each plug-in's on or off, in `plugin-last-changes.json`, one entry per key and
  plug-in, never rotated; it is refused if it is a link, and if it cannot be read every change and every proposal is refused (no record is appended) (it is never
  reset, which would lose that history) until you move it aside. **Numbers never start again:** each record is
  numbered above the highest number the log, `plugin-last-changes.json` or `plugin-proposals.json` knows, so moving the
  change log aside (as a log whose end cannot be read asks you to) begins a new one that goes on from there, and the
  enable review still sees what changed; a number in a log that does not go up is a problem said aloud, and is not
  acted on.
- **The line to type holds no free text.** A plug-in's name is a plain word (letters, digits, `_` and `-`; an entry
  point named otherwise is never listed or loaded, and one left on from before under such a name is shown as such,
  with `semantext plugins disable <name>` when the name is plain or a note to edit `plugins.json` when not). `--home`
  is shown only for a home of letters, digits, spaces and `\ / : . _ -`, with no quote of any kind (PowerShell takes the
  curly quotes for quotes too); for a POSIX shell it is quoted whenever it holds a backslash or a space. For any other
  home the line leaves it out, and the page says to type the line in a console where `SEMANTEXT_HOME` names your home.
  The lines are for PowerShell on Windows and a POSIX shell elsewhere; **pasting into cmd.exe is not supported.**
  **The same limits as above:** a page module can do what the page does: turn plug-ins off and make proposals, at most
  30 a minute. It cannot apply one or turn a plug-in on. The declaration is the package's word, not a fence; and the
  change log and `plugin-last-changes.json` are files an agent can edit (a record out of its place is shown as a
  problem and never rolled back).
- **Run records** are what a checker says, never re-run. A record whose own `outcome` is `failed` or `not proved` is
  never guarded, whatever its counts say; an outcome the reader does not know refuses the record.
- **The plug-in surface is `semantext.api`, version 0.2**, experimental until each kind has a plug-in that is not a
  built-in. Nothing else in the package is public. The contract is in `docs/plugin-api.md`, and the run-record format
  in `docs/run-record-schema.md`; what 0.2 added and changed is also in the module's own docstring.

## What Semantext does not protect against

- **Anything that can already act as you.** Malware, or another account with your permissions, can read and change your
  rules, because they are ordinary files. Semantext adds no encryption.
- **Your AI provider.** The card is sent to your AI tool with every prompt, since that is its purpose. Whatever your
  provider does with prompt content applies to the card too. Do not put secrets in your rules.
- **A model ignoring a rule.** Rules are instructions to an AI model, and a model may not follow them every time. They
  guide the assistant; they do not enforce anything.
- **A program determined to answer as you.** The inbox's checks stop an agent answering by habit or by accident. They
  cannot stop a program running as you that sets out to forge an answer. It can append to `inbox.jsonl`, call the
  library, send the page's own headers, or write a record into the tool's transcript, and it can forge the record of
  where an answer came from as well. On one
  account no software can prevent that. So "only you answer" is a rule with a record, not a guarantee.
- **An agent that edits your files directly.** The same holds for your rules and your settings. The gates stop an
  agent changing them through Semantext, by habit or by accident. A program running as you can still write the rule
  files or `settings.json`, unset the variables, open a console, or set another session's id. A rule written into a
  file by hand carries no agent's name. When its file holds none of the provenance Semantext writes, the card counts
  such rules in one line ("N rules are hand-written (no provenance)", one line however many, so the card stays under
  the hook's limit) and the page marks each; a program that writes a provenance into the file by hand is not caught.
  In a folder of ratified environments a rule with no provenance is counted in one line under its environment on the
  card, and marked in the reference and the Rules drawer: those files cannot tell a rule typed in by hand from one
  ratified without a record.
- **Reading a session's role from its commands is a heuristic.** `envhook` takes a session's role from the latest
  command that runs a program with the declaring flag outside quoted text. It reads PowerShell and bash quoting well
  enough for ordinary commands, not completely. Known shapes it reads wrong: a `$( )` holding its own double quotes
  inside a double-quoted string; a doubled backtick before a closing quote; a quote straight after a closing
  parenthesis; PowerShell's doubled single quote (`''`) inside a single-quoted string; and bash's `\"` inside a
  double-quoted string. In the first three a real declaration can be missed, and the session keeps its earlier role.
  In the last two a flag written inside text can be taken as real. A command over 200,000 characters declares
  nothing. A wrong role shows a different set of rules; it grants nothing.
- **A document read can be raced.** The page reads one listed document through one handle checked against its first
  look, and checks its folder again before the file's last check. A local program that swaps the folder for a link to
  another folder, and back, each between two adjacent checks, can still have that other file shown. Swapping once is
  refused.
- **A change's evidence digest is an oracle, kept where it confirms nothing new.** "Current" or "stale" tells whether
  a file's bytes match a guess. So the page digests only files inside the filing agent's own home and the projects
  bound to it, never through a link or junction below that folder, never a hard link, an alternate stream, a device
  or short (8.3) name. Which files are evidence is decided by structure, not by name
  (`semantext/sources/evidence_gitindex.py`): a file is evidence only when the git repository that holds it (the
  nearest `.git` folder, searched up to the root, and above it only while still inside one of the agent's roots)
  lists it in its index as an ordinary file at stage 0. **The premise, stated plainly: evidence is what the project's
  index lists, and an agent can write the index** (`git add -f .env` lists `.env` with no commit; an agent can write
  objects and commits too). So no reading of the repository is a boundary against an agent that breaks rules: this
  policy chooses relevant files for a digest to confirm, it is not a defence against such an agent. This is the
  chosen way of the two built (see `docs/evidence-ways.md`); revisit in a later review if it needs more guards. The
  repository must be a real one: `.git/HEAD` a plain file holding a commit id of the right length, or naming a ref
  git would write (no `..`, no part starting with a dot, no `.lock`) that exists, as a loose ref file under
  `.git/refs` holding a commit id or as a line of `.git/packed-refs`. So a hand-built index in a plain folder admits
  nothing, nor one beside a hand-written HEAD naming a ref that is not there; a branch with no commit yet is
  "unknown" too. It is still a test of text and files: a forger who writes the ref too is admitted, as the premise
  says. The index is read in pure Python; nothing runs git. Untracked and ignored files, files of a
  repository whose `.git` is a file (a linked worktree or a submodule) or a link, a repository whose top is above
  every root, and an index that is sparse, split, over 64 MB, a hard link, of a version other than 2, 3 or 4, or
  whose checksum does not match, are all "unknown". A short name belt refuses listed names that are almost never
  honest, with a reason: keys and key stores (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx`, `id_rsa*`, `id_ed25519*`,
  `id_ecdsa*`, `id_dsa*`), credential folders (`.ssh*`, `.aws`, `.gnupg`, `.kube`), credential dotfiles (`.env*`,
  `.npmrc`, `.netrc`, `.pgpass`, `.git-credentials`), and secret, token, wallet, vault, password and credentials as
  their own word; words honest as a note or code (`key`, `auth`, `env`, `seed`) are refused only as data (`.json`,
  `.txt`, `.yaml` and the like). On the audit's lists, tracked: all 89 secret names refused, none of its 60 honest
  names (`tokenizer.py`, `tokens.md`, `wallets.md`, `keys.py`, `key.md`, `password_policy.md`,
  `credentials_policy.md` digest). Its stated cost: a few common names the audit found holding secrets are refused
  even when honest (`app.log`, `server.log`, `access.log`, `appsettings.json`, `settings.xml`, `known_hosts`,
  `session.json`). The full old list stays in `semantext/sources/evidence.py`, off, because it refused
  honest files (`password_policy.md`, `keys.py`) and never kept up with new secret names. A secret listed under any
  other name is evidence, like any listed file. The HEAD, ref and packed-refs files are each read through one handle
  checked against the file as examined; the packed-refs bytes count against the read budget. The index's bytes count
  against the read budget when it is read, and a parsed index is kept in memory for 60 seconds, keyed by its path,
  size, modification time and file id. An absent file is "unknown", never a match. At most 50 files a record and 200 records
  an agent are digested in one page build, and at most 256 MB is read across all evidence in one build; past those,
  a record says "not checked: over the cap" or "not checked: over the read budget". Each file's digest is kept in memory
  (never on disk) for 60 seconds, keyed by its path, size, modification time, file id and its first and last 4 KB.
  So an edit that keeps the size and both 4 KB ends and puts the modification time back as it was can read as
  current for up to 60 seconds; an ordinary edit changes the time and is read again.
- **Which projects an agent is bound to is a claim the project makes.** A project binds to an agent when it is that
  agent's home, or when its `.identity` file lists the agent's email in a "Name <email>" line. Anyone who can write
  into a project can append such a line, and the page then digests that project's files for that agent's change
  records. A project bound to two agents can be digested for either; both can already read it, so the digest tells
  neither anything new. Likewise a change's "decided" follows a close line on the decision card that asks about it,
  or an outcome line: both are lines in the agent's own files, so they record what the agent wrote, not what you did.
  A changes file with a second name (a hard link) or that is a link is not read at all. Two rarer forms still get
  through, and each amounts to the agent writing the lines itself: a home folder that is itself a junction to another
  agent's home shows that agent's records under this one (the home is the seats file's to name), and a hard link made
  in the moment between the check and the read is read once.
- **A clock far ahead, then corrected, costs `undo_last` its order for a while.** Kept versions are named by the time
  in UTC, never below a name already in the history folder, and a name more than two days ahead of now is ignored
  (1.2.2), so a planted name dated 2099 cannot stop saving or pin later names. The price of that bound, stated: a
  clock that ran more than two days ahead and was then corrected leaves its versions named in the future. They are
  ignored as a floor, so the next versions get the real (earlier) time, and the future-named ones still sort as the
  newest: `undo_last` restores one of them, an older version than the last one kept, until the real time passes their
  names. A name up to two days ahead (a clock a day fast, or a local time east of UTC) does count: every later name is
  held just past it, at that future time, for as long as the clock is behind it. The order is kept then, so
  `undo_last` restores the right version, but the names show a time that has not come yet. Nothing is lost either way:
  every version stays in the folder.
- **A guarded rule's checker path is looked up only when it is local.** The page says whether the `where` a guards
  file gives for a checker is there now. A `where` that starts with two slashes (a share, `\\?\` or `\\.\`) or holds
  a colon past a drive letter is never looked up, so building the page makes no network connection for a local drive;
  a mapped network drive (a letter that points at a share) cannot be told from its text and is looked up like any
  drive. The page shows a refused `where` as written with "not checked: a network or device path". Whether a checker
  ran is never claimed.

## Reporting a vulnerability

Please report privately through GitHub's **Report a vulnerability** button, on the repository's **Security** tab. Please
do not open a public issue for a security problem.

## Supported versions

| Version | Supported |
|---|---|
| 1.4.x | yes |
| 1.3.x and older | no |
