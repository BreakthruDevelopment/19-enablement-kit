"""The pass pipeline: a fan-out, then a line, then consolidation -- and the verdict, in code.

    correctness  ┐
                 ├─ (concurrent, diff only) ─> project-rules ─> tests-coverage ─> consolidation
    security     ┘

`catalog.yaml` calls these passes a Chain of Responsibility. They are not one: no pass may stop the
chain or suppress a finding, so this is a pipeline with a fan-out, and the design is not bent to fit
the label. (The kit's genuine Chain of Responsibility is the sandbox's ordered checks.)

**The reviewer can block. It cannot approve.** The computed value is `blocking` or nothing -- there
is no `verdict` field anywhere in the schema to compute or contradict. Every control in this package
acts *after* a finding exists, so a pass that silently never reports one cannot be detected by
construction, and no stacking of rules makes the absence of a block mean "safe to merge". What the
controls buy is the blocking direction: silencing the reviewer is no longer one injected comment in
one pass, it is suppressing the finding in every pass, at the moment of raising, without ever
quoting it.

**Recorded set vs presented set.** Every pass's findings, after the quote and criterion checks, form
the *recorded set*, and `blocking` is computed from that and from nothing else -- not a count, not
what consolidation returned. Consolidation yields a separate *presented set* that merges duplicates
and ranks; it cannot remove anything from the recorded set, and the display is trimmed only
after the verdict is computed.

`complete` is false when any pass *failed* (no parseable response came back). The result is then not
postable at all: it is not `blocking` on that account, and a throttled run on a clean diff must not
become a blocking review. The step that runs this exits non-zero instead.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, Protocol

from agent_container.core.budget import Budget
from agent_container.core.provider import ModelProvider

from kit.review.criteria import BLOCKING_SEVERITIES, Criteria, Severity
from kit.review.inputs import check_diff
from kit.review.passes import (
    PassResult,
    PassStatus,
    RecordedFinding,
    run_consolidation,
    run_finding_pass,
)
from kit.review.passes_names import FINDING_PASSES, PassName

__all__ = [
    "MAX_PRESENTED",
    "PresentedFinding",
    "ProviderSource",
    "ReviewResult",
    "SharedProvider",
    "build_presented",
    "compute_blocking",
    "default_budget",
    "run_review",
]

# Display only. Trimmed after the verdict is computed, and the report says how many were not shown.
MAX_PRESENTED: Final = 25

_SEVERITY_RANK: Final = {Severity.CRITICAL: 0, Severity.MAJOR: 1, Severity.MINOR: 2}


class ProviderSource(Protocol):
    """Where each pass gets its model.

    Two passes run concurrently, so one ordered `ReplayProvider` would make a fixture's meaning
    depend on scheduling. Each pass gets its own provider by name instead; a live source can hand
    every pass the same one.
    """

    def for_pass(self, name: PassName) -> ModelProvider: ...


@dataclass(frozen=True, slots=True)
class SharedProvider:
    provider: ModelProvider

    def for_pass(self, name: PassName) -> ModelProvider:
        return self.provider


@dataclass(frozen=True, slots=True)
class PresentedFinding:
    """One line of the report: the most severe of the findings merged into it, and the rest."""

    lead: RecordedFinding
    merged: tuple[RecordedFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class ReviewResult:
    passes: tuple[PassResult, ...]
    recorded: tuple[RecordedFinding, ...]
    presented: tuple[PresentedFinding, ...]
    omitted: int
    blocking: bool

    @property
    def verdict(self) -> Literal["blocking"] | None:
        """`blocking` or nothing. There is no second value to return."""
        return "blocking" if self.blocking else None

    @property
    def failed(self) -> tuple[PassResult, ...]:
        return tuple(p for p in self.passes if p.status is PassStatus.FAILED)

    @property
    def rejected(self) -> tuple[PassResult, ...]:
        return tuple(p for p in self.passes if p.status is PassStatus.REJECTED)

    @property
    def complete(self) -> bool:
        """False if any pass never got a parseable response. An incomplete run posts nothing."""
        return not self.failed


def compute_blocking(passes: Sequence[PassResult], recorded: Sequence[RecordedFinding]) -> bool:
    """`blocking` iff a pass was rejected or the recorded set holds a major or critical finding.

    Severity was assigned from the criterion by code. Nothing a model returned reaches this
    function except through the recorded set's verified findings.
    """
    if any(p.status is PassStatus.REJECTED for p in passes):
        return True
    return any(r.severity in BLOCKING_SEVERITIES for r in recorded)


def build_presented(
    recorded: Sequence[RecordedFinding],
    groups: Sequence[Sequence[int]] | None,
) -> tuple[PresentedFinding, ...]:
    """Merge and rank for display. Consolidation proposes; code disposes.

    * Only findings on the **same path** merge, and a group's lead is its **most severe** member, so
      a merge can never show a major finding as a minor one.
    * An index that is out of range or already used is ignored, and a finding no group mentions is
      still shown. Consolidation cannot make a finding disappear from the report either.
    * The order is by severity first and consolidation's ranking second, so a hostile or lazy
      ranking
      cannot push a critical finding below the trim.
    """
    count = len(recorded)
    assigned: set[int] = set()
    items: list[PresentedFinding] = []
    for group in groups or ():
        members = [i for i in dict.fromkeys(group) if 0 <= i < count and i not in assigned]
        by_path: dict[str, list[int]] = {}
        for i in members:
            by_path.setdefault(recorded[i].finding.path, []).append(i)
        for bucket in by_path.values():
            lead = min(bucket, key=lambda i: _SEVERITY_RANK[recorded[i].severity])
            items.append(
                PresentedFinding(recorded[lead], tuple(recorded[i] for i in bucket if i != lead))
            )
            assigned.update(bucket)
    items.extend(PresentedFinding(recorded[i]) for i in range(count) if i not in assigned)
    items.sort(key=lambda item: _SEVERITY_RANK[item.lead.severity])  # stable
    return tuple(items)


def default_budget() -> Budget:
    """One run's allowance, shared by every pass.

    200 KB of diff is about 50k tokens a call, and there are five calls.
    """
    return Budget(max_turns=8, max_tokens=800_000, max_seconds=600.0)


async def run_review(
    diff: str,
    providers: ProviderSource,
    criteria: Mapping[PassName, Criteria],
    *,
    budget: Budget | None = None,
    nonce: str | None = None,
) -> ReviewResult:
    """Run every pass over `diff` and compute the result.

    `budget` is one per run, shared by all passes; a used one raises `BudgetAlreadyStarted`. Raises
    `ReviewError` before any model call if the diff is over a cap.
    """
    check_diff(diff)
    run_budget = budget if budget is not None else default_budget()
    run_budget.start()
    run_nonce = nonce if nonce is not None else secrets.token_hex(8)

    async def finding_pass(name: PassName, prior: Sequence[RecordedFinding]) -> PassResult:
        return await run_finding_pass(
            name, providers.for_pass(name), run_budget, criteria[name], diff, run_nonce, prior
        )

    results: list[PassResult] = []
    recorded: list[RecordedFinding] = []

    # Correctness and security are two concurrent instances that see only the diff.
    first = await asyncio.gather(
        finding_pass(PassName.CORRECTNESS, ()), finding_pass(PassName.SECURITY, ())
    )
    for result in first:
        results.append(result)
        recorded.extend(result.findings)

    # The later passes see the diff plus everything recorded before them.
    for name in FINDING_PASSES[2:]:
        result = await finding_pass(name, tuple(recorded))
        results.append(result)
        recorded.extend(result.findings)

    groups: tuple[tuple[int, ...], ...] | None = None
    run_complete = all(r.status is not PassStatus.FAILED for r in results)
    if recorded and run_complete:
        consolidation, groups = await run_consolidation(
            providers.for_pass(PassName.CONSOLIDATION),
            run_budget,
            tuple(recorded),
            diff,
            run_nonce,
        )
        results.append(consolidation)

    blocking = compute_blocking(results, recorded)  # before anything is trimmed
    presented = build_presented(recorded, groups)
    return ReviewResult(
        passes=tuple(results),
        recorded=tuple(recorded),
        presented=presented[:MAX_PRESENTED],
        omitted=max(0, len(presented) - MAX_PRESENTED),
        blocking=blocking,
    )
