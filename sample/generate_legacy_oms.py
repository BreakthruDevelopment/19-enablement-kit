"""Generate the committed Harbor OMS sample from its manifest.

The tree under ``sample/legacy-oms`` is a synthetic Java EE order desk written
for this repository. This script is the record of that tree. It plants four
problems the scout is expected to cite from the generated source:

1. The same JDBC JNDI lookup is copied into nine classes: every entity bean
   and every stateless session bean.
2. ``PricingService`` is container-managed in ``ejb-jar.xml`` (the
   ``applyPriceOverride`` method is ``Required``), and ``PricingServiceBean``
   begins and commits its own ``UserTransaction``.
3. ``OrderDao.findByCustomerAndStatus`` builds SQL by concatenating the
   caller's strings.
4. ``CatalogAdminBean`` is a session bean that also serves HTTP and writes
   the product table through JDBC.

The manifest stays outside ``sample/legacy-oms``. The generator does not
create symlinks. Nothing under ``kit/core/`` is touched, and nothing from
app 17 is imported.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

JAVA_PACKAGE = "com.harbor.oms"
DATASOURCE_JNDI = "java:comp/env/jdbc/OrderDS"
GLOBAL_JNDI = "jdbc/HarborOrderDS"
JNDI_CLASS_COUNT = 9
TX_EJB = "PricingService"
TX_METHOD = "applyPriceOverride"
CONCAT_DAO = "OrderDao"
CONCAT_METHOD = "findByCustomerAndStatus"
HTTP_EJB = "CatalogAdmin"
JAVA_IDENT = re.compile(r"[A-Za-z][A-Za-z0-9]*")
SQL_IDENT = re.compile(r"[a-z][a-z0-9_]*")
SQL_TYPE = re.compile(r"[A-Z0-9(),]+")
SUBPACKAGE = re.compile(r"[a-z]+")
URL_PATH = re.compile(r"/[a-z0-9./-]*")

ENTITY_FIELDS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "Customer": (
        ("customerId", "customer_id", "String", "VARCHAR(32)"),
        ("legalName", "legal_name", "String", "VARCHAR(120)"),
        ("regionCode", "region_code", "String", "VARCHAR(8)"),
        ("creditLimitCents", "credit_limit_cents", "long", "BIGINT"),
        ("statusCode", "status_code", "String", "VARCHAR(16)"),
        ("buyerName", "buyer_name", "String", "VARCHAR(80)"),
        ("city", "city", "String", "VARCHAR(80)"),
        ("openedOn", "opened_on", "String", "VARCHAR(10)"),
    ),
    "Product": (
        ("sku", "sku", "String", "VARCHAR(32)"),
        ("description", "description", "String", "VARCHAR(200)"),
        ("unitPriceCents", "unit_price_cents", "long", "BIGINT"),
        ("onHand", "on_hand", "int", "INTEGER"),
        ("warehouseCode", "warehouse_code", "String", "VARCHAR(16)"),
        ("reorderPoint", "reorder_point", "int", "INTEGER"),
        ("activeFlag", "active_flag", "String", "VARCHAR(1)"),
        ("vendorCode", "vendor_code", "String", "VARCHAR(32)"),
    ),
    "SalesOrder": (
        ("orderId", "order_id", "String", "VARCHAR(32)"),
        ("customerId", "customer_id", "String", "VARCHAR(32)"),
        ("statusCode", "status_code", "String", "VARCHAR(16)"),
        ("placedOn", "placed_on", "String", "VARCHAR(10)"),
        ("requestedShip", "requested_ship", "String", "VARCHAR(10)"),
        ("totalCents", "total_cents", "long", "BIGINT"),
        ("currencyCode", "currency_code", "String", "VARCHAR(3)"),
        ("buyerPo", "buyer_po", "String", "VARCHAR(40)"),
        ("warehouseCode", "warehouse_code", "String", "VARCHAR(16)"),
        ("lineSku", "line_sku", "String", "VARCHAR(32)"),
        ("lineQuantity", "line_quantity", "int", "INTEGER"),
    ),
    "Shipment": (
        ("shipmentId", "shipment_id", "String", "VARCHAR(32)"),
        ("orderId", "order_id", "String", "VARCHAR(32)"),
        ("carrier", "carrier", "String", "VARCHAR(40)"),
        ("trackingNo", "tracking_no", "String", "VARCHAR(40)"),
        ("shippedOn", "shipped_on", "String", "VARCHAR(10)"),
        ("statusCode", "status_code", "String", "VARCHAR(16)"),
        ("weightGrams", "weight_grams", "int", "INTEGER"),
        ("dockDoor", "dock_door", "String", "VARCHAR(16)"),
    ),
}

ENTITY_METHODS: dict[str, tuple[str, ...]] = {
    "Customer": ("placeOnHold", "releaseHold"),
    "Product": ("reserve", "release"),
    "SalesOrder": ("cancel", "attachBuyerPo"),
    "Shipment": ("markShipped", "markDelivered"),
}

SESSION_METHODS: dict[str, tuple[str, ...]] = {
    "OrderService": (
        "placeOrder",
        "cancelOrder",
        "findOrdersForCustomer",
        "attachBuyerPo",
    ),
    "InventoryService": (
        "onHand",
        "reserveStock",
        "releaseStock",
        "belowReorder",
    ),
    "PricingService": (
        "quote",
        "applyPriceOverride",
        "priceBookForRegion",
    ),
    "FulfillmentService": (
        "createShipment",
        "markShipped",
        "markDelivered",
        "findShipments",
    ),
    "CatalogAdmin": (
        "addProduct",
        "discontinueProduct",
        "updateWarehouse",
    ),
}

SESSION_REFS: dict[str, tuple[str, ...]] = {
    "OrderService": ("Customer", "Product", "SalesOrder"),
    "InventoryService": ("Product",),
    "PricingService": ("Product",),
    "FulfillmentService": ("SalesOrder", "Shipment"),
    "CatalogAdmin": ("Product",),
}

SESSION_POOL: dict[str, int] = {
    "OrderService": 30,
    "InventoryService": 20,
    "PricingService": 15,
    "FulfillmentService": 20,
    "CatalogAdmin": 10,
}

ENTITY_ORDER = ("Customer", "Product", "SalesOrder", "Shipment")
SESSION_ORDER = (
    "OrderService",
    "InventoryService",
    "PricingService",
    "FulfillmentService",
    "CatalogAdmin",
)
SERVLET_ORDER = ("OrderEntryServlet", "OrderStatusServlet")

BANNED_OUTPUT = (
    "planted problem",
    "PLANTED",
    "self_managed",
    "sql_concatenation",
    "legacy_oms_manifest",
    "generate_legacy_oms",
)


@dataclass(frozen=True)
class Field:
    name: str
    column: str
    java_type: str
    sql_type: str


@dataclass(frozen=True)
class Entity:
    name: str
    subpackage: str
    table: str
    dao: str
    description: str
    business_methods: tuple[str, ...]
    fields: tuple[Field, ...]

    def fqcn(self, root: str) -> str:
        return f"{root}.{self.subpackage}.{self.name}"

    def pk(self) -> Field:
        return self.fields[0]


@dataclass(frozen=True)
class Session:
    name: str
    subpackage: str
    description: str
    pool: int
    entity_refs: tuple[str, ...]
    methods: tuple[str, ...]

    def fqcn(self, root: str) -> str:
        return f"{root}.{self.subpackage}.{self.name}"


@dataclass(frozen=True)
class Servlet:
    name: str
    url: str
    ejb_ref: str
    description: str


@dataclass(frozen=True)
class Planted:
    jndi_class_count: int
    self_managed_transaction_ejb: str
    self_managed_transaction_method: str
    sql_concatenation_dao: str
    sql_concatenation_method: str
    http_database_ejb: str


@dataclass(frozen=True)
class Manifest:
    app_name: str
    java_package: str
    datasource_jndi: str
    datasource_global_jndi: str
    ear: str
    ejb_jar: str
    web_war: str
    context_root: str
    planted: Planted
    entities: tuple[Entity, ...]
    sessions: tuple[Session, ...]
    servlets: tuple[Servlet, ...]

    def entity(self, name: str) -> Entity:
        for item in self.entities:
            if item.name == name:
                return item
        raise ValueError(f"unknown entity {name}")

    def session(self, name: str) -> Session:
        for item in self.sessions:
            if item.name == name:
                return item
        raise ValueError(f"unknown session {name}")


def as_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    out: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        out[key] = item
    return out


def as_array(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a JSON array")
    return list(value)


def as_str(value: object, label: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{label} must be a non-empty string")
    return value


def as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def exact_keys(value: Mapping[str, object], keys: set[str], label: str) -> None:
    missing = sorted(keys - set(value))
    extra = sorted(set(value) - keys)
    if missing or extra:
        raise ValueError(f"{label} keys mismatch, missing={missing} extra={extra}")


def require_text(value: str, label: str, limit: int) -> str:
    if len(value) > limit or "\n" in value or "*/" in value or "/*" in value:
        raise ValueError(f"{label} is empty, too long, or not a single safe line")
    return value


def load_manifest(path: Path) -> Manifest:
    raw = as_object(json.loads(path.read_text(encoding="utf-8")), "manifest")
    exact_keys(
        raw,
        {
            "app_name",
            "java_package",
            "datasource_jndi",
            "datasource_global_jndi",
            "ear",
            "ejb_jar",
            "web_war",
            "context_root",
            "planted",
            "entities",
            "sessions",
            "servlets",
        },
        "manifest",
    )
    planted_raw = as_object(raw["planted"], "planted")
    exact_keys(
        planted_raw,
        {
            "jndi_class_count",
            "self_managed_transaction_ejb",
            "self_managed_transaction_method",
            "sql_concatenation_dao",
            "sql_concatenation_method",
            "http_database_ejb",
        },
        "planted",
    )
    planted = Planted(
        jndi_class_count=as_int(planted_raw["jndi_class_count"], "jndi_class_count"),
        self_managed_transaction_ejb=as_str(
            planted_raw["self_managed_transaction_ejb"],
            "self_managed_transaction_ejb",
        ),
        self_managed_transaction_method=as_str(
            planted_raw["self_managed_transaction_method"],
            "self_managed_transaction_method",
        ),
        sql_concatenation_dao=as_str(
            planted_raw["sql_concatenation_dao"],
            "sql_concatenation_dao",
        ),
        sql_concatenation_method=as_str(
            planted_raw["sql_concatenation_method"],
            "sql_concatenation_method",
        ),
        http_database_ejb=as_str(planted_raw["http_database_ejb"], "http_database_ejb"),
    )
    if planted.jndi_class_count != JNDI_CLASS_COUNT:
        raise ValueError("the planted JNDI lookup must be repeated in nine classes")
    if (
        planted.self_managed_transaction_ejb != TX_EJB
        or planted.self_managed_transaction_method != TX_METHOD
    ):
        raise ValueError("the self-managed transaction must be PricingService.applyPriceOverride")
    if (
        planted.sql_concatenation_dao != CONCAT_DAO
        or planted.sql_concatenation_method != CONCAT_METHOD
    ):
        raise ValueError("SQL concatenation must be OrderDao.findByCustomerAndStatus")
    if planted.http_database_ejb != HTTP_EJB:
        raise ValueError("the HTTP-and-database EJB must be CatalogAdmin")
    java_package = as_str(raw["java_package"], "java_package")
    if java_package != JAVA_PACKAGE:
        raise ValueError("java_package must be com.harbor.oms")
    datasource = as_str(raw["datasource_jndi"], "datasource_jndi")
    global_jndi = as_str(raw["datasource_global_jndi"], "datasource_global_jndi")
    if datasource != DATASOURCE_JNDI or global_jndi != GLOBAL_JNDI:
        raise ValueError("datasource JNDI names drifted from the planted lookup")
    entities = tuple(
        load_entity(item, index) for index, item in enumerate(as_array(raw["entities"], "entities"))
    )
    sessions = tuple(
        load_session(item, index)
        for index, item in enumerate(as_array(raw["sessions"], "sessions"))
    )
    servlets = tuple(
        load_servlet(item, index)
        for index, item in enumerate(as_array(raw["servlets"], "servlets"))
    )
    if tuple(item.name for item in entities) != ENTITY_ORDER:
        raise ValueError("entities must be Customer, Product, SalesOrder, Shipment")
    if tuple(item.name for item in sessions) != SESSION_ORDER:
        raise ValueError("session list drifted")
    if tuple(item.name for item in servlets) != SERVLET_ORDER:
        raise ValueError("servlet list drifted")
    manifest = Manifest(
        app_name=require_text(as_str(raw["app_name"], "app_name"), "app_name", 40),
        java_package=java_package,
        datasource_jndi=datasource,
        datasource_global_jndi=global_jndi,
        ear=as_str(raw["ear"], "ear"),
        ejb_jar=as_str(raw["ejb_jar"], "ejb_jar"),
        web_war=as_str(raw["web_war"], "web_war"),
        context_root=as_str(raw["context_root"], "context_root"),
        planted=planted,
        entities=entities,
        sessions=sessions,
        servlets=servlets,
    )
    for name in (manifest.ear, manifest.ejb_jar, manifest.web_war):
        if not re.fullmatch(r"[a-z0-9.-]+", name):
            raise ValueError(f"archive name is not safe: {name}")
    if not re.fullmatch(r"[a-z0-9-]+", manifest.context_root):
        raise ValueError("context_root is not a single path segment")
    known = {item.name for item in entities}
    for session in sessions:
        for ref in session.entity_refs:
            if ref not in known:
                raise ValueError(f"{session.name} refs unknown entity {ref}")
    for servlet in servlets:
        manifest.session(servlet.ejb_ref)
    return manifest


def load_entity(value: object, index: int) -> Entity:
    raw = as_object(value, f"entities[{index}]")
    exact_keys(
        raw,
        {
            "name",
            "subpackage",
            "table",
            "dao",
            "description",
            "business_methods",
            "fields",
        },
        f"entities[{index}]",
    )
    name = as_str(raw["name"], "entity name")
    if name not in ENTITY_FIELDS:
        raise ValueError(f"unexpected entity {name}")
    fields = tuple(
        load_field(item, index, name)
        for index, item in enumerate(as_array(raw["fields"], f"{name}.fields"))
    )
    expected = tuple(Field(item[0], item[1], item[2], item[3]) for item in ENTITY_FIELDS[name])
    if fields != expected:
        raise ValueError(f"{name} fields drifted from the generator's SQL")
    methods = tuple(
        as_str(item, f"{name} business method")
        for item in as_array(raw["business_methods"], f"{name}.business_methods")
    )
    if methods != ENTITY_METHODS[name]:
        raise ValueError(f"{name} business methods drifted")
    subpackage = as_str(raw["subpackage"], f"{name}.subpackage")
    table = as_str(raw["table"], f"{name}.table")
    dao = as_str(raw["dao"], f"{name}.dao")
    if not SUBPACKAGE.fullmatch(subpackage) or not SQL_IDENT.fullmatch(table):
        raise ValueError(f"{name} package or table is not an identifier")
    if not JAVA_IDENT.fullmatch(dao):
        raise ValueError(f"{name} dao name is not an identifier")
    return Entity(
        name=name,
        subpackage=subpackage,
        table=table,
        dao=dao,
        description=require_text(as_str(raw["description"], f"{name}.description"), name, 88),
        business_methods=methods,
        fields=fields,
    )


def load_field(value: object, index: int, entity: str) -> Field:
    raw = as_object(value, f"{entity}.fields[{index}]")
    exact_keys(
        raw,
        {"name", "column", "java_type", "sql_type"},
        f"{entity}.fields[{index}]",
    )
    name = as_str(raw["name"], "field name")
    column = as_str(raw["column"], "column")
    java_type = as_str(raw["java_type"], "java_type")
    sql_type = as_str(raw["sql_type"], "sql_type")
    if java_type not in {"String", "int", "long"}:
        raise ValueError(f"unsupported Java type {java_type}")
    if not JAVA_IDENT.fullmatch(name) or not SQL_IDENT.fullmatch(column):
        raise ValueError(f"bad field identifier {name}")
    if not SQL_TYPE.fullmatch(sql_type):
        raise ValueError(f"bad sql type {sql_type}")
    return Field(name, column, java_type, sql_type)


def load_session(value: object, index: int) -> Session:
    raw = as_object(value, f"sessions[{index}]")
    exact_keys(
        raw,
        {"name", "subpackage", "description", "pool", "entity_refs", "methods"},
        f"sessions[{index}]",
    )
    name = as_str(raw["name"], "session name")
    if name not in SESSION_METHODS:
        raise ValueError(f"unexpected session {name}")
    methods = tuple(
        as_str(item, f"{name} method") for item in as_array(raw["methods"], f"{name}.methods")
    )
    refs = tuple(
        as_str(item, f"{name} ref") for item in as_array(raw["entity_refs"], f"{name}.entity_refs")
    )
    if methods != SESSION_METHODS[name] or refs != SESSION_REFS[name]:
        raise ValueError(f"{name} methods or entity refs drifted")
    pool = as_int(raw["pool"], f"{name}.pool")
    if pool != SESSION_POOL[name]:
        raise ValueError(f"{name} pool drifted")
    subpackage = as_str(raw["subpackage"], f"{name}.subpackage")
    if not SUBPACKAGE.fullmatch(subpackage):
        raise ValueError(f"{name} subpackage is not an identifier")
    return Session(
        name=name,
        subpackage=subpackage,
        description=require_text(as_str(raw["description"], f"{name}.description"), name, 88),
        pool=pool,
        entity_refs=refs,
        methods=methods,
    )


def load_servlet(value: object, index: int) -> Servlet:
    raw = as_object(value, f"servlets[{index}]")
    exact_keys(
        raw,
        {"name", "url", "ejb_ref", "description"},
        f"servlets[{index}]",
    )
    name = as_str(raw["name"], "servlet name")
    url = as_str(raw["url"], "servlet url")
    if name not in SERVLET_ORDER or not URL_PATH.fullmatch(url):
        raise ValueError(f"unexpected servlet {name} {url}")
    return Servlet(
        name=name,
        url=url,
        ejb_ref=as_str(raw["ejb_ref"], "ejb_ref"),
        description=require_text(as_str(raw["description"], f"{name}.description"), name, 88),
    )


def cap(name: str) -> str:
    return name[:1].upper() + name[1:]


def camel(name: str) -> str:
    return name[:1].lower() + name[1:]


def java_path(subpackage: str, class_name: str) -> str:
    dotted = f"{JAVA_PACKAGE}.{subpackage}.{class_name}"
    return "src/" + dotted.replace(".", "/") + ".java"


def finish(lines: Sequence[str]) -> str:
    cleaned = [line.rstrip() for line in lines]
    text = "\n".join(cleaned) + "\n"
    if "\t" in text or "\r" in text:
        raise ValueError("generated text contains a tab or CR")
    return text


def check_balance(rel: str, text: str) -> None:
    braces = 0
    parens = 0
    for char in text:
        if char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        elif char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
        if braces < 0 or parens < 0:
            raise ValueError(f"unbalanced brackets in {rel}")
    if braces != 0 or parens != 0:
        raise ValueError(f"unbalanced brackets in {rel}: braces={braces} parens={parens}")


def java_file(package: str, imports: Sequence[str], body: Sequence[str]) -> str:
    lines = [
        "/*",
        " * Harbor OMS. Synthetic order-management code written for this repository.",
        " */",
        f"package {package};",
        "",
    ]
    grouped: dict[str, list[str]] = {"java": [], "javax": [], "com": []}
    for item in sorted(set(imports)):
        prefix = item.split(".", 1)[0]
        if prefix not in grouped:
            raise ValueError(f"unexpected import root {item}")
        grouped[prefix].append(item)
    started = False
    for key in ("java", "javax", "com"):
        block = grouped[key]
        if not block:
            continue
        if started:
            lines.append("")
        started = True
        for item in block:
            lines.append(f"import {item};")
    if started:
        lines.append("")
    lines.extend(body)
    return finish(lines)


def sql_chunks(sql: str, width: int = 46) -> list[str]:
    parts: list[str] = []
    rest = sql
    while rest:
        if len(rest) <= width:
            parts.append(rest)
            break
        cut = rest.rfind(" ", 0, width)
        if cut <= 0:
            raise ValueError(f"cannot wrap SQL: {sql}")
        parts.append(rest[:cut] + " ")
        rest = rest[cut + 1 :]
    return parts


def sql_expr(sql: str) -> list[str]:
    parts = sql_chunks(sql)
    lines: list[str] = []
    for index, part in enumerate(parts):
        literal = '"' + part + '"'
        if index == 0:
            lines.append(f"                {literal}")
        else:
            lines.append(f"                        + {literal}")
    lines[-1] = lines[-1] + ");"
    return lines


def sql_statement(*parts: str) -> str:
    """Join SQL fragments. Identifiers were validated when the manifest loaded."""
    return " ".join(part.strip() for part in parts if part != "")


def prepare_call(sql: str) -> list[str]:
    return [
        "        PreparedStatement statement = connection.prepareStatement(",
        *sql_expr(sql),
    ]


def jndi_lookup_lines(jndi: str) -> list[str]:
    return [
        "    private DataSource lookupOrderDataSource() throws NamingException {",
        "        InitialContext naming = new InitialContext();",
        f'        return (DataSource) naming.lookup("{jndi}");',
        "    }",
    ]


def close_lines() -> list[str]:
    return [
        "    private void close(Connection connection) {",
        "        if (connection == null) {",
        "            return;",
        "        }",
        "        try {",
        "            connection.close();",
        "        } catch (SQLException failure) {",
        '            throw new EJBException("failed to close a JDBC connection", failure);',
        "        }",
        "    }",
    ]


def class_doc(description: str) -> list[str]:
    return ["/**", f" * {description}", " */"]


def setter_name(java_type: str) -> str:
    return {"String": "setString", "int": "setInt", "long": "setLong"}[java_type]


def getter_name(java_type: str) -> str:
    return {"String": "getString", "int": "getInt", "long": "getLong"}[java_type]


def select_list(entity: Entity) -> str:
    return ", ".join(field.column for field in entity.fields)


def column_of(entity: Entity, field_name: str) -> str:
    for field in entity.fields:
        if field.name == field_name:
            return field.column
    raise ValueError(f"{entity.name} has no field {field_name}")


def render_row(entity: Entity) -> list[str]:
    lines = [
        "    /** Column holder passed between the bean and this DAO. */",
        "    public static final class Row {",
    ]
    for field in entity.fields:
        lines.append(f"        private {field.java_type} {field.name};")
    lines.append("")
    for field in entity.fields:
        lines.extend(row_accessors(field))
    lines.append("    }")
    return lines


def bean_accessors(field: Field, *, primary: bool) -> list[str]:
    name = cap(field.name)
    lines = [
        "    /**",
        f"     * Return the stored {field.column}.",
        "     */",
        f"    public {field.java_type} get{name}() {{",
        f"        return {field.name};",
        "    }",
        "",
    ]
    if primary:
        return lines
    lines.extend(
        [
            "    /**",
            f"     * Replace the stored {field.column}.",
            "     */",
            f"    public void set{name}({field.java_type} value) {{",
            f"        this.{field.name} = value;",
            "    }",
            "",
        ]
    )
    return lines


def row_accessors(field: Field) -> list[str]:
    name = cap(field.name)
    return [
        "        /**",
        f"         * Return the stored {field.column}.",
        "         */",
        f"        public {field.java_type} get{name}() {{",
        f"            return {field.name};",
        "        }",
        "",
        "        /**",
        f"         * Replace the stored {field.column}.",
        "         */",
        f"        public void set{name}({field.java_type} value) {{",
        f"            this.{field.name} = value;",
        "        }",
        "",
    ]


def render_read(entity: Entity) -> list[str]:
    lines = [
        "    private Row read(ResultSet rows) throws SQLException {",
        "        Row row = new Row();",
    ]
    for index, field in enumerate(entity.fields, start=1):
        call = getter_name(field.java_type)
        lines.append(f"        row.set{cap(field.name)}(rows.{call}({index}));")
    lines.extend(["        return row;", "    }"])
    return lines


def render_dao(manifest: Manifest, entity: Entity) -> str:
    root = manifest.java_package
    package = f"{root}.dao"
    columns = select_list(entity)
    pk = entity.pk()
    setters = [field for field in entity.fields if field.name != pk.name]
    imports = [
        "java.sql.Connection",
        "java.sql.PreparedStatement",
        "java.sql.ResultSet",
        "java.sql.SQLException",
    ]
    if entity.dao in {CONCAT_DAO, "ProductDao", "ShipmentDao"}:
        imports.extend(["java.util.ArrayList", "java.util.List"])
    lines = [
        *class_doc(f"JDBC access to {entity.table}. Callers pass an open connection and close it."),
        f"public final class {entity.dao} {{",
        "",
        *render_row(entity),
        "",
        f"    public {entity.dao}() {{",
        "    }",
        "",
        "    public void insert(Connection connection, Row row) throws SQLException {",
        *prepare_call(
            sql_statement(
                "INSERT INTO",
                entity.table,
                "(" + columns + ")",
                "VALUES",
                "(" + ", ".join("?" for _ in entity.fields) + ")",
            )
        ),
        "        try {",
    ]
    for index, field in enumerate(entity.fields, start=1):
        call = setter_name(field.java_type)
        lines.append(f"            statement.{call}({index}, row.get{cap(field.name)}());")
    lines.extend(
        [
            "            statement.executeUpdate();",
            "        } finally {",
            "            statement.close();",
            "        }",
            "    }",
            "",
            "    public void update(Connection connection, Row row) throws SQLException {",
            *prepare_call(
                sql_statement(
                    "UPDATE",
                    entity.table,
                    "SET",
                    ", ".join(field.column + " = ?" for field in setters),
                    "WHERE",
                    pk.column + " = ?",
                )
            ),
            "        try {",
        ]
    )
    for index, field in enumerate(setters, start=1):
        call = setter_name(field.java_type)
        lines.append(f"            statement.{call}({index}, row.get{cap(field.name)}());")
    pk_index = len(setters) + 1
    lines.append(
        f"            statement.{setter_name(pk.java_type)}({pk_index}, row.get{cap(pk.name)}());"
    )
    lines.extend(
        [
            "            statement.executeUpdate();",
            "        } finally {",
            "            statement.close();",
            "        }",
            "    }",
            "",
            "    public int delete(Connection connection, String key) throws SQLException {",
            *prepare_call(
                sql_statement(
                    "DELETE FROM",
                    entity.table,
                    "WHERE",
                    pk.column + " = ?",
                )
            ),
            "        try {",
            "            statement.setString(1, key);",
            "            return statement.executeUpdate();",
            "        } finally {",
            "            statement.close();",
            "        }",
            "    }",
            "",
            "    public Row findById(Connection connection, String key) throws SQLException {",
            *prepare_call(
                sql_statement(
                    "SELECT",
                    columns,
                    "FROM",
                    entity.table,
                    "WHERE",
                    pk.column + " = ?",
                )
            ),
            "        try {",
            "            statement.setString(1, key);",
            "            ResultSet rows = statement.executeQuery();",
            "            try {",
            "                if (!rows.next()) {",
            "                    return null;",
            "                }",
            "                return read(rows);",
            "            } finally {",
            "                rows.close();",
            "            }",
            "        } finally {",
            "            statement.close();",
            "        }",
            "    }",
            "",
        ]
    )
    lines.extend(extra_dao_methods(manifest, entity))
    lines.extend(["", *render_read(entity), "}"])
    if entity.dao == CONCAT_DAO:
        imports.append("java.sql.Statement")
    if entity.dao == CONCAT_DAO:
        imports.append(f"{root}.order.OrderLine")
    return java_file(package, imports, lines)


def extra_dao_methods(manifest: Manifest, entity: Entity) -> list[str]:
    if entity.dao == CONCAT_DAO:
        return [
            *concat_method(entity),
            "",
            *insert_line_method(),
        ]
    if entity.dao == "ProductDao":
        return find_below_reorder(entity)
    if entity.dao == "ShipmentDao":
        return find_by_order(entity)
    return []


def concat_method(entity: Entity) -> list[str]:
    if entity.table != "sales_order":
        raise ValueError("concatenation DAO must own sales_order")
    customer_col = column_of(entity, "customerId")
    status_col = column_of(entity, "statusCode")
    if customer_col != "customer_id" or status_col != "status_code":
        raise ValueError("concatenation SQL columns drifted")
    select = select_list(entity)
    if "line_sku" not in select or "line_quantity" not in select:
        raise ValueError("order select list drifted")
    return [
        f"    public List<Row> {CONCAT_METHOD}(",
        "            Connection connection, String customerId, String statusCode)",
        "            throws SQLException {",
        '        String sql = "SELECT order_id, customer_id, status_code, placed_on, "',
        '                + "requested_ship, total_cents, currency_code, buyer_po, "',
        '                + "warehouse_code, line_sku, line_quantity "',
        '                + "FROM sales_order WHERE customer_id = \'" + customerId + "\' "',
        '                + "AND status_code = \'" + statusCode + "\' "',
        '                + "ORDER BY placed_on";',
        "        Statement statement = connection.createStatement();",
        "        try {",
        "            ResultSet rows = statement.executeQuery(sql);",
        "            try {",
        "                List<Row> found = new ArrayList<Row>();",
        "                while (rows.next()) {",
        "                    found.add(read(rows));",
        "                }",
        "                return found;",
        "            } finally {",
        "                rows.close();",
        "            }",
        "        } finally {",
        "            statement.close();",
        "        }",
        "    }",
    ]


def insert_line_method() -> list[str]:
    return [
        "    public void insertLine(Connection connection, String orderId, OrderLine line)",
        "            throws SQLException {",
        *prepare_call(
            "INSERT INTO order_line (order_id, line_no, sku, quantity, unit_price_cents) "
            "VALUES (?, 1, ?, ?, ?)"
        ),
        "        try {",
        "            statement.setString(1, orderId);",
        "            statement.setString(2, line.getSku());",
        "            statement.setInt(3, line.getQuantity());",
        "            statement.setLong(4, line.getUnitPriceCents());",
        "            statement.executeUpdate();",
        "        } finally {",
        "            statement.close();",
        "        }",
        "    }",
    ]


def find_below_reorder(entity: Entity) -> list[str]:
    sql = sql_statement(
        "SELECT",
        select_list(entity),
        "FROM",
        entity.table,
        "WHERE warehouse_code = ? AND on_hand <= reorder_point",
        "AND active_flag = 'Y' ORDER BY sku",
    )
    return [
        "    public List<Row> findBelowReorder(Connection connection, String warehouseCode)",
        "            throws SQLException {",
        *prepare_call(sql),
        "        try {",
        "            statement.setString(1, warehouseCode);",
        "            ResultSet rows = statement.executeQuery();",
        "            try {",
        "                List<Row> found = new ArrayList<Row>();",
        "                while (rows.next()) {",
        "                    found.add(read(rows));",
        "                }",
        "                return found;",
        "            } finally {",
        "                rows.close();",
        "            }",
        "        } finally {",
        "            statement.close();",
        "        }",
        "    }",
    ]


def find_by_order(entity: Entity) -> list[str]:
    sql = sql_statement(
        "SELECT",
        select_list(entity),
        "FROM",
        entity.table,
        "WHERE order_id = ? ORDER BY shipment_id",
    )
    return [
        "    public List<Row> findByOrder(Connection connection, String orderId)",
        "            throws SQLException {",
        *prepare_call(sql),
        "        try {",
        "            statement.setString(1, orderId);",
        "            ResultSet rows = statement.executeQuery();",
        "            try {",
        "                List<Row> found = new ArrayList<Row>();",
        "                while (rows.next()) {",
        "                    found.add(read(rows));",
        "                }",
        "                return found;",
        "            } finally {",
        "                rows.close();",
        "            }",
        "        } finally {",
        "            statement.close();",
        "        }",
        "    }",
    ]


def render_remote(manifest: Manifest, entity: Entity) -> str:
    root = manifest.java_package
    lines = [
        *class_doc(entity.description),
        f"public interface {entity.name} extends EJBObject {{",
    ]
    for field in entity.fields:
        lines.extend(
            [
                "",
                f"    /** @return the stored {field.column} */",
                f"    {field.java_type} get{cap(field.name)}() throws RemoteException;",
            ]
        )
        if field.name != entity.pk().name:
            lines.extend(
                [
                    "",
                    f"    /** Store a new {field.column}. */",
                    (
                        f"    void set{cap(field.name)}({field.java_type} value)"
                        " throws RemoteException;"
                    ),
                ]
            )
    for method in entity.business_methods:
        signature = entity_remote_signature(entity.name, method)
        lines.extend(["", f"    {signature} throws OmsException, RemoteException;"])
    lines.append("}")
    return java_file(
        f"{root}.{entity.subpackage}",
        ["java.rmi.RemoteException", "javax.ejb.EJBObject", f"{root}.support.OmsException"],
        lines,
    )


def render_home(manifest: Manifest, entity: Entity) -> str:
    root = manifest.java_package
    params = ", ".join(f"{field.java_type} {field.name}" for field in entity.fields)
    lines = [
        *class_doc(f"Home for {entity.name}. Keys are strings."),
        f"public interface {entity.name}Home extends EJBHome {{",
        "",
        f"    {entity.name} create({params}) throws CreateException, RemoteException;",
        "",
        f"    {entity.name} findByPrimaryKey(String key) throws FinderException, RemoteException;",
        "}",
    ]
    return java_file(
        f"{root}.{entity.subpackage}",
        [
            "java.rmi.RemoteException",
            "javax.ejb.CreateException",
            "javax.ejb.EJBHome",
            "javax.ejb.FinderException",
        ],
        lines,
    )


def entity_remote_signature(entity_name: str, method: str) -> str:
    signatures = {
        ("Customer", "placeOnHold"): "void placeOnHold(String reason)",
        ("Customer", "releaseHold"): "void releaseHold()",
        ("Product", "reserve"): "void reserve(int quantity)",
        ("Product", "release"): "void release(int quantity)",
        ("SalesOrder", "cancel"): "void cancel()",
        ("SalesOrder", "attachBuyerPo"): "void attachBuyerPo(String buyerPo)",
        ("Shipment", "markShipped"): "void markShipped(String trackingNo)",
        ("Shipment", "markDelivered"): "void markDelivered()",
    }
    try:
        return signatures[(entity_name, method)]
    except KeyError as exc:
        raise ValueError(f"no signature for {entity_name}.{method}") from exc


def entity_method_body(entity_name: str, method: str) -> list[str]:
    bodies = {
        ("Customer", "placeOnHold"): [
            "    public void placeOnHold(String reason) throws OmsException {",
            "        if (reason == null || reason.length() == 0) {",
            '            throw new OmsException("a hold reason is required");',
            "        }",
            '        if ("CLOSED".equals(statusCode)) {',
            '            throw new OmsException("closed customers stay closed");',
            "        }",
            '        statusCode = "HOLD";',
            "    }",
        ],
        ("Customer", "releaseHold"): [
            "    public void releaseHold() throws OmsException {",
            '        if (!"HOLD".equals(statusCode)) {',
            '            throw new OmsException("customer is not on hold");',
            "        }",
            '        statusCode = "ACTIVE";',
            "    }",
        ],
        ("Product", "reserve"): [
            "    public void reserve(int quantity) throws OmsException {",
            "        if (quantity <= 0) {",
            '            throw new OmsException("quantity must be positive");',
            "        }",
            "        if (onHand < quantity) {",
            '            throw new OmsException("not enough on hand for " + sku);',
            "        }",
            "        onHand = onHand - quantity;",
            "    }",
        ],
        ("Product", "release"): [
            "    public void release(int quantity) throws OmsException {",
            "        if (quantity <= 0) {",
            '            throw new OmsException("quantity must be positive");',
            "        }",
            "        onHand = onHand + quantity;",
            "    }",
        ],
        ("SalesOrder", "cancel"): [
            "    public void cancel() throws OmsException {",
            '        if (!"OPEN".equals(statusCode) && !"ALLOCATED".equals(statusCode)) {',
            '            throw new OmsException("order cannot be cancelled");',
            "        }",
            '        statusCode = "CANCELLED";',
            "    }",
        ],
        ("SalesOrder", "attachBuyerPo"): [
            "    public void attachBuyerPo(String buyerPo) throws OmsException {",
            "        if (buyerPo == null || buyerPo.length() == 0) {",
            '            throw new OmsException("buyer PO is required");',
            "        }",
            '        if (!"OPEN".equals(statusCode)) {',
            "            throw new OmsException(",
            '                    "buyer PO is frozen once the order leaves the desk");',
            "        }",
            "        this.buyerPo = buyerPo;",
            "    }",
        ],
        ("Shipment", "markShipped"): [
            "    public void markShipped(String trackingNo) throws OmsException {",
            "        if (trackingNo == null || trackingNo.length() == 0) {",
            '            throw new OmsException("tracking number is required");',
            "        }",
            '        if (!"STAGED".equals(statusCode)) {',
            '            throw new OmsException("shipment is not staged");',
            "        }",
            "        this.trackingNo = trackingNo;",
            '        statusCode = "SHIPPED";',
            "    }",
        ],
        ("Shipment", "markDelivered"): [
            "    public void markDelivered() throws OmsException {",
            '        if (!"SHIPPED".equals(statusCode)) {',
            '            throw new OmsException("shipment has not left the dock");',
            "        }",
            '        statusCode = "DELIVERED";',
            "    }",
        ],
    }
    try:
        return bodies[(entity_name, method)]
    except KeyError as exc:
        raise ValueError(f"no body for {entity_name}.{method}") from exc


def java_throw(exception: str, argument: str) -> str:
    """One indented throw statement inside an entity lifecycle method."""
    return f"            throw new {exception}({argument});"


def render_entity_bean(manifest: Manifest, entity: Entity) -> str:
    root = manifest.java_package
    pk = entity.pk()
    params = ", ".join(f"{field.java_type} {field.name}" for field in entity.fields)
    lines = [
        *class_doc(entity.description),
        f"public class {entity.name}Bean implements EntityBean {{",
        "",
        "    private EntityContext entityContext;",
        "",
    ]
    for field in entity.fields:
        lines.append(f"    private {field.java_type} {field.name};")
    lines.extend(
        [
            "",
            f"    public {pk.java_type} ejbCreate({params})",
            "            throws CreateException, RemoteException {",
            f"        if ({pk.name} == null || {pk.name}.length() == 0) {{",
            f'            throw new CreateException("{entity.table} key is required");',
            "        }",
        ]
    )
    if entity.name == "SalesOrder":
        lines.extend(
            [
                "        if (lineQuantity <= 0) {",
                '            throw new CreateException("line quantity must be positive");',
                "        }",
            ]
        )
    lines.extend(
        [
            "        Connection connection = null;",
            "        try {",
            "            connection = lookupOrderDataSource().getConnection();",
            f"            {entity.dao}.Row row = new {entity.dao}.Row();",
        ]
    )
    for field in entity.fields:
        lines.append(f"            row.set{cap(field.name)}({field.name});")
    lines.append(f"            new {entity.dao}().insert(connection, row);")
    if entity.name == "SalesOrder":
        lines.extend(
            [
                "            long unitPrice = totalCents / lineQuantity;",
                "            OrderLine line = new OrderLine(lineSku, lineQuantity, unitPrice);",
                "            new OrderDao().insertLine(connection, orderId, line);",
            ]
        )
    lines.extend(
        [
            f"            return {pk.name};",
            "        } catch (NamingException failure) {",
            java_throw(
                "EJBException",
                f'"{entity.table} datasource lookup failed", failure',
            ),
            "        } catch (SQLException failure) {",
            java_throw(
                "CreateException",
                f'"{entity.table} insert failed: " + failure.getMessage()',
            ),
            "        } finally {",
            "            close(connection);",
            "        }",
            "    }",
            "",
            "    public void ejbPostCreate("
            + params
            + ") throws CreateException, RemoteException {",
            "    }",
            "",
            "    public void ejbLoad() throws RemoteException {",
            "        String key = (String) entityContext.getPrimaryKey();",
            "        Connection connection = null;",
            "        try {",
            "            connection = lookupOrderDataSource().getConnection();",
            f"            {entity.dao}.Row row = new {entity.dao}().findById(connection, key);",
            "            if (row == null) {",
            "                throw new EJBException(",
            f'                        "{entity.table} disappeared during load: " + key);',
            "            }",
            "            copyFrom(row);",
            "        } catch (NamingException failure) {",
            java_throw(
                "EJBException",
                f'"{entity.table} datasource lookup failed", failure',
            ),
            "        } catch (SQLException failure) {",
            f'            throw new EJBException("{entity.table} load failed: " + key, failure);',
            "        } finally {",
            "            close(connection);",
            "        }",
            "    }",
            "",
            "    public void ejbStore() throws RemoteException {",
            "        Connection connection = null;",
            "        try {",
            "            connection = lookupOrderDataSource().getConnection();",
            f"            {entity.dao}.Row row = new {entity.dao}.Row();",
            "            copyTo(row);",
            f"            new {entity.dao}().update(connection, row);",
            "        } catch (NamingException failure) {",
            java_throw(
                "EJBException",
                f'"{entity.table} datasource lookup failed", failure',
            ),
            "        } catch (SQLException failure) {",
            f'            throw new EJBException("{entity.table} store failed", failure);',
            "        } finally {",
            "            close(connection);",
            "        }",
            "    }",
            "",
            "    public void ejbRemove() throws RemoveException, RemoteException {",
            "        String key = (String) entityContext.getPrimaryKey();",
            "        Connection connection = null;",
            "        try {",
            "            connection = lookupOrderDataSource().getConnection();",
            f"            int removed = new {entity.dao}().delete(connection, key);",
            "            if (removed != 1) {",
            f'                throw new RemoveException("{entity.table} was not removed: " + key);',
            "            }",
            "        } catch (NamingException failure) {",
            java_throw(
                "EJBException",
                f'"{entity.table} datasource lookup failed", failure',
            ),
            "        } catch (SQLException failure) {",
            java_throw(
                "EJBException",
                f'"{entity.table} remove failed: " + key, failure',
            ),
            "        } finally {",
            "            close(connection);",
            "        }",
            "    }",
            "",
            "    public String ejbFindByPrimaryKey(String key)",
            "            throws FinderException, RemoteException {",
            "        if (key == null || key.length() == 0) {",
            f'            throw new FinderException("{entity.table} key is required");',
            "        }",
            "        Connection connection = null;",
            "        try {",
            "            connection = lookupOrderDataSource().getConnection();",
            f"            {entity.dao}.Row row = new {entity.dao}().findById(connection, key);",
            "            if (row == null) {",
            f'                throw new FinderException("{entity.table} not found: " + key);',
            "            }",
            "            return key;",
            "        } catch (NamingException failure) {",
            java_throw(
                "EJBException",
                f'"{entity.table} datasource lookup failed", failure',
            ),
            "        } catch (SQLException failure) {",
            f'            throw new EJBException("{entity.table} find failed: " + key, failure);',
            "        } finally {",
            "            close(connection);",
            "        }",
            "    }",
            "",
            "    public void ejbActivate() throws RemoteException {",
            "    }",
            "",
            "    public void ejbPassivate() throws RemoteException {",
            "    }",
            "",
            "    public void setEntityContext(EntityContext context) throws RemoteException {",
            "        this.entityContext = context;",
            "    }",
            "",
            "    public void unsetEntityContext() throws RemoteException {",
            "        this.entityContext = null;",
            "    }",
            "",
            f"    private void copyFrom({entity.dao}.Row row) {{",
        ]
    )
    for field in entity.fields:
        lines.append(f"        this.{field.name} = row.get{cap(field.name)}();")
    lines.extend(["    }", "", f"    private void copyTo({entity.dao}.Row row) {{"])
    for field in entity.fields:
        lines.append(f"        row.set{cap(field.name)}(this.{field.name});")
    lines.extend(["    }", ""])
    for field in entity.fields:
        lines.extend(bean_accessors(field, primary=field.name == pk.name))
    for method in entity.business_methods:
        lines.extend(entity_method_body(entity.name, method))
        lines.append("")
    lines.extend(jndi_lookup_lines(manifest.datasource_jndi))
    lines.append("")
    lines.extend(close_lines())
    lines.append("}")
    imports = [
        "java.rmi.RemoteException",
        "java.sql.Connection",
        "java.sql.SQLException",
        "javax.ejb.CreateException",
        "javax.ejb.EJBException",
        "javax.ejb.EntityBean",
        "javax.ejb.EntityContext",
        "javax.ejb.FinderException",
        "javax.ejb.RemoveException",
        "javax.naming.InitialContext",
        "javax.naming.NamingException",
        "javax.sql.DataSource",
        f"{root}.dao.{entity.dao}",
        f"{root}.support.OmsException",
    ]
    if entity.name == "SalesOrder":
        imports.append(f"{root}.order.OrderLine")
    return java_file(f"{root}.{entity.subpackage}", imports, lines)


def home_helper(entity: Entity) -> list[str]:
    method = camel(entity.name) + "Home"
    jndi = f"java:comp/env/ejb/{entity.name}"
    return [
        f"    private {entity.name}Home {method}() throws NamingException {{",
        "        InitialContext naming = new InitialContext();",
        f'        Object bound = naming.lookup("{jndi}");',
        f"        return ({entity.name}Home) PortableRemoteObject.narrow(",
        f"                bound, {entity.name}Home.class);",
        "    }",
    ]


def render_session_home(manifest: Manifest, session: Session) -> str:
    root = manifest.java_package
    lines = [
        *class_doc(session.description),
        f"public interface {session.name}Home extends EJBHome {{",
        "",
        f"    {session.name} create() throws CreateException, RemoteException;",
        "}",
    ]
    return java_file(
        f"{root}.{session.subpackage}",
        [
            "java.rmi.RemoteException",
            "javax.ejb.CreateException",
            "javax.ejb.EJBHome",
        ],
        lines,
    )


def session_signature(session_name: str, method: str, *, remote: bool) -> str:
    signatures = {
        ("OrderService", "placeOrder"): (
            "String placeOrder(String customerId, String sku, int quantity, "
            "String placedOn, String requestedShip, String buyerPo)"
        ),
        ("OrderService", "cancelOrder"): "void cancelOrder(String orderId)",
        ("OrderService", "findOrdersForCustomer"): (
            "String findOrdersForCustomer(String customerId, String statusCode)"
        ),
        ("OrderService", "attachBuyerPo"): "void attachBuyerPo(String orderId, String buyerPo)",
        ("InventoryService", "onHand"): "int onHand(String sku)",
        ("InventoryService", "reserveStock"): "void reserveStock(String sku, int quantity)",
        ("InventoryService", "releaseStock"): "void releaseStock(String sku, int quantity)",
        ("InventoryService", "belowReorder"): "String belowReorder(String warehouseCode)",
        ("PricingService", "quote"): "long quote(String sku, String regionCode, int quantity)",
        ("PricingService", "applyPriceOverride"): (
            "void applyPriceOverride(String sku, long unitPriceCents)"
        ),
        ("PricingService", "priceBookForRegion"): (
            "long priceBookForRegion(String sku, String regionCode)"
        ),
        ("FulfillmentService", "createShipment"): (
            "String createShipment(String orderId, String carrier)"
        ),
        ("FulfillmentService", "markShipped"): (
            "void markShipped(String shipmentId, String trackingNo)"
        ),
        ("FulfillmentService", "markDelivered"): "void markDelivered(String shipmentId)",
        ("FulfillmentService", "findShipments"): "String findShipments(String orderId)",
        ("CatalogAdmin", "addProduct"): (
            "void addProduct(String sku, String description, long unitPriceCents, "
            "String warehouseCode, String vendorCode)"
        ),
        ("CatalogAdmin", "discontinueProduct"): "void discontinueProduct(String sku)",
        ("CatalogAdmin", "updateWarehouse"): (
            "void updateWarehouse(String sku, String warehouseCode)"
        ),
    }
    try:
        base = signatures[(session_name, method)]
    except KeyError as exc:
        raise ValueError(f"no signature for {session_name}.{method}") from exc
    throws = "throws OmsException, RemoteException" if remote else "throws OmsException"
    return f"{base} {throws}"


def render_session_remote(manifest: Manifest, session: Session) -> str:
    root = manifest.java_package
    lines = [
        *class_doc(session.description),
        f"public interface {session.name} extends EJBObject {{",
    ]
    for method in session.methods:
        lines.extend(["", f"    {session_signature(session.name, method, remote=True)};"])
    lines.append("}")
    return java_file(
        f"{root}.{session.subpackage}",
        ["java.rmi.RemoteException", "javax.ejb.EJBObject", f"{root}.support.OmsException"],
        lines,
    )


def render_session_bean(manifest: Manifest, session: Session) -> str:
    root = manifest.java_package
    http = session.name == HTTP_EJB
    header = f"public class {session.name}Bean "
    if http:
        header += "extends HttpServlet implements SessionBean {"
    else:
        header += "implements SessionBean {"
    lines = [
        *class_doc(session.description),
        header,
        "",
        "    private SessionContext sessionContext;",
        "",
    ]
    if http:
        lines.extend(
            [
                "    private static final long serialVersionUID = 1L;",
                "",
            ]
        )
    lines.extend(
        [
            "    public void ejbCreate() throws RemoteException {",
            "    }",
            "",
            "    public void ejbRemove() throws RemoteException {",
            "    }",
            "",
            "    public void ejbActivate() throws RemoteException {",
            "    }",
            "",
            "    public void ejbPassivate() throws RemoteException {",
            "    }",
            "",
            "    public void setSessionContext(SessionContext context) throws RemoteException {",
            "        this.sessionContext = context;",
            "    }",
            "",
        ]
    )
    for method in session.methods:
        lines.extend(session_method_body(session.name, method))
        lines.append("")
    if session.name == TX_EJB:
        lines.extend(rollback_override_method())
        lines.append("")
    if http:
        lines.extend(catalog_http_methods())
        lines.append("")
    for ref in session.entity_refs:
        lines.extend(home_helper(manifest.entity(ref)))
        lines.append("")
    lines.extend(jndi_lookup_lines(manifest.datasource_jndi))
    lines.append("")
    lines.extend(close_lines())
    lines.append("}")
    imports = session_imports(manifest, session)
    return java_file(f"{root}.{session.subpackage}", imports, lines)


def session_imports(manifest: Manifest, session: Session) -> list[str]:
    root = manifest.java_package
    imports = [
        "java.rmi.RemoteException",
        "javax.ejb.EJBException",
        "javax.ejb.FinderException",
        "javax.ejb.SessionBean",
        "javax.ejb.SessionContext",
        "javax.naming.InitialContext",
        "javax.naming.NamingException",
        "javax.rmi.PortableRemoteObject",
        "javax.sql.DataSource",
        f"{root}.support.OmsException",
    ]
    needs_sql = session.name in {
        "OrderService",
        "InventoryService",
        "PricingService",
        "FulfillmentService",
        "CatalogAdmin",
    }
    if needs_sql:
        imports.extend(["java.sql.Connection", "java.sql.SQLException"])
    if session.name in {"OrderService", "InventoryService", "FulfillmentService"}:
        imports.extend(["java.util.List"])
    if session.name == "PricingService":
        imports.extend(
            [
                "java.sql.PreparedStatement",
                "javax.transaction.SystemException",
                "javax.transaction.UserTransaction",
                f"{root}.support.Money",
                f"{root}.support.Regions",
            ]
        )
    if session.name == "OrderService":
        imports.append(f"{root}.support.Money")
        imports.append(f"{root}.dao.OrderDao")
    if session.name == "InventoryService":
        imports.append(f"{root}.dao.ProductDao")
    if session.name == "FulfillmentService":
        imports.append("javax.ejb.CreateException")
        imports.append(f"{root}.dao.ShipmentDao")
    if session.name == "CatalogAdmin":
        imports.extend(
            [
                "java.io.IOException",
                "java.sql.PreparedStatement",
                "javax.ejb.CreateException",
                "javax.servlet.ServletException",
                "javax.servlet.http.HttpServlet",
                "javax.servlet.http.HttpServletRequest",
                "javax.servlet.http.HttpServletResponse",
            ]
        )
    for ref in session.entity_refs:
        entity = manifest.entity(ref)
        package = f"{root}.{entity.subpackage}"
        bean_package = f"{root}.{session.subpackage}"
        if package != bean_package:
            imports.append(f"{package}.{entity.name}")
            imports.append(f"{package}.{entity.name}Home")
    return imports


def session_method_body(session_name: str, method: str) -> list[str]:
    builders: dict[tuple[str, str], Callable[[], list[str]]] = {
        ("OrderService", "placeOrder"): place_order,
        ("OrderService", "cancelOrder"): cancel_order,
        ("OrderService", "findOrdersForCustomer"): find_orders,
        ("OrderService", "attachBuyerPo"): attach_buyer_po,
        ("InventoryService", "onHand"): on_hand,
        ("InventoryService", "reserveStock"): reserve_stock,
        ("InventoryService", "releaseStock"): release_stock,
        ("InventoryService", "belowReorder"): below_reorder,
        ("PricingService", "quote"): quote,
        ("PricingService", "applyPriceOverride"): apply_price_override,
        ("PricingService", "priceBookForRegion"): price_book,
        ("FulfillmentService", "createShipment"): create_shipment,
        ("FulfillmentService", "markShipped"): mark_shipped,
        ("FulfillmentService", "markDelivered"): mark_delivered,
        ("FulfillmentService", "findShipments"): find_shipments,
        ("CatalogAdmin", "addProduct"): add_product,
        ("CatalogAdmin", "discontinueProduct"): discontinue_product,
        ("CatalogAdmin", "updateWarehouse"): update_warehouse,
    }
    try:
        build = builders[(session_name, method)]
    except KeyError as exc:
        raise ValueError(f"no body for {session_name}.{method}") from exc
    lines = [f"    public {session_signature(session_name, method, remote=False)} {{"]
    lines.extend(build())
    lines.append("    }")
    return lines


def place_order() -> list[str]:
    return [
        "        if (customerId == null || customerId.length() == 0) {",
        '            throw new OmsException("customer id is required");',
        "        }",
        "        if (sku == null || sku.length() == 0) {",
        '            throw new OmsException("sku is required");',
        "        }",
        "        if (quantity <= 0) {",
        '            throw new OmsException("quantity must be positive");',
        "        }",
        "        if (placedOn == null || placedOn.length() != 10) {",
        '            throw new OmsException("placed-on must be yyyy-mm-dd");',
        "        }",
        "        if (requestedShip == null || requestedShip.length() != 10) {",
        '            throw new OmsException("requested ship must be yyyy-mm-dd");',
        "        }",
        "        try {",
        "            Customer customer = customerHome().findByPrimaryKey(customerId);",
        '            if (!"ACTIVE".equals(customer.getStatusCode())) {',
        '                throw new OmsException("customer cannot place orders: " + customerId);',
        "            }",
        "            Product product = productHome().findByPrimaryKey(sku);",
        '            if (!"Y".equals(product.getActiveFlag())) {',
        '                throw new OmsException("sku is not active: " + sku);',
        "            }",
        "            long lineCents = Money.lineTotal(product.getUnitPriceCents(), quantity);",
        "            if (lineCents > customer.getCreditLimitCents()) {",
        '                throw new OmsException("credit limit exceeded for " + customerId);',
        "            }",
        "            product.reserve(quantity);",
        '            String orderId = customerId + "-" + placedOn + "-" + sku;',
        "            SalesOrder created = salesOrderHome().create(",
        "                    orderId,",
        "                    customerId,",
        '                    "OPEN",',
        "                    placedOn,",
        "                    requestedShip,",
        "                    lineCents,",
        '                    "USD",',
        '                    buyerPo == null ? "" : buyerPo,',
        "                    product.getWarehouseCode(),",
        "                    sku,",
        "                    quantity);",
        "            return created.getOrderId();",
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown customer or sku");',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("order desk naming failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("order desk remote call failed", failure);',
        "        } catch (javax.ejb.CreateException failure) {",
        '            throw new EJBException("order create failed", failure);',
        "        }",
    ]


def cancel_order() -> list[str]:
    return [
        "        if (orderId == null || orderId.length() == 0) {",
        '            throw new OmsException("order id is required");',
        "        }",
        "        try {",
        "            SalesOrder order = salesOrderHome().findByPrimaryKey(orderId);",
        "            String status = order.getStatusCode();",
        '            if (!"OPEN".equals(status) && !"ALLOCATED".equals(status)) {',
        '                throw new OmsException("order cannot be cancelled: " + orderId);',
        "            }",
        "            Product product = productHome().findByPrimaryKey(order.getLineSku());",
        "            product.release(order.getLineQuantity());",
        "            order.cancel();",
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown order: " + orderId);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("cancel lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("cancel call failed", failure);',
        "        }",
    ]


def find_orders() -> list[str]:
    return [
        "        if (customerId == null || customerId.length() == 0) {",
        '            throw new OmsException("customer id is required");',
        "        }",
        "        if (statusCode == null || statusCode.length() == 0) {",
        '            throw new OmsException("status is required");',
        "        }",
        "        Connection connection = null;",
        "        try {",
        "            connection = lookupOrderDataSource().getConnection();",
        "            List<OrderDao.Row> found = new OrderDao().findByCustomerAndStatus(",
        "                    connection, customerId, statusCode);",
        "            StringBuilder joined = new StringBuilder();",
        "            for (int index = 0; index < found.size(); index++) {",
        "                if (index > 0) {",
        "                    joined.append(',');",
        "                }",
        "                joined.append(found.get(index).getOrderId());",
        "            }",
        "            return joined.toString();",
        "        } catch (NamingException failure) {",
        '            throw new EJBException("order search lookup failed", failure);',
        "        } catch (SQLException failure) {",
        '            throw new EJBException("order search failed", failure);',
        "        } finally {",
        "            close(connection);",
        "        }",
    ]


def attach_buyer_po() -> list[str]:
    return [
        "        if (orderId == null || orderId.length() == 0) {",
        '            throw new OmsException("order id is required");',
        "        }",
        "        try {",
        "            salesOrderHome().findByPrimaryKey(orderId).attachBuyerPo(buyerPo);",
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown order: " + orderId);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("buyer PO lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("buyer PO call failed", failure);',
        "        }",
    ]


def on_hand() -> list[str]:
    return [
        "        try {",
        "            return productHome().findByPrimaryKey(sku).getOnHand();",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown sku: " + sku);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("on-hand lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("on-hand call failed", failure);',
        "        }",
    ]


def reserve_stock() -> list[str]:
    return [
        "        try {",
        "            productHome().findByPrimaryKey(sku).reserve(quantity);",
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown sku: " + sku);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("reserve lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("reserve call failed", failure);',
        "        }",
    ]


def release_stock() -> list[str]:
    return [
        "        try {",
        "            productHome().findByPrimaryKey(sku).release(quantity);",
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown sku: " + sku);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("release lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("release call failed", failure);',
        "        }",
    ]


def below_reorder() -> list[str]:
    return [
        "        if (warehouseCode == null || warehouseCode.length() == 0) {",
        '            throw new OmsException("warehouse is required");',
        "        }",
        "        Connection connection = null;",
        "        try {",
        "            connection = lookupOrderDataSource().getConnection();",
        "            List<ProductDao.Row> found = new ProductDao().findBelowReorder(",
        "                    connection, warehouseCode);",
        "            StringBuilder joined = new StringBuilder();",
        "            for (int index = 0; index < found.size(); index++) {",
        "                if (index > 0) {",
        "                    joined.append(',');",
        "                }",
        "                joined.append(found.get(index).getSku());",
        "            }",
        "            return joined.toString();",
        "        } catch (NamingException failure) {",
        '            throw new EJBException("reorder lookup failed", failure);',
        "        } catch (SQLException failure) {",
        '            throw new EJBException("reorder query failed", failure);',
        "        } finally {",
        "            close(connection);",
        "        }",
    ]


def quote() -> list[str]:
    return [
        "        if (quantity <= 0) {",
        '            throw new OmsException("quantity must be positive");',
        "        }",
        "        long unit = priceBookForRegion(sku, regionCode);",
        "        return Money.lineTotal(unit, quantity);",
    ]


def apply_price_override() -> list[str]:
    return [
        "        if (sku == null || sku.length() == 0) {",
        '            throw new OmsException("sku is required");',
        "        }",
        "        if (unitPriceCents < 0) {",
        '            throw new OmsException("price must not be negative");',
        "        }",
        "        UserTransaction transaction = sessionContext.getUserTransaction();",
        "        Connection connection = null;",
        "        try {",
        "            transaction.begin();",
        "            connection = lookupOrderDataSource().getConnection();",
        "            PreparedStatement statement = connection.prepareStatement(",
        '                    "UPDATE product SET unit_price_cents = ? WHERE sku = ?");',
        "            try {",
        "                statement.setLong(1, unitPriceCents);",
        "                statement.setString(2, sku);",
        "                int updated = statement.executeUpdate();",
        "                if (updated != 1) {",
        '                    throw new OmsException("sku was not updated: " + sku);',
        "                }",
        "            } finally {",
        "                statement.close();",
        "            }",
        "            transaction.commit();",
        "        } catch (OmsException business) {",
        "            rollbackOverride(transaction);",
        "            throw business;",
        "        } catch (Exception failure) {",
        "            rollbackOverride(transaction);",
        '            throw new EJBException("price override failed for " + sku, failure);',
        "        } finally {",
        "            close(connection);",
        "        }",
    ]


def price_book() -> list[str]:
    return [
        "        if (sku == null || sku.length() == 0) {",
        '            throw new OmsException("sku is required");',
        "        }",
        "        try {",
        "            Product product = productHome().findByPrimaryKey(sku);",
        "            return Regions.adjust(product.getUnitPriceCents(), regionCode);",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown sku: " + sku);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("price book lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("price book call failed", failure);',
        "        }",
    ]


def create_shipment() -> list[str]:
    return [
        "        if (orderId == null || orderId.length() == 0) {",
        '            throw new OmsException("order id is required");',
        "        }",
        "        if (carrier == null || carrier.length() == 0) {",
        '            throw new OmsException("carrier is required");',
        "        }",
        "        try {",
        "            SalesOrder order = salesOrderHome().findByPrimaryKey(orderId);",
        '            if (!"OPEN".equals(order.getStatusCode())) {',
        '                throw new OmsException("order is not open for shipment: " + orderId);',
        "            }",
        '            String shipmentId = orderId + "-S1";',
        "            Shipment created = shipmentHome().create(",
        "                    shipmentId,",
        "                    orderId,",
        "                    carrier,",
        '                    "",',
        '                    "",',
        '                    "STAGED",',
        "                    0,",
        '                    "DOOR-1");',
        '            order.setStatusCode("ALLOCATED");',
        "            return created.getShipmentId();",
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown order: " + orderId);',
        "        } catch (CreateException failure) {",
        '            throw new EJBException("shipment create failed", failure);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("shipment lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("shipment call failed", failure);',
        "        }",
    ]


def mark_shipped() -> list[str]:
    return [
        "        try {",
        "            Shipment shipment = shipmentHome().findByPrimaryKey(shipmentId);",
        "            shipment.markShipped(trackingNo);",
        "            SalesOrder order = salesOrderHome().findByPrimaryKey(shipment.getOrderId());",
        '            order.setStatusCode("SHIPPED");',
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown shipment: " + shipmentId);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("ship lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("ship call failed", failure);',
        "        }",
    ]


def mark_delivered() -> list[str]:
    return [
        "        try {",
        "            Shipment shipment = shipmentHome().findByPrimaryKey(shipmentId);",
        "            shipment.markDelivered();",
        "            SalesOrder order = salesOrderHome().findByPrimaryKey(shipment.getOrderId());",
        '            order.setStatusCode("DELIVERED");',
        "        } catch (OmsException business) {",
        "            throw business;",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown shipment: " + shipmentId);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("delivery lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("delivery call failed", failure);',
        "        }",
    ]


def find_shipments() -> list[str]:
    return [
        "        if (orderId == null || orderId.length() == 0) {",
        '            throw new OmsException("order id is required");',
        "        }",
        "        Connection connection = null;",
        "        try {",
        "            connection = lookupOrderDataSource().getConnection();",
        "            List<ShipmentDao.Row> found = new ShipmentDao()",
        "                    .findByOrder(connection, orderId);",
        "            StringBuilder joined = new StringBuilder();",
        "            for (int index = 0; index < found.size(); index++) {",
        "                if (index > 0) {",
        "                    joined.append(',');",
        "                }",
        "                joined.append(found.get(index).getShipmentId());",
        "            }",
        "            return joined.toString();",
        "        } catch (NamingException failure) {",
        '            throw new EJBException("shipment search lookup failed", failure);',
        "        } catch (SQLException failure) {",
        '            throw new EJBException("shipment search failed", failure);',
        "        } finally {",
        "            close(connection);",
        "        }",
    ]


def add_product() -> list[str]:
    return [
        "        if (sku == null || sku.length() == 0) {",
        '            throw new OmsException("sku is required");',
        "        }",
        "        if (unitPriceCents < 0) {",
        '            throw new OmsException("price must not be negative");',
        "        }",
        "        try {",
        "            productHome().create(",
        "                    sku,",
        '                    description == null ? "" : description,',
        "                    unitPriceCents,",
        "                    0,",
        "                    warehouseCode,",
        "                    0,",
        '                    "Y",',
        '                    vendorCode == null ? "" : vendorCode);',
        "        } catch (CreateException failure) {",
        '            throw new EJBException("catalog create failed for " + sku, failure);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("catalog lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("catalog call failed", failure);',
        "        }",
    ]


def discontinue_product() -> list[str]:
    return [
        "        try {",
        "            Product product = productHome().findByPrimaryKey(sku);",
        '            product.setActiveFlag("N");',
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown sku: " + sku);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("catalog lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("catalog call failed", failure);',
        "        }",
    ]


def update_warehouse() -> list[str]:
    return [
        "        if (warehouseCode == null || warehouseCode.length() == 0) {",
        '            throw new OmsException("warehouse is required");',
        "        }",
        "        try {",
        "            Product product = productHome().findByPrimaryKey(sku);",
        "            product.setWarehouseCode(warehouseCode);",
        "        } catch (FinderException missing) {",
        '            throw new OmsException("unknown sku: " + sku);',
        "        } catch (NamingException failure) {",
        '            throw new EJBException("catalog lookup failed", failure);',
        "        } catch (RemoteException failure) {",
        '            throw new EJBException("catalog call failed", failure);',
        "        }",
    ]


def catalog_http_methods() -> list[str]:
    return [
        "    @Override",
        "    protected void doGet(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        '        response.setContentType("text/html; charset=UTF-8");',
        "        response.getWriter().print(catalogForm(request.getContextPath()));",
        "    }",
        "",
        "    @Override",
        "    protected void doPost(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        '        String sku = request.getParameter("sku");',
        '        String description = request.getParameter("description");',
        '        String priceText = request.getParameter("unitPriceCents");',
        '        String warehouseCode = request.getParameter("warehouseCode");',
        '        String vendorCode = request.getParameter("vendorCode");',
        "        if (sku == null || description == null || priceText == null",
        "                || warehouseCode == null) {",
        "            response.sendError(",
        "                    HttpServletResponse.SC_BAD_REQUEST,",
        '                    "sku, description, price and warehouse are required");',
        "            return;",
        "        }",
        "        long unitPriceCents;",
        "        try {",
        "            unitPriceCents = Long.parseLong(priceText);",
        "        } catch (NumberFormatException failure) {",
        "            response.sendError(",
        '                    HttpServletResponse.SC_BAD_REQUEST, "unit price must be cents");',
        "            return;",
        "        }",
        "        try {",
        "            writeProduct(",
        "                    sku,",
        "                    description,",
        "                    unitPriceCents,",
        "                    warehouseCode,",
        '                    vendorCode == null ? "" : vendorCode);',
        "        } catch (OmsException failure) {",
        "            response.sendError(HttpServletResponse.SC_CONFLICT, failure.getMessage());",
        "            return;",
        "        }",
        '        response.sendRedirect(request.getContextPath() + "/admin/catalog");',
        "    }",
        "",
        "    private void writeProduct(",
        "            String sku,",
        "            String description,",
        "            long unitPriceCents,",
        "            String warehouseCode,",
        "            String vendorCode) throws OmsException {",
        "        if (sku.length() == 0 || unitPriceCents < 0) {",
        '            throw new OmsException("sku and a non-negative price are required");',
        "        }",
        "        Connection connection = null;",
        "        try {",
        "            connection = lookupOrderDataSource().getConnection();",
        "            PreparedStatement update = connection.prepareStatement(",
        '                    "UPDATE product SET description = ?, unit_price_cents = ?, "',
        "                            + \"warehouse_code = ?, vendor_code = ?, active_flag = 'Y' \"",
        '                            + "WHERE sku = ?");',
        "            try {",
        "                update.setString(1, description);",
        "                update.setLong(2, unitPriceCents);",
        "                update.setString(3, warehouseCode);",
        "                update.setString(4, vendorCode);",
        "                update.setString(5, sku);",
        "                int updated = update.executeUpdate();",
        "                if (updated == 0) {",
        "                    insertProduct(",
        "                            connection,",
        "                            sku,",
        "                            description,",
        "                            unitPriceCents,",
        "                            warehouseCode,",
        "                            vendorCode);",
        "                }",
        "            } finally {",
        "                update.close();",
        "            }",
        "        } catch (NamingException failure) {",
        '            throw new EJBException("catalog datasource lookup failed", failure);',
        "        } catch (SQLException failure) {",
        '            throw new EJBException("catalog write failed for " + sku, failure);',
        "        } finally {",
        "            close(connection);",
        "        }",
        "    }",
        "",
        "    private void insertProduct(",
        "            Connection connection,",
        "            String sku,",
        "            String description,",
        "            long unitPriceCents,",
        "            String warehouseCode,",
        "            String vendorCode) throws SQLException {",
        "        PreparedStatement insert = connection.prepareStatement(",
        '                "INSERT INTO product (sku, description, unit_price_cents, on_hand, "',
        '                        + "warehouse_code, reorder_point, active_flag, vendor_code) "',
        "                        + \"VALUES (?, ?, ?, 0, ?, 0, 'Y', ?)\");",
        "        try {",
        "            insert.setString(1, sku);",
        "            insert.setString(2, description);",
        "            insert.setLong(3, unitPriceCents);",
        "            insert.setString(4, warehouseCode);",
        "            insert.setString(5, vendorCode);",
        "            insert.executeUpdate();",
        "        } finally {",
        "            insert.close();",
        "        }",
        "    }",
        "",
        "    private String catalogForm(String contextPath) {",
        '        return "<!DOCTYPE html>\\n"',
        '                + "<html><head><title>Harbor catalog desk</title></head>\\n"',
        '                + "<body><h1>Harbor catalog desk</h1>\\n"',
        '                + "<form method=\\"post\\" action=\\"" + contextPath',
        '                + "/admin/catalog\\">\\n"',
        '                + "<p>SKU <input name=\\"sku\\"/></p>\\n"',
        '                + "<p>Description <input name=\\"description\\"/></p>\\n"',
        '                + "<p>Unit price (cents) <input name=\\"unitPriceCents\\"/></p>\\n"',
        '                + "<p>Warehouse <input name=\\"warehouseCode\\"/></p>\\n"',
        '                + "<p>Vendor <input name=\\"vendorCode\\"/></p>\\n"',
        '                + "<p><button type=\\"submit\\">Save sku</button></p>\\n"',
        '                + "</form></body></html>\\n";',
        "    }",
    ]


def rollback_override_method() -> list[str]:
    return [
        "    private void rollbackOverride(UserTransaction transaction) {",
        "        try {",
        "            transaction.rollback();",
        "        } catch (SystemException failure) {",
        '            throw new EJBException("price override rollback failed", failure);',
        "        }",
        "    }",
    ]


def render_servlet(manifest: Manifest, servlet: Servlet) -> str:
    root = manifest.java_package
    methods = (
        order_entry_methods() if servlet.name == "OrderEntryServlet" else order_status_methods()
    )
    lines = [
        *class_doc(servlet.description),
        f"public class {servlet.name} extends HttpServlet {{",
        "",
        "    private static final long serialVersionUID = 1L;",
        "",
        *methods,
        "",
        "    private OrderServiceHome orderServiceHome() throws NamingException {",
        "        InitialContext naming = new InitialContext();",
        '        Object bound = naming.lookup("java:comp/env/ejb/OrderService");',
        "        return (OrderServiceHome) PortableRemoteObject.narrow(",
        "                bound, OrderServiceHome.class);",
        "    }",
        "",
        "    private void forward(",
        "            HttpServletRequest request, HttpServletResponse response, String view)",
        "            throws ServletException, IOException {",
        "        request.getRequestDispatcher(view).forward(request, response);",
        "    }",
        "}",
    ]
    return java_file(
        f"{root}.web",
        [
            "java.io.IOException",
            "javax.ejb.CreateException",
            "javax.naming.InitialContext",
            "javax.naming.NamingException",
            "javax.rmi.PortableRemoteObject",
            "javax.servlet.ServletException",
            "javax.servlet.http.HttpServlet",
            "javax.servlet.http.HttpServletRequest",
            "javax.servlet.http.HttpServletResponse",
            f"{root}.order.OrderService",
            f"{root}.order.OrderServiceHome",
            f"{root}.support.OmsException",
        ],
        lines,
    )


def order_entry_methods() -> list[str]:
    return [
        "    @Override",
        "    protected void doGet(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        '        forward(request, response, "/order-entry.jsp");',
        "    }",
        "",
        "    @Override",
        "    protected void doPost(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        '        String customerId = request.getParameter("customerId");',
        '        String sku = request.getParameter("sku");',
        '        String quantityText = request.getParameter("quantity");',
        '        String placedOn = request.getParameter("placedOn");',
        '        String requestedShip = request.getParameter("requestedShip");',
        '        String buyerPo = request.getParameter("buyerPo");',
        "        if (customerId == null || sku == null || quantityText == null) {",
        '            fail(request, response, "customer, sku and quantity are required");',
        "            return;",
        "        }",
        "        int quantity;",
        "        try {",
        "            quantity = Integer.parseInt(quantityText);",
        "        } catch (NumberFormatException failure) {",
        '            fail(request, response, "quantity must be a whole number");',
        "            return;",
        "        }",
        "        try {",
        "            OrderService service = orderServiceHome().create();",
        "            String orderId = service.placeOrder(",
        "                    customerId, sku, quantity, placedOn, requestedShip, buyerPo);",
        '            request.setAttribute("orderId", orderId);',
        '            request.setAttribute("customerId", customerId);',
        '            request.setAttribute("sku", sku);',
        '            request.setAttribute("quantity", Integer.valueOf(quantity));',
        '            forward(request, response, "/order-detail.jsp");',
        "        } catch (OmsException failure) {",
        "            fail(request, response, failure.getMessage());",
        "        } catch (CreateException failure) {",
        '            fail(request, response, "the order desk could not open a service");',
        "        } catch (NamingException failure) {",
        '            fail(request, response, "the order service is not bound");',
        "        } catch (java.rmi.RemoteException failure) {",
        '            fail(request, response, "the order service did not answer");',
        "        }",
        "    }",
        "",
        "    private void fail(",
        "            HttpServletRequest request, HttpServletResponse response, String message)",
        "            throws ServletException, IOException {",
        '        request.setAttribute("deskMessage", message);',
        '        forward(request, response, "/error.jsp");',
        "    }",
    ]


def order_status_methods() -> list[str]:
    return [
        "    @Override",
        "    protected void doGet(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        "        show(request, response);",
        "    }",
        "",
        "    @Override",
        "    protected void doPost(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        "        show(request, response);",
        "    }",
        "",
        "    private void show(HttpServletRequest request, HttpServletResponse response)",
        "            throws ServletException, IOException {",
        '        String customerId = request.getParameter("customerId");',
        '        String statusCode = request.getParameter("statusCode");',
        "        if (statusCode == null || statusCode.length() == 0) {",
        '            statusCode = "OPEN";',
        "        }",
        "        if (customerId == null || customerId.length() == 0) {",
        '            request.setAttribute("orderList", "");',
        '            request.setAttribute("statusCode", statusCode);',
        '            forward(request, response, "/order-list.jsp");',
        "            return;",
        "        }",
        "        try {",
        "            OrderService service = orderServiceHome().create();",
        "            String orderList = service.findOrdersForCustomer(customerId, statusCode);",
        '            request.setAttribute("customerId", customerId);',
        '            request.setAttribute("statusCode", statusCode);',
        '            request.setAttribute("orderList", orderList);',
        '            forward(request, response, "/order-list.jsp");',
        "        } catch (OmsException failure) {",
        '            request.setAttribute("deskMessage", failure.getMessage());',
        '            forward(request, response, "/error.jsp");',
        "        } catch (CreateException failure) {",
        "            request.setAttribute(",
        '                    "deskMessage", "the order desk could not open a service");',
        '            forward(request, response, "/error.jsp");',
        "        } catch (NamingException failure) {",
        '            request.setAttribute("deskMessage", "the order service is not bound");',
        '            forward(request, response, "/error.jsp");',
        "        } catch (java.rmi.RemoteException failure) {",
        '            request.setAttribute("deskMessage", "the order service did not answer");',
        '            forward(request, response, "/error.jsp");',
        "        }",
        "    }",
    ]


def render_support() -> dict[str, str]:
    root = JAVA_PACKAGE
    exception = java_file(
        f"{root}.support",
        [],
        [
            "/** A business failure the order desk can show to a clerk. */",
            "public class OmsException extends Exception {",
            "",
            "    private static final long serialVersionUID = 1L;",
            "",
            "    public OmsException(String message) {",
            "        super(message);",
            "    }",
            "}",
        ],
    )
    money = java_file(
        f"{root}.support",
        [],
        [
            "/** Whole-cent arithmetic for desk prices. */",
            "public final class Money {",
            "",
            "    private Money() {",
            "    }",
            "",
            "    public static long lineTotal(long unitPriceCents, int quantity) {",
            "        if (unitPriceCents < 0 || quantity < 0) {",
            '            throw new IllegalArgumentException("money inputs must not be negative");',
            "        }",
            "        return unitPriceCents * (long) quantity;",
            "    }",
            "",
            "    public static String format(long cents) {",
            "        long whole = cents / 100;",
            "        long fraction = Math.abs(cents % 100);",
            "        String digits = Long.toString(fraction);",
            "        if (fraction < 10) {",
            '            digits = "0" + digits;',
            "        }",
            '        return Long.toString(whole) + "." + digits;',
            "    }",
            "}",
        ],
    )
    regions = java_file(
        f"{root}.support",
        [f"{root}.support.OmsException"],
        [
            "/** Region codes the price book knows. */",
            "public final class Regions {",
            "",
            '    public static final String NORTH = "NORTH";',
            '    public static final String SOUTH = "SOUTH";',
            '    public static final String EAST = "EAST";',
            '    public static final String WEST = "WEST";',
            "",
            "    private Regions() {",
            "    }",
            "",
            "    public static long adjust(long unitPriceCents, String regionCode)",
            "            throws OmsException {",
            "        if (regionCode == null || regionCode.length() == 0) {",
            '            throw new OmsException("region is required");',
            "        }",
            "        if (NORTH.equals(regionCode)) {",
            "            return unitPriceCents;",
            "        }",
            "        if (SOUTH.equals(regionCode)) {",
            "            return unitPriceCents + (unitPriceCents * 3) / 100;",
            "        }",
            "        if (EAST.equals(regionCode)) {",
            "            return unitPriceCents + (unitPriceCents * 2) / 100;",
            "        }",
            "        if (WEST.equals(regionCode)) {",
            "            return unitPriceCents + unitPriceCents / 100;",
            "        }",
            '        throw new OmsException("unknown region: " + regionCode);',
            "    }",
            "}",
        ],
    )
    line = java_file(
        f"{root}.order",
        [],
        [
            "/** One sku on a desk order. The order bean writes it beside the header. */",
            "public final class OrderLine {",
            "",
            "    private final String sku;",
            "    private final int quantity;",
            "    private final long unitPriceCents;",
            "",
            "    public OrderLine(String sku, int quantity, long unitPriceCents) {",
            "        this.sku = sku;",
            "        this.quantity = quantity;",
            "        this.unitPriceCents = unitPriceCents;",
            "    }",
            "",
            "    public String getSku() {",
            "        return sku;",
            "    }",
            "",
            "    public int getQuantity() {",
            "        return quantity;",
            "    }",
            "",
            "    public long getUnitPriceCents() {",
            "        return unitPriceCents;",
            "    }",
            "}",
        ],
    )
    return {
        java_path("support", "OmsException"): exception,
        java_path("support", "Money"): money,
        java_path("support", "Regions"): regions,
        java_path("order", "OrderLine"): line,
    }


def xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def resource_ref(indent: str) -> list[str]:
    return [
        f"{indent}<resource-ref>",
        f"{indent}  <res-ref-name>jdbc/OrderDS</res-ref-name>",
        f"{indent}  <res-type>javax.sql.DataSource</res-type>",
        f"{indent}  <res-auth>Container</res-auth>",
        f"{indent}</resource-ref>",
    ]


def ejb_local_ref(indent: str, manifest: Manifest, entity_name: str) -> list[str]:
    entity = manifest.entity(entity_name)
    home = f"{entity.fqcn(manifest.java_package)}Home"
    remote = entity.fqcn(manifest.java_package)
    kind = "Entity"
    return [
        f"{indent}<ejb-ref>",
        f"{indent}  <ejb-ref-name>ejb/{entity_name}</ejb-ref-name>",
        f"{indent}  <ejb-ref-type>{kind}</ejb-ref-type>",
        f"{indent}  <home>{home}</home>",
        f"{indent}  <remote>{remote}</remote>",
        f"{indent}</ejb-ref>",
    ]


def render_ejb_jar(manifest: Manifest) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- EJB 2.0 deployment descriptor for Harbor OMS. -->",
        "<ejb-jar>",
        "  <enterprise-beans>",
    ]
    for session in manifest.sessions:
        fqcn = session.fqcn(manifest.java_package)
        lines.extend(
            [
                "    <session>",
                f"      <description>{xml_escape(session.description)}</description>",
                f"      <display-name>{session.name}</display-name>",
                f"      <ejb-name>{session.name}</ejb-name>",
                f"      <home>{fqcn}Home</home>",
                f"      <remote>{fqcn}</remote>",
                f"      <ejb-class>{fqcn}Bean</ejb-class>",
                "      <session-type>Stateless</session-type>",
                "      <transaction-type>Container</transaction-type>",
            ]
        )
        for ref in session.entity_refs:
            lines.extend(ejb_local_ref("      ", manifest, ref))
        lines.extend(resource_ref("      "))
        lines.append("    </session>")
    for entity in manifest.entities:
        fqcn = entity.fqcn(manifest.java_package)
        lines.extend(
            [
                "    <entity>",
                f"      <description>{xml_escape(entity.description)}</description>",
                f"      <display-name>{entity.name}</display-name>",
                f"      <ejb-name>{entity.name}</ejb-name>",
                f"      <home>{fqcn}Home</home>",
                f"      <remote>{fqcn}</remote>",
                f"      <ejb-class>{fqcn}Bean</ejb-class>",
                "      <persistence-type>Bean</persistence-type>",
                "      <prim-key-class>java.lang.String</prim-key-class>",
                "      <reentrant>False</reentrant>",
            ]
        )
        lines.extend(resource_ref("      "))
        lines.append("    </entity>")
    lines.extend(
        [
            "  </enterprise-beans>",
            "  <assembly-descriptor>",
            "    <security-role>",
            "      <description>Clerks at the Harbor order desk.</description>",
            "      <role-name>desk</role-name>",
            "    </security-role>",
        ]
    )
    for session in manifest.sessions:
        for method in session.methods:
            lines.extend(method_permission(session.name, method))
            lines.extend(container_tx(session.name, method))
    for entity in manifest.entities:
        lines.extend(wildcard_permission(entity.name))
        lines.extend(wildcard_tx(entity.name))
    lines.extend(["  </assembly-descriptor>", "</ejb-jar>"])
    return finish(lines)


def method_permission(ejb: str, method: str) -> list[str]:
    return [
        "    <method-permission>",
        "      <role-name>desk</role-name>",
        "      <method>",
        f"        <ejb-name>{ejb}</ejb-name>",
        f"        <method-name>{method}</method-name>",
        "      </method>",
        "    </method-permission>",
    ]


def container_tx(ejb: str, method: str) -> list[str]:
    return [
        "    <container-transaction>",
        "      <method>",
        f"        <ejb-name>{ejb}</ejb-name>",
        f"        <method-name>{method}</method-name>",
        "      </method>",
        "      <trans-attribute>Required</trans-attribute>",
        "    </container-transaction>",
    ]


def wildcard_permission(ejb: str) -> list[str]:
    return [
        "    <method-permission>",
        "      <role-name>desk</role-name>",
        "      <method>",
        f"        <ejb-name>{ejb}</ejb-name>",
        "        <method-name>*</method-name>",
        "      </method>",
        "    </method-permission>",
    ]


def wildcard_tx(ejb: str) -> list[str]:
    return [
        "    <container-transaction>",
        "      <method>",
        f"        <ejb-name>{ejb}</ejb-name>",
        "        <method-name>*</method-name>",
        "      </method>",
        "      <trans-attribute>Required</trans-attribute>",
        "    </container-transaction>",
    ]


def render_weblogic_ejb(manifest: Manifest) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- WebLogic bindings for Harbor OMS. The container is not run from this repo. -->",
        '<weblogic-ejb-jar xmlns="http://www.bea.com/ns/weblogic/90">',
    ]
    for session in manifest.sessions:
        lines.extend(
            [
                "  <weblogic-enterprise-bean>",
                f"    <ejb-name>{session.name}</ejb-name>",
                "    <stateless-session-descriptor>",
                "      <pool>",
                f"        <max-beans-in-free-pool>{session.pool}</max-beans-in-free-pool>",
                "      </pool>",
                "    </stateless-session-descriptor>",
                "    <transaction-descriptor>",
                "      <trans-timeout-seconds>60</trans-timeout-seconds>",
                "    </transaction-descriptor>",
                f"    <jndi-name>ejb/harbor/{session.name}</jndi-name>",
            ]
        )
        lines.extend(resource_description("    ", manifest))
        for ref in session.entity_refs:
            lines.extend(ejb_link(ref))
        lines.append("  </weblogic-enterprise-bean>")
    caches = {"Customer": 200, "Product": 400, "SalesOrder": 300, "Shipment": 150}
    for entity in manifest.entities:
        lines.extend(
            [
                "  <weblogic-enterprise-bean>",
                f"    <ejb-name>{entity.name}</ejb-name>",
                "    <entity-descriptor>",
                "      <entity-cache>",
                f"        <max-beans-in-cache>{caches[entity.name]}</max-beans-in-cache>",
                "        <idle-timeout-seconds>600</idle-timeout-seconds>",
                "      </entity-cache>",
                "    </entity-descriptor>",
                "    <transaction-descriptor>",
                "      <trans-timeout-seconds>60</trans-timeout-seconds>",
                "    </transaction-descriptor>",
                f"    <jndi-name>ejb/harbor/{entity.name}</jndi-name>",
            ]
        )
        lines.extend(resource_description("    ", manifest))
        lines.append("  </weblogic-enterprise-bean>")
    lines.append("</weblogic-ejb-jar>")
    return finish(lines)


def resource_description(indent: str, manifest: Manifest) -> list[str]:
    return [
        f"{indent}<resource-description>",
        f"{indent}  <res-ref-name>jdbc/OrderDS</res-ref-name>",
        f"{indent}  <jndi-name>{manifest.datasource_global_jndi}</jndi-name>",
        f"{indent}</resource-description>",
    ]


def ejb_link(entity_name: str) -> list[str]:
    return [
        "    <ejb-reference-description>",
        f"      <ejb-ref-name>ejb/{entity_name}</ejb-ref-name>",
        f"      <jndi-name>ejb/harbor/{entity_name}</jndi-name>",
        "    </ejb-reference-description>",
    ]


def render_application(manifest: Manifest) -> str:
    return finish(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            "<application>",
            f"  <display-name>{xml_escape(manifest.app_name)}</display-name>",
            "  <module>",
            f"    <ejb>{manifest.ejb_jar}</ejb>",
            "  </module>",
            "  <module>",
            "    <web>",
            f"      <web-uri>{manifest.web_war}</web-uri>",
            f"      <context-root>{manifest.context_root}</context-root>",
            "    </web>",
            "  </module>",
            "</application>",
        ]
    )


def render_web_xml(manifest: Manifest) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<web-app xmlns="http://java.sun.com/xml/ns/j2ee" version="2.4">',
        f"  <display-name>{xml_escape(manifest.app_name)}</display-name>",
    ]
    for servlet in manifest.servlets:
        lines.extend(
            servlet_xml(
                manifest, servlet.name, servlet.description, f"com.harbor.oms.web.{servlet.name}"
            )
        )
        lines.extend(
            [
                "  <servlet-mapping>",
                f"    <servlet-name>{servlet.name}</servlet-name>",
                f"    <url-pattern>{servlet.url}</url-pattern>",
                "  </servlet-mapping>",
            ]
        )
    lines.extend(
        servlet_xml(
            manifest,
            "CatalogAdminServlet",
            "Browser post the warehouse office uses to save a sku.",
            "com.harbor.oms.catalog.CatalogAdminBean",
        )
    )
    lines.extend(
        [
            "  <servlet-mapping>",
            "    <servlet-name>CatalogAdminServlet</servlet-name>",
            "    <url-pattern>/admin/catalog</url-pattern>",
            "  </servlet-mapping>",
        ]
    )
    lines.extend(resource_ref("  "))
    service = manifest.session("OrderService")
    fqcn = service.fqcn(manifest.java_package)
    lines.extend(
        [
            "  <ejb-ref>",
            "    <ejb-ref-name>ejb/OrderService</ejb-ref-name>",
            "    <ejb-ref-type>Session</ejb-ref-type>",
            f"    <home>{fqcn}Home</home>",
            f"    <remote>{fqcn}</remote>",
            "  </ejb-ref>",
            "  <error-page>",
            "    <exception-type>java.lang.Exception</exception-type>",
            "    <location>/error.jsp</location>",
            "  </error-page>",
            "  <welcome-file-list>",
            "    <welcome-file>index.jsp</welcome-file>",
            "  </welcome-file-list>",
            "</web-app>",
        ]
    )
    return finish(lines)


def servlet_xml(manifest: Manifest, name: str, description: str, class_name: str) -> list[str]:
    del manifest
    return [
        "  <servlet>",
        f"    <description>{xml_escape(description)}</description>",
        f"    <servlet-name>{name}</servlet-name>",
        f"    <servlet-class>{class_name}</servlet-class>",
        "  </servlet>",
    ]


def render_weblogic_web(manifest: Manifest) -> str:
    return finish(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<weblogic-web-app xmlns="http://www.bea.com/ns/weblogic/90">',
            f"  <context-root>{manifest.context_root}</context-root>",
            *resource_description("  ", manifest),
            "  <ejb-reference-description>",
            "    <ejb-ref-name>ejb/OrderService</ejb-ref-name>",
            "    <jndi-name>ejb/harbor/OrderService</jndi-name>",
            "  </ejb-reference-description>",
            "</weblogic-web-app>",
        ]
    )


def render_schema(manifest: Manifest) -> str:
    lines = [
        "-- Harbor OMS physical model. Synthetic tables for the order desk.",
        "",
    ]
    for entity in manifest.entities:
        lines.append(f"-- {entity.description}")
        lines.append(f"CREATE TABLE {entity.table} (")
        for index, field in enumerate(entity.fields):
            nullability = "NOT NULL" if index == 0 else "NULL"
            comma = "," if index < len(entity.fields) - 1 else ""
            lines.append(f"    -- {field.name} ({field.java_type})")
            lines.append(f"    {field.column} {field.sql_type} {nullability}{comma}")
        lines.append(f"    , CONSTRAINT pk_{entity.table} PRIMARY KEY ({entity.pk().column})")
        lines.append(");")
        lines.append("")
    lines.extend(
        [
            "-- One packing line for each desk order.",
            "CREATE TABLE order_line (",
            "    order_id VARCHAR(32) NOT NULL,",
            "    line_no INTEGER NOT NULL,",
            "    sku VARCHAR(32) NOT NULL,",
            "    quantity INTEGER NOT NULL,",
            "    unit_price_cents BIGINT NOT NULL,",
            "    CONSTRAINT pk_order_line PRIMARY KEY (order_id, line_no)",
            ");",
            "",
            "ALTER TABLE sales_order ADD CONSTRAINT fk_sales_order_customer",
            "    FOREIGN KEY (customer_id) REFERENCES customer (customer_id);",
            "ALTER TABLE order_line ADD CONSTRAINT fk_order_line_order",
            "    FOREIGN KEY (order_id) REFERENCES sales_order (order_id);",
            "ALTER TABLE shipment ADD CONSTRAINT fk_shipment_order",
            "    FOREIGN KEY (order_id) REFERENCES sales_order (order_id);",
            "",
            "CREATE INDEX ix_customer_region ON customer (region_code);",
            "CREATE INDEX ix_sales_order_customer_status",
            "    ON sales_order (customer_id, status_code);",
            "CREATE INDEX ix_product_warehouse ON product (warehouse_code);",
            "CREATE INDEX ix_shipment_order ON shipment (order_id);",
            "",
        ]
    )
    return finish(lines)


def sql_value(java_type: str, value: object) -> str:
    if java_type == "String":
        if not isinstance(value, str) or "'" in value:
            raise ValueError("seed strings must be plain text")
        return "'" + value + "'"
    if java_type in {"int", "long"}:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("seed numbers must be integers")
        return str(value)
    raise ValueError(java_type)


def insert_statement(table: str, columns: Sequence[str], values: Sequence[str]) -> list[str]:
    lines = [f"INSERT INTO {table} ("]
    for index, column in enumerate(columns):
        comma = "," if index < len(columns) - 1 else ""
        lines.append(f"    {column}{comma}")
    lines.append(") VALUES (")
    for index, value in enumerate(values):
        comma = "," if index < len(values) - 1 else ""
        lines.append(f"    {value}{comma}")
    lines.append(");")
    lines.append("")
    return lines


def render_seed(manifest: Manifest) -> str:
    lines = ["-- Sample rows for the Harbor desk. Names are fictional.", ""]
    customers = manifest.entity("Customer")
    products = manifest.entity("Product")
    orders = manifest.entity("SalesOrder")
    shipments = manifest.entity("Shipment")
    customer_rows: tuple[tuple[object, ...], ...] = (
        (
            "C-100",
            "Pier Street Market",
            "NORTH",
            500000,
            "ACTIVE",
            "Ada Shore",
            "Harbor City",
            "2014-04-02",
        ),
        (
            "C-110",
            "North Dock Supply",
            "NORTH",
            250000,
            "ACTIVE",
            "Ben Calder",
            "Harbor City",
            "2015-01-19",
        ),
        (
            "C-120",
            "Lantern Hill Grocers",
            "SOUTH",
            800000,
            "ACTIVE",
            "Cora Nguyen",
            "Saltmere",
            "2012-11-03",
        ),
        (
            "C-130",
            "Westbreak Chandlery",
            "WEST",
            150000,
            "HOLD",
            "Diego Marsh",
            "Cape Rowan",
            "2016-06-28",
        ),
        (
            "C-140",
            "Eastwharf Bakery",
            "EAST",
            120000,
            "ACTIVE",
            "Eden Price",
            "Millhaven",
            "2018-02-14",
        ),
        (
            "C-150",
            "Keel and Crate",
            "SOUTH",
            640000,
            "ACTIVE",
            "Farah Quinn",
            "Saltmere",
            "2011-09-09",
        ),
        (
            "C-160",
            "Blue Buoy Provisions",
            "WEST",
            300000,
            "ACTIVE",
            "Gus Hale",
            "Cape Rowan",
            "2017-05-21",
        ),
        (
            "C-170",
            "Closed Pier Cafe",
            "EAST",
            90000,
            "CLOSED",
            "Hana Ito",
            "Millhaven",
            "2009-12-01",
        ),
    )
    product_rows: tuple[tuple[object, ...], ...] = (
        ("SKU-FLOUR", "Stone flour 25kg", 4200, 80, "DOCK-N", 20, "Y", "V-MILL"),
        ("SKU-OIL", "Lamp oil 12L", 3100, 40, "DOCK-N", 10, "Y", "V-MILL"),
        ("SKU-SALT", "Bay salt 10kg", 900, 120, "DOCK-S", 30, "Y", "V-SALT"),
        ("SKU-ROPE", "Manila rope 30m", 2500, 15, "DOCK-W", 8, "Y", "V-CORD"),
        ("SKU-NAIL", "Copper nails 5kg", 1800, 200, "DOCK-W", 40, "Y", "V-CORD"),
        ("SKU-TEA", "Dock tea 1kg", 1500, 60, "DOCK-E", 12, "Y", "V-LEAF"),
        ("SKU-BEAN", "Dry beans 20kg", 2700, 50, "DOCK-S", 15, "Y", "V-MILL"),
        ("SKU-SOAP", "Galley soap 4kg", 800, 10, "DOCK-E", 25, "Y", "V-LEAF"),
    )
    order_rows: tuple[tuple[object, ...], ...] = (
        (
            "C-100-2024-03-01-SKU-FLOUR",
            "C-100",
            "OPEN",
            "2024-03-01",
            "2024-03-04",
            21000,
            "USD",
            "PO-441",
            "DOCK-N",
            "SKU-FLOUR",
            5,
        ),
        (
            "C-120-2024-03-02-SKU-BEAN",
            "C-120",
            "OPEN",
            "2024-03-02",
            "2024-03-06",
            54000,
            "USD",
            "PO-442",
            "DOCK-S",
            "SKU-BEAN",
            20,
        ),
        (
            "C-140-2024-03-03-SKU-TEA",
            "C-140",
            "ALLOCATED",
            "2024-03-03",
            "2024-03-05",
            15000,
            "USD",
            "PO-443",
            "DOCK-E",
            "SKU-TEA",
            10,
        ),
        (
            "C-150-2024-02-20-SKU-SALT",
            "C-150",
            "SHIPPED",
            "2024-02-20",
            "2024-02-22",
            9000,
            "USD",
            "PO-410",
            "DOCK-S",
            "SKU-SALT",
            10,
        ),
        (
            "C-160-2024-02-11-SKU-ROPE",
            "C-160",
            "DELIVERED",
            "2024-02-11",
            "2024-02-14",
            5000,
            "USD",
            "PO-388",
            "DOCK-W",
            "SKU-ROPE",
            2,
        ),
        (
            "C-110-2024-01-09-SKU-OIL",
            "C-110",
            "CANCELLED",
            "2024-01-09",
            "2024-01-12",
            6200,
            "USD",
            "PO-301",
            "DOCK-N",
            "SKU-OIL",
            2,
        ),
    )
    shipment_rows: tuple[tuple[object, ...], ...] = (
        (
            "C-140-2024-03-03-SKU-TEA-S1",
            "C-140-2024-03-03-SKU-TEA",
            "Harbor Barge",
            "",
            "",
            "STAGED",
            0,
            "DOOR-1",
        ),
        (
            "C-150-2024-02-20-SKU-SALT-S1",
            "C-150-2024-02-20-SKU-SALT",
            "Coast Wagon",
            "TRK-150",
            "2024-02-22",
            "SHIPPED",
            10000,
            "DOOR-2",
        ),
        (
            "C-160-2024-02-11-SKU-ROPE-S1",
            "C-160-2024-02-11-SKU-ROPE",
            "Coast Wagon",
            "TRK-088",
            "2024-02-14",
            "DELIVERED",
            4000,
            "DOOR-3",
        ),
    )
    lines.extend(seed_entity(customers, customer_rows))
    lines.extend(seed_entity(products, product_rows))
    lines.extend(seed_entity(orders, order_rows))
    lines.extend(seed_lines(order_rows))
    lines.extend(seed_entity(shipments, shipment_rows))
    return finish(lines)


def seed_entity(entity: Entity, rows: Sequence[tuple[object, ...]]) -> list[str]:
    columns = [field.column for field in entity.fields]
    lines: list[str] = []
    for row in rows:
        if len(row) != len(entity.fields):
            raise ValueError(f"{entity.name} seed width drifted")
        values = [
            sql_value(field.java_type, value)
            for field, value in zip(entity.fields, row, strict=True)
        ]
        lines.extend(insert_statement(entity.table, columns, values))
    return lines


def seed_lines(order_rows: Sequence[tuple[object, ...]]) -> list[str]:
    lines: list[str] = []
    for row in order_rows:
        order_id = row[0]
        total = row[5]
        sku = row[9]
        quantity = row[10]
        if not isinstance(order_id, str) or not isinstance(sku, str):
            raise ValueError("order seed ids must be strings")
        if isinstance(total, bool) or not isinstance(total, int):
            raise ValueError("order total must be an integer")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("order quantity must be a positive integer")
        unit = total // quantity
        lines.extend(
            insert_statement(
                "order_line",
                ["order_id", "line_no", "sku", "quantity", "unit_price_cents"],
                [
                    sql_value("String", order_id),
                    "1",
                    sql_value("String", sku),
                    str(quantity),
                    str(unit),
                ],
            )
        )
    return lines


def render_build(manifest: Manifest) -> dict[str, str]:
    properties = finish(
        [
            f"app.name={manifest.ear.removesuffix('.ear')}",
            "app.version=1.4.2",
            "java.source=1.5",
            "java.target=1.5",
            f"datasource.jndi={manifest.datasource_global_jndi}",
            f"ejb.jar={manifest.ejb_jar}",
            f"web.war={manifest.web_war}",
            f"ear.name={manifest.ear}",
            f"context.root={manifest.context_root}",
        ]
    )
    script = finish(
        [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<project name="harbor-oms" default="ear" basedir=".">',
            "  <!--",
            "    Harbor OMS. Compiles the desk sources and packs an EAR.",
            "    The Java EE libraries come from the app server, via J2EE_HOME.",
            "    Order DAO sources live at src/com/harbor/oms/dao.",
            "  -->",
            '  <property file="build.properties"/>',
            '  <property environment="env"/>',
            '  <property name="j2ee.lib" value="${env.J2EE_HOME}/lib/j2ee.jar"/>',
            '  <property name="build.dir" value="build"/>',
            '  <property name="classes.dir" value="${build.dir}/classes"/>',
            "",
            '  <target name="init">',
            '    <mkdir dir="${classes.dir}"/>',
            "  </target>",
            "",
            '  <target name="compile" depends="init">',
            "    <javac",
            '        srcdir="src"',
            '        destdir="${classes.dir}"',
            '        source="${java.source}"',
            '        target="${java.target}"',
            '        debug="on"',
            '        includeantruntime="false">',
            '      <classpath path="${j2ee.lib}"/>',
            '      <include name="com/harbor/oms/**/*.java"/>',
            "    </javac>",
            "  </target>",
            "",
            '  <target name="ejb-jar" depends="compile">',
            '    <jar destfile="${build.dir}/${ejb.jar}">',
            '      <fileset dir="${classes.dir}" includes="com/harbor/oms/**/*.class"/>',
            '      <metainf dir="dd" includes="ejb-jar.xml,weblogic-ejb-jar.xml"/>',
            "    </jar>",
            "  </target>",
            "",
            '  <target name="war" depends="compile">',
            '    <war destfile="${build.dir}/${web.war}" webxml="web/WEB-INF/web.xml">',
            '      <fileset dir="web" excludes="WEB-INF/web.xml"/>',
            '      <classes dir="${classes.dir}" includes="com/harbor/oms/web/**/*.class"/>',
            '      <classes dir="${classes.dir}" includes="com/harbor/oms/catalog/**/*.class"/>',
            "    </war>",
            "  </target>",
            "",
            '  <target name="ear" depends="ejb-jar,war">',
            '    <ear destfile="${build.dir}/${ear.name}" appxml="dd/application.xml">',
            '      <fileset dir="${build.dir}" includes="${ejb.jar},${web.war}"/>',
            "    </ear>",
            "  </target>",
            "",
            '  <target name="clean">',
            '    <delete dir="${build.dir}"/>',
            "  </target>",
            "</project>",
        ]
    )
    return {"build.properties": properties, "build.xml": script}


def html_page(title: str, body: Sequence[str]) -> str:
    lines = [
        '<%@ page contentType="text/html; charset=UTF-8" %>',
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        '  <meta charset="UTF-8"/>',
        f"  <title>{title}</title>",
        "</head>",
        "<body>",
        "  <h1>Harbor order desk</h1>",
        f"  <h2>{title}</h2>",
        "  <p>",
        '    <a href="index.jsp">Home</a>',
        '    | <a href="order-entry.jsp">New order</a>',
        '    | <a href="order-list.jsp">Order status</a>',
        "  </p>",
        *body,
        "  <hr/>",
        "  <p>Pier office, doors 1 to 4. Stored prices are whole cents.</p>",
        "</body>",
        "</html>",
    ]
    return finish(lines)


def render_pages() -> dict[str, str]:
    index = html_page(
        "Desk home",
        [
            "  <ol>",
            "    <li>Confirm the buyer is active before taking a sku.</li>",
            "    <li>Reserve stock, then write the order with the buyer's PO.</li>",
            "    <li>Stage a shipment only after the order is open.</li>",
            "    <li>Mark the shipment shipped with a tracking number.</li>",
            "    <li>Mark it delivered when the barge or wagon reports in.</li>",
            "  </ol>",
            "  <ul>",
            '    <li><a href="<%= request.getContextPath() %>/orders/new">Place an order</a></li>',
            (
                '    <li><a href="<%= request.getContextPath() %>/orders/status">'
                "Look up orders</a></li>"
            ),
            '    <li><a href="<%= request.getContextPath() %>/admin/catalog">Catalog desk</a></li>',
            "  </ul>",
        ],
    )
    entry = html_page(
        "Place an order",
        [
            '  <form method="post" action="<%= request.getContextPath() %>/orders/new">',
            '    <p>Customer id<br/><input name="customerId"/></p>',
            '    <p>SKU<br/><input name="sku"/></p>',
            '    <p>Quantity<br/><input name="quantity"/></p>',
            '    <p>Placed on (yyyy-mm-dd)<br/><input name="placedOn"/></p>',
            '    <p>Requested ship (yyyy-mm-dd)<br/><input name="requestedShip"/></p>',
            '    <p>Buyer PO<br/><input name="buyerPo"/></p>',
            '    <p><button type="submit">Place order</button></p>',
            "  </form>",
            "  <p>A held or closed buyer is refused. The sku must be active.</p>",
        ],
    )
    listing = html_page(
        "Order status",
        [
            '  <form method="post" action="<%= request.getContextPath() %>/orders/status">',
            '    <p>Customer id<br/><input name="customerId"/></p>',
            "    <p>Status<br/>",
            '      <select name="statusCode">',
            "        <option>OPEN</option>",
            "        <option>ALLOCATED</option>",
            "        <option>SHIPPED</option>",
            "        <option>DELIVERED</option>",
            "        <option>CANCELLED</option>",
            "      </select>",
            "    </p>",
            '    <p><button type="submit">Find orders</button></p>',
            "  </form>",
            "  <%",
            '    String orderList = (String) request.getAttribute("orderList");',
            "    if (orderList == null) {",
            '        orderList = "";',
            "    }",
            "  %>",
            "  <h3>Matching orders</h3>",
            "  <p><%= orderList %></p>",
        ],
    )
    detail = html_page(
        "Order accepted",
        [
            "  <%",
            '    String orderId = (String) request.getAttribute("orderId");',
            '    String customerId = (String) request.getAttribute("customerId");',
            '    String sku = (String) request.getAttribute("sku");',
            "    if (orderId == null) {",
            '        orderId = "";',
            "    }",
            "    if (customerId == null) {",
            '        customerId = "";',
            "    }",
            "    if (sku == null) {",
            '        sku = "";',
            "    }",
            "  %>",
            "  <p>Order <strong><%= orderId %></strong></p>",
            "  <p>Customer <%= customerId %>, sku <%= sku %>.</p>",
            "  <p>The desk has reserved the quantity and stored the buyer PO.</p>",
        ],
    )
    error = html_page(
        "Desk message",
        [
            "  <%",
            '    String deskMessage = (String) request.getAttribute("deskMessage");',
            "    if (deskMessage == null) {",
            '        deskMessage = "The desk could not complete that step.";',
            "    }",
            "  %>",
            "  <p><%= deskMessage %></p>",
        ],
    )
    return {
        "web/index.jsp": index,
        "web/order-entry.jsp": entry,
        "web/order-list.jsp": listing,
        "web/order-detail.jsp": detail,
        "web/error.jsp": error,
    }


def render(manifest: Manifest) -> dict[str, str]:
    files: dict[str, str] = {}
    for entity in manifest.entities:
        put(files, java_path(entity.subpackage, entity.name), render_remote(manifest, entity))
        put(
            files, java_path(entity.subpackage, entity.name + "Home"), render_home(manifest, entity)
        )
        put(
            files,
            java_path(entity.subpackage, entity.name + "Bean"),
            render_entity_bean(manifest, entity),
        )
        put(files, java_path("dao", entity.dao), render_dao(manifest, entity))
    for session in manifest.sessions:
        put(
            files,
            java_path(session.subpackage, session.name),
            render_session_remote(manifest, session),
        )
        put(
            files,
            java_path(session.subpackage, session.name + "Home"),
            render_session_home(manifest, session),
        )
        put(
            files,
            java_path(session.subpackage, session.name + "Bean"),
            render_session_bean(manifest, session),
        )
    for servlet in manifest.servlets:
        put(files, java_path("web", servlet.name), render_servlet(manifest, servlet))
    for rel, text in render_support().items():
        put(files, rel, text)
    put(files, "dd/ejb-jar.xml", render_ejb_jar(manifest))
    put(files, "dd/weblogic-ejb-jar.xml", render_weblogic_ejb(manifest))
    put(files, "dd/application.xml", render_application(manifest))
    put(files, "sql/schema.sql", render_schema(manifest))
    put(files, "sql/seed.sql", render_seed(manifest))
    put(files, "web/WEB-INF/web.xml", render_web_xml(manifest))
    put(files, "web/WEB-INF/weblogic.xml", render_weblogic_web(manifest))
    for rel, text in render_pages().items():
        put(files, rel, text)
    for rel, text in render_build(manifest).items():
        put(files, rel, text)
    check_planted(manifest, files)
    line_count = sum(text.count("\n") for text in files.values())
    if not 42 <= len(files) <= 60:
        raise ValueError(f"sample file count {len(files)} is outside the expected shape")
    if not 5500 <= line_count <= 8000:
        raise ValueError(f"sample line count {line_count} is outside the expected shape")
    return files


def put(files: dict[str, str], rel: str, text: str) -> None:
    if rel in files:
        raise ValueError(f"duplicate path {rel}")
    if ".." in rel.split("/") or rel.startswith("/"):
        raise ValueError(f"unsafe path {rel}")
    if not text.endswith("\n") or text.strip() == "":
        raise ValueError(f"{rel} is empty or missing its trailing newline")
    check_balance(rel, text)
    for banned in BANNED_OUTPUT:
        if banned in text:
            raise ValueError(f"{rel} contains {banned}")
    files[rel] = text


def check_planted(manifest: Manifest, files: Mapping[str, str]) -> None:
    jndi_line = f'        return (DataSource) naming.lookup("{manifest.datasource_jndi}");'
    jndi_files = sorted(rel for rel, text in files.items() if jndi_line in text)
    expected = sorted(
        java_path(entity.subpackage, entity.name + "Bean") for entity in manifest.entities
    ) + sorted(
        java_path(session.subpackage, session.name + "Bean") for session in manifest.sessions
    )
    expected_sorted = sorted(expected)
    if jndi_files != expected_sorted or len(jndi_files) != manifest.planted.jndi_class_count:
        raise ValueError(f"JNDI lookup is in {jndi_files}, expected {expected_sorted}")
    for rel in jndi_files:
        if files[rel].count(jndi_line) != 1:
            raise ValueError(f"{rel} repeats the JNDI lookup")
    pricing = java_path("pricing", "PricingServiceBean")
    tx_files = sorted(rel for rel, text in files.items() if "getUserTransaction()" in text)
    if tx_files != [pricing]:
        raise ValueError(f"UserTransaction is in {tx_files}")
    pricing_text = files[pricing]
    if "transaction.begin()" not in pricing_text or "transaction.commit()" not in pricing_text:
        raise ValueError("PricingServiceBean does not begin and commit a transaction")
    xml = files["dd/ejb-jar.xml"]
    if session_transaction_type(xml, TX_EJB) != "Container":
        raise ValueError("PricingService is not container-managed in ejb-jar.xml")
    if "<transaction-type>Bean</transaction-type>" in xml:
        raise ValueError("ejb-jar.xml declares a bean-managed transaction")
    if not has_method_tx(xml, TX_EJB, TX_METHOD, "Required"):
        raise ValueError("applyPriceOverride has no Required container transaction")
    dao_rel = java_path("dao", CONCAT_DAO)
    dao_text = files[dao_rel]
    marker = "FROM sales_order WHERE customer_id = '\" + customerId + \"'"
    status_marker = "AND status_code = '\" + statusCode + \"'"
    if marker not in dao_text or status_marker not in dao_text:
        raise ValueError("OrderDao does not concatenate the search SQL")
    if "createStatement()" not in dao_text or "executeQuery(sql)" not in dao_text:
        raise ValueError("OrderDao does not execute the concatenated SQL")
    others = [rel for rel, text in files.items() if rel != dao_rel and "createStatement()" in text]
    if others:
        raise ValueError(f"createStatement also appears in {others}")
    catalog = java_path("catalog", "CatalogAdminBean")
    http_files = sorted(
        rel
        for rel, text in files.items()
        if "extends HttpServlet" in text and "implements SessionBean" in text
    )
    if http_files != [catalog]:
        raise ValueError(f"HTTP session beans: {http_files}")
    catalog_text = files[catalog]
    if "doPost(" not in catalog_text or "executeUpdate()" not in catalog_text:
        raise ValueError("CatalogAdminBean does not serve HTTP and write a row")
    plain_servlets = [
        rel
        for rel, text in files.items()
        if text.find("extends HttpServlet") >= 0 and "implements SessionBean" not in text
    ]
    if len(plain_servlets) != 2:
        raise ValueError(f"expected two servlets, found {plain_servlets}")
    if "com.harbor.oms.catalog.CatalogAdminBean" not in files["web/WEB-INF/web.xml"]:
        raise ValueError("web.xml does not publish CatalogAdminBean")
    if f"<ejb-class>{JAVA_PACKAGE}.catalog.CatalogAdminBean</ejb-class>" not in xml:
        raise ValueError("ejb-jar.xml does not declare CatalogAdminBean")


def session_transaction_type(xml: str, ejb: str) -> str:
    match = re.search(
        rf"<ejb-name>{re.escape(ejb)}</ejb-name>.*?<transaction-type>(.*?)</transaction-type>",
        xml,
        re.DOTALL,
    )
    if match is None:
        raise ValueError(f"{ejb} has no transaction-type")
    return match.group(1)


def has_method_tx(xml: str, ejb: str, method: str, attribute: str) -> bool:
    pattern = re.compile(
        r"<container-transaction>\s*<method>\s*"
        rf"<ejb-name>{re.escape(ejb)}</ejb-name>\s*"
        rf"<method-name>{re.escape(method)}</method-name>\s*"
        r"</method>\s*"
        rf"<trans-attribute>{re.escape(attribute)}</trans-attribute>\s*"
        r"</container-transaction>",
    )
    return pattern.search(xml) is not None


def write_tree(out: Path, files: Mapping[str, str]) -> None:
    if out.exists():
        raise ValueError(f"output already exists: {out}")
    out.mkdir(parents=True)
    root = out.resolve()
    for rel in sorted(files):
        dest = out.joinpath(*rel.split("/"))
        if not dest.resolve().is_relative_to(root):
            raise ValueError(f"path escapes the output directory: {rel}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            raise ValueError(f"refusing to write through a symlink: {rel}")
        dest.write_bytes(files[rel].encode("utf-8"))


def generate(manifest_path: Path, out: Path) -> tuple[int, int]:
    files = render(load_manifest(manifest_path))
    write_tree(out, files)
    return len(files), sum(text.count("\n") for text in files.values())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Harbor OMS sample from its manifest."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    manifest_path = args.manifest
    out = args.out
    if not isinstance(manifest_path, Path) or not isinstance(out, Path):
        print("error: manifest and out must be paths", file=sys.stderr)
        return 1
    try:
        count, lines = generate(manifest_path, out)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {count} files, {lines} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
