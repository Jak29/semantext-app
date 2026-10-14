# Install test cases

One set of cases for every way Semantext connects to an agent: Claude Code, Codex, freebuff, a generic AGENTS.md, and
a local model through `export`. They were first drafted against 0.1.0 at 9bcecfa, where only `claude-code` existed.

**Pinned** below means measured on 0.1.0 at b73be19, on Windows, in the harness described next, for every installer,
Claude Code's included. The same cases were measured first at a5e6b6d. A case marked **open** is a proposal, not yet what
the code does.

## The harness

- **A fresh venv** with the wheel installed offline, and `SEMANTEXT_HOME` set to a scratch folder.
- **A sandboxed profile.** Run every `semantext` command with `USERPROFILE` (Windows) and `HOME` (macOS, Linux) set to a
  scratch folder. Every default path (`~/.claude`, `~/.codex`, `~/.semantext`) then lands in scratch, so the plain forms
  without `--settings` or `--file` can be tested too.
  - **Checked:** on 9bcecfa and again on a5e6b6d. Each dry run named a target inside the scratch profile, and the real
    agent files were unchanged afterwards.
  - **Guard it anyway:** read the dry run's target first, and apply nothing unless the target is inside scratch.
- **The real profile, watched.** Before and after the run, take the sha256 and modification time of the real agent
  files: `~/.claude/settings.json`, `~/.codex/AGENTS.md` and `~/.codex/config.toml`. Every one must be unchanged. This
  is read-only.
- **The scratch tree, listed** (each path with its sha256) before and after each step. Each step's effect is the
  difference between the two lists.
- **A scratch project** for freebuff: a git repository with a subfolder, and a plain folder outside git.

## What every installer must do

| # | property | how it is checked | at a5e6b6d |
|---|---|---|---|
| P1 | **Dry run by default.** The plain form prints the exact change and writes nothing. | The scratch tree is byte-identical before and after. | pinned |
| P2 | **One block, nothing else.** `--apply` adds exactly one marked block or entry. When the target already existed, a backup is saved beside it first. | The target differs only by the block. For JSON targets, compare the parsed data, since the file is re-serialized. | pinned (backup `<file>.semantext-backup-<time>`) |
| P3 | **Idempotent.** A second `--apply` changes nothing. | The target is byte-identical, and no second backup appears. | pinned |
| P4 | **Reversible.** `uninstall --apply` takes back exactly what install added. | Markdown: the target's bytes are back to before. JSON: the parsed data is equal. | pinned. When install created the file, uninstall leaves it: empty for Markdown, `{}` for `claude-code` |
| P5 | **The file keeps its form.** Encoding (UTF-8, with or without a BOM), line endings (CRLF stays CRLF), the trailing newline, and every line outside the block are kept. | Byte comparison outside the block, on a target made with CRLF, a BOM and no final newline. | pinned |
| P6 | **Refuses what it does not understand.** Examples: invalid JSON, a block's start marker with no end, two blocks. | One line naming the file, a non-zero exit, and nothing written. | pinned (exit 1, file unchanged) |
| P7 | **Touches only its own block.** Text the user wrote that looks like the block (the word semantext in a comment, for example) is left alone. | User content above, below, and resembling the block survives install and uninstall. | pinned |
| P8 | **Upgrades in place.** After the card changes, `sync` refreshes the block in every connected file. | One block after, holding the new card; the user's text kept; a second `sync` byte-identical ("already current"). | pinned |
| P9 | **`doctor` reports it.** It names each connected file, and says when one is broken. | `doctor` (and `doctor --settings FILE` for Claude Code) in the sandboxed profile. | pinned: exit 0 when all is well; exit 1 and "PROBLEM: block missing or broken" for a broken file, or "cannot read" for invalid settings |
| P10 | **Nothing else is written.** | The only new paths in scratch are the target, its backup and `SEMANTEXT_HOME`. | pinned: an apply also records the connected file in `SEMANTEXT_HOME/state.json`, for `sync` and `doctor` |

The block is marked `<!-- semantext:start -->` … `<!-- semantext:end -->` in Markdown targets.

## Per agent

### Claude Code (`install claude-code`)

- **Target:** `~/.claude/settings.json`, or `--settings`. The entry is one `UserPromptSubmit` hook that runs
  `semantext hook`, or `python -m semantext hook` when it is not on PATH.
- **Cases:**
  - P1 to P10, with JSON comparison;
  - existing hooks and keys kept;
  - a settings file whose `hooks` has an odd shape is refused (P6);
  - **the hook runs:** pipe a prompt event (JSON) into the configured command. The card prints, it exits 0, the output
    is UTF-8, and it is under the hook's byte limit;
  - **a prompt with accents is read correctly on Windows** (stdin as UTF-8, not cp1252).
- **Manual, not in CI:** start Claude Code with `--settings <scratch file>` and see the card arrive with a prompt.

### Codex (`install codex`)

- **Target:** `~/.codex/AGENTS.md` (Codex's global instructions), or `--file`.
- **Cases:**
  - P1 to P10, with byte comparison;
  - P5 on a CRLF AGENTS.md with a BOM and no final newline: **pinned**, all three kept, and uninstall restores the exact
    bytes;
  - P7 with the user's own instructions above and below the block;
  - **`~/.codex` missing: pinned, created.**
- **Observe, after a Codex import from Claude Code:** in one run, seen on one machine, that feature copied a folder's
  CLAUDE.md into AGENTS.md, and its Claude Code hooks into `.codex/hooks.json`. Every "claude", in any case, became
  "Codex". The feature may behave differently elsewhere or later, so re-check what it does before relying on this. After
  it runs, check that Semantext is not connected twice and that no copied hook command is broken.
- **Manual, not in CI:** open Codex and ask it to quote the Semantext section of its instructions.

### freebuff (`install freebuff`)

- **Target:** the project's `knowledge.md`, which freebuff reads by itself, or `--file`.
- **Cases:**
  - P1 to P10;
  - **which folder is the project: pinned.** Inside a git repository, the block goes to the repository's root, even when
    run from a subfolder. Outside git, it goes to the current folder;
  - an existing `knowledge.md` is kept around the block.
- **Manual, not in CI:** install freebuff (an npm download from a third party), sign in, and run it in a scratch project.

### Any agent that reads AGENTS.md (`install agents-md --file`)

- **Target:** the file named by `--file`.
- **Cases:**
  - P1 to P10;
  - **no `--file`: pinned, refused.** "agents-md has no default file: name one with --file PATH", exit 1;
  - **pinned:** it never writes a CLAUDE.md.

### Keeping every copy current (`sync`)

- **Cases, all pinned:**
  - after the card changes, `sync` refreshes the block in each connected file ("refreshed: <file>"), with one block
    after it and the rest of the file kept;
  - a second `sync` changes nothing ("already current");
  - a connected file whose markers do not form one block (two blocks, for example) is left untouched and named in a
    "PROBLEM:" line, and `sync` exits 1, as `doctor` does. At a5e6b6d it said "no block there any more" and exited 0.

### A local model (`export`)

- **`export system-prompt`, pinned:**
  - it prints the card as a system prompt;
  - the output is stable across runs, and it exits 0;
  - it writes nothing (it has no `--out`).
- **`export modelfile --base MODEL`, pinned:**
  - the output starts `FROM MODEL`, then one `SYSTEM` block holding the card;
  - with no `--base`, it is refused with a hint ("--base llama3.2"), exit 1;
  - a rule containing `"""` is refused, exit 1, pointing to `export system-prompt` instead;
  - it writes nothing.
- **These checks are static,** and need no model.
- **Manual, not in CI:** create a model from the Modelfile and send one prompt. It needs the compute, and the owner's
  go-ahead for the model used.

## Manual steps, all of which need the machine owner's go-ahead

- a download from the internet (freebuff's npm package);
- a sign-in to any agent;
- any agent session that spends the account's usage;
- running a local model;
- an install into the real agent configs rather than the sandboxed profile.
