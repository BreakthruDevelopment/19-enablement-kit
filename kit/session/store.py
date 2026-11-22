"""The append-only session store.

A session is one file, `sessions/<id>.json`. Appending a turn rewrites that file with the turns
already stored followed by the new one; the stored turns are serialised again but not changed, and
there is no operation that edits or deletes one. A fork writes a new file. Resume does not write
at all.

Own sessions only. Every operation calls `assert_can` with `manage_own_sessions` and the owner,
which is the `principal` column. `ci` has no session capability. An engineer who names someone
else's session is refused with `principal.not_owner` and learns nothing about its turns.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from kit.core.errors import KitError
from kit.core.principals import Capability, Principal, assert_can
from kit.session.errors import SessionError, SessionReason
from kit.session.models import (
    MAX_SESSION_BYTES,
    Session,
    Turn,
    budget_of,
    ensure_turns,
    parse_turn,
    session_id_ok,
)

__all__ = ["SessionStore"]

_NOFOLLOW: Final = os.O_NOFOLLOW if hasattr(os, "O_NOFOLLOW") else 0


class SessionStore:
    """Sessions rooted at one directory. The directory is created on the first write."""

    def __init__(
        self,
        root: Path,
        *,
        clock: Callable[[], datetime] | None = None,
        new_id: Callable[[], str] | None = None,
    ) -> None:
        self._root = root
        self._clock = clock or (lambda: datetime.now(UTC))
        self._new_id = new_id or (lambda: secrets.token_hex(16))

    def create(self, principal: Principal, turn: Turn | Mapping[str, object]) -> Session:
        """Start a session with its first turn. The id and the budget are not caller-supplied."""
        assert_can(principal, Capability.MANAGE_OWN_SESSIONS, owner=principal.subject)
        parsed = parse_turn(turn)
        ensure_turns((parsed,), on_error=SessionReason.TURN_REJECTED)
        session = self._new(principal.subject, (parsed,), parent_id=None)
        self._write(session)
        return session

    def append(
        self, principal: Principal, session_id: str, turn: Turn | Mapping[str, object]
    ) -> Session:
        """Add one turn. Turns already in the file are kept as they were stored."""
        session = self.get(principal, session_id)
        parsed = parse_turn(turn)
        if any(stored.name == parsed.name for stored in session.turns):
            raise SessionError(SessionReason.DUPLICATE_TURN)
        turns = (*session.turns, parsed)
        ensure_turns(turns, on_error=SessionReason.TURN_REJECTED)
        updated = session.model_copy(update={"turns": turns, "budget_spent": budget_of(turns)})
        self._write(updated)
        return updated

    def get(self, principal: Principal, session_id: str) -> Session:
        """The session, if `principal` owns it."""
        assert_can(principal, Capability.MANAGE_OWN_SESSIONS, owner=principal.subject)
        session = self._read(session_id)
        assert_can(principal, Capability.MANAGE_OWN_SESSIONS, owner=session.principal)
        return session

    def list_sessions(self, principal: Principal) -> tuple[Session, ...]:
        """This principal's sessions, oldest first. Anyone else's files are not returned."""
        assert_can(principal, Capability.MANAGE_OWN_SESSIONS, owner=principal.subject)
        found = [session for session in self._load_all() if session.principal == principal.subject]
        found.sort(key=lambda session: (session.created_at, session.id))
        return tuple(found)

    def fork(self, principal: Principal, session_id: str, turn_name: str) -> Session:
        """A new session with the turns up to and including `turn_name`, and `parent_id` set.

        The parent file is not modified. The copy ends at that turn, so a later continuation is
        a different session.
        """
        session = self.get(principal, session_id)
        index = next((i for i, turn in enumerate(session.turns) if turn.name == turn_name), None)
        if index is None:
            raise SessionError(SessionReason.UNKNOWN_TURN)
        copied = session.turns[: index + 1]
        ensure_turns(copied, on_error=SessionReason.TURN_REJECTED)
        forked = self._new(session.principal, copied, parent_id=session.id)
        self._write(forked)
        return forked

    def _new(self, owner: str, turns: tuple[Turn, ...], *, parent_id: str | None) -> Session:
        session_id = self._new_id()
        if not session_id_ok(session_id):
            raise SessionError(SessionReason.INVALID)
        try:
            created_at = self._clock()
            session = Session(
                id=session_id,
                parent_id=parent_id,
                principal=owner,
                created_at=created_at,
                turns=turns,
                budget_spent=budget_of(turns),
            )
        except ValidationError:
            raise SessionError(SessionReason.INVALID) from None
        return session

    def _load_all(self) -> list[Session]:
        root = self._root
        if not root.exists():
            return []
        if not root.is_dir():
            raise SessionError(SessionReason.INVALID)
        try:
            entries = list(root.iterdir())
        except OSError:
            raise SessionError(SessionReason.INVALID) from None
        loaded: list[Session] = []
        for entry in entries:
            if entry.suffix == ".json" and session_id_ok(entry.stem):
                loaded.append(self._read(entry.stem))
        return loaded

    def _file(self, session_id: str) -> Path:
        if not session_id_ok(session_id):
            raise SessionError(SessionReason.INVALID)
        root = self._root.resolve()
        path = root / f"{session_id}.json"
        if path.parent != root:
            raise SessionError(SessionReason.INVALID)
        return path

    def _read(self, session_id: str) -> Session:
        path = self._file(session_id)
        if not os.path.lexists(path):
            raise SessionError(SessionReason.NOT_FOUND)
        try:
            fd = os.open(path, os.O_RDONLY | _NOFOLLOW)
        except OSError:
            raise SessionError(SessionReason.INVALID) from None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SESSION_BYTES:
                raise SessionError(SessionReason.INVALID)
            blob = _read_capped(fd)
        finally:
            os.close(fd)
        return _decode(session_id, blob)

    def _write(self, session: Session) -> None:
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise SessionError(SessionReason.INVALID) from None
        path = self._file(session.id)
        raw = (
            json.dumps(session.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
        ).encode()
        if len(raw) > MAX_SESSION_BYTES:
            raise SessionError(SessionReason.INVALID)
        fd, tmp_name = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=self._root)
        tmp = Path(tmp_name)
        closed = False
        replaced = False
        try:
            os.fchmod(fd, 0o600)
            pending = raw
            while pending:
                count = os.write(fd, pending)
                if count <= 0:
                    raise OSError
                pending = pending[count:]
            os.fsync(fd)
            os.close(fd)
            closed = True
            os.replace(tmp, path)
            replaced = True
        except OSError:
            raise SessionError(SessionReason.INVALID) from None
        finally:
            if not closed:
                with suppress(OSError):
                    os.close(fd)
            if not replaced:
                with suppress(OSError):
                    tmp.unlink(missing_ok=True)


def _read_capped(fd: int) -> bytes:
    chunks: list[bytes] = []
    left = MAX_SESSION_BYTES + 1
    while left > 0:
        chunk = os.read(fd, min(left, 1024 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        left -= len(chunk)
    blob = b"".join(chunks)
    if len(blob) > MAX_SESSION_BYTES:
        raise SessionError(SessionReason.INVALID)
    return blob


def _decode(session_id: str, blob: bytes) -> Session:
    try:
        data = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise SessionError(SessionReason.INVALID) from None
    if not isinstance(data, dict):
        raise SessionError(SessionReason.INVALID)
    try:
        session = Session.model_validate(data)
    except ValidationError:
        raise SessionError(SessionReason.INVALID) from None
    if session.id != session_id or session.budget_spent != budget_of(session.turns):
        raise SessionError(SessionReason.INVALID)
    try:
        # The role is irrelevant: `Principal` owns the subject rule, and every role shares it.
        Principal.engineer(session.principal)
    except KitError:
        raise SessionError(SessionReason.INVALID) from None
    ensure_turns(session.turns, on_error=SessionReason.INVALID)
    return session
