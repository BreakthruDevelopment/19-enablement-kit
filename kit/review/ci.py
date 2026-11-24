"""The headless reviewer: `kit review-ci`, run by `.github/workflows/kit-review.yml` as `ci`.

It runs the review passes over a pull request's diff and posts **at most one** review. "At most one"
is a ceiling and not a floor, and the cases that fall under it are decided here, not in the YAML:

* the run could not complete (a pass never got a parseable response -- a throttle, a provider
  error, the budget gone): **nothing is posted** and the command exits `1`, so the workflow step
  errors. A *rejected* pass is a different thing and does post, as `blocking`: see
  `kit.review.passes`.
* the pull request already carries a review from the Actions bot for this commit and this mode:
  nothing more is posted. A label event or a re-run cannot stack reviews.
* the finished body could satisfy the factory's gate: nothing is posted.

Everything that reaches the pull request goes through `post_review`, and `post_review` is the one
place the finished body is checked (`assert_body_safe`) and the one place the HTTP call is made, so
no path around the check exists. The report that goes in is **evidence for the person giving
sign-off and never a substitute for it**: it carries the kit's own `Kit-Review:` marker and never
the factory's `Reviewer:`/`Verdict:` lines. The review is posted as a `COMMENT`, never an approval
or a change request, so it cannot change the merge state by itself either.

Recorded replies are the default: they cost nothing and need no credential. `live=True` is chosen
by the workflow only when both a secret and a label are present; this module does not read a secret
(the model's credentials arrive through boto3's default chain, which the workflow populated), and
the token that posts is read once, from `GITHUB_TOKEN`, and never placed in a message.

Exit codes: `0` posted, or already posted for this commit and mode; `1` could not complete, nothing
posted; `2` refused before any model call; `3` the report was withheld; `4` the post failed.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Protocol, TextIO

from agent_container.core.bedrock import BedrockProvider

from kit.core.errors import KitError
from kit.core.principals import Capability, Principal, assert_can
from kit.review.command import DEFAULT_CRITERIA_DIR, run_review_command
from kit.review.errors import ReviewError, ReviewReason
from kit.review.pipeline import ProviderSource, SharedProvider
from kit.review.report import ReportMode
from kit.review.sanitize import assert_body_safe

__all__ = [
    "BOT_LOGIN",
    "GitHubReviews",
    "ReviewsApi",
    "post_review",
    "run_ci_review",
]

BOT_LOGIN: Final = "github-actions[bot]"
_MARKER_LINE: Final = "Kit-Review: pr-review"
_MAX_BODY_CHARS: Final = 60_000  # GitHub's limit is 65,536; the margin is for the encoding
_MAX_PAGES: Final = 20

_REPO: Final = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_SHA: Final = re.compile(r"[0-9a-f]{40}")
_API: Final = "https://api.github.com"


class ReviewsApi(Protocol):
    """The two calls the posting path makes. Tests stub it; `GitHubReviews` is the real one."""

    def bot_review_bodies(self, repo: str, pr: int) -> list[str]:
        """Bodies of the reviews on `pr` written by `BOT_LOGIN`. Raises `ReviewError` if the list
        cannot be read in full."""
        ...

    def create_review(self, repo: str, pr: int, commit: str, body: str) -> None: ...


class GitHubReviews:
    """The reviews endpoints of the GitHub REST API, over `urllib`.

    The token is held in a private field and used in one header. Every failure is a fixed
    `ReviewError`: the response body is never read into a message, because it is somebody else's
    text and an error message ends up in a workflow log.
    """

    def __init__(self, token: str) -> None:
        if not token or not token.isascii() or any(c in token for c in "\r\n"):
            raise ReviewError(ReviewReason.CI_INPUT_INVALID)
        self._token = token

    def _request(
        self, method: str, url: str, payload: Mapping[str, object] | None = None
    ) -> object:
        if not url.startswith(_API + "/"):
            raise ReviewError(ReviewReason.POST_FAILED)
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(  # noqa: S310 -- scheme and host pinned by the check above
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
                "User-Agent": "kit-review-ci",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                raw = resp.read(4_000_000)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReviewError(ReviewReason.POST_FAILED) from None
        try:
            return json.loads(raw) if raw else None
        except ValueError:
            raise ReviewError(ReviewReason.POST_FAILED) from None

    def bot_review_bodies(self, repo: str, pr: int) -> list[str]:
        bodies: list[str] = []
        for page in range(1, _MAX_PAGES + 1):
            url = f"{_API}/repos/{repo}/pulls/{pr}/reviews?per_page=100&page={page}"
            try:
                items = self._request("GET", url)
            except ReviewError:
                raise ReviewError(ReviewReason.POST_UNVERIFIABLE) from None
            if not isinstance(items, list):
                raise ReviewError(ReviewReason.POST_UNVERIFIABLE)
            for item in items:
                if not isinstance(item, dict):
                    continue
                user = item.get("user")
                body = item.get("body")
                if isinstance(user, dict) and user.get("login") == BOT_LOGIN:
                    bodies.append(body if isinstance(body, str) else "")
            if len(items) < 100:
                return bodies
        # Too many reviews to read them all: "at most one" cannot be checked, so do not post.
        raise ReviewError(ReviewReason.POST_UNVERIFIABLE)

    def create_review(self, repo: str, pr: int, commit: str, body: str) -> None:
        self._request(
            "POST",
            f"{_API}/repos/{repo}/pulls/{pr}/reviews",
            # COMMENT, never APPROVE or REQUEST_CHANGES: the report is evidence, not a decision.
            {"commit_id": commit, "body": body, "event": "COMMENT"},
        )


def _marker_lines(mode: ReportMode, commit: str) -> frozenset[str]:
    return frozenset({f"Kit-Mode: {mode.value}", f"Kit-Commit: {commit}"})


def post_review(
    api: ReviewsApi,
    principal: Principal,
    *,
    repo: str,
    pr: int,
    commit: str,
    mode: ReportMode,
    body: str,
) -> bool:
    """Post `body` as the one review, or post nothing. Returns whether a review was posted.

    This is the single path to the pull request. It re-checks the capability, the arguments and the
    *finished* body -- whatever assembled that body, including text added after `render_report`.
    """
    assert_can(principal, Capability.POST_REVIEW)
    if not _REPO.fullmatch(repo) or pr < 1 or not _SHA.fullmatch(commit):
        raise ReviewError(ReviewReason.CI_INPUT_INVALID)
    assert_body_safe(body)
    lines = body.split("\n")
    if lines[0] != _MARKER_LINE or not _marker_lines(mode, commit) <= set(lines):
        # Not a report this kit assembled: it must carry its own marker and the dedupe keys.
        raise ReviewError(ReviewReason.REPORT_REFUSED)
    if len(body) > _MAX_BODY_CHARS:
        raise ReviewError(ReviewReason.REPORT_REFUSED)
    wanted = _marker_lines(mode, commit)
    for existing in api.bot_review_bodies(repo, pr):
        if wanted <= set(existing.replace("\r", "").split("\n")):
            return False
    api.create_review(repo, pr, commit, body)
    return True


def live_providers(environ: Mapping[str, str]) -> ProviderSource:
    """Bedrock behind the `ModelProvider` contract, for the workflow's live mode.

    The model id comes from the environment; the credential, if any, is boto3's default chain,
    which the workflow filled in. Nothing here reads a secret.
    """
    model_id = environ.get("KIT_REVIEW_MODEL_ID", "").strip()
    if not model_id:
        raise ReviewError(ReviewReason.LIVE_UNCONFIGURED)
    region = environ.get("AWS_REGION", "").strip() or None
    return SharedProvider(BedrockProvider(model_id, region_name=region))


def run_ci_review(
    diff_path: Path,
    *,
    repo: str,
    pr: int,
    commit: str,
    live: bool,
    replay_dir: Path | None,
    criteria_dir: Path = DEFAULT_CRITERIA_DIR,
    api: ReviewsApi | None = None,
    environ: Mapping[str, str] | None = None,
    err: TextIO | None = None,
) -> int:
    """Run the passes as `ci` and post at most one review. Returns the exit code (module doc)."""
    env = environ if environ is not None else os.environ
    err = err if err is not None else sys.stderr
    principal = Principal.ci()
    mode = ReportMode.LIVE if live else ReportMode.RECORDED
    try:
        if not _REPO.fullmatch(repo) or pr < 1 or not _SHA.fullmatch(commit):
            raise ReviewError(ReviewReason.CI_INPUT_INVALID)
        assert_can(principal, Capability.POST_REVIEW)
        providers = live_providers(env) if live else None
        reviews = api if api is not None else GitHubReviews(env.get("GITHUB_TOKEN", ""))
    except ReviewError as refusal:
        print(f"kit review-ci: {refusal}", file=err)
        return 2
    except KitError as refusal:
        print(f"kit review-ci: {refusal.message}", file=err)
        return 2

    out = io.StringIO()
    code = run_review_command(
        diff_path,
        principal=principal,
        replay_dir=replay_dir,
        criteria_dir=criteria_dir,
        out=out,
        err=err,
        providers=providers,
        mode=mode,
        markers={"Kit-Mode": mode.value, "Kit-Commit": commit},
    )
    if code != 0:
        # 1: incomplete (nothing was printed to `out`), 2: refused, 3: report withheld.
        return code
    try:
        posted = post_review(
            reviews, principal, repo=repo, pr=pr, commit=commit, mode=mode, body=out.getvalue()
        )
    except ReviewError as refusal:
        print(f"kit review-ci: {refusal}", file=err)
        return 3 if refusal.reason is ReviewReason.REPORT_REFUSED else 4
    except KitError as refusal:
        print(f"kit review-ci: {refusal.message}", file=err)
        return 2
    print(
        "kit review-ci: review posted" if posted else "kit review-ci: already posted; not repeated",
        file=err,
    )
    return 0
