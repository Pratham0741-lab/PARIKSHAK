"""
Metrics API endpoint: benchmark performance reporting including Recall, FNR, and Drift MAE.
"""

from __future__ import annotations

from typing import Dict, List
import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.database import get_async_db
from backend.app.models.component import Component
from backend.app.models.prediction import ModelPrediction, ScreeningVerdict
from backend.app.models.reading import BurnInReading
from backend.app.schemas.metrics import BenchmarkMetricsResponse

router = APIRouter(prefix="/metrics", tags=["Metrics"])

PROTOCOL = (
    "Out-of-fold: GroupKFold over lots; each part is predicted by a model trained on other lots "
    "from its 0h/24h readings only. Ground truth is joined only at scoring time."
)


@router.get(
    "/benchmark",
    response_model=BenchmarkMetricsResponse,
    summary="Get system-wide screening recall, FNR, and Module B drift accuracy",
)
async def get_benchmark_metrics(
    db: AsyncSession = Depends(get_async_db),
) -> BenchmarkMetricsResponse:
    """
    Computes system-level validation benchmarks against ground-truth defect labels:
    - Anomaly Detection Recall, Precision, False Negative Rate (FNR), and F1 Score.
    - Component Triage Distribution (PASS / REVIEW / REJECT).
    - Module B LightGBM 168h Forecast MAE vs Simple Linear Extrapolation Baseline.
    """
    stmt = (
        select(Component)
        .options(
            selectinload(Component.prediction),
            selectinload(Component.readings),
        )
    )
    result = await db.execute(stmt)
    components = result.scalars().all()

    total = len(components)
    if total == 0:
        return BenchmarkMetricsResponse(
            total_components=0,
            defective_count=0,
            benign_count=0,
            flagged_count=0,
            true_positives=0,
            false_positives=0,
            false_negatives=0,
            true_negatives=0,
            recall=0.0,
            precision=0.0,
            false_negative_rate=0.0,
            f1_score=0.0,
            triage_distribution={"PASS": 0, "REVIEW": 0, "REJECT": 0},
            module_b_mae_leakage=0.0,
            linear_baseline_mae_leakage=0.0,
            mae_reduction_pct=0.0,
            evaluation_protocol=PROTOCOL,
            out_of_fold_predictions=0,
            in_sample_predictions=0,
        )

    oof = 0
    tp = 0
    fp = 0
    fn = 0
    tn = 0
    defective_count = 0
    benign_count = 0
    flagged_count = 0

    triage_counts: Dict[str, int] = {"PASS": 0, "REVIEW": 0, "REJECT": 0}

    lgbm_errors: List[float] = []
    linear_errors: List[float] = []

    for comp in components:
        is_defective = bool(comp.ground_truth_flag)
        if is_defective:
            defective_count += 1
        else:
            benign_count += 1

        pred = comp.prediction
        if pred is not None and pred.cv_fold is not None:
            oof += 1
        verdict = pred.verdict.value if pred and hasattr(pred.verdict, "value") else (str(pred.verdict) if pred else "PASS")
        triage_counts[verdict] = triage_counts.get(verdict, 0) + 1

        # Screening alert = REVIEW or REJECT (or module flags)
        is_flagged = verdict in ["REVIEW", "REJECT"]
        if is_flagged:
            flagged_count += 1

        if is_defective and is_flagged:
            tp += 1
        elif not is_defective and is_flagged:
            fp += 1
        elif is_defective and not is_flagged:
            fn += 1
        else:
            tn += 1

        # Compare Module B vs Linear Baseline on actual 168h leakage
        if pred and comp.readings:
            r_map = {r.interval_hours: r.leakage_current_ua for r in comp.readings}
            if 0 in r_map and 24 in r_map and 168 in r_map:
                actual_168 = r_map[168]
                v0 = r_map[0]
                v24 = r_map[24]
                # Linear baseline projection: v0 + 7 * (v24 - v0)
                linear_proj = v0 + 7.0 * (v24 - v0)
                lgbm_proj = pred.pred_leakage_168h

                lgbm_errors.append(abs(lgbm_proj - actual_168))
                linear_errors.append(abs(linear_proj - actual_168))

    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    fnr = fn / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    mae_lgbm = float(np.mean(lgbm_errors)) if lgbm_errors else 0.0
    mae_linear = float(np.mean(linear_errors)) if linear_errors else 0.0
    reduction_pct = ((mae_linear - mae_lgbm) / mae_linear * 100.0) if mae_linear > 0 else 0.0

    return BenchmarkMetricsResponse(
        total_components=total,
        defective_count=defective_count,
        benign_count=benign_count,
        flagged_count=flagged_count,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        recall=round(recall, 4),
        precision=round(precision, 4),
        false_negative_rate=round(fnr, 4),
        f1_score=round(f1, 4),
        triage_distribution=triage_counts,
        module_b_mae_leakage=round(mae_lgbm, 4),
        linear_baseline_mae_leakage=round(mae_linear, 4),
        mae_reduction_pct=round(reduction_pct, 2),
        evaluation_protocol=PROTOCOL,
        out_of_fold_predictions=oof,
        in_sample_predictions=sum(1 for c in components if c.prediction is not None) - oof,
    )
