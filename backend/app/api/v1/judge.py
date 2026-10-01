"""
Judge mode (ml_engine/judge.py): train on an uploaded file that includes 168h readings, predict from
0h/24h-only files, export the prediction CSV and score it against a ground-truth file.

The /score endpoint and `python -m evaluation.score --predictions preds.csv --truth truth.csv` call
the same function (evaluation.score.score_judge_files) on the same bytes, so they give identical numbers.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from backend.app.core.config import settings
from backend.app.services.screening_service import artifact_path
from data_engine.tabular import TableError, read_table
from evaluation.cost import CostConfig
from evaluation.rules import RULE_ID, RULE_TEXT
from ml_engine import judge

router = APIRouter(prefix="/judge", tags=["Judge mode"])

_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
_ACTIVE: Dict[str, Any] = {"model": None, "loaded_from": None}


def clean(o: Any) -> Any:
    """JSON-safe copy: NaN/inf -> None, numpy scalars -> Python."""
    import math

    import numpy as np

    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [clean(v) for v in o]
    if isinstance(o, np.generic):
        o = o.item()
    if isinstance(o, float) and not math.isfinite(o):
        return None
    return o


def pretrained_for(params):
    """The production pipeline for these parameters (Module B for small files), or None if there is none yet."""
    from backend.app.services.screening_service import model_for_parameters

    try:
        return model_for_parameters(params)
    except (FileNotFoundError, ValueError):
        return None


def judge_dir() -> Path:
    return artifact_path().parent / "judge"


def models_dir() -> Path:
    from backend.app.services.screening_service import PROJECT_ROOT

    p = Path(settings.MODELS_DIR)
    return p if p.is_absolute() else PROJECT_ROOT / p


def active_model() -> Optional[judge.JudgeModel]:
    meta = models_dir() / "latest.pkl"
    stamp = meta.stat().st_mtime if meta.exists() else None
    if _ACTIVE["model"] is None or _ACTIVE["loaded_from"] != stamp:
        _ACTIVE["model"] = judge.JudgeModel.load_active(models_dir())
        _ACTIVE["loaded_from"] = stamp
    return _ACTIVE["model"]


class FileRequest(BaseModel):
    csv: str = Field(..., min_length=1, description="CSV text (wide or long; see data_engine/tabular.py)")
    filename: str = Field("(pasted CSV)", max_length=255)
    static_limit: Optional[float] = Field(None, gt=0, description="static limit for the primary parameter")


class ScoreRequest(BaseModel):
    truth_csv: str = Field(..., min_length=1, description="ground-truth file with 168h readings (labels optional)")
    truth_filename: str = Field("(pasted truth CSV)", max_length=255)
    predictions_csv: Optional[str] = Field(None, description="exported predictions; default: the last /predict export")


def _parse(text: str):
    try:
        return read_table(text)
    except (TableError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _run_training(job_id: str, text: str, filename: str, static_limit: Optional[float]) -> None:
    job = _JOBS[job_id]

    def progress(msg: str) -> None:
        job["message"] = msg

    try:
        table = read_table(text)
        jm, oof_export, _ = judge.train(table, filename, CostConfig.from_settings(), static_limit=static_limit,
                                        progress=progress, pretrained=pretrained_for(table.params),
                                        max_flag_rate=settings.JUDGE_MAX_FLAG_RATE)
        with _LOCK:
            jm.save(models_dir())
            judge_dir().mkdir(parents=True, exist_ok=True)
            oof_export.to_csv(judge_dir() / "train_oof_predictions.csv", index=False)
        job.update(state="done", message="trained", model=jm.info)
    except Exception as exc:  # reported to the UI, not swallowed
        job.update(state="failed", message=f"{type(exc).__name__}: {exc}")
    job["finished_at"] = datetime.now(UTC).isoformat()


@router.post("/train", status_code=status.HTTP_202_ACCEPTED,
             summary="Train on an uploaded file with 168h readings (labels optional); runs in the background")
async def train(req: FileRequest) -> Dict[str, Any]:
    table = await run_in_threadpool(_parse, req.csv)
    if not table.has_168h:
        raise HTTPException(status_code=422, detail="training needs 168h readings")
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"id": job_id, "state": "running", "message": "queued", "file": req.filename,
                     "started_at": datetime.now(UTC).isoformat(), "validation": table.summary()}
    threading.Thread(target=_run_training, args=(job_id, req.csv, req.filename, req.static_limit), daemon=True).start()
    return clean(_JOBS[job_id])


@router.get("/jobs/{job_id}", summary="Training job status")
async def job(job_id: str) -> Dict[str, Any]:
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail="unknown job")
    return clean(_JOBS[job_id])


@router.get("/model", summary="The active judge-mode model (what it was trained on) and the defect rule")
async def model_info() -> Dict[str, Any]:
    jm = await run_in_threadpool(active_model)
    return clean({"model": None if jm is None else jm.info, "rule": {"id": RULE_ID, "text": RULE_TEXT},
            "export_columns": judge.EXPORT_COLUMNS})


def _predict_sync(req: FileRequest) -> Dict[str, Any]:
    jm = active_model()
    if jm is None:
        raise HTTPException(status_code=409, detail="no judge-mode model yet: POST /judge/train first")
    table = _parse(req.csv)
    try:
        export, rows = judge.predict(jm, table, static_limit=req.static_limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    csv_text = export.to_csv(index=False)
    meta = {"file": req.filename, "sha256": table.sha256, "n_parts": table.n_parts, "n_lots": table.n_lots,
            "parameters": table.params, "ignored_intervals": sorted({96, 168} & set(table.df["interval_hours"])),
            "model_sha256": jm.info["data_sha256"], "predicted_at": datetime.now(UTC).isoformat()}
    with _LOCK:
        d = judge_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "last_predictions.csv").write_text(csv_text, encoding="utf-8")
        import json

        (d / "last_predictions.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return clean({"input": meta, "validation": table.summary(), "model": jm.info, "rows": rows,
                  "flagged": int(export["Flag"].sum()), "export_sha256": hashlib.sha256(csv_text.encode()).hexdigest()})


@router.post("/predict", summary="Predict 168h, intervals, flags and explanations from 0h/24h readings")
async def predict(req: FileRequest) -> Dict[str, Any]:
    return await run_in_threadpool(_predict_sync, req)


@router.get("/predictions.csv", response_class=PlainTextResponse, summary="The last /predict export as CSV")
async def export_csv() -> PlainTextResponse:
    path = judge_dir() / "last_predictions.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no predictions yet")
    return PlainTextResponse(path.read_text(encoding="utf-8"), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="preds.csv"'})


def _score_sync(req: ScoreRequest) -> Dict[str, Any]:
    from evaluation.score import score_judge_files

    preds = req.predictions_csv
    if preds is None:
        path = judge_dir() / "last_predictions.csv"
        if not path.exists():
            raise HTTPException(status_code=409, detail="no predictions to score: run /judge/predict first")
        preds = path.read_text(encoding="utf-8")
    jm = active_model()
    parameter = jm.info["primary_parameter"] if jm else None
    limit = jm.info.get("static_limit_override") if jm else None
    cost = CostConfig.from_settings()
    try:
        res = score_judge_files(preds, req.truth_csv, cost, parameter, limit)
    except (TableError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cmd = (f"python -m evaluation.score --predictions preds.csv --truth {req.truth_filename}"
           + (f" --parameter {parameter}" if parameter else "") + (f" --static-limit {limit:g}" if limit else "")
           + f" --fn-cost {cost.fn_cost:g} --fp-cost {cost.fp_cost:g}")
    res["reproduce_with"] = cmd
    res["predictions_sha256"] = hashlib.sha256(preds.encode()).hexdigest()
    return clean(res)


@router.post("/score", summary="Score the exported predictions against a ground-truth file")
async def score(req: ScoreRequest) -> Dict[str, Any]:
    return await run_in_threadpool(_score_sync, req)
