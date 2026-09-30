"""
Persistence helpers shared by the batch pipeline (ml_engine/run_screening.py) and CSV ingest:
converting ScreeningModel outputs into ModelPrediction rows, screening a single (new) lot with the
persisted model artifact, and writing audit events.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.models import AuditEvent, BurnInReading, Component, ModelPrediction
from ml_engine.features import PARAMETERS
from ml_engine.screening import ScreeningModel, early_readings_only, prediction_details

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def artifact_path() -> Path:
    from backend.app.core.config import settings

    p = Path(settings.MODEL_ARTIFACT_PATH)
    return p if p.is_absolute() else PROJECT_ROOT / p

INSUFFICIENT_REASON = (
    "INSUFFICIENT_DATA: a 0h/24h reading was missing or invalid at ingest (imputed for display only); "
    "no Module A/B score was computed. Sent to REVIEW for re-test or manual assessment."
)


def _finite(x) -> Optional[float]:
    if x is None or pd.isna(x):
        return None
    x = float(x)
    return None if x in (float("inf"), float("-inf")) else x


def prediction_record(row: pd.Series, run_id=None, cv_fold: Optional[int] = None) -> Dict[str, Any]:
    return {
        "component_id": uuid.UUID(str(row["component_id"])),
        "module_a_score": float(row["module_a_score"]),
        "module_a_mahalanobis": float(row["module_a_mahalanobis"]),
        "module_a_flag": bool(row["module_a_flag"]),
        "pred_leakage_168h": float(row["pred_leakage_168h"]),
        "pred_iddq_168h": float(row["pred_iddq_168h"]),
        "pred_delay_168h": float(row["pred_delay_168h"]),
        "drift_slope_ua_per_hr": float(row["drift_slope_ua_per_hr"]),
        "module_b_flag": bool(row["module_b_flag"]),
        "module_b_score": _finite(row["module_b_score"]),
        "threshold_a": _finite(row["threshold_a"]),
        "threshold_b": _finite(row["threshold_b"]),
        "safety_slope_ua_per_hr": _finite(row.get("safety_slope_leakage_current_ua")),
        "details": prediction_details(row),
        "verdict": row["verdict"],
        "verdict_reason": row["verdict_reason"],
        "run_id": run_id,
        "cv_fold": cv_fold,
    }


def insufficient_record(component_id: uuid.UUID, run_id=None) -> Dict[str, Any]:
    return {
        "component_id": component_id,
        "module_a_flag": False,
        "module_b_flag": False,
        "verdict": "REVIEW",
        "verdict_reason": INSUFFICIENT_REASON,
        "details": {"insufficient_data": True},
        "run_id": run_id,
        "cv_fold": None,
    }


def write_predictions(session: Session, records: List[Dict[str, Any]], batch_size: int = 1000) -> int:
    for i in range(0, len(records), batch_size):
        session.execute(insert(ModelPrediction), records[i: i + batch_size])
    return len(records)


def audit(session: Session, category: str, actor: str, action: str, details: str,
          lot_id=None, component_id=None, payload: Optional[Dict[str, Any]] = None) -> None:
    session.add(AuditEvent(category=category, actor=actor, action=action, details=details,
                           lot_id=lot_id, component_id=component_id, payload=payload))


def load_model(path: Path | None = None) -> ScreeningModel:
    path = path or artifact_path()
    if not Path(path).exists():
        raise FileNotFoundError(f"No trained model artifact at {path}. Run `python ml_engine/run_screening.py` first.")
    return ScreeningModel.load(path)


def screen_lot(session: Session, lot_id: uuid.UUID, model: Optional[ScreeningModel] = None) -> Dict[str, Any]:
    """Screens one lot with the persisted production model (thresholds, calibration and floors included)."""
    model = model or load_model()
    comps = session.scalars(select(Component).where(Component.lot_id == lot_id)).all()
    ok_ids = [c.id for c in comps if not c.insufficient_data]
    bad_ids = [c.id for c in comps if c.insufficient_data]
    session.execute(delete(ModelPrediction).where(ModelPrediction.component_id.in_([c.id for c in comps])))

    records: List[Dict[str, Any]] = []
    if ok_ids:
        rows = session.execute(
            select(BurnInReading.component_id, BurnInReading.interval_hours,
                   *[getattr(BurnInReading, p) for p in PARAMETERS])
            .where(BurnInReading.component_id.in_(ok_ids), BurnInReading.interval_hours.in_([0, 24]))
        ).all()
        df = pd.DataFrame([r._asdict() for r in rows])
        df["component_id"] = df["component_id"].astype(str)
        df["lot_id"] = str(lot_id)
        preds = model.predict(early_readings_only(df))
        records += [prediction_record(r) for _, r in preds.iterrows()]
    records += [insufficient_record(cid) for cid in bad_ids]
    write_predictions(session, records)
    verdicts = pd.Series([r["verdict"] for r in records]).value_counts().to_dict() if records else {}
    return {"n_screened": len(records), "n_insufficient_data": len(bad_ids), "verdicts": verdicts,
            "thresholds": {"threshold_a": _finite(model.thresholds_["threshold_a"]),
                           "threshold_b": _finite(model.thresholds_["threshold_b"])}}
