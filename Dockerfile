# Serves the web support portal (support_automation.webapp.app) on :8000.
# Not used for the MCP server -- that's deployed separately via
# `arcade deploy` (see README's Arcade section), not this image.

# Pinned to linux/amd64 regardless of the host building it: on Apple
# Silicon, a plain `docker build` produces an arm64 image that fails on
# Fargate (the default architecture for ECS/App Runner/etc.) with "exec
# format error" -- learned this the hard way deploying to ECS Express
# Mode. Pinning here means every build command in DEPLOY.md and
# scripts/deploy-ecs-express.sh stays simple and correct without each
# one needing its own --platform flag.
FROM --platform=linux/amd64 python:3.12-slim AS base

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install dependencies first, without the project itself, so this layer
# stays cached across source-only changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY . /app

# Installs the project itself in the same editable mode `uv sync` uses in
# local dev (deliberately not --no-editable): support_automation.webapp.app
# locates data/ and static/ relative to its own source file
# (src/support_automation/webapp/app.py), which only resolves to the real
# repo root -- and therefore to the data/ this image just copied in -- when
# the install stays editable. See _config_paths.py's docstring for the
# same reasoning applied to config/.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM base
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /app

EXPOSE 8000
CMD ["uvicorn", "support_automation.webapp.app:app", "--host", "0.0.0.0", "--port", "8000"]
