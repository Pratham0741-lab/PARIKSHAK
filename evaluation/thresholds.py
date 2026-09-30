"""
Decision-threshold selection by expected-cost minimisation on VALIDATION predictions.

Validation predictions must be out-of-fold (see ScreeningModel.fit, which produces them with
an inner lot-grouped CV over the training lots). Held-out evaluation lots are never used here.

The screening decision is the union
    flag = forced | (score_a >= t_a) | (score_b >= t_b)
where `forced` are specification rules (a datasheet limit already breached, or forecast to be
breached at 168h). Candidate thresholds are the observed score values plus +inf (module off);
the pair minimising FN_COST*FN + FP_COST*FP is chosen, subject to recall >= recall_target if set.
Ties break toward fewer FNs, then fewer FPs, then higher thresholds (fewer flags), so the
selection is deterministic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from evaluation.cost import CostConfig, f_beta

INF = float("inf")


def _candidates(scores: np.ndarray, max_candidates: int = 200) -> np.ndarray:
    s = np.unique(np.asarray(scores, dtype=float)[np.isfinite(scores)])
    if len(s) > max_candidates:
        s = np.unique(np.quantile(s, np.linspace(0.0, 1.0, max_candidates)))
    return np.concatenate([s, [INF]])


def _pick(costs, fns, fps, recalls, cfg: CostConfig, ta, tb) -> int:
    """Index of the best candidate under cost, the optional recall constraint and tie-breaks."""
    idx = np.arange(len(costs))
    if cfg.recall_target is not None:
        ok = recalls >= cfg.recall_target - 1e-12
        if ok.any():
            idx = idx[ok]
        else:  # constraint unreachable: take the highest achievable recall, then cost
            idx = idx[recalls == recalls.max()]
    order = np.lexsort((-tb[idx], -ta[idx], fps[idx], fns[idx], costs[idx]))
    return int(idx[order[0]])


def choose_union_thresholds(
    score_a: Sequence[float],
    score_b: Sequence[float],
    y_true: Sequence[bool],
    cfg: CostConfig,
    forced: Optional[Sequence[bool]] = None,
    candidates_a: Optional[np.ndarray] = None,
    candidates_b: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    a = np.asarray(score_a, dtype=float)
    b = np.asarray(score_b, dtype=float)
    y = np.asarray(y_true, dtype=bool)
    f = np.zeros_like(y) if forced is None else np.asarray(forced, dtype=bool)
    ca = _candidates(a) if candidates_a is None else np.asarray(candidates_a, dtype=float)
    cb = _candidates(b) if candidates_b is None else np.asarray(candidates_b, dtype=float)

    flags_b = b[:, None] >= cb[None, :]                      # n x |cb|
    pos = y.sum()
    rows = []
    for t in ca:
        flag = (f | (a >= t))[:, None] | flags_b              # n x |cb|
        tp = (flag & y[:, None]).sum(axis=0)
        fp = (flag & ~y[:, None]).sum(axis=0)
        rows.append((np.full(len(cb), t), cb, tp, fp))
    ta = np.concatenate([r[0] for r in rows])
    tb = np.concatenate([r[1] for r in rows])
    tp = np.concatenate([r[2] for r in rows])
    fp = np.concatenate([r[3] for r in rows])
    fn = pos - tp
    costs = cfg.fn_cost * fn + cfg.fp_cost * fp
    recalls = tp / pos if pos else np.ones_like(tp, dtype=float)
    ta_s = np.where(np.isinf(ta), 1e300, ta)
    tb_s = np.where(np.isinf(tb), 1e300, tb)
    i = _pick(costs, fn, fp, recalls, cfg, ta_s, tb_s)
    precision = tp[i] / (tp[i] + fp[i]) if tp[i] + fp[i] else 0.0
    return {
        "threshold_a": float(ta[i]),
        "threshold_b": float(tb[i]),
        "validation": {
            "n": int(len(y)),
            "tp": int(tp[i]), "fp": int(fp[i]), "fn": int(fn[i]), "tn": int(len(y) - pos - fp[i]),
            "recall": float(recalls[i]),
            "precision": float(precision),
            "f2": f_beta(float(precision), float(recalls[i])),
            "weighted_cost": float(costs[i]),
        },
        "cost_config": cfg.as_dict(),
    }


def choose_threshold(scores: Sequence[float], y_true: Sequence[bool], cfg: CostConfig,
                     forced: Optional[Sequence[bool]] = None) -> Dict[str, Any]:
    """Single-score version (flag = forced | score >= t)."""
    s = np.asarray(scores, dtype=float)
    res = choose_union_thresholds(s, np.full(len(s), -INF), y_true, cfg, forced,
                                  candidates_b=np.array([INF]))
    return {"threshold": res["threshold_a"], "validation": res["validation"], "cost_config": res["cost_config"]}


def cost_curve(
    score_sweep: Sequence[float],
    score_fixed: Sequence[float],
    threshold_fixed: float,
    y_true: Sequence[bool],
    cfg: CostConfig,
    forced: Optional[Sequence[bool]] = None,
    n_points: int = 40,
) -> List[Dict[str, float]]:
    """Cost / FN / FP / recall / precision / F2 as one module's threshold is swept, the other held fixed."""
    s = np.asarray(score_sweep, dtype=float)
    other = np.asarray(score_fixed, dtype=float) >= threshold_fixed
    y = np.asarray(y_true, dtype=bool)
    f = np.zeros_like(y) if forced is None else np.asarray(forced, dtype=bool)
    finite = s[np.isfinite(s)]
    grid = np.unique(np.quantile(finite, np.linspace(0, 1, n_points))) if len(finite) else np.array([])
    out = []
    for t in grid:
        flag = f | other | (s >= t)
        tp = int((flag & y).sum()); fp = int((flag & ~y).sum()); fn = int((~flag & y).sum())
        rec = tp / (tp + fn) if tp + fn else 0.0
        prec = tp / (tp + fp) if tp + fp else 0.0
        out.append({"threshold": float(t), "weighted_cost": cfg.fn_cost * fn + cfg.fp_cost * fp,
                    "fn": fn, "fp": fp, "recall": rec, "precision": prec, "f2": f_beta(prec, rec)})
    return out
