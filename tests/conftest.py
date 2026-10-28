import pytest

from semantext.store import Store

# The variables an AI tool sets in its agent's shell. They change who Semantext thinks is asking, and whether a
# terminal may answer, so every test starts from a plain shell; a test that needs one sets it itself. (A suite run
# inside an agent's own shell once passed for that reason alone.)
AGENT_VARIABLES = ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED",
                   "SEMANTEXT_AGENT")


@pytest.fixture(autouse=True)
def plain_shell(monkeypatch):
    for name in AGENT_VARIABLES:
        monkeypatch.delenv(name, raising=False)


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
