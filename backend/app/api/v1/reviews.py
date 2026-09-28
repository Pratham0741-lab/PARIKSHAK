"""
Reviews API endpoints: QA human inspector review submission and audit log.
"""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.database import get_async_db
from backend.app.models.component import Component
from backend.app.models.prediction import ScreeningVerdict
from backend.app.models.review import InspectorReview, ReviewDisposition
from backend.app.schemas.review import ReviewActionRequest, ReviewActionResponse

router = APIRouter(prefix="/reviews", tags=["Reviews"])


@router.post(
    "/{component_id}/action",
    response_model=ReviewActionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record QA inspector override or disposition action",
)
async def submit_review_action(
    component_id: uuid.UUID,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_async_db),
) -> ReviewActionResponse:
    """
    Submits a human QA inspector review action. Persists an immutable InspectorReview
    audit record associated with the component, capturing badge ID, prior verdict,
    disposition (ACCEPTED, QUARANTINED, RE_TEST), and mandatory engineering notes.
    """
    stmt = (
        select(Component)
        .where(Component.id == component_id)
        .options(selectinload(Component.prediction))
    )
    result = await db.execute(stmt)
    component = result.scalar_one_or_none()

    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Component with id '{component_id}' not found.",
        )

    # Determine original verdict
    original_verdict = (
        component.prediction.verdict
        if component.prediction
        else ScreeningVerdict.PASS
    )

    review_record = InspectorReview(
        component_id=component.id,
        inspector_id=payload.inspector_id,
        original_verdict=original_verdict,
        disposition=payload.disposition,
        inspector_notes=payload.inspector_notes,
    )

    db.add(review_record)
    await db.commit()
    await db.refresh(review_record)

    return ReviewActionResponse(
        review_id=review_record.id,
        component_id=component.id,
        inspector_id=review_record.inspector_id,
        original_verdict=original_verdict.value if hasattr(original_verdict, "value") else str(original_verdict),
        disposition=review_record.disposition.value if hasattr(review_record.disposition, "value") else str(review_record.disposition),
        inspector_notes=review_record.inspector_notes,
        reviewed_at=review_record.reviewed_at,
        status="SUCCESS",
    )
