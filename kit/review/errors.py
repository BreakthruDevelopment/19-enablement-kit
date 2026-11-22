"""Refusals the review package raises before or after a run, as fixed reasons.

`kit/core/errors.py` is a foundation path and its `ErrorCode` set is closed to this slice, so the
reviewer carries its own small vocabulary. The rule is the foundation's: a message is a fixed
template for a fixed reason, never built from the diff, a criteria file or a model's answer, because
all three are somebody else's text and an error message is what ends up in a log line, a workflow
summary and a pull-request comment.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ReviewError", "ReviewReason"]


class ReviewReason(StrEnum):
    """Why a review did not start, or why its report was refused."""

    DIFF_EMPTY = "review.diff_empty"
    DIFF_TOO_LARGE = "review.diff_too_large"
    DIFF_TOO_MANY_FILES = "review.diff_too_many_files"
    DIFF_HAS_NUL = "review.diff_has_nul"
    CRITERIA_INVALID = "review.criteria_invalid"
    REPLAY_MISSING = "review.replay_missing"
    REPORT_REFUSED = "review.report_refused"


_MESSAGE = {
    ReviewReason.DIFF_EMPTY: "the diff is empty",
    ReviewReason.DIFF_TOO_LARGE: "the diff is larger than the review byte cap",
    ReviewReason.DIFF_TOO_MANY_FILES: "the diff changes more files than the review file cap",
    ReviewReason.DIFF_HAS_NUL: "the diff contains a NUL byte",
    ReviewReason.CRITERIA_INVALID: "a criteria file does not follow the criteria format",
    ReviewReason.REPLAY_MISSING: "no recorded replies exist for a pass",
    ReviewReason.REPORT_REFUSED: (
        "the assembled report would satisfy the factory's sign-off check, so it was not posted"
    ),
}


class ReviewError(Exception):
    """A refusal with a fixed reason. Nothing is interpolated into the message."""

    def __init__(self, reason: ReviewReason) -> None:
        self.reason = reason
        super().__init__(f"{reason.value}: {_MESSAGE[reason]}")
