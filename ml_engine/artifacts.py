"""
Portable model bundle (.pkl): one file that survives `docker compose down -v` and can be copied between machines.

File layout (pickle protocol 4):
    {"format": "parikshak-model-bundle", "bundle_checksum": sha256(payload_bytes), "payload_bytes": <pickled payload>}
The checksum is verified BEFORE the payload is unpickled, and both levels are read with a restricted unpickler
(numpy, pandas, sklearn, lightgbm, scipy, safe builtins and our own ml_engine/evaluation classes only).

Payload: format_version, created_at, library versions, the model (Module A calibration, Module B point + interval
models, feature list, parameters, units, thresholds, safety-slope k, cost, strategy), provenance (source file, SHA-256
of the training data, n parts, n lots, seed), metrics exactly as computed at training time (held-out, plus train
labelled "optimistic"), and a self-test (synthetic 0h/24h input + the outputs it must reproduce on load).
No labels, no raw training data and no 96h/168h-derived Module B features are stored.
"""

from __future__ import annotations

import copy
import hashlib
import io
import os
import pickle
import platform
import tempfile
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

FORMAT = "parikshak-model-bundle"
FORMAT_VERSION = 1
PROTOCOL = 4
LATEST = "latest.pkl"

_ALLOWED_PREFIXES = ("numpy", "pandas", "sklearn", "lightgbm", "scipy", "ml_engine.", "evaluation.")
_ALLOWED_EXACT = {
    ("builtins", n) for n in ("dict", "list", "set", "frozenset", "tuple", "bytes", "bytearray", "str", "int", "float",
                              "complex", "bool", "slice", "range", "object", "NoneType")
} | {("copyreg", "_reconstructor"), ("collections", "OrderedDict"), ("collections", "defaultdict"),
     ("datetime", "datetime"), ("datetime", "timezone"), ("datetime", "timedelta"), ("functools", "partial")}


class BundleError(ValueError):
    pass


class _RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if (module, name) in _ALLOWED_EXACT or module.startswith(_ALLOWED_PREFIXES) or module in ("numpy", "pandas", "scipy"):
            return super().find_class(module, name)
        raise BundleError(f"refused to load {module}.{name}: not an allowed class in a model bundle")


def restricted_loads(data: bytes) -> Any:
    return _RestrictedUnpickler(io.BytesIO(data)).load()


def library_versions() -> Dict[str, str]:
    import lightgbm
    import scipy
    import sklearn

    return {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
            "scikit-learn": sklearn.__version__, "lightgbm": lightgbm.__version__, "scipy": scipy.__version__}


def _strip(model):
    """Copy of the ScreeningModel without labels or training-row identities (validation scores carry labels)."""
    from ml_engine.features import assert_no_future_features

    m = copy.copy(model)
    m.validation_ = None
    m.training_component_ids_ = frozenset()
    m.training_lot_ids_ = frozenset()
    assert_no_future_features(m.module_b.feature_columns_)
    return m


def _selftest_input(params: List[str]) -> pd.DataFrame:
    """Small synthetic 0h/24h lot (not training data) used to prove the loaded model predicts identically."""
    from data_engine.physics_generator import PhysicsBurnInGenerator

    df = PhysicsBurnInGenerator(num_lots=1, components_per_lot=12, random_seed=0).generate_dataset()
    df = df[df["interval_hours"].isin([0, 24])]
    return df[["component_id", "lot_id", "interval_hours", *params]].reset_index(drop=True)


_SELFTEST_COLS = ("module_a_score", "module_b_score", "pred_leakage_168h", "pred_iddq_168h", "pred_delay_168h", "verdict")


def _selftest_output(model, x: pd.DataFrame) -> pd.DataFrame:
    p = model.predict(x)
    return p[["component_id", *[c for c in _SELFTEST_COLS if c in p.columns]]].sort_values("component_id").reset_index(drop=True)


def build_payload(model, info: Dict[str, Any]) -> Dict[str, Any]:
    from ml_engine.conditions import CANONICAL_UNIT

    m = _strip(model)
    params = list(info.get("parameters") or m.module_b.params_)
    x = _selftest_input(params)
    created = datetime.now(UTC).isoformat()
    bundle_id = hashlib.sha256(f"{info.get('data_sha256', '')}{created}".encode()).hexdigest()[:12]
    return {
        "format_version": FORMAT_VERSION,
        "bundle_id": bundle_id,
        "created_at": created,
        "library_versions": library_versions(),
        "model": m,
        "model_summary": {
            "parameters": params, "units": {p: CANONICAL_UNIT[p] for p in params},
            "module_b_features": list(m.module_b.feature_columns_), "module_b_config": {
                "feature_set": m.module_b.feature_set, "target": m.module_b.target, "lgb_params": m.module_b.lgb_params},
            "module_a_params": list(getattr(m.module_a, "params_", params)),
            "interval": m.conformal_,
        },
        "decision": {"threshold_a": m.thresholds_.get("threshold_a"), "safety_slope_k": m.thresholds_.get("threshold_b"),
                     "cost": m.cost.as_dict(), "strategy": m.threshold_strategy,
                     "threshold_source": m.thresholds_.get("source"), "spread_floors": m.spread_floors_},
        "provenance": {"source_file": info.get("file"), "data_sha256": info.get("data_sha256"),
                       "n_parts": info.get("n_parts"), "n_lots": info.get("n_lots"), "seed": info.get("seed")},
        "metrics": {"held_out": info.get("oof_metrics"), "held_out_split": info.get("evaluation_split"),
                    "train_optimistic": info.get("train_optimistic")},
        "info": info,  # the judge-mode info dict as produced at training time (shown unchanged after import)
        "selftest": {"input": x, "expected": _selftest_output(m, x)},
    }


def save_bundle(model, info: Dict[str, Any], path: Path) -> Dict[str, Any]:
    """Atomic write: temp file in the same directory, fsync, then rename."""
    payload = build_payload(model, info)
    payload_bytes = pickle.dumps(payload, protocol=PROTOCOL)
    outer = {"format": FORMAT, "bundle_checksum": hashlib.sha256(payload_bytes).hexdigest(), "payload_bytes": payload_bytes}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".pkl")
    try:
        with os.fdopen(fd, "wb") as fh:
            pickle.dump(outer, fh, protocol=PROTOCOL)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"path": str(path), "bundle_id": payload["bundle_id"], "bundle_checksum": outer["bundle_checksum"]}


def load_bundle(source) -> Tuple[Any, Dict[str, Any], List[str]]:
    """Returns (model, payload without the model, warnings). Raises BundleError with a clear reason on any failure."""
    if isinstance(source, str | Path) and not Path(source).is_file():
        raise BundleError(f"no bundle at {source}")
    data = Path(source).read_bytes() if isinstance(source, str | Path) else bytes(source)
    try:
        outer = restricted_loads(data)
    except BundleError:
        raise
    except Exception as exc:
        raise BundleError(f"not a model bundle (unreadable pickle: {type(exc).__name__})") from exc
    if not isinstance(outer, dict) or outer.get("format") != FORMAT or "payload_bytes" not in outer:
        raise BundleError("not a PARIKSHAK model bundle")
    payload_bytes = outer["payload_bytes"]
    if hashlib.sha256(payload_bytes).hexdigest() != outer.get("bundle_checksum"):
        raise BundleError("checksum mismatch: the bundle is corrupted or was modified")
    payload = restricted_loads(payload_bytes)
    if payload.get("format_version") != FORMAT_VERSION:
        raise BundleError(f"unsupported format_version {payload.get('format_version')} (this build reads {FORMAT_VERSION})")
    notes = []
    current = library_versions()
    for lib, v in (payload.get("library_versions") or {}).items():
        if lib != "python" and current.get(lib) != v:
            notes.append(f"{lib} {v} at training, {current.get(lib)} here")
    for n in notes:
        warnings.warn(f"model bundle library-version mismatch: {n}", stacklevel=2)
    model = payload["model"]
    st = payload["selftest"]
    try:
        got = _selftest_output(model, st["input"])
        pd.testing.assert_frame_equal(got, st["expected"], check_exact=False, rtol=1e-9, atol=1e-9)
    except Exception as exc:
        raise BundleError(f"self-test prediction failed after loading: {exc}") from exc
    meta = {k: v for k, v in payload.items() if k not in ("model", "selftest")}
    meta["bundle_checksum"] = outer["bundle_checksum"]
    meta["version_mismatch"] = notes
    return model, meta, notes


def describe(meta: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    pv = meta.get("provenance") or {}
    return {"bundle_id": meta.get("bundle_id"), "file": path.name if path else None, "created_at": meta.get("created_at"),
            "source_file": pv.get("source_file"), "data_sha256": pv.get("data_sha256"), "n_parts": pv.get("n_parts"),
            "n_lots": pv.get("n_lots"), "library_versions": meta.get("library_versions"),
            "version_mismatch": meta.get("version_mismatch", []), "bundle_checksum": meta.get("bundle_checksum")}
