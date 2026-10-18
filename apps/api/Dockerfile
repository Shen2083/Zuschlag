# syntax=docker/dockerfile:1.7
# Build from the repository root:  docker build -f apps/api/Dockerfile .

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra llm --extra embeddings --no-install-project
COPY apps/api/src ./src
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra llm --extra embeddings

# Optionally bake the embedding model into the image so production never
# downloads weights at runtime:  --build-arg PRELOAD_EMBEDDING_MODEL=intfloat/multilingual-e5-large
ARG PRELOAD_EMBEDDING_MODEL=""
ENV HF_HOME=/app/.cache/huggingface
RUN if [ -n "$PRELOAD_EMBEDDING_MODEL" ]; then \
      /app/.venv/bin/python -c "import sys; from sentence_transformers import SentenceTransformer; SentenceTransformer(sys.argv[1])" "$PRELOAD_EMBEDDING_MODEL"; \
    fi

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC \
    HF_HOME=/app/.cache/huggingface
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=build --chown=app:app /app /app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"
# --proxy-headers only trusts X-Forwarded-For from the load balancer subnet set in FORWARDED_ALLOW_IPS.
CMD ["uvicorn", "zuschlag_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header"]
