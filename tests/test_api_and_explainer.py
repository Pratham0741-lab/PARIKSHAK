"""
Automated Unit and Integration Tests for Phase 3:
- DeterministicExplainer unit tests across defect classes (Level Outlier, Steep Drift, Subtle Multivariate, Nominal).
- Safe division & edge cases.
- FastAPI REST API async integration tests with httpx.AsyncClient.
"""

from __future__ import annotations

import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from backend.app.main import app
from backend.app.models.prediction import ScreeningVerdict
from backend.app.models.review import ReviewDisposition
from backend.app.services.local_explainer import DeterministicExplainer


# ==============================================================================
# Unit Tests: DeterministicExplainer
# ==============================================================================

@pytest.fixture
def explainer() -> DeterministicExplainer:
    return DeterministicExplainer()


@pytest.fixture
def baseline_lot_readings():
    """Generates synthetic baseline readings for 10 lot components across 0h, 24h, 96h, 168h."""
    readings = []
    for comp_idx in range(10):
        c_id = uuid.uuid4()
        for h in [0, 24, 96, 168]:
            readings.append({
                "component_id": c_id,
                "interval_hours": h,
                "leakage_current_ua": 3.0 + 0.1 * comp_idx + 0.005 * h,
                "iddq_ma": 0.45 + 0.01 * comp_idx,
                "propagation_delay_ns": 4.2 + 0.02 * comp_idx,
            })
    return readings


def test_explainer_level_outlier_identification(explainer, baseline_lot_readings):
    """Verify that LEVEL_OUTLIER with high 0h reading is classified as LATENT_LOT_OUTLIER."""
    lot_stats = explainer.compute_lot_statistics(baseline_lot_readings)

    comp_data = {
        "id": uuid.uuid4(),
        "serial_number": "SN-OUTLIER-01",
        "lot_number": "LOT-2026-TEST",
        "wafer_id": "WFR-01",
        "ground_truth_label": "LEVEL_OUTLIER",
        "ground_truth_flag": True,
        "is_datasheet_breached": False,
    }

    # High initial leakage: 12.0 uA vs lot median ~3.45 uA (MAD ~0.25 -> Z_MAD > 30)
    comp_readings = [
        {"interval_hours": 0, "leakage_current_ua": 12.0, "iddq_ma": 0.50, "propagation_delay_ns": 4.3},
        {"interval_hours": 24, "leakage_current_ua": 12.1, "iddq_ma": 0.51, "propagation_delay_ns": 4.31},
    ]

    pred_data = {
        "module_a_score": 0.92,
        "module_a_mahalanobis": 8.5,
        "module_a_flag": True,
        "pred_leakage_168h": 12.5,
        "pred_iddq_168h": 0.52,
        "pred_delay_168h": 4.35,
        "drift_slope_ua_per_hr": 0.004,
        "module_b_flag": False,
        "verdict": "REJECT",
        "verdict_reason": "RULE_EXTREME_OUTLIER: Module A spatial anomaly score exceeds critical limit.",
    }

    res = explainer.explain_component(comp_data, comp_readings, lot_stats, pred_data)

    assert res["risk_category"] == "LATENT_LOT_OUTLIER"
    assert res["primary_parameter"] == "leakage_current_ua"
    assert res["recommended_action"] == "QUARANTINE_FLIGHT_HARDWARE"
    assert "LATENT_LOT_OUTLIER" in res["executive_summary"]
    assert "OUTLIER" in res["technical_justification"]
    assert res["parameter_metrics"]["leakage_current_ua"]["max_abs_z_mad"] >= 4.0


def test_explainer_steep_drift_identification(explainer, baseline_lot_readings):
    """Verify that STEEP_DRIFT part with severe slope is classified as CRITICAL_RUNAWAY."""
    lot_stats = explainer.compute_lot_statistics(baseline_lot_readings)

    comp_data = {
        "id": uuid.uuid4(),
        "serial_number": "SN-RUNAWAY-02",
        "lot_number": "LOT-2026-TEST",
        "wafer_id": "WFR-01",
        "ground_truth_label": "STEEP_DRIFT",
        "ground_truth_flag": True,
        "is_datasheet_breached": False,
    }

    # Nominal at 0h (3.2 uA), jumps to 9.5 uA at 24h -> slope (9.5 - 3.2)/24 = 0.2625 uA/hr
    comp_readings = [
        {"interval_hours": 0, "leakage_current_ua": 3.2, "iddq_ma": 0.50, "propagation_delay_ns": 4.2},
        {"interval_hours": 24, "leakage_current_ua": 9.5, "iddq_ma": 0.70, "propagation_delay_ns": 4.3},
    ]

    pred_data = {
        "module_a_score": 0.45,
        "module_a_mahalanobis": 2.1,
        "module_a_flag": False,
        "pred_leakage_168h": 58.4,  # Breaches 50 uA ceiling
        "pred_iddq_168h": 1.2,
        "pred_delay_168h": 4.8,
        "drift_slope_ua_per_hr": 0.2625,
        "module_b_flag": True,
        "verdict": "REJECT",
        "verdict_reason": "RULE_RUNAWAY_DRIFT: Severe leakage drift rate indicates runaway kinetics.",
    }

    res = explainer.explain_component(comp_data, comp_readings, lot_stats, pred_data)

    assert res["risk_category"] == "CRITICAL_RUNAWAY"
    assert res["recommended_action"] == "QUARANTINE_FLIGHT_HARDWARE"
    assert res["primary_parameter"] == "leakage_current_ua"
    assert "CRITICAL_RUNAWAY" in res["executive_summary"]
    assert "58.4" in res["technical_justification"]


def test_explainer_subtle_multivariate_identification(explainer, baseline_lot_readings):
    """Verify that SUBTLE_MULTIVARIATE Part is classified as SUBTLE_DEGRADATION and maps to HOLD_FOR_96H_CHECK."""
    lot_stats = explainer.compute_lot_statistics(baseline_lot_readings)

    comp_data = {
        "id": uuid.uuid4(),
        "serial_number": "SN-SUBTLE-03",
        "lot_number": "LOT-2026-TEST",
        "wafer_id": "WFR-01",
        "ground_truth_label": "SUBTLE_MULTIVARIATE",
        "ground_truth_flag": True,
        "is_datasheet_breached": False,
    }

    # Readings moderately higher across all parameters, but individually < 4.0 MAD
    comp_readings = [
        {"interval_hours": 0, "leakage_current_ua": 3.7, "iddq_ma": 0.52, "propagation_delay_ns": 4.35},
        {"interval_hours": 24, "leakage_current_ua": 4.2, "iddq_ma": 0.55, "propagation_delay_ns": 4.38},
    ]

    pred_data = {
        "module_a_score": 0.65,
        "module_a_mahalanobis": 3.8,  # High Mahalanobis distance
        "module_a_flag": True,
        "pred_leakage_168h": 12.0,
        "pred_iddq_168h": 0.70,
        "pred_delay_168h": 4.5,
        "drift_slope_ua_per_hr": 0.02,
        "module_b_flag": False,
        "verdict": "REVIEW",
        "verdict_reason": "RULE_BORDERLINE: Module A lot outlier flagged (score=0.650).",
    }

    res = explainer.explain_component(comp_data, comp_readings, lot_stats, pred_data)

    assert res["risk_category"] == "SUBTLE_DEGRADATION"
    assert res["recommended_action"] == "HOLD_FOR_96H_CHECK"
    assert "SUBTLE_DEGRADATION" in res["executive_summary"]
    assert "D_M" in res["technical_justification"]


def test_explainer_nominal_component(explainer, baseline_lot_readings):
    """Verify that nominal parts are assigned NOMINAL risk and PASS_FLIGHT_READY."""
    lot_stats = explainer.compute_lot_statistics(baseline_lot_readings)

    comp_data = {
        "id": uuid.uuid4(),
        "serial_number": "SN-NOMINAL-04",
        "lot_number": "LOT-2026-TEST",
        "wafer_id": "WFR-01",
        "ground_truth_label": "NORMAL",
        "ground_truth_flag": False,
        "is_datasheet_breached": False,
    }

    comp_readings = [
        {"interval_hours": 0, "leakage_current_ua": 3.45, "iddq_ma": 0.50, "propagation_delay_ns": 4.29},
        {"interval_hours": 24, "leakage_current_ua": 3.50, "iddq_ma": 0.50, "propagation_delay_ns": 4.30},
    ]

    pred_data = {
        "module_a_score": 0.12,
        "module_a_mahalanobis": 0.8,
        "module_a_flag": False,
        "pred_leakage_168h": 4.2,
        "pred_iddq_168h": 0.52,
        "pred_delay_168h": 4.32,
        "drift_slope_ua_per_hr": 0.002,
        "module_b_flag": False,
        "verdict": "PASS",
        "verdict_reason": "RULE_NOMINAL: Component within lot baseline envelope.",
    }

    res = explainer.explain_component(comp_data, comp_readings, lot_stats, pred_data)

    assert res["risk_category"] == "NOMINAL"
    assert res["recommended_action"] == "PASS_FLIGHT_READY"
    assert "nominal parametric performance" in res["executive_summary"]


def test_explainer_divide_by_zero_safety(explainer):
    """Verify robust protection when all lot readings are identical (MAD=0)."""
    identical_readings = [
        {"component_id": uuid.uuid4(), "interval_hours": 0, "leakage_current_ua": 5.0, "iddq_ma": 1.0, "propagation_delay_ns": 4.0},
        {"component_id": uuid.uuid4(), "interval_hours": 0, "leakage_current_ua": 5.0, "iddq_ma": 1.0, "propagation_delay_ns": 4.0},
    ]
    lot_stats = explainer.compute_lot_statistics(identical_readings)

    assert lot_stats["leakage_current_ua"][0]["mad"] >= 1e-6

    comp_data = {
        "id": uuid.uuid4(),
        "serial_number": "SN-ZERO-DIV",
        "lot_number": "LOT-ZERO",
        "wafer_id": "WFR-ZERO",
        "ground_truth_label": "NORMAL",
        "ground_truth_flag": False,
        "is_datasheet_breached": False,
    }
    comp_readings = [
        {"interval_hours": 0, "leakage_current_ua": 5.5, "iddq_ma": 1.0, "propagation_delay_ns": 4.0}
    ]

    # Should not raise ZeroDivisionError
    res = explainer.explain_component(comp_data, comp_readings, lot_stats)
    assert res is not None
    assert "parameter_metrics" in res


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
    assert exp["risk_category"] in ["CRITICAL_RUNAWAY", "LATENT_LOT_OUTLIER", "SUBTLE_DEGRADATION", "NOMINAL"]
    assert exp["recommended_action"] in ["QUARANTINE_FLIGHT_HARDWARE", "HOLD_FOR_96H_CHECK", "PASS_FLIGHT_READY"]
    assert len(exp["executive_summary"]) > 20
    assert "# Engineering Screening Justification" in exp["technical_justification"]
    assert "drift_metrics" in exp
    assert "lot_comparison" in exp


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
