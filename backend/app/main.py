"""
FastAPI Application Entry Point for ISRO SIH26170 Burn-In Screening & Analytics.
Features CORS middleware, API v1 routing, health checks, and lifecycle management.
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Automatically bootstrap project root into sys.path to allow execution from either backend/ or repo root
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.app.api.v1.router import api_v1_router
from backend.app.core.config import settings
from backend.app.core.database import async_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager for startup and shutdown procedures.
    """
    # Verify database connection on startup
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        print(f"[WARNING] Database connection check during startup: {exc}")
    yield
    # Dispose connection pools on shutdown
    await async_engine.dispose()


app = FastAPI(
    title="ISRO SIH26170 Burn-In Anomaly Detection & Screening System",
    description=(
        "Mission-critical screening and predictive degradation analytics platform for aerospace semiconductor components. "
        "Integrates lot-adaptive spatial outlier detection (Module A), 24h early drift forecasting (Module B), "
        "deterministic local explainability, and QA inspector audit trails."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS for the React (Vite) frontend; origins come from settings.CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API Routers
app.include_router(api_v1_router)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
async def health_check():
    """System health check endpoint."""
    return {
        "status": "HEALTHY",
        "app_name": settings.APP_NAME,
        "environment": settings.APP_ENV,
        "api_version": "v1",
    }
