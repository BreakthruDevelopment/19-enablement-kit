"""Configuration: the sandbox's caps, and the external gateway command.

Config is a TOML file validated at the boundary by typed models. Unknown keys are refused rather
than ignored, so a typo in a cap is an error instead of a silently generous sandbox.

The gateway is **an external process named here**, never an import: app 19 does not check out or
import app 18. `gateway.command` defaults to `p2p-erp` on `PATH`, and `gateway.live` stays false so
the default run replays the recorded transcript and needs no app 18 anywhere.

A validation failure is reported as a schema-derived field path and a fixed problem token. A
pydantic message would otherwise quote the offending value, which for an unknown key *is* the key
the file supplied -- parsed input, straight into a log line. `_KNOWN_FIELDS` is derived from the
models themselves, and anything outside it is reported as `unrecognized`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from kit.core.errors import ErrorCode, KitError, safe_token

__all__ = ["Config", "GatewayConfig", "SandboxLimits"]

_STRICT = ConfigDict(extra="forbid", frozen=True)

DEFAULT_CONFIG_FILENAME: Final = "kit.toml"


class SandboxLimits(BaseModel):
    """The sandbox's three caps. Exceeding one is a `business` error, never a truncated read."""

    model_config = _STRICT

    max_file_bytes: int = Field(default=512 * 1024, gt=0)
    max_run_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    max_files: int = Field(default=2_000, gt=0)


class GatewayConfig(BaseModel):
    """How to reach app 18's `p2p-erp` gateway, if a run is asked to reach it at all."""

    model_config = _STRICT

    command: str = Field(default="p2p-erp", min_length=1, max_length=256)
    args: tuple[str, ...] = ()
    # Replay is the default everywhere: CI and every demo run at zero cost on the recorded
    # transcript. Only an explicit flag reaches a live gateway.
    live: bool = False


class Config(BaseModel):
    """Everything the foundation reads from configuration."""

    model_config = _STRICT

    sandbox: SandboxLimits = SandboxLimits()
    gateway: GatewayConfig = GatewayConfig()
    contract_path: Path = Path("contracts/p2p-erp.json")

    @classmethod
    def default(cls) -> Config:
        return cls()

    @classmethod
    def from_toml(cls, path: Path) -> Config:
        """Load and validate a TOML config file.

        Raises `KitError` with `config.unreadable` if the file is missing or is not TOML, and
        `config.invalid` if a field is wrong.
        """
        try:
            raw = path.read_bytes()
        except OSError as err:
            raise KitError(ErrorCode.CONFIG_UNREADABLE) from err
        try:
            data = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as err:
            raise KitError(ErrorCode.CONFIG_UNREADABLE) from err
        return cls.from_mapping(data)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> Config:
        try:
            return cls.model_validate(data)
        except ValidationError as err:
            field, problem = _first_problem(err, _KNOWN_FIELDS)
            raise KitError(ErrorCode.CONFIG_INVALID, field=field, problem=problem) from err


def _known_fields(model: type[BaseModel], prefix: str = "") -> frozenset[str]:
    """Every dotted field path the model accepts, derived from the model, not written out."""
    paths: set[str] = set()
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        paths.add(path)
        annotation = info.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths |= _known_fields(annotation, f"{path}.")
    return frozenset(paths)


def _first_problem(err: ValidationError, known: frozenset[str]) -> tuple[str, str]:
    """A schema-derived field path and a fixed problem token for the first error.

    The value pydantic saw is deliberately dropped, and a field path the file invented -- an
    unknown key, which `extra="forbid"` reports under its own name -- becomes `unrecognized`.
    """
    first = err.errors()[0]
    path = ".".join(str(part) for part in first["loc"])
    field = path if path in known else "unrecognized"
    # Pydantic's error types are fixed identifiers (`extra_forbidden`, `greater_than`), but a
    # custom validator could introduce anything, and `KitError` refuses a detail value that is not
    # a short token. Fall back rather than turn a config error into a crash.
    return field, safe_token(str(first["type"]), fallback="invalid")


_KNOWN_FIELDS: Final = _known_fields(Config)
