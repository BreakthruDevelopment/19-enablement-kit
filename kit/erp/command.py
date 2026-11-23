"""`kit erp <tool> [args]`: one read call, replayed unless `--live` is set.

Exit codes:

* `0` -- the gateway returned a structured result, printed to stdout.
* `1` -- the gateway returned a structured error. It is printed as the gateway sent it,
  with its `error_category` and `is_retryable`, and it was not retried.
* `2` -- refused before a result: the principal may not call, the tool is not a service
  read, the arguments are wrong, the recording has no such call, or the gateway could
  not be spoken to.

A completed call also writes one JSON log line to stderr. The line names the tool and
the category. It does not carry arguments or the result body.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, TextIO, cast

from pydantic import JsonValue

from kit.core.config import Config
from kit.core.contract import load_contract
from kit.core.errors import KitError
from kit.core.principals import Capability, Principal, Role, assert_can
from kit.erp.client import call_read
from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult

__all__ = ["parse_arguments", "register_erp", "render_result", "run_erp", "run_erp_command"]

_KEY: Final = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_CATEGORIES: Final = frozenset({"transient", "validation", "permission", "business", "internal"})


def register_erp(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `erp` to the CLI's one subparser group."""
    erp = commands.add_parser(
        "erp",
        help="one read call to the ERP gateway, replayed by default",
        description=(
            "Call one read tool on the ERP gateway. The default replays the recorded "
            "transcript and starts no process. --live runs gateway.command instead."
        ),
    )
    erp.add_argument("tool", help="a read tool from the frozen contract")
    erp.add_argument(
        "args",
        nargs="*",
        help="key=value arguments (values are JSON when they parse), or one JSON object",
    )
    erp.add_argument(
        "--live",
        action="store_true",
        help="call the configured gateway instead of replaying the recording",
    )
    erp.add_argument("--config", type=Path, default=None, help="a kit.toml to load")
    erp.add_argument(
        "--principal",
        default=Role.ENGINEER.value,
        choices=[role.value for role in Role],
        help="acting principal. engineer and lead may call; ci may not. Defaults to engineer.",
    )
    erp.add_argument(
        "--subject",
        default=None,
        help="subject token. Defaults to the role name, or github-actions for ci.",
    )


def run_erp_command(args: argparse.Namespace) -> int:
    """The CLI entry. `run_erp` owns the exit codes."""
    tokens = getattr(args, "args", ())
    tool = getattr(args, "tool", "")
    config_path = getattr(args, "config", None)
    raw_subject = getattr(args, "subject", None)
    return run_erp(
        tool if isinstance(tool, str) else "",
        tuple(tokens) if isinstance(tokens, list) else (),
        role=str(getattr(args, "principal", Role.ENGINEER.value)),
        subject=raw_subject if isinstance(raw_subject, str) else None,
        config_path=config_path if isinstance(config_path, Path) else None,
        live=bool(getattr(args, "live", False)),
    )


def run_erp(
    tool: str,
    argument_tokens: Sequence[str],
    *,
    role: str,
    subject: str | None,
    config: Config | None = None,
    config_path: Path | None = None,
    live: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Render one call. See the module docstring for the exit codes."""
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        # The principal is checked before arguments are read, so a refusal never depends
        # on what the caller asked the gateway for.
        principal = _principal(role, subject)
        assert_can(principal, Capability.CALL_GATEWAY)
        loaded = _load_config(config, config_path)
        result = call_read(
            principal,
            load_contract(loaded.contract_path),
            tool,
            parse_arguments(argument_tokens),
            config=loaded.gateway,
            live=live or loaded.gateway.live,
        )
    except (KitError, ErpError) as refusal:
        print(str(refusal), file=err)
        return 2
    _log(tool, result, err)
    out.write(render_result(result))
    return 1 if result.is_error else 0


def parse_arguments(tokens: Sequence[str]) -> dict[str, JsonValue]:
    """`key=value` pairs, or a single JSON object. A bad token is refused without quoting it.

    A value that parses as JSON is taken as that JSON, so `limit=5` is a number and
    `invoice_id=INV-1001` stays a string. One argument that starts with `{` is the whole
    object and is not read as a pair.
    """
    if not all(isinstance(token, str) for token in tokens):
        raise ErpError(ErpCode.BAD_ARGUMENTS)
    if len(tokens) == 1 and tokens[0].startswith("{"):
        return _object_argument(tokens[0])
    parsed: dict[str, JsonValue] = {}
    for token in tokens:
        key, sep, value = token.partition("=")
        if sep != "=" or _KEY.fullmatch(key) is None or key in parsed:
            raise ErpError(ErpCode.BAD_ARGUMENTS)
        parsed[key] = _value(value)
    return parsed


def render_result(result: CallResult) -> str:
    """The structured body, pretty-printed. The gateway's fields are not rewritten."""
    return (
        json.dumps(
            dict(result.structured),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _object_argument(token: str) -> dict[str, JsonValue]:
    try:
        parsed = json.loads(token)
    except json.JSONDecodeError:
        raise ErpError(ErpCode.BAD_ARGUMENTS) from None
    if not isinstance(parsed, dict):
        raise ErpError(ErpCode.BAD_ARGUMENTS)
    return cast(dict[str, JsonValue], parsed)


def _value(value: str) -> JsonValue:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return cast(JsonValue, parsed)


def _load_config(config: Config | None, path: Path | None) -> Config:
    if config is not None:
        return config
    if path is not None:
        return Config.from_toml(path)
    return Config.default()


def _principal(role: str, subject: str | None) -> Principal:
    try:
        chosen = Role(role)
    except ValueError:
        raise ErpError(ErpCode.BAD_ARGUMENTS) from None
    name = subject if subject is not None else _default_subject(chosen)
    return Principal(chosen, name)


def _default_subject(role: Role) -> str:
    if role is Role.CI:
        return "github-actions"
    return role.value


def _log(tool: str, result: CallResult, err: TextIO) -> None:
    # The tool was checked against the contract before a result exists. A name that is
    # not one of those tokens is not logged: the log line is fixed fields only.
    if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", tool) is None:
        return
    category: str | None
    if result.is_error:
        raw = result.error_category
        category = raw if raw in _CATEGORIES else "invalid"
    else:
        category = None
    line = {
        "error_category": category,
        "event": "erp.call",
        "is_error": result.is_error,
        "is_retryable": result.is_retryable,
        "tool": tool,
    }
    err.write(json.dumps(line, sort_keys=True) + "\n")
