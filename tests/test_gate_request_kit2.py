"""Koinos's second kit run (3 November 2026): R4 to R7 at the request gate. Each must-refuse arm changes one thing in
the request test_gate_request passes (its REQ, the control)."""
from __future__ import annotations

import copy

import pytest

from tests.test_gate_request import REQ, ok, refused


def req(**over):
    body = copy.deepcopy(REQ)
    body.update(over)
    return body


def test_context_management_passes_and_is_counted_as_vendor_work(tmp_path):     # R4 (KIT_SPEC: P, counted)
    c = ok(tmp_path, req(context_management={"edits": [{"type": "clear_tool_uses_20250919"}]}))
    assert c.recorded == ["context editing (context_management)"]
    assert ok(tmp_path).recorded == []                                             # control: nothing counted


@pytest.mark.parametrize("tool", [
    {"type": None, "name": "x", "input_schema": {"type": "object"}},
    {"description": "no name", "input_schema": {"type": "object"}},
    {"name": "x"},
    {"name": "", "input_schema": {"type": "object"}},
], ids=["type null", "no name", "no schema", "empty name"])
def test_a_tool_that_is_not_a_custom_tool_is_refused(tmp_path, tool):          # must-refuse (R5)
    e = refused(tmp_path, req(tools=[*REQ["tools"], tool]), "X-REQ")
    assert "custom tool" in e.reason or "does not know" in e.reason            # a null type is an unknown type


@pytest.mark.parametrize("choice,why", [
    ({"type": "tool", "name": "web_search"}, "does not declare"),
    ({"type": "tool", "name": "Nothing"}, "does not declare"),
    ({"type": "server"}, "does not know"),
])
def test_tool_choice_names_only_a_tool_the_client_runs(tmp_path, choice, why):  # must-refuse (R6)
    refused(tmp_path, req(tool_choice=choice), "X-REQ", why)


@pytest.mark.parametrize("choice", [{"type": "auto"}, {"type": "tool", "name": "Bash"},
                                    {"type": "tool", "name": "str_replace_based_edit_tool"}, {"type": "none"}])
def test_tool_choice_of_a_declared_client_tool_passes(tmp_path, choice):       # control (R6)
    ok(tmp_path, req(tool_choice=choice))


def test_an_unknown_nested_key_is_named_by_its_own_name(tmp_path):             # R7
    body = req()
    body["messages"][2]["content"][0]["content"][0]["a_very_particular_key"] = 1
    refused(tmp_path, body, "X-FIELD", "a_very_particular_key", "messages.content.tool_result.text")
