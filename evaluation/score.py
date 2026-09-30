"""
Score predictions against separately-held ground truth.

    python -m evaluation.score --predictions preds.csv --truth truth.csv [--json out.json]

`preds.csv` needs: component_id, screen_flag (or verdict), pred_{leakage,iddq,delay}_168h,
and optionally baseline_{param}_168h. `truth.csv` needs: component_id, ground_truth_flag,
optionally ground_truth_label and true_{param}_168h. Components are joined on component_id;
parts without ground truth (e.g. ingested lots) are excluded and counted.

Judge-mode export (detected by a Part_ID column: Part_ID, Predicted_168h, PI_low, PI_high,
Anomaly_score, Flag, Reason) is scored against a raw burn-in file with 168h readings (the same
formats /judge/train accepts). Ground truth is the file's labels if it has them, else the labels-free
rule LFR-1 (evaluation/rules.py). The /judge/score endpoint calls `score_judge_files` on the same
bytes, so this CLI reproduces the UI's numbers exactly.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

import pandas as pd

from evaluation.cost import CostConfig, cost_report
from evaluation.metrics import regression_metrics
from ml_engine.features import PARAMETERS

PRED_COLUMN = {
    "leakage_current_ua": "pred_leakage_168h",
    "iddq_ma": "pred_iddq_168h",
    "propagation_delay_ns": "pred_delay_168h",
}


def _flag(preds: pd.DataFrame) -> pd.Series:
    if "screen_flag" in preds.columns:
        return preds["screen_flag"].astype(str).str.lower().isin(["true", "1"])
    return preds["verdict"].isin(["REVIEW", "REJECT"])


def score(predictions: pd.DataFrame, truth: pd.DataFrame, cost: CostConfig | None = None) -> Dict[str, Any]:
    cost = cost or CostConfig()
    preds = predictions.copy()
    preds["component_id"] = preds["component_id"].astype(str)
    tr = truth.copy()
    if "component_id" in tr.columns:
        tr = tr.set_index("component_id")
    tr.index = tr.index.astype(str)

    joined = preds.set_index("component_id").join(tr, how="left", rsuffix="_truth")
    has_truth = joined["ground_truth_flag"].notna()
    scored = joined[has_truth]
    y_true = scored["ground_truth_flag"].astype(str).str.lower().isin(["true", "1"])
    y_pred = _flag(scored.reset_index())
    y_pred.index = scored.index

    result: Dict[str, Any] = {
        "n_predictions": int(len(preds)),
        "n_scored": int(len(scored)),
        "n_excluded_no_truth": int((~has_truth).sum()),
        "detection": cost_report(y_true.to_numpy(), y_pred.to_numpy(), cost),
    }

    n_def = int(y_true.sum())
    n_ok = int(len(y_true) - n_def)
    result["trivial_policies"] = {
        "flag_all_parts": {"weighted_cost": cost.fp_cost * n_ok, "recall": 1.0 if n_def else 0.0},
        "flag_no_parts": {"weighted_cost": cost.fn_cost * n_def, "recall": 0.0},
    }

    if "ground_truth_label" in scored.columns:
        per_class = {}
        for label, grp in scored.groupby("ground_truth_label"):
            flagged = y_pred.loc[grp.index]
            per_class[str(label)] = {"n": int(len(grp)), "flagged_rate": float(flagged.mean())}
        result["per_class"] = per_class
    if "latent_signal_24h" in scored.columns:
        # Catch rate of drift defects by how much signal they carry at 24h (physics generator).
        per_signal = {}
        for sig, grp in scored[scored["latent_signal_24h"].notna()].groupby("latent_signal_24h"):
            per_signal[str(sig)] = {"n": int(len(grp)), "flagged_rate": float(y_pred.loc[grp.index].mean())}
        result["per_signal_24h"] = per_signal

    regression: Dict[str, Any] = {}
    for p in PARAMETERS:
        tcol = f"true_{p}_168h"
        if tcol not in scored.columns or PRED_COLUMN[p] not in scored.columns:
            continue
        entry = {"model": regression_metrics(scored[tcol], scored[PRED_COLUMN[p]])}
        short = {"leakage_current_ua": "leakage", "iddq_ma": "iddq", "propagation_delay_ns": "delay"}[p]
        lo_c, hi_c = f"pi_lo_{short}_168h", f"pi_hi_{short}_168h"
        if lo_c in scored.columns and hi_c in scored.columns:
            ok = scored[tcol].notna() & scored[lo_c].notna()
            t, lo, hi = scored.loc[ok, tcol], scored.loc[ok, lo_c], scored.loc[ok, hi_c]
            entry["interval"] = {
                "n": int(ok.sum()),
                "empirical_coverage": float(((t >= lo) & (t <= hi)).mean()) if ok.any() else float("nan"),
                "mean_width": float((hi - lo).mean()) if ok.any() else float("nan"),
                "width_min": float((hi - lo).min()) if ok.any() else float("nan"),
                "width_max": float((hi - lo).max()) if ok.any() else float("nan"),
            }
        bcol = f"baseline_{p}_168h"
        if bcol in scored.columns:
            entry["linear_baseline"] = regression_metrics(scored[tcol], scored[bcol])
        regression[p] = entry
    result["regression"] = regression
    return result


def score_export(export: pd.DataFrame, truth: pd.DataFrame, primary: str, cost: CostConfig) -> Dict[str, Any]:
    """Judge-mode metrics: detection on Flag, MAE/RMSE and interval coverage on Predicted_168h vs the
    primary parameter's true 168h value. `truth` is indexed by Part_ID (see ml_engine.judge.truth_frame)."""
    ex = export.copy()
    ex["Part_ID"] = ex["Part_ID"].astype(str)
    ex = ex.set_index("Part_ID")
    tr = truth.copy()
    tr.index = tr.index.astype(str)
    common = ex.index.intersection(tr.index)
    y_true = tr.loc[common, "ground_truth_flag"].astype(bool).to_numpy()
    y_pred = ex.loc[common, "Flag"].astype(int).astype(bool).to_numpy()
    det = cost_report(y_true, y_pred, cost)
    n_def, n_ok = int(y_true.sum()), int(len(y_true) - y_true.sum())
    t = tr.loc[common, f"true_{primary}_168h"].astype(float)
    pr = ex.loc[common, "Predicted_168h"].astype(float)
    lo, hi = ex.loc[common, "PI_low"].astype(float), ex.loc[common, "PI_high"].astype(float)
    ok = t.notna() & lo.notna() & hi.notna()
    per_label = {}
    if "ground_truth_label" in tr.columns:
        lab = tr.loc[common, "ground_truth_label"].astype(str)
        for name, idx in lab.groupby(lab).groups.items():
            per_label[str(name)] = {"n": int(len(idx)), "flagged_rate": float(ex.loc[idx, "Flag"].astype(int).mean())}
    return {
        "n_predictions": int(len(ex)),
        "n_scored": int(len(common)),
        "n_excluded_no_truth": int(len(ex) - len(common)),
        "primary_parameter": primary,
        "detection": det,
        "confusion_matrix": {"tp": det["tp"], "fn": det["fn"], "fp": det["fp"], "tn": det["tn"]},
        "trivial_policies": {
            "flag_all_parts": {"weighted_cost": cost.fp_cost * n_ok, "recall": 1.0 if n_def else 0.0},
            "flag_no_parts": {"weighted_cost": cost.fn_cost * n_def, "recall": 0.0},
        },
        "regression": regression_metrics(t, pr),
        "interval": {"n": int(ok.sum()), "coverage": float(((t[ok] >= lo[ok]) & (t[ok] <= hi[ok])).mean()) if ok.any() else float("nan"),
                     "mean_width": float((hi[ok] - lo[ok]).mean()) if ok.any() else float("nan")},
        "per_label": per_label,
    }


def judge_truth_from_text(truth_text: str, limits: Dict[str, float] | None = None):
    """(truth frame, parameters, truth source) from a raw burn-in file with 168h readings."""
    from data_engine.tabular import read_table
    from evaluation.rules import RULE_ID
    from ml_engine.judge import training_labels, truth_frame

    table = read_table(truth_text)
    if not table.has_168h:
        raise ValueError("the truth file has no 168h readings")
    df = table.df.drop(columns=["insufficient_data"])
    labelled, source = training_labels(df, table.params, table.has_labels, limits)
    source = "file labels" if table.has_labels else f"labels-free rule {RULE_ID}"
    return truth_frame(df, table.params, labels_df=labelled), table.params, source


def score_judge_files(predictions_text: str, truth_text: str, cost: CostConfig,
                      parameter: str | None = None, static_limit: float | None = None) -> Dict[str, Any]:
    import io

    from ml_engine.judge import primary_parameter

    export = pd.read_csv(io.StringIO(predictions_text), dtype={"Part_ID": str})
    truth, params, source = judge_truth_from_text(truth_text)
    primary = primary_parameter(params, parameter)
    if static_limit:
        truth, _, source = judge_truth_from_text(truth_text, {primary: static_limit})
    res = score_export(export, truth, primary, cost)
    res["truth_source"] = source
    return res


def _print_judge(res: Dict[str, Any], cfg: CostConfig) -> None:
    d = res["detection"]
    print(f"scored parts: {res['n_scored']} (excluded without truth: {res['n_excluded_no_truth']}); truth: {res['truth_source']}")
    print(f"TP={d['tp']} FN={d['fn']} FP={d['fp']} TN={d['tn']}  recall={d['recall']:.4f}  precision={d['precision']:.4f}  F2={d['f2']:.4f}")
    print(f"weighted cost={d['weighted_cost']:.1f} (FN_COST={cfg.fn_cost:g}, FP_COST={cfg.fp_cost:g}); "
          f"flag-all cost={res['trivial_policies']['flag_all_parts']['weighted_cost']:.1f}")
    r = res["regression"]
    print(f"{res['primary_parameter']}: MAE={r['mae']:.4f} RMSE={r['rmse']:.4f}  "
          f"PI coverage={res['interval']['coverage']:.4f} (n={res['interval']['n']})")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--json", help="write full metrics JSON here")
    ap.add_argument("--fn-cost", type=float, default=None, help="cost of a missed defect (default from settings: 20)")
    ap.add_argument("--fp-cost", type=float, default=None, help="cost of a false alarm (default from settings: 1)")
    ap.add_argument("--parameter", default=None, help="judge mode: parameter of Predicted_168h (default: as in the UI)")
    ap.add_argument("--static-limit", type=float, default=None, help="judge mode: static limit override for LFR-1")
    args = ap.parse_args(argv)

    cfg = CostConfig.from_settings(fn_cost=args.fn_cost, fp_cost=args.fp_cost)
    with open(args.predictions, encoding="utf-8") as fh:
        head = fh.readline()
    if "Part_ID" in head.split(","):
        with open(args.predictions, encoding="utf-8") as fp, open(args.truth, encoding="utf-8") as ft:
            res = score_judge_files(fp.read(), ft.read(), cfg, args.parameter, args.static_limit)
        _print_judge(res, cfg)
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(res, fh, indent=2)
        return 0
    res = score(pd.read_csv(args.predictions), pd.read_csv(args.truth), cfg)
    d = res["detection"]
    print(f"scored parts: {res['n_scored']} (excluded without truth: {res['n_excluded_no_truth']})")
    print(f"TP={d['tp']} FN={d['fn']} FP={d['fp']} TN={d['tn']}  recall={d['recall']:.4f}  precision={d['precision']:.4f}  F2={d['f2']:.4f}")
    print(f"weighted cost={d['weighted_cost']:.1f} (FN_COST={cfg.fn_cost:g}, FP_COST={cfg.fp_cost:g}); "
          f"per 1000 parts={d['cost_per_1000_parts']:.1f}")
    for p, e in res["regression"].items():
        line = f"{p}: MAE={e['model']['mae']:.4f} RMSE={e['model']['rmse']:.4f}"
        if "linear_baseline" in e:
            line += f"  (linear baseline MAE={e['linear_baseline']['mae']:.4f})"
        print(line)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
