"""A provider per pass, from a directory of recorded replies.

App 17's `ReplayProvider` hands back its replies in order, one per call. Two of the passes run
concurrently, so a single ordered provider would make a fixture mean whatever the scheduler decided;
the fixture here is one file per pass instead -- `<dir>/<pass>.json`, in app 17's own format, which
is not changed -- and each pass gets its own `ReplayProvider`. Nothing is serialised to make an
ordered recording work: the concurrency is the design's.

A file is loaded when its pass asks for it, so a clean diff, which never reaches consolidation,
needs no consolidation recording.
"""

from __future__ import annotations

from pathlib import Path

from agent_container.core.errors import ReplayFormatError
from agent_container.core.provider import ModelProvider
from agent_container.core.replay import ReplayProvider

from kit.review.errors import ReviewError, ReviewReason
from kit.review.passes_names import PassName

__all__ = ["ReplayDirectory"]


class ReplayDirectory:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self._loaded: dict[PassName, ReplayProvider] = {}

    def for_pass(self, name: PassName) -> ModelProvider:
        if name not in self._loaded:
            path = self._directory / f"{name.value}.json"
            try:
                self._loaded[name] = ReplayProvider.from_file(path)
            except (OSError, ReplayFormatError) as err:
                raise ReviewError(ReviewReason.REPLAY_MISSING) from err
        return self._loaded[name]
