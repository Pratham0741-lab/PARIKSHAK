"""
Module A decision-score study on DEVELOPMENT data (never the evaluation seed).

    python -m evaluation.module_a_dev_study      # writes reports/module_a_dev_study.json

Module A is unsupervised; this study only decides which of its lot-relative statistics is used
as the decision score. To avoid tuning on the evaluation lots, it uses independently generated
datasets (seeds in DEV_SEEDS, all different from the evaluation seed). Each dataset is split by
lot (6 lots fit the detector, 4 held-out lots are scored). The candidate with the highest mean
ROC-AUC (defective vs normal) over the development datasets is selected.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import settings  # noqa: E402
from data_engine.physics_generator import make_generator  # noqa: E402
from ml_engine.features import PARAMETERS  # noqa: E402
from ml_engine.module_a_outlier import LotOutlierDetector  # noqa: E402
from ml_engine.screening import early_readings_only  # noqa: E402

DEV_SEEDS = (101, 202, 303)
OUT = {"legacy": ROOT / "reports" / "module_a_dev_study.json",
       "physics": ROOT / "reports" / "module_a_dev_study_physics.json"}
CLASSES = ("LEVEL_OUTLIER", "SUBTLE_MULTIVARIATE", "STEEP_DRIFT", "LATE_DRIFT")


def candidates(r: pd.DataFrame) -> dict:
    z = r[[f"robust_z_{p}" for p in PARAMETERS]].to_numpy()
    return {
        "composite_v1": r["module_a_composite"].to_numpy(),
        "mahalanobis": r["module_a_mahalanobis"].to_numpy(),
        "isolation_forest": r["module_a_isolation"].to_numpy(),
        "max_abs_z": np.abs(z).max(axis=1),
        "sum_z_squared": (z ** 2).sum(axis=1),
        "max_positive_z": np.maximum(z, 0).max(axis=1),
        "sum_positive_z": np.maximum(z, 0).sum(axis=1),
    }


def run(generator: str = "legacy") -> dict:
    assert settings.SYNTHETIC_RANDOM_SEED not in DEV_SEEDS, "development seeds must differ from the evaluation seed"
    rows = []
    for seed in DEV_SEEDS:
        n_lots = 10 if generator == "legacy" else 12
        df = make_generator(generator, num_lots=n_lots, components_per_lot=100, random_seed=seed).generate_dataset()
        lots = sorted(df["lot_id"].unique())
        n_fit = int(round(0.6 * len(lots)))
        fit_df, score_df = df[df["lot_id"].isin(lots[:n_fit])], df[df["lot_id"].isin(lots[n_fit:])]
        det = LotOutlierDetector().fit(early_readings_only(fit_df))
        r = det.predict(early_readings_only(score_df)).set_index("component_id")
        meta = score_df.drop_duplicates("component_id").set_index("component_id")
        r = r.join(meta[["ground_truth_flag", "ground_truth_label"]])
        y = r["ground_truth_flag"].astype(bool).to_numpy()
        for name, s in candidates(r.reset_index()).items():
            row = {"seed": seed, "score": name, "auc_all": float(roc_auc_score(y, s))}
            for c in CLASSES:
                m = r["ground_truth_label"].isin([c, "NORMAL"]).to_numpy()
                row[f"auc_{c}"] = float(roc_auc_score(y[m], s[m]))
            rows.append(row)
    table = pd.DataFrame(rows).groupby("score").mean(numeric_only=True).drop(columns="seed")
    best = table["auc_all"].idxmax()
    return {
        "generator": generator,
        "dev_seeds": list(DEV_SEEDS),
        "evaluation_seed_excluded": settings.SYNTHETIC_RANDOM_SEED,
        "criterion": "mean ROC-AUC (defective vs normal) over development datasets",
        "mean_auc": {k: {c: round(v, 4) for c, v in d.items()} for k, d in table.to_dict(orient="index").items()},
        "selected": best,
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--generator", choices=("legacy", "physics"), default="legacy")
    res = run(ap.parse_args().generator)
    out = OUT[res["generator"]]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for k, v in sorted(res["mean_auc"].items(), key=lambda kv: kv[1]["auc_all"]):
        print(f"{k:18s} all={v['auc_all']:.3f}  " + "  ".join(f"{c[:6]}={v['auc_' + c]:.3f}" for c in CLASSES))
    print("selected:", res["selected"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
