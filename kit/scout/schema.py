"""The `scout-brief` schema: what the model may say, and the brief that leaves the scout.

**This `severity` is model-supplied, and that is deliberate.** It is not the reviewer's rule applied
badly. `kit.review` assigns severity in code from the criterion a finding fails, because the
reviewer's verdict gates a merge and a model that could grade its own findings could grade its way
to silence. A brief gates nothing: a person reads it, so a mis-graded finding costs a reader a
moment and corrupts no verdict. Do not "fix" this by importing the reviewer's rule -- there is no
criterion here to take a severity from, and nothing here for a severity to protect. What a model
cannot do is cite ground it did not read: that is checked in `kit.scout.verify`, in code.

Every list and string is bounded. A reply over a bound is a reply that does not parse -- never one
that is trimmed to fit, because a trimmed brief looks complete.

`coverage` is mandatory in the reply, so a model that says nothing about what it left unread has
not answered. What leaves the scout carries the **code's** coverage, though: the counts come from
the sandbox, and the reason is built from fixed codes. A model's own account of what it covered is a
claim, and a brief that repeated it would let a hostile file talk the reader into believing the
scout had seen more than it had.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Final, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

__all__ = [
    "MAX_FINDINGS",
    "Coverage",
    "Finding",
    "Module",
    "ScoutBrief",
    "Severity",
    "parse_brief",
]

MAX_FINDINGS: Final = 20

Severity = Literal["high", "medium", "low"]

_STRICT = ConfigDict(extra="forbid", frozen=True)

Line = Annotated[str, StringConstraints(min_length=1, max_length=300)]


class Finding(BaseModel):
    """One problem the scout names, with the files it is in and a line quoted from them."""

    model_config = _STRICT

    title: str = Field(min_length=1, max_length=120)
    severity: Severity
    # Nine classes share one of the planted problems, so the bound is above nine.
    files: list[Annotated[str, StringConstraints(min_length=1, max_length=300)]] = Field(
        min_length=1, max_length=16
    )
    # Checked against what the sandbox served, in code. 400 characters is a line or three.
    evidence_quote: str = Field(min_length=1, max_length=400)
    why_it_matters: str = Field(min_length=1, max_length=600)


class Module(BaseModel):
    model_config = _STRICT

    name: str = Field(min_length=1, max_length=80)
    responsibility: str = Field(min_length=1, max_length=300)


class Coverage(BaseModel):
    """What the scout read and what it did not. Mandatory: unexplored ground is named."""

    model_config = _STRICT

    files_total: int = Field(ge=0, le=1_000_000)
    files_read: int = Field(ge=0, le=1_000_000)
    # Never empty: "nothing was left unread" is a statement, and it is made in words.
    unread_reason: str = Field(min_length=1, max_length=1_200)


class ScoutBrief(BaseModel):
    model_config = _STRICT

    findings: list[Finding] = Field(max_length=MAX_FINDINGS)
    modules: list[Module] = Field(max_length=30)
    risks: list[Line] = Field(max_length=15)
    recommended_order: list[Line] = Field(max_length=15)
    coverage: Coverage


def _refuse_constant(_name: str) -> NoReturn:
    # `NaN` and `Infinity` are not JSON; Python's decoder accepts them unless told not to.
    raise ValueError("not JSON")


def parse_brief(text: str) -> ScoutBrief | None:
    """The reply as a brief, or `None` if it is not one. Nothing from the reply is echoed."""
    body = text.strip()
    if body.startswith("```"):
        lines = body.split("\n")
        if len(lines) >= 3 and lines[-1].strip() == "```":
            body = "\n".join(lines[1:-1])
    try:
        data: Any = json.loads(body, parse_constant=_refuse_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return ScoutBrief.model_validate(data)
    except ValidationError:
        return None
