"""Physics-based generator (T4): the documented properties hold, and the legacy generator stays selectable."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_engine.generator import BurnInSyntheticGenerator
from data_engine.physics_generator import LIMITS, PhysicsBurnInGenerator, make_generator
from ml_engine.conditions import arrhenius_factor


@pytest.fixture(scope="module")
def df() -> pd.DataFrame:
    return PhysicsBurnInGenerator(num_lots=40, components_per_lot=100, random_seed=11).generate_dataset()


def test_seeded_and_configurable(df):
    again = PhysicsBurnInGenerator(num_lots=40, components_per_lot=100, random_seed=11).generate_dataset()
    pd.testing.assert_frame_equal(df.drop(columns="recorded_at"), again.drop(columns="recorded_at"))
    assert df["lot_id"].nunique() == 40 and df["component_id"].nunique() == 4000
    assert PhysicsBurnInGenerator(num_lots=7, components_per_lot=10, random_seed=1).generate_dataset()["lot_id"].nunique() == 7


def test_legacy_generator_still_selectable():
    assert isinstance(make_generator("legacy", num_lots=2, components_per_lot=5, random_seed=1), BurnInSyntheticGenerator)
    assert isinstance(make_generator("physics", num_lots=2, components_per_lot=5, random_seed=1), PhysicsBurnInGenerator)
    with pytest.raises(ValueError):
        make_generator("other")


def test_log_normal_baseline_and_lot_to_lot_shift(df):
    t0 = df[(df.interval_hours == 0) & (df.ground_truth_label == "NORMAL") & (df.temperature_c == 125.0)]
    assert t0["leakage_current_ua"].skew() > 0.1  # right-skewed in linear space
    assert abs(np.log(t0["leakage_current_ua"]).skew()) < abs(t0["leakage_current_ua"].skew())  # ~symmetric in log
    # Lot-to-lot shift across ALL lots, after dividing out each lot's Arrhenius temperature factor.
    all0 = df[(df.interval_hours == 0) & (df.ground_truth_label == "NORMAL")]
    med = all0.groupby("lot_id").agg(m=("leakage_current_ua", "median"), t=("temperature_c", "first"))
    shift = med["m"] / med["t"].map(arrhenius_factor)
    assert shift.max() / shift.min() > 1.5


def test_temperature_dependence(df):
    med = df[(df.interval_hours == 0) & (df.ground_truth_label == "NORMAL")].groupby("temperature_c")["leakage_current_ua"].median()
    assert list(med.sort_index().values) == sorted(med.values)  # hotter lots leak more (Arrhenius)


def test_power_law_degradation_is_sublinear_for_normal_parts(df):
    n = df[df.ground_truth_label == "NORMAL"].groupby("interval_hours")["leakage_current_ua"].median()
    early, late = (n[24] - n[0]) / 24, (n[168] - n[96]) / 72
    assert n[168] > n[0] and early > late  # increasing, decelerating (exponent < 1)


def test_heteroscedastic_noise(df):
    # Residual spread of repeated measurements grows with level: compare 0h vs a smooth fit through lots
    t0 = df[(df.interval_hours == 0) & (df.ground_truth_label == "NORMAL")]
    lo, hi = t0[t0.temperature_c == 85.0]["leakage_current_ua"], t0[t0.temperature_c == 150.0]["leakage_current_ua"]
    assert hi.std() > 3 * lo.std()


def test_latent_parts_pass_static_limit_everywhere_with_documented_signal_mix(df):
    parts = df.drop_duplicates("component_id").set_index("component_id")
    drift = parts[parts.ground_truth_label.isin(["STEEP_DRIFT", "LATE_DRIFT"])]
    maxes = df[df.component_id.isin(drift.index)].groupby("component_id")["leakage_current_ua"].max()
    latent = maxes[~drift["is_datasheet_breached"]]
    assert len(latent) > 100 and (latent < LIMITS["leakage_current_ua"]).all()
    gross = drift[drift["is_datasheet_breached"]]
    assert 0 < len(gross) < 0.4 * len(drift)
    mix = drift["latent_signal_24h"].value_counts(normalize=True)
    assert set(mix.index) == {"clear", "partial", "none"}
    for k, target in (("clear", 0.40), ("partial", 0.25), ("none", 0.35)):
        assert abs(mix[k] - target) < 0.12
    # 'none' parts show no more early change than normal parts; 'clear' parts do
    wide = df.pivot_table(index="component_id", columns="interval_hours", values="leakage_current_ua")
    rel24 = (wide[24] - wide[0]) / wide[0]
    normal_rel = rel24[parts.index[parts.ground_truth_label == "NORMAL"]].median()
    assert rel24[drift.index[drift.latent_signal_24h == "clear"]].median() > 3 * normal_rel
    assert abs(rel24[drift.index[drift.latent_signal_24h == "none"]].median() - normal_rel) < 0.02
