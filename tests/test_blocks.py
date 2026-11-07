"""The block format and its validator (B1): one fault anywhere and the folder loads nothing, the fault named.

Each must-refuse arm changes one thing in a space that, unchanged, loads (the control, test_a_good_space_loads).
"""
from __future__ import annotations

import pytest

from semantext import blocks

GOOD = {
    "space.yaml": "default: hold\nunknown_request_fields: refuse\n",
    "claude.yaml": (
        "id: claude\nkind: model\nprovider: anthropic\nmodel: claude-opus-5-5\n"
        "endpoint: https://api.anthropic.com\ncredential_host: api.anthropic.com\n"
        "tests:\n  - name: the vendor host only\n    given: {host: api.anthropic.com}\n    expect: pass\n"
    ),
    "bash.yaml": "id: bash\nkind: tool\nname: Bash\nruns_as: client\nruns_programs: true\ntests: []\n",
    "coder.yaml": (
        "id: coder\nkind: agent\nidentity: claude-code\nmodels: [claude]\ntools: [bash]\n"
        "budgets: {asks_open: 20}\ntests: []\n"
    ),
    "shell-held.yaml": (
        "id: shell-held\nkind: gate\nmatch: {tools: [bash]}\nanswer: [person]\non_timeout: refuse\n"
        "tests:\n  - name: a shell call waits\n    given: {tool: Bash}\n    expect: hold\n"
    ),
}


def space(tmp_path, changes=None, drop=()):
    for name, text in {**GOOD, **(changes or {})}.items():
        if name not in drop:
            (tmp_path / name).write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return tmp_path


def refused(folder, *words):
    """Loads nothing, and one named fault carries every one of `words`."""
    with pytest.raises(blocks.Fault) as e:
        blocks.load(folder)
    assert any(all(w in f for w in words) for f in e.value.faults), e.value.faults
    return e.value.faults


def test_a_good_space_loads(tmp_path):                                                  # the control
    s = blocks.load(space(tmp_path))
    assert set(s.blocks) == {"claude", "bash", "coder", "shell-held"}
    assert s.settings["default"] == "hold"
    assert s.blocks["coder"]["budgets"] == {"asks_open": 20}
    assert s.blocks["bash"]["runs_programs"] is True
    assert len(s.digest) == 64 and s.digest == blocks.digest(tmp_path)


def test_the_digest_moves_with_any_byte(tmp_path):
    before = blocks.load(space(tmp_path)).digest
    (tmp_path / "bash.yaml").write_text(GOOD["bash.yaml"] + "\n", encoding="utf-8")
    assert blocks.load(tmp_path).digest != before


# ---- the strict reader ----
@pytest.mark.parametrize("text,words", [
    ("id: &a bash\nkind: tool\n", ("anchor",)),
    ("id: bash\nkind: tool\nname: *a\n", ("alias", "not allowed")),
    ("id: bash\nkind: tool\nkind: tool\n", ("given twice",)),
    ("id: bash\n? [a, b]\n: x\n", ("not text",)),
    ("id: !!int 5\n", ("tag",)),
    ("id: !!python/object:os.system x\n", ("tag",)),
    ("id: !!binary aGk=\n", ("tag",)),
    ("id: !custom x\n", ("tag",)),
    ("id: bash\nkind: tool\nname: ~\n", ("null",)),
    ("id: bash\nkind: tool\nname:\n", ("null",)),
])
def test_the_reader_refuses_what_yaml_reads_in_silence(tmp_path, text, words):        # must-refuse
    refused(space(tmp_path, {"bash.yaml": text}), "bash.yaml", *words)


def test_yaml_1_1_booleans_floats_and_dates_stay_text_and_then_fail_their_type(tmp_path):   # must-refuse
    text = "id: bash\nkind: tool\nname: Bash\nruns_as: client\nruns_programs: yes\ntests: []\n"
    refused(space(tmp_path, {"bash.yaml": text}), "runs_programs", "true or false")
    text = GOOD["coder.yaml"].replace("asks_open: 20", "asks_open: 1.5")
    refused(space(tmp_path, {"coder.yaml": text}), "asks_open", "whole number")
    text = GOOD["coder.yaml"].replace("asks_open: 20", "asks_open: 2026-11-03")
    refused(space(tmp_path, {"coder.yaml": text}), "asks_open", "whole number")


def test_a_quoted_number_is_text(tmp_path):                                             # must-refuse
    text = GOOD["coder.yaml"].replace("asks_open: 20", "asks_open: '20'")
    refused(space(tmp_path, {"coder.yaml": text}), "asks_open", "whole number")


def test_true_is_not_a_number(tmp_path):                                                # must-refuse
    text = GOOD["coder.yaml"].replace("asks_open: 20", "asks_open: true")
    refused(space(tmp_path, {"coder.yaml": text}), "asks_open", "whole number")


def test_a_negative_number_is_refused(tmp_path):                                        # must-refuse
    text = GOOD["coder.yaml"].replace("asks_open: 20", "asks_open: -1")
    refused(space(tmp_path, {"coder.yaml": text}), "asks_open")


def test_over_the_size_cap_is_not_parsed(tmp_path):                                     # must-refuse
    text = GOOD["bash.yaml"] + "# " + "x" * blocks.MAX_FILE + "\n"
    refused(space(tmp_path, {"bash.yaml": text}), "bash.yaml", "over")


def test_not_utf8(tmp_path):                                                            # must-refuse
    refused(space(tmp_path, {"bash.yaml": b"id: b\xffash\n"}), "bash.yaml", "UTF-8")


# ---- the folder ----
def test_a_file_that_is_not_yaml_is_a_fault(tmp_path):                                  # must-refuse
    refused(space(tmp_path, {"README.md": "notes"}), "README.md", "belong")


def test_a_subfolder_is_a_fault(tmp_path):                                              # must-refuse
    (space(tmp_path) / "inner").mkdir()
    refused(tmp_path, "inner", "plain file")


def test_the_space_file_is_required(tmp_path):                                          # must-refuse
    refused(space(tmp_path, drop=("space.yaml",)), "space.yaml", "missing")


@pytest.mark.parametrize("text,words", [
    ("unknown_request_fields: refuse\n", ("missing", "default")),
    ("default: open\n", ("default", "one of")),
    ("default: hold\nplugins: [x]\n", ("unknown field", "plugins")),
])
def test_the_space_file_is_checked(tmp_path, text, words):                              # must-refuse
    refused(space(tmp_path, {"space.yaml": text}), "space.yaml", *words)


def test_one_bad_file_loads_nothing(tmp_path):                                          # must-refuse
    with pytest.raises(blocks.Fault) as e:
        blocks.load(space(tmp_path, {"zzz.yaml": "id: zzz\nkind: teleport\ntests: []\n"}))
    assert len(e.value.faults) == 1                                                     # only that one is named


# ---- the blocks ----
@pytest.mark.parametrize("name,text,words", [
    ("bash.yaml", "id: bash\nname: Bash\ntests: []\n", ("missing field 'kind'",)),
    ("bash.yaml", "id: bash\nkind: teleport\ntests: []\n", ("unknown kind", "teleport")),
    ("bash.yaml", "id: bash\nkind: tool\nname: Bash\nruns_as: client\n", ("missing field 'tests'",)),
    ("bash.yaml", "id: bash\nkind: tool\nruns_as: client\ntests: []\n", ("missing field 'name'",)),
    ("bash.yaml", "id: bash\nkind: tool\nname: Bash\nruns_as: client\ntests: []\nserver_side: true\n",
     ("unknown field", "server_side")),
    ("bash.yaml", "id: bash\nkind: tool\nname: Bash\nruns_as: vendor\ntests: []\n", ("runs_as", "one of")),
    ("coder.yaml", GOOD["coder.yaml"].replace("asks_open: 20", "asks_open: 20, open: true"),
     ("unknown field", "budgets.open")),
    ("shell-held.yaml", GOOD["shell-held.yaml"].replace("on_timeout: refuse", "on_timeout: allow"),
     ("on_timeout", "one of")),
    ("shell-held.yaml", GOOD["shell-held.yaml"].replace("expect: hold", "expect: maybe"), ("expect", "one of")),
    ("shell-held.yaml", GOOD["shell-held.yaml"].replace("answer: [person]", "answer: person"), ("answer", "list")),
    ("bash.yaml", "id: Bash\nkind: tool\nname: Bash\nruns_as: client\ntests: []\n", ("id must be",)),
])
def test_a_block_with_a_fault(tmp_path, name, text, words):                             # must-refuse
    refused(space(tmp_path, {name: text}), name, *words)


@pytest.mark.parametrize("field", ["locked: false", "owner: agent"])
def test_locks_and_owners_are_never_read_from_a_block(tmp_path, field):                 # must-refuse (A1)
    refused(space(tmp_path, {"bash.yaml": GOOD["bash.yaml"] + field + "\n"}), "bash.yaml", "never read")


def test_the_file_is_named_after_its_id(tmp_path):                                      # must-refuse
    refused(space(tmp_path, {"other.yaml": GOOD["bash.yaml"]}), "other.yaml", "bash.yaml")


def test_a_dangling_referent_refuses_to_load(tmp_path):                                 # must-refuse (G14)
    refused(space(tmp_path, drop=("bash.yaml",)), "coder.yaml", "bash", "no tool block")


def test_a_referent_of_the_wrong_kind_refuses(tmp_path):                                # must-refuse
    text = GOOD["coder.yaml"].replace("tools: [bash]", "tools: [claude]")
    refused(space(tmp_path, {"coder.yaml": text}), "coder.yaml", "claude", "no tool block")
