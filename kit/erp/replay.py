"""Replay the recorded transcript. No process, no network, one lookup per call."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import JsonValue

from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, LiveTool
from kit.erp.transcript import Recording

__all__ = ["ReplayGateway"]


class ReplayGateway:
    """The recorded session, behind the same two methods as the stdio gateway."""

    def __init__(self, recording: Recording) -> None:
        self._recording = recording
        self._closed = False

    def list_tools(self) -> tuple[LiveTool, ...]:
        self._check_open()
        return self._recording.tools

    def call(self, name: str, arguments: Mapping[str, JsonValue]) -> CallResult:
        """Return the recorded body once. A call that was not recorded is not invented."""
        self._check_open()
        found = self._recording.find(name, arguments)
        if found is None:
            raise ErpError(ErpCode.REPLAY_MISSING)
        return found

    def close(self) -> None:
        self._closed = True

    def _check_open(self) -> None:
        if self._closed:
            raise ErpError(ErpCode.REPLAY_MISSING)
