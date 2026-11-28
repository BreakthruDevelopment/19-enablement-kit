"""The recordings `kit plan` replays, and the rules that make them a plan-mode comparison.

Two files, both in one replay directory:

* `plan.json` -- one task, its system prompt and fence nonce, the **shared prefix** both arms
  start from, and the turns of each arm after the fork: `planned` and `direct`.
* `refine.json` -- the second attempt of the refinement demo: the opening it was recorded with,
  and its turns. Only `--refine` reads it.

A turn is the session store's own `Turn`, so a recording cannot hold anything a session file
could not. The opening fields (`user_message`, `system`, `fence_nonce`) are not allowed on a
recorded turn: code puts the task and the prompt on the first turn of the prefix, so the opening
a session replays is the one this run was asked for.

**The rules are checked in code, before anything is stored.** A recording is somebody's claim
about what a model did. What makes it a plan-mode comparison is checked here, not trusted:

* every tool a turn calls is in a fixed vocabulary -- three read tools, `exit_plan_mode`, and
  `propose_patch`, which stages a diff and writes nothing;
* the prefix is read-only and ends on a tool round, because both arms continue from it;
* the planned arm presents **exactly one** plan, through `exit_plan_mode`, with an approved
  (non-error) result, and calls no write tool before it -- which is what plan mode means;
* the direct arm presents no plan;
* both arms end on a stop reason that finishes a run, and each stages at least one patch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_container.core.fence import check_nonce
from agent_container.core.loop import MAX_USER_MESSAGE_CHARS
from agent_container.core.messages import StopReason
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from kit.core.errors import ErrorCode, KitError
from kit.core.sandbox import Sandbox
from kit.plan.errors import PlanError, PlanReason
from kit.review.errors import ReviewError
from kit.review.inputs import check_diff
from kit.session.models import Turn

__all__ = [
    "EXIT_PLAN_MODE",
    "MAX_PLAN_CHARS",
    "PLAN_FILE",
    "PROPOSE_PATCH",
    "READ_TOOLS",
    "REFINE_FILE",
    "PatchStats",
    "PlanRecording",
    "RefineRecording",
    "check_attempt_rules",
    "check_plan_rules",
    "load_plan_recording",
    "load_refine_recording",
    "patch_stats",
    "plan_text",
    "staged_patches",
]

PLAN_FILE: Final = "plan.json"
REFINE_FILE: Final = "refine.json"

# The fixed vocabulary. Read tools look; `exit_plan_mode` presents a plan and asks for approval,
# the way Claude Code's plan mode ends; `propose_patch` stages a diff and writes nothing.
READ_TOOLS: Final = frozenset({"read_file", "grep", "list_dir"})
EXIT_PLAN_MODE: Final = "exit_plan_mode"
PROPOSE_PATCH: Final = "propose_patch"
_VOCABULARY: Final = READ_TOOLS | {EXIT_PLAN_MODE, PROPOSE_PATCH}

MAX_PLAN_CHARS: Final = 4_000
# Both files together are a few kilobytes. This is the sandbox's own default file cap, restated
# here so the limit a recording is read under is named where it is used, not inherited silently.
MAX_RECORDING_BYTES: Final = 512 * 1024
_MAX_TURNS: Final = 24

_STRICT = ConfigDict(extra="forbid", frozen=True)


def _no_opening(turns: tuple[Turn, ...]) -> tuple[Turn, ...]:
    for turn in turns:
        if turn.user_message is not None or turn.system is not None or turn.fence_nonce is not None:
            raise ValueError("a recorded turn does not carry the opening")
    return turns


class PlanRecording(BaseModel):
    """`plan.json`. `description` is for a reader and is not used."""

    model_config = _STRICT

    description: str = Field(default="", max_length=2_000)
    task: str = Field(min_length=1, max_length=MAX_USER_MESSAGE_CHARS)
    system: str = Field(min_length=1, max_length=20_000)
    fence_nonce: str
    prefix: tuple[Turn, ...] = Field(min_length=1, max_length=_MAX_TURNS)
    planned: tuple[Turn, ...] = Field(min_length=1, max_length=_MAX_TURNS)
    direct: tuple[Turn, ...] = Field(min_length=1, max_length=_MAX_TURNS)

    @field_validator("fence_nonce")
    @classmethod
    def _nonce(cls, value: str) -> str:
        check_nonce(value)
        return value

    @field_validator("task", "system")
    @classmethod
    def _opening_text(cls, value: str) -> str:
        # `Turn` screens its own text fields; these two come from the recording and are copied
        # into the opening of a stored session, so the boundary is here. Refused at load time as
        # `plan.recording_invalid`, a fixed code, so the recording's own bytes never reach a
        # message -- letting pydantic's error escape instead would put them there.
        return _no_nul(value)

    @field_validator("prefix", "planned", "direct")
    @classmethod
    def _turns(cls, value: tuple[Turn, ...]) -> tuple[Turn, ...]:
        return _no_opening(value)


class RefineRecording(BaseModel):
    """`refine.json`: the second attempt, recorded from the opening code builds for it."""

    model_config = _STRICT

    description: str = Field(default="", max_length=2_000)
    system: str = Field(min_length=1, max_length=20_000)
    fence_nonce: str
    user_message: str = Field(min_length=1, max_length=MAX_USER_MESSAGE_CHARS)
    attempt: tuple[Turn, ...] = Field(min_length=1, max_length=_MAX_TURNS)

    @field_validator("fence_nonce")
    @classmethod
    def _nonce(cls, value: str) -> str:
        check_nonce(value)
        return value

    @field_validator("system", "user_message")
    @classmethod
    def _opening_text(cls, value: str) -> str:
        return _no_nul(value)

    @field_validator("attempt")
    @classmethod
    def _turns(cls, value: tuple[Turn, ...]) -> tuple[Turn, ...]:
        return _no_opening(value)


def _read(sandbox: Sandbox, path: Path, missing: PlanReason) -> object:
    try:
        raw = sandbox.read_text(path)
    except KitError as refusal:
        # A file that is not there is "no recording"; a refusal for any other reason (outside the
        # roots, a denied name, over the cap) is the sandbox's own, and is raised as it is.
        if refusal.code is ErrorCode.MISSING:
            raise PlanError(missing) from None
        raise
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        raise PlanError(PlanReason.RECORDING_INVALID) from None


def load_plan_recording(sandbox: Sandbox, directory: Path) -> PlanRecording:
    """Read and validate `plan.json` through the sandbox."""
    data = _read(sandbox, directory / PLAN_FILE, PlanReason.RECORDING_MISSING)
    try:
        return PlanRecording.model_validate(data)
    except ValidationError:
        raise PlanError(PlanReason.RECORDING_INVALID) from None


def load_refine_recording(sandbox: Sandbox, directory: Path) -> RefineRecording:
    """Read and validate `refine.json` through the sandbox."""
    data = _read(sandbox, directory / REFINE_FILE, PlanReason.REFINE_RECORDING_MISSING)
    try:
        return RefineRecording.model_validate(data)
    except ValidationError:
        raise PlanError(PlanReason.RECORDING_INVALID) from None


def _no_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("a text field cannot contain a NUL")
    return value


def _names(turn: Turn) -> list[str]:
    return [use.name for use in turn.tool_uses]


def _check_vocabulary(turns: Sequence[Turn]) -> None:
    for turn in turns:
        if any(name not in _VOCABULARY for name in _names(turn)):
            raise PlanError(PlanReason.UNKNOWN_TOOL)


def _check_finished(turns: Sequence[Turn]) -> None:
    if turns[-1].stop_reason == StopReason.TOOL_USE:
        raise PlanError(PlanReason.ARM_UNFINISHED)


def _result_for(turn: Turn, tool_use_id: str) -> bool | None:
    """Whether the recorded result for a call was an error, or None if none is recorded."""
    for result in turn.tool_results:
        if result.tool_use_id == tool_use_id:
            return result.is_error
    return None


def check_plan_rules(recording: PlanRecording) -> None:
    """Raise `PlanError` unless the recording is the comparison it claims to be."""
    for turns in (recording.prefix, recording.planned, recording.direct):
        _check_vocabulary(turns)

    prefix = recording.prefix
    if prefix[-1].stop_reason != StopReason.TOOL_USE or any(
        name not in READ_TOOLS for turn in prefix for name in _names(turn)
    ):
        raise PlanError(PlanReason.BAD_PREFIX)

    # The planned arm: read tools only, until one approved plan; then anything in the vocabulary.
    plans = 0
    for turn in recording.planned:
        for use in turn.tool_uses:
            if use.name == EXIT_PLAN_MODE:
                plans += 1
                text = use.input.get("plan")
                if (
                    plans > 1
                    or len(turn.tool_uses) != 1
                    or not isinstance(text, str)
                    or not text.strip()
                    or len(text) > MAX_PLAN_CHARS
                    or _result_for(turn, use.id) is not False
                ):
                    raise PlanError(PlanReason.PLAN_MODE_VIOLATED)
            elif plans == 0 and use.name not in READ_TOOLS:
                raise PlanError(PlanReason.PLAN_MODE_VIOLATED)
    if plans != 1:
        raise PlanError(PlanReason.PLAN_MODE_VIOLATED)

    if any(EXIT_PLAN_MODE in _names(turn) for turn in recording.direct):
        raise PlanError(PlanReason.DIRECT_HAS_PLAN)

    for arm in (recording.planned, recording.direct):
        _check_finished(arm)
        staged_patches(arm)  # at least one, each a usable diff


def check_attempt_rules(turns: Sequence[Turn]) -> None:
    """The second attempt of the refinement demo: no plan, a finished run, a staged patch."""
    _check_vocabulary(turns)
    if any(EXIT_PLAN_MODE in _names(turn) for turn in turns):
        raise PlanError(PlanReason.DIRECT_HAS_PLAN)
    _check_finished(turns)
    staged_patches(turns)


def plan_text(turns: Sequence[Turn]) -> str:
    """The one plan the planned arm presented. Call after `check_plan_rules`."""
    for turn in turns:
        for use in turn.tool_uses:
            text = use.input.get("plan")
            if use.name == EXIT_PLAN_MODE and isinstance(text, str):
                return text
    raise PlanError(PlanReason.PLAN_MODE_VIOLATED)


@dataclass(frozen=True, slots=True)
class PatchStats:
    files: int
    added: int
    removed: int

    def as_dict(self) -> dict[str, int]:
        return {"added": self.added, "files": self.files, "removed": self.removed}


def patch_stats(diff: str) -> PatchStats:
    files = added = removed = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            files += 1
        elif line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return PatchStats(files=files, added=added, removed=removed)


def staged_patches(turns: Sequence[Turn]) -> tuple[str, ...]:
    """Every diff the turns staged with `propose_patch` and whose recorded result was not an error.

    Raises `PlanError` if there is none, or if any staged diff is not a usable one (empty, over the
    review's caps, a NUL). The last one is what the arm produced.
    """
    found: list[str] = []
    for turn in turns:
        for use in turn.tool_uses:
            if use.name != PROPOSE_PATCH:
                continue
            diff = use.input.get("diff")
            if not isinstance(diff, str):
                raise PlanError(PlanReason.BAD_PATCH)
            try:
                check_diff(diff)
            except ReviewError:
                raise PlanError(PlanReason.BAD_PATCH) from None
            if not diff.startswith("diff --git ") and not diff.startswith("--- "):
                raise PlanError(PlanReason.BAD_PATCH)
            if _result_for(turn, use.id) is False:
                found.append(diff)
    if not found:
        raise PlanError(PlanReason.NO_PATCH)
    return tuple(found)
