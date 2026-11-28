"""`kit plan`: plan mode versus direct execution, and iterative refinement (statements 3.4, 3.5).

One task, run planned first and executed directly from one forked session prefix, both transcripts
kept as sessions and replayed through app 17's loop at zero cost; then, with `--refine`, the
reviewer's findings on the direct attempt run into a second attempt, and the two review rounds are
compared.
"""

from kit.plan.errors import PlanError, PlanReason
from kit.plan.recording import PlanRecording, RefineRecording, check_plan_rules
from kit.plan.run import PlanReport, RefineReport, build_refine_opening, run_plan, run_refine

__all__ = [
    "PlanError",
    "PlanReason",
    "PlanRecording",
    "PlanReport",
    "RefineRecording",
    "RefineReport",
    "build_refine_opening",
    "check_plan_rules",
    "run_plan",
    "run_refine",
]
