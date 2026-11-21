"""Command-line entry point. Subcommands arrive in later slices; for now `--version`."""

import argparse
from collections.abc import Sequence

from kit import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kit", description="The enablement kit.")
    parser.add_argument("--version", action="version", version=f"kit {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    build_parser().parse_args(argv)
    print(f"kit {__version__}: no command given; see --help")
    return 0
