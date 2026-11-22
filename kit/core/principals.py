"""The three principals and `assert_can`: who the kit acts for, and what each may do.

A command, a workflow run and an MCP session each act as exactly one principal. There are no web
sessions in this repo, so this module is the whole of its authorization:

| Principal  | Who                                         |
| ---------- | ------------------------------------------- |
| `engineer` | a client developer at their own machine     |
| `ci`       | the headless reviewer in GitHub Actions     |
| `lead`     | the engineer rolling the kit out            |

There is one capability per command in the spec's command table, declared here even where the
command itself arrives in a later slice: `kit/core/` is a foundation path, so a later slice needing
a capability would otherwise have to stop and ask for a foundation change.

`ci` is deliberately the weakest: it runs unattended on contributor-supplied content, so it may
read the checkout and post its one report, and nothing else. It holds no credential but the
model's, cannot write the working tree and -- the control that matters most in this repo -- cannot
change a label, because `security-sensitive` is what makes a Codex review required and the token
that posts a review can also set labels.

Three capabilities are declared and granted to nobody (`NEVER_GRANTED`). They are the actions the
threat model says `ci` must not have; naming them makes "cannot" a line of code with a test on it
rather than a sentence in a document.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from kit.core.errors import ErrorCode, KitError

__all__ = [
    "NEVER_GRANTED",
    "OWNER_SCOPED",
    "Capability",
    "Principal",
    "Role",
    "assert_can",
]


class Role(StrEnum):
    """The three principals. A run acts as exactly one."""

    ENGINEER = "engineer"
    CI = "ci"
    LEAD = "lead"


class Capability(StrEnum):
    """One thing a principal may or may not do. Checked with `assert_can`, never inferred."""

    READ_FILES = "read_files"  # read through the sandbox Proxy
    RUN_SCOUT = "run_scout"  # explore a codebase and write a brief
    RUN_REVIEW = "run_review"  # the review passes over a diff
    RUN_PLAN = "run_plan"  # `kit plan`: the same task planned first versus executed directly
    POST_REVIEW = "post_review"  # post the one report on a pull request
    CALL_GATEWAY = "call_gateway"  # one read call through the MCP client
    MANAGE_OWN_SESSIONS = "manage_own_sessions"  # list, resume, fork -- own sessions only
    WRITE_TARGET = "write_target"  # `kit new`: the only write path in the kit
    CHANGE_LABELS = "change_labels"  # never granted: see the module docstring
    MERGE = "merge"  # never granted
    RESOLVE_THREADS = "resolve_threads"  # never granted


# Capabilities that are checked against an owner as well as a role. `assert_can` refuses one of
# these outright when it is asked without an owner, so a caller cannot get a session capability by
# forgetting the argument.
OWNER_SCOPED: frozenset[Capability] = frozenset({Capability.MANAGE_OWN_SESSIONS})

# Declared so the refusal is testable, granted to no role.
NEVER_GRANTED: frozenset[Capability] = frozenset(
    {Capability.CHANGE_LABELS, Capability.MERGE, Capability.RESOLVE_THREADS}
)

_ENGINEER: frozenset[Capability] = frozenset(
    {
        Capability.READ_FILES,
        Capability.RUN_SCOUT,
        Capability.RUN_REVIEW,
        Capability.RUN_PLAN,
        Capability.CALL_GATEWAY,
        Capability.MANAGE_OWN_SESSIONS,
    }
)

_GRANTS: Mapping[Role, frozenset[Capability]] = MappingProxyType(
    {
        Role.ENGINEER: _ENGINEER,
        # Read the checkout, run the passes, post at most one review. No scout, no sessions, no
        # write, no gateway: nothing unattended CI has a reason to reach.
        Role.CI: frozenset({Capability.READ_FILES, Capability.RUN_REVIEW, Capability.POST_REVIEW}),
        # "Additionally run `kit new`": everything the engineer may do, plus the one write path.
        Role.LEAD: _ENGINEER | {Capability.WRITE_TARGET},
    }
)

# A subject names the actor for logs and for session ownership. Kept to a short token so it can
# never carry a path or a sentence into a log line or an error message.
_SUBJECT = re.compile(r"\A[A-Za-z0-9_.@-]{1,64}\Z")


@dataclass(frozen=True, slots=True)
class Principal:
    """Who a run acts for: a role and the subject that owns the run's own sessions."""

    role: Role
    subject: str

    def __post_init__(self) -> None:
        if not _SUBJECT.fullmatch(self.subject):
            raise KitError(ErrorCode.BAD_SUBJECT)

    @classmethod
    def engineer(cls, subject: str) -> Principal:
        return cls(Role.ENGINEER, subject)

    @classmethod
    def ci(cls, subject: str = "github-actions") -> Principal:
        return cls(Role.CI, subject)

    @classmethod
    def lead(cls, subject: str) -> Principal:
        return cls(Role.LEAD, subject)

    @property
    def capabilities(self) -> frozenset[Capability]:
        return _GRANTS[self.role]

    def can(self, capability: Capability, *, owner: str | None = None) -> bool:
        """Whether this principal holds `capability`, for `owner`'s resource if one is named."""
        if capability not in self.capabilities:
            return False
        if capability in OWNER_SCOPED:
            return owner is not None and owner == self.subject
        return True


def assert_can(principal: Principal, capability: Capability, *, owner: str | None = None) -> None:
    """Raise a `permission` `KitError` unless `principal` may do `capability`.

    `owner` is required for an owner-scoped capability and ignored for the rest. The two refusals
    are distinct codes on purpose: `principal.forbidden` means the role never has it,
    `principal.not_owner` means the role has it but not here.
    """
    if capability not in principal.capabilities:
        raise KitError(ErrorCode.FORBIDDEN, role=principal.role.value, capability=capability.value)
    if capability in OWNER_SCOPED and (owner is None or owner != principal.subject):
        raise KitError(ErrorCode.NOT_OWNER, role=principal.role.value, capability=capability.value)
