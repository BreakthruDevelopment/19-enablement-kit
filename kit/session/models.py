"""The session file: `sessions/<id>.json`, validated at the boundary.

The columns are the spec's and nothing else: `id`, `parent_id`, `principal`, `created_at`,
`turns`, `budget_spent`. A turn is one recorded model reply. The first turn also carries the
opening the loop needs to replay it (`user_message`, `system`, `fence_nonce`); later turns do not,
so a fork of any prefix still starts from the same opening. `budget_spent` is derived from the
turns and checked on read, so a file cannot claim a cost the turns do not add up to.

Turns are append-only. Nothing in this package edits a turn that has been stored, and a fork
copies them into a new file rather than changing the parent.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Final

from agent_container.core.errors import UnrecognizedStopReason
from agent_container.core.fence import MAX_TOOL_OUTPUT_CHARS, check_nonce
from agent_container.core.loop import MAX_USER_MESSAGE_CHARS
from agent_container.core.messages import StopReason
from agent_container.core.tool import TOOL_NAME_PATTERN, ErrorCategory
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
    model_validator,
)

from kit.session.errors import SessionError, SessionReason

__all__ = [
    "MAX_SESSION_BYTES",
    "BudgetSpent",
    "Session",
    "ToolResultRecord",
    "ToolUseRecord",
    "Turn",
    "UsageRecord",
    "budget_of",
    "ensure_turns",
    "parse_turn",
    "session_id_ok",
]

# One session file. A larger file is refused before it is parsed.
MAX_SESSION_BYTES: Final = 8 * 1024 * 1024

_MAX_SYSTEM_CHARS: Final = 100_000
_MAX_TEXT_CHARS: Final = 200_000
_MAX_TOOL_INPUT_CHARS: Final = 64 * 1024
_MAX_TOOLS: Final = 32

# Generated ids are `secrets.token_hex(16)`. Lower case only: the Mac's filesystem does not
# distinguish case, and two ids that differed only by case would be one file.
_ID = re.compile(r"\A[a-f0-9]{32}\Z")
_TURN_NAME = re.compile(r"\A[A-Za-z0-9_.@-]{1,64}\Z")

_STRICT = ConfigDict(extra="forbid", frozen=True)


def _no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("a text field cannot contain a NUL")
    return value


class UsageRecord(BaseModel):
    """Tokens one recorded reply reported. Both counts are what the model billed for that call."""

    model_config = _STRICT

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)


class ToolUseRecord(BaseModel):
    """One tool call the model asked for, in the shape app 17 records it."""

    model_config = _STRICT

    id: str = Field(min_length=1, max_length=200)
    name: str
    input: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if re.fullmatch(r"[^\x00-\x1f\x7f]{1,200}", value) is None:
            raise ValueError("a tool-use id is not a usable token")
        return value

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if TOOL_NAME_PATTERN.fullmatch(value) is None:
            raise ValueError("a tool name is not an identifier")
        return value

    @field_validator("input")
    @classmethod
    def _input(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if len(json.dumps(value)) > _MAX_TOOL_INPUT_CHARS:
            raise ValueError("a tool input is too large")
        return value


class ToolResultRecord(BaseModel):
    """The result recorded for one tool call. Resume returns it; the tool is not run again."""

    model_config = _STRICT

    tool_use_id: str = Field(min_length=1, max_length=200)
    content: str = Field(default="", max_length=MAX_TOOL_OUTPUT_CHARS)
    is_error: bool = False
    error_category: ErrorCategory | None = None
    is_retryable: bool = False

    @field_validator("tool_use_id")
    @classmethod
    def _id(cls, value: str) -> str:
        if re.fullmatch(r"[^\x00-\x1f\x7f]{1,200}", value) is None:
            raise ValueError("a tool-use id is not a usable token")
        return value

    @field_validator("content")
    @classmethod
    def _content(cls, value: str) -> str:
        return _no_nul(value)

    @model_validator(mode="after")
    def _consistent(self) -> ToolResultRecord:
        if self.is_error and self.error_category is None:
            raise ValueError("an error result needs a category")
        if not self.is_error and (self.error_category is not None or self.is_retryable):
            raise ValueError("only an error result carries a category")
        return self


class Turn(BaseModel):
    """One recorded model reply.

    `user_message`, `system` and `fence_nonce` are set on the first turn of a session and null on
    every later turn. `system` is the prompt handed to the loop, not the one the loop sends: the
    loop appends its own fence notice.
    """

    model_config = _STRICT

    name: str
    stop_reason: str
    text: str = Field(default="", max_length=_MAX_TEXT_CHARS)
    tool_uses: tuple[ToolUseRecord, ...] = Field(default=(), max_length=_MAX_TOOLS)
    tool_results: tuple[ToolResultRecord, ...] = Field(default=(), max_length=_MAX_TOOLS)
    usage: UsageRecord = Field(default_factory=UsageRecord)
    user_message: str | None = Field(default=None, max_length=MAX_USER_MESSAGE_CHARS)
    system: str | None = Field(default=None, max_length=_MAX_SYSTEM_CHARS)
    fence_nonce: str | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if _TURN_NAME.fullmatch(value) is None:
            raise ValueError("a turn name is not an identifier")
        return value

    @field_validator("stop_reason")
    @classmethod
    def _stop(cls, value: str) -> str:
        try:
            StopReason.parse(value)
        except UnrecognizedStopReason:
            raise ValueError("unrecognized stop reason") from None
        return value

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        return _no_nul(value)

    @field_validator("user_message", "system")
    @classmethod
    def _opening_text(cls, value: str | None) -> str | None:
        if value is not None:
            _no_nul(value)
        return value


class BudgetSpent(BaseModel):
    """What the recorded replies cost. Derived from the turns; never supplied by the caller."""

    model_config = _STRICT

    turns: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class Session(BaseModel):
    """One `sessions/<id>.json` document."""

    model_config = _STRICT

    id: str
    parent_id: str | None = None
    principal: str
    created_at: datetime
    turns: tuple[Turn, ...]
    budget_spent: BudgetSpent

    @field_validator("id", "parent_id")
    @classmethod
    def _ids(cls, value: str | None) -> str | None:
        if value is not None and _ID.fullmatch(value) is None:
            raise ValueError("a session id is not an identifier")
        return value

    @field_validator("created_at")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at needs a timezone")
        return value.astimezone(UTC)


def budget_of(turns: Sequence[Turn]) -> BudgetSpent:
    """The budget the turns themselves account for."""
    return BudgetSpent(
        turns=len(turns),
        input_tokens=sum(turn.usage.input_tokens for turn in turns),
        output_tokens=sum(turn.usage.output_tokens for turn in turns),
    )


def parse_turn(value: Turn | Mapping[str, object]) -> Turn:
    """Validate a turn at the boundary. A bad turn is `session.turn_rejected`, never a trace."""
    try:
        if isinstance(value, Turn):
            return value
        return Turn.model_validate(value)
    except ValidationError:
        raise SessionError(SessionReason.TURN_REJECTED) from None


def ensure_turns(turns: Sequence[Turn], *, on_error: SessionReason) -> None:
    """The rules that relate one turn to the others.

    A stop reason other than `tool_use` ends a run, so it can only be the last turn. A `tool_use`
    turn records a result for every call, because resume does not run the tool. Any other stop
    reason records none: an unanswered call is answered by app 17's loop with its synthetic
    result, and storing one here would be a second source of truth.
    """
    if not turns:
        return
    names: set[str] = set()
    seen_ids: set[str] = set()
    last = len(turns) - 1
    for index, turn in enumerate(turns):
        if turn.name in names:
            raise SessionError(on_error)
        names.add(turn.name)
        if index == 0:
            user = turn.user_message
            if user is None or not user.strip() or len(user) > MAX_USER_MESSAGE_CHARS:
                raise SessionError(on_error)
            if turn.system is None or len(turn.system) > _MAX_SYSTEM_CHARS:
                raise SessionError(on_error)
            if turn.fence_nonce is None:
                raise SessionError(on_error)
            try:
                check_nonce(turn.fence_nonce)
            except ValueError:
                raise SessionError(on_error) from None
        elif (
            turn.user_message is not None or turn.system is not None or turn.fence_nonce is not None
        ):
            raise SessionError(on_error)
        if index != last and turn.stop_reason != StopReason.TOOL_USE:
            raise SessionError(on_error)
        _check_pairing(turn, seen_ids, on_error)


def _check_pairing(turn: Turn, seen_ids: set[str], on_error: SessionReason) -> None:
    use_ids = [use.id for use in turn.tool_uses]
    if len(use_ids) != len(set(use_ids)) or any(use_id in seen_ids for use_id in use_ids):
        raise SessionError(on_error)
    result_ids = [result.tool_use_id for result in turn.tool_results]
    if turn.stop_reason == StopReason.TOOL_USE:
        if not use_ids or sorted(result_ids) != sorted(use_ids) or len(result_ids) != len(use_ids):
            raise SessionError(on_error)
    elif result_ids:
        raise SessionError(on_error)
    seen_ids.update(use_ids)


def session_id_ok(value: str) -> bool:
    """Whether `value` can be a session id. Filenames are built only from ids that pass."""
    return _ID.fullmatch(value) is not None
