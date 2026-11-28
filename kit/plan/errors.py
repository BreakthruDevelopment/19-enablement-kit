"""Refusals `kit plan` makes, as fixed reasons.

`kit/core/errors.py` is a foundation path, so this slice adds its codes here, the way the session
and review packages do. A message is a fixed template: never built from the task, a turn name, a
tool input, a plan or a finding. Those are somebody else's text, and an error message is what ends
up on stderr.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["PlanError", "PlanReason"]


class PlanReason(StrEnum):
    """Why a plan run did not happen, or did not finish."""

    RECORDING_MISSING = "plan.recording_missing"
    RECORDING_INVALID = "plan.recording_invalid"
    NO_RECORDING_FOR_TASK = "plan.no_recording_for_task"
    UNKNOWN_TOOL = "plan.unknown_tool"
    BAD_PREFIX = "plan.bad_prefix"
    PLAN_MODE_VIOLATED = "plan.plan_mode_violated"
    DIRECT_HAS_PLAN = "plan.direct_has_plan"
    ARM_UNFINISHED = "plan.arm_unfinished"
    NO_PATCH = "plan.no_patch"
    BAD_PATCH = "plan.bad_patch"
    REFINE_RECORDING_MISSING = "plan.refine_recording_missing"
    REFINE_STALE = "plan.refine_stale"
    REFINE_TOO_LARGE = "plan.refine_too_large"
    REVIEW_INCOMPLETE = "plan.review_incomplete"


_MESSAGE = {
    PlanReason.RECORDING_MISSING: "no plan recording in the replay directory",
    PlanReason.RECORDING_INVALID: "the plan recording is not valid",
    PlanReason.NO_RECORDING_FOR_TASK: (
        "no recording for this task; only recorded replies are wired, so the task must be the "
        "recorded one"
    ),
    PlanReason.UNKNOWN_TOOL: "a recorded turn calls a tool outside the plan vocabulary",
    PlanReason.BAD_PREFIX: "the shared prefix must be read-only and end on a tool round",
    PlanReason.PLAN_MODE_VIOLATED: (
        "the planned arm must present exactly one approved plan before any write"
    ),
    PlanReason.DIRECT_HAS_PLAN: "the direct arm must not present a plan",
    PlanReason.ARM_UNFINISHED: "an arm must end on a stop reason that finishes the run",
    PlanReason.NO_PATCH: "the arm staged no patch",
    PlanReason.BAD_PATCH: "a staged patch is not a usable diff",
    PlanReason.REFINE_RECORDING_MISSING: "no refinement recording in the replay directory",
    PlanReason.REFINE_STALE: (
        "the recorded second attempt was not opened with the findings this run produced"
    ),
    PlanReason.REFINE_TOO_LARGE: "the findings do not fit in one opening message",
    PlanReason.REVIEW_INCOMPLETE: "a review pass got no usable response; nothing to compare",
}


class PlanError(Exception):
    """A refusal with a fixed reason. Nothing is interpolated into the message."""

    def __init__(self, reason: PlanReason) -> None:
        self.reason = reason
        super().__init__(f"{reason.value}: {_MESSAGE[reason]}")
