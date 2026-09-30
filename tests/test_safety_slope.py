"""Calculated, lot-relative safety slope (Module B early-rejection rule)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_engine.generator import BurnInSyntheticGenerator
from ml_engine.features import PARAMETERS
from ml_engine.safety_slope import lot_statistics, safety_slopes, spread_floors
from ml_engine.screening import ScreeningModel


def _rates(lot_rates: dict) -> pd.DataFrame:
    rows = []
    for lot, rs in lot_rates.items():
        for i, r in enumerate(rs):
            rows.append({"component_id": f"{lot}-{i}", "lot_id": lot,
                         **{f"rate_{p}": r * (1 if p == "leakage_current_ua" else 0.01) for p in PARAMETERS}})
    return pd.DataFrame(rows)


def test_two_lots_with_different_drift_get_different_safety_slopes():
    rng = np.random.default_rng(0)
    rates = _rates({"calm": rng.normal(0.01, 0.005, 60), "drifty": rng.normal(0.08, 0.02, 60)})
    floors = spread_floors(rates)
    stats = lot_statistics(rates, floors)
    slopes = safety_slopes(stats, k=3.0).assign(lot=stats["lot_id"])
    per_lot = slopes.groupby("lot")["safety_slope_leakage_current_ua"].agg(["min", "max"])
    # constant within a lot, different between lots, and ordered like the lots' drift behaviour
    assert (per_lot["min"] == per_lot["max"]).all()
    assert per_lot.loc["drifty", "min"] > per_lot.loc["calm", "min"] + 0.03
    # derivation: median + k * spread
    calm = stats[stats["lot_id"] == "calm"].iloc[0]
    assert slopes.loc[stats["lot_id"] == "calm", "safety_slope_leakage_current_ua"].iloc[0] == pytest.approx(
        calm["lot_median_leakage_current_ua"] + 3.0 * calm["lot_spread_leakage_current_ua"])


def test_spread_floor_prevents_degenerate_lot():
    rates = _rates({"normal": np.linspace(0.0, 0.04, 50), "flat": np.full(50, 0.02)})
    floors = spread_floors(rates)
    stats = lot_statistics(rates, floors)
    flat = stats[stats["lot_id"] == "flat"]
    assert (flat["lot_spread_leakage_current_ua"] == floors["leakage_current_ua"]).all()
    assert floors["leakage_current_ua"] > 0


def test_flag_equivalence_score_vs_slope():
    rng = np.random.default_rng(1)
    rates = _rates({"a": rng.normal(0.02, 0.01, 80), "b": rng.normal(0.05, 0.01, 80)})
    stats = lot_statistics(rates, spread_floors(rates))
    k = 2.0
    slopes = safety_slopes(stats, k)
    any_exceeds = np.zeros(len(stats), dtype=bool)
    for p in PARAMETERS:
        any_exceeds |= stats[f"rate_{p}"].to_numpy() >= slopes[f"safety_slope_{p}"].to_numpy() - 1e-12
    assert ((stats["module_b_score"].to_numpy() >= k) == any_exceeds).all()


def test_safety_slope_computed_from_early_data_only_and_differs_between_real_lots():
    df = BurnInSyntheticGenerator(num_lots=5, components_per_lot=50, random_seed=4).generate_dataset()
    lots = sorted(df["lot_id"].unique())
    train, test = df[df["lot_id"].isin(lots[:3])], df[df["lot_id"].isin(lots[3:])].copy()
    model = ScreeningModel(random_state=0).fit(train)

    # Make every part of one test lot drift faster between 0h and 24h.
    fast_lot = lots[3]
    m = (test["lot_id"] == fast_lot) & (test["interval_hours"] == 24)
    test.loc[m, "leakage_current_ua"] *= 1.6
    p1 = model.predict(test)
    per_lot = p1.groupby("lot_id")["safety_slope_leakage_current_ua"].first()
    assert per_lot[fast_lot] > per_lot[lots[4]]

    tampered = test.copy()
    late = tampered["interval_hours"].isin([96, 168])
    tampered.loc[late, "leakage_current_ua"] += 500.0
    p2 = model.predict(tampered)
    pd.testing.assert_series_equal(p1["safety_slope_leakage_current_ua"], p2["safety_slope_leakage_current_ua"])
