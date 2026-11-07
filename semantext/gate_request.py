"""The request gate for an Anthropic Messages request (PROXY-DESIGN r4: section 3 steps 4 and 5, D1, T5, T14).

A request is where vendor-side work is switched on, so it is judged before anything is forwarded:

  - **Fields are an allow-list** in a gated space (T5: its default is hold, or it has any gate block): every field,
    and every key inside a known field down to free-form content, must be on the lists below or on the space's
    `extra_fields`; an unknown one is refused with its name (capped, D7). Inspection stops at free-form content: a tool
    input, a tool's input_schema, text, metadata values.
  - **Tools** are client-run (no `type`, or an Anthropic-schema client tool type) or vendor-run (any server tool
    type); an unknown `type` is refused.
  - **Vendor-side work is refused** unless the space says `vendor_side: record`: a vendor-run tool, `mcp_servers`,
    `container`, and an image or document whose source makes the vendor fetch an address (`url`, `file`), at any
    depth, inside tool results and the system prompt too (J7, T14).
  - The model must be named exactly as one of the agent's model blocks names it (T13).

Sources of the lists: PROXY-DESIGN r4 section 1 (the streaming and vision pages; the claude-api skill for the request
fields and tool types). A field whose only source is memory is not here (T4, KP7); the person adds a name by a console
act (`extra_fields` in space.yaml).
"""
from __future__ import annotations

from .assemble import Refused, _name

# Top-level request fields, each with the keys allowed inside it ("*" = free-form, not inspected).
TOP = {
    "model": None, "messages": "messages", "max_tokens": None, "system": "system", "stream": None, "tools": "tools",
    "tool_choice": {"type", "name", "disable_parallel_tool_use"}, "metadata": "*", "stop_sequences": None,
    "temperature": None, "top_p": None, "top_k": None, "thinking": {"type", "display", "budget_tokens"},
    "output_config": {"effort", "format", "task_budget"}, "context_management": "*", "cache_control": {"type", "ttl"},
    "inference_geo": None, "speed": None, "fallbacks": "*",
    "mcp_servers": "VENDOR", "container": "VENDOR",
}
BLOCK_KEYS = {
    "text": {"type", "text", "cache_control", "citations"},
    "image": {"type", "source", "cache_control"},
    "document": {"type", "source", "cache_control", "title", "context", "citations"},
    "tool_use": {"type", "id", "name", "input", "cache_control"},
    "tool_result": {"type", "tool_use_id", "content", "is_error", "cache_control"},
    "thinking": {"type", "thinking", "signature"},
    "redacted_thinking": {"type", "data"},
}
FETCHING_SOURCES = {"url", "file"}     # the vendor fetches what the client names: egress at the vendor
# Sources carried in the request itself (the vision page: base64; documents: base64, plain text, inline blocks).
SOURCES = {"image": {"base64"}, "document": {"base64", "text", "content"}}
CUSTOM_TOOL_KEYS = {"name", "description", "input_schema", "cache_control", "strict", "eager_input_streaming"}
CLIENT_TOOL_TYPES = ("bash_", "text_editor_", "computer_", "memory_")        # Anthropic-schema, run by the client
SERVER_TOOL_TYPES = ("web_search_", "web_fetch_", "code_execution_", "tool_search_tool_", "advisor_", "mcp_toolset")


def gated(space) -> bool:
    """T5: a space is gated if its default is hold or it has any gate block."""
    return space.settings.get("default") == "hold" or bool(space.of("gate"))


class Check:
    def __init__(self, space, agent_id: str):
        self.space, self.agent = space, space.blocks.get(agent_id)
        self.strict = gated(space)
        self.extra = set(space.settings.get("extra_fields", []))
        self.vendor_ok = space.settings.get("vendor_side") == "record"
        self.recorded: list[str] = []          # vendor-side work allowed and recorded as ungateable
        self.unknown: list[str] = []           # unknown fields passed in an ungated space
        self.client_tools: set[str] = set()     # names of the tools this request declares and the client runs

    def field(self, path: str):
        if path in self.extra:
            return
        if self.strict:
            # Koinos R7: the key itself is named, then where it sits; a long path once cut the key's own name off.
            where, _, key = path.rpartition(".")
            at = f" in {_name(where)}" if where else ""
            raise Refused("X-FIELD", f"the field {_name(key)!r}{at} is not on this space's list; "
                                     f"add it by a console act if the client needs it")
        self.unknown.append(path)

    def vendor(self, what: str):
        if not self.vendor_ok:
            raise Refused("X-REQ", f"{what}: work the vendor runs, which no gate here can hold")
        self.recorded.append(what)

    def keys(self, obj: dict, allowed: set, path: str):
        for k in obj:
            if k not in allowed:
                self.field(f"{path}.{k}")

    def blocks(self, content, path: str):
        if isinstance(content, str):
            return
        if not isinstance(content, list):
            raise Refused("X-BODY", f"{path} must be text or a list of blocks")
        for b in content:
            if not isinstance(b, dict):
                raise Refused("X-BODY", f"an item of {path} is not a block")
            t = b.get("type")
            if t not in BLOCK_KEYS:
                self.field(f"{path}.{_name(t)}")
                continue
            self.keys(b, BLOCK_KEYS[t], f"{path}.{t}")
            if t in ("image", "document"):
                src = b.get("source")
                kind = src.get("type") if isinstance(src, dict) else None
                if kind not in SOURCES[t] and kind not in FETCHING_SOURCES:      # R3: a checked list, nothing else
                    raise Refused("X-REQ", f"an {t} source of a type the proxy does not know: {_name(kind)}")
                if isinstance(src, dict) and src.get("type") in FETCHING_SOURCES:
                    self.vendor(f"an {t} the vendor fetches ({src.get('type')} source)")
                if isinstance(src, dict) and src.get("type") == "content":      # blocks inside a document (P9)
                    self.blocks(src.get("content", ""), f"{path}.{t}.source")
            if t == "tool_result":
                self.blocks(b.get("content", ""), f"{path}.tool_result")

    def tools(self, tools):
        if not isinstance(tools, list):
            raise Refused("X-BODY", "tools must be a list")
        for t in tools:
            if not isinstance(t, dict):
                raise Refused("X-BODY", "a tool that is not an object")
            kind = t.get("type")
            if ("type" not in t) or kind == "custom":
                # Koinos R5: a custom tool has a name and an object schema; a `type` that is there but null is not one.
                if not isinstance(t.get("name"), str) or not t["name"] or not isinstance(t.get("input_schema"), dict):
                    raise Refused("X-REQ", "a custom tool needs a name and an input_schema object")
                self.keys(t, CUSTOM_TOOL_KEYS | {"type"}, "tools.custom")
                self.client_tools.add(t["name"])
            elif isinstance(kind, str) and kind.startswith(CLIENT_TOOL_TYPES):
                self.keys(t, {"type", "name", "cache_control"} | ({"display_width_px", "display_height_px",
                                                                    "display_number"} if kind.startswith("computer_")
                                                                   else set()), f"tools.{_name(kind)}")
                if isinstance(t.get("name"), str):
                    self.client_tools.add(t["name"])
            elif isinstance(kind, str) and kind.startswith(SERVER_TOOL_TYPES):
                self.vendor(f"the tool {_name(kind)}")
            else:
                raise Refused("X-REQ", f"a tool of a type the proxy does not know: {_name(kind)}")

    def model(self, name):
        allowed = {self.space.blocks[m]["model"] for m in (self.agent or {}).get("models", [])}
        if name not in allowed:
            raise Refused("X-MODEL", "a model this agent's model blocks do not name exactly")

    def run(self, body: dict):
        if not isinstance(body, dict):
            raise Refused("X-BODY", "the request is not an object")
        if self.agent is None or self.agent.get("kind") != "agent":
            raise Refused("X-ID", "no agent block for this request")
        for k, v in body.items():
            spec = TOP.get(k, "UNKNOWN")
            if spec == "UNKNOWN":
                self.field(k)
            elif spec == "VENDOR":
                self.vendor(f"the field {k}")
            elif spec == "messages":
                if not isinstance(v, list):
                    raise Refused("X-BODY", "messages must be a list")
                for m in v:
                    if not isinstance(m, dict):
                        raise Refused("X-BODY", "a message that is not an object")
                    self.keys(m, {"role", "content"}, "messages")
                    self.blocks(m.get("content", ""), "messages.content")
            elif spec == "system":
                self.blocks(v, "system")
            elif spec == "tools":
                self.tools(v)
            elif isinstance(spec, set):
                if not isinstance(v, dict):
                    raise Refused("X-BODY", f"{k} must be an object")
                self.keys(v, spec, k)
            if k == "context_management":
                # Koinos R4 (KIT_SPEC ruling: P, counted): context editing runs at the vendor, so no gate here sees it;
                # it passes and is recorded as ungateable work.
                self.recorded.append("context editing (context_management)")
        self.tool_choice(body.get("tool_choice"))
        self.model(body.get("model"))
        return self

    def tool_choice(self, tc):
        """Koinos R6: tool_choice names only a tool this request declares and the client runs. Its keys were checked;
        its value was not, so a choice could force a vendor-run tool (web_search) that the tools list never had."""
        if tc is None:
            return
        kind = tc.get("type")
        if kind not in ("auto", "any", "tool", "none"):
            raise Refused("X-REQ", f"a tool_choice of a type the proxy does not know: {_name(kind)}")
        if kind == "tool" and tc.get("name") not in self.client_tools:
            raise Refused("X-REQ", "tool_choice names a tool this request does not declare as one the client runs")


def check(body: dict, space, agent_id: str) -> Check:
    """Judge one request; raises Refused, or returns the check with what it recorded."""
    return Check(space, agent_id).run(body)
