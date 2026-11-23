"""Compare a live gateway to the frozen contract.

App 19 connects as app 18's read-only `service` principal. That principal's tool list is
the frozen contract's read tools, which are exactly the tools whose roles include
`service`. The error shape is the two fields the contract names, the five categories, and
the rule that only a category in `retryable_categories` has `is_retryable` true.

A mismatch is `erp.contract_drift`. The message names which part (`tools`, `effect`,
`errors`, `server`) and nothing the gateway sent: a drifted payload is untrusted text.
"""

from __future__ import annotations

from collections.abc import Sequence

from kit.core.contract import GatewayContract
from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, LiveTool

__all__ = ["PROBE_TOOL", "match_error_shape", "match_tool_list"]

# Not a tool in the frozen contract. A conforming gateway reports it as a tool error --
# app 18 uses `validation`, `is_retryable` false, for a name it does not publish -- which
# is enough to read the error shape without a seeded row and without calling a write.
PROBE_TOOL = "kit_contract_probe"


def match_tool_list(contract: GatewayContract, listed: Sequence[LiveTool]) -> None:
    """The live list is the service principal's tools: the contract's read tools, no others.

    Order is not part of the check. The frozen file is sorted by name and a gateway may
    publish the spec's table order; both are the same set. `readOnlyHint` has to agree
    with the frozen `effect`.
    """
    names = [tool.name for tool in listed]
    if len(names) != len(set(names)):
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="tools")
    expected = {tool.name: tool for tool in contract.read_tools}
    if set(names) != set(expected):
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="tools")
    by_name = {tool.name: tool for tool in listed}
    for name, frozen in expected.items():
        live = by_name[name]
        if live.read_only != (frozen.effect == "read"):
            raise ErpError(ErpCode.CONTRACT_DRIFT, part="effect")


def match_error_shape(contract: GatewayContract, result: CallResult) -> None:
    """A live tool failure carries the frozen fields, a known category, and a matching flag.

    Extra fields are allowed. The frozen file names `error_category` and `is_retryable`;
    the gateway also sends a fixed `message`, which is not part of the shape this checks.
    A success is not an error shape. `is_retryable` is true only for a category the
    contract lists as retryable, which today is `transient` and nothing else.
    """
    if not result.is_error:
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="errors")
    for field in contract.errors.fields:
        if field not in result.structured:
            raise ErpError(ErpCode.CONTRACT_DRIFT, part="errors")
    category = result.structured.get("error_category")
    retryable = result.structured.get("is_retryable")
    if not isinstance(category, str) or category not in contract.errors.categories:
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="errors")
    if not isinstance(retryable, bool):
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="errors")
    if retryable != (category in contract.errors.retryable_categories):
        raise ErpError(ErpCode.CONTRACT_DRIFT, part="errors")
