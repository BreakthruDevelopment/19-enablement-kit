"""One scout run: explore through the sandbox, ask a model once, verify, report what was not read.

    sandbox ──> explore ──> prompt (capped) ──> ONE model call ──> parse ──> verify ──> brief
                   │                                                            │
                   └─ refusals, caps, withheld files ──────────> coverage ──────┘

**The model is called once and decides nothing about the filesystem.** What to read next is the
exploration's strategy (`kit.scout.explore`), written down as code, so that a run is the same run
every time and the recorded reply in CI means something. The model reads what the sandbox served,
and says what it makes of it.

**Coverage is the code's, not the model's.** `files_total` is the sandbox's own count of what it
would serve. `files_read` is what it did serve. `unread_reason` is assembled here from fixed words:
the sandbox's refusal codes, kinds of file and counts. It is never assembled from a path, from the
pattern a deny-list rule matched, or from anything the model wrote -- which is what lets it say
*that* a part of the tree was refused without saying *what* was refused. A brief that named the
refused path would hand a reader the very thing the deny list exists to keep out of the output.

The budget is app 17's `Budget`: one turn, because there is one call. `kit scout` wires a recorded
reply by default, so CI and a demo make no model call.
"""

from __future__ import annotations

import logging
import secrets as stdlib_secrets
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Final

from agent_container.core.budget import Budget
from agent_container.core.messages import Message, ModelRequest
from agent_container.core.provider import ModelProvider

from kit.core.errors import ErrorCode
from kit.core.principals import Capability, assert_can
from kit.core.sandbox import Sandbox
from kit.scout.errors import ScoutError, ScoutReason
from kit.scout.explore import Explorer, Step
from kit.scout.prompt import MAX_OUTPUT_TOKENS, build_prompt
from kit.scout.schema import Coverage, ScoutBrief, parse_brief
from kit.scout.secrets import looks_secret
from kit.scout.verify import Dropped, verify_brief

__all__ = ["ScoutResult", "default_budget", "run_scout"]

log = logging.getLogger("kit.scout")

_USABLE_STOPS: Final = frozenset({"end_turn", "stop_sequence"})
_REASON_LIMIT: Final = 1_200
_TRUNCATED: Final = " [truncated]"

_UNREAD_PHRASES: Final = {
    "not_reached": "Not reached before the cap",
    "not_referenced": "Not named by any build file, descriptor or class",
    "not_readable": "Could not be read",
}


def default_budget() -> Budget:
    """One call. The prompt is capped at 60 KB, about 15k tokens, plus the reply."""
    return Budget(max_turns=1, max_tokens=60_000, max_seconds=300.0)


@dataclass(frozen=True, slots=True)
class ScoutResult:
    """The brief, and everything a reader needs to check how it was made."""

    brief: ScoutBrief
    steps: tuple[Step, ...]
    dropped: tuple[Dropped, ...]
    refusals: tuple[tuple[ErrorCode, str], ...]
    served: tuple[str, ...]
    withheld: int
    stopped_by: ErrorCode | None
    not_shown: int

    def as_dict(self) -> dict[str, object]:
        return {
            "brief": self.brief.model_dump(),
            "steps": [step.as_dict() for step in self.steps],
            "dropped": [item.as_dict() for item in self.dropped],
            "refusals": [{"code": code.value, "category": cat} for code, cat in self.refusals],
            "withheld": self.withheld,
        }


def _counts(by_kind: dict[Any, int]) -> str:
    order = ("java", "xml", "jsp", "sql", "properties", "other")
    return ", ".join(f"{by_kind[kind]} {kind}" for kind in order if kind in by_kind)


def build_unread_reason(explorer: Explorer, *, dropped: tuple[Dropped, ...], not_shown: int) -> str:
    """The coverage reason, from counts, fixed phrases and sandbox refusal codes. No path."""
    index = set(explorer.files)
    read = len(index & explorer.served.keys())
    parts = [f"Read {read} of {len(index)} files."]
    if explorer.stopped_by is not None:
        parts.append(
            f"Exploration stopped when the sandbox refused a read with {explorer.stopped_by.value}."
        )
    unread = explorer.unread()
    for key in ("not_reached", "not_referenced", "not_readable"):
        if key in unread:
            parts.append(f"{_UNREAD_PHRASES[key]}: {_counts(unread[key])}.")
    refusals = explorer.sandbox_refusals()
    if refusals:
        named = ", ".join(f"{code.value} ({category})" for code, category in refusals)
        parts.append(f"The sandbox refused part of the tree: {named}.")
    if explorer.withheld:
        parts.append(
            f"{explorer.withheld} file(s) were withheld because their content looked like a "
            "credential."
        )
    if dropped:
        parts.append(
            f"{len(dropped)} entr(ies) in the model's reply were dropped because they could not "
            "be verified against the files the sandbox served."
        )
    if not_shown:
        parts.append(f"{not_shown} item(s) of evidence did not fit the model's input cap.")
    if len(parts) == 1 and read == len(index):
        parts.append("Nothing was left unread and the sandbox refused nothing.")
    text = " ".join(parts)
    if len(text) > _REASON_LIMIT:
        text = text[: _REASON_LIMIT - len(_TRUNCATED)] + _TRUNCATED
    return text


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def assert_brief_clean(brief: ScoutBrief) -> None:
    """The last gate: no string anywhere in the brief is secret-shaped."""
    if any(looks_secret(text) for text in _strings(brief.model_dump())):
        raise ScoutError(ScoutReason.BRIEF_REFUSED)


async def run_scout(
    sandbox: Sandbox,
    provider: ModelProvider,
    *,
    budget: Budget | None = None,
    nonce: str | None = None,
) -> ScoutResult:
    """Explore `sandbox`'s one root and return a verified brief.

    Raises `KitError` (before anything is read) if the principal may not run a scout, and
    `ScoutError` if no brief can be produced. A model is called at most once.
    """
    assert_can(sandbox.principal, Capability.RUN_SCOUT)
    explorer = Explorer(sandbox)
    explorer.explore()
    served = explorer.served
    if not served:
        raise ScoutError(ScoutReason.NOTHING_READ)

    run_budget = budget if budget is not None else default_budget()
    run_budget.start()
    prompt = build_prompt(explorer, nonce if nonce is not None else stdlib_secrets.token_hex(8))
    if run_budget.check() is not None:
        raise ScoutError(ScoutReason.BUDGET_EXHAUSTED)
    request = ModelRequest(
        system=prompt.system,
        messages=(Message.user_text(prompt.user),),
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    try:
        response = await provider.converse(request)
    except Exception:  # a throttle, a timeout, an exhausted recording: all "nothing came back"
        log.warning("scout.provider_error")
        raise ScoutError(ScoutReason.PROVIDER_ERROR) from None
    run_budget.record_turn(response.usage.total)
    if response.stop_reason not in _USABLE_STOPS:
        raise ScoutError(ScoutReason.UNUSABLE_STOP_REASON)
    reply = parse_brief(response.text)
    if reply is None:
        raise ScoutError(ScoutReason.REPLY_NOT_PARSEABLE)

    verified, dropped = verify_brief(reply, served)
    coverage = Coverage(
        files_total=len(explorer.files),
        files_read=len(set(explorer.files) & served.keys()),
        unread_reason=build_unread_reason(explorer, dropped=dropped, not_shown=prompt.not_shown),
    )
    brief = ScoutBrief(
        findings=verified.findings,
        modules=verified.modules,
        risks=verified.risks,
        recommended_order=verified.recommended_order,
        coverage=coverage,
    )
    assert_brief_clean(brief)
    log.info(
        "scout.done files_read=%d files_total=%d findings=%d dropped=%d",
        coverage.files_read,
        coverage.files_total,
        len(brief.findings),
        len(dropped),
    )
    return ScoutResult(
        brief=brief,
        steps=explorer.steps,
        dropped=dropped,
        refusals=explorer.sandbox_refusals(),
        served=tuple(sorted(served)),
        withheld=explorer.withheld,
        stopped_by=explorer.stopped_by,
        not_shown=prompt.not_shown,
    )
