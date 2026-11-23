"""A stdio MCP client for the gateway named in `gateway.command`.

One process, started here, stopped by the PID `Popen` recorded. The gateway is an
external program. Nothing in this module imports app 18. Replay is the other
implementation; this one runs only when a call asks to go live.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import shutil
import subprocess
import threading
import time
from collections.abc import Mapping
from typing import IO, Final

from pydantic import JsonValue

from kit import __version__
from kit.core.config import GatewayConfig
from kit.core.contract import GatewayContract
from kit.erp.errors import ErpCode, ErpError
from kit.erp.models import CallResult, LiveTool
from kit.erp.protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    notification,
    parse_call_result,
    parse_initialize,
    parse_response,
    parse_tool_list,
    request,
)

__all__ = ["StdioGateway"]

_CLOSE_WAIT: Final = 2.0


def _drain(fd: int) -> None:
    """Read a stderr pipe until it closes, and keep none of it.

    A full pipe would stall the gateway on its next log line. The bytes are the
    gateway's own diagnostics and are not copied into an error or a log.
    """
    while True:
        try:
            block = os.read(fd, 65536)
        except OSError:
            return
        if block == b"":
            return


class StdioGateway:
    """One live gateway process and the JSON-RPC session on its stdio."""

    def __init__(
        self,
        config: GatewayConfig,
        contract: GatewayContract,
        *,
        timeout: float = 10.0,
    ) -> None:
        if timeout <= 0:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        self._command = config.command
        self._args = config.args
        self._server_name = contract.server.name
        self._timeout = timeout
        self._proc: subprocess.Popen[bytes] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._buffer = b""
        self._ids = 1
        self._ready = False
        self._returncode: int | None = None

    @property
    def returncode(self) -> int | None:
        """The exit status after `close`, or `None` when the process was not reaped."""
        return self._returncode

    def start(self) -> None:
        """Spawn the gateway and complete `initialize`. Closes the process on any failure."""
        if self._ready:
            return
        try:
            self._spawn()
            self._initialize()
            self._ready = True
        finally:
            if not self._ready:
                self.close()

    def list_tools(self) -> tuple[LiveTool, ...]:
        result = self._exchange("tools/list", {})
        return parse_tool_list(result)

    def call(self, name: str, arguments: Mapping[str, JsonValue]) -> CallResult:
        """Send one `tools/call` and return its result. No second attempt."""
        result = self._exchange(
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
        )
        return parse_call_result(result)

    def close(self) -> None:
        """Stop the process this object started, by the PID it recorded. Idempotent."""
        self._ready = False
        proc = self._proc
        if proc is None:
            return
        self._proc = None
        stdin = proc.stdin
        if stdin is not None:
            with contextlib.suppress(OSError):
                stdin.close()
        if proc.poll() is None:
            try:
                proc.wait(timeout=_CLOSE_WAIT)
            except subprocess.TimeoutExpired:
                # `Popen.kill` signals the PID `Popen` created. This object started it.
                proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=_CLOSE_WAIT)
        thread = self._stderr_thread
        self._stderr_thread = None
        if thread is not None:
            thread.join(timeout=_CLOSE_WAIT)
        self._returncode = proc.returncode

    def _spawn(self) -> None:
        resolved = shutil.which(self._command)
        if resolved is None:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        argv = [resolved, *self._args]
        try:
            proc = subprocess.Popen(  # noqa: S603
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except (OSError, ValueError):
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE) from None
        self._proc = proc
        stderr = proc.stderr
        if stderr is None or proc.stdin is None or proc.stdout is None:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        thread = threading.Thread(target=_drain, args=(stderr.fileno(),), daemon=True)
        thread.start()
        self._stderr_thread = thread

    def _initialize(self) -> None:
        result = self._exchange(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "kit", "version": __version__},
            },
        )
        parse_initialize(result, server_name=self._server_name)
        self._write(notification("notifications/initialized"))

    def _exchange(self, method: str, params: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        if self._proc is None and method != "initialize":
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        # `initialize` is the first exchange, sent before `_ready` is set. Later calls
        # require a process that is still the one `start` spawned.
        if method != "initialize" and not self._ready:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        try:
            result = self._request(request(method, self._next_id(), params))
        except ErpError:
            self.close()
            raise
        if result is None:
            self.close()
            raise ErpError(ErpCode.PROTOCOL)
        return result

    def _next_id(self) -> int:
        value = self._ids
        self._ids += 1
        return value

    def _request(self, payload: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
        """Write one message. Return the result object, or `None` for a notification."""
        self._write(payload)
        if "id" not in payload:
            return None
        request_id = payload["id"]
        if isinstance(request_id, bool) or not isinstance(request_id, int):
            raise ErpError(ErpCode.PROTOCOL)
        return parse_response(self._read_line(), request_id)

    def _write(self, payload: Mapping[str, JsonValue]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        try:
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise ErpError(ErpCode.BAD_ARGUMENTS) from None
        if len(encoded) + 1 > MAX_MESSAGE_BYTES:
            raise ErpError(ErpCode.BAD_ARGUMENTS)
        try:
            _write_all(proc.stdin, encoded + b"\n")
        except OSError:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE) from None

    def _read_line(self) -> str:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        fd = proc.stdout.fileno()
        deadline = time.monotonic() + self._timeout
        while True:
            while b"\n" not in self._buffer:
                if len(self._buffer) > MAX_MESSAGE_BYTES:
                    raise ErpError(ErpCode.PROTOCOL)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ErpError(ErpCode.GATEWAY_TIMEOUT)
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    raise ErpError(ErpCode.GATEWAY_TIMEOUT)
                try:
                    block = os.read(fd, 65536)
                except OSError:
                    raise ErpError(ErpCode.GATEWAY_UNAVAILABLE) from None
                if block == b"":
                    raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
                self._buffer += block
            line, _, self._buffer = self._buffer.partition(b"\n")
            if line.strip() == b"":
                continue
            if len(line) > MAX_MESSAGE_BYTES:
                raise ErpError(ErpCode.PROTOCOL)
            try:
                return line.decode("utf-8")
            except UnicodeDecodeError:
                raise ErpError(ErpCode.PROTOCOL) from None


def _write_all(stream: IO[bytes], payload: bytes) -> None:
    view = memoryview(payload)
    sent = 0
    while sent < len(view):
        wrote = stream.write(view[sent:])
        if not wrote:
            raise ErpError(ErpCode.GATEWAY_UNAVAILABLE)
        sent += wrote
    stream.flush()
