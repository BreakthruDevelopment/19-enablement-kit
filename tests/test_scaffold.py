"""The scaffold factory: golden files, and the write rules around `kit new`.

The committed templates are the golden bytes. `EXPECTED` is the golden manifest: each
output path, in order, and nothing else. The factory must reproduce those bytes under
the target root. A change to a template shows up in review; a factory that drops,
moves or alters a byte fails here.
"""

from __future__ import annotations

import difflib
import errno
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import cast

import pytest

from kit.core.config import SandboxLimits
from kit.core.errors import ErrorCode, KitError
from kit.core.principals import Capability, Principal, assert_can
from kit.scaffold.errors import ScaffoldCode, ScaffoldError
from kit.scaffold.factory import Manifest, write_scaffold
from kit.scaffold.templates import Kind, LoadedTemplate

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "kit" / "scaffold" / "templates"

# Output paths the factory must write, sorted. The source file for a `.claude/...`
# path is the same path with that prefix removed (`rules/`, `commands/`, `skills/`).
EXPECTED: dict[Kind, tuple[str, ...]] = {
    Kind.PYTHON_SERVICE: (
        ".claude/commands/explain.md",
        ".claude/commands/plan.md",
        ".claude/commands/review.md",
        ".claude/rules/python-sources.md",
        ".claude/rules/python-tests.md",
        ".claude/skills/add-endpoint/SKILL.md",
        ".claude/skills/write-test/SKILL.md",
        "CLAUDE.md",
        "src/CLAUDE.md",
        "tests/CLAUDE.md",
    ),
    Kind.JAVA_LEGACY_COMPANION: (
        ".claude/commands/cite.md",
        ".claude/commands/plan.md",
        ".claude/commands/review.md",
        ".claude/rules/descriptors.md",
        ".claude/rules/java-sources.md",
        ".claude/rules/jsp.md",
        ".claude/rules/sql.md",
        ".claude/skills/review-dao/SKILL.md",
        ".claude/skills/trace-call/SKILL.md",
        "CLAUDE.md",
        "dd/CLAUDE.md",
        "sql/CLAUDE.md",
        "src/CLAUDE.md",
        "web/CLAUDE.md",
    ),
    Kind.DOCS_ONLY: (
        ".claude/commands/draft.md",
        ".claude/commands/plan.md",
        ".claude/commands/review.md",
        ".claude/rules/adr.md",
        ".claude/rules/prose.md",
        ".claude/skills/cite-source/SKILL.md",
        ".claude/skills/write-adr/SKILL.md",
        "CLAUDE.md",
        "docs/CLAUDE.md",
        "docs/adr/CLAUDE.md",
    ),
}

_DENY = {".git", ".env*", "*.pem", "id_*", "secrets"}


def _source_for(output: str) -> str:
    prefix = ".claude/"
    if output.startswith(prefix):
        return output[len(prefix) :]
    return output


def _tree_bytes(root: Path) -> dict[str, bytes]:
    found: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise AssertionError(f"symlink in the tree: {path.name}")
        if path.is_file():
            found[path.relative_to(root).as_posix()] = path.read_bytes()
    return found


def _frontmatter(text: str) -> str:
    assert text.startswith("---\n")
    end = text.find("\n---\n", 3)
    assert end > 0
    return text[4:end]


def _lead() -> Principal:
    return Principal.lead("lead")


def _build(code: ScaffoldCode) -> ScaffoldError:
    if code is ScaffoldCode.DENIED_NAME:
        return ScaffoldError(code, pattern=".env*")
    return ScaffoldError(code)


def _patch_loader(monkeypatch: pytest.MonkeyPatch, loaded: Sequence[LoadedTemplate]) -> None:
    def fake(_kind: Kind) -> tuple[LoadedTemplate, ...]:
        return tuple(loaded)

    monkeypatch.setattr("kit.scaffold.factory.load_kind", fake)


def test_there_are_three_scaffold_kinds() -> None:
    assert [kind.value for kind in Kind] == [
        "python-service",
        "java-legacy-companion",
        "docs-only",
    ]


def test_the_golden_manifests_are_sorted_and_distinct() -> None:
    sets = [set(EXPECTED[kind]) for kind in Kind]
    assert len({frozenset(item) for item in sets}) == 3
    for kind in Kind:
        assert EXPECTED[kind] == tuple(sorted(EXPECTED[kind]))
        assert "CLAUDE.md" in EXPECTED[kind]


@pytest.mark.parametrize("kind", list(Kind))
def test_scaffold_matches_the_golden_files(tmp_path: Path, kind: Kind) -> None:
    target = tmp_path / "repo"
    manifest = write_scaffold(target, kind, _lead())
    expected = EXPECTED[kind]
    written = _tree_bytes(target)
    golden_root = TEMPLATES / kind.value
    on_disk = _tree_bytes(golden_root)
    assert set(on_disk) == {_source_for(output) for output in expected}
    assert tuple(sorted(written)) == expected
    assert manifest.files == expected
    assert manifest.scaffold is kind
    mismatches = [
        output
        for output in expected
        if written[output] != (golden_root / _source_for(output)).read_bytes()
    ]
    if mismatches:
        chunks: list[str] = []
        for output in mismatches[:3]:
            left = (
                (golden_root / _source_for(output))
                .read_text(encoding="utf-8")
                .splitlines(keepends=True)
            )
            right = written[output].decode("utf-8").splitlines(keepends=True)
            chunks.extend(
                difflib.unified_diff(left, right, fromfile=f"golden/{output}", tofile=output)
            )
        pytest.fail("".join(chunks))
    blob = b"\n".join(written.values())
    assert str(target).encode() not in blob
    assert b"$ARGUMENTS" in blob
    assert list(target.rglob(".kit-*")) == []


@pytest.mark.parametrize("kind", list(Kind))
def test_each_kind_has_a_hierarchy_rules_commands_and_skills(kind: Kind) -> None:
    # Statements 3.1, 3.2 and 3.3: the hierarchy, the commands and skills, the rules.
    files = EXPECTED[kind]
    claude = [path for path in files if path == "CLAUDE.md" or path.endswith("/CLAUDE.md")]
    rules = [path for path in files if path.startswith(".claude/rules/") and path.endswith(".md")]
    commands = [path for path in files if "/commands/" in path and path.endswith(".md")]
    skills = [path for path in files if path.endswith("/SKILL.md")]
    assert len(claude) >= 2
    assert len(rules) >= 2
    assert len(commands) >= 2
    assert len(skills) >= 2
    root = (TEMPLATES / kind.value / "CLAUDE.md").read_text(encoding="utf-8")
    assert "root of the CLAUDE.md hierarchy" in root
    assert ".claude/rules/" in root
    assert ".claude/commands/" in root
    assert ".claude/skills/" in root
    assert "@" not in root
    for path in claude:
        text = (TEMPLATES / kind.value / _source_for(path)).read_text(encoding="utf-8")
        assert "@" not in text
        if path == "CLAUDE.md":
            continue
        assert "layer of the CLAUDE.md hierarchy" in text
        assert not text.startswith("---")
    for path in rules:
        text = (TEMPLATES / kind.value / _source_for(path)).read_text(encoding="utf-8")
        front = _frontmatter(text)
        # A scalar, on one line, quoted. Not a YAML block list: Claude Code's loader reads this
        # value as a string and splits it on commas, so `- "a"` / `- "b"` arrives concatenated
        # as `ab` and the rule then matches nothing. A one-element list survives that by
        # accident, which is why only the two-element rule was dead and why the shape, not the
        # presence, is what this pins.
        assert re.search(r'^paths: "[^"\n]+"$', front, re.M), path
        assert "\n  - " not in front, path
    for path in commands:
        text = (TEMPLATES / kind.value / _source_for(path)).read_text(encoding="utf-8")
        front = _frontmatter(text)
        assert "description:" in front
        stem = Path(path).stem
        assert f"/{stem}" in text
        assert "$ARGUMENTS" in text
    for path in skills:
        text = (TEMPLATES / kind.value / _source_for(path)).read_text(encoding="utf-8")
        front = _frontmatter(text)
        assert f"name: {Path(path).parent.name}" in front
        assert "description:" in front


def test_the_manifest_is_relative_paths_only(tmp_path: Path) -> None:
    target = tmp_path / "my repo"
    manifest = write_scaffold(target, Kind.DOCS_ONLY, _lead())
    rendered = manifest.render()
    assert str(target) not in rendered
    assert "my repo" not in rendered
    payload = json.loads(rendered)
    assert list(payload) == ["scaffold", "files"]
    assert payload == {"scaffold": "docs-only", "files": list(EXPECTED[Kind.DOCS_ONLY])}
    assert rendered.endswith("\n")


def test_assert_can_runs_with_the_acting_principal_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    seen: list[tuple[Principal, Capability]] = []

    def spy(principal: Principal, capability: Capability, *, owner: str | None = None) -> None:
        assert not target.exists()
        seen.append((principal, capability))
        assert_can(principal, capability, owner=owner)

    # Patch the name the factory calls. `assert_can` is not part of its public export.
    monkeypatch.setattr("kit.scaffold.factory.assert_can", spy)
    lead = Principal.lead("rollout")
    write_scaffold(target, Kind.DOCS_ONLY, lead)
    assert seen == [(lead, Capability.WRITE_TARGET)]
    assert (target / "CLAUDE.md").is_file()


def test_a_principal_other_than_lead_is_refused_before_the_target_is_touched(
    tmp_path: Path,
) -> None:
    # Non-empty, and no --force. Emptiness would also refuse, with a different code.
    # Forbidden means the principal was checked first.
    target = tmp_path / "repo"
    target.mkdir()
    (target / "keep.txt").write_text("stay\n")
    for principal in (Principal.engineer("dev"), Principal.ci()):
        with pytest.raises(KitError) as caught:
            write_scaffold(target, Kind.PYTHON_SERVICE, principal, force=True)
        assert caught.value.code is ErrorCode.FORBIDDEN
        assert caught.value.category.value == "permission"
        assert str(target) not in str(caught.value)
    assert [path.name for path in target.iterdir()] == ["keep.txt"]
    assert (target / "keep.txt").read_text(encoding="utf-8") == "stay\n"


def test_a_refused_principal_does_not_create_a_missing_target(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    with pytest.raises(KitError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, Principal.engineer("dev"))
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert not target.exists()


def test_an_unknown_kind_is_refused_after_the_principal_check(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, cast(Kind, "bundle"), _lead())
    assert caught.value.code is ScaffoldCode.UNKNOWN_KIND
    assert not target.exists()
    with pytest.raises(KitError) as forbidden:
        write_scaffold(target, cast(Kind, "bundle"), Principal.engineer("dev"))
    assert forbidden.value.code is ErrorCode.FORBIDDEN
    assert not target.exists()


def test_force_must_be_a_bool(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead(), force=cast(bool, "yes"))
    assert caught.value.code is ScaffoldCode.BAD_INVOCATION
    assert not target.exists()


def test_a_non_empty_target_is_refused_without_force(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("keep\n")
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.TARGET_NOT_EMPTY
    assert caught.value.category.value == "validation"
    assert str(target) not in str(caught.value)
    assert (target / "README.md").read_text(encoding="utf-8") == "keep\n"
    assert not (target / "CLAUDE.md").exists()


def test_an_empty_directory_does_not_need_force(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    manifest = write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert isinstance(manifest, Manifest)
    assert (target / "CLAUDE.md").is_file()


def test_a_missing_directory_is_created(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert target.is_dir()
    assert (target / "docs" / "adr" / "CLAUDE.md").is_file()


def test_a_missing_parent_is_not_created(tmp_path: Path) -> None:
    target = tmp_path / "missing" / "repo"
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.TARGET_UNUSABLE
    assert not (tmp_path / "missing").exists()


def test_a_file_target_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "notes.md"
    target.write_text("keep\n")
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.TARGET_UNUSABLE
    assert target.read_text(encoding="utf-8") == "keep\n"


def test_a_symlink_target_is_not_followed(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "keep.txt").write_text("stay\n")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(link, Kind.DOCS_ONLY, _lead(), force=True)
    assert caught.value.code is ScaffoldCode.THROUGH_LINK
    assert (real / "keep.txt").read_text(encoding="utf-8") == "stay\n"
    assert not (real / "CLAUDE.md").exists()


def test_a_linked_directory_on_a_scaffold_path_refuses_the_whole_write(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker").write_text("stay\n")
    (target / "src").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.PYTHON_SERVICE, _lead(), force=True)
    assert caught.value.code is ScaffoldCode.THROUGH_LINK
    assert (outside / "marker").read_text(encoding="utf-8") == "stay\n"
    assert not (outside / "CLAUDE.md").exists()
    assert [path.name for path in target.iterdir()] == ["src"]


def test_a_linked_file_on_a_scaffold_path_is_not_replaced(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("stay\n")
    (target / "CLAUDE.md").symlink_to(outside)
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead(), force=True)
    assert caught.value.code is ScaffoldCode.THROUGH_LINK
    assert outside.read_text(encoding="utf-8") == "stay\n"
    assert not (target / "docs").exists()


def test_a_sibling_symlink_is_left_alone(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "marker").write_text("stay\n")
    (target / "unrelated").symlink_to(outside, target_is_directory=True)
    write_scaffold(target, Kind.DOCS_ONLY, _lead(), force=True)
    assert (outside / "marker").read_text(encoding="utf-8") == "stay\n"
    assert not (outside / "CLAUDE.md").exists()
    assert (target / "CLAUDE.md").is_file()
    assert (target / "unrelated").is_symlink()


def test_a_directory_where_a_file_belongs_refuses_the_whole_write(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "CLAUDE.md").mkdir()
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead(), force=True)
    assert caught.value.code is ScaffoldCode.PATH_OCCUPIED
    assert (target / "CLAUDE.md").is_dir()
    assert not (target / ".claude").exists()


def test_a_file_where_a_directory_belongs_refuses_the_whole_write(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "src").write_text("not a directory\n")
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.PYTHON_SERVICE, _lead(), force=True)
    assert caught.value.code is ScaffoldCode.PATH_OCCUPIED
    assert (target / "src").read_text(encoding="utf-8") == "not a directory\n"
    assert not (target / "CLAUDE.md").exists()


def test_force_overwrites_scaffold_files_and_keeps_the_rest(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("keep\n")
    (target / "notes").mkdir()
    (target / "CLAUDE.md").write_text("old\n")
    write_scaffold(target, Kind.DOCS_ONLY, _lead(), force=True)
    assert (target / "README.md").read_text(encoding="utf-8") == "keep\n"
    assert (target / "notes").is_dir()
    golden = (TEMPLATES / "docs-only" / "CLAUDE.md").read_bytes()
    assert (target / "CLAUDE.md").read_bytes() == golden


def test_a_second_run_without_force_refuses_and_a_third_with_force_matches(
    tmp_path: Path,
) -> None:
    target = tmp_path / "repo"
    first = write_scaffold(target, Kind.DOCS_ONLY, _lead())
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.TARGET_NOT_EMPTY
    second = write_scaffold(target, Kind.DOCS_ONLY, _lead(), force=True)
    assert first.files == second.files
    assert _tree_bytes(target) == {
        output: (TEMPLATES / "docs-only" / _source_for(output)).read_bytes()
        for output in EXPECTED[Kind.DOCS_ONLY]
    }


def test_a_relative_target_stays_in_the_named_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    before = Path.cwd()
    write_scaffold(Path("../repo"), Kind.DOCS_ONLY, _lead())
    assert Path.cwd() == before
    assert (repo / "CLAUDE.md").is_file()
    assert not (work / "CLAUDE.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_dot_scaffolds_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    monkeypatch.chdir(target)
    write_scaffold(Path("."), Kind.DOCS_ONLY, _lead())
    assert (target / "CLAUDE.md").is_file()
    assert not (tmp_path / "CLAUDE.md").exists()


def test_a_nul_in_the_target_is_refused_without_quoting_it(tmp_path: Path) -> None:
    raw = str(tmp_path / "repo") + "/has\0nul"
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(raw, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.UNREADABLE
    assert "nul" not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_a_resolved_directory_outside_the_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real_realpath = os.path.realpath

    def flipped(path: str | Path) -> str:
        text = os.fspath(path)
        if text.endswith(f"{os.sep}docs") or f"{os.sep}docs{os.sep}" in text:
            return str(outside)
        return real_realpath(path)

    monkeypatch.setattr(os.path, "realpath", flipped)
    try:
        with pytest.raises(ScaffoldError) as caught:
            write_scaffold(target, Kind.DOCS_ONLY, _lead())
    finally:
        monkeypatch.undo()
    assert caught.value.code is ScaffoldCode.OUTSIDE_TARGET
    assert list(outside.iterdir()) == []
    assert not (target / "CLAUDE.md").exists()


def test_a_failed_write_leaves_no_scaffold_file_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    target.mkdir()

    def no_space(_fd: int, _data: bytes) -> int:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "write", no_space)
    try:
        with pytest.raises(ScaffoldError) as caught:
            write_scaffold(target, Kind.DOCS_ONLY, _lead())
    finally:
        monkeypatch.undo()
    assert caught.value.code is ScaffoldCode.WRITE_FAILED
    assert caught.value.category.value == "internal"
    for relative in EXPECTED[Kind.DOCS_ONLY]:
        assert not (target / relative).exists()
    assert list(target.rglob(".kit-*")) == []


def test_every_rule_glob_is_a_single_comma_separated_value() -> None:
    # The dead rule this pins was `paths:` with two block-list entries, which the loader read as
    # one concatenated glob (`dd/**/*.xmlweb/**/*.xml`) that matches no file. Both of the
    # descriptors globs must survive as separate globs on one line.
    descriptors = (
        TEMPLATES / Kind.JAVA_LEGACY_COMPANION.value / "rules" / "descriptors.md"
    ).read_text(encoding="utf-8")
    front = _frontmatter(descriptors)
    match = re.search(r'^paths: "([^"\n]+)"$', front, re.M)
    assert match, front
    globs = [part.strip() for part in match.group(1).split(",")]
    assert globs == ["dd/**/*.xml", "web/**/*.xml"]
    for glob in globs:
        assert "*.xml" in glob and glob.count("**") == 1


def test_an_empty_target_is_refused_and_is_not_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `Path("")` is relative, so an empty target would resolve to the working directory and
    # scaffold whatever the caller is standing in -- with `force`, over the top of it. The CLI
    # refuses it, but `write_scaffold` is exported and later slices call it directly.
    monkeypatch.chdir(tmp_path)
    keep = tmp_path / "CLAUDE.md"
    keep.write_text("mine\n", encoding="utf-8")
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold("", Kind.DOCS_ONLY, _lead(), force=True)
    assert caught.value.code is ScaffoldCode.TARGET_UNUSABLE
    # The same refusal, and the same reasoning, as `kit.core.sandbox._as_root`: `realpath("")` is
    # the working directory, and that is not a reasonable reading of an empty string. (`Path("")`
    # is already `Path(".")` by the time it arrives, so an explicit `.` still means here.)
    assert keep.read_text(encoding="utf-8") == "mine\n"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["CLAUDE.md"]


@pytest.mark.parametrize(
    "output",
    [
        "a" * 129,
        "/".join(["d"] * 17),
        "dir\\file.md",
        "dir//file.md",
        "../escape.md",
        "./here.md",
    ],
)
def test_template_output_paths_outside_the_shape_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, output: str
) -> None:
    # The segment length, the depth and the backslash rule had no test of their own.
    target = tmp_path / "repo"
    _patch_loader(monkeypatch, (LoadedTemplate(output, b"body\n"),))
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.BAD_TEMPLATE
    assert not target.exists()


def test_a_failure_on_a_later_item_leaves_no_staged_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `_discard` was unexercised: the existing write-failure tests fail on the *first* item, so
    # only `_cleanup_stage` ran. Fail on a later one and every earlier temporary must go too.
    target = tmp_path / "repo"
    target.mkdir()
    real_write = os.write
    seen: list[int] = []

    def failing(fd: int, data: bytes) -> int:
        # Count calls, not distinct descriptors: each staged file is opened, written and closed,
        # so the kernel hands the same number straight back and a set of fds stays tiny.
        seen.append(fd)
        if len(seen) > 3:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", failing)
    try:
        with pytest.raises(ScaffoldError) as caught:
            write_scaffold(target, Kind.DOCS_ONLY, _lead())
    finally:
        monkeypatch.undo()
    assert caught.value.code is ScaffoldCode.WRITE_FAILED
    assert len(seen) > 3  # it really did get past the first few files
    assert list(target.rglob(".kit-*")) == []
    for relative in EXPECTED[Kind.DOCS_ONLY]:
        assert not (target / relative).exists()


def test_a_failed_close_is_a_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    real_close = os.close

    def failing(fd: int) -> None:
        real_close(fd)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(os, "close", failing)
    try:
        with pytest.raises(ScaffoldError) as caught:
            write_scaffold(target, Kind.DOCS_ONLY, _lead())
    finally:
        monkeypatch.undo()
    assert caught.value.code is ScaffoldCode.WRITE_FAILED
    assert not (target / "CLAUDE.md").exists()
    assert list(target.rglob(".kit-*")) == []


def test_a_short_write_is_finished(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "repo"
    real_write = os.write
    calls: list[int] = []

    payloads: list[bytes] = []

    def grudging(fd: int, data: bytes) -> int:
        taken = real_write(fd, data[:1])
        calls.append(taken)
        payloads.append(data[:taken])
        return taken

    monkeypatch.setattr(os, "write", grudging)
    try:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    finally:
        monkeypatch.undo()
    written = _tree_bytes(target)
    assert set(written) == set(EXPECTED[Kind.DOCS_ONLY])
    # Compare what landed with a tree written by an unhobbled `os.write`, not two counts that
    # shrink together: a `sum(len(...)) == len(calls)` assertion holds for any truncating writer,
    # including one that writes a single byte per file and stops.
    control = tmp_path / "control"
    write_scaffold(control, Kind.DOCS_ONLY, _lead())
    assert written == _tree_bytes(control)
    assert all(len(payload) == 1 for payload in payloads)  # the stub really was grudging
    assert len(calls) == sum(len(payload) for payload in written.values())


@pytest.mark.parametrize(
    "content",
    [b"", b"no-newline", b"cr\r\n", b"\xff\n", b"nul\x00\n"],
)
def test_unusable_template_bytes_are_refused_before_create(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    target = tmp_path / "repo"
    _patch_loader(monkeypatch, (LoadedTemplate("CLAUDE.md", content),))
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.BAD_TEMPLATE
    assert not target.exists()


def test_a_template_over_the_sandbox_cap_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    cap = SandboxLimits().max_file_bytes
    # One byte over the cap and otherwise *valid*: UTF-8, no NUL, no CR, and it ends with a
    # newline. `b"x" * (cap + 1)` has no trailing newline, so `_check_content`'s newline rule
    # refuses it too and the test passed with the cap deleted.
    over = b"x" * cap + b"\n"
    assert len(over) == cap + 1 and over.endswith(b"\n")
    _patch_loader(monkeypatch, (LoadedTemplate("CLAUDE.md", over),))
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.BAD_TEMPLATE
    assert not target.exists()


def test_an_empty_template_set_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "repo"
    _patch_loader(monkeypatch, ())
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.BAD_TEMPLATE
    assert not target.exists()


def test_a_duplicate_output_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "repo"
    _patch_loader(
        monkeypatch,
        (
            LoadedTemplate("CLAUDE.md", b"one\n"),
            LoadedTemplate("CLAUDE.md", b"two\n"),
        ),
    )
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.BAD_TEMPLATE
    assert not target.exists()


@pytest.mark.parametrize(
    "relative",
    ["../escape.md", "/opt/escape.md", "a//b.md", "foo/../../etc/passwd", "bad name.md"],
)
def test_a_template_path_that_can_leave_the_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    target = tmp_path / "repo"
    _patch_loader(monkeypatch, (LoadedTemplate(relative, b"x\n"),))
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.BAD_TEMPLATE
    assert "escape" not in str(caught.value)
    assert "passwd" not in str(caught.value)
    assert not target.exists()


@pytest.mark.parametrize(
    "relative",
    [".env", ".ENV", "secrets/a.md", "id_rsa", "keys/server.pem", ".git/config", ".claude/.env"],
)
def test_a_secret_shaped_template_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    target = tmp_path / "repo"
    _patch_loader(monkeypatch, (LoadedTemplate(relative, b"TOKEN=no\n"),))
    with pytest.raises(ScaffoldError) as caught:
        write_scaffold(target, Kind.DOCS_ONLY, _lead())
    assert caught.value.code is ScaffoldCode.DENIED_NAME
    assert caught.value.category.value == "permission"
    assert caught.value.detail["pattern"] in _DENY
    assert "TOKEN" not in str(caught.value)
    assert "a.md" not in str(caught.value)
    assert not target.exists()


def test_every_scaffold_code_renders_without_a_path() -> None:
    for code in ScaffoldCode:
        err = _build(code)
        assert err.message.startswith(f"{code.value}: ")
        assert "{" not in err.message
        assert "\n" not in err.message
        assert "/" not in err.message
        assert err.is_retryable is False
        assert err.message == str(err)


def test_permission_validation_and_internal_stay_distinct() -> None:
    assert _build(ScaffoldCode.THROUGH_LINK).category.value == "permission"
    assert _build(ScaffoldCode.OUTSIDE_TARGET).category.value == "permission"
    assert _build(ScaffoldCode.DENIED_NAME).category.value == "permission"
    assert _build(ScaffoldCode.TARGET_NOT_EMPTY).category.value == "validation"
    assert _build(ScaffoldCode.UNKNOWN_KIND).category.value == "validation"
    assert _build(ScaffoldCode.BAD_TEMPLATE).category.value == "internal"
    assert _build(ScaffoldCode.WRITE_FAILED).category.value == "internal"
    assert _build(ScaffoldCode.UNREADABLE).category.value == "internal"


def test_a_detail_cannot_carry_a_path() -> None:
    with pytest.raises(ValueError, match="safe token"):
        ScaffoldError(ScaffoldCode.DENIED_NAME, pattern="../secret")
    with pytest.raises(ValueError, match="exactly the fields"):
        ScaffoldError(ScaffoldCode.THROUGH_LINK, pattern=".env*")
    err = _build(ScaffoldCode.DENIED_NAME)
    with pytest.raises(TypeError):
        cast(dict[str, str], err.detail)["pattern"] = "no"
