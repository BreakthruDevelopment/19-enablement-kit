"""Refusals the session store makes, as fixed reasons.

`kit/core/errors.py` is a foundation path, so this slice does not add codes there. The rule is the
same one the foundation uses: a message is a fixed template, never built from a session id, a turn
name, a prompt or a tool result. Those are somebody else's text, and an error message is what ends
up on stderr and in a log line.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["SessionError", "SessionReason"]


class SessionReason(StrEnum):
    """Why a session operation did not happen."""

    NOT_FOUND = "session.not_found"
    INVALID = "session.invalid"
    UNKNOWN_TURN = "session.unknown_turn"
    DUPLICATE_TURN = "session.duplicate_turn"
    TURN_REJECTED = "session.turn_rejected"
    EMPTY = "session.empty"
    UNSENDABLE = "session.unsendable"
    DIVERGED = "session.diverged"


_MESSAGE = {
    SessionReason.NOT_FOUND: "no session with that id",
    SessionReason.INVALID: "the session file is not a valid session",
    SessionReason.UNKNOWN_TURN: "the session has no turn by that name",
    SessionReason.DUPLICATE_TURN: "a turn with that name is already stored",
    SessionReason.TURN_REJECTED: "the turn does not follow the session rules",
    SessionReason.EMPTY: "the session has no turns to replay",
    SessionReason.UNSENDABLE: "the replayed transcript is not sendable",
    SessionReason.DIVERGED: "the recorded turns did not replay",
}


class SessionError(Exception):
    """A refusal with a fixed reason. Nothing is interpolated into the message."""

    def __init__(self, reason: SessionReason) -> None:
        self.reason = reason
        super().__init__(f"{reason.value}: {_MESSAGE[reason]}")
