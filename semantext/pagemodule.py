"""Page modules: the one ES module an enabled outside place may ship, and how the server finds it.

ECOSYSTEM.md names a Place as build(sources) "plus one page module render(data, el) using the shared text-only DOM
helpers". The smallest safe shape of that:

  - The plug-in's Place object declares `page_module`: a path to a .js file, relative, written with forward slashes,
    exactly as it appears among its own distribution's installed files (importlib.metadata's RECORD). Nothing else is
    ever served: not a path from the request, not a file the distribution does not list, not one whose real path lies
    outside the folder the distribution is installed in.
  - The server serves it at /v2/plugin/<place name>.js, only for a place the person turned on (registry.load_enabled),
    with the page's own Content-Security-Policy, so it can import nothing from another site. A place name that is not
    a plain word (NAME) gets no module, since it could not be told apart from a path.
  - The page imports it when you go to that place and calls render(data, el, helpers) (static/v2/outside.js).

A page module is code in the person's browser, on their page, as a plug-in's Python is code in their process: the
helpers make setting text as text the easy way, and nothing here can make it the only way (SECURITY.md, "Plug-ins").
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from . import registry

NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")   # a place name the page may ask a module for
MAX_MODULE = 1024 * 1024                          # bytes; a larger module is not served
PREFIX = "/v2/plugin/"


class NoModule(Exception):
    """Why a place has no module to serve; the server answers 404 with it."""


def url(name: str) -> str:
    return f"{PREFIX}{name}.js"


def _declared(entry) -> str:
    path = getattr(entry.obj, "page_module", None)
    if path is None:
        raise NoModule(f"the place {entry.name} ships no page module")
    if (not isinstance(path, str) or not path.endswith(".js") or path != path.strip() or "\\" in path or ":" in path
            or "\x00" in path or path.startswith("/")):
        raise NoModule(f"the place {entry.name} names its page module as {str(path)[:80]!r}, which is not a relative "
                       f"path to a .js file written with forward slashes")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise NoModule(f"the place {entry.name} names its page module with an empty, . or .. part")
    return path


def locate(entry) -> Path:
    """The file an enabled outside place's page module is, or NoModule with the reason."""
    if entry is None or entry.kind != "place":
        raise NoModule("no place of that name is turned on")
    if entry.builtin:
        raise NoModule("a built-in place's modules are the page's own")
    if not NAME.fullmatch(entry.name):
        raise NoModule(f"the place name {entry.name[:80]!r} is not a plain word, so it gets no module")
    path = _declared(entry)
    dist = entry.dist
    files = getattr(dist, "files", None) if dist is not None else None
    if not files:
        raise NoModule(f"{entry.origin} lists no installed files, so its page module cannot be found among them")
    if path not in {str(f).replace("\\", "/") for f in files}:
        raise NoModule(f"{path} is not among the files {entry.origin} installed")
    base = os.path.realpath(str(dist.locate_file("")))
    found = os.path.realpath(str(dist.locate_file(path)))
    if not (found == base or found.startswith(base.rstrip("\\/") + os.sep)):
        raise NoModule(f"{path} resolves outside the folder {entry.origin} is installed in")
    return Path(found)


def offers(entry) -> bool:
    try:
        locate(entry)
        return True
    except NoModule:
        return False


def read(entry) -> bytes:
    """The module's bytes, or NoModule with the reason."""
    where = locate(entry)
    try:
        with open(where, "rb") as f:
            data = f.read(MAX_MODULE + 1)
    except OSError as e:
        raise NoModule(f"the page module could not be read ({type(e).__name__})") from None
    if len(data) > MAX_MODULE:
        raise NoModule(f"the page module is over {MAX_MODULE // 2**20} MiB, so it is not served")
    return data
