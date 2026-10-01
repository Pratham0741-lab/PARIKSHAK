"""Judge mode: labels-free training, 0h/24h-only prediction, export format, and API == CLI scoring."""

from __future__ import annotations

import asyncio
import json

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from data_engine.physics_generator import PhysicsBurnInGenerator
from data_engine.tabular import read_table
from evaluation import score as score_cli
from evaluation.cost import CostConfig
from evaluation.rules import Z_CUT, apply_rule
from ml_engine import judge
from ml_engine.features import PARAMETERS
from ml_engine.screening import ScreeningModel


def wide_csv(df: pd.DataFrame, hours=(0, 24, 96, 168), params=PARAMETERS, labels=False) -> str:
    w = df.pivot_table(index=["component_id", "lot_id"], columns="interval_hours", values=list(params))
    w.columns = [f"{p}_{h}h" for p, h in w.columns]
    w = w[[c for c in w.columns if int(c.rsplit("_", 1)[1][:-1]) in hours]].reset_index()
    w = w.rename(columns={"component_id": "part_id"})
    if labels:
        m = df.drop_duplicates("component_id").set_index("component_id")
        w["ground_truth_flag"] = w["part_id"].map(m["ground_truth_flag"])
        w["ground_truth_label"] = w["part_id"].map(m["ground_truth_label"])
    return w.to_csv(index=False)


@pytest.fixture(scope="module")
def data():
    df = PhysicsBurnInGenerator(num_lots=8, components_per_lot=40, random_seed=11).generate_dataset()
    lots = sorted(df["lot_id"].unique())
    return df[df["lot_id"].isin(lots[:6])], df[df["lot_id"].isin(lots[6:])]


@pytest.fixture(scope="module")
def trained(data):
    train_df, _ = data
    return judge.train(read_table(wide_csv(train_df)), "train.csv", CostConfig())


def test_reader_accepts_wide_long_and_parameter_subsets(data):
    train_df, _ = data
    t = read_table(wide_csv(train_df))
    assert (t.layout, t.params, t.has_labels, t.has_168h) == ("wide", list(PARAMETERS), False, True)
    long = train_df[["component_id", "lot_id", "interval_hours", "leakage_current_ua"]].to_csv(index=False)
    tl = read_table(long)
    assert tl.layout == "long" and tl.params == ["leakage_current_ua"] and tl.n_parts == t.n_parts
    blank = wide_csv(train_df).splitlines()
    cells = blank[1].split(",")
    cells[3] = ""  # one 0h value blank
    tb = read_table("\n".join([blank[0], ",".join(cells), *blank[2:]]))
    assert tb.df.loc[tb.df["component_id"] == cells[0], "insufficient_data"].all()
    assert not (tb.df.drop(columns=["component_id", "lot_id"]) == 0).all(axis=None)  # never zero-filled


def test_labels_free_rule_is_fixed_and_needs_no_labels(data):
    train_df, _ = data
    assert Z_CUT == 3.5
    unlabelled = train_df.drop(columns=["ground_truth_flag", "ground_truth_label"])
    r = apply_rule(unlabelled, PARAMETERS)
    assert set(r["ground_truth_label"]) <= {"NORMAL", "LIMIT", "DRIFT", "LEVEL"}
    assert 0 < r["ground_truth_flag"].mean() < 0.5


def test_training_without_labels_and_export_format(trained):
    jm, oof, _ = trained
    assert jm.info["label_source"].startswith("labels-free rule")
    assert jm.info["evaluation_split"].startswith("lot-grouped") and not jm.info["single_lot"]
    assert list(oof.columns) == judge.EXPORT_COLUMNS
    assert jm.info["n_parts"] == 240 and jm.info["n_lots"] == 6


def test_prediction_sees_only_early_readings(trained, data):
    jm, _, _ = trained
    _, test_df = data
    seen = []
    orig = jm.model.predict

    def spy(df, **kw):
        seen.append(df.copy())
        return orig(df, **kw)

    jm.model.predict = spy
    try:
        full, _ = judge.predict(jm, read_table(wide_csv(test_df, labels=True)))
        early, rows = judge.predict(jm, read_table(wide_csv(test_df, hours=(0, 24))))
    finally:
        jm.model.predict = orig
    for df in seen:
        assert set(df["interval_hours"]) <= {0, 24}
        assert not {"ground_truth_flag", "ground_truth_label"} & set(df.columns)
    pd.testing.assert_frame_equal(full, early)  # 96h/168h/labels in the file change nothing
    assert rows[0]["explanation"]["module_a"]["threshold"] is not None


def test_single_lot_file_uses_within_file_split(data):
    train_df, _ = data
    one = train_df[train_df["lot_id"] == sorted(train_df["lot_id"].unique())[0]]
    jm, _, _ = judge.train(read_table(wide_csv(one, params=("leakage_current_ua",))), "one.csv", CostConfig())
    assert jm.info["single_lot"] and judge.SINGLE_LOT_NOTE in jm.info["evaluation_split"]
    assert jm.info["parameters"] == ["leakage_current_ua"]


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    from backend.app.api.v1 import judge as judge_api
    from backend.app.main import app

    monkeypatch.setattr(judge_api, "judge_dir", lambda: tmp_path / "judge")
    judge_api._ACTIVE.update(model=None, loaded_from=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    judge_api._ACTIVE.update(model=None, loaded_from=None)


@pytest.mark.asyncio
async def test_api_train_predict_score_matches_cli(client, data, tmp_path, capsys):
    train_df, test_df = data
    r = await client.post("/api/v1/judge/train", json={"csv": wide_csv(train_df), "filename": "train.csv"})
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    for _ in range(600):
        st = (await client.get(f"/api/v1/judge/jobs/{job_id}")).json()
        if st["state"] != "running":
            break
        await asyncio.sleep(0.5)
    assert st["state"] == "done", st
    info = (await client.get("/api/v1/judge/model")).json()["model"]
    assert (info["file"], info["n_parts"], info["n_lots"]) == ("train.csv", 240, 6)

    r = await client.post("/api/v1/judge/predict", json={"csv": wide_csv(test_df, hours=(0, 24)), "filename": "test.csv"})
    assert r.status_code == 200, r.text
    preds = (await client.get("/api/v1/judge/predictions.csv")).text
    assert preds.splitlines()[0] == ",".join(judge.EXPORT_COLUMNS)

    truth = wide_csv(test_df, labels=True)
    ui = (await client.post("/api/v1/judge/score", json={"truth_csv": truth, "truth_filename": "truth.csv"})).json()
    (tmp_path / "preds.csv").write_text(preds, encoding="utf-8")
    (tmp_path / "truth.csv").write_text(truth, encoding="utf-8")
    out = tmp_path / "m.json"
    argv = ui["reproduce_with"].split()[3:]  # drop "python -m evaluation.score"
    argv = [str(tmp_path / a) if a in ("preds.csv", "truth.csv") else a for a in argv]
    assert score_cli.main([*argv, "--json", str(out)]) == 0
    cli = json.loads(out.read_text())
    for key in ("detection", "confusion_matrix", "regression", "interval", "trivial_policies"):
        assert cli[key] == ui[key], key
    assert ui["truth_source"] == "file labels"
    assert np.isfinite(ui["regression"]["mae"])


def test_small_file_uses_pretrained_with_file_calibration_and_guard_banner(data):
    train_df, _ = data
    pretrained = ScreeningModel(random_state=0).fit(PhysicsBurnInGenerator(num_lots=6, components_per_lot=40,
                                                                           random_seed=99).generate_dataset())
    one = train_df[train_df["lot_id"] == sorted(train_df["lot_id"].unique())[0]]
    jm, _, _ = judge.train(read_table(wide_csv(one)), "one.csv", CostConfig(), pretrained=pretrained, max_flag_rate=0.0)
    tried = {p["path"]: p for p in jm.info["paths_tried"]}
    assert set(tried) == {judge.PATH_CALIBRATED, judge.PATH_PRETRAINED}
    # the lower validation cost wins; the flag-rate ceiling is a warning, not a gate
    assert jm.info["path"] == min(tried, key=lambda k: tried[k]["validation_cost"])
    assert jm.model.module_b is pretrained.module_b  # Module B is the pretrained one either way
    assert jm.model.thresholds_["threshold_b"] == pretrained.thresholds_["threshold_b"]
    assert any("too small" in b for b in jm.info["banner"])
    assert jm.info["flag_rate_warning"] and "ceiling" in jm.info["flag_rate_warning"]
    assert not any("ceiling" in b for b in jm.info["banner"])


def test_guard_rejects_only_paths_that_do_not_beat_flag_everything():
    m = {"detection": {"tp": 5, "fp": 50, "fn": 0, "tn": 45, "n": 100, "weighted_cost": 50.0},
         "trivial_policies": {"flag_all_parts": {"weighted_cost": 95.0}}}
    assert judge._guard(m) == [] and judge._flag_rate(m) == 0.55  # high flag rate alone does not fail the guard
    m["detection"]["weighted_cost"] = 95.0
    assert len(judge._guard(m)) == 1 and "flag-everything" in judge._guard(m)[0]
