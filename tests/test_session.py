"""Session state: append-only store, own-session access, resume and fork.

Resume is asserted against app 17's loop: recorded replies come back through `ReplayProvider`,
the transcript those calls resend is sendable, and an unanswered tool call carries the loop's
synthetic result. Nothing here calls a model.
"""

from __future__ import annotations

import asyncio
import json
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from agent_container.core.bedrock import build_request
from agent_container.core.loop import MAX_USER_MESSAGE_CHARS
from agent_container.core.messages import (
    Message,
    ModelRequest,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

from kit.cli import main
from kit.core.errors import ErrorCode, KitError
from kit.core.principals import Principal
from kit.session import (
    SessionError,
    SessionReason,
    SessionStore,
    resume,
    transcript_is_sendable,
)
from kit.session.models import MAX_SESSION_BYTES

ID_A = "a" * 32
ID_B = "b" * 32
ID_C = "c" * 32
NONCE = "0123456789abcdef"
NOTE = "personal-note-do-not-print"
DEV = Principal.engineer("dev")
T0 = datetime(2026, 11, 22, 16, 0, tzinfo=UTC)
T1 = datetime(2026, 11, 22, 16, 1, tzinfo=UTC)
T2 = datetime(2026, 11, 22, 16, 2, tzinfo=UTC)


def _store(
    root: Path,
    ids: tuple[str, ...] = (ID_A, ID_B, ID_C),
    times: tuple[datetime, ...] = (T0, T1, T2),
) -> SessionStore:
    pending_ids = iter(ids)
    pending_times = iter(times)
    return SessionStore(root, clock=lambda: next(pending_times), new_id=lambda: next(pending_ids))


def _opening(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "fence_nonce": NONCE,
        "name": "look",
        "stop_reason": "tool_use",
        "system": "You are a test.",
        "text": "Looking.",
        "tool_results": [{"content": "recorded-dao-body", "is_error": False, "tool_use_id": "t1"}],
        "tool_uses": [{"id": "t1", "input": {"path": "Dao.java"}, "name": "lookup"}],
        "usage": {"input_tokens": 11, "output_tokens": 5},
        "user_message": NOTE,
    }
    body.update(overrides)
    return body


def _finished(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "fence_nonce": NONCE,
        "name": "look",
        "stop_reason": "end_turn",
        "system": "You are a test.",
        "text": "Finished.",
        "usage": {"input_tokens": 1, "output_tokens": 1},
        "user_message": NOTE,
    }
    body.update(overrides)
    return body


def _later(**overrides: object) -> dict[str, object]:
    """A closing turn that leaves a tool call unanswered, so the loop must answer it."""
    body: dict[str, object] = {
        "name": "done",
        "stop_reason": "end_turn",
        "text": "Finished.",
        "tool_uses": [{"id": "t2", "input": {}, "name": "note"}],
        "usage": {"input_tokens": 7, "output_tokens": 3},
    }
    body.update(overrides)
    return body


def _no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a model was called")

    monkeypatch.setattr("agent_container.core.bedrock.BedrockProvider.converse", boom)
    monkeypatch.setattr("agent_container.core.bedrock.make_client", boom)


def _result_text(messages: tuple[Message, ...] | list[Message]) -> str:
    return "\n".join(
        block.content
        for message in messages
        for block in message.content
        if isinstance(block, ToolResultBlock)
    )


def _reject(store: SessionStore, turn: dict[str, object]) -> SessionError:
    with pytest.raises(SessionError) as caught:
        store.create(DEV, turn)
    return caught.value


# -- the file ---------------------------------------------------------------------


def test_create_writes_the_spec_columns_and_a_private_file(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(DEV, _finished())
    path = tmp_path / f"{session.id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == {
        "budget_spent",
        "created_at",
        "id",
        "parent_id",
        "principal",
        "turns",
    }
    assert document["id"] == ID_A
    assert document["parent_id"] is None
    assert document["principal"] == "dev"
    assert document["budget_spent"] == {"input_tokens": 1, "output_tokens": 1, "turns": 1}
    assert set(document["turns"][0]) == {
        "fence_nonce",
        "name",
        "stop_reason",
        "system",
        "text",
        "tool_results",
        "tool_uses",
        "usage",
        "user_message",
    }


def test_append_keeps_the_turns_already_stored(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    session = store.create(DEV, _opening())
    path = tmp_path / f"{session.id}.json"
    before = json.loads(path.read_text(encoding="utf-8"))
    updated = store.append(DEV, session.id, _later())
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["turns"][:-1] == before["turns"]
    assert after["turns"][-1]["name"] == "done"
    assert updated.created_at == session.created_at
    assert updated.parent_id is None
    assert updated.budget_spent.turns == 2
    assert updated.budget_spent.input_tokens == 18
    assert updated.budget_spent.output_tokens == 8


def test_a_duplicate_turn_name_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    store.create(DEV, _opening())
    with pytest.raises(SessionError) as caught:
        store.append(DEV, ID_A, _later(name="look"))
    assert caught.value.reason is SessionReason.DUPLICATE_TURN


def test_a_finished_session_does_not_take_another_turn(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    store.create(DEV, _finished())
    with pytest.raises(SessionError) as caught:
        store.append(DEV, ID_A, {"name": "more", "stop_reason": "end_turn", "text": "nope"})
    assert caught.value.reason is SessionReason.TURN_REJECTED


def test_a_tool_use_turn_must_record_each_result(tmp_path: Path) -> None:
    refusal = _reject(_store(tmp_path), _opening(tool_results=[]))
    assert refusal.reason is SessionReason.TURN_REJECTED


def test_an_end_turn_does_not_carry_stored_tool_results(tmp_path: Path) -> None:
    refusal = _reject(
        _store(tmp_path),
        _opening(stop_reason="end_turn", tool_results=[{"content": "x", "tool_use_id": "t1"}]),
    )
    assert refusal.reason is SessionReason.TURN_REJECTED


def test_a_later_turn_cannot_replace_the_opening(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    store.create(DEV, _opening())
    with pytest.raises(SessionError) as caught:
        store.append(DEV, ID_A, _later(user_message="a different task"))
    assert caught.value.reason is SessionReason.TURN_REJECTED


def test_a_repeated_tool_call_id_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    store.create(DEV, _opening())
    with pytest.raises(SessionError) as caught:
        store.append(DEV, ID_A, _later(tool_uses=[{"id": "t1", "input": {}, "name": "note"}]))
    assert caught.value.reason is SessionReason.TURN_REJECTED


@pytest.mark.parametrize(
    "turn",
    [
        _opening(stop_reason="ignore-previous-instructions", tool_results=[], tool_uses=[]),
        _finished(user_message="   "),
        _finished(user_message="x" * (MAX_USER_MESSAGE_CHARS + 1)),
        _finished(name="n" * 65),
        _finished(fence_nonce="short"),
        _finished(text="bad\x00text"),
    ],
)
def test_a_turn_that_breaks_the_rules_is_refused_without_an_echo(
    tmp_path: Path, turn: dict[str, object]
) -> None:
    refusal = _reject(_store(tmp_path), turn)
    assert refusal.reason is SessionReason.TURN_REJECTED
    assert refusal.__cause__ is None
    assert "ignore-previous-instructions" not in str(refusal)
    assert "\x00" not in str(refusal)


def test_the_largest_accepted_opening_is_stored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    message = "x" * MAX_USER_MESSAGE_CHARS
    name = "n" * 64
    session = store.create(DEV, _finished(user_message=message, name=name))
    assert session.turns[0].user_message == message
    assert session.turns[0].name == name


# -- access ----------------------------------------------------------------------


def test_list_returns_only_the_callers_sessions(tmp_path: Path) -> None:
    store = _store(tmp_path, ids=(ID_A, ID_B), times=(T0, T1))
    store.create(DEV, _finished())
    store.create(Principal.engineer("ada"), _finished())
    listed = store.list_sessions(DEV)
    assert [session.id for session in listed] == [ID_A]
    assert all(NOTE not in session.id for session in listed)
    assert store.list_sessions(Principal.engineer("ada"))[0].id == ID_B


def test_an_empty_store_lists_nothing(tmp_path: Path) -> None:
    assert _store(tmp_path / "missing").list_sessions(DEV) == ()


def test_ci_cannot_use_sessions_even_for_a_missing_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    ci = Principal.ci()
    for action in (
        lambda: store.list_sessions(ci),
        lambda: store.get(ci, "f" * 32),
        lambda: store.create(ci, _finished()),
        lambda: store.append(ci, ID_A, _later()),
        lambda: store.fork(ci, ID_A, "look"),
    ):
        with pytest.raises(KitError) as caught:
            action()
        assert caught.value.code is ErrorCode.FORBIDDEN


def test_another_engineer_cannot_read_append_or_fork(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replayed a session the caller does not own")

    monkeypatch.setattr("agent_container.core.loop.AgentLoop.run", explode)
    store = _store(tmp_path, times=(T0,))
    session = store.create(DEV, _opening())
    path = tmp_path / f"{session.id}.json"
    raw = path.read_bytes()
    other = Principal.engineer("ada")
    for action in (
        lambda: store.get(other, session.id),
        lambda: store.append(other, session.id, _later()),
        lambda: store.fork(other, session.id, "look"),
        lambda: asyncio.run(resume(store, other, session.id)),
    ):
        with pytest.raises(KitError) as caught:
            action()
        assert caught.value.code is ErrorCode.NOT_OWNER
        assert NOTE not in str(caught.value)
        assert path.read_bytes() == raw


def test_a_lead_manages_only_their_own_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_model(monkeypatch)
    store = _store(tmp_path)
    session = store.create(Principal.lead("lead"), _finished())
    result = asyncio.run(resume(store, Principal.lead("lead"), session.id))
    assert result.turns_replayed == 1
    assert result.end_reason == "end_turn"
    with pytest.raises(KitError) as caught:
        store.get(DEV, session.id)
    assert caught.value.code is ErrorCode.NOT_OWNER


def test_a_missing_session_is_not_found_and_a_bad_id_is_not_a_path(tmp_path: Path) -> None:
    store = _store(tmp_path / "sessions")
    with pytest.raises(SessionError) as missing:
        store.get(DEV, "f" * 32)
    assert missing.value.reason is SessionReason.NOT_FOUND
    with pytest.raises(SessionError) as bad:
        store.get(DEV, "../passwd")
    assert bad.value.reason is SessionReason.INVALID
    assert "passwd" not in str(bad.value)
    assert not (tmp_path / "passwd").exists()


# -- fork ------------------------------------------------------------------------


def test_fork_copies_up_to_the_named_turn_and_sets_parent_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(DEV, _opening())
    store.append(DEV, session.id, _later())
    parent = tmp_path / f"{ID_A}.json"
    raw = parent.read_bytes()
    at_look = store.fork(DEV, ID_A, "look")
    at_done = store.fork(DEV, ID_A, "done")
    assert parent.read_bytes() == raw
    assert at_look.id == ID_B
    assert at_look.parent_id == ID_A
    assert at_look.created_at == T1
    assert [turn.name for turn in at_look.turns] == ["look"]
    assert at_look.budget_spent.input_tokens == 11
    assert at_look.budget_spent.turns == 1
    assert at_done.id == ID_C
    assert at_done.parent_id == ID_A
    assert [turn.name for turn in at_done.turns] == ["look", "done"]
    assert at_done.budget_spent.input_tokens == 18
    child = json.loads((tmp_path / f"{ID_B}.json").read_text(encoding="utf-8"))
    assert child["parent_id"] == ID_A
    assert child["principal"] == "dev"
    assert child["turns"] == json.loads(raw)["turns"][:1]


def test_fork_of_a_fork_parents_the_immediate_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(DEV, _finished())
    first = store.fork(DEV, ID_A, "look")
    second = store.fork(DEV, first.id, "look")
    assert first.parent_id == ID_A
    assert second.parent_id == first.id
    assert second.id == ID_C


def test_an_unknown_turn_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    store.create(DEV, _finished())
    before = {path.name for path in tmp_path.glob("*.json")}
    raw = (tmp_path / f"{ID_A}.json").read_bytes()
    with pytest.raises(SessionError) as caught:
        store.fork(DEV, ID_A, "missing")
    assert caught.value.reason is SessionReason.UNKNOWN_TURN
    assert {path.name for path in tmp_path.glob("*.json")} == before
    assert (tmp_path / f"{ID_A}.json").read_bytes() == raw


# -- resume ----------------------------------------------------------------------


def test_resume_resends_the_transcript_and_does_not_call_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_model(monkeypatch)
    store = _store(tmp_path, times=(T0,))
    session = store.create(DEV, _opening())
    store.append(DEV, session.id, _later())
    path = tmp_path / f"{session.id}.json"
    raw = path.read_bytes()
    result = asyncio.run(resume(store, DEV, session.id))
    assert path.read_bytes() == raw
    assert len(result.requests) == 2
    assert result.turns_replayed == 2
    assert result.end_reason == "end_turn"
    assert result.stop_reason == "end_turn"
    assert result.input_tokens == 18
    assert result.output_tokens == 8
    first, second = result.requests
    assert [message.role for message in first.messages] == ["user"]
    assert [message.role for message in second.messages] == ["user", "assistant", "user"]
    assert isinstance(second.messages[0].content[0], TextBlock)
    assert second.messages[0].content[0].text == NOTE
    assert first.system.startswith("You are a test.")
    assert NONCE in first.system
    assert any(
        isinstance(block, ToolUseBlock) and block.id == "t1" for block in second.messages[1].content
    )
    answered = [block for block in second.messages[2].content if isinstance(block, ToolResultBlock)]
    assert [block.tool_use_id for block in answered] == ["t1"]
    assert "recorded-dao-body" in answered[0].content
    assert "synthetic result added by the agent loop" not in _result_text(second.messages)
    assert "synthetic result added by the agent loop" in _result_text(result.messages)
    assert "that tool is not available" not in _result_text(result.messages)
    assert transcript_is_sendable(result.messages)
    build_request("kit-session", ModelRequest(system=second.system, messages=result.messages))


def test_resume_of_a_fork_replays_only_the_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_model(monkeypatch)
    store = _store(tmp_path)
    session = store.create(DEV, _opening())
    store.append(DEV, session.id, _later())
    forked = store.fork(DEV, session.id, "look")
    parent = tmp_path / f"{session.id}.json"
    child = tmp_path / f"{forked.id}.json"
    parent_raw = parent.read_bytes()
    child_raw = child.read_bytes()
    result = asyncio.run(resume(store, DEV, forked.id))
    assert result.turns_replayed == 1
    assert result.end_reason == "stopped_by_hook"
    assert len(result.requests) == 1
    assert "recorded-dao-body" in _result_text(result.messages)
    assert transcript_is_sendable(result.messages)
    assert parent.read_bytes() == parent_raw
    assert child.read_bytes() == child_raw


def test_resume_of_an_empty_session_does_not_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _no_model(monkeypatch)

    def explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("replayed an empty session")

    monkeypatch.setattr("agent_container.core.loop.AgentLoop.run", explode)
    document: dict[str, object] = {
        "budget_spent": {"input_tokens": 0, "output_tokens": 0, "turns": 0},
        "created_at": "2026-11-22T16:00:00+00:00",
        "id": ID_A,
        "parent_id": None,
        "principal": "dev",
        "turns": [],
    }
    (tmp_path / f"{ID_A}.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SessionError) as caught:
        asyncio.run(resume(SessionStore(tmp_path), DEV, ID_A))
    assert caught.value.reason is SessionReason.EMPTY


def test_a_paired_transcript_is_sendable_and_an_open_call_is_not() -> None:
    paired = (
        Message.user_text("hello"),
        Message("assistant", (ToolUseBlock("t1", "lookup", {}),)),
        Message("user", (ToolResultBlock("t1", "ok"),)),
    )
    open_call = paired[:2]
    early_result = (Message("user", (ToolResultBlock("t1", "ok"),)),)
    assert transcript_is_sendable(paired)
    assert not transcript_is_sendable(open_call)
    assert not transcript_is_sendable(early_result)
    assert not transcript_is_sendable(())


# -- corrupt files ---------------------------------------------------------------


def test_a_symlink_is_not_followed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    session = store.create(DEV, _finished())
    path = tmp_path / f"{session.id}.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(SessionError) as caught:
        store.get(DEV, session.id)
    assert caught.value.reason is SessionReason.INVALID
    assert NOTE not in str(caught.value)


def test_an_oversized_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / f"{'d' * 32}.json").write_bytes(b"{" * (MAX_SESSION_BYTES + 1))
    with pytest.raises(SessionError) as caught:
        _store(tmp_path).get(DEV, "d" * 32)
    assert caught.value.reason is SessionReason.INVALID


def test_corrupt_session_files_are_refused(tmp_path: Path) -> None:
    store = _store(tmp_path, times=(T0,))
    session = store.create(DEV, _finished())
    path = tmp_path / f"{session.id}.json"
    good = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(good, dict)

    budget = dict(good)
    spent = dict(budget["budget_spent"])
    spent["input_tokens"] = 999
    budget["budget_spent"] = spent
    path.write_text(json.dumps(budget), encoding="utf-8")
    with pytest.raises(SessionError) as bad_budget:
        store.get(DEV, session.id)
    assert bad_budget.value.reason is SessionReason.INVALID

    renamed = dict(good)
    renamed["id"] = ID_B
    path.write_text(json.dumps(renamed), encoding="utf-8")
    with pytest.raises(SessionError) as mismatched:
        store.get(DEV, session.id)
    assert mismatched.value.reason is SessionReason.INVALID

    hostile = dict(good)
    hostile["principal"] = "has a space"
    path.write_text(json.dumps(hostile), encoding="utf-8")
    with pytest.raises(SessionError) as principal:
        store.get(DEV, session.id)
    assert principal.value.reason is SessionReason.INVALID
    assert "space" not in str(principal.value)

    path.write_text("{", encoding="utf-8")
    with pytest.raises(SessionError) as garbage:
        store.list_sessions(DEV)
    assert garbage.value.reason is SessionReason.INVALID


# -- CLI -------------------------------------------------------------------------


def test_cli_lists_resumes_and_forks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _no_model(monkeypatch)
    monkeypatch.setenv("USER", "dev")
    store = _store(tmp_path, times=(T0,))
    session = store.create(DEV, _opening())
    store.append(DEV, session.id, _later())
    parent_raw = (tmp_path / f"{session.id}.json").read_bytes()

    assert main(["session", "list", "--dir", str(tmp_path)]) == 0
    listed = capsys.readouterr()
    assert NOTE not in listed.out
    rows = [json.loads(line) for line in listed.out.splitlines()]
    assert rows == [
        {
            "budget_spent": {"input_tokens": 18, "output_tokens": 8, "turns": 2},
            "id": ID_A,
            "parent_id": None,
            "turn_names": ["look", "done"],
        }
    ]

    assert main(["session", "resume", ID_A, "--dir", str(tmp_path)]) == 0
    resumed = capsys.readouterr()
    assert resumed.err == ""
    assert NOTE not in resumed.out
    lines = [json.loads(line) for line in resumed.out.splitlines()]
    assert lines[0] == {"stop_reason": "tool_use", "text": "Looking.", "turn": "look"}
    assert lines[1] == {"stop_reason": "end_turn", "text": "Finished.", "turn": "done"}
    assert lines[2]["event"] == "resumed"
    assert lines[2]["model_call"] is False
    assert lines[2]["end_reason"] == "end_turn"
    assert lines[2]["turns"] == 2
    assert (tmp_path / f"{session.id}.json").read_bytes() == parent_raw

    assert main(["session", "fork", ID_A, "look", "--dir", str(tmp_path)]) == 0
    forked = json.loads(capsys.readouterr().out)
    assert forked["parent_id"] == ID_A
    assert forked["turn"] == "look"
    assert forked["turns"] == 1
    child = json.loads((tmp_path / f"{forked['id']}.json").read_text(encoding="utf-8"))
    assert [turn["name"] for turn in child["turns"]] == ["look"]
    assert (tmp_path / f"{session.id}.json").read_bytes() == parent_raw


def test_cli_refuses_someone_elses_session_without_echoing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _store(tmp_path, times=(T0,)).create(Principal.engineer("ada"), _finished())
    monkeypatch.setenv("USER", "dev")
    assert main(["session", "resume", ID_A, "--dir", str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert NOTE not in captured.err
    assert "principal.not_owner" in captured.err


def test_cli_session_without_a_subcommand_is_rejected() -> None:
    with pytest.raises(SystemExit) as caught:
        main(["session"])
    assert caught.value.code == 2


def test_cli_list_of_an_empty_directory_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("USER", "dev")
    assert main(["session", "list", "--dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""
