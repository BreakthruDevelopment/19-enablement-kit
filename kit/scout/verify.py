"""Quote verification: a finding is kept only if the sandbox served the bytes it quotes.

A model's answer is a claim. For each finding this module asks, in code and against the text the
sandbox returned **in this run** (not by reading the file again, which would verify against a file
that may have changed, and would charge the run's byte cap twice):

1. every file it cites is a file the sandbox served -- a finding about a file the scout never saw
   is dropped, whatever the quote says;
2. the quote is long enough to mean something and is a substring of one of the files it cites;
3. nothing in it is secret-shaped.

A dropped finding is recorded with a fixed reason and its position in the reply. It is **not**
recorded with its title, its files or its quote: those are model text, and the model's text is what
a hostile file is trying to write.

The brief's other lists (`modules`, `risks`, `recommended_order`) carry no quote to check. They are
held to the one rule that needs no evidence: nothing secret-shaped.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from kit.scout.logline import log_line
from kit.scout.schema import Finding, ScoutBrief
from kit.scout.secrets import looks_secret

__all__ = ["MIN_QUOTE_CHARS", "DropReason", "Dropped", "verify_brief"]

# A quote of `{` is in every file. Twelve characters is a line fragment a reader can find.
MIN_QUOTE_CHARS: Final = 12

log = logging.getLogger("kit.scout")


class DropReason(StrEnum):
    UNSERVED_FILE = "unserved_file"
    QUOTE_NOT_IN_CITED_FILES = "quote_not_in_cited_files"
    QUOTE_TOO_SHORT = "quote_too_short"
    SECRET_SHAPED = "secret_shaped"  # noqa: S105 -- a reason code, not a secret


@dataclass(frozen=True, slots=True)
class Dropped:
    """A reply entry that did not survive verification. Fixed words and a position only."""

    section: str
    index: int
    reason: DropReason

    def as_dict(self) -> dict[str, object]:
        return {"section": self.section, "index": self.index, "reason": self.reason.value}


def _normalise(path: str) -> str:
    cleaned = path.strip()
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned


def _check(finding: Finding, served: Mapping[str, str]) -> tuple[Finding | None, DropReason | None]:
    files = list(dict.fromkeys(_normalise(name) for name in finding.files))
    if any(name not in served for name in files):
        return None, DropReason.UNSERVED_FILE
    quote = finding.evidence_quote.strip()
    if len(quote) < MIN_QUOTE_CHARS:
        return None, DropReason.QUOTE_TOO_SHORT
    if not any(quote in served[name] for name in files):
        return None, DropReason.QUOTE_NOT_IN_CITED_FILES
    texts = (finding.title, quote, finding.why_it_matters, *files)
    if any(looks_secret(text) for text in texts):
        return None, DropReason.SECRET_SHAPED
    return finding.model_copy(update={"files": files, "evidence_quote": quote}), None


def _drop(dropped: list[Dropped], section: str, index: int, reason: DropReason) -> None:
    dropped.append(Dropped(section, index, reason))
    # A position and a fixed word. Never the entry: it is the model's text. `log_line` checks
    # that for us, so a later caller cannot widen this by passing something else.
    log.warning(
        "%s",
        log_line("scout.entry_dropped", section=section, index=index, reason=reason.value),
    )


def verify_brief(
    brief: ScoutBrief, served: Mapping[str, str]
) -> tuple[ScoutBrief, tuple[Dropped, ...]]:
    """`brief` with every entry that cannot be verified removed, and what was removed."""
    dropped: list[Dropped] = []
    findings: list[Finding] = []
    for index, finding in enumerate(brief.findings):
        kept, reason = _check(finding, served)
        if kept is None and reason is not None:
            _drop(dropped, "findings", index, reason)
        elif kept is not None:
            findings.append(kept)
    modules = []
    for index, module in enumerate(brief.modules):
        if looks_secret(module.name) or looks_secret(module.responsibility):
            _drop(dropped, "modules", index, DropReason.SECRET_SHAPED)
        else:
            modules.append(module)
    risks = []
    for index, risk in enumerate(brief.risks):
        if looks_secret(risk):
            _drop(dropped, "risks", index, DropReason.SECRET_SHAPED)
        else:
            risks.append(risk)
    order = []
    for index, step in enumerate(brief.recommended_order):
        if looks_secret(step):
            _drop(dropped, "recommended_order", index, DropReason.SECRET_SHAPED)
        else:
            order.append(step)
    cleaned = brief.model_copy(
        update={
            "findings": findings,
            "modules": modules,
            "risks": risks,
            "recommended_order": order,
        }
    )
    return cleaned, tuple(dropped)
