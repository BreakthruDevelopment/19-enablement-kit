"""Command-line entry point: `--version` and the subcommands, one per slice."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from kit import __version__
from kit.scaffold.command import register_new, run_new


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit", description="The enablement kit.")
    parser.add_argument("--version", action="version", version=f"kit {__version__}")
    # One subparser group for the whole CLI. argparse allows a parser only one, so a slice
    # registers its command on the group rather than on the parser.
    commands = parser.add_subparsers(dest="command", metavar="<command>")

    register_new(commands)

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
    command = cast(str | None, getattr(args, "command", None))
    if command is None:
        print(f"kit {__version__}: no command given; see --help")
        return 0
    if command == "new":
        return run_new(args)
    if command == "review":
        # Imported here so `kit --version` and `kit new` do not load the review package.
        from kit.review.command import engineer_from_environment, run_review_command

        return run_review_command(
            args.diff,
            principal=engineer_from_environment(),
            replay_dir=args.replay,
            criteria_dir=args.criteria,
        )
    print(f"kit {__version__}: no command given; see --help", file=sys.stderr)
    return 2
