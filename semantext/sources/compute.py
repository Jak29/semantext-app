"""The compute monitor: whether this machine is free for heavy work, read and never changed.

The gaming reader answers only what a button said, so a game started without pressing it was not seen. This reader adds
what the machine shows, and gives one verdict with its reasons:

    hold      the button is on, a program runs from a game folder, or a full-screen program is in front
    light     nothing says a game, but the processor is busy or memory is short: light work only
    unknown   a sign could not be read (the button's flag, or a check that failed), or this system let nothing be read,
              and nothing above says hold
    free      none of the signs this system can read says otherwise

Only "free" means go. A sign can only add a hold, never lift one: an unreadable sign is never counted as a clear one.
`not_read` names what was not looked at, so "free" is always read beside it. The GPU is always in it, since reading it
would start another program on every read of the page. Windows answers every other sign; Linux all but full screen; on
other systems (macOS) the machine's signs are not read yet, and there the verdict is "unknown" unless the button says
hold, never "free".

Game folders: the stores in GAME_FOLDERS, and any more the sources file's "game_folders" names, each a part of a path
such as "Games/Blizzard". The folders are matched whole, in any case, with either slash.

It lists the running programs' paths and asks the system about the screen, the processor and memory. It reads no
program's files, starts nothing and writes nothing, and only a game program's file name leaves this module.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from . import gaming

HOLD, LIGHT, UNKNOWN, FREE = "hold", "light", "unknown", "free"
CPU_BUSY = 90.0        # percent of the processor in use over the last reading, from which only light work is offered
MEMORY_LOW = 10.0      # percent of memory free, under which only light work is offered
FRESH_S = 5.0          # a reading is kept this long, since the frame is read with every answer
CPU_GAP_S = 0.2        # the shortest time two processor readings can be compared over
FULL_SCREEN = {2: "a full-screen program is in front", 3: "a Direct3D full-screen program is in front"}
MAX_GAMES = 8          # names of game programs given back; the count of the rest is not kept
GAME_FOLDERS = ("steamapps/common", "Epic Games", "GOG Games", "GOG Galaxy/Games", "Riot Games", "XboxGames",
                "Battle.net", "Ubisoft Game Launcher/games", "EA Games", "Lutris")   # the common stores' own folders
MAX_FOLDERS = 64
LAUNCHERS = {"epic games": {"epicgameslauncher.exe", "epicwebhelper.exe"},   # a store left open is no game: each
             "battle.net": {"battle.net.exe", "agent.exe"},                   # named within its own store's folder only,
             "riot games": {"riotclientservices.exe", "riotclientux.exe", "riotclientuxrender.exe"}}   # never by name alone


def _parts(path: str) -> list[str]:
    return [x for x in _back(path).lower().split("\\") if x]


def _named_folders(cfg: dict | None) -> tuple[list[str], str | None]:
    """The person's own game folders, and what is wrong with the setting. A folder the setting failed to name may be
    where a game is running, so a wrong setting is a sign that could not be read, never a clear one."""
    theirs = cfg.get("game_folders") if isinstance(cfg, dict) else None
    if theirs is None:
        return [], None
    if not isinstance(theirs, list):
        return [], "the game_folders setting is not a list of folders"
    good = [x for x in theirs[:MAX_FOLDERS] if isinstance(x, str) and _parts(x)]
    if len(theirs) > MAX_FOLDERS:
        return good, f"the game_folders setting names more than {MAX_FOLDERS} folders, and the rest were not looked for"
    if len(good) != len(theirs):
        return good, "the game_folders setting holds an entry that is not a folder"
    return good, None


def game_folders(cfg: dict | None) -> list[list[str]]:
    """Every game folder as its parts: the stores' own, then the person's."""
    return [_parts(x) for x in (*GAME_FOLDERS, *_named_folders(cfg)[0]) if _parts(x)]


def is_game_path(path: str, folders: list[list[str]] | None = None) -> bool:
    """A program inside a game folder: the folder's parts appear in the path's, in order and whole, before its file."""
    folders = game_folders(None) if folders is None else folders
    whole = _parts(path)
    parts = whole[:-1]
    if whole and any(store in parts and whole[-1] in names for store, names in LAUNCHERS.items()):
        return False
    return any(parts[i:i + len(f)] == f for f in folders for i in range(len(parts) - len(f) + 1))


def _back(path: str) -> str:
    return path.translate({ord("/"): "\\"})


def _base(path: str) -> str:
    return _back(path).rsplit("\\", 1)[-1]


# ---- Windows' answers ------------------------------------------------------------------------------------------
def _process_paths() -> list[str]:
    """The full path of every running program whose path Windows will tell this user."""
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.K32EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    k.K32EnumProcesses.restype = wintypes.BOOL
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    size = 4096
    while True:
        pids = (wintypes.DWORD * size)()
        got = wintypes.DWORD()
        if not k.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(got)):
            raise OSError(ctypes.get_last_error(), "could not list the running programs")
        if got.value < ctypes.sizeof(pids):
            break
        size *= 2
    out, buf = [], ctypes.create_unicode_buffer(32768)
    for pid in pids[: got.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            continue
        try:
            n = wintypes.DWORD(len(buf))
            if k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(n)):
                out.append(buf.value)
        finally:
            k.CloseHandle(handle)
    return out


def _screen_state() -> int:
    state = ctypes.c_int(0)
    hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    if hr != 0:
        raise OSError(hr, "could not ask Windows whether a full-screen program is in front")
    return state.value


def _cpu_times() -> tuple[int, int]:
    """(idle, total) processor time so far. Windows' kernel time includes its idle time."""
    idle, kernel, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError("could not read the processor's times")

    def n(t):
        return (t.dwHighDateTime << 32) | t.dwLowDateTime
    return n(idle), n(kernel) + n(user)


class _Memory(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def _memory_free() -> float:
    m = _Memory()
    m.dwLength = ctypes.sizeof(_Memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)) or not m.ullTotalPhys:
        raise OSError("could not read the memory's state")
    return 100.0 * m.ullAvailPhys / m.ullTotalPhys


# ---- Linux's answers --------------------------------------------------------------------------------------------
def _linux_programs() -> list[str]:
    out = []
    for entry in os.scandir("/proc"):
        if entry.name.isdigit():
            try:
                out.append(os.readlink(f"/proc/{entry.name}/exe"))
            except OSError:   # another user's program, or one that has just ended
                continue
    return out


def _linux_cpu_times() -> tuple[int, int]:
    parts = [int(x) for x in Path("/proc/stat").read_text(encoding="ascii").splitlines()[0].split()[1:]]
    return parts[3] + parts[4], sum(parts[:8])   # idle and waiting; every state but the guests', counted within user


def _linux_memory_free() -> float:
    seen = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        name, _, rest = line.partition(":")
        seen[name] = int(rest.split()[0])
    return 100.0 * seen["MemAvailable"] / seen["MemTotal"]


def _cannot(*a):
    raise NotImplementedError


class Signs:
    """What is read, one method for each sign, so a test can stand in for the machine. A sign this system has no way
    to read raises NotImplementedError: it is named in not_read, and is not a fault."""
    windows, linux = sys.platform == "win32", sys.platform.startswith("linux")
    programs = staticmethod(_process_paths if windows else _linux_programs if linux else _cannot)
    screen = staticmethod(_screen_state if windows else _cannot)
    cpu_times = staticmethod(_cpu_times if windows else _linux_cpu_times if linux else _cannot)
    memory_free = staticmethod(_memory_free if windows else _linux_memory_free if linux else _cannot)
    clock = staticmethod(time.monotonic)


# ---- the verdict -----------------------------------------------------------------------------------------------
_LOCK = threading.Lock()
_LAST_CPU: list = []    # [when, idle, total], the reading the next one is compared with
_KEPT: dict = {}        # the machine's part of the answer, and when it was read


def _reset() -> None:
    with _LOCK:
        _LAST_CPU.clear()
        _KEPT.clear()


def _cpu_busy(signs) -> float | None:
    """Percent busy since the last reading, or None when there is no reading far enough back to compare (not a fault:
    said in not_read, and it costs the verdict "free" until the next read). Called under _LOCK."""
    idle, total = signs.cpu_times()
    now = signs.clock()
    if _LAST_CPU and now - _LAST_CPU[0] < CPU_GAP_S:
        return None
    last = list(_LAST_CPU)
    _LAST_CPU[:] = [now, idle, total]
    if not last or total <= last[2] or idle < last[1]:
        return None
    return max(0.0, min(100.0, 100.0 * (1 - (idle - last[1]) / (total - last[2]))))


def _machine(signs, folders) -> dict:
    """The machine's signs: reasons to hold, reasons for light work, what could not be told, and what was not read."""
    hold, light, trouble, not_read, games = [], [], [], ["the GPU"], []
    if getattr(signs, "windows", False):   # Windows refuses to name many programs, games run as another user among them
        not_read.append("programs Windows will not name")
    read = 0
    try:
        names = sorted({_base(p) for p in signs.programs() if is_game_path(p, folders)})
        read += 1
        games = [str(n)[:120] for n in names[:MAX_GAMES]]
        if names:
            hold.append("a game is running: " + ", ".join(games))
    except NotImplementedError:
        not_read.append("running games")
    except Exception as e:  # noqa: BLE001  a sign that cannot be read is said, and is never a clear one
        trouble.append(f"the running programs could not be listed ({type(e).__name__})")
    try:
        state = signs.screen()
        read += 1
        if type(state) is not int or not 1 <= state <= 7:   # Windows' states are 1 to 7: anything else is no answer
            trouble.append("the system gave no answer on whether a full-screen program is in front")
        elif state in FULL_SCREEN:
            hold.append(FULL_SCREEN[state])
    except NotImplementedError:
        not_read.append("full-screen programs")
    except Exception as e:  # noqa: BLE001
        trouble.append(f"the system could not say whether a full-screen program is in front ({type(e).__name__})")
    busy = free = None
    waiting = False
    try:
        busy = _cpu_busy(signs)
        read += 1
        if busy is None:
            waiting = True
            not_read.append("the processor (no earlier reading to compare yet)")
        elif busy >= CPU_BUSY:
            light.append(f"the processor is {busy:.0f}% busy")
    except NotImplementedError:
        not_read.append("the processor")
    except Exception as e:  # noqa: BLE001
        trouble.append(f"the processor could not be read ({type(e).__name__})")
    try:
        free = signs.memory_free()
        read += 1
        if free < MEMORY_LOW:
            light.append(f"only {free:.0f}% of memory is free")
    except NotImplementedError:
        not_read.append("memory")
    except Exception as e:  # noqa: BLE001
        trouble.append(f"memory could not be read ({type(e).__name__})")
    return {"hold": hold, "light": light, "trouble": trouble, "not_read": not_read, "games": games,
            "blind": waiting or not read, "cpu_busy": None if busy is None else round(busy, 1),
            "memory_free": None if free is None else round(free, 1)}


def _kept_machine(signs, folders) -> dict:
    with _LOCK:
        now = signs.clock()
        if _KEPT.get("signs") is signs and _KEPT.get("folders") == folders and now - _KEPT["at"] < FRESH_S:
            return _KEPT["machine"]
        machine = _machine(signs, folders)
        _KEPT.update(signs=signs, folders=folders, at=now, machine=machine)
        return machine


def verdict(cfg: dict, now: float | None = None, signs=Signs) -> dict:
    """{"verdict": "hold" | "light" | "unknown" | "free", "reasons": [...], "not_read": [...], ...}. The button is read
    every time, so lowering it shows at once; what the machine shows is at most FRESH_S old."""
    button = gaming.load(cfg, now)
    m = _kept_machine(signs, game_folders(cfg))
    hold, trouble = list(m["hold"]), list(m["trouble"])
    bad_setting = _named_folders(cfg)[1]
    if isinstance(cfg, dict) and cfg.get("_sources_missing"):
        trouble.insert(0, "your sources file is named and is not there, so its settings were not read")
    if bad_setting:
        trouble.insert(0, bad_setting)
    if button.get("state") == "on":
        hold.insert(0, "the I'm gaming button is on")
    elif button.get("state") == "unknown":
        trouble.insert(0, str(button.get("why") or "the gaming flag could not be read"))
    if hold:
        word, reasons = HOLD, hold + m["light"]
    elif m["light"]:
        word, reasons = LIGHT, list(m["light"])
    elif trouble or m["blind"]:
        word, reasons = UNKNOWN, trouble or ["not every sign could be read"]
    else:
        word, reasons = FREE, []
    return {"verdict": word, "reasons": reasons[:12], "could_not_tell": trouble[:12], "not_read": list(m["not_read"]),
            "games": list(m["games"]), "cpu_busy": m["cpu_busy"], "memory_free": m["memory_free"]}


EXIT = {FREE: 0, UNKNOWN: 2, LIGHT: 3, HOLD: 3}   # as the inbox's gaming.py: only 0 means go


def ask(cfg: dict, signs=Signs, sleep=time.sleep) -> dict:
    """The verdict for a job about to start, from readings made now: nothing kept is used, and the processor is read
    twice, CPU_GAP_S and a little apart, so a single question can be answered "free"."""
    _reset()
    try:
        with _LOCK:
            _cpu_busy(signs)
        sleep(CPU_GAP_S + 0.1)
    except Exception:  # noqa: BLE001  said by the reading below, which fails the same way
        pass
    return verdict(cfg, signs=signs)
