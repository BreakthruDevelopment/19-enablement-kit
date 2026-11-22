"""Committed scaffolds, loaded from package data.

Three kinds, each a fixed reviewed set. Nothing in here is authored at runtime: `kit new`
copies bytes. The files on disk live under ordinary names (`rules/`, `commands/`,
`skills/`) so they are normal package data. The factory writes them where Claude Code
looks:

- `CLAUDE.md` at the root and in subdirectories is the hierarchy (statement 3.1).
  A subdirectory file loads when work touches that directory, and adds to the root file.
- `.claude/rules/*.md` with a `paths` frontmatter is a path-scoped rule (statement 3.3).
- `.claude/commands/*.md` is a slash command and `.claude/skills/<name>/SKILL.md` is a
  skill (statement 3.2).

`.claude` is deliberately not the directory name in this package. The sandbox deny list
refuses that segment, which is correct for a read: those files are instructions, and the
scout must not treat them as source. The product of this factory is that directory in a
*target* repository. Renaming on the way out keeps the two facts apart.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from fnmatch import fnmatchcase
from importlib.resources import files
from importlib.resources.abc import Traversable

from kit.core.config import SandboxLimits
from kit.scaffold.errors import ScaffoldCode, ScaffoldError

__all__ = ["Kind", "LoadedTemplate", "check_templates", "load_kind"]

# Secret-shaped names the sandbox also refuses. `.claude` is not in this list: see the
# module docstring. Matched against every segment, and against its lowercase form,
# because a case-insensitive volume opens `.ENV` as `.env`.
_DENY: tuple[str, ...] = (".git", ".env*", "*.pem", "id_*", "secrets")

# Top-level template directories and the Claude Code paths they are written to.
_REMAP: dict[str, str] = {
    "rules": ".claude/rules",
    "commands": ".claude/commands",
    "skills": ".claude/skills",
}

# A segment is a token we would put in a path ourselves. `..` matches the character
# class, so it is rejected by name before the class is applied.
_SEGMENT_MAX = 128
_DEPTH_MAX = 16


class Kind(StrEnum):
    """The three scaffolds `kit new` can write."""

    PYTHON_SERVICE = "python-service"
    JAVA_LEGACY_COMPANION = "java-legacy-companion"
    DOCS_ONLY = "docs-only"


@dataclass(frozen=True, slots=True)
class LoadedTemplate:
    """One template, already mapped to the relative path it is written to."""

    output: str
    content: bytes


def load_kind(kind: Kind) -> tuple[LoadedTemplate, ...]:
    """The committed files for `kind`, mapped onto their output paths.

    Raises `ScaffoldError` with `scaffold.bad_template` when the package data is missing
    or not usable. A caller that patched this function still has to pass `check_templates`:
    the factory calls that itself.
    """
    if not isinstance(kind, Kind):
        raise ScaffoldError(ScaffoldCode.UNKNOWN_KIND)
    try:
        found = tuple(_walk(_root(kind)))
    except ScaffoldError:
        raise
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE) from None
    loaded = tuple(LoadedTemplate(_output_for(source), content) for source, content in found)
    check_templates(loaded)
    return loaded


def check_templates(loaded: Sequence[LoadedTemplate]) -> None:
    """Refuse an empty set, a duplicate path, a secret-shaped name, or unusable bytes.

    The per-file cap is the sandbox default. `kit new` must not be a way to write a file
    the sandbox would have refused on size.
    """
    if not loaded:
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
    cap = SandboxLimits().max_file_bytes
    seen: set[str] = set()
    for item in loaded:
        if not isinstance(item, LoadedTemplate) or not _relative_ok(item.output):
            raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
        denied = _denied_pattern(item.output)
        if denied is not None:
            raise ScaffoldError(ScaffoldCode.DENIED_NAME, pattern=denied)
        if item.output in seen:
            raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
        seen.add(item.output)
        _check_content(item.content, cap)


def _root(kind: Kind) -> Traversable:
    return files("kit.scaffold").joinpath("templates", kind.value)


def _by_name(node: Traversable) -> str:
    return node.name


def _walk(node: Traversable, prefix: str = "") -> Iterator[tuple[str, bytes]]:
    for child in sorted(node.iterdir(), key=_by_name):
        relative = child.name if not prefix else f"{prefix}/{child.name}"
        if child.is_dir():
            yield from _walk(child, relative)
        elif child.is_file():
            yield relative, child.read_bytes()
        else:
            raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)


def _output_for(source: str) -> str:
    if not _relative_ok(source):
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
    head, sep, tail = source.partition("/")
    if sep and head in _REMAP:
        if not tail:
            raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
        output = f"{_REMAP[head]}/{tail}"
    else:
        output = source
    if not _relative_ok(output):
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
    return output


def _relative_ok(path: str) -> bool:
    if path.startswith("/") or "\\" in path or "\x00" in path:
        return False
    parts = path.split("/")
    if not parts or len(parts) > _DEPTH_MAX:
        return False
    for part in parts:
        if part in {"", ".", ".."} or len(part) > _SEGMENT_MAX:
            return False
        if not part.isascii() or not all(
            character.isalnum() or character in "._-" for character in part
        ):
            return False
    return True


def _denied_pattern(path: str) -> str | None:
    for part in path.split("/"):
        lowered = part.lower()
        for pattern in _DENY:
            if fnmatchcase(part, pattern) or fnmatchcase(lowered, pattern):
                return pattern
    return None


def _check_content(content: bytes, cap: int) -> None:
    if not content or len(content) > cap or b"\x00" in content or b"\r" in content:
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE) from None
    if not text.endswith("\n"):
        raise ScaffoldError(ScaffoldCode.BAD_TEMPLATE)
