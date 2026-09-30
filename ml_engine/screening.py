"""
End-to-end screening model: Module A + Module B + verdict layer.

`fit(train_df)` receives training lots (all intervals + labels) and:
  1. runs an inner GroupKFold over the TRAINING lots to obtain out-of-fold validation scores;
  2. chooses the Module A / Module B decision thresholds by FN-weighted cost minimisation on
     those validation scores (evaluation/thresholds.py);
  3. refits both modules on all training lots.
`predict(df)` receives ONLY what is available at the 24h checkpoint: every non-early reading
and every label column is stripped before anything is computed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import joblib
import numpy as np
import pandas as pd

from evaluation.cost import CostConfig
from evaluation.splits import assert_disjoint, lot_group_kfold
from evaluation.thresholds import choose_union_thresholds
from ml_engine.features import EARLY_INTERVALS, PARAMETERS
from ml_engine.module_a_outlier import LotOutlierDetector
from ml_engine.module_b_drift import DriftPredictor
from ml_engine.safety_slope import COLD_START_K, drift_rates, lot_statistics, safety_slopes, spread_floors
from ml_engine.verdict_engine import PRED_COLUMN, ScreeningVerdictEngine

READING_COLUMNS = ["component_id", "lot_id", "interval_hours", *PARAMETERS]
LABEL_COLUMNS = ("ground_truth_label", "ground_truth_flag", "is_datasheet_breached", "is_benign_high_lot")
DATASHEET_LIMITS = ScreeningVerdictEngine.datasheet_limits()

# Cold-start defaults, used only if a model is asked to predict before thresholds are learned.
COLD_START_THRESHOLDS = {"threshold_a": LotOutlierDetector.DEFAULT_THRESHOLD, "threshold_b": COLD_START_K}


def early_readings_only(df: pd.DataFrame, intervals: Iterable[int] = EARLY_INTERVALS) -> pd.DataFrame:
    """Readings visible at the 24h checkpoint, with every label/ground-truth column removed."""
    out = df[df["interval_hours"].isin(tuple(intervals))]
    return out[[c for c in READING_COLUMNS if c in out.columns]].copy()


def observed_static_breach(early: pd.DataFrame) -> pd.Series:
    """Static datasheet-limit check on the readings actually observed so far (0h/24h)."""
    breach = pd.Series(False, index=early["component_id"].unique())
    for p, limit in DATASHEET_LIMITS.items():
        breach.loc[early.loc[early[p] > limit, "component_id"].unique()] = True
    return breach


class ScreeningModel:
    def __init__(self, cost: Optional[CostConfig] = None, random_state: int = 42, inner_splits: int = 4):
        self.cost = cost or CostConfig()
        self.random_state = random_state
        self.inner_splits = inner_splits
        self.module_a = LotOutlierDetector(random_state=random_state)
        self.module_b = DriftPredictor(random_state=random_state)
        self.verdict_engine = ScreeningVerdictEngine()
        self.thresholds_: Dict[str, Any] = dict(COLD_START_THRESHOLDS, source="cold_start_default")
        self.training_component_ids_: frozenset = frozenset()
        self.training_lot_ids_: frozenset = frozenset()
        self.spread_floors_: Dict[str, float] = {}

    # ------------------------------------------------------------------ scoring
    @staticmethod
    def _v0(early: pd.DataFrame) -> pd.DataFrame:
        return early[early["interval_hours"] == 0][["component_id", *PARAMETERS]].drop_duplicates("component_id")

    def _scores(self, early: pd.DataFrame, module_a: LotOutlierDetector, module_b: DriftPredictor,
                floors: Dict[str, float]) -> pd.DataFrame:
        res_a = module_a.predict(early)
        res_b = module_b.predict(early)
        merged = res_a.merge(res_b, on="component_id", how="inner")
        # Module B decision score: lot-relative robust z of the predicted drift rate (max over parameters).
        stats = lot_statistics(drift_rates(merged, self._v0(early)), floors)
        merged = merged.merge(stats.drop(columns=["lot_id"]), on="component_id", how="left")
        breach = observed_static_breach(early)
        merged["observed_static_breach"] = merged["component_id"].map(breach).fillna(False).astype(bool)
        pred_breach = np.zeros(len(merged), dtype=bool)
        for p, lim in DATASHEET_LIMITS.items():
            pred_breach |= merged[PRED_COLUMN[p]].to_numpy() >= lim
        merged["predicted_limit_breach"] = pred_breach
        return merged

    @staticmethod
    def _labels(train_df: pd.DataFrame) -> pd.Series:
        meta = train_df.drop_duplicates("component_id").set_index("component_id")
        return meta["ground_truth_flag"].astype(bool)

    # ------------------------------------------------------------------ fit
    def _fit_modules(self, df: pd.DataFrame):
        early = early_readings_only(df)
        a = LotOutlierDetector(random_state=self.random_state).fit(early)
        b = DriftPredictor(random_state=self.random_state).fit(df[[c for c in READING_COLUMNS if c in df.columns]])
        # Spread floors for the safety slope come from the TRAINING lots' predicted drift rates.
        pred = b.predict(early).merge(a.predict(early)[["component_id", "lot_id"]], on="component_id")
        floors = spread_floors(drift_rates(pred, self._v0(early)))
        return a, b, floors

    def validation_scores(self, train_df: pd.DataFrame) -> pd.DataFrame:
        """Out-of-fold scores over the training lots (inner lot-grouped CV)."""
        lots = train_df["lot_id"].astype(str).unique()
        k = min(self.inner_splits, len(lots))
        frames = []
        for f in lot_group_kfold(lots, n_splits=k, seed=self.random_state):
            inner_train = train_df[train_df["lot_id"].astype(str).isin(f.train_lots)]
            inner_val = train_df[train_df["lot_id"].astype(str).isin(f.test_lots)]
            assert_disjoint(set(inner_train["component_id"]), set(inner_val["component_id"]), what="component")
            a, b, floors = self._fit_modules(inner_train)
            frames.append(self._scores(early_readings_only(inner_val), a, b, floors))
        val = pd.concat(frames, ignore_index=True)
        val["y"] = val["component_id"].map(self._labels(train_df)).astype(bool)
        return val

    def fit(self, train_df: pd.DataFrame) -> "ScreeningModel":
        self.training_component_ids_ = frozenset(train_df["component_id"].astype(str).unique())
        self.training_lot_ids_ = frozenset(train_df["lot_id"].astype(str).unique())

        if "ground_truth_flag" in train_df.columns and len(self.training_lot_ids_) >= 2:
            val = self.validation_scores(train_df)
            chosen = choose_union_thresholds(
                val["module_a_score"], val["module_b_score"], val["y"], self.cost,
                forced=val["observed_static_breach"] | val["predicted_limit_breach"],
            )
            self.thresholds_ = {**chosen, "source": "cost_minimised_on_inner_oof_validation",
                                "n_validation_lots": len(self.training_lot_ids_)}

        self.module_a, self.module_b, self.spread_floors_ = self._fit_modules(train_df)
        return self

    # ------------------------------------------------------------------ predict
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        early = early_readings_only(df)
        scored = self._scores(early, self.module_a, self.module_b, self.spread_floors_)
        ta, tb = self.thresholds_["threshold_a"], self.thresholds_["threshold_b"]
        scored = scored.merge(safety_slopes(scored, tb), on="component_id", how="left")
        scored["module_a_flag"] = scored["module_a_score"] >= ta
        scored["module_b_flag"] = (scored["module_b_score"] >= tb) | scored["predicted_limit_breach"]
        scored["threshold_a"] = ta
        scored["threshold_b"] = tb
        out = self.verdict_engine.evaluate_dataframe(scored, ta, tb)
        out["screen_flag"] = out["verdict"].isin(["REVIEW", "REJECT"])
        return out

    # ------------------------------------------------------------------ persistence
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        meta = {"thresholds": self.thresholds_, "cost_config": self.cost.as_dict(),
                "safety_slope_spread_floors": self.spread_floors_,
                "n_training_lots": len(self.training_lot_ids_),
                "n_training_parts": len(self.training_component_ids_)}
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "ScreeningModel":
        return joblib.load(Path(path))


def _num(x):
    x = float(x)
    return None if not np.isfinite(x) else round(x, 6)


def prediction_details(row) -> Dict[str, Any]:
    """JSON-safe per-part derivations persisted with each prediction (row = one predict() output row)."""
    from ml_engine.safety_slope import RATE_UNITS

    k = float(row["threshold_b"])
    drift = {}
    for p in PARAMETERS:
        drift[p] = {
            "predicted_rate": _num(row[f"rate_{p}"]),
            "lot_median_rate": _num(row[f"lot_median_{p}"]),
            "lot_spread": _num(row[f"lot_spread_{p}"]),
            "z": _num(row[f"z_{p}"]),
            "safety_slope": _num(row[f"safety_slope_{p}"]),
            "exceeds_safety_slope": bool(np.isfinite(k) and row[f"rate_{p}"] >= row[f"safety_slope_{p}"]),
            "unit": RATE_UNITS[p],
        }
    return {
        "safety_slope": {
            "rule": "safety_slope = lot median of predicted drift rate + k * max(1.4826*MAD, floor)",
            "k": _num(k),
            "driver_parameter": str(row["module_b_driver"]),
            "per_parameter": drift,
        },
    }
