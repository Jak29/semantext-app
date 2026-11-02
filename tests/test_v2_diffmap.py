"""The Diffmap place: the change specs agents keep in cv/<project>/diffmap/, listed, read, and each given the command that
opens it in the viewer, built from the person's diffmap_command (Jak's pick, I-20261102-114114 option 3).

Every check has a must-pass arm and a must-refuse arm: a spec is listed, read and given its command; a name the
launcher would not take gets no command, a bad template gives none to anyone, a spec outside a diffmap folder or of
another group is not listed, and a read that is not a listed spec is refused. Nothing is run.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from semantext.sources import gates, places, view
from semantext.sources.gates import World as GitWorld
from test_v2_view import World, touch
from v2_node import NODE, run

SPEC = """# The Pele CRLF fix

Why it changed. <b>not bold</b>

## Phase 1: the test's CRLF step
```mermaid diff [How the self-test builds the CRLF shim]
 flowchart LR
   R["The shim's bytes"] --> C["The CRLF step"]
-  C --> D["Every LF becomes CRLF"]
+  C --> D["Read as LF first, then every LF becomes CRLF"]
```
```changes
4b18cc6..2f73969
tools/pele_draw.py
```
"""
LAUNCH = r"python C:\Tools\diffmap\trial.py serve {name}"


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    specs = w.base / "alder" / "cv" / "notes" / "diffmap"
    touch(specs / "pele-crlf.md", SPEC)
    touch(specs / "Bad Name.md", "# A spec the launcher cannot be given\n")
    touch(specs / "notes.txt", "not a spec\n")
    touch(specs / ".hidden.md", "# hidden\n")
    touch(w.base / "alder" / "cv" / "notes" / "loose.md", "# beside the diffmap folder, a document\n")
    touch(w.base / "alder" / "cv" / "solo" / "diffmap" / "only-specs.md", "# A project with specs and no MASTER.md\n")
    touch(w.base / "dune" / "cv" / "guest" / "diffmap" / "guest-spec.md", "# Dune's, outside the group\n")
    monkeypatch.setenv("SEMANTEXT_SOURCES", str(w.config))
    user = tmp_path / "git-user"
    user.mkdir()
    monkeypatch.setattr(gates, "this_machine", lambda env=None: GitWorld({}, user, (), (), ()))
    w.specs = specs
    return w


def listed(**change):
    return view.answer("diffmap")


def by_stem(got) -> dict:
    return {s["stem"]: s for s in got["specs"]}


# ---------------------------------------------------------------- the list
def test_every_spec_in_a_diffmap_folder_is_listed_with_its_title(world):
    got = view.answer("diffmap")
    assert got["place"] == "diffmap" and got["off"] is False
    specs = by_stem(got)
    assert set(specs) == {"pele-crlf", "Bad Name", "only-specs"}              # Dune is outside the group
    assert specs["pele-crlf"]["title"] == "The Pele CRLF fix" and specs["pele-crlf"]["agent"] == "Alder"
    assert specs["pele-crlf"]["slug"] == "notes" and specs["only-specs"]["slug"] == "solo"   # no MASTER.md needed
    assert specs["pele-crlf"]["project_name"] == "Alder home"
    # must-refuse: a .txt, a hidden file and a document beside the folder are not specs; the Documents place is unchanged
    assert not {"notes", ".hidden", "loose"} & set(specs)
    assert [d["slug"] for d in view.answer("documents")["documents"]] == ["notes"]


def test_a_spec_folder_that_is_a_file_or_missing_lists_nothing(world):
    os.remove(world.specs / "pele-crlf.md")
    os.remove(world.specs / "Bad Name.md")
    assert "pele-crlf" not in by_stem(view.answer("diffmap"))
    # must-refuse: a file called diffmap is not a folder of specs
    touch(world.base / "alder" / "cv" / "flat" / "diffmap", "# not a folder\n")
    assert all(s["slug"] != "flat" for s in view.answer("diffmap")["specs"])


@pytest.mark.skipif(os.name != "nt", reason="a junction is how a Windows folder links elsewhere")
def test_a_diffmap_folder_that_is_a_link_is_not_followed(world, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    touch(elsewhere / "planted.md", "# planted\n")
    link = world.base / "alder" / "cv" / "linked" / "diffmap"
    link.parent.mkdir(parents=True)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(elsewhere)], check=True, capture_output=True)
    got = view.answer("diffmap")
    assert "planted" not in by_stem(got)                                         # must-refuse
    assert "pele-crlf" in by_stem(got)                                           # must-pass beside it


# ---------------------------------------------------------------- the command
def test_the_command_is_built_from_the_template_for_a_name_the_launcher_takes(world):
    world.write_config(diffmap_command=LAUNCH, diffmap_note="not yet built")
    got = view.answer("diffmap")
    specs = by_stem(got)
    assert specs["pele-crlf"]["command"] == r"python C:\Tools\diffmap\trial.py serve pele-crlf"
    assert got["note"] == "not yet built" and got["template_problem"] is None
    # must-refuse: a stem with a space or capitals is never handed to the launcher
    assert specs["Bad Name"]["command"] is None and "a-z" in specs["Bad Name"]["no_command"]


def test_with_no_template_no_spec_has_a_command_and_says_why(world):
    specs = by_stem(view.answer("diffmap"))
    assert specs["pele-crlf"]["command"] is None
    assert "no diffmap_command" in specs["pele-crlf"]["no_command"]


@pytest.mark.parametrize("bad", ["python serve", "serve {name} {name}", "serve {name}\nrm -rf /", "x" * 400 + "{name}",
                                 ["serve {name}"], 5])
def test_a_template_that_is_not_one_line_with_name_once_gives_no_command(world, bad):
    world.write_config(diffmap_command=bad)
    got = view.answer("diffmap")
    assert all(s["command"] is None for s in got["specs"])                      # must-refuse, for every spec
    assert got["template_problem"]


def test_a_stem_is_checked_by_the_launcher_rule_exactly():
    for good in ("a", "pele-crlf", "x" * 40, "0-9"):
        assert places.STEM.fullmatch(good), good
    for bad in ("", "x" * 41, "Pele", "a b", "a_b", "a.b", "../a", "a/b", "é", "a\n"):
        assert not places.STEM.fullmatch(bad), bad


# ---------------------------------------------------------------- one spec, read
def test_a_listed_spec_is_read_as_its_text(world):
    s = by_stem(view.answer("diffmap"))["pele-crlf"]
    got = view.document(s["folder"], "pele-crlf.md")
    assert got["kind"] == "spec" and got["text"] == SPEC and got["title"] == "The Pele CRLF fix"
    assert "<b>not bold</b>" in got["text"]                                     # as written; the page sets it as text


def test_a_read_that_is_not_a_listed_spec_is_refused(world):
    s = by_stem(view.answer("diffmap"))["pele-crlf"]
    folder = s["folder"]
    with pytest.raises(view.DocumentRefused) as e:
        view.document(folder, "notes.txt")
    assert e.value.status == 400                                                # only .md and .svg are ever read
    for file in ("missing.md", "loose.md", "flow.svg"):
        with pytest.raises(view.DocumentRefused) as e:
            view.document(folder, file)
        assert e.value.status == 404, file
    for file in ("../loose.md", "..\\MASTER.md", "../../secret.md", ".hidden.md", str(world.specs / "pele-crlf.md")):
        with pytest.raises(view.DocumentRefused) as e:
            view.document(folder, file)
        assert e.value.status == 400, file
    # a document folder's id never opens a spec, and a spec folder's id never opens the document beside it
    doc = view.answer("documents")["documents"][0]["id"]
    with pytest.raises(view.DocumentRefused):
        view.document(doc, "pele-crlf.md")
    with pytest.raises(view.DocumentRefused):
        view.document(folder, "MASTER.md")


# ---------------------------------------------------------------- the page draws it
@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_page_lists_a_spec_and_draws_it_as_text_with_its_command(world):
    world.write_config(diffmap_command=LAUNCH, diffmap_note="not yet built")
    data = view.answer("diffmap")
    s = by_stem(data)["pele-crlf"]
    js = """
const DATA = %s, SPEC = %s, s = %s;
S.data.diffmap = DATA; S.place = "diffmap"; S.sub = null; mount(); fill();
const list = $("place").textContent;
M.text.set(s.folder + "/" + s.file + "@" + s.updated, { text: SPEC });
S.sub = s.folder + "/" + s.file; mount(); fill();
const place = $("place");
const cls = (c) => place.all((e) => e.className === c).map((e) => e.textContent);
report({ list, detail: place.textContent, add: cls("add"), del: cls("del"), bold: place.all((e) => e.tagName === "B").length,
  parts: specParts(SPEC).map((p) => p.kind), code: place.all((e) => e.className === "command").map((e) => e.textContent) });
""" % (json.dumps(data), json.dumps(SPEC), json.dumps(s))
    got = run(js)
    assert "The Pele CRLF fix" in got["list"] and "no command" in got["list"]          # Bad Name has none
    assert got["code"] == [r"python C:\Tools\diffmap\trial.py serve pele-crlf"] and "not yet built" in got["detail"]
    assert got["parts"] == ["prose", "diagram", "changes"]
    assert got["add"] == ['+  C --> D["Read as LF first, then every LF becomes CRLF"]\n']
    assert got["del"] == ['-  C --> D["Every LF becomes CRLF"]\n']
    assert "4b18cc6..2f73969" in got["detail"] and "tools/pele_draw.py" in got["detail"]
    # must-refuse: HTML written in a spec stays text, never markup
    assert got["bold"] == 0 and "<b>not bold</b>" in got["detail"]

# ---------------------------------------------------------------- what the attack on 5a7ecfa found
def test_a_hard_linked_spec_is_left_out_and_its_heading_never_shown(world, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# SECRET HEADING\n", encoding="utf-8")
    os.link(outside, world.specs / "hl.md")
    got = view.answer("diffmap")
    assert "hl" not in by_stem(got)                                                  # must-refuse
    assert "SECRET HEADING" not in json.dumps(got)
    assert "pele-crlf" in by_stem(got)                                               # must-pass beside it


def test_a_hard_linked_document_is_left_out_too(world, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text("# OUTSIDE HEADING\n", encoding="utf-8")
    notes = world.base / "alder" / "cv" / "notes"
    os.link(outside, notes / "hl.md")
    got = view.answer("documents")
    assert "OUTSIDE HEADING" not in json.dumps(got)                                  # must-refuse
    assert [x["file"] for x in got["documents"][0]["docs"]] == ["loose.md", "part.md"]   # must-pass: the rest still listed


def test_a_stem_starting_with_a_dash_gets_no_command(world):
    touch(world.specs / "--help.md", "# Reads as an option\n")
    touch(world.specs / "-rf.md", "# Reads as an option too\n")
    world.write_config(diffmap_command=LAUNCH)
    specs = by_stem(view.answer("diffmap"))
    assert specs["--help"]["command"] is None and specs["-rf"]["command"] is None   # must-refuse
    assert specs["pele-crlf"]["command"].endswith("serve pele-crlf")                 # must-pass
    assert places.STEM.fullmatch("a-") and places.STEM.fullmatch("9") and not places.STEM.fullmatch("-a")


@pytest.mark.parametrize("bad", ["a {name}\u2028b", "a {name}\u2029b", "a \u202e{name}", "a {name}\u200b", "a\ufeff {name}"])
def test_a_template_with_a_hidden_line_or_direction_mark_gives_no_command(world, bad):
    world.write_config(diffmap_command=bad)
    got = view.answer("diffmap")
    assert all(s["command"] is None for s in got["specs"]) and got["template_problem"]

def test_a_spec_title_keeps_no_format_character(world):
    touch(world.specs / "bidi.md", "# Safe \u202echange\u200b\n")
    specs = by_stem(view.answer("diffmap"))
    assert specs["bidi"]["title"] == "Safe change"                                        # N5: must-refuse
    assert specs["pele-crlf"]["title"] == "The Pele CRLF fix"                             # must-pass