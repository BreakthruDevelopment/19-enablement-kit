"""Command-line entry point: `--version` and the subcommands, one per slice."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from kit import __version__
from kit.erp.command import register_erp, run_erp_command
from kit.plan.command import register_plan
from kit.scaffold.command import register_new, run_new
from kit.scout.command import engineer_from_environment as scout_principal
from kit.scout.command import register_scout, run_scout_command


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit", description="The enablement kit.")
    parser.add_argument("--version", action="version", version=f"kit {__version__}")
    # One subparser group for the whole CLI. argparse allows a parser only one, so a slice
    # registers its command on the group rather than on the parser.
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    register_new(commands)
    register_erp(commands)
    register_scout(commands)
    register_plan(commands)

    review = commands.add_parser(
        "review", help="run the review passes over a diff, against the written criteria"
    )
    review.add_argument("diff", type=Path, help="a unified diff file")
    review.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="directory of per-pass recorded replies (default: replies/ beside the diff)",
    )
    review.add_argument(
        "--criteria", type=Path, default=Path("criteria"), help="the criteria directory"
    )

    review_ci = commands.add_parser(
        "review-ci",
        help="the headless reviewer: run the passes as `ci` and post at most one review",
    )
    review_ci.add_argument("diff", type=Path, help="the pull request's unified diff file")
    review_ci.add_argument("--repo", required=True, help="owner/name of the repository")
    review_ci.add_argument("--pr", required=True, type=int, help="the pull request number")
    review_ci.add_argument("--commit", required=True, help="the head commit the diff ends at")
    review_ci.add_argument(
        "--live", action="store_true", help="call the model; default is recorded replies"
    )
    review_ci.add_argument(
        "--replay", type=Path, default=None, help="directory of per-pass recorded replies"
    )
    review_ci.add_argument(
        "--criteria", type=Path, default=Path("criteria"), help="the criteria directory"
    )

    session = commands.add_parser("session", help="list, resume or fork your own sessions")
    session_commands = session.add_subparsers(dest="session_command", required=True)
    session_list = session_commands.add_parser("list", help="list your sessions")
    _add_session_dir(session_list)
    session_resume = session_commands.add_parser(
        "resume", help="replay a session's recorded turns, without a model call"
    )
    session_resume.add_argument("session_id", metavar="id", help="the session to replay")
    _add_session_dir(session_resume)
    session_fork = session_commands.add_parser(
        "fork", help="copy turns up to a named turn into a new session"
    )
    session_fork.add_argument("session_id", metavar="id", help="the session to copy from")
    session_fork.add_argument("turn", help="copy turns up to and including this turn")
    _add_session_dir(session_fork)
    return parser


def _add_session_dir(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dir",
        dest="directory",
        type=Path,
        default=Path("sessions"),
        help="directory of session files (default: sessions/)",
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = cast(str | None, getattr(args, "command", None))
    if command is None:
        print(f"kit {__version__}: no command given; see --help")
        return 0
    if command == "new":
        return run_new(args)
    if command == "erp":
        return run_erp_command(args)
    if command == "scout":
        return run_scout_command(args.root, principal=scout_principal(), replay_dir=args.replay)
    if command == "review":
        # Imported here so `kit --version` and `kit new` do not load the review package.
        from kit.review.command import engineer_from_environment, run_review_command

        return run_review_command(
            args.diff,
            principal=engineer_from_environment(),
            replay_dir=args.replay,
            criteria_dir=args.criteria,
        )
    if command == "review-ci":
        from kit.review.ci import run_ci_review

        return run_ci_review(
            args.diff,
            repo=args.repo,
            pr=args.pr,
            commit=args.commit,
            live=args.live,
            replay_dir=args.replay,
            criteria_dir=args.criteria,
        )
    if command == "session":
        # Imported here so the other commands do not load the session package.
        from kit.session.command import (
            engineer_from_environment,
            run_fork_command,
            run_list_command,
            run_resume_command,
        )

        principal = engineer_from_environment()
        if args.session_command == "list":
            return run_list_command(principal, directory=args.directory)
        if args.session_command == "resume":
            return run_resume_command(principal, args.session_id, directory=args.directory)
        if args.session_command == "fork":
            return run_fork_command(principal, args.session_id, args.turn, directory=args.directory)
        return 2
    if command == "plan":
        # Not a lazy import: `register_plan` is imported from this module at module scope, so the
        # plan package is already loaded. These two names are read here only to keep the branch
        # self-contained, as the other branches are.
        from kit.plan.command import engineer_from_environment as plan_principal
        from kit.plan.command import run_plan_command

        return run_plan_command(
            args.task,
            principal=plan_principal(),
            replay_dir=args.replay,
            directory=args.directory,
            criteria_dir=args.criteria,
            refine=args.refine,
        )
    print(f"kit {__version__}: no command given; see --help", file=sys.stderr)
    return 2
