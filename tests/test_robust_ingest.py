"""T6 robust ingest: aliases, layouts, units, blanks, duplicates, non-numeric cells, 10k+ streamed parse."""

from __future__ import annotations

import io
import time
import uuid

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from backend.app.core.database import SessionLocal
from backend.app.main import app
from backend.app.models import AuditEvent, BurnInReading, Component, Lot
from backend.app.services.ingest import parse_csv
from data_engine.tabular import interpret_header, read_table

P = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")


@pytest.mark.parametrize("header,param,hour,how", [
    ("Iddq_0h", "iddq_ma", 0, "alias"),
    ("IDDQ_24H", "iddq_ma", 24, "alias"),
    ("I_0", "leakage_current_ua", 0, "alias"),
    ("T0", "leakage_current_ua", 0, "bare-interval"),
    ("t_168", "leakage_current_ua", 168, "bare-interval"),
    ("leakage (nA) @ 24 h", "leakage_current_ua", 24, "alias"),
    ("tpd_168h_ps", "propagation_delay_ns", 168, "alias"),
    ("Propagation Delay 96h", "propagation_delay_ns", 96, "alias"),
    ("leakge_current_24h", "leakage_current_ua", 24, "fuzzy"),
    ("LEAKAGE_CURRENT_UA_0H", "leakage_current_ua", 0, "exact"),
])
def test_header_aliases_case_insensitive_and_fuzzy(header, param, hour, how):
    c = interpret_header(header, "leakage_current_ua")
    assert (c.role, c.param, c.hour) == ("reading", param, hour)
    assert c.how.startswith(how)


def test_unrecognised_and_off_grid_columns_are_reported_not_guessed():
    assert interpret_header("delay 48h", "leakage_current_ua").role == "ignored"
    assert interpret_header("operator_notes", "leakage_current_ua").role == "ignored"
    t = read_table("sn,I_0,I_24,notes\nA,1,2,x\nB,1,2,y\n")
    assert any("notes" in i["message"] for i in t.issues)


def test_bare_interval_columns_follow_test_parameter():
    text = "part,test_parameter,T0,T24,T168\nA,iddq,1.1,1.2,1.3\nB,iddq,1.0,1.1,1.2\n"
    t = read_table(text)
    assert t.params == ["iddq_ma"]
    assert t.df.loc[(t.df.component_id == "A") & (t.df.interval_hours == 24), "iddq_ma"].item() == 1.2


def _wide_rows(n=3):
    return [[f"P{i}", 10 + i, 1.5, 4.2, 10.5 + i, 1.5, 4.2] for i in range(n)]


def test_wide_long_and_tidy_layouts_give_the_same_readings():
    wide = "part_id,leakage_current_ua_0h,iddq_ma_0h,propagation_delay_ns_0h,leakage_current_ua_24h,iddq_ma_24h,propagation_delay_ns_24h\n"
    wide += "\n".join(",".join(map(str, r)) for r in _wide_rows())
    long = "Serial,Hours,Leakage_uA,IDDQ_mA,Delay_ns\n" + "\n".join(
        f"{r[0]},{h},{r[1 + 3 * k]},{r[2 + 3 * k]},{r[3 + 3 * k]}" for r in _wide_rows() for k, h in enumerate((0, 24)))
    tidy = "part,interval,parameter,value\n" + "\n".join(
        f"{r[0]},{h},{name},{r[1 + j + 3 * k]}" for r in _wide_rows() for k, h in enumerate((0, 24))
        for j, name in enumerate(("leakage", "iddq", "delay")))
    frames = [read_table(x) for x in (wide, long, tidy)]
    assert [f.layout for f in frames] == ["wide", "long", "tidy"]
    cols = ["component_id", "interval_hours", *P]
    for f in frames[1:]:
        assert f.df[cols].equals(frames[0].df[cols])


def test_units_are_detected_converted_and_need_confirmation():
    t = read_table("part,I_0 (nA),I_24 (nA),tpd_0h_ps,tpd_24h_ps\nA,12000,12500,4200,4300\nB,11000,11500,4100,4150\n")
    a0 = t.df[(t.df.component_id == "A") & (t.df.interval_hours == 0)]
    assert a0["leakage_current_ua"].item() == pytest.approx(12.0)
    assert a0["propagation_delay_ns"].item() == pytest.approx(4.2)
    assert t.units["leakage_current_ua"]["detected"] == {"na": "file header"} and t.needs_unit_confirmation
    # an assumed (canonical) unit whose values are implausible is flagged too
    t2 = read_table("part,I_0,I_24\nA,12000,12500\nB,11000,11500\n")
    assert t2.units["leakage_current_ua"]["implausible"] and t2.needs_unit_confirmation
    # a unit column, and an explicit override
    t3 = read_table("part,unit,I_0,I_24\nA,nA,12000,12500\nB,nA,11000,11500\n")
    assert t3.df["leakage_current_ua"].max() == pytest.approx(12.5)
    t4 = read_table("part,I_0,I_24\nA,12000,12500\nB,11000,11500\n", unit_overrides={"leakage": "nA"})
    assert t4.df["leakage_current_ua"].max() == pytest.approx(12.5)
    # canonical units, plausible values: no confirmation needed
    assert not read_table("part,I_0,I_24\nA,12,12.5\nB,11,11.5\n").needs_unit_confirmation


def test_missing_96h_blank_cells_duplicates_and_non_numeric_with_row_links():
    text = ("part_id,leakage_current_ua_0h,iddq_ma_0h,propagation_delay_ns_0h,"
            "leakage_current_ua_24h,iddq_ma_24h,propagation_delay_ns_24h,leakage_current_ua_168h,iddq_ma_168h,propagation_delay_ns_168h\n"
            "A,12,1.5,4.2,12.1,1.5,4.2,12.4,1.5,4.2\n"
            "B,13,1.5,4.2,,1.5,4.2,13.4,1.5,4.2\n"           # line 3: blank 24h leakage
            "C,11,1.5,4.2,11.2,oops,4.2,11.4,1.5,4.2\n"     # line 4: non-numeric
            "A,99,9,9,99,9,9,99,9,9\n")                     # line 5: duplicate
    res = parse_csv(text)
    assert res.ok and [p.part_id for p in res.parts] == ["A", "B", "C"]
    assert 96 not in res.parts[0].values  # no 96h columns: nothing invented
    b = res.parts[1]
    assert b.values[24]["leakage_current_ua"] == pytest.approx(11.65) and b.insufficient_data  # lot median, never 0
    assert b.imputed[24] == ["leakage_current_ua"]
    rows = {(i.row, i.part_id) for i in res.issues if i.severity == "error"}
    assert (4, "C") in rows and (5, "A") in rows
    assert res.duplicate_part_ids == 1 and res.non_numeric_cells == 1
    assert all(v != 0 for p in res.parts for h in p.values for v in p.values[h].values())


def test_single_parameter_file_is_accepted_and_reports_parameters_used():
    res = parse_csv("part,I_0,I_24\nA,12,12.5\nB,11,11.4\n")
    assert res.ok and res.parameters_used == ["leakage_current_ua"]
    assert all(p.values[0]["iddq_ma"] is None and not p.insufficient_data for p in res.parts)  # absent, not imputed


def _big_csv(n: int, seed: int = 0) -> str:
    rng = np.random.default_rng(seed)
    base = rng.lognormal(np.log(10), 0.1, n)
    buf = io.StringIO()
    buf.write("Serial Number;Leakage_0h (uA);IDDQ_0h;tpd_0h;Leakage_24h (uA);IDDQ_24h;tpd_24h\n")
    for i in range(n):
        buf.write(f"SN{i:06d};{base[i]:.4f};{1.5 + 0.01 * rng.standard_normal():.4f};{4.2:.3f};"
                  f"{base[i] * 1.01:.4f};{1.5:.4f};{4.2:.3f}\n")
    return buf.getvalue()


def test_ten_thousand_parts_parse_as_a_stream():
    text = _big_csv(12000)
    t0 = time.perf_counter()
    t = read_table(io.StringIO(text))  # a text stream, read line by line
    elapsed = time.perf_counter() - t0
    assert t.n_parts == 12000 and t.layout == "wide" and t.params == list(P)
    assert elapsed < 30, elapsed
    import hashlib

    assert t.sha256 == hashlib.sha256(text.encode()).hexdigest()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=600) as c:
        yield c


@pytest.mark.asyncio
async def test_stream_endpoint_ingests_10k_parts_and_requires_unit_confirmation(client):
    text = _big_csv(10000, seed=1)
    lot_number = f"TEST-BIG-{uuid.uuid4().hex[:8]}"
    v = await client.post("/api/v1/ingest/stream", params={"validate_only": True, "filename": "big.csv"},
                          content=text.encode(), headers={"Content-Type": "text/csv"})
    assert v.status_code == 201 and v.json()["validation"]["parts_accepted"] == 10000

    nA = text.replace("Leakage_0h (uA)", "Leakage_0h (nA)").replace("Leakage_24h (uA)", "Leakage_24h (nA)")
    r = await client.post("/api/v1/ingest/stream", params={"lot_number": lot_number}, content=nA.encode())
    assert r.status_code == 409 and "units" in r.json()["detail"]  # converted unit: confirmation required
    r = await client.post("/api/v1/ingest/stream", params={"lot_number": lot_number, "units_confirmed": True,
                                                            "filename": "big.csv"}, content=nA.encode())
    assert r.status_code == 201, r.text[:500]
    lot_id = uuid.UUID(r.json()["lot_id"])
    try:
        assert r.json()["screening"]["n_screened"] == 10000
        with SessionLocal() as s:
            assert s.scalar(select(func.count()).select_from(Component).where(Component.lot_id == lot_id)) == 10000
            vmax = s.scalar(select(func.max(BurnInReading.leakage_current_ua)).join(Component)
                            .where(Component.lot_id == lot_id))
            assert vmax < 1.0  # nA converted to uA (~0.01 uA), not stored raw
            lot = s.get(Lot, lot_id)
            assert lot.unit == "uA" and lot.source_detail["units_in_file"]["leakage_current_ua"] == ["na"]
    finally:
        with SessionLocal() as s:
            s.execute(delete(AuditEvent).where(AuditEvent.lot_id == lot_id))
            s.execute(delete(Lot).where(Lot.id == lot_id))
            s.commit()


def _single_param_csv(params, n=40, seed=5):
    """A ~nominal lot with only `params` at 0/24/96/168h, plus one latent part (30 uA-type excursion)."""
    rng = np.random.default_rng(seed)
    base = {"leakage_current_ua": 10.0, "iddq_ma": 1.5, "propagation_delay_ns": 4.2}
    header = ["part_id"] + [f"{p}_{h}h" for h in (0, 24, 96, 168) for p in params]
    rows = [",".join(header)]
    for i in range(n):
        v0 = {p: base[p] * float(rng.lognormal(0, 0.05)) for p in params}
        rows.append(",".join([f"SP{i:03d}"] + [f"{v0[p] * (1 + 0.002 * h / 24):.4f}" for h in (0, 24, 96, 168) for p in params]))
    rows.append(",".join(["LATENT-001"] + [f"{3 * base[p] * (1 + 0.2 * h / 24):.4f}" for h in (0, 24, 96, 168) for p in params]))
    return "\n".join(rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [("leakage_current_ua",), ("iddq_ma",), ("propagation_delay_ns",), P])
async def test_single_parameter_ingest_screens_with_absent_parameters_dropped(client, params):
    lot_number = f"TEST-SP-{uuid.uuid4().hex[:8]}"
    r = await client.post("/api/v1/ingest", json={"csv": _single_param_csv(params), "lot_number": lot_number})
    assert r.status_code == 201, r.text[:500]
    body = r.json()
    lot_id = body["lot_id"]
    try:
        assert body["validation"]["parameters_used"] == list(params)
        assert body["screening"]["n_screened"] == 41
        lot = next(lt for lt in (await client.get("/api/v1/lots")).json() if lt["id"] == lot_id)
        assert lot["source_detail"]["parameters_used"] == list(params)
        if len(params) == 1:  # the lot is charted on its own parameter, with that parameter's unit and limit
            from ml_engine.verdict_engine import ScreeningVerdictEngine
            assert lot["test_parameter"] == params[0]
            assert lot["unit"] == {"leakage_current_ua": "uA", "iddq_ma": "mA", "propagation_delay_ns": "ns"}[params[0]]
            assert lot["static_limit"] == ScreeningVerdictEngine.datasheet_limits()[params[0]]
        parts = await client.get(f"/api/v1/lots/{lot_id}/parts")  # the UI's lot view
        assert parts.status_code == 200 and len(parts.json()) == 41
        comps = (await client.get("/api/v1/components", params={"lot_id": lot_id, "page_size": 100})).json()["items"]
        latent = next(c for c in comps if c["serial_number"] == "LATENT-001")
        prof = (await client.get(f"/api/v1/components/{latent['id']}/profile")).json()
        pred = prof["prediction"]
        short = {"leakage_current_ua": "leakage", "iddq_ma": "iddq", "propagation_delay_ns": "delay"}
        for p in P:  # absent parameters: no forecast (never a number made up from missing inputs)
            assert (pred[f"pred_{short[p]}_168h"] is None) == (p not in params)
        assert pred["verdict"] in ("REVIEW", "REJECT")  # 3x the lot level on the present parameter(s)
        assert "model_beats_flag_all" in body["screening"]
        ex = await client.get(f"/api/v1/components/{latent['id']}/explain")
        assert ex.status_code == 200
    finally:
        with SessionLocal() as s:
            s.execute(delete(AuditEvent).where(AuditEvent.lot_id == uuid.UUID(lot_id)))
            s.execute(delete(Lot).where(Lot.id == uuid.UUID(lot_id)))
            s.commit()
