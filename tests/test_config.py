"""Configuration: defaults, strict validation, and messages that quote nothing."""

from pathlib import Path

import pytest

from kit.core.config import Config, GatewayConfig, SandboxLimits
from kit.core.errors import ErrorCode, KitError


def test_the_defaults_replay_and_name_the_gateway_command() -> None:
    config = Config.default()
    assert config.gateway.command == "p2p-erp"
    assert config.gateway.args == ()
    # Replay is the default everywhere: no app 18, no network, no cost.
    assert config.gateway.live is False
    assert config.contract_path == Path("contracts/p2p-erp.json")
    assert config.sandbox.max_file_bytes > 0
    assert config.sandbox.max_run_bytes > config.sandbox.max_file_bytes
    assert config.sandbox.max_files > 0


def test_a_file_overrides_what_it_names_and_nothing_else(tmp_path: Path) -> None:
    path = tmp_path / "kit.toml"
    path.write_text(
        """
        [sandbox]
        max_file_bytes = 2048

        [gateway]
        command = "p2p-erp"
        args = ["--company", "1000"]
        live = true
        """
    )
    config = Config.from_toml(path)
    assert config.sandbox.max_file_bytes == 2048
    assert config.sandbox.max_files == SandboxLimits().max_files
    assert config.gateway.args == ("--company", "1000")
    assert config.gateway.live is True


def test_a_missing_file_is_unreadable_not_a_crash(tmp_path: Path) -> None:
    with pytest.raises(KitError) as caught:
        Config.from_toml(tmp_path / "absent.toml")
    assert caught.value.code is ErrorCode.CONFIG_UNREADABLE
    assert caught.value.category.value == "validation"


def test_broken_toml_is_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "kit.toml"
    path.write_text("[sandbox\n")
    with pytest.raises(KitError) as caught:
        Config.from_toml(path)
    assert caught.value.code is ErrorCode.CONFIG_UNREADABLE


def test_an_unknown_key_is_refused_not_ignored() -> None:
    # A typo in a cap must be an error, or the sandbox is silently more generous than intended.
    with pytest.raises(KitError) as caught:
        Config.from_mapping({"sandbox": {"max_file_byte": 10}})
    assert caught.value.code is ErrorCode.CONFIG_INVALID


def test_a_cap_must_be_positive() -> None:
    for field in ("max_file_bytes", "max_run_bytes", "max_files"):
        with pytest.raises(KitError) as caught:
            Config.from_mapping({"sandbox": {field: 0}})
        assert caught.value.code is ErrorCode.CONFIG_INVALID
        assert caught.value.detail["field"] == f"sandbox.{field}"


def test_a_known_field_is_named_and_the_value_is_not() -> None:
    with pytest.raises(KitError) as caught:
        Config.from_mapping({"sandbox": {"max_files": "lots"}})
    assert caught.value.detail["field"] == "sandbox.max_files"
    assert "lots" not in caught.value.message


def test_a_hostile_key_cannot_reach_the_message() -> None:
    # `extra="forbid"` reports an unknown key under its own name, which is parsed input. The field
    # path is checked against the paths derived from the models, so this one becomes a token.
    hostile = "../../etc/passwd"
    with pytest.raises(KitError) as caught:
        Config.from_mapping({hostile: 1})
    assert caught.value.detail["field"] == "unrecognized"
    assert hostile not in caught.value.message
    assert "passwd" not in caught.value.message


def test_the_models_are_frozen() -> None:
    config = Config.default()
    with pytest.raises(ValueError, match="frozen"):
        config.sandbox.max_files = 1
    with pytest.raises(ValueError, match="frozen"):
        config.gateway.command = "other"


def test_an_empty_gateway_command_is_refused() -> None:
    with pytest.raises(KitError) as caught:
        Config.from_mapping({"gateway": {"command": ""}})
    assert caught.value.detail["field"] == "gateway.command"
    assert GatewayConfig().command == "p2p-erp"
