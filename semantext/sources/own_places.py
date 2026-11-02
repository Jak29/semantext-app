"""Projects and the map with no setup: what Semantext already knows, with no seats file.

A project is a name you gave (`semantext work project NAME`), a folder you bound to an agent, or a project an agent was
seen working in. An agent is one you bound or named, one the hook has seen, or one that filed a request in your inbox. This
reads those files and writes nothing.
A name that is only a name has no folder, so it has no gates and no documents to show.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePath

from .. import jsonread
from ..agents import Agents
from . import problem
from .own_inbox import load as own_inbox
from .places import _key, _node_id


def _named(home: Path, problems: list) -> list[str]:
    path = home / "work" / "projects.json"
    try:
        listed = jsonread.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, RecursionError) as e:
        problems.append(problem(path, None, "unreadable", f"your list of projects cannot be read ({type(e).__name__})"))
        return []
    return [x for x in listed if isinstance(x, str) and x.strip()] if isinstance(listed, list) else []


def load(home, name, group, problems: list) -> dict:
    """In the shape of places.load, with "own": True and one level: the whole. An agent's id and a project's come from
    what each is known by, so a link to either holds from one answer to the next."""
    home = Path(home)
    try:
        seen = Agents(home).overview()
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as e:   # a file edited by hand costs the agents it held, said
        seen = []
        problems.append(problem(home, None, "unreadable", f"the agents Semantext has seen cannot be read ({type(e).__name__})"))
    asked = [s["seat"] for s in own_inbox(home)["seats"]]
    spelled = {x.casefold(): x for x in asked}   # one agent, however its name was written: the cards' spelling is what they match
    seen = [{**a, "name": spelled.get(str(a["name"]).casefold(), str(a["name"]))} for a in seen]
    known = {a["name"] for a in seen}
    seen += [{"name": x} for x in asked if x not in known]
    projects: dict[str, dict] = {}

    def project(label: str, folder: str = "") -> dict:
        key = _key(folder) or label.casefold()
        if folder and label.casefold() in projects and not projects[label.casefold()]["path"]:
            named = projects[label.casefold()]   # the name you gave is this folder: one project
            named.update(path=folder, exists=Path(folder).is_dir())
            return named
        if key not in projects:
            projects[key] = {"id": _node_id("project", key), "name": label, "root": label, "path": folder, "kind": "own",
                             "exists": bool(folder) and Path(folder).is_dir(), "home_of": [], "members": [], "others": [],
                             "identity": {"path": None, "state": "absent", "entries": 0}}
        return projects[key]

    for label in _named(home, problems):
        project(label)
    agents = []
    for a in seen:
        who = str(a["name"])
        folders = [str(f) for f in a.get("folders") or []]
        me = {"id": _node_id("agent", who), "name": who, "other_names": [a["label"]] if isinstance(a.get("label"), str) and a["label"] else [], "groups": [],
              "emails": [], "home": folders[0] if folders else None, "sigils": [],
              "placed": {"group": None, "environment": None, "projects": []}}
        agents.append(me)
        places = [(PurePath(f).name or f, f, "bound") for f in folders]
        places += [(str(s["project"]), "", "seen") for s in a.get("sessions") or [] if isinstance(s.get("project"), str) and s["project"]]
        for label, folder, basis in places:
            p = project(label, folder)
            if not any(m["agent_id"] == me["id"] for m in p["members"]):
                p["members"].append({"agent_id": me["id"], "name": who, "basis": [basis], "emails": []})
                me["placed"]["projects"].append(p["id"])
    top = {"id": _node_id("whole", "own", str(home)), "kind": "whole", "name": name, "measured": None, "members": [], "children": []}
    return {"off": False, "own": True, "missing": [], "name": name, "group": group, "seats_file": None, "base": None,
            "agents": agents, "projects": list(projects.values()), "levels": top, "documents": [], "diffmaps": [], "map": {"off": True},
            "problems": problems}
