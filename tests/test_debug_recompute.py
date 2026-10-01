"""T7: the debug recompute (raw SQL + plain Python) agrees with every number the API serves to the UI."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.app.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_recompute_matches_benchmark_and_lot_counts(client):
    raw = (await client.get("/api/v1/debug/recompute")).json()
    shown = (await client.get("/api/v1/metrics/benchmark")).json()
    b = raw["benchmark"]
    for key in ("total_components", "true_positives", "false_positives", "false_negatives", "true_negatives",
                "recall", "precision", "f2_score", "weighted_cost", "module_b_mae_leakage", "linear_baseline_mae_leakage"):
        assert b[key] == pytest.approx(shown[key], abs=1e-4), key
    lots = (await client.get("/api/v1/lots")).json()
    assert lots
    for lot in lots:
        c = raw["lots"][lot["id"]]
        assert (c["pass"], c["review"], c["reject"]) == (lot["pass_count"], lot["review_count"], lot["reject_count"])


@pytest.mark.asyncio
async def test_every_lot_has_a_provenance_tag_source(client):
    for lot in (await client.get("/api/v1/lots")).json():
        d = lot["source_detail"]
        assert d and d["kind"] in ("SYNTHETIC", "UPLOADED")
        if d["kind"] == "SYNTHETIC":
            assert "seed" in d and "generator" in d
