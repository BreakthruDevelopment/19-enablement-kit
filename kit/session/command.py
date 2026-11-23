"""`kit session list | resume <id> | fork <id> <turn>`.

The CLI acts as the `engineer` principal for this machine's user, the same subject rule as
`kit review`, so one person is one principal for both commands. Resume prints the replay and
says that no model was called. It does not print the opening prompt or tool results: those can
carry repository content and personal text, and the stop reason is what the run ended on.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Final, TextIO

from kit.core.errors import KitError
from kit.core.principals import Principal
from kit.session.errors import SessionError
from kit.session.store import SessionStore

__all__ = [
    "DEFAULT_SESSION_DIR",
    "engineer_from_environment",
    "run_fork_command",
    "run_list_command",
    "run_resume_command",
]

DEFAULT_SESSION_DIR: Final = Path("sessions")

_UNSAFE_SUBJECT = re.compile(r"[^A-Za-z0-9_.@-]")


def engineer_from_environment() -> Principal:
    """The `engineer` principal for this machine's user, or a fixed subject if the name is odd."""
    subject = _UNSAFE_SUBJECT.sub("", os.environ.get("USER", ""))[:64] or "engineer"
    return Principal.engineer(subject)


def run_list_command(
    principal: Principal,
    *,
    directory: Path,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out, err = _streams(out, err)
    try:
        sessions = SessionStore(directory).list_sessions(principal)
    except (KitError, SessionError) as refusal:
        return _refuse(refusal, err)
    for session in sessions:
        _emit(
            out,
            {
                "budget_spent": {
                    "input_tokens": session.budget_spent.input_tokens,
                    "output_tokens": session.budget_spent.output_tokens,
                    "turns": session.budget_spent.turns,
                },
                "id": session.id,
                "parent_id": session.parent_id,
                "turn_names": [turn.name for turn in session.turns],
            },
        )
    return 0


def run_resume_command(
    principal: Principal,
    session_id: str,
    *,
    directory: Path,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out, err = _streams(out, err)
    # Imported here so `kit session list` does not load the agent loop.
    from kit.session.resume import resume

    store = SessionStore(directory)
    try:
        result = asyncio.run(resume(store, principal, session_id))
        # Resume does not write, so the turns read back are the ones just replayed. The assistant
        # text is that recording. The opening prompt and tool results are not printed.
        session = store.get(principal, session_id)
    except (KitError, SessionError) as refusal:
        return _refuse(refusal, err)
    for turn in session.turns:
        _emit(out, {"stop_reason": turn.stop_reason, "text": turn.text, "turn": turn.name})
    _emit(
        out,
        {
            "end_reason": result.end_reason,
            "event": "resumed",
            "id": result.session_id,
            "model_call": False,
            "stop_reason": result.stop_reason,
            "turns": result.turns_replayed,
        },
    )
    return 0


def run_fork_command(
    principal: Principal,
    session_id: str,
    turn_name: str,
    *,
    directory: Path,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out, err = _streams(out, err)
    try:
        forked = SessionStore(directory).fork(principal, session_id, turn_name)
    except (KitError, SessionError) as refusal:
        return _refuse(refusal, err)
    _emit(
        out,
        {
            "budget_spent": {
                "input_tokens": forked.budget_spent.input_tokens,
                "output_tokens": forked.budget_spent.output_tokens,
                "turns": forked.budget_spent.turns,
            },
            "event": "forked",
            "id": forked.id,
            "parent_id": forked.parent_id,
            "turn": turn_name,
            "turns": len(forked.turns),
        },
    )
    return 0


def _streams(out: TextIO | None, err: TextIO | None) -> tuple[TextIO, TextIO]:
    return out if out is not None else sys.stdout, err if err is not None else sys.stderr


def _refuse(refusal: KitError | SessionError, err: TextIO) -> int:
    print(f"kit session: {refusal}", file=err)
    return 2


def _emit(out: TextIO, payload: dict[str, object]) -> None:
    out.write(json.dumps(payload, sort_keys=True) + "\n")
