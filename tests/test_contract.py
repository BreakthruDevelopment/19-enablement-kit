"""The frozen copy of app 18's gateway contract, and the schema that guards it."""

import json
from pathlib import Path
from typing import Any

import pytest
from agent_container.core.tool import ErrorCategory

from kit.core.config import Config
from kit.core.contract import GatewayContract, load_contract
from kit.core.errors import ErrorCode, KitError

REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN = REPO_ROOT / "contracts" / "p2p-erp.json"


def test_the_default_config_points_at_the_frozen_copy() -> None:
    assert (REPO_ROOT / Config.default().contract_path) == FROZEN


def test_the_frozen_contract_loads() -> None:
    contract = load_contract(FROZEN)
    assert contract.server.name == "p2p-erp"
    assert contract.server.transport == "stdio"
    assert contract.contract_version >= 1
    assert "18-procure-to-pay" in contract.source


def test_the_frozen_tool_list_is_app_18s_published_one() -> None:
    contract = load_contract(FROZEN)
    reads = {tool.name for tool in contract.tools if tool.effect == "read"}
    writes = {tool.name for tool in contract.tools if tool.effect == "write"}
    assert reads == {
        "find_supplier",
        "get_purchase_order",
        "get_goods_receipt",
        "get_invoice",
        "list_open_invoices",
        "get_payment_status",
    }
    assert writes == {"post_invoice", "issue_credit_memo", "hold_payment"}


def test_the_write_tools_name_the_roles_app_18_gives_them() -> None:
    contract = load_contract(FROZEN)
    expected = {
        "post_invoice": {"clerk"},
        "issue_credit_memo": {"disputes"},
        "hold_payment": {"disputes"},
    }
    for name, roles in expected.items():
        tool = contract.tool(name)
        assert tool is not None
        assert set(tool.roles) == roles


def test_app_19_connects_as_a_read_only_principal() -> None:
    # App 18 gives `service` the read tools only; nothing here may stage a change in the ERP.
    contract = load_contract(FROZEN)
    assert contract.read_tools == tuple(tool for tool in contract.tools if "service" in tool.roles)
    assert len(contract.read_tools) == 6
    for tool in contract.tools:
        if tool.effect == "write":
            assert "service" not in tool.roles


def test_the_error_shape_is_app_17s_five_categories_with_a_retry_flag() -> None:
    contract = load_contract(FROZEN)
    assert contract.errors.categories == tuple(category.value for category in ErrorCategory)
    assert set(contract.errors.fields) == {"error_category", "is_retryable"}
    # App 17's rule: a retry is worth it only for a transient failure.
    assert contract.errors.retryable_categories == ("transient",)


def test_a_missing_contract_is_unreadable_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(KitError) as caught:
        load_contract(tmp_path / "absent.json")
    assert caught.value.code is ErrorCode.CONTRACT_UNREADABLE


def test_contents_that_are_not_json_are_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "p2p-erp.json"
    path.write_text("{not json")
    with pytest.raises(KitError) as caught:
        load_contract(path)
    assert caught.value.code is ErrorCode.CONTRACT_UNREADABLE


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda d: d.update(server={"name": "other", "transport": "stdio"}), id="server"
        ),
        pytest.param(lambda d: d.update(extra=True), id="unknown-key"),
        pytest.param(lambda d: d["tools"].append(dict(d["tools"][0])), id="duplicate-tool"),
        pytest.param(
            lambda d: d["tools"].insert(0, {**d["tools"][0], "name": "zz_last"}), id="unsorted"
        ),
        pytest.param(lambda d: d["tools"][0].update(effect="delete"), id="bad-effect"),
        pytest.param(lambda d: d["tools"][0].update(roles=[]), id="no-roles"),
        pytest.param(lambda d: d["errors"].update(categories=["transient"]), id="short-categories"),
        pytest.param(
            lambda d: d["errors"].update(
                categories=["validation", "transient", "permission", "business", "internal"]
            ),
            id="reordered-categories",
        ),
        pytest.param(lambda d: d["errors"].update(fields=["error_category"]), id="missing-field"),
        pytest.param(
            lambda d: d["errors"].update(retryable_categories=["sometimes"]), id="unknown-retryable"
        ),
        pytest.param(lambda d: d.update(frozen_on="yesterday"), id="bad-date"),
        pytest.param(lambda d: d.update(contract_version=0), id="bad-version"),
        # Proves the `^...$` anchors are exact under pydantic's Rust regex engine: a trailing
        # newline must not slip past a name or a date pattern.
        pytest.param(lambda d: d["tools"][0].update(name="aa_tool\n"), id="name-newline"),
        pytest.param(lambda d: d.update(frozen_on="2026-11-22\n"), id="date-newline"),
    ],
)
def test_a_drifted_contract_is_refused(tmp_path: Path, mutate: Any) -> None:
    data = json.loads(FROZEN.read_text())
    mutate(data)
    path = tmp_path / "p2p-erp.json"
    path.write_text(json.dumps(data))
    with pytest.raises(KitError) as caught:
        load_contract(path)
    assert caught.value.code is ErrorCode.CONTRACT_INVALID
    assert caught.value.category.value == "validation"


def test_a_hostile_field_name_cannot_reach_the_message(tmp_path: Path) -> None:
    data = json.loads(FROZEN.read_text())
    data["../../etc/passwd"] = 1
    path = tmp_path / "p2p-erp.json"
    path.write_text(json.dumps(data))
    with pytest.raises(KitError) as caught:
        load_contract(path)
    assert "passwd" not in caught.value.message


def test_the_contract_model_is_frozen() -> None:
    contract = load_contract(FROZEN)
    with pytest.raises(ValueError, match="frozen"):
        contract.contract_version = 2
    assert isinstance(contract, GatewayContract)


def test_the_frozen_file_is_formatted_so_a_drift_is_a_readable_diff() -> None:
    raw = FROZEN.read_text()
    assert raw == json.dumps(json.loads(raw), indent=2) + "\n"


def test_an_oversized_contract_is_refused_before_it_is_parsed(tmp_path: Path) -> None:
    path = tmp_path / "p2p-erp.json"
    path.write_text(json.dumps({"padding": "x" * 300_000}))
    with pytest.raises(KitError) as caught:
        load_contract(path)
    assert caught.value.code is ErrorCode.CONTRACT_UNREADABLE
