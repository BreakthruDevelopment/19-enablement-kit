"""The names of the passes, kept apart so `criteria` and `passes` can both import them."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = ["FINDING_PASSES", "PassName"]


class PassName(StrEnum):
    CORRECTNESS = "correctness"
    SECURITY = "security"
    PROJECT_RULES = "project-rules"
    TESTS_COVERAGE = "tests-coverage"
    CONSOLIDATION = "consolidation"


# The passes that raise findings against a criteria file. Consolidation raises none.
FINDING_PASSES: Final = (
    PassName.CORRECTNESS,
    PassName.SECURITY,
    PassName.PROJECT_RULES,
    PassName.TESTS_COVERAGE,
)
