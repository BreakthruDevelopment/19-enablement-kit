# Minimal image: the package and nothing else. No credentials are baked in.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml README.md ./
COPY kit ./kit
RUN uv build --wheel --out-dir /dist

FROM python:3.12-slim AS runner
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm /tmp/*.whl \
    && useradd --system --uid 10001 app
USER app
ENTRYPOINT ["kit"]
CMD ["--version"]
