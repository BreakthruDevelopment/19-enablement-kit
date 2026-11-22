import json
from pathlib import Path

import pytest

from kit import __version__
from kit.cli import build_parser, main


def test_main_returns_zero_and_names_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert __version__ in capsys.readouterr().out


def test_version_flag_prints_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"kit {__version__}"


def test_unknown_flag_is_rejected() -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--bogus"])
    assert exit_info.value.code == 2


def test_core_package_imports() -> None:
    import kit.core

    assert kit.core.__doc__


def test_new_help_names_the_three_kinds_and_lead(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["new", "--help"])
    assert exit_info.value.code == 0
    text = capsys.readouterr().out
    assert "python-service" in text
    assert "java-legacy-companion" in text
    assert "docs-only" in text
    assert "lead" in text


def test_new_requires_a_target_and_a_scaffold(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as missing_scaffold:
        main(["new", str(tmp_path / "repo")])
    assert missing_scaffold.value.code == 2
    with pytest.raises(SystemExit) as missing_target:
        main(["new", "--scaffold", "docs-only", "--principal", "lead"])
    assert missing_target.value.code == 2
    assert not (tmp_path / "repo").exists()


def test_an_unknown_scaffold_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "repo"
    with pytest.raises(SystemExit) as exit_info:
        main(["new", str(target), "--scaffold", "nope", "--principal", "lead"])
    assert exit_info.value.code == 2
    assert not target.exists()


def test_kit_new_prints_a_manifest_for_lead(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "repo"
    code = main(
        [
            "new",
            str(target),
            "--scaffold",
            "docs-only",
            "--principal",
            "lead",
            "--subject",
            "rollout",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["scaffold"] == "docs-only"
    assert "CLAUDE.md" in payload["files"]
    assert "docs/adr/CLAUDE.md" in payload["files"]
    assert ".claude/skills/write-adr/SKILL.md" in payload["files"]
    assert str(target) not in captured.out
    assert (target / "CLAUDE.md").is_file()
    assert (target / ".claude" / "commands" / "plan.md").is_file()


def test_kit_new_defaults_to_a_principal_that_cannot_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # An environment variable does not promote the run. The default is engineer.
    monkeypatch.setenv("KIT_PRINCIPAL", "lead")
    monkeypatch.setenv("KIT_ROLE", "lead")
    target = tmp_path / "repo"
    code = main(["new", str(target), "--scaffold", "docs-only"])
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "principal.forbidden" in captured.err
    assert str(target) not in captured.err
    assert not target.exists()


@pytest.mark.parametrize("role", ["engineer", "ci"])
def test_kit_new_refuses_a_principal_other_than_lead(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], role: str
) -> None:
    target = tmp_path / "repo"
    code = main(
        ["new", str(target), "--scaffold", "python-service", "--principal", role, "--force"]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "principal.forbidden" in captured.err
    assert not target.exists()


def test_kit_new_refuses_a_bad_subject(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "repo"
    code = main(
        [
            "new",
            str(target),
            "--scaffold",
            "docs-only",
            "--principal",
            "lead",
            "--subject",
            "a b",
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "principal.bad_subject" in captured.err
    assert "a b" not in captured.err
    assert not target.exists()


def test_kit_new_refuses_a_non_empty_target_unless_forced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    (target / "README.md").write_text("keep\n")
    refused = main(["new", str(target), "--scaffold", "docs-only", "--principal", "lead"])
    assert refused == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "scaffold.target_not_empty" in captured.err
    assert str(target) not in captured.err
    assert (target / "README.md").read_text(encoding="utf-8") == "keep\n"
    assert not (target / "CLAUDE.md").exists()
    forced = main(["new", str(target), "--scaffold", "docs-only", "--principal", "lead", "--force"])
    assert forced == 0
    assert (target / "README.md").read_text(encoding="utf-8") == "keep\n"
    assert (target / "CLAUDE.md").is_file()
