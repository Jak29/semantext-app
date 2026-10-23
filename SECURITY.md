# Security

Semantext runs on your machine. It reads and writes files in one folder, and it serves one page to your own browser.
This page says what it touches, how it protects you, what it does not protect against, and how to report a problem.

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
  file by hand carries no agent's name, and Semantext does not yet mark such rules on the card.
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
  or short (8.3) name. Two layers decide which files those are. First, evidence is a document, a script or source
  text, by its kind (`.md`, `.txt`, `.json`, `.jsonl`, `.yaml`, `.yml`, `.toml`, `.py`, `.ts`, `.tsx`, `.js`, `.mjs`,
  `.cs`, `.rs`, `.lean`, `.svg`, `.csv`, `.sh`, `.ps1`, `.bat`, `.cmd`, `.html`, `.css`, `.xml`, `.cfg`, `.ini`,
  `.go`, `.java`, `.c`, `.h`, `.hpp`, `.cpp`, `.log`, and the files `LICENSE`, `Makefile`, `Dockerfile`, `README`,
  `.gitignore`, `.gitattributes` and `.editorconfig`), and nothing else. Those kinds are where secrets live too, so
  the second layer carries the weight: no part of the path, taken whole and in any case, may be named like a secret
  (the list is `SECRET_NAMES` in `semantext/sources/change.py`: `.env*`, key and certificate files, `credentials*`,
  `wallet*`, `vault*`, `secret`/`secrets` and `*_secret*`, `token`/`tokens` and `*_token*`, `password*`, `seed`,
  `mnemonic*`, `*api_key*`, `key.*`, `settings.local.json`, `hosts.yml` under a `gh` folder, the folders `.ssh*`,
  `.kube`, `.docker`, `.aws`, `.gnupg` and `*kaggle*`, and more). The trade-off, stated: "token" and "secret" are
  matched as whole words, so `tokenizer.py` and `secretary.md` stay evidence, while `wallet*`, `vault*` and `.ssh*`
  also refuse a few honest names (`wallets.md`, `vault_notes.md`, `tokens.md`). A secret kept under an ordinary name
  of an evidence kind can still be digested; the home and project limit is what keeps that from telling the agent
  anything it could not read. An absent file is "unknown", never a match. At most 50 files a record and 200 records
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
| 1.0.x | yes |
| 0.1.x | no |
