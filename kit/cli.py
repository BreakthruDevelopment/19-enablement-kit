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
    return parser


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
    print(f"kit {__version__}: no command given; see --help")
    return 0
