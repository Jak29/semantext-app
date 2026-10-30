"""How the kernel holds an outside plug-in at arm's length: what "a plug-in never stops the rest" takes at run time.

The audit of the registry (c696d0b) found the promise held only at load. Here, for an outside plug-in only:

- Its attributes are read once, through one guarded accessor (attr), into a Snapshot: plain values and its bound
  methods. Before, a property that raised anything but AttributeError (hasattr catches only that) escaped
  load_enabled, and every /api/v2 place and `semantext plugins` went down with it (a second review, R1). Now it is a
  problem line and that plug-in is skipped; later reads touch the snapshot, never the plug-in's own attributes.
- Each call into it (a source's read, a place's build, a document's resolve and check_bytes) runs in a worker thread
  with a time budget (SECONDS, or SEMANTEXT_PLUGIN_SECONDS). A call that is late is a problem, and its result is
  ignored when it arrives. A thread cannot be killed: a late call keeps running in the background until it returns,
  with the process's whole reach (SECURITY.md, Plug-ins).
- What it answers is capped: at most MAX_PROBLEMS problems, each field cut to MAX_TEXT, and the whole answer at most
  MAX_BYTES when written as JSON. Over the cap is a problem, never a 100 MB answer. Every outside answer one page
  is built from (each source's, then the place's) is at most MAX_TOTAL together: the first that would pass it is
  refused, as that plug-in's problem (the audit of 784faf6, note 11: many plug-ins under the cap gave tens of MB).
- Whatever it raises in the worker (SystemExit, KeyboardInterrupt, GeneratorExit, asyncio.CancelledError, its own
  BaseException) is caught there and said as a RuntimeError: the person's own Ctrl-C arrives on the calling thread,
  never the worker's, and goes through.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time

from . import jsonread

SECONDS = 5.0                 # the time budget of one call into an outside plug-in
MAX_PROBLEMS = 200            # problems kept from one answer
MAX_TEXT = 300                # characters kept of each problem field
MAX_BYTES = 2 * 1024 * 1024   # an answer's size written as JSON
MAX_TOTAL = 8 * 1024 * 1024   # every outside answer of one page together, written as JSON
PLAIN = (str, int, float, bool, type(None))
VALUES = ("kind", "name", "title", "records", "page_module", "doc_type")   # kept as read, when plain
LISTS = ("keys", "needs")                                                  # kept as a tuple of plain values
CALLS = ("read", "build", "resolve", "check_bytes")                        # kept as the bound methods
_MISSING = object()


class Bad(Exception):
    """An outside plug-in that cannot be held: an attribute that raised, or is not a plain value."""


class Late(Exception):
    """A call into an outside plug-in that did not return within its time budget."""


class Snapshot:
    """An outside plug-in's attributes as read once at load, and its methods. Reading one never runs its code."""

    def __init__(self, values: dict):
        self.__dict__.update(values)

    def __repr__(self):
        return f"<plug-in {self.__dict__.get('kind')}.{self.__dict__.get('name')}>"


_REQUIRED = object()


def attr(obj, name: str, default=_REQUIRED):
    """getattr, with anything the plug-in raises, other than AttributeError, turned into Bad."""
    try:
        return getattr(obj, name)
    except AttributeError:
        if default is _REQUIRED:
            raise
        return default
    except KeyboardInterrupt:
        raise
    except BaseException as e:  # noqa: BLE001  SystemExit included: reading an attribute must not end the process
        raise Bad(f"reading its {name} raised {type(e).__name__}") from None


def snapshot(obj) -> Snapshot:
    """The attributes the kernel reads of a plug-in, each read once through attr. Bad when one raises, or holds
    something other than a plain value (a text, a number, a truth value, None), of that exact type: a subclass's own
    __eq__ or __hash__ would run later, on the caller's thread, when its name is compared or its doc_type looked up
    (the recheck of 4d78973, row 1)."""
    out = {}
    for name in VALUES:
        v = attr(obj, name, _MISSING)
        if v is _MISSING:
            continue
        if type(v) not in PLAIN:
            raise Bad(f"its {name} is a {type(v).__name__}, not a plain value")
        out[name] = v
    for name in LISTS:
        v = attr(obj, name, _MISSING)
        if v is _MISSING:
            continue
        if type(v) not in (list, tuple) or not all(type(x) in PLAIN for x in v):
            raise Bad(f"its {name} is not a list of plain values")
        out[name] = tuple(v)
    for name in CALLS:
        v = attr(obj, name, _MISSING)
        if v is not _MISSING:
            out[name] = v
    return Snapshot(out)


def seconds() -> float:
    try:
        said = float(os.environ.get("SEMANTEXT_PLUGIN_SECONDS", ""))
    except ValueError:
        return SECONDS
    return said if 0 < said <= 600 else SECONDS


UNSAYABLE = "it raised something whose words cannot be read"


def _said(e: BaseException) -> str:
    """What a plug-in raised, as plain text made on the worker's thread. Its __str__, and a SystemExit's code's
    __repr__, are its own code, so each is guarded: before, SystemExit(obj) whose repr raised escaped here, the worker
    left no answer and no error, and run gave back None, which the serve hook read as a check that passed (the Fable
    review of 70f2d3c, finding 2)."""
    try:
        name = type(e).__name__
        if type(name) is not str:
            name = "an error"
    except BaseException:  # noqa: BLE001
        name = "an error"
    try:
        text = f"it raised SystemExit({e.code!r})" if isinstance(e, SystemExit) else f"{name}: {e}"
        if type(text) is not str:
            raise TypeError
    except BaseException:  # noqa: BLE001  an error whose words cannot be read is still said
        text = f"{name}: (its words cannot be read)"
    return text[:MAX_TEXT]


class Busy(Late):
    """A call refused at once, with no thread started: the plug-in's earlier call passed its budget and still runs, or
    MAX_HANGING calls of all plug-ins together still run past theirs."""


class Crowded(Late):
    """A call refused at once, with no thread started and no wait: its plug-in's calls already fill every turn and
    every place in line (MAX_WAITING), or MAX_WAITERS calls of every plug-in together already wait. It is not Busy:
    nothing of the plug-in's need be hanging."""


MAX_IN_FLIGHT = 4    # calls of one plug-in that may run at once; one past that waits for a turn up to its budget, and
# then has its whole budget to run, so a caller waits at most twice the budget
MAX_WAITING = 2 * MAX_IN_FLIGHT   # calls of one plug-in that may wait for a turn at once; one more is Crowded
MAX_WAITERS = 32     # calls that may wait for a turn at once, of every plug-in together
MAX_HANGING = 16     # threads of calls into plug-ins that may be alive at once, of every plug-in together: so at most
# this many are ever past their budget and still running


class _Flight:
    """One plug-in's calls now running, and those of them already past their budget (hanging)."""
    __slots__ = ("running", "hanging")

    def __init__(self):
        self.running: set = set()
        self.hanging: set = set()


_FLIGHTS: dict[str, _Flight] = {}   # the plug-in's registration name ("<kind>.<name>") -> its calls
_WAITING: dict[str, int] = {}        # the plug-in's registration name -> its calls now waiting for a turn
_TURN = threading.Condition(threading.Lock())
_LAST: dict[tuple, dict] = {}        # (registration name, package, version) -> how its last call here ended
_IDENT: dict[str, tuple] = {}        # the registration name -> (package, version) of the plug-in loaded under it now
_ORDER = itertools.count()             # which call ended last: a clock can read the same twice
MAX_LAST = 256                       # plug-ins whose last call is kept; the oldest is let go past that
OUTCOMES = ("answered", "error", "late", "busy", "crowded")


CALLS_NAMED = ("call", "import", "signature", "read", "build", "resolve", "check_bytes")


def _ident(origin, version) -> tuple:
    return ("" if origin is None else str(origin), "" if version is None else str(version))


def identify(key: str, origin, version) -> None:
    """Say which package and version the plug-in loaded under a registration name is (registry.load_enabled, before
    its import): its calls' health is kept under the three together, so another version installed under the same name
    never shows this one's last call."""
    with _TURN:
        _IDENT[key] = _ident(origin, version)


def forget(key: str) -> None:
    """Let go of every last call kept under a registration name, of any package and version: done when the plug-in is
    turned on or off, so its health starts again from nothing."""
    with _TURN:
        for k in [k for k in _LAST if k[0] == key]:
            del _LAST[k]


def forget_all() -> None:
    """Every last call kept, let go (the tests start each from nothing)."""
    with _TURN:
        _LAST.clear()
        _IDENT.clear()


def _ended(key: str, outcome: str, seconds: float, call: str = "call") -> None:
    """Keep how a call ended, for the page's Plug-ins tab: the words are the kernel's, never the plug-in's. `call` is
    which call it was, as the kernel code that made it names it ("import", "read", ...)."""
    call = call if call in CALLS_NAMED else "call"
    with _TURN:
        key = (key,) + _IDENT.get(key, _ident(None, None))
        mine = _LAST.pop(key, {})
        mine[call] = {"outcome": outcome, "call": call, "seconds": round(max(0.0, seconds), 3),
                      "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "t": next(_ORDER)}
        _LAST[key] = mine
        while len(_LAST) > MAX_LAST:
            del _LAST[next(iter(_LAST))]


LOADING = ("import", "signature")   # the kernel's own calls made to load a plug-in, every answer


def _newest(records) -> dict | None:
    got = max(records, key=lambda r: r["t"], default=None)
    return {k: v for k, v in got.items() if k != "t"} if got else None


def health(key: str, origin=None, version=None) -> dict:
    """How a plug-in's calls stand in this process, by its registration name and the package and version it is: its
    last call of its own work (a read, a build, a resolve or a check) and its last call made to load it (its import,
    the read of its signature), each None when none was made here by THAT package and version; and how many of its
    calls are past their budget and still run (by name: those threads are the name's, whatever was loaded). Reading
    this runs nothing of the plug-in's."""
    with _TURN:   # no package named: the one loaded under the name now
        who = _IDENT.get(key, _ident(None, None)) if origin is None and version is None else _ident(origin, version)
        mine = _LAST.get((key,) + who, {})
        flight = _FLIGHTS.get(key)
        return {"last": _newest(r for c, r in mine.items() if c not in LOADING),
                "loading": _newest(r for c, r in mine.items() if c in LOADING),
                "holding": len(flight.hanging) if flight else 0}


def _hanging() -> int:
    return sum(len(f.hanging) for f in _FLIGHTS.values())


def _running() -> int:
    """Under _TURN: the threads of calls into plug-ins now alive, past their budget or not, of every plug-in."""
    return sum(len(f.running) for f in _FLIGHTS.values())


def _holding() -> dict[str, int]:
    """Under _TURN: each plug-in with calls past their budget that still run, and how many, by name."""
    return {k: len(f.hanging) for k, f in sorted(_FLIGHTS.items()) if f.hanging}


def holding() -> dict[str, int]:
    """Each plug-in holding calls that did not answer in time and still run, by its registration name, and how many.
    One plug-in holds at most MAX_IN_FLIGHT; MAX_HANGING of every plug-in together are allowed, so the cap is reached
    only by several plug-ins at once, and then the page and `semantext plugins` name them (holding_said)."""
    with _TURN:
        return _holding()


def _named(held: dict[str, int]) -> str:
    return ", ".join(f"{k} ({n})" for k, n in held.items())


def holding_said() -> list[str]:
    """What the page and `semantext plugins` say of the plug-ins holding calls: one line each, and one more when the
    cap of every plug-in together is reached, which then makes every other plug-in's call Busy."""
    held = holding()
    said = [f"{k} has {n} call{'s' if n != 1 else ''} that did not answer in time and still "
            f"run{'s' if n == 1 else ''}; its own calls are refused until they return" for k, n in held.items()]
    if sum(held.values()) >= MAX_HANGING:
        said.append(f"{MAX_HANGING} calls into plug-ins did not answer in time and still run, held by "
                    f"{_named(held)}: every other plug-in's call is refused until one of them returns")
    return said


def _whose(owner) -> str:
    """The name a call is counted under: the one the registry gave the plug-in when it was added ("<kind>.<name>"),
    passed by the kernel code that makes the call. Never the callable, a bound method's __self__ or a function's
    identity: two plug-ins sharing one helper, or one bound to the other's object, were counted as one, so one's late
    call made the other Busy; and a plug-in giving a fresh callable on every load was a new owner each time, so it alone
    filled the cap every plug-in shares (the recheck of 17021c2, V and NH3)."""
    if type(owner) is not str or not owner:
        raise TypeError("a call into a plug-in names the plug-in it is made for, by its registration name")
    return owner


def as_json(value) -> str:
    """A plug-in's answer as JSON text, made in the worker (the audit of 784faf6, findings 5 and 6: json.dumps calls a
    dict subclass's own items(), and a deep copy a __deepcopy__, so on the caller's thread they ran outside the
    budget, and one answer nested 500 deep stopped every other place). At most MAX_BYTES, nested at most
    jsonread.MAX_DEPTH; anything else is refused here, for this plug-in only. NaN and Infinity are refused too: json
    would write them bare, which no browser's JSON.parse reads, so one number cost the page's whole answer (the recheck
    of 4d78973, R)."""
    try:
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except RecursionError:
        raise ValueError(f"its answer is nested more than {jsonread.MAX_DEPTH} levels deep, so it is not used") from None
    except ValueError as e:
        if "Out of range float" in str(e):   # json's own words for NaN and Infinity under allow_nan=False
            raise ValueError("its answer holds NaN or Infinity, which JSON cannot carry, so it is not used") from None
        raise TypeError("its answer cannot be written as JSON") from None
    except TypeError:
        raise TypeError("its answer cannot be written as JSON") from None
    n = len(text.encode("utf-8", "surrogatepass"))
    if n > MAX_BYTES:
        raise ValueError(f"its answer is {n // 1024} KB, over the {MAX_BYTES // (1024 * 1024)} MB cap, so it is not used")
    if jsonread.depth(text) > jsonread.MAX_DEPTH:
        raise ValueError(f"its answer is nested more than {jsonread.MAX_DEPTH} levels deep, so it is not used")
    return text


def run_json(fn, *args, owner: str, budget: float | None = None, call: str = "call"):
    """fn(*args) as run makes it, its answer turned into JSON text in the worker (as_json), and that bounded text
    parsed here: what comes back is plain data, of known size and depth, that no code of the plug-in's is part of."""
    return jsonread.loads(run(fn, *args, owner=owner, budget=budget, post=as_json, call=call))


def run(fn, *args, owner: str, budget: float | None = None, post=None, call: str = "call"):
    """fn(*args) in a worker thread, its answer or its error, or Late after the budget. A late call's answer is never
    used: the thread is left to finish on its own (daemon), since a thread cannot be stopped from outside.

    Calls that overlap are served (the recheck of 4d78973, NH1: a page fetches several documents of one place at once,
    and two tabs overlap): up to MAX_IN_FLIGHT of one plug-in run at once, and up to MAX_WAITING more wait their turn
    (MAX_WAITERS of every plug-in together), each for at most its budget, so it is Late, never kept, when no turn comes
    in time; past that line a call is Crowded at once. One that gets a turn then has its whole budget to run, so a
    caller waits at most twice the budget. Only a call that started running and passed its budget is hanging, and no
    more than MAX_HANGING threads of every plug-in's calls are ever alive at once, so no more can hang.
    Only a plug-in whose earlier call
    has passed its budget and still runs is refused, Busy at once with no thread started, so one that hangs holds at most
    MAX_IN_FLIGHT threads, never one per request (the audit of 784faf6, finding 4). And at most MAX_HANGING calls past
    their budget run at once, of every plug-in together: past that, every call is Busy until one of them returns. One
    plug-in's share is MAX_IN_FLIGHT, so it takes MAX_HANGING // MAX_IN_FLIGHT plug-ins to reach that cap (the recheck
    of 17021c2, NH3), and the Busy then names them, as the page and `semantext plugins` do (holding_said).

    `owner` is whose call it is: the plug-in's registration name, "<kind>.<name>", given by the code that makes the
    call (_whose). Every call made on a plug-in's behalf carries it, the kernel's own reading of its signature included,
    so all of one plug-in's calls are counted together and no other plug-in's with them."""
    box: dict = {}
    key = _whose(owner)
    me: list = []

    def work():
        try:
            value = fn(*args)
            box["value"] = post(value) if post is not None else value   # post runs here too, under the budget
        except BaseException as e:  # noqa: BLE001  every one is the plug-in's: said as text, made here
            try:
                box["error"] = _said(e)
            except BaseException:  # noqa: BLE001  even saying it failed: the call is still an error, never no answer
                box["error"] = UNSAYABLE
        finally:
            with _TURN:
                flight = _FLIGHTS.get(key)
                if flight is not None:
                    flight.running.discard(me[0])
                    flight.hanging.discard(me[0])
                    if not flight.running:
                        del _FLIGHTS[key]
                _TURN.notify_all()

    budget = seconds() if budget is None else budget
    asked = time.monotonic()
    try:
        value = _run(work, me, key, budget, box)
    except Crowded:
        _ended(key, "crowded", time.monotonic() - asked, call)
        raise
    except Busy:
        _ended(key, "busy", time.monotonic() - asked, call)
        raise
    except Late:
        _ended(key, "late", time.monotonic() - asked, call)
        raise
    except RuntimeError:
        _ended(key, "error", time.monotonic() - asked, call)
        raise
    _ended(key, "answered", time.monotonic() - asked, call)
    return value


def _run(work, me: list, key: str, budget: float, box: dict):
    """run's turn, thread and wait, apart from keeping how the call ended (outside _TURN, which is not re-entrant)."""
    turn_by = time.monotonic() + budget   # the longest it waits for a turn; once it has one, it has its whole budget
    t = threading.Thread(target=work, name="semantext-plugin", daemon=True)
    me.append(t)
    with _TURN:
        waiting = False
        try:
            while True:
                flight = _FLIGHTS.get(key)
                if flight is not None and flight.hanging:
                    raise Busy("its last call did not answer in time and is still running, so this one is not made")
                if _hanging() >= MAX_HANGING:   # reached only by several plug-ins: each holds at most MAX_IN_FLIGHT
                    raise Busy(f"{MAX_HANGING} calls into plug-ins did not answer in time and are still running, held "
                               f"by {_named(_holding())}, so no other is made until one of them returns")
                # A turn is one of its plug-in's MAX_IN_FLIGHT and one of the MAX_HANGING threads of every plug-in:
                # a thread is counted from when it starts until it returns, so calls already running that later pass
                # their budget can never make more than MAX_HANGING threads (the Fable review of 70f2d3c, F4).
                if (flight is None or len(flight.running) < MAX_IN_FLIGHT) and _running() < MAX_HANGING:
                    break
                if not waiting:   # the line is bounded too: each place in it parks a caller's thread
                    if _WAITING.get(key, 0) >= MAX_WAITING:
                        raise Crowded(f"its calls fill every turn and all {MAX_WAITING} places in line, so this one "
                                      f"is not made")
                    if sum(_WAITING.values()) >= MAX_WAITERS:
                        raise Crowded(f"{MAX_WAITERS} calls into plug-ins already wait for a turn, so this one is not "
                                      f"made")
                    _WAITING[key] = _WAITING.get(key, 0) + 1
                    waiting = True
                left = turn_by - time.monotonic()
                if left <= 0:   # it never ran, so it is not hanging: it holds no thread and no turn
                    raise Late(f"it waited for a turn and none came in time ({budget:g} s; other calls held every "
                               f"turn), so this call was not made")
                _TURN.wait(left)   # woken when a call returns, or passes its budget
        finally:
            if waiting:
                _WAITING[key] -= 1
                if not _WAITING[key]:
                    del _WAITING[key]
        if flight is None:
            flight = _FLIGHTS[key] = _Flight()
        flight.running.add(t)
    try:
        t.start()
    except BaseException:   # no thread could be made: this call is not counted, or the plug-in would stay held
        with _TURN:
            flight.running.discard(t)
            if not flight.running and _FLIGHTS.get(key) is flight:
                del _FLIGHTS[key]
            _TURN.notify_all()
        raise
    # Its budget counts from when it started running, never from when it asked: time spent waiting for a turn never
    # makes a call hanging (the recheck of 17021c2, NH1's residual: well-behaved calls that got a late turn were counted
    # as hanging, so their plug-in was Busy, and they took places in the cap of every plug-in together).
    t.join(budget)   # the person's own Ctrl-C arrives here, on the calling thread
    if t.is_alive():
        with _TURN:
            flight = _FLIGHTS.get(key)
            if flight is not None and t in flight.running:   # still running past its budget: counted as hanging
                flight.hanging.add(t)
                _TURN.notify_all()                           # a call waiting its turn is now Busy, at once
        raise Late(f"it did not answer within {budget:g} s, so its answer is not used")
    if "error" in box:
        # Anything raised in the worker is the plug-in's, never the person's Ctrl-C (which arrives on the calling
        # thread): KeyboardInterrupt, GeneratorExit, asyncio.CancelledError and a BaseException of its own included.
        # All of them become one RuntimeError, which every caller catches (the audit of 784faf6, finding 1).
        raise RuntimeError(box["error"])
    if "value" not in box:   # the worker ended with neither: a failed call, never an answer of None
        raise RuntimeError("the call ended with no answer and no error, so it is taken as failed")
    return box["value"]


def _cut(v):
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return str(v)[:MAX_TEXT] if isinstance(v, (str, float)) else f"<{type(v).__name__}>"


def problems(said) -> tuple[list[dict], int]:
    """An outside answer's problems, kept to MAX_PROBLEMS records of short plain fields, and how many were left out."""
    if not isinstance(said, list):
        return [], 0
    kept = [{k: _cut(v) for k, v in list(p.items())[:8] if isinstance(k, str)}
            for p in said[:MAX_PROBLEMS] if isinstance(p, dict)]
    return kept, max(0, len(said) - MAX_PROBLEMS)


def size(answer) -> int | None:
    """The answer's size written as JSON, or None when it cannot be written as JSON at all."""
    try:
        return len(json.dumps(answer, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        return None
