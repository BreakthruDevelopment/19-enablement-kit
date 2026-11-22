"""A stdio stand-in for the gateway. Not app 18, and not imported by the kit.

Modes are the first argument. An optional second argument is a file that receives one
method name per request, so a test can see that a call was not repeated. The six tool
names are the service principal's list, in the gateway's published order, written out
here so this process is not reading the frozen file it is supposed to be checked against.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# The service principal's tools, in app 18's gateway-table order. Not sorted by name.
READ_TOOLS = (
    "find_supplier",
    "get_purchase_order",
    "get_goods_receipt",
    "get_invoice",
    "list_open_invoices",
    "get_payment_status",
)

SUCCESS: dict[str, object] = {"company_code": "1000", "id": "INV-1001", "state": "received"}
PERMISSION: dict[str, object] = {
    "error_category": "permission",
    "is_retryable": False,
    "message": "no invoice visible to this principal",
}
UNKNOWN_TOOL: dict[str, object] = {
    "error_category": "validation",
    "is_retryable": False,
    "message": "no such tool",
}
TRANSIENT: dict[str, object] = {
    "error_category": "transient",
    "is_retryable": True,
    "message": "the database is busy",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    mode = args[1] if len(args) > 1 else "conform"
    log_path = Path(args[2]) if len(args) > 2 else None
    if mode == "die":
        return 0
    for raw in sys.stdin:
        if raw.strip() == "":
            continue
        message = _message(raw)
        if message is None:
            _emit(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "parse error"},
                }
            )
            continue
        method = message.get("method")
        if isinstance(method, str):
            _log(log_path, method)
        if "id" not in message:
            continue
        if mode == "hang":
            time.sleep(5)
            return 0
        if mode == "flood":
            # More than one message cap, with no newline anywhere. The client cannot stop on a
            # line boundary, so its bound on the unterminated buffer is the only thing between
            # it and reading until it runs out of memory.
            block = "x" * 65536
            for _ in range(20):
                sys.stdout.write(block)
            sys.stdout.flush()
            time.sleep(5)
            return 0
        if mode == "garbage" and method == "tools/call":
            sys.stdout.write("LEAK-this-body\n")
            sys.stdout.flush()
            continue
        _emit(_respond(mode, message))
    return 0


def _message(raw: str) -> dict[str, object] | None:
    try:
        parsed: object = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    message: dict[str, object] = {}
    for key, value in parsed.items():
        if isinstance(key, str):
            message[key] = value
    return message


def _respond(mode: str, message: dict[str, object]) -> dict[str, object]:
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        name = "other" if mode == "drift-server" else "p2p-erp"
        return _result(
            request_id,
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": name, "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": _tools(mode)})
    if method == "tools/call":
        return _result(request_id, _call(mode, message.get("params")))
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": "method not found"},
    }


def _tools(mode: str) -> list[dict[str, object]]:
    names = list(READ_TOOLS)
    if mode == "drift-missing":
        names = [name for name in names if name != "get_payment_status"]
    if mode == "drift-extra":
        names.append("release_payment")
    listed = [_descriptor(name, read_only=True) for name in names]
    if mode == "drift-effect":
        listed = [
            _descriptor(tool["name"], read_only=tool["name"] != "get_invoice")
            if isinstance(tool["name"], str)
            else tool
            for tool in listed
        ]
    if mode == "drift-duplicate":
        listed.append(_descriptor("get_invoice", read_only=True))
    return listed


def _descriptor(name: object, *, read_only: bool) -> dict[str, object]:
    return {
        "name": name,
        "description": "a stub tool",
        "annotations": {"readOnlyHint": read_only},
    }


def _call(mode: str, params: object) -> dict[str, object]:
    if mode == "transient":
        return _body(TRANSIENT, is_error=True)
    if mode == "drift-error":
        return _body({"error_category": "permission", "message": "no such tool"}, is_error=True)
    if mode == "drift-retry":
        return _body(
            {"error_category": "permission", "is_retryable": True, "message": "no such tool"},
            is_error=True,
        )
    if mode == "drift-category":
        return _body(
            {"error_category": "exploded", "is_retryable": False, "message": "no such tool"},
            is_error=True,
        )
    if mode == "drift-success":
        return _body({"id": "INV-1001"}, is_error=False)
    if mode == "disagree":
        return {
            "content": [{"type": "text", "text": '{"ok":true}'}],
            "isError": False,
            "structuredContent": dict(UNKNOWN_TOOL),
        }
    name, arguments = _params(params)
    if name == "get_invoice" and arguments.get("invoice_id") == "INV-1001":
        return _body(SUCCESS, is_error=False)
    if name == "get_invoice" and arguments.get("invoice_id") == "INV-2001":
        return _body(PERMISSION, is_error=True)
    return _body(UNKNOWN_TOOL, is_error=True)


def _params(params: object) -> tuple[str, dict[str, object]]:
    if not isinstance(params, dict):
        return "", {}
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(name, str):
        name = ""
    if not isinstance(arguments, dict):
        return name, {}
    cleaned: dict[str, object] = {}
    for key, value in arguments.items():
        if isinstance(key, str):
            cleaned[key] = value
    return name, cleaned


def _body(payload: dict[str, object], *, is_error: bool) -> dict[str, object]:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
        "structuredContent": payload,
    }


def _result(request_id: object, result: dict[str, object]) -> dict[str, object]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _log(path: Path | None, method: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(method + "\n")
        handle.flush()


if __name__ == "__main__":
    raise SystemExit(main())
