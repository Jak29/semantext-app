"""Which files a change card may cite as evidence: the one question change.py leaves to a policy.

change.py keeps every check that is about HOW a file is read: a full plain path, inside a root, no link or junction at
any level below it, no hard link, no alternate stream, no device or short (8.3) name, a plain file under the size cap,
its real path inside the root's real path, one checked read-only handle, the 50-file cap, the read budget and the 60 s
cache. What it does not decide is WHICH files are evidence at all. That is a policy:

    roots()                         the folders reading may start from; change.py walks down from one of them, so a
                                    policy with no roots reads nothing (roots are required, there is no default)
    refuse(path, real, root, budget) why this file is not evidence, or None when it is. It is asked only after every
                                    check above has passed for the file, with `real` its resolved path; `budget` is the
                                    build's shared read budget ({"left": bytes}), for a policy that reads to decide

A file a policy refuses is "unknown" on its card, never "current". A way of choosing evidence is one small module that
builds a Policy for a seat (`for_seat(seat, got, roots)`, where got is the readers' answers and roots the filing agent's
home and bound projects as the page knows them); WAYS names each way's module and DEFAULT_WAY the one the page uses
(view.py imports it), and change.py never changes for a new one. The base Policy admits nothing.

The public interface (semantext.api.fingerprint) takes the filing agent's roots as a list, as it did before the
policies: a list is read through the page's way (`from_roots`), so a filer that passes its home and projects computes
the digest the page computes. A list is never read with no policy: an untracked file under git-index stays "unknown".

The name lists below are what decided evidence before the policies (change.py at 1.2.2). A name loses to the next name
(an audit found 34 of 35 new secret-shaped names digested and 16 of 32 honest names refused), so no policy here rests
on them. They remain only as a second belt a policy may switch on (`secret_name`); each way's docstring says whether it
does and why.
"""
from __future__ import annotations

import fnmatch
import os

OVER_BUDGET = "not checked: over the read budget"   # what a policy that reads returns when the build's budget is spent


class Policy:
    """Which files are evidence. The base admits nothing: a policy says yes only for what its structure holds."""
    name = "none"

    def roots(self) -> list[str]:
        return []

    def refuse(self, path: str, real: str, root: str, budget: dict | None = None) -> str | None:
        return "no evidence policy admits it"


# ---- the ways (one module each, with for_seat(seat, got, roots)) --------------------------------------------------
WAYS = {"git-index": "evidence_gitindex"}   # the owner's pick; a folders-first way would be one more entry here
DEFAULT_WAY = "git-index"


def way(name: str | None = None):
    """The module of one evidence way (the page's when no name is given). Imported when asked: a way imports this
    module, so this module cannot import a way at its top."""
    import importlib
    return importlib.import_module(f".{WAYS[name or DEFAULT_WAY]}", __package__)


def from_roots(roots, name: str | None = None) -> Policy:
    """The policy of a way (the page's by default) over a list of roots, as a filer that knows only its roots asks."""
    return way(name).for_seat(None, {}, [str(r) for r in roots if isinstance(r, (str, os.PathLike)) and str(r).strip()])


def key(path) -> str:
    """A path as compared on this system: separators and case as it treats them."""
    return os.path.normcase(os.path.normpath(str(path)))


def below(path, root) -> list[str] | None:
    """The parts of `path` below `root` (both as compared), or None when it is not below it."""
    p, r = key(path), key(root).rstrip("\\/")
    if not p.startswith(r + os.sep):
        return None
    return [x for x in p[len(r) + 1:].split(os.sep) if x]


# ---- the optional second belt: names (moved from change.py as 1.2.2 had them) -----------------------------------
SECRET_NAMES = (".env*", ".npmrc", ".netrc", ".pgpass", ".git-credentials", "id_rsa*", "id_dsa*", "id_ecdsa*",
                "id_ed25519*", "*.pem", "*.key", "*.key.*", "*.pfx", "*.p12", "*.kdbx", "credentials*", "cred", "cred.*",
                "wallet*", "vault*", "*kaggle*", ".ssh*",
                "token", "tokens", "token.*", "tokens.*", "*_token*", "*-token*",
                "secret", "secrets", "secret.*", "secrets.*", "*_secret*", "*-secret*", "client_secret*",
                "settings.local.json", "service-account*", "service_account*", "*api_key*", "*api-key*", "*apikey*",
                "password*", "passwd*", "seed", "seed.*", "mnemonic*", "recovery_code*", "auth.json", "env.json",
                "key", "key.*", "keys", "keys.*", "private_key*", "private-key*")
SECRET_FOLDERS = (".ssh", ".kube", ".docker", ".aws", ".gnupg", ".kaggle")
SECRET_IN = {"gh": ("hosts.yml", "hosts.yaml")}   # a name that holds secrets only under a folder of this name


def secret_name(parts: list[str]) -> str | None:
    """The first part of a path named like a secret, taken whole and in any case, or None. A belt, never the policy."""
    for i, part in enumerate(parts):
        low = part.lower()
        if low in SECRET_FOLDERS or any(fnmatch.fnmatchcase(low, pat) for pat in SECRET_NAMES):
            return part
        if i and low in SECRET_IN.get(parts[i - 1].lower(), ()):
            return part
    return None
