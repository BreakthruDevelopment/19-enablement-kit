"""One read call through the MCP client, replayed unless a run asks to go live.

Authorization is `assert_can(CALL_GATEWAY)`, which `engineer` and `lead` hold and `ci`
does not. The tool is then checked against the frozen contract: app 19 connects as the
read-only `service` principal, so a write tool is refused here and is never sent. The
call itself happens once. A gateway error is returned as the gateway sent it, category
and `is_retryable` included, and is not turned into a success and not tried again.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

from pydantic import JsonValue

from kit.core.config import GatewayConfig
from kit.core.contract import GatewayContract
from kit.core.principals import Capability, Principal, assert_can
from kit.erp.contract_check import PROBE_TOOL, match_error_shape, match_tool_list
from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, normalize_arguments
from kit.erp.replay import ReplayGateway
from kit.erp.stdio import StdioGateway
from kit.erp.transcript import load_recording

__all__ = ["call_read", "check_live_contract"]

_TOOL: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")

# What a gateway object can do. Both implementations, so the policy below stays one path.
_Gateway = ReplayGateway | StdioGateway


def call_read(
    principal: Principal,
    contract: GatewayContract,
    name: str,
    arguments: Mapping[str, JsonValue],
    *,
    config: GatewayConfig,
    live: bool,
    timeout: float = 10.0,
) -> CallResult:
    """Authorize, check the tool, then make exactly one gateway call."""
    assert_can(principal, Capability.CALL_GATEWAY)
    _require_read_tool(contract, name)
    normalized = normalize_arguments(arguments)
    gateway = _open(contract, config, live=live, timeout=timeout)
    try:
        return gateway.call(name, normalized)
    finally:
        gateway.close()


def check_live_contract(
    config: GatewayConfig,
    contract: GatewayContract,
    *,
    timeout: float = 10.0,
) -> None:
    """Ask a live gateway for its tool list and one error, and compare both to the contract.

    The probe is a tool name the contract does not publish, so a conforming gateway
    answers with its error shape and does not read or stage a row. This is not a `kit erp`
    call: it is the drift check, and it does not retry.
    """
    gateway = StdioGateway(config, contract, timeout=timeout)
    try:
        gateway.start()
        match_tool_list(contract, gateway.list_tools())
        probed = gateway.call(PROBE_TOOL, {})
        match_error_shape(contract, probed)
    finally:
        gateway.close()


def _require_read_tool(contract: GatewayContract, name: str) -> None:
    if _TOOL.fullmatch(name) is None:
        raise ErpError(ErpCode.UNKNOWN_TOOL)
    frozen = contract.tool(name)
    if frozen is None:
        raise ErpError(ErpCode.UNKNOWN_TOOL)
    # `service` is the principal app 19 connects as. A read tool it is not allowed to
    # call is the same refusal as a write: it is not sent.
    if frozen.effect != "read" or "service" not in frozen.roles:
        raise ErpError(ErpCode.WRITE_REFUSED)


def _open(
    contract: GatewayContract,
    config: GatewayConfig,
    *,
    live: bool,
    timeout: float,
) -> _Gateway:
    if live:
        gateway = StdioGateway(config, contract, timeout=timeout)
        gateway.start()
        return gateway
    recording = load_recording()
    recording.check_against(contract)
    return ReplayGateway(recording)
