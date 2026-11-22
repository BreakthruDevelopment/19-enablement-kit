"""The written criteria: one file per pass, numbered, each entry declaring its own severity.

This is statement 4.1, and the control that keeps the reviewer from inventing house style: a finding
must name a criterion, and a criterion is one of the numbered entries in the file of the pass that
raised it. Severity lives here too. It is a property of the rule that was broken, not a judgement
about the instance, so code looks a finding's severity up by `criterion_id` and a model is never
asked for one -- and is not *shown* them either, so a pass cannot pick the cheapest criterion in its
file to dodge a block.

An entry is a level-two heading and its body::

    ## COR-1 | major | Reference equality on values
    Text of the criterion...

Anything else that starts `## ` is refused rather than skipped: a heading that failed to parse would
otherwise be a criterion that silently does not exist. Each file's ids carry its pass's prefix, so
an id is unique across files by construction and a pass cannot cite another pass's entry by
accident.

`criteria/` is not a foundation path, deliberately (see the spec): lowering a severity can only
cause a missed block, which is the ceiling the one-sided verdict already concedes. The CI slice
should read this directory from the base branch rather than from the pull request under review.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Final

from kit.core.sandbox import Sandbox
from kit.review.errors import ReviewError, ReviewReason
from kit.review.passes_names import FINDING_PASSES, PassName

__all__ = [
    "BLOCKING_SEVERITIES",
    "Criteria",
    "Criterion",
    "Severity",
    "load_criteria",
    "parse_criteria",
]


class Severity(StrEnum):
    """`critical`, `major`, `minor`. The order is documentation: code tests membership only."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


BLOCKING_SEVERITIES: Final = frozenset({Severity.MAJOR, Severity.CRITICAL})

_PREFIX: Final[Mapping[PassName, str]] = MappingProxyType(
    {
        PassName.CORRECTNESS: "COR",
        PassName.SECURITY: "SEC",
        PassName.PROJECT_RULES: "RUL",
        PassName.TESTS_COVERAGE: "TST",
    }
)

# A criterion is a rule, written to be read by a person and applied by a pass. Its text is bounded
# because `render()` goes into every pass's system prompt: `criteria/` is deliberately not a
# foundation path, so a pull request can edit it, and without a cap four files could put several
# hundred kilobytes into each of five calls. The cap is generous for a rule and small for a
# payload.
MAX_CRITERION_BYTES: Final = 2_000
MAX_CRITERIA_BYTES: Final = 20_000
MAX_CRITERIA_ENTRIES: Final = 40

_HEADING = re.compile(
    r"\A## (?P<id>[A-Z]{3}-[0-9]{1,3}) \| (?P<severity>critical|major|minor) \| "
    r"(?P<title>\S.{0,118})\Z"
)


@dataclass(frozen=True, slots=True)
class Criterion:
    id: str
    severity: Severity
    title: str
    text: str


@dataclass(frozen=True, slots=True)
class Criteria:
    """One pass's criteria. `by_id` is the only lookup a finding is graded through."""

    pass_name: PassName
    entries: tuple[Criterion, ...]

    @property
    def by_id(self) -> Mapping[str, Criterion]:
        return MappingProxyType({c.id: c for c in self.entries})

    def render(self) -> str:
        """The numbered list a pass is shown. Titles and text, no severities."""
        return "\n\n".join(f"{c.id}: {c.title}\n{c.text}" for c in self.entries)


def parse_criteria(pass_name: PassName, text: str) -> Criteria:
    """Parse one file, or raise `ReviewError(CRITERIA_INVALID)`."""
    prefix = _PREFIX[pass_name]
    entries: list[Criterion] = []
    seen: set[str] = set()
    current: tuple[str, Severity, str] | None = None
    body: list[str] = []

    def close() -> None:
        if current is None:
            return
        text_ = "\n".join(body).strip()
        if not text_ or len(text_.encode("utf-8")) > MAX_CRITERION_BYTES:
            raise ReviewError(ReviewReason.CRITERIA_INVALID)
        entries.append(Criterion(current[0], current[1], current[2], text_))

    if len(text.encode("utf-8")) > MAX_CRITERIA_BYTES:
        raise ReviewError(ReviewReason.CRITERIA_INVALID)
    for line in text.splitlines():
        if line.startswith("## "):
            close()
            match = _HEADING.match(line)
            if match is None or not match["id"].startswith(prefix + "-"):
                raise ReviewError(ReviewReason.CRITERIA_INVALID)
            if match["id"] in seen:
                raise ReviewError(ReviewReason.CRITERIA_INVALID)
            seen.add(match["id"])
            current = (match["id"], Severity(match["severity"]), match["title"])
            body = []
        elif current is not None:
            body.append(line)
    close()
    if not entries or len(entries) > MAX_CRITERIA_ENTRIES:
        raise ReviewError(ReviewReason.CRITERIA_INVALID)
    return Criteria(pass_name, tuple(entries))


def load_criteria(sandbox: Sandbox, directory: Path) -> Mapping[PassName, Criteria]:
    """Every finding pass's criteria, read through the sandbox.

    `directory` must be one of the sandbox's roots.
    """
    loaded = {
        name: parse_criteria(name, sandbox.read_text(directory / f"{name.value}.md"))
        for name in FINDING_PASSES
    }
    return MappingProxyType(loaded)
