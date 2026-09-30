"""
Unit tests for the BurnInSyntheticGenerator.
Validates semiconductor physics emulation, sensor noise,
and specific screening defect signatures.
"""

import numpy as np

from data_engine.generator import BurnInSyntheticGenerator


def test_generator_deterministic_output() -> None:
    """Verifies that setting a random seed produces strictly reproducible datasets."""
    gen1 = BurnInSyntheticGenerator(num_lots=2, components_per_lot=20, random_seed=123)
    df1 = gen1.generate_dataset()

    gen2 = BurnInSyntheticGenerator(num_lots=2, components_per_lot=20, random_seed=123)
    df2 = gen2.generate_dataset()

    assert df1.shape == df2.shape
    np.testing.assert_allclose(df1["leakage_current_ua"].values, df2["leakage_current_ua"].values)
    assert (df1["ground_truth_label"].values == df2["ground_truth_label"].values).all()


def test_dataset_dimensions_and_columns() -> None:
    """Verifies dataset rows, columns, and interval spacing."""
    num_lots = 5
    comp_per_lot = 40
    gen = BurnInSyntheticGenerator(num_lots=num_lots, components_per_lot=comp_per_lot, random_seed=42)
    df = gen.generate_dataset()

    expected_rows = num_lots * comp_per_lot * 4
    assert len(df) == expected_rows
    assert set(df["interval_hours"].unique()) == {0, 24, 96, 168}

    expected_cols = {
        "lot_id",
        "lot_number",
        "wafer_id",
        "is_benign_high_lot",
        "component_id",
        "serial_number",
        "interval_hours",
        "leakage_current_ua",
        "iddq_ma",
        "propagation_delay_ns",
        "ground_truth_label",
        "ground_truth_flag",
        "is_datasheet_breached",
        "recorded_at",
    }
    assert expected_cols.issubset(set(df.columns))


def test_level_outlier_signature() -> None:
    """Verifies LEVEL_OUTLIER sits elevated from t=0 and stays below 50 uA absolute ceiling."""
    gen = BurnInSyntheticGenerator(num_lots=10, components_per_lot=100, random_seed=42)
    df = gen.generate_dataset()

    outliers = df[df["ground_truth_label"] == "LEVEL_OUTLIER"]
    assert len(outliers) > 0

    # Must stay strictly below 50 uA absolute limit
    assert (outliers["leakage_current_ua"] < 50.0).all()

    # Trajectory must be elevated at t=0
    t0_leakage = outliers[outliers["interval_hours"] == 0]["leakage_current_ua"].mean()
    normal_t0_leakage = df[(df["ground_truth_label"] == "NORMAL") & (~df["is_benign_high_lot"]) & (df["interval_hours"] == 0)]["leakage_current_ua"].mean()
    assert t0_leakage > normal_t0_leakage + 2.0


def test_steep_drift_signature() -> None:
    """Verifies STEEP_DRIFT starts near baseline at t=0h and drifts past 35 uA by t=168h."""
    gen = BurnInSyntheticGenerator(num_lots=10, components_per_lot=100, random_seed=42)
    df = gen.generate_dataset()

    steep = df[df["ground_truth_label"] == "STEEP_DRIFT"]
    assert len(steep) > 0

    # Group by component and verify monotonic upward drift
    for _comp_id, comp_df in steep.groupby("component_id"):
        comp_df = comp_df.sort_values("interval_hours")
        leak_0h = comp_df[comp_df["interval_hours"] == 0]["leakage_current_ua"].iloc[0]
        leak_168h = comp_df[comp_df["interval_hours"] == 168]["leakage_current_ua"].iloc[0]

        # Starts near baseline (typically < 18 uA)
        assert leak_0h < 18.0
        # By 168h, must drift significantly past 35 uA
        assert leak_168h > 35.0


def test_late_drift_signature() -> None:
    """Verifies LATE_DRIFT remains flat through 96h and surges upward between 96h and 168h."""
    gen = BurnInSyntheticGenerator(num_lots=10, components_per_lot=100, random_seed=42)
    df = gen.generate_dataset()

    late = df[df["ground_truth_label"] == "LATE_DRIFT"]
    assert len(late) > 0

    for _comp_id, comp_df in late.groupby("component_id"):
        comp_df = comp_df.sort_values("interval_hours")
        leak_0h = comp_df[comp_df["interval_hours"] == 0]["leakage_current_ua"].iloc[0]
        leak_24h = comp_df[comp_df["interval_hours"] == 24]["leakage_current_ua"].iloc[0]
        leak_96h = comp_df[comp_df["interval_hours"] == 96]["leakage_current_ua"].iloc[0]
        leak_168h = comp_df[comp_df["interval_hours"] == 168]["leakage_current_ua"].iloc[0]

        # Flat between 0h and 24h (within sensor noise margin < 2.0 uA)
        assert abs(leak_24h - leak_0h) < 2.0
        # Surges sharply by 168h
        assert (leak_168h - leak_96h) > 15.0


def test_subtle_multivariate_signature() -> None:
    """Verifies SUBTLE_MULTIVARIATE has simultaneous elevation across all three parameters."""
    gen = BurnInSyntheticGenerator(num_lots=10, components_per_lot=100, random_seed=42)
    df = gen.generate_dataset()

    subtle = df[df["ground_truth_label"] == "SUBTLE_MULTIVARIATE"]
    normal = df[(df["ground_truth_label"] == "NORMAL") & (~df["is_benign_high_lot"])]

    # All three parameters should have higher means than standard normal parts
    assert subtle["leakage_current_ua"].mean() > normal["leakage_current_ua"].mean()
    assert subtle["iddq_ma"].mean() > normal["iddq_ma"].mean()
    assert subtle["propagation_delay_ns"].mean() > normal["propagation_delay_ns"].mean()


def test_benign_high_lot_behavior() -> None:
    """Verifies BENIGN_HIGH_LOT has naturally elevated baseline (~22 uA) but normal labels and zero drift."""
    gen = BurnInSyntheticGenerator(num_lots=10, components_per_lot=100, random_seed=42)
    df = gen.generate_dataset()

    benign = df[df["is_benign_high_lot"]]
    assert len(benign) > 0

    # In benign high lot, all parts are structurally NORMAL (ground_truth_flag = False)
    assert (benign["ground_truth_label"] == "NORMAL").all()
    assert (~benign["ground_truth_flag"].astype(bool)).all()

    # Elevated baseline ~22 uA
    t0_leakage = benign[benign["interval_hours"] == 0]["leakage_current_ua"].mean()
    assert 20.0 <= t0_leakage <= 24.5

    # Zero drift between 0h and 168h (stable)
    t168_leakage = benign[benign["interval_hours"] == 168]["leakage_current_ua"].mean()
    assert abs(t168_leakage - t0_leakage) < 1.0


def test_datasheet_breaches_computation() -> None:
    """Verifies is_datasheet_breached correctly flags parts violating absolute limits."""
    gen = BurnInSyntheticGenerator(num_lots=5, components_per_lot=50, random_seed=42)
    df = gen.generate_dataset()

    for _comp_id, comp_df in df.groupby("component_id"):
        breached_flag = comp_df["is_datasheet_breached"].iloc[0]
        actual_breach = bool(
            (comp_df["leakage_current_ua"] > 50.0).any()
            or (comp_df["iddq_ma"] > 5.0).any()
            or (comp_df["propagation_delay_ns"] > 8.0).any()
        )
        assert breached_flag == actual_breach
