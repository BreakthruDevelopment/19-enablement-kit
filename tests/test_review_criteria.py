"""The criteria files: parsed strictly, each declaring its own severity."""

from __future__ import annotations

import pytest
from review_support import load_demo_criteria

from kit.review import BLOCKING_SEVERITIES, FINDING_PASSES, PassName, ReviewError, Severity
from kit.review.criteria import parse_criteria
from kit.review.passes import RecordedFinding
from kit.review.pipeline import MAX_PRESENTED, ReviewResult, build_presented
from kit.review.report import render_report
from kit.review.schema import Finding

GOOD = (
    "# Title\n\n## SEC-1 | critical | Title here\nBody text.\n\n## SEC-2 | minor | Another\nMore.\n"
)


def test_the_shipped_criteria_load_with_a_severity_each() -> None:
    criteria = load_demo_criteria()
    assert set(criteria) == set(FINDING_PASSES)
    for entries in criteria.values():
        assert entries.entries
        assert all(isinstance(c.severity, Severity) for c in entries.entries)
    ids = [c.id for e in criteria.values() for c in e.entries]
    assert len(ids) == len(set(ids))


def test_blocking_severities_are_major_and_critical() -> None:
    assert {Severity.MAJOR, Severity.CRITICAL} == BLOCKING_SEVERITIES


def test_a_good_file_parses_and_renders_without_severities() -> None:
    parsed = parse_criteria(PassName.SECURITY, GOOD)
    assert [c.id for c in parsed.entries] == ["SEC-1", "SEC-2"]
    assert parsed.by_id["SEC-1"].severity is Severity.CRITICAL
    assert parsed.render() == "SEC-1: Title here\nBody text.\n\nSEC-2: Another\nMore."


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# only a title\n",
        "## SEC-1 | urgent | Bad severity\nBody\n",
        "## SEC-1 | major\nBody\n",
        "## SEC-1 | major | Title\n",  # no body
        "## COR-1 | major | Wrong pass prefix\nBody\n",
        "## SEC-1 | major | A\nBody\n## SEC-1 | minor | B\nBody\n",  # duplicate id
        "## Unnumbered heading\nBody\n",
        "## sec-1 | major | Lower case id\nBody\n",
    ],
)
def test_malformed_criteria_are_refused(text: str) -> None:
    with pytest.raises(ReviewError):
        parse_criteria(PassName.SECURITY, text)


# --- The presented set is ordered in code, not by the consolidation pass ------------------------


def _critical(index: int, path: str = "src/A.java") -> RecordedFinding:
    return RecordedFinding(
        PassName.SECURITY,
        Finding(
            path=path,
            line=index + 1,
            category="security",
            claim=f"claim {index}",
            evidence_quote=f"quote {index}",
            criterion_id="SEC-1",
        ),
        Severity.CRITICAL,
    )


def test_a_hostile_ranking_cannot_push_a_finding_past_the_display_trim() -> None:
    # Within one severity class the order is the recorded index, not consolidation's. Otherwise a
    # grouping that lists the real finding last decides which findings survive `MAX_PRESENTED`.
    recorded = [_critical(i, path=f"src/F{i}.java") for i in range(MAX_PRESENTED + 6)]
    hostile = [[i] for i in reversed(range(len(recorded)))]
    presented = build_presented(recorded, hostile)
    shown = {item.lead.finding.claim for item in presented[:MAX_PRESENTED]}
    assert recorded[0].finding.claim in shown
    assert [item.lead_index for item in presented] == list(range(len(recorded)))


def test_a_hostile_merge_cannot_put_a_decoy_in_place_of_the_real_finding() -> None:
    # Two findings of one severity on one path: the lead is the lower recorded index, chosen in
    # code, so a grouping cannot replace a real finding's claim and quote with a decoy's.
    real, decoy = _critical(0), _critical(1)
    presented = build_presented([real, decoy], [[1, 0]])
    assert presented[0].lead is real
    assert presented[0].merged == (decoy,)


def test_a_merged_finding_keeps_its_own_criterion_in_the_report() -> None:
    other = RecordedFinding(
        PassName.PROJECT_RULES,
        Finding(
            path="src/A.java",
            line=9,
            category="project-rules",
            claim="same problem, other rule",
            evidence_quote="quote 9",
            criterion_id="RUL-2",
        ),
        Severity.MAJOR,
    )
    presented = build_presented([_critical(0), other], [[0, 1]])
    body = render_report(
        ReviewResult(
            passes=(),
            recorded=(_critical(0), other),
            presented=presented,
            omitted=0,
            blocking=True,
        )
    )
    assert "SEC-1" in body
    assert "RUL-2" in body
