"""
Judge mode: train on an uploaded file that includes 168h readings, then predict for files that have
only 0h/24h readings.

Training (`train`):
  * Labels are optional. If the file has labels, they are used ONLY to pick the Module A/B thresholds
    on out-of-fold predictions (ScreeningModel's inner lot-grouped CV). Otherwise the labels-free rule
    LFR-1 (evaluation/rules.py), computed from the file's own 168h readings, stands in for them.
  * Honest estimate: lot-grouped out-of-fold (OOF) predictions over the file's lots, scored with the
    same function the /judge/score endpoint and `python -m evaluation.score` use. A file with fewer than
    MIN_LOTS lots is split within the file: each lot's parts are randomly assigned (seeded) to
    WITHIN_FILE_GROUPS groups that act as lots. This split is labelled "single-lot, less reliable",
    because parts of one lot share its conditions, so the estimate is optimistic.
  * The final model is fitted on the whole file and persisted with the file's sha256.
Prediction (`predict`): only 0h/24h readings reach the model (96h/168h and label columns are
removed first). The output is the export table (EXPORT_COLUMNS) plus a compact explanation per part.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from evaluation.cost import CostConfig
from evaluation.crossfit import cross_fit_predict
from evaluation.rules import RULE_ID, RULE_TEXT, apply_rule
from ml_engine.features import PARAMETERS
from ml_engine.screening import MODULE_B_TARGET_CLASSES, PRED_COLUMN, SHORT, ScreeningModel, early_readings_only

MIN_LOTS = 3
WITHIN_FILE_GROUPS = 5
EXPORT_COLUMNS = ["Part_ID", "Predicted_168h", "PI_low", "PI_high", "Anomaly_score", "Flag", "Reason"]
SINGLE_LOT_NOTE = "single-lot, less reliable"
INSUFFICIENT_REASON = "REVIEW: INSUFFICIENT_DATA: a 0h/24h reading is missing or invalid; no model score computed."


def primary_parameter(params: List[str], requested: Optional[str] = None) -> str:
    """The parameter reported in Predicted_168h: the requested one if present, else the first of
    leakage, IDDQ, delay that the file contains."""
    if requested and requested in params:
        return requested
    return next(p for p in PARAMETERS if p in params)


def training_labels(df: pd.DataFrame, params: List[str], has_labels: bool,
                    limits: Optional[Dict[str, float]] = None) -> tuple[pd.DataFrame, str]:
    """Attach ground_truth_flag / ground_truth_label (one per part) used for threshold selection."""
    rule = apply_rule(df, params, limits)
    out = df.drop(columns=[c for c in ("ground_truth_flag", "ground_truth_label") if c in df.columns])
    if has_labels:
        meta = df.drop_duplicates("component_id").set_index("component_id")
        flag = meta["ground_truth_flag"].astype(bool)
        file_label = meta["ground_truth_label"] if "ground_truth_label" in meta else pd.Series("", index=meta.index)
        if file_label.isin(MODULE_B_TARGET_CLASSES).any():
            label = file_label.where(flag, "NORMAL")
            source = "file labels (flag and defect type)"
        else:
            # The file says which parts are defective but not which are drift defects; the drift type
            # (for calibrating Module B's k) comes from LFR-1's DRIFT criterion.
            drift = rule["ground_truth_label"].reindex(flag.index).isin(["DRIFT", "LIMIT"])
            label = pd.Series(np.where(flag & drift, "DRIFT", np.where(flag, "DEFECT", "NORMAL")), index=flag.index)
            source = f"file labels (flag); drift type from {RULE_ID}"
    else:
        flag = rule["ground_truth_flag"].reindex(out["component_id"].unique()).fillna(False).astype(bool)
        label = rule["ground_truth_label"].reindex(flag.index).fillna("NORMAL")
        source = f"labels-free rule {RULE_ID} on the file's 168h readings"
    out["ground_truth_flag"] = out["component_id"].map(flag).fillna(False).astype(bool)
    out["ground_truth_label"] = out["component_id"].map(label).fillna("NORMAL")
    return out, source


def within_file_groups(df: pd.DataFrame, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    comps = df.drop_duplicates("component_id")[["component_id", "lot_id"]]
    group = {}
    for lot, ids in comps.groupby("lot_id")["component_id"]:
        ids = ids.to_numpy()
        for i, cid in enumerate(rng.permutation(ids)):
            group[cid] = f"{lot}#g{i % WITHIN_FILE_GROUPS}"
    out = df.copy()
    out["lot_id"] = out["component_id"].map(group)
    return out


def export_frame(pred: pd.DataFrame, primary: str, insufficient_ids=()) -> pd.DataFrame:
    """One row per part in EXPORT_COLUMNS. Anomaly_score = max(Module A score / threshold A, Module B z / k)."""
    ta, tb = pred["threshold_a"].astype(float), pred["threshold_b"].astype(float)
    ra = pred["module_a_score"].astype(float) / ta
    rb = (pred["module_b_score"].astype(float) / tb).where(np.isfinite(tb) & (tb > 0))
    anomaly = np.fmax(ra.to_numpy(), rb.to_numpy())
    out = pd.DataFrame({
        "Part_ID": pred["component_id"].astype(str),
        "Predicted_168h": pred[PRED_COLUMN[primary]].astype(float).round(6),
        "PI_low": pred[f"pi_lo_{SHORT[primary]}_168h"].astype(float).round(6),
        "PI_high": pred[f"pi_hi_{SHORT[primary]}_168h"].astype(float).round(6),
        "Anomaly_score": np.round(anomaly, 6),
        "Flag": pred["screen_flag"].astype(bool).astype(int),
        "Reason": pred["verdict"].astype(str) + ": " + pred["verdict_reason"].astype(str),
    })
    if len(insufficient_ids):
        extra = pd.DataFrame({"Part_ID": list(insufficient_ids), "Predicted_168h": np.nan, "PI_low": np.nan,
                              "PI_high": np.nan, "Anomaly_score": np.nan, "Flag": 1, "Reason": INSUFFICIENT_REASON})
        out = pd.concat([out, extra], ignore_index=True)
    return out.sort_values("Part_ID").reset_index(drop=True)[EXPORT_COLUMNS]


def explanation(row: pd.Series, params: List[str]) -> Dict[str, Any]:
    """Compact per-part explanation: the parameter driving each module and how far past its threshold it is."""
    def f(x):
        x = float(x)
        return None if not np.isfinite(x) else round(x, 4)

    a_top = max(params, key=lambda p: float(np.nan_to_num(row.get(f"a_contrib_{p}", np.nan), nan=-1)))
    b_top = max(params, key=lambda p: float(np.nan_to_num(row.get(f"z_{p}", np.nan), nan=-np.inf)))
    return {
        "module_a": {"score": f(row["module_a_score"]), "threshold": f(row["threshold_a"]), "flag": bool(row["module_a_flag"]),
                     "top_parameter": a_top, "robust_z": f(row[f"robust_z_{a_top}"]),
                     "value_0_24h_mean": f(row[f"a_value_{a_top}"]), "lot_median": f(row[f"a_lot_median_{a_top}"])},
        "module_b": {"score": f(row["module_b_score"]), "k": f(row["threshold_b"]), "flag": bool(row["module_b_flag"]),
                     "top_parameter": b_top, "predicted_rate": f(row[f"rate_{b_top}"]),
                     "safety_slope": f(row[f"safety_slope_{b_top}"])},
        "static_limit": {"observed_breach": bool(row["observed_static_breach"]),
                         "forecast_breach": bool(row["predicted_limit_breach"])},
    }


@dataclass
class JudgeModel:
    model: ScreeningModel
    info: Dict[str, Any] = field(default_factory=dict)

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"judge_{self.info['data_sha256'][:16]}.joblib"
        self.model.save(path)
        (directory / "active.json").write_text(json.dumps({**self.info, "artifact": path.name}, indent=2, default=str),
                                               encoding="utf-8")
        return path

    @staticmethod
    def load_active(directory: Path) -> Optional[JudgeModel]:
        meta = directory / "active.json"
        if not meta.exists():
            return None
        info = json.loads(meta.read_text(encoding="utf-8"))
        path = directory / info["artifact"]
        if not path.exists():
            return None
        return JudgeModel(model=ScreeningModel.load(path), info=info)


# Small-file policy (fixed in advance, not tuned): below these sizes a file is not used to train Module B.
MIN_PARTS_FULL_TRAIN = 500
DEFAULT_MAX_FLAG_RATE = 0.40
PATH_FULL = "trained on file"
PATH_CALIBRATED = "pretrained + file-level outlier calibration"
PATH_PRETRAINED = "pretrained (no calibration)"


def _guard(metrics: Dict[str, Any], max_flag_rate: float) -> List[str]:
    """Reasons a path is rejected: validation cost not below flag-everything, or flag rate above the ceiling."""
    d = metrics["detection"]
    reasons = []
    flag_all = metrics["trivial_policies"]["flag_all_parts"]["weighted_cost"]
    if d["weighted_cost"] >= flag_all:
        reasons.append(f"validation cost {d['weighted_cost']:.0f} does not beat flag-everything ({flag_all:.0f})")
    rate = (d["tp"] + d["fp"]) / d["n"] if d["n"] else 0.0
    if rate > max_flag_rate:
        reasons.append(f"flag rate {100 * rate:.1f}% exceeds the {100 * max_flag_rate:.0f}% ceiling")
    return reasons


def _calibrated(pretrained: ScreeningModel, work: pd.DataFrame, truth: pd.DataFrame, primary: str,
                cost: CostConfig, seed: int, limits) -> tuple[ScreeningModel, pd.DataFrame]:
    """Pretrained Module B (and its k) unchanged; Module A refitted on the file (lot-relative, label-free) and
    its threshold chosen on the file's truth. Validation: threshold A chosen on 4 of 5 random part groups and
    applied to the 5th (out-of-group), so no part's flag uses its own label."""
    import copy

    from evaluation.thresholds import choose_threshold
    from ml_engine.module_a_outlier import LotOutlierDetector

    early = early_readings_only(work)
    early = early[[c for c in early.columns if c not in ("ground_truth_flag", "ground_truth_label")]]
    m = copy.copy(pretrained)
    m.module_a = LotOutlierDetector(random_state=seed).fit(early)
    pred = m.predict(early, limits=limits)
    pred["component_id"] = pred["component_id"].astype(str)
    y = truth.reindex(pred["component_id"])["ground_truth_flag"].fillna(False).to_numpy(bool)
    forced = (pred["module_b_flag"] | pred["observed_static_breach"]).to_numpy(bool)
    score = pred["module_a_score"].to_numpy(float)
    groups = within_file_groups(work, seed).drop_duplicates("component_id").set_index("component_id")["lot_id"]
    g = pred["component_id"].map(groups).to_numpy()
    oof_flag = np.zeros(len(pred), bool)
    for grp in np.unique(g):
        te = g == grp
        t = choose_threshold(score[~te], y[~te], cost, forced[~te])["threshold"]
        oof_flag[te] = forced[te] | (score[te] >= t)
    val_export = export_frame(pred, primary)
    val_export["Flag"] = val_export["Part_ID"].map(dict(zip(pred["component_id"], oof_flag.astype(int), strict=True)))
    t_all = choose_threshold(score, y, cost, forced)["threshold"]
    m.thresholds_ = {**pretrained.thresholds_, "threshold_a": t_all,
                     "source": "threshold A calibrated on the file; Module B and k pretrained"}
    return m, val_export


def train(table, filename: str, cost: Optional[CostConfig] = None, seed: int = 42,
          static_limit: Optional[float] = None, progress=lambda msg: None,
          pretrained: Optional[ScreeningModel] = None, max_flag_rate: float = DEFAULT_MAX_FLAG_RATE,
          min_parts: int = MIN_PARTS_FULL_TRAIN) -> tuple[JudgeModel, pd.DataFrame, pd.DataFrame]:
    """Returns (model, validation export, truth table used for the validation score).

    Paths:
      1. trained on file - only if the file has >= MIN_LOTS lots and >= min_parts parts (lot-grouped OOF);
      2. pretrained + file-level outlier calibration (needs `pretrained`, the production pipeline for these
         parameters). This is the fallback whenever path 1 is not eligible or fails the guard (_guard), and is
         kept (with the banner) even if it fails the guard too.
    "pretrained (no calibration)" is validated and reported for reference only; it is never selected."""
    from evaluation.score import score_export

    if not table.has_168h:
        raise ValueError("training needs 168h readings (the model learns the 0h/24h -> 168h drift)")
    cost = cost or CostConfig()
    params = table.params
    primary = primary_parameter(params)
    limits = {primary: static_limit} if static_limit else None
    df = table.df[~table.df["insufficient_data"]].drop(columns=["insufficient_data"])
    df, label_source = training_labels(df, params, table.has_labels, limits)
    n_parts = int(df["component_id"].nunique())
    truth = truth_frame(df, params, labels_df=df)

    single = table.n_lots < MIN_LOTS
    small = single or n_parts < min_parts
    candidates = []  # (path, model, validation export, split description)
    if not small or pretrained is None:
        work = within_file_groups(df, seed) if single else df
        n_groups = work["lot_id"].nunique()
        split = (f"{SINGLE_LOT_NOTE}: {table.n_lots} lot(s) split within the file into {n_groups} random part groups"
                 if single else f"lot-grouped {min(5, n_groups)}-fold over {n_groups} lots")
        progress(f"out-of-fold evaluation ({split})")
        res = cross_fit_predict(work, lambda: ScreeningModel(cost=cost, random_state=seed), n_splits=min(5, n_groups), seed=seed)
        progress("fitting the final model on the whole file")
        candidates.append((PATH_FULL, ScreeningModel(cost=cost, random_state=seed).fit(work),
                           export_frame(res.predictions, primary), split))
    if pretrained is not None:
        progress("pretrained Module B + Module A calibrated on the file")
        m, val = _calibrated(pretrained, df, truth, primary, cost, seed, limits)
        candidates.append((PATH_CALIBRATED, m, val,
                           f"threshold A out-of-group over {WITHIN_FILE_GROUPS} random part groups of the file"))
        early = early_readings_only(df)
        early = early[[c for c in early.columns if c not in ("ground_truth_flag", "ground_truth_label")]]
        candidates.append((PATH_PRETRAINED, pretrained, export_frame(pretrained.predict(early, limits=limits), primary),
                           "whole file (never seen by the pretrained model)"))

    banner, paths = [], []
    if small and pretrained is not None:
        banner.append(f"file too small to train Module B ({table.n_lots} lot(s), {n_parts} parts; needs >= {MIN_LOTS} "
                      f"lots and >= {min_parts} parts)")
    chosen = None
    for path, model, val, split in candidates:
        metrics = score_export(val, truth, primary, cost)
        reasons = _guard(metrics, max_flag_rate)
        d = metrics["detection"]
        paths.append({"path": path, "evaluation_split": split, "validation_metrics": metrics, "rejected_because": reasons,
                      "flag_rate": (d["tp"] + d["fp"]) / d["n"] if d["n"] else 0.0, "selectable": path != PATH_PRETRAINED})
        if chosen is not None or path == PATH_PRETRAINED:
            continue
        if not reasons:
            chosen = (path, model, val, split, metrics)
        elif path == PATH_CALIBRATED or len(candidates) == 1:  # the fallback is kept even when it fails the guard
            chosen = (path, model, val, split, metrics)
            banner.append(f"{path}: " + "; ".join(reasons) + " - used anyway (fallback path)")
        else:
            banner.append(f"{path}: " + "; ".join(reasons) + f" - falling back to '{PATH_CALIBRATED}'")
    path, model, val, split, metrics = chosen

    info = {
        "file": filename, "data_sha256": table.sha256, "n_parts": n_parts,
        "n_lots": int(table.n_lots), "n_parts_excluded_insufficient": int(table.df.loc[table.df["insufficient_data"], "component_id"].nunique()),
        "parameters": params, "primary_parameter": primary, "static_limit_override": static_limit,
        "label_source": label_source, "rule": {"id": RULE_ID, "text": RULE_TEXT},
        "path": path, "paths_tried": paths, "banner": banner, "max_flag_rate": max_flag_rate,
        "evaluation_split": split, "single_lot": single, "oof_metrics": metrics,
        "thresholds": {k: model.thresholds_.get(k) for k in ("threshold_a", "threshold_b", "source")},
        "cost_config": cost.as_dict(), "seed": seed, "trained_at": datetime.now(UTC).isoformat(),
    }
    return JudgeModel(model=model, info=info), val, truth


def truth_frame(df: pd.DataFrame, params: List[str], labels_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Per-part truth (flag, label, true 168h per parameter) from long readings that carry labels."""
    src = labels_df if labels_df is not None else df
    meta = src.drop_duplicates("component_id").set_index("component_id")
    t = pd.DataFrame({"ground_truth_flag": meta["ground_truth_flag"].astype(bool),
                      "ground_truth_label": meta["ground_truth_label"].astype(str)})
    t168 = df[df["interval_hours"] == 168].drop_duplicates("component_id").set_index("component_id")
    for p in params:
        t[f"true_{p}_168h"] = t168[p].reindex(t.index) if p in t168 else np.nan
    t.index = t.index.astype(str)
    t.index.name = "Part_ID"
    return t


def predict(jm: JudgeModel, table, static_limit: Optional[float] = None) -> tuple[pd.DataFrame, List[Dict[str, Any]]]:
    missing = [p for p in jm.info["parameters"] if p not in table.params]
    if missing:
        raise ValueError(f"the model was trained on {jm.info['parameters']}; this file lacks {missing}")
    primary = jm.info["primary_parameter"]
    limit = static_limit or jm.info.get("static_limit_override")
    limits = {primary: limit} if limit else None
    df = table.df
    bad = df.loc[df["insufficient_data"], "component_id"].unique()
    early = early_readings_only(df[~df["insufficient_data"]].drop(columns=["insufficient_data"]))
    early = early[[c for c in early.columns if c not in ("ground_truth_flag", "ground_truth_label")]]
    pred = jm.model.predict(early, limits=limits) if len(early) else None
    if pred is None:
        return export_frame(pd.DataFrame(columns=["component_id"]), primary, bad), []
    export = export_frame(pred, primary, bad)
    params = jm.info["parameters"]
    expl = {str(r["component_id"]): explanation(r, params) for _, r in pred.iterrows()}
    rows = []
    for rec in export.to_dict(orient="records"):
        rec = {k: (None if isinstance(v, float) and not np.isfinite(v) else v) for k, v in rec.items()}
        rec["explanation"] = expl.get(rec["Part_ID"])
        rows.append(rec)
    return export, rows
