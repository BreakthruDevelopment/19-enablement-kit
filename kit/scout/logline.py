"""Scout log lines: a JSON object per line, over a fixed key set.

`AGENTS.md` requires "JSON lines with fixed fields". `agent_container.core.log` does ship a
JSON-lines emitter, but its schema is pinned to a model loop's fields (`run_id`, `turn`, `tool`,
`outcome`, `tokens`, `duration`), none of which describes a scout event, so reusing it would mean
logging a scout event under names that do not fit it. Hence a scout-local emitter over the scout's
own keys.

The key set is closed and the values are checked here rather than at the call sites, which is the
point: every value a scout log line can carry is a count, an `ErrorCode`-style token or one of a
closed set of words. A path, a model's text, a deny-list pattern or an exception message cannot
reach a log line even if a later caller passes one by mistake -- it is replaced by `INVALID`. That
is the property `build_unread_reason` holds for `coverage.unread_reason`, enforced the same way,
because a log line is as readable as a brief.
"""

from __future__ import annotations

import json
import re
from typing import Final

__all__ = ["FIELDS", "INVALID", "MAX_TOKEN_CHARS", "log_line"]

# Every key a scout log line may carry. A key outside this set is dropped.
FIELDS: Final = (
    "event",
    "section",
    "index",
    "reason",
    "files_read",
    "files_total",
    "findings",
    "dropped",
)

# What an unsafe value becomes. A caller that passes a path or a model's text gets this, not a
# truncated or escaped copy of what it passed.
INVALID: Final = "invalid"

# Longest token a log line will carry. The bound is a comparison here rather than a quantifier in
# the pattern, where it is easier to widen by accident.
MAX_TOKEN_CHARS: Final = 64

# A token: dotted lower-case words, no leading dot and no separator. `ErrorCode` and `DropReason`
# values are tokens by construction (`unserved_file`, `sandbox.denied_name`); a path, a sentence, a
# quote and a dotfile name are not. The leading-dot and slash refusals are the point -- `.env` and
# `/etc/passwd` are exactly the values that must not survive this.
_TOKEN: Final = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*")

# Counts only. A negative or absurd number is a bug in the caller, not something to log.
_MAX_COUNT: Final = 10**9


def _value(value: object) -> int | str:
    if isinstance(value, bool):  # before `int`: `bool` is an `int` and reads wrong in a log line
        return INVALID
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_COUNT else INVALID
    if isinstance(value, str) and len(value) <= MAX_TOKEN_CHARS:
        return value if _TOKEN.fullmatch(value) is not None else INVALID
    return INVALID


def log_line(event: str, **values: object) -> str:
    """One JSON object, keys sorted, holding `event` and whichever of `FIELDS` were passed."""
    body: dict[str, int | str] = {"event": _value(event)}
    for key in FIELDS:
        if key != "event" and key in values:
            body[key] = _value(values[key])
    return json.dumps(body, sort_keys=True, separators=(",", ":"))
