"""Errors carry an app-17 category and a retry flag, and never echo parsed input."""

import pytest
from agent_container.core.tool import ErrorCategory

from kit.core.errors import ErrorCode, KitError, safe_token


def test_every_code_has_a_category_and_renders() -> None:
    for code in ErrorCode:
        err = _build(code)
        assert isinstance(err.category, ErrorCategory)
        assert err.message.startswith(f"{code.value}: ")
        assert "{" not in err.message


def test_only_transient_is_retryable() -> None:
    # Nothing the foundation refuses is transient: a cap, a deny-list name and a root are the same
    # next time, so a retry is wrong rather than unlucky.
    for code in ErrorCode:
        err = _build(code)
        assert err.is_retryable == (err.category is ErrorCategory.TRANSIENT)
        assert not err.is_retryable


def test_as_dict_is_the_log_and_mcp_shape() -> None:
    err = KitError(ErrorCode.FILE_BYTE_CAP, cap="max_file_bytes", limit=1024, size=4096)
    assert err.as_dict() == {
        "code": "sandbox.file_byte_cap",
        "error_category": "business",
        "is_retryable": False,
        "message": err.message,
        "detail": {"cap": "max_file_bytes", "limit": 1024, "size": 4096},
    }


def test_as_tool_result_is_an_app_17_error_result() -> None:
    result = KitError(ErrorCode.OUTSIDE_ROOT).as_tool_result()
    assert result.is_error
    assert result.error_category is ErrorCategory.PERMISSION
    assert result.is_retryable is False
    assert result.content == "sandbox.outside_root: the resolved path is outside every allowed root"


def test_a_path_cannot_be_put_in_a_detail() -> None:
    # The guard that keeps a hostile path out of a log line: a value with a separator is refused
    # at construction rather than interpolated into the message.
    with pytest.raises(ValueError, match="safe token"):
        KitError(ErrorCode.DENIED_NAME, pattern="/home/victim/.ssh/id_rsa")


def test_a_code_takes_exactly_its_declared_fields() -> None:
    with pytest.raises(ValueError, match="exactly the fields"):
        KitError(ErrorCode.DENIED_NAME)
    with pytest.raises(ValueError, match="exactly the fields"):
        KitError(ErrorCode.OUTSIDE_ROOT, pattern=".env*")


def test_a_detail_must_be_an_int_or_a_token() -> None:
    with pytest.raises(ValueError, match="int or a short token"):
        KitError(ErrorCode.FILE_COUNT_CAP, cap="max_files", limit=True)


def test_safe_token_falls_back_rather_than_leaking() -> None:
    assert safe_token("extra_forbidden", fallback="invalid") == "extra_forbidden"
    assert safe_token("sandbox.max_files", fallback="invalid") == "sandbox.max_files"
    assert safe_token("/etc/passwd", fallback="unrecognized") == "unrecognized"
    assert safe_token("drop table; --", fallback="unrecognized") == "unrecognized"
    assert safe_token("x" * 65, fallback="unrecognized") == "unrecognized"


_SAMPLES: dict[ErrorCode, dict[str, int | str]] = {
    ErrorCode.DENIED_NAME: {"pattern": ".env*"},
    ErrorCode.UNREADABLE: {"encoding": "utf-8"},
    ErrorCode.FILE_BYTE_CAP: {"cap": "max_file_bytes", "limit": 1, "size": 2},
    ErrorCode.RUN_BYTE_CAP: {"cap": "max_run_bytes", "limit": 1, "spent": 1, "size": 2},
    ErrorCode.FILE_COUNT_CAP: {"cap": "max_files", "limit": 1},
    ErrorCode.FORBIDDEN: {"role": "ci", "capability": "write_target"},
    ErrorCode.NOT_OWNER: {"role": "engineer", "capability": "manage_own_sessions"},
    ErrorCode.CONFIG_INVALID: {"field": "sandbox.max_files", "problem": "greater_than"},
    ErrorCode.CONTRACT_INVALID: {"field": "tools.0.effect", "problem": "literal_error"},
}


def _build(code: ErrorCode) -> KitError:
    return KitError(code, **_SAMPLES.get(code, {}))
