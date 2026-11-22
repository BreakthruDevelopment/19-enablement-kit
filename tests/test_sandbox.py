"""The sandbox Proxy: one integration test per rule, against a real filesystem.

Every test builds its tree on disk and reads it through a `Sandbox`, because the rules are about
symlinks, path resolution and file sizes -- none of which a mocked filesystem would exercise. The
escape fixtures are built here at test time rather than committed: a symlink to `/etc/passwd` is
not something to put in a public repository.
"""

import os
import traceback
from collections.abc import Iterator
from pathlib import Path

import pytest

from kit.core.config import SandboxLimits
from kit.core.errors import ErrorCode, KitError
from kit.core.principals import Principal
from kit.core.sandbox import DENY_PATTERNS, Sandbox, Usage


def _tree(root: Path) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "src" / "Main.java").write_text("class Main {}\n")
    (root / "README.md").write_text("# oms\n")
    return root


def _sandbox(root: Path, limits: SandboxLimits | None = None) -> Sandbox:
    return Sandbox(Principal.engineer("dev"), [root], limits)


# -- rule 1 and 2: symlinks resolved first, then the root allowlist ---------------------------


def test_a_file_inside_a_root_is_read(tmp_path: Path) -> None:
    box = _sandbox(_tree(tmp_path / "repo"))
    assert box.read_text(tmp_path / "repo" / "src" / "Main.java") == "class Main {}\n"
    assert box.usage.files_read == 1
    assert box.usage.bytes_read == len("class Main {}\n")
    assert box.refusals == ()


def test_a_path_outside_every_root_is_refused(tmp_path: Path) -> None:
    box = _sandbox(_tree(tmp_path / "repo"))
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("secret\n")
    with pytest.raises(KitError) as caught:
        box.read_text(outside)
    assert caught.value.code is ErrorCode.OUTSIDE_ROOT
    assert caught.value.category.value == "permission"


def test_dot_dot_cannot_climb_out_of_a_root(tmp_path: Path) -> None:
    box = _sandbox(_tree(tmp_path / "repo"))
    (tmp_path / "elsewhere.txt").write_text("secret\n")
    with pytest.raises(KitError) as caught:
        box.read_text(tmp_path / "repo" / "src" / ".." / ".." / "elsewhere.txt")
    assert caught.value.code is ErrorCode.OUTSIDE_ROOT


def test_a_symlink_out_of_the_tree_is_refused(tmp_path: Path) -> None:
    # The escape a prefix test on the requested path would miss.
    root = _tree(tmp_path / "repo")
    (tmp_path / "outside.txt").write_text("secret\n")
    (root / "escape.txt").symlink_to(tmp_path / "outside.txt")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "escape.txt")
    assert caught.value.code is ErrorCode.OUTSIDE_ROOT


def test_a_symlinked_directory_out_of_the_tree_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (tmp_path / "away").mkdir()
    (tmp_path / "away" / "notes.txt").write_text("secret\n")
    (root / "away").symlink_to(tmp_path / "away", target_is_directory=True)
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "away" / "notes.txt")
    assert caught.value.code is ErrorCode.OUTSIDE_ROOT


def test_a_symlinked_root_still_serves_its_files(tmp_path: Path) -> None:
    # Resolved to resolved. A raw-root comparison would refuse everything on macOS, where /tmp
    # resolves to /private/tmp, and on a Linux box with a symlinked home.
    real = _tree(tmp_path / "real")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    box = Sandbox(Principal.engineer("dev"), [link])
    assert box.roots == (real.resolve(),)
    assert box.read_text(link / "README.md") == "# oms\n"
    assert box.read_text(real / "README.md") == "# oms\n"


def test_a_root_must_be_an_existing_directory(tmp_path: Path) -> None:
    a_file = tmp_path / "file.txt"
    a_file.write_text("x")
    for roots in ([], [tmp_path / "missing"], [a_file]):
        with pytest.raises(KitError) as caught:
            Sandbox(Principal.engineer("dev"), roots)
        assert caught.value.code is ErrorCode.BAD_ROOT


# -- rule 3: the deny list, per segment of the resolved path ---------------------------------


@pytest.mark.parametrize(
    ("relative", "pattern"),
    [
        (".git/config", ".git"),
        (".env", ".env*"),
        (".env.local", ".env*"),
        ("deploy/key.pem", "*.pem"),
        ("src/id_rsa", "id_*"),
        ("secrets/token.txt", "secrets"),
        (".claude/settings.json", ".claude"),
        ("nested/.git/hooks/pre-push", ".git"),
    ],
)
def test_the_deny_list_refuses_before_the_open(tmp_path: Path, relative: str, pattern: str) -> None:
    root = _tree(tmp_path / "repo")
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("sensitive\n")
    box = _sandbox(root)
    with pytest.raises(KitError) as caught:
        box.read_text(target)
    assert caught.value.code is ErrorCode.DENIED_NAME
    assert caught.value.detail == {"pattern": pattern}
    assert caught.value.category.value == "permission"
    # Refused before the open, so nothing was charged and the refusal is on the record.
    assert box.usage.bytes_read == 0
    assert [refusal.code for refusal in box.refusals] == [ErrorCode.DENIED_NAME]


def test_a_denied_directory_denies_everything_beneath_it(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / "secrets" / "deep" / "deeper").mkdir(parents=True)
    (root / "secrets" / "deep" / "deeper" / "plain.txt").write_text("x\n")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "secrets" / "deep" / "deeper" / "plain.txt")
    assert caught.value.code is ErrorCode.DENIED_NAME


def test_a_symlink_inside_the_root_aimed_at_a_denied_file_is_refused(tmp_path: Path) -> None:
    # The same escape one layer down: resolving for the allowlist but matching the deny list on
    # the requested name would leave exactly this hole.
    root = _tree(tmp_path / "repo")
    (root / ".env").write_text("TOKEN=shh\n")
    (root / "harmless.txt").symlink_to(root / ".env")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "harmless.txt")
    assert caught.value.code is ErrorCode.DENIED_NAME
    assert caught.value.detail == {"pattern": ".env*"}


def test_the_deny_list_is_matched_per_segment_not_as_one_string(tmp_path: Path) -> None:
    # `id_*` against the whole path would match nothing, because a path starts with a slash.
    root = _tree(tmp_path / "repo")
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "id_ed25519").write_text("key\n")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "a" / "b" / "id_ed25519")
    assert caught.value.detail == {"pattern": "id_*"}


def test_a_denied_name_above_the_root_does_not_deny_the_tree(tmp_path: Path) -> None:
    # Matched relative to its root: a checkout that happens to live under a directory called
    # `secrets` is still readable, or the kit would refuse the operator's own layout.
    root = tmp_path / "secrets" / "repo"
    _tree(root)
    assert _sandbox(root).read_text(root / "README.md") == "# oms\n"


def test_an_uppercase_denied_name_is_refused(tmp_path: Path) -> None:
    # On a case-insensitive filesystem `.ENV` opens `.env`; a case-sensitive match alone would
    # let the request through.
    root = _tree(tmp_path / "repo")
    (root / ".ENV").write_text("TOKEN=shh\n")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / ".ENV")
    assert caught.value.code is ErrorCode.DENIED_NAME


def test_the_deny_list_is_the_specified_one() -> None:
    assert DENY_PATTERNS == (".git", ".env*", "*.pem", "id_*", "secrets", ".claude")


# -- rule 4: the three caps ------------------------------------------------------------------


def test_the_per_file_byte_cap_refuses_rather_than_truncates(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / "big.txt").write_text("x" * 200)
    box = _sandbox(root, SandboxLimits(max_file_bytes=100))
    with pytest.raises(KitError) as caught:
        box.read_text(root / "big.txt")
    assert caught.value.code is ErrorCode.FILE_BYTE_CAP
    assert caught.value.category.value == "business"
    assert caught.value.detail == {"cap": "max_file_bytes", "limit": 100, "size": 200}
    # Nothing was served, so no caller can mistake a truncated read for a complete one.
    assert box.usage == Usage(files_read=0, bytes_read=0)


def test_the_per_run_byte_cap_stops_the_run(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    for index in range(3):
        (root / f"f{index}.txt").write_text("x" * 40)
    box = _sandbox(root, SandboxLimits(max_run_bytes=100))
    assert len(box.read_text(root / "f0.txt")) == 40
    assert len(box.read_text(root / "f1.txt")) == 40
    with pytest.raises(KitError) as caught:
        box.read_text(root / "f2.txt")
    assert caught.value.code is ErrorCode.RUN_BYTE_CAP
    assert caught.value.detail["cap"] == "max_run_bytes"
    assert caught.value.detail["limit"] == 100
    assert box.usage.bytes_read == 80


def test_the_file_count_cap_stops_the_run(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    for index in range(3):
        (root / f"f{index}.txt").write_text("x\n")
    box = _sandbox(root, SandboxLimits(max_files=2))
    box.read_text(root / "f0.txt")
    box.read_text(root / "f1.txt")
    with pytest.raises(KitError) as caught:
        box.read_text(root / "f2.txt")
    assert caught.value.code is ErrorCode.FILE_COUNT_CAP
    assert caught.value.detail == {"cap": "max_files", "limit": 2}


def test_re_reading_a_file_costs_bytes_but_not_another_file(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root, SandboxLimits(max_files=1))
    box.read_text(root / "README.md")
    box.read_text(root / "README.md")
    assert box.usage.files_read == 1
    assert box.usage.bytes_read == 2 * len("# oms\n")


def test_a_cap_refusal_is_recorded_for_the_brief(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / "big.txt").write_text("x" * 200)
    box = _sandbox(root, SandboxLimits(max_file_bytes=100))
    with pytest.raises(KitError):
        box.read_text(root / "big.txt")
    refusal = box.refusals[0]
    assert refusal.code is ErrorCode.FILE_BYTE_CAP
    assert refusal.category.value == "business"
    assert "max_file_bytes" in refusal.reason


def test_no_refusal_carries_a_path(tmp_path: Path) -> None:
    # A brief must be able to quote the reason without republishing the path that was refused.
    root = _tree(tmp_path / "repo")
    (root / ".env").write_text("TOKEN=shh\n")
    box = _sandbox(root)
    for target in (root / ".env", tmp_path / "outside.txt"):
        with pytest.raises(KitError):
            box.read_text(target)
    for refusal in box.refusals:
        assert str(root) not in refusal.reason
        assert "TOKEN" not in refusal.reason
        for value in refusal.detail.values():
            assert "/" not in str(value)


# -- existence, kind and decoding -------------------------------------------------------------


def test_a_missing_file_inside_a_root_is_a_validation_error(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "nope.txt")
    assert caught.value.code is ErrorCode.MISSING
    assert caught.value.category.value == "validation"


def test_a_directory_is_not_a_file(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "src")
    assert caught.value.code is ErrorCode.NOT_A_FILE


def test_bytes_that_are_not_text_refuse_rather_than_mangle(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / "oms.jar").write_bytes(b"\xff\xfe\x00binary")
    box = _sandbox(root)
    assert box.read_bytes(root / "oms.jar") == b"\xff\xfe\x00binary"
    with pytest.raises(KitError) as caught:
        box.read_text(root / "oms.jar")
    assert caught.value.code is ErrorCode.UNREADABLE


# -- listing and walking ----------------------------------------------------------------------


def test_list_dir_hides_denied_children_and_records_why(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / ".env").write_text("TOKEN=shh\n")
    (root / ".git").mkdir()
    box = _sandbox(root)
    names = [child.name for child in box.list_dir(root)]
    assert names == ["README.md", "src"]
    assert {refusal.code for refusal in box.refusals} == {ErrorCode.DENIED_NAME}


def test_list_dir_charges_no_cap(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root, SandboxLimits(max_files=1, max_run_bytes=1))
    assert box.list_dir(root)
    assert box.usage.files_read == 0


def test_list_dir_refuses_a_file_and_a_path_outside(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root)
    with pytest.raises(KitError) as caught:
        box.list_dir(root / "README.md")
    assert caught.value.code is ErrorCode.NOT_A_DIRECTORY
    with pytest.raises(KitError) as caught:
        box.list_dir(tmp_path)
    assert caught.value.code is ErrorCode.OUTSIDE_ROOT


def test_walk_finds_the_readable_files_and_prunes_denied_subtrees(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n")
    (root / "secrets").mkdir()
    (root / "secrets" / "token.txt").write_text("shh\n")
    (root / "src" / "dao").mkdir()
    (root / "src" / "dao" / "OrderDao.java").write_text("class OrderDao {}\n")
    found = [path.relative_to(root).as_posix() for path in _sandbox(root).walk(root)]
    assert found == ["README.md", "src/Main.java", "src/dao/OrderDao.java"]


def test_walk_does_not_follow_a_symlink_out_of_the_tree(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (tmp_path / "away").mkdir()
    (tmp_path / "away" / "notes.txt").write_text("secret\n")
    (root / "away").symlink_to(tmp_path / "away", target_is_directory=True)
    found = [path.relative_to(root).as_posix() for path in _sandbox(root).walk(root)]
    assert found == ["README.md", "src/Main.java"]


def test_walk_terminates_on_a_symlink_loop(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / "src" / "loop").symlink_to(root / "src", target_is_directory=True)
    found = [path.relative_to(root).as_posix() for path in _sandbox(root).walk(root)]
    assert found == ["README.md", "src/Main.java"]


# -- writes ------------------------------------------------------------------------------------


def test_writes_are_refused_entirely_for_engineer_and_ci(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    for principal in (Principal.engineer("dev"), Principal.ci()):
        box = Sandbox(principal, [root], write_root=target)
        with pytest.raises(KitError) as caught:
            box.write_text("CLAUDE.md", "# rules\n")
        assert caught.value.code is ErrorCode.FORBIDDEN
        assert caught.value.category.value == "permission"
    assert list(target.iterdir()) == []


def test_lead_writes_only_under_the_write_root(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    written = box.write_text("docs/CLAUDE.md", "# rules\n")
    assert written == (target / "docs" / "CLAUDE.md").resolve()
    assert written.read_text() == "# rules\n"


def test_lead_cannot_write_outside_the_write_root(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    for path in (Path("../escaped.md"), tmp_path / "escaped.md", root / "README.md"):
        with pytest.raises(KitError) as caught:
            box.write_text(path, "x\n")
        assert caught.value.code is ErrorCode.OUTSIDE_ROOT
    assert not (tmp_path / "escaped.md").exists()
    assert (root / "README.md").read_text() == "# oms\n"


def test_lead_cannot_write_through_a_symlinked_parent(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "away").mkdir()
    (target / "away").symlink_to(tmp_path / "away", target_is_directory=True)
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("away/escaped.md", "x\n")
    assert caught.value.code is ErrorCode.OUTSIDE_ROOT
    assert not (tmp_path / "away" / "escaped.md").exists()


def test_lead_cannot_write_a_denied_name(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    for relative in (".git/config", ".env", ".claude/settings.json"):
        with pytest.raises(KitError) as caught:
            box.write_text(relative, "x\n")
        assert caught.value.code is ErrorCode.DENIED_NAME


def test_a_write_without_a_write_root_is_refused(tmp_path: Path) -> None:
    box = Sandbox(Principal.lead("lead"), [_tree(tmp_path / "repo")])
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "x\n")
    assert caught.value.code is ErrorCode.WRITE_FORBIDDEN


def test_a_write_obeys_the_per_file_cap(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(
        Principal.lead("lead"), [root], write_root=target, limits=SandboxLimits(max_file_bytes=10)
    )
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "x" * 11)
    assert caught.value.code is ErrorCode.FILE_BYTE_CAP
    assert not (target / "CLAUDE.md").exists()


# -- several roots ------------------------------------------------------------------------------


def test_several_roots_are_each_allowed(tmp_path: Path) -> None:
    first = _tree(tmp_path / "one")
    second = _tree(tmp_path / "two")
    box = Sandbox(Principal.engineer("dev"), [first, second])
    assert box.read_text(first / "README.md") == "# oms\n"
    assert box.read_text(second / "README.md") == "# oms\n"
    assert box.usage.files_read == 2


# -- what a review found: escapes the rule-by-rule tests above did not reach ------------------


def test_a_write_is_not_followed_through_a_symlinked_destination(tmp_path: Path) -> None:
    # `kit new` writes into a target checkout that is untrusted content, so the destination name
    # itself can be a planted link. Resolving only the parent left the final component raw, and an
    # open follows a link like any other: the write landed on whatever it pointed at.
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("untouched\n")
    (target / "CLAUDE.md").symlink_to(outside)
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "planted\n")
    assert caught.value.code is ErrorCode.WRITE_THROUGH_LINK
    assert caught.value.category.value == "permission"
    assert outside.read_text() == "untouched\n"


def test_a_write_cannot_reach_a_denied_file_through_a_link(tmp_path: Path) -> None:
    # The same escape aimed inside the write root: the deny list would be bypassed on the write
    # path, because the name asked for carries no denied segment.
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    (target / ".env").write_text("TOKEN=shh\n")
    (target / "notes.md").symlink_to(target / ".env")
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("notes.md", "planted\n")
    assert caught.value.code is ErrorCode.WRITE_THROUGH_LINK
    assert (target / ".env").read_text() == "TOKEN=shh\n"


def test_a_write_cannot_reach_outside_through_a_link_in_a_subdirectory(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    (target / "docs").mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("untouched\n")
    (target / "docs" / "CLAUDE.md").symlink_to(outside)
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("docs/CLAUDE.md", "planted\n")
    assert caught.value.code is ErrorCode.WRITE_THROUGH_LINK
    assert outside.read_text() == "untouched\n"


def test_a_write_over_a_directory_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    (target / "docs").mkdir(parents=True)
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    # `docs` is a directory inside the root; `docs/..` resolves to the root itself, which is one
    # too; `..` leaves the root altogether.
    for destination, code in (
        ("docs", ErrorCode.NOT_A_FILE),
        ("docs/..", ErrorCode.NOT_A_FILE),
        ("..", ErrorCode.OUTSIDE_ROOT),
    ):
        with pytest.raises(KitError) as caught:
            box.write_text(destination, "x\n")
        assert caught.value.code is code
    assert (target / "docs").is_dir()


def _understate_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `fstat` report one byte, as a file that grows after the check would.

    Patched on the `os` module itself, which is the object the sandbox calls through.
    """
    real_fstat = os.fstat

    def small(fd: int) -> os.stat_result:
        status = real_fstat(fd)
        return os.stat_result(
            (
                status.st_mode,
                status.st_ino,
                status.st_dev,
                status.st_nlink,
                status.st_uid,
                status.st_gid,
                1,
                int(status.st_atime),
                int(status.st_mtime),
                int(status.st_ctime),
            )
        )

    monkeypatch.setattr(os, "fstat", small)


def test_the_per_file_cap_bounds_the_read_not_just_the_reported_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The size came from a separate call, so it was a claim about the past: a file that grew in
    # between was served whole and `usage` recorded the old number.
    root = _tree(tmp_path / "repo")
    (root / "grows.txt").write_text("x" * 100)
    box = _sandbox(root, SandboxLimits(max_file_bytes=4))
    _understate_size(monkeypatch)
    with pytest.raises(KitError) as caught:
        box.read_bytes(root / "grows.txt")
    assert caught.value.code is ErrorCode.FILE_BYTE_CAP
    assert box.usage == Usage(files_read=0, bytes_read=0)


def test_the_run_cap_bounds_the_read_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path / "repo")
    (root / "grows.txt").write_text("x" * 100)
    box = _sandbox(root, SandboxLimits(max_run_bytes=4))
    _understate_size(monkeypatch)
    with pytest.raises(KitError) as caught:
        box.read_bytes(root / "grows.txt")
    assert caught.value.code is ErrorCode.RUN_BYTE_CAP
    assert box.usage.bytes_read == 0


def test_usage_records_what_was_served(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root)
    served = box.read_bytes(root / "src" / "Main.java")
    assert box.usage == Usage(files_read=1, bytes_read=len(served))


def test_a_file_that_is_not_a_regular_file_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    os.mkfifo(root / "pipe")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_bytes(root / "pipe")
    # Refused before the open, so reading a pipe cannot hang the run either.
    assert caught.value.code is ErrorCode.NOT_A_FILE


def _refuse_iterdir(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make one directory unreadable, the way a mode-000 directory is for a non-root user."""
    real_iterdir = Path.iterdir

    def iterdir(self: Path) -> Iterator[Path]:
        if self.name == name:
            raise PermissionError(13, "Permission denied", str(self))
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)


def test_an_unreadable_directory_is_a_refusal_not_an_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A bare OSError would leave the Proxy carrying the absolute path it was given, which is the
    # one thing no message here may do.
    root = _tree(tmp_path / "repo")
    (root / "locked").mkdir()
    box = _sandbox(root)
    _refuse_iterdir(monkeypatch, "locked")
    with pytest.raises(KitError) as caught:
        box.list_dir(root / "locked")
    assert caught.value.code is ErrorCode.DIRECTORY_UNREADABLE
    assert caught.value.category.value == "internal"
    assert str(root) not in caught.value.message
    assert box.refusals[-1].code is ErrorCode.DIRECTORY_UNREADABLE


def test_walk_carries_on_past_an_unreadable_directory_and_records_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Otherwise an unreadable directory ends the walk, and 19.8's brief gets a crash where it
    # should get named unexplored ground.
    root = _tree(tmp_path / "repo")
    (root / "locked").mkdir()
    (root / "locked" / "hidden.java").write_text("class Hidden {}\n")
    box = _sandbox(root)
    _refuse_iterdir(monkeypatch, "locked")
    found = [path.relative_to(root).as_posix() for path in box.walk(root)]
    assert found == ["README.md", "src/Main.java"]
    assert ErrorCode.DIRECTORY_UNREADABLE in {refusal.code for refusal in box.refusals}


def test_a_path_that_cannot_be_resolved_is_a_refusal(tmp_path: Path) -> None:
    box = _sandbox(_tree(tmp_path / "repo"))
    with pytest.raises(KitError) as caught:
        box.read_text("has\0nul")
    assert caught.value.code is ErrorCode.BAD_PATH
    assert caught.value.category.value == "validation"


def test_two_links_to_one_file_are_one_entry(tmp_path: Path) -> None:
    # `coverage.files_total` is counted from these, so duplicates would overcount.
    root = _tree(tmp_path / "repo")
    (root / "a.java").symlink_to(root / "src" / "Main.java")
    (root / "b.java").symlink_to(root / "src" / "Main.java")
    box = _sandbox(root)
    listed = box.list_dir(root)
    assert len(listed) == len(set(listed))
    walked = box.walk(root)
    assert walked == tuple(sorted({root / "README.md", (root / "src" / "Main.java")}))


def test_a_hard_link_to_a_denied_file_is_served_and_that_is_known(tmp_path: Path) -> None:
    # Named rather than implied: the rules resolve symlinks and match the deny list against the
    # segments of the resolved path, and a hard link has no second path to match. Closing it would
    # mean refusing any file with st_nlink > 1, which the spec does not ask for -- so this test
    # pins the limitation so a later slice changes it deliberately rather than by accident.
    root = _tree(tmp_path / "repo")
    (root / ".env").write_text("TOKEN=shh\n")
    os.link(root / ".env", root / "notes.txt")
    assert _sandbox(root).read_text(root / "notes.txt") == "TOKEN=shh\n"


# -- and what the re-review found: a bare OSError is not a refusal ----------------------------

# A name over NAME_MAX. `pathlib`'s `exists`, `is_file`, `is_dir` and `is_symlink` swallow only a
# short list of errnos and re-raise the rest, so this reaches a public method as `OSError: [Errno
# 36] File name too long: '<absolute path>'` unless every kind test is guarded. It needs no
# privileges, which is why it stands in here for the mode-000 directory a non-root user meets.
_TOO_LONG = "n" * 300


def test_an_unusable_name_is_a_refusal_on_every_read_path(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root)
    for call in (
        lambda: box.read_bytes(root / _TOO_LONG),
        lambda: box.read_text(root / _TOO_LONG),
        lambda: box.list_dir(root / _TOO_LONG),
        lambda: box.walk(root / _TOO_LONG),
    ):
        with pytest.raises(KitError) as caught:
            call()
        assert caught.value.code is ErrorCode.PATH_UNREADABLE
        assert str(root) not in caught.value.message
        assert _TOO_LONG not in caught.value.message
    # Each one is on the record, so `coverage.unread_reason` can name it.
    assert len(box.refusals) == 4


def test_an_unusable_name_is_a_refusal_on_the_write_path(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text(_TOO_LONG, "x\n")
    assert caught.value.code is ErrorCode.PATH_UNREADABLE
    assert _TOO_LONG not in caught.value.message


def test_a_root_that_cannot_be_used_is_a_bad_root(tmp_path: Path) -> None:
    for root in (tmp_path / _TOO_LONG, Path("has\0nul")):
        with pytest.raises(KitError) as caught:
            Sandbox(Principal.engineer("dev"), [root])
        assert caught.value.code is ErrorCode.BAD_ROOT
        assert "nul" not in caught.value.message


def test_a_write_root_that_cannot_be_used_is_a_bad_root(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    with pytest.raises(KitError) as caught:
        Sandbox(Principal.lead("lead"), [root], write_root=tmp_path / _TOO_LONG)
    assert caught.value.code is ErrorCode.BAD_ROOT


def test_content_that_cannot_be_encoded_is_a_refusal(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "café", encoding="ascii")
    assert caught.value.code is ErrorCode.BAD_ENCODING
    assert caught.value.category.value == "validation"
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "hi", encoding="no-such-codec")
    assert caught.value.code is ErrorCode.BAD_ENCODING
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "lone \ud800 surrogate")
    assert caught.value.code is ErrorCode.BAD_ENCODING
    assert not (target / "CLAUDE.md").exists()


def test_a_descriptor_that_is_not_a_regular_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The kind test on the descriptor, not on the name: the only way to reach it is to have the
    # file swapped between the resolve and the open, which is what this stands in for.
    import stat as stat_module

    root = _tree(tmp_path / "repo")
    real_fstat = os.fstat

    def as_fifo(fd: int) -> os.stat_result:
        status = real_fstat(fd)
        mode = (status.st_mode & ~stat_module.S_IFMT(status.st_mode)) | stat_module.S_IFIFO
        return os.stat_result(
            (
                mode,
                status.st_ino,
                status.st_dev,
                status.st_nlink,
                status.st_uid,
                status.st_gid,
                status.st_size,
                int(status.st_atime),
                int(status.st_mtime),
                int(status.st_ctime),
            )
        )

    monkeypatch.setattr(os, "fstat", as_fifo)
    box = _sandbox(root)
    with pytest.raises(KitError) as caught:
        box.read_bytes(root / "README.md")
    assert caught.value.code is ErrorCode.NOT_A_FILE
    assert box.usage == Usage(files_read=0, bytes_read=0)


# -- third review: the walk must finish, and a write must be whole ----------------------------


def test_walk_carries_on_past_an_unresolvable_symlink_cycle(tmp_path: Path) -> None:
    # No monkeypatch and no privileges: `realpath` leaves a two-link cycle unresolved, so the
    # child's `stat` is an ELOOP, and that must not end the walk.
    root = _tree(tmp_path / "repo")
    (root / "loopa").symlink_to(root / "loopb")
    (root / "loopb").symlink_to(root / "loopa")
    box = _sandbox(root)
    found = [path.relative_to(root).as_posix() for path in box.walk(root)]
    assert found == ["README.md", "src/Main.java"]
    assert ErrorCode.PATH_UNREADABLE in {refusal.code for refusal in box.refusals}


def test_a_link_to_the_directory_itself_is_not_one_of_its_children(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    (root / "self").symlink_to(root, target_is_directory=True)
    box = _sandbox(root)
    assert root not in box.list_dir(root)
    assert [path.relative_to(root).as_posix() for path in box.walk(root)] == [
        "README.md",
        "src/Main.java",
    ]


def test_a_short_write_is_finished_not_reported_as_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `write` may take fewer bytes than it is given. Discarding the count left a truncated file
    # reported as a successful scaffold write.
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    real_write = os.write
    calls: list[int] = []

    def grudging(fd: int, data: bytes) -> int:
        taken = real_write(fd, data[:1])
        calls.append(taken)
        return taken

    monkeypatch.setattr(os, "write", grudging)
    written = box.write_text("CLAUDE.md", "# rules\n")
    monkeypatch.undo()
    assert written.read_text() == "# rules\n"
    assert len(calls) == len("# rules\n")


def test_a_failed_write_is_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)

    def no_space(fd: int, data: bytes) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "write", no_space)
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "# rules\n")
    assert caught.value.code is ErrorCode.WRITE_FAILED
    assert caught.value.category.value == "internal"


def test_a_failed_close_is_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A deferred ENOSPC surfaces at `close`, after the last `write` returned, so a `finally` that
    # swallowed it would report a truncated file as written.
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    real_close = os.close

    def failing(fd: int) -> None:
        real_close(fd)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "close", failing)
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "# rules\n")
    monkeypatch.undo()
    assert caught.value.code is ErrorCode.WRITE_FAILED


def test_a_close_failure_on_a_read_does_not_mask_the_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root)
    real_close = os.close

    def failing(fd: int) -> None:
        real_close(fd)
        raise OSError(5, "I/O error")

    monkeypatch.setattr(os, "close", failing)
    content = box.read_text(root / "README.md")
    monkeypatch.undo()
    assert content == "# oms\n"


@pytest.mark.parametrize("encoding", ["café", "n" * 65, "", "utf-8-but-not-really"])
def test_an_unusable_encoding_name_is_still_a_refusal(tmp_path: Path, encoding: str) -> None:
    # The encoding is an argument, so it reaches a message only through the one sanitiser in
    # `errors`. A sanitiser of its own let a name through that `KitError` then refused, turning a
    # refusal into a `ValueError` with nothing recorded.
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "hi", encoding=encoding)
    assert caught.value.code is ErrorCode.BAD_ENCODING
    # Either the name is a safe token and is quoted, or it is replaced by the fallback -- never
    # interpolated raw, and never a `ValueError` out of `KitError` instead of a refusal.
    assert "text" in caught.value.message or encoding in caught.value.message


def test_an_unusable_encoding_name_on_a_read_is_still_a_refusal(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    with pytest.raises(KitError) as caught:
        _sandbox(root).read_text(root / "README.md", encoding="n" * 65)
    assert caught.value.code is ErrorCode.UNREADABLE


def test_a_write_needs_a_directory_for_a_parent(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    (target / "notes.md").write_text("a file, not a directory\n")
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)
    with pytest.raises(KitError) as caught:
        box.write_text("notes.md/CLAUDE.md", "x\n")
    assert caught.value.code is ErrorCode.NOT_A_DIRECTORY
    assert (target / "notes.md").read_text() == "a file, not a directory\n"


def test_an_empty_root_is_not_the_working_directory(tmp_path: Path) -> None:
    candidates: list[list[Path | str]] = [[""], [tmp_path / "repo", ""]]
    for roots in candidates:
        with pytest.raises(KitError) as caught:
            Sandbox(Principal.engineer("dev"), roots)
        assert caught.value.code is ErrorCode.BAD_ROOT


# -- fourth review ----------------------------------------------------------------------------


def test_walk_stays_under_the_directory_it_was_asked_about(tmp_path: Path) -> None:
    # A link to somewhere else inside the roots is readable, but it is not a file *under* this
    # directory, and `coverage.files_total` is counted from here.
    root = _tree(tmp_path / "repo")
    (root / "src" / "up").symlink_to(root, target_is_directory=True)
    found = _sandbox(root).walk(root / "src")
    assert [path.relative_to(root).as_posix() for path in found] == ["src/Main.java"]


def test_a_failed_write_leaves_the_destination_as_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Written through a temporary file and renamed, so a failure cannot leave a truncated file
    # that 19.4's manifest then lists as written.
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    (target / "CLAUDE.md").write_text("# the previous version\n")
    box = Sandbox(Principal.lead("lead"), [root], write_root=target)

    def no_space(fd: int, data: bytes) -> int:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "write", no_space)
    with pytest.raises(KitError) as caught:
        box.write_text("CLAUDE.md", "# the new version, interrupted\n")
    monkeypatch.undo()
    assert caught.value.code is ErrorCode.WRITE_FAILED
    assert (target / "CLAUDE.md").read_text() == "# the previous version\n"
    # And no litter left behind.
    assert [path.name for path in target.iterdir()] == ["CLAUDE.md"]


def test_a_refused_write_capability_is_on_the_record(tmp_path: Path) -> None:
    root = _tree(tmp_path / "repo")
    target = tmp_path / "target"
    target.mkdir()
    box = Sandbox(Principal.ci(), [root], write_root=target)
    with pytest.raises(KitError):
        box.write_text("CLAUDE.md", "x\n")
    # A caller reading `refusals` should not have to know which came from the capability check.
    assert [refusal.code for refusal in box.refusals] == [ErrorCode.FORBIDDEN]


def test_a_root_that_is_itself_a_denied_name_is_refused(tmp_path: Path) -> None:
    # The deny list is matched relative to a root, so `roots=[<repo>/.git]` would have no `.git`
    # segment left to match and would serve everything inside it.
    root = _tree(tmp_path / "repo")
    for name in (".git", "secrets", ".claude"):
        (root / name).mkdir()
        with pytest.raises(KitError) as caught:
            Sandbox(Principal.engineer("dev"), [root / name])
        assert caught.value.code is ErrorCode.BAD_ROOT


def test_an_open_failure_is_a_read_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _tree(tmp_path / "repo")
    box = _sandbox(root)
    real_open = os.open

    def refused(path: object, flags: int, mode: int = 0o777) -> int:
        raise OSError(13, "Permission denied", str(path))

    monkeypatch.setattr(os, "open", refused)
    with pytest.raises(KitError) as caught:
        box.read_bytes(root / "README.md")
    monkeypatch.undo()
    assert real_open is os.open
    assert caught.value.code is ErrorCode.READ_FAILED
    assert caught.value.category.value == "internal"
    assert str(root) not in caught.value.message


def test_a_refusal_does_not_chain_an_exception_carrying_the_path(tmp_path: Path) -> None:
    # An OSError keeps the path in `filename` and in its own message, so a chained cause would
    # put the path back into any traceback a later slice logs. `raise ... from None` leaves no
    # `__cause__` and sets `__suppress_context__`, which is what keeps the context out of a
    # printed traceback.
    root = _tree(tmp_path / "repo")
    box = _sandbox(root)
    with pytest.raises(KitError) as caught:
        box.read_text(root / _TOO_LONG)
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert str(root) not in "".join(traceback.format_exception_only(caught.value))
