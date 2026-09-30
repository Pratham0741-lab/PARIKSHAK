"""
Asymmetric-cost scoring for burn-in screening.

A missed defective part (false negative) can reach flight hardware; a false positive costs
only an extra QA inspection or a re-test. The default therefore weights an escape 20x a false
alarm (FN_COST = 20, FP_COST = 1, in "QA-inspection equivalents"). Both are configurable via
the FN_COST / FP_COST / RECALL_TARGET settings (environment or .env) and via CLI flags.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

from evaluation.metrics import detection_metrics

DEFAULT_FN_COST = 20.0
DEFAULT_FP_COST = 1.0


@dataclass(frozen=True)
class CostConfig:
    fn_cost: float = DEFAULT_FN_COST
    fp_cost: float = DEFAULT_FP_COST
    recall_target: Optional[float] = None  # optional hard constraint used during threshold selection

    def __post_init__(self):
        if self.fn_cost < 0 or self.fp_cost < 0:
            raise ValueError("costs must be non-negative")
        if self.recall_target is not None and not 0.0 < self.recall_target <= 1.0:
            raise ValueError("recall_target must be in (0, 1]")

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_settings(cls, **overrides) -> "CostConfig":
        from backend.app.core.config import settings

        base = {"fn_cost": settings.FN_COST, "fp_cost": settings.FP_COST, "recall_target": settings.RECALL_TARGET}
        base.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**base)


def f_beta(precision: float, recall: float, beta: float = 2.0) -> float:
    b2 = beta * beta
    denom = b2 * precision + recall
    return (1 + b2) * precision * recall / denom if denom > 0 else 0.0


def weighted_cost(fn: int, fp: int, cfg: CostConfig) -> float:
    return cfg.fn_cost * fn + cfg.fp_cost * fp


def cost_report(y_true, y_pred, cfg: CostConfig) -> Dict[str, Any]:
    """Confusion matrix, recall, precision, F2 and FN-weighted cost for a set of decisions."""
    d = detection_metrics(y_true, y_pred)
    total = weighted_cost(d["fn"], d["fp"], cfg)
    return {
        **d,
        "f2": f_beta(d["precision"], d["recall"], 2.0),
        "weighted_cost": total,
        "cost_per_1000_parts": 1000.0 * total / d["n"] if d["n"] else 0.0,
        "cost_config": cfg.as_dict(),
    }
