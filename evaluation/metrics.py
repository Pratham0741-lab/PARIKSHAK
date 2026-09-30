"""Detection and regression metrics computed strictly from predictions vs. ground truth."""

from __future__ import annotations

from typing import Dict

import numpy as np


def confusion(y_true, y_pred) -> Dict[str, int]:
    y = np.asarray(y_true, dtype=bool)
    p = np.asarray(y_pred, dtype=bool)
    return {
        "tp": int(np.sum(y & p)),
        "fp": int(np.sum(~y & p)),
        "fn": int(np.sum(y & ~p)),
        "tn": int(np.sum(~y & ~p)),
    }


def detection_metrics(y_true, y_pred) -> Dict[str, float]:
    cm = confusion(y_true, y_pred)
    tp, fp, fn, tn = cm["tp"], cm["fp"], cm["fn"], cm["tn"]
    recall = tp / (tp + fn) if tp + fn else 0.0
    precision = tp / (tp + fp) if tp + fp else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        **cm,
        "n": tp + fp + fn + tn,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "false_negative_rate": fn / (tp + fn) if tp + fn else 0.0,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
    }


def regression_metrics(y_true, y_pred) -> Dict[str, float]:
    t = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    mask = ~(np.isnan(t) | np.isnan(p))
    err = p[mask] - t[mask]
    return {
        "n": int(mask.sum()),
        "mae": float(np.mean(np.abs(err))) if mask.any() else float("nan"),
        "rmse": float(np.sqrt(np.mean(err**2))) if mask.any() else float("nan"),
    }
