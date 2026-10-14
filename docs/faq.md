# FAQ

**Is this a prompt library?**
No. A prompt library stores tasks. Semantext stores how you mean what you say: whether a question is a request, what
counts as a yes, which acts must wait for you. It puts those rules in front of every task.

**Does it send my rules anywhere?**
No. Semantext makes no network calls of its own, and has no account or telemetry. Your AI tool receives the card as
part of your prompt, as it would anything else you type. The page answers only on `127.0.0.1`. The one opt-in
exception is `semantext backtest --reader`, which sends the card and the messages it scores to the model you name.

**Does the hook read my prompts?**
It receives each prompt event from Claude Code, prints your inbox's notes and your card, and keeps nothing. If you
switch on `semantext config hear-prompts on`, it also keeps each prompt in your heard log, on this machine, so that
`semantext propose` can suggest rules from it. `semantext forget --all` clears the log.

**Will it slow my prompts down?**
The hook reads a small YAML file and your inbox, and prints a few kilobytes. It never blocks a prompt.

**What happens if my rule file is broken?**
Your prompt goes through as normal. Your AI still gets the base rules, with one line naming the broken file and the
problem, until you fix it. `semantext card` refuses with one line naming the file and the rule (for a YAML mistake,
the line and the column), and `semantext doctor` lists every file it cannot read. The page's editor refuses to save a
file that would break.

**Can I edit the YAML by hand?**
Yes. It is your file, and `semantext where` prints its path. Keep the environment's `id` unchanged, and give every rule
a unique `id` and a `statement`. When Semantext changes the file itself (for example `teach`, `toggle`, `pin` or
`undo RULE_ID`), it writes the file again from its data, so comments and your own layout are not kept. A save from the
page's editor keeps your text as typed. Every earlier version is kept in `~/.semantext/history/`, so a comment you
wrote is still there.

**How do I take a rule back?**
`semantext undo RULE_ID` archives it: the rule stays in the file, and leaves the card. `semantext undo --last` restores
the previous version of the whole file. Nothing is ever deleted.

**Which AI tools does it work with?**
- **Claude Code,** through its `UserPromptSubmit` hook: `semantext install claude-code`.
- **Codex, freebuff, and any agent that reads an instructions file,** through a block in that file:
  `semantext install codex`, `install freebuff`, or `install agents-md --file PATH`.
- **Any tool that speaks MCP** (Claude Desktop, Cursor and others), through `semantext mcp`.
- **Local models,** through `semantext export system-prompt`, or `export modelfile --base MODEL` for Ollama.

Each `install` shows its change first and makes it only with `--apply`.

**Can my AI answer its own request in the inbox?**
It must not, and Semantext's checks stop it doing so by habit or by accident: `semantext answer` refuses an agent's
shell, and the page takes an answer only from itself. A program running as you that sets out to fake an answer cannot
be stopped on one account, so every answer records where it came from. See [inbox.md](inbox.md) and
[SECURITY.md](../SECURITY.md).

**Can I share an environment with my team?**
Yes. An environment is one YAML file. Commit it to a repository, review changes as diffs, and copy it into
`~/.semantext/profiles/<name>/`. The [writing-desk example](../examples/writing-desk/) is one such file.

**Why "Semantext"?**
Semantics and context: what your words mean, carried as context into every prompt.
