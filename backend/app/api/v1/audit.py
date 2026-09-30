"""Audit log API (append-only events: ingest, screening runs, inspector decisions)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.database import get_async_db
from backend.app.models import AuditEvent

router = APIRouter(prefix="/audit", tags=["Audit"])


class AuditEventItem(BaseModel):
    id: uuid.UUID
    created_at: datetime
    category: str
    actor: str
    action: str
    details: str
    lot_id: Optional[uuid.UUID] = None
    component_id: Optional[uuid.UUID] = None
    payload: Optional[Dict[str, Any]] = None


@router.get("", response_model=List[AuditEventItem], summary="Audit events, newest first")
async def list_audit_events(
    lot_id: Optional[uuid.UUID] = Query(None, description="Only events for this lot (plus global events)"),
    limit: int = Query(200, ge=1, le=2000),
    db: AsyncSession = Depends(get_async_db),
) -> List[AuditEventItem]:
    stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
    if lot_id:
        stmt = stmt.where(or_(AuditEvent.lot_id == lot_id, AuditEvent.lot_id.is_(None)))
    rows = (await db.execute(stmt)).scalars().all()
    return [AuditEventItem.model_validate(r, from_attributes=True) for r in rows]
