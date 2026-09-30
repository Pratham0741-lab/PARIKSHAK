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
from typing import Any, Dict

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
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.core.database import SessionLocal  # noqa: E402
from backend.app.models import BurnInReading, Component, Lot, ModelPrediction, ScreeningRun  # noqa: E402
from backend.app.services.screening_service import (  # noqa: E402
    artifact_path,
    audit,
    prediction_record,
    write_predictions,
)
from evaluation.cost import CostConfig  # noqa: E402
from evaluation.crossfit import cross_fit_predict, extract_truth  # noqa: E402
from evaluation.score import score  # noqa: E402
from ml_engine.screening import ScreeningModel, early_readings_only  # noqa: E402

console = Console(highlight=False)

PROTOCOL = (
    "Out-of-fold: GroupKFold over lots; each fold's model is trained on the other lots with thresholds "
    "chosen by FN-weighted cost minimisation on an inner lot-grouped CV of those training lots; held-out "
    "lots are predicted from 0h/24h readings only."
)


def _finite(x):
    """JSON/DB-safe threshold: +inf (module disabled) is stored as NULL."""
    x = float(x)
    return None if x == float("inf") else x


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float) and obj in (float("inf"), float("-inf")):
        return None
    return obj


def fetch_screening_data(session: Session) -> pd.DataFrame:
    """Labelled lots, components and time-series readings from PostgreSQL (long format)."""
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
        # Only labelled lots can be used for training and held-out evaluation.
        .where(Component.ground_truth_flag.is_not(None))
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


def persist_predictions(session: Session, preds: pd.DataFrame, run_id=None) -> int:
    """Replaces the predictions of the LABELLED lots only; ingested (unlabelled) lots keep theirs."""
    ids = [uuid.UUID(str(c)) for c in preds["component_id"]]
    session.execute(delete(ModelPrediction).where(ModelPrediction.component_id.in_(ids)))
    session.flush()
    records = [
        prediction_record(row, run_id=run_id, cv_fold=None if pd.isna(row["cv_fold"]) else int(row["cv_fold"]))
        for _, row in preds.iterrows()
    ]
    write_predictions(session, records)
    session.commit()
    return len(records)


def print_metrics(title: str, res: Dict[str, Any]) -> None:
    d = res["detection"]
    t = Table(title=title, show_header=True)
    t.add_column("Metric")
    t.add_column("Value", justify="right")
    for k in ("recall", "precision", "f2", "f1", "false_negative_rate"):
        t.add_row(k, f"{100 * d[k]:.2f}%")
    t.add_row("weighted cost", f"{d['weighted_cost']:.1f} (per 1000 parts: {d['cost_per_1000_parts']:.1f})")
    for k in ("tp", "fn", "fp", "tn"):
        t.add_row(k.upper(), str(d[k]))
    for p, e in res["regression"].items():
        t.add_row(f"MAE {p}", f"{e['model']['mae']:.4f} (linear {e['linear_baseline']['mae']:.4f})"
                  if "linear_baseline" in e else f"{e['model']['mae']:.4f}")
    console.print(t)


def run_pipeline(
    n_splits: int = 5, persist: bool = True, report_train: bool = False, cost: CostConfig | None = None
) -> Dict[str, Any]:
    start = time.perf_counter()
    seed = settings.SYNTHETIC_RANDOM_SEED
    cost = cost or CostConfig.from_settings()

    def factory():
        return ScreeningModel(cost=cost, random_state=seed)

    with SessionLocal() as session:
        df = fetch_screening_data(session)
        console.print(f"Loaded {df['component_id'].nunique():,} components across {df['lot_id'].nunique()} lots.")
        console.print(f"Decision cost: FN={cost.fn_cost:g}, FP={cost.fp_cost:g}, recall target={cost.recall_target}")

        cf = cross_fit_predict(df, factory, n_splits=n_splits, seed=seed)
        truth = extract_truth(df)
        held_out = score(cf.predictions, truth, cost)
        print_metrics(f"HELD-OUT (out-of-fold, GroupKFold over lots, k={n_splits})", held_out)

        # Final model on every labelled lot: its thresholds (chosen on inner OOF) are persisted
        # with the artifact and used for lots screened later (e.g. CSV ingest).
        final = factory().fit(df)
        artifact = artifact_path()
        final.save(artifact)
        console.print(f"Saved model + thresholds to {artifact} "
                      f"(A={final.thresholds_['threshold_a']:.4f}, B={final.thresholds_['threshold_b']:.4f})")

        result: Dict[str, Any] = {"held_out": held_out, "predictions": cf.predictions, "final_model": final}
        if report_train:
            train_preds = final.predict(early_readings_only(df))
            result["train_optimistic"] = score(train_preds, truth, cost)
            print_metrics("TRAIN (optimistic, in-sample - NOT a performance estimate)", result["train_optimistic"])

        if persist:
            run = ScreeningRun(
                protocol=PROTOCOL,
                cost_config=cost.as_dict(),
                final_thresholds=_jsonable(final.thresholds_),
                fold_thresholds=_jsonable({str(k): m.thresholds_ for k, m in cf.models.items()}),
                held_out_metrics=_jsonable(held_out),
                artifact_path=str(artifact),
            )
            session.add(run)
            session.flush()
            n = persist_predictions(session, cf.predictions, run_id=run.id)
            result["run_id"] = run.id
            d = held_out["detection"]
            audit(session, "MODEL", "screening-pipeline", "Screening run",
                  f"{n} out-of-fold predictions over {df['lot_id'].nunique()} labelled lots; held-out recall "
                  f"{d['recall']:.3f}, precision {d['precision']:.3f}, weighted cost {d['weighted_cost']:g}",
                  payload={"run_id": str(run.id), "thresholds": _jsonable(final.thresholds_)})
            session.commit()
            console.print(f"Persisted {n:,} out-of-fold predictions (run {run.id}).")

    result["elapsed_seconds"] = round(time.perf_counter() - start, 2)
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--folds", type=int, default=5, help="number of lot-level folds (default 5)")
    ap.add_argument("--no-persist", action="store_true", help="do not write predictions to the database")
    ap.add_argument("--report-train", action="store_true", help="also print TRAIN (optimistic) in-sample metrics")
    ap.add_argument("--fn-cost", type=float, default=None, help="cost of a missed defect (default: settings.FN_COST=20)")
    ap.add_argument("--fp-cost", type=float, default=None, help="cost of a false alarm (default: settings.FP_COST=1)")
    ap.add_argument("--recall-target", type=float, default=None, help="optional recall constraint for threshold choice")
    args = ap.parse_args()
    cost = CostConfig.from_settings(fn_cost=args.fn_cost, fp_cost=args.fp_cost, recall_target=args.recall_target)
    try:
        run_pipeline(n_splits=args.folds, persist=not args.no_persist, report_train=args.report_train, cost=cost)
    except Exception as exc:
        console.print(f"[bold red]Pipeline error: {exc}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
