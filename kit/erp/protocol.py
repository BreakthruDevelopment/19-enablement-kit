"""The slice of MCP stdio this client speaks.

Newline-delimited JSON-RPC 2.0. One request, one response line. A notification (no `id`)
gets no response. A tool failure is a successful JSON-RPC response whose `result` has
`isError` true and the frozen error object in `structuredContent`; the text content, when
the gateway sends it, is that same object. A protocol failure carries no payload back to
the caller: the line is untrusted and is not copied into the error.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Final, cast

from pydantic import JsonValue

from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, LiveTool

__all__ = [
    "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION",
    "notification",
    "parse_call_result",
    "parse_initialize",
    "parse_response",
    "parse_tool_list",
    "request",
]

# The version this client offers. App 18's gateway echoes a version it implements and
# answers anything else with its preferred one; we require the one we offered, so a
# gateway that no longer speaks it fails here instead of being half-understood.
PROTOCOL_VERSION: Final = "2025-03-26"

# One line, the same order of magnitude as the gateway's own cap. Past it the line is
# refused without being parsed, so a huge or hostile body is never decoded.
MAX_MESSAGE_BYTES: Final = 1_000_000

_TOOL_NAME: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")


def request(
    method: str, request_id: int, params: Mapping[str, JsonValue] | None = None
) -> dict[str, JsonValue]:
    """One JSON-RPC request. `params` is omitted when the method takes none."""
    message: dict[str, JsonValue] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = dict(params)
    return message


def notification(method: str) -> dict[str, JsonValue]:
    """A notification. The client writes it and does not read a response."""
    return {"jsonrpc": "2.0", "method": method}


def parse_response(line: str, expected_id: int) -> Mapping[str, JsonValue]:
    """The `result` object of the response to `expected_id`.

    A JSON-RPC `error`, a mismatched id, or anything that is not one object is a protocol
    failure. The line itself is not quoted.
    """
    message = _decode_object(line)
    if message.get("jsonrpc") != "2.0" or message.get("id") != expected_id:
        raise ErpError(ErpCode.PROTOCOL)
    if "error" in message or "result" not in message:
        raise ErpError(ErpCode.PROTOCOL)
    result = _object(message.get("result"))
    if result is None:
        raise ErpError(ErpCode.PROTOCOL)
    return result


def parse_initialize(result: Mapping[str, JsonValue], *, server_name: str) -> None:
    """Require the protocol version we offered and the frozen contract's server name."""
    if result.get("protocolVersion") != PROTOCOL_VERSION:
        raise ErpError(ErpCode.PROTOCOL)
    info = _object(result.get("serverInfo"))
    if info is None or info.get("name") != server_name:
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="server")


def parse_tool_list(result: Mapping[str, JsonValue]) -> tuple[LiveTool, ...]:
    """The tools a `tools/list` result names. A malformed entry is drift, not a crash."""
    raw = result.get("tools")
    if not isinstance(raw, list):
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="tools")
    listed: list[LiveTool] = []
    for item in raw:
        listed.append(_one_tool(item))
    return tuple(listed)


def parse_call_result(result: Mapping[str, JsonValue]) -> CallResult:
    """One `tools/call` result. Text and structured content must agree when both are present.

    Disagreeing copies are a protocol failure. Picking the text would let a gateway show a
    success in one channel and an error in the other, and the client would have chosen.
    """
    is_error = result.get("isError")
    structured = _object(result.get("structuredContent"))
    if not isinstance(is_error, bool) or structured is None:
        raise ErpError(ErpCode.PROTOCOL)
    _agree(result.get("content"), structured)
    return CallResult(is_error=is_error, structured=structured)


def _one_tool(item: object) -> LiveTool:
    body = _object(item)
    if body is None:
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="tools")
    name = body.get("name")
    if not isinstance(name, str) or _TOOL_NAME.fullmatch(name) is None:
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="tools")
    annotations = _object(body.get("annotations"))
    if annotations is None:
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="effect")
    read_only = annotations.get("readOnlyHint")
    if not isinstance(read_only, bool):
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="effect")
    description = body.get("description")
    text = description if isinstance(description, str) else ""
    return LiveTool(name=name, read_only=read_only, description=text)


def _agree(content: object, structured: Mapping[str, JsonValue]) -> None:
    """If the gateway sent a text block, it has to be the structured object and nothing else."""
    if content is None:
        return
    if not isinstance(content, list) or len(content) != 1:
        raise ErpError(ErpCode.PROTOCOL)
    block = _object(content[0])
    if block is None or block.get("type") != "text":
        raise ErpError(ErpCode.PROTOCOL)
    text = block.get("text")
    if not isinstance(text, str):
        raise ErpError(ErpCode.PROTOCOL)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise ErpError(ErpCode.PROTOCOL) from None
    if parsed != structured:
        raise ErpError(ErpCode.PROTOCOL)


def _decode_object(line: str) -> Mapping[str, JsonValue]:
    if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ErpError(ErpCode.PROTOCOL)
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        raise ErpError(ErpCode.PROTOCOL) from None
    body = _object(parsed)
    if body is None:
        raise ErpError(ErpCode.PROTOCOL)
    return body


def _object(value: object) -> dict[str, JsonValue] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return cast(dict[str, JsonValue], value)
