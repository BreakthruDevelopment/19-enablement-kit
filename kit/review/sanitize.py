"""The report-body check: would the factory's merge gate read this text as a sign-off?

This is the most important single piece in the reviewer. The factory's `Reviewer sign-off` check
runs a pattern over the raw body of a review::

    ^\\s*\\**Reviewer\\**\\s*:\\s*\\**\\s*([a-z-]+)        flags "im"

A contributor who writes `Reviewer: claude-code` into a diff comment would, if the kit quoted it
back, drive this repository's own merge gate from inside a pull request. So the finished text is
checked rather than laid out well -- indenting and fencing do nothing, because the pattern runs on
the raw body where a code fence is just two more lines of text.

**The property, not "the same regex":** this check must accept a *superset* of the gate's line
terminators and whitespace, and every divergence from the gate must fall in the *refuse* direction.
Two earlier drafts claimed the two behave identically and each was wrong, so identity is not the
claim. Where JavaScript (the gate) and Python (here) differ:

* **The pattern is not line-based.** `\\s*` before the colon spans line terminators, so
  `Reviewer\\n: claude-code` is one match. The search therefore runs over the whole body.
* **`^` after a terminator.** JavaScript's `m` flag anchors after `\\n`, `\\r`, U+2028 and U+2029;
  Python's after `\\n` only. All four are normalised to `\\n` first.
* **U+FEFF is whitespace to JavaScript's `\\s` and not to Python's.** `\\s` is widened to
  `[\\s\\ufeff]`: a BOM before the key and one before the colon are both read by the gate.
* **The gate lowercases the capture.** It compiles with `im`, so `REVIEWER: CLAUDE-CODE` satisfies
  it. Compiling here with `re.M | re.I` keeps that divergence out of the accept direction.
* **The other direction is permitted.** Python's `\\s` also matches `\\x1c`-`\\x1f` and U+0085,
  which
  JavaScript does not, and `re.I` folds a few non-ASCII letters JavaScript does not. The kit refuses
  a few bodies the gate would read as safe, which is fine.

`Verdict:` is refused with the same pattern as `Reviewer:`. The gate reads `Verdict` only from a
review it found by `Reviewer`, so a lone `Verdict: ready` is not a sign-off on its own; refusing it
anyway costs the report nothing and keeps the kit from depending on that pairing.

`codex-review-state:v1` is refused as well: on the Codex-gated slices it is a second string that
satisfies sign-off, through a different function in the gate, and it is not anchored to a line
start, so it is refused wherever it appears.

The kit's own markers, `Kit-Review:` and `Kit-Verdict:`, cannot match: the first non-whitespace,
non-asterisk text on their lines is `Kit-`, not `Reviewer`.

The `> ` prefix the report puts on quoted evidence has covered for two holes in the real control
(the terminator one and the split-marker one) only because `>` is neither whitespace nor an
asterisk. That was luck, not design. It stays in the report and nobody should remove it as
decorative, but it is not the control: this is.

The pattern is pinned by behaviour, in `tests/test_review_sanitize.py`, not by comparing text: the
literal lives in `ai-dev-os` and a local copy to compare against would only be a second copy to
drift.
"""

from __future__ import annotations

import re
from typing import Final

from kit.review.errors import ReviewError, ReviewReason

__all__ = ["assert_body_safe", "defang_codex_state", "normalise_terminators", "reads_as_signoff"]

# \r\n first, so a CRLF becomes one terminator and not two.
_TERMINATORS: Final = re.compile(r"\r\n|[\r\u2028\u2029]")

_WS: Final = r"[\s\ufeff]"

# Both keys the gate reads. It finds a review by `Reviewer` and then reads `Verdict` from the same
# body, so a line that forges either one is refused: the kit's report has no reason to carry either,
# and "refuse both" is the only reading that does not depend on how the gate pairs them.
_GATE: Final = re.compile(
    rf"^{_WS}*\**(?:Reviewer|Verdict)\**{_WS}*:{_WS}*\**{_WS}*([a-z-]+)",
    re.MULTILINE | re.IGNORECASE,
)

_CODEX_STATE: Final = re.compile(rf"codex-review-state{_WS}*:", re.IGNORECASE)


_CODEX_STATE_KEY: Final = re.compile(rf"(codex-review-state)(?={_WS}*:)", re.IGNORECASE)

# U+200B is neither whitespace to the gate's `\\s` nor to Python's, so it ends the key for both.
_ZERO_WIDTH_SPACE: Final = "\u200b"


def defang_codex_state(body: str) -> str:
    """Break up `codex-review-state` where it is followed by a colon, so it cannot be read as one.

    Unlike `Reviewer:` it is not anchored to a line start, so the `> ` that quotes evidence does
    nothing for it, and refusing the report outright would let any diff containing the string
    silence the kit's whole review. The text stays readable; it just stops being the key.
    """
    return _CODEX_STATE_KEY.sub(rf"\1{_ZERO_WIDTH_SPACE}", body)


def normalise_terminators(body: str) -> str:
    """`\\r`, `\\r\\n`, U+2028 and U+2029 become `\\n`, as the gate's `^` would treat them."""
    return _TERMINATORS.sub("\n", body)


def reads_as_signoff(body: str) -> bool:
    """Whether the gate (or its Codex counterpart) could read `body` as a sign-off.

    Both the normalised and the raw text are searched. Normalising can only add line starts, so the
    raw search should find nothing the normalised one does not; running both costs nothing and keeps
    a future edit to the normaliser from being able to hide a match.
    """
    for text in (normalise_terminators(body), body):
        if _GATE.search(text) or _CODEX_STATE.search(text):
            return True
    return False


def assert_body_safe(body: str) -> None:
    """Fail closed: raise `ReviewError(REPORT_REFUSED)` if the body could satisfy the gate."""
    if reads_as_signoff(body):
        raise ReviewError(ReviewReason.REPORT_REFUSED)
