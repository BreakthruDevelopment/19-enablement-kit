"""The live gateway, spoken to over stdio, checked against the frozen contract.

The process is `tests/erp_stub.py`. It is not app 18. A real `p2p-erp` is reached only when
`KIT_ERP_LIVE=1` and `KIT_ERP_CONFIG` name a startable gateway; CI does not set those.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import JsonValue

from kit.core.config import Config, GatewayConfig
from kit.core.contract import GatewayContract, load_contract
from kit.core.principals import Principal
from kit.erp.client import call_read, check_live_contract
from kit.erp.contract_check import match_error_shape, match_tool_list
from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, LiveTool
from kit.erp.stdio import StdioGateway

REPO = Path(__file__).resolve().parent.parent
FROZEN = REPO / "contracts" / "p2p-erp.json"
STUB = Path(__file__).resolve().parent / "erp_stub.py"


def test_tool_list_match_ignores_order_and_rejects_a_different_set() -> None:
    contract = load_contract(FROZEN)
    listed = [
        LiveTool(name=tool.name, read_only=tool.effect == "read", description="stub")
        for tool in reversed(contract.read_tools)
    ]
    match_tool_list(contract, listed)
    # The frozen file is alphabetical. A reversed list is a different order and the same set.
    assert [tool.name for tool in listed] != [tool.name for tool in contract.read_tools]

    extra = [*listed, LiveTool(name="release_payment", read_only=False, description="stub")]
    with pytest.raises(ErpError) as extra_caught:
        match_tool_list(contract, extra)
    assert extra_caught.value.code is ErpCode.CONTRACT_DRIFT
    assert extra_caught.value.detail["part"] == "tools"

    missing = listed[:-1]
    with pytest.raises(ErpError) as missing_caught:
        match_tool_list(contract, missing)
    assert missing_caught.value.detail["part"] == "tools"

    duplicate = [*listed, listed[0]]
    with pytest.raises(ErpError) as duplicate_caught:
        match_tool_list(contract, duplicate)
    assert duplicate_caught.value.detail["part"] == "tools"


def test_read_only_hint_must_agree_with_effect() -> None:
    contract = load_contract(FROZEN)
    listed = [
        LiveTool(name=tool.name, read_only=tool.name != "get_invoice", description="stub")
        for tool in contract.read_tools
    ]
    with pytest.raises(ErpError) as caught:
        match_tool_list(contract, listed)
    assert caught.value.detail["part"] == "effect"


def test_error_shape_allows_an_extra_message_and_rejects_a_bad_flag() -> None:
    contract = load_contract(FROZEN)
    match_error_shape(contract, _error("permission", False, message="no such tool"))
    match_error_shape(contract, _error("transient", True, message="the database is busy"))

    for body in (
        _error("permission", True, message="no such tool"),
        CallResult(
            is_error=True,
            structured={"error_category": "permission", "message": "no such tool"},
        ),
        _error("exploded", False),
        CallResult(is_error=False, structured={"id": "INV-1001"}),
    ):
        with pytest.raises(ErpError) as caught:
            match_error_shape(contract, body)
        assert caught.value.detail["part"] == "errors"


def test_a_conforming_process_matches_the_frozen_contract(tmp_path: Path) -> None:
    contract = load_contract(FROZEN)
    log = tmp_path / "methods"
    gateway = _open("conform", contract, log)
    try:
        gateway.start()
        listed = gateway.list_tools()
        match_tool_list(contract, listed)
        # App 18 publishes the spec table order. The frozen file is sorted. Same set.
        assert [tool.name for tool in listed] != sorted(tool.name for tool in listed)
        probed = gateway.call("kit_contract_probe", {})
    finally:
        gateway.close()
    match_error_shape(contract, probed)
    assert probed.is_error is True
    assert probed.error_category == "validation"
    assert probed.is_retryable is False
    assert probed.structured["message"] == "no such tool"
    assert "kit_contract_probe" not in str(probed.structured)
    assert _methods(log) == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]


@pytest.mark.parametrize(
    ("mode", "part"),
    [
        ("drift-missing", "tools"),
        ("drift-extra", "tools"),
        ("drift-duplicate", "tools"),
        ("drift-effect", "effect"),
        ("drift-error", "errors"),
        ("drift-retry", "errors"),
        ("drift-category", "errors"),
        ("drift-success", "errors"),
        ("drift-server", "server"),
    ],
)
def test_a_drifting_process_fails_the_part_that_moved(mode: str, part: str) -> None:
    contract = load_contract(FROZEN)
    with pytest.raises(ErpError) as caught:
        check_live_contract(_config(mode), contract, timeout=5)
    assert caught.value.code is ErpCode.CONTRACT_DRIFT
    assert caught.value.detail["part"] == part
    assert caught.value.__cause__ is None


def test_a_garbage_line_is_a_protocol_error_and_is_not_echoed() -> None:
    contract = load_contract(FROZEN)
    with pytest.raises(ErpError) as caught:
        check_live_contract(_config("garbage"), contract, timeout=5)
    assert caught.value.code is ErpCode.PROTOCOL
    assert caught.value.__cause__ is None
    assert "LEAK" not in str(caught.value)


def test_disagreeing_text_and_structured_content_is_not_a_success() -> None:
    contract = load_contract(FROZEN)
    with pytest.raises(ErpError) as caught:
        check_live_contract(_config("disagree"), contract, timeout=5)
    assert caught.value.code is ErpCode.PROTOCOL
    assert "ok" not in str(caught.value)


def test_a_hung_gateway_is_reaped_by_the_recorded_pid() -> None:
    contract = load_contract(FROZEN)
    gateway = StdioGateway(_config("hang"), contract, timeout=1)
    with pytest.raises(ErpError) as caught:
        gateway.start()
    assert caught.value.code is ErpCode.GATEWAY_TIMEOUT
    assert caught.value.is_retryable is True
    assert gateway.returncode is not None


def test_a_gateway_that_floods_one_line_is_refused_on_the_buffer_bound() -> None:
    # No newline ever arrives, so there is no line boundary to stop on and the bound on the
    # unterminated buffer is the only thing between the client and reading until memory runs
    # out. The code is what this asserts, not merely that it refused: without the bound the
    # read runs to the deadline instead and the error is a timeout.
    contract = load_contract(FROZEN)
    gateway = StdioGateway(_config("flood"), contract, timeout=5)
    with pytest.raises(ErpError) as caught:
        gateway.start()
    assert caught.value.code is ErpCode.PROTOCOL
    assert caught.value.is_retryable is False
    assert "xxx" not in str(caught.value)  # and the body is not quoted back
    assert gateway.returncode is not None  # cleaned up by the pid it started


def test_a_gateway_that_exits_is_unavailable() -> None:
    contract = load_contract(FROZEN)
    with pytest.raises(ErpError) as caught:
        check_live_contract(_config("die"), contract, timeout=5)
    assert caught.value.code is ErpCode.GATEWAY_UNAVAILABLE
    assert "erp_stub" not in str(caught.value)


def test_one_live_read_is_one_tools_call(tmp_path: Path) -> None:
    contract = load_contract(FROZEN)
    log = tmp_path / "methods"
    result = call_read(
        Principal.engineer("ada"),
        contract,
        "get_invoice",
        {"invoice_id": "INV-1001"},
        config=_config("conform", log),
        live=True,
        timeout=5,
    )
    assert result.is_error is False
    assert result.structured["id"] == "INV-1001"
    assert result.structured["state"] == "received"
    assert _methods(log) == ["initialize", "notifications/initialized", "tools/call"]


def test_a_live_permission_error_is_returned_once_and_not_retried(tmp_path: Path) -> None:
    contract = load_contract(FROZEN)
    log = tmp_path / "methods"
    result = call_read(
        Principal.engineer("ada"),
        contract,
        "get_invoice",
        {"invoice_id": "INV-2001"},
        config=_config("conform", log),
        live=True,
        timeout=5,
    )
    assert result.is_error is True
    assert result.error_category == "permission"
    assert result.is_retryable is False
    assert result.structured["message"] == "no invoice visible to this principal"
    rendered = str(result.structured)
    assert "INV-2001" not in rendered
    assert _methods(log).count("tools/call") == 1


def test_a_retryable_gateway_error_is_still_one_call(tmp_path: Path) -> None:
    contract = load_contract(FROZEN)
    log = tmp_path / "methods"
    result = call_read(
        Principal.engineer("ada"),
        contract,
        "get_invoice",
        {"invoice_id": "INV-1001"},
        config=_config("transient", log),
        live=True,
        timeout=5,
    )
    assert result.is_error is True
    assert result.error_category == "transient"
    assert result.is_retryable is True
    assert _methods(log).count("tools/call") == 1


@pytest.mark.skipif(
    os.environ.get("KIT_ERP_LIVE") != "1" or not os.environ.get("KIT_ERP_CONFIG"),
    reason="KIT_ERP_LIVE=1 and KIT_ERP_CONFIG are required to reach a real gateway",
)
def test_a_configured_real_gateway_matches_the_frozen_contract() -> None:
    raw = os.environ.get("KIT_ERP_CONFIG")
    if raw is None:
        pytest.fail("KIT_ERP_CONFIG was not set")
    loaded = Config.from_toml(Path(raw))
    check_live_contract(loaded.gateway, load_contract(loaded.contract_path))


def _error(category: str, retryable: bool, **extra: JsonValue) -> CallResult:
    body: dict[str, JsonValue] = {"error_category": category, "is_retryable": retryable}
    body.update(extra)
    return CallResult(is_error=True, structured=body)


def _config(mode: str, log: Path | None = None) -> GatewayConfig:
    args = [str(STUB), mode]
    if log is not None:
        args.append(str(log))
    return GatewayConfig(command=sys.executable, args=tuple(args))


def _open(mode: str, contract: GatewayContract, log: Path | None = None) -> StdioGateway:
    return StdioGateway(_config(mode, log), contract, timeout=5)


def _methods(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines()
