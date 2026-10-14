# Changelog

All notable changes to Semantext are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
