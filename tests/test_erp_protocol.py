"""The protocol layer, tested directly: every rule it applies to what a gateway sends.

`kit/erp/protocol.py` is the module that decides what counts as a well-formed answer, so each
of its rules is only reachable from untrusted input and none of them is exercised by the
happy-path transcript. These tests drive the parsers with the malformed answers themselves, and
each one is written so that the rule under test is the *only* reason the input is refused --
otherwise deleting the rule leaves the suite green, which is how this repo has shipped a cap
nothing could fail.
"""

from __future__ import annotations

import json

import pytest
from pydantic import JsonValue

from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import MAX_ARGUMENT_BYTES, normalize_arguments
from kit.erp.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    parse_call_result,
    parse_initialize,
    parse_response,
    parse_tool_list,
)

SERVER = "p2p-erp"


def _response(body: JsonValue, request_id: int = 1) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "result": body})


def _tool(**overrides: JsonValue) -> dict[str, JsonValue]:
    tool: dict[str, JsonValue] = {
        "name": "get_invoice",
        "annotations": {"readOnlyHint": True},
        "description": "one invoice",
    }
    tool.update(overrides)
    return tool


# --- The caps on what a gateway may send --------------------------------------------------------


def test_a_line_over_the_message_cap_is_refused_without_being_parsed() -> None:
    # Valid JSON, the right id, a well-formed result: the size is the only thing wrong with it,
    # so raising the cap makes this parse cleanly and the test fail.
    padded = _response({"pad": "x" * MAX_MESSAGE_BYTES})
    assert len(padded.encode("utf-8")) > MAX_MESSAGE_BYTES
    with pytest.raises(ErpError) as caught:
        parse_response(padded, 1)
    assert caught.value.code is ErpCode.PROTOCOL
    # And one byte under the cap is accepted, so the test pins the bound and not merely "large".
    pad = MAX_MESSAGE_BYTES - len(_response({"pad": ""}).encode("utf-8"))
    body: dict[str, JsonValue] = {"pad": "x" * pad}
    under = _response(body)
    assert len(under.encode("utf-8")) == MAX_MESSAGE_BYTES
    assert parse_response(under, 1) == body


def test_arguments_over_the_argument_cap_are_refused() -> None:
    # Canonical JSON, a plain object, every value a string: only the cap can refuse it.
    big = {"invoice_id": "I" * (MAX_ARGUMENT_BYTES + 1)}
    with pytest.raises(ErpError) as caught:
        normalize_arguments(big)
    assert caught.value.code is ErpCode.BAD_ARGUMENTS
    assert normalize_arguments({"invoice_id": "INV-1001"})["invoice_id"] == "INV-1001"


# --- parse_response -----------------------------------------------------------------------------


def test_a_response_to_another_request_is_refused() -> None:
    # The reply is well-formed and would be a perfectly good answer to request 2. Dropping the
    # id comparison would let request 1 be answered by it.
    line = _response({"ok": True}, request_id=2)
    with pytest.raises(ErpError) as caught:
        parse_response(line, 1)
    assert caught.value.code is ErpCode.PROTOCOL
    assert parse_response(line, 2) == {"ok": True}


# --- parse_initialize ---------------------------------------------------------------------------


def test_a_gateway_offering_another_protocol_version_is_refused() -> None:
    # The server name is the frozen one and the handshake is otherwise complete, so the version
    # is the only objection. A gateway that no longer speaks our version must fail here rather
    # than be half-understood.
    other: dict[str, JsonValue] = {
        "protocolVersion": "1999-01-01",
        "serverInfo": {"name": SERVER, "version": "9"},
    }
    with pytest.raises(ErpError) as caught:
        parse_initialize(other, server_name=SERVER)
    assert caught.value.code is ErpCode.PROTOCOL
    ours: dict[str, JsonValue] = {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": {"name": SERVER, "version": "9"},
    }
    parse_initialize(ours, server_name=SERVER)


def test_a_missing_protocol_version_is_refused() -> None:
    with pytest.raises(ErpError) as caught:
        no_version: dict[str, JsonValue] = {"serverInfo": {"name": SERVER}}
        parse_initialize(no_version, server_name=SERVER)
    assert caught.value.code is ErpCode.PROTOCOL


# --- parse_tool_list ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["Get_Invoice", "get-invoice", "get invoice", "", "x" * 65, "1x"])
def test_a_tool_name_outside_the_shape_is_drift(name: str) -> None:
    # Annotations are present and well-formed, so the name is the only objection.
    with pytest.raises(ErpError) as caught:
        listed: dict[str, JsonValue] = {"tools": [_tool(name=name)]}
        parse_tool_list(listed)
    assert caught.value.code is ErpCode.CONTRACT_DRIFT
    assert caught.value.detail["part"] == "tools"


def test_a_tool_without_annotations_is_drift_not_assumed_read_only() -> None:
    # The dangerous default: a tool whose effect the gateway did not state must not be taken
    # for a read. The name is valid, so the missing annotations are the only objection.
    missing = _tool()
    del missing["annotations"]
    with pytest.raises(ErpError) as caught:
        broken: dict[str, JsonValue] = {"tools": [missing]}
        parse_tool_list(broken)
    assert caught.value.code is ErpCode.CONTRACT_DRIFT
    assert caught.value.detail["part"] == "effect"


@pytest.mark.parametrize("hint", ["true", 1, None, {}])
def test_a_read_only_hint_that_is_not_a_boolean_is_drift(hint: JsonValue) -> None:
    with pytest.raises(ErpError) as caught:
        hinted: dict[str, JsonValue] = {"tools": [_tool(annotations={"readOnlyHint": hint})]}
        parse_tool_list(hinted)
    assert caught.value.code is ErpCode.CONTRACT_DRIFT
    assert caught.value.detail["part"] == "effect"


def test_a_well_formed_tool_list_is_accepted() -> None:
    good: dict[str, JsonValue] = {"tools": [_tool()]}
    listed = parse_tool_list(good)
    assert [(tool.name, tool.read_only) for tool in listed] == [("get_invoice", True)]


# --- parse_call_result --------------------------------------------------------------------------


def test_a_call_result_without_structured_content_is_refused() -> None:
    # `isError` is a proper boolean, so the missing object is the only objection. Defaulting it
    # to `{}` would turn a malformed answer into an empty success.
    with pytest.raises(ErpError) as caught:
        only_flag: dict[str, JsonValue] = {"isError": False}
        parse_call_result(only_flag)
    assert caught.value.code is ErpCode.PROTOCOL


@pytest.mark.parametrize("is_error", ["false", 0, None])
def test_a_call_result_whose_is_error_is_not_a_boolean_is_refused(
    is_error: JsonValue,
) -> None:
    # Coercing this would read a string "false" as an error, or 0 as a success, from a gateway
    # that never said either.
    with pytest.raises(ErpError) as caught:
        body: dict[str, JsonValue] = {
            "isError": is_error,
            "structuredContent": {"id": "INV-1001"},
        }
        parse_call_result(body)
    assert caught.value.code is ErpCode.PROTOCOL


def test_a_well_formed_call_result_is_accepted() -> None:
    ok: dict[str, JsonValue] = {
        "isError": False,
        "structuredContent": {"id": "INV-1001"},
    }
    result = parse_call_result(ok)
    assert result.is_error is False
    assert result.structured["id"] == "INV-1001"
