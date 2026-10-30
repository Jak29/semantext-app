import os
import site
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from semantext.store import Store

# ---- the real user home is never read --------------------------------------------------------------------------------
# Taken once, here, before any test moves the home: the folder every test must keep out of, and the folders under it a
# run may still use (the temporary folder, this checkout, Python's own).
REAL_HOME = os.path.normcase(os.path.abspath(os.path.expanduser("~")))
ROOT = Path(__file__).resolve().parents[1]
ALLOWED = tuple(a for a in (os.path.normcase(os.path.abspath(p)) for p in {
    tempfile.gettempdir(), str(ROOT), sys.prefix, sys.base_prefix, sys.exec_prefix,
    site.getusersitepackages() if hasattr(site, "getusersitepackages") else sys.prefix,
    *(p for p in sys.path if p)} if p) if a != REAL_HOME)   # the home itself is never an allowed folder
WATCHED = ("open", "os.listdir", "os.scandir", "os.mkdir", "os.rename", "os.remove", "os.rmdir", "os.chmod",
           "os.symlink", "os.link", "shutil.copyfile", "shutil.rmtree")
TOUCHED: list = []        # (test, event, path) for every touch of the real home outside ALLOWED, in this process
_now = ["<collection>"]   # the test running now
_guard = threading.local()


def _under(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("\\/") + os.sep)


def real_home_touch(event: str, args) -> str | None:
    """The real-home path an audit event touches, or None: a path under REAL_HOME and under none of ALLOWED. Every
    path the event names is looked at, not only the first: a rename's, a link's or a copy's destination too."""
    if event not in WATCHED or not args:
        return None
    for arg in (args[:1] if event == "open" else args):   # open's other arguments are its mode text and flags
        if not isinstance(arg, (str, bytes, os.PathLike)):
            continue   # a file descriptor, a flag, a mode: no path
        try:
            p = os.path.normcase(os.path.abspath(os.fsdecode(arg)))
        except (TypeError, ValueError):
            continue
        if _under(p, REAL_HOME) and not any(_under(p, a) for a in ALLOWED):
            return p
    return None


def _audit(event, args):
    if getattr(_guard, "on", False):
        return
    _guard.on = True   # the hook's own work raises no events it would see again
    try:
        p = real_home_touch(event, args)
        if p is not None:
            TOUCHED.append((_now[0], event, p))
    finally:
        _guard.on = False


sys.addaudithook(_audit)   # for the whole run; an audit hook cannot be taken off, and it only records


def pytest_runtest_setup(item):
    _now[0] = item.nodeid


def pytest_runtest_teardown(item):
    _now[0] = "<between tests>"


def pytest_collection_modifyitems(session, config, items):
    """The check that no test touched the real home runs last, after every other test of the run."""
    last = [i for i in items if i.name == "test_no_test_of_the_run_touched_the_real_user_home"]
    items[:] = [i for i in items if i not in last] + last


@pytest.fixture(autouse=True)
def away_from_the_real_home(tmp_path_factory, monkeypatch):
    """Every test runs with the user's home, the Semantext home and the sources file pointed into a temporary folder,
    so nothing that works out "the user's home" (Path.home, expanduser, the default Semantext home, the sources file,
    git's global settings, Ollama's models) can reach the real one. A test that needs its own home sets it over this."""
    user = tmp_path_factory.mktemp("user-home")
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(user))
    drive, rest = os.path.splitdrive(str(user))
    monkeypatch.setenv("HOMEDRIVE", drive or "")
    monkeypatch.setenv("HOMEPATH", rest or str(user))
    monkeypatch.setenv("SEMANTEXT_HOME", str(user / ".semantext"))
    monkeypatch.delenv("SEMANTEXT_SOURCES", raising=False)   # the sources file is then the temporary home's, absent
    monkeypatch.setenv("APPDATA", str(user / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(user / "AppData" / "Local"))
    for name in ("XDG_CONFIG_HOME", "GIT_CONFIG_GLOBAL", "OLLAMA_MODELS"):
        monkeypatch.delenv(name, raising=False)

# The variables an AI tool sets in its agent's shell. They change who Semantext thinks is asking, and whether a
# terminal may answer, so every test starts from a plain shell; a test that needs one sets it itself. (A suite run
# inside an agent's own shell once passed for that reason alone.)
AGENT_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED",
                   "SEMANTEXT_AGENT")


@pytest.fixture(autouse=True)
def plain_shell(monkeypatch):
    for name in AGENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    # A console review is measured at the console's width (pluginpage.width()): every test sees the same 100 columns,
    # whatever terminal runs the suite; a test of the width itself puts the real one back.
    monkeypatch.setattr("semantext.pluginpage.width", lambda: 100)
    # How each plug-in's last call ended is kept per process (outside.health); tests reuse plug-in names, so each test
    # starts from nothing, never from the last call of another test's plug-in of the same name.
    from semantext import outside
    outside.forget_all()


@pytest.fixture(autouse=True)
def at_the_users_terminal(monkeypatch):
    """In-process, a test is the user at their own terminal (answering and changing rules are theirs), unless it says
    otherwise: a test of an agent sets a marker, and a test of a pipe sets stdin_is_console to False. A subprocess
    keeps its real standard input."""
    monkeypatch.setattr("semantext.inbox.stdin_is_console", lambda: True)


@pytest.fixture(autouse=True)
def no_plug_in_call_outlives_its_test():
    """Calls into plug-ins are counted under the plug-in's registration name ("source.tickets"), and tests reuse names:
    a late call one test leaves running would make the same name Busy in the next. So each test ends only once the
    plug-in threads it started have returned (each ends on its own deadline), as if every test were its own process."""
    yield
    import threading
    import time
    end = time.monotonic() + 15
    while time.monotonic() < end and any(t.name == "semantext-plugin" and t.is_alive() for t in threading.enumerate()):
        time.sleep(0.01)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh Semantext home, and a fresh user home, so no test ever touches the real ~/.semantext or ~/.claude."""
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setenv("HOME", str(user))          # Path.home() on Linux and macOS
    monkeypatch.setenv("USERPROFILE", str(user))   # Path.home() on Windows
    monkeypatch.setenv("SEMANTEXT_HOME", str(tmp_path / "semantext"))
    return tmp_path / "semantext"


@pytest.fixture
def store(home):
    return Store.open(home)
