"""FN-weighted scoring and cost-based threshold selection."""

from __future__ import annotations

import json

import numpy as np
import pytest

from data_engine.generator import BurnInSyntheticGenerator
from evaluation.cost import CostConfig, cost_report, f_beta
from evaluation.thresholds import choose_threshold, choose_union_thresholds, cost_curve
from ml_engine.screening import COLD_START_THRESHOLDS, ScreeningModel


@pytest.fixture(scope="module")
def validation_scores():
    """Real out-of-fold validation scores from the inner CV of a ScreeningModel."""
    df = BurnInSyntheticGenerator(num_lots=6, components_per_lot=60, random_seed=3).generate_dataset()
    return ScreeningModel(random_state=0).validation_scores(df)


FN_COSTS = [0.5, 1, 2, 5, 10, 20, 50, 100, 500]


def test_raising_fn_cost_never_raises_threshold_or_fns_single_score(validation_scores):
    v = validation_scores
    prev_t, prev_fn = np.inf, np.inf
    for c in FN_COSTS:
        res = choose_threshold(v["module_a_score"], v["y"], CostConfig(fn_cost=c, fp_cost=1.0))
        t, fn = res["threshold"], res["validation"]["fn"]
        assert t <= prev_t, f"threshold rose from {prev_t} to {t} when FN_COST rose to {c}"
        assert fn <= prev_fn, f"FN rose from {prev_fn} to {fn} when FN_COST rose to {c}"
        prev_t, prev_fn = t, fn


def test_raising_fn_cost_never_increases_fns_union(validation_scores):
    v = validation_scores
    forced = v["observed_static_breach"] | v["predicted_limit_breach"]
    fns, recalls = [], []
    for c in FN_COSTS:
        res = choose_union_thresholds(v["module_a_score"], v["module_b_score"], v["y"],
                                      CostConfig(fn_cost=c, fp_cost=1.0), forced=forced)
        fns.append(res["validation"]["fn"])
        recalls.append(res["validation"]["recall"])
    assert all(b <= a for a, b in zip(fns, fns[1:], strict=False)), fns
    assert all(b >= a for a, b in zip(recalls, recalls[1:], strict=False)), recalls
    assert fns[-1] < fns[0]  # the cost ratio actually matters on this data


def test_fewer_false_negatives_scores_better_at_equal_accuracy():
    y = np.array([1] * 20 + [0] * 180, dtype=bool)
    # Model X: 2 FN, 10 FP. Model Y: 10 FN, 2 FP. Same accuracy (12 errors each).
    px = y.copy()
    px[:2] = False
    px[20:30] = True
    py = y.copy()
    py[:10] = False
    py[20:22] = True
    cfg = CostConfig()
    rx, ry = cost_report(y, px, cfg), cost_report(y, py, cfg)
    assert (rx["fn"], rx["fp"], ry["fn"], ry["fp"]) == (2, 10, 10, 2)
    assert rx["tp"] + rx["tn"] == ry["tp"] + ry["tn"]
    assert rx["weighted_cost"] < ry["weighted_cost"]
    assert rx["f2"] > ry["f2"]
    assert rx["weighted_cost"] == 2 * cfg.fn_cost + 10 * cfg.fp_cost
    assert rx["cost_per_1000_parts"] == pytest.approx(1000 * rx["weighted_cost"] / 200)


def test_f_beta_matches_definition():
    assert f_beta(0.5, 0.8, 2.0) == pytest.approx(5 * 0.5 * 0.8 / (4 * 0.5 + 0.8))
    assert f_beta(0.0, 0.0) == 0.0


def test_recall_target_is_enforced(validation_scores):
    v = validation_scores
    res = choose_union_thresholds(v["module_a_score"], v["module_b_score"], v["y"],
                                  CostConfig(fn_cost=1.0, fp_cost=1.0, recall_target=0.95))
    assert res["validation"]["recall"] >= 0.95


def test_cost_curve_is_computed_not_assumed(validation_scores):
    v = validation_scores
    curve = cost_curve(v["module_a_score"], v["module_b_score"], np.inf, v["y"], CostConfig())
    assert len(curve) > 5
    thresholds = [p["threshold"] for p in curve]
    assert thresholds == sorted(thresholds)
    # sweeping upward can only lose detections
    assert all(b["fn"] >= a["fn"] for a, b in zip(curve, curve[1:], strict=False))
    for p in curve:
        assert p["weighted_cost"] == 20 * p["fn"] + 1 * p["fp"]


def test_model_learns_and_persists_thresholds(tmp_path):
    df = BurnInSyntheticGenerator(num_lots=5, components_per_lot=40, random_seed=9).generate_dataset()
    m = ScreeningModel(cost=CostConfig(fn_cost=20, fp_cost=1), random_state=0).fit(df)
    assert m.thresholds_["source"] == "cost_minimised_on_inner_oof_validation"
    assert (m.thresholds_["threshold_a"], m.thresholds_["threshold_b"]) != (
        COLD_START_THRESHOLDS["threshold_a"], COLD_START_THRESHOLDS["threshold_b"])
    path = tmp_path / "model.joblib"
    m.save(path)
    loaded = ScreeningModel.load(path)
    assert loaded.thresholds_ == m.thresholds_
    meta = json.loads(path.with_suffix(".json").read_text())
    assert meta["cost_config"]["fn_cost"] == 20
    # predictions apply the persisted thresholds
    preds = loaded.predict(df)
    assert (preds["threshold_a"] == m.thresholds_["threshold_a"]).all()
    assert (preds["module_a_flag"] == (preds["module_a_score"] >= m.thresholds_["threshold_a"])).all()


def test_separate_strategy_keeps_module_b_rule_active(validation_scores):
    from evaluation.thresholds import choose_thresholds
    from ml_engine.screening import MODULE_B_TARGET_CLASSES

    v = validation_scores
    forced = v["observed_static_breach"] | v["predicted_limit_breach"]
    scope = v["label"].isin(MODULE_B_TARGET_CLASSES) | ~v["y"]
    res = choose_thresholds(v["module_a_score"], v["module_b_score"], v["y"], CostConfig(), forced,
                            strategy="separate", b_scope=scope, b_positive=v["label"].isin(MODULE_B_TARGET_CLASSES))
    assert np.isfinite(res["threshold_b"]) and np.isfinite(res["threshold_a"])
    # k is exactly the cost-optimal single threshold on Module B's drift scope
    rb = choose_threshold(v["module_b_score"][scope], v["label"][scope].isin(MODULE_B_TARGET_CLASSES),
                          CostConfig(), forced[scope])
    assert res["threshold_b"] == rb["threshold"]


def test_module_a_decision_statistic_matches_dev_study():
    from pathlib import Path

    from backend.app.core.config import settings

    study = json.loads((Path(__file__).resolve().parent.parent / "reports" / "module_a_dev_study.json").read_text())
    assert settings.SYNTHETIC_RANDOM_SEED not in study["dev_seeds"]
    assert study["selected"] == "sum_positive_z"
    best = max(study["mean_auc"], key=lambda k: study["mean_auc"][k]["auc_all"])
    assert best == study["selected"]


def test_module_a_statistic_also_wins_on_physics_development_data():
    from pathlib import Path

    from backend.app.core.config import settings

    study = json.loads((Path(__file__).resolve().parent.parent / "reports" / "module_a_dev_study_physics.json").read_text())
    assert study["generator"] == "physics" and settings.SYNTHETIC_RANDOM_SEED not in study["dev_seeds"]
    assert study["selected"] == "sum_positive_z" == max(study["mean_auc"], key=lambda k: study["mean_auc"][k]["auc_all"])
