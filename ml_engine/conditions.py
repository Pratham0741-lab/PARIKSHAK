"""
Burn-in test conditions as data: temperature, monitored parameter, unit and static limit.

Defaults (used only when a value is not supplied; every defaulted field is recorded as "assumed"):
  temperature_c  = 125.0 degC (the classic MIL-STD-883 TM1015 burn-in temperature)
  test_parameter = leakage_current_ua
  unit           = the canonical unit of the parameter (uA / mA / ns)
  static_limit   = the datasheet limit of the parameter (ScreeningVerdictEngine)

Arrhenius temperature dependence (JEDEC JEP122 style):
  AF(T) = exp( Ea / k_B * (1 / T_ref - 1 / T) ),  temperatures in kelvin.
Ea = 0.5 eV is a mid-range activation energy for leakage/defect-driven mechanisms; JEP122 lists
roughly 0.3-1.0 eV depending on the mechanism, so treat it as a documented modelling assumption.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

K_BOLTZMANN_EV = 8.617333262e-5
T_REF_C = 125.0
EA_LEAKAGE_EV = 0.5

CANONICAL_UNIT = {"leakage_current_ua": "uA", "iddq_ma": "mA", "propagation_delay_ns": "ns"}
PARAMETER_ALIASES = {
    "leakage": "leakage_current_ua", "leakage_current_ua": "leakage_current_ua", "ileak": "leakage_current_ua",
    "iddq": "iddq_ma", "iddq_ma": "iddq_ma", "idd": "iddq_ma",
    "delay": "propagation_delay_ns", "propagation_delay_ns": "propagation_delay_ns", "tpd": "propagation_delay_ns",
}


def datasheet_limit(parameter: str) -> float:
    from ml_engine.verdict_engine import ScreeningVerdictEngine

    return ScreeningVerdictEngine.datasheet_limits()[parameter]


def arrhenius_factor(temperature_c: float, t_ref_c: float = T_REF_C, ea_ev: float = EA_LEAKAGE_EV) -> float:
    """Rate/level multiplier at temperature_c relative to t_ref_c (1.0 at the reference)."""
    t, t_ref = temperature_c + 273.15, t_ref_c + 273.15
    return math.exp(ea_ev / K_BOLTZMANN_EV * (1.0 / t_ref - 1.0 / t))


def normalise_parameter(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    key = str(value).strip().lower().replace(" ", "_")
    if key not in PARAMETER_ALIASES:
        raise ValueError(f"unknown parameter {value!r}; expected one of leakage / iddq / delay")
    return PARAMETER_ALIASES[key]


def _missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "") or (isinstance(v, float) and math.isnan(v))


def resolve_conditions(supplied: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Fill missing condition fields with documented defaults; return (conditions, assumed_field_names)."""
    assumed: List[str] = []
    param = normalise_parameter(supplied.get("test_parameter"))
    if param is None:
        param = "leakage_current_ua"
        assumed.append("test_parameter")
    temp = supplied.get("temperature_c")
    if _missing(temp):
        temp = T_REF_C
        assumed.append("temperature_c")
    unit = supplied.get("unit")
    if _missing(unit):
        unit = CANONICAL_UNIT[param]
        assumed.append("unit")
    limit = supplied.get("static_limit")
    if _missing(limit):
        limit = datasheet_limit(param)
        assumed.append("static_limit")
    return {"temperature_c": float(temp), "test_parameter": param, "unit": str(unit), "static_limit": float(limit)}, assumed
