"""
Pydantic schemas for held-out evaluation metrics.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class BenchmarkMetricsResponse(BaseModel):
    """Held-out (out-of-fold) screening performance, computed from persisted predictions + ground truth."""
    total_components: int = Field(..., description="Components with a prediction AND ground truth (scored)")
    excluded_without_ground_truth: int = Field(0, description="Predicted components without ground truth (not scored)")
    defective_count: int = Field(..., description="Ground-truth defective components")
    benign_count: int = Field(..., description="Ground-truth benign components")
    flagged_count: int = Field(..., description="Components flagged REVIEW or REJECT")
    true_positives: int
    false_positives: int
    false_negatives: int = Field(..., description="Defective components passed (escapes)")
    true_negatives: int
    recall: float
    precision: float
    false_negative_rate: float
    f1_score: float
    f2_score: float = Field(..., description="F-beta with beta=2 (recall weighted 4x precision)")
    fn_cost: float = Field(..., description="Cost of one missed defect")
    fp_cost: float = Field(..., description="Cost of one false alarm")
    weighted_cost: float = Field(..., description="fn_cost*FN + fp_cost*FP")
    cost_per_1000_parts: float
    triage_distribution: Dict[str, int]
    module_b_mae_leakage: float = Field(..., description="Held-out 168h leakage forecast MAE (uA)")
    linear_baseline_mae_leakage: float = Field(..., description="Linear extrapolation baseline MAE (uA)")
    mae_reduction_pct: float
    evaluation_protocol: str
    out_of_fold_predictions: int
    in_sample_predictions: int = Field(..., description="Predictions lacking out-of-fold provenance (should be 0)")
    final_thresholds: Optional[Dict[str, Any]] = Field(None, description="Thresholds persisted with the latest model artifact")
    run_id: Optional[uuid.UUID] = None


class CostCurvePoint(BaseModel):
    threshold: float
    weighted_cost: float
    fn: int
    fp: int
    recall: float
    precision: float
    f2: float


class CostCurveResponse(BaseModel):
    module: str
    fn_cost: float
    fp_cost: float
    chosen_threshold: Optional[float] = Field(None, description="Operational threshold (NULL = module disabled)")
    other_threshold: Optional[float] = None
    n_parts: int
    points: List[CostCurvePoint]
