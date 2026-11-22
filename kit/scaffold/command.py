"""The `kit new` command.

The acting principal is a flag, and the default is `engineer`, which cannot write.
Nothing in the environment promotes a run to `lead`. The target path is not a token,
so it is not put through the same pattern as a subject: the factory checks that it is
a directory we can create, that its final component is not a link, and that every
write stays inside it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError

from kit.core.errors import ErrorCode, KitError
from kit.core.principals import Principal, Role
from kit.core.schema import first_problem, known_fields
from kit.scaffold.errors import ScaffoldCode, ScaffoldError
from kit.scaffold.factory import write_scaffold
from kit.scaffold.templates import Kind

_STRICT = ConfigDict(extra="forbid", frozen=True)


class NewInvocation(BaseModel):
    """The arguments of `kit new`, checked before the factory is called.

    `subject` is bounded here and then handed to `Principal`, which owns the character
    rule. A failure on `subject` is `principal.bad_subject`. A failure on `scaffold`
    is `scaffold.unknown_kind`.
    """

    model_config = _STRICT

    scaffold: Kind
    role: Role
    subject: str = Field(min_length=1, max_length=64)
    force: StrictBool

    def to_principal(self) -> Principal:
        return Principal(self.role, self.subject)


_KNOWN: Final = known_fields(NewInvocation)


def register_new(parser: argparse.ArgumentParser) -> None:
    """Add the `new` subcommand. The default principal cannot write."""
    commands = parser.add_subparsers(dest="command")
    new = commands.add_parser(
        "new",
        help="Write a scaffold into a target directory.",
        description=(
            "Write a CLAUDE.md hierarchy, path-scoped rules, slash commands and skills "
            "into a target directory. Only the lead principal may write. The default "
            "principal is engineer, which is refused."
        ),
    )
    new.add_argument("target", help="Directory to write into. Created when its parent exists.")
    new.add_argument(
        "--scaffold",
        required=True,
        choices=[kind.value for kind in Kind],
        help="Which scaffold to write.",
    )
    new.add_argument(
        "--force",
        action="store_true",
        help="Write into a target that already has files. Symbolic links are still refused.",
    )
    new.add_argument(
        "--principal",
        default=Role.ENGINEER.value,
        choices=[role.value for role in Role],
        help="Acting principal. Only lead may write. Defaults to engineer.",
    )
    new.add_argument(
        "--subject",
        default=None,
        help="Subject token. Defaults to the role name, or github-actions for ci.",
    )


def run_new(args: argparse.Namespace) -> int:
    """Write the scaffold, or return 1 with a fixed message on stderr. Never a path."""
    try:
        invocation = _invocation(args)
        manifest = write_scaffold(
            _target(args),
            invocation.scaffold,
            invocation.to_principal(),
            force=invocation.force,
        )
    except ValidationError as err:
        print(str(_invocation_error(err)), file=sys.stderr)
        return 1
    except (KitError, ScaffoldError) as err:
        print(str(err), file=sys.stderr)
        return 1
    sys.stdout.write(manifest.render())
    return 0


def _invocation(args: argparse.Namespace) -> NewInvocation:
    role = getattr(args, "principal", None)
    given = getattr(args, "subject", None)
    subject = given if isinstance(given, str) else _default_subject(role)
    return NewInvocation.model_validate(
        {
            "scaffold": getattr(args, "scaffold", None),
            "role": role,
            "subject": subject,
            "force": getattr(args, "force", False),
        }
    )


def _default_subject(role: object) -> str:
    if role == Role.CI.value:
        return "github-actions"
    if role == Role.LEAD.value:
        return Role.LEAD.value
    return Role.ENGINEER.value


def _target(args: argparse.Namespace) -> Path:
    raw = getattr(args, "target", "")
    if not isinstance(raw, str) or raw == "":
        raise ScaffoldError(ScaffoldCode.TARGET_UNUSABLE)
    return Path(raw)


def _invocation_error(err: ValidationError) -> KitError | ScaffoldError:
    field, _problem = first_problem(err, _KNOWN)
    if field == "subject":
        return KitError(ErrorCode.BAD_SUBJECT)
    if field == "scaffold":
        return ScaffoldError(ScaffoldCode.UNKNOWN_KIND)
    return ScaffoldError(ScaffoldCode.BAD_INVOCATION)
