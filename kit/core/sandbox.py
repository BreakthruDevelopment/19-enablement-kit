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
has and which `kit.core.errors` explains it must not take from here. Nothing escapes as a bare
`OSError` either: an unreadable directory inside a root is a recorded refusal and `walk` carries
on past it, so a permission problem cannot turn a brief into a crash -- or put an absolute path
into an exception message.

A read opens the file once and works from that descriptor: `O_NOFOLLOW` on the resolved path (whose
final component is by definition not a link), `fstat` for the kind and the size, and a bounded read
of the caps plus one byte. That is what makes a cap a cap -- `st_size` from a separate `stat` call
is a claim about the past, and a file that grew in between would otherwise be served whole.

**Two limitations are deliberate, and named rather than implied.** A **hard link** to a denied file
is served: the rules the spec sets out resolve symlinks and match the deny list against the segments
of the resolved path, and a hard link has no second path to match, so `notes.txt` hard-linked to
`<root>/.env` reads as itself. Closing it would mean refusing any file with `st_nlink > 1`, which is
a rule the spec does not state, so the limitation is recorded here, and in the pull request that
introduced it, instead of being closed on a builder's own authority. A test pins it, so a later
slice changes it deliberately rather than by accident; 19.8 owns the brief's "no secret-shaped
string" test and is where a content-level check belongs.

Second, the **resolve-then-open** window is narrowed, not removed: the path is resolved by name and
then opened by name, so a component *above* the file can be swapped in between. `O_NOFOLLOW` and
the `fstat` close that window for the final component, which is the one an untrusted checkout can
plant.
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat as stat_module
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from types import MappingProxyType
from typing import NoReturn

from agent_container.core.tool import ErrorCategory

from kit.core.config import SandboxLimits
from kit.core.errors import ErrorCode, KitError, safe_token
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
        # The counters come first: resolving a root can itself refuse, and `_refuse` records.
        self._principal = principal
        self._limits = limits if limits is not None else SandboxLimits()
        self._files: set[Path] = set()
        self._bytes = 0
        self._refusals: list[Refusal] = []
        if not roots:
            raise KitError(ErrorCode.BAD_ROOT)
        try:
            self._roots: tuple[Path, ...] = tuple(self._as_root(root) for root in roots)
            self._write_root: Path | None = (
                None if write_root is None else self._as_root(write_root)
            )
        except KitError as err:
            # A root is the caller's own configuration, not untrusted input, so every way it can
            # be wrong -- missing, a file, unreadable, unresolvable -- is one error.
            raise KitError(ErrorCode.BAD_ROOT) from err

    def _as_root(self, root: Path | str) -> Path:
        """A root, resolved once and confirmed to be a directory."""
        if not str(root):
            # `realpath("")` is the working directory; rooting a sandbox there silently is not a
            # reasonable reading of an empty string.
            raise KitError(ErrorCode.BAD_ROOT)
        real = self._real(root)
        status = self._status(real)
        if status is None or not stat_module.S_ISDIR(status.st_mode):
            raise KitError(ErrorCode.BAD_ROOT)
        return real

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
        """The whole file, or a `KitError`. Never a partial read, never past a cap."""
        real = self._check_read(path)
        limits = self._limits
        try:
            # `O_NONBLOCK` as well: `O_RDONLY` on a fifo blocks in the open, before `fstat`
            # could refuse it, and a CLI run has no timeout. It costs a regular file nothing.
            descriptor = os.open(real, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as err:
            self._refuse(ErrorCode.UNREADABLE, cause=err, encoding="bytes")
        try:
            try:
                status = os.fstat(descriptor)
            except OSError as err:
                self._refuse(ErrorCode.READ_FAILED, cause=err)
            # Checked on the descriptor, not by name: this is the file that will be read, whatever
            # the name pointed at a moment ago.
            if not stat_module.S_ISREG(status.st_mode):
                self._refuse(ErrorCode.NOT_A_FILE)
            self._check_caps(real, status.st_size)
            # The caps plus one byte: anything over the allowance proves the file grew after the
            # `fstat`, and a cap that is refused is the specified behaviour, not a short read.
            allowance = min(limits.max_file_bytes, limits.max_run_bytes - self._bytes)
            try:
                data = _read_up_to(descriptor, allowance + 1)
            except OSError as err:
                self._refuse(ErrorCode.READ_FAILED, cause=err)
        finally:
            # A close failure on a read descriptor costs nothing and must not mask a refusal
            # raised inside the block above.
            _close_quietly(descriptor)
        served = len(data)
        if served > limits.max_file_bytes:
            self._refuse(
                ErrorCode.FILE_BYTE_CAP,
                cap="max_file_bytes",
                limit=limits.max_file_bytes,
                size=served,
            )
        if self._bytes + served > limits.max_run_bytes:
            self._refuse(
                ErrorCode.RUN_BYTE_CAP,
                cap="max_run_bytes",
                limit=limits.max_run_bytes,
                spent=self._bytes,
                size=served,
            )
        self._charge(real, served)
        return data

    def read_text(self, path: Path | str, *, encoding: str = "utf-8") -> str:
        """The whole file decoded strictly. A decode failure refuses rather than mangles."""
        data = self.read_bytes(path)
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError) as err:
            self._refuse(
                ErrorCode.UNREADABLE, cause=err, encoding=safe_token(encoding, fallback="text")
            )

    def list_dir(self, path: Path | str) -> tuple[Path, ...]:
        """The children of a directory, resolved, sorted, with denied and escaping ones removed.

        A removed child is recorded as a refusal, so a listing can never look complete when it is
        not. Listing charges no cap: nothing is opened.
        """
        real = self._check_path(path)
        status = self._status(real)
        if status is None:
            self._refuse(ErrorCode.MISSING)
        if not stat_module.S_ISDIR(status.st_mode):
            self._refuse(ErrorCode.NOT_A_DIRECTORY)
        try:
            children = sorted(real.iterdir())
        except OSError as err:
            # An unreadable directory is a refusal on the record, not an exception carrying its
            # path: `coverage.unread_reason` is where a caller must be able to report it.
            self._refuse(ErrorCode.DIRECTORY_UNREADABLE, cause=err)
        kept: set[Path] = set()
        for child in children:
            try:
                resolved = self._check_path(child)
            except KitError:
                continue
            if resolved == real:
                continue  # a link back to the directory itself is not one of its children
            kept.add(resolved)
        # Deduplicated: two links to one file are one entry, or a caller counting
        # `coverage.files_total` from a listing would overcount.
        return tuple(sorted(kept))

    def walk(self, path: Path | str) -> tuple[Path, ...]:
        """Every readable regular file under a directory, sorted, denied subtrees pruned.

        Opens nothing and charges no cap, so a caller can count `files_total` for the brief's
        `coverage` before deciding what to spend its byte budget on.
        """
        start = self._check_path(path)
        start_status = self._status(start)
        if start_status is None:
            self._refuse(ErrorCode.MISSING)
        if not stat_module.S_ISDIR(start_status.st_mode):
            self._refuse(ErrorCode.NOT_A_DIRECTORY)
        found: set[Path] = set()
        stack = [start]
        seen: set[Path] = {start}
        while stack:
            current = stack.pop()
            try:
                children = self.list_dir(current)
            except KitError:
                # Recorded by `list_dir`. A directory nobody may read must not end the walk: the
                # brief names unexplored ground, so the rest of the tree still has to be counted.
                continue
            for child in children:
                try:
                    child_status = self._status(child)
                except KitError:
                    # Recorded by `_status`. An unresolvable symlink cycle or an unreadable child
                    # must not end the walk either: this is the whole point of walking.
                    continue
                if child_status is None:
                    continue  # it went away between the listing and the look
                if stat_module.S_ISDIR(child_status.st_mode):
                    if child not in seen:
                        seen.add(child)
                        stack.append(child)
                elif stat_module.S_ISREG(child_status.st_mode):
                    found.add(child)
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
        # The file may not exist yet, so the parent is resolved first and the name joined on. The
        # joined path is then resolved in turn and BOTH rules are applied to the result: a
        # destination that is itself a link would otherwise be written straight through, out of the
        # root or over a denied file, because an open follows a link like any other.
        parent = target.parent if target.is_absolute() else write_root / target.parent
        real_parent = self._real(parent)
        candidate = real_parent / target.name
        candidate_status = self._status(candidate, follow=False)
        if candidate_status is not None and stat_module.S_ISLNK(candidate_status.st_mode):
            self._refuse(ErrorCode.WRITE_THROUGH_LINK)
        real = self._real(candidate)
        if not _within(real, write_root):
            self._refuse(ErrorCode.OUTSIDE_ROOT)
        denied = _denied_pattern(real.relative_to(write_root).parts)
        if denied is not None:
            self._refuse(ErrorCode.DENIED_NAME, pattern=denied)
        real_status = self._status(real)
        if real_status is not None and not stat_module.S_ISREG(real_status.st_mode):
            self._refuse(ErrorCode.NOT_A_FILE)
        try:
            data = content.encode(encoding)
        except (UnicodeEncodeError, LookupError) as err:
            self._refuse(
                ErrorCode.BAD_ENCODING, cause=err, encoding=safe_token(encoding, fallback="text")
            )
        limit = self._limits.max_file_bytes
        if len(data) > limit:
            self._refuse(ErrorCode.FILE_BYTE_CAP, cap="max_file_bytes", limit=limit, size=len(data))
        parent_status = self._status(real.parent)
        if parent_status is not None and not stat_module.S_ISDIR(parent_status.st_mode):
            self._refuse(ErrorCode.NOT_A_DIRECTORY)
        try:
            real.parent.mkdir(parents=True, exist_ok=True)
            # `O_NOFOLLOW` as well: the link check above is by name, and this is the open itself.
            descriptor = os.open(
                real,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o644,
            )
        except OSError as err:
            self._refuse(ErrorCode.WRITE_FAILED, cause=err)
        try:
            _write_all(descriptor, data)
        except OSError as err:
            _close_quietly(descriptor)
            self._refuse(ErrorCode.WRITE_FAILED, cause=err)
        try:
            # Not in a `finally`: a deferred `ENOSPC` or `EIO` surfaces here, after the last
            # `write` returned, and a scaffold that reports success on a truncated file is worse
            # than one that fails.
            os.close(descriptor)
        except OSError as err:
            self._refuse(ErrorCode.WRITE_FAILED, cause=err)
        return real

    # -- checks -----------------------------------------------------------------------------

    def _real(self, path: Path | str) -> Path:
        """`_real`, with a failure turned into a recorded refusal rather than an exception.

        A path carrying a NUL byte raises `ValueError` from the C layer, and `realpath` can raise
        `OSError`; either would otherwise leave the Proxy carrying the path it was given.
        """
        try:
            return _real(path)
        except (OSError, ValueError) as err:
            self._refuse(ErrorCode.BAD_PATH, cause=err)

    def _status(self, path: Path, *, follow: bool = True) -> os.stat_result | None:
        """`stat`, as a refusal rather than an exception, and `None` for "nothing there".

        Every kind test in this module goes through here. `pathlib`'s `exists`, `is_file`,
        `is_dir` and `is_symlink` swallow only a short list of errnos and re-raise the rest, so a
        mode-000 parent directory or a name over `NAME_MAX` would otherwise leave a public method
        as a bare `OSError` carrying the absolute path it was given -- and record no refusal.
        """
        try:
            return os.stat(path, follow_symlinks=follow)
        except (FileNotFoundError, NotADirectoryError):
            return None
        except (OSError, ValueError) as err:
            self._refuse(ErrorCode.PATH_UNREADABLE, cause=err)

    def _check_path(self, path: Path | str) -> Path:
        """Resolve, then the allowlist, then the deny list. Shared by reads and listings."""
        real = self._real(path)
        root = self._containing_root(real)
        if root is None:
            self._refuse(ErrorCode.OUTSIDE_ROOT)
        denied = _denied_pattern(real.relative_to(root).parts)
        if denied is not None:
            self._refuse(ErrorCode.DENIED_NAME, pattern=denied)
        return real

    def _check_read(self, path: Path | str) -> Path:
        real = self._check_path(path)
        status = self._status(real)
        if status is None:
            self._refuse(ErrorCode.MISSING)
        if not stat_module.S_ISREG(status.st_mode):
            self._refuse(ErrorCode.NOT_A_FILE)
        return real

    def _containing_root(self, real: Path) -> Path | None:
        for root in self._roots:
            if _within(real, root):
                return root
        return None

    def _check_caps(self, real: Path, size: int) -> None:
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

    def _charge(self, real: Path, served: int) -> None:
        """Record what was actually served, once the read has happened."""
        self._files.add(real)
        self._bytes += served

    def _refuse(
        self, code: ErrorCode, *, cause: BaseException | None = None, **detail: int | str
    ) -> NoReturn:
        """Record the refusal, then raise it. No code declares a detail field named `cause`."""
        err = KitError(code, **detail)
        self._refusals.append(Refusal.of(err))
        raise err from cause


def _read_up_to(descriptor: int, limit: int) -> bytes:
    """At most `limit` bytes from an open descriptor, looping because `read` may return less."""
    chunks: list[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = os.read(descriptor, min(remaining, 1 << 20))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _within(candidate: Path, root: Path) -> bool:
    return candidate == root or candidate.is_relative_to(root)


def _write_all(descriptor: int, data: bytes) -> None:
    """Write every byte, because `write` may take fewer than it was given."""
    written = 0
    while written < len(data):
        taken = os.write(descriptor, data[written:])
        if taken <= 0:  # pragma: no cover -- POSIX forbids it; a refusal beats a silent loop
            raise OSError(errno.EIO, "the write made no progress")
        written += taken


def _close_quietly(descriptor: int) -> None:
    with contextlib.suppress(OSError):
        os.close(descriptor)
