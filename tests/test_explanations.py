"""Explanations are generated from the model's own per-part outputs (replaces DeterministicExplainer tests)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from data_engine.generator import BurnInSyntheticGenerator
from ml_engine.explain import build_explanation
from ml_engine.features import PARAMETERS
from ml_engine.screening import ScreeningModel, early_readings_only, prediction_details


@pytest.fixture(scope="module")
def explained():
    df = BurnInSyntheticGenerator(num_lots=5, components_per_lot=60, random_seed=17).generate_dataset()
    df["lot_id"] = df["lot_id"].astype(str)
    df["component_id"] = df["component_id"].astype(str)
    lots = sorted(df["lot_id"].unique())
    model = ScreeningModel(random_state=0).fit(df[df["lot_id"].isin(lots[:4])])
    test = df[df["lot_id"] == lots[4]]
    preds = model.predict(early_readings_only(test))
    out = []
    for _, row in preds.iterrows():
        pred = {**row.to_dict(), "details": prediction_details(row)}
        readings = test[test["component_id"] == row["component_id"]][["interval_hours", *PARAMETERS]].to_dict("records")
        out.append((row, build_explanation(pred, readings, row["component_id"][:8], "LOT-X")))
    return model, test, preds, out


def test_different_parts_get_different_explanations(explained):
    _, _, _, out = explained
    summaries = {e["summary"] for _, e in out}
    assert len(summaries) == len(out)  # no shared boilerplate text
    contrib_vectors = {tuple(round(c["value"], 6) for c in e["module_b"]["contributions"]) for _, e in out}
    assert len(contrib_vectors) > 0.9 * len(out)


def test_named_top_contributors_are_the_largest_absolute_contributions(explained):
    _, _, _, out = explained
    for _, e in out:
        real = [c for c in e["module_b"]["contributions"] if c["feature"] != "__other__"]
        top_b = max(real, key=lambda c: abs(c["value"]))["feature"]
        assert e["module_b"]["top_contributor"] == top_b
        assert f"Largest Module B contributor to the" in e["summary"] and top_b in e["summary"]
        top_a = max(e["module_a"]["contributions"], key=lambda c: abs(c["contribution"]))["parameter"]
        assert e["module_a"]["top_contributor"] == top_a
        assert f"Largest Module A contributor: {top_a}" in e["summary"]


def test_module_a_contributions_sum_to_score(explained):
    _, _, preds, out = explained
    for row, e in out:
        total = sum(c["contribution"] for c in e["module_a"]["contributions"])
        assert total == pytest.approx(row["module_a_score"], abs=1e-3)


def test_treeshap_contributions_reconstruct_the_forecast(explained):
    model, test, preds, _ = explained
    feats = model.module_b.features(early_readings_only(test))
    contribs = model.module_b.contributions(feats, top_k=len(model.module_b.feature_columns_))
    for (cid, f), c in zip(feats.iterrows(), contribs):
        for p in PARAMETERS:
            total = c[p]["total"]
            assert total == pytest.approx(sum(x["value"] for x in c[p]["top"]) + c[p]["other"] + c[p]["bias"])
            pred = preds.loc[preds["component_id"] == cid]
            col = {"leakage_current_ua": "pred_leakage_168h", "iddq_ma": "pred_iddq_168h",
                   "propagation_delay_ns": "pred_delay_168h"}[p]
            if model.module_b.target == "log_ratio":
                recon = f[f"{p}_v24"] * math.exp(total)
            elif model.module_b.target == "drift":
                recon = f[f"{p}_v24"] + total
            else:
                recon = total
            assert recon == pytest.approx(float(pred[col].iloc[0]), abs=2e-3)


def test_explanation_numbers_come_from_the_prediction(explained):
    _, _, _, out = explained
    row, e = out[0]
    assert f"{row['pred_leakage_168h']:.3f}" in e["summary"] or e["module_b"]["driver_parameter"] != "leakage_current_ua"
    assert f"{row['module_a_score']:.2f}" in e["summary"]
    b = {r["parameter"]: r for r in e["module_b"]["per_parameter"]}
    assert b["leakage_current_ua"]["interval_lower"] == pytest.approx(row["pi_lo_leakage_168h"], abs=1e-4)
    assert b["leakage_current_ua"]["safety_slope"] == pytest.approx(row["safety_slope_leakage_current_ua"], abs=1e-5)
