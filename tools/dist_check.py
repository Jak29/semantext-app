"""dist_check.py -- check that the built wheel and sdist ship exactly the committed files, byte for byte.

Usage:  python tools/dist_check.py [--ref REF] [--dist DIR]

For every file in dist/*.whl and dist/*.tar.gz, it reports one of three things:
  - identical to its blob at REF (git's own hash; LF/CRLF differences are tolerated);
  - build metadata (dist-info, egg-info, PKG-INFO, setup.cfg);
  - a problem: it DIFFERS from the commit, or it is NOT IN THE COMMIT at all.
Files in the commit that the sdist leaves out are listed for reading, without a verdict.
Exit 0 when nothing differs and nothing ships that the commit lacks; 1 otherwise; 2 on bad usage.
"""
import argparse
import hashlib
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


def git(*args) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def tree(ref: str) -> dict[str, str]:
    out = {}
    for rec in git("ls-tree", "-r", "-z", ref).split(b"\x00"):
        if rec:
            meta, path = rec.split(b"\t", 1)
            out[path.decode("utf-8")] = meta.split()[2].decode()
    return out


def is_metadata(name: str) -> bool:
    return ".dist-info/" in name or ".egg-info/" in name or name in ("PKG-INFO", "setup.cfg")


def compare(label: str, members, blobs: dict[str, str]) -> bool:
    same, differ, extra, meta = [], [], [], []
    for name, data in members:
        if name in blobs:
            ok = blobs[name] in (blob_sha1(data), blob_sha1(data.replace(b"\r\n", b"\n")))
            (same if ok else differ).append(name)
        elif is_metadata(name):
            meta.append(name)
        else:
            extra.append(name)
    print(f"{label}: {len(same)} identical, {len(differ)} DIFFER, {len(extra)} NOT IN THE COMMIT, {len(meta)} metadata")
    for n in differ:
        print(f"  DIFFERS: {n}")
    for n in extra:
        print(f"  NOT IN THE COMMIT: {n}")
    return not differ and not extra


def main() -> int:
    ap = argparse.ArgumentParser(description="Check that dist/ ships exactly the committed files.")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--dist", default="dist")
    a = ap.parse_args()
    d = Path(a.dist)
    wheels, sdists = sorted(d.glob("*.whl")), sorted(d.glob("*.tar.gz"))
    if not wheels and not sdists:
        print(f"no wheel or sdist in {d}", file=sys.stderr)
        return 2
    blobs = tree(a.ref)
    ok = True
    for w in wheels:
        with zipfile.ZipFile(w) as z:
            ok &= compare(w.name, [(n, z.read(n)) for n in z.namelist() if not n.endswith("/")], blobs)
    for s in sdists:
        with tarfile.open(s) as t:
            files = [m for m in t.getmembers() if m.isfile() and "/" in m.name]
            members = [(m.name.split("/", 1)[1], t.extractfile(m).read()) for m in files]
        ok &= compare(s.name, members, blobs)
        left_out = sorted(set(blobs) - {n for n, _ in members})
        if left_out:
            print(f"  in the commit but not in {s.name} (for reading): {', '.join(left_out)}")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
