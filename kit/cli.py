"""Command-line entry point: `--version` and the subcommands, one per slice."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from kit import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit", description="The enablement kit.")
    parser.add_argument("--version", action="version", version=f"kit {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")

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
    if args.command == "review":
        # Imported here so `kit --version` does not load the review package.
        from kit.review.command import engineer_from_environment, run_review_command

        return run_review_command(
            args.diff,
            principal=engineer_from_environment(),
            replay_dir=args.replay,
            criteria_dir=args.criteria,
        )
    if args.command == "session":
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
    print(f"kit {__version__}: no command given; see --help")
    return 0
