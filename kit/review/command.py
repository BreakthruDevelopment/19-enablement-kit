"""`kit review <diff>`: the review passes over a diff, as the `engineer` principal.

Authorization comes first (`assert_can(..., RUN_REVIEW)`), and every file is read through a sandbox,
the diff included: it is untrusted content, so it gets the same symlink, deny-list and byte-cap
treatment as anything the scout reads. The sandbox's per-file cap is set to the review's own 200 KB
cap, so an oversized diff is refused by the Proxy before it is decoded.

Exit codes, so a workflow step can tell the four outcomes apart:

* `0` -- a report was produced (blocking or not) and printed to stdout.
* `1` -- the run could not complete: a pass never got a parseable response. **Nothing is printed
  to stdout** and nothing should be posted; this is the throttled-run case.
* `2` -- refused before any model call: bad usage, an unreadable or oversized diff, bad criteria,
  no recording.
* `3` -- the assembled report could satisfy the factory's sign-off check, so it was withheld.

Only recorded replies are wired in this slice. `--replay` names a directory of per-pass recordings,
defaulting to `replies/` beside the diff, so every run is at zero cost with no network.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import Final, TextIO

from kit.core.config import SandboxLimits
from kit.core.errors import KitError
from kit.core.principals import Capability, Principal, assert_can
from kit.core.sandbox import Sandbox
from kit.review.criteria import load_criteria
from kit.review.errors import ReviewError
from kit.review.inputs import MAX_DIFF_BYTES
from kit.review.pipeline import run_review
from kit.review.replay import ReplayDirectory
from kit.review.report import render_report

__all__ = ["engineer_from_environment", "run_review_command"]

DEFAULT_CRITERIA_DIR: Final = Path("criteria")

_UNSAFE_SUBJECT = re.compile(r"[^A-Za-z0-9_.@-]")


def engineer_from_environment() -> Principal:
    """The `engineer` principal for this machine's user, or a fixed subject if the name is odd."""
    subject = _UNSAFE_SUBJECT.sub("", os.environ.get("USER", ""))[:64] or "engineer"
    return Principal.engineer(subject)


def run_review_command(
    diff_path: Path,
    *,
    principal: Principal,
    replay_dir: Path | None = None,
    criteria_dir: Path = DEFAULT_CRITERIA_DIR,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        assert_can(principal, Capability.RUN_REVIEW)
        diff_file = diff_path.resolve()
        sandbox = Sandbox(
            principal,
            [diff_file.parent, criteria_dir],
            SandboxLimits(max_file_bytes=MAX_DIFF_BYTES),
        )
        diff = sandbox.read_text(diff_file)
        criteria = load_criteria(sandbox, criteria_dir.resolve())
        replies = ReplayDirectory(
            replay_dir if replay_dir is not None else diff_file.parent / "replies"
        )
        result = asyncio.run(run_review(diff, replies, criteria))
    except KitError as refusal:
        print(f"kit review: {refusal.message}", file=err)
        return 2
    except ReviewError as refusal:
        print(f"kit review: {refusal}", file=err)
        return 2

    if not result.complete:
        names = ", ".join(p.name.value for p in result.failed)
        print(
            f"kit review: could not complete; no response from: {names}. Nothing was posted.",
            file=err,
        )
        if result.blocking:
            # The one degraded case worth stating out loud: a pass got nothing back, so nothing
            # is posted, *and* what the other passes did record would have blocked. Printing only
            # the failed pass names would let that pass unnoticed.
            print(
                "kit review: findings that would have blocked are already on record"
                f" ({len(result.recorded)} in all); re-run when the provider answers.",
                file=err,
            )
        return 1
    try:
        body = render_report(result)
    except ReviewError as refusal:
        print(f"kit review: {refusal}", file=err)
        return 3
    out.write(body)
    return 0
