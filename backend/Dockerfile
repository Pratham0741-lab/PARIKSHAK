# syntax=docker/dockerfile:1.7
# ==============================================================================
# FastAPI backend (Python 3.11 slim, non-root).
# All Python dependencies install from prebuilt wheels (no compiler needed). The only system package
# is libgomp1 (OpenMP runtime required by LightGBM). Network steps retry and use BuildKit caches,
# because concurrent `docker compose up --build` downloads were observed to drop connections.
# ==============================================================================

FROM python:3.11-slim AS builder
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    n=0; until pip install --retries 10 --timeout 60 --only-binary=:all: --prefix=/install -r requirements.txt; \
    do n=$((n+1)); [ "$n" -ge 4 ] && exit 1; echo "pip retry $n"; sleep 15; done

FROM python:3.11-slim AS runner
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean; \
    n=0; until apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends libgomp1; \
    do n=$((n+1)); [ "$n" -ge 4 ] && exit 1; echo "apt retry $n"; sleep 15; done

COPY --from=builder /install /usr/local

RUN groupadd -g 1001 appgroup && useradd -u 1001 -g appgroup -s /bin/bash -m appuser

COPY alembic.ini .
COPY backend ./backend
COPY data_engine ./data_engine
COPY ml_engine ./ml_engine
COPY evaluation ./evaluation
COPY scripts ./scripts
RUN mkdir -p /app/artifacts /app/reports && chown -R appuser:appgroup /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

CMD ["/bin/bash", "scripts/bootstrap.sh"]
