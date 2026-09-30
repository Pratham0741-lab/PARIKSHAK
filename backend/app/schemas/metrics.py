"""
Pydantic Schemas for System Evaluation and Benchmark Metrics.
"""

from __future__ import annotations

from typing import Dict
from pydantic import BaseModel, Field


class BenchmarkMetricsResponse(BaseModel):
    """Aggregate benchmark report highlighting Recall, False Negative Rate, and Drift MAE."""
    total_components: int = Field(..., description="Total evaluated components")
    defective_count: int = Field(..., description="Total ground-truth defective components")
    benign_count: int = Field(..., description="Total ground-truth benign components")
    flagged_count: int = Field(..., description="Total components flagged as REVIEW or REJECT")
    true_positives: int = Field(..., description="Defective components correctly flagged")
    false_positives: int = Field(..., description="Benign components incorrectly flagged")
    false_negatives: int = Field(..., description="Defective components mistakenly passed (Critical)")
    true_negatives: int = Field(..., description="Benign components correctly passed")
    recall: float = Field(..., description="Recall = TP / (TP + FN)")
    precision: float = Field(..., description="Precision = TP / (TP + FP)")
    false_negative_rate: float = Field(..., description="FNR = FN / (TP + FN) [Mission-critical]")
    f1_score: float = Field(..., description="Harmonic mean of precision and recall")
    triage_distribution: Dict[str, int] = Field(..., description="Distribution across PASS, REVIEW, REJECT")
    module_b_mae_leakage: float = Field(..., description="LightGBM 168h forecast MAE in uA")
    linear_baseline_mae_leakage: float = Field(..., description="Linear extrapolation baseline MAE in uA")
    mae_reduction_pct: float = Field(..., description="Percent improvement over linear baseline")
    evaluation_protocol: str = Field(..., description="How the scored predictions were produced")
    out_of_fold_predictions: int = Field(..., description="Predictions produced by a model that never saw the part's lot")
    in_sample_predictions: int = Field(..., description="Predictions lacking out-of-fold provenance (should be 0)")
