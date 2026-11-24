"""The report: sanitised, not typeset.

It carries its own marker -- `Kit-Review: pr-review` and, when blocking, `Kit-Verdict: blocking` --
and never the factory's. It is a report: it never satisfies `Reviewer sign-off`, which stays a
person's to give, and a clean diff yields findings or nothing and **no verdict**, never an approval.

Everything a model or a contributor wrote is made safe by shape before it is placed: a claim, a
path and a criterion id are flattened to one line so none can begin a line of its own, and every
line
of quoted evidence is prefixed with `> `. That prefix is typography and not the control (see
`kit.review.sanitize`); the control is the check the finished body goes through last, which refuses
the whole report if the gate could read any of it as a sign-off.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from kit.review.errors import ReviewError, ReviewReason
from kit.review.passes import PassStatus, RecordedFinding
from kit.review.passes_names import PassName
from kit.review.pipeline import PresentedFinding, ReviewResult
from kit.review.sanitize import assert_body_safe, defang_codex_state, normalise_terminators

__all__ = ["EXTRA_MARKER_KEYS", "ReportMode", "render_report"]

_MARKER: Final = "Kit-Review: pr-review"
_BLOCKING_MARKER: Final = "Kit-Verdict: blocking"
_MAX_QUOTE_LINES: Final = 8

# The only extra marker lines a caller can add, and the shape their values must have. A fixed set of
# keys and a token-shaped value: nothing a diff or a model wrote can reach a marker line.
EXTRA_MARKER_KEYS: Final = frozenset({"Kit-Mode", "Kit-Commit"})
_MARKER_VALUE: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")


class ReportMode(StrEnum):
    """How the passes got their answers. Said in the report, because it changes what it proves."""

    RECORDED = "recorded"
    LIVE = "live"


_RECORDED_NOTICE: Final = (
    "This run used recorded replies: no model read this diff. The lines below show that the"
    " pipeline ran, not that the change is clean."
)

_SQUASH = re.compile(r"[\s\ufeff\x00-\x1f\x7f]+")


def _one_line(text: str) -> str:
    return _SQUASH.sub(" ", text).strip()


def _quote(text: str) -> list[str]:
    all_lines = normalise_terminators(text).split("\n")
    lines = all_lines[:_MAX_QUOTE_LINES]
    quoted = [f"> {line}" for line in lines]
    if len(all_lines) > _MAX_QUOTE_LINES:
        # Said rather than left silent: a quote cut without a marker reads like the whole of the
        # evidence, which is the same class of mistake as a truncated read that looks complete.
        quoted.append(f"> ... ({len(all_lines) - _MAX_QUOTE_LINES} more line(s) not shown)")
    return quoted


def _where(r: RecordedFinding) -> str:
    path = _one_line(r.finding.path).replace("`", "'")
    return f"`{path}:{r.finding.line}`"


def _finding_lines(r: RecordedFinding) -> list[str]:
    return [
        f"**{r.severity.value}** {_one_line(r.finding.criterion_id)} "
        f"{_where(r)} ({r.pass_name.value}): {_one_line(r.finding.claim)}",
        *(f"  {line}" for line in _quote(r.finding.evidence_quote)),
    ]


def _item(item: PresentedFinding) -> list[str]:
    head, *rest = _finding_lines(item.lead)
    out = [f"- {head}", *rest]
    for m in item.merged:
        # Each merged finding keeps its own claim and its own quote, not just its criterion and
        # line. A merge groups what consolidation says is one problem, and the lead is a model's
        # choice twice over -- consolidation's grouping, and the order its own pass listed the
        # findings in, which is what the recorded-index tie-break reads. So showing only the
        # lead's text would let a trivial decoy listed first stand in for the real defect, in the
        # only artifact the command emits. The recorded set would still hold it; the report would
        # not say what it was.
        also, *quoted = _finding_lines(m)
        out.append(f"  Also: {also}")
        out.extend(f"  {line}" for line in quoted)
    return out


def render_report(
    result: ReviewResult,
    *,
    mode: ReportMode | None = None,
    markers: Mapping[str, str] | None = None,
) -> str:
    """The body to post. Raises `ReviewError` if the body could satisfy the gate, and `ValueError`
    if the run is incomplete: an incomplete run has no report."""
    if not result.complete:
        raise ValueError("an incomplete run has no report to post")
    lines = [_MARKER]
    if result.blocking:
        lines.append(_BLOCKING_MARKER)
    for key, value in (markers or {}).items():
        if key not in EXTRA_MARKER_KEYS or not _MARKER_VALUE.fullmatch(value):
            raise ReviewError(ReviewReason.CI_INPUT_INVALID)
        lines.append(f"{key}: {value}")
    lines += ["", "## Automated review", ""]
    lines.append(
        "This is an automated report. It can block, it cannot approve, and it is not a sign-off:"
        " the merge gate's approval stays with a person."
    )
    if mode is ReportMode.RECORDED:
        lines.append("")
        lines.append(_RECORDED_NOTICE)
    lines.append("")
    for p in result.passes:
        if p.name is PassName.CONSOLIDATION:
            # Branched on the status, not assumed: a failed consolidation no longer makes the run
            # incomplete, so this line is now reachable on a degraded run -- and it is the only
            # thing the report says about consolidation. Claiming it ranked the findings when it
            # did not would be a false statement about the artifact, and consolidation is
            # prompted with the diff, so a contributor can reach that path.
            if p.status is PassStatus.FAILED:
                reasons = ", ".join(p.reasons)
                lines.append(
                    f"- consolidation: did not complete ({reasons});"
                    " the findings below are neither merged nor ranked"
                )
            else:
                lines.append(
                    "- consolidation: merged duplicates; the display order is by severity"
                    " and then by the order the findings were recorded, set in code"
                )
            continue
        note = ""
        if p.status is PassStatus.REJECTED:
            note = " -- rejected (" + ", ".join(p.reasons) + "); findings it raised are kept"
        lines.append(f"- {p.name.value}: {len(p.findings)} finding(s){note}")
    lines.append("")
    if not result.presented:
        lines.append("No findings. This is a report, not an approval.")
    else:
        lines.append("### Findings")
        lines.append("")
        for item in result.presented:
            lines.extend(_item(item))
        # Counted over the findings, not the display items: a merged group shows several, so
        # counting trimmed items would undercount what is on record and not shown.
        shown = sum(1 + len(item.merged) for item in result.presented)
        unshown = len(result.recorded) - shown
        if unshown > 0:
            lines.append("")
            lines.append(f"{unshown} further finding(s) are on record and not shown here.")
    # Defanged first, then checked: the check is the control, and it still refuses anything left.
    body = defang_codex_state("\n".join(lines) + "\n")
    assert_body_safe(body)
    return body
