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
from evaluation.splits import lot_holdout_split
from ml_engine.module_b_drift import DriftPredictor, linear_extrapolation_baseline
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

    # Scale-free (the decision score is in lot-MAD units): most level outliers rank above the
    # 90th percentile of normal parts.
    assert lvl_scores.mean() > 2 * norm_scores.mean()
    assert (lvl_scores > norm_scores.quantile(0.90)).mean() >= 0.75

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
    # Lot-relative scoring: parts from the benign high-baseline lots (~22 uA vs ~12 uA) score like
    # normal parts from standard lots, not like outliers.
    ratio = benign_normal_parts["module_a_score"].mean() / norm_scores.mean()
    assert 0.75 < ratio < 1.33


def test_module_b_held_out_lots_beats_linear_baseline(
    synthetic_screening_dataset: pd.DataFrame,
) -> None:
    """
    Module B is trained on some lots and evaluated on DIFFERENT lots whose 96h/168h readings are
    hidden at prediction time. (Replaces an earlier test that scored the model on its own
    training parts, which overstated accuracy.)
    """
    df = synthetic_screening_dataset.copy()
    df["lot_id"] = df["lot_id"].astype(str)
    fold = lot_holdout_split(df["lot_id"].unique(), test_fraction=0.25, seed=42)
    train = df[df["lot_id"].isin(fold.train_lots)]
    test = df[df["lot_id"].isin(fold.test_lots)]

    predictor = DriftPredictor(random_state=42).fit(train)
    preds = predictor.predict(test[test["interval_hours"].isin([0, 24])]).set_index("component_id")
    truth = test[test["interval_hours"] == 168].set_index("component_id")["leakage_current_ua"]
    base = linear_extrapolation_baseline(test)["leakage_current_ua_168"]

    ids = preds.index
    model_mae = float(np.mean(np.abs(preds.loc[ids, "pred_leakage_168h"] - truth.loc[ids])))
    base_mae = float(np.mean(np.abs(base.loc[ids] - truth.loc[ids])))
    assert model_mae < base_mae

    meta = test.drop_duplicates("component_id").set_index("component_id")["ground_truth_label"]
    steep = preds[meta.loc[ids] == "STEEP_DRIFT"]
    normal = preds[meta.loc[ids] == "NORMAL"]
    assert len(steep) > 0
    # Held-out steep-drift parts are forecast well above held-out normal parts.
    assert steep["pred_leakage_168h"].median() > normal["pred_leakage_168h"].quantile(0.95)


def test_unified_verdict_mapping_uses_supplied_thresholds() -> None:
    """
    Decision = union of Module A and Module B with LEARNED thresholds, plus datasheet rules.
    (Replaces a test that encoded the removed hand-set constants 0.85 / 0.50 / 0.12 / 35 uA.)
    """
    engine = ScreeningVerdictEngine()
    nominal = {"leakage_current_ua": 12.0, "iddq_ma": 1.5, "propagation_delay_ns": 4.2}

    def ev(**kw):
        args = dict(observed_breach=False, predictions_168h=nominal, module_a_score=0.1,
                    threshold_a=0.4, module_b_score=0.01, threshold_b=0.05)
        args.update(kw)
        return engine.evaluate_component(**args)

    assert ev(observed_breach=True)[0] == "REJECT"
    v, r = ev(predictions_168h={**nominal, "leakage_current_ua": 52.5})
    assert v == "REJECT" and "RULE_PRED_LIMIT" in r
    v, r = ev(module_a_score=0.5, module_b_score=0.2)
    assert v == "REJECT" and "RULE_BOTH_MODULES" in r
    v, r = ev(module_a_score=0.5)
    assert v == "REVIEW" and "RULE_MODULE_A" in r and "threshold 0.400" in r
    v, r = ev(module_b_score=0.06)
    assert v == "REVIEW" and "RULE_MODULE_B" in r
    assert ev()[0] == "PASS"
    # The same scores give a different decision when the learned threshold differs.
    assert ev(module_a_score=0.5, threshold_a=0.6)[0] == "PASS"
    # A disabled module (threshold = +inf) never flags.
    assert ev(module_a_score=1.0, threshold_a=float("inf"))[0] == "PASS"


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
