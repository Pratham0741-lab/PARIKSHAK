"""
Metrics API: held-out screening performance with FN-weighted cost, F2, and threshold-vs-cost curves.

All numbers are computed on request from persisted OUT-OF-FOLD predictions joined with ground
truth, using the same code as the offline evaluation (evaluation/cost.py, evaluation/thresholds.py).
Parts without ground truth (e.g. ingested production lots) are excluded and counted.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import numpy as np
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.config import settings
from backend.app.core.database import get_async_db
from backend.app.models.component import Component
from backend.app.models.run import ScreeningRun
from backend.app.schemas.metrics import BenchmarkMetricsResponse, CostCurveResponse
from evaluation.cost import CostConfig, cost_report
from evaluation.thresholds import cost_curve
from ml_engine.verdict_engine import ScreeningVerdictEngine

router = APIRouter(prefix="/metrics", tags=["Metrics"])

PROTOCOL = (
    "Out-of-fold: GroupKFold over lots; each part is predicted by a model trained on other lots "
    "from its 0h/24h readings only. Ground truth is joined only at scoring time."
)


def _cost(fn_cost: Optional[float], fp_cost: Optional[float]) -> CostConfig:
    return CostConfig.from_settings(fn_cost=fn_cost, fp_cost=fp_cost)


async def _labelled_rows(db: AsyncSession) -> Dict[str, Any]:
    comps = (
        await db.execute(select(Component).options(selectinload(Component.prediction), selectinload(Component.readings)))
    ).scalars().all()
    rows = []
    no_truth = 0
    for c in comps:
        if c.prediction is None:
            continue
        if c.ground_truth_flag is None:
            no_truth += 1
            continue
        rows.append(c)
    return {"rows": rows, "total": len(comps), "no_truth": no_truth}


async def _latest_run(db: AsyncSession) -> Optional[ScreeningRun]:
    return (await db.execute(select(ScreeningRun).order_by(ScreeningRun.created_at.desc()).limit(1))).scalars().first()


def _verdict(c: Component) -> str:
    v = c.prediction.verdict
    return v.value if hasattr(v, "value") else str(v)


@router.get("/benchmark", response_model=BenchmarkMetricsResponse, summary="Held-out recall, precision, F2, FN-weighted cost, drift MAE")
async def get_benchmark_metrics(
    fn_cost: Optional[float] = Query(None, ge=0, description=f"Cost of a missed defect (default {settings.FN_COST:g})"),
    fp_cost: Optional[float] = Query(None, ge=0, description=f"Cost of a false alarm (default {settings.FP_COST:g})"),
    db: AsyncSession = Depends(get_async_db),
) -> BenchmarkMetricsResponse:
    cfg = _cost(fn_cost, fp_cost)
    data = await _labelled_rows(db)
    comps = data["rows"]

    y_true = np.array([bool(c.ground_truth_flag) for c in comps], dtype=bool)
    verdicts = [_verdict(c) for c in comps]
    y_pred = np.array([v in ("REVIEW", "REJECT") for v in verdicts], dtype=bool)
    rep = cost_report(y_true, y_pred, cfg)

    triage = {"PASS": 0, "REVIEW": 0, "REJECT": 0}
    for v in verdicts:
        triage[v] = triage.get(v, 0) + 1

    lgbm_err: List[float] = []
    lin_err: List[float] = []
    for c in comps:
        r = {x.interval_hours: x.leakage_current_ua for x in c.readings}
        if {0, 24, 168} <= r.keys() and c.prediction.pred_leakage_168h is not None:
            lgbm_err.append(abs(c.prediction.pred_leakage_168h - r[168]))
            lin_err.append(abs(r[0] + 7.0 * (r[24] - r[0]) - r[168]))
    mae = float(np.mean(lgbm_err)) if lgbm_err else 0.0
    mae_lin = float(np.mean(lin_err)) if lin_err else 0.0
    oof = sum(1 for c in comps if c.prediction.cv_fold is not None)
    run = await _latest_run(db)

    return BenchmarkMetricsResponse(
        total_components=len(comps),
        excluded_without_ground_truth=data["no_truth"],
        defective_count=int(y_true.sum()),
        benign_count=int((~y_true).sum()),
        flagged_count=int(y_pred.sum()),
        true_positives=rep["tp"],
        false_positives=rep["fp"],
        false_negatives=rep["fn"],
        true_negatives=rep["tn"],
        recall=round(rep["recall"], 4),
        precision=round(rep["precision"], 4),
        false_negative_rate=round(rep["false_negative_rate"], 4),
        f1_score=round(rep["f1"], 4),
        f2_score=round(rep["f2"], 4),
        fn_cost=cfg.fn_cost,
        fp_cost=cfg.fp_cost,
        weighted_cost=round(rep["weighted_cost"], 4),
        cost_per_1000_parts=round(rep["cost_per_1000_parts"], 4),
        triage_distribution=triage,
        module_b_mae_leakage=round(mae, 4),
        linear_baseline_mae_leakage=round(mae_lin, 4),
        mae_reduction_pct=round((mae_lin - mae) / mae_lin * 100.0, 2) if mae_lin > 0 else 0.0,
        evaluation_protocol=PROTOCOL,
        out_of_fold_predictions=oof,
        in_sample_predictions=len(comps) - oof,
        final_thresholds=(run.final_thresholds if run else None),
        run_id=(run.id if run else None),
    )


def _forced(c: Component, limits: Dict[str, float]) -> bool:
    """Specification rules: observed (0h/24h) or forecast (168h) datasheet breach."""
    p = c.prediction
    if p.pred_leakage_168h is not None and (
        p.pred_leakage_168h >= limits["leakage_current_ua"]
        or p.pred_iddq_168h >= limits["iddq_ma"]
        or p.pred_delay_168h >= limits["propagation_delay_ns"]
    ):
        return True
    return any(
        r.interval_hours in (0, 24)
        and (r.leakage_current_ua > limits["leakage_current_ua"] or r.iddq_ma > limits["iddq_ma"]
             or r.propagation_delay_ns > limits["propagation_delay_ns"])
        for r in c.readings
    )


@router.get("/cost-curve", response_model=CostCurveResponse, summary="Weighted cost / FN / FP vs. one module's threshold")
async def get_cost_curve(
    module: Literal["A", "B"] = Query("A", description="Which module's threshold to sweep"),
    fn_cost: Optional[float] = Query(None, ge=0),
    fp_cost: Optional[float] = Query(None, ge=0),
    points: int = Query(40, ge=5, le=200),
    db: AsyncSession = Depends(get_async_db),
) -> CostCurveResponse:
    """
    Sweeps one module's threshold over the persisted out-of-fold scores while the other module is
    held at its chosen (final-model) threshold. Specification rules (observed or forecast datasheet
    breach) always apply. This is a diagnostic of the cost landscape; the operational thresholds
    were chosen on inner-CV validation data, not on this curve.
    """
    cfg = _cost(fn_cost, fp_cost)
    comps = [c for c in (await _labelled_rows(db))["rows"] if c.prediction.module_b_score is not None]
    run = await _latest_run(db)
    thr = (run.final_thresholds if run else {}) or {}
    ta = float("inf") if thr.get("threshold_a") is None else float(thr["threshold_a"])
    tb = float("inf") if thr.get("threshold_b") is None else float(thr["threshold_b"])

    limits = ScreeningVerdictEngine.datasheet_limits()
    a = np.array([c.prediction.module_a_score for c in comps], dtype=float)
    b = np.array([c.prediction.module_b_score for c in comps], dtype=float)
    y = np.array([bool(c.ground_truth_flag) for c in comps], dtype=bool)
    forced = np.array([_forced(c, limits) for c in comps], dtype=bool)

    sweep, fixed, t_fixed, chosen = (a, b, tb, ta) if module == "A" else (b, a, ta, tb)
    curve = cost_curve(sweep, fixed, t_fixed, y, cfg, forced, n_points=points)
    fin = lambda x: None if x == float("inf") else x  # noqa: E731
    return CostCurveResponse(
        module=module,
        fn_cost=cfg.fn_cost,
        fp_cost=cfg.fp_cost,
        chosen_threshold=fin(chosen),
        other_threshold=fin(t_fixed),
        n_parts=len(comps),
        points=curve,
    )
