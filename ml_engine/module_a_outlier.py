"""
Module A: Dynamic Lot-Adaptive Outlier Detector for ISRO SIH26170.

Every part is scored relative to its OWN lot: per-lot Median/MAD normalisation of the
early (0h, 24h) readings, followed by a Ledoit-Wolf shrunk Mahalanobis distance and an
Isolation Forest fitted on lot-normalised training data. Only 0h and 24h readings are used,
so the detector can run at the 24h checkpoint and never sees 96h/168h values.

Decision score (module_a_score): the sum over parameters of the POSITIVE lot-relative robust
z-scores, i.e. how far, in lot-MAD units, a part sits above its own lot's median on leakage,
IDDQ and delay combined. Burn-in degradation raises all three, so downward deviations are not
counted. This statistic was selected on development datasets that exclude the evaluation seed
(evaluation/module_a_dev_study.py, reports/module_a_dev_study.json). Mahalanobis distance,
Isolation Forest score and the earlier blended composite are still reported as diagnostics and
used in explanations.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)

EARLY_INTERVALS: Tuple[int, int] = (0, 24)


class LotOutlierDetector:
    """
    Spatial lot-adaptive anomaly detector for early burn-in screening.
    Normalizes components relative to their specific manufacturing lot
    to decouple wafer process corner shifts (BENIGN_HIGH_LOT) from genuine defects.
    """

    # Cold-start default only (in lot-MAD units); the operational threshold is chosen by cost
    # minimisation on out-of-fold validation predictions (see evaluation/thresholds.py).
    DEFAULT_THRESHOLD: float = 4.0
    PARAMETERS: Tuple[str, ...] = (
        "leakage_current_ua",
        "iddq_ma",
        "propagation_delay_ns",
    )

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        isolation_forest_contamination: float = 0.10,
        random_state: int = 42,
    ) -> None:
        self.threshold = threshold
        self.isolation_forest_contamination = isolation_forest_contamination
        self.random_state = random_state

        self.covariance_estimator_: LedoitWolf | None = None
        self.isolation_forest_: IsolationForest | None = None
        self.iso_norm_params_: Dict[str, float] = {}

    @staticmethod
    def _compute_mad(arr: np.ndarray) -> float:
        """Empirical Median Absolute Deviation (MAD), guarded against zero."""
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))
        return max(mad, 1e-5)

    def _extract_early_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Pivots 0h and 24h measurements per component. Later intervals are discarded here."""
        df_early = df[df["interval_hours"].isin(EARLY_INTERVALS)]
        pivot = df_early.pivot_table(
            index=["component_id", "lot_id"],
            columns="interval_hours",
            values=list(self.PARAMETERS),
        ).reset_index()
        pivot.columns = [f"{c[0]}_{c[1]}" if c[1] != "" else c[0] for c in pivot.columns]
        pivot = pivot.dropna(subset=[f"{p}_{h}" for p in self.PARAMETERS for h in EARLY_INTERVALS])
        return pivot.sort_values(["lot_id", "component_id"]).reset_index(drop=True)

    def lot_profiles(self, piv: pd.DataFrame) -> Dict[Any, Dict[str, Dict[str, float]]]:
        """Per-lot robust location/scale of the 0h/24h average, computed from the scored lot itself."""
        profiles: Dict[Any, Dict[str, Dict[str, float]]] = {}
        for lot_id, lot_data in piv.groupby("lot_id"):
            profile: Dict[str, Dict[str, float]] = {}
            for p in self.PARAMETERS:
                v_avg = (lot_data[f"{p}_0"].to_numpy() + lot_data[f"{p}_24"].to_numpy()) / 2.0
                profile[p] = {"median": float(np.median(v_avg)), "mad": self._compute_mad(v_avg)}
            profiles[lot_id] = profile
        return profiles

    def _lot_normalise(self, piv: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
        Z, Z0, _ = self._lot_normalise_with_stats(piv)
        return Z, Z0

    def _lot_normalise_with_stats(self, piv: pd.DataFrame):
        profiles = self.lot_profiles(piv)
        n = len(piv)
        Z = np.zeros((n, len(self.PARAMETERS)))
        Z0 = np.zeros((n, len(self.PARAMETERS)))
        stats: Dict[str, Dict[str, np.ndarray]] = {}
        lot_ids = piv["lot_id"].to_numpy()
        for j, p in enumerate(self.PARAMETERS):
            med = np.array([profiles[lot][p]["median"] for lot in lot_ids])
            mad = np.array([profiles[lot][p]["mad"] for lot in lot_ids])
            v0 = piv[f"{p}_0"].to_numpy()
            v24 = piv[f"{p}_24"].to_numpy()
            Z[:, j] = ((v0 + v24) / 2.0 - med) / mad
            Z0[:, j] = (v0 - med) / mad
            stats[p] = {"value": (v0 + v24) / 2.0, "median": med, "mad": mad}
        return Z, Z0, stats

    def fit(self, df: pd.DataFrame) -> LotOutlierDetector:
        """Fits Ledoit-Wolf covariance and Isolation Forest on lot-normalised (MAD-unit) training data."""
        piv = self._extract_early_features(df)
        Z, _ = self._lot_normalise(piv)

        # In lot-normalised space every lot's median sits at the origin.
        self.covariance_estimator_ = LedoitWolf(assume_centered=True).fit(Z)
        self.isolation_forest_ = IsolationForest(
            n_estimators=100,
            contamination=self.isolation_forest_contamination,
            random_state=self.random_state,
        ).fit(Z)

        iso_raw = -self.isolation_forest_.decision_function(Z)
        self.iso_norm_params_ = {
            "p5": float(np.percentile(iso_raw, 5)),
            "p95": float(np.percentile(iso_raw, 95)),
        }
        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """Module A metrics for every component with complete 0h/24h readings."""
        if self.covariance_estimator_ is None or self.isolation_forest_ is None:
            raise RuntimeError("LotOutlierDetector must be fitted prior to calling predict().")

        piv = self._extract_early_features(df)
        Z, Z0, lot_stats = self._lot_normalise_with_stats(piv)

        prec = self.covariance_estimator_.precision_
        mahalanobis_dists = np.sqrt(np.maximum(0.0, np.sum(Z @ prec * Z, axis=1)))

        iso_raw = -self.isolation_forest_.decision_function(Z)
        p5, p95 = self.iso_norm_params_["p5"], self.iso_norm_params_["p95"]
        s_iso = np.clip((iso_raw - p5) / (p95 - p5 + 1e-6), 0.0, 1.0)

        # Univariate extreme deviation (LEVEL_OUTLIER-type signatures)
        max_abs_z = np.maximum(np.max(np.abs(Z0), axis=1), np.max(np.abs(Z), axis=1))
        s_univ = np.clip((max_abs_z - 2.5) / 2.0, 0.0, 1.0)

        # Simultaneous positive excursion across all parameters (SUBTLE_MULTIVARIATE-type)
        z_pos_sum = np.sum(np.maximum(0.0, Z), axis=1)
        s_joint = np.clip((z_pos_sum - 3.2) / 2.2, 0.0, 1.0)
        s_maha = np.clip((mahalanobis_dists - 1.6) / 2.0, 0.0, 1.0)

        blended = 0.35 * s_maha + 0.35 * s_univ + 0.15 * s_joint + 0.15 * s_iso
        composite = np.clip(np.maximum(blended, np.maximum(s_univ * 0.95, s_joint * 0.90)), 0.0, 1.0)

        decision = np.sum(np.maximum(0.0, Z), axis=1)

        out = pd.DataFrame(
            {
                "component_id": piv["component_id"].to_numpy(),
                "lot_id": piv["lot_id"].to_numpy(),
                "module_a_score": np.round(decision, 4),
                "module_a_composite": np.round(composite, 4),
                "module_a_mahalanobis": np.round(mahalanobis_dists, 4),
                "module_a_isolation": np.round(s_iso, 4),
                "module_a_flag": decision >= self.threshold,
            }
        )
        for j, p in enumerate(self.PARAMETERS):
            out[f"robust_z_{p}"] = np.round(Z[:, j], 3)
            # Exact additive decomposition of the decision score: contribution_p = max(0, z_p).
            out[f"a_contrib_{p}"] = np.round(np.maximum(0.0, Z[:, j]), 4)
            out[f"a_value_{p}"] = np.round(lot_stats[p]["value"], 4)
            out[f"a_lot_median_{p}"] = np.round(lot_stats[p]["median"], 4)
            out[f"a_lot_mad_{p}"] = np.round(lot_stats[p]["mad"], 5)
        return out
