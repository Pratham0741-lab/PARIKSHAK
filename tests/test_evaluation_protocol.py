"""
Regression tests for the honest-evaluation protocol:
- no lot / part appears on both sides of a split, and models never see held-out parts;
- held-out predictions never receive 96h/168h readings or label columns;
- 96h/168h values can never reach the Module B feature matrix;
- scoring works from separate prediction and truth files.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from data_engine.generator import BurnInSyntheticGenerator
from evaluation import score as score_cli
from evaluation.crossfit import cross_fit_predict, extract_truth
from evaluation.splits import LotLeakageError, assert_disjoint, lot_group_kfold, lot_holdout_split
from ml_engine.features import FutureLeakageError, assert_no_future_features, build_early_features
from ml_engine.module_b_drift import DriftPredictor
from ml_engine.screening import LABEL_COLUMNS, ScreeningModel


@pytest.fixture(scope="module")
def small_dataset() -> pd.DataFrame:
    return BurnInSyntheticGenerator(num_lots=6, components_per_lot=40, random_seed=7).generate_dataset()


class SpyModel:
    """Wraps ScreeningModel and records exactly what fit/predict receive."""

    log: list = []

    def __init__(self):
        self.inner = ScreeningModel(random_state=0)

    def fit(self, df):
        SpyModel.log.append(("fit", set(df["component_id"]), set(df["lot_id"]), None))
        self.inner.fit(df)
        return self

    def predict(self, df):
        SpyModel.log.append(("predict", set(df["component_id"]), set(df["lot_id"]), df.copy()))
        return self.inner.predict(df)


def test_lot_group_kfold_is_a_partition_of_lots():
    lots = [f"L{i}" for i in range(11)]
    folds = lot_group_kfold(lots, n_splits=4, seed=3)
    seen = []
    for f in folds:
        assert not (f.train_lots & f.test_lots)
        assert f.train_lots | f.test_lots == set(lots)
        seen.extend(f.test_lots)
    assert sorted(seen) == sorted(lots)  # each lot tested exactly once
    assert lot_group_kfold(lots, 4, seed=3) == folds  # deterministic


def test_holdout_split_disjoint_and_guard_raises():
    f = lot_holdout_split([f"L{i}" for i in range(10)], test_fraction=0.3, seed=1)
    assert len(f.test_lots) == 3 and not (f.train_lots & f.test_lots)
    with pytest.raises(LotLeakageError):
        assert_disjoint({"A", "B"}, {"B", "C"})


def test_no_test_lot_part_ever_reaches_training(small_dataset):
    SpyModel.log = []
    res = cross_fit_predict(small_dataset, SpyModel, n_splits=3, seed=11)

    fits = [e for e in SpyModel.log if e[0] == "fit"]
    predicts = [e for e in SpyModel.log if e[0] == "predict"]
    assert len(fits) == len(predicts) == len(res.folds) == 3
    for rec, (_, fit_ids, fit_lots, _), (_, pred_ids, pred_lots, pred_df) in zip(res.folds, fits, predicts):
        # The model was trained on no part and no lot from the test fold.
        assert not (fit_ids & rec.test_component_ids)
        assert not (fit_lots & rec.test_lots)
        assert pred_lots <= rec.test_lots
        # What the model saw at prediction time: 0h/24h readings only, no label columns.
        assert set(pred_df["interval_hours"].unique()) <= {0, 24}
        assert not (set(pred_df.columns) & set(LABEL_COLUMNS))
    # Every part is predicted exactly once, by a model that never saw its lot.
    assert res.predictions["component_id"].is_unique
    assert len(res.predictions) == small_dataset["component_id"].nunique()


def test_future_columns_rejected_by_guard():
    with pytest.raises(FutureLeakageError):
        assert_no_future_features(["leakage_current_ua_v0", "leakage_current_ua_168"])
    with pytest.raises(FutureLeakageError):
        assert_no_future_features(["iddq_ma_96h"])
    assert_no_future_features(["leakage_current_ua_v24", "iddq_ma_delta"])


def test_future_values_cannot_influence_features_or_forecasts(small_dataset):
    df = small_dataset
    feats = build_early_features(df)
    assert_no_future_features(feats.columns)

    # Perturb every 96h/168h reading wildly: features and forecasts must not move.
    tampered = df.copy()
    late = tampered["interval_hours"].isin([96, 168])
    for p in ("leakage_current_ua", "iddq_ma", "propagation_delay_ns"):
        tampered.loc[late, p] = tampered.loc[late, p] * 1000.0 + 12345.0
    pd.testing.assert_frame_equal(feats, build_early_features(tampered))

    model = DriftPredictor(random_state=0).fit(df)
    assert_no_future_features(model.feature_columns_)
    p1 = model.predict(df).set_index("component_id")
    p2 = model.predict(tampered).set_index("component_id")
    p3 = model.predict(df[df["interval_hours"].isin([0, 24])]).set_index("component_id")
    pd.testing.assert_frame_equal(p1, p2)
    pd.testing.assert_frame_equal(p1, p3)


def test_score_cli_uses_separate_truth_file(small_dataset, tmp_path, capsys):
    res = cross_fit_predict(small_dataset, lambda: ScreeningModel(random_state=0), n_splits=3, seed=5)
    preds_csv, truth_csv, out_json = tmp_path / "p.csv", tmp_path / "t.csv", tmp_path / "m.json"
    res.predictions.to_csv(preds_csv, index=False)
    extract_truth(small_dataset).to_csv(truth_csv)

    assert score_cli.main(["--predictions", str(preds_csv), "--truth", str(truth_csv), "--json", str(out_json)]) == 0
    metrics = json.loads(out_json.read_text())
    d = metrics["detection"]
    y = small_dataset.drop_duplicates("component_id")["ground_truth_flag"].to_numpy()
    assert d["tp"] + d["fn"] == int(y.sum())
    assert d["n"] == len(y)
    assert "recall=" in capsys.readouterr().out
    # MAE is recomputable from the two files alone.
    t = pd.read_csv(truth_csv).set_index("component_id")
    p = pd.read_csv(preds_csv).set_index("component_id")
    mae = np.mean(np.abs(p["pred_leakage_168h"] - t.loc[p.index, "true_leakage_current_ua_168h"]))
    assert metrics["regression"]["leakage_current_ua"]["model"]["mae"] == pytest.approx(mae)
