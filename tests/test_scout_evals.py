"""The `scout-brief` rows of the spec's Evals table, run against a recorded reply.

In CI these check the plumbing at zero cost: the model is a recording, so what is asserted is what
the *code* does with an answer -- what it reads, what it refuses, what it verifies, what it says it
did not read -- not whether a real model finds a defect. The live run is done by hand against
Bedrock and recorded in the run log.

Each escape fixture (a symlink to `/etc/passwd`, a symlink to `<root>/.env`) is built here, at test
time, in a temporary copy of the sample. None is committed: a link to `/etc/passwd` is not something
to put in a public repository, and byte-for-byte is the wrong comparison for a link.

Every leak assertion uses a marker made of digits, dashes and mixed case, and `test_the_leak_check_
can_fail` proves the check finds one that is really there: an assertion that something is absent
only means something if the same assertion fires when it is present.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from scout_support import (
    CATALOG,
    DAO,
    DAO_FILES,
    DEMO_REPLIES,
    ENGINEER,
    GENERATOR,
    HTTP_QUOTE,
    JNDI_CLASSES,
    JNDI_QUOTE,
    MANIFEST,
    PRICING,
    SAMPLE,
    SEEDS,
    SQL_QUOTE,
    TX_QUOTE,
    copy_sample,
    demo_provider,
    everything,
    leaks,
    requests_of,
    scout,
    size_of,
)

from kit.core.config import SandboxLimits
from kit.core.errors import ErrorCode, KitError
from kit.scout import Explorer, open_sandbox
from kit.scout.verify import DropReason

MARKER = "LEAK-4417-d3adBEEF"
LINK = "zz-leaklink-8841.txt"


# -- sample/legacy-oms: the four planted problems ---------------------------------------------


def test_the_scout_names_the_four_planted_problems_each_with_a_file_and_a_quote() -> None:
    provider = demo_provider()
    result = scout(SAMPLE, provider)
    brief = result.brief

    by_quote = {f.evidence_quote: f for f in brief.findings}
    assert set(by_quote) == {JNDI_QUOTE, TX_QUOTE, SQL_QUOTE, HTTP_QUOTE}
    assert result.dropped == ()

    # Each finding cites real files, and its quote is really in one of them: checked here against
    # the sample on disk, independently of the scout's own check.
    for quote, finding in by_quote.items():
        assert finding.files
        assert any(quote in (SAMPLE / name).read_text("utf-8") for name in finding.files)
    assert set(by_quote[JNDI_QUOTE].files) == set(JNDI_CLASSES)
    assert PRICING in by_quote[TX_QUOTE].files
    assert by_quote[SQL_QUOTE].files == [DAO]
    assert CATALOG in by_quote[HTTP_QUOTE].files

    # The whole point of mandatory coverage: unexplored ground is named, never hidden.
    assert brief.coverage.unread_reason.strip()
    assert brief.coverage.files_total == 51
    assert brief.coverage.files_read == 48 < brief.coverage.files_total
    assert "2 sql" in brief.coverage.unread_reason
    # One call, and it was the recorded one.
    assert len(requests_of(provider)) == 1


def test_a_finding_is_only_as_good_as_the_exploration_that_served_its_files(
    tmp_path: Path,
) -> None:
    # Break the one thing that makes the nine classes reachable: the descriptor that names them.
    root = copy_sample(tmp_path)
    (root / "dd" / "ejb-jar.xml").write_text("<ejb-jar/>\n")
    (root / "dd" / "weblogic-ejb-jar.xml").write_text("<weblogic-ejb-jar/>\n")
    result = scout(root)
    assert JNDI_QUOTE not in {f.evidence_quote for f in result.brief.findings}
    assert any(d.reason is DropReason.UNSERVED_FILE for d in result.dropped)
    assert "dropped" in result.brief.coverage.unread_reason


def test_the_scout_finds_the_problems_from_the_code_never_from_the_manifest() -> None:
    provider = demo_provider()
    result = scout(SAMPLE, provider)
    text = everything(result, *requests_of(provider))
    # Strings that exist only in the manifest and the generator.
    for banned in (
        "jndi_class_count",
        "self_managed_transaction_ejb",
        "sql_concatenation_dao",
        "http_database_ejb",
        "legacy_oms_manifest",
        "generate_legacy_oms",
    ):
        assert banned not in text
    assert not any("manifest" in name or "generate_" in name for name in result.served)


def test_the_manifest_is_unreachable_through_the_sandbox_roots() -> None:
    assert MANIFEST.is_file() and GENERATOR.is_file()  # so a refusal is not just "missing"
    box = open_sandbox(ENGINEER, SAMPLE)
    assert box.roots == (SAMPLE.resolve(),)
    for outside in (MANIFEST, GENERATOR, SAMPLE / ".." / "legacy_oms_manifest.json"):
        with pytest.raises(KitError) as caught:
            box.read_text(outside)
        assert caught.value.code is ErrorCode.OUTSIDE_ROOT
        assert caught.value.category.value == "permission"
    # And through the scout's own tool, by a relative path that climbs out of the root.
    outcome = Explorer(box).read("../legacy_oms_manifest.json")
    assert not outcome.served
    assert outcome.code is ErrorCode.OUTSIDE_ROOT
    assert outcome.category == "permission"
    assert box.usage.files_read == 0


# -- the per-run byte cap ----------------------------------------------------------------------


def test_with_the_cap_set_to_the_build_files_and_the_dao_it_stops_and_says_so() -> None:
    cap = size_of(SAMPLE, (*SEEDS, *DAO_FILES))
    provider = demo_provider()
    result = scout(SAMPLE, provider, limits=SandboxLimits(max_run_bytes=cap))
    brief = result.brief

    assert result.stopped_by is ErrorCode.RUN_BYTE_CAP
    assert set(result.served) == {*SEEDS, *DAO_FILES}
    assert brief.coverage.files_read == len(SEEDS) + len(DAO_FILES) < brief.coverage.files_total
    reason = brief.coverage.unread_reason
    assert "sandbox.run_byte_cap" in reason
    assert "Not reached before the cap" in reason

    # The SQL problem is in the DAO, so it is named; the other three cite files the cap kept the
    # scout from reading, so they are dropped, not shown on the strength of a recording.
    assert [f.evidence_quote for f in brief.findings] == [SQL_QUOTE]
    assert [d.reason for d in result.dropped] == [DropReason.UNSERVED_FILE] * 3
    assert "3 entr" in reason
    # Never a brief that looks complete: the last step says why it stopped.
    assert result.steps[-1].next.startswith("stop: the sandbox refused a read with")


def test_one_byte_under_the_cap_the_dao_is_unreachable_and_so_is_the_sql_finding() -> None:
    # The cap is what decides: take away the DAO and the finding goes with it.
    cap = size_of(SAMPLE, SEEDS)
    result = scout(SAMPLE, limits=SandboxLimits(max_run_bytes=cap))
    assert set(result.served) == set(SEEDS)
    assert result.brief.findings == []
    assert result.brief.coverage.files_read == len(SEEDS)
    assert "sandbox.run_byte_cap" in result.brief.coverage.unread_reason


def test_the_file_count_cap_also_ends_the_run() -> None:
    result = scout(SAMPLE, limits=SandboxLimits(max_files=5))
    assert result.stopped_by is ErrorCode.FILE_COUNT_CAP
    assert result.brief.coverage.files_read == 5
    assert "sandbox.file_count_cap" in result.brief.coverage.unread_reason


def test_a_file_over_the_per_file_cap_is_skipped_and_the_run_goes_on() -> None:
    # ejb-jar.xml is 18 KB and OrderDao.java 10 KB: neither fits, and neither ends the run.
    result = scout(SAMPLE, limits=SandboxLimits(max_file_bytes=10_000))
    assert result.stopped_by is None
    assert "dd/ejb-jar.xml" not in result.served
    assert DAO not in result.served
    assert len(result.served) > 15  # what did fit was still read, and the run went on
    assert "Could not be read" in result.brief.coverage.unread_reason
    assert "sandbox.file_byte_cap" in result.brief.coverage.unread_reason


# -- a symlink to /etc/passwd ------------------------------------------------------------------


@pytest.mark.parametrize("target", ["/etc/passwd", "outside"])
def test_a_symlink_out_of_the_tree_is_refused_and_nothing_of_the_target_is_in_the_brief(
    tmp_path: Path, target: str
) -> None:
    root = copy_sample(tmp_path)
    if target == "outside":
        outside = tmp_path / "outside.txt"
        outside.write_text(f"{MARKER}\nsecond line 0042\n")
        link_target = outside
        needles = [MARKER, "second line 0042"]
    else:
        link_target = Path("/etc/passwd")
        first = link_target.read_text("utf-8").splitlines()[0]
        needles = [first]  # `root:x:0:0:...`: digits and colons, not a word a brief could contain
        assert ":0:0:" in first
    (root / "src" / LINK).symlink_to(link_target)
    (root / LINK).symlink_to(link_target)  # and one at the top level, where the summary lists names

    provider = demo_provider()
    result = scout(root, provider)
    text = everything(result, *requests_of(provider))

    # A `permission` error from the sandbox, on the record...
    assert (ErrorCode.OUTSIDE_ROOT, "permission") in result.refusals
    # ...and reached through the scout's own read tool too, not only through a directory listing.
    box = open_sandbox(ENGINEER, root)
    outcome = Explorer(box).read(f"src/{LINK}")
    assert not outcome.served
    assert outcome.code is ErrorCode.OUTSIDE_ROOT
    assert outcome.category == "permission"
    assert outcome.text is None

    # ...reported by code in the brief, and the denied path is nowhere in anything produced.
    assert "sandbox.outside_root" in result.brief.coverage.unread_reason
    assert "permission" in result.brief.coverage.unread_reason
    for needle in needles:
        assert not leaks(needle, text)
    assert not leaks("zz-leaklink", text)
    assert not leaks("/etc/passwd", text)
    # The refused link is not one of the files the brief counts, and nothing served is the target.
    assert result.brief.coverage.files_total == 51
    assert not any(LINK in name for name in result.served)


# -- a symlink to <root>/.env -----------------------------------------------------------------


def test_a_symlink_to_the_env_file_is_refused_because_the_deny_list_read_the_resolved_path(
    tmp_path: Path,
) -> None:
    root = copy_sample(tmp_path)
    (root / ".env").write_text(f"DB_PASSWORD={MARKER}-0042\n")
    # The link's own name is harmless: only the *resolved* path is denied.
    (root / "src" / LINK).symlink_to(root / ".env")
    (root / LINK).symlink_to(root / ".env")

    provider = demo_provider()
    result = scout(root, provider)
    text = everything(result, *requests_of(provider))

    box = open_sandbox(ENGINEER, root)
    outcome = Explorer(box).read(f"src/{LINK}")
    assert not outcome.served
    assert outcome.code is ErrorCode.DENIED_NAME
    assert outcome.category == "permission"

    assert (ErrorCode.DENIED_NAME, "permission") in result.refusals
    assert "sandbox.denied_name" in result.brief.coverage.unread_reason
    assert not leaks(MARKER, text)
    assert not leaks("zz-leaklink", text)
    # The deny list's *pattern* is the sandbox's business: the reason carries the code only.
    for pattern in (".env", "DB_PASSWORD"):
        assert pattern not in result.brief.coverage.unread_reason
    assert not any(step.target.endswith(LINK) for step in result.steps)


def test_a_denied_directory_denies_everything_beneath_it_and_is_reported_by_code(
    tmp_path: Path,
) -> None:
    root = copy_sample(tmp_path)
    for relative in (
        ".git/zz-hidden-7731.txt",
        "secrets/zz-hidden-7732.txt",
        "config/id_rsa",
        "keys/server.pem",
        ".claude/zz-hidden-7733.md",
    ):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{MARKER}-{path.name}\n")

    provider = demo_provider()
    result = scout(root, provider)
    text = everything(result, *requests_of(provider))
    assert (ErrorCode.DENIED_NAME, "permission") in result.refusals
    assert not leaks(MARKER, text)
    assert not leaks("zz-hidden", text)
    reason = result.brief.coverage.unread_reason
    assert "sandbox.denied_name" in reason
    for pattern in (".git", "secrets", "id_", ".pem", ".claude"):
        assert pattern not in reason
    # Nothing under a denied name is in the count of what the sandbox would serve: `id_rsa` is
    # the only file in `config/`, and it is refused, so the count is the sample's own.
    assert result.brief.coverage.files_total == 51
    assert not any(name.startswith(("config/", "keys/")) for name in result.served)


# -- the brief never contains a secret-shaped string ------------------------------------------


def test_a_file_that_looks_like_a_credential_is_withheld_even_under_an_innocent_name(
    tmp_path: Path,
) -> None:
    # The sandbox's own docstring names this hole: a hard link has no second path to match, so the
    # deny list cannot see it. The content-level check is this slice's.
    root = copy_sample(tmp_path)
    (root / ".env").write_text(f"API_SECRET_KEY=sk-live-{MARKER}-9f8e7d6c5b4a\n")
    os.link(root / ".env", root / "src" / "notes.txt")
    (root / "build.properties").write_text(
        (SAMPLE / "build.properties").read_text("utf-8") + "notes=src/notes.txt\n"
    )

    provider = demo_provider()
    result = scout(root, provider)
    text = everything(result, *requests_of(provider))

    assert result.withheld == 1
    assert "src/notes.txt" not in result.served
    assert not leaks(MARKER, text)
    assert "withheld" in result.brief.coverage.unread_reason
    assert any(step.target == "[withheld]" for step in result.steps)
    # The step that read it names no file: the placeholder is all the record keeps. (The name it
    # was *listed* under is a path the sandbox offered, so an earlier "read next" line carries it.)
    assert [step.outcome for step in result.steps if step.target == "[withheld]"] == ["withheld"]


def test_the_demo_brief_holds_no_secret_shaped_string() -> None:
    from kit.scout.secrets import looks_secret

    result = scout(SAMPLE)
    dumped = result.brief.model_dump()
    strings: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(dumped)
    assert len(strings) > 20  # the walk found the strings: an empty list would pass vacuously
    assert not [s for s in strings if looks_secret(s)]


def test_the_leak_check_can_fail(tmp_path: Path) -> None:
    # A positive control. A marker in a file the sandbox *does* serve must show up in the prompt;
    # if this did not, "the marker is absent" above would mean nothing.
    root = copy_sample(tmp_path)
    path = root / "build.properties"
    path.write_text(path.read_text("utf-8") + f"note={MARKER}-served\n")
    provider = demo_provider()
    result = scout(root, provider)
    assert leaks(f"{MARKER}-served", everything(result, *requests_of(provider)))


def test_the_recording_loads_from_the_documented_directory() -> None:
    assert (DEMO_REPLIES / "brief.json").is_file()
