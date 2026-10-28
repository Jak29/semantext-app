"""A git index written in pure Python, for tests: the dircache layout of versions 2, 3 and 4 as git documents it
(Documentation/gitformat-index.txt). Each entry is a path, or (path, {"mode", "stage", "ext", "name_len"}) to bend
one field. The checksum is SHA-1 (hash=20) or SHA-256 (hash=32); trailer="zero" writes the all-zero trailer of
index.skipHash, trailer="bad" a wrong one. `extensions` are (signature, bytes) written after the entries."""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path


def varint(v: int) -> bytes:
    """Git's offset varint (encode_varint)."""
    out = [v & 127]
    v >>= 7
    while v:
        v -= 1
        out.append(128 | (v & 127))
        v >>= 7
    return bytes(reversed(out))


def index_bytes(entries, version=2, hash=20, trailer="ok", extensions=(), count=None) -> bytes:
    rows = []
    for e in entries:
        path, opts = (e, {}) if isinstance(e, str) else e
        rows.append((path.encode("utf-8"), opts))
    rows.sort(key=lambda r: r[0])
    parts, prev = [], b""
    for name, opts in rows:
        mode, stage, ext = opts.get("mode", 0o100644), opts.get("stage", 0), opts.get("ext", 0)
        flags = min(opts.get("name_len", len(name)), 0xFFF) | (stage << 12) | (0x4000 if ext else 0)
        head = struct.pack(">10I", 0, 0, 0, 0, 0, 0, mode, 0, 0, 0) + b"\x11" * hash + struct.pack(">H", flags)
        if ext:
            head += struct.pack(">H", ext)
        if version == 4:
            common = 0
            while common < min(len(prev), len(name)) and prev[common] == name[common]:
                common += 1
            parts.append(head + varint(len(prev) - common) + name[common:] + b"\0")
        else:
            size = (len(head) + len(name) + 8) & ~7
            parts.append(head + name + b"\0" * (size - len(head) - len(name)))
        prev = name
    for sig, data in extensions:
        parts.append(sig + struct.pack(">I", len(data)) + data)
    data = b"DIRC" + struct.pack(">II", version, len(rows) if count is None else count) + b"".join(parts)
    algo = hashlib.sha1 if hash == 20 else hashlib.sha256
    if trailer == "zero":
        return data + bytes(hash)
    digest = algo(data).digest()
    return data + (digest if trailer == "ok" else bytes(b ^ 0xFF for b in digest))


def write_index(top: Path, entries, head="ref: refs/heads/main\n", ref="1" * 40, **kw) -> Path:
    """<top>/.git/index holding these entries (the .git folder is made when it is not there), and a HEAD as git
    writes one when there is none yet (head=None writes no HEAD: a hand-built index in a plain folder), with the loose
    ref it names holding `ref` (ref=None writes none: a branch with no commit yet)."""
    git = Path(top) / ".git"
    git.mkdir(parents=True, exist_ok=True)
    if head is not None and not (git / "HEAD").exists():
        (git / "HEAD").write_text(head, encoding="utf-8")
    said = (git / "HEAD").read_text(encoding="utf-8") if (git / "HEAD").is_file() else ""
    if ref is not None and said.startswith("ref: "):          # the branch HEAD names, with a commit, as git leaves it
        branch = git.joinpath(*said[5:].strip().split("/"))
        if not branch.exists():
            branch.parent.mkdir(parents=True, exist_ok=True)
            branch.write_text(ref + "\n", encoding="ascii")
    out = git / "index"
    out.write_bytes(index_bytes(entries, **kw))
    return out
