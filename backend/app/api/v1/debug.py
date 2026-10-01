"""
Debug: recompute the numbers the UI displays straight from raw database rows, with deliberately simple
code that does not use the services or evaluation modules. The UI's "Recompute" button compares these
values with the ones on screen and marks any mismatch.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict

from fastapi import APIRouter
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from backend.app.core.config import settings
from backend.app.core.database import SessionLocal

router = APIRouter(prefix="/debug", tags=["Debug"])


def _recompute() -> Dict[str, Any]:
    with SessionLocal() as s:
        preds = s.execute(text(
            "SELECT c.id, c.lot_id, c.ground_truth_flag, p.verdict::text AS verdict, p.pred_leakage_168h "
            "FROM components c JOIN model_predictions p ON p.component_id = c.id")).all()
        readings = s.execute(text(
            "SELECT component_id, interval_hours, leakage_current_ua FROM burn_in_readings "
            "WHERE interval_hours IN (0, 24, 168)")).all()

    lots: Dict[str, Dict[str, int]] = defaultdict(lambda: {"pass": 0, "review": 0, "reject": 0, "total": 0})
    tp = fp = fn = tn = 0
    for r in preds:
        lot = lots[str(r.lot_id)]
        lot[r.verdict.lower()] += 1
        lot["total"] += 1
        if r.ground_truth_flag is None:
            continue
        flagged = r.verdict in ("REVIEW", "REJECT")
        if r.ground_truth_flag and flagged:
            tp += 1
        elif r.ground_truth_flag:
            fn += 1
        elif flagged:
            fp += 1
        else:
            tn += 1

    leak: Dict[str, Dict[int, float]] = defaultdict(dict)
    for r in readings:
        leak[str(r.component_id)][r.interval_hours] = r.leakage_current_ua
    err, lin = [], []
    for r in preds:
        v = leak.get(str(r.id), {})
        if r.ground_truth_flag is None or r.pred_leakage_168h is None or not {0, 24, 168} <= v.keys():
            continue
        err.append(abs(r.pred_leakage_168h - v[168]))
        lin.append(abs(v[0] + 7.0 * (v[24] - v[0]) - v[168]))

    n = tp + fp + fn + tn
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    f2 = 5 * precision * recall / (4 * precision + recall) if precision + recall else 0.0
    return {
        "benchmark": {
            "total_components": n, "true_positives": tp, "false_positives": fp, "false_negatives": fn,
            "true_negatives": tn, "recall": round(recall, 4), "precision": round(precision, 4), "f2_score": round(f2, 4),
            "weighted_cost": round(settings.FN_COST * fn + settings.FP_COST * fp, 4),
            "module_b_mae_leakage": round(sum(err) / len(err), 4) if err else 0.0,
            "linear_baseline_mae_leakage": round(sum(lin) / len(lin), 4) if lin else 0.0,
        },
        "lots": lots,
        "method": "raw SQL rows + plain Python (no services/evaluation code)",
    }


@router.get("/recompute", summary="Recompute displayed metrics and lot counts from raw rows")
async def recompute() -> Dict[str, Any]:
    return await run_in_threadpool(_recompute)
