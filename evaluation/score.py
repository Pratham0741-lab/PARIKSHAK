"""
Score predictions against separately-held ground truth.

    python -m evaluation.score --predictions preds.csv --truth truth.csv [--json out.json]

`preds.csv` needs: component_id, screen_flag (or verdict), pred_{leakage,iddq,delay}_168h,
and optionally baseline_{param}_168h. `truth.csv` needs: component_id, ground_truth_flag,
optionally ground_truth_label and true_{param}_168h. Components are joined on component_id;
parts without ground truth (e.g. ingested lots) are excluded and counted.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

import pandas as pd

from evaluation.metrics import detection_metrics, regression_metrics
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


def score(predictions: pd.DataFrame, truth: pd.DataFrame) -> Dict[str, Any]:
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
        "detection": detection_metrics(y_true.to_numpy(), y_pred.to_numpy()),
    }

    if "ground_truth_label" in scored.columns:
        per_class = {}
        for label, grp in scored.groupby("ground_truth_label"):
            flagged = y_pred.loc[grp.index]
            per_class[str(label)] = {"n": int(len(grp)), "flagged_rate": float(flagged.mean())}
        result["per_class"] = per_class

    regression: Dict[str, Any] = {}
    for p in PARAMETERS:
        tcol = f"true_{p}_168h"
        if tcol not in scored.columns or PRED_COLUMN[p] not in scored.columns:
            continue
        entry = {"model": regression_metrics(scored[tcol], scored[PRED_COLUMN[p]])}
        bcol = f"baseline_{p}_168h"
        if bcol in scored.columns:
            entry["linear_baseline"] = regression_metrics(scored[tcol], scored[bcol])
        regression[p] = entry
    result["regression"] = regression
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", required=True)
    ap.add_argument("--truth", required=True)
    ap.add_argument("--json", help="write full metrics JSON here")
    args = ap.parse_args(argv)

    res = score(pd.read_csv(args.predictions), pd.read_csv(args.truth))
    d = res["detection"]
    print(f"scored parts: {res['n_scored']} (excluded without truth: {res['n_excluded_no_truth']})")
    print(f"TP={d['tp']} FN={d['fn']} FP={d['fp']} TN={d['tn']}  recall={d['recall']:.4f}  precision={d['precision']:.4f}")
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
