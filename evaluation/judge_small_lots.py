"""
S3 check of judge-mode paths on small unlabelled files (nothing here is used to choose any setting).

    python -m evaluation.judge_small_lots     # writes reports/judge_small_lots.json

* Pretrained model = the production pipeline on the default synthetic data (physics, seed 42, 40 x 100).
* Example files: train on examples/judge/train.csv (no labels), predict examples/judge/test.csv, score
  against examples/judge/truth.csv (generator labels).
* 20 fresh lots (physics, seed 2027, never used before): for each lot i, the training file is lot i
  (with 168h, labels removed) and the test file is lot i+1 (0h/24h only), scored against its generator labels.
For every path: flag rate and FN-weighted cost on the TEST parts vs the cost of flagging every test part.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_engine.physics_generator import PhysicsBurnInGenerator  # noqa: E402
from data_engine.tabular import read_table  # noqa: E402
from evaluation.cost import CostConfig, cost_report  # noqa: E402
from ml_engine import judge  # noqa: E402
from ml_engine.features import PARAMETERS  # noqa: E402
from ml_engine.screening import ScreeningModel  # noqa: E402

FRESH_SEED = 2027  # S3 check; F2 used --seed 8642 (new lots, not used before)


def wide(df, hours, labels=False):
    w = df.pivot_table(index=["component_id", "lot_id"], columns="interval_hours", values=list(PARAMETERS))
    w.columns = [f"{p}_{h}h" for p, h in w.columns]
    w = w[[c for c in w.columns if int(c.rsplit("_", 1)[1][:-1]) in hours]].reset_index().rename(columns={"component_id": "part_id"})
    if labels:
        m = df.drop_duplicates("component_id").set_index("component_id")
        w["ground_truth_flag"] = w["part_id"].map(m["ground_truth_flag"])
    return w.to_csv(index=False)


def _score(model, test_csv, truth: pd.Series, cost, primary):
    ex, _ = judge.predict(judge.JudgeModel(model=model, info={"parameters": list(PARAMETERS), "primary_parameter": primary}),
                          read_table(test_csv))
    y = truth.reindex(ex["Part_ID"]).fillna(False).to_numpy(bool)
    f = ex["Flag"].astype(bool).to_numpy()
    r = cost_report(y, f, cost)
    return {"n": r["n"], "flagged": int(f.sum()), "defective": int(y.sum()), "fn": r["fn"], "fp": r["fp"],
            "cost": r["weighted_cost"], "flag_all_cost": cost.fp_cost * int((~y).sum())}


def _sum(rows):
    keys = ("n", "flagged", "defective", "fn", "fp", "cost", "flag_all_cost")
    tot = {k: float(sum(r[k] for r in rows)) for k in keys}
    tot["flag_rate"] = tot["flagged"] / tot["n"] if tot["n"] else 0.0
    tot["recall"] = (tot["defective"] - tot["fn"]) / tot["defective"] if tot["defective"] else float("nan")
    return tot


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=FRESH_SEED, help="seed of the 20 fresh lots")
    seed = ap.parse_args().seed
    cost = CostConfig.from_settings()
    primary = PARAMETERS[0]
    print("fitting the pretrained production pipeline (physics, seed 42, 40 x 100)...", flush=True)
    base = PhysicsBurnInGenerator(num_lots=40, components_per_lot=100, random_seed=42).generate_dataset()
    pretrained = ScreeningModel(cost=cost, random_state=42).fit(base)

    out = {"pretrained": "physics seed 42, 40 lots x 100 parts", "cost": cost.as_dict(),
           "max_flag_rate": judge.DEFAULT_MAX_FLAG_RATE, "min_parts_full_train": judge.MIN_PARTS_FULL_TRAIN}

    # ---- example files
    ex_dir = ROOT / "examples" / "judge"
    train_t = read_table((ex_dir / "train.csv").read_text())
    truth_ex = pd.read_csv(ex_dir / "truth.csv").set_index("part_id")["ground_truth_flag"].astype(bool)
    test_csv = (ex_dir / "test.csv").read_text()
    jm, _, _ = judge.train(train_t, "train.csv", cost, pretrained=pretrained)
    full, _, _ = judge.train(train_t, "train.csv", cost, pretrained=None)
    df = train_t.df[~train_t.df["insufficient_data"]].drop(columns=["insufficient_data"])
    df, _ = judge.training_labels(df, train_t.params, False)
    cal, _ = judge._calibrated(pretrained, df, judge.truth_frame(df, train_t.params, df), primary, cost, 42, None)
    out["example_files"] = {
        "chosen_path": jm.info["path"], "banner": jm.info["banner"],
        "validation_on_training_file": [{k: p[k] for k in ("path", "flag_rate", "rejected_because")} for p in jm.info["paths_tried"]],
        "test_lots": {judge.PATH_FULL: _score(full.model, test_csv, truth_ex, cost, primary),
                      judge.PATH_CALIBRATED: _score(cal, test_csv, truth_ex, cost, primary),
                      judge.PATH_PRETRAINED: _score(pretrained, test_csv, truth_ex, cost, primary),
                      "chosen": _score(jm.model, test_csv, truth_ex, cost, primary)},
    }

    # ---- 20 fresh single-lot files
    fresh = PhysicsBurnInGenerator(num_lots=20, components_per_lot=100, random_seed=seed).generate_dataset()
    lots = sorted(fresh["lot_id"].unique())
    rows = {judge.PATH_CALIBRATED: [], judge.PATH_PRETRAINED: [], "chosen": []}
    chosen_paths = []
    for i, lot in enumerate(lots):
        tr = fresh[fresh["lot_id"] == lot]
        te = fresh[fresh["lot_id"] == lots[(i + 1) % len(lots)]]
        t = read_table(wide(tr, (0, 24, 96, 168)))
        truth = te.drop_duplicates("component_id").set_index("component_id")["ground_truth_flag"].astype(bool)
        test = wide(te, (0, 24))
        jm, _, _ = judge.train(t, f"lot{i}.csv", cost, pretrained=pretrained)
        chosen_paths.append(jm.info["path"])
        d = t.df[~t.df["insufficient_data"]].drop(columns=["insufficient_data"])
        d, _ = judge.training_labels(d, t.params, False)
        cal, _ = judge._calibrated(pretrained, d, judge.truth_frame(d, t.params, d), primary, cost, 42, None)
        rows[judge.PATH_CALIBRATED].append(_score(cal, test, truth, cost, primary))
        rows[judge.PATH_PRETRAINED].append(_score(pretrained, test, truth, cost, primary))
        rows["chosen"].append(_score(jm.model, test, truth, cost, primary))
        print(f"lot {i:2d}: chosen {jm.info['path']}", flush=True)
    out["fresh_20_single_lots"] = {"seed": seed, "chosen_path_counts": pd.Series(chosen_paths).value_counts().to_dict(),
                                   "totals": {k: _sum(v) for k, v in rows.items()}}

    path = ROOT / "reports" / ("judge_small_lots.json" if seed == FRESH_SEED else f"judge_small_lots_seed{seed}.json")
    path.write_text(json.dumps(out, indent=2, default=lambda o: o.item() if isinstance(o, np.generic) else str(o)) + "\n")
    print(json.dumps({"example_files": out["example_files"]["test_lots"], "chosen": out["example_files"]["chosen_path"],
                      "fresh": out["fresh_20_single_lots"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
