"""Burn-in test conditions stored as data (T3): defaults flagged as assumed, Arrhenius, Module B feature, ingest."""

from __future__ import annotations

import uuid

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.app.core.database import SessionLocal
from backend.app.main import app
from backend.app.models import AuditEvent, Lot
from data_engine.generator import BurnInSyntheticGenerator
from ml_engine.conditions import T_REF_C, arrhenius_factor, resolve_conditions
from ml_engine.features import build_early_features


def test_defaults_are_flagged_as_assumed():
    cond, assumed = resolve_conditions({})
    assert cond == {"temperature_c": 125.0, "test_parameter": "leakage_current_ua", "unit": "uA", "static_limit": 50.0}
    assert set(assumed) == {"temperature_c", "test_parameter", "unit", "static_limit"}
    cond, assumed = resolve_conditions({"temperature_c": 150, "test_parameter": "IDDQ"})
    assert cond["temperature_c"] == 150 and cond["test_parameter"] == "iddq_ma" and cond["unit"] == "mA"
    assert cond["static_limit"] == 5.0 and set(assumed) == {"unit", "static_limit"}
    with pytest.raises(ValueError):
        resolve_conditions({"test_parameter": "voltage"})


def test_arrhenius_factor():
    assert arrhenius_factor(T_REF_C) == pytest.approx(1.0)
    assert arrhenius_factor(150) > 1.0 > arrhenius_factor(85)
    assert arrhenius_factor(150) / arrhenius_factor(125) == pytest.approx(arrhenius_factor(150, t_ref_c=125))


def test_generator_uses_temperature_and_default_is_unchanged():
    base = BurnInSyntheticGenerator(num_lots=3, components_per_lot=30, random_seed=5).generate_dataset()
    same = BurnInSyntheticGenerator(num_lots=3, components_per_lot=30, random_seed=5,
                                    lot_temperatures_c=[125.0]).generate_dataset()
    pd.testing.assert_frame_equal(base.drop(columns="recorded_at"), same.drop(columns="recorded_at"))
    hot = BurnInSyntheticGenerator(num_lots=3, components_per_lot=30, random_seed=5,
                                   lot_temperatures_c=[150.0]).generate_dataset()
    normal = lambda d: d[(d.ground_truth_label == "NORMAL") & (d.interval_hours == 0)].leakage_current_ua.median()  # noqa: E731
    assert normal(hot) > normal(base) * 1.2
    assert set(base["temperature_c"]) == {125.0}


def test_temperature_is_a_lot_level_feature_from_metadata_only():
    df = BurnInSyntheticGenerator(num_lots=3, components_per_lot=20, random_seed=2,
                                  lot_temperatures_c=[85.0, 125.0, 150.0]).generate_dataset()
    f = build_early_features(df, "v2")
    per_lot = f.groupby("lot_id")["lot_temperature_c"].nunique()
    assert (per_lot == 1).all() and set(f["lot_temperature_c"]) == {85.0, 125.0, 150.0}
    # changing future readings does not change it; unknown temperature is NaN (missing), not a guess
    tampered = df.copy()
    tampered.loc[tampered.interval_hours == 168, "leakage_current_ua"] += 99
    pd.testing.assert_series_equal(f["lot_temperature_c"], build_early_features(tampered, "v2")["lot_temperature_c"])
    assert np.isnan(build_early_features(df.drop(columns="temperature_c"), "v2")["lot_temperature_c"]).all()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _csv(extra_header="", extra=""):
    rows = ["part_id,leakage_current_ua_0h,iddq_ma_0h,propagation_delay_ns_0h,leakage_current_ua_24h,iddq_ma_24h,"
            "propagation_delay_ns_24h" + extra_header]
    for i in range(30):
        rows.append(f"P{i},{10 + i * 0.05:.3f},1.5,4.2,{10.1 + i * 0.05:.3f},1.5,4.2{extra}")
    return "\n".join(rows)


@pytest.mark.asyncio
async def test_ingest_stores_conditions_and_flags_assumed(client):
    ids = []
    try:
        r1 = await client.post("/api/v1/ingest", json={"csv": _csv(",temperature_c,parameter", ",150,leakage"),
                                                       "lot_number": f"T3-{uuid.uuid4().hex[:6]}", "filename": "hot.csv"})
        r2 = await client.post("/api/v1/ingest", json={"csv": _csv(), "lot_number": f"T3-{uuid.uuid4().hex[:6]}"})
        assert r1.status_code == 201 and r2.status_code == 201
        ids = [r1.json()["lot_id"], r2.json()["lot_id"]]
        lots = {lot["id"]: lot for lot in (await client.get("/api/v1/lots")).json()}
        hot, default = lots[ids[0]], lots[ids[1]]
        assert hot["temperature_c"] == 150.0 and hot["test_parameter"] == "leakage_current_ua"
        assert set(hot["conditions_assumed"]) == {"unit", "static_limit"}
        assert hot["source_detail"]["file"] == "hot.csv" and len(hot["source_detail"]["sha256"]) == 64
        assert default["temperature_c"] == 125.0 and "temperature_c" in default["conditions_assumed"]
    finally:
        with SessionLocal() as s:
            for i in ids:
                s.execute(delete(AuditEvent).where(AuditEvent.lot_id == uuid.UUID(i)))
                s.execute(delete(Lot).where(Lot.id == uuid.UUID(i)))
            s.commit()
