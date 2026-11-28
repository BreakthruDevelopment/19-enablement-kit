"""`kit plan <task>`: the same task planned first and executed directly, and `--refine`.

The CLI acts as the `engineer` principal for this machine's user, as `kit review` and `kit
session` do, so the sessions it stores are that person's own and `kit session list` shows them.
Authorization comes first: `assert_can(..., RUN_PLAN)` runs before any file is read, and `ci`
does not hold it.

Only recorded replies are wired, as in every command so far: `--replay` names a directory holding
`plan.json` (and, for `--refine`, `refine.json` and the reviewer's recordings for both rounds in
`review-1/` and `review-2/`). Every run is at zero cost with no network, and the output says
`model_call: false` on every line that replayed something.

Output is JSON lines on stdout: `prefix`, one `arm` per mode, `comparison`; with `--refine`, then
`review` (round 1), `attempt`, `review` (round 2) and `refinement`.

Exit codes:

* `0` -- the comparison (and the refinement, if asked) was printed.
* `1` -- a review pass got no usable response, so there is nothing to compare. Sessions stored
  before that point are kept.
* `2` -- refused: the principal, a missing or invalid recording, a task with no recording, a
  recording that breaks the plan rules, a stale refinement recording, or a session refusal.

An error line carries a fixed reason code and its fixed wording: no path, no task text, no turn.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Final, TextIO

from kit.core.config import SandboxLimits
from kit.core.errors import KitError
from kit.core.principals import Capability, Principal, assert_can
from kit.core.sandbox import Sandbox
from kit.plan.errors import PlanError, PlanReason
from kit.plan.recording import (
    MAX_RECORDING_BYTES,
    load_plan_recording,
    load_refine_recording,
)
from kit.plan.run import run_plan, run_refine
from kit.review.criteria import load_criteria
from kit.review.errors import ReviewError
from kit.review.replay import ReplayDirectory
from kit.session.errors import SessionError
from kit.session.store import SessionStore

__all__ = [
    "DEFAULT_REPLAY_DIR",
    "engineer_from_environment",
    "register_plan",
    "run_plan_command",
]

DEFAULT_REPLAY_DIR: Final = Path("fixtures/plan/demo")
DEFAULT_SESSION_DIR: Final = Path("sessions")
DEFAULT_CRITERIA_DIR: Final = Path("criteria")
FIRST_REVIEW_DIR: Final = "review-1"
SECOND_REVIEW_DIR: Final = "review-2"

_UNSAFE_SUBJECT = re.compile(r"[^A-Za-z0-9_.@-]")


def engineer_from_environment() -> Principal:
    """The `engineer` principal for this machine's user, or a fixed subject if the name is odd."""
    subject = _UNSAFE_SUBJECT.sub("", os.environ.get("USER", ""))[:64] or "engineer"
    return Principal.engineer(subject)


def register_plan(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `plan` to the CLI's one subparser group."""
    plan = commands.add_parser(
        "plan",
        help="the same task planned first versus executed directly, both transcripts kept",
        description=(
            "Run one task planned first and executed directly from one forked session prefix, "
            "keep both transcripts as sessions, and print a comparison of turns, tool calls and "
            "budget spent. --refine then reviews the direct attempt, runs the findings into a "
            "second attempt and shows what changed. The default replays recorded replies and "
            "makes no model call."
        ),
    )
    plan.add_argument("task", help="the task; it must be the recorded one")
    plan.add_argument(
        "--replay",
        type=Path,
        default=DEFAULT_REPLAY_DIR,
        help=f"directory holding plan.json and refine.json (default: {DEFAULT_REPLAY_DIR})",
    )
    plan.add_argument(
        "--dir",
        dest="directory",
        type=Path,
        default=DEFAULT_SESSION_DIR,
        help=f"directory of session files (default: {DEFAULT_SESSION_DIR}/)",
    )
    plan.add_argument(
        "--criteria",
        type=Path,
        default=DEFAULT_CRITERIA_DIR,
        help=f"the review criteria directory, for --refine (default: {DEFAULT_CRITERIA_DIR}/)",
    )
    plan.add_argument(
        "--refine",
        action="store_true",
        help="review the direct attempt and run the findings into a second attempt",
    )


def run_plan_command(
    task: str,
    *,
    principal: Principal,
    replay_dir: Path = DEFAULT_REPLAY_DIR,
    directory: Path = DEFAULT_SESSION_DIR,
    criteria_dir: Path = DEFAULT_CRITERIA_DIR,
    refine: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    lines: list[dict[str, object]] = []
    try:
        assert_can(principal, Capability.RUN_PLAN)
        if refine:
            assert_can(principal, Capability.RUN_REVIEW)
        roots = [replay_dir, criteria_dir] if refine else [replay_dir]
        sandbox = Sandbox(principal, roots, SandboxLimits(max_file_bytes=MAX_RECORDING_BYTES))
        recording = load_plan_recording(sandbox, replay_dir.resolve())
        store = SessionStore(directory)
        report = asyncio.run(run_plan(store, principal, recording, task))
        lines.append(report.prefix_dict())
        lines.append(report.planned.as_dict())
        lines.append(report.direct.as_dict())
        lines.append(report.comparison())
        if refine:
            refine_recording = load_refine_recording(sandbox, replay_dir.resolve())
            criteria = load_criteria(sandbox, criteria_dir.resolve())
            refined = asyncio.run(
                run_refine(
                    store,
                    principal,
                    report,
                    refine_recording,
                    first_review=ReplayDirectory(replay_dir / FIRST_REVIEW_DIR),
                    second_review=ReplayDirectory(replay_dir / SECOND_REVIEW_DIR),
                    criteria=criteria,
                )
            )
            lines.append(refined.first.as_dict())
            lines.append(refined.attempt_dict())
            lines.append(refined.second.as_dict())
            lines.append(refined.changes())
    except KitError as refusal:
        print(f"kit plan: refused: {refusal.code.value}", file=err)
        return 2
    except PlanError as refusal:
        print(f"kit plan: {refusal}", file=err)
        return 1 if refusal.reason is PlanReason.REVIEW_INCOMPLETE else 2
    except (SessionError, ReviewError) as refusal:
        print(f"kit plan: {refusal}", file=err)
        return 2
    for line in lines:
        # `ensure_ascii=True`: the recorded plan text is the one free value copied verbatim
        # to stdout, and U+2028/U+2029 are line terminators to a Unicode-aware splitter
        # (`str.splitlines`, JavaScript) but not to `json.dumps`, so leaving them raw let a
        # recording split one object across two lines. The other `ensure_ascii=False` calls
        # in the kit are prompt text or a single pretty-printed object, not line-delimited.
        out.write(json.dumps(line, sort_keys=True) + "\n")
    return 0
