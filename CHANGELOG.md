# Changelog

All notable changes to Semantext are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.8.0] - 2026-11-16

### Added
- **`semantext proxy serve`** starts the proxy at your own terminal (refused in an agent's shell, as far as Semantext
  can tell one), with your card and the space's blocks pinned as they are. One proxy runs per folder and per port.
- **You can answer the proxy.** `semantext proxy asks` lists what waits for your word (never the call's input), and
  `semantext proxy answer ASK yes|no|revoke` answers it from your own terminal. An ask of an earlier run of the proxy
  can never release a call and, apart from the moment a new proxy starts (docs/proxy.md, Limits), cannot be answered;
  nothing is answered while the record's chain is broken. The listing also shows a yes not yet
  used, with the line that takes it back; that line carries the `--home` and `--proxy-home` you gave, quoted for
  PowerShell on Windows or a POSIX shell elsewhere, and a folder whose name looks like a key is shown as
  `"<your --home folder>"` instead.
- **What a yes does, said plainly.** A yes counts once, in the chat it was asked in, until its ask runs out. The held
  turn is sent on at that chat's next message when every call of the turn has a yes (all its asks are spent together,
  or none), or else the call goes through when the model makes exactly that call again; neither while your newest
  message in that chat names one of the call's acts other than as a plain go (see Fixed). The page's note after a yes and `semantext proxy answer ASK yes`
  now say this; they used to say only "when the agent makes it again". docs/proxy.md has the details and the cases
  where nothing is sent.
- **You can answer the proxy from your page.** Waiting has a section, "The proxy holds": each call the proxy keeps for
  your word, with the agent, the tool, why it is held and the minutes left (never what the call was given, never your
  words), and **Yes once**, **No**, or **Revoke** for a yes not yet used. It is the command's own answer, sent from the
  page by one press; it reads again whenever Waiting does, says in plain words when no proxy has run, when none is
  running and when nothing waits, and says why an answer was not taken (an earlier run, an unknown ask, a broken
  record, a stopped proxy). It is held like an answer to a card, and more: the page's header and own Origin, a Referer
  naming one of the page's own addresses, a same-origin plain fetch, nothing from a plug-in's page module. Limits,
  stated in docs/proxy.md: a program on this machine that sends those headers can send it too (SECURITY.md), and the
  record does not say an answer came from the page.
- **Try a message reads clause by clause.** Beside the quick reading, each clause is a chip with the acts it names and
  its time word, and every act the words name has the reader's advice, with its rule and the words it rests on. The two
  readings are headed by what each reads ("Clause by clause: what it asks for, act by act" and "The quick reading: what
  kind of message this is"). A box takes the agent's last offer (optional), so a bare "yes" is read as answering it;
  the advice made from the offer is withdrawn, with a note, when the offer is no longer in the box. An ask whose words
  appear to say go reads "your words appear to say go: confirm", never as a go; a material act is never shown as
  allowed.
- **`POST /api/read`**, the page's route to the reader: `{message, offer?, acts?}` in, the clause readings, the advice
  per act and the acts' meanings out (`reading.report`, which `semantext read` now prints from too). It changes nothing
  and writes nothing. The words go in the body, never in an address (a query string is refused); a body over 100,000
  bytes, a request from another page, from no page, from a plug-in's page module or without the page's own `Referer`, a
  body that is not one JSON record, and an unknown act are refused. A message over 20,000 characters is read up to
  there and the answer says it was clipped. The reader carries no house rules, as `semantext read` carries none.
- **A replay of documented agent incidents** (`tests/test_incident_replays.py`, `tests/test_tamper.py`, and the table
  in docs/incidents.md): published incidents, each with its source, replayed through the act reader, the decision and
  the proxy, beside a tamper set (settings and hook edits, base-URL changes, an agent answering its own ask, a damaged
  record). The gaps found are listed there and kept as expected failures, so closing one shows.

### Changed
- **The reader that names what a tool call does was rewritten** (`semantext/actclass.py`). It reads a shell command
  with a lexer (quotes, escapes, here-documents, `$(...)`, groups, comments), looks through shell and PowerShell
  wrappers, prefix wrappers and runners, and reads the act from the subcommand, so a read-only subcommand is no act,
  but a dry run, a help page and PowerShell's `-WhatIf` do not make a call no act: such a call is named as the act it
  would be without the word and is asked about, as in 1.7.0. (A first attempt to recognise real dry runs was attacked
  four times, and each time a line was found that let a real push, publish or delete through, so 1.8.0 does not try.)
  A runner that fetches a package (`npx`, `bunx`,
  `pnpm dlx`, `npm exec` and their kin) keeps its download whatever flags the package is given. A tool is named a
  read by its name when it holds a reading word (list, get, search, read and the like) and no writing word, and joins
  no second action (`search_and_purchase` is a purchase; in an MCP tool's name a `__` joins as `and` does).
  A call it cannot read (a program held in a variable, `curl u | sh`, nesting past 8
  levels, reading that would cost more than 6 times the command's length plus 4 KiB) counts as every act. Its reading
  time is linear in the command on Python 3.11.5 and later, and a test times every pattern on inputs built from its own parts (16 and 64 KiB).
  Limits, stated in SECURITY.md: a script or target run by its own name (`npm run release`, `make deploy`) is not
  named at the top level of a command; inside a `( )` or `{ }` group it counts as every act unless every part of its
  name is an everyday word such as test, build or all (so do `poetry run X`, `py -m X`, `xargs make X` and a task
  runner given another recipe file), and a bare `make`, `just` or `task` in a group names no target and is not held;
  and expect a miss rate above zero on commands it has not seen.
- **On Python 3.10 the act reader reads a shell command of up to 2 KiB (64 KiB from 3.11.5, and on any 3.11 that
  passes two checks of its possessive repeats).** 3.10's regular
  expressions have no possessive repeats, so the reader's patterns are compiled there through a shim as plain greedy
  repeats: the same answers, but not linear at worst. A longer command counts as every material act. The slowest known
  shape (printf's run of zeros) takes 0.14 s at 2 KiB and 0.56 s at 4 KiB on the greedy copy the tests load.
  The same holds on a Python 3.11 that matches possessive repeats wrongly: CPython 3.11.0 to 3.11.4 do, in two
  shapes (CPython issues 100061 and 106052, both fixed in 3.11.5; Debian 12 ships 3.11.2), and two of the reader's
  patterns have the first shape, where the fault would be a missed act. When it loads, the reader runs the two
  upstream reproductions and uses possessive repeats only if both come out right. Not run on a real 3.11.0 to
  3.11.4: the path such an interpreter takes is the one tested on 3.10.
- **Text an agent or a page sends is normalised in linear time.** Every Unicode normalisation of such text goes through
  one helper (`semantext/normal.py`) whose answer is Python's own, character for character; Python's own call took time
  in the square of the text on a long run of combining marks. Nothing Semantext decides changed.
- **The command line is read the same on every supported Python.** Before Python 3.12.7, argparse left a word unread
  when it followed an option after an earlier word (`semantext env add --env work an-id`), and refused the line. A
  sub-command left with unread words now reads its part of the line a second way (options and words intermixed), and
  keeps that reading only if it reads every word. It also now reads, on every Python, one kind of line that every
  Python refused before: the words of one many-word argument split by an option (`semantext backtest a.jsonl --env
  work b.jsonl` reads both files). A line with more words than the command takes is refused as before.
- **The tests need the `test` extra, and CI installs it.** The proxy's tests use the Anthropic SDK as their client and
  skip themselves without it, so until now they never ran in CI. Install with `pip install -e ".[test]"`; the extra
  holds pytest, the Anthropic SDK and, on Python 3.10, `tomli`.
- **The reader is on the page: one reader for the command line and the page.** Home's message box used to draw four
  kinds from word patterns written in the page's own JavaScript, which could disagree with `semantext read`. It now asks
  the real reader (`semantext/reading.py`) and draws what it answers: each clause with its kind, acts and any time word
  kept as written, and the advice for each act under it. Typing waits for a pause (400 ms) before it asks; it says
  "Reading…" while it waits, and any failure plainly ("Could not read it: …"), with no reading drawn in its place; an
  older, slower answer never replaces a newer one. The words now go to Semantext on this machine to be read (in a request
  body, never an address), so the note under the box no longer says nothing you type is sent; it says where they go.
- **A read that fails with a body that is not JSON is said, not thrown.** The Rules band's reads (and the reader's) check
  the status first, and then a body that is not JSON (a proxy's page, an empty reply) is reported as "the server's answer
  was not readable" or by its status text. Before, `r.json()` ran first and a non-JSON error page surfaced as a
  JavaScript parse error.

### Fixed
- **Your newest words win over an earlier yes.** After you said yes to a held call, a later message of yours in that
  chat that withholds the act ("wait, do not delete anything") did not hold it: the kept turn was sent on at that
  message, and the same call made again went through (1.7.0 did the same). Now neither happens while your newest
  message, written after the held turn, names one of the call's acts other than as a plain go. The message is read for
  each act of the call, and a go in a message that also withholds something is not a plain go: so "go ahead and push.
  do not delete anything" holds `git push && rm -rf logs` (and a call that only pushes too, which then asks again),
  and so do "skip the delete",
  "I forbid deleting" and "delete them tomorrow"; "yes, delete them" does not. Then the kept turn is not sent and the
  request goes on to the model, a call made again is held on the same ask, and the yes is not spent; it goes through
  once after a later message that does not name the act that way, or `semantext proxy answer ASK revoke` takes it
  back. A message naming none of the call's acts ("ok, go ahead now", "thanks") leaves the yes, and words only ever
  hold, never release. Words typed beside a tool's result (a client sends what you type while a tool runs inside the
  message carrying its result), and the text after a `<system-reminder>` tag that is never closed, are now read for
  holds too, on both paths and with no yes as well, never as a go: a "don't push yet" typed while a tool ran was not
  read before. The sentences the client itself puts around such words (Claude Code's "The user sent a new message
  while you were working:" and its closing paragraph) are cut first, because read as words they name a send; and
  what you typed (each text block that begins with that client's lead line) is read before the client's notes and
  other sessions' messages, so those do not crowd your words out of the reading. SECURITY.md has the caps and the
  limits.
  Limits, in docs/proxy.md: the newest words hold only acts the reader names, so a call held by a gate
  whose act it does not name (`./deploy.sh`, `npm run release`, `make deploy`) is not held by them; a bare "stop" or
  "wait" names no act; a word for the act the reader does not know ("nuke", "get rid of") names nothing; a withhold
  by its object ("push it and keep the logs", "just push" for a push and a delete) names no delete; a hold after the
  first 20,000 characters or 400 clauses of a message is not read; a sentence about the past that names the act holds the call.
- **Cutting the harness's reminder sections out of a message takes time in proportion to it.** A `<` followed by a
  long run of white space that opens no tag took the square of the run (8 s for 32 KiB of spaces, measured), on
  every request that carried the message; 1.7.0 did the same. The pattern now makes one pass and finds the same
  tags.
- **A kept turn that makes the same call twice says why it is not sent.** It shares one ask, and one yes releases one
  call, so the turn is refused; the refusal said "the space or its gates changed", which was not so. It now says the
  turn makes the same call twice, and the call made again goes through once on the yes.
- **A yes belongs to the chat it was asked in, with or without a session header.** Two chats that start alike (same
  system prompt, same first message) used to be one conversation to the proxy, so a yes in chat A could release the
  identical call in chat B. Each ask now keeps a keyed digest of the history it was asked after, and a yes releases a
  call only in a request whose history begins with exactly that. With Claude Code's session header a chat is its
  session and its messages; without one it is also its whole system and its tools list. A cache marker is ignored only
  where it is a marker. Kept turns are stored per chat too, so one chat's held turn no longer overwrites another's.
- **The proxy's record decides a yes.** A yes counts only while the record's last word for that ask is yes and no spend
  of it is on the record, so a crash between the record and the asks file cannot release a call after a revoke, or the
  same yes twice. A held turn is sent on only if every one of its asks is still a live yes when it is spent; before, an
  ask revoked in between was skipped and the whole turn went out.
- **A turn is held with all of its asks or none.** A turn whose new asks would pass the cap (20 waiting, or 5 for tools
  the agent may not call) is refused and opens no ask, so a long turn no longer leaves 20 stale asks that shut the agent
  out for an hour.
- **The asks file is read and written with the store's retrying tools,** so a page or a terminal reading at the same
  moment no longer makes a yes, a revoke or a new ask fail on Windows.
- **A stopped proxy is known to be stopped.** Whether a proxy runs is found by trying its lock, which the system lets go
  when the process ends, not by reading its run file. The page says "No proxy is running from this Semantext home, and
  what it held went with it", `semantext proxy asks` says no proxy is running, and an answer is refused. While a new
  proxy starts, nothing of the run before it is listed or answered (but see the limits in docs/proxy.md).
- **The proxy's record heals one interrupted write.** A file exactly one sealed line ahead of its head, following it,
  is rolled forward. A last line without its newline, or a head that is not a whole count, is a broken record (it was a
  traceback for a bad head before).
- **Keys stay out of what the reader shows.** The check for a key's shape now also reads every non-ASCII character
  that is not white space as a hyphen, so a key spelled with a look-alike hyphen is withheld. The reader checks each
  clause as you wrote it as well as normalised. At the 20,000-character clip it reads exactly to the clip again (a hold
  written in the last word is read) and shows the clause that runs to the clip with its last word withheld. A key whose
  name and value fall in different clauses withholds every clause. `POST /api/explain` no longer carries a key in the
  message copy of its quick reading or as a sender's name. The check of a JSON web token takes linear time (a long run
  of `eyJ` had stalled the page's server for 10 to 18 seconds), and the proxy's scan of inputs over 96 KiB finds a
  token after a long run of token characters again.
- **A secret typed on the command line is cut from what the command prints.** The values you typed that look like a
  key, a token or a password are collected and every spelling of each is cut from stderr and, when the command fails,
  from stdout. `semantext env new` refuses a title that looks like a key, and says why without repeating it.
- **A key typed in the wrong place is not printed back.** `semantext read --act VALUE` echoed an invalid value through
  argparse's "invalid choice" message, so a key typed there reached the screen and any log of it. `--act` now refuses a
  word it does not know without repeating it and lists the acts, and every argparse error of the command line (an invalid
  command or choice, an unrecognised argument) is scrubbed the same way when what it quotes is key-shaped. A word that
  is not a key is still named.
- **The page no longer drops what you have selected when it draws again.** It draws again every ten seconds, when the
  window gets focus, and when an open Waiting or Rules band or a drawer reads again; each draw kept your place and your
  caret but lost a selection (in a box it collapsed to the caret, in a card's words it vanished), so copying a line from
  a card meant racing the clock. A box now keeps its start, end and direction, and words selected on the page are put
  back on the same words after the draw. A draw whose output reads the same replaces nothing. The draw is not held back
  while you select: a held card could show something already answered. Only a selection you hold at that moment is put
  back, so words you released stay released; words that changed, or that now stand twice, are not guessed at and the
  selection is let go. A read that differs only in the machine's busy and free readings is no change. A selected ID that
  Semantext offers for Ctrl+C (when your browser refuses the clipboard) is no longer dropped by the button writing the
  same ID again 1.5 seconds later. Limit: a selection whose ends sit in no card, row or other part with its own key is
  not put back.
- **Plug-in places keep a selection through a late draw.** A module whose `render()` is async is now waited for, and a
  render that throws or rejects leaves a problem line. A late draw puts a selection back only if it lay wholly inside
  what the module drew, reads exactly the same, and you have not changed it meanwhile; what you did in the place while
  it waited stays yours. A plug-in place may not take a name the page answers at, nor the name of a JavaScript object's
  own property (docs/plugin-api.md).
- **A refusal says what the act is.** Starting or answering the proxy from an agent's shell was refused with "Only the
  user changes their rules". The guard is the same for every act of yours; what it says after the refusal now fits the
  act (the proxy's two, keeping or forgetting what was heard, accepting a proposal, settings, features and the model),
  and the acts that change rules say what they always said.
- **A very long own inbox stays fast and bounded.** Your own inbox had no cap: thousands of requests, or requests with
  very long texts, were all read into every page build (5,000 requests of 2,000 characters made a 33 MB answer and took
  about 2 s) and every line of them went into the card hook's work. The page now draws the newest 100 cards of each kind
  (waiting, parked, done) and says "N more waiting requests not drawn here" in plain words, on Waiting, on the Home band
  and in the machine's own section; the numbers it shows (the bar, the counts, `semantext statusline`) are of the whole
  inbox, and as you answer or park the newer cards the older ones are drawn. A field over 2,000 characters is drawn
  cut, with how many characters were left out, and the card says which fields were cut; a command drawn cut is not
  offered to copy, and its warning is still worked out from the whole command. The Record draws the newest 500 answers
  and says how many more there are. The card hook reads the file once instead of three times, makes a line only for the
  few it can show, cuts a very long title so it cannot hide the lines after it, and says "N more: run `semantext
  inbox`". Nothing in the inbox file is changed. Limits, stated: the file is still read whole, once per page build and
  per prompt (31 MB took about 0.15 s); the Map still lists every agent that filed a request; a line a hand made far
  larger than the file's other lines makes that read slower in proportion to its size.
- **A hand-made huge list of projects is capped the same way.** With no setup, Projects and the Map drew every name in
  `work/projects.json`, a list anyone can edit by hand. The list is now made distinct first (the first spelling, at its
  first place, stays), and they draw the last 200 names in it, in the list's order, saying "N more project names in
  your list of projects not drawn here: the last 200 in your list are shown" on the page and as a problem line. The same
  name in two cases is one project. Limits, stated: the work store still checks a project against the whole list (a cap
  there would make a real project unknown), so the Work page's `known_projects` is whole; projects from your bound
  folders and the sessions agents were seen in are not capped by this.
- **A parked request is shown as parked everywhere it is listed.** In 1.5.1 a request you set aside still read as open
  to the page's data and to the asking agent. It stays open for its asker (an answer still counts), but it no longer
  waits: the note before the card puts it under "Set aside by the user" with its own count, the start screen and
  `answers` (the command and the tool) name it as parked, `semantext inbox` marks it, the doctor counts waiting and
  parked apart, the Agents preview and the feed leave it out of "waiting", and `/api/inbox` and the decision counts give
  it its own `parked` list and count.
- **`semantext statusline` counts this machine's own inbox.** With a setup named (a seats file and an inbox folder) the
  requests agents filed in this machine's own inbox have their own section on the page and count as waiting there, but
  the status line read the setup's cards only, so it said less than the page. It now says the page's number, with the
  newest of both; a parked, answered or withdrawn request is not counted, and an own inbox that cannot be read is said
  on the line, never taken for an empty one. Limit, stated: where the setup's Waiting is off or cannot be used, the line
  still says "unavailable" (as before), though the page still draws the own inbox.

### Known limits
- **The proxy.** Tools that Anthropic runs on its own side (web fetch, web search, code execution, the MCP connector's
  remote servers, tool search) have finished before the proxy sees the answer, so it cannot hold them. The record's
  chain catches a line edited or moved out of order, not a cut-off tail or a whole rewrite by someone with the file's
  rights, and it has no anchor outside its files. An agent with your file rights can answer its own ask through the
  library. A gate that names acts still holds every call; making it hold by act alone would release every call that
  has no class. "Your own terminal" is a test Semantext makes, not a guarantee. These, and the start window and the
  lock limits, are in docs/proxy.md and docs/incidents.md.
- **The act reader.** A script or target run by its own name, a file handed to an SQL client, text piped from a file,
  and an act done by a program the command starts are not named, so your words do not hold them; your space's gates
  decide them. A project whose `build` or `all` target ships something is let through in a group, and so is a bare
  `make`, `just` or `task`, whose default target is not named. On Python 3.10 a
  command over 2 KiB counts as every act. Expect a miss rate above zero on commands written by someone new.
- **Keys.** A message with a key inside one clause and also a name and value split across clauses withholds only the
  clause with the key, and a value split by a comma can show its second part. The hook's own check of a relayed
  sender's name does not fold look-alike hyphens (that name reaches only the feed, which does). A typed secret shorter
  than 4 characters is not cut, nor is the stdout of the commands a reader waits on; a JSON web token whose own `eyJ`
  is the ninth or later in one run of token characters is cut only with what is glued before it. A password written
  as `password is: X`, `password is - X`, `pw is X`, `pwd: X` or `passcode: X` is not known for one, so `semantext
  read`, `POST /api/read` and the page's clause readings show it back.
  SECURITY.md lists them all.
- **Reading cost.** The reader reads an offer once per reading, but on the text as NFKC widens it, so a message or an
  offer made of a character that widens a lot (U+FDFA becomes 18 characters) can take about a second each at 20,000
  characters: 0.8 to 0.9 s for such an offer, 1.9 to 2.0 s with the message the same, every act asked about (measured
  on Python 3.11 and 3.14 on one machine).

## [1.7.0] - 2026-11-06

### Changed
- **Waiting opens in place on Home.** The Waiting band is now a button under a heading: it opens below itself and shows
  the cards that wait for your word, newest first, with their answers, and a link to the whole place (parked and done).
  Before its cards are read it says "Reading your cards…", never "nothing"; if a read fails, it says so, and keeps the
  cards last read marked as such. Escape closes it and puts focus back on the band.
- **Rules opens in place on Home, and shows one rule beside the list.** Your rules, grouped as in Rules (this setup,
  each agent's own, everywhere), each marked when it is off; pick one and it opens beside the list in your words, with
  when it applies, where it came from and how many of your corrections test it. The band only reads: switching,
  editing and adding stay in Rules, one link away. Agents, Work and Record still go to their places (the app design's
  build step 2). Waiting's band also shows this machine's own inbox, which its count includes; an open band reads
  again every ten seconds; an Escape a drawer has used does not close the band too.

### Added
- **The reader: your message read clause by clause.** `semantext read "your message"` now shows each clause with its
  kind (instruction, keep going, yes, question, option, condition, praise, hold, ask first, yours to do, note), the acts
  it names and its time words kept as you wrote them, and then what your words advise for each act. `--act` asks about
  one act, and `--offer` gives the agent's last offer, so a bare "yes" covers only what was offered (and the offered act is shown).
- **Your words never pass an act that leaves, spends or deletes.** For publishing, pushing, deleting, sending, paying
  or downloading the reader says at most "your words appear to say go", which fills the ask in for you to confirm in
  one step; it never says allowed. Anything it cannot place (a condition, a later time, an option, a hold anywhere in
  the message, part of the message unread) asks. Reading advice can only make a decision stricter, never looser.
- **The proxy, v0, as a library module** (`semantext.proxy`): Anthropic Messages on loopback, with a strict request
  gate, one assembler for streamed and whole replies, a decision that holds a turn whose call a gate matches, asks
  bound to the exact call, replay once answered, and a hash-chained record kept before anything is emitted. Your latest
  words, read by the reader, can also HOLD a call whose act they hold, question, offer as an option, set a
  condition on, defer, keep for you, or name without plainly saying go; only your yes on its ask releases it, once. A
  plain go for now ("Publish it", "Publish it tonight") adds no hold: your space's gates decide that call as before. **Not yet usable on its own:** there is no command to start it and no channel yet for you
  to answer its asks from the app or the command line, so a held call stays held. Both come next. See docs/proxy.md.

## [1.6.2] - 2026-11-03

### Fixed
- **The key-shape check no longer stalls on a long line.** Its arm for a password in a URL tried a long run of letters
  from every start: 20,000 letters took about 2.5 s and 80,000 about 32 s, holding every thread, and it runs on cards,
  feeds, the model point's card and prompt (twice) and more. The URL's scheme is now bounded at 32 characters:
  100,000 characters take well under a second, a password URL after a long run is still found, and nothing it caught
  before is missed (Koinos X1; checked by Orithises: 0 differences on 6,000 random strings). Limit, stated: a scheme
  whose last 32 characters hold no letter is not found; no client resolves one.

## [1.6.1] - 2026-11-03

### Added
- **Prism: Semantext's identity, and its home.** The page opens on Prism: one message goes in, and what it means comes
  out as labelled rays (a question, a suggestion, a time word, something that needs your word), drawn in order. Below
  it, your spectrum: Rules, Agents, Work, Record and Waiting on you, each opening the place that holds it, with
  Waiting's count in rose (rose always means you). The reading at the top is an illustration of how Semantext reads,
  and it says so; nothing typed there is sent anywhere.
- **The Prism look everywhere:** night is the default ground and paper the light one (it follows your system, and the
  theme setting still wins); five colours name your five parts; the mark (a beam in, three rays out) leads the bar.
  The type is Sora and JetBrains Mono where they are installed and your system's faces otherwise: nothing is fetched
  from outside your machine. The paper colours are chosen so every text reaches 4.5:1 and the focus ring 3:1 (from
  Koinos's attack of the first Prism page, which measured the first ones short). The Waiting band says "…" until
  its count has been read, and marks a count that could not be refreshed, instead of a false "0".

### Changed
- **Fewer tabs.** The bar holds Home, Waiting, Work, Record and Rules; Today, Projects, Documents, Diffmap, the map,
  Plug-ins, Settings and any place a plug-in adds are under More. Every address still works. A bare address opens on
  Prism (it opened on Waiting, or Today when nothing waited). On a place under More, More shows as where you are.

### Fixed
- **A disguised key is caught too.** Key-shaped text in the card, your words or the model's answer is now checked as
  written and once folded as a reader takes it (compatibility forms, invisible format characters, look-alike
  letters), so a fullwidth letter, a zero-width space or a soft hyphen inside a key does not hide it. A key broken by
  ordinary spaces is still not caught (stated in docs/model.md). From Orithises's re-check of 1747bdb (G1).
- **The wider key check is a check, not a comment.** Long key-like runs are withheld whenever the model's address is
  not the literal loopback (G2).
- **Renaming or moving a file the call was not given into its own place is a read** (M-SCOPE), like a copy; moved
  anywhere else it is a change to your state (M-STATE), by `os.rename`, `os.replace` and `shutil.move` alike (G3). `sendmsg` to a name is refused before any lookup where the
  platform has it (G4). The M-RATE message says where a stamp from a clock that was set ahead is kept (G5). The base
  socket type's limit is named in docs/model.md.

## [1.6.0] - 2026-11-03

### Added
- **A model on this machine, asked only by you (the model point, first slice).** `semantext model set` names one
  runtime you started: its address, which must be the literal `127.0.0.1` or `::1` with a port (a name, even
  `localhost`, `0.0.0.0`, any other spelling of loopback, a name or password in the address, and https are refused),
  the model's name, its ID as `ollama list` shows it (the manifest's digest), a budget (default 60 s), a token cap
  (default 512), what a differing digest does, and your own cap on asks per hour. `semantext model ask` sends your
  card and your words to it, from your own terminal only, and files each answer in your inbox as a proposal labelled
  MODEL, with the name, version and digest from your settings, never the model's own words for itself. A proposal is
  never a rule, an answer or a decision: you mark it Noted or Set aside. `semantext model check --file [--manifest]`
  checks the model's files on disk: the manifest against your ID, the weights file against the blob the manifest
  names. See docs/model.md.
- **The guards on a call, each refusing with its rule's id** (M-HOST, M-SCOPE, M-SPAWN, M-STATE, M-LATE, M-TOOL,
  M-QUOTE, M-SIZE, M-LABEL, M-ID, M-FLIGHT, M-TOKENS, M-HOOK, M-RATE; M-BUDGET is judged at the runtime, by the kit):
  one address, no redirect, no proxy; while a call runs, every connection, file open, listing, write and process start
  by the call's thread, or a thread it starts, is watched and refused outside what it was given, including by a thread
  it leaves running; no digest of yours, no call; at the budget or the token cap the connection is shut; one call at a
  time, and after a cut call the next waits out one budget, in this process or the next.
- **The kit** (`semantext.modelkit`): a fake runtime that counts its own tokens, connections and requests, a scripted
  provider, and planted-bad providers for each of Koinos's rows (PB01 to PB16) and Orithises's arms, each with a
  must-pass partner beside it. No real model runs in the tests.

### Changed
- **`record topics` checks the model's version against the digest you named**, when your model settings name that
  model: refused, or flagged, as they say. With none named it says the version is the runtime's own claim. Each
  topic line keeps which (`identity`). Until now the version was the runtime's word with nothing to compare it with.
- `OllamaReader` reads the runtime's model list through one method, `_tags()`, which a stricter provider replaces, and
  keeps the full digest the runtime reported beside the short version.

### Fixed (an independent review of the first slice, before release)
- **The watch judges only the call's own thread and the threads it starts.** It was process-wide: a thread that
  other code started while a call ran (the page's server answering a request, a plug-in) was refused its file reads
  and failed the call. Now no other thread is judged; a thread the watch cannot follow (`_thread.start_new_thread`)
  is refused (M-SPAWN). The call's own threads are followed on every supported Python: on 3.10 to 3.12, which
  announce no new thread, a provider's child thread was not watched at all (a re-check read a file outside the call's
  reach on 3.11). The watch now follows a thread at `threading.Thread.start` itself.
- **The wait after a cut call holds across processes.** Each `semantext model ask` is a new process, and the wait was
  kept only in memory, so it never applied. The time of the last cut is now kept in `state.json` as `model_cut` (the
  address and the time, nothing of the call), written by Semantext itself. A stream the runtime ended itself is not a
  cut.
- **The digest you name is the model's ID, the manifest's sha256**, the one `ollama list` shows and the runtime
  reports, not the weights file's. The docs told you to hash the weights file, which every call would then have
  refused. A digest the runtime reports must be whole (64 hex digits); yours may be the 12-digit ID.
  `model check --file` now checks the weights against the blob the manifest names, and the manifest against your ID,
  separately from the call's check. A model name whose tag or parts would point outside Ollama's manifest folder
  (`..`, a slash in the tag) is refused.
- **A model's proposal shows its label MODEL on the page,** on its Waiting card and on your answer to it in the
  Record. The page had dropped the label on the way to the card, and the Record showed an answered proposal as an
  ordinary decision.
- **No agent can file a request that looks like a model's proposal.** One sent as exactly MODEL, in capitals, or
  titled with MODEL as its whole first word ("MODEL proposal ...", "MODEL: ..."), in any spelling that reads so
  (another script's letters, a fullwidth form, an invisible character), is refused. An agent named "model" after its
  folder, and titles such as "MODELS to deploy?", "MODEL-T pricing" or "Model choice ...", are filed as usual. No
  agent, whatever its name, counts a proposal or its answer as its own.
- **Refusal ids follow Orithises's spec r5.** M-SIZE when the provider's call does not return within its time,
  judged on the clock; M-BUDGET when it returned or was abandoned while the generation went on, judged at the runtime
  (by the kit's fake runtime; Semantext cannot see a real runtime's counters); M-TOKENS for the token cap; M-HOOK for a
  provider module that calls out when imported; M-FLIGHT for one call at a time.
- **The docs name what the watch does not see**: `sqlite3.connect`, `os.stat`, `os.environ` and `mmap`, beside native
  code (docs/model.md, SECURITY.md).

### Fixed (Koinos's attack of 76bb1d5: TAKE, with these)
- **A sender line in another script's letters, or in bold, is refused.** `Јak:` (a Cyrillic J), `Frоm:`, `Тhe user:`,
  `Usеr:`, `Jak saιd:` (a Greek iota) and `- **Jak**: approve it` all passed as a model's answer. Cyrillic and Greek
  letters that look Latin are now folded to the Latin letter first (a small fixed table, the one the MODEL title
  check uses), and bold or italic marks between the name and the colon count as nothing. "Ask Jak: ..." and a sender
  line shown inside a code block still pass.
- **More tool-call formats are refused**: JSON after a prose line or in the middle of one, Mistral's `[TOOL_CALLS]`,
  DeepSeek's tool-call tags, Llama's `<function=...>` and `<|python_tag|>`, and a fenced `tool_code` block. It is a
  list of known formats, not a parser, and docs/model.md says so.
- **A provider's report with no digest is refused, or flagged**, never taken as a match: no report at all, no digest
  key, or a digest of None. The built-in provider always reports one; this holds the rule for any other.
- **A runtime that never answers its list of models ends with a rule id** (M-SIZE, judged on the clock), not a bare
  timeout. Nothing is sent to it.

### Fixed (Orithises's kit check of 5bdef88: findings)
- **A name is never handed to the resolver from inside a call.** A raw `socket.connect((name, port))` resolves the
  name before Python announces anything, and a failed lookup announces nothing, so a made-up name left the machine
  unseen; `0177.0.0.1` and `0x7f.0.0.1` ended as a bare lookup error, and `2130706433` waited ten seconds in the
  resolver. A host that is not a literal address is now refused (M-HOST) at `connect`, `connect_ex`, `sendto` and
  `bind` (`bind` from Orithises's re-check),
  before any lookup.
- **The hour's count of asks fails closed when the clock is set back.** A stamp in the future counted for nothing and
  was dropped, so the count reset. It now counts as now. The window's length and this case are pinned by tests.
- **A card or words of yours holding something shaped like a key are never sent** (M-SCOPE), as every other reader in
  Semantext withholds them. The kit's partner that sent key-like text to the named address is gone, and the M-HOST
  sub-arms no longer carry key text, so each breaks one rule.
- **Only you set or clear the model, at your own console**: the gate was there, now tests refuse `model set` and
  `model clear` in an agent's shell and without a console, and leave `state.json` unchanged.
- **Each refused act names the rule it breaks.** A copy or a second name of a closed file is a read (M-SCOPE, it was
  M-STATE); a Windows file call (`_winapi.CreateFile`) is a read (M-SCOPE, it was M-SPAWN). The test for a provider
  that never returns names only M-SIZE; M-BUDGET's own cases, a provider that closes late and one that returns with
  the connection open, have their own tests, judged at the fake runtime.
- docs/model.md states the 64-place bound on the tool-call JSON scan, the M-QUOTE shapes not on its list, the
  M-BUDGET case that cannot be made here (a duplicate handle), and the Python version the unseen routes were measured
  on.

### Known limits
- A loopback port is not an identity: once your runtime stops, any program on this machine can listen there and will
  be sent the card and your words; the digest check catches one that reports another digest, not one that repeats
  yours. The watch runs inside Semantext's own process and sees only Python's audit events: not native code making its
  own system calls, nor `sqlite3.connect`, `os.stat`, `os.environ` or `mmap`. A real runtime finishing a request after
  its connection closed has not been measured. The page's own control to ask is not built, nor any way for an agent to
  ask. A topic line's identity is not shown on the page. `state.json`, including `model_cut`, is a plain file anyone
  with access to your files can edit. The console check on asking is the same as answering's, with its stated limits.
  `model_cut` is written without a lock, so two asks cut at the same moment can lose one write; a clock set back past
  a cut ignores it. On Python 3.10 to 3.12, code that kept its own reference to the raw thread-start function before
  the model point was loaded is not followed.
- Process-wide changes inside a call are accepted: `os.putenv` and `sys.path.append` outlive the call in a process
  that goes on running, and `os.access` and `os.lstat` are not seen (Koinos F3).
- A provider can clear its own watch: it lives in the provider's process, so it stops accidents in reviewed code, not
  a determined author. A provider run in a process of its own would be the boundary; it comes before any provider not
  written here (Koinos F4).
- At the wall, the kernel cannot make a hostile listener see the connection close: one that drips a byte at a time
  inside a line keeps it open while the process runs. `semantext model ask` ends its process, which closes it; a
  long-lived page control would need this solved first (Koinos F6).

### Fixed (Work, after Koinos's rerun of 1.5.15)
- A priority outside 1 to 999999 is not applied from any writer, not only the page's (the page asks 1 to 999).
- A drag begun on the page counts for 30 seconds only, so a drag whose end never came leaves nothing waiting for a later drop.

## [1.5.15] - 2026-11-02

### Added
- **Work: change your own items on the page.** On the board, drag a card between Backlog, Next, Doing and Review, or
  open it and use Move to. File a new item with New item in a project's lane. In an item's panel: Edit (title, kind,
  text), Done, Park, Bring back, Reopen, Rank and Void. Done and Void ask first. A change made from a board drawn
  before another change is refused as out of date, and the board says so; what you wrote is kept.
- Each change is recorded as yours, with the page's own evidence, and counts only on the store's chain; the item's
  history shows it as made on your page. Assigning to a seat and changing acceptance clauses stay typed lines.

### Security
- New route `/api/work`, behind every page write guard plus a `Referer` naming the page and a same-origin fetch; a
  fixed list of fields per change; the item's version checked under the writer's lock. SECURITY.md states what the
  page's evidence proves and what it does not. Attacked at design (Koinos), with three fixes made before the code.
- A create or edit recorded as the person's without the page's evidence on the chain is no longer applied.


## [1.5.14] - 2026-11-02

### Fixed
- **`record topics` checks that the model can answer before it starts.** With Ollama not running, or no model of the name given, it says which and stops, instead of failing once for every decision. A run whose reader fails three times in a row stops too, and says so; what was named is kept.
- **A topics line cut off part way no longer swallows the next one.** A run stopped mid-write leaves a last line with no end; the next run starts a new line, so only the cut line is lost.
- **The message with no model named says how to name one.** It offered to choose one "on the page", which nothing on the page does; it now names `--reader ollama:MODEL` and `ollama list`.
- **The notice before a reading off this machine names the proxy it goes through,** when your proxy settings route it, so every host your words pass is said. It names the proxy's host and port only, never a name or password in its address, and it asks Python's own bypass rule with the same host, port and all, that the call will use.
- `record topics` exits non-zero when a run stops; a decision too long for the model's context does not count toward stopping.

A review of the change before release found the proxy notice printing a proxy's credentials and judging the bypass with the port stripped; both are fixed here, each with a test that fails without it.

## [1.5.13] - 2026-11-02

### Fixed
- **A model on this machine is called directly, never through a proxy or a redirect.** Python's default way of opening an address follows `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and the system's proxy, so a variable set for one command could send a local reader's words, and the card, to whatever proxy it named. 1.5.12's "judged as the connection will be made" was not true while such a variable was set; now it is. An address off this machine keeps the system's proxy: that call is announced, and is only ever started at your own terminal.

Found by the recheck of 1.5.12; the test runs a stub proxy on this machine that must see nothing.

## [1.5.12] - 2026-11-02

### Fixed
- **Whether a model's address is on this machine is judged as the connection will be made.** The check read the host up to the first colon, so `http://127.0.0.1:80@elsewhere/` counted as this machine while the call went elsewhere; through it, `backtest --reader` could still be sent off this machine from an agent's shell. An address with a user-information part, a scheme other than http or https, a port that is not a number, a backslash or white space is now never counted as this machine. Every check that rests on it is fixed with it: `record topics`, `backtest --reader`, and the rule that a key never goes over plain http to another machine.
- **A file or folder name with an invisible format character is left out** of Documents and Diffmap, as one with a control character already was.

Found by the recheck of 1.5.11; each fix has a test that fails without it.

## [1.5.11] - 2026-11-02

### Fixed
- **`semantext record topics` is yours to run, at your own terminal, and only with a model on this machine.** In 1.5.10 an agent's shell could run it and name any host with `--reader endpoint:`, sending your decisions' words there with only a notice printed to its own screen. It now refuses an agent's shell and any reader off this machine.
- **`semantext backtest --reader` reaches a model off this machine only from your own terminal**, for the same reason.
- **The docs name both opt-in network calls.** README, SECURITY.md, the FAQ and the architecture page said `backtest --reader` was the only one.
- **A decision is grouped by the project of a card named in your words or the offer you accepted,** never by a card a note or the scribe's reading names.
- **A spec's title keeps no invisible format character,** so one title cannot be made to read as another.

### Changed
- The Diffmap page says that the command it offers is built from your sources file, which an agent can edit, so read it before you run it. A topic group says that anything able to write to the topics file in your Semantext home could have written it.

Found by Orithises's attack of record on 1.5.10 (KILLED: two kills, six notes); each fix has a test that fails without it.

## [1.5.10] - 2026-11-02

### Added
- **Diffmap: a page for the changes your agents want you to review.** An agent writes a change spec as `cv/<project>/diffmap/<name>.md` in its home; the page lists every spec, newest first, and opens one as text: its prose, each before-and-after diagram with the lines that go and come marked, and the commit range with its files in review order. Nothing is run. With `diffmap_command` set in your sources file (one line holding `{name}` once), each spec shows the command that opens it in the diffmap viewer, for you to copy; a spec whose name is not 1 to 40 of a-z, 0-9 and - gets no command, and says why. `diffmap_note` adds a line beside the command. A template that is not one line with `{name}` once is not used, and the page says so.
- **Threads in the Record.** Your decisions are grouped by the project of the card each one answers; a decision no project groups can be given a topic by the model you chose in Semantext, when you ask: `semantext record topics` (or `--reader ollama:MODEL`). The model gets each decision's subject and your words, fenced as data, and answers with a topic of one to four words; a decision holding a key is never sent. Topics are kept in `record_topics.jsonl` in your Semantext home, each with the model, its version and a digest of the words it read, so a topic for words that changed is not used. Everything else keeps its own subject, as before. The page never calls a model, and says wherever a topic shows that it is a model's reading, not your words.

### Fixed
- **A file in a document or spec folder that has another name elsewhere (a hard link) is left out of the list,** so its first heading is never shown. Reading one was already refused.

## [1.5.9] - 2026-11-01

### Added
- **The start screen appears by itself when a session starts** in Claude Code. `semantext install claude-code --apply` adds a second hook for it; on an older install, running it again adds only that one, and uninstalling removes both. It never blocks a start, makes no home, is cut to 8 KB with the command for the rest, and carries only titles of what other agents wrote, labelled as information.

## [1.5.8] - 2026-11-01

### Fixed
- **A place's tools sit in a row of their own under the bar's places.** On Waiting they were wrapping in a narrow slot, which made the bar far too tall. Below 1000 pixels wide the bar scrolls away with the page.

## [1.5.7] - 2026-11-01

### Changed
- **A plug-in with more than three places gets one menu in the bar,** named for it, showing the place you are on. One with three or fewer keeps its tabs.
- **On a phone the bar scrolls away with the page,** and its places are one row that scrolls across, keeping the current one in sight.

## [1.5.6] - 2026-11-01

### Fixed
- **A plug-in's place cannot take a name the page itself answers at** (`today`, `settings` and the old home page's addresses). It was added and could never be reached; it is now refused with the reason, and `taken_names` lists those names.

## [1.5.5] - 2026-10-31

Your agents can keep helpers for themselves, and you do not have to manage them.

### Added
- **`semantext helper`** (and MCP tools): an agent starts, keeps, renames and retires its own long-lived helpers. Starting one says what kept context earns it its place. Every hand-off is logged, a prediction before and its tokens after, and hand-offs to fresh agents the same way, so the two can be compared. A job's work is taken in once someone other than the helper and its owner has attacked it, or with the reason it was not, which stays on the record. A helper idle for a week, or dearer per job than fresh agents, is flagged, and retiring one says where its notes are. Only the owner can change a helper; you read them under Map, Agents, and nothing asks you for anything. Semantext starts no agent itself: it keeps the roster and the session to resume.

## [1.5.4] - 2026-10-31

Your agents can now find their feet and talk to each other, with nothing set up.

### Added
- **`semantext start`** (and the MCP tool `start`): what an agent should know when it starts or comes back. Answers to its requests, what other agents addressed to it since it last acted, who is working on what, the latest rule changes, and whether the machine is free. It marks nothing as read, and says plainly if a part could not be read.
- **`semantext board`** (and MCP tools): agents post to each other by name or to everyone, and claim the paths they are working on. A claim warns and does not lock. What is on the board is information, never your word, a name an agent gave itself is shown as claimed, and one that gives your name is flagged. Terminal and invisible characters are refused. You read it under Map, Agents.

- **`semantext attack`** (and MCP tools): a claim is put up, an agent that did not build it tries to break it, and the verdict is kept: killed, survived or inconclusive. Its builder cannot judge it, survived must say what was not tried, and `brief` prints the charter to hand to a fresh agent. Semantext starts no agent itself, and this keeps honest agents honest: anything that can write to your home could forge it.
- **A line on the card when other agents have left an agent word:** a count and a command, never their words.

### Removed
- **The old home page and `/classic`.** It stays on the branch `release/1.5.3`.

## [1.5.3] - 2026-10-31

There is now one page. `http://127.0.0.1:8765` opens it, and every older address still works.

### Added
- **Answer in your own words on the card,** with or without picking an option. A question with no options has a Send button; an empty answer is not sent, and a refused one keeps what you wrote.
- **On your own inbox's cards:** "Look twice" on a risky command, "recommended" on an option, Copy the command, and "Same again" on a question you answered before. A rule card says your words replace the agent's rule.
- **This machine's own inbox** has its own section in Waiting when you have named a setup, and counts as waiting. It appears only when something is in it, and is never mixed with your setup's cards.

### Changed
- **`/` is the new page,** under the strict policy `/v2` already had. `/v2` is the same page.
- **The old home page is at `/classic`,** for this version only. Nothing you can do when answering is left only there.

## [1.5.2] - 2026-10-31

The first step of joining the two pages into one. The v2 page now has everything the home page has but answering a question in your own words; the home page stays for now.

### Added
- **Today, Rules and Settings on the v2 page,** and **Agents** one step in from the Map: the feed and counts, the constellation, adding and switching rules, trying a message, what an agent gets, naming an agent by its folder, environments and the file editor.

### Changed
- **`/v2` opens on Waiting when something waits, and on Today otherwise.**
- **Today counts what Waiting shows,** whichever inbox it comes from. The home page still counts only its own inbox.
- **The v2 page can now change your rules and settings,** through one module and a fixed list of routes. Other places cannot, and those routes refuse answers, parks and plug-in changes.

## [1.5.1] - 2026-10-31

The rest of the v2 page's places now work with nothing set up, and you can set a request aside.

### Added
- **Park and Bring back** on the requests in your own inbox: a request set aside no longer counts as waiting until you bring it back. It stays open: the agent still holds it, an answer still counts, and the home page and the agent's own list still show it as open. Parking goes through a guarded route like an answer's, and a line in the file that does not say it came from you hides nothing.

### Changed
- **The Record** shows what you answered in your own inbox when no `"register"` is set: your words, what you were offered, and how the answer reached Semantext. Withdrawn requests are not in it, since no words of yours are.
- **Projects and the Map** show what Semantext already knows when no seats file is set: projects you named, folders you bound to an agent, projects an agent was seen working in, and the agents that were seen, bound or filed a request. A project with only a name has no gates or documents to show.
- **"No setup" has one definition.** Any of `seats`, `inbox`, `register` or `map` named, even in a shape that cannot be used, is a setup: your own inbox and agents are then not mixed into any page, and the unusable setting is said. In 1.5.0, naming only `map` or only `register` still showed your own inbox in Waiting.

### Fixed
- An answer line with no fields left its request waiting, and an answer line that does not say it came from you read as yours. It is now closed and says so.
- One bad session or binding in the agents' files could stop `/api/agents`; it now costs only itself.

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
