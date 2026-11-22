"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import cast

from kit import __version__
from kit.scaffold.command import register_new, run_new


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit", description="The enablement kit.")
    parser.add_argument("--version", action="version", version=f"kit {__version__}")
    register_new(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = cast(str | None, getattr(args, "command", None))
    if command is None:
        print(f"kit {__version__}: no command given; see --help")
        return 0
    if command == "new":
        return run_new(args)
    print(f"kit {__version__}: no command given; see --help", file=sys.stderr)
    return 2
