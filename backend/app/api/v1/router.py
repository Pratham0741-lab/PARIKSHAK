"""
API v1 unified router aggregator.
"""

from fastapi import APIRouter

from backend.app.api.v1.audit import router as audit_router
from backend.app.api.v1.components import router as components_router
from backend.app.api.v1.debug import router as debug_router
from backend.app.api.v1.ingest import router as ingest_router
from backend.app.api.v1.judge import router as judge_router
from backend.app.api.v1.lots import router as lots_router
from backend.app.api.v1.metrics import router as metrics_router
from backend.app.api.v1.model_artifacts import router as model_artifacts_router
from backend.app.api.v1.parts import router as parts_router
from backend.app.api.v1.reviews import router as reviews_router
from backend.app.api.v1.system import router as system_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(lots_router)
api_v1_router.include_router(components_router)
api_v1_router.include_router(reviews_router)
api_v1_router.include_router(metrics_router)
api_v1_router.include_router(ingest_router)
api_v1_router.include_router(audit_router)
api_v1_router.include_router(parts_router)
api_v1_router.include_router(system_router)
api_v1_router.include_router(judge_router)
api_v1_router.include_router(debug_router)
api_v1_router.include_router(model_artifacts_router)
