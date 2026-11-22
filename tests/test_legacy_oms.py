"""The Harbor OMS sample is the tree its generator writes."""

from __future__ import annotations

import difflib
import importlib.util
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample" / "legacy-oms"
MANIFEST = ROOT / "sample" / "legacy_oms_manifest.json"
GENERATOR = ROOT / "sample" / "generate_legacy_oms.py"

JNDI_LINE = '        return (DataSource) naming.lookup("java:comp/env/jdbc/OrderDS");'
JNDI_CLASSES = (
    "src/com/harbor/oms/catalog/CatalogAdminBean.java",
    "src/com/harbor/oms/customer/CustomerBean.java",
    "src/com/harbor/oms/fulfillment/FulfillmentServiceBean.java",
    "src/com/harbor/oms/inventory/InventoryServiceBean.java",
    "src/com/harbor/oms/order/OrderServiceBean.java",
    "src/com/harbor/oms/order/SalesOrderBean.java",
    "src/com/harbor/oms/pricing/PricingServiceBean.java",
    "src/com/harbor/oms/product/ProductBean.java",
    "src/com/harbor/oms/shipment/ShipmentBean.java",
)
ORDER_DAO = "src/com/harbor/oms/dao/OrderDao.java"
PRICING_BEAN = "src/com/harbor/oms/pricing/PricingServiceBean.java"
CATALOG_BEAN = "src/com/harbor/oms/catalog/CatalogAdminBean.java"
PLAIN_SERVLETS = (
    "src/com/harbor/oms/web/OrderEntryServlet.java",
    "src/com/harbor/oms/web/OrderStatusServlet.java",
)
BANNED = (
    "PLANTED",
    "planted problem",
    "self_managed",
    "sql_concatenation",
    "legacy_oms_manifest",
    "generate_legacy_oms",
    "/etc/passwd",
)

Generate = Callable[[Path, Path], tuple[int, int]]


def load_generate() -> Generate:
    spec = importlib.util.spec_from_file_location("generate_legacy_oms", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the Harbor OMS generator")
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    loaded = cast(object, module.__dict__["generate"])
    if not callable(loaded):
        raise RuntimeError("generator has no generate function")
    return cast(Generate, loaded)


def tree_bytes(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError(f"symlink in the sample tree: {path}")
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def test_generator_reproduces_the_committed_tree(tmp_path: Path) -> None:
    sample = SAMPLE.resolve()
    assert sample.is_dir()
    assert not MANIFEST.resolve().is_relative_to(sample)
    assert not GENERATOR.resolve().is_relative_to(sample)
    out = tmp_path / "legacy-oms"
    file_count, line_count = load_generate()(MANIFEST, out)
    committed = tree_bytes(sample)
    fresh = tree_bytes(out)
    assert set(committed) == set(fresh)
    assert file_count == len(fresh)
    counted = sum(payload.count(b"\n") for payload in fresh.values())
    assert line_count == counted
    mismatches = [rel for rel in sorted(committed) if committed[rel] != fresh[rel]]
    if mismatches:
        chunks: list[str] = []
        for rel in mismatches[:3]:
            left = committed[rel].decode("utf-8").splitlines(keepends=True)
            right = fresh[rel].decode("utf-8").splitlines(keepends=True)
            chunks.extend(
                difflib.unified_diff(
                    left,
                    right,
                    fromfile=f"committed/{rel}",
                    tofile=f"generated/{rel}",
                )
            )
        pytest.fail("".join(chunks))
    assert 42 <= file_count <= 60
    assert 5500 <= line_count <= 8000
    for name in ("dd/ejb-jar.xml", "dd/weblogic-ejb-jar.xml", "build.xml", "web/index.jsp"):
        assert name in committed


def test_generator_refuses_an_existing_output_directory(tmp_path: Path) -> None:
    out = tmp_path / "legacy-oms"
    out.mkdir()
    with pytest.raises(ValueError, match="output already exists"):
        load_generate()(MANIFEST, out)


def test_sample_files_are_plain_utf8_text() -> None:
    files = tree_bytes(SAMPLE)
    assert files
    for rel, payload in files.items():
        assert b"\x00" not in payload, rel
        assert b"\r" not in payload, rel
        assert payload.endswith(b"\n"), rel
        text = payload.decode("utf-8")
        for banned in BANNED:
            assert banned not in text, f"{rel} contains {banned}"


def test_jndi_lookup_is_copied_into_nine_classes() -> None:
    hits: list[str] = []
    for rel, payload in tree_bytes(SAMPLE).items():
        if not rel.endswith(".java"):
            continue
        count = payload.decode("utf-8").count(JNDI_LINE)
        if count:
            hits.append(rel)
            assert count == 1, rel
    assert sorted(hits) == sorted(JNDI_CLASSES)
    assert len(hits) == 9


def test_pricing_service_declares_container_and_begins_a_user_transaction() -> None:
    files = tree_bytes(SAMPLE)
    holders = sorted(rel for rel, payload in files.items() if b"getUserTransaction()" in payload)
    assert holders == [PRICING_BEAN]
    pricing = files[PRICING_BEAN].decode("utf-8")
    assert "transaction.begin()" in pricing
    assert "transaction.commit()" in pricing
    xml = files["dd/ejb-jar.xml"].decode("utf-8")
    assert "<transaction-type>Bean</transaction-type>" not in xml
    declared = re.search(
        r"<ejb-name>PricingService</ejb-name>.*?<transaction-type>(.*?)</transaction-type>",
        xml,
        re.DOTALL,
    )
    assert declared is not None
    assert declared.group(1) == "Container"
    required = re.compile(
        r"<container-transaction>\s*<method>\s*"
        r"<ejb-name>PricingService</ejb-name>\s*"
        r"<method-name>applyPriceOverride</method-name>\s*"
        r"</method>\s*"
        r"<trans-attribute>Required</trans-attribute>"
    )
    assert required.search(xml)


def test_order_dao_builds_sql_by_concatenation() -> None:
    files = tree_bytes(SAMPLE)
    text = files[ORDER_DAO].decode("utf-8")
    assert "findByCustomerAndStatus" in text
    assert "FROM sales_order WHERE customer_id = '\" + customerId + \"'" in text
    assert "AND status_code = '\" + statusCode + \"'" in text
    assert "createStatement()" in text
    assert "executeQuery(sql)" in text
    others = [
        rel
        for rel, payload in files.items()
        if rel != ORDER_DAO and b"createStatement()" in payload
    ]
    assert others == []


def test_catalog_admin_serves_http_and_writes_a_row() -> None:
    files = tree_bytes(SAMPLE)
    both: list[str] = []
    plain: list[str] = []
    for rel, payload in files.items():
        text = payload.decode("utf-8")
        extends = "extends HttpServlet" in text
        session = "implements SessionBean" in text
        if extends and session:
            both.append(rel)
        elif extends:
            plain.append(rel)
    assert both == [CATALOG_BEAN]
    catalog = files[CATALOG_BEAN].decode("utf-8")
    assert "doGet(" in catalog
    assert "doPost(" in catalog
    assert "executeUpdate()" in catalog
    assert sorted(plain) == sorted(PLAIN_SERVLETS)
    web = files["web/WEB-INF/web.xml"].decode("utf-8")
    assert "com.harbor.oms.catalog.CatalogAdminBean" in web
    ejb = files["dd/ejb-jar.xml"].decode("utf-8")
    assert "<ejb-class>com.harbor.oms.catalog.CatalogAdminBean</ejb-class>" in ejb
