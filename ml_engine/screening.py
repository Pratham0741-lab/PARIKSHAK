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
from evaluation.thresholds import choose_thresholds
from ml_engine.features import EARLY_INTERVALS, PARAMETERS
from ml_engine.module_a_outlier import LotOutlierDetector
from ml_engine.module_b_drift import DriftPredictor
from ml_engine.safety_slope import COLD_START_K, drift_rates, lot_statistics, safety_slopes, spread_floors
from ml_engine.verdict_engine import PRED_COLUMN, ScreeningVerdictEngine

READING_COLUMNS = ["component_id", "lot_id", "interval_hours", *PARAMETERS]
LABEL_COLUMNS = ("ground_truth_label", "ground_truth_flag", "is_datasheet_breached", "is_benign_high_lot")
DATASHEET_LIMITS = ScreeningVerdictEngine.datasheet_limits()
# Conformalised quantile regression: target coverage of the Module B prediction interval.
INTERVAL_COVERAGE = 0.90
SHORT = {"leakage_current_ua": "leakage", "iddq_ma": "iddq", "propagation_delay_ns": "delay"}

# Defect types Module B's safety-slope rule is responsible for (used only to calibrate k on training lots).
MODULE_B_TARGET_CLASSES = ("STEEP_DRIFT", "LATE_DRIFT")

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
    def __init__(self, cost: Optional[CostConfig] = None, random_state: int = 42, inner_splits: int = 4,
                 threshold_strategy: str = "separate"):
        self.cost = cost or CostConfig()
        self.threshold_strategy = threshold_strategy
        self.random_state = random_state
        self.inner_splits = inner_splits
        self.module_a = LotOutlierDetector(random_state=random_state)
        self.module_b = DriftPredictor(random_state=random_state)
        self.verdict_engine = ScreeningVerdictEngine()
        self.thresholds_: Dict[str, Any] = dict(COLD_START_THRESHOLDS, source="cold_start_default")
        self.training_component_ids_: frozenset = frozenset()
        self.training_lot_ids_: frozenset = frozenset()
        self.spread_floors_: Dict[str, float] = {}
        self.conformal_: Dict[str, Any] = {"calibrated": False, "coverage_target": INTERVAL_COVERAGE,
                                           "q": {p: 0.0 for p in PARAMETERS}}
        self.validation_: Optional[pd.DataFrame] = None

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
            sc = self._scores(early_readings_only(inner_val), a, b, floors)
            t168 = inner_val[inner_val["interval_hours"] == 168].set_index("component_id")
            for p in PARAMETERS:
                sc[f"true_{p}_168h"] = sc["component_id"].map(t168[p]) if p in t168 else np.nan
            frames.append(sc)
        val = pd.concat(frames, ignore_index=True)
        val["y"] = val["component_id"].map(self._labels(train_df)).astype(bool)
        if "ground_truth_label" in train_df.columns:
            labels = train_df.drop_duplicates("component_id").set_index("component_id")["ground_truth_label"]
            val["label"] = val["component_id"].map(labels).astype(str)
        return val

    def fit(self, train_df: pd.DataFrame) -> ScreeningModel:
        self.training_component_ids_ = frozenset(train_df["component_id"].astype(str).unique())
        self.training_lot_ids_ = frozenset(train_df["lot_id"].astype(str).unique())

        if "ground_truth_flag" in train_df.columns and len(self.training_lot_ids_) >= 2:
            val = self.validation_scores(train_df)
            chosen = choose_thresholds(
                val["module_a_score"], val["module_b_score"], val["y"], self.cost,
                forced=val["observed_static_breach"] | val["predicted_limit_breach"],
                strategy=self.threshold_strategy,
                b_scope=(val["label"].isin(MODULE_B_TARGET_CLASSES) | ~val["y"]) if "label" in val else None,
                b_positive=val["label"].isin(MODULE_B_TARGET_CLASSES) if "label" in val else None,
            )
            self.thresholds_ = {**chosen, "source": "cost_minimised_on_inner_oof_validation",
                                "n_validation_lots": len(self.training_lot_ids_)}
            self.conformal_ = self._calibrate_intervals(val)
            self.validation_ = val

        self.module_a, self.module_b, self.spread_floors_ = self._fit_modules(train_df)
        return self

    @staticmethod
    def _calibrate_intervals(val: pd.DataFrame) -> Dict[str, Any]:
        """Split-conformal correction for the quantile interval (CQR), from inner out-of-fold residuals."""
        alpha = 1.0 - INTERVAL_COVERAGE
        q, n_cal = {}, {}
        for p in PARAMETERS:
            y = val[f"true_{p}_168h"].to_numpy(float)
            lo = val[f"q_lo_{SHORT[p]}_168h"].to_numpy(float)
            hi = val[f"q_hi_{SHORT[p]}_168h"].to_numpy(float)
            ok = ~np.isnan(y)
            e = np.maximum(lo[ok] - y[ok], y[ok] - hi[ok])  # conformity score
            n = len(e)
            level = min(1.0, np.ceil((n + 1) * (1 - alpha)) / n) if n else 1.0
            q[p] = float(np.quantile(e, level, method="higher")) if n else 0.0
            n_cal[p] = int(n)
        return {"calibrated": True, "method": "CQR (LightGBM 5%/95% quantiles + split-conformal on inner OOF)",
                "coverage_target": INTERVAL_COVERAGE, "q": q, "n_calibration": n_cal}

    def rethreshold(self, strategy: str) -> ScreeningModel:
        """Copy of this model with thresholds re-chosen from the stored validation scores (no refit)."""
        import copy

        if self.validation_ is None:
            raise RuntimeError("model has no stored validation scores")
        m = copy.copy(self)
        m.threshold_strategy = strategy
        val = self.validation_
        chosen = choose_thresholds(
            val["module_a_score"], val["module_b_score"], val["y"], self.cost,
            forced=val["observed_static_breach"] | val["predicted_limit_breach"], strategy=strategy,
            b_scope=(val["label"].isin(MODULE_B_TARGET_CLASSES) | ~val["y"]) if "label" in val else None,
            b_positive=val["label"].isin(MODULE_B_TARGET_CLASSES) if "label" in val else None,
        )
        m.thresholds_ = {**chosen, "source": "cost_minimised_on_inner_oof_validation",
                         "n_validation_lots": len(self.training_lot_ids_)}
        return m

    # ------------------------------------------------------------------ predict
    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        early = early_readings_only(df)
        scored = self._scores(early, self.module_a, self.module_b, self.spread_floors_)
        ta, tb = self.thresholds_["threshold_a"], self.thresholds_["threshold_b"]
        scored = scored.merge(safety_slopes(scored, tb), on="component_id", how="left")
        for p in PARAMETERS:
            qp = self.conformal_["q"][p]
            scored[f"pi_lo_{SHORT[p]}_168h"] = (scored[f"q_lo_{SHORT[p]}_168h"] - qp).round(4)
            scored[f"pi_hi_{SHORT[p]}_168h"] = (scored[f"q_hi_{SHORT[p]}_168h"] + qp).round(4)
        scored["module_a_flag"] = scored["module_a_score"] >= ta
        scored["module_b_flag"] = (scored["module_b_score"] >= tb) | scored["predicted_limit_breach"]
        scored["threshold_a"] = ta
        scored["threshold_b"] = tb
        out = self.verdict_engine.evaluate_dataframe(scored, ta, tb)
        out["screen_flag"] = out["verdict"].isin(["REVIEW", "REJECT"])
        feats = self.module_b.features(early)
        contrib = dict(zip(feats.index.astype(str), self.module_b.contributions(feats), strict=False))
        out["b_contributions"] = out["component_id"].astype(str).map(contrib)
        return out

    # ------------------------------------------------------------------ persistence
    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)
        meta = {"thresholds": self.thresholds_, "cost_config": self.cost.as_dict(),
                "safety_slope_spread_floors": self.spread_floors_,
                "prediction_interval": self.conformal_,
                "n_training_lots": len(self.training_lot_ids_),
                "n_training_parts": len(self.training_component_ids_)}
        path.with_suffix(".json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> ScreeningModel:
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
    interval = {}
    for p in PARAMETERS:
        lo, hi = row.get(f"pi_lo_{SHORT[p]}_168h"), row.get(f"pi_hi_{SHORT[p]}_168h")
        if lo is not None and pd.notna(lo):
            interval[p] = {"lower": _num(lo), "upper": _num(hi), "width": _num(float(hi) - float(lo))}
    module_a = {
        "score": _num(row["module_a_score"]),
        "threshold": _num(row["threshold_a"]),
        "decision_statistic": "sum over parameters of max(0, robust z vs own lot)",
        "per_parameter": {
            p: {
                "robust_z": _num(row[f"robust_z_{p}"]),
                "contribution": _num(row[f"a_contrib_{p}"]),
                "value_0_24h_mean": _num(row[f"a_value_{p}"]),
                "lot_median": _num(row[f"a_lot_median_{p}"]),
                "lot_mad": _num(row[f"a_lot_mad_{p}"]),
            }
            for p in PARAMETERS
        },
        "diagnostics": {
            "mahalanobis": _num(row["module_a_mahalanobis"]),
            "isolation_forest": _num(row["module_a_isolation"]),
            "composite_v1": _num(row["module_a_composite"]),
        },
    }
    b_contrib = row.get("b_contributions")
    return {
        "module_a": module_a,
        "module_b_contributions": b_contrib if isinstance(b_contrib, dict) else None,
        "observed_static_breach": bool(row.get("observed_static_breach", False)),
        "prediction_interval": {"coverage_target": INTERVAL_COVERAGE, "method": "CQR", "per_parameter": interval},
        "safety_slope": {
            "rule": "safety_slope = lot median of predicted drift rate + k * max(1.4826*MAD, floor)",
            "k": _num(k),
            "driver_parameter": str(row["module_b_driver"]),
            "per_parameter": drift,
        },
    }
