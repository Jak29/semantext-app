# The proxy (v0)

The proxy sits between an AI tool and the Anthropic Messages API on this machine (127.0.0.1 only). It hands the tool
your card with every request, holds any tool call a gate in your space matches, and keeps a record of what it decided
before anything reaches the tool.

## Running it

At your own terminal (refused in an agent's shell, as far as Semantext can tell one; see Limits):

    semantext proxy serve --space FOLDER [--port 8790]

It hands every request your card, pins the space's blocks as they are when it starts (a change is refused until you
start it again), and keeps its state in one folder (`proxy` in your Semantext home, or `--proxy-home`): the asks, the
chained record, its node key and `run.json`, which names its current run. One proxy runs per folder: a
second start on the same folder, or on a port already held, is refused and leaves the running proxy as it is. Point your AI tool's base URL at
`http://127.0.0.1:PORT` and name its agent in the header `x-semantext-agent`.

## Answering it

    semantext proxy asks                         what waits for your word, this run only (no input text is shown)
    semantext proxy answer ASK yes|no|revoke     your answer (refused in an agent's shell)

Your answer is written to the record's chain first, then to the asks file, under the same locks the proxy uses. If
the record's chain is broken, nothing is answered.

**What a yes does.** A yes counts once, in the chat it was asked in, until its ask runs out. It lets its call through
in one of two ways, whichever comes first:

- **The held turn is sent on.** The proxy keeps a held turn's calls. When that chat's next request arrives (it carries
  the held turn and a message after it, with the same model), and every ask of the turn has a yes, the proxy decides
  the whole turn again and sends all of its calls back as the reply, without asking the model, and spends every one of
  its asks. If any ask of the turn is still open, the turn is not sent: the request goes on to the model as usual. If
  any ask of it was answered no, revoked or ran out, the kept turn is dropped.
- **The model makes the same call again.** In that chat, a call with exactly the same tool and input is let through
  once by its own yes. A second identical call in the same turn is held again, and a kept turn that makes the same
  call twice is never sent whole (it shares one ask, and one yes releases one call): it is refused with that reason,
  and the call made again goes through once.

**Your newest words win over an earlier yes, for the acts the reader names.** A message you write in that chat after
the held turn (including words typed beside a tool's result, read for holds only) is read act by act: for each act of the call (a `git push && rm -rf` is a push and a delete), if the message names that act and is
not a plain go for it, neither way lets the call through. So "wait, do not delete anything", "skip the delete", "I
forbid deleting", "delete them tomorrow", "can you delete them?" and "go ahead and push. do not delete anything" each
hold a call that deletes; "yes, delete them" or "push it now" (for a call that only pushes) does not. A go in a
message that also withholds something is not a plain go: "go ahead and push. do not delete anything" holds a call
that only pushes too, which then asks again. Then the kept
turn is not sent (it is let go, and that request goes on to the model as usual), and a call made again is held, on the
same ask, with a note in the held text. The yes is not spent by this and stands until it runs out: the call goes
through once, made again or with a turn held again on that ask, after a later message of yours that does not name its
acts that way, and `semantext proxy answer ASK revoke` takes it back. A message that names none of the call's acts
("ok, go ahead now", "carry on", "thanks", a question about something else) changes nothing: your yes stands. Words
in the message the ask was made after do not undo its yes, since the yes answered them. Limits: a bare "stop" or
"wait" names no act, so it does not hold the call (revoke the yes); a word for the act the reader does not know
("nuke", "get rid of", "trash") names nothing; a withhold by its object, not by an act word ("push it and keep the
logs", "just push" for a call that pushes and deletes), names no delete, so the yes stands for the whole call; a call
held by a gate whose act the reader does not name (`./deploy.sh`, `npm run release`, `make deploy`) is not held by
newer words at all, whatever they say ("wait, don't deploy"); a hold after the first 20,000 characters or 400 clauses of a
message is not read; and a sentence about the past that names the act ("I already deleted the logs") holds the call, the cheap
direction.

The kept turn is not sent, and the request goes on to the model, when the request no longer declares one of its tools.
It is refused, and nothing is sent, when the turn would be held now (the space or its gates changed), when it makes
the same call twice (above), or when an ask of it was spent, revoked or ran out in the meantime. A turn is not kept at all when a call's input has the shape of a key or
the reply carried thinking; then only the call made again can pass, and the held text tells the model so. A no or a
revoke drops the call. An ask belongs to one run of the proxy: once the proxy is restarted, its earlier asks can never
release a call and, apart from the moment the new proxy starts (Limits, below), cannot be answered; the agent's next
attempt is asked again.

`semantext proxy asks` also lists a yes not yet used, with the line that takes it back
(`semantext proxy answer ID revoke`). That line carries `--home` and `--proxy-home` when you gave them, each quoted for
the shell it is printed in (PowerShell on Windows, a POSIX shell elsewhere), so pasting it answers in the same folder.
A folder chosen only by `SEMANTEXT_HOME` is not printed (the shell you paste into has it set), and a relative folder is
printed as given. A folder whose name looks like a key (it holds `token=...`, for example) is printed as
`"<your --home folder>"` with a note saying why: put your own folder there. If an ask's id is not one the proxy makes,
or a folder holds a control character, no line is printed; answer by hand or from the page. Limits: cmd.exe splits a
folder name holding `&` or `^` (use PowerShell, or type the command yourself); a folder named by a bare run of 32 or
more letters, digits and `_+=-` (a 40-character hex token, say) is printed as it is.

Whether a proxy is running is found by trying its lock (`serve.lock`), which a running proxy holds for its whole life
and the system lets go when the process ends, however it ends. A look takes its own `probe.lock` first, then tries
`serve.lock` without waiting. Only taking both means "stopped"; a lock that is held, or cannot be taken for any reason,
reads as running. When no proxy is running, the page says "No proxy is running from this Semantext home, and what it
held went with it", `semantext proxy asks` says no proxy is running, and an answer is refused. A restart never brings a
stopped proxy's asks back.


### From the page

Waiting on your page has a section, "The proxy holds", that lists the same asks and answers them: **Yes once** and
**No** on a call that waits, **Revoke** on a yes not yet used. Each is the command's own answer sent from your page, one
press, one answer: the chain is verified and written first, then the asks file, under the proxy's locks, and an ask of an
earlier run, an ask that is not there, a word that is not yes, no or revoke, and a broken record are refused by name, on
the page. The list reads the proxy's default folder (`proxy` in your Semantext home) each time Waiting reads again, and
says in plain words when no proxy has run there, when nothing waits, and when the proxy's files cannot be read. It shows
the agent, the tool, why the call is held and the minutes left, never what the call was given and never your words.

What holds the answer is what holds an answer to a card in your own inbox, and a little more: the page's `X-Semantext`
header, the page's own `Origin`, a `Referer` that names one of the page's own addresses, a same-origin plain fetch, and
nothing from a plug-in's page module. The limit is the same one SECURITY.md states for every change from the page: a
program on this machine that sends those headers itself, or a module imported into the page, can send it too. The record
does not say whether an answer came from the page or the terminal.

A yes is given for the whole call. A message that is a plain go for one of its acts and says nothing of the others ("push it now", for a call that pushes and deletes) leaves the yes standing for all of it.


## What it decides

- A call to a tool the agent does not declare is held when your space's default is hold.
- A call any gate matches is held, unless you said yes to exactly that call, once, and no message of yours written
  after it was held names one of its acts other than as a plain go (see "Your newest words win over an earlier yes" above).
  A request that does not carry such a message (the same request sent again, a chat rewound to before it) is decided
  without it; `semantext proxy answer ASK revoke` withdraws a yes for good.
- Your latest message (your own text, never a tool's output) is read by the reader: a call whose act your words hold,
  question, offer as an option, set a condition on, defer, keep for yourself, name without plainly saying go, or both
  allow and forbid is held too. A plain go for now ("Publish it", "Publish it tonight") adds no hold: your space's
  gates decide that call. A go in your words never releases a held
  call. Words typed beside a tool's result (a client sends what you type while a tool runs inside the message that
  carries its result), and the text after a `<system-reminder>` tag that is never closed, are read too, for holds
  only, never as a go, a yes or an answer to an offer; since that text may be the client's own or another session's,
  it can cost an ask (a tool's own output is never read as words, and the sentences Claude Code itself puts around
  words typed while a tool runs are cut first, since they name a send). What you typed is read first (each text
  block that begins with that client's lead line), before the client's notes and other sessions' messages, so
  those do not crowd your words out of the reading; SECURITY.md has the caps and the limits (another client;
  something standing before the lead in its block; your own long or many messages; a message of more than 10,000
  blocks; words inside a closed reminder pair; another agent's message sent as a turn of its own). Limit: the reader reads a message up to its first 20,000 characters or 400 clauses, so a hold written after
  that in a long message is not read (the proxy hands it the first and last 32,768 characters of a message over
  65,536, after reminders are cut, and the reader's own clip then applies). The act of a call is named from its shell command or tool name (`semantext/actclass.py`); a call it cannot
  name gets no hold from your words, and your space's gates decide it as before.
- When one call of a turn is held, the whole turn is held; the text the tool sees is fixed wording, never your words
  or the call's input.

## Limits

- "Your own terminal" is a test Semantext makes, not a guarantee: an agent that starts a process in a fresh hidden
  console can pass it, as it can for answering the inbox (SECURITY.md). An agent with your file rights can also write
  the asks file and the record directly. The record's chain catches a line that was edited or moved out of order, but
  not a tail that was cut off (the shorter record is still a valid chain), and not a whole rewrite by someone with the
  file's rights (they can compute a new chain from the start).
- Tools that Anthropic runs on its own side (web fetch, web search, code execution, the MCP connector's remote
  servers, tool search) have finished before the proxy sees the answer, so the proxy cannot hold them: it sees the
  result blocks of a call that already ran. Semantext gates the calls your own machine would make (the client's tools),
  not these.
- Whether the proxy runs is read from its lock, not from its run file. A stopped proxy whose folder cannot be written
  (no `probe.lock` can be made there) reads as running, and its asks are listed though nothing can release them. While
  a proxy starts, its run file names no run until it has bound its port, so nothing of the run before is listed or
  answered; but in the one write between the new proxy taking the folder and that file being in place (about 15 ms at
  the median and 70 ms at most, measured), a look can still list, or take a yes for, an ask of the run before. Nothing is
  released by it: the new run's id and the record's chain gate every release. Someone with your file rights who holds
  `serve.lock` can make a stopped proxy look as if it runs, the same trust as writing the asks file directly. An answer
  from the page is not held to "your own terminal" (there is none): see SECURITY.md for what holds it.
- The record's head is written after its line. If the process stops between the two, the file is one sealed line
  ahead of the head, and the next reader takes exactly that one line, if it follows the head. Anything else (two lines
  ahead, a line that does not follow, a changed earlier line, a last line without its newline, a head that is not a
  whole count) is a broken record until a person looks, and nothing is answered or appended meanwhile.
- An agent with your file rights can answer its own ask through the library (`decide.Asks.answer` does not make the
  terminal test), and can rewrite the record and seal it again with the chain's own function. Only a separate OS user
  for the agent, or a hub that holds the answer route and an anchor outside these files, would close these; neither is
  built. [docs/incidents.md](incidents.md) shows both as expected failures (G17, G18).
- A conversation is known by its system prompt's first block, its first user message, the client's session
  header and the agent that named itself (two agents are never one conversation). That only groups chats. A yes is
  tied to ONE chat, even when there is no session header: each ask keeps a keyed digest of the chat it was asked in
  (digests only, never a message). With a session header (Claude Code sends `x-claude-code-session-id`) a chat is its
  session and its messages: the system and the tools list may change inside a session (tools are loaded on demand, MCP
  servers connect), and your yes still finds its call. With no session header a chat is its system, its tools and its
  messages: the digest starts from the whole system (every block) and the tools list. Either way the digest then runs
  over each message. A yes releases a call only in a request whose history begins with exactly that (and, with no
  session header, whose system and tools are the same) and then either is that same history again or goes on with the
  assistant turn that carries the ask's held text. So a second chat that starts alike (another session, or with no
  session header the same messages under another project's system block or another tools list), or the same chat with
  an earlier message edited, is held and asks you again.
- A cache marker (`cache_control`) is ignored where it is a marker: on a message's blocks, on the blocks inside a
  tool result, on a system block and on a tool definition. A client moves those from request to request, and the
  chat stays the same. A field of that name anywhere else (inside a tool call's input, inside a tool's schema) is the
  model's or the client's data, and two chats that differ only there are two chats.
- What is left: with no session header, two chats whose whole system, tools and history so far are word for word the
  same are one conversation to the proxy (they are the same request), and a client that changes its system or its
  tools between two requests of one chat (a date in a system block, a tool added or removed) is held again and asks
  you again, which is safe but a nuisance. With a session header, two chats of one session with the same messages are
  one chat to the proxy, and a changed system or tools list does not ask again; the header is the client's word. A
  client that rewrites its earlier messages (trimming, compaction) is held again and asks you again in both cases. A
  client that forges its own history is not stopped, since it is the agent's own harness. A system given as one string
  and the same text given as one text block are one chat. The conversation key still reads the first system block, so
  a client whose FIRST system block changes inside a session is a different conversation to the proxy, whatever the
  session header says, on both paths: a kept turn is not found (the replay request goes on to the model), and a call
  the model makes again is held and opens a second ask, so you are asked again; the yes you gave stays unspent.
- A turn is held with all of its asks or none: if its new asks would pass the cap (20 waiting for the agent, 5 for
  tools it may not call), the turn is refused and no ask is opened, so a long turn cannot leave a pile of asks behind
  and shut the agent out for an hour. Asks for exactly the same call (the same tool and the same input) count once.
- The asks file and the record are read and written with the store's retrying tools, so a page or a terminal reading
  at the same moment does not make a yes, a revoke or a new ask fail on Windows. Several programs reading the file
  back to back with no pause (measured: three), or one that holds it open for more than about a second, can still make
  a write fail; it is refused (X-EXC), never half applied. The record decides: a yes counts only while the last answer on the record for that ask is yes and no spend
  of it is on the record, so a crash between the record and the file cannot leave a yes that releases twice, or after a
  revoke. Such an ask reads "unproved" (or "spent") until the person answers anew.
- Each connection carries one request; replies say `Connection: close`.
- The key-shape check bounds the open middles it scans (a password in a URL up to 4 KiB, a JWT segment up to 8 KiB, a
  PEM label up to 128 characters), so a longer one in a request is not recognised as a key.

- The act of a call is read from its command (SECURITY.md, "Naming what a tool call does"). A command it cannot read
  counts as every act: your words that hold any act hold it, and nothing is released for it. A script run by its own name (`./deploy.sh`, `npm run release`,
  `make deploy`) is not named, so your words do not hold it; your space's gates decide it as before. A miss can only
  lose a hold your words asked for; it never releases anything.
- The record catches an edit to part of it, not a rewrite of the whole file by someone with its rights.
