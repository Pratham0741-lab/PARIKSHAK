"""
Module B model-selection study with NESTED lot-grouped cross-validation.

    python -m evaluation.module_b_study     # writes reports/module_b_study.json and ml_engine/module_b_config.json

Candidates: feature set (v1 original / v2 lot-relative) x target (raw v168 / drift v168-v24 /
log-ratio log(v168/v24)) x a small LightGBM grid, plus the linear-extrapolation baseline.

* Honest estimate: outer GroupKFold over lots (5 folds). Inside each outer fold, an inner
  GroupKFold over the outer-training lots picks the candidate; that candidate is refit on the
  outer-training lots and scored on the untouched outer-test lots.
* Production choice: the candidate with the best inner-CV score over all lots, written to
  ml_engine/module_b_config.json. (Because it is chosen on all lots, the fixed-config numbers
  in the main evaluation report are slightly optimistic for this selection step; the nested
  estimate here is the unbiased one.)
Selection criterion: mean over the three parameters of MAE / linear-baseline MAE on the same parts.
Only 0h/24h-derived features are used (ml_engine/features.py enforces this).
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.run import default_config, generate  # noqa: E402
from evaluation.splits import lot_group_kfold  # noqa: E402
from ml_engine.features import PARAMETERS, build_early_features, extract_targets, feature_columns  # noqa: E402
from ml_engine.module_b_drift import CONFIG_PATH, DriftPredictor, from_target, to_target  # noqa: E402

STUDY_JSON = ROOT / "reports" / "module_b_study.json"

LGB_GRID: List[Dict[str, Any]] = [
    {"n_estimators": 100, "learning_rate": 0.05, "min_child_samples": 5},  # original setting
    {"n_estimators": 300, "learning_rate": 0.03, "num_leaves": 15, "min_child_samples": 20, "reg_lambda": 1.0},
    {"n_estimators": 200, "learning_rate": 0.05, "num_leaves": 7, "min_child_samples": 30, "reg_lambda": 5.0},
]
VARIANTS = [("v1", "raw"), ("v1", "drift"), ("v2", "raw"), ("v2", "drift"), ("v2", "log_ratio")]
CANDIDATES = [
    {"feature_set": fs, "target": tg, "lgb_params": g, "id": f"{fs}-{tg}-g{gi}"}
    for (fs, tg), (gi, g) in itertools.product(VARIANTS, enumerate(LGB_GRID))
]


class Data:
    """Features are computed once: lot-level features use only the part's own lot, so they do not
    depend on which other lots are in a fold."""

    def __init__(self, df: pd.DataFrame):
        self.feats = {fs: build_early_features(df, fs) for fs in ("v1", "v2")}
        self.targets = extract_targets(df)
        self.lot = self.feats["v1"]["lot_id"].astype(str)
        self.ids = self.feats["v1"].index

    def rows(self, lots) -> pd.Index:
        return self.ids[self.lot.isin(lots).to_numpy()]


def _fit_predict(data: Data, cand: Dict[str, Any], train_ids, test_ids, seed: int) -> Dict[str, np.ndarray]:
    F = data.feats[cand["feature_set"]]
    cols = feature_columns(F)
    m = DriftPredictor(feature_set=cand["feature_set"], target=cand["target"], lgb_params=cand["lgb_params"],
                       random_state=seed)
    out = {}
    for p in PARAMETERS:
        y = to_target(data.targets.loc[train_ids, f"{p}_168"].to_numpy(float), F.loc[train_ids, f"{p}_v24"].to_numpy(float),
                      cand["target"])
        model = m._new_model().fit(F.loc[train_ids, cols], y)
        out[p] = from_target(model.predict(F.loc[test_ids, cols]), F.loc[test_ids, f"{p}_v24"].to_numpy(float), cand["target"])
    return out


def _baseline(data: Data, ids) -> Dict[str, np.ndarray]:
    F = data.feats["v1"]
    return {p: (F.loc[ids, f"{p}_v0"] + 7 * (F.loc[ids, f"{p}_v24"] - F.loc[ids, f"{p}_v0"])).to_numpy() for p in PARAMETERS}


def _mae(data: Data, ids, preds: Dict[str, np.ndarray]) -> Dict[str, float]:
    return {p: float(np.mean(np.abs(preds[p] - data.targets.loc[ids, f"{p}_168"].to_numpy()))) for p in PARAMETERS}


def _criterion(data: Data, ids, preds) -> float:
    m, b = _mae(data, ids, preds), _mae(data, ids, _baseline(data, ids))
    return float(np.mean([m[p] / b[p] for p in PARAMETERS]))


def _cv_criterion(data: Data, cand, lots, n_splits: int, seed: int) -> float:
    """OOF predictions over `lots` with lot-grouped CV, scored once on all OOF parts."""
    preds = {p: [] for p in PARAMETERS}
    all_ids = []
    for f in lot_group_kfold(lots, n_splits=min(n_splits, len(lots)), seed=seed):
        tr, te = data.rows(f.train_lots), data.rows(f.test_lots)
        pr = _fit_predict(data, cand, tr, te, seed)
        for p in PARAMETERS:
            preds[p].append(pr[p])
        all_ids.extend(te)
    ids = pd.Index(all_ids)
    return _criterion(data, ids, {p: np.concatenate(v) for p, v in preds.items()})


def run_study(cfg: Dict[str, Any] | None = None) -> Dict[str, Any]:
    cfg = {**default_config(), **(cfg or {})}
    seed = cfg["seed"]
    data = Data(generate(cfg))
    lots = sorted(data.lot.unique())

    outer = lot_group_kfold(lots, n_splits=cfg["n_splits"], seed=seed)
    nested = {p: [] for p in PARAMETERS}
    per_cand = {c["id"]: {p: [] for p in PARAMETERS} for c in CANDIDATES}
    base = {p: [] for p in PARAMETERS}
    all_ids, chosen = [], []
    for f in outer:
        tr_lots = sorted(f.train_lots)
        scores = {c["id"]: _cv_criterion(data, c, tr_lots, 4, seed) for c in CANDIDATES}
        best = min(CANDIDATES, key=lambda c: (scores[c["id"]], c["id"]))
        chosen.append({"fold": f.fold, "chosen": best["id"], "inner_criterion": scores[best["id"]]})
        tr, te = data.rows(f.train_lots), data.rows(f.test_lots)
        all_ids.extend(te)
        pr = _fit_predict(data, best, tr, te, seed)
        bl = _baseline(data, te)
        for p in PARAMETERS:
            nested[p].append(pr[p])
            base[p].append(bl[p])
        for c in CANDIDATES:  # transparency only: NOT used for any selection
            pc = _fit_predict(data, c, tr, te, seed)
            for p in PARAMETERS:
                per_cand[c["id"]][p].append(pc[p])

    ids = pd.Index(all_ids)
    cat = lambda d: {p: np.concatenate(v) for p, v in d.items()}  # noqa: E731
    truth = {p: data.targets.loc[ids, f"{p}_168"].to_numpy() for p in PARAMETERS}

    def summary(preds):
        preds = cat(preds)
        return {p: {"mae": float(np.mean(np.abs(preds[p] - truth[p]))),
                    "rmse": float(np.sqrt(np.mean((preds[p] - truth[p]) ** 2)))} for p in PARAMETERS}

    final_scores = {c["id"]: _cv_criterion(data, c, lots, cfg["n_splits"], seed) for c in CANDIDATES}
    final = min(CANDIDATES, key=lambda c: (final_scores[c["id"]], c["id"]))

    return {
        "config": {"seed": seed, "num_lots": cfg["num_lots"], "components_per_lot": cfg["components_per_lot"],
                   "outer_folds": cfg["n_splits"], "inner_folds": 4,
                   "criterion": "mean over parameters of MAE / linear-baseline MAE"},
        "candidates": [{k: c[k] for k in ("id", "feature_set", "target", "lgb_params")} for c in CANDIDATES],
        "nested_estimate": {"per_fold_choice": chosen, "metrics": summary(nested)},
        "linear_baseline": summary(base),
        "original_v1_raw_g0": summary(per_cand["v1-raw-g0"]),
        "per_candidate_outer_metrics_not_used_for_selection": {cid: summary(v) for cid, v in per_cand.items()},
        "production_choice": {"id": final["id"], "inner_cv_criterion": final_scores[final["id"]],
                              "all_candidate_criteria": final_scores},
    }


def _round(o, nd=4):
    if isinstance(o, float):
        return round(o, nd)
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v, nd) for v in o]
    return o


def main() -> int:
    res = _round(run_study())
    STUDY_JSON.parent.mkdir(parents=True, exist_ok=True)
    STUDY_JSON.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    choice = next(c for c in CANDIDATES if c["id"] == res["production_choice"]["id"])
    CONFIG_PATH.write_text(json.dumps({
        "feature_set": choice["feature_set"], "target": choice["target"], "lgb_params": choice["lgb_params"],
        "selected_by": "python -m evaluation.module_b_study (lot-grouped CV over all lots; see reports/module_b_study.json)",
        "candidate_id": choice["id"],
    }, indent=2) + "\n", encoding="utf-8")

    print("Nested (honest) estimate vs baselines, MAE:")
    for p in PARAMETERS:
        print(f"  {p:22s} nested={res['nested_estimate']['metrics'][p]['mae']:.4f}  "
              f"original(v1-raw-g0)={res['original_v1_raw_g0'][p]['mae']:.4f}  linear={res['linear_baseline'][p]['mae']:.4f}")
    print("Per-fold choice:", [c["chosen"] for c in res["nested_estimate"]["per_fold_choice"]])
    print("Production choice:", res["production_choice"]["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
