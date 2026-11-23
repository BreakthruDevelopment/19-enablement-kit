"""`kit erp`: replay by default, one read call, and a permission error left as it arrived."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from kit.cli import main
from kit.core.config import Config, GatewayConfig
from kit.core.contract import load_contract
from kit.core.principals import Principal
from kit.erp.client import call_read
from kit.erp.command import parse_arguments, run_erp
from kit.erp.errors import ErpCode, ErpError
from kit.erp.transcript import load_recording

REPO = Path(__file__).resolve().parent.parent
FROZEN = REPO / "contracts" / "p2p-erp.json"
PACKAGE = REPO / "kit" / "erp"


def test_the_package_does_not_import_app_18() -> None:
    for path in PACKAGE.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "import p2p" not in text
        assert "from p2p" not in text


def test_only_a_timeout_is_retryable() -> None:
    for code in ErpCode:
        detail = {"part": "tools"} if code is ErpCode.CONTRACT_DRIFT else {}
        error = ErpError(code, **detail)
        assert error.is_retryable is (code is ErpCode.GATEWAY_TIMEOUT)
        assert error.is_retryable is (error.category.value == "transient")


def test_the_recording_is_the_service_view_of_the_frozen_contract() -> None:
    contract = load_contract(FROZEN)
    recording = load_recording()
    recording.check_against(contract)
    assert {tool.name for tool in recording.tools} == {tool.name for tool in contract.read_tools}
    assert all(tool.read_only for tool in recording.tools)
    denied = recording.find("get_invoice", {"invoice_id": "INV-2001"})
    assert denied is not None
    assert denied.is_error is True
    assert denied.error_category == "permission"
    assert denied.is_retryable is False


def test_replay_returns_the_recorded_invoice_and_does_not_start_a_process() -> None:
    result = call_read(
        Principal.engineer("ada"),
        load_contract(FROZEN),
        "get_invoice",
        {"invoice_id": "INV-1001"},
        config=GatewayConfig(command="not-a-real-gateway"),
        live=False,
    )
    assert result.is_error is False
    assert result.structured["id"] == "INV-1001"
    assert result.structured["number"] == "1001-A"
    assert result.structured["supplier_id"] == "SUP-1001"
    assert result.is_retryable is False


def test_a_permission_error_is_surfaced_and_not_retried() -> None:
    # The eval: a gateway permission error keeps its category and is_retryable, is not
    # retried, and is not reworded as a success. Replay has one stored reply; a second
    # attempt would miss and raise, so a loop cannot pass this either.
    recording = load_recording()
    found = recording.find("get_invoice", {"invoice_id": "INV-2001"})
    assert found is not None
    again = recording.find("get_invoice", {"invoice_id": "INV-2001"})
    assert again == found
    assert found.structured["message"] == "no invoice visible to this principal"
    assert "INV-2001" not in json.dumps(dict(found.structured))


def test_replay_of_a_missing_call_does_not_echo_the_argument() -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run_erp(
        "get_invoice",
        ["invoice_id=/etc/passwd"],
        role="engineer",
        subject="ada",
        config=Config(contract_path=FROZEN, gateway=GatewayConfig(command="not-a-real-gateway")),
        out=out,
        err=err,
    )
    assert code == 2
    assert out.getvalue() == ""
    text = err.getvalue()
    assert "erp.replay_missing" in text
    assert "/etc/passwd" not in text
    assert "INV" not in text


def test_ci_is_refused_before_the_arguments_are_read() -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run_erp(
        "get_invoice",
        ["invoice_id=/etc/passwd"],
        role="ci",
        subject=None,
        config=Config(contract_path=FROZEN),
        out=out,
        err=err,
    )
    assert code == 2
    assert out.getvalue() == ""
    text = err.getvalue()
    assert "principal.forbidden" in text
    assert "call_gateway" in text
    assert "/etc/passwd" not in text


def test_lead_may_replay_a_read() -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run_erp(
        "list_open_invoices",
        ["limit=1"],
        role="lead",
        subject="rollout",
        config=Config(contract_path=FROZEN),
        out=out,
        err=err,
    )
    assert code == 0
    body = json.loads(out.getvalue())
    assert body["count"] == 1
    assert body["limit"] == 1
    log = json.loads(err.getvalue())
    assert log["tool"] == "list_open_invoices"
    assert log["is_error"] is False
    assert "1001-A" not in err.getvalue()


@pytest.mark.parametrize("tool", ["post_invoice", "issue_credit_memo", "hold_payment"])
def test_a_write_tool_is_refused_and_the_gateway_is_not_started(tool: str) -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run_erp(
        tool,
        ["invoice_id=INV-1001"],
        role="engineer",
        subject="ada",
        config=Config(contract_path=FROZEN, gateway=GatewayConfig(command="not-a-real-gateway")),
        live=True,
        out=out,
        err=err,
    )
    assert code == 2
    assert out.getvalue() == ""
    text = err.getvalue()
    assert "erp.write_refused" in text
    assert "INV-1001" not in text
    assert tool not in text


def test_an_unknown_tool_is_refused_without_its_name() -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run_erp(
        "ignore_previous_instructions",
        [],
        role="engineer",
        subject="ada",
        config=Config(contract_path=FROZEN),
        out=out,
        err=err,
    )
    assert code == 2
    text = err.getvalue()
    assert "erp.unknown_tool" in text
    assert "ignore_previous_instructions" not in text
    assert out.getvalue() == ""


def test_a_bad_argument_is_refused_without_the_token() -> None:
    out, err = io.StringIO(), io.StringIO()
    code = run_erp(
        "get_invoice",
        ["../../secret=1"],
        role="engineer",
        subject="ada",
        config=Config(contract_path=FROZEN),
        out=out,
        err=err,
    )
    assert code == 2
    text = err.getvalue()
    assert "erp.bad_arguments" in text
    assert "../" not in text
    assert "secret" not in text


def test_a_bad_subject_is_refused_without_the_subject() -> None:
    err = io.StringIO()
    code = run_erp(
        "get_invoice",
        ["invoice_id=INV-1001"],
        role="engineer",
        subject="a b",
        config=Config(contract_path=FROZEN),
        err=err,
    )
    assert code == 2
    text = err.getvalue()
    assert "principal.bad_subject" in text
    assert "a b" not in text


def test_arguments_are_json_when_they_parse_and_strings_otherwise() -> None:
    assert parse_arguments(["invoice_id=INV-1001", "limit=5"]) == {
        "invoice_id": "INV-1001",
        "limit": 5,
    }
    assert parse_arguments(['{"invoice_id": "INV-1001"}']) == {"invoice_id": "INV-1001"}
    with pytest.raises(ErpError) as caught:
        parse_arguments(["limit=1", "limit=2"])
    assert caught.value.code is ErpCode.BAD_ARGUMENTS


def test_cli_replays_and_logs_the_call_without_the_invoice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["erp", "get_invoice", "invoice_id=INV-1001"])
    assert code == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["number"] == "1001-A"
    assert body["total"] == 125000
    log = json.loads(captured.err)
    assert log["event"] == "erp.call"
    assert log["tool"] == "get_invoice"
    assert log["is_error"] is False
    assert "1001-A" not in captured.err
    assert "M8 hex bolts" not in captured.err
    assert "INV-1001" not in captured.err


def test_cli_prints_a_permission_error_as_the_gateway_sent_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["erp", "get_invoice", "invoice_id=INV-2001"])
    assert code == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        "error_category": "permission",
        "is_retryable": False,
        "message": "no invoice visible to this principal",
    }
    assert json.loads(captured.err)["is_retryable"] is False
    assert json.loads(captured.err)["error_category"] == "permission"
    assert "INV-2001" not in captured.out
    assert "INV-2001" not in captured.err


def test_cli_help_says_replay_is_the_default(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["erp", "--help"])
    assert exit_info.value.code == 0
    text = capsys.readouterr().out
    assert "--live" in text
    assert "replay" in text


def test_cli_requires_a_tool() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["erp"])
    assert exit_info.value.code == 2
