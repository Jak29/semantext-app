"""Which of the reader's acts a tool call is, where that can be told from the call alone.

Used by the decision to let the person's words HOLD a call (reading.py): a call this cannot classify gets no hold from
the words, and the space's gates and default decide it as before. So a miss here costs a hold the words asked for, and
never releases anything; a wrong class costs an extra ask at most. Every choice below leans that way: when a command
is unclear it is given the extra class, never dropped.

r2 (Koinos's attack on the reader's wiring: its regexes were quadratic, 12 s on a 64 KiB command, and it held `git commit -m
'fix push bug'`): a shell command is cut into segments at ; & | and line ends, and each segment is read as a list of
words, so the work is linear in the command and a word inside quotes is never an act.
A command longer than MAX_COMMAND is not read at all and counts as every material act (only a hold can follow).

r3 (Koinos's second attack, 1,075 commands, and the gate attack, 346; both are tests/data/actclass/): the reading is
now ONE pass of a real lexer (quotes, escapes, line continuations, here-documents and here-strings, redirections,
$(...), backticks, ( ) and { } groups, comments), so a quoted value is a word with its quotes taken off:
`git -C "$REPO" push`, `"git" push` and `git p""ush` all name git push, and `git commit -m 'fix push bug'` still
does not. A literal newline ends a command; a backslash-newline (sh) or a backtick-newline (PowerShell) does not.
A lone CR ends a statement. Four things are READ AS CODE on purpose, each with the same segment rules: the argument
of a shell or PowerShell `-c`/`-Command` (any flag before it, `-EncodedCommand` decoded), of an interpreter's
`-c`/`-e`/`-r` (call sites only: `os.remove(`, never the word in a string), of an SQL client's statement
(`psql -c`, `mysql -e`, `sqlite3 db "..."`, `sqlcmd -Q`, `wrangler d1 execute --command`), and of a remote shell
(`ssh host '...'`, `docker exec`, `kubectl exec --`, `gcloud compute ssh --command`, `fly ssh console -C`).
Prefix wrappers (sudo -u x, env -i, timeout 60, nice -n 10, nohup, watch, wsl, xargs, find -exec, ! , time) and the
control words (if/then/do/while) are looked through. The act is read from the SUBCOMMAND, not from any word: `cargo
test publish` is a test, `kubectl describe deploy` a read. Read-only subcommands are no act; a dry run (--dry-run, -n,
-WhatIf) and a help page (--help, `git help push`) are NOT: they are named as the act, as 1.7.0 named them. HTTP verbs are read as what they are (DELETE is a delete; POST, PUT, PATCH
a send); a copy is a send going out and a download coming in.
An OPAQUE evaluation counts as every material act, as an over-long command does: eval or iex with an argument that
is not plain text, a pipe into sh/bash/pwsh/iex/python that does not come from an echo, `bash <(...)`, a program held
in a variable ($cmd, "$(which rm)") and run, and anything nested deeper than MAX_DEPTH or costing more than a fixed
multiple of the command's length to read (nesting is bounded so a hostile command cannot make the reading slow).

r4 (Orithises's third attack, 1,830 commands, v2-24; it killed r3 on seven counts, all closed here):
TIME. Two texts were read again and again: one here-document under many `find -exec A ';' -exec B ';' <<EOF` siblings (38 s
at 64 KiB) and the list of words under a long chain of wrappers after a pipe. A text handed to several readers is now read
once and its answer kept, every reading is charged to the work budget, a chain of wrappers is walked by index and at
most MAX_HOPS long, and a `#` comment finds the next CR once. The shapes are timed in the tests (64 KiB under 0.5 s).
OPAQUE. A program word that IS an expansion ($cmd, $(curl u), a backtick) is opaque even when a URL inside it holds a
slash: only a word that BEGINS with an expansion and goes on with a path ($HOME/bin/x) is a script by name.
`sh -c "$(curl -fsSL URL)"`, `python -c "$CODE"` and `node -e "$(cat f)"` are every act. A pipe into `sh -s`, `bash -s` or
`python3 -` runs the piped program whatever arguments follow (rustup, rvm, bun, poetry); `sh script.sh` and `bash -c x` do
not. A pipe into a group `( ... )` reaches the group's first reader. A list-form call (["bash","-lc","git push"]) is read
as an ARGV: each element is one word, so the element after -c is the whole script and an element holding `;` is data.
An option cluster ending in a letter that takes a value (`sudo -iu x`, `bash -euo pipefail -c`) takes the next word.
SUBSHELLS AND BLOCKS. A bash `( ... )` and a PowerShell `( ... )` or `{ ... }` are classified by what they hold, and
PowerShell control flow (if, foreach, try, switch, function) is looked through; `$x.Length` is an expression, and only
`& $x` runs a value. Only `& (expr)`, and what cannot be read, is opaque.
WRAPPERS. Runners (poetry, uv, pipenv, pdm, hatch, bundle, conda, mise, volta, doppler, op, aws-vault, direnv, dotenv,
nix, pnpm/yarn/npm exec and a bin run by its name) and strace, gtimeout, wsl -e, env -S, flock -c are looked through.
The acts the base named that r4 had lost are named again (docker builder/service/stack/secret rm, playwright install,
heroku run, git clone -n; and in r5 the 23 the attacker found, `helm -n prod uninstall api` among them: restored and
pinned in tests/data/actclass/round3_regress.json). Escapes in text a shell runs are decoded (printf, echo -e, $'...').

r5 (Orithises's fourth attack, v2-25; it killed r4 on TIME again, and on a regression in the costly direction). A15, the
structural cure: every pattern in this file is LINEAR BY CONSTRUCTION from Python 3.11 (3.10 has no possessive repeats:
r6, E9), by four rules written above _ORD_SH (a repeat that can overlap what follows is possessive; a pattern used with
.match carries \\A so a search cannot restart it at every character; a pattern no regex can make linear is a plain loop,
as _blank, _method_verb and _var_end are; a repeat that cannot be possessive is bounded). tests/test_actclass_linear.py
finds every pattern in the module by itself and times it on its own fragments at 16 and 64 KiB, so the next quadratic
one fails a test before an attacker finds it; it also holds the shapes of every attacker, timed through decide.decide.
THE BUDGET: every text handed to a regex or a reader (an SQL or code string, an ftp script, a printf format, a group
re-lexed after a pipe) is charged to the work budget (WORK_FACTOR x the command's length + WORK_SLACK), a text handed to
many siblings (the here-documents and here-strings of one segment) is read once per kind of reader and its answer kept,
and a reading that spent past the budget is every act whatever part noticed. THE BACKSTOP: a command longer than
MAX_COMMAND (64 KiB; on 3.10 the smaller MAX_COMMAND_310, E9) is every act and is not lexed or read. A11 printf's
format; A12 `.send.send...`; A14 find with many -exec and many here-strings; A21 `\'` runs: all linear.
A13: a program held in a variable is opaque wherever it is RUN: `& $x`, `. $x`, `Start-Process $x`, `cmd /c $x`,
`-Command $x`, `sudo $x`, `wsl $x`, `docker/kubectl exec c $x`, `Invoke-Command -ScriptBlock $sb`, `[scriptblock]::Create`;
only a bare `$x.Length` statement is an expression (r6, E3 below: in every command of a text the outer shell expanded).
A Start-Process argument list is read whole (`'a', 'b'`, `'a','b'`, `@('a','b')`; r6, E1: as the line the program gets).
A16/A17: an option no table lists can take a value, and the value was taken for the subcommand; a call of a program in
ALT_PROGS (docker, kubectl, helm, aws, az, gcloud, npm, cargo, gh...; the claim is made for those only, r6 E6) is ALSO read
as if every option took the word after it, and both readings count (the costly direction); `help` as an option's value is
not a help page; a leading `+toolchain` (cargo +nightly) is not the subcommand; the tables gained the options the attacker
named. A18: the pipe walk looks through every wrapper in WRAP with its option forms, `bash /dev/stdin`, `python3 -E -`,
`pwsh -File -`, `sudo -s`, and an unknown program or ssh/docker/kubectl before a shell on a pipe is opaque (r6, E4: and the
shapes listed there). A19: $(...) and backticks in a here-string and in an UNQUOTED here-document (and a PowerShell @" "@)
are read; a quoted delimiter ('EOF', "EOF", \\EOF) is data, and so is an escaped `\\$(...)` (r6, E8). A20: a ( ) or { }
group that runs a script or program by its own name and names nothing for it is opaque, except an everyday target (r6, E5:
the one list below).

r6 (the round-4 attack on r5, v2-26; it killed r5 on two regressions in the costly direction and on claims wider than
the code). E1: Start-Process joins an -ArgumentList array with single spaces (documented) and the program splits that
ONE line by the Windows rules (_win_argv: quotes inside an item are kept), so `-ArgumentList 'push origin main',
'--force'` is git push origin main --force; r5 kept an item holding a space as one word and named nothing. E2: aws s3
cp/mv/sync read the SOURCE and the DESTINATION as the first two operands, the AWS CLI's order (r5 took the last two, and
a --grants list made an upload a download); each option of the table has its own shape: --grants and --filters take a
list (every word to the next option), --sse, --sse-c, --sse-c-copy-source and --request-payer an optional value (the
next word only when it is a legal one: AES256, aws:kms, aws:kms:dsse / AES256 / requester), the rest one word; and where
the operands are not certain (not two of them, or an option no table lists before a word) every act their order allows
is named, a local path before an s3:// one an upload, the reverse a download, both when both occur. A third reading
takes the valued options of the tables r5 widened (aws, docker, kubectl, helm) as flags while they stand before the
words that name the act (`helm -n uninstall api`); the attacker's scan of every newly valued option at every position
(3,045 calls) now loses nothing 99f9116 named (r5 lost 570; tests/data/actclass/round4_scan.json). E3: a text the outer
shell EXPANDED before a wrapper runs it (`cmd /c "cd /d C:\\app && $cmd"`, `-Command "Set-Location $root; $task"`) runs
the value of a variable at the head of ANY of its commands, not only the first; a text written literally holds the
child's own variables, read by the child's rules (in PowerShell a `$x` or `$x.Prop` statement is a value: `pwsh -Command
'$PSVersionTable.PSVersion'` reads a property, E8); a PowerShell `(expr)` a wrapper is handed as its program is computed
(`Start-Process (Get-Command git).Source`, `cmd /c (Get-Content x -Raw)`, `. (expr)` as `& (expr)`, a -FilePath held in
a value); a script block held in a value runs, opaque, by every way listed: `& $sb`, `. $sb`, `$sb.Invoke()` (and
BeginInvoke, InvokeReturnAsIs), Invoke-Command by name or by position (`Invoke-Command $sb`, `icm web01 $block`, unless
a block is written in the call), Start-Job, Start-ThreadJob, ForEach-Object, Where-Object and Measure-Command; runas
reads its one program string (`runas /user:x "cmd /c rd /s /q C:\\b"`). E4: a pipe into these runs what it reads, every
act: ssh with no remote command, or whose remote command runs a program reading standard input, quoted or not (`| ssh h
'bash -s'`, `"sudo bash -s"`, `'cd /srv && bash'`; not with -N); `source /dev/stdin`, `. /dev/stdin`; parallel with no
command (and `parallel ::: 'cmd' ...` reads its arguments as commands); xargs handing what it reads to `bash -c`/`sh -c`
with no script; `sudo --login`, `sudo --shell`, su with no -c and su (runuser) whose -c text reads standard input; a
shell's -c or a PowerShell -Command text that does (`sh -c 'exec bash'`); lua, luajit, julia, Rscript and tclsh reading
standard input; an interpreter's valued options before it (`node -r dotenv/config`). E5: a group's target is everyday
only when EVERY segment of its name (split on `: - . _ /`) is one of these words, and the first is one of r5's 26
(below): test, tests, testing, unit, e2e, integration, int, spec, specs, jest, vitest, mocha, pytest, build, builds,
compile, lint, linting, fix, format, fmt, prettier, eslint, stylelint, check, checks, verify, validate, typecheck,
types, type, tsc, dev, develop, development, start, serve, server, watch, preview, storybook, docs, doc, html, coverage,
cov, bench, benchmark, benchmarks, all, prod, production, local, ci, debug, ssr, client, web, ui, css, js, ts, styles,
assets, analyze, analyse, report, quick, fast, full. The first segment must be one of the 26 names r5 exempted, so
nothing r5 held is released (`build:prod` is everyday; `make prod`, `npm run ci` and `type-check` stay opaque, as
3e5e2ac held them): test, tests, build, lint, format, fmt, check, dev, start, serve, docs, html, typecheck, types,
coverage, bench, watch, compile, all, storybook, preview, prettier, eslint, tsc, pytest, doc. A segment that names a
material act never is everyday: deploy, publish, release, upload, push, ship, delete, rm, clean, reset, drop, destroy,
purge, wipe, prune, send, mail, pay, migrate, seed. `python -m X` in a group is opaque unless X is pytest, unittest,
doctest, mypy, ruff, black, isort, flake8, pylint, pyflakes, pycodestyle, pydocstyle, bandit, coverage, build, pip,
venv, virtualenv, http.server, json.tool, timeit, cProfile, profile, pdb, pydoc, compileall, py_compile, pyright or
tabnanny. A bash `{ ...; }` group is read like a ( ) one. r5 exempted a FIRST segment from a list of 26 names, so `npm
run preview:deploy` was released. Measured on the everyday set (27 bash, 64 PowerShell): 0 with a class before and
after. E6: git (--attr-source), redis-cli (--cacert, --sni... and -x is a flag), s3cmd (-c/--config) and minikube (-p)
gained the options the attacker named; redis-cli and minikube joined ALT_PROGS; a PowerShell array handed to a program
is its items (`& git @('push','origin','main')`). E8: a property read in a literal -Command text, a block that is
assigned and not run (`$d = { .\\deploy.ps1 }`), and an escaped substitution in an unquoted here-document get no class.
E7: tests/test_actclass_linear.py prints how many module-level patterns it guards and how many shapes it times (no
number is written here to go stale); the guard's fragments hold every literal of a pattern WITH the punctuation before
it (`.send`, `.delete`), so the old _METHOD is caught by the generic guard alone. E9: on Python 3.10, which has no
possessive repeats, the shim compiles every pattern greedy (correct, not linear), so there the backstop is
MAX_COMMAND_310, 2 KiB, measured on the greedy copy (the comment above _POSSESSIVE_OK): printf's run of zeros, the one
known shape that grows faster than the command, takes 0.14 s at 2 KiB and 0.56 s at 4 KiB; a longer command on 3.10 is
every act (the cheap direction).

Read for a shell call: the command string (a `command`, `cmd`, `script` or `CommandLine` field; a list is an argv). For
any other tool: its name, where a name that reads as a read (list_, get_, search_) and holds no writing word is no act.
Still missed, stated. Measured: the attack corpora (1,421 commands of r3, 1,830 of r4, and the 471 fresh ones of the r5
attack) are named in full and the benign ones get a class in 0.4% (the 1,830) and 1.3% (the 150 fresh benign: `& $sb` of a
script block written in the same command, and `uv run python main.py`, which may fetch), but the tables were tuned on all
of them; the commands written after each round's fixes missed none and were written by the same hand, so expect a miss rate
above zero on the next attacker's commands (r3 had 0 on its own corpora and 11.1% on the next one, r4 had 0 and 2.8%,
r5 had 0 and 9.4%: 15 of the round-4 attacker's 160 fresh ones; r6, written after reading them, still misses 6).
Named limits: a script run by its own name (`./deploy.sh`, `sh cleanup.sh`, `npm run release`, `yarn deploy`, `just
deploy`, `task deploy`, `pwsh -File x.ps1`, `ansible-playbook`, `go run ./cmd/x`) and a file handed to an SQL client
(`psql -f drop.sql`, `sqlite3 db < x.sql`) at the TOP level of a command (in a ( ) or { } group, A20, it is opaque,
except an everyday target, every segment of its name on the E5 list: a project whose `build` ships something is released
in a group; the blanket rule was measured at 5 of 27 bash and 1 of 64 PowerShell everyday commands with a false class, 1
of 391 Koinos benign, 0 of 472 in the 1,830 corpus), `make deploy` (only `make clean` is read); a function body is read
as a group where it is defined, and a function defined in one call and run in another is not; `. "$file"` in sh (a
variable path, as in a profile, is a file and not a program; in PowerShell `. $x` and `. (expr)` are opaque); an option
this file's tables do not list is covered by the second reading (`_alt_words`) only for ALT_PROGS and only while it
stands before the subcommand or between a command group and its subcommand: `docker run --unknown-flag x IMAGE cmd`
reads x as the image, and a CLI outside ALT_PROGS (git, s3cmd...) reads only the options its table lists (`git --unknown
x push` names nothing); that second reading gives every option a value, so a flag before an operand loses the operand
there (`aws s3 cp --recursive ./d s3://b` also reads a download; `rclone sync -n a r:b` gets a class: the cheap
direction); a cmd variable (`cmd /c "%CMD%"`) is not read as a program; a cmdlet that keeps a script block to run later
(Register-ObjectEvent -Action) is not read; the image's own entrypoint is not known (`docker run curlimages/curl -X
DELETE u` names a download only); text piped from a file (`cat x.sql | psql`, `ssh h 'bash -s' < cleanup.sh`, which is
unnamed unless the pipe ends in a shell, where it is every act); a program held in a variable that is assigned in an
earlier command and not run through $x, an alias, a function defined in one call and run in another; an act done by a
program the command starts (`bash cleanup.sh`), including `tee >(sh)`; the programs that print shell code for `eval` are
not an act when they are in the table of setup generators (`eval "$(ssh-agent -s)"`, `eval "$(pyenv init -)"`, `source
<(kubectl completion bash)`), and a program of that name that prints anything else is read as that; a tool whose name
says nothing (the MCP tools that run SQL or code: `write_query`, `run_code`, `execute_cell`); code read only at its call
sites, so an act spelled through an alias, getattr, a wrapper function or a built-up name is missed, and any
string-built SQL or base64-decoded program; an option abbreviated in a way the tool accepts but this table does not
know; the many CLIs beyond those named (a CLI in no table names nothing); an input that is not a dict with one of the
command keys (a nested {"input": {...}}, an `args` list, a list holding a non-string); `Set-Content` is a delete (it
overwrites); and read-only verbs outside the lists given (an unknown subcommand of a cloud CLI that deletes is missed
unless its name is `delete`, `remove`, `destroy`, `rm`, `purge`, `terminate`, `uninstall`, `unset`, `prune`, `wipe`,
`erase`). Wrapper depth beyond MAX_DEPTH, a chain beyond MAX_HOPS, or reading cost beyond 6x the command, is every act.
Judged against the labels: a plain `cargo build`, `gradle build` or `dotnet publish` is a build and not a download or
a publish; `curl https://api.stripe.com/v1/charges` with no data is a GET and not a payment; `iwr u` is a read.
"""
from __future__ import annotations

import base64
import re as _re
import sys
from functools import lru_cache
import unicodedata

from semantext import normal   # absolute: this file is also loaded on its own, by path (the greedy copy, attack harnesses)

# Possessive quantifiers (`*+`, `++`, `?+`) are Python 3.11's; the package lists 3.10, and the gate reader imports there
# (docs/security-floor.md item 1, kept: E9). On 3.10 every pattern here is compiled with them turned into the plain
# greedy repeat (the same matches on every input the tests hold, tested by
# tests/test_actclass_linear.py::test_the_greedy_fallback_matches_what_the_possessive_patterns_match), which is correct
# but NOT linear by construction: the guarantee of r5 holds from 3.11. On 3.10 the worst case is BOUNDED instead, by a
# smaller backstop (MAX_COMMAND_310 below), measured on the greedy copy loaded as the test loads it (version_info set to
# 3.10), best of 2 through acts_of_call. printf's run of zeros (the greedy PRINTF_SPEC) is the one known shape that grows
# faster than the command: 0.03 s at 1 KiB, 0.14 s at 2 KiB, 0.56 s at 4 KiB, 2.3 s at 8 KiB (x4 per doubling:
# quadratic). The method chains (at most 0.01 s at 64 KiB), _blank on runs of \' (0.1 s) and find with many here-strings
# (0.09 s) stay linear there, and at 2 KiB every other shape the tests time takes under 0.02 s. On the guard's own
# fragments, of the 35 patterns the shim changes PRINTF_SPEC is the slowest (0.08 to 0.11 s a search at 2 KiB, 0.29 s at
# 4 KiB; every other one under 0.003 s at 4 KiB). 2 KiB keeps every one of them under the 0.5 s the end-to-end tests
# assert, with room for a slower machine; 4 KiB would not. No pattern can backtrack without end there (which no size
# would bound): only two nest an unbounded repeat, each unit ending in a character its repeat cannot take. Held by the
# tests (tests/test_actclass_linear.py)
#   test_e9_on_python_3_10_a_smaller_backstop_bounds_the_greedy_patterns (every timed shape at that size),
#   test_e9_the_guard_holds_on_the_greedy_patterns_at_the_smaller_backstop,
#   test_e9_no_new_greedy_pattern_nests_an_unbounded_repeat and
#   test_e9_the_shim_leaves_no_pattern_that_3_10_cannot_parse.
#
# 3.11 alone is not enough to know (L2.1). CPython 3.11.0 to 3.11.4 have possessive repeats and match two shapes of them
# wrongly (CPython issues 100061 and 106052, both fixed in 3.11.5; Debian 12 ships 3.11.2). Two patterns here have the
# first shape, a possessive repeat over a group that begins with a negative look-ahead (_FTP_PUT, _SQL_EXPLAIN_RUNS),
# and there the fault would be a missed act. So the interpreter is asked, not only its version: each upstream
# reproduction must come out right, or the patterns are compiled greedy as on 3.10, with the smaller backstop. Not run
# on a real 3.11.0 to 3.11.4 (none here); the path such an interpreter takes is the one run on a real 3.10. Held by
# tests/test_actclass_linear.py::test_l21_the_interpreter_is_asked_whether_possessive_repeats_match_rightly.


def _possessive_right() -> bool:
    try:
        return (_re.findall("(((?!C).)++)", "ABC") == [("AB", "B")]       # issue 100061 gave [("ABC", "B")]
                and _re.fullmatch("(?:ab?c)*+", "a") is None)              # issue 106052 matched
    except _re.error:
        return False


_POSSESSIVE_OK = sys.version_info >= (3, 11) and _possessive_right()
_DEPOSSESS = _re.compile(r"(?<!\\)([*+?}])\+")


class _Re:
    """The re module, with compile() giving up possessive quantifiers where the interpreter has none."""

    def __getattr__(self, name):
        return getattr(_re, name)

    @staticmethod
    def compile(pattern, flags=0):
        return _re.compile(pattern if _POSSESSIVE_OK else _DEPOSSESS.sub(r"\1", pattern), flags)


re = _Re()

# THE BACKSTOP (A15e): a command longer than this is every act and is not read at all. E9: on Python 3.10 the patterns are
# greedy (the shim above) and not linear by construction, so the worst case is bounded by a smaller backstop instead,
# chosen by measuring the greedy copy on the worst known shapes (the numbers are in the comment above _POSSESSIVE_OK).
MAX_COMMAND_310 = 2 * 1024
MAX_COMMAND = 64 * 1024 if _POSSESSIVE_OK else MAX_COMMAND_310
WORK_FACTOR = 6                     # the work budget: this many units per character of the command,
WORK_SLACK = 4096                   # plus this many; a unit is a character a lexer, a regex or a reader is handed
MAX_DEPTH = 8                       # wrappers, substitutions and groups nested deeper than this are opaque
ORDER = ("publish", "push", "delete", "send", "pay", "download")
ALL = frozenset(ORDER)

SHELL_NAMES = {"bash", "shell", "sh", "powershell", "pwsh", "cmd", "terminal", "run_command", "execute_command",
               "run_shell_command", "exec"}
PS_NAMES = {"powershell", "pwsh", "cmd"}      # tools whose commands are PowerShell or cmd text: a backslash is a path

NAME = {
    "send": re.compile(r"send|email|mail|message|slack|post_?message|reply|forward|notify|sms|tweet|"
                       r"create_issue|add_\w{0,256}comment|create_comment|post_comment", re.I),   # {0,256}: the name is cut at 256
    "publish": re.compile(r"publish|deploy|release|upload|share|merge_pull|create_pull|post(?!gres)|"
                          r"create_issue|create_repo|create_or_update|kubectl_apply|helm_install|terraform_apply", re.I),
    "delete": re.compile(r"delete|remove|trash|destroy|purge|wipe|erase|drop|execute_sql", re.I),
    "pay": re.compile(r"pay|purchase|checkout|transfer|charge|buy|order|refund", re.I),
    "download": re.compile(r"download|install|fetch_file", re.I),
    "push": re.compile(r"push|create_or_update_file", re.I),
}
# A tool whose name reads as a read ("list_orders", "get_channel_history", "search_threads") and holds no writing word
# is a read, whatever its server is called ("slack", "gmail", "shopify"): the server's name is not the act (A8).
_NAME_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
_READ_WORDS = frozenset({"get", "list", "search", "read", "describe", "query", "find", "show", "view", "check",
                         "status", "count", "lookup", "retrieve", "browse", "inspect", "preview", "history", "recent"})
_WRITE_WORDS = frozenset({"send", "post", "create", "delete", "remove", "update", "upload", "publish", "reply",
                          "forward", "merge", "transfer", "pay", "charge", "buy", "set", "write", "put", "add",
                          "execute", "run", "apply", "deploy", "push", "drop", "destroy", "purge", "wipe",
                          "erase", "trash", "share", "notify", "email", "tweet", "checkout", "download", "edit",
                          "modify", "patch", "refund", "submit", "start", "stop", "restart", "cancel", "close",
                          "approve", "comment", "invite", "move", "copy", "rename", "restore", "revoke", "grant",
                          "sign", "place", "capture", "confirm"})


# F4: a name that joins two verbs (`search_and_purchase`, `count_then_mail`, `find_or_order`, `list_plus_install`) does
# the second as well as the first; and a material verb before the read word (`mcp__a__purchase_check`,
# `install_updates_check`) is the tool's act, not its server's name. Every word of _WRITE_WORDS already refuses the read
# wherever it stands; of the rest, only these are read as verbs before a read word. A stated limit: order, release,
# message, mail, sms and tweet are nouns there as often as verbs (`chat_message_search`, `order_lookup` are reads), so a
# name such as `release_check` with no joining word is read as a read
_NAME_CONJ = frozenset({"and", "then", "or", "plus", "also", "n"})
_HEAD_VERBS = frozenset({"purchase", "install", "reinstall", "uninstall"})
# G8: `to`, `for`, `with`, `via` and a number between words join a second action as `and` does when the word after them
# is an act word in its bare (verb) form (`find_to_purchase`, `search_for_install`, `find2purchase`,
# `lookup_via_message`). A plural or other noun after them is the thing read: `search_for_messages`, `get_orders_for_x`
# stay reads (chosen: a bare verb after the joiner is a second action, a plural is what is searched for)
_NAME_JOINERS = frozenset({"to", "for", "with", "via"})
_JOIN_ACTS = frozenset({"purchase", "order", "install", "reinstall", "uninstall", "release", "message", "mail", "email",
                        "sms", "tweet", "slack", "notify", "reply", "forward", "send", "post", "publish", "deploy",
                        "upload", "share", "delete", "remove", "trash", "destroy", "purge", "wipe", "erase", "drop",
                        "pay", "checkout", "transfer", "charge", "buy", "refund", "download", "push"})


def _joined_act(ws: list) -> bool:
    """Whether a joiner or a number stands between two words and the word after it is a bare act verb (G8)."""
    return any((ws[i] in _NAME_JOINERS or ws[i].isdigit()) and ws[i + 1] in _JOIN_ACTS for i in range(1, len(ws) - 1))


def _name_acts(nm: str) -> set:
    nm = nm[:256]
    acts = {a for a, rx in NAME.items() if rx.search(nm)}
    if not acts:
        return acts
    # the tool is everything after the server's name (split ONCE: a server names its own tools, so `mcp__a__buy__list`
    # is the tool `buy__list`, not `list`), and a `__` inside it joins two words as `and` does
    tool = nm[5:].split("__", 1)[-1] if nm.lower().startswith("mcp__") else nm
    ws = [w.lower() for w in _NAME_WORDS.findall(tool)]
    first = next((i for i, w in enumerate(ws) if w in _READ_WORDS), None)
    if first is None or _WRITE_WORDS.intersection(w.lower() for w in _NAME_WORDS.findall(nm)) or \
            _NAME_CONJ.intersection(ws) or "__" in tool or _joined_act(ws) or \
            any(ch in tool for ch in "+&|") or \
            _HEAD_VERBS.intersection(ws[:first]):
        return acts
    return set()

# ---------------------------------------------------------------------------------------------------------------
# the lexer: one linear pass; every quoted value is a word with its quotes taken off and q set
# ---------------------------------------------------------------------------------------------------------------

# PowerShell's assignment operators, written as their own word (`$r = & $x`); `&` after one is the call operator
_PS_ASSIGN_OPS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "??="})


class Word:
    """One shell word. t: its text with quotes and escapes resolved. q: any part of it was quoted or escaped.
    dyn: it holds an expansion ($x, $(...), a group). subs: the command texts inside it ($(...), `...`, ( ), { }).
    commas: PowerShell only, the indexes in t of the commas that were written outside quotes, so `'-c','rm x'` (an array
    in an argument list) can be told from one string with a comma in it."""
    __slots__ = ("t", "q", "dyn", "subs", "proc", "commas")

    def __init__(self, t, q, dyn, subs, proc, commas=None):
        self.t, self.q, self.dyn, self.subs, self.proc, self.commas = t, q, dyn, subs, proc, commas


class Seg:
    """One simple command: its words, its redirections, the here-document and here-string text handed to it, the
    operator that ended it, and whether PowerShell's call operator (& or .) began it (call)."""
    __slots__ = ("words", "redirs", "heredocs", "herestr", "op", "call", "hsubs", "outred")

    def __init__(self):
        self.words, self.redirs, self.heredocs, self.herestr, self.op = [], [], [], [], ""
        self.call = False
        self.hsubs = []                 # the $(...) and `...` texts inside an UNQUOTED here-document (it expands them)
        self.outred = None              # whether a redirection writes a file; found once, however many readers ask


# R5 (A15): every pattern below is linear BY CONSTRUCTION, not by luck, and tests/test_actclass_linear.py times each one
# on inputs built from its own fragments. The rules, each paid for by a finding:
#   1. a quantified part that is followed by something it could also match is POSSESSIVE (*+, ++, ?+) or atomic, so a
#      failed match gives nothing back and tries nothing else;
#   2. a pattern is searched only where a match can begin: one that is used with .match carries \A, so a search of a long
#      text cannot restart it at every character and rescan the rest (the old _METHOD, _PLAIN_ARG, ENV_ASSIGN);
#   3. a pattern that would need to look back or retry from every start is a plain loop instead (_blank, _method_verb,
#      _var_end), because no regex can be made linear for it;
#   4. a repeat that cannot be made possessive without changing what it means is BOUNDED ({0,N}), so the work per start
#      has a fixed ceiling.
# Add a pattern: put it at module level (the guard test finds it by itself) and keep to these four rules.
_ORD_SH = re.compile(r"[^\s'\"\\$`;&|()<>#@]++")
_ORD_PS = re.compile(r"[^\s'\"`$;&|()<>{}#@]++")
_WS = re.compile(r"[ \t\f\v]++")
_SPECIAL = re.compile(r"""['"\\`(){}]""")
_DQ_SH = re.compile(r'[\\"]')
_DQ_PS = re.compile(r'[`"]')
_DQ_ESC_SH = re.compile(r'\\(["\\$`\n])')
_DQ_ESC_PS = re.compile(r"`(.)", re.S)
_SUB_SH = re.compile(r"\$\(|`")
_SUB_PS = re.compile(r"\$\(")


_ANSI_ESC = re.compile(r"\\(x[0-9a-fA-F]{1,2}|u[0-9a-fA-F]{1,4}|U[0-9a-fA-F]{1,8}|[0-7]{1,3}|c.|.)", re.S)
_ANSI_ONE = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "v": "\v",
             "\\": "\\", "'": "'", '"': '"', "?": "?"}


def _ansi_one(m) -> str:
    g = m.group(1)
    ch = g[0]
    if ch in "xuU" and len(g) > 1:
        try:
            out = chr(int(g[1:], 16))
        except (ValueError, OverflowError):
            return ""
    elif ch in "01234567":
        out = chr(int(g, 8) & 255)
    elif ch == "c" and len(g) > 1:
        out = chr(ord(g[1]) & 31)
    else:
        return _ANSI_ONE.get(ch, "\\" + g)
    return "" if out in ("\x00", "\x01", "\x02") else out       # the three marker characters never come from input


def _ansi(raw: str) -> str:
    """The escapes of $'...' (and of printf, echo -e) decoded: \\n \\t \\xHH \\NNN \\uHHHH. Linear."""
    return _ANSI_ESC.sub(_ansi_one, raw) if "\\" in raw else raw


def _dq_close(s: str, start: int, ps: bool) -> int:
    """The index of the quote that closes a double-quoted string opened before start, or -1. Linear."""
    rx = _DQ_PS if ps else _DQ_SH
    k = start
    while True:
        m = rx.search(s, k)
        if m is None:
            return -1
        if m.group() == '"':
            return m.start()
        k = m.start() + 2


def _match(s: str, i: int, o: str, c: str, ps: bool) -> int:
    """The index of the bracket closing the one at s[i] (quote-aware); len(s) when it never closes."""
    depth, j, n = 0, i, len(s)
    while j < n:
        m = _SPECIAL.search(s, j)
        if m is None:
            return n
        ch, j = m.group(), m.start()
        if ch == "'":
            k = s.find("'", j + 1)
            j = j + 1 if k < 0 else k + 1
        elif ch == '"':
            k = _dq_close(s, j + 1, ps)
            j = j + 1 if k < 0 else k + 1
        elif ch == "\\":
            j += 1 if ps else 2
        elif ch == "`":
            if ps:
                j += 2
            else:
                k = s.find("`", j + 1)
                j = j + 1 if k < 0 else k + 1
        else:
            if ch == o:
                depth += 1
            elif ch == c:
                depth -= 1
                if depth == 0:
                    return j
            j += 1
    return n


# an unquoted here-document's escapes: the shell takes the backslash off before $, `, \ and a line end (E8)
_HEREDOC_ESC = re.compile(r"\\([$`\\\n])")


def _heredoc_unescape(m) -> str:
    return "" if m.group(1) == "\n" else m.group(1)


def _escaped(raw: str, at: int, esc: str) -> bool:
    """Whether the character at `at` is escaped: an odd run of `esc` (a backslash in sh, a backtick in PowerShell) stands
    just before it. The run is walked back once per expansion it precedes, so the total is linear."""
    k = at
    while k > 0 and raw[k - 1] == esc:
        k -= 1
    return (at - k) % 2 == 1


def _dq_subs(raw: str, ps: bool) -> list:
    """The command texts a double-quoted string (or an unquoted here-document, or a PowerShell @" "@) runs: $(...) in both
    shells, `...` in sh. E8: an ESCAPED one (`\\$(git push)`, `` \\`x\\` ``, PowerShell `` `$(x) ``) is text the shell
    prints and does not run."""
    subs, k = [], 0
    rx = _SUB_PS if ps else _SUB_SH
    esc = "`" if ps else "\\"
    while True:
        m = rx.search(raw, k)
        if m is None:
            return subs
        if _escaped(raw, m.start(), esc):
            k = m.start() + 1
            continue
        if m.group() == "`":
            e = raw.find("`", m.end())
            e = len(raw) if e < 0 else e
            subs.append(raw[m.end():e])
            k = e + 1
        else:
            j = _match(raw, m.end() - 1, "(", ")", ps)
            subs.append(raw[m.end():j])
            k = j + 1


class _Lex:
    def __init__(self, src: str, ps: bool):
        self.s, self.ps, self.segs, self.seg = src, ps, [], Seg()
        self.buf, self.on, self.q, self.dyn, self.subs, self.proc = [], False, False, False, [], False
        self.redir, self.here = None, []
        self.cr = -1                  # the next CR at or after the scan point (found once, not once per comment)
        self.blen, self.commas = 0, []        # the length of the word so far, and where its unquoted commas fall

    def put(self, text, quoted=False, dyn=False):
        if self.ps and not quoted and not dyn and "," in text:
            k = text.find(",")
            while k >= 0:
                self.commas.append(self.blen + k)
                k = text.find(",", k + 1)
        self.buf.append(text)
        self.blen += len(text)
        self.on = True
        if quoted:
            self.q = True
        if dyn:
            self.dyn = True

    def word_end(self):
        if not self.on:
            return
        w = Word("".join(self.buf), self.q, self.dyn, self.subs, self.proc, self.commas or None)
        self.buf, self.on, self.q, self.dyn, self.subs, self.proc = [], False, False, False, [], False
        self.blen, self.commas = 0, []
        r, self.redir = self.redir, None
        if r is None:
            self.seg.words.append(w)
        elif r in ("<<", "<<-"):
            tag, quoted = w.t, w.q
            if tag.startswith("\\"):                 # <<\EOF is a quoted delimiter too: its body is data
                tag, quoted = tag[1:], True
            self.here.append((self.seg, tag, quoted))
        elif r == "<<<":
            self.seg.herestr.append(w)
        else:
            self.seg.redirs.append((r, w))

    def seg_end(self, op):
        self.word_end()
        self.redir = None
        sg = self.seg
        if sg.words or sg.redirs or sg.herestr:
            sg.op = op
            self.segs.append(sg)
        self.seg = Seg()

    def bodies(self, p: int) -> int:
        """Read the here-document bodies that start at p (just after a line end); the index after them."""
        s, n = self.s, len(self.s)
        for sg, tag, quoted in self.here:
            lines = []
            while p < n:
                e = s.find("\n", p)
                line = s[p:] if e < 0 else s[p:e]
                p = n if e < 0 else e + 1
                if line.strip() == tag:
                    break
                lines.append(line)
            body = "\n".join(lines)
            # A19: a here-document whose delimiter is NOT quoted expands $(...) and backticks, so a command in it runs
            # (`cat <<EOF` with `$(git push)` inside); a quoted one ('EOF', "EOF", \EOF) is data and runs nothing. E8: an
            # escaped one (`\$(git push)`) is not run by this shell; but the shell takes the backslash off, so the program
            # the document is handed reads `$(git push)`, and a shell or an os.system there runs it (`bash <<EOF` with
            # `` \`git push\` ``): the text kept for that program is the unescaped one.
            if not quoted and ("$(" in body or "`" in body):
                sg.hsubs.extend(_dq_subs(body, self.ps))
            if not quoted and not self.ps and "\\" in body:
                body = _HEREDOC_ESC.sub(_heredoc_unescape, body)
            sg.heredocs.append(body)
        self.here = []
        return p

    def run(self) -> list:
        s, ps, n = self.s, self.ps, len(self.s)
        ORD = _ORD_PS if ps else _ORD_SH
        i = 0
        while i < n:
            m = ORD.match(s, i)
            if m is not None:
                self.put(m.group())
                i = m.end()
                continue
            c = s[i]
            if c in " \t\f\v":
                self.word_end()
                i = _WS.match(s, i).end()
            elif c == "\n" or c == "\r":
                self.seg_end("\n")
                i += 2 if s.startswith("\r\n", i) else 1
                if self.here:
                    i = self.bodies(i)
            elif c == "#":
                if self.on:
                    self.put("#")
                    i += 1
                else:                                        # a comment runs to the next LF or CR (A2: the CR is
                    e = s.find("\n", i)                      # searched for once, else every '#' line rescans to the end)
                    e = n if e < 0 else e
                    if self.cr < i:
                        self.cr = s.find("\r", i)
                        self.cr = n + 1 if self.cr < 0 else self.cr
                    i = min(e, self.cr)
            elif c == ";":
                self.seg_end(";")
                i += 1
            elif c == "&":
                if s.startswith("&&", i):
                    self.seg_end("&&")
                    i += 2
                elif s.startswith("&>", i):
                    self.word_end()
                    self.redir = ">"
                    i += 3 if s.startswith("&>>", i) else 2
                elif not self.on and not self.seg.words and (s[i + 1:i + 2] in (" ", "\t") or ps and s[i + 1:i + 2]):
                    self.seg.call = True                    # PowerShell's call operator: & git push, &$cmd, &"C:\x.exe"
                    i += 1
                elif ps and not self.on and self.seg.words and not self.seg.words[-1].q and \
                        self.seg.words[-1].t in _PS_ASSIGN_OPS and s[i + 1:i + 2]:
                    # close1 F2: on the right of an assignment `&` is the call operator too (`$r = & $deploy` runs the
                    # block); it had ended the statement, leaving `$deploy`, a value, which names nothing
                    self.seg.call = True
                    i += 1
                else:
                    self.seg_end("&")
                    i += 1
            elif c == "|":
                if s.startswith("||", i):
                    self.seg_end("||")
                    i += 2
                else:
                    self.seg_end("|")
                    i += 2 if s.startswith("|&", i) else 1
            elif c == "(":
                j = _match(s, i, "(", ")", ps)
                self.subs.append(s[i + 1:j])
                self.put("\x00", dyn=True)
                i = j + 1
            elif c == ")":
                self.seg_end(")")
                i += 1
            elif c == "{":                                   # only PowerShell reaches here (sh braces are word text)
                j = _match(s, i, "{", "}", ps)
                self.subs.append(s[i + 1:j])
                self.put("\x01", dyn=True)                   # a script block: code written here, read where it stands
                i = j + 1
            elif c == "}":
                self.seg_end("}")
                i += 1
            elif c == "'":
                prev = self.on and self.buf[-1][-1:].isalnum()
                if prev and s[i + 1:i + 2].isalnum():       # an apostrophe in a word (it's) opens nothing
                    self.put("'")
                    i += 1
                else:
                    j = s.find("'", i + 1)
                    if j < 0:
                        self.put("'")
                        i += 1
                    else:
                        self.put(s[i + 1:j], quoted=True)
                        i = j + 1
            elif c == '"':
                prev = self.on and self.buf[-1][-1:].isalnum()
                j = -1 if (prev and s[i + 1:i + 2].isalnum()) else _dq_close(s, i + 1, ps)
                if j < 0:
                    self.put('"')
                    i += 1
                else:
                    raw = s[i + 1:j]
                    dyn = "$" in raw or (not ps and "`" in raw)
                    if dyn:
                        self.subs.extend(_dq_subs(raw, ps))
                    if ps:
                        raw = _DQ_ESC_PS.sub(r"\1", raw) if "`" in raw else raw
                    elif "\\" in raw:
                        raw = _DQ_ESC_SH.sub(lambda mm: "" if mm.group(1) == "\n" else mm.group(1), raw)
                    self.put(raw, quoted=True, dyn=dyn)
                    i = j + 1
            elif c == "\\" and not ps:
                nx = s[i + 1:i + 2]
                if nx == "\n":
                    i += 2
                elif nx == "\r":
                    i += 3 if s.startswith("\r\n", i + 1) else 2
                elif nx == "":
                    self.put("\\")
                    i += 1
                elif nx in " \t\"'$;&|<>()*?[]#~!`{}":
                    self.put(nx, quoted=True)
                    i += 2
                else:
                    self.put("\\" + nx)
                    i += 2
            elif c == "`":
                if ps:
                    nx = s[i + 1:i + 2]
                    if nx == "\n":
                        i += 2
                    elif nx == "\r":
                        i += 3 if s.startswith("\r\n", i + 1) else 2
                    elif nx:
                        self.put(nx, quoted=True)
                        i += 2
                    else:
                        i += 1
                else:
                    j = s.find("`", i + 1)
                    if j < 0:
                        self.put("`")
                        i += 1
                    else:
                        self.subs.append(s[i + 1:j])
                        self.put(s[i:j + 1], dyn=True)
                        i = j + 1
            elif c == "$":
                nx = s[i + 1:i + 2]
                if nx == "(":
                    if s[i + 2:i + 3] == "(":
                        j = s.find("))", i + 3)
                        j = n if j < 0 else j + 1
                        self.put(s[i:j + 1], dyn=True)
                    else:
                        j = _match(s, i + 1, "(", ")", ps)
                        self.subs.append(s[i + 2:j])
                        self.put(s[i:j + 1], dyn=True)
                    i = j + 1
                elif nx == "{":
                    j = s.find("}", i + 2)
                    j = n - 1 if j < 0 else j
                    self.put(s[i:j + 1], dyn=True)
                    i = j + 1
                elif nx == "'" and not ps:
                    k = i + 2
                    while k < n and s[k] != "'":
                        k += 2 if s[k] == "\\" else 1
                    self.put(_ansi(s[i + 2:k]), quoted=True)  # ANSI-C quoting: $'a\nb' holds a real line end
                    i = k + 1
                else:
                    self.put("$", dyn=True)
                    i += 1
            elif c == "<" or c == ">":
                i = self._redirect(i, c)
            elif c == "@":
                q = s[i + 1:i + 2]
                nl = s[i + 2:i + 3]
                if q in ("'", '"') and nl in ("\n", "\r"):    # a PowerShell here-string: its body is data
                    k = s.find("\n" + q + "@", i + 2)
                    body = s[i + 3:] if k < 0 else s[i + 3:k]
                    if q == '"' and "$(" in body:               # A19: @" "@ expands $(...); @' '@ does not
                        self.subs.extend(_dq_subs(body, True))
                    self.put(body, quoted=True)
                    self.proc = None                          # marks data: never a command line, never code
                    i = n if k < 0 else k + 3
                else:
                    self.put("@")
                    i += 1
            else:                                            # a character nothing above claimed
                self.put(c)
                i += 1
        self.seg_end("")
        return self.segs

    def _redirect(self, i: int, c: str) -> int:
        s = self.s
        if c == "<":
            if s.startswith("<(", i) or s.startswith(">(", i):
                pass
            if s.startswith("<<<", i):
                op, adv = "<<<", 3
            elif s.startswith("<<", i):
                op, adv = ("<<-", 3) if s[i + 2:i + 3] == "-" else ("<<", 2)
            elif s.startswith("<(", i):
                return self._procsub(i)
            elif self.ps and s.startswith("<#", i) and not self.on:
                k = s.find("#>", i + 2)
                return len(s) if k < 0 else k + 2
            else:
                op, adv = "<", 1
                if s.startswith("<&", i) or s.startswith("<>", i):
                    adv = 2
        else:
            if s.startswith(">(", i):
                return self._procsub(i)
            if s.startswith(">>", i):
                op, adv = ">>", 2
            elif s.startswith(">|", i):
                op, adv = ">", 2
            elif s.startswith(">&", i):
                op, adv = ">", 2
                nx = s[i + 2:i + 3]
                if nx.isdigit() or nx == "-":
                    self._fd()
                    return i + 3
            else:
                op, adv = ">", 1
        self._fd()
        self.redir = op
        return i + adv

    def _fd(self):
        if self.on and not self.q and "".join(self.buf).isdigit():      # 2> : the 2 is a descriptor, not a word
            self.buf, self.on, self.dyn, self.subs = [], False, False, []
            self.blen, self.commas = 0, []
        else:
            self.word_end()

    def _procsub(self, i: int) -> int:
        j = _match(self.s, i + 1, "(", ")", self.ps)
        self.subs.append(self.s[i + 2:j])
        self.put("\x02", dyn=True)
        self.proc = True
        return j + 1


# ---------------------------------------------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------------------------------------------

ENV_ASSIGN = re.compile(r"\A\$?[A-Za-z_][A-Za-z0-9_]*+=")
CONTROL = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "esac",
                     "coproc"})
SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "ash", "fish", "csh", "tcsh", "rbash"})
PS_SHELLS = frozenset({"pwsh", "powershell"})
INTERP_FLAGS = {"node": ("-e", "--eval", "-p", "--print"), "nodejs": ("-e", "--eval", "-p", "--print"),
                "ruby": ("-e",), "perl": ("-e", "-E"), "php": ("-r",), "bun": ("-e", "--eval", "-p"),
                "lua": ("-e",), "rscript": ("-e",), "osascript": ("-e",), "python": ("-c",),
                "julia": ("-e", "--eval", "-E", "--print")}
STDIN_INTERP = SHELLS | PS_SHELLS | {"python", "node", "nodejs", "ruby", "perl", "php", "iex", "invoke-expression",
                                     "cmd", "deno", "bun", "lua", "luajit", "julia", "rscript", "tclsh"}
SQL_CLIENTS = frozenset({"psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "duckdb", "clickhouse-client", "cqlsh",
                         "snowsql", "usql", "invoke-sqlcmd", "invoke-dbaquery", "bq", "pgcli", "mycli", "sqlplus",
                         "isql", "mongosh", "mongo", "redis-cli", "clickhouse-local"})
INERT = frozenset({
    "echo", "printf", "write-host", "write-output", "write-verbose", "write-warning", "write-error", "write-debug",
    "write-information", "out-host", "man", "help", "get-help", "rem", "::", "cat", "grep", "egrep", "fgrep", "rg",
    "ag", "sed", "ls", "dir", "type", "head", "tail", "less", "more", "diff", "wc", "sort", "uniq", "cut",
    "tr", "stat", "file", "md5sum", "sha256sum", "shasum", "tree", "du", "df", "locate", "which", "where",
    "whereis", "history", "alias", "set", "export", "cd", "pushd", "popd", "mkdir", "touch", "chmod", "chown", "ln",
    "test", "[", "true", "false", "sleep", "date", "ps", "kill", "tar", "zip", "unzip", "jq", "yq", "select-string",
    "get-content", "get-childitem", "gci", "get-item", "get-process", "get-service", "get-history", "test-path",
    "new-item", "rename-item", "compress-archive", "expand-archive", "get-filehash", "set-location", "ren", "fd",
    "vim", "nano", "notepad", "pytest", "eslint", "prettier", "black", "ruff", "mypy", "tsc",
    "ping", "nslookup", "openssl", "id", "whoami", "uname", "pwd", "ver", "ipconfig", "tasklist", "findstr",
    "stop-process", "get-command", "gcm", "get-alias", "get-random", "get-date", "read-host"})   # not measure-command (E3)
ECHOES = frozenset({"echo", "printf", "write-host", "write-output", "print"})
NET_FETCH = frozenset({"curl", "wget", "iwr", "irm", "invoke-webrequest", "invoke-restmethod", "aria2c", "http",
                       "https", "xh", "xhs"})
SAVING_SINKS = frozenset({"tar", "unzip", "gunzip", "gzip", "bunzip2", "xz", "unxz", "zstd", "7z", "7za", "unrar",
                          "cpio", "dd", "tee", "install", "sponge", "patch"})
SUBCLI = frozenset({"git", "gh", "glab", "hub", "aws", "az", "gcloud", "kubectl", "oc", "helm", "terraform", "tofu",
                    "pulumi", "docker", "podman", "npm", "pnpm", "yarn", "cargo", "dotnet", "firebase", "netlify",
                    "vercel", "wrangler", "fly", "flyctl", "heroku", "stripe", "nerdctl"})
DYN_START = ("$", "`", "\x02")
PS_KEYWORDS = frozenset({"if", "elseif", "else", "while", "do", "until", "foreach", "switch", "try", "catch",
                         "finally", "return", "throw", "exit", "break", "continue", "param", "function", "filter",
                         "begin", "process", "end", "data"})        # not `for`: cmd's `for ... do cmd` is h_for's
MAX_HOPS = 40                       # wrappers looked through in a row; past this the command is opaque


class _C:
    """The state of one reading: dialect, depth, the work spent, the segment being read, the pipe's next segment.
    ran: the words being read run a value the OUTER shell put there (a wrapper's argv, or a command text the outer shell
    expanded), so a word that is a variable is a program to run and not an expression (A13). argv: the words are an
    argument list a wrapper hands to run (Start-Process, sudo, docker exec ...), so a PowerShell `(expr)` program word is
    a program computed at run time (E3). alt: this is the second or third reading of a call under another view of its
    options (see _alt_words and _flag_words): "alt" or "flags"; it is not read a further time."""
    __slots__ = ("ps", "depth", "work", "seg", "nxt", "ran", "alt", "argv")

    def __init__(self, ps, depth, work, seg=None, nxt=None, ran=False, alt="", argv=False):   # seg and nxt move along it
        self.ps, self.depth, self.work, self.seg, self.nxt, self.ran, self.alt = ps, depth, work, seg, nxt, ran, alt
        self.argv = argv

    def read(self, text: str, ps=None, spliced: bool = False) -> set:
        """A command text a wrapper runs (`bash -c`, `cmd /c`, `ssh h '...'`). spliced: the outer shell expanded it (a
        word holding $x, "...$x...", $(...)), so EVERY command of it whose program is a variable runs that value (E3,
        A13 narrowed in round 4: only the first was); a text written literally holds the child's own variables, read by
        the child's rules (PowerShell: a `$x` or `$x.Prop` statement is a value, E8)."""
        return _read(text, self.ps if ps is None else ps, self.depth + 1, self.work, spliced, self.alt)

    def run(self, words: list) -> set:
        if self.depth + 1 > MAX_DEPTH:
            return set(ALL)
        return _exec(words, _C(self.ps, self.depth + 1, self.work, self.seg, self.nxt, True, self.alt, True))

    def code(self, text: str) -> set:
        return _code(text, self)

    def spend(self, n: int) -> bool:
        """Charge n units of work to the budget; True when the budget is gone (the caller then answers every act).
        R5 (A15b): EVERY text handed to a regex or a reader is charged here before it is read, so the total reading work
        is at most a fixed multiple of the command's length; a command over the budget is every act, never a part."""
        return _spend(self.work, n)


def _spend(work: list, n: int) -> bool:
    work[0] += n
    return work[0] > work[1]


def _read(src: str, ps: bool, depth: int, work: list, spliced: bool = False, alt: str = "",
          grp: bool = False) -> set:
    """The acts of a command text. Opaque (every act) past MAX_DEPTH or past the work budget. spliced: the outer shell
    expanded this text before a wrapper runs it, so a variable at the head of ANY of its commands is a program (E3, see
    _C.read). grp: the text is what a ( ) or { } group holds; a group that runs a script or a program by its own name
    and names nothing for it is opaque (A20). A bash `{ ...; }` group written inline is read the same way (E5)."""
    work[0] += len(src) + 1
    if depth > MAX_DEPTH or work[0] > work[1]:
        return set(ALL)
    if "\x00" in src or "\x01" in src or "\x02" in src:     # the lexer's own markers never come from the input
        src = src.replace("\x00", " ").replace("\x01", " ").replace("\x02", " ")
    segs = _Lex(src, ps).run()
    found: set = set()
    c = _C(ps, depth, work, alt=alt)
    last = len(segs) - 1
    brace = 0                                               # E5: how deep the segment stands in bash `{ ...; }` groups
    for k, sg in enumerate(segs):
        nxt = segs[k + 1] if sg.op == "|" and k < last else None
        c.seg, c.nxt, c.ran = sg, nxt, spliced
        if not ps and sg.words and sg.words[0].t == "{" and not sg.words[0].q:
            brace += 1
        here = _exec(sg.words, c)
        found |= here
        # G7: a runner's download says nothing of what the script it runs does (`(cd web && uv run deploy)` named only
        # download): a group whose only act is a download is still asked what it runs by name
        if (grp or brace) and (not here or here == {"download"}) and _by_name(sg, ps):
            found |= ALL                                    # A20: `(cd infra && ./deploy.sh prod)` is not read away
        if brace and not ps and sg.words and sg.words[-1].t == "}" and not sg.words[-1].q:
            brace -= 1
        if nxt is not None:
            found |= _pipe(sg, nxt, ps, depth, work)
        if sg.redirs:
            if any(op in (">", ">|") and t.t.lower() not in ("/dev/null", "nul", "$null", "/dev/stdout",
                                                             "/dev/stderr") for op, t in sg.redirs) and \
                    (not sg.words or sg.words[0].t in (":", "true") and len(sg.words) == 1):
                found.add("delete")                         # `> f` and `: > f` empty the file
            for _op, w in sg.redirs:
                for sub in w.subs:
                    found |= _read(sub, ps, depth + 1, work, alt=alt)
        for i, w in enumerate(sg.words):
            if w.subs:
                # the word IS a group (a $(...) inside a word is not one). E8: a PowerShell block that is the VALUE of an
                # assignment (`$deploy = { .\deploy.ps1 }`) is defined here, not run: what it names is still read, but
                # it is not a group that runs a script by name (running it later is `& $x`, `.Invoke()`... : opaque)
                # close1 F2: `$x = & { ... }` RUNS the block (the call operator after the assignment sets sg.call)
                g = w.t[:1] in ("\x00", "\x01") and not (ps and w.t[:1] == "\x01" and i and not sg.call and
                                                          sg.words[i - 1].t == "=" and not sg.words[i - 1].q)
                for sub in w.subs:
                    found |= _read(sub, ps, depth + 1, work, alt=alt, grp=g)
        # A19: a command in a here-string (`<<< "$(rm -rf build)"`) or in an unquoted here-document runs
        for w in sg.herestr:
            for sub in w.subs:
                found |= _read(sub, ps, depth + 1, work, alt=alt)
        for sub in sg.hsubs:
            found |= _read(sub, ps, depth + 1, work, alt=alt)
        if len(found) == 6:
            break
    return found


_PYTHON_NAME = re.compile(r"\Apython[\d.]*+w?+\Z")


def _canon(name: str) -> str:
    if name.startswith("python") and _PYTHON_NAME.match(name):
        return "python"
    if name.startswith("pypy"):
        return "python"
    return name


@lru_cache(maxsize=4096)
def _prog(t: str) -> str:
    """A program word as its bare name: /bin/rm, \\rm, r\\m, rm.exe, npm.cmd, 'C:\\Program Files\\Git\\git.exe'."""
    w = t.lower().strip()
    pick = []
    for cand in (w.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], w.replace("\\", "").rsplit("/", 1)[-1]):
        for ext in (".exe", ".cmd", ".bat", ".ps1"):
            if cand.endswith(ext):
                cand = cand[: -len(ext)]
        pick.append(_canon(cand))
    if pick[0] in KNOWN or pick[1] not in KNOWN:
        return pick[0]
    return pick[1]


_VAR_NAME = re.compile(r"\$(?:(?:[A-Za-z_]\w*+:)?+[A-Za-z_]\w*+|[@*#?$!0-9-])")
_ENV_PROGRAMS = re.compile(r"\$\{?(?:EDITOR|VISUAL|PAGER|BROWSER|GIT_EDITOR|GIT_PAGER)\b")
# the same names anywhere in the call that are not read through `$` or `${`: an assignment (EDITOR='git push' $EDITOR)
_ENV_PROGRAM_SET = re.compile(r"(?<![$\{\w])(?:EDITOR|VISUAL|PAGER|BROWSER|GIT_EDITOR|GIT_PAGER)\b")


def _var_end(t: str) -> int:
    """The index just past the variable that t begins with (`$x`, `$env:Path`, `${x y}`, `$1`), or -1. R5: `${` is a
    find, not a pattern: `\\{[^}]*\\}` rescanned the rest of the word from every `${` that never closed."""
    if t[1:2] == "{":
        j = t.find("}", 2)
        return j + 1 if j >= 0 else -1
    m = _VAR_NAME.match(t)
    return m.end() if m else -1


def _opaque_program(t: str, assigned: bool = False) -> bool:
    """A program word that is an expansion whose value is the program: `$cmd`, `$(which rm)`, `` `which git` ``,
    `<(...)`. A path that BEGINS with an expansion is not: `$HOME/bin/tool`, `$(git rev-parse --show-toplevel)/run.sh`
    name a file, and a script run by its own name is a stated limit. (A3: this used to exempt any word holding a
    slash, and every URL has one, so `sh -c "$(curl -fsSL https://.../install.sh)"` named nothing.)"""
    ch = t[:1]
    if ch not in DYN_START:
        return False
    if ch == "\x02":
        return True
    if ch == "`":
        j = t.find("`", 1)
        rest = t[j + 1:] if j >= 0 else ""
    elif t.startswith("$(("):
        j = t.find("))", 3)
        rest = t[j + 2:] if j >= 0 else ""
    elif t.startswith("$("):
        j = _match(t, 1, "(", ")", False)
        rest = t[j + 1:]
    else:
        e = _var_end(t)
        rest = t[e:] if e >= 0 else t[1:]
    if rest[:1] in ("/", "\\"):
        return False
    if _ENV_PROGRAMS.match(t) and not assigned:  # $EDITOR file: the person's editor, not a computed command
        return False
    return True


_METHOD_VERBS = ("delete", "deleteasync", "deletedirectory", "deletefile", "downloadfile", "downloadstring",
                 "downloaddata", "downloadfileasync", "uploadfile", "uploadstring", "uploaddata", "uploadvalues",
                 "uploadfileasync", "uploadstringasync", "send", "sendasync", "sendmail", "postasync", "putasync",
                 "patchasync")
# A12: the method's verb is the LAST `.verb` of a word that may go on as `.name.name`, and it was found by a search
# that tried every `.send` of `.send.send.send...` and ran to the end of the word from each (11.6 s at 64 KiB). The word is
# matched REVERSED and anchored: the chain `name.name.` first, then the lexer's markers, then the verb and its dot (or
# `::`). One start, one pass, and the longest chain wins, which is the leftmost verb the old search found.
_METHOD = re.compile(r"\A(?:\w++\.)*[\x00\x01]*+(" + "|".join(v[::-1] for v in _METHOD_VERBS) + r")(?:\.|::)")


def _method_verb(word: str) -> str | None:
    """The .NET method verb a program word ends in (`$wc.DownloadString(`, `[IO.File]::Delete`), or None."""
    m = _METHOD.match(word[::-1])
    return m.group(1)[::-1] if m else None


def _isopt(w) -> bool:
    """An option: a word that begins with - (a quoted one as `--name='a b'`, an option with its value, or as one word
    with no white space in it: the shell takes the quotes off, so `git "--no-pager" push` is git --no-pager push, and a
    quoted `"--dry-run"` before the subcommand must not be taken for it; a quoted text with a space is a value)."""
    t = w.t
    return t.startswith("-") and (not w.q or "=" in t or not (" " in t or "\t" in t or "\n" in t))


def _takes_value(t: str, vals) -> bool:
    """Whether the option word t is one whose value is the NEXT word: `-u` when -u takes a value, and a cluster whose
    last letter does (`-iu`, `-Eu`, `-euo`): getopt reads a valued letter's rest of the word as its value, so only a
    valued letter at the END leaves the value to the next word. (A7: `sudo -iu postgres psql ...` hid psql.)"""
    if t in vals:
        return True
    if len(t) > 2 and t[0] == "-" and t[1] != "-" and "=" not in t:
        for k in range(1, len(t)):
            if ("-" + t[k]) in vals:
                return k == len(t) - 1
    return False


def _first_cmd(a: list, vals, start: int = 0) -> int:
    """The index of the first word of a wrapped command: past the wrapper's options and their values. Counted from
    the start of a, not from start, so a chain of wrappers needs no slicing (A2)."""
    i, n = start, len(a)
    while i < n:
        w = a[i]
        if not _isopt(w):
            break
        if w.t == "--":
            return i + 1
        i += 2 if _takes_value(w.t, vals) else 1
    return i


def _exec(words: list, c: _C) -> set:
    """The acts of one simple command given as words. Prefix wrappers are looked through in a loop (a chain of
    them is bounded: MAX_HOPS hops, then the command is opaque), so no input makes the recursion deep. Each hop past
    the first is charged to the work budget by the words it walks (A1/A2)."""
    for hop in range(MAX_HOPS):
        if hop and c.spend(len(words)):
            return set(ALL)
        # a command a wrapper starts is RUN: a $variable there is a program, and so is a PowerShell (expr) (E3)
        r = _exec1(words, c, hop > 0 or c.ran, hop > 0 or c.argv)
        if not isinstance(r, list):
            return r
        words = r
    return set(ALL)


def _cmd_if(words: list, k: int) -> int:
    """The index past `if` and its cmd condition (`exist x`, `not exist x`, `defined X`, `errorlevel 1`, `a==b`,
    `a equ b`), so the command it guards is read; past `if` alone for PowerShell's `if (...) {...}` (A10)."""
    n, i = len(words), k + 1
    if i < n and words[i].t.lower() == "not":
        i += 1
    if i >= n:
        return k + 1
    tok = words[i].t.lower()
    if tok in ("exist", "defined", "errorlevel", "cmdextversion"):
        return min(n, i + 2)
    if "==" in tok:
        return i + 1
    if i + 2 < n and (words[i + 1].t == "==" or words[i + 1].t.lower() in ("equ", "neq", "lss", "leq", "gtr", "geq")):
        return i + 3
    return k + 1


_SCRIPT_EXT = (".sh", ".bash", ".zsh", ".ps1", ".bat", ".cmd", ".py", ".rb", ".pl", ".js", ".mjs", ".ts", ".php", ".psm1")
_SCRIPT_INTERPS = frozenset({"python", "node", "nodejs", "ruby", "perl", "php", "bun", "deno", "lua", "julia", "rscript"})
_TASK_RUNNERS = frozenset({"make", "gmake", "nmake", "just", "task", "rake", "ninja", "ansible-playbook", "mage", "tox",
                           "nox", "invoke", "fab", "gulp", "grunt", "jake"})      # gulp, grunt, jake: close1 F5
# the wrappers that run the next word as a program, passed over when a group is asked what it runs by name (close1 F5)
_GROUP_PREFIX_WRAPPERS = frozenset({"sudo", "doas", "nohup", "nice", "time", "exec", "env", "stdbuf", "ionice",
                                    "chrt", "taskset", "command", "builtin", "timeout"})
_GROUP_RUN_PAIRS = {"poetry": "run", "pipenv": "run", "uv": "run", "bundle": "exec", "pdm": "run", "hatch": "run"}


# The everyday words of a test, build or lint target: ONE list, the same in this code, the docstring, the test
# (test_e5_the_everyday_list_is_the_one_list) and the report. A20 had made every group that runs a script by name opaque,
# and measured on the everyday set that held 5 of 27 bash idioms (`(cd frontend && npm test)`, `(cd docs && make html)`,
# `time (npm run build)`) and 1 of 64 PowerShell ones. E5: round 4 exempted a target whose FIRST segment was one of 26
# names, so `npm run preview:deploy`, `pnpm storybook:deploy` and `make all-deploy` were released in a group. A target is
# everyday only when EVERY segment of its name (split on `: - . _ /`) is a word of this list and its first is one of those
# 26 (_EVERYDAY_HEADS); a segment naming a material act (_MATERIAL_WORDS) never is. Any other name, a script PATH, and an
# interpreter given a file are opaque in a group. A named limit: a project whose `build` target ships something is
# released in a group (at the top level every such script already is, as the stated limit).
_EVERYDAY_WORDS = frozenset({
    "test", "tests", "testing", "unit", "e2e", "integration", "int", "spec", "specs", "jest", "vitest", "mocha",
    "pytest", "build", "builds", "compile", "lint", "linting", "fix", "format", "fmt", "prettier", "eslint",
    "stylelint", "check", "checks", "verify", "validate", "typecheck", "types", "type", "tsc", "dev", "develop",
    "development", "start", "serve", "server", "watch", "preview", "storybook", "docs", "doc", "html", "coverage", "cov",
    "bench", "benchmark", "benchmarks", "all", "prod", "production", "local", "ci", "debug", "ssr", "client", "web", "ui",
    "css", "js", "ts", "styles", "assets", "analyze", "analyse", "report", "quick", "fast", "full"})
# the words of the list a target may BEGIN with: the 26 names r5 exempted. A target's first segment must be one (r5's own
# rule, kept as it was, so nothing it held is released: `make prod`, `npm run ci`, `type-check` stay opaque), and every
# segment after it must be on the list (E5: `preview:deploy`, `storybook:deploy`, `all-deploy` are opaque again)
_EVERYDAY_HEADS = frozenset({"test", "tests", "build", "lint", "format", "fmt", "check", "dev", "start", "serve", "docs",
                             "html", "typecheck", "types", "coverage", "bench", "watch", "compile", "all", "storybook",
                             "preview", "prettier", "eslint", "tsc", "pytest", "doc"})
# a segment naming a material act is never everyday (deploy:docs, compile-and-publish, all-deploy, test:upload...)
_MATERIAL_WORDS = frozenset({"deploy", "publish", "release", "upload", "push", "ship", "delete", "rm", "clean", "reset",
                             "drop", "destroy", "purge", "wipe", "prune", "send", "mail", "pay", "migrate", "seed"})
# `python -m X` in a group is opaque unless X is one of these everyday modules (E5: `(cd ops && python -m deploy)`)
_EVERYDAY_MODULES = frozenset({"pytest", "unittest", "doctest", "mypy", "ruff", "black", "isort", "flake8", "pylint",
                               "pyflakes", "pycodestyle", "pydocstyle", "bandit", "coverage", "build", "pip", "venv",
                               "virtualenv", "http.server", "json.tool", "timeit", "cprofile", "profile", "pdb", "pydoc",
                               "compileall", "py_compile", "pyright", "tabnanny"})
_TARGET_SPLIT = re.compile(r"[:\-_./]")
# a task runner's options that name another recipe file or give a recipe text (F6): make -f/--file/--makefile/--eval,
# just --justfile, task -t/--taskfile, rake -f
_RECIPE_OPTS = ("-f", "--file", "--makefile", "--eval", "--justfile", "--taskfile", "-t", "--rakefile")


def _everyday_target(t: str) -> bool:
    segs = [s for s in _TARGET_SPLIT.split(t.lower()) if s]
    return bool(segs) and segs[0] in _EVERYDAY_HEADS and \
        all(s in _EVERYDAY_WORDS and s not in _MATERIAL_WORDS for s in segs)


def _by_name(sg, ps: bool = False) -> bool:
    """Whether the simple command runs a script or a program BY ITS OWN NAME, whose acts are not in the command (the
    stated limit: `./deploy.sh`, `bash cleanup.sh`, `npm run release`, `make deploy`, `just`, `task`, `psql -f x.sql`,
    `. ./x`). A20: the reader looks inside a ( ) or { } group and finds nothing in `(cd infra && ./deploy.sh prod)`, so
    the group was released that the parent held as every act. A group that does this and names nothing for it is
    opaque, except a target every segment of which is an everyday word, and `python -m` of an everyday module (E5, see
    _EVERYDAY_WORDS and _EVERYDAY_MODULES)."""
    words, k, n = sg.words, 0, len(sg.words)
    while k < n and (not words[k].q and (words[k].t.lower() in CONTROL or words[k].t.lower() in PS_KEYWORDS)
                     or ENV_ASSIGN.match(words[k].t)):
        k += 1
    # close1 F5: a prefix wrapper runs the next word as the program (`(cd infra && sudo ./deploy.sh prod)`); its options
    # are passed over. A stated limit: an option that takes a value as its own word (`sudo -u ops ./x`) leaves the value
    # as the program, which is then no script by name (a miss, as before), and a script named inside a -c text
    # (`(cd infra && bash -c './deploy.sh prod')`) is not looked for
    paired = False
    while k < n and not words[k].q:
        pw = _prog(words[k].t)
        if pw in _GROUP_RUN_PAIRS:
            # `poetry run X`, `bundle exec X`: X is the program; G7: past the runner's own options first (`poetry -C web
            # run deploy`, `hatch -e prod run deploy`), by the runner's table of valued options
            j = _first_cmd(words, RUNNERS.get(pw, (None, frozenset()))[1], k + 1)
            if j < n and not words[j].q and words[j].t == _GROUP_RUN_PAIRS[pw]:
                k = j + 1
                paired = True
                continue
        if pw in ("npm", "pnpm", "yarn") and k + 1 < n and not words[k + 1].q and \
                words[k + 1].t in ("exec", "x", "dlx"):
            # G7: `npm exec turbo run deploy`, `pnpm dlx X`: the program is the package word
            k = _first_cmd(words, {"-p", "--package", "-c", "--call"}, k + 2)
            paired = True
            continue
        if pw in ("npx", "pnpx", "bunx", "xargs"):
            # F3/F6: `npx turbo run deploy`, `xargs make deploy`: the program is the word after their options
            k = _first_cmd(words, XARGS_VAL if pw == "xargs" else {"-p", "--package"}, k + 1)
            paired = pw != "xargs"
            continue
        if pw not in _GROUP_PREFIX_WRAPPERS:
            break
        k += 1
        while k < n and not words[k].q and (words[k].t.startswith("-") or ENV_ASSIGN.match(words[k].t)):
            k += 1
        if pw == "timeout" and k < n:
            k += 1                                           # `timeout 900 make deploy`: the duration
            while k < n and not words[k].q and words[k].t.startswith("-"):
                k += 1
    if k >= n:
        return False
    w0 = words[k]
    t0 = w0.t
    p = _prog(t0)
    if p == "py":
        p = "python"                                         # F6: the Windows launcher, `py -m deploy`
    a = words[k + 1:]
    if p in ("turbo", "nx"):
        # F3: `turbo run deploy`, `nx run web:deploy`, `nx deploy web`: the task is named by the word after `run`
        pl = _pos(a)
        if pl and pl[0] in ("run", "run-many", "affected"):
            pl = pl[1:]
        return not all(_everyday_target(x) for x in pl)
    if p not in KNOWN and p not in _TASK_RUNNERS:
        if w0.q and ps and not sg.call:
            return False                                     # a string at the start of a PowerShell statement is a value
        if paired and not w0.q:
            # F6: `poetry run deploy`, `pipenv run deploy`: the project's own entry point, run by its name
            return not (_everyday_target(t0) or t0.lower() in _EVERYDAY_MODULES)
        return "/" in t0 or "\\" in t0 or t0.lower().endswith(_SCRIPT_EXT)
    if p in SHELLS or p in PS_SHELLS or p in _SCRIPT_INTERPS:
        for i, x in enumerate(a):
            if p == "python" and not x.q and (x.t == "-m" or x.t.startswith("-m") and x.t[2:].isidentifier()):
                mod = x.t[2:] if x.t != "-m" else (a[i + 1].t if i + 1 < len(a) else "")
                return mod.lower() not in _EVERYDAY_MODULES  # E5: `python -m deploy` runs a module by its name
        if any(not x.q and (x.t in ("-c", "-e", "-m", "-r", "-p", "-E") or x.t.lower() in ("-command", "-encodedcommand",
                                                                                          "-ec", "-ep", "--eval"))
               for x in a):
            return False
        if p in PS_SHELLS and any(not x.q and x.t.lower() in ("-file", "-f") for x in a):
            return True
        return any(not _isopt(x) for x in a)
    if p in ("npm", "pnpm", "yarn", "bun"):
        pl = _pos(a, NPM_VAL)
        s0 = pl[0] if pl else ""
        if s0 in ("run", "run-script"):
            return not (len(pl) > 1 and _everyday_target(pl[1]))
        if s0 in ("start", "test", "t", "restart", "stop"):
            return not _everyday_target("test" if s0 == "t" else s0)
        return p in ("yarn", "pnpm") and bool(s0) and s0 not in PM_OWN and not _everyday_target(s0)
    if p in _TASK_RUNNERS:
        # F6: a runner given another recipe file or a recipe text (`--file=release.mk`, `-f`, `--eval=...`) runs what is
        # written there. A stated limit, kept as A20 measured it: a runner given no target (`make`, `just`, `task`) runs
        # its default one, which no word names, and is not counted (pinned as everyday in test_a20 and test_e5)
        if any(_isopt(x) and x.t.lower().startswith(_RECIPE_OPTS) for x in a):
            return True
        return not all(_everyday_target(x) for x in _pos(a))
    if p in ("go", "cargo", "dotnet"):
        return bool(a) and a[0].t == "run"
    if p in (".", "source"):
        return bool(a) and a[0].t.lower().endswith(_SCRIPT_EXT)       # `. .venv/bin/activate`, `source .env` load a file
    if p in SQL_CLIENTS:
        return any(not x.q and x.t in ("-f", "--file") for x in a) or any(op == "<" for op, _ in sg.redirs)
    return False


_PS_RUNS_TEXT = ("[scriptblock]::create", "[powershell]::create", "invokescript", "invokecommand", "[scriptblock]::",
                 "diagnostics.process]::start",
                 # E3: a script block (or a PowerShell, a delegate) held in a value and run by a method call: `$sb.Invoke()`
                 ".invoke\x00", ".invokeasync\x00", ".invokereturnasis\x00", ".invokewithcontext\x00",
                 ".begininvoke\x00")


def _exec1(words: list, c: _C, ran: bool = False, argv: bool = False):
    """_exec for one step: the acts, or the words of the command a prefix wrapper runs. ran: the words are what a
    wrapper (Start-Process, cmd /c, sudo, wsl, docker exec, -Command, & ...) RUNS, so a program held in a variable is
    opaque there, as it is after `&` (A13). argv: the words are an argument list a wrapper runs, so a PowerShell
    `(expr)` program word is computed at run time and opaque, as `& (expr)` is (E3: `Start-Process (Get-Command
    git).Source`, `Start-Process -FilePath (Resolve-Path .\\x.exe)`); a ( ) at the head of a statement in a text, and a
    bash ( ) after `time` or `!`, are groups read where they stand."""
    k, n = 0, len(words)
    while k < n:                                         # control words, assignments, PowerShell $x = cmd
        w = words[k]
        if c.ps and not w.q and w.t.lower() == "if":
            k = _cmd_if(words, k)                        # cmd: `if exist build rmdir /s /q build`
        elif not w.q and w.t.lower() in CONTROL:
            k += 1
        elif c.ps and not w.q and w.t.lower() in ("return", "throw", "exit", "break", "continue"):
            return set()                                 # they run nothing: `throw "git push failed"` is a message
        elif c.ps and not w.q and w.t.lower() in PS_KEYWORDS:
            k += 1                                       # if/foreach/try/function...: the blocks are read where they stand
        elif ENV_ASSIGN.match(w.t):
            k += 1
        elif k + 1 < n and w.t.startswith("$") and words[k + 1].t in ("=", "+=", "-=", "*=", "/="):
            k += 2
        elif not c.ps and not w.q and w.t == "function" and k + 1 < n:
            k += 2                                       # bash `function name { body; }`: the body is read in line
        elif not c.ps and w.t[-1:] == "\x00" and w.t[:-1].isidentifier() and not w.q:
            k += 1                                       # bash `name() { body; }`
        else:
            break
    if k >= n:
        return set()
    w0, a = words[k], words[k + 1:]
    t0 = w0.t
    found: set = set()
    verb = _method_verb(t0.lower()) if c.ps or "." in t0 else None
    if verb:
        found.add("delete" if verb.startswith("delete") else "download" if verb.startswith("download") else "send")
        return found
    if c.ps and any(x in t0.lower() for x in _PS_RUNS_TEXT):
        return set(ALL)                                  # A13: [scriptblock]::Create($code).Invoke(), InvokeScript($s)
    if t0[:1] in ("\x00", "\x01"):
        # A group: ( ... ) in bash, ( ... ) or { ... } in PowerShell. Its contents are read where they stand (in _read),
        # so the group is classified by what it holds (A8). `& (expr)`, and a PowerShell (expr) a wrapper is handed as
        # its program (E3), run a value computed at run time.
        return set(ALL) if t0[:1] == "\x00" and (c.seg is not None and c.seg.call or c.ps and argv and k == 0) \
            else set()
    if _opaque_program(t0, c.work[2].get("assigned", False)):
        # PowerShell: `$x.Length` as a statement is an expression and `$x` alone is a value; `& $x`, `. $x` and a value a
        # wrapper RUNS (`Start-Process $exe`, `cmd /c $cmd`, `sudo $cmd`, `wsl $cmd`, `docker exec c $cmd`) are programs
        # (A13: the exemption had been written for the statement and it was reaching every wrapper's command).
        if c.ps and t0[:1] == "$" and not ran and not (c.seg is not None and c.seg.call):
            return set()
        return set(ALL)
    if w0.q and w0.proc is not None and len(words) - k == 1 and (" " in t0 or "\t" in t0):
        return c.read(t0, None, w0.dyn)                  # a whole command line in one quoted word
    p = _prog(t0)
    if p in INERT or p in ECHOES:
        return found
    if c.ps and p not in _PS_ARRAY_PARAMS and any(x.t == "@\x00" and x.subs for x in a):
        a = _ps_arrays(a, c)                             # E6: `& git @('push','origin','main')` is git push origin main
        if a is None:
            return set(ALL)
    if len(a) == 1 and a[0].t == "--version" and not a[0].q:
        return found                                     # `git --version`: the whole command is a version page
    plain = {x.t.lower() for x in a if not x.q}
    f = H.get(p)
    if f is not None:
        # No dry-run, help or -WhatIf exemption (removed in 1.8.0). Such a word must not hide the act either: as an
        # option's value it can be taken for the subcommand (`gh -n release create`, `curl -X --dry-run POST u`,
        # `git help push`, `rsync -av a h:/b help`). So every reading below is made of the call as written AND of the
        # call without those words; all count. A reading added can only name more, never less (no word is removed from
        # the first). At most two variants, each read at most three times: linear
        variants = [a]
        if not c.alt:
            a4 = [x for x in a if not _dryhelp_word(x.t)]
            if len(a4) != len(a):
                if c.spend(len(a)):
                    return set(ALL)
                variants.append(a4)
        for av in variants:
            if av is not a:
                found |= f(p, _noplus(p, av), _C(c.ps, c.depth, c.work, c.seg, c.nxt, c.ran, "nodry"))
            else:
                found |= f(p, _noplus(p, av), c)
            if p in ALT_PROGS and not c.alt:
                # A16/A17: an option this table does not know can take a value, and that value is then taken for the
                # subcommand (`helm -n prod uninstall api`, `docker --log-level error rm -f web`, `kubectl --as admin
                # delete`). The call is read a second time as if EVERY option took the word after it; both count.
                a2 = _alt_words(av)
                if a2 is not None:
                    if c.spend(len(av)):
                        return set(ALL)
                    found |= f(p, _noplus(p, a2), _C(c.ps, c.depth, c.work, c.seg, c.nxt, c.ran, "alt"))
                # E2: and an option a table says takes a value may be given with none (an optional value, as `aws s3
                # cp --sse`; or one left out), so its value word is the subcommand (`helm -n uninstall api`, `docker
                # --log-level rm -f web`, `docker run --rm --link alpine rm -rf /d`, `aws --exclude s3 cp ./d s3://b`:
                # 99f9116, whose tables were smaller, named each). The call is read a third time with the table's
                # valued options that stand before the words naming the act taken as flags (_flag_words).
                table, depth = _VALUED.get(p, (None, 0))
                a3 = _flag_words(av, table, depth) if table is not None else None
                if a3 is not None:
                    if c.spend(len(av)):
                        return set(ALL)
                    found |= f(p, _noplus(p, a3), _C(c.ps, c.depth, c.work, c.seg, c.nxt, c.ran, "flags"))
    elif p in WRAP:
        return _unwrap(p, a, c)
    elif p.startswith("remove-") and p not in REMOVE_SAFE or p.startswith(("unregister-", "uninstall-", "delete-",
                                                                          "mkfs")):
        found.add("delete")
    elif p.startswith("publish-") or p.startswith(PS_PUBLISH):
        found.add("publish")
    elif p.startswith("send-"):
        found.add("send")
    elif p.startswith(("install-", "save-")) or p == "update-module" or p.startswith(PS_DOWNLOAD):
        found.add("download")
    if p in SQL_CLIENTS:
        for x in a:
            found |= _sql(x.t, p, c.work)
    if p in STDIN_INTERP or p in SQL_CLIENTS or p in ("ssh", "sftp"):
        found |= _stdin_text(p, c)
    if not found and p not in H and p not in WRAP:       # the old fallbacks, for a program this table does not know
        if "download" in plain:
            found.add("download")
        joined = " ".join(x.t.lower() for x in words[k:] if not x.q)
        if c.spend(len(joined)):
            return set(ALL)
        if _SQL_WORDS.search(joined):
            found.add("delete")
    return found


# The programs whose options this file's tables may not all know; read a second time by _alt_words (A16/A17). E6: the
# claim "an option no table lists does not hide the subcommand" is made for THESE programs only. Other handled CLIs read
# their options from their own tables (git, redis-cli, s3cmd and minikube gained the options the attacker named), and an
# option those tables lack can still hide their subcommand: a stated limit. redis-cli and minikube join this list: no
# short option of theirs is a flag a handler reads. git does not: the second reading drops an option and the word after
# it, and `git push -n origin main` is a dry run it would turn into a push. (rclone and gsutil, already here, have that
# noise: `rclone sync -n a r:b` gets a class. The cheap direction, a stated limit.)
ALT_PROGS = frozenset({"gh", "glab", "aws", "az", "gcloud", "gsutil", "kubectl", "oc", "k", "helm", "terraform", "tofu",
                       "pulumi", "docker", "podman", "nerdctl", "npm", "pnpm", "yarn", "cargo", "dotnet", "firebase",
                       "netlify", "vercel", "wrangler", "fly", "flyctl", "heroku", "pip", "pip3", "pipx", "uv", "poetry",
                       "gem", "composer", "mvn", "gradle", "brew", "doctl", "supabase", "prisma", "serverless", "sls",
                       "docker-compose", "bun", "rclone", "stripe", "redis-cli", "minikube"})
_SQL_WORDS = re.compile(r"\b(?:drop\s++(?:table|database|schema)|truncate\s++table|delete\s++from)\b")


def _noplus(p: str, a: list) -> list:
    """`cargo +nightly publish`, `rustup +stable run ...`: a leading +toolchain is not the subcommand (A17)."""
    return a[1:] if p in ("cargo", "rustup", "rustc") and a and a[0].t.startswith("+") and not a[0].q else a


def _alt_words(a: list):
    """The words of a call read the other way: every unquoted option without an `=` takes the word after it (when that
    word is not itself an option), and both are dropped. None when that changes nothing. A table of valued options is
    never complete (`helm -n`, `docker --log-level`, `aws s3 sync --exclude`, `kubectl --as`), and a value that is
    taken for the subcommand hides the real one; the call is then read both ways and every act of either counts (the
    costly direction). Words after `--` are kept as they are. A stated limit, the cheap direction: a flag before an
    operand gives up that operand here (`aws s3 cp --recursive ./d s3://b` reads a download too, as 3e5e2ac did); the
    reading is kept whole because a malformed call (`aws --sse v1 s3 cp ...`) is named only by it."""
    out, i, n, changed = [], 0, len(a), False
    while i < n:
        w = a[i]
        if not w.q and w.t == "--":
            out.extend(a[i:])
            break
        if not w.q and w.t.startswith("-") and len(w.t) > 1 and "=" not in w.t and i + 1 < n and not _isopt(a[i + 1]) \
                and not (a[i + 1].t == "--" and not a[i + 1].q):
            i += 2
            changed = True
            continue
        out.append(w)
        i += 1
    return out if changed else None


def _flag_words(a: list, table, depth: int):
    """The words of a call read the third way (E2): an unquoted option that `table` says takes a value is taken to have
    none and is dropped, so the word after it stays an operand, while it stands before the `depth`-th operand (the words
    that name the act: aws's service and command, docker's command and image, kubectl's and helm's subcommand). Only
    the table's own options go, so every flag a handler reads (--delete, a dry run) is kept; and only before those
    operands, so an option's value later in the call is not read as an operand (`kubectl cp -c sidecar pod:/x ./x`,
    `aws s3 sync --exclude x s3://b ./d`). None when nothing is dropped."""
    out, changed, seen = [], False, 0
    for k, w in enumerate(a):
        if not w.q and w.t == "--":
            out.extend(a[k:])
            break
        if seen < depth and not w.q and "=" not in w.t and (w.t in table or w.t.lower() in table):
            changed = True
            continue
        if not _isopt(w) or len(w.t) < 2:
            seen += 1
        out.append(w)
    return out if changed else None


# the cmdlets whose parameters take a PowerShell array whole (an -ArgumentList, a -ComputerName list): read as written
_PS_ARRAY_PARAMS = frozenset({"start-process", "saps", "invoke-command", "icm", "start-job", "start-threadjob",
                              "foreach-object", "%", "where-object", "?", "measure-command"})


def _ps_arrays(a: list, c: _C):
    """E6: the words with each PowerShell array `@('a','b c')` handed to a program spread into its items, as PowerShell
    passes them (`& git @('push','origin','main')` runs git push origin main): an item holding white space is one quoted
    argument, any other item a bare word (so '--force' stays an option). None when the budget cannot pay for lexing the
    arrays again (A15b)."""
    out = []
    for w in a:
        if w.t != "@\x00" or not w.subs:
            out.append(w)
            continue
        if c.spend(len(w.subs[0]) + 1):
            return None
        for sg in _Lex(w.subs[0], True).run():
            for x in sg.words:
                for piece in _ps_pieces(x)[0]:
                    out.append(Word(piece, x.q and (" " in piece or "\t" in piece), x.dyn, [], False))
    return out


_DRYHELP_WORDS = frozenset({"--dry-run", "--dryrun", "-dry-run", "-dryrun", "--help", "-help", "/?", "/h", "/help",
                            "help", "-whatif", "-wi", "--whatif", "--what-if", "--simulate", "--noop", "/l",
                            "--just-print", "--recon", "--list-only", "--no-dry-run", "--no-dryrun"})


def _dryhelp_word(t: str) -> bool:
    """A dry-run, help or -WhatIf word in one of its spellings (for the second reading in _exec1 only: never an
    exemption). The one-letter ones (-n, -h) as written, since -N, -H mean other things. A set lookup and prefix tests."""
    if t in ("-n", "-h"):
        return True
    tl = t.lower()
    return tl in _DRYHELP_WORDS or tl.startswith(("--dry-run=", "--dryrun=", "-whatif:", "-wi:"))


# 1.8.0 had an exemption that read a dry run (--dry-run, -n, --dryrun), a help page (--help, -h) or PowerShell's
# -WhatIf as no act. Four attacks in a row found a spelling it let through (an option's value, a cluster, a switch-off,
# a quoted option, an alias); it was new in 1.8.0, and 1.7.0 named every one of those calls. It is REMOVED: such a word
# never makes a call no act, in any spelling, position or program; the call is named as its act and asked about.


# Runners: a program whose subcommand starts another command. (subcommands, options that take a value, operands to
# skip before the command, whether `--` separates the command). A7: only npx, uvx and bunx were looked through, so
# `poetry run twine upload`, `doppler run -- git push` and `nix develop -c npm publish` named nothing.
_UV_VALS = frozenset({"--with", "--with-requirements", "--with-editable", "--python", "-p", "--directory", "--project",
                      "--env-file", "--group", "--extra", "--package", "--index", "--index-url", "-i", "--config-file"})
RUNNERS = {
    "poetry": ({"run"}, frozenset({"-C", "--directory", "-P", "--project"}), 0, False),
    "pipenv": ({"run"}, frozenset(), 0, False), "pdm": ({"run"}, frozenset({"-p", "--project"}), 0, False),
    "uv": ({"run"}, _UV_VALS, 0, False), "hatch": ({"run"}, frozenset({"-e", "--env"}), 0, False),
    "rye": ({"run"}, frozenset(), 0, False), "bundle": ({"exec"}, frozenset({"--gemfile"}), 0, False),
    "conda": ({"run"}, frozenset({"-n", "--name", "-p", "--prefix"}), 0, False),
    "mamba": ({"run"}, frozenset({"-n", "--name", "-p", "--prefix"}), 0, False),
    "micromamba": ({"run"}, frozenset({"-n", "--name", "-p", "--prefix"}), 0, False),
    "mise": ({"exec", "x"}, frozenset({"-C", "--cd", "-c", "--command"}), 0, True),
    "fnm": ({"exec"}, frozenset({"--using"}), 0, True), "volta": ({"run"}, frozenset({"--node", "--npm", "--yarn",
                                                                                    "--pnpm", "--bundled-npm"}), 0, False),
    "devbox": ({"run"}, frozenset({"-c", "--config"}), 0, False), "asdf": ({"exec"}, frozenset(), 0, False),
    "doppler": ({"run"}, frozenset({"-p", "--project", "-c", "--config", "--token", "--command", "-m", "--mount"}), 0,
                True),
    "op": ({"run"}, frozenset({"--env-file", "--account", "--vault", "--no-masking"}), 0, True),
    "aws-vault": ({"exec"}, frozenset({"-d", "--duration", "--region", "-t", "--mfa-token", "--prompt", "--backend"}),
                  1, True),
    "chamber": ({"exec"}, frozenset({"-b", "--backend"}), 0, True), "direnv": ({"exec"}, frozenset(), 1, False),
    "dotenv": (None, frozenset({"-e", "-f", "-v", "-c", "-p", "-o"}), 0, False),
    "envchain": (None, frozenset(), 1, False), "dotenvx": ({"run"}, frozenset({"-f", "--env-file"}), 0, True),
    "pipx": ({"run"}, frozenset({"--spec", "--python", "--pip-args", "--index-url"}), 0,
             False),                                            # A16: `pipx run twine upload dist/*` runs twine
}


def _runner(p: str, a: list, c) -> set | None:
    """The acts of the command a RUNNERS program starts; None when this call is not one of its run forms."""
    subs, vals, skip, dd = RUNNERS[p]
    i, n = 0, len(a)
    if subs is not None:
        while i < n and (_isopt(a[i]) or a[i].t.lower() not in subs):
            if not _isopt(a[i]):
                return None                                      # the first operand is not a run subcommand
            i += 2 if _takes_value(a[i].t, vals) else 1
        if i >= n:
            return None
        i += 1
    if dd:
        for k in range(i, n):
            if a[k].t == "--" and not a[k].q:
                return c.run(a[k + 1:])
        if p in ("doppler", "op", "chamber", "dotenvx", "mise", "fnm"):
            return None                                          # these need `--`; without it nothing is run
    j = _first_cmd(a, vals, i)
    for _ in range(skip):
        j += 1
    return c.run(a[j:]) if j < n else set()


REMOVE_SAFE = frozenset({"remove-variable", "remove-module", "remove-psdrive", "remove-job", "remove-pssession",
                         "remove-typedata", "remove-psbreakpoint", "remove-event", "remove-eventsubscription"})


# PowerShell cmdlets (AWS, Azure, SharePoint) that ship or fetch by their name; each was a corpus miss (A10)
PS_PUBLISH = ("new-azresourcegroupdeployment", "new-azdeployment", "new-azsubscriptiondeployment", "write-s3object",
              "add-pnpfile", "set-azstorageblobcontent", "set-azstoragefilecontent", "write-gcsobject",
              "start-azdeployment", "write-azstorageblob", "set-azwebapp")
PS_DOWNLOAD = ("read-s3object", "get-azstorageblobcontent", "get-azstoragefilecontent", "read-gcsobject")


def _stdin_text(p: str, c: _C) -> set:
    """Here-documents and here-strings handed to an interpreter, a shell or an SQL client are code."""
    if p in SHELLS or p == "ssh":
        kind = "sh"
    elif p in PS_SHELLS or p in ("iex", "invoke-expression", "cmd"):
        kind = "ps"
    elif p in SQL_CLIENTS:
        kind = "mongo" if p in ("mongosh", "mongo") else "sql"
    elif p in STDIN_INTERP:
        kind = "code"
    elif p in FTP_PROGS:
        kind = "ftp"
    else:
        return set()
    return _seg_stdin(kind, c)


FTP_PROGS = frozenset({"sftp", "ftp", "lftp", "smbclient", "tftp"})


def _seg_stdin(kind: str, c: _C) -> set:
    """The acts of ALL the here-documents and here-strings of the segment, read as `kind` (sh, ps, sql, mongo, code,
    ftp). A1/A14: a text is read ONCE per kind and the answer kept, AND the union over the segment is kept too, so the N
    siblings of `find -exec A \\; -exec B \\; ... <<<x <<<x ...` (N commands, M texts) ask once and not N times M (5 s at 64
    KiB; sftp 12 s). Each reading charges the text it reads to the budget; a text too big for it is every act."""
    sg = c.seg
    if sg is None or not (sg.heredocs or sg.herestr):
        return set()
    memo = c.work[2]
    hit = memo.get((sg, kind))
    if hit is not None:
        return set(hit)
    found: set = set()
    for tx in sg.heredocs + [w.t for w in sg.herestr]:
        key = (kind, tx)
        h = memo.get(key)
        if h is None:
            if kind == "sh":
                h = c.read(tx, False, True)
            elif kind == "ps":
                h = c.read(tx, True, True)                  # whether the shell expanded it is not kept: as if it did
            elif kind == "sql":
                h = _sql(tx, "psql", c.work)
            elif kind == "mongo":
                h = _sql(tx, "mongosh", c.work)
            elif kind == "code":
                h = c.code(tx)
            else:
                h = _ftp_text(tx, c)
            memo[key] = h
        found |= h
    memo[(sg, kind)] = found
    return set(found)


STDIN_PROGS = SHELLS | PS_SHELLS | frozenset({"iex", "invoke-expression", "python", "node", "nodejs", "ruby", "perl",
                                              "php", "deno", "lua", "luajit", "julia", "rscript", "tclsh"})
# E4: the options of an interpreter that take the next word as their value (`node -r dotenv/config` reads its program
# from standard input; the value was taken for a script file and the pipe named nothing)
_INTERP_VAL = {"python": frozenset({"-W", "-X", "--check-hash-based-pycs"}),
               "node": frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader", "-C",
                                  "--conditions", "--env-file", "--title", "--inspect-port", "--input-type",
                                  "--redirect-warnings", "--icu-data-dir", "--openssl-config", "--diagnostic-dir"}),
               "ruby": frozenset({"-r", "-I", "-C", "-E", "-F"}), "perl": frozenset({"-I", "-M", "-m"}),
               "php": frozenset({"-c", "-d", "-z"}), "lua": frozenset({"-l"}), "luajit": frozenset({"-l", "-j", "-O"}),
               "julia": frozenset({"-L", "--load", "-J", "--sysimage", "-p", "--procs", "-t", "--threads", "--project"})}
_INTERP_VAL["nodejs"] = _INTERP_VAL["node"]
_CODE_FLAG_LETTERS = "ceErp"        # -c -e -E -r -p: the program is the next word, not stdin


def _reads_stdin_program(p2: str, rest: list) -> bool:
    """Whether p2, given these arguments, takes its PROGRAM from standard input (what a pipe then supplies).
    A4: `curl u | sh -s -- -y` does (-s says so); `sh script.sh`, `bash -c 'x'` and `python3 file.py` do not.
    Before, any positional word after `sh -s` was taken as a script file, and every official installer line
    (rustup, rvm, golangci-lint, bun, poetry) named nothing."""
    if p2 in ("iex", "invoke-expression"):
        return True
    if p2 in PS_SHELLS:
        i, n = 0, len(rest)
        while i < n:
            w = rest[i]
            t = w.t.lower()
            if w.q or not t.startswith(("-", "/")):
                return False                                  # bare words are the command text
            name = t.lstrip("-/").split(":")[0]
            val = t.split(":", 1)[1] if ":" in t else None
            if name and "command".startswith(name) and name not in ("co", "con", "conf"):
                return (val == "-") if val is not None else (i + 1 >= n or rest[i + 1].t == "-")
            if name and "file".startswith(name):
                # A18: `-File -` reads the script from standard input (`iwr u | pwsh -File -`); any other -File is a file
                return (val == "-") if val is not None else (i + 1 < n and rest[i + 1].t == "-")
            if name and ("encodedcommand".startswith(name) or name in ("e", "ec")):
                return False
            i += 1 if val is not None or not (name and any(v.startswith(name) for v in _PS_VALUED)) else 2
        return True
    if p2 in SHELLS:
        has_c = has_s = False
        i, n = 0, len(rest)
        while i < n:
            w = rest[i]
            t = w.t
            if t in _STDIN_FILES and not w.q:
                return not has_c                              # A18: `bash /dev/stdin --yes` is the piped program
            if w.q or not t.startswith(("-", "+")):
                return has_s and not has_c                    # the first operand: a script file (or the -c text)
            if t == "--":
                return (has_s and not has_c) if i + 1 < n else not has_c
            if t.startswith("--"):
                i += 2 if t in ("--rcfile", "--init-file") else 1
                continue
            letters = t[1:]
            has_c = has_c or "c" in letters
            has_s = has_s or "s" in letters
            i += 2 if letters[-1:] in ("o", "O") else 1       # -o name / -O name take a value
        return not has_c
    if p2 == "deno":
        return any(w.t == "-" for w in rest)
    i, n = 0, len(rest)
    vals = _INTERP_VAL.get(p2, frozenset())
    while i < n:
        w = rest[i]
        t = w.t
        if t == "-" or t in _STDIN_FILES and not w.q:
            return True
        if w.q or not t.startswith("-"):
            return False                                      # a script file
        if t in vals:
            i += 1                                            # E4: its value is the next word, not a script file
        elif not t.startswith("--") and t[-1] in _CODE_LETTERS.get(p2, "ce") and t[1:].isalpha():
            # A18: `python3 -E -` and `-I -`: only the letters that carry the program are code flags (-E is not one)
            return False
        i += 1
    return True


_STDIN_FILES = frozenset({"/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"})
_CODE_LETTERS = {"python": "cm", "node": "ep", "nodejs": "ep", "ruby": "e", "perl": "eE", "php": "r", "bun": "ep",
                 "lua": "e", "luajit": "e", "julia": "eE", "rscript": "e", "tclsh": ""}
# words that, beside a read of standard input, mean the text read is run (a keyword list, nothing here runs anything)
_STDIN_EXEC = ("exec", "eval", "compile", "system", "popen", "spawn", "subprocess", "child_process", "execsync")


def _code_runs_stdin(p2: str, rest: list) -> bool:
    """`python3 -c "import sys; exec(sys.stdin.read())"` and `node -e "eval(require('fs').readFileSync(0,'utf8'))"`: the
    program is the -c text, which reads standard input and runs it, so a pipe into it is a pipe into a shell (A18)."""
    letters = _CODE_LETTERS.get(p2, "")
    for k, w in enumerate(rest[:-1]):
        t = w.t
        if w.q or not t.startswith("-") or t == "-":
            continue
        if not t.startswith("--") and t[1:].isalpha() and t[-1] in letters and t[-1] != "m" or \
                t in ("--eval", "--print"):
            low = rest[k + 1].t.lower()
            return ("stdin" in low or "readfilesync(0" in low or "/dev/stdin" in low) and \
                any(x in low for x in _STDIN_EXEC)
    return False


PRINTF_SPEC = re.compile(r"%([-+ #0]*+\d*+(?:\.\d++)?+[sbdiouxXeEfgGcq%])")     # A11: `[-+ #0]*\d*` split a run of zeros
                                                                                # every way before it failed (156 s)


def _echo_texts(p1: str, words: list, work: list):
    """The texts an echo or printf puts on its output, as a shell reading it will see them: as written, and with
    the escapes decoded (echo -e, dash's echo, printf's format and %s). A9: `printf 'git push\\n' | bash`.
    None when the work budget ran out while building them (the caller then answers every act)."""
    args = [w.t for w in words if w.q or not w.t.startswith("-")]
    if _spend(work, sum(len(x) for x in args) + 1):
        return None
    out = [" ".join(args)]
    if p1 == "printf" and args:
        fmt, vals = _ansi(args[0]), args[1:]
        per = sum(1 for m in PRINTF_SPEC.finditer(fmt) if m.group(1) != "%")
        text, k, size = [], 0, 0
        for _round in range(max(1, len(vals) if per else 1)):
            def one(m):
                nonlocal k
                if m.group(1) == "%":
                    return "%"
                v = vals[k] if k < len(vals) else ""
                k += 1
                return _ansi(v) if m.group(1).endswith("b") else v
            if _spend(work, len(fmt)):
                return None
            piece = PRINTF_SPEC.sub(one, fmt)
            text.append(piece)
            size += len(piece)
            if k >= len(vals) or size > MAX_COMMAND:         # bounded: one long format over many values is not repeated
                break
        out.append("".join(text))
    else:
        out.append(_ansi(out[0]))
    return out if out[1] != out[0] else out[:1]


def _walk_wrappers(ws: list):
    """(index of the program, its name) past a chain of prefix wrappers, walked by index; None past MAX_HOPS hops.
    A18: EVERY wrapper in WRAP is looked through, with its option forms and the operands it takes before the command
    (`timeout 300 bash`, `nice -n 10 sh`, `stdbuf -oL sh`, `flock /tmp/l bash`, `env -i A=1 sh`, `doas sh`, `setsid sh`);
    before, six of them were, and `curl u | timeout 300 bash` named nothing."""
    j = 0
    p2 = _prog(ws[0].t)
    for hop in range(MAX_HOPS + 1):
        if p2 in WRAP and j + 1 < len(ws):
            if hop == MAX_HOPS:
                return None
            vals, skip = WRAP[p2]
            i = _first_cmd(ws, vals, j + 1)
            if skip and i < len(ws):
                i += skip
            while i < len(ws) and not ws[i].q and ENV_ASSIGN.match(ws[i].t):
                i += 1                                       # `env A=1 sh`: the assignments are not the command
            if i >= len(ws):
                break
            j, p2 = i, _prog(ws[i].t)
        else:
            break
    return j, p2


# programs that start the command they are given and hand it their own standard input (a pipe into them is a pipe into
# that command): a shell or an interpreter named after one of these, or after a program this file does not know, is
# taken to read the pipe (A18: an unknown wrapper in front of a shell on a pipe is opaque).
_STARTS_COMMANDS = frozenset({"ssh", "mosh", "docker", "podman", "nerdctl", "kubectl", "oc", "k", "su", "runuser", "script",
                              "nsenter", "lxc", "incus", "wsl", "vagrant", "sshpass", "fly", "flyctl", "heroku", "gcloud",
                              "sg", "newgrp", "setpriv", "unshare", "cgexec", "firejail", "bwrap", "proot", "linux32",
                              "linux64"})                  # not xargs or parallel: they pass the pipe as ARGUMENTS


# PowerShell's filters: they take their words as data, so `| Where-Object Name -eq python` is no shell on a pipe
_PIPE_FILTERS = frozenset({"where-object", "foreach-object", "select-object", "sort-object", "group-object",
                           "measure-object", "format-table", "format-list", "format-wide", "out-string", "out-file",
                           "out-null", "out-default", "convertto-json", "convertfrom-json", "convertto-csv",
                           "convertfrom-csv", "tee-object", "compare-object", "get-unique", "export-csv", "import-csv",
                           "add-content", "clip", "set-clipboard", "where", "foreach", "select", "sort", "ft", "fl",
                           "%", "?", "convertto-html", "convertto-xml", "out-gridview", "write-host"})


def _runs_piped_shell(ws: list, j: int, p2: str) -> bool:
    """Whether the program the pipe ends in is an unknown program, or one that starts commands, and a shell or an
    interpreter stands among its words: `curl u | unknown-wrapper bash`, `curl u | ssh host sh` (A18)."""
    if (p2 in KNOWN or p2 in _PIPE_FILTERS) and p2 not in _STARTS_COMMANDS:
        return False
    return any(_prog(w.t) in STDIN_PROGS for w in ws[j + 1:] if not w.q and not w.t.startswith("-") and "://" not in w.t)


def _group_reads_stdin(text: str, ps: bool, depth: int, work: list) -> bool:
    """Whether a command inside a text that is handed a pipe (a group `( ... )`, the remote command of ssh, the -c text
    of a shell or su) takes its program from that pipe. Past MAX_DEPTH, or past the budget, it is taken to."""
    if depth > MAX_DEPTH or _spend(work, len(text) + 1):    # the text is lexed again here: charged (A15b)
        return True
    for sg in _Lex(text, ps).run():
        ws = [w for w in sg.words if not (w.t.lower() in CONTROL and not w.q) and not ENV_ASSIGN.match(w.t)]
        if not ws:
            continue
        target = _walk_wrappers(ws)
        if target is None:
            return True
        j, p = target
        if p in STDIN_PROGS and (_reads_stdin_program(p, ws[j + 1:]) or _code_runs_stdin(p, ws[j + 1:]) or
                                 _text_reads_stdin(p, ws[j + 1:], depth, work)):
            return True
        if _runs_what_it_reads(ws, j, p, depth, work) or _runs_piped_shell(ws, j, p):
            return True
        if ws[j].t[:1] in ("\x00", "\x01") and depth < MAX_DEPTH and \
                any(_group_reads_stdin(sub, ps, depth + 1, work) for sub in ws[j].subs):
            return True
    return False


_SSH_VAL = frozenset({"-p", "-i", "-l", "-o", "-F", "-J", "-L", "-R", "-D", "-b", "-c", "-e", "-E", "-I", "-m", "-O",
                      "-Q", "-S", "-W", "-w", "-B"})


def _ssh_rest(a: list) -> tuple:
    """(the host word or None, the words of the remote command) of an ssh call: options may stand before and after the
    host (`ssh web1 -t 'sudo rm ...'`, A7)."""
    j = _first_cmd(a, _SSH_VAL)
    if j >= len(a):
        return None, []
    return a[j], a[_first_cmd(a, _SSH_VAL, j + 1):]


def _text_reads_stdin(p: str, rest: list, depth: int, work: list) -> bool:
    """E4: a shell's -c text, or a PowerShell -Command (or bare) text, that holds a program reading standard input:
    `curl u | sh -c 'exec bash'`, `| pwsh -c '$input | iex'`. The text runs with the pipe as its standard input."""
    if p in SHELLS:
        i, n, code = 0, len(rest), False
        while i < n:
            t = rest[i].t
            if rest[i].q or not t.startswith(("-", "+")):
                break
            if t == "--":
                i += 1
                break
            if t.startswith("--"):
                i += 2 if t in ("--rcfile", "--init-file") else 1
                continue
            letters = t[1:]
            code = code or t[0] == "-" and "c" in letters and letters.isalpha()
            i += 2 if letters[-1:] in ("o", "O") else 1
        return code and i < n and _group_reads_stdin(rest[i].t, False, depth + 1, work)
    if p in PS_SHELLS:
        i, n = 0, len(rest)
        while i < n:
            w = rest[i]
            t = w.t.lower()
            if w.q or not t.startswith(("-", "/")):
                break                                         # bare words: the command text
            name = t.lstrip("-/").split(":")[0]
            if name and "command".startswith(name) and name not in ("co", "con", "conf"):
                i += 1
                break
            if name and ("file".startswith(name) or "encodedcommand".startswith(name) or name in ("e", "ec")):
                return False
            i += 1 if ":" in t or not (name and any(v.startswith(name) for v in _PS_VALUED)) else 2
        return i < n and _group_reads_stdin(" ".join(x.t for x in rest[i:]), True, depth + 1, work)
    return False


PARALLEL_VAL = frozenset({"-j", "-n", "-N", "-S", "--jobs", "-a", "--sshlogin", "-P", "-I", "-d", "--delimiter", "-E",
                          "--halt", "--delay", "--timeout", "--joblog", "--results", "--colsep", "-C", "--workdir", "--wd",
                          "--env", "--block", "--load", "--memfree", "--tmpdir", "--retries", "--sshloginfile", "--slf",
                          "--arg-sep", "--arg-file-sep", "-L", "--max-lines", "-s", "--max-chars", "--tag-string",
                          "--basefile", "--bf", "--return", "--transferfile", "--tf", "--arg-file"})
_PARALLEL_SEPS = frozenset({":::", "::::", ":::+", "::::+"})


def _runs_what_it_reads(ws: list, j: int, p: str, depth: int, work: list) -> bool:
    """E4 (A18's claim was wider than the code): whether the program at ws[j], past its wrappers, RUNS the text a pipe
    hands it, by the shapes beyond a shell or an interpreter reading standard input:
      - ssh (mosh) with no remote command, whose remote login shell reads the pipe (`| ssh root@server`), or whose remote
        command holds a program that reads its program from standard input, quoted or not (`| ssh h 'bash -s'`,
        `"sudo bash -s"`, `'sh -s -- --yes'`, `'cd /srv && bash'`); `-N` runs no remote command;
      - `source /dev/stdin` and `. /dev/stdin`;
      - parallel with no command: every line it reads is a command line;
      - `sudo --login` and `sudo --shell` (as -i and -s), su with no -c, and su or runuser whose -c text reads standard
        input (`su -c 'bash' deploy`)."""
    rest = ws[j + 1:]
    if p in ("ssh", "mosh"):
        host, cmd = _ssh_rest(rest)
        if host is None:
            return False
        if not cmd:
            return not _cluster(rest, "N")
        return _group_reads_stdin(cmd[0].t if len(cmd) == 1 else " ".join(x.t for x in cmd), False, depth + 1, work)
    if p in (".", "source"):
        return bool(rest) and not rest[0].q and rest[0].t in _STDIN_FILES
    if p == "parallel":
        k = _first_cmd(rest, PARALLEL_VAL)
        return k >= len(rest) or not rest[k].q and rest[k].t in _PARALLEL_SEPS
    if p in ("sudo", "doas"):
        return _cluster(rest, "s") or _cluster(rest, "i") or any(not x.q and x.t in ("--login", "--shell") for x in rest)
    if p in ("su", "runuser"):
        for k, x in enumerate(rest):
            if not x.q and x.t in ("-c", "--command") and k + 1 < len(rest):
                return _group_reads_stdin(rest[k + 1].t, False, depth + 1, work)
            if not x.q and x.t.startswith("--command="):
                return _group_reads_stdin(x.t[10:], False, depth + 1, work)
        return p == "su"                                      # `| su - deploy`: a login shell reads the pipe
    return False


def _pipe(sg: Seg, nxt, ps: bool, depth: int, work: list) -> set:
    """What a pipe adds: text piped into a shell or an SQL client IS the program; a download piped into an extractor
    or a shell is a download and a run. A chain of prefix wrappers before the program is walked by index (no slicing)
    and at most MAX_HOPS long, then it is opaque (A2: `echo hi | env env env ... sh` was quadratic)."""
    if nxt is None or not sg.words:
        return set()
    p1 = _prog(sg.words[0].t) if not sg.words[0].dyn else ""
    ws = [w for w in nxt.words if not (w.t.lower() in CONTROL and not w.q) and not ENV_ASSIGN.match(w.t)]
    if not ws:
        return set()
    target = _walk_wrappers(ws)
    if target is None:
        return set(ALL)
    j, p2 = target
    if ws[j].t[:1] in ("\x00", "\x01") and ws[j].subs and depth < MAX_DEPTH and \
            any(_group_reads_stdin(sub, ps, depth + 1, work) for sub in ws[j].subs):
        return set(ALL)                                        # `curl u | (bash)`: the group's first reader gets the pipe
    found: set = set()
    if p2 in STDIN_PROGS:
        if not _reads_stdin_program(p2, ws[j + 1:]):
            if _code_runs_stdin(p2, ws[j + 1:]) or _text_reads_stdin(p2, ws[j + 1:], depth, work):
                return set(ALL)                                # `| python3 -c "exec(sys.stdin.read())"` (A18), `| sh -c 'bash'`
            return set()                                       # the program comes from a file or an argument
        if p1 in ECHOES and all(not w.dyn for w in sg.words[1:]):
            out: set = set()
            texts = _echo_texts(p1, sg.words[1:], work)
            if texts is None:
                return set(ALL)
            for tx in texts:                                   # echoed text with no expansion in it: literal (E8)
                if p2 in SHELLS:
                    out |= _read(tx, False, depth + 1, work)
                elif p2 in PS_SHELLS or p2 in ("iex", "invoke-expression"):
                    out |= _read(tx, True, depth + 1, work)
                else:
                    out |= _code(tx, _C(ps, depth, work, nxt, None))
            return out
        return set(ALL)
    if _runs_what_it_reads(ws, j, p2, depth, work):
        return set(ALL)                                        # `| sudo -s`, `| su`, `| ssh h 'bash -s'`, `| parallel` (E4)
    if _runs_piped_shell(ws, j, p2):
        return set(ALL)                                        # an unknown wrapper, or ssh/docker exec, before a shell (A18)
    if p2 in SQL_CLIENTS and p1 in ECHOES:
        txt = " ".join(w.t for w in sg.words[1:])
        return _sql(txt, p2, work)
    if p1 in NET_FETCH and p2 in SAVING_SINKS:
        found.add("download")
    return found


# ---------------------------------------------------------------------------------------------------------------
# rules by program
# ---------------------------------------------------------------------------------------------------------------

H: dict = {}


def rule(*names):
    def deco(f):
        for nm in names:
            H[nm] = f
        return f
    return deco


def _low(a: list) -> list:
    return [x.t.lower() for x in a]


def _pos(a: list, vals=frozenset()) -> list:
    """The words that are not options (and not the values of the options named in vals), lower-cased."""
    out, skip = [], False
    for k, w in enumerate(a):
        t = w.t
        if skip:
            skip = False
            continue
        if _isopt(w) and len(t) > 1:
            if t == "--":
                out.extend(x.t.lower() for x in a[k + 1:])
                break
            if "=" not in t and (t in vals or t.lower() in vals):
                skip = True
            continue
        out.append(t.lower())
    return out


def _posw(a: list, vals=frozenset()) -> list:
    out, skip = [], False
    for w in a:
        t = w.t
        if skip:
            skip = False
            continue
        if _isopt(w) and len(t) > 1:
            if "=" not in t and (t in vals or t.lower() in vals):
                skip = True
            continue
        out.append(w)
    return out


def _flags(a: list) -> set:
    return {x.t.lower() for x in a if _isopt(x)}      # a quoted `"--delete"` is the flag the program sees


def _cluster(a: list, ch: str) -> bool:
    """A single-dash cluster such as -rf or -avn holds the letter ch."""
    return any(not x.q and x.t.startswith("-") and not x.t.startswith("--") and ch in x.t[1:] for x in a)


@rule("rm", "rmdir", "rd", "del", "erase", "ri", "remove-item", "unlink", "shred", "srm", "wipe", "rimraf", "trash",
      "trash-put", "del-cli", "clear-content", "clear-item", "clear-itemproperty", "clear-recyclebin", "clear-disk",
      "clear-eventlog", "truncate", "set-content", "dropdb", "dropuser", "userdel", "deluser", "groupdel", "delgroup",
      "wipefs", "lvremove", "vgremove", "pvremove", "format-volume", "remove-itemproperty", "unlink-item", "rm.exe")
def h_delete(p, a, c):
    return {"delete"}


_UNC_WEB = re.compile(r"[\\/](?:www|wwwroot|html|htdocs|public|public_html|static|web|site)\b", re.I)


@rule("mv", "move", "move-item", "cp", "copy", "copy-item", "xcopy", "robocopy")
def h_move(p, a, c):
    found = set()
    pl = [x.t for x in a if not (x.t.startswith("-") and not x.q) and not (x.t.startswith("/") and len(x.t) < 6
                                                                          and not x.q and p == "robocopy")]
    if pl and pl[-1].lower() in ("/dev/null", "nul", "$null"):
        found.add("delete")
    if p == "cp" and pl and pl[0] == "/dev/null":
        found.add("delete")
    if p == "robocopy":
        fl = {x.t.lower() for x in a if x.t.startswith("/")}
        if {"/mir", "/purge", "/move", "/mov"} & fl:
            found.add("delete")
    unc = [x.t for x in a if x.t.startswith("\\\\") and not x.t.startswith("\\\\?\\")]
    if unc:
        found.add("send")
        if any(_UNC_WEB.search(u) for u in unc):
            found.add("publish")
        if p == "robocopy":
            found.add("push")
    if {"-tosession"} & _flags(a):
        found.add("send")
    if {"-fromsession"} & _flags(a):
        found.add("download")
    return found


@rule("find")
def h_find(p, a, c):
    found = set()
    if "-delete" in {x.t.lower() for x in a if not x.q}:
        found.add("delete")
    i = 0
    while i < len(a):                      # each -exec runs to its ; or +, and the scan goes on after it (linear)
        w = a[i]
        i += 1
        if not w.q and w.t in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i
            while j < len(a) and a[j].t not in (";", "+"):
                j += 1
            found |= c.run(a[i:j])
            i = j + 1
            if len(found) == 6:                # every act is named: the rest of the siblings add nothing
                break
    return found


XARGS_VAL = frozenset({"-I", "-L", "-n", "-P", "-s", "-d", "-E", "-a", "-l", "--max-args", "--max-procs",
                       "--max-lines", "--delimiter", "--arg-file", "--eof", "--max-chars"})


@rule("xargs")
def h_xargs(p, a, c):
    inner = a[_first_cmd(a, XARGS_VAL):]
    target = _walk_wrappers(inner) if inner else None
    if target is not None:
        j, p2 = target
        # E4: xargs appends what it reads to the command, so a shell given -c and no script runs the first thing read as
        # its script (`curl -s u | xargs -0 bash -c`): what xargs reads runs. With a script (`sh -c 'wc -l "$0"'`) it
        # does not, and the script is read below.
        if p2 in SHELLS and _c_without_script(inner[j + 1:]):
            return set(ALL)
    return c.run(inner)


def _c_without_script(rest: list) -> bool:
    """A shell's arguments that hold -c (alone or in a cluster) and nothing after the options: the script is left out.
    The options are read as h_sh reads them (`-o pipefail` and `--rcfile f` take a value)."""
    code, i, n = False, 0, len(rest)
    while i < n:
        t = rest[i].t
        if rest[i].q or not t.startswith(("-", "+")):
            return False
        if t == "--":
            return code and i + 1 >= n
        if t.startswith("--"):
            i += 2 if t in ("--rcfile", "--init-file") else 1
            continue
        code = code or t[0] == "-" and "c" in t[1:] and t[1:].isalpha()
        i += 2 if t[-1:] in ("o", "O") else 1
    return code


@rule("parallel")
def h_parallel(p, a, c):
    """parallel CMD ::: ARGS runs CMD with each argument. E4: with no command, each input IS a command line: the
    arguments after ::: are read here (a pipe into it, in _pipe, is every act; `::::` files are scripts by name)."""
    j = _first_cmd(a, PARALLEL_VAL)
    inner = []
    for w in a[j:]:
        if w.t in _PARALLEL_SEPS and not w.q:
            break
        inner.append(w)
    if inner:
        return c.run(inner)
    found: set = set()
    sep = ""
    for w in a[j:]:
        if not w.q and w.t in _PARALLEL_SEPS:
            sep = w.t
        elif sep in (":::", ":::+"):
            found |= c.read(w.t, False, w.dyn)
            if len(found) == 6:
                break
    return found


# prefix wrappers: (options that take a value, positionals to skip)
WRAP = {
    "sudo": (frozenset("-u -g -h -p -C -D -R -T -U -r -t --user --group --host --prompt --chdir --role --type".split()), 0),
    "doas": (frozenset({"-u", "-C"}), 0), "nohup": (frozenset(), 0), "setsid": (frozenset(), 0),
    "unbuffer": (frozenset(), 0), "exec": (frozenset({"-a"}), 0), "builtin": (frozenset(), 0),
    "call": (frozenset(), 0), "start": (frozenset(), 0), "time": (frozenset({"-f", "-o", "--format", "--output"}), 0),
    "nice": (frozenset({"-n", "--adjustment"}), 0),
    "ionice": (frozenset({"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"}), 0),
    "stdbuf": (frozenset({"-i", "-o", "-e"}), 0), "timeout": (frozenset({"-s", "-k", "--signal", "--kill-after"}), 1),
    "taskset": (frozenset({"-c"}), 1), "flock": (frozenset({"-w", "-E", "--timeout"}), 1),
    "watch": (frozenset({"-n", "-d", "--interval"}), 0), "caffeinate": (frozenset({"-t", "-w"}), 0),
    "busybox": (frozenset(), 0), "toybox": (frozenset(), 0), "sshpass": (frozenset({"-p", "-f", "-d", "-P"}), 0),
    "chroot": (frozenset({"--userspec", "--groups"}), 1), "env": (frozenset({"-u", "-C", "-S"}), 0),
    "command": (frozenset(), 0), "chrt": (frozenset(), 1), "wsl": (frozenset({"-d", "-u", "--distribution", "--user",
                                                                           "--cd", "--shell-type"}), 0),
    "runas": (frozenset(), 0),
    # A7: more wrappers that start the command they are given (the corpus and the findings name each)
    "gtimeout": (frozenset({"-s", "-k", "--signal", "--kill-after"}), 1),
    "strace": (frozenset({"-o", "-e", "-p", "-s", "-u", "-E", "-a", "-b", "-I", "-O", "-P", "-S", "-X", "-U"}), 0),
    "ltrace": (frozenset({"-o", "-e", "-p", "-s", "-u", "-a", "-n", "-l"}), 0), "pkexec": (frozenset({"--user"}), 0),
    "xvfb-run": (frozenset({"-s", "-e", "-n", "-f", "--server-args", "--error-file", "--server-num"}), 0),
    "gosu": (frozenset(), 1), "su-exec": (frozenset(), 1), "proxychains": (frozenset({"-f"}), 0),
    "proxychains4": (frozenset({"-f"}), 0), "torify": (frozenset(), 0), "tsocks": (frozenset(), 0),
    "chronic": (frozenset(), 0), "faketime": (frozenset({"-f"}), 1), "dbus-run-session": (frozenset(), 0),
    "systemd-run": (frozenset({"-p", "--property", "-u", "--unit", "--slice", "-E", "--setenv", "--uid", "--gid",
                               "--working-directory", "-M", "--machine", "--description", "--on-active",
                               "--on-calendar"}), 0),
    "firejail": (frozenset(), 0), "ssh-agent": (frozenset({"-t", "-a", "-E", "-P"}), 0),
}


def _lex_words(text: str, ps: bool) -> list:
    """The words of the first simple command of text (an `env -S` string, a `flock -c` string)."""
    segs = _Lex(text, ps).run()
    return segs[0].words if segs else []


def _unwrap(p, a, c=None):
    """The words of the command a prefix wrapper runs (empty when it only reports, as `command -v git` does); for a
    wrapper that takes the command as one STRING (`env -S 'git push'`, `flock f -c 'git push'`) the acts of that string."""
    vals, skip = WRAP[p]
    if p == "command" and any(x.t in ("-v", "-V") for x in a if not x.q):
        return []
    if p in ("start", "call"):
        a = [x for x in a if x.q or not x.t.startswith("/")]
        if p == "start" and a and a[0].q:
            a = a[1:]                                   # cmd's `start "title" command`: the first quoted word is a title
    if p == "runas":
        # E3: runas takes cmd-style options (/user:X, /savecred, /netonly...) and then ONE program string, a command line
        # it hands to the system: `runas /user:Administrator "cmd /c rd /s /q C:\build"` runs cmd /c rd... (the options
        # were taken for the program, and nothing was named)
        rest = [x for x in a if x.q or not x.t.startswith("/")]
        if not rest:
            return []
        if c is not None and c.spend(len(rest[0].t) + 1):
            return set(ALL)
        return _win_argv([(rest[0].t, rest[0].dyn)]) or []
    if p == "env" and c is not None:
        for k, w in enumerate(a):
            if w.q:
                continue
            if w.t in ("-S", "--split-string") and k + 1 < len(a):
                text, rest = a[k + 1].t, a[k + 2:]
            elif w.t.startswith("--split-string="):
                text, rest = w.t.split("=", 1)[1], a[k + 1:]
            else:
                continue
            return c.read(text + " " + " ".join(x.t for x in rest), False)
    if p == "flock" and c is not None:
        for k, w in enumerate(a):
            if not w.q and w.t in ("-c", "--command") and k + 1 < len(a):
                return c.read(a[k + 1].t, False)
    if p == "wsl":                                      # wsl -e CMD / --exec CMD / -- CMD run CMD; the rest manage distros
        low = {x.t.lower() for x in a if not x.q}
        if c is not None:
            if "--install" in low:
                return {"download"}
            if "--unregister" in low:
                return {"delete"}
        for k, w in enumerate(a):
            if not w.q and w.t in ("-e", "--exec", "--"):
                return a[k + 1:]
    return a[_first_cmd(a, vals) + skip:]


def _opaque_if_dynamic(a):
    return set(ALL) if any(x.proc and not _is_setup_generator(x) for x in a) else set()


def _dot_source(p, a, c):
    """`. FILE` / `source FILE`. In PowerShell a variable there is a script run (`. $script`, A13: a wrapper that runs a
    value), and so is a computed one (`. (Get-Item function:x).ScriptBlock`, E3: as `& (expr)` is); in sh `.
    "$HOME/.profile"` names a file, so only a process substitution is opaque there."""
    if c.ps and a and (_opaque_program(a[0].t) or a[0].t[:1] == "\x00"):
        return set(ALL)
    return _opaque_if_dynamic(a)


H["."] = _dot_source
H["source"] = _dot_source


@rule("eval", "iex", "invoke-expression")
def h_eval(p, a, c):
    if p != "eval" and a and not a[0].q and a[0].t.lower().startswith("-c") and \
            "-command".startswith(a[0].t.lower()) and len(a[0].t) > 1:
        a = a[1:]                                       # A7: Invoke-Expression -Command "..." names its parameter
    if not a:
        return set()
    if any(x.dyn or x.proc for x in a):
        if len(a) == 1 and _is_setup_generator(a[0]):
            return set()                                # eval "$(ssh-agent -s)" and its kin: see _is_setup_generator
        return set(ALL)
    return c.read(" ".join(x.t for x in a))


# Programs whose output is shell code that only sets up the person's own environment (exports, aliases, completions).
# `eval "$(ssh-agent -s)"`, `eval "$(pyenv init -)"`, `source <(kubectl completion bash)` are in nearly every profile; to
# call them every act costs an ask a day and teaches the person to ignore the ask. The word must be exactly one
# simple command from this table with one of these subcommands. A limit, named: a program of this name that prints
# anything else is read as this.
SETUP_GENERATORS = {
    "ssh-agent": {"-s", "-c"}, "pyenv": {"init", "virtualenv-init"}, "rbenv": {"init"}, "nodenv": {"init"},
    "jenv": {"init"}, "goenv": {"init"}, "direnv": {"hook", "export"}, "starship": {"init"}, "zoxide": {"init"},
    "fnm": {"env"}, "mise": {"activate", "hook-env", "completion"}, "rtx": {"activate"}, "thefuck": {"--alias"},
    "brew": {"shellenv"}, "conda": {"shell.bash", "shell.zsh", "shell.posix", "shell.powershell"},
    "micromamba": {"shell"}, "mamba": {"shell"}, "volta": {"completions"}, "pip": {"completion"}, "pipx": {"completion"},
    "register-python-argcomplete": None, "opam": {"env"}, "luarocks": {"path"}, "fzf": {"--bash", "--zsh"},
    "atuin": {"init"}, "navi": {"widget"}, "keychain": {"--eval"}, "gpg-agent": {"--daemon"},
}
SETUP_COMPLETION = frozenset({"kubectl", "helm", "oc", "gh", "glab", "docker", "podman", "npm", "pnpm", "yarn",
                              "poetry", "rustup", "cargo", "terraform", "aws", "gcloud", "flux", "kind", "minikube",
                              "k3d", "argocd", "istioctl", "kustomize", "skaffold", "stern", "tilt", "just", "task",
                              "deno", "bun", "uv", "ruff", "hugo", "cobra", "pulumi", "doctl", "flyctl", "fly",
                              "heroku", "vercel", "netlify", "supabase", "stripe", "kubeadm", "crictl", "nerdctl"})


def _is_setup_generator(w) -> bool:
    """Whether the word is exactly `$(prog sub)` or `<(prog sub)` for one program in the tables above."""
    if len(w.subs) != 1:
        return False
    t = w.t.strip()
    if not (t.startswith("$(") and t.endswith(")") or t.startswith("`") and t.endswith("`") or t == "\x02"):
        return False
    segs = _Lex(w.subs[0], False).run()
    if len(segs) != 1 or segs[0].redirs or segs[0].heredocs or segs[0].herestr or \
            any(x.dyn or x.subs for x in segs[0].words):
        return False
    return _generator_words([x.t for x in segs[0].words])


def _generator_words(ws: list) -> bool:
    if not ws:
        return False
    prog = _prog(ws[0])
    rest = [x.lower() for x in ws[1:]]
    if prog in SETUP_GENERATORS:
        want = SETUP_GENERATORS[prog]
        if prog == "ssh-agent" and not rest:
            return True                                     # `eval $(ssh-agent)`: the agent prints its own exports
        return want is None or bool(want & set(rest)) and len(rest) <= 3
    return prog in SETUP_COMPLETION and rest[:1] in (["completion"], ["completions"], ["--completion"]) and \
        len(rest) <= 2 and not any(r in ("--help",) for r in rest)


@rule("su", "runuser")
def h_su(p, a, c):
    for i, w in enumerate(a):
        if not w.q and w.t in ("-c", "--command") and i + 1 < len(a):
            return c.read(a[i + 1].t, False)
        if not w.q and w.t.startswith("--command="):
            return c.read(w.t[10:], False)
    if p == "runuser":
        j = _first_cmd(a, {"-u", "-g", "-G", "-s", "-l"})
        return c.run(a[j:]) if "-u" in {x.t for x in a} else set()
    return set()


@rule("sh", "bash", "zsh", "dash", "ksh", "ash", "fish", "csh", "tcsh", "rbash")
def h_sh(p, a, c):
    """sh/bash/zsh... The text of `-c` is the first operand once the options are past. An option cluster ending in o
    or O takes the next word as its value (`-euo pipefail`), `--` ends the options (`-c -- 'git push'`) (A7)."""
    i, n = 0, len(a)
    code = False
    while i < n:
        t = a[i].t
        if a[i].q or not t.startswith(("-", "+")):
            break
        if t == "--":
            i += 1
            break
        if t.startswith("--"):
            i += 2 if t in ("--rcfile", "--init-file") else 1
            continue
        letters = t[1:]
        if t[0] == "-" and "c" in letters and letters.isalpha():
            code = True
        i += 2 if letters[-1:] in ("o", "O") else 1
    if code:
        if i >= n:
            return set()
        w = a[i]
        if w.dyn and _opaque_program(w.t):                  # the script text is an expansion: `-c "$(curl u)"`, `-c "$CMD"`
            return set(ALL)
        if w.t.strip() in ("{}", "{1}", "%", "$1", "@"):    # `xargs -I{} sh -c '{}'`: the script is the data fed in
            return set(ALL)
        return c.read(w.t, False)
    if i < n and a[i].proc:
        return set(ALL)
    return set()


def _run_text(ws: list, c: _C, ps: bool) -> set:
    """The acts of a command line a wrapper is handed as words (`cmd /c ...`, `pwsh -Command ...`), read as text in the
    child's dialect with the words joined by spaces, as the child joins them. E3 (A13, narrowed in round 4): a word the
    outer shell EXPANDED ($x, "...$x...", $(...)) splices its value into the code before the child reads it, so every
    command of the text whose program is a variable runs that value, not only the first (`cmd /c "cd /d C:\\app &&
    $cmd"`); a text written literally ('...') holds the child's own variables, read by the child's rules (E8: `pwsh
    -Command '$PSVersionTable.PSVersion'` reads a property). A first word that is a parenthesised PowerShell expression
    is a command computed at run time (`cmd /c (Get-Content .\\cleanup.cmd -Raw)`): opaque."""
    if not ws:
        return set()
    if c.ps and ws[0].t[:1] == "\x00":
        return set(ALL)
    return c.read(ws[0].t if len(ws) == 1 else " ".join(x.t for x in ws), ps, any(x.dyn for x in ws))


@rule("cmd")
def h_cmd(p, a, c):
    for i, w in enumerate(a):
        if not w.q and w.t.lower() in ("/c", "/k", "/r"):
            return _run_text(a[i + 1:], c, True)
    return set()


_PS_FLAGS = ("noprofile", "nologo", "noninteractive", "noexit", "sta", "mta", "nop")
_PS_VALUED = ("executionpolicy", "windowstyle", "workingdirectory", "inputformat", "outputformat", "version",
              "psconsolefile", "configurationname", "custompipename", "encodedarguments")
# powershell.exe's documented aliases that are not a prefix of the long name (A7: -ep bypass hid the -c after it)
_PS_ALIAS = {"ep": "executionpolicy", "ec": "encodedcommand", "e": "encodedcommand", "ea": "encodedarguments",
             "w": "windowstyle", "wd": "workingdirectory", "if": "inputformat", "of": "outputformat",
             "psc": "psconsolefile", "cfg": "configurationname"}


@rule("pwsh", "powershell")
def h_ps(p, a, c):
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t.lower()
        if w.q or not t.startswith(("-", "/")):
            break
        name = _PS_ALIAS.get(t.lstrip("-/").split(":")[0], t.lstrip("-/").split(":")[0])
        val = None
        if ":" in t:
            val = w.t.split(":", 1)[1]
        if name and "command".startswith(name) and name not in ("co", "con", "conf"):
            rest = ([Word(val, w.q, w.dyn, [], False)] if val else []) + a[i + 1:]
            return _run_text(rest, c, True)
        if name and "encodedcommand".startswith(name) and not name.startswith("ex"):
            raw = val if val is not None else (a[i + 1].t if i + 1 < n else "")
            try:
                txt = base64.b64decode(raw[:MAX_COMMAND], validate=False).decode("utf-16-le", "ignore")
            except Exception:
                return set(ALL)
            return c.read(txt, True)                         # decoded text: literal, nothing of the outer shell's in it
        if name and "file".startswith(name):
            return set()
        if len(name) >= 2 and any(f.startswith(name) for f in _PS_FLAGS):
            i += 1
        elif name and any(v.startswith(name) for v in _PS_VALUED):
            i += 1 if val is not None else 2
        else:
            i += 1
    if i < n:
        return _run_text(a[i:], c, True)
    return set()


def _code_arg(w, c) -> set:
    """The code of an interpreter's -c/-e: read at its call sites; but code that IS an expansion (`-c "$CODE"`,
    `-e "$(curl u)"`) is not known before it runs, so it is opaque like `bash -c "$CMD"` (A9)."""
    if w.dyn and _opaque_program(w.t.lstrip()):
        return set(ALL)
    return c.code(w.t)


@rule("python", "py")
def h_python(p, a, c):
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t
        if w.q or not t.startswith("-") or t == "-":
            break
        if t in ("-W", "-X", "--check-hash-based-pycs"):
            i += 2
        elif t == "-m":
            return c.run(a[i + 1:]) if i + 1 < n else set()
        elif t.startswith("-m") and len(t) > 2 and t[2:].isidentifier():
            return c.run([Word(t[2:], False, False, [], False)] + a[i + 1:])
        elif not t.startswith("--") and t[1:].isalpha() and t[-1] == "c":
            return _code_arg(a[i + 1], c) if i + 1 < n else set()
        else:
            i += 1
    if i < n:
        base = _prog(a[i].t)
        pl = _pos(a[i + 1:])
        if base == "manage.py" and {"flush", "reset_db", "sqlflush", "sqlclear"} & set(pl):
            return {"delete"}
        if base == "setup.py" and "upload" in {x.t.lower() for x in a[i + 1:]}:
            return {"publish"}
        if base == "-" or a[i].t == "-":
            return set()
    return set()


@rule("node", "nodejs", "ruby", "perl", "php", "bun", "lua", "rscript", "osascript", "deno", "julia")
def h_interp(p, a, c):
    flags = INTERP_FLAGS.get(p, ())
    if p == "php" and a and not a[0].t.startswith("-") and _prog(a[0].t) == "artisan":
        return h_infra("artisan", a[1:], c)
    if p == "deno":
        pl = [x for x in a if not x.t.startswith("-")]
        if pl and pl[0].t.lower() in ("install", "add", "cache"):
            return {"download"}                              # deno install -gA jsr:@deno/deployctl
        if pl and pl[0].t.lower() in ("publish", "deploy"):
            return {"publish"}
        if pl and pl[0].t.lower() == "eval" and len(pl) > 1:
            return c.code(pl[1].t)
        if pl and pl[0].t.lower() == "run" and len(pl) > 1:
            nm = pl[1].t
            if nm.lower().startswith(("npm:", "jsr:")):
                nm = nm.split(":", 1)[1]
            return c.run([Word(nm, False, False, [], False)] + pl[2:])
        return set()
    if p == "bun" and a and a[0].t.lower() in ("add", "install", "i", "x", "create", "publish"):
        return _pkg("bun", a, c)
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t
        if w.q or not t.startswith("-") or t == "-":
            break
        name, eq, val = t.partition("=")
        if name in flags:
            cw = Word(val, False, False, [], False) if eq else (a[i + 1] if i + 1 < n else Word("", False, False, [], False))
            return _osa(cw.t, c) if p == "osascript" else _code_arg(cw, c)
        if not t.startswith("--") and t[1:].isalpha() and t[-1] in "eEr" and (t[-1] + "") in {f[-1] for f in flags}:
            if any(f[1:] == t[-1] for f in flags):
                return _code_arg(a[i + 1], c) if i + 1 < n else set()
        i += 1
    return set()


_OSA_SEND = re.compile(r"\bsend\b")
_OSA_DELETE = re.compile(r"\bdelete\b")


def _osa(code: str, c: _C) -> set:
    if c.spend(len(code)):
        return set(ALL)
    sans = _blank(code).lower()
    found = set()
    if _OSA_SEND.search(sans):
        found.add("send")
    if _OSA_DELETE.search(sans):
        found.add("delete")
    return found


# ---- code read at its call sites ----------------------------------------------------------------------------

_EXEC_OPEN = re.compile(r"(?:\bos\.(?:system|popen)|\bsubprocess\.\w++|\bPopen|\bcheck_output|\bcheck_call|"
                        r"\bchild_process\.\w++|\b(?:execSync|execFileSync|spawnSync|spawn|exec|execFile)|\bsystem|"
                        r"\bshell_exec|\bpassthru|\bpopen|\bproc_open)\s*+\(")
_LIT = re.compile(r"""'([^'\n]*+)'|"([^"\n]*+)\"""")
_TEMPLATE = re.compile(r"\$`([^`]{0,400}+)`")
_CODE = (
    ("delete", re.compile(r"\bos\.(?:remove|unlink|rmdir|removedirs)\s*+\(|\bshutil\.rmtree\s*+\(|\.unlink\s*+\(|"
                          r"\bunlink(?:Sync)?\b|\bfs\w*+\.(?:promises\.)?(?:rm|rmdir|rmSync|rmdirSync)\s*+\(|"
                          r"\)\s*+\.(?:rm|rmdir)(?:Sync)?\s*+\(|\bDeno\.remove\s*+\(|\bFile\.(?:delete|unlink)\b|"
                          r"\bFileUtils\.(?:rm|rm_f|rm_r|rm_rf|remove\w*+)\b|\bremove_tree\b|\brmtree\b|"
                          r"\brequests\.delete\s*+\(|\bhttpx\.delete\s*+\(|\baxios\.delete\s*+\(|"
                          r"\.delete_\w++\s*+\(|\bfile\.remove\s*+\(|\bNet::HTTP::Delete\b|"
                          r"\brm\s*+\(\s*+,\s*+recursive")),          # boto3 delete_object, R file.remove, julia rm(.., recursive=)
    ("send", re.compile(r"\brequests\.(?:post|put|patch)\s*+\(|\bhttpx\.(?:post|put|patch)\s*+\(|\.sendmail\s*+\(|"
                        r"\.send_message\s*+\(|\bsendMail\s*+\(|\bmail\s*+\(|\baxios\.(?:post|put|patch)\s*+\(|"
                        r"\bgot\.(?:post|put|patch)\b|\bsocket\.send(?:all|to)?\s*+\(|"
                        r"\bNet::HTTP\.(?:post|post_form|put|patch)\b|\.publish_message\s*+\(|\.send_email\s*+\(")),
    ("publish", re.compile(r"\.upload_file(?:obj)?\s*+\(|\.put_object\s*+\(|\.upload_from_\w++\s*+\(")),
    ("download", re.compile(r"\burlretrieve\b|\bwget\.download\s*+\(|\bgetstore\s*+\(|\bcurl_exec\b|"
                            r"\binstall\.packages\s*+\(|\bPkg\.(?:add|update)\s*+\(|\.download_file\s*+\(")),
    ("pay", re.compile(r"\b(?:Charge|PaymentIntent|Payout|Transfer|Refund|charges|paymentIntents|payouts|transfers|"
                       r"refunds)\s*+\.\s*+(?:create|confirm|capture)\s*+\(")),
)
_FETCH = re.compile(r"\brequests\.get\b|\burlopen\b|\burllib\b|\bhttps?\.get\b|\bfetch\s*+\(|\bURI\.open\b|"
                    r"\bNet::HTTP\b|\bfile_get_contents\b|\baxios\.get\b")
_REQ_HTTP = re.compile(r"""require\(\s*+['"]https?['"]\s*+\)""")
_WRITE = re.compile(r"""open\s*+\([^)]{0,120}['"]w|\.write\s*+\(|createWriteStream|writeFile|File\.write|"""
                    r"file_put_contents")
_FETCH_METHOD = re.compile(r"\bfetch\s*+\([^;]{0,300}?method\s*+:\s*+['\"](post|put|patch|delete)", re.I)
_URLOPEN_DATA = re.compile(r"\burlopen\s*+\([^)]{0,200}\bdata\s*+=")

_QUOTE = re.compile(r"""['"]""")
_SQ_STOP = re.compile(r"""[\\'\n]""")
_DQ_STOP = re.compile(r'''[\\"\n]''')


def _blank(text: str) -> str:
    """text with every string literal blanked to spaces (same length), so a word in a string is not code.
    A21: this was one pattern, `'(?:[^'\\\\\\n]|\\\\.)*'|\"...\"`, and every `'` of an unterminated run of `\\'` started a
    match that scanned to the end (13.6 s at 64 KiB). A literal that does not close fails at one place (a line end, a
    backslash that ends the line or the text, or the end), and no later quote of that kind BEFORE that place can close
    either (every quote in between was escaped, and a later start has the same alignment), so it is skipped: each
    stretch is scanned at most once per kind of quote."""
    out, last, i = [], 0, 0
    dead = {"'": 0, '"': 0}                    # quotes of this kind before this index open nothing
    while True:
        m = _QUOTE.search(text, i)
        if m is None:
            break
        j, q = m.start(), m.group()
        if j < dead[q]:
            i = j + 1
            continue
        stop = _SQ_STOP if q == "'" else _DQ_STOP
        k, end, fail = j + 1, -1, len(text)
        while True:
            s = stop.search(text, k)
            if s is None:
                break
            ch, at = s.group(), s.start()
            if ch == q:
                end = at
                break
            if ch == "\n" or text[at + 1:at + 2] in ("", "\n"):      # a line end, or a backslash with nothing to escape
                fail = at
                break
            k = at + 2
        if end < 0:
            dead[q] = fail
            i = j + 1
            continue
        out.append(text[last:j])
        out.append(" " * (end + 1 - j))
        last = i = end + 1
    out.append(text[last:])
    return "".join(out)


def _code(text: str, c: _C) -> set:
    """The acts of a one-liner in an interpreter: calls only, never a word in a string, plus the commands handed
    to an exec call (os.system, subprocess.run, execSync, system, shell_exec). Its length is charged first (A15b)."""
    found: set = set()
    if len(text) > MAX_COMMAND or c.spend(len(text)):
        return set(ALL)
    sans = _blank(text)
    for act, rx in _CODE:
        if rx.search(sans):
            found.add(act)
    if (_FETCH.search(sans) or _REQ_HTTP.search(text)) and _WRITE.search(text):
        found.add("download")
    m = _FETCH_METHOD.search(text)
    if m:
        found.add("delete" if m.group(1).lower() == "delete" else "send")
    if _URLOPEN_DATA.search(text):
        found.add("send")
    for n, m in enumerate(_EXEC_OPEN.finditer(sans)):
        if n >= 400:
            return set(ALL)
        win = text[m.end():m.end() + 400]
        cut = sans.find(")", m.end(), m.end() + 400) - m.end()     # the call's own `)`, not one inside a string
        win = win if cut < 0 else win[:cut]
        lits = [x or y for x, y in _LIT.findall(win)]
        if lits:
            found |= c.read(" ".join(lits), False)
    for m in _TEMPLATE.finditer(text):
        found |= c.read(m.group(1), False)
    return found


# ---- SQL ----------------------------------------------------------------------------------------------------

_NOT_A_TABLE = r"(?!(?:cascade|restrict|set|no|action|on|rule|where|from|output|using)\b)"
_SQL_DEL = re.compile(r"\b(?:drop\s++(?:table|database|schema|index|view|user|role|keyspace|column|collection|"
                      r"materialized|trigger|function|procedure|sequence|type|extension|policy|publication|"
                      r"subscription|server|tablespace|domain|aggregate|constraint|owned|rule|operator|cast|"
                      r"language|event|group|login|synonym|statistics|foreign|temporary|temp|unlogged)|"
                      r"truncate|delete\s++from|"
                      # T-SQL `DELETE dbo.Logs WHERE ...`, MySQL `DELETE t FROM t JOIN u ...`: a name, then a clause
                      r"delete\s++(?:top\s*+\(\s*+\d++\s*+\)\s*+(?:percent\s*+)?)?" + _NOT_A_TABLE +
                      r"[\w\[\]\".@#`]++\s*+(?:where\b|from\b|output\b|using\b|join\b|$)|"
                      r"alter\s++table\s++(?:if\s++exists\s++)?(?:only\s++)?\S++\s++(?:[^;]{0,200}?,\s*+)?drop|"
                      r"flushall|flushdb)\b")
_SQL_DROP_START = re.compile(r"\Adrop\s++\S")
# `(?:\w+\s+)*analyze` retried every split of a long run of words; the star is possessive and stops at the first `analyze`
_SQL_EXPLAIN_RUNS = re.compile(r"\Aexplain\s*+(?:\([^)]*\banaly[sz]e\b|(?:(?!analy[sz]e\b)\w++\s++)*+analy[sz]e\b)")
_JS_DEL = re.compile(r"\.(?:drop\w*+|delete\w*+|remove\w*+|findOneAndDelete|findAndRemove)\s*+\(")
_DQ_LIT = re.compile(r'"[^"\n]*+"')
_REDIS_DEL = frozenset({"flushall", "flushdb", "del", "unlink"})


def _blank_sql(s: str) -> str:
    out, i = [], 0
    while True:
        j = s.find("'", i)
        if j < 0:
            out.append(s[i:])
            break
        out.append(s[i:j])
        k = s.find("'", j + 1)
        while k >= 0 and s[k + 1:k + 2] == "'":
            k = s.find("'", k + 2)
        out.append(" ")
        if k < 0:
            break
        i = k + 1
    return "".join(out)


def _sql(text: str, prog: str, work=None) -> set:
    """The acts of SQL (or mongo JS, or a redis command) text; a quoted literal is data, EXPLAIN runs nothing. The
    text's length is charged to the work budget (work) before it is read; over it, or over MAX_COMMAND, is every act."""
    if len(text) > MAX_COMMAND or work is not None and _spend(work, len(text)):
        return set(ALL)
    low = _blank_sql(text.lower())
    low = _DQ_LIT.sub(" ", low) if '"' in low else low
    if prog in ("mongosh", "mongo"):
        return {"delete"} if _JS_DEL.search(_blank(text)) else set()
    for stmt in low.split(";"):
        s = stmt.strip()
        if s.startswith("explain") and not _SQL_EXPLAIN_RUNS.match(s):
            continue                                    # EXPLAIN plans and runs nothing; EXPLAIN ANALYZE runs it
        if _SQL_DROP_START.match(s) or _SQL_DEL.search(s):
            return {"delete"}
    return set()


# redis-cli's options that take a value (its --help). E6: `--cacert ca.pem` took the cert for the command; -x is a flag
# (the last argument is read from standard input), not a valued option
REDIS_VAL = frozenset({"-h", "-p", "-s", "-a", "-u", "-n", "-r", "-i", "-d", "-D", "-X", "-t", "--user", "--pass",
                       "--pattern", "--quoted-pattern", "--count", "--sni", "--cacert", "--cacertdir", "--cert", "--key",
                       "--tls-ciphers", "--tls-ciphersuites", "--rdb", "--functions-rdb", "--pipe-timeout",
                       "--memkeys-samples", "--intrinsic-latency", "--eval", "--lru-test", "--show-pushes", "--cluster"})


@rule(*sorted(SQL_CLIENTS - {"bq", "mongosh", "mongo"}))
def h_sql(p, a, c):
    if p == "redis-cli":
        pl = _pos(a, REDIS_VAL)
        if pl and pl[0] in ("publish", "xadd", "spublish"):
            return {"send"}                                    # PUBLISH hands a message to every subscriber
        return {"delete"} if pl and pl[0] in _REDIS_DEL else set()
    return set()


@rule("mongosh", "mongo")
def h_mongo(p, a, c):
    found = set()
    for x in a:
        found |= _sql(x.t, p, c.work)
    return found


# ---- version control ----------------------------------------------------------------------------------------

GIT_VAL = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env",
                     "--exec-path", "--attr-source"})    # E6: `git --attr-source HEAD push` named nothing


@rule("git", "hub")
def h_git(p, a, c):
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        if _isopt(w):
            i += 2 if (w.t in GIT_VAL) else 1              # `--git-dir=x` is one word and takes no value after it
            continue
        break
    if i >= n:
        return set()
    if a[i].t.lower() == "help" and not a[i].q and i + 1 < n:
        i += 1                                              # `git -C x help push`: no help exemption; push is read
    sub, rest = a[i].t.lower().replace("\\", ""), a[i + 1:]       # git p\ush is git push (a shell drops the backslash)
    rl = [x.t.lower() for x in rest if not x.q]
    fl = {x for x in rl if x.startswith("-")}
    first = rl[0] if rl else ""
    # no dry run, help page or -n exempts anything here (removed in 1.8.0: four attacks found spellings it let through)
    found: set = set()
    if sub == "push":
        found.add("push")
        if {"--delete", "-d", "--mirror", "--prune"} & fl or any(x.startswith((":", "+:")) for x in rl):
            found.add("delete")
        if rl[:1] == ["heroku"] or any("heroku.com" in x for x in rl):
            found.add("publish")                            # pushing to a Heroku remote deploys
    elif sub == "p4" and first in ("submit", "commit"):
        found.add("push")                                   # git p4 submit writes to the Perforce server
    elif sub == "review":
        found |= {"push", "publish"}                        # git-review sends the change to Gerrit
    elif sub == "subtree":
        found.add("push" if first == "push" else "download") if first in ("push", "pull", "add") else None
    elif sub == "lfs":
        if first == "push":
            found.add("push")
        elif first in ("pull", "fetch", "clone"):
            found.add("download")
    elif sub == "svn":
        if first == "dcommit":
            found.add("push")
        elif first in ("fetch", "clone", "rebase"):
            found.add("download")
    elif sub in ("send-pack",):
        found.add("push")
    elif sub == "send-email":
        found.add("send")
    elif sub in ("clean", "rm"):
        found.add("delete")
    elif sub == "branch":
        if {"--delete", "-d", "-D".lower()} & fl or _cluster(rest, "d") or _cluster(rest, "D"):
            found.add("delete")
    elif sub == "tag":
        if {"-d", "--delete"} & fl or _cluster(rest, "d"):
            found.add("delete")
    elif sub == "reset":
        if "--hard" in fl:
            found.add("delete")
    elif sub == "stash":
        if first in ("drop", "clear"):
            found.add("delete")
    elif sub == "restore":                                  # -S --staged, -W --worktree, -s --source (case matters)
        rf = {x.t for x in rest if not x.q}
        staged = "--staged" in rf or any(t.startswith("-") and not t.startswith("--") and "S" in t[1:] for t in rf)
        worktree = "--worktree" in rf or any(t.startswith("-") and not t.startswith("--") and "W" in t[1:]
                                              for t in rf)
        if not staged or worktree:
            found.add("delete")
    elif sub == "checkout":
        if "--" in rl or rl == ["."] or "-f" in fl:
            found.add("delete")
    elif sub == "worktree":
        if first in ("remove", "prune"):
            found.add("delete")
    elif sub == "reflog":
        if first in ("expire", "delete"):
            found.add("delete")
    elif sub == "gc":
        if any(x.startswith("--prune") for x in fl):
            found.add("delete")
    elif sub in ("filter-branch", "filter-repo"):
        found.add("delete")
    elif sub == "update-ref":
        if "-d" in fl:
            found.add("delete")
    elif sub == "remote":
        if first in ("remove", "rm", "prune"):
            found.add("delete")
        elif first == "update":
            found.add("download")
    elif sub in ("clone", "fetch", "pull", "submodule"):
        found.add("download")
    elif p == "hub" and sub in ("pull-request", "release", "create", "fork"):
        found.add("publish")
    return found


@rule("hg", "svn", "fossil", "jj", "bzr")
def h_vcs(p, a, c):
    pl = _pos(a)
    found = set()
    if p == "jj":
        if pl[:2] == ["git", "push"]:
            found.add("push")
        elif pl[:2] == ["git", "fetch"] or pl[:2] == ["git", "clone"]:
            found.add("download")
        return found
    if not pl:
        return found
    s = pl[0]
    if s in ("push", "commit", "ci", "import", "sync") and not (p == "hg" and s in ("commit", "ci")):
        found.add("push")
    elif s in ("delete", "rm", "remove", "del"):
        found.add("delete")
    elif s in ("clone", "checkout", "co", "pull", "update", "up", "export"):
        found.add("download")
    return found


_GH_PUBLISH_PATH = re.compile(r"/(?:releases|deployments|pages|dispatches)\b|/git/refs")
GH_VAL = frozenset({"-R", "--repo", "-b", "--body", "-t", "--title", "-X", "--method", "-H", "--header", "-q", "--jq",
                    "-F", "-f", "--field", "--raw-field", "--input", "-p", "--pattern", "--ref", "-B", "--base",
                    "-l", "--label", "-a", "--assignee", "-m", "--milestone", "--notes", "-n", "-d", "-D", "--name"})


@rule("gh", "glab")
def h_gh(p, a, c):
    pl = _pos(a, GH_VAL)
    fl = _flags(a)
    s0 = pl[0] if pl else ""
    s1 = pl[1] if len(pl) > 1 else ""
    found = set()
    if s0 in ("release", "gist", "repo", "pr", "mr", "issue", "run", "workflow", "extension", "ext", "codespace",
              "secret", "variable", "label", "cache", "ruleset", "project", "api"):
        pass
    if s0 == "release":
        if s1 in ("create", "upload", "edit"):
            found.add("publish")
        elif s1 == "delete" or s1 == "delete-asset":
            found.add("delete")
        elif s1 == "download":
            found.add("download")
    elif s0 == "repo":
        if s1 in ("create", "edit", "fork", "rename", "archive"):
            found.add("publish")
            if "--push" in fl:
                found.add("push")
        elif s1 == "delete":
            found.add("delete")
        elif s1 == "clone":
            found.add("download")
        elif s1 == "sync":
            found.add("push")
    elif s0 in ("pr", "mr"):
        if s1 in ("create", "merge"):
            found.add("publish")
            if s1 == "merge":
                found.add("push")                           # a merge writes the base branch on the remote
            if s1 == "merge" and ({"--delete-branch", "-d"} & fl):
                found.add("delete")
        elif s1 in ("comment", "note", "review", "edit", "close", "reopen", "ready", "approve"):
            found.add("send")
            if s1 == "close" and "--delete-branch" in fl:
                found.add("delete")                         # A16: `gh pr close 12 --delete-branch` removes the branch
    elif s0 == "issue":
        if s1 == "delete":
            found.add("delete")
        elif s1 in ("create", "comment", "edit", "close", "reopen", "note", "transfer"):
            found.add("send")
    elif s0 == "gist":
        if s1 in ("create", "edit"):
            found.add("publish")
        elif s1 == "delete":
            found.add("delete")
    elif s0 == "workflow" and s1 == "run":
        found.add("publish")
    elif s0 == "run":
        if s1 == "download":
            found.add("download")
        elif s1 == "delete":
            found.add("delete")
    elif s0 in ("extension", "ext") and s1 == "install":
        found.add("download")
    elif s0 in ("codespace", "secret", "variable", "label", "cache", "ruleset", "project") and s1 == "delete":
        found.add("delete")
    elif s0 == "api":
        method = None
        for k, w in enumerate(a):
            if not w.q and w.t in ("-X", "--method") and k + 1 < len(a):
                method = a[k + 1].t.upper()
            elif not w.q and w.t.startswith("--method="):
                method = w.t[9:].upper()
            elif not w.q and w.t.startswith("-X") and len(w.t) > 2:
                method = w.t[2:].lstrip("=").upper()                  # -XDELETE (A9)
        data = bool({"-f", "-F", "--field", "--raw-field", "--input"} & {x.t for x in a if not x.q})
        method = method or ("POST" if data else "GET")
        ep = s1 if len(pl) > 1 else ""
        if method == "DELETE":
            found.add("delete")
        elif method in ("POST", "PUT", "PATCH"):
            found.add("send")
            if _GH_PUBLISH_PATH.search(ep):
                found.add("publish")
    return found


# ---- package managers ---------------------------------------------------------------------------------------

NPM_VAL = frozenset({"--prefix", "-w", "--workspace", "-C", "--filter", "-F", "--registry", "--userconfig",
                     "--cache", "--tag", "--otp", "--access", "--loglevel", "--dir", "--cwd", "--scope",
                     "--workspaces-update"})
LOCAL_NPX = frozenset({"tsc", "eslint", "prettier", "jest", "vitest", "mocha", "tsx", "ts-node", "vite", "next",
                       "webpack", "nodemon", "playwright", "cypress", "turbo", "nx", "tailwindcss", "changeset",
                       "lint-staged", "husky", "rollup", "esbuild", "tsup", "storybook", "tsc-watch", "ava"})


def _pkg(p, a, c):
    pl = _pos(a, NPM_VAL)
    fl = _flags(a)
    s0 = pl[0] if pl else ""
    s1 = pl[1] if len(pl) > 1 else ""
    found = set()
    off = 0
    if p == "yarn" and s0 == "workspace" and len(pl) > 2:
        off = 2                                          # A16: `yarn workspace NAME CMD ...` runs CMD in that package
        s0, s1 = pl[2], (pl[3] if len(pl) > 3 else "")
    if p == "yarn" and s0 == "npm":
        s0, s1 = s1, (pl[off + 2] if len(pl) > off + 2 else "")   # `yarn npm publish`, `yarn workspace x npm publish`
    if s0 in ("publish", "lerna"):
        found.add("publish")
    elif s0 in ("unpublish",):
        found |= {"delete", "publish"}
    elif s0 in ("deprecate",):
        found.add("publish")
    elif s0 == "dist-tag" and s1 in ("add", "rm", "remove"):
        found.add("publish")
    elif s0 in ("install", "i", "add", "ci", "update", "up", "upgrade", "install-test", "it", "exec", "x", "dlx",
                "create", "init", "install-ci-test", "cit", "outdated-fix"):
        if s0 not in ("init",) or len(pl) > 1:
            found.add("download")
    elif s0 == "pack" and len(pl) > 1 and not pl[1].startswith((".", "/")):
        found.add("download")
    elif s0 in ("uninstall", "remove", "rm", "un", "r", "unlink"):
        found.add("delete")
    elif s0 == "cache" and s1 in ("clean", "rm", "purge"):
        found.add("delete")
    elif p == "yarn" and not pl and not fl - {"--frozen-lockfile", "--immutable"} == set():
        found.add("download")
    elif p == "yarn" and not pl:
        found.add("download")
    # A7: what the package manager starts. `pnpm exec wrangler deploy`, `npm exec -- vercel --prod`, `pnpm dlx x`; and a
    # bin run by its name (`pnpm wrangler deploy`, `yarn changeset publish`); and yarn berry's foreach.
    if p in ("npm", "pnpm", "yarn", "bun") and s0 in ("exec", "x", "dlx"):
        found |= h_npx(p, a[_pos_at(a, NPM_VAL, 1):], c)
    elif p in ("pnpm", "yarn") and s0 and s0 not in PM_OWN and s0 in H and pl:
        found |= c.run(a[_pos_at(a, NPM_VAL, off):])
    elif p == "yarn" and s0 == "workspaces" and s1 == "foreach":
        j = _pos_at(a, NPM_VAL | {"--include", "--exclude", "-j", "--jobs", "--since"}, 2)
        found |= c.run(a[_first_cmd(a, NPM_VAL | {"--include", "--exclude", "-j", "--jobs", "--since"}, j):])
    return found


# names a package manager owns itself; `pnpm test` is pnpm's, not the `test` program (A7)
PM_OWN = frozenset({"start", "watch", "time", "call", "exec", "command", "test", "install", "make", "for", "find",
                    "xargs", "env", "set", "help", "init", "pack", "cache", "list", "config", "link", "audit",
                    "version", "info", "why", "remove", "add", "up", "dlx", "create", "outdated", "publish", "run",
                    "unpublish", "x", "i", "rm", "update", "upgrade", "build", "dev", "lint", "format", "serve",
                    "stat", "file", "date", "ps", "id", "code", "touch", "kill", "cd", "rd", "dir", "type", "move",
                    "copy", "start-process"})


def _pos_at(a: list, vals, n: int) -> int:
    """The index in a of the n-th (from 0) operand: past options, the values of the options in vals, and a `--`."""
    i, skip = 0, False
    count = 0
    while i < len(a):
        w = a[i]
        if skip:
            skip = False
        elif w.t == "--" and not w.q:
            i += 1
            return min(len(a), i + n - count)
        elif _isopt(w) and len(w.t) > 1:
            skip = "=" not in w.t and (w.t in vals or w.t.lower() in vals)
        else:
            if count == n:
                return i
            count += 1
        i += 1
    return len(a)


for _n in ("npm", "pnpm", "yarn"):
    H[_n] = (lambda n: lambda p, a, c: _pkg(n, a, c))(_n)
H["bun"] = lambda p, a, c: (h_interp(p, a, c) if a and a[0].t in ("-e", "--eval", "-p") else _pkg("bun", a, c))


HELM_VAL = frozenset({"-n", "--namespace", "--kube-context", "--kubeconfig", "--kube-as-user", "--kube-as-group",
                      "--kube-apiserver", "--kube-token", "--kube-ca-file", "--kube-tls-server-name",
                      "--registry-config", "--repository-cache", "--repository-config", "--burst-limit", "--qps", "-f",
                      "--values", "--set", "--set-string", "--set-file", "--set-json", "--set-literal", "--version",
                      "--timeout", "--description", "--ca-file", "--cert-file", "--key-file", "--username", "--password",
                      "--repo", "--post-renderer", "--post-renderer-args", "--output", "-o"})


@rule("lerna", "changeset", "np", "release-it", "semantic-release", "gh-pages", "vsce", "ovsx", "snapcraft",
      "fastlane", "mvn", "mvnw", "gradle", "gradlew", "dotnet", "nuget", "gem", "bundle", "composer", "mix", "pod",
      "dart", "flutter", "cabal", "stack", "twine", "flit", "hatch", "pdm", "poetry", "uv", "pip", "pip3", "pipx",
      "conda", "mamba", "micromamba", "cargo", "go", "choco", "winget", "scoop", "apt", "apt-get", "dnf", "yum",
      "zypper", "apk", "pacman", "brew", "xcrun", "altool", "notarytool", "fastlane", "helm", "ollama", "kaggle",
      "huggingface-cli", "hf", "docker-compose")
def h_pkgmisc(p, a, c):
    pl = _pos(a, HELM_VAL if p == "helm" else frozenset())
    fl = _flags(a)
    s0 = pl[0] if pl else ""
    s1 = pl[1] if len(pl) > 1 else ""
    found: set = set()
    low = {x.t.lower() for x in a if not x.q}
    if p in RUNNERS:
        found |= _runner(p, a, c) or set()                  # poetry run X, uv run X, bundle exec X, conda run X (A7)
    if p in ("lerna", "changeset", "np", "release-it", "semantic-release", "gh-pages", "vsce", "ovsx"):
        if p in ("np", "release-it", "semantic-release", "gh-pages") or s0 == "publish":
            found.add("publish")
            if p == "gh-pages":
                found.add("push")
    elif p == "snapcraft":
        if s0 in ("upload", "push", "release"):
            found.add("publish")
    elif p == "fastlane":
        if s0 in ("deliver", "supply", "pilot", "upload_to_app_store", "upload_to_play_store", "release", "beta"):
            found.add("publish")
    elif p in ("xcrun", "altool", "notarytool"):
        if "altool" in low and "--upload-app" in low or s0 == "altool" and ("--upload-app" in low):
            found.add("publish")
        if "notarytool" in low and "submit" in low:
            found |= {"publish", "send"}
    elif p in ("mvn", "mvnw"):
        if "deploy" in low:
            found.add("publish")
        if "install" in low or any(x.startswith("dependency:") and not x.endswith(("tree", "list", "analyze"))
                                   for x in low):
            found.add("download")                           # dependency:resolve / get / go-offline fetch the jars
    elif p in ("gradle", "gradlew"):
        if any(x.startswith("publish") for x in low):
            found.add("publish")
    elif p == "dotnet":
        if s0 == "nuget" and s1 == "push" or s0 == "nuget" and s1 == "delete":
            found.add("publish")
            if s1 == "delete":
                found.add("delete")
        elif s0 in ("restore",) or s0 == "add" and s1 == "package" or s0 == "tool" and s1 in ("install", "update"):
            found.add("download")
    elif p == "nuget":
        if s0 == "push":
            found.add("publish")
        elif s0 == "delete":
            found |= {"delete", "publish"}
        elif s0 in ("install", "restore", "update"):
            found.add("download")
    elif p == "gem":
        if s0 == "push":
            found.add("publish")
        elif s0 == "yank":
            found |= {"delete", "publish"}
        elif s0 in ("install", "update", "fetch"):
            found.add("download")
        elif s0 == "uninstall":
            found.add("delete")
    elif p in ("bundle", "composer"):
        if s0 == "global" and s1:
            s0 = s1                                         # composer global require x
        if s0 in ("install", "update", "require"):
            found.add("download")
        elif s0 == "remove":
            found.add("delete")
    elif p == "mix":
        if s0 == "hex.publish":
            found.add("publish")
        elif s0 in ("deps.get", "deps.update"):
            found.add("download")
    elif p == "pod":
        if s0 == "trunk" and s1 == "push":
            found.add("publish")
        elif s0 in ("install", "update"):
            found.add("download")
    elif p in ("dart", "flutter"):
        if "publish" in pl and "pub" in pl:
            found.add("publish")
        elif "pub" in pl and ({"get", "add", "upgrade"} & set(pl)):
            found.add("download")
    elif p == "cabal" or p == "stack":
        if s0 == "upload":
            found.add("publish")
        elif s0 in ("update", "install", "fetch"):
            found.add("download")
    elif p in ("twine", "flit", "hatch", "pdm", "poetry", "uv"):
        if {"upload", "publish", "register"} & set(pl[:2]):
            found.add("publish")
        elif p in ("uv",) and s0 == "pip" and s1 == "install" or p == "uv" and s0 in ("add", "sync", "run", "tool",
                                                                                        "lock"):
            found.add("download")
        elif p == "poetry" and s0 in ("add", "install", "update"):
            found.add("download")
        elif p in ("uv", "poetry", "pdm") and (s0 in ("remove",) or s0 == "pip" and s1 == "uninstall"):
            found.add("delete")
    elif p in ("pip", "pip3", "pipx", "conda", "mamba", "micromamba"):
        if s0 in ("install", "download", "wheel", "run", "upgrade", "create", "update"):
            found.add("download")
        elif s0 in ("uninstall", "remove", "clean", "purge"):
            found.add("delete")
        elif s0 == "cache" and s1 in ("purge", "remove"):
            found.add("delete")
        elif s0 == "env" and s1 == "remove":
            found.add("delete")
        elif s0 == "env" and s1 in ("create", "update"):
            found.add("download")
    elif p == "cargo":
        if s0 == "publish":
            found.add("publish")
        elif s0 == "yank":
            found |= {"delete", "publish"}
        elif s0 in ("install", "add", "fetch", "update", "vendor"):
            found.add("download")
        elif s0 == "uninstall":
            found.add("delete")
    elif p == "go":
        if s0 in ("get", "install") or s0 == "mod" and s1 in ("download", "tidy"):
            found.add("download")
    elif p in ("choco", "winget", "scoop", "apt", "apt-get", "dnf", "yum", "zypper", "apk", "pacman", "brew"):
        if p == "choco" and s0 == "push":
            found.add("publish")
        if {"install", "add", "upgrade", "update", "reinstall", "download", "source", "-s", "-sy", "-syu",
            "fetch"} & (set(pl) | low) and "uninstall" not in low:
            found.add("download")
        if {"uninstall", "remove", "purge", "autoremove", "erase", "del", "-r", "-rs", "-rns"} & (set(pl) | low):
            found.add("delete")
        if p == "brew" and "uninstall" in low:
            found.add("delete")
    elif p == "helm":
        if s0 == "push":
            found |= {"push", "publish"}
        elif s0 == "pull" or s0 == "fetch":
            found.add("download")
        elif s0 in ("install", "upgrade"):
            found.add("publish")
            if s0 == "install":
                found.add("download")
        elif s0 in ("uninstall", "delete"):
            found.add("delete")
    elif p == "ollama":
        if s0 == "pull":
            found.add("download")
        elif s0 == "push":
            found |= {"push", "publish"}
        elif s0 == "rm":
            found.add("delete")
    elif p in ("huggingface-cli", "hf"):
        if s0 == "download":
            found.add("download")
        elif s0 == "upload":
            found.add("publish")
        elif s0 == "delete-cache" or s0 == "repo" and s1 == "delete":
            found.add("delete")
    elif p == "kaggle":
        if s1 in ("download",) or s0 == "kernels" and s1 in ("pull",):
            found.add("download")
        elif s0 == "competitions" and s1 == "submit":
            found |= {"send", "publish"}
        elif s1 in ("create", "version", "push", "init") and s0 in ("datasets", "kernels", "models"):
            found.add("publish") if s1 != "init" else None
    elif p == "docker-compose":
        return _container("docker", [Word("compose", False, False, [], False)] + a, c)
    return found


@rule("pipenv", "rye", "devbox", "asdf", "mise", "fnm", "volta", "doppler", "op", "aws-vault", "chamber",
      "direnv", "dotenv", "envchain", "dotenvx")
def h_runner(p, a, c):
    found = _runner(p, a, c) or set()
    if p in VERBS:
        found |= _verbs(p, a)                                # volta install, mise use, asdf install fetch too
    return found


# an npm package whose command is named differently (`npx firebase-tools deploy` runs `firebase deploy`; A16)
_NPX_BIN = {"firebase-tools": "firebase", "netlify-cli": "netlify", "aws-cdk": "cdk", "serverless": "serverless",
            "vercel": "vercel", "wrangler": "wrangler", "@vercel/cli": "vercel"}
_NPX_VERSION = re.compile(r"@[^/@]*+$")                  # `pkg@1.2.3` -> `pkg`
_NPX_SCOPED_VERSION = re.compile(r"(?<=.)@[^/@]*+$")


@rule("npx", "pnpx", "bunx", "uvx")
def h_npx(p, a, c):
    j = _first_cmd(a, {"-p", "--package", "-c", "--call"})
    inner = a[j:]
    found = set()
    if inner:
        nm = inner[0].t
        base = _NPX_VERSION.sub("", nm) if not nm.startswith("@") else _NPX_SCOPED_VERSION.sub("", nm)
        short = _NPX_BIN.get(base.lower(), base.rsplit("/", 1)[-1].lower())
        fl = _flags(a[:j])
        # F3: only npx runs a project's own copy first; pnpx (pnpm dlx), bunx and uvx fetch. A version (`tsc@latest`) or
        # a package named by -p/--package asks npx for a fetch, so the local exemption does not hold for them
        # G6: a scoped package (`@scope/tsc`) is another package than the project's tool: never its own copy
        # and a name not written in lower case, or `-y`/`--yes`/`--ignore-existing`/`--prefer-online`, asks for a fetch
        local = p == "npx" and short in LOCAL_NPX and nm == base.lower() and not nm.startswith("@") and \
            not {"-y", "--yes", "--ignore-existing", "--prefer-online"} & fl and \
            not any(f in ("-p", "--package") or f.startswith("--package=") or
                    f.startswith("-p") and not f.startswith("--") for f in fl)
        if not (local or {"--no-install", "--offline", "--no"} & fl):
            found.add("download")
        found |= c.run([Word(short if short not in ("netlify-cli",) else "netlify", False, False, [], False)]
                       + inner[1:])
    else:
        found.add("download")
    return found


# ---- shipping and deploying CLIs ----------------------------------------------------------------------------

DEL_TOK = frozenset({"delete", "destroy", "rm", "remove", "rmi", "del", "drop", "purge", "terminate", "uninstall",
                     "unset", "prune", "wipe", "erase", "truncate", "delete-batch", "unlink"})
PUB_TOK = frozenset({"deploy", "publish", "release", "up", "promote", "rollback", "redeploy"})


def _colon(pl: list) -> set:
    found = set()
    for t in pl[:3]:
        if ":" in t:
            end = t.rsplit(":", 1)[-1]
            if end in DEL_TOK or end in ("unset", "disable", "reset") and "pg" in t or t.endswith(":destroy"):
                found.add("delete")
            if end in PUB_TOK or end == "push" or end == "release":
                found.add("publish")
            if end == "download":
                found.add("download")
            if t.startswith("addons:create"):
                found.add("pay")
    return found


# E6: the valued options of single programs among these, which the shared table above lacks (`s3cmd --config ~/.s3cfg
# put ...` and `minikube -p staging delete` took the value for the subcommand)
_INFRA_VAL = {"s3cmd": frozenset({"-c", "--config", "--access_key", "--secret_key", "--access_token", "-m", "--mime-type",
                                  "--add-header", "--remove-header", "--bucket-location", "--exclude", "--include",
                                  "--rexclude", "--rinclude", "--exclude-from", "--include-from", "--cache-file",
                                  "--storage-class", "--encoding", "--host", "--host-bucket"}),
              "minikube": frozenset({"-p", "--profile", "--driver", "--kubernetes-version", "--cpus", "--memory",
                                     "--container-runtime", "--nodes"})}


@rule("terraform", "tofu", "pulumi", "cdk", "sam", "serverless", "sls", "cf", "eb", "amplify", "railway", "render",
      "surge", "supabase", "prisma", "rails", "artisan", "sequelize-cli", "knex", "flyway", "alembic", "kind",
      "minikube", "ctr", "crictl", "skopeo", "oras", "crane", "etcdctl", "consul", "vault", "influx", "doctl",
      "hcloud", "linode-cli", "pscale", "turso", "mc", "s3cmd", "gdrive", "bq", "mysqladmin", "az", "okta")
def h_infra(p, a, c):
    vals = {"--profile", "--region", "-g", "--resource-group", "--subscription", "-n", "--name", "--query", "-o",
            "--output", "-f", "--env", "--stage", "--target"} | _INFRA_VAL.get(p, frozenset())
    pl = _pos(a, vals)
    fl = _flags(a)
    s0 = pl[0] if pl else ""
    s1 = pl[1] if len(pl) > 1 else ""
    found: set = set()
    low = {x.t.lower() for x in a if not x.q}
    if p in ("terraform", "tofu"):
        if s0 == "destroy" or s0 == "apply" and "-destroy" in low:
            found.add("delete")
        elif s0 == "apply":
            found.add("publish")
        elif s0 == "state" and s1 in ("rm",) or s0 == "workspace" and s1 == "delete":
            found.add("delete")
        elif s0 in ("init", "get") and ({"-upgrade", "-update"} & low):
            found.add("download")
    elif p == "pulumi":
        if s0 == "destroy" or s0 == "stack" and s1 in ("rm", "remove"):
            found.add("delete")
        elif s0 == "up":
            found.add("publish")
    elif p in ("cdk", "sam", "serverless", "sls", "cf", "eb", "amplify", "railway", "render", "surge"):
        if s0 in ("destroy", "remove", "delete"):
            found.add("delete")
        elif s0 in ("deploy", "up", "push", "publish", "release") or p == "surge" and not s0.startswith("tele"):
            found.add("publish")
    elif p == "supabase":
        if s0 == "db" and s1 == "reset" or DEL_TOK & set(pl[:3]):
            found.add("delete")                              # db reset, projects delete, functions delete, branches delete
        elif s0 in ("functions", "db") and s1 in ("deploy", "push"):
            found.add("publish")
    elif p == "prisma":
        if s0 == "migrate" and s1 == "reset" or s0 == "db" and ("--force-reset" in fl):
            found.add("delete")
        if s0 == "db" and s1 == "push" or s0 == "migrate" and s1 == "deploy":
            found.add("publish")                             # pushes the schema to the database
            if "--accept-data-loss" in fl:
                found.add("delete")
    elif p in ("rails", "artisan", "sequelize-cli", "knex", "alembic", "flyway"):
        if any(t.endswith((":drop", ":wipe", ":reset", ":fresh", ":clean")) or t in ("db:drop", "clean") for t in pl):
            found.add("delete")
    elif p in ("kind", "minikube"):
        if s0 == "delete":
            found.add("delete")
    elif p == "ctr":
        if "rm" in pl[:4] or "delete" in pl[:4]:
            found.add("delete")
    elif p == "crictl":
        if s0 in ("rm", "rmi", "rmp", "stop"):
            found.add("delete") if s0 != "stop" else None
    elif p == "skopeo":
        if s0 == "delete":
            found.add("delete")
        elif s0 == "copy":
            found |= {"download", "push"}
    elif p in ("oras", "crane"):
        if s0 == "push":
            found.add("push")
        elif s0 in ("pull",):
            found.add("download")
        elif s0 in ("delete",):
            found.add("delete")
    elif p in ("etcdctl", "consul", "vault", "influx", "doctl", "hcloud", "linode-cli", "pscale", "turso", "mc",
               "s3cmd", "gdrive", "bq", "mysqladmin", "okta"):
        if DEL_TOK & set(pl[:4]) or {"destroy"} & set(pl[:4]):
            found.add("delete")
        if p == "mc" and s0 in ("cp", "mirror") or p == "s3cmd" and s0 in ("put", "sync") or \
                p == "gdrive" and s0 == "upload":
            found.add("publish")
        if p == "s3cmd" and s0 == "get" or p == "gdrive" and s0 == "download":
            found.add("download")
        if p == "doctl" and s0 == "apps" and s1 in ("create", "update", "create-deployment") or \
                p == "doctl" and s0 == "serverless" and s1 == "deploy":
            found.add("publish")
        if p == "bq":
            for x in a:
                found |= _sql(x.t, "bq", c.work)
        if p == "mysqladmin" and "drop" in {x.t.lower() for x in a if not x.q}:
            found.add("delete")
    elif p == "az":
        found |= _cloud_tokens(pl[:6], fl, a)
        if s0 == "rest":                                     # az rest --method post --url .../sendMail
            for k, w in enumerate(a):
                m = a[k + 1].t.upper() if not w.q and w.t in ("--method", "-m") and k + 1 < len(a) else \
                    w.t.split("=", 1)[1].upper() if w.t.startswith("--method=") else ""
                if m in ("POST", "PUT", "PATCH"):
                    found.add("send")
                elif m == "DELETE":
                    found.add("delete")
        if {"repos", "pr"} <= set(pl[:3]) and set(pl[:5]) & {"create", "update", "set-vote"}:
            found |= {"publish", "send"}
    return found


def _cloud_tokens(pl: list, fl: set, a: list) -> set:
    found = set()
    toks = set(pl)
    if toks & DEL_TOK or any(t.startswith("delete") for t in pl):
        found.add("delete")
    if "purchase" in toks or "buy" in toks or any(t.startswith("purchase-") for t in pl):
        found.add("pay")
    if "upload" in toks or "upload-batch" in toks:
        found.add("publish")
    if "download" in toks or "download-batch" in toks:
        found.add("download")
    if toks & {"deploy", "up", "publish", "config-zip"} or {"deployment", "create"} <= toks:
        found.add("publish")
    if "send" in toks and ("email" in toks or "sms" in toks):
        found.add("send")
    low = [x.t for x in a]
    for k, t in enumerate(low):
        if t in ("--command", "--scripts", "--command-id") or t.startswith(("--command=", "--scripts=")):
            pass
    return found


_BRACKETS = re.compile(r'[\[\]"]')

# The aws options that take a value (global, and the s3 transfer commands', from the AWS CLI's own reference). A16: an
# s3 option value was taken for the source or the destination. E2: each is read by its own SHAPE, not as one word each.
AWS_VAL = frozenset({"--profile", "--region", "--output", "--query", "--endpoint-url", "--filters", "--cli-input-json",
                     "--cli-input-yaml", "--ca-bundle", "--color", "--cli-read-timeout", "--cli-connect-timeout",
                     "--cli-binary-format", "--exclude", "--include", "--acl", "--cache-control", "--sse",
                     "--sse-kms-key-id", "--storage-class", "--content-type", "--content-encoding",
                     "--content-disposition", "--content-language", "--expires", "--metadata", "--metadata-directive",
                     "--grants", "--website-redirect", "--source-region", "--request-payer", "--page-size", "--sse-c",
                     "--sse-c-key", "--sse-c-copy-source", "--sse-c-copy-source-key", "--copy-props", "--checksum-mode",
                     "--checksum-algorithm", "--expected-size"})
_AWS_LIST = frozenset({"--grants", "--filters"})       # a LIST: its values run until the next option
# an OPTIONAL value: the next word is its value only when it is a legal one ("if the parameter is specified but no value
# is provided, AES256 is used"; --request-payer's only value is requester)
_AWS_OPTIONAL = {"--sse": frozenset({"aes256", "aws:kms", "aws:kms:dsse"}), "--sse-c": frozenset({"aes256"}),
                 "--sse-c-copy-source": frozenset({"aes256"}), "--request-payer": frozenset({"requester"})}
_AWS_FLAGS = frozenset({"--recursive", "--dryrun", "--quiet", "--only-show-errors", "--no-progress", "--follow-symlinks",
                        "--no-follow-symlinks", "--no-guess-mime-type", "--ignore-glacier-warnings",
                        "--force-glacier-transfer", "--delete", "--exact-timestamps", "--size-only", "--no-overwrite",
                        "--debug", "--no-verify-ssl", "--no-paginate", "--no-sign-request", "--no-cli-pager",
                        "--cli-auto-prompt", "--no-cli-auto-prompt", "--human-readable", "--summarize", "--force"})


def _aws_words(a: list) -> tuple:
    """(operands, every non-option word, sure) of an aws call, lower-cased. The operands are the words past the options
    and past the values of the options in AWS_VAL, each by its own shape (E2): --grants and --filters take a LIST (every
    word up to the next option); --sse, --sse-c, --sse-c-copy-source and --request-payer take an OPTIONAL value (the next
    word only when it is a legal one); every other one takes the next word. Every non-option word comes as (word, it is
    an operand). sure is False when a word could be an operand or the value of an option no table here lists (an
    unknown option stood before it)."""
    ops, allw, sure, i, n = [], [], True, 0, len(a)
    while i < n:
        w = a[i]
        t = w.t
        i += 1
        if not (_isopt(w) and len(t) > 1):
            ops.append(t.lower())
            allw.append((t.lower(), True))
            continue
        if t == "--":
            rest = [x.t.lower() for x in a[i:]]
            ops.extend(rest)
            allw.extend((x, True) for x in rest)
            break
        low = t.lower()
        if "=" in low:
            continue
        if low in _AWS_OPTIONAL:
            if i < n and not _isopt(a[i]) and a[i].t.lower() in _AWS_OPTIONAL[low]:
                allw.append((a[i].t.lower(), False))
                i += 1
        elif low in _AWS_LIST:
            while i < n and not _isopt(a[i]):
                allw.append((a[i].t.lower(), False))
                i += 1
        elif low in AWS_VAL:
            if i < n and not _isopt(a[i]):
                allw.append((a[i].t.lower(), False))
                i += 1
        elif low not in _AWS_FLAGS and i < n and not _isopt(a[i]):
            sure = False
    return ops, allw, sure


@rule("aws")
def h_aws(p, a, c):
    pl, allw, sure = _aws_words(a)
    fl = _flags(a)
    svc = pl[0] if pl else ""
    op = pl[1] if len(pl) > 1 else ""
    found: set = set()
    if svc == "s3api" and op == "get-object":
        return {"download"}                                  # the object's body goes to a file (A10)
    if svc in ("s3", "s3api") and svc == "s3" and op in ("cp", "mv", "sync"):
        # E2: the source and the destination are the FIRST two operands (the AWS CLI's own order: `cp <src> <dst>`);
        # r5 took the last two and a --grants list moved them (an upload read as a download). Where the operands cannot
        # be read with certainty (not exactly two of them, or an option no table lists stood before a word), every act
        # the order of the words allows is named, the costly direction: a local path before an s3:// one is an upload
        # (publish), an s3:// one before a local path is a download; both when both orders occur. With fewer than two
        # operands an option's value may be the operand it ate (`--exclude ./dist s3://b`), so the values are in that
        # order too. That is the first reading's backstop, made against its own table: the second and third readings
        # (every option valued, the table's options as flags) leave a list's other values, or the values, among their
        # operands, so they read the first two only.
        ops = pl[2:]
        src, dst = (ops[0] if ops else ""), (ops[1] if len(ops) > 1 else "")
        if dst.startswith("s3://"):
            found.add("publish")
        if src.startswith("s3://") and not dst.startswith("s3://"):
            found.add("download")
        if not c.alt and (not sure or len(ops) != 2):
            seen_local = seen_s3 = False
            k = nops = 0
            while k < len(allw) and nops < 2:                # the words after the service and the command
                nops += allw[k][1]
                k += 1
            for t, is_op in allw[k:]:
                if not is_op and len(ops) >= 2:
                    continue
                if t.startswith("s3://"):
                    if seen_local:
                        found.add("publish")
                    seen_s3 = True
                else:
                    if seen_s3:
                        found.add("download")
                    seen_local = True
        if op == "mv" or "--delete" in fl:
            found.add("delete")
        return found
    if svc == "s3" and op in ("rm", "rb"):
        return {"delete"}
    if op.startswith(("delete", "terminate", "deregister", "remove", "purge", "batch-delete", "destroy")) or \
            op.endswith("-delete"):
        found.add("delete")
    elif op.startswith(("describe", "list", "get-", "head", "ls", "tail", "show", "lookup", "search", "view")):
        return found
    if op in ("send-email", "send-raw-email", "send-templated-email", "send-bulk-email", "send-message",
              "send-message-batch", "send-command", "send-bulk-templated-email") or svc == "sns" and op == "publish":
        found.add("send")
    if svc == "sns" and op == "publish" or svc == "pubsub":
        found.add("publish")
    if op in ("update-function-code", "publish-version", "create-function", "deploy", "create-deployment",
              "start-deployment", "put-object", "put-object-acl", "put-bucket-policy", "put-bucket-website",
              "create-invalidation", "update-service", "put-image", "upload-layer-part", "publish-layer-version") \
            or svc == "deploy" and op == "create-deployment" or "--publish" in fl:
        found.add("publish")
    if svc == "cloudformation" and op == "deploy":
        found.add("publish")
    if op in ("register-domain", "renew-domain", "transfer-domain") or op.startswith("purchase-") or \
            op in ("create-savings-plan",):
        found.add("pay")
    if op == "send-command":
        for x in a:
            if "commands=" in x.t:
                found |= c.read(_BRACKETS.sub(" ", x.t.split("commands=", 1)[1]), False)
    return found


@rule("gcloud", "gsutil")
def h_gcloud(p, a, c):
    vals = {"--project", "--zone", "--region", "--account", "--format", "--filter"}
    pl = _pos(a, vals)
    fl = _flags(a)
    toks = set(pl[:7])
    found: set = set()
    if p == "gsutil":
        s0 = pl[0] if pl else ""
        if s0 == "rm":
            found.add("delete")
        elif s0 in ("cp", "mv", "rsync"):
            src, dst = pl[1] if len(pl) > 1 else "", pl[-1] if len(pl) > 2 else ""
            if dst.startswith("gs://"):
                found.add("publish")
            if src.startswith("gs://") and not dst.startswith("gs://"):
                found.add("download")
            if s0 == "mv" or "-d" in fl:
                found.add("delete")
        elif s0 in ("acl", "iam", "web", "defacl") and ({"ch", "set"} & set(pl[1:3])):
            found.add("publish")
        return found
    if toks & DEL_TOK or "delete" in toks:
        found.add("delete")
    if "storage" in toks and ("cp" in toks or "mv" in toks or "rsync" in toks):
        rest = [t for t in pl if t.startswith("gs://") or t.startswith(".") or "/" in t or t.endswith(("csv", "json"))]
        dst = pl[-1] if pl else ""
        if dst.startswith("gs://"):
            found.add("publish")
        elif any(t.startswith("gs://") for t in pl):
            found.add("download")
    if {"builds", "submit"} <= toks:
        found.add("publish")                                 # gcloud builds submit --tag: builds and pushes an image
    if toks & {"deploy", "publish"} and "describe" not in toks and "list" not in toks:
        found.add("publish")
        if "publish" in toks and "topics" in toks:
            found.add("send")
    if "register" in toks and "domains" in toks or "purchase" in toks:
        found.add("pay")
    if "ssh" in toks:
        for k, w in enumerate(a):
            if w.t == "--command" and k + 1 < len(a):
                found |= c.read(a[k + 1].t, False)
            elif w.t.startswith("--command="):
                found |= c.read(w.t[10:], False)
    if "scp" in toks:                              # the flag values are not operands, wherever the flags stand (A9)
        found |= _transfer(a, c, frozenset({"--zone", "--project", "--region", "--account", "--format", "--filter",
                                            "--ssh-key-file", "--port", "--scp-flag", "--ssh-flag", "--command",
                                            "--billing-project", "--impersonate-service-account"}))
    return found


def _remote(t: str) -> bool:
    if "://" in t:
        return t.split("://")[0].lower() != "file"
    if len(t) > 1 and t[1] == ":" and t[0].isalpha() and (len(t) == 2 or t[2] in "\\/"):
        return False
    i = t.find(":")
    return i > 0 and "/" not in t[:i] and "\\" not in t[:i]


WEB_PATH = re.compile(r"/(?:www|html|htdocs|public|public_html|static|web|site)\b|\$web\b|s3://|gs://", re.I)


def _transfer(a: list, c, vals=frozenset()) -> set:
    pw = _posw(a, vals | {"-P", "-i", "-o", "-F", "-c", "-l", "-S", "-J", "-e", "--rsh", "--port", "--exclude",
                            "--include", "--bwlimit", "-f", "--filter", "--files-from", "--log-file", "--rsync-path"})
    found = set()
    if len(pw) < 2:
        return found
    srcs, dst = [w.t for w in pw[:-1]], pw[-1].t
    rd, rs = _remote(dst), any(_remote(s) for s in srcs)
    if rd:
        found.add("send")
        if WEB_PATH.search(dst):
            found.add("publish")
    elif rs:
        found.add("download")
    return found


@rule("scp", "rsync")
def h_scp(p, a, c):
    fl = _flags(a)
    if p == "rsync" and "--version" in fl:
        return set()
    found = _transfer(a, c)
    if p == "rsync" and any(f.startswith(("--delete", "--del", "--remove-source")) for f in fl):
        found.add("delete")
    return found


_FTP_GET = re.compile(r"\b(?:get|mget|reget|pget)\b")
# `mirror -R` / `-aR`: an option cluster holding r. `-\w*r` retried the cluster from every `-`; the cluster is now walked
# once: word characters that are not r (possessively), then the r.
_FTP_PUT = re.compile(r"\b(?:put|mput|reput)\b|\bmirror\s++(?:-(?:(?!r)\w)*+r|--reverse)", re.I)
_FTP_DEL = re.compile(r"\b(?:rm|del|rmdir|mrm|delete)\b")
_FTP_MIRROR = re.compile(r"\bmirror\b")


def _ftp_text(text: str, c: _C | None = None) -> set:
    if c is not None and c.spend(len(text)):
        return set(ALL)
    found = set()
    low = text.lower()
    if _FTP_PUT.search(low):
        found.add("send")
    if _FTP_GET.search(low) or _FTP_MIRROR.search(low) and "send" not in found:
        found.add("download")
    if _FTP_DEL.search(low):
        found.add("delete")
    return found


@rule("sftp", "ftp", "lftp", "smbclient", "tftp")
def h_ftp(p, a, c):
    found: set = set()
    for tx in [w.t for w in a if w.q or " " in w.t]:
        key = ("ftp", tx)                                   # kept and charged like a here-document (A1)
        hit = c.work[2].get(key)
        if hit is None:
            hit = c.work[2][key] = _ftp_text(tx, c)
        found |= hit
    found |= _seg_stdin("ftp", c)                           # the segment's here-documents and here-strings: read once
    if p in ("lftp",) and found & {"send"}:
        found.add("publish")
    return found or {"send"} if p in ("sftp", "ftp") and not found else found


@rule("rclone")
def h_rclone(p, a, c):
    pl = _posw(a)
    fl = _flags(a)
    s0 = pl[0].t.lower() if pl else ""
    found = set()
    if s0 in ("delete", "purge", "deletefile", "rmdir", "rmdirs", "cleanup"):
        return {"delete"}
    if s0 in ("copy", "sync", "move", "copyto", "moveto", "bisync"):
        src, dst = (pl[1].t if len(pl) > 1 else ""), (pl[2].t if len(pl) > 2 else "")
        if _remote(dst) and not _remote(src):
            found |= {"publish", "send"}
        elif _remote(src) and not _remote(dst):
            found.add("download")
        elif _remote(src) and _remote(dst):
            found |= {"send"}
        if s0 in ("sync", "bisync", "move", "moveto"):
            found.add("delete")
    return found


@rule("ssh", "mosh", "vagrant", "lxc", "incus", "nsenter")
def h_ssh(p, a, c):
    if p == "vagrant":
        for k, w in enumerate(a):
            if w.t in ("-c", "--command") and k + 1 < len(a):
                return c.read(a[k + 1].t, False)
        return {"delete"} if "destroy" in _pos(a)[:2] else set()        # vagrant destroy -f
    if p in ("lxc", "incus"):
        pl = [w for w in a]
        for k, w in enumerate(pl):
            if w.t == "--":
                return c.run(pl[k + 1:])
        return {"delete"} if DEL_TOK & set(_pos(a)[:3]) else set()      # lxc delete c1 --force, lxc image delete
    host, rest = _ssh_rest(a)
    if host is None or not rest:
        return set()
    return c.read(rest[0].t if len(rest) == 1 else " ".join(x.t for x in rest), False)


# ---- containers and clusters --------------------------------------------------------------------------------

CTR_VAL = frozenset({"-v", "--volume", "-p", "--publish", "-e", "--env", "-u", "--user", "-w", "--workdir", "--name",
                     "-l", "--label", "--network", "--net", "--entrypoint", "-h", "--hostname", "--mount", "--cpus",
                     "-m", "--memory", "--restart", "--platform", "--pull", "--env-file", "--add-host", "--device",
                     "--cap-add", "--cap-drop", "--security-opt", "--shm-size", "--tmpfs", "--gpus", "--log-driver",
                     "--pid", "--ipc", "--dns", "-c", "--cidfile", "--user", "--group-add", "--ulimit", "-f",
                     "--file", "-H", "--host", "--context", "--project-name", "-p",
                     # A16/A17: the global options of docker and compose that take a value, and the run options this
                     # table lacked (`--link db:db` was taken for the image; `--log-level error` for the subcommand)
                     "--log-level", "--config", "--profile", "--project-directory", "--ansi", "--progress", "--parallel",
                     "--link", "--volumes-from", "--expose", "--ip", "--ip6", "--mac-address", "--label-file",
                     "--cgroup-parent", "--health-cmd", "--health-interval", "--health-retries", "--health-timeout",
                     "--stop-signal", "--stop-timeout", "--storage-opt", "--sysctl", "--runtime", "--isolation",
                     "--userns", "--uts", "--domainname", "--dns-search", "--dns-option", "--cpuset-cpus",
                     "--cpu-shares", "--pids-limit", "--detach-keys", "--tlscacert", "--tlscert", "--tlskey",
                     "--attach", "--blkio-weight", "--oom-score-adj", "--kernel-memory", "--memory-swap",
                     "--memory-reservation"})


def _container(p, a, c):
    pl = _pos(a, CTR_VAL)
    fl = _flags(a)
    s0 = pl[0] if pl else ""
    s1 = pl[1] if len(pl) > 1 else ""
    if s0 in ("container", "image", "volume", "network", "manifest", "context", "buildx", "system", "compose",
              "builder", "machine", "node", "service", "secret", "stack", "config", "plugin", "swarm", "trust"):
        grp, op = s0, s1
    else:
        grp, op = "", s0
    found: set = set()
    if op == "push" or "--push" in fl or op == "imagetools" and "create" in pl:
        found.add("push")
    # A6: rm, rmi and prune delete in EVERY group (builder, buildx, service, stack, secret, config, plugin...), which the
    # base named and an earlier list of groups dropped; `kill` stops a container and is not a delete
    if op in ("rm", "rmi", "prune", "reset", "remove") or grp == "compose" and op == "down" or \
            grp == "swarm" and op == "leave" or grp == "trust" and op == "revoke":
        found.add("delete")
    if grp == "stack" and op in ("deploy", "up") or grp == "service" and op in ("create", "update", "rollback"):
        found.add("publish")                                # a swarm deploy ships to the cluster
    if op == "pull" or op in ("run", "create") and grp in ("", "container") or grp == "compose" and \
            op in ("pull",):
        found.add("download")
    if op in ("exec", "run") and grp in ("", "container", "compose"):
        j = _inner_index(a, op)
        if j is not None:
            entry = _entrypoint(a[:j]) if op == "run" else None
            # A16: `docker run --entrypoint sh alpine -c 'rm -rf /data/*'` runs sh, with the words after the image as its
            # arguments; the image's own command is replaced
            found |= c.run(([entry] if entry is not None else []) + a[j:])
    return found


def _entrypoint(before_image: list):
    """The Word of a docker run `--entrypoint X` / `--entrypoint=X` given before the image, or None."""
    for k, w in enumerate(before_image):
        if w.q:
            continue
        if w.t == "--entrypoint" and k + 1 < len(before_image) and before_image[k + 1].t:
            return before_image[k + 1]
        if w.t.startswith("--entrypoint=") and len(w.t) > 13:
            return Word(w.t[13:], False, False, [], False)
    return None


def _inner_index(a: list, op: str):
    """Index in a of the command run inside a container: past the container (exec) or image (run) argument."""
    seen_op, skip = False, False
    pos = 0
    for k, w in enumerate(a):
        t = w.t
        if skip:
            skip = False
            continue
        if not w.q and t.startswith("-") and len(t) > 1:
            if "=" not in t and t in CTR_VAL:
                skip = True
            continue
        if not seen_op:
            if t.lower() == op:
                seen_op = True
            continue
        if t.lower() == "exec" or t.lower() == "run":
            continue
        return k + 1                                 # the container or image; the command starts after it
    return None


@rule("docker", "podman", "nerdctl")
def h_docker(p, a, c):
    return _container(p, a, c)


KUBE_VAL = frozenset({"-n", "--namespace", "-c", "--container", "--context", "--kubeconfig", "-s", "--server", "-f",
                      "--filename", "-l", "--selector", "-o", "--output", "--cluster", "--user", "-t", "-i",
                      # A16/A17: the global options that take a value (`kubectl --as admin delete ns staging`)
                      "--as", "--as-group", "--as-uid", "--token", "--username", "--password", "--certificate-authority",
                      "--client-certificate", "--client-key", "--request-timeout", "--cache-dir", "--field-selector",
                      "--sort-by", "--tls-server-name", "--profile", "--profile-output", "-v", "--v", "--vmodule"})


@rule("kubectl", "oc", "k")
def h_kubectl(p, a, c):
    pl = _pos(a, KUBE_VAL)
    fl = _flags(a)
    s0 = pl[0] if pl else ""
    s1 = pl[1] if len(pl) > 1 else ""
    found: set = set()
    if s0 == "delete":
        found.add("delete")
    elif s0 in ("apply", "create", "replace", "patch", "scale", "set", "expose", "run", "annotate", "label") or \
            s0 == "rollout" and s1 in ("undo", "restart"):
        found.add("publish")
    elif s0 == "config" and s1 in ("delete-context", "delete-cluster", "unset", "delete-user"):
        found.add("delete")
    elif s0 == "cp":
        ws = [w.t for w in _posw(a, KUBE_VAL)][1:]
        if ws and ":" in ws[0] and not (len(ws) > 1 and ":" in ws[1]):
            found.add("download")
        elif len(ws) > 1:
            found.add("send")
    elif s0 == "exec":
        for k, w in enumerate(a):
            if w.t == "--":
                found |= c.run(a[k + 1:])
                break
        else:
            j = _inner_index(a, "exec")
            if j is not None:
                found |= c.run(a[j:])
    return found


# ---- network and mail ---------------------------------------------------------------------------------------

_PAY_HOST = re.compile(r"stripe\.com|paypal\.com|squareup\.com|adyen\.com|braintreegateway\.com|mollie\.com|"
                       r"razorpay\.com|paddle\.com|gocardless\.com|checkout\.com|wise\.com|coinbase\.com|"
                       r"binance\.com|kraken\.com|alpaca\.markets|bitstamp\.net", re.I)
_PAY_PATH = re.compile(r"/v\d/(?:charges|payment_intents|payouts|transfers|payments|refunds|checkout|topups)|"
                       r"/checkout/orders|/payment_links", re.I)
_PUB_PATH = re.compile(r"/(?:releases|deploys|deployments|publish|pages/builds)\b", re.I)
CURL_VALS = frozenset("AbcCdDeEFHKmoPQrtTuUwxXyYz")
CURL_LONG_VAL = frozenset({"--request", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
                           "--form", "--form-string", "--header", "--output", "--upload-file", "--user", "--url",
                           "--json", "--mail-from", "--mail-rcpt", "--proxy", "--cookie", "--user-agent",
                           "--referer", "--connect-timeout", "--max-time", "--retry", "--cacert", "--cert", "--key",
                           "--resolve", "--write-out", "--config", "--range", "--oauth2-bearer", "--output-dir",
                           "--limit-rate", "--cookie-jar", "--dump-header", "--proxy-user", "--retry-delay",
                           "--expect100-timeout", "--aws-sigv4", "--interface"})
CURL_DATA_LONG = frozenset({"--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "--form",
                            "--form-string", "--json", "--upload-file", "--mail-rcpt"})


def _urls_extras(urls: list, sends: bool) -> set:
    found = set()
    if sends:
        for u in urls:
            if _PAY_HOST.search(u) or _PAY_PATH.search(u):
                found.add("pay")
            if _PUB_PATH.search(u):
                found.add("publish")
    return found


@rule("curl")
def h_curl(p, a, c):
    method, data, out, head, upload, urls = None, False, False, False, False, []
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t
        i += 1
        if w.q or not t.startswith("-") or t == "-":
            urls.append(t)
            continue
        if t.startswith("--"):
            name, eq, val = t.partition("=")
            name = name.lower()
            if name in CURL_LONG_VAL and not eq:
                val = a[i].t if i < n else ""
                i += 1
            if name == "--request":
                method = val.upper()
            elif name in CURL_DATA_LONG:
                data = True
                if name == "--upload-file":
                    upload = True
            elif name in ("--output", "--remote-name", "--remote-name-all"):
                out = True
            elif name == "--head":
                head = True
            elif name == "--url":
                urls.append(val)
            continue
        letters, j = t[1:], 0
        while j < len(letters):
            ch = letters[j]
            if ch in CURL_VALS:
                val = letters[j + 1:]
                if not val:
                    val = a[i].t if i < n else ""
                    i += 1
                if ch == "X":
                    method = val.upper()
                elif ch in "dF":
                    data = True
                elif ch == "o":
                    out = True
                elif ch == "T":
                    data = upload = True
                break
            if ch == "O":
                out = True
            elif ch == "I":
                head = True
            j += 1
    found: set = set()
    if head and not data:
        return found
    m = method or ("PUT" if upload else "POST" if data else "GET")
    sends = m in ("POST", "PUT", "PATCH") or (data and m not in ("DELETE",))
    if sends:
        found.add("send")
    if m == "DELETE":
        found.add("delete")
    if out and not sends:
        found.add("download")
    found |= _urls_extras(urls, sends)
    if c.seg is not None and not sends and m == "GET" and _writes_file(c.seg):
        found.add("download")
    return found


def _writes_file(sg) -> bool:
    """Whether a redirection of the segment writes a file. Found once per segment: the N siblings of
    `find -exec curl u \\; ... > f > f ...` each looped over all M redirections (N x M, A14)."""
    if sg.outred is None:
        sg.outred = any(op in (">", ">>") and w.t.lower() not in ("/dev/null", "nul", "$null") for op, w in sg.redirs)
    return sg.outred


@rule("wget", "wget2")
def h_wget(p, a, c):
    low = [x.t.lower() for x in a if not x.q or _isopt(x)]        # A16: `--post-data='a=1'` is a quoted option and an option
    if "--spider" in low:
        return set()
    if "--method=delete" in low or any(t == "--method" and k + 1 < len(low) and low[k + 1] == "delete"
                                       for k, t in enumerate(low)):
        return {"delete"}                                   # the verb is read, as curl's is (A9)
    if any(t.startswith(("--post-data", "--post-file", "--body-data", "--body-file")) or
           t in ("--method=post", "--method=put", "--method=patch") for t in low) or \
            any(t == "--method" and k + 1 < len(low) and low[k + 1] in ("post", "put", "patch")
                for k, t in enumerate(low)):
        return {"send"}
    stdout = "--output-document=-" in low or any(
        t.startswith("-") and not t.startswith("--") and t.endswith("o-") for t in low) or \
        any(t == "-o" and k + 1 < len(low) and low[k + 1] == "-" for k, t in enumerate(low))
    if stdout:
        return set()
    return {"download"}


_VERBS = {"get", "post", "put", "patch", "delete", "head", "options"}


@rule("http", "https", "xh", "xhs", "httpie", "curlie")
def h_httpie(p, a, c):
    vals = {"-a", "--auth", "-A", "--auth-type", "--proxy", "--timeout", "-o", "--output", "--session", "--pretty",
            "--style", "--print", "-p", "--verify", "--cert", "--max-redirects"}
    pw = _posw(a, vals)
    fl = _flags(a)
    verb, items = None, []
    for k, w in enumerate(pw):
        if k == 0 and w.t.lower() in _VERBS:
            verb = w.t.upper()
        elif k <= 1 and "://" in w.t or k == (1 if verb else 0):
            continue
        else:
            items.append(w.t)
    data = any(("=" in x and "==" not in x) or x.startswith("@") or ":=" in x for x in items)
    m = verb or ("POST" if data else "GET")
    found = set()
    if m in ("POST", "PUT", "PATCH"):
        found.add("send")
    elif m == "DELETE":
        found.add("delete")
    if {"--download", "-d"} & fl and m == "GET":
        found.add("download")
    return found


_PS_HTTP_VAL = ("uri", "method", "body", "infile", "outfile", "headers", "contenttype", "credential", "timeoutsec",
                "useragent", "websession", "proxy", "token", "authentication", "form", "maximumredirection",
                "sessionvariable", "transferencoding", "certificate", "certificatethumbprint")


@rule("invoke-webrequest", "invoke-restmethod", "iwr", "irm")
def h_iwr(p, a, c):
    method = body = outfile = infile = None
    urls = []
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t
        i += 1
        if w.q or not t.startswith("-"):
            urls.append(t)
            continue
        name, _, val = t[1:].lower().partition(":")
        key = next((v for v in _PS_HTTP_VAL if len(name) >= 3 and v.startswith(name)), None)
        if key and not val:
            val = a[i].t if i < n else ""
            i += 1
        if key == "method":
            method = val.upper()
        elif key == "body":
            body = val or "x"
        elif key == "outfile":
            outfile = val
        elif key == "infile":
            infile = val
        elif key == "uri":
            urls.append(val)
    m = method or ("POST" if body or infile else "GET")
    found = set()
    sends = m in ("POST", "PUT", "PATCH", "MERGE") or bool(infile)
    if sends:
        found.add("send")
    if m == "DELETE":
        found.add("delete")
    if outfile and not sends:
        found.add("download")
    found |= _urls_extras(urls, sends)
    return found


@rule("start-bitstransfer")
def h_bits(p, a, c):
    low = {x.t.lower() for x in a if not x.q}
    return {"send"} if "upload" in low or "-upload" in low else {"download"}


_PS_SP_VALS = ("filepath", "argumentlist", "workingdirectory", "verb", "windowstyle", "redirectstandardoutput",
               "redirectstandarderror", "redirectstandardinput", "credential", "environment")


def _win_argv(items: list) -> list:
    """The argv a Windows program gets when the (text, dyn) items are joined with single spaces into ONE command line
    (as Start-Process does with an -ArgumentList array, documented, and as runas hands its program string to the system)
    and the child splits that line by the Windows rules (CommandLineToArgvW and the C runtime): white space separates; a
    double quote opens or closes a quoted run, in which white space is kept; 2n backslashes before a quote give n and the
    quote delimits, 2n+1 give n and a literal quote; `""` inside a quoted run is a literal quote; other backslashes are
    literal. Each argument is a Word: q when any of it was quoted, dyn when it came from an item the outer shell expanded
    and holds a `$`. E1: an array item that held a space was kept as ONE word (`'push origin main', '--force'` named
    nothing); the child sees `push origin main --force`. Linear: every character is looked at once."""
    words: list = []
    buf: list = []
    q = dyn = on = inq = False
    for k, (text, d) in enumerate(items):
        if k and (on or inq):
            if inq:
                buf.append(" ")                    # the joining space inside a quoted run is kept
            else:
                words.append(Word("".join(buf), q, dyn and "$" in "".join(buf), [], False))
                buf, q, dyn, on = [], False, False, False
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch == "\\":
                j = i
                while j < n and text[j] == "\\":
                    j += 1
                if j < n and text[j] == '"':
                    buf.append("\\" * ((j - i) // 2))
                    if (j - i) % 2:
                        buf.append('"')            # an escaped quote is a literal one
                        j += 1
                else:
                    buf.append(text[i:j])
                on, dyn, i = True, dyn or d, j
            elif ch == '"':
                if inq and text[i + 1:i + 2] == '"':
                    buf.append('"')
                    i += 2
                else:
                    inq = not inq
                    i += 1
                on, q, dyn = True, True, dyn or d
            elif ch in " \t" and not inq:
                if on:
                    words.append(Word("".join(buf), q, dyn and "$" in "".join(buf), [], False))
                    buf, q, dyn, on = [], False, False, False
                i += 1
            else:
                buf.append(ch)
                on, dyn = True, dyn or d
                i += 1
    if on:
        words.append(Word("".join(buf), q, dyn and "$" in "".join(buf), [], False))
    return words


def _ps_pieces(w) -> tuple:
    """(items, goes_on): the items a PowerShell word holds when its commas, written outside quotes, are the array
    operator (`'-c','rm x'` is two), and whether the word ends in one (the list goes on in the next word)."""
    t, cm = w.t, w.commas
    if not cm:
        return [t], False
    out, start = [], 0
    for k in cm:
        out.append(t[start:k])
        start = k + 1
    out.append(t[start:])
    return [x for x in out if x], cm[-1] == len(t) - 1


def _ps_list(a: list, i: int, c: _C | None = None, first=None) -> tuple:
    """The array a PowerShell parameter takes from a[i]: `'x', 'y z'` (a word ending in a comma goes on in the next),
    `'x','y'` or `@('x','y z')`. (items as (text, dyn), index after it.) first: the pieces of an option word that holds
    the start of the list after its colon (`-ArgumentList:'a','b'`) and whether it goes on. A13/A16: only the first word
    was taken, so the -Command of `Start-Process powershell -ArgumentList '-NoProfile', '-Command', 'Remove-Item x'` was
    never read."""
    items, n = [], len(a)
    if first is not None:
        pieces, goes_on, dyn = first
        items.extend((x, dyn) for x in pieces)
        if not goes_on:
            return items, i
    while i < n:
        w = a[i]
        i += 1
        if w.t == "@\x00" and w.subs:
            if c is not None and c.spend(len(w.subs[0])):          # the array's text is lexed again here: charged (A15b)
                return [], len(a)
            for sg in _Lex(w.subs[0], True).run():
                for x in sg.words:
                    items.extend((y, x.dyn) for y in _ps_pieces(x)[0])
            break
        pieces, goes_on = _ps_pieces(w)
        items.extend((x, w.dyn) for x in pieces)
        if not goes_on and not (c is not None and not c.ps and w.t.endswith(",")):   # a bash lexer marks no commas
            break
    return items, i


# a PowerShell parameter written with its value after a colon: `-ArgumentList:'a'` (close1 F1)
_PS_PARAM_COLON = re.compile(r"-[A-Za-z][A-Za-z0-9_]*+:")
# programs that split their own command line by POSIX quoting, not by the Windows rules (close1 F3)
_SP_POSIX_ARGV = SHELLS | {"wsl"}


@rule("start-process", "saps")
def h_startproc(p, a, c):
    """Start-Process FILE -ArgumentList ARGS: the acts of FILE run with ARGS. The program is RUN, so a variable there
    is opaque (A13: `$git = ...; Start-Process $git -ArgumentList 'push origin main'` named nothing), and so is a program
    computed in parentheses (E3: `Start-Process (Get-Command git).Source`; see _exec1). E1: the arguments are what the
    program gets: Start-Process joins an -ArgumentList array with single spaces (documented) and the program splits that
    one line by the Windows rules (_win_argv), so `'push origin main', '--force'` is `git push origin main --force`."""
    fw, items, posw = None, None, []
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t
        i += 1
        # `-ArgumentList:'a','b'` is a parameter with its value (the word is quoted in part). close1 F1: a QUOTED string
        # is never a parameter, so a quoted word is one only when it has that shape, `-Name:` and a name Start-Process
        # takes; `'-C C:\repo push origin main'` (a space before its colon) is the positional -ArgumentList, and was
        # dropped as an unknown parameter, naming nothing
        if not t.startswith("-") or w.q and not _PS_PARAM_COLON.match(t):
            posw.append(w)
            continue
        name, colon, _ = t[1:].lower().partition(":")
        key = "argumentlist" if name in ("args", "arg") else \
            next((v for v in _PS_SP_VALS if len(name) >= 3 and v.startswith(name)), None)
        if key is None:
            if w.q:
                posw.append(w)                               # not a Start-Process parameter: a quoted value (F1)
            continue
        if key == "argumentlist":
            if colon:
                pieces, goes_on = _ps_pieces(Word(t.partition(":")[2], w.q, w.dyn, [], False,
                                                  [k - len(t.partition(":")[0]) - 1 for k in (w.commas or [])
                                                   if k > len(t.partition(":")[0])] or None))
                items, i = _ps_list(a, i, c, (pieces, goes_on, w.dyn))
            else:
                items, i = _ps_list(a, i, c)
        elif colon or i < n:
            vw = Word(t.partition(":")[2], w.q, w.dyn, [], False) if colon else a[i]
            i += 0 if colon else 1
            if key == "filepath":
                fw = vw
    fw = fw or (posw[0] if posw else None)
    if items is None and len(posw) > 1:
        items = [(x, w.dyn) for w in posw[1:] for x in _ps_pieces(w)[0]]
    if fw is None or not fw.t:
        return set()
    if not c.ps and items:
        # read in a bash dialect (the Bash tool, `bash -c "Start-Process ..."`), the lexer marks no PowerShell array
        # commas, so a comma in an item is taken as the array operator, as before (no reading 3e5e2ac had is lost)
        items = [(x, d) for t, d in items for x in t.split(",") if x]
    if items and c.spend(sum(len(x) + 1 for x, _d in items)):
        return set(ALL)                                      # the joined line is split again here: charged (A15b)
    found = c.run([Word(fw.t, False, False, [], False)] + _win_argv(items or []))
    if items and len(found) < len(ALL) and _prog(fw.t) in _SP_POSIX_ARGV and any("'" in x for x, _d in items):
        # close1 F3: a POSIX shell built for Windows (Git for Windows / MSYS bash) and wsl split their own command line
        # and keep a single-quoted run whole, which the Windows rules do not: `Start-Process bash -ArgumentList '-c',
        # "'git push origin main'"` runs `git push origin main`. Both readings are taken (the union; neither is dropped)
        found |= c.read(" ".join([_prog(fw.t)] + [x for x, _d in items]), False, any(d for _x, d in items))
    return found


_ICM_VALS = ("computername", "session", "credential", "argumentlist", "port", "configurationname", "name",
             "throttlelimit", "hostname", "username", "keyfilepath", "sessionoption", "applicationname", "uri",
             "certificatethumbprint", "authentication", "jobname", "inputobject", "filepath", "literalpath",
             "workingdirectory", "psversion", "definitionname", "definitionpath", "type", "streaminghost",
             "containerid", "vmid", "vmname", "subsystem", "connectionuri", "options", "sshconnection")
# the parameters whose value is a script block that RUNS (a value or a computed block there is a program run at run time)
_BLOCK_PARAMS = ("scriptblock", "initializationscript", "process", "begin", "end", "remainingscripts", "filterscript",
                 "parallel", "expression")


def _computed_block(t: str) -> bool:
    """A script block given as a value, not written here: `$sb`, `$(...)`, a PowerShell (expr) (E3)."""
    return _opaque_program(t) or t[:1] == "\x00"


@rule("invoke-command", "icm", "start-job", "start-threadjob", "foreach-object", "%", "where-object", "?",
      "measure-command")
def h_icm(p, a, c):
    """The script block that Invoke-Command, Start-Job, Start-ThreadJob, ForEach-Object, Where-Object or Measure-Command
    RUNS is read where it is written ({ ... }, in _read). One that is HELD in a value or made from text is a program run
    at run time: opaque (A13). E3: every way it can be handed over counts, by name (`-ScriptBlock $sb`,
    `-InitializationScript $i`, `-Process $p`) or by POSITION (`Invoke-Command $sb`, `icm web01 $deployBlock`,
    `Start-ThreadJob $work`, `ForEach-Object $sb`), unless a block is written in the call, which is then the one that
    runs (`Invoke-Command $session { Get-Date }`: the variable is the session) or the code is a file (-FilePath). Only
    the positions a block can take are read: the first two of Invoke-Command (computer, block), the first of the rest
    (`Where-Object Name -eq $x` compares to a value). `& $sb`, `. $sb` and `$sb.Invoke()` are read in _exec1 and
    _dot_source. A stated limit: cmdlets that keep a block to run later (Register-ObjectEvent -Action) are not read."""
    written = any(w.t[:1] == "\x01" for w in a)           # a { } block in the call: it is the one that runs
    by_file, positional = False, []
    i, n = 0, len(a)
    while i < n:
        w = a[i]
        t = w.t.lower()
        i += 1
        if not w.q and t.startswith("-"):
            name, colon, _ = t[1:].partition(":")
            if len(name) >= 2 and any(b.startswith(name) for b in _BLOCK_PARAMS) and \
                    not (p in ("foreach-object", "%") and "membername".startswith(name)):
                v = w.t.partition(":")[2] if colon else (a[i].t if i < n else "")
                i += 0 if colon else 1
                if _computed_block(v) or "[scriptblock]" in v.lower():
                    return set(ALL)
            elif len(name) >= 2 and any(x.startswith(name) for x in _ICM_VALS + ("membername",)):
                if "filepath".startswith(name) or "literalpath".startswith(name):
                    v = w.t.partition(":")[2] if colon else (a[i].t if i < n else "")
                    if _computed_block(v):
                        return set(ALL)                      # a script whose path is held in a value is run (A13)
                    by_file = True
                i += 0 if colon else 1
        else:
            positional.append(w)
    if p == "start-job" and any(_opaque_program(w.t) for w in positional):
        return set(ALL)                                      # Start-Job's block by position, as r5 read it (any position)
    if written or by_file:
        return set()
    upto = 2 if p in ("invoke-command", "icm") else 1
    if any(not w.q and _computed_block(w.t) for w in positional[:upto]):
        return set(ALL)                                      # a block by position: Invoke-Command $sb, Start-Job $sb
    return set()


@rule("nc", "ncat", "netcat", "socat", "telnet")
def h_nc(p, a, c):
    fl = _flags(a)
    if {"-l", "-z", "-lk", "-lp", "-listen"} & fl or _cluster(a, "l") or _cluster(a, "z"):
        return set()
    return {"send"} if _pos(a) else set()


@rule("sendmail", "send-mailmessage", "mail", "mailx", "msmtp", "mutt", "neomutt", "swaks", "ssmtp", "mpack", "wall",
      "msg", "telegram-send", "matrix-commander", "apprise", "slack", "slack-cli", "slackcat", "write", "mailsend",
      "s-nail", "exim", "postfix", "twilio", "signal-cli", "ntfy", "croc", "wormhole", "magic-wormhole",
      "dropbox-uploader")
def h_send(p, a, c):
    pl = _pos(a)
    s0 = pl[0] if pl else ""
    if p == "twilio":
        if any(":messages:create" in t or ":calls:create" in t or t.endswith(":send") for t in pl):
            return {"send"}
        return {"pay"} if any("phone-numbers:buy" in t for t in pl) else set()
    if p in ("mail", "mailx", "mutt", "neomutt", "s-nail") and not (_flags(a) & {"-s", "-a", "-r", "-c", "-b", "-t"}) \
            and not any("@" in x.t for x in a):
        return set()
    if p in ("signal-cli", "ntfy") and s0 not in ("send", "publish", "pub", "post") and p == "ntfy" and pl[:1] != []:
        if p == "ntfy" and s0 in ("subscribe", "sub"):
            return set()
        if p == "signal-cli" and "send" not in pl:
            return set()
    if p in ("croc", "wormhole", "magic-wormhole", "dropbox-uploader"):
        if s0 in ("send", "upload"):
            return {"send"}
        return {"download"} if s0 in ("receive", "download") or p == "croc" and s0 else set()
    if p == "slack" or p == "slack-cli":
        if {"auth", "login", "version", "help"} & set(pl[:1]):
            return set()
    return {"send"}


@rule("stripe")
def h_stripe(p, a, c):
    pl = _pos(a, {"--api-key", "-d", "--data", "--project-name", "--config", "--device-name", "--log-level", "-c",
                  "--expand", "-e"})
    r0, r1 = (pl[0] if pl else ""), (pl[1] if len(pl) > 1 else "")
    found = set()
    pay = {"charges": {"create", "capture"}, "payment_intents": {"create", "confirm", "capture"},
           "payouts": {"create"}, "transfers": {"create"}, "refunds": {"create"}, "invoices": {"pay"},
           "subscriptions": {"create"}, "topups": {"create"}, "payment_links": {"create"}}
    if r1 in pay.get(r0, ()) or r0 == "checkout" and r1 == "sessions" and "create" in pl:
        found.add("pay")
    if "delete" in pl[:3] or "cancel" in pl[:3] and r0 in ("subscriptions",):
        found.add("delete")
    if r0 == "post":                                       # the raw request: `stripe post /v1/refunds -d charge=ch_1`
        found.add("pay" if _STRIPE_PAY.search(r1) else "send")
    elif r0 == "invoices" and r1 == "send":
        found.add("send")                                  # emails the invoice (A7)
    return found


_STRIPE_PAY = re.compile(r"/v\d/(?:charges|payment_intents|payouts|transfers|refunds|topups|subscriptions|"
                         r"payment_links|checkout/sessions|invoices/[^/]++/pay|setup_intents|credit_notes|"
                         r"issuing/authorizations)|/(?:confirm|capture|pay)\b", re.I)


CRYPTO = {"bitcoin-cli": {"sendtoaddress", "sendmany", "send", "sendall", "sendrawtransaction"},
          "litecoin-cli": {"sendtoaddress", "sendmany"}, "dogecoin-cli": {"sendtoaddress", "sendmany"},
          "lncli": {"payinvoice", "sendpayment", "sendcoins", "sendmany"},
          "lightning-cli": {"pay", "keysend", "withdraw"}, "cast": {"send"}, "solana": {"transfer"},
          "near": {"send"}, "monero-wallet-cli": {"transfer"}, "paypal-cli": {"pay", "send", "payout", "transfer"},
          "venmo": {"pay", "send"}, "square-cli": {"pay", "charge"}}


@rule(*CRYPTO)
def h_crypto(p, a, c):
    return {"pay"} if CRYPTO[p] & set(_pos(a, {"-rpcwallet", "--rpc-url", "--private-key", "-k"})[:3]) else set()


@rule("yt-dlp", "youtube-dl", "gallery-dl", "you-get", "lux", "aria2c", "axel", "save-module", "save-package",
      "httrack", "certutil", "bitsadmin")
def h_dl(p, a, c):
    low = {x.t.lower() for x in a if not x.q}
    if p == "certutil":
        return {"download"} if "-urlcache" in low or "-verifyctl" in low else set()
    if p == "bitsadmin":
        return {"download"} if "/transfer" in low or "/addfile" in low else set()
    return {"download"}


_GRPC_DEL = re.compile(r"/(?:delete|remove|destroy|purge)\w*+$")
_GRPC_SEND = re.compile(r"/(?:send|publish)\w*+$")


@rule("grpcurl")
def h_grpc(p, a, c):
    found = set()
    for x in a:
        if _GRPC_DEL.search(x.t.lower()):
            found.add("delete")
        elif _GRPC_SEND.search(x.t.lower()):
            found.add("send")
    return found


# ---- fly, heroku, wrangler, vercel, netlify, firebase -------------------------------------------------------

@rule("fly", "flyctl")
def h_fly(p, a, c):
    pl = _pos(a, {"-a", "--app", "-c", "--config", "-r", "--region", "-C", "--command", "-s"})
    found = set()
    if pl[:1] in (["deploy"], ["launch"]):
        found.add("publish")
    if DEL_TOK & set(pl[:3]):
        found.add("delete")
    if pl[:2] == ["ssh", "console"] or pl[:1] == ["ssh"]:
        for k, w in enumerate(a):
            if w.t in ("-C", "--command") and k + 1 < len(a):
                found |= c.read(a[k + 1].t, False)
            elif w.t.startswith("--command="):
                found |= c.read(w.t[10:], False)
        if pl[:3] == ["ssh", "sftp", "get"]:
            found.add("download")
        elif pl[:3] == ["ssh", "sftp", "put"]:
            found.add("send")
    return found


@rule("heroku")
def h_heroku(p, a, c):
    vals = {"-a", "--app", "-r", "--remote", "-s", "--size", "-e", "--env", "-x", "--exit-code"}
    pl = _pos(a, vals)
    found = _colon(pl)
    if pl[:1] == ["push"]:
        found.add("publish")                                  # the old `heroku push`
    if pl[:1] == ["run"] and len(pl) > 1:
        # heroku's own flags may stand anywhere, the command's too: `run bash -c "rm -rf x" -a app` keeps the -c (A6)
        hflags = {"-a", "--app", "-r", "--remote", "-s", "--size", "-e", "--env", "--type", "-x"}
        inner, i, seen = [], 0, False
        while i < len(a):
            w = a[i]
            i += 1
            if not seen:
                if not _isopt(w):
                    seen = w.t.lower() == "run"
                    continue
                if w.t in vals:
                    i += 1
                continue
            if not w.q and (w.t in hflags and w.t != "-x" or w.t.startswith(("--app=", "--remote=", "--size="))):
                i += 0 if "=" in w.t else 1
            elif not w.q and w.t in ("-x", "--exit-code", "--no-tty", "--no-notify", "--"):
                pass
            else:
                inner.append(w)
        found |= c.run(inner)
    if pl[:1] == ["pg:psql"]:
        for k, w in enumerate(a):
            if not w.q and w.t in ("-c", "--command") and k + 1 < len(a):
                found |= _sql(a[k + 1].t, "psql", c.work)
    if DEL_TOK & set(pl[:2]):
        found.add("delete")
    if pl[:1] == ["releases:rollback"]:
        found.add("publish")
    return found


@rule("wrangler")
def h_wrangler(p, a, c):
    pl = _pos(a, {"--name", "--env", "-e", "--project-name", "--binding", "--config", "-c", "--file", "--command",
                  "--branch", "--namespace-id"})
    found = set()
    s0 = pl[0] if pl else ""
    toks = set(pl[:5])
    if s0 in ("deploy", "publish"):
        found.add("publish")
    if s0 == "pages" and toks & {"deploy", "publish"}:
        found.add("publish")
    if DEL_TOK & toks:
        found.add("delete")
    if s0 == "r2" and "put" in toks:
        found |= {"publish", "push"}
    if s0 == "r2" and "get" in toks:
        found.add("download")
    for k, w in enumerate(a):
        if w.t in ("--command", "--file") and k + 1 < len(a):
            found |= _sql(a[k + 1].t, "wrangler", c.work)
        elif w.t.startswith("--command="):
            found |= _sql(w.t[10:], "wrangler", c.work)
    return found


@rule("vercel", "vc")
def h_vercel(p, a, c):
    pl = _pos(a, {"--token", "-t", "--scope", "-S", "--cwd", "--env", "-e", "--build-env", "-b", "--meta", "-m",
                  "--regions", "--name", "-n", "--local-config", "-A"})
    s0, s1 = (pl[0] if pl else ""), (pl[1] if len(pl) > 1 else "")
    fl = _flags(a)
    found = set()
    quiet = {"ls", "list", "logs", "whoami", "inspect", "dev", "link", "login", "logout", "build", "projects",
             "help", "switch", "teams", "certs", "dns", "secrets", "bisect", "init", "open", "git", "telemetry",
             "curl", "pull", "env", "domains", "alias", "rollback", "promote", "remove", "rm", "redeploy"}
    if s0 in ("remove", "rm"):
        found.add("delete")
    elif s0 == "env" and s1 in ("rm", "remove"):
        found.add("delete")
    elif s0 == "domains" and s1 in ("buy", "transfer-in"):
        found.add("pay")
    elif s0 in ("promote", "rollback", "redeploy", "deploy") or s0 == "alias" and s1 in ("set", "rm"):
        found.add("publish")
    elif s0 not in quiet and "--version" not in fl:
        found.add("publish")
    if s0 == "env" and s1 == "pull" or s0 == "pull":
        found.add("download")
    return found


@rule("netlify", "firebase")
def h_netfire(p, a, c):
    pl = _pos(a, {"--dir", "-d", "--site", "-s", "--message", "-m", "--only", "--project", "-P", "--token",
                  "--alias", "--functions", "-f"})
    found = _colon(pl)
    toks = set(pl[:3])
    if "deploy" in toks:
        found.add("publish")
    if DEL_TOK & toks:
        found.add("delete")
    if p == "firebase" and "hosting:disable" in toks:
        found |= {"delete"}
    return found


@rule("crontab")
def h_crontab(p, a, c):
    return {"delete"} if "-r" in _flags(a) else set()


@rule("reg", "schtasks", "sc", "sc.exe", "net", "vssadmin", "cipher", "wmic", "forfiles", "diskutil", "dd", "tmutil",
      "defaults", "security", "journalctl", "format", "diskpart", "zpool", "zfs", "btrfs")
def h_system(p, a, c):
    low = {x.t.lower() for x in a if not x.q}
    pl = _pos(a)
    found = set()
    if p in ("reg", "sc", "sc.exe", "defaults", "tmutil") and "delete" in low:
        found.add("delete")
    elif p == "schtasks" and "/delete" in low:
        found.add("delete")
    elif p == "net" and "/delete" in low:
        found.add("delete")
    elif p == "vssadmin" and "delete" in low:
        found.add("delete")
    elif p == "cipher" and any(x.startswith("/w") for x in low):
        found.add("delete")
    elif p == "wmic" and "uninstall" in low:
        found.add("delete")
    elif p == "forfiles":
        for k, w in enumerate(a):
            if w.t.lower() == "/c" and k + 1 < len(a):
                found |= c.read(a[k + 1].t, True, a[k + 1].dyn)
    elif p == "diskutil" and pl and pl[0].lower().startswith(("erase", "securee", "partitiondisk", "reformat")):
        found.add("delete")
    elif p == "dd" and any(x.t.startswith("of=/dev/") for x in a):
        found.add("delete")
    elif p == "security" and pl and pl[0].startswith("delete-"):
        found.add("delete")
    elif p == "journalctl" and any(x.startswith("--vacuum") for x in low):
        found.add("delete")
    elif p == "format" and pl:
        found.add("delete")
    elif p == "diskpart" and "clean" in low:
        found.add("delete")
    elif p in ("zpool", "zfs") and "destroy" in low:
        found.add("delete")
    elif p == "btrfs" and "delete" in low:
        found.add("delete")
    return found


@rule("make", "gmake", "ninja", "nmake")
def h_make(p, a, c):
    return {"delete"} if {"clean", "distclean", "mrproper", "veryclean"} & {x.t.lower() for x in a if not x.q} \
        else set()


@rule("for")
def h_for(p, a, c):
    for k, w in enumerate(a):
        if not w.q and w.t.lower() == "do":
            return c.run(a[k + 1:])
    return set()


# ---- round 2b: commands that carry a command, and tools the corpus found missing ---------------------------------

@rule("nix-shell", "nix")
def h_nix(p, a, c):
    """nix-shell --run 'cmd' / --command 'cmd'; nix develop|shell|run -c cmd args; nix profile install, nix-env -i."""
    found: set = set()
    pl = _pos(a)
    if p == "nix-shell":
        for k, w in enumerate(a):
            if not w.q and w.t in ("--run", "--command") and k + 1 < len(a):
                found |= c.read(a[k + 1].t, False)
        return found
    s0, s1 = (pl[0] if pl else ""), (pl[1] if len(pl) > 1 else "")
    if s0 == "profile" and s1 in ("install", "upgrade"):
        found.add("download")
    if s0 in ("develop", "shell", "run"):
        for k, w in enumerate(a):
            if not w.q and w.t in ("-c", "--command") and k + 1 < len(a):
                found |= c.run(a[k + 1:])
                break
    return found


@rule("nix-env")
def h_nixenv(p, a, c):
    low = {x.t for x in a if not x.q}
    if "-e" in low or "--uninstall" in low:
        return {"delete"}
    if any(t.startswith("-") and not t.startswith("--") and ("i" in t or "u" in t) for t in low) or \
            {"--install", "--upgrade"} & low:
        return {"download"}
    return set()


@rule("playwright", "cypress", "puppeteer")
def h_browser_tools(p, a, c):
    """`playwright install [--with-deps]`, `playwright install-deps`, `cypress install`, `puppeteer browsers install`
    fetch browsers (A6: `npx playwright install` was named by the base and lost when playwright went into LOCAL_NPX)."""
    pl = _pos(a, {"-p", "--project"})
    if any(t in ("install", "install-deps") for t in pl[:3]):
        return {"download"}
    return set()


@rule("code", "code-insiders", "codium", "cursor")
def h_editor(p, a, c):
    """An editor is inert, except `code --install-extension x` (a download) and `--uninstall-extension`."""
    low = {x.t.lower().split("=", 1)[0] for x in a if not x.q}
    found: set = set()
    if "--install-extension" in low:
        found.add("download")
    if "--uninstall-extension" in low:
        found.add("delete")
    return found


@rule("trap")
def h_trap(p, a, c):
    """`trap 'rm -rf "$TMP"' EXIT`: the handler is a command text that runs at exit (A10)."""
    if not a or a[0].t in ("-", "-p", "-l", "--"):
        return set()
    return c.read(a[0].t, False)


@rule("tmux", "screen")
def h_tmux(p, a, c):
    """Text typed or started in a terminal multiplexer: `tmux send-keys 'git push' Enter`, `tmux new-session 'cmd'`,
    `screen -X stuff 'cmd'`. A quoted word holding a space is read as a command line."""
    found: set = set()
    pl = _pos(a)
    if p == "screen" and "stuff" not in pl:
        return found
    if p == "tmux" and not ({"send-keys", "send", "new-session", "new", "new-window", "neww", "split-window",
                              "splitw", "run-shell", "run", "respawn-pane", "respawn-window"} & set(pl[:3])):
        return found
    for w in a:
        if w.q and (" " in w.t or "\t" in w.t) and not w.t.startswith("-"):
            found |= c.read(w.t.replace("\\n", "\n"), False)
    return found


@rule("script")
def h_script(p, a, c):
    """script -q -c 'cmd' /dev/null"""
    for k, w in enumerate(a):
        if not w.q and w.t in ("-c", "--command") and k + 1 < len(a):
            return c.read(a[k + 1].t, False)
        if not w.q and w.t.startswith("--command="):
            return c.read(w.t.split("=", 1)[1], False)
    return set()


@rule("ansible", "ansible-console")
def h_ansible(p, a, c):
    """ansible HOSTS -m shell|command|raw -a 'cmd': the module argument is a command line run on the hosts."""
    mod, arg = "command", None
    for k, w in enumerate(a):
        if w.q:
            continue
        if w.t in ("-m", "--module-name") and k + 1 < len(a):
            mod = a[k + 1].t.lower()
        elif w.t in ("-a", "--args") and k + 1 < len(a):
            arg = a[k + 1].t
    if arg is not None and mod in ("shell", "command", "raw", "script", "ansible.builtin.shell",
                                   "ansible.builtin.command", "ansible.builtin.raw"):
        return c.read(arg, False)
    return set()


@rule("pssh", "parallel-ssh", "pdsh", "clush", "salt", "salt-ssh")
def h_multissh(p, a, c):
    """pssh -h hosts 'cmd'; pdsh -w h 'cmd'; clush -w h 'cmd'; salt '*' cmd.run 'cmd': the command line is read."""
    if p in ("salt", "salt-ssh"):
        for k, w in enumerate(a):
            if w.t in ("cmd.run", "cmd.run_all", "cmd.script", "cmd.shell") and k + 1 < len(a):
                return c.read(" ".join(x.t for x in a[k + 1:]), False)
        return set()
    vals = {"-h", "-H", "-l", "-p", "-o", "-e", "-t", "-O", "-x", "-X", "-w", "-g", "-b", "-u", "-f", "--hosts"}
    j = _first_cmd(a, vals)
    rest = a[j:]
    return c.read(rest[0].t if len(rest) == 1 else " ".join(x.t for x in rest), False) if rest else set()


@rule("rake")
def h_rake(p, a, c):
    return h_infra("rails", a, c)


@rule("sl", "gt", "graphite")
def h_sl(p, a, c):
    """Sapling `sl push`, Graphite `gt submit`: push and publish a stack."""
    pl = _pos(a)
    s0 = pl[0] if pl else ""
    if p == "sl":
        return {"push"} if s0 in ("push", "pr") else ({"download"} if s0 in ("pull", "clone") else set())
    return {"push", "publish"} if s0 in ("submit", "ss", "stack") and (s0 != "stack" or "submit" in pl) else set()


@rule("jsr", "deployctl")
def h_jsr(p, a, c):
    pl = _pos(a)
    s0 = pl[0] if pl else ""
    if p == "deployctl":
        return {"publish"} if s0 == "deploy" else set()
    return {"publish"} if s0 == "publish" else ({"download"} if s0 in ("add", "install") else set())


# Tools that fetch, remove or ship by subcommand and name no flag worth reading: (download, delete, publish) verbs.
# Each row was a miss of the 1,830-command corpus; a tool not in a table is a stated limit.
VERBS = {
    "snap": ({"install", "refresh", "download"}, {"remove"}, set()),
    "flatpak": ({"install", "update"}, {"uninstall"}, set()),
    "vcpkg": ({"install", "upgrade"}, {"remove"}, set()),
    "opam": ({"install", "update", "upgrade"}, {"remove", "uninstall"}, set()),
    "luarocks": ({"install", "download"}, {"remove"}, {"upload"}),
    "cpanm": ({"*"}, set(), set()), "cpan": ({"*"}, set(), set()),
    "nvm": ({"install"}, {"uninstall"}, set()), "pyenv": ({"install"}, {"uninstall"}, set()),
    "rbenv": ({"install"}, {"uninstall"}, set()), "nodenv": ({"install"}, {"uninstall"}, set()),
    "rustup": ({"install", "update", "default"}, {"uninstall"}, set()),
    "sdk": ({"install", "update", "upgrade"}, {"uninstall", "rm", "remove"}, set()),
    "volta": ({"install", "fetch"}, {"uninstall"}, set()), "fnm": ({"install"}, {"uninstall"}, set()),
    "mise": ({"install", "use", "upgrade"}, {"uninstall", "rm", "remove"}, set()),
    "asdf": ({"install", "update"}, {"uninstall"}, set()),
    "ipfs": ({"get"}, {"rm"}, {"add"}), "eas": (set(), set(), {"submit", "update"}),
    "skaffold": (set(), {"delete"}, {"run", "deploy", "apply"}),
    "liquibase": (set(), {"dropall", "drop-all"}, {"update"}), "azcopy": (set(), {"remove", "rm"}, set()),
}


def _verbs(p: str, a: list) -> set:
    dl, de, pu = VERBS[p]
    pl = _pos(a)
    found: set = set()
    if "*" in dl and pl:
        found.add("download")
    toks = set(pl[:3])
    if dl & toks:
        found.add("download")
    if de & toks:
        found.add("delete")
    if pu & toks:
        found.add("publish")
    if p == "rustup" and pl[:1] in (["target"], ["component"], ["toolchain"]) and pl[1:2] in (["add"], ["install"]):
        found.add("download")                                # `rustup target add x` fetches; `rustup toolchain list` does not
    if p == "azcopy":
        if pl[:1] in (["copy"], ["cp"], ["sync"]):
            tail = [w.t for w in _posw(a)][1:]
            if len(tail) > 1 and "://" in tail[1]:
                found |= {"send", "publish"}
            elif tail and "://" in tail[0]:
                found.add("download")
    return found


@rule(*sorted(set(VERBS) - {"volta", "fnm", "mise", "asdf"}))
def h_verbs(p, a, c):
    return _verbs(p, a)


@rule("nomad", "argocd", "k3d", "eksctl", "multipass", "neonctl", "kops", "talosctl", "rancher", "ibmcloud", "scw",
      "civo", "vultr-cli", "oci", "upctl", "exo", "mgc")
def h_clusters(p, a, c):
    """Cluster and cloud CLIs whose deleting verb is the subcommand's name; a few ship (nomad job run, argocd app sync)."""
    pl = _pos(a)
    toks = set(pl[:4])
    found: set = set()
    if p == "nomad":
        if toks & {"stop", "purge"} and pl[:1] == ["job"]:
            found.add("delete")
        elif pl[:2] == ["job", "run"]:
            found.add("publish")
        return found
    if p == "argocd":
        if pl[:1] == ["app"] and toks & {"sync", "create", "set", "rollback"}:
            found.add("publish")
        if toks & DEL_TOK:
            found.add("delete")
        return found
    if p == "mgc":
        return {"send"} if any(t.startswith("send") for t in pl) else set()
    if DEL_TOK & toks:
        found.add("delete")
    if p == "eksctl" and "create" in toks:
        found.add("publish")
    return found


@rule("mongorestore", "pg_restore")
def h_restore(p, a, c):
    """mongorestore --drop and pg_restore --clean drop what they restore over."""
    low = {x.t for x in a if not x.q}
    if p == "mongorestore":
        return {"delete"} if "--drop" in low else set()
    return {"delete"} if {"--clean", "-c"} & low else set()


@rule("forge")
def h_forge(p, a, c):
    """forge script ... --broadcast sends signed transactions: money moves and a contract is deployed."""
    low = {x.t.lower() for x in a if not x.q}
    if "--broadcast" in low:
        return {"pay", "publish"}
    return {"publish"} if _pos(a)[:1] == ["create"] else set()


@rule("toot")
def h_toot(p, a, c):
    pl = _pos(a)
    return {"publish", "send"} if pl[:1] == ["post"] else set()


@rule("awk", "gawk", "mawk", "nawk")
def h_awk(p, a, c):
    """awk is inert except for what its program runs: system("rm -rf x"), "cmd" | getline, print | "cmd" (A10)."""
    found: set = set()
    for x in a:
        if "system" in x.t:
            found |= c.code(x.t)
        if "|" in x.t:
            for m in _AWK_PIPE.finditer(x.t):
                found |= c.read(m.group(1) or m.group(2), False)
    return found


_AWK_PIPE = re.compile(r'\|\s*+"([^"]++)"|"([^"]++)"\s*+\|\s*+getline')


KNOWN =(frozenset(H) | frozenset(WRAP) | SHELLS | PS_SHELLS | INERT | ECHOES | NET_FETCH | SQL_CLIENTS |
         frozenset({"eval", "iex", "invoke-expression"}))

# E2: the tables r5 widened, whose valued options the third reading (_flag_words) takes as flags before the words that
# name the act (how many: aws's service and command, docker's command and image, kubectl's and helm's subcommand). The
# attacker's scan of every option newly valued, at every position, lost acts 99f9116 had named only on these.
_VALUED = {"aws": (AWS_VAL, 2), "docker": (CTR_VAL, 2), "podman": (CTR_VAL, 2), "nerdctl": (CTR_VAL, 2),
           "docker-compose": (CTR_VAL, 2), "kubectl": (KUBE_VAL, 1), "oc": (KUBE_VAL, 1), "k": (KUBE_VAL, 1),
           "helm": (HELM_VAL, 1)}


# ---------------------------------------------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------------------------------------------

def _shell_acts(cmd: str, ps: bool = False) -> set:
    if len(cmd) > MAX_COMMAND:                  # checked before any other work (Orithises: NFKC on 32 MiB took 4 s)
        return set(ORDER)                       # too long to read whole: only a hold can follow
    c = normal.nfkc(cmd)                        # linear: unicodedata's was quadratic (actclass r4 attack, finding 3)
    c = "".join(ch for ch in c if unicodedata.category(ch) != "Cf")
    if len(c) > MAX_COMMAND:
        return set(ORDER)
    # spent, budget, and a dict: answers kept for texts read twice, and whether the call assigns $EDITOR and kin
    work = [0, WORK_FACTOR * len(c) + WORK_SLACK, {"assigned": bool(_ENV_PROGRAM_SET.search(c))}]
    found = _read(c, ps, 0, work)
    # R5 (A15b): the budget pays for every text a reader is handed. A reading that spent past it is every act, whatever
    # the part that noticed was; a part of the answer is never returned from a reading that did not finish.
    return set(ORDER) if work[0] > work[1] else found


COMMAND_KEYS = ("command", "cmd", "script", "CommandLine", "commandLine", "command_line", "shell_command")
_PLAIN_ARG = re.compile(r"\A[A-Za-z0-9_@%+=:,./~^-]++\Z")


def _quote_arg(x: str) -> str:
    """One argv element as one shell word: left bare when it holds nothing a shell reads (so `-lc` stays an option),
    else in single quotes. A5: an argv list is NOT shell text; `["bash","-lc","git push"]` is a shell whose script
    is its third element, and `["echo","a; git push"]` is an echo."""
    if _PLAIN_ARG.match(x):
        return x
    return "'" + x.replace("'", "'\\''") + "'"


def _command(inp) -> str | None:
    if isinstance(inp, dict):
        for k in COMMAND_KEYS:
            v = inp.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, list):
                parts, size = [], 0
                for x in v:                         # bounded: past MAX_COMMAND the command is "too long" anyway
                    if not isinstance(x, str):
                        return None
                    parts.append(_quote_arg(x))
                    size += len(x) + 1
                    if size > MAX_COMMAND or len(parts) > MAX_COMMAND:
                        return "x" * (MAX_COMMAND + 1)
                return " ".join(parts)
    return None


def acts_of_call(name, inp) -> tuple:
    """The acts this call is, in reading.ACTS order; () when it cannot be told."""
    nm = name if isinstance(name, str) else ""
    cmd = _command(inp)
    found = set()
    if cmd is not None:
        found |= _shell_acts(cmd, nm.lower() in PS_NAMES)
    if cmd is None or nm.lower() not in SHELL_NAMES:
        found |= _name_acts(nm)
    return tuple(a for a in ORDER if a in found)
