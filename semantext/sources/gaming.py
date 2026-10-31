"""Gaming: whether the person's inbox says they are gaming, read from its flag and never written.

An "I'm gaming" switch writes gaming.json: `semantext compute hold` in your Semantext home, or an inbox app's own button
in its folder. This reader reads that flag, and nothing more: it never writes the file, and does not look at the running
programs or the screen, which the compute monitor (compute.py) does. So it answers only what the switch said.

    on        the flag's "on" is true itself, and its "until_epoch" is a number later than now: on until then
    off       there is no file, or it is lowered, or it has no end time, or its end time has come
    unknown   the file cannot be read, is not JSON, is not a JSON object, or ends further off than the button's six
              hours (gaming.py refuses that as unreadable, since such a flag would hold work until someone edited it)

The file is the config's "gaming" key, or gaming.json in its "inbox" folder when that key is missing, or gaming.json in
the Semantext home. With none of them, the reader is off.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

from .. import jsonread

FILE = "gaming.json"
LAPSE_S = 6 * 3600   # the button's own lapse, as gaming.py has it
SLACK_S = 600        # gaming.py's allowance past the lapse before an end time is unreadable
MAX_BYTES = 64 * 1024


def path_of(cfg: dict) -> Path | None:
    """The flag's file: the "gaming" key, else gaming.json in the "inbox" folder, else in the home, else None."""
    named = cfg.get("gaming") if isinstance(cfg, dict) else None
    if isinstance(named, str) and named.strip():
        return Path(named.strip()).expanduser()
    inbox = cfg.get("inbox") if isinstance(cfg, dict) else None
    if isinstance(inbox, str) and inbox.strip():
        return Path(inbox.strip()).expanduser() / FILE
    home = cfg.get("_home") if isinstance(cfg, dict) else None
    if isinstance(home, str) and home.strip():
        return Path(home.strip()).expanduser() / FILE
    return None


def _unknown(path, why: str) -> dict:
    return {"off": False, "state": "unknown", "file": str(path), "why": why[:300]}


def load(cfg: dict, now: float | None = None) -> dict:
    """{"state": "on" | "off" | "unknown", "file", ...}: with "until" and "until_epoch" (and "since") when on, and
    "why" when unknown. {"off": True, "state": "off"} when no file can be named."""
    now = time.time() if now is None else now
    path = path_of(cfg)
    if path is None:
        return {"off": True, "state": "off", "file": None, "missing": ["gaming"]}
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return {"off": False, "state": "off", "file": str(path)}
    except (OSError, ValueError) as e:
        return _unknown(path, f"the gaming flag cannot be read: {getattr(e, 'strerror', None) or e}")
    if len(raw) > MAX_BYTES:
        return _unknown(path, "the gaming flag is too large to be the inbox's")
    try:
        g = jsonread.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError) as e:
        return _unknown(path, f"the gaming flag is not readable: {e}")
    if not isinstance(g, dict):
        return _unknown(path, "the gaming flag is not readable: not an object")
    until = g.get("until_epoch")
    if g.get("on") is True and isinstance(until, (int, float)) and now < until:
        if not math.isfinite(until) or until > now + LAPSE_S + SLACK_S:
            return _unknown(path, f"the gaming flag's end time is not within {LAPSE_S // 3600} hours")
        return {"off": False, "state": "on", "file": str(path), "until_epoch": until,
                "until": g.get("until") if isinstance(g.get("until"), str) else None,
                "since": g.get("since") if isinstance(g.get("since"), str) else None}
    return {"off": False, "state": "off", "file": str(path)}
