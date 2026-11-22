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
from typing import Final

from kit.review.passes import PassStatus, RecordedFinding
from kit.review.passes_names import PassName
from kit.review.pipeline import PresentedFinding, ReviewResult
from kit.review.sanitize import assert_body_safe, normalise_terminators

__all__ = ["render_report"]

_MARKER: Final = "Kit-Review: pr-review"
_BLOCKING_MARKER: Final = "Kit-Verdict: blocking"
_MAX_QUOTE_LINES: Final = 8

_SQUASH = re.compile(r"[\s\ufeff\x00-\x1f\x7f]+")


def _one_line(text: str) -> str:
    return _SQUASH.sub(" ", text).strip()


def _quote(text: str) -> list[str]:
    lines = normalise_terminators(text).split("\n")[:_MAX_QUOTE_LINES]
    return [f"> {line}" for line in lines]


def _where(r: RecordedFinding) -> str:
    path = _one_line(r.finding.path).replace("`", "'")
    return f"`{path}:{r.finding.line}`"


def _item(item: PresentedFinding) -> list[str]:
    lead = item.lead
    out = [
        f"- **{lead.severity.value}** {_one_line(lead.finding.criterion_id)} "
        f"{_where(lead)} ({lead.pass_name.value}): {_one_line(lead.finding.claim)}",
        *(f"  {line}" for line in _quote(lead.finding.evidence_quote)),
    ]
    for m in item.merged:
        # Each merged finding keeps its own criterion and line: a merge groups what consolidation
        # says is one problem, and showing only the lead's text would let a grouping replace a
        # real finding's claim with a decoy's.
        out.append(
            f"  Also: **{m.severity.value}** {_one_line(m.finding.criterion_id)} "
            f"{_where(m)} ({m.pass_name.value})"
        )
    return out


def render_report(result: ReviewResult) -> str:
    """The body to post. Raises `ReviewError` if the body could satisfy the gate, and `ValueError`
    if the run is incomplete: an incomplete run has no report."""
    if not result.complete:
        raise ValueError("an incomplete run has no report to post")
    lines = [_MARKER]
    if result.blocking:
        lines.append(_BLOCKING_MARKER)
    lines += ["", "## Automated review", ""]
    lines.append(
        "This is an automated report. It can block, it cannot approve, and it is not a sign-off:"
        " the merge gate's approval stays with a person."
    )
    lines.append("")
    for p in result.passes:
        if p.name is PassName.CONSOLIDATION:
            lines.append("- consolidation: merged duplicates and ranked the findings for display")
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
        if result.omitted:
            lines.append("")
            lines.append(f"{result.omitted} further finding(s) are on record and not shown here.")
    body = "\n".join(lines) + "\n"
    assert_body_safe(body)
    return body
