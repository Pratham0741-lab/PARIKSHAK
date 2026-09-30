"""System configuration for the UI: datasheet limits, decision costs and the current learned thresholds."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.core.database import get_async_db
from backend.app.models import ScreeningRun
from ml_engine.module_b_drift import load_default_config
from ml_engine.screening import INTERVAL_COVERAGE
from ml_engine.verdict_engine import ScreeningVerdictEngine

router = APIRouter(prefix="/config", tags=["System"])


@router.get("", summary="Datasheet limits, decision costs, learned thresholds and model configuration")
async def get_config(db: AsyncSession = Depends(get_async_db)) -> Dict[str, Any]:
    run = (await db.execute(select(ScreeningRun).order_by(ScreeningRun.created_at.desc()).limit(1))).scalars().first()
    return {
        "datasheet_limits": ScreeningVerdictEngine.datasheet_limits(),
        "cost": {"fn_cost": settings.FN_COST, "fp_cost": settings.FP_COST, "recall_target": settings.RECALL_TARGET},
        "threshold_strategy": settings.THRESHOLD_STRATEGY,
        "interval_coverage_target": INTERVAL_COVERAGE,
        "module_b_config": load_default_config(),
        "latest_run": None if run is None else {
            "id": str(run.id),
            "created_at": run.created_at.isoformat(),
            "protocol": run.protocol,
            "final_thresholds": run.final_thresholds,
        },
    }
