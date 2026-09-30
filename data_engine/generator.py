"""
Synthetically Realistic Burn-In Screening Dataset Generator.
Emulates semiconductor physics, fab wafer-level batch variation,
subthreshold leakage, IDDQ quiescent current, propagation delay,
sensor noise, and specific screening defect signatures.
"""

from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class LotProfile:
    """Manufacturing profile for a single fabrication lot."""
    lot_id: uuid.UUID
    lot_number: str
    wafer_id: str
    is_benign_high: bool
    base_leakage_ua: float
    base_iddq_ma: float
    base_delay_ns: float
    leakage_mad: float = 0.0
    iddq_mad: float = 0.0
    delay_mad: float = 0.0
    leakage_median: float = 0.0
    iddq_median: float = 0.0
    delay_median: float = 0.0


class BurnInSyntheticGenerator:
    """
    Mathematical and physical synthetic data generator for semiconductor burn-in testing.
    Emulates MIL-STD-883 / JEDEC / ISRO screening environments.
    """

    INTERVALS: Tuple[int, ...] = (0, 24, 96, 168)

    # Datasheet Absolute Ceilings
    DEFAULT_LEAKAGE_MAX_UA: float = 50.0
    DEFAULT_IDDQ_MAX_MA: float = 5.0
    DEFAULT_DELAY_MAX_NS: float = 8.0

    # Nominal physical parameter distributions
    NOMINAL_LEAKAGE_MEAN_UA: float = 12.0
    NOMINAL_LEAKAGE_STD_UA: float = 1.5
    BENIGN_HIGH_LEAKAGE_MEAN_UA: float = 22.0

    NOMINAL_IDDQ_MEAN_MA: float = 1.5
    NOMINAL_IDDQ_STD_MA: float = 0.15
    BENIGN_HIGH_IDDQ_MEAN_MA: float = 2.2

    NOMINAL_DELAY_MEAN_NS: float = 4.2
    NOMINAL_DELAY_STD_NS: float = 0.25
    BENIGN_HIGH_DELAY_MEAN_NS: float = 4.9

    # Intra-lot component variation
    INTRA_LOT_LEAKAGE_SIGMA: float = 0.85
    INTRA_LOT_IDDQ_SIGMA: float = 0.06
    INTRA_LOT_DELAY_SIGMA: float = 0.12

    def __init__(
        self,
        num_lots: int = 10,
        components_per_lot: int = 100,
        random_seed: Optional[int] = 42,
        leakage_max_ua: float = DEFAULT_LEAKAGE_MAX_UA,
        iddq_max_ma: float = DEFAULT_IDDQ_MAX_MA,
        delay_max_ns: float = DEFAULT_DELAY_MAX_NS,
        sensor_noise_ratio: float = 0.05,
        benign_lot_fraction: float = 0.2,
        defect_rates: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Initialize the synthetic burn-in generator.

        Args:
            num_lots: Total fabrication lots to emulate.
            components_per_lot: Number of physical parts per lot.
            random_seed: Seed for reproducible random numbers.
            leakage_max_ua: Absolute datasheet ceiling for leakage current.
            iddq_max_ma: Absolute datasheet ceiling for IDDQ quiescent current.
            delay_max_ns: Absolute datasheet ceiling for critical path propagation delay.
            sensor_noise_ratio: Gaussian sensor measurement relative error (sigma = ratio * value).
            benign_lot_fraction: Proportion of lots generated as BENIGN_HIGH_LOT.
            defect_rates: Proportions for each anomaly class per normal lot.
        """
        self.num_lots = num_lots
        self.components_per_lot = components_per_lot
        self.random_seed = random_seed
        self.leakage_max_ua = leakage_max_ua
        self.iddq_max_ma = iddq_max_ma
        self.delay_max_ns = delay_max_ns
        self.sensor_noise_ratio = sensor_noise_ratio
        self.benign_lot_fraction = benign_lot_fraction

        self.rng = np.random.default_rng(seed=self.random_seed)
        # Deterministic identifiers: derived from the seed with uuid5 so repeated runs with the
        # same seed yield identical IDs without consuming the numeric RNG stream.
        self._id_namespace = (
            uuid.uuid5(uuid.NAMESPACE_OID, f"sih26170-burnin-seed-{self.random_seed}")
            if self.random_seed is not None
            else None
        )

        # Default defect rates per normal lot (~12% total anomalies)
        self.defect_rates = defect_rates or {
            "LEVEL_OUTLIER": 0.03,        # 3%
            "STEEP_DRIFT": 0.03,          # 3%
            "LATE_DRIFT": 0.03,           # 3%
            "SUBTLE_MULTIVARIATE": 0.03,  # 3%
        }

    def _make_id(self, key: str) -> uuid.UUID:
        """Seed-derived UUID (uuid5) when seeded, random UUID otherwise."""
        if self._id_namespace is None:
            return uuid.uuid4()
        return uuid.uuid5(self._id_namespace, key)

    @staticmethod
    def _compute_mad(data: np.ndarray) -> float:
        """Compute the empirical Median Absolute Deviation (MAD)."""
        med = float(np.median(data))
        mad = float(np.median(np.abs(data - med)))
        return max(mad, 1e-4)

    def _inject_sensor_noise(self, value: float) -> float:
        """Applies Gaussian sensor measurement noise: sigma = sensor_noise_ratio * value."""
        sigma = self.sensor_noise_ratio * max(abs(value), 1e-4)
        noisy = float(self.rng.normal(loc=value, scale=sigma))
        return max(0.001, noisy)

    def _create_lot_profiles(self) -> List[LotProfile]:
        """Generates lot profiles with physical fab baseline shifts."""
        profiles: List[LotProfile] = []
        num_benign = max(1, int(round(self.num_lots * self.benign_lot_fraction)))
        benign_indices = set(self.rng.choice(self.num_lots, size=num_benign, replace=False))

        for lot_idx in range(self.num_lots):
            lot_num = f"LOT-2026-B{lot_idx + 1:03d}"
            lot_id = self._make_id(f"lot-{lot_num}")
            wafer_id = f"WAF-ISRO-{(lot_idx % 25) + 1:02d}{chr(65 + (lot_idx % 6))}"
            is_benign = lot_idx in benign_indices

            if is_benign:
                # Naturally elevated baseline due to process corner / thinner gate oxide
                base_leakage = float(self.rng.normal(self.BENIGN_HIGH_LEAKAGE_MEAN_UA, 0.6))
                base_iddq = float(self.rng.normal(self.BENIGN_HIGH_IDDQ_MEAN_MA, 0.05))
                base_delay = float(self.rng.normal(self.BENIGN_HIGH_DELAY_MEAN_NS, 0.08))
            else:
                # Nominal manufacturing baseline with batch-to-batch fab variation
                base_leakage = float(self.rng.normal(self.NOMINAL_LEAKAGE_MEAN_UA, self.NOMINAL_LEAKAGE_STD_UA))
                base_iddq = float(self.rng.normal(self.NOMINAL_IDDQ_MEAN_MA, self.NOMINAL_IDDQ_STD_MA))
                base_delay = float(self.rng.normal(self.NOMINAL_DELAY_MEAN_NS, self.NOMINAL_DELAY_STD_NS))

            profiles.append(
                LotProfile(
                    lot_id=lot_id,
                    lot_number=lot_num,
                    wafer_id=wafer_id,
                    is_benign_high=is_benign,
                    base_leakage_ua=max(1.0, base_leakage),
                    base_iddq_ma=max(0.1, base_iddq),
                    base_delay_ns=max(0.5, base_delay),
                )
            )

        return profiles

    def _assign_labels_to_lot(
        self, profile: LotProfile
    ) -> List[Tuple[str, bool]]:
        """
        Assigns defect and normal labels to components in a lot.
        Benign high lots have 100% normal parts (demonstrating adaptive baseline handling).
        """
        n = self.components_per_lot
        if profile.is_benign_high:
            # Benign high lot: all components are structurally NORMAL despite elevated baseline
            return [("NORMAL", False)] * n

        labels: List[Tuple[str, bool]] = []
        counts = {
            defect: int(round(rate * n))
            for defect, rate in self.defect_rates.items()
        }

        for defect_name, count in counts.items():
            labels.extend([(defect_name, True)] * count)

        # Pad remainder with normal components
        normals_needed = n - len(labels)
        if normals_needed > 0:
            labels.extend([("NORMAL", False)] * normals_needed)
        elif normals_needed < 0:
            labels = labels[:n]

        # Shuffle component assignments within the lot
        perm = self.rng.permutation(len(labels))
        return [labels[i] for i in perm]

    def _generate_component_trajectories(
        self,
        profile: LotProfile,
        label: str,
        is_anomaly: bool,
    ) -> Tuple[List[Dict[str, float]], bool]:
        """
        Emulates physical parametric burn-in trajectories across [0, 24, 96, 168] hours.
        Returns:
            (readings_list, is_datasheet_breached)
        """
        intervals = self.INTERVALS
        readings: List[Dict[str, float]] = []

        # Component baseline drawn from lot distribution
        comp_base_leakage = float(self.rng.normal(profile.base_leakage_ua, self.INTRA_LOT_LEAKAGE_SIGMA))
        comp_base_iddq = float(self.rng.normal(profile.base_iddq_ma, self.INTRA_LOT_IDDQ_SIGMA))
        comp_base_delay = float(self.rng.normal(profile.base_delay_ns, self.INTRA_LOT_DELAY_SIGMA))

        # Use empirical lot median and MAD if available, else standard intra-lot sigmas
        leak_median = profile.leakage_median if profile.leakage_median > 0 else profile.base_leakage_ua
        leak_mad = profile.leakage_mad if profile.leakage_mad > 0 else (0.6745 * self.INTRA_LOT_LEAKAGE_SIGMA)
        iddq_median = profile.iddq_median if profile.iddq_median > 0 else profile.base_iddq_ma
        iddq_mad = profile.iddq_mad if profile.iddq_mad > 0 else (0.6745 * self.INTRA_LOT_IDDQ_SIGMA)
        delay_median = profile.delay_median if profile.delay_median > 0 else profile.base_delay_ns
        delay_mad = profile.delay_mad if profile.delay_mad > 0 else (0.6745 * self.INTRA_LOT_DELAY_SIGMA)

        is_datasheet_breached = False

        if label == "LEVEL_OUTLIER":
            # Sits 4 to 6 MADs above lot median from t=0h, staying strictly below 50 uA ceiling
            mad_multiplier = float(self.rng.uniform(4.0, 6.0))
            elevated_leakage = leak_median + (mad_multiplier * leak_mad)
            elevated_leakage = min(elevated_leakage, self.leakage_max_ua - 1.5)

            for t in intervals:
                # Stationary elevated profile across all intervals with sensor noise
                leak = self._inject_sensor_noise(elevated_leakage)
                # Ensure strictly below datasheet ceiling
                leak = min(leak, self.leakage_max_ua - 0.5)
                iddq = self._inject_sensor_noise(comp_base_iddq)
                delay = self._inject_sensor_noise(comp_base_delay)
                readings.append({"t": t, "leakage": leak, "iddq": iddq, "delay": delay})

        elif label == "STEEP_DRIFT":
            # Starts at lot baseline at 0h, drifts steadily past 35 uA by 168h
            target_168_leak = float(self.rng.uniform(36.0, 48.0))
            # 15% chance of catastrophic breach past 50 uA to test gross failure detection
            if self.rng.random() < 0.15:
                target_168_leak = float(self.rng.uniform(51.0, 56.0))

            total_drift = target_168_leak - comp_base_leakage
            progressions = {
                0: 0.0,
                24: 0.20 + float(self.rng.normal(0, 0.02)),
                96: 0.65 + float(self.rng.normal(0, 0.03)),
                168: 1.0,
            }

            for t in intervals:
                prog = max(0.0, min(1.0, progressions[t]))
                true_leak = comp_base_leakage + (prog * total_drift)
                leak = self._inject_sensor_noise(true_leak)
                # IDDQ also slightly increases under oxide breakdown
                true_iddq = comp_base_iddq + (prog * 0.3 * comp_base_iddq)
                iddq = self._inject_sensor_noise(true_iddq)
                delay = self._inject_sensor_noise(comp_base_delay)
                readings.append({"t": t, "leakage": leak, "iddq": iddq, "delay": delay})

        elif label == "LATE_DRIFT":
            # Flat across 0h, 24h, 96h; surges upward between 96h and 168h
            surge_leak = float(self.rng.uniform(35.0, 48.0))
            if self.rng.random() < 0.15:
                surge_leak = float(self.rng.uniform(51.0, 55.0))

            for t in intervals:
                if t < 96:
                    true_leak = comp_base_leakage
                    true_iddq = comp_base_iddq
                elif t == 96:
                    # Very subtle initiation
                    true_leak = comp_base_leakage + (0.05 * (surge_leak - comp_base_leakage))
                    true_iddq = comp_base_iddq
                else: # 168h
                    true_leak = surge_leak
                    true_iddq = comp_base_iddq * 1.25

                leak = self._inject_sensor_noise(true_leak)
                iddq = self._inject_sensor_noise(true_iddq)
                delay = self._inject_sensor_noise(comp_base_delay)
                readings.append({"t": t, "leakage": leak, "iddq": iddq, "delay": delay})

        elif label == "SUBTLE_MULTIVARIATE":
            # Sits at +1.8 MAD across all three parameters simultaneously
            multiv_leak = leak_median + (1.8 * leak_mad)
            multiv_iddq = iddq_median + (1.8 * iddq_mad)
            multiv_delay = delay_median + (1.8 * delay_mad)

            for t in intervals:
                leak = self._inject_sensor_noise(multiv_leak)
                iddq = self._inject_sensor_noise(multiv_iddq)
                delay = self._inject_sensor_noise(multiv_delay)
                readings.append({"t": t, "leakage": leak, "iddq": iddq, "delay": delay})

        else: # NORMAL (both standard lot normal and benign high lot normal)
            for t in intervals:
                # Physically normal parts have slight infant mortality settling (~1-2% drop)
                # followed by stable operation with sensor measurement noise
                settling = 1.0 - (0.015 * (t / 168.0))
                leak = self._inject_sensor_noise(comp_base_leakage * settling)
                iddq = self._inject_sensor_noise(comp_base_iddq * settling)
                delay = self._inject_sensor_noise(comp_base_delay)
                readings.append({"t": t, "leakage": leak, "iddq": iddq, "delay": delay})

        # Check for absolute datasheet ceiling breaches across all interval readings
        for r in readings:
            if (
                r["leakage"] > self.leakage_max_ua
                or r["iddq"] > self.iddq_max_ma
                or r["delay"] > self.delay_max_ns
            ):
                is_datasheet_breached = True
                break

        return readings, is_datasheet_breached

    def generate_dataset(self) -> pd.DataFrame:
        """
        Executes complete synthetic burn-in screening emulation.

        Returns:
            pd.DataFrame: Tabular dataset with all component readings and ground-truth tags.
        """
        profiles = self._create_lot_profiles()
        rows: List[Dict[str, Any]] = []
        base_timestamp = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)

        for profile in profiles:
            # 1. Sample preliminary nominal components to calculate empirical lot median and MAD
            prelim_samples = self.rng.normal(
                loc=[profile.base_leakage_ua, profile.base_iddq_ma, profile.base_delay_ns],
                scale=[self.INTRA_LOT_LEAKAGE_SIGMA, self.INTRA_LOT_IDDQ_SIGMA, self.INTRA_LOT_DELAY_SIGMA],
                size=(self.components_per_lot, 3),
            )
            profile.leakage_median = float(np.median(prelim_samples[:, 0]))
            profile.leakage_mad = self._compute_mad(prelim_samples[:, 0])
            profile.iddq_median = float(np.median(prelim_samples[:, 1]))
            profile.iddq_mad = self._compute_mad(prelim_samples[:, 1])
            profile.delay_median = float(np.median(prelim_samples[:, 2]))
            profile.delay_mad = self._compute_mad(prelim_samples[:, 2])

            labels = self._assign_labels_to_lot(profile)

            for comp_idx, (label, is_anomaly) in enumerate(labels, start=1):
                serial_num = f"{profile.lot_number}-SN{comp_idx:04d}"
                comp_id = self._make_id(f"component-{serial_num}")

                readings, is_breached = self._generate_component_trajectories(
                    profile=profile,
                    label=label,
                    is_anomaly=is_anomaly,
                )

                for r in readings:
                    interval_hours = r["t"]
                    recorded_at = base_timestamp + datetime.timedelta(hours=interval_hours)

                    rows.append(
                        {
                            "lot_id": str(profile.lot_id),
                            "lot_number": profile.lot_number,
                            "wafer_id": profile.wafer_id,
                            "is_benign_high_lot": profile.is_benign_high,
                            "component_id": str(comp_id),
                            "serial_number": serial_num,
                            "interval_hours": interval_hours,
                            "leakage_current_ua": round(r["leakage"], 4),
                            "iddq_ma": round(r["iddq"], 4),
                            "propagation_delay_ns": round(r["delay"], 4),
                            "ground_truth_label": label,
                            "ground_truth_flag": is_anomaly,
                            "is_datasheet_breached": is_breached,
                            "recorded_at": recorded_at,
                        }
                    )

        df = pd.DataFrame(rows)
        return df

    def generate_records(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generates structured records partitioned by database entities
        ('lots', 'components', 'readings') for high-throughput bulk database seeding.
        """
        profiles = self._create_lot_profiles()
        lots_records: List[Dict[str, Any]] = []
        components_records: List[Dict[str, Any]] = []
        readings_records: List[Dict[str, Any]] = []

        base_timestamp = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)

        for profile in profiles:
            lots_records.append(
                {
                    "id": profile.lot_id,
                    "lot_number": profile.lot_number,
                    "wafer_id": profile.wafer_id,
                    "status": "INGESTED",
                    "created_at": base_timestamp,
                }
            )

            # Calculate empirical lot statistics
            prelim_samples = self.rng.normal(
                loc=[profile.base_leakage_ua, profile.base_iddq_ma, profile.base_delay_ns],
                scale=[self.INTRA_LOT_LEAKAGE_SIGMA, self.INTRA_LOT_IDDQ_SIGMA, self.INTRA_LOT_DELAY_SIGMA],
                size=(self.components_per_lot, 3),
            )
            profile.leakage_median = float(np.median(prelim_samples[:, 0]))
            profile.leakage_mad = self._compute_mad(prelim_samples[:, 0])
            profile.iddq_median = float(np.median(prelim_samples[:, 1]))
            profile.iddq_mad = self._compute_mad(prelim_samples[:, 1])
            profile.delay_median = float(np.median(prelim_samples[:, 2]))
            profile.delay_mad = self._compute_mad(prelim_samples[:, 2])

            labels = self._assign_labels_to_lot(profile)

            for comp_idx, (label, is_anomaly) in enumerate(labels, start=1):
                serial_num = f"{profile.lot_number}-SN{comp_idx:04d}"
                comp_id = self._make_id(f"component-{serial_num}")

                readings, is_breached = self._generate_component_trajectories(
                    profile=profile,
                    label=label,
                    is_anomaly=is_anomaly,
                )

                components_records.append(
                    {
                        "id": comp_id,
                        "lot_id": profile.lot_id,
                        "serial_number": serial_num,
                        "ground_truth_label": label,
                        "ground_truth_flag": is_anomaly,
                        "is_datasheet_breached": is_breached,
                    }
                )

                for r in readings:
                    interval_hours = r["t"]
                    recorded_at = base_timestamp + datetime.timedelta(hours=interval_hours)
                    readings_records.append(
                        {
                            "id": self._make_id(f"reading-{serial_num}-{interval_hours}"),
                            "component_id": comp_id,
                            "interval_hours": interval_hours,
                            "leakage_current_ua": round(r["leakage"], 4),
                            "iddq_ma": round(r["iddq"], 4),
                            "propagation_delay_ns": round(r["delay"], 4),
                            "recorded_at": recorded_at,
                        }
                    )

        return {
            "lots": lots_records,
            "components": components_records,
            "readings": readings_records,
        }
