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
