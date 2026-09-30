"""
Components API endpoints: listing with filters, detailed inspection profile, and deterministic explainability.
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.database import get_async_db
from backend.app.models.component import Component, GroundTruthLabel
from backend.app.models.lot import Lot
from backend.app.models.prediction import ModelPrediction, ScreeningVerdict
from backend.app.models.reading import BurnInReading
from backend.app.models.review import InspectorReview
from backend.app.schemas.component import (
    ComponentListItem,
    ComponentProfileResponse,
    ModelPredictionItem,
    PaginatedComponentsResponse,
    ReadingItem,
)
from backend.app.schemas.explanation import ExplanationResponse
from backend.app.schemas.review import ReviewItem
from backend.app.services.lot_stats import compute_lot_statistics
from ml_engine.explain import build_explanation

router = APIRouter(prefix="/components", tags=["Components"])


@router.get("", response_model=PaginatedComponentsResponse, summary="Query components with pagination and triage filters")
async def list_components(
    lot_id: Optional[uuid.UUID] = Query(None, description="Filter by Lot UUID"),
    verdict: Optional[ScreeningVerdict] = Query(None, description="Filter by Screening Verdict: PASS, REVIEW, REJECT"),
    ground_truth_flag: Optional[bool] = Query(None, description="Filter by Ground Truth Defect Flag"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
    db: AsyncSession = Depends(get_async_db),
) -> PaginatedComponentsResponse:
    """
    Returns a paginated list of components filterable by manufacturing lot, triage verdict,
    and ground truth defect status.
    """
    # Base query for count
    count_query = select(func.count(Component.id)).outerjoin(ModelPrediction, ModelPrediction.component_id == Component.id)
    if lot_id:
        count_query = count_query.where(Component.lot_id == lot_id)
    if verdict:
        count_query = count_query.where(ModelPrediction.verdict == verdict)
    if ground_truth_flag is not None:
        count_query = count_query.where(Component.ground_truth_flag == ground_truth_flag)

    total_res = await db.execute(count_query)
    total_count = total_res.scalar_one()

    # Query for items
    stmt = (
        select(
            Component.id,
            Component.lot_id,
            Lot.lot_number,
            Component.serial_number,
            Component.ground_truth_label,
            Component.ground_truth_flag,
            Component.is_datasheet_breached,
            ModelPrediction.verdict,
            ModelPrediction.module_a_score,
            ModelPrediction.pred_leakage_168h,
            ModelPrediction.drift_slope_ua_per_hr,
        )
        .join(Lot, Lot.id == Component.lot_id)
        .outerjoin(ModelPrediction, ModelPrediction.component_id == Component.id)
    )

    if lot_id:
        stmt = stmt.where(Component.lot_id == lot_id)
    if verdict:
        stmt = stmt.where(ModelPrediction.verdict == verdict)
    if ground_truth_flag is not None:
        stmt = stmt.where(Component.ground_truth_flag == ground_truth_flag)

    offset = (page - 1) * page_size
    stmt = stmt.order_by(Component.serial_number).offset(offset).limit(page_size)

    result = await db.execute(stmt)
    rows = result.all()

    items = [
        ComponentListItem(
            id=r.id,
            lot_id=r.lot_id,
            lot_number=r.lot_number,
            serial_number=r.serial_number,
            ground_truth_label=r.ground_truth_label.value if hasattr(r.ground_truth_label, "value") else str(r.ground_truth_label),
            ground_truth_flag=r.ground_truth_flag,
            is_datasheet_breached=r.is_datasheet_breached,
            verdict=r.verdict.value if r.verdict and hasattr(r.verdict, "value") else (str(r.verdict) if r.verdict else None),
            module_a_score=r.module_a_score,
            pred_leakage_168h=r.pred_leakage_168h,
            drift_slope_ua_per_hr=r.drift_slope_ua_per_hr,
        )
        for r in rows
    ]

    total_pages = math.ceil(total_count / page_size) if total_count > 0 else 0

    return PaginatedComponentsResponse(
        total=total_count,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=items,
    )


@router.get(
    "/{component_id}/profile",
    response_model=ComponentProfileResponse,
    summary="Get comprehensive component inspection profile with time-series and lot bands",
)
async def get_component_profile(
    component_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> ComponentProfileResponse:
    """
    Returns full component metadata, raw readings time-series (0h, 24h, 96h, 168h),
    lot statistical envelope bands, ModelPrediction record, and QA review history.
    """
    stmt = (
        select(Component)
        .where(Component.id == component_id)
        .options(
            selectinload(Component.lot),
            selectinload(Component.readings),
            selectinload(Component.prediction),
            selectinload(Component.reviews),
        )
    )
    result = await db.execute(stmt)
    component = result.scalar_one_or_none()

    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component with id '{component_id}' not found.",
        )

    # Fetch lot readings to construct lot envelope bands
    lot_readings_stmt = (
        select(
            BurnInReading.interval_hours,
            BurnInReading.leakage_current_ua,
            BurnInReading.iddq_ma,
            BurnInReading.propagation_delay_ns,
        )
        .join(Component, Component.id == BurnInReading.component_id)
        .where(Component.lot_id == component.lot_id)
    )
    lot_res = await db.execute(lot_readings_stmt)
    lot_reading_rows = lot_res.all()

    lot_envelope: Optional[Dict[str, Any]] = None
    if lot_reading_rows:
        readings_dicts = [
            {
                "interval_hours": r.interval_hours,
                "leakage_current_ua": r.leakage_current_ua,
                "iddq_ma": r.iddq_ma,
                "propagation_delay_ns": r.propagation_delay_ns,
            }
            for r in lot_reading_rows
        ]
        lot_envelope = compute_lot_statistics(readings_dicts)

    # Format readings
    readings_items = [
        ReadingItem(
            interval_hours=r.interval_hours,
            leakage_current_ua=round(r.leakage_current_ua, 4),
            iddq_ma=round(r.iddq_ma, 4),
            propagation_delay_ns=round(r.propagation_delay_ns, 4),
            recorded_at=r.recorded_at,
        )
        for r in component.readings
    ]

    # Format prediction
    pred_item: Optional[ModelPredictionItem] = None
    if component.prediction:
        p = component.prediction
        pred_item = ModelPredictionItem(
            id=p.id,
            module_a_score=round(p.module_a_score, 4),
            module_a_mahalanobis=round(p.module_a_mahalanobis, 4),
            module_a_flag=p.module_a_flag,
            pred_leakage_168h=round(p.pred_leakage_168h, 3),
            pred_iddq_168h=round(p.pred_iddq_168h, 3),
            pred_delay_168h=round(p.pred_delay_168h, 3),
            drift_slope_ua_per_hr=round(p.drift_slope_ua_per_hr, 4),
            module_b_flag=p.module_b_flag,
            module_b_score=p.module_b_score,
            threshold_a=p.threshold_a,
            threshold_b=p.threshold_b,
            safety_slope_ua_per_hr=p.safety_slope_ua_per_hr,
            details=p.details,
            cv_fold=p.cv_fold,
            verdict=p.verdict.value if hasattr(p.verdict, "value") else str(p.verdict),
            verdict_reason=p.verdict_reason,
            created_at=p.created_at,
        )

    # Format reviews
    review_items = [
        ReviewItem(
            id=rev.id,
            component_id=rev.component_id,
            inspector_id=rev.inspector_id,
            original_verdict=rev.original_verdict.value if hasattr(rev.original_verdict, "value") else str(rev.original_verdict),
            disposition=rev.disposition.value if hasattr(rev.disposition, "value") else str(rev.disposition),
            inspector_notes=rev.inspector_notes,
            reviewed_at=rev.reviewed_at,
        )
        for rev in component.reviews
    ]

    return ComponentProfileResponse(
        id=component.id,
        lot_id=component.lot_id,
        lot_number=component.lot.lot_number,
        wafer_id=component.lot.wafer_id,
        serial_number=component.serial_number,
        ground_truth_label=component.ground_truth_label.value if hasattr(component.ground_truth_label, "value") else str(component.ground_truth_label),
        ground_truth_flag=component.ground_truth_flag,
        is_datasheet_breached=component.is_datasheet_breached,
        readings=readings_items,
        prediction=pred_item,
        reviews=review_items,
        lot_envelope=lot_envelope,
    )


def prediction_dict(p: ModelPrediction) -> Dict[str, Any]:
    return {
        "module_a_score": p.module_a_score,
        "module_a_flag": p.module_a_flag,
        "module_b_score": p.module_b_score,
        "module_b_flag": p.module_b_flag,
        "threshold_a": p.threshold_a,
        "threshold_b": p.threshold_b,
        "pred_leakage_168h": p.pred_leakage_168h,
        "pred_iddq_168h": p.pred_iddq_168h,
        "pred_delay_168h": p.pred_delay_168h,
        "verdict": p.verdict.value if hasattr(p.verdict, "value") else str(p.verdict),
        "verdict_reason": p.verdict_reason,
        "details": p.details or {},
    }


@router.get(
    "/{component_id}/explain",
    response_model=ExplanationResponse,
    summary="Per-part explanation generated from this part's model outputs",
)
async def explain_component(
    component_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
) -> ExplanationResponse:
    """
    Builds the explanation from the persisted prediction for this part: Module A's additive
    decomposition (robust z per parameter vs its own lot), Module B's TreeSHAP contributions,
    the calculated lot safety slope, the conformal prediction interval and the static-limit status.
    """
    stmt = (
        select(Component)
        .where(Component.id == component_id)
        .options(selectinload(Component.lot), selectinload(Component.readings), selectinload(Component.prediction))
    )
    component = (await db.execute(stmt)).scalar_one_or_none()
    if not component:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Component with id '{component_id}' not found.")
    if component.prediction is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Component has no screening prediction yet.")

    readings = [
        {
            "interval_hours": r.interval_hours,
            "leakage_current_ua": r.leakage_current_ua,
            "iddq_ma": r.iddq_ma,
            "propagation_delay_ns": r.propagation_delay_ns,
        }
        for r in component.readings
    ]
    exp = build_explanation(prediction_dict(component.prediction), readings, component.serial_number,
                            component.lot.lot_number)
    return ExplanationResponse(component_id=component.id, cv_fold=component.prediction.cv_fold, **exp)
