"""
API v1 unified router aggregator.
"""

from fastapi import APIRouter
from backend.app.api.v1.lots import router as lots_router
from backend.app.api.v1.components import router as components_router
from backend.app.api.v1.reviews import router as reviews_router
from backend.app.api.v1.metrics import router as metrics_router

api_v1_router = APIRouter(prefix="/api/v1")

api_v1_router.include_router(lots_router)
api_v1_router.include_router(components_router)
api_v1_router.include_router(reviews_router)
api_v1_router.include_router(metrics_router)
