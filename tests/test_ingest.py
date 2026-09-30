"""CSV ingest: validation rules (no zero-fill) and the full ingest -> Module A/B -> explanation flow."""

from __future__ import annotations

import uuid

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.app.core.database import SessionLocal
from backend.app.main import app
from backend.app.models import AuditEvent, Lot
from backend.app.services.ingest import PARAMETERS, REQUIRED_COLUMNS, parse_csv
from data_engine.generator import BurnInSyntheticGenerator

HEADER = ["part_id"] + [f"{p}_{h}h" for h in (0, 24, 96, 168) for p in PARAMETERS]


def _row(pid, vals):
    return ",".join([pid] + [str(v) for v in vals])


def _csv(rows):
    return "\n".join([",".join(HEADER)] + rows)


GOOD = [12.0, 1.5, 4.2, 12.1, 1.5, 4.2, 12.3, 1.5, 4.2, 12.4, 1.5, 4.2]


def test_missing_required_columns_rejects_file():
    res = parse_csv("part_id,leakage_current_ua_0h\nA,1.0\n")
    assert not res.ok and res.parts == []
    assert set(res.missing_columns) == set(REQUIRED_COLUMNS) - {"leakage_current_ua_0h"}


def test_missing_values_are_imputed_with_lot_median_never_zero():
    rows = [_row(f"P{i}", [10.0 + i] + GOOD[1:]) for i in range(5)]
    vals = list(GOOD)
    vals[3] = ""  # leakage 24h missing
    rows.append(_row("GAP", vals))
    res = parse_csv(_csv(rows))
    gap = next(p for p in res.parts if p.part_id == "GAP")
    assert gap.values[24]["leakage_current_ua"] == pytest.approx(12.1)  # median of the other parts, not 0
    assert gap.imputed[24] == ["leakage_current_ua"]
    assert gap.insufficient_data is True
    assert res.imputed_cells == 1 and res.missing_cells == 1
    assert all(p.values[h][q] != 0 for p in res.parts for h in p.values for q in PARAMETERS)


def test_duplicate_ids_rejected_and_first_kept():
    res = parse_csv(_csv([_row("A", GOOD), _row("B", GOOD), _row("A", [99] * 12)]))
    assert [p.part_id for p in res.parts] == ["A", "B"]
    assert res.duplicate_part_ids == 1 and res.rows_rejected == 1
    assert res.parts[0].values[0]["leakage_current_ua"] == 12.0


def test_non_numeric_and_negative_cells_are_missing_not_zero():
    bad = list(GOOD)
    bad[0] = "abc"
    bad[4] = "-3"
    res = parse_csv(_csv([_row("A", GOOD), _row("B", GOOD), _row("C", bad)]))
    c = next(p for p in res.parts if p.part_id == "C")
    assert res.non_numeric_cells == 2
    assert c.values[0]["leakage_current_ua"] == 12.0 and c.values[24]["iddq_ma"] == 1.5  # lot medians
    assert c.insufficient_data
    assert {i.column for i in res.issues if i.severity == "error"} == {"leakage_current_ua_0h", "iddq_ma_24h"}


def test_empty_part_id_rejected_and_missing_future_interval_not_stored():
    no_future = GOOD[:6] + [""] * 6
    res = parse_csv(_csv([_row("", GOOD), _row("A", GOOD), _row("B", no_future)]))
    assert res.rows_rejected == 1 and [p.part_id for p in res.parts] == ["A", "B"]
    b = res.parts[1]
    assert not b.insufficient_data
    assert all(v is None for v in b.values[168].values())  # not imputed: whole interval absent


# ------------------------------------------------------------------ full flow through the API
@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _lot_csv():
    df = BurnInSyntheticGenerator(num_lots=5, components_per_lot=40, random_seed=77).generate_dataset()
    df = df[df["lot_id"] == df.loc[~df["is_benign_high_lot"], "lot_id"].iloc[0]]  # a nominal (~12 uA) lot
    wide = df.pivot_table(index="serial_number", columns="interval_hours", values=list(PARAMETERS))
    rows = []
    for sn, r in wide.iterrows():
        rows.append(_row(sn, [round(r[(p, h)], 4) for h in (0, 24, 96, 168) for p in PARAMETERS]))
    lot_median = float(np.median(wide[("leakage_current_ua", 0)]))
    latent = [30.0, 1.5, 4.2, 36.0, 1.52, 4.2, 42.0, 1.55, 4.2, 48.5, 1.6, 4.2]
    rows.append(_row("LATENT-001", latent))
    gap = latent.copy()
    gap[4] = ""
    rows.append(_row("GAP-001", gap))
    rows.append(rows[0])  # duplicate
    return _csv(rows), lot_median


@pytest.mark.asyncio
async def test_ingest_to_prediction_flow(client):
    csv_text, lot_median = _lot_csv()
    lot_number = f"TEST-INGEST-{uuid.uuid4().hex[:8]}"
    before = (await client.get("/api/v1/metrics/benchmark")).json()
    res = await client.post("/api/v1/ingest", json={"csv": csv_text, "lot_number": lot_number, "actor": "pytest"})
    assert res.status_code == 201, res.text
    body = res.json()
    lot_id = body["lot_id"]
    try:
        v = body["validation"]
        assert v["parts_accepted"] == 42 and v["duplicate_part_ids"] == 1 and v["insufficient_data_parts"] == 1
        assert body["screening"]["n_screened"] == 42 and body["screening"]["n_insufficient_data"] == 1

        comps = (await client.get("/api/v1/components", params={"lot_id": lot_id, "page_size": 100})).json()["items"]
        assert len(comps) == 42 and all(c["verdict"] for c in comps)
        assert all(c["ground_truth_flag"] is None for c in comps)
        by_sn = {c["serial_number"]: c for c in comps}

        gap = (await client.get(f"/api/v1/components/{by_sn['GAP-001']['id']}/profile")).json()
        assert gap["insufficient_data"] and gap["prediction"]["verdict"] == "REVIEW"
        assert "INSUFFICIENT_DATA" in gap["prediction"]["verdict_reason"]
        assert gap["prediction"]["pred_leakage_168h"] is None
        assert any(r["imputed_fields"] == ["iddq_ma"] for r in gap["readings"])

        # The latent part (30 uA in a ~lot_median uA lot, below the 50 uA limit) is screened like any other part.
        latent = (await client.get(f"/api/v1/components/{by_sn['LATENT-001']['id']}/explain")).json()
        assert latent["module_a"]["flag"] is True and latent["verdict"] in ("REVIEW", "REJECT")
        assert latent["static_limit"]["observed_breach"]["leakage_current_ua"] is False
        assert "LATENT-001" in latent["summary"]
        assert lot_median < 20

        after = (await client.get("/api/v1/metrics/benchmark")).json()
        assert after["total_components"] == before["total_components"]  # unlabelled lot excluded from metrics
        assert after["excluded_without_ground_truth"] == before["excluded_without_ground_truth"] + 42

        audit = (await client.get("/api/v1/audit", params={"lot_id": lot_id})).json()
        assert {"Lot ingested", "Lot screened"} <= {e["action"] for e in audit if e["lot_id"] == lot_id}
    finally:
        with SessionLocal() as s:
            s.execute(delete(AuditEvent).where(AuditEvent.lot_id == uuid.UUID(lot_id)))
            s.execute(delete(Lot).where(Lot.id == uuid.UUID(lot_id)))
            s.commit()


@pytest.mark.asyncio
async def test_ingest_rejects_bad_file_without_writing(client):
    with SessionLocal() as s:
        n_before = len(s.scalars(select(Lot.id)).all())
    res = await client.post("/api/v1/ingest", json={"csv": "part_id,foo\nA,1\n"})
    assert res.status_code == 422
    assert "missing_columns" in res.json()["detail"]
    with SessionLocal() as s:
        assert len(s.scalars(select(Lot.id)).all()) == n_before
