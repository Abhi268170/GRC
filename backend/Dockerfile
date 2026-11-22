# syntax=docker/dockerfile:1
# Build with the shared AI service API models as an extra context (see docker-compose.yml):
#   docker build --build-context contracts=../packages/ai_contracts ./backend
FROM python:3.13.18-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# INSTALL_DEV=true adds the test and lint tools (used by docker-compose.test.yml).
ARG INSTALL_DEV=false
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ "$INSTALL_DEV" = "true" ]; then uv sync --frozen; else uv sync --frozen --no-dev; fi

RUN useradd --create-home --uid 1000 app
COPY --chown=app . .
COPY --chown=app --from=contracts ai_contracts /app/ai_contracts
USER app

EXPOSE 8000
# docker-compose.yml overrides this with the production flags (proxy headers, several workers).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--root-path", "/api"]
