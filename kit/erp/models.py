"""The two shapes the client hands back: a tool descriptor and one call's body.

Both are taken from a gateway payload or a recording. They are copied into frozen values
so a caller cannot edit the object the next check reads.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import cast

from pydantic import JsonValue

from kit.erp.errors import ErpCode, ErpError

__all__ = [
    "MAX_ARGUMENT_BYTES",
    "CallResult",
    "LiveTool",
    "canonical_arguments",
    "normalize_arguments",
]

# A tool argument is a page of ids, not a document. The same bound the gateway uses for one
# line is far larger; this one is the client's own, applied before anything is sent.
MAX_ARGUMENT_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class LiveTool:
    """One tool a gateway listed. `read_only` is the MCP `readOnlyHint`."""

    name: str
    read_only: bool
    description: str


@dataclass(frozen=True, slots=True)
class CallResult:
    """One tool result, as the gateway's structured content, not a rewritten sentence.

    `is_error` is the MCP flag. The body is the structured object beside it. A permission
    failure stays a permission failure: the category and `is_retryable` are the gateway's,
    and nothing here turns them into a success.
    """

    is_error: bool
    structured: Mapping[str, JsonValue]

    @property
    def error_category(self) -> str | None:
        if not self.is_error:
            return None
        value = self.structured.get("error_category")
        if isinstance(value, str):
            return value
        return None

    @property
    def is_retryable(self) -> bool:
        """The gateway's flag. False when the call succeeded or the field was not a boolean."""
        if not self.is_error:
            return False
        return self.structured.get("is_retryable") is True


def canonical_arguments(arguments: Mapping[str, JsonValue]) -> str:
    """One stable encoding of an argument object, for a replay lookup."""
    try:
        # `dict` so a read-only mapping encodes. JSON only walks a plain object.
        return json.dumps(
            dict(arguments),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        raise ErpError(ErpCode.BAD_ARGUMENTS) from None


def normalize_arguments(arguments: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    """A copy that is JSON and within the argument cap. Refuses anything that is not.

    The cap is on the canonical encoding, so key order cannot sneak a second copy past it.
    The returned mapping is read-only.
    """
    encoded = canonical_arguments(arguments)
    if len(encoded.encode("utf-8")) > MAX_ARGUMENT_BYTES:
        raise ErpError(ErpCode.BAD_ARGUMENTS)
    parsed = json.loads(encoded)
    if not isinstance(parsed, dict):
        raise ErpError(ErpCode.BAD_ARGUMENTS)
    return MappingProxyType(cast(dict[str, JsonValue], parsed))
