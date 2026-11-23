"""`kit scout <root>`: explore a codebase under the sandbox and print a migration brief.

The CLI acts as the `engineer` principal for this machine's user, as `kit review` does, and
authorization comes first: `assert_can(..., RUN_SCOUT)` runs before the sandbox is opened, so a
principal that may not scout reads nothing. `ci` may read files and may not scout.

The sandbox's one root is the directory named on the command line, and `open_sandbox` is the only
place that decides it. Anything beside or above that directory -- the sample's manifest, which
lists the planted problems, is one level up from `sample/legacy-oms/` -- is outside the roots, and
the sandbox refuses it. The tests open their sandboxes through the same function, so a change to the
roots is a change those tests see.

Only the recorded reply is wired here, as in `kit review`: `--replay` names a directory holding
`brief.json`. `run_scout` takes any `ModelProvider`, which is where a live one would be passed.

Exit codes:

* `0` -- a brief was produced and printed to stdout as JSON: the brief, and the step record.
* `1` -- the run could not complete: no reply, an unusable stop reason, an unparseable reply, or a
  spent budget. Nothing is printed to stdout.
* `2` -- refused before any model call: the principal may not scout, the root is not a directory,
  no recording, or the sandbox served nothing.
* `3` -- the assembled brief held a secret-shaped string, so it was withheld.

An error line carries a fixed reason code and nothing else: no path, no pattern, no file content.
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
from kit.scout.errors import ScoutError, ScoutReason
from kit.scout.pipeline import run_scout
from kit.scout.replay import load_replay

__all__ = ["engineer_from_environment", "open_sandbox", "register_scout", "run_scout_command"]

DEFAULT_REPLAY_DIR: Final = Path("fixtures/scout-brief/demo/replies")

_UNSAFE_SUBJECT = re.compile(r"[^A-Za-z0-9_.@-]")


def engineer_from_environment() -> Principal:
    """The `engineer` principal for this machine's user, or a fixed subject if the name is odd."""
    subject = _UNSAFE_SUBJECT.sub("", os.environ.get("USER", ""))[:64] or "engineer"
    return Principal.engineer(subject)


def open_sandbox(
    principal: Principal, root: Path | str, limits: SandboxLimits | None = None
) -> Sandbox:
    """The sandbox a scout explores: exactly one root, the one it was asked to explore."""
    return Sandbox(principal, [root], limits)


def register_scout(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Add `scout` to the CLI's one subparser group."""
    scout = commands.add_parser(
        "scout",
        help="explore a codebase under the read-only sandbox and write a migration brief",
        description=(
            "Explore a codebase through the read-only sandbox and print a migration brief. "
            "The default replays a recorded reply and makes no model call."
        ),
    )
    scout.add_argument("root", type=Path, help="the codebase to explore")
    scout.add_argument(
        "--replay",
        type=Path,
        default=DEFAULT_REPLAY_DIR,
        help=f"directory holding the recorded reply, brief.json (default: {DEFAULT_REPLAY_DIR})",
    )


def run_scout_command(
    root: Path,
    *,
    principal: Principal,
    replay_dir: Path = DEFAULT_REPLAY_DIR,
    limits: SandboxLimits | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out if out is not None else sys.stdout
    err = err if err is not None else sys.stderr
    try:
        assert_can(principal, Capability.RUN_SCOUT)
        sandbox = open_sandbox(principal, root, limits)
        provider = load_replay(replay_dir)
        result = asyncio.run(run_scout(sandbox, provider))
    except KitError as refusal:
        print(f"kit scout: refused: {refusal.code.value}", file=err)
        return 2
    except ScoutError as refusal:
        print(f"kit scout: {refusal.reason.value}", file=err)
        if refusal.reason is ScoutReason.BRIEF_REFUSED:
            return 3
        if refusal.reason in (ScoutReason.REPLAY_MISSING, ScoutReason.NOTHING_READ):
            return 2
        return 1
    out.write(json.dumps(result.as_dict(), indent=2, ensure_ascii=False) + "\n")
    return 0
