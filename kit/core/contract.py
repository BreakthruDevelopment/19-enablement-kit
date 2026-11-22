"""App 18's gateway contract, frozen.

App 19 does **not** check out or import app 18. App 18's spec publishes its gateway's tool list and
error shape as a contract; this repo commits a frozen copy at `contracts/p2p-erp.json` and tests
against it. The gateway itself is reached as an external process named in `gateway.command`, so CI
and the default demo run entirely on a recorded transcript and need no app 18 anywhere, while a
live run can assert that the gateway's own tool list and error shape still match the frozen copy --
a drift in app 18 then fails loudly here instead of silently.

This module is the schema and the loader. The frozen JSON lives in the repository rather than in
the wheel, so a caller passes its path (`Config.contract_path`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from agent_container.core.tool import ErrorCategory
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from kit.core.errors import ErrorCode, KitError, safe_token

__all__ = ["ContractTool", "ErrorShape", "GatewayContract", "ServerInfo", "load_contract"]

_STRICT = ConfigDict(extra="forbid", frozen=True)

# The five app-17 categories, in app 17's own order. The frozen contract must name exactly these:
# app 18 maps every gateway error onto one of them, and a copy that drifted would be worse than no
# copy at all.
_CATEGORIES: tuple[str, ...] = tuple(category.value for category in ErrorCategory)


class ServerInfo(BaseModel):
    """How the gateway is spoken to."""

    model_config = _STRICT

    name: Literal["p2p-erp"]
    transport: Literal["stdio"]


class ContractTool(BaseModel):
    """One MCP tool the gateway exposes."""

    model_config = _STRICT

    # Pydantic compiles patterns with Rust's regex crate, which has no `\A`/`\Z`; there `$` is the
    # end of the haystack and does not match before a trailing newline, so `^...$` is exact here.
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    effect: Literal["read", "write"]
    roles: tuple[str, ...] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=400)


class ErrorShape(BaseModel):
    """The error payload every gateway failure carries."""

    model_config = _STRICT

    fields: tuple[str, ...] = Field(min_length=1)
    categories: tuple[str, ...] = Field(min_length=1)
    retryable_categories: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> ErrorShape:
        if tuple(self.categories) != _CATEGORIES:
            raise ValueError("categories must be app 17's five, in order")
        if "error_category" not in self.fields or "is_retryable" not in self.fields:
            raise ValueError("fields must carry error_category and is_retryable")
        if not set(self.retryable_categories) <= set(self.categories):
            raise ValueError("retryable_categories must be a subset of categories")
        return self


class GatewayContract(BaseModel):
    """The frozen tool list and error shape."""

    model_config = _STRICT

    contract_version: int = Field(ge=1)
    source: str = Field(min_length=1, max_length=400)
    frozen_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    server: ServerInfo
    tools: tuple[ContractTool, ...] = Field(min_length=1)
    errors: ErrorShape

    @model_validator(mode="after")
    def _check(self) -> GatewayContract:
        names = [tool.name for tool in self.tools]
        if len(set(names)) != len(names):
            raise ValueError("tool names must be unique")
        if names != sorted(names):
            raise ValueError("tools must be sorted by name")
        return self

    def tool(self, name: str) -> ContractTool | None:
        return next((tool for tool in self.tools if tool.name == name), None)

    @property
    def read_tools(self) -> tuple[ContractTool, ...]:
        """The tools app 19 may call: it connects as a read-only principal."""
        return tuple(tool for tool in self.tools if tool.effect == "read")


def load_contract(path: Path) -> GatewayContract:
    """Load and validate the frozen contract.

    Raises `KitError` with `contract.unreadable` if the file is missing or is not JSON, and
    `contract.invalid` if it does not match the schema. Neither message quotes the file.
    """
    try:
        raw = path.read_bytes()
    except OSError as err:
        raise KitError(ErrorCode.CONTRACT_UNREADABLE) from err
    try:
        data = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise KitError(ErrorCode.CONTRACT_UNREADABLE) from err
    try:
        return GatewayContract.model_validate(data)
    except ValidationError as err:
        first = err.errors()[0]
        location = ".".join(str(part) for part in first["loc"])
        raise KitError(
            ErrorCode.CONTRACT_INVALID,
            field=safe_token(location, fallback="unrecognized"),
            problem=safe_token(str(first["type"]), fallback="invalid"),
        ) from err
