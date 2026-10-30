# The plug-in API, version 0.2

This is the contract between Semantext and a plug-in: what a plug-in is, what it is given, what it must give back,
and what it may not do. It is written from the code (`semantext/api.py`, `registry.py`, `outside.py`, `docserve.py`,
`pagemodule.py`, `sources/closed.py`, `sources/kernel.py`, `sources/view.py`), and where the two differ the code is
right and this page is a bug. [SECURITY.md, "Plug-ins"](../SECURITY.md#plug-ins) says the same things from the
person's side.

## Stability

`semantext.api` is the one surface a plug-in imports. Nothing else in the package is public: a plug-in that imports
`semantext.sources.places` or any other module is reaching into code that may change in any release.

The version is `semantext.api.VERSION`, now `"0.2"`. It is **experimental, and stays 0.x until each kind has a user
that is not a built-in**: until then a contract is only the built-ins' shape, and the first outside plug-ins are what
shows whether it holds. 0.2 is what the first outside plug-ins asked for. Everything in 0.1 still works as it did: a
`read(config)` or a `build(sources)` that takes one argument is still called that way.

### What changed in 0.2

- `Source.read(config, ctx)`: a read that takes two arguments is given the build's `ReadContext`; `read(config)` is
  called as before. A Source's `needs` is part of the contract. A Place's `build(sources, ctx)` and `resolve(row_id,
  ctx)` are given the same context when they take two arguments.
- A Source's keys may hold lists (of plain texts and numbers, or of flat records); before, every list was dropped.
- `is_closed_place(path, ctx=None)` takes a `ReadContext` as well as a home, is true for every path while the
  closures are not known, and takes the `\\?\` prefix off a Windows path before comparing.
- A Place may serve documents by row (`resolve` and `check_bytes`), a byte span among them.
- Each call into a plug-in has a time budget and its answer has caps; attributes are read once, at load; a Place is
  given a copy of the sources' answers; a name two packages declare loads neither.
- New helpers: `ReadContext`, `closures_known`, `named_roots`, `seat_rows`, `inside_roots`, `taken_names`.
- **Changed after 0.2 first shipped (Semantext 1.4), with the version left at 0.2:** `seat_rows` and `named_roots`
  judge the seats file's base and join each home by the one rule every reader now uses (below), so they agree. A home
  written as a full path (inside the base folder or not), or one the rule refuses, now comes back from `seat_rows` as
  None, where before it gave a full path inside the base as it was and a spaced home with its space; and a base the
  rule refuses, a missing base, or a base that is not an existing folder gives no home from either, where before the
  readers each read it their own way (`named_roots` gave full-path homes with no base at all). A plug-in that read
  such homes reads None, or no row, for them now.
- **Also in Semantext 1.4, with the version left at 0.2:** closures by name (`"closed_names"`, below), and
  `ReadContext` has a third field, `names`; in the closures-file format a plug-in finds every path closed until the
  list of closed paths says it is complete; the closures keys are reserved, so no plug-in may read them as settings; a
  package may declare its plug-ins' settings and reads in `semantext-plugin.json`; and the Plug-ins tab shows every
  plug-in, turns one off, and keeps a settings change as a proposal the person applies at the console.

## Kinds

| Kind | What it is | Entry point name |
| --- | --- | --- |
| `source` | a reader of files the person already keeps | `source.<name>` |
| `place` | a part of the page, at `/api/v2/<name>` | `place.<name>` |
| `checker` | something that runs outside the package and leaves run records, which the page only reads | `checker.<name>` |

These three are open now, and were shipped first because the page is built from them. Five more are named and
**reserved**: `card-format`, `evidence-policy`, `door`, `tool`, `exporter`. They are listed, and refused: a
package that declares one is shown as installed and not on, it cannot be turned on, and it is never loaded.

The built-in parts register exactly as an outside one does (`semantext/sources/builtin.py`, `sources/view.py`), so
the way in is proven by use. A built-in is told apart by being the package's own code, flagged when the package
registers it, and never by a name: an installed package called `built-in` is an outside plug-in like any other.

`semantext.api.KINDS` is the tuple of open kinds, and `semantext.api.GROUP` the entry-point group.

## Declaring a plug-in

A plug-in is an installed Python package with an entry point in the group `semantext.plugins`, named
`<kind>.<name>`, pointing at an object of that kind:

```toml
[project.entry-points."semantext.plugins"]
"place.board" = "semantext_board:BOARD"
```

The name is read from the package's metadata, so listing a plug-in runs none of its code. Nothing is fetched, and no
folder of loose scripts is ever loaded.

The object must say the same kind and name as its entry point (`kind = "place"`, `name = "board"`), or it is not
loaded. A name is one plug-in within its kind: an outside plug-in with a built-in's name is refused, so it can never
stand in for one, and a name that two installed packages declare loads neither until all but one are removed. `semantext.api.taken_names(kind)` lists the names already taken, every built-in's and every installed
package's, read from metadata, so a plug-in can avoid a collision before it ships.

An entry point whose name is not `<kind>.<name>` with an open or reserved kind is a problem, never guessed at.

### Its settings and reads: semantext-plugin.json

A package may declare its plug-ins' settings and what they read in one file, `semantext-plugin.json`, in the folder of
the module its entry point names (`semantext_jira/semantext-plugin.json` for `"semantext_jira.reader:SOURCE"`), listed
among its installed files. One file can declare every plug-in of the package:

```json
{"plugins": {"source.tickets": {
    "reads":    ["the tickets file you name, and nothing else"],
    "settings": [{"key": "tickets", "type": "path", "title": "Tickets file", "required": true},
                 {"key": "project", "type": "text"}]}}}
```

A setting's `type` is `text`, `path`, `paths` or `list`; it says how the Plug-ins tab draws the setting and how a
proposed change to it is labelled ("widens", "narrows", "unknown", "order changed"). A setting may give a `"default"`, and
`"widens": true` makes every change to it widen. The file is read as data, so the page shows a plug-in's settings and
reads before it is on, and no code of it runs to draw them. It is the package's word, not a fence (`semantext/manifest.py`).

### Keys no plug-in may have

Some keys of the sources file are **reserved**, compared without case (by Unicode case folding, so `Closed` and
`CLOSED` are `closed`): every key a built-in reader reads, and every key the closures are read from
(`manifest.CLOSURE_KEYS`: `closed`, `closed_names`, `closures_file`, `closures_key`, `closures_names_key`, and the
closures-file format's `schema`, `closed_paths`, `closed_paths_complete`, `known_closed_paths`,
`known_open_paths_near`), and the keys `closures_key` and `closures_names_key` name. A source whose `keys` name a
closures key is not added; a plug-in whose `keys` or `needs` name any reserved key is not loaded when it is turned on,
and a problem line says why; the page never proposes a change to one. A plug-in is given the person's closures in its
`ReadContext`, never as settings.

## Turning one on, at the console

**Installed is not on.** A plug-in is loaded only when the person has turned it on, and only at the version they
turned it on for:

```
semantext plugins                         every plug-in, where it came from, and whether it is on
semantext plugins enable <kind>.<name>    turn one on: typed at the person's own console
semantext plugins disable <kind>.<name>   turn one off
```

`enable` refuses in an agent's shell (the same markers the inbox uses for answering) and anywhere that is not an
interactive console, and asks the person to type the plug-in's name back. It also refuses until the person has named
their closed places (below). What is on is kept in `plugins.json` in the Semantext home, written only by `enable`, `disable` and
the page's turn-off; an upgrade of the package turns its plug-in off until it is turned on again. `disable` is not held to the
console, since it takes reach away.

**The limit of "typed at a console", decided:** this rests on the agent markers and on whether standard input is a
console. It bars an agent that follows the rules. It is no bar against a program that does not: one running as the
person can open a console and type the name, or write `plugins.json` itself.

`semantext plugins check` is for the conformance kits, which would check a plug-in against this contract. They are not
built yet, so it prints "Not checked" and exits 1. Not checked is never said as passed.

Which processes load plug-ins: the page's server (`semantext serve`) and the command line. **The card hook loads none**:
it never imports the registry, and a test pins the modules it imports.

### The Plug-ins tab: the page proposes, the console applies

The page's Plug-ins tab shows every installed plug-in, where it came from, whether it is on, its health, its declared
settings and reads, and the change log; none of it is asked of a plug-in. The page **turns a plug-in off**, recorded.
It **never turns one on** (it shows the `enable` line to type), and **never writes a setting**: a change from its
settings form, or a rollback of a settings change, is kept as a numbered proposal, labelled for the person to read,
and applied only at the console:

```
semantext plugins show <n> [--full]       the exact difference a proposal would make
semantext plugins confirm <n>             apply it, at the person's own console, as enable is
```

`confirm` applies a proposal only while the sources file is byte for byte what it was made on and no change has been
recorded to its keys since. The page proposes nothing in a sources file that is also the closures file (its
`closures_file` leads back to it), and writes none of its files
(the change log, the rotated log, the last-changes file, the proposals) through a link, a folder or a second hard link.
Every change is recorded in `plugin-changes.jsonl` in the Semantext home (`semantext/pluginpage.py`).

## Closed places must be named first

The person's closed places are folders nothing of Semantext's may read. They are named in the sources file, or in a
closures file it names, or both (the lists merge):

```json
"closed": ["C:\\Users\\me\\Private", "~/secrets-folder"],
"closures_file": "C:\\Users\\me\\closures.json",
"closures_key": "closed"
```

each a full path (a leading `~` is the user's home). Closures by **name** close a folder or file wherever it is: a
`"closed_names"` list, in the sources file or in the closures file (under `"closures_names_key"`, `"closed_names"`
when not given), in the closures-file format (schema `estate.closures/0`): entries with an `id`, a `form`
(`segment`, `segment-pair`, `segment-prefix-except`, `segment-or-dotted-prefix`, `substring`, `suffix`) and that
form's fields; `SECURITY.md`, "Closed names", gives the rules. A closures file that says the format's schema may also
say `"closed_paths"`, `"closed_paths_complete"` and `"known_closed_paths"`, and list a path as a record
(`{"path": ...}`). The format is read only in a closures file the sources file names: in the sources file itself those
keys mean nothing (the page says so), and the sources file keeps 1.3.0's rules (a path record there is unknown, as in
1.3.0). Nothing 1.3.0 read changes meaning, with one deliberate exception: a closures file in the closures-file format
(schema `estate.closures/0`), new in 1.4, is read by that format's rules. Where its complete list is not supplied, it
is read by the built-in card readers and the root rule as a lower bound (its known paths and names), and stays unknown
to plug-ins and the strict view; and its path records are read as its paths, where 1.3.0 found them unreadable. Every
other change closes more.

**Until the closures are known, every path is closed to a plug-in.** They are not known with no closures named at all
(no `"closed"` key and no closures file, or no sources file; **closed names add closures and never by themselves
make them known**, so a sources file with only `"closed_names"` is none named for a plug-in, as in 1.3.0); with a list or file that cannot be
read, is a closures file over 1 MB (the sources file has no such cap), holds anything but full paths or usable name entries, or gives a key twice; with a list given as
`null`; and, in the closures-file format, **while the list of closed paths is not said to be complete**: a plug-in is
judged by `closed_paths` only when it is a list, `closed_paths_complete` is exactly `true`, and every path of
`known_closed_paths` is in it. A named but incomplete list is unknown to a plug-in, never read as complete. While the
closures are not known, `closures_known()` is false, `is_closed_place` is true for every path, and `semantext plugins
enable` refuses, saying the true state: "name your closed places first" when none are named, the list being
incomplete, or the reason the closures cannot be used, with what fixes it. An explicit empty list is a statement that
nothing is closed, and is known.

There is one shared judgement of closed places, and a plug-in asks it rather than keeping its own:

- `is_closed_place(path, ctx=None)`: whether `path` is in a closed place (by path or by name), as written or with every
  link resolved, the Windows `\\?\` prefix taken off first. `ctx` is the read's `ReadContext`, or a Semantext home
  (0.1's form), or None for the default home. True for anything it cannot judge. A plug-in that prunes its own walk
  asks it of each folder: `ctx.closures` alone leaves out every closed name.
- `closures_known(ctx=None)`: whether the closures are named, readable and, in the closures-file format, complete.

## What a plug-in is given

### ReadContext

`semantext.api.ReadContext` is a frozen record of four fields, three given and one set when it is made:

- `home`: the Semantext home the page was started with, as text;
- `closures`: the person's closed folders as full paths, read **once for this build**, or None when they cannot be
  known to a plug-in (which closes every path);
- `names`: the person's closed names, each a `Name` (its id, its form, its literals as compared, and its regex), read
  with them. A context built by hand with `names=()` (the default) closes no name; one built with names that are not
  `Name`s (texts, records, a subclass of `Name`) is refused with a `TypeError`, and one whose fields, or whose names'
  fields, are set after it was made (`object.__setattr__` on the frozen record) closes every path: it is sealed once,
  when made, with a key of this process, and never sealed anew. The seal stops accidents; it is no bar to a plug-in in
  the same process that means harm (SECURITY.md, "Plug-ins are handed your closures");
- `seal`: set when the context is made, never given (it is not an argument of the constructor, and is left out of its
  repr and its equality): the keyed hash of the three fields above that `is_closed_place` checks.

Every outside source in one build is given its own sealed copy of one context, so they all judge against one reading
of the closures, and what one does to its copy never reaches another's.
The closures are not secret from a plug-in that is on: they are in its context so that it can ask.

### The read-only helpers

| Name | What it gives |
| --- | --- |
| `problem(source, line, kind, text)` | one problem record, `{source, line, kind, text}`, the text cut to 300 characters |
| `read_lines(path)` | `(line number, text)` for each non-blank line of a JSON-lines file, a leading BOM removed; a line over `MAX_LINE` (64 KB) gives `(number, None)`; a file over 16 MB is an `OSError` |
| `named_roots(ctx)` | the seats file's roots, `[{name, path, kind}]`, each path in full as the Places reader resolves it; a `"{home}"` root as one row per seat home in the group |
| `seat_rows(ctx)` | the seats in the person's group, `[{seat, home, groups}]`, by the Waiting reader's rules; `home` is None where that reader would not follow it |
| `inside_roots(path, ctx)` | whether `path`, as it leads now (prefix off, `..` worked out, every link resolved), lies inside a named root and outside every closed place: the same judgement the serve hook makes |
| `taken_names(kind)` | the names already taken (above) |
| `fingerprint(files, roots)` | the change-evidence digest, as the page computes it |

The seats file's base, and each home or root joined to it, are judged by one rule (`semantext/pathrule.py`), the same
for every reader, for these helpers, and for the card hook that gives a session its seat, and the same on every
system. The seats file itself is found and parsed one way by all of them: its path with the same `~` rule as a base
(`~` and `~/` are your home, `~name` is refused), a relative path taken relative to the folder of the file that names
it (the sources file, or the card hook's config), never to the working folder, read no further than 4 MB, and parsed as the person's own inbox
parses it, refusing a key given twice in one object, NaN or Infinity, a number out of its range, or half of a
surrogate pair; a seats file one of them refuses, all of them refuse. A path is read exactly as written. The rule refuses:

- a control character (a NUL, a tab, a line break, DEL among them) or half of a surrogate pair;
- a space before or after the whole path;
- a part ending in a dot or a space (Windows would open `teams.` as `teams`);
- a colon anywhere but straight after a drive letter at the start (a stream of a folder, not a folder);
- a path written with the `\\?\` or `\\.\` prefix, which turns off the path's own reading;
- a part that is a device name in the shape `os.path.isreserved` reads one: CON, PRN, AUX, NUL, CONIN$, CONOUT$,
  COM1 to COM9 or LPT1 to LPT9 (their superscript-digit forms too), in any case, then any spaces, then an extension
  or nothing (`nul`, `con .txt`, `aux  .d`). These are refused on every system, because many Windows versions read
  them as devices; recent Windows 11 does not;
- for a home or a root: a `..` step, or a drive, a root or a share of its own (a full path among them);
- for a base: a `..` step anywhere (so `~/../Other` cannot climb out of your home); one that is not a full path once
  a leading `~` is expanded to the user's own home (`~` and `~/` on every system, and `~\` too on Windows, where a
  backslash is a separator; elsewhere `~\x` is not expanded, and so is refused); `~name`, another user's home, is
  refused on every system;
- for the homes: no base given, or a base that is not an existing folder; then no seat's home is read, by any reader
  or the hook, and each says so once.

It does **not** refuse, and every reader therefore reads alike: a short (8.3) name such as `PROGRA~1`, a share as a
base (`\\server\share\x`), a format character such as a right-to-left override or a zero-width space, and a name that
differs only in case or in Unicode normalisation. Each helper reads only, and a file it cannot read gives no rows, never an error.

## Source

```python
class Board:
    kind = "source"
    name = "board"
    title = "Board"
    keys = ("board_file",)          # the keys of the sources file it reads
    needs = ("board_file",)         # optional: the keys it cannot run without

    def read(self, config, ctx):    # or read(self, config), as in 0.1
        ...
        return {"items": [...], "problems": [...], "off": False}
```

- `keys` are the keys of the person's sources file it reads. `config` holds those keys and no others. Each value is a
  non-empty text, or a list of at most 200 entries, each a plain text or number, or a flat record of at most 16 plain
  fields. A setting of any other shape is not given, and is a problem line of that source instead.
- `needs`, when declared, is part of the contract: the page reads it to say which settings a source that is off is
  missing (all of `keys` when it declares none).
- `read(config, ctx)` is given the build's `ReadContext` when it takes two positional arguments (or `*args`);
  `read(config)` is called with one. The signature is read once, when the plug-in is added. If it cannot be read
  (it raised, or was late), the read is not called for that answer, with a problem line, and it is asked again at the
  next answer: it is never called without its context by mistake.
- It returns a record: its data, `"problems"` (a list of `problem(...)` records, one for every line it could not use,
  never dropped in silence), and `"off": True` when a key it needs is missing.
- It opens files for reading only, and asks `is_closed_place(path, ctx)` before opening one.

## Place

```python
class BoardPlace:
    kind = "place"
    name = "board"
    title = "Board"
    page_module = "semantext_board/board.js"   # optional
    doc_type = "image/svg+xml"                 # optional, for documents by row

    def build(self, sources, ctx):             # or build(self, sources)
        return {"rows": sources["board"]["items"]}

    def resolve(self, row_id, ctx):            # optional, with check_bytes
        return "/full/path/to/row.svg"         # or (path, start, end), or None

    def check_bytes(self, data):
        return None                            # None: the bytes pass; anything else is why not
```

### build

The place is answered at `/api/v2/<name>`. `build(sources, ctx)` returns a record of what the place shows.
`sources[name]` is that source's answer for the person's group; nothing else of the argument is part of the contract.
**An outside place is given a copy** of every source's answer, so it can change nothing the page or another place
reads. `ctx` is the `ReadContext` of the home the page was started with; a build that takes one argument is called
that way. The keys `place` and `frame` of its answer are the page's own and are dropped. A built-in place's name, or
the person's own word for the whole page, cannot be taken.

### The page module

A place may declare `page_module`: the path of **one** ES module among its own distribution's installed files,
relative and with forward slashes (no `\`, `:`, NUL, leading `/`, or empty, `.` or `..` part), ending in `.js`. Once the
person has turned the place on, the server serves it at `/v2/plugin/<name>.js`, where the name must be a plain word
(lower-case letters, digits, `-` and `_`, starting with a letter or digit, at most 64 characters). Nothing else is ever
served: not a path from the request, not a file the distribution does not list, not one whose real path lies outside
the folder the distribution is installed in, and not a module over 1 MiB.

The page imports it when you go to the place and calls its exported `render(data, el, helpers)`:

- `data` is the place's JSON (build's record, without the frame);
- `el` is an empty element of its own;
- `helpers` are the page's text-only DOM helpers, `{h, text}`.

A module that throws shows a problem line in its frame, and the rest of the page goes on. The page's
Content-Security-Policy stops it loading anything from another site, and inline styles and scripts. **The helpers are
the easy path, not a sandbox**: a page module is code in the person's page with the page's whole reach (see "What a
plug-in may not do").

### Documents by row: the serve hook

A place may serve its own files to the page, one row at a time, at `/api/v2/doc/<name>/<row_id>`, by declaring
**both** `resolve` and `check_bytes`:

- `resolve(row_id)` (or `resolve(row_id, ctx)`, given the `ReadContext` the path is then judged against) gives the full
  path of one row of its last read, or None. It may instead give a **byte span**, `(path, start, end)`: a plain tuple
  (or list) of the path and two plain whole numbers with `0 <= start < end`, when the row is the bytes from `start` up
  to `end` of a larger file. Then only those bytes are read, checked and sent, and the span, not the file, is held to
  the size cap.
- `check_bytes(data)` is the place's own check of the bytes about to be served: None when they pass; anything else (cut
  to 200 characters) is why not, and the document is refused.

What the kernel does, in order:

1. The place name must be a plain word and the row id must be letters, digits, `-` and `_` (at most 128, never a dot,
   slash, colon or space), before anything is looked up. No part of the request reaches the file system.
2. The place must be one the person turned on, and must declare both calls.
3. `resolve` runs under the budget, and what it gives must be exact built-in types (a `str`, or a plain tuple of plain
   values); the path must be a full path with no NUL in it.
4. At serve time the path must lie, as it leads now, inside a named root and outside every closed place (the judgement
   `inside_roots` gives plug-ins).
5. The bytes are read **once**, from one descriptor: a regular file with one name on disk (a hard link is refused),
   at most 4 MB (or the span at most 4 MB; a span past the file's end as it is now is refused).
6. Exactly those bytes go to `check_bytes`. Only an explicit pass (it said None) serves them; a check that raises, is
   late, or gives anything else is a check that did not pass.
7. The answer carries the document policy (`default-src 'none'; style-src 'unsafe-inline'; sandbox`), with the type
   `doc_type` says: `image/svg+xml` unless it names `image/png` or `text/plain; charset=utf-8`.

**A stated limit:** the check and the open are two steps, so a folder swapped for a link between them is not seen. The
file opened is the path as resolved for the check, which narrows that window to a change of a folder on the way to it.

## Checker

```python
class MyChecker:
    kind = "checker"
    name = "my-checker"
    records = "runs/my-checker.jsonl under each folder in run_records"   # or None
```

A checker runs **outside** the package, and leaves run records the page only reads, never re-runs. `records` says
where it keeps them, or None when it keeps none. The record's shape is in [run-record-schema.md](run-record-schema.md).

## Budgets and caps

Every call into an outside plug-in (the import that loads it, a source's read, a place's build, a document's resolve
and check_bytes, and reading a signature, which can run its code) runs in a worker thread, under a budget:

| Limit | Value |
| --- | --- |
| time for one call, counted from when it starts to run | 5 s, or `SEMANTEXT_PLUGIN_SECONDS` |
| calls of one plug-in running at once | 4; one more waits for a turn up to its budget, and is late without running |
| calls of one plug-in waiting for a turn | 8; one more is refused at once |
| calls waiting for a turn, of every plug-in | 32 |
| threads of calls alive at once, late or not, of every plug-in | 16; while 16 hang, every plug-in's call is refused |
| problems kept from one answer | 200 |
| characters kept of each problem field | 300 |
| one answer, written as JSON | 2 MB |
| every outside answer one page is built from, together | 8 MB |
| one served document or span | 4 MB |
| one page module | 1 MiB |

A call that is late is a problem and its answer is not used. **A thread cannot be killed**: a late call keeps running
in the background until it returns. Whatever a plug-in raises in the worker (`SystemExit`, `GeneratorExit`,
`asyncio.CancelledError`, its own `BaseException`) is caught there and said as a problem; the person's own Ctrl-C
arrives on the calling thread and goes through. A plug-in that fails, or answers over a cap, costs only its own part
of the page.

**Attributes are read once.** At load, every attribute the kernel reads (`kind`, `name`, `title`, `records`,
`page_module`, `doc_type`; `keys` and `needs` as tuples of plain values; `read`, `build`, `resolve`, `check_bytes` as
the bound methods) is read through one guarded accessor into a snapshot, and must be a plain value. After that only the
snapshot is read. One that raises when read is a problem line, and that plug-in is skipped.

## What a plug-in may not do

These are the laws. They are checked on a plug-in's code path, never inherited: the kernel holds a plug-in at arm's
length (the budgets, caps, copies and checks above), and **none of it is a sandbox**. A plug-in is code in the person's
process, with its whole reach, and a page module is code in the person's page.

- **Read only.** It opens the person's files for reading, and writes nothing of theirs.
- **Start no process.**
- **Set the person's text as text**: in a page module, through the helpers (`h`, `text`), never as markup.
- **Read nothing in a closed place**, and nothing at all until the closures are named: ask `is_closed_place(path, ctx)`
  before opening a file. (The kernel enforces its own side: the serve hook judges every path itself.)
- **Change nothing through the page.** A page module shows its place; answering requests, teaching or changing rules
  and changing settings are the person's. A change whose `Referer` is a page module's path, or that the browser marks
  as anything but a plain fetch, is refused; a module calling `fetch()` from inside the page is not told apart by that.
- **Rely on nothing of Semantext but `semantext.api`**: nothing else of the package is public.
- **Take no name** a built-in or another package has (a built-in's name is refused; one two packages declare loads
  neither), and claim to be no built-in: a package calling itself `built-in` is an outside plug-in all the same.

The closures, `plugins.json` and the sources file are files an agent can edit, and "typed at a console" bars only an
agent that follows the rules. A plug-in that does not ask `is_closed_place` is not stopped. Install only what you would
run yourself.

## Not here yet

The evidence policy (which files a change card may cite) is not a plug-in kind yet. It lives in
`semantext/sources/evidence.py`, one module per way, and only the `fingerprint` that applies it is exposed.
`fingerprint(files, roots)` reads through the page's way, so a file no repository's git index lists gets no digest
("unknown").
