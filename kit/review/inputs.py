"""The diff is untrusted contributor content, so it is capped before it reaches any model.

200 KB and 400 changed files. Over either is a refusal, **never a truncation**: a truncated diff is
a review of less than was asked for that looks complete, and it lets a contributor hide a change
behind enough harmless ones to push it past the cut.

The file count is the larger of the `diff --git` headers and the `+++ ` headers, over lines split
the way `str.splitlines` splits them (a superset of `\\n`). A `+++ ` line can also be an added line
that begins `++ `, and a count that is too high only refuses a diff it could have read, which is the
safe direction.
"""

from __future__ import annotations

from typing import Final

from kit.review.errors import ReviewError, ReviewReason

__all__ = ["MAX_DIFF_BYTES", "MAX_DIFF_FILES", "check_diff", "count_changed_files"]

MAX_DIFF_BYTES: Final = 200 * 1024
MAX_DIFF_FILES: Final = 400


def count_changed_files(diff: str) -> int:
    git_headers = 0
    plus_headers = 0
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            git_headers += 1
        elif line.startswith("+++ "):
            plus_headers += 1
    return max(git_headers, plus_headers)


def check_diff(diff: str) -> None:
    """Raise `ReviewError` unless `diff` is non-empty, text, and inside both caps."""
    if "\0" in diff:
        raise ReviewError(ReviewReason.DIFF_HAS_NUL)
    if not diff.strip():
        raise ReviewError(ReviewReason.DIFF_EMPTY)
    if len(diff.encode("utf-8", errors="surrogatepass")) > MAX_DIFF_BYTES:
        raise ReviewError(ReviewReason.DIFF_TOO_LARGE)
    if count_changed_files(diff) > MAX_DIFF_FILES:
        raise ReviewError(ReviewReason.DIFF_TOO_MANY_FILES)
