"""
CSV ingest endpoint: validates a new lot's readings, stores them (with imputation flags, never
zero-filled), and screens the lot through Modules A and B with the persisted production model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select
from starlette.concurrency import run_in_threadpool

from backend.app.core.database import SessionLocal
from backend.app.models import BurnInReading, Component, Lot, LotStatus
from backend.app.services.ingest import PARAMETERS, parse_csv
from backend.app.services.screening_service import audit, model_for_parameters, screen_lot
from data_engine.tabular import TO_CANONICAL
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
    static_limit: Optional[float] = Field(None, gt=0, description="in the file's unit for the monitored parameter")
    units: Optional[Dict[str, str]] = Field(None, description="unit overrides, e.g. {'leakage': 'nA'}")
    supplier: Optional[str] = Field(None, max_length=128, description="Supplier (optional; else a `supplier` CSV column)")
    units_confirmed: bool = Field(False, description="the user has confirmed the detected units")


class IngestResponse(BaseModel):
    lot_id: Optional[uuid.UUID]
    lot_number: Optional[str]
    validation: Dict[str, Any]
    screening: Optional[Dict[str, Any]] = None


def _ingest_sync(req: IngestRequest, parsed=None) -> IngestResponse:
    parsed = parsed or parse_csv(req.csv, req.test_parameter, req.units)
    if not parsed.ok or not parsed.parts:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=parsed.summary())
    if parsed.needs_unit_confirmation and not req.units_confirmed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "message": "confirm the detected units (converted or implausible) and resubmit with units_confirmed=true",
            "units": parsed.units})
    supplied = {**parsed.conditions, **{k: getattr(req, k) for k in ("temperature_c", "test_parameter", "unit",
                                                                   "static_limit") if getattr(req, k) is not None}}
    if len(parsed.parameters_used) == 1 and not supplied.get("test_parameter"):
        supplied["test_parameter"] = parsed.parameters_used[0]  # a single-parameter file monitors that parameter
    try:
        conditions, assumed = resolve_conditions({k: v for k, v in supplied.items() if k != "unit"})
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    # Readings are stored in canonical units, so the lot's unit is canonical. A static limit given in the
    # file's unit is converted by the same factor as the readings.
    p = conditions["test_parameter"]
    file_units = list(parsed.units.get(p, {}).get("detected", {}))
    if len(file_units) == 1 and supplied.get("static_limit") is not None:
        conditions["static_limit"] = float(supplied["static_limit"]) * TO_CANONICAL[p][file_units[0]]
    if supplied.get("unit") and "unit" in assumed:
        assumed.remove("unit")
    source_units = {q: sorted(u["detected"]) for q, u in parsed.units.items()}
    model = model_for_parameters(parsed.parameters_used)  # fail before writing anything if there is no model
    limits = ScreeningVerdictEngine.datasheet_limits()
    lot_number = req.lot_number or f"INGEST-{datetime.now(UTC):%Y%m%d-%H%M%S}"

    with SessionLocal() as session:
        if session.scalar(select(Lot.id).where(Lot.lot_number == lot_number)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Lot {lot_number} already exists")
        lot = Lot(lot_number=lot_number, wafer_id=req.wafer_id, status=LotStatus.INGESTED, source="CSV_INGEST",
                  **conditions, conditions_assumed=assumed, supplier=req.supplier or parsed.conditions.get("supplier"),
                  source_detail={"kind": "UPLOADED", "file": req.filename or "(pasted CSV)",
                                 "sha256": parsed.sha256, "rows": parsed.rows_total, "layout": parsed.layout,
                                 "units_in_file": source_units, "units_confirmed": req.units_confirmed,
                                 "parameters_used": parsed.parameters_used})
        session.add(lot)
        session.flush()

        readings, comps = [], []
        for pp in parsed.parts:
            observed_breach = any(
                v is not None and q not in pp.imputed.get(h, []) and v > limits[q]
                for h, vals in pp.values.items() for q, v in vals.items()
            )
            cid = uuid.uuid4()
            comps.append({"id": cid, "lot_id": lot.id, "serial_number": pp.part_id, "ground_truth_label": None,
                          "ground_truth_flag": None, "is_datasheet_breached": observed_breach,
                          "insufficient_data": pp.insufficient_data})
            for h, vals in pp.values.items():
                if all(vals[q] is None for q in PARAMETERS) or any(vals[q] is None for q in parsed.parameters_used):
                    continue  # whole optional interval absent
                readings.append({"id": uuid.uuid4(), "component_id": cid, "interval_hours": h,
                                 **{q: vals[q] for q in PARAMETERS},
                                 "imputed_fields": pp.imputed.get(h) or None})
        for i in range(0, len(comps), 2000):  # bulk insert (10k+ part files)
            session.execute(insert(Component), comps[i: i + 2000])
        for i in range(0, len(readings), 5000):
            session.execute(insert(BurnInReading), readings[i: i + 5000])
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
    return (await run_in_threadpool(parse_csv, req.csv, req.test_parameter, req.units)).summary()


@router.post("/stream", response_model=IngestResponse, status_code=status.HTTP_201_CREATED,
             summary="Ingest a large CSV sent as the raw request body (text/csv), parsed as a stream")
async def ingest_stream(
    request: Request,
    filename: str = Query("(streamed CSV)", max_length=255),
    lot_number: Optional[str] = Query(None, max_length=64),
    test_parameter: Optional[str] = Query(None),
    units_confirmed: bool = Query(False),
    validate_only: bool = Query(False),
    actor: str = Query("QA Inspector", max_length=64),
) -> Any:
    import io
    import tempfile

    spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)  # spills to disk above 8 MB
    async for chunk in request.stream():
        spool.write(chunk)
    spool.seek(0)
    text = io.TextIOWrapper(spool, encoding="utf-8-sig", newline="")
    parsed = await run_in_threadpool(parse_csv, text, test_parameter, None)
    spool.close()
    if validate_only:
        return IngestResponse(lot_id=None, lot_number=None, validation=parsed.summary())
    req = IngestRequest(csv="(streamed)", filename=filename, lot_number=lot_number, test_parameter=test_parameter,
                        units_confirmed=units_confirmed, actor=actor)
    try:
        return await run_in_threadpool(_ingest_sync, req, parsed)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
