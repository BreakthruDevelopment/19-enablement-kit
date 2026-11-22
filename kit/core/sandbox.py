"""The read-only sandbox Proxy: the only module in the kit that opens a file.

Every read the scout or the reviewer makes goes through a `Sandbox`. It is a Proxy over the
filesystem rather than a convenience wrapper: the subject it stands in front of is the real
filesystem, the interface it offers is the same read-a-file interface, and what it adds is the
access control the scout and the reviewer must not be able to go around.

The rules, in the order they are applied to every path:

1. **Symlinks are resolved first.** The sample codebase and any client checkout are untrusted
   content, so a symlink out of the tree is the obvious way past a prefix test -- and a symlink
   *within* the tree aimed at a denied file is the same escape one layer down. Both later checks
   therefore read the resolved real path, never the path as asked for.
2. **Root allowlist.** The roots are resolved **once, when the sandbox is constructed**, and a
   read's resolved path is compared against those resolved roots -- resolved to resolved. Comparing
   a resolved path against a raw root would refuse everything on macOS, where `/tmp` resolves to
   `/private/tmp`, and the Mac is where `run-harness.sh` runs; a symlinked home does the same on
   Linux. Outside every root is a `permission` error.
3. **Deny list.** `.git`, `.env*`, `*.pem`, `id_*`, `secrets` and `.claude` refuse before the open.
   Each pattern is matched against **every path segment** of the resolved real path relative to its
   root -- not against the path as asked for, and not against the whole path as one string, which
   would make `id_*` match nothing. So a denied directory name denies everything beneath it.
4. **Caps.** A per-file byte cap, a per-run total byte cap and a file-count cap. Exceeding one is a
   `business` error naming the cap -- never a truncated read that looks complete.

Writes are refused entirely for `engineer` and `ci`. `lead` writes only through the scaffold
factory, only under the write root, and the deny list and the per-file cap apply there too.

Every refusal is both raised as a `KitError` and recorded in `refusals`, because the migration
brief must report refused ground in `coverage.unread_reason` rather than quietly look complete. A
refusal records the code and the cap or pattern involved -- not the path, which the caller already
has and which `kit.core.errors` explains it must not take from here.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn

from agent_container.core.tool import ErrorCategory

from kit.core.config import SandboxLimits
from kit.core.errors import ErrorCode, KitError
from kit.core.principals import Capability, Principal, assert_can

__all__ = ["DENY_PATTERNS", "Refusal", "Sandbox", "Usage"]

# Matched against every segment of a resolved path, relative to its root.
DENY_PATTERNS: tuple[str, ...] = (".git", ".env*", "*.pem", "id_*", "secrets", ".claude")


@dataclass(frozen=True, slots=True)
class Usage:
    """What a run has spent. `files_read` counts distinct files; `bytes_read` counts every byte
    served, so re-reading a file costs bytes again but not another file."""

    files_read: int
    bytes_read: int


@dataclass(frozen=True, slots=True)
class Refusal:
    """A refusal, for `coverage.unread_reason`. Carries no path: see the module docstring."""

    code: ErrorCode
    category: ErrorCategory
    reason: str
    detail: Mapping[str, int | str] = field(default_factory=lambda: MappingProxyType({}))

    @classmethod
    def of(cls, err: KitError) -> Refusal:
        return cls(err.code, err.category, err.message, err.detail)


def _real(path: Path | str) -> Path:
    """The fully resolved real path: symlinks followed, `..` removed, nothing opened."""
    return Path(os.path.realpath(path))


def _denied_pattern(segments: Iterable[str]) -> str | None:
    """The first deny-list pattern any segment matches, or None.

    Matched case-sensitively against the segment and again against its lowercase form: the
    patterns are lowercase, and on a case-insensitive filesystem `.ENV` opens `.env`.
    """
    for segment in segments:
        lowered = segment.lower()
        for pattern in DENY_PATTERNS:
            if fnmatchcase(segment, pattern) or fnmatchcase(lowered, pattern):
                return pattern
    return None


class Sandbox:
    """A read-only view of one or more roots, for one principal."""

    def __init__(
        self,
        principal: Principal,
        roots: Sequence[Path | str],
        limits: SandboxLimits | None = None,
        *,
        write_root: Path | str | None = None,
    ) -> None:
        assert_can(principal, Capability.READ_FILES)
        if not roots:
            raise KitError(ErrorCode.BAD_ROOT)
        resolved: list[Path] = []
        for root in roots:
            real = _real(root)
            if not real.is_dir():
                raise KitError(ErrorCode.BAD_ROOT)
            resolved.append(real)
        self._principal = principal
        self._roots: tuple[Path, ...] = tuple(resolved)
        self._limits = limits if limits is not None else SandboxLimits()
        self._write_root: Path | None = None
        if write_root is not None:
            real_write = _real(write_root)
            if not real_write.is_dir():
                raise KitError(ErrorCode.BAD_ROOT)
            self._write_root = real_write
        self._files: set[Path] = set()
        self._bytes = 0
        self._refusals: list[Refusal] = []

    # -- what the run has spent, and what it was refused ------------------------------------

    @property
    def principal(self) -> Principal:
        return self._principal

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    @property
    def limits(self) -> SandboxLimits:
        return self._limits

    @property
    def usage(self) -> Usage:
        return Usage(len(self._files), self._bytes)

    @property
    def refusals(self) -> tuple[Refusal, ...]:
        return tuple(self._refusals)

    # -- reads ------------------------------------------------------------------------------

    def read_bytes(self, path: Path | str) -> bytes:
        """The whole file, or a `KitError`. Never a partial read."""
        real = self._check_read(path)
        size = real.stat().st_size
        self._charge(real, size)
        try:
            return real.read_bytes()
        except OSError as err:
            self._refuse(ErrorCode.UNREADABLE, cause=err, encoding="bytes")

    def read_text(self, path: Path | str, *, encoding: str = "utf-8") -> str:
        """The whole file decoded strictly. A decode failure refuses rather than mangles."""
        data = self.read_bytes(path)
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as err:
            self._refuse(ErrorCode.UNREADABLE, cause=err, encoding=_safe_encoding(encoding))

    def list_dir(self, path: Path | str) -> tuple[Path, ...]:
        """The children of a directory, resolved, sorted, with denied and escaping ones removed.

        A removed child is recorded as a refusal, so a listing can never look complete when it is
        not. Listing charges no cap: nothing is opened.
        """
        real = self._check_path(path)
        if not real.is_dir():
            self._refuse(ErrorCode.NOT_A_DIRECTORY)
        kept: list[Path] = []
        for child in sorted(real.iterdir()):
            try:
                kept.append(self._check_path(child))
            except KitError:
                continue
        return tuple(kept)

    def walk(self, path: Path | str) -> tuple[Path, ...]:
        """Every readable regular file under a directory, sorted, denied subtrees pruned.

        Opens nothing and charges no cap, so a caller can count `files_total` for the brief's
        `coverage` before deciding what to spend its byte budget on.
        """
        start = self._check_path(path)
        if not start.is_dir():
            self._refuse(ErrorCode.NOT_A_DIRECTORY)
        found: list[Path] = []
        stack = [start]
        seen: set[Path] = {start}
        while stack:
            current = stack.pop()
            for child in self.list_dir(current):
                if child.is_dir():
                    if child not in seen:
                        seen.add(child)
                        stack.append(child)
                elif child.is_file():
                    found.append(child)
        return tuple(sorted(found))

    # -- the one write path -----------------------------------------------------------------

    def write_text(self, path: Path | str, content: str, *, encoding: str = "utf-8") -> Path:
        """Write a file under the write root. `lead` only, through the scaffold factory.

        `engineer` and `ci` are refused by `assert_can` before anything is resolved: they hold no
        `write_target` capability at all.
        """
        assert_can(self._principal, Capability.WRITE_TARGET)
        write_root = self._write_root
        if write_root is None:
            self._refuse(ErrorCode.WRITE_FORBIDDEN)
        target = Path(path)
        # The file may not exist yet, so the parent is what gets resolved; the name is then joined
        # on so a symlinked parent cannot smuggle the write out of the root.
        real_parent = _real(target.parent if target.is_absolute() else write_root / target.parent)
        real = real_parent / target.name
        if not _within(real, write_root):
            self._refuse(ErrorCode.OUTSIDE_ROOT)
        denied = _denied_pattern(real.relative_to(write_root).parts)
        if denied is not None:
            self._refuse(ErrorCode.DENIED_NAME, pattern=denied)
        data = content.encode(encoding)
        limit = self._limits.max_file_bytes
        if len(data) > limit:
            self._refuse(ErrorCode.FILE_BYTE_CAP, cap="max_file_bytes", limit=limit, size=len(data))
        real_parent.mkdir(parents=True, exist_ok=True)
        real.write_bytes(data)
        return real

    # -- checks -----------------------------------------------------------------------------

    def _check_path(self, path: Path | str) -> Path:
        """Resolve, then the allowlist, then the deny list. Shared by reads and listings."""
        real = _real(path)
        root = self._containing_root(real)
        if root is None:
            self._refuse(ErrorCode.OUTSIDE_ROOT)
        denied = _denied_pattern(real.relative_to(root).parts)
        if denied is not None:
            self._refuse(ErrorCode.DENIED_NAME, pattern=denied)
        return real

    def _check_read(self, path: Path | str) -> Path:
        real = self._check_path(path)
        if not real.exists():
            self._refuse(ErrorCode.MISSING)
        if not real.is_file():
            self._refuse(ErrorCode.NOT_A_FILE)
        return real

    def _containing_root(self, real: Path) -> Path | None:
        for root in self._roots:
            if _within(real, root):
                return root
        return None

    def _charge(self, real: Path, size: int) -> None:
        """Apply the three caps before a byte is read. Refuses rather than truncates."""
        limits = self._limits
        if size > limits.max_file_bytes:
            self._refuse(
                ErrorCode.FILE_BYTE_CAP,
                cap="max_file_bytes",
                limit=limits.max_file_bytes,
                size=size,
            )
        fresh = real not in self._files
        if fresh and len(self._files) >= limits.max_files:
            self._refuse(ErrorCode.FILE_COUNT_CAP, cap="max_files", limit=limits.max_files)
        if self._bytes + size > limits.max_run_bytes:
            self._refuse(
                ErrorCode.RUN_BYTE_CAP,
                cap="max_run_bytes",
                limit=limits.max_run_bytes,
                spent=self._bytes,
                size=size,
            )
        self._files.add(real)
        self._bytes += size

    def _refuse(
        self, code: ErrorCode, *, cause: BaseException | None = None, **detail: int | str
    ) -> NoReturn:
        """Record the refusal, then raise it. No code declares a detail field named `cause`."""
        err = KitError(code, **detail)
        self._refusals.append(Refusal.of(err))
        raise err from cause


def _within(candidate: Path, root: Path) -> bool:
    return candidate == root or candidate.is_relative_to(root)


def _safe_encoding(encoding: str) -> str:
    """An encoding name is an argument, so it is checked before it reaches an error message."""
    cleaned = encoding.strip().lower()
    return cleaned if cleaned.replace("-", "").replace("_", "").isalnum() else "text"
