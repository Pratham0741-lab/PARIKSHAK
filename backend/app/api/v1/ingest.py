"""
CSV ingest endpoint: validates a new lot's readings, stores them (with imputation flags, never
zero-filled), and screens the lot through Modules A and B with the persisted production model.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select
from starlette.concurrency import run_in_threadpool

from backend.app.core.database import SessionLocal
from backend.app.models import BurnInReading, Component, Lot, LotStatus
from backend.app.services.ingest import PARAMETERS, parse_csv
from backend.app.services.screening_service import audit, load_model, screen_lot
from ml_engine.conditions import resolve_conditions
from ml_engine.verdict_engine import ScreeningVerdictEngine

router = APIRouter(prefix="/ingest", tags=["Ingest"])


class IngestRequest(BaseModel):
    csv: str = Field(..., min_length=1, description="CSV text (see backend/app/services/ingest.py for the format)")
    lot_number: Optional[str] = Field(None, max_length=64, description="Lot number; generated if omitted")
    wafer_id: Optional[str] = Field(None, max_length=64)
    actor: str = Field("QA Inspector", max_length=64, description="Who performed the ingest (audit log)")
    filename: Optional[str] = Field(None, max_length=255, description="Uploaded file name (provenance)")
    # Burn-in test conditions; these override lot-level CSV columns. Missing values are defaulted
    # (ml_engine/conditions.py) and recorded as assumed.
    temperature_c: Optional[float] = Field(None, ge=-60, le=300)
    test_parameter: Optional[str] = Field(None, description="leakage | iddq | delay")
    unit: Optional[str] = Field(None, max_length=16)
    static_limit: Optional[float] = Field(None, gt=0)


class IngestResponse(BaseModel):
    lot_id: Optional[uuid.UUID]
    lot_number: Optional[str]
    validation: Dict[str, Any]
    screening: Optional[Dict[str, Any]] = None


def _ingest_sync(req: IngestRequest) -> IngestResponse:
    parsed = parse_csv(req.csv)
    if not parsed.ok or not parsed.parts:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=parsed.summary())
    supplied = {**parsed.conditions, **{k: getattr(req, k) for k in ("temperature_c", "test_parameter", "unit",
                                                                   "static_limit") if getattr(req, k) is not None}}
    try:
        conditions, assumed = resolve_conditions(supplied)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    model = load_model()  # fail before writing anything if there is no trained model
    limits = ScreeningVerdictEngine.datasheet_limits()
    lot_number = req.lot_number or f"INGEST-{datetime.now(UTC):%Y%m%d-%H%M%S}"

    with SessionLocal() as session:
        if session.scalar(select(Lot.id).where(Lot.lot_number == lot_number)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Lot {lot_number} already exists")
        lot = Lot(lot_number=lot_number, wafer_id=req.wafer_id, status=LotStatus.INGESTED, source="CSV_INGEST",
                  **conditions, conditions_assumed=assumed,
                  source_detail={"kind": "UPLOADED", "file": req.filename or "(pasted CSV)",
                                 "sha256": hashlib.sha256(req.csv.encode()).hexdigest(),
                                 "rows": parsed.rows_total})
        session.add(lot)
        session.flush()

        readings = []
        for pp in parsed.parts:
            observed_breach = any(
                v is not None and p not in pp.imputed.get(h, []) and v > limits[p]
                for h, vals in pp.values.items() for p, v in vals.items()
            )
            comp = Component(lot_id=lot.id, serial_number=pp.part_id, ground_truth_label=None,
                             ground_truth_flag=None, is_datasheet_breached=observed_breach,
                             insufficient_data=pp.insufficient_data)
            session.add(comp)
            session.flush()
            for h, vals in pp.values.items():
                if any(vals[p] is None for p in PARAMETERS):
                    continue  # whole optional interval absent
                readings.append({"id": uuid.uuid4(), "component_id": comp.id, "interval_hours": h,
                                 **{p: vals[p] for p in PARAMETERS},
                                 "imputed_fields": pp.imputed.get(h) or None})
        if readings:
            session.execute(insert(BurnInReading), readings)
        summary = parsed.summary()
        summary["conditions"] = conditions
        summary["conditions_assumed"] = assumed
        audit(session, "INGEST", req.actor, "Lot ingested",
              f"{lot_number}: {summary['parts_accepted']} parts accepted, {summary['rows_rejected']} rows rejected, "
              f"{summary['imputed_cells']} cells imputed, {summary['insufficient_data_parts']} parts with insufficient data",
              lot_id=lot.id, payload={k: v for k, v in summary.items() if k != "issues"})

        screening = screen_lot(session, lot.id, model)
        lot.status = LotStatus.SCREENED
        audit(session, "MODEL", "screening-pipeline", "Lot screened",
              f"{lot_number}: {screening['n_screened']} parts screened with the production model "
              f"(verdicts {screening['verdicts']})", lot_id=lot.id, payload=screening)
        session.commit()
        return IngestResponse(lot_id=lot.id, lot_number=lot_number, validation=summary, screening=screening)


@router.post("", response_model=IngestResponse, status_code=status.HTTP_201_CREATED,
             summary="Validate, store and screen a new lot from CSV")
async def ingest_csv(req: IngestRequest) -> IngestResponse:
    try:
        return await run_in_threadpool(_ingest_sync, req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/validate", summary="Validate a CSV without storing anything")
async def validate_csv(req: IngestRequest) -> Dict[str, Any]:
    return parse_csv(req.csv).summary()
