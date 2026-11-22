"""The criteria files: parsed strictly, each declaring its own severity."""

from __future__ import annotations

import pytest
from review_support import load_demo_criteria

from kit.review import BLOCKING_SEVERITIES, FINDING_PASSES, PassName, ReviewError, Severity
from kit.review.criteria import parse_criteria

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
