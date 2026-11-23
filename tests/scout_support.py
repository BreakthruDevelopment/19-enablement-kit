"""Shared helpers for the scout tests: the sample, a scripted model, and a leak check."""

from __future__ import annotations

import asyncio
import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agent_container.core.messages import ModelRequest, ModelResponse, Usage
from agent_container.core.provider import ModelProvider
from agent_container.core.replay import ReplayProvider

from kit.core.config import SandboxLimits
from kit.core.principals import Principal
from kit.scout import ScoutResult, open_sandbox, run_scout

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "sample" / "legacy-oms"
MANIFEST = ROOT / "sample" / "legacy_oms_manifest.json"
GENERATOR = ROOT / "sample" / "generate_legacy_oms.py"
DEMO_REPLIES = ROOT / "fixtures" / "scout-brief" / "demo" / "replies"

B = "src/com/harbor/oms/"
DAO = B + "dao/OrderDao.java"
PRICING = B + "pricing/PricingServiceBean.java"
CATALOG = B + "catalog/CatalogAdminBean.java"
JNDI_CLASSES = tuple(
    B + name
    for name in (
        "catalog/CatalogAdminBean.java",
        "customer/CustomerBean.java",
        "fulfillment/FulfillmentServiceBean.java",
        "inventory/InventoryServiceBean.java",
        "order/OrderServiceBean.java",
        "order/SalesOrderBean.java",
        "pricing/PricingServiceBean.java",
        "product/ProductBean.java",
        "shipment/ShipmentBean.java",
    )
)
SEEDS = ("build.xml", "build.properties", "dd/ejb-jar.xml", "dd/weblogic-ejb-jar.xml")
DAO_FILES = tuple(
    B + f"dao/{name}Dao.java" for name in ("Customer", "Order", "Product", "Shipment")
)

JNDI_QUOTE = 'return (DataSource) naming.lookup("java:comp/env/jdbc/OrderDS");'
TX_QUOTE = "UserTransaction transaction = sessionContext.getUserTransaction();"
SQL_QUOTE = '"FROM sales_order WHERE customer_id = \'" + customerId + "\' "'
HTTP_QUOTE = "public class CatalogAdminBean extends HttpServlet implements SessionBean {"

ENGINEER = Principal.engineer("tester")


def demo_brief() -> dict[str, Any]:
    """The recorded reply's brief, as a dict a test can bend."""
    recording = json.loads((DEMO_REPLIES / "brief.json").read_text("utf-8"))
    brief = json.loads(recording["replies"][0]["text"])
    assert isinstance(brief, dict)
    return brief


def brief_reply(brief: dict[str, Any]) -> ModelResponse:
    return ModelResponse.of(json.dumps(brief), usage=Usage(100, 50))


class Scripted(ModelProvider):
    """Answers every call with one fixed reply, or raises; records the requests it saw."""

    def __init__(self, response: ModelResponse | Exception) -> None:
        self.response = response
        self.requests: list[ModelRequest] = []

    async def converse(self, request: ModelRequest) -> ModelResponse:
        await asyncio.sleep(0)
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def demo_provider() -> ReplayProvider:
    return ReplayProvider.from_file(DEMO_REPLIES / "brief.json")


def scout(
    root: Path,
    provider: ModelProvider | None = None,
    *,
    principal: Principal = ENGINEER,
    limits: SandboxLimits | None = None,
) -> ScoutResult:
    """Run a scout the way `kit scout` does: through `open_sandbox`."""
    sandbox = open_sandbox(principal, root, limits)
    return asyncio.run(run_scout(sandbox, provider if provider is not None else demo_provider()))


def copy_sample(destination: Path) -> Path:
    """A writable copy of the sample, for tests that plant escape fixtures in it."""
    target = destination / "oms"
    shutil.copytree(SAMPLE, target)
    return target


def everything(result: ScoutResult, *requests: ModelRequest) -> str:
    """All the text a run produced or sent: the brief, every step, and every prompt."""
    parts = [json.dumps(result.as_dict(), ensure_ascii=False)]
    for request in requests:
        parts.append(request.system)
        parts.extend(
            block.text
            for message in request.messages
            for block in message.content
            if hasattr(block, "text")
        )
    return "\n".join(parts)


def leaks(marker: str, *haystacks: str) -> bool:
    return any(marker in text for text in haystacks)


def requests_of(provider: ModelProvider) -> list[ModelRequest]:
    found = getattr(provider, "requests", None)
    assert isinstance(found, list)
    return list(found)


def size_of(root: Path, names: Iterable[str]) -> int:
    return sum(len((root / name).read_bytes()) for name in names)


def as_json(result: ScoutResult) -> str:
    return json.dumps(result.as_dict(), ensure_ascii=False)
