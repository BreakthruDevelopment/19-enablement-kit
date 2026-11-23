"""Refusals the scout raises, as fixed reasons.

`kit/core/errors.py` is a foundation path and its `ErrorCode` set is closed to this slice, so the
scout carries its own small vocabulary, as `kit.review.errors` does. The rule is the foundation's:
a message is a fixed template for a fixed reason and is never built from a path, a file's content
or a model's answer. All three are somebody else's text, and an error message is what ends up in a
log line and a terminal.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["ScoutError", "ScoutReason"]


class ScoutReason(StrEnum):
    """Why a scout run did not produce a brief."""

    REPLAY_MISSING = "scout.replay_missing"
    NOTHING_READ = "scout.nothing_read"
    PROVIDER_ERROR = "scout.provider_error"
    BUDGET_EXHAUSTED = "scout.budget_exhausted"
    UNUSABLE_STOP_REASON = "scout.unusable_stop_reason"
    REPLY_NOT_PARSEABLE = "scout.reply_not_parseable"
    BRIEF_REFUSED = "scout.brief_refused"


_MESSAGE = {
    ScoutReason.REPLAY_MISSING: "no recorded reply exists for the scout",
    ScoutReason.NOTHING_READ: "the sandbox served no file, so there is nothing to brief",
    ScoutReason.PROVIDER_ERROR: "the model provider returned no reply",
    ScoutReason.BUDGET_EXHAUSTED: "the run budget was spent before the model call",
    ScoutReason.UNUSABLE_STOP_REASON: "the model's reply did not end cleanly",
    ScoutReason.REPLY_NOT_PARSEABLE: "the model's reply is not a valid scout brief",
    ScoutReason.BRIEF_REFUSED: "the brief held a secret-shaped string, so it was withheld",
}


class ScoutError(Exception):
    """A refusal with a fixed reason. Nothing is interpolated into the message."""

    def __init__(self, reason: ScoutReason) -> None:
        self.reason = reason
        super().__init__(f"{reason.value}: {_MESSAGE[reason]}")
