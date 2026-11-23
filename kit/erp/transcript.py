"""The recorded MCP transcript the default `kit erp` replays.

The file is committed next to this module and loaded from the package, so a run needs no
app 18 and no network. It is a recording of one service-role session: the tool list that
principal is shown, one successful read, one permission refusal, and one paged read.
Replay looks a call up by tool name and canonical arguments and returns that body once.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from kit.core.contract import GatewayContract
from kit.erp.contract_check import match_error_shape
from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, LiveTool, canonical_arguments, normalize_arguments

__all__ = ["Recording", "load_recording"]

_STRICT = ConfigDict(extra="forbid", frozen=True)

# The recording is a few pages. A larger file is the wrong file.
_MAX_TRANSCRIPT_BYTES: Final = 256 * 1024


class _Tool(BaseModel):
    model_config = _STRICT

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=400)
    read_only: bool = Field(alias="readOnlyHint")


class _Call(BaseModel):
    model_config = _STRICT

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    arguments: dict[str, JsonValue]
    is_error: bool = Field(alias="isError")
    structured: dict[str, JsonValue] = Field(alias="structuredContent")


class _Server(BaseModel):
    model_config = _STRICT

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    version: str = Field(min_length=1, max_length=32)


class _Document(BaseModel):
    model_config = _STRICT

    source: str = Field(min_length=1, max_length=400)
    protocol_version: str = Field(alias="protocolVersion", pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
    server_info: _Server = Field(alias="serverInfo")
    tools: tuple[_Tool, ...] = Field(min_length=1)
    calls: tuple[_Call, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class Recording:
    """A validated transcript, indexed for one lookup per call."""

    server_name: str
    protocol_version: str
    tools: tuple[LiveTool, ...]
    _calls: Mapping[tuple[str, str], CallResult]

    def check_against(self, contract: GatewayContract) -> None:
        """The recording must be the service principal's view of this contract.

        A transcript that lists a write, drops a read, or stores an error the frozen
        shape would refuse is not replayed. That is `erp.replay_invalid`, not drift:
        the file is ours, and a live gateway was not asked.
        """
        try:
            names = [tool.name for tool in self.tools]
            expected = {tool.name for tool in contract.read_tools}
            if len(names) != len(set(names)) or set(names) != expected:
                raise ErpError(ErpCode.REPLAY_INVALID)
            if any(not tool.read_only for tool in self.tools):
                raise ErpError(ErpCode.REPLAY_INVALID)
            if self.server_name != contract.server.name:
                raise ErpError(ErpCode.REPLAY_INVALID)
            for (name, _), result in self._calls.items():
                if name not in expected:
                    raise ErpError(ErpCode.REPLAY_INVALID)
                if result.is_error:
                    match_error_shape(contract, result)
        except ErpError as err:
            if err.code is ErpCode.REPLAY_INVALID:
                raise
            raise ErpError(ErpCode.REPLAY_INVALID) from None

    def find(self, name: str, arguments: Mapping[str, JsonValue]) -> CallResult | None:
        """The recorded result, or `None` when this call was not recorded. One lookup."""
        key = (name, canonical_arguments(arguments))
        return self._calls.get(key)


def load_recording() -> Recording:
    """Load the committed transcript from the package. A bad file is `erp.replay_invalid`."""
    try:
        raw = files("kit.erp").joinpath("transcript.json").read_bytes()
    except (OSError, TypeError, UnicodeError):
        raise ErpError(ErpCode.REPLAY_INVALID) from None
    if len(raw) > _MAX_TRANSCRIPT_BYTES:
        raise ErpError(ErpCode.REPLAY_INVALID)
    try:
        data = json.loads(raw)
        document = _Document.model_validate(data)
    except (json.JSONDecodeError, UnicodeError, ValidationError):
        raise ErpError(ErpCode.REPLAY_INVALID) from None
    return _index(document)


def _index(document: _Document) -> Recording:
    calls: dict[tuple[str, str], CallResult] = {}
    for call in document.calls:
        try:
            arguments = normalize_arguments(call.arguments)
            key = (call.name, canonical_arguments(arguments))
            structured = normalize_arguments(call.structured)
        except ErpError:
            raise ErpError(ErpCode.REPLAY_INVALID) from None
        if key in calls:
            raise ErpError(ErpCode.REPLAY_INVALID)
        calls[key] = CallResult(is_error=call.is_error, structured=structured)
    tools = tuple(
        LiveTool(name=tool.name, read_only=tool.read_only, description=tool.description)
        for tool in document.tools
    )
    return Recording(
        server_name=document.server_info.name,
        protocol_version=document.protocol_version,
        tools=tools,
        _calls=calls,
    )
