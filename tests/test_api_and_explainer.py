"""
FastAPI REST API integration tests (httpx.AsyncClient). Model-based explanation tests live in
tests/test_explanations.py (they replace the former DeterministicExplainer unit tests, which
asserted risk categories derived from hand-set constants unrelated to the model's decision).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app


# ==============================================================================
# Integration Tests: FastAPI REST Endpoints (httpx.AsyncClient)
# ==============================================================================

import pytest_asyncio

@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_api_health_endpoint(async_client: AsyncClient):
    """Verify system health endpoint returns 200 and HEALTHY."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "HEALTHY"
    assert data["api_version"] == "v1"


@pytest.mark.asyncio
async def test_api_lots_list(async_client: AsyncClient):
    """Verify GET /api/v1/lots returns lots with triage counts."""
    response = await async_client.get("/api/v1/lots")
    assert response.status_code == 200
    lots = response.json()
    assert isinstance(lots, list)
    assert len(lots) > 0

    first = lots[0]
    assert "id" in first
    assert "lot_number" in first
    assert "total_components" in first
    assert "pass_count" in first
    assert "review_count" in first
    assert "reject_count" in first
    assert first["total_components"] == (first["pass_count"] + first["review_count"] + first["reject_count"])


@pytest.mark.asyncio
async def test_api_lot_distribution(async_client: AsyncClient):
    """Verify GET /api/v1/lots/{lot_id}/distribution returns statistical envelope per parameter."""
    lots_res = await async_client.get("/api/v1/lots")
    lots = lots_res.json()
    lot_id = lots[0]["id"]

    response = await async_client.get(f"/api/v1/lots/{lot_id}/distribution")
    assert response.status_code == 200
    data = response.json()
    assert data["lot_id"] == lot_id
    assert "parameters" in data
    assert len(data["parameters"]) == 3

    for param in data["parameters"]:
        assert param["parameter"] in ["leakage_current_ua", "iddq_ma", "propagation_delay_ns"]
        assert len(param["intervals"]) == 4  # 0h, 24h, 96h, 168h
        for interval in param["intervals"]:
            assert "min" in interval
            assert "p25" in interval
            assert "median" in interval
            assert "p75" in interval
            assert "max" in interval
            assert "mad" in interval
            assert interval["min"] <= interval["median"] <= interval["max"]


@pytest.mark.asyncio
async def test_api_lot_distribution_not_found(async_client: AsyncClient):
    """Verify GET /api/v1/lots/{lot_id}/distribution returns 404 for unknown lot."""
    random_id = str(uuid.uuid4())
    response = await async_client.get(f"/api/v1/lots/{random_id}/distribution")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_api_components_list_and_filters(async_client: AsyncClient):
    """Verify GET /api/v1/components pagination and filtering."""
    # 1. Base listing
    response = await async_client.get("/api/v1/components?page=1&page_size=20")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] > 0
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert len(data["items"]) <= 20

    # 2. Filter by verdict=REJECT
    reject_res = await async_client.get("/api/v1/components?verdict=REJECT")
    assert reject_res.status_code == 200
    reject_data = reject_res.json()
    for item in reject_data["items"]:
        assert item["verdict"] == "REJECT"

    # 3. Filter by ground_truth_flag=true
    defect_res = await async_client.get("/api/v1/components?ground_truth_flag=true")
    assert defect_res.status_code == 200
    defect_data = defect_res.json()
    for item in defect_data["items"]:
        assert item["ground_truth_flag"] is True


@pytest.mark.asyncio
async def test_api_component_profile_and_explain(async_client: AsyncClient):
    """Verify GET /components/{id}/profile and /components/{id}/explain endpoints."""
    comp_res = await async_client.get("/api/v1/components?page_size=1")
    comp = comp_res.json()["items"][0]
    comp_id = comp["id"]

    # 1. Profile
    prof_res = await async_client.get(f"/api/v1/components/{comp_id}/profile")
    assert prof_res.status_code == 200
    profile = prof_res.json()
    assert profile["id"] == comp_id
    assert len(profile["readings"]) == 4
    assert profile["prediction"] is not None
    assert profile["prediction"]["verdict"] in ["PASS", "REVIEW", "REJECT"]
    assert profile["lot_envelope"] is not None

    # 2. Explain
    exp_res = await async_client.get(f"/api/v1/components/{comp_id}/explain")
    assert exp_res.status_code == 200
    exp = exp_res.json()
    assert exp["component_id"] == comp_id
    assert exp["verdict"] == profile["prediction"]["verdict"]
    assert exp["module_a"]["score"] == pytest.approx(profile["prediction"]["module_a_score"], abs=1e-3)
    assert len(exp["module_a"]["contributions"]) == 3
    assert len(exp["module_b"]["contributions"]) > 0
    assert exp["module_b"]["top_contributor"] in exp["summary"]
    assert exp["module_a"]["top_contributor"] in exp["summary"]


@pytest.mark.asyncio
async def test_api_inspector_review_submission_and_persistence(async_client: AsyncClient):
    """Verify POST /api/v1/reviews/{component_id}/action creates and persists QA review."""
    comp_res = await async_client.get("/api/v1/components?page_size=1")
    comp = comp_res.json()["items"][0]
    comp_id = comp["id"]

    payload = {
        "inspector_id": "ISRO-QA-CHIEF-09",
        "disposition": "QUARANTINED",
        "inspector_notes": "Latent gate oxide risk confirmed via local MAD breakdown. Quarantining from satellite flight package.",
    }

    # 1. Submit review action
    rev_res = await async_client.post(f"/api/v1/reviews/{comp_id}/action", json=payload)
    assert rev_res.status_code == 201
    rev_data = rev_res.json()
    assert rev_data["status"] == "SUCCESS"
    assert rev_data["component_id"] == comp_id
    assert rev_data["disposition"] == "QUARANTINED"
    assert rev_data["inspector_id"] == "ISRO-QA-CHIEF-09"

    # 2. Verify persistence in component profile
    prof_res = await async_client.get(f"/api/v1/components/{comp_id}/profile")
    assert prof_res.status_code == 200
    profile = prof_res.json()
    assert len(profile["reviews"]) >= 1

    latest_rev = profile["reviews"][0]
    assert latest_rev["inspector_id"] == "ISRO-QA-CHIEF-09"
    assert latest_rev["disposition"] == "QUARANTINED"
    assert "Latent gate oxide risk" in latest_rev["inspector_notes"]


@pytest.mark.asyncio
async def test_api_benchmark_metrics(async_client: AsyncClient):
    """Verify GET /api/v1/metrics/benchmark returns performance metrics."""
    res = await async_client.get("/api/v1/metrics/benchmark")
    assert res.status_code == 200
    metrics = res.json()

    assert metrics["total_components"] == 1000
    # Held-out (out-of-fold) metrics; exact values are checked against the committed
    # evaluation in test_e2e_workflow.py.
    assert metrics["in_sample_predictions"] == 0
    assert 0.0 < metrics["recall"] <= 1.0
    assert metrics["false_negative_rate"] == pytest.approx(1.0 - metrics["recall"], abs=1e-3)
    assert "PASS" in metrics["triage_distribution"]
    assert "REVIEW" in metrics["triage_distribution"]
    assert "REJECT" in metrics["triage_distribution"]
    assert metrics["module_b_mae_leakage"] > 0.0
    assert metrics["mae_reduction_pct"] > 0.0  # LightGBM outperforms linear baseline


@pytest.mark.asyncio
async def test_api_benchmark_cost_fields_are_computed(async_client: AsyncClient):
    """Weighted cost is recomputed from the confusion matrix and responds to the cost query params."""
    m = (await async_client.get("/api/v1/metrics/benchmark")).json()
    assert m["weighted_cost"] == pytest.approx(m["fn_cost"] * m["false_negatives"] + m["fp_cost"] * m["false_positives"])
    assert m["cost_per_1000_parts"] == pytest.approx(1000 * m["weighted_cost"] / m["total_components"], abs=1e-3)
    p, r = m["precision"], m["recall"]
    assert m["f2_score"] == pytest.approx(5 * p * r / (4 * p + r), abs=1e-3)
    assert m["final_thresholds"]["source"] == "cost_minimised_on_inner_oof_validation"

    m100 = (await async_client.get("/api/v1/metrics/benchmark", params={"fn_cost": 100, "fp_cost": 1})).json()
    assert m100["weighted_cost"] == pytest.approx(100 * m100["false_negatives"] + m100["false_positives"])


@pytest.mark.asyncio
async def test_api_cost_curve(async_client: AsyncClient):
    for module in ("A", "B"):
        res = await async_client.get("/api/v1/metrics/cost-curve", params={"module": module, "points": 30})
        assert res.status_code == 200
        curve = res.json()
        assert curve["module"] == module and len(curve["points"]) >= 5
        for pt in curve["points"]:
            assert pt["weighted_cost"] == pytest.approx(curve["fn_cost"] * pt["fn"] + curve["fp_cost"] * pt["fp"])
        fns = [pt["fn"] for pt in curve["points"]]
        assert fns == sorted(fns)  # raising the swept threshold can only add escapes
