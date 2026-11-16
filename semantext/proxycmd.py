"""The proxy from the command line: start it, list what it holds, and answer it.

    semantext proxy serve --space FOLDER [--port N]     start the proxy (your own act, at your own terminal)
    semantext proxy asks                                the calls it holds for your word, this run only
    semantext proxy answer ASK yes|no|revoke             your answer (your own act, at your own terminal)

The proxy keeps its state in one folder (default: `proxy` in your Semantext home): the asks it holds, the chained
record, its node key, and `run.json`, which names its current run. An ask belongs to one run of the proxy: an answer
to an ask of an earlier run is refused, so a yes can never outlive the proxy that held the call. While a proxy starts,
`run.json` names no run ("starting": true) from the moment it holds the folder until it has bound its port, so nothing
of the run before it is listed or answered in between, with one residual window: from the moment serve takes the folder
(serve.lock) until its one atomic write of the starting run.json, a look still reads the old run.json and can list, or
take a yes for, a dead run's ask (_run_of states it: 14.7 ms at the median, 22.7 at the 90th percentile and 68.8 at most,
measured under a tight poller in 150 starts). Nothing is released by it: the new run's id and the record's chain gate
every release.

What an answer does: `answer` writes your word to the record's chain first, then to the asks file, under the same
cross-process locks the proxy uses. The running proxy reads both: a yes releases exactly the call it was asked for,
once, when the agent makes that call again (or the client retries the held turn); a no or a revoke drops it.

Starting and answering are refused in an agent's shell, as far as Semantext can tell one (inbox.human_terminal). Its
limit is the inbox answer's, stated in SECURITY.md: an agent that starts a process in a fresh hidden console can pass
that test, and an agent with your file rights can write the asks file and the record directly (decide.Asks, A1). The
anchor (ARCHITECTURE section 2) is what would catch the second. Listing is not refused: an ask holds no input text,
only the tool, the agent and why it is held.

One proxy per folder: `serve` holds a lock on the folder for as long as it runs, and binds its port exclusively, so a
second start on the same folder or port is refused and never renames the run of the one that is running.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import time
from pathlib import Path

from . import blocks, decide
from .assemble import Refused as KernelRefused
from .proxy_record import Record, RecordFailed
from .store import Refused, file_lock, write_atomic

CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _shown(value, cap: int = 80) -> str:
    """A field from the asks file as it may be printed: no control characters (a stray escape reaches the terminal),
    and at most `cap` characters."""
    s = CONTROL.sub("?", str(value))
    return s if len(s) <= cap else s[:cap] + "..."


ASK_ID = re.compile(r"ask_[0-9A-HJKMNP-TV-Z]{26}\Z")      # the shape the proxy mints (proxy_record.mint)
_BARE_WINDOWS = re.compile(r"[A-Za-z0-9_./\\:+][A-Za-z0-9_./\\:+~-]*\Z")


def shell_quote(text: str, windows: bool | None = None) -> str:
    """`text` as one argument in the shell it is printed for: PowerShell on Windows, a POSIX shell elsewhere. Left bare
    when it has nothing the shell reads (so an ordinary path is printed as it is), otherwise in single quotes: in
    PowerShell a quote inside is doubled, and so is each of the curly quotes it also reads as a quote; in a POSIX shell
    shlex.quote."""
    windows = os.name == "nt" if windows is None else windows
    if not windows:
        return shlex.quote(text)
    if _BARE_WINDOWS.match(text):
        return text
    for quote in "'‘’‚‛":
        text = text.replace(quote, quote * 2)
    return "'" + text + "'"


# Quoted, so a person who pastes the line unedited does not run `<your` and `> proxy` as redirections in cmd.exe or a POSIX
# shell (attack 26: with a file named `your` beside them they emptied or overwrote a file named `proxy`); the program is then
# given a folder name it cannot use and refuses.
_HIDDEN = {"--home": '"<your --home folder>"', "--proxy-home": '"<your --proxy-home folder>"'}


def _key_shaped_folder(typed, normalised: str) -> bool:
    """Whether the folder, as typed or as Path writes it, holds a key the typed-secret cut collects (cli.secret_values: a
    key shape, key=VALUE from 4 characters, a password in prose, a password in a URL). Looked at here, where the line is
    made, because a command that works releases its stdout uncut. The long token-like RUN is not asked (runs=False): an
    ordinary folder name of 32 or more letters, digits and underscores that holds a digit is that shape, and hiding it
    would turn most long folder names into a line that cannot be pasted. Limit: a folder named by a bare random run
    with no key shape is printed. The import is inside the function: cli imports this module."""
    from .cli import secret_values
    return bool(secret_values([str(typed), normalised], runs=False))


def revoke_note(proxy_home=None, home=None) -> str:
    """The words that go with a revoke line whose folder was not printed (see revoke_line), or "" when every folder was."""
    hidden = [flag for flag, folder in (("--home", home), ("--proxy-home", proxy_home))
              if folder and not CONTROL.search(str(Path(folder))) and _key_shaped_folder(folder, str(Path(folder)))]
    if not hidden:
        return ""
    return (f"(the name of your {' and '.join(hidden)} folder looks like a key, so it is not printed here; "
            f"put the folder you typed in place of the <...> part)")


def revoke_line(ask_id: str, proxy_home=None, home=None) -> str | None:
    """The line that takes a yes back, as the person pastes it:
    `semantext [--home HOME] proxy answer ASK revoke [--proxy-home PROXY_HOME]`, each folder quoted for their shell, with
    EVERY option that chose the proxy's folder, as given (attack 24, L3: the line carried --proxy-home alone, so after
    `semantext --home X proxy asks` it answered in the default home, was refused, and the yes stayed live). None when
    there is no line to print safely: an id that is not the shape the proxy mints (the asks file is a file another
    process can write: an id with `;` or `$(` in it is not pasted into a shell), or a folder with a control character in
    it. Found by the pageasks attack, K7: the line was built from unquoted text.
    *Limits:* a folder chosen by the SEMANTEXT_HOME variable is not printed (the person pastes the line into the shell
    that has it set); a relative folder is printed as given (it means the same only from the same working folder); one
    that begins with `-` is quoted but argparse still reads it as an option. The quoting is for PowerShell on Windows and
    a POSIX shell elsewhere, so a person pasting into cmd.exe has a folder holding `&` or `^` split (cmd.exe reads a
    single quote as an ordinary character); and a UNC root (`\\\\server\\share name\\`) keeps the trailing backslash Path
    leaves on a root, inside the quotes, where PowerShell 5.1 hands a native program a final `\\"`. Both are stated and
    not fixed: they need a person with a space, `&` or a bare share root in a folder they chose to type.
    A folder whose name looks like a key (attack 25, L8: `--home C:\\x\\token=Zq9x5Wv8Ut7Sr6\\h`) is NOT printed: the
    command exits 0 and its stdout is released uncut, so the line would say the key back. It is printed as
    `"<your --home folder>"` (or `"<your --proxy-home folder>"`), and revoke_note says why in words. Limits (attack 26):
    a folder named by a bare run of 32 or more letters, digits and `_+=-` (a 40-hex token) is printed, as _key_shaped_folder
    says; and a folder whose name ends in a key word and `=` (`secret=`) is hidden though it holds no value, and the word
    after it in the line becomes a value cut from later messages. Both are the price of not calling every long folder a key."""
    if not isinstance(ask_id, str) or not ASK_ID.match(ask_id):
        return None
    quoted = {}
    for flag, folder in (("--home", home), ("--proxy-home", proxy_home)):
        if folder:
            text = str(Path(folder))                  # no trailing separator: PowerShell 5.1 reads a final \ as an escape
            if CONTROL.search(text):
                return None
            quoted[flag] = f" {flag} {_HIDDEN[flag] if _key_shaped_folder(folder, text) else shell_quote(text)}"
    # --home is the program's own option and goes before the command; --proxy-home belongs to `proxy` and goes after it.
    return f"semantext{quoted.get('--home', '')} proxy answer {ask_id} revoke{quoted.get('--proxy-home', '')}"


def _guarded(fn):
    """The asks file and the record are files another process can damage: whatever they hold, the command answers
    with one readable refusal, never a traceback or a "please report it"."""
    def run(*a, **kw):
        try:
            return fn(*a, **kw)
        except Refused:
            raise
        except KernelRefused as e:
            raise Refused(f"the proxy's files cannot be used: {getattr(e, 'reason', e)}") from None
        except (TypeError, KeyError, AttributeError, ValueError, RecursionError, OSError, OverflowError,
                IndexError) as e:
            # OverflowError: a whole number too large for a float (or Infinity) in "expires" fails at the minutes
            # left, not at the compare (int(inf), int - float); it is the same damaged file as any other.
            raise Refused(f"the proxy's asks file holds something it should not ({type(e).__name__}); nothing was "
                          f"answered") from None
    return run

RUN_FILE = "run.json"
DEFAULT_PORT = 8790


def proxy_home(store_root, given=None) -> Path:
    return Path(given) if given else Path(store_root) / "proxy"


def write_run(home: Path, run: str, port: int) -> None:
    """Name the proxy's current run, so the answering command answers this run's asks and no other."""
    home.mkdir(parents=True, exist_ok=True)
    write_atomic(home / RUN_FILE, json.dumps({"run": run, "port": port, "pid": os.getpid(),
                                              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))


def write_starting(home: Path, port: int) -> None:
    """Name no run: the proxy holds the folder and is starting, and has not got a run to name yet. Written the moment
    serve takes serve.lock, before the proxy's start (its blocks, key, record check and bind), which takes as long as the
    record is long. Until then run.json named the run of the proxy that ended, and that run's asks, with days left on
    the monotonic clock after a reboot, were listed and answered as live (the pageasks attack, K4). The new run is named
    after the bind, by write_run, as before.
    *Limit:* the moment between taking the lock and this write (one atomic file write) still has the old run.json."""
    home.mkdir(parents=True, exist_ok=True)
    write_atomic(home / RUN_FILE, json.dumps({"run": None, "starting": True, "port": port, "pid": os.getpid(),
                                              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))


class NoProxy(Refused):
    """No proxy has ever run from this folder (there is no run.json). The page says this in plain words; the command
    line says it as the refusal it always was."""


class Stopped(Refused):
    """A run.json is there, and no proxy holds the folder: the proxy that wrote it has ended."""


class Starting(Stopped):
    """A proxy holds the folder and has not named its run yet (run.json says so): nothing is listed or answered until it
    has. The page reads it as it reads a stopped proxy: nothing is held yet."""


STARTING = "a proxy is starting from this home and has not named its run yet"


def read_run(home: Path) -> dict:
    p = home / RUN_FILE
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise NoProxy(f"no proxy has run from {home}: start one with `semantext proxy serve`") from None
    except (OSError, ValueError):
        raise Refused(f"{p} cannot be read") from None
    if isinstance(d, dict) and d.get("starting") is True and not d.get("run"):
        raise Starting(f"{STARTING}: nothing is listed until it has")
    if not isinstance(d, dict) or not isinstance(d.get("run"), str) or not d["run"]:
        raise Refused(f"{p} does not name a run")
    return d


def _asks(home: Path, run: str, with_record: bool = True) -> decide.Asks:
    record = Record(home / "proxy.jsonl") if with_record else None
    if record is not None and not record.verify():
        raise Refused("the proxy's record is broken; nothing is answered until it is looked at")
    key_path = home / "node.key"
    key = key_path.read_bytes() if key_path.exists() else None
    return _RunAsks(home / "asks.json", run=run, key=key, record=record, home=home, answering=True)


STOPPED = "no proxy is running from this home, and what it held went with it"
STOPPED_ANSWER = "the proxy that held this call has stopped; nothing was answered"
PROBE_WAIT = 2.0     # seconds a probe waits for another probe; they hold the lock for microseconds


def proxy_running(home: Path) -> bool:
    """Whether a proxy runs from this folder, found out the only way that cannot be wrong after a reboot or a crash: by
    trying serve.lock, which a running proxy holds for its whole life (serve) and the operating system lets go when the
    process ends, however it ends. run.json is not the evidence: it is never removed, and the asks' expiry is on the
    monotonic clock, which starts again at boot (the pageasks attack: after a reboot a dead proxy's asks were listed
    with days left and could be answered).

    Only one answer means stopped: this probe took serve.lock, with its gate, and let it go at once. Anything else is
    "running", or not to be told, and reads the same: the lock held by a proxy; held by a proxy that is starting; a
    folder, a link, a second name or a read-only file where the lock should be; no right to make the file; a probe
    lock that could not be taken. A running proxy that is said to have stopped is the costly error (the person is told
    its held call went with it, and cannot answer it); a stopped one that reads running costs its asks listed, and an
    answer to one reported as taken though nothing releases it, since a run id and the chain gate every release
    (pageasks attack, K6).

    Probes do not meet each other at serve.lock. Each takes the probe lock (probe.lock, its own file, a short wait)
    first, and only then tries serve.lock without waiting, so the lock and its gate are held by a probe only while
    no other probe tries them; a probe that met a probe there read "running" for a dead proxy, and a dead proxy's
    ask was answered (K5). The probe never holds serve.lock longer than the test, and a proxy starting at that
    moment is not refused (its serve waits 0.5 s).
    *Limits:* a probe that meets a proxy that is starting at that instant reads "running", which is right a moment
    later; a stopped proxy's folder that cannot be written (no probe.lock can be made) reads "running", and its
    asks are listed though nothing can release them; the probe makes nothing where there is no folder."""
    home = Path(home)
    if not home.is_dir():
        return False                                   # the probe makes nothing where there is no folder
    try:
        with file_lock(home / "probe.lock", timeout=PROBE_WAIT):
            with file_lock(home / "serve.lock", timeout=0):
                return False                           # taken: nothing holds it
    except Exception:                                # held, or not to be taken at all: not "stopped"
        return True


def _starting(answering: bool) -> Starting:
    return Starting(f"{STARTING}; nothing was answered" if answering else f"{STARTING}: nothing is listed until it has")


def _run_of(home: Path, answering: bool = False) -> str:
    """The run the proxy has named in run.json, read AFTER the probe of the lock (attack 24, L2). It was read first and
    probed second, and a reader that read the dead run's run.json, then met a probe that had to wait for another
    probe's lock, found serve.lock held by the NEW proxy that had started in between, and took the old name for the
    new proxy's: in 150 of 150 starts a dead run's asks were listed, and in 114 a dead run's yes was taken. Probing first
    means a run.json read after "running" is the file as the holder left it, and "stopped" is never overtaken.
    While a proxy is starting there is no run to name (Starting); if nothing holds the folder then, the start ended
    without one and the proxy has stopped (Stopped).
    *Limit:* the file is still the old one in the moment between serve taking serve.lock and its one atomic write of the
    starting run.json (measured 14.7 ms at the median, 22.7 at the 90th percentile, 68.8 at most, under a tight poller
    in the attacker's 150 starts). There the lock is held, nothing marks the holder as new, and the dead run's name is
    read; every release still needs the new run's id and the chain, so nothing goes out (K6). It is the same file
    write that write_starting states."""
    try:
        read_run(home)                         # absent or unreadable: said now (the probe makes lock files in the folder)
    except Starting:
        pass
    running = proxy_running(home)              # the probe first ...
    try:
        run = read_run(home)["run"]            # ... run.json after it
    except Starting:
        if not running:
            raise Stopped(STOPPED_ANSWER if answering else STOPPED) from None
        raise _starting(answering) from None
    if not running:
        raise Stopped(STOPPED_ANSWER if answering else STOPPED)
    return run


def _still_this_run(home: Path, run: str, answering: bool) -> None:
    """run.json read once more, now: refuse unless it still names `run` (attack 24, L2). Called after the asks file is
    read, and for an answer under the asks file's lock, so a start that began after the first reading (run.json
    "starting", or the new run's name) stops the listing and the answer instead of being read past."""
    try:
        now = read_run(home)["run"]
    except Starting:
        raise _starting(answering) from None
    if now != run:
        raise Stopped(STOPPED_ANSWER if answering else STOPPED)


class _RunAsks(decide.Asks):
    """decide.Asks that checks run.json again each time it reads the asks file. Asks.answer reads the file after it takes
    the file's lock, so the check there is the last look before the write, under the lock (L2)."""

    def __init__(self, *a, home: Path, answering: bool = False, **kw):
        super().__init__(*a, **kw)
        self._home, self._answering = Path(home), answering

    def _read(self) -> list:
        rows = super()._read()
        _still_this_run(self._home, self.run, self._answering)
        return rows


def _chain_state(record) -> tuple[dict, set]:
    """One pass over the record's chain: {ask: its last answered word} and the set of spent asks. The chain's last
    word decides (decide.Asks, on the core branch: a yes later revoked is not a yes), and a spent ask releases
    nothing more. Read once per list, however many yeses the list holds (the pageasks attack: once per yes)."""
    last, spent = {}, set()
    for r in record.lines():
        body = r.get("body")
        if not isinstance(body, dict):
            continue
        if r.get("kind") == "answered" and isinstance(body.get("ask"), str) and isinstance(body.get("word"), str):
            last[body["ask"]] = body["word"]
        elif r.get("kind") == "spent" and isinstance(body.get("asks"), list):
            spent.update(x for x in body["asks"] if isinstance(x, str))
    return last, spent


def _listing(home: Path, with_yes: bool) -> list:
    """This run's live asks, oldest first, with `status` ("open" or "yes"): each the fields id, agent, tool, why,
    minutes_left. A yes is listed only when the chain's last word for it is "yes" and it is not spent (as the proxy
    itself requires). Raises NoProxy, or Stopped when no proxy holds the folder, or Refused when a file is damaged."""
    run = _run_of(home)                                # the probe first, run.json after it (L2)
    asks = _RunAsks(home / "asks.json", run=run, record=Record(home / "proxy.jsonl"), home=home)
    now = time.monotonic()
    chain = None
    out = []
    for a in asks._read():
        if not (isinstance(a.get("id"), str) and isinstance(a.get("expires"), (int, float))
                and not isinstance(a.get("expires"), bool)) or not asks.live(a, now):
            continue                                   # not an ask the proxy wrote, or not this run's, or run out
        status = a.get("status")
        if status not in (("open", "yes") if with_yes else ("open",)):
            continue
        if status == "yes":
            if chain is None:
                chain = _chain_state(asks.record)
            if chain[0].get(a["id"]) != "yes" or a["id"] in chain[1]:
                continue                               # the file says yes and the chain does not: it releases nothing
        tool = str(a.get("tool", ""))
        reading = a.get("reading") if isinstance(a.get("reading"), dict) else {}
        out.append({"id": _shown(a["id"]), "agent": _shown(a.get("agent", "")),
                    "tool": "a tool the agent may not call" if tool.startswith("undeclared") else _shown(tool),
                    "why": _shown(reading.get("rule") or "a gate holds this tool"),
                    "minutes_left": max(0, int((a["expires"] - now) // 60)), "status": status})
    return out


@_guarded
def open_asks(home: Path) -> list:
    """This run's asks that are still open and live, oldest first: id, agent, tool, reading rule, minutes left. Raises
    Stopped (with STOPPED) when no proxy runs from the folder."""
    return [{k: v for k, v in r.items() if k != "status"} for r in _listing(home, False)]


@_guarded
def held_asks(home: Path) -> list:
    """What `semantext proxy asks` lists: open_asks' rows, and the live yeses not yet used (each with status "yes"), so
    a yes can be seen and taken back at the terminal."""
    return _listing(home, True)


def page_asks(home: Path) -> dict:
    """What the page lists under "The proxy holds": {"state": "none" | "stopped" | "ok" | "unreadable", "asks": [...]}.

    "none": no proxy has run from this folder. "stopped": one did, and none runs now (nothing holds serve.lock), so
    nothing is listed: what it held went with it. "unreadable": the run file or the asks file is damaged, so nothing is
    listed (the command line says why). Otherwise this run's live asks that are open, and the live yeses not yet used
    (the ones a Revoke can still take back, and only a yes the record's chain also holds, last word "yes", not spent),
    oldest first. Each is the command's own fields (id, agent, tool, why, minutes_left) and `status`, "open" or "yes".
    Never the call's input and never your words; an ask of an earlier run is never listed. Read only: nothing is
    written, and the chain is not verified here (answering verifies it); the chain is read once per list."""
    try:
        return {"state": "ok", "asks": _listing(home, True)}
    except NoProxy:
        return {"state": "none", "asks": []}
    except Stopped:
        return {"state": "stopped", "asks": []}
    except (Refused, KernelRefused, TypeError, KeyError, AttributeError, ValueError, RecursionError, OSError,
            OverflowError):
        return {"state": "unreadable", "asks": []}


NOT_WRITTEN_RECORD = ("Semantext could not write the proxy's record, so nothing was answered; the record needs looking "
                      "at before any answer can be made")
NOT_WRITTEN_ASKS = ("your answer is on the proxy's record, but the proxy's asks file could not be written, so the proxy "
                    "does not act on it; answer again (the buttons on the page, or `semantext proxy answer ASK "
                    "yes|no|revoke`)")


@_guarded
def answer(home: Path, ask_id: str, word: str) -> str:
    """Your answer to one ask of the current run. Returns the ask's status after it."""
    if word not in ("yes", "no", "revoke"):
        raise Refused("answer yes, no or revoke")
    run = _run_of(home, answering=True)                # the probe first, run.json after it (L2)
    asks = _asks(home, run)                            # the asks file's reads look at run.json again, under its lock
    now = time.monotonic()
    before = asks.record.seq
    try:
        done = asks.answer(ask_id, word, now)
    except RecordFailed:
        raise Refused(NOT_WRITTEN_RECORD) from None    # the chain comes first: no line, no change to the asks file
    except KernelRefused:
        if asks.record.seq > before:                   # the line is on the chain and the asks file did not take it
            raise Refused(NOT_WRITTEN_ASKS) from None
        raise
    if not done:
        mine = next((a for a in asks._read() if a.get("id") == ask_id), None)
        if mine is None:
            raise Refused(f"there is no ask {ask_id}")
        if mine.get("run") != run:
            raise Refused(f"ask {ask_id} belongs to an earlier run of the proxy: its call is gone with that run, and "
                          f"the agent's next attempt is asked again")
        raise Refused(f"ask {_shown(ask_id)} cannot take {word!r}: it is {asks.status(ask_id, now)}")
    return {"yes": "yes", "no": "no", "revoke": "revoked"}[word]   # answered just now: no second read of the chain


class _NotStarted(Exception):
    """serve could not write run.json: said as one refusal, not taken for a port that cannot be used."""


def serve(space_dir, home: Path, card: str, port: int, ready=None) -> None:
    """Start the proxy on 127.0.0.1:port with this card, the space pinned as it is now."""
    from . import proxy
    space_dir = Path(space_dir)
    blocks.load(space_dir)                      # refused here, readably, if the space does not load whole
    home.mkdir(parents=True, exist_ok=True)
    try:
        with file_lock(home / "serve.lock", timeout=0.5):     # held for the proxy's whole life
            try:
                write_starting(home, port)              # at once: the run before this one is not this proxy's to list
            except OSError as e:
                raise _NotStarted(f"the proxy cannot write {RUN_FILE} in {home} ({e.strerror or e}), so it does not "
                                  f"start") from None
            proxy.serve(space_dir, home, card, port, ready=ready, on_run=lambda run: write_run(home, run, port))
    except _NotStarted as e:
        raise Refused(str(e)) from None
    except Refused:
        raise Refused(f"a proxy already runs from {home}: stop it first, or give this one its own --proxy-home") \
            from None
    except OSError as e:
        raise Refused(f"port {port} on 127.0.0.1 cannot be used ({e.strerror or e}): another program, or another "
                      f"proxy, holds it") from None
