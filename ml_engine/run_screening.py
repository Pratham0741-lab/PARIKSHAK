"""
ISRO SIH26170 Screening Pipeline & Benchmark Runner.
Executes Module A (Lot Outlier Detector), Module B (Early Drift Predictor),
and the Unified Verdict Layer against PostgreSQL database records.
Persists ModelPrediction results and outputs comprehensive Rich benchmark tables.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

# Reconfigure stdout/stderr for UTF-8 on Windows
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal
from backend.app.models import BurnInReading, Component, Lot, ModelPrediction, ScreeningVerdict
from ml_engine.module_a_outlier import LotOutlierDetector
from ml_engine.module_b_drift import DriftPredictor
from ml_engine.verdict_engine import ScreeningVerdictEngine

console = Console(highlight=False)


def fetch_screening_data(session: Session) -> pd.DataFrame:
    """Queries lots, components, and time-series readings from PostgreSQL."""
    query = (
        select(
            Component.id.label("component_id"),
            Component.lot_id,
            Component.serial_number,
            Component.ground_truth_label,
            Component.ground_truth_flag,
            Component.is_datasheet_breached,
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
    result = session.execute(query).fetchall()
    if not result:
        raise ValueError("No burn-in screening records found in database. Run seed_db.py first.")

    df = pd.DataFrame([r._asdict() for r in result])
    # Convert Enum objects to string representation if needed
    df["ground_truth_label"] = df["ground_truth_label"].apply(
        lambda x: x.value if hasattr(x, "value") else str(x)
    )
    return df


def persist_predictions(
    session: Session, prediction_rows: List[Dict[str, Any]], batch_size: int = 2000
) -> None:
    """Bulk inserts ModelPrediction records into PostgreSQL."""
    session.execute(delete(ModelPrediction))
    session.flush()

    for i in range(0, len(prediction_rows), batch_size):
        chunk = prediction_rows[i : i + batch_size]
        session.execute(insert(ModelPrediction), chunk)
    session.commit()


def run_pipeline(
    module_a_threshold: float = 0.50,
    persist: bool = True,
) -> Dict[str, Any]:
    """
    Executes Phase 2 screening inference pipeline and computes verification metrics.
    """
    start_time = time.perf_counter()

    console.print(
        Panel.fit(
            "[bold cyan]ISRO SIH26170 Screening & Verdict Analytical Pipeline[/bold cyan]\n"
            "[dim]Phase 2: Module A (Spatial Outlier) + Module B (Drift Forecast) + Unified Verdict[/dim]",
            border_style="cyan",
        )
    )

    with SessionLocal() as session:
        console.print("[cyan]-> Pulling component readings from PostgreSQL...[/cyan]")
        df = fetch_screening_data(session)
        total_parts = df["component_id"].nunique()
        total_readings = len(df)
        console.print(
            f"[green]✓ Loaded {total_parts:,} components with {total_readings:,} parametric readings.[/green]"
        )

        # 1. Module A: Lot-Adaptive Outlier Detection
        console.print("[cyan]-> Fitting Module A: Lot-Adaptive Outlier Detector (Ledoit-Wolf + iForest)...[/cyan]")
        detector_a = LotOutlierDetector(threshold=module_a_threshold)
        detector_a.fit(df)
        results_a = detector_a.predict(df)
        console.print(
            f"[green]✓ Module A completed. Flagged {results_a['module_a_flag'].sum()} parts as lot outliers.[/green]"
        )

        # 2. Module B: 24h Early Drift Predictor
        console.print("[cyan]-> Training Module B: 168h Degradation Forecast (LightGBM vs Linear)...[/cyan]")
        predictor_b = DriftPredictor()
        predictor_b.fit(df)
        results_b = predictor_b.predict(df)
        b_eval_metrics = predictor_b.evaluate_against_linear_baseline(df)
        console.print(
            f"[green]✓ Module B completed. Forecasted 168h metrics with LightGBM (Leakage MAE: {b_eval_metrics['leakage_current_ua']['lightgbm_mae']} uA vs Linear: {b_eval_metrics['leakage_current_ua']['linear_mae']} uA).[/green]"
        )

        # 3. Merge Component State
        # Component metadata map (unique per component)
        comp_meta = df.drop_duplicates(subset=["component_id"])[
            [
                "component_id",
                "lot_id",
                "serial_number",
                "ground_truth_label",
                "ground_truth_flag",
                "is_datasheet_breached",
            ]
        ].set_index("component_id")

        results_a_clean = results_a.drop(columns=["lot_id"], errors="ignore").set_index("component_id")
        merged = results_a_clean.join(results_b.set_index("component_id"))
        merged = merged.join(comp_meta)

        # 4. Unified Verdict Layer
        console.print("[cyan]-> Applying Unified Verdict Layer rules...[/cyan]")
        verdict_engine = ScreeningVerdictEngine()
        evaluated_df = verdict_engine.evaluate_dataframe(merged.reset_index())
        console.print("[green]✓ Unified Verdict Layer triage complete.[/green]")

        # 5. Persist to PostgreSQL
        if persist:
            console.print("[cyan]-> Persisting ModelPrediction records to PostgreSQL...[/cyan]")
            pred_records = []
            for _, r in evaluated_df.iterrows():
                pred_records.append(
                    {
                        "component_id": r["component_id"],
                        "module_a_score": float(r["module_a_score"]),
                        "module_a_mahalanobis": float(r["module_a_mahalanobis"]),
                        "module_a_flag": bool(r["module_a_flag"]),
                        "pred_leakage_168h": float(r["pred_leakage_168h"]),
                        "pred_iddq_168h": float(r["pred_iddq_168h"]),
                        "pred_delay_168h": float(r["pred_delay_168h"]),
                        "drift_slope_ua_per_hr": float(r["drift_slope_ua_per_hr"]),
                        "module_b_flag": bool(r["module_b_flag"]),
                        "verdict": r["verdict"],
                        "verdict_reason": r["verdict_reason"],
                    }
                )
            persist_predictions(session, pred_records)
            console.print(f"[bold green]✓ Successfully committed {len(pred_records):,} predictions to PostgreSQL![/bold green]")

    elapsed = time.perf_counter() - start_time

    # Display benchmark reports
    display_benchmark_report(evaluated_df, b_eval_metrics, elapsed)

    return {
        "evaluated_df": evaluated_df,
        "drift_metrics": b_eval_metrics,
        "elapsed_seconds": round(elapsed, 2),
    }


def display_benchmark_report(
    df: pd.DataFrame, drift_metrics: Dict[str, Any], elapsed: float
) -> None:
    """Formats and prints comprehensive Rich summary and evaluation tables."""
    # Table 1: Triage Distribution (Pass / Review / Reject)
    triage_table = Table(
        title="ISRO Burn-In Screening Unified Verdict Triage",
        style="cyan",
        show_header=True,
    )
    triage_table.add_column("Verdict", style="bold")
    triage_table.add_column("Part Count", justify="right")
    triage_table.add_column("Percentage", justify="right")
    triage_table.add_column("Operational Meaning", style="dim")

    verdict_colors = {"PASS": "green", "REVIEW": "yellow", "REJECT": "red"}
    verdict_desc = {
        "PASS": "Cleared for space flight integration; nominal lot envelope & stable drift kinetics",
        "REVIEW": "Diverted to QA engineering inspection; borderline anomaly or elevated drift",
        "REJECT": "Strictly quarantined; gross specification breach or catastrophic drift trajectory",
    }

    total_parts = len(df)
    for verdict, desc in verdict_desc.items():
        count = (df["verdict"] == verdict).sum()
        pct = (count / total_parts) * 100.0
        color = verdict_colors[verdict]
        triage_table.add_row(
            f"[{color}]{verdict}[/{color}]",
            f"{count:,}",
            f"{pct:5.2f}%",
            desc,
        )

    console.print(triage_table)

    # Table 2: Anomaly Detection Performance on Ground-Truth
    # An anomaly is accurately flagged if verdict in ('REVIEW', 'REJECT')
    is_anomaly = df["ground_truth_flag"].values
    predicted_anomaly = df["verdict"].isin(["REVIEW", "REJECT"]).values

    tp = int(np.sum(is_anomaly & predicted_anomaly))
    fp = int(np.sum((~is_anomaly) & predicted_anomaly))
    tn = int(np.sum((~is_anomaly) & (~predicted_anomaly)))
    fn = int(np.sum(is_anomaly & (~predicted_anomaly)))

    recall = tp / max(tp + fn, 1)
    precision = tp / max(tp + fp, 1)
    fnr = fn / max(tp + fn, 1)  # False Negative Rate (Critical for ISRO mission safety)
    f1 = 2 * (precision * recall) / max(precision + recall, 1e-6)

    metrics_table = Table(
        title="Anomaly Detection Performance (Ground-Truth Defects)",
        style="magenta",
        show_header=True,
    )
    metrics_table.add_column("Metric", style="bold white")
    metrics_table.add_column("Value", style="green", justify="right")
    metrics_table.add_column("Significance for High-Reliability Screening", style="dim")

    metrics_table.add_row(
        "Screening Recall (Sensitivity)",
        f"{recall * 100:.2f}%",
        "Proportion of defective parts successfully intercepted",
    )
    metrics_table.add_row(
        "False Negative Rate (Miss Rate)",
        f"[{'bold red' if fnr > 0.05 else 'bold green'}]{fnr * 100:.2f}%[/{'bold red' if fnr > 0.05 else 'bold green'}]",
        "Defects escaping to flight payload (Target: < 5%)",
    )
    metrics_table.add_row(
        "Screening Precision",
        f"{precision * 100:.2f}%",
        "Confidence that an intercepted component is genuinely anomalous",
    )
    metrics_table.add_row("F1-Score", f"{f1 * 100:.2f}%", "Harmonic balance of precision and recall")
    metrics_table.add_row("True Positives (TP)", str(tp), "Defective units intercepted")
    metrics_table.add_row("False Negatives (FN)", str(fn), "Defective units missed")
    metrics_table.add_row("False Positives (FP)", str(fp), "Normal units sent to QA review")

    console.print(metrics_table)

    # Table 3: Ground Truth Label Breakdown vs Final Verdict
    class_table = Table(
        title="Disposition Breakdown by Physical Defect Signature",
        style="blue",
        show_header=True,
    )
    class_table.add_column("Ground Truth Class", style="bold")
    class_table.add_column("Total Parts", justify="right")
    class_table.add_column("Pass", justify="right", style="green")
    class_table.add_column("Review", justify="right", style="yellow")
    class_table.add_column("Reject", justify="right", style="red")
    class_table.add_column("Detection Rate", justify="right", style="bold cyan")

    for lbl, grp in df.groupby("ground_truth_label"):
        tot = len(grp)
        p_cnt = (grp["verdict"] == "PASS").sum()
        r_cnt = (grp["verdict"] == "REVIEW").sum()
        j_cnt = (grp["verdict"] == "REJECT").sum()
        det_pct = ((r_cnt + j_cnt) / tot) * 100.0 if lbl != "NORMAL" else (p_cnt / tot) * 100.0
        class_table.add_row(
            lbl,
            str(tot),
            str(p_cnt),
            str(r_cnt),
            str(j_cnt),
            f"{det_pct:5.1f}% {'(Passed)' if lbl == 'NORMAL' else '(Intercepted)'}",
        )

    console.print(class_table)

    # Table 4: Module B Kinetic Drift Forecasting Accuracy
    drift_table = Table(
        title="Module B: 168h Drift Forecasting Accuracy vs Linear Baseline",
        style="yellow",
        show_header=True,
    )
    drift_table.add_column("Electronic Parameter", style="bold")
    drift_table.add_column("LightGBM MAE", justify="right", style="green")
    drift_table.add_column("Linear Baseline MAE", justify="right", style="red")
    drift_table.add_column("LightGBM RMSE", justify="right")
    drift_table.add_column("Linear RMSE", justify="right")
    drift_table.add_column("MAE Reduction", justify="right", style="bold cyan")

    units = {
        "leakage_current_ua": "uA",
        "iddq_ma": "mA",
        "propagation_delay_ns": "ns",
    }

    for p, stats in drift_metrics.items():
        u = units.get(p, "")
        drift_table.add_row(
            p,
            f"{stats['lightgbm_mae']} {u}",
            f"{stats['linear_mae']} {u}",
            f"{stats['lightgbm_rmse']} {u}",
            f"{stats['linear_rmse']} {u}",
            f"+{stats['mae_improvement_pct']:.1f}%",
        )

    console.print(drift_table)


def main() -> None:
    """CLI Entry point for screening pipeline."""
    parser = argparse.ArgumentParser(
        description="ISRO SIH26170 Screening & Anomaly Detection Pipeline"
    )
    parser.add_argument(
        "--module-a-threshold",
        "-t",
        type=float,
        default=0.50,
        help="Module A outlier score threshold (default: 0.50)",
    )
    parser.add_argument(
        "--no-persist",
        action="store_true",
        help="Do not save predictions to PostgreSQL database",
    )

    args = parser.parse_args()

    try:
        run_pipeline(
            module_a_threshold=args.module_a_threshold,
            persist=not args.no_persist,
        )
    except Exception as exc:
        console.print(f"[bold red]Pipeline error: {exc}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
