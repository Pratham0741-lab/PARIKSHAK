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
from ml_engine.verdict_engine import PRED_COLUMN, ScreeningVerdictEngine

READING_COLUMNS = ["component_id", "lot_id", "interval_hours", *PARAMETERS]
LABEL_COLUMNS = ("ground_truth_label", "ground_truth_flag", "is_datasheet_breached", "is_benign_high_lot")
DATASHEET_LIMITS = ScreeningVerdictEngine.datasheet_limits()

# Cold-start defaults, used only if a model is asked to predict before thresholds are learned.
COLD_START_THRESHOLDS = {"threshold_a": LotOutlierDetector.DEFAULT_THRESHOLD, "threshold_b": 0.12}


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

    # ------------------------------------------------------------------ scoring
    def _scores(self, early: pd.DataFrame, module_a: LotOutlierDetector, module_b: DriftPredictor) -> pd.DataFrame:
        res_a = module_a.predict(early)
        res_b = module_b.predict(early)
        merged = res_a.merge(res_b, on="component_id", how="inner")
        merged["module_b_score"] = merged["drift_slope_ua_per_hr"]
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
        a = LotOutlierDetector(random_state=self.random_state).fit(early_readings_only(df))
        b = DriftPredictor(random_state=self.random_state).fit(df[[c for c in READING_COLUMNS if c in df.columns]])
        return a, b

    def validation_scores(self, train_df: pd.DataFrame) -> pd.DataFrame:
        """Out-of-fold scores over the training lots (inner lot-grouped CV)."""
        lots = train_df["lot_id"].astype(str).unique()
        k = min(self.inner_splits, len(lots))
        frames = []
        for f in lot_group_kfold(lots, n_splits=k, seed=self.random_state):
            inner_train = train_df[train_df["lot_id"].astype(str).isin(f.train_lots)]
            inner_val = train_df[train_df["lot_id"].astype(str).isin(f.test_lots)]
            assert_disjoint(set(inner_train["component_id"]), set(inner_val["component_id"]), what="component")
            a, b = self._fit_modules(inner_train)
            frames.append(self._scores(early_readings_only(inner_val), a, b))
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

        self.module_a, self.module_b = self._fit_modules(train_df)
        return self

    # ------------------------------------------------------------------ predict
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        early = early_readings_only(df)
        scored = self._scores(early, self.module_a, self.module_b)
        ta, tb = self.thresholds_["threshold_a"], self.thresholds_["threshold_b"]
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
                "n_training_lots": len(self.training_lot_ids_),
                "n_training_parts": len(self.training_component_ids_)}
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "ScreeningModel":
        return joblib.load(Path(path))
