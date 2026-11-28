# Minimal image: the locked runtime dependencies and the package, nothing else. No credentials are baked in.
# App 17 is a git dependency (pinned by tag in pyproject.toml), so the build stage needs git.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY kit ./kit
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim AS runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH PORT=3000
COPY --from=build /opt/venv /opt/venv

# AWS Lambda Web Adapter: the Lambda stack runs this image as a package_type="Image" function, which must
# speak the Lambda Runtime API. The adapter does that and proxies to the HTTP server; it is inert elsewhere.
# Copied before USER so it keeps its exec bit.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

# COPY --from an external image can hand over a wrong-architecture binary. Prove it: ELF e_machine is at
# offset 18, 2 bytes little-endian (62 = x86-64, 183 = AArch64).
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) want=62 ;; \
      arm64) want=183 ;; \
      *) echo "adapter check: unsupported TARGETARCH" >&2; exit 1 ;; \
    esac; \
    got=$(od -An -tu2 -j18 -N2 /opt/extensions/lambda-adapter | tr -d ' \n'); \
    if [ "$got" != "$want" ]; then \
      echo "adapter check: ELF e_machine $got, expected $want" >&2; exit 1; \
    fi

RUN useradd --system --uid 10001 app
USER app
EXPOSE 3000
# Absolute: /opt/venv/bin is not on Lambda's default PATH. CMD stays --version until the HTTP surface
# (slice 19.11) provides a serving command; this image cannot serve yet.
ENTRYPOINT ["/opt/venv/bin/kit"]
CMD ["--version"]
