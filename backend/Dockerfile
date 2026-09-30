# ==============================================================================
# Multi-stage Dockerfile for FastAPI Analytical Backend
# Python 3.11 Slim, Non-root execution, Pre-installed Wheels
# ==============================================================================

# Stage 1: Build & Dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed python dependencies from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd -g 1001 appgroup && \
    useradd -u 1001 -g appgroup -s /bin/bash -m appuser

# Copy application code
COPY alembic.ini .
COPY backend ./backend
COPY data_engine ./data_engine
COPY ml_engine ./ml_engine
COPY evaluation ./evaluation
COPY scripts ./scripts
RUN mkdir -p /app/artifacts /app/reports

# Grant permissions to non-root user
RUN chown -R appuser:appgroup /app

USER appuser

EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["/bin/bash", "scripts/bootstrap.sh"]
