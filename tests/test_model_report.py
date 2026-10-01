"""Reskin backend additions: /metrics/model, per-lot module flag counts, optional supplier."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.app.core.database import SessionLocal
from backend.app.main import app
from backend.app.models import AuditEvent, Lot


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=300) as c:
        yield c


@pytest.mark.asyncio
async def test_model_report_is_computed_from_the_run_and_artifact(client):
    r = (await client.get("/api/v1/metrics/model")).json()
    bench = (await client.get("/api/v1/metrics/benchmark")).json()
    assert r["registry"] and r["registry"][0]["current"] and sum(x["current"] for x in r["registry"]) == 1
    assert r["held_out"]["detection"]["recall"] == pytest.approx(bench["recall"], abs=1e-3)
    assert r["train_optimistic"]["detection"]["n"] == r["held_out"]["detection"]["n"]
    assert r["split"]["n_lots"] == 10 and r["split"]["n_parts"] == 1000  # test fixture: legacy 10 x 100
    fi = r["feature_importance"]["per_parameter"]["leakage_current_ua"]
    assert fi and 0 < sum(f["share"] for f in fi) <= 1.0001
    pts = r["predicted_vs_actual"]["points"]
    assert len(pts) == bench["total_components"]
    mae = sum(abs(p["pred"] - p["actual"]) for p in pts) / len(pts)
    assert mae == pytest.approx(bench["module_b_mae_leakage"], abs=1e-3)


@pytest.mark.asyncio
async def test_lot_flag_counts_and_optional_supplier(client):
    lots = (await client.get("/api/v1/lots")).json()
    assert all(0 <= x["module_a_flag_count"] <= x["total_components"] for x in lots)
    assert all(x["supplier"] is None for x in lots)  # synthetic lots have no supplier: the UI hides that panel
    csv = "part_id,supplier," + ",".join(f"{p}_{h}h" for h in (0, 24) for p in ("leakage_current_ua", "iddq_ma", "propagation_delay_ns"))
    csv += "".join(f"\nS{i},Acme Test Co,{10 + i * 0.1},1.5,4.2,{10.1 + i * 0.1},1.5,4.2" for i in range(30))
    res = await client.post("/api/v1/ingest", json={"csv": csv, "lot_number": f"TEST-SUP-{uuid.uuid4().hex[:6]}"})
    assert res.status_code == 201, res.text[:300]
    lot_id = res.json()["lot_id"]
    try:
        lot = next(x for x in (await client.get("/api/v1/lots")).json() if x["id"] == lot_id)
        assert lot["supplier"] == "Acme Test Co"
    finally:
        with SessionLocal() as s:
            s.execute(delete(AuditEvent).where(AuditEvent.lot_id == uuid.UUID(lot_id)))
            s.execute(delete(Lot).where(Lot.id == uuid.UUID(lot_id)))
            s.commit()
