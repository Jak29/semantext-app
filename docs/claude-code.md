# Using Semantext with Claude Code

Claude Code can run a command each time you submit a prompt, and add whatever that command prints to the prompt's
context. Semantext uses this `UserPromptSubmit` hook to hand your card to the assistant with every prompt.

## Install

```bash
semantext install claude-code           # prints the entry it would add, and changes nothing
semantext install claude-code --apply   # saves a backup, then adds the entry
```

The entry:

```json
{"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "semantext hook"}]}]}}
```

- **The command** is `semantext hook` when `semantext` is on your PATH. Otherwise it is your Python running the module,
  such as `"/path/to/python" -m semantext hook`, which works wherever the package is installed. `--command` chooses it
  yourself.
- **The backup:** before changing anything, `--apply` copies the settings file to
  `settings.json.semantext-backup-YYYYMMDD-HHMMSS` beside it.
- **Your existing hooks are kept.** Semantext's entry is added alongside them, and never added twice.
- **A settings file that is not valid JSON** is refused and left untouched.
- **Another settings file:** `--settings PATH` uses it instead of `~/.claude/settings.json`.

You can also add the entry by hand.

## Check it

- `semantext doctor` reports whether Claude Code is connected, whether `semantext` is on your PATH, and whether your
  card fits the hook's size limit.
- `semantext card` prints the card the hook adds to your prompts. The hook puts your inbox's notes before it, when
  there are any.

## What the hook does

The hook reads the prompt event that Claude Code sends on stdin, then prints two things:
- **your inbox's notes,** if there are any: your answers that Claude has not read yet, then the requests still waiting
  for you (see [inbox.md](inbox.md));
- **the card** for your active environment.

It does nothing else unless you switch on `hear-prompts` (below). It keeps three promises:

- **It never blocks a prompt.** Whatever goes wrong, such as a broken rule file, it prints one line,
  `Semantext: the card is unavailable this time (...)`, and exits with status 0. A hook that exits with status 2 blocks
  the prompt in Claude Code, and Semantext's never does.
- **It stays under 9,500 bytes,** the inbox's notes included. Claude Code may save larger hook output to a file and show
  only a short preview, so most of the card would never reach the model. The notes take at most 3,000 bytes.
- **It drops whole rules only.** If rules must be left out to fit, a final line says how many.

It makes no network calls.

Two more lines it may print after the card, each a fault it says rather than hides:

- `Semantext: this turn's record was not kept (...)`. For Work, the hook keeps where each of your turns lies in the
  session's transcript, so an act you type is checked against your own words. When that record cannot be written,
  an act typed in that session reads "unverified". On Windows this happens when your Semantext home's path is long
  enough that the record's file passes the 260-character limit; a shorter home path cures it.
- `Semantext: the feed was not kept: ...`, when the feed's lock is refused for what stands at its name, or the system
  refuses it. It is said once for each fault, not on every prompt; a feed that is only busy is not said at all.

## Hearing prompts (off unless you switch it on)

```bash
semantext config hear-prompts on    # the hook also keeps each prompt in your heard log, on this machine
semantext config hear-prompts off
```

With `hear-prompts` on, `semantext propose` can suggest rules from how you actually talk to your assistant. It looks
for sentences such as "always…", "never…", "don't…" or "from now on…". Nothing becomes a rule until you accept it.
`semantext forget --all` clears the log.

## Remove it

```bash
semantext uninstall claude-code           # says what it would remove
semantext uninstall claude-code --apply   # saves a backup, then removes Semantext's entry and nothing else
```
