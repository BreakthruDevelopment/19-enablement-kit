"""Structured errors, mapped onto app 17's `ErrorCategory` and `is_retryable`.

Every failure in the kit is one of these. A `KitError` carries a fixed `ErrorCode`, the app-17
`ErrorCategory` that code belongs to, and an `is_retryable` flag -- the same two pieces of
information app 18's gateway puts in its MCP error payload, so a caller on either side of the
boundary can tell a retry from a dead end.

**Messages are built from schema-derived names and fixed codes only.** A message assembled from
parsed input echoes that input back: a hostile path, a config key or a model's answer ends up in a
log line, a brief or a PR comment. So the message of every code is a fixed template, the only
values interpolated into it are the ones the code declares, and `_SAFE_VALUE` mechanically refuses
anything that looks like a path or carries whitespace. A caller that needs to say *which* file was
refused pairs the code with the path it asked for itself -- the error never carries it.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from agent_container.core.tool import ErrorCategory, ToolResult

__all__ = ["ErrorCode", "KitError", "safe_token"]


class ErrorCode(StrEnum):
    """Why something failed. One code per refusal the kit can make."""

    # The sandbox Proxy (`kit.core.sandbox`).
    OUTSIDE_ROOT = "sandbox.outside_root"
    DENIED_NAME = "sandbox.denied_name"
    MISSING = "sandbox.missing"
    NOT_A_FILE = "sandbox.not_a_file"
    NOT_A_DIRECTORY = "sandbox.not_a_directory"
    UNREADABLE = "sandbox.unreadable"
    WRITE_FORBIDDEN = "sandbox.write_forbidden"
    FILE_BYTE_CAP = "sandbox.file_byte_cap"
    RUN_BYTE_CAP = "sandbox.run_byte_cap"
    FILE_COUNT_CAP = "sandbox.file_count_cap"
    BAD_ROOT = "sandbox.bad_root"
    # Principals (`kit.core.principals`).
    FORBIDDEN = "principal.forbidden"
    NOT_OWNER = "principal.not_owner"
    BAD_SUBJECT = "principal.bad_subject"
    # Configuration and the frozen contract.
    CONFIG_UNREADABLE = "config.unreadable"
    CONFIG_INVALID = "config.invalid"
    CONTRACT_UNREADABLE = "contract.unreadable"
    CONTRACT_INVALID = "contract.invalid"


@dataclass(frozen=True, slots=True)
class _Spec:
    """What a code means: its app-17 category, whether a retry could help, and its wording."""

    category: ErrorCategory
    template: str
    fields: tuple[str, ...] = ()
    is_retryable: bool = False


# `is_retryable` follows app 17's rule: only a transient failure is worth trying again. Nothing the
# sandbox refuses is transient -- a cap, a deny-list name and a root are all the same next time --
# so every code here is terminal, and a caller that retries one is wrong rather than unlucky.
_SPEC: Mapping[ErrorCode, _Spec] = MappingProxyType(
    {
        ErrorCode.OUTSIDE_ROOT: _Spec(
            ErrorCategory.PERMISSION,
            "the resolved path is outside every allowed root",
        ),
        ErrorCode.DENIED_NAME: _Spec(
            ErrorCategory.PERMISSION,
            "a path segment matches the deny-list pattern {pattern}",
            ("pattern",),
        ),
        ErrorCode.MISSING: _Spec(ErrorCategory.VALIDATION, "no such path inside the roots"),
        ErrorCode.NOT_A_FILE: _Spec(ErrorCategory.VALIDATION, "the path is not a regular file"),
        ErrorCode.NOT_A_DIRECTORY: _Spec(ErrorCategory.VALIDATION, "the path is not a directory"),
        ErrorCode.UNREADABLE: _Spec(
            ErrorCategory.VALIDATION,
            "the file could not be read as {encoding} text",
            ("encoding",),
        ),
        ErrorCode.WRITE_FORBIDDEN: _Spec(
            ErrorCategory.PERMISSION,
            "this sandbox has no write root: writes go through the scaffold factory",
        ),
        ErrorCode.FILE_BYTE_CAP: _Spec(
            ErrorCategory.BUSINESS,
            "the file is larger than the {cap} cap of {limit} bytes",
            ("cap", "limit", "size"),
        ),
        ErrorCode.RUN_BYTE_CAP: _Spec(
            ErrorCategory.BUSINESS,
            "this read would pass the {cap} cap of {limit} bytes for the run",
            ("cap", "limit", "spent", "size"),
        ),
        ErrorCode.FILE_COUNT_CAP: _Spec(
            ErrorCategory.BUSINESS,
            "the run has already read its {cap} of {limit} files",
            ("cap", "limit"),
        ),
        ErrorCode.BAD_ROOT: _Spec(
            ErrorCategory.VALIDATION,
            "a sandbox root must be an existing directory",
        ),
        ErrorCode.FORBIDDEN: _Spec(
            ErrorCategory.PERMISSION,
            "principal {role} may not {capability}",
            ("role", "capability"),
        ),
        ErrorCode.NOT_OWNER: _Spec(
            ErrorCategory.PERMISSION,
            "principal {role} may {capability} only for what it owns",
            ("role", "capability"),
        ),
        ErrorCode.BAD_SUBJECT: _Spec(
            ErrorCategory.VALIDATION,
            "a principal subject is 1 to 64 letters, digits, dots, underscores, at-signs"
            " or hyphens",
        ),
        ErrorCode.CONFIG_UNREADABLE: _Spec(
            ErrorCategory.VALIDATION, "the config file is missing or is not TOML"
        ),
        ErrorCode.CONFIG_INVALID: _Spec(
            ErrorCategory.VALIDATION,
            "config field {field} is wrong: {problem}",
            ("field", "problem"),
        ),
        ErrorCode.CONTRACT_UNREADABLE: _Spec(
            ErrorCategory.VALIDATION, "the frozen contract is missing or is not JSON"
        ),
        ErrorCode.CONTRACT_INVALID: _Spec(
            ErrorCategory.VALIDATION,
            "frozen contract field {field} is wrong: {problem}",
            ("field", "problem"),
        ),
    }
)

# A detail value is a number or a short token from a vocabulary this repo owns: a cap name, a
# capability, a role, a deny-list pattern, a schema field path. No separator, no whitespace, no
# quote, nothing that could carry a path or a sentence of someone else's text.
_SAFE_VALUE = re.compile(r"\A[A-Za-z0-9_.*\[\]-]{1,64}\Z")


def safe_token(value: str, *, fallback: str) -> str:
    """`value` if it is a safe detail token, else `fallback`.

    Used where a name comes from a schema but is not guaranteed to be one of ours -- a pydantic
    error type, or a field path an input file invented through `extra="forbid"`. Keeping the
    fallback here means a hostile key can never reach a message, and a detail that slipped through
    would be a programming error rather than a leak.
    """
    return value if _SAFE_VALUE.fullmatch(value) else fallback


def _check_detail(code: ErrorCode, detail: Mapping[str, object]) -> dict[str, int | str]:
    spec = _SPEC[code]
    if set(detail) != set(spec.fields):
        raise ValueError(f"{code} takes exactly the fields {spec.fields!r}")
    checked: dict[str, int | str] = {}
    for key, value in detail.items():
        if isinstance(value, bool) or not isinstance(value, int | str):
            raise ValueError(f"{code} detail {key!r} must be an int or a short token")
        if isinstance(value, str) and not _SAFE_VALUE.fullmatch(value):
            # Reached only by a programming mistake: it is the guard that keeps parsed input --
            # a path, a config key, a model's sentence -- out of a message that gets logged.
            raise ValueError(f"{code} detail {key!r} is not a safe token")
        checked[key] = value
    return checked


class KitError(Exception):
    """A refusal, with the app-17 category and retry flag that go with it.

    Construct it with the code's declared fields and nothing else::

        raise KitError(ErrorCode.FILE_BYTE_CAP, cap="max_file_bytes", limit=1024, size=4096)
    """

    def __init__(self, code: ErrorCode, **detail: int | str) -> None:
        spec = _SPEC[code]
        checked = _check_detail(code, detail)
        self.code = code
        self.category = spec.category
        self.is_retryable = spec.is_retryable
        self.detail: Mapping[str, int | str] = MappingProxyType(checked)
        super().__init__(f"{code.value}: {spec.template.format(**checked)}")

    @property
    def message(self) -> str:
        return str(self)

    def as_dict(self) -> dict[str, object]:
        """The shape a log line or an MCP error payload carries."""
        return {
            "code": self.code.value,
            "error_category": self.category.value,
            "is_retryable": self.is_retryable,
            "message": self.message,
            "detail": dict(self.detail),
        }

    def as_tool_result(self) -> ToolResult:
        """The same refusal as an app-17 tool result, so the loop can hand it to a model."""
        return ToolResult.error(self.category, self.message, retryable=self.is_retryable)
