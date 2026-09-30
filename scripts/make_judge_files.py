"""
Write example judge-mode files (physics generator, seed 7 - not the evaluation seed 42):

  examples/judge/train.csv   12 lots with 0/24/96/168h readings, NO labels (thresholds come from LFR-1)
  examples/judge/test.csv    4 other lots, 0h and 24h only (what /judge/predict receives)
  examples/judge/truth.csv   the same 4 lots with 168h readings and the generator's labels

    python scripts/make_judge_files.py [--lots 16 --parts 80 --seed 7]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_engine.physics_generator import PhysicsBurnInGenerator  # noqa: E402
from ml_engine.features import PARAMETERS  # noqa: E402


def wide(df, hours, labels=False):
    w = df.pivot_table(index=["component_id", "lot_id"], columns="interval_hours", values=list(PARAMETERS))
    w.columns = [f"{p}_{h}h" for p, h in w.columns]
    w = w[[c for c in w.columns if int(c.rsplit("_", 1)[1][:-1]) in hours]].reset_index()
    w = w.rename(columns={"component_id": "part_id"})
    meta = df.drop_duplicates("component_id").set_index("component_id")
    w.insert(2, "temperature_c", w["part_id"].map(meta["temperature_c"]))
    if labels:
        w["ground_truth_flag"] = w["part_id"].map(meta["ground_truth_flag"])
        w["ground_truth_label"] = w["part_id"].map(meta["ground_truth_label"])
    return w.round(6)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lots", type=int, default=16)
    ap.add_argument("--parts", type=int, default=80)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(ROOT / "examples" / "judge"))
    a = ap.parse_args()
    df = PhysicsBurnInGenerator(num_lots=a.lots, components_per_lot=a.parts, random_seed=a.seed).generate_dataset()
    lots = sorted(df["lot_id"].unique())
    n_test = max(1, a.lots // 4)
    train, test = df[df["lot_id"].isin(lots[:-n_test])], df[df["lot_id"].isin(lots[-n_test:])]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    wide(train, (0, 24, 96, 168)).to_csv(out / "train.csv", index=False)
    wide(test, (0, 24)).to_csv(out / "test.csv", index=False)
    wide(test, (0, 24, 96, 168), labels=True).to_csv(out / "truth.csv", index=False)
    print(f"wrote {out}: train {train['lot_id'].nunique()} lots, test {test['lot_id'].nunique()} lots")
    return 0


if __name__ == "__main__":
    sys.exit(main())
