"""Resume: replay a session's recorded turns into app 17's loop. No model call.

The loop is what makes the transcript sendable. A reply that ends the run can still carry a tool
call; app 17 answers it with a synthetic result (slice 17.3) because Bedrock rejects a transcript
that leaves a `ToolUseBlock` unanswered, and resuming a session sends that transcript. This module
does not invent that result and does not call Bedrock. `ReplayProvider` hands back the recorded
replies, and a recorded tool result is returned instead of running the tool again, so a resume
costs nothing and writes nothing.

What "resend" means here: each model request carries the messages so far. The second request is
the first turn's transcript, and `RunResult.messages` is the transcript a further continuation
would send. Both are checked with the same pairing rule Bedrock enforces and with `build_request`,
which is the Converse translation and does not touch the network.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agent_container.core.bedrock import build_request
from agent_container.core.budget import Budget
from agent_container.core.errors import (
    InputTooLarge,
    MalformedModelResponse,
    ReplayExhausted,
    UnrecognizedStopReason,
)
from agent_container.core.loop import AgentLoop, RunState
from agent_container.core.messages import (
    Message,
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from agent_container.core.provider import ModelProvider
from agent_container.core.replay import ReplayProvider
from agent_container.core.tool import (
    AnyTool,
    Effect,
    ErrorCategory,
    Identity,
    Tool,
    ToolContext,
    ToolResult,
)
from pydantic import BaseModel, ConfigDict, JsonValue

from kit.core.principals import Principal
from kit.session.errors import SessionError, SessionReason
from kit.session.models import Session, ToolResultRecord, Turn
from kit.session.store import SessionStore

__all__ = ["ResumeResult", "resume", "transcript_is_sendable"]


class _AnyArgs(BaseModel):
    """Recorded tool input is data. It is validated only to satisfy the tool contract."""

    model_config = ConfigDict(extra="allow", frozen=True)


class _RecordedTool(Tool[_AnyArgs]):
    """Returns the result stored for a call. The tool body from the original run does not run."""

    def __init__(self, name: str, results: Mapping[str, ToolResult]) -> None:
        self._name = name
        self._results = dict(results)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Replay a recorded tool result. The tool is not run again."

    @property
    def effect(self) -> Effect:
        return Effect.READ

    @property
    def input_model(self) -> type[_AnyArgs]:
        return _AnyArgs

    async def run(self, args: _AnyArgs, ctx: ToolContext) -> ToolResult:
        found = self._results.get(ctx.tool_use_id)
        if found is None:
            # The id is model-chosen, so it stays out of the message. A consistent recording
            # never reaches this: resume pairs every dispatched call before the loop starts.
            return ToolResult.error(ErrorCategory.INTERNAL, "no recorded result for this call")
        return found


class _ReplayLoop(AgentLoop):
    """Stops once the recorded replies have been played, including a trailing tool round.

    A session may end on `tool_use` -- a fork's prefix does. The loop would otherwise ask for
    another reply, and there is nothing recorded to give it. Stopping here is what keeps resume
    from calling a model.
    """

    def __init__(
        self,
        provider: ModelProvider,
        tools: Sequence[AnyTool],
        *,
        turns: int,
        system_prompt: str,
        fence_nonce: str,
        identity: Identity,
    ) -> None:
        super().__init__(
            provider,
            tools,
            system_prompt=system_prompt,
            fence_nonce=fence_nonce,
            identity=identity,
        )
        self._turns = turns

    async def should_stop(self, state: RunState) -> str | None:
        if state.turn >= self._turns:
            return "recorded turns replayed"
        return None


@dataclass(frozen=True, slots=True)
class ResumeResult:
    """What a replay produced. `requests` are the transcripts that were sent, one per turn."""

    session_id: str
    end_reason: str
    stop_reason: str | None
    turns_replayed: int
    input_tokens: int
    output_tokens: int
    requests: tuple[ModelRequest, ...]
    messages: tuple[Message, ...]


def transcript_is_sendable(messages: Sequence[Message]) -> bool:
    """Whether Bedrock could accept `messages`: every tool call is answered exactly once.

    An assistant message while a call is still open is the shape Bedrock rejects, and so is a
    result for a call that was not made. Empty transcripts are not sendable.
    """
    if not messages:
        return False
    pending: set[str] = set()
    answered: set[str] = set()
    for message in messages:
        if message.role == "assistant" and pending:
            return False
        for block in message.content:
            if isinstance(block, ToolUseBlock):
                if message.role != "assistant" or not block.id:
                    return False
                if block.id in pending or block.id in answered:
                    return False
                pending.add(block.id)
            elif isinstance(block, ToolResultBlock):
                if message.role != "user" or block.tool_use_id not in pending:
                    return False
                pending.discard(block.tool_use_id)
                answered.add(block.tool_use_id)
    return not pending


async def resume(store: SessionStore, principal: Principal, session_id: str) -> ResumeResult:
    """Replay `session_id` through app 17's loop on its recorded replies.

    Refuses a session the principal does not own before any replay. Does not write the store and
    does not construct a Bedrock client.
    """
    session = store.get(principal, session_id)
    if not session.turns:
        raise SessionError(SessionReason.EMPTY)
    try:
        return await _replay(session)
    except (InputTooLarge, MalformedModelResponse, ReplayExhausted, UnrecognizedStopReason):
        raise SessionError(SessionReason.DIVERGED) from None


async def _replay(session: Session) -> ResumeResult:
    opening = session.turns[0]
    user = opening.user_message
    system = opening.system
    nonce = opening.fence_nonce
    if user is None or system is None or nonce is None:
        raise SessionError(SessionReason.INVALID)
    replies = [_reply(turn) for turn in session.turns]
    provider = ReplayProvider(replies)
    loop = _ReplayLoop(
        provider,
        _tools(session),
        turns=len(session.turns),
        system_prompt=system,
        fence_nonce=nonce,
        identity=Identity(subject=session.principal),
    )
    # One more token than the recording billed, so the last recorded call is not refused for
    # having spent exactly the cap. `max_turns` is what stops a trailing tool round from asking
    # for a reply that was never recorded.
    spent = session.budget_spent
    budget = Budget(
        max_turns=len(session.turns),
        max_tokens=spent.input_tokens + spent.output_tokens + 1,
        max_seconds=30,
    )
    result = await loop.run(user, budget)
    if (
        provider.remaining != 0
        or not provider.requests
        or result.turns_used != len(session.turns)
        or result.input_tokens != spent.input_tokens
        or result.output_tokens != spent.output_tokens
    ):
        raise SessionError(SessionReason.DIVERGED)
    for request in provider.requests:
        _assert_resendable(request.system, request.messages)
    _assert_resendable(provider.requests[-1].system, result.messages)
    return ResumeResult(
        session_id=session.id,
        end_reason=result.end_reason.value,
        stop_reason=result.stop_reason,
        turns_replayed=result.turns_used,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        requests=tuple(provider.requests),
        messages=result.messages,
    )


def _reply(turn: Turn) -> ModelResponse:
    return ModelResponse.of(
        turn.text,
        stop_reason=turn.stop_reason,
        tool_uses=[_tool_use(use.id, use.name, use.input) for use in turn.tool_uses],
        usage=Usage(turn.usage.input_tokens, turn.usage.output_tokens),
    )


def _tool_use(tool_id: str, name: str, tool_input: Mapping[str, JsonValue]) -> ToolUseBlock:
    return ToolUseBlock(tool_id, name, dict(tool_input))


def _tools(session: Session) -> tuple[_RecordedTool, ...]:
    by_name: dict[str, dict[str, ToolResult]] = {}
    for turn in session.turns:
        if turn.stop_reason != StopReason.TOOL_USE:
            continue
        recorded = {result.tool_use_id: result for result in turn.tool_results}
        for use in turn.tool_uses:
            by_name.setdefault(use.name, {})[use.id] = _stored_result(recorded[use.id])
    return tuple(_RecordedTool(name, results) for name, results in by_name.items())


def _stored_result(record: ToolResultRecord) -> ToolResult:
    return ToolResult(
        content=record.content,
        is_error=record.is_error,
        error_category=record.error_category,
        is_retryable=record.is_retryable,
    )


def _assert_resendable(system: str, messages: Sequence[Message]) -> None:
    if not transcript_is_sendable(messages):
        raise SessionError(SessionReason.UNSENDABLE)
    try:
        # The model id is a label in the built request. Nothing is sent.
        build_request("kit-session", ModelRequest(system=system, messages=tuple(messages)))
    except ValueError:
        raise SessionError(SessionReason.UNSENDABLE) from None
