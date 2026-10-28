# Two ways to choose a change's evidence

A change card can name up to 50 files as its evidence, and the page says whether they are still the bytes the agent
measured ("current"), have moved ("stale"), or cannot be checked ("unknown"). A digest confirms a guess about a file,
so which files may be digested matters. Up to 1.2.2 that was decided by **names**: an allowlist of kinds plus a list of
secret-shaped names. Names lose to the next name. An audit found 34 of 35 new secret-shaped names still digested, and
16 of 32 honest names refused (`password_policy.md`, `keys.py`, `key.md`). Measured on the audit's full lists at
1.2.2, in a project bound to the agent: 34 of 89 secret-shaped names digest, and 22 of 60 honest names are refused.

Two replacements are built, each on its own branch, and each decides by **structure** instead. **The git index (way
2) is the chosen way**; folders first stays described here as the alternative that was weighed. Review note: revisit
in a later review if it needs more guards.

Both keep everything about *how* a file is read: no link or junction at any level, no hard link, no alternate stream,
no device or short name, the real path inside its root, one checked read-only handle, at most 50 files a record and
200 records an agent, the 256 MB read budget, the 60-second in-memory cache, and roots that must be given. Both leave
the old full name list switched off (it stays in `sources/evidence.py` as a belt that can be switched on, at the cost of
refusing honest names again); the git-index way adds a short belt of names that are almost never honest, for listed
files. Each is one small module behind the same interface (`evidence.Policy`), so a third way
can be added without touching `change.py`.

## Way 1: folders first (`v2-b4-folders`, `sources/evidence_folders.py`)

**Evidence is** a file directly inside one of the agent's `cv/<project>/` document folders that the page lists (one
holding a MASTER.md), under a plain name; a file directly inside a rule-card folder whose card names the agent as its
seat or holds its layer of rules; and the agent's own requests and changes files.

**Refused (unknown):** everything else. A project's files, the rest of the agent's home (its CLAUDE.md included), a
subfolder of a document folder, a hidden name (`.gitignore`), another agent's folders, a folder with no MASTER.md.

**Cost:** nothing extra. The folders come from what the readers already found; no file is opened to decide.

**Failure modes:** it is narrow. A change about code or a script in a project can never be current, because a project
is not where an agent keeps notes. A rule card whose `seat:` is free text ("the desk seat") binds to no one. A secret
an agent writes into its own notes folder under a plain name is evidence like any note (it is the agent's own file).

## Way 2: git index (`v2-b4-gitindex`, `sources/evidence_gitindex.py`)

**The premise.** Evidence is what the project's index lists. The index is not a record of what was committed or
reviewed: an agent can write it (`git add -f .env` lists `.env` with no commit), and it can write objects and commits
too, so no reading of a repository is a boundary against an agent that breaks rules. This way chooses relevant files
for a digest to confirm; it is not a defence against such an agent.

**Evidence is** a file inside the agent's home or a bound project that the nearest real git repository lists in its
index as an ordinary file. The repository is the nearest `.git` folder, searched up to the root and above it only
while still inside one of the agent's roots (so a home below a shared repository's top is read when that top is
itself a named root, and only the home's files are asked of it). It must be real: `.git/HEAD` a plain file holding a
commit id of the right length, or naming a ref git would write that exists (a loose ref file under `.git/refs`
holding a commit id, or a line of `.git/packed-refs`). The index is read in pure Python (versions 2, 3 and 4; SHA-1
or SHA-256); nothing runs git.

**Refused (unknown):** untracked and ignored files; an entry that is a symlink, a submodule, a merge conflict,
intent-to-add (`git add -N`) or skip-worktree; a `.git` with no HEAD, or one naming neither a ref nor a commit (a
hand-built index in a plain folder), or naming a ref that does not exist or that git would not write (`..`, a part
starting with a dot, `.lock`); a branch with no commit yet; a repository whose `.git` is a file (a linked worktree or
a submodule) or a link; a repository whose top is above every root; an index that is sparse, split, over 64 MB, a
hard link, of another version, or whose checksum does not match; and a listed file the short name belt names,
refused with that reason. The belt (`TRACKED_BELT` and `TRACKED_DATA` in the module) names keys and key stores
(`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx`, `id_rsa*`, `id_ed25519*`, `id_ecdsa*`, `id_dsa*`), credential folders
(`.ssh*`, `.aws`, `.gnupg`, `.kube`), credential dotfiles (`.env*`, `.npmrc`, `.netrc`, `.pgpass`,
`.git-credentials`), and secret, token, wallet, vault, password and credentials as their own word; `key`, `auth`,
`env`, `seed` and the like only as data (`.json`, `.txt`, `.yaml` ...). Measured on the audit's lists, tracked with
`git add -f` in a real repository: 89 of 89 secret names refused (16 at f8dfae1), 0 of 60 honest names (1 at
f8dfae1).

**Cost:** one read of each repository's index per page build, counted against the read budget, then cached for 60 s.
Measured: a real repository's index (1,412 files, 158 KB) parses in about 1 ms; a 200,000-entry index (13.6 MB) in 0.19 s.

**Failure modes:** a new note is unknown until it is added to the index. Work done in a linked git worktree is
unknown (its `.git` is a file, not followed), and so is a home below a repository whose top is above every root. A
listed secret under a name the short belt does not name is evidence. The belt's cost: a few common names the audit
found holding secrets are refused even when honest (`app.log`, `server.log`, `access.log`, `appsettings.json`,
`settings.xml`, `known_hosts`, `session.json`), while `tokenizer.py`, `tokens.md`, `wallets.md`, `keys.py`, `key.md`
and `password_policy.md` digest. A repository just made with `git init` and `git add`, with no commit, is unknown
until its first commit. An agent that writes the index and a ref can admit any file under any other name: the
premise above.

## What one catches that the other misses

| case | folders first | git index |
|---|---|---|
| an untracked `oauth.json` or `wallet.json` in a project | refused | refused |
| a listed `wallet.json` or `.env` in a project (`git add -f`) | refused | refused (short belt) |
| a listed `oauth.json` or `id_ed25519` in a project | refused | refused (short belt) |
| a listed secret under a plain name (`deploy_config.json`) | refused | **evidence** |
| a hand-written HEAD naming a ref that does not exist | not affected | refused |
| a plain-named secret written into the agent's own `cv/` notes | **evidence** | refused unless listed |
| a tracked script or source file in a project (`run.ps1`, `src/x.py`) | **refused** | evidence |
| a new note in `cv/<project>/`, not yet added | evidence | **refused** |
| the agent's own `requests.jsonl` / `changes.jsonl` | evidence | evidence only if listed |
| a hand-built `.git/index` in a plain folder (no HEAD) | not affected | refused |
| a hidden file (`.gitignore`) or a file in a subfolder | refused | evidence if tracked |
| work in a linked worktree (`.git` is a file) | not affected | **refused** |
| honest names the old list refused (`password_policy.md`, `keys.py`) | evidence (in `cv/`) | evidence (if tracked) |
| cost per build | none | one index read per repository |

## In one line

Folders first is the stricter fence and costs nothing, but it cannot vouch for code. The git index chooses the code
and notes a project lists as its own, at the cost of one index read, but it says "unknown" for anything not yet added
and for linked worktrees; it is a choice of relevant files, not a boundary, since an agent can write the index.
Neither rests on a name (the git index keeps a short belt for names almost never honest). The git index is the chosen
way; revisit in a later review if it needs more guards. They could be combined (a file is evidence when either
admits it, or only when both do) by adding a third policy module; that is not built.
