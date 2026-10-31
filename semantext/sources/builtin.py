"""The built-in sources and checker, registered as plug-ins exactly as an outside one is (docs/plugin-api.md,
"Kinds": the built-ins are plug-ins too, so the way in is proven by use). The built-in places are added beside them
in view.py, where they are written.

Each source names the keys of the sources file it reads, and the ones it cannot be on without; the keys the config
keeps are the frame's own and every built-in source's, so a new reader adds its keys here and nowhere else. A reader's
module is imported when it is first read, so asking which keys exist imports no reader.
"""
from __future__ import annotations

from importlib import import_module

from ..registry import Registry

FRAME_KEYS = ("name", "group", "gaming", "game_folders", "inbox_app")   # read by the frame itself: the person's word, the group, the gaming flag


class Reader:
    """A built-in source: one module of this package with a load(config) function."""

    kind = "source"

    def __init__(self, name: str, title: str, module: str, keys: tuple, needs: tuple):
        self.name, self.title, self._module, self.keys, self.needs = name, title, module, keys, needs

    @property
    def module(self):
        return import_module(f"{__package__}.{self._module}")

    def read(self, config: dict, world=None) -> dict:
        """The reader's answer. The gates reader alone takes a stand-in for this machine's git settings (the tests')."""
        if world is not None and self._module == "gates":
            return self.module.load(config, world)
        return self.module.load(config)


class Guards:
    """The guards file the rules reader reads. It names what should have a run record; it is not one (the ecosystem
    review, section 2), so it has no records and makes no rule guarded."""

    kind = "checker"
    name = "guards"
    title = "the guards file"
    records = None


class Runs:
    """The built-in Checker reader: the run records a checker outside the package leaves, read by runs.py (schema 1).
    A valid, fresh record is the one thing that makes a rule guarded."""

    kind = "checker"
    name = "runs"
    title = "run records"
    records = "runs/<checker>.jsonl under each folder the sources file lists in run_records"

    def read(self, config: dict) -> dict:
        return import_module(f"{__package__}.runs").read(config)


# In the order the page has always read them: an answer's problems keep that order.
SOURCES = (
    Reader("waiting", "Waiting", "cards", ("seats", "group", "requests", "changes", "inbox"), ("seats", "inbox")),
    Reader("record", "Record", "record", ("register", "notes"), ("register",)),
    Reader("rules", "Rules", "rules", ("cards", "guards", "run_records", "run_record_days"), ("cards",)),
    Reader("gates", "Gates", "gates", ("seats", "group"), ("seats",)),
    Reader("places", "Places", "places", ("seats", "map", "name", "group"), ("seats", "map")),
    # The work store lies in the Semantext home, so no key turns it on; the register gives its parked decisions, and
    # the cards, run records and verdicts files the evidence its clauses are judged on (slice 2b).
    Reader("work", "Work", "work", ("seats", "group", "register", "notes", "cards", "run_records", "run_record_days",
                                    "verdicts", "pieces"), ()),
)


def registry() -> Registry:
    """A new registry holding the built-in sources and checker."""
    reg = Registry()
    for s in SOURCES:
        reg.add("source", s.name, s)
    reg.add("checker", Guards.name, Guards())
    reg.add("checker", Runs.name, Runs())
    return reg


def config_keys() -> tuple[str, ...]:
    """Every key the sources file may give: the frame's, then each built-in source's, each once."""
    return tuple(dict.fromkeys(FRAME_KEYS + tuple(k for s in SOURCES for k in s.keys)))
