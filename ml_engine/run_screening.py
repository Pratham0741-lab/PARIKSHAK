"""
ISRO SIH26170 screening pipeline over the PostgreSQL database.

Every persisted prediction is OUT-OF-FOLD: lots are split with GroupKFold, each fold's model is
trained on the other lots only, and the held-out lots are predicted from their 0h/24h readings
with labels and 96h/168h readings removed. Metrics printed (and served by /metrics) are
therefore held-out metrics. `--report-train` additionally prints in-sample metrics, clearly
labelled TRAIN (optimistic).
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402
from sqlalchemy import delete, insert, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.core.database import SessionLocal  # noqa: E402
from backend.app.models import BurnInReading, Component, Lot, ModelPrediction  # noqa: E402
from evaluation.crossfit import cross_fit_predict, extract_truth  # noqa: E402
from evaluation.score import score  # noqa: E402
from ml_engine.screening import ScreeningModel, early_readings_only  # noqa: E402

console = Console(highlight=False)


def fetch_screening_data(session: Session) -> pd.DataFrame:
    """Lots, components and time-series readings from PostgreSQL (long format)."""
    query = (
        select(
            Component.id.label("component_id"),
            Component.lot_id,
            Component.serial_number,
            Component.ground_truth_label,
            Component.ground_truth_flag,
            Lot.lot_number,
            BurnInReading.interval_hours,
            BurnInReading.leakage_current_ua,
            BurnInReading.iddq_ma,
            BurnInReading.propagation_delay_ns,
        )
        .join(Lot, Component.lot_id == Lot.id)
        .join(BurnInReading, Component.id == BurnInReading.component_id)
        .order_by(Component.id, BurnInReading.interval_hours)
    )
    rows = session.execute(query).fetchall()
    if not rows:
        raise ValueError("No burn-in records found in database. Run data_engine/seed_db.py first.")
    df = pd.DataFrame([r._asdict() for r in rows])
    df["ground_truth_label"] = df["ground_truth_label"].apply(lambda x: getattr(x, "value", x))
    df["component_id"] = df["component_id"].astype(str)
    df["lot_id"] = df["lot_id"].astype(str)
    return df


def persist_predictions(session: Session, preds: pd.DataFrame, batch_size: int = 2000) -> int:
    session.execute(delete(ModelPrediction))
    session.flush()
    rows: List[Dict[str, Any]] = [
        {
            "component_id": uuid.UUID(str(r.component_id)),
            "module_a_score": float(r.module_a_score),
            "module_a_mahalanobis": float(r.module_a_mahalanobis),
            "module_a_flag": bool(r.module_a_flag),
            "pred_leakage_168h": float(r.pred_leakage_168h),
            "pred_iddq_168h": float(r.pred_iddq_168h),
            "pred_delay_168h": float(r.pred_delay_168h),
            "drift_slope_ua_per_hr": float(r.drift_slope_ua_per_hr),
            "module_b_flag": bool(r.module_b_flag),
            "verdict": r.verdict,
            "verdict_reason": r.verdict_reason,
            "cv_fold": None if pd.isna(r.cv_fold) else int(r.cv_fold),
        }
        for r in preds.itertuples(index=False)
    ]
    for i in range(0, len(rows), batch_size):
        session.execute(insert(ModelPrediction), rows[i : i + batch_size])
    session.commit()
    return len(rows)


def print_metrics(title: str, res: Dict[str, Any]) -> None:
    d = res["detection"]
    t = Table(title=title, show_header=True)
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    for k in ("recall", "precision", "f1", "false_negative_rate"):
        t.add_row(k, f"{100 * d[k]:.2f}%")
    for k in ("tp", "fn", "fp", "tn"):
        t.add_row(k.upper(), str(d[k]))
    for p, e in res["regression"].items():
        t.add_row(f"MAE {p}", f"{e['model']['mae']:.4f} (linear {e['linear_baseline']['mae']:.4f})"
                  if "linear_baseline" in e else f"{e['model']['mae']:.4f}")
    console.print(t)


def run_pipeline(n_splits: int = 5, persist: bool = True, report_train: bool = False) -> Dict[str, Any]:
    start = time.perf_counter()
    seed = settings.SYNTHETIC_RANDOM_SEED
    with SessionLocal() as session:
        df = fetch_screening_data(session)
        console.print(f"Loaded {df['component_id'].nunique():,} components across {df['lot_id'].nunique()} lots.")

        cf = cross_fit_predict(df, lambda: ScreeningModel(random_state=seed), n_splits=n_splits, seed=seed)
        truth = extract_truth(df)
        held_out = score(cf.predictions, truth)
        print_metrics(f"HELD-OUT (out-of-fold, GroupKFold over lots, k={n_splits})", held_out)

        result: Dict[str, Any] = {"held_out": held_out, "predictions": cf.predictions}
        if report_train:
            model = ScreeningModel(random_state=seed).fit(df)
            train_preds = model.predict(early_readings_only(df))
            result["train_optimistic"] = score(train_preds, truth)
            print_metrics("TRAIN (optimistic, in-sample - NOT a performance estimate)", result["train_optimistic"])

        if persist:
            n = persist_predictions(session, cf.predictions)
            console.print(f"Persisted {n:,} out-of-fold predictions.")

    result["elapsed_seconds"] = round(time.perf_counter() - start, 2)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--folds", type=int, default=5, help="number of lot-level folds (default 5)")
    ap.add_argument("--no-persist", action="store_true", help="do not write predictions to the database")
    ap.add_argument("--report-train", action="store_true", help="also print TRAIN (optimistic) in-sample metrics")
    args = ap.parse_args()
    try:
        run_pipeline(n_splits=args.folds, persist=not args.no_persist, report_train=args.report_train)
    except Exception as exc:
        console.print(f"[bold red]Pipeline error: {exc}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
