"""
Module B: 24-Hour Early Drift Predictor for ISRO SIH26170.
Forecasts 168-hour end-of-screening parameter values using ONLY 0h and 24h readings,
employing LightGBM gradient boosted regressors and evaluating against linear extrapolators.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)


class DriftPredictor:
    """
    Early kinetic drift forecaster for semiconductor burn-in screening.
    Takes early measurements at t=0h and t=24h and predicts parameter degradation at t=168h.
    """

    PARAMETERS: Tuple[str, ...] = (
        "leakage_current_ua",
        "iddq_ma",
        "propagation_delay_ns",
    )

    # Thresholds for triggering drift flag
    DEFAULT_LEAKAGE_DRIFT_THRESHOLD_UA: float = 35.0
    DEFAULT_DRIFT_SLOPE_THRESHOLD_UA_HR: float = 0.12
    DEFAULT_DATASHEET_LEAKAGE_MAX: float = 50.0
    DEFAULT_DATASHEET_IDDQ_MAX: float = 5.0
    DEFAULT_DATASHEET_DELAY_MAX: float = 8.0

    def __init__(
        self,
        leakage_threshold_ua: float = DEFAULT_LEAKAGE_DRIFT_THRESHOLD_UA,
        slope_threshold_ua_hr: float = DEFAULT_DRIFT_SLOPE_THRESHOLD_UA_HR,
        n_estimators: int = 100,
        learning_rate: float = 0.05,
        random_state: int = 42,
    ) -> None:
        """
        Initialize the Drift Predictor.

        Args:
            leakage_threshold_ua: Absolute predicted leakage at 168h triggering warning.
            slope_threshold_ua_hr: Projected drift rate (uA/hr) indicating runaway kinetics.
            n_estimators: Trees in LightGBM regressors.
            learning_rate: Step size shrinkage for LightGBM.
            random_state: Seed for deterministic model training.
        """
        self.leakage_threshold_ua = leakage_threshold_ua
        self.slope_threshold_ua_hr = slope_threshold_ua_hr
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.random_state = random_state

        # Trained LightGBM models for each parameter
        self.models_: Dict[str, lgb.LGBMRegressor] = {}
        self.feature_columns_: List[str] = []
        self.lot_medians_24h_: Dict[Any, Dict[str, float]] = {}

    def _extract_and_engineer_features(
        self, df: pd.DataFrame
    ) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
        """
        Extracts 0h and 24h measurements and engineers kinetic and lot-relative features.
        If 168h measurements exist, returns targets (Y) as well.
        """
        df_0 = df[df["interval_hours"] == 0].set_index("component_id")
        df_24 = df[df["interval_hours"] == 24].set_index("component_id")

        common_ids = df_0.index.intersection(df_24.index)
        if len(common_ids) == 0:
            raise ValueError("No matching components with both 0h and 24h readings.")

        features: List[Dict[str, Any]] = []
        targets: List[Dict[str, Any]] = []

        has_168 = 168 in df["interval_hours"].values
        df_168 = df[df["interval_hours"] == 168].set_index("component_id") if has_168 else None

        for cid in common_ids:
            r0 = df_0.loc[cid]
            r24 = df_24.loc[cid]

            feat: Dict[str, Any] = {
                "component_id": cid,
                "lot_id": r0["lot_id"] if "lot_id" in r0 else "DEFAULT_LOT",
            }

            for p in self.PARAMETERS:
                v0 = float(r0[p])
                v24 = float(r24[p])
                delta = v24 - v0
                ratio = v24 / (v0 + 1e-6)
                slope24 = delta / 24.0

                feat[f"{p}_0"] = v0
                feat[f"{p}_24"] = v24
                feat[f"{p}_delta"] = delta
                feat[f"{p}_ratio"] = ratio
                feat[f"{p}_slope24"] = slope24

            features.append(feat)

            if df_168 is not None and cid in df_168.index:
                r168 = df_168.loc[cid]
                targ: Dict[str, Any] = {"component_id": cid}
                for p in self.PARAMETERS:
                    targ[f"{p}_168"] = float(r168[p])
                targets.append(targ)

        feat_df = pd.DataFrame(features).set_index("component_id")

        # Lot-relative 24h distance and delta
        for lot_id, lot_rows in feat_df.groupby("lot_id"):
            for p in self.PARAMETERS:
                med24 = float(lot_rows[f"{p}_24"].median())
                med_delta = float(lot_rows[f"{p}_delta"].median())
                feat_df.loc[lot_rows.index, f"{p}_lot_dist24"] = lot_rows[f"{p}_24"] - med24
                feat_df.loc[lot_rows.index, f"{p}_lot_delta"] = lot_rows[f"{p}_delta"] - med_delta

        target_df = pd.DataFrame(targets).set_index("component_id") if targets else None
        return feat_df, target_df

    def fit(self, df: pd.DataFrame) -> "DriftPredictor":
        """
        Trains LightGBM regression models for each parameter to forecast 168h values.

        Args:
            df: Historical/training dataset containing 0h, 24h, and 168h readings.
        """
        feat_df, target_df = self._extract_and_engineer_features(df)
        if target_df is None or len(target_df) == 0:
            raise ValueError("Training data must contain 168h readings to fit regression targets.")

        # Identify numerical feature columns
        self.feature_columns_ = [
            c for c in feat_df.columns if c != "lot_id"
        ]

        X = feat_df[self.feature_columns_]

        for p in self.PARAMETERS:
            target_col = f"{p}_168"
            y = target_df.loc[feat_df.index, target_col]

            model = lgb.LGBMRegressor(
                n_estimators=self.n_estimators,
                learning_rate=self.learning_rate,
                random_state=self.random_state,
                verbose=-1,
                min_child_samples=5,
            )
            model.fit(X, y)
            self.models_[p] = model

        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Generates 168h forecasts and kinetic drift metrics for components.

        Returns:
            pd.DataFrame: DataFrame indexed by component_id with:
                - pred_leakage_168h
                - pred_iddq_168h
                - pred_delay_168h
                - drift_slope_ua_per_hr
                - module_b_flag
        """
        if not self.models_:
            raise RuntimeError("DriftPredictor must be fitted before predict().")

        feat_df, _ = self._extract_and_engineer_features(df)
        X = feat_df[self.feature_columns_]

        predictions: Dict[str, np.ndarray] = {}
        for p in self.PARAMETERS:
            predictions[p] = self.models_[p].predict(X)

        # Implied drift slope for leakage current (uA/hr) between 0h and predicted 168h
        leak_0 = feat_df["leakage_current_ua_0"].values
        pred_leak_168 = predictions["leakage_current_ua"]
        drift_slope = (pred_leak_168 - leak_0) / 168.0

        pred_iddq_168 = predictions["iddq_ma"]
        pred_delay_168 = predictions["propagation_delay_ns"]

        # Flag rule: predicted 168h value crosses safety threshold or high drift rate
        module_b_flag = (
            (pred_leak_168 >= self.leakage_threshold_ua)
            | (drift_slope >= self.slope_threshold_ua_hr)
            | (pred_leak_168 >= self.DEFAULT_DATASHEET_LEAKAGE_MAX)
            | (pred_iddq_168 >= self.DEFAULT_DATASHEET_IDDQ_MAX)
            | (pred_delay_168 >= self.DEFAULT_DATASHEET_DELAY_MAX)
        )

        return pd.DataFrame(
            {
                "component_id": feat_df.index,
                "pred_leakage_168h": np.round(pred_leak_168, 4),
                "pred_iddq_168h": np.round(pred_iddq_168, 4),
                "pred_delay_168h": np.round(pred_delay_168, 4),
                "drift_slope_ua_per_hr": np.round(drift_slope, 5),
                "module_b_flag": module_b_flag,
            }
        ).reset_index(drop=True)

    def evaluate_against_linear_baseline(
        self, df: pd.DataFrame, test_size: float = 0.3
    ) -> Dict[str, Any]:
        """
        Evaluates the LightGBM model against a linear extrapolation baseline.

        Linear Extrapolator Formulation:
            v_168_linear = v_0 + (v_24 - v_0) * (168 / 24) = v_0 + 7 * (v_24 - v_0)

        Returns:
            Dict containing MAE and RMSE metrics for both models across parameters.
        """
        feat_df, target_df = self._extract_and_engineer_features(df)
        if target_df is None:
            raise ValueError("Evaluation requires true 168h target readings.")

        # Train/test split
        X = feat_df[self.feature_columns_]
        train_idx, test_idx = train_test_split(
            feat_df.index, test_size=test_size, random_state=self.random_state
        )

        X_train, X_test = X.loc[train_idx], X.loc[test_idx]
        metrics: Dict[str, Any] = {}

        for p in self.PARAMETERS:
            y_train = target_df.loc[train_idx, f"{p}_168"]
            y_test = target_df.loc[test_idx, f"{p}_168"]

            # Train temporary model on train split
            eval_model = lgb.LGBMRegressor(
                n_estimators=self.n_estimators,
                learning_rate=self.learning_rate,
                random_state=self.random_state,
                verbose=-1,
                min_child_samples=5,
            )
            eval_model.fit(X_train, y_train)
            lgb_preds = eval_model.predict(X_test)

            # Linear extrapolation baseline
            v0 = X_test[f"{p}_0"]
            v24 = X_test[f"{p}_24"]
            linear_preds = v0 + 7.0 * (v24 - v0)

            lgb_mae = float(mean_absolute_error(y_test, lgb_preds))
            linear_mae = float(mean_absolute_error(y_test, linear_preds))
            lgb_rmse = float(root_mean_squared_error(y_test, lgb_preds))
            linear_rmse = float(root_mean_squared_error(y_test, linear_preds))
            improvement_pct = ((linear_mae - lgb_mae) / linear_mae) * 100.0

            metrics[p] = {
                "lightgbm_mae": round(lgb_mae, 4),
                "linear_mae": round(linear_mae, 4),
                "lightgbm_rmse": round(lgb_rmse, 4),
                "linear_rmse": round(linear_rmse, 4),
                "mae_improvement_pct": round(improvement_pct, 2),
            }

        return metrics
