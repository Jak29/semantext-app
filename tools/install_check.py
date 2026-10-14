"""install_check.py -- install a built wheel into a fresh virtual environment and check that it works as installed.

Usage:
  python install_check.py WHEEL [--sha256 HEX] [--system-site-packages] [--keep] [--timeout SECONDS]
  python install_check.py --self-test [--keep]

Every step is a check that can fail, and every failure is printed:
  1. hash       with --sha256, the wheel's SHA-256 must equal it, or nothing else runs;
  2. imports    read, not installed (ast): every import in the wheel's modules comes from the standard library, the
                wheel's own packages, or a declared dependency (Requires-Dist). Imports guarded by
                `try/except ImportError` or by `if TYPE_CHECKING:` are optional and are skipped. Imports made at run
                time by name (importlib) are not seen;
  3. venv       a new virtual environment in a new temporary directory. With --system-site-packages it can see this
                machine's installed packages, and the run is labelled NOT CLEAN;
  4. install    pip installs the wheel with --no-index --no-deps, so nothing is ever downloaded;
  5. deps       each declared dependency imports inside the venv;
  6. import     each top-level package imports inside the venv and is loaded from the venv, run isolated (-I) from an
                empty directory, so a source tree cannot stand in for the installed package;
  7. scripts    each console and GUI script runs `--help` and exits 0 within the timeout;
  8. uninstall  pip uninstalls the wheel, after which no top-level package loads from the venv.
Exit 0 when every check passes; 1 when any fails; 2 on bad usage.

The temporary directory is removed at the end unless --keep is given.
"""
import argparse
import ast
import base64
import configparser
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

# Distribution names whose import name differs (Requires-Dist name -> import name).
DIST_TO_IMPORT = {"pyyaml": "yaml", "pillow": "PIL", "scikit-learn": "sklearn", "beautifulsoup4": "bs4",
                  "python-dateutil": "dateutil", "opencv-python": "cv2", "pyzmq": "zmq", "protobuf": "google"}
PIP = [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check", "--no-input"]


def norm_dist(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def import_name(dist):
    n = norm_dist(dist)
    return DIST_TO_IMPORT.get(n, n.replace("-", "_"))


def read_wheel(whl):
    """Return (name, requires, scripts {name: target}, top-level names, {path: bytes} of .py files)."""
    with zipfile.ZipFile(whl) as z:
        names = z.namelist()
        infos = sorted({n.split("/")[0] for n in names if n.split("/")[0].endswith(".dist-info")})
        if len(infos) != 1:
            raise ValueError(f"expected one .dist-info directory, found {len(infos)}")
        di = infos[0]
        meta = z.read(f"{di}/METADATA").decode("utf-8", "replace")
        ep = z.read(f"{di}/entry_points.txt").decode("utf-8") if f"{di}/entry_points.txt" in names else ""
        top = z.read(f"{di}/top_level.txt").decode("utf-8").split() if f"{di}/top_level.txt" in names else None
        py = {n: z.read(n) for n in names if n.endswith(".py")}
    m = re.search(r"^Name:\s*(.+)$", meta, re.M)
    if not m:
        raise ValueError("METADATA has no Name")
    requires = []
    for line in meta.splitlines():
        if line.startswith("Requires-Dist:"):
            spec = line.split(":", 1)[1].strip()
            if re.search(r"\bextra\s*==", spec):
                continue  # an optional extra
            requires.append(re.match(r"[A-Za-z0-9._-]+", spec).group(0))
    cp = configparser.ConfigParser()
    cp.optionxform = str
    cp.read_string(ep)
    scripts = {}
    for section in ("console_scripts", "gui_scripts"):
        if cp.has_section(section):
            scripts.update({k: v.strip() for k, v in cp.items(section)})
    if top is None:  # no top_level.txt: packages are first path parts, modules are top-level .py files
        top = set()
        for n in names:
            first = n.split("/")[0]
            if first.endswith((".dist-info", ".data")):
                continue
            if "/" in n:
                top.add(first)
            elif n.endswith(".py"):
                top.add(n.removesuffix(".py"))
        top = sorted(top)
    return m.group(1).strip(), requires, scripts, top, py


def optional_import_ids(tree):
    """ids of import nodes that sit inside `try/except ImportError` or `if TYPE_CHECKING:`."""
    opt = set()

    def mark(stmts):
        for s in stmts:
            for n in ast.walk(s):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    opt.add(id(n))

    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                t = h.type
                caught = []
                if t is None:
                    caught = ["*"]
                elif isinstance(t, ast.Name):
                    caught = [t.id]
                elif isinstance(t, ast.Tuple):
                    caught = [e.id for e in t.elts if isinstance(e, ast.Name)]
                if set(caught) & {"*", "ImportError", "ModuleNotFoundError", "Exception", "BaseException"}:
                    mark(node.body)
                    break
        elif isinstance(node, ast.If):
            t = node.test
            if (isinstance(t, ast.Name) and t.id == "TYPE_CHECKING") or \
                    (isinstance(t, ast.Attribute) and t.attr == "TYPE_CHECKING"):
                mark(node.body)
    return opt


def static_imports(py_files, own, declared):
    stdlib = set(sys.stdlib_module_names)
    problems = []
    for path, src in sorted(py_files.items()):
        try:
            tree = ast.parse(src, filename=path)
        except SyntaxError as e:
            problems.append(f"{path}:{e.lineno}: does not parse ({e.msg})")
            continue
        opt = optional_import_ids(tree)
        for node in ast.walk(tree):
            if id(node) in opt:
                continue
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                mods = [node.module or ""]
            else:
                continue
            for mod in mods:
                top = mod.split(".")[0]
                if top and top not in stdlib and top not in own and top not in declared:
                    problems.append(f"{path}:{node.lineno}: imports '{top}', which is not the standard library, "
                                    f"this wheel, or a declared dependency")
    return problems


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


PROBE = (
    "import importlib, json, sys\n"
    "out = {}\n"
    "for name in sys.argv[1:]:\n"
    "    try:\n"
    "        m = importlib.import_module(name)\n"
    "        out[name] = ['ok', getattr(m, '__file__', None) or str(list(getattr(m, '__path__', [])))]\n"
    "    except BaseException as e:\n"
    "        out[name] = ['error', type(e).__name__ + ': ' + str(e)]\n"
    "print(json.dumps(out))\n"
)


def probe(py, names, cwd, timeout):
    r = subprocess.run([str(py), "-I", "-c", PROBE, *names], cwd=cwd, capture_output=True, text=True,
                       timeout=timeout)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {n: ["error", f"probe failed: {r.stderr.strip()[:200]}"] for n in names}


def under(path_text, root):
    try:
        p = pathlib.Path(path_text.strip("[]'\"")).resolve()
        return p.is_relative_to(pathlib.Path(root).resolve())
    except (OSError, ValueError):
        return False


def check(whl, want_sha=None, system_site=False, keep=False, timeout=60, quiet=False):
    """Run the eight steps. Return (ok, {step: bool}, lines)."""
    lines, steps = [], {}

    def say(step, ok, text):
        steps[step] = steps.get(step, True) and ok
        lines.append(f"  {'PASS' if ok else 'FAIL'}  {step}: {text}")

    whl = pathlib.Path(whl)
    if want_sha:
        got = sha256(whl)
        say("hash", got == want_sha.lower(), f"sha256 {got}" + ("" if got == want_sha.lower() else
                                                               f" is not the expected {want_sha.lower()}"))
        if not steps["hash"]:
            return False, steps, lines
    name, requires, scripts, top, py = read_wheel(whl)
    declared = {import_name(r) for r in requires}
    problems = static_imports(py, set(top), declared)
    say("imports", not problems, f"{len(py)} module(s) read, every import accounted for" if not problems else
        f"{len(problems)} problem(s)")
    lines += [f"        {p}" for p in problems]
    root = pathlib.Path(tempfile.mkdtemp(prefix="install_check_"))
    empty = root / "empty"
    empty.mkdir()
    try:
        vdir = root / "venv"
        args = [sys.executable, "-m", "venv", "--without-pip"] + (["--system-site-packages"] if system_site else [])
        r = subprocess.run(args + [str(vdir)], capture_output=True, text=True)
        vpy = vdir / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")
        say("venv", r.returncode == 0 and vpy.exists(),
            ("NOT CLEAN (it sees this machine's site-packages)" if system_site else "clean (no site-packages)")
            + ("" if r.returncode == 0 else f"; venv failed: {r.stderr.strip()[:200]}"))
        if not steps["venv"]:
            return False, steps, lines
        r = subprocess.run(PIP + ["--python", str(vpy), "install", "--no-index", "--no-deps", str(whl)],
                           capture_output=True, text=True, timeout=max(timeout, 120))
        say("install", r.returncode == 0, f"pip install --no-index --no-deps {whl.name}" +
            ("" if r.returncode == 0 else f"; pip said: {(r.stderr or r.stdout).strip()[-300:]}"))
        if requires:
            res = probe(vpy, sorted(declared), empty, timeout)
            bad = {n: v for n, v in res.items() if v[0] != "ok"}
            say("deps", not bad, f"{len(res) - len(bad)} of {len(res)} declared dependencies import" +
                ("" if not bad else "; missing: " + ", ".join(f"{n} ({v[1]})" for n, v in sorted(bad.items()))
                 + ("" if system_site else " (nothing is downloaded; a clean venv has only what the wheel brings)")))
        else:
            say("deps", True, "no declared dependencies")
        res = probe(vpy, top, empty, timeout)
        bad = {n: v for n, v in res.items() if v[0] != "ok" or not under(v[1], vdir)}
        say("import", not bad and bool(top), f"{len(top) - len(bad)} of {len(top)} top-level package(s) load from "
            f"the venv" + ("" if not bad else "; " + ", ".join(
                f"{n} ({v[1] if v[0] != 'ok' else 'loaded from outside the venv: ' + v[1]})"
                for n, v in sorted(bad.items()))))
        sdir = vdir / ("Scripts" if os.name == "nt" else "bin")
        if scripts:
            for s in sorted(scripts):
                exe = sdir / (s + ".exe" if os.name == "nt" else s)
                if not exe.exists():
                    say("scripts", False, f"{s}: no launcher was installed")
                    continue
                try:
                    r = subprocess.run([str(exe), "--help"], cwd=empty, capture_output=True, text=True,
                                       timeout=timeout)
                    say("scripts", r.returncode == 0, f"{s} --help exited {r.returncode}" +
                        ("" if r.returncode == 0 else f": {(r.stderr or r.stdout).strip()[-200:]}"))
                except subprocess.TimeoutExpired:
                    say("scripts", False, f"{s} --help did not finish within {timeout} s")
        else:
            say("scripts", True, "no scripts declared")
        r = subprocess.run(PIP + ["--python", str(vpy), "uninstall", "-y", name], capture_output=True, text=True,
                           timeout=max(timeout, 120))
        res = probe(vpy, top, empty, timeout)
        left = [n for n, v in res.items() if v[0] == "ok" and under(v[1], vdir)]
        say("uninstall", r.returncode == 0 and not left, f"pip uninstall {name}" +
            ("" if not left else f"; still loads from the venv: {', '.join(left)}") +
            ("" if r.returncode == 0 else f"; pip said: {(r.stderr or r.stdout).strip()[-200:]}"))
    finally:
        if keep:
            lines.append(f"  (kept: {root})")
        else:
            shutil.rmtree(root, ignore_errors=True)
    ok = all(steps.values())
    return ok, steps, lines


# ---------------------------------------------------------------- self-test
def build_wheel(dst, name, version, files, requires=(), scripts=None, top=None):
    """A minimal, valid pure-Python wheel, built by hand (no build tool needed)."""
    dist = name.replace("-", "_")
    di = f"{dist}-{version}.dist-info"
    entries = dict(files)
    entries[f"{di}/METADATA"] = (f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
                                 + "".join(f"Requires-Dist: {r}\n" for r in requires))
    entries[f"{di}/WHEEL"] = ("Wheel-Version: 1.0\nGenerator: install_check self-test\nRoot-Is-Purelib: true\n"
                              "Tag: py3-none-any\n")
    if scripts:
        entries[f"{di}/entry_points.txt"] = "[console_scripts]\n" + "".join(f"{k} = {v}\n" for k, v in scripts.items())
    if top:
        entries[f"{di}/top_level.txt"] = "\n".join(top) + "\n"
    record = []
    for p, text in entries.items():
        data = text.encode("utf-8")
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{p},sha256={digest},{len(data)}")
    record.append(f"{di}/RECORD,,")
    entries[f"{di}/RECORD"] = "\n".join(record) + "\n"
    whl = pathlib.Path(dst) / f"{dist}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w", zipfile.ZIP_DEFLATED) as z:
        for p, text in entries.items():
            z.writestr(p, text)
    return whl


CLI = ("import argparse\n\n\ndef main():\n    p = argparse.ArgumentParser(prog='demo')\n"
       "    p.add_argument('--name', default='world')\n    a = p.parse_args()\n    print('hello', a.name)\n")


def self_test(keep=False):
    work = pathlib.Path(tempfile.mkdtemp(prefix="install_check_selftest_"))
    try:
        import yaml  # noqa: F401  (only to know whether the system-site arm can run here)
        have_yaml = True
    except ImportError:
        have_yaml = False
    good = build_wheel(work, "demo-ok", "0.1.0", {
        "demo_ok/__init__.py": "import json\n__version__ = '0.1.0'\ntry:\n    import zz_optional_extra\n"
                               "except ImportError:\n    zz_optional_extra = None\n",
        "demo_ok/cli.py": CLI}, scripts={"demo-ok": "demo_ok.cli:main"}, top=["demo_ok"])
    arms = [
        # (name, kind, wheel, kwargs, expected failing step or None)
        ("good wheel", "must-pass", good, {}, None),
        ("wrong hash", "must-refuse", good, {"want_sha": "0" * 64}, "hash"),
        ("undeclared import", "must-refuse", build_wheel(work, "demo-undeclared", "0.1.0", {
            "demo_undeclared/__init__.py": "import zz_not_a_real_module\n"}, top=["demo_undeclared"]), {}, "imports"),
        ("broken script", "must-refuse", build_wheel(work, "demo-broken", "0.1.0", {
            "demo_broken/__init__.py": "", "demo_broken/cli.py": CLI},
            scripts={"demo-broken": "demo_broken.cli:missing"}, top=["demo_broken"]), {}, "scripts"),
        ("package missing from the wheel", "must-refuse", build_wheel(work, "demo-ghost", "0.1.0", {
            "demo_ghost_other/__init__.py": ""}, top=["demo_ghost"]), {}, "import"),
        ("dependency absent in a clean venv", "must-refuse", build_wheel(work, "demo-dep", "0.1.0", {
            "demo_dep/__init__.py": "import yaml\n"}, requires=["PyYAML>=5"], top=["demo_dep"]), {}, "deps"),
    ]
    if have_yaml:
        arms.append(("dependency seen with system site-packages", "must-pass", arms[-1][2],
                     {"system_site": True}, None))
    ok_all = True
    for name, kind, whl, kw, expect in arms:
        ok, steps, lines = check(whl, keep=keep, **kw)
        if expect is None:
            passed = ok
            label = "NOT CLEAN" if kw.get("system_site") else "clean"
            detail = f"every step passed ({label})" if ok else "a step failed"
        else:
            passed = (not ok) and steps.get(expect) is False
            detail = f"step '{expect}' failed as it must" if passed else f"step '{expect}' did not fail: {steps}"
        print(f"  {'PASS' if passed else 'FAIL'}  {kind:<11}  {name}: {detail}")
        if not passed:
            print("\n".join(lines))
        ok_all &= passed
    if not have_yaml:
        print("  SKIP  must-pass     dependency seen with system site-packages: PyYAML is not installed here")
    print(f"self-test: {'ALL PASSED' if ok_all else 'FAILED'} ({len(arms)} checks)")
    if keep:
        print(f"(kept: {work})")
    else:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if ok_all else 1


def main():
    ap = argparse.ArgumentParser(description="Install a wheel into a fresh venv and check it works as installed.")
    ap.add_argument("wheel", nargs="?")
    ap.add_argument("--sha256")
    ap.add_argument("--system-site-packages", action="store_true")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test(a.keep)
    if not a.wheel:
        ap.error("WHEEL is required (or --self-test)")
    ok, _, lines = check(a.wheel, a.sha256, a.system_site_packages, a.keep, a.timeout)
    print(f"install check of {pathlib.Path(a.wheel).name}:")
    print("\n".join(lines))
    print("RESULT: " + ("PASS" if ok else "FAIL") + (" (NOT CLEAN: system site-packages)" if a.system_site_packages
                                                     else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
