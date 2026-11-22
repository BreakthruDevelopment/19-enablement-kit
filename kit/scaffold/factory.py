"""Write a scaffold into a target directory, and nowhere else.

`kit new` is the only command that writes into a target repository. It calls `assert_can`
with the acting principal before it creates or replaces anything, and the only principal
that holds `write_target` is `lead`.

The bytes are not written through `Sandbox.write_text`. That primitive applies the read
deny list, and `.claude` is on it, so it cannot emit the directory Claude Code reads.
The checks that matter for a write are repeated here, in the same order the sandbox uses
for the cases they share:

1. The principal can write.
2. The target's final component is not a symbolic link. Its parent is resolved, so a
   link in a parent is the directory the caller named, and every later check is against
   that resolved root.
3. Each output path is relative, stays inside the resolved root after `realpath`, and
   is not followed through a link. A link on a path the scaffold writes refuses the
   whole run, before any destination is replaced.
4. A secret-shaped segment (`.git`, `.env*`, `*.pem`, `id_*`, `secrets`) is refused.
   `.claude` is the exception, and only because it is the scaffold's product.

Files are staged beside the destination and renamed over it. A failure unlinks the
staged copies and does not replace a destination, so a manifest is printed only for a
run that finished. Empty directories created on the way may remain: a half-written
file may not.

Errors never carry the target path. An `OSError` does, so it is not chained.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import stat as stat_module
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from kit.core.principals import Capability, Principal, assert_can
from kit.scaffold.errors import ScaffoldCode, ScaffoldError
from kit.scaffold.templates import Kind, LoadedTemplate, check_templates, load_kind

__all__ = ["Manifest", "write_scaffold"]


@dataclass(frozen=True, slots=True)
class Manifest:
    """What a successful `kit new` wrote. Paths are relative and use `/`."""

    scaffold: Kind
    files: tuple[str, ...]

    def render(self) -> str:
        """One JSON document, pretty-printed, with a trailing newline. No target path."""
        body = json.dumps(
            {"scaffold": self.scaffold.value, "files": list(self.files)},
            indent=2,
        )
        return body + "\n"


def write_scaffold(
    target: Path | str,
    kind: Kind,
    principal: Principal,
    *,
    force: bool = False,
) -> Manifest:
    """Write `kind` under `target` for `principal`.

    A missing target is created when its parent exists. A target that already has
    anything in it is refused unless `force` is set. `force` overwrites scaffold files
    and leaves every other name alone. It does not follow a symbolic link.
    """
    # Before any create, replace, or even a look that would only matter if we then
    # wrote. A principal without `write_target` learns nothing about the target from
    # this function: the refusal is the same whether or not the directory is empty.
    assert_can(principal, Capability.WRITE_TARGET)
    if not isinstance(kind, Kind):
        raise ScaffoldError(ScaffoldCode.UNKNOWN_KIND)
    if not isinstance(force, bool):
        raise ScaffoldError(ScaffoldCode.BAD_INVOCATION)
    loaded = load_kind(kind)
    # A second check, so a stand-in for `load_kind` cannot skip the path and byte rules.
    check_templates(loaded)
    root = _resolve_target(target)
    existing = _lstat(root)
    if existing is not None and not force and not _is_empty(root):
        raise ScaffoldError(ScaffoldCode.TARGET_NOT_EMPTY)
    if existing is not None:
        for item in loaded:
            _preflight(root, item.output)
    else:
        _mkdir(root)
    staged: list[tuple[Path, str]] = []
    try:
        for item in loaded:
            staged.append(_stage(root, item))
        for dest, temporary in staged:
            _commit(root, dest, temporary)
    finally:
        _discard(staged)
    return Manifest(kind, tuple(sorted(item.output for item in loaded)))


def _resolve_target(target: Path | str) -> Path:
    """The directory to write into. The final component is not followed if it is a link."""
    # A NUL cannot be a path on POSIX. Reject it before any call that would truncate
    # the name at the NUL and examine a different path.
    if "\0" in os.fspath(target):
        raise ScaffoldError(ScaffoldCode.UNREADABLE)
    try:
        raw_path = Path(target)
        raw = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
        absolute = Path(os.path.normpath(raw))
        name = absolute.name
        parent_real = Path(os.path.realpath(absolute.parent))
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.UNREADABLE) from None
    if name == "":
        raise ScaffoldError(ScaffoldCode.TARGET_UNUSABLE)
    try:
        parent_is_dir = parent_real.is_dir()
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.UNREADABLE) from None
    if not parent_is_dir:
        raise ScaffoldError(ScaffoldCode.TARGET_UNUSABLE)
    candidate = parent_real / name
    status = _lstat(candidate)
    if status is None:
        return candidate
    if stat_module.S_ISLNK(status.st_mode):
        raise ScaffoldError(ScaffoldCode.THROUGH_LINK)
    if not stat_module.S_ISDIR(status.st_mode):
        raise ScaffoldError(ScaffoldCode.TARGET_UNUSABLE)
    try:
        return Path(os.path.realpath(candidate))
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.UNREADABLE) from None


def _preflight(root: Path, relative: str) -> None:
    """Refuse a link or a non-file on an output path. Creates nothing."""
    directory = root
    parts = relative.split("/")
    for part in parts[:-1]:
        directory = directory / part
        status = _lstat(directory)
        if status is None:
            return
        if stat_module.S_ISLNK(status.st_mode):
            raise ScaffoldError(ScaffoldCode.THROUGH_LINK)
        if not stat_module.S_ISDIR(status.st_mode):
            raise ScaffoldError(ScaffoldCode.PATH_OCCUPIED)
        directory = _real_inside(root, directory)
    dest = directory / parts[-1]
    status = _lstat(dest)
    if status is None:
        return
    if stat_module.S_ISLNK(status.st_mode):
        raise ScaffoldError(ScaffoldCode.THROUGH_LINK)
    if not stat_module.S_ISREG(status.st_mode):
        raise ScaffoldError(ScaffoldCode.PATH_OCCUPIED)
    _real_inside(root, dest)


def _mkdir(path: Path) -> None:
    try:
        path.mkdir(mode=0o755)
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.WRITE_FAILED) from None


def _make_dirs(root: Path, relative: str) -> Path:
    directory = root
    for part in relative.split("/")[:-1]:
        directory = _ensure_dir(root, directory, part)
    return directory


def _ensure_dir(root: Path, parent: Path, name: str) -> Path:
    candidate = parent / name
    status = _lstat(candidate)
    if status is not None and stat_module.S_ISLNK(status.st_mode):
        raise ScaffoldError(ScaffoldCode.THROUGH_LINK)
    if status is not None and not stat_module.S_ISDIR(status.st_mode):
        raise ScaffoldError(ScaffoldCode.PATH_OCCUPIED)
    if status is None:
        try:
            candidate.mkdir(mode=0o755)
        except FileExistsError:
            # Lost a race. A link that appeared here is the same refusal as one we saw.
            again = _lstat(candidate)
            if again is not None and stat_module.S_ISLNK(again.st_mode):
                raise ScaffoldError(ScaffoldCode.THROUGH_LINK) from None
            if again is None or not stat_module.S_ISDIR(again.st_mode):
                raise ScaffoldError(ScaffoldCode.PATH_OCCUPIED) from None
        except (OSError, ValueError):
            raise ScaffoldError(ScaffoldCode.WRITE_FAILED) from None
    return _real_inside(root, candidate)


def _stage(root: Path, item: LoadedTemplate) -> tuple[Path, str]:
    """Write the bytes to a temporary file in the destination directory. Do not replace yet."""
    directory = _make_dirs(root, item.output)
    dest = directory / item.output.rsplit("/", 1)[-1]
    status = _lstat(dest)
    if status is not None and stat_module.S_ISLNK(status.st_mode):
        raise ScaffoldError(ScaffoldCode.THROUGH_LINK)
    if status is not None and not stat_module.S_ISREG(status.st_mode):
        raise ScaffoldError(ScaffoldCode.PATH_OCCUPIED)
    _real_inside(root, dest)
    descriptor = -1
    temporary = ""
    try:
        descriptor, temporary = tempfile.mkstemp(dir=directory, prefix=".kit-", suffix=".tmp")
        _real_inside(root, Path(temporary))
        _write_all(descriptor, item.content)
        os.close(descriptor)
        descriptor = -1
        os.chmod(temporary, 0o644)
    except ScaffoldError:
        _cleanup_stage(descriptor, temporary)
        raise
    except (OSError, ValueError):
        _cleanup_stage(descriptor, temporary)
        raise ScaffoldError(ScaffoldCode.WRITE_FAILED) from None
    return dest, temporary


def _commit(root: Path, dest: Path, temporary: str) -> None:
    """Replace `dest` with the staged file. `rename` replaces a link; we refuse first."""
    status = _lstat(dest)
    if status is not None and stat_module.S_ISLNK(status.st_mode):
        raise ScaffoldError(ScaffoldCode.THROUGH_LINK)
    if status is not None and not stat_module.S_ISREG(status.st_mode):
        raise ScaffoldError(ScaffoldCode.PATH_OCCUPIED)
    _real_inside(root, dest)
    try:
        os.replace(temporary, dest)
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.WRITE_FAILED) from None


def _cleanup_stage(descriptor: int, temporary: str) -> None:
    if descriptor >= 0:
        _close_quietly(descriptor)
    if temporary:
        _unlink_quietly(temporary)


def _discard(staged: Sequence[tuple[Path, str]]) -> None:
    """Unlink staged copies that were not renamed. A renamed one is already gone."""
    for _dest, temporary in staged:
        _unlink_quietly(temporary)


def _real_inside(root: Path, path: Path) -> Path:
    try:
        real = Path(os.path.realpath(path))
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.UNREADABLE) from None
    if not _within(real, root):
        raise ScaffoldError(ScaffoldCode.OUTSIDE_TARGET)
    return real


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.UNREADABLE) from None


def _is_empty(root: Path) -> bool:
    try:
        with os.scandir(root) as scan:
            for _entry in scan:
                return False
    except FileNotFoundError:
        return True
    except (OSError, ValueError):
        raise ScaffoldError(ScaffoldCode.UNREADABLE) from None
    return True


def _within(candidate: Path, root: Path) -> bool:
    """Resolved path against resolved root. Not a string prefix: `/repo` is not `/repo-other`."""
    return candidate == root or candidate.is_relative_to(root)


def _write_all(descriptor: int, data: bytes) -> None:
    """Write every byte. `write` may take fewer than it was given."""
    written = 0
    while written < len(data):
        taken = os.write(descriptor, data[written:])
        if taken <= 0:  # pragma: no cover -- POSIX forbids it; a refusal beats a silent loop
            raise OSError(errno.EIO, "the write made no progress")
        written += taken


def _close_quietly(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        os.close(descriptor)


def _unlink_quietly(path: str) -> None:
    with contextlib.suppress(OSError):
        os.unlink(path)
