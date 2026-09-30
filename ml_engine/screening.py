"""
End-to-end screening model: Module A + Module B + verdict layer.

`fit` receives training lots (all intervals + labels). `predict` receives ONLY what is
available at the 24h checkpoint: it strips every non-early reading and every label column
before anything is computed, so held-out ground truth cannot influence a prediction.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from ml_engine.features import EARLY_INTERVALS, PARAMETERS
from ml_engine.module_a_outlier import LotOutlierDetector
from ml_engine.module_b_drift import DriftPredictor
from ml_engine.verdict_engine import ScreeningVerdictEngine

READING_COLUMNS = ["component_id", "lot_id", "interval_hours", *PARAMETERS]
LABEL_COLUMNS = ("ground_truth_label", "ground_truth_flag", "is_datasheet_breached", "is_benign_high_lot")

DATASHEET_LIMITS = {
    "leakage_current_ua": ScreeningVerdictEngine.DATASHEET_LEAKAGE_MAX_UA,
    "iddq_ma": ScreeningVerdictEngine.DATASHEET_IDDQ_MAX_MA,
    "propagation_delay_ns": ScreeningVerdictEngine.DATASHEET_DELAY_MAX_NS,
}


def early_readings_only(df: pd.DataFrame, intervals: Iterable[int] = EARLY_INTERVALS) -> pd.DataFrame:
    """Readings visible at the 24h checkpoint, with every label/ground-truth column removed."""
    out = df[df["interval_hours"].isin(tuple(intervals))]
    return out[[c for c in READING_COLUMNS if c in out.columns]].copy()


def observed_static_breach(early: pd.DataFrame) -> pd.Series:
    """Static datasheet-limit check on the readings actually observed so far (0h/24h)."""
    breach = pd.Series(False, index=early["component_id"].unique())
    for p, limit in DATASHEET_LIMITS.items():
        hit = early.loc[early[p] > limit, "component_id"].unique()
        breach.loc[hit] = True
    return breach


class ScreeningModel:
    def __init__(self, module_a_threshold: float = LotOutlierDetector.DEFAULT_THRESHOLD, random_state: int = 42):
        self.module_a = LotOutlierDetector(threshold=module_a_threshold, random_state=random_state)
        self.module_b = DriftPredictor(random_state=random_state)
        self.verdict_engine = ScreeningVerdictEngine()
        self.training_component_ids_: frozenset = frozenset()
        self.training_lot_ids_: frozenset = frozenset()

    def fit(self, train_df: pd.DataFrame) -> "ScreeningModel":
        self.training_component_ids_ = frozenset(train_df["component_id"].unique())
        self.training_lot_ids_ = frozenset(train_df["lot_id"].unique())
        # Module A is unsupervised and early-only; Module B needs the 168h targets of TRAINING lots.
        self.module_a.fit(early_readings_only(train_df))
        self.module_b.fit(train_df[[c for c in READING_COLUMNS if c in train_df.columns]])
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        early = early_readings_only(df)
        res_a = self.module_a.predict(early)
        res_b = self.module_b.predict(early)
        merged = res_a.merge(res_b, on="component_id", how="inner")
        breach = observed_static_breach(early)
        merged["observed_static_breach"] = merged["component_id"].map(breach).fillna(False).astype(bool)
        out = self.verdict_engine.evaluate_dataframe(merged)
        out["screen_flag"] = out["verdict"].isin(["REVIEW", "REJECT"])
        return out
