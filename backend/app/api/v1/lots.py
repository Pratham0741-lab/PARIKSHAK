"""
Lots API endpoints: summary counts, triage breakdown, and parametric distributions.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_async_db
from backend.app.models.component import Component
from backend.app.models.lot import Lot
from backend.app.models.prediction import ModelPrediction, ScreeningVerdict
from backend.app.models.reading import BurnInReading
from backend.app.schemas.lot import (
    IntervalStats,
    LotDistributionResponse,
    LotSummary,
    ParameterDistribution,
)
from backend.app.services.local_explainer import DeterministicExplainer

router = APIRouter(prefix="/lots", tags=["Lots"])
explainer = DeterministicExplainer()


@router.get("", response_model=List[LotSummary], summary="List all manufacturing lots with triage counts")
async def list_lots(
    db: AsyncSession = Depends(get_async_db),
) -> List[LotSummary]:
    """
    Returns all manufacturing lots with total component counts and triage status breakdown.
    """
    stmt = (
        select(
            Lot.id,
            Lot.lot_number,
            Lot.wafer_id,
            Lot.status,
            Lot.created_at,
            func.count(Component.id).label("total_components"),
            func.count(case((ModelPrediction.verdict == ScreeningVerdict.PASS, 1))).label("pass_count"),
            func.count(case((ModelPrediction.verdict == ScreeningVerdict.REVIEW, 1))).label("review_count"),
            func.count(case((ModelPrediction.verdict == ScreeningVerdict.REJECT, 1))).label("reject_count"),
        )
        .outerjoin(Component, Component.lot_id == Lot.id)
        .outerjoin(ModelPrediction, ModelPrediction.component_id == Component.id)
        .group_by(Lot.id)
        .order_by(Lot.lot_number)
    )

    result = await db.execute(stmt)
    rows = result.all()

    return [
        LotSummary(
            id=r.id,
            lot_number=r.lot_number,
            wafer_id=r.wafer_id,
            status=r.status.value if hasattr(r.status, "value") else str(r.status),
            created_at=r.created_at,
            total_components=r.total_components,
            pass_count=r.pass_count,
            review_count=r.review_count,
            reject_count=r.reject_count,
        )
        for r in rows
    ]


@router.get(
    "/{lot_id}/distribution",
    response_model=LotDistributionResponse,
    summary="Get lot statistical envelope per parameter and interval",
)
async def get_lot_distribution(
    lot_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> LotDistributionResponse:
    """
    Returns lot-level statistical envelope (min, p25, median, p75, max, MAD)
    per parameter per interval (0h, 24h, 96h, 168h) for box-plot and band rendering.
    """
    # 1. Fetch lot
    lot_stmt = select(Lot).where(Lot.id == lot_id)
    lot_res = await db.execute(lot_stmt)
    lot = lot_res.scalar_one_or_none()
    if not lot:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Lot with id '{lot_id}' not found.",
        )

    # 2. Fetch all readings for components in this lot
    readings_stmt = (
        select(
            BurnInReading.interval_hours,
            BurnInReading.leakage_current_ua,
            BurnInReading.iddq_ma,
            BurnInReading.propagation_delay_ns,
        )
        .join(Component, Component.id == BurnInReading.component_id)
        .where(Component.lot_id == lot_id)
    )
    readings_res = await db.execute(readings_stmt)
    reading_rows = readings_res.all()

    if not reading_rows:
        return LotDistributionResponse(
            lot_id=lot.id,
            lot_number=lot.lot_number,
            wafer_id=lot.wafer_id,
            parameters=[],
        )

    readings_dicts: List[Dict[str, Any]] = [
        {
            "interval_hours": r.interval_hours,
            "leakage_current_ua": r.leakage_current_ua,
            "iddq_ma": r.iddq_ma,
            "propagation_delay_ns": r.propagation_delay_ns,
        }
        for r in reading_rows
    ]

    stats = explainer.compute_lot_statistics(readings_dicts)

    param_meta = [
        ("leakage_current_ua", "Leakage Current (uA)", "uA", 50.0),
        ("iddq_ma", "IDDQ Current (mA)", "mA", 5.0),
        ("propagation_delay_ns", "Propagation Delay (ns)", "ns", 8.0),
    ]

    param_dists: List[ParameterDistribution] = []
    for param_key, label, unit, ceiling in param_meta:
        intervals_stats: List[IntervalStats] = []
        if param_key in stats:
            for interval in sorted(stats[param_key].keys()):
                idata = stats[param_key][interval]
                intervals_stats.append(
                    IntervalStats(
                        interval_hours=interval,
                        min=round(idata["min"], 4),
                        p25=round(idata["p25"], 4),
                        median=round(idata["median"], 4),
                        p75=round(idata["p75"], 4),
                        max=round(idata["max"], 4),
                        mad=round(idata["mad"], 4),
                    )
                )
        param_dists.append(
            ParameterDistribution(
                parameter=param_key,
                label=label,
                unit=unit,
                datasheet_max=ceiling,
                intervals=intervals_stats,
            )
        )

    return LotDistributionResponse(
        lot_id=lot.id,
        lot_number=lot.lot_number,
        wafer_id=lot.wafer_id,
        parameters=param_dists,
    )
