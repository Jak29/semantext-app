"""Evidence, way 2 (git index): a change's evidence is read only from files the project's git index lists.

THE PREMISE, stated plainly. Evidence is what the project's index lists. The index is not a record of what was
committed or reviewed: an agent can write it (`git add -f .env`, with no commit, lists .env), and an agent can write
objects and commits too, so no reading of a repository is a boundary against an agent that breaks rules. This policy
chooses RELEVANT files (what a project keeps as its own) for a digest to confirm; it is not a defence against an agent
that breaks rules. What it does refuse is structural: files no real repository lists, and a few names (the short
belt below) that are almost never honest even when listed.

The roots are the filing agent's home and the projects bound to it, as before. Inside a root, a file is evidence when
the git repository that holds it lists it in its index as an ordinary file:
  the repository  the nearest folder at or above the file's own that holds a .git FOLDER (git's own rule: the nearest
                  one wins, so a nested repository holds its own files). It is searched for up to the root, and above
                  the root only while the folder is still inside one of the policy's roots: a home below its
                  repository's top (seat folders in one shared repository) is read when that top is itself inside a
                  named root, and only the home's own files are asked of it; a top above every root is never read.
                  It must be a real repository: .git/HEAD a plain file holding a commit id of the right length, or
                  naming a ref ("ref: refs/...", a name git would write) that exists, as a loose ref file under
                  .git/refs holding a commit id or as a line of .git/packed-refs. So a hand-built .git/index in a
                  plain folder admits nothing, nor one beside a hand-written HEAD naming a ref that is not there; a
                  branch with no commit yet is not read either. This is still a test of text and files: a forger
                  who writes the ref file too is admitted, as the premise says.
  the index       <top>/.git/index, read here in pure Python: nothing runs git, and nothing else in .git is opened. It
                  must be a plain file (no link, no hard link), at most 64 MB, read through one handle checked against
                  it as examined, and its trailing checksum must match (SHA-1 or SHA-256; an all-zero trailer, which
                  git writes with index.skipHash, is accepted, as git accepts it).
  the entry       stage 0 (not a merge conflict), an ordinary file (mode 100644 or 100755: never a symlink or a
                  submodule), not marked intent-to-add (`git add -N`) and not skip-worktree (sparse checkout), whose
                  path equals the file's path below the top. The path is compared as this system compares paths: on
                  Windows without case, as git's core.ignorecase does there.
Index versions 2, 3 and 4 are read (4 writes each path as a cut of the one before it). Not read, and so "unknown": an
index of another version, a sparse index (it lists whole folders), a split index (core.splitIndex: part of it lives
in another file), a .git that is a FILE (a linked worktree or a submodule names its repository elsewhere, and that is
not followed), a .git or index that is a link, and an index whose checksum does not match. Untracked and ignored files
are not in the index, so they are "unknown", never "current".

Every check of change.py runs first (no link or junction below the root, no hard link, no stream, the real path inside
the root, the size cap); this policy only narrows what inside the roots is evidence. A parsed index is kept in memory
(never on disk) for 60 seconds, keyed by its path, size, modification time and file id; its bytes count against the
page build's read budget when it is read.

The full name belt (evidence.secret_name) is OFF here: it refused honest listed files (password_policy.md, keys.py).
A SHORT belt is on, for listed files only, each name refused with its reason: TRACKED_BELT (keys and key stores by
extension, ssh key names, credential folders such as .ssh and .aws, dotfiles such as .npmrc, .netrc and .pgpass, and
the words secret, token, wallet, vault, password, credentials as their own word), and TRACKED_DATA (words honest as a
note or code, key, auth, env, seed and the like, refused only as data: .json, .txt, .yaml and the rest of DATA_EXT).
Measured on the audit's lists, tracked: all 89 of its secret names refused, none of its 60 honest names. Its cost,
stated: a few common names that are usually honest (app.log, server.log, access.log, appsettings.json, settings.xml,
known_hosts, session.json) are refused because the audit found them holding secrets. A secret listed under any other
name is evidence, like any listed file.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import stat
import struct
import time

from .evidence import OVER_BUDGET, Policy, below, key, secret_name
from .places import _linked   # a symlink or a junction; a cloud placeholder is not a link

NAME_BELT = False             # see the docstring: the index decides; switching this on refuses honest files again
# The short belt, for TRACKED files only (audit of fb1720d, protection finding 2; widened by the audit of f8dfae1,
# protection finding 1): names that are almost never honest, refused even when the index lists them. Each part of the
# path below the root (folders too) is matched whole, in any case. Every word is matched as its own word: never
# tokenizer.py, tokens.md, wallets.md, keys.py, key.md, password_policy.md, secretary.md or api_keys_doc.md.
TRACKED_BELT = (
    ".env*", "*.pem", "*.key", "*.key.*", "*.p12", "*.pfx", "*.kdbx", "*.jks", "*.keystore",        # keys and stores
    "id_rsa*", "id_dsa*", "id_ecdsa*", "id_ed25519*",                   # ssh keys by name (never id_mapping.py)
    ".ssh*", ".aws", ".gnupg", ".kube", ".kaggle", ".docker",           # folders that hold credentials
    ".npmrc", ".netrc", "_netrc", ".pgpass", ".git-credentials", ".pypirc", ".dockercfg", ".htpasswd", "htpasswd",
    "passwd", "shadow", "authorized_keys", "known_hosts", "kubeconfig", "kubeconfig.*", "pip.ini", "rclone.ini",
    "rclone.conf", "settings.xml", "appsettings.json", "appsettings.*.json", "settings.local.*", "kaggle.json",
    "app.log", "server.log", "access.log",                              # logs the audit found holding secrets
    "credentials", "credentials.*", "*_credentials*", "*-credentials*",  # never credentials_policy.md
    "service-account*", "service_account*", "client_secret*", "clientsecret*",
    "secret.*", "secrets.*", "secret_*", "secrets_*", "secret-*", "secrets-*", "*_secret*", "*-secret*", "secretkey*",
    "private_key*", "private-key*", "privatekey*", "apikey*", "api_key.*", "api-key.*",
    "token", "token.*", "*_token*", "*-token*", "*.token", "*token.*", "tokenstore*",   # never tokenizer.py
    "wallet", "*wallet.*", "wallet_*", "wallet-*", "vault.*",           # never wallets.md, vaulted.md, vault_notes.md
    "password.*", "passwords.*", "*_password*", "*-password*", "passphrase*", "mnemonic*", "seed_phrase*",
    "seed-phrase*", "recovery_codes*", "recovery-codes*")
# Words that are honest as a note or code (key.md, keys.py, auth.md, env.md, token_budget.md) but not as data: refused
# only with one of these extensions.
DATA_EXT = ("json", "txt", "yaml", "yml", "csv", "ini", "toml", "xml", "conf", "cfg", "env", "sh", "dat", "properties")
TRACKED_DATA = ("key", "keys", "*_key", "*-key", "api_keys", "auth", "env", "cred", "creds", "seed", "pass", "oauth",
                "jwt", "bearer", "session", "sessions", "cookie", "cookies", "hosts", "tokens", "token_*", "token-*",
                "tokens_*", "tokens-*", "credentials_*", "credentials-*")
_BELT = TRACKED_BELT + tuple(f"{w}.{x}" for w in TRACKED_DATA for x in DATA_EXT)
HEAD_CAP = 4096               # a HEAD or a loose ref longer than this names no ref or commit
PACKED_CAP = 16 * 1024 * 1024  # a packed-refs over this is not read
# What a repository's HEAD holds: a symbolic ref, or a detached commit id (SHA-1 or SHA-256).
HEAD_SAYS = re.compile(rb"(?:ref: (refs/[!-~]+)|([0-9a-f]{40}|[0-9a-f]{64}))\r?\n?")
REF_HOLDS = re.compile(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})\r?\n?")     # what a loose ref file holds
PACKED_LINE = re.compile(rb"([0-9a-f]{40}|[0-9a-f]{64}) (\S+)\r?")  # a packed-refs line: an id, a space, the ref
REF_BAD = re.compile(r"\.\.|@\{|[~^:?*\[\\]|//|/\.|\.lock(?:/|$)|[/.]$")   # git check-ref-format's refusals
INDEX_CAP = 64 * 1024 * 1024  # an index over this is not read
CACHE_S = 60.0                # how long a parsed index stands
VERSIONS = (2, 3, 4)
_CACHE: dict = {}             # in memory only: (index as compared, size, mtime, file id) -> (names or why, when)
_NOT_HERE = object()


class _Bad(Exception):
    pass


# ---- the index file (git's dircache, read without git) ----------------------------------------------------------
def _varint(data: bytes, q: int, end: int) -> tuple[int, int]:
    """Git's offset varint (version 4's "strip this many bytes"): 7 bits a byte, high bit set while more follow, and
    one added before each shift so that no value has two spellings."""
    if q >= end:
        raise _Bad("its index ends inside an entry's name")
    c, q = data[q], q + 1
    val, steps = c & 127, 0
    while c & 128:
        steps += 1
        if steps > 9 or q >= end:
            raise _Bad("an entry's name cut cannot be read")
        c, q = data[q], q + 1
        val = ((val + 1) << 7) + (c & 127)
    return val, q


def _entries(data: bytes, version: int, count: int, size: int, end: int) -> list[bytes]:
    """The paths of the ordinary tracked files in an index whose hash is `size` bytes long, its entries ending by
    `end`. _Bad when it cannot be read as an index whole."""
    out: list[bytes] = []
    p, prev = 12, b""
    for _ in range(count):
        start = p
        if p + 40 + size + 2 > end:
            raise _Bad("its index ends inside an entry")
        mode = struct.unpack_from(">I", data, p + 24)[0]
        flags = struct.unpack_from(">H", data, p + 40 + size)[0]
        q = p + 40 + size + 2
        extended = 0
        if flags & 0x4000:
            if version < 3:
                raise _Bad("a version 2 index has an entry with extended flags")
            if q + 2 > end:
                raise _Bad("its index ends inside an entry")
            extended = struct.unpack_from(">H", data, q)[0]
            q += 2
        if version == 4:
            strip, q = _varint(data, q, end)
            nul = data.find(b"\0", q, end)
            if nul < 0 or strip > len(prev):
                raise _Bad("an entry's name cannot be read")
            name = prev[:len(prev) - strip] + data[q:nul]
            p = nul + 1
        else:
            nul = data.find(b"\0", q, end)
            if nul < 0:
                raise _Bad("an entry's name cannot be read")
            name = data[q:nul]
            length = flags & 0x0FFF
            if length < 0x0FFF and length != len(name):
                raise _Bad("an entry's name is not as long as it says")
            p = start + (((q - start) + len(name) + 8) & ~7)   # padded with 1 to 8 NULs to a multiple of 8
            if p > end:
                raise _Bad("its index ends inside an entry")
        prev = name
        kind, stage = mode >> 12, (flags >> 12) & 3
        if kind == 0o04:
            raise _Bad("it is a sparse index (it lists whole folders), which is not read")
        if stage == 0 and kind == 0o10 and not extended & 0x6000:   # 0x2000 intent-to-add, 0x4000 skip-worktree
            out.append(name)
    while p + 8 <= end:                                             # the extensions after the entries
        sig, length = data[p:p + 4], struct.unpack_from(">I", data, p + 4)[0]
        if sig == b"link":
            raise _Bad("it is a split index (part of it is in another file), which is not read")
        if sig == b"sdir":
            raise _Bad("it is a sparse index (it lists whole folders), which is not read")
        p += 8 + length
    return out


def tracked(data: bytes) -> list[bytes]:
    """The paths (as git writes them: bytes, "/" between names) of the ordinary tracked files in an index's bytes, or
    _Bad with the reason it cannot be read."""
    if len(data) < 12 or data[:4] != b"DIRC":
        raise _Bad("it is not a git index (no DIRC signature)")
    version, count = struct.unpack(">II", data[4:12])
    if version not in VERSIONS:
        raise _Bad(f"its index is version {version}; versions 2, 3 and 4 are read")
    why = "its index's checksum does not match its bytes"
    for size, algo in ((20, hashlib.sha1), (32, hashlib.sha256)):
        if len(data) < 12 + size:
            continue
        trailer = data[-size:]
        if trailer != bytes(size) and algo(data[:-size]).digest() != trailer:
            continue
        try:
            return _entries(data, version, count, size, len(data) - size)
        except _Bad as e:
            why = str(e)
    raise _Bad(why)


def _same(a, b) -> bool:
    return (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_dev, b.st_ino, b.st_size, b.st_mtime_ns)


def _names(index: str, budget: dict | None):
    """The tracked paths of one index, as compared on this system, or why they cannot be known."""
    try:
        st = os.lstat(index)
    except FileNotFoundError:
        return "its repository has no index, so nothing in it is tracked yet"
    except (OSError, ValueError) as e:
        return f"its repository's index cannot be examined ({getattr(e, 'strerror', None) or e})"
    if _linked(st) or not stat.S_ISREG(st.st_mode):
        return "its repository's index is not a plain file, so it is not read"
    if st.st_nlink > 1:
        return "its repository's index is a hard link, so it is not read"
    if st.st_size > INDEX_CAP:
        return f"its repository's index is over {INDEX_CAP // (1024 * 1024)} MB, so it is not read"
    now = time.monotonic()
    k = (key(os.path.realpath(index)), st.st_size, st.st_mtime_ns, st.st_ino)
    hit = _CACHE.get(k)
    if hit and now - hit[1] < CACHE_S:
        return hit[0]
    if budget is not None:
        if st.st_size > budget["left"]:
            return OVER_BUDGET
        budget["left"] -= st.st_size
    fd = os.open(index, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        if not _same(os.fstat(fd), st):
            return "its repository's index changed before it was read"
        chunks, left = [], INDEX_CAP + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != st.st_size or not _same(os.lstat(index), st):
        return "its repository's index changed while it was read"
    try:
        got = frozenset(key(n.decode("utf-8", "surrogateescape").replace("/", os.sep)) for n in tracked(data))
    except _Bad as e:
        got = f"its repository's index is not read: {e}"
    for old in [x for x, (_, at) in _CACHE.items() if now - at >= CACHE_S]:
        del _CACHE[old]
    _CACHE[k] = (got, now)
    return got


def _small(path: str, what: str, cap: int, budget: dict | None = None):
    """The bytes of one plain file in .git, read through one handle checked against it as examined (audit of f8dfae1,
    note 3: the HEAD was opened by name after it was examined); None when it is not there, else why it is not read."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        return f"its repository's {what} cannot be examined ({getattr(e, 'strerror', None) or e})"
    if _linked(st) or not stat.S_ISREG(st.st_mode) or st.st_nlink > 1:
        return f"its repository's {what} is not a plain file, so it is not read"
    if st.st_size > cap:
        return f"its repository's {what} is too long, so it is not read"
    if budget is not None:
        if st.st_size > budget["left"]:
            return OVER_BUDGET
        budget["left"] -= st.st_size
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as e:
        return f"its repository's {what} cannot be read ({e.strerror or e})"
    try:
        if not _same(os.fstat(fd), st):
            return f"its repository's {what} changed before it was read"
        chunks, left = [], cap + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) != st.st_size:
        return f"its repository's {what} changed while it was read"
    return data


def _head(dotgit: str, budget: dict | None = None) -> str | None:
    """Why this .git folder is not a real repository, or None. Its HEAD must be a plain file holding a commit id, or
    naming a ref that exists: a loose ref file under .git/refs holding a commit id, or a line of .git/packed-refs
    (audit of fb1720d: a hand-built .git/index in a plain folder admitted anything beside it; audit of f8dfae1,
    protection finding 2: a HEAD naming a ref that does not exist was admitted). A branch with no commit yet (git
    init, git add) names a ref that does not exist yet, so it is not read either."""
    data = _small(os.path.join(dotgit, "HEAD"), "HEAD", HEAD_CAP)   # capped this small, it is not counted
    if data is None:
        return "its .git has no HEAD, so it is not a repository (an index alone is not read)"
    if isinstance(data, str):
        return data
    said = HEAD_SAYS.fullmatch(data)
    if not said:
        return "its repository's HEAD names neither a ref nor a commit id, so it is not a repository"
    if said.group(2):
        return None                                        # a detached HEAD: a commit id of the right length
    ref = said.group(1).decode("ascii")
    if REF_BAD.search(ref):
        return "its repository's HEAD names a ref git would not write, so it is not a repository"
    loose = _small(os.path.join(dotgit, *ref.split("/")), "ref", HEAD_CAP)
    if isinstance(loose, bytes):
        if REF_HOLDS.fullmatch(loose):
            return None
        return "its repository's HEAD names a ref whose file holds no commit id, so it is not a repository"
    if isinstance(loose, str):
        return loose
    packed = _small(os.path.join(dotgit, "packed-refs"), "packed-refs", PACKED_CAP, budget)
    if isinstance(packed, str):
        return packed
    want = ref.encode("ascii")
    for line in (packed or b"").split(b"\n"):
        got = PACKED_LINE.fullmatch(line)
        if got and got.group(2) == want:
            return None
    return (f"its repository's HEAD names {ref}, which no ref file or packed-refs line holds (a branch with no commit "
            "yet, or not a repository)")


def tracked_belt(parts: list[str]) -> str | None:
    """The first part of a path the short belt names, or None."""
    for part in parts:
        low = part.lower()
        if any(fnmatch.fnmatchcase(low, pat) for pat in _BELT):
            return part
    return None


# ---- the policy ---------------------------------------------------------------------------------------------------
class GitIndex(Policy):
    name = "git-index"

    def __init__(self, roots=()):
        self._roots = [str(r) for r in roots if r]

    def roots(self) -> list[str]:
        return list(self._roots)

    def _inside_a_root(self, folder: str) -> bool:
        return any(key(folder) == key(r) or below(folder, r) is not None
                   for r in (os.path.realpath(x) for x in self._roots))

    def _verdict(self, got, parts: list[str]):
        """The index's answer, with the belts on a file it admits."""
        if got is not None:
            return got
        part = tracked_belt(parts)
        if part:
            return f"{part!r} is named like a secret, so it is refused even though git tracks it"
        if NAME_BELT:
            part = secret_name(parts)
            if part:
                return f"{part!r} is named like a secret"
        return None

    def _at(self, top: str, rest: list[str], budget):
        dotgit = os.path.join(top, ".git")
        try:
            st = os.lstat(dotgit)
        except FileNotFoundError:
            return _NOT_HERE
        except (OSError, ValueError) as e:
            return f"its repository cannot be examined ({getattr(e, 'strerror', None) or e})"
        if _linked(st):
            return "its repository's .git is a link, so it is not followed"
        if stat.S_ISREG(st.st_mode):
            return ("its repository's .git is a file (a linked worktree or a submodule names its repository "
                    "elsewhere), which is not followed")
        if not stat.S_ISDIR(st.st_mode):
            return "its repository's .git is not a folder"
        why = _head(dotgit, budget)
        if why:
            return why
        names = _names(os.path.join(dotgit, "index"), budget)
        if isinstance(names, str):
            return names
        if key(os.path.join(*rest)) not in names:
            return "git does not track it (it is untracked, ignored, or not listed in its index as an ordinary file)"
        return None

    def refuse(self, path: str, real: str, root: str, budget: dict | None = None) -> str | None:
        real_root = os.path.realpath(root)
        if not below(real, real_root):
            return "it is not inside its root"
        rest = os.path.relpath(real, real_root).split(os.sep)
        for i in range(len(rest) - 1, -1, -1):   # the file's own folder first, then up to the root
            got = self._at(os.path.join(real_root, *rest[:i]), rest[i:], budget)
            if got is _NOT_HERE:
                continue
            return self._verdict(got, rest)
        # A home below its repository's top (seat folders inside one shared repository): the search goes on up, but
        # never out of the policy's own roots, so the top must itself be inside one of them (audit of fb1720d,
        # protection finding 3). Only this file is asked of that index, and it lies below the home.
        up = real_root
        while True:
            parent = os.path.dirname(up)
            if parent == up or not self._inside_a_root(parent):
                break
            up = parent
            got = self._at(up, os.path.relpath(real, up).split(os.sep), budget)
            if got is _NOT_HERE:
                continue
            return self._verdict(got, rest)
        return "it is in no git repository whose top is inside its roots"


def for_seat(seat: str, got: dict, roots: list[str] | None = None) -> GitIndex:
    """The git-index policy for one agent: its home and bound projects are the roots; the index decides inside."""
    return GitIndex(roots or [])
