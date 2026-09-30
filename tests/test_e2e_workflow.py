"""
End-to-End System Test for ISRO SIH26170 Screening & Analytics Pipeline.
Validates the complete full-stack lifecycle:
1. Database integrity: 10 lots, 1,000 components, 4,000 readings.
2. Screening inference: ModelPrediction records populated across all units.
3. Review Queue query: Filtering borderline components (verdict=REVIEW).
4. Explainability generation: Deterministic local explanation retrieval.
5. Human QA override: Submitting inspector review audit action.
6. Audit ledger persistence: Verification of updated disposition in component profile.
7. Held-out benchmark verification: API metrics equal the reproducible out-of-fold evaluation.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backend.app.core.database import SessionLocal
from backend.app.main import app
from backend.app.models.component import Component
from backend.app.models.lot import Lot
from backend.app.models.prediction import ModelPrediction
from backend.app.models.reading import BurnInReading


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_full_pipeline_e2e_workflow(async_client: AsyncClient):
    """
    Executes the comprehensive Phase 1 through Phase 4 operational workflow:
    Seeding Verification -> Screening Inference -> Queue Triage -> Explainability -> Override -> Benchmark Audit.
    """
    # --------------------------------------------------------------------------
    # Step 1: Verify database seeding and dimensional integrity
    # --------------------------------------------------------------------------
    with SessionLocal() as session:
        lot_count = session.scalar(select(func.count(Lot.id)))
        comp_count = session.scalar(select(func.count(Component.id)))
        reading_count = session.scalar(select(func.count(BurnInReading.id)))

        assert lot_count is not None and lot_count >= 10, f"Expected >= 10 lots, found {lot_count}"
        assert comp_count is not None and comp_count >= 1000, f"Expected >= 1000 components, found {comp_count}"
        assert reading_count is not None and reading_count >= 4000, f"Expected >= 4000 readings, found {reading_count}"

    # --------------------------------------------------------------------------
    # Step 2: Verify screening analysis predictions exist
    # --------------------------------------------------------------------------
    with SessionLocal() as session:
        pred_count = session.scalar(select(func.count(ModelPrediction.id)))
        assert pred_count is not None and pred_count >= 1000, f"Expected >= 1000 predictions, found {pred_count}"

    # --------------------------------------------------------------------------
    # Step 3: Query GET /api/v1/components filtering by verdict=REVIEW
    # --------------------------------------------------------------------------
    review_res = await async_client.get("/api/v1/components?verdict=REVIEW&page=1&page_size=25")
    assert review_res.status_code == 200, f"Failed to fetch review queue: {review_res.text}"
    review_data = review_res.json()

    assert review_data["total"] > 0, "Expected borderline review components in queue"
    assert len(review_data["items"]) > 0
    borderline_item = review_data["items"][0]
    borderline_id = borderline_item["id"]
    borderline_serial = borderline_item["serial_number"]

    # --------------------------------------------------------------------------
    # Step 4: Retrieve GET /api/v1/components/{id}/explain for borderline part
    # --------------------------------------------------------------------------
    explain_res = await async_client.get(f"/api/v1/components/{borderline_id}/explain")
    assert explain_res.status_code == 200, f"Failed to get explanation: {explain_res.text}"
    explain_data = explain_res.json()

    assert explain_data["component_id"] == borderline_id
    assert explain_data["serial_number"] == borderline_serial
    # Explanation is built from this part's model outputs (see tests/test_explanations.py).
    assert explain_data["verdict"] == "REVIEW"
    assert borderline_serial in explain_data["summary"]
    assert (explain_data["module_a"]["top_contributor"] is None
            or explain_data["module_a"]["top_contributor"] in explain_data["summary"])
    assert explain_data["module_b"]["top_contributor"] in explain_data["summary"]
    assert explain_data["cv_fold"] is not None

    # --------------------------------------------------------------------------
    # Step 5: Post an override action via POST /api/v1/reviews/{id}/action
    # --------------------------------------------------------------------------
    override_payload = {
      "inspector_id": "ISRO-SR-QA-042",
      "disposition": "QUARANTINED",
      "inspector_notes": "Senior QA engineering override: Component exhibits elevated drift and multi-parameter excursion; quarantined from primary flight assembly."
    }

    action_res = await async_client.post(
        f"/api/v1/reviews/{borderline_id}/action",
        json=override_payload,
    )
    assert action_res.status_code == 201, f"Failed to record review action: {action_res.text}"
    action_data = action_res.json()

    assert action_data["status"] == "SUCCESS"
    assert action_data["component_id"] == borderline_id
    assert action_data["inspector_id"] == "ISRO-SR-QA-042"
    assert action_data["disposition"] == "QUARANTINED"
    assert "quarantined from primary flight assembly" in action_data["inspector_notes"]

    # --------------------------------------------------------------------------
    # Step 6: Verify component profile reflects updated disposition and audit ledger
    # --------------------------------------------------------------------------
    prof_res = await async_client.get(f"/api/v1/components/{borderline_id}/profile")
    assert prof_res.status_code == 200, f"Failed to get profile: {prof_res.text}"
    profile_data = prof_res.json()

    assert len(profile_data["reviews"]) >= 1
    latest_review = profile_data["reviews"][0]
    assert latest_review["inspector_id"] == "ISRO-SR-QA-042"
    assert latest_review["disposition"] == "QUARANTINED"

    # --------------------------------------------------------------------------
    # Step 7: Query /api/v1/metrics/benchmark and verify mission safety gates
    # --------------------------------------------------------------------------
    bench_res = await async_client.get("/api/v1/metrics/benchmark")
    assert bench_res.status_code == 200, f"Failed to get benchmarks: {bench_res.text}"
    bench_data = bench_res.json()

    # Held-out gates. Every prediction must be out-of-fold, and the API's numbers must equal an
    # independent fresh offline evaluation of the same pipeline on the same data (the test database is
    # seeded with the pinned legacy protocol, see tests/conftest.py).
    from evaluation.run import LEGACY_PROTOCOL, evaluate

    reference = evaluate({**LEGACY_PROTOCOL}, include_train=False)["held_out"]
    assert bench_data["total_components"] == 1000
    assert bench_data["in_sample_predictions"] == 0
    assert bench_data["out_of_fold_predictions"] == 1000
    assert bench_data["recall"] == pytest.approx(reference["detection"]["recall"], abs=1e-4)
    assert bench_data["precision"] == pytest.approx(reference["detection"]["precision"], abs=1e-4)
    assert bench_data["false_negatives"] == reference["detection"]["fn"]
    assert bench_data["module_b_mae_leakage"] == pytest.approx(
        reference["regression"]["leakage_current_ua"]["model"]["mae"], abs=1e-4
    )
    # Module B must still beat the naive linear extrapolation on held-out lots.
    assert bench_data["mae_reduction_pct"] > 0.0
    assert bench_data["triage_distribution"]["PASS"] > 0
    assert bench_data["triage_distribution"]["REVIEW"] > 0
    assert bench_data["triage_distribution"]["REJECT"] > 0
