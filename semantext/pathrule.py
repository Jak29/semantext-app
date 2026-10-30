"""The path rule: how a seats file's base folder and each home or root under it are read, by every reader.

One small module, importing nothing heavy and nothing of Semantext but jsonread, so the card hook can use it as the
places, gates and inbox readers do (and through them semantext.api's seat_rows and named_roots): the seats file is
parsed one way by all of them (read_seats), and one spelling is one folder to all of them, or refused by all of them.

What the rule refuses, the same on every system (inexact, base_of, under, home_base):

  - a control character (a NUL, a tab, a line break, DEL among them) or half of a surrogate pair;
  - a space before or after the whole path: trimmed, "alder\\t" would be read as the folder alder;
  - a part ending in a dot or a space ("teams.", "cedar. . ."), which Windows opens as the part without them;
  - a colon anywhere but straight after a drive letter at the start ("alder:stream", "cedar::$INDEX_ALLOCATION"),
    which Windows reads as a stream of a folder, not a folder;
  - a path written with the \\\\?\\ or \\\\.\\ prefix, which turns off the path's own reading;
  - a part that is a device name in the shape os.path.isreserved reads one (CON, PRN, AUX, NUL, CONIN$, CONOUT$,
    COM1 to COM9 and LPT1 to LPT9 with their superscript-digit forms, in any case, then any spaces, then an extension
    or nothing: "nul", "con .txt", "aux  .d"). Refused on every system, because many Windows versions read them as
    devices; recent Windows 11 does not;
  - for a home or a root under a base: a ".." step, or a drive, a root or a share of its own (a full path among them);
  - for a base: a ".." step anywhere (so "~/../Other" cannot climb out of your home); one that is not a full path
    once a leading "~" is expanded to the user's own home ("~" and "~/" on every system, and "~\\" too on Windows,
    whose expanduser reads a backslash as a separator; elsewhere "~\\x" is not expanded and so is refused); and
    "~name", another user's home, refused rather than guessed at (Windows would read it as a folder beside yours);
  - for the homes: no base given, or a base that is not an existing folder, which refuses every home at once.

What it does not refuse, and every reader therefore reads alike: a short (8.3) name such as PROGRA~1, a share as a
base (\\\\server\\share\\x), a format character such as a right-to-left override or a zero-width space, and a name
that differs only in case or in Unicode normalisation.
"""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import jsonread   # the one module of Semantext this imports: light, and the card hook's already

MAX_SEATS = 4 * 1024 * 1024   # bytes in a seats file; a larger one is a mistake, not a list of seats, and is not read


class SeatsUnread(ValueError):
    """Why the seats file could not be read: `kind` is too-big, unreadable, encoding or not-json."""

    def __init__(self, kind: str, why: str):
        super().__init__(why)
        self.kind = kind


def seats_path(value, folder=None) -> Path:
    """The seats file's own path, as every reader and the card hook resolve it: a leading "~" alone or "~/" (and "~\\"
    where expanduser reads a backslash as a separator) is the user's home, as for a base; "~name", another user's
    home, is refused (SeatsUnread); a relative path is relative to `folder`, the folder of the settings file that
    names it (the sources file's, for the readers; the card hook's config's, for the hook), never to the process's
    working folder; a full path is as written."""
    text = os.fspath(value) if isinstance(value, os.PathLike) else value
    if not isinstance(text, str) or not text.strip():
        raise SeatsUnread("unreadable", "no seats file is named")
    if OTHER_USER.match(text):
        raise SeatsUnread("unreadable", f"{text} names another user's home; write it in full, or as ~/ for your own")
    p = Path(os.path.expanduser(text)) if text.startswith("~") else Path(text)
    return Path(folder) / p if folder is not None and not p.is_absolute() else p


def read_seats(path):
    """The seats file's value, read one way by every reader and the card hook, or SeatsUnread: at most MAX_SEATS bytes,
    UTF-8 text (one byte-order mark allowed), and JSON as the person's own inbox parses it (jsonread.inbox_loads: no
    NaN or Infinity, no number out of its range, no half of a surrogate pair, no nesting past its depth), with no key
    given twice in one object (JSON would keep the last in silence). Whether the value has the right shape is each
    reader's own question.

    The path is resolved here too (seats_path), so every reader finds the same file: a leading "~" or "~/" is the
    user's home, as for a base, and "~name" is refused. The bytes are read with the cap, never past it, whatever the
    file's size said a moment before."""
    p = seats_path(path)
    try:
        with open(p, "rb") as f:
            raw = f.read(MAX_SEATS + 1)
    except (OSError, ValueError) as e:   # a ValueError is a name the system cannot take, such as one holding a NUL
        raise SeatsUnread("unreadable", f"it cannot be read ({getattr(e, 'strerror', None) or e})") from None
    if len(raw) > MAX_SEATS:
        raise SeatsUnread("too-big", f"it is over {MAX_SEATS // (1024 * 1024)} MB, so it is not read")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise SeatsUnread("encoding", "it is not saved as UTF-8 text") from None
    try:
        return jsonread.inbox_loads(text, unique=True)
    except (ValueError, RecursionError) as e:
        raise SeatsUnread("not-json", f"it is not valid JSON ({e})") from None

DRIVE = re.compile(r"[A-Za-z]:")
# Names Windows keeps for devices, as os.path.isreserved (3.13) knows them, superscript digits after COM and LPT included
DEVICES = frozenset({"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
                     *(f"{d}{n}" for d in ("COM", "LPT") for n in "123456789¹²³")})


def device(part: str) -> bool:
    """Whether a path part is a device name in the shape os.path.isreserved reads one: the device's name, then any
    spaces, then an extension or nothing ("nul", "con .txt", "aux  .d", "CONIN$ .x", "COM¹"), in any case."""
    return part.partition(".")[0].rstrip(" ").upper() in DEVICES
OTHER_USER = re.compile(r"~[^\\/]")   # ~name: another user's home, never expanded


def rooted(rel: str) -> bool:
    """Whether a path names its own start: a drive (D:\\x, or D:x), a root (\\Windows, /etc), or a share (\\\\srv\\x,
    //srv/x, \\\\?\\...), read the Windows way and the POSIX way alike, whatever this system is."""
    w = PureWindowsPath(rel)
    return bool(w.drive or w.root or PurePosixPath(rel).root)


def inexact(text: str) -> str | None:
    """Why a path, as a seats file writes it, would not be read as exactly the folder it names, or None (the first
    five refusals of the module's list)."""
    if any(unicodedata.category(c) in ("Cc", "Cs") for c in text):
        return "a path may not hold a control character or half of a surrogate pair"
    if text != text.strip():
        return (f"{text.strip()} is written with a space before or after it; a path is read exactly as written, so "
                f"write it without")
    if text[:4].replace("/", "\\") in ("\\\\?\\", "\\\\.\\"):
        return (f"{text} is written with the {text[:4]} prefix, which turns off the path's own reading; write the "
                f"path without it")
    parts = re.split(r"[\\/]", text)
    if any(p not in ("", ".", "..") and p[-1] in ". " for p in parts):
        return (f"{text} has a part ending in a dot or a space, which Windows reads as the part without it; write the "
                f"folder's name exactly")
    if ":" in (text[2:] if DRIVE.match(text) else text):
        return f"{text} holds a colon past a drive letter, which Windows reads as a stream of a folder, not a folder"
    if any(device(p) for p in parts):
        return (f"{text} has a part that is a device name, refused on every system because many Windows versions read "
                f"it as a device")
    return None


def base_of(value) -> tuple[str | None, str | None]:
    """A seats file's base folder, in full: (the path, None), or (None, why it cannot be). Read exactly as written
    (inexact); a leading "~" alone or "~/" is the user's home, "~name" is refused; and the path, once expanded, must be
    a full one. Whether the folder is there is home_base's question, not this one's."""
    if not isinstance(value, str) or not value.strip():
        return None, "the base folder is not given as a path"
    why = inexact(value)
    if why:
        return None, f"the base folder: {why}"
    if OTHER_USER.match(value):
        return None, f"the base folder {value} names another user's home; write it in full, or as ~/ for your own"
    if ".." in re.split(r"[\\/]", value):
        return None, f"the base folder {value} steps up with '..'; write the folder itself"
    full = Path(os.path.expanduser(value))
    if not full.is_absolute():
        return None, f"the base folder {value} is not a full path"
    return str(full), None


def home_base(value) -> tuple[str | None, str | None]:
    """The base the homes are joined to: base_of's judgement, and then the folder must be there. (None, why) when the
    seats file gives no base or one that is not an existing folder: then no seat's home is read, by any reader, and
    each says so once."""
    if value is None:
        return None, "the seats file gives no base folder, so no seat's home is read"
    full, why = base_of(value)
    if full is None:
        return None, f"{why}, so no seat's home is read"
    if not os.path.isdir(full):
        return None, f"the base folder {full} is not an existing folder, so no seat's home is read"
    return full, None


def under(base: str | None, rel) -> tuple[str | None, str | None]:
    """A folder as a seats file writes it, in full: (the path, None), or (None, why it cannot be). The one join of a
    seats file's homes and roots, for every reader. `base` is a base as base_of (or home_base) gives it.

    With a base, the path is put under it and must stay there: one that steps out with "..", or that names its own
    start (rooted: a drive, a root or a share) is refused, since joined to the base it would leave it (Path("C:\\seats")
    / "D:\\other" is D:\\other). With no base, the path must be written in full. Either way it is read exactly as
    written (inexact)."""
    if not isinstance(rel, str) or not rel.strip():
        return None, "has no path"
    if any(unicodedata.category(c) in ("Cc", "Cs") for c in rel) or rel != rel.strip():
        return None, inexact(rel)
    if ".." in re.split(r"[\\/]", rel):
        return None, f"a path may not step out with '..': {rel}"
    if base and rooted(rel):
        return None, (f"{rel} names a drive, a root or a share of its own, so it would leave the base folder; a path "
                      f"under the base is written without one")
    why = inexact(rel)
    if why:
        return None, why
    full = Path(base) / rel if base else Path(rel)
    if not full.is_absolute():
        return None, f"{rel} is not a full path, and the seats file gives no base folder to put it under"
    return str(full), None
