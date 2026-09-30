"""
Module B: 24-Hour Early Drift Predictor for ISRO SIH26170.

Forecasts 168h parameter values from ONLY the 0h and 24h readings (plus lot-level context
derived from those two intervals). Feature construction lives in ml_engine/features.py and
refuses any 96h/168h-derived column.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import lightgbm as lgb
import numpy as np
import pandas as pd

from ml_engine.features import (
    PARAMETERS,
    assert_no_future_features,
    build_early_features,
    extract_targets,
    feature_columns,
)

logger = logging.getLogger(__name__)


class DriftPredictor:
    """Early kinetic drift forecaster: (0h, 24h) -> 168h for each electrical parameter."""

    PARAMETERS = PARAMETERS

    def __init__(self, n_estimators: int = 100, learning_rate: float = 0.05, random_state: int = 42) -> None:
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.random_state = random_state
        self.models_: Dict[str, lgb.LGBMRegressor] = {}
        self.feature_columns_: List[str] = []

    def _new_model(self) -> lgb.LGBMRegressor:
        return lgb.LGBMRegressor(
            n_estimators=self.n_estimators,
            learning_rate=self.learning_rate,
            random_state=self.random_state,
            min_child_samples=5,
            deterministic=True,
            force_row_wise=True,
            n_jobs=1,
            verbose=-1,
        )

    def fit(self, df: pd.DataFrame) -> "DriftPredictor":
        """Trains one regressor per parameter. `df` must contain 0h, 24h and 168h rows."""
        feats = build_early_features(df)
        targets = extract_targets(df)
        common = feats.index.intersection(targets.index)
        if len(common) == 0:
            raise ValueError("Training data must contain 0h, 24h and 168h readings.")
        feats = feats.loc[common]
        self.feature_columns_ = feature_columns(feats)
        X = feats[self.feature_columns_]
        assert_no_future_features(X.columns)
        for p in self.PARAMETERS:
            self.models_[p] = self._new_model().fit(X, targets.loc[common, f"{p}_168"])
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """168h forecasts for every part with complete 0h/24h readings (other intervals are ignored)."""
        if not self.models_:
            raise RuntimeError("DriftPredictor must be fitted before predict().")
        feats = build_early_features(df)
        X = feats[self.feature_columns_]
        assert_no_future_features(X.columns)

        preds = {p: self.models_[p].predict(X) for p in self.PARAMETERS}
        leak_0 = feats["leakage_current_ua_v0"].to_numpy()
        # Predicted 168h drift rate of leakage current (uA/hr), from 0h to the 168h forecast.
        drift_slope = (preds["leakage_current_ua"] - leak_0) / 168.0
        return pd.DataFrame(
            {
                "component_id": feats.index.to_numpy(),
                "pred_leakage_168h": np.round(preds["leakage_current_ua"], 4),
                "pred_iddq_168h": np.round(preds["iddq_ma"], 4),
                "pred_delay_168h": np.round(preds["propagation_delay_ns"], 4),
                "drift_slope_ua_per_hr": np.round(drift_slope, 5),
            }
        )


def linear_extrapolation_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """Naive physics-free baseline: v168 = v0 + 7 * (v24 - v0), from 0h/24h only."""
    feats = build_early_features(df)
    out = pd.DataFrame(index=feats.index)
    for p in PARAMETERS:
        out[f"{p}_168"] = feats[f"{p}_v0"] + 7.0 * (feats[f"{p}_v24"] - feats[f"{p}_v0"])
    return out
