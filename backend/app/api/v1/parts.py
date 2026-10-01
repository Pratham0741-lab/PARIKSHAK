"""
Lot parts endpoint for the UI: readings, persisted model prediction and latest QA decision per part.

Ground-truth labels are deliberately NOT part of this response: the UI must derive every status
from model decisions and inspector reviews, never from labels.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.database import get_async_db
from backend.app.models import Component, Lot
from backend.app.schemas.component import ModelPredictionItem

router = APIRouter(prefix="/lots", tags=["Lots"])


class PartReading(BaseModel):
    interval_hours: int
    leakage_current_ua: Optional[float] = None  # null when the parameter is absent from the lot
    iddq_ma: Optional[float] = None  # null when the parameter is absent from the lot
    propagation_delay_ns: Optional[float] = None  # null when the parameter is absent from the lot
    imputed_fields: Optional[List[str]] = None


class PartDecision(BaseModel):
    disposition: str
    original_verdict: str
    inspector_id: str
    inspector_notes: str
    reviewed_at: datetime


class PartItem(BaseModel):
    id: uuid.UUID
    lot_id: uuid.UUID
    serial_number: str
    insufficient_data: bool
    readings: List[PartReading]
    prediction: Optional[ModelPredictionItem] = None
    latest_decision: Optional[PartDecision] = None


def _v(x: Any) -> Any:
    return x.value if hasattr(x, "value") else x


def _r(x, nd):
    return None if x is None else round(x, nd)


@router.get("/{lot_id}/parts", response_model=List[PartItem], summary="All parts of a lot with readings, prediction and latest decision")
async def list_lot_parts(lot_id: uuid.UUID, db: AsyncSession = Depends(get_async_db)) -> List[PartItem]:
    if not (await db.execute(select(Lot.id).where(Lot.id == lot_id))).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Lot {lot_id} not found")
    comps = (
        await db.execute(
            select(Component)
            .where(Component.lot_id == lot_id)
            .options(selectinload(Component.readings), selectinload(Component.prediction), selectinload(Component.reviews))
            .order_by(Component.serial_number)
        )
    ).scalars().all()

    out: List[PartItem] = []
    for c in comps:
        p = c.prediction
        pred = None
        if p is not None:
            pred = ModelPredictionItem(
                id=p.id, module_a_score=_r(p.module_a_score, 4), module_a_mahalanobis=_r(p.module_a_mahalanobis, 4),
                module_a_flag=p.module_a_flag, pred_leakage_168h=_r(p.pred_leakage_168h, 4),
                pred_iddq_168h=_r(p.pred_iddq_168h, 4), pred_delay_168h=_r(p.pred_delay_168h, 4),
                drift_slope_ua_per_hr=_r(p.drift_slope_ua_per_hr, 6), module_b_flag=p.module_b_flag,
                module_b_score=p.module_b_score, threshold_a=p.threshold_a, threshold_b=p.threshold_b,
                safety_slope_ua_per_hr=p.safety_slope_ua_per_hr, details=p.details, cv_fold=p.cv_fold,
                verdict=_v(p.verdict), verdict_reason=p.verdict_reason, created_at=p.created_at,
            )
        latest = c.reviews[0] if c.reviews else None  # relationship is ordered newest first
        out.append(PartItem(
            id=c.id, lot_id=c.lot_id, serial_number=c.serial_number, insufficient_data=c.insufficient_data,
            readings=[PartReading(interval_hours=r.interval_hours, leakage_current_ua=r.leakage_current_ua,
                                  iddq_ma=r.iddq_ma, propagation_delay_ns=r.propagation_delay_ns,
                                  imputed_fields=r.imputed_fields) for r in c.readings],
            prediction=pred,
            latest_decision=None if latest is None else PartDecision(
                disposition=_v(latest.disposition), original_verdict=_v(latest.original_verdict),
                inspector_id=latest.inspector_id, inspector_notes=latest.inspector_notes,
                reviewed_at=latest.reviewed_at),
        ))
    return out
