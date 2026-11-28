"""The Dockerfile contract for running as an AWS Lambda behind the Lambda Web Adapter.

Needs no Docker. Comment lines are stripped before every check, so a guard cannot be satisfied (or
survive) by a commented-out instruction.
"""

import re
from pathlib import Path

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
    assert '"$got" != "$want"' in check and "exit 1" in check
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
