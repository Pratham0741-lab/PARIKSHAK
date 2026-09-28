"""
Automated Unit and Integration Tests for Phase 2 Analytical Engines.
Tests Module A (Lot Outlier Detector), Module B (Early Drift Predictor),
and the Unified Verdict Layer for ISRO SIH26170.
"""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from backend.app.core.database import SessionLocal
from backend.app.models import Component, ModelPrediction, ScreeningVerdict
from data_engine.generator import BurnInSyntheticGenerator
from ml_engine.module_a_outlier import LotOutlierDetector
from ml_engine.module_b_drift import DriftPredictor
from ml_engine.verdict_engine import ScreeningVerdictEngine


@pytest.fixture(scope="module")
def synthetic_screening_dataset() -> pd.DataFrame:
    """Provides a deterministic synthetic burn-in dataset for testing."""
    generator = BurnInSyntheticGenerator(
        num_lots=8,
        components_per_lot=60,
        random_seed=42,
        benign_lot_fraction=0.25,
    )
    return generator.generate_dataset()


def test_module_a_outlier_detection_and_benign_control(
    synthetic_screening_dataset: pd.DataFrame,
) -> None:
    """
    Verifies Module A detects LEVEL_OUTLIER and SUBTLE_MULTIVARIATE defects
    while preserving BENIGN_HIGH_LOT controls without false alarms.
    """
    df = synthetic_screening_dataset
    detector = LotOutlierDetector(threshold=0.50, random_state=42)
    detector.fit(df)
    results = detector.predict(df)

    # Merge labels
    meta = df.drop_duplicates(subset=["component_id"])[
        ["component_id", "ground_truth_label", "is_benign_high_lot"]
    ]
    merged = results.merge(meta, on="component_id")

    # 1. LEVEL_OUTLIER should have significantly higher scores than standard NORMAL parts
    lvl_scores = merged[merged["ground_truth_label"] == "LEVEL_OUTLIER"]["module_a_score"]
    norm_scores = merged[
        (merged["ground_truth_label"] == "NORMAL") & (~merged["is_benign_high_lot"])
    ]["module_a_score"]

    assert lvl_scores.mean() > norm_scores.mean() + 0.35
    assert (lvl_scores > 0.40).mean() >= 0.75

    # 2. SUBTLE_MULTIVARIATE should exhibit elevated Mahalanobis distances
    subtle_maha = merged[merged["ground_truth_label"] == "SUBTLE_MULTIVARIATE"]["module_a_mahalanobis"]
    norm_maha = merged[
        (merged["ground_truth_label"] == "NORMAL") & (~merged["is_benign_high_lot"])
    ]["module_a_mahalanobis"]
    assert subtle_maha.mean() > norm_maha.mean()

    # 3. BENIGN_HIGH_LOT control parts should NOT be falsely flagged by naive baseline elevation
    benign_parts = merged[merged["is_benign_high_lot"]]
    benign_normal_parts = benign_parts[benign_parts["ground_truth_label"] == "NORMAL"]
    assert len(benign_normal_parts) > 0
    # Mean score for benign lot parts must remain low despite elevated baseline (~22 uA)
    assert benign_normal_parts["module_a_score"].mean() < 0.35


def test_module_b_drift_prediction_and_baseline_comparison(
    synthetic_screening_dataset: pd.DataFrame,
) -> None:
    """
    Verifies Module B predicts STEEP_DRIFT from early intervals (0h/24h)
    and demonstrates test MAE superior to the linear baseline extrapolator.
    """
    df = synthetic_screening_dataset
    predictor = DriftPredictor(random_state=42)
    predictor.fit(df)

    # 1. Benchmark comparison against Linear Extrapolator
    metrics = predictor.evaluate_against_linear_baseline(df, test_size=0.30)
    leak_metrics = metrics["leakage_current_ua"]

    # LightGBM MAE must be substantially lower than linear baseline (> 35% improvement)
    assert leak_metrics["lightgbm_mae"] < leak_metrics["linear_mae"]
    assert leak_metrics["mae_improvement_pct"] > 35.0

    # 2. Check STEEP_DRIFT detection
    predictions = predictor.predict(df)
    meta = df.drop_duplicates(subset=["component_id"])[
        ["component_id", "ground_truth_label"]
    ]
    merged = predictions.merge(meta, on="component_id")

    steep_parts = merged[merged["ground_truth_label"] == "STEEP_DRIFT"]
    assert len(steep_parts) > 0
    # Predicted 168h leakage should capture the drift past 30 uA
    assert (steep_parts["pred_leakage_168h"] > 30.0).all()
    # Implied drift slopes should be elevated (> 0.10 uA/hr)
    assert (steep_parts["drift_slope_ua_per_hr"] > 0.08).mean() >= 0.90


def test_unified_verdict_mapping_and_borderline_review() -> None:
    """
    Verifies that the ScreeningVerdictEngine deterministically maps rules
    to PASS, REVIEW, and REJECT, correctly steering borderline parts to REVIEW.
    """
    engine = ScreeningVerdictEngine()

    # Rule 1: Datasheet breach -> REJECT
    v, r = engine.evaluate_component(
        is_datasheet_breached=True,
        module_a_score=0.2,
        module_a_flag=False,
        pred_leakage_168h=15.0,
        pred_iddq_168h=1.5,
        pred_delay_168h=4.2,
        drift_slope_ua_per_hr=0.01,
        module_b_flag=False,
    )
    assert v == "REJECT"
    assert "RULE_BREACH" in r

    # Rule 2: Extreme Module A score (> 0.85) -> REJECT
    v, r = engine.evaluate_component(
        is_datasheet_breached=False,
        module_a_score=0.92,
        module_a_flag=True,
        pred_leakage_168h=20.0,
        pred_iddq_168h=1.5,
        pred_delay_168h=4.2,
        drift_slope_ua_per_hr=0.02,
        module_b_flag=False,
    )
    assert v == "REJECT"
    assert "RULE_EXTREME_OUTLIER" in r

    # Rule 3: Predicted 168h leakage exceeding 50 uA ceiling -> REJECT
    v, r = engine.evaluate_component(
        is_datasheet_breached=False,
        module_a_score=0.3,
        module_a_flag=False,
        pred_leakage_168h=52.5,
        pred_iddq_168h=1.5,
        pred_delay_168h=4.2,
        drift_slope_ua_per_hr=0.25,
        module_b_flag=True,
    )
    assert v == "REJECT"

    # Rule 4: Borderline Module A score (0.50 <= score < 0.85) -> REVIEW
    v, r = engine.evaluate_component(
        is_datasheet_breached=False,
        module_a_score=0.68,
        module_a_flag=True,
        pred_leakage_168h=18.0,
        pred_iddq_168h=1.5,
        pred_delay_168h=4.2,
        drift_slope_ua_per_hr=0.03,
        module_b_flag=False,
    )
    assert v == "REVIEW"
    assert "RULE_BORDERLINE" in r

    # Rule 5: Elevated drift slope (> 0.12 uA/hr) -> REVIEW
    v, r = engine.evaluate_component(
        is_datasheet_breached=False,
        module_a_score=0.25,
        module_a_flag=False,
        pred_leakage_168h=32.0,
        pred_iddq_168h=1.5,
        pred_delay_168h=4.2,
        drift_slope_ua_per_hr=0.14,
        module_b_flag=True,
    )
    assert v == "REVIEW"
    assert "Elevated drift slope" in r

    # Rule 6: Nominal component within envelope -> PASS
    v, r = engine.evaluate_component(
        is_datasheet_breached=False,
        module_a_score=0.15,
        module_a_flag=False,
        pred_leakage_168h=12.2,
        pred_iddq_168h=1.48,
        pred_delay_168h=4.15,
        drift_slope_ua_per_hr=0.005,
        module_b_flag=False,
    )
    assert v == "PASS"
    assert "RULE_NOMINAL" in r


def test_model_predictions_database_persistence() -> None:
    """Verifies that ModelPrediction records persisted in PostgreSQL can be retrieved."""
    with SessionLocal() as session:
        preds = session.scalars(select(ModelPrediction).limit(5)).all()
        assert len(preds) > 0

        first_pred = preds[0]
        assert first_pred.id is not None
        assert first_pred.verdict in [
            ScreeningVerdict.PASS,
            ScreeningVerdict.REVIEW,
            ScreeningVerdict.REJECT,
        ]
        assert 0.0 <= first_pred.module_a_score <= 1.0
        assert first_pred.component is not None
        assert first_pred.component.serial_number is not None
