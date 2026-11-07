"""The request gate (PROXY-DESIGN r4: section 3 steps 4 and 5, D1, T5, T13, T14).

Each must-refuse arm changes one thing in a request that, unchanged, passes (the control).
"""
from __future__ import annotations

import copy

import pytest

from semantext import blocks, gate_request
from semantext.assemble import Refused
from tests.test_blocks import GOOD


def space_of(tmp_path, settings="default: hold\n"):
    for name, text in {**GOOD, "space.yaml": settings}.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    return blocks.load(tmp_path)


REQ = {
    "model": "claude-opus-5-5", "max_tokens": 1024, "stream": True,
    "system": [{"type": "text", "text": "attribution", "cache_control": {"type": "ephemeral"}}],
    "messages": [
        {"role": "user", "content": "list the files"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Bash",
                                           "input": {"command": "ls", "anything": {"deep": [1]}}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": [
            {"type": "text", "text": "a b"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                                          "data": "aGk="}}]}]},
    ],
    "tools": [{"name": "Bash", "description": "run", "input_schema": {"type": "object", "x-anything": True}},
              {"type": "text_editor_20250728", "name": "str_replace_based_edit_tool"}],
    "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}, "metadata": {"user_id": "u"},
}


def ok(tmp_path, body=None, settings="default: hold\n"):
    return gate_request.check(body or copy.deepcopy(REQ), space_of(tmp_path, settings), "coder")


def refused(tmp_path, body, rule, *words, settings="default: hold\n"):
    with pytest.raises(Refused) as e:
        gate_request.check(body, space_of(tmp_path, settings), "coder")
    assert e.value.rule == rule and all(w in e.value.reason for w in words), e.value
    return e.value


def changed(**kw):
    body = copy.deepcopy(REQ)
    for path, value in kw.items():
        body[path] = value
    return body


def test_a_plain_request_passes(tmp_path):                                              # the control
    c = ok(tmp_path)
    assert c.recorded == [] and c.unknown == []


# ---- fields (D1, T5) ----
@pytest.mark.parametrize("body,words", [
    (changed(web_search_options={}), ("web_search_options",)),
    (changed(functions=[]), ("functions",)),
    (changed(thinking={"type": "adaptive", "server_side": True}), ("server_side",)),
    (changed(output_config={"effort": "high", "egress": "x"}), ("egress",)),
])
def test_an_unknown_field_or_nested_key_is_refused_and_named(tmp_path, body, words):    # must-refuse (RQ-1, RQ-3)
    refused(tmp_path, body, "X-FIELD", *words)


def test_an_unknown_key_in_a_tool_entry(tmp_path):                                      # must-refuse (RQ-3)
    body = copy.deepcopy(REQ)
    body["tools"][0]["server_side"] = True
    refused(tmp_path, body, "X-FIELD", "server_side")


def test_an_unknown_key_in_a_block(tmp_path):                                           # must-refuse
    body = copy.deepcopy(REQ)
    body["messages"][0]["content"] = [{"type": "text", "text": "x", "fetch": "http://a"}]
    refused(tmp_path, body, "X-FIELD", "fetch")


def test_an_unknown_block_type_in_a_message(tmp_path):                                  # must-refuse
    body = copy.deepcopy(REQ)
    body["messages"][0]["content"] = [{"type": "search_result", "source": "x"}]
    refused(tmp_path, body, "X-FIELD", "search_result")


def test_a_field_name_in_an_error_is_capped(tmp_path):                                  # D7
    e = refused(tmp_path, changed(**{"x" * 70000: 1}), "X-FIELD")
    assert len(e.reason) < 200


def test_the_person_can_add_a_field(tmp_path):                                          # control for RQ-1
    c = ok(tmp_path, changed(web_search_options={}),
           settings="default: hold\nextra_fields: [web_search_options]\n")
    assert c.unknown == []


def test_an_ungated_space_passes_unknown_fields_and_records_them(tmp_path):            # RQ-4
    (tmp_path / "g").mkdir()
    for name, text in {**GOOD, "space.yaml": "default: pass\n"}.items():
        if name != "shell-held.yaml":
            (tmp_path / "g" / name).write_text(text, encoding="utf-8")
    space = blocks.load(tmp_path / "g")
    assert not gate_request.gated(space)
    got = gate_request.check(changed(new_field=1), space, "coder")
    assert got.unknown == ["new_field"]


def test_a_hold_default_with_no_gate_block_is_still_gated(tmp_path):                   # T5
    for name, text in {**GOOD, "space.yaml": "default: hold\n"}.items():
        if name != "shell-held.yaml":
            (tmp_path / name).write_text(text, encoding="utf-8")
    space = blocks.load(tmp_path)
    assert not space.of("gate") and gate_request.gated(space)
    with pytest.raises(Refused):
        gate_request.check(changed(new_field=1), space, "coder")


def test_an_unknown_key_on_a_message(tmp_path):                                         # must-refuse
    body = copy.deepcopy(REQ)
    body["messages"][0]["name"] = "admin"
    refused(tmp_path, body, "X-FIELD", "name")


def test_a_pass_default_with_a_gate_block_is_still_gated(tmp_path):                    # T5
    refused(tmp_path, changed(new_field=1), "X-FIELD", "new_field", settings="default: pass\n")


# ---- vendor-side work (D1, J7) ----
@pytest.mark.parametrize("body,words", [
    (changed(mcp_servers=[{"type": "url", "url": "https://x", "name": "x"}]), ("mcp_servers",)),
    (changed(container={"skills": []}), ("container",)),
])
def test_vendor_side_fields_are_refused(tmp_path, body, words):                         # must-refuse
    refused(tmp_path, body, "X-REQ", *words)


@pytest.mark.parametrize("kind", ["web_search_20260209", "web_fetch_20260209", "code_execution_20260521",
                                  "tool_search_tool_regex_20251119", "mcp_toolset"])
def test_a_server_tool_is_refused(tmp_path, kind):                                      # must-refuse
    body = copy.deepcopy(REQ)
    body["tools"].append({"type": kind, "name": "x"})
    refused(tmp_path, body, "X-REQ", "vendor runs")


def test_an_unknown_tool_type_is_refused(tmp_path):                                     # must-refuse
    body = copy.deepcopy(REQ)
    body["tools"].append({"type": "made_up_tool_2099", "name": "x"})
    refused(tmp_path, body, "X-REQ", "made_up_tool_2099")


@pytest.mark.parametrize("where", ["top", "tool_result", "system"])
@pytest.mark.parametrize("src", [{"type": "url", "url": "http://10.0.0.1/x.png"}, {"type": "file", "file_id": "f"}])
def test_a_source_the_vendor_fetches_is_refused_at_any_depth(tmp_path, where, src):    # must-refuse (RQ-2, J7)
    block = {"type": "image", "source": src}
    body = copy.deepcopy(REQ)
    if where == "top":
        body["messages"][0]["content"] = [block]
    elif where == "tool_result":
        body["messages"][2]["content"][0]["content"].append(block)
    else:
        body["system"].append(block)
    refused(tmp_path, body, "X-REQ", "fetches")


def test_the_space_may_record_vendor_work_instead(tmp_path):                            # control
    body = copy.deepcopy(REQ)
    body["tools"].append({"type": "web_search_20260209", "name": "web_search"})
    c = ok(tmp_path, body, settings="default: hold\nvendor_side: record\n")
    assert c.recorded == ["the tool web_search_20260209"]


# ---- model and agent (T13) ----
@pytest.mark.parametrize("name", ["claude-opus-5-5 ", "Claude-Opus-5-5", "claude-opus-5", "opus"])
def test_the_model_matches_exactly(tmp_path, name):                                     # must-refuse
    refused(tmp_path, changed(model=name), "X-MODEL")


def test_an_unknown_agent_is_refused(tmp_path):                                         # must-refuse
    with pytest.raises(Refused) as e:
        gate_request.check(copy.deepcopy(REQ), space_of(tmp_path), "nobody")
    assert e.value.rule == "X-ID"


def test_free_form_content_is_not_inspected(tmp_path):                                  # control (T14)
    body = copy.deepcopy(REQ)
    body["messages"][1]["content"][0]["input"] = {"source": {"type": "url", "url": "http://x"}, "type": "image"}
    body["tools"][0]["input_schema"] = {"anything": {"type": "url"}}
    ok(tmp_path, body)
