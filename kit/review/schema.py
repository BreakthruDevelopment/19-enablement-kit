"""The `pr-review` wire schema: what a pass may say, bounded, with nothing a model could grade.

Two absences are the design. There is **no `severity`**: severity is a property of the criterion a
finding fails and code looks it up, so there is no model-supplied value left to protect. There is
**no `verdict`** either: it was recorded-but-unused once the comparison it existed for died, and a
vestigial field that four rounds of attacks aimed at is an invitation to start using it again.

A model that returns either anyway is not rejected for it -- the spec says the value is
*discarded* -- so `parse_pass_output` drops both keys before validation. Everything else is
`extra="forbid"`.

The findings bound is **50** while the per-pass cap in code is **40**. The gap is deliberate: a 41st
finding then arrives as a schema-valid response that code rejects as overflow, where a schema bound
of 40 would make the same event a parse failure and the two could not be told apart. A parse
failure is a *failed* pass (nothing usable came back, no `blocking`); an overflow is a *rejected*
pass (something came back and was adversarial, so `blocking`).
"""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Final, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError


class PassOverflow(Exception):
    """A well-shaped reply whose `findings` list is longer than the schema allows.

    The schema's bound (50) sits deliberately above the per-pass cap (40) so a 41st finding
    arrives schema-valid and code can reject the pass as overflow rather than see a parse failure.
    A 51st would fall off that design: pydantic would refuse it, `parse_pass_output` would report
    "nothing parseable came back", and the pass would *fail* -- which posts nothing at all. One
    pass talked into listing nits would then silence a run in which another pass recorded a
    critical finding, which is the injection-to-silence attack the per-pass cap exists to defeat.
    So the over-bound case is raised here and rejected like any other overflow.
    """


__all__ = [
    "MAX_FINDINGS_PER_PASS",
    "MAX_FINDINGS_SCHEMA",
    "Category",
    "ConsolidationOutput",
    "Finding",
    "Group",
    "PassOutput",
    "parse_consolidation_output",
    "parse_pass_output",
]

MAX_FINDINGS_PER_PASS: Final = 40
MAX_FINDINGS_SCHEMA: Final = 50  # deliberately above the cap; see the module docstring

Category = Literal[
    "correctness", "security", "project-rules", "tests", "performance", "maintainability"
]

_STRICT = ConfigDict(extra="forbid", frozen=True)

# Keys a model may send that code never reads. They are dropped, not refused.
_DISCARDED: Final = ("severity", "verdict")


class Finding(BaseModel):
    """One thing a pass says is wrong, with the line it is about quoted."""

    model_config = _STRICT

    path: str = Field(min_length=1, max_length=300)
    line: int = Field(ge=1, le=1_000_000)
    category: Category
    claim: str = Field(min_length=1, max_length=600)
    # Checked against the diff in code. 400 characters is a line or three, not the file.
    evidence_quote: str = Field(min_length=1, max_length=400)
    # Not pattern-constrained: whether it names a criterion in the raising pass's own file is a
    # lookup in code, and a malformed id is a *rejected* pass, not a parse failure.
    criterion_id: str = Field(min_length=1, max_length=40)


class PassOutput(BaseModel):
    model_config = _STRICT

    findings: list[Finding] = Field(max_length=MAX_FINDINGS_SCHEMA)
    passes_run: list[Annotated[str, StringConstraints(max_length=40)]] = Field(
        default_factory=list, max_length=8
    )


class Group(BaseModel):
    """Findings the consolidation pass says are one problem, by index into the recorded set."""

    model_config = _STRICT

    members: list[Annotated[int, Field(ge=0, le=100_000)]] = Field(min_length=1, max_length=200)


class ConsolidationOutput(BaseModel):
    """The consolidation pass's answer: an order and a grouping, never a removal."""

    model_config = _STRICT

    groups: list[Group] = Field(max_length=200)


_FENCE = re.compile(r"\A```[A-Za-z]*\n(.*)\n```\Z", re.DOTALL)


def _refuse_constant(_name: str) -> NoReturn:
    # `NaN` and `Infinity` are not JSON; Python's decoder accepts them unless told not to.
    raise ValueError("not JSON")


def _load_object(text: str) -> dict[str, Any] | None:
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        data = json.loads(body, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


def parse_pass_output(text: str) -> PassOutput | None:
    """The pass's answer, or `None` when nothing parseable came back (a *failed* pass)."""
    data = _load_object(text)
    if data is None:
        return None
    findings_value = data.get("findings")
    if isinstance(findings_value, list) and len(findings_value) > MAX_FINDINGS_SCHEMA:
        raise PassOverflow
    for key in _DISCARDED:
        data.pop(key, None)
    findings = data.get("findings")
    if isinstance(findings, list):
        for item in findings:
            if isinstance(item, dict):
                for key in _DISCARDED:
                    item.pop(key, None)
    try:
        return PassOutput.model_validate(data)
    except ValidationError:
        return None


def parse_consolidation_output(text: str) -> ConsolidationOutput | None:
    data = _load_object(text)
    if data is None:
        return None
    try:
        return ConsolidationOutput.model_validate(data)
    except ValidationError:
        return None
