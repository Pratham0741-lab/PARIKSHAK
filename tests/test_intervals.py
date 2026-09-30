"""Module B prediction intervals: conformalised quantile regression, per-part and computed coverage."""

from __future__ import annotations

import numpy as np
import pytest

from data_engine.generator import BurnInSyntheticGenerator
from evaluation.crossfit import cross_fit_predict, extract_truth
from evaluation.score import score
from ml_engine.screening import INTERVAL_COVERAGE, SHORT, ScreeningModel


@pytest.fixture(scope="module")
def crossfit():
    df = BurnInSyntheticGenerator(num_lots=6, components_per_lot=60, random_seed=21).generate_dataset()
    return df, cross_fit_predict(df, lambda: ScreeningModel(random_state=0), n_splits=3, seed=2)


def test_intervals_differ_across_parts(crossfit):
    _, cf = crossfit
    p = cf.predictions
    width = p["pi_hi_leakage_168h"] - p["pi_lo_leakage_168h"]
    assert (width > 0).all()
    assert width.nunique() > len(p) * 0.5  # per-part, not a constant band
    assert width.max() > 2 * width.min()
    assert ((p["pi_lo_leakage_168h"] <= p["pred_leakage_168h"]) & (p["pred_leakage_168h"] <= p["pi_hi_leakage_168h"])).mean() > 0.95


def test_conformal_correction_is_computed_from_validation_residuals(crossfit):
    _, cf = crossfit
    model = next(iter(cf.models.values()))
    conf = model.conformal_
    assert conf["calibrated"] and conf["coverage_target"] == INTERVAL_COVERAGE
    val = model.validation_
    for p, short in SHORT.items():
        y = val[f"true_{p}_168h"].to_numpy(float)
        e = np.maximum(val[f"q_lo_{short}_168h"] - y, y - val[f"q_hi_{short}_168h"]).to_numpy()
        n = len(e)
        level = min(1.0, np.ceil((n + 1) * INTERVAL_COVERAGE) / n)
        assert conf["q"][p] == pytest.approx(float(np.quantile(e, level, method="higher")))
        assert conf["n_calibration"][p] == n


def test_coverage_is_computed_not_assumed(crossfit):
    df, cf = crossfit
    truth = extract_truth(df)
    res = score(cf.predictions, truth)
    cov = res["regression"]["leakage_current_ua"]["interval"]["empirical_coverage"]

    j = cf.predictions.set_index("component_id").join(truth.drop(columns="lot_id"))
    manual = ((j["true_leakage_current_ua_168h"] >= j["pi_lo_leakage_168h"])
              & (j["true_leakage_current_ua_168h"] <= j["pi_hi_leakage_168h"])).mean()
    assert cov == pytest.approx(manual)
    assert 0.75 <= cov <= 1.0  # calibrated, loosely, on a small dataset

    # Moving the truth outside the intervals must lower the reported coverage.
    shifted = truth.copy()
    shifted["true_leakage_current_ua_168h"] += 1000.0
    assert score(cf.predictions, shifted)["regression"]["leakage_current_ua"]["interval"]["empirical_coverage"] == 0.0
