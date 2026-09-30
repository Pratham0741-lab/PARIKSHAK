"""
Module B: 24-Hour Early Drift Predictor for ISRO SIH26170.

Forecasts 168h parameter values from ONLY the 0h and 24h readings (plus lot-level context
derived from those two intervals). Feature construction lives in ml_engine/features.py and
refuses any 96h/168h-derived column.

Configurable (see ml_engine/module_b_config.json, chosen by `python -m evaluation.module_b_study`
with lot-grouped cross-validation):
  feature_set: "v1" | "v2"
  target:      "raw"       -> model predicts v168
               "drift"     -> model predicts v168 - v24          (forecast = v24 + yhat)
               "log_ratio" -> model predicts log(v168 / v24)     (forecast = v24 * exp(yhat))
  lgb_params:  LightGBM hyper-parameters
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

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

CONFIG_PATH = Path(__file__).with_name("module_b_config.json")
TARGETS = ("raw", "drift", "log_ratio")
# Quantile models for conformalised quantile regression (CQR). The nominal coverage of the final
# interval is set by the conformal step in ScreeningModel (INTERVAL_COVERAGE), not by these alphas.
QUANTILES = (0.05, 0.95)
SHORT = {"leakage_current_ua": "leakage", "iddq_ma": "iddq", "propagation_delay_ns": "delay"}
BASE_LGB_PARAMS: Dict[str, Any] = {"n_estimators": 100, "learning_rate": 0.05, "min_child_samples": 5}


def load_default_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return {"feature_set": cfg["feature_set"], "target": cfg["target"], "lgb_params": cfg["lgb_params"]}
    return {"feature_set": "v1", "target": "raw", "lgb_params": dict(BASE_LGB_PARAMS)}


def to_target(y168: np.ndarray, v24: np.ndarray, target: str) -> np.ndarray:
    if target == "raw":
        return y168
    if target == "drift":
        return y168 - v24
    if target == "log_ratio":
        return np.log(np.maximum(y168, 1e-6) / np.maximum(v24, 1e-6))
    raise ValueError(f"unknown target {target!r}")


def from_target(yhat: np.ndarray, v24: np.ndarray, target: str) -> np.ndarray:
    if target == "raw":
        return yhat
    if target == "drift":
        return v24 + yhat
    if target == "log_ratio":
        return v24 * np.exp(yhat)
    raise ValueError(f"unknown target {target!r}")


class DriftPredictor:
    """Early kinetic drift forecaster: (0h, 24h) -> 168h for each electrical parameter."""

    PARAMETERS = PARAMETERS

    def __init__(
        self,
        feature_set: Optional[str] = None,
        target: Optional[str] = None,
        lgb_params: Optional[Dict[str, Any]] = None,
        random_state: int = 42,
    ) -> None:
        default = load_default_config()
        self.feature_set = feature_set or default["feature_set"]
        self.target = target or default["target"]
        self.lgb_params = dict(lgb_params if lgb_params is not None else default["lgb_params"])
        self.random_state = random_state
        if self.target not in TARGETS:
            raise ValueError(f"target must be one of {TARGETS}")
        self.models_: Dict[str, lgb.LGBMRegressor] = {}
        self.quantile_models_: Dict[str, Dict[float, lgb.LGBMRegressor]] = {}
        self.feature_columns_: List[str] = []

    def config(self) -> Dict[str, Any]:
        return {"feature_set": self.feature_set, "target": self.target, "lgb_params": self.lgb_params}

    def _new_model(self, **overrides) -> lgb.LGBMRegressor:
        params = {**self.lgb_params, **overrides}
        return lgb.LGBMRegressor(
            random_state=self.random_state, deterministic=True, force_row_wise=True, n_jobs=1, verbose=-1, **params
        )

    def features(self, df: pd.DataFrame) -> pd.DataFrame:
        return build_early_features(df, self.feature_set)

    def fit(self, df: pd.DataFrame) -> "DriftPredictor":
        """Trains one regressor per parameter. `df` must contain 0h, 24h and 168h rows."""
        feats = self.features(df)
        targets = extract_targets(df)
        common = feats.index.intersection(targets.index)
        if len(common) == 0:
            raise ValueError("Training data must contain 0h, 24h and 168h readings.")
        feats = feats.loc[common]
        self.feature_columns_ = feature_columns(feats)
        X = feats[self.feature_columns_]
        assert_no_future_features(X.columns)
        for p in self.PARAMETERS:
            y = to_target(targets.loc[common, f"{p}_168"].to_numpy(float), feats[f"{p}_v24"].to_numpy(float), self.target)
            self.models_[p] = self._new_model().fit(X, y)
            self.quantile_models_[p] = {
                q: self._new_model(objective="quantile", alpha=q).fit(X, y) for q in QUANTILES
            }
        return self

    def predict_values(self, feats: pd.DataFrame) -> Dict[str, np.ndarray]:
        X = feats[self.feature_columns_]
        assert_no_future_features(X.columns)
        return {
            p: from_target(self.models_[p].predict(X), feats[f"{p}_v24"].to_numpy(float), self.target)
            for p in self.PARAMETERS
        }

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """168h forecasts for every part with complete 0h/24h readings (other intervals are ignored)."""
        if not self.models_:
            raise RuntimeError("DriftPredictor must be fitted before predict().")
        feats = self.features(df)
        preds = self.predict_values(feats)
        X = feats[self.feature_columns_]
        bounds = {}
        for p in self.PARAMETERS:
            v24 = feats[f"{p}_v24"].to_numpy(float)
            lo = from_target(self.quantile_models_[p][QUANTILES[0]].predict(X), v24, self.target)
            hi = from_target(self.quantile_models_[p][QUANTILES[1]].predict(X), v24, self.target)
            bounds[f"q_lo_{SHORT[p]}_168h"] = np.round(np.minimum(lo, hi), 4)  # guard against quantile crossing
            bounds[f"q_hi_{SHORT[p]}_168h"] = np.round(np.maximum(lo, hi), 4)
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
                **bounds,
            }
        )


def linear_extrapolation_baseline(df: pd.DataFrame) -> pd.DataFrame:
    """Naive physics-free baseline: v168 = v0 + 7 * (v24 - v0), from 0h/24h only."""
    feats = build_early_features(df)
    out = pd.DataFrame(index=feats.index)
    for p in PARAMETERS:
        out[f"{p}_168"] = feats[f"{p}_v0"] + 7.0 * (feats[f"{p}_v24"] - feats[f"{p}_v0"])
    return out
