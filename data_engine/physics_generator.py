"""
Physics-based synthetic burn-in generator ("physics"). The previous generator remains available
as "legacy" (data_engine/generator.py); select with `--generator legacy|physics`.

Model (all random draws come from one seeded numpy Generator):

Lots
  * Burn-in temperature T per lot drawn from TEMPERATURES_C.
  * Baseline leakage median L_lot = L_REF * S_lot * AF(T), with lot-to-lot shift S_lot ~ LogNormal(0, 0.30)
    and Arrhenius factor AF(T) = exp(Ea/k (1/T_ref - 1/T)), Ea = 0.5 eV, T_ref = 125 degC
    (ml_engine/conditions.py). IDDQ and delay lot medians get their own log-normal shifts.
Parts
  * Leakage v0 ~ LogNormal(ln L_lot, 0.12) (log-normal: leakage is exponential in threshold voltage,
    which varies roughly normally across a lot). IDDQ is correlated with leakage (rho ~ 0.6), delay
    is log-normal with a small spread.
Time dependence (power law)
  * Nominal degradation v(t) = v0 * (1 + A * (t/168)^n), n ~ U(0.25, 0.60), A ~ LogNormal(ln 0.03, 0.5) * AF(T).
    Power-law time dependence with sub-linear exponents is the standard empirical form for gate-oxide
    / BTI-type wear-out and stress-induced leakage (JEDEC JEP122 describes power-law and Arrhenius
    models; Schroder & Babcock, J. Appl. Phys. 94, 1 (2003) review BTI exponents of roughly 0.1-0.3;
    stress-induced leakage growth is commonly fitted with exponents around 0.3-0.6). The range used
    here is a modelling assumption spanning those regimes, not a fit to a specific device.
Measurement noise (heteroscedastic)
  * sigma = abs + rel * value (leakage 0.05 uA + 2 %, IDDQ 0.005 mA + 1.5 %, delay 0.01 ns + 0.5 %).
Defects (ground truth; the label is used only for evaluation and threshold calibration)
  * LEVEL_OUTLIER (2 %): baseline x U(2.0, 3.5) at t=0, nominal drift afterwards.
  * SUBTLE_MULTIVARIATE (2 %): simultaneous +1.5..2.5 lot-sigma shift on all three parameters.
  * Latent accelerated drift (5 %): extra term B * ((t - t_on)/(168 - t_on))^m for t > t_on,
    m ~ U(1.0, 2.0) (accelerating), with the 168h value drawn in [0.45, 0.95] x static limit and every
    reading kept strictly BELOW the static limit. Onset t_on from a documented mixture:
        40 % t_on = 0          -> clear signal by 24h            (signal_24h = "clear")
        25 % t_on ~ U(0, 24)   -> weak signal by 24h             (signal_24h = "partial")
        35 % t_on ~ U(30, 120) -> nothing visible by 24h         (signal_24h = "none")
    Labels: STEEP_DRIFT if t_on < 24h, else LATE_DRIFT.
  * Gross drift (1 %): as above but the 168h value exceeds the static limit (STEEP_DRIFT, breached).
"""

from __future__ import annotations

import datetime
import math
import uuid
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ml_engine.conditions import arrhenius_factor

PARAMS = ("leakage_current_ua", "iddq_ma", "propagation_delay_ns")
INTERVALS = (0, 24, 96, 168)
TEMPERATURES_C = (85.0, 105.0, 125.0, 150.0)
LIMITS = {"leakage_current_ua": 50.0, "iddq_ma": 5.0, "propagation_delay_ns": 8.0}
NOISE = {"leakage_current_ua": (0.05, 0.02), "iddq_ma": (0.005, 0.015), "propagation_delay_ns": (0.01, 0.005)}
L_REF_UA, IDDQ_REF_MA, DELAY_REF_NS = 10.0, 1.5, 4.2
DEFECT_RATES = {"LEVEL_OUTLIER": 0.02, "SUBTLE_MULTIVARIATE": 0.02, "LATENT": 0.05, "GROSS": 0.01}
ONSET_MIX = (("clear", 0.40), ("partial", 0.25), ("none", 0.35))


class PhysicsBurnInGenerator:
    GENERATOR_NAME = "physics"

    def __init__(self, num_lots: int = 40, components_per_lot: int = 100, random_seed: Optional[int] = 42,
                 leakage_max_ua: float = LIMITS["leakage_current_ua"], **_ignored: Any) -> None:
        self.num_lots = num_lots
        self.components_per_lot = components_per_lot
        self.random_seed = random_seed
        self.leakage_max_ua = leakage_max_ua
        self.rng = np.random.default_rng(random_seed)
        self._ns = uuid.uuid5(uuid.NAMESPACE_OID, f"sih26170-physics-seed-{random_seed}") if random_seed is not None else None

    def _id(self, key: str) -> uuid.UUID:
        return uuid.uuid4() if self._ns is None else uuid.uuid5(self._ns, key)

    def _noisy(self, p: str, v: float) -> float:
        a, r = NOISE[p]
        return float(max(1e-4, v + self.rng.normal(0.0, a + r * abs(v))))

    # ------------------------------------------------------------------ lots and parts
    def _lots(self) -> List[Dict[str, Any]]:
        lots = []
        for i in range(self.num_lots):
            temp = float(self.rng.choice(TEMPERATURES_C))
            shift = float(np.exp(self.rng.normal(0.0, 0.30)))
            lots.append({
                "lot_number": f"LOT-P{self.random_seed}-{i + 1:03d}",
                "wafer_id": f"WAF-P-{(i % 25) + 1:02d}{chr(65 + i % 6)}",
                "temperature_c": temp,
                "leak_med": L_REF_UA * shift * arrhenius_factor(temp),
                "iddq_med": IDDQ_REF_MA * float(np.exp(self.rng.normal(0.0, 0.08))) * arrhenius_factor(temp, ea_ev=0.2),
                "delay_med": DELAY_REF_NS * float(np.exp(self.rng.normal(0.0, 0.04))),
                "af": arrhenius_factor(temp),
                "high_baseline": shift > float(np.exp(0.30)),  # > +1 sigma lot-to-lot shift
            })
        return lots

    def _labels(self) -> List[str]:
        n = self.components_per_lot
        out: List[str] = []
        for k, r in DEFECT_RATES.items():
            out += [k] * int(self.rng.binomial(n, r))
        out = out[:n] + ["NORMAL"] * max(0, n - len(out))
        return [out[i] for i in self.rng.permutation(n)]

    def _part(self, lot: Dict[str, Any], kind: str) -> Dict[str, Any]:
        z = self.rng.normal(size=3)
        v0 = {
            "leakage_current_ua": lot["leak_med"] * math.exp(0.12 * z[0]),
            "iddq_ma": lot["iddq_med"] * math.exp(0.05 * (0.6 * z[0] + 0.8 * z[1])),
            "propagation_delay_ns": lot["delay_med"] * math.exp(0.025 * z[2]),
        }
        n = float(self.rng.uniform(0.25, 0.60))
        amp = {p: float(np.exp(self.rng.normal(math.log(0.03), 0.5))) * lot["af"] for p in PARAMS}
        amp["propagation_delay_ns"] *= 0.2
        label, signal, onset = "NORMAL", None, None
        extra = {p: (lambda t: 0.0) for p in PARAMS}

        if kind == "LEVEL_OUTLIER":
            label = "LEVEL_OUTLIER"
            v0["leakage_current_ua"] = min(v0["leakage_current_ua"] * float(self.rng.uniform(2.0, 3.5)),
                                           0.8 * self.leakage_max_ua)
        elif kind == "SUBTLE_MULTIVARIATE":
            label = "SUBTLE_MULTIVARIATE"
            k = float(self.rng.uniform(1.5, 2.5))
            v0["leakage_current_ua"] *= math.exp(0.12 * k)
            v0["iddq_ma"] *= math.exp(0.05 * k)
            v0["propagation_delay_ns"] *= math.exp(0.025 * k)
        elif kind in ("LATENT", "GROSS"):
            u = float(self.rng.random())
            signal = "clear" if u < ONSET_MIX[0][1] else "partial" if u < ONSET_MIX[0][1] + ONSET_MIX[1][1] else "none"
            onset = 0.0 if signal == "clear" else float(self.rng.uniform(0, 24)) if signal == "partial" else float(self.rng.uniform(30, 120))
            label = "STEEP_DRIFT" if onset < 24 else "LATE_DRIFT"
            m = float(self.rng.uniform(1.0, 2.0))
            if kind == "GROSS":
                target = self.leakage_max_ua * float(self.rng.uniform(1.05, 1.3))
                label = "STEEP_DRIFT"
            else:
                target = self.leakage_max_ua * float(self.rng.uniform(0.45, 0.95))
            base168 = v0["leakage_current_ua"] * (1 + amp["leakage_current_ua"])
            b = max(target - base168, 0.5 * v0["leakage_current_ua"])
            shape = lambda t, on=onset, mm=m: 0.0 if t <= on else ((t - on) / (168.0 - on)) ** mm  # noqa: E731
            extra["leakage_current_ua"] = lambda t, bb=b, sh=shape: bb * sh(t)
            extra["iddq_ma"] = lambda t, bb=b, sh=shape, l0=v0["leakage_current_ua"], i0=v0["iddq_ma"]: 0.3 * i0 * (bb / l0) * sh(t)
        return {"v0": v0, "n": n, "amp": amp, "extra": extra, "label": label, "signal": signal, "onset": onset,
                "gross": kind == "GROSS"}

    def _trajectory(self, part: Dict[str, Any]) -> Dict[int, Dict[str, float]]:
        for _ in range(50):
            out = {}
            for t in INTERVALS:
                out[t] = {}
                for p in PARAMS:
                    true = part["v0"][p] * (1 + part["amp"][p] * (t / 168.0) ** part["n"]) + part["extra"][p](t)
                    out[t][p] = self._noisy(p, true)
            if part["gross"] or part["label"] == "NORMAL" or all(
                    out[t]["leakage_current_ua"] < self.leakage_max_ua for t in INTERVALS):
                return out
        # latent parts must pass the static limit at every time point: clip the true curve if noise keeps crossing
        for t in INTERVALS:
            out[t]["leakage_current_ua"] = min(out[t]["leakage_current_ua"], 0.99 * self.leakage_max_ua)
        return out

    # ------------------------------------------------------------------ outputs
    def lot_conditions(self, lot: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "temperature_c": lot["temperature_c"], "test_parameter": "leakage_current_ua", "unit": "uA",
            "static_limit": self.leakage_max_ua, "conditions_assumed": [],
            "source_detail": {"kind": "SYNTHETIC", "generator": self.GENERATOR_NAME, "seed": self.random_seed},
        }

    def _generate(self):
        base_ts = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)
        for lot in self._lots():
            lot_id = self._id(f"lot-{lot['lot_number']}")
            parts = []
            for j, kind in enumerate(self._labels(), start=1):
                part = self._part(lot, kind)
                sn = f"{lot['lot_number']}-SN{j:04d}"
                traj = self._trajectory(part)
                breached = any(traj[t][p] > LIMITS[p] for t in INTERVALS for p in PARAMS)
                parts.append((self._id(f"component-{sn}"), sn, part, traj, breached))
            yield lot, lot_id, parts, base_ts

    def generate_dataset(self) -> pd.DataFrame:
        rows = []
        for lot, lot_id, parts, ts in self._generate():
            for cid, sn, part, traj, breached in parts:
                for t in INTERVALS:
                    rows.append({
                        "lot_id": str(lot_id), "lot_number": lot["lot_number"], "wafer_id": lot["wafer_id"],
                        "is_benign_high_lot": lot["high_baseline"], "temperature_c": lot["temperature_c"],
                        "component_id": str(cid), "serial_number": sn, "interval_hours": t,
                        **{p: round(traj[t][p], 4) for p in PARAMS},
                        "ground_truth_label": part["label"], "ground_truth_flag": part["label"] != "NORMAL",
                        "is_datasheet_breached": breached, "latent_signal_24h": part["signal"],
                        "recorded_at": ts + datetime.timedelta(hours=t),
                    })
        return pd.DataFrame(rows)

    def generate_records(self) -> Dict[str, List[Dict[str, Any]]]:
        lots, comps, reads = [], [], []
        for lot, lot_id, parts, ts in self._generate():
            lots.append({"id": lot_id, "lot_number": lot["lot_number"], "wafer_id": lot["wafer_id"],
                         "status": "INGESTED", "created_at": ts, **self.lot_conditions(lot)})
            for cid, sn, part, traj, breached in parts:
                comps.append({"id": cid, "lot_id": lot_id, "serial_number": sn, "ground_truth_label": part["label"],
                              "ground_truth_flag": part["label"] != "NORMAL", "is_datasheet_breached": breached})
                for t in INTERVALS:
                    reads.append({"id": self._id(f"reading-{sn}-{t}"), "component_id": cid, "interval_hours": t,
                                  **{p: round(traj[t][p], 4) for p in PARAMS}, "recorded_at": ts + datetime.timedelta(hours=t)})
        return {"lots": lots, "components": comps, "readings": reads}


def make_generator(name: str, **kwargs):
    """'physics' (default) or 'legacy'."""
    if name == "physics":
        return PhysicsBurnInGenerator(**kwargs)
    if name == "legacy":
        from data_engine.generator import BurnInSyntheticGenerator

        return BurnInSyntheticGenerator(**kwargs)
    raise ValueError(f"unknown generator {name!r}; expected physics or legacy")
