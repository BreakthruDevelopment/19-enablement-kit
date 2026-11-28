"""The Dockerfile contract for running as an AWS Lambda behind the Lambda Web Adapter.

Needs no Docker. Comment lines are stripped before every check, so a guard cannot be satisfied (or
survive) by a commented-out instruction.
"""

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = "public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1"


def _instructions(stage: str | None = None) -> list[str]:
    """Instructions with comments dropped and continuations joined; optionally one stage."""
    lines = [
        line
        for line in (ROOT / "Dockerfile").read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    joined = re.sub(r"\\\s*\n", " ", "\n".join(lines))
    out = [" ".join(i.split()) for i in joined.splitlines() if i.strip()]
    if stage is None:
        return out
    start = next(n for n, i in enumerate(out) if re.match(rf"FROM .* AS {stage}$", i))
    rest = out[start + 1 :]
    end = next((n for n, i in enumerate(rest) if i.startswith("FROM ")), len(rest))
    return rest[:end]


def _runner() -> list[str]:
    return _instructions("runner")


def _index(prefix: str) -> int:
    hits = [n for n, i in enumerate(_runner()) if i.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly one {prefix!r} in the runner stage, found {len(hits)}"
    return hits[0]


def test_adapter_is_copied_from_the_pinned_version_into_extensions() -> None:
    copy = _runner()[_index("COPY --from=public.ecr.aws/")]
    assert copy == f"COPY --from={ADAPTER} /lambda-adapter /opt/extensions/lambda-adapter"


def test_adapter_is_copied_before_user_so_it_keeps_its_exec_bit() -> None:
    assert _index("COPY --from=public.ecr.aws/") < _index("USER ")


def test_adapter_architecture_is_checked_in_the_build() -> None:
    check = _runner()[_index("RUN set -eu;")]
    assert "amd64) want=62" in check
    assert "arm64) want=183" in check
    assert "od -An -tu2 -j18 -N2 /opt/extensions/lambda-adapter" in check
    # A mismatch must fail the build: exit 1 inside the comparison's own then-branch.
    assert re.search(r'\[ "\$got" != "\$want" \]; then [^;]*;\s*exit 1; fi', check)
    assert _index("ARG TARGETARCH") < _index("RUN set -eu;")
    # The check must run on the adapter, so after it lands.
    assert _index("COPY --from=public.ecr.aws/") < _index("RUN set -eu;")


def test_port_env_matches_expose() -> None:
    runner = _runner()
    env = runner[_index("ENV ")]
    port = re.search(r"\bPORT=(\d+)\b", env)
    assert port, "the runner ENV line must set PORT: the Lambda stack sets AWS_LWA_PORT and no PORT"
    exposed = re.fullmatch(r"EXPOSE (\d+)", runner[_index("EXPOSE ")])
    assert exposed
    assert port.group(1) == exposed.group(1) == "3000"


def test_entrypoint_is_absolute_and_in_the_venv() -> None:
    entry = _runner()[_index("ENTRYPOINT ")]
    assert entry == 'ENTRYPOINT ["/opt/venv/bin/kit"]'


def test_build_stage_installs_from_a_checked_lock() -> None:
    sync = [i for i in _instructions("build") if "uv sync" in i]
    assert len(sync) == 1
    assert "--locked" in sync[0]
    assert "--frozen" not in sync[0]


def test_cmd_is_still_version_until_the_http_surface_exists() -> None:
    # Deliberate: slice 19.11 owns the serving command. Change this test with that slice.
    assert _runner()[_index("CMD ")] == 'CMD ["--version"]'


# --- The architecture check, run rather than read ------------------------------------------------
#
# Everything above asserts the Dockerfile's *text*. That ceiling is real: a reviewer of this branch
# wrote four mutations that keep the text matching while the check protects nothing -- `want=$got`,
# `if false && [ "$got" != "$want" ]`, `*) exit 0`, and `*) want=62`. Each builds, and each would
# hand a wrong-architecture adapter to a deployed Lambda. So this block extracts the snippet and
# executes it under `sh` against crafted ELF headers, which pins what it *does*.


def _arch_check_script() -> str:
    """The `RUN` that checks the adapter's architecture, as a runnable shell script."""
    runs = [i for i in _instructions("runner") if i.startswith("RUN ") and "e_machine" in i]
    assert len(runs) == 1, f"expected exactly one architecture check, found {len(runs)}"
    return runs[0].removeprefix("RUN ")


def _elf_header(e_machine: int) -> bytes:
    """A 64-byte little-endian ELF64 header carrying `e_machine` at offset 18."""
    header = bytearray(64)
    header[0:4] = b"\x7fELF"
    header[4] = 2  # ELFCLASS64
    header[5] = 1  # ELFDATA2LSB
    header[6] = 1  # EV_CURRENT
    header[16:18] = (2).to_bytes(2, "little")  # ET_EXEC
    header[18:20] = e_machine.to_bytes(2, "little")
    return bytes(header)


def _run_arch_check(tmp_path: Path, target_arch: str, e_machine: int) -> int:
    adapter = tmp_path / "lambda-adapter"
    adapter.write_bytes(_elf_header(e_machine))
    script = _arch_check_script()
    # The snippet names the image path; point it at the crafted file instead. Asserting the
    # substitution happened keeps this test from silently checking nothing if that path changes.
    assert "/opt/extensions/lambda-adapter" in script
    script = script.replace("/opt/extensions/lambda-adapter", str(adapter))
    return subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", script],
        env={"PATH": os.environ["PATH"], "TARGETARCH": target_arch},
        capture_output=True,
    ).returncode


@pytest.mark.parametrize(
    ("target_arch", "e_machine"),
    [("amd64", 62), ("arm64", 183)],
)
def test_the_architecture_check_accepts_the_matching_adapter(
    tmp_path: Path, target_arch: str, e_machine: int
) -> None:
    assert _run_arch_check(tmp_path, target_arch, e_machine) == 0


@pytest.mark.parametrize(
    ("target_arch", "e_machine"),
    [
        ("amd64", 183),  # an arm64 adapter in an amd64 build
        ("arm64", 62),  # the one that would reach the deployed arm64 Lambda
    ],
)
def test_the_architecture_check_refuses_a_wrong_architecture_adapter(
    tmp_path: Path, target_arch: str, e_machine: int
) -> None:
    assert _run_arch_check(tmp_path, target_arch, e_machine) != 0


def test_an_unsupported_target_architecture_is_refused(tmp_path: Path) -> None:
    # The header is amd64-shaped on purpose: a `*)` branch falling through to `want=62` would
    # accept it, and refusing it is what distinguishes `*) exit 1` from `*) want=62`.
    assert _run_arch_check(tmp_path, "riscv64", 62) != 0
