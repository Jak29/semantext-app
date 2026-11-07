"""Which of the reader's acts a tool call is, where that can be told from the call alone.

Used by the decision to let the person's words HOLD a call (reading.py): a call this cannot classify gets no hold from
the words, and the space's gates and default decide it as before. So a miss here costs a hold the words asked for, and
never releases anything; a wrong class costs an extra ask at most.

r2 (Koinos's attack on the reader's wiring: its regexes were quadratic, 12 s on a 64 KiB command, and it held `git commit -m
'fix push bug'`): a shell command is cut into segments at ; & | and line ends, quoted text is dropped, and each
segment is read as a list of words, so the work is linear in the command and a word inside quotes is never an act.
A command longer than MAX_COMMAND is read up to there and counted as every material act (only a hold can follow).

Read for a shell call: the command string (a `command`, `cmd` or `script` field). For any other tool: its name.
Still missed, stated: a command built at run time (a variable, an alias, base64, a script file run by name), a tool
whose name says nothing, an act done by a program the command starts, and the long tail Koinos listed (cloud CLIs
beyond the ones below, language-level file and network calls).
"""
from __future__ import annotations

import re
import unicodedata

MAX_COMMAND = 64 * 1024
ORDER = ("publish", "push", "delete", "send", "pay", "download")

SHELL_NAMES = {"bash", "shell", "sh", "powershell", "pwsh", "cmd", "terminal", "run_command", "execute_command",
               "run_shell_command", "exec"}

# A quote opens only where a word does not continue into it: the apostrophe in "it's" opens nothing (Orithises).
QUOTED = re.compile(r"(?<![\w])'[^'\n]*'|(?<![\w])\"[^\"\n]*\"")
SUBST = re.compile(r"\$\(([^()\n]{0,4096})\)|`([^`\n]{0,4096})`")
HEREDOC = re.compile(r"<<-?[ \t]{0,8}['\"]?([A-Za-z_][A-Za-z0-9_]{0,63})['\"]?[^\n]{0,4096}\n")
SHELLS = {"sh", "bash", "zsh", "dash", "cmd", "pwsh", "powershell"}
SEGMENTS = re.compile(r"&&|\|\||[;&|\n]")
WORD = re.compile(r"[^\s()`{}]+")
SKIP_FIRST = {"sudo", "doas", "nohup", "time", "env", "exec", "command", "builtin", "call", "start", "&", "."}
ECHOES = {"echo", "printf", "write-host", "write-output", "man", "help", "get-help", "#", "rem", "::"}

NAME = {
    "send": re.compile(r"send|email|mail|message|slack|post_?message|reply|forward|notify|sms|tweet", re.I),
    "publish": re.compile(r"publish|deploy|release|upload|share|merge_pull|create_pull|post(?!gres)", re.I),
    "delete": re.compile(r"delete|remove|trash|destroy|purge|wipe|erase|drop|execute_sql", re.I),
    "pay": re.compile(r"pay|purchase|checkout|transfer|charge|buy|order", re.I),
    "download": re.compile(r"download|install|fetch_file", re.I),
    "push": re.compile(r"push", re.I),
}


def _prog(w: str) -> str:
    """A program word as its bare name: /bin/rm, \\rm, rm.exe, npm.cmd -> rm, npm."""
    w = w.lower().rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lstrip("\\")
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if w.endswith(ext):
            w = w[: -len(ext)]
    return w


ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
WRAPPED = re.compile(r"\b(?:sh|bash|zsh|dash|cmd|cmd\.exe|pwsh|powershell)\s+(?:-c|/c|/k|-command|-c?ommand)\s+"
                     r"(?:'([^'\n]*)'|\"([^\"\n]*)\")", re.I)


def _segment(words: list, depth: int = 0) -> set:
    """The acts one command segment is, from its words."""
    k = 0
    while k < len(words) and (_prog(words[k]) in SKIP_FIRST or ENV_ASSIGN.match(words[k])):
        k += 1
    words = words[k:]
    for n, w in enumerate(words):                 # a comment runs from a word that opens with # to the segment's end
        if w.startswith("#"):
            words = words[:n]
            break
    if depth < 3 and words:
        p0, low0 = _prog(words[0]), [w.lower() for w in words]
        inner = None
        if p0 in SHELLS and len(words) > 2 and low0[1] in ("-c", "/c", "/k", "-command"):
            inner = words[2:]                             # cmd /c echo download: the wrapped command, read as one
        elif p0 in ("xargs",):
            inner = [w for w in words[1:] if not w.startswith("-")]
        elif p0 == "find" and "-exec" in low0:
            inner = words[low0.index("-exec") + 1:]
        elif p0 in ("python", "python3", "py") and "-m" in low0:
            inner = words[low0.index("-m") + 1:]
        elif p0 in ("npx", "pnpx", "bunx", "uvx", "pipx") and len(words) > 1:
            inner = [w for w in words[1:] if not w.startswith("-")] if p0 != "pipx" or low0[1:2] == ["run"] else None
        if inner:
            got = _segment(inner, depth + 1)
            if p0 in ("npx", "pnpx", "bunx", "uvx"):
                got.add("download")
            if p0 not in ("find",) or got:
                return got | (_segment(words[:low0.index("-exec")], depth + 1) if p0 == "find" else set())
    if not words:
        return set()
    p = _prog(words[0])
    if p in ECHOES:
        return set()
    low = [w.lower() for w in words]
    rest = low[1:]
    s = set(rest)
    found = set()
    if p == "git":
        sub, skip = "", False
        for w in rest:                                    # git's own options; -C, -c and two others take a value
            if skip:
                skip = False
            elif w in ("-c", "--git-dir", "--work-tree", "--namespace"):
                skip = True
            elif not w.startswith("-") and "=" not in w:
                sub = w
                break
        if sub == "push":
            found.add("push")
            if {"--delete", "-d"} & s or any(w.startswith(":") for w in rest):
                found.add("delete")
        elif sub in ("clean", "rm") or (sub == "branch" and ({"-d", "-D".lower(), "--delete"} & s)) \
                or (sub == "reset" and "--hard" in s) or (sub == "stash" and {"drop", "clear"} & s) \
                or (sub == "restore") or (sub == "checkout" and "--" in s):
            found.add("delete")
        elif sub in ("clone", "fetch", "pull", "submodule"):
            found.add("download")
        elif sub == "send-email":
            found.add("send")
    elif p in ("rm", "rmdir", "rd", "del", "erase", "ri", "remove-item", "unlink", "shred", "rimraf", "trash",
               "clear-content", "set-content", "truncate"):
        found.add("delete")
    elif p == "find" and "-delete" in s:
        found.add("delete")
    elif p in ("docker", "podman"):
        if "push" in s or "--push" in s:
            found.add("push")
        if {"rm", "rmi", "prune"} & s:
            found.add("delete")
        if "pull" in s:
            found.add("download")
    elif p in ("npm", "pnpm", "yarn", "bun"):
        if "publish" in s:
            found.add("publish")
        if {"install", "i", "add", "ci", "dlx", "x"} & s or (p == "yarn" and len(rest) == 0):
            found.add("download")
    elif p in ("npx", "pipx", "bunx", "uvx"):
        found.add("download")
    elif p in ("pip", "pip3", "uv", "poetry", "conda", "mamba", "cargo", "gem", "go", "winget", "choco", "scoop",
               "apt", "apt-get", "brew", "dnf", "yum", "apk", "pacman", "install-module", "install-package"):
        if p.startswith("install-") or {"install", "add", "get", "i", "sync"} & s:
            found.add("download")
        if "publish" in s:
            found.add("publish")
    elif p in ("twine", "flit", "hatch"):
        if {"upload", "publish"} & s:
            found.add("publish")
    elif p == "gh":
        sub2 = " ".join(rest[:2])
        if rest[:1] == ["release"] or sub2 in ("repo create", "pr create", "pr merge", "gist create", "repo edit",
                                               "workflow run"):
            found.add("publish")
        if sub2 in ("issue comment", "pr comment", "issue create") or (rest[:1] == ["api"]
                                                                        and {"-x", "--method"} & s
                                                                        and {"post", "put", "patch", "delete"} & s):
            found.add("send")
        if rest[:1] == ["repo"] and "delete" in s:
            found.add("delete")
    elif p in ("curl", "wget", "invoke-webrequest", "iwr", "invoke-restmethod", "irm", "http", "https", "httpie"):
        methods = {"post", "put", "patch", "delete", "-method:post", "-method:put"}
        data = any(w in ("-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii", "-f",
                         "--form", "--json", "-t", "--upload-file", "-body", "-infile")
                   or w.startswith(("--post-data", "--post-file", "--body-data", "--method=post", "-xpost", "-xput",
                                    "-xpatch", "-xdelete"))
                   or (len(w) > 1 and w[0] == "-" and w[1] != "-" and w.endswith("d") and w[1:].isalpha())
                   for w in rest)
        if data or (methods & s) or any(w.startswith("-method:") and w != "-method:get" for w in rest):
            found.add("send")
        if (p == "wget" and not data) or "--output" in s or "--remote-name" in s or "-outfile" in s or \
                any(len(w) > 1 and w[0] == "-" and w[1] != "-" and "o" in w and w[1:].isalpha() for w in rest):
            found.add("download")
    elif p in ("scp", "rsync", "sftp", "send-mailmessage", "sendmail", "mail", "mailx"):
        found.add("send")
    elif p in ("kubectl", "helm", "terraform", "pulumi", "az", "aws", "gcloud", "gsutil", "sam", "cdk", "fly",
               "flyctl", "wrangler", "vercel", "netlify", "firebase", "heroku"):
        if {"send-email", "send-raw-email", "sns", "ses", "pubsub"} & s:
            found.add("send")
        elif {"apply", "deploy", "install", "upgrade", "up", "publish", "release", "cp", "sync", "push",
              "update-function-code", "deployment"} & s or p in ("vercel",):
            found.add("publish")
        if {"delete", "destroy", "rm", "uninstall", "remove"} & s:
            found.add("delete")
    elif p == "stripe":
        if {"create"} & s and {"charges", "payment_intents", "payouts", "transfers", "refunds"} & s:
            found.add("pay")
    elif p in ("psql", "mysql", "sqlite3", "sqlcmd"):
        pass
    if re.search(r"\b(?:drop\s+(?:table|database|schema)|truncate\s+table|delete\s+from)\b", " ".join(low)):
        found.add("delete")
    if "download" in s or (p in ("ollama", "podman", "docker") and "pull" in s):
        found.add("download")
    return found


def _shell_acts(cmd: str) -> set:
    if len(cmd) > MAX_COMMAND:                  # checked before any other work (Orithises: NFKC on 32 MiB took 4 s)
        return set(ORDER)                       # too long to read whole: only a hold can follow
    c = unicodedata.normalize("NFKC", cmd)
    c = "".join(ch for ch in c if unicodedata.category(ch) != "Cf")
    if len(c) > MAX_COMMAND:
        return set(ORDER)
    c = _drop_heredocs(_drop_herestrings(c))     # here-document and here-string bodies are data, not commands
    found = set()
    for m in SUBST.finditer(c):                 # $(...) and `...` run even inside an echo: read them as commands
        found |= _shell_inner(m.group(1) or m.group(2) or "")
    for m in WRAPPED.finditer(c):                 # the command a shell is handed in quotes: sh -c 'git push'
        found |= _shell_inner(m.group(1) or m.group(2) or "")
    c = QUOTED.sub(" ", c)
    for seg in SEGMENTS.split(c):
        found |= _segment(WORD.findall(seg))
    return found


def _drop_herestrings(c: str) -> str:
    """c with each PowerShell here-string body (@'...'@, @"..."@) removed; an unclosed one runs to the end. Linear."""
    out, i = [], 0
    while True:
        j = min((k for k in (c.find("@'\n", i), c.find("@\"\n", i)) if k >= 0), default=-1)
        if j < 0:
            out.append(c[i:])
            return "".join(out)
        out.append(c[i:j])
        close = "\n" + c[j + 1] + "@"
        k = c.find(close, j + 3)
        if k < 0:
            return "".join(out)
        i = k + len(close)


def _drop_heredocs(c: str) -> str:
    """c with each here-document body (<<EOF ... EOF) removed. Linear: one find for each body's end."""
    out, i = [], 0
    for m in HEREDOC.finditer(c):
        if m.start() < i:
            continue
        out.append(c[i:m.end()])
        tag = m.group(1)
        k = c.find("\n" + tag, m.end() - 1)
        i = len(c) if k < 0 else k + 1 + len(tag)
    out.append(c[i:])
    return "".join(out)


def _shell_inner(cmd: str) -> set:
    found = set()
    for seg in SEGMENTS.split(QUOTED.sub(" ", cmd)):
        found |= _segment(WORD.findall(seg), 1)
    return found


def _command(inp) -> str | None:
    if isinstance(inp, dict):
        for k in ("command", "cmd", "script"):
            v = inp.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, list):
                parts, size = [], 0
                for x in v:                         # bounded: past MAX_COMMAND the command is "too long" anyway
                    if not isinstance(x, str):
                        return None
                    parts.append(x)
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
        found |= _shell_acts(cmd)
    if cmd is None or nm.lower() not in SHELL_NAMES:
        found |= {a for a, rx in NAME.items() if rx.search(nm[:256])}
    return tuple(a for a in ORDER if a in found)
