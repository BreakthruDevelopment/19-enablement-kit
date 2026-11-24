"""The scout's recorded reply: one file, in app 17's replay format.

`<dir>/brief.json` holds the one model reply a scout run asks for. A run that wires this in makes no
model call and needs no network, which is what CI and the default demo run on.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from agent_container.core.errors import ReplayFormatError
from agent_container.core.provider import ModelProvider
from agent_container.core.replay import ReplayProvider

from kit.scout.errors import ScoutError, ScoutReason

__all__ = ["REPLY_FILE", "load_replay"]

REPLY_FILE: Final = "brief.json"


def load_replay(directory: Path) -> ModelProvider:
    try:
        return ReplayProvider.from_file(directory / REPLY_FILE)
    except (OSError, ReplayFormatError):
        raise ScoutError(ScoutReason.REPLAY_MISSING) from None
