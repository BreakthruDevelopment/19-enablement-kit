"""Refusals the MCP client can make.

`kit/core/errors.py` is a foundation path, so this slice keeps its own small vocabulary, the
same way the scaffold and the reviewer do. A message is a fixed template. A tool argument, a
gateway payload and a command path are all somebody else's text, and an error message is what
ends up on stderr.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from agent_container.core.tool import ErrorCategory

from kit.core.errors import safe_token

__all__ = ["ErpCode", "ErpError"]


class ErpCode(StrEnum):
    """Why a gateway call did not return a rendered result."""

    UNKNOWN_TOOL = "erp.unknown_tool"
    WRITE_REFUSED = "erp.write_refused"
    BAD_ARGUMENTS = "erp.bad_arguments"
    REPLAY_MISSING = "erp.replay_missing"
    REPLAY_INVALID = "erp.replay_invalid"
    PROTOCOL = "erp.protocol"
    GATEWAY_UNAVAILABLE = "erp.gateway_unavailable"
    GATEWAY_TIMEOUT = "erp.gateway_timeout"
    CONTRACT_DRIFT = "erp.contract_drift"


class _Spec:
    """What a code means: its category, whether a retry could help, and its wording."""

    def __init__(
        self,
        category: ErrorCategory,
        template: str,
        fields: tuple[str, ...] = (),
        *,
        is_retryable: bool = False,
    ) -> None:
        self.category = category
        self.template = template
        self.fields = fields
        self.is_retryable = is_retryable


# Only a timeout is transient: the gateway might answer a second attempt. The client still
# does not retry one. `is_retryable` says a caller may; it is not an instruction to loop.
_SPEC: dict[ErpCode, _Spec] = {
    ErpCode.UNKNOWN_TOOL: _Spec(ErrorCategory.VALIDATION, "the tool is not in the frozen contract"),
    ErpCode.WRITE_REFUSED: _Spec(
        ErrorCategory.PERMISSION,
        "app 19 calls only the read tools of the service principal",
    ),
    ErpCode.BAD_ARGUMENTS: _Spec(
        ErrorCategory.VALIDATION, "arguments are key=value pairs or one JSON object"
    ),
    ErpCode.REPLAY_MISSING: _Spec(
        ErrorCategory.VALIDATION,
        "no recorded reply for this call; pass --live to reach the gateway",
    ),
    ErpCode.REPLAY_INVALID: _Spec(ErrorCategory.INTERNAL, "the recorded transcript is not usable"),
    ErpCode.PROTOCOL: _Spec(
        ErrorCategory.INTERNAL, "the gateway's response was not a usable JSON-RPC result"
    ),
    ErpCode.GATEWAY_UNAVAILABLE: _Spec(
        ErrorCategory.VALIDATION, "the gateway command could not be started"
    ),
    ErpCode.GATEWAY_TIMEOUT: _Spec(
        ErrorCategory.TRANSIENT,
        "the gateway did not answer in time",
        is_retryable=True,
    ),
    ErpCode.CONTRACT_DRIFT: _Spec(
        ErrorCategory.BUSINESS,
        "the live gateway does not match the frozen contract ({part})",
        ("part",),
    ),
}


class ErpError(Exception):
    """A client refusal. Construct it with the code's declared fields and nothing else."""

    def __init__(self, code: ErpCode, **detail: str) -> None:
        spec = _SPEC[code]
        checked = _check_detail(code, detail)
        self.code = code
        self.category = spec.category
        self.is_retryable = spec.is_retryable
        self.detail: Mapping[str, str] = MappingProxyType(checked)
        super().__init__(f"{code.value}: {spec.template.format(**checked)}")

    @property
    def message(self) -> str:
        return str(self)


def _check_detail(code: ErpCode, detail: Mapping[str, str]) -> dict[str, str]:
    spec = _SPEC[code]
    if set(detail) != set(spec.fields):
        raise ValueError(f"{code} takes exactly the fields {spec.fields!r}")
    checked: dict[str, str] = {}
    for key, value in detail.items():
        if not isinstance(value, str) or safe_token(value, fallback="invalid") != value:
            raise ValueError(f"{code} detail {key!r} is not a safe token")
        checked[key] = value
    return checked
