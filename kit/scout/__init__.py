"""The scout: explore a legacy codebase under the read-only sandbox and write a migration brief."""

from kit.scout.command import open_sandbox, run_scout_command
from kit.scout.errors import ScoutError, ScoutReason
from kit.scout.explore import Explorer, Step
from kit.scout.pipeline import ScoutResult, run_scout
from kit.scout.replay import load_replay
from kit.scout.schema import Coverage, Finding, ScoutBrief

__all__ = [
    "Coverage",
    "Explorer",
    "Finding",
    "ScoutBrief",
    "ScoutError",
    "ScoutReason",
    "ScoutResult",
    "Step",
    "load_replay",
    "open_sandbox",
    "run_scout",
    "run_scout_command",
]
