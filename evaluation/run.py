"""
Reproducible held-out evaluation of the screening system.

    python -m evaluation.run            # writes reports/evaluation_results.json + SIH26170_EVALUATION_REPORT.md

Data: the seeded synthetic generator with the same configuration used to seed the database.
Split: GroupKFold over LOTS (every part is predicted by a model that never saw its lot).
Held-out parts are predicted from 0h/24h readings only; labels and 168h values are held back
and joined only in evaluation.score. A TRAIN (in-sample, optimistic) column is reported
alongside so the generalisation gap is visible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import settings  # noqa: E402
from data_engine.generator import BurnInSyntheticGenerator  # noqa: E402
from evaluation.cost import CostConfig  # noqa: E402
from evaluation.crossfit import cross_fit_predict, extract_truth  # noqa: E402
from evaluation.score import score  # noqa: E402
from ml_engine.features import PARAMETERS  # noqa: E402
from ml_engine.module_b_drift import linear_extrapolation_baseline  # noqa: E402
from ml_engine.screening import ScreeningModel, early_readings_only  # noqa: E402

REPORT_JSON = ROOT / "reports" / "evaluation_results.json"
REPORT_MD = ROOT / "SIH26170_EVALUATION_REPORT.md"
STUDY_JSON = ROOT / "reports" / "module_b_study.json"


def default_config() -> Dict[str, Any]:
    return {
        "seed": settings.SYNTHETIC_RANDOM_SEED,
        "num_lots": settings.DEFAULT_NUM_LOTS,
        "components_per_lot": settings.DEFAULT_COMPONENTS_PER_LOT,
        "n_splits": 5,
        "fn_cost": settings.FN_COST,
        "fp_cost": settings.FP_COST,
        "recall_target": settings.RECALL_TARGET,
        "threshold_strategy": settings.THRESHOLD_STRATEGY,
    }


def cost_of(cfg: Dict[str, Any]) -> CostConfig:
    return CostConfig(fn_cost=cfg["fn_cost"], fp_cost=cfg["fp_cost"], recall_target=cfg["recall_target"])


def model_factory(cfg: Dict[str, Any], strategy: str | None = None):
    strat = strategy or cfg["threshold_strategy"]
    return lambda: ScreeningModel(cost=cost_of(cfg), random_state=cfg["seed"], threshold_strategy=strat)


def generate(cfg: Dict[str, Any]) -> pd.DataFrame:
    return BurnInSyntheticGenerator(
        num_lots=cfg["num_lots"],
        components_per_lot=cfg["components_per_lot"],
        random_seed=cfg["seed"],
    ).generate_dataset()


def _round(obj: Any, nd: int = 4) -> Any:
    if isinstance(obj, float):
        return round(obj, nd)
    if isinstance(obj, dict):
        return {k: _round(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round(v, nd) for v in obj]
    return obj


def train_in_sample(df: pd.DataFrame, cfg: Dict[str, Any]) -> pd.DataFrame:
    """TRAIN (optimistic): fit on every lot and predict the same parts."""
    model = model_factory(cfg)().fit(df)
    early = early_readings_only(df)
    preds = model.predict(early)
    preds["component_id"] = preds["component_id"].astype(str)
    base = linear_extrapolation_baseline(early)
    for p in PARAMETERS:
        preds[f"baseline_{p}_168h"] = preds["component_id"].map(base[f"{p}_168"].rename(index=str))
    return preds


def evaluate(cfg: Dict[str, Any] | None = None, include_train: bool = True, out_dir: Path | None = None) -> Dict[str, Any]:
    cfg = {**default_config(), **(cfg or {})}
    df = generate(cfg)
    truth = extract_truth(df)
    cf = cross_fit_predict(df, model_factory(cfg), n_splits=cfg["n_splits"], seed=cfg["seed"])

    results: Dict[str, Any] = {
        "config": cfg,
        "split": {
            "method": "GroupKFold over lots (lot-level cross-fitting); 96h/168h and labels hidden at prediction time",
            "n_lots": int(df["lot_id"].nunique()),
            "n_parts": int(df["component_id"].nunique()),
            "n_defective": int(df.drop_duplicates("component_id")["ground_truth_flag"].sum()),
            "folds": [
                {"fold": f.fold, "n_train_lots": len(f.train_lots), "n_test_lots": len(f.test_lots),
                 "n_test_parts": len(f.test_component_ids),
                 "threshold_a": cf.models[f.fold].thresholds_["threshold_a"],
                 "threshold_b": cf.models[f.fold].thresholds_["threshold_b"],
                 "validation_recall": cf.models[f.fold].thresholds_["validation"]["recall"]}
                for f in cf.folds
            ],
        },
        "held_out": score(cf.predictions, truth, cost_of(cfg)),
    }
    # Transparency: the alternative threshold strategy, evaluated with the same held-out protocol.
    alt = "joint" if cfg["threshold_strategy"] == "separate" else "separate"
    df_s = df.assign(lot_id=df["lot_id"].astype(str), component_id=df["component_id"].astype(str))
    alt_models, alt_preds = {}, []
    for f in cf.folds:  # same fitted models, thresholds re-chosen from their own inner-CV validation scores
        alt_models[f.fold] = cf.models[f.fold].rethreshold(alt)
        alt_preds.append(alt_models[f.fold].predict(early_readings_only(df_s[df_s["lot_id"].isin(f.test_lots)])))

    class _Alt:  # minimal stand-in with the fields used below
        predictions = pd.concat(alt_preds, ignore_index=True)
        models = alt_models

    cf_alt = _Alt()
    alt_score = score(cf_alt.predictions, truth, cost_of(cfg))
    results["alternative_strategy"] = {
        "strategy": alt,
        "detection": {k: alt_score["detection"][k] for k in ("recall", "precision", "f2", "weighted_cost", "fn", "fp")},
        "module_b_disabled_folds": sum(1 for m in cf_alt.models.values() if m.thresholds_["threshold_b"] == float("inf")),
    }
    if STUDY_JSON.exists():
        study = json.loads(STUDY_JSON.read_text(encoding="utf-8"))
        results["module_b_selection"] = {
            "production_choice": study["production_choice"]["id"],
            "nested_estimate": study["nested_estimate"]["metrics"],
            "per_fold_choice": [c["chosen"] for c in study["nested_estimate"]["per_fold_choice"]],
            "original_v1_raw_g0": study["original_v1_raw_g0"],
            "linear_baseline": study["linear_baseline"],
            "n_candidates": len(study["candidates"]),
        }
    if include_train:
        results["train_optimistic"] = score(train_in_sample(df, cfg), truth, cost_of(cfg))
    results = _round(results)

    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        cf.predictions.drop(columns=["b_contributions"], errors="ignore").to_csv(out_dir / "oof_predictions.csv", index=False)
        truth.to_csv(out_dir / "truth.csv")
    return results


def _pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def render_markdown(res: Dict[str, Any]) -> str:
    cfg, split, ho = res["config"], res["split"], res["held_out"]
    tr = res.get("train_optimistic")
    lines = [
        "# SIH26170 Evaluation Report (held-out lots)",
        "",
        "Generated by `python -m evaluation.run`. Every number below is computed by code from a fresh run;",
        "`reports/evaluation_results.json` holds the same values and `tests/test_evaluation_report.py`",
        "fails if a fresh run does not reproduce them exactly.",
        "",
        "## Protocol",
        "",
        f"- Data: seeded synthetic generator, seed **{cfg['seed']}**, **{split['n_lots']} lots**, "
        f"**{split['n_parts']} parts** ({split['n_defective']} labelled defective).",
        f"- Split: {split['method']}; **{cfg['n_splits']} folds**.",
        "- Each held-out part is predicted by a model trained on other lots only, using its 0h/24h readings.",
        "- Ground truth (labels, true 168h values) is joined only at scoring time (`python -m evaluation.score`).",
        "- The TRAIN column refits on all lots and scores the same parts. It is **optimistic** and shown only",
        "  to make the generalisation gap visible.",
        "",
        f"- Decision cost: a missed defect (FN) costs **{cfg['fn_cost']:g}**, a false alarm (FP) **{cfg['fp_cost']:g}**"
        + (f"; recall target {cfg['recall_target']:g}" if cfg.get("recall_target") else "; no recall constraint") + ".",
        "- Module A / Module B thresholds are chosen per fold by minimising that cost on an inner lot-grouped",
        "  CV over the fold's training lots only (never on the held-out lots).",
        f"- Threshold strategy: **{cfg['threshold_strategy']}** (separate = each module's threshold minimises cost on",
        "  its own, as PS 26170 requires Module B to flag on its own safety-slope rule; decision = union).",
        "",
        "| Fold | Train lots | Test lots | Test parts | Chosen threshold A | Chosen threshold B | Inner-CV recall |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for f in split["folds"]:
        lines.append(
            f"| {f['fold']} | {f['n_train_lots']} | {f['n_test_lots']} | {f['n_test_parts']} | "
            f"{f['threshold_a']} | {f['threshold_b']} | {_pct(f['validation_recall'])} |"
        )

    def det_row(name: str, key: str, fmt=lambda v: f"{v}") -> str:
        a = fmt(ho["detection"][key])
        b = fmt(tr["detection"][key]) if tr else "n/a"
        return f"| {name} | **{a}** | {b} |"

    lines += [
        "",
        "## Anomaly detection (flag = verdict REVIEW or REJECT)",
        "",
        "| Metric | Held-out lots | TRAIN (optimistic) |",
        "|---|---:|---:|",
        det_row("Recall", "recall", _pct),
        det_row("Precision", "precision", _pct),
        det_row("F2 (beta=2)", "f2", _pct),
        det_row("F1", "f1", _pct),
        det_row(f"Weighted cost (FN x{cfg['fn_cost']:g} + FP x{cfg['fp_cost']:g})", "weighted_cost"),
        det_row("Weighted cost per 1,000 parts", "cost_per_1000_parts"),
        f"| Reference: cost of flagging EVERY part | {ho['trivial_policies']['flag_all_parts']['weighted_cost']:g} | "
        f"{tr['trivial_policies']['flag_all_parts']['weighted_cost'] if tr else 'n/a':g} |",
        f"| Reference: cost of flagging NO part | {ho['trivial_policies']['flag_no_parts']['weighted_cost']:g} | "
        f"{tr['trivial_policies']['flag_no_parts']['weighted_cost'] if tr else 'n/a':g} |",
        det_row("False-negative rate", "false_negative_rate", _pct),
        det_row("TP", "tp"),
        det_row("FN (escapes)", "fn"),
        det_row("FP", "fp"),
        det_row("TN", "tn"),
    ]
    alt = res.get("alternative_strategy")
    if alt:
        ad = alt["detection"]
        lines += [
            "",
            f"Alternative threshold strategy **{alt['strategy']}** under the same held-out protocol: recall "
            f"{_pct(ad['recall'])}, precision {_pct(ad['precision'])}, F2 {_pct(ad['f2'])}, weighted cost "
            f"{ad['weighted_cost']:g} (FN {ad['fn']}, FP {ad['fp']}); Module B's slope rule was disabled "
            f"(k = +inf) in {alt['module_b_disabled_folds']} of {len(split['folds'])} folds.",
        ]
    lines += [
        "",
        "### Catch rate by defect class (held-out)",
        "",
        "| Class | Parts | Flagged (held-out) | Flagged (TRAIN) |",
        "|---|---:|---:|---:|",
    ]
    for label, v in sorted(ho.get("per_class", {}).items()):
        t = tr["per_class"][label]["flagged_rate"] if tr else None
        lines.append(f"| `{label}` | {v['n']} | **{_pct(v['flagged_rate'])}** | {_pct(t) if t is not None else 'n/a'} |")

    lines += [
        "",
        "## Module B: 168h forecast accuracy",
        "",
        "| Parameter | Held-out MAE | Held-out RMSE | Linear baseline MAE (held-out) | TRAIN MAE (optimistic) "
        "| 90% interval: held-out coverage | Mean width (min-max) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for p in [q for q in PARAMETERS if q in ho["regression"]]:
        e = ho["regression"][p]
        t = tr["regression"][p]["model"]["mae"] if tr else None
        lines.append(
            f"| `{p}` | **{e['model']['mae']:.4f}** | {e['model']['rmse']:.4f} | "
            f"{e['linear_baseline']['mae']:.4f} | {t if t is not None else 'n/a'} | "
            + (f"**{_pct(e['interval']['empirical_coverage'])}** | {e['interval']['mean_width']:.3f} "
               f"({e['interval']['width_min']:.3f}-{e['interval']['width_max']:.3f}) |" if "interval" in e else "n/a | n/a |")
        )
    sel = res.get("module_b_selection")
    if sel:
        lines += [
            "",
            "### Module B model selection (nested lot-grouped CV, `python -m evaluation.module_b_study`)",
            "",
            f"{sel['n_candidates']} candidates (feature set v1/v2 x target raw/drift/log-ratio x LightGBM grid) were",
            "compared. In each outer fold an inner lot-grouped CV over that fold's training lots picked the",
            f"candidate (choices: {', '.join(sel['per_fold_choice'])}); it was then scored on the untouched outer lots.",
            f"The production configuration (`{sel['production_choice']}`, `ml_engine/module_b_config.json`) was chosen",
            "by lot-grouped CV over all lots, so the fixed-config MAE in the table above is slightly optimistic",
            "for that choice; the nested column below is the unbiased estimate.",
            "",
            "| Parameter | Nested MAE (selection inside CV) | Original model (v1, raw target) | Linear baseline |",
            "|---|---:|---:|---:|",
        ]
        for p in PARAMETERS:
            lines.append(
                f"| `{p}` | **{sel['nested_estimate'][p]['mae']:.4f}** | {sel['original_v1_raw_g0'][p]['mae']:.4f} | "
                f"{sel['linear_baseline'][p]['mae']:.4f} |"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-write", action="store_true", help="print only; do not overwrite report files")
    args = ap.parse_args(argv)

    res = json.loads(json.dumps(evaluate(out_dir=ROOT / "reports"), sort_keys=True))
    md = render_markdown(res)
    if not args.no_write:
        REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
        REPORT_JSON.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        REPORT_MD.write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
