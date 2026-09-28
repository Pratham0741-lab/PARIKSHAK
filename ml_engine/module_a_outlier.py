"""
Module A: Dynamic Lot-Adaptive Outlier Detector for ISRO SIH26170.
Identifies spatial lot anomalies using robust location (Median), scale (MAD),
Ledoit-Wolf covariance-shrunk Mahalanobis distances, and Isolation Forests.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import chi2
from sklearn.covariance import LedoitWolf
from sklearn.ensemble import IsolationForest

logger = logging.getLogger(__name__)


class LotOutlierDetector:
    """
    Spatial lot-adaptive anomaly detector for early burn-in screening.
    Normalizes components relative to their specific manufacturing lot
    to decouple wafer process corner shifts (BENIGN_HIGH_LOT) from genuine defects.
    """

    DEFAULT_THRESHOLD: float = 0.50
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
        """
        Initialize the Module A Outlier Detector.

        Args:
            threshold: Anomaly score cutoff [0.0, 1.0] for flagging outliers.
            isolation_forest_contamination: Expected proportion of outliers for iForest.
            random_state: Seed for reproducible Isolation Forest estimators.
        """
        self.threshold = threshold
        self.isolation_forest_contamination = isolation_forest_contamination
        self.random_state = random_state

        # Fitted estimators and lot profiles
        self.lot_profiles_: Dict[Any, Dict[str, Dict[str, float]]] = {}
        self.covariance_estimator_: Optional[LedoitWolf] = None
        self.isolation_forest_: Optional[IsolationForest] = None
        self.iso_norm_params_: Dict[str, float] = {}

    @staticmethod
    def _compute_mad(arr: np.ndarray) -> float:
        """Computes empirical Median Absolute Deviation (MAD), guarded against zero."""
        med = float(np.median(arr))
        mad = float(np.median(np.abs(arr - med)))
        return max(mad, 1e-5)

    def _extract_early_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extracts and pivots 0h and 24h measurements for each component."""
        df_early = df[df["interval_hours"].isin([0, 24])].copy()
        pivot = df_early.pivot_table(
            index=["component_id", "lot_id"],
            columns="interval_hours",
            values=list(self.PARAMETERS),
        ).reset_index()

        pivot.columns = [
            f"{c[0]}_{c[1]}" if c[1] != "" else c[0]
            for c in pivot.columns
        ]
        return pivot

    def fit(self, df: pd.DataFrame) -> "LotOutlierDetector":
        """
        Fits robust lot statistics, Ledoit-Wolf covariance shrinkage,
        and Isolation Forest density boundaries.
        """
        piv = self._extract_early_features(df)

        # 1. Compute per-lot robust location (median) and scale (MAD)
        self.lot_profiles_ = {}
        for lot_id, lot_data in piv.groupby("lot_id"):
            profile: Dict[str, Dict[str, float]] = {}
            for p in self.PARAMETERS:
                v0 = lot_data[f"{p}_0"].values
                v24 = lot_data[f"{p}_24"].values
                v_avg = (v0 + v24) / 2.0
                med = float(np.median(v_avg))
                mad = self._compute_mad(v_avg)
                profile[p] = {"median": med, "mad": mad}
            self.lot_profiles_[lot_id] = profile

        # 2. Transform into lot-normalized Z-space (in MAD units)
        Z_list = []
        for _, row in piv.iterrows():
            lid = row["lot_id"]
            prof = self.lot_profiles_[lid]
            z_row = []
            for p in self.PARAMETERS:
                v_avg = (row[f"{p}_0"] + row[f"{p}_24"]) / 2.0
                z = (v_avg - prof[p]["median"]) / prof[p]["mad"]
                z_row.append(z)
            Z_list.append(z_row)

        Z = np.array(Z_list, dtype=np.float64)

        # 3. Fit Ledoit-Wolf Covariance Estimator for Mahalanobis metric
        # In lot-normalized Z-space, the lot median is strictly at the origin (0, 0, 0)
        self.covariance_estimator_ = LedoitWolf(assume_centered=True)
        self.covariance_estimator_.fit(Z)

        # 4. Fit Isolation Forest on lot-normalized representations
        self.isolation_forest_ = IsolationForest(
            n_estimators=100,
            contamination=self.isolation_forest_contamination,
            random_state=self.random_state,
        )
        self.isolation_forest_.fit(Z)

        iso_raw = -self.isolation_forest_.decision_function(Z)
        self.iso_norm_params_ = {
            "p5": float(np.percentile(iso_raw, 5)),
            "p95": float(np.percentile(iso_raw, 95)),
        }

        return self

    def predict(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates Module A outlier metrics for all components in the dataset.
        """
        if not self.lot_profiles_ or self.covariance_estimator_ is None or self.isolation_forest_ is None:
            raise RuntimeError("LotOutlierDetector must be fitted prior to calling predict().")

        piv = self._extract_early_features(df)
        components = piv["component_id"].values
        lot_ids = piv["lot_id"].values

        Z_list = []
        Z0_list = []
        for _, row in piv.iterrows():
            lid = row["lot_id"]
            prof = self.lot_profiles_.get(lid)
            if prof is None:
                prof = {
                    p: {
                        "median": float(np.median((piv[f"{p}_0"] + piv[f"{p}_24"]) / 2.0)),
                        "mad": self._compute_mad((piv[f"{p}_0"].values + piv[f"{p}_24"].values) / 2.0),
                    }
                    for p in self.PARAMETERS
                }
            z_row = []
            z0_row = []
            for p in self.PARAMETERS:
                v_avg = (row[f"{p}_0"] + row[f"{p}_24"]) / 2.0
                z = (v_avg - prof[p]["median"]) / prof[p]["mad"]
                z0 = (row[f"{p}_0"] - prof[p]["median"]) / prof[p]["mad"]
                z_row.append(z)
                z0_row.append(z0)
            Z_list.append(z_row)
            Z0_list.append(z0_row)

        Z = np.array(Z_list, dtype=np.float64)
        Z0 = np.array(Z0_list, dtype=np.float64)

        # 1. Mahalanobis distance from lot median origin using shrunk precision matrix
        prec = self.covariance_estimator_.precision_
        mahalanobis_dists = np.sqrt(np.maximum(0.0, np.sum(Z @ prec * Z, axis=1)))

        # 2. Isolation Forest score
        iso_raw = -self.isolation_forest_.decision_function(Z)
        p5 = self.iso_norm_params_["p5"]
        p95 = self.iso_norm_params_["p95"]
        s_iso = np.clip((iso_raw - p5) / (p95 - p5 + 1e-6), 0.0, 1.0)

        # 3. Univariate Extreme Deviation (catches LEVEL_OUTLIER at t=0h or avg)
        max_abs_z0 = np.max(np.abs(Z0), axis=1)
        max_abs_zavg = np.max(np.abs(Z), axis=1)
        max_abs_z = np.maximum(max_abs_z0, max_abs_zavg)
        s_univ = np.clip((max_abs_z - 2.5) / 2.0, 0.0, 1.0)

        # 4. Multivariate Simultaneous Excursion (catches SUBTLE_MULTIVARIATE)
        # Sum of positive deviations across the 3 dimensions
        z_pos_sum = np.sum(np.maximum(0.0, Z), axis=1)
        s_joint = np.clip((z_pos_sum - 3.2) / 2.2, 0.0, 1.0)
        s_maha = np.clip((mahalanobis_dists - 1.6) / 2.0, 0.0, 1.0)

        # 5. Composite Normalized Score in [0.0, 1.0]
        blended_score = 0.35 * s_maha + 0.35 * s_univ + 0.15 * s_joint + 0.15 * s_iso
        composite_score = np.clip(
            np.maximum(
                blended_score,
                np.maximum(s_univ * 0.95, s_joint * 0.90),
            ),
            0.0,
            1.0,
        )

        flags = composite_score >= self.threshold

        return pd.DataFrame(
            {
                "component_id": components,
                "lot_id": lot_ids,
                "module_a_score": np.round(composite_score, 4),
                "module_a_mahalanobis": np.round(mahalanobis_dists, 4),
                "module_a_flag": flags,
            }
        )
