"""Refusals the scaffold factory can make.

A principal who may not write is not one of these. That refusal is `assert_can`'s
`principal.forbidden`, raised before this module is asked to look at a target. The codes
here are the target directory and the committed templates. Adding them to `kit.core.errors`
would mean editing a foundation path this slice does not own.

Messages are fixed. A path the caller passed is never interpolated, and a filesystem
error is raised `from None`: an `OSError` would otherwise carry the path in its own
message.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from agent_container.core.tool import ErrorCategory

from kit.core.errors import safe_token

__all__ = ["ScaffoldCode", "ScaffoldError"]


class ScaffoldCode(StrEnum):
    """Why `kit new` refused. One code per refusal that is not a principal check."""

    UNKNOWN_KIND = "scaffold.unknown_kind"
    BAD_INVOCATION = "scaffold.bad_invocation"
    TARGET_NOT_EMPTY = "scaffold.target_not_empty"
    TARGET_UNUSABLE = "scaffold.target_unusable"
    PATH_OCCUPIED = "scaffold.path_occupied"
    UNREADABLE = "scaffold.unreadable"
    THROUGH_LINK = "scaffold.through_link"
    OUTSIDE_TARGET = "scaffold.outside_target"
    DENIED_NAME = "scaffold.denied_name"
    BAD_TEMPLATE = "scaffold.bad_template"
    WRITE_FAILED = "scaffold.write_failed"


class _Spec:
    """What a code means: its category, its wording, and the detail fields it may carry."""

    def __init__(
        self, category: ErrorCategory, template: str, fields: tuple[str, ...] = ()
    ) -> None:
        self.category = category
        self.template = template
        self.fields = fields


_SPEC: dict[ScaffoldCode, _Spec] = {
    ScaffoldCode.UNKNOWN_KIND: _Spec(
        ErrorCategory.VALIDATION, "the scaffold kind is not one of the three"
    ),
    ScaffoldCode.BAD_INVOCATION: _Spec(
        ErrorCategory.VALIDATION, "kit new was given an argument it cannot accept"
    ),
    ScaffoldCode.TARGET_NOT_EMPTY: _Spec(
        ErrorCategory.VALIDATION,
        "the target is not empty; pass --force to write into it",
    ),
    ScaffoldCode.TARGET_UNUSABLE: _Spec(
        ErrorCategory.VALIDATION, "the target is not a directory the scaffold can create"
    ),
    ScaffoldCode.PATH_OCCUPIED: _Spec(
        ErrorCategory.VALIDATION,
        "a path the scaffold writes is already a directory, or a directory is already a file",
    ),
    ScaffoldCode.UNREADABLE: _Spec(ErrorCategory.INTERNAL, "the target could not be examined"),
    ScaffoldCode.THROUGH_LINK: _Spec(
        ErrorCategory.PERMISSION, "the scaffold refuses to write through a symbolic link"
    ),
    ScaffoldCode.OUTSIDE_TARGET: _Spec(
        ErrorCategory.PERMISSION, "the resolved path is outside the target root"
    ),
    ScaffoldCode.DENIED_NAME: _Spec(
        ErrorCategory.PERMISSION,
        "a path segment matches the deny-list pattern {pattern}",
        ("pattern",),
    ),
    ScaffoldCode.BAD_TEMPLATE: _Spec(
        ErrorCategory.INTERNAL, "a committed scaffold template is not usable"
    ),
    ScaffoldCode.WRITE_FAILED: _Spec(ErrorCategory.INTERNAL, "the scaffold could not be written"),
}


class ScaffoldError(Exception):
    """A scaffold refusal. Construct it with the code's declared fields and nothing else."""

    def __init__(self, code: ScaffoldCode, **detail: str) -> None:
        spec = _SPEC[code]
        checked = _check_detail(code, detail)
        self.code = code
        self.category = spec.category
        self.is_retryable = False
        self.detail: Mapping[str, str] = MappingProxyType(checked)
        super().__init__(f"{code.value}: {spec.template.format(**checked)}")

    @property
    def message(self) -> str:
        return str(self)


def _check_detail(code: ScaffoldCode, detail: Mapping[str, str]) -> dict[str, str]:
    spec = _SPEC[code]
    if set(detail) != set(spec.fields):
        raise ValueError(f"{code} takes exactly the fields {spec.fields!r}")
    checked: dict[str, str] = {}
    for key, value in detail.items():
        # `safe_token` is the foundation's rule for what may appear in a message. A
        # value that fails it is dropped rather than quoted: the caller gets the key.
        if not isinstance(value, str) or safe_token(value, fallback="invalid") != value:
            raise ValueError(f"{code} detail {key!r} is not a safe token")
        checked[key] = value
    return checked
