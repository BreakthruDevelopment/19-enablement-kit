"""The three principals: what each may do, and the capabilities nobody holds."""

import pytest

from kit.core.errors import ErrorCode, KitError
from kit.core.principals import (
    NEVER_GRANTED,
    OWNER_SCOPED,
    Capability,
    Principal,
    Role,
    assert_can,
)


def test_the_three_roles_and_their_constructors() -> None:
    assert Principal.engineer("dev").role is Role.ENGINEER
    assert Principal.ci().subject == "github-actions"
    assert Principal.lead("lead").role is Role.LEAD
    assert {role for role in Role} == {Role.ENGINEER, Role.CI, Role.LEAD}


def test_engineer_reads_scouts_reviews_and_owns_sessions() -> None:
    dev = Principal.engineer("dev")
    for capability in (
        Capability.READ_FILES,
        Capability.RUN_SCOUT,
        Capability.RUN_REVIEW,
        Capability.CALL_GATEWAY,
    ):
        assert_can(dev, capability)
    assert_can(dev, Capability.MANAGE_OWN_SESSIONS, owner="dev")


def test_engineer_may_not_write_a_target() -> None:
    with pytest.raises(KitError) as caught:
        assert_can(Principal.engineer("dev"), Capability.WRITE_TARGET)
    assert caught.value.code is ErrorCode.FORBIDDEN
    assert caught.value.category.value == "permission"


def test_lead_is_the_only_principal_that_may_write() -> None:
    assert_can(Principal.lead("lead"), Capability.WRITE_TARGET)
    writers = [
        role for role in Role if Capability.WRITE_TARGET in Principal(role, "s").capabilities
    ]
    assert writers == [Role.LEAD]


def test_lead_has_everything_the_engineer_has() -> None:
    assert Principal.engineer("x").capabilities <= Principal.lead("x").capabilities


def test_ci_is_the_weakest_principal() -> None:
    ci = Principal.ci()
    assert_can(ci, Capability.READ_FILES)
    assert_can(ci, Capability.RUN_REVIEW)
    assert_can(ci, Capability.POST_REVIEW)
    # Unattended on contributor content: no scout, no sessions, no gateway, no write.
    for capability in (
        Capability.RUN_SCOUT,
        Capability.CALL_GATEWAY,
        Capability.WRITE_TARGET,
        Capability.MANAGE_OWN_SESSIONS,
    ):
        with pytest.raises(KitError) as caught:
            assert_can(ci, capability, owner=ci.subject)
        assert caught.value.code is ErrorCode.FORBIDDEN


def test_posting_a_review_is_ci_and_the_engineer_locally() -> None:
    # The report is posted by the workflow, not by a developer's machine.
    assert not Principal.engineer("dev").can(Capability.POST_REVIEW)
    assert not Principal.lead("lead").can(Capability.POST_REVIEW)


def test_no_principal_may_change_a_label_merge_or_resolve_a_thread() -> None:
    # `security-sensitive` is what makes a Codex review required, and the token that posts a
    # review can also set labels. These are declared so the refusal is a test, not a sentence.
    assert {
        Capability.CHANGE_LABELS,
        Capability.MERGE,
        Capability.RESOLVE_THREADS,
    } == NEVER_GRANTED
    for role in Role:
        principal = Principal(role, "subject")
        for capability in NEVER_GRANTED:
            assert not principal.can(capability)
            with pytest.raises(KitError) as caught:
                assert_can(principal, capability)
            assert caught.value.code is ErrorCode.FORBIDDEN


def test_an_owner_scoped_capability_needs_the_owner() -> None:
    assert {Capability.MANAGE_OWN_SESSIONS} == OWNER_SCOPED
    dev = Principal.engineer("dev")
    # Forgetting the argument must not be a way to get the capability.
    with pytest.raises(KitError) as caught:
        assert_can(dev, Capability.MANAGE_OWN_SESSIONS)
    assert caught.value.code is ErrorCode.NOT_OWNER
    assert not dev.can(Capability.MANAGE_OWN_SESSIONS)


def test_another_engineers_session_is_refused() -> None:
    with pytest.raises(KitError) as caught:
        assert_can(Principal.engineer("dev"), Capability.MANAGE_OWN_SESSIONS, owner="someone")
    assert caught.value.code is ErrorCode.NOT_OWNER


def test_an_owner_is_ignored_for_everything_else() -> None:
    assert_can(Principal.engineer("dev"), Capability.READ_FILES, owner="someone-else")


@pytest.mark.parametrize("subject", ["", " ", "a" * 65, "dev/../root", "a b", "dev\n"])
def test_a_subject_is_a_short_token(subject: str) -> None:
    with pytest.raises(KitError) as caught:
        Principal.engineer(subject)
    assert caught.value.code is ErrorCode.BAD_SUBJECT


def test_capabilities_are_immutable() -> None:
    assert isinstance(Principal.ci().capabilities, frozenset)


def test_there_is_a_capability_for_every_command_in_the_spec() -> None:
    # `kit/core/` is a foundation path, so a later slice that found its command had no capability
    # would have to stop and ask for a foundation change. The table is declared up front instead.
    dev = Principal.engineer("dev")
    for capability in (Capability.RUN_SCOUT, Capability.RUN_REVIEW, Capability.RUN_PLAN):
        assert_can(dev, capability)
    assert_can(dev, Capability.CALL_GATEWAY)
    assert_can(dev, Capability.MANAGE_OWN_SESSIONS, owner="dev")
    assert_can(Principal.lead("lead"), Capability.WRITE_TARGET)
    # Not CI's: a plan is an engineer at their own machine.
    with pytest.raises(KitError):
        assert_can(Principal.ci(), Capability.RUN_PLAN)
